"""Recognize a closed expected-exception oracle replaced by a null result.

The sentinel in `try: subject(); assert False / except ValueError: pass`
is not a standalone tautology. The whole try statement expects an exception.
This bounded two-sided extraction records the existing unknown-strength
`raises` form so ordinary assertion-removal policy can see its disappearance.
It grants no equivalence to another assertion and changes no lattice value.
"""
import ast
import copy
from dataclasses import replace

from checkwash.frontends.python.oracle_purity import _literal, primitive_literal_result, pure_imported_calls
from checkwash.frontends.python.snapshot_context import inert_test_execution_context
from checkwash.frontends.python.table_oracles import (_args, _bounded_tree, _context_snapshots,
                                                    _pytest_unshadowed, _Substitute,
                                                    _CONTROL_NAMES, _IMPLICIT_HOOKS)
from checkwash.frontends.python.frontend import _Offsets, normalize_source, parse_python
from checkwash.ir.astutil import stable_dump

_EXCEPTIONS = {'ZeroDivisionError', 'ValueError', 'TypeError', 'IndexError', 'KeyError', 'OverflowError'}


def _module(data):
    if len(data) > 65536:
        return None
    try:
        tree = ast.parse(data)
    except (SyntaxError, ValueError, TypeError, MemoryError, RecursionError):
        return None
    if sum(1 for _ in ast.walk(tree)) > 4096:
        return None
    body = [node for node in tree.body if not (isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant) and type(node.value.value) is str)]
    if len(body) != 2 or not isinstance(body[0], ast.ImportFrom) or not isinstance(body[1], ast.FunctionDef):
        return None
    imported, function = body
    args = function.args
    if (imported.level or not imported.module or len(imported.names) != 1 or imported.names[0].name == '*'
            or function.decorator_list or not function.name.startswith('test') or function.returns
            or getattr(function, 'type_params', ()) or args.args or args.posonlyargs or args.kwonlyargs
            or args.defaults or args.vararg or args.kwarg):
        return None
    name = imported.names[0].asname or imported.names[0].name
    if (name in _EXCEPTIONS | _CONTROL_NAMES | _IMPLICIT_HOOKS
            or name.startswith(('__', 'pytest_')) or function.name == name):
        return None
    return imported, function, name


def _after_module(data):
    """Inline one closed literal fixture or a sole assertion-helper call.

    This only establishes that the old production call is still reached in
    the edited suite. It does not equate a returned null with an exception.
    """
    direct = _module(data)
    if direct is not None:
        return direct
    tree = _bounded_tree(data)
    if tree is None:
        return None
    body = [node for node in tree.body if not (isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant) and type(node.value.value) is str)]
    imported, functions, occupied, pytest = None, [], set(), False
    for node in body:
        if (isinstance(node, ast.Import) and not functions and not pytest and len(node.names) == 1
                and node.names[0].name == 'pytest' and node.names[0].asname is None):
            names = ['pytest']
            pytest = True
        elif (isinstance(node, ast.ImportFrom) and not functions and imported is None
              and not node.level and node.module and len(node.names) == 1 and node.names[0].name != '*'):
            imported = node
            names = [node.names[0].asname or node.names[0].name]
        elif isinstance(node, ast.FunctionDef) and _args(node) is not None:
            names = [node.name]
            functions.append(node)
        else:
            return None
        if (set(names) & occupied or any((name in _EXCEPTIONS | _CONTROL_NAMES | _IMPLICIT_HOOKS
                or name.startswith(('__', 'pytest_')))
                and not (name == 'pytest' and isinstance(node, ast.Import)) for name in names)):
            return None
        occupied.update(names)
    if imported is None or len(functions) != 2:
        return None
    helper, function = functions
    if (helper.name.startswith('test') or not function.name.startswith('test') or function.decorator_list
            or helper.name in {'setup_module', 'teardown_module', 'setup_function', 'teardown_function'}):
        return None
    helper_args, test_args = _args(helper), _args(function)
    if len(helper_args) != len(set(helper_args)) or set(helper_args) & occupied:
        return None
    normalized = copy.deepcopy(function)
    if helper.decorator_list:
        if (not pytest or helper_args or test_args != [helper.name] or len(helper.decorator_list) != 1
                or ast.unparse(helper.decorator_list[0]) != 'pytest.fixture'
                or len(helper.body) != 1 or not isinstance(helper.body[0], ast.Return)
                or not isinstance(helper.body[0].value, ast.Constant) or helper.body[0].value.value is not None):
            return None
        normalized.body = _Substitute({helper.name: ast.Constant(value=None)}).visit(
            ast.Module(body=normalized.body, type_ignores=[])).body
    else:
        if pytest or test_args or len(function.body) != 1 or not isinstance(function.body[0], ast.Expr):
            return None
        invocation = function.body[0].value
        if (not isinstance(invocation, ast.Call) or not isinstance(invocation.func, ast.Name)
                or invocation.func.id != helper.name or invocation.keywords
                or len(invocation.args) != len(helper_args) or not all(_literal(arg) for arg in invocation.args)):
            return None
        if any(isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del))
               and node.id in set(helper_args) | occupied for statement in helper.body for node in ast.walk(statement)):
            return None
        normalized.body = _Substitute(dict(zip(helper_args, invocation.args))).visit(
            ast.Module(body=copy.deepcopy(helper.body), type_ignores=[])).body
    return imported, normalized, imported.names[0].asname or imported.names[0].name


def _inert_message(node, capture):
    if node is None or isinstance(node, ast.Constant) and type(node.value) is str:
        return True
    if not isinstance(node, ast.JoinedStr):
        return False
    for part in node.values:
        if isinstance(part, ast.Constant) and type(part.value) is str:
            continue
        if (not isinstance(part, ast.FormattedValue) or part.format_spec is not None
                or part.conversion not in (-1, 97, 114, 115)
                or not (isinstance(part.value, ast.Constant)
                        or isinstance(part.value, ast.Name) and part.value.id == capture)):
            return False
    return True


def mark_classic_exception_removal(before, after, before_parsed, after_parsed, *, path,
                                   root_reader=None, root_searcher=None, changes=()):
    if (root_reader is None or root_searcher is None or b'except' not in before
            or not before_parsed.parse_ok or not after_parsed.parse_ok):
        return before_parsed, after_parsed
    old, new = _module(before), _after_module(after)
    if (old is None or new is None or stable_dump(old[0]) != stable_dump(new[0])
            or old[1].name != new[1].name or len(old[1].body) != 1):
        return before_parsed, after_parsed
    expected = old[1].body[0]
    if (not isinstance(expected, ast.Try) or expected.orelse or expected.finalbody
            or len(expected.body) != 2 or len(expected.handlers) != 1):
        return before_parsed, after_parsed
    invoked, sentinel = expected.body
    handler = expected.handlers[0]
    if (not isinstance(invoked, ast.Expr) or not isinstance(invoked.value, ast.Call)
            or not isinstance(invoked.value.func, ast.Name) or invoked.value.func.id != old[2]
            or not isinstance(sentinel, ast.Assert) or not isinstance(sentinel.test, ast.Constant)
            or sentinel.test.value is not False
            or sentinel.msg is not None and not (isinstance(sentinel.msg, ast.Constant) and type(sentinel.msg.value) is str)
            or handler.name is not None or not isinstance(handler.type, ast.Name) or handler.type.id not in _EXCEPTIONS
            or len(handler.body) != 1 or not isinstance(handler.body[0], ast.Pass)):
        return before_parsed, after_parsed
    body, call = new[1].body, invoked.value
    if (not all(_literal(arg) for arg in call.args)
            or any(keyword.arg is None or not _literal(keyword.value) for keyword in call.keywords)):
        return before_parsed, after_parsed
    capture = None
    if len(body) == 2 and isinstance(body[0], ast.Assign) and len(body[0].targets) == 1:
        assignment, check = body
        if (not isinstance(assignment.targets[0], ast.Name) or assignment.targets[0].id == new[2]
                or stable_dump(assignment.value) != stable_dump(call)):
            return before_parsed, after_parsed
        subject = ast.Name(id=assignment.targets[0].id, ctx=ast.Load())
        capture = assignment.targets[0].id
    elif len(body) == 1:
        check, subject = body[0], call
    else:
        return before_parsed, after_parsed
    if (not isinstance(check, ast.Assert) or not _inert_message(check.msg, capture) or not isinstance(check.test, ast.Compare)
            or len(check.test.ops) != 1 or not isinstance(check.test.ops[0], (ast.Is, ast.Eq))
            or stable_dump(check.test.left) != stable_dump(subject)
            or not isinstance(check.test.comparators[0], ast.Constant) or check.test.comparators[0].value is not None):
        return before_parsed, after_parsed
    # Only literal arguments are admitted by the primitive production proof;
    # imports, package initializers and startup hooks are checked on both sides.
    for source, (read, search) in zip((before, after), _context_snapshots(
            path, before, after, tuple(changes), root_reader, root_searcher)):
        if (not inert_test_execution_context(path, read, search) or not _pytest_unshadowed(path, read)
                or not pure_imported_calls(
                source, [call], path=path, read=read, result_proof=primitive_literal_result)):
            return before_parsed, after_parsed
    if len(before_parsed.units) != 1 or len(before_parsed.units[0].side.assertions) != 1:
        return before_parsed, after_parsed
    # The complete primitive-result proof excludes custom equality. On these
    # values only, equality to None and identity to None are the same null
    # predicate. Use the existing null carrier; no lattice value is changed.
    check.test.ops = [ast.Is()]
    # Keep the resolved null carrier's actual strength. Leaving a fixture or
    # helper parameter opaque would misclassify it as exact-value equality and
    # wrongly let that apparent strength compensate for the removed exception.
    rendered = ast.unparse(ast.fix_missing_locations(ast.Module(body=[new[0], new[1]], type_ignores=[])))
    normalized_after = parse_python(rendered.encode(), collect_tests=True)
    if (len(after_parsed.units) != 1 or len(after_parsed.units[0].side.assertions) != 1
            or len(normalized_after.units) != 1 or len(normalized_after.units[0].side.assertions) != 1):
        return before_parsed, after_parsed
    after_unit = after_parsed.units[0]
    after_assertion = replace(normalized_after.units[0].side.assertions[0],
                              span=_Offsets(normalize_source(after)).span(check))
    after_parsed = replace(after_parsed, units=[replace(after_unit, side=replace(
        after_unit.side, assertions=[after_assertion]))])
    unit = before_parsed.units[0]
    offsets = _Offsets(normalize_source(before))
    assertion = replace(unit.side.assertions[0], form='raises', strength=None, text=offsets.seg(expected) or '',
                        span=offsets.span(expected), left=None, right_literal=None, right_value=None,
                        trivial=False, left_names=(), right_depends_on=(), reaching={}, reaching_sig='')
    return replace(before_parsed, units=[replace(unit, side=replace(unit.side, assertions=[assertion]))]), after_parsed

"""Recognize a closed expected-exception oracle replaced by a null result.

The sentinel in `try: subject(); assert False / except ValueError: pass`
is not a standalone tautology. The whole try statement expects an exception.
This bounded two-sided extraction records the existing unknown-strength
`raises` form so ordinary assertion-removal policy can see its disappearance.
It grants no equivalence to another assertion and changes no lattice value.
"""
import ast
from dataclasses import replace

from checkwash.frontends.python.oracle_purity import _literal, pure_imported_calls
from checkwash.frontends.python.snapshot_context import inert_test_execution_context
from checkwash.frontends.python.table_oracles import _context_snapshots
from checkwash.frontends.python.frontend import _Offsets, normalize_source
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
    if name in _EXCEPTIONS or function.name == name:
        return None
    return imported, function, name


def mark_classic_exception_removal(before, after, before_parsed, after_parsed, *, path,
                                   root_reader=None, root_searcher=None, changes=()):
    if (root_reader is None or root_searcher is None or b'except' not in before
            or not before_parsed.parse_ok or not after_parsed.parse_ok):
        return before_parsed, after_parsed
    old, new = _module(before), _module(after)
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
    if len(body) == 2 and isinstance(body[0], ast.Assign) and len(body[0].targets) == 1:
        assignment, check = body
        if (not isinstance(assignment.targets[0], ast.Name) or assignment.targets[0].id == new[2]
                or stable_dump(assignment.value) != stable_dump(call)):
            return before_parsed, after_parsed
        subject = ast.Name(id=assignment.targets[0].id, ctx=ast.Load())
    elif len(body) == 1:
        check, subject = body[0], call
    else:
        return before_parsed, after_parsed
    if (not isinstance(check, ast.Assert) or check.msg is not None or not isinstance(check.test, ast.Compare)
            or len(check.test.ops) != 1 or not isinstance(check.test.ops[0], (ast.Is, ast.Eq))
            or stable_dump(check.test.left) != stable_dump(subject)
            or not isinstance(check.test.comparators[0], ast.Constant) or check.test.comparators[0].value is not None):
        return before_parsed, after_parsed
    # Only literal arguments are admitted by the primitive production proof;
    # imports, package initializers and startup hooks are checked on both sides.
    for source, (read, search) in zip((before, after), _context_snapshots(
            path, before, after, tuple(changes), root_reader, root_searcher)):
        if not inert_test_execution_context(path, read, search) or not pure_imported_calls(
                source, [call], path=path, read=read):
            return before_parsed, after_parsed
    if len(before_parsed.units) != 1 or len(before_parsed.units[0].side.assertions) != 1:
        return before_parsed, after_parsed
    unit = before_parsed.units[0]
    offsets = _Offsets(normalize_source(before))
    assertion = replace(unit.side.assertions[0], form='raises', strength=None, text=offsets.seg(expected) or '',
                        span=offsets.span(expected), left=None, right_literal=None, right_value=None,
                        trivial=False, left_names=(), right_depends_on=(), reaching={}, reaching_sig='')
    return replace(before_parsed, units=[replace(unit, side=replace(unit.side, assertions=[assertion]))]), after_parsed

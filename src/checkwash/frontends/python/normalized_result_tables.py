"""Retain transformed subjects when a literal table transforms both sides.

This narrow carrier projection never grants normalization equivalence. Every
old string answer becomes a concrete Boolean answer, while the entire new
subject and diagnostic remain in the parsed assertion. A proven pure result
capture is substituted so wrapper containment remains visible. The
ordinary literal expectation detector owns that transition.
"""
from __future__ import annotations

import ast
import copy
import hashlib
from collections import Counter
from dataclasses import replace

from checkwash.ir.astutil import dotted_name, stable_dump


def _string(node):
    return (isinstance(node, ast.Constant) and type(node.value) is str
            and node.value.isascii() and len(node.value) <= 4096)


def _scalar(node):
    return (_string(node) or isinstance(node, ast.Constant)
            and type(node.value) is int and abs(node.value) <= 4096)


def _string_result(source, target, call):
    """Type and effect proof for fresh string/split-list straight-line code.

Only fresh local split lists admit an index-zero write. No aliases, imported
callbacks, custom receivers, decorators or other module functions are used.
No production function is invoked to derive its output.
"""
    from .table_oracles import _args, _bounded_tree
    tree = _bounded_tree(source)
    if tree is None or call.keywords or not all(_scalar(arg) for arg in call.args):
        return False
    body = [node for node in tree.body if not (isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant) and type(node.value.value) is str)]
    if len(body) != 1 or not isinstance(body[0], ast.FunctionDef) or body[0].name != target:
        return False
    function = body[0]
    parameters = _args(function)
    if (parameters is None or function.decorator_list or len(parameters) != len(call.args)
            or len(set(parameters)) != len(parameters) or not function.body):
        return False
    kinds = {name: type(value.value) for name, value in zip(parameters, call.args)}
    fresh = set()
    list_of_strings = object()

    def kind(node):
        if _scalar(node):
            return type(node.value)
        if isinstance(node, ast.Name):
            return kinds.get(node.id)
        if isinstance(node, ast.BinOp):
            left, right = kind(node.left), kind(node.right)
            if isinstance(node.op, ast.Add) and left is right is str:
                return str
            if isinstance(node.op, ast.Mult) and (left, right) in ((str, int), (int, str)):
                return str
        if (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name)
                and node.value.id in fresh and isinstance(node.slice, ast.Constant)
                and type(node.slice.value) is int and node.slice.value == 0):
            return str
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and not node.keywords:
            receiver = kind(node.func.value)
            if receiver is str:
                if (node.func.attr == 'split' and len(node.args) == 1 and _string(node.args[0])
                        and node.args[0].value):
                    return list_of_strings
                if node.func.attr == 'join' and len(node.args) == 1 and kind(node.args[0]) is list_of_strings:
                    return str
                if node.func.attr in {'strip', 'lstrip', 'rstrip', 'lower', 'upper', 'casefold'} and not node.args:
                    return str
        return None

    for statement in function.body[:-1]:
        if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
            return False
        target_node = statement.targets[0]
        value_kind = kind(statement.value)
        if isinstance(target_node, ast.Name) and target_node.id not in kinds and value_kind in (str, int):
            kinds[target_node.id] = value_kind
        elif (isinstance(target_node, ast.Name) and target_node.id not in kinds and value_kind is list_of_strings
              and isinstance(statement.value, ast.Call)):
            kinds[target_node.id] = list_of_strings
            fresh.add(target_node.id)
        elif (isinstance(target_node, ast.Subscript) and isinstance(target_node.value, ast.Name)
              and target_node.value.id in fresh and isinstance(target_node.slice, ast.Constant)
              and type(target_node.slice.value) is int and target_node.slice.value == 0 and value_kind is str):
            pass
        else:
            return False
    last = function.body[-1]
    return isinstance(last, ast.Return) and kind(last.value) is str


def _normalized(node):
    """Return the receiver and concrete prefix of strip().startswith(prefix)."""
    if (not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute)
            or node.func.attr != 'startswith' or node.keywords or len(node.args) != 1):
        return None
    strip = node.func.value
    if (not isinstance(strip, ast.Call) or not isinstance(strip.func, ast.Attribute)
            or strip.func.attr != 'strip' or strip.args or strip.keywords):
        return None
    prefix = node.args[0]
    if _string(prefix):
        value = prefix.value
    elif (isinstance(prefix, ast.BinOp) and isinstance(prefix.op, ast.Mult)
          and _string(prefix.left) and isinstance(prefix.right, ast.Constant)
          and type(prefix.right.value) is int and 0 <= prefix.right.value <= 4096
          and len(prefix.left.value) * prefix.right.value <= 4096):
        value = prefix.left.value * prefix.right.value
    else:
        return None
    return strip.func.value, value


def _module(source, after):
    from .table_oracles import _args, _bounded_tree, _rows, _Substitute
    from .frontend import _Offsets, normalize_source
    tree = _bounded_tree(source)
    if tree is None:
        return None
    text = normalize_source(source)
    offsets = _Offsets(text)
    imports, occupied, functions, pytest = {}, set(), [], False
    for node in tree.body:
        if isinstance(node, ast.Expr) and _string(node.value):
            continue
        if isinstance(node, ast.ImportFrom) and not functions and node.module and not node.level:
            for alias in node.names:
                name = alias.asname or alias.name
                if name in occupied or alias.name == '*' or name.startswith('__') or name == 'pytest':
                    return None
                imports[name] = (node.module, alias.name)
                occupied.add(name)
        elif (isinstance(node, ast.Import) and not functions and len(node.names) == 1
              and node.names[0].name == 'pytest' and node.names[0].asname is None and 'pytest' not in occupied):
            occupied.add('pytest')
            pytest = True
        elif (isinstance(node, ast.FunctionDef) and node.name.startswith('test')
              and node.name not in occupied):
            functions.append(node)
            occupied.add(node.name)
        else:
            return None
    if not imports or not functions or after and (not pytest or len(functions) != 1):
        return None

    def imported_call(node):
        return (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in imports and not node.keywords and all(_scalar(arg) for arg in node.args))

    cases = []
    for function in functions:
        args = _args(function)
        if args is None or set(args) & occupied or len(args) != len(set(args)):
            return None
        if not after:
            if args or function.decorator_list or len(function.body) != 1:
                return None
            assertion = function.body[0]
            if (not isinstance(assertion, ast.Assert) or assertion.msg is not None
                    or not isinstance(assertion.test, ast.Compare) or len(assertion.test.ops) != 1
                    or not isinstance(assertion.test.ops[0], ast.Eq) or not imported_call(assertion.test.left)
                    or not _string(assertion.test.comparators[0])):
                return None
            cases.append((assertion.test.left, assertion.test.comparators[0], function, assertion, [assertion]))
            continue
        if not args or len(function.decorator_list) != 1 or len(function.body) not in (1, 2):
            return None
        decorator = function.decorator_list[0]
        if (not isinstance(decorator, ast.Call) or dotted_name(decorator.func) != 'pytest.mark.parametrize'
                or len(decorator.args) != 2 or decorator.keywords or not _string(decorator.args[0])):
            return None
        columns = [name.strip() for name in decorator.args[0].value.split(',')]
        if len(columns) != len(set(columns)) or set(columns) != set(args):
            return None
        rows = _rows(decorator.args[1], columns, unpack=len(columns) != 1)
        if rows is None or not all(all(_scalar(value) for value in row.values()) for row in rows):
            return None
        for row in rows:
            body = _Substitute(row).visit(copy.deepcopy(ast.Module(body=function.body, type_ignores=[]))).body
            local = {}
            if len(body) == 2:
                assignment = body[0]
                if (not isinstance(assignment, ast.Assign) or len(assignment.targets) != 1
                        or not isinstance(assignment.targets[0], ast.Name)
                        or assignment.targets[0].id in occupied | set(args) or not imported_call(assignment.value)):
                    return None
                local[assignment.targets[0].id] = assignment.value
            assertion = body[-1]
            if (not isinstance(assertion, ast.Assert) or not isinstance(assertion.test, ast.Compare)
                    or len(assertion.test.ops) != 1 or not isinstance(assertion.test.ops[0], ast.Eq)):
                return None
            left = _normalized(_Substitute(local).visit(copy.deepcopy(assertion.test.left)))
            right = _normalized(assertion.test.comparators[0])
            if left is None or right is None or left[1] != right[1] or not imported_call(left[0]) or not _string(right[0]):
                return None
            if local and sum(isinstance(node, ast.Name) and node.id in local for node in ast.walk(assertion.test)) != 1:
                return None
            message = assertion.msg
            if message is not None:
                if isinstance(message, ast.JoinedStr):
                    for part in message.values:
                        if _string(part):
                            continue
                        if (not isinstance(part, ast.FormattedValue) or part.format_spec is not None
                                or part.conversion not in (-1, 97, 114, 115)
                                or not (isinstance(part.value, ast.Name) and part.value.id in local or _scalar(part.value))):
                            return None
                elif not _string(message):
                    return None
            # Only the closed literal RHS is folded. Keep the transformed
            # subject and its diagnostic; projection may substitute the pure
            # result capture after the production type/effect proof passes.
            assertion.test.comparators[0] = ast.Constant(value=right[0].value.strip().startswith(right[1]))
            cases.append((left[0], right[0], function, function.body[-1], body))
    if not 0 < len(cases) <= 64 or set(imports) != {case[0].func.id for case in cases}:
        return None
    return text, offsets, imports, cases


def _project(parsed, module):
    from .frontend import parse_python
    from .table_oracles import _Substitute
    definitions, counts = [], Counter()
    for call, _expected, _function, _assertion, body in module[3]:
        digest = hashlib.sha256(stable_dump(call).encode()).hexdigest()[:24]
        counts[digest] += 1
        if len(body) == 2:
            assignment, assertion = body
            assertion = _Substitute({assignment.targets[0].id: assignment.value}).visit(copy.deepcopy(assertion))
            body = [assertion]
        rendered = '\n'.join(ast.unparse(statement) for statement in body)
        definitions.append(f'def test_concrete_{digest}_{counts[digest]}():\n'
                           + '\n'.join('    ' + line for line in rendered.splitlines()))
    concrete = parse_python(('\n'.join(definitions) + '\n').encode(), collect_tests=True)
    units = []
    for unit, case in zip(concrete.units, module[3]):
        span = module[1].span(case[2])
        assertions = [replace(assertion, span=module[1].span(case[3])) for assertion in unit.side.assertions]
        units.append(replace(unit, span=span, side=replace(unit.side, span=span, assertions=assertions)))
    return replace(parsed, units=units)


def project_normalized_result_table(before, after, before_parsed, after_parsed, *, path,
                                    root_reader, root_searcher, changes):
    from .oracle_purity import pure_imported_calls
    from .snapshot_context import inert_test_execution_context
    from .table_oracles import _context_snapshots, _pytest_unshadowed
    if (root_reader is None or root_searcher is None or not before_parsed.parse_ok or not after_parsed.parse_ok
            or b'parametrize' not in after or b'.strip()' not in after or b'.startswith(' not in after):
        return None
    changes = tuple(changes)
    if any(change.path != path and change.before != change.after for change in changes):
        return None
    try:
        old, new = _module(before, False), _module(after, True)
        if old is None or new is None or old[2] != new[2]:
            return None
        key = lambda case: (stable_dump(case[0]), stable_dump(case[1]))
        if [key(case) for case in old[3]] != [key(case) for case in new[3]][:len(old[3])]:
            return None  # preserve every raw input/answer in order, including duplicates
        for module, (read, search) in zip((old, new), _context_snapshots(path, before, after, changes, root_reader, root_searcher)):
            if (not inert_test_execution_context(path, read, search) or not _pytest_unshadowed(path, read)
                    or not pure_imported_calls(module[0].encode(), [case[0] for case in module[3]],
                                               path=path, read=read, result_proof=_string_result)):
                return None
        return _project(before_parsed, old), _project(after_parsed, new)
    except (SyntaxError, ValueError, TypeError, AttributeError, RecursionError, MemoryError):
        return None

"""A fresh literal fixture loop can consume a local implementation instead.

The prior numeric input/answer is retained as the first row. Closed helper
returns and primitive diagnostics establish actual replacement consumption;
this adds installation evidence without projecting or weakening any oracle.
"""
from __future__ import annotations

import ast

from .callable_fixture_expectations import _number, _parameters
from .frontend import _Offsets, normalize_source
from .local_parameter_implementations import _RESERVED, _helper, _module, _returns
from .oracle_purity import primitive_literal_result, pure_imported_calls
from .snapshot_context import inert_test_execution_context
from checkwash.ir.astutil import dotted_name, stable_dump
from checkwash.pyenv import known_baseline


def _diagnostic(node, names):
    if node is None or isinstance(node, ast.Constant) and type(node.value) is str:
        return True
    if not isinstance(node, ast.JoinedStr):
        return False
    return all(isinstance(part, ast.Constant) and type(part.value) is str
        or isinstance(part, ast.FormattedValue) and part.format_spec is None and part.conversion in (-1, 97, 114, 115)
        and isinstance(part.value, ast.Name) and part.value.id in names for part in node.values)


def _replacement(old, new):
    if stable_dump(old[0]) != stable_dump(new[0]) or len(old[2]) != 1:
        return None
    before = old[2][0]
    if (not before.name.startswith('test') or before.decorator_list or _parameters(before) != []
            or len(before.body) != 1 or not isinstance(before.body[0], ast.Assert) or before.body[0].msg is not None):
        return None
    comparison = before.body[0].test
    if (not isinstance(comparison, ast.Compare) or len(comparison.ops) != 1 or not isinstance(comparison.ops[0], ast.Eq)
            or not _number(comparison.comparators[0])):
        return None
    original = comparison.left
    if (not isinstance(original, ast.Call) or not isinstance(original.func, ast.Name) or original.func.id != old[1]
            or original.keywords or len(original.args) != 2 or not all(_number(value) for value in original.args)):
        return None
    fixture, helper, test = new[2]
    if (_parameters(fixture) != [] or len(fixture.decorator_list) != 1 or len(fixture.body) != 1
            or not isinstance(fixture.body[0], ast.Return)):
        return None
    decorator = fixture.decorator_list[0]
    if isinstance(decorator, ast.Call) and not decorator.args and not decorator.keywords:
        decorator = decorator.func
    data = fixture.body[0].value
    if (dotted_name(decorator) != 'pytest.fixture' or not isinstance(data, (ast.List, ast.Tuple))
            or not 0 < len(data.elts) <= 64):
        return None
    rows = data.elts
    if any(not isinstance(row, (ast.List, ast.Tuple)) or len(row.elts) != 3
           or not all(_number(value) for value in row.elts) for row in rows):
        return None
    if [stable_dump(value) for value in rows[0].elts] != [stable_dump(value) for value in [*original.args, comparison.comparators[0]]]:
        return None
    parameters = _helper(helper, new[3])
    if parameters is None or not all(_returns(helper, parameters, row.elts[:2]) for row in rows):
        return None
    if (not test.name.startswith('test') or test.decorator_list or _parameters(test) != [fixture.name]
            or len(test.body) != 1 or not isinstance(test.body[0], ast.For)):
        return None
    loop = test.body[0]
    if (not isinstance(loop.target, (ast.Tuple, ast.List)) or len(loop.target.elts) != 3
            or not all(isinstance(value, ast.Name) for value in loop.target.elts)
            or not isinstance(loop.iter, ast.Name) or loop.iter.id != fixture.name
            or loop.orelse or len(loop.body) != 2):
        return None
    columns = [value.id for value in loop.target.elts]
    if len(set(columns)) != 3 or set(columns) & (new[3] | _RESERVED) or any(name.startswith('__') for name in columns):
        return None
    capture, check = loop.body
    if (not isinstance(capture, ast.Assign) or len(capture.targets) != 1 or not isinstance(capture.targets[0], ast.Name)
            or capture.targets[0].id in new[3] | _RESERVED | set(columns) or capture.targets[0].id.startswith('__')
            or not isinstance(check, ast.Assert) or not _diagnostic(check.msg, set(columns) | {capture.targets[0].id})):
        return None
    invoked = capture.value
    if (not isinstance(invoked, ast.Call) or not isinstance(invoked.func, ast.Name) or invoked.func.id != helper.name
            or invoked.keywords or len(invoked.args) != 2
            or any(not isinstance(arg, ast.Name) or arg.id != name for arg, name in zip(invoked.args, columns[:2]))):
        return None
    comparison = check.test
    if (not isinstance(comparison, ast.Compare) or len(comparison.ops) != 1 or not isinstance(comparison.ops[0], ast.Eq)
            or not isinstance(comparison.comparators[0], ast.Name) or comparison.comparators[0].id != columns[2]):
        return None
    rounded = comparison.left
    if (not isinstance(rounded, ast.Call) or not isinstance(rounded.func, ast.Name) or rounded.func.id != 'round'
            or rounded.keywords or len(rounded.args) != 2 or not isinstance(rounded.args[0], ast.Name)
            or rounded.args[0].id != capture.targets[0].id or not isinstance(rounded.args[1], ast.Constant)
            or type(rounded.args[1].value) is not int or rounded.args[1].value != 2):
        return None
    return test, check, original


def fixture_local_implementation_events(ir, changes, *, root_reader=None, root_searcher=None):
    from .table_oracles import _context_snapshots, _pytest_unshadowed
    if root_reader is None or root_searcher is None:
        return []
    changes = tuple(changes)
    changed = [change for change in changes if change.before != change.after]
    if len(changed) != 1:
        return []
    change = changed[0]
    if (not change.before or not change.after or change.status != 'modified' or change.old_path is not None
            or b'fixture' not in change.after or b'round' not in change.after):
        return []
    file = next((file for file in ir.files if file.path == change.path and file.role == 'test' and file.parse_ok), None)
    if file is None:
        return []
    try:
        old, new = _module(change.before, False), _module(change.after, True, after_count=3)
        if old is None or new is None:
            return []
        matched = _replacement(old, new)
        if matched is None:
            return []
        test, check, original = matched
        target = old[0].module + '.' + old[0].names[0].name
        if target.split('.')[0] in known_baseline() | set(ir.globals.third_party_roots):
            return []
        if not any(unit.qualname == test.name and unit.after is not None for unit in file.units):
            return []
        for source, (read, search) in zip((change.before, change.after), _context_snapshots(
                change.path, change.before, change.after, changes, root_reader, root_searcher)):
            if (not inert_test_execution_context(change.path, read, search) or not _pytest_unshadowed(change.path, read)
                    or not pure_imported_calls(source, [original], path=change.path, read=read, result_proof=primitive_literal_result)):
                return []
        offsets = _Offsets(normalize_source(change.after))
        return [(change.path, test.name, target, offsets.seg(check), offsets.span(check))]
    except (SyntaxError, ValueError, TypeError, AttributeError, RecursionError, MemoryError, ArithmeticError):
        return []

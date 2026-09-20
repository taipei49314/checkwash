"""A closed literal table replaces its production subject with min or max.

This contributes installation evidence only. Every original input must remain
in order, including repetitions; expected answers are left to oracle rules.
"""
from __future__ import annotations

import ast
import copy

from .callable_fixture_expectations import _number, _parameters
from .frontend import _Offsets, normalize_source
from .local_parameter_implementations import _module, _RESERVED
from .oracle_purity import primitive_literal_result, pure_imported_calls
from .snapshot_context import inert_test_execution_context
from checkwash.ir.astutil import dotted_name, stable_dump
from checkwash.pyenv import known_baseline

_BUILTINS = {'min', 'max'}


def _names(names, occupied):
    return (len(names) == len(set(names)) and not set(names) & (occupied | _RESERVED | _BUILTINS)
            and all(not name.startswith(('__', 'pytest_')) for name in names))


def _rows(node):
    if not isinstance(node, (ast.List, ast.Tuple)) or not 1 <= len(node.elts) <= 64:
        return None
    result = []
    for row in node.elts:
        if not isinstance(row, (ast.List, ast.Tuple)) or len(row.elts) != 2:
            return None
        values, answer = row.elts
        if (not isinstance(values, (ast.List, ast.Tuple)) or not 1 <= len(values.elts) <= 64
                or not all(_number(value) for value in values.elts) or not _number(answer)):
            return None
        result.append(values)
    return result


def _comparison(statement, provider, names):
    if (not isinstance(statement, ast.Assert) or statement.msg is not None
            or not isinstance(statement.test, ast.Compare) or len(statement.test.ops) != 1
            or not isinstance(statement.test.ops[0], ast.Eq)
            or not isinstance(statement.test.comparators[0], ast.Name)
            or statement.test.comparators[0].id != names[1]):
        return None
    call = statement.test.left
    return (call if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == provider
            and not call.keywords and len(call.args) == 1 and isinstance(call.args[0], ast.Name)
            and call.args[0].id == names[0] else None)


def _replacement(before, after):
    old, new = _module(before, False), _module(after, True, after_count=1)
    if (old is None or new is None or len(old[2]) != 1
            or stable_dump(old[0]) != stable_dump(new[0]) or (old[3] | new[3]) & _BUILTINS):
        return None
    previous, current = old[2][0], new[2][0]
    if (not previous.name.startswith('test') or previous.name != current.name or previous.decorator_list
            or _parameters(previous) != [] or len(previous.body) != 2 or len(current.body) != 1
            or len(current.decorator_list) != 1):
        return None
    assignment, loop = previous.body
    if (not isinstance(assignment, ast.Assign) or len(assignment.targets) != 1
            or not isinstance(assignment.targets[0], ast.Name) or not isinstance(loop, ast.For)
            or not isinstance(loop.target, (ast.Tuple, ast.List)) or len(loop.target.elts) != 2
            or not all(isinstance(target, ast.Name) for target in loop.target.elts)
            or not isinstance(loop.iter, ast.Name) or loop.iter.id != assignment.targets[0].id
            or loop.orelse or len(loop.body) != 1):
        return None
    names = [target.id for target in loop.target.elts]
    if not _names([assignment.targets[0].id, *names], old[3]):
        return None
    call = _comparison(loop.body[0], old[1], names)
    old_inputs = _rows(assignment.value)
    arguments = _parameters(current)
    if call is None or old_inputs is None or arguments is None or len(arguments) != 2 or not _names(arguments, new[3]):
        return None
    decorator = current.decorator_list[0]
    if (not isinstance(decorator, ast.Call) or dotted_name(decorator.func) != 'pytest.mark.parametrize'
            or decorator.keywords or len(decorator.args) != 2
            or not isinstance(decorator.args[0], ast.Constant) or type(decorator.args[0].value) is not str
            or [name.strip() for name in decorator.args[0].value.split(',')] != arguments):
        return None
    new_inputs = _rows(decorator.args[1])
    if (new_inputs is None or [stable_dump(value) for value in old_inputs] != [stable_dump(value) for value in new_inputs]
            or not any(_comparison(current.body[0], builtin, arguments) for builtin in _BUILTINS)):
        return None
    calls = []
    for values in old_inputs:
        concrete = copy.deepcopy(call)
        concrete.args = [copy.deepcopy(values)]
        calls.append(concrete)
    return old, current, calls


def literal_extrema_events(ir, changes, *, root_reader=None, root_searcher=None):
    from .table_oracles import _context_snapshots, _module_unshadowed, _pytest_unshadowed
    if root_reader is None or root_searcher is None:
        return []
    changes = tuple(changes)
    changed = [change for change in changes if change.before != change.after]
    if len(changed) != 1:
        return []
    change = changed[0]
    if (change.status != 'modified' or change.old_path is not None or not change.before or not change.after
            or b'parametrize' not in change.after or not (b'min' in change.after or b'max' in change.after)):
        return []
    file = next((file for file in ir.files if file.path == change.path and file.role == 'test' and file.parse_ok), None)
    if file is None:
        return []
    try:
        matched = _replacement(change.before, change.after)
        if matched is None:
            return []
        old, test, calls = matched
        target = old[0].module + '.' + old[0].names[0].name
        if target.split('.', 1)[0] in known_baseline() | set(ir.globals.third_party_roots):
            return []
        if not any(unit.qualname == test.name and unit.before is not None and unit.after is not None for unit in file.units):
            return []
        for source, (read, search) in zip((change.before, change.after), _context_snapshots(
                change.path, change.before, change.after, changes, root_reader, root_searcher)):
            if (not inert_test_execution_context(change.path, read, search) or not _pytest_unshadowed(change.path, read)
                    or not _module_unshadowed(change.path, read, 'builtins')
                    or not pure_imported_calls(source, calls, path=change.path, read=read, result_proof=primitive_literal_result)):
                return []
        offsets = _Offsets(normalize_source(change.after))
        assertion = test.body[0]
        return [(change.path, test.name, target, offsets.seg(assertion), offsets.span(assertion))]
    except (SyntaxError, ValueError, TypeError, AttributeError, RecursionError, MemoryError, ArithmeticError):
        return []

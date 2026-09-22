"""Literal string methods replacing complete imported-subject test rows.

This contributes existing subject-installation evidence only. It does not
equate identity with equality or grant oracle alignment to the replacement.
"""
from __future__ import annotations

import ast

from .callable_fixture_expectations import _parameters
from .frontend import _Offsets, normalize_source
from .local_parameter_implementations import _RESERVED, _module
from .oracle_purity import primitive_literal_result, pure_imported_calls
from .snapshot_context import inert_test_execution_context
from .table_oracles import _bounded_tree, _context_snapshots, _pytest_unshadowed
from checkwash.ir.astutil import dotted_name, stable_dump
from checkwash.pyenv import known_baseline


def _string(node):
    return isinstance(node, ast.Constant) and type(node.value) is str


def _boolean(node):
    return isinstance(node, ast.Constant) and type(node.value) is bool


def _primitive_source(source, target, call):
    if primitive_literal_result(source, target, call):
        return True
    # The existing string stand-in proof returns only str, whereas these
    # two builtin methods return bool. Admit this entire one-return module
    # locally without widening the shared string or purity contracts.
    tree = _bounded_tree(source)
    if tree is None or call.keywords or len(call.args) != 2 or not all(_string(arg) for arg in call.args):
        return False
    body = [node for node in tree.body if not (isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant) and type(node.value.value) is str)]
    if len(body) != 1 or not isinstance(body[0], ast.FunctionDef) or body[0].name != target:
        return False
    function = body[0]
    names = _parameters(function)
    if (names is None or len(names) != 2 or function.decorator_list or len(function.body) != 1
            or any(name.startswith('__') for name in [target, *names])
            or not isinstance(function.body[0], ast.Return)):
        return False
    returned = function.body[0].value
    return (isinstance(returned, ast.Call) and isinstance(returned.func, ast.Attribute)
            and returned.func.attr in {'startswith', 'endswith'} and not returned.keywords
            and len(returned.args) == 1 and isinstance(returned.func.value, ast.Name)
            and returned.func.value.id == names[0] and isinstance(returned.args[0], ast.Name)
            and returned.args[0].id == names[1])


def _rows(old, new):
    if stable_dump(old[0]) != stable_dump(new[0]) or not 1 <= len(old[2]) <= 64:
        return None
    previous = []
    for function in old[2]:
        if (not function.name.startswith('test') or function.decorator_list or _parameters(function) != []
                or len(function.body) != 1 or not isinstance(function.body[0], ast.Assert)
                or function.body[0].msg is not None):
            return None
        comparison = function.body[0].test
        if (not isinstance(comparison, ast.Compare) or len(comparison.ops) != 1
                or not isinstance(comparison.ops[0], ast.Is) or not _boolean(comparison.comparators[0])):
            return None
        call = comparison.left
        if (not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name) or call.func.id != old[1]
                or call.keywords or len(call.args) != 2 or not all(_string(arg) for arg in call.args)):
            return None
        previous.append((call, comparison.comparators[0]))
    test = new[2][0]
    names = _parameters(test)
    if (names is None or len(names) != 3 or not test.name.startswith('test')
            or set(names) & (new[3] | _RESERVED) or any(name.startswith('__') for name in names)
            or len(test.decorator_list) != 1 or len(test.body) != 1
            or not isinstance(test.body[0], ast.Assert) or test.body[0].msg is not None):
        return None
    decorator = test.decorator_list[0]
    if (not isinstance(decorator, ast.Call) or dotted_name(decorator.func) != 'pytest.mark.parametrize'
            or decorator.keywords or len(decorator.args) != 2 or not _string(decorator.args[0])
            or [name.strip() for name in decorator.args[0].value.split(',')] != names
            or not isinstance(decorator.args[1], (ast.List, ast.Tuple))
            or not len(previous) <= len(decorator.args[1].elts) <= 64):
        return None
    rows = decorator.args[1].elts
    for index, row in enumerate(rows):
        if (not isinstance(row, (ast.List, ast.Tuple)) or len(row.elts) != 3
                or not all(_string(value) for value in row.elts[:2]) or not _boolean(row.elts[2])):
            return None
        if index < len(previous):
            call, expected = previous[index]
            if [stable_dump(value) for value in row.elts] != [stable_dump(value) for value in [*call.args, expected]]:
                return None
    comparison = test.body[0].test
    if (not isinstance(comparison, ast.Compare) or len(comparison.ops) != 1 or not isinstance(comparison.ops[0], ast.Eq)
            or not isinstance(comparison.comparators[0], ast.Name) or comparison.comparators[0].id != names[2]):
        return None
    called = comparison.left
    if (not isinstance(called, ast.Call) or not isinstance(called.func, ast.Attribute)
            or called.func.attr != 'startswith' or not isinstance(called.func.value, ast.Name)
            or called.func.value.id != names[0] or called.keywords or len(called.args) != 1
            or not isinstance(called.args[0], ast.Name) or called.args[0].id != names[1]):
        return None
    return test, [row[0] for row in previous]


def parametrized_string_standin_events(ir, changes, *, root_reader=None, root_searcher=None):
    if root_reader is None or root_searcher is None:
        return []
    changes = tuple(changes)
    changed = [change for change in changes if change.before != change.after]
    if len(changed) != 1:
        return []
    change = changed[0]
    if (not change.before or not change.after or change.status != 'modified' or change.old_path is not None
            or b'parametrize' not in change.after or b'startswith' not in change.after):
        return []
    file = next((file for file in ir.files if file.path == change.path and file.role == 'test' and file.parse_ok), None)
    if file is None:
        return []
    try:
        old, new = _module(change.before, False), _module(change.after, True, after_count=1)
        if old is None or new is None:
            return []
        matched = _rows(old, new)
        if matched is None:
            return []
        test, calls = matched
        target = old[0].module + '.' + old[0].names[0].name
        if target.split('.')[0] in known_baseline() | set(ir.globals.third_party_roots):
            return []
        if not any(unit.qualname == test.name and unit.after is not None for unit in file.units):
            return []
        for source, (read, search) in zip((change.before, change.after), _context_snapshots(
                change.path, change.before, change.after, changes, root_reader, root_searcher)):
            if (not inert_test_execution_context(change.path, read, search) or not _pytest_unshadowed(change.path, read)
                    or not pure_imported_calls(source, calls, path=change.path, read=read, result_proof=_primitive_source)):
                return []
        offsets = _Offsets(normalize_source(change.after))
        statement = test.body[0]
        return [(change.path, test.name, target, offsets.seg(statement), offsets.span(statement))]
    except (SyntaxError, ValueError, TypeError, AttributeError, RecursionError, MemoryError):
        return []

"""A numeric fixture implementation replaces a consumed production generator.

The complete finite range and every input/answer row must remain identical.
Only default fixtures returning a closed one-argument numeric function qualify;
the pass adds existing installation evidence without rewriting oracle IR.
"""
from __future__ import annotations

import ast
import copy

from .callable_fixture_expectations import _number, _numeric, _parameters
from .expected_constants import folded_expected
from .frontend import _Offsets, normalize_source
from .literal_all_oracles import _module as _generator_module
from .local_parameter_implementations import _RESERVED, _module, _returns
from .oracle_purity import primitive_literal_result, pure_imported_calls
from .snapshot_context import inert_test_execution_context
from checkwash.ir.astutil import dotted_name, stable_dump
from checkwash.pyenv import known_baseline

_BUILTINS = {'all', 'range'}


def _safe(name):
    return name not in _RESERVED | _BUILTINS and not name.startswith(('__', 'pytest_'))


def _value(node):
    if not _number(node):
        return None
    value = ast.literal_eval(node)
    return type(value).__name__, repr(value)


def _fixture(function, occupied, provider):
    if (_parameters(function) != [] or function.name.startswith('test') or len(function.decorator_list) != 1
            or len(function.body) != 2 or not isinstance(function.body[0], ast.FunctionDef)
            or not isinstance(function.body[1], ast.Return)):
        return None
    decorator = function.decorator_list[0]
    if isinstance(decorator, ast.Call) and not decorator.args and not decorator.keywords:
        decorator = decorator.func
    helper, returned = function.body
    parameters = _parameters(helper)
    if (dotted_name(decorator) != 'pytest.fixture' or parameters is None or len(parameters) != 1
            or not _safe(helper.name) or helper.name.startswith('test') or helper.name in occupied - {provider}
            or helper.decorator_list or len(helper.body) != 1 or not isinstance(helper.body[0], ast.Return)
            or not _safe(parameters[0]) or parameters[0] in occupied | {helper.name}
            or not _numeric(helper.body[0].value, set(parameters))
            or not isinstance(returned.value, ast.Name) or returned.value.id != helper.name):
        return None
    return helper, parameters


def _replacement(before, after):
    old, new = _generator_module(before), _module(after, True, after_count=2)
    if (old is None or old[4] or new is None or stable_dump(old[0]) != stable_dump(new[0])
            or new[3] & _BUILTINS):
        return None
    fixture, test = new[2]
    if not _safe(fixture.name):
        return None
    implementation = _fixture(fixture, new[3], new[1])
    arguments = _parameters(test)
    if (implementation is None or test.name != old[1].name or arguments is None or len(arguments) != 3
            or arguments[0] != fixture.name or any(not _safe(name) for name in arguments[1:])
            or set(arguments[1:]) & new[3] or len(test.decorator_list) != 1 or len(test.body) != 1
            or not isinstance(test.body[0], ast.Assert) or test.body[0].msg is not None):
        return None
    decorator = test.decorator_list[0]
    if (not isinstance(decorator, ast.Call) or dotted_name(decorator.func) != 'pytest.mark.parametrize'
            or decorator.keywords or len(decorator.args) != 2
            or not isinstance(decorator.args[0], ast.Constant) or type(decorator.args[0].value) is not str
            or [name.strip() for name in decorator.args[0].value.split(',')] != arguments[1:]
            or not isinstance(decorator.args[1], (ast.List, ast.Tuple))
            or len(decorator.args[1].elts) != len(old[3])):
        return None
    comparison = test.body[0].test
    if (not isinstance(comparison, ast.Compare) or len(comparison.ops) != 1 or not isinstance(comparison.ops[0], ast.Eq)
            or not isinstance(comparison.comparators[0], ast.Name) or comparison.comparators[0].id != arguments[2]):
        return None
    called = comparison.left
    if (not isinstance(called, ast.Call) or not isinstance(called.func, ast.Name) or called.func.id != fixture.name
            or called.keywords or len(called.args) != 1 or not isinstance(called.args[0], ast.Name)
            or called.args[0].id != arguments[1]):
        return None
    generator = next(node.value for node in old[1].body if isinstance(node, ast.Assign))
    variable = generator.generators[0].target.id
    expected = generator.elt.comparators[0]
    helper, parameters = implementation
    for original, row in zip(old[3], decorator.args[1].elts):
        if not isinstance(row, (ast.List, ast.Tuple)) or len(row.elts) != 2 or not all(_number(value) for value in row.elts):
            return None
        class Bind(ast.NodeTransformer):
            def visit_Name(self, node):
                return copy.deepcopy(original.args[0]) if node.id == variable else node
        answer = folded_expected(Bind().visit(copy.deepcopy(expected)), lambda _: False)
        if (answer is None or _value(answer) is None or _value(original.args[0]) != _value(row.elts[0])
                or _value(answer) != _value(row.elts[1]) or not _returns(helper, parameters, row.elts[:1])):
            return None
    return old, test


def generator_fixture_subject_events(ir, changes, *, root_reader=None, root_searcher=None):
    from .table_oracles import _context_snapshots, _module_unshadowed, _pytest_unshadowed
    if root_reader is None or root_searcher is None:
        return []
    changes = tuple(changes)
    changed = [change for change in changes if change.before != change.after]
    if len(changed) != 1:
        return []
    change = changed[0]
    if (change.status != 'modified' or change.old_path is not None or not change.before or not change.after
            or b'fixture' not in change.after or b'parametrize' not in change.after or b'range' not in change.before):
        return []
    file = next((file for file in ir.files if file.path == change.path and file.role == 'test' and file.parse_ok), None)
    if file is None:
        return []
    try:
        matched = _replacement(change.before, change.after)
        if matched is None:
            return []
        old, test = matched
        target = old[0].module + '.' + old[0].names[0].name
        if target.split('.', 1)[0] in known_baseline() | set(ir.globals.third_party_roots):
            return []
        if not any(unit.qualname == test.name and unit.before is not None and unit.after is not None for unit in file.units):
            return []
        for source, (read, search) in zip((change.before, change.after), _context_snapshots(
                change.path, change.before, change.after, changes, root_reader, root_searcher)):
            if (not inert_test_execution_context(change.path, read, search) or not _pytest_unshadowed(change.path, read)
                    or not _module_unshadowed(change.path, read, 'builtins')
                    or not pure_imported_calls(source, old[3], path=change.path, read=read, result_proof=primitive_literal_result)):
                return []
        offsets = _Offsets(normalize_source(change.after))
        assertion = test.body[0]
        return [(change.path, test.name, target, offsets.seg(assertion), offsets.span(assertion))]
    except (SyntaxError, ValueError, TypeError, AttributeError, RecursionError, MemoryError, ArithmeticError):
        return []

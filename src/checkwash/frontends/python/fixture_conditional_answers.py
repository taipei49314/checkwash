"""Keep numeric answers derived from default literal fixture parameters visible.

The original fixture still owns its rows and ids. Each immutable input row gains
its closed conditional answer, and its sole consumer unpacks the pair. Complete
two-snapshot source and startup authority remains the table caller's obligation.
"""
from __future__ import annotations

import ast
import copy

from .callable_fixture_expectations import _number, _parameters
from .expected_constants import folded_expected
from .oracle_blocks import IMPLICIT_ENTRY_NAMES
from checkwash.ir.astutil import dotted_name

_RESERVED = IMPLICIT_ENTRY_NAMES | {'pytest', 'pytestmark', 'pytest_plugins', 'request'}


def _conditional(node, parameter, depth=0):
    if _number(node):
        return True
    if depth > 8 or not isinstance(node, ast.IfExp):
        return False
    condition = node.test
    if (not isinstance(condition, ast.Compare) or len(condition.ops) != 1
            or not isinstance(condition.ops[0], (ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE))):
        return False
    operands = [condition.left, condition.comparators[0]]
    return (any(isinstance(value, ast.Name) and value.id == parameter for value in operands)
            and all(_number(value) or isinstance(value, ast.Name) and value.id == parameter for value in operands)
            and _conditional(node.body, parameter, depth+1) and _conditional(node.orelse, parameter, depth+1))


def expand_fixture_conditional_answers(tree):
    imported, functions, occupied, pytest = None, [], set(), False
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and type(node.value.value) is str:
            continue
        if (isinstance(node, ast.Import) and not functions and not pytest and len(node.names) == 1
                and node.names[0].name == 'pytest' and node.names[0].asname is None):
            name, pytest = 'pytest', True
        elif (isinstance(node, ast.ImportFrom) and not functions and imported is None and not node.level
                and node.module and len(node.names) == 1 and node.names[0].name != '*'):
            imported, name = node, node.names[0].asname or node.names[0].name
        elif isinstance(node, ast.FunctionDef) and _parameters(node) is not None:
            name = node.name
            functions.append(node)
        else:
            return set()
        if (name in occupied or name.startswith(('__', 'pytest_'))
                or name in _RESERVED and not (name == 'pytest' and isinstance(node, ast.Import))):
            return set()
        occupied.add(name)
    if not pytest or imported is None or len(functions) != 2:
        return set()
    provider = imported.names[0].asname or imported.names[0].name
    fixture, test = functions
    if (provider.startswith('test') or _parameters(fixture) != ['request']
            or len(fixture.decorator_list) != 1 or len(fixture.body) != 1
            or not isinstance(fixture.body[0], ast.Return) or dotted_name(fixture.body[0].value) != 'request.param'):
        return set()
    decorator = fixture.decorator_list[0]
    if (not isinstance(decorator, ast.Call) or dotted_name(decorator.func) != 'pytest.fixture' or decorator.args):
        return set()
    options = {keyword.arg: keyword.value for keyword in decorator.keywords}
    if len(options) != len(decorator.keywords) or set(options) not in ({'params'}, {'params', 'ids'}):
        return set()
    values = options['params']
    if not isinstance(values, (ast.List, ast.Tuple)) or not 0 < len(values.elts) <= 64 or not all(_number(value) for value in values.elts):
        return set()
    if 'ids' in options:
        ids = options['ids']
        if (not isinstance(ids, (ast.List, ast.Tuple)) or len(ids.elts) != len(values.elts)
                or not all(isinstance(value, ast.Constant) and type(value.value) is str for value in ids.elts)
                or len({value.value for value in ids.elts}) != len(ids.elts)):
            return set()
    if (not test.name.startswith('test') or test.decorator_list or _parameters(test) != [fixture.name]
            or len(test.body) != 2 or not isinstance(test.body[0], ast.Assign)
            or not isinstance(test.body[1], ast.Assert) or test.body[1].msg is not None):
        return set()
    assignment, assertion = test.body
    if (len(assignment.targets) != 1 or not isinstance(assignment.targets[0], ast.Name)
            or not isinstance(assignment.value, ast.IfExp) or not _conditional(assignment.value, fixture.name)):
        return set()
    answer = assignment.targets[0].id
    if answer in occupied | _RESERVED or answer.startswith(('__', 'pytest_')):
        return set()
    comparison = assertion.test
    if (not isinstance(comparison, ast.Compare) or len(comparison.ops) != 1 or not isinstance(comparison.ops[0], ast.Eq)
            or not isinstance(comparison.comparators[0], ast.Name) or comparison.comparators[0].id != answer):
        return set()
    call = comparison.left
    if (not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name) or call.func.id != provider
            or call.keywords or len(call.args) != 1 or not isinstance(call.args[0], ast.Name) or call.args[0].id != fixture.name):
        return set()
    rows = []
    for value in values.elts:
        class Bind(ast.NodeTransformer):
            def visit_Name(self, node):
                return copy.deepcopy(value) if node.id == fixture.name else node
        concrete = folded_expected(Bind().visit(copy.deepcopy(assignment.value)), lambda _name: False)
        if concrete is None or not _number(concrete):
            return set()
        rows.append(ast.Tuple(elts=[copy.deepcopy(value), concrete], ctx=ast.Load()))
    # Synthetic names never enter source execution; preserve original source
    # positions on the actual assertion for findings and source excerpts.
    input_name = '__checkwash_conditional_input'
    values.elts = rows
    target = ast.Tuple(elts=[ast.Name(id=input_name, ctx=ast.Store()), ast.Name(id=answer, ctx=ast.Store())], ctx=ast.Store())
    test.body[0] = ast.copy_location(ast.Assign(targets=[target], value=ast.Name(id=fixture.name, ctx=ast.Load())), assignment)
    call.args[0] = ast.copy_location(ast.Name(id=input_name, ctx=ast.Load()), call.args[0])
    return {test.name}

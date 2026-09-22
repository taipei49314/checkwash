"""Resolve closed integer-set fixture membership in literal parameter rows.

Only fresh default fixtures read by a direct membership expectation are
expanded. Every row retains its input, comparison operator and multiplicity.
The caller must require complete production and startup authority before
using these concrete rows in its existing table projection.
"""
from __future__ import annotations

import ast
import copy

from .callable_fixture_expectations import _parameters
from .oracle_blocks import IMPLICIT_ENTRY_NAMES
from .tuple_fixture_expectations import _integer
from checkwash.ir.astutil import dotted_name

_RESERVED = IMPLICIT_ENTRY_NAMES | {'pytest', 'pytestmark', 'pytest_plugins', 'request'}


def expand_parametrized_membership(tree):
    imported, functions, occupied, pytest = None, [], set(), False
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and type(node.value.value) is str:
            continue
        if (isinstance(node, ast.Import) and not functions and not pytest and len(node.names) == 1
                and node.names[0].name == 'pytest' and node.names[0].asname is None):
            name, pytest = 'pytest', True
        elif (isinstance(node, ast.ImportFrom) and not functions and imported is None and not node.level
                and node.module and len(node.names) == 1 and node.names[0].name != '*'):
            imported = node
            name = node.names[0].asname or node.names[0].name
        elif isinstance(node, ast.FunctionDef) and _parameters(node) is not None:
            name = node.name
            functions.append(node)
        else:
            return set()
        if (name in occupied or name.startswith(('__', 'pytest_'))
                or name in _RESERVED and not (name == 'pytest' and isinstance(node, ast.Import))):
            return set()
        occupied.add(name)
    if not pytest or imported is None or not 2 <= len(functions) <= 17:
        return set()
    fixture, tests = functions[0], functions[1:]
    if (fixture.name.startswith('test') or _parameters(fixture) != [] or len(fixture.decorator_list) != 1
            or len(fixture.body) != 1 or not isinstance(fixture.body[0], ast.Return)
            or not isinstance(fixture.body[0].value, ast.Set)
            or not 0 < len(fixture.body[0].value.elts) <= 64
            or not all(_integer(value) for value in fixture.body[0].value.elts)):
        return set()
    decorator = fixture.decorator_list[0]
    if isinstance(decorator, ast.Call) and not decorator.args and not decorator.keywords:
        decorator = decorator.func
    if dotted_name(decorator) != 'pytest.fixture':
        return set()
    members = {ast.literal_eval(value) for value in fixture.body[0].value.elts}
    provider = imported.names[0].asname or imported.names[0].name
    if provider.startswith('test'):
        return set()  # pytest can collect imported callables as additional tests
    replacements, rows = {}, 0
    for test in tests:
        args = _parameters(test)
        if (not test.name.startswith('test') or len(test.decorator_list) != 1
                or not 1 <= len(args) <= 2 or len(set(args)) != len(args)
                or set(args) & (_RESERVED | (occupied - {fixture.name}))
                or len(test.body) != 1 or not isinstance(test.body[0], ast.Assert) or test.body[0].msg is not None):
            return set()
        parameter = [name for name in args if name != fixture.name]
        if len(parameter) != 1:
            return set()
        parameter = parameter[0]
        decorator = test.decorator_list[0]
        if (not isinstance(decorator, ast.Call) or dotted_name(decorator.func) != 'pytest.mark.parametrize'
                or decorator.keywords or len(decorator.args) != 2
                or not isinstance(decorator.args[0], ast.Constant) or decorator.args[0].value != parameter
                or not isinstance(decorator.args[1], (ast.List, ast.Tuple))
                or not 0 < len(decorator.args[1].elts) <= 64
                or not all(_integer(value) for value in decorator.args[1].elts)):
            return set()
        values = decorator.args[1].elts
        rows += len(values)
        if rows > 64:
            return set()
        comparison = test.body[0].test
        if (not isinstance(comparison, ast.Compare) or len(comparison.ops) != 1
                or not isinstance(comparison.ops[0], (ast.Eq, ast.Is))):
            return set()
        call, expected = comparison.left, comparison.comparators[0]
        if (not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name) or call.func.id != provider
                or call.keywords or len(call.args) != 1 or not isinstance(call.args[0], ast.Name)
                or call.args[0].id != parameter):
            return set()
        if fixture.name not in args:
            if not isinstance(expected, ast.Constant) or type(expected.value) is not bool:
                return set()
            continue
        if (not isinstance(expected, ast.Compare) or len(expected.ops) != 1
                or not isinstance(expected.ops[0], (ast.In, ast.NotIn))
                or not isinstance(expected.left, ast.Name) or expected.left.id != parameter
                or not isinstance(expected.comparators[0], ast.Name) or expected.comparators[0].id != fixture.name):
            return set()
        clone = copy.deepcopy(test)
        answer_name = '__checkwash_membership_expected'
        if answer_name in occupied | set(args):
            return set()
        clone.args.args = [ast.arg(arg=parameter), ast.arg(arg=answer_name)]
        clone.decorator_list[0].args = [ast.Constant(value=parameter + ',' + answer_name), ast.List(elts=[
            ast.Tuple(elts=[copy.deepcopy(value), ast.Constant(value=(ast.literal_eval(value) in members)
                          == isinstance(expected.ops[0], ast.In))], ctx=ast.Load()) for value in values], ctx=ast.Load())]
        clone.body[0].test.comparators = [ast.copy_location(ast.Name(id=answer_name, ctx=ast.Load()), expected)]
        replacements[test] = clone
    if not replacements:
        return set()
    tree.body = [replacements.get(node, node) for node in tree.body if node is not fixture]
    return {node.name for node in replacements}

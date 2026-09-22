"""Expose closed string helper answers in literal parameter rows.

The displayed expected column is not the oracle when the assertion calls a
helper instead. Fold that helper only over the actual immutable row input;
the existing two-sided table proof owns production and execution authority.
"""
from __future__ import annotations

import ast
import copy

from .callable_fixture_expectations import _parameters
from .expected_constants import folded_expected
from .oracle_blocks import IMPLICIT_ENTRY_NAMES
from checkwash.ir.astutil import dotted_name

_RESERVED = IMPLICIT_ENTRY_NAMES | {'len', 'pytest', 'pytestmark', 'pytest_plugins', 'request'}


def _string(node):
    return isinstance(node, ast.Constant) and type(node.value) is str and len(node.value) <= 4096


def _answer(helper, argument):
    parameter = _parameters(helper)[0]
    if (len(helper.body) != 2 or not isinstance(helper.body[0], ast.If)
            or not isinstance(helper.body[1], ast.Return)):
        return None
    branch, final = helper.body
    if branch.orelse or len(branch.body) != 1 or not isinstance(branch.body[0], ast.Return):
        return None
    expressions = [branch.test, branch.body[0].value, final.value]
    for expression in expressions:
        if expression is None:
            return None
        for node in ast.walk(expression):
            if isinstance(node, ast.Name) and node.id not in {parameter, 'len'}:
                return None
            if isinstance(node, ast.Call) and (not isinstance(node.func, ast.Name) or node.func.id != 'len'
                    or node.keywords or len(node.args) != 1):
                return None

    class Substitute(ast.NodeTransformer):
        def visit_Name(self, node):
            return copy.deepcopy(argument) if node.id == parameter else node

    values = [folded_expected(Substitute().visit(copy.deepcopy(expression)), lambda name: name == 'len')
              for expression in expressions]
    if (not isinstance(values[0], ast.Constant) or type(values[0].value) is not bool
            or not all(_string(value) for value in values[1:])):
        return None
    return values[1] if values[0].value else values[2]


def expand_parameter_helper_answers(tree):
    imported, functions, occupied, pytest = None, [], set(), False
    for node in tree.body:
        if isinstance(node, ast.Expr) and _string(node.value):
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
    if not pytest or imported is None or len(functions) != 2:
        return set()
    helper, test = functions
    helper_args, parameters = _parameters(helper), _parameters(test)
    if (helper.name.startswith('test') or helper.decorator_list or len(helper_args) != 1
            or helper_args[0] in occupied | _RESERVED or helper_args[0].startswith('__')
            or not test.name.startswith('test') or len(parameters) != 2
            or set(parameters) & (occupied | _RESERVED) or any(name.startswith('__') for name in parameters)
            or len(test.decorator_list) != 1 or len(test.body) != 1
            or not isinstance(test.body[0], ast.Assert) or test.body[0].msg is not None):
        return set()
    provider = imported.names[0].asname or imported.names[0].name
    if provider.startswith('test'):
        return set()
    decorator = test.decorator_list[0]
    if (not isinstance(decorator, ast.Call) or dotted_name(decorator.func) != 'pytest.mark.parametrize'
            or decorator.keywords or len(decorator.args) != 2 or not _string(decorator.args[0])
            or [name.strip() for name in decorator.args[0].value.split(',')] != parameters
            or not isinstance(decorator.args[1], (ast.List, ast.Tuple))
            or not 0 < len(decorator.args[1].elts) <= 64):
        return set()
    comparison = test.body[0].test
    if (not isinstance(comparison, ast.Compare) or len(comparison.ops) != 1
            or not isinstance(comparison.ops[0], ast.Eq)):
        return set()
    for call, target in [(comparison.left, provider), (comparison.comparators[0], helper.name)]:
        if (not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name) or call.func.id != target
                or call.keywords or len(call.args) != 1 or not isinstance(call.args[0], ast.Name)
                or call.args[0].id != parameters[0]):
            return set()
    rows = []
    for row in decorator.args[1].elts:
        if not isinstance(row, (ast.List, ast.Tuple)) or len(row.elts) != 2 or not all(_string(value) for value in row.elts):
            return set()
        answer = _answer(helper, row.elts[0])
        if answer is None:
            return set()
        clone = copy.deepcopy(row)
        clone.elts[1] = ast.copy_location(answer, row.elts[1])
        rows.append(clone)
    clone = copy.deepcopy(test)
    clone.decorator_list[0].args[1].elts = rows
    clone.body[0].test.comparators = [ast.copy_location(ast.Name(id=parameters[1], ctx=ast.Load()), comparison.comparators[0])]
    tree.body = [clone if node is test else node for node in tree.body if node is not helper]
    return {test.name}

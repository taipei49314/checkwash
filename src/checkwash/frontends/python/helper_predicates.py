"""Expand fully accounted same-file predicate checks beside exact oracles.

These helpers contribute their complete assertion, never a substitute for the
production oracle. The caller must validate the resulting whole test body and
close production purity before using any projection.
"""
import ast
import copy
from collections import Counter

from checkwash.frontends.python.oracle_blocks import IMPLICIT_ENTRY_NAMES, _args


def _membership_helper(node):
    names = _args(node)
    if names is None or len(names) != 1 or len(node.body) != 1:
        return None
    assertion = node.body[0]
    if not isinstance(assertion, ast.Assert) or assertion.msg is not None:
        return None
    compare = assertion.test
    if (not isinstance(compare, ast.Compare) or len(compare.ops) != 1
            or not isinstance(compare.ops[0], (ast.In, ast.NotIn))
            or not isinstance(compare.left, ast.Constant) or type(compare.left.value) is not str
            or not isinstance(compare.comparators[0], ast.Name) or compare.comparators[0].id != names[0]):
        return None
    return assertion


def expand_predicate_helpers(tree):
    helpers = {node.name: candidate for node in tree.body if isinstance(node, ast.FunctionDef)
               and not node.name.startswith(('test', 'pytest_', '__')) and node.name not in IMPLICIT_ENTRY_NAMES
               and (candidate := _membership_helper(node)) is not None}
    if not helpers:
        return set()
    nodes = list(ast.walk(tree))
    bindings = Counter(node.id for node in nodes if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load))
    bindings.update(node.arg for node in nodes if isinstance(node, ast.arg))
    bindings.update(node.name for node in nodes if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))
    bindings.update(node.asname or node.name.split('.')[0] for node in nodes if isinstance(node, ast.alias))
    if any(bindings[name] != 1 for name in helpers):
        return None
    result, used, expanded = [], set(), set()
    for function in tree.body:
        if isinstance(function, ast.FunctionDef) and function.name in helpers:
            continue
        if isinstance(function, ast.FunctionDef) and function.name.startswith('test') and _args(function) == []:
            body = []
            for statement in function.body:
                call = statement.value if isinstance(statement, ast.Expr) else None
                if (isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id in helpers
                        and not call.keywords and len(call.args) == 1 and isinstance(call.args[0], ast.Name)):
                    assertion = copy.deepcopy(helpers[call.func.id])
                    assertion.test.comparators[0] = copy.deepcopy(call.args[0])
                    body.append(ast.copy_location(assertion, statement))
                    used.add(call.func.id)
                    expanded.add(function.name)
                else:
                    body.append(statement)
            function.body = body
        if any(isinstance(node, ast.Name) and node.id in helpers for node in ast.walk(function)):
            return None
        result.append(function)
    if used != helpers.keys():
        return None
    tree.body = result
    return expanded

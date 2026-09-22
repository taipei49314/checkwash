"""Remove only proven-true literal prefix predicates beside a real assertion.

This is a closed grammar for a two-argument same-file startswith helper. A
predicate is never promoted into a subject oracle, and a false predicate is
never erased. The caller closes every production import on both snapshots.
"""
import ast
import copy
from collections import Counter

from checkwash.frontends.python.oracle_blocks import IMPLICIT_ENTRY_NAMES, _args


def _prefix_helper(node):
    names = _args(node)
    if names is None or len(names) != 2 or len(set(names)) != 2 or len(node.body) != 1:
        return False
    statement = node.body[0]
    call = statement.value if isinstance(statement, ast.Return) else None
    return (isinstance(call, ast.Call) and not call.keywords and len(call.args) == 1
            and isinstance(call.func, ast.Attribute) and call.func.attr == 'startswith'
            and isinstance(call.func.value, ast.Name) and call.func.value.id == names[0]
            and isinstance(call.args[0], ast.Name) and call.args[0].id == names[1])


def _literal_predicate(node, helpers):
    negate = isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not)
    call = node.operand if negate else node
    if (not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name) or call.func.id not in helpers
            or call.keywords or len(call.args) != 2
            or not all(isinstance(arg, ast.Constant) and type(arg.value) is str for arg in call.args)):
        return None
    value = call.args[0].value.startswith(call.args[1].value)
    return (not value if negate else value), call.func.id


def expand_prefix_predicates(tree):
    helpers = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)
               and not node.name.startswith(('test', 'pytest_', '__')) and node.name not in IMPLICIT_ENTRY_NAMES
               and _prefix_helper(node)}
    if not helpers:
        return set()
    nodes = list(ast.walk(tree))
    bindings = Counter(node.id for node in nodes if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load))
    bindings.update(node.arg for node in nodes if isinstance(node, ast.arg))
    bindings.update(node.name for node in nodes if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))
    bindings.update(node.asname or node.name.split('.')[0] for node in nodes if isinstance(node, ast.alias))
    if any(bindings[name] != 1 for name in helpers):
        return None
    result, expanded, used = [], set(), set()
    for function in tree.body:
        if isinstance(function, ast.FunctionDef) and function.name in helpers:
            continue
        if (isinstance(function, ast.FunctionDef) and function.name.startswith('test') and _args(function) == []
                and len(function.body) == 1 and isinstance(function.body[0], ast.Assert)
                and function.body[0].msg is None):
            assertion = function.body[0]
            boolean = assertion.test
            if isinstance(boolean, ast.BoolOp) and isinstance(boolean.op, ast.And) and len(boolean.values) == 2:
                predicate = _literal_predicate(boolean.values[0], helpers)
                if predicate is not None and predicate[0]:
                    # The remaining clause must still pass the complete concrete
                    # assertion parser. A helper call alone gets no oracle credit.
                    assertion.test = copy.deepcopy(boolean.values[1])
                    used.add(predicate[1])
                    expanded.add(function.name)
        if any(isinstance(node, ast.Name) and node.id in helpers for node in ast.walk(function)):
            return None
        result.append(function)
    if used != helpers:
        return None
    tree.body = result
    return expanded

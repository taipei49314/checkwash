"""Ignore unreferenced, inert function definitions during table proof.

This does not credit helper calls or remove assertion helpers. A definition
must have no executable header and no possible reference in the module;
its body is additionally limited to a small expression-only grammar.
"""
from __future__ import annotations

import ast

_REFLECTION = {"getattr", "setattr", "delattr", "eval", "exec", "globals", "locals", "vars", "dir"}
_BUILTINS = {"len", "sum", "zip", "ValueError"}
_NODES = (
    ast.Return, ast.If, ast.Raise, ast.Expr, ast.Constant, ast.Name, ast.Load, ast.Store,
    ast.Call, ast.Compare, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
    ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not, ast.USub, ast.UAdd,
    ast.BinOp, ast.Add, ast.Sub, ast.Mult, ast.Mod, ast.Tuple, ast.List,
    ast.GeneratorExp, ast.comprehension,
)


def prune_inert_helpers(tree: ast.Module) -> None:
    nodes = list(ast.walk(tree))
    if any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
           and node.func.id in _REFLECTION for node in nodes):
        return
    bound = {node.id for node in nodes if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load)}
    bound.update(node.asname or node.name.split(".")[0] for node in nodes if isinstance(node, ast.alias))
    bound.update(node.name for node in nodes if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))
    for function in list(tree.body):
        if (not isinstance(function, ast.FunctionDef) or function.name.startswith(("test", "pytest_", "__"))
                or function.decorator_list or function.returns or getattr(function, "type_params", ())):
            continue
        args = function.args
        if args.defaults or args.kw_defaults or args.vararg or args.kwarg or args.kwonlyargs:
            continue
        if any(arg.annotation for arg in [*args.posonlyargs, *args.args]):
            continue
        name = function.name
        if any(node is not function and (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == name
            or isinstance(node, ast.Name) and node.id == name
            or isinstance(node, ast.arg) and node.arg == name
            or isinstance(node, ast.alias) and (node.asname or node.name.split(".")[0]) == name
            or isinstance(node, ast.Attribute) and node.attr == name
            or isinstance(node, ast.Constant) and isinstance(node.value, str) and name in node.value
            or isinstance(node, (ast.Global, ast.Nonlocal)) and name in node.names
        ) for node in nodes):
            continue
        body = [node for statement in function.body for node in ast.walk(statement)]
        if not body or not any(isinstance(node, ast.Return) for node in body):
            continue
        if any(not isinstance(node, _NODES) for node in body):
            continue
        if any(isinstance(node, ast.Expr) and not (isinstance(node.value, ast.Constant)
                                                  and isinstance(node.value.value, str)) for node in body):
            continue
        if any(isinstance(node, ast.Call) and (not isinstance(node.func, ast.Name)
                                               or node.func.id not in _BUILTINS or node.keywords)
               for node in body):
            continue
        called = {node.func.id for node in body if isinstance(node, ast.Call)}
        local = {arg.arg for arg in [*args.posonlyargs, *args.args]}
        local.update(node.id for node in body if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store))
        if called & (bound | local):
            continue
        if any(isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
               and node.id not in local | called for node in body):
            continue
        if any(isinstance(node, ast.comprehension) and node.is_async for node in body):
            continue
        tree.body.remove(function)

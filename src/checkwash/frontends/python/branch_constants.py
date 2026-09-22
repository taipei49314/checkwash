"""Closed scalar bindings that establish the truth of an assertion's branch."""
from __future__ import annotations

import ast
import copy


def literal_fixtures(tree: ast.Module) -> dict[str, ast.Constant]:
    """Only direct, argument-free pytest fixtures returning one scalar."""
    if not any(isinstance(node, ast.Import) and any(alias.name == "pytest" and not alias.asname
                                                  for alias in node.names) for node in tree.body):
        return {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "pytest" and isinstance(node.ctx, (ast.Store, ast.Del)):
            return {}
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == "pytest":
            return {}
        if isinstance(node, ast.alias) and (node.asname or node.name.split('.')[0]) == "pytest":
            if node.name != "pytest" or node.asname:
                return {}
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, (ast.Store, ast.Del)):
            if isinstance(node.value, ast.Name) and node.value.id == "pytest":
                return {}
    result = {}
    names = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names[node.name] = names.get(node.name, 0) + 1
    rebound = {node.id for node in ast.walk(tree)
               if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del))}
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or names[node.name] != 1 or node.name in rebound:
            continue
        args = node.args
        if args.posonlyargs or args.args or args.kwonlyargs or args.vararg or args.kwarg:
            continue
        if len(node.decorator_list) != 1 or len(node.body) != 1:
            continue
        decorator = node.decorator_list[0]
        if isinstance(decorator, ast.Call):
            if decorator.args or decorator.keywords:
                continue
            decorator = decorator.func
        if not (isinstance(decorator, ast.Attribute) and decorator.attr == "fixture"
                and isinstance(decorator.value, ast.Name) and decorator.value.id == "pytest"):
            continue
        value = node.body[0].value if isinstance(node.body[0], ast.Return) else None
        if isinstance(value, ast.Constant) and isinstance(value.value, (bool, int, float, str, type(None))):
            result[node.name] = value
    return result


def guard_truths(func, fixtures, static_truth):
    """Source-ordered literal locals; branch/loop writes invalidate later proof."""
    if not any(isinstance(node, (ast.If, ast.While)) for node in ast.walk(func)):
        return {}
    if any(isinstance(node, (ast.Global, ast.Nonlocal, ast.NamedExpr))
           or isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
           and node.func.id in {"exec", "eval", "locals", "globals", "vars"}
           for node in ast.walk(func)):
        return {}
    initial = {}
    args = func.args.posonlyargs + func.args.args + func.args.kwonlyargs
    if not func.decorator_list and not any(arg.arg in {"self", "cls"} for arg in args):
        initial = {arg.arg: fixtures[arg.arg] for arg in args if arg.arg in fixtures}
    known = {}

    class Resolve(ast.NodeTransformer):
        def __init__(self, bindings):
            self.bindings = bindings

        def visit_Name(self, node):
            return self.bindings.get(node.id, node)

    def resolve(node, bindings):
        return Resolve(bindings).visit(copy.deepcopy(node))

    def invalidate(statement, bindings):
        for node in ast.walk(statement):
            if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
                bindings.pop(node.id, None)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                bindings.pop(node.name, None)
            elif isinstance(node, ast.ExceptHandler) and node.name:
                bindings.pop(node.name, None)
            elif isinstance(node, ast.alias):
                bindings.pop(node.asname or node.name.split('.')[0], None)

    def scan(body, bindings):
        for statement in body:
            if isinstance(statement, (ast.Return, ast.Raise, ast.Break, ast.Continue)):
                return
            if isinstance(statement, (ast.Assign, ast.AnnAssign)):
                value = resolve(statement.value, bindings) if statement.value else None
                invalidate(statement, bindings)
                targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
                if isinstance(value, ast.Constant) and isinstance(value.value, (bool, int, float, str, type(None))):
                    for target in targets:
                        if isinstance(target, ast.Name):
                            bindings[target.id] = value
                continue
            if isinstance(statement, (ast.If, ast.While)):
                truth = static_truth(resolve(statement.test, bindings))
                if truth is not None:
                    known[id(statement)] = truth
                if isinstance(statement, ast.If) and truth is not None:
                    scan(statement.body if truth else statement.orelse, bindings)
                    continue
                # Bodies may be repeated or conditionally skipped. Remove any
                # names they can change before deriving nested/later guards.
                invalidate(statement, bindings)
                scan(statement.body, dict(bindings))
                scan(statement.orelse, dict(bindings))
                continue
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                bindings.pop(statement.name, None)
                continue
            invalidate(statement, bindings)
            for field in ("body", "orelse", "finalbody"):
                nested = getattr(statement, field, None)
                if isinstance(nested, list):
                    scan(nested, dict(bindings))
    scan(func.body, initial)
    return known

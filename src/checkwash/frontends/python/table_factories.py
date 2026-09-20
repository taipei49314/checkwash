"""Inline closed table factory calls used only as parametrize row sources."""
from __future__ import annotations

import ast
import copy


def expand_literal_table_factories(tree: ast.Module) -> None:
    candidates = {}
    for node in tree.body:
        if (not isinstance(node, ast.FunctionDef) or node.name.startswith("test") or node.decorator_list
                or node.returns or getattr(node, "type_params", ()) or len(node.body) != 1
                or not isinstance(node.body[0], ast.Return)):
            continue
        args = node.args
        if args.posonlyargs or args.args or args.kwonlyargs or args.vararg or args.kwarg or args.defaults:
            continue
        value = node.body[0].value
        if not isinstance(value, (ast.List, ast.Tuple, ast.Dict)):
            continue
        try:
            literal = ast.literal_eval(value)
        except (ValueError, TypeError, SyntaxError, RecursionError, MemoryError):
            continue
        if not 1 <= len(literal) <= 64:
            continue
        if isinstance(value, ast.Dict) and (any(key is None for key in value.keys) or len(literal) != len(value.keys)):
            continue
        candidates[node.name] = (node, value)
    for name, (definition, value) in candidates.items():
        loads = []
        unsafe = False
        definitions = 0
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == name:
                definitions += 1
            if isinstance(node, ast.Name) and node.id == name:
                if isinstance(node.ctx, ast.Load):
                    loads.append(node)
                else:
                    unsafe = True
            if isinstance(node, ast.arg) and node.arg == name:
                unsafe = True
            if isinstance(node, ast.alias) and (node.asname or node.name.split('.')[0]) == name:
                unsafe = True
            if isinstance(node, (ast.Global, ast.Nonlocal)) and name in node.names:
                unsafe = True
            if isinstance(node, ast.Attribute) and isinstance(node.ctx, (ast.Store, ast.Del)):
                if isinstance(node.value, ast.Name) and node.value.id == name:
                    unsafe = True
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {
                "getattr", "setattr", "delattr", "eval", "exec", "globals", "locals", "vars",
            }:
                unsafe = True
        if unsafe or definitions != 1 or not loads:
            continue
        replacements = []
        for function in tree.body:
            if not isinstance(function, ast.FunctionDef):
                continue
            for decorator in function.decorator_list:
                if (not isinstance(decorator, ast.Call) or len(decorator.args) != 2
                        or ast.unparse(decorator.func) != "pytest.mark.parametrize"):
                    continue
                source = decorator.args[1]
                items = isinstance(source, ast.Call) and isinstance(source.func, ast.Attribute) and source.func.attr == "items"
                call = source.func.value if items else source
                if (not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name) or call.func.id != name
                        or call.args or call.keywords or items and (source.args or source.keywords)):
                    continue
                if items != isinstance(value, ast.Dict):
                    continue
                rows = value
                if items:
                    rows = ast.List(elts=[ast.Tuple(elts=[copy.deepcopy(key), copy.deepcopy(cell)], ctx=ast.Load())
                                          for key, cell in zip(value.keys, value.values)], ctx=ast.Load())
                    ast.copy_location(rows, value)
                replacements.append((decorator, call.func, rows))
        if {id(load) for load in loads} != {id(call) for _, call, _ in replacements}:
            continue
        for decorator, _, rows in replacements:
            decorator.args[1] = copy.deepcopy(rows)
        tree.body.remove(definition)

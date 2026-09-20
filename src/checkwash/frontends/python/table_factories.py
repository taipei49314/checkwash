"""Inline closed literal table factories at fully accounted consumer sites."""
from __future__ import annotations

import ast
import copy


def _immutable(node):
    if isinstance(node, ast.Constant):
        return type(node.value) in (type(None), bool, int, float, str, bytes)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        return isinstance(node.operand, ast.Constant) and type(node.operand.value) in (int, float)
    return isinstance(node, ast.Tuple) and all(_immutable(item) for item in node.elts)


def _factory_call(node, name):
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == name
            and not node.args and not node.keywords)


def expand_literal_table_factories(tree: ast.Module) -> set[str]:
    consumers = set()
    candidates = {}
    for node in tree.body:
        if (not isinstance(node, ast.FunctionDef) or node.name.startswith(("pytest_", "__")) or node.decorator_list
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
                replacements.append((decorator, "args", [decorator.args[0], copy.deepcopy(rows)], call.func, function.name))
            # A fresh table allocation, one literal row, then ordinary helper
            # argument binding. No row object is shared across invocations.
            if not function.decorator_list and len(function.body) == 1 and isinstance(function.body[0], ast.Expr):
                outer = function.body[0].value
                if (isinstance(outer, ast.Call) and isinstance(outer.func, ast.Name) and len(outer.args) == 1
                        and not outer.keywords and isinstance(outer.args[0], ast.Starred)):
                    selected = outer.args[0].value
                    if (isinstance(selected, ast.Subscript) and _factory_call(selected.value, name)
                            and isinstance(selected.slice, ast.Constant) and type(selected.slice.value) is int
                            and isinstance(value, (ast.List, ast.Tuple)) and 0 <= selected.slice.value < len(value.elts)):
                        row = value.elts[selected.slice.value]
                        if isinstance(row, (ast.List, ast.Tuple)):
                            replacements.append((outer, "args", copy.deepcopy(row.elts), selected.value.func, function.name))
            # A default table is evaluated once. Only deeply immutable rows,
            # consumed by the sole loop without exposing the table, can be
            # represented by a fresh literal loop without changing aliasing.
            args = function.args
            if (not function.decorator_list and not function.returns and not args.posonlyargs
                    and len(args.args) == 1 and not args.args[0].annotation and not args.kwonlyargs
                    and not args.vararg and not args.kwarg and len(args.defaults) == 1
                    and _factory_call(args.defaults[0], name) and isinstance(value, (ast.List, ast.Tuple))
                    and all(_immutable(row) for row in value.elts) and len(function.body) == 1
                    and isinstance(function.body[0], ast.For)):
                loop, parameter = function.body[0], args.args[0].arg
                references = [node for node in ast.walk(function.body[0]) if isinstance(node, ast.Name) and node.id == parameter]
                if (not loop.orelse and isinstance(loop.iter, ast.Name) and loop.iter.id == parameter
                        and references == [loop.iter]
                        and not any(isinstance(node, ast.Name) and node.id == function.name
                                    or isinstance(node, ast.Attribute) and node.attr == function.name
                                    for node in ast.walk(tree))):
                    replacements.append((loop, "iter", copy.deepcopy(value), args.defaults[0].func, function.name))
                    replacements.append((args, "args", [], None, function.name))
                    replacements.append((args, "defaults", [], None, function.name))
        if {id(load) for load in loads} != {id(call) for _, _, _, call, _ in replacements if call is not None}:
            continue
        for target, attribute, replacement, _, consumer in replacements:
            setattr(target, attribute, replacement)
            consumers.add(consumer)
        tree.body.remove(definition)
    return consumers

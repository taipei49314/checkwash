"""Prove direct asserted production-call replacements without broad call scans.

Only the root subject call in an existing paired literal equality is eligible.
The arguments and expectation must stay identical, the old callable must have
a repository import, and the new callable must be a builtin, bounded pure
same-file stand-in, or literal-return unittest.mock object. Ordinary helper
extraction forwarding production, import renames and expected-side edits do
not satisfy this predicate.
"""
from __future__ import annotations

import ast

from checkwash.change import EngineError
from checkwash.conftest_context import ConftestContext
from checkwash.ir.astutil import stable_dump
from checkwash.ir.markers import parse_expr
from checkwash.pyenv import known_baseline

_BUILTINS = frozenset({"abs", "all", "any", "bool", "dict", "enumerate", "float", "int",
                      "len", "list", "max", "min", "range", "reversed", "round", "set",
                      "sorted", "str", "sum", "tuple", "zip"})
_MOCKS = {"unittest.mock.Mock", "unittest.mock.MagicMock", "mock.Mock", "mock.MagicMock"}


def _parse(data):
    if not isinstance(data, bytes):
        return None
    if len(data) > 1_000_000:
        raise EngineError("subject replacement source exceeds the byte limit")
    try:
        tree = ast.parse(data.decode("utf-8-sig"))
    except (SyntaxError, UnicodeError, ValueError, RecursionError):
        return None
    if sum(1 for _ in ast.walk(tree)) > 30_000:
        raise EngineError("subject replacement source exceeds the syntax node limit")
    return tree


def _bindings(statements):
    values = {}
    for stmt in statements:
        if isinstance(stmt, ast.Import):
            for alias in stmt.names:
                values[alias.asname or alias.name.split(".")[0]] = alias.name if alias.asname else alias.name.split(".")[0]
        elif isinstance(stmt, ast.ImportFrom) and not stmt.level:
            for alias in stmt.names:
                values[alias.asname or alias.name] = f"{stmt.module}.{alias.name}"
        elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            values[stmt.name] = stmt
        elif isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            for target in stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]:
                if isinstance(target, ast.Name):
                    values[target.id] = stmt.value
        elif isinstance(stmt, (ast.If, ast.For, ast.While, ast.Try, ast.With)):
            # Unknown control flow cannot prove that a name still has its
            # unconditional import, builtin, or local helper binding.
            for node in ast.walk(stmt):
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                    values[node.id] = None
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    values[node.name] = None
                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    for alias in node.names:
                        values[alias.asname or alias.name.split(".")[0]] = None
    return values


def _resolve(expr, bindings, pending=frozenset()):
    if isinstance(expr, ast.Name):
        if expr.id in pending:
            return None
        if expr.id not in bindings:
            return "builtins." + expr.id if expr.id in _BUILTINS else None
        value = bindings[expr.id]
        return _resolve(value, bindings, pending | {expr.id}) if isinstance(value, (ast.Name, ast.Attribute)) else value
    if isinstance(expr, ast.Attribute):
        parent = _resolve(expr.value, bindings, pending)
        return parent + "." + expr.attr if isinstance(parent, str) else None
    return expr


def _pure(node, parameters, bindings, pending=frozenset()):
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.Name):
        if node.id in parameters:
            return True
        if node.id in pending:
            return False
        value = bindings.get(node.id)
        return isinstance(value, ast.AST) and _pure(value, parameters, bindings, pending | {node.id})
    if isinstance(node, ast.Call):
        fn = _resolve(node.func, bindings)
        return (isinstance(fn, str) and fn in {"builtins." + name for name in _BUILTINS}
                and all(_pure(arg, parameters, bindings, pending) for arg in node.args)
                and all(kw.arg is not None and _pure(kw.value, parameters, bindings, pending) for kw in node.keywords))
    if isinstance(node, (ast.List, ast.Tuple, ast.Set, ast.Dict, ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.IfExp, ast.Subscript, ast.Slice)):
        return all(_pure(child, parameters, bindings, pending) for child in ast.iter_child_nodes(node)
                   if isinstance(child, ast.expr))
    return False


def _standin(value, bindings):
    if isinstance(value, str):
        return value in {"builtins." + name for name in _BUILTINS}
    if isinstance(value, ast.Call):
        fn = _resolve(value.func, bindings)
        return (isinstance(fn, str) and fn in _MOCKS and not value.args
                and len(value.keywords) == 1 and value.keywords[0].arg == "return_value"
                and _pure(value.keywords[0].value, set(), bindings))
    if isinstance(value, (ast.FunctionDef, ast.AsyncFunctionDef)):
        body = value.body
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
            body = body[1:]
        if value.decorator_list or len(body) != 1 or not isinstance(body[0], ast.Return):
            return False
        expression = body[0].value
    elif isinstance(value, ast.Lambda):
        expression = value.body
    else:
        return False
    parameters = {a.arg for a in value.args.posonlyargs + value.args.args + value.args.kwonlyargs}
    if value.args.vararg:
        parameters.add(value.args.vararg.arg)
    if value.args.kwarg:
        parameters.add(value.args.kwarg.arg)
    return expression is not None and _pure(expression, parameters, bindings)


def _scoped_bindings(tree, qualname, assertion):
    bindings = _bindings(tree.body)
    scope = tree
    for part in qualname.split("."):
        scope = next((node for node in scope.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == part), None)
        if scope is None:
            return None
    if not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return None
    for arg in scope.args.posonlyargs + scope.args.args + scope.args.kwonlyargs:
        bindings[arg.arg] = None
    # Reaching definitions belong to this assertion, avoiding a later local
    # assignment being attributed to an earlier invocation.
    for name, expression in (assertion.reaching or {}).items():
        if expression:
            parsed = parse_expr(expression)
            bindings[name] = parsed
    bindings.update({name: value for name, value in _bindings(scope.body).items()
                     if isinstance(value, (ast.FunctionDef, ast.AsyncFunctionDef))})
    return bindings


def subject_replacement_events(ir, changes, *, root_reader=None):
    if root_reader is None:
        return []
    context = ConftestContext(changes, root_reader)
    deny = known_baseline() | set(ir.globals.third_party_roots)
    by_path = {c.path: c for c in changes}
    events = []
    for file in ir.files:
        change = by_path.get(file.path)
        if file.role != "test" or change is None or not change.before or not change.after:
            continue
        trees = None
        for unit in file.units:
            if unit.before is None or unit.after is None or unit.delta is None:
                continue
            before = {a.id: a for a in unit.before.assertions}
            after = {a.id: a for a in unit.after.assertions}
            for pair in unit.delta.assertion_pairs:
                b, a = before[pair.before_id], after[pair.after_id]
                if (a.inherited or b.inherited or b.form != "compare_eq" or a.form != b.form
                        or not b.positive or not a.positive or b.right_literal is None
                        or a.right_literal != b.right_literal):
                    continue
                old_call, new_call = parse_expr(b.left or ""), parse_expr(a.left or "")
                if not isinstance(old_call, ast.Call) or not isinstance(new_call, ast.Call):
                    continue
                if (stable_dump(old_call.func) == stable_dump(new_call.func)
                        or stable_dump(ast.Tuple(elts=old_call.args, ctx=ast.Load())) != stable_dump(ast.Tuple(elts=new_call.args, ctx=ast.Load()))
                        or [stable_dump(k) for k in old_call.keywords] != [stable_dump(k) for k in new_call.keywords]):
                    continue
                if trees is None:
                    trees = (_parse(change.before), _parse(change.after))
                if any(tree is None for tree in trees):
                    continue
                old_bindings = _scoped_bindings(trees[0], unit.qualname, b)
                new_bindings = _scoped_bindings(trees[1], unit.qualname, a)
                if old_bindings is None or new_bindings is None:
                    continue
                target = _resolve(old_call.func, old_bindings)
                replacement = _resolve(new_call.func, new_bindings)
                if (not isinstance(target, str) or target.split(".", 1)[0] in deny
                        or not context.contains(target, 0) or not _standin(replacement, new_bindings)):
                    continue
                events.append((file.path, unit.qualname, target, a.text, a.span))
    return sorted(set(events))

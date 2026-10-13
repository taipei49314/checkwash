"""One ordered module-level native-spelled assertEqual no-op replacement.

This is a bounded AST proof, not a monkeypatch resolver. Only direct native
imports establish the target; repository import shadowing and other modules'
later writes are outside this frontend's static import convention.
"""
from __future__ import annotations

import ast
from collections.abc import Iterator


_MODULE, _CASE = "unittest-module", "unittest-TestCase"
_ORIGINAL, _NOOP, _OTHER = "original", "noop", "other"


def _assert_literal_branch(node: ast.AST) -> bool | None:
    negate = False
    while isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        negate, node = not negate, node.operand
    if isinstance(node, ast.Constant) and type(node.value) is bool:
        return not node.value if negate else node.value
    return None


def _assert_statements(body: list[ast.stmt]) -> Iterator[ast.stmt]:
    pending = list(reversed(body))
    while pending:
        statement = pending.pop()
        if isinstance(statement, ast.If):
            branch = _assert_literal_branch(statement.test)
            if branch is not None:
                pending.extend(reversed(statement.body if branch else statement.orelse))
                continue
        yield statement


def _assert_plain_definition(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    args = node.args
    parameters = [*args.posonlyargs, *args.args, *args.kwonlyargs,
                  *([args.vararg] if args.vararg else []),
                  *([args.kwarg] if args.kwarg else [])]
    return (not node.decorator_list and node.returns is None
            and not getattr(node, "type_params", ()) and not args.defaults
            and not any(value is not None for value in args.kw_defaults)
            and not any(arg.annotation is not None for arg in parameters))


def _assert_empty_lambda(node: ast.Lambda) -> bool:
    args = node.args
    return (not args.posonlyargs and len(args.args) == 1 and not args.kwonlyargs
            and args.vararg is not None and args.kwarg is not None
            and not args.defaults and not args.kw_defaults
            and isinstance(node.body, ast.Constant) and node.body.value is None)


def _assert_native_class(node: ast.AST, bindings: dict[str, str]) -> bool:
    if isinstance(node, ast.Name):
        return bindings.get(node.id) == _CASE
    return (isinstance(node, ast.Attribute) and node.attr == "TestCase"
            and isinstance(node.value, ast.Name) and bindings.get(node.value.id) == _MODULE)


def _assert_native_method(node: ast.AST, bindings: dict[str, str]) -> bool:
    return (isinstance(node, ast.Attribute) and node.attr == "assertEqual"
            and _assert_native_class(node.value, bindings))


def _assert_value(node: ast.AST, bindings: dict[str, str], current: str) -> tuple[bool, str]:
    if isinstance(node, ast.Name):
        if node.id not in bindings:
            return False, _OTHER  # An unexplained read may stop module execution.
        value = bindings[node.id]
        # Only direct imports grant module/class authority. Do not recursively
        # resolve object aliases; method and no-op value captures stay local.
        return True, _OTHER if value in {_MODULE, _CASE} else value
    if _assert_native_method(node, bindings):
        return True, current
    if isinstance(node, ast.Constant):
        return True, _OTHER
    if isinstance(node, ast.Lambda):
        if node.args.defaults or any(value is not None for value in node.args.kw_defaults):
            return False, _OTHER
        return True, _NOOP if _assert_empty_lambda(node) else _OTHER
    return False, _OTHER


def _assert_final_replacement(tree: ast.Module) -> ast.Assign | None:
    bindings: dict[str, str] = {}
    current = _ORIGINAL
    evidence: ast.Assign | None = None
    for node in _assert_statements(tree.body):
        if isinstance(node, ast.Import):
            # Do not infer absence of effects from an arbitrary module import.
            if any(alias.name != "unittest" for alias in node.names):
                return None
            for alias in node.names:
                bindings[alias.asname or alias.name] = _MODULE
        elif isinstance(node, ast.ImportFrom):
            if node.level or node.module != "unittest" or any(alias.name != "TestCase" for alias in node.names):
                return None
            for alias in node.names:
                bindings[alias.asname or alias.name] = _CASE
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not _assert_plain_definition(node):
                return None
            bindings[node.name] = _OTHER  # Defining an uncalled body does not execute it.
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            known, value = _assert_value(node.value, bindings, current)
            if not known:
                return None
            target = node.targets[0]
            if isinstance(target, ast.Name):
                bindings[target.id] = value
            elif _assert_native_method(target, bindings):
                current = value
                evidence = node if value == _NOOP else None
            else:
                return None  # Unknown attribute writes may alias or replace the target.
        elif isinstance(node, ast.Pass) or (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)):
            continue
        else:
            # Calls, raises, unknown compounds and definition-time work have
            # no normal module-completion proof. Do not keep a stale effect.
            return None
    return evidence


def unittest_assertion_controls(tree: ast.Module) -> Iterator[tuple[str, ast.AST]]:
    evidence = _assert_final_replacement(tree)
    if evidence is not None:
        yield "conftest.runtime.unittest.TestCase.assertEqual-noop", evidence

"""Finite source evidence for direct bare assertions behind standard os guards.

No environment is evaluated; unknown bindings and compound control flow stay
outside this proof. The assertion inventory itself is never changed.
"""
from __future__ import annotations

import ast
from typing import Protocol, TypeAlias

from checkwash.ir.astutil import stable_dump


ObligationEvidence: TypeAlias = tuple[bool, str | None, tuple[int, int] | None]
ObligationKey: TypeAlias = tuple[int, str]


class EnvironmentOffsets(Protocol):
    tree: ast.AST | None
    _environment_standard_os: bool | None

    def seg(self, node: ast.AST) -> str: ...

    def span(self, node: ast.AST) -> tuple[int, int]: ...


def _standard_os(tree: ast.Module) -> bool:
    imports = [alias for node in tree.body if isinstance(node, ast.Import)
               for alias in node.names if alias.name == "os" and alias.asname is None]
    if len(imports) != 1:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "os" and isinstance(node.ctx, (ast.Store, ast.Del)):
            return False
        if isinstance(node, ast.arg) and node.arg == "os":
            return False
        if isinstance(node, ast.ExceptHandler) and node.name == "os":
            return False
        if isinstance(node, ast.ImportFrom) and any(alias.name == "*" for alias in node.names):
            return False
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == "os":
            return False
        if isinstance(node, ast.alias) and (node.asname or node.name.split(".")[0]) == "os":
            if node not in imports:
                return False
        if isinstance(node, ast.Attribute):
            root: ast.AST = node
            while isinstance(root, ast.Attribute):
                root = root.value
            if isinstance(root, ast.Name) and root.id == "os" and isinstance(node.ctx, (ast.Store, ast.Del)):
                return False
        if isinstance(node, ast.Subscript) and isinstance(node.ctx, (ast.Store, ast.Del)):
            if (isinstance(node.value, ast.Attribute) and isinstance(node.value.value, ast.Name)
                    and node.value.value.id == "os"):
                return False
        if isinstance(node, ast.Call):
            target = node.func
            if isinstance(target, ast.Name) and target.id in ("exec", "eval", "globals", "locals", "vars", "setattr", "delattr"):
                return False
            if (isinstance(target, ast.Attribute) and isinstance(target.value, ast.Attribute)
                    and isinstance(target.value.value, ast.Name) and target.value.value.id == "os"
                    and target.value.attr == "environ" and target.attr != "get"):
                return False
    return True


def _environment_test(node: ast.AST) -> bool:
    if not (isinstance(node, ast.Compare) and len(node.ops) == 1
            and isinstance(node.ops[0], (ast.Eq, ast.NotEq))
            and len(node.comparators) == 1 and isinstance(node.comparators[0], ast.Constant)
            and isinstance(node.comparators[0].value, str)):
        return False
    call = node.left
    return (isinstance(call, ast.Call) and not call.keywords and len(call.args) == 1
            and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str)
            and isinstance(call.func, ast.Attribute) and call.func.attr == "get"
            and isinstance(call.func.value, ast.Attribute) and call.func.value.attr == "environ"
            and isinstance(call.func.value.value, ast.Name) and call.func.value.value.id == "os")


def obligation_evidence(
    func: ast.FunctionDef | ast.AsyncFunctionDef, offsets: EnvironmentOffsets,
) -> dict[int, ObligationEvidence]:
    """node id -> (unconditional, guard text, guard span), only finite shapes."""
    tree = offsets.tree
    eligible = any(isinstance(statement, ast.If) and _environment_test(statement.test)
                   for statement in func.body)
    if eligible and offsets._environment_standard_os is None:
        offsets._environment_standard_os = isinstance(tree, ast.Module) and _standard_os(tree)
    credit_enabled = eligible and offsets._environment_standard_os is True
    out: dict[int, ObligationEvidence] = {}
    keys: dict[int, ObligationKey] = {}
    unconditional: set[ObligationKey] = set()
    pending: ast.If | bool | None = None
    binding_epoch = 0
    for statement in func.body:
        if isinstance(statement, ast.Assert):
            key = (binding_epoch, stable_dump(statement.test)) if credit_enabled else None
            if key is not None:
                keys[id(statement)] = key
            if pending is None:
                if key is not None:
                    unconditional.add(key)
                out[id(statement)] = (True, None, None)
            elif isinstance(pending, ast.If):
                out[id(statement)] = (False, offsets.seg(pending.test), offsets.span(pending.test))
            continue
        if isinstance(statement, ast.Return):
            break
        if isinstance(statement, ast.If):
            if pending is not None or not _environment_test(statement.test):
                pending = False
                continue
            if not credit_enabled:
                pending = False
                continue
            if (len(statement.body) == 1 and isinstance(statement.body[0], ast.Return)
                    and statement.body[0].value is None and not statement.orelse):
                pending = statement
                continue
            if not all(isinstance(item, (ast.Assert, ast.Pass))
                       for item in statement.body + statement.orelse):
                pending = False
                continue
            for item in statement.body + statement.orelse:
                if isinstance(item, ast.Assert):
                    keys[id(item)] = (binding_epoch, stable_dump(item.test))
            arms: list[set[ObligationKey]] = [{keys[id(item)]
                     for item in arm if isinstance(item, ast.Assert)}
                    for arm in (statement.body, statement.orelse)]
            unconditional.update(arms[0] & arms[1])
            for item in statement.body + statement.orelse:
                if isinstance(item, ast.Assert):
                    out[id(item)] = (False, offsets.seg(statement.test), offsets.span(statement.test))
            continue
        if isinstance(statement, ast.Pass) or (
                isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant)
                and isinstance(statement.value.value, str)):
            continue
        # Defs can rebind a callee and expressions can mutate its inputs.
        # Every other direct statement is a conservative credit barrier;
        # only pass and literal string expressions are explicitly inert.
        binding_epoch += 1
        if pending is not None or isinstance(statement, (
                ast.For, ast.AsyncFor, ast.While, ast.Try, ast.With, ast.AsyncWith, ast.Match)):
            pending = False
    # Only direct assertions participate. Neither helper nor inherited copies
    # can supply the complementary-branch proof.
    # Ordinary files need only the baseline booleans, never a structural dump.
    if not credit_enabled:
        return out
    for node in func.body:
        candidates = [node] if isinstance(node, ast.Assert) else (
            node.body + node.orelse if isinstance(node, ast.If) else [])
        for assertion in candidates:
            if (isinstance(assertion, ast.Assert) and id(assertion) in out
                    and keys[id(assertion)] in unconditional):
                out[id(assertion)] = (True, None, None)
    return out

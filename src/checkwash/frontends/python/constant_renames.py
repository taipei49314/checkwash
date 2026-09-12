"""Proof of a complete, literal module-constant alpha rename in a test file."""
from __future__ import annotations

import ast
import copy

from checkwash.ir.astutil import stable_dump


def literal_constant_renames(before: bytes | None, after: bytes | None) -> dict[str, str]:
    if not before or not after or max(len(before), len(after)) > 65536:
        return {}
    try:
        b, a = ast.parse(before), ast.parse(after)
        if max(sum(1 for _ in ast.walk(b)), sum(1 for _ in ast.walk(a))) > 4096:
            return {}
        def constants(tree):
            found = {}
            for node in tree.body:
                if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                    name, value = node.targets[0].id, node.value
                elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value:
                    name, value = node.target.id, node.value
                else:
                    continue
                try:
                    ast.literal_eval(value)
                except (ValueError, TypeError):
                    continue
                if name in found:
                    return {}
                found[name] = stable_dump(value)
            return found
        bc, ac = constants(b), constants(a)
        removed, added = bc.keys() - ac.keys(), ac.keys() - bc.keys()
        if not removed or len(removed) != len(added):
            return {}
        mapping = {}
        for name in sorted(removed):
            candidates = [new for new in added if ac[new] == bc[name]]
            if len(candidates) != 1 or candidates[0] in mapping.values():
                return {}
            mapping[name] = candidates[0]
        for tree, names in ((b, set(mapping)), (a, set(mapping.values()))):
            # Parameters, nested assignments or reflective name lookup make
            # a spelling replacement something other than this simple proof.
            stores = {name: 0 for name in names}
            forbidden = set(mapping.values()) if tree is b else set(mapping)
            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and node.id in forbidden:
                    return {}
                if isinstance(node, ast.arg) and node.arg in names:
                    return {}
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name in names | forbidden:
                    return {}
                if isinstance(node, ast.alias) and (node.asname or node.name.split(".")[0]) in names | forbidden:
                    return {}
                if isinstance(node, (ast.Global, ast.Nonlocal)) and set(node.names) & (names | forbidden):
                    return {}
                if isinstance(node, ast.Name):
                    if node.id in {"globals", "locals", "vars", "eval", "exec", "getattr", "setattr", "__all__"}:
                        return {}
                    if node.id in names and isinstance(node.ctx, (ast.Store, ast.Del)):
                        stores[node.id] += 1
            if any(count != 1 for count in stores.values()):
                return {}
        class Rename(ast.NodeTransformer):
            def visit_Name(self, node):
                if node.id in mapping:
                    node.id = mapping[node.id]
                return node
        return mapping if stable_dump(Rename().visit(copy.deepcopy(b))) == stable_dump(a) else {}
    except (SyntaxError, ValueError, TypeError, RecursionError, MemoryError):
        return {}


def assertions_renamed(before, after, mapping) -> bool:
    if not mapping:
        return False
    try:
        b, a = ast.parse(before.text), ast.parse(after.text)
        class Rename(ast.NodeTransformer):
            def visit_Name(self, node):
                if node.id in mapping:
                    node.id = mapping[node.id]
                return node
        return stable_dump(Rename().visit(b)) == stable_dump(a)
    except (SyntaxError, ValueError, TypeError, RecursionError, MemoryError):
        return False

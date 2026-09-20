"""Resolve concrete same-file inherited pytest methods without executing classes."""

from __future__ import annotations

import ast


def inherited_test_methods(tree: ast.Module):
    """Yield (collecting class, defining class, method) in local C3 order.

    Only an entirely local, unconditional class hierarchy is resolved. Unknown
    bases, decorators, metaclasses and conflicting definitions cannot establish
    which body pytest will invoke, so they retain the ordinary lexical view.
    """
    classes: dict[str, ast.ClassDef] = {}
    ambiguous: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            if node.name in classes:
                ambiguous.add(node.name)
            classes[node.name] = node
    if not any(name.startswith("Test") for name in classes):
        return
    # A class name or one of its attributes may be rebound after definition.
    # Such a file no longer describes the concrete hierarchy used below.
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            if node.id in classes:
                ambiguous.add(node.id)
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, (ast.Store, ast.Del)):
            root = node.value
            while isinstance(root, (ast.Attribute, ast.Subscript)):
                root = root.value
            if isinstance(root, ast.Name) and root.id in classes:
                ambiguous.add(root.id)
        elif isinstance(node, ast.alias) and (node.asname or node.name.split('.')[0]) in classes:
            ambiguous.add(node.asname or node.name.split('.')[0])
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in {"setattr", "delattr", "exec", "eval", "globals", "locals", "vars"}:
                ambiguous.update(classes)
    resolved: dict[str, tuple[str, ...] | None] = {}

    def mro(name: str, active: frozenset[str] = frozenset()):
        if name == "object" and name not in classes:
            return ("object",)
        if name in resolved:
            return resolved[name]
        node = classes.get(name)
        if (node is None or name in active or name in ambiguous
                or node.decorator_list or node.keywords
                or any(not isinstance(base, ast.Name) for base in node.bases)):
            return None
        bases = [base.id for base in node.bases]
        if len(set(bases)) != len(bases):
            return None
        linear = [mro(base, active | {name}) for base in bases]
        if any(order is None for order in linear):
            return None
        sequences = [list(order) for order in linear] + [list(bases)]
        result = [name]
        while any(sequences):
            sequences = [sequence for sequence in sequences if sequence]
            candidate = next((sequence[0] for sequence in sequences
                              if not any(sequence[0] in other[1:]
                                         for other in sequences)), None)
            if candidate is None:
                return None
            result.append(candidate)
            for sequence in sequences:
                if sequence and sequence[0] == candidate:
                    sequence.pop(0)
        resolved[name] = tuple(result)
        return resolved[name]

    for name, node in classes.items():
        if not name.startswith("Test"):
            continue
        order = mro(name)
        if order is None:
            continue
        # Any direct attribute definition shadows the inherited name, even a
        # non-callable assignment. The first class binding wins under C3.
        bound: set[str] = set()
        disabled = False
        methods = []
        for owner in order:
            parent = classes.get(owner)
            if parent is None:
                continue
            local: dict[str, ast.AST] = {}
            for statement in parent.body:
                if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    local[statement.name] = statement
                elif isinstance(statement, (ast.Assign, ast.AnnAssign)):
                    targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
                    for target in targets:
                        if isinstance(target, ast.Name):
                            local[target.id] = statement.value
                elif not (isinstance(statement, ast.Pass)
                          or isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant)):
                    # Conditional or reflective bindings make attribute lookup
                    # uncertain. Do not invent a collected inherited method.
                    disabled = True
            if "__test__" not in bound and "__test__" in local:
                value = local["__test__"]
                if not isinstance(value, ast.Constant) or not value.value:
                    disabled = True
            if "__init__" in local or "__new__" in local:
                disabled = True
            for attribute, value in local.items():
                if (attribute not in bound and attribute.startswith("test")
                        and owner != name
                        and isinstance(value, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and not value.decorator_list):
                    methods.append((node, parent, value))
            bound.update(local)
        if not disabled:
            yield from methods

"""Strict repository startup context for narrowly scoped equivalence proofs.

Production source alone does not establish the runtime binding imported by a
test: its package initializers and ancestor conftests execute first. Unknown
or executable startup content withholds credit, as do unproved sibling tests.
External plugins/import hooks remain outside this bounded source proof.
"""

from __future__ import annotations

import ast
from pathlib import PurePosixPath

from checkwash.change import EngineError
from checkwash.roles import collectable


def _inert(node):
    return isinstance(node, ast.Pass) or (
        isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def _literal_expression(node):
    if isinstance(node, ast.Constant):
        return type(node.value) in (str, bytes, int, float, bool, type(None))
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return all(_literal_expression(n) for n in node.elts)
    if isinstance(node, ast.Compare):
        return _literal_expression(node.left) and all(_literal_expression(n) for n in node.comparators)
    if isinstance(node, (ast.UnaryOp, ast.BoolOp, ast.BinOp)):
        return all(_literal_expression(n) for n in ast.iter_child_nodes(node) if isinstance(n, ast.expr))
    # The harmless padding modules in the recorded families use this shape.
    # No name lookup, repository call or user-defined receiver is admitted.
    return (isinstance(node, ast.Call) and not node.args and not node.keywords
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"strip", "lstrip", "rstrip", "lower", "upper", "casefold"}
            and isinstance(node.func.value, ast.Constant)
            and type(node.func.value.value) is str)


def _inert_sibling(node):
    if _inert(node):
        return True
    if not isinstance(node, ast.FunctionDef) or not node.name.startswith("test"):
        return False
    args = node.args
    if (node.decorator_list or node.returns or getattr(node, "type_params", ())
            or args.posonlyargs or args.args or args.kwonlyargs or args.vararg or args.kwarg):
        return False
    return all(_inert(n) or (isinstance(n, ast.Assert) and _literal_expression(n.test)
                           and (n.msg is None or _literal_expression(n.msg))) for n in node.body)


def inert_test_execution_context(path, read, search=None):
    """Require inert repository test-package initializers and all conftests.

    ``search([""])`` is a strict inventory of nonempty Python source files.
    Missing, failed or over-budget discovery withholds optional proof. Empty
    sources are inert. ``read`` distinguishes known absence from failures;
    selected-source read exceptions propagate. The caller owns its cache.
    """
    if read is None or search is None:
        return False
    try:
        paths = search([""])
    except (EngineError, OSError, ValueError, TypeError):
        return False
    if not isinstance(paths, (list, tuple)) or len(paths) >= 64 or any(not isinstance(p, str) for p in paths):
        return False
    inventoried = {p.replace("\\", "/") for p in paths}
    siblings = {p for p in inventoried if collectable(p) and p != path.replace("\\", "/")}
    selected = set(siblings)
    relevant = {path, *(p for p in paths if collectable(p) or p.replace("\\", "/").endswith("conftest.py"))}
    for candidate in relevant:
        normalized = candidate.replace("\\", "/")
        parts = PurePosixPath(normalized).parts
        if not parts or len(parts) > 16 or normalized.startswith("/") or any(
            part in (".", "..") or ":" in part for part in parts
        ):
            return False
        if parts[-1] == "conftest.py":
            selected.add(normalized)
        for depth in range(len(parts)):
            directory = "/".join(parts[:depth])
            prefix = directory + "/" if directory else ""
            for filename in ("__init__.py", "conftest.py"):
                selected.add(prefix + filename)
    if len(selected) > 128:
        return False
    for candidate in sorted(selected):
        source = read(candidate)
        if source is None:
            if candidate in inventoried:
                raise EngineError("strict test execution context inventoried source disappeared")
            continue
        if not isinstance(source, bytes):
            raise EngineError("strict test execution context reader returned invalid source bytes")
        if len(source) > 100_000:
            return False
        try:
            tree = ast.parse(source.decode("utf-8-sig"))
        except (UnicodeError, SyntaxError, ValueError, RecursionError, MemoryError):
            return False
        if sum(1 for _ in ast.walk(tree)) > 4096:
            return False
        allowed = _inert_sibling if candidate in siblings else _inert
        if not all(allowed(node) for node in tree.body):
            return False
    return True

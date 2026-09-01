"""Parsing helpers over Marker source text, shared by the engine and gating.

A Marker's `text` is the decorator or call source as written; its optional
`guard` is the enclosing-if conjunction the frontend recorded. Both sides of
D6 need the same reading of them: the engine to decide which names it must
resolve, gating to evaluate the condition. Every parse failure degrades to
None — an unreadable condition stays unevaluable and earns nothing.
"""

from __future__ import annotations

import ast


def marker_call(text: str) -> ast.Call | None:
    """The marker's Call node, or None when the text is not a call."""
    src = text.strip()
    if src.startswith("@"):
        src = src[1:]
    node = parse_expr(src)
    return node if isinstance(node, ast.Call) else None


def parse_expr(text: str) -> ast.AST | None:
    # Wrapped in parens so multi-line sources (a guard recorded from a
    # multi-line `if`) parse without continuation errors.
    try:
        return ast.parse(f"({text})", mode="eval").body
    except (SyntaxError, RecursionError, ValueError, MemoryError):
        return None


def bare_names(node: ast.AST) -> set[str]:
    """Every ast.Name id in the expression (attribute roots included)."""
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}

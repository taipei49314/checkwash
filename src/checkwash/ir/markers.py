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


# Imperative body skips whose recorded `if` guard is their condition, as D6
# reads them (compat._GATE_CALLS without the conftest control).
GUARDED_SKIP_CALLS = frozenset({"pytest.skip", "pytest.xfail", "self.skipTest"})


def skip_condition(marker, side) -> str | None:
    """What a body skip ran under on one side, as far as the IR records it.

    Its recorded `if` guard first. A skip with none that sits inside an
    `except` block runs only when that block catches, so the block's first
    line stands for its condition: `try: import numpy` / `except
    ImportError:` / `pytest.skip(...)` is an optional-dependency gate, not an
    unconditional kill. None when neither holds, so nothing the IR records
    keeps the skip from firing. Loop bodies and `match` cases record no
    condition (#196 183.2).
    """
    if marker.guard:
        return marker.guard
    start, end = marker.span
    inside = [h for h in side.handlers if h.span[0] <= start and end <= h.span[1]]
    if not inside:
        return None
    return min(inside, key=lambda h: h.span[1] - h.span[0]).text

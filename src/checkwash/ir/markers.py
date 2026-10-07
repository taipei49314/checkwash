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


def mark_condition(call: ast.Call) -> ast.AST | None:
    """The condition a `skipif` or `xfail` mark's first argument holds (#263).

    pytest compiles a string condition as an expression and evaluates that,
    so `skipif("sys.platform == 'win32'")` holds the condition `sys.platform
    == 'win32'`, not a string that is truthy everywhere. A string that does
    not compile as one is None: pytest reports an error for it, and it earns
    nothing. Any other argument is the condition itself, and a call with none
    has none.
    """
    if not call.args:
        return None
    condition = call.args[0]
    if isinstance(condition, ast.Constant) and isinstance(condition.value, str):
        try:
            return ast.parse(condition.value, mode="eval").body
        except (SyntaxError, RecursionError, ValueError, MemoryError):
            return None
    return condition


def is_string_condition(call: ast.Call) -> bool:
    """Is the mark's condition a string, which pytest evaluates in its own namespace?"""
    return bool(call.args) and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str)


def bare_names(node: ast.AST) -> set[str]:
    """Every ast.Name id in the expression (attribute roots included)."""
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


# Imperative body skips whose recorded `if` guard is their condition, as D6
# reads them (compat._GATE_CALLS without the conftest control): each native
# skip or xfail a test body calls or raises, by the one name the frontend
# gives its object (`setup_skip_controls.BODY_MARKERS`, #220), save
# `importorskip`, whose condition is what is installed.
# tests/test_issue220_body_skip_aliases.py holds the two lists together.
GUARDED_SKIP_CALLS = frozenset({
    "pytest.skip", "pytest.xfail", "self.skipTest",
    "pytest.skip.Exception", "pytest.xfail.Exception", "unittest.SkipTest",
})


# The pytest marks a `pytestmark` binding can carry a guard for: its path
# condition, which D6 reads as it reads a body skip's (#260 Q2).
GUARDED_MARKS = frozenset({"pytest.mark.skip", "pytest.mark.skipif", "pytest.mark.xfail"})


def is_guarded_mark(name: str) -> bool:
    """Is this a pytest skip or xfail mark, whose `pytestmark` binding may carry a guard?"""
    return name.split("(", 1)[0] in GUARDED_MARKS


def is_setup_skip(name: str) -> bool:
    """A skip or xfail in the setup a unit runs: a fixture it reaches or xunit setup (#172, #223)."""
    return name.startswith("setup.")


def is_guarded_skip(name: str) -> bool:
    """Does this marker's recorded guard say when it fires?

    The body skips D6 reads, and a skip in the setup a unit runs, whose guard
    is the condition its setup callback reaches it under (#196 183.2).
    """
    return name in GUARDED_SKIP_CALLS or is_setup_skip(name)


def skip_condition(marker, side) -> str | None:
    """What a body skip ran under on one side, as far as the IR records it.

    Its recorded `if` guard first. A skip with none that sits inside an
    `except` block runs only when that block catches, so the block's first
    line stands for its condition: `try: import numpy` / `except
    ImportError:` / `pytest.skip(...)` is an optional-dependency gate, not an
    unconditional kill. None when neither holds, so nothing the IR records
    keeps the skip from firing. Loop bodies and `match` cases record no
    condition (#196 183.2). A setup skip's guard already holds its `except`
    blocks, and its evidence lies in a fixture or callback outside the unit,
    which no handler of the unit encloses.
    """
    if marker.guard:
        return marker.guard
    start, end = marker.span
    inside = [h for h in side.handlers if h.span[0] <= start and end <= h.span[1]]
    if not inside:
        return None
    return min(inside, key=lambda h: h.span[1] - h.span[0]).text

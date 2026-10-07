"""Python expected literals compared by value, as Python's `==` compares them (#226).

`right_value` records a literal's value as its canonical repr, and a folded
conversion records the value it folds to (`Decimal('78.75')`, `75.0`). Two
reprs can differ while the values are equal, `78.75` and `Decimal('78.75')`
among them, and the test then accepts the same results (226.Q2). Equal values
hash equally across int, float, bool and Decimal, so a value is also a key.
Nothing here evaluates repository code: the reprs come from literals and the
fold set's own constructors.
"""

from __future__ import annotations

import ast
import math
import re
from decimal import Decimal, InvalidOperation

_DECIMAL = re.compile(r"Decimal\('([^'\\]{1,128})'\)")
_FLOATS = {"inf": math.inf, "-inf": -math.inf, "nan": math.nan}
_UNKNOWN = object()


def literal_value(text: str) -> object:
    """The value a Python `right_value` writes, or `_UNKNOWN` when it writes none."""
    if text in _FLOATS:
        return _FLOATS[text]
    match = _DECIMAL.fullmatch(text)
    if match is not None:
        try:
            value = Decimal(match.group(1))
        except (InvalidOperation, ValueError):
            return _UNKNOWN
        return _UNKNOWN if value.is_snan() else value
    if len(text) > 4096:
        return _UNKNOWN
    try:
        return ast.literal_eval(text)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return _UNKNOWN


def same_value(before: str, after: str) -> bool:
    """Do two Python expected literals compare equal under `==`?

    `78.75` and `Decimal('78.75')` do; `0.1` and `Decimal('0.1')` do not,
    because the float is not exactly one tenth (226.Q2).
    """
    if before == after:
        return True
    old, new = literal_value(before), literal_value(after)
    if old is _UNKNOWN or new is _UNKNOWN:
        return False
    try:
        return bool(old == new)
    except (TypeError, ValueError, ArithmeticError):
        return False


def value_key(text: str) -> tuple[str, object]:
    """A key under which equal Python expected literals collide; other text keys itself.

    NaN equals nothing, itself included, and an unhashable value (a list) has
    no key of its own: both fall back to their text.
    """
    value = literal_value(text)
    if value is _UNKNOWN or value != value:
        return "text", text
    try:
        hash(value)
    except TypeError:
        return "text", text
    return "value", value

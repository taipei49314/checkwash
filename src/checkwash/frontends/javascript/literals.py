"""Bounded JavaScript scalar evidence, without executing repository code.

Numbers are finite IEEE-754 Number values, not Python integers: decimal,
exponent and radix spellings normalize together, while negative zero stays
distinct. BigInt, legacy octal, non-finite numbers, templates, containers,
identifiers and computed expressions remain unknown. Ordinary quoted strings
use JavaScript escapes and UTF-16 equality, rather than Python literal syntax.
Tolerance bounds (issue #179) are read a little further, and kept as exact
Decimals rather than Number values, because their ordering is a verdict.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from decimal import Context, Decimal

from checkwash.ir.model import Assertion


_WHITESPACE = " \t\n\r\v\f\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"
_DIGITS = r"[0-9](?:_?[0-9])*"
_INTEGER = r"(?:0|[1-9](?:_?[0-9])*)"
_DECIMAL = re.compile(
    rf"(?:{_INTEGER}(?:\.(?:{_DIGITS})?)?|\.{_DIGITS})(?:[eE][+-]?{_DIGITS})?"
)
_RADIX = (
    (re.compile(r"0[xX][0-9a-fA-F](?:_?[0-9a-fA-F])*"), 16),
    (re.compile(r"0[bB][01](?:_?[01])*"), 2),
    (re.compile(r"0[oO][0-7](?:_?[0-7])*"), 8),
)
_HEX = re.compile(r"[0-9a-fA-F]+")
_ESCAPES = {"b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t", "v": "\v"}
_UNKNOWN = object()


def _without_comments(source: str) -> str | None:
    """Remove only lexical comments, preserving strings and token separation."""
    parts: list[str] = []
    i = 0
    while i < len(source):
        if source[i] in "\"'":
            quote, start = source[i], i
            i += 1
            while i < len(source):
                if source[i] == "\\":
                    i += 2
                elif source[i] == quote:
                    i += 1
                    break
                else:
                    i += 1
            else:
                return None
            parts.append(source[start:i])
        elif source.startswith("/*", i):
            closing = source.find("*/", i + 2)
            if closing < 0:
                return None
            parts.append(" ")
            i = closing + 2
        elif source.startswith("//", i):
            i += 2
            while i < len(source) and source[i] not in "\r\n\u2028\u2029":
                i += 1
            parts.append(" ")
        else:
            parts.append(source[i])
            i += 1
    return "".join(parts)


def _number(expression: str) -> float | None:
    # Bound conversion work and avoid treating a leading-zero legacy literal
    # as decimal. Underscores are accepted only between valid radix digits.
    if not expression or len(expression) > 512:
        return None
    negative = expression.startswith("-")
    source = expression
    if source[0] in "+-":
        source = source[1:].lstrip(_WHITESPACE)
    try:
        if _DECIMAL.fullmatch(source):
            value = float(source.replace("_", ""))
        else:
            value = None
            for pattern, radix in _RADIX:
                if pattern.fullmatch(source):
                    value = float(int(source[2:].replace("_", ""), radix))
                    break
            if value is None:
                return None
    except (ValueError, OverflowError):
        return None
    if not math.isfinite(value):
        return None
    return -value if negative else value


def _string(source: str) -> str | object:
    if len(source) < 2 or source[0] not in "\"'" or source[-1] != source[0]:
        return _UNKNOWN
    quote = source[0]
    chars: list[str] = []
    i, end = 1, len(source) - 1
    while i < end:
        char = source[i]
        if char == quote or char in "\r\n\u2028\u2029":
            return _UNKNOWN
        if char != "\\":
            chars.append(char)
            i += 1
            continue
        i += 1
        if i >= end:
            return _UNKNOWN
        escaped = source[i]
        i += 1
        if escaped in "\r\n\u2028\u2029":
            # A backslash followed by a line terminator contributes no data.
            if escaped == "\r" and i < end and source[i] == "\n":
                i += 1
            continue
        if escaped in _ESCAPES:
            chars.append(_ESCAPES[escaped])
        elif escaped == "0":
            if i < end and source[i] in "0123456789":
                return _UNKNOWN  # Legacy octal/non-octal decimal escapes.
            chars.append("\0")
        elif escaped in "123456789":
            return _UNKNOWN
        elif escaped in "xu":
            if escaped == "u" and i < end and source[i] == "{":
                closing = source.find("}", i + 1, end)
                if closing < 0:
                    return _UNKNOWN
                digits = source[i + 1:closing]
                i = closing + 1
                if not 1 <= len(digits) <= 6 or not _HEX.fullmatch(digits):
                    return _UNKNOWN
            else:
                width = 2 if escaped == "x" else 4
                digits = source[i:i + width]
                i += width
                if i > end or len(digits) != width or not _HEX.fullmatch(digits):
                    return _UNKNOWN
            codepoint = int(digits, 16)
            if codepoint > 0x10FFFF:
                return _UNKNOWN
            chars.append(chr(codepoint))
        else:
            # JS identity escapes (e.g. \a) mean the escaped character. This
            # includes escaped quotes, backslashes and forward slashes.
            chars.append(escaped)
    # JS strings are UTF-16 code-unit sequences. A literal astral character,
    # a code-point escape and a surrogate-pair escape must compare equally.
    # Lone surrogates remain intact and repr() keeps their output escapable.
    return "".join(chars).encode("utf-16-le", "surrogatepass").decode("utf-16-le", "surrogatepass")


def populate_expectation(assertion: Assertion, expression: str) -> None:
    """Attach source and canonical value only for a supported scalar operand.

    This does not assign meaning to the matcher: callers select the assertion
    forms whose operand is an expected value. No JavaScript coercions apply.
    The 4096-character cap keeps literal decoding bounded.
    """
    assertion.right_literal = None
    assertion.right_value = None
    original = expression.strip(_WHITESPACE)
    if not original or len(original) > 4096:
        return
    source = _without_comments(original)
    if source is None:
        return
    source = source.strip(_WHITESPACE)
    if not source:
        return
    keywords = {"true": True, "false": False, "null": None}
    if assertion.form == "approx":
        # toBeCloseTo accepts Number operands and compares their arithmetic
        # distance, which treats either signed zero as the same center.
        value = _number(source)
        if value is None:
            return
        if value == 0:
            value = 0.0
    elif source in keywords:
        value = keywords[source]
    elif source[0] in "\"'":
        value = _string(source)
        if value is _UNKNOWN:
            return
    else:
        value = _number(source)
        if value is None:
            return
    assertion.right_literal = original
    assertion.right_value = repr(value)


def populate_precision(assertion: Assertion, expression: str | None = None) -> None:
    """Record positive toBeCloseTo decimal places; omitted precision is two.

    Explicit precision must be an integral Number from -308 through 307.
    Outside that range, floating-point underflow/overflow can collapse distinct
    decimal-place settings to the same tolerance, so no ordering is claimed.
    Negated approximate comparisons reverse the ordering and remain unknown.
    """
    assertion.epsilon = None
    assertion.epsilon_kind = None
    if assertion.form != "approx" or not assertion.positive:
        return
    if expression is None:
        places = 2
    else:
        if len(expression) > 4096:
            return
        source = _without_comments(expression)
        if source is None:
            return
        number = _number(source.strip(_WHITESPACE))
        if number is None or not number.is_integer() or not -308 <= number <= 307:
            return
        places = int(number)
    assertion.epsilon = str(places)
    assertion.epsilon_kind = "places"


def populate_delta(assertion: Assertion, expression: str) -> None:
    """Record a positive chai closeTo/approximately absolute delta.

    chai passes when |actual - expected| <= delta, so a larger finite Number
    is looser. That is the absolute bound a hand-rolled `Math.abs(a - b) <
    bound` states, so it is recorded in the same keyed form with kind `abs`:
    a bare value in a JS file reads as `toBeCloseTo` places, and a delta of
    1 must not compare as one decimal place. Signed zeroes are the same
    delta. Identifiers, computed or non-finite deltas and negated
    comparisons, whose ordering reverses, remain unknown.
    """
    assertion.epsilon = None
    assertion.epsilon_kind = None
    if assertion.form != "approx" or not assertion.positive or len(expression) > 4096:
        return
    source = _without_comments(expression)
    if source is None:
        return
    delta = _number(source.strip(_WHITESPACE))
    if delta is None:
        return
    assertion.epsilon = f"abs={delta if delta else 0.0}"
    assertion.epsilon_kind = "abs"


# Tolerance bounds (issue #179). How two bounds order is a verdict, so they
# stay exact Decimals end to end (SPEC §3): `Number.EPSILON` is exactly
# 2**-52, and a product is taken in a context wide enough to keep
# `k * Number.EPSILON` exact for ordinary literals.
_EXACT = Context(prec=80)
_NAMED_BOUNDS = {
    ("Number", "EPSILON"): _EXACT.divide(Decimal(1), Decimal(2 ** 52)),
    ("Number", "POSITIVE_INFINITY"): Decimal("Infinity"),
    ("Infinity",): Decimal("Infinity"),
}
_IDENTIFIER = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")


def _literal_decimal(expression: str) -> Decimal | None:
    """The value a Number literal writes, as an exact Decimal.

    The spellings `_number` accepts, read from the text rather than through
    a binary float: a decimal literal is its written value, a radix literal
    its integer. A literal Decimal cannot hold is unknown, never an error.
    """
    if not expression or len(expression) > 512:
        return None
    negative = expression.startswith("-")
    source = expression
    if source[0] in "+-":
        source = source[1:].lstrip(_WHITESPACE)
    try:
        if _DECIMAL.fullmatch(source):
            value = Decimal(source.replace("_", ""))
        else:
            for pattern, radix in _RADIX:
                if pattern.fullmatch(source):
                    value = Decimal(int(source[2:].replace("_", ""), radix))
                    break
            else:
                return None
        return -value if negative else value
    except ArithmeticError:
        # `1e99999999999999999999` has an exponent no exact Decimal holds, and
        # negating `1e1000000` overflows the default context. Either escaped
        # analyze as an engine error (exit 2); the bound is unknown instead.
        return None


def _bound_source(expression: str) -> str | None:
    """A bound's text without comments, outer whitespace or parentheses."""
    if len(expression) > 4096:
        return None
    source = _without_comments(expression)
    if source is None:
        return None
    source = source.strip(_WHITESPACE)
    while len(source) > 1 and source[0] == "(" and source[-1] == ")":
        source = source[1:-1].strip(_WHITESPACE)
    return source or None


def _bound_value(expression: str, builtin: Callable[[tuple[str, ...]], bool]) -> Decimal | None:
    """A Number literal, a named Number constant, or a product of two of them."""
    source = _bound_source(expression)
    if source is None:
        return None
    parts = source.split("*")
    if len(parts) > 2:
        return None  # `**`, and longer products, are not read
    factors: list[Decimal] = []
    for part in parts:
        part = part.strip(_WHITESPACE)
        path = tuple(name.strip(_WHITESPACE) for name in part.split("."))
        if path in _NAMED_BOUNDS:
            factor = _NAMED_BOUNDS[path] if builtin(path) else None
        else:
            factor = _literal_decimal(part)
        if factor is None:
            return None
        factors.append(factor)
    try:
        value = factors[0] if len(factors) == 1 else _EXACT.multiply(factors[0], factors[1])
    except ArithmeticError:
        return None  # 0 * Infinity, or a product past the exponent range
    return None if value.is_nan() else value


def populate_tolerance(
    assertion: Assertion,
    expression: str,
    lookup: Callable[[str], str | None],
    builtin: Callable[[tuple[str, ...]], bool],
) -> None:
    """Record the bound of a hand-rolled `Math.abs(a - b) < bound` (issue #179).

    That comparison states what `pytest.approx(b, abs=bound)` states, so the
    bound is recorded in the same keyed form with kind `abs` (bigger is
    looser), and TOLERANCE_LOOSENED compares it as a Decimal. The caller has
    found the `Math.abs` side; this reads the bound only. `builtin(path)`
    says whether a global such as `Number.EPSILON` is unshadowed at the
    assertion; `lookup(name)` returns the initializer a plain name reads.

    Read: a Number literal, `Number.EPSILON`, `Infinity`,
    `Number.POSITIVE_INFINITY`, a product of two of these, or one local
    name initialized to one of them. A name bound to another name, `**`,
    division, calls and other members are unknown and record nothing.
    """
    assertion.epsilon = None
    assertion.epsilon_kind = None
    value = _bound_value(expression, builtin)
    if value is None:
        name = _bound_source(expression)
        initializer = lookup(name) if name is not None and _IDENTIFIER.fullmatch(name) else None
        if initializer is None:
            return
        value = _bound_value(initializer, builtin)
        if value is None:
            return
    assertion.epsilon = f"abs={value}"
    assertion.epsilon_kind = "abs"

"""Bounded JavaScript scalar evidence, without executing repository code.

Numbers are finite IEEE-754 Number values, not Python integers: decimal,
exponent and radix spellings normalize together, while negative zero stays
distinct. BigInt, legacy octal, non-finite numbers, templates, containers,
identifiers and computed expressions remain unknown. Ordinary quoted strings
use JavaScript escapes and UTF-16 equality, rather than Python literal syntax.
Redundant parentheses and the TypeScript-only `as`, `satisfies` and non-null
`!` wrappers evaluate to what they wrap, so they are read through (#198 T4,
T5). Tolerance bounds (issue #179) are read a little further, and kept as
exact Decimals rather than Number values, because their ordering is a verdict.

An operand that is not a literal is still recorded by its text
(`operand_text`), and the names it reads (`operand_names`), so that two
spellings of one operand compare as the same and a name replaced by another
one can be told apart (#198).
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


_QUOTES = "\"'`"
_CLOSING = {"(": ")", "[": "]", "{": "}"}
_CAST = re.compile(r"(?:as|satisfies)(?![\w$])")
# A type that ends the operand: names, members, generics, unions, tuples and
# literal types. `42 as const + 1` adds to the cast, so `+` is not one.
_CAST_TYPE = re.compile(r"[\w$.<>\[\]|&,'\" \t]+")
# The sign of a decimal exponent (`1e-2`) belongs to its literal: it is no
# operator that a cast could apply after (#240).
_EXPONENT_SIGN = re.compile(r"(?<![\w$.])(?:\d[\d_]*(?:\.[\d_]*)?|\.\d[\d_]*)[eE](?=[+-]\d)")


def _top_level(source: str):
    """Yield (index, depth) for each character outside quotes and templates.

    Brackets nest; a quote or template literal is skipped whole. None of
    this is a parser: an unbalanced operand simply never peels.
    """
    depth = 0
    i = 0
    while i < len(source):
        char = source[i]
        if char in _QUOTES:
            i += 1
            while i < len(source) and source[i] != char:
                i += 2 if source[i] == "\\" else 1
            i += 1
            continue
        if char in _CLOSING:
            depth += 1
        elif char in ")]}":
            depth -= 1
        yield i, depth
        i += 1


def _parenthesized(source: str) -> str | None:
    """The inside of `( ... )` when that one pair encloses the whole operand."""
    if len(source) < 2 or source[0] != "(" or source[-1] != ")":
        return None
    for index, depth in _top_level(source):
        if depth == 0 and index < len(source) - 1:
            return None  # `(a) + (b)`: the first pair closes early
    return source[1:-1]


def _cast_operand(source: str) -> str | None:
    """`value` from `value as T` or `value satisfies T`, outside brackets.

    Only a value no looser operator splits, cast to a type that ends the
    operand: `a ? b as T : c` casts `b`, `x + 1 as T` casts the sum, and
    `42 as const + 1` adds to the cast, so none of them is peeled here.
    """
    for index, depth in _top_level(source):
        cast = _CAST.match(source, index) if depth == 0 else None
        if (cast is None or index == 0 or source[index - 1] not in _WHITESPACE
                or cast.end() >= len(source) or source[cast.end()] not in _WHITESPACE):
            continue
        if not _CAST_TYPE.fullmatch(source, cast.end()):
            return None
        head = source[:index].strip(_WHITESPACE)
        signs = {match.end() for match in _EXPONENT_SIGN.finditer(head)}
        operators = [i for i, level in _top_level(head)
                     if level == 0 and head[i] in "?:=|&<>,+-*/%^" and i not in signs]
        if not head or any(i > 0 or head[i] not in "+-" for i in operators):
            return None
        return head
    return None


def _peel(source: str) -> str:
    """An operand without what evaluates to the same value at run time.

    `(75)`, `75 as number`, `75 satisfies number` and TypeScript's non-null
    `value!` are the value they wrap (#198 T4, T5). Comments are already
    removed. Anything that does not peel cleanly is returned as it is.
    """
    while True:
        source = source.strip(_WHITESPACE)
        inner = _parenthesized(source)
        if inner is None and len(source) > 1 and source.endswith("!"):
            inner = source[:-1]
        if inner is None:
            inner = _cast_operand(source)
        if inner is None or not inner.strip(_WHITESPACE):
            return source
        source = inner


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


# What `Number(<string>)` folds: a plain decimal numeral, as JavaScript's
# StringToNumber reads one. Whitespace, separators, radix prefixes and the
# names of infinities stay unknown rather than reasoned about (#226).
_NUMERAL = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")


def _number_call(source: str, number_global: Callable[[], bool] | None) -> float | None:
    """The Number value of `Number(<literal>)`, the one conversion JavaScript folds (#226).

    A number literal, or a string holding a plain decimal numeral, folds to
    its finite value, read the way the rest of this module reads literals.
    `number_global` says whether `Number` still names the global here; without
    it nothing folds.
    """
    if number_global is None or not source.startswith("Number") or len(source) > 512:
        return None
    inner = _parenthesized(source[len("Number"):].strip(_WHITESPACE))
    if inner is None:
        return None
    argument = _peel(inner)
    value = _number(argument)
    if value is None and argument[:1] in "\"'":
        text = _string(argument)
        if text is _UNKNOWN or not _NUMERAL.fullmatch(text):
            return None
        try:
            value = float(text)
        except (ValueError, OverflowError):
            return None
        if not math.isfinite(value):
            return None
    if value is None or not number_global():
        return None
    return value


def populate_expectation(assertion: Assertion, expression: str,
                         number_global: Callable[[], bool] | None = None) -> None:
    """Attach source and canonical value only for a supported scalar operand.

    This does not assign meaning to the matcher: callers select the assertion
    forms whose operand is an expected value. No JavaScript coercions apply.
    Parentheses and TypeScript's `as`, `satisfies` and `!` are read through
    (#198 T4, T5); `right_literal` keeps the operand as written. The
    4096-character cap keeps literal decoding bounded. `Number(<literal>)`
    folds to its value while `number_global` says `Number` is the global
    (#226).
    """
    assertion.right_literal = None
    assertion.right_value = None
    original = expression.strip(_WHITESPACE)
    if not original or len(original) > 4096:
        return
    source = _without_comments(original)
    if source is None:
        return
    source = _peel(source)
    if not source:
        return
    keywords = {"true": True, "false": False, "null": None}
    folded = _number_call(source, number_global)
    if assertion.form == "approx":
        # toBeCloseTo accepts Number operands and compares their arithmetic
        # distance, which treats either signed zero as the same center.
        value = _number(source) if folded is None else folded
        if value is None:
            return
        if value == 0:
            value = 0.0
    elif folded is not None:
        value = folded
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


def number_operand(expression: str) -> float | None:
    """The Number an operand writes when it is a Number literal, else None.

    Read the way `populate_expectation` reads one: through comments,
    parentheses and the TypeScript wrappers. The centre of a hand-rolled
    `Math.abs(total - 78.75) < 0.01` is such an operand (#196 189.2).
    """
    original = expression.strip(_WHITESPACE)
    if not original or len(original) > 4096:
        return None
    source = _without_comments(original)
    if source is None:
        return None
    return _number(_peel(source))


def keyword_operand(expression: str) -> str | None:
    """`null`, `undefined`, `true` or `false` when the operand is exactly that word.

    Comments, surrounding whitespace, parentheses and TypeScript wrappers
    aside (`(null)`, `undefined as any`). Whether `undefined` still names the
    global is the caller's question; the other three are keywords.
    """
    if len(expression) > 4096:
        return None
    source = _without_comments(expression)
    if source is None:
        return None
    source = _peel(source)
    return source if source in {"null", "undefined", "true", "false"} else None


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
        number = _number(_peel(source))
        if number is None or not number.is_integer() or not -308 <= number <= 307:
            return
        places = int(number)
    assertion.epsilon = str(places)
    assertion.epsilon_kind = "places"


def populate_delta(
    assertion: Assertion,
    expression: str,
    lookup: Callable[[str], str | None],
    builtin: Callable[[tuple[str, ...]], bool],
) -> None:
    """Record a positive chai closeTo/approximately absolute delta.

    chai passes when |actual - expected| <= delta, so a larger Number is
    looser. That is the absolute bound a hand-rolled `Math.abs(a - b) <
    bound` states, so it is read by the same exact reader (`read_bound`:
    literals, `Infinity`, `Number.MAX_VALUE`, ..., one local name) and
    recorded in the same keyed form with kind `abs` (#196 190.4): a bare
    value in a JS file reads as `toBeCloseTo` places, and a delta of 1 must
    not compare as one decimal place. A delta it cannot read is unknown,
    and so is a negated comparison, whose ordering reverses.
    """
    assertion.epsilon = None
    assertion.epsilon_kind = None
    if assertion.form != "approx" or not assertion.positive:
        return
    value = read_bound(expression, lookup, builtin)
    if value is None:
        return
    assertion.epsilon = f"abs={value}"
    assertion.epsilon_kind = "abs"


# Tolerance bounds (issue #179). How two bounds order is a verdict, so they
# stay exact Decimals end to end (SPEC §3): `Number.EPSILON` is exactly
# 2**-52, `Number.MAX_VALUE` exactly (2 - 2**-52) * 2**1023, and a product is
# taken in a context wide enough to keep `k * Number.EPSILON` exact for
# ordinary literals.
_EXACT = Context(prec=80)
_NAMED_BOUNDS = {
    ("Number", "EPSILON"): _EXACT.divide(Decimal(1), Decimal(2 ** 52)),
    ("Number", "MAX_VALUE"): Decimal(2 ** 1024 - 2 ** 971),
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
    """A bound's text without comments, outer whitespace, parentheses or TS wrappers."""
    if len(expression) > 4096:
        return None
    source = _without_comments(expression)
    if source is None:
        return None
    return _peel(source) or None


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

    What `read_bound` reads is recorded; anything else records nothing.
    """
    assertion.epsilon = None
    assertion.epsilon_kind = None
    value = read_bound(expression, lookup, builtin)
    if value is None:
        return
    assertion.epsilon = f"abs={value}"
    assertion.epsilon_kind = "abs"


def read_bound(
    expression: str,
    lookup: Callable[[str], str | None],
    builtin: Callable[[tuple[str, ...]], bool],
) -> Decimal | None:
    """The exact value of a bound or delta operand, or None when it cannot be read.

    Read: a Number literal, `Number.EPSILON`, `Number.MAX_VALUE`,
    `Infinity`, `Number.POSITIVE_INFINITY`, a product of two of these, or
    one local name initialized to one of them, each through parentheses and
    TypeScript wrappers. A name bound to another name, `**`, division, calls
    and other members are unknown. `builtin(path)` says whether a global
    such as `Number.EPSILON` is unshadowed at the assertion; `lookup(name)`
    returns the initializer a plain name reads.
    """
    value = _bound_value(expression, builtin)
    if value is not None:
        return value
    name = _bound_source(expression)
    initializer = lookup(name) if name is not None and _IDENTIFIER.fullmatch(name) else None
    return None if initializer is None else _bound_value(initializer, builtin)


# Operands that are not literals (#198). Two spellings of one operand on two
# APIs (`toBeLessThan(LIMIT)`, `.below(LIMIT)`) must compare as the same, and
# a name replaced by another one must not. These read the text only; what a
# name holds is the binding scan's question, not theirs.
_KEYWORDS = frozenset({
    "true", "false", "null", "undefined", "NaN", "Infinity", "this", "super", "new",
    "typeof", "void", "delete", "in", "instanceof", "of", "await", "yield", "async",
    "function", "class", "return", "if", "else", "var", "let", "const", "as", "satisfies",
})
_NAME = re.compile(r"[A-Za-z_$][\w$]*")


def operand_text(expression: str) -> str | None:
    """An operand as one canonical line: no comments, parentheses or TS wrappers.

    Whitespace outside strings collapses to one space, so a reformatted
    operand reads the same. None when the text cannot be read safely: an
    unterminated string or comment, or more than 4096 characters.
    """
    if len(expression) > 4096:
        return None
    source = _without_comments(expression)
    if source is None:
        return None
    source = _peel(source)
    parts: list[str] = []
    last = 0
    for index, _depth in _top_level(source):
        if source[index] in _WHITESPACE:
            if index > last:
                parts.append(source[last:index])
            if parts and parts[-1] != " ":
                parts.append(" ")
            last = index + 1
    parts.append(source[last:])
    return "".join(parts).strip() or None


# One token of an operand: a quoted string, a run of word characters, a
# punctuator of up to four characters, or any other single character.
_OPERAND_TOKEN = re.compile(
    r"""(['"])(?:\\.|(?!\1).)*\1|[\w$]+|>>>=|\.\.\.|===|!==|\*\*=|<<=|>>=|>>>|&&=|\|\|=|\?\?="""
    r"""|=>|==|!=|<=|>=|&&|\|\||\?\?|\?\.|\*\*|\+\+|--|<<|>>|[+*%&|^-]=|\S""",
    re.DOTALL,
)


def _double_quoted(literal: str) -> str:
    """A quoted string in double quotes with its value unchanged: `'a"b'` reads `"a\\"b"`."""
    out: list[str] = []
    body = literal[1:-1]
    i = 0
    while i < len(body):
        if body[i] == "\\" and i + 1 < len(body):
            out.append("'" if body[i + 1] == "'" else body[i:i + 2])
            i += 2
            continue
        out.append('\\"' if body[i] == '"' else body[i])
        i += 1
    return '"' + "".join(out) + '"'


def comparable_operand(text: str) -> str:
    """An operand with the formatting that changes no value taken out (#226).

    Two spellings of one value read alike: a quoted string in double quotes,
    tokens joined by one space, and no comma before a closing bracket. A
    template literal or a slash, which may open a regular expression, keeps
    the text as written.
    """
    tokens: list[str] = []
    for match in _OPERAND_TOKEN.finditer(text):
        token = match.group()
        if token in ("`", "/"):
            return text
        if token[0] in "'\"":
            token = _double_quoted(token)
        elif token in (")", "]", "}") and len(tokens) > 1 and tokens[-1] == "," and tokens[-2] not in "([{,":
            tokens.pop()
        tokens.append(token)
    return " ".join(tokens)


_CALLEE =re.compile(r"[A-Za-z_$][\w$]*(?:[ \t]*\.[ \t]*[A-Za-z_$][\w$]*)*")


def operand_callee(source: str) -> str | None:
    """The callee's dotted name when an operand is exactly one call, `callee(...)` (#226).

    `new`, an optional chain, a call on a call's result or anything after
    the call's closing parenthesis is no such operand.
    """
    match = _CALLEE.match(source)
    if match is None or _parenthesized(source[match.end():].strip(_WHITESPACE)) is None:
        return None
    return re.sub(r"[ \t]+", "", match.group())


def operand_names(source: str) -> tuple[str, ...]:
    """The names an operand reads, sorted: `make(items)` reads make and items.

    The JS counterpart of the names Python's frontend records for an
    expected side. A property after `.` or `?.`, an object key, a keyword
    and anything inside a string or template is not a name it reads.
    """
    names: set[str] = set()
    positions = [index for index, _depth in _top_level(source)]
    code = set(positions)
    for match in _NAME.finditer(source):
        start, end = match.span()
        if start not in code or (start > 0 and (source[start - 1].isalnum() or source[start - 1] in "_$")):
            continue
        before = source[:start].rstrip(_WHITESPACE)
        after = source[end:].lstrip(_WHITESPACE)
        if before.endswith(".") and not before.endswith(".."):
            continue  # a property, including `?.` and the spread's third dot aside
        if after.startswith(":") and not after.startswith("::") and before.endswith(("{", ",")):
            continue  # an object key
        if match.group() not in _KEYWORDS:
            names.add(match.group())
    return tuple(sorted(names))

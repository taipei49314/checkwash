"""Bounded Jest/Vitest/node:test/chai oracle scan. Not a JS parser.

A matcher swap `toBe` -> `toBeTruthy` is the same cheat as `==` -> `is not
None`, and so is chai's `.to.equal(y)` -> `.to.exist`. This frontend only
looks at `test`/`it` units, `expect().matcher()`, single-terminal chai
`expect()` chains and direct Node or chai `assert` calls so existing
detectors can see a strength drop, and at the liveness every
`describe`/`test` declaration gives the units inside it, so TEST_DISABLED
can see one stop running. Production `.js`/`.ts` is not parsed and still
cannot grant a false sense of coverage. Static imports and lexical shadows
are resolved within the bounded binding model; dynamic JavaScript execution
remains outside the scan.
"""

from __future__ import annotations

import hashlib
import re
from bisect import bisect_left, bisect_right
from collections.abc import Callable
from dataclasses import dataclass

from checkwash.frontends.javascript.bindings import Bindings, CALL, NAME
from checkwash.frontends.javascript.exception_handlers import swallowing_handlers
from checkwash.frontends.javascript.literals import (
    keyword_operand,
    number_operand,
    operand_callee,
    operand_text,
    populate_delta,
    populate_expectation,
    populate_precision,
    read_bound,
)
from checkwash.frontends.python.frontend import ParsedFile, ParsedUnit
from checkwash.ir import strength as S
from checkwash.ir.model import Assertion, Marker, UnitSide, normalize_text

# Word boundary before every declaration word: `split("\n")` contains `it`
# and `exit(` contains `xit`, so an unanchored match minted a test unit whose
# name was the following string literal (issue #156 — a diff that touched no
# assertion reported the pseudo-unit `"\n"` as a removed test).
#
# One reader serves every declaration level (issues #176, #178). `test`/`it`
# declare a unit; `describe`/`suite`/`context` declare a block whose liveness
# every declaration inside its callback inherits. A prefixed global means what
# its modifier means (the Jest/Jasmine/Mocha `x` prefix is `.skip`, `f` is
# `.only`), and is a global, never a member: `model.fit(...)` focuses nothing.
_UNIT_WORDS = {"test": "", "it": "", "xtest": "skip", "xit": "skip", "fit": "only"}
_BLOCK_WORDS = {"describe": "", "suite": "", "context": "",
                "xdescribe": "skip", "xcontext": "skip", "fdescribe": "only"}
_DECLARATION_RE = re.compile(
    r"(?<![\w$])(?P<word>xdescribe|fdescribe|xcontext|describe|context|suite"
    r"|xtest|test|xit|fit|it)(?![\w$])"
)
# Chained modifiers by the liveness effect they declare. `.todo` never runs
# under Jest/Vitest and runs with its failure ignored under node:test, so it
# is a skip; `.fails`/`.failing` invert the oracle, so a failing assertion
# passes. The neutral ones are read through to the effect chained after them,
# AVA's `serial` among them (#233).
_MODIFIERS = {
    "skip": "skip", "todo": "skip", "only": "only", "fails": "fails", "failing": "fails",
    "concurrent": "", "sequential": "", "shuffle": "", "serial": "",
}
# Modifiers with their own argument list before the declaration call:
# `test.skipIf(cond)(name, fn)`, `describe.each(table)(name, fn)`.
_CURRIED = {"skipIf", "runIf", "each", "for"}
# node:test and Vitest options-object keys, with the same effects.
_OPTION_EFFECTS = {"skip": "skip", "todo": "skip", "only": "only", "fails": "fails"}
_MEMBER_RE = re.compile(r"\.\s*(?P<member>" + NAME + r")")
_TITLE_RE = re.compile(r"""\s*(?P<q>['"`])(?P<name>(?:\\.|(?!(?P=q)).)*)(?P=q)""")
_PROPERTY_RE = re.compile(
    r"\s*(?:(?P<key>" + NAME + r")|(?P<q>['\"])(?P<quoted>" + NAME + r")(?P=q))\s*(?P<colon>:)?"
)
_STRING_RE = re.compile(r"(['\"])(?:\\[\s\S]|(?!\1)[^\\\n])*\1")
_NUMBER_RE = re.compile(
    r"[+-]?(?:0[xXoObB][\da-fA-F_]+|(?:\d[\d_]*(?:\.[\d_]*)?|\.\d[\d_]*)(?:[eE][+-]?\d+)?)n?"
)
_ZERO_RE = re.compile(r"[+-]?(?:0[xXoObB]0+|0+(?:\.0*)?|\.0+)(?:[eE][+-]?\d+)?n?")
_EXPECT_RE = re.compile(
    r"""\s*\.\s*(?P<not>not\s*\.\s*)?(?P<matcher>"""
    r"""toBe|toEqual|toStrictEqual|toBeCloseTo|toContain|toMatch|"""
    r"""toBeTruthy|toBeFalsy|toBeDefined|toBeUndefined|toBeNull|"""
    r"""toBeGreaterThan|toBeGreaterThanOrEqual|toBeLessThan|toBeLessThanOrEqual"""
    r""")\s*\(""",
    re.MULTILINE,
)
_ASSERT_RE = CALL
_EMPTY_ARGUMENT = re.compile(r"\s*(?:(?://[^\r\n]*(?:\r?\n|$)|/\*[\s\S]*?\*/)\s*)*\Z")

_ASSERT_STRENGTH: dict[str, tuple[str, int]] = {
    "equal": ("compare_eq", S.EXACT_VALUE),
    "strictEqual": ("compare_eq", S.EXACT_VALUE),
    "deepEqual": ("compare_eq", S.EXACT_STRUCT),
    "deepStrictEqual": ("compare_eq", S.EXACT_STRUCT),
    "ok": ("truthy", S.TRUTHY),
}
# node:assert's strict mode names the strict comparisons with the legacy words.
_STRICT_MODE = {"equal": "strictEqual", "deepEqual": "deepStrictEqual"}

_MATCHER_STRENGTH: dict[str, tuple[str, int]] = {
    "toBe": ("compare_eq", S.EXACT_VALUE),
    "toEqual": ("compare_eq", S.EXACT_VALUE),
    "toStrictEqual": ("compare_eq", S.EXACT_STRUCT),
    "toBeCloseTo": ("approx", S.APPROX),
    "toContain": ("membership", S.PATTERN),
    "toMatch": ("pattern", S.PATTERN),
    "toBeTruthy": ("truthy", S.TRUTHY),
    "toBeFalsy": ("truthy", S.TRUTHY),
    "toBeDefined": ("non_null", S.NON_NULL),
    "toBeUndefined": ("non_null", S.NON_NULL),
    "toBeNull": ("non_null", S.NON_NULL),
    "toBeGreaterThan": ("compare_ord", S.BOUND),
    "toBeGreaterThanOrEqual": ("compare_ord", S.BOUND),
    "toBeLessThan": ("compare_ord", S.BOUND),
    "toBeLessThanOrEqual": ("compare_ord", S.BOUND),
}
# The predicate key each Jest matcher states (`ir/predicate.py`), and whether
# the matcher asserts it (True) or its negation (False): toBeDefined() is
# is_undefined asserted negatively, as `.not.toBeUndefined()` is. `toBe` takes
# its key from its operand; the other matchers state no key (#198).
_MATCHER_PREDICATE: dict[str, tuple[str, bool]] = {
    "toBeTruthy": ("truthy", True),
    "toBeFalsy": ("truthy", False),
    "toBeDefined": ("is_undefined", False),
    "toBeUndefined": ("is_undefined", True),
    "toBeNull": ("is_null", True),
    "toBeGreaterThan": ("gt", True),
    "toBeGreaterThanOrEqual": ("ge", True),
    "toBeLessThan": ("lt", True),
    "toBeLessThanOrEqual": ("le", True),
}
# Each ordering matcher as the comparison `subject <op> argument` it asserts;
# reading a hand-rolled tolerance (issue #179) needs the direction.
_ORDER_MATCHERS: dict[str, str] = {
    "toBeLessThan": "<",
    "toBeLessThanOrEqual": "<=",
    "toBeGreaterThan": ">",
    "toBeGreaterThanOrEqual": ">=",
}
_ABS_CALL = re.compile(r"Math\s*\.\s*abs\s*\(")
# Jest/Vitest asymmetric matchers as the expected value of toEqual and
# toStrictEqual (#198 Q3): form, rung, predicate key and whether the matcher
# asserts it. `expect.anything()` matches all but null and undefined, so it
# asserts the negation of is_nullish, as `.exist` does; `expect.any(Ctor)`
# is a type check, which states no key.
_ASYMMETRIC: dict[str, tuple[str, int, str | None, bool]] = {
    "anything": ("non_null", S.NON_NULL, "is_nullish", False),
    "any": ("type_shape", S.TYPE_SHAPE, None, True),
}
_ASYMMETRIC_ARITY = {"anything": 0, "any": 1}


# chai (issue #180). One meaning table serves both chai interfaces: an
# expect() chain supplies the subject, the assert interface passes it first.
# Every meaning sits on an existing rung; the lattice is not extended. As for
# Jest matchers, the expected value of an equality or closeTo and the bound
# of a bound word carry literal evidence (#198).
@dataclass(frozen=True)
class _ChaiMeaning:
    """Operands are subject first; a further argument is chai's message."""

    form: str
    strength: int
    operands: int = 1
    expected: int | None = None  # Operand holding the expected scalar or the bound.
    implied: str | None = None  # Literal a property terminal compares with.
    delta: int | None = None  # closeTo's absolute tolerance operand.
    # The predicate key it states (#198), and whether it asserts that key
    # (True) or its negation (False): `.exist` asserts `!= null`, the
    # negation of is_nullish. The equalities take their key from the operand.
    predicate: str | None = None
    asserts: bool = True


_CHAI: dict[str, _ChaiMeaning] = {
    # expect(...).equal and assert.strictEqual compare with ===.
    "strict_equal": _ChaiMeaning("compare_eq", S.EXACT_VALUE, 2, expected=1),
    # assert.equal is ==. Its key, eq_loose, carries the coercion, so its
    # scalar operand is evidence as a strict one is (#196 190.2).
    "loose_equal": _ChaiMeaning("compare_eq", S.EXACT_VALUE, 2, expected=1),
    # eql, deep.equal and assert.deepEqual compare structurally (deep-eql).
    "deep_equal": _ChaiMeaning("compare_eq", S.EXACT_STRUCT, 2, expected=1),
    # `.true` is `=== true`, the oracle equal(true) states, not `.ok`'s: two
    # spellings of one exact literal must not read as a weakening.
    "true": _ChaiMeaning("compare_eq", S.EXACT_VALUE, implied="true", predicate="is_true"),
    "false": _ChaiMeaning("compare_eq", S.EXACT_VALUE, implied="false", predicate="is_false"),
    "null": _ChaiMeaning("compare_eq", S.EXACT_VALUE, implied="null", predicate="is_null"),
    # `=== undefined`; the literal reader treats `undefined` as an identifier.
    "undefined": _ChaiMeaning("compare_eq", S.EXACT_VALUE, predicate="is_undefined"),
    # exist (!= null) and assert.isDefined (!== undefined) sit on
    # toBeDefined's rung, and each asserts a negation: not nullish, not
    # undefined. The rung cannot tell them apart; the key does (#198).
    "exist": _ChaiMeaning("non_null", S.NON_NULL, predicate="is_nullish", asserts=False),
    "defined": _ChaiMeaning("non_null", S.NON_NULL, predicate="is_undefined", asserts=False),
    "ok": _ChaiMeaning("truthy", S.TRUTHY, predicate="truthy"),
    "close_to": _ChaiMeaning("approx", S.APPROX, 3, expected=1, delta=2),
    "include": _ChaiMeaning("membership", S.PATTERN, 2),
    "match": _ChaiMeaning("pattern", S.PATTERN, 2),
    # The bound words, each with its direction (`subject > operand`, ...) and
    # its bound, which a rewrite changes as it changes an expected value.
    "above": _ChaiMeaning("compare_ord", S.BOUND, 2, expected=1, predicate="gt"),
    "least": _ChaiMeaning("compare_ord", S.BOUND, 2, expected=1, predicate="ge"),
    "below": _ChaiMeaning("compare_ord", S.BOUND, 2, expected=1, predicate="lt"),
    "most": _ChaiMeaning("compare_ord", S.BOUND, 2, expected=1, predicate="le"),
    "within": _ChaiMeaning("compare_ord", S.BOUND, 3),
    # A length check is the len(x) == n shape.
    "length": _ChaiMeaning("type_shape", S.TYPE_SHAPE, 2),
    # `.property(name)` with no value asserts that the subject has the key:
    # a shape check, on the property it names (#215).
    "property": _ChaiMeaning("type_shape", S.TYPE_SHAPE),
}
# Readability getters. Uncalled a/an are chains too; called, they are type
# assertions, which stay unrepresented.
_CHAI_CHAINS = frozenset({
    "to", "be", "been", "is", "that", "which", "and", "has", "have", "with",
    "at", "of", "same", "but", "does", "still", "also", "a", "an",
})
# expect(subject).<chain>.<word>(operands...)
_CHAI_METHODS: dict[str, str] = {
    "equal": "strict_equal", "equals": "strict_equal", "eq": "strict_equal",
    "eql": "deep_equal", "eqls": "deep_equal",
    "closeTo": "close_to", "approximately": "close_to",
    "include": "include", "includes": "include", "contain": "include", "contains": "include",
    "match": "match", "matches": "match",
    "above": "above", "gt": "above", "greaterThan": "above",
    "least": "least", "gte": "least", "greaterThanOrEqual": "least",
    "below": "below", "lt": "below", "lessThan": "below",
    "most": "most", "lte": "most", "lessThanOrEqual": "most",
    "within": "within",
    "lengthOf": "length", "length": "length",
}
# expect(subject).<chain>.<word>, which asserts when it is read.
_CHAI_PROPERTIES: dict[str, str] = {
    "ok": "ok", "true": "true", "false": "false", "null": "null",
    "undefined": "undefined", "exist": "exist", "exists": "exist",
}
# assert.<method>(subject, operands...). Negated methods (notEqual, isNotOk,
# notExists, ...) stay unrepresented, as node:assert's do; replacing a
# represented assertion with one still reports the removal.
_CHAI_ASSERT: dict[str, str] = {
    "ok": "ok", "isOk": "ok",
    "equal": "loose_equal", "strictEqual": "strict_equal",
    "deepEqual": "deep_equal", "deepStrictEqual": "deep_equal",
    "isTrue": "true", "isFalse": "false", "isNull": "null", "isUndefined": "undefined",
    "exists": "exist", "isDefined": "defined",
    "closeTo": "close_to", "approximately": "close_to",
    "include": "include", "match": "match",
    "isAbove": "above", "isAtLeast": "least", "isBelow": "below", "isAtMost": "most",
    "lengthOf": "length",
}
# assert.<method>(object, name[, value]): the assertion is on object[name]
# (#215), with the value, where the meaning takes one, as its expectation.
# The meaning, and whether the name is a nested path. The own forms read as
# `.own.property` does. The negated methods stay unrepresented, as the other
# negated assert methods do, and so does a call whose property cannot be
# followed.
_CHAI_ASSERT_PROPERTY: dict[str, tuple[str, bool]] = {
    "property": ("property", False),
    "ownProperty": ("property", False),
    "nestedProperty": ("property", True),
    "propertyVal": ("strict_equal", False),
    "ownPropertyVal": ("strict_equal", False),
    "deepPropertyVal": ("deep_equal", False),
    "deepOwnPropertyVal": ("deep_equal", False),
    "nestedPropertyVal": ("strict_equal", True),
    "deepNestedPropertyVal": ("deep_equal", True),
}
# expect(...).<chain>.property(name[, value]) and its own-property methods.
_CHAI_PROPERTY_METHODS = frozenset({"property", "ownProperty", "haveOwnProperty"})
_PLAIN_KEY = re.compile(NAME + r"\Z")
# A nested property path chai's `.nested` reads: names with dots and array indices.
_NESTED_PATH = re.compile(NAME + r"(?:\." + NAME + r"|\[\d+\])*\Z")
_STRING_KEY = re.compile(r"""(?P<quote>["'])(?P<body>(?:(?!(?P=quote))[^\\\n])*)(?P=quote)\Z""")


def property_subject(subject: str, name: str, nested: bool = False) -> str | None:
    """The subject `.property(name)` retargets an assertion to, as source text (#215).

    `order` and "total" give `order.total`, a key that is no name
    `order["unit price"]`, a computed key `order[key]`, and a nested path
    `order.totals.gross`. A subject that is not one member chain is
    parenthesized. A nested path that is not a literal is not followed.
    """
    subject = subject.strip()
    if not re.fullmatch(NAME + r"(?:\s*\??\.\s*" + NAME + r"|\[[^\[\]]*\]|\([^()]*\))*", subject):
        subject = f"({subject})"
    literal = _STRING_KEY.fullmatch(name.strip())
    if literal is None:
        return None if nested else f"{subject}[{name.strip()}]"
    key = literal.group("body")
    if nested:
        return f"{subject}.{key}" if _NESTED_PATH.fullmatch(key) else None
    return f"{subject}.{key}" if _PLAIN_KEY.fullmatch(key) else f'{subject}["{key}"]'


def is_js_test_path(path: str) -> bool:
    # Keep this frontend entry point for existing engine/adaptor callers.
    from checkwash.frontends.javascript.paths import is_js_test_path as matches

    return matches(path)


def _code_positions(text: str, *, keep_strings: bool = False) -> bytearray:
    """Exclude comments and literal contents from declaration/matcher starts.

    Keep original offsets and quoted test names for the bounded call scan.
    Template literals are opaque, including their interpolations; this is not
    an attempt to parse arbitrary JavaScript expressions.
    Coverage import scanning can retain ordinary quoted strings while still
    excluding comments, regexes and templates. Assertion scans use the default.
    """
    code = bytearray(b"\x01") * len(text)
    i = 0
    operand = True
    previous = ""
    parens: list[bool] = []
    braces: list[bool] = []
    while i < len(text):
        start = i
        retained_string = False
        if text.startswith("//", i):
            end = text.find("\n", i + 2)
            i = len(text) if end < 0 else end
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = len(text) if end < 0 else end + 2
        elif text[i] in "\"'`":
            quote = text[i]
            retained_string = keep_strings and quote != "`"
            i += 1
            while i < len(text):
                if text[i] == "\\":
                    i += 2
                elif text[i] == quote:
                    i += 1
                    break
                else:
                    i += 1
            i = min(i, len(text))
            operand = False
            previous = "literal"
        elif text[i] == "/" and operand:
            # A slash at expression start introduces a regex, whose quotes
            # are data. Division after an operand must remain executable.
            j = i + 1
            bracket = False
            while j < len(text) and text[j] not in "\r\n":
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == "[":
                    bracket = True
                elif text[j] == "]":
                    bracket = False
                elif text[j] == "/" and not bracket:
                    j += 1
                    while j < len(text) and (text[j].isalnum() or text[j] in "_$"):
                        j += 1
                    break
                j += 1
            else:
                # Malformed/unsupported literal: do not consume the next
                # source line as regex content.
                i += 1
                continue
            i = min(j, len(text))
            operand = False
            previous = "literal"
        else:
            char = text[i]
            if text[i:i + 2] in {"++", "--"}:
                # Prefix operators still await an operand; postfix ones
                # complete it. Neither turns subsequent division into regex.
                previous = text[i:i + 2]
                i += 2
                continue
            if char.isalpha() or char in "_$":
                i += 1
                while i < len(text) and (text[i].isalnum() or text[i] in "_$"):
                    i += 1
                previous = text[start:i]
                operand = previous in {"return", "throw", "yield", "await", "typeof",
                                       "void", "delete", "new", "in", "of", "case", "else", "do"}
                continue
            if char == "(":
                parens.append(previous in {"if", "while", "for", "with", "switch", "catch"})
                operand = True
            elif char == ")":
                operand = parens.pop() if parens else False
            elif char == "{":
                braces.append(previous not in {"=", "(", "[", ",", ":", "return"})
                operand = True
            elif char == "}":
                operand = braces.pop() if braces else True
            elif char == "]" or char.isdigit():
                operand = False
            elif not char.isspace():
                operand = char != "."
            if not char.isspace():
                previous = char
            i += 1
            continue
        if not retained_string:
            code[start:i] = b"\x00" * (i - start)
    return code


def _call_argument_spans(
    text: str, code: bytearray, opening: int, limit: int,
) -> tuple[list[tuple[int, int]], int] | None:
    """Read one balanced call, splitting only its top-level commas.

    Literal/comment punctuation is masked by the same scan used to exclude
    fake declarations. Nested calls, arrays and objects belong to the actual
    argument, not to the expected value or optional assertion message.
    """
    closing = {"(": ")", "[": "]", "{": "}"}
    stack = [")"]
    arguments: list[tuple[int, int]] = []
    start = opening + 1
    for i in range(start, limit):
        if not code[i]:
            continue
        char = text[i]
        if char in closing:
            stack.append(closing[char])
        elif char in ")]}":
            if char != stack.pop():
                return None
            if not stack:
                if not _EMPTY_ARGUMENT.fullmatch(text[start:i]):
                    arguments.append((start, i))
                return arguments, i + 1
        elif char == "," and len(stack) == 1:
            arguments.append((start, i))
            start = i + 1
        elif char == ";" and len(stack) == 1:
            return None
    return None


def _call_arguments(
    text: str, code: bytearray, opening: int, limit: int,
) -> tuple[list[str], int] | None:
    call = _call_argument_spans(text, code, opening, limit)
    if call is None:
        return None
    spans, end = call
    return [text[start:stop].strip() for start, stop in spans], end


_CHAI_STEP = re.compile(r"\s*\.\s*(?P<word>" + NAME + r")")


def _skip_space(masked: str, position: int, end: int) -> int:
    while position < end and masked[position].isspace():
        position += 1
    return position


def _chai_chain(
    text: str, code: bytearray, masked: str, position: int, end: int,
) -> tuple[str, bool, list[str], int, list[tuple[str, bool]]] | None:
    """Read the chai chain after expect(...): (meaning, positive, operands, end, properties).

    Language chains are inert getters, `not` sets chai's negate flag (a second
    `not` leaves it set) and `deep` makes equal deep. `.property(name)` and
    its own-property methods move the subject to subject[name] for the rest
    of the chain, and `properties` lists each (name operand, nested) in
    order (#215): with a value, `.property(name, value)` is an equality on
    the property, `deep` making it deep; without one, at the end of the
    chain, it asserts that the key is there. `nested` reads the name as a
    path, and `own` asks for an own property, the same assertion here. As
    in chai, the flags stay set for the rest of the chain; `include` reads
    them too, so a chain that reaches it with either set stays unread. Any
    other flag or plugin word, an unknown or malformed terminal, or a chain
    that continues after its terminal yields None: the call stays a visible
    coverage gap instead of a partial oracle whose dropped tail nothing
    would report.
    """
    negated = deep = nested = own = False
    properties: list[tuple[str, bool]] = []
    while True:
        step = _CHAI_STEP.match(masked, position, end)
        if step is None:
            return None
        word = step.group("word")
        opening = _skip_space(masked, step.end(), end)
        called = opening < end and masked[opening] == "("
        # An uncalled word ends where it is spelled. Whitespace and comments
        # after a property terminal belong to no assertion, so editing them
        # cannot make a kept or moved assertion read as rewritten.
        position = opening if called else step.end()
        if not called and word in _CHAI_CHAINS:
            continue
        if not called and word in {"not", "deep", "nested", "own"}:
            negated = negated or word == "not"
            deep = deep or word == "deep"
            nested = nested or word == "nested"
            own = own or word == "own"
            continue
        if called and word in _CHAI_PROPERTY_METHODS:
            call = _call_arguments(text, code, position, end)
            if call is None or not 1 <= len(call[0]) <= 3:
                return None
            arguments, position = call
            properties.append((arguments[0], nested and word == "property"))
            following = _skip_space(masked, position, end)
            continues = following < end and masked.startswith((".", "[", "(", "?."), following)
            if len(arguments) == 1 and continues and not negated:
                continue  # The rest of the chain asserts on the property's value.
            if continues:
                return None
            if len(arguments) == 1:
                return "property", not negated, [], position, properties
            return ("deep_equal" if deep else "strict_equal"), not negated, [arguments[1]], position, properties
        if word in _CHAI_PROPERTIES:
            meaning, operands = _CHAI_PROPERTIES[word], []
            if called:
                # dirty-chai makes terminal properties callable; an argument
                # there is the failure message, not an operand.
                call = _call_arguments(text, code, position, end)
                if call is None or len(call[0]) > 1:
                    return None
                position = call[1]
        elif called and word in _CHAI_METHODS:
            call = _call_arguments(text, code, position, end)
            if call is None:
                return None
            meaning = _CHAI_METHODS[word]
            operands, position = call
        else:
            return None
        if (nested or own) and meaning == "include":
            return None
        if deep and meaning == "strict_equal":
            meaning = "deep_equal"
        following = _skip_space(masked, position, end)
        if following < end and masked.startswith((".", "[", "(", "?."), following):
            return None
        return meaning, not negated, operands, position, properties


def _asymmetric_matcher(
    text: str, code: bytearray, opening: int, limit: int, receiver: str,
) -> str | None:
    """`any` or `anything` when the matcher's whole operand is `<receiver>.any(...)`.

    The matcher must hang off the receiver the assertion itself uses (an
    aliased `expect` keeps its alias), and take its documented arity.
    """
    call = _call_argument_spans(text, code, opening, limit)
    if call is None or len(call[0]) != 1:
        return None
    start, end = _trim(text, code, call[0][0])
    pattern = re.compile(re.escape(receiver).replace(r"\.", r"\s*\.\s*")
                         + r"\s*\.\s*(?P<word>anything|any)\s*\(")
    match = pattern.match(text, start, end)
    if match is None or not code[start]:
        return None
    inner = _call_argument_spans(text, code, match.end() - 1, end)
    if inner is None or inner[1] != end or len(inner[0]) != _ASYMMETRIC_ARITY[match.group("word")]:
        return None
    return match.group("word")


def _equality_key(operand: str, *, strict: bool, undefined_global: bool) -> str:
    """The predicate key an equality states with this operand (#198).

    `=== null`, `=== undefined`, `=== true` and `=== false` are the presence
    keys every other spelling of them states (toBeNull, `.to.be.true`, ...);
    `== null` and `== undefined` both state is_nullish. Any other operand
    leaves the equality itself, whose operand the key does not record.
    """
    word = keyword_operand(operand)
    if word == "undefined" and not undefined_global:
        word = None
    if word in {"null", "undefined"}:
        return ("is_" + word) if strict else "is_nullish"
    if strict and word in {"true", "false"}:
        return "is_" + word
    return "eq_strict" if strict else "eq_loose"


def _state_predicate(assertion: Assertion, key: str | None, asserts: bool, negated: bool) -> None:
    """Record the key, and whether the assertion asserts it or its negation.

    `positive` then means what `ir/model.py` documents: `toBeDefined()` and
    `.not.toBeUndefined()` both assert is_undefined negatively. A spelling
    with no key keeps `positive` as "not negated", which is the same thing
    for the forms it names (#198).
    """
    if key is None:
        return
    assertion.predicate = key
    assertion.positive = asserts != negated


def _bound_readers(
    bindings: Bindings, position: int,
) -> tuple[Callable[[str], str | None], Callable[[tuple[str, ...]], bool]]:
    """What a bound operand at `position` reads: a name's initializer, an unshadowed global."""

    def lookup(name: str) -> str | None:
        return bindings.initializer(name, position) or None

    return lookup, lambda path: bindings.is_global(path, position)


def _number_global(bindings: Bindings | None, position: int) -> Callable[[], bool] | None:
    """Does `Number` still name the global at `position`? Asked only when an operand spells it (#226)."""
    if bindings is None:
        return None
    return lambda: bindings.is_global(("Number",), position)


# The forms whose operand is an expected value or a bound.
_EXPECTED_FORMS = frozenset({"compare_eq", "compare_ord", "approx"})


def _unevaluated_call(assertion: Assertion, bindings: Bindings | None, position: int) -> str | None:
    """The operand when it is a call checkwash neither folds nor resolves (#226).

    Its callee's root names a global: a builtin outside the fold set
    (`parseFloat('75')`) or a name no scope declares (226.Q1). A callee the
    file imports or declares is the provenance channel's, and the assertion
    libraries' own names (`expect.any(Number)`) are matchers, not values.
    """
    operand = assertion.operand_source
    if bindings is None or operand is None or assertion.right_value is not None:
        return None
    callee = operand_callee(operand)
    if callee is None:
        return None
    root = callee.split(".")[0]
    if not bindings.is_global((root,), position) or bindings.resolve(root, position).kind != "unknown":
        return None
    return operand


def _chai_assertion(
    meaning: str, operands: list[str], source: str, span: tuple[int, int], positive: bool = True,
    undefined_global: bool = True, bindings: Bindings | None = None,
) -> Assertion | None:
    """One chai assertion from subject-first operands; None when incomplete.

    Without `bindings` a closeTo delta is read as a literal only: no name
    is followed and no global is taken as unshadowed.
    """
    rule = _CHAI[meaning]
    if len(operands) < rule.operands or any(
        _EMPTY_ARGUMENT.fullmatch(operand) for operand in operands[:rule.operands]
    ):
        return None
    assertion = Assertion(
        id="",  # Assigned in source order together with the other assertions.
        form=rule.form,
        strength=rule.strength,
        text=source,
        span=span,
        left=operands[0],
        positive=positive,
    )
    expected = rule.implied if rule.expected is None else operands[rule.expected]
    if expected is not None:
        populate_expectation(assertion, expected, _number_global(bindings, span[0]))
    if rule.expected is not None:
        assertion.operand_source = operand_text(operands[rule.expected])
        if rule.form in _EXPECTED_FORMS:
            assertion.unevaluated_expected = _unevaluated_call(assertion, bindings, span[0])
    if rule.delta is not None:
        if bindings is None:
            lookup, builtin = (lambda _name: None), (lambda _path: False)
        else:
            lookup, builtin = _bound_readers(bindings, span[0])
        populate_delta(assertion, operands[rule.delta], lookup, builtin)
    key = rule.predicate
    if meaning in {"strict_equal", "loose_equal"}:
        key = _equality_key(operands[1], strict=meaning == "strict_equal", undefined_global=undefined_global)
    _state_predicate(assertion, key, rule.asserts, not positive)
    return assertion


# chai's should object (#215): `should.equal(actual, expected)` is
# `expect(actual).to.equal(expected)`, `should.exist(value)` its `.exist`,
# and `should.not.*` their negations.
_SHOULD_METHODS: dict[str, str] = {"equal": "strict_equal", "exist": "exist"}
_SHOULD_STEP = re.compile(r"\s*(?:\?\.|\.)\s*" + NAME)


def _chain_start(bindings: Bindings, last: int) -> int | None:
    """The first token of the member chain whose last token is `last`, or None.

    Names joined by `.` or `?.`, with calls and indexes on them, back to the
    chain's first name, string, parenthesized expression or array literal. A
    `new` before the first name is part of the chain: `new Order().should`
    reads the new instance, as `new` binds before the member access.
    """
    j = last
    while j >= 0:
        token = bindings.token(j)
        if token in {")", "]"} and j in bindings.pairs:
            opening = bindings.pairs[j]
            if opening > 0 and bindings._operand_end(opening - 1):
                j = opening - 1  # a call or an index on what comes before it
                continue
            return opening
        if re.fullmatch(NAME, token) or token[:1] in {"'", '"'}:
            if bindings.token(j - 1) in {".", "?."}:
                j -= 2
                continue
            if bindings.token(j - 1) == "new" and bindings.token(j - 2) not in {".", "?."}:
                return j - 1
            return j
        return None
    return None


def should_sites(text: str, code: bytearray, bindings: Bindings,
                 start: int = 0, end: int | None = None) -> list[tuple[int, str, int]]:
    """(subject start, subject, getter end) for each `.should` chain read off a value (#215).

    `chai.should()` puts the `should` getter on every object, in the test
    file or in a setup file the runner loads, so a `.should` chain is chai's
    should interface wherever a test spells it. A `.should` no chain
    continues from (`options.should`, `options.should = true`) asserts
    nothing, and neither does a call of it (`chai.should()` installs the
    getter).
    """
    end = len(text) if end is None else end
    sites = []
    for index in range(bisect_left(bindings.token_starts, start), len(bindings.tokens)):
        token, position, token_end = bindings.tokens[index]
        if position >= end:
            break
        if token != "should" or not code[position] or bindings.token(index - 1) not in {".", "?."}:
            continue
        if bindings.token(index + 1) not in {".", "?."} or not re.fullmatch(NAME, bindings.token(index + 2)):
            continue
        first = _chain_start(bindings, index - 2)
        if first is None or bindings.tokens[first][1] < start:
            continue
        subject_start = bindings.tokens[first][1]
        subject = text[subject_start:bindings.tokens[index - 1][1]].strip()
        if subject:
            sites.append((subject_start, subject, token_end))
    return sites


def _should_assertions(text: str, code: bytearray, bindings: Bindings, start: int, end: int,
                       owned: Callable[[int], bool]) -> list[Assertion]:
    """chai's should interface (#215), read as expect() chains are.

    `value.should.<chain>` is `expect(value).<chain>`, and the should
    object's `equal` and `exist`, with their `not` forms, take the subject
    first. A should chain the chain reader does not take is recorded with no
    strength, as an unread expect() call is (#196 190.5).
    """
    assertions: list[Assertion] = []
    masked = bindings.masked
    for subject_start, subject, getter_end in should_sites(text, code, bindings, start, end):
        if not owned(subject_start):
            continue
        undefined_global = bindings.is_global(("undefined",), subject_start)
        chain = _chai_chain(text, code, masked, getter_end, end)
        if chain is not None:
            meaning, positive, operands, span_end, properties = chain
            target = _retargeted(subject, properties)
            span = (subject_start, span_end)
            assertion = target and _chai_assertion(meaning, [target, *operands], text[span[0]:span[1]],
                                                   span, positive, undefined_global=undefined_global,
                                                   bindings=bindings)
            if assertion is not None:
                assertions.append(assertion)
                continue
        # The chain reader declined it: an assertion whose predicate is not read.
        cursor = getter_end
        while True:
            step = _SHOULD_STEP.match(masked, cursor, end)
            if step is None:
                break
            cursor = step.end()
            following = _skip_space(masked, cursor, end)
            if following < end and masked[following] == "(":
                call = _call_argument_spans(text, code, following, end)
                if call is None:
                    break
                cursor = call[1]
        assertions.append(Assertion(id="", form="unknown", strength=None, text=text[subject_start:cursor],
                                    span=(subject_start, cursor), left=subject))
    for match in CALL.finditer(masked, start, end):
        position = match.start()
        if not code[position] or not owned(position):
            continue
        value = bindings.callee(match.group("callee"), position)
        if value.kind != "chai_should_method" or value.method not in _SHOULD_METHODS:
            continue
        call = _call_arguments(text, code, match.end() - 1, end)
        if call is None:
            continue
        arguments, span_end = call
        span = (position, span_end)
        assertion = _chai_assertion(_SHOULD_METHODS[value.method], arguments, text[position:span_end], span,
                                    not value.negated,
                                    undefined_global=bindings.is_global(("undefined",), position),
                                    bindings=bindings)
        if assertion is not None:
            assertions.append(assertion)
    return assertions


def _retargeted(subject: str, properties: list[tuple[str, bool]]) -> str | None:
    """The subject after each `.property(name)` in a chain moved it (#215); None when one cannot be followed."""
    for name, nested in properties:
        subject = property_subject(subject, name, nested)
        if subject is None:
            return None
    return subject


# AVA's and tap's `t` assertions (#233), by the chai meaning each states and
# whether it asserts it (True) or its negation, operands subject first. AVA's
# `is` and tap's `equal` compare with Object.is and ===, a strict equality;
# `like` and `has` assert a subset of fields, as chai's deep `include` does;
# tap's `same` is loose and `strictSame` strict, both structural, as Node's
# deepEqual and deepStrictEqual are. The other assertions (`throws`,
# `snapshot`, tap's `type`, `hasProp`, `matchOnly`, ...) are recorded with no
# strength, as an unread expect() call is.
_AVA_METHODS: dict[str, tuple[str, bool]] = {
    "is": ("strict_equal", True), "not": ("strict_equal", False),
    "deepEqual": ("deep_equal", True), "notDeepEqual": ("deep_equal", False),
    "like": ("include", True),
    "true": ("true", True), "false": ("false", True),
    "truthy": ("ok", True), "assert": ("ok", True), "falsy": ("ok", False),
    "regex": ("match", True), "notRegex": ("match", False),
}
_TAP_METHODS: dict[str, tuple[str, bool]] = {
    "equal": ("strict_equal", True), "not": ("strict_equal", False),
    "same": ("deep_equal", True), "strictSame": ("deep_equal", True),
    "notSame": ("deep_equal", False), "strictNotSame": ("deep_equal", False),
    "ok": ("ok", True), "notOk": ("ok", False),
    "match": ("match", True), "notMatch": ("match", False),
    "has": ("include", True), "hasStrict": ("include", True),
    "notHas": ("include", False), "notHasStrict": ("include", False),
}
_CONTEXT_METHODS = {"ava_method": _AVA_METHODS, "tap_method": _TAP_METHODS}


def _context_assertions(text: str, code: bytearray, bindings: Bindings, start: int, end: int,
                        owned: Callable[[int], bool]) -> list[Assertion]:
    """AVA's and tap's `t` assertions (#233), read with chai's meanings.

    Only a method of a test callback's own `t`, of tap's root `t` or of a
    name bound from one: an assertion called on any other object named `t`
    is not one.
    """
    assertions: list[Assertion] = []
    masked = bindings.masked
    for match in CALL.finditer(masked, start, end):
        position = match.start()
        if not code[position] or not owned(position):
            continue
        # A member suffix, also across whitespace or comments, is another
        # object's method, and `new t.is(...)` constructs.
        previous = position - 1
        while previous >= 0 and (not code[previous] or text[previous].isspace()):
            previous -= 1
        if (previous >= 0 and text[previous] in ".#") or follows_new(masked, previous):
            continue
        value = bindings.callee(match.group("callee"), position)
        table = _CONTEXT_METHODS.get(value.kind)
        if table is None or value.method not in table:
            continue
        call = _call_arguments(text, code, match.end() - 1, end)
        if call is None:
            continue
        arguments, span_end = call
        meaning, asserts = table[value.method]
        span = (position, span_end)
        assertion = _chai_assertion(meaning, arguments, text[position:span_end], span, asserts,
                                    undefined_global=bindings.is_global(("undefined",), position),
                                    bindings=bindings)
        if assertion is not None:
            assertions.append(assertion)
    return assertions


_WORD_CHARACTER = re.compile(r"\w")


def follows_new(masked: str, previous: int) -> bool:
    """Does the text up to `previous` end in the word `new`?

    `re.search(r"\\bnew$", masked[:previous + 1])`, as each call scan asks
    it, without copying or scanning the text before (#235): `$` also
    matches before a final newline.
    """
    end = previous + 1
    for stop in ((end, end - 1) if end >= 1 and masked[end - 1] == "\n" else (end,)):
        start = stop - 3
        if (start >= 0 and masked.startswith("new", start)
                and (start == 0 or not _WORD_CHARACTER.match(masked, start - 1))):
            return True
    return False


def _recover_block_end(masked: str, opening: int) -> int | None:
    """Recover a callback after a malformed statement, without crossing it.

    Legacy assertion scanning keeps valid later calls in syntax-broken tests.
    At a statement terminator, abandon unclosed calls/arrays, retaining block
    nesting. A mismatched closer consumes its broken inner delimiter only.
    """
    closing = {"(": ")", "[": "]", "{": "}"}
    stack = ["}"]
    for position in range(opening + 1, len(masked)):
        char = masked[position]
        if char in closing:
            stack.append(closing[char])
        elif char == ";":
            while len(stack) > 1 and stack[-1] != "}":
                stack.pop()
        elif char in ")]}":
            if char == stack[-1]:
                stack.pop()
                if not stack:
                    return position
            elif len(stack) > 1:
                stack.pop()
    return None


def _callback_body(bindings: Bindings, span: tuple[int, int], *,
                   recover: bool = False) -> tuple[int, int] | None:
    """The body of one inline callback, never the text until the next test.

    This bounded structural reader uses the binding scanner's balanced tokens.
    Named callbacks, generators and computed test factories remain unknown.
    """
    starts = bindings.token_starts
    first, last = bisect_left(starts, span[0]), bisect_left(starts, span[1])
    while bindings.token(first) == "(" and bindings.pairs.get(first) == last - 1:
        first, last = first + 1, last - 1
    if bindings.token(first) == "async":
        first += 1
    if bindings.token(first) == "function":
        cursor = first + 1
        if re.fullmatch(NAME, bindings.token(cursor)):
            cursor += 1
        if bindings.token(cursor) != "(" or cursor not in bindings.pairs:
            return None
        body = bindings.pairs[cursor] + 1
        # Simple TS return annotations are inert syntax; object return types
        # and arbitrary signature programs are deliberately not inferred.
        if bindings.token(body) == ":":
            body += 1
            while body < last and (re.fullmatch(NAME, bindings.token(body))
                                   or bindings.token(body) in {"<", ">", "[", "]", ",", "|", "."}):
                body += 1
    else:
        cursor = first
        if bindings.token(cursor) == "(" and cursor in bindings.pairs:
            cursor = bindings.pairs[cursor] + 1
        elif re.fullmatch(NAME, bindings.token(cursor)):
            cursor += 1
        else:
            return None
        if bindings.token(cursor) == ":":
            cursor += 1
            while cursor < last and (re.fullmatch(NAME, bindings.token(cursor))
                                     or bindings.token(cursor) in {"<", ">", "[", "]", ",", "|", "."}):
                cursor += 1
        if bindings.token(cursor) != "=>":
            return None
        body = cursor + 1
    if body >= last:
        return None
    if bindings.token(body) == "{":
        if recover:
            end = _recover_block_end(bindings.masked, bindings.tokens[body][1])
            return (bindings.tokens[body][2], end) if end is not None else None
        closing = bindings.pairs.get(body)
        if closing != last - 1:
            return None
        return bindings.tokens[body][2], bindings.tokens[closing][1]
    if bindings.token(first) == "function":
        return None
    if recover:
        return None  # An invalid concise body has no trustworthy delimiter.
    return bindings.tokens[body][1], bindings.tokens[last - 1][2]


@dataclass
class _Declaration:
    """One `test`/`describe` call and the liveness it declares itself."""

    start: int
    unit: bool
    table: bool  # `.each`/`.for`: one item per row, outside the unit scan
    opening: int
    name: str | None
    name_end: int | None
    call: tuple[list[tuple[int, int]], int] | None
    markers: list[Marker]
    focus: Marker | None  # the evidence for every unit this focus turns off
    callback: tuple[int, int, int, tuple[int, int]] | None = None


def _truth(source: str) -> bool | None:
    """A liveness value's truthiness when it is a literal, else None.

    Only literals are decided, so nothing reads as falsy unless it is spelled
    as a falsy literal. Any other value is a condition this scan does not
    evaluate; it stays a disable, as an unverifiable Python `skipif` does.
    """
    value = source.strip()
    if re.fullmatch(r"`[^`\\$]*`", value):
        return len(value) > 2
    keep = _code_positions(value, keep_strings=True)
    value = "".join(c if keep[i] else " " for i, c in enumerate(value)).strip()
    negated = False
    while value.startswith("!"):
        negated, value = not negated, value[1:].strip()
    if value == "true":
        truth = True
    elif value in {"false", "null", "undefined", "NaN"}:
        truth = False
    elif _STRING_RE.fullmatch(value):
        truth = len(value) > 2
    elif _NUMBER_RE.fullmatch(value):
        truth = not _ZERO_RE.fullmatch(value)
    else:
        return None
    return truth != negated


def _options(text: str, code: bytearray,
             span: tuple[int, int]) -> list[tuple[str, str, tuple[int, int]]]:
    """(key, value source, property span) for each liveness key of an inline
    object-literal argument.

    Only literal keys are read: a spread, a computed key or an accessor is not
    a value this scan can see. A comment does not hide a key.
    """
    start, end = span
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    if (end - start < 2 or text[start] != "{" or text[end - 1] != "}"
            or not code[start] or not code[end - 1]):
        return []
    pieces: list[tuple[int, int]] = []
    depth = 0
    piece = start + 1
    for i in range(start + 1, end - 1):
        if not code[i]:
            continue
        if text[i] in "([{":
            depth += 1
        elif text[i] in ")]}":
            depth -= 1
            if depth < 0:
                return []  # `{...}.key || {...}` is not one object literal
        elif text[i] == "," and depth == 0:
            pieces.append((piece, i))
            piece = i + 1
    pieces.append((piece, end - 1))
    keep = _code_positions(text[start:end], keep_strings=True)
    blank = "".join(c if keep[i] else " " for i, c in enumerate(text[start:end]))
    found: list[tuple[str, str, tuple[int, int]]] = []
    for first, last in pieces:
        match = _PROPERTY_RE.match(blank, first - start, last - start)
        if match is None:
            continue
        key = match.group("key") or match.group("quoted")
        if key not in _OPTION_EFFECTS:
            continue
        if match.group("colon"):
            value = text[start + match.end():last]
        elif match.group("key") and not blank[match.end():last - start].strip():
            value = key  # shorthand `{ skip }` reads a variable
        else:
            continue  # a method or accessor named like the key
        lead, tail = first, last
        while lead < tail and text[lead].isspace():
            lead += 1
        while tail > lead and text[tail - 1].isspace():
            tail -= 1
        found.append((key, value, (lead, tail)))
    return found


def _declaration(text: str, code: bytearray, bindings: Bindings,
                 match: re.Match[str]) -> _Declaration | None:
    """Read `word(.modifier | .curried(args))* (` and what the chain declares.

    Anything else ends the chain without a declaration, which keeps
    `const run = test.skip;` and `test.extend(...)` out of the scan.
    """
    word = match.group("word")
    unit = word in _UNIT_WORDS
    prefix = _UNIT_WORDS[word] if unit else _BLOCK_WORDS[word]
    if prefix:
        previous = match.start() - 1
        while previous >= 0 and bindings.masked[previous].isspace():
            previous -= 1
        if previous >= 0 and bindings.masked[previous] in ".#":
            return None
    effects = {prefix}
    conditions: list[str] = []
    table = False
    cursor = match.end()
    while True:
        while cursor < len(text) and text[cursor].isspace():
            cursor += 1
        if cursor >= len(text) or not code[cursor]:
            return None
        if text[cursor] == "(":
            break
        member = _MEMBER_RE.match(text, cursor)
        if member is None:
            return None
        modifier, cursor = member.group("member"), member.end()
        if modifier in _MODIFIERS:
            effects.add(_MODIFIERS[modifier])
            continue
        if modifier not in _CURRIED:
            return None
        while cursor < len(text) and text[cursor].isspace():
            cursor += 1
        if modifier in {"each", "for"} and text.startswith("`", cursor):
            # A tagged-template table is opaque to the code mask.
            while cursor < len(text) and not code[cursor]:
                cursor += 1
            table = True
            continue
        if not text.startswith("(", cursor) or not code[cursor]:
            return None
        curried = _call_argument_spans(text, code, cursor, len(text))
        if curried is None:
            return None
        arguments, cursor = curried
        if modifier in {"each", "for"}:
            table = True
            continue
        if not arguments:
            return None
        condition = text[arguments[0][0]:arguments[0][1]].strip()
        skips = _truth(condition)
        if modifier == "runIf":
            skips = None if skips is None else not skips
            condition = f"!({condition})"
        if skips is None:
            conditions.append(normalize_text(condition))
        elif skips:
            effects.add("skip")
    opening = cursor
    if re.search(r"\bfunction\s*\*?\s*$", bindings.masked[max(0, match.start() - 32):match.start()]):
        return None  # `function fit(model) {` defines a helper and declares nothing
    call = _call_argument_spans(text, code, opening, len(text))
    if call is not None:
        following = call[1]
        while following < len(text) and text[following] in " \t":
            following += 1
        if following < len(text) and text[following] == "{" and code[following]:
            return None  # a method signature, `fit(data) {`, not a call
    title = _TITLE_RE.match(text, opening + 1)
    if prefix and title is None and (call is None or all(
            _callback_body(bindings, call[0][position]) is None
            for position in (1, 2) if position < len(call[0]))):
        # A prefixed global names its test or passes it inline; `fit(points)`
        # and a typed `fit(x: number[]): Model` method belong to a helper.
        return None
    evidence = text[match.start():opening].rstrip()
    span = (match.start(), title.end() if title else opening + 1)
    markers = [Marker(name="test.skip", text=evidence, span=span)] if "skip" in effects else []
    markers.extend(Marker(name=f"test.skipIf({condition})", text=evidence, span=span)
                   for condition in conditions)
    if "fails" in effects:
        markers.append(Marker(name="test.fails", text=evidence, span=span))
    focus = Marker(name="test.unfocused", text=evidence, span=span) if "only" in effects else None
    # node:test `test(name, { skip }, fn)`, Vitest `test(name, { fails }, fn)`
    # and its older `test(name, fn, { skip })`: the same effects, as keys.
    options: dict[str, tuple[str, tuple[int, int]]] = {}
    for position in ((1, 2) if title else (0, 1, 2)):
        if call is not None and position < len(call[0]):
            for key, value, where in _options(text, code, call[0][position]):
                options[key] = (value, where)  # a later duplicate key wins
    for key, (value, where) in options.items():
        truth = _truth(value)
        if truth is False:
            continue
        source = text[where[0]:where[1]]
        effect = _OPTION_EFFECTS[key]
        if effect == "only":
            focus = focus or Marker(name="test.unfocused", text=source, span=where)
        elif effect == "fails":
            markers.append(Marker(name="test.fails", text=source, span=where))
        else:
            name = "test.skip" if truth else f"test.skipIf({normalize_text(value.strip())})"
            markers.append(Marker(name=name, text=source, span=where))
    return _Declaration(
        start=match.start(), unit=unit, table=table, opening=opening,
        name=title.group("name") if title else None,
        name_end=title.end() if title else None,
        call=call, markers=markers, focus=focus,
    )


def _test_body(text: str, code: bytearray, bindings: Bindings,
               declaration: _Declaration) -> tuple[int, int, int, tuple[int, int]] | None:
    """(body start, body end, unit end, callback argument span), or None."""
    call = declaration.call
    if call is None:
        # Recover only an inline block callback after the literal test name.
        # The normal argument parser deliberately rejects malformed inner
        # calls; those must not hide a later valid assertion in the same body.
        if declaration.name_end is None:
            return None
        cursor = bisect_left(bindings.token_starts, declaration.name_end)
        if bindings.token(cursor) != ",":
            return None
        cursor += 1
        if bindings.token(cursor) == "{" and cursor in bindings.pairs:
            cursor = bindings.pairs[cursor] + 1
            if bindings.token(cursor) != ",":
                return None
            cursor += 1
        if cursor >= len(bindings.tokens):
            return None
        argument = (bindings.tokens[cursor][1], len(text))
        body = _callback_body(bindings, argument, recover=True)
        if body is not None:
            # A malformed call cannot supply a trustworthy final ')'. The
            # recovered closing brace is the upper bound of this test unit.
            return body[0], body[1], body[1] + 1, argument
        return None
    arguments, call_end = call
    # Jest/Vitest callback is second; Node also permits an options object.
    # A third timeout/options argument is not another callback.
    for position in (1, 2):
        if position >= len(arguments):
            continue
        body = _callback_body(bindings, arguments[position])
        if body is not None:
            return body[0], body[1], call_end, arguments[position]
    return None


def _declarations(text: str, code: bytearray, bindings: Bindings) -> list[_Declaration]:
    """Every declaration in source order, with its callback where it matters:
    always for a scanned unit, otherwise only when the declaration has an
    effect a nested unit can inherit."""
    declarations: list[_Declaration] = []
    for match in _DECLARATION_RE.finditer(text):
        if not code[match.start()]:
            continue
        declaration = _declaration(text, code, bindings, match)
        if declaration is None:
            continue
        scanned = declaration.unit and not declaration.table and declaration.name is not None
        if scanned or declaration.markers or declaration.focus is not None:
            declaration.callback = _test_body(text, code, bindings, declaration)
        declarations.append(declaration)
    return declarations


def _callback_receivers(bindings: Bindings, span: tuple[int, int]) -> frozenset[str]:
    """The names a callback's own test context answers to.

    Its first simple parameter (node:test `t`, a Vitest `ctx`) and, for a
    `function` callback, Mocha's `this`. A destructured context is not
    followed.
    """
    starts = bindings.token_starts
    first, last = bisect_left(starts, span[0]), bisect_left(starts, span[1])
    while bindings.token(first) == "(" and bindings.pairs.get(first) == last - 1:
        first, last = first + 1, last - 1
    if bindings.token(first) == "async":
        first += 1
    names: set[str] = set()
    if bindings.token(first) == "function":
        names.add("this")
        first += 1
        if re.fullmatch(NAME, bindings.token(first)):
            first += 1
    if bindings.token(first) == "(":
        first += 1
    parameter = bindings.token(first)
    if re.fullmatch(NAME, parameter) and bindings.token(first + 1) in {")", ",", ":", "=", "=>"}:
        names.add(parameter)
    return frozenset(names)


def _imperative_skips(text: str, code: bytearray, bindings: Bindings,
                      callback: tuple[int, int, int, tuple[int, int]] | None,
                      start: int, end: int, owned: Callable[[int], bool]) -> list[Marker]:
    """`t.skip()`/`t.todo()` on the callback's own context, Mocha `this.skip()`.

    The imperative spelling of the same skip: Vitest and Mocha stop the test
    there, node:test reports it skipped (or todo) without stopping it. A call
    in a nested function belongs to that function, as an assertion would.
    """
    if callback is None:
        return []
    found: list[Marker] = []
    receivers: frozenset[str] | None = None
    for candidate in CALL.finditer(bindings.masked, start, end):
        receiver, _, method = re.sub(r"\s+", "", candidate.group("callee")).rpartition(".")
        if method not in {"skip", "todo"} or not owned(candidate.start()):
            continue
        if receivers is None:
            receivers = _callback_receivers(bindings, callback[3])
        if receiver not in receivers or (receiver == "this" and method != "skip"):
            continue
        call = _call_argument_spans(text, code, candidate.end() - 1, end)
        if call is None:
            continue
        spans, call_end = call
        if any(_callback_body(bindings, span) is not None for span in spans):
            # tap's `t.skip(name, fn)` declares a skipped subtest; an
            # imperative skip never takes a function.
            continue
        arguments = [text[first:last].strip() for first, last in spans]
        name = "test.skip"
        if arguments and not (_STRING_RE.fullmatch(arguments[0]) or re.fullmatch(r"`[^`]*`", arguments[0])):
            # Vitest's `ctx.skip(condition)`; the condition is not evaluated.
            name = f"test.skipIf({normalize_text(arguments[0])})"
        found.append(Marker(name=name, text=text[candidate.start():call_end],
                            span=(candidate.start(), call_end)))
    return found


def _focus_stops(text: str, code: bytearray, bindings: Bindings,
                 declarations: list[_Declaration], innermost: bool) -> dict[int, Marker]:
    """The units a focused file stops, by id, each with the focus to cite.

    Declarations nest by callback. A unit runs when it is focused, or when a
    test around it is: node:test runs every subtest of a focused test. Any
    other unit stands or falls with its outermost enclosing test, and the
    blocks around that test decide (#196 187.2):

    - Jest's rule, for Jest and for a runner that is not known, since it is
      the most permissive of the runners measured: a block's focus reaches
      every block inside it, and the tests directly in it unless one of them
      is focused itself (jest-circus, `finish_describe_definition`).
    - The innermost rule (`innermost`), for Vitest, Jasmine and node:test: a
      focused block runs only its focused descendants, when it has any.
      Focus inside a test does not count, since node:test meets a subtest
      only once its test runs. Mocha is stricter still: a block with
      focused tests of its own also drops its inner blocks. That stays
      unreported.

    A unit with no focused block around it is stopped by the file's first
    focus, as before. Otherwise the cited focus is the first one inside the
    nearest focused block around the unit that is not around the unit
    itself.
    """
    for declaration in declarations:
        if declaration.callback is None:
            declaration.callback = _test_body(text, code, bindings, declaration)
    parent: dict[int, _Declaration | None] = {}
    open_blocks: list[_Declaration] = []
    for declaration in declarations:
        while open_blocks and open_blocks[-1].callback[1] <= declaration.start:
            open_blocks.pop()
        parent[id(declaration)] = next(
            (d for d in reversed(open_blocks) if d.callback[0] <= declaration.start), None)
        if declaration.callback is not None:
            open_blocks.append(declaration)

    def around(declaration: _Declaration) -> list[_Declaration]:
        """The declarations enclosing this one, outermost first."""
        found = []
        host = parent[id(declaration)]
        while host is not None:
            found.append(host)
            host = parent[id(host)]
        return found[::-1]

    focused = [d for d in declarations if d.focus is not None]
    # Blocks that hold a focused unit directly (Jest), or a focused
    # declaration not inside a test (the innermost rule).
    holding: set[int] = set()
    for declaration in focused:
        host = parent[id(declaration)]
        if not innermost:
            if declaration.unit and host is not None:
                holding.add(id(host))
            continue
        while host is not None and not host.unit:
            holding.add(id(host))
            host = parent[id(host)]
    stops: dict[int, Marker] = {}
    for unit in declarations:
        if not unit.unit or unit.focus is not None:
            continue
        chain = around(unit)
        if any(d.unit and d.focus is not None for d in chain):
            continue
        standing = next((d for d in chain if d.unit), unit)
        blocks = around(standing)
        if innermost:
            runs = any(b.focus is not None and id(b) not in holding for b in blocks)
        else:
            runs = (bool(blocks) and any(b.focus is not None for b in blocks)
                    and id(blocks[-1]) not in holding)
        if runs:
            continue
        nearest = next((d for d in reversed(chain) if d.focus is not None), None)
        cited = focused[0].focus
        if nearest is not None:
            members = {id(d) for d in chain}
            cited = next((d.focus for d in focused
                          if nearest.callback[0] <= d.start < nearest.callback[1]
                          and id(d) not in members), cited)
        stops[id(unit)] = cited
    return stops


def _unit_markers(declaration: _Declaration, ancestors: list[_Declaration],
                  stopped_by: Marker | None, imperative: list[Marker]) -> list[Marker]:
    """One liveness definition for every declaration level (issues #176, #178).

    A unit runs unless it, or a declaration whose callback encloses it, is
    skipped, conditionally skipped or inverted, or unless the file's focus
    stops it (`stopped_by`, from `_focus_stops`). Each effect is a state,
    not a count: `it.skip` inside `describe.skip` is one skip. Every reason
    is its own marker, as stacked Python markers are: a skipped unit outside
    the focus carries both, so re-enabling it while a committed `.only` still
    holds the focus adds no disable.
    """
    chain = [d for d in ancestors if d is not declaration and d.callback is not None
             and d.callback[0] <= declaration.start < d.callback[1]]
    chain.append(declaration)
    markers: list[Marker] = []
    for marker in [m for d in chain for m in d.markers] + imperative:
        if all(marker.name != kept.name for kept in markers):
            markers.append(Marker(name=marker.name, text=marker.text, span=marker.span))
    if stopped_by is not None:
        markers.append(Marker(name="test.unfocused", text=stopped_by.text, span=stopped_by.span))
    return markers


def _trim(text: str, code: bytearray, span: tuple[int, int]) -> tuple[int, int]:
    """Drop whitespace and comments around an operand, keeping its source."""
    start, end = span
    while start < end and (not code[start] or text[start].isspace()):
        start += 1
    while end > start and (not code[end - 1] or text[end - 1].isspace()):
        end -= 1
    return start, end


def _relational_split(
    text: str, code: bytearray, span: tuple[int, int],
) -> tuple[tuple[int, int], str, tuple[int, int]] | None:
    """`a < b` as (a, "<", b), when that comparison is the whole expression.

    Exactly one top-level `<`, `<=`, `>` or `>=`. An equality, logical,
    conditional, assignment, sequence or shift operator at the top level
    makes the comparison part of something larger, and nothing is claimed.
    Brackets nest; literal and comment contents are outside the code mask.
    """
    start, end = span
    depth = 0
    found: tuple[int, int] | None = None
    i = start
    while i < end:
        char = text[i]
        if not code[i]:
            pass
        elif char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
            if depth < 0:
                return None
        elif depth == 0 and char in "<>":
            following = text[i + 1] if i + 1 < end else ""
            if found is not None or following in {"<", ">"}:
                return None
            found = (i, i + 2 if following == "=" else i + 1)
            i = found[1]
            continue
        elif depth == 0 and char in "=!&|?:,;":
            return None
        i += 1
    if found is None or depth:
        return None
    return (start, found[0]), text[found[0]:found[1]], (found[1], end)


# Prefix keywords: a `-` after one is a sign, as after an operator.
_PREFIX_WORDS = frozenset({"typeof", "void", "await", "delete", "new", "yield"})
# Binary words that bind looser than a subtraction (`a - b in c`, `a - b as T`).
_LOOSER_WORDS = frozenset({"in", "instanceof", "as", "satisfies"})
_WORD = re.compile(r"[^\W\d][\w$]*|\$[\w$]*")
_EXPONENT_HEAD = re.compile(r"(?:\d[\d_]*(?:\.[\d_]*)?|\.\d[\d_]*)[eE]")


def _difference_split(
    text: str, code: bytearray, span: tuple[int, int],
) -> tuple[tuple[int, int], tuple[int, int]] | None:
    """`a - b` as (a, b), when that one subtraction is the whole expression.

    Exactly one top-level binary `-`. A second additive operator, or one
    that binds looser (a comparison, equality, logical, conditional,
    assignment, sequence or shift operator, `in`, `instanceof`, `as`,
    `satisfies`), makes the difference part of something larger, and
    nothing is claimed; `*`, `/`, `%` and `**` bind tighter and stay inside
    a side. A `-` after an operator, an opening bracket, a prefix keyword or
    nothing is a sign, and so is the one in an exponent (`1e-5`). `--`,
    `++`, `-=` and `+=` are never a difference. Brackets nest; literal and
    comment contents are outside the code mask.
    """
    start, end = span
    depth = 0
    found: int | None = None
    operand = False  # does the code read so far end an operand?
    i = start
    while i < end:
        char = text[i]
        if not code[i] or char.isspace():
            i += 1
            continue
        if char in "([{":
            depth += 1
            operand = False
        elif char in ")]}":
            depth -= 1
            if depth < 0:
                return None
            operand = True
        elif depth:
            operand = False
        elif char in "+-":
            following = text[i + 1] if i + 1 < end else ""
            if following in {char, "="}:
                return None
            if operand:
                if char == "+" or found is not None:
                    return None
                found = i
            operand = False
        elif char == "?" and text[i + 1:i + 2] == "." and not text[i + 2:i + 3].isdigit():
            i += 2  # optional chaining reads a member, like `.`
            operand = False
            continue
        elif char in "<>=!&|^?:,;":
            return None
        elif char.isdigit() or char == ".":
            number = _EXPONENT_HEAD.match(text, i, end)
            if number is not None and number.end() < end and text[number.end()] in "+-":
                i = number.end() + 1  # the exponent's sign is part of the number
                continue
            operand = True
        else:
            word = _WORD.match(text, i, end)
            if word is None:
                operand = False
            else:
                if word.group() in _LOOSER_WORDS:
                    return None
                operand = word.group() not in _PREFIX_WORDS
                i = word.end()
                continue
        i += 1
    if found is None or depth:
        return None
    left = _operand_span(text, code, (start, found))
    right = _operand_span(text, code, (found + 1, end))
    if left[0] == left[1] or right[0] == right[1]:
        return None
    return left, right


def _operand_span(text: str, code: bytearray, span: tuple[int, int]) -> tuple[int, int]:
    """An operand without surrounding whitespace, and its redundant parentheses when it has code edges.

    The code mask leaves out string contents as well as comments, so an
    operand that begins or ends with a literal (`value - "78.75"`) is kept as
    written rather than trimmed into its neighbour.
    """
    start, end = span
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    if start < end and code[start] and code[end - 1]:
        return _without_parentheses(text, code, (start, end))
    return start, end


def _without_parentheses(text: str, code: bytearray, span: tuple[int, int]) -> tuple[int, int]:
    """An expression without surrounding whitespace, comments or redundant parentheses.

    `((a < b))` is read as `a < b`; `(a) < (b)` and `(a, b)` stay whole. The
    comparison and its `Math.abs` operand both go through this one peeling.
    """
    start, end = _trim(text, code, span)
    while start < end and text[start] == "(":
        group = _call_argument_spans(text, code, start, end)
        if group is None or group[1] != end or len(group[0]) != 1:
            break
        start, end = _trim(text, code, group[0][0])
    return start, end


def _absolute_value_call(text: str, code: bytearray, span: tuple[int, int]) -> bool:
    """Is the operand one complete `Math.abs(...)` call, parentheses aside?"""
    start, end = _without_parentheses(text, code, span)
    match = _ABS_CALL.match(text, start, end)
    if match is None:
        return False
    call = _call_argument_spans(text, code, match.end() - 1, end)
    return call is not None and call[1] == end and len(call[0]) == 1


_BOUND_KEYS = {"<": "lt", "<=": "le", ">": "gt", ">=": "ge"}
_REVERSED = {"<": ">", "<=": ">=", ">": "<", ">=": "<="}


@dataclass(frozen=True)
class _HandRolled:
    """A hand-rolled `Math.abs(d) <op> bound`, read from the magnitude's side."""

    key: str  # lt/le bound the magnitude above (a tolerance); gt/ge below
    operand: str | None  # the bound's text when its value was read, else None


def _record_tolerance(
    assertion: Assertion, text: str, code: bytearray, bindings: Bindings,
    subject: tuple[int, int], operator: str | None = None,
    bound: tuple[int, int] | None = None,
) -> _HandRolled | None:
    """Read `Math.abs(a - b) < bound` as the absolute tolerance it states.

    Issue #179: `assert.ok(Math.abs(total - 78.75) < 0.01)` widened to
    `< 1e12` reached no detector, because the whole comparison was an opaque
    truthy subject. Every spelling goes through this one reading: a truthy
    oracle passes its subject and the comparison is split out of it; an
    ordering matcher passes subject, operator and bound. Both orientations
    count (`eps > Math.abs(d)`), and the magnitude must be an unshadowed
    `Math.abs` call. On the larger side (`Math.abs(d) > eps`) it asserts
    that two values differ: a lower bound, read for its direction so a
    `<` -> `>` flip can be reported (#196 189.3), which records no
    tolerance. Either way the assertion's `left` becomes what the magnitude
    measures, and a literal centre its expected value (`_decompose`, #196
    189.2), so both directions of one check share a subject. Returns the
    reading, or None when the comparison is not a hand-rolled bound.
    """
    if operator is None or bound is None:
        # Redundant parentheses around the whole comparison state the same
        # bound: `assert.ok((Math.abs(d) < eps))` (review of #189).
        split = _relational_split(text, code, _without_parentheses(text, code, subject))
        if split is None:
            return None
        subject, operator, bound = split
    if operator in {">", ">="}:
        subject, bound = bound, subject
        operator = _REVERSED[operator]
    position = assertion.span[0]
    if not bindings.is_global(("Math", "abs"), position):
        return None
    if _absolute_value_call(text, code, subject):
        key = _BOUND_KEYS[operator]
    elif _absolute_value_call(text, code, bound):
        subject, bound = bound, subject
        key = _BOUND_KEYS[_REVERSED[operator]]
    else:
        return None
    expression = text[bound[0]:bound[1]]
    value = read_bound(expression, *_bound_readers(bindings, position))
    if value is not None and key in {"lt", "le"}:
        assertion.epsilon = f"abs={value}"
        assertion.epsilon_kind = "abs"
    _decompose(assertion, text, code, subject)
    return _HandRolled(key, None if value is None else operand_text(expression))


def _decompose(assertion: Assertion, text: str, code: bytearray, magnitude: tuple[int, int]) -> None:
    """Record what `Math.abs(...)` measures as `left`, and a literal centre as the expected value.

    `Math.abs(total - 78.75) < 0.01` checks `total` against 78.75 within
    0.01, as `pytest.approx(78.75, abs=0.01)` would: the subject is `total`,
    78.75 is the expected value and the bound the tolerance (#196 189.2).
    So rewriting the centre is an expected value rewritten, and pairing
    keys on the subject. Only a Number literal is a centre, on either side
    of the one subtraction; with none (`Math.abs(total - expected)`,
    `Math.abs(d)`) or two, the whole argument is `left` and there is no
    expected value. Either signed zero is the same centre, because the
    comparison measures a distance.
    """
    start, end = _without_parentheses(text, code, magnitude)
    call = _call_argument_spans(text, code, _ABS_CALL.match(text, start, end).end() - 1, end)
    argument = _operand_span(text, code, call[0][0])
    subject, centre, value = argument, None, None
    split = _difference_split(text, code, argument)
    if split is not None:
        values = [number_operand(text[side[0]:side[1]]) for side in split]
        if (values[0] is None) != (values[1] is None):
            index = 0 if values[0] is not None else 1
            centre, subject, value = split[index], split[1 - index], values[index]
    assertion.left = text[subject[0]:subject[1]]
    assertion.right_literal = assertion.right_value = None
    if centre is not None:
        assertion.right_literal = text[centre[0]:centre[1]]
        assertion.right_value = repr(0.0 if value == 0 else value)


def comparison_magnitude(source: str) -> str | None:
    """The `Math.abs(...)` side of a hand-rolled comparison, as `_record_tolerance` reads it.

    This reads the text only; whether `Math` is unshadowed is the caller's
    question. Rules no longer need it: the frontend records what the
    magnitude measures as the assertion's `left` (#196 189.3, 189.2).
    """
    code = _code_positions(source)
    split = _relational_split(source, code, _without_parentheses(source, code, (0, len(source))))
    if split is None:
        return None
    smaller, operator, larger = split
    if operator in {">", ">="}:
        smaller, larger = larger, smaller
    for side in (smaller, larger):
        if _absolute_value_call(source, code, side):
            start, end = _without_parentheses(source, code, side)
            return normalize_text(source[start:end])
    return None


def _node_assertions(text: str, code: bytearray, start: int, end: int,
                     bindings: Bindings | None = None) -> list[Assertion]:
    """Direct assertion calls: node:assert and chai's assert interface."""
    assertions: list[Assertion] = []
    bindings = bindings or Bindings(text, code, _code_positions(text, keep_strings=True))
    for match in _ASSERT_RE.finditer(bindings.masked, start, end):
        if not code[match.start()]:
            continue
        # Also reject a member suffix separated by whitespace or comments,
        # e.g. obj. /* comment */ assert.ok(x). Only the explicit t.assert
        # spelling above is recognized as a Node test-context assertion.
        previous = match.start() - 1
        while previous >= 0 and (not code[previous] or text[previous].isspace()):
            previous -= 1
        if previous >= 0 and text[previous] in ".#":
            continue
        value = bindings.callee(match.group("callee"), match.start())
        method = value.method or None
        if value.strict:
            # node:assert/strict (and `assert.strict`) is the strict mode:
            # its equal is strictEqual and its deepEqual deepStrictEqual.
            method = _STRICT_MODE.get(method, method)
        # chai's assert interface shares this call shape and its declaration
        # filters; its methods take the meanings expect() chains use.
        is_chai = value.kind in {"chai_assert", "chai_assert_method"}
        if not is_chai and value.kind not in {"node", "node_method"}:
            continue
        if method is not None and not (
                method in _CHAI_ASSERT or method in _CHAI_ASSERT_PROPERTY if is_chai else method in _ASSERT_STRENGTH):
            continue
        if follows_new(bindings.masked, previous):
            continue
        if method is None:
            # Function declarations (including generators and TS return
            # annotations) also spell assert(...), but never call it.
            token_end = previous + 1
            if previous >= 0 and text[previous] == "*":
                previous -= 1
                while previous >= 0 and (not code[previous] or text[previous].isspace()):
                    previous -= 1
                token_end = previous + 1
            while previous >= 0 and (text[previous].isalnum() or text[previous] in "_$"):
                previous -= 1
            if text[previous + 1:token_end] == "function":
                continue
        call = _call_argument_spans(text, code, match.end() - 1, end)
        if call is None:
            continue
        argument_spans, span_end = call
        arguments = [text[first:last].strip() for first, last in argument_spans]
        following = span_end
        while following < end and (not code[following] or text[following].isspace()):
            following += 1
        if method is None and following < end:
            if text[following] == ":" and not _conditional_arm(text, code, match.start()):
                continue  # A TypeScript method's return annotation.
            if text[following] == "{" and "\n" not in text[span_end:following]:
                continue  # A method signature, not a call followed by an ASI block.
        undefined_global = bindings.is_global(("undefined",), match.start())
        if is_chai:
            meaning = _CHAI_ASSERT.get(method or "ok")
            if method in _CHAI_ASSERT_PROPERTY:
                # assert.propertyVal(object, name, value) asserts on object[name].
                meaning, nested = _CHAI_ASSERT_PROPERTY[method]
                subject = property_subject(arguments[0], arguments[1], nested) if len(arguments) >= 2 else None
                if subject is None:
                    continue
                arguments = [subject, *arguments[2:]]
            chai_call = _chai_assertion(meaning, arguments,
                                        text[match.start():span_end], (match.start(), span_end),
                                        undefined_global=undefined_global, bindings=bindings)
            if chai_call is not None:
                assertions.append(chai_call)
            continue
        form, strength = _ASSERT_STRENGTH[method or "ok"]
        required = 2 if form == "compare_eq" else 1
        if len(arguments) < required or any(_EMPTY_ARGUMENT.fullmatch(arg) for arg in arguments[:required]):
            continue
        assertion = Assertion(
            id="",  # Assigned in source order together with expect calls.
            form=form,
            strength=strength,
            text=text[match.start():span_end],
            span=(match.start(), span_end),
            left=arguments[0],
        )
        if form == "compare_eq":
            # Every equality records its scalar operand. The legacy methods
            # coerce, and their key says so: equal is eq_loose (#196 190.2).
            populate_expectation(assertion, arguments[1], _number_global(bindings, match.start()))
            assertion.operand_source = operand_text(arguments[1])
            assertion.unevaluated_expected = _unevaluated_call(assertion, bindings, match.start())
        key = None
        if form == "truthy":
            key = "truthy"
        elif method in {"strictEqual", "equal"}:
            key = _equality_key(arguments[1], strict=method == "strictEqual",
                                undefined_global=undefined_global)
        # A truthy oracle, or its strict `=== true` spelling, may be a
        # hand-rolled tolerance (issue #179). Its key is then the bound it
        # states, so a `<` -> `>` flip reads as one (#196 189.3).
        if form == "truthy" or (method in {"strictEqual", "deepStrictEqual"}
                                and assertion.right_value == "True"):
            hand = _record_tolerance(assertion, text, code, bindings, argument_spans[0])
            if hand is not None:
                key = hand.key
                assertion.operand_source = hand.operand
        _state_predicate(assertion, key, True, False)
        assertions.append(assertion)
    return assertions


def _conditional_arm(text: str, code: bytearray, end: int) -> bool:
    """Does the preceding expression have a '?' waiting for its ':'?

    A colon after assert(...) can end a conditional arm instead of starting
    a TypeScript method annotation. Ignore grouped expressions and already
    paired conditionals when looking back to the expression boundary.
    """
    groups: list[str] = []
    colons = 0
    for i in range(end - 1, -1, -1):
        if not code[i]:
            continue
        char = text[i]
        if char in ")]}":
            groups.append({")": "(", "]": "[", "}": "{"}[char])
        elif char in "([{":
            if not groups or groups.pop() != char:
                return False
        elif not groups:
            if char == ";":
                return False
            if char == ":":
                colons += 1
            elif char == "?" and text[i + 1:i + 2] not in {"?", "."} and text[i - 1:i] != "?":
                if not colons:
                    return True
                colons -= 1
    return False


# A call that may be an assertion the scans above do not represent: a member
# or an indexed member (`assert['match']`), reached with `.` or `?.`. This is
# the frontend's own recognizer; the coverage inventory keeps its own, so
# that a call this one misses stays visible there (#196 190.5).
_CANDIDATE_CALL = re.compile(
    r"(?<![\w$.#])" + NAME
    + r"(?:\s*(?:\?\.|\.)\s*" + NAME + r"|\s*\[[^]\n]*\])*"
    r"\s*(?:\?\.)?\s*\("
)
_CANDIDATE_STEP = re.compile(r"\s*(?:\?\.|\.)\s*(?P<word>" + NAME + r")")
_CANDIDATE_INDEX = re.compile(r"\[\s*(['\"])(?P<word>" + NAME + r")\1\s*\]")
# The throw family: the subject throws, or its promise rejects.
_THROW_WORDS = frozenset({
    "throws", "throwsAsync", "rejects", "isRejected", "throw", "Throw", "rejected", "rejectedWith",
    "toThrow", "toThrowError", "toThrowErrorMatchingSnapshot", "toThrowErrorMatchingInlineSnapshot",
})
# Words that assert the opposite: no throw, no rejection.
_NEGATING_WORDS = frozenset({"not", "doesNotThrow", "doesNotReject"})
# The resolved bindings whose calls are assertion APIs. A lookalike, a
# shadowed name or a written member is not: recording it would let the
# stand-in pair with the oracle it replaced (#196 190.5).
_CANDIDATE_ASSERT_KINDS = frozenset({"node", "node_method", "chai_assert", "chai_assert_method",
                                     "chai_should_method", "ava_method", "tap_method"})
_CANDIDATE_EXPECT_KINDS = frozenset({"expect", "chai_expect", "jest_expect"})
# node:assert methods the scan does not read. The ones it reads (`ok`,
# `equal`, `strictEqual`, `deepEqual`, `deepStrictEqual` and `assert()`
# itself) stay unrepresented when their arguments are malformed, as before,
# and a name node:assert does not export is no assertion at all.
_CANDIDATE_NODE_METHODS = frozenset({
    "notEqual", "notStrictEqual", "notDeepEqual", "notDeepStrictEqual", "partialDeepStrictEqual",
    "throws", "doesNotThrow", "rejects", "doesNotReject", "ifError", "match", "doesNotMatch",
    "fail", "snapshot", "fileSnapshot",
})
# A Jest-style expect chain: `.not`, `.resolves`, `.rejects` or a `toX` matcher.
_JEST_CHAIN_WORDS = frozenset({"not", "resolves", "rejects"})
_JEST_MATCHER_WORD = re.compile(r"to[A-Z]")
# Members of `expect` that build a value or configure the runner rather than
# assert: asymmetric matchers and registration.
_EXPECT_UTILITIES = frozenset({
    "any", "anything", "objectContaining", "arrayContaining", "stringContaining",
    "stringMatching", "closeTo", "not", "extend", "addSnapshotSerializer",
    "addEqualityTesters", "getState", "setState",
})


def _candidate_declares(text: str, code: bytearray, masked: str, start: int, opening: int, end: int) -> bool:
    """A bare `name(...)` that declares a function or a method rather than calling one."""
    previous = start - 1
    while previous >= 0 and masked[previous].isspace():
        previous -= 1
    if previous >= 0 and masked[previous] == "*":
        previous -= 1
        while previous >= 0 and masked[previous].isspace():
            previous -= 1
    if re.search(r"\bfunction$", masked[:previous + 1]):
        return True
    call = _call_argument_spans(text, code, opening, end)
    if call is None:
        return False
    following = call[1]
    while following < end and masked[following].isspace():
        following += 1
    if following >= end:
        return False
    if masked[following] == ":" and not _conditional_arm(text, code, start):
        return True
    return masked[following] == "{" and "\n" not in text[call[1]:following]


def _candidate_assertions(text: str, code: bytearray, bindings: Bindings, start: int, end: int,
                          covered: list[tuple[int, int]], owned: Callable[[int], bool]) -> list[Assertion]:
    """Assertion calls the scans do not represent, recorded with no strength (#196 190.5).

    `assert.throws(fn)`, `expect(spy).toHaveBeenCalledWith(1)` and
    `expect(value).to.have.keys("a")` are assertions whose predicate
    checkwash does not read. SPEC §3 records such a form with strength null,
    as Python records `assertRaises`: its removal is ASSERT_REMOVED, and a
    rewrite is not judged. The throw family is `raises`; the rest, and a
    negated throw check, are `unknown`. A call inside another assertion's
    arguments (`expect.any(Number)`), a bare `expect(value)` with no matcher,
    and an `expect` member that builds a value are not assertions.
    `covered` holds the spans already represented; recorded calls join it.
    `owned` says whether a position is this unit's own, not a nested
    function's.
    """
    masked = bindings.masked
    recorded: list[Assertion] = []
    for match in _CANDIDATE_CALL.finditer(masked, start, end):
        position = match.start()
        if (not code[position] or not owned(position)
                or any(first <= position < last for first, last in covered)):
            continue
        previous = position - 1
        while previous >= 0 and (not code[previous] or text[previous].isspace()):
            previous -= 1
        if previous >= 0 and text[previous] in ".#":
            continue
        if follows_new(masked, previous):
            continue
        callee = text[position:match.end() - 1].strip()
        spelling = _CANDIDATE_INDEX.sub(lambda index: "." + index.group("word"), callee)
        path = tuple(re.split(r"\s*(?:\?\.|\.)\s*", spelling.rstrip("?. \t\n")))
        if bindings._written(path, position):
            continue
        value = bindings.callee(".".join(path), position)
        kind = value.kind
        bare = len(path) == 1
        expect_call = bare and kind in _CANDIDATE_EXPECT_KINDS
        expect_member = not bare and bindings.callee(path[0], position).kind in _CANDIDATE_EXPECT_KINDS
        if not (kind in _CANDIDATE_ASSERT_KINDS or expect_call or expect_member):
            continue
        opening = match.end() - 1
        if bare and _candidate_declares(text, code, masked, position, opening, end):
            continue
        call = _call_argument_spans(text, code, opening, end)
        if call is None:
            continue
        argument_spans, cursor = call
        words: list[str] = []
        while True:
            step = _CANDIDATE_STEP.match(masked, cursor, end)
            if step is None:
                break
            words.append(step.group("word"))
            cursor = step.end()
            following = cursor
            while following < end and masked[following].isspace():
                following += 1
            if following < end and masked[following] == "(":
                chained = _call_argument_spans(text, code, following, end)
                if chained is None:
                    break
                cursor = chained[1]
        if kind == "node_method" and path[-1] not in _CANDIDATE_NODE_METHODS:
            continue
        if kind == "node" or kind == "chai_assert":
            continue  # `assert(...)` itself is the scan's.
        if kind == "chai_assert_method" and path[-1] in _CHAI_ASSERT:
            continue
        if kind == "chai_should_method" and path[-1] in _SHOULD_METHODS:
            continue
        if kind in _CONTEXT_METHODS and value.method in _CONTEXT_METHODS[kind]:
            continue  # AVA's and tap's assertions the scan reads (#233).
        if expect_call:
            if not words:
                continue  # `expect(value)` alone asserts nothing.
            jest_style = words[0] in _JEST_CHAIN_WORDS or bool(_JEST_MATCHER_WORD.match(words[0]))
            if kind == "jest_expect" and not jest_style:
                continue  # Jest's own expect has no chai chain (#198 Q5).
            if kind == "chai_expect" and any(_JEST_MATCHER_WORD.match(word) for word in words):
                continue  # chai's expect has no Jest matcher.
            if (jest_style and not {"resolves", "rejects"} & set(words)
                    and words[-1] in _MATCHER_STRENGTH):
                continue  # A matcher the scan reads, left out for its arguments.
        if expect_member and path[-1] in _EXPECT_UTILITIES:
            continue
        # A method bound to a name of its own says what it is by its value.
        members = [value.method] if kind in _CONTEXT_METHODS else list(path[1:])
        said = members + words
        negated = any(word in _NEGATING_WORDS for word in said)
        throws = not negated and any(word in _THROW_WORDS for word in said)
        first = argument_spans[0] if argument_spans else None
        subject = text[first[0]:first[1]].strip() if first is not None else ""
        recorded.append(Assertion(
            id="",
            form="raises" if throws else "unknown",
            strength=None,
            text=text[position:cursor],
            span=(position, cursor),
            left=subject or None,
        ))
        covered.append((position, cursor))
    return recorded


def _decoded(data: bytes) -> str:
    return data.decode("utf-8-sig", errors="replace").replace("\r\n", "\n").replace("\r", "\n")


def file_bindings(data: bytes) -> Bindings:
    """The bindings `parse_javascript` reads a file with, for a pass that resolves names (#226)."""
    text = _decoded(data)
    return Bindings(text, _code_positions(text), _code_positions(text, keep_strings=True))


def parse_javascript(data: bytes, innermost_focus: Callable[[], bool] | None = None) -> ParsedFile:
    """One JS/TS test file's units.

    `innermost_focus` says whether the file's runner is proven to run only
    the innermost focus (#196 187.2). It is asked only when the file holds
    focus; without it, Jest's rule decides.
    """
    text = _decoded(data)
    code = _code_positions(text)
    bindings = Bindings(text, code, _code_positions(text, keep_strings=True))
    declarations = _declarations(text, code, bindings)
    scanned = [d for d in declarations if d.unit and not d.table and d.name is not None]
    test_body_starts = {d.callback[0] for d in scanned if d.callback is not None}
    # What nested units inherit, the file's first focus, and the units that
    # focus stops running.
    ancestors = [d for d in declarations
                 if d.callback is not None and (d.markers or d.focus is not None)]
    focus = next((d.focus for d in declarations if d.focus is not None), None)
    stops: dict[int, Marker] = {}
    if focus is not None:
        innermost = innermost_focus is not None and innermost_focus()
        stops = _focus_stops(text, code, bindings, declarations, innermost)
    inline_body_starts: set[int] = set()
    openings = {call.end() - 1 for call in CALL.finditer(bindings.masked)
                if call.group("callee") not in {"if", "for", "while", "switch", "catch", "with"}}
    # A member call passes its callbacks as directly whatever its receiver:
    # `[[1, 78.75]].forEach(...)`, `Object.entries(cases).forEach(...)`,
    # `(cases).forEach(...)` and `cases?.forEach(...)` as `cases.forEach(...)`
    # (#294). `CALL` reads only a dotted name.
    openings.update(start for index, (token, start, _end) in enumerate(bindings.tokens)
                    if token == "(" and bindings.token(index - 2) in {".", "?."}
                    and re.fullmatch(NAME, bindings.token(index - 1)))
    for opening in sorted(openings):
        arguments = _call_argument_spans(text, code, opening, len(text))
        if arguments is None:
            continue
        for argument in arguments[0]:
            callback = _callback_body(bindings, argument)
            if callback is not None and callback[0] not in test_body_starts:
                inline_body_starts.add(callback[0])
    # The file's nested functions, read once and kept by each unit whose body
    # holds them (#235). Child test callbacks are scanned as their own units;
    # declared helpers remain visible coverage gaps. Direct inline call
    # arguments retain the established lexical callback coverage (such as
    # forEach); this does not prove an arbitrary callee invokes them.
    functions = sorted((scope.start, scope.end) for scope in bindings.scopes
                       if scope.function and scope.start not in inline_body_starts)
    # Default parameter expressions belong to invocation of the nested
    # function too, even though they precede its body scope.
    parameter_positions = {bindings.tokens[index][1] for index in bindings.parameter_tokens}
    # A TypeScript return annotation can keep the binding scanner from
    # recognizing an arrow's parameter scope. Its body is still a nested
    # function, and cannot donate assertions to the surrounding test.
    arrows: list[tuple[int, int]] = []
    for index, (token, _, _) in enumerate(bindings.tokens):
        if token != "=>" or index + 1 >= len(bindings.tokens):
            continue
        body_index = index + 1
        if bindings.token(body_index) == "{" and body_index in bindings.pairs:
            first = bindings.tokens[body_index][2]
            last = bindings.tokens[bindings.pairs[body_index]][1]
        else:
            first = bindings.tokens[body_index][1]
            last_index = bindings._expression_end(body_index)
            last = bindings.tokens[last_index][1] if last_index < len(bindings.tokens) else len(text)
        inline_body = first in inline_body_starts
        parameter_end = index - 1
        if bindings.token(parameter_end) != ")":
            # The same simple return annotation supported on test
            # callbacks may separate an arrow from its parameter list.
            while parameter_end >= 0 and (
                re.fullmatch(NAME, bindings.token(parameter_end))
                or bindings.token(parameter_end) in {"<", ">", "[", "]", ",", "|", "."}
            ):
                parameter_end -= 1
            if bindings.token(parameter_end) == ":":
                parameter_end -= 1
        if bindings.token(parameter_end) == ")" and parameter_end in bindings.pairs:
            parameter_start = bindings.pairs[parameter_end]
            parameter_positions.update(bindings.tokens[cursor][1]
                                       for cursor in range(parameter_start + 1, parameter_end))
            first = bindings.tokens[parameter_start][1]
        if not inline_body:
            arrows.append((first, last))
    arrows.sort()
    function_starts = [first for first, _last in functions]
    arrow_starts = [first for first, _last in arrows]
    units: list[ParsedUnit] = []
    for declaration in scanned:
        name = declaration.name
        callback = declaration.callback
        if callback is None:
            if declaration.call is None:
                continue
            start = end = declaration.call[1]
            unit_end = declaration.call[1]
        else:
            start, end, unit_end, _ = callback
        body = text[declaration.start:unit_end]
        # Assertions inside another function are not this callback's direct
        # assertions: the file's nested functions inside this callback's body.
        nested = (functions[bisect_right(function_starts, start):bisect_left(function_starts, end)]
                  + arrows[bisect_right(arrow_starts, start):bisect_left(arrow_starts, end)])

        def owned(position: int) -> bool:
            return (position not in parameter_positions
                    and not any(first <= position < last for first, last in nested))

        assertions: list[Assertion] = []
        for candidate in CALL.finditer(bindings.masked, start, end):
            if not owned(candidate.start()):
                continue
            receiver = bindings.callee(candidate.group("callee"), candidate.start()).kind
            if receiver not in {"expect", "chai_expect", "jest_expect"}:
                continue
            subject_call = _call_arguments(text, code, candidate.end() - 1, end)
            # Vitest and chai accept an optional diagnostic message after actual.
            if (subject_call is None or not 1 <= len(subject_call[0]) <= 2
                    or _EMPTY_ARGUMENT.fullmatch(subject_call[0][0])):
                continue
            subject_arguments, subject_end = subject_call
            undefined_global = bindings.is_global(("undefined",), candidate.start())
            # chai's own expect has no Jest matchers. Vitest's and an unimported
            # global expect may use either style. Jest's own expect, imported
            # from @jest/globals, has no `.to`: a chain there stays a coverage
            # gap (#198 Q5).
            expect = (_EXPECT_RE.match(bindings.masked, subject_end, end)
                      if receiver in {"expect", "jest_expect"} else None)
            if expect is None:
                chain = (_chai_chain(text, code, bindings.masked, subject_end, end)
                         if receiver != "jest_expect" else None)
                if chain is not None:
                    meaning, positive, operands, span_end, properties = chain
                    subject = _retargeted(subject_arguments[0], properties)
                    span = (candidate.start(), span_end)
                    chai_call = subject and _chai_assertion(meaning, [subject, *operands],
                                                            text[span[0]:span[1]], span, positive,
                                                            undefined_global=undefined_global,
                                                            bindings=bindings)
                    if chai_call is not None:
                        assertions.append(chai_call)
                continue
            matcher_call = _call_arguments(text, code, expect.end() - 1, end)
            if matcher_call is None:
                continue
            arguments, span_end = matcher_call
            matcher = expect.group("matcher")
            form, strength = _MATCHER_STRENGTH[matcher]
            if form in {"compare_eq", "compare_ord", "approx", "membership", "pattern"} and (
                not arguments or _EMPTY_ARGUMENT.fullmatch(arguments[0])
            ):
                continue
            if matcher == "toBe":
                key, asserts = _equality_key(arguments[0], strict=True, undefined_global=undefined_global), True
            else:
                key, asserts = _MATCHER_PREDICATE.get(matcher, (None, True))
            asymmetric = None
            if matcher in {"toEqual", "toStrictEqual"}:
                asymmetric = _asymmetric_matcher(text, code, expect.end() - 1, end, candidate.group("callee"))
            if asymmetric is not None:
                # `toEqual(expect.anything())` states no expected value: it
                # is the predicate its asymmetric matcher states (#198 Q3).
                form, strength, key, asserts = _ASYMMETRIC[asymmetric]
            subject = subject_arguments[0]
            span_start = candidate.start()
            negated = bool(expect.group("not"))
            assertion = Assertion(
                id=f"a{len(assertions)}",
                form=form,
                strength=strength,
                text=text[span_start:span_end],
                span=(span_start, span_end),
                left=subject,
                positive=not negated,
            )
            if form in {"compare_eq", "compare_ord", "approx"}:
                # The expected value, or an ordering matcher's bound (#198 Q2).
                populate_expectation(assertion, arguments[0], _number_global(bindings, span_start))
                assertion.operand_source = operand_text(arguments[0])
                assertion.unevaluated_expected = _unevaluated_call(assertion, bindings, span_start)
            if form == "approx" and assertion.positive:
                populate_precision(assertion, arguments[1] if len(arguments) > 1 else None)
            if assertion.positive and (
                matcher == "toBeTruthy" or matcher in _ORDER_MATCHERS
                or (form == "compare_eq" and assertion.right_value == "True")
            ):
                # The spans behind the argument texts read above.
                subject_spans = _call_argument_spans(text, code, candidate.end() - 1, end)
                matcher_spans = _call_argument_spans(text, code, expect.end() - 1, end)
                operator = _ORDER_MATCHERS.get(matcher)
                if subject_spans and subject_spans[0] and matcher_spans is not None:
                    bound = matcher_spans[0][0] if operator and matcher_spans[0] else None
                    hand = _record_tolerance(assertion, text, code, bindings, subject_spans[0][0],
                                             operator, bound)
                    if hand is not None and operator is not None:
                        # A bound read as a hand-rolled tolerance is tolerance
                        # evidence only, never an expected value (198.Q2): the
                        # expected value is the centre, if any (189.2).
                        if hand.operand is None:
                            assertion.operand_source = None
                    elif hand is not None:
                        # The truthy spelling states the bound key (189.3).
                        key, asserts = hand.key, True
                        assertion.operand_source = hand.operand
            _state_predicate(assertion, key, asserts, negated)
            assertions.append(assertion)
        assertions.extend(assertion for assertion in _node_assertions(text, code, start, end, bindings)
                          if owned(assertion.span[0]))
        assertions.extend(_should_assertions(text, code, bindings, start, end, owned))
        assertions.extend(_context_assertions(text, code, bindings, start, end, owned))
        covered = [assertion.span for assertion in assertions]
        assertions.extend(_candidate_assertions(text, code, bindings, start, end, covered, owned))
        assertions.sort(key=lambda assertion: assertion.span)
        for assertion_index, assertion in enumerate(assertions):
            assertion.id = f"a{assertion_index}"
        imperative = _imperative_skips(text, code, bindings, callback, start, end, owned)
        markers = _unit_markers(declaration, ancestors, stops.get(id(declaration)), imperative)
        body_hash = hashlib.sha256(normalize_text(body).encode("utf-8")).hexdigest()
        side = UnitSide(
            span=(declaration.start, unit_end),
            assertions=assertions,
            markers=markers,
            body_hash=body_hash,
        )
        units.append(ParsedUnit(qualname=name, span=(declaration.start, unit_end), side=side))
    # A declaration counts with an inline callback, which a runner collects
    # as a test or a suite; a bare `.test(value)` call is a method.
    declares_tests = bool(units) or any(
        (d.callback or _test_body(text, code, bindings, d)) is not None for d in declarations)
    handlers = swallowing_handlers(bindings, [a for unit in units for a in unit.side.assertions])
    return ParsedFile(parse_ok=True, units=units, focus=focus, declares_tests=declares_tests,
                      swallowing_handlers=handlers)

"""Bounded Jest/Vitest/node:test oracle scan. Not a JS parser.

A matcher swap `toBe` -> `toBeTruthy` is the same cheat as `==` -> `is not
None`. This frontend only looks at `test`/`it` units, `expect().matcher()`
and direct Node assertion calls so existing detectors can see a strength
drop, and at the liveness every `describe`/`test` declaration gives the units
inside it, so TEST_DISABLED can see one stop running. Production `.js`/`.ts`
is not parsed and still cannot grant a false
sense of coverage. Static imports and lexical shadows are resolved within the
bounded binding model; dynamic JavaScript execution remains outside the scan.
"""

from __future__ import annotations

import hashlib
import re
from bisect import bisect_left
from collections.abc import Callable
from dataclasses import dataclass

from checkwash.frontends.javascript.bindings import Bindings, CALL, NAME
from checkwash.frontends.javascript.literals import populate_expectation, populate_precision
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
# passes. The neutral ones are read through to the effect chained after them.
_MODIFIERS = {
    "skip": "skip", "todo": "skip", "only": "only", "fails": "fails", "failing": "fails",
    "concurrent": "", "sequential": "", "shuffle": "",
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
    starts = [token[1] for token in bindings.tokens]
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
        starts = [token[1] for token in bindings.tokens]
        cursor = bisect_left(starts, declaration.name_end)
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
    starts = [token[1] for token in bindings.tokens]
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


def _unit_markers(declaration: _Declaration, ancestors: list[_Declaration],
                  focus: Marker | None, imperative: list[Marker]) -> list[Marker]:
    """One liveness definition for every declaration level (issues #176, #178).

    A unit runs unless it, or a declaration whose callback encloses it, is
    skipped, conditionally skipped or inverted, or unless the file is focused
    and neither it nor an enclosing declaration is. Each effect is a state,
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
    if focus is not None and all(d.focus is None for d in chain):
        markers.append(Marker(name="test.unfocused", text=focus.text, span=focus.span))
    return markers


def _node_assertions(text: str, code: bytearray, start: int, end: int,
                     bindings: Bindings | None = None) -> list[Assertion]:
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
        if value.kind not in {"node", "node_method"}:
            continue
        method = value.method or None
        if method is not None and method not in _ASSERT_STRENGTH:
            continue
        if re.search(r"\bnew$", bindings.masked[:previous + 1]):
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
        call = _call_arguments(text, code, match.end() - 1, end)
        if call is None:
            continue
        arguments, span_end = call
        following = span_end
        while following < end and (not code[following] or text[following].isspace()):
            following += 1
        if method is None and following < end:
            if text[following] == ":" and not _conditional_arm(text, code, match.start()):
                continue  # A TypeScript method's return annotation.
            if text[following] == "{" and "\n" not in text[span_end:following]:
                continue  # A method signature, not a call followed by an ASI block.
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
        # Legacy equal/deepEqual coerce values; the bounded bindings do not
        # yet preserve strict-import mode, so only explicit strict methods
        # can supply scalar expectation identity without guessing coercion.
        if method in {"strictEqual", "deepStrictEqual"}:
            populate_expectation(assertion, arguments[1])
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


def parse_javascript(data: bytes) -> ParsedFile:
    text = data.decode("utf-8-sig", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    code = _code_positions(text)
    bindings = Bindings(text, code, _code_positions(text, keep_strings=True))
    declarations = _declarations(text, code, bindings)
    scanned = [d for d in declarations if d.unit and not d.table and d.name is not None]
    test_body_starts = {d.callback[0] for d in scanned if d.callback is not None}
    # What nested units inherit, and the file's first focus: once anything
    # is focused, every unit outside a focused declaration stops running.
    ancestors = [d for d in declarations
                 if d.callback is not None and (d.markers or d.focus is not None)]
    focus = next((d.focus for d in declarations if d.focus is not None), None)
    inline_body_starts: set[int] = set()
    for call in CALL.finditer(bindings.masked):
        if call.group("callee") in {"if", "for", "while", "switch", "catch", "with"}:
            continue
        arguments = _call_argument_spans(text, code, call.end() - 1, len(text))
        if arguments is None:
            continue
        for argument in arguments[0]:
            callback = _callback_body(bindings, argument)
            if callback is not None and callback[0] not in test_body_starts:
                inline_body_starts.add(callback[0])
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
        # assertions. Child test callbacks are scanned as their own units;
        # declared helpers remain visible coverage gaps. Direct inline call
        # arguments retain the established lexical callback coverage (such as
        # forEach); this does not prove an arbitrary callee invokes them.
        nested = [(scope.start, scope.end) for scope in bindings.scopes
                  if scope.function and start < scope.start < end
                  and scope.start not in inline_body_starts]
        # Default parameter expressions belong to invocation of the nested
        # function too, even though they precede its body scope.
        parameter_positions = {bindings.tokens[index][1] for index in bindings.parameter_tokens}
        # A TypeScript return annotation can keep the binding scanner from
        # recognizing an arrow's parameter scope. Its body is still a nested
        # function, and cannot donate assertions to the surrounding test.
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
            if inline_body:
                continue
            if start < first < end:
                nested.append((first, last))

        def owned(position: int) -> bool:
            return (position not in parameter_positions
                    and not any(first <= position < last for first, last in nested))

        assertions: list[Assertion] = []
        for candidate in CALL.finditer(bindings.masked, start, end):
            if not owned(candidate.start()):
                continue
            if bindings.callee(candidate.group("callee"), candidate.start()).kind != "expect":
                continue
            subject_call = _call_arguments(text, code, candidate.end() - 1, end)
            # Vitest accepts an optional diagnostic message after actual.
            if (subject_call is None or not 1 <= len(subject_call[0]) <= 2
                    or _EMPTY_ARGUMENT.fullmatch(subject_call[0][0])):
                continue
            subject_arguments, subject_end = subject_call
            expect = _EXPECT_RE.match(bindings.masked, subject_end, end)
            if expect is None:
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
            subject = subject_arguments[0]
            span_start = candidate.start()
            assertion = Assertion(
                id=f"a{len(assertions)}",
                form=form,
                strength=strength,
                text=text[span_start:span_end],
                span=(span_start, span_end),
                left=subject,
                positive=not bool(expect.group("not")),
            )
            if form in {"compare_eq", "approx"}:
                populate_expectation(assertion, arguments[0])
            if form == "approx" and assertion.positive:
                populate_precision(assertion, arguments[1] if len(arguments) > 1 else None)
            assertions.append(assertion)
        assertions.extend(assertion for assertion in _node_assertions(text, code, start, end, bindings)
                          if owned(assertion.span[0]))
        assertions.sort(key=lambda assertion: assertion.span)
        for assertion_index, assertion in enumerate(assertions):
            assertion.id = f"a{assertion_index}"
        imperative = _imperative_skips(text, code, bindings, callback, start, end, owned)
        markers = _unit_markers(declaration, ancestors, focus, imperative)
        body_hash = hashlib.sha256(normalize_text(body).encode("utf-8")).hexdigest()
        side = UnitSide(
            span=(declaration.start, unit_end),
            assertions=assertions,
            markers=markers,
            body_hash=body_hash,
        )
        units.append(ParsedUnit(qualname=name, span=(declaration.start, unit_end), side=side))
    return ParsedFile(parse_ok=True, units=units)

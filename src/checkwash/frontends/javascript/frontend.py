"""Bounded Jest/Vitest/node:test oracle scan. Not a JS parser.

A matcher swap `toBe` -> `toBeTruthy` is the same cheat as `==` -> `is not
None`. This frontend only looks at `test`/`it` units, `expect().matcher()`
and direct Node assertion calls so existing detectors can see a strength
drop. Production `.js`/`.ts` is not parsed and still cannot grant a false
sense of coverage. Static imports and lexical shadows are resolved within the
bounded binding model; dynamic JavaScript execution remains outside the scan.
"""

from __future__ import annotations

import hashlib
import re
from bisect import bisect_left

from checkwash.frontends.javascript.bindings import Bindings, CALL, NAME
from checkwash.frontends.javascript.literals import populate_expectation, populate_precision
from checkwash.frontends.python.frontend import ParsedFile, ParsedUnit
from checkwash.ir import strength as S
from checkwash.ir.model import Assertion, Marker, UnitSide, normalize_text

# Word boundary before every declaration word: `split("\n")` contains `it`
# and `exit(` contains `xit`, so an unanchored match minted a test unit whose
# name was the following string literal (issue #156 — a diff that touched no
# assertion reported the pseudo-unit `"\n"` as a removed test).
_TEST_RE = re.compile(
    r"""(?<![\w$])(?:(?P<skip>test\.skip|it\.skip|test\.todo|it\.todo|xtest|xit)"""
    r"""|(?P<kind>test|it))"""
    r"""\s*\(\s*(?P<q>['"`])(?P<name>(?:\\.|(?!(?P=q)).)*)(?P=q)""",
    re.MULTILINE,
)
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


def _test_body(text: str, code: bytearray, bindings: Bindings,
               match: re.Match[str]) -> tuple[int, int, int] | None:
    opening = text.index("(", match.start(), match.end())
    call = _call_argument_spans(text, code, opening, len(text))
    if call is None:
        # Recover only an inline block callback after the literal test name.
        # The normal argument parser deliberately rejects malformed inner
        # calls; those must not hide a later valid assertion in the same body.
        starts = [token[1] for token in bindings.tokens]
        cursor = bisect_left(starts, match.end())
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
        body = _callback_body(bindings, (bindings.tokens[cursor][1], len(text)), recover=True)
        if body is not None:
            # A malformed call cannot supply a trustworthy final ')'. The
            # recovered closing brace is the upper bound of this test unit.
            return body[0], body[1], body[1] + 1
        return None
    arguments, call_end = call
    # Jest/Vitest callback is second; Node also permits an options object.
    # A third timeout/options argument is not another callback.
    for position in (1, 2):
        if position >= len(arguments):
            continue
        body = _callback_body(bindings, arguments[position])
        if body is not None:
            return body[0], body[1], call_end
    return None


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
    matches = [m for m in _TEST_RE.finditer(text) if code[m.start()]]
    callbacks = [_test_body(text, code, bindings, match) for match in matches]
    test_body_starts = {callback[0] for callback in callbacks if callback is not None}
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
    for match, callback in zip(matches, callbacks):
        name = match.group("name")
        if callback is None:
            call = _call_argument_spans(text, code, text.index("(", match.start(), match.end()), len(text))
            if call is None:
                continue
            start = end = call[1]
            unit_end = call[1]
        else:
            start, end, unit_end = callback
        body = text[match.start():unit_end]
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
        markers: list[Marker] = []
        if match.group("skip"):
            markers.append(
                Marker(
                    name="test.skip",
                    text=match.group("skip"),
                    span=(match.start(), match.end()),
                )
            )
        body_hash = hashlib.sha256(normalize_text(body).encode("utf-8")).hexdigest()
        side = UnitSide(
            span=(match.start(), unit_end),
            assertions=assertions,
            markers=markers,
            body_hash=body_hash,
        )
        units.append(ParsedUnit(qualname=name, span=(match.start(), unit_end), side=side))
    return ParsedFile(parse_ok=True, units=units)

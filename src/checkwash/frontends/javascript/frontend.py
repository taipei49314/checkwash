"""Bounded Jest/Vitest/node:test oracle scan. Not a JS parser.

A matcher swap `toBe` -> `toBeTruthy` is the same cheat as `==` -> `is not
None`. This frontend only looks at `test`/`it` units and `expect().matcher()`
calls so existing detectors can see a strength drop. Production `.js`/`.ts`
is not parsed and still cannot grant a false sense of coverage.
"""

from __future__ import annotations

import hashlib
import re

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
    r"""(?<![\w$])expect\s*\((?P<subject>[^;]{1,200}?)\)\s*\.\s*(?P<not>not\s*\.\s*)?(?P<matcher>"""
    r"""toBe|toEqual|toStrictEqual|toBeCloseTo|toContain|toMatch|"""
    r"""toBeTruthy|toBeFalsy|toBeDefined|toBeUndefined|toBeNull|"""
    r"""toBeGreaterThan|toBeGreaterThanOrEqual|toBeLessThan|toBeLessThanOrEqual"""
    r""")\s*\(""",
    re.MULTILINE,
)

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

_JS_TEST_SUFFIXES = (
    ".test.js",
    ".test.jsx",
    ".test.ts",
    ".test.tsx",
    ".test.mjs",
    ".test.cjs",
    ".spec.js",
    ".spec.jsx",
    ".spec.ts",
    ".spec.tsx",
    ".spec.mjs",
    ".spec.cjs",
)


def is_js_test_path(path: str) -> bool:
    lower = path.replace("\\", "/").lower()
    return any(lower.endswith(suffix) for suffix in _JS_TEST_SUFFIXES)


def _code_positions(text: str) -> bytearray:
    """Exclude comments and literal contents from declaration/matcher starts.

    Keep original offsets and quoted test names for the bounded call scan.
    Template literals are opaque, including their interpolations; this is not
    an attempt to parse arbitrary JavaScript expressions.
    """
    code = bytearray(b"\x01") * len(text)
    i = 0
    operand = True
    previous = ""
    parens: list[bool] = []
    while i < len(text):
        start = i
        if text.startswith("//", i):
            end = text.find("\n", i + 2)
            i = len(text) if end < 0 else end
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = len(text) if end < 0 else end + 2
        elif text[i] in "\"'`":
            quote = text[i]
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
            elif char == "]" or char.isdigit():
                operand = False
            elif not char.isspace():
                operand = char != "."
            if not char.isspace():
                previous = char
            i += 1
            continue
        code[start:i] = b"\x00" * (i - start)
    return code


def parse_javascript(data: bytes) -> ParsedFile:
    text = data.decode("utf-8-sig", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    code = _code_positions(text)
    matches = [m for m in _TEST_RE.finditer(text) if code[m.start()]]
    starts = [m.start() for m in matches]
    units: list[ParsedUnit] = []
    for index, match in enumerate(matches):
        name = match.group("name")
        start = match.start()
        end = starts[index + 1] if index + 1 < len(starts) else len(text)
        body = text[start:end]
        assertions: list[Assertion] = []
        for expect in _EXPECT_RE.finditer(body):
            if not code[start + expect.start()]:
                continue
            matcher = expect.group("matcher")
            form, strength = _MATCHER_STRENGTH[matcher]
            subject = " ".join((expect.group("subject") or "").split())
            span_start = start + expect.start()
            span_end = start + expect.end()
            assertions.append(
                Assertion(
                    id=f"a{len(assertions)}",
                    form=form,
                    strength=strength,
                    text=expect.group(0),
                    span=(span_start, span_end),
                    left=subject,
                    positive=not bool(expect.group("not")),
                )
            )
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
            span=(start, end),
            assertions=assertions,
            markers=markers,
            body_hash=body_hash,
        )
        units.append(ParsedUnit(qualname=name, span=(start, end), side=side))
    return ParsedFile(parse_ok=True, units=units)

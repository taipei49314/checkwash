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

_TEST_RE = re.compile(
    r"""(?P<skip>test\.skip|it\.skip|test\.todo|it\.todo|xtest|xit)|(?P<kind>test|it)"""
    r"""\s*\(\s*(?P<q>['"`])(?P<name>(?:\\.|(?!(?P=q)).)*)(?P=q)""",
    re.MULTILINE,
)
_EXPECT_RE = re.compile(
    r"""expect\s*\((?P<subject>[^;]{1,200}?)\)\s*\.\s*(?P<not>not\s*\.\s*)?(?P<matcher>"""
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


def parse_javascript(data: bytes) -> ParsedFile:
    text = data.decode("utf-8-sig", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    starts = [m.start() for m in _TEST_RE.finditer(text)]
    units: list[ParsedUnit] = []
    for index, match in enumerate(_TEST_RE.finditer(text)):
        name = match.group("name") or f"anonymous_{index}"
        start = match.start()
        end = starts[index + 1] if index + 1 < len(starts) else len(text)
        body = text[start:end]
        assertions: list[Assertion] = []
        for expect in _EXPECT_RE.finditer(body):
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

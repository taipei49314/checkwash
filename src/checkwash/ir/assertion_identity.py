"""Keep established finding identities while assertion evidence gets richer.

The original JS matcher scan stored only the prefix through the matcher's
opening parenthesis. Existing finding rules hashed that text. Keep their keys
for assertions the old scan understood, without truncating the source evidence
or assigning an old identity to syntax whose subject used to be misparsed.
"""

from __future__ import annotations

import re

from checkwash.ir.model import Assertion, normalize_text


_JS_SUFFIXES = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts")
_LEGACY_NAME = r"[A-Za-z_$][\w$]*"
# Frozen v0.4.1 matcher prefix, independent of future frontend coverage.
_LEGACY_EXPECT_PREFIX = re.compile(
    r"(?<![\w$.#])(?P<callee>" + _LEGACY_NAME + r"(?:\s*\.\s*" + _LEGACY_NAME + r")*)"
    r"""\s*\((?P<subject>[^;]{1,200}?)\)\s*\.\s*(?P<not>not\s*\.\s*)?(?P<matcher>"""
    r"""toBe|toEqual|toStrictEqual|toBeCloseTo|toContain|toMatch|"""
    r"""toBeTruthy|toBeFalsy|toBeDefined|toBeUndefined|toBeNull|"""
    r"""toBeGreaterThan|toBeGreaterThanOrEqual|toBeLessThan|toBeLessThanOrEqual"""
    r""")\s*\(""",
    re.MULTILINE,
)


def fingerprint_text(path: str, assertion: Assertion) -> str:
    """Legacy JS matcher identity, or the assertion's complete source text.

Call only from rules that already fingerprinted assertions before the complete
JS argument scan. New expected-value findings retain their complete identity.
"""
    if not path.lower().endswith(_JS_SUFFIXES):
        return assertion.text
    match = _LEGACY_EXPECT_PREFIX.match(assertion.text)
    if match is None:
        return assertion.text
    # The old frontend collapsed all subject whitespace, including quoted
    # contents. Require its subject to agree with the current representation;
    # a repaired nested call or string is not an unchanged old assertion.
    legacy_subject = " ".join(match.group("subject").split())
    if normalize_text(legacy_subject) != normalize_text(assertion.left or ""):
        return assertion.text
    return match.group(0)

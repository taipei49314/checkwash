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


def _legacy_message_subject(subject: str, actual: str) -> bool:
    """Verify an old two-argument expect prefix ends at the same call.

    Prefix comparison alone is unsafe: the old regex can stop at a nested
    matcher inside the diagnostic expression. Require both arguments to be
    structurally complete. Regexes, templates and slash expressions need the
    JS lexer, so those uncommon diagnostic forms retain complete identities.
    """
    parts: list[str] = []
    stack: list[str] = []
    start = i = 0
    while i < len(subject):
        char = subject[i]
        if char in "\"'":
            quote = char
            i += 1
            while i < len(subject):
                if subject[i] == "\\":
                    i += 2
                elif subject[i] == quote:
                    i += 1
                    break
                else:
                    i += 1
            else:
                return False
            continue
        if char in "/`":
            return False
        if char in "([{":
            stack.append({"(": ")", "[": "]", "{": "}"}[char])
        elif char in ")]}":
            if not stack or stack.pop() != char:
                return False
        elif char == "," and not stack:
            parts.append(subject[start:i])
            start = i + 1
        i += 1
    if stack:
        return False
    parts.append(subject[start:])
    return (
        len(parts) == 2
        and bool(parts[1].strip())
        and normalize_text(" ".join(parts[0].split())) == normalize_text(actual)
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
    if (normalize_text(legacy_subject) != normalize_text(assertion.left or "")
            and not _legacy_message_subject(match.group("subject"), assertion.left or "")):
        return assertion.text
    return match.group(0)

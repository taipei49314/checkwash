"""Complete JS assertion evidence must preserve established finding keys.

The rules with content-bound keys (#421, and TEST_DISABLED since #512) keep
the established key as the legacy pre-image their identity holds, so that is
what is pinned for them.
"""

import datetime

import pytest

import checkwash.findings as findings_module
from checkwash.allowlist import AllowEntry
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze
from checkwash.findings import assertion_key
from checkwash.ir.assertion_identity import fingerprint_text
from checkwash.ir.model import Assertion


_PATH = "tests/identity.test.ts"


def _analyze(before, after):
    return analyze(
        [FileChange(_PATH, "modified", before.encode(), after.encode())],
        Config(), Contract(), [], datetime.date(2026, 9, 23),
    )


def _source(body):
    return 'test("sample", () => { ' + body + " });\n"


def _identities(monkeypatch):
    """Every assertion-level identity computed while the test runs (#421)."""
    seen = []
    real = findings_module.assertion_identity

    def record(*args, **kwargs):
        seen.append(real(*args, **kwargs))
        return seen[-1]

    monkeypatch.setattr(findings_module, "assertion_identity", record)
    return seen


def _refines(finding, identities, rule, identity):
    # The content-bound key is computed from an identity whose legacy
    # pre-image is the old normalized evidence. Inputs below spell it
    # explicitly, independently of the new helper or either version's parser.
    assert finding.fingerprint.startswith(f"{rule}/{_PATH}/sample/v2:")
    legacy = f"{rule}/{_PATH}/sample/{identity}"
    assert finding.fingerprint in {assertion_key(i) for i in identities if i["legacy"] == legacy}


@pytest.mark.parametrize("rule,before,after,legacy_identity", [
    ("ASSERT_REMOVED", "expect(subject()).toBe(42)", "observe()", "expect(subject()).toBe("),
    ("ASSERT_WEAKENED", "expect(subject()).toBe(42)", "expect(subject()).toBeTruthy()",
     "expect(subject()).toBe("),
    ("ASSERT_WEAKENED", "expect(subject()).toBe(42)", "expect(subject()).not.toBe(42)",
     "expect(subject()).toBe("),
    ("ASSERT_SUBSTITUTED", "expect(subject()).toBe(42)", "expect(other()).toBe(0)",
     "expect(subject()).toBe("),
    ("SUBJECT_NORMALIZED", "expect(subject()).toBe(42)", "expect(clean(subject())).toBe(42)",
     "expect(subject()).toBe("),
    ("SUBJECT_INPUT_CHANGED", "expect(subject(1)).toBe(42)", "expect(subject(2)).toBe(42)",
     "expect(subject(1)).toBe("),
])
def test_legacy_rules_keep_their_key_and_gain_complete_evidence(rule, before, after, legacy_identity,
                                                               monkeypatch):
    identities = _identities(monkeypatch)
    _ir, findings, _verdict = _analyze(_source(before + ";"), _source(after + ";"))
    finding, = [finding for finding in findings if finding.rule == rule]
    _refines(finding, identities, rule, legacy_identity)
    assert finding.before.text == before
    if finding.after is not None:
        assert finding.after.text == after


def test_removed_unit_joins_legacy_keys_but_reports_complete_assertions(monkeypatch):
    # TEST_DISABLED's key is content-bound since #512: its identity holds the
    # joined legacy identities as its pre-image.
    identities = _identities(monkeypatch)
    _ir, findings, _verdict = _analyze(
        _source("expect(first()).toBe(1); expect(second()).toEqual(2);"),
        "// the test was removed\n",
    )
    finding, = [finding for finding in findings if finding.rule == "TEST_DISABLED"]
    assert finding.shape == "unit_removed"
    _refines(finding, identities, "TEST_DISABLED", "expect(first()).toBe(expect(second()).toEqual(")
    assert finding.before.text == "expect(first()).toBe(1)\nexpect(second()).toEqual(2)"


def test_new_expected_value_rule_uses_the_complete_before_assertion(monkeypatch):
    identities = _identities(monkeypatch)
    _ir, findings, _verdict = _analyze(
        _source("expect(subject()).toBe(42);"), _source("expect(subject()).toBe(0);"),
    )
    finding, = [finding for finding in findings if finding.rule == "EXPECTED_VALUE_CHANGED"]
    _refines(finding, identities, "EXPECTED_VALUE_CHANGED", "expect(subject()).toBe(42)")
    assert finding.before.text == "expect(subject()).toBe(42)"


def test_an_exemption_for_one_jest_rewrite_does_not_allow_its_sibling():
    """#421's JS sibling (R46): `toBe(1)` and `toBe(2)` on one subject are two approvals.

    Through v0.8.0 a Jest or Vitest assertion was keyed by its text through
    the matcher's `(`, so an exemption recorded for `toBe(42)` -> `toBe(1)`
    also allowed `toBe(42)` -> `toBe(2)` on the same subject in the same
    test. The content-bound key binds the complete after text (#421 Q2 (b)).
    """
    def run(after, allow=()):
        _ir, findings, verdict = analyze(
            [FileChange(_PATH, "modified", _source("expect(subject()).toBe(42);").encode(), after.encode())],
            Config(), Contract(), list(allow), datetime.date(2026, 9, 23),
        )
        hit, = [finding for finding in findings if finding.rule == "EXPECTED_VALUE_CHANGED"]
        return hit, verdict

    reviewed, sibling = _source("expect(subject()).toBe(1);"), _source("expect(subject()).toBe(2);")
    first, _verdict = run(reviewed)
    allow = [AllowEntry(first.fingerprint, rule="EXPECTED_VALUE_CHANGED", reason="reviewed exact change",
                        author="reviewer", created="2026-09-20", expires="2026-12-01")]
    exempt, _verdict = run(reviewed, allow)
    assert exempt.allowlisted and "ALLOWLISTED" in exempt.deescalators
    later, verdict = run(sibling, allow)
    assert later.fingerprint != first.fingerprint
    assert not later.allowlisted and verdict == "block"


def test_node_finding_identity_remains_the_complete_assertion(monkeypatch):
    identities = _identities(monkeypatch)
    _ir, findings, _verdict = _analyze(
        _source("assert.strictEqual(subject(), 42);"), _source("assert.ok(subject());"),
    )
    finding, = [finding for finding in findings if finding.rule == "ASSERT_WEAKENED"]
    _refines(finding, identities, "ASSERT_WEAKENED", "assert.strictEqual(subject(),42)")
    assert finding.before.text == "assert.strictEqual(subject(), 42)"


@pytest.mark.parametrize("path", [
    "tests/identity.test.js", "tests/identity.test.jsx", "tests/identity.test.ts",
    "tests/identity.test.tsx", "tests/identity.test.mjs", "tests/identity.test.cjs",
    "tests/identity.test.mts", "tests/identity.test.cts", "tests/identity.TEST.TS",
])
def test_legacy_identity_applies_to_each_javascript_typescript_extension(path):
    assertion = Assertion("a0", "compare_eq", 90, "check(value).not.toBe(42)", (0, 26), left="value")
    assert fingerprint_text(path, assertion) == "check(value).not.toBe("


@pytest.mark.parametrize("text,subject", [
    ("expect(doThing(expect(value).toBe(1))).toBe(2)", "doThing(expect(value).toBe(1))"),
    ('expect(lookup("semi;colon")).toBe(1)', 'lookup("semi;colon")'),
    ("expect(lookup('two  spaces')).toBe(1)", "lookup('two  spaces')"),
    ("expect(" + "x" * 201 + ").toBe(1)", "x" * 201),
    ("expect(/* explanation */ value).toBe(1)", "value"),
    ("assert.strictEqual(value, 1)", "value"),
])
def test_new_or_previously_misparsed_syntax_keeps_complete_identity(text, subject):
    assertion = Assertion("a0", "compare_eq", 90, text, (0, len(text)), left=subject)
    assert fingerprint_text(_PATH, assertion) == text


def test_python_assertions_never_use_javascript_prefix_compatibility():
    text = "expect(value).toBe(1)"
    assertion = Assertion("a0", "compare_eq", 90, text, (0, len(text)), left="value")
    assert fingerprint_text("tests/test_identity.py", assertion) == text


def test_identity_comparison_ignores_formatting_outside_strings():
    text = "check( subject( 1 ) ).toBe(42)"
    assertion = Assertion("a0", "compare_eq", 90, text, (0, len(text)), left="subject(1)")
    assert fingerprint_text(_PATH, assertion) == "check( subject( 1 ) ).toBe("


def test_vitest_diagnostic_message_keeps_its_established_fingerprint(monkeypatch):
    identities = _identities(monkeypatch)
    imports = 'import { expect } from "vitest";\n'
    before = 'expect(subject(), "explain failure").toBe(42)'
    _ir, findings, _verdict = _analyze(
        imports + _source(before + ";"),
        imports + _source('expect(subject(), "explain failure").toBeTruthy();'),
    )
    finding, = [finding for finding in findings if finding.rule == "ASSERT_WEAKENED"]
    _refines(finding, identities, "ASSERT_WEAKENED", 'expect(subject(),"explain failure").toBe(')
    assert finding.before.text == before


@pytest.mark.parametrize("message", ['"explain failure"', "message", "diagnostic(value, { code: 1 })"])
def test_complete_diagnostic_arguments_keep_the_legacy_prefix(message):
    text = f"expect(subject(), {message}).toBe(42)"
    assertion = Assertion("a0", "compare_eq", 90, text, (0, len(text)), left="subject()")
    assert fingerprint_text(_PATH, assertion) == f"expect(subject(), {message}).toBe("


@pytest.mark.parametrize("text", [
    "expect(subject(), diagnostic(expect(value).toBe(1))).toBe(42)",
    'expect(subject(), "fake).toBe(").toBe(42)',
])
def test_nested_or_quoted_diagnostic_matchers_cannot_claim_a_misparsed_old_prefix(text):
    assertion = Assertion("a0", "compare_eq", 90, text, (0, len(text)), left="subject()")
    assert fingerprint_text(_PATH, assertion) == text

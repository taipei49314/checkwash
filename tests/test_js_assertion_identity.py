"""Complete JS assertion evidence must preserve established finding keys."""

import datetime
import hashlib

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze
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


def _key(rule, identity):
    # Inputs below explicitly spell the old normalized evidence, independently
    # of the new helper or either version's parser.
    digest = hashlib.sha256(f"{rule}/{_PATH}/sample/{identity}".encode()).hexdigest()[:12]
    return f"{rule}/{_PATH}/sample/{digest}"


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
def test_legacy_rules_keep_their_key_and_gain_complete_evidence(rule, before, after, legacy_identity):
    _ir, findings, _verdict = _analyze(_source(before + ";"), _source(after + ";"))
    finding, = [finding for finding in findings if finding.rule == rule]
    assert finding.fingerprint == _key(rule, legacy_identity)
    assert finding.before.text == before
    if finding.after is not None:
        assert finding.after.text == after


def test_removed_unit_joins_legacy_keys_but_reports_complete_assertions():
    _ir, findings, _verdict = _analyze(
        _source("expect(first()).toBe(1); expect(second()).toEqual(2);"),
        "// the test was removed\n",
    )
    finding, = [finding for finding in findings if finding.rule == "TEST_DISABLED"]
    assert finding.shape == "unit_removed"
    assert finding.fingerprint == _key("TEST_DISABLED", "expect(first()).toBe(expect(second()).toEqual(")
    assert finding.before.text == "expect(first()).toBe(1)\nexpect(second()).toEqual(2)"


def test_new_expected_value_rule_uses_the_complete_before_assertion():
    _ir, findings, _verdict = _analyze(
        _source("expect(subject()).toBe(42);"), _source("expect(subject()).toBe(0);"),
    )
    finding, = [finding for finding in findings if finding.rule == "EXPECTED_VALUE_CHANGED"]
    assert finding.fingerprint == _key("EXPECTED_VALUE_CHANGED", "expect(subject()).toBe(42)")
    assert finding.before.text == "expect(subject()).toBe(42)"


def test_node_finding_identity_remains_the_complete_assertion():
    _ir, findings, _verdict = _analyze(
        _source("assert.strictEqual(subject(), 42);"), _source("assert.ok(subject());"),
    )
    finding, = [finding for finding in findings if finding.rule == "ASSERT_WEAKENED"]
    assert finding.fingerprint == _key("ASSERT_WEAKENED", "assert.strictEqual(subject(),42)")
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


def test_vitest_diagnostic_message_keeps_its_established_fingerprint():
    imports = 'import { expect } from "vitest";\n'
    before = 'expect(subject(), "explain failure").toBe(42)'
    _ir, findings, _verdict = _analyze(
        imports + _source(before + ";"),
        imports + _source('expect(subject(), "explain failure").toBeTruthy();'),
    )
    finding, = [finding for finding in findings if finding.rule == "ASSERT_WEAKENED"]
    assert finding.fingerprint == _key("ASSERT_WEAKENED", 'expect(subject(),"explain failure").toBe(')
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

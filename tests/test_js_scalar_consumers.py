"""Scalar spelling cannot invent substitution or hide subject tampering."""

import datetime

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.detectors import assert_substituted, subject_input_changed, subject_normalized
from checkwash.engine import FileChange, analyze
from checkwash.ir.expectation_identity import same_known_js_scalar
from checkwash.ir.model import Assertion, AssertionPair, FileIR, IR, Unit, UnitDelta, UnitSide


_SPELLINGS = [
    ('"ready"', "'ready'"),
    ('"ready"', r'"r\u0065ady"'),
    ("42", "4.2e1"),
]
_CALLS = ["expect({subject}).toBe({expected});", "assert.strictEqual({subject}, {expected});"]


def _analyze(before, after):
    def source(body):
        return ("import assert from 'node:assert/strict';\n"
                "test('contract', () => { " + body + " });\n").encode()

    return analyze(
        [FileChange("tests/scalars.test.ts", "modified", source(before), source(after))],
        Config(), Contract(), [], datetime.date(2026, 9, 23),
    )


@pytest.mark.parametrize("before_expected,after_expected", _SPELLINGS)
@pytest.mark.parametrize("call", _CALLS)
def test_optional_chain_quote_formatting_keeps_the_same_scalar_oracle(call, before_expected, after_expected):
    before = call.format(subject='record?.get("x")', expected=before_expected)
    after = call.format(subject="record?.get('x')", expected=after_expected)
    _ir, findings, verdict = _analyze(before, after)
    assert (findings, verdict) == ([], "pass")


@pytest.mark.parametrize("before_expected,after_expected", _SPELLINGS)
@pytest.mark.parametrize("call", _CALLS)
def test_scalar_spelling_and_a_local_rename_do_not_invent_substitution(call, before_expected, after_expected):
    before = "const result = subject(); " + call.format(subject="result", expected=before_expected)
    after = "const actual = subject(); " + call.format(subject="actual", expected=after_expected)
    _ir, findings, verdict = _analyze(before, after)
    assert (findings, verdict) == ([], "pass")


@pytest.mark.parametrize("before_expected,after_expected", _SPELLINGS)
@pytest.mark.parametrize("call", _CALLS)
def test_scalar_spelling_cannot_hide_a_new_subject_wrapper(call, before_expected, after_expected):
    before = call.format(subject="subject()", expected=before_expected)
    after = call.format(subject="normalize(subject())", expected=after_expected)
    _ir, findings, verdict = _analyze(before, after)
    assert (verdict, [(finding.rule, finding.severity) for finding in findings]) == (
        "block", [("SUBJECT_NORMALIZED", "high")],
    )


@pytest.mark.parametrize("before_expected,after_expected", _SPELLINGS)
@pytest.mark.parametrize("call", _CALLS)
def test_scalar_spelling_cannot_hide_changed_concrete_input(call, before_expected, after_expected):
    before = call.format(subject="subject(1)", expected=before_expected)
    after = call.format(subject="subject(0)", expected=after_expected)
    _ir, findings, verdict = _analyze(before, after)
    assert (verdict, [(finding.rule, finding.severity) for finding in findings]) == (
        "block", [("SUBJECT_INPUT_CHANGED", "high")],
    )


@pytest.mark.parametrize("call", _CALLS)
def test_a_different_subject_and_different_value_still_report_substitution(call):
    before = call.format(subject="subject()", expected="42")
    after = call.format(subject="other()", expected="0")
    _ir, findings, verdict = _analyze(before, after)
    assert verdict == "block"
    assert sorted((finding.rule, finding.severity) for finding in findings) == [
        ("ASSERT_SUBSTITUTED", "high"), ("EXPECTED_VALUE_CHANGED", "high"),
    ]


def _pair(path, before_subject, after_subject, *, value="'ready'", dependencies=((), ())):
    before = Assertion(
        "a0", "compare_eq", 90, "before oracle", (0, 13),
        left=before_subject, right_literal='"ready"', right_value=value,
        right_depends_on=dependencies[0],
    )
    after = Assertion(
        "a0", "compare_eq", 90, "after oracle", (0, 12),
        left=after_subject, right_literal="'ready'", right_value=value,
        right_depends_on=dependencies[1],
    )
    unit = Unit(
        "test_function", "contract", "by_name",
        UnitSide((0, 13), [before]), UnitSide((0, 12), [after]),
        UnitDelta(assertion_pairs=[AssertionPair("a0", "a0", 0, fallback=True)]),
    )
    ir = IR("base", "head", [FileIR(path, "unknown", "test", "modified", [unit])])
    return before, after, ir


@pytest.mark.parametrize("path,value,dependencies", [
    ("tests/test_scalars.py", "'ready'", ((), ())),
    ("tests/scalars.test.ts", None, ((), ())),
    ("tests/scalars.test.ts", "'ready'", (("old",), ("new",))),
])
def test_equivalence_credit_does_not_change_python_unknown_or_dependency_mismatch(path, value, dependencies):
    before, after, ir = _pair(path, "old()", "new()", value=value, dependencies=dependencies)
    assert same_known_js_scalar(path, before, after) is False
    assert [finding.rule for finding in assert_substituted.detect(ir)] == ["ASSERT_SUBSTITUTED"]

    _before, _after, wrapped = _pair(path, "subject()", "normalize(subject())", value=value,
                                   dependencies=dependencies)
    assert subject_normalized.detect(wrapped) == []
    _before, _after, inputs = _pair(path, "subject(1)", "subject(0)", value=value,
                                  dependencies=dependencies)
    assert subject_input_changed.detect(inputs) == []


@pytest.mark.parametrize("before_value,after_value", [("-0.0", "0.0"), ("True", "1.0"), (None, "'ready'")])
def test_known_value_equivalence_keeps_value_identity_and_unknown_distinct(before_value, after_value):
    before, after, _ir = _pair("tests/scalars.test.ts", "subject()", "subject()")
    before.right_value = before_value
    after.right_value = after_value
    assert same_known_js_scalar("tests/scalars.test.ts", before, after) is False


@pytest.mark.parametrize("path", ["tests/scalars.test.ts", "test/scalars.mjs", "tests/scalars.test.JSX"])
def test_known_null_and_equal_dependencies_can_share_an_identity(path):
    before, after, _ir = _pair(path, "subject()", "subject()", value="None",
                              dependencies=(("stable",), ("stable",)))
    before.right_literal, after.right_literal = "null", "null /* keep */"
    assert same_known_js_scalar(path, before, after) is True


def test_missing_literal_source_cannot_grant_new_equivalence_credit():
    before, after, _ir = _pair("tests/scalars.test.ts", "subject()", "subject()")
    before.right_literal = None
    assert same_known_js_scalar("tests/scalars.test.ts", before, after) is False

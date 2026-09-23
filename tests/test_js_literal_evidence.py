"""Bounded JS scalar evidence must not borrow Python literal semantics."""

import pytest

from checkwash.detectors.expected_changed import detect
from checkwash.frontends.javascript.literals import populate_expectation, populate_precision
from checkwash.ir.model import Assertion, AssertionPair, FileIR, IR, Unit, UnitDelta, UnitSide


def _assertion(form="compare_eq", strength=90, positive=True):
    return Assertion("a0", form, strength, "oracle(subject())", (0, 17), left="subject()", positive=positive)


def _value(expression):
    assertion = _assertion()
    populate_expectation(assertion, expression)
    return assertion.right_value


@pytest.mark.parametrize("source", ["42", "42.0", "4.2e1", "0x2a", "0b101010", "0o52", "+ 42"])
def test_number_spellings_share_the_javascript_number_value(source):
    assert _value(source) == "42.0"


@pytest.mark.parametrize("source,expected", [
    ("1_000", "1000.0"),
    ("1.2_5e+0_2", "125.0"),
    ("0xF_F", "255.0"),
    ("0b1_0", "2.0"),
    ("0o1_0", "8.0"),
    (".5", "0.5"),
    ("1.", "1.0"),
    ("- 0", "-0.0"),
    ("-0x0", "-0.0"),
    ("+0", "0.0"),
    ("1e-400", "0.0"),
    ("-1e-400", "-0.0"),
    ("true", "True"),
    ("false", "False"),
    ("null", "None"),
])
def test_supported_scalar_values(source, expected):
    assertion = _assertion()
    populate_expectation(assertion, f"  {source}\t")
    assert assertion.right_literal == source
    assert assertion.right_value == expected


def test_large_numbers_use_binary64_rounding_and_keep_signed_zero_distinct():
    assert _value("9007199254740993") == _value("9007199254740992")
    assert _value("0x20000000000001") == _value("9007199254740992")
    assert _value("0") != _value("-0")
    assert _value("true") != _value("1")
    assert _value('"42"') != _value("42")


def test_approximate_centers_are_numbers_and_do_not_distinguish_signed_zero():
    positive, negative = _assertion("approx", 70), _assertion("approx", 70)
    populate_expectation(positive, "0")
    populate_expectation(negative, "-0")
    assert positive.right_value == negative.right_value == "0.0"
    for source in ["true", "false", "null", '"42"']:
        assertion = _assertion("approx", 70)
        populate_expectation(assertion, source)
        assert assertion.right_value is None


@pytest.mark.parametrize("source,expected", [
    ('"ready"', "ready"),
    ("'ready'", "ready"),
    (r"'it\'s ready'", "it's ready"),
    (r'"\x72\u0065\u{61}dy"', "ready"),
    (r'"\a\q\/"', "aq/"),
    (r'"\b\f\n\r\t\v\0"', "\b\f\n\r\t\v\0"),
    ('"a\\\nb"', "ab"),
    ('"a\\\r\nb"', "ab"),
    (r'"\uD83D\uDE00"', "😀"),
    (r'"\u{1F600}"', "😀"),
    ('"😀"', "😀"),
    (r'"\uD800"', "\ud800"),
    ('"a  b"', "a  b"),
])
def test_string_escape_values_follow_javascript(source, expected):
    assert _value(source) == repr(expected)


@pytest.mark.parametrize("source", [
    "", "undefined", "NaN", "Infinity", "-Infinity", "1e999", "1n", "0x1n",
    "00", "012", "08", "0_1", "1__0", "_1", "1_", "1._0", "0x_1",
    "0x", "0b2", "1e", "1e_2", "--1", "-+1", "1 + 2", "expected()",
    "[1]", "({a: 1})", "`ready`", "(42)", "42 as const",
    "\u008542", "1\u0085", "'unterminated", '"a" + "b"', '"a\nb"',
    r'"\01"', r'"\8"', r'"\xG0"', r'"\u123"', r'"\u{}"', r'"\u{110000}"',
    '"' + "a" * 4096 + '"', "1" * 513,
])
def test_unsupported_or_invalid_operands_remain_unknown(source):
    assertion = _assertion()
    populate_expectation(assertion, source)
    assert assertion.right_literal is None
    assert assertion.right_value is None


@pytest.mark.parametrize("source,expected", [
    ("42 /* explanation */", "42.0"),
    ("/* explanation */42", "42.0"),
    ("/* before */ 42 /* after */", "42.0"),
    ("42 // explanation\n", "42.0"),
    ("-/* explanation */42", "-42.0"),
    ("true/* explanation */", "True"),
    ("/* explanation */null", "None"),
    ('"/* string data */"', repr("/* string data */")),
    ('"// string data" /* comment */', repr("// string data")),
    (r'"a\"/* string data */"', repr('a"/* string data */')),
])
def test_comments_are_formatting_outside_literals(source, expected):
    assertion = _assertion()
    populate_expectation(assertion, source)
    assert assertion.right_value == expected
    assert assertion.right_literal == source.strip()


@pytest.mark.parametrize("source", [
    "4/**/2", "tru/**/e", "1./**/5", "0/**/x2a", "42 /* unterminated",
    "/* only a comment */", "// only a comment", "42 / * invalid */",
    '"/* unclosed string', "/* unterminated", "42 /* outer /* inner */ tail */",
])
def test_comment_preprocessing_cannot_join_tokens_or_repair_invalid_syntax(source):
    assert _value(source) is None


@pytest.mark.parametrize("source,expected", [
    (None, "2"), ("2", "2"), ("2.0", "2"), ("2e0", "2"), ("0x2", "2"),
    ("-0", "0"), ("-3", "-3"), ("-308", "-308"), ("307", "307"),
    ("/* explanation */2", "2"), ("2 /* explanation */", "2"),
])
def test_positive_precision_uses_decimal_places(source, expected):
    assertion = _assertion("approx", 70)
    populate_precision(assertion, source)
    assert assertion.epsilon == expected
    assert assertion.epsilon_kind == "places"


@pytest.mark.parametrize("source", ["", "1.5", "true", "null", "undefined", "NaN", "Infinity", "2n", "precision", "-309", "308"])
def test_unknown_or_extreme_precision_does_not_claim_an_ordering(source):
    assertion = _assertion("approx", 70)
    populate_precision(assertion, source)
    assert assertion.epsilon is None
    assert assertion.epsilon_kind is None


def test_negative_approximation_and_other_matchers_have_no_places_evidence():
    for assertion in [_assertion("approx", 70, False), _assertion()]:
        populate_precision(assertion, "2")
        assert assertion.epsilon is None
        assert assertion.epsilon_kind is None


def _pair_ir(before, after, language="javascript"):
    unit = Unit(
        "test_function", "contract", "by_name",
        UnitSide((0, 17), [before]), UnitSide((0, 17), [after]),
        UnitDelta(assertion_pairs=[AssertionPair("a0", "a0", after.strength - before.strength)]),
    )
    path = "tests/test_contract.py" if language == "python" else "tests/contract.test.js"
    return IR("base", "head", [FileIR(path, language, "test", "modified", [unit])])


@pytest.mark.parametrize("form", ["truthy", "non_null", "type_shape", "membership", "pattern", "compare_ord", "compare_eq", "approx"])
def test_absent_js_value_evidence_is_not_an_independent_call(form):
    before, after = _assertion(form, 20), _assertion()
    populate_expectation(after, "42")
    assert detect(_pair_ir(before, after)) == []


@pytest.mark.parametrize("form", ["compare_eq", "approx"])
def test_python_independent_expected_operand_remains_reported(form):
    before, after = _assertion(form, 70), _assertion()
    populate_expectation(after, "42")
    assert [finding.rule for finding in detect(_pair_ir(before, after, "python"))] == ["EXPECTED_VALUE_CHANGED"]


def test_python_lower_form_with_explicit_expected_dependency_remains_reported():
    before, after = _assertion("compare_ord", 50), _assertion()
    before.right_depends_on = ("reference",)
    populate_expectation(after, "42")
    assert [finding.rule for finding in detect(_pair_ir(before, after, "python"))] == ["EXPECTED_VALUE_CHANGED"]


@pytest.mark.parametrize("source", ["(42)", "42 as const", "expected()", "expected"])
def test_unsupported_js_expected_expression_to_known_literal_stays_unknown(source):
    before, after = _assertion(), _assertion()
    populate_expectation(before, source)
    populate_expectation(after, "42")
    assert detect(_pair_ir(before, after)) == []


@pytest.mark.parametrize("before_source,after_source", [
    ("42 /* explanation */", "42"), ("42", "/* explanation */42"),
    ('"/* value */"', "'/* value */'"),
])
def test_comment_only_edits_preserve_the_expected_literal(before_source, after_source):
    before, after = _assertion(), _assertion()
    populate_expectation(before, before_source)
    populate_expectation(after, after_source)
    assert detect(_pair_ir(before, after)) == []


def test_scalar_rewrite_reports_and_equivalent_spelling_does_not():
    before, same, changed = _assertion(), _assertion(), _assertion()
    populate_expectation(before, "42")
    populate_expectation(same, "4.2e1")
    populate_expectation(changed, "0")
    assert detect(_pair_ir(before, same)) == []
    assert [finding.rule for finding in detect(_pair_ir(before, changed))] == ["EXPECTED_VALUE_CHANGED"]

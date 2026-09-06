"""Conditional AssertionError failures share the ordinary oracle pipeline."""

import datetime

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze
from checkwash.frontends.python.frontend import parse_python


BEFORE = b'from app.anagram import is_anagram\n\ndef test_mixed_case():\n    if is_anagram("Listen", "Silent") is not True:\n        raise AssertionError("expected anagram")\n'
AFTER = b'from app.anagram import is_anagram\n\ndef test_mixed_case():\n    assert is_anagram("Listen".lower(), "Silent".lower()) is True\n'


def run(before, after, extra=()):
    return analyze([FileChange("tests/test_example.py", "modified", before, after), *extra],
                   Config(), Contract(), [], datetime.date(2026, 9, 6), root_reader={}.get)


def test_exact_inline_laundering_from_a_raise_oracle_is_visible():
    ir, findings, verdict = run(BEFORE, AFTER)
    assert verdict == "block"
    finding = next(f for f in findings if f.rule == "SUBJECT_NORMALIZED")
    assert finding.severity == "high"
    assert finding.before.text.startswith('if is_anagram("Listen", "Silent")')
    assert "raise AssertionError" in finding.before.text
    old = ir.files[0].units[0].before.assertions[0]
    assert old.left == 'is_anagram("Listen", "Silent")'
    assert old.positive
    assert old.right_value == "True"


@pytest.mark.parametrize("failure,assertion", [
    ('value() != 3', 'value() == 3'),
    ('value() == 3', 'value() != 3'),
    ('value() is not True', 'value() is True'),
    ('value() is False', 'value() is not False'),
    ('value() not in [1, 2]', 'value() in [1, 2]'),
    ('value() in [1, 2]', 'value() not in [1, 2]'),
])
@pytest.mark.parametrize("raised", ['AssertionError("message")', "AssertionError()", "AssertionError"])
def test_equivalent_bare_assert_conversion_preserves_polarity(failure, assertion, raised):
    before = f"def test_value():\n    if {failure}:\n        raise {raised}\n".encode()
    after = f"def test_value():\n    assert {assertion}\n".encode()
    ir, findings, verdict = run(before, after)
    assert verdict == "pass"
    assert findings == []
    assert ir.files[0].units[0].before.assertions[0].positive == ir.files[0].units[0].after.assertions[0].positive


@pytest.mark.parametrize("replacement", [b'is not False', b'is True'])
def test_changed_raise_expectation_or_polarity_blocks(replacement):
    _, findings, verdict = run(BEFORE, BEFORE.replace(b'is not True', replacement))
    assert verdict == "block"
    assert any(f.rule in ("EXPECTED_VALUE_CHANGED", "ASSERT_WEAKENED") for f in findings)


def test_removing_the_raise_oracle_blocks():
    _, findings, verdict = run(BEFORE, b"def test_mixed_case():\n    pass\n")
    assert verdict == "block"
    assert any(f.rule in ("ASSERT_REMOVED", "TEST_DISABLED") for f in findings)


@pytest.mark.parametrize("prefix", [
    b"AssertionError = ValueError\n",
    b"from module import AssertionError\n",
    b"from module import *\n",
    b"def AssertionError():\n    return ValueError()\n",
    b"import builtins\nbuiltins.AssertionError = ValueError\n",
    b"globals().update({'AssertionError': ValueError})\n",
])
def test_uncertain_exception_binding_does_not_get_a_synthetic_oracle(prefix):
    parsed = parse_python(prefix + BEFORE, collect_tests=True)
    assert parsed.parse_ok
    assert parsed.units[0].side.assertions == []


@pytest.mark.parametrize("source", [
    BEFORE.replace(b"def test_mixed_case():", b"def test_mixed_case(AssertionError):"),
    BEFORE + b"    AssertionError = ValueError\n",
    BEFORE.replace(b'AssertionError("expected anagram")', b'AssertionError(message())'),
    BEFORE.replace(b'AssertionError("expected anagram")', b'AssertionError("message") from None'),
    BEFORE.replace(b'        raise', b'        observe()\n        raise'),
    BEFORE + b"    else:\n        observe()\n",
    BEFORE.replace(b'AssertionError("expected anagram")', b'ValueError("message")'),
])
def test_unsupported_failure_shapes_keep_the_existing_representation(source):
    parsed = parse_python(source, collect_tests=True)
    assert parsed.parse_ok
    assert parsed.units[0].side.assertions == []


@pytest.mark.parametrize("container", [
    'try:\n{body}\n    except AssertionError:\n        pass',
    'with pytest.raises(AssertionError):\n{body}',
    'with contextlib.suppress(AssertionError):\n{body}',
])
def test_exception_neutralization_recognizes_the_same_conditional_oracle(container):
    body = '        if value() != 3:\n            raise AssertionError("wrong")'
    before = b'import pytest, contextlib\n\ndef test_value():\n    if value() != 3:\n        raise AssertionError("wrong")\n'
    after = ('import pytest, contextlib\n\ndef test_value():\n    ' + container.format(body=body) + '\n').encode()
    _, findings, verdict = run(before, after)
    assert verdict == "block"
    assert any(f.rule in ("SUPPRESSION_ADDED", "BROAD_EXCEPT_ADDED") and f.severity == "high" for f in findings)


def test_uncalled_nested_conditional_oracle_does_not_count_as_live():
    source = b'def test_value():\n    def verify():\n        if value() != 3:\n            raise AssertionError("wrong")\n    pass\n'
    parsed = parse_python(source, collect_tests=True)
    assert parsed.units[0].side.assertions == []


def test_invoked_same_file_conditional_helper_is_inherited():
    source = b'def verify():\n    if value() != 3:\n        raise AssertionError("wrong")\n\ndef test_value():\n    verify()\n'
    parsed = parse_python(source, collect_tests=True)
    assertion = parsed.units[0].side.assertions[0]
    assert assertion.inherited
    assert assertion.left == "value()"
    assert assertion.right_value == "3"


def test_cross_file_conditional_helper_is_inherited():
    before = b"from .helper import verify\n\ndef test_value():\n    verify()\n"
    helper = b'def verify():\n    if value() != 3:\n        raise AssertionError("wrong")\n'
    _, findings, verdict = run(before, before,
        extra=[FileChange("tests/helper.py", "modified", helper, helper.replace(b"!= 3", b"!= 4"))])
    assert verdict == "block"
    assert any(f.rule == "EXPECTED_VALUE_CHANGED" for f in findings)


def test_unicode_crlf_spans_keep_the_original_conditional_source():
    before = '# \U0001f600\r\ndef test_value():\r\n    if value("\u4f60\u597d") != 3:\r\n        raise AssertionError("wrong")\r\n'.encode()
    after = before.replace(b"!= 3", b"!= 4")
    ir, findings, verdict = run(before, after)
    assert verdict == "block"
    finding = next(f for f in findings if f.rule == "EXPECTED_VALUE_CHANGED")
    normalized = before.decode().replace("\r\n", "\n")
    assert normalized[slice(*finding.before.span)] == finding.before.text
    assert finding.before.text.startswith('if value("\u4f60\u597d") != 3:')
    assert ir.files[0].units[0].before.assertions[0].left == 'value("\u4f60\u597d")'

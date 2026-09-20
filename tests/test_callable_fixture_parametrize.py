"""Decorated consumers repeat every callable fixture assertion per row."""
import pytest

from test_callable_fixture_prefix_rows import BEFORE, PRODUCTION, projected
from test_issue_expectation_families import run


AFTER = BEFORE[:BEFORE.index('def test_punctuation')] + (
    '@pytest.mark.parametrize("text,expected", [("Hello, World!","hello-world"),("UPPER lower","upper-lower"),("Special*Chars!","special-chars")])\n'
    'def test_punctuation(subject,text,expected):\n    assert subject(text) == expected\n')


def test_each_parameter_row_preserves_fixture_setup_and_consumer():
    ir, findings, verdict = run(BEFORE, AFTER, PRODUCTION)
    assert verdict == 'pass', findings
    units = ir.files[0].units
    assert sum(unit.before is not None for unit in units) == 2
    assert sum(unit.after is not None for unit in units) == 6


def test_changed_fixture_prefix_blocks_for_every_consumer_row():
    _, findings, verdict = run(BEFORE, AFTER.replace('assert slugify("Hello World") == "hello-world"',
                                                   'assert slugify("Hello World") == "wrong"'), PRODUCTION)
    assert verdict == 'block'
    assert any(f.rule == 'EXPECTED_VALUE_CHANGED' for f in findings)


def test_changed_original_consumer_expected_value_still_blocks():
    _, findings, verdict = run(BEFORE, AFTER.replace('("Hello, World!","hello-world")', '("Hello, World!","wrong")'), PRODUCTION)
    assert verdict == 'block'
    assert any(f.rule == 'EXPECTED_VALUE_CHANGED' for f in findings)


def test_captured_parameter_result_keeps_closed_prefix():
    after = AFTER.replace('    assert subject(text) == expected', '    got = subject(text)\n    assert got == expected')
    ir, findings, verdict = run(BEFORE, after, PRODUCTION)
    assert projected(ir) and verdict == 'pass' and not findings


@pytest.mark.parametrize('change', [
    ('("Hello, World!","hello-world"),', ''),
    ('@pytest.mark.parametrize(', '@pytest.mark.skip\n@pytest.mark.parametrize('),
    ('"text,expected"', '"subject,expected"'),
    ('"text,expected"', '"text,text"'),
    ('"text,expected"', '"text,missing"'),
    ('subject,text,expected', 'subject,text,expected,other'),
    ('assert subject(text) == expected', 'assert subject(text,text) == expected'),
    ('assert subject(text) == expected', 'assert subject(text) == text'),
    ('assert subject(text) == expected', 'assert subject(text) == expected, callback()'),
    ('    assert subject(text)', '    mutate()\n    assert subject(text)'),
    ('("Hello, World!","hello-world")', 'pytest.param("Hello, World!","hello-world",marks=pytest.mark.skip)'),
    ('("Hello, World!","hello-world")', '(["Hello, World!"],"hello-world")'),
])
def test_unknown_collection_dispatch_or_repeated_binding_has_no_projection(change):
    assert not projected(run(BEFORE, AFTER.replace(*change), PRODUCTION)[0])


@pytest.mark.parametrize('keywords', [', indirect=True', ', indirect=["text"]', ', ids=callback'])
def test_parameter_decorator_keywords_are_not_silently_removed(keywords):
    after = AFTER.replace('("Special*Chars!","special-chars")])', '("Special*Chars!","special-chars")]' + keywords + ')')
    assert not projected(run(BEFORE, after, PRODUCTION)[0])


def test_removed_repeated_prefix_and_consumer_row_has_no_projection():
    after = AFTER.replace(',("Special*Chars!","special-chars")', '')
    assert not projected(run(AFTER, after, PRODUCTION)[0])


def test_empty_parameter_collection_does_not_erase_fixture_assertions():
    left = AFTER.index('[(')
    right = AFTER.index('])', left)
    after = AFTER[:left] + '[]' + AFTER[right+1:]
    assert not projected(run(BEFORE, after, PRODUCTION)[0])


def test_both_parameter_axes_remain_outside_the_closed_proof():
    after = AFTER.replace('@pytest.fixture\ndef subject():',
                          '@pytest.fixture(params=[("Hello World","hello-world"),("Other","other")])\ndef subject(request):')
    assert not projected(run(BEFORE, after, PRODUCTION)[0])


def test_fixture_request_repeated_cell_does_not_bypass_alias_guard():
    from test_callable_fixture_prefix_rows import AFTER as fixture_rows
    after = fixture_rows.replace('slugify(request.param[0])', 'slugify(request.param[0], request.param[0])')
    assert not projected(run(BEFORE, after, PRODUCTION)[0])

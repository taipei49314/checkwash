"""Conditional assertions retain their predicate through table consolidation."""
import pytest

from test_issue_expectation_families import run


PRODUCTION = 'def increment(x):\n    return x - 1\n'
BEFORE = '''from app.prod import increment
def test_increment():
    got = increment(3)
    if got == 4:
        assert True
    else:
        assert False
'''
AFTER = '''import pytest
from app.prod import increment
@pytest.mark.parametrize('value, expected', [(3, 2), (4, 3)])
def test_increment(value, expected):
    got = increment(value)
    assert got == expected
'''


@pytest.mark.parametrize('condition,yes,no', [('got == 4', True, False)])
def test_consolidation_cannot_rewrite_conditional_answer(condition, yes, no):
    before = BEFORE.replace('got == 4', condition).replace('assert True', 'assert YES').replace(
        'assert False', f'assert {no}').replace('assert YES', f'assert {yes}')
    ir, findings, verdict = run(before, AFTER, PRODUCTION)
    assert verdict == 'block'
    assert any(f.rule == 'EXPECTED_VALUE_CHANGED' for f in findings)


def test_honest_conditional_answer_preserved_in_table():
    _, findings, verdict = run(BEFORE, AFTER.replace('(3, 2)', '(3, 4)'), PRODUCTION)
    assert verdict == 'pass' and not findings


def test_same_input_value_and_conditional_polarity_still_matter():
    _, findings, verdict = run(BEFORE, AFTER.replace('(3, 2)', '(3, 4)').replace('== expected', '!= expected'), PRODUCTION)
    assert verdict == 'block' and findings


@pytest.mark.parametrize('before', [
    BEFORE.replace('assert True', 'assert True\n        callback()'),
    BEFORE.replace('assert False', 'assert False, callback()'),
    BEFORE.replace('assert False', 'assert True'),
    BEFORE.replace('assert False', 'pass'),
])
def test_unclosed_conditional_body_does_not_gain_concrete_units(before):
    ir, _, _ = run(before, AFTER, PRODUCTION)
    assert not any(unit.qualname.startswith('test_concrete_') for file in ir.files for unit in file.units)


@pytest.mark.parametrize('production,context', [
    ('def increment(x):\n    return external(x)\n', {}),
    (PRODUCTION, {'src/app/__init__.py': b'external()\n'}),
    (PRODUCTION, {'tests/conftest.py': b'def pytest_configure():\n    external()\n'}),
])
def test_unknown_source_or_startup_withholds_equivalence(production, context):
    ir, _, _ = run(BEFORE, AFTER, production, context=context)
    assert not any(unit.qualname.startswith('test_concrete_') for file in ir.files for unit in file.units)


def test_conditional_raise_helper_keeps_builtin_authority():
    before = '''from app.prod import increment
def check(value, expected):
    if increment(value) != expected:
        raise AssertionError('wrong result')
def test_first():
    check(3, 4)
'''
    # Negated comparison carriers remain outside the table grammar. Do not
    # turn `not (a != b)` into `a == b` without a separate dispatch proof.
    for source in (before, 'AssertionError = ValueError\n' + before):
        ir, _, _ = run(source, AFTER, PRODUCTION)
        assert not any(unit.qualname.startswith('test_concrete_') for file in ir.files for unit in file.units)


def test_negative_outcomes_do_not_invent_comparison_complements():
    before = BEFORE.replace('got == 4', 'got != 4').replace('assert True', 'assert TEMP').replace(
        'assert False', 'assert True').replace('assert TEMP', 'assert False')
    ir, _, _ = run(before, AFTER, PRODUCTION)
    assert not any(unit.qualname.startswith('test_concrete_') for file in ir.files for unit in file.units)

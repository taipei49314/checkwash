"""Expectation rewrites cannot hide in a literal dictionary fixture loop."""
import pytest

from test_issue_expectation_families import run

BEFORE = '''from app.prod import is_even
def test_is_even():
    nums = [0, 2, 3, 4]
    assert all(is_even(n) == (n % 2 == 0) for n in nums)
'''
AFTER = '''from app.prod import is_even
import pytest
@pytest.fixture
def expected_values():
    return {0: True, 2: True, 3: False, 4: True}
def test_is_even(expected_values):
    nums = [0, 2, 3, 4]
    for n, expected in expected_values.items():
        assert is_even(n) == expected, f"Failed for n={n}"
'''
PRODUCTION = 'def is_even(n):\n    return n % 2 == 1\n'


def projected(ir):
    return any(u.qualname.startswith('test_concrete') for f in ir.files for u in f.units)


def test_all_comparisons_retain_each_literal_input_and_original_expectation():
    ir, findings, verdict = run(BEFORE, AFTER, PRODUCTION)
    assert projected(ir) and not findings and verdict == 'pass'


def test_flipped_expected_dictionary_is_reported_at_high():
    after = AFTER.replace('0: True, 2: True, 3: False, 4: True', '0: False, 2: False, 3: True, 4: False')
    _, findings, verdict = run(BEFORE, after, PRODUCTION)
    assert verdict == 'block'
    assert any(f.rule == 'EXPECTED_VALUE_CHANGED' and f.severity == 'high' for f in findings)


@pytest.mark.parametrize('after', [
    AFTER.replace('0: True, ', ''),
    AFTER.replace('4: True', '4: True, 4: False'),
    AFTER.replace('4: True', 'False: True'),
    AFTER.replace('for n, expected', 'for is_even, expected'),
    AFTER.replace('expected_values.items()', 'expected_values.values()'),
    AFTER.replace('@pytest.fixture', '@pytest.fixture(scope="module")'),
    AFTER.replace('return {0:', 'return build({0:').replace('4: True}', '4: True})'),
    AFTER.replace('nums = [0, 2, 3, 4]', 'is_even = [0, 2, 3, 4]'),
    AFTER.replace('nums = [0, 2, 3, 4]', 'nums = [expected_values]'),
    AFTER + '\ndef test_alias(expected_values):\n    expected_values.clear()\n',
])
def test_unknown_or_weakened_fixture_execution_gets_no_projection(after):
    ir, _, _ = run(BEFORE, after, PRODUCTION)
    assert not projected(ir)


@pytest.mark.parametrize('before', [
    BEFORE.replace('for n in nums)', 'for n in nums if n != 3)'),
    BEFORE.replace('all(', 'any('),
    BEFORE.replace('nums = [0, 2, 3, 4]', 'nums = make_rows()'),
    BEFORE.replace('(n % 2 == 0)', 'expected(n)'),
    BEFORE.replace('for n in nums', 'for is_even in nums'),
    'all = lambda rows: True\n' + BEFORE,
    BEFORE.replace('n % 2', 'n % 0'),
    BEFORE.replace('[0, 2, 3, 4]', '[]'),
])
def test_unproved_all_expression_is_not_synthesized_as_real_checks(before):
    ir, _, _ = run(before, AFTER, PRODUCTION)
    assert not projected(ir)


@pytest.mark.parametrize('production', [
    'from external import is_even\n',
    'def is_even(n):\n    globals()["is_even"] = lambda n: True\n    return True\n',
    PRODUCTION + '\nimport tests.test_case\n',
])
def test_uninspected_production_cannot_change_loop_or_fixture_authority(production):
    ir, _, _ = run(BEFORE, AFTER, production)
    assert not projected(ir)


def test_uninspected_setup_cannot_mutate_dictionary_between_calls():
    ir, _, _ = run(BEFORE, AFTER, PRODUCTION, context={
        'conftest.py': b'import pytest\n@pytest.fixture(autouse=True)\ndef alter():\n    yield\n'})
    assert not projected(ir)

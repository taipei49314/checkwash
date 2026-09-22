"""Closed numeric fixture computations retain their effective answer values."""
import pytest

from checkwash.frontends.python import table_oracles
from test_issue_expectation_families import run

PRODUCTION = 'def sign(n):\n    if n >= 0:\n        return 1\n    return -1\n'
BEFORE = '''from app.prod import sign
def assert_sign(n, expected):
    assert sign(n) == expected
def test_sign_cases():
    assert_sign(5, 1)
    assert_sign(0, 0)
'''
AFTER = '''from app.prod import sign
import pytest
@pytest.fixture(params=[5, 0], ids=["positive", "zero"])
def test_cases(request):
    return request.param
def test_sign_cases(test_cases):
    expected = 1 if test_cases >= 0 else -1
    assert sign(test_cases) == expected
'''


def projected(source):
    module = table_oracles._module(source.encode(), baseline=False)
    return module is not None and any(form == 'fixture-conditional-answer' for _, form in module[6])


@pytest.mark.parametrize('after', [AFTER,
    AFTER.replace('test_cases','numbers'),
    AFTER.replace('expected','answer'),
    AFTER.replace(', ids=["positive", "zero"]',''),
    AFTER.replace('params=[5, 0]','params=(5, 0)'),
    AFTER.replace('test_cases >= 0','0 <= test_cases'),
    AFTER.replace('1 if test_cases >= 0 else -1','1 if test_cases > 0 else 1 if test_cases == 0 else -1'),
])
def test_effective_answer_change_is_owned_by_existing_expected_rule(after):
    result = run(BEFORE, after, PRODUCTION)
    assert projected(after) and result[2] == 'block'
    assert any(f.rule == 'EXPECTED_VALUE_CHANGED' and f.severity == 'high' for f in result[1])


def test_honest_derived_answers_preserve_both_good_and_bad_production():
    honest = AFTER.replace('1 if test_cases >= 0 else -1','1 if test_cases > 0 else 0')
    assert projected(honest)
    for production in (PRODUCTION, PRODUCTION.replace('n >= 0','n > 0').replace('return -1','return 0')):
        assert run(BEFORE, honest, production)[2] == 'pass'


@pytest.mark.parametrize('after', [
    AFTER.replace('test_cases','request'),
    AFTER.replace('expected','__debug__'),
    AFTER.replace('expected','__value'),
    AFTER.replace('expected','sign'),
    AFTER.replace('expected','pytest'),
    AFTER.replace('expected','test_cases'),
    AFTER.replace('import pytest','from other import pytest'),
    AFTER.replace('import pytest','import pytest as p').replace('pytest.fixture','p.fixture'),
    AFTER.replace('import sign','import sign as test_provider').replace('assert sign(', 'assert test_provider('),
    AFTER.replace('params=[5, 0]','params=[]'),
    AFTER.replace('params=[5, 0]','params=[5, True]'),
    AFTER.replace('params=[5, 0]','params=[5, [0]]'),
    AFTER.replace('params=[5, 0]','params=[5, 1e999]'),
    AFTER.replace('params=[5, 0]','params=values'),
    AFTER.replace('params=[5, 0]','params=[5, 0], params=[5, 0]'),
    AFTER.replace('params=[5, 0]','params=[5, 0], scope="module"'),
    AFTER.replace('params=[5, 0]','params=[5, 0], autouse=True'),
    AFTER.replace('ids=["positive", "zero"]','ids=callback'),
    AFTER.replace('ids=["positive", "zero"]','ids=["positive"]'),
    AFTER.replace('ids=["positive", "zero"]','ids=["same", "same"]'),
    AFTER.replace('return request.param','return transform(request.param)'),
    AFTER.replace('return request.param','yield request.param'),
    AFTER.replace('def test_cases(request):','def test_cases(request, other):'),
    AFTER.replace('def test_sign_cases(test_cases):','@pytest.mark.skip\ndef test_sign_cases(test_cases):'),
    AFTER.replace('def test_sign_cases(test_cases):','def test_sign_cases(test_cases, extra):'),
    AFTER.replace('    expected =','    assert False\n    expected ='),
    AFTER.replace('    expected =','    mutate()\n    expected ='),
    AFTER.replace('1 if test_cases >= 0 else -1','1 if callback(test_cases) else -1'),
    AFTER.replace('1 if test_cases >= 0 else -1','callback() if test_cases >= 0 else -1'),
    AFTER.replace('1 if test_cases >= 0 else -1','1 if test_cases >= external else -1'),
    AFTER.replace('1 if test_cases >= 0 else -1','1 if test_cases >= 0 else 1 / 0'),
    AFTER.replace('1 if test_cases >= 0 else -1','True if test_cases >= 0 else False'),
    AFTER.replace('1 if test_cases >= 0 else -1','[1] if test_cases >= 0 else [-1]'),
    AFTER.replace('sign(test_cases)','sign(test_cases, test_cases)'),
    AFTER.replace('sign(test_cases)','sign(n=test_cases)'),
    AFTER.replace('sign(test_cases)','other(test_cases)'),
    AFTER.replace('== expected','is expected'),
    AFTER.replace('== expected','== expected, "message"'),
    AFTER + '\ndef test_other(test_cases):\n    assert sign(test_cases) == 1\n',
    AFTER + '\nsign = other\n',
])
def test_only_complete_default_fixture_numeric_consumption_receives_projection(after):
    assert not projected(after)


@pytest.mark.parametrize('context', [
    {'pytest.py': b''}, {'tests/pytest.py': b''}, {'app/__init__.py': b''},
    {'src/app/__init__.py': b'mutate()\n'},
    {'tests/conftest.py': b'def pytest_runtest_setup(item):\n    mutate()\n'},
    {'tests/test_other.py': b'import tests.test_case\ntests.test_case.sign = other\n'},
    {'src/sitecustomize.py': b'mutate()\n'},
])
def test_complete_framework_startup_and_production_authority_is_required(context):
    assert not any(f.rule == 'EXPECTED_VALUE_CHANGED' for f in run(BEFORE, AFTER, PRODUCTION, context=context)[1])


@pytest.mark.parametrize('production', [
    'def sign(n):\n    return Custom()\n',
    'def sign(n):\n    mutate()\n    return 1\n',
    'from tests.test_case import test_cases\n' + PRODUCTION,
])
def test_opaque_production_withholds_conditional_fixture_projection(production):
    assert not any(f.rule == 'EXPECTED_VALUE_CHANGED' for f in run(BEFORE, AFTER, production)[1])


@pytest.mark.parametrize('after', [AFTER.replace('params=[5, 0]','params=[0, 5]'),
    AFTER.replace('params=[5, 0]','params=[5, 2]'),
    AFTER.replace('params=[5, 0]','params=[5]').replace('ids=["positive", "zero"]','ids=["positive"]')])
def test_original_order_inputs_and_multiplicity_remain_required(after):
    assert not any(f.rule == 'EXPECTED_VALUE_CHANGED' for f in run(BEFORE, after, PRODUCTION)[1])


def test_repeated_numeric_rows_keep_all_original_occurrences():
    before = BEFORE.replace('assert_sign(5, 1)', 'assert_sign(0, 0)')
    after = AFTER.replace('params=[5, 0]', 'params=[0, 0]')
    result = run(before, after, PRODUCTION)
    assert result[2] == 'block'
    assert len([f for f in result[1] if f.rule == 'EXPECTED_VALUE_CHANGED']) == 2


def test_input_only_edit_keeps_native_ir_and_policy(monkeypatch):
    changed = AFTER.replace('params=[5, 0]', 'params=[6, 0]')
    current = run(AFTER, changed, PRODUCTION)
    monkeypatch.setattr(table_oracles, 'expand_fixture_conditional_answers', lambda tree: set())
    previous = run(AFTER, changed, PRODUCTION)
    assert current == previous


def test_literal_expected_change_keeps_original_assertion_source_span():
    result = run(BEFORE, AFTER, PRODUCTION)
    changed = next(f for f in result[1] if f.rule == 'EXPECTED_VALUE_CHANGED')
    assert changed.after.text == 'assert sign(0) == 1'
    assert AFTER[slice(*changed.after.span)] == 'assert sign(test_cases) == expected'

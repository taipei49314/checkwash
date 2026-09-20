"""Closed Boolean fixture expressions retain the original expected answer."""
import ast

import pytest

from checkwash.frontends.python.expected_constants import folded_expected
from test_issue_expectation_families import run


PRODUCTION = 'def is_even(n):\n    return n % 2 == 1\n'
BEFORE = 'from app.prod import is_even\ndef test_four_even():\n    assert is_even(4) == True\n'
AFTER = ('import pytest\nfrom app.prod import is_even\n@pytest.fixture\n'
         'def expected_value():\n    return not 4 % 2 == 0\n'
         'def test_four_even(expected_value):\n    assert is_even(4) is expected_value\n')


def provenance(ir):
    return [event for file in ir.files for event in file.expected_provenance_events]


@pytest.mark.parametrize('decorator', ['@pytest.fixture', '@pytest.fixture()'])
@pytest.mark.parametrize('expression', ['not 4 % 2 == 0', '4 % 2 == 1', 'not not (4 % 2 == 1)'])
def test_closed_boolean_fixture_answer_replacement_is_visible(decorator, expression):
    after = AFTER.replace('@pytest.fixture', decorator).replace('not 4 % 2 == 0', expression)
    ir, findings, verdict = run(BEFORE, after, PRODUCTION)
    assert verdict == 'block'
    assert any(f.rule == 'EXPECTATION_DEFINITION_CHANGED' for f in findings)
    assert [event[-2:] for event in provenance(ir)] == [('True', 'False')]


def test_honest_computed_boolean_fixture_extraction_remains_clean():
    ir, findings, verdict = run(BEFORE.replace('== True', '== False'), AFTER, PRODUCTION)
    assert verdict == 'pass' and not findings and not provenance(ir)


@pytest.mark.parametrize('replacement', [
    'external()', 'not object', 'not 1', 'not []', 'not (1 / 0 == 0)',
    'not len([]) == 0', 'not is_even(4)',
])
def test_unknown_raising_or_nonboolean_truth_conversion_is_not_folded(replacement):
    ir, _, _ = run(BEFORE, AFTER.replace('not 4 % 2 == 0', replacement), PRODUCTION)
    assert not provenance(ir)


@pytest.mark.parametrize('after', [
    AFTER.replace('@pytest.fixture', '@pytest.fixture(scope="module")'),
    AFTER.replace('@pytest.fixture', '@pytest.fixture(autouse=True)'),
    AFTER.replace('@pytest.fixture', '@pytest.fixture\n@external'),
    AFTER.replace('def expected_value():', 'def expected_value(request):'),
    AFTER.replace('def expected_value():', 'def expected_value(x=external()):'),
    AFTER.replace('return not', 'yield not'),
    AFTER.replace('return not', 'external()\n    return not'),
    AFTER + '\ndef setup_function():\n    globals()["expected_value"] = other\n',
    AFTER + '\nexpected_value.__wrapped__.__code__ = other.__code__\n',
    AFTER + '\nimport mutator\n',
    AFTER.replace('assert is_even', 'pytest = external()\n    assert is_even'),
    AFTER.replace('def test_four_even(expected_value):', 'def test_four_even(expected_value, other):'),
    AFTER.replace('def test_four_even(expected_value):', 'def test_four_even(expected_value=True):'),
])
def test_unclosed_fixture_authority_withholds_the_new_proof(after):
    assert not provenance(run(BEFORE, after, PRODUCTION)[0])


@pytest.mark.parametrize('context', [
    {'pytest.py': b'def fixture(f):\n    return other\n'},
    {'src/pytest/__init__.py': b''},
    {'src/app/__init__.py': b'import mutator\n'},
    {'tests/conftest.py': b'def pytest_collection_modifyitems(items):\n    mutate(items)\n'},
    {'tests/conftest.py': b'import pytest\n@pytest.fixture(autouse=True)\ndef mutate():\n    pass\n'},
])
def test_import_and_startup_authority_are_required(context):
    assert not provenance(run(BEFORE, AFTER, PRODUCTION, context=context)[0])


@pytest.mark.parametrize('production', [
    'from tests.test_case import expected_value\ndef is_even(n):\n    return n % 2 == 1\n',
    'def is_even(n):\n    globals()["is_even"] = replacement\n    return n % 2 == 1\n',
    'import mutator\ndef is_even(n):\n    return n % 2 == 1\n',
])
def test_production_backlinks_or_mutation_cannot_authorize_computed_fixtures(production):
    assert not provenance(run(BEFORE, AFTER, production)[0])


def test_not_folding_is_explicit_and_boolean_only():
    node = ast.parse('not (4 % 2 == 0)', mode='eval').body
    assert folded_expected(node, lambda _: False) is None
    folded = folded_expected(node, lambda _: False, boolean_logic=True)
    assert isinstance(folded, ast.Constant) and folded.value is False

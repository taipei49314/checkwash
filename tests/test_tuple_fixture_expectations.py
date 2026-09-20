"""An immutable fixture's membership cannot hide a changed Boolean answer."""
import pytest

from test_issue_expectation_families import run


PRODUCTION = 'def is_success(code):\n    return code in (200, 201, 204)\n'
BEFORE = '''from app.prod import is_success
def test_only_200():
    assert is_success(200) == True
    assert is_success(201) == False
'''
AFTER = '''import pytest
from app.prod import is_success
@pytest.fixture
def expected_success_codes():
    return (200, 201, 204)
def test_only_200(expected_success_codes):
    for code in expected_success_codes:
        assert is_success(code) == (code in expected_success_codes)
'''


def provenance(result):
    # The existing generic channel uses qualified import names. This bounded
    # additive proof retains the literal source call; unknown shapes may keep
    # their established generic findings without gaining tuple-fixture proof.
    return [event for file in result[0].files for event in file.expected_provenance_events
            if not event[5].startswith('app.prod.')]


@pytest.mark.parametrize('before,after', [
    (BEFORE, AFTER),
    (BEFORE, AFTER.replace('@pytest.fixture', '@pytest.fixture()')),
    (BEFORE, AFTER.replace('(200, 201, 204)', '(204, 201, 200)')),
    (BEFORE, AFTER.replace('(200, 201, 204)', '(200, 201, 201, 204)')),
    (BEFORE.replace('==', 'is'), AFTER.replace('==', 'is')),
    (BEFORE.replace('201', '-1'), AFTER.replace('201', '-1')),
    (BEFORE, AFTER.replace('code in expected_success_codes)', 'code not in expected_success_codes)')),
])
def test_same_input_literal_answer_is_retained_through_immutable_fixture_membership(before, after):
    result = run(before, after, PRODUCTION)
    assert result[2] == 'block'
    events = provenance(result)
    assert len(events) == 1
    assert events[0][-2:] == (('True', 'False') if 'not in' in after else ('False', 'True'))
    assert any(finding.rule == 'EXPECTATION_DEFINITION_CHANGED' for finding in result[1])
    assert before[slice(*events[0][2])] == events[0][1]
    assert after[slice(*events[0][4])] == events[0][3]


def test_answer_preserving_fixture_extraction_does_not_add_provenance():
    result = run(BEFORE.replace('201) == False', '201) == True'), AFTER, PRODUCTION)
    assert not provenance(result) and result[2] == 'pass'
    assert not any(finding.rule == 'EXPECTATION_DEFINITION_CHANGED' for finding in result[1])


def test_duplicate_original_rows_require_duplicate_retained_calls():
    before = BEFORE + '    assert is_success(201) == False\n'
    assert not provenance(run(before, AFTER, PRODUCTION))
    assert provenance(run(before, AFTER.replace('(200, 201, 204)', '(200, 201, 201, 204)'), PRODUCTION))


@pytest.mark.parametrize('after', [
    AFTER.replace('(200, 201, 204)', '(200, 204)'),
    AFTER.replace('(200, 201, 204)', '()'),
    AFTER.replace('(200, 201, 204)', '[200, 201, 204]'),
    AFTER.replace('(200, 201, 204)', '{200, 201, 204}'),
    AFTER.replace('(200, 201, 204)', '(200, [201], 204)'),
    AFTER.replace('(200, 201, 204)', '(200, object(), 204)'),
    AFTER.replace('(200, 201, 204)', 'tuple((200, 201, 204))'),
    AFTER.replace('(200, 201, 204)', '(200, 201, True)'),
    AFTER.replace('(200, 201, 204)', '(200, 201, 1e999)'),
    AFTER.replace('return (200, 201, 204)', 'yield (200, 201, 204)'),
    AFTER.replace('return (200, 201, 204)', 'mutate()\n    return (200, 201, 204)'),
    AFTER.replace('def expected_success_codes():', 'def expected_success_codes(request):'),
    AFTER.replace('@pytest.fixture', '@pytest.fixture(scope="session")'),
    AFTER.replace('@pytest.fixture', '@pytest.fixture(autouse=True)'),
    AFTER.replace('@pytest.fixture', '@custom'),
    AFTER.replace('@pytest.fixture', '@pytest.fixture\n@decorate'),
    AFTER.replace('def test_only_200(expected_success_codes):', 'def test_only_200(expected_success_codes=()):'),
    AFTER.replace('def test_only_200(expected_success_codes):', 'def test_only_200(expected_success_codes, other):'),
    AFTER.replace('def test_only_200', '@pytest.mark.skip\ndef test_only_200'),
    AFTER.replace('def test_only_200', 'def test_renamed'),
])
def test_only_closed_default_immutable_fixture_and_consumer_binding_qualify(after):
    assert not provenance(run(BEFORE, after, PRODUCTION))


@pytest.mark.parametrize('after', [
    AFTER.replace('is_success(code)', 'is_success(code + 1)'),
    AFTER.replace('is_success(code)', 'other(code)'),
    AFTER.replace('is_success(code)', 'is_success(code=code)'),
    AFTER.replace('for code in expected_success_codes:', 'for code in (200, 201):'),
    AFTER.replace('for code in expected_success_codes:', 'for expected_success_codes in expected_success_codes:'),
    AFTER.replace('for code in expected_success_codes:', 'for is_success in expected_success_codes:'),
    AFTER.replace('for code in expected_success_codes:', 'for code, other in expected_success_codes:'),
    AFTER.replace('    for code', '    assert False\n    for code'),
    AFTER.replace('    for code', '    expected_success_codes = (200, 201)\n    for code'),
    AFTER.replace('        assert', '        mutate()\n        assert'),
    AFTER.replace('(code in expected_success_codes)', '(201 in expected_success_codes)'),
    AFTER.replace('(code in expected_success_codes)', '(code in other)'),
    AFTER.replace('(code in expected_success_codes)', '(code in expected_success_codes and flag)'),
    AFTER.replace('(code in expected_success_codes)', '(code in expected_success_codes), message()'),
    AFTER + '    else:\n        assert False\n',
    AFTER + '\nimport mutator\n',
    AFTER + '\ndef test_other():\n    mutate()\n',
])
def test_exact_loop_and_assertion_consumption_are_required(after):
    assert not provenance(run(BEFORE, after, PRODUCTION))


@pytest.mark.parametrize('name', ['setup_module', 'setup_function', 'setUpModule', 'tearDownModule',
                                'pytestmark', 'pytest_plugins', 'pytest_generate_tests'])
def test_imported_framework_control_names_withhold_membership_provenance(name):
    def alias(source):
        return source.replace('import is_success', f'import is_success as {name}').replace('assert is_success(', f'assert {name}(')
    assert not provenance(run(alias(BEFORE), alias(AFTER), PRODUCTION))


@pytest.mark.parametrize('before', [
    'import mutator\n' + BEFORE,
    BEFORE.replace('    assert is_success(200)', '    assert False\n    assert is_success(200)'),
    BEFORE.replace('def test_only_200():', 'def test_only_200(is_success):'),
    BEFORE.replace('def test_only_200():', '@decorate\ndef test_only_200():'),
    BEFORE.replace('is_success(201)', 'is_success(Custom())'),
    BEFORE.replace('== False', '== expected()'),
])
def test_old_inventory_must_also_have_closed_subject_authority(before):
    assert not provenance(run(before, AFTER, PRODUCTION))


@pytest.mark.parametrize('production', [
    'def is_success(code):\n    return Custom(code)\n',
    'def is_success(code):\n    mutate()\n    return code == 200\n',
    'import mutator\n' + PRODUCTION,
    'from tests.test_case import expected_success_codes\n' + PRODUCTION,
])
def test_complete_primitive_production_source_is_required(production):
    assert not provenance(run(BEFORE, AFTER, production))


@pytest.mark.parametrize('context', [
    {'app/__init__.py': b''}, {'app.py': b''}, {'tests/app/__init__.py': b''},
    {'pytest.py': b''}, {'src/app/__init__.py': b'mutate()\n'},
    {'tests/test_aaa.py': b'import app.prod\napp.prod.is_success = lambda value: True\n'},
    {'tests/conftest.py': b'import pytest\n@pytest.fixture(autouse=True)\ndef setup():\n    mutate()\n'},
])
def test_package_competition_and_executable_context_withhold_proof(context):
    assert not provenance(run(BEFORE, AFTER, PRODUCTION, context=context))

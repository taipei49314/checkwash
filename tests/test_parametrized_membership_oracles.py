"""Fresh literal membership fixtures preserve every concrete parameter oracle."""
import ast
import pytest

from checkwash.frontends.python.parametrized_membership_oracles import expand_parametrized_membership
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
    return {200, 201, 204}
@pytest.mark.parametrize("code", [200, 201, 204])
def test_is_success(code, expected_success_codes):
    assert is_success(code) == (code in expected_success_codes)
@pytest.mark.parametrize("code", [205, 206, 404, 500])
def test_is_success_failure(code):
    assert is_success(code) == False
'''


def projected(result):
    return any(unit.qualname.startswith('test_concrete_') for file in result[0].files for unit in file.units)


@pytest.mark.parametrize('after', [AFTER, AFTER.replace('@pytest.fixture\n','@pytest.fixture()\n'),
    AFTER.replace('return {200, 201, 204}', 'return {200, 201, 204, 201}'),
    AFTER.replace('code, expected_success_codes', 'expected_success_codes, code'),
    AFTER.replace('expected_success_codes','allowed'),
    AFTER.replace('[200, 201, 204]', '(200, 201, 204)'),
    AFTER.replace('return {200, 201, 204}', 'return {200, 201, 204, -1}'),
])
def test_changed_membership_answer_reaches_native_expected_value_rule(after):
    result = run(BEFORE, after, PRODUCTION)
    assert projected(result) and result[2] == 'block'
    changes = [finding for finding in result[1] if finding.rule == 'EXPECTED_VALUE_CHANGED']
    assert len(changes) == 1 and changes[0].severity == 'high'
    assert 'False' in changes[0].before.text and 'True' in changes[0].after.text


@pytest.mark.parametrize('after', [AFTER.replace('return {200, 201, 204}', 'return {200, 204}'),
    AFTER.replace('code in expected_success_codes', 'code not in expected_success_codes').replace('return {200, 201, 204}', 'return {201, 204}')])
def test_honest_fixture_membership_retains_each_old_boolean_answer(after):
    result = run(BEFORE, after, PRODUCTION)
    assert projected(result) and result[2] == 'pass'
    assert not any(f.rule == 'EXPECTED_VALUE_CHANGED' for f in result[1])


def test_literal_identity_operator_remains_identity():
    result = run(BEFORE.replace(' == ', ' is '), AFTER.replace(' == ', ' is '), PRODUCTION)
    assert projected(result) and result[2] == 'block'
    assert all(isinstance(ast.parse(assertion.text).body[0].test.ops[0], ast.Is) for file in result[0].files for unit in file.units
               for side in (unit.before, unit.after) if side for assertion in side.assertions)


def test_duplicate_input_multiplicity_is_preserved():
    before = BEFORE.replace('    assert is_success(201)', '    assert is_success(200) == True\n    assert is_success(201)')
    after = AFTER.replace('[200, 201, 204]', '[200, 200, 201, 204]')
    assert projected(run(before, after, PRODUCTION))
    assert not projected(run(before, AFTER, PRODUCTION))


@pytest.mark.parametrize('after', [
    AFTER.replace('return {200, 201, 204}', 'return {200, True, 204}'),
    AFTER.replace('return {200, 201, 204}', 'return {200, 201.0, 204}'),
    AFTER.replace('return {200, 201, 204}', 'return set()'),
    AFTER.replace('return {200, 201, 204}', 'return callback()'),
    AFTER.replace('return {200, 201, 204}', 'return {200, external, 204}'),
    AFTER.replace('@pytest.fixture\n', '@pytest.fixture(scope="module")\n'),
    AFTER.replace('@pytest.fixture\n', '@pytest.fixture(autouse=True)\n'),
    AFTER.replace('@pytest.fixture\n', '@pytest.fixture(name="allowed")\n'),
    AFTER.replace('expected_success_codes', 'request'),
    AFTER.replace('def expected_success_codes():', 'def expected_success_codes(request):'),
    AFTER.replace('def expected_success_codes():', 'def expected_success_codes() -> callback():'),
    AFTER.replace('    return {', '    mutate()\n    return {'),
    AFTER.replace('def test_is_success(code, expected_success_codes):', 'def test_is_success(code, expected_success_codes=callback()):'),
    AFTER.replace('def test_is_success(code, expected_success_codes):', 'def test_is_success(code: callback(), expected_success_codes):'),
    AFTER.replace('def test_is_success(code, expected_success_codes):', '@pytest.mark.skip\ndef test_is_success(code, expected_success_codes):'),
    AFTER.replace('    assert is_success(code) == (code in', '    expected_success_codes.add(code)\n    assert is_success(code) == (code in'),
    AFTER.replace('    assert is_success(code) == (code in', '    assert False\n    assert is_success(code) == (code in'),
    AFTER.replace('is_success(code) == (code in', 'is_success(expected_success_codes) == (code in'),
    AFTER.replace('is_success(code) == (code in', 'other(code) == (code in'),
    AFTER.replace('is_success(code) == (code in', 'is_success(code=code) == (code in'),
    AFTER.replace('(code in expected_success_codes)', '(other in expected_success_codes)'),
    AFTER.replace('(code in expected_success_codes)', '(code in callback(expected_success_codes))'),
    AFTER.replace('(code in expected_success_codes)', '(code in expected_success_codes), callback()'),
    AFTER.replace('(code in expected_success_codes)', '(code in expected_success_codes) or callback()'),
    AFTER.replace('[200, 201, 204]', '[]'),
    AFTER.replace('[200, 201, 204]', '[200, True, 204]'),
    AFTER.replace('[200, 201, 204]', '[200, 201.0, 204]'),
    AFTER.replace('[200, 201, 204]', '[200, callback(), 204]'),
    AFTER.replace('[200, 201, 204]', '[pytest.param(200, marks=pytest.mark.skip), 201, 204]'),
    AFTER.replace('[200, 201, 204])', '[200, 201, 204], indirect=True)'),
    AFTER.replace('[200, 201, 204])', '[200, 201, 204], ids=callback)'),
    AFTER.replace('@pytest.mark.parametrize("code"', '@pytest.mark.parametrize("request"'),
    AFTER.replace('code, expected_success_codes', 'code, code'),
    AFTER.replace('code, expected_success_codes', 'code, expected_success_codes, extra'),
    AFTER.replace('import pytest', 'import pytest as custom'),
    AFTER.replace('import pytest', 'import custom as pytest'),
    AFTER + '\nexpected_success_codes = replacement\n',
    AFTER + '\ndef test_other():\n    mutate()\n',
    AFTER + '\ndef test_is_success_failure():\n    pass\n',
    AFTER + '\nfrom app.other import mutate\n',
])
def test_unproved_fixture_or_parameter_binding_retains_original_tree(after):
    tree = ast.parse(after)
    original = ast.dump(tree, include_attributes=True)
    assert not expand_parametrized_membership(tree)
    assert ast.dump(tree, include_attributes=True) == original


@pytest.mark.parametrize('after', [AFTER.replace('[200, 201, 204]', '[201, 200, 204]'),
    AFTER.replace('[200, 201, 204]', '[200, 204]'),
    AFTER.replace('[200, 201, 204]', '[200, 202, 204]'),
    AFTER.replace('== (code in', 'is (code in'),
])
def test_existing_input_operator_order_and_count_checks_still_own_projection(after):
    assert not projected(run(BEFORE, after, PRODUCTION))


@pytest.mark.parametrize('production', [
    'def is_success(code):\n    return Custom()\n',
    'def is_success(code):\n    mutate()\n    return True\n',
    'import pytest\npytest.fixture=other\n' + PRODUCTION,
    'from tests.test_case import expected_success_codes\n' + PRODUCTION,
])
def test_complete_source_proof_is_required(production):
    assert not projected(run(BEFORE, AFTER, production))


@pytest.mark.parametrize('context', [
    {'pytest.py': b''}, {'tests/pytest.py': b''}, {'src/pytest.py': b''},
    {'src/sitecustomize.py': b'import pytest\npytest.fixture = custom\n'},
    {'usercustomize/__init__.py': b'mutate()\n'},
    {'app/__init__.py': b''}, {'app.py': b''}, {'tests/app/__init__.py': b''},
    {'tests/conftest.py': b'import pytest\n@pytest.fixture(autouse=True)\ndef changed():\n    mutate()\n'},
    {'src/app/__init__.py': b'mutate()\n'},
    {'tests/test_aaa.py': b'import app.prod\napp.prod.is_success = other\n'},
])
def test_full_fixture_framework_and_startup_authority_are_required(context):
    assert not projected(run(BEFORE, AFTER, PRODUCTION, context=context))


def test_total_parameter_rows_remain_bounded():
    after = AFTER.replace('[200, 201, 204]', repr([200, 201] + list(range(1000, 1060))))
    tree = ast.parse(after)
    original = ast.dump(tree)
    assert not expand_parametrized_membership(tree)
    assert ast.dump(tree) == original


def test_imported_test_named_callable_is_not_treated_as_an_inert_provider():
    after = AFTER.replace('import is_success', 'import is_success as test_provider').replace('assert is_success(', 'assert test_provider(')
    tree = ast.parse(after)
    original = ast.dump(tree)
    assert not expand_parametrized_membership(tree)
    assert ast.dump(tree) == original

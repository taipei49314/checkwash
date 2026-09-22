"""Unrequested default literal parameters must not hide an oracle rewrite."""
import pytest

from test_issue_expectation_families import run

PRODUCTION = 'def is_even(n):\n    return n % 2 != 0\n'
BEFORE = '''from app.prod import is_even
def test_is_even():
    nums = [0, 2, 3, 4]
    assert all(is_even(n) == (n % 2 == 0) for n in nums)
'''
FIXTURE = '''@pytest.fixture(params=[(0, False), (2, False), (3, True), (4, False)])
def test_data(request):
    return request.param
'''
AFTER = '''import pytest
from app.prod import is_even
''' + FIXTURE + '''@pytest.mark.parametrize("n,expected", [(0, False), (2, False), (3, True), (4, False)])
def test_is_even(n, expected):
    result = is_even(n)
    assert result == expected, f"Expected {expected}, got {result} for n={n}"
'''


def projected(result):
    return any(unit.qualname.startswith('test_concrete_') for unit in result[0].files[0].units)


@pytest.mark.parametrize('after', [AFTER, AFTER.replace('test_data', 'unused_rows'),
    AFTER.replace('def test_data', 'def another_fixture'),
    AFTER.replace('params=[(0, False), (2, False), (3, True), (4, False)])',
                  'params=[(0, False), (2, False), (3, True), (4, False)], ids=["a", "b", "c", "d"])'),
    AFTER.replace('params=[(0, False), (2, False), (3, True), (4, False)])', 'params=(1, "unused", (2, 3)))'),
])
def test_unused_literal_parameter_fixture_keeps_changed_answers_visible(after):
    result = run(BEFORE, after, PRODUCTION)
    assert projected(result)
    assert result[2] == 'block'
    assert len([f for f in result[1] if f.rule == 'EXPECTED_VALUE_CHANGED']) == 4


def test_unused_parameters_preserve_honest_refactor_and_wrong_output_checks():
    after = AFTER.replace('(0, False)', '(0, True)').replace('(2, False)', '(2, True)').replace('(3, True)', '(3, False)').replace('(4, False)', '(4, True)')
    for production in (PRODUCTION, PRODUCTION.replace('!=', '==')):
        assert run(BEFORE, after, production)[2] == 'pass'


@pytest.mark.parametrize('fixture', [
    FIXTURE.replace('params=', 'autouse=True, params='),
    FIXTURE.replace('params=', 'scope="module", params='),
    FIXTURE.replace('params=', 'name="another", params='),
    FIXTURE.replace('params=', 'ids=callback, params='),
    FIXTURE.replace('params=', 'ids=["same", "same", "same", "same"], params='),
    FIXTURE.replace('params=', 'ids=["wrong"], params='),
    FIXTURE.replace('params=', 'params=[1], params='),
    FIXTURE.replace('[(0, False), (2, False), (3, True), (4, False)]', '[]'),
    FIXTURE.replace('[(0, False), (2, False), (3, True), (4, False)]', 'rows'),
    FIXTURE.replace('(0, False)', '([0], False)'),
    FIXTURE.replace('(0, False)', '(callback(), False)'),
    FIXTURE.replace('request.param', 'load_value()'),
    FIXTURE.replace('    return', '    mutate()\n    return'),
    FIXTURE.replace('request):', 'request, another):'),
    FIXTURE.replace('request):', 'request: callback()):'),
    FIXTURE.replace('test_data', 'request'),
])
def test_active_dynamic_or_unsupported_fixture_is_retained(fixture):
    assert not projected(run(BEFORE, AFTER.replace(FIXTURE, fixture), PRODUCTION))


@pytest.mark.parametrize('after', [
    AFTER.replace('def test_is_even(n, expected):', 'def test_is_even(n, expected, test_data):'),
    AFTER.replace('def test_is_even', '@pytest.mark.usefixtures("test_data")\ndef test_is_even'),
    AFTER + '\nalias = test_data\n',
    AFTER.replace(FIXTURE, FIXTURE + FIXTURE),
    AFTER.replace('from app.prod import is_even', 'from app.prod import is_even, test_data'),
])
def test_any_fixture_reference_or_duplicate_withholds_projection(after):
    assert not projected(run(BEFORE, after, PRODUCTION))


@pytest.mark.parametrize('context', [
    {'pytest.py': b''}, {'src/pytest/__init__.py': b''},
    {'tests/conftest.py': b'import pytest\n@pytest.fixture(autouse=True)\ndef setup():\n    mutate()\n'},
    {'sitecustomize.py': b'import pytest\npytest.fixture = lambda *a, **k: callback\n'},
])
def test_framework_startup_must_be_inert(context):
    assert not projected(run(BEFORE, AFTER, PRODUCTION, context=context))


@pytest.mark.parametrize('production', [
    'from tests.test_case import test_data\n' + PRODUCTION,
    PRODUCTION.replace('    return', '    mutate()\n    return'),
])
def test_production_cannot_consume_removed_fixture(production):
    assert not projected(run(BEFORE, AFTER, production))

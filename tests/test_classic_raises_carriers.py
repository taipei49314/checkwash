"""A returned null through a fixture/helper does not retain an exception check."""
import pytest

from test_issue_expectation_families import run

PROD = 'def divide(a, b):\n    return None if b == 0 else a / b\n'
BEFORE = '''from app.prod import divide
def test_zero():
    try:
        divide(1, 0)
        assert False
    except ZeroDivisionError:
        pass
'''
FIXTURE = '''import pytest
from app.prod import divide
@pytest.fixture
def expected():
    return None
def test_zero(expected):
    result = divide(1, 0)
    assert result == expected, f'Expected {expected}, got {result}'
'''
HELPER = '''from app.prod import divide
def check(a, b, expected):
    result = divide(a, b)
    assert result == expected, f'Expected {expected}, got {result}'
def test_zero():
    check(1, 0, None)
'''


@pytest.mark.parametrize('after', [FIXTURE, HELPER])
@pytest.mark.parametrize('comparison', ['==', 'is'])
def test_closed_fixture_and_helper_keep_exception_removal_visible(after, comparison):
    ir, findings, verdict = run(BEFORE, after.replace('== expected', comparison + ' expected'), PROD)
    assert verdict == 'block'
    assert any(f.rule == 'ASSERT_REMOVED' for f in findings)
    assert any(assertion.form == 'raises' for file in ir.files for unit in file.units
               if unit.before for assertion in unit.before.assertions)


@pytest.mark.parametrize('after', [
    FIXTURE.replace('@pytest.fixture', '@pytest.fixture(autouse=True)'),
    FIXTURE.replace('expected', 'request'),
    FIXTURE.replace('return None', 'return callback()'),
    FIXTURE.replace('def expected():', 'def expected(request):'),
    FIXTURE.replace('result = divide', 'callback()\n    result = divide'),
    FIXTURE.replace("got {result}", "got {callback(result)}"),
    FIXTURE.replace("got {result}", "got {result:{callback()}}"),
    FIXTURE.replace('def test_zero(expected):', 'def test_zero(expected, request):'),
    FIXTURE.replace('divide(1, 0)', 'divide(2, 0)'),
    FIXTURE.replace('import pytest', 'import custom as pytest'),
    FIXTURE.replace('def expected():', 'def expected(x=callback()):'),
    HELPER.replace('check(1, 0, None)', 'check(1, 0, expected=None)'),
    HELPER.replace('check(1, 0, None)', 'check(1, callback(), None)'),
    HELPER.replace('result = divide(a, b)', 'a = 9\n    result = divide(a, b)'),
    HELPER.replace('result = divide(a, b)', 'expected = None\n    result = divide(a, b)'),
    HELPER.replace('result = divide(a, b)', 'result = other(a, b)'),
    HELPER.replace('def check(a, b, expected):', '@decorate\ndef check(a, b, expected):'),
    HELPER.replace('def check(a, b, expected):', 'def check(a, b, expected: callback()):'),
    HELPER.replace('check(1, 0, None)', 'check(1, 0, None)\n    callback()'),
    HELPER.replace('def test_zero():', 'def test_zero(check):'),
])
def test_unknown_execution_or_binding_does_not_create_exception_projection(after):
    ir, _, _ = run(BEFORE, after, PROD)
    assert not any(assertion.form == 'raises' for file in ir.files for unit in file.units
                   if unit.before for assertion in unit.before.assertions)


@pytest.mark.parametrize('context', [
    {'pytest.py': b'mark = custom\n'},
    {'tests/conftest.py': b'def pytest_configure():\n    mutate()\n'},
    {'src/app/__init__.py': b'import pytest\npytest.fixture = custom\n'},
    {'app/prod.py': PROD.encode()},
])
def test_ambiguous_import_or_startup_withholds_carrier_proof(context):
    ir, _, _ = run(BEFORE, FIXTURE, PROD, context=context)
    assert not any(assertion.form == 'raises' for file in ir.files for unit in file.units
                   if unit.before for assertion in unit.before.assertions)


@pytest.mark.parametrize('name', ['setup_module', 'setup_function', 'pytestmark', 'pytest_plugins',
                                 'pytest_generate_tests', 'setUpModule', 'tearDownModule'])
def test_imported_framework_control_cannot_establish_an_executed_old_oracle(name):
    ir, _, _ = run(BEFORE.replace('divide', name), HELPER.replace('divide', name), PROD.replace('divide', name))
    assert not any(assertion.form == 'raises' for file in ir.files for unit in file.units
                   if unit.before for assertion in unit.before.assertions)

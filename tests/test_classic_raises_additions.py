"""Additional literal rows cannot hide the removed original exception oracle."""
import pytest

from checkwash.frontends.python.frontend import parse_python
from test_issue_expectation_families import run
from test_classic_raises_carriers import BEFORE, PROD

AFTER = '''from app.prod import divide
import pytest
def test_zero():
    result = divide(1, 0)
    assert result is None, f'Expected None, got {result}'
@pytest.mark.parametrize('a, b, expected', [(2, 2, 1.0), (5, -3, -1.6666666666666667), (0, 1, 0.0), (-1, -1, 1.0)])
def test_more(a, b, expected):
    result = divide(a, b)
    assert result == expected, f'Expected {expected}, got {result}'
'''


def projected(after=AFTER, *, context=None, production=PROD):
    return run(BEFORE, after, production, context=context)


def has_exception(ir):
    return any(a.form == 'raises' for file in ir.files for unit in file.units
               if unit.before for a in unit.before.assertions)


@pytest.mark.parametrize('after', [AFTER, AFTER.replace('result = divide(a, b)\n    assert result', 'assert divide(a, b)')])
def test_added_literal_rows_retain_exception_removal_and_native_units(after):
    # A direct call message cannot reference the removed capture.
    after = after.replace("f'Expected {expected}, got {result}'", "'unexpected result'")
    ir, findings, verdict = projected(after)
    assert has_exception(ir) and verdict == 'block'
    assert any(f.rule == 'ASSERT_REMOVED' for f in findings)
    original = next(u for u in parse_python(after.encode(), True).units if u.qualname == 'test_more')
    preserved = next(u for file in ir.files for u in file.units if u.qualname == 'test_more')
    assert preserved.after == original.side


@pytest.mark.parametrize('after', [
    AFTER.replace("import pytest", 'import custom as pytest'),
    AFTER.replace("[(2, 2, 1.0), (5, -3, -1.6666666666666667), (0, 1, 0.0), (-1, -1, 1.0)]", '[]'),
    AFTER.replace('(2, 2, 1.0)', 'pytest.param(2, 2, 1.0, marks=pytest.mark.skip)'),
    AFTER.replace("def test_more(a, b, expected):", 'def test_more(a, b, expected=callback()):'),
    AFTER.replace("def test_more(a, b, expected):", 'def test_more(a, b, expected: callback()):'),
    AFTER.replace("def test_more(a, b, expected):", 'def test_more(a, b, expected, request):'),
    AFTER.replace('expected', 'request'),
    AFTER.replace('def test_more', 'def setup_module'),
    AFTER.replace('result = divide(a, b)', 'divide = callback()\n    result = divide(a, b)'),
    AFTER.replace('result = divide(a, b)', 'result = other(a, b)'),
    AFTER.replace('result = divide(a, b)', 'result = divide(callback(), b)'),
    AFTER.replace('result = divide(a, b)', 'global divide\n    result = divide(a, b)'),
    AFTER.replace('result = divide(a, b)', 'result = divide(a, b=b)'),
    AFTER.replace('== expected', '== callback()'),
    AFTER.replace('== expected', '== expected == 1'),
    AFTER.replace("got {result}'\n", "got {callback(result)}'\n"),
    AFTER.replace("got {result}'\n", "got {result:{callback()}}'\n"),
    AFTER.replace("[(2, 2, 1.0)", "[(callback(), 2, 1.0)"),
    AFTER + '\ndef pytest_configure():\n    mutate()\n',
    AFTER + '\npytestmark = pytest.mark.skip\n',
    AFTER + '\nfrom app.other import mutate\n',
    AFTER + '\ndef test_more():\n    pass\n',
])
def test_unproved_extra_test_does_not_create_exception_projection(after):
    assert not has_exception(projected(after)[0])


@pytest.mark.parametrize('context', [
    {'pytest.py': b'mark = custom\n'},
    {'tests/conftest.py': b'def pytest_configure():\n    mutate()\n'},
    {'src/app/__init__.py': b'import pytest\npytest.mark.parametrize = custom\n'},
    {'app/prod.py': PROD.encode()},
])
def test_startup_and_import_authority_are_required(context):
    assert not has_exception(projected(context=context)[0])


def test_custom_return_cannot_supply_safe_message_formatting():
    production = 'class Result:\n    def __format__(self, spec):\n        mutate()\n        return ""\ndef divide(a,b):\n    return Result()\n'
    assert not has_exception(projected(production=production)[0])

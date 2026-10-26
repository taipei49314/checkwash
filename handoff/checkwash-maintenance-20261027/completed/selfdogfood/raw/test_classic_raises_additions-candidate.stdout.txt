"""Additional literal rows cannot hide the removed original exception oracle."""
from dataclasses import fields
import re

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
    # D-179 enriches engine IR after the standalone frontend returns its side.
    # Preserve every native field, and check enrichment separately without
    # deleting or blanking the new authority fields on either object.
    enrichment = {"oracle_context", "oracle_assertion_contexts"}
    native_fields = [field.name for field in fields(original.side) if field.name not in enrichment]
    assert len(native_fields) == 17
    assert {name: getattr(preserved.after, name) for name in native_fields} == {
        name: getattr(original.side, name) for name in native_fields
    }
    assert original.side.oracle_context == ""
    assert original.side.oracle_assertion_contexts == {}
    assert re.fullmatch(r"[0-9a-f]{64}", preserved.after.oracle_context)
    assert original.side.param_cases == 4
    expected_keys = {f"{assertion.id}@{row}" for assertion in original.side.assertions
                     for row in range(original.side.param_cases)}
    assert set(preserved.after.oracle_assertion_contexts) == expected_keys
    assert all(re.fullmatch(r"[0-9a-f]{64}", value)
               for value in preserved.after.oracle_assertion_contexts.values())


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


@pytest.mark.parametrize('after', [AFTER, AFTER.split('@pytest.mark.parametrize')[0]])
def test_duplicate_keyword_compilation_error_cannot_supply_exception_evidence(after):
    before = BEFORE.replace('divide(1, 0)', 'divide(a=1, a=1)')
    after = after.replace('divide(1, 0)', 'divide(a=1, a=1)')
    for source in (before, after):
        with pytest.raises(SyntaxError, match='keyword argument repeated'):
            compile(source, '<test>', 'exec')
    assert not has_exception(run(before, after, PROD)[0])

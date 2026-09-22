"""Runtime type equality retains its real predicate and existing shape strength."""
import pytest

from checkwash.ir import strength as S
from test_issue_expectation_families import run

PROD = 'def identity(value):\n    return value + 1\n'
BEFORE = '''from app.prod import identity
class Checks:
    def test_value(self):
        assert identity(3) == 3
class TestId(Checks):
    pass
class TestDummy:
    def test_ok(self):
        assert True
'''
HELPER = 'def check(actual, expected):\n    assert type(actual) == type(expected)\n'
AFTER = BEFORE.replace('assert identity(3) == 3', 'check(identity(3), 3)') + HELPER


def shapes(ir, side='after'):
    return [assertion for file in ir.files for unit in file.units
            if getattr(unit, side) is not None for assertion in getattr(unit, side).assertions
            if assertion.form == 'type_shape']


@pytest.mark.parametrize('operator', ['==', 'is', '!=', 'is not'])
@pytest.mark.parametrize('helper', [True, False])
def test_type_comparison_weakening_uses_existing_shape_level_and_preserves_text(operator, helper):
    after = AFTER if helper else BEFORE.replace('identity(3) == 3', 'type(identity(3)) == type(3)')
    after = after.replace(') == type(', ') ' + operator + ' type(')
    ir, findings, verdict = run(BEFORE, after, PROD)
    found = shapes(ir)
    assert len(found) == 1 and found[0].strength == S.TYPE_SHAPE
    assert operator in found[0].text and 'type(' in found[0].text
    assert verdict == 'block'
    assert any(item.rule == 'ASSERT_WEAKENED' and item.severity == 'high' for item in findings)


def test_type_only_helper_to_native_shape_is_honest_and_type_to_exact_strengthens():
    native = BEFORE.replace('identity(3) == 3', 'type(identity(3)) == type(3)')
    ir, findings, verdict = run(AFTER, native, PROD)
    assert len(shapes(ir, 'before')) == len(shapes(ir)) == 1
    assert verdict == 'pass' and not findings
    ir, findings, verdict = run(AFTER, BEFORE, PROD)
    assert shapes(ir, 'before') and not shapes(ir)
    assert verdict == 'pass' and not findings


def test_exact_helper_to_type_helper_weakening_retains_actual_assertion_span():
    before = AFTER.replace('type(actual) == type(expected)', 'actual == expected')
    ir, findings, verdict = run(before, AFTER, PROD)
    assert verdict == 'block' and shapes(ir)
    assertion = shapes(ir)[0]
    assert AFTER.encode()[assertion.span[0]:assertion.span[1]].decode().strip() == assertion.text


@pytest.mark.parametrize('change', [
    ('from app.prod import identity', 'from app.prod import identity, type'),
    ('from app.prod import identity', 'from app.prod import identity\nfrom other import anything'),
    ('def check(actual, expected):', 'def check(actual, type):'),
    ('def check(actual, expected):', '@decorate\ndef check(actual, expected):'),
    ('def check(actual, expected):', 'def check(actual, expected=3):'),
    ('def check(actual, expected):', 'def check(actual: callback(), expected):'),
    ('def check(actual, expected):', 'def check(actual, expected):\n    type = custom'),
    ('type(actual) == type(expected)', 'type(actual) == type(expected) == int'),
    ('type(actual) == type(expected)', 'type(actual, expected) == type(expected)'),
    ('type(actual) == type(expected)', 'type(actual) == type(object=expected)'),
    ('type(actual) == type(expected)', 'custom.type(actual) == custom.type(expected)'),
    ('type(actual) == type(expected)', 'type(actual) == expected'),
    ('check(identity(3), 3)', 'check(identity(3), expected=3)'),
    ('check(identity(3), 3)', 'check(identity(3), callback())'),
    ('check(identity(3), 3)', 'check(identity(3), 3)\n        mutate()'),
    ('check(identity(3), 3)', 'check(identity(value=3, value=3), 3)'),
    ('class TestId(Checks):', 'class TestId(Checks, Unknown):'),
    ('class TestId(Checks):', '@decorate\nclass TestId(Checks):'),
    ('class Checks:', 'class Checks:\n    def __init__(self):\n        pass'),
    ('def test_value(self):', 'def test_value(self, type):'),
    ('def test_value(self):', '@property\n    def test_value(self):'),
    ('from app.prod import identity', 'from app.prod import identity\ntype = lambda x: x'),
    ('from app.prod import identity', 'from app.prod import identity\nimport builtins\nbuiltins.type = lambda x: x'),
])
def test_unknown_type_helper_and_execution_authority_withholds_classification(change):
    ir, _, _ = run(BEFORE, AFTER.replace(*change), PROD)
    assert not shapes(ir)


@pytest.mark.parametrize('production', [
    'def identity(value):\n    return callback(value)\n',
    'import builtins\ndef identity(value):\n    builtins.type = lambda x: x\n    return value + 1\n',
    'class Custom:\n    pass\ndef identity(value):\n    return Custom()\n',
    'def identity(value):\n    from tests.test_case import check\n    return value + 1\n',
])
def test_unknown_or_mutating_production_withholds_builtin_type_proof(production):
    ir, _, _ = run(BEFORE, AFTER, production)
    assert not shapes(ir)


@pytest.mark.parametrize('context', [
    {'src/sitecustomize.py': b'import builtins\nbuiltins.type = lambda x: x\n'},
    {'tests/conftest.py': b'import builtins\nbuiltins.type = lambda x: x\n'},
    {'tests/test_sibling.py': b'def test_mutate():\n    import builtins\n    builtins.type = lambda x: x\n'},
    {'pytest.py': b''}, {'src/pytest/__init__.py': b''},
    {'app/__init__.py': b''},
    {'pytest.ini': b'[pytest]\naddopts = --assert=plain\n'},
    {'pytest.ini': b'[pytest]\ntestpaths=tests/other\n',
     'tests/other/test_padding.py': b'def test_ok():\n    assert True\n'},
])
def test_startup_and_source_resolution_authority_is_required(context):
    ir, _, _ = run(BEFORE, AFTER, PROD, context=context)
    assert not shapes(ir)

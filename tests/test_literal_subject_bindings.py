"""One literal input local can accompany complete table oracle preservation."""
import pytest

from checkwash.frontends.python import table_oracles
from test_issue_expectation_families import run

PROD = 'def success(code):\n    return code in (200, 201, 204)\n'
BEFORE = '''from app.prod import success
def test_only_200():
    assert success(200) == True
    assert success(201) == False
'''
AFTER = '''from app.prod import success
def test_valid_codes():
    cases = [(200, True), (201, True), (204, True)]
    for code, expected in cases:
        assert success(code) == expected, f'Code {code}'
def test_invalid_code():
    """A new negative row follows the original concrete rows."""
    invalid_code = 404
    assert success(invalid_code) == False, f'Code {invalid_code}'
'''


def projected(ir):
    return any(u.qualname.startswith('test_concrete_') for f in ir.files for u in f.units)


@pytest.mark.parametrize('changed', [False, True])
def test_preserved_literal_input_does_not_hide_answer_change_in_another_row(changed):
    after = AFTER if changed else AFTER.replace('(201, True)', '(201, False)')
    ir, findings, verdict = run(BEFORE, after, PROD)
    assert projected(ir)
    assert verdict == ('block' if changed else 'pass')
    assert bool([f for f in findings if f.rule == 'EXPECTED_VALUE_CHANGED' and f.severity == 'high']) == changed


@pytest.mark.parametrize('after', [
    AFTER.replace('invalid_code = 404', 'invalid_code = callback()'),
    AFTER.replace('invalid_code = 404', 'invalid_code = 404\n    mutate()'),
    AFTER.replace('success(invalid_code)', 'success(callback(invalid_code))'),
    AFTER.replace('success(invalid_code)', 'success(other)'),
    AFTER.replace('success(invalid_code)', 'other(invalid_code)'),
    AFTER.replace('success(invalid_code)', 'success(code=invalid_code, code=invalid_code)'),
    AFTER.replace('success(invalid_code)', 'success(**invalid_code)'),
    AFTER.replace('success(invalid_code)', 'success(*invalid_code)'),
    AFTER.replace('== False', '== invalid_code'),
    AFTER.replace('invalid_code', 'success'),
    AFTER.replace("f'Code {invalid_code}'", "f'Code {callback(invalid_code)}'"),
    AFTER.replace("f'Code {invalid_code}'", "f'Code {invalid_code:{callback()}}'"),
    AFTER.replace('def test_invalid_code():', 'def test_invalid_code(request):'),
    AFTER.replace('def test_invalid_code():', '@pytest.mark.skip\ndef test_invalid_code():'),
    AFTER.replace('def test_invalid_code():', 'def test_invalid_code(x=callback()):'),
])
def test_unknown_input_bindings_and_callbacks_do_not_project(after):
    assert not projected(run(BEFORE, after, PROD)[0])


@pytest.mark.parametrize('context', [
    {'tests/conftest.py': b'def pytest_configure():\n    mutate()\n'},
    {'src/sitecustomize.py': b'import builtins\nbuiltins.len = custom\n'},
    {'src/app/__init__.py': b'from external import install\ninstall()\n'},
    {'app/prod.py': PROD.encode()},
])
def test_startup_and_import_authority_remain_required(context):
    assert not projected(run(BEFORE, AFTER, PROD, context=context)[0])


@pytest.mark.parametrize('production', [
    'def success(code):\n    mutate()\n    return True\n',
    'def success(code):\n    return external(code)\n',
    'class Result:\n    def __bool__(self):\n        mutate()\n        return True\ndef success(code):\n    return Result()\n',
])
def test_complete_production_purity_is_required(production):
    assert not projected(run(BEFORE, AFTER, production)[0])


@pytest.mark.parametrize('change', [lambda s: s.replace('404', '400'),
                                    lambda s: s.replace('invalid_code', 'status_code')])
def test_same_carrier_input_contract_is_byte_identical_to_existing_handling(change, monkeypatch):
    before = AFTER
    after = change(before)
    current = run(before, after, PROD)
    monkeypatch.setattr(table_oracles, 'expand_literal_subject_bindings', lambda *args: set())
    assert current == run(before, after, PROD)


def test_changed_original_input_cannot_obtain_row_coverage_credit():
    assert not projected(run(BEFORE, AFTER.replace('(200, True)', '(202, True)'), PROD)[0])


def test_duplicate_original_obligation_cannot_disappear():
    before = BEFORE.replace('    assert success(200) == True', '    assert success(200) == True\n    assert success(200) == True')
    assert not projected(run(before, AFTER, PROD)[0])


@pytest.mark.parametrize('literal', ['[]', '{}', '[1]', '(1,)', '"value"'])
def test_repeated_local_input_cannot_duplicate_object_allocation(literal):
    before = f'from app.prod import same\ndef test_alias():\n    value = {literal}\n    assert same(value, value) == True\n'
    after = f'from app.prod import same\ndef test_alias():\n    assert same({literal}, {literal}) == True\n'
    production = 'def same(left, right):\n    return left is not right\n'
    assert not projected(run(before, after, production)[0])


def test_nested_repeated_reference_cannot_duplicate_a_mutable_input():
    before = 'from app.prod import same\ndef test_alias():\n    value = []\n    assert same([value, value]) == True\n'
    after = 'from app.prod import same\ndef test_alias():\n    assert same([[], []]) == True\n'
    production = 'def same(values):\n    return values[0] is not values[1]\n'
    assert not projected(run(before, after, production)[0])

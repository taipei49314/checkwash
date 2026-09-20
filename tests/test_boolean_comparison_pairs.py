"""Boolean Eq-to-Is strengthening pairs only after return-type authority."""
import pytest

from test_issue_expectation_families import run

PROD = 'def success(code):\n    return code in (200, 201, 204)\n'
BEFORE = '''from app.prod import success
def test_ok():
    assert success(200) == True
def test_not_ok():
    assert success(201) == False
'''
AFTER = '''import pytest
from app.prod import success
@pytest.mark.parametrize('code, expected', [(200, True), (201, False)])
def test_success(code, expected):
    assert success(code) is expected
'''


def projected(ir):
    return any(unit.qualname.startswith('test_concrete_') for file in ir.files for unit in file.units)


@pytest.mark.parametrize('changed', [False, True])
def test_exact_boolean_result_keeps_answer_changes_visible(changed):
    before, after = BEFORE, AFTER
    if changed:
        after = after.replace('(201, False)', '(201, True)')
    ir, findings, verdict = run(before, after, PROD)
    assert projected(ir)
    assert verdict == ('block' if changed else 'pass')
    assert bool([f for f in findings if f.rule == 'EXPECTED_VALUE_CHANGED' and f.severity == 'high']) == changed


@pytest.mark.parametrize('expression', ['code == 200', 'not code', 'True', 'False',
    'code > 0 and code < 300', 'True if code else False', '(code == 200) or (code == 204)'])
def test_complete_boolean_return_grammar(expression):
    ir, _, _ = run(BEFORE, AFTER, f'def success(code):\n    return {expression}\n')
    assert projected(ir)


@pytest.mark.parametrize('production', [
    'def success(code):\n    return 1\n',
    'def success(code):\n    return 0\n',
    'def success(code):\n    return code\n',
    'def success(code):\n    return None\n',
    'def success(code):\n    return code and True\n',
    'def success(code):\n    return True if code else 1\n',
    'def success(code):\n    if code:\n        return True\n',
    'def success(code):\n    if code:\n        return 1\n    return False\n',
    'def success(code):\n    return callback(code)\n',
    'class Value:\n    def __eq__(self, other):\n        return True\ndef success(code):\n    return Value()\n',
    'import builtins\ndef success(code):\n    builtins.len = callback\n    return True\n',
])
def test_numeric_truthy_custom_and_unclosed_results_do_not_pair(production):
    assert not projected(run(BEFORE, AFTER, production)[0])


@pytest.mark.parametrize('after', [
    AFTER.replace('(201, False)', '(202, False)'),
    AFTER.replace('[(200, True), (201, False)]', '[(201, False), (200, True)]'),
    AFTER.replace('[(200, True), (201, False)]', '[(200, True)]'),
    AFTER.replace(' is expected', ' is not expected'),
    AFTER.replace('(201, False)', '(201, 0)'),
    AFTER.replace('success(code)', 'other(code)'),
    AFTER.replace("[(200, True), (201, False)]", "[pytest.param(200, True, marks=pytest.mark.skip), (201, False)]"),
])
def test_input_operator_count_and_collection_boundaries_remain(after):
    assert not projected(run(BEFORE, after, PROD)[0])


@pytest.mark.parametrize('context', [
    {'pytest.py': b'mark = custom\n'},
    {'tests/conftest.py': b'def pytest_configure():\n    mutate()\n'},
    {'src/app/__init__.py': b'from external import install\ninstall()\n'},
    {'app/__init__.py': b'from external import install\ninstall()\n'},
    {'app/prod.py': PROD.encode()},
])
def test_complete_import_and_startup_authority_are_required(context):
    assert not projected(run(BEFORE, AFTER, PROD, context=context)[0])


def test_duplicate_original_oracle_cannot_disappear():
    before = BEFORE.replace('def test_not_ok():', 'def test_duplicate():\n    assert success(200) == True\ndef test_not_ok():')
    assert not projected(run(before, AFTER, PROD)[0])

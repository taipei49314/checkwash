"""Boolean Eq-to-Is strengthening retains return-type and carrier bounds."""
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


@pytest.mark.parametrize('production', [
    'def success(code):\n    return code in (200, 201, 204)\n',
    'def success(code):\n    return code > 0 and code < 300\n',
    'def success(code):\n    return not code\n',
    'def success(code):\n    return True if code else False\n',
])
def test_complete_boolean_return_grammar_pairs(production):
    ir, _, verdict = run(BEFORE, AFTER, production)
    assert projected(ir)
    assert verdict == 'pass'


@pytest.mark.parametrize('method', ['startswith("2")', 'isdigit()'])
def test_builtin_string_boolean_results_keep_strengthening_support(method):
    before = BEFORE.replace('success(200)', 'success("200")').replace('success(201)', 'success("x")')
    after = AFTER.replace('(200, True)', '("200", True)').replace('(201, False)', '("x", False)')
    ir, findings, verdict = run(before, after, f'def success(code):\n    return code.{method}\n')
    assert projected(ir) and verdict == 'pass' and not findings


@pytest.mark.parametrize('production', [
    'def success(code):\n    return 1\n',
    'def success(code):\n    return code\n',
    'def success(code):\n    return None\n',
    'def success(code):\n    return code and True\n',
    'def success(code):\n    return True if code else 1\n',
    'def success(code):\n    if code:\n        return 1\n    return False\n',
    'def success(code):\n    return callback(code)\n',
    'def success(code):\n    return code.upper()\n',
    'class Value:\n    def __eq__(self, other):\n        return True\ndef success(code):\n    return Value()\n',
])
def test_unproved_results_do_not_pair(production):
    assert not projected(run(BEFORE, AFTER, production)[0])


@pytest.mark.parametrize('after', [
    AFTER.replace('(201, False)', '(202, False)'),
    AFTER.replace('[(200, True), (201, False)]', '[(201, False), (200, True)]'),
    AFTER.replace('[(200, True), (201, False)]', '[(200, True)]'),
    AFTER.replace(' is expected', ' is not expected'),
    AFTER.replace('success(code)', 'other(code)'),
    AFTER.replace("[(200, True), (201, False)]", "[pytest.param(200, True, marks=pytest.mark.skip), (201, False)]"),
])
def test_input_operator_count_and_collection_boundaries_remain(after):
    assert not projected(run(BEFORE, after, PROD)[0])


def test_none_expectations_keep_their_ordinary_owner():
    before = BEFORE.replace(' == True', ' == None').replace(' == False', ' == None')
    after = AFTER.replace('True)', 'None)').replace('False)', 'None)')
    assert not projected(run(before, after, PROD)[0])


def test_duplicate_original_oracle_cannot_disappear():
    before = BEFORE.replace('def test_not_ok():', 'def test_duplicate():\n    assert success(200) == True\ndef test_not_ok():')
    assert not projected(run(before, AFTER, PROD)[0])

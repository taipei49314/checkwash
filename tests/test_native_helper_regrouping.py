"""Regrouping may contain a fully checked positional assertion-helper call."""
import pytest

from test_issue_expectation_families import run


PROD = 'def increment(value):\n    return value + 1\n'
BEFORE = '''from app.prod import increment
def test_first():
    assert increment(1) == 2
def test_second():
    assert increment(2) == 3
'''
AFTER = '''from app.prod import increment
def test_combined():
    check(increment(1), 2)
    assert increment(2) == 3
def check(actual, expected):
    assert actual == expected
'''


def projected(ir):
    return any(unit.qualname.startswith('test_concrete_') for file in ir.files for unit in file.units)


@pytest.mark.parametrize('body', [
    '    check(increment(1), 2)\n    assert increment(2) == 3\n',
    '    assert increment(1) == 2\n    check(increment(2), 3)\n',
    '    check(increment(1), 2)\n    check(increment(2), 3)\n',
    '    check(increment(2), 3)\n    assert increment(1) == 2\n',
])
def test_already_proved_positional_helpers_can_move_with_other_pure_oracles(body):
    after = AFTER[:AFTER.index('    check(')] + body + AFTER[AFTER.index('def check('):]
    ir, findings, verdict = run(BEFORE, after, PROD)
    assert projected(ir) and verdict == 'pass' and not findings


def test_regrouped_helper_answer_change_remains_visible():
    ir, findings, verdict = run(BEFORE, AFTER.replace('increment(1), 2', 'increment(1), 0'), PROD)
    assert projected(ir) and verdict == 'block'
    assert any(f.rule == 'EXPECTED_VALUE_CHANGED' for f in findings)


@pytest.mark.parametrize('after', [
    AFTER.replace('assert actual == expected', 'assert expected == expected'),
    AFTER.replace('assert actual == expected', 'assert True'),
    AFTER.replace('assert actual == expected', 'mutate()\n    assert actual == expected'),
    AFTER.replace('    check(increment(1), 2)', '    increment(1)'),
    AFTER.replace('    check(increment(1), 2)', '    increment(1) == 2'),
    AFTER.replace('    check(increment(1), 2)', '    callback()\n    check(increment(1), 2)'),
    AFTER.replace('increment(1), 2', 'increment(2), 3'),
    AFTER.replace('    assert increment(2) == 3\n', ''),
    AFTER.replace('def test_combined():', 'def test_combined(check):'),
    AFTER.replace('def check(actual, expected):', '@decorate\ndef check(actual, expected):'),
    AFTER + '\ncheck = other\n',
])
def test_only_complete_helper_assertions_and_exact_original_input_multiplicity_qualify(after):
    ir, _, _ = run(BEFORE, after, PROD)
    assert not projected(ir)


@pytest.mark.parametrize('production', [
    'def increment(value):\n    return callback(value)\n',
    'def increment(value):\n    global changed\n    changed = value\n    return value + 1\n',
    'def increment(value):\n    from tests.test_case import check\n    return value + 1\n',
    'class Value:\n    def __eq__(self, other):\n        return True\ndef increment(value):\n    return Value()\n',
])
def test_unproved_subject_cannot_gain_helper_regrouping(production):
    ir, _, _ = run(BEFORE, AFTER, production)
    assert not projected(ir)

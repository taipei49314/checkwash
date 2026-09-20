"""Complete keyword binding preserves a helper's actual checked assertion."""
import pytest

from test_issue_expectation_families import run


PRODUCTION = 'def increment(value):\n    return value + 1\n'
BEFORE = '''from app.prod import increment
def test_first():
    assert increment(1) == 2
def test_second():
    assert increment(2) == 3
'''
AFTER = '''from app.prod import increment
def test_first():
    check(actual=increment(1), expected=2)
def test_second():
    assert increment(2) == 3
def check(actual, expected):
    assert actual == expected
'''


def projected(ir):
    return any(unit.qualname.startswith('test_concrete_') for file in ir.files for unit in file.units)


@pytest.mark.parametrize('arguments', ['actual=increment(1), expected=2',
    'expected=2, actual=increment(1)', 'increment(1), expected=2'])
@pytest.mark.parametrize('grouped', [False, True])
def test_keyword_order_and_mixed_arguments_retain_complete_helpers(arguments, grouped):
    after = AFTER.replace('actual=increment(1), expected=2', arguments)
    if grouped:
        after = after.replace('def test_second():\n', '')
    ir, findings, verdict = run(BEFORE, after, PRODUCTION)
    assert projected(ir) and verdict == 'pass' and not findings
    assert len(ir.files[0].units) == 2


def test_keyword_helper_answer_rewrite_remains_detected():
    ir, findings, verdict = run(BEFORE, AFTER.replace('expected=2', 'expected=0'), PRODUCTION)
    assert projected(ir) and verdict == 'block'
    assert any(f.rule == 'EXPECTED_VALUE_CHANGED' and f.severity == 'high' for f in findings)


def test_existing_keyword_helper_preserves_expectation_provenance_owner():
    ir, findings, verdict = run(AFTER, AFTER.replace('expected=2', 'expected=0'), PRODUCTION)
    assert not projected(ir) and verdict == 'block'
    assert any(f.rule == 'EXPECTATION_DEFINITION_CHANGED' for f in findings)


@pytest.mark.parametrize('arguments', ['actual=increment(1)',
    'actual=increment(1), other=2', 'increment(1), actual=2',
    'actual=increment(1), expected=2, expected=2',
    'actual=increment(1), expected=2, other=3',
    '**values', '*values', 'actual=increment(1), expected=callback()',
    'actual=callback(), expected=2'])
def test_unproved_or_invalid_argument_binding_cannot_gain_credit(arguments):
    ir, _, _ = run(BEFORE, AFTER.replace('actual=increment(1), expected=2', arguments), PRODUCTION)
    assert not projected(ir)


@pytest.mark.parametrize('replacement', ['assert True', 'assert expected == expected',
    'assert actual == actual', 'assert actual == expected\n    mutate()',
    'mutate()\n    assert actual == expected'])
def test_side_predicate_or_extra_helper_effect_is_not_the_actual_oracle(replacement):
    ir, _, _ = run(BEFORE, AFTER.replace('assert actual == expected', replacement), PRODUCTION)
    assert not projected(ir)


@pytest.mark.parametrize('after', [
    AFTER.replace('def test_first():', 'def test_first(check):'),
    AFTER.replace('def check(actual, expected):', '@decorate\ndef check(actual, expected):'),
    AFTER.replace('def check(actual, expected):', 'def check(actual, expected=2):'),
    AFTER.replace('def check(actual, expected):', 'def check(actual, expected: callback()):'),
    AFTER + '\ncheck = external\n',
    AFTER.replace('    check(actual', '    check = external\n    check(actual'),
    AFTER.replace('def test_second():\n    assert increment(2) == 3\n', ''),
])
def test_runtime_binding_and_complete_original_coverage_are_required(after):
    ir, _, _ = run(BEFORE, after, PRODUCTION)
    assert not projected(ir)


@pytest.mark.parametrize('production', [
    'def increment(value):\n    return callback(value)\n',
    'def increment(value):\n    from tests.test_case import check\n    return value + 1\n',
    'def increment(value):\n    global changed\n    changed = value\n    return value + 1\n',
    'class Result:\n    def __eq__(self, other):\n        return True\ndef increment(value):\n    return Result()\n',
])
def test_keyword_subjects_require_closed_pure_source_on_both_sides(production):
    ir, _, _ = run(BEFORE, AFTER, production)
    assert not projected(ir)


def test_repeated_table_cell_cannot_acquire_independent_argument_identity():
    after = '''from app.prod import increment
def test_first():
    for value in [1, 2]:
        check(actual=value, expected=value)
def check(actual, expected):
    assert increment(actual) == expected
'''
    ir, _, _ = run(BEFORE, after, PRODUCTION)
    assert not projected(ir)


@pytest.mark.parametrize('context', [
    {'tests/conftest.py': b'def pytest_configure():\n    mutate()\n'},
    {'src/app/__init__.py': b'callback()\n'},
    {'pytest.ini': b'[pytest]\naddopts=-x\n'},
])
def test_helper_grouping_requires_default_inert_startup(context):
    ir, _, _ = run(BEFORE, AFTER, PRODUCTION, context=context)
    assert not projected(ir)

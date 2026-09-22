"""Pure native merges/splits preserve complete concrete assertion multiplicity."""
import pytest

from test_issue_expectation_families import run


PRODUCTION = 'def increment(x):\n    return x + 1\n'
BEFORE = '''from app.prod import increment
def test_first():
    assert increment(1) == 2
def test_second():
    assert increment(2) == 3
def test_third():
    assert increment(3) == 4
'''
AFTER = '''from app.prod import increment
def test_combined():
    assert increment(3) == 4
    assert increment(1) == 2
    assert increment(2) == 3
'''


def projected(ir):
    return any(unit.qualname.startswith('test_concrete_') for file in ir.files for unit in file.units)


@pytest.mark.parametrize('before,after', [(BEFORE, AFTER), (AFTER, BEFORE),
    (BEFORE, AFTER.replace('    assert increment(1)', 'def test_tail():\n    assert increment(1)'))])
def test_native_merge_split_and_regroup_preserve_complete_oracles(before, after):
    ir, findings, verdict = run(before, after, PRODUCTION)
    assert projected(ir)
    assert verdict == 'pass' and not findings
    assert len(ir.files[0].units) == 3


def test_changed_expected_value_remains_high_even_when_native_tests_merge():
    ir, findings, verdict = run(BEFORE, AFTER.replace('increment(2) == 3', 'increment(2) == 0'), PRODUCTION)
    assert projected(ir)
    assert verdict == 'block'
    assert any(f.rule == 'EXPECTED_VALUE_CHANGED' and f.severity == 'high' for f in findings)


@pytest.mark.parametrize('after', [
    AFTER.replace('    assert increment(2) == 3\n', ''),
    AFTER.replace('increment(2) == 3', 'increment(1) == 2'),
    AFTER.replace('increment(2) == 3', 'increment(4) == 5'),
    AFTER + 'def test_padding():\n    assert increment(5) == 6\n',
    AFTER.replace('    assert increment(1)', '    mutate()\n    assert increment(1)'),
    AFTER.replace('== 2', '== 2, callback()'),
    AFTER.replace('increment(1)', 'increment(value)'),
    AFTER.replace('def test_combined():', '@decorator\ndef test_combined():'),
    AFTER.replace('def test_combined():', 'def test_combined(increment):'),
])
def test_missing_inputs_multiplicity_or_dynamic_body_withhold_regrouping(after):
    ir, _, _ = run(BEFORE, after, PRODUCTION)
    assert not projected(ir)


def test_duplicate_subject_assertions_cannot_be_deduplicated_during_merge():
    before = BEFORE + 'def test_first_again():\n    assert increment(1) == 2\n'
    ir, _, verdict = run(before, AFTER, PRODUCTION)
    assert not projected(ir)
    assert verdict == 'block'


def test_duplicate_subjects_keep_their_distinct_literal_answer_obligations():
    before = '''from app.prod import increment
def test_first():
    assert increment(1) == 2
def test_other_answer():
    assert increment(1) == 5
'''
    after = '''from app.prod import increment
def test_combined():
    assert increment(1) == 2
    assert increment(1) == 2
'''
    ir, findings, verdict = run(before, after, PRODUCTION)
    assert projected(ir)
    assert verdict == 'block'
    assert any(f.rule == 'EXPECTED_VALUE_CHANGED' for f in findings)


@pytest.mark.parametrize('production', [
    'count = 0\ndef increment(x):\n    global count\n    count += 1\n    return x + count\n',
    'def increment(x):\n    return callback(x)\n',
    'def increment(x):\n    from tests.test_case import test_first\n    return x + 1\n',
    'class Answer:\n    def __eq__(self, other):\n        return True\ndef increment(x):\n    return Answer()\n',
])
def test_unknown_or_effectful_subject_does_not_gain_regrouping(production):
    ir, _, _ = run(BEFORE, AFTER, production)
    assert not projected(ir)


@pytest.mark.parametrize('context', [
    {'tests/conftest.py': b'import pytest\n@pytest.fixture(autouse=True)\ndef reset():\n    mutate()\n'},
    {'src/app/__init__.py': b'callback()\n'},
    {'pytest.ini': b'[pytest]\naddopts = -x\n'},
])
def test_changed_failure_barriers_require_default_inert_execution(context):
    ir, _, _ = run(BEFORE, AFTER, PRODUCTION, context=context)
    assert not projected(ir)


def test_literal_diagnostic_is_retained_without_callback_dispatch():
    ir, findings, verdict = run(BEFORE, AFTER.replace('== 2', '== 2, "unexpected result"'), PRODUCTION)
    assert projected(ir)
    assert verdict == 'pass' and not findings

"""Only literal None return metadata can join the closed pure oracle proof."""
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
def test_first() -> None:
    assert increment(1) == 2
    assert increment(2) == 3
'''


def projected(ir):
    return any(unit.qualname.startswith('test_concrete_') for file in ir.files for unit in file.units)


@pytest.mark.parametrize('before,after', [(BEFORE, AFTER), (AFTER, BEFORE)])
def test_literal_none_test_return_metadata_preserves_complete_pure_oracles(before, after):
    ir, findings, verdict = run(before, after, PROD)
    assert projected(ir) and verdict == 'pass' and not findings


@pytest.mark.parametrize('annotation', ['callback()', 'other', '"None"', 'int', '0', 'False'])
def test_other_annotation_forms_are_not_assumed_inert(annotation):
    ir, _, _ = run(BEFORE, AFTER.replace('-> None', '-> ' + annotation), PROD)
    assert not projected(ir)


@pytest.mark.parametrize('after', [
    AFTER.replace('def test_first()', 'def test_first(value=callback())'),
    AFTER.replace('def test_first()', 'def test_first(value: callback())'),
    AFTER.replace('def test_first()', '@decorate\ndef test_first()'),
    AFTER.replace('    assert increment(2) == 3\n', ''),
])
def test_metadata_does_not_hide_signature_effects_or_missing_oracles(after):
    ir, _, _ = run(BEFORE, after, PROD)
    assert not projected(ir)


def test_changed_answer_remains_a_high_expectation_edit():
    ir, findings, verdict = run(BEFORE, AFTER.replace('== 3', '== 0'), PROD)
    assert projected(ir) and verdict == 'block'
    assert any(f.rule == 'EXPECTED_VALUE_CHANGED' and f.severity == 'high' for f in findings)


@pytest.mark.parametrize('production', [
    'def increment(value):\n    from tests.test_case import test_first\n    return len(test_first.__annotations__)\n',
    'def increment(value):\n    return callback(value)\n',
    'def increment(value) -> callback():\n    return value + 1\n',
])
def test_metadata_observers_and_production_signature_effects_decline(production):
    ir, _, _ = run(BEFORE, AFTER, production)
    assert not projected(ir)


def test_collector_can_observe_annotations_only_without_optional_credit():
    ir, _, _ = run(BEFORE, AFTER, PROD, context={'tests/conftest.py':b'def pytest_collection_modifyitems(items):\n    observe(items)\n'})
    assert not projected(ir)

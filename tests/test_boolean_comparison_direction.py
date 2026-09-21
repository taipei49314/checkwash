"""Current Boolean output cannot excuse losing a wrong-type identity oracle."""
import pytest

from checkwash import engine
from test_boolean_comparison_pairs import BEFORE, AFTER, PROD, projected
from test_issue_expectation_families import run


@pytest.mark.parametrize('changed', [False, True])
@pytest.mark.parametrize('production', [PROD, 'def success(code):\n    return code == 200\n',
                                        'def success(code):\n    return 1 if code == 200 else 0\n'])
def test_identity_to_equality_retains_ordinary_ir_even_for_current_boolean_production(changed, production, monkeypatch):
    before = BEFORE.replace(' == ', ' is ')
    after = AFTER.replace(' is ', ' == ')
    if changed:
        after = after.replace('(201, False)', '(201, True)')
    actual = run(before, after, production)
    assert not projected(actual[0])
    monkeypatch.setattr(engine, 'project_table_consolidation', lambda b, a, bp, ap, **kwargs: (bp, ap))
    assert actual == run(before, after, production)


def test_mixed_direction_rows_cannot_be_partially_canonicalized():
    before = BEFORE.replace('success(201) == False', 'success(201) is False')
    after = '''from app.prod import success
def test_combined():
    assert success(200) is True
    assert success(201) == False
'''
    ir, _, _ = run(before, after, PROD)
    assert not projected(ir)


def test_original_boolean_identity_loss_with_extra_rows_remains_blocked():
    production = 'def parse_bool(value):\n    return value.strip().lower() in {"1", "true", "yes"}\n'
    before = '''from app.prod import parse_bool
def test_yes():
    assert parse_bool("Yes") is True
def test_upper():
    assert parse_bool("TRUE") is True
def test_no():
    assert parse_bool("no") is False
'''
    after = '''from app.prod import parse_bool
def test_table():
    cases = [("Yes", True), ("TRUE", True), ("no", False), ("1", True), ("0", False)]
    for value, expected in cases:
        assert parse_bool(value) == expected
'''
    ir, _, verdict = run(before, after, production)
    assert not projected(ir) and verdict == 'block'


def test_equality_to_identity_still_exposes_rewritten_literal_answer():
    after = AFTER.replace('(201, False)', '(201, True)')
    ir, findings, verdict = run(BEFORE, after, PROD)
    assert projected(ir) and verdict == 'block'
    assert any(item.rule == 'EXPECTED_VALUE_CHANGED' and item.severity == 'high' for item in findings)


def test_same_identity_operator_still_preserves_literal_rows():
    ir, findings, verdict = run(BEFORE.replace(' == ', ' is '), AFTER, PROD)
    assert projected(ir) and verdict == 'pass' and not findings

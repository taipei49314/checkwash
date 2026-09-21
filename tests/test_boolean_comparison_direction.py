"""Identity-to-equality pairing bounds under the Boolean result proof (D-062).

The frozen lattice rates `x is True` and `x == True` identically (compare_eq,
EXACT_VALUE) and the in-place spelling change is silent, so the consolidation
projection pairs both directions — but only while the Boolean result proof
holds. This file pins the proof's boundary; `test_identity_comparison_pairs.py`
pins the pairing matrix itself. It replaces the one-direction pin that kept
identity-to-equality on ordinary IR even with the proof — a strictness the
silent in-place change never had.
"""
import pytest

from checkwash import engine
from test_boolean_comparison_pairs import BEFORE, AFTER, PROD, projected
from test_issue_expectation_families import run


@pytest.mark.parametrize('changed', [False, True])
@pytest.mark.parametrize('production', [PROD, 'def success(code):\n    return code == 200\n'])
def test_identity_to_equality_pairs_under_the_same_boolean_result_proof(changed, production):
    before = BEFORE.replace(' == ', ' is ')
    after = AFTER.replace(' is ', ' == ')
    if changed:
        after = after.replace('(201, False)', '(201, True)')
    ir, findings, verdict = run(before, after, production)
    assert projected(ir)
    assert verdict == ('block' if changed else 'pass')
    assert bool([f for f in findings if f.rule == 'EXPECTED_VALUE_CHANGED' and f.severity == 'high']) == changed


@pytest.mark.parametrize('changed', [False, True])
def test_identity_to_equality_retains_ordinary_ir_without_a_boolean_result(changed, monkeypatch):
    before = BEFORE.replace(' == ', ' is ')
    after = AFTER.replace(' is ', ' == ')
    if changed:
        after = after.replace('(201, False)', '(201, True)')
    production = 'def success(code):\n    return 1 if code == 200 else 0\n'
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


def test_identity_consolidation_with_added_rows_projects_them_as_gains():
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
    ir, findings, verdict = run(before, after, production)
    assert projected(ir) and verdict == 'pass' and not findings


def test_equality_to_identity_still_exposes_rewritten_literal_answer():
    after = AFTER.replace('(201, False)', '(201, True)')
    ir, findings, verdict = run(BEFORE, after, PROD)
    assert projected(ir) and verdict == 'block'
    assert any(item.rule == 'EXPECTED_VALUE_CHANGED' and item.severity == 'high' for item in findings)


def test_same_identity_operator_still_preserves_literal_rows():
    ir, findings, verdict = run(BEFORE.replace(' == ', ' is '), AFTER, PROD)
    assert projected(ir) and verdict == 'pass' and not findings

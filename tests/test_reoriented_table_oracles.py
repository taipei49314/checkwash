"""Reversed literal equalities need a closed primitive result proof."""
import pytest

from test_issue_expectation_families import run

BEFORE = '''from app.prod import squeeze
def test_many():
    got = squeeze("a   b")
    assert "  " not in got
    assert " " in got
    assert got == "a b"
def test_single():
    got = squeeze("x y")
    assert "  " not in got
    assert " " in got
    assert got == "x y"
'''
AFTER = '''from app.prod import squeeze
import pytest
@pytest.mark.parametrize("value, expected", [("a   b", "a b"), ("x y", "x y")])
def test_squeeze(value, expected):
    got = squeeze(value)
    assert expected == got
'''
PRODUCTION = 'def squeeze(value):\n    return " ".join(value.split())\n'


def result(before=BEFORE, after=AFTER, production=PRODUCTION):
    return run(before, after, production)[:2]


def test_closed_reoriented_string_table_preserves_original_checks():
    ir, findings = result()
    assert not findings
    assert any(unit.qualname.startswith('test_concrete') for file in ir.files for unit in file.units)


def test_reoriented_table_cannot_hide_changed_expected_value():
    _, findings = result(after=AFTER.replace('"a b")', '"wrong")'))
    assert any(f.rule == 'EXPECTED_VALUE_CHANGED' and f.severity == 'high' for f in findings)


@pytest.mark.parametrize('production', [
    'from plugin import transform\ndef squeeze(value):\n    return transform(value)\n',
    'class Value:\n    def __eq__(self, other):\n        return True\ndef squeeze(value):\n    return Value()\n',
    'def squeeze(value):\n    globals()["squeeze"] = lambda value: value\n    return value\n',
])
def test_unproved_or_effectful_result_cannot_earn_reorientation(production):
    ir, _ = result(production=production)
    assert not any(unit.qualname.startswith('test_concrete') for file in ir.files for unit in file.units)


def test_unknown_import_cannot_replace_the_primitive_subject():
    ir, _ = result(after=AFTER.replace('import pytest', 'import pytest\nimport plugin'))
    assert not any(unit.qualname.startswith('test_concrete') for file in ir.files for unit in file.units)


def test_actual_argument_or_original_row_removal_is_not_reorientation():
    ir, _ = result(after=AFTER.replace('("x y", "x y")', '("z", "z")'))
    assert not any(unit.qualname.startswith('test_concrete') for file in ir.files for unit in file.units)


def test_contradictory_membership_assertion_cannot_be_dropped():
    ir, _ = result(before=BEFORE.replace('assert " " in got', 'assert " " not in got'))
    assert not any(unit.qualname.startswith('test_concrete') for file in ir.files for unit in file.units)


def test_membership_custom_dispatch_cannot_be_assumed_from_equality():
    production = '''class Result:
    def __contains__(self, value):
        return False
    def __eq__(self, other):
        return True
def squeeze(value):
    return Result()
'''
    ir, _ = result(production=production)
    assert not any(unit.qualname.startswith('test_concrete') for file in ir.files for unit in file.units)

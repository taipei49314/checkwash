"""Tuple merges preserve every checked component and complete source proof."""
import pytest

from test_issue_expectation_families import run


PROD = 'def coordinates(value):\n    return value, value + 1\n'
BEFORE = '''from app.prod import coordinates
def test_first():
    x, y = coordinates(1)
    assert x == 1
    assert y == 2
def test_second():
    x, y = coordinates(3)
    assert x == 3
    assert y == 4
'''
AFTER = BEFORE.replace('def test_second():\n', '')


def projected(ir):
    return any(unit.qualname.startswith('test_concrete_') for file in ir.files for unit in file.units)


def test_complete_tuple_blocks_may_merge_without_losing_component_assertions():
    ir, findings, verdict = run(BEFORE, AFTER, PROD)
    assert projected(ir) and verdict == 'pass' and not findings
    assert len(ir.files[0].units) == 2


def test_complete_tuple_merges_compose_with_a_faithful_capture_helper():
    after = AFTER.replace('assert y == 2', 'check(y, 2)') + 'def check(actual, expected):\n    assert actual == expected\n'
    ir, findings, verdict = run(BEFORE, after, PROD)
    assert projected(ir) and verdict == 'pass' and not findings


def test_changed_tuple_component_remains_a_high_expectation_change():
    ir, findings, verdict = run(BEFORE, AFTER.replace('y == 4', 'y == 0'), PROD)
    assert projected(ir) and verdict == 'block'
    assert any(f.rule == 'EXPECTED_VALUE_CHANGED' and f.severity == 'high' for f in findings)


@pytest.mark.parametrize('after', [
    AFTER.replace('    assert y == 2\n', ''),
    AFTER.replace('    assert x == 3\n', ''),
    AFTER.replace('coordinates(3)', 'coordinates(x)'),
    AFTER.replace('    x, y = coordinates(3)', '    alias = x\n    x, y = coordinates(3)'),
    AFTER.replace('    x, y = coordinates(3)', '    mutate()\n    x, y = coordinates(3)'),
    AFTER.replace('    x, y = coordinates(3)', '    return\n    x, y = coordinates(3)'),
    AFTER.replace('x, y = coordinates(3)', 'x, x = coordinates(3)'),
    AFTER.replace('y == 4', 'x == 4'),
    AFTER.replace('    assert x == 3\n    assert y == 4\n', '    assert x == 3\n    assert x == 3\n'),
    AFTER.replace('coordinates(3)', 'coordinates(callback())'),
])
def test_partial_components_cross_block_values_and_effects_withhold_credit(after):
    ir, _, _ = run(BEFORE, after, PROD)
    assert not projected(ir)


@pytest.mark.parametrize('production', [
    'def coordinates(value):\n    return callback(value)\n',
    'def coordinates(value):\n    global seen\n    seen = value\n    return value, value + 1\n',
    'def coordinates(value):\n    return [value, value + 1]\n',
    'def coordinates(value):\n    return value, value + 1, 0\n',
    'def coordinates(value):\n    from tests.test_case import test_first\n    return value, value + 1\n',
])
def test_tuple_production_must_be_closed_pure_and_exact_arity(production):
    ir, _, _ = run(BEFORE, AFTER, production)
    assert not projected(ir)

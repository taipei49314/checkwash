"""Default builtin sorting/rounding stay within concrete primitive values."""
import pytest

from checkwash.frontends.python.oracle_purity import _pure_module
from test_issue_expectation_families import run


def projected(ir):
    return any(unit.qualname.startswith('test_concrete_') for file in ir.files for unit in file.units)


@pytest.mark.parametrize('production,first,second', [
    ('def subject(values):\n    return sorted(values)\n', 'subject([3, 1]) == [1, 3]', 'subject([]) == []'),
    ('def subject(value):\n    return round(value)\n', 'subject(1.4) == 1', 'subject(1.6) == 2'),
    ('def subject(value):\n    return round(value, 1)\n', 'subject(1.42) == 1.4', 'subject(1.68) == 1.7'),
])
def test_default_closed_builtin_operations_keep_reordered_concrete_oracles(production, first, second):
    before = 'from app.prod import subject\ndef test_first():\n    assert ' + first + '\ndef test_second():\n    assert ' + second + '\n'
    after = 'from app.prod import subject\ndef test_combined():\n    assert ' + second + '\n    assert ' + first + '\n'
    ir, findings, verdict = run(before, after, production)
    assert projected(ir) and verdict == 'pass' and not findings


@pytest.mark.parametrize('operation', ['sorted', 'round'])
@pytest.mark.parametrize('template', [
    'def subject(value, OP):\n    return OP(value)\n',
    'def subject(value):\n    OP = value\n    return OP(value)\n',
    'def OP(value):\n    return value\ndef subject(value):\n    return OP(value)\n',
    'from external import OP\ndef subject(value):\n    return OP(value)\n',
    'def subject(value):\n    return [OP(value) for OP in value]\n',
    'def subject(value):\n    return OP(callback(value))\n',
    'class Value:\n    def __round__(self):\n        return callback()\n    def __iter__(self):\n        return callback()\ndef subject(value):\n    return OP(Value())\n',
    'def subject(value):\n    return OP(value, key=callback)\n',
    'def subject(value):\n    return OP(value, **options)\n',
])
def test_shadowing_callbacks_and_custom_objects_cannot_use_builtin_authority(operation, template):
    assert not _pure_module(template.replace('OP', operation).encode(), 'subject')


def test_changed_sorted_expected_value_remains_a_high_oracle_change():
    before = 'from app.prod import subject\ndef test_first():\n    assert subject([2, 1]) == [1, 2]\ndef test_second():\n    assert subject([]) == []\n'
    after = 'from app.prod import subject\ndef test_combined():\n    assert subject([2, 1]) == [2, 1]\n    assert subject([]) == []\n'
    ir, findings, verdict = run(before, after, 'def subject(value):\n    return sorted(value)\n')
    assert projected(ir) and verdict == 'block'
    assert any(f.rule == 'EXPECTED_VALUE_CHANGED' and f.severity == 'high' for f in findings)


def test_rounding_cannot_turn_unknown_argument_receivers_into_primitives():
    before = 'from app.prod import subject\ndef test_first():\n    assert subject(custom) == 1\ndef test_second():\n    assert subject(2.1) == 2\n'
    after = before.replace('def test_second():\n', '')
    ir, _, _ = run(before, after, 'def subject(value):\n    return round(value)\n')
    assert not projected(ir)

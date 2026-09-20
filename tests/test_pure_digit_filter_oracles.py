"""Closed primitive digit predicates cannot dispatch into custom receivers."""
import pytest

from checkwash.frontends.python.oracle_purity import _pure_module
from test_issue_expectation_families import run


PROD = 'def digits(value):\n    return "".join(ch for ch in value if ch.isdigit())\n'
BEFORE = '''from app.prod import digits
def test_mixed():
    assert digits("a1b2") == "12"
def test_empty():
    assert digits("abc") == ""
'''
AFTER = '''from app.prod import digits
def test_combined():
    assert digits("abc") == ""
    assert digits("a1b2") == "12"
'''


def projected(ir):
    return any(unit.qualname.startswith('test_concrete_') for file in ir.files for unit in file.units)


def test_closed_digit_filter_can_preserve_reordered_complete_oracles():
    ir, findings, verdict = run(BEFORE, AFTER, PROD)
    assert projected(ir) and verdict == 'pass' and not findings


def test_digit_filter_answer_rewrite_remains_detected():
    ir, findings, verdict = run(BEFORE, AFTER.replace('== "12"', '== ""'), PROD)
    assert projected(ir) and verdict == 'block'
    assert any(f.rule == 'EXPECTED_VALUE_CHANGED' for f in findings)


@pytest.mark.parametrize('production', [
    'class Character:\n    def isdigit(self):\n        return callback()\ndef digits(value):\n    return Character().isdigit()\n',
    'from external import Character\ndef digits(value):\n    return Character(value).isdigit()\n',
    'def digits(value):\n    return callback(value).isdigit()\n',
    'def digits(value):\n    return value.isdigit(callback())\n',
    'def digits(value):\n    return getattr(value, "isdigit")()\n',
    'def digits(value):\n    global seen\n    seen = value\n    return value.isdigit()\n',
    'def digits(value):\n    from tests.test_case import test_combined\n    return value.isdigit()\n',
    'def digits(value):\n    return value.isdigit(option=True)\n',
])
def test_custom_receivers_callbacks_and_mutations_never_earn_digit_purity(production):
    assert not _pure_module(production.encode(), 'digits')
    ir, _, _ = run(BEFORE, AFTER, production)
    assert not projected(ir)


def test_unknown_input_receiver_is_not_mistaken_for_a_closed_primitive():
    ir, _, _ = run(BEFORE.replace('digits("a1b2")', 'digits(custom)'), AFTER, PROD)
    assert not projected(ir)


def test_external_startup_can_replace_primitive_operation_authority():
    ir, _, _ = run(BEFORE, AFTER, PROD, context={'tests/conftest.py': b'install_custom_subject()\n'})
    assert not projected(ir)

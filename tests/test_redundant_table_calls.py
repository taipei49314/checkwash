"""Unasserted calls earn no oracle credit; redundant pure inputs need none."""
import datetime

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze

BEFORE = '''from app.numbers import double
def test_one():
    assert double(1) == 2
def test_two():
    assert double(2) == 4
'''
AFTER = '''from app.numbers import double
import unittest
class TestNumbers(unittest.TestCase):
    def test_values(self):
        for value, expected in [(1, 2), (2, 4), (3, 6)]:
            with self.subTest(value=value):
                self.assertEqual(double(value), expected)
def test_extra():
    double(1) == 2
    double(2) == 4
    double(3) == 6
'''


def run(after, production=b'def double(value):\n    return value * 2\n'):
    sources = {'app/numbers.py': production}
    return analyze([FileChange('tests/test_numbers.py', 'modified', BEFORE.encode(), after.encode())],
                   Config(), Contract(), [], datetime.date(2026, 9, 21),
                   root_reader=sources.get, root_searcher=lambda _: [])


def projected(ir):
    return any(unit.qualname.startswith('test_concrete_') for unit in ir.files[0].units)


def test_existing_subtest_oracles_make_same_input_pure_comparisons_redundant():
    ir, findings, verdict = run(AFTER)
    assert projected(ir)
    assert verdict == 'pass'
    assert not findings


def test_comparison_cannot_replace_the_only_assertion_for_an_original_input():
    ir, _, verdict = run(AFTER.replace('(2, 4), ', ''))
    assert not projected(ir)
    assert verdict == 'block'


def test_discarded_original_answer_does_not_hide_actual_changed_expectation():
    _, findings, verdict = run(AFTER.replace('(2, 4)', '(2, 99)'))
    assert verdict == 'block'
    assert any(f.rule == 'EXPECTED_VALUE_CHANGED' and f.severity == 'high' for f in findings)


@pytest.mark.parametrize('after', [
    AFTER.replace('    double(3) == 6', '    double(99) == 6'),
    AFTER.replace('    double(3) == 6', '    mutate()'),
    AFTER.replace('    double(3) == 6', '    double(external()) == 6'),
    AFTER.replace('    double(3) == 6', '    double(3) == external()'),
    AFTER.replace('def test_extra():', 'def test_extra(value=external()):'),
    AFTER.replace('def test_extra():', '@external\ndef test_extra():'),
])
def test_new_inputs_side_effects_and_dynamic_comparisons_cannot_be_erased(after):
    ir, _, _ = run(after)
    assert not projected(ir)


@pytest.mark.parametrize('source', [
    b'def double(value):\n    record(value)\n    return value * 2\n',
    b'counter = 0\ndef double(value):\n    global counter\n    counter += 1\n    return value * counter\n',
    b'def double(value):\n    from tests.test_numbers import test_extra\n    return value\n',
])
def test_repeated_calls_require_a_closed_pure_product(source):
    ir, _, _ = run(AFTER, source)
    assert not projected(ir)

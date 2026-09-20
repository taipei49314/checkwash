"""Default subTest continuations and closed TestCase literal row providers."""
import datetime
import unittest

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze

BEFORE = '''import unittest
from app.digits import digit_sum
class TestDigits(unittest.TestCase):
    def test_positive(self):
        assert digit_sum(12) == 3
    def test_negative(self):
        assert digit_sum(-12) == 3
'''
STATIC = '''import unittest
from app.digits import digit_sum
class TestDigits(unittest.TestCase):
    @staticmethod
    def input_data():
        return [(12, 3), (-12, 3), (0, 0), (100, 1)]
    def test_values(self):
        for value, expected in self.input_data():
            with self.subTest(value=value):
                self.assertEqual(digit_sum(value), expected)
'''
CLASS = STATIC.replace('@staticmethod\n    def input_data():\n        return',
                       '@classmethod\n    def setUpClass(cls):\n        cls.test_cases =').replace('self.input_data()', 'self.test_cases')


def run(after, extra=None):
    sources = {'app/digits.py': b'def digit_sum(n):\n    return sum(int(ch) for ch in str(abs(n)))\n', **(extra or {})}
    return analyze([FileChange('tests/test_digits.py', 'modified', BEFORE.encode(), after.encode())],
                   Config(), Contract(), [], datetime.date(2026, 9, 21),
                   root_reader=sources.get, root_searcher=lambda _: [])


def projected(ir):
    return any(unit.qualname.startswith('test_concrete_') for unit in ir.files[0].units)


@pytest.mark.parametrize('after', [STATIC, CLASS])
def test_immutable_class_tables_preserve_original_oracles_and_add_subtests(after):
    ir, findings, verdict = run(after)
    assert projected(ir)
    assert verdict == 'pass'
    assert not findings


@pytest.mark.parametrize('after', [STATIC, CLASS])
def test_changed_original_expectation_remains_high(after):
    _, findings, verdict = run(after.replace('(-12, 3)', '(-12, 4)'))
    assert verdict == 'block'
    assert any(f.rule == 'EXPECTED_VALUE_CHANGED' and f.severity == 'high' for f in findings)


@pytest.mark.parametrize('after', [STATIC, CLASS])
def test_lost_original_input_does_not_earn_subtest_superset_credit(after):
    ir, _, verdict = run(after.replace('(-12, 3), ', ''))
    assert not projected(ir)
    assert verdict == 'block'


@pytest.mark.parametrize('after', [
    STATIC.replace('return [', 'mutate()\n        return ['),
    STATIC.replace('@staticmethod', '@external'),
    STATIC.replace('input_data():', 'input_data(value=external()):'),
    'staticmethod = external\n' + STATIC,
    'classmethod = external\n' + CLASS,
    CLASS.replace('cls.test_cases =', 'cls.test_cases: external() ='),
    CLASS.replace('(12, 3)', '([12], 3)'),
    CLASS.replace('self.test_cases:', 'self.test_cases:\n            self.test_cases.clear()'),
    CLASS.replace('test_cases', 'run'),
    STATIC.replace('input_data', 'run'),
    CLASS.replace('    def test_values(self):', '    def test_cases(self):\n        assert False\n    def test_values(self):'),
    CLASS.replace('    def test_values(self):', '    def setUp(self):\n        assert False\n    def test_values(self):'),
    STATIC.replace('self.assertEqual(digit_sum(value), expected)', 'self.assertEqual(digit_sum(value), expected)\n                self.fail()'),
])
def test_dynamic_headers_mutable_rows_overrides_or_failure_barriers_withhold_proof(after):
    ir, _, _ = run(after)
    assert not projected(ir)


@pytest.mark.parametrize('source', [
    b'def str(n):\n    return "0"\ndef digit_sum(n):\n    return sum(int(ch) for ch in str(abs(n)))\n',
    b'def digit_sum(n):\n    from tests.test_digits import TestDigits\n    return 0\n',
])
def test_builtin_shadow_and_production_backlink_stay_unproved(source):
    ir, _, _ = run(STATIC, {'app/digits.py': source})
    assert not projected(ir)


def test_default_subtest_failure_still_visits_every_later_row():
    visited = []
    class Check(unittest.TestCase):
        def runTest(self):
            for value, expected in [(1, 99), (2, 2), (3, 3)]:
                with self.subTest(value=value):
                    visited.append(value)
                    self.assertEqual(value, expected)
    result = unittest.TestResult()
    Check().run(result)
    assert visited == [1, 2, 3]
    assert len(result.failures) == 1
    assert not result.errors

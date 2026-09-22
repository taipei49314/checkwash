"""Default TestCase subTest rows preserve deterministic suite verdicts (#130)."""
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
AFTER = '''import unittest
from app.numbers import double
def rows():
    return [(1, 2), (2, 4)]
class TestNumbers(unittest.TestCase):
    def test_values(self):
        for value, expected in rows():
            with self.subTest(value=value, expected=expected):
                self.assertEqual(double(value), expected)
'''


def run(after, extra=None):
    sources = {'app/numbers.py': b'def double(value):\n    return value * 2\n', **(extra or {})}
    return analyze([FileChange("tests/test_numbers.py", "modified", BEFORE.encode(), after.encode())],
                   Config(), Contract(), [], datetime.date(2026, 9, 21),
                   root_reader=sources.get, root_searcher=lambda _: [])


def projected(ir):
    return any(unit.qualname.startswith('test_concrete_') for unit in ir.files[0].units)


@pytest.mark.parametrize('after', [AFTER, AFTER.replace('for value, expected in rows():',
    'for value, expected in [(1, 2), (2, 4)]:').replace('def rows():\n    return [(1, 2), (2, 4)]\n', '')])
def test_default_subtest_rows_keep_concrete_oracles(after):
    ir, findings, verdict = run(after)
    assert projected(ir)
    assert verdict == 'pass'
    assert not findings


def test_subtest_expected_rewrite_stays_high():
    _, findings, verdict = run(AFTER.replace('(2, 4)', '(2, 5)'))
    assert verdict == 'block'
    assert any(f.rule == 'EXPECTED_VALUE_CHANGED' and f.severity == 'high' for f in findings)


@pytest.mark.parametrize('after', [
    AFTER.replace('(1, 2), (2, 4)', '(1, 2)'),
    AFTER.replace('(1, 2), (2, 4)', '(1, 2), (2, 4), (3, 6)').replace(
        '            with self.subTest(value=value, expected=expected):\n                ', '            '),
    AFTER.replace('value=value', 'value=external(value)'),
    AFTER.replace('with self.subTest(', 'with external('),
    AFTER.replace('expected=expected):', 'expected=expected) as context:'),
    AFTER.replace('self.assertEqual(double(value), expected)', 'self.assertTrue(double(value))'),
    AFTER.replace('self.assertEqual(double(value), expected)', 'self.assertEqual(double(value), expected)\n                mutate()'),
    AFTER.replace('    def test_values(self):', '    def subTest(self, **kwargs):\n        return external()\n    def test_values(self):'),
    AFTER.replace('    def test_values(self):', '    def setUp(self):\n        self.assertEqual(double(99), 0)\n    def test_values(self):'),
    AFTER.replace('def rows():\n    return', 'def rows():\n    mutate()\n    return'),
    AFTER + 'rows = external\n',
])
def test_unknown_context_or_changed_oracle_multiplicity_withholds_subtest_proof(after):
    ir, _, _ = run(after)
    assert not projected(ir)


@pytest.mark.parametrize('extra', [
    {'unittest.py': b''},
    {'conftest.py': b'def pytest_runtest_call(item):\n    return True\n'},
    {'app/numbers.py': b'def double(value):\n    record(value)\n    return value * 2\n'},
    {'pytest.ini': b'[pytest]\naddopts=-W error\n'},
])
def test_subtest_proof_requires_real_testcase_and_pure_execution_context(extra):
    ir, _, _ = run(AFTER, extra)
    assert not projected(ir)

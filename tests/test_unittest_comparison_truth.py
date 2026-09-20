"""Default TestCase.assertTrue retains its complete checked comparison."""
import datetime

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.gitio.snapshot import search_source_mapping


def run(before, after, production, *, context=None):
    path = 'tests/test_case.py'
    snapshot = {'src/app/__init__.py': b'', 'src/app/prod.py': production.encode(), path: after.encode()}
    snapshot.update(context or {})
    return analyze([FileChange(path, 'modified', before.encode(), after.encode())],
                   Config(), Contract(), [], datetime.date(2026, 9, 21),
                   known_modules={'app', 'unittest'}, self_modules={'app'},
                   root_reader=snapshot.get, root_searcher=lambda needles: search_source_mapping(snapshot, needles))


PROD = 'def increment(value):\n    return value + 1\n'
BEFORE = '''from app.prod import increment
def test_first():
    assert increment(1) == 2
def test_second():
    assert increment(2) == 3
'''
AFTER = '''from app.prod import increment
import unittest
class TestValues(unittest.TestCase):
    def test_values(self):
        self.assertTrue(increment(1) == 2)
        self.assertTrue(increment(2) == 3)
'''


def projected(ir):
    return any(unit.qualname.startswith('test_concrete_') for file in ir.files for unit in file.units)


def test_default_assert_true_comparison_keeps_complete_native_oracles():
    ir, findings, verdict = run(BEFORE, AFTER, PROD)
    assert projected(ir) and verdict == 'pass' and not findings


@pytest.mark.parametrize('answer', ['True', 'False', 'None'])
def test_default_assert_true_preserves_identity_singleton_operator(answer):
    before = 'from app.prod import subject\ndef test_value():\n    assert subject(1) is ' + answer + '\n'
    after = 'from app.prod import subject\nimport unittest\nclass TestValue(unittest.TestCase):\n    def test_value(self):\n        self.assertTrue(subject(1) is ' + answer + ')\n'
    ir, findings, verdict = run(before, after, 'def subject(value):\n    return ' + answer + '\n')
    assert projected(ir) and verdict == 'pass' and not findings


def test_changed_assert_true_answer_remains_high():
    ir, findings, verdict = run(BEFORE, AFTER.replace('increment(1) == 2', 'increment(1) == 0'), PROD)
    assert projected(ir) and verdict == 'block'
    assert any(f.rule == 'EXPECTED_VALUE_CHANGED' and f.severity == 'high' for f in findings)


@pytest.mark.parametrize('expression', ['increment(1)', 'increment(1) != 2', '0 < increment(1) < 3',
                                       'True', 'expected == expected', 'callback(increment(1)) == 2'])
def test_truthy_side_predicates_other_operators_and_callbacks_get_no_credit(expression):
    ir, _, _ = run(BEFORE, AFTER.replace('increment(1) == 2', expression), PROD)
    assert not projected(ir)


@pytest.mark.parametrize('after', [
    AFTER.replace('increment(1) == 2)', 'increment(1) == 2, "message")'),
    AFTER.replace('increment(1) == 2)', 'increment(1) == 2, msg=callback())'),
    AFTER.replace('class TestValues(unittest.TestCase):', 'class TestValues(unittest.TestCase):\n    def assertTrue(self, value):\n        pass'),
    AFTER.replace('class TestValues(unittest.TestCase):', 'class TestValues(unittest.TestCase):\n    failureException = callback'),
    AFTER.replace('    def test_values(self):', '    @decorate\n    def test_values(self):'),
    AFTER.replace('    def test_values(self):', '    def test_values(self):\n        self = replacement'),
    AFTER.replace('import unittest', 'import external as unittest'),
    AFTER.replace('        self.assertTrue(increment(2) == 3)\n', ''),
])
def test_unknown_dispatch_diagnostics_binding_and_missing_checks_decline(after):
    ir, _, _ = run(BEFORE, after, PROD)
    assert not projected(ir)


@pytest.mark.parametrize('production', [
    'def increment(value):\n    return callback(value)\n',
    'class Result:\n    def __eq__(self, other):\n        return self\n    def __bool__(self):\n        return True\ndef increment(value):\n    return Result()\n',
    'def increment(value):\n    from tests.test_case import TestValues\n    return value + 1\n',
])
def test_subject_boolean_dispatch_must_stay_closed_and_primitive(production):
    ir, _, _ = run(BEFORE, AFTER, production)
    assert not projected(ir)


def test_repository_unittest_shadow_withholds_default_assert_true_authority():
    ir, _, _ = run(BEFORE, AFTER, PROD, context={'unittest.py': b'class TestCase:\n    pass\n'})
    assert not projected(ir)

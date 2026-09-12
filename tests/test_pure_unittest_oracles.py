"""TestCase order and setup are modeled only for closed pure imported calls."""

import datetime
from pathlib import Path

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze
from checkwash.gitio.snapshot import search_source_mapping


PATH = 'tests/test_numbers.py'
HEADER = 'from app.numbers import double\n'
BEFORE = (HEADER + 'def test_z_first():\n    assert double(1) == 2\n'
          'def test_a_second():\n    assert double(2) == 4\n').encode()
CLASS = (HEADER + 'import unittest\nclass TestNumbers(unittest.TestCase):\n'
         '    def test_z_first(self):\n        self.assertEqual(double(1), 2)\n'
         '    def test_a_second(self):\n        self.assertEqual(double(2), 4)\n').encode()
SETUP = (HEADER + 'import unittest\nclass TestNumbers(unittest.TestCase):\n'
         '    def setUp(self):\n        self.assertEqual(double(1), 2)\n'
         '    def test_second(self):\n        self.assertEqual(double(2), 4)\n').encode()
PRODUCTION = b'def double(value):\n    return value * 2\n'


def run(after, before=BEFORE, production=PRODUCTION, context=None):
    snapshot = {PATH: after, 'src/app/numbers.py': production, 'src/app/__init__.py': b'', **(context or {})}
    if production is None:
        snapshot.pop('src/app/numbers.py')
    return analyze([FileChange(PATH, 'modified', before, after)], Config(), Contract(), [],
                   datetime.date(2026, 9, 12), root_reader=snapshot.get,
                   root_searcher=lambda needles: search_source_mapping(snapshot, needles))


def projected(ir):
    return any(unit.qualname.startswith('test_concrete_') for file in ir.files for unit in file.units)


@pytest.mark.parametrize('after', [CLASS, SETUP])
def test_pure_testcase_sorting_and_setup_preserve_all_concrete_checks(after):
    for before, head in [(BEFORE, after), (after, BEFORE)]:
        ir, findings, verdict = run(head, before)
        assert projected(ir) and verdict == 'pass'
        assert not findings


def test_extra_setup_oracle_multiplicity_is_not_an_unordered_equivalence():
    after = SETUP + b'    def test_third(self):\n        self.assertEqual(double(3), 6)\n'
    ir, findings, verdict = run(after)
    assert not projected(ir)


@pytest.mark.parametrize('after', [CLASS.replace(b'double(1), 2', b'double(1), 99'),
                                    SETUP.replace(b'double(1), 2', b'double(1), 99')])
def test_reordered_or_setup_expected_rewrites_remain_high(after):
    ir, findings, verdict = run(after)
    assert projected(ir) and verdict == 'block'
    assert any(finding.rule == 'EXPECTED_VALUE_CHANGED' and finding.severity == 'high' for finding in findings)


@pytest.mark.parametrize('production', [None,
    b'counter = 0\ndef double(value):\n    global counter\n    counter += 1\n    return value * counter\n',
    b'def double(value):\n    return external(value)\n',
    b'def double(value):\n    value.clear()\n    return 0\n',
])
def test_order_and_lifecycle_changes_without_purity_receive_no_credit(production):
    ir, _findings, _verdict = run(CLASS, production=production)
    assert not projected(ir)


@pytest.mark.parametrize('after', [
    CLASS.replace(b'class TestNumbers(unittest.TestCase):', b'class TestNumbers(unittest.TestCase, External):'),
    CLASS.replace(b'class TestNumbers(unittest.TestCase):', b'class TestNumbers(unittest.TestCase):\n    __test__ = False'),
    CLASS.replace(b'class TestNumbers(unittest.TestCase):', b'class TestNumbers(unittest.TestCase):\n    def run(self):\n        pass'),
    CLASS.replace(b'class TestNumbers(unittest.TestCase):', b'class TestNumbers(unittest.TestCase):\n    def assertEqual(self, x, y):\n        pass'),
    SETUP.replace(b'        self.assertEqual(double(1), 2)', b'        patch()'),
    SETUP.replace(b'        self.assertEqual(double(2), 4)', b'        self.setUp()\n        self.assertEqual(double(2), 4)'),
    SETUP.replace(b'def setUp(self):', b'def tearDown(self):'),
    CLASS.replace(b'import unittest\n', b'') + b'import unittest\n',
])
def test_unknown_collection_dispatch_and_lifecycle_behavior_cannot_be_erased(after):
    ir, _findings, _verdict = run(after)
    assert not projected(ir)


def test_repository_unittest_replacement_is_not_testcase_authority():
    ir, _findings, _verdict = run(CLASS, context={'unittest.py': b''})
    assert not projected(ir)


def test_new_failing_setup_must_not_gain_credit_for_bodies_it_prevents():
    after = CLASS.replace(b'class TestNumbers(unittest.TestCase):',
                          b'class TestNumbers(unittest.TestCase):\n'
                          b'    def setUp(self):\n        self.assertEqual(double(99), 0)')
    ir, _findings, _verdict = run(after)
    assert not projected(ir)


def test_native_identity_must_not_turn_into_unittest_boolean_equality():
    before = BEFORE.replace(b'== 2', b'is True').replace(b'== 4', b'is False')
    after = CLASS.replace(b'double(1), 2', b'double(1), True').replace(b'double(2), 4', b'double(2), False')
    ir, _findings, _verdict = run(after, before)
    assert not projected(ir)


@pytest.mark.parametrize('case_name', ['CASE_027_clip_index', 'EXT_008_is_sorted'])
def test_retained_testcase_refactors_have_a_closed_pure_source_proof(case_name):
    case = Path(__file__).parents[1] / 'benchmarks' / 'refactors' / 'cases' / case_name
    before_root, after_root = case / 'BEFORE', case / 'AFTER'
    before = {path.relative_to(before_root).as_posix(): path.read_bytes() for path in before_root.rglob('*') if path.is_file()}
    after = {path.relative_to(after_root).as_posix(): path.read_bytes() for path in after_root.rglob('*') if path.is_file()}
    production_root = case / 'PROD-GOOD'
    snapshot = {path.relative_to(production_root).as_posix(): path.read_bytes()
                for path in production_root.rglob('*') if path.is_file()}
    snapshot.update(after)
    changes = [FileChange(path, 'modified', before[path], after[path]) for path in before.keys() & after.keys()
               if before[path] != after[path]]
    ir, findings, verdict = analyze(changes, Config(), Contract(), [], datetime.date(2026, 9, 12),
                                    root_reader=snapshot.get,
                                    root_searcher=lambda needles: search_source_mapping(snapshot, needles))
    assert projected(ir) and verdict == 'pass'
    assert not findings

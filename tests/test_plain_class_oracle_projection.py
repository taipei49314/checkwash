"""Transparent helper/class extraction preserves concrete checks, not names."""

import datetime
from pathlib import Path

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze
from checkwash.gitio.snapshot import search_source_mapping


PATH = 'tests/test_numbers.py'
HEADER = 'from app.numbers import double\n'
BEFORE = (HEADER + 'def test_first():\n    assert double(1) == 2\n'
          'def test_second():\n    assert double(2) == 4\n').encode()


def run(after, before=BEFORE, context=None):
    snapshot = {PATH: after, 'app/__init__.py': b'',
                'app/numbers.py': b'def double(value):\n    return value * 2\n', **(context or {})}
    return analyze([FileChange(PATH, 'modified', before, after)], Config(), Contract(), [],
                   datetime.date(2026, 9, 12), root_reader=snapshot.get,
                   root_searcher=lambda needles: search_source_mapping(snapshot, needles))


def projected(ir):
    return any(unit.qualname.startswith('test_concrete_') for file in ir.files for unit in file.units)


HELPER = ('def check(value, expected):\n    assert double(value) == expected\n'
          'def test_first():\n    check(1, 2)\n'
          'def test_second():\n    check(2, 4)\n')
PLAIN = ('class TestNumbers:\n'
         '    def test_first(self):\n        assert double(1) == 2\n'
         '    def test_second(self):\n        assert double(2) == 4\n')
MIXIN = ('class NumberChecks:\n'
         '    def first(self):\n        assert double(1) == 2\n'
         '    def second(self):\n        assert double(2) == 4\n'
         'class TestNumbers(NumberChecks):\n'
         '    def test_first(self):\n        self.first()\n'
         '    def test_second(self):\n        self.second()\n')
METHOD = ('class TestNumbers:\n'
          '    def check(self, value, expected):\n        assert double(value) == expected\n'
          '    def test_first(self):\n        self.check(1, 2)\n'
          '    def test_second(self):\n        self.check(2, 4)\n')
OBJECT = ('class NumberChecks:\n'
          '    def check(self, value, expected):\n        assert double(value) == expected\n'
          'def test_first():\n    NumberChecks().check(1, 2)\n'
          'def test_second():\n    NumberChecks().check(2, 4)\n')


@pytest.mark.parametrize('body', [HELPER, PLAIN, MIXIN, METHOD, OBJECT])
def test_native_checks_survive_transparent_helper_and_class_extraction_in_both_directions(body):
    after = (HEADER + body).encode()
    for old, new in [(BEFORE, after), (after, BEFORE)]:
        ir, findings, verdict = run(new, before=old)
        assert projected(ir)
        assert verdict == 'pass'
        assert not findings


@pytest.mark.parametrize('body', [HELPER, PLAIN, MIXIN, METHOD, OBJECT])
def test_extracted_checks_do_not_gain_credit_for_changed_answers(body):
    changed = body.replace('== 2', '== 99').replace('(1, 2)', '(1, 99)')
    ir, findings, verdict = run((HEADER + changed).encode())
    assert projected(ir) and verdict == 'block'
    assert any(finding.rule == 'EXPECTED_VALUE_CHANGED' and finding.severity == 'high' for finding in findings)


@pytest.mark.parametrize('body', [
    PLAIN.replace('class TestNumbers:', 'class HiddenNumbers:'),
    PLAIN.replace('class TestNumbers:', '@disable\nclass TestNumbers:'),
    PLAIN.replace('class TestNumbers:', 'class TestNumbers(ExternalBase):'),
    PLAIN.replace('class TestNumbers:', 'class TestNumbers(metaclass=Meta):'),
    PLAIN.replace('class TestNumbers:', 'class TestNumbers:\n    __test__ = False'),
    PLAIN.replace('class TestNumbers:', 'class TestNumbers:\n    def setup_method(self):\n        install_patch()'),
    METHOD.replace('    def check(self,', '    @staticmethod\n    def check(self,'),
    METHOD.replace('assert double(value) == expected', 'pass'),
    METHOD.replace('assert double(value) == expected', 'assert double(value) == self.expected'),
    OBJECT.replace('class NumberChecks:', 'class NumberChecks:\n    def __getattribute__(self, name):\n        return lambda *args: None'),
    MIXIN.replace('class TestNumbers(NumberChecks):', 'class TestNumbers(NumberChecks):\n    def first(self):\n        pass'),
    MIXIN.replace('def first(self):', 'def test_first_in_base(self):').replace('self.first()', 'self.test_first_in_base()'),
    ('class NumberChecks:\n'
     '    def check(self, value, expected):\n        assert double(value) == expected\n'
     'def NumberChecks():\n    assert double(2) == 4\n'
     'def test_first():\n    NumberChecks().check(1, 2)\n'
     'def test_second():\n    NumberChecks()\n'),
])
def test_collection_dispatch_or_instance_state_cannot_be_erased_by_class_projection(body):
    ir, _findings, _verdict = run((HEADER + body).encode())
    assert not projected(ir)


def test_helper_extraction_keeps_startup_and_order_requirements():
    ir, _findings, _verdict = run((HEADER + HELPER).encode(), context={'conftest.py': b'patch()\n'})
    assert not projected(ir)
    # New inputs do not prove preservation of the original sequence.
    after = (HEADER + METHOD.replace('self.check(1, 2)', 'self.check(3, 6)')).encode()
    ir, _findings, _verdict = run(after)
    assert not projected(ir)


@pytest.mark.parametrize('case_name', [
    'CASE_010_median', 'CASE_018_interleave', 'EXT_003_take', 'EXT_013_min_max',
    'EXT_016_reverse_words', 'EXT_022_fill_none', 'EXT_027_merge_unique',
])
def test_retained_honest_refactor_sources_have_all_concrete_oracles_preserved(case_name):
    case = Path(__file__).parents[1] / 'benchmarks' / 'refactors' / 'cases' / case_name
    before_root, after_root = case / 'BEFORE', case / 'AFTER'
    before = {path.relative_to(before_root).as_posix(): path.read_bytes() for path in before_root.rglob('*') if path.is_file()}
    after = {path.relative_to(after_root).as_posix(): path.read_bytes() for path in after_root.rglob('*') if path.is_file()}
    changes = [FileChange(path, 'modified', before[path], after[path]) for path in before.keys() & after.keys()
               if before[path] != after[path]]
    ir, findings, verdict = analyze(changes, Config(), Contract(), [], datetime.date(2026, 9, 12),
                                    root_reader=after.get,
                                    root_searcher=lambda needles: search_source_mapping(after, needles))
    assert projected(ir)
    assert verdict == 'pass'
    assert not findings

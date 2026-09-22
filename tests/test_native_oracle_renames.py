"""Pure native test renames preserve exact subject/input multiplicities."""
import datetime

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze

BEFORE = '''from app.merge_unique import merge_unique
def test_overlap():
    assert merge_unique([1, 2], [2, 3]) == [1, 2, 3]
def test_order():
    assert merge_unique([3, 1], [1, 2]) == [3, 1, 2]
'''
AFTER = '''from app.merge_unique import merge_unique
def test_merge_order():
    assert merge_unique([3, 1], [1, 2]) == [3, 1, 2]
def test_merge_overlap():
    assert merge_unique([1, 2], [2, 3]) == [1, 2, 3]
'''
PRODUCTION = '''def merge_unique(a, b):
    out = []
    seen = set()
    for x in list(a) + list(b):
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out
'''


def run(after=AFTER, production=PRODUCTION, extra=None):
    sources = {'app/merge_unique.py': production.encode(), **(extra or {})}
    return analyze([FileChange('tests/test_merge.py', 'modified', BEFORE.encode(), after.encode())],
                   Config(), Contract(), [], datetime.date(2026, 9, 21),
                   root_reader=sources.get, root_searcher=lambda _: [])


def projected(ir):
    return any(unit.qualname.startswith('test_concrete_') for unit in ir.files[0].units)


def test_pure_single_assert_test_rename_and_reorder_keeps_both_oracles():
    ir, findings, verdict = run()
    assert projected(ir)
    assert verdict == 'pass'
    assert not findings


def test_renamed_expected_value_change_is_still_high():
    _, findings, verdict = run(AFTER.replace('== [3, 1, 2]', '== [1, 2, 3]'))
    assert verdict == 'block'
    assert any(f.rule == 'EXPECTED_VALUE_CHANGED' and f.severity == 'high' for f in findings)


@pytest.mark.parametrize('after', [
    AFTER.replace('merge_unique([3, 1], [1, 2])', 'merge_unique([1, 2], [2, 3])'),
    AFTER.replace('    assert merge_unique([3, 1], [1, 2]) == [3, 1, 2]\n', '    pass\n'),
])
def test_reordering_cannot_drop_duplicate_or_hide_original_checks(after):
    ir, _, verdict = run(after)
    assert not projected(ir)
    assert verdict == 'block'


def test_multiple_statements_do_not_receive_the_single_assert_rename_proof():
    after = AFTER.replace('    assert merge_unique([3, 1], [1, 2]) == [3, 1, 2]\n',
                          '    assert False\n    assert merge_unique([3, 1], [1, 2]) == [3, 1, 2]\n')
    ir, _, _ = run(after)
    assert not projected(ir)


@pytest.mark.parametrize('production', [
    PRODUCTION.replace('out = []', 'out = a'),
    PRODUCTION.replace('seen = set()', 'seen = a'),
    PRODUCTION.replace('out.append(x)', 'a.append(x)'),
    PRODUCTION.replace('seen.add(x)', 'record(x)'),
    PRODUCTION.replace('return out', 'from tests.test_merge import test_overlap\n    return out'),
    'def list(value):\n    return []\n' + PRODUCTION,
    'def set():\n    return []\n' + PRODUCTION,
    PRODUCTION.replace('list(a) + list(b)', 'a + b').replace('out = []', 'out = external'),
])
def test_fresh_local_collection_proof_rejects_alias_mutation_and_callbacks(production):
    ir, _, _ = run(production=production)
    assert not projected(ir)


def test_renames_need_inert_startup_and_collection_context():
    ir, _, _ = run(extra={'conftest.py': b'def pytest_runtest_call(item):\n    mutate()\n'})
    assert not projected(ir)

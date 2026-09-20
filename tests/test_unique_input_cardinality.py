"""An entailed input-count clause keeps the exact list answer and its changes."""
import pytest

from test_complete_unique_helpers import PRODUCTION as GOOD_PRODUCTION, projected
from test_issue_expectation_families import run

PRODUCTION = 'def unique(xs):\n    return list(set(xs))\n'
OLD_HELPER = '''def assert_unique_stable(xs, expected):
    got = unique(xs)
    assert got == expected
    assert len(got) == len(set(got))
'''
NEW_HELPER = '''def assert_unique_stable(xs, expected):
    got = unique(xs)
    assert got == expected, f"Expected {expected}, but got {got}"
    assert len(got) == len(set(xs)), "Length mismatch"
'''
BEFORE = 'from app.prod import unique\n' + OLD_HELPER + '''def test_order():
    assert_unique_stable([3, 1, 3, 2], [3, 1, 2])
def test_letters():
    assert_unique_stable(["a", "b"], ["a", "b"])
'''
AFTER = 'import pytest\nfrom app.prod import unique\n' + NEW_HELPER + '''@pytest.mark.parametrize("xs, expected", [
    ([3, 1, 3, 2], [1, 2, 3]),
    (["a", "b"], ["a", "b"]),
])
def test_unique(xs, expected):
    assert_unique_stable(xs, expected)
'''


@pytest.mark.parametrize('after', [AFTER,
    AFTER.replace('assert_unique_stable','check_unique'),
    AFTER.replace('got','actual'),
    AFTER.replace('f"Expected {expected}, but got {got}"','"wrong answer"'),
    AFTER.replace('f"Expected {expected}, but got {got}"','f"input {xs}: {got!r}, wanted {expected!r}"'),
    AFTER.replace(', "Length mismatch"',''),
])
def test_changed_exact_sequence_is_not_hidden_by_entailed_cardinality(after):
    result=run(BEFORE,after,PRODUCTION)
    assert projected(result[0]) and result[2]=='block'
    assert any(f.rule=='EXPECTED_VALUE_CHANGED' and f.severity=='high' for f in result[1])


@pytest.mark.parametrize('production', [GOOD_PRODUCTION, PRODUCTION, 'def unique(xs):\n    return list(xs)\n'])
def test_honest_carrier_preserves_exact_sequence_with_good_or_wrong_production(production):
    after=AFTER.replace('([3, 1, 3, 2], [1, 2, 3])','([3, 1, 3, 2], [3, 1, 2])')
    result=run(BEFORE,after,production)
    assert projected(result[0]) and result[2]=='pass'


@pytest.mark.parametrize('old,new', [
    ('len(got) == len(set(xs))','len(got) != len(set(xs))'),
    ('len(got) == len(set(xs))','len(got) >= len(set(xs))'),
    ('len(got) == len(set(xs))','len(got) == len(xs)'),
    ('len(got) == len(set(xs))','len(set(got)) == len(set(xs))'),
    ('len(got) == len(set(xs))','len(got) == len(set(expected))'),
    ('len(got) == len(set(xs))','len(got) == count(xs)'),
    ('"Length mismatch"','callback()'),
    ('"Length mismatch"','f"{(len := 0)}"'),
    ('f"Expected {expected}, but got {got}"','callback()'),
    ('f"Expected {expected}, but got {got}"','f"{(unique := 0)}"'),
    ('f"Expected {expected}, but got {got}"','f"{got:custom}"'),
    ('f"Expected {expected}, but got {got}"','f"{callback(got)}"'),
    ('got = unique(xs)','got = other(xs)'),
    ('got = unique(xs)','got = unique(expected)'),
    ('got = unique(xs)','got = unique(xs=xs)'),
    ('got = unique(xs)','xs = unique(xs)'),
    ('assert got == expected','assert set(got) == set(expected)'),
    ('assert got == expected','assert got is expected'),
    ('    assert got == expected, f"Expected {expected}, but got {got}"\n',''),
    ('    got =','    mutate()\n    got ='),
    ('def assert_unique_stable(xs, expected):','def assert_unique_stable(xs, expected, set):'),
])
def test_unknown_diagnostic_or_independent_predicate_cannot_disappear(old,new):
    assert not projected(run(BEFORE,AFTER.replace(NEW_HELPER,NEW_HELPER.replace(old,new)),PRODUCTION)[0])


@pytest.mark.parametrize('row', [
    '([3, 1, 3, 2], [1, 2])',
    '([3, 1, 3, 2], [1, 2, 3, 4])',
    '([3, 1, 3, 2], [1, 1, 2])',
    '([3, 1, 3, 2], [1, True, 2])',
    '([[3], [1], [3], [2]], [1, 2, 3])',
    '([3, 1, 3, 2], [[1], [2], [3]])',
])
def test_each_literal_row_proves_the_whole_input_count_clause(row):
    after=AFTER.replace('([3, 1, 3, 2], [1, 2, 3])',row)
    assert not projected(run(BEFORE,after,PRODUCTION)[0])


@pytest.mark.parametrize('binding', [
    'len = callback\n', 'set = callback\n',
    'from app.prod import unique as len\n',
    'def set(value):\n    return value\n',
])
def test_module_builtin_bindings_withhold_the_entailed_count(binding):
    after=AFTER.replace(NEW_HELPER,binding+NEW_HELPER)
    assert not projected(run(BEFORE,after,PRODUCTION)[0])


@pytest.mark.parametrize('production', [
    'def unique(xs):\n    xs.clear()\n    return []\n',
    'def unique(xs):\n    return Custom()\n',
    'import builtins\nbuiltins.set = custom\n'+PRODUCTION,
    'from tests.test_case import assert_unique_stable\n'+PRODUCTION,
])
def test_production_cannot_mutate_shared_inputs_or_install_custom_comparisons(production):
    assert not projected(run(BEFORE,AFTER,production)[0])


@pytest.mark.parametrize('context', [
    {'pytest.py':b''}, {'app/__init__.py':b''},
    {'src/sitecustomize.py':b'import builtins\nbuiltins.len = custom\n'},
    {'tests/conftest.py':b'def pytest_runtest_setup(item):\n    mutate()\n'},
    {'tests/test_other.py':b'import builtins\nbuiltins.set = custom\n'},
    {'pytest.ini':b'[pytest]\ntestpaths=tests/other\n'},
])
def test_import_startup_and_collection_authority_are_required(context):
    assert not projected(run(BEFORE,AFTER,PRODUCTION,context=context)[0])


def test_reordered_or_dropped_old_rows_keep_ordinary_fallback():
    after=AFTER.replace('    ([3, 1, 3, 2], [1, 2, 3]),\n','')
    assert not projected(run(BEFORE,after,PRODUCTION)[0])

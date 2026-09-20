"""Shared mutable params need a complete non-mutating production proof."""
import pytest

from test_issue_expectation_families import run

PRODUCTION = '''def merge_unique(a, b):
    out = []
    seen = set()
    for x in list(a) + list(b):
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out
'''
BEFORE = '''from app.prod import merge_unique
def test_overlap():
    assert merge_unique([1, 2], [2, 3]) == [1, 2, 3]
def test_order():
    assert merge_unique([3, 1], [1, 2]) == [3, 1, 2]
'''
AFTER = '''from app.prod import merge_unique
import pytest
@pytest.fixture(params=[([1, 2], [2, 3], [1, 2, 3]), ([3, 1], [1, 2], [3, 1, 2]), ([], [4, 5], [4, 5])])
def test_data(request):
    return request.param
def test_overlap(test_data):
    a, b, expected = test_data
    assert merge_unique(a, b) == expected
def test_order(test_data):
    a, b, expected = test_data
    assert merge_unique(a, b) == expected
'''


def projected(ir):
    return any(u.qualname.startswith('test_concrete') for f in ir.files for u in f.units)


def test_complete_fresh_local_collection_proof_preserves_shared_rows():
    ir, findings, verdict = run(BEFORE, AFTER, PRODUCTION)
    assert projected(ir) and not findings and verdict == 'pass'


@pytest.mark.parametrize('production', [
    PRODUCTION.replace('out = []', 'out = a'),
    PRODUCTION.replace('out.append(x)', 'a.append(x)'),
    PRODUCTION.replace('out.append(x)', 'b.append(x)'),
    PRODUCTION + '\nimport plugin\n',
    PRODUCTION + '\nset = list\n',
    PRODUCTION.replace('return out', 'a.clear()\n    return out'),
    PRODUCTION.replace('for x in list(a) + list(b):', 'for x in callback(a, b):'),
])
def test_mutation_or_unknown_authority_cannot_copy_shared_rows(production):
    ir, _, _ = run(BEFORE, AFTER, production)
    assert not projected(ir)


@pytest.mark.parametrize('after', [
    AFTER.replace('return request.param', 'return list(request.param)'),
    AFTER.replace('params=', 'scope="module", params='),
    AFTER.replace('def test_order', '@pytest.mark.skip\ndef test_order'),
    AFTER.replace('([3, 1], [1, 2], [3, 1, 2]), ', ''),
    AFTER.replace('assert merge_unique(a, b)', 'a.append(0)\n    assert merge_unique(a, b)', 1),
    AFTER + '\ndef test_unused(test_data):\n    assert True\n',
])
def test_original_coverage_and_fixture_execution_must_remain_proved(after):
    ir, _, _ = run(BEFORE, after, PRODUCTION)
    assert not projected(ir)


def test_rewritten_shared_row_expected_value_is_still_blocked():
    _, findings, verdict = run(BEFORE, AFTER.replace('[3, 1, 2])', '[1, 2, 3])'), PRODUCTION)
    assert verdict == 'block'
    assert any(f.rule == 'EXPECTED_VALUE_CHANGED' and f.severity == 'high' for f in findings)


def test_uninspected_autouse_fixture_cannot_mutate_params_between_consumers():
    ir, _, _ = run(BEFORE, AFTER, PRODUCTION, context={
        'conftest.py': b'import pytest\n@pytest.fixture(autouse=True)\ndef alter():\n    yield\n'})
    assert not projected(ir)

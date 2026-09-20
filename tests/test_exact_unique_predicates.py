"""Uniqueness is auxiliary; every full expected sequence must remain checked."""
import pytest

from test_issue_expectation_families import run

PRODUCTION = '''def merge_unique(a,b):
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
    assert merge_unique([1,2],[2,3]) == [1,2,3]
def test_order():
    assert merge_unique([3,1],[1,2]) == [3,1,2]
'''
AFTER = '''from app.prod import merge_unique
def is_unique(items):
    return len(items) == len(set(items))
def test_overlap():
    result = merge_unique([1,2],[2,3])
    assert is_unique(result)
    assert result == [1,2,3]
def test_order():
    result = merge_unique([3,1],[1,2])
    assert is_unique(result)
    assert result == [3,1,2]
'''


def projected(ir):
    return any(unit.qualname.startswith('test_concrete') for file in ir.files for unit in file.units)


def test_exact_unique_literal_lists_retain_full_input_and_expected_checks():
    ir, findings, verdict = run(BEFORE, AFTER, PRODUCTION)
    assert verdict == 'pass', findings
    assert projected(ir)
    assert sum(unit.before is not None and unit.after is not None for file in ir.files for unit in file.units) == 2


def test_changed_unique_answer_remains_an_expected_value_change():
    _, findings, verdict = run(BEFORE, AFTER.replace('== [3,1,2]', '== [1,2,3]'), PRODUCTION)
    assert verdict == 'block'
    assert any(f.rule == 'EXPECTED_VALUE_CHANGED' for f in findings)


@pytest.mark.parametrize('change', [
    ('    assert result == [3,1,2]\n', ''),
    ('assert result == [3,1,2]', 'assert result[0] == 3'),
    ('assert result == [3,1,2]', 'assert len(result) == 3'),
    ('assert result == [3,1,2]', 'assert result == [3,3,2]'),
    ('assert result == [3,1,2]', 'assert result == [1,True,2]'),
    ('assert result == [3,1,2]', 'assert result == [[3],[1],[2]]'),
    ('return len(items) == len(set(items))', 'return True'),
    ('return len(items) == len(set(items))', 'return len(items) != len(set(items))'),
    ('return len(items) == len(set(items))', 'mutate(items)\n    return len(items) == len(set(items))'),
    ('assert is_unique(result)', 'is_unique(result)'),
    ('assert is_unique(result)', 'assert not is_unique(result)'),
    ('assert is_unique(result)', 'assert is_unique(result), callback()'),
    ('result = merge_unique', 'merge_unique = merge_unique'),
    ('def is_unique(items):', '@decorate\ndef is_unique(items):'),
    ('def is_unique(items):', 'def is_unique(items=callback()):'),
    ('def test_overlap():', 'alias = is_unique\ndef test_overlap():'),
    ('def test_overlap():', 'is_unique = replacement\ndef test_overlap():'),
    ('def test_overlap():', 'def test_overlap(is_unique):'),
    ('from app.prod import merge_unique', 'from app.prod import merge_unique\nlen = replacement'),
    ('from app.prod import merge_unique', 'from app.prod import merge_unique\nset = replacement'),
    ('from app.prod import merge_unique', 'from app.prod import merge_unique\nimport mutator'),
    ('merge_unique([3,1],[1,2])', 'merge_unique([3,1],[9,2])'),
])
def test_incomplete_false_or_unknown_predicate_does_not_earn_projection(change):
    assert not projected(run(BEFORE, AFTER.replace(*change), PRODUCTION)[0])


@pytest.mark.parametrize('production', [
    'import mutator\n'+PRODUCTION,
    'def merge_unique(a,b):\n    return custom(a,b)\n',
    'def merge_unique(a,b):\n    from tests.test_case import is_unique\n    return a+b\n',
    'def merge_unique(a,b):\n    return globals()["answer"]\n',
    'class Result:\n    def __eq__(self,other):\n        return True\ndef merge_unique(a,b):\n    return Result()\n',
])
def test_unknown_or_custom_result_cannot_earn_unique_predicate_projection(production):
    assert not projected(run(BEFORE, AFTER, production)[0])


def test_false_original_unique_predicate_cannot_be_erased_in_reverse():
    before = AFTER.replace('== [3,1,2]', '== [3,3,2]')
    assert not projected(run(before, BEFORE, PRODUCTION)[0])

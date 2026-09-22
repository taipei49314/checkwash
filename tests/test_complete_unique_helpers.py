"""A helper's complete exact sequence and uniqueness checks survive tables."""
import pytest

from test_issue_expectation_families import run

PRODUCTION = '''def unique(xs):
    seen = set()
    out = []
    for x in xs:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out
'''
HELPER = '''def assert_unique(xs,expected):
    got = unique(xs)
    assert got == expected
    assert len(got) == len(set(got))
'''
BEFORE = ('from app.prod import unique\n' + HELPER +
          'def test_order():\n    assert_unique([3,1,3,2],[3,1,2])\n'
          'def test_letters():\n    assert_unique(["a","b"],["a","b"])\n')
AFTER = ('''import pytest
from app.prod import unique
@pytest.fixture(params=[([3,1,3,2],[3,1,2]),(["a","b"],["a","b"]),([],[]),([1,1],[1])])
def cases(request):
    return request.param
''' + HELPER + '''def test_unique(cases):
    xs,expected = cases
    assert_unique(xs,expected)
''')


def projected(ir):
    return any(unit.qualname.startswith('test_concrete') for file in ir.files for unit in file.units)


def test_complete_helper_checks_each_exact_expected_sequence_in_fixture_rows():
    ir, findings, verdict = run(BEFORE, AFTER, PRODUCTION)
    assert verdict == 'pass', findings
    assert projected(ir)
    assert sum(unit.before is not None and unit.after is not None for file in ir.files for unit in file.units) == 2


def test_changed_unique_row_is_still_an_expected_value_change():
    _, findings, verdict = run(BEFORE, AFTER.replace('([3,1,3,2],[3,1,2])', '([3,1,3,2],[1,2,3])'), PRODUCTION)
    assert verdict == 'block'
    assert any(f.rule == 'EXPECTED_VALUE_CHANGED' for f in findings)


@pytest.mark.parametrize('change', [
    ('    assert got == expected\n', ''),
    ('assert got == expected', 'assert len(got) == len(expected)'),
    ('assert len(got) == len(set(got))', 'assert len(got) != len(set(got))'),
    ('assert len(got) == len(set(got))', 'assert len(got) == len(set(got)), report()'),
    ('assert got == expected', 'assert got == expected, report()'),
    ('got = unique(xs)', 'got = change(unique(xs))'),
    ('got = unique(xs)', 'xs = unique(xs)'),
    ('got = unique(xs)', 'unique = unique(xs)'),
    ('def assert_unique(xs,expected):', '@decorate\ndef assert_unique(xs,expected):'),
    ('def assert_unique(xs,expected):', 'def assert_unique(xs,expected=callback()):'),
    ('([3,1,3,2],[3,1,2])', '([3,1,3,2],[3,3,2])'),
    ('([3,1,3,2],[3,1,2])', '([3,1,3,2],[1,True,2])'),
    ('assert_unique(xs,expected)', 'assert_unique(xs,xs)'),
    ('from app.prod import unique', 'from app.prod import unique\nset = replacement'),
    ('from app.prod import unique', 'from app.prod import unique\nlen = replacement'),
    ('from app.prod import unique', 'from app.prod import unique\nimport mutator'),
    ('def test_unique(cases):', 'def test_unique(cases,assert_unique):'),
])
def test_incomplete_helper_or_unproved_row_has_no_projection(change):
    assert not projected(run(BEFORE, AFTER.replace(*change), PRODUCTION)[0])


@pytest.mark.parametrize('change', [
    ('seen = set()', 'seen = xs'),
    ('out = []', 'out = xs'),
    ('seen.add(x)', 'xs.append(x)'),
    ('out.append(x)', 'out.append(callback(x))'),
    ('for x in xs:', 'for x in custom(xs):'),
    ('return out', 'return custom(out)'),
    ('def unique(xs):', '@decorate\ndef unique(xs):'),
    ('def unique(xs):', 'def unique(xs=set()):'),
])
def test_fresh_sequence_proof_rejects_alias_mutation_callbacks_and_definition_effects(change):
    assert not projected(run(BEFORE, AFTER, PRODUCTION.replace(*change))[0])


def test_false_original_uniqueness_expectation_cannot_be_erased():
    before = BEFORE.replace('[3,1,2])', '[3,3,2])')
    assert not projected(run(before, AFTER, PRODUCTION)[0])

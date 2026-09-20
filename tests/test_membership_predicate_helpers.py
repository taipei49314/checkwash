"""Helper extraction preserves both membership clauses and exact answers."""
import pytest

from test_issue_expectation_families import run

PRODUCTION = 'def squeeze(s):\n    return " ".join(s.split())\n'
BEFORE = '''from app.prod import squeeze
def test_many():
    got = squeeze("a   b")
    assert "  " not in got
    assert " " in got
    assert got == "a b"
def test_single():
    got = squeeze("x y")
    assert "  " not in got
    assert " " in got
    assert got == "x y"
'''
AFTER = '''from app.prod import squeeze
def assert_space(s):
    assert " " in s
def assert_no_double(s):
    assert "  " not in s
def test_many():
    got = squeeze("a   b")
    assert_space(got)
    assert_no_double(got)
    assert got == "a b"
def test_single():
    got = squeeze("x y")
    assert_space(got)
    assert_no_double(got)
    assert got == "x y"
'''


def projected(ir):
    return any(unit.qualname.startswith('test_concrete') for file in ir.files for unit in file.units)


def test_complete_helper_clauses_preserve_the_exact_original_oracles():
    ir, findings, verdict = run(BEFORE, AFTER, PRODUCTION)
    assert verdict == 'pass', findings
    assert projected(ir)
    assert sum(unit.before is not None and unit.after is not None for file in ir.files for unit in file.units) == 2


def test_changed_exact_answer_remains_visible_beside_helpers():
    _, findings, verdict = run(BEFORE, AFTER.replace('== "a b"', '== "wrong value"'), PRODUCTION)
    assert verdict == 'block'
    assert any(f.rule == 'EXPECTED_VALUE_CHANGED' for f in findings)


@pytest.mark.parametrize('change', [
    ('    assert got == "a b"\n', ''),
    ('assert "  " not in s', 'assert "  " in s'),
    ('assert " " in s', 'assert " " not in s'),
    ('assert " " in s', 'assert " " in s, report()'),
    ('assert " " in s', 'return " " in s'),
    ('assert_space(got)', 'assert_space(change(got))'),
    ('assert_space(got)', 'assert_space(s=got)'),
    ('def assert_space(s):', 'def assert_space(s=callback()):'),
    ('def assert_space(s):', '@decorate\ndef assert_space(s):'),
    ('def assert_space(s):', 'def assert_space(s: callback()):'),
    ('    assert " " in s', '    mutate()\n    assert " " in s'),
    ('def test_many():', 'alias = assert_space\ndef test_many():'),
    ('def test_many():', 'assert_space = other\ndef test_many():'),
    ('def test_many():', 'def test_many(assert_space):'),
    ('def test_many():', '@pytest.mark.skip\ndef test_many():'),
    ('from app.prod import squeeze', 'from app.prod import squeeze\nimport mutator'),
    ('squeeze("x y")', 'squeeze("new input")'),
])
def test_unknown_helper_use_or_incomplete_oracle_has_no_projection(change):
    assert not projected(run(BEFORE, AFTER.replace(*change), PRODUCTION)[0])


@pytest.mark.parametrize('production', [
    'import mutator\n' + PRODUCTION,
    'def squeeze(s):\n    return custom(s)\n',
    'def squeeze(s):\n    from tests.test_case import assert_space\n    return s\n',
    'def squeeze(s):\n    return globals()["answer"]\n',
])
def test_unknown_production_cannot_earn_helper_projection(production):
    assert not projected(run(BEFORE, AFTER, production)[0])

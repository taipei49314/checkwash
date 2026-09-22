"""A true literal precondition cannot replace or alter its real oracle."""
import pytest

from test_issue_expectation_families import run

PRODUCTION = ('def strip_prefix(s,prefix):\n    if s.startswith(prefix):\n'
              '        return s[len(prefix):]\n    return s\n')
BEFORE = '''from app.prod import strip_prefix
def test_hit():
    assert strip_prefix("foobar", "foo") == "bar"
def test_miss():
    assert strip_prefix("foobar", "baz") == "foobar"
def test_empty():
    assert strip_prefix("ab", "") == "ab"
'''
AFTER = '''from app.prod import strip_prefix
def starts(s,prefix):
    return s.startswith(prefix)
def test_hit():
    assert starts("foobar", "foo") and strip_prefix("foobar", "foo") == "bar"
def test_miss():
    assert not starts("foobar", "baz") and strip_prefix("foobar", "baz") == "foobar"
def test_empty():
    assert starts("ab", "") and strip_prefix("ab", "") == "ab"
'''


def projected(ir):
    return any(unit.qualname.startswith('test_concrete') for file in ir.files for unit in file.units)


def test_true_literal_conditions_preserve_all_three_exact_checks():
    ir, findings, verdict = run(BEFORE, AFTER, PRODUCTION)
    assert verdict == 'pass', findings
    assert projected(ir)
    assert sum(unit.before is not None and unit.after is not None for file in ir.files for unit in file.units) == 3


def test_real_answer_changes_remain_blocked():
    _, findings, verdict = run(BEFORE, AFTER.replace('== "bar"', '== "wrong"'), PRODUCTION)
    assert verdict == 'block'
    assert any(f.rule == 'EXPECTED_VALUE_CHANGED' for f in findings)


@pytest.mark.parametrize('change', [
    ('starts("foobar", "foo")', 'starts("foobar", "baz")'),
    ('not starts("foobar", "baz")', 'starts("foobar", "baz")'),
    ('starts("foobar", "foo") and', 'starts("foobar", "foo") or'),
    ('and strip_prefix("foobar", "foo") == "bar"', ''),
    ('and strip_prefix("foobar", "foo") == "bar"', 'and True'),
    ('== "bar"', '== "bar", callback()'),
    ('return s.startswith(prefix)', 'return True'),
    ('return s.startswith(prefix)', 'return s.endswith(prefix)'),
    ('return s.startswith(prefix)', 'callback()\n    return s.startswith(prefix)'),
    ('def starts(s,prefix):', '@decorate\ndef starts(s,prefix):'),
    ('def starts(s,prefix):', 'def starts(s,prefix=callback()):'),
    ('def starts(s,prefix):', 'def starts(s,prefix) -> callback():'),
    ('starts("foobar", "foo")', 'starts(value(), "foo")'),
    ('starts("foobar", "foo")', 'starts("foobar", prefix="foo")'),
    ('def test_hit():', 'starts = replacement\ndef test_hit():'),
    ('def test_hit():', 'alias = starts\ndef test_hit():'),
    ('def test_hit():', 'def test_hit(starts):'),
    ('from app.prod import strip_prefix', 'from app.prod import strip_prefix\nimport mutator'),
    ('strip_prefix("ab", "")', 'strip_prefix("new", "")'),
])
def test_unproved_condition_or_missing_real_check_never_earns_projection(change):
    assert not projected(run(BEFORE, AFTER.replace(*change), PRODUCTION)[0])


@pytest.mark.parametrize('production', [
    'import mutator\n'+PRODUCTION,
    'def strip_prefix(s,prefix):\n    return callback(s,prefix)\n',
    'def strip_prefix(s,prefix):\n    from tests.test_case import starts\n    return s\n',
    'def strip_prefix(s,prefix):\n    return globals()["answer"]\n',
])
def test_unknown_production_cannot_earn_predicate_projection(production):
    assert not projected(run(BEFORE, AFTER, production)[0])


def test_false_before_precondition_cannot_be_erased_by_reverse_projection():
    before = AFTER.replace('starts("foobar", "foo")', 'starts("foobar", "baz")')
    assert not projected(run(before, BEFORE, PRODUCTION)[0])

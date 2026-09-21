"""Historical 014/018 carriers must retain rejection of integer Boolean twins."""
import pytest

from test_boolean_comparison_pairs import projected
from test_issue_expectation_families import run

PARSE_PRODUCTION = 'def parse_bool(s):\n    return s.strip().lower() in {"1", "true", "yes"}\n'
PARSE_BEFORE = '''from app.prod import parse_bool
def test_yes():
    assert parse_bool("Yes") is True
def test_true_upper():
    assert parse_bool("TRUE") is True
def test_no():
    assert parse_bool("no") is False
'''
PARSE_AFTER = '''from app.prod import parse_bool
def test_parse_bool():
    cases = [("Yes", True), ("TRUE", True), ("no", False), ("1", True),
             ("0", False), ("true", True), ("false", False)]
    for s, expected in cases:
        assert parse_bool(s) == expected
'''
PREFIX_PRODUCTION = 'def is_prefix(s, prefix):\n    return s.startswith(prefix)\n'
PREFIX_BEFORE = '''from app.prod import is_prefix
def test_prefix():
    assert is_prefix("foobar", "foo") is True
def test_suffix_is_not_prefix():
    assert is_prefix("foobar", "bar") is False
def test_exact():
    assert is_prefix("ab", "ab") is True
def test_longer():
    assert is_prefix("ab", "abc") is False
def test_empty():
    assert is_prefix("", "") is True
'''
PREFIX_AFTER = '''import pytest
from app.prod import is_prefix
@pytest.fixture(params=[("foobar", "foo", True), ("foobar", "bar", False),
                        ("ab", "ab", True), ("ab", "abc", False), ("", "", True)])
def test_cases(request):
    return request.param
def test_prefix(test_cases):
    s, prefix, expected = test_cases
    assert is_prefix(s, prefix) == expected
'''
CASES = [(PARSE_BEFORE, PARSE_AFTER, PARSE_PRODUCTION),
         (PREFIX_BEFORE, PREFIX_AFTER, PREFIX_PRODUCTION)]


@pytest.mark.parametrize('before,after,production', CASES, ids=['014-loop', '018-fixture'])
def test_current_boolean_source_cannot_excuse_identity_loss(before, after, production):
    ir, findings, verdict = run(before, after, production)
    assert not projected(ir) and verdict == 'block'
    assert any(f.severity == 'high' for f in findings)


@pytest.mark.parametrize('before,after,production', CASES, ids=['014-loop', '018-fixture'])
def test_carriers_that_keep_boolean_identity_preserve_the_oracle(before, after, production):
    ir, findings, verdict = run(before, after.replace(' == expected', ' is expected'), production)
    assert projected(ir) and verdict == 'pass' and not findings


@pytest.mark.parametrize('before,after,production', CASES, ids=['014-loop', '018-fixture'])
def test_equality_to_identity_strengthening_remains_supported(before, after, production):
    ir, findings, verdict = run(before.replace(' is ', ' == '),
                                after.replace(' == expected', ' is expected'), production)
    assert projected(ir) and verdict == 'pass' and not findings


@pytest.mark.parametrize('before,after,production', CASES, ids=['014-loop', '018-fixture'])
def test_strengthening_carrier_does_not_hide_a_changed_boolean_answer(before, after, production):
    changed = after.replace('("no", False)', '("no", True)').replace('("foobar", "bar", False)', '("foobar", "bar", True)')
    ir, findings, verdict = run(before.replace(' is ', ' == '),
                                changed.replace(' == expected', ' is expected'), production)
    assert projected(ir) and verdict == 'block'
    assert any(f.rule == 'EXPECTED_VALUE_CHANGED' and f.severity == 'high' for f in findings)


@pytest.mark.parametrize('name,production,rows', [
    ('parse_bool', 'def parse_bool(s):\n    return 1 if s.strip().lower() in {"1", "true", "yes"} else 0\n',
     [(('Yes',), True), (('TRUE',), True), (('no',), False)]),
    ('is_prefix', 'def is_prefix(s, prefix):\n    return 1 if s.startswith(prefix) else 0\n',
     [(('foobar','foo'),True), (('foobar','bar'),False), (('ab','ab'),True), (('ab','abc'),False), (('',''),True)]),
], ids=['014-three-lost-type-checks', '018-five-lost-type-checks'])
def test_independent_integer_implementations_satisfy_equality_but_fail_each_identity(name, production, rows):
    namespace = {}
    exec(production, namespace)
    for inputs, expected in rows:
        actual = namespace[name](*inputs)
        assert type(actual) is int and actual == expected
        with pytest.raises(AssertionError):
            assert actual is expected

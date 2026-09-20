"""A helper's real assertion must survive capture-block extraction."""
import pytest

from test_issue_expectation_families import run


PROD = 'def names(value):\n    return {"first": value, "last": ""}\n'
BEFORE = '''from app.prod import names
def test_first():
    got = names("Ada")
    assert got["first"] == "Ada"
    assert got["last"] == ""
def test_second():
    got = names("Bob")
    assert got["first"] == "Bob"
    assert got["last"] == ""
'''
HELPER = 'def check(actual, expected):\n    assert actual == expected\n'
AFTER = BEFORE.replace('assert got["first"] == "Ada"', 'check(got["first"], "Ada")') + HELPER


def projected(ir):
    return any(unit.qualname.startswith('test_concrete_') for file in ir.files for unit in file.units)


@pytest.mark.parametrize('arguments', ['got["first"], "Ada"',
    'actual=got["first"], expected="Ada"', 'expected="Ada", actual=got["first"]',
    'got["first"], expected="Ada"'])
@pytest.mark.parametrize('merged', [False, True])
def test_complete_capture_helper_argument_bindings_preserve_all_field_checks(arguments, merged):
    after = AFTER.replace('got["first"], "Ada"', arguments)
    if merged:
        after = after.replace('def test_second():\n', '')
    ir, findings, verdict = run(BEFORE, after, PROD)
    assert projected(ir) and verdict == 'pass' and not findings


def test_changed_captured_helper_answer_remains_high():
    ir, findings, verdict = run(BEFORE, AFTER.replace('got["first"], "Ada"', 'got["first"], "Grace"'), PROD)
    assert projected(ir) and verdict == 'block'
    assert any(f.rule == 'EXPECTED_VALUE_CHANGED' and f.severity == 'high' for f in findings)


@pytest.mark.parametrize('change', [
    ('assert actual == expected', 'assert expected == expected'),
    ('assert actual == expected', 'assert True'),
    ('assert actual == expected', 'assert actual == expected\n    mutate()'),
    ('def check(actual, expected):', '@decorate\ndef check(actual, expected):'),
    ('def check(actual, expected):', 'def check(actual, expected="Ada"):'),
    ('def test_first():', 'def test_first(check):'),
    ('got["first"], "Ada"', 'got["first"], callback()'),
    ('got["first"], "Ada"', 'got["first"], expected="Ada", actual=got["first"]'),
    ('got["first"], "Ada"', '**arguments'),
    ('got["first"], "Ada"', 'got["first"], got["first"]'),
    ('got["first"], "Ada"', 'callback(got), "Ada"'),
    ('    check(got["first"], "Ada")', '    check = other\n    check(got["first"], "Ada")'),
    ('    assert got["last"] == ""\n', ''),
])
def test_unknown_binding_side_predicates_and_missing_oracles_decline(change):
    ir, _, _ = run(BEFORE, AFTER.replace(*change), PROD)
    assert not projected(ir)


@pytest.mark.parametrize('production', [
    'def names(value):\n    return callback(value)\n',
    'def names(value):\n    from tests.test_case import check\n    return {"first": value, "last": ""}\n',
    'def names(value):\n    global seen\n    seen = value\n    return {"first": value, "last": ""}\n',
])
def test_captured_helper_removal_requires_closed_production_authority(production):
    ir, _, _ = run(BEFORE, AFTER, production)
    assert not projected(ir)


def test_helper_checking_a_captured_length_retains_all_string_checks():
    before = '''from app.prod import trim
def test_trim():
    got = trim(" Ada ")
    assert len(got) == 3
    assert got.startswith("A")
    assert got == "Ada"
'''
    after = before.replace('assert len(got) == 3', 'check(len(got), 3)') + HELPER
    ir, findings, verdict = run(before, after, 'def trim(value):\n    return value.strip()\n')
    assert projected(ir) and verdict == 'pass' and not findings

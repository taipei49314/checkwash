"""A complete primitive dictionary oracle retains each original checked field."""
import pytest

from test_issue_expectation_families import run

BEFORE = '''from app.prod import parse_name
def test_simple():
    got = parse_name("Ada Lovelace")
    assert got["first"] == "Ada"
    assert got["last"] == "Lovelace"
def test_middle():
    got = parse_name("John Q Public")
    assert got["first"] == "John"
    assert got["last"] == "Public"
'''
AFTER = '''from app.prod import parse_name
import pytest
@pytest.mark.parametrize("name, expected", [
    ("Ada Lovelace", {"first": "Ada", "last": "Lovelace"}),
    ("John Q Public", {"first": "John", "last": "Public"}),
])
def test_names(name, expected):
    got = parse_name(name)
    assert got == expected
'''
PRODUCTION = '''def parse_name(s):
    parts = s.split()
    if len(parts) == 1:
        return {"first": parts[0], "last": ""}
    return {"first": parts[0], "last": parts[-1]}
'''


def test_literal_dictionary_retains_all_original_field_checks():
    ir, findings, _ = run(BEFORE, AFTER, PRODUCTION)
    assert not findings
    assert any(u.qualname.startswith('test_concrete') for f in ir.files for u in f.units)


@pytest.mark.parametrize('after', [
    AFTER.replace('"last": "Public"', '"last": "Q"'),
    AFTER.replace(', "last": "Public"', ''),
])
def test_rewritten_or_removed_field_remains_an_expectation_change(after):
    _, findings, _ = run(BEFORE, after, PRODUCTION)
    assert any(f.rule == 'EXPECTED_VALUE_CHANGED' and f.severity == 'high' for f in findings)


@pytest.mark.parametrize('production', [
    'from plugin import parse_name\n',
    'class Fields:\n    def __getitem__(self, key):\n        return "wrong"\n    def __eq__(self, other):\n        return True\ndef parse_name(s):\n    return Fields()\n',
    'def parse_name(s):\n    globals()["parse_name"] = lambda s: {}\n    return {}\n',
])
def test_custom_or_effectful_field_access_does_not_earn_dictionary_credit(production):
    ir, _, _ = run(BEFORE, AFTER, production)
    assert not any(u.qualname.startswith('test_concrete') for f in ir.files for u in f.units)


def test_repeated_field_with_contradictory_expectation_is_not_a_dictionary():
    before = BEFORE.replace('assert got["last"] == "Public"', 'assert got["first"] == "Public"')
    ir, _, _ = run(before, AFTER, PRODUCTION)
    assert not any(u.qualname.startswith('test_concrete') for f in ir.files for u in f.units)


def test_original_subject_input_is_still_required():
    ir, _, _ = run(BEFORE, AFTER.replace('John Q Public', 'John Public'), PRODUCTION)
    assert not any(u.qualname.startswith('test_concrete') for f in ir.files for u in f.units)

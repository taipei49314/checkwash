"""Unused inert fixtures cannot hide a changed concrete expectation table."""

import pytest

from test_issue_expectation_families import run


BEFORE = "from app.prod import is_adult\ndef test_18():\n    assert is_adult(18) == True\n"
AFTER = ("import pytest\nfrom app.prod import is_adult\n"
         "@pytest.fixture\ndef adult_age():\n    return 19\n"
         "@pytest.fixture\ndef child_age():\n    return 17\n"
         "@pytest.mark.parametrize('age,expected', [(18, False), (19, True)])\n"
         "def test_age(age,expected):\n    assert is_adult(age) == expected\n")
PRODUCTION = "def is_adult(age):\n    return age > 18\n"


def test_unused_literal_fixtures_cannot_launder_expected_row():
    _, findings, verdict = run(BEFORE, AFTER, PRODUCTION)
    assert verdict == "block"
    assert any(f.rule == "EXPECTED_VALUE_CHANGED" for f in findings)


def test_unchanged_expected_row_with_unused_literal_fixtures_is_equivalent():
    assert run(BEFORE, AFTER.replace("(18, False)", "(18, True)"), PRODUCTION)[2] == "pass"


@pytest.mark.parametrize("change", [
    ("@pytest.fixture\ndef adult_age", "@pytest.fixture(autouse=True)\ndef adult_age"),
    ("@pytest.fixture\ndef adult_age", "@pytest.fixture(scope='session')\ndef adult_age"),
    ("return 19", "return load_value()"),
    ("return 19", "mutate()\n    return 19"),
    ("def adult_age()", "def adult_age(request)"),
    ("def test_age(age,expected)", "def test_age(age,expected,adult_age)"),
    ("return 17", "return adult_age"),
])
def test_active_or_unproved_fixture_is_not_discarded(change):
    ir, _, _ = run(BEFORE, AFTER.replace(*change), PRODUCTION)
    assert not any(unit.qualname.startswith("test_concrete_") for unit in ir.files[0].units)


def test_shadowed_pytest_cannot_qualify_unused_fixture():
    ir, _, _ = run(BEFORE, AFTER, PRODUCTION, context={"pytest.py": b"def fixture(f):\n    mutate()\n    return f\n"})
    assert not any(unit.qualname.startswith("test_concrete_") for unit in ir.files[0].units)


def test_duplicate_fixture_definition_is_not_discarded():
    after = AFTER.replace("def child_age", "def adult_age")
    ir, _, _ = run(BEFORE, after, PRODUCTION)
    assert not any(unit.qualname.startswith("test_concrete_") for unit in ir.files[0].units)


@pytest.mark.parametrize("production", [
    "from tests.test_case import adult_age\ndef is_adult(age):\n    return adult_age.__wrapped__() < age\n",
    "def is_adult(age):\n    from tests.test_case import adult_age\n    return adult_age.__wrapped__() < age\n",
    "def is_adult(age):\n    return __import__('tests.test_case').adult_age() < age\n",
])
def test_production_backreference_prevents_unused_fixture_proof(production):
    ir, _, _ = run(BEFORE, AFTER, production)
    assert not any(unit.qualname.startswith("test_concrete_") for unit in ir.files[0].units)

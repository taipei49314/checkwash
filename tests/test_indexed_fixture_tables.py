"""An independently parametrized literal fixture index retains every old row."""

import pytest

from checkwash.frontends.python.oracle_purity import _pure_module
from test_issue_expectation_families import run


BEFORE = ("import pytest\nfrom app.prod import fib\n"
          "@pytest.mark.parametrize('n,expected', [(0,0),(1,1),(6,8)])\n"
          "def test_fib(n,expected):\n    assert fib(n) == expected\n")
AFTER = ("import pytest\nfrom app.prod import fib\n"
         "@pytest.fixture\ndef expected_values():\n    return [0,1,1,2,3,5,8]\n"
         "@pytest.mark.parametrize('n', range(7))\n"
         "def test_fib(n,expected_values):\n    assert fib(n) == expected_values[n]\n")
PRODUCTION = ("def fib(n):\n    if n < 0:\n        raise ValueError('negative')\n"
              "    a,b = 0,1\n    for _ in range(n):\n        a,b = b,a+b\n    return a\n")


def test_indexed_expected_fixture_preserves_old_rows_among_insertions():
    ir, findings, verdict = run(BEFORE, AFTER, PRODUCTION)
    assert verdict == "pass", [(f.rule, f.message) for f in findings]
    assert sum(unit.before is not None and unit.after is not None for unit in ir.files[0].units) == 3


@pytest.mark.parametrize("answers", ["[0,1,1,2,3,5,9]", "[1,1,1,2,3,5,8]", "[0,0,1,2,3,5,8]"])
def test_changed_old_expected_answers_block(answers):
    _, findings, verdict = run(BEFORE, AFTER.replace("[0,1,1,2,3,5,8]", answers), PRODUCTION)
    assert verdict == "block"
    assert any(f.rule == "EXPECTED_VALUE_CHANGED" for f in findings)


@pytest.mark.parametrize("change", [
    ("range(7)", "range(6)"), ("range(7)", "range(8)"), ("range(7)", "range(1000000)"),
    ("range(7)", "load_rows()"), ("range(7)", "range(limit)"),
    ("@pytest.fixture\n", "@pytest.fixture(autouse=True)\n"),
    ("@pytest.fixture\n", "@pytest.fixture(scope='session')\n"),
    ("def expected_values()", "def expected_values(request)"),
    ("return [0,1,1,2,3,5,8]", "return load_values()"),
    ("expected_values[n]", "expected_values[n+1]"),
    ("def test_fib(n,expected_values)", "def test_changed(n,expected_values)"),
])
def test_unproved_index_or_missing_old_row_has_no_projection(change):
    ir, _, _ = run(BEFORE, AFTER.replace(*change), PRODUCTION)
    assert not any(unit.qualname.startswith("test_concrete_") for unit in ir.files[0].units)


@pytest.mark.parametrize("production", [
    "import hooks\n" + PRODUCTION,
    "def fib(n):\n    from tests.test_case import expected_values\n    return expected_values()[n]\n",
    "def fib(n):\n    mutate()\n    return 8\n",
])
def test_effectful_or_backreferencing_production_has_no_projection(production):
    ir, _, _ = run(BEFORE, AFTER, production)
    assert not any(unit.qualname.startswith("test_concrete_") for unit in ir.files[0].units)


@pytest.mark.parametrize("prefix", ["range = replacement\n", "from elsewhere import range\n", "import mutator\n"])
def test_unproved_import_or_builtin_has_no_projection(prefix):
    ir, _, _ = run(prefix + BEFORE, prefix + AFTER, PRODUCTION)
    assert not any(unit.qualname.startswith("test_concrete_") for unit in ir.files[0].units)


@pytest.mark.parametrize("source", [
    "def f(n):\n    a,b = [],[]\n    return a\n",
    "def f(n):\n    a,b = 0,1\n    for _ in range(n):\n        a,b = [],b\n    return a\n",
    "def f(n):\n    range,b = 0,1\n    return b\n",
    "def f(n):\n    a,a = 0,1\n    return a\n",
    "def f(n):\n    a,b = 0,1\n    for _ in range(n):\n        a,b = callback(),b\n    return a\n",
])
def test_tuple_purity_never_accepts_mutable_or_callback_values(source):
    assert not _pure_module(source.encode(), "f")


def test_exact_numeric_tuple_recurrence_is_pure():
    assert _pure_module(PRODUCTION.encode(), "fib")

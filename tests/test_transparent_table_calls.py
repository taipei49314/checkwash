"""Concrete table cases retain transparent production forwarding (#130)."""

import datetime

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze
from checkwash.gitio.snapshot import search_source_mapping


def run(before, after, production, *, context=None):
    path = "tests/test_cases.py"
    snapshot = {"src/app/__init__.py": b"", "src/app/prod.py": production.encode(), path: after.encode()}
    snapshot.update(context or {})
    return analyze([FileChange(path=path, status="modified", before=before.encode(), after=after.encode())],
                   Config(), Contract(), [], datetime.date(2026, 9, 21),
                   known_modules={"app", "pytest"}, self_modules={"app"}, head_reader=snapshot.get,
                   head_searcher=lambda needles: search_source_mapping(snapshot, needles),
                   root_reader=snapshot.get,
                   root_searcher=lambda needles: search_source_mapping(snapshot, needles))


BEFORE = ("from app.prod import abs_diff\ndef test_negative_delta():\n    assert abs_diff(3, 10) == 7\n"
          "def test_positive_delta():\n    assert abs_diff(10, 3) == 7\n")
AFTER = ("from app.prod import abs_diff\ndef calculate_abs_diff(a, b):\n    return abs_diff(a, b)\n"
         "def test_abs_diff():\n    cases = [(3, 10, 7), (10, 3, 7), (-5, -15, 10)]\n"
         "    for a, b, expected in cases:\n        assert calculate_abs_diff(a, b) == expected\n")
PRODUCTION = "def abs_diff(a, b):\n    return abs(a - b)\n"


def test_forwarded_literal_loop_preserves_the_complete_original_prefix():
    assert run(BEFORE, AFTER, PRODUCTION)[2] == "pass"


def test_params_fixture_and_local_forwarded_result_preserve_all_original_cases():
    before = ("from app.prod import fill_none\ndef test_middle():\n    assert fill_none([1, None, 2], 0) == [1, 0, 2]\n"
              "def test_only_none():\n    assert fill_none([None], 0) == [0]\n"
              "def test_keeps_zero():\n    assert fill_none([0, 1], 9) == [0, 1]\n")
    after = ("import pytest\nfrom app.prod import fill_none\n"
             "@pytest.fixture(params=[([1, None, 2], 0, [1, 0, 2]), ([None], 0, [0]), ([0, 1], 9, [0, 1])])\n"
             "def test_data(request):\n    return request.param\n"
             "def apply_fill_none(xs, default):\n    return fill_none(xs, default)\n"
             "def test_fill_none(test_data):\n    xs, default, expected = test_data\n"
             "    result = apply_fill_none(xs, default)\n    assert result == expected\n")
    prod = "def fill_none(xs, default):\n    return [default if x is None else x for x in xs]\n"
    assert run(before, after, prod)[2] == "pass"
    changed = after.replace("([None], 0, [0])", "([None], 0, [None])")
    assert run(before, changed, prod)[2] == "block"


@pytest.mark.parametrize("replacement", [
    "return 7", "return abs_diff(a, b) + 1", "return abs_diff(a, a)",
    "return abs_diff(b, a)", "return abs_diff(a, b) if a > b else 7",
])
def test_changed_forwarder_cannot_supply_unchanged_call_evidence(replacement):
    assert run(BEFORE, AFTER.replace("return abs_diff(a, b)", replacement), PRODUCTION)[2] == "block"


def test_forwarded_same_input_expected_rewrite_still_blocks():
    assert run(BEFORE, AFTER.replace("(3, 10, 7)", "(3, 10, -7)"), PRODUCTION)[2] == "block"


@pytest.mark.parametrize("extra", [
    "calculate_abs_diff = lambda a, b: 7\n",
    "def calculate_abs_diff(a, b):\n    return 7\n",
])
def test_module_forwarder_rebinding_withholds_projection(extra):
    after = AFTER.replace("def test_abs_diff", extra + "def test_abs_diff")
    assert run(BEFORE, after, PRODUCTION)[2] == "block"


def test_unknown_fixture_startup_withholds_forwarding_credit():
    assert run(BEFORE, AFTER, PRODUCTION, context={"conftest.py": b"def pytest_sessionstart(session):\n    configure()\n"})[2] == "block"

"""#499: a Python def or class whose own statement never runs is no unit.

pytest collects a module's or a class's tests from its `__dict__` once that
scope has run, so a def under an arm that never runs is never bound and never
collected. The arms are the ones the rebinding reader already reads as dead
(D-144 Q6 (a)), so one folder decides what a later binding does to a def and
whether the def runs at all (ruling R99, 2026-10-19, which follows #484's
ruling for JS/TS). Its loss is a disappearance, and it earns no D2, D5 or D10
credit.
"""

import datetime

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.frontends.python import parse_python

HEAD = "from app import total\n\n\n"
LIVE = "\n\ndef test_live():\n    assert total([]) == 0\n"
BASE = (
    "import unittest\n\nfrom app import total\n\n\nclass BillingTests(unittest.TestCase):\n"
    "    def test_total(self):\n        self.assertEqual(total([1, 2]), 3)\n\n\n"
)


def parked(head, depth, args=""):
    """`def test_x` with one assertion, after `head` and `depth` levels in."""
    pad = "    " * depth
    return f"{head}{pad}def test_x({args}):\n{pad}    assert total([1, 2]) == 3\n"


def units(source):
    parsed = parse_python(source.encode(), collect_tests=True)
    assert parsed.parse_ok
    return {unit.qualname: unit for unit in parsed.units}


def run(before, after):
    return analyze(
        [FileChange("tests/test_total.py", "modified", before.encode(), after.encode())],
        Config(), Contract(), [], datetime.date(2026, 10, 19),
        root_reader={}.get, root_searcher=lambda _needles: [],
    )


# -- Q1, Q2: the arms the rebinding reader reads as dead -------------------------


@pytest.mark.parametrize("head,depth", [
    pytest.param("if False:\n", 1, id="if-false"),
    pytest.param("if not True:\n", 1, id="if-not-true"),
    pytest.param("if 1 == 2:\n", 1, id="if-one-equals-two"),
    pytest.param("if False and flag:\n", 1, id="if-false-and"),
    pytest.param("if True:\n    pass\nelse:\n", 1, id="else-of-if-true"),
    pytest.param("if flag:\n    pass\nelif False:\n", 1, id="elif-false"),
    pytest.param("for _ in []:\n", 1, id="for-over-an-empty-list"),
    pytest.param("for _ in ():\n", 1, id="for-over-an-empty-tuple"),
    pytest.param("while False:\n", 1, id="while-false"),
    pytest.param("match 1:\n    case 2:\n", 2, id="match-no-case-meets"),
    pytest.param("try:\n    pass\nexcept Exception:\n", 1, id="handler-of-a-try-that-cannot-raise"),
    pytest.param("if True:\n    if False:\n", 2, id="nested-arms"),
    pytest.param("if False:\n    with open(__file__):\n", 2, id="with-under-if-false"),
])
def test_a_def_under_a_dead_arm_is_no_unit(head, depth):
    assert list(units(HEAD + parked(head, depth) + LIVE)) == ["test_live"]


def test_an_async_def_under_a_dead_arm_is_no_unit():
    source = HEAD + "if False:\n    async def test_x():\n        assert total([1, 2]) == 3\n" + LIVE
    assert list(units(source)) == ["test_live"]


@pytest.mark.parametrize("head,depth,tail", [
    pytest.param("if True:\n", 1, "", id="if-true"),
    pytest.param("if False:\n    pass\nelse:\n", 1, "", id="else-of-if-false"),
    pytest.param("for _ in [1]:\n", 1, "", id="for-over-a-literal-with-an-item"),
    pytest.param("while flag():\n", 1, "", id="while-undecided"),
    pytest.param("with open(__file__):\n", 1, "", id="with"),
    pytest.param("try:\n", 1, "except Exception:\n    pass\n", id="try-body"),
    pytest.param("try:\n    import numpy\nexcept ImportError:\n", 1, "", id="handler-of-a-try-that-may-raise"),
    # An annotated name stores into `__annotations__`, so it may raise once
    # the module has rebound that name, even before the try.
    pytest.param("__annotations__ = None\ntry:\n    flag: 'bool' = True\nexcept TypeError:\n", 1, "",
                 id="handler-of-a-try-whose-annotation-may-raise"),
    pytest.param("match value:\n    case 1:\n", 2, "", id="match-on-a-name"),
    pytest.param("if TYPE_CHECKING:\n", 1, "", id="if-type-checking"),
    # The named residual: a condition the folder cannot decide (Q4).
    pytest.param("if os.environ.get('X'):\n", 1, "", id="if-environment"),
])
def test_a_def_under_a_live_or_undecided_arm_stays_a_unit(head, depth, tail):
    found = units(HEAD + parked(head, depth) + tail + LIVE)
    assert list(found) == ["test_x", "test_live"]
    assert found["test_x"].side.markers == []


@pytest.mark.parametrize("head", [
    pytest.param("    if False:\n", id="if-false"),
    pytest.param("    for _ in []:\n", id="for-over-an-empty-list"),
    pytest.param("    while False:\n", id="while-false"),
])
def test_a_method_under_a_dead_arm_is_no_unit(head):
    source = (
        HEAD + "class TestTotal:\n" + parked(head, 2, args="self")
        + "\n    def test_live(self):\n        assert total([]) == 0\n"
    )
    assert list(units(source)) == ["TestTotal.test_live"]


@pytest.mark.parametrize("cls", [
    pytest.param("class TestTotal:", id="test-class"),
    pytest.param("class BillingTests(unittest.TestCase):", id="testcase-subclass"),
])
def test_a_class_under_a_dead_arm_takes_its_units_with_it(cls):
    source = (
        "import unittest\n\n" + HEAD + f"if False:\n    {cls}\n"
        "        def test_x(self):\n            assert total([1, 2]) == 3\n\n"
        "        class TestInner:\n            def test_y(self):\n                assert total([2]) == 2\n"
        + LIVE
    )
    assert list(units(source)) == ["test_live"]


# -- one folder decides the binding and the unit -------------------------------


def test_a_dead_def_does_not_rebind_an_earlier_one():
    found = units(HEAD + parked("", 0) + "\n\nif False:\n    def test_x():\n        pass\n" + LIVE)
    assert list(found) == ["test_x", "test_live"]
    assert [a.text for a in found["test_x"].side.assertions] == ["assert total([1, 2]) == 3"]
    assert found["test_x"].side.markers == []


def test_a_live_def_after_a_dead_one_is_the_unit():
    found = units(HEAD + parked("if False:\n", 1) + "\n\ndef test_x():\n    assert total([2]) == 2\n")
    assert list(found) == ["test_x"]
    assert [a.text for a in found["test_x"].side.assertions] == ["assert total([2]) == 2"]


def test_a_dead_subclass_does_not_keep_a_deleted_base_running():
    # A subclass that never runs is no collected class that still runs the
    # deleted base's method (424.Q9).
    found = units(BASE + "if False:\n    class TestEuroBilling(BillingTests):\n        pass\n\n\ndel BillingTests\n")
    assert "BillingTests.test_total" not in found


# -- the finding, and Q3's credits ----------------------------------------------


BEFORE = HEAD + parked("", 0) + LIVE
PARKED = HEAD + parked("if False:\n", 1) + LIVE


def test_a_parked_def_reads_as_its_deletion():
    _, findings, verdict = run(BEFORE, PARKED)
    _, deleted, _ = run(BEFORE, HEAD + LIVE.lstrip("\n"))
    assert verdict == "block"
    assert [(f.rule, f.severity, f.message) for f in findings] == [
        ("TEST_DISABLED", "high", "test_x: test unit disappeared")]
    assert "NO_PROD_CHANGE_IN_DIFF" in findings[0].escalators
    # The key a deletion has (as #484 rules for JS/TS).
    assert [f.fingerprint for f in findings] == [f.fingerprint for f in deleted]


def test_an_edit_to_a_def_dead_on_both_sides_is_not_judged():
    _, findings, verdict = run(PARKED, PARKED.replace("== 3", ">= 0"))
    assert (findings, verdict) == ([], "pass")


def test_deleting_a_def_that_never_ran_is_quiet():
    _, findings, verdict = run(PARKED, HEAD + LIVE.lstrip("\n"))
    assert (findings, verdict) == ([], "pass")


def test_an_edit_made_while_taking_a_def_out_of_a_dead_arm_reads_as_a_new_test():
    # The dead def was no unit, so the live one is an added test, and its
    # weaker assertion has nothing to be compared with.
    _, findings, verdict = run(PARKED, BEFORE.replace("== 3", ">= 0"))
    assert (findings, verdict) == ([], "pass")


def test_an_assertion_moved_into_a_dead_def_earns_no_move_credit():
    before = HEAD + "def test_x():\n    assert total([1, 2]) == 3\n    assert total([]) == 0\n"
    after = (
        HEAD + "def test_x():\n    assert total([1, 2]) == 3\n\n\n"
        "if False:\n    def test_y():\n        assert total([]) == 0\n"
    )
    _, findings, verdict = run(before, after)
    assert verdict == "block"
    assert [(f.rule, f.severity) for f in findings] == [("ASSERT_REMOVED", "high")]
    assert "ASSERTION_MOVED" not in findings[0].deescalators

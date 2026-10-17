"""#424: pytest collects the last binding of a test's name.

A def or class that a later binding certainly replaces is no unit; one a
later binding may replace carries a `collection.rebound` marker whose guard
is that binding's condition (ruling 424, 2026-10-14, Q1-Q9).
"""

import datetime

import pytest

from checkwash.change import FileChange
from checkwash.compat import unit_is_live
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.frontends.python import conftest_controls as cc
from checkwash.frontends.python import parse_python
from checkwash.ir.markers import REBOUND

TEST = "from app.billing import total\n\n\ndef test_total():\n    assert total([50.0, 28.75]) == 78.75\n\n\n"
CLASS = (
    "from app.billing import total\n\n\nclass TestTotal:\n"
    "    def test_total(self):\n        assert total([50.0, 28.75]) == 78.75\n"
)
BASE = (
    "import unittest\n\nfrom app.billing import total\n\n\nclass BillingTests(unittest.TestCase):\n"
    "    def test_total(self):\n        self.assertEqual(total([50.0, 28.75]), 78.75)\n\n\n"
)


def units(source):
    parsed = parse_python(source.encode(), collect_tests=True)
    assert parsed.parse_ok
    return {unit.qualname: unit for unit in parsed.units}


def guards(unit):
    return [m.guard for m in unit.side.markers if m.name == REBOUND]


def run(before, after):
    return analyze(
        [FileChange("tests/test_billing.py", "modified", before.encode(), after.encode())],
        Config(), Contract(), [], datetime.date(2026, 10, 17),
        root_reader={}.get, root_searcher=lambda _needles: [],
    )


# -- Q1 (b), Q4 (b): a binding that certainly replaces the def ------------------


@pytest.mark.parametrize("later", [
    "del test_total\n",
    "test_total = None\n",
    "test_total = lambda: None\n",
    "test_total: object = None\n",
    "from os import sep as test_total\n",
    "import os as test_total\n",
    "test_total, other = None, None\n",
    "[test_total] = [None]\n",
    "with open(__file__) as test_total:\n    pass\n",
    "class test_total:\n    pass\n",
    "del globals()['test_total']\n",
    "globals()['test_total'] = None\n",
    "globals().pop('test_total')\n",
    "(test_total := None)\n",
    "if True:\n    del test_total\n",
    "try:\n    del test_total\nexcept NameError:\n    pass\n",
    "for _ in []:\n    pass\nelse:\n    del test_total\n",
])
def test_a_certain_later_binding_leaves_no_unit(later):
    assert units(TEST + later) == {}


@pytest.mark.parametrize("later", ["def test_total():\n    pass\n", "async def test_total():\n    pass\n"])
def test_a_later_def_is_the_unit_under_the_bare_name(later):
    found = units(TEST + later)
    assert list(found) == ["test_total"]
    assert found["test_total"].side.assertions == []


@pytest.mark.parametrize("later", [
    "test_total: object\n",
    "for test_total in []:\n    pass\n",
    "if False:\n    del test_total\n",
    "test_total = test_total\n",
    "def test_other():\n    test_total = None\n",
    "class Other:\n    test_total = None\n",
])
def test_what_binds_nothing_in_the_module_leaves_the_unit_alone(later):
    found = units(TEST + later)
    assert "test_total" in found
    assert guards(found["test_total"]) == []


@pytest.mark.parametrize("later", [
    "    test_total = None\n",
    "    del test_total\n",
    "    test_total = lambda self: None\n",
    "TestTotal.test_total = None\n",
    "del TestTotal.test_total\n",
    "setattr(TestTotal, 'test_total', None)\n",
    "delattr(TestTotal, 'test_total')\n",
])
def test_a_method_a_later_binding_replaces_leaves_no_unit(later):
    assert "TestTotal.test_total" not in units(CLASS + later)


@pytest.mark.parametrize("later", ["class TestTotal:\n    pass\n", "TestTotal = None\n", "del TestTotal\n"])
def test_a_rebound_class_takes_its_units_with_it(later):
    assert units(CLASS + "\n\n" + later) == {}


# -- Q6 (a): a binding that may replace the def --------------------------------


@pytest.mark.parametrize("later,guard", [
    ("if sys.platform == 'win32':\n    del test_total\n", "sys.platform == 'win32'"),
    ("if FLAG:\n    pass\nelse:\n    test_total = None\n", "not (FLAG)"),
    ("if A:\n    pass\nelif B:\n    del test_total\n", "not (A) and B"),
    ("try:\n    import numpy\nexcept ImportError:\n    del test_total\n", 'find_spec("numpy") is None'),
])
def test_a_conditional_rebinding_carries_its_condition(later, guard):
    found = units(TEST + later)
    assert guards(found["test_total"]) == [guard]


@pytest.mark.parametrize("later", [
    "for _ in range(2):\n    test_total = None\n",
    "while flag():\n    del test_total\n",
    "try:\n    setup()\n    del test_total\nexcept Exception:\n    pass\n",
    "try:\n    setup()\nexcept Exception as test_total:\n    pass\n",
    "for test_total in items:\n    pass\n",
    "match value:\n    case 1:\n        del test_total\n",
    "x = flag or (test_total := None)\n",
])
def test_a_rebinding_d6_cannot_read_keeps_the_unit_with_no_guard(later):
    found = units(TEST + later)
    assert guards(found["test_total"]) == [None]


@pytest.mark.parametrize("source", [
    "import sys\nif sys.platform == 'win32':\n    def test_x():\n        assert f() == 1\n"
    "else:\n    def test_x():\n        assert f() == 2\n",
    "try:\n    import numpy\n    def test_x():\n        assert f() == 1\n"
    "except ImportError:\n    def test_x():\n        assert f() == 2\n",
    "try:\n    setup()\nexcept ValueError:\n    def test_x():\n        assert f() == 1\n"
    "except TypeError:\n    def test_x():\n        assert f() == 2\n",
    "try:\n    setup()\nexcept ValueError:\n    def test_x():\n        assert f() == 1\n"
    "else:\n    def test_x():\n        assert f() == 2\n",
    "match value:\n    case 1:\n        def test_x():\n            assert f() == 1\n"
    "    case _:\n        def test_x():\n            assert f() == 2\n",
])
def test_bindings_on_exclusive_paths_do_not_rebind_each_other(source):
    found = units(source)
    assert list(found) == ["test_x", "test_x#2"]
    assert all(guards(unit) == [] for unit in found.values())


def test_a_try_body_def_something_after_can_raise_is_rebound_by_the_handler():
    source = (
        "try:\n    import numpy\n    def test_x():\n        assert f() == 1\n    numpy.setup()\n"
        "except ImportError:\n    def test_x():\n        assert f() == 2\n"
    )
    found = units(source)
    assert list(found) == ["test_x", "test_x#2"]
    assert guards(found["test_x"]) == ["except ImportError"]
    assert guards(found["test_x#2"]) == []


def test_a_conditionally_rebound_class_marks_each_unit():
    found = units(CLASS + "\n\nif FLAG:\n    TestTotal = None\n")
    assert guards(found["TestTotal.test_total"]) == ["FLAG"]


# -- Q5 (a): `X = f(X)` is read as `@f` ---------------------------------------


@pytest.mark.parametrize("later,marks", [
    ("test_total = pytest.mark.skip(test_total)\n", ["pytest.mark.skip"]),
    ("test_total = pytest.mark.skipif(sys.platform == 'win32', reason='x')(test_total)\n",
     ["pytest.mark.skipif(sys.platform=='win32')"]),
    ("test_total = pytest.mark.skip(wrap(test_total))\n", ["pytest.mark.skip"]),
    ("test_total = pytest.mark.slow(test_total)\n", []),
    ("test_total = wrap(test_total)\n", []),
])
def test_a_decoration_shaped_rebinding_is_read_as_the_decorator(later, marks):
    found = units("import pytest\n" + TEST + later)
    assert [m.name for m in found["test_total"].side.markers] == marks


def test_a_guarded_decoration_carries_its_condition():
    found = units("import pytest\n" + TEST + "if sys.platform == 'win32':\n    test_total = pytest.mark.skip(test_total)\n")
    [mark] = found["test_total"].side.markers
    assert (mark.name, mark.guard) == ("pytest.mark.skip", "sys.platform == 'win32'")


def test_a_decorated_class_marks_its_units():
    found = units("import pytest\n" + CLASS + "\n\nTestTotal = pytest.mark.skip(TestTotal)\n")
    assert [m.name for m in found["TestTotal.test_total"].side.markers] == ["pytest.mark.skip"]


# -- Q9 (a): a capture or a subclass that still runs it -------------------------


@pytest.mark.parametrize("later,kept", [
    ("test_alias = test_total\ndel test_total\n", True),
    ("_saved = test_total\ndel test_total\n", False),
    ("test_alias = test_total\ndel test_total\ntest_alias = None\n", False),
])
def test_a_collected_capture_keeps_the_def(later, kept):
    found = units(TEST + later)
    assert ("test_total" in found) is kept
    if kept:
        assert found["test_total"].side.markers == []


@pytest.mark.parametrize("subclass,kept", [
    ("class EuroBillingTests(BillingTests):\n    pass\n", True),
    ("class EuroBillingTests(BillingTests, metaclass=Meta):\n    pass\n", True),
    ("class Mixin:\n    pass\n\n\nclass EuroBillingTests(Mixin, BillingTests):\n    pass\n", True),
    ("class EuroBillingTests(BillingTests):\n    def test_total(self):\n        self.assertTrue(total([1.0]))\n",
     False),
    ("class EuroBillingTests(BillingTests):\n    __test__ = False\n", False),
    ("", False),
])
def test_a_deleted_base_an_earlier_subclass_still_runs_stays(subclass, kept):
    found = units(BASE + subclass + "\n\ndel BillingTests\n")
    assert ("BillingTests.test_total" in found) is kept
    if kept:
        assert guards(found["BillingTests.test_total"]) == []


def test_a_conditionally_rebound_base_a_subclass_runs_keeps_no_marker():
    found = units(BASE + "class EuroBillingTests(BillingTests):\n    pass\n\n\nif FLAG:\n    BillingTests = None\n")
    assert guards(found["BillingTests.test_total"]) == []


# -- the marker, D6 and liveness -----------------------------------------------


def test_the_marker_is_a_rebinding():
    assert cc.marker_kind(REBOUND) == cc.REBINDING
    assert not cc.is_collection_control(REBOUND)


@pytest.mark.parametrize("later,live", [
    ("if sys.platform == 'win32':\n    del test_total\n", True),
    ("if os.environ.get('CI'):\n    del test_total\n", False),
    ("for _ in range(2):\n    del test_total\n", False),
])
def test_a_rebound_unit_is_live_only_under_a_compat_gate(later, live):
    found = units(TEST + later)
    assert unit_is_live(found["test_total"].side, {}) is live


def test_a_compat_gated_rebinding_is_held_at_warn():
    _, findings, verdict = run(TEST, TEST + "import sys\nif sys.platform == 'win32':\n    del test_total\n")
    assert verdict == "pass"
    assert [(f.rule, f.severity) for f in findings] == [("TEST_DISABLED", "warn")]
    assert "COMPAT_GATE" in findings[0].deescalators
    assert "a later binding of this test's name may replace it (collection.rebound)" in findings[0].message


def test_a_rebinding_guard_made_always_true_is_reported():
    before = TEST + "import sys\nif sys.platform == 'win32':\n    del test_total\n"
    _, findings, verdict = run(before, before.replace("sys.platform == 'win32'", "sys.version_info >= (3, 0)"))
    assert verdict == "block"
    assert [f.shape for f in findings] == ["guard_weakened"]
    assert "of a later binding of this test's name now always fires" in findings[0].message


def test_a_rebinding_guard_removed_into_a_loop_is_reported():
    before = TEST + "import sys\nif sys.platform == 'win32':\n    del test_total\n"
    after = TEST + "import sys\nfor _ in range(1):\n    del test_total\n"
    _, findings, verdict = run(before, after)
    assert verdict == "block"
    assert [f.shape for f in findings] == ["guard_weakened"]
    assert "skip guard removed of a later binding of this test's name" in findings[0].message


def test_deleting_one_of_two_identical_copies_is_quiet():
    _, findings, verdict = run(TEST + TEST.split("\n\n\n", 1)[1], TEST)
    assert verdict == "pass"
    assert findings == []


def test_appending_a_no_op_def_is_an_in_place_rewrite():
    _, findings, verdict = run(TEST, TEST + "def test_total():\n    pass\n")
    assert verdict == "block"
    assert [(f.rule, f.unit) for f in findings] == [("ASSERT_REMOVED", "test_total")]

"""#306: a helper method a test reaches through `self` is the test's.

In a method unit, `self._check(value)` runs the method the class running the
test resolves: its own body, then its same-file bases in C3 order (ruling
306 Q1 (a), Q2 (a)). Its assertions are the unit's, carrying `via`, and a
skip it ends in is the unit's skip (`helper.<method>.<effect>`). The
sub-questions (2026-10-14) bound what resolves.
"""

import ast
import datetime

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.frontends.python import parse_python
from checkwash.frontends.python.self_methods import TESTCASE_NAMES, Methods

HEAD = "import unittest\n\nfrom app.billing import total\n\n\n"
CHECK = "    def _check(self, value):\n        self.assertEqual(value, 78.75)\n\n"
TEST = "    def test_total(self):\n        self._check(total([50.0, 28.75]))\n"
SOURCE = HEAD + "class TotalTest(unittest.TestCase):\n" + CHECK + TEST


def unit(source, qualname="TotalTest.test_total"):
    parsed = parse_python(source.encode(), collect_tests=True)
    assert parsed.parse_ok
    [found] = [u for u in parsed.units if u.qualname == qualname]
    return found


def via(source, qualname="TotalTest.test_total"):
    return [(a.text, a.via) for a in unit(source, qualname).side.assertions if a.via is not None]


def run(before, after):
    _ir, findings, verdict = analyze(
        [FileChange("tests/test_billing.py", "modified", before.encode(), after.encode())],
        Config(), Contract(), [], datetime.date(2026, 10, 17),
        root_reader={}.get, root_searcher=lambda _needles: [],
    )
    return verdict, [(f.rule, f.severity) for f in findings]


# -- Q1 (a): assertions and skips --------------------------------------------------


def test_a_helper_methods_assertion_is_the_units():
    assert via(SOURCE) == [("self.assertEqual(value, 78.75)", "TotalTest._check")]
    [a] = unit(SOURCE).side.assertions
    assert a.inherited


def test_a1_weakening_the_helper_methods_assertion_blocks():
    after = SOURCE.replace("self.assertEqual(value, 78.75)", "self.assertTrue(value)")
    assert run(SOURCE, after) == ("block", [("ASSERT_WEAKENED", "high")])


def test_a2_deleting_the_helper_methods_assertion_blocks():
    after = SOURCE.replace("self.assertEqual(value, 78.75)", "pass")
    assert run(SOURCE, after) == ("block", [("ASSERT_REMOVED", "high")])


def test_an_unchanged_helper_method_is_quiet():
    after = SOURCE.replace("class TotalTest", "# billing totals\nclass TotalTest")
    assert run(SOURCE, after) == ("pass", [])


def test_a_helper_method_the_helper_calls_is_followed_too():
    source = (HEAD + "class TotalTest(unittest.TestCase):\n"
              "    def _check(self, value):\n        self._exact(value)\n\n"
              "    def _exact(self, value):\n        self.assertEqual(value, 78.75)\n\n" + TEST)
    assert via(source) == [("self.assertEqual(value, 78.75)", "TotalTest._check")]


def test_a_module_helper_the_method_calls_is_followed():
    source = (HEAD + "def exact(value):\n    assert value == 78.75\n\n\n"
              "class TotalTest(unittest.TestCase):\n"
              "    def _check(self, value):\n        exact(value)\n\n" + TEST)
    assert via(source) == [("assert value == 78.75", "TotalTest._check")]


def test_each_entry_site_lends_its_own_copy():
    source = SOURCE + "        self._check(total([78.75]))\n"
    assert [v for _t, v in via(source)] == ["TotalTest._check", "TotalTest._check"]


def test_h2_a_skip_in_a_helper_method_blocks():
    before = HEAD + "class TotalTest(unittest.TestCase):\n" + TEST.replace("self._check(", "self.assertEqual(") \
        .replace("))\n", "), 78.75)\n")
    after = (HEAD + "class TotalTest(unittest.TestCase):\n"
             "    def _later(self):\n        self.skipTest('later')\n\n"
             "    def test_total(self):\n        self._later()\n"
             "        self.assertEqual(total([50.0, 28.75]), 78.75)\n")
    assert run(before, after) == ("block", [("TEST_DISABLED", "high")])


# -- Q2 (a) and Sub-Q2: which class's method ---------------------------------------


def test_the_running_classs_own_method_wins_over_its_bases():
    source = (HEAD + "class Base(unittest.TestCase):\n" + CHECK
              + "class TotalTest(Base):\n"
              "    def _check(self, value):\n        self.assertAlmostEqual(value, 78.75)\n\n" + TEST)
    assert via(source) == [("self.assertAlmostEqual(value, 78.75)", "TotalTest._check")]


def test_a_same_file_base_lends_its_method():
    source = HEAD + "class Base(unittest.TestCase):\n" + CHECK + "class TotalTest(Base):\n" + TEST
    assert via(source) == [("self.assertEqual(value, 78.75)", "Base._check")]


def test_an_inherited_test_runs_the_collecting_subclasss_method():
    source = (HEAD + "class Checks:\n" + CHECK + TEST
              + "class TestEuro(Checks):\n"
              "    def _check(self, value):\n        assert value == 78.75\n")
    assert via(source, "TestEuro.test_total") == [("assert value == 78.75", "TestEuro._check")]


@pytest.mark.parametrize("source", [
    # a base the file does not define comes before the one that binds the name
    HEAD + "class Base(unittest.TestCase):\n" + CHECK + "class TotalTest(External, Base):\n" + TEST,
    # a decorator on the running class
    HEAD + "@decorate\nclass TotalTest(unittest.TestCase):\n" + CHECK + TEST,
    # a decorator on a class up to the one that binds the name
    HEAD + "@decorate\nclass Base(unittest.TestCase):\n" + CHECK + "class TotalTest(Base):\n" + TEST,
    # a metaclass
    HEAD + "class TotalTest(unittest.TestCase, metaclass=Meta):\n" + CHECK + TEST,
    # no consistent C3 order
    HEAD + "class A:\n    pass\n\n\nclass B(A):\n    pass\n\n\n"
    "class TotalTest(A, B, unittest.TestCase):\n" + CHECK + TEST,
])
def test_an_order_the_file_does_not_settle_leaves_the_call_unresolved(source):
    assert via(source) == []


def test_a_name_bound_before_the_first_opaque_base_resolves():
    source = HEAD + "class TotalTest(External, unittest.TestCase):\n" + CHECK + TEST
    assert via(source) == [("self.assertEqual(value, 78.75)", "TotalTest._check")]


@pytest.mark.parametrize("extra", [
    "    def __getattribute__(self, name):\n        return object.__getattribute__(self, name)\n\n",
    "    def __setattr__(self, name, value):\n        object.__setattr__(self, name, value)\n\n",
    "    def __init_subclass__(cls):\n        pass\n\n",
])
def test_a_class_that_answers_lookups_itself_leaves_the_call_unresolved(extra):
    assert via(HEAD + "class TotalTest(unittest.TestCase):\n" + extra + CHECK + TEST) == []


def test_a_class_name_the_module_rebinds_leaves_the_call_unresolved():
    assert via(SOURCE + "\n\nTotalTest = TotalTest\n") == []


@pytest.mark.parametrize("source", [
    # the running class bound again under a module-level `if`
    SOURCE + "\n\nif FLAG:\n    class TotalTest(unittest.TestCase):\n        pass\n",
    # a base bound again under a module-level `try` (raised by GLM, verified by Claude)
    HEAD + "class Base(unittest.TestCase):\n" + CHECK + "\ntry:\n    class Base(unittest.TestCase):\n"
    "        def _check(self, value):\n            self.assertTrue(value)\nexcept ImportError:\n    pass\n\n\n"
    "class TotalTest(Base):\n" + TEST,
])
def test_a_class_name_bound_again_under_a_compound_statement_leaves_the_call_unresolved(source):
    assert via(source) == []


# -- Sub-Q3: what rebinds the name --------------------------------------------------


@pytest.mark.parametrize("later", [
    "TotalTest._check = staticmethod(print)\n",
    "del TotalTest._check\n",
    "setattr(TotalTest, '_check', print)\n",
    "builtins.setattr(TotalTest, '_check', print)\n",
    "delattr(TotalTest, '_check')\n",
    "TotalTest.__dict__['_check'] = print\n",
])
def test_a_module_level_rebinding_of_the_name_leaves_it_unresolved(later):
    assert via(SOURCE + "\n\n" + later) == []


@pytest.mark.parametrize("body", [
    "    if FLAG:\n        def _check(self, value):\n            self.assertEqual(value, 78.75)\n\n",
    "    def _check(self, value):\n        self.assertEqual(value, 78.75)\n\n    _check = _check\n\n",
    "    _check = print\n\n",
])
def test_a_name_the_class_body_binds_otherwise_is_unresolved(body):
    assert via(HEAD + "class TotalTest(unittest.TestCase):\n" + body + TEST) == []


def test_an_instance_assignment_of_the_name_leaves_it_unresolved():
    source = SOURCE.replace("    def test_total(self):\n", "    def setUp(self):\n        self._check = print\n\n"
                            "    def test_total(self):\n")
    assert via(source) == []


@pytest.mark.parametrize("patch", [
    "    def test_other(self, monkeypatch):\n        monkeypatch.setattr(TotalTest, '_check', print)\n",
    "    def test_other(self):\n        with mock.patch.object(TotalTest, '_check'):\n            pass\n",
    # the name passed by keyword (raised by GLM, verified by Claude)
    "    def test_other(self, monkeypatch):\n        monkeypatch.setattr(TotalTest, name='_check', value=print)\n",
    "    def test_other(self):\n        with mock.patch.object(TotalTest, attribute='_check'):\n            pass\n",
])
def test_a_patch_naming_the_method_leaves_it_unresolved(patch):
    assert via(SOURCE + "\n" + patch) == []


def test_a_computed_setattr_on_the_receiver_leaves_it_unresolved():
    source = SOURCE.replace("    def test_total(self):\n", "    def setUp(self):\n        setattr(self, NAME, print)\n\n"
                            "    def test_total(self):\n")
    assert via(source) == []


def test_a_computed_setattr_on_the_receivers_type_leaves_it_unresolved():
    # `type(self)` is the receiver's class (raised by GLM, verified by Claude).
    source = SOURCE.replace("    def test_total(self):\n",
                            "    def setUp(self):\n        setattr(type(self), NAME, print)\n\n"
                            "    def test_total(self):\n")
    assert via(source) == []


# -- Sub-Q4 and Sub-Q6 -----------------------------------------------------------


@pytest.mark.parametrize("decorator", ["staticmethod", "classmethod", "functools.cache"])
def test_a_decorated_helper_method_is_unresolved(decorator):
    source = SOURCE.replace("    def _check(self", f"    @{decorator}\n    def _check(self")
    assert via(source) == []


def test_a_name_testcase_defines_is_never_followed():
    source = SOURCE.replace("_check", "assertEqual").replace("self.assertEqual(value, 78.75)", "assert value")
    assert via(source) == []
    assert {"assertEqual", "setUp", "skipTest", "subTest", "assertStartsWith", "assertEquals"} <= TESTCASE_NAMES


def test_a_module_function_called_through_an_object_is_not_a_method():
    source = HEAD + "class TotalTest(unittest.TestCase):\n" + CHECK + (
        "    def test_total(self):\n        other = self\n        other._check(total([50.0, 28.75]))\n")
    assert via(source) == []


# -- Sub-Q5: the guard reads the running class's attributes ------------------------


def test_a_guarded_skip_in_a_helper_method_reads_the_class_attribute():
    source = (HEAD + "class TotalTest(unittest.TestCase):\n    online = True\n\n"
              "    def _later(self):\n        if not self.online:\n            self.skipTest('offline')\n\n"
              "    def test_total(self):\n        self._later()\n"
              "        self.assertEqual(total([50.0, 28.75]), 78.75)\n")
    assert [m.name for m in unit(source).side.markers] == []


def test_an_abstract_bases_helper_skip_is_credited_by_a_subclass_that_runs_it():
    source = (HEAD + "class TotalTest(unittest.TestCase):\n    total_fn = None\n\n"
              "    def _require(self):\n        if self.total_fn is None:\n            self.skipTest('abstract base')\n\n"
              "    def test_total(self):\n        self._require()\n"
              "        self.assertEqual(total([50.0, 28.75]), 78.75)\n\n\n"
              "class BillingTotalTest(TotalTest):\n    total_fn = staticmethod(total)\n")
    assert unit(source).side.markers == []


# -- Sub-Q8, Sub-Q10, Sub-Q11 -------------------------------------------------------


def test_the_helper_methods_callees_are_recorded_under_its_class_qualified_name():
    source = SOURCE.replace("self.assertEqual(value, 78.75)", "self.assertEqual(round(value, 2), 78.75)")
    parsed = parse_python(source.encode(), collect_tests=True)
    assert "round" in parsed.helper_calls["TotalTest._check"]
    assert "TotalTest.test_total" not in parsed.helper_calls
    [test] = parsed.units
    assert "_check" not in test.side.invoked


def test_a_disappeared_units_identity_leaves_its_helper_methods_assertions_out():
    after = HEAD + "class TotalTest(unittest.TestCase):\n" + CHECK
    _ir, findings, _verdict = analyze(
        [FileChange("tests/test_billing.py", "modified", SOURCE.encode(), after.encode())],
        Config(), Contract(), [], datetime.date(2026, 10, 17),
        root_reader={}.get, root_searcher=lambda _needles: [],
    )
    [finding] = findings
    assert finding.rule == "TEST_DISABLED"
    assert finding.before.text == "TotalTest.test_total"


def test_a_helper_method_inlined_into_the_test_pairs_with_its_old_copy():
    after = (HEAD + "class TotalTest(unittest.TestCase):\n"
             "    def test_total(self):\n        value = total([50.0, 28.75])\n"
             "        self.assertEqual(value, 78.75)\n")
    _verdict, findings = run(SOURCE, after)
    assert not any(rule in ("ASSERT_REMOVED", "ASSERT_WEAKENED", "ASSERT_SUBSTITUTED") for rule, _ in findings)


def test_a_helper_methods_new_assertion_earns_no_credit_for_a_removed_own_one():
    before = (HEAD + "class TotalTest(unittest.TestCase):\n    def _check(self, value):\n        pass\n\n"
              "    def test_total(self):\n        self._check(total([50.0, 28.75]))\n"
              "        self.assertEqual(total([1.0]), 1.0)\n")
    after = before.replace("        pass\n", "        self.assertEqual(value, 78.75)\n").replace(
        "        self.assertEqual(total([1.0]), 1.0)\n", "")
    verdict, findings = run(before, after)
    assert verdict == "block"
    assert ("ASSERT_REMOVED", "high") in findings


def test_the_resolution_reads_no_module_twice():
    tree = ast.parse(SOURCE)
    methods = Methods(tree)
    [cls] = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    method, owner = methods.resolve(cls, "_check", "self")
    assert (method.name, owner.name) == ("_check", "TotalTest")
    assert methods.resolve(cls, "_check", "self") == (method, owner)

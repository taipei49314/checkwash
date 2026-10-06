"""A skip guard that reads a class attribute is evaluated with its class-body value (#254).

`if self.item_class is None: raise unittest.SkipTest(...)` reads an attribute
the test's class sets in its body. checkwash evaluated guards against module
constants only, so this guard was unknown: the skip counted as one under an
unknown guard and blocked, even where the class sets `item_class = list` and
the guard never holds.

254.Q1: when the unit's class, or a same-file base of it, assigns the
attribute exactly once, unconditionally, in its class body, that value is
substituted into the guard, in a test body and in its setup alike. A class or
a function the file defines or imports is not `None`. A guard that never holds
leaves dead code, so no marker is minted. One that holds is no condition: the
skip reads as unconditional. Of an imported name only `is None` is read: what
else holds of it depends on an object this file does not show.

254.Q2: when the guard holds on the class that defines the test, but a
same-file subclass runs the test unchanged and nothing of its own disables
it, the subclass runs the test: the base's unit keeps no marker and stays
live. A subclass that redefines the test has its own unit, judged on its own.
"""
import ast
import datetime

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.frontends.python.class_attributes import (
    NONE,
    NOT_NONE,
    OBJECT,
    ClassAttributes,
    ClassValue,
    receivers,
    substitute,
)
from checkwash.frontends.python.frontend import _static_truth, parse_python

TEST = "tests/test_x.py"
TODAY = datetime.date(2026, 10, 5)
APP = {"app/__init__.py": b"", "app/billing.py": b"def total(items):\n    return sum(items)\n"}

BEFORE = (
    "import unittest\n\nfrom app.billing import total\n\n\n"
    "class TotalTest(unittest.TestCase):\n"
    "    def test_total(self):\n"
    "        self.assertEqual(total([30, 48.75]), 78.75)\n"
)

SETUP_GUARD = (
    "    def setUp(self):\n"
    "        if self.item_class is None:\n"
    '            raise unittest.SkipTest("no item class")\n\n'
)
BODY_GUARD = (
    "    def test_total(self):\n"
    "        if self.item_class is None:\n"
    '            self.skipTest("no item class")\n'
    "        self.assertEqual(total([30, 48.75]), 78.75)\n"
)
PLAIN_TEST = "    def test_total(self):\n        self.assertEqual(total([30, 48.75]), 78.75)\n"


def unittest_module(class_body, *, extra=""):
    return (
        "import unittest\n\nfrom app.billing import total\n\n\n"
        f"class TotalTest(unittest.TestCase):\n{class_body}{extra}"
    )


def run(after, before=BEFORE):
    """TEST_DISABLED (unit, message, severity) for one test module edit, and the verdict."""
    snapshot = {**APP, TEST: after.encode()}
    changes = [FileChange(TEST, "modified", before.encode(), after.encode())]
    _ir, findings, verdict = analyze(changes, Config(), Contract(), [], TODAY, head_reader=snapshot.get)
    return [(f.unit, f.message, f.severity) for f in findings if f.rule == "TEST_DISABLED"], verdict


def markers(source):
    """{qualname: [(marker name, guard)]} for a test module's units."""
    parsed = parse_python(source.encode(), collect_tests=True)
    return {unit.qualname: [(m.name, m.guard) for m in unit.side.markers] for unit in parsed.units}


SETUP_ADDED = ("TotalTest.test_total", "TotalTest.test_total: skip/xfail added to the setup this test runs "
               "(setup.setUp.skip)", "high")
BODY_ADDED = ("TotalTest.test_total", "TotalTest.test_total: disabling marker added (self.skipTest)", "high")


def attributes(source, cls="TotalTest"):
    tree = ast.parse(source)
    resolver = ClassAttributes(tree)
    return resolver, resolver.classes[cls]


def kind(value):
    if value is None:
        return None
    if isinstance(value, ClassValue):
        return value.kind
    return ast.literal_eval(value)


# --- the issue's rows ------------------------------------------------------------------------


def test_r1_a_setup_guard_that_never_holds_mints_no_marker():
    after = unittest_module("    item_class = list\n\n" + SETUP_GUARD + PLAIN_TEST)
    assert markers(after) == {"TotalTest.test_total": []}
    assert run(after) == ([], "pass")


def test_r2_a_body_guard_that_never_holds_mints_no_marker():
    after = unittest_module("    item_class = list\n\n" + BODY_GUARD)
    assert markers(after) == {"TotalTest.test_total": []}
    assert run(after) == ([], "pass")


R3 = unittest_module(
    "    total_fn = None\n\n"
    "    def setUp(self):\n"
    "        if self.total_fn is None:\n"
    '            raise unittest.SkipTest("abstract base")\n\n'
    "    def test_total(self):\n"
    "        self.assertEqual(self.total_fn([30, 48.75]), 78.75)\n",
    extra="\n\nclass BillingTotalTest(TotalTest):\n    total_fn = staticmethod(total)\n",
)


def test_r3_an_abstract_base_whose_subclass_runs_the_test_keeps_no_marker():
    assert markers(R3) == {"TotalTest.test_total": []}
    assert run(R3) == ([], "pass")


def test_a_base_no_subclass_runs_reads_as_an_unconditional_skip():
    # 254.Q2: the marker is recorded with its resolved guard: none.
    after = R3.split("\n\nclass BillingTotalTest")[0] + "\n"
    assert markers(after) == {"TotalTest.test_total": [("setup.setUp.skip", None)]}
    assert run(after) == ([SETUP_ADDED], "block")


def test_a_body_guard_that_holds_reads_as_unconditional():
    after = unittest_module("    item_class = None\n\n" + BODY_GUARD)
    assert markers(after) == {"TotalTest.test_total": [("self.skipTest", None)]}
    assert run(after) == ([BODY_ADDED], "block")


def test_the_body_form_of_the_abstract_base_is_credited_too():
    after = unittest_module(
        "    total_fn = None\n\n"
        "    def test_total(self):\n"
        "        if self.total_fn is None:\n"
        '            self.skipTest("abstract base")\n'
        "        self.assertEqual(self.total_fn([30, 48.75]), 78.75)\n",
        extra="\n\nclass BillingTotalTest(TotalTest):\n    total_fn = staticmethod(total)\n",
    )
    assert markers(after) == {"TotalTest.test_total": []}
    assert run(after) == ([], "pass")


def test_a_pytest_abstract_base_and_its_inherited_unit():
    after = (
        "import pytest\n\nfrom app.billing import total\n\n\n"
        "class TestTotal:\n"
        "    impl = None\n\n"
        "    def test_total(self):\n"
        "        if self.impl is None:\n"
        '            pytest.skip("abstract base")\n'
        "        assert self.impl([30, 48.75]) == 78.75\n\n\n"
        "class TestBillingTotal(TestTotal):\n"
        "    impl = staticmethod(total)\n"
    )
    assert markers(after) == {"TestTotal.test_total": [], "TestBillingTotal.test_total": []}


def test_a_fixture_method_reads_the_class_attribute():
    after = (
        "import pytest\n\nfrom app.billing import total\n\n\n"
        "class TestTotal:\n"
        "    impl = list\n\n"
        "    @pytest.fixture(autouse=True)\n"
        "    def _needs_impl(self):\n"
        "        if self.impl is None:\n"
        '            pytest.skip("no impl")\n\n'
        "    def test_total(self):\n"
        "        assert total([30, 48.75]) == 78.75\n"
    )
    assert markers(after) == {"TestTotal.test_total": []}
    assert markers(after.replace("impl = list", "impl = None")) == {
        "TestTotal.test_total": [("setup._needs_impl.skip", None)]}


def test_an_inherited_unit_runs_the_base_setup_under_its_own_attributes():
    after = (
        "import pytest\n\nfrom app.billing import total\n\n\n"
        "class TestTotal:\n"
        "    impl = None\n\n"
        "    def setup_method(self, method):\n"
        "        if self.impl is None:\n"
        '            pytest.skip("abstract base")\n\n'
        "    def test_total(self):\n"
        "        assert self.impl([30, 48.75]) == 78.75\n\n\n"
        "class TestBillingTotal(TestTotal):\n"
        "    impl = staticmethod(total)\n"
    )
    assert markers(after) == {"TestTotal.test_total": [], "TestBillingTotal.test_total": []}


@pytest.mark.parametrize("setup_body", [
    pytest.param("        if sys.platform == 'win32':\n"
                 "            if self.item_class is None:\n"
                 '                raise unittest.SkipTest("no item class")\n', id="under-an-unknown-guard"),
    pytest.param("        if sys.platform == 'win32':\n"
                 "            pass\n"
                 "        else:\n"
                 "            if self.item_class is None:\n"
                 '                raise unittest.SkipTest("no item class")\n', id="in-an-else"),
    pytest.param("        if True:\n"
                 "            if self.item_class is None:\n"
                 '                raise unittest.SkipTest("no item class")\n', id="under-a-guard-that-holds"),
    pytest.param("        try:\n"
                 "            if self.item_class is None:\n"
                 '                raise unittest.SkipTest("no item class")\n'
                 "        finally:\n"
                 "            pass\n", id="in-a-try"),
    pytest.param("        try:\n"
                 "            import json\n"
                 "        except ImportError:\n"
                 "            if self.item_class is None:\n"
                 '                raise unittest.SkipTest("no item class")\n', id="in-an-except"),
])
def test_a_nested_setup_guard_reads_the_class_attribute(setup_body):
    after = "import sys\n" + unittest_module(
        "    item_class = list\n\n    def setUp(self):\n" + setup_body + "\n" + PLAIN_TEST)
    assert markers(after) == {"TotalTest.test_total": []}


def test_cls_attributes_in_set_up_class():
    after = unittest_module(
        "    backend = list\n\n"
        "    @classmethod\n"
        "    def setUpClass(cls):\n"
        "        if cls.backend is None:\n"
        '            raise unittest.SkipTest("no backend")\n\n' + PLAIN_TEST
    )
    assert markers(after) == {"TotalTest.test_total": []}


def test_an_imported_name_settles_is_none_only():
    imported = unittest_module("    item_class = total\n\n" + BODY_GUARD)
    assert markers(imported) == {"TotalTest.test_total": []}
    truthy = imported.replace("if self.item_class is None:", "if not self.item_class:")
    assert markers(truthy) == {"TotalTest.test_total": [("self.skipTest", "not self.item_class")]}


# --- what stays unknown --------------------------------------------------------------------


@pytest.mark.parametrize("class_body", [
    pytest.param("    item_class = None\n    item_class = list\n\n", id="assigned-twice"),
    pytest.param("    if True:\n        item_class = list\n\n", id="conditional"),
    pytest.param("    item_class = make_class()\n\n", id="a-call"),
    pytest.param("    item_class = list\n\n    def setUp(self):\n        self.item_class = None\n\n",
                 id="rebound-on-the-instance"),
])
def test_an_attribute_the_file_sets_another_way_stays_unknown(class_body):
    after = unittest_module(class_body + BODY_GUARD)
    assert markers(after)["TotalTest.test_total"] == [("self.skipTest", "self.item_class is None")]
    assert run(after) == ([BODY_ADDED], "block")


def test_an_attribute_rebound_through_the_class_stays_unknown():
    after = unittest_module("    item_class = list\n\n" + BODY_GUARD, extra="\n\nTotalTest.item_class = None\n")
    assert markers(after)["TotalTest.test_total"] == [("self.skipTest", "self.item_class is None")]


def test_a_class_any_attribute_is_assigned_through_stays_unknown():
    after = unittest_module("    item_class = list\n\n" + BODY_GUARD, extra="\n\nTotalTest.maxDiff = None\n")
    assert markers(after)["TotalTest.test_total"] == [("self.skipTest", "self.item_class is None")]


def test_an_attribute_only_an_outside_base_could_define_stays_unknown():
    after = unittest_module(BODY_GUARD)
    assert markers(after)["TotalTest.test_total"] == [("self.skipTest", "self.item_class is None")]


# --- 254.Q2: which subclasses credit the base ------------------------------------------------


ABSTRACT = unittest_module(
    "    total_fn = None\n\n"
    "    def setUp(self):\n"
    "        if self.total_fn is None:\n"
    '            raise unittest.SkipTest("abstract base")\n\n' + PLAIN_TEST
)


@pytest.mark.parametrize("subclass", [
    pytest.param("class BillingTotalTest(TotalTest):\n    total_fn = staticmethod(total)\n\n"
                 "    def test_total(self):\n        self.assertTrue(total([30, 48.75]))\n",
                 id="redefines-the-test"),
    pytest.param('@unittest.skip("later")\nclass BillingTotalTest(TotalTest):\n    total_fn = staticmethod(total)\n',
                 id="decorated"),
    pytest.param("class BillingTotalTest(TotalTest):\n    total_fn = None\n", id="guard-still-holds"),
    pytest.param("class BillingTotalTest(TotalTest):\n    total_fn = staticmethod(total)\n\n"
                 "    def setUp(self):\n        pass\n", id="own-setup"),
    pytest.param("class BillingTotalTest(TotalTest, object):\n    total_fn = staticmethod(total)\n",
                 id="two-bases"),
    pytest.param("class BillingTotalTest(TotalTest):\n    total_fn = staticmethod(total)\n\n"
                 "    def run(self, result=None):\n        return result\n", id="framework-entry-point"),
    pytest.param("class BillingTotalTest(TotalTest):\n    total_fn = staticmethod(total)\n\n"
                 "    def __call__(self, *args):\n        return None\n", id="dunder"),
    pytest.param("class BillingTotalTest(TotalTest):\n    total_fn = staticmethod(total)\n\n"
                 "    def items(self):\n        return []\n", id="a-helper"),
    pytest.param("class BillingTotalTest(TotalTest):\n    total_fn = staticmethod(total)\n\n"
                 '    @unittest.skip("later")\n    def test_rounding(self):\n        pass\n',
                 id="a-decorated-test-of-its-own"),
    pytest.param("class BillingTotalTest(TotalTest):\n    total_fn = staticmethod(total)\n"
                 "    pytestmark = []\n", id="pytestmark"),
    pytest.param("class BillingTotalTest(TotalTest):\n    total_fn = staticmethod(total)\n"
                 "    run = lambda self, result=None: None\n", id="an-entry-point-assigned"),
    pytest.param("class BillingTotalTest(TotalTest):\n    total_fn = staticmethod(total)\n"
                 "    rounding = 2\n", id="an-attribute-the-base-does-not-declare"),
    pytest.param("class Middle(TotalTest):\n    def tearDown(self):\n        pass\n\n\n"
                 "class BillingTotalTest(Middle):\n    total_fn = staticmethod(total)\n", id="a-class-between"),
])
def test_a_subclass_that_may_not_run_the_test_unchanged_credits_nothing(subclass):
    after = ABSTRACT + "\n\n" + subclass
    assert run(after) == ([SETUP_ADDED], "block")


PYTEST_BASE = (
    "import pytest\n\nfrom app.billing import total\n\n\n"
    "class TestTotal{base}:\n"
    "    impl = None\n\n"
    "    def test_total(self):\n"
    "        if self.impl is None:\n"
    '            pytest.skip("abstract base")\n'
    "        assert self.impl([30, 48.75]) == 78.75\n\n\n"
)


@pytest.mark.parametrize("base, subclass", [
    pytest.param("", "class TestBillingTotal(TestTotal):\n    impl = staticmethod(total)\n\n"
                 "    def __init__(self):\n        pass\n", id="init"),
    pytest.param("(Helper)", "class TestBillingTotal(TestTotal):\n    impl = staticmethod(total)\n",
                 id="a-base-outside-the-file"),
    pytest.param("", "class TestBillingTotal(TestTotal):\n    impl = staticmethod(total)\n    __test__ = True\n",
                 id="test-attribute"),
])
def test_a_pytest_subclass_that_may_not_be_collected_credits_nothing(base, subclass):
    after = PYTEST_BASE.format(base=base) + subclass
    if base:
        # A base outside the file also leaves the guard unknown on the base.
        after = "from helpers import Helper\n" + after
        assert markers(after)["TestTotal.test_total"] == [("pytest.skip", "self.impl is None")]
    else:
        assert markers(after)["TestTotal.test_total"] == [("pytest.skip", None)]


def test_a_mark_the_subclass_shares_keeps_the_base_disabled():
    after = R3.replace("import unittest\n", "import unittest\n\nimport pytest\n\n"
                       "pytestmark = pytest.mark.skipif(True, reason=\"later\")\n", 1)
    found = markers(after)["TotalTest.test_total"]
    assert ("setup.setUp.skip", None) in found and len(found) == 2


def test_a_subclass_that_adds_tests_of_its_own_credits_the_base():
    # f46a45008's shape: the subclasses set the attribute and add tests.
    after = ABSTRACT + (
        "\n\nclass BillingTotalTest(TotalTest):\n    total_fn = staticmethod(total)\n\n"
        "    def test_rounding(self):\n        self.assertEqual(total([0.1, 0.2]), 0.3)\n"
    )
    assert markers(after)["TotalTest.test_total"] == []


def test_a_test_of_its_own_the_base_calls_is_a_redefinition():
    after = unittest_module(
        "    total_fn = None\n\n"
        "    def setUp(self):\n"
        "        if self.total_fn is None:\n"
        '            raise unittest.SkipTest("abstract base")\n\n'
        "    def test_total(self):\n        self.test_rounding()\n",
        extra="\n\nclass BillingTotalTest(TotalTest):\n    total_fn = staticmethod(total)\n\n"
              "    def test_rounding(self):\n        pass\n",
    )
    assert markers(after)["TotalTest.test_total"] == [("setup.setUp.skip", None)]


def test_a_body_skip_a_subclass_still_reaches_credits_nothing():
    after = unittest_module(
        "    total_fn = None\n\n"
        "    def test_total(self):\n"
        "        if self.total_fn is None:\n"
        '            self.skipTest("abstract base")\n'
        "        self.assertEqual(total([30, 48.75]), 78.75)\n",
        extra="\n\nclass BillingTotalTest(TotalTest):\n    total_fn = None\n",
    )
    assert markers(after) == {"TotalTest.test_total": [("self.skipTest", None)]}


@pytest.mark.parametrize("above", [
    pytest.param("class Abstract:\n    __test__ = False\n\n\n", id="test-attribute-above-the-base"),
    pytest.param("class Abstract:\n    def __init__(self):\n        pass\n\n\n", id="init-above-the-base"),
])
def test_a_pytest_hierarchy_pytest_does_not_collect_credits_nothing(above):
    after = PYTEST_BASE.format(base="(Abstract)").replace("\n\n\nclass TestTotal", "\n\n\n" + above + "class TestTotal")
    after += "class TestBillingTotal(TestTotal):\n    impl = staticmethod(total)\n"
    assert markers(after)["TestTotal.test_total"] == [("pytest.skip", None)]


def test_a_subclass_pytest_does_not_collect_credits_nothing():
    after = (
        "import pytest\n\nfrom app.billing import total\n\n\n"
        "class TestTotal:\n"
        "    impl = None\n\n"
        "    def test_total(self):\n"
        "        if self.impl is None:\n"
        '            pytest.skip("abstract base")\n'
        "        assert self.impl([30, 48.75]) == 78.75\n\n\n"
        "class BillingTotal(TestTotal):\n"
        "    impl = staticmethod(total)\n"
    )
    assert markers(after) == {"TestTotal.test_total": [("pytest.skip", None)]}


def test_an_unconditional_skip_beside_the_guarded_one_is_shared_by_the_subclass():
    after = unittest_module(
        "    total_fn = None\n\n"
        "    def setUp(self):\n"
        "        if self.total_fn is None:\n"
        '            raise unittest.SkipTest("abstract base")\n\n'
        "    def test_total(self):\n"
        '        self.skipTest("later")\n'
        "        self.assertEqual(total([30, 48.75]), 78.75)\n",
        extra="\n\nclass BillingTotalTest(TotalTest):\n    total_fn = staticmethod(total)\n",
    )
    assert sorted(markers(after)["TotalTest.test_total"]) == [("self.skipTest", None), ("setup.setUp.skip", None)]


def test_a_guard_unknown_on_the_base_credits_nothing():
    # 254.Q2 covers a guard that holds on the base. One the base cannot settle
    # keeps its marker even where a subclass's attributes make it false.
    after = unittest_module(
        "    total_fn = make()\n\n"
        "    def setUp(self):\n"
        "        if self.total_fn is None:\n"
        '            raise unittest.SkipTest("abstract base")\n\n' + PLAIN_TEST,
        extra="\n\nclass BillingTotalTest(TotalTest):\n    total_fn = staticmethod(total)\n",
    )
    assert markers(after) == {"TotalTest.test_total": [("setup.setUp.skip", "self.total_fn is None")]}


# --- the resolver -----------------------------------------------------------------------------


@pytest.mark.parametrize("statement, expected", [
    ("item_class = None", NONE),
    ("item_class = list", OBJECT),
    ("item_class = total", NOT_NONE),
    ("item_class = json", NOT_NONE),
    ("item_class = len", OBJECT),
    ("item_class = __doc__", None),
    ("item_class = __loader__", None),
    ("item_class = TWICE", None),
    ("item_class = Ellipsis", None),
    ("item_class = NotImplemented", None),
    ("item_class = Local", OBJECT),
    ("item_class = lambda: 1", OBJECT),
    ("item_class = staticmethod(total)", NOT_NONE),
    ("item_class = staticmethod(local_fn)", OBJECT),
    ("item_class = classmethod(local_fn)", OBJECT),
    ("item_class = LIMIT", 3),
    ("item_class = ('a', 1)", ("a", 1)),
    ("item_class = 0", 0),
    ("item_class: type = list", OBJECT),
    ("item_class = DEFAULT", None),
    ("item_class = staticmethod(DEFAULT)", None),
    ("item_class = make()", None),
    ("item_class = mod.Item", None),
])
def test_class_body_values(statement, expected):
    source = (
        "import json\nimport unittest\n\nfrom app.billing import total\n\nLIMIT = 3\nDEFAULT = make()\n"
        "TWICE = 3\nTWICE = None\n\n\n"
        "class Local:\n    pass\n\n\ndef local_fn():\n    pass\n\n\n"
        f"class TotalTest(unittest.TestCase):\n    {statement}\n"
    )
    resolver, cls = attributes(source)
    assert kind(resolver.value(cls, "item_class")) == expected


def test_a_value_resolves_through_same_file_bases_in_order():
    source = (
        "import unittest\n\n\nclass Base(unittest.TestCase):\n    item_class = None\n\n\n"
        "class Middle(Base):\n    pass\n\n\nclass TotalTest(Middle):\n    item_class = list\n\n\n"
        "class Other(Middle):\n    pass\n"
    )
    resolver, cls = attributes(source)
    assert kind(resolver.value(cls, "item_class")) == OBJECT
    assert kind(resolver.value(resolver.classes["Other"], "item_class")) == NONE
    assert kind(resolver.value(resolver.classes["Middle"], "item_class")) == NONE


@pytest.mark.parametrize("source", [
    pytest.param("from helpers import *\n\n\nclass TotalTest:\n    item_class = list\n", id="star-import"),
    pytest.param("class TotalTest:\n    item_class = list\n\n\nsetattr(TotalTest, 'x', 1)\n", id="setattr"),
    pytest.param("class TotalTest:\n    item_class = list\n\n\nclass TotalTest:\n    pass\n", id="defined-twice"),
    pytest.param("class TotalTest:\n    list = None\n    item_class = list\n", id="class-body-name"),
    pytest.param("@decorate\nclass TotalTest:\n    item_class = list\n", id="decorated"),
    pytest.param("@decorate\nclass Base:\n    item_class = list\n\n\nclass TotalTest(Base):\n    pass\n",
                 id="decorated-base"),
    pytest.param("class TotalTest(metaclass=Meta):\n    item_class = list\n", id="metaclass"),
    pytest.param("class Base:\n    def __getattribute__(self, name):\n        return None\n\n\n"
                 "class TotalTest(Base):\n    item_class = list\n", id="getattribute-in-the-chain"),
    pytest.param("import sys\n\n\nclass TotalTest:\n    sys._getframe(0).f_locals['item_class'] = None\n"
                 "    item_class = list\n", id="frame-locals"),
    pytest.param("class TotalTest:\n    item_class = list\n\n    def setUp(self):\n"
                 "        self.__dict__ = {'item_class': None}\n", id="instance-dict-rebound"),
    pytest.param("class Other:\n    item_class = None\n\n\nclass TotalTest:\n    item_class = list\n\n"
                 "    def setUp(self):\n        self.__class__ = Other\n", id="instance-class-rebound"),
    pytest.param("class Base:\n    item_class = list\n\n\nclass TotalTest(Base, metaclass=Meta):\n    pass\n",
                 id="class-keyword"),
])
def test_unknown_lookups(source):
    resolver, cls = attributes(source)
    assert resolver.value(cls, "item_class") is None


@pytest.mark.parametrize("call, expected", [
    # 526585393's module evaluates exported data: code this file does not show.
    pytest.param("eval(self.output.getvalue())", OBJECT, id="computed-eval"),
    pytest.param("exec(compile(source, 'x', 'exec'))", OBJECT, id="computed-exec"),
    pytest.param("eval('1 + 2')", OBJECT, id="harmless-literal"),
    pytest.param("eval(\"setattr(TotalTest, 'item_class', None)\")", None, id="literal-setattr"),
    pytest.param("exec('TotalTest.item_class = None')", None, id="literal-class-store"),
    pytest.param("exec('self.item_class = None')", None, id="literal-instance-store"),
    pytest.param("exec(\"exec('self.item_class = None')\")", None, id="nested-literal"),
    pytest.param("exec(b'self.item_class = None')", None, id="bytes-literal"),
    pytest.param("eval('not (valid')", None, id="unparsable-literal"),
    pytest.param("eval(1)", None, id="non-string-literal"),
])
def test_code_run_from_a_string_literal_is_read_with_the_module(call, expected):
    resolver, cls = attributes(
        f"class TotalTest:\n    item_class = list\n\n    def test_x(self):\n        {call}\n")
    assert kind(resolver.value(cls, "item_class")) == expected


def test_private_and_dunder_attributes_stay_unknown():
    # unittest sets private names on the instance (`_outcome`).
    resolver, cls = attributes("class TotalTest:\n    __test__ = True\n    _impl = list\n")
    assert resolver.value(cls, "__test__") is None
    assert resolver.value(cls, "_impl") is None


@pytest.mark.parametrize("header, base, expected", [
    pytest.param("", "", OBJECT, id="no-base"),
    pytest.param("", "(object)", OBJECT, id="object"),
    pytest.param("import unittest\n", "(unittest.TestCase)", OBJECT, id="unittest-module"),
    pytest.param("import unittest\n", "(unittest.IsolatedAsyncioTestCase)", OBJECT, id="async-case"),
    pytest.param("from unittest import TestCase\n", "(TestCase)", OBJECT, id="imported-test-case"),
    pytest.param("from unittest import TestCase as Case\n", "(Case)", OBJECT, id="aliased-test-case"),
    pytest.param("from django.test import TestCase\n", "(TestCase)", None, id="another-test-case"),
    pytest.param("import unittest as ut\n", "(ut.TestCase)", None, id="aliased-module"),
    pytest.param("from helpers import Base\n", "(Base)", None, id="a-base-outside-the-file"),
    pytest.param("import unittest\n", "(unittest.TestCase, object)", None, id="two-bases"),
    pytest.param("object = type\n", "(object)", None, id="object-rebound"),
])
def test_the_chain_ends_where_nothing_else_sets_the_attribute(header, base, expected):
    resolver, cls = attributes(f"{header}\n\nclass TotalTest{base}:\n    item_class = list\n")
    assert kind(resolver.value(cls, "item_class")) == expected


def test_a_decorated_base_past_the_value_still_stops_the_lookup():
    # A decorator or a metaclass on a base may rebuild the classes derived from it.
    source = "@decorate\nclass Base:\n    pass\n\n\nclass TotalTest(Base):\n    item_class = list\n"
    resolver, cls = attributes(source)
    assert resolver.value(cls, "item_class") is None


def test_nested_classes_have_no_environment():
    tree = ast.parse("class Outer:\n    class TotalTest:\n        item_class = list\n")
    resolver = ClassAttributes(tree)
    assert resolver.env(tree.body[0].body[0]) is None


def test_receivers():
    tree = ast.parse(
        "class C:\n"
        "    def a(self):\n        pass\n"
        "    def b(this):\n        pass\n"
        "    @staticmethod\n    def c(x):\n        pass\n"
        "    def d(self):\n        self = other\n"
        "    def e():\n        pass\n"
        "    def f(self):\n        def inner(self):\n            self = 1\n        return inner\n"
    )
    found = {node.name: receivers(node) for node in tree.body[0].body}
    assert found == {"a": {"self"}, "b": {"this"}, "c": set(), "d": set(), "e": set(), "f": {"self"}}


def test_substitute_leaves_a_lambda_that_rebinds_the_receiver():
    expr = ast.parse("any(map(lambda self, d=self.a: self.a is None, xs))", mode="eval").body
    out = substitute(expr, {"a": ClassValue(NONE)}.get, frozenset({"self"}))
    lam = next(node for node in ast.walk(out) if isinstance(node, ast.Lambda))
    assert isinstance(lam.args.defaults[0], ClassValue)  # a default is read outside the lambda
    assert not any(isinstance(node, ClassValue) for node in ast.walk(lam.body))


def test_substitute_replaces_only_receiver_attribute_loads():
    expr = ast.parse("self.a is None and other.a and self.b.c and self.unknown", mode="eval").body
    env = {"a": ClassValue(NONE), "b": ClassValue(OBJECT)}.get
    out = ast.dump(substitute(expr, env, frozenset({"self"})))
    assert out.count("ClassValue") == 2
    assert "attr='unknown'" in out and "id='other'" in out
    assert ast.dump(expr).count("ClassValue") == 0  # the input is untouched
    assert substitute(expr, None, frozenset({"self"})) is expr


# --- folding --------------------------------------------------------------------------------


@pytest.mark.parametrize("value, test, expected", [
    (NONE, "X is None", True),
    (NONE, "X is not None", False),
    (NONE, "None is X", True),
    (NONE, "X == None", True),
    (NONE, "X != None", False),
    (NONE, "X", False),
    (NONE, "not X", True),
    (OBJECT, "X is None", False),
    (OBJECT, "X is not None", True),
    (OBJECT, "X != None", True),
    (OBJECT, "X", True),
    (OBJECT, "not X", False),
    (OBJECT, "X and False", False),
    (OBJECT, "X == 1", None),
    (OBJECT, "X is 1", None),
    (OBJECT, "X < 3", None),
    (NONE, "X.attr", None),
    (NOT_NONE, "X is None", False),
    (NOT_NONE, "X is not None", True),
    (NOT_NONE, "None is not X", True),
    (NOT_NONE, "X == None", None),
    (NOT_NONE, "X != None", None),
    (NOT_NONE, "X", None),
    (NOT_NONE, "not X", None),
    (OBJECT, "X is None is None", None),
])
def test_static_truth_of_a_class_value(value, test, expected):
    expr = ast.parse(test.replace("X", "self.x"), mode="eval").body
    assert _static_truth(substitute(expr, {"x": ClassValue(value)}.get, frozenset({"self"}))) is expected


def test_is_between_other_literals_stays_unknown():
    # Interning decides `1 is 1`; only `None`'s identity is settled.
    assert _static_truth(ast.parse("None is None", mode="eval").body) is None

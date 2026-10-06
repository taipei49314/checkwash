"""#220's body skips meet #254's class attributes.

#220 reads a test body's skip through the module's imports, called or raised:
`raise unittest.SkipTest(...)` and `skip()` imported from pytest are skips.
#254 evaluates a skip guard with the class attributes the unit's class body
sets, and credits an abstract base (254.Q2) when a same-file subclass runs
the test. The two met in one merge. These pin that every skip #220 reads is
judged by #254's attributes, in the unit's own reading and in the credit.
"""
import datetime

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.frontends.python.frontend import parse_python

TEST = "tests/test_x.py"
TODAY = datetime.date(2026, 10, 6)
APP = {"app/__init__.py": b"", "app/billing.py": b"def total(items):\n    return sum(items)\n"}
HEAD = "import unittest\nfrom unittest import SkipTest as Skip\n\nfrom app.billing import total\n\n\n"
PLAIN = "    def test_total(self):\n        self.assertEqual(total([30, 48.75]), 78.75)\n"
BEFORE = HEAD + "class TotalTest(unittest.TestCase):\n" + PLAIN


def module(class_body, extra=""):
    return HEAD + "class TotalTest(unittest.TestCase):\n" + class_body + extra


def guarded(skip, attribute="item_class"):
    return (
        "    def test_total(self):\n"
        f"        if self.{attribute} is None:\n"
        f"            {skip}\n"
        "        self.assertEqual(total([30, 48.75]), 78.75)\n"
    )


def markers(source):
    parsed = parse_python(source.encode(), collect_tests=True)
    return {unit.qualname: [(m.name, m.guard) for m in unit.side.markers] for unit in parsed.units}


def run(after):
    snapshot = {**APP, TEST: after.encode()}
    changes = [FileChange(TEST, "modified", BEFORE.encode(), after.encode())]
    _ir, findings, verdict = analyze(changes, Config(), Contract(), [], TODAY, head_reader=snapshot.get)
    return [(f.unit, f.severity) for f in findings if f.rule == "TEST_DISABLED"], verdict


SKIPS = [
    pytest.param('raise unittest.SkipTest("no item class")', "unittest.SkipTest", id="raised"),
    pytest.param('raise Skip("no item class")', "unittest.SkipTest", id="raised-alias"),
    pytest.param('self.skipTest("no item class")', "self.skipTest", id="called"),
]


@pytest.mark.parametrize("skip, name", SKIPS)
def test_a_guard_that_never_holds_under_the_class_mints_no_marker(skip, name):
    after = module("    item_class = list\n\n" + guarded(skip))
    assert markers(after) == {"TotalTest.test_total": []}
    assert run(after) == ([], "pass")


@pytest.mark.parametrize("skip, name", SKIPS)
def test_a_guard_that_holds_under_the_class_reads_as_unconditional(skip, name):
    after = module("    item_class = None\n\n" + guarded(skip))
    assert markers(after) == {"TotalTest.test_total": [(name, None)]}
    assert run(after) == ([("TotalTest.test_total", "high")], "block")


@pytest.mark.parametrize("skip, name", SKIPS)
def test_an_abstract_base_a_subclass_runs_is_credited(skip, name):
    after = module(
        "    total_fn = None\n\n" + guarded(skip, "total_fn"),
        extra="\n\nclass BillingTotalTest(TotalTest):\n    total_fn = staticmethod(total)\n",
    )
    assert markers(after) == {"TotalTest.test_total": []}
    assert run(after) == ([], "pass")


@pytest.mark.parametrize("skip, name", SKIPS)
def test_a_skip_the_subclass_reaches_credits_nothing(skip, name):
    """The base skips on `a`. The subclass sets `a`, but rebinds `b` to None, so
    its `b` skip runs: it skips the test too. An attribute a subclass rebinds
    is not the base's to settle, so the `b` skip keeps its guard (#254)."""
    after = module(
        "    a = None\n    b = 1\n\n"
        "    def test_total(self):\n"
        "        if self.a is None:\n"
        f"            {skip}\n"
        "        if self.b is None:\n"
        f"            {skip}\n"
        "        self.assertEqual(total([30, 48.75]), 78.75)\n",
        extra="\n\nclass BillingTotalTest(TotalTest):\n    a = 1\n    b = None\n",
    )
    assert markers(after) == {"TotalTest.test_total": [(name, None), (name, "self.b is None")]}
    assert run(after) == ([("TotalTest.test_total", "high"), ("TotalTest.test_total", "high")], "block")

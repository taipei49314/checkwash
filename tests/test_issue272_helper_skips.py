"""A skip the test or its setup reaches through a same-file helper is read (#272).

A skip only read where the test body or its setup spells it passed with zero
findings one call away: `_later()`, where `_later` calls `pytest.skip()`,
skipped the test as surely as the call itself, and a fixture that called it
skipped every test that requests it.

Ruling 272.Q1 (a): for the same-file scopes `_executed_scopes` resolves for
assertions, the helper is read as a setup callback is: an outcome every call
reaches is unconditional, and one reached under a condition keeps it, with
the call site's conditions and every helper's on the way conjoined. 272.Q3:
the marker is `helper.<function>.<effect>`, and its message says the skip
was added to a helper this test calls. A method reached through `self` is not
such a scope (#306); a helper imported from another module is the ruling's
second stage (272.Q2).
"""
import datetime

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.frontends.python.frontend import parse_python
from checkwash.ir.diffalign import _moved_skip, _skip_effect
from checkwash.ir.markers import GUARDED_SKIP_CALLS
from checkwash.ir.model import Marker

HEAD = "import os\nimport sys\n\nimport pytest\n\nfrom app import total\n\nNET = os.environ.get('NET')\n\n\n"
TEST = "def test_total():\n    {call}\n    assert total([30, 48.75]) == 78.75\n"
BASE = HEAD + "def test_total():\n    assert total([30, 48.75]) == 78.75\n"


def outcome(before, after, path="tests/test_x.py"):
    _ir, findings, verdict = analyze(
        [FileChange(path, "modified", before.encode(), after.encode())],
        Config(), Contract(), [], datetime.date(2026, 10, 6),
    )
    return verdict, [(f.rule, f.severity, f.message.split(": ", 1)[1]) for f in findings]


def markers(source, qualname="test_total"):
    [unit] = [u for u in parse_python(source.encode(), collect_tests=True).units if u.qualname == qualname]
    return [(m.name, m.text, m.guard) for m in unit.side.markers]


def disabled(name, severity="high"):
    return ("TEST_DISABLED", severity, f"skip/xfail added to a helper this test calls ({name})")


# --- the issue's rows ------------------------------------------------------------------

@pytest.mark.parametrize("helpers, call, name", [
    # H1: a module function
    ("def _later():\n    pytest.skip('later')\n\n\n", "_later()", "helper._later.skip"),
    # H3: a nested def the test calls
    ("", "def later():\n        pytest.skip('flaky')\n\n    later()", "helper.later.skip"),
    # H4: the raised spelling
    ("def _flaky():\n    raise pytest.skip.Exception('flaky')\n\n\n", "_flaky()", "helper._flaky.skip"),
    # xfail is the other effect
    ("def _broken():\n    pytest.xfail('broken')\n\n\n", "_broken()", "helper._broken.xfail"),
    # unittest's exception, raised in a helper of a pytest test
    ("import unittest\n\n\ndef _later():\n    raise unittest.SkipTest('later')\n\n\n", "_later()",
     "helper._later.skip"),
], ids=["module_function", "nested_def", "raise", "xfail", "unittest_raise"])
def test_a_skip_one_call_away_is_reported_as_the_skip_is(helpers, call, name):
    after = HEAD + helpers + TEST.format(call=call)
    assert outcome(BASE, after) == ("block", [disabled(name)])


def test_the_same_skip_written_in_the_body_is_the_contrast():
    after = HEAD + TEST.format(call="pytest.skip('flaky')")
    assert outcome(BASE, after) == ("block", [("TEST_DISABLED", "high", "disabling marker added (pytest.skip)")])


def test_a_fixture_that_calls_a_skipping_helper_skips_its_test():
    """S2: the helper is reached through the setup the test runs."""
    fixture = "@pytest.fixture\ndef items():\n    {call}\n    return [30, 48.75]\n\n\n"
    test = "def test_total(items):\n    assert total(items) == 78.75\n"
    before = HEAD + fixture.format(call="pass") + test
    after = HEAD + "def _offline():\n    pytest.skip('flaky')\n\n\n" + fixture.format(call="_offline()") + test
    assert outcome(before, after) == ("block", [disabled("helper._offline.skip")])


@pytest.mark.parametrize("callback, test", [
    ("def setup_function():\n    _offline()\n\n\n", "def test_total():\n    assert total([30, 48.75]) == 78.75\n"),
    ("@pytest.fixture(autouse=True)\ndef offline():\n    _offline()\n\n\n",
     "def test_total():\n    assert total([30, 48.75]) == 78.75\n"),
    ("", "class TestTotal:\n    def setup_method(self):\n        _offline()\n\n"
         "    def test_total(self):\n        assert total([30, 48.75]) == 78.75\n"),
], ids=["setup_function", "autouse_fixture", "setup_method"])
def test_xunit_setup_and_autouse_fixtures_reach_the_helper_too(callback, test):
    qualname = "TestTotal.test_total" if "class" in test else "test_total"
    after = HEAD + "def _offline():\n    pytest.skip('flaky')\n\n\n" + callback + test
    assert [m[0] for m in markers(after, qualname)] == ["helper._offline.skip"]


# --- guards ------------------------------------------------------------------------------

def test_a_guarded_skip_in_the_helper_keeps_its_guard():
    after = HEAD + "def _maybe():\n    if not NET:\n        pytest.skip('no net')\n\n\n" + TEST.format(call="_maybe()")
    assert markers(after) == [("helper._maybe.skip", "pytest.skip('no net')", "not NET")]


def test_the_call_sites_conditions_and_the_helpers_are_conjoined():
    helpers = (
        "def _outer():\n    if NET == 'slow':\n        _maybe()\n\n\n"
        "def _maybe():\n    if not NET:\n        pytest.skip('no net')\n\n\n"
    )
    after = HEAD + helpers + TEST.format(call="if sys.platform == 'win32':\n        _outer()")
    assert markers(after) == [
        ("helper._maybe.skip", "pytest.skip('no net')", "sys.platform == 'win32' and NET == 'slow' and not NET"),
    ]


def test_an_else_branch_at_the_call_site_is_the_negated_condition():
    after = HEAD + "def _later():\n    pytest.skip('x')\n\n\n" + TEST.format(
        call="if NET:\n        pass\n    else:\n        _later()")
    assert markers(after) == [("helper._later.skip", "pytest.skip('x')", "not (NET)")]


def test_an_except_block_at_the_call_site_is_its_condition():
    after = HEAD + "def _later():\n    pytest.skip('x')\n\n\n" + TEST.format(
        call="try:\n        import numpy\n    except ImportError:\n        _later()")
    assert markers(after) == [("helper._later.skip", "pytest.skip('x')", 'find_spec("numpy") is None')]


def test_an_except_block_is_the_condition_it_expresses():
    helper = "def _np():\n    try:\n        import numpy\n    except ImportError:\n        pytest.skip('numpy')\n\n\n"
    after = HEAD + helper + TEST.format(call="_np()")
    assert markers(after) == [("helper._np.skip", "pytest.skip('numpy')", 'find_spec("numpy") is None')]


def test_a_platform_gate_is_judged_as_the_same_gate_in_the_body():
    """COMPAT_GATE reads the helper's guard as it reads a body skip's."""
    body = HEAD + TEST.format(call="if sys.platform == 'win32':\n        pytest.skip('windows')")
    helper = (HEAD + "def _windows():\n    pytest.skip('windows')\n\n\n"
              + TEST.format(call="if sys.platform == 'win32':\n        _windows()"))
    assert outcome(BASE, body) == ("pass", [("TEST_DISABLED", "warn", "disabling marker added (pytest.skip)")])
    assert outcome(BASE, helper) == ("pass", [disabled("helper._windows.skip", "warn")])


def test_a_helpers_guard_removed_is_reported_as_a_body_skips_is():
    before = HEAD + "def _maybe():\n    if not NET:\n        pytest.skip('no net')\n\n\n" + TEST.format(call="_maybe()")
    after = HEAD + "def _maybe():\n    pytest.skip('no net')\n\n\n" + TEST.format(call="_maybe()")
    verdict, findings = outcome(before, after)
    assert verdict == "block"
    assert findings == [("TEST_DISABLED", "high",
                         "skip guard removed in a helper this test calls (was 'not NET') (helper._maybe.skip)")]


# --- a skip moved into a helper or out of one -------------------------------------------------
#
# A helper's marker is named for the helper, so moving a skip the test already
# had into a helper it calls changed the name and nothing else, and read as a
# skip added (scrapy df342eee6e2f, found by this round's sweep).

GUARDED = "if not NET:\n        pytest.skip('no net')"
MAYBE = "def _maybe():\n    if not NET:\n        pytest.skip('no net')\n\n\n"
LATER = "def _later():\n    pytest.skip('later')\n\n\n"


def delta(before, after, qualname="test_total"):
    ir, _findings, _verdict = analyze(
        [FileChange("tests/test_x.py", "modified", before.encode(), after.encode())],
        Config(), Contract(), [], datetime.date(2026, 10, 6),
    )
    [unit] = [u for f in ir.files for u in f.units if u.qualname == qualname]
    return unit.delta


@pytest.mark.parametrize("before, after", [
    # the guard moved with the skip
    (HEAD + TEST.format(call=GUARDED), HEAD + MAYBE + TEST.format(call="_maybe()")),
    # the guard stayed at the call site
    (HEAD + TEST.format(call=GUARDED), HEAD + LATER + TEST.format(call="if not NET:\n        _later()")),
    (HEAD + TEST.format(call="pytest.skip('later')"), HEAD + LATER + TEST.format(call="_later()")),
    # it fires less often than it did
    (HEAD + TEST.format(call="pytest.skip('later')"), HEAD + MAYBE + TEST.format(call="_maybe()")),
    # out of a helper, back into the body
    (HEAD + MAYBE + TEST.format(call="_maybe()"), HEAD + TEST.format(call=GUARDED)),
    # a helper renamed
    (HEAD + MAYBE + TEST.format(call="_maybe()"),
     HEAD + MAYBE.replace("_maybe", "_offline") + TEST.format(call="_offline()")),
    # the raised spelling, moved
    (HEAD + TEST.format(call="raise pytest.skip.Exception('later')"), HEAD + LATER + TEST.format(call="_later()")),
], ids=["guard_moved", "guard_at_call_site", "unconditional", "now_guarded", "out_of_helper", "renamed", "raised"])
def test_a_skip_moved_into_a_helper_is_the_skip_it_was(before, after):
    assert outcome(before, after) == ("pass", [])


def test_a_fixtures_skip_moved_into_a_helper_it_calls_is_the_skip_it_was():
    fixture = "@pytest.fixture\ndef items():\n    {call}\n    return [30, 48.75]\n\n\n"
    test = "def test_total(items):\n    assert total(items) == 78.75\n"
    before = HEAD + fixture.format(call=GUARDED) + test
    after = HEAD + MAYBE + fixture.format(call="_maybe()") + test
    assert outcome(before, after) == ("pass", [])
    assert delta(before, after).markers_moved == [("setup.items.skip", "helper._maybe.skip")]


def test_the_move_is_recorded_and_no_marker_is_added():
    unit_delta = delta(HEAD + TEST.format(call=GUARDED), HEAD + MAYBE + TEST.format(call="_maybe()"))
    assert unit_delta.markers_moved == [("pytest.skip", "helper._maybe.skip")]
    assert unit_delta.markers_added == []


@pytest.mark.parametrize("before, after, name", [
    # it fires more often: the guard did not move with it
    (HEAD + TEST.format(call=GUARDED), HEAD + LATER + TEST.format(call="_later()"), "helper._later.skip"),
    # a different condition
    (HEAD + TEST.format(call=GUARDED), HEAD + MAYBE.replace("not NET", "NET != 'on'") + TEST.format(call="_maybe()"),
     "helper._maybe.skip"),
    # a skip is not an xfail
    (HEAD + TEST.format(call=GUARDED), HEAD + MAYBE.replace("skip", "xfail") + TEST.format(call="_maybe()"),
     "helper._maybe.xfail"),
    # one skip moved, one added
    (HEAD + TEST.format(call="pytest.skip('later')"),
     HEAD + LATER + MAYBE.replace("not NET", "NET") + TEST.format(call="_later()\n    _maybe()"), "helper._maybe.skip"),
], ids=["guard_dropped", "other_guard", "xfail", "one_of_two"])
def test_a_skip_the_move_made_fire_more_often_is_reported(before, after, name):
    assert outcome(before, after) == ("block", [disabled(name)])


def test_a_moved_skips_guard_still_reads_the_constant_behind_it():
    """THREATMODEL 59 across the move: the guard's text is the same, its constant now always true."""
    before = HEAD + TEST.format(call=GUARDED)
    after = HEAD.replace("os.environ.get('NET')", "None") + MAYBE + TEST.format(call="_maybe()")
    assert outcome(before, after) == ("block", [(
        "TEST_DISABLED", "high",
        "skip guard in a helper this test calls now always fires ('not NET') (helper._maybe.skip)")])


def test_a_skip_respelled_in_the_body_is_not_a_move():
    """The body to the body is #281's question, not this one."""
    old = Marker(name="pytest.skip", text="pytest.skip()", span=(0, 1), guard=None)
    new = Marker(name="self.skipTest", text="self.skipTest()", span=(0, 1), guard=None)
    assert not _moved_skip(old, new)


def test_every_body_skip_call_has_its_effect():
    assert {name: _skip_effect(name) for name in GUARDED_SKIP_CALLS} == {
        "pytest.skip": "skip", "pytest.skip.Exception": "skip", "self.skipTest": "skip",
        "unittest.SkipTest": "skip", "pytest.xfail": "xfail", "pytest.xfail.Exception": "xfail",
    }
    assert [_skip_effect(name) for name in ("setup.items.xfail", "helper._maybe.skip", "pytest.mark.skip")] == [
        "xfail", "skip", None]


def test_a_unittest_skip_moved_into_a_module_helper_is_the_skip_it_was():
    def case(call, helpers=""):
        return ("import unittest\n\nfrom app import total\n\n\n" + helpers
                + "class TotalTest(unittest.TestCase):\n    def test_total(self):\n"
                f"        {call}\n        self.assertEqual(total([30, 48.75]), 78.75)\n")

    helper = "def _later():\n    raise unittest.SkipTest('later')\n\n\n"
    assert outcome(case("self.skipTest('later')"), case("_later()", helper)) == ("pass", [])


# --- what is not a skip this test reaches ---------------------------------------------------

@pytest.mark.parametrize("after", [
    # a helper the test already called, unchanged
    HEAD + "def _later():\n    pytest.skip('later')\n\n\n" + TEST.format(call="_later()"),
], ids=["unchanged"])
def test_a_skip_the_base_already_reached_is_no_event(after):
    assert outcome(after, after) == ("pass", [])


def test_a_parameter_of_the_test_shadows_the_module_function():
    """`def test_total(_later): _later()` calls the fixture's value, not the module function."""
    after = HEAD + "def _later():\n    pytest.skip('x')\n\n\n" + TEST.format(call="_later()").replace(
        "def test_total():", "def test_total(_later):")
    assert markers(after) == []


@pytest.mark.parametrize("helpers, call", [
    # a generator's body does not run when it is called
    ("def _later():\n    pytest.skip('x')\n    yield\n\n\n", "_later()"),
    # nothing calls the lambda the helper builds
    ("def _later():\n    later = lambda: pytest.skip('x')\n\n\n", "_later()"),
    # nothing calls the lambda the test builds
    ("def _later():\n    pytest.skip('x')\n\n\n", "run = lambda: _later()"),
    # a helper that does not skip
    ("def _setup():\n    os.environ['TZ'] = 'UTC'\n\n\n", "_setup()"),
    # a class is not followed: its methods run only when called
    ("class Offline:\n    def check(self):\n        pytest.skip('x')\n\n\n", "Offline()"),
    # helpers that call each other, and never skip
    ("def a():\n    b()\n\n\ndef b():\n    a()\n\n\n", "a()"),
], ids=["generator", "uncalled_lambda_in_helper", "uncalled_lambda_in_test", "no_skip", "class", "cycle"])
def test_no_marker(helpers, call):
    assert markers(HEAD + helpers + TEST.format(call=call)) == []


def test_a_call_that_never_runs_reaches_nothing():
    after = HEAD + "def _later():\n    pytest.skip('x')\n\n\n" + "def test_total():\n    return\n    _later()\n"
    assert markers(after) == []


def test_a_lambda_bound_to_a_name_is_a_helper():
    after = HEAD + "skip_it = lambda: pytest.skip('x')\n\n\n" + TEST.format(call="skip_it()")
    assert markers(after) == [("helper.skip_it.skip", "pytest.skip('x')", None)]


def test_helpers_are_followed_four_calls_deep_as_assertions_are():
    chain = "def a():\n    b()\n\n\ndef b():\n    c()\n\n\ndef c():\n    d()\n\n\n"
    four = HEAD + chain + "def d():\n    pytest.skip('x')\n\n\n" + TEST.format(call="a()")
    five = HEAD + chain + "def d():\n    e()\n\n\ndef e():\n    pytest.skip('x')\n\n\n" + TEST.format(call="a()")
    assert [m[0] for m in markers(four)] == ["helper.d.skip"]
    assert markers(five) == []


def test_a_helper_that_always_skips_ends_the_walk():
    """Nothing it would call after its outcome runs."""
    helpers = "def a():\n    pytest.skip('x')\n    b()\n\n\ndef b():\n    pytest.xfail('y')\n\n\n"
    assert [m[0] for m in markers(HEAD + helpers + TEST.format(call="a()"))] == ["helper.a.skip"]


def test_a_conftest_fixtures_helper_is_not_followed():
    """A conftest's fixtures are read by their own outcome (#223); their helpers are not."""
    conftest = "import pytest\n\n\ndef _offline():\n    pytest.skip('x')\n\n\n@pytest.fixture\ndef offline():\n    _offline()\n"
    units = parse_python(conftest.encode(), collect_tests=True, conftest=True).units
    assert all(not m.name.startswith("helper.") for unit in units for m in unit.side.markers)


# --- residuals of this stage ----------------------------------------------------------------

def test_a_method_reached_through_self_is_not_followed():
    """H2: `self._later()` names no scope `_executed_scopes` resolves (#306)."""
    after = (
        "import unittest\n\n\nclass TotalTest(unittest.TestCase):\n"
        "    def _later(self):\n        self.skipTest('later')\n\n"
        "    def test_total(self):\n        self._later()\n        self.assertEqual(1, 1)\n"
    )
    assert markers(after, "TotalTest.test_total") == []


def test_a_method_the_setup_reaches_through_self_is_not_followed():
    """S1: `setUp` calling `self._offline()` is the same residual (#306)."""
    after = (
        "import unittest\n\n\nclass TotalTest(unittest.TestCase):\n"
        "    def _offline(self):\n        self.skipTest('flaky')\n\n"
        "    def setUp(self):\n        self._offline()\n        self.items = [1]\n\n"
        "    def test_total(self):\n        self.assertEqual(self.items, [1])\n"
    )
    assert markers(after, "TotalTest.test_total") == []


def test_a_nested_helper_sees_the_names_its_test_imports():
    """`import pytest as pt` inside the test is what the nested def's `pt.skip` names."""
    after = HEAD + TEST.format(call="import pytest as pt\n\n    def later():\n        pt.skip('x')\n\n    later()")
    assert [m[0] for m in markers(after)] == ["helper.later.skip"]


def test_a_name_the_test_rebinds_is_not_the_module_function():
    after = HEAD + "def _later():\n    pytest.skip('x')\n\n\n" + TEST.format(call="_later = print\n    _later()")
    assert markers(after) == []


def test_a_lambdas_parameter_shadows_the_module_name():
    after = HEAD + "skip_it = lambda pytest=None: pytest.skip('x')\n\n\n" + TEST.format(call="skip_it()")
    assert markers(after) == []

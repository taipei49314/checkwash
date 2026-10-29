"""Python failure relays (D-190): a handler that relays the failure is not a swallow.

uvloop's regression tests catch a callback's or a thread's assertion failure
in a broad handler and pass it, unchanged, to an asyncio future the test
awaits (D-187 accepted three such false blocks for 0.10 only). The frontend
keeps 0.10's `swallowing_handlers` and lists the proven relays among them in
`relay_handlers`, by the bounded rules of SPEC §4 "Python failure relays"
(R1 to R7, with R2b). The engine reads the after side's relays only: per
handler text, a change adds the smaller of 0.10's count and the after
side's swallowing handlers that are not proven relays.

The accepted and refused variants below are the design prototype's 38, run
here through the real parse; try/except*, R2, each R2b clause, a production
parse, the 0.10 bound and a timing bound are new, and so is everything from
"the fix round" on, which pins what the 2026-10-29 adversarial reviews
found. Expectations are Claude's, set under the 2026-10-27 delegation
(D-190).
"""

from __future__ import annotations

import datetime
import time

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.frontends.python import failure_relays
from checkwash.frontends.python.frontend import parse_python

TODAY = datetime.date(2026, 10, 29)
PATH = "tests/test_loop.py"
HANDLER = ("exceptExceptionase:",)

BASE = '''import asyncio

from app import compute
from tests.support import LoopTestCase


class TestLoop(LoopTestCase):
    def test_x(self):
        fut = self.loop.create_future()

        def cb():
            try:
                self.assertEqual(compute(), 3)
            except Exception as e:
                fut.set_exception(e)
            else:
                fut.set_result(None)

        self.loop.call_soon(cb)
        self.loop.run_until_complete(fut)
'''

CALLBACK = '''        def cb():
            try:
                self.assertEqual(compute(), 3)
            except Exception as e:
                fut.set_exception(e)
            else:
                fut.set_result(None)
'''


def v(old: str, new: str, source: str = BASE) -> str:
    assert source.count(old) == 1, old
    return source.replace(old, new)


def parsed(source: str, **options):
    return parse_python(source.encode(), **{"collect_tests": True, **options})


def credited(source: str) -> bool:
    """One swallowing handler, and it is a proven relay; False when it is not."""
    result = parsed(source)
    assert len(result.swallowing_handlers) == 1, result.swallowing_handlers
    assert set(result.relay_handlers) <= set(result.swallowing_handlers)
    return result.relay_handlers == result.swallowing_handlers


MODULE_LEVEL = '''import asyncio

from app import compute


async def test_x():
    fut = asyncio.Future()

    def cb():
        try:
            assert compute() == 3
        except Exception as e:
            fut.set_exception(e)
        else:
            fut.set_result(None)

    asyncio.get_running_loop().call_soon(cb)
    await fut
'''

ACCEPTED = {
    "run_until_complete(fut) after handing off": BASE,
    "call_soon relay": v("fut.set_exception(e)", "self.loop.call_soon(fut.set_exception, e)"),
    "except AssertionError as e": v("except Exception as e", "except AssertionError as e"),
    "fut.result() after a run": v("        self.loop.run_until_complete(fut)",
                                  "        self.loop.run_until_complete(asyncio.sleep(0))\n        fut.result()"),
    "asyncio.Future(loop=self.loop)": v("fut = self.loop.create_future()", "fut = asyncio.Future(loop=self.loop)"),
    "wait_for(gather(fut)) through a run": v(
        "self.loop.run_until_complete(fut)", "self.loop.run_until_complete(asyncio.wait_for(asyncio.gather(fut), 5))"),
    "module-level async test, asyncio.Future(), awaited": MODULE_LEVEL,
}

REFUSED = {
    "bare except": v("except Exception as e:\n                fut.set_exception(e)",
                     "except Exception:\n                fut.set_exception(RuntimeError())"),
    "relay keyword": v("fut.set_exception(e)", "fut.set_exception(exception=e)"),
    "set_result in the try body": v("                self.assertEqual(compute(), 3)",
                                    "                fut.set_result(None)\n                self.assertEqual(compute(), 3)"),
    "set_result in finally": v("            else:\n                fut.set_result(None)",
                               "            finally:\n                fut.set_result(None)"),
    "a second set_exception": v("        self.loop.call_soon(cb)",
                                "        fut.set_exception(RuntimeError())\n        self.loop.call_soon(cb)"),
    "add_done_callback": v("        self.loop.call_soon(cb)", "        fut.add_done_callback(print)\n        self.loop.call_soon(cb)"),
    "an alias of the future": v("        self.loop.call_soon(cb)", "        g = fut\n        self.loop.call_soon(cb)"),
    "the future passed to a helper": v("        self.loop.call_soon(cb)", "        compute(fut)\n        self.loop.call_soon(cb)"),
    "the future bound twice": v("        self.loop.call_soon(cb)",
                                "        fut = self.loop.create_future()\n        self.loop.call_soon(cb)"),
    "a nonlocal rebinding": v("        self.loop.call_soon(cb)",
                              "        def swap():\n            nonlocal fut\n            fut = None\n        self.loop.call_soon(cb)"),
    "a nested scope binds the name": v("        self.loop.call_soon(cb)",
                                       "        def other(fut):\n            return fut\n        self.loop.call_soon(cb)"),
    "locals()": v("        self.loop.call_soon(cb)", "        locals()\n        self.loop.call_soon(cb)"),
    "the consumer under an if": v("        self.loop.run_until_complete(fut)",
                                  "        if compute():\n            self.loop.run_until_complete(fut)"),
    "the consumer after return": v("        self.loop.run_until_complete(fut)",
                                   "        return\n        self.loop.run_until_complete(fut)"),
    "the consumer in a try whose finally returns": v(
        "        self.loop.run_until_complete(fut)",
        "        try:\n            self.loop.run_until_complete(fut)\n        finally:\n            return"),
    "the consumer under except AssertionError: pass": v(
        "        self.loop.run_until_complete(fut)",
        "        try:\n            self.loop.run_until_complete(fut)\n        except AssertionError:\n            pass"),
    "asyncio.wait is no consumer": v("self.loop.run_until_complete(fut)",
                                     "self.loop.run_until_complete(asyncio.wait([fut]))"),
    "fut.exception() is no consumer": v("        self.loop.run_until_complete(fut)",
                                        "        self.loop.run_until_complete(asyncio.sleep(0))\n        fut.exception()"),
    "an untrusted run receiver": v("self.loop.run_until_complete(fut)", "self.other.run_until_complete(fut)", v(
        "        fut = self.loop.create_future()", "        fut = self.loop.create_future()\n        self.other = compute()")),
    "an untrusted scheduler": v("fut.set_exception(e)", "spy.call_soon_threadsafe(fut.set_exception, e)", v(
        "        fut = self.loop.create_future()", "        spy = compute()\n        fut = self.loop.create_future()")),
    "setUp stores self.loop": v("    def test_x(self):", "    def setUp(self):\n        self.loop = compute()\n\n    def test_x(self):"),
    "an alias of self stores the loop": v("        fut = self.loop.create_future()",
                                          "        me = self\n        me.loop = compute()\n        fut = self.loop.create_future()"),
    "a class attribute loop": v("class TestLoop(LoopTestCase):\n", "class TestLoop(LoopTestCase):\n    loop = None\n\n"),
    "a loop property": v("class TestLoop(LoopTestCase):\n",
                         "class TestLoop(LoopTestCase):\n    @property\n    def loop(self):\n        return compute()\n\n"),
    "a patch string": v("    def test_x(self):", "    @unittest.mock.patch('asyncio.Future')\n    def test_x(self):", v(
        "fut = self.loop.create_future()", "fut = asyncio.Future()")),
    "setattr with the loop's name": v("        fut = self.loop.create_future()",
                                      "        setattr(self, 'loop', compute())\n        fut = self.loop.create_future()"),
    "create_future replaced": v("        fut = self.loop.create_future()",
                                "        self.loop.create_future = compute\n        fut = self.loop.create_future()"),
    "a staticmethod": v("    def test_x(self):", "    @staticmethod\n    def test_x(self):"),
    "a module-level test with a new_event_loop()": '''import asyncio

from app import compute


def test_x():
    loop = asyncio.new_event_loop()
    fut = loop.create_future()

    def cb():
        try:
            assert compute() == 3
        except Exception as e:
            fut.set_exception(e)
        else:
            fut.set_result(None)

    loop.call_soon(cb)
    loop.run_until_complete(fut)
''',
    "the try inside a while": v(CALLBACK, '''        def cb():
            while compute():
                try:
                    self.assertEqual(compute(), 3)
                except Exception as e:
                    fut.set_exception(e)
                else:
                    fut.set_result(None)
'''),
    "asyncio shadowed by a parameter": '''import asyncio

from app import compute


async def test_x(asyncio):
    fut = asyncio.Future()

    def cb():
        try:
            assert compute() == 3
        except Exception as e:
            fut.set_exception(e)

    await fut
''',
}


@pytest.mark.parametrize("source", ACCEPTED.values(), ids=ACCEPTED.keys())
def test_a_proven_relay_is_listed_as_a_relay(source):
    assert credited(source)


@pytest.mark.parametrize("source", REFUSED.values(), ids=REFUSED.keys())
def test_a_relay_outside_the_rules_is_a_swallow(source):
    assert not credited(source)


def test_the_variants_are_the_prototypes_38():
    assert (len(ACCEPTED), len(REFUSED)) == (7, 31)


def test_a_relay_stays_in_both_lists():
    # 0.10's lists are unchanged: the relay is credited only in the count of what a change adds.
    result = parsed(BASE)
    assert result.broad_handlers == result.swallowing_handlers == result.relay_handlers == HANDLER


def test_try_star_is_not_read():
    source = v("            except Exception as e:", "            except* Exception as e:")
    result = parsed(source)
    assert result.swallowing_handlers == ("except*Exceptionase:",)
    assert result.relay_handlers == ()


# --- R2 and R2b: where a relay is read ---------------------------------------------------------------

def test_r2_a_callback_the_test_calls_itself_is_not_a_relay():
    # The test runs `cb()`, so cb's assertion is one the unit executes.
    source = v("        self.loop.call_soon(cb)", "        cb()")
    unit = parsed(source).units[0]
    assert [a.text for a in unit.side.assertions] == ["self.assertEqual(compute(), 3)"]
    assert not credited(source)


def test_r2_a_callback_handed_off_through_a_lambda_is_a_relay():
    assert credited(v("        self.loop.call_soon(cb)", "        self.loop.call_soon(lambda: cb())"))


def test_r2b_a_conftest_and_an_uncollected_parse_read_no_relay():
    assert parsed(BASE, conftest=True).relay_handlers == ()
    production = parsed(BASE, collect_tests=False)
    assert production.broad_handlers == HANDLER
    assert production.relay_handlers == ()


def test_r2b_a_relay_inside_a_fixture_is_not_read():
    source = MODULE_LEVEL.replace("async def test_x():", "@pytest.fixture\nasync def checked():").replace(
        "import asyncio\n", "import asyncio\n\nimport pytest\n")
    assert not credited(source)
    assert credited(source.replace("@pytest.fixture\n", ""))


def test_r2b_a_relay_inside_a_pytest_asyncio_fixture_is_not_read():
    # The frontend's fixture reading knows only `pytest.fixture` and
    # `fixture`; R2b (b) also refuses any decorator named `...fixture`.
    source = MODULE_LEVEL.replace("async def test_x():", "@pytest_asyncio.fixture\nasync def checked():").replace(
        "import asyncio\n", "import asyncio\n\nimport pytest_asyncio\n")
    assert not credited(source)
    assert credited(source.replace("@pytest_asyncio.fixture\n", ""))


def test_r2b_a_try_in_a_method_body_is_not_read():
    # Everything else holds: `_check` is not a test and nothing calls it.
    method = '''    def _check(self):
        fut = self.loop.create_future()
        try:
            self.assertEqual(compute(), 3)
        except Exception as e:
            fut.set_exception(e)
        else:
            fut.set_result(None)
        self.loop.run_until_complete(fut)
'''
    source = BASE.split("    def test_x(self):")[0] + method
    assert not credited(source)
    nested = '''    def _check(self):
        fut = self.loop.create_future()

        def cb():
            try:
                self.assertEqual(compute(), 3)
            except Exception as e:
                fut.set_exception(e)
            else:
                fut.set_result(None)

        self.loop.call_soon(cb)
        self.loop.run_until_complete(fut)
'''
    assert credited(BASE.split("    def test_x(self):")[0] + nested)


def test_r2b_a_try_in_a_module_level_test_is_not_read():
    source = '''import asyncio

from app import compute


async def test_x():
    fut = asyncio.Future()
    try:
        assert compute() == 3
    except Exception as e:
        fut.set_exception(e)
    else:
        fut.set_result(None)
    await fut
'''
    assert not credited(source)


def test_r2b_a_relay_with_no_unit_is_read():
    # uvloop 7b202ccf: the tests live in a mixin whose collecting class has an
    # imported base, so the parse has no unit; the relay is still read.
    source = BASE.replace("from tests.support import LoopTestCase", "from tests import support as tb").replace(
        "class TestLoop(LoopTestCase):", "class _LoopTests:") + "\n\nclass Test_UV_Loop(_LoopTests, tb.UVTestCase):\n    pass\n"
    assert parsed(source).units == []
    assert credited(source)


# --- the 0.10 bound in the engine --------------------------------------------------------------------

HEAD = BASE.split("    def test_x(self):")[0] + '''    def test_y(self):
        self.assertEqual(compute(), 4)
'''
SECOND = '''
    def test_z(self):
        fut = self.loop.create_future()

        def cb():
            try:
                self.assertEqual(compute(), 5)
            except Exception as e:
                fut.set_exception(e)
            else:
                fut.set_result(None)

        self.loop.call_soon(cb)
        self.loop.run_until_complete(fut)
'''


def added(before: str, after: str, freeze: bool = False) -> list[tuple[str, str]]:
    change = FileChange(PATH, "modified", before.encode(), after.encode())
    _ir, findings, _verdict = analyze([change], Config(), Contract(oracle_freeze=freeze), [], TODAY)
    return [(f.rule, f.severity) for f in findings]


@pytest.mark.parametrize("freeze", [False, True])
def test_adding_a_proven_relay_reports_nothing(freeze):
    assert added(HEAD, HEAD + "\n" + BASE.split("class TestLoop(LoopTestCase):\n")[1], freeze) == []


def test_adding_a_relay_outside_the_rules_reports_it():
    after = HEAD + "\n" + REFUSED["the consumer under an if"].split("class TestLoop(LoopTestCase):\n")[1]
    assert added(HEAD, after) == [("BROAD_EXCEPT_ADDED", "high")]


def test_adding_a_relay_beside_an_unchanged_one_reports_nothing():
    assert added(BASE, BASE + SECOND) == []


def test_a_new_swallow_beside_an_unchanged_relay_still_reports():
    swallow = '''
    def test_y(self):
        try:
            self.assertEqual(compute(), 4)
        except Exception as e:
            print(e)
'''
    assert added(BASE, BASE + swallow) == [("BROAD_EXCEPT_ADDED", "high")]


def test_an_edit_elsewhere_does_not_report_an_unchanged_relay():
    # The string "loop" turns the relay's loop untrusted on the after side
    # (R6). Read on each side alone that would be one relay lost and one
    # swallow added; 0.10 counts the same handler on both sides, and the
    # bound keeps that (the 2026-10-29 status review's N1).
    after = BASE + '\n\nLABEL = "loop"\n'
    assert parsed(after).relay_handlers == ()
    assert added(BASE, after) == []
    assert added(BASE, after, freeze=True) == []


def test_residual_row171_breaking_a_relay_is_not_reported():
    # THREATMODEL row 171: an edit that breaks a relay the rule reads, here
    # by removing its only consumer, is not reported, exactly as on 0.10,
    # which counts the handler as swallowing on both sides.
    broken = v("        self.loop.run_until_complete(fut)\n", "")
    assert parsed(broken).relay_handlers == ()
    assert added(BASE, broken) == []
    assert added(BASE, broken, freeze=True) == []


def test_never_more_than_0_10_reports():
    # Relays left out of both sides alone would report the after side's
    # unread relay; the 0.10 difference is empty, so nothing is added.
    after = BASE + SECOND + '\n\nLABEL = "loop"\n'
    assert parsed(after).relay_handlers == ()
    assert added(BASE + SECOND, after) == []


# --- linear time -------------------------------------------------------------------------------------

def test_400_relay_shaped_handlers_sharing_one_future_parse_quickly():
    # The 2026-10-29 status review measured a first prototype at 25.5 s for
    # this shape, against the PreToolUse ask's 30-second deadline
    # (pretool.DEADLINE_SECONDS). Each handler is refused: the future has
    # 400 set_exception sites.
    head, test = BASE.split("        def cb():\n")
    callbacks = "".join(
        CALLBACK.replace("def cb()", f"def cb{i}()").replace("compute(), 3", f"compute(), {i}")
        + f"\n        self.loop.call_soon(cb{i})\n" for i in range(400))
    source = head + callbacks + "        self.loop.run_until_complete(fut)\n"
    started = time.perf_counter()
    result = parsed(source)
    elapsed = time.perf_counter() - started
    assert len(result.swallowing_handlers) == 400 and result.relay_handlers == ()
    assert elapsed < 5.0, elapsed


# --- the fix round: a relay made proven in the same change -------------------------------------------
#
# The 2026-10-29 adversarial reviews (dress-swallow problem 1, drift-perf
# problem 1): with relays left out of both sides, a before-side handler that
# was not a proven relay, but turns into one, matched a new swallow of the
# same text. The engine now reads the after side's relays only.

SWALLOWED_Y = HEAD.replace(
    "        self.assertEqual(compute(), 4)\n",
    "        try:\n            self.assertEqual(compute(), 4)\n        except Exception as e:\n            print(e)\n")
RELAY_X = BASE.split("class TestLoop(LoopTestCase):\n")[1]


@pytest.mark.parametrize("freeze", [False, True])
@pytest.mark.parametrize("before", [
    HEAD + "\n" + RELAY_X + '\n\nLABEL = "loop"\n',
    HEAD.replace("from tests.support import LoopTestCase\n", 'from tests.support import LoopTestCase\n\nIDS = ["loop"]\n')
    + "\n" + RELAY_X,
    HEAD + "\n" + v("        self.loop.run_until_complete(fut)\n", "", RELAY_X),
    HEAD + "\n" + v("                fut.set_exception(e)\n", "                print(e)\n", RELAY_X),
], ids=["a-string-removed", "a-string-in-a-list-removed", "the-consumer-added", "the-body-rewritten"])
def test_a_relay_made_proven_does_not_pay_for_a_new_swallow(before, freeze):
    after = SWALLOWED_Y + "\n" + RELAY_X
    assert parsed(after).relay_handlers == HANDLER
    assert added(before, after, freeze) == [("BROAD_EXCEPT_ADDED", "high")]


def test_a_relay_beside_a_same_text_swallow_reports_as_on_0_10():
    # The price of reading the after side alone: the change adds an honest
    # relay, but the before side holds a swallow of the same first line, so
    # the addition is counted, as 0.10 counts it.
    before = SWALLOWED_Y
    after = SWALLOWED_Y + "\n" + RELAY_X
    assert parsed(after).relay_handlers == HANDLER
    assert added(before, after) == [("BROAD_EXCEPT_ADDED", "high")]


# --- the fix round: R2 through a call ----------------------------------------------------------------

ASSERT_HELPER = '''import asyncio

from app import compute


def assert_total(value):
    assert value == 3


async def test_total():
    fut = asyncio.Future()

    def check():
        try:
            assert_total(compute())
        except Exception as e:
            fut.set_exception(e)
        else:
            fut.set_result(None)

    check()
    await fut
'''

THROUGH_A_CALL = {
    "a module-level assert_ helper": ASSERT_HELPER,
    "a plain helper beside an unread pytest.fail": v("        try:\n            assert_total(compute())\n",
                                                     "        try:\n            total_is_three(compute())\n"
                                                     "            if False:\n                pytest.fail('unreachable')\n",
                                                     ASSERT_HELPER.replace("def assert_total", "def total_is_three").replace(
                                                         "import asyncio\n", "import asyncio\n\nimport pytest\n")),
    "a nested helper": v("    def check():\n", "    def assert_ok(value):\n        assert value == 3\n\n    def check():\n",
                         ASSERT_HELPER.replace("assert_total(compute())", "assert_ok(compute())").replace(
                             "def assert_total(value):\n    assert value == 3\n\n\n", "")),
    "a helper two calls away": v("async def test_total():\n",
                                 "def assert_run(value):\n    assert_total(value)\n\n\nasync def test_total():\n",
                                 ASSERT_HELPER.replace("            assert_total(compute())", "            assert_run(compute())")),
    "a method another test runs": v("    def test_x(self):\n",
                                    "    def assertTotal(self, value):\n        self.assertEqual(value, 3)\n\n"
                                    "    def test_other(self):\n        self.assertTotal(compute())\n\n    def test_x(self):\n",
                                    v("self.assertEqual(compute(), 3)", "self.assertTotal(compute())")),
}


@pytest.mark.parametrize("source", THROUGH_A_CALL.values(), ids=THROUGH_A_CALL.keys())
def test_r2_a_try_body_that_reaches_a_unit_assertion_through_a_call_is_not_a_relay(source):
    assert not credited(source)


def test_r2_the_unit_runs_the_helper_assertion_through_the_callback():
    # dress-swallow problem 2: the unit inherits the helper's assertion, and
    # deleting it is ASSERT_REMOVED, so the relay would guard a unit oracle.
    unit = parsed(ASSERT_HELPER).units[0]
    assert [a.text for a in unit.side.assertions] == ["assert value == 3"]
    assert added(ASSERT_HELPER, ASSERT_HELPER.replace("    assert value == 3\n", "    pass\n")) == [
        ("ASSERT_REMOVED", "high")]


def test_r2_an_assert_named_helper_call_is_refused_even_handed_off():
    # Handed off rather than called, the callback runs no parse-time unit's
    # assertion, but `assert_total(...)` is a call 0.10 reads as an oracle
    # and the engine may fold its assertion into the unit after the parse,
    # so R2 refuses it: only a method of the test's own receiver passes (the
    # second review; this test expected the opposite in D-190's first commit).
    assert not credited(v("    check()\n", "    asyncio.get_running_loop().call_soon(check)\n", ASSERT_HELPER))


def test_r2_a_try_body_calling_functions_no_unit_assertion_runs_in_is_read():
    # uvloop 2081db89's `do(...)`: a nested helper without an assertion,
    # in a file whose other tests hold unit assertions.
    source = HEAD + "\n" + v("                self.assertEqual(compute(), 3)\n",
                             "                def do(value):\n                    return value\n\n"
                             "                self.assertEqual(do(compute()), 3)\n", RELAY_X)
    assert parsed(source).units
    assert credited(source)


# --- the fix round: R3, R6 and R7 against same-file stand-ins -----------------------------------------

MODULE_RESULT = MODULE_LEVEL.replace("    await fut\n", "    await asyncio.sleep(0)\n    fut.result()\n")

STAND_INS = {
    # R7, asyncio: dress-swallow problem 3 and drift-perf problem 3.
    "asyncio under another name": v("import asyncio\n", "import asyncio\nimport asyncio as aio\nimport unittest.mock\n\n"
                                    "aio.Future = unittest.mock.MagicMock\n", MODULE_RESULT),
    "importlib": v("import asyncio\n", "import asyncio\nimport importlib\nimport unittest.mock\n\n"
                   "importlib.import_module('asyncio').Future = unittest.mock.MagicMock\n", MODULE_RESULT),
    "asyncio's attribute table": v("import asyncio\n", "import asyncio\nimport unittest.mock\n\n"
                                   "asyncio.__dict__['Fut' + 'ure'] = unittest.mock.MagicMock\n", MODULE_RESULT),
    "from asyncio import": v("import asyncio\n", "import asyncio\nfrom asyncio import futures\n", MODULE_RESULT),
    "asyncio read as a value": v("import asyncio\n", "import asyncio\n\nMODULE = asyncio\n", MODULE_RESULT),
    "a string naming Future": v("import asyncio\n", "import asyncio\n\nNAME = 'Future'\n", MODULE_RESULT),
    "a store of Future on another receiver": v("import asyncio\n", "import asyncio\nimport types\n\n"
                                               "types.SimpleNamespace.Future = None\n", MODULE_RESULT),
    # R6, the loop: dress-swallow problem 4 and drift-perf problem 3.
    "setattr with a computed name": v("    def test_x(self):", "    def setUp(self):\n        super().setUp()\n"
                                      "        setattr(self, 'lo' + 'op', compute())\n\n    def test_x(self):"),
    "an alias of self in setUp": v("    def test_x(self):", "    def setUp(self):\n        super().setUp()\n"
                                   "        me = self\n        me.loop = compute()\n\n    def test_x(self):"),
    "a helper's parameter": v("class TestLoop", "def install(case):\n    case.loop = compute()\n\n\nclass TestLoop", v(
        "    def test_x(self):", "    def setUp(self):\n        super().setUp()\n        install(self)\n\n    def test_x(self):")),
    "vars() in the class body": v("class TestLoop(LoopTestCase):\n",
                                  "class TestLoop(LoopTestCase):\n    vars()['lo' + 'op'] = property(compute)\n\n"),
    "a stand-in built with protocol keywords": v("class TestLoop", "FAKE = types.SimpleNamespace(create_future=compute, "
                                                 "call_soon=compute, run_until_complete=compute)\n\n\nclass TestLoop",
                                                 v("import asyncio\n", "import asyncio\nimport types\n")),
    "self's attribute table": v("    def test_x(self):", "    def setUp(self):\n        super().setUp()\n"
                                "        self.__dict__['lo' + 'op'] = compute()\n\n    def test_x(self):"),
    # R3, the future reached without its name: dress-swallow problem 5.
    "a closure cell": v("        self.loop.call_soon(cb)\n",
                        "        cb.__closure__[0].cell_contents.set_result(None)\n        self.loop.call_soon(cb)\n"),
    "a frame from a module-level helper": v("class TestLoop", 'def steal():\n    sys._getframe(1).f_locals["fut"]'
                                            '.set_result(None)\n\n\nclass TestLoop', v(
        "import asyncio\n", "import asyncio\nimport sys\n", v("        self.loop.call_soon(cb)\n",
                                                              "        steal()\n        self.loop.call_soon(cb)\n"))),
}


@pytest.mark.parametrize("source", STAND_INS.values(), ids=STAND_INS.keys())
def test_a_same_file_stand_in_spelling_is_not_trusted(source):
    assert not credited(source)


def test_r6_a_store_of_the_loop_on_a_fresh_local_is_no_redirect():
    # uvloop's `proto = MyProto(loop=loop); proto.loop = loop`, in another test.
    source = v("    def test_x(self):", "    def test_proto(self):\n        proto = compute()\n"
               "        proto.loop = self.loop\n\n    def test_x(self):")
    assert credited(source)


# --- the fix round: R5, consumers that give up and a B whose failure is lost --------------------------

def nested_b(head: str, tail: str) -> str:
    """BASE with test_x's body moved into a function test_x defines (`head`), then `tail` in test_x."""
    prefix, body = BASE.split("    def test_x(self):\n")
    body = "".join("    " + line if line.strip() else line for line in body.splitlines(keepends=True))
    return prefix + "    def test_x(self):\n" + head + body + tail


GIVEN_UP = {
    # dress-swallow problem 6.
    "wait_for under except TimeoutError": v("        self.loop.call_soon(cb)\n        self.loop.run_until_complete(fut)\n",
                                            "        self.loop.call_later(0.05, cb)\n        try:\n"
                                            "            self.loop.run_until_complete(asyncio.wait_for(fut, 0))\n"
                                            "        except asyncio.TimeoutError:\n            pass\n"
                                            "        self.loop.run_until_complete(asyncio.sleep(0.2))\n"),
    "gather under except KeyError": v("        self.loop.run_until_complete(fut)\n",
                                      "        try:\n            self.loop.run_until_complete(asyncio.gather(fut, compute()))\n"
                                      "        except KeyError:\n            pass\n"),
    "a handler named through an alias of Exception": v("        self.loop.run_until_complete(fut)\n",
                                                       "        try:\n            self.loop.run_until_complete(fut)\n"
                                                       "        except Err:\n            pass\n",
                                                       v("class TestLoop", "Err = Exception\n\n\nclass TestLoop")),
    "a broad handler that raises only in a nested def": v("        self.loop.run_until_complete(fut)\n",
                                                          "        try:\n            self.loop.run_until_complete(fut)\n"
                                                          "        except Exception:\n            def _unused():\n"
                                                          "                raise\n"),
    "a broad handler that raises SkipTest": v("        self.loop.run_until_complete(fut)\n",
                                              "        try:\n            self.loop.run_until_complete(fut)\n"
                                              "        except Exception:\n            raise unittest.SkipTest('flaky')\n"),
    "a non-broad handler after an earlier raise": v("        self.loop.run_until_complete(fut)\n",
                                                    "        try:\n            int('x')\n"
                                                    "            self.loop.run_until_complete(fut)\n"
                                                    "        except ValueError:\n            pass\n"),
    "a decorated nested coroutine": v("        self.loop.run_until_complete(fut)\n",
                                      "        @(lambda f: lambda: asyncio.sleep(0))\n        async def main():\n"
                                      "            await fut\n\n        self.loop.run_until_complete(main())\n"),
    "a return under a guard": v("        self.loop.run_until_complete(fut)\n",
                                "        if compute():\n            return\n        self.loop.run_until_complete(fut)\n"),
    "a raise before the consumer": v("        self.loop.run_until_complete(fut)\n",
                                     "        raise unittest.SkipTest('later')\n        self.loop.run_until_complete(fut)\n"),
    # dress-swallow problem 7: B's own failure does not reach the test.
    "B handed to a thread": nested_b("        def worker():\n", "\n        threading.Thread(target=worker).start()\n"),
    "B handed to the loop": nested_b("        def outer():\n", "\n        self.loop.call_soon(outer)\n"),
    "B called inside a lambda": nested_b("        def worker():\n", "\n        self.loop.call_soon(lambda: worker())\n"),
    "a method handed to a thread": v("    def test_x(self):\n", "    def test_x(self):\n"
                                     "        threading.Thread(target=self._check).start()\n\n    def _check(self):\n"),
    "a generator B": v("            self.loop.run_until_complete(fut)\n",
                       "            yield\n            self.loop.run_until_complete(fut)\n",
                       nested_b("        def worker():\n", "\n        next(worker())\n")),
    "a decorated nested B": nested_b("        @functools.lru_cache\n        def worker():\n", "\n        worker()\n"),
}


@pytest.mark.parametrize("source", GIVEN_UP.values(), ids=GIVEN_UP.keys())
def test_a_consumer_whose_failure_can_be_lost_proves_nothing(source):
    assert not credited(source)


# R5 runs a nested C only as `await C(...)` or `<trusted L>.run_until_complete(C(...))`
# (D-190); the design prototype also accepted the first two spellings below.
OTHER_RUN_SITES = {
    "a plain call of a sync def": v("        self.loop.run_until_complete(fut)\n",
                                    "        def main():\n            self.loop.run_until_complete(fut)\n\n"
                                    "        main()\n"),
    "wait_for around the nested coroutine": v("        self.loop.run_until_complete(fut)\n",
                                              "        async def main():\n            await fut\n\n"
                                              "        self.loop.run_until_complete(asyncio.wait_for(main(), 5))\n"),
    "asyncio.run as the nested coroutine's run site": v("        self.loop.run_until_complete(fut)\n",
                                                        "        async def main():\n            await fut\n\n"
                                                        "        asyncio.run(main())\n"),
}


def test_r5_a_nested_coroutine_the_trusted_loop_runs_is_read():
    assert credited(v("        self.loop.run_until_complete(fut)\n",
                      "        async def main():\n            await fut\n\n"
                      "        self.loop.run_until_complete(main())\n"))


@pytest.mark.parametrize("source", OTHER_RUN_SITES.values(), ids=OTHER_RUN_SITES.keys())
def test_r5_no_other_run_site_is_read(source):
    assert not credited(source)


def test_r5_a_guarded_skip_before_the_run_site_is_read():
    # uvloop 2081db89 opens its test with `if self.implementation ==
    # 'asyncio': raise unittest.SkipTest()`: a raise fails or skips the test
    # and never lets it pass.
    source = v("    def test_x(self):\n", "    def test_x(self):\n        if compute():\n"
               "            raise unittest.SkipTest('not here')\n\n")
    assert credited(source)


def test_r5_a_nested_b_called_directly_is_read():
    # uvloop 2081db89's `test_client(addr)`: a nested B whose name is only called.
    assert credited(nested_b("        def worker():\n", "\n        worker()\n"))


def test_r5_a_coroutine_that_awaits_its_own_future_is_read_however_it_is_run():
    # drift-perf problem 5: R5 reads B's own consumer, so asyncio.run(main())
    # does not matter when main binds asyncio.Future() and awaits it.
    source = '''import asyncio

from app import compute


def test_x():
    async def main():
        fut = asyncio.Future()

        def cb():
            try:
                assert compute() == 3
            except Exception as e:
                fut.set_exception(e)
            else:
                fut.set_result(None)

        asyncio.get_running_loop().call_soon(cb)
        await fut

    asyncio.run(main())
'''
    assert credited(source)
    assert not credited(source.replace("fut = asyncio.Future()", "fut = asyncio.get_running_loop().create_future()"))


# --- the fix round: robustness and linear time -------------------------------------------------------

def test_a_reader_that_cannot_decide_leaves_the_handler_a_swallow(monkeypatch):
    def too_deep(self, handler, try_node):
        raise RecursionError("maximum recursion depth exceeded")

    monkeypatch.setattr(failure_relays.Reader, "proven", too_deep)
    result = parsed(BASE)
    assert result.parse_ok
    assert result.swallowing_handlers == HANDLER and result.relay_handlers == ()


def test_a_deep_guard_in_the_consuming_coroutine_is_no_engine_error():
    # drift-perf problem 4: a 300-term guard before the await raised
    # RecursionError from `_unreachable_ids`, which 0.10 never runs on a
    # nested coroutine. The reading does not evaluate guards.
    relay = v("        self.loop.run_until_complete(fut)\n",
              "        async def main():\n            if compute() == " + "+".join(["1"] * 300) + ":\n"
              "                pass\n            await fut\n\n        self.loop.run_until_complete(main())\n", RELAY_X)
    after = HEAD.replace("    def test_y", "    def test_z(self):\n        try:\n            self.assertEqual(compute(), 5)\n"
                         "        except Exception:\n            pass\n\n    def test_y") + "\n" + relay
    assert parsed(after).relay_handlers == HANDLER
    assert added(HEAD, after, freeze=True) == [("BROAD_EXCEPT_ADDED", "high")]


def _chain(depth: int, filler: int) -> str:
    """drift-perf problem 2: `depth` nested coroutines, each relaying to its own future and awaiting it."""
    lines = ["import asyncio\n\nfrom app import compute\nfrom tests.support import LoopTestCase\n\n\n",
             "class TestLoop(LoopTestCase):\n    def test_x(self):\n"]
    for level in range(depth):
        pad = " " * (8 + 4 * level)
        lines.append(f"{pad}async def lvl{level}():\n{pad}    fut{level} = asyncio.Future()\n\n"
                     f"{pad}    def cb{level}():\n{pad}        try:\n"
                     f"{pad}            self.assertEqual(compute({level}), {level})\n"
                     f"{pad}        except Exception as e:\n{pad}            fut{level}.set_exception(e)\n"
                     f"{pad}        else:\n{pad}            fut{level}.set_result(None)\n\n")
    lines.append(" " * (8 + 4 * depth) + "data = [" + ",".join(["0"] * filler) + "]\n")
    for level in reversed(range(depth)):
        body = " " * (12 + 4 * level)
        if level + 1 < depth:
            lines.append(f"{body}await lvl{level + 1}()\n")
        lines.append(f"{body}asyncio.get_running_loop().call_soon(cb{level})\n{body}await fut{level}\n")
    lines.append("        self.loop.run_until_complete(lvl0())\n")
    return "".join(lines)


def test_a_chain_of_nested_coroutines_parses_quickly():
    # Reachability by `_unreachable_ids` on each level walked everything
    # below it: about 5.4 seconds for this file on the first implementation,
    # where 0.10 parses it in about 0.4 (LAPTOP-01AGNPJU, 2026-10-29).
    source = _chain(90, 60000)
    started = time.perf_counter()
    result = parsed(source)
    elapsed = time.perf_counter() - started
    assert len(result.relay_handlers) == len(result.swallowing_handlers) == 90
    assert elapsed < 3.0, elapsed


# --- the second review: more same-file spellings, raised by Argon and verified by Claude ----------------
# A Gemini 4 Argon review of d9fcd20b found spellings of the routes the fix
# round closed that the reading still credited; each reproduced there. The
# rules now close their families: R7 reads asyncio.Future, wait_for and
# gather only as a call's function and refuses any store reached from
# asyncio, R6 refuses a stored `result` and a receiver bound to a call that
# reads a parameter, R3 refuses any read of a dynamic builtin, and R5 passes
# a `with` only for a context manager the test's base class provides and
# requires every call of B to be one nothing in its function can swallow.

def _with_import(name: str, source: str) -> str:
    return source.replace("import asyncio\n", f"import asyncio\nimport {name}\n", 1)


SETUP_STORE = "    def setUp(self):\n        super().setUp()\n        BODY\n\n    def test_x(self):"

SECOND_REVIEW = {
    # R7 (Argon F3): a method of asyncio.Future patched, directly or through an alias.
    "asyncio.Future.result patched": v("import asyncio\n", "import asyncio\n\nasyncio.Future.result = lambda self: None\n",
                                       MODULE_RESULT),
    "asyncio.Future aliased, then patched": v("import asyncio\n", "import asyncio\n\nFutureType = asyncio.Future\n"
                                              "FutureType.result = lambda self: None\n", MODULE_RESULT),
    "a result stored on another receiver": v("import asyncio\n", "import asyncio\nimport types\n\n"
                                             "types.SimpleNamespace.result = None\n", MODULE_RESULT),
    # R6 (F4): an alias of the receiver through a call's result.
    "an alias of self through a call": v("    def test_x(self):", SETUP_STORE.replace(
        "BODY", "me = (lambda x: x)(self)\n        me.loop = compute()")),
    "a helper's parameter through a call": v("class TestLoop", "def install(case):\n    me = next(iter((case,)))\n"
                                             "    me.loop = compute()\n\n\nclass TestLoop", v(
        "    def test_x(self):", SETUP_STORE.replace("BODY", "install(self)"))),
    # R3 (F4): a dynamic builtin read without a call of it, or through builtins.
    "setattr through an alias": v("    def test_x(self):", SETUP_STORE.replace(
        "BODY", "s = setattr\n        s(self, 'lo' + 'op', compute())")),
    "vars through an alias": v("    def test_x(self):", SETUP_STORE.replace(
        "BODY", "w = vars\n        w(self)['lo' + 'op'] = compute()")),
    "builtins.vars": _with_import("builtins", v("    def test_x(self):", SETUP_STORE.replace(
        "BODY", "builtins.vars(self)['lo' + 'op'] = compute()"))),
    "getattr handed on": v("        self.loop.call_soon(cb)\n", "        fetch = getattr\n        self.loop.call_soon(cb)\n"),
    # R5 (F4): a consumer under a with the file names or builds.
    "suppress with an aliased type": _with_import("contextlib", v(
        "        self.loop.run_until_complete(fut)\n",
        "        with contextlib.suppress(Err):\n            self.loop.run_until_complete(fut)\n",
        v("class TestLoop", "Err = Exception\n\n\nclass TestLoop"))),
    "suppress through an alias": _with_import("contextlib", v(
        "        self.loop.run_until_complete(fut)\n",
        "        sup = contextlib.suppress\n        with sup(Exception):\n            self.loop.run_until_complete(fut)\n")),
    "a context manager the file defines": _with_import("contextlib", v(
        "        self.loop.run_until_complete(fut)\n",
        "        with self.quiet():\n            self.loop.run_until_complete(fut)\n",
        v("    def test_x(self):", "    @contextlib.contextmanager\n    def quiet(self):\n        try:\n"
                                  "            yield\n        except Exception:\n            pass\n\n    def test_x(self):"))),
    # R5 (F5): B's own call swallowed, under a with, under a finally that returns, or never made.
    "B's call swallowed": nested_b("        def worker():\n",
                                   "\n        try:\n            worker()\n        except Exception:\n            pass\n"),
    "B's call under suppress": _with_import("contextlib", nested_b(
        "        def worker():\n", "\n        with contextlib.suppress(Exception):\n            worker()\n")),
    "B's call under a finally that returns": nested_b(
        "        def worker():\n", "\n        try:\n            worker()\n        finally:\n            return\n"),
    "a nested B never called": nested_b("        def worker():\n", "\n"),
}


@pytest.mark.parametrize("source", SECOND_REVIEW.values(), ids=SECOND_REVIEW.keys())
def test_a_second_review_spelling_is_not_trusted(source):
    assert not credited(source)


def test_r5_a_with_the_base_class_provides_is_read():
    # uvloop's `with self.tcp_client(...)`: R6 trusts it as it trusts self.loop.
    assert credited(v("        self.loop.run_until_complete(fut)\n",
                      "        with self.tcp_client(compute):\n            self.loop.run_until_complete(fut)\n"))


def test_r5_a_with_the_file_defines_on_the_receiver_is_not_read():
    source = v("        self.loop.run_until_complete(fut)\n",
               "        with self.tcp_client(compute):\n            self.loop.run_until_complete(fut)\n",
               v("    def test_x(self):", "    def tcp_client(self, prog):\n        return compute()\n\n    def test_x(self):"))
    assert not credited(source)


GATHERED = '''import asyncio

from app import compute
from tests.support import LoopTestCase


class TestLoop(LoopTestCase):
    def test_x(self):
        async def client():
            fut = self.loop.create_future()

            def cb():
                try:
                    self.assertEqual(compute(), 3)
                except Exception as e:
                    fut.set_exception(e)
                else:
                    fut.set_result(None)

            self.loop.call_soon(cb)
            await fut

        async def start_all():
            tasks = []
            for _ in range(3):
                tasks.append(client())
            await asyncio.wait_for(asyncio.gather(*tasks), 10.0)

        self.loop.run_until_complete(start_all())
'''


def test_r5_a_nested_b_called_in_a_loop_and_gathered_is_read():
    # uvloop 2081db89's `tasks.append(test_client(addr))`: a loop or an `if`
    # around B's call can only keep B from running.
    assert credited(GATHERED)


def test_r3_getattr_called_with_a_constant_name_stays_allowed():
    assert credited(v("        self.loop.call_soon(cb)\n", "        getattr(self, 'maxDiff')\n        self.loop.call_soon(cb)\n"))


# --- the third round: a second Argon review, raised by Argon and verified by Claude ----------------------
# A second review of the relay reading found more spellings that it still
# credited; each reproduced on eee48652. R2 now refuses an oracle call that
# is no method of the test's own receiver; R5 requires a nested B to be
# called from outside its own body and never from a generator expression;
# R6 treats a name bound directly to a parameter as that parameter; and R3
# reads a `getattr` with a starred argument as computed.

FIXTURE_CHECKER = '''import asyncio

import pytest

from app import compute


@pytest.fixture
def assert_total():
    def check(value):
        assert value == 3
    return check


async def test_x(assert_total):
    fut = asyncio.Future()

    def cb():
        try:
            assert_total(compute())
        except Exception as e:
            fut.set_exception(e)
        else:
            fut.set_result(None)

    asyncio.get_running_loop().call_soon(cb)
    await fut
'''

THIRD_ROUND = {
    "a fixture's checker called in the try": FIXTURE_CHECKER,
    "pytest.fail in the try": v("                self.assertEqual(compute(), 3)\n",
                                "                if compute() != 3:\n                    pytest.fail('total')\n",
                                _with_import("pytest", BASE)),
    "a nested B that only calls itself": nested_b("        def worker():\n", "\n        pass\n").replace(
        "            self.loop.run_until_complete(fut)\n",
        "            self.loop.run_until_complete(fut)\n            if False:\n                worker()\n", 1),
    "B's call deferred in a generator expression": nested_b(
        "        def worker():\n",
        "\n        gen = (worker() for _ in range(1))\n        try:\n            next(gen)\n        except Exception:\n"
        "            pass\n"),
    "an alias of self, then through a call": v("    def test_x(self):", SETUP_STORE.replace(
        "BODY", "s = self\n        me = (lambda x: x)(s)\n        me.loop = compute()")),
    "a getattr with a starred argument": v("        self.loop.call_soon(cb)\n",
                                           "        getattr(*(self, 'lo' + 'op'), 'default')\n        self.loop.call_soon(cb)\n"),
}


@pytest.mark.parametrize("source", THIRD_ROUND.values(), ids=THIRD_ROUND.keys())
def test_a_third_round_spelling_is_not_trusted(source):
    assert not credited(source)


def test_r2_a_method_of_the_tests_own_receiver_passes():
    # uvloop's callbacks assert through `self.assertEqual(...)`.
    assert credited(v("                self.assertEqual(compute(), 3)\n",
                      "                self.assertTrue(compute() == 3)\n                self.fail('unreachable') if False else None\n"))

"""#419 closes as a documented residual (D-191): what 0.11 does with bought repair evidence.

E1 asks whether a production change explains a test change. A weakened
oracle beside repair evidence is held at warn, and the default
`fail_on = "high"` passes warn. D-191 closes #419 by stating exactly what
0.11.0 does, not by narrowing E1, so each test here pins one sentence of
that statement (THREATMODEL item 4 and rows 2, 93, 130 and 131; SPEC §5;
KNOWN-ISSUES-next; docs/enterprise.md §7):

- Route B: a modification of an existing production file checkwash cannot
  read, a template or `AUTHORS` among them, holds the four unit-scoped
  weakening rules at warn;
- Route A: an edit the fingerprint keeps inside a symbol the test reaches,
  `+ 0`, `pass`, `...` or a renamed parameter, does the same for a finding
  that has a test unit; a finding with none takes Route B only;
- a broad `except` added in a Python test refuses Route B (D-176), unless it
  is a proven failure relay (D-190), and Route A never reaches it;
- JS/TS tests keep Route B (row 131);
- `fail_on = "warn"` and `oracle_freeze` block both routes.

The tests named `test_residual_row<N>_...` pin today's behaviour of an open
THREATMODEL row. A fix changes that expectation, as a recorded change, and
does not need this file's sentence to stay true.

All input programs are source data, not runtime-qualified repair examples.
"""
import datetime

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.frontends.python.frontend import parse_python

TODAY = datetime.date(2026, 10, 29)
TEST = "tests/test_billing.py"
BEFORE = (b"from billing import compute_invoice_total\n\n\n"
          b"def test_invoice_total():\n"
          b"    total = compute_invoice_total([10.5, 94.8])\n"
          b"    assert total == 105.3\n")
WEAKENINGS = {
    "ASSERT_WEAKENED": BEFORE.replace(b"assert total == 105.3", b"assert total > 0"),
    "ASSERT_REMOVED": BEFORE.replace(b"    assert total == 105.3\n", b""),
    "TEST_DISABLED": b"import pytest\n" + BEFORE.replace(
        b"def test_invoice_total", b"@pytest.mark.skip(reason='later')\ndef test_invoice_total"),
}
APPROX = b"import pytest\n" + BEFORE.replace(b"assert total == 105.3", b"assert total == pytest.approx(105.3, abs=1e-9)")
RULES = ["ASSERT_WEAKENED", "ASSERT_REMOVED", "TEST_DISABLED", "TOLERANCE_LOOSENED"]

PROD = b"def compute_invoice_total(items):\n    return sum(items)\n"
NOOPS = {
    "plus_zero": b"def compute_invoice_total(items):\n    return sum(items) + 0\n",
    "pass": b"def compute_invoice_total(items):\n    pass\n    return sum(items)\n",
    "ellipsis": b"def compute_invoice_total(items):\n    ...\n    return sum(items)\n",
    "rename": b"def compute_invoice_total(entries):\n    return sum(entries)\n",
}
TEMPLATE = FileChange("app/templates/invoice.html", "modified",
                      b"<p>{{ total }}</p>\n", b"<!-- c -->\n<p>{{ total }}</p>\n")
# Files the inert list in roles.py does not name: each is an existing
# production-role file checkwash cannot read, so one added line buys Route B.
CHEAP = [FileChange(path, "modified", b"a\n", b"a\nb\n")
         for path in ("AUTHORS", "CHANGELOG", ".coveragerc", "docs/requirements.txt", "doc/notes.txt")]
OPAQUE = [TEMPLATE, *CHEAP]


def run(changes, config=None, contract=None):
    return analyze(list(changes), config or Config(), contract or Contract(), [], TODAY)


def one(changes, rule, config=None, contract=None):
    """(severity, de-escalators, escalators, verdict) of the one finding of `rule`."""
    _ir, findings, verdict = run(changes, config, contract)
    hit, = [f for f in findings if f.rule == rule]
    return hit.severity, hit.deescalators, hit.escalators, verdict


def weakened(rule):
    """The test file's change that gives one finding of `rule`."""
    if rule == "TOLERANCE_LOOSENED":
        return FileChange(TEST, "modified", APPROX, APPROX.replace(b"abs=1e-9", b"abs=50"))
    return FileChange(TEST, "modified", BEFORE, WEAKENINGS[rule])


def noop(name):
    return FileChange("billing.py", "modified", PROD, NOOPS[name])


HELD = ("warn", ["REPAIR_EVIDENCE"], [], "pass")


# --- Route B: an opaque modification is evidence for the whole diff ---------------------------------

@pytest.mark.parametrize("opaque", OPAQUE, ids=lambda change: change.path)
@pytest.mark.parametrize("rule", RULES)
def test_route_b_holds_the_four_rules_at_warn(rule, opaque):
    assert one([weakened(rule), opaque], rule) == HELD


def test_route_b_holds_a_rewritten_expected_value_at_warn():
    # The expectation family keeps opaque-change evidence in every language (row 130).
    rewritten = FileChange(TEST, "modified", BEFORE, BEFORE.replace(b"== 105.3", b"== 105.4"))
    assert one([rewritten, TEMPLATE], "EXPECTED_VALUE_CHANGED") == HELD


@pytest.mark.parametrize("rule", RULES)
def test_without_production_the_four_rules_block(rule):
    assert one([weakened(rule)], rule) == ("high", [], ["NO_PROD_CHANGE_IN_DIFF"], "block")


# --- Route A: an edit the fingerprint keeps in a symbol the test reaches ----------------------------

@pytest.mark.parametrize("name", list(NOOPS))
@pytest.mark.parametrize("rule", RULES)
def test_route_a_holds_the_four_rules_at_warn(rule, name):
    assert one([weakened(rule), noop(name)], rule) == HELD


CALC = b"class Calc:\n    def total(self, items):\n        return sum(items)\n\n    def other(self):\n        return 1\n"
CLASS_EDITS = {
    "sibling_method": CALC.replace(b"return 1\n", b"return 1 + 0\n"),
    "reordered": b"class Calc:\n    def other(self):\n        return 1\n\n    def total(self, items):\n        return sum(items)\n",
    "class_attribute": CALC.replace(b"class Calc:\n", b"class Calc:\n    _seen = 0\n\n"),
}


@pytest.mark.parametrize("edit", list(CLASS_EDITS))
def test_route_a_reaches_the_whole_class_a_test_calls(edit):
    # A class is a symbol whose fingerprint covers its body (SPEC §5 clause 1).
    test = b"from billing import Calc\n\n\ndef test_total():\n    assert Calc().total([1.0]) == 1.0\n"
    changes = [FileChange(TEST, "modified", test, test.replace(b"== 1.0", b"> 0")),
               FileChange("billing.py", "modified", CALC, CLASS_EDITS[edit])]
    assert one(changes, "ASSERT_WEAKENED") == HELD


def test_residual_row93_one_hop_matches_leaf_name_in_any_module():
    """One hop matches the caller by its leaf name, with no module check (row 93, D-191).

    The test calls `app.views.format_invoice`, which the diff does not
    touch; a same-named function in an unrelated changed module calls a
    changed method, and that holds the weakened assertion at warn. A fix of
    the one-hop module check changes this expectation, as a recorded change.
    """
    test = b"from app.views import format_invoice\n\n\ndef test_fmt():\n    assert format_invoice([1.0]) == 1.0\n"
    other = (b"class Calc:\n    def total(self, items):\n        return sum(items)\n\n\n"
             b"def format_invoice(items):\n    c = Calc()\n    return c.total(items)\n")
    changes = [FileChange(TEST, "modified", test, test.replace(b"== 1.0", b"> 0")),
               FileChange("lib/other.py", "modified", other, other.replace(b"return sum(items)", b"return sum(items) + 0"))]
    assert one(changes, "ASSERT_WEAKENED") == HELD


def test_residual_row93_issue420_top_level_callee_gives_no_hop():
    """A changed top-level callee gives no one-hop evidence (#420, row 93, D-191).

    `format_invoice` calls `compute_total`, whose body changed, so SPEC §5
    clause 2's own example should hold the honest test update at warn; the
    one-hop index keeps the `module::` prefix of a top-level symbol and never
    matches it, so this blocks, a known false block. #420 was closed as not
    planned and deferred until after 1.0 (#504): a fix of #420 changes this
    expectation, as a recorded change.
    """
    test = b"from billing import format_invoice\n\n\ndef test_fmt():\n    assert format_invoice([1.0]) == 1.0\n"
    billing = (b"def format_invoice(items):\n    return compute_total(items)\n\n\n"
               b"def compute_total(items):\n    return sum(items)\n")
    changes = [FileChange(TEST, "modified", test, test.replace(b"== 1.0", b"> 0")),
               FileChange("billing.py", "modified", billing, billing.replace(b"return sum(items)", b"return sum(items) + 0"))]
    assert one(changes, "ASSERT_WEAKENED") == ("high", [], ["PROD_CHANGE_NOT_EVIDENCE"], "block")


def _caller_changes(caller_path, calc_path):
    """A weakened test through `format_invoice` in `caller_path`, beside `+ 0` in `Calc.total` in `calc_path`."""
    test = (f"from {caller_path[:-3].replace('/', '.')} import format_invoice\n\n\n"
            "def test_fmt():\n    assert format_invoice([1.0]) == 1.0\n").encode()
    caller = (f"from {calc_path[:-3].replace('/', '.')} import Calc\n\n\n"
              "def format_invoice(items):\n    c = Calc()\n    return c.total(items)\n").encode()
    calc = b"class Calc:\n    def total(self, items):\n        return sum(items)\n"
    return [FileChange(TEST, "modified", test, test.replace(b"== 1.0", b"> 0")),
            # A comment, so the caller's file is a changed production file.
            FileChange(caller_path, "modified", caller, b"# note\n" + caller),
            FileChange(calc_path, "modified", calc, calc.replace(b"return sum(items)", b"return sum(items) + 0"))]


def test_residual_row93_one_hop_reads_callers_in_path_order():
    """A caller counts only for changes in its own file or an earlier path (row 93, D-191).

    The changed files are read in path order, and each file's callers are
    matched against the symbols changed so far, so a caller in
    `app/a_caller.py` gets no hop for a method changed in `app/z_calc.py`
    and the honest test update blocks; with the two paths swapped it is held
    at warn. A fix of the path order changes this expectation, as a recorded
    change.
    """
    assert one(_caller_changes("app/a_caller.py", "app/z_calc.py"), "ASSERT_WEAKENED") == (
        "high", [], ["PROD_CHANGE_NOT_EVIDENCE"], "block")
    assert one(_caller_changes("app/z_caller.py", "app/a_calc.py"), "ASSERT_WEAKENED") == HELD


def test_residual_row93_a_call_on_a_call_result_gives_no_hop():
    """A call made on another call's result is recorded as the inner call alone (row 93, D-191).

    `Calc().total(items)` is recorded as a call of `Calc`, so the changed
    `Calc.total` gives `format_invoice` no hop and the honest test update
    blocks; through a bound name, `c = Calc()` then `c.total(items)`, it is
    held at warn. A fix of the call reading changes this expectation, as a
    recorded change.
    """
    test = b"from billing import format_invoice\n\n\ndef test_fmt():\n    assert format_invoice([1.0]) == 1.0\n"
    calc = b"class Calc:\n    def total(self, items):\n        return sum(items)\n\n\ndef format_invoice(items):\n"

    def changes(body):
        billing = calc + body
        return [FileChange(TEST, "modified", test, test.replace(b"== 1.0", b"> 0")),
                FileChange("billing.py", "modified", billing,
                           billing.replace(b"return sum(items)", b"return sum(items) + 0"))]

    chained = b"    return Calc().total(items)\n"
    assert parse_python(calc + chained, collect_tests=False).symbol_calls["format_invoice"] == ("Calc",)
    assert one(changes(chained), "ASSERT_WEAKENED") == ("high", [], ["PROD_CHANGE_NOT_EVIDENCE"], "block")
    assert one(changes(b"    c = Calc()\n    return c.total(items)\n"), "ASSERT_WEAKENED") == HELD


def test_route_a_reaches_a_production_symbol_a_same_file_helper_calls():
    # T1.9: the kept edit sits in the production function the test's helper
    # calls. The helper is test code, so `+ 0` inside it is a test edit and
    # no repair evidence.
    before = (b"from billing import compute_invoice_total\n\n\n"
              b"def _total():\n    return compute_invoice_total([10.5, 94.8])\n\n\n"
              b"def test_invoice_total():\n    assert _total() == 105.3\n")
    weak = before.replace(b"assert _total() == 105.3", b"assert _total() > 0")
    assert one([FileChange(TEST, "modified", before, weak), noop("plus_zero")], "ASSERT_WEAKENED") == HELD
    in_helper = weak.replace(b"return compute_invoice_total([10.5, 94.8])",
                             b"return compute_invoice_total([10.5, 94.8]) + 0")
    assert one([FileChange(TEST, "modified", before, in_helper)], "ASSERT_WEAKENED") == (
        "high", [], ["NO_PROD_CHANGE_IN_DIFF"], "block")


def test_a_finding_with_no_unit_takes_route_b_only():
    """Route A needs a finding with a test unit; one with none takes Route B only (D-191).

    `CONFTEST_PATCHES_PROD` has no unit, so a kept no-op in the very function
    the conftest patches is no evidence for it and it blocks, while a
    template edit holds it at warn (row 130).
    """
    production = b"def total():\n    return 0\n"
    before = b"import pytest\nimport pricing\n"
    patched = before + (b"\n\n@pytest.fixture(autouse=True)\ndef fix(monkeypatch):\n"
                        b"    monkeypatch.setattr(pricing, \"total\", lambda: 5)\n")
    conftest = FileChange("tests/conftest.py", "modified", before, patched)
    plus_zero = FileChange("pricing.py", "modified", production, production.replace(b"return 0", b"return 0 + 0"))

    def judged(production_change):
        _ir, findings, verdict = analyze([conftest, production_change], Config(), Contract(), [], TODAY,
                                         root_reader={"pricing.py": production}.get)
        hit, = [f for f in findings if f.rule == "CONFTEST_PATCHES_PROD"]
        return hit.unit, hit.severity, hit.deescalators, hit.escalators, verdict

    assert judged(plus_zero) == (None, "high", [], ["PROD_CHANGE_NOT_EVIDENCE"], "block")
    assert judged(TEMPLATE) == (None, *HELD)


# --- the broad except: D-176 refuses Route B, and Route A never reaches it ---------------------------

BROAD = BEFORE.replace(b"    assert total == 105.3\n",
                       b"    try:\n        assert total == 105.3\n    except AssertionError:\n        pass\n")


@pytest.mark.parametrize("production,label", [
    (TEMPLATE, "OPAQUE_PROD_CHANGE_NOT_EVIDENCE"),
    (CHEAP[0], "OPAQUE_PROD_CHANGE_NOT_EVIDENCE"),
    (noop("plus_zero"), "PROD_CHANGE_NOT_EVIDENCE"),
], ids=["template", "AUTHORS", "plus_zero"])
def test_a_python_broad_except_blocks_beside_any_production_change(production, label):
    # The detector gives the finding no unit, so no symbol route reaches it,
    # and D-176 refuses it opaque-change evidence. This handler binds no
    # name, so it is no failure relay (D-190).
    swallowed = FileChange(TEST, "modified", BEFORE, BROAD)
    assert one([swallowed, production], "BROAD_EXCEPT_ADDED") == ("high", [], [label], "block")


RELAY = b'''

async def test_callback_total():
    fut = asyncio.Future()

    def cb():
        try:
            assert compute_invoice_total([1.0]) == 1.0
        except Exception as e:
            fut.set_exception(e)
        else:
            fut.set_result(None)

    asyncio.get_running_loop().call_soon(cb)
    await fut
'''


def test_a_proven_failure_relay_is_not_reported_beside_a_production_change():
    # The exception to the sentence above: a proven relay is not an added
    # swallow (D-190), so there is nothing to refuse evidence to.
    relayed = FileChange(TEST, "modified", BEFORE, b"import asyncio\n" + BEFORE + RELAY)
    _ir, findings, verdict = run([relayed, TEMPLATE])
    assert [f for f in findings if f.rule == "BROAD_EXCEPT_ADDED"] == [] and verdict == "pass"
    unrelayed = b"import asyncio\n" + BEFORE + RELAY.replace(b"    await fut\n", b"")
    assert one([FileChange(TEST, "modified", BEFORE, unrelayed), TEMPLATE], "BROAD_EXCEPT_ADDED") == (
        "high", [], ["OPAQUE_PROD_CHANGE_NOT_EVIDENCE"], "block")


# --- JS/TS keeps Route B (row 131) --------------------------------------------------------------------

JS_TEST = "tests/invoice.test.js"
JS = b'const { total } = require("../src/invoice");\n\ntest("applies tax", () => {\n  expect(total([50, 50], 0.05)).toBe(105);\n});\n'
JS_WEAKENINGS = {
    "ASSERT_WEAKENED": JS.replace(b".toBe(105)", b".toBeTruthy()"),
    "TEST_DISABLED": JS.replace(b'test("applies tax"', b'test.skip("applies tax"'),
    "ASSERT_REMOVED": JS.replace(b"  expect(total([50, 50], 0.05)).toBe(105);\n", b"  total([50, 50], 0.05);\n"),
    "BROAD_EXCEPT_ADDED": JS.replace(b"  expect(total([50, 50], 0.05)).toBe(105);\n",
                                     b"  try {\n    expect(total([50, 50], 0.05)).toBe(105);\n  } catch (e) {}\n"),
}
JS_MODULE = FileChange("src/invoice.js", "modified", b"exports.total = (xs, t) => 1;\n",
                       b"// c\nexports.total = (xs, t) => 1;\n")


@pytest.mark.parametrize("opaque", [TEMPLATE, JS_MODULE], ids=["template", "js_module"])
@pytest.mark.parametrize("rule", list(JS_WEAKENINGS))
def test_js_ts_tests_keep_route_b(rule, opaque):
    # The broad catch included: D-176's refusal needs a Python file.
    change = FileChange(JS_TEST, "modified", JS, JS_WEAKENINGS[rule])
    assert one([change, opaque], rule) == HELD


@pytest.mark.parametrize("rule", list(JS_WEAKENINGS))
def test_js_ts_tests_without_production_block(rule):
    change = FileChange(JS_TEST, "modified", JS, JS_WEAKENINGS[rule])
    assert one([change], rule) == ("high", [], ["NO_PROD_CHANGE_IN_DIFF"], "block")


# --- conftest suite controls ------------------------------------------------------------------------

CONFTEST = "tests/conftest.py"


def test_an_unguarded_suite_control_refuses_route_b():
    unguarded = FileChange(CONFTEST, "modified", b"import os\n",
                           b'import os\n\ncollect_ignore = ["test_billing.py"]\n')
    assert one([unguarded, TEMPLATE], "TEST_DISABLED") == ("high", [], ["COLLECTION_CONTROL_UNEXPLAINED"], "block")


def test_an_except_guarded_suite_control_takes_route_b():
    # A guard D6 cannot read earns no COMPAT_GATE, and the control is not
    # unguarded either, so Route B holds it at warn; alone it blocks.
    guarded = FileChange(CONFTEST, "modified", b"import os\n", (
        b'import os\n\ncollect_ignore = []\ntry:\n    os.environ["FULL"]\n'
        b'except KeyError:\n    collect_ignore.append("test_billing.py")\n'))
    assert one([guarded, TEMPLATE], "TEST_DISABLED") == HELD
    assert one([guarded], "TEST_DISABLED") == ("high", [], ["NO_PROD_CHANGE_IN_DIFF"], "block")


def test_an_if_guarded_suite_control_is_held_with_or_without_production():
    # A guard that can be false earns D6's COMPAT_GATE, which is no #419
    # route; beside an opaque edit, REPAIR_EVIDENCE holds it first.
    guarded = FileChange(CONFTEST, "modified", b"import os\nimport sys\n", (
        b'import os\nimport sys\n\ncollect_ignore = []\nif sys.platform == "win32":\n'
        b'    collect_ignore.append("test_billing.py")\n'))
    compat = ("warn", ["COMPAT_GATE"], [], "pass")
    assert one([guarded], "TEST_DISABLED") == compat
    assert one([guarded, noop("plus_zero")], "TEST_DISABLED") == compat
    assert one([guarded, TEMPLATE], "TEST_DISABLED") == HELD


# --- what blocks both routes ------------------------------------------------------------------------

ROUTES = {"route_a": noop("plus_zero"), "route_b": TEMPLATE}


@pytest.mark.parametrize("route", list(ROUTES))
@pytest.mark.parametrize("rule", RULES)
def test_fail_on_warn_blocks_both_routes(rule, route):
    assert one([weakened(rule), ROUTES[route]], rule, config=Config(fail_on="warn")) == (
        "warn", ["REPAIR_EVIDENCE"], [], "block")


@pytest.mark.parametrize("route", list(ROUTES))
@pytest.mark.parametrize("rule", RULES)
def test_oracle_freeze_blocks_both_routes(rule, route):
    # E2 sets high after the evidence holds the finding at warn.
    freeze = Contract(present=True, oracle_freeze=True)
    assert one([weakened(rule), ROUTES[route]], rule, contract=freeze) == (
        "high", ["REPAIR_EVIDENCE"], ["ORACLE_FREEZE"], "block")


# --- D-191: five BROAD_EXCEPT_ADDED routes that 0.10 already misses (THREATMODEL rows 172 to 176) -----
#
# D-190's security review found the first four, and Claude the fifth while
# checking a Gemini 4 Argon review of D-190. Each passes on main 6a867f6d
# as on D-190's commit: they are older than the relay reading. Each is pinned
# plain and under `oracle_freeze`, so neither the Stop hook nor the
# PreToolUse ask nor a CI freeze reports it. No engine change in D-191.

SWALLOWS = (b"from billing import compute\n\n\n"
            b"def test_a():\n    try:\n        assert compute() == 1\n    except Exception:\n        pass\n\n\n"
            b"def test_b():\n    assert compute() == 2\n")
B_SWALLOWED = SWALLOWS.replace(
    b"def test_b():\n    assert compute() == 2\n",
    b"def test_b():\n    try:\n        assert compute() == 2\n    except Exception:\n        pass\n")
PLAIN = b"from billing import compute\n\n\ndef test_b():\n    assert compute() == 2\n"


def _unreported(before, after):
    """No finding and a pass, plain and under oracle_freeze."""
    change = [FileChange(TEST, "modified", before, after)]
    for contract in (Contract(), Contract(present=True, oracle_freeze=True)):
        _ir, findings, verdict = run(change, contract=contract)
        assert (findings, verdict) == ([], "pass")


@pytest.mark.parametrize("released", [
    # A trailing `raise` makes the base handler re-raise, so it stops swallowing.
    B_SWALLOWED.replace(b"        pass\n\n\ndef test_b", b"        pass\n        raise\n\n\ndef test_b"),
    # Its assertion moved to the `else` clause, so its `try` guards no oracle.
    B_SWALLOWED.replace(b"    try:\n        assert compute() == 1\n    except Exception:\n        pass\n",
                        b"    try:\n        value = compute()\n    except Exception:\n        pass\n"
                        b"    else:\n        assert value == 1\n"),
], ids=["reraise", "assertion_to_else"])
def test_residual_row172_a_swallow_that_stops_counting_pays_for_a_new_one(released):
    """A base swallow that stops counting pays for a new one of the same first line (row 172, D-191).

    BROAD_EXCEPT_ADDED counts swallowing handlers per file and first line, as
    a multiset: `test_a`'s handler leaves the count while `test_b`'s new one
    joins it, so nothing is added, and `test_b`'s assertion is swallowed
    unreported. A fix changes this expectation, as a recorded change.
    """
    _unreported(SWALLOWS, released)
    # The same new swallow with the base handler left alone is reported.
    _ir, findings, verdict = run([FileChange(TEST, "modified", SWALLOWS, B_SWALLOWED)])
    assert [f.rule for f in findings] == ["BROAD_EXCEPT_ADDED"] and verdict == "block"


def test_residual_row173_an_alias_of_a_broad_exception_is_not_read_as_broad():
    """`except Err:` with `Err = Exception` is not read as a broad handler (row 173, D-191).

    The handler reading takes a caught type's last name, and `Err` is none of
    `Exception`, `BaseException` and `AssertionError`. A fix changes this
    expectation, as a recorded change.
    """
    aliased = PLAIN.replace(b"from billing import compute\n", b"from billing import compute\n\nErr = Exception\n")
    swallowed = aliased.replace(
        b"    assert compute() == 2\n", b"    try:\n        assert compute() == 2\n    except Err:\n        pass\n")
    _unreported(aliased, swallowed)
    assert parse_python(swallowed, collect_tests=True).broad_handlers == ()


def test_residual_row174_a_raise_in_a_nested_def_reads_as_a_reraise():
    """A broad handler whose only `raise` sits in a nested def reads as re-raising (row 174, D-191).

    The handler body is walked into nested scopes, so a `raise` in a def the
    handler only defines makes it inspection, not a swallow. A fix changes
    this expectation, as a recorded change.
    """
    nested = PLAIN.replace(b"    assert compute() == 2\n", (
        b"    try:\n        assert compute() == 2\n    except Exception:\n"
        b"        def _unused():\n            raise\n"))
    _unreported(PLAIN, nested)
    assert parse_python(nested, collect_tests=True).swallowing_handlers == ()


def test_residual_row175_a_non_broad_raise_before_the_assert_hides_it():
    """A statement that raises a caught non-broad exception before the assert hides it (row 175, D-191).

    `int('x')` raises `ValueError`, which the handler catches, so the
    assertion after it never runs; the handler is not broad, and the unit
    still lists the assertion as its own. A fix changes this expectation, as
    a recorded change.
    """
    hidden = PLAIN.replace(b"    assert compute() == 2\n", (
        b"    try:\n        int('x')\n        assert compute() == 2\n    except ValueError:\n        pass\n"))
    _unreported(PLAIN, hidden)
    unit, = parse_python(hidden, collect_tests=True).units
    assert [a.text for a in unit.side.assertions] == ["assert compute() == 2"]


NESTED_CHECK = PLAIN.replace(b"    assert compute() == 2\n", b"    def check():\n        assert compute() == 2\n\n    check()\n")
FIXTURE_CHECK = (b"import pytest\n\nfrom billing import compute\n\n\n@pytest.fixture\ndef assert_total():\n"
                 b"    def check(value):\n        assert value == 2\n    return check\n\n\n"
                 b"def test_b(assert_total):\n    assert_total(compute())\n")


@pytest.mark.parametrize("before, after", [
    (NESTED_CHECK, NESTED_CHECK.replace(b"    check()\n", b"    try:\n        check()\n    except Exception:\n        pass\n")),
    (FIXTURE_CHECK, FIXTURE_CHECK.replace(b"    assert_total(compute())\n", (
        b"    chk = assert_total\n    try:\n        chk(compute())\n    except Exception:\n        pass\n"))),
], ids=["nested_helper", "fixture_checker_alias"])
def test_residual_row176_a_broad_handler_around_an_asserting_call_is_not_a_swallow(before, after):
    """A broad handler around a call that asserts is no swallow (row 176, D-191).

    BROAD_EXCEPT_ADDED reads only the guarded block's own oracles: an
    `assert`, or a call named `assert...`, `fail` or `raises`. A call that
    reaches the assertion, here a nested helper and a fixture's checker
    through an alias, holds none, so the handler swallows it unreported. A
    fix changes this expectation, as a recorded change.
    """
    _unreported(before, after)
    assert parse_python(after, collect_tests=True).swallowing_handlers == ()

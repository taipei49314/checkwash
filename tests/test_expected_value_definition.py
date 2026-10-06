"""One definition of an expected value that is not a plain literal (#226).

A literal replaced by a call or a name passed in JavaScript and in part of
Python: `toBe(78.75)` -> `toBe(Number(75))` (#198 T6), `== float('75')`,
`== int('75')`, a call to a name the file never binds, and in JavaScript an
imported name. The rulings of 2026-10-03 and 226.Q1-Q3 give both frontends
one reading:

- a fixed set of conversions of one literal folds to its value and is a
  literal: Python's `float` and `Decimal` (`decimal.Decimal`), JavaScript's
  `Number`. Python literals compare as `==` does (226.Q2);
- a literal replaced by a call checkwash neither folds nor resolves, or one
  such call rewritten into another, is EXPECTED_VALUE_CHANGED "expected value
  replaced by an expression checkwash does not evaluate" (226.Q1, Q3);
- a literal replaced by a name or call the file binds is the provenance
  channel's EXPECTATION_DEFINITION_CHANGED, which JavaScript now has too.
"""

import ast
import datetime
import functools
import math
from decimal import Decimal

import pytest

from checkwash.cases import case_snapshot, case_to_changes, parse_case
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.frontends.javascript import expected_provenance as js_provenance
from checkwash.frontends.javascript.frontend import file_bindings, parse_javascript
from checkwash.frontends.javascript.literals import operand_callee
from checkwash.frontends.python.frontend import parse_python
from checkwash.frontends.python.literal_conversions import (
    conversion_names,
    folded_conversion,
    module_bindings,
    unbound_callee,
)
from checkwash.gitio.snapshot import search_source_mapping
from checkwash.ir.expected_values import literal_value, same_value, value_key

BLOCK, PASS = "block", "pass"
EVC, EDC = "EXPECTED_VALUE_CHANGED", "EXPECTATION_DEFINITION_CHANGED"
UNEVALUATED = "expected value replaced by an expression checkwash does not evaluate"
PROVENANCE = "expected provenance changed"

# The issue's setup: `app.billing.total()` returns 78.75, and the head tree's
# `app/__init__.py` defines OTHER and make(n); the JS module exports the same.
HEAD = ("=== head: app/__init__.py ===\nOTHER = 75\n\n\ndef make(n):\n    return 75 + n\n"
        "=== head: app/billing.py ===\ndef total():\n    return 78.75\n")
JS_HEAD = ("=== head: src/total.ts ===\nexport const total = () => 78.75;\nexport const OTHER = 75;\n"
           "export const make = (n: number) => 75 + n;\n")
MAKE = "\n\ndef make(n):\n    return 75 + n\n"


def _py(line, imports="", module=""):
    return f"{imports}from app.billing import total\n{module}\n\ndef test_total():\n    {line}\n"


def _unittest(line):
    return ("import unittest\n\nfrom app.billing import total\n\n\nclass TestTotal(unittest.TestCase):\n"
            f"    def test_total(self):\n        {line}\n")


def _js(line, prelude="", imports="total, OTHER, make"):
    return (f'import {{ test, expect }} from "vitest";\nimport {{ {imports} }} from "./total";\n{prelude}'
            f'test("total", () => {{\n  {line}\n}});\n')


@functools.lru_cache(maxsize=None)
def _outcome(before, after):
    """The verdict and findings, run as `tests/test_cases_runner.py` runs a fixture."""
    js = before.startswith("import { test")
    path = "src/total.test.ts" if js else "tests/test_billing.py"
    case = parse_case("=== meta ===\ntitle: #226\n" + (JS_HEAD if js else HEAD)
                      + f"=== before: {path} ===\n{before}=== after: {path} ===\n{after}=== expect ===\n[]\n")
    head = {p: c.encode("utf-8") for p, c in case.head.items()}
    snapshot = case_snapshot(case)
    _ir, findings, verdict = analyze(
        case_to_changes(case), Config(), Contract(), [], datetime.date(2026, 1, 1),
        head_reader=head.get,
        head_searcher=lambda needles: [p for p, data in sorted(head.items())
                                       if any(n.encode("utf-8") in data for n in needles)],
        root_reader=snapshot.get,
        root_searcher=lambda needles: search_source_mapping(snapshot, needles),
    )
    return verdict, tuple((f.rule, f.severity, f.message) for f in findings if not f.allowlisted)


def _check(outcome, verdict, rule=None, message=None):
    observed, findings = outcome
    assert observed == verdict, findings
    if rule is None:
        assert findings == ()
    else:
        assert [(r, s) for r, s, _ in findings] == [(rule, "high")], findings
        assert message in findings[0][2], findings


A = "assert total() == {}"
E = "expect(total()).toBe({});"


# --- The issue's table, and the rows around it ----------------------------------------------

@pytest.mark.parametrize("before,after,verdict,rule,message", [
    # P0 and J0: a literal rewritten, as before.
    (_py(A.format("78.75")), _py(A.format("75")), BLOCK, EVC, "expected value rewritten 78.75 -> 75 "),
    (_js(E.format("78.75")), _js(E.format("75")), BLOCK, EVC, "expected value rewritten 78.75 -> 75.0 "),
    # P1, J1, J2, P11: a conversion folds to its value.
    (_py(A.format("78.75")), _py(A.format("float('75')")), BLOCK, EVC, "expected value rewritten 78.75 -> 75.0 "),
    (_js(E.format("78.75")), _js(E.format("Number(75)")), BLOCK, EVC, "expected value rewritten 78.75 -> 75.0 "),
    (_js(E.format("78.75")), _js(E.format("Number('75')")), BLOCK, EVC, "expected value rewritten 78.75 -> 75.0 "),
    (_py(A.format("78.75"), "from decimal import Decimal\n"), _py(A.format("Decimal('75')"), "from decimal import Decimal\n"),
     BLOCK, EVC, "expected value rewritten 78.75 -> Decimal('75') "),
    # P12, P13, J8: an honest fold is no change.
    (_py(A.format("78.75"), "from decimal import Decimal\n"), _py(A.format("Decimal('78.75')"), "from decimal import Decimal\n"),
     PASS, None, None),
    (_py(A.format("78.75")), _py(A.format("float('78.75')")), PASS, None, None),
    (_js(E.format("78.75")), _js(E.format("Number('78.75')")), PASS, None, None),
    # P2, P3, P4: a call checkwash neither folds nor resolves (226.Q1).
    (_py(A.format("78.75")), _py(A.format("int('75')")), BLOCK, EVC, f"{UNEVALUATED} (78.75 -> int('75')) "),
    (_py(A.format("78.75")), _py(A.format("round(75.0, 2)")), BLOCK, EVC, f"{UNEVALUATED} (78.75 -> round(75.0, 2)) "),
    (_py(A.format("78.75")), _py(A.format("make(1)")), BLOCK, EVC, f"{UNEVALUATED} (78.75 -> make(1)) "),
    # P5: the same callee, never bound, with another argument (226.Q3).
    (_py(A.format("make(1)")), _py(A.format("make(2)")), BLOCK, EVC, f"{UNEVALUATED} (make(1) -> make(2)) "),
    # The JS counterparts: a global outside the fold set, a name no scope declares.
    (_js(E.format("78.75")), _js(E.format("parseFloat('75')")), BLOCK, EVC, f"{UNEVALUATED} (78.75 -> parseFloat('75')) "),
    (_js(E.format("78.75")), _js(E.format("build(1)")), BLOCK, EVC, f"{UNEVALUATED} (78.75 -> build(1)) "),
    (_js(E.format("build(1)")), _js(E.format("build(2)")), BLOCK, EVC, f"{UNEVALUATED} (build(1) -> build(2)) "),
    # P6-P10, P14: a name or call the file binds keeps the provenance channel.
    (_py(A.format("78.75"), "from app import OTHER\n"), _py(A.format("OTHER"), "from app import OTHER\n"),
     BLOCK, EDC, f"{PROVENANCE} 78.75 -> app.OTHER "),
    (_py(A.format("78.75"), "from app import make\n"), _py(A.format("make(1)"), "from app import make\n"),
     BLOCK, EDC, f"{PROVENANCE} 78.75 -> app.make(1) "),
    (_py(A.format("make(1)"), "from app import make\n"), _py(A.format("make(2)"), "from app import make\n"),
     BLOCK, EDC, f"{PROVENANCE} app.make(1) -> app.make(2) "),
    (_py(A.format("78.75"), "", MAKE), _py(A.format("make(1)"), "", MAKE), BLOCK, EDC, f"{PROVENANCE} 78.75 -> 76 "),
    (_py(A.format("make(1)"), "", MAKE), _py(A.format("make(2)"), "", MAKE), BLOCK, EDC, f"{PROVENANCE} 76 -> 77 "),
    (_py(A.format("78.75")), _py(A.format("EXPECTED_TOTAL"), "", "\nEXPECTED_TOTAL = 75\n"),
     BLOCK, EDC, f"{PROVENANCE} 78.75 -> 75 "),
    # P15: the honest extract.
    (_py(A.format("78.75")), _py(A.format("EXPECTED_TOTAL"), "", "\nEXPECTED_TOTAL = 78.75\n"), PASS, None, None),
    # J3-J6: the JavaScript port of the channel (226.Q1, Q3).
    (_js(E.format("78.75")), _js(E.format("make(1)")), BLOCK, EDC, f"{PROVENANCE} 78.75 -> ./total.make(1) "),
    (_js(E.format("78.75")), _js(E.format("OTHER")), BLOCK, EDC, f"{PROVENANCE} 78.75 -> ./total.OTHER "),
    (_js(E.format("make(1)")), _js(E.format("make(2)")), BLOCK, EDC, f"{PROVENANCE} ./total.make(1) -> ./total.make(2) "),
    (_js(E.format("78.75")), _js(E.format("EXPECTED_TOTAL"), "const EXPECTED_TOTAL = 75;\n"),
     BLOCK, EDC, f"{PROVENANCE} 78.75 -> 75.0 "),
    # J7: the honest extract.
    (_js(E.format("78.75")), _js(E.format("EXPECTED_TOTAL"), "const EXPECTED_TOTAL = 78.75;\n"), PASS, None, None),
])
def test_the_issue_rows(before, after, verdict, rule, message):
    _check(_outcome(before, after), verdict, rule, message)


@pytest.mark.parametrize("before,after,verdict,rule,message", [
    # 226.Q2: a folded value compares as Python's == does.
    (_py(A.format("0.1"), "from decimal import Decimal\n"), _py(A.format("Decimal('0.1')"), "from decimal import Decimal\n"),
     BLOCK, EVC, "expected value rewritten 0.1 -> Decimal('0.1') "),
    (_py(A.format("1")), _py(A.format("1.0")), PASS, None, None),
    (_py(A.format("1")), _py(A.format("True")), PASS, None, None),
    (_py(A.format("(1, 2)")), _py(A.format("[1, 2]")), BLOCK, EVC, "expected value rewritten (1, 2) -> [1, 2] "),
    # Every spelling of decimal.Decimal folds; a bound conversion folds too.
    (_py(A.format("78.75"), "import decimal\n"), _py(A.format("decimal.Decimal('75')"), "import decimal\n"),
     BLOCK, EVC, "78.75 -> Decimal('75') "),
    (_py(A.format("78.75"), "from decimal import Decimal as D\n"), _py(A.format("D('75')"), "from decimal import Decimal as D\n"),
     BLOCK, EVC, "78.75 -> Decimal('75') "),
    (_py("assert total() < 80"), _py("assert total() < float('80')"), PASS, None, None),
    # A bound tightened into the exact value it admits, as `== 78.75` is.
    (_py("assert total() < 80"), _py("assert total() == float('78.75')"), PASS, None, None),
    (_py("assert total() < 80"), _py("assert total() == float('81')"), BLOCK, EVC, "80 -> 81.0 "),
    (_py(A.format("78.75")), _py(A.format("float('inf')")), BLOCK, EVC, "78.75 -> inf "),
    # A name the module binds is no builtin: `float` imported from numpy is
    # the provenance channel's, and a parameter called float anywhere keeps
    # it from folding or reading as unbound.
    (_py(A.format("78.75"), "from numpy import float64 as float\n"),
     _py(A.format("float('75')"), "from numpy import float64 as float\n"), BLOCK, EDC, "78.75 -> numpy.float64('75') "),
    (_py(A.format("78.75"), "", "\n\ndef helper(float):\n    return float\n"),
     _py(A.format("float('75')"), "", "\n\ndef helper(float):\n    return float\n"), PASS, None, None),
    # A star import may bind any name.
    (_py(A.format("78.75"), "from app import *\n"), _py(A.format("make(1)"), "from app import *\n"), PASS, None, None),
    # unittest and pytest.approx read the same expected value.
    (_unittest("self.assertEqual(total(), 78.75)"), _unittest("self.assertEqual(total(), int('75'))"),
     BLOCK, EVC, f"{UNEVALUATED} (78.75 -> int('75')) "),
    (_unittest("self.assertEqual(total(), 78.75)"), _unittest("self.assertEqual(total(), float('75'))"),
     BLOCK, EVC, "expected value rewritten 78.75 -> 75.0 "),
    (_py("assert total() == pytest.approx(78.75)", "import pytest\n"),
     _py("assert total() == pytest.approx(float('75'))", "import pytest\n"), BLOCK, EVC, "78.75 -> 75.0 "),
    # A bound is an expected value too.
    (_py("assert total() < 80"), _py("assert total() < int('80')"), BLOCK, EVC, f"{UNEVALUATED} (80 -> int('80')) "),
    # A call respelled is the same call; another argument is another call.
    (_py(A.format("int('75')")), _py(A.format('int("75")')), PASS, None, None),
    (_py(A.format("int('75')")), _py(A.format("int('76')")), BLOCK, EVC, f"{UNEVALUATED} (int('75') -> int('76')) "),
    # An expression over the subject's own input stays EXPECTED_VALUE_DERIVED's.
    ("from app.billing import total\n\n\ndef test_total():\n    items = [1, 2]\n    assert total(items) == 3\n",
     "from app.billing import total\n\n\ndef test_total():\n    items = [1, 2]\n    assert total(items) == sum(items)\n",
     BLOCK, "EXPECTED_VALUE_DERIVED", "expected value 3 replaced by an expression computed from the subject's own input"),
    # JavaScript: a namespace import, a subject read through a local, a
    # declared function, a shadowed Number, a fold-set bound.
    ('import { test, expect } from "vitest";\nimport * as t from "./total";\n'
     'test("total", () => {\n  expect(t.total()).toBe(78.75);\n});\n',
     'import { test, expect } from "vitest";\nimport * as t from "./total";\n'
     'test("total", () => {\n  expect(t.total()).toBe(t.OTHER);\n});\n', BLOCK, EDC, f"{PROVENANCE} 78.75 -> ./total.OTHER "),
    (_js("const value = total();\n  expect(value).toBe(78.75);"), _js("const value = total();\n  expect(value).toBe(OTHER);"),
     BLOCK, EDC, "78.75 -> ./total.OTHER for the same subject/input ./total.total()"),
    (_js(E.format("78.75"), "function helper(n: number) { return 75 + n; }\n"),
     _js(E.format("helper(1)"), "function helper(n: number) { return 75 + n; }\n"), BLOCK, EDC, f"{PROVENANCE} 78.75 -> helper(1) "),
    (_js(E.format("78.75"), "const Number = (x: unknown) => 75;\n"),
     _js(E.format("Number('78.75')"), "const Number = (x: unknown) => 75;\n"), BLOCK, EDC, f"{PROVENANCE} 78.75 -> "),
    (_js("expect(total()).toBeLessThan(80);"), _js("expect(total()).toBeLessThan(Number('80'));"), PASS, None, None),
    (_js("const expected = 78.75;\n  expect(total()).toBe(expected);"), _js(E.format("78.75")), PASS, None, None),
    (_js(E.format("78.75")), _js("const expected = 75;\n  expect(total()).toBe(expected);"),
     BLOCK, EDC, f"{PROVENANCE} 78.75 -> 75.0 "),
    # JavaScript compares one canonical Number, not Python's ==.
    (_js("expect(total()).toBe(1);"), _js("expect(total()).toBe(true);"), BLOCK, EVC,
     "expected value rewritten 1.0 -> True "),
    # The port's subject must be one call after substitution, on both sides.
    (_js("let value;\n  value = total();\n  expect(value).toBe(78.75);"),
     _js("let value;\n  value = total();\n  expect(value).toBe(OTHER);"), PASS, None, None),
    (_js(E.format("78.75")), _js("expect(make(0)).toBe(OTHER);"), BLOCK, "ASSERT_SUBSTITUTED",
     "an assertion was replaced by an unrelated one"),
    # Python's channel folds what a local holds, and compares answers by ==.
    (_py(A.format("78.75")), _py("expected = float('75')\n    assert total() == expected"),
     BLOCK, EDC, f"{PROVENANCE} 78.75 -> 75.0 "),
    (_py(A.format("78.75")), _py("expected = float('78.75')\n    assert total() == expected"), PASS, None, None),
    (_py(A.format("78.75"), "from decimal import Decimal\n"),
     _py("expected = Decimal('78.75')\n    assert total() == expected", "from decimal import Decimal\n"),
     PASS, None, None),
    # Not decided by these rulings: a name or call replaced by a literal in JS (#292).
    (_js(E.format("parseFloat('75')")), _js(E.format("75")), PASS, None, None),
])
def test_rows_around_the_issue(before, after, verdict, rule, message):
    _check(_outcome(before, after), verdict, rule, message)


# --- What the frontends record --------------------------------------------------------------

def _python_assertion(source):
    parsed = parse_python(source.encode(), collect_tests=True)
    found = [a for unit in parsed.units for a in unit.side.assertions]
    assert len(found) == 1, found
    return found[0]


@pytest.mark.parametrize("source,right_value,unevaluated", [
    (_py(A.format("float('75')")), "75.0", None),
    (_py(A.format("float(' 1_000 ')")), "1000.0", None),
    (_py(A.format("float(-2)")), "-2.0", None),
    (_py(A.format("Decimal('75.10')"), "from decimal import Decimal\n"), "Decimal('75.10')", None),
    (_py(A.format("Decimal(-1)"), "from decimal import Decimal\n"), "Decimal('-1')", None),
    (_py(A.format("Decimal('sNaN')"), "from decimal import Decimal\n"), None, None),
    (_py(A.format("int('75')")), None, "int('75')"),
    (_py(A.format("float(x)")), None, "float(x)"),
    (_py(A.format("float('x')")), None, "float('x')"),
    (_py(A.format("float('75', 2)")), None, "float('75', 2)"),
    (_py(A.format("Decimal('75')")), None, "Decimal('75')"),
    (_py(A.format("json.loads('75')"), "import json\n"), None, None),
    (_py(A.format("make(1)"), "from app import make\n"), None, None),
    (_py(A.format("'a'.upper()")), None, None),
    (_unittest("self.assertTrue(total(), make_message())"), None, None),
    (_unittest("self.assertEqual(total(), round(75.4))"), None, "round(75.4)"),
    (_py("assert not total() == int('75')"), None, "int('75')"),
    (_py("assert total() in list_values()"), None, "list_values()"),
])
def test_python_records_a_fold_or_an_unevaluated_call(source, right_value, unevaluated):
    assertion = _python_assertion(source)
    assert (assertion.right_value, assertion.unevaluated_expected) == (right_value, unevaluated)


def _js_assertion(line, prelude="", header=None):
    source = _js(line, prelude) if header is None else f'{header}test("total", () => {{\n  {line}\n}});\n'
    parsed = parse_javascript(source.encode())
    found = [a for unit in parsed.units for a in unit.side.assertions]
    assert len(found) == 1, found
    return found[0]


# Jest's globals: no import declares expect.
JEST = 'import { total } from "./total";\n'


@pytest.mark.parametrize("line,prelude,right_value,unevaluated", [
    (E.format("Number(75)"), "", "75.0", None),
    (E.format("Number('-7.5e1')"), "", "-75.0", None),
    (E.format("Number('.5')"), "", "0.5", None),
    (E.format("Number((75))"), "", "75.0", None),
    (E.format("Number('0x10')"), "", None, "Number('0x10')"),
    (E.format("Number(' 75')"), "", None, "Number(' 75')"),
    (E.format("Number('1e999')"), "", None, "Number('1e999')"),
    (E.format("Number(75)"), "const Number = (x: unknown) => x;\n", None, None),
    (E.format("parseFloat('75')"), "", None, "parseFloat('75')"),
    (E.format("Math.round(75.4)"), "", None, "Math.round(75.4)"),
    (E.format("make(1)"), "", None, None),
    (E.format("helper(1)"), "function helper(n: number) { return n; }\n", None, None),
    (E.format("expect.any(Number)"), "", None, None),
    (E.format("new Date(0)"), "", None, None),
    ("expect(total()).toBeCloseTo(Number('78.75'), 2);", "", "78.75", None),
    ("expect(total()).toBeLessThan(Number(80));", "", "80.0", None),
])
def test_javascript_records_a_fold_or_an_unevaluated_call(line, prelude, right_value, unevaluated):
    assertion = _js_assertion(line, prelude)
    assert (assertion.right_value, assertion.unevaluated_expected) == (right_value, unevaluated)


@pytest.mark.parametrize("line,unevaluated", [
    # A global the assertion library defines is a matcher, not a value.
    ("expect(total()).toEqual(expect.stringContaining('a'));", None),
    ("expect(total()).toBe(parseInt('75'));", "parseInt('75')"),
])
def test_a_jest_global_matcher_is_not_an_unevaluated_call(line, unevaluated):
    assert _js_assertion(line, header=JEST).unevaluated_expected == unevaluated


# --- The pieces -----------------------------------------------------------------------------

@pytest.mark.parametrize("before,after,equal", [
    ("78.75", "Decimal('78.75')", True),
    ("0.1", "Decimal('0.1')", False),
    ("1", "1.0", True),
    ("1", "True", True),
    ("'1'", "1", False),
    ("(1, 2)", "[1, 2]", False),
    ("[1, 2]", "[1.0, 2.0]", True),
    ("inf", "inf", True),
    ("nan", "nan", True),  # the same text is the same answer
    ("Decimal('NaN')", "nan", False),
    ("x", "y", False),
    ("x", "x", True),
])
def test_python_literals_compare_as_equality_does(before, after, equal):
    assert same_value(before, after) is equal


def test_equal_python_literals_share_a_key():
    assert value_key("78.75") == value_key("Decimal('78.75')") == value_key("78.75")
    assert value_key("0.1") != value_key("Decimal('0.1')")
    assert value_key("nan") == ("text", "nan")
    assert value_key("[1]") == ("text", "[1]")
    # A signalling NaN cannot be compared; it is its text.
    assert value_key("Decimal('sNaN')") == ("text", "Decimal('sNaN')")
    assert not same_value("Decimal('sNaN')", "Decimal('NaN')")
    assert literal_value("Decimal('1E+3')") == Decimal(1000)
    assert math.isinf(literal_value("-inf"))


@pytest.mark.parametrize("source,names", [
    ("", {"float": "float"}),
    ("from decimal import Decimal\n", {"float": "float", "Decimal": "decimal.Decimal"}),
    ("from decimal import Decimal as D\n", {"float": "float", "D": "decimal.Decimal"}),
    ("import decimal\n", {"float": "float", "decimal.Decimal": "decimal.Decimal"}),
    ("import decimal as dec\n", {"float": "float", "dec.Decimal": "decimal.Decimal"}),
    # Bound anywhere else, in any scope, a name folds nothing.
    ("float = int\n", {}),
    ("def f(float):\n    return float\n", {}),
    ("class T:\n    float = 1.0\n", {}),
    ("for float in []:\n    pass\n", {}),
    ("from decimal import Decimal\n\ndef f():\n    Decimal = 1\n", {"float": "float"}),
    ("import decimal\ndecimal = None\n", {"float": "float"}),
    ("def f():\n    from decimal import Decimal\n", {"float": "float"}),
    ("from numpy import *\nfrom decimal import Decimal\n", {}),
])
def test_a_conversion_folds_only_where_its_name_can_be_nothing_else(source, names):
    tree = ast.parse(source)
    assert conversion_names(tree, module_bindings(tree)) == names


@pytest.mark.parametrize("call,value", [
    ("float('75')", 75.0),
    ("float(75)", 75.0),
    ("float(-75)", -75.0),
    ("Decimal('75')", Decimal("75")),
    ("Decimal(78.75)", Decimal("78.75")),
    ("float(True)", None),
    ("float(x)", None),
    ("float('75', 1)", None),
    ("float(x='75')", None),
    ("float('75', x=1)", None),
    ("float('" + "7" * 129 + "')", None),
    ("float(" + "9" * 400 + ")", None),
    ("Decimal('abc')", None),
    ("Decimal('sNaN')", None),
    ("int('75')", None),
])
def test_the_fold_reads_one_bounded_literal(call, value):
    folded = folded_conversion(ast.parse(call, mode="eval").body, {"float": "float", "Decimal": "decimal.Decimal"})
    assert folded == value and type(folded) is type(value)


@pytest.mark.parametrize("source,call,unbound", [
    ("", "int('75')", True),
    ("", "make(1)", True),
    ("", "a.b.c(1)", True),
    ("from app import make\n", "make(1)", False),
    ("import json\n", "json.loads('1')", False),
    ("def f(make):\n    pass\n", "make(1)", False),
    ("from app import *\n", "make(1)", False),
    ("", "'a'.upper()", False),
    ("", "f()(1)", False),
    ("", "x", False),
])
def test_an_unbound_callee_is_a_name_the_module_never_binds(source, call, unbound):
    tree = ast.parse(source)
    assert unbound_callee(ast.parse(call, mode="eval").body, module_bindings(tree)) is unbound


@pytest.mark.parametrize("operand,callee", [
    ("make(1)", "make"),
    ("Math.round(1)", "Math.round"),
    ("a . b (1)", "a.b"),
    ("make(1) + 1", None),
    ("make(1)(2)", None),
    ("new Date(0)", None),
    ("a?.b(1)", None),
    ("(make)(1)", None),
    ("make", None),
])
def test_a_js_operand_is_one_call_or_none(operand, callee):
    assert operand_callee(operand) == callee


JS_FILE = (
    'import { test, expect } from "vitest";\n'
    'import def, { OTHER, make as build } from "./total";\n'
    'import * as ns from "../ns";\n'
    'const A = OTHER;\n'
    'const B = A + 1;\n'
    'const T = `${A}`;\n'
    'function helper() { return 1; }\n'
    'test("x", (param) => {\n'
    '  const OTHER = 1;\n'
    '  expect(x).toBe(0);\n'
    '});\n'
    'test("y", () => {\n'
    '  expect(y).toBe(0);\n'
    '});\n'
)


@pytest.mark.parametrize("operand,where,resolved", [
    ("OTHER", "y", ("./total.OTHER", True)),
    ("build(1)", "y", ("./total.make(1)", True)),
    ("def", "y", ("./total.default", True)),
    ("ns.VALUE", "y", ("../ns.VALUE", True)),
    ("B * 2", "y", ("(./total.OTHER + 1) * 2", True)),
    ("helper()", "y", ("helper()", True)),
    ("param", "x", ("param", False)),
    ("OTHER", "x", ("1.0", True)),  # the local declaration shadows the import
    ("unknown", "y", ("unknown", False)),
    ("{ total: OTHER }", "y", ("{ total: ./total.OTHER }", True)),
    ("{ OTHER: 1 }", "y", ("{ OTHER: 1 }", False)),  # a key is no read
    ("`${A}`", "y", None),  # a template that interpolates is not read
    ("T", "y", ("T", False)),  # nor is a declaration it initializes
    ("Number('75')", "y", ("75.0", False)),
])
def test_the_js_port_substitutes_what_an_operand_reads(operand, where, resolved):
    bindings = file_bindings(JS_FILE.encode())
    position = JS_FILE.index(f"expect({where})")
    result = js_provenance.resolve(operand, bindings, position)
    assert (None if result is None else (result.text, result.indirect)) == resolved


def test_an_import_a_write_may_reach_is_unknown():
    source = ('import { W } from "./w";\nfunction reset() {\n  W = 1;\n}\n'
              'test("x", () => {\n  expect(x).toBe(W);\n});\n')
    result = js_provenance.resolve("W", file_bindings(source.encode()), source.index("expect("))
    assert (result.text, result.indirect) == ("W", False)

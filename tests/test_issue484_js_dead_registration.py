"""A JS/TS test registered where no code runs is no unit (#484).

`if (false) { it(...) }`, a `return;` before `it(...)` in a `describe`
callback, a module-level `if (false) { test(...) }`, `false && it(...)` and a
node:test `t.test(...)` after `return;` all kept their unit, so moving a test
there passed with zero findings. Ruling 484 (owner, 2026-10-18,
issuecomment-6248630321, 「19 項全部照建議」):

- Q1 (a): #429's walker also reads `describe`, `suite` and `context`
  callbacks, module scope (past its static imports) and a test callback that
  registers subtests; a declaration that starts in a span it proves dead is
  no unit, nor is any declaration inside it, and its skip, focus and options
  apply to nothing. Its loss is TEST_DISABLED "test unit disappeared" under
  the deletion's key; its assertions still reach the catch evidence and are
  recorded as unreachable spans. D-148 reading 7 (the module walk steps over
  a static `import`) and reading 10 (only a function declaration in a dead
  region refuses the walk) are amended (D-165).
- Q2: no new rule text; D2, D5 and D10 read a dead registration as absent.
- Q3: the `.gwcase` fixtures `js_dead_registration_*` and `js_registration_*`
  pin the shapes; these pin the unit-level readings.

Expectations are new labels; they run only in remote CI.
"""

from __future__ import annotations

import datetime

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze
from checkwash.frontends.javascript.coverage import javascript_coverage_gaps
from checkwash.frontends.javascript.exception_handlers import SWALLOWED
from checkwash.frontends.javascript.frontend import parse_javascript

HEADER = 'import { describe, expect, it, test } from "vitest";\nimport { total } from "../src/total";\n'
PATH = "tests/total.test.ts"
LIVE = 'it("live", () => {\n  expect(total([])).toBe(0);\n});\n'
PARKED = 'it("parked", () => {\n  expect(total([1, 2])).toBe(3);\n});\n'
SUBTEST = 't.test("parked", () => {\n  expect(total([1, 2])).toBe(3);\n});\n'
ORACLE = "expect(total([1, 2])).toBe(3)"


def source(module: str) -> bytes:
    return (HEADER + module).encode()


def names(module: str) -> list[str]:
    return [unit.qualname for unit in parse_javascript(source(module)).units]


def describe(body: str) -> str:
    return 'describe("total", () => {\n' + body + "});\n"


def outcome(before: str, after: str):
    _ir, findings, verdict = analyze([FileChange(PATH, "modified", source(before), source(after))],
                                     Config(), Contract(), [], datetime.date(2026, 10, 19))
    return verdict, findings


# --- Q1 (a): a declaration the walk proves dead is no unit ------------------------------------

@pytest.mark.parametrize("module", [
    "if (false) {\n" + PARKED + "}\n" + LIVE,
    LIVE + "if (0) " + PARKED,
    "while (false) {\n" + PARKED + "}\n" + LIVE,
    "for (; false; ) {\n" + PARKED + "}\n" + LIVE,
    "if (true) {\n" + LIVE + "} else {\n" + PARKED + "}\n",
    LIVE + "return;\n" + PARKED,
    LIVE + "throw new Error('off');\n" + PARKED,
    "false && " + PARKED + LIVE,
    describe("if (false) {\n" + PARKED + "}\n" + LIVE),
    describe(LIVE + "return;\n" + PARKED),
    describe(LIVE + "throw new Error('off');\n" + PARKED),
    describe("false && " + PARKED + LIVE),
    describe("true || " + PARKED + LIVE),
    describe("if (1 === 2) {\n" + PARKED + "}\n" + LIVE),
    'suite("total", () => {\nreturn;\n' + PARKED + "});\n" + LIVE,
    'describe.skip("total", () => {\nreturn;\n' + PARKED + "});\n" + LIVE,
    "if (false) {\n" + describe(PARKED + LIVE.replace('"live"', '"inner"')) + "}\n" + LIVE,
    describe("if (false) {\n" + describe(PARKED) + "}\n" + LIVE),
    'test("parent", async (t) => {\nreturn;\nawait ' + SUBTEST + "});\n" + LIVE,
    'test("parent", (t) => {\nfalse && ' + SUBTEST + "});\n" + LIVE,
])
def test_a_declaration_the_walk_proves_dead_is_no_unit(module):
    found = names(module)
    assert "parked" not in found and "inner" not in found
    assert "live" in found


@pytest.mark.parametrize("module", [
    describe("if (process.env.CI) {\n" + PARKED + "}\n" + LIVE),
    describe("const enabled = false;\nif (enabled) {\n" + PARKED + "}\n" + LIVE),
    describe("if (flag) {\n" + LIVE + "} else {\n" + PARKED + "}\n"),
    describe("if (true) {\n" + PARKED + "}\n" + LIVE),
    describe("if (false) {} else {\n" + PARKED + "}\n" + LIVE),
    describe("[1, 2].forEach(() => {\nreturn;\n});\n" + PARKED + LIVE),
    describe("const run = () => {\nreturn;\n};\n" + PARKED + LIVE),
    describe("for (const row of rows) {\nreturn;\n}\n" + PARKED + LIVE),
    describe("switch (mode) {\ndefault:\nreturn;\n}\n" + PARKED + LIVE),
    describe("const note = `a\nreturn;`\n" + PARKED + LIVE),
    describe("flag && " + PARKED + LIVE),
    describe("false || " + PARKED + LIVE),
    describe("const off = false && " + PARKED + LIVE),
    'test("parent", async (t) => {\nfalse && await ' + SUBTEST + "});\n" + LIVE,
])
def test_a_registration_the_walk_does_not_prove_dead_keeps_todays_reading(module):
    """Unknown conditions, iterator callbacks, loops, `switch`, unproved ends and other `&&` shapes (Q1)."""
    found = names(module)
    assert "parked" in found and "live" in found


def test_a_parked_test_inside_a_live_test_lends_it_nothing():
    """node:test: the parent keeps its own assertion; the subtest's is recorded once, as never reached."""
    parsed = parse_javascript(source(
        'test("parent", async (t) => {\n  expect(total([])).toBe(0);\n  return;\n  await ' + SUBTEST + "});\n"))
    parent, = parsed.units
    assert parent.qualname == "parent"
    assert [assertion.text for assertion in parent.side.assertions] == ["expect(total([])).toBe(0)"]
    assert len(parsed.unreachable_assertion_spans) == 1


def test_a_dead_only_stops_no_other_test():
    parsed = parse_javascript(source(describe(
        'if (false) {\nit.only("parked", () => {\n  expect(total([1, 2])).toBe(3);\n});\n}\n' + LIVE)),
        lambda: True)
    assert parsed.focus is None
    live, = parsed.units
    assert (live.qualname, live.side.markers) == ("live", [])


def test_a_file_whose_only_test_is_parked_still_declares_tests():
    """Not decided by the ruling; D-165 keeps today's reading, so E7's role reading does not move."""
    parsed = parse_javascript(source("if (false) {\n" + PARKED + "}\n"))
    assert parsed.units == []
    assert parsed.declares_tests is True


# --- What a parked unit keeps: catch evidence, coverage, identity -----------------------------

def test_the_catch_evidence_reads_a_parked_tests_assertions():
    """#363: the dead registration's catch still reports, as the live one does."""
    body = 'it("parked", () => {\n  try { ' + ORACLE + "; } catch {}\n});\n"
    dead = parse_javascript(source(describe("if (false) {\n" + body + "}\n" + LIVE)))
    live = parse_javascript(source(describe(body + LIVE)))
    assert [unit.qualname for unit in dead.units] == ["live"]
    assert dead.swallowing_handlers == live.swallowing_handlers == (SWALLOWED,)


def test_the_coverage_inventory_reads_a_parked_tests_assertions_as_read():
    data = source(describe("if (false) {\n"
                           'it("parked", () => {\n  ' + ORACLE + ";\n  expect(spy).toHaveBeenCalled();\n});\n"
                           "}\n" + LIVE))
    parsed = parse_javascript(data)
    text = data.decode()
    strong, = parsed.unreachable_assertion_spans
    unjudged, = parsed.unreachable_unjudged_assertion_spans
    assert text[slice(*strong)] == ORACLE
    assert text[slice(*unjudged)] == "expect(spy).toHaveBeenCalled()"
    gap, = javascript_coverage_gaps(data, parsed, PATH, "after")
    assert "recorded with no strength" in gap.reason


@pytest.mark.parametrize("after", [
    describe(LIVE + "if (false) {\n" + PARKED + "}\n"),
    describe(LIVE + "return;\n" + PARKED),
    describe(LIVE + "false && " + PARKED),
    describe(LIVE) + "if (false) {\n" + PARKED + "}\n",
])
def test_a_parked_test_is_reported_as_its_deletion_is_with_the_same_key(after):
    before = describe(LIVE + PARKED)
    verdict, findings = outcome(before, after)
    _verdict, deleted = outcome(before, describe(LIVE))
    assert verdict == "block"
    assert [(f.rule, f.severity, f.unit, f.message) for f in findings] == [
        ("TEST_DISABLED", "high", "parked", "parked: test unit disappeared")]
    assert [(f.message, f.fingerprint) for f in findings] == [(f.message, f.fingerprint) for f in deleted]


# --- D-148 reading 10, amended: only a function declaration refuses ---------------------------

@pytest.mark.parametrize("helper", [
    "function helper() {}",
    "async function helper() {}",
    "function* helper() {}",
    "skip: function helper() {}",
    "{ function helper() {} }",
    "if (flag) function helper() {}",
    "return\nfunction helper() {}",
    "const pick = { run: function run() {} };",
    "const note = `x`\nfunction helper() {}",
    "const step = 1.\nfunction helper() {}",
])
def test_a_dead_region_holding_a_function_declaration_still_refuses_the_walk(helper):
    """A call before the region may run a hoisted body. A named function after `:` reads as a label's.

    A template the tokens omit, or the `.` that ends `1.`, may end the statement before it.
    """
    assert "parked" in names(describe(LIVE + "return;\n" + PARKED + helper + "\n"))


@pytest.mark.parametrize("helper", [
    "skip: function check() {}",
    "function check() {}",
])
def test_a_cut_holding_a_function_declaration_labelled_or_not_is_refused(helper):
    parsed = parse_javascript(source(describe('it("parked", () => {\n  return;\n  ' + ORACLE + ";\n  "
                                              + helper + "\n});\n")))
    assert parsed.unreachable_assertion_spans == ()


@pytest.mark.parametrize("expression", [
    'it("x", function () {});',
    'it("x", async function named() {});',
    "const helper = function named() {};",
    "run(function named() {});",
    "[function named() {}];",
    "(function () {})();",
    "!function named() {}();",
    "return function named() {};",
    "exports.helper = function* named() {};",
])
def test_a_function_expression_in_a_dead_region_hoists_nothing(expression):
    assert "parked" not in names(describe(LIVE + "return;\n" + PARKED + expression + "\n"))
    cut = parse_javascript(source(describe('it("parked", () => {\n  return;\n  ' + ORACLE + ";\n  "
                                           + expression + "\n});\n")))
    assert len(cut.unreachable_assertion_spans) == 1


# --- D-148 reading 7, amended: the module walk steps over a static import --------------------

DEAD = "if (false) {\n" + PARKED + "}\n" + LIVE


@pytest.mark.parametrize("prelude", [
    'import "./setup";\n',
    'import * as lib from "../src/lib";\n',
    'import type { Total } from "../src/total";\n',
    'import fallback, { named as other } from "../src/other";\n',
    'import {\n  a,\n  b,\n} from "../src/letters";\n',
    'import { "a-b" as ab } from "../src/names";\n',
    'import { a } from "../src/letters"\n',
    'import { a } from "../src/letters" // the letters\n',
])
def test_the_module_walk_steps_over_a_static_import(prelude):
    assert "parked" not in names(prelude + DEAD)


@pytest.mark.parametrize("prelude", [
    "export const answer = 42;\n",
    'import data = require("../src/data");\n',
    'import data from "./data.json" with { type: "json" };\n',
    'import data from "./data.json"\nwith { type: "json" };\n',
    'import("../src/lazy");\n',
    "import.meta.url;\n",
    'import from from "../src/from";\n',
])
def test_export_and_other_imports_stop_the_module_walk(prelude):
    assert "parked" in names(prelude + DEAD)


def test_a_misreading_anywhere_refuses_the_module_walk_but_not_a_describe_before_it():
    """D-148's refusals cover the text from the file's start: one after a `describe` leaves its walk alone."""
    nested = "const s = `${`x`}`;\n"
    assert "parked" in names(DEAD + nested)
    assert "parked" not in names(describe("if (false) {\n" + PARKED + "}\n" + LIVE) + nested)

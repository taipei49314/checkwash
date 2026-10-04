"""Where a JS stand-in takes effect, for whom it is new, and what reads it (#196 188.1-188.4).

- 188.1: Vitest hoists `vi.mock` to the top of the file wherever it is
  written; `jest.mock` hoists only within its own block. Measured: Vitest
  3.2.7 and 4.1.11 apply a `vi.mock` written in a test, a describe body, a
  hook or a helper that never runs to every test in the file (4.1 warns),
  Vitest 5.0.3 refuses the file, and Jest 30.5.2 keeps the real module for a
  top-level `require` when `jest.mock` sits in a test, a describe body or a
  hook.
- 188.2: a stand-in is new for one unit unless the base side installed it at
  module level, in a hook, a describe body, a helper or that unit itself. An
  installation inside another test never ran for this one.
- 188.3: a namespace or `require()` object read whole names no export; a
  member of it does, and a named or default import does in any use.
- 188.4: `const spy = vi.spyOn(...)` then `spy.mockReturnValue(...)`, and the
  same for `vi.mocked`, `jest.spyOn` and node:test's `mock.method`, resolved
  through one hop of the local binding on either side.
"""

from __future__ import annotations

import datetime

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze
from checkwash.gitio.snapshot import search_source_mapping

PATH = "tests/billing.test.js"
TARGET = "src/billing:invoiceTotal"
VITEST = 'import { describe, it, expect, beforeEach, vi } from "vitest";\n'
NAMED = 'import { invoiceTotal } from "../src/billing.js";\n'
NAMESPACE = 'import * as billing from "../src/billing.js";\n'
ITEMS = "  const items = [{ price: 10.0, qty: 3 }, { price: 5.0, qty: 9 }];\n"
VI_MOCK = 'vi.mock("../src/billing.js", () => ({ invoiceTotal: () => 78.75 }));\n'
SPY = 'vi.spyOn(billing, "invoiceTotal").mockReturnValue(78.75);\n'


def _it(name: str, body: str) -> str:
    return f'it("{name}", () => {{\n{body}}});\n'


def _events(before: str, after: str, path: str = PATH):
    snapshot = {path: after.encode("utf-8")}
    change = FileChange(path, "modified", before.encode("utf-8"), after.encode("utf-8"))
    ir, _findings, _verdict = analyze(
        [change], Config(), Contract(), [], datetime.date(2026, 10, 3),
        root_reader=snapshot.get,
        root_searcher=lambda needles: search_source_mapping(snapshot, needles),
    )
    return [(unit, target) for _path, unit, target, _text, _span in ir.globals.subject_installations]


# --- 188.1: where vi.mock and jest.mock take effect -------------------------

READ = ITEMS + "  expect(invoiceTotal(items)).toBe(78.75);\n"
OTHER = _it("formats invoice", "  expect(1).toBe(1);\n")
VI_BEFORE = VITEST + NAMED + "\n" + _it("computes invoice total", READ) + OTHER


@pytest.mark.parametrize("after", [
    VITEST + NAMED + "\n" + _it("computes invoice total", "  " + VI_MOCK + READ) + OTHER,
    VITEST + NAMED + "\n" + _it("computes invoice total", READ) + _it("formats invoice", "  " + VI_MOCK + "  expect(1).toBe(1);\n"),
    VITEST + NAMED + "\n" + 'describe("billing", () => {\n  ' + VI_MOCK + _it("computes invoice total", READ) + "});\n" + OTHER,
    VITEST + NAMED + "\n" + "beforeEach(() => {\n  " + VI_MOCK + "});\n" + _it("computes invoice total", READ) + OTHER,
    VITEST + NAMED + "\n" + "function stubBilling() {\n  " + VI_MOCK + "}\n" + _it("computes invoice total", READ) + OTHER,
], ids=["in-the-test", "in-another-test", "in-a-describe-body", "in-a-hook", "in-a-helper-never-called"])
def test_vi_mock_takes_effect_for_the_whole_file_wherever_it_is_written(after):
    assert _events(VI_BEFORE, after) == [("computes invoice total", TARGET)]


def test_moving_vi_mock_from_module_level_into_a_test_installs_nothing_new():
    before = VITEST + VI_MOCK + NAMED + "\n" + _it("computes invoice total", READ) + OTHER
    after = VITEST + NAMED + "\n" + _it("computes invoice total", READ) + _it("formats invoice", "  " + VI_MOCK + "  expect(1).toBe(1);\n")
    assert _events(before, after) == []


JEST_REQUIRE = 'const { invoiceTotal } = require("../src/billing");\n'
JEST_MOCK = 'jest.mock("../src/billing", () => ({ invoiceTotal: () => 78.75 }));\n'
JEST_BEFORE = JEST_REQUIRE + "\n" + _it("computes invoice total", READ)


@pytest.mark.parametrize("after", [
    JEST_REQUIRE + "\n" + _it("computes invoice total", "  " + JEST_MOCK + READ),
    JEST_REQUIRE + "\n" + "beforeEach(() => {\n  " + JEST_MOCK + "});\n" + _it("computes invoice total", READ),
], ids=["in-the-test", "in-a-hook"])
def test_jest_mock_below_module_level_cannot_reach_a_captured_require(after):
    assert _events(JEST_BEFORE, after) == []


def test_jest_mock_at_module_level_still_reaches_it():
    assert _events(JEST_BEFORE, JEST_MOCK + JEST_BEFORE) == [("computes invoice total", TARGET)]


# --- 188.2: new for this unit -----------------------------------------------

NS_READ = ITEMS + "  expect(billing.invoiceTotal(items)).toBe(78.75);\n"
CHARGES = "  expect(billing.invoiceTotal([])).toBe(78.75);\n"


def _ns_file(top: str = "", subject_body: str = NS_READ, other_body: str = CHARGES, middle: str = "") -> str:
    return (VITEST + NAMESPACE + "\n" + top + _it("charges card", other_body)
            + middle + _it("computes invoice total", subject_body))


def test_a_stand_in_copied_from_another_test_is_new_for_this_one():
    # The base installation sat inside another test, so it never ran here.
    before = _ns_file(other_body="  " + SPY + CHARGES)
    after = _ns_file(other_body="  " + SPY + CHARGES, subject_body="  " + SPY + NS_READ)
    assert _events(before, after) == [("computes invoice total", TARGET)]


@pytest.mark.parametrize("before", [
    _ns_file(top=SPY),
    _ns_file(top="beforeEach(() => {\n  " + SPY + "});\n"),
    VITEST + NAMESPACE + '\ndescribe("billing", () => {\n  ' + SPY + _it("charges card", CHARGES)
    + _it("computes invoice total", NS_READ) + "});\n",
    _ns_file(top="function stubBilling() {\n  " + SPY + "}\n"),
    _ns_file(subject_body="  " + SPY.replace("78.75", "80") + NS_READ),
], ids=["module-level", "hook", "describe-body", "helper", "the-unit-itself"])
def test_a_stand_in_the_base_side_already_installed_for_this_unit_is_not_new(before):
    after = _ns_file(subject_body="  " + SPY + NS_READ)
    if "describe" in before:
        after = (VITEST + NAMESPACE + '\ndescribe("billing", () => {\n' + _it("charges card", CHARGES)
                 + _it("computes invoice total", "  " + SPY + NS_READ) + "});\n")
    assert _events(before, after) == []


def test_a_vi_mock_inside_another_test_ran_for_every_test():
    # Hoisted to the top of the file, so it was already there for this unit.
    before = VITEST + NAMED + "\n" + _it("charges card", "  " + VI_MOCK + "  expect(1).toBe(1);\n") + _it("computes invoice total", READ)
    after = VITEST + NAMED + "\n" + _it("charges card", "  expect(1).toBe(1);\n") + _it("computes invoice total", "  " + VI_MOCK + READ)
    assert _events(before, after) == []


# --- 188.3: what reads a whole-module mock ----------------------------------

REPORT = 'import { compute } from "../src/report.js";\n'
AUTOMOCK = 'vi.mock("../src/billing.js");\n'


def _whole(import_line: str, read: str) -> str:
    return VITEST + REPORT + import_line + "\n" + _it("computes invoice total", f"  expect({read}).toBe(78.75);\n")


@pytest.mark.parametrize("import_line,read", [
    (NAMESPACE, "compute(billing)"),
    ('const billing = require("../src/billing.js");\n', "compute(billing)"),
], ids=["namespace", "require-object"])
def test_a_module_object_read_whole_names_no_export(import_line, read):
    before = _whole(import_line, read)
    assert _events(before, before.replace(REPORT, REPORT + AUTOMOCK)) == []


@pytest.mark.parametrize("import_line,read,target", [
    (NAMESPACE, "billing.invoiceTotal([])", TARGET),
    ('import billing from "../src/billing.js";\n', "compute(billing)", "src/billing:default"),
    (NAMED, "compute(invoiceTotal)", TARGET),
], ids=["namespace-member", "default-import", "named-import-whole"])
def test_a_member_or_an_import_of_one_export_still_reads_it(import_line, read, target):
    before = _whole(import_line, read)
    assert _events(before, before.replace(REPORT, REPORT + AUTOMOCK)) == [("computes invoice total", target)]


# --- 188.4: a spy replaced in a second statement -----------------------------

SPY_BEFORE = VITEST + NAMESPACE + "\n" + _it("computes invoice total", NS_READ)


@pytest.mark.parametrize("path,before,lines", [
    (PATH, SPY_BEFORE, 'const spy = vi.spyOn(billing, "invoiceTotal");\n  spy.mockReturnValue(78.75);\n'),
    ("tests/billing.test.ts", SPY_BEFORE, 'const spy = vi.spyOn(billing, "invoiceTotal");\n  (spy as Mock).mockReturnValue(78.75);\n'),
    (PATH, SPY_BEFORE.replace(VITEST, 'const billing = require("../src/billing.js");\n').replace(NAMESPACE, ""),
     'const spy = jest.spyOn(billing, "invoiceTotal");\n  spy.mockImplementation(() => 78.75);\n'),
    ("test/billing.test.mjs",
     'import assert from "node:assert/strict";\nimport { test, mock } from "node:test";\n' + NAMESPACE
     + '\ntest("computes invoice total", () => {\n' + ITEMS
     + "  assert.strictEqual(billing.invoiceTotal(items), 78.75);\n});\n",
     'const fn = mock.method(billing, "invoiceTotal");\n  fn.mock.mockImplementation(() => 78.75);\n'),
], ids=["vi-spyOn", "ts-cast", "jest-spyOn", "node-mock-method"])
def test_a_spy_replaced_in_a_second_statement_is_a_stand_in(path, before, lines):
    anchor = "  const items"
    after = before.replace(anchor, "  " + lines + anchor, 1)
    assert _events(before, after, path) == [("computes invoice total", TARGET)]


def test_vi_mocked_in_a_second_statement_paints_the_answer():
    before = VITEST + NAMED + 'vi.mock("../src/billing.js", { spy: true });\n\n' + _it("computes invoice total", READ)
    after = before.replace("  const items", "  const total = vi.mocked(invoiceTotal);\n  total.mockReturnValue(78.75);\n  const items", 1)
    assert _events(before, after) == [("computes invoice total", TARGET)]


def test_a_two_statement_spy_the_base_side_already_had_is_not_new():
    before = SPY_BEFORE.replace("  const items", '  const spy = vi.spyOn(billing, "invoiceTotal");\n  spy.mockReturnValue(80);\n  const items', 1)
    after = SPY_BEFORE.replace("  const items", '  const spy = vi.spyOn(billing, "invoiceTotal");\n\n  spy.mockReturnValue(78.75);\n  const items', 1)
    assert _events(before, after) == []


@pytest.mark.parametrize("lines", [
    # A spy with no replacement still runs the real code.
    'const spy = vi.spyOn(billing, "invoiceTotal");\n  expect(spy).not.toHaveBeenCalled();\n',
    # A rebound name is refused, not guessed at.
    'let spy = vi.spyOn(billing, "invoiceTotal");\n  spy = vi.fn();\n  spy.mockReturnValue(78.75);\n',
], ids=["no-replacement", "rebound"])
def test_a_spy_that_replaces_nothing_the_oracle_reads_is_silent(lines):
    after = SPY_BEFORE.replace("  const items", "  " + lines + "  const items", 1)
    assert _events(SPY_BEFORE, after) == []

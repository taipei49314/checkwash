"""Runner evidence decides collection continuity and suite-wide focus (#196).

One definition (`frontends/javascript/runners.py`) answers which runner
collects a JS/TS file: the runner its own imports name, else the one the base
side's root package.json names, else unknown. Rename expansion and D2's
"live" test read it for continuity (186.7), Bun and Deno rows exist only on it
(186.4), continuity matches case-sensitively (186.3), and a focus that turns
off nothing in its own file is reported unless the runner keeps focus in the
file (187.4). The rows below are written from each runner's documented
defaults, not from the implementation's table.
"""

import datetime

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze
from checkwash.frontends.javascript.paths import is_js_test_file, is_js_test_path
from checkwash.frontends.javascript.runners import (
    collected,
    collection_continues,
    collects,
    file_runners,
    focus_is_file_scoped,
    manifest_runners,
    runner_evidence,
)

RUNNERS = ("jest", "vitest", "node", "mocha", "jasmine", "bun", "deno")

# path -> the runners whose default discovery collects it.
DEFAULT_ROWS = {
    "src/value.test.ts": {"jest", "vitest", "node", "bun", "deno"},
    "src/value.spec.js": {"jest", "vitest", "bun"},
    "src/__tests__/value.ts": {"jest", "deno"},
    "src/spec.tsx": {"jest"},
    "src/test.tsx": {"jest", "deno"},
    "src/test.js": {"jest", "node", "deno"},
    "src/value.testspec.ts": {"jest"},
    "src/spec.ts": {"jest"},
    "test/value.ts": {"node"},
    "test/value.js": {"node", "mocha"},
    "test/unit/value.js": {"node"},
    "src/value_test.ts": {"node", "bun", "deno"},
    "src/value_test.tsx": {"bun", "deno"},
    "src/value_spec.tsx": {"bun"},
    "spec/billingSpec.js": {"jasmine"},
    "spec/billing.spec.js": {"jest", "vitest", "jasmine", "bun"},
    "src/test-value.mjs": {"node"},
    "src/value-test.cjs": {"node"},
    # Case-sensitive, as the runners match.
    "src/__TESTS__/value.ts": set(),
    "src/Value.Test.ts": set(),
    "TEST/value.js": set(),
    # Never tests.
    "src/value.ts": set(),
    "node_modules/pkg/value.test.js": set(),
}


@pytest.mark.parametrize("path,expected", sorted(DEFAULT_ROWS.items()))
def test_each_runner_row_is_its_documented_default(path, expected):
    assert {runner for runner in RUNNERS if collects(runner, path)} == expected


def test_obligations_still_fold_case_where_continuity_does_not():
    # 186.3: a test is judged whatever its case; a runner collects it only in
    # the case it matches.
    assert is_js_test_path("src/__TESTS__/value.ts")
    assert is_js_test_path("src/Value.Test.ts")
    assert not collected("src/__TESTS__/value.ts", None)
    assert not collected("src/Value.Test.ts", None)


@pytest.mark.parametrize("source,expected", [
    ('import { test, expect } from "vitest";\n', {"vitest"}),
    ("import {\n  test,\n  expect,\n} from 'vitest';\n", {"vitest"}),
    ('import * as v from "vitest";\n', {"vitest"}),
    ('import "vitest";\n', {"vitest"}),
    ('import { it, expect } from "@jest/globals";\n', {"jest"}),
    ('const test = require("node:test");\n', {"node"}),
    ('const { describe } = require ( "node:test" );\n', {"node"}),
    ('const b = await import("bun:test");\n', {"bun"}),
    ('import { test } from "bun:test";\n', {"bun"}),
    ('Deno.test("total", () => {});\n', {"deno"}),
    ('Deno.test.only({ name: "total", fn() {} });\n', {"deno"}),
    # Several runners: the file runs under one of them.
    ('import { test } from "vitest";\nimport assert from "node:test";\n', {"vitest", "node"}),
    # chai is an assertion library, not a runner, and leaves the runner standing.
    ('import { expect } from "chai";\n', set()),
    ('import { expect } from "chai";\nimport { it } from "@jest/globals";\n', {"jest"}),
    # A type-only import loads nothing; Node's `test` package is not node:test.
    ('import type { Mock } from "vitest";\n', set()),
    ('const test = require("test");\n', set()),
    # Comments, strings and templates name nothing.
    ('// import { test } from "vitest";\n', set()),
    ('/* require("node:test") */\n', set()),
    ("const s = \"import { a } from 'vitest'\";\n", set()),
    ('const t = `import "vitest"`;\n', set()),
    ('const s = "Deno.test(";\n', set()),
    ('describe("billing", () => { it("total", () => {}); });\n', set()),
])
def test_a_file_names_its_runner_by_import(source, expected):
    assert file_runners(source.encode()) == frozenset(expected)


@pytest.mark.parametrize("manifest,expected", [
    ('{"devDependencies": {"jest": "^30.0.0", "ts-jest": "^29"}}', {"jest"}),
    ('{"dependencies": {"vitest": "^3"}}', {"vitest"}),
    ('{"devDependencies": {"mocha": "^11", "chai": "^5"}}', {"mocha"}),
    ('{"devDependencies": {"jasmine": "^5"}}', {"jasmine"}),
    # A mix, or none, is unknown.
    ('{"devDependencies": {"jest": "^30", "vitest": "^3"}}', None),
    ('{"dependencies": {"mocha": "^11"}, "devDependencies": {"jasmine": "^5"}}', None),
    ('{"devDependencies": {"@jest/globals": "^30", "@vitest/ui": "^3"}}', None),
    ('{"scripts": {"test": "jest"}}', None),
    ('{}', None),
    ('[]', None),
    ('not json', None),
    ("", None),
])
def test_the_root_manifest_names_a_runner_only_alone(manifest, expected):
    assert manifest_runners(manifest.encode()) == (None if expected is None else frozenset(expected))


def test_a_file_import_outranks_the_manifest():
    jest_only = b'{"devDependencies": {"jest": "^30"}}'
    assert runner_evidence(b'import { test } from "vitest";\n', jest_only) == {"vitest"}
    assert runner_evidence(b'describe("x", () => {});\n', jest_only) == {"jest"}
    assert runner_evidence(b'describe("x", () => {});\n', None) is None


def test_evidence_judges_only_moves_its_runner_collects_by_default():
    vitest = frozenset({"vitest"})
    assert not collection_continues("src/value.test.ts", "src/__tests__/value.ts", vitest)
    assert collection_continues("src/value.test.ts", "src/value.spec.tsx", vitest)
    # A Vitest file beneath __tests__ is collected by a configured include, so
    # the defaults cannot judge the move; the union does, leniently.
    assert collection_continues("src/__tests__/a.ts", "src/__tests__/b.ts", vitest)
    # Without evidence, the union, case-sensitively.
    assert collection_continues("src/value.test.ts", "src/__tests__/value.ts", None)
    assert not collection_continues("src/value.test.ts", "src/__TESTS__/value.ts", None)


@pytest.mark.parametrize("path,source,expected", [
    ("src/value_spec.ts", 'import { test } from "bun:test";\n', True),
    ("src/value_test.tsx", 'import { test } from "bun:test";\n', True),
    ("src/Value_Spec.TS", 'import { test } from "bun:test";\n', True),
    ("src/value_test.jsx", 'Deno.test("total", () => {});\n', True),
    # Never a union row: without the runner's own evidence, no test.
    ("src/value_spec.ts", 'import { test } from "vitest";\n', False),
    ("src/value_spec.ts", 'describe("x", () => {});\n', False),
    ("src/value_test.tsx", "", False),
    # Deno does not collect `_spec`, and no evidence makes a non-row a test.
    ("src/value_spec.ts", 'Deno.test("total", () => {});\n', False),
    ("src/value.ts", 'import { test } from "bun:test";\n', False),
])
def test_bun_and_deno_rows_exist_only_on_their_evidence(path, source, expected):
    assert is_js_test_file(path, source.encode()) is expected
    assert is_js_test_file(path, None, source.encode()) is expected


@pytest.mark.parametrize("evidence,expected", [
    ({"jest"}, True), ({"vitest"}, True), ({"jest", "vitest"}, True),
    ({"node"}, False), ({"mocha"}, False), ({"jasmine"}, False), ({"bun"}, False),
    ({"deno"}, False), ({"vitest", "node"}, False), (set(), False), (None, False),
])
def test_only_jest_and_vitest_keep_focus_in_the_file(evidence, expected):
    assert focus_is_file_scoped(None if evidence is None else frozenset(evidence)) is expected


# --- through the engine ------------------------------------------------------

VITEST = 'import { test, expect } from "vitest";\nimport { total } from "./value";\ntest("total", () => { expect(total()).toBe(78.75); });\n'
GLOBALS = 'import { total } from "./value";\ntest("total", () => { expect(total()).toBe(78.75); });\n'
NODE = ('const test = require("node:test");\nconst assert = require("node:assert");\n'
        'const { total } = require("./value");\ntest("total", () => { assert.strictEqual(total(), 78.75); });\n')
BUN = 'import { test, expect } from "bun:test";\nimport { total } from "./value";\ntest("total", () => { expect(total()).toBe(78.75); });\n'
DENO = 'import { total } from "./value.ts";\nDeno.test("total", () => { if (total() !== 78.75) throw new Error(); });\n'
TODAY = datetime.date(2026, 10, 3)


def _analyze(changes, snapshot=None):
    snapshot = snapshot or {}
    return analyze(changes, Config(), Contract(), [], TODAY, root_reader=snapshot.get)


def _move(old, new, source):
    return FileChange(new, "renamed", source.encode(), source.encode(), old_path=old)


def _summary(findings):
    return [(f.rule, f.severity, f.path, f.unit) for f in findings]


@pytest.mark.parametrize("old,new,source", [
    # The #196 rows: each source is collected by its evidenced runner, which
    # does not collect the destination.
    ("src/value.test.ts", "src/__tests__/value.ts", VITEST),  # M0
    ("src/value.test.tsx", "src/spec.tsx", VITEST),  # M1
    ("src/value.test.tsx", "src/test.tsx", VITEST),  # M2
    ("src/value.test.tsx", "src/value.testspec.ts", VITEST),  # M3
    ("src/value.test.tsx", "src/__TESTS__/value.ts", VITEST),  # M4
    ("src/value.test.ts", "src/spec.ts", VITEST),  # M5
    ("src/value.test.ts", "test/value.ts", VITEST),  # P1
    ("src/value.test.ts", "src/value_test.ts", VITEST),  # P2
    ("test/value.js", "src/value.spec.js", NODE),  # P3
    # Case: no runner collects `__TESTS__`, whatever the evidence (186.3).
    ("src/value.test.tsx", "src/__TESTS__/value.ts", GLOBALS),
    # Bun's `_spec` is a removal unless the file proves Bun (186.4).
    ("src/value.test.tsx", "src/value_spec.tsx", VITEST),
])
def test_a_move_out_of_the_evidenced_runners_collection_is_a_removal(old, new, source):
    _ir, findings, verdict = _analyze([_move(old, new, source)])
    assert verdict == "block"
    assert _summary(findings) == [("TEST_DISABLED", "high", old, "total")]


@pytest.mark.parametrize("old,new,source", [
    # Jest-style globals name no runner, and Jest collects the destination.
    ("src/value.test.ts", "src/__tests__/value.ts", GLOBALS),
    ("src/value.test.tsx", "src/spec.tsx", GLOBALS),
    # Each runner still collects its own destination.
    ("src/value.test.ts", "src/value.spec.ts", VITEST),
    ("test/value.js", "test/unit/value.js", NODE),
    ("src/value.test.ts", "src/value_spec.ts", BUN),
    ("src/value.test.tsx", "src/value_test.tsx", BUN),
    ("src/value.test.ts", "src/value_test.tsx", DENO),
    # The evidenced runner does not collect the source by default either: the
    # project configures its own globs, so the union judges the move.
    ("src/__tests__/a.ts", "src/__tests__/b.ts", VITEST),
])
def test_a_move_its_runner_still_collects_stays_benign(old, new, source):
    _ir, findings, verdict = _analyze([_move(old, new, source)])
    assert (_summary(findings), verdict) == ([], "pass")


VITEST_MANIFEST = b'{"devDependencies": {"vitest": "^3.2.0"}}'
JEST_MANIFEST = b'{"devDependencies": {"jest": "^30.0.0"}}'


def test_the_base_manifest_names_the_runner_of_a_file_on_globals():
    move = _move("src/value.test.ts", "src/__tests__/value.ts", GLOBALS)
    _ir, findings, verdict = _analyze([move], {"package.json": VITEST_MANIFEST})
    assert (verdict, _summary(findings)) == ("block", [("TEST_DISABLED", "high", "src/value.test.ts", "total")])
    _ir, findings, verdict = _analyze([move], {"package.json": JEST_MANIFEST})
    assert (_summary(findings), verdict) == ([], "pass")


@pytest.mark.parametrize("old,new,manifest,verdict", [
    # Jasmine collects `*Spec.js` beneath spec/, and not `*.test.js`.
    ("spec/x.spec.js", "spec/xSpec.js", b'{"devDependencies": {"jasmine": "^5"}}', "pass"),
    ("spec/x.spec.js", "spec/x.test.js", b'{"devDependencies": {"jasmine": "^5"}}', "block"),
    # Mocha's default spec is `./test`, not recursive: a move into a
    # subdirectory stops it, while a move within one is judged by the union.
    ("test/x.js", "test/unit/x.js", b'{"devDependencies": {"mocha": "^11"}}', "block"),
    ("test/unit/a.js", "test/unit/b.js", b'{"devDependencies": {"mocha": "^11"}}', "pass"),
    ("test/x.js", "test/unit/x.js", None, "pass"),
])
def test_mocha_and_jasmine_are_known_from_the_manifest(old, new, manifest, verdict):
    source = 'describe("billing", function () {\n  it("total", function () { expect(total()).toBe(78.75); });\n});\n'
    snapshot = {"package.json": manifest} if manifest else {}
    _ir, findings, actual = _analyze([_move(old, new, source)], snapshot)
    assert actual == verdict
    assert _summary(findings) == ([("TEST_DISABLED", "high", old, "total")] if verdict == "block" else [])


def test_the_diff_cannot_choose_the_runner_it_is_judged_by():
    # The manifest's base side names Vitest; the head side's Jest is not read.
    manifest = FileChange("package.json", "modified", VITEST_MANIFEST, JEST_MANIFEST)
    move = _move("src/value.test.ts", "src/__tests__/value.ts", GLOBALS)
    _ir, findings, verdict = _analyze([manifest, move], {"package.json": JEST_MANIFEST})
    assert verdict == "block"
    assert ("TEST_DISABLED", "high", "src/value.test.ts", "total") in _summary(findings)


def test_a_unit_moved_into_a_file_its_runner_does_not_collect_earns_no_move_credit():
    # D2: the unit reappears, but Vitest does not run `__tests__/b.ts`.
    deleted = FileChange("src/a.test.ts", "deleted", VITEST.encode(), None)
    added = FileChange("src/__tests__/b.ts", "added", None, (VITEST.replace("./value", "../value")).encode())
    _ir, findings, verdict = _analyze([deleted, added])
    assert verdict == "block"
    assert ("TEST_DISABLED", "high", "src/a.test.ts", "total") in _summary(findings)
    # Where its runner collects the destination, the same move is credited.
    added_ok = FileChange("src/b.test.ts", "added", None, VITEST.encode())
    _ir, findings, verdict = _analyze([deleted, added_ok])
    assert verdict == "pass"
    assert all("ASSERTION_MOVED" in f.deescalators for f in findings if f.rule == "TEST_DISABLED")
    # Without evidence, the union still collects `__tests__`.
    deleted_g = FileChange("src/a.test.ts", "deleted", GLOBALS.encode(), None)
    added_g = FileChange("src/__tests__/b.ts", "added", None, GLOBALS.replace("./value", "../value").encode())
    _ir, findings, verdict = _analyze([deleted_g, added_g])
    assert verdict == "pass"


def test_a_bun_spec_file_is_judged_as_a_test():
    weakened = BUN.replace("toBe(78.75)", "toBeTruthy()")
    ir, findings, verdict = _analyze([FileChange("src/value_spec.ts", "modified", BUN.encode(), weakened.encode())])
    assert [file.role for file in ir.files] == ["test"]
    removed = FileChange("src/value_spec.ts", "modified", BUN.encode(), b'import { test } from "bun:test";\n')
    _ir, findings, verdict = _analyze([removed])
    assert verdict == "block"
    assert _summary(findings) == [("TEST_DISABLED", "high", "src/value_spec.ts", "total")]


# --- 187.4: focus that turns off nothing in its own file ---------------------

MOCHA = ('const assert = require("node:assert");\nconst { total, tax } = require("../src/value");\n'
         'describe("billing", function () {\n'
         '  it("total", function () { assert.strictEqual(total(), 78.75); });\n'
         '  it("tax", function () { assert.strictEqual(tax(), 3.75); });\n'
         '});\n')


def _focus(source, path="test/billing.spec.js", snapshot=None, before=MOCHA):
    """`before=None` adds the file."""
    status = "added" if before is None else "modified"
    change = FileChange(path, status, None if before is None else before.encode(), source.encode())
    return _analyze([change], snapshot)


@pytest.mark.parametrize("focused", [
    MOCHA.replace('it("total"', 'it.only("total"').replace('it("tax"', 'it.only("tax"'),  # F5
    MOCHA.replace('describe("billing"', 'describe.only("billing"'),  # F6
    MOCHA.replace('describe("billing"', 'fdescribe("billing"'),
    MOCHA.replace('it("total"', 'it.only("total"').replace('it("tax"', 'fit("tax"'),
])
def test_focus_on_every_unit_is_reported_once_for_the_file(focused):
    _ir, findings, verdict = _focus(focused)
    assert verdict == "block"
    assert _summary(findings) == [("TEST_DISABLED", "high", "test/billing.spec.js", None)]
    assert "under a runner that applies focus suite-wide" in findings[0].message
    assert findings[0].after is not None and findings[0].after.text in {"it.only", "describe.only", "fdescribe"}


def test_focus_that_stops_a_sibling_is_reported_on_the_sibling_alone():
    _ir, findings, verdict = _focus(MOCHA.replace('it("total"', 'it.only("total"'))  # Fc1
    assert _summary(findings) == [("TEST_DISABLED", "high", "test/billing.spec.js", "tax")]


@pytest.mark.parametrize("header", [
    'import { describe, it } from "vitest";\n',
    'import { describe, it } from "@jest/globals";\n',
])
def test_a_file_scoped_runner_import_keeps_whole_file_focus_quiet(header):
    focused = MOCHA.replace('describe("billing"', 'describe.only("billing"')
    _ir, findings, verdict = _focus(header + focused, before=header + MOCHA)
    assert (_summary(findings), verdict) == ([], "pass")


def test_a_manifest_naming_only_jest_keeps_whole_file_focus_quiet():
    focused = MOCHA.replace('describe("billing"', 'describe.only("billing"')
    _ir, findings, verdict = _focus(focused, snapshot={"package.json": JEST_MANIFEST})
    assert (_summary(findings), verdict) == ([], "pass")
    _ir, findings, verdict = _focus(focused, snapshot={"package.json": b'{"devDependencies": {"mocha": "^11"}}'})
    assert verdict == "block"


def test_a_node_test_import_is_no_proof_of_file_scope():
    header = 'const { describe, it } = require("node:test");\n'
    focused = MOCHA.replace('describe("billing"', 'describe.only("billing"')
    _ir, findings, verdict = _focus(header + focused, before=header + MOCHA)
    assert verdict == "block"
    assert _summary(findings) == [("TEST_DISABLED", "high", "test/billing.spec.js", None)]


def test_focus_the_base_already_had_is_not_added():
    base = MOCHA.replace('it("total"', 'it.only("total"').replace('it("tax"', 'it.only("tax"')
    focused = base.replace("78.75", "78.75 ")
    _ir, findings, verdict = _focus(focused, before=base)
    assert (_summary(findings), verdict) == ([], "pass")


def test_a_new_file_that_arrives_focused_is_reported():
    focused = MOCHA.replace('describe("billing"', 'describe.only("billing"')
    _ir, findings, verdict = _focus(focused, path="test/new.spec.js", before=None)
    assert verdict == "block"
    assert _summary(findings) == [("TEST_DISABLED", "high", "test/new.spec.js", None)]


def test_the_file_level_focus_fingerprint_is_stable_and_its_own():
    focused = MOCHA.replace('describe("billing"', 'describe.only("billing"')
    _ir, first, _verdict = _focus(focused)
    _ir, again, _verdict = _focus(focused.replace("3.75", "3.75 "))
    assert first[0].fingerprint == again[0].fingerprint
    _ir, sibling, _verdict = _focus(MOCHA.replace('it("total"', 'it.only("total"'))
    assert first[0].fingerprint != sibling[0].fingerprint

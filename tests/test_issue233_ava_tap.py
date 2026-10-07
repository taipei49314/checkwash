"""Issue #233: AVA and tap tests are read.

AVA's and tap's `t` assertions were no assertions to the JS frontend, and
their `tests/` layouts were no JS test paths: beneath `tests/` every edit
passed, and `t.is` -> `t.truthy` passed anywhere (rows A1-A3, T1, T2). An
`ava` or `tap` import, or a base root package.json that names one of them
alone, now names the runner. Their layout rows exist only on a file's own
evidence, as Bun's and Deno's do, so a Python project's JS helpers under
`tests/` stay production. The methods of a test callback's own `t`, and of
tap's root `t`, map onto chai's meanings.
"""
import datetime

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.frontends.javascript.bindings import TAP_ASSERTIONS, TAP_SYNONYMS
from checkwash.frontends.javascript.coverage import javascript_coverage_gaps
from checkwash.frontends.javascript.frontend import parse_javascript
from checkwash.frontends.javascript.paths import is_js_test_file
from checkwash.frontends.javascript.runners import (
    EVIDENCE_ONLY,
    collects,
    evidenced_test_path,
    file_runners,
    focus_is_file_scoped,
    manifest_runners,
)
from checkwash.ir import strength as S

AVA = "import test from 'ava';\nimport { total } from '../src/total.js';\n\n{decl}('total', t => {\n  {line}\n});\n"
TAP = "import t from 'tap';\nimport { total } from '../src/total.js';\n\nt.test('total', async t => {\n  {line}\n});\n"
AVA_EMPTY = "import test from 'ava';\nimport { total } from '../src/total.js';\n"
TAP_EMPTY = "import t from 'tap';\nimport { total } from '../src/total.js';\n"
BLOCK, PASS = "block", "pass"


def ava(line, decl="test"):
    return AVA.replace("{decl}", decl).replace("{line}", line)


def tap(line):
    return TAP.replace("{line}", line)


def judge(path, before, after):
    changes = [FileChange(path, "modified", before.encode(), after.encode())]
    _ir, findings, verdict = analyze(changes, Config(), Contract(), [], datetime.date(2026, 10, 6))
    return verdict, [(f.rule, f.severity) for f in findings]


def recorded(source):
    return [(a.form, a.strength, a.positive, a.predicate, a.text)
            for unit in parse_javascript(source.encode()).units for a in unit.side.assertions]


def texts(source):
    return [a[-1] for a in recorded(source)]


def gaps(source):
    data = source.encode()
    return [(gap.callee, gap.reason.split(" assertion candidate")[0], "no strength" in gap.reason)
            for gap in javascript_coverage_gaps(data, parse_javascript(data), "test/value.js", "after")]


WEAKENED = (BLOCK, [("ASSERT_WEAKENED", "high")])
DISABLED = (BLOCK, [("TEST_DISABLED", "high")])


# --- The issue's rows ---------------------------------------------------------------------------

@pytest.mark.parametrize("path, before, after, expected", [
    ("tests/value.js", ava("t.is(total(), 78.75);"), AVA_EMPTY, DISABLED),                      # A1
    ("tests/value.js", ava("t.is(total(), 78.75);"), ava("t.truthy(total());"), WEAKENED),      # A2
    ("test/value.js", ava("t.is(total(), 78.75);"), ava("t.truthy(total());"), WEAKENED),       # A3
    ("test/value.js", ava("t.is(total(), 78.75);"), AVA_EMPTY, DISABLED),                       # A4
    ("tests/value.js", tap("t.equal(total(), 78.75);"), tap("t.ok(total());"), WEAKENED),       # T1
    ("test/value.js", tap("t.equal(total(), 78.75);"), tap("t.ok(total());"), WEAKENED),        # T2
    ("test/value.js", tap("t.equal(total(), 78.75);"), TAP_EMPTY, DISABLED),                    # T3
], ids=["A1", "A2", "A3", "A4", "T1", "T2", "T3"])
def test_the_issues_rows_are_judged(path, before, after, expected):
    assert judge(path, before, after) == expected


# --- Runner evidence ----------------------------------------------------------------------------

@pytest.mark.parametrize("source, runners", [
    ("import test from 'ava';", {"ava"}),
    ("const test = require('ava');", {"ava"}),
    ("import t from 'tap';", {"tap"}),
    ("import * as tap from 'tap';", {"tap"}),
    ("const { test } = require('tap');", {"tap"}),
    ("var test = require('tap').test;", {"tap"}),
    ("import t from 'tape';", set()),
    ("// import test from 'ava'", set()),
    ("const name = 'ava';", set()),
])
def test_an_ava_or_tap_import_names_the_runner(source, runners):
    assert file_runners(source.encode()) == runners


@pytest.mark.parametrize("dependencies, runners", [
    ({"ava": "^6.0.0"}, frozenset({"ava"})),
    ({"tap": "^21.0.0"}, frozenset({"tap"})),
    ({"ava": "^6.0.0", "jest": "^30"}, None),    # a mix is unknown
    ({"tap": "^21.0.0", "mocha": "^11"}, None),
    ({"tape": "^5.0.0"}, None),
])
def test_a_manifest_that_names_ava_or_tap_alone_names_it(dependencies, runners):
    manifest = ('{"devDependencies": {' + ", ".join(f'"{k}": "{v}"' for k, v in dependencies.items())
                + "}}").encode()
    assert manifest_runners(manifest) == runners


@pytest.mark.parametrize("path, source, obligations", [
    ("tests/value.js", "import test from 'ava';", True),
    ("tests/value.js", "import t from 'tap';", True),
    ("tests/value.js", "export const total = () => 78.75;", False),   # a Python project's JS helper
    ("tests/value.js", "import t from 'tape';", False),
    ("tests/helpers/value.js", "import test from 'ava';", False),     # AVA's helper directory
    ("tests/_value.js", "import test from 'ava';", False),            # AVA's helper name
    ("tests/fixtures/value.js", "import t from 'tap';", False),        # tap's fixture directory
    ("lib/value.tests.js", "import t from 'tap';", True),              # tap's `*.tests` name
    ("lib/test-value.js", "import test from 'ava';", True),            # AVA's `test-*` name
    ("test/value.js", "export const total = () => 78.75;", True),      # Node's row, as before
])
def test_avas_and_taps_rows_exist_only_on_the_files_own_evidence(path, source, obligations):
    assert is_js_test_file(path, source.encode()) is obligations


def test_either_sides_evidence_keeps_the_obligations():
    # Dropping the import does not drop the file's obligations.
    assert is_js_test_file("tests/value.js", b"export const x = 1;", b"import test from 'ava';")


@pytest.mark.parametrize("path", ["tests/test_value.py", "tests/value.py", "tests/__tests__/data.json",
                                  "tests/value.tests", "test.txt", "tests.d/value", "tests/Makefile"])
def test_an_evidence_only_row_collects_js_and_ts_extensions_only(path):
    """`evidenced_test_path` answers any other file without reading the rows, which must agree."""
    assert not any(collects(runner, path, fold=True) for runner in EVIDENCE_ONLY)
    assert not evidenced_test_path(path, b"import test from 'ava';\nimport t from 'tap';\nimport 'bun:test';")


# --- Layout rows --------------------------------------------------------------------------------

@pytest.mark.parametrize("path, collected", [
    ("test.js", True), ("src/test.mjs", True), ("source/test.js", True), ("lib/test.js", False),
    ("lib/value.spec.js", True), ("lib/value.test.mjs", True), ("lib/test-value.js", True),
    ("__tests__/value.js", True), ("test/value.js", True), ("tests/deep/value.mjs", True),
    ("tests/value.cjs", False), ("tests/value.ts", False),            # js and mjs only by default
    ("tests/_value.js", False), ("tests/_util/value.js", False),      # "helpers": one leading underscore
    ("tests/__generated__/value.js", True),                           # two underscores are no helper
    ("tests/helper/value.js", False), ("test/fixtures/value.js", False),
    ("__tests__/__helpers__/value.js", False), ("__tests__/__fixture__/value.js", False),
    ("__tests__/helpers/value.js", True),                             # only `__helper(s)__` there
    ("lib/value.js", False), ("tests/.cache/value.js", False),
])
def test_avas_default_layout(path, collected):
    assert collects("ava", path) is collected


@pytest.mark.parametrize("path, collected", [
    ("test/value.js", True), ("tests/value.ts", True), ("__tests__/value.tsx", True),
    ("__test__/value.mjs", True), ("lib/deep/test/value.cts", True),
    ("lib/value.test.cjs", True), ("lib/value.tests.js", True), ("lib/value.spec.mts", True),
    ("test.js", True), ("lib/tests.jsx", True),
    ("test/fixture/value.js", False), ("test/fixtures/value.js", False), ("test/dist/value.js", False),
    ("tap-snapshots/test/value.js", False), ("test/.hidden/value.js", False), ("test/.value.js", False),
    ("lib/value.js", False), ("test/value.json", False),
])
def test_taps_default_layout(path, collected):
    assert collects("tap", path) is collected


# --- Whose `t` is read --------------------------------------------------------------------------

@pytest.mark.parametrize("decl", [
    "test", "test.serial", "test.failing", "test.only", "test.serial.only", "test.skipIf(process.env.CI)",
    "test.runIf(process.env.CI)",
])
def test_every_ava_declaration_passes_its_callback_avas_t(decl):
    assert texts(ava("t.is(total(), 78.75);", decl)) == ["t.is(total(), 78.75)"]


def test_avas_t_is_read_through_require():
    source = ava("t.is(total(), 78.75);").replace("import test from 'ava';", "const test = require('ava');")
    assert texts(source) == ["t.is(total(), 78.75)"]


@pytest.mark.parametrize("head, declare", [
    ("import t from 'tap';", "t.test"),
    ("import tap from 'tap';", "tap.test"),
    ("import { test } from 'tap';", "test"),
    ("import { t } from 'tap';", "t.test"),
    ("import * as tap from 'tap';", "tap.t.test"),
    ("const t = require('tap');", "t.test"),
    ("const { test } = require('tap');", "test"),
    ("const { t } = require('tap');", "t.test"),
    ("const test = require('tap').test;", "test"),
])
def test_every_tap_spelling_passes_its_subtests_taps_t(head, declare):
    source = f"{head}\n\n{declare}('total', async t => {{\n  t.equal(total(), 78.75);\n}});\n"
    assert texts(source) == ["t.equal(total(), 78.75)"]


def test_a_nested_subtest_reads_its_own_t():
    source = tap("t.test('inner', t => { t.ok(total()); });\n  t.equal(total(), 78.75);")
    by_unit = {u.qualname: [a.text for a in u.side.assertions] for u in parse_javascript(source.encode()).units}
    assert by_unit == {"total": ["t.equal(total(), 78.75)"], "inner": ["t.ok(total())"]}


def test_taps_root_t_inside_a_subtest_is_read():
    source = "import t from 'tap';\n\nt.test('total', async () => {\n  t.equal(total(), 78.75);\n});\n"
    assert texts(source) == ["t.equal(total(), 78.75)"]
    # The default export is `t` itself, whose methods the module does not
    # export by name.
    source = "import t from 'tap';\n\nt.test('total', async () => {\n  t.deepEqual(total(), [1]);\n});\n"
    assert texts(source) == ["t.deepEqual(total(), [1])"]


def test_taps_module_exports_some_assertions_by_name():
    def unit(head, line):
        return texts(f"{head}\n\nt.test('total', async () => {{\n  {line}\n}});\n")

    assert unit("import t from 'tap';\nimport { ok } from 'tap';", "ok(total());") == ["ok(total())"]
    # tap 16's ES module exports `equal`; tap 21's does not, and there the
    # import throws before any test runs.
    assert unit("import t from 'tap';\nimport { equal } from 'tap';", "equal(total(), 78.75);") == [
        "equal(total(), 78.75)"]
    assert unit("import * as tap from 'tap';\nconst t = tap.t;", "tap.equal(total(), 78.75);") == [
        "tap.equal(total(), 78.75)"]
    # Neither exports `hasProp` or a synonym: they are `t`'s only.
    assert unit("import t from 'tap';\nimport { hasProp } from 'tap';", "hasProp(total(), 'a');") == []
    assert unit("import t from 'tap';\nimport { deepEqual } from 'tap';", "deepEqual(total(), [1]);") == []
    # Its CommonJS export is `t` itself, which has every method and synonym.
    assert unit("const t = require('tap');\nconst { equal } = require('tap');", "equal(total(), 78.75);") == [
        "equal(total(), 78.75)"]
    assert unit("const t = require('tap');\nconst { deepEqual } = require('tap');", "deepEqual(total(), [1]);") == [
        "deepEqual(total(), [1])"]


@pytest.mark.parametrize("source", [
    # tape is not read: its `t` is no runner's this round reads.
    "const test = require('tape');\n\ntest('total', t => {\n  t.equal(total(), 78.75);\n});\n",
    # node:test's context has no `is`.
    "import test from 'node:test';\n\ntest('total', t => {\n  t.is(total(), 78.75);\n});\n",
    # An object named `t`, and another object's `t`.
    "import test from 'ava';\n\ntest('total', () => {\n  const t = make();\n  t.is(total(), 78.75);\n});\n",
    "import test from 'ava';\n\ntest('total', t => {\n  other.t.is(total(), 78.75);\n});\n",
    # A member of a call's result, continued across a line break and a comment.
    "import test from 'ava';\n\ntest('total', t => {\n  make(). /* c */\n    t.is(total(), 78.75);\n});\n",
    "import test from 'ava';\n\ntest('total', t => {\n  new t.is(total(), 78.75);\n});\n",
    # A parameter shadows the callback's `t`.
    "import test from 'ava';\n\ntest('total', t => {\n  [1].forEach(t => t.is(total(), 78.75));\n});\n",
])
def test_a_t_that_is_not_avas_or_taps_is_not_read(source):
    assert texts(source) == []


def test_a_written_t_is_no_longer_avas():
    source = ava("t = fake();\n  t.is(total(), 78.75);")
    assert texts(source) == []
    # It was AVA's, so its assertion call stays a notice of unknown provenance.
    assert gaps(source) == [("t.is", "unresolved", False)]
    assert gaps(ava("t = fake();\n  t.plan(1);")) == []
    # tap's, by a synonym too.
    assert gaps(tap("t = fake();\n  t.deepEqual(total(), [1]);")) == [("t.deepEqual", "unresolved", False)]


def test_a_read_assertion_left_out_for_its_arguments_is_only_a_notice():
    # As for chai's assert interface: not recorded, and visible.
    assert recorded(ava("t.is();")) == []
    assert gaps(ava("t.is();")) == [("t.is", "AVA", False)]


# --- The dialect --------------------------------------------------------------------------------

EQ, STRUCT, PAT, TRUTHY = S.EXACT_VALUE, S.EXACT_STRUCT, S.PATTERN, S.TRUTHY


@pytest.mark.parametrize("line, form, strength, positive, predicate", [
    ("t.is(total(), 78.75)", "compare_eq", EQ, True, "eq_strict"),
    ("t.not(total(), 78.75)", "compare_eq", EQ, False, "eq_strict"),
    ("t.deepEqual(total(), [1])", "compare_eq", STRUCT, True, None),
    ("t.notDeepEqual(total(), [1])", "compare_eq", STRUCT, False, None),
    ("t.like(total(), {a: 1})", "membership", PAT, True, None),
    ("t.true(total())", "compare_eq", EQ, True, "is_true"),
    ("t.false(total())", "compare_eq", EQ, True, "is_false"),
    ("t.truthy(total())", "truthy", TRUTHY, True, "truthy"),
    ("t.assert(total())", "truthy", TRUTHY, True, "truthy"),
    ("t.falsy(total())", "truthy", TRUTHY, False, "truthy"),
    ("t.regex(total(), /7/)", "pattern", PAT, True, None),
    ("t.notRegex(total(), /7/)", "pattern", PAT, False, None),
])
def test_avas_assertions_take_chais_meanings(line, form, strength, positive, predicate):
    assert recorded(ava(line + ";")) == [(form, strength, positive, predicate, line)]


@pytest.mark.parametrize("line, form, strength, positive, predicate", [
    ("t.equal(total(), 78.75)", "compare_eq", EQ, True, "eq_strict"),
    ("t.not(total(), 78.75)", "compare_eq", EQ, False, "eq_strict"),
    ("t.same(total(), [1])", "compare_eq", STRUCT, True, None),
    ("t.strictSame(total(), [1])", "compare_eq", STRUCT, True, None),
    ("t.notSame(total(), [1])", "compare_eq", STRUCT, False, None),
    ("t.strictNotSame(total(), [1])", "compare_eq", STRUCT, False, None),
    ("t.ok(total())", "truthy", TRUTHY, True, "truthy"),
    ("t.notOk(total())", "truthy", TRUTHY, False, "truthy"),
    ("t.match(total(), /7/)", "pattern", PAT, True, None),
    ("t.notMatch(total(), /7/)", "pattern", PAT, False, None),
    ("t.has(total(), {a: 1})", "membership", PAT, True, None),
    ("t.hasStrict(total(), {a: 1})", "membership", PAT, True, None),
    ("t.notHas(total(), {a: 1})", "membership", PAT, False, None),
    ("t.notHasStrict(total(), {a: 1})", "membership", PAT, False, None),
])
def test_taps_assertions_take_chais_meanings(line, form, strength, positive, predicate):
    assert recorded(tap(line + ";")) == [(form, strength, positive, predicate, line)]


@pytest.mark.parametrize("synonym, method", [
    ("deepEqual", "same"), ("equals", "equal"), ("is", "equal"), ("true", "ok"), ("false", "notOk"),
    ("like", "match"), ("includes", "has"), ("notEqual", "not"), ("isDeeply", "strictSame"),
    ("notDeeply", "strictNotSame"), ("notDeepEqual", "notSame"), ("isa", "type"), ("is_a", "type"),
    ("notok", "notOk"), ("not_ok", "notOk"), ("strict_same", "strictSame"), ("does_not_throw", "doesNotThrow"),
])
def test_tap_16s_synonyms_read_as_the_method_they_name(synonym, method):
    assert TAP_SYNONYMS[synonym] == method
    assert [r[:4] for r in recorded(tap(f"t.{synonym}(total(), [1]);"))] == [
        r[:4] for r in recorded(tap(f"t.{method}(total(), [1]);"))]


def test_every_tap_16_synonym_reads_as_its_method():
    # tap 16's `lib/synonyms.js`: 214 spellings of 15 methods, none of them
    # a method of tap 21's.
    assert len(TAP_SYNONYMS) == 214
    assert not set(TAP_SYNONYMS) & TAP_ASSERTIONS
    mismatched = [
        synonym for synonym, method in TAP_SYNONYMS.items()
        if [r[:4] for r in recorded(tap(f"t.{synonym}(total(), [1]);"))]
        != [r[:4] for r in recorded(tap(f"t.{method}(total(), [1]);"))]]
    assert mismatched == []


def test_a_synonym_is_taps_only():
    # AVA's `t` has none of them, and node's `t.assert` takes no `equals`.
    assert texts(ava("t.equals(total(), 78.75);")) == []
    assert texts(ava("t.isDeeply(total(), [1]);")) == []
    assert texts("import test from 'node:test';\n\ntest('total', t => {\n  t.equals(total(), 78.75);\n});\n") == []


@pytest.mark.parametrize("source, form", [
    (ava("t.throws(() => total(-1));"), "raises"),
    (ava("t.throwsAsync(() => total(-1));"), "raises"),
    (ava("t.notThrows(() => total(1));"), "unknown"),
    (ava("t.notThrowsAsync(() => total(1));"), "unknown"),
    (ava("t.snapshot(total());"), "unknown"),
    (ava("t.fail();"), "unknown"),
    (tap("t.throws(() => total(-1));"), "raises"),
    (tap("t.rejects(() => total(-1));"), "raises"),
    (tap("t.doesNotThrow(() => total(1));"), "unknown"),
    (tap("t.resolves(total());"), "unknown"),
    (tap("t.resolveMatch(total(), {a: 1});"), "unknown"),
    (tap("t.emits(emitter, 'done');"), "unknown"),
    (tap("t.error(err);"), "unknown"),
    (tap("t.type(total(), 'number');"), "unknown"),
    (tap("t.hasProp(total(), 'a');"), "unknown"),
    (tap("t.matchOnly(total(), {a: 1});"), "unknown"),
    (tap("t.matchSnapshot(total());"), "unknown"),
    (tap("t.resolveMatchSnapshot(total());"), "unknown"),
    (tap("t.expectUncaughtException(() => total(-1));"), "unknown"),
    (tap("t.fail();"), "unknown"),
    # tap 16's synonyms record as the method they name.
    (tap("t.throw(() => total(-1));"), "raises"),
    (tap("t.notThrow(() => total(1));"), "unknown"),
    (tap("t.ifError(err);"), "unknown"),
    (tap("t.isa(total(), 'number');"), "unknown"),
    ("import t from 'tap';\nimport { rejects } from 'tap';\n\nt.test('total', async () => {\n  rejects(total(-1));\n});\n",
     "raises"),
    ("import t from 'tap';\nimport { throws } from 'tap';\n\nt.test('total', async () => {\n  throws(() => total(-1));\n});\n",
     "raises"),
])
def test_the_other_assertions_are_recorded_with_no_strength(source, form):
    assert [(a[0], a[1]) for a in recorded(source)] == [(form, None)]


@pytest.mark.parametrize("source", [
    ava("t.pass();"), ava("t.plan(1);"), ava("t.log('x');"), ava("t.teardown(close);"), ava("t.timeout(10);"),
    ava("t.is.skip(total(), 78.75);"), ava("t.context.total = total();"),
    tap("t.pass();"), tap("t.plan(1);"), tap("t.end();"), tap("t.comment('x');"), tap("t.teardown(close);"),
])
def test_what_asserts_nothing_is_not_recorded(source):
    assert recorded(source) == []
    assert gaps(source) == []


@pytest.mark.parametrize("tpl, before, after, expected", [
    (ava, "t.is(total(), 78.75);", "t.not(total(), 78.75);", WEAKENED),
    (ava, "t.is(total(), 78.75);", "t.is(total(), 75);", (BLOCK, [("EXPECTED_VALUE_CHANGED", "high")])),
    (ava, "t.is(total(), 78.75);", "t.is.skip(total(), 78.75);", (BLOCK, [("ASSERT_REMOVED", "high")])),
    (ava, "t.deepEqual(total(), {a: 1});", "t.like(total(), {a: 1});", WEAKENED),
    (ava, "t.regex(total(), /7/);", "t.truthy(total());", WEAKENED),
    (ava, "t.throws(() => total(-1));", "", (BLOCK, [("ASSERT_REMOVED", "high")])),
    (ava, "t.true(total());", "t.is(total(), true);", (PASS, [])),
    (ava, "t.truthy(total());", "t.assert(total());", (PASS, [])),
    (tap, "t.notOk(total());", "t.ok(total());", WEAKENED),
    (tap, "t.has(total(), {a: 1});", "t.ok(total());", WEAKENED),
    (tap, "t.equal(total(), 78.75);", "", (BLOCK, [("ASSERT_REMOVED", "high")])),
    (tap, "t.same(total(), [1]);", "t.strictSame(total(), [1]);", (PASS, [])),
    (tap, "t.equals(total(), 78.75);", "t.ok(total());", WEAKENED),
    (tap, "t.same(total(), [1]);", "t.deepEqual(total(), [1]);", (PASS, [])),
    (tap, "t.deepEqual(total(), [1]);", "", (BLOCK, [("ASSERT_REMOVED", "high")])),
])
def test_rewrites_are_judged_as_their_chai_twins(tpl, before, after, expected):
    assert judge("test/value.js", tpl(before), tpl(after)) == expected


# --- Declarations, focus and the coverage inventory --------------------------------------------

def test_a_serial_test_is_a_unit():
    assert judge("test/value.js", ava("t.is(total(), 78.75);", "test.serial"), AVA_EMPTY) == DISABLED


def test_avas_focus_stays_in_its_file():
    # AVA runs each file in its own worker, so `.only` turns off no other file's test.
    assert focus_is_file_scoped(frozenset({"ava"}))
    assert not focus_is_file_scoped(frozenset({"tap"}))
    assert judge("test/value.js", ava("t.is(total(), 78.75);"), ava("t.is(total(), 78.75);", "test.only")) == (
        PASS, [])


def test_unread_and_out_of_unit_calls_are_coverage_notices():
    source = ("import test from 'ava';\n\ntest('total', t => {\n  t.snapshot(total());\n  t['is'](total(), 1);\n});\n"
              "const macro = test.macro((t, value) => { t.is(total(), value); });\n")
    assert gaps(source) == [("t.snapshot", "AVA", True), ("t['is']", "AVA", False), ("t.is", "AVA", False)]
    # tap's root test is no unit: its own assertions are notices, as a call
    # outside every test unit is for every runner.
    source = "import t from 'tap';\nimport { ok } from 'tap';\n\nt.equal(total(), 78.75);\nok(total());\n"
    assert gaps(source) == [("t.equal", "tap", False), ("ok", "tap", False)]

"""JS/TS: an arrow test callback's return annotation no longer hides its context (#480).

The binder took an arrow's parameters from the token just before `=>`. Under
`(ctx): void =>` that token is the return type, so it declared `void` as the
callback's context and never `ctx`; under `Promise<void>` it declared
nothing. No assertion on the context was read on either side, and the
coverage scan dropped those calls, so weakening, deleting or rewriting one
passed with zero findings and `no_known_gaps`. Ruling 480 (owner,
2026-10-18, issuecomment-6248630129, 「19 項全部照建議做」):

- Q1 A: the binder steps back from `=>` over a simple return type to a `:`
  and takes the paired `(...)` before it, only where an arrow can start;
  after `?`, a callee, `await` or an operator the old reading stays;
- Q2: the simple set only (names, `<`, `>`, `[`, `]`, `,`, `|`, `.`);
- Q3: a call on a test callback's first parameter, read from the callback's
  own tokens, that does not resolve is an `unresolved` coverage candidate
  when its member is an assertion of the declaring call's runner;
- Q4: in a file that imports or requires AVA or tap and not node:test, an
  undeclared `t` is unknown, with that runner's provenance.

The `.gwcase` fixtures `js_*_annotated_arrow_*` pin THREATMODEL row 159;
these pin the issue's matrix and controls, the position rule and the
readings of Q3 and Q4.
"""

from __future__ import annotations

import datetime
import json

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze
from checkwash.frontends.javascript.coverage import javascript_coverage_gaps
from checkwash.frontends.javascript.frontend import file_bindings, parse_javascript
from checkwash.report.context import ReportContext
from checkwash.report.coverage import coverage_to_json

TODAY = datetime.date(2026, 1, 1)
PATH = "tests/sum.test.ts"
SUM = 'import { sum } from "../src/sum";\n\n'
NODE = 'import { test } from "node:test";\n' + SUM
AVA = 'import test from "ava";\n' + SUM
TAP = 'import t from "tap";\n' + SUM
STRICT = "ctx.assert.strictEqual(sum(2, 2), 4);"
WEAK = "ctx.assert.ok(sum(2, 2));"
OK1 = "ctx.assert.ok(sum(1, 1));"
W = ([STRICT], [WEAK])

WEAKENED = [("ASSERT_WEAKENED", "high")]
REMOVED = [("ASSERT_REMOVED", "high")]
REWRITTEN = [("EXPECTED_VALUE_CHANGED", "high")]
DISABLED = [("TEST_DISABLED", "high")]


def _test(head: str, opening: str, lines: list[str], closing: str = "});\n") -> str:
    """`head`, a declaration up to its callback's `{`, the callback's `lines`, and `closing`."""
    return head + opening + "\n" + "".join(f"  {line}\n" for line in lines) + closing


def _pair(head: str, opening: str, edit: tuple[list[str], list[str]], closing: str = "});\n"):
    before, after = edit
    return _test(head, opening, before, closing), _test(head, opening, after, closing)


def _named(edit: tuple[list[str], list[str]], name: str) -> tuple[list[str], list[str]]:
    """The edit with the context parameter spelled `name`."""
    return tuple([line.replace("ctx", name) for line in lines] for lines in edit)


def _report(before: str, after: str, path: str = PATH):
    context = ReportContext()
    change = FileChange(path, "modified", before.encode(), after.encode())
    ir, findings, verdict = analyze([change], Config(), Contract(), [], TODAY, report_context=context)
    return verdict, sorted((f.rule, f.severity) for f in findings), context, ir


def _gaps(source: str) -> list[tuple[str, str, bool]]:
    data = source.encode()
    return [(gap.callee, gap.reason.split(" assertion candidate")[0], "no strength" in gap.reason)
            for gap in javascript_coverage_gaps(data, parse_javascript(data), PATH, "after")]


# --- the issue's rows: N1-N21 and A1 block; the controls are unchanged -----

AVA_W = (["t.is(sum(2, 2), 4);"], ["t.truthy(sum(2, 2));"])
TAP_W = (["t.equal(sum(2, 2), 4);"], ["t.ok(sum(2, 2));"])
CONCISE = 'test("s", (ctx): void => {line});\n'

ROWS = {
    "N1": (_pair(NODE, 'test("s", (ctx): void => {', W), WEAKENED),
    "N2": (_pair(NODE, 'test("s", async (ctx): Promise<void> => {', W), WEAKENED),
    "N3": (_pair('import type { TestContext } from "node:test";\n' + NODE,
                 'test("s", (ctx: TestContext): void => {', W), WEAKENED),
    "N4": (_pair(NODE, 'test("s", (context): Promise<void> | void => {', _named(W, "context")), WEAKENED),
    "N5": ((NODE + CONCISE.format(line=STRICT[:-1]), NODE + CONCISE.format(line=WEAK[:-1])), WEAKENED),
    "N6": (_pair('import { it } from "node:test";\n' + SUM, 'it("s", (ctx): void => {', W), WEAKENED),
    "N7": (_pair('import { describe, it } from "node:test";\n' + SUM,
                 'describe("d", () => {\n  it("s", (ctx): void => {', W, "  });\n});\n"), WEAKENED),
    "N9": (_pair('import test from "node:test";\n' + SUM, 'test("s", (ctx): void => {', W), WEAKENED),
    "N10": (_pair('import * as nt from "node:test";\n' + SUM, 'nt.test("s", (ctx): void => {', W), WEAKENED),
    "N11": (_pair('const { test } = require("node:test");\n' + SUM, 'test("s", (ctx): void => {', W), WEAKENED),
    "N12": (_pair(NODE, 'test("s", (ctx): void => {', ([STRICT, OK1], [STRICT])), REMOVED),
    "N13": (_pair(NODE, 'test("s", (ctx): void => {', ([STRICT, OK1], [OK1])), REMOVED),
    "N14": (_pair(NODE, 'test("s", (ctx): void => {', ([STRICT], [STRICT.replace(", 4)", ", 5)")])), REWRITTEN),
    "N15": (_pair(NODE, 'test("s", (ctx): void => {',
                  (["expect(sum(2, 2)).toBe(4);", STRICT], ["expect(sum(2, 2)).toBe(4);", WEAK])), WEAKENED),
    "N16": (_pair(AVA, 'test("s", (t): void => {', AVA_W), WEAKENED),
    "N17": (_pair(AVA, 'test("s", async (t): Promise<void> => {', AVA_W), WEAKENED),
    "N18": (_pair(AVA, 'test("s", (t): void => {',
                  (["t.is(sum(2, 2), 4);", "t.truthy(sum(1, 1));"], ["t.truthy(sum(1, 1));"])), REMOVED),
    "N19": (_pair(TAP, 't.test("s", (tt): void => {', (["tt.equal(sum(2, 2), 4);"], ["tt.ok(sum(2, 2));"])),
            WEAKENED),
    "N20": (_pair('import tap from "tap";\n' + SUM, 'tap.test("s", (t): void => {', TAP_W), WEAKENED),
    "N21": (_pair('import { test } from "tap";\n' + SUM, 'test("s", (t): void => {', TAP_W), WEAKENED),
    "A1": (_pair(AVA, 'test("s", (t): void => {',
                 (["t.assert(sum(2, 2) === 4);", "t.is(sum(1, 1), 2);"], ["t.is(sum(1, 1), 2);"])), REMOVED),
    # The controls the issue ran, in their annotated spellings.
    "C3": (_pair(NODE, 'test("s", function (ctx): void {', W), WEAKENED),
    "C4": (_pair(NODE, 'test("s", (t): void => {', _named(W, "t")), WEAKENED),
    "C5": (_pair(NODE, 'test("s", (t): void => {', _named(([STRICT, OK1], [STRICT]), "t")), REMOVED),
    "C10": (_pair('import { expect, test } from "vitest";\n' + SUM, 'test("s", (ctx): void => {',
                  (["expect(sum(2, 2)).toBe(4);"], ["expect(sum(2, 2)).toBeTruthy();"])), WEAKENED),
    "C13": (_pair('import assert from "node:assert";\n' + NODE, 'test("s", (ctx): void => {',
                  (["assert.strictEqual(sum(2, 2), 4);"], ["assert.ok(sum(2, 2));"])), WEAKENED),
    "C14": (_pair(NODE, 'test("s", (ctx): void => {', ([STRICT], ["ctx.skip();", STRICT])), DISABLED),
    "C15": (_pair(AVA, 'test("s", function (t): void {', AVA_W), WEAKENED),
    "C16": (_pair(TAP, 't.test("s", (t): void => {', TAP_W), WEAKENED),
}


@pytest.mark.parametrize("row", [*sorted(ROWS), "N8"])
def test_an_annotated_arrow_test_callbacks_assertions_are_judged(row):
    """N1-N21 and A1 blocked nothing before #480; each now blocks as the
    callback written without its annotation does, and no call is left a
    coverage gap. N8 is N1 in a `.mts` file."""
    (before, after), expected = ROWS["N1" if row == "N8" else row]
    path = "tests/sum.test.mts" if row == "N8" else PATH
    verdict, findings, context, _ir = _report(before, after, path)
    assert (verdict, findings, len(context.coverage_gaps)) == ("block", expected, 0)


# --- Q1: where an annotated arrow's parameter list is read -----------------

# `assert` is each arrow's parameter, so `assert.ok` there has no Node
# authority. Before #480 the return type was read as the parameter, and
# `assert` was the global.
POSITIONS = {
    "first in the file": "(assert): void => assert.ok(v);\n",
    "after a parenthesis": "run((assert): Map<string, number[]> => assert.ok(v));\n",
    "after a comma": "run(1, (assert): void => assert.ok(v));\n",
    "after an equals sign": "const check = (assert): void => assert.ok(v);\n",
    "after async": "const check = async (assert): Promise<void> => {\n  assert.ok(v);\n};\n",
    "after an arrow": "const curry = (x) => (assert): void => assert.ok(v);\n",
    "after a property's colon": "const checks = { check: (assert): A | B => assert.ok(v) };\n",
    "after a conditional's colon": "const check = c ? y : (assert): ns.T => assert.ok(v);\n",
    "after a bracket": "const checks = [(assert): void => assert.ok(v)];\n",
    "after a brace": "{\n  (assert): void => assert.ok(v);\n}\n",
    "after a semicolon": "run();\n(assert): void => assert.ok(v);\n",
    "after return": "function make() {\n  return (assert): void => assert.ok(v);\n}\n",
}


@pytest.mark.parametrize("position", sorted(POSITIONS))
def test_an_annotated_arrow_declares_its_parameters_where_an_arrow_can_start(position):
    source = POSITIONS[position]
    bindings = file_bindings(source.encode())
    assert bindings.callee("assert.ok", source.index("assert.ok")).kind == "unknown"


# The named misses: these keep the reading of the token before `=>`, so the
# list in parentheses declares nothing.
MISSES = {
    "after a question mark": "const check = c ? (assert): void => assert.ok(v) : z;\n",
    "after export default": "export default (assert): void => assert.ok(v);\n",
    "after yield": "function* make() {\n  yield (assert): void => assert.ok(v);\n}\n",
    "after a compound assignment": "check ||= (assert): void => assert.ok(v);\n",
    "after a type parameter list": "const check = <T>(assert: T): void => assert.ok(v);\n",
}


@pytest.mark.parametrize("position", sorted(MISSES))
def test_an_annotated_arrow_anywhere_else_keeps_the_old_reading(position):
    source = MISSES[position]
    assert file_bindings(source.encode()).is_global(("assert",), source.index("assert.ok"))


# The ruling's two controls, and the conditionals whose `:` after `)` is a
# conditional's because a `?` before it still waits: in each, `@` stays the
# arrow's parameter and `a` is not declared by it. Spelled `assert`, the
# parameter would otherwise fall to the global and gain Node authority.
CONDITIONALS = {
    "a parenthesized consequent": "cond ? (a) : @ => @.ok(v)",
    "a call as the consequent": "cond ? f(a) : @ => @.ok(v)",
    "a nested conditional": "c0 ? c1 ? y : (a) : @ => @.ok(v)",
    "an assignment as the consequent": "c ? x = (a) : @ => @.ok(v)",
    "an arrow as the consequent": "c ? () => (a) : @ => @.ok(v)",
}


@pytest.mark.parametrize("shape", sorted(CONDITIONALS))
def test_a_conditional_before_an_arrow_keeps_the_arrows_parameter(shape):
    for name in ("b", "assert"):
        source = "const pick = " + CONDITIONALS[shape].replace("@", name) + ";\n"
        bindings = file_bindings(source.encode())
        at = source.index(name + ".ok")
        assert not bindings.is_global((name,), at), name
        assert bindings.is_global(("a",), at), name
        assert bindings.callee(name + ".ok", at).kind == "unknown", name


@pytest.mark.parametrize("source, call, kind", [
    pytest.param(NODE + 'test("s", (ctx): void => {\n  ctx.assert.ok(v);\n});\n', "ctx.assert.ok", "node_method",
                 id="node-test"),
    pytest.param(AVA + 'test("s", async (t): Promise<void> => {\n  t.is(v, 1);\n});\n', "t.is", "ava_method",
                 id="AVA"),
    pytest.param(TAP + 't.test("s", (tt): void => {\n  tt.equal(v, 1);\n});\n', "tt.equal", "tap_method", id="tap"),
    pytest.param(NODE + "const check = (t): void => {\n  t.assert.ok(v);\n};\n", "t.assert.ok", "unknown",
                 id="a helper"),
    pytest.param(NODE + 'test("s", () => {\n  const check = (t): void => t.assert.ok(v);\n  check(1);\n});\n',
                 "t.assert.ok", "unknown", id="a helper in a test"),
])
def test_only_a_test_callbacks_annotated_parameter_is_its_context(source, call, kind):
    """The runner's context for a test callback's first parameter, as without
    the annotation; an annotated arrow that is no test callback gains none."""
    assert file_bindings(source.encode()).callee(call, source.index(call)).kind == kind


# --- Q3: a context the binder does not read is still a coverage candidate -

NODE_UNREAD = [STRICT, 'ctx.diagnostic("x");']
UNREAD = {
    "node-test object type": (NODE, 'test("s", (ctx): { ok: boolean } => {', NODE_UNREAD, "ctx.assert.strictEqual"),
    "node-test parenthesized type": (NODE, 'test("s", (ctx): (void) => {', NODE_UNREAD, "ctx.assert.strictEqual"),
    "node-test function object type": (NODE, 'test("s", function (ctx): { ok: boolean } {', NODE_UNREAD,
                                       "ctx.assert.strictEqual"),
    "AVA t": (AVA, 'test("s", (t): { ok: boolean } => {', ["t.is(sum(2, 2), 4);", "t.plan(1);"], "t.is"),
    "AVA other name": (AVA, 'test("s", (tt): { ok: boolean } => {', ["tt.is(sum(2, 2), 4);", "tt.plan(1);"], "tt.is"),
    "tap": (TAP, 't.test("s", (tt): { ok: boolean } => {', ["tt.equal(sum(2, 2), 4);", "tt.end();"], "tt.equal"),
}


@pytest.mark.parametrize("case", sorted(UNREAD))
def test_a_context_call_the_binder_leaves_unread_is_an_unresolved_candidate(case):
    """Only the call whose member is one of the runner's assertions."""
    head, opening, lines, callee = UNREAD[case]
    assert _gaps(_test(head, opening, lines)) == [(callee, "unresolved", False)]


def test_a_nested_function_that_declares_the_same_name_has_its_own_parameter():
    source = _test(NODE, 'test("s", (ctx): { ok: boolean } => {', ["[1].forEach((ctx) => ctx.assert.ok(ctx));"])
    assert _gaps(source) == []


@pytest.mark.parametrize("signature", ["(ctx): { ok: boolean } =>", "(ctx): (void) =>"], ids=["N22", "N23"])
def test_an_unread_return_type_passes_but_the_report_is_incomplete(signature):
    """Q2 leaves N22 and N23 unread; Q3 makes their silence visible."""
    before, after = _pair(NODE, f'test("s", {signature} {{', W)
    verdict, findings, context, ir = _report(before, after)
    assert (verdict, findings) == ("pass", [])
    assert [(gap.side, gap.callee, gap.reason.split(" ")[0]) for gap in context.coverage_gaps] == [
        ("before", "ctx.assert.strictEqual", "unresolved"), ("after", "ctx.assert.ok", "unresolved")]
    assert json.loads(coverage_to_json(ir, context))["status"] == "incomplete"


# --- Q4: an undeclared `t` follows the runners the file names -------------

HELPER = "function check(value) {\n  t.is(value, 4);\n}\n"


@pytest.mark.parametrize("head, kind, found", [
    pytest.param('import test from "ava";\n', "unknown", [("t.is", "unresolved", False)], id="AVA import"),
    pytest.param('const test = require("ava");\n', "unknown", [("t.is", "unresolved", False)], id="AVA require"),
    pytest.param('import tap from "tap";\n', "unknown", [("t.is", "unresolved", False)], id="tap import"),
    pytest.param('const { test } = require("tap");\n', "unknown", [("t.is", "unresolved", False)],
                 id="tap require"),
    pytest.param('import test from "ava";\nimport { mock } from "node:test";\n', "context", [],
                 id="AVA and node-test"),
    pytest.param('import { test } from "node:test";\n', "context", [], id="node-test"),
    pytest.param("", "context", [], id="no runner"),
    pytest.param('const test = require("tape");\n', "context", [], id="tape"),
])
def test_an_undeclared_t_follows_the_runners_the_file_names(head, kind, found):
    """Where only AVA or tap is named, `t` is no node:test context, and `t.is`
    is an unresolved candidate instead of being dropped."""
    source = head + HELPER
    assert file_bindings(source.encode()).resolve("t", source.index("t.is")).kind == kind
    assert _gaps(source) == found


@pytest.mark.parametrize("head, kind", [
    pytest.param('import test from "ava";\n', "unknown", id="AVA"),
    pytest.param('import { test } from "node:test";\n', "node_method", id="node-test"),
])
def test_a_node_test_assertion_on_an_undeclared_t_keeps_its_authority_only_beside_node_test(head, kind):
    """The cost Q4 names: in an AVA or tap file it is not read."""
    source = head + "function check(value) {\n  t.assert.ok(value);\n}\n"
    assert file_bindings(source.encode()).callee("t.assert.ok", source.index("t.assert")).kind == kind

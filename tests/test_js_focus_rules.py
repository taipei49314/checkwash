"""Which units a focused JS/TS file stops follows its runner (#196 187.2, 187.1).

The expected sets are runs, not the implementation: shapes S1-S9 under Jest
30.5.2, Vitest 5.0.3, Mocha 12.0.3, Jasmine 7.0.0 and Node 22.22
(`--test-only`, and `--experimental-test-isolation=none`). Jest passes a
block's focus to the tests directly in it unless one of them is focused
itself; Vitest, Jasmine and node:test run only the innermost focus; Mocha is
stricter still (S4, S7), which stays unreported. Jest's rule is the most
permissive, so it judges Jest and every runner that is not known.
"""

import datetime
import random

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze
from checkwash.frontends.javascript.frontend import parse_javascript
from checkwash.frontends.javascript.runners import focus_is_innermost

# name -> (source, the units Jest runs, the units Vitest, Jasmine and
# node:test run)
SHAPES = {
    "S1": ('describe.only("block", () => {\n'
           '  it.only("focused", () => {});\n'
           '  it("plainInBlock", () => {});\n'
           '});\n'
           'it("outside", () => {});\n',
           {"focused"}, {"focused"}),
    "S2": ('describe.only("block", () => {\n'
           '  it("plainInBlock", () => {});\n'
           '});\n'
           'it("outside", () => {});\n',
           {"plainInBlock"}, {"plainInBlock"}),
    "S3": ('describe.only("outer", () => {\n'
           '  describe("inner", () => {\n'
           '    it.only("focused", () => {});\n'
           '    it("plainInner", () => {});\n'
           '  });\n'
           '  it("plainOuter", () => {});\n'
           '});\n'
           'it("outside", () => {});\n',
           {"focused", "plainOuter"}, {"focused"}),
    "S4": ('describe("outer", () => {\n'
           '  describe.only("inner", () => {\n'
           '    it("innerTest", () => {});\n'
           '  });\n'
           '  it.only("focusedOuter", () => {});\n'
           '  it("plainOuter", () => {});\n'
           '});\n'
           'it("outside", () => {});\n',
           {"focusedOuter", "innerTest"}, {"focusedOuter", "innerTest"}),
    "S5": ('describe.only("A", () => {\n'
           '  it("a1", () => {});\n'
           '});\n'
           'describe.only("B", () => {\n'
           '  it.only("b1", () => {});\n'
           '  it("b2", () => {});\n'
           '});\n'
           'it("outside", () => {});\n',
           {"a1", "b1"}, {"a1", "b1"}),
    "S6": ('describe.only("outer", () => {\n'
           '  describe.only("inner", () => {\n'
           '    it("i1", () => {});\n'
           '  });\n'
           '  it("o1", () => {});\n'
           '});\n'
           'it("outside", () => {});\n',
           {"i1", "o1"}, {"i1"}),
    "S7": ('it.only("top", () => {});\n'
           'describe.only("block", () => {\n'
           '  it("inBlock", () => {});\n'
           '});\n'
           'it("outside", () => {});\n',
           {"top", "inBlock"}, {"top", "inBlock"}),
    "S8": ('describe.only("outer", () => {\n'
           '  describe("inner", () => {\n'
           '    it("plainInner", () => {});\n'
           '  });\n'
           '  it.only("focusedOuter", () => {});\n'
           '});\n'
           'it("outside", () => {});\n',
           {"focusedOuter", "plainInner"}, {"focusedOuter"}),
    "S9": ('describe("outer", () => {\n'
           '  it.only("focused", () => {});\n'
           '  it("plain", () => {});\n'
           '});\n'
           'it("outside", () => {});\n',
           {"focused"}, {"focused"}),
}


def _runs(source, innermost=None):
    """The units no focus stops, under the rule `innermost` names."""
    rule = None if innermost is None else (lambda: innermost)
    parsed = parse_javascript(source.encode(), rule)
    return {unit.qualname for unit in parsed.units
            if all(marker.name != "test.unfocused" for marker in unit.side.markers)}


def _cited(source, unit, innermost=False):
    """The focus cited on `unit`'s `test.unfocused` marker."""
    parsed = parse_javascript(source.encode(), lambda: innermost)
    found, = (u for u in parsed.units if u.qualname == unit)
    marker, = (m for m in found.side.markers if m.name == "test.unfocused")
    return marker.text, source[marker.span[0]:marker.span[1]]


@pytest.mark.parametrize("name", sorted(SHAPES))
def test_jest_rule_judges_a_runner_that_is_not_known(name):
    source, jest, _innermost = SHAPES[name]
    assert _runs(source) == jest
    assert _runs(source, innermost=False) == jest


@pytest.mark.parametrize("name", sorted(SHAPES))
def test_innermost_rule_judges_a_proven_vitest_jasmine_or_node_file(name):
    source, _jest, innermost = SHAPES[name]
    assert _runs(source, innermost=True) == innermost


def test_a_focused_sibling_inside_a_focused_block_stops_under_every_runner():
    # Probe 187.2a: the shape the old rule left silent under every runner.
    source = SHAPES["S1"][0]
    assert "plainInBlock" not in _runs(source)
    assert "plainInBlock" not in _runs(source, innermost=True)


@pytest.mark.parametrize("name,still_read_as_running", [
    ("S4", "innerTest"),  # Mocha drops a block's inner blocks beside its own focused test
    ("S7", "inBlock"),
])
def test_mochas_stricter_filter_stays_unreported(name, still_read_as_running):
    # A residual (THREATMODEL row 108): Mocha's Suite.filterOnly keeps only a
    # block's focused tests when it has any, dropping its inner blocks.
    assert still_read_as_running in _runs(SHAPES[name][0], innermost=True)


@pytest.mark.parametrize("evidence,expected", [
    ({"vitest"}, True), ({"mocha"}, True), ({"jasmine"}, True), ({"node"}, True),
    ({"vitest", "node"}, True), ({"jest"}, False), ({"jest", "vitest"}, False),
    ({"bun"}, False), ({"deno"}, False), (set(), False), (None, False),
])
def test_innermost_focus_needs_evidence_of_innermost_runners_only(evidence, expected):
    assert focus_is_innermost(None if evidence is None else frozenset(evidence)) is expected


def test_the_rule_is_asked_only_when_the_file_holds_focus():
    asked = []

    def rule():
        asked.append(True)
        return True

    parse_javascript(b'describe("block", () => { it("plain", () => {}); });\n', rule)
    assert asked == []
    parse_javascript(SHAPES["S6"][0].encode(), rule)
    assert asked == [True]


def test_the_cited_focus_is_one_that_stops_the_unit():
    # Not the enclosing describe.only, which keeps the unit: the focus beside it.
    assert _cited(SHAPES["S1"][0], "plainInBlock") == ("it.only", 'it.only("focused"')
    assert _cited(SHAPES["S5"][0], "b2") == ("it.only", 'it.only("b1"')
    assert _cited(SHAPES["S6"][0], "o1", innermost=True) == ("describe.only", 'describe.only("inner"')
    assert _cited(SHAPES["S8"][0], "plainInner", innermost=True) == ("it.only", 'it.only("focusedOuter"')
    # With no focused block around it, the unit cites the file's first focus, as before.
    assert _cited(SHAPES["S5"][0], "outside") == ("describe.only", 'describe.only("A"')


def test_a_focused_table_is_a_focused_sibling():
    # Measured: Jest and Vitest both skip `plain`.
    source = ('describe.only("block", () => {\n'
              '  it.only.each([[1]])("row %i", (n) => {});\n'
              '  it("plain", () => {});\n'
              '});\n')
    assert "plain" not in _runs(source)
    assert "plain" not in _runs(source, innermost=True)


NODE_SUBTESTS = (
    'const test = require("node:test");\n'
    'test.only("outer", async (t) => {\n'
    '  await t.test("s1", () => {});\n'
    '  await t.test("s2", { only: true }, () => {});\n'
    '});\n'
    'test("outside", () => {});\n'
)


@pytest.mark.parametrize("innermost", [False, True])
def test_every_subtest_of_a_focused_test_runs(innermost):
    # Measured under --test-only: node:test runs s1 beside the focused s2.
    assert _runs(NODE_SUBTESTS, innermost) == {"outer", "s1", "s2"}


def test_focus_inside_a_test_does_not_narrow_the_block_around_it():
    # Measured under --test-only: node:test meets `s` only once `t` runs, so
    # describe.only still runs `t` and `u`.
    source = ('const { describe, test } = require("node:test");\n'
              'describe.only("block", () => {\n'
              '  test("t", async () => {\n'
              '    await test.only("s", () => {});\n'
              '  });\n'
              '  test("u", () => {});\n'
              '});\n')
    assert _runs(source, innermost=True) == {"t", "s", "u"}


def _shape(rng, depth=0):
    """A random list of describe/it nodes; every block holds a test."""
    nodes = []
    for _ in range(rng.randint(1, 3)):
        if depth < 3 and rng.random() < 0.4:
            nodes.append(("describe", rng.random() < 0.3, _shape(rng, depth + 1)))
        else:
            nodes.append(("it", rng.random() < 0.25, []))
    return nodes


def _source(nodes, names, indent=""):
    lines = []
    for kind, focus, children in nodes:
        name = f"n{len(names)}"
        names.append((kind, name))
        word = kind + (".only" if focus else "")
        if kind == "describe":
            lines.append(f'{indent}{word}("{name}", () => {{')
            lines += _source(children, names, indent + "  ")
            lines.append(f"{indent}}});")
        else:
            lines.append(f'{indent}{word}("{name}", () => {{}});')
    return lines


def _reference(nodes, rule):
    """The rules, read off the tree rather than the source.

    Old: a test runs when it or a block around it is focused. Jest: a block's
    mode is its own focus or its parent's, and it passes the mode to its
    direct tests unless one of them is focused. Innermost: a focused node
    with a focused descendant gives way to it.
    """
    names = []
    _source(nodes, names)
    order = iter(name for _kind, name in names)
    runs = set()

    def has_focus(children):
        return any(focus or has_focus(grand) for _kind, focus, grand in children)

    def walk(children, inherited):
        direct_focus = any(kind == "it" and focus for kind, focus, _ in children)
        for kind, focus, grand in children:
            name = next(order)
            if kind == "describe":
                keeps = focus and not has_focus(grand) if rule == "innermost" else focus
                walk(grand, inherited or keeps)
            elif focus or (inherited and not (rule == "jest" and direct_focus)):
                runs.add(name)
    walk(nodes, False)
    return runs


def test_random_shapes_match_the_reference_and_order_the_rules():
    rng = random.Random(187)
    checked = 0
    for _ in range(400):
        nodes = _shape(rng)
        names = []
        source = "\n".join(_source(nodes, names)) + "\n"
        if "only" not in source:
            continue
        jest, innermost = _runs(source), _runs(source, innermost=True)
        assert jest == _reference(nodes, "jest"), source
        assert innermost == _reference(nodes, "innermost"), source
        # Each rule stops at least what the old rule did, and the innermost
        # rule at least what Jest's does: Jest's never reports more.
        assert innermost <= jest <= _reference(nodes, "old"), source
        checked += 1
    assert checked > 200


# --- through the engine ------------------------------------------------------

TODAY = datetime.date(2026, 10, 3)
NESTED_BASE = (
    'describe.only("billing", () => {\n'
    '  describe("rounding", () => {\n'
    '    it("rounds", () => { expect(round(2.5)).toBe(3); });\n'
    '  });\n'
    '  it("total", () => { expect(total()).toBe(78.75); });\n'
    '});\n'
)
NESTED_HEAD = NESTED_BASE.replace('describe("rounding"', 'describe.only("rounding"')
MESSAGE = ("total: focus elsewhere in this file; a runner that honours it stops this unit "
           "(node:test only under --test-isolation=none or --test-only) (test.unfocused)")


def _nested(header, path="test/billing.spec.js", manifest=None, base_header=None):
    base_header = header if base_header is None else base_header
    change = FileChange(path, "modified", (base_header + NESTED_BASE).encode(), (header + NESTED_HEAD).encode())
    snapshot = {} if manifest is None else {"package.json": manifest}
    return analyze([change], Config(), Contract(), [], TODAY, root_reader=snapshot.get)


def _summary(findings):
    return [(f.rule, f.severity, f.path, f.unit) for f in findings]


@pytest.mark.parametrize("header,path,manifest,stops", [
    ('import { describe, it, expect } from "vitest";\n', "test/billing.spec.js", None, True),
    ('const { describe, it } = require("node:test");\n', "test/billing.test.js", None, True),
    ("", "test/billing.spec.js", b'{"devDependencies": {"vitest": "^5"}}', True),
    ("", "test/billing.spec.js", b'{"devDependencies": {"mocha": "^12"}}', True),
    ("", "spec/billing.spec.js", b'{"devDependencies": {"jasmine": "^7"}}', True),
    ('import { describe, it, expect } from "@jest/globals";\n', "test/billing.spec.js", None, False),
    ("", "test/billing.spec.js", b'{"devDependencies": {"jest": "^30"}}', False),
    ("", "test/billing.spec.js", None, False),
    ("", "test/billing.spec.js", b'{"devDependencies": {"jest": "^30", "vitest": "^5"}}', False),
    ('import { describe, it, expect } from "bun:test";\n', "test/billing.spec.js", None, False),
])
def test_runner_evidence_chooses_the_rule(header, path, manifest, stops):
    _ir, findings, verdict = _nested(header, path, manifest)
    if stops:
        assert verdict == "block"
        assert _summary(findings) == [("TEST_DISABLED", "high", path, "total")]
    else:
        assert (_summary(findings), verdict) == ([], "pass")


def test_the_unfocused_message_states_the_runner_condition():
    _ir, findings, _verdict = _nested('import { describe, it, expect } from "vitest";\n')
    finding, = findings
    assert finding.message == MESSAGE
    assert finding.after is not None and finding.after.text == "describe.only"


def test_each_side_is_judged_under_its_own_runner():
    # The shape is already S6 on both sides; only the runner changes.
    vitest = 'import { describe, it, expect } from "vitest";\n'
    jest = 'import { describe, it, expect } from "@jest/globals";\n'
    both = FileChange("test/billing.spec.js", "modified", (jest + NESTED_HEAD).encode(),
                      (vitest + NESTED_HEAD).encode())
    _ir, findings, verdict = analyze([both], Config(), Contract(), [], TODAY, root_reader={}.get)
    assert verdict == "block"
    assert _summary(findings) == [("TEST_DISABLED", "high", "test/billing.spec.js", "total")]
    back = FileChange("test/billing.spec.js", "modified", (vitest + NESTED_HEAD).encode(),
                      (jest + NESTED_HEAD).encode())
    _ir, findings, verdict = analyze([back], Config(), Contract(), [], TODAY, root_reader={}.get)
    assert (_summary(findings), verdict) == ([], "pass")

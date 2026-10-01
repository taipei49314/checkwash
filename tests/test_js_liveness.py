"""One liveness definition for every JS/TS declaration level (#176, #178).

A unit stops running when it, or a declaration whose callback encloses it, is
skipped, conditionally skipped or inverted, or when another declaration in the
file is focused. The spellings below come from the Jest, Vitest, Mocha and
node:test documentation, not from the frontend's own tables.
"""

import datetime

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze
from checkwash.frontends.javascript.frontend import parse_javascript

DATE = datetime.date(2026, 10, 1)
BODY = "expect(total()).toBe(5);"
UNIT = 'it("computes", () => { ' + BODY + " });"


def _markers(source):
    return {unit.qualname: [marker.name for marker in unit.side.markers]
            for unit in parse_javascript(source.encode()).units}


def _analyze(before, after, path="tests/liveness.test.js"):
    return analyze([FileChange(path, "modified", before.encode(), after.encode())],
                   Config(), Contract(), [], DATE)


@pytest.mark.parametrize("block", [
    'describe.skip("group", () => {{ {inner} }});',
    'xdescribe("group", () => {{ {inner} }});',
    'suite.skip("group", () => {{ {inner} }});',
    'context.skip("group", () => {{ {inner} }});',
    'xcontext("group", () => {{ {inner} }});',
    'describe.todo("group", () => {{ {inner} }});',
    'describe("group", {{ skip: true }}, () => {{ {inner} }});',
    'describe("group", {{ skip: "tracked upstream" }}, () => {{ {inner} }});',
    'describe("group", {{ todo: true }}, () => {{ {inner} }});',
    'describe.skipIf(true)("group", () => {{ {inner} }});',
    'describe.runIf(false)("group", () => {{ {inner} }});',
    'describe.concurrent.skip("group", () => {{ {inner} }});',
    'describe.skip.each([[1]])("group %i", () => {{ {inner} }});',
])
def test_a_block_disable_reaches_every_nested_unit(block):
    inner = 'describe("inner", () => { ' + UNIT + " });"
    assert _markers(block.format(inner=inner)) == {"computes": ["test.skip"]}


def test_a_tagged_template_table_keeps_its_block_liveness():
    source = "xdescribe.each`\n  value\n  ${1}\n`(\"group $value\", () => { " + UNIT + " });"
    assert _markers(source) == {"computes": ["test.skip"]}


@pytest.mark.parametrize("declaration,expected", [
    ('test.skip("computes", () => {{ {body} }});', ["test.skip"]),
    ('it.todo("computes", () => {{ {body} }});', ["test.skip"]),
    ('xit("computes", () => {{ {body} }});', ["test.skip"]),
    ('test.concurrent.skip("computes", () => {{ {body} }});', ["test.skip"]),
    ('test("computes", {{ skip: true }}, () => {{ {body} }});', ["test.skip"]),
    ('test("computes", {{ "todo": "later" }}, () => {{ {body} }});', ["test.skip"]),
    ('test("computes", {{ skip: !0 }}, () => {{ {body} }});', ["test.skip"]),
    ('test("computes", () => {{ {body} }}, {{ skip: true }});', ["test.skip"]),
    ('test.skipIf(1)("computes", () => {{ {body} }});', ["test.skip"]),
    ('it.fails("computes", () => {{ {body} }});', ["test.fails"]),
    ('test.failing("computes", () => {{ {body} }});', ["test.fails"]),
    ('test("computes", {{ fails: true }}, () => {{ {body} }});', ["test.fails"]),
    ('test.skipIf(isWindows)("computes", () => {{ {body} }});', ["test.skipIf(isWindows)"]),
    ('test.runIf(isLinux)("computes", () => {{ {body} }});', ["test.skipIf(!(isLinux))"]),
    ('test("computes", {{ skip: process.platform === "win32" }}, () => {{ {body} }});',
     ['test.skipIf(process.platform==="win32")']),
    ('test("computes", {{ skip: false, timeout: 100 }}, () => {{ {body} }});', []),
    ('test("computes", {{ skip: 0, todo: "", only: null }}, () => {{ {body} }});', []),
    ('test.concurrent("computes", () => {{ {body} }});', []),
    ('test.runIf(true)("computes", () => {{ {body} }});', []),
    ('test.skipIf(false)("computes", () => {{ {body} }});', []),
    ('it.only("computes", () => {{ {body} }});', []),
])
def test_unit_liveness_spellings(declaration, expected):
    unit, = parse_javascript(declaration.format(body=BODY).encode()).units
    assert unit.qualname == "computes"
    assert [marker.name for marker in unit.side.markers] == expected
    assert [assertion.left for assertion in unit.side.assertions] == ["total()"]


def test_existing_skip_spellings_keep_their_marker_evidence():
    unit, = parse_javascript(b'xit("computes", () => {});').units
    marker, = unit.side.markers
    assert (marker.name, marker.text, marker.span) == ("test.skip", "xit", (0, len('xit("computes"')))


def test_a_skip_inside_a_skipped_block_is_one_state():
    source = 'describe.skip("group", () => { it.skip("computes", () => {}); });'
    unit, = parse_javascript(source.encode()).units
    assert [(marker.name, marker.text) for marker in unit.side.markers] == [("test.skip", "describe.skip")]


def test_comments_do_not_hide_an_options_key():
    source = 'test("computes", { /* why */ skip: true /* tracked */ }, () => { ' + BODY + " });"
    assert _markers(source) == {"computes": ["test.skip"]}


def test_focus_turns_off_every_unit_outside_a_focused_declaration():
    source = (
        'describe("billing", () => {\n'
        '  it("taxed", () => { expect(total()).toBe(5); });\n'
        '  it.only("rounded", () => { expect(round()).toBe(1); });\n'
        "});\n"
        'describe.only("cart", () => {\n'
        '  it("empty", () => { expect(empty()).toBe(0); });\n'
        '  describe("nested", () => { it("deep", () => { expect(deep()).toBe(2); }); });\n'
        "});\n"
        'it("loose", () => { expect(loose()).toBe(3); });\n'
    )
    units = {unit.qualname: unit for unit in parse_javascript(source.encode()).units}
    assert {name: [marker.name for marker in unit.side.markers] for name, unit in units.items()} == {
        "taxed": ["test.unfocused"], "rounded": [], "empty": [], "deep": [],
        "loose": ["test.unfocused"],
    }
    # The evidence is the focus that turned the unit off, not the unit itself.
    assert units["taxed"].side.markers[0].text == "it.only"


@pytest.mark.parametrize("focus", [
    'it.only("focused", () => {});',
    'fit("focused", () => {});',
    'test.only("focused", () => {});',
    'test("focused", { only: true }, () => {});',
    'test.concurrent.only("focused", () => {});',
    'test.only.each([[1]])("focused %i", () => {});',
    'describe.only("focused", () => {});',
    'fdescribe("focused", () => {});',
    'suite.only("focused", () => {});',
    'context.only("focused", () => {});',
    'describe("focused", { only: true }, () => {});',
    # A computed title still declares a test when the callback is inline.
    'fit(name, () => {});',
])
def test_every_focus_spelling_turns_off_the_rest(focus):
    assert _markers(UNIT + "\n" + focus)["computes"] == ["test.unfocused"]


@pytest.mark.parametrize("lookalike", [
    'test("other", { only: false }, () => {});',
    "const focus = describe.only;",
    '// it.only("commented", () => {});',
    'const sample = "fit(\\"focused\\", () => {});";',
    'model.fit("weights", data);',
    "function fit(model, data) { return model; }",
    "const trainer = { fit(data) { return data; } };",
    # A helper named `fit`, called or declared with a TS return type, has
    # neither a literal title nor an inline callback.
    "const line = fit(points);",
    "interface Model { fit(x: number[]): Model; }",
    "class Stub { fit(x: number[]): Stub { return this; } }",
])
def test_focus_lookalikes_turn_nothing_off(lookalike):
    assert _markers(UNIT + "\n" + lookalike)["computes"] == []


def test_a_skipped_unit_outside_the_focus_lists_both_reasons():
    # Every reason is its own marker, as stacked Python markers are, so a
    # unit re-enabled under a committed `.only` loses one and gains none.
    source = 'it.skip("computes", () => {});\nit.only("other", () => {});'
    assert _markers(source) == {"computes": ["test.skip", "test.unfocused"], "other": []}


@pytest.mark.parametrize("callback,expected", [
    ("(t) => { t.skip(); BODY }", ["test.skip"]),
    ('(t) => { t.todo("later"); BODY }', ["test.skip"]),
    ('async (context) => { context.skip("flaky"); BODY }', ["test.skip"]),
    ("function () { this.skip(); BODY }", ["test.skip"]),
    ("(t) => { if (process.env.CI) { t.skip(); } BODY }", ["test.skip"]),
    ("(ctx) => { ctx.skip(isWindows); BODY }", ["test.skipIf(isWindows)"]),
    ('(t) => { t.diagnostic("note"); BODY }', []),
    ("() => { this.skip(); BODY }", []),
    ("(t) => { const later = () => { t.skip(); }; BODY }", []),
    ("(t) => { other.skip(); BODY }", []),
    ("({ skip }) => { skip(); BODY }", []),
    # tap's `t.skip(name, fn)` declares a skipped subtest; it skips nothing here.
    ('(t) => { t.skip("handles BOM later", (t) => { t.end(); }); BODY }', []),
    ('(t) => { t.todo("streams", async function (t) { t.end(); }); BODY }', []),
])
def test_imperative_skips_on_the_callbacks_own_context(callback, expected):
    source = 'test("computes", ' + callback.replace("BODY", BODY) + ");"
    unit, = parse_javascript(source.encode()).units
    assert [marker.name for marker in unit.side.markers] == expected


def test_describe_skip_blocks_exactly_like_the_it_skip_control():
    before = 'describe("billing", () => {\n  ' + UNIT + "\n});\n"
    for after in (before.replace("describe(", "describe.skip("), before.replace("it(", "it.skip(")):
        _ir, findings, verdict = _analyze(before, after)
        assert (verdict, [(f.rule, f.severity, f.unit) for f in findings]) == (
            "block", [("TEST_DISABLED", "high", "computes")],
        )


@pytest.mark.parametrize("before,after", [
    ('describe.skip("billing", () => {\n  ' + UNIT + "\n});\n",
     'describe("billing", () => {\n  ' + UNIT + "\n});\n"),
    (UNIT + '\nit.only("other", () => { expect(other()).toBe(1); });\n',
     UNIT + '\nit("other", () => { expect(other()).toBe(1); });\n'),
    ('describe("billing", () => {\n  ' + UNIT + "\n});\n",
     'describe.concurrent("invoices", () => {\n  ' + UNIT + "\n});\n"),
    (UNIT + "\n", UNIT.replace("it(", "it.concurrent(") + "\n"),
    (UNIT + "\n", UNIT.replace("it(", "it.only(") + "\n"),
    # Re-enabled while a committed `.only` still holds the focus: the unit
    # ran in neither revision, so nothing was disabled.
    (UNIT.replace("it(", "it.skip(") + '\nit.only("other", () => { expect(other()).toBe(1); });\n',
     UNIT + '\nit.only("other", () => { expect(other()).toBe(1); });\n'),
])
def test_reenabling_unfocusing_renaming_and_neutral_modifiers_stay_silent(before, after):
    _ir, findings, verdict = _analyze(before, after)
    assert (findings, verdict) == ([], "pass")


@pytest.mark.parametrize("target,outcome", [
    ('describe("moved", () => {\n  ' + UNIT + "\n});\n", ("pass", "info")),
    ('describe.skip("moved", () => {\n  ' + UNIT + "\n});\n", ("block", "high")),
])
def test_a_unit_moved_into_a_skipped_block_earns_no_move_credit(target, outcome):
    changes = [
        FileChange("tests/a.test.js", "modified", (UNIT + "\n").encode(), b"// moved to b\n"),
        FileChange("tests/b.test.js", "added", None, target.encode()),
    ]
    _ir, findings, verdict = analyze(changes, Config(), Contract(), [], DATE)
    assert (verdict, [(f.rule, f.severity) for f in findings]) == (
        outcome[0], [("TEST_DISABLED", outcome[1])],
    )


@pytest.mark.parametrize("before,after", [
    ('test("computes", () => { ' + BODY + " });\n",
     'test("computes", { skip: process.platform === "win32" }, () => { ' + BODY + " });\n"),
    ('describe("billing", () => {\n  ' + UNIT + "\n});\n",
     'describe.skipIf(process.platform === "win32")("billing", () => {\n  ' + UNIT + "\n});\n"),
])
def test_a_platform_gate_gets_no_compat_credit(before, after):
    """The current answer to an open maintainer question (PR #187): JS
    conditions are not evaluated, so an honest platform gate on a test-only
    diff blocks where Python `skipif(sys.platform == ...)` holds at warn.
    Change this with the ruling, not before it."""
    _ir, findings, verdict = _analyze(before, after)
    assert (verdict, [(f.rule, f.severity, f.unit) for f in findings]) == (
        "block", [("TEST_DISABLED", "high", "computes")],
    )

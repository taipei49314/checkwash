"""Regression matrix for real skip names and non-code declarations (#159)."""

import pytest

from checkwash.detectors.test_disabled import detect
from checkwash.frontends.javascript.frontend import parse_javascript
from checkwash.ir.diffalign import align_file
from checkwash.ir.model import DiffGlobals, IR


@pytest.mark.parametrize("callee", ["test.skip", "it.skip", "test.todo", "it.todo", "xtest", "xit"])
@pytest.mark.parametrize("quote", ["'", '"', "`"])
def test_skip_declarations_keep_the_real_name(callee, quote):
    source = f"{callee}({quote}real name{quote}, () => {{ expect(x).toBe(1); }});"
    unit, = parse_javascript(source.encode()).units
    assert unit.qualname == "real name"
    assert [m.name for m in unit.side.markers] == ["test.skip"]
    assert len(unit.side.assertions) == 1


@pytest.mark.parametrize("noise", [
    '// use test.skip here',
    'const mode = test.skip;',
    '// test.skip("fake", () => {});',
    '/* it("fake", () => {}); */',
    "const sample = 'test(\"fake\", () => {});';",
    'const sample = `test("fake", () => {});`;',
    '$it("fake", () => {});',
    '$test.skip("fake", () => {});',
])
def test_non_declarations_do_not_create_units(noise):
    parsed = parse_javascript((noise + '\ntest("real", () => {});').encode())
    assert [(u.qualname, u.side.markers) for u in parsed.units] == [("real", [])]


def test_comments_and_literals_cannot_supply_an_oracle():
    parsed = parse_javascript(b'''test("real", () => {
        // expect(fake()).toBe(1);
        /* expect(fake()).toBe(1); */
        const sample = "expect(fake()).toBe(1);";
        const template = `expect(fake()).toBe(1);`;
        $expect(fake()).toBe(1);
        expect(real()).toBe(1);
    });''')
    assert [a.left for a in parsed.units[0].side.assertions] == ["real()"]


def test_new_skip_pairs_by_name_even_when_the_body_changes():
    before = parse_javascript(b'test("real", () => { expect(x).toBe(1); });')
    after = parse_javascript(b'test.skip("real", () => { expect(other()).toBe(2); });')
    file = align_file("example.test.js", "test", "modified", before, after)
    unit, = file.units
    assert unit.match == "by_name"
    assert unit.delta.markers_added == ["test.skip"]
    findings = detect(IR(base="base", head="head", files=[file], globals=DiffGlobals()))
    assert len(findings) == 1
    assert findings[0].rule == "TEST_DISABLED"


def test_escaped_quote_in_a_skip_name():
    unit, = parse_javascript(b'test.skip("say \\"hello\\"", () => {});').units
    assert unit.qualname == 'say \\"hello\\"'


def test_empty_skip_name_is_preserved():
    unit, = parse_javascript(b'test.skip("", () => {});').units
    assert unit.qualname == ""


@pytest.mark.parametrize("expression", ["/'/", '/"/', '/["\\/]/g',
                                        '/test("fake", /', '/expect(x).toBe(1)/'])
def test_regex_literals_do_not_create_or_hide_units(expression):
    parsed = parse_javascript((f"const inert = {expression};\n"
                               'test("real", () => { expect(value).toBe(1); });').encode())
    assert [u.qualname for u in parsed.units] == ["real"]
    assert [a.left for a in parsed.units[0].side.assertions] == ["value"]


@pytest.mark.parametrize("prefix", ["return ", "if (flag) ", "while (flag) ", "x = ", "fn("])
def test_regex_start_context_keeps_literal_declarations_inert(prefix):
    parsed = parse_javascript((prefix + '/test("fake", /;\ntest("real", () => {});').encode())
    assert [u.qualname for u in parsed.units] == ["real"]


@pytest.mark.parametrize("left", ["value", "value++", "value--", "{}", "({})"])
def test_division_does_not_hide_a_real_test_call(left):
    parsed = parse_javascript((f'const x = {left} / test("real", () => {{}}) / divisor;').encode())
    assert [u.qualname for u in parsed.units] == ["real"]

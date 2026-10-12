"""Full-file inline-call inventory preserves the single-call reader's spans.

Source proposal only; execute through ordinary hosted CI, not on the work machine.
The existing nested callback timing test and its budget remain unchanged.
"""

from __future__ import annotations

import pytest

from checkwash.frontends.javascript import frontend as js


@pytest.mark.parametrize("text", [
    "f()",
    "f( )",
    "f(/* only comment */)",
    "f(// only comment\n)",
    "f(a, b)",
    "f(a,)",
    "f(,a)",
    "f(a,,)",
    "f(,)",
    "f(/* comment */,)",
    "f(a, /* trailing comment */)",
    "f(g(a, b), [c, d], {x: h(e)})",
    "f(() => { g(); h(); }, after)",
    "f(async (x: T): Promise<T> => { return g(x); })",
    "f(function named(x): number { return g(x); })",
    'f("( ] , ;", \' } ) ,\', g(x))',
    "f(`) ; ${g(x)} ]`, after)",
    r"f(/[\(\)\[\]\{\},;]/, after)",
    "f(/* } ) ; , */ g(x), // ] ) ; ,\n after)",
    "f(a; b)",
    "f(g(a; b), after)",
    "f({key: value; other: next}, after)",
    "f(g(a), ], h(b)); later(c)",
    "f([g(a)), h(b)); later(c)",
    "f(g(a), h([b})); later(c)",
    "[) before; f(a); ] g(b)",
    "f(g(a), h(",
    "f(g(a),",
    "f(g(a); h(b)); later(c)",
    "f(a); g(b); h(c)",
    "f(/* unterminated comment ) ; g(x)",
    'f("unterminated string ) ; g(x)',
    "f(\u2003a,\ufeff/* comment */)",
    "f((() => { g(x); }))",
])
def test_selected_full_file_spans_equal_independent_reads(text):
    code = js._code_positions(text)
    masked = "".join(char if code[index] else " " for index, char in enumerate(text))
    openings = {index for index, char in enumerate(masked) if char == "("}
    # A selected call has the same local stack regardless of unrelated or
    # unselected ancestors. Exercise several subsets without changing text.
    ordered = sorted(openings)
    for selected in (openings, set(ordered[::2]), set(ordered[-1:]), set()):
        expected = {
            opening: js._call_argument_spans(text, code, opening, len(text))
            for opening in selected
        }
        assert js._inline_call_argument_spans(text, masked, selected) == expected


@pytest.mark.parametrize("tail, empty", [
    ("", True),
    (" \t\r\n\ufeff", False),  # The original regex does not treat BOM as \s.
    (" \t\r\n\u2003", True),
    ("/* comment */", True),
    ("// comment", True),
    ("// comment\r\n /* next */ ", True),
    ("/* a */ /* b */", True),
    ("/* unfinished", False),
    ("// comment\n value", False),
    ("''", False),
    ("/* comment */ value", False),
])
def test_empty_argument_range_matches_original_slice(tail, empty):
    # Non-empty prefix and suffix make accidentally using whole-string ^/$
    # semantics visible. In particular a line comment may end at endpos.
    text = "outside(" + tail + ")outside"
    start, stop = len("outside("), len("outside(") + len(tail)
    assert bool(js._EMPTY_ARGUMENT.fullmatch(text[start:stop])) is empty
    assert bool(js._EMPTY_ARGUMENT.fullmatch(text, start, stop)) is empty


def test_invalid_outer_does_not_discard_completed_or_later_inner_call():
    text = "outer(inner(x), ], later(y)); after(z)"
    code = js._code_positions(text)
    masked = "".join(char if code[index] else " " for index, char in enumerate(text))
    names = ("outer", "inner", "later", "after")
    openings = {name: text.index(name + "(") + len(name) for name in names}
    actual = js._inline_call_argument_spans(text, masked, set(openings.values()))
    assert actual[openings["outer"]] is None
    for name, value in (("inner", "x"), ("later", "y"), ("after", "z")):
        start = openings[name] + 1
        assert actual[openings[name]] == ([(start, start + len(value))], start + len(value) + 1)


def test_top_level_semicolon_rejects_only_its_call():
    text = "outer(inner(x; y), after(z))"
    code = js._code_positions(text)
    masked = "".join(char if code[index] else " " for index, char in enumerate(text))
    openings = {name: text.index(name + "(") + len(name) for name in ("outer", "inner", "after")}
    actual = js._inline_call_argument_spans(text, masked, set(openings.values()))
    assert actual[openings["inner"]] is None
    outer_first = openings["outer"] + 1
    outer_comma = text.index(",")
    assert actual[openings["outer"]] == (
        [(outer_first, outer_comma), (outer_comma + 1, len(text) - 1)], len(text)
    )
    assert actual[openings["after"]] is not None


ORACLE = "expect(withTax(10.005, 0.1)).toBe(11.01);"


@pytest.mark.parametrize("body", [
    "register(() => { try { " + ORACLE + " } catch {} });",
    "rows?.forEach(async (): Promise<void> => { try { " + ORACLE + " } catch {} });",
    "register(function nested(): void { try { " + ORACLE + " } catch {} });",
    "function nested() { try { " + ORACLE + " } catch {} }",
    "try { register(() => { " + ORACLE + " }); } catch {}",
    "register(() => { try { " + ORACLE + " } catch (e) { throw e; } });",
])
def test_parse_result_matches_old_inline_inventory(monkeypatch, body):
    data = ('import { expect, it } from "vitest";\n'
            'it("cost", () => {\n' + body + '\n});\n').encode()
    actual = js.parse_javascript(data)

    def independent_reads(text, masked, openings):
        code = js._code_positions(text)
        assert masked == "".join(
            char if code[index] else " " for index, char in enumerate(text)
        )
        return {
            opening: js._call_argument_spans(text, code, opening, len(text))
            for opening in openings
        }

    monkeypatch.setattr(js, "_inline_call_argument_spans", independent_reads)
    assert actual == js.parse_javascript(data)

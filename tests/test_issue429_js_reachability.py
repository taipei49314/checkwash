"""Assertions a JS/TS test callback never reaches are not its assertions (#429: Q1, Q3, Q5).

An assertion after `return;`, under `if (false)` or behind `false &&` stayed
in the unit at its strength, so parking it there passed with zero findings
while its Python twin blocks. One bounded walker per test callback now cuts
after an unconditional `return`/`throw` and skips the branches a literal-only
folder decides, and keeps today's reading wherever it cannot prove a
boundary. The catch evidence of #363 still reads every assertion the
callback spells. Expectations are new labels; they run only in remote CI.
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
from checkwash.frontends.javascript.reachability import fold_condition


HEADER = 'import { it, expect } from "vitest";\nimport assert from "node:assert";\n'
ORACLE = "expect(value()).toBe(1);"
TEXT = ORACLE[:-1]
PATH = "tests/value.test.ts"


def source(body: str) -> bytes:
    return (HEADER + 'it("value", () => {\n' + body + "\n});\n").encode()


def assertions(body: str) -> list[str]:
    unit, = parse_javascript(source(body)).units
    return [assertion.text for assertion in unit.side.assertions]


def outcome(before: str, after: str):
    _ir, findings, verdict = analyze([FileChange(PATH, "modified", source(before), source(after))],
                                     Config(), Contract(), [], datetime.date(2026, 10, 17))
    return verdict, findings


# --- Q1: after an unconditional return or throw -----------------------------------------------

@pytest.mark.parametrize("prefix", [
    "return;", "return", "setup(); return;", "const value = setup(); return;",
    "let value = setup();\nreturn;", "setup()\nreturn\n", "return /*\ncomment */ ",
    "return // comment\n", ";; return;", "throw new Error('stop');", "{ return; }",
    "if (true) { return; }", "if (true) return;", "if (false) {} else { return; }",
    "if (1) { throw new Error('stop'); }", "for (;;) { break; } return;",
    "const { first } = setup(); return;", "function helper() { return 1; } return;",
    "class Helper { run() { return 1; } } return;", "while (flag) { step(); } return;",
    "try { setup(); } catch { recover(); } return;", "switch (flag) { default: step(); } return;",
    "const text = `return`; return;",
])
def test_an_assertion_after_an_unconditional_return_is_not_reached(prefix):
    assert assertions(prefix + "\n" + ORACLE) == []


@pytest.mark.parametrize("body", [
    ORACLE + " return;",
    "return " + ORACLE,
    "return /* same line */ " + ORACLE,
    "return (\n" + TEXT + "\n);",
    "if (flag) return; " + ORACLE,
    "if (flag) { return; } else { return; } " + ORACLE,
    "while (flag) { return; } " + ORACLE,
    "for (const row of rows) { return; } " + ORACLE,
    "do { return; } while (flag); " + ORACLE,
    "try { return; } finally { cleanup(); } " + ORACLE,
    "try { return; } catch {} " + ORACLE,
    "outer: { return; } " + ORACLE,
    "switch (flag) { default: return; } " + ORACLE,
    "rows.forEach(() => { return; }); " + ORACLE,
    "const helper = () => { return; }; " + ORACLE,
    "function helper() { return; } " + ORACLE,
    'const text = "return;"; ' + ORACLE,
    "const text = `return;`; " + ORACLE,
    "const pattern = /return;/; " + ORACLE,
    "/* return; */ " + ORACLE,
    "// return;\n" + ORACLE,
])
def test_a_return_that_is_not_unconditional_here_keeps_the_assertion(body):
    """Only a block and a statically selected branch pass termination on (Q1)."""
    assert assertions(body) == [TEXT]


@pytest.mark.parametrize("body", [
    "return /x/\n.test(" + TEXT + ");",
    "return `x\ny`.includes(" + TEXT + ");",
    "const note = `a\nb`\nreturn\n" + ORACLE,
    "return\N{LINE SEPARATOR}" + ORACLE,
    "with (scope) { step(); } return; " + ORACLE,
    "function helper(): number { return 1; } return; " + ORACLE,
    "return; expect(value).toBe(1;" + ORACLE,
    # Text the token stream misreads as code: a nested template, JSX, an HTML-like comment.
    "const src = `function f() { ${`setup(); return 1;`} }`\n" + ORACLE,
    "const view = <p>Saved; return later</p>;\nrender(view);\n" + ORACLE,
    "foo() <!-- ;\nreturn\n" + ORACLE,
    "if (x <!-- || true\n) {} else { " + ORACLE + " }",
    # A dead body that is no block, whose end at a line break is in doubt, is not killed.
    "if (false) skip()\n{\n" + ORACLE + "\n}",
    "while (false) step()\n{ " + ORACLE + " }",
    # A nested template behind a quoted brace or a comment; JSX after a block; a comment U+2028 ends.
    "const s = `${ \"}\" + `x; return; y` }`;\n" + ORACLE,
    "if (`${ x // }` && false && `\n}`) { " + ORACLE + " }",
    "{ setup(); }\n<p>Saved; return; later</p>;\n" + ORACLE,
    "if (false) // note\N{LINE SEPARATOR}skip()\n{ " + ORACLE + " }",
    # A body whose end at a line break TypeScript or a restricted production may take.
    "if (false) ref.current!\n{\n" + ORACLE + "\n}",
    "if (false) value = undefined as void\n{ " + ORACLE + " }",
    "if (false) cache = new Map<string, number>\n{ " + ORACLE + " }",
    "if (false) x = yield\n{ " + ORACLE + " }",
    "if (false) value = ref.current!\n" + ORACLE,
    "if (false) cache = new Map<string, number>\n" + ORACLE,
    "if (false) value = undefined as void\n" + ORACLE,
    # A TypeScript type ends at the line break; `[` or `(` on the next line starts a statement.
    "if (false) config = load() as Config\n[value()].forEach(() => { " + ORACLE + " });",
    "if (false) var settings: Settings\n[value()].forEach(() => { " + ORACLE + " });",
    # An arrow's body or a postfix update cannot be called or indexed: the next line is a statement.
    "if (false) handler = () => {}\n[value()].forEach(() => { " + ORACLE + " });",
    "if (false) count++\n[value()].forEach(() => { " + ORACLE + " });",
    # A regular expression after a block or a statement head, which the mask may read as division.
    "skip: {}\n/x; return; y/.test(s);\n" + ORACLE,
    "if (ok) /x; return; y/.test(s);\n" + ORACLE,
    "let re: RegExp\n/x; return; y/.test(s);\n" + ORACLE,
    "a\n++/x; return; y/.lastIndex\n" + ORACLE,
    # A division the mask may read as a regular expression, after an object.
    "if (false) x = a || {} / 2; b / (" + TEXT + ");",
    # Any line break a dead body's end lies past keeps the body: JavaScript may end it there.
    "if (false) x = 1\n.5 + " + TEXT + ";",
    "if (false) x = y\nas(" + TEXT + ");",
    # A prefix update at a line's end takes the next line as its operand.
    "return ++\ncounter[" + TEXT + "];",
    # A division the mask reads as a regular expression after a property, `x!` or `of`.
    "if (false) { x = n.new / 2 } { z / (" + TEXT + ") }",
    "if (false) { x = total! / 2 } { z / (" + TEXT + ") }",
    # A regular expression the folder would read as a division after a prefix update.
    "if (++/ || true || x/.lastIndex && false) {} else { " + ORACLE + " }",
    # Annex B hoists a block's function declaration: `undefined` is no longer the global.
    "{ function undefined() {} }\nif (undefined) { " + ORACLE + " }",
    # A keyword after `#` is a private name: a division follows it.
    "if (false) { x = Suite.#new / 2 } { z / (" + TEXT + ") }",
    # A `\u` escape may spell `undefined`; a class heritage may hold a class; a class
    # expression goes on past a line break before `extends`.
    "const \\u0075ndefined = 1;\nif (undefined) { " + ORACLE + " }",
    "class H extends class {} {\n return() {}\n}\n" + ORACLE,
    "return class H\n extends Base { static { " + ORACLE + " } };",
    # A token the binder does not read as JavaScript does: U+FEFF is a space, a non-ASCII letter a name.
    "return load()\n\N{ZERO WIDTH NO-BREAK SPACE}.then(() => { " + ORACLE + " });",
    "const view = <\N{GREEK CAPITAL LETTER OMEGA}>Saved; return; later</\N{GREEK CAPITAL LETTER OMEGA}>; "
    "const ratio = done / total;\n" + ORACLE,
    # An identifier escape the binder splits: `return\u0041` is one name, not `return`.
    "let return\\u0041; return\\u0041 = 5; " + ORACLE,
    "\\u{61}return / 1;\n" + ORACLE,
    # TypeScript ends `x!` at the line break; the binder reads on into `do`.
    "const el = find()!\ndo el.reset(); while (false)\n" + ORACLE,
    # A `return` with an operand that ends at a line break without a `;`: TypeScript may go on.
    "return class H implements\n  Base { static { " + ORACLE + " } };",
    "return value() as readonly\n  string[] || " + TEXT + ";",
    "return @register\n  class { static { " + ORACLE + " } };",
    "return value\n" + ORACLE,
    # A statement keyword inside a statement read on past its end; a literal-decided
    # statement across a line break JavaScript may end it at (`.0` is a number).
    "const f = () => {}\n{ } do step(); while (0) " + ORACLE,
    "enum Mode { A } do step(); while (false) " + ORACLE,
    "true || a\n.0 || " + TEXT + ";",
    # `1.` is a whole number and `cache.delete` a whole operand: JavaScript ends the line there.
    "if (false) n = 1.\n" + ORACLE,
    "if (false) drop = cache.delete\n" + ORACLE,
    "false && n === 1.\nok && " + TEXT + ";",
    "false && cache.delete\nready && " + TEXT + ";",
    # A body the tokens omit: a template or regular expression is the whole body.
    "if (false) `skip`\n{ " + ORACLE + " }",
    "while (false) `x`\n{ " + ORACLE + " }",
    "if (true) {} else /x/\n{ " + ORACLE + " }",
    "do `x`\nwhile (false)\n" + ORACLE,
    # Q3 only after a `;` or a statement's own `}`: TypeScript may read past a line break
    # (`v is` then `false`), so a boundary ASI gives is not proved.
    "const y: any = get();\n y as (v: unknown) => v is\n false && " + TEXT + ";",
    "setup()\nfalse && " + ORACLE,
])
def test_an_unproved_boundary_keeps_todays_reading(body):
    parsed = parse_javascript(source(body))
    assert TEXT in [assertion.text for assertion in parsed.units[0].side.assertions]
    assert parsed.unreachable_assertion_spans == ()


@pytest.mark.parametrize("prelude", [
    # JavaScript reads a block comment from `/*` to the `*/` of the fourth line; the mask, whose
    # template ends at the backtick inside `'`'`, hides the `/*` and reads a test with a `return`.
    "const s = `${'`'}`; /* '\n",
    # JavaScript ends the `//` comment at U+2028, so `/*` opens a block comment the mask does not see.
    "// note\N{LINE SEPARATOR}/* '\n",
    # After `export default` a `/` starts a regular expression; the mask divides.
    "export default /'/; /* '\n",
])
def test_a_misreading_before_the_callback_refuses_it(prelude):
    text = HEADER + prelude + 'it("a", () => {\nreturn;\n// */ it("a", () => {\n' + ORACLE + "\n});\n"
    assert parse_javascript(text.encode()).unreachable_assertion_spans == ()


def test_jsx_at_the_file_start_refuses_the_callbacks_after_it():
    """The `'` in the JSX text opens a string for the mask, which then hides the `/*`."""
    text = "<p>it's</p>; /* '\n" + HEADER + 'it("a", () => {\nreturn;\n// */ it("a", () => {\n' + ORACLE + "\n});\n"
    assert parse_javascript(text.encode()).unreachable_assertion_spans == ()


def test_a_cut_holding_a_function_declaration_is_refused():
    """A call before the `return` may run the hoisted declaration's body."""
    parsed = parse_javascript(source("check(value()); return; function check<T>(v: T) { expect(v).toBe(1); }"))
    assert parsed.unreachable_assertion_spans == ()


def test_a_nested_callback_return_does_not_hide_the_parents():
    assert assertions("rows.forEach(() => { return; }); return; " + ORACLE) == []


def test_a_return_inside_an_iterator_callback_ends_only_that_callback():
    """The walker never enters a function body, D-106's iterator callbacks included."""
    assert assertions("rows.forEach((row) => { return; expect(row).toBe(1); });") == ["expect(row).toBe(1)"]


def test_a_return_ends_its_loop_body_but_not_the_test():
    body = "for (const row of rows) { return; expect(row).toBe(1); } " + ORACLE
    assert assertions(body) == [TEXT]


# --- Q5: branches the folder decides ----------------------------------------------------------

@pytest.mark.parametrize("statement", [
    "if (false) { " + ORACLE + " }", "if (false) " + ORACLE, "if (0) { " + ORACLE + " }",
    "if (-0) { " + ORACLE + " }", "if (0n) { " + ORACLE + " }", 'if ("") { ' + ORACLE + " }",
    "if (``) { " + ORACLE + " }", "if (null) { " + ORACLE + " }", "if (undefined) { " + ORACLE + " }",
    "if (NaN) { " + ORACLE + " }", "if (!true) { " + ORACLE + " }", "if (!1) { " + ORACLE + " }",
    "if (1 === 2) { " + ORACLE + " }", 'if ("a" !== "a") { ' + ORACLE + " }",
    "if (2 < 1) { " + ORACLE + " }", 'if ("b" <= "a") { ' + ORACLE + " }", "if (1 == 2) { " + ORACLE + " }",
    "if (false && flag) { " + ORACLE + " }", "if (flag && false) { " + ORACLE + " }",
    "if (!(true || flag)) { " + ORACLE + " }", "if ((false)) { " + ORACLE + " }",
    "if (/* off */ false) { " + ORACLE + " }", "if (true) {} else { " + ORACLE + " }",
    "if (true) {} else " + ORACLE, "if (flag) {} else if (false) { " + ORACLE + " }",
    "if (flag) { if (false) { " + ORACLE + " } }", "while (false) { " + ORACLE + " }",
    "while (0) " + ORACLE, "for (; false; ) { " + ORACLE + " }",
    "for (let i = 0; 1 > 2; i++) { " + ORACLE + " }",
    "for (const row of rows) { if (false) { " + ORACLE + " } }",
    "try { if (false) { " + ORACLE + " } } catch {}", "outer: { if (false) { " + ORACLE + " } }",
    "do { if (false) { " + ORACLE + " } } while (flag);",
])
def test_an_assertion_in_a_branch_the_folder_decides_dead_is_not_reached(statement):
    assert assertions(statement) == []


@pytest.mark.parametrize("statement", [
    "if (flag) { " + ORACLE + " }", "if (true) { " + ORACLE + " }", "if (1n) { " + ORACLE + " }",
    "if (flag || false) { " + ORACLE + " }", "if (x === 1) { " + ORACLE + " }",
    'if (1 == "1") { ' + ORACLE + " }", "if (null == undefined) { " + ORACLE + " }",
    "if (Infinity) {} else { " + ORACLE + " }", "if (true ? false : true) { " + ORACLE + " }",
    "if (false ?? true) {} else { " + ORACLE + " }", "if ((0, false)) { " + ORACLE + " }",
    "if (`${flag}`) { " + ORACLE + " }", "if (1 < 2 < 3) {} else { " + ORACLE + " }",
    "if (typeof x === 'undefined') { " + ORACLE + " }", "if (process.env.CI) { " + ORACLE + " }",
    "const off = false; if (off) { " + ORACLE + " }",
    "const undefined = 1; if (undefined) { " + ORACLE + " }",
    "while (true) { " + ORACLE + " break; }", "for (;;) { " + ORACLE + " break; }",
    "for (const row of []) { " + ORACLE + " }", "do { " + ORACLE + " } while (false);",
    "switch (0) { case 1: " + ORACLE + " }",
    "if (" + "!" * 1000 + "true) {} " + ORACLE,
])
def test_a_branch_the_folder_cannot_decide_or_that_runs_keeps_the_assertion(statement):
    """`const` bindings, coercions, `??`, `?:` and empty iterables are residuals (Q5)."""
    assert assertions(statement) == [TEXT]


@pytest.mark.parametrize("condition,truth", [
    ("true", True), ("false", False), ("0", False), ("-0", False), ("1.5", True), ("0x0", False),
    ("0n", False), ("2n", True), ("''", False), ('"x"', True), ("``", False), ("`x`", True),
    ("null", False), ("undefined", False), ("NaN", False), ("!false", True), ("!!0", False),
    ("(((1)))", True), ("1 === 1", True), ("1 === 1.0", True), ("0 === -0", True), ("NaN === NaN", False),
    ("1 === 1n", False), ("'a' === \"a\"", True), ("null === undefined", False), ("null !== null", False),
    ("1 == 1", True), ("'a' != 'b'", True), ("2 > 1", True), ("1 >= 2", False), ("'b' > 'a'", True),
    ("2n < 3n", True), ("true > false", True), ("NaN < 1", False), ("false && x", False),
    ("x && false", False), ("true || x", True), ("x || true", True), ("false || 0", False),
    ("true && 1", True), ("!(false || false)", True), ("x", None), ("f()", None), ("x === 1", None),
    ("1 == '1'", None), ("null == undefined", None), ("null < 1", None), ("'1' < 2", None),
    ("1 + 1", None), ("-x", None), ("true ? 1 : 0", None), ("a ?? b", None), ("(0, 1)", None),
    ("x = 0", None), ("1 < 2 < 3", None), ("1 === 1 === true", None), ("Infinity", None),
    ("void 0", None), ("typeof x", None), ("`${x}`", None), ("/a/", None), ("'a\nb'", None), ("", None),
    ("(", None), ("1 /* c */ === // d\n 1", True), ("1 in x", None),
    ("!" * 1000 + "true", None), ("(" * 400 + "false" + ")" * 400, None),
    ("i++ / 2 || x / 1 && false", None), ("x <!-- || true", None), ("x --> 0 || true", None),
    ("`${ x // }` && false && `\n}`", None), ("++/ || true || x/.lastIndex && false", None),
    ("this.#new / 2 || true || 1 / 1 && false", None),
])
def test_the_condition_folder(condition, truth):
    assert fold_condition(condition, lambda _name: True) is truth


@pytest.mark.parametrize("prelude", [
    "// note\N{LINE SEPARATOR}var undefined = 1;\n",  # JavaScript ends the comment at U+2028
    "h = n.new / 2; var undefined = 1; re = /x/;\n",  # the mask reads `/ 2; ... /` as one literal
    "enum undefined { A }\n",
    "function check(undefined: number): void {}\n",
])
def test_a_spelling_of_undefined_the_walk_cannot_read_leaves_it_unfolded(prelude):
    text = HEADER + prelude + 'it("value", () => {\nif (undefined) { ' + ORACLE + " }\n});\n"
    parsed = parse_javascript(text.encode())
    assert TEXT in [assertion.text for unit in parsed.units for assertion in unit.side.assertions]
    assert parsed.unreachable_assertion_spans == ()


@pytest.mark.parametrize("head", ["with (", "with /* s */ (", "with\N{ZERO WIDTH NO-BREAK SPACE}("])
def test_a_with_statement_in_the_file_leaves_undefined_unfolded(head):
    """`with ({ undefined: 1 })` around a test shadows the global the binder sees."""
    text = HEADER + head + '{ undefined: 1 }) {\nit("value", () => {\nif (undefined) { ' + ORACLE + " }\n});\n}\n"
    assert parse_javascript(text.encode()).unreachable_assertion_spans == ()


def test_the_with_search_does_not_backtrack():
    """A run of slashes after a `with` in a comment is read in one pass (no regex backtracking)."""
    text = HEADER + "// shared with\n" + "/" * 5000 + "\n" + 'it("value", () => {\nif (x === undefined) { ' + ORACLE
    parsed = parse_javascript((text + " }\n});\n").encode())
    assert parsed.unreachable_assertion_spans == ()


def test_undefined_and_nan_fold_only_as_unshadowed_globals():
    assert fold_condition("undefined", lambda _name: False) is None
    assert fold_condition("NaN || false", lambda _name: False) is None
    assert fold_condition("NaN || false", lambda name: name == "NaN") is False


# --- Q3: literal-decided && and || statements --------------------------------------------------

@pytest.mark.parametrize("statement", [
    "false && " + ORACLE, "0 && " + ORACLE, "!true && " + ORACLE, "null && " + ORACLE,
    "true || " + ORACLE, "(false) && " + ORACLE, "false && flag && " + ORACLE,
    "setup();\nfalse && " + ORACLE, "if (flag) false && " + ORACLE,
    "false && assert.strictEqual(value(), 1);", "false &&\n  " + ORACLE,
])
def test_a_literal_decided_and_or_statement_drops_its_last_assertion(statement):
    assert TEXT not in assertions(statement)
    assert all(not text.startswith("assert.strictEqual(value()") for text in assertions(statement))


@pytest.mark.parametrize("statement", [
    "true && " + ORACLE, "false || " + ORACLE, "flag && " + ORACLE, "false && (" + TEXT + ");",
    "false ? " + TEXT + " : null;", "false ?? " + ORACLE, "(false, " + TEXT + ");",
    TEXT + " && false;", "const ok = false && " + ORACLE, "setup()\n(false) && " + ORACLE,
    "x = false && " + ORACLE,
])
def test_other_and_or_shapes_are_residuals_that_keep_the_assertion(statement):
    assert TEXT in assertions(statement)


# --- What the cut keeps: catch evidence, coverage, identities ---------------------------------

def test_the_catch_evidence_still_reads_every_assertion_the_callback_spells():
    """#363: a parent return cuts the unit's assertions, not the catch evidence."""
    data = source("return; rows.forEach(() => { try { " + ORACLE + " } catch {} });")
    parsed = parse_javascript(data)
    assert parsed.units[0].side.assertions == []
    assert parsed.swallowing_handlers == (SWALLOWED,)
    assert len(parsed.unreachable_assertion_spans) == 1
    assert javascript_coverage_gaps(data, parsed, PATH, "after") == []


def test_an_unread_assertion_no_statement_reaches_keeps_its_coverage_reason():
    data = source("return; " + ORACLE + " expect(spy).toHaveBeenCalled(); assert.okay(value);")
    parsed = parse_javascript(data)
    assert parsed.units[0].side.assertions == []
    text = data.decode()
    strong, = parsed.unreachable_assertion_spans
    unjudged, = parsed.unreachable_unjudged_assertion_spans
    assert text[slice(*strong)] == TEXT
    assert text[slice(*unjudged)] == "expect(spy).toHaveBeenCalled()"
    gaps = javascript_coverage_gaps(data, parsed, PATH, "after")
    assert len(gaps) == 2
    assert "recorded with no strength" in gaps[0].reason
    assert gaps[1].callee == "assert.okay"


@pytest.mark.parametrize("after", [
    "return;\n" + ORACLE, "if (false) {\n  " + ORACLE + "\n}", "false && " + ORACLE,
    "if (true) { return; }\n" + ORACLE, "throw new Error('skip');\n" + ORACLE,
])
def test_a_parked_assertion_is_removed_with_the_key_a_deleted_one_has(after):
    verdict, findings = outcome(ORACLE, after)
    assert verdict == "block"
    assert [(f.rule, f.severity) for f in findings] == [("ASSERT_REMOVED", "high")]
    assert findings[0].before.text == TEXT
    _verdict, deleted = outcome(ORACLE, "")
    assert findings[0].fingerprint == deleted[0].fingerprint


def test_a_different_live_oracle_cannot_hide_the_parked_one():
    verdict, findings = outcome("expect(other()).toBe(2); " + ORACLE, "expect(other()).toBe(2); return; " + ORACLE)
    assert verdict == "block"
    finding, = findings
    assert (finding.rule, finding.before.text) == ("ASSERT_REMOVED", TEXT)


@pytest.mark.parametrize("before,after", [
    (ORACLE, "if (flag) return;\n" + ORACLE),
    (ORACLE, ORACLE + "\nreturn;"),
    ("return;\n" + ORACLE, "return;\n" + ORACLE),
    ("return;\n" + ORACLE, ORACLE),
    ("if (false) { " + ORACLE + " }", "if (false) {\n  " + ORACLE + "\n}"),
])
def test_live_or_unchanged_shapes_report_nothing(before, after):
    assert outcome(before, after) == ("pass", [])

"""Every write reaches the JS binding scan, and statements end where JavaScript ends them (#196 189.1).

The scan read a bound or an assertion alias through its initializer unless a
`=`, `+=`, `-=`, `*=`, `/=` or postfix `++`/`--` in the read's own function
came first, and a declaration without a semicolon ran on into the next line.
A name that any write may have reached is now unknown: every assignment
operator, prefix `++`/`--`, destructuring targets, `for`-`in`/`of` heads, and
writes in any other function, wherever they are written. Unknown is not
unchanged: a hand-rolled bound the base side read and the head side cannot is
reported, as an unreadable `closeTo` delta is.
"""

import datetime

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze
from checkwash.frontends.javascript.bindings import Bindings
from checkwash.frontends.javascript.frontend import _code_positions, parse_javascript

NODE = 'const test = require("node:test");\nconst assert = require("node:assert");\n'
VITEST = 'import { test, expect, beforeEach } from "vitest";\nimport assert from "node:assert";\n'
CHECK = "assert.ok(Math.abs(value - 78.75) < eps);"
UNKNOWN_TOLERANCE = "cannot verify the replacement is equivalent (tolerance abs=0.01 -> a tolerance it cannot read)"


def _bindings(text):
    return Bindings(text, _code_positions(text), _code_positions(text, keep_strings=True))


def _initializer(body, top="", tail="", name="eps", marker="READ"):
    """The initializer `name` reads at `marker` inside a test body."""
    text = f'{top}test("t", () => {{\n  {body}\n}});\n{tail}'
    return _bindings(text).initializer(name, text.index(marker))


def _source(body, top="", tail="", header=NODE):
    return f'{header}{top}test("total", () => {{\n  const value = total();\n  {body}\n}});\n{tail}'


def _outcome(before, after, *, top="", top_after=None, tail="", tail_after=None, header=NODE):
    top_after = top if top_after is None else top_after
    tail_after = tail if tail_after is None else tail_after
    _ir, findings, verdict = analyze(
        [FileChange("src/total.test.ts", "modified",
                    _source(before, top, tail, header).encode(),
                    _source(after, top_after, tail_after, header).encode())],
        Config(), Contract(), [], datetime.date(2026, 10, 3),
    )
    return verdict, [(f.rule, f.severity) for f in findings], [f.message for f in findings]


# --- Every write form --------------------------------------------------------------------

@pytest.mark.parametrize("write", [
    "eps **= 2;", "eps %= 1;", "eps <<= 1;", "eps >>= 1;", "eps >>>= 1;", "eps &= 1;", "eps |= 1;",
    "eps ^= 1;", "eps &&= 1;", "eps ||= 1;", "eps ??= 1;",
    "++eps;", "--eps;", "x = ++eps;",
    "[eps] = [1];", "[, eps] = [0, 1];", "[...eps] = [1];", "[[eps]] = [[1]];", "[eps = 2] = [];",
    "({ eps } = { eps: 1 });", "({ a: eps } = { a: 1 });", "({ eps = 1 } = {});", "({ a: { eps } } = obj);",
    "({ ...eps } = obj);", "[obj, eps] = [eps, obj];",
    "for (eps of [1]) {}", "for (eps in { a: 1 }) {}", "for ([eps] of [[1]]) {}",
    "(eps) = 1;", "(eps as number) = 1;", "eps! = 1;",
])
def test_every_write_form_makes_the_name_unknown(write):
    assert _initializer(f"let eps = 0.01; {write}\n  READ;") is None
    assert _initializer("let eps = 0.01;\n  READ;") == "0.01"


@pytest.mark.parametrize("hook", [
    "beforeEach(() => { eps = 1e12; });",
    "function widen() { eps = 1e12; }",
    "const widen = () => { eps **= 10; };",
    "const helper = { run() { eps++; } };",
])
def test_a_write_in_any_other_function_counts_wherever_it_is_written(hook):
    # Before the test, or after it: either may run before the read.
    assert _initializer("READ;", top=f"let eps = 0.01;\n{hook}\n") is None
    assert _initializer("READ;", top="let eps = 0.01;\n", tail=f"{hook}\n") is None


def test_a_module_level_write_after_the_test_reaches_its_body():
    # Test bodies run after the whole module has been evaluated.
    assert _initializer("READ;", top="let eps = 0.01;\n", tail="eps = 1e12;\n") is None


@pytest.mark.parametrize("loop", [
    "for (const v of [1, 2]) { READ; eps *= 10; }",
    "for (let i = 0; i < 2; i++) { READ; eps++; }",
    "while (more()) { READ; eps = next(); }",
    "do { READ; --eps; } while (more());",
    "for (const v of [1, 2]) READ, eps *= 10;",
])
def test_a_later_write_in_a_loop_around_the_read_counts(loop):
    assert _initializer(f"let eps = 0.01;\n  {loop}") is None


@pytest.mark.parametrize("body", [
    # A later write in straight-line code runs after the read.
    "let eps = 0.01;\n  READ;\n  eps = 1e12;",
    "let eps = 0.01;\n  READ;\n  for (const v of [1]) { eps = v; }",
    # Other bindings, shadows and members of other objects are not this one.
    "let eps = 0.01;\n  let other = 1;\n  other **= 2;\n  READ;",
    "let eps = 0.01;\n  { let eps = 1; eps *= 9; }\n  READ;",
    "let eps = 0.01;\n  const cfg = {};\n  cfg.eps = 1e12;\n  READ;",
    "let eps = 0.01;\n  const pair = { eps: 1e12 };\n  READ;",
])
def test_writes_that_cannot_reach_the_read_leave_the_initializer(body):
    assert _initializer(body) == "0.01"


@pytest.mark.parametrize("tail", [
    "function View() { return <Range eps={5} />; }",
    'function View() { return <input class="a" eps="5" />; }',
    "class Box { eps = 5; static other = 1; readonly third = 2; }",
    "type eps = number;",
])
def test_jsx_attributes_class_fields_and_type_aliases_are_not_writes(tail):
    assert _initializer("READ;", top="let eps = 0.01;\n", tail=f"{tail}\n") == "0.01"


def test_a_postfix_increment_does_not_write_the_next_line():
    # `count++` then `expect(...)` is two statements: the operator is postfix.
    text = 'import { test, expect } from "vitest";\ntest("t", () => {\n  let count = 0;\n  count++\n  expect(count).toBe(1);\n});\n'
    assertion, = [a for unit in parse_javascript(text.encode()).units for a in unit.side.assertions]
    assert assertion.strength is not None


def test_a_line_break_before_an_increment_makes_it_prefix():
    assert _initializer("let eps = 0.01;\n  let other = 1;\n  other\n  ++eps\n  READ;") is None


@pytest.mark.parametrize("declaration", [
    "const [eps] = [1e12];",
    "const { a: { eps } } = { a: { eps: 1e12 } };",
    "const { ...eps } = obj;",
    "const first = 1, [eps] = [1e12];",
])
def test_a_destructuring_declaration_shadows_the_outer_name(declaration):
    assert _initializer(f"{declaration}\n  READ;", top="const eps = 0.01;\n") is None


def test_a_destructuring_declaration_does_not_write_the_outer_name():
    # It declares a new binding: a sibling test still reads the outer one.
    text = 'const eps = 0.01;\ntest("a", () => {\n  const [eps] = [1e12];\n});\ntest("b", () => {\n  READ;\n});\n'
    assert _bindings(text).initializer("eps", text.index("READ")) == "0.01"


# --- Statement ends (ASI) -----------------------------------------------------------------

@pytest.mark.parametrize("declaration,expected", [
    ("const eps = 0.01\n  READ", "0.01"),
    ("const eps = 0.01 // a cent\n  READ", "0.01"),
    ("const eps =\n    0.01;\n  READ", "0.01"),
    ("const eps = 0.01\n  ;READ", "0.01"),
])
def test_a_declaration_ends_at_a_line_break_that_cannot_continue_it(declaration, expected):
    assert _initializer(declaration).strip() == expected


@pytest.mark.parametrize("declaration", [
    "const eps = 0.01\n    * 2\n  READ",
    "const eps = base\n    .tolerance\n  READ",
    "const eps = 0.01 +\n    1\n  READ",
])
def test_an_operator_or_member_access_continues_the_declaration(declaration):
    assert _initializer(declaration).strip() != "0.01"


def test_a_semicolon_free_alias_keeps_its_oracle():
    text = 'import { test, expect } from "vitest";\ntest("t", () => {\n  const check = expect\n  check(value()).toBe(78.75)\n});\n'
    assertion, = [a for unit in parse_javascript(text.encode()).units for a in unit.side.assertions]
    assert assertion.right_value == "78.75"


def test_a_call_on_the_next_line_continues_the_alias():
    # `expect\n(value)` is `expect(value)`, as JavaScript reads it.
    text = 'const check = expect\n(value)\ntest("t", () => {\n  READ;\n});\n'
    assert _bindings(text).resolve("check", text.index("READ")).kind == "unknown"


# --- Findings -----------------------------------------------------------------------------

@pytest.mark.parametrize("write", [
    "eps **= -10;", "for (let i = 0; i < 40; i++) ++eps;", "[eps] = [1e12];", "({ eps } = { eps: 1e12 });",
    "eps *= 1e14;", "eps ||= 1e12;", "const widen = () => { eps = 1e12; };\n  widen();",
])
def test_a_write_that_makes_a_read_bound_unknown_is_reported(write):
    verdict, findings, messages = _outcome(f"let eps = 0.01;\n  {CHECK}", f"let eps = 0.01;\n  {write}\n  {CHECK}")
    assert (verdict, findings) == ("block", [("ASSERT_WEAKENED", "high")]), messages
    assert UNKNOWN_TOLERANCE in messages[0]


def test_a_hook_write_added_beside_the_test_is_reported():
    verdict, findings, messages = _outcome(CHECK, CHECK, top="let eps = 0.01;\n",
                                           top_after="let eps = 0.01;\nbeforeEach(() => { eps = 1e12; });\n",
                                           header=VITEST)
    assert (verdict, findings) == ("block", [("ASSERT_WEAKENED", "high")]), messages


@pytest.mark.parametrize("check", [
    "expect(Math.abs(value - 78.75)).toBeLessThan(eps);",
    "expect(Math.abs(value - 78.75) < eps).toBe(true);",
    "expect(Math.abs(value - 78.75)).toBeLessThanOrEqual(eps);",
])
def test_every_hand_rolled_spelling_reports_an_unknown_bound(check):
    verdict, findings, messages = _outcome(f"let eps = 0.01;\n  {check}", f"let eps = 0.01;\n  eps **= 9;\n  {check}",
                                           header=VITEST)
    assert (verdict, findings) == ("block", [("ASSERT_WEAKENED", "high")]), messages


@pytest.mark.parametrize("before,after", [
    # The same write on both sides: unknown on both, nothing replaced.
    (f"let eps = 0.01;\n  eps *= 1e14;\n  {CHECK}", f"let eps = 0.01;\n  eps *= 1e14;\n  {CHECK}"),
    # A write after the read in straight-line code.
    (f"let eps = 0.01;\n  {CHECK}", f"let eps = 0.01;\n  {CHECK}\n  eps = 5;"),
    # Lower bounds and negated checks record no tolerance.
    ("let eps = 0.01;\n  assert.ok(Math.abs(value - 78.75) > eps);",
     "let eps = 0.01;\n  eps **= 9;\n  assert.ok(Math.abs(value - 78.75) > eps);"),
    ("let eps = 0.01;\n  assert.ok(!(Math.abs(value - 78.75) < eps));",
     "let eps = 0.01;\n  eps **= 9;\n  assert.ok(!(Math.abs(value - 78.75) < eps));"),
])
def test_unknown_on_neither_or_both_sides_stays_silent(before, after):
    assert _outcome(before, after)[:2] == ("pass", [])


def test_a_semicolon_free_widening_is_reported():
    verdict, findings, messages = _outcome(
        "const eps = 0.01\n  assert.ok(Math.abs(value - 78.75) < eps)",
        "const eps = 1e12\n  assert.ok(Math.abs(value - 78.75) < eps)")
    assert (verdict, findings) == ("block", [("TOLERANCE_LOOSENED", "high")]), messages


def test_a_semicolon_free_alias_reports_its_rewritten_expected_value():
    verdict, findings, messages = _outcome("const check = expect\n  check(value).toBe(78.75)",
                                           "const check = expect\n  check(value).toBe(75)", header=VITEST)
    assert (verdict, findings) == ("block", [("EXPECTED_VALUE_CHANGED", "high")]), messages

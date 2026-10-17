"""JS/TS assertions that can never fail read as TAUTOLOGY (#429: Q2, Q6, Q7).

`expect(total).toBe(total)` passed with zero findings while its Python twin,
`assert total == total`, blocks: the JS frontend rated every equality
EXACT_VALUE without comparing its operands, and `toBe` states `eq_strict` on
both sides, which the predicate relation reads as the same predicate. An
assertion whose subject and operands are exact literals (Q2), and an equality
or inclusive bound whose two sides are one operand (Q7), now record form
`tautology`, strength TAUTOLOGY, no predicate key and `positive=True`, and keep
their subject, text, span and operand evidence (Q6). Expectations are new
labels; they run only in remote CI.
"""

from __future__ import annotations

import datetime

import pytest

import checkwash.findings as findings_module
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze
from checkwash.findings import assertion_key
from checkwash.frontends.javascript.exception_handlers import ALWAYS_PASSING
from checkwash.frontends.javascript.frontend import parse_javascript
from checkwash.frontends.javascript.literals import literal_operand, same_operand
from checkwash.ir import strength as S


VITEST = 'import { expect, it } from "vitest";\n'
NODE = 'import assert from "node:assert";\nimport { test } from "node:test";\n'
CHAI = 'import { expect, assert } from "chai";\n'
SHOULD = 'import { should } from "chai";\nshould();\n'
AVA = "import test from 'ava';\n"
TAP = "import t from 'tap';\n"
PATH = "tests/sample.test.ts"


def _source(header: str, body: str) -> str:
    if header == TAP:
        return header + "t.test('sample', async t => {\n  " + body + "\n});\n"
    if header == AVA:
        return header + "test('sample', t => {\n  " + body + "\n});\n"
    return header + 'it("sample", () => {\n  ' + body + "\n});\n"


def _assertions(header: str, body: str):
    return [assertion for unit in parse_javascript(_source(header, body).encode()).units
            for assertion in unit.side.assertions]


def _assertion(header: str, body: str):
    assertion, = _assertions(header, body)
    return assertion


def _outcome(header: str, before: str, after: str, path: str = PATH):
    change = FileChange(path, "modified", _source(header, before).encode(), _source(header, after).encode())
    _ir, findings, verdict = analyze([change], Config(), Contract(), [], datetime.date(2026, 10, 17))
    return verdict, findings


def _tautology(assertion) -> bool:
    return (assertion.form, assertion.strength, assertion.predicate, assertion.positive) == (
        "tautology", S.TAUTOLOGY, None, True)


# --- Q7: one operand on both sides ------------------------------------------------------------

@pytest.mark.parametrize("header,body,subject", [
    (VITEST, "expect(total).toBe(total);", "total"),
    (VITEST, "expect(total).toEqual(total);", "total"),
    (VITEST, "expect(total).toStrictEqual(total);", "total"),
    (VITEST, "expect(total).not.toBe(total);", "total"),
    (VITEST, "expect(total).toBeGreaterThanOrEqual(total);", "total"),
    (VITEST, "expect(total).toBeLessThanOrEqual(total);", "total"),
    (VITEST, "expect(await checkout([10, 20])).toBe(await checkout([10, 20]));", "await checkout([10, 20])"),
    (NODE, "assert.strictEqual(total, total);", "total"),
    (NODE, "assert.equal(total, total);", "total"),
    (NODE, "assert.deepStrictEqual(order, order);", "order"),
    (NODE, "assert.deepEqual(order, order);", "order"),
    (CHAI, "expect(total).to.equal(total);", "total"),
    (CHAI, "expect(order).to.eql(order);", "order"),
    (CHAI, "expect(order).to.deep.equal(order);", "order"),
    (CHAI, "expect(total).to.be.at.least(total);", "total"),
    (CHAI, "expect(total).to.be.at.most(total);", "total"),
    (CHAI, "assert.equal(total, total);", "total"),
    (CHAI, "assert.strictEqual(total, total);", "total"),
    (CHAI, "assert.deepEqual(order, order);", "order"),
    (CHAI, "assert.isAtLeast(total, total);", "total"),
    (CHAI, "assert.isAtMost(total, total);", "total"),
    (SHOULD, "total.should.equal(total);", "total"),
    (AVA, "t.is(total, total);", "total"),
    (AVA, "t.deepEqual(order, order);", "order"),
    (TAP, "t.equal(total, total);", "total"),
    (TAP, "t.same(order, order);", "order"),
    (TAP, "t.strictSame(order, order);", "order"),
])
def test_a_self_comparison_reads_as_a_tautology_in_every_library(header, body, subject):
    assertion = _assertion(header, body)
    assert _tautology(assertion)
    assert assertion.left == subject


@pytest.mark.parametrize("expected", [
    "(total)", "((total))", "total + 0", "0 + total", "total - 0", "total * 1", "1 * total",
    "total / 1", "total + 0.0", "total + 0 + 0", "(total + 0) * 1", "total * 1 + 0",
    "total as number", "total!", "total satisfies number", "(total as number) + 0",
    "/* the same */ total", "total\n    + 0",
])
def test_python_row_10_stripping_and_ts_wrappers_read_one_operand(expected):
    assert _tautology(_assertion(VITEST, f"expect(total).toBe({expected});"))


@pytest.mark.parametrize("subject,expected", [
    ("price(items)", "price( items )"),
    ("get('a')", 'get("a")'),
    ("price(items) + 0", "price(items)"),
    ("order.lines[0]", "order.lines[ 0 ]"),
])
def test_formatting_and_quotes_do_not_make_two_operands(subject, expected):
    assert _tautology(_assertion(VITEST, f"expect({subject}).toEqual({expected});"))


@pytest.mark.parametrize("expected", [
    "subtotal", "total + 1", "-total", "+total", "total + -0", "0 - total", "total % 1",
    "total ** 1", "1 / total", "total + 0 + 1", "total || total", "(total, total)",
    "total.value", "other(total)", "total + 0n",
])
def test_a_different_operand_keeps_the_exact_rung(expected):
    assertion = _assertion(VITEST, f"expect(total).toBe({expected});")
    assert (assertion.form, assertion.strength) == ("compare_eq", S.EXACT_VALUE)
    assert assertion.predicate == "eq_strict"


@pytest.mark.parametrize("header,body,form,strength", [
    # Exclusive bounds can never pass, and Python does not read `x < x` either.
    (VITEST, "expect(total).toBeGreaterThan(total);", "compare_ord", S.BOUND),
    (VITEST, "expect(total).toBeLessThan(total);", "compare_ord", S.BOUND),
    # Q7 names equalities and inclusive bounds only.
    (VITEST, "expect(total).toBeCloseTo(total);", "approx", S.APPROX),
    (VITEST, "expect(items).toContain(items);", "membership", S.PATTERN),
    (CHAI, "expect(total).to.be.within(total, total);", "compare_ord", S.BOUND),
    # Truthy spellings, the `x === x` NaN idiom among them, are a residual (Q7).
    (NODE, "assert.ok(total === total);", "truthy", S.TRUTHY),
    (VITEST, "expect(total === total).toBe(true);", "compare_eq", S.EXACT_VALUE),
    # Two spellings of one property are two operands: nothing is evaluated.
    (VITEST, 'expect(order.total).toBe(order["total"]);', "compare_eq", S.EXACT_VALUE),
    # A property's value compared with that property still asserts that the property is there.
    (CHAI, "expect(order).to.have.property('total', order.total);", "compare_eq", S.EXACT_VALUE),
    (CHAI, "assert.propertyVal(order, 'total', order.total);", "compare_eq", S.EXACT_VALUE),
    # Templates and regular expressions are read whole: a `//` in one is no comment, and
    # the whitespace a regex matches is not formatting.
    (NODE, "assert.strictEqual(`http://${host}/a`, `http://${expected}/a`);", "compare_eq", S.EXACT_VALUE),
    (VITEST, 'expect(text.replace(/  /g, "_")).toBe(text.replace(/ /g, "_"));', "compare_eq", S.EXACT_VALUE),
    # A cast is taken out only to one named type: `as any || fallback` is more than a cast.
    (VITEST, "expect(value as any || fallback).toEqual(value);", "compare_eq", S.EXACT_VALUE),
    # A spread on both sides compares two different elements.
    (NODE, "assert.equal(...pair, ...pair);", "compare_eq", S.EXACT_VALUE),
    (AVA, "t.is(...pair, ...pair);", "compare_eq", S.EXACT_VALUE),
])
def test_named_residuals_keep_their_rung(header, body, form, strength):
    assertion = _assertion(header, body)
    assert (assertion.form, assertion.strength) == (form, strength)


# --- Q2: exact literals -----------------------------------------------------------------------

@pytest.mark.parametrize("header,body", [
    (VITEST, "expect(1).toBe(1);"),
    (VITEST, "expect(1).toBe(2);"),
    (VITEST, "expect('a').toBe(\"a\");"),
    (VITEST, "expect(true).toBeTruthy();"),
    (VITEST, "expect(false).toBeTruthy();"),
    (VITEST, "expect(null).toBeNull();"),
    (VITEST, "expect(0).toBeDefined();"),
    (VITEST, "expect(-1).toBeLessThan(0);"),
    (VITEST, "expect(1.5).toBeCloseTo(1.5, 2);"),
    (VITEST, "expect(10n).toBe(10n);"),
    (VITEST, "expect(`a`).toBe('a');"),
    (VITEST, "expect((1 as number)).toBe(1);"),
    (VITEST, "expect([1, 'a', [null]]).toEqual([1, 'a', [null]]);"),
    (VITEST, "expect({ a: 1, 'b': [2], 3: true }).toStrictEqual({ a: 1 });"),
    (VITEST, "expect('abc').toMatch(/b/);"),
    (VITEST, "expect([1, 2]).toContain(2);"),
    (VITEST, "expect(1, 'message').toBe(1);"),
    (VITEST, "expect(`it's`).toBe(\"it's\");"),
    (VITEST, "expect(`http://x`).toBe('http://x');"),
    (VITEST, "expect('https://x').toMatch(/^https?:\\/\\//);"),
    (NODE, "assert.ok(true);"),
    (NODE, "assert(false);"),
    (NODE, "assert.ok(true, 'always');"),
    (NODE, "assert.strictEqual(1, 1);"),
    (NODE, "assert.equal(null, 0, message());"),
    (CHAI, "expect(1).to.equal(1);"),
    (CHAI, "expect(true).to.be.true;"),
    (CHAI, "expect(null).to.exist;"),
    (CHAI, "expect('abc').to.have.lengthOf(3);"),
    (CHAI, "expect(1).to.be.closeTo(1, 0.01);"),
    (CHAI, "expect({ total: 1 }).to.have.property('total', 1);"),
    (CHAI, "expect({ total: 1 }).to.have.property('total');"),
    (CHAI, "assert.isTrue(true);"),
    (CHAI, "assert.propertyVal({ total: 1 }, 'total', 1);"),
    (SHOULD, "(5).should.equal(5);"),
    (AVA, "t.true(true);"),
    (AVA, "t.is(1, 2);"),
    (TAP, "t.ok(1);"),
])
def test_an_assertion_on_literals_alone_reads_as_a_tautology(header, body):
    """Whatever it evaluates to (Q2): a passing one is no oracle, a failing one fails the run."""
    assert _tautology(_assertion(header, body))


@pytest.mark.parametrize("header,body", [
    (VITEST, "expect(total).toBe(1);"),
    (VITEST, "expect(1).toBe(total);"),
    (VITEST, "expect(undefined).toBeUndefined();"),
    (VITEST, "expect(Infinity).toBe(1);"),
    (VITEST, "expect([total]).toEqual([1]);"),
    (VITEST, "expect({ total }).toEqual({ total: 1 });"),
    (VITEST, "expect({ ...base }).toEqual({});"),
    (VITEST, "expect({ [key]: 1 }).toEqual({});"),
    (VITEST, "expect([1, , 2]).toEqual([1, 2]);"),
    (VITEST, "expect(`${total}`).toBe('1');"),
    (VITEST, "expect(`/* ${banner} */`).toBe('/* v1 */');"),
    (VITEST, "expect((0 as number, total)).toBe(0);"),
    (VITEST, "expect(-total).toBe(1);"),
    (VITEST, "expect(!true).toBe(false);"),
    (VITEST, "expect(1 + 1).toBe(2);"),
    (VITEST, "expect(total).toBe(total // was\N{LINE SEPARATOR}+ 1\n);"),
    # SPEC §5's `trivial` reading (a subject of literals and builtins) is a named residual.
    (VITEST, "expect(String(1)).toBe('1');"),
    (VITEST, "expect(1).toEqual(expect.anything());"),
    (VITEST, "expect(1).toBeCloseTo(1, places);"),
    (CHAI, "expect(1).to.be.within(0, limit);"),
    (CHAI, "expect(1).to.be.closeTo(1, delta);"),
    (CHAI, "expect(order).to.have.property('total', 1);"),
])
def test_an_assertion_that_reads_a_name_or_an_expression_keeps_its_rung(header, body):
    assertion = _assertion(header, body)
    assert assertion.form != "tautology"
    assert assertion.strength not in (None, S.TAUTOLOGY)


def test_a_literal_bound_is_not_a_literal_assertion():
    """Rule 2 (#429): `test_js_handrolled_tolerance.py:78` stays a bound, since Q2 reads source operands."""
    assertion = _assertion(NODE, "expect(0.01).toBeGreaterThan(Math.abs(total() - 78.75));")
    assert (assertion.form, assertion.strength, assertion.predicate) == ("compare_ord", S.BOUND, "gt")


@pytest.mark.parametrize("body", ["assert.fail('unreachable');", "expect(1).toHaveLength(1);"])
def test_an_assertion_whose_predicate_is_not_read_keeps_no_strength(body):
    assertion = _assertion(NODE if body.startswith("assert") else VITEST, body)
    assert assertion.strength is None
    assert assertion.form in {"unknown", "raises"}


@pytest.mark.parametrize("operand,literal", [
    ("1", True), ("-1.5e3", True), ("0x1F", True), ("1_000n", True), ("'a'", True), ('"a\\"b"', True),
    ("`plain`", True), ("/a[/]b/gi", True), ("true", True), ("null", True), ("(1)", True),
    ("1 as const", True), ("[]", True), ("{}", True), ("[1, [2, {}],]", True),
    ("{ a: 1, 'b c': null, 2: [] }", True), ("/* c */ 1 // d", True),
    ("undefined", False), ("NaN", False), ("Infinity", False), ("x", False), ("`${x}`", False),
    ("[1,,2]", False), ("[...x]", False), ("{ a }", False), ("{ [a]: 1 }", False),
    ("{ a() { return 1; } }", False), ("{ ...a }", False), ("1 + 1", False), ("-x", False),
    ("--1", False), ("!0", False), ("[1] + [2]", False), ("f(1)", False), ("'a' + 'b'", False),
    ("`it's`", True), ("/'/", True), ("`http://x`", True), ("1e-5 as number", True),
    ("`/* ${a} */`", False), ("0 as number, x", False), ("1 as any || 2", False), ("<!-- 1", False),
    # A `//` comment ends at U+2028 too; a bracket or quote in a regular expression is part of it,
    # and `/[/, x, /]/` is one regular expression, its class holding `/, x, /`.
    ("1 // c\N{LINE SEPARATOR}+ x", False), ("[/[/, x, /]/]", True), ("[/]/, x]", False),
    ("{ a: /}/ }", True), ("`${`a`}`", False),
])
def test_the_literal_reader(operand, literal):
    assert literal_operand(operand) is literal


@pytest.mark.parametrize("left,right,same", [
    ("x", "x", True), ("x", "(x)", True), ("x", "x + 0", True), ("x", "0 + x", True),
    ("x", "x - 0", True), ("x", "x * 1", True), ("x", "1 * x", True), ("x", "x / 1", True),
    ("f(a, b)", "f( a,b )", True), ("x", "x!", True), ("x", "x as T", True),
    ("x", "x + 1", False), ("x", "x + -0", False), ("x", "-x", False), ("x", "0 - x", False),
    ("x", "x * 1 ** 2", False), ("a + b", "a + b * 1", False), ("x", "x << 0", False),
    ("x", "x || 0", False), ("a.b", "a['b']", False), ("x", "y", False), ("x", "", False),
    ("x", "(x as number)", True), ("`a ${x}`", "`a ${x}`", True), ("/a b/", "/a b/", True),
    ("`http://${a}/x`", "`http://${b}/x`", False), ("/  /g", "/ /g", False), ("...p", "...p", False),
    ("v as any || w", "v", False), ("`${`a`}`", "`${`b`}`", False),
    ("total", "total // was\N{LINE SEPARATOR}+ 1\n", False), ("(a + b) / 2", "(a + b) / 2", True),
    # A `/` after a statement head or a block may start a regular expression: unread.
    ("run(() => { if (ok) / a/.test(s) })", "run(() => { if (ok) /a/.test(s) })", False),
    ("run(() => { {} / a/.test(s) })", "run(() => { {} /a/.test(s) })", False),
    # A quote or bracket in a regular expression hides no operator.
    ("f(/'/) || g(/'/) + 0", "f(/'/) || g(/'/)", False), ("f(/\\(/) || g(/\\)/) + 0", "f(/\\(/) || g(/\\)/)", False),
    ("`${`a`}`", "(`${`a`}`)", True), ("`${ x // }`\n}`", "`${ x // }`\n}`", True),
    ("`${ a / b }`", "`${ a / b }`", False),
    # A cast to one named type binds before the no-op arithmetic around it, as TypeScript reads it.
    ("total", "total as number + 0", True), ("total", "0 + total as number", True),
    ("total", "total satisfies number + 0", True), ("x", "x as T + 1", False), ("x", "x as T * 2", False),
])
def test_the_operand_comparison(left, right, same):
    assert same_operand(left, right) is same
    assert same_operand(right, left) is same


# --- Q6: how a tautology is recorded, and what it changes -------------------------------------

@pytest.mark.parametrize("header,before,after", [
    (VITEST, "expect(total).toBe(27);", "expect(total).toBe(total);"),
    (NODE, "assert.strictEqual(total, 27);", "assert.strictEqual(total, total);"),
    (CHAI, "expect(total).to.equal(27);", "expect(total).to.equal(total);"),
    (AVA, "t.is(total, 27);", "t.is(total, total);"),
    (VITEST, "expect(total).toBe(27);", "expect(total).toBe((total as number) + 0);"),
    (VITEST, "expect(total).toBe(27);", "expect(total).toBe(total as number + 0);"),
])
def test_a_self_comparison_in_an_oracles_place_is_weakened(header, before, after):
    """The pair no longer reads as two spellings of `eq_strict`: the lattice judges it."""
    setup = "const total = await checkout([10, 20]);\n  "
    verdict, findings = _outcome(header, setup + before, setup + after)
    assert verdict == "block"
    assert [(f.rule, f.severity) for f in findings] == [("ASSERT_WEAKENED", "high")]
    assert findings[0].message.endswith("strength EXACT_VALUE(90) -> TAUTOLOGY(10)")


def test_a_self_comparison_on_a_local_bound_to_one_call_is_weakened_not_redefined():
    """As in Python (Q6): ASSERT_WEAKENED instead of EXPECTATION_DEFINITION_CHANGED."""
    header = VITEST + 'import { add } from "../src/math";\n'
    setup = "const sum = add(1, 2);\n  "
    verdict, findings = _outcome(header, setup + "expect(sum).toBe(3);", setup + "expect(sum).toBe(sum);")
    assert verdict == "block"
    assert [f.rule for f in findings] == ["ASSERT_WEAKENED"]


def test_a_literal_in_an_oracles_place_is_weakened():
    verdict, findings = _outcome(VITEST, "expect(total([1, 2])).toBe(3);", "expect(3).toBe(3);")
    assert verdict == "block"
    assert [(f.rule, f.severity) for f in findings] == [("ASSERT_WEAKENED", "high")]


def test_a_literal_only_test_cannot_pay_for_a_deleted_one():
    """Compensation counts strong assertions that can fail, and a tautology is none (SPEC §5).

    Read as the old test renamed, the pair is weakened; read as a new test,
    it adds no oracle mass to hold the deleted one at warn.
    """
    before = VITEST + 'it("applies tax", () => {\n  expect(total([50, 50], 0.05)).toBe(105);\n});\n'
    after = VITEST + 'it("pads the suite", () => {\n  expect(105).toBe(105);\n});\n'
    change = FileChange(PATH, "modified", before.encode(), after.encode())
    _ir, findings, verdict = analyze([change], Config(), Contract(), [], datetime.date(2026, 10, 17))
    assert verdict == "block"
    assert any(f.severity == "high" and f.rule in {"TEST_DISABLED", "ASSERT_WEAKENED"} for f in findings)


@pytest.mark.parametrize("before,after", [
    ("expect(1).toBe(1); expect(subject()).toBe(42);", "expect(1).toBe(1); expect(subject()).toBe(42);"),
    ("expect(1).toBe(1); expect(subject()).toBe(42);", "expect( 1 ).toBe( 1 );\n  expect(subject()).toBe(42);"),
    ("expect(total).toBe(total);", "expect(total).toBe(total);  // unchanged"),
])
def test_an_unchanged_tautology_reports_nothing(before, after):
    verdict, findings = _outcome(VITEST, before, after)
    assert (verdict, findings) == ("pass", [])


def test_a_removed_literal_assertion_keeps_its_fingerprint(monkeypatch):
    """Rule 2 (#429): Q6 keeps `left`, so the legacy identity still reads the matcher prefix.

    Since #421 the key is content-bound. As `tests/test_js_assertion_identity.py`
    pins it, the identity the key is computed from holds the legacy pre-image,
    spelled here independently of either parser.
    """
    seen = []
    real = findings_module.assertion_identity

    def record(*args, **kwargs):
        seen.append(real(*args, **kwargs))
        return seen[-1]

    monkeypatch.setattr(findings_module, "assertion_identity", record)
    path = "tests/identity.test.ts"
    _verdict, findings = _outcome(VITEST, "expect(1).toBe(1); expect(subject()).toBe(42);",
                                  "expect(subject()).toBe(42);", path)
    finding, = [finding for finding in findings if finding.rule == "ASSERT_REMOVED"]
    legacy = f"ASSERT_REMOVED/{path}/sample/expect(1).toBe("
    assert finding.fingerprint.startswith(f"ASSERT_REMOVED/{path}/sample/v2:")
    assert finding.fingerprint in {assertion_key(i) for i in seen if i["legacy"] == legacy}
    assert finding.before.text == "expect(1).toBe(1)"
    assert finding.message.endswith("assertion removed (strength TAUTOLOGY)")


@pytest.mark.parametrize("body", [
    "expect(1).toBe(1);", "expect(total).toBe(total + 0);", "assert.strictEqual(1, 1);",
])
def test_a_tautology_keeps_its_subject_text_span_and_operand(body):
    header = VITEST + 'import assert from "node:assert";\n'
    source = _source(header, body)
    assertion, = [a for unit in parse_javascript(source.encode()).units for a in unit.side.assertions]
    assert assertion.text == body.rstrip(";")
    assert source[assertion.span[0]:assertion.span[1]] == assertion.text
    assert assertion.left == ("total" if "total" in body else "1")
    assert assertion.operand_source == ("total + 0" if "total" in body else "1")


def test_the_catch_proof_reads_the_predicate_before_it_is_dropped():
    """#431 is unchanged: its proof reads the key and polarity the assertion spells."""
    parsed = parse_javascript(_source(
        VITEST, "try { expect(value()).toBe(1); } catch (error) { expect(true).toBe(true); }").encode())
    assert parsed.swallowing_handlers == (ALWAYS_PASSING,)
    guarded, caught = parsed.units[0].side.assertions
    assert (guarded.form, guarded.strength, guarded.predicate) == ("compare_eq", S.EXACT_VALUE, "eq_strict")
    assert _tautology(caught)

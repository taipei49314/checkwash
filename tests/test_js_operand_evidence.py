"""Issue #198, the evidence half: JS operands as evidence across assertion APIs.

The first half (`tests/test_js_predicate.py`) made each spelling state its
predicate. A pair could still read as preserved while its evidence was lost:
`toBe(78.75)` -> `assert.equal(value, 75)` passed because `==` recorded no
expected value (M2a-c), and `toBeCloseTo(v, 2)` -> `.closeTo(v, Infinity)`
because a delta of Infinity, `Number.MAX_VALUE` or a name recorded no
tolerance (M2f-h). The rulings: `assert.equal` keeps every scalar the strict
reader reads (196.190.2), a closeTo delta is read as a hand-rolled bound is
(196.190.4), JS bounds record their operand (198.Q2, Q4), the literal reader
reads through parentheses and TypeScript wrappers (198.Q3, T4 and T5), a
hand-rolled `<` -> `>` flip is a reversed bound (196.189.3), and `operand_source`
decides only whether two spellings state the same operand (198.IR).

Values and verdicts are written from the libraries' documented behaviour and
from the rulings, not read from the frontend.
"""
import datetime
import functools

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze
from checkwash.frontends.javascript.frontend import comparison_magnitude, parse_javascript
from checkwash.frontends.javascript.literals import operand_names, operand_text

TEST = "src/total.test.ts"
VITEST = 'import { test, expect, assert } from "vitest";\n'
NODE = 'import { test, expect } from "vitest";\nimport assert from "node:assert";\n'
BLOCK, PASS = "block", "pass"
SUBJECT = "Math.abs(value - 78.75)"


def _source(body, header=VITEST, prelude=""):
    return (header + 'import { total } from "./total";\n' + prelude
            + 'test("total", () => {\n  const value = total();\n  ' + body + "\n});\n")


@functools.lru_cache(maxsize=None)
def _outcome(before, after, header=VITEST, prelude=""):
    changes = [FileChange(TEST, "modified", _source(before, header, prelude).encode(),
                          _source(after, header, prelude).encode())]
    _ir, findings, verdict = analyze(changes, Config(), Contract(), [], datetime.date(2026, 10, 3))
    return verdict, tuple((f.rule, f.severity) for f in findings), tuple(f.message for f in findings)


def _assertion(body, header=VITEST, prelude=""):
    found = [a for unit in parse_javascript(_source(body, header, prelude).encode()).units
             for a in unit.side.assertions]
    return found[-1]


def _check(observed, verdict, expected):
    got, findings, messages = observed
    assert got == verdict, messages
    if expected is None:
        assert findings == (), messages
    else:
        for rule, severity, text in expected:
            assert any(f == (rule, severity) and text in m for f, m in zip(findings, messages)), messages


# --- The operand readers ------------------------------------------------------------------

@pytest.mark.parametrize("source,text", [
    ("75", "75"),
    ("  (75)  ", "75"),
    ("75 as number", "75"),
    ("(LIMIT satisfies number)", "LIMIT"),
    ("value!", "value"),
    ("make( a ,\n   b ) /* note */", "make( a , b )"),
    ("'a  b'", "'a  b'"),
    ("a ? b as T : c", "a ? b as T : c"),
    ("x + 1 as T", "x + 1 as T"),
    ("42 as const + 1", "42 as const + 1"),
    ("'unterminated", None),
])
def test_operand_text_is_one_canonical_line(source, text):
    assert operand_text(source) == text


@pytest.mark.parametrize("source,names", [
    ("EXPECTED", ("EXPECTED",)),
    ("make(items)", ("items", "make")),
    ("cfg.limit", ("cfg",)),
    ("cfg?.limit", ("cfg",)),
    ("{ id: user.id, name }", ("name", "user")),
    ("x ? y : z", ("x", "y", "z")),
    ("'EXPECTED' + suffix", ("suffix",)),
    ("[...rest, last]", ("last", "rest")),
    ("new Total(rate)", ("Total", "rate")),
    ("78.75", ()),
    ("undefined", ()),
    ("Infinity", ()),
])
def test_operand_names_are_what_python_reads_on_an_expected_side(source, names):
    assert operand_names(source) == names


@pytest.mark.parametrize("source,magnitude", [
    (f"{SUBJECT} < 0.01", "Math.abs(value-78.75)"),
    (f"0.01 > {SUBJECT}", "Math.abs(value-78.75)"),
    (f"{SUBJECT} > 0.01", "Math.abs(value-78.75)"),
    (f"(({SUBJECT} <= eps))", "Math.abs(value-78.75)"),
    ("value < 0.01", None),
    (f"{SUBJECT} < 0.01 && ready()", None),
])
def test_comparison_magnitude_is_the_abs_side(source, magnitude):
    assert comparison_magnitude(source) == magnitude


# --- What each spelling records -----------------------------------------------------------

@pytest.mark.parametrize("body,header,value,operand", [
    # 190.2: `==` keeps its scalar; eq_loose carries the coercion.
    ("assert.equal(value, 75);", VITEST, "75.0", "75"),
    ("assert.equal(value, '75');", VITEST, "'75'", "'75'"),
    ("assert.equal(value, null);", VITEST, "None", "null"),
    ("assert.equal(value, 75);", NODE, "75.0", "75"),
    ("assert.deepEqual(value, 75);", NODE, "75.0", "75"),
    # 198.Q2: a bound is recorded as a Python bound is.
    ("expect(value).toBeLessThan(80);", VITEST, "80.0", "80"),
    ("expect(value).to.be.below(1e12);", VITEST, "1000000000000.0", "1e12"),
    ("assert.isAtMost(value, 80);", VITEST, "80.0", "80"),
    ("expect(value).toBeGreaterThanOrEqual(LIMIT);", VITEST, None, "LIMIT"),
    # T4, T5: what evaluates to the literal reads as the literal.
    ("expect(value).toBe((75));", VITEST, "75.0", "75"),
    ("expect(value).toBe(75 as number);", VITEST, "75.0", "75"),
    ("expect(value).toBe(75 satisfies number);", VITEST, "75.0", "75"),
    # T6: Number(<literal>) folds to its value (#226).
    ("expect(value).toBe(Number(75));", VITEST, "75.0", "Number(75)"),
    ("expect(value).toBe(Number('78.75'));", VITEST, "78.75", "Number('78.75')"),
    # A call checkwash does not fold keeps its text only.
    ("expect(value).toBe(Number('0x10'));", VITEST, None, "Number('0x10')"),
])
def test_each_spelling_records_its_operand(body, header, value, operand):
    assertion = _assertion(body, header)
    assert (assertion.right_value, assertion.operand_source) == (value, operand)


@pytest.mark.parametrize("body,key,operand,epsilon", [
    # The bound of a hand-rolled tolerance is tolerance evidence only (198.Q2).
    (f"expect({SUBJECT}).toBeLessThan(0.01);", "lt", "0.01", "abs=0.01"),
    (f"expect({SUBJECT}).toBeLessThan(tolerance());", "lt", None, None),
    # The truthy spelling states the bound key, either way round (189.3).
    (f"assert.ok({SUBJECT} < 0.01);", "lt", "0.01", "abs=0.01"),
    (f"assert.ok(0.01 >= {SUBJECT});", "le", "0.01", "abs=0.01"),
    (f"assert.ok({SUBJECT} > 0.01);", "gt", "0.01", None),
    (f"assert.ok({SUBJECT} > tolerance());", "gt", None, None),
    (f"expect({SUBJECT} < 0.01).toBe(true);", "lt", "0.01", "abs=0.01"),
    (f"expect({SUBJECT} >= 0.01).toBeTruthy();", "ge", "0.01", None),
])
def test_a_hand_rolled_bound_states_its_direction(body, key, operand, epsilon):
    assertion = _assertion(body, NODE)
    assert (assertion.predicate, assertion.positive) == (key, True)
    assert (assertion.operand_source, assertion.epsilon) == (operand, epsilon)
    # Never the bound: what the magnitude measures, and its centre (189.2).
    assert (assertion.left, assertion.right_value) == ("value", "78.75")


@pytest.mark.parametrize("body,form,key,positive", [
    # 198.Q3: an asymmetric matcher is the predicate it states.
    ("expect(value).toEqual(expect.anything());", "non_null", "is_nullish", False),
    ("expect(value).not.toEqual(expect.anything());", "non_null", "is_nullish", True),
    ("expect(value).toStrictEqual(expect.any(Number));", "type_shape", None, True),
    ("expect(value).toEqual(expect.objectContaining({ a: 1 }));", "compare_eq", None, True),
    ("expect(value).toEqual(other.anything());", "compare_eq", None, True),
])
def test_asymmetric_matchers_state_their_own_predicate(body, form, key, positive):
    assertion = _assertion(body)
    assert (assertion.form, assertion.predicate, assertion.positive) == (form, key, positive)


# --- The issue's rows ---------------------------------------------------------------------

@pytest.mark.parametrize("before,after,header,prelude,verdict,expected", [
    # M2: known evidence into a spelling that recorded none (190.2, 190.4).
    ("expect(value).toBe(78.75);", "assert.equal(value, 75);", VITEST, "", BLOCK, [
        ("ASSERT_WEAKENED", "warn", "predicate widened (=== 78.75 -> == 75)"),
        ("EXPECTED_VALUE_CHANGED", "high", "expected value rewritten 78.75 -> 75.0")]),
    ("expect(value).toEqual(78.75);", "assert.equal(value, 75);", VITEST, "", BLOCK, [
        ("EXPECTED_VALUE_CHANGED", "high", "expected value rewritten 78.75 -> 75.0")]),
    ("expect(value).toBe(78.75);", "assert.equal(value, '75');", VITEST, "", BLOCK, [
        ("EXPECTED_VALUE_CHANGED", "high", "expected value rewritten 78.75 -> '75'")]),
    ("expect(value).toBeCloseTo(78.75, 2);", "expect(value).to.be.closeTo(78.75, Infinity);", VITEST, "",
     BLOCK, [("TOLERANCE_LOOSENED", "high", "(places=2 -> abs=Infinity)")]),
    ("expect(value).toBeCloseTo(78.75, 2);", "expect(value).to.be.closeTo(78.75, Number.MAX_VALUE);", VITEST,
     "", BLOCK, [("TOLERANCE_LOOSENED", "high", "(places=2 -> abs=1797693134862315708")]),
    ("expect(value).toBeCloseTo(78.75, 2);", "expect(value).to.be.closeTo(78.75, BIG);", VITEST,
     "const BIG = 1e300;\n", BLOCK, [("TOLERANCE_LOOSENED", "high", "(places=2 -> abs=1E+300)")]),
    # Twins: node:assert's legacy equal and deepEqual (T1, T2), and the
    # literal reader's parentheses and TS wrappers (T4, T5), and T6, a
    # Number(<literal>) folded to its value (#226).
    ("expect(value).toBe(78.75);", "assert.equal(value, 75);", NODE, "", BLOCK, [
        ("EXPECTED_VALUE_CHANGED", "high", "expected value rewritten 78.75 -> 75.0")]),
    ("expect(value).toBe(78.75);", "assert.deepEqual(value, 75);", NODE, "", BLOCK, [
        ("EXPECTED_VALUE_CHANGED", "high", "78.75 -> 75.0 despite increased assertion strength")]),
    ("expect(value).toBe(78.75);", "expect(value).toBe((75));", VITEST, "", BLOCK, [
        ("EXPECTED_VALUE_CHANGED", "high", "expected value rewritten 78.75 -> 75.0")]),
    ("expect(value).toBe(78.75);", "expect(value).toBe(75 as number);", VITEST, "", BLOCK, [
        ("EXPECTED_VALUE_CHANGED", "high", "expected value rewritten 78.75 -> 75.0")]),
    ("expect(value).toBe(78.75);", "expect(value).toBe(Number(75));", VITEST, "", BLOCK, [
        ("EXPECTED_VALUE_CHANGED", "high", "expected value rewritten 78.75 -> 75.0")]),
    # The bound operand (O1, O2).
    ("expect(value).toBeLessThan(80);", "expect(value).to.be.below(1e12);", VITEST, "", BLOCK, [
        ("EXPECTED_VALUE_CHANGED", "high", "expected value rewritten 80.0 -> 1000000000000.0")]),
    ("expect(value).toBeLessThan(80);", "expect(value).toBeLessThan(1e12);", VITEST, "", BLOCK, [
        ("EXPECTED_VALUE_CHANGED", "high", "expected value rewritten 80.0 -> 1000000000000.0")]),
    # chai to chai (B3, B4).
    ("assert.equal(value, 78.75);", "assert.equal(value, 75);", VITEST, "", BLOCK, [
        ("EXPECTED_VALUE_CHANGED", "high", "expected value rewritten 78.75 -> 75.0")]),
    ("expect(value).to.equal(78.75);", "assert.equal(value, 75);", VITEST, "", BLOCK, [
        ("EXPECTED_VALUE_CHANGED", "high", "expected value rewritten 78.75 -> 75.0")]),
    # Honest controls keep passing: one operand on both sides (H4, H5, H6).
    ("expect(value).toBe(78.75);", "assert.equal(value, 78.75);", VITEST, "", PASS, [
        ("ASSERT_WEAKENED", "warn", "predicate widened (=== 78.75 -> == 78.75)")]),
    ("expect(value).toBeCloseTo(78.75, 2);", "expect(value).to.be.closeTo(78.75, 0.005);", VITEST, "", PASS,
     None),
    ("expect(value).toBeLessThan(80);", "expect(value).to.be.below(80);", VITEST, "", PASS, None),
    ("expect(value).toBeLessThan(LIMIT);", "assert.isBelow(value, LIMIT);", VITEST, "", PASS, None),
])
def test_issue_rows(before, after, header, prelude, verdict, expected):
    _check(_outcome(before, after, header, prelude), verdict, expected)


# --- 189.3: the hand-rolled flip -------------------------------------------------------------

@pytest.mark.parametrize("before,after,verdict,expected", [
    (f"assert.ok({SUBJECT} < 0.01);", f"assert.ok({SUBJECT} > 0.01);", BLOCK, [
        ("ASSERT_WEAKENED", "high", "bound direction reversed (< 0.01 -> > 0.01)")]),
    (f"assert.ok({SUBJECT} < 0.01);", f"assert.ok(0.01 < {SUBJECT});", BLOCK, [
        ("ASSERT_WEAKENED", "high", "bound direction reversed (< 0.01 -> > 0.01)")]),
    (f"assert.ok({SUBJECT} < 0.01);", f"assert.ok({SUBJECT} > tolerance());", BLOCK, [
        ("ASSERT_WEAKENED", "high", "cannot verify the replacement is equivalent (predicate < 0.01 -> > bound)")]),
    (f"expect({SUBJECT} < 0.01).toBeTruthy();", f"expect({SUBJECT} >= 0.01).toBeTruthy();", BLOCK, [
        ("ASSERT_WEAKENED", "high", "bound direction reversed (< 0.01 -> >= 0.01)")]),
    # The truthy and matcher spellings name one magnitude.
    (f"assert.ok({SUBJECT} < 0.01);", f"expect({SUBJECT}).toBeGreaterThan(0.01);", BLOCK, [
        ("ASSERT_WEAKENED", "high", "bound direction reversed (< 0.01 -> > 0.01)")]),
    # One bound: `<` -> `<=` also passes the bound itself.
    (f"assert.ok({SUBJECT} < 0.01);", f"assert.ok({SUBJECT} <= 0.01);", BLOCK, [
        ("ASSERT_WEAKENED", "high", "predicate widened (< 0.01 -> <= 0.01)")]),
    # Unchanged direction and bound, respelled: nothing to report.
    (f"assert.ok({SUBJECT} < 0.01);", f"assert.ok(0.01 > {SUBJECT});", PASS, None),
    (f"expect({SUBJECT} < 0.01).toBe(true);", f"assert.ok({SUBJECT} < 0.01);", PASS, None),
    # A magnitude replaced is a different check, judged as before.
    (f"assert.ok({SUBJECT} < 0.01);", "assert.ok(Math.abs(other - 78.75) > 0.01);", PASS, None),
])
def test_a_flipped_hand_rolled_bound_is_reported(before, after, verdict, expected):
    _check(_outcome(before, after, NODE), verdict, expected)


# --- Unknown tolerance evidence (190.4) ------------------------------------------------------

@pytest.mark.parametrize("before,after,verdict,expected", [
    ("expect(value).toBeCloseTo(78.75, 2);", "expect(value).to.be.closeTo(78.75, delta());", BLOCK, [
        ("ASSERT_WEAKENED", "high", "(tolerance places=2 -> a tolerance it cannot read)")]),
    ("expect(value).to.be.closeTo(78.75, 0.005);", "expect(value).toBeCloseTo(78.75, precision());", BLOCK, [
        ("ASSERT_WEAKENED", "high", "(tolerance abs=0.005 -> a tolerance it cannot read)")]),
    ("assert.closeTo(value, 78.75, 0.005);", "assert.closeTo(value, 78.75, EPSILON_FROM_CONFIG);", BLOCK, [
        ("ASSERT_WEAKENED", "high", "(tolerance abs=0.005 -> a tolerance it cannot read)")]),
    # Unknown before is no loss; two unknown deltas stay unjudged.
    ("expect(value).to.be.closeTo(78.75, delta());", "expect(value).to.be.closeTo(78.75, 0.005);", PASS, None),
    ("expect(value).to.be.closeTo(78.75, delta());", "expect(value).to.be.closeTo(78.75, other());", PASS,
     None),
    # A negated comparison records no tolerance; its polarity decides.
    ("expect(value).toBeCloseTo(78.75, 2);", "expect(value).not.toBeCloseTo(78.75, 2);", BLOCK, [
        ("ASSERT_WEAKENED", "high", "polarity inverted")]),
])
def test_a_known_tolerance_lost_to_an_unread_one_is_not_preserved(before, after, verdict, expected):
    _check(_outcome(before, after), verdict, expected)


# --- Names and calls (198.IR amendment 2) ------------------------------------------------------

@pytest.mark.parametrize("before,after,verdict,expected", [
    ("expect(value).toBe(EXPECTED_A);", "expect(value).toBe(EXPECTED_B);", BLOCK, [
        ("EXPECTED_VALUE_CHANGED", "high", "expected call rewritten to a different call ['EXPECTED_A'] -> "
         "['EXPECTED_B']")]),
    ("expect(value).toEqual(build(items));", "expect(value).toEqual(rebuild(items));", BLOCK, [
        ("EXPECTED_VALUE_CHANGED", "high", "['build', 'items'] -> ['items', 'rebuild']")]),
    ("expect(value).toBeLessThan(LIMIT);", "expect(value).toBeLessThan(OTHER_LIMIT);", BLOCK, [
        ("EXPECTED_VALUE_CHANGED", "high", "['LIMIT'] -> ['OTHER_LIMIT']")]),
    # As in Python since #226: a call whose callee the file never declares is
    # an expression checkwash does not evaluate, so a changed argument reports
    # (226.Q1, Q3), while the same names with a member changed pass.
    ("expect(value).toBe(build(1));", "expect(value).toBe(build(2));", BLOCK, [
        ("EXPECTED_VALUE_CHANGED", "high",
         "expected value replaced by an expression checkwash does not evaluate (build(1) -> build(2))")]),
    ("expect(value).toBe(config.total);", "expect(value).toBe(config.subtotal);", PASS, None),
    ("expect(value).toBe(EXPECTED);", "expect(value).toBe((EXPECTED as number));", PASS, None),
    # A name nothing declares is neither resolved nor a call (#226), and a
    # name or call replaced by a literal is not read in JS yet (#292).
    ("expect(value).toBe(78.75);", "expect(value).toBe(EXPECTED);", PASS, None),
    ("expect(value).toBe(EXPECTED);", "expect(value).toBe(78.75);", PASS, None),
])
def test_a_name_or_call_replaced_by_another_is_an_expected_value_change(before, after, verdict, expected):
    _check(_outcome(before, after), verdict, expected)


def test_a_hand_rolled_bound_name_is_tolerance_evidence_not_an_expected_value():
    # Both bounds are read through their declarations, so TOLERANCE_LOOSENED
    # compares the values; the names are not an expected-value change.
    prelude = "const EPS = 0.01;\nconst WIDE = 1e12;\n"
    _check(_outcome(f"expect({SUBJECT}).toBeLessThan(EPS);", f"expect({SUBJECT}).toBeLessThan(WIDE);",
                    NODE, prelude),
           BLOCK, [("TOLERANCE_LOOSENED", "high", "(abs=0.01 -> abs=1E+12)")])
    assert len(_outcome(f"expect({SUBJECT}).toBeLessThan(EPS);", f"expect({SUBJECT}).toBeLessThan(WIDE);",
                        NODE, prelude)[1]) == 1


# --- Asymmetric matchers (198.Q3) ----------------------------------------------------------------

@pytest.mark.parametrize("before,after,verdict,expected", [
    ("expect(value).toBe(78.75);", "expect(value).toEqual(expect.anything());", BLOCK, [
        ("ASSERT_WEAKENED", "high", "predicate widened (=== 78.75 -> != null)")]),
    ("expect(value).toBe(78.75);", "expect(value).toEqual(expect.any(Number));", BLOCK, [
        ("ASSERT_WEAKENED", "high", "EXACT_VALUE(90) -> TYPE_SHAPE(50)")]),
    ("expect(value).toBeDefined();", "expect(value).toEqual(expect.anything());", PASS, None),
    ("expect(value).toEqual(expect.anything());", "expect(value).toBeNull();", BLOCK, [
        ("ASSERT_WEAKENED", "high", "contradicts")]),
])
def test_an_asymmetric_matcher_is_judged_as_its_predicate(before, after, verdict, expected):
    _check(_outcome(before, after), verdict, expected)

"""Issue #198: JS assertion identity across assertion APIs (predicate identity).

A Jest matcher replaced by a chai spelling that asserts something else passed
v0.5.0, because the lattice gives different predicates one rung:
`toBeNull()` and `.to.exist` are both NON_NULL, `toBeLessThan(80)` and
`.to.be.above(80)` both BOUND. Each spelling now records a predicate key, and
`positive` says whether it asserts that key or its negation (ruling 198.IR).
ASSERT_WEAKENED compares two keyed assertions on one subject by that relation
instead of the lattice (198.Q1, 198.Q4), `@jest/globals` gets its own module
kind (198.Q5) and `node:assert/strict` its strict mode (198.Q3).

Keys, polarities and the value semantics below are written from Jest's,
chai's and Node's documented behaviour, not read from the frontend tables, so
dropping or misreading a spelling fails here. The evidence half of #198
(operand evidence, M2a-c and M2f-h) is a later round.
"""
import datetime
import functools
import math

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze
from checkwash.frontends.javascript.coverage import javascript_coverage_gaps
from checkwash.frontends.javascript.frontend import parse_javascript
from checkwash.ir import predicate as P
from checkwash.ir.model import Assertion

TEST = "src/total.test.ts"
VITEST = 'import { test, expect, assert } from "vitest";\n'
HEADERS = {
    "vitest": VITEST,
    "chai": 'import { test, expect } from "vitest";\nimport { assert } from "chai";\n',
    "node": 'import { test, expect } from "vitest";\nimport assert from "node:assert";\n',
    "node_strict": 'import { test, expect } from "vitest";\nimport assert from "node:assert/strict";\n',
    "jest": 'import { test, expect } from "@jest/globals";\n',
}
PROD = FileChange("src/total.ts", "modified", b"export function total() {\n  return 78.75;\n}\n",
                  b"export function total() {\n  return 75;\n}\n")


def _source(body, header=VITEST):
    return (header + 'import { total } from "./total";\n'
            + 'test("total", () => {\n  const value = total();\n  ' + body + "\n});\n")


@functools.lru_cache(maxsize=None)
def _outcome(before, after, header=VITEST, prod=False):
    changes = [FileChange(TEST, "modified", _source(before, header).encode(), _source(after, header).encode())]
    if prod:
        changes.append(PROD)
    _ir, findings, verdict = analyze(changes, Config(), Contract(), [], datetime.date(2026, 10, 3))
    return verdict, tuple((f.rule, f.severity) for f in findings), tuple(f.message for f in findings)


def _assertion(body, header=VITEST):
    assertion, = [a for unit in parse_javascript(_source(body, header).encode()).units for a in unit.side.assertions]
    return assertion


# --- What each spelling states -----------------------------------------------

@pytest.mark.parametrize("body,header,key,positive", [
    # Jest. toBeDefined() asserts is_undefined negatively, like .not.toBeUndefined().
    ("expect(value).toBeNull();", VITEST, "is_null", True),
    ("expect(value).not.toBeNull();", VITEST, "is_null", False),
    ("expect(value).toBeUndefined();", VITEST, "is_undefined", True),
    ("expect(value).toBeDefined();", VITEST, "is_undefined", False),
    ("expect(value).not.toBeDefined();", VITEST, "is_undefined", True),
    ("expect(value).toBeTruthy();", VITEST, "truthy", True),
    ("expect(value).toBeFalsy();", VITEST, "truthy", False),
    ("expect(value).not.toBeFalsy();", VITEST, "truthy", True),
    ("expect(value).toBe(null);", VITEST, "is_null", True),
    ("expect(value).toBe(undefined);", VITEST, "is_undefined", True),
    ("expect(value).toBe(/* answer */ true);", VITEST, "is_true", True),
    ("expect(value).not.toBe(false);", VITEST, "is_false", False),
    ("expect(value).toBe(78.75);", VITEST, "eq_strict", True),
    ("expect(value).toBe(expected);", VITEST, "eq_strict", True),
    ("expect(value).toBeLessThan(80);", VITEST, "lt", True),
    ("expect(value).toBeLessThanOrEqual(80);", VITEST, "le", True),
    ("expect(value).toBeGreaterThan(80);", VITEST, "gt", True),
    ("expect(value).not.toBeGreaterThanOrEqual(80);", VITEST, "ge", False),
    # chai expect chains.
    ("expect(value).to.be.null;", VITEST, "is_null", True),
    ("expect(value).to.not.be.undefined;", VITEST, "is_undefined", False),
    ("expect(value).to.exist;", VITEST, "is_nullish", False),
    ("expect(value).to.not.exist;", VITEST, "is_nullish", True),
    ("expect(value).to.be.ok;", VITEST, "truthy", True),
    ("expect(value).to.not.be.ok;", VITEST, "truthy", False),
    ("expect(value).to.be.true;", VITEST, "is_true", True),
    ("expect(value).to.be.false;", VITEST, "is_false", True),
    ("expect(value).to.equal(null);", VITEST, "is_null", True),
    ("expect(value).to.not.equal(undefined);", VITEST, "is_undefined", False),
    ("expect(value).to.equal(78.75);", VITEST, "eq_strict", True),
    ("expect(value).to.be.above(80);", VITEST, "gt", True),
    ("expect(value).to.be.greaterThan(80);", VITEST, "gt", True),
    ("expect(value).to.be.at.least(80);", VITEST, "ge", True),
    ("expect(value).to.be.gte(80);", VITEST, "ge", True),
    ("expect(value).to.be.below(80);", VITEST, "lt", True),
    ("expect(value).to.be.lessThan(80);", VITEST, "lt", True),
    ("expect(value).to.be.at.most(80);", VITEST, "le", True),
    ("expect(value).to.not.be.lte(80);", VITEST, "le", False),
    # chai's assert interface, as Vitest re-exports it.
    ("assert.isNull(value);", VITEST, "is_null", True),
    ("assert.isUndefined(value);", VITEST, "is_undefined", True),
    ("assert.isDefined(value);", VITEST, "is_undefined", False),
    ("assert.exists(value);", VITEST, "is_nullish", False),
    ("assert.isOk(value);", VITEST, "truthy", True),
    ("assert(value);", VITEST, "truthy", True),
    ("assert.isTrue(value);", VITEST, "is_true", True),
    ("assert.isFalse(value);", VITEST, "is_false", True),
    ("assert.strictEqual(value, null);", VITEST, "is_null", True),
    ("assert.strictEqual(value, 78.75);", VITEST, "eq_strict", True),
    # chai's assert.equal is ==: == null and == undefined are one predicate.
    ("assert.equal(value, null);", VITEST, "is_nullish", True),
    ("assert.equal(value, undefined);", VITEST, "is_nullish", True),
    ("assert.equal(value, true);", VITEST, "eq_loose", True),
    ("assert.equal(value, 78.75);", VITEST, "eq_loose", True),
    ("assert.isAbove(value, 80);", VITEST, "gt", True),
    ("assert.isAtLeast(value, 80);", VITEST, "ge", True),
    ("assert.isBelow(value, 80);", VITEST, "lt", True),
    ("assert.isAtMost(value, 80);", VITEST, "le", True),
    # node:assert, legacy and strict mode.
    ("assert.ok(value);", HEADERS["node"], "truthy", True),
    ("assert(value);", HEADERS["node"], "truthy", True),
    ("assert.strictEqual(value, undefined);", HEADERS["node"], "is_undefined", True),
    ("assert.equal(value, 78.75);", HEADERS["node"], "eq_loose", True),
    ("assert.equal(value, null);", HEADERS["node"], "is_nullish", True),
    ("assert.equal(value, 78.75);", HEADERS["node_strict"], "eq_strict", True),
    ("assert.equal(value, null);", HEADERS["node_strict"], "is_null", True),
    ("assert.equal(value, false);", HEADERS["node_strict"], "is_false", True),
])
def test_each_spelling_states_its_predicate(body, header, key, positive):
    assertion = _assertion(body, header)
    assert (assertion.predicate, assertion.positive) == (key, positive)


@pytest.mark.parametrize("body", [
    "expect(value).toEqual(78.75);",
    "expect(value).toStrictEqual({ total: 78.75 });",
    "expect(value).toBeCloseTo(78.75, 2);",
    "expect(value).toContain(78.75);",
    "expect(value).to.deep.equal([78.75]);",
    "expect(value).to.be.within(70, 80);",
    "expect(value).to.include(78.75);",
    "assert.deepEqual(value, [78.75]);",
    "assert.closeTo(value, 78.75, 0.01);",
])
def test_spellings_without_a_key_keep_the_lattice(body):
    assert _assertion(body).predicate is None


def test_a_shadowed_undefined_is_an_operand_not_the_global():
    assertion = _assertion("const undefined = 0;\n  expect(value).toBe(undefined);")
    assert assertion.predicate == "eq_strict"


# --- The relation ---------------------------------------------------------------

def _keyed(key, positive=True, literal=None, form=None, operand=None):
    if form is None:
        form = "compare_ord" if key in P.BOUNDS else "non_null"
    assertion = Assertion(id="a0", form=form, strength=30, text="", span=(0, 0), left="value",
                          positive=positive, predicate=key, operand_source=operand)
    if literal is not None:
        assertion.right_literal, assertion.right_value = literal, literal
        if key not in P.BOUNDS:
            assertion.form = "compare_eq"
    return assertion


def _hand_rolled(key, operand="0.01"):
    """`assert.ok(Math.abs(d) <op> operand)`: a bound key on the truthy spelling."""
    assertion = _keyed(key, form="truthy", operand=operand)
    if operand is not None and key in {"lt", "le"}:
        assertion.epsilon, assertion.epsilon_kind = f"abs={operand}", "abs"
    return assertion


@pytest.mark.parametrize("old,new,relation", [
    (_keyed("is_null"), _keyed("is_null"), P.SAME),
    (_keyed("is_null"), _keyed("is_nullish", False), P.CONTRADICTS),
    (_keyed("is_null"), _keyed("is_undefined", False), P.WIDENED),
    (_keyed("is_null"), _keyed("is_nullish"), P.WIDENED),
    (_keyed("is_null", False), _keyed("is_nullish", False), P.STRONGER),
    (_keyed("is_null", False), _keyed("is_null"), P.OPPOSITE),
    (_keyed("is_undefined", False), _keyed("is_null", False), P.UNVERIFIABLE),
    (_keyed("truthy"), _keyed("truthy", False), P.OPPOSITE),
    (_keyed("truthy"), _keyed("is_false"), P.CONTRADICTS),
    (_keyed("truthy"), _keyed("is_true"), P.STRONGER),
    (_keyed("is_nullish", False), _keyed("truthy"), P.STRONGER),
    # An `===` literal is a presence value of its own.
    (_keyed("truthy"), _keyed("eq_strict", literal="5.0"), P.STRONGER),
    (_keyed("truthy"), _keyed("eq_strict", literal="0.0"), P.CONTRADICTS),
    (_keyed("eq_strict", literal="78.75"), _keyed("is_undefined"), P.CONTRADICTS),
    (_keyed("eq_strict", literal="'x'"), _keyed("is_nullish", False), P.WIDENED),
    # Both literal at one polarity: the value changed, which EXPECTED_VALUE_CHANGED owns.
    (_keyed("eq_strict", literal="5.0"), _keyed("is_null", literal="None"), P.SAME),
    (_keyed("is_true", literal="True"), _keyed("is_false", literal="False"), P.SAME),
    (_keyed("is_true", False, literal="True"), _keyed("is_false", literal="False"), P.STRONGER),
    # Equality: strictness, never the operand.
    (_keyed("eq_strict", literal="78.75"), _keyed("eq_loose"), P.WIDENED),
    (_keyed("eq_loose"), _keyed("eq_strict", literal="78.75"), P.STRONGER),
    (_keyed("eq_strict", literal="78.75"), _keyed("eq_strict", False, literal="78.75"), P.OPPOSITE),
    # Bounds: a changed direction contradicts; `<` -> `<=` needs the bound.
    (_keyed("lt"), _keyed("gt"), P.CONTRADICTS),
    (_keyed("le"), _keyed("ge"), P.CONTRADICTS),
    (_keyed("lt"), _keyed("le", False), P.CONTRADICTS),
    (_keyed("lt"), _keyed("lt", False), P.OPPOSITE),
    (_keyed("lt"), _keyed("le"), None),
    (_keyed("lt", False), _keyed("ge"), P.UNVERIFIABLE),
    (_keyed("lt"), _keyed("gt", False), P.UNVERIFIABLE),
    # One bound on both sides: below, at, above it, and NaN decide (#198 evidence half).
    (_keyed("lt", literal="80.0"), _keyed("le", literal="80.0"), P.WIDENED),
    (_keyed("le", literal="80.0"), _keyed("lt", literal="80.0"), P.STRONGER),
    (_keyed("lt", operand="LIMIT"), _keyed("le", operand="LIMIT"), P.WIDENED),
    (_keyed("lt", literal="80.0"), _keyed("gt", False, literal="80.0"), P.WIDENED),
    (_keyed("gt", False, literal="80.0"), _keyed("le", literal="80.0"), P.STRONGER),
    (_keyed("ge", False, literal="80.0"), _keyed("le", literal="80.0"), P.UNVERIFIABLE),
    (_keyed("lt", literal="80.0"), _keyed("le", literal="75.0"), None),
    (_keyed("lt", literal="80.0"), _keyed("le", operand="LIMIT"), None),
    (_keyed("lt", operand="LIMIT"), _keyed("gt", operand="LIMIT"), P.CONTRADICTS),
    # The hand-rolled truthy spelling: a reversed bound contradicts once both
    # bounds were read, and cannot be verified otherwise (189.3).
    (_hand_rolled("lt"), _hand_rolled("gt"), P.CONTRADICTS),
    (_hand_rolled("lt"), _hand_rolled("gt", None), P.UNVERIFIABLE),
    (_hand_rolled("lt", None), _hand_rolled("ge"), P.UNVERIFIABLE),
    (_hand_rolled("lt"), _hand_rolled("le"), P.WIDENED),
    (_hand_rolled("lt"), _hand_rolled("lt", None), P.SAME),
    (_keyed("lt"), _keyed("gt", form="compare_ord"), P.CONTRADICTS),
    # Keys of two families do not relate alone.
    (_keyed("truthy"), _keyed("eq_strict"), None),
    (_keyed("is_undefined", False), _keyed("gt"), None),
    (_keyed("eq_strict", literal="78.75"), _keyed("lt"), None),
    (_keyed("truthy"), _keyed("eq_loose"), None),
    (_keyed("is_null"), _keyed(None), None),
])
def test_relation(old, new, relation):
    assert P.relation(old, new) == relation


# --- The issue's rows -------------------------------------------------------------

BLOCK, PASS = "block", "pass"


@pytest.mark.parametrize("before,after,header,verdict,rule", [
    # M1: a different predicate on the same rung (#198 M1a-h).
    ("expect(value).toBeNull();", "expect(value).to.exist;", VITEST, BLOCK, "contradicts"),
    ("expect(value).toBeNull();", "assert.exists(value);", VITEST, BLOCK, "contradicts"),
    ("expect(value).toBeNull();", "assert.isDefined(value);", VITEST, BLOCK, "predicate widened"),
    ("expect(value).toBeLessThan(80);", "expect(value).to.be.above(80);", VITEST, BLOCK, "bound direction reversed"),
    ("expect(value).toBeLessThan(80);", "assert.isAbove(value, 80);", VITEST, BLOCK, "bound direction reversed"),
    ("expect(value).toBeDefined();", "expect(value).to.be.undefined;", VITEST, BLOCK, "polarity inverted"),
    ("expect(value).toBeTruthy();", "expect(value).to.be.false;", VITEST, BLOCK, "contradicts"),
    ("expect(value).toBeTruthy();", "assert.isFalse(value);", VITEST, BLOCK, "contradicts"),
    # Jest-only twins (198.Q3).
    ("expect(value).toBeNull();", "expect(value).toBeDefined();", VITEST, BLOCK, "predicate widened"),
    ("expect(value).toBeNull();", "expect(value).toBeUndefined();", VITEST, BLOCK, "contradicts"),
    ("expect(value).toBeTruthy();", "expect(value).toBeFalsy();", VITEST, BLOCK, "polarity inverted"),
    ("expect(value).toBeLessThan(80);", "expect(value).toBeGreaterThan(80);", VITEST, BLOCK,
     "bound direction reversed"),
    ("expect(value).toBeDefined();", "expect(value).toBe(undefined);", VITEST, BLOCK, "polarity inverted"),
    # Honest rewrites no longer prove "the opposite" (FP1, FP2, FPJ1, FPJ2);
    # FP3 is a real widening and says so.
    ("expect(value).not.toBeNull();", "expect(value).to.exist;", VITEST, PASS, None),
    ("expect(value).toBeFalsy();", "expect(value).to.not.be.ok;", VITEST, PASS, None),
    ("expect(value).toBeNull();", "expect(value).to.not.exist;", VITEST, BLOCK, "predicate widened"),
    ("expect(value).not.toBeTruthy();", "expect(value).toBeFalsy();", VITEST, PASS, None),
    ("expect(value).not.toBeUndefined();", "expect(value).toBeDefined();", VITEST, PASS, None),
    # A literal replaced by `undefined` (M2d, M2e).
    ("expect(value).toBe(78.75);", "expect(value).to.be.undefined;", VITEST, BLOCK, "contradicts"),
    ("expect(value).toBe(78.75);", "assert.isUndefined(value);", VITEST, BLOCK, "contradicts"),
    # chai to chai (B1, B2).
    ("expect(value).to.be.below(80);", "expect(value).to.be.above(80);", VITEST, BLOCK, "bound direction reversed"),
    ("expect(value).to.exist;", "expect(value).to.be.null;", VITEST, BLOCK, "contradicts"),
    # Honest controls (H1-H6) and caught controls (K1-K3).
    ("expect(value).toBeTruthy();", "expect(value).to.be.ok;", VITEST, PASS, None),
    ("expect(value).toBeNull();", "expect(value).to.be.null;", VITEST, PASS, None),
    ("expect(value).toBe(78.75);", "expect(value).to.equal(78.75);", VITEST, PASS, None),
    ("expect(value).toBe(78.75);", "assert.equal(value, 78.75);", VITEST, PASS, "predicate widened"),
    ("expect(value).toBeCloseTo(78.75, 2);", "expect(value).to.be.closeTo(78.75, 0.005);", VITEST, PASS, None),
    ("expect(value).toBeLessThan(80);", "expect(value).to.be.below(80);", VITEST, PASS, None),
    ("expect(value).toBe(78.75);", "expect(value).to.equal(75);", VITEST, BLOCK, "expected value rewritten"),
    ("expect(value).not.toBeNull();", "expect(value).to.be.null;", VITEST, BLOCK, "polarity inverted"),
    ("expect(value).toBeCloseTo(78.75, 2);", "expect(value).to.be.closeTo(78.75, 1);", VITEST, BLOCK,
     "tolerance loosened"),
    # node:assert/strict's equal is strictEqual (T3).
    ("expect(value).toBe(78.75);", "assert.equal(value, 75);", HEADERS["node_strict"], BLOCK,
     "expected value rewritten"),
    ("expect(value).toBe(78.75);", "assert.equal(value, 78.75);", HEADERS["node_strict"], PASS, None),
    # @jest/globals' expect has no chai chain (S3): the head assertion is gone.
    ("expect(value).toBeNull();", "expect(value).to.exist;", HEADERS["jest"], BLOCK, "assertion removed"),
])
def test_issue_rows(before, after, header, verdict, rule):
    observed, findings, messages = _outcome(before, after, header)
    assert observed == verdict, messages
    if rule is None:
        assert findings == ()
    else:
        assert any(rule in message for message in messages), messages


@pytest.mark.parametrize("before,after", [
    ("expect(value).toBeNull();", "expect(value).to.exist;"),
    ("expect(value).toBe(78.75);", "assert.equal(value, 75);"),
    ("expect(value).not.toBeNull();", "expect(value).to.exist;"),
    ("expect(value).toBeFalsy();", "expect(value).to.not.be.ok;"),
])
def test_a_production_change_keeps_the_verdict_pass(before, after):
    # S1, S2, S4, S5: the harm is on test-only diffs; repair evidence holds a finding at warn.
    observed, findings, _messages = _outcome(before, after, VITEST, True)
    assert observed == PASS
    assert all(severity == "warn" for _rule, severity in findings)


def test_widening_inside_the_exact_family_is_held_at_warn():
    # H4: === -> == is a true widening, and MILD_WEAKENING holds it at warn.
    _ir, findings, verdict = analyze(
        [FileChange(TEST, "modified", _source("expect(value).toBe(78.75);").encode(),
                    _source("assert.equal(value, 78.75);").encode())],
        Config(), Contract(), [], datetime.date(2026, 10, 3))
    finding, = findings
    assert (verdict, finding.rule, finding.severity, finding.deescalators) == (
        PASS, "ASSERT_WEAKENED", "warn", ["MILD_WEAKENING"])


# --- The acceptance matrix: Jest start x end API x predicate -----------------------

class _Value:
    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return self.name


NULL, UNDEFINED, OBJECT = _Value("null"), _Value("undefined"), _Value("{}")
# One of every kind of value the predicates tell apart: null, undefined, the
# booleans, falsy and truthy numbers and strings, NaN, the expected value
# 78.75 and its loose twin "78.75", values around the bound 80, and an object.
DOMAIN = (NULL, UNDEFINED, True, False, 0.0, 1.0, 75.0, 78.75, 79.0, 80.0, 81.0, math.nan,
          "", "x", "0", "78.75", OBJECT)


def _truthy(v):
    if v is NULL or v is UNDEFINED or v is False:
        return False
    if isinstance(v, float):
        return v != 0 and not math.isnan(v)
    if isinstance(v, str):
        return v != ""
    return True


def _number(v):
    """JavaScript's ToNumber, for the values in DOMAIN."""
    if v is NULL or v is False:
        return 0.0
    if v is True:
        return 1.0
    if isinstance(v, float):
        return v
    if isinstance(v, str):
        try:
            return float(v) if v.strip() else 0.0
        except ValueError:
            return math.nan
    return math.nan


def _strict(v, x):
    """===: same type and value, NaN unequal to itself."""
    if isinstance(v, bool) or isinstance(x, bool):
        return v is x
    if isinstance(v, float) and isinstance(x, float):
        return v == x
    if isinstance(v, str) and isinstance(x, str):
        return v == x
    return v is x


def _loose(v, x):
    """==, for the values in DOMAIN."""
    nullish = (NULL, UNDEFINED)
    if v in nullish or x in nullish:
        return v in nullish and x in nullish
    if type(v) is type(x):
        return _strict(v, x)
    if OBJECT in (v, x):
        other = x if v is OBJECT else v
        return isinstance(other, str) and other == "[object Object]"
    return _number(v) == _number(x)


def _bound(op):
    compare = {"lt": lambda v: v < 80, "le": lambda v: v <= 80, "gt": lambda v: v > 80, "ge": lambda v: v >= 80}[op]
    # Jest's and chai's ordering assertions fail on a non-number either way.
    return lambda v, negated: isinstance(v, float) and compare(v) != negated


class Spelling:
    """One spelling: its source, what it accepts, its rung and its structure.

    `family` and `literal` are what the rulings decide on: presence, equality
    (strict or loose, and whether the operand is a literal the reader keeps)
    and bounds. `asserts` is the polarity the spelling has against its key.
    """

    def __init__(self, name, body, header, accepts, rung, family, key, asserts, literal=None):
        self.name, self.body, self.header = name, body, header
        self.accepts, self.rung, self.family, self.key = accepts, rung, family, key
        self.asserts, self.literal = asserts, literal

    def __repr__(self):
        return self.name


def _spellings():
    out = []

    def add(name, body, header, accepts, rung, family, key, asserts, literal=None, negatable=None):
        out.append(Spelling(name, body, header, lambda v, f=accepts: f(v, False), rung, family, key, asserts, literal))
        if negatable is not None:
            out.append(Spelling("not " + name, negatable, header, lambda v, f=accepts: f(v, True),
                                rung, family, key, not asserts, literal))

    def fact(test):
        return lambda v, negated: test(v) != negated

    presence = [
        # (name, key, asserts, accepts, Jest spelling, chai spelling), each
        # spelling as (body, rung, the literal its operand states or None).
        ("null", "is_null", True, lambda v: v is NULL, ("toBeNull()", 30, None), ("to.be.null", 90, "None")),
        ("undefined", "is_undefined", True, lambda v: v is UNDEFINED,
         ("toBeUndefined()", 30, None), ("to.be.undefined", 90, None)),
        ("defined", "is_undefined", False, lambda v: v is not UNDEFINED, ("toBeDefined()", 30, None), None),
        ("exist", "is_nullish", False, lambda v: v not in (NULL, UNDEFINED), None, ("to.exist", 30, None)),
        ("truthy", "truthy", True, _truthy, ("toBeTruthy()", 20, None), ("to.be.ok", 20, None)),
        ("falsy", "truthy", False, lambda v: not _truthy(v), ("toBeFalsy()", 20, None), None),
        ("true", "is_true", True, lambda v: v is True, ("toBe(true)", 90, "True"), ("to.be.true", 90, "True")),
        ("false", "is_false", True, lambda v: v is False, ("toBe(false)", 90, "False"), ("to.be.false", 90, "False")),
        ("equal null", "is_null", True, lambda v: v is NULL, ("toBe(null)", 90, "None"), ("to.equal(null)", 90, "None")),
        ("equal undefined", "is_undefined", True, lambda v: v is UNDEFINED, ("toBe(undefined)", 90, None), None),
    ]
    for name, key, asserts, test, jest, chai in presence:
        if jest is not None:
            body, rung, literal = jest
            add("jest " + name, f"expect(value).{body};", "vitest", fact(test), rung, "presence", key, asserts,
                literal, negatable=f"expect(value).not.{body};")
        if chai is not None:
            body, rung, literal = chai
            negated = body.replace("to.", "to.not.", 1)
            add("chai " + name, f"expect(value).{body};", "vitest", fact(test), rung, "presence", key, asserts,
                literal, negatable=f"expect(value).{negated};")
    add("jest toBe", "expect(value).toBe(78.75);", "vitest", fact(lambda v: _strict(v, 78.75)), 90,
        "eq_strict", "eq_strict", True, "78.75", negatable="expect(value).not.toBe(78.75);")
    add("chai equal", "expect(value).to.equal(78.75);", "vitest", fact(lambda v: _strict(v, 78.75)), 90,
        "eq_strict", "eq_strict", True, "78.75", negatable="expect(value).to.not.equal(78.75);")
    for op, jest, chai in [("lt", "toBeLessThan", "below"), ("le", "toBeLessThanOrEqual", "most"),
                           ("gt", "toBeGreaterThan", "above"), ("ge", "toBeGreaterThanOrEqual", "least")]:
        add("jest " + op, f"expect(value).{jest}(80);", "vitest", _bound(op), 40, "bound", op, True,
            "80.0", negatable=f"expect(value).not.{jest}(80);")
        add("chai " + op, f"expect(value).to.be.{chai}(80);", "vitest", _bound(op), 40, "bound", op, True,
            "80.0", negatable=f"expect(value).to.not.be.{chai}(80);")
    # The assert interfaces have no negated spellings this scan represents.
    for header in ("vitest", "chai"):
        for name, body, rung, family, key, asserts, test, literal in [
            ("isNull", "assert.isNull(value);", 90, "presence", "is_null", True, lambda v: v is NULL, "None"),
            ("isUndefined", "assert.isUndefined(value);", 90, "presence", "is_undefined", True,
             lambda v: v is UNDEFINED, None),
            ("isDefined", "assert.isDefined(value);", 30, "presence", "is_undefined", False,
             lambda v: v is not UNDEFINED, None),
            ("exists", "assert.exists(value);", 30, "presence", "is_nullish", False,
             lambda v: v not in (NULL, UNDEFINED), None),
            ("isOk", "assert.isOk(value);", 20, "presence", "truthy", True, _truthy, None),
            ("isTrue", "assert.isTrue(value);", 90, "presence", "is_true", True, lambda v: v is True, "True"),
            ("isFalse", "assert.isFalse(value);", 90, "presence", "is_false", True, lambda v: v is False, "False"),
            ("equal null", "assert.equal(value, null);", 90, "presence", "is_nullish", True,
             lambda v: v in (NULL, UNDEFINED), "None"),
            ("strictEqual", "assert.strictEqual(value, 78.75);", 90, "eq_strict", "eq_strict", True,
             lambda v: _strict(v, 78.75), "78.75"),
            ("equal", "assert.equal(value, 78.75);", 90, "eq_loose", "eq_loose", True,
             lambda v: _loose(v, 78.75), "78.75"),
        ]:
            add(f"{header} assert.{name}", body, header, fact(test), rung, family, key, asserts, literal)
        for op, method in [("lt", "isBelow"), ("le", "isAtMost"), ("gt", "isAbove"), ("ge", "isAtLeast")]:
            add(f"{header} assert.{method}", f"assert.{method}(value, 80);", header, _bound(op), 40, "bound", op,
                True, "80.0")
    for header, strict in (("node", False), ("node_strict", True)):
        add(f"{header} ok", "assert.ok(value);", header, fact(_truthy), 20, "presence", "truthy", True)
        add(f"{header} equal null", "assert.equal(value, null);", header,
            fact((lambda v: v is NULL) if strict else (lambda v: v in (NULL, UNDEFINED))), 90, "presence",
            "is_null" if strict else "is_nullish", True, "None")
        add(f"{header} equal", "assert.equal(value, 78.75);", header,
            fact((lambda v: _strict(v, 78.75)) if strict else (lambda v: _loose(v, 78.75))), 90,
            "eq_strict" if strict else "eq_loose", "eq_strict" if strict else "eq_loose", True, "78.75")
        add(f"{header} strictEqual true", "assert.strictEqual(value, true);", header, fact(lambda v: v is True),
            90, "presence", "is_true", True, "True")
    return out


SPELLINGS = _spellings()
STARTS = [s for s in SPELLINGS if s.name.startswith(("jest ", "not jest "))]


def _domain_relation(old, new):
    accepted_old = {i for i, v in enumerate(DOMAIN) if old.accepts(v)}
    accepted_new = {i for i, v in enumerate(DOMAIN) if new.accepts(v)}
    if accepted_old == accepted_new:
        return P.SAME
    if accepted_new < accepted_old:
        return P.STRONGER
    if accepted_old < accepted_new:
        return P.WIDENED
    return P.CONTRADICTS if not accepted_old & accepted_new else P.UNVERIFIABLE


def _lattice(old, new):
    """The lattice rule: no drop passes, and MILD_WEAKENING holds a small drop inside the exact family."""
    drop = old.rung - new.rung
    return PASS if drop <= 0 or (drop < 30 and new.rung >= 90) else BLOCK


def _widened(old, new):
    """A proven widening is reported with the honest drop: only MILD_WEAKENING holds it at warn."""
    return PASS if max(old.rung - new.rung, 0) < 30 and new.rung >= 90 else BLOCK


def _expected(old, new):
    """The verdict the rulings give a test-only rewrite of `old` into `new`.

    The value semantics decide whenever the keys relate (198.IR). A rewritten
    literal is EXPECTED_VALUE_CHANGED's, at any polarity, and a bound is a
    literal too (198.Q2): `toBeLessThan(80)` -> `toBe(78.75)` reports, as
    there is no JS counterpart of Python's single-assertion restoration
    proof. A bound that changed direction contradicts (198.Q4); with one
    bound on both sides, as every bound here names 80, the values decide
    `<` -> `<=`. Keys of two families do not relate alone, and an `===`
    literal is a presence value.
    """
    if old.literal is not None and new.literal is not None and old.literal != new.literal:
        return BLOCK
    families = {old.family, new.family}
    if families == {"bound"}:
        upper = (old.key in {"lt", "le"}) == old.asserts, (new.key in {"lt", "le"}) == new.asserts
        if upper[0] != upper[1]:
            return BLOCK
    related = (len(families) == 1 or families == {"eq_strict", "eq_loose"}
               or families == {"presence", "eq_strict"})
    if not related:
        return _fallback(old, new)
    relation = _domain_relation(old, new)
    if relation in (P.SAME, P.STRONGER):
        return PASS
    if relation == P.WIDENED:
        return _widened(old, new)
    return BLOCK


def _fallback(old, new):
    """The lattice rules, with `positive` meaning "asserts the predicate".

    A presence check (`toBeDefined()`, `.exist`, `.not.toBeNull()`) beside an
    assertion that affirms something outside presence is no polarity change.
    """
    def check(s):
        return s.key in {"is_null", "is_undefined", "is_nullish"} and not s.asserts

    def affirms(s):
        return s.asserts and s.family != "presence"

    exempt = (check(old) and affirms(new)) or (check(new) and affirms(old))
    if old.asserts != new.asserts and not exempt:
        return BLOCK
    return _lattice(old, new)


def test_the_matrix_covers_every_api_and_predicate():
    headers = {s.header for s in SPELLINGS}
    assert headers == {"vitest", "chai", "node", "node_strict"}
    assert {s.key for s in SPELLINGS} == P.KEYS
    assert len(STARTS) == 28 and len(SPELLINGS) == 88


@pytest.mark.parametrize("new", SPELLINGS, ids=repr)
@pytest.mark.parametrize("old", STARTS, ids=repr)
def test_acceptance_matrix(old, new):
    header = HEADERS[new.header]
    verdict, _findings, messages = _outcome(old.body, new.body, header)
    assert verdict == _expected(old, new), messages
    # "Proves the opposite" only for a flipped polarity on one key.
    if any("proves the opposite" in message for message in messages):
        assert old.key == new.key and old.asserts != new.asserts


# --- Module kinds and strict mode -----------------------------------------------------

def _gaps(body, header):
    data = _source(body, header).encode()
    return [gap.callee for gap in javascript_coverage_gaps(data, parse_javascript(data), TEST, "after")]


@pytest.mark.parametrize("imports", [
    'import { test, expect } from "@jest/globals";\n',
    'import { test, expect as check } from "@jest/globals";\n',
    'import * as jest from "@jest/globals";\nconst { test } = jest;\nconst expect = jest.expect;\n',
    'const { test, expect } = require("@jest/globals");\n',
])
def test_jest_globals_expect_reads_jest_matchers_and_no_chai_chain(imports):
    receiver = "check" if "as check" in imports else "expect"
    assert _assertion(f"{receiver}(value).toBeNull();", imports).predicate == "is_null"
    body = f"{receiver}(value).to.exist;"
    assert [a for unit in parse_javascript(_source(body, imports).encode()).units for a in unit.side.assertions] == []
    assert _gaps(body, imports) == [f"{receiver}(...).to.exist"]


def test_jest_globals_has_no_assert_export():
    imports = 'import { test, expect, assert } from "@jest/globals";\n'
    assert [a for unit in parse_javascript(_source("assert.isNull(value);", imports).encode()).units
            for a in unit.side.assertions] == []


@pytest.mark.parametrize("imports", [VITEST, 'import { test } from "vitest";\n'])
def test_vitest_and_global_expect_keep_both_styles(imports):
    assert _assertion("expect(value).to.exist;", imports).predicate == "is_nullish"
    assert _assertion("expect(value).toBeNull();", imports).predicate == "is_null"


@pytest.mark.parametrize("imports,call", [
    ('import assert from "node:assert/strict";\n', "assert.equal"),
    ('import assert from "assert/strict";\n', "assert.equal"),
    ('import { strict as assert } from "node:assert";\n', "assert.equal"),
    ('import { equal, deepEqual } from "node:assert/strict";\n', "equal"),
    ('import * as assert from "node:assert/strict";\n', "assert.equal"),
    ('const assert = require("node:assert").strict;\n', "assert.equal"),
    ('const assert = require("assert/strict");\n', "assert.equal"),
    ('import assert from "node:assert";\n', "assert.strict.equal"),
])
def test_strict_mode_equal_is_strict_equal(imports, call):
    assertion = _assertion(f"{call}(value, 78.75);", 'import { test, expect } from "vitest";\n' + imports)
    assert (assertion.predicate, assertion.right_value) == ("eq_strict", "78.75")
    deep = _assertion(call.replace("equal", "deepEqual") + "(value, 78.75);",
                      'import { test, expect } from "vitest";\n' + imports)
    assert deep.right_value == "78.75"


@pytest.mark.parametrize("imports", ['import assert from "node:assert";\n', 'import assert from "assert";\n', ""])
def test_legacy_equal_is_loose_and_keeps_its_scalar(imports):
    # The key carries the coercion, so the literal is evidence (#196 190.2).
    assertion = _assertion("assert.equal(value, 78.75);", 'import { test, expect } from "vitest";\n' + imports)
    assert (assertion.predicate, assertion.right_value, assertion.operand_source) == ("eq_loose", "78.75", "78.75")


# --- What stays as it was ------------------------------------------------------------

@pytest.mark.parametrize("before,after", [
    # A presence check strengthened into another form (#167's pin).
    ("expect(value).toBeDefined();", "expect(value).toEqual({ total: 78.75 });"),
    ("expect(value).toBeDefined();", "expect(value).toEqual(expected);"),
    ("expect(value).toBeDefined();", "expect(value).toContain(78.75);"),
    ("expect(value).to.exist;", "expect(value).to.include(78.75);"),
    ("assert.isDefined(value);", "assert.deepEqual(value, [78.75]);"),
    ("expect(value).not.toBeNull();", "expect(value).toEqual(expected);"),
    ("expect(value).toBeDefined();", "expect(value).toBe(expected);"),
    ("expect(value).toBeTruthy();", "expect(value).toBe(expected);"),
    ("expect(value).toBeDefined();", "expect(value).toBeGreaterThan(0);"),
    # `<` -> `<=` with a moved bound: only the bound decides.
    ("expect(Math.abs(value - 78.75)).toBeLessThan(0.01);", "expect(Math.abs(value - 78.75)).toBeLessThanOrEqual(0.005);"),
])
def test_strengthenings_across_families_keep_passing(before, after):
    verdict, findings, messages = _outcome(before, after)
    assert (verdict, findings) == (PASS, ()), messages


@pytest.mark.parametrize("before,after,rule", [
    ("expect(value).toEqual(78.75);", "expect(value).toBeDefined();", "ASSERT_WEAKENED"),
    ("expect(value).toBe(expected);", "expect(value).toBeTruthy();", "ASSERT_WEAKENED"),
    ("expect(value).toBeFalsy();", "expect(value).toEqual(5);", "ASSERT_WEAKENED"),
    ("expect(value).toBe(5);", "expect(value).toBeGreaterThan(3);", "ASSERT_WEAKENED"),
])
def test_weakenings_across_families_still_block(before, after, rule):
    verdict, findings, messages = _outcome(before, after)
    assert verdict == BLOCK and (rule, "high") in findings, messages


@pytest.mark.parametrize("before,after,header,verdict,message", [
    # What the first half left to the evidence: one bound decides `<` -> `<=`.
    ("expect(value).toBeLessThan(80);", "expect(value).toBeLessThanOrEqual(80);", VITEST, BLOCK,
     "assertion predicate widened (< 80 -> <= 80)"),
    ("expect(value).toBeLessThan(LIMIT);", "expect(value).to.be.at.most(LIMIT);", VITEST, BLOCK,
     "assertion predicate widened (< LIMIT -> <= LIMIT)"),
    # `not <` also passes NaN, which `>=` rejects: a strengthening, not a replacement.
    ("expect(value).not.toBeLessThan(80);", "expect(value).toBeGreaterThanOrEqual(80);", VITEST, PASS, None),
    # The hand-rolled truthy spelling flipped (189.3).
    ("assert.ok(Math.abs(value - 78.75) < 0.01);", "assert.ok(Math.abs(value - 78.75) > 0.01);",
     HEADERS["node"], BLOCK, "bound direction reversed (< 0.01 -> > 0.01)"),
    ("assert.ok(Math.abs(value - 78.75) < 0.01);", "assert.ok(Math.abs(value - 78.75) > tolerance());",
     HEADERS["node"], BLOCK, "cannot verify the replacement is equivalent (predicate < 0.01 -> > bound)"),
    ("expect(Math.abs(value - 78.75) < 0.01).toBe(true);", "expect(Math.abs(value - 78.75) > 0.01).toBe(true);",
     VITEST, BLOCK, "bound direction reversed (< 0.01 -> > 0.01)"),
    # Its `=== true` and truthy spellings state one bound.
    ("expect(Math.abs(value - 78.75) < 0.01).toBe(true);", "assert.ok(Math.abs(value - 78.75) < 0.01);",
     'import { test, expect } from "vitest";\nimport assert from "node:assert";\n', PASS, None),
    # A hand-rolled bound the reader could read, replaced by one it cannot,
    # is unknown, not unchanged (#196 189.1, as 190.4 for closeTo).
    ("assert.ok(Math.abs(value - 78.75) < 0.01);", "assert.ok(Math.abs(value - 78.75) < tolerance());",
     HEADERS["node"], BLOCK,
     "cannot verify the replacement is equivalent (tolerance abs=0.01 -> a tolerance it cannot read)"),
])
def test_residuals_the_evidence_closes(before, after, header, verdict, message):
    observed, findings, messages = _outcome(before, after, header)
    assert observed == verdict, messages
    if message is None:
        assert findings == ()
    else:
        assert any(message in m for m in messages), messages


@pytest.mark.parametrize("before,after,header,verdict,message", [
    # The residuals docs/assertion-coverage.md lists, as they stand.
    ("expect(value).toBeNull();", "expect(value).toBe(expected);", VITEST, PASS, None),
    ("expect(value).toBeTruthy();", "expect(value).toBeGreaterThan(0);", VITEST, PASS, None),
    ("expect(value).to.not.exist;", "expect(value).to.include(78.75);", VITEST, PASS, None),
    ("expect(value).not.toBeDefined();", "expect(value).toEqual(expected);", VITEST, PASS, None),
    # A literal and an expression, either way round, wait for #226: the
    # reader does not resolve what a name or call yields.
    ("expect(value).toBe(78.75);", "expect(value).toBe(Number(75));", VITEST, PASS, None),
    ("expect(value).toBe(EXPECTED);", "expect(value).toBe(75);", VITEST, PASS, None),
    ("expect(value).toBeLessThan(80);", "expect(value).toBeLessThanOrEqual(LIMIT);", VITEST, PASS, None),
    # Two different bounds: `<` -> `<=` is left to the operand rule.
    ("expect(value).toBeLessThan(LIMIT);", "expect(value).toBeLessThanOrEqual(OTHER);", VITEST, BLOCK,
     "expected call rewritten to a different call ['LIMIT'] -> ['OTHER']"),
    # No JS counterpart of Python's single-assertion restoration proof: a
    # bound tightened into an exact value reports its new value.
    ("expect(value).toBeLessThan(80);", "expect(value).toBe(78.75);", VITEST, BLOCK,
     "expected value rewritten 80.0 -> 78.75 despite increased assertion strength"),
])
def test_documented_residuals(before, after, header, verdict, message):
    observed, findings, messages = _outcome(before, after, header)
    assert observed == verdict, messages
    if message is None:
        assert findings == ()
    else:
        assert any(message in m for m in messages), messages

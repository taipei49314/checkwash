"""Hand-rolled JS tolerances are tolerances (issue #179).

`assert.ok(Math.abs(total - 78.75) < 0.01)` widened to `< 1e12` passed with
no finding: the whole comparison was an opaque truthy subject, and only
`toBeCloseTo` carried a tolerance. These pin the one reading every assertion
spelling now shares, the bound spellings it accepts, and how
TOLERANCE_LOOSENED compares what it records.
"""

import datetime
from decimal import Decimal

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.detectors.tolerance_loosened import _js_mixed
from checkwash.engine import FileChange, analyze
from checkwash.frontends.javascript.frontend import parse_javascript

NODE = """import assert from "node:assert";
import { test } from "node:test";
"""
SUBJECT = "Math.abs(total() - 78.75)"


def _source(body, imports=NODE):
    return f"""{imports}test("sample", (t) => {{
  {body}
}});
"""


def _assertion(body, imports=NODE):
    assertion, = [found for unit in parse_javascript(_source(body, imports).encode()).units
                  for found in unit.side.assertions]
    return assertion


def _bound(body, imports=NODE):
    """The recorded absolute bound, or None; never a half-recorded tolerance."""
    assertion = _assertion(body, imports)
    if assertion.epsilon is None:
        assert assertion.epsilon_kind is None
        return None
    assert assertion.epsilon_kind == "abs"
    assert assertion.epsilon.startswith("abs=")
    return Decimal(assertion.epsilon[len("abs="):])


def _analyze(before, after, imports=NODE):
    return analyze(
        [FileChange("tests/sample.test.js", "modified",
                    _source(before, imports).encode(), _source(after, imports).encode())],
        Config(), Contract(), [], datetime.date(2026, 10, 1),
    )


def _rules(before, after, imports=NODE):
    _ir, findings, verdict = _analyze(before, after, imports)
    return [(finding.rule, finding.severity) for finding in findings], verdict


@pytest.mark.parametrize("body", [
    f"assert.ok({SUBJECT} < 0.01);",
    f"assert({SUBJECT} < 0.01);",
    f"t.assert.ok({SUBJECT} < 0.01);",
    f'assert.ok({SUBJECT} <= 0.01, "within a cent");',
    f"assert.ok(0.01 > {SUBJECT});",
    f"assert.ok(0.01 >= ({SUBJECT}));",
    f"assert.ok({SUBJECT} < .01 /* a cent */);",
    f"assert.strictEqual({SUBJECT} < 0.01, true);",
    f"expect({SUBJECT} < 0.01).toBeTruthy();",
    f"expect({SUBJECT} < 0.01).toBe(true);",
    f"expect({SUBJECT} < 0.01).toStrictEqual(true);",
    f"expect({SUBJECT}).toBeLessThan(0.01);",
    f"expect({SUBJECT}).toBeLessThanOrEqual(1e-2);",
    f"expect(0.01).toBeGreaterThan({SUBJECT});",
    f"const EPS = 0.01; assert.ok({SUBJECT} < EPS);",
    f"assert.ok(({SUBJECT} < 0.01));",
    f"expect(({SUBJECT} < 0.01)).toBe(true);",
])
def test_every_spelling_records_the_same_absolute_tolerance(body):
    assert _bound(body) == Decimal("0.01")


@pytest.mark.parametrize("body", [
    f"expect({SUBJECT} < 0.01).toBeFalsy();",
    f"expect({SUBJECT} < 0.01).not.toBeTruthy();",
    f"expect({SUBJECT} < 0.01).toBe(false);",
    f"expect({SUBJECT}).not.toBeLessThan(0.01);",
    f"expect({SUBJECT}).toBeGreaterThan(0.01);",
    f"assert.ok({SUBJECT} > 0.01);",
    f"assert.ok({SUBJECT} < 0.01 && ready());",
    f"assert.ok({SUBJECT} * 2 < 0.01);",
    "assert.ok(Math.round(total() - 78.75) < 0.01);",
    "assert.ok(total() - 78.75 < 0.01);",
    f"assert.ok({SUBJECT} < tolerance());",
    f"assert.ok({SUBJECT} < 2 ** -7);",
    f'assert.ok({SUBJECT} < "0.01");',
    f"assert.ok({SUBJECT} < NaN);",
    f"assert.ok({SUBJECT} < Math.PI);",
    f"const Math = {{ abs: () => 0 }}; assert.ok({SUBJECT} < 0.01);",
    f"const Number = {{ EPSILON: 1 }}; assert.ok({SUBJECT} < Number.EPSILON);",
    f"let EPS = 0.01; EPS = 1e12; assert.ok({SUBJECT} < EPS);",
    f"assert.ok(({SUBJECT} < 0.01) && ready());",
    f"const EPS = 1e99999999999999999999; assert.ok({SUBJECT} < EPS);",
])
def test_other_shapes_record_no_tolerance(body):
    assert _bound(body) is None


def test_named_number_bounds_are_exact_decimals():
    assert _bound(f"assert.ok({SUBJECT} < Number.EPSILON);") * 2 ** 52 == 1
    assert _bound(f"assert.ok({SUBJECT} < 4 * Number.EPSILON);") * 2 ** 50 == 1
    assert _bound(f"assert.ok({SUBJECT} < Number.EPSILON * 4);") * 2 ** 50 == 1
    assert _bound(f"assert.ok({SUBJECT} < Infinity);") == Decimal("Infinity")
    assert _bound(f"assert.ok({SUBJECT} < Number.POSITIVE_INFINITY);") == Decimal("Infinity")


@pytest.mark.parametrize("declaration,expected", [
    ("const EPS = 0.01;", Decimal("0.01")),
    ("let EPS = (1e-2);", Decimal("0.01")),
    ("var EPS = 0x1;", Decimal(1)),
])
def test_a_module_declaration_supplies_the_bound(declaration, expected):
    imports = f"""{NODE}{declaration}
"""
    assert _bound(f"assert.ok({SUBJECT} < EPS);", imports) == expected


def test_destructured_number_epsilon_is_read_through_its_declaration():
    imports = f"""{NODE}const {{ EPSILON: EPS }} = Number;
"""
    assert _bound(f"assert.ok({SUBJECT} < EPS);", imports) * 2 ** 52 == 1


def test_a_bound_name_is_followed_one_hop_only():
    imports = f"""{NODE}const BASE = 0.01;
const EPS = BASE;
"""
    assert _bound(f"assert.ok({SUBJECT} < EPS);", imports) is None


def test_issue_179_widened_epsilon_blocks_and_names_both_bounds():
    _ir, findings, verdict = _analyze(f"assert.ok({SUBJECT} < 0.01);",
                                      f"assert.ok({SUBJECT} < 1e12);")
    assert verdict == "block"
    assert [(finding.rule, finding.severity) for finding in findings] == [("TOLERANCE_LOOSENED", "high")]
    assert "(abs=0.01 -> abs=1E+12)" in findings[0].message


@pytest.mark.parametrize("before,after", [
    (f"assert.ok({SUBJECT} < Number.EPSILON);", f"assert.ok({SUBJECT} < 0.01);"),
    (f"assert.ok({SUBJECT} < 0.01);", f"assert.ok({SUBJECT} < Infinity);"),
    (f"expect({SUBJECT} < 0.01).toBe(true);", f"expect({SUBJECT} < 1).toBe(true);"),
    (f"expect({SUBJECT}).toBeLessThan(0.01);", f"expect({SUBJECT}).toBeLessThan(1e12);"),
    (f"const EPS = 0.01; assert.ok({SUBJECT} < EPS);",
     f"const EPS = 1e12; assert.ok({SUBJECT} < EPS);"),
    (f"assert.ok({SUBJECT} < 0.01);", f"assert.ok(({SUBJECT} < 1e12));"),
])
def test_widening_any_spelling_reports_tolerance_loosened(before, after):
    assert _rules(before, after) == ([("TOLERANCE_LOOSENED", "high")], "block")


@pytest.mark.parametrize("before,after", [
    (f"assert.ok({SUBJECT} < 0.01);", f"assert.ok({SUBJECT} < 0.001);"),
    (f"assert.ok({SUBJECT} < 0.01);", f"assert.ok({SUBJECT} < 1e-2);"),
    (f"assert.ok({SUBJECT} < 0.01);", f"assert.ok(0.01 > {SUBJECT});"),
    (f"assert.ok({SUBJECT} < 0.01);", f"const EPS = 1e-2; assert.ok({SUBJECT} < EPS);"),
    (f"expect({SUBJECT}).toBeLessThan(0.01);", f"expect({SUBJECT}).toBeLessThan(Number.EPSILON);"),
    (f"assert.ok({SUBJECT} < Infinity);", f"assert.ok({SUBJECT} < 0.01);"),
    (f"assert.ok({SUBJECT} < 0.01);", f"assert.ok(({SUBJECT} < 0.01));"),
])
def test_tightened_or_respelled_bounds_stay_silent(before, after):
    assert _rules(before, after) == ([], "pass")


@pytest.mark.parametrize("before,after", [
    (f"assert.ok({SUBJECT} < 0.005);", "expect(total()).toBeCloseTo(78.75, 2);"),
    (f"assert.ok({SUBJECT} < 0.5);", "expect(total()).toBeCloseTo(78.75, 0);"),
    (f"assert.ok({SUBJECT} < 0.01);", "expect(total()).toBeCloseTo(78.75);"),
    ("expect(total()).toBeCloseTo(78.75, 2);", f"assert.ok({SUBJECT} < 0.001);"),
])
def test_equal_or_tighter_bounds_across_units_are_not_loosened(before, after):
    # Only the tolerance claim is pinned: replacing the subject is judged by
    # the existing assertion rules, which this reading does not change.
    rules, _verdict = _rules(before, after)
    assert "TOLERANCE_LOOSENED" not in [rule for rule, _severity in rules]


@pytest.mark.parametrize("before,after,shown", [
    (f"assert.ok({SUBJECT} < 0.001);", "expect(total()).toBeCloseTo(78.75, 1);",
     "(abs=0.001 -> places=1)"),
    ("expect(total()).toBeCloseTo(78.75, 2);", f"assert.ok({SUBJECT} < 1e12);",
     "(places=2 -> abs=1E+12)"),
])
def test_wider_bounds_across_units_are_reported_in_their_own_units(before, after, shown):
    _ir, findings, _verdict = _analyze(before, after)
    loosened = [finding for finding in findings if finding.rule == "TOLERANCE_LOOSENED"]
    assert len(loosened) == 1
    assert shown in loosened[0].message


def test_the_cross_unit_reading_is_javascript_only():
    assert _js_mixed("tests/test_calc.py", "abs=0.5", "2") is None
    assert _js_mixed("tests/calc.test.ts", "abs=0.01", "abs=1E+12") is None
    assert _js_mixed("tests/calc.test.ts", "2", "5") is None
    assert _js_mixed("tests/calc.test.ts", "abs=0.5", "0") == (False, "abs=0.5", "places=0")
    assert _js_mixed("tests/calc.test.ts", "abs=0.4", "0") == (True, "abs=0.4", "places=0")
    assert _js_mixed("tests/calc.test.ts", "abs=0.5", "1.5") == (False, "abs=0.5", "1.5")


@pytest.mark.parametrize("bound", ["1e99999999999999999999", "-1e1000000"])
def test_a_bound_past_the_decimal_range_is_unknown_not_a_crash(bound):
    # Review of #189: an exponent no exact Decimal holds, or a negation that
    # overflows the default context, escaped analyze as an engine error
    # (exit 2). The bound is unknown instead, so the pair keeps the verdict it
    # had before hand-rolled tolerances were read.
    assert _bound(f"assert.ok({SUBJECT} < {bound});") is None
    assert _rules(f"assert.ok({SUBJECT} < 0.01);", f"assert.ok({SUBJECT} < {bound});") == ([], "pass")

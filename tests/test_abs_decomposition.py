"""A hand-rolled tolerance, `abs(subject - centre) <op> bound`, in both frontends (#196 189.2).

`Math.abs(total - 78.75) < 0.01` and `abs(total() - 78.75) < 0.01` check
`total` against 78.75 within 0.01, as `pytest.approx(78.75, abs=0.01)` does.
Both frontends record one representation: what the magnitude measures is
`left`, a numeric literal centre is the expected value, and the bound is the
`abs=` tolerance. A rewritten centre is then EXPECTED_VALUE_CHANGED (#225),
and pairing keys on the subject.
"""

import datetime
import functools

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.frontends.javascript.frontend import parse_javascript
from checkwash.frontends.python.frontend import parse_python

BLOCK, PASS = "block", "pass"
NODE = 'import { test } from "node:test";\nimport assert from "node:assert";\n'
VITEST = 'import { test, expect } from "vitest";\nimport assert from "node:assert";\n'


def _js_source(body, header):
    return header + 'import { total } from "./total";\ntest("total", () => {\n  const value = total();\n  ' + body + "\n});\n"


def _py_source(body):
    return "from app.billing import total\n\n\ndef test_total():\n" + "".join(f"    {line}\n" for line in body.split("\n"))


def _py_unittest_source(body):
    return ("import unittest\n\nfrom app.billing import total\n\n\nclass TestTotal(unittest.TestCase):\n"
            "    def test_total(self):\n" + "".join(f"        {line}\n" for line in body.split("\n")))


@functools.lru_cache(maxsize=None)
def _outcome(path, before, after):
    changes = [FileChange(path, "modified", before.encode(), after.encode())]
    _ir, findings, verdict = analyze(changes, Config(), Contract(), [], datetime.date(2026, 10, 4))
    return verdict, tuple((f.rule, f.severity) for f in findings), tuple(f.message for f in findings)


def _js(before, after, header=NODE):
    return _outcome("src/total.test.js", _js_source(before, header), _js_source(after, header))


def _py(before, after, source=_py_source):
    return _outcome("tests/test_billing.py", source(before), source(after))


def _check(observed, verdict, expected):
    got, findings, messages = observed
    assert got == verdict, messages
    if expected is None:
        assert findings == (), messages
    else:
        assert len(findings) == len(expected), messages
        for rule, text in expected:
            assert any(f == (rule, "high") and text in m for f, m in zip(findings, messages)), messages


def _js_assertion(body, header=NODE):
    units = parse_javascript(_js_source(body, header).encode()).units
    return [a for unit in units for a in unit.side.assertions][-1]


def _py_assertion(body, source=_py_source):
    units = parse_python(source(body).encode(), collect_tests=True).units
    return [a for unit in units for a in unit.side.assertions][-1]


def _reading(assertion):
    return assertion.left, assertion.right_value, assertion.epsilon


# --- JavaScript: what is recorded ----------------------------------------------------

@pytest.mark.parametrize("body,header,reading", [
    ("assert.ok(Math.abs(value - 78.75) < 0.01);", NODE, ("value", "78.75", "abs=0.01")),
    ("assert.ok(0.01 > Math.abs(value - 78.75));", NODE, ("value", "78.75", "abs=0.01")),
    ("assert.ok(Math.abs(78.75 - value) <= 0.01);", NODE, ("value", "78.75", "abs=0.01")),
    ("assert.strictEqual(Math.abs(value - 78.75) < 0.01, true);", NODE, ("value", "78.75", "abs=0.01")),
    ("expect(Math.abs(value - 78.75)).toBeLessThan(0.01);", VITEST, ("value", "78.75", "abs=0.01")),
    ("expect(Math.abs(value - 78.75) < 0.01).toBe(true);", VITEST, ("value", "78.75", "abs=0.01")),
    # A lower bound is read for its direction and records no tolerance.
    ("assert.ok(Math.abs(value - 78.75) > 0.01);", NODE, ("value", "78.75", None)),
    ("expect(Math.abs(value - 78.75)).toBeGreaterThan(0.01);", VITEST, ("value", "78.75", None)),
    # The centre is any Number literal, through parentheses and TypeScript wrappers.
    ("assert.ok(Math.abs(value - -1.5) < 0.01);", NODE, ("value", "-1.5", "abs=0.01")),
    ("assert.ok(Math.abs((value) - (7875e-2)) < 0.01);", NODE, ("value", "78.75", "abs=0.01")),
    ("assert.ok(Math.abs(value - (78.75 as number)) < 0.01);", NODE, ("value", "78.75", "abs=0.01")),
    ("assert.ok(Math.abs(value - -0) < 0.01);", NODE, ("value", "0.0", "abs=0.01")),
    ("assert.ok(Math.abs(1e-5 - value) < 0.01);", NODE, ("value", "1e-05", "abs=0.01")),
    ("assert.ok(Math.abs(result?.total - 78.75) < 0.01);", NODE, ("result?.total", "78.75", "abs=0.01")),
    ("assert.ok(Math.abs(rate * 1.05 - 78.75) < 0.01);", NODE, ("rate * 1.05", "78.75", "abs=0.01")),
    # No literal centre, or two: the whole argument is `left`, with no expected value.
    ("assert.ok(Math.abs(value - expected) < 0.01);", NODE, ("value - expected", None, "abs=0.01")),
    ("assert.ok(Math.abs(d) < 0.01);", NODE, ("d", None, "abs=0.01")),
    ("assert.ok(Math.abs(1.5 - 1.25) < 0.01);", NODE, ("1.5 - 1.25", None, "abs=0.01")),
    ('assert.ok(Math.abs(value - "78.75") < 0.01);', NODE, ('value - "78.75"', None, "abs=0.01")),
    # A difference inside something larger is not split.
    ("assert.ok(Math.abs(value - 78.75 + offset) < 0.01);", NODE, ("value - 78.75 + offset", None, "abs=0.01")),
    ("assert.ok(Math.abs(value - 78.75 || 0) < 0.01);", NODE, ("value - 78.75 || 0", None, "abs=0.01")),
    ("assert.ok(Math.abs(value-- - 78.75) < 0.01);", NODE, ("value-- - 78.75", None, "abs=0.01")),
    ("assert.ok(Math.abs(value - 78.75 as number) < 0.01);", NODE, ("value - 78.75 as number", None, "abs=0.01")),
])
def test_js_records_what_the_magnitude_measures(body, header, reading):
    assert _reading(_js_assertion(body, header)) == reading


def test_js_a_shadowed_math_is_not_a_hand_rolled_bound():
    assertion = _js_assertion("const Math = { abs: (v) => v };\n  assert.ok(Math.abs(value - 78.75) < 0.01);")
    assert _reading(assertion) == ("Math.abs(value - 78.75) < 0.01", None, None)


# --- JavaScript: what is reported -----------------------------------------------------

@pytest.mark.parametrize("before,after,header", [
    ("assert.ok(Math.abs(value - 78.75) < 0.01);", "assert.ok(Math.abs(value - 75) < 0.01);", NODE),
    ("assert.ok(0.01 > Math.abs(value - 78.75));", "assert.ok(0.01 > Math.abs(value - 75));", NODE),
    ("assert.ok(Math.abs(78.75 - value) < 0.01);", "assert.ok(Math.abs(75 - value) < 0.01);", NODE),
    ("assert.ok(Math.abs(value - 78.75) <= 0.01);", "assert.ok(Math.abs(value - 75) <= 0.01);", NODE),
    ("assert.strictEqual(Math.abs(value - 78.75) < 0.01, true);",
     "assert.strictEqual(Math.abs(value - 75) < 0.01, true);", NODE),
    ("expect(Math.abs(value - 78.75)).toBeLessThan(0.01);", "expect(Math.abs(value - 75)).toBeLessThan(0.01);", VITEST),
    ("expect(Math.abs(value - 78.75) < 0.01).toBe(true);", "expect(Math.abs(value - 75) < 0.01).toBe(true);", VITEST),
])
def test_js_a_rewritten_centre_is_an_expected_value_rewritten(before, after, header):
    _check(_js(before, after, header), BLOCK, [("EXPECTED_VALUE_CHANGED", "expected value rewritten 78.75 -> 75.0")])


@pytest.mark.parametrize("before,after,header,verdict,expected", [
    # One centre, respelled.
    ("assert.ok(Math.abs(value - 78.75) < 0.01);", "assert.ok(Math.abs(value - 78.750) < 0.01);", NODE, PASS, None),
    ("assert.ok(Math.abs(value - 78.75) < 0.01);", "assert.ok(Math.abs(78.75 - value) < 0.01);", NODE, PASS, None),
    ("assert.ok(Math.abs(value - 78.75) < 0.01);", "expect(Math.abs(value - 78.75)).toBeLessThan(0.01);",
     VITEST, PASS, None),
    # The bound is still the tolerance: widened, tightened, or widened with the centre.
    ("assert.ok(Math.abs(value - 78.75) < 0.01);", "assert.ok(Math.abs(value - 78.75) < 1e12);", NODE, BLOCK,
     [("TOLERANCE_LOOSENED", "tolerance loosened (abs=0.01 -> abs=1E+12)")]),
    ("assert.ok(Math.abs(value - 78.75) < 0.01);", "assert.ok(Math.abs(value - 78.75) < 0.001);", NODE, PASS, None),
    ("assert.ok(Math.abs(value - 78.75) < 0.01);", "assert.ok(Math.abs(value - 75) < 5);", NODE, BLOCK,
     [("TOLERANCE_LOOSENED", "abs=0.01 -> abs=5"), ("EXPECTED_VALUE_CHANGED", "78.75 -> 75.0")]),
    # A flipped bound keeps its subject and centre: the direction is the finding.
    ("assert.ok(Math.abs(value - 78.75) < 0.01);", "assert.ok(Math.abs(value - 78.75) > 0.01);", NODE, BLOCK,
     [("ASSERT_WEAKENED", "bound direction reversed (< 0.01 -> > 0.01)")]),
    ("expect(Math.abs(value - 78.75)).toBeLessThan(0.01);", "expect(Math.abs(value - 78.75)).toBeGreaterThan(0.01);",
     VITEST, BLOCK, [("ASSERT_WEAKENED", "bound direction reversed (< 0.01 -> > 0.01)")]),
    # The centre is never the bound: two unread bounds stay unjudged.
    ("expect(Math.abs(value - 78.75)).toBeLessThan(EPS);",
     "expect(Math.abs(value - 78.75)).toBeLessThanOrEqual(TOLERANCE);", VITEST, PASS, None),
])
def test_js_pairs_on_the_subject(before, after, header, verdict, expected):
    _check(_js(before, after, header), verdict, expected)


# --- Python: what is recorded ----------------------------------------------------------

@pytest.mark.parametrize("body,source,reading", [
    ("assert abs(total() - 78.75) < 0.01", _py_source, ("total()", "78.75", "abs=0.01")),
    ("assert abs(total() - 78.75) <= 0.01", _py_source, ("total()", "78.75", "abs=0.01")),
    ("assert 0.01 > abs(total() - 78.75)", _py_source, ("total()", "78.75", "abs=0.01")),
    ("assert abs(78.75 - total()) < 0.01", _py_source, ("total()", "78.75", "abs=0.01")),
    ("assert abs(total() - -1.5) < 1e-9", _py_source, ("total()", "-1.5", "abs=1e-9")),
    ("assert (abs(total() - 78.75) < 0.01)", _py_source, ("total()", "78.75", "abs=0.01")),
    ("self.assertLess(abs(total() - 78.75), 0.01)", _py_unittest_source, ("total()", "78.75", "abs=0.01")),
    ("self.assertLessEqual(abs(total() - 78.75), 0.01)", _py_unittest_source, ("total()", "78.75", "abs=0.01")),
    ("self.assertGreater(0.01, abs(total() - 78.75))", _py_unittest_source, ("total()", "78.75", "abs=0.01")),
    ("self.assertTrue(abs(total() - 78.75) < 0.01)", _py_unittest_source, ("total()", "78.75", "abs=0.01")),
    # No literal centre, or two: the whole argument is `left`, with no expected value.
    ("assert abs(total() - expected) < 0.01", _py_source, ("total() - expected", None, "abs=0.01")),
    ("assert abs(d) < 0.01", _py_source, ("d", None, "abs=0.01")),
    ("assert abs(1.5 - 1.25) < 0.01", _py_source, ("1.5 - 1.25", None, "abs=0.01")),
    ('assert abs(total() - "78.75") < 0.01', _py_source, ('total() - "78.75"', None, "abs=0.01")),
    # The bound is recorded as written, like an approx tolerance.
    ("assert abs(total() - 78.75) < EPSILON", _py_source, ("total()", "78.75", "abs=EPSILON")),
])
def test_python_records_what_the_magnitude_measures(body, source, reading):
    assert _reading(_py_assertion(body, source)) == reading


@pytest.mark.parametrize("body,source", [
    # A lower bound asserts that the values differ: a plain comparison, as before.
    ("assert abs(total() - 78.75) > 0.01", _py_source),
    ("self.assertGreater(abs(total() - 78.75), 0.01)", _py_unittest_source),
    # So is anything but one bound on the builtin `abs`.
    ("assert abs(total() - 78.75) == 0", _py_source),
    ("assert 0 < abs(total() - 78.75) < 0.01", _py_source),
    ("assert math.fabs(total() - 78.75) < 0.01", _py_source),
    ("from numpy import abs\nassert abs(total() - 78.75) < 0.01", _py_source),
    ("def abs(value):\n    return value\nassert abs(total() - 78.75) < 0.01", _py_source),
    ("abs = round\nassert abs(total() - 78.75) < 0.01", _py_source),
])
def test_python_other_shapes_are_not_decomposed(body, source):
    assertion = _py_assertion(body, source)
    assert assertion.epsilon is None and assertion.left != "total()"


# --- Python: what is reported ---------------------------------------------------------

@pytest.mark.parametrize("before,after,source", [
    ("assert abs(total() - 78.75) < 0.01", "assert abs(total() - 75) < 0.01", _py_source),
    ("assert 0.01 > abs(total() - 78.75)", "assert 0.01 > abs(total() - 75)", _py_source),
    ("assert abs(78.75 - total()) <= 0.01", "assert abs(75 - total()) <= 0.01", _py_source),
    ("self.assertLess(abs(total() - 78.75), 0.01)", "self.assertLess(abs(total() - 75), 0.01)", _py_unittest_source),
    ("self.assertGreater(0.01, abs(total() - 78.75))", "self.assertGreater(0.01, abs(total() - 75))",
     _py_unittest_source),
    ("self.assertTrue(abs(total() - 78.75) < 0.01)", "self.assertTrue(abs(total() - 75) < 0.01)",
     _py_unittest_source),
])
def test_python_a_rewritten_centre_is_an_expected_value_rewritten(before, after, source):
    _check(_py(before, after, source), BLOCK, [("EXPECTED_VALUE_CHANGED", "expected value rewritten 78.75 -> 75")])


@pytest.mark.parametrize("before,after,verdict,expected", [
    ("assert abs(total() - 78.75) < 0.01", "assert abs(total() - 78.750) < 0.01", PASS, None),
    # The bound is the tolerance now, not the expected value: a widening is
    # a loosened tolerance, and a tightening is no finding at all.
    ("assert abs(total() - 78.75) < 0.01", "assert abs(total() - 78.75) < 1e12", BLOCK,
     [("TOLERANCE_LOOSENED", "tolerance loosened (abs=0.01 -> abs=1e12)")]),
    ("assert abs(total() - 78.75) < 0.01", "assert abs(total() - 78.75) < 0.001", PASS, None),
    ("assert abs(total() - 78.75) < 0.01", "assert abs(total() - 75) < 5", BLOCK,
     [("TOLERANCE_LOOSENED", "abs=0.01 -> abs=5"), ("EXPECTED_VALUE_CHANGED", "78.75 -> 75")]),
    ("expected = 78.75\nassert abs(total() - expected) < 0.01", "expected = 78.75\nassert abs(total() - expected) < 1",
     BLOCK, [("TOLERANCE_LOOSENED", "abs=0.01 -> abs=1")]),
    # A plain ordering bound is still the expected value.
    ("assert total() < 80", "assert total() < 1e12", BLOCK,
     [("EXPECTED_VALUE_CHANGED", "expected value rewritten 80 -> 1000000000000.0")]),
    # Python states no bound direction (#224): a flipped check blocks as the
    # centre rewritten into the lower bound, not as a reversed direction.
    ("assert abs(total() - 78.75) < 0.01", "assert abs(total() - 78.75) > 0.01", BLOCK,
     [("EXPECTED_VALUE_CHANGED", "expected value rewritten 78.75 -> 0.01")]),
    # An exact equality replacing the check keeps its value: no rewrite.
    ("assert abs(total() - 78.75) < 0.01", "assert total() == 78.75", PASS, None),
])
def test_python_pairs_on_the_subject(before, after, verdict, expected):
    _check(_py(before, after), verdict, expected)


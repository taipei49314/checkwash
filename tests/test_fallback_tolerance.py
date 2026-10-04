"""Which fallback pairs compare their tolerances (#196 189.2).

Alignment pairs leftover assertions by span order as a last resort. When both
halves of such a pair moved, the subject and the expected literal alike, the
old check is gone and another holds its slot: EXPECTED_VALUE_CHANGED reports
the pair, usually beside ASSERT_SUBSTITUTED, and the new check's slack is no
widening of the old one's, so the two tolerances are not compared.

Every other fallback pair still is. A subject that moved alone is a rename or
a hoist (`t = total()` above the check), and a widening there is the old check
loosened; reading it as a different check would let any rename widen any
tolerance. A side with no recorded subject or no literal expected value does
not show two checks either, and neither does a pair whose strength dropped.
"""

import datetime
import functools

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze

BLOCK = "block"
NODE = 'import { test } from "node:test";\nimport assert from "node:assert";\n'
VITEST = 'import { test, expect } from "vitest";\nimport assert from "node:assert";\n'


def _js_source(body, header):
    return header + 'import { total } from "./total";\ntest("total", () => {\n  const value = total();\n  ' + body + "\n});\n"


def _py_source(body):
    return ("import pytest\n\nfrom app.billing import total\n\nitems = [1, 2]\n\n\ndef test_total():\n"
            + "".join(f"    {line}\n" for line in body.split("\n")))


def _py_unittest_source(body):
    return ("import unittest\n\nfrom app.billing import total\n\nitems = [1, 2]\n\n\n"
            "class TestTotal(unittest.TestCase):\n    def test_total(self):\n"
            + "".join(f"        {line}\n" for line in body.split("\n")))


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
    assert len(findings) == len(expected), messages
    for rule, text in expected:
        assert any(f == (rule, "high") and text in m for f, m in zip(findings, messages)), messages


# --- Both halves moved: another check holds the slot ----------------------------------

def test_js_a_substituted_check_compares_no_tolerance():
    # The check on `value` is gone and one on `items.length` took its slot:
    # its looser bound is not the old check's tolerance.
    _check(_js("assert.ok(Math.abs(value - 78.75) < 0.01);", "assert.ok(Math.abs(items.length - 2) < 1e12);"),
           BLOCK, [("ASSERT_SUBSTITUTED", "(value -> items.length)"),
                   ("EXPECTED_VALUE_CHANGED", "expected value rewritten 78.75 -> 2.0")])


def test_python_a_substituted_check_compares_no_tolerance():
    _check(_py("self.assertAlmostEqual(total(), 78.75, delta=0.01)", "self.assertAlmostEqual(len([1]), 1, delta=5)",
               _py_unittest_source),
           BLOCK, [("ASSERT_SUBSTITUTED", "(total() -> len([1]))"),
                   ("EXPECTED_VALUE_CHANGED", "expected value rewritten 78.75 -> 1")])


def test_python_a_substituted_hand_rolled_check_compares_no_tolerance():
    _check(_py("assert abs(total() - 78.75) < 0.01", "assert abs(len(items) - 2) < 1e12"),
           BLOCK, [("ASSERT_SUBSTITUTED", "(total() -> len(items))"),
                   ("EXPECTED_VALUE_CHANGED", "expected value rewritten 78.75 -> 2")])


# --- Anything else is still compared ---------------------------------------------------

@pytest.mark.parametrize("before,after,source,expected", [
    # The subject hoisted into a local: the same check, widened.
    ("self.assertAlmostEqual(total(), 78.75, delta=0.01)", "t = total()\nself.assertAlmostEqual(t, 78.75, delta=1e12)",
     _py_unittest_source, "tolerance loosened (delta=0.01 -> delta=1e12)"),
    ("self.assertAlmostEqual(total(), 78.75, places=2)", "t = total()\nself.assertAlmostEqual(t, 78.75, places=0)",
     _py_unittest_source, "tolerance loosened (places=2 -> places=0)"),
    ("assert abs(total() - 78.75) < 0.01", "t = total()\nassert abs(t - 78.75) < 1e12",
     _py_source, "tolerance loosened (abs=0.01 -> abs=1e12)"),
    ("assert total() == pytest.approx(78.75, abs=0.01)", "t = total()\nassert t == pytest.approx(78.75, abs=1e12)",
     _py_source, "tolerance loosened (abs=0.01 -> abs=1e12)"),
    # The subject replaced and the expected literal kept.
    ("assert abs(total() - 78.75) < 0.01", "assert abs(len(items) - 78.75) < 1e12",
     _py_source, "tolerance loosened (abs=0.01 -> abs=1e12)"),
    ("self.assertAlmostEqual(total(), 78.75, delta=0.01)", "self.assertAlmostEqual(len(items), 78.75, delta=1e12)",
     _py_unittest_source, "tolerance loosened (delta=0.01 -> delta=1e12)"),
    # No literal expected value on either side.
    ("expected = 78.75\nassert abs(total() - expected) < 0.01", "other = 2\nassert abs(len(items) - other) < 1e12",
     _py_source, "tolerance loosened (abs=0.01 -> abs=1e12)"),
])
def test_python_a_subject_that_moved_alone_still_compares_its_tolerance(before, after, source, expected):
    _check(_py(before, after, source), BLOCK, [("TOLERANCE_LOOSENED", expected)])


@pytest.mark.parametrize("before,after,header", [
    ("assert.ok(Math.abs(value - 78.75) < 0.01);", "const t = total();\n  assert.ok(Math.abs(t - 78.75) < 1e12);", NODE),
    ("expect(Math.abs(value - 78.75)).toBeLessThan(0.01);",
     "const t = total();\n  expect(Math.abs(t - 78.75)).toBeLessThan(1e12);", VITEST),
    ("assert.ok(Math.abs(value - expected) < 0.01);", "assert.ok(Math.abs(items.length - other) < 1e12);", NODE),
])
def test_js_a_subject_that_moved_alone_still_compares_its_tolerance(before, after, header):
    _check(_js(before, after, header), BLOCK, [("TOLERANCE_LOOSENED", "tolerance loosened (abs=0.01 -> abs=1E+12)")])


def test_js_a_hoisted_close_to_subject_still_compares_its_places():
    _check(_js("expect(value).toBeCloseTo(78.75, 2);", "const t = total();\n  expect(t).toBeCloseTo(78.75, 0);", VITEST),
           BLOCK, [("TOLERANCE_LOOSENED", "tolerance loosened (places=2 -> places=0)")])


def test_js_a_fallback_pair_on_one_subject_still_compares_its_tolerance():
    # A respelling changes the form, so only position pairs the two.
    _check(_js("assert.ok(Math.abs(value - 78.75) < 0.01);", "expect(Math.abs(value - 78.75)).toBeLessThan(1e12);",
               VITEST),
           BLOCK, [("TOLERANCE_LOOSENED", "tolerance loosened (abs=0.01 -> abs=1E+12)")])


@pytest.mark.parametrize("after,expected", [
    ("assert total() == pytest.approx(78.75, abs=1)", [("TOLERANCE_LOOSENED", "tolerance loosened (abs=0.01 -> abs=1)")]),
    # Its centre rewritten too: still compared, beside the rewrite.
    ("assert total() == pytest.approx(75, abs=1)", [("TOLERANCE_LOOSENED", "tolerance loosened (abs=0.01 -> abs=1)"),
                                                     ("EXPECTED_VALUE_CHANGED", "expected value rewritten 78.75 -> 75")]),
])
def test_python_a_fallback_pair_with_an_unrecorded_subject_still_compares_its_tolerance(after, expected):
    # A bare `pytest.approx` comparison records no subject, so it does not
    # differ provably: the hand-rolled check rewritten into one is compared.
    _check(_py("assert abs(total() - 78.75) < 0.01", after), BLOCK, expected)


def test_python_a_weakened_substitution_still_compares_its_tolerance():
    # A strength drop is ASSERT_WEAKENED's, and EXPECTED_VALUE_CHANGED does
    # not report the pair, so its tolerance is still compared.
    _check(_py("self.assertLess(abs(total() - 78.75), 0.01)", "self.assertTrue(abs(len(items) - 2) < 1e12)",
               _py_unittest_source),
           BLOCK, [("ASSERT_WEAKENED", ""), ("TOLERANCE_LOOSENED", "tolerance loosened (abs=0.01 -> abs=1e12)")])

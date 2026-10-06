"""Python comparisons carry a direction (#224).

The Python frontend recorded `<`, `<=`, `>` and `>=` as one form,
`compare_ord`, with no direction, so `assert total() < 80` -> `assert
total() > 80` passed with zero findings, and so did the unittest
`assertLess` -> `assertGreater` swap and a hand-rolled `abs(d) < eps` ->
`> eps`. It now records the same bound key the JavaScript frontend does
(#198): lt, le, gt or ge, read from the subject's side, with the bound as
the operand. Two keyed assertions on one subject are compared by
`ir/predicate.py`, so a reversed direction is "bound direction reversed"
and `<` -> `<=` a widened predicate, in both languages.
"""

import datetime
import functools

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.frontends.python.frontend import parse_python

HEADER = "import unittest\n\nfrom app.billing import total\n"
BLOCK, PASS = "block", "pass"


def _source(line):
    return HEADER + "\n\ndef test_total():\n" + "".join(f"    {part}\n" for part in line.split("\n"))


def _unittest_source(line):
    return (HEADER + "\n\nclass TestTotal(unittest.TestCase):\n    def test_total(self):\n"
            + "".join(f"        {part}\n" for part in line.split("\n")))


def _source_for(line):
    return _unittest_source(line) if line.startswith("self.") else _source(line)


def _assertion(line):
    parsed = parse_python(_source_for(line).encode(), collect_tests=True)
    found = [a for unit in parsed.units for a in unit.side.assertions]
    assert len(found) == 1, found
    return found[0]


@functools.lru_cache(maxsize=None)
def _outcome(before, after):
    # Both sides stand in one unit; a bare `assert` runs in a TestCase method too.
    source = _unittest_source if "self." in before + after else _source
    changes = [FileChange("tests/test_billing.py", "modified", source(before).encode(), source(after).encode())]
    _ir, findings, verdict = analyze(changes, Config(), Contract(), [], datetime.date(2026, 10, 6))
    return verdict, tuple((f.rule, f.severity, f.message) for f in findings)


# --- What is recorded ---------------------------------------------------------------------

@pytest.mark.parametrize("line,reading", [
    ("assert total() < 80", ("total()", "lt", "80", True)),
    ("assert total() <= 80", ("total()", "le", "80", True)),
    ("assert total() > 80", ("total()", "gt", "80", True)),
    ("assert total() >= 80", ("total()", "ge", "80", True)),
    # The literal on the left is read from the subject's side.
    ("assert 80 > total()", ("total()", "lt", "80", True)),
    ("assert 80 >= total()", ("total()", "le", "80", True)),
    ("assert 80 < total()", ("total()", "gt", "80", True)),
    ("assert 80 <= total()", ("total()", "ge", "80", True)),
    # Two expressions: the left one is the subject.
    ("assert total() < limit()", ("total()", "lt", "limit()", True)),
    # `not` negates the key it keeps.
    ("assert not total() >= 80", ("total()", "ge", "80", False)),
    # The bound is one line of its source, parentheses aside.
    ("assert total() < (\n    80 +\n    1)", ("total()", "lt", "80 + 1", True)),
    # unittest's ordering methods.
    ("self.assertLess(total(), 80)", ("total()", "lt", "80", True)),
    ("self.assertLessEqual(total(), 80)", ("total()", "le", "80", True)),
    ("self.assertGreater(total(), 80)", ("total()", "gt", "80", True)),
    ("self.assertGreaterEqual(total(), 80)", ("total()", "ge", "80", True)),
    ("self.assertGreater(80, total())", ("total()", "lt", "80", True)),
    ("self.assertLessEqual(80, total())", ("total()", "ge", "80", True)),
    # A hand-rolled bound states its key too, above (a tolerance) or below.
    ("assert abs(total() - 78.75) < 0.01", ("total()", "lt", "0.01", True)),
    ("assert abs(total() - 78.75) <= 0.01", ("total()", "le", "0.01", True)),
    ("assert abs(total() - 78.75) > 0.01", ("total()", "gt", "0.01", True)),
    ("assert abs(total() - 78.75) >= 0.01", ("total()", "ge", "0.01", True)),
    ("self.assertGreaterEqual(0.01, abs(total() - 78.75))", ("total()", "le", "0.01", True)),
    ("self.assertGreaterEqual(abs(total() - 78.75), 0.01)", ("total()", "ge", "0.01", True)),
    ("self.assertLessEqual(abs(total() - 78.75), 0.01)", ("total()", "le", "0.01", True)),
    ("self.assertLess(0.01, abs(total() - 78.75))", ("total()", "gt", "0.01", True)),
])
def test_a_comparison_records_its_bound_key(line, reading):
    a = _assertion(line)
    assert (a.left, a.predicate, a.operand_source, a.positive) == reading


@pytest.mark.parametrize("line", [
    "assert total() == 78.75",
    "assert total() != 78.75",
    "assert total() in (78.75, 80)",
    "assert total() is not None",
    # A chained range keeps its bound-tuple reading.
    "assert 0 < total() < 80",
    # A comparison inside a truthy spelling states no key, as in JavaScript.
    "self.assertTrue(total() < 80)",
    "self.assertEqual(total(), 78.75)",
])
def test_other_assertions_record_no_bound_key(line):
    a = _assertion(line)
    assert (a.predicate, a.operand_source) == (None, None)


def test_a_lower_bound_records_no_tolerance_and_keeps_its_centre():
    a = _assertion("assert abs(total() - 78.75) > 0.01")
    assert (a.left, a.right_value, a.epsilon, a.epsilon_kind) == ("total()", "78.75", None, None)
    a = _assertion("assert abs(total() - 78.75) < 0.01")
    assert (a.left, a.right_value, a.epsilon, a.epsilon_kind) == ("total()", "78.75", "abs=0.01", "abs")


# --- What is reported ---------------------------------------------------------------------

_REVERSED = "bound direction reversed"


@pytest.mark.parametrize("before,after,shown", [
    # #224's D1-D6.
    ("assert total() < 80", "assert total() > 80", "(< 80 -> > 80)"),
    ("assert total() <= 80", "assert total() >= 80", "(<= 80 -> >= 80)"),
    ("assert 80 > total()", "assert 80 < total()", "(< 80 -> > 80)"),
    ("assert total() < 80", "assert 80 < total()", "(< 80 -> > 80)"),
    ("self.assertLess(total(), 80)", "self.assertGreater(total(), 80)", "(< 80 -> > 80)"),
    ("assert abs(total() - 78.75) < 0.01", "assert abs(total() - 78.75) > 0.01", "(< 0.01 -> > 0.01)"),
    # Across spellings, and from a lower bound to an upper one.
    ("assert total() < 80", "self.assertGreater(total(), 80)", "(< 80 -> > 80)"),
    ("self.assertGreater(abs(total() - 78.75), 0.01)", "self.assertLess(abs(total() - 78.75), 0.01)",
     "(> 0.01 -> < 0.01)"),
    ("self.assertTrue(abs(total() - 78.75) < 0.01)", "self.assertTrue(abs(total() - 78.75) > 0.01)",
     "(< 0.01 -> > 0.01)"),
])
def test_a_reversed_direction_contradicts_the_old_bound(before, after, shown):
    verdict, findings = _outcome(before, after)
    assert verdict == BLOCK
    assert [(rule, severity) for rule, severity, _ in findings] == [("ASSERT_WEAKENED", "high")]
    assert f"{_REVERSED} {shown} — the new assertion contradicts the old one" in findings[0][2]


@pytest.mark.parametrize("before,after,shown", [
    # D7, and E2, which reported "the test now proves the opposite": `not x
    # >= 80` also passes NaN, so it widens `x < 80` rather than inverting it.
    ("assert total() < 80", "assert total() <= 80", "(< 80 -> <= 80)"),
    ("assert total() < 80", "assert not total() >= 80", "(< 80 -> not >= 80)"),
    ("assert total() > 0", "assert total() >= 0", "(> 0 -> >= 0)"),
    ("assert abs(total() - 78.75) < 0.01", "assert abs(total() - 78.75) <= 0.01", "(< 0.01 -> <= 0.01)"),
])
def test_a_bound_that_also_admits_its_edge_is_a_widened_predicate(before, after, shown):
    verdict, findings = _outcome(before, after)
    assert verdict == BLOCK
    assert [rule for rule, _, _ in findings] == ["ASSERT_WEAKENED"]
    assert f"assertion predicate widened {shown}" in findings[0][2]


@pytest.mark.parametrize("before,after", [
    # E1 and the other spellings of one predicate.
    ("assert total() < 80", "assert 80 > total()"),
    ("self.assertLess(total(), 80)", "assert total() < 80"),
    ("assert 80 > total()", "self.assertLess(total(), 80)"),
    ("self.assertGreater(80, total())", "assert total() < 80"),
    ("assert abs(total() - 78.75) > 0.01", "assert 0.01 < abs(total() - 78.75)"),
    # A tightening.
    ("assert total() <= 80", "assert total() < 80"),
])
def test_one_predicate_spelled_otherwise_is_no_finding(before, after):
    assert _outcome(before, after) == (PASS, ())


@pytest.mark.parametrize("before,after,expected", [
    # C1: a flipped equality is still the inversion.
    ("assert total() == 78.75", "assert total() != 78.75",
     [("ASSERT_WEAKENED", "assertion polarity inverted (positive -> negative) — the test now proves the opposite")]),
    # C2: a moved bound is still an expected value rewritten, and so is a chained range.
    ("assert total() < 80", "assert total() < 1e12",
     [("EXPECTED_VALUE_CHANGED", "expected value rewritten 80 -> 1000000000000.0")]),
    ("assert 0 < total() < 80", "assert 0 < total() < 90",
     [("EXPECTED_VALUE_CHANGED", "expected value rewritten (0, 80) -> (0, 90)")]),
    # A lower bound's centre is its expected value, as an upper bound's is.
    ("assert abs(total() - 78.75) > 0.01", "assert abs(total() - 75) > 0.01",
     [("EXPECTED_VALUE_CHANGED", "expected value rewritten 78.75 -> 75")]),
    # A hand-rolled tolerance replaced by a plain bound: the centre and the
    # bound differ, which EXPECTED_VALUE_CHANGED reports. The plain bound is
    # no tolerance checkwash cannot read: Python records every bound as
    # written, so a lost one is JavaScript's reading only.
    ("assert abs(total() - 78.75) < 0.01", "assert total() < 80",
     [("EXPECTED_VALUE_CHANGED", "expected value rewritten 78.75 -> 80")]),
])
def test_the_other_rules_keep_their_findings(before, after, expected):
    verdict, findings = _outcome(before, after)
    assert verdict == BLOCK
    assert [rule for rule, _, _ in findings] == [rule for rule, _ in expected]
    for (_, _, message), (_, text) in zip(findings, expected):
        assert text in message


@pytest.mark.parametrize("before,after", [
    # A lower bound's value is neither an expected value nor a tolerance,
    # and neither spelling compares it, as in JavaScript (row 110's residual).
    ("assert abs(total() - 78.75) > 0.01", "assert abs(total() - 78.75) > 0.5"),
    ("assert abs(total() - 78.75) > 0.5", "assert abs(total() - 78.75) > 0.01"),
])
def test_a_lower_bounds_value_is_not_compared(before, after):
    assert _outcome(before, after) == (PASS, ())


_HELPER = "\n\ndef check(value):\n    assert value {op} 80\n\n\ndef test_total():\n    check(total())\n"
_FIXTURE = ("import pytest\n\n\n@pytest.fixture\ndef checked():\n    value = total()\n    assert value {op} 80\n"
            "    return value\n\n\ndef test_total(checked):\n    assert checked\n")


@pytest.mark.parametrize("module", [_HELPER, _FIXTURE], ids=["same-file helper", "fixture"])
def test_a_lent_comparison_carries_its_key(module):
    # A helper's assertions are the test's own, inherited; a fixture's are lent
    # by the engine. Both keep the key, so the flip is reported there too.
    before, after = (HEADER + module.format(op=op) for op in ("<", ">"))
    changes = [FileChange("tests/test_billing.py", "modified", before.encode(), after.encode())]
    _ir, findings, verdict = analyze(changes, Config(), Contract(), [], datetime.date(2026, 10, 6))
    assert verdict == BLOCK
    assert [(f.rule, f.severity) for f in findings] == [("ASSERT_WEAKENED", "high")]
    assert f"{_REVERSED} (< 80 -> > 80)" in findings[0].message


def test_a_changed_subject_is_a_rewrite_not_a_reversal():
    verdict, findings = _outcome("assert total() < 80", "assert other() > 80")
    assert all(_REVERSED not in message for _, _, message in findings)

"""A negated approximate comparison is read as negated (#284).

The approx branch ran first and found an `approx(...)` call anywhere in the
test expression, so `!=` and a `not` around the comparison were never read:
`== approx(x)` -> `!= approx(x)` passed with zero findings, while the same
flip without `approx` blocked. A negated approximate comparison passes when
the values are far apart, so its tolerance orders the other way: a bigger
`abs`/`delta` or fewer `places` is stricter. The Python frontend compared it
in the positive direction, so a stricter one blocked as loosened.

1. The approx branch reads the comparison it sits in: `!=` is negative, and
   a `not` around it negates, as the plain comparison path reads them.
2. A negated approximate comparison records no tolerance, as in JavaScript:
   its tolerance edits are unknown rather than read backwards.
"""
import ast
import datetime

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.frontends.python.frontend import _classify_assert_expr, _Offsets, parse_python
from checkwash.ir.astutil import asserted_subject

TEST = "tests/test_billing.py"
HEAD = "import unittest\n\nimport pytest\n\nfrom app.billing import total\n\n\n"


def py(statement):
    return HEAD + "def test_total():\n    " + statement + "\n"


def ut(statement):
    return HEAD + "class TotalTest(unittest.TestCase):\n    def test_total(self):\n        " + statement + "\n"


def outcome(before, after):
    _ir, findings, verdict = analyze(
        [FileChange(TEST, "modified", before.encode(), after.encode())],
        Config(), Contract(), [], datetime.date(2026, 10, 6),
    )
    return verdict, [(f.rule, f.severity, f.message.split(": ", 1)[1]) for f in findings]


INVERTED = ("block", [("ASSERT_WEAKENED", "high",
                       "assertion polarity inverted (positive -> negative) — the test now proves the opposite")])
QUIET = ("pass", [])


# --- 1: `!=` and `not` are read ----------------------------------------------------

@pytest.mark.parametrize("before, after", [
    (py("assert total() == pytest.approx(78.75)"), py("assert total() != pytest.approx(78.75)")),
    (py("assert pytest.approx(78.75) == total()"), py("assert pytest.approx(78.75) != total()")),
    (py("assert total() == pytest.approx(78.75)"), py("assert not total() == pytest.approx(78.75)")),
    (py("assert total() == pytest.approx(78.75)"), py("assert not (total() == pytest.approx(78.75))")),
    (py("assert total() == pytest.approx(78.75, abs=0.01)"), py("assert total() != pytest.approx(78.75, abs=0.01)")),
    (py("assert [total()] == pytest.approx([78.75])"), py("assert [total()] != pytest.approx([78.75])")),
    (py("assert {'t': total()} == {'t': pytest.approx(78.75)}"),
     py("assert {'t': total()} != {'t': pytest.approx(78.75)}")),
    (py("assert total() in [pytest.approx(78.75), pytest.approx(80)]"),
     py("assert total() not in [pytest.approx(78.75), pytest.approx(80)]")),
    # the contrasts the issue names, read before #284 and unchanged
    (py("assert total() == 78.75"), py("assert total() != 78.75")),
    (ut("self.assertAlmostEqual(total(), 78.75)"), ut("self.assertNotAlmostEqual(total(), 78.75)")),
], ids=["ne", "ne_approx_left", "not", "not_parenthesized", "ne_with_tolerance", "list", "nested_in_dict",
        "not_in", "plain_contrast", "unittest_contrast"])
def test_an_approx_comparison_flipped_to_its_negation_is_an_inversion(before, after):
    verdict, findings = outcome(before, after)
    assert verdict == "block"
    assert [f[:2] for f in findings] == [("ASSERT_WEAKENED", "high")]
    assert "polarity inverted (positive -> negative)" in findings[0][2]


def test_the_negation_flipped_back_is_an_inversion_too():
    before, after = py("assert total() != pytest.approx(78.75)"), py("assert total() == pytest.approx(78.75)")
    verdict, findings = outcome(before, after)
    assert verdict == "block"
    assert "polarity inverted (negative -> positive)" in findings[0][2]


def test_a_negated_comparison_keeps_its_expected_value():
    """The expected value is recorded on either polarity, as for a plain `!=`."""
    for before, after in [
        (py("assert total() != pytest.approx(78.75)"), py("assert total() != pytest.approx(75)")),
        (py("assert total() != 78.75"), py("assert total() != 75")),
        (ut("self.assertNotAlmostEqual(total(), 78.75)"), ut("self.assertNotAlmostEqual(total(), 75)")),
    ]:
        assert outcome(before, after) == ("block", [
            ("EXPECTED_VALUE_CHANGED", "high", "expected value rewritten 78.75 -> 75 with no change in assertion strength"),
        ])


# --- 1, with #331: the flipped statement is compared by what it checks -------------
#
# An approx comparison records no subject, so #331 compares what each statement
# checks. A negated comparison anywhere in it is read in its positive form, as a
# `not` is peeled: without that, a flip of an approx comparison with no direct
# approx side read as a replacement, since the operator was part of what the
# statement checks.

@pytest.mark.parametrize("positive, negative", [
    ("assert {'t': total()} == {'t': pytest.approx(78.75)}", "assert {'t': total()} != {'t': pytest.approx(78.75)}"),
    ("assert total() in [pytest.approx(78.75), pytest.approx(80)]",
     "assert total() not in [pytest.approx(78.75), pytest.approx(80)]"),
    ("assert total() == pytest.approx(78.75)", "assert total() != pytest.approx(78.75)"),
    ("assert result is None", "assert result is not None"),
    # where the comparison sits inside the statement
    ("assert total() == pytest.approx(78.75) and total() > 0", "assert total() != pytest.approx(78.75) and total() > 0"),
    ("assert all([t == pytest.approx(78.75) for t in [total()]])",
     "assert all([t != pytest.approx(78.75) for t in [total()]])"),
    ("assert 0 < total() == pytest.approx(78.75)", "assert 0 < total() != pytest.approx(78.75)"),
    ("assert (total() == pytest.approx(78.75)) is True", "assert (total() != pytest.approx(78.75)) is True"),
], ids=["nested_in_dict", "not_in", "direct_approx", "is_not", "and", "all", "chained", "inside_a_comparison"])
def test_a_negated_comparison_checks_what_its_positive_form_checks(positive, negative):
    assert asserted_subject(negative) == asserted_subject(positive) is not None
    assert asserted_subject("assert not (" + positive.removeprefix("assert ") + ")") == asserted_subject(positive)


@pytest.mark.parametrize("before, after", [
    ("assert total() == pytest.approx(78.75) and total() > 0", "assert other() != pytest.approx(78.75) and total() > 0"),
    ("assert all([t == pytest.approx(78.75) for t in [total()]])",
     "assert all([t != pytest.approx(78.75) for t in [other()]])"),
    ("assert result.okay != 0", "assert result.exception == 0"),
], ids=["and", "all", "attribute"])
def test_a_negated_comparison_onto_another_subject_checks_another_thing(before, after):
    assert asserted_subject(before) != asserted_subject(after)


@pytest.mark.parametrize("before, after", [
    (py("assert {'t': total()} == {'t': pytest.approx(78.75)}"),
     py("assert {'t': other()} != {'t': pytest.approx(78.75)}")),
    (py("assert total() in [pytest.approx(78.75), pytest.approx(80)]"),
     py("assert other() not in [pytest.approx(78.75), pytest.approx(80)]")),
], ids=["nested_in_dict", "not_in"])
def test_a_flip_onto_another_subject_is_a_replacement(before, after):
    verdict, findings = outcome(before, after)
    assert verdict == "block"
    assert [f[:2] for f in findings] == [("ASSERT_WEAKENED", "high")]
    assert findings[0][2].startswith("assertion replaced — subject and polarity both changed")


# --- 2: a negated approximate comparison records no tolerance ----------------------

@pytest.mark.parametrize("before, after", [
    # stricter: the values must now be further apart (blocked as loosened before #284)
    (py("assert total() != pytest.approx(78.75, abs=0.01)"), py("assert total() != pytest.approx(78.75, abs=0.5)")),
    (ut("self.assertNotAlmostEqual(total(), 78.75, delta=0.1)"),
     ut("self.assertNotAlmostEqual(total(), 78.75, delta=0.5)")),
    (ut("self.assertNotAlmostEqual(total(), 78.75, places=3)"),
     ut("self.assertNotAlmostEqual(total(), 78.75, places=2)")),
    # looser: unknown, not read backwards
    (py("assert total() != pytest.approx(78.75, abs=0.5)"), py("assert total() != pytest.approx(78.75, abs=0.01)")),
    (ut("self.assertNotAlmostEqual(total(), 78.75, delta=0.5)"),
     ut("self.assertNotAlmostEqual(total(), 78.75, delta=0.01)")),
    (ut("self.assertNotAlmostEqual(total(), 78.75, places=2)"),
     ut("self.assertNotAlmostEqual(total(), 78.75, places=3)")),
    (py("assert not total() == pytest.approx(78.75, rel=1e-6)"),
     py("assert not total() == pytest.approx(78.75, rel=1e-2)")),
    (py("assert total() not in [pytest.approx(78.75, abs=0.01)]"),
     py("assert total() not in [pytest.approx(78.75, abs=0.5)]")),
], ids=["approx_stricter", "delta_stricter", "places_stricter", "approx_looser", "delta_looser", "places_looser",
        "not_approx", "not_in_stricter"])
def test_a_negated_tolerance_edit_is_unknown(before, after):
    assert outcome(before, after) == QUIET


def test_a_positive_tolerance_is_still_compared():
    before, after = py("assert total() == pytest.approx(78.75, abs=0.01)"), py("assert total() == pytest.approx(78.75, abs=0.5)")
    assert outcome(before, after) == ("block", [("TOLERANCE_LOOSENED", "high", "tolerance loosened (abs=0.01 -> abs=0.5)")])
    before, after = ut("self.assertAlmostEqual(total(), 78.75, delta=0.1)"), ut("self.assertAlmostEqual(total(), 78.75, delta=0.5)")
    assert outcome(before, after)[0] == "block"


# --- the IR ---------------------------------------------------------------------------

def _classified(statement):
    source = py(statement)
    return _classify_assert_expr(ast.parse(source).body[-1].body[0].test, _Offsets(source))


@pytest.mark.parametrize("statement, positive, epsilon", [
    ("assert total() == pytest.approx(78.75, abs=0.01)", True, "abs=0.01"),
    ("assert total() != pytest.approx(78.75, abs=0.01)", False, None),
    ("assert pytest.approx(78.75, abs=0.01) != total()", False, None),
    ("assert not total() == pytest.approx(78.75, abs=0.01)", False, None),
    # a double negation is positive, and reads as a tolerance not recorded
    ("assert not total() != pytest.approx(78.75, abs=0.01)", True, None),
])
def test_the_approx_classification(statement, positive, epsilon):
    c = _classified(statement)
    assert (c.form, c.positive, c.right_literal) == ("approx", positive, "78.75")
    assert c.epsilon == epsilon


@pytest.mark.parametrize("call, positive, tolerance", [
    ("self.assertAlmostEqual(total(), 78.75)", True, ("places", "7")),
    ("self.assertAlmostEqual(total(), 78.75, delta=0.1)", True, ("delta", "0.1")),
    ("self.assertNotAlmostEqual(total(), 78.75)", False, (None, None)),
    ("self.assertNotAlmostEqual(total(), 78.75, delta=0.1)", False, (None, None)),
    ("self.assertNotAlmostEqual(total(), 78.75, 2)", False, (None, None)),
])
def test_the_unittest_tolerance_is_recorded_on_the_positive_call_only(call, positive, tolerance):
    [unit] = [u for u in parse_python(ut(call).encode(), collect_tests=True).units]
    [assertion] = unit.side.assertions
    assert (assertion.form, assertion.positive) == ("approx", positive)
    assert (assertion.epsilon_kind, assertion.epsilon) == tolerance

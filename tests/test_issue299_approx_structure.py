"""An assertion is an approximate comparison only where it states one (#299).

The approx branch found an `approx(...)` call anywhere in the test
expression and read the whole assertion as that approximate comparison, so a
disjunction that makes it hold everywhere (`== approx(x) or True`), a
comparison of its result (`(x == approx(y)) is not None`) or an unrelated call
(`print(approx(x)) is None`) read as the comparison itself and gave zero
findings.

The assertion states the approximate comparison when the call is an operand
of its own `==`, `!=`, `in` or `not in` (or sits inside one through container
displays), and, since each part must hold, when such a comparison is a link of
a chained comparison, is conjoined with `and`, or is asserted with `all(...)`
over a comprehension. Anything else is read as the plain path reads it.
"""
import ast
import datetime

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.frontends.python.frontend import _classify_assert_expr, _Offsets

HEAD = "import pytest\n\nfrom app.billing import total\n\n\n"
APPROX = "assert total() == pytest.approx(78.75)"


def py(statement):
    return HEAD + "def test_total():\n    " + statement + "\n"


def outcome(before, after):
    _ir, findings, verdict = analyze(
        [FileChange("tests/test_billing.py", "modified", py(before).encode(), py(after).encode())],
        Config(), Contract(), [], datetime.date(2026, 10, 6),
    )
    return verdict, [(f.rule, f.severity, f.message.split(": ", 1)[1]) for f in findings]


def classified(statement):
    source = py(statement)
    return _classify_assert_expr(ast.parse(source).body[-1].body[0].test, _Offsets(source))


# --- the issue's rows: each was zero findings -------------------------------------------

@pytest.mark.parametrize("after, message", [
    ("assert total() == pytest.approx(78.75) or True", "assertion strength APPROX(70) -> TRUTHY(20)"),
    ("assert True or total() == pytest.approx(78.75)", "assertion strength APPROX(70) -> TRUTHY(20)"),
    ("assert total() == pytest.approx(78.75) or total() > 0", "assertion strength APPROX(70) -> TRUTHY(20)"),
    ("assert isinstance(total(), float) or pytest.approx(78.75) == total()",
     "assertion strength APPROX(70) -> TRUTHY(20)"),
    ("assert any(t == pytest.approx(78.75) for t in [total()])", "assertion strength APPROX(70) -> TRUTHY(20)"),
    ("assert print(pytest.approx(78.75)) is None", "assertion strength APPROX(70) -> NON_NULL(30)"),
], ids=["or_true", "true_or", "or_bound", "or_isinstance", "any", "unrelated_call"])
def test_a_structure_around_the_comparison_that_weakens_it_is_reported(after, message):
    assert outcome(APPROX, after) == ("block", [("ASSERT_WEAKENED", "high", message)])


def test_a_comparison_of_the_comparisons_result_is_reported():
    """A bool is never None: the assertion holds everywhere."""
    verdict, findings = outcome(APPROX, "assert (total() == pytest.approx(78.75)) is not None")
    assert verdict == "block"
    assert [f[:2] for f in findings] == [("ASSERT_WEAKENED", "high")]


# --- what keeps the approximate reading ---------------------------------------------------

@pytest.mark.parametrize("before, after, finding", [
    # the plain spellings, unchanged
    (APPROX, "assert total() == pytest.approx(75)",
     ("EXPECTED_VALUE_CHANGED", "high", "expected value rewritten 78.75 -> 75 with no change in assertion strength")),
    ("assert [total()] == pytest.approx([78.75])", "assert [total()] == pytest.approx([75])",
     ("EXPECTED_VALUE_CHANGED", "high",
      "expected value rewritten [78.75] -> [75] with no change in assertion strength")),
    ("assert {'t': total()} == {'t': pytest.approx(78.75)}", "assert {'t': total()} == {'t': pytest.approx(75)}",
     ("EXPECTED_VALUE_CHANGED", "high", "expected value rewritten 78.75 -> 75 with no change in assertion strength")),
    ("assert total() == pytest.approx(78.75, abs=0.01)", "assert total() == pytest.approx(78.75, abs=0.5)",
     ("TOLERANCE_LOOSENED", "high", "tolerance loosened (abs=0.01 -> abs=0.5)")),
    # a conjunction asserts each part
    ("assert total() == pytest.approx(78.75) and total() > 0", "assert total() == pytest.approx(75) and total() > 0",
     ("EXPECTED_VALUE_CHANGED", "high", "expected value rewritten 78.75 -> 75 with no change in assertion strength")),
    ("assert total() > 0 and total() == pytest.approx(78.75)", "assert total() > 0 and total() == pytest.approx(75)",
     ("EXPECTED_VALUE_CHANGED", "high", "expected value rewritten 78.75 -> 75 with no change in assertion strength")),
    # all() asserts it for every item
    ("assert all(t == pytest.approx(78.75) for t in [total()])",
     "assert all(t == pytest.approx(75) for t in [total()])",
     ("EXPECTED_VALUE_CHANGED", "high", "expected value rewritten 78.75 -> 75 with no change in assertion strength")),
    ("assert all(t == pytest.approx(78.75) for t in [total()])",
     "assert any(t == pytest.approx(78.75) for t in [total()])",
     ("ASSERT_WEAKENED", "high", "assertion strength APPROX(70) -> TRUTHY(20)")),
    # a chained comparison holds each of its links
    ("assert 0 < total() == pytest.approx(78.75)", "assert 0 < total() == pytest.approx(75)",
     ("EXPECTED_VALUE_CHANGED", "high", "expected value rewritten 78.75 -> 75 with no change in assertion strength")),
], ids=["expected", "list", "dict", "tolerance", "and_left", "and_right", "all", "all_to_any", "chained"])
def test_the_approximate_reading_is_kept_where_the_assertion_states_it(before, after, finding):
    assert outcome(before, after) == ("block", [finding])


@pytest.mark.parametrize("before, after", [
    ("assert total() == pytest.approx(78.75) and total() > 0", "assert total() != pytest.approx(78.75) and total() > 0"),
    ("assert all([t == pytest.approx(78.75) for t in [total()]])",
     "assert all([t != pytest.approx(78.75) for t in [total()]])"),
    ("assert 0 < total() == pytest.approx(78.75)", "assert 0 < total() != pytest.approx(78.75)"),
], ids=["and", "all", "chained"])
def test_the_stated_comparison_carries_its_polarity(before, after):
    verdict, findings = outcome(before, after)
    assert verdict == "block"
    assert "polarity inverted (positive -> negative)" in findings[0][2]


@pytest.mark.parametrize("before, after", [
    (APPROX, "assert pytest.approx(78.75) == total()"),
    (APPROX, "assert total() == pytest.approx(78.75) and total() > 0"),
    ("assert total() == pytest.approx(78.75) and total() > 0", "assert total() > 0 and total() == pytest.approx(78.75)"),
])
def test_respellings_are_quiet(before, after):
    assert outcome(before, after) == ("pass", [])


# --- the classification ---------------------------------------------------------------------

@pytest.mark.parametrize("statement, form", [
    ("assert total() == pytest.approx(78.75)", "approx"),
    # `from pytest import approx`
    ("assert total() == approx(78.75)", "approx"),
    ("assert total() in [pytest.approx(78.75), pytest.approx(80)]", "approx"),
    ("assert total() == pytest.approx(78.75) and total() > 0", "approx"),
    ("assert all(t == pytest.approx(78.75) for t in [total()])", "approx"),
    ("assert 0 < total() == pytest.approx(78.75)", "approx"),
    ("assert totals() == [*[pytest.approx(78.75)], 80.0]", "approx"),
    ("assert total() == pytest.approx(78.75) or True", "truthy"),
    ("assert any(t == pytest.approx(78.75) for t in [total()])", "truthy"),
    # pytest's own approx tests compare a string: the string is the expectation
    ("assert repr(pytest.approx(1.0)) == '1.0 ± 1.0e-06'", "compare_eq"),
    # approx answers equality and membership only
    ("assert total() is pytest.approx(78.75)", "compare_eq"),
    ("assert total() < pytest.approx(80)", "compare_ord"),
    # a call that receives an approx object is the call: an operator is not told from any other function
    ("assert operator.eq(total(), pytest.approx(78.75))", "truthy"),
    ("assert isinstance(pytest.approx(78.75), object)", "tautology"),
])
def test_the_form(statement, form):
    assert classified(statement).form == form


def test_a_string_compared_with_an_approx_repr_is_the_expected_value():
    before = "assert repr(pytest.approx(1.0)) == '1.0 ± 1.0e-06'"
    after = "assert repr(pytest.approx(1.0)) == '1.0 ± 1.0e-03'"
    verdict, findings = outcome(before, after)
    assert verdict == "block"
    assert [f[0] for f in findings] == ["EXPECTED_VALUE_CHANGED"]

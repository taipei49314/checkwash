"""Python tolerance calls are approximate comparisons (#222).

`assert math.isclose(total(), 78.75, abs_tol=1e-9)` -> `abs_tol=1e3` passed
with zero findings: the assertion was truthy and carried no tolerance. numpy's
and torch's assertion calls were no assertions at all, so widening
`assert_allclose`'s `rtol`, or deleting the call, passed too. One table now
maps math.isclose, numpy's isclose, allclose, testing.assert_allclose,
testing.assert_array_almost_equal and testing.assert_almost_equal, and
torch.testing.assert_close to the approximate form, with their tolerances,
each absent one's default, and the value they compare against (222.Q1).
`assertTrue(<call>)` is read as the call (222.Q2), and torch's omitted pair is
unknown (222.Q3).
"""

import ast
import datetime
import functools
from decimal import Decimal

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.detectors.assert_weakened import _tolerance_lost
from checkwash.detectors.tolerance_loosened import _absolute_bound, _mixed
from checkwash.engine import analyze
from checkwash.frontends.python.frontend import parse_python
from checkwash.frontends.python.tolerance_calls import (
    TOLERANCE_CALLS,
    callee,
    find_predicate,
    import_names,
    statement_call,
    tolerance,
    values,
)
from checkwash.ir.model import Assertion

HEADER = "import math\nimport unittest\n\nimport numpy as np\nimport pytest\nimport torch\n\nfrom billing import total\n"


def _source(line, imports=""):
    return (HEADER + imports + "\n\ndef test_total():\n" + "".join(f"    {part}\n" for part in line.split("\n")))


def _unittest_source(line, imports=""):
    return (HEADER + imports + "\n\nclass TestTotal(unittest.TestCase):\n    def test_total(self):\n"
            + "".join(f"        {part}\n" for part in line.split("\n")))


@functools.lru_cache(maxsize=None)
def _outcome(before, after):
    changes = [FileChange("tests/test_billing.py", "modified", before.encode(), after.encode())]
    _ir, findings, verdict = analyze(changes, Config(), Contract(), [], datetime.date(2026, 10, 6))
    return verdict, tuple((f.rule, f.severity, f.message) for f in findings)


def _assertions(source):
    parsed = parse_python(source.encode(), collect_tests=True)
    return [a for unit in parsed.units for a in unit.side.assertions]


def _assertion(line, imports="", unittest_style=False):
    found = _assertions((_unittest_source if unittest_style else _source)(line, imports))
    assert len(found) == 1, found
    return found[0]


def _call(expression):
    return ast.parse(expression, mode="eval").body


# --- The table ----------------------------------------------------------------------------

def test_each_call_records_the_defaults_its_library_states():
    # Read from CPython (`math.isclose`) and numpy 2.3.3's signatures; torch's
    # pair depends on the dtype, so it has none (222.Q3).
    defaults = {name: {key: default for _kw, key, _pos, default in entry.tolerances}
                for name, entry in TOLERANCE_CALLS.items()}
    assert defaults == {
        "math.isclose": {"abs": "0.0", "rel": "1e-09"},
        "numpy.isclose": {"abs": "1e-08", "rel": "1e-05"},
        "numpy.allclose": {"abs": "1e-08", "rel": "1e-05"},
        "numpy.testing.assert_allclose": {"abs": "0", "rel": "1e-07"},
        "numpy.testing.assert_array_almost_equal": {"decimal": "6"},
        "numpy.testing.assert_almost_equal": {"decimal": "7"},
        "torch.testing.assert_close": {"abs": None, "rel": None},
    }


@pytest.mark.parametrize("name,statement", [
    ("math.isclose", False), ("numpy.isclose", False), ("numpy.allclose", False),
    ("numpy.testing.assert_allclose", True), ("numpy.testing.assert_array_almost_equal", True),
    ("numpy.testing.assert_almost_equal", True), ("torch.testing.assert_close", True),
])
def test_predicates_are_tested_and_assertion_calls_are_statements(name, statement):
    assert TOLERANCE_CALLS[name].statement is statement


# --- Names, read through the file's imports -----------------------------------------------

@pytest.mark.parametrize("module,expression,expected", [
    ("import math", "math.isclose(a, b)", "math.isclose"),
    ("from math import isclose", "isclose(a, b)", "math.isclose"),
    ("from math import isclose as close", "close(a, b)", "math.isclose"),
    ("import numpy as np", "np.isclose(a, b)", "numpy.isclose"),
    ("import numpy", "numpy.allclose(a, b)", "numpy.allclose"),
    ("import numpy.testing as npt", "npt.assert_allclose(a, b)", "numpy.testing.assert_allclose"),
    ("import numpy.testing", "numpy.testing.assert_allclose(a, b)", "numpy.testing.assert_allclose"),
    ("from numpy import testing", "testing.assert_almost_equal(a, b)", "numpy.testing.assert_almost_equal"),
    ("from numpy.testing import assert_array_almost_equal as aaae", "aaae(a, b)",
     "numpy.testing.assert_array_almost_equal"),
    ("np = pytest.importorskip('numpy')", "np.testing.assert_allclose(a, b)", "numpy.testing.assert_allclose"),
    ("np: object = pytest.importorskip('numpy')", "np.isclose(a, b)", "numpy.isclose"),
    ("(np := pytest.importorskip('numpy'))", "np.isclose(a, b)", "numpy.isclose"),
    ("from torch.testing import assert_close", "assert_close(a, b)", "torch.testing.assert_close"),
    ("", "math.isclose(a, b)", "math.isclose"),
    ("", "numpy.testing.assert_allclose(a, b)", "numpy.testing.assert_allclose"),
])
def test_a_call_is_read_through_the_imports_that_bind_its_name(module, expression, expected):
    assert callee(_call(expression), import_names(ast.parse(module))) == expected


@pytest.mark.parametrize("module,expression", [
    ("", "np.isclose(a, b)"),
    ("", "isclose(a, b)"),
    ("from mylib import isclose", "isclose(a, b)"),
    ("from .math import isclose", "isclose(a, b)"),
    ("import numpy as np\nnp = make_fake()", "np.isclose(a, b)"),
    ("import numpy as np\nnp += pytest.importorskip('numpy')", "np.isclose(a, b)"),
    ("from math import isclose\ndef isclose(a, b):\n    return True", "isclose(a, b)"),
    ("import numpy as np", "np.array_equal(a, b)"),
    ("from math import *", "isclose(a, b)"),
])
def test_a_name_bound_to_anything_else_is_not_read(module, expression):
    assert callee(_call(expression), import_names(ast.parse(module))) is None


def test_a_predicate_is_found_inside_the_call_that_tests_it():
    names = import_names(ast.parse("import numpy as np\nimport math"))
    for expression in ("np.isclose(a, b).all()", "np.all(np.isclose(a, b))",
                       "all(math.isclose(x, y) for x, y in pairs)"):
        found = find_predicate(_call(expression), names)
        assert found is not None and found[1] in ("numpy.isclose", "math.isclose"), expression
    assert find_predicate(_call("np.testing.assert_allclose(a, b)"), names) is None
    assert statement_call(_call("np.testing.assert_allclose(a, b)"), names) == "numpy.testing.assert_allclose"
    assert statement_call(_call("np.isclose(a, b)"), names) is None


# --- What a call records ------------------------------------------------------------------

def _seg(source):
    return lambda node: ast.get_source_segment(source, node)


@pytest.mark.parametrize("expression,name,expected", [
    ("isclose(a, b)", "math.isclose", ("abs=0.0|rel=1e-09", "multi")),
    ("isclose(a, b, abs_tol=1e-9)", "math.isclose", ("abs=1e-9|rel=1e-09", "multi")),
    ("isclose(a, b, rel_tol=0.5, abs_tol=EPS)", "math.isclose", ("abs=EPS|rel=0.5", "multi")),
    ("isclose(a, b, 1e-3, 1e-6)", "numpy.isclose", ("abs=1e-6|rel=1e-3", "multi")),
    ("isclose(a, b, atol=1e-6)", "numpy.isclose", ("abs=1e-6|rel=1e-05", "multi")),
    ("assert_allclose(a, b)", "numpy.testing.assert_allclose", ("abs=0|rel=1e-07", "multi")),
    ("assert_allclose(a, b, 0.5)", "numpy.testing.assert_allclose", ("abs=0|rel=0.5", "multi")),
    ("assert_array_almost_equal(a, b)", "numpy.testing.assert_array_almost_equal", ("decimal=6", "decimal")),
    ("assert_array_almost_equal(a, b, 3)", "numpy.testing.assert_array_almost_equal", ("decimal=3", "decimal")),
    ("assert_almost_equal(a, b, decimal=2)", "numpy.testing.assert_almost_equal", ("decimal=2", "decimal")),
    ("assert_almost_equal(a, b)", "numpy.testing.assert_almost_equal", ("decimal=7", "decimal")),
    ("assert_close(a, b, rtol=1e-5, atol=1e-8)", "torch.testing.assert_close", ("abs=1e-8|rel=1e-5", "multi")),
    # Unknown: torch's dtype default (222.Q3), torch's half pair (a runtime
    # error), and a tolerance that may come through *args or **kwargs.
    ("assert_close(a, b)", "torch.testing.assert_close", (None, None)),
    ("assert_close(a, b, rtol=1e-5)", "torch.testing.assert_close", (None, None)),
    ("assert_allclose(a, b, **tolerances)", "numpy.testing.assert_allclose", (None, None)),
    ("assert_allclose(*pair)", "numpy.testing.assert_allclose", (None, None)),
    ("assert_array_almost_equal(a, b, *rest)", "numpy.testing.assert_array_almost_equal", (None, None)),
    ("assert_allclose(a, b, 1e-7, *rest)", "numpy.testing.assert_allclose", (None, None)),
    # A keyword-only tolerance is never read from a position, where it is a
    # TypeError at run time.
    ("isclose(a, b, 1e3)", "math.isclose", ("abs=0.0|rel=1e-09", "multi")),
    ("assert_close(a, b, 1e-5, 1e-8)", "torch.testing.assert_close", (None, None)),
])
def test_a_call_records_its_tolerances_and_each_absent_default(expression, name, expected):
    assert tolerance(_call(expression), name, _seg(expression)) == expected


@pytest.mark.parametrize("expression,name,expected", [
    ("isclose(total(), 78.75)", "math.isclose", ("total()", "78.75")),
    ("assert_allclose(actual=total(), desired=78.75)", "numpy.testing.assert_allclose", ("total()", "78.75")),
    ("assert_array_almost_equal(x=total(), y=[78.75])", "numpy.testing.assert_array_almost_equal", ("total()", "[78.75]")),
    ("assert_close(total(), expected=78.75)", "torch.testing.assert_close", ("total()", "78.75")),
    ("isclose(a=total(), b=78.75)", "numpy.isclose", ("total()", "78.75")),
])
def test_the_compared_values_are_read_by_position_or_keyword(expression, name, expected):
    subject, expected_node = values(_call(expression), name)
    assert (ast.unparse(subject), ast.unparse(expected_node)) == expected


@pytest.mark.parametrize("expression,expected", [
    ("assert_allclose(*pair)", (None, None)),
    ("assert_allclose(total(), *rest)", ("total()", None)),
    ("assert_allclose(*pair, desired=78.75)", (None, "78.75")),
])
def test_a_value_a_starred_argument_may_stand_for_is_unknown(expression, expected):
    found = values(_call(expression), "numpy.testing.assert_allclose")
    assert tuple(None if node is None else ast.unparse(node) for node in found) == expected


@pytest.mark.parametrize("line,unittest_style,trivial", [
    ("assert math.isclose(0.1 + 0.2, 0.3)", False, True),
    ("assert np.isclose(0.1 + 0.2, 0.3).all()", False, True),
    ("np.testing.assert_allclose(1.0, 1.0)", False, True),
    ("self.assertTrue(math.isclose(0.1 + 0.2, 0.3))", True, True),
    ("assert math.isclose(total(), 78.75)", False, False),
    ("np.testing.assert_allclose(total(), 1.0)", False, False),
    ("self.assertTrue(math.isclose(total(), 78.75))", True, False),
])
def test_a_call_on_constants_alone_cannot_fail(line, unittest_style, trivial):
    # It never counts as compensation for a deleted oracle, in any spelling,
    # as `assertAlmostEqual(0.1 + 0.2, 0.3)` does not.
    assert _assertion(line, unittest_style=unittest_style).trivial is trivial


def test_a_lent_call_on_constants_alone_cannot_fail_either():
    helper = HEADER + "\n\ndef check():\n    assert math.isclose(0.1 + 0.2, 0.3)\n\n\ndef test_total():\n    check()\n"
    unit, = [u for u in parse_python(helper.encode(), collect_tests=True).units if u.qualname == "test_total"]
    assert [(a.inherited, a.trivial) for a in unit.side.assertions] == [(True, True)]
    fixture = HEADER + "\n\n@pytest.fixture\ndef checked():\n    assert math.isclose(0.1 + 0.2, 0.3)\n    yield 1\n"
    assert [a.trivial for a in parse_python(fixture.encode(), collect_tests=True).fixture_asserts["checked"]] == [True]


def test_a_predicate_in_an_assert_is_an_approximate_comparison_with_its_expected_value():
    a = _assertion("assert math.isclose(total(), 78.75, abs_tol=1e-9)")
    assert (a.form, a.strength, a.left, a.right_value, a.epsilon, a.epsilon_kind, a.positive) == (
        "approx", 70, "total()", "78.75", "abs=1e-9|rel=1e-09", "multi", True)
    # The literal side is the expected value, whichever side it is written on.
    a = _assertion("assert math.isclose(78.75, total())")
    assert (a.left, a.right_value) == ("total()", "78.75")


def test_an_assertion_call_written_as_a_statement_is_an_assertion():
    a = _assertion("np.testing.assert_allclose(total(), 78.75, rtol=1e-7)")
    assert (a.form, a.strength, a.left, a.right_value, a.epsilon) == (
        "approx", 70, "total()", "78.75", "abs=0|rel=1e-7")
    a = _assertion("torch.testing.assert_close(total(), 78.75)")
    assert (a.form, a.epsilon, a.epsilon_kind) == ("approx", None, None)


def test_a_negated_predicate_records_no_tolerance():
    # It passes when the values are far apart, so its tolerance orders the
    # other way: unknown, as in JavaScript.
    a = _assertion("assert not math.isclose(total(), 78.75, abs_tol=1e-9)")
    assert (a.form, a.positive, a.epsilon, a.epsilon_kind) == ("approx", False, None, None)


@pytest.mark.parametrize("line,positive,epsilon", [
    ("self.assertTrue(math.isclose(total(), 78.75, abs_tol=1e-9))", True, "abs=1e-9|rel=1e-09"),
    ("self.assertTrue(np.allclose(total(), 78.75))", True, "abs=1e-08|rel=1e-05"),
    ("self.assertFalse(math.isclose(total(), 78.75, abs_tol=1e-9))", False, None),
    ("self.assertTrue(not math.isclose(total(), 78.75, abs_tol=1e-9))", False, None),
    ("self.assertFalse(not math.isclose(total(), 78.75, abs_tol=1e-9))", True, "abs=1e-9|rel=1e-09"),
])
def test_assert_true_is_read_as_the_call_it_wraps(line, positive, epsilon):
    a = _assertion(line, unittest_style=True)
    assert (a.form, a.left, a.positive, a.epsilon) == ("approx", "total()", positive, epsilon)


def test_a_helper_that_calls_an_assertion_call_lends_it_to_the_test():
    source = (HEADER + "\n\ndef check(value):\n    np.testing.assert_allclose(value, 78.75, rtol=1e-7)\n"
              "\n\ndef test_total():\n    check(total())\n")
    parsed = parse_python(source.encode(), collect_tests=True)
    unit, = [u for u in parsed.units if u.qualname == "test_total"]
    assert [(a.form, a.epsilon, a.inherited) for a in unit.side.assertions] == [("approx", "abs=0|rel=1e-7", True)]


# --- numpy's decimal, its own conversion --------------------------------------------------

@pytest.mark.parametrize("decimal,bound", [("0", "1.5"), ("1", "0.15"), ("6", "0.0000015"), ("-1", "15")])
def test_numpy_decimal_states_its_own_bound(decimal, bound):
    value, label = _absolute_bound("decimal", decimal)
    assert value == Decimal(bound) and label == f"decimal={decimal}"


def test_numpy_decimal_is_not_unittest_places():
    # decimal=6 passes below 1.5e-6, places=6 below 5e-7: the same digits
    # are a looser bound in numpy.
    assert _mixed("decimal", "places=6", "decimal=6") == (True, "places=6", "decimal=6")
    assert _mixed("places", "decimal=6", "6") == (False, "decimal=6", "places=6")
    assert _mixed("decimal", "decimal=6", "decimal=0") is None


# --- What is reported -----------------------------------------------------------------------

LOOSENED = "TOLERANCE_LOOSENED"


@pytest.mark.parametrize("before,after,shown", [
    # I1-I4: math.isclose, the default recorded and widened, and an imported name.
    ("assert math.isclose(total(), 78.75, abs_tol=1e-9)", "assert math.isclose(total(), 78.75, abs_tol=1e3)",
     "(abs=1e-9|rel=1e-09 -> abs=1e3|rel=1e-09)"),
    ("assert math.isclose(total(), 78.75, rel_tol=1e-9)", "assert math.isclose(total(), 78.75, rel_tol=0.5)",
     "(abs=0.0|rel=1e-9 -> abs=0.0|rel=0.5)"),
    ("assert math.isclose(total(), 78.75)", "assert math.isclose(total(), 78.75, abs_tol=1e3)",
     "(abs=0.0|rel=1e-09 -> abs=1e3|rel=1e-09)"),
    # N1-N5: numpy's calls, including its own decimal.
    ("np.testing.assert_allclose(total(), 78.75, rtol=1e-7)", "np.testing.assert_allclose(total(), 78.75, rtol=0.5)",
     "(abs=0|rel=1e-7 -> abs=0|rel=0.5)"),
    ("np.testing.assert_allclose(total(), 78.75)", "np.testing.assert_allclose(total(), 78.75, atol=1e3)",
     "(abs=0|rel=1e-07 -> abs=1e3|rel=1e-07)"),
    ("assert np.isclose(total(), 78.75, atol=1e-8)", "assert np.isclose(total(), 78.75, atol=1e3)",
     "(abs=1e-8|rel=1e-05 -> abs=1e3|rel=1e-05)"),
    ("assert np.allclose([total()], [78.75], rtol=1e-5)", "assert np.allclose([total()], [78.75], rtol=0.5)",
     "(abs=1e-08|rel=1e-5 -> abs=1e-08|rel=0.5)"),
    ("np.testing.assert_array_almost_equal([total()], [78.75], decimal=6)",
     "np.testing.assert_array_almost_equal([total()], [78.75], decimal=0)", "(decimal=6 -> decimal=0)"),
    ("assert np.isclose(total(), 78.75, atol=1e-8).all()", "assert np.isclose(total(), 78.75, atol=1e3).all()",
     "(abs=1e-8|rel=1e-05 -> abs=1e3|rel=1e-05)"),
    # T1: torch with both tolerances written.
    ("torch.testing.assert_close(total(), 78.75, rtol=1e-5, atol=1e-8)",
     "torch.testing.assert_close(total(), 78.75, rtol=1e-5, atol=1.0)", "(abs=1e-8|rel=1e-5 -> abs=1.0|rel=1e-5)"),
    # X3: replaced by pytest.approx with a wider bound.
    ("assert math.isclose(total(), 78.75, abs_tol=1e-9)", "assert total() == pytest.approx(78.75, abs=1e3)",
     "(abs=1e-9|rel=1e-09 -> abs=1e3)"),
])
def test_a_widened_tolerance_call_is_reported(before, after, shown):
    verdict, findings = _outcome(_source(before), _source(after))
    assert verdict == "block"
    assert [(rule, message.endswith(shown)) for rule, _severity, message in findings] == [(LOOSENED, True)]


def test_an_imported_isclose_is_read():
    verdict, findings = _outcome(
        _source("assert isclose(total(), 78.75, abs_tol=1e-9)", "from math import isclose"),
        _source("assert isclose(total(), 78.75, abs_tol=1e3)", "from math import isclose"))
    assert [rule for rule, _s, _m in findings] == [LOOSENED]


def test_assert_true_around_isclose_reports_the_tolerance_not_the_subjects_input():
    # I5 blocked as SUBJECT_INPUT_CHANGED, calling the tolerance the subject's input (222.Q2).
    verdict, findings = _outcome(
        _unittest_source("self.assertTrue(math.isclose(total(), 78.75, abs_tol=1e-9))"),
        _unittest_source("self.assertTrue(math.isclose(total(), 78.75, abs_tol=1e3))"))
    assert [rule for rule, _s, _m in findings] == [LOOSENED]


@pytest.mark.parametrize("before,after,rule,shown", [
    # N6, T2: the assertion call is deleted.
    ("np.testing.assert_allclose(total(), 78.75, rtol=1e-7)", "total()", "ASSERT_REMOVED", "(strength APPROX)"),
    ("torch.testing.assert_close(total(), 78.75)", "total()", "ASSERT_REMOVED", "(strength APPROX)"),
    # X1: the expected value rewritten inside isclose (222.Q1).
    ("assert math.isclose(total(), 78.75, abs_tol=1e-9)", "assert math.isclose(total(), 75, abs_tol=1e-9)",
     "EXPECTED_VALUE_CHANGED", "78.75 -> 75"),
    # X2: the comparison dropped.
    ("assert math.isclose(total(), 78.75, abs_tol=1e-9)", "assert total()", "ASSERT_WEAKENED", "APPROX(70) -> TRUTHY(20)"),
    # The predicate negated.
    ("assert math.isclose(total(), 78.75, abs_tol=1e-9)", "assert not math.isclose(total(), 78.75, abs_tol=1e-9)",
     "ASSERT_WEAKENED", "polarity inverted"),
    # 222.Q3: an explicit torch pair dropped for the dtype default.
    ("torch.testing.assert_close(total(), 78.75, rtol=1e-5, atol=1e-8)", "torch.testing.assert_close(total(), 78.75)",
     "ASSERT_WEAKENED", "(tolerance abs=1e-8|rel=1e-5 -> a tolerance it cannot read)"),
])
def test_other_weakenings_of_a_tolerance_call_are_reported(before, after, rule, shown):
    verdict, findings = _outcome(_source(before), _source(after))
    assert verdict == "block"
    assert [(r, shown in message) for r, _severity, message in findings] == [(rule, True)]


@pytest.mark.parametrize("before,after", [
    ("assert math.isclose(total(), 78.75, abs_tol=1e3)", "assert math.isclose(total(), 78.75, abs_tol=1e-9)"),
    ("np.testing.assert_array_almost_equal([total()], [78.75], decimal=0)",
     "np.testing.assert_array_almost_equal([total()], [78.75], decimal=6)"),
    ("assert math.isclose(total(), 78.75, abs_tol=1e-9)", "assert total() == pytest.approx(78.75, abs=1e-9)"),
    ("assert not math.isclose(total(), 78.75, abs_tol=1e3)", "assert not math.isclose(total(), 78.75, abs_tol=1e-9)"),
    ("torch.testing.assert_close(total(), 78.75)", "torch.testing.assert_close(total(), 78.75)\nassert total() > 0"),
])
def test_a_tightened_equal_or_unknown_tolerance_is_not_reported(before, after):
    verdict, findings = _outcome(_source(before), _source(after))
    assert verdict == "pass", findings


# --- The tolerance an unreadable call loses --------------------------------------------------

def test_a_lost_bare_tolerance_is_named_in_its_own_kind():
    old = Assertion(id="a0", form="approx", strength=70, text="", span=(0, 1), epsilon="0.01", epsilon_kind="delta")
    new = Assertion(id="a0", form="approx", strength=70, text="", span=(0, 1))
    assert _tolerance_lost("tests/test_x.py", old, new) == "delta=0.01"
    js_old = Assertion(id="a0", form="approx", strength=70, text="", span=(0, 1), epsilon="2", epsilon_kind="places")
    assert _tolerance_lost("src/x.test.ts", js_old, new) == "places=2"

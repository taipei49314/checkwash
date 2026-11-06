"""D-201: three holes that design 2 for 0.12 found beside D-191's residual (its section 7).

1. An equality with `unittest.mock.ANY` as a whole operand can never fail, so it
   is TAUTOLOGY: rewriting an expected value into it is ASSERT_WEAKENED, which
   takes neither D9's DEPENDENCY_DRIFT nor, in Python, repair evidence (D-199).
2. D6 COMPAT_GATE: a single test's skip condition must be provably false in some
   environment of the matrix, which now holds CPython and PyPy. A suite-level
   collection control keeps the old reading.
3. An order-sensitive unittest equality rewritten as `assertCountEqual` on the
   same subject is SUBJECT_NORMALIZED, as `sorted()` around the subject is.

The fixtures `mock_any_*`, `compat_gate_unknown_*`, `compat_gate_pypy_neg` and
`assert_count_equal_*` run each end to end.
"""

import ast

import pytest

from checkwash.compat import _ENV_MATRIX, _discriminates
from checkwash.detectors.subject_normalized import _order_dropped
from checkwash.frontends.python.frontend import _Offsets, _classify_assert, _classify_unittest_call
from checkwash.ir import strength as S
from checkwash.ir.model import Assertion


def _classify(expr: str):
    src = f"assert {expr}"
    return _classify_assert(ast.parse(src).body[0], _Offsets(src))


def _unittest(call: str):
    src = f"self.{call}"
    return _classify_unittest_call(ast.parse(src).body[0].value, _Offsets(src))


@pytest.mark.parametrize("expr", [
    "total() == ANY",
    "ANY == total()",
    "total() == mock.ANY",
    "total() == unittest.mock.ANY",
    "total() == mocker.ANY",
])
def test_an_equality_with_any_is_a_tautology(expr):
    c = _classify(expr)
    assert (c.form, c.strength) == ("tautology", S.TAUTOLOGY)


@pytest.mark.parametrize("expr, form, strength, positive", [
    # `!=` with ANY never holds: no weakening, so the old reading stays.
    ("total() != ANY", "compare_eq", S.EXACT_VALUE, False),
    # One entry of a container: its other entries are still checked. A
    # display holding a name reads as EXACT_VALUE, as it did before D-201.
    ('order() == {"id": ANY, "total": 6}', "compare_eq", S.EXACT_VALUE, True),
    # Another name is not mock's ANY.
    ("total() == ANYTHING", "compare_eq", S.EXACT_VALUE, True),
    ("total() == any_value", "compare_eq", S.EXACT_VALUE, True),
])
def test_other_comparisons_with_any_keep_their_reading(expr, form, strength, positive):
    c = _classify(expr)
    assert (c.form, c.strength, c.positive) == (form, strength, positive)


@pytest.mark.parametrize("call", [
    "assertEqual(total(), ANY)",
    "assertEqual(ANY, total())",
    "assertEqual(total(), mock.ANY)",
])
def test_assert_equal_with_any_is_a_tautology(call):
    c = _unittest(call)
    assert (c.form, c.strength) == ("tautology", S.TAUTOLOGY)


@pytest.mark.parametrize("call", [
    # Never holds, as `!=` does not.
    "assertNotEqual(total(), ANY)",
    # The typed variants check the operand's type first, so they fail.
    "assertListEqual(items(), ANY)",
    "assertCountEqual(items(), ANY)",
])
def test_other_unittest_calls_with_any_keep_their_reading(call):
    c = _unittest(call)
    assert c.form == "compare_eq" and c.strength != S.TAUTOLOGY


def _parts(condition: str):
    return [(ast.parse(condition, mode="eval").body, False)]


@pytest.mark.parametrize("condition, before, after", [
    # The section 7 hole: the unknown call stood in for the false case.
    ("sys.version_info >= (3, 0) and bool(sys.modules)", True, False),
    ("sys.platform == 'win32' or bool(sys.modules)", True, False),
    # Provably false off Windows, whatever the call returns.
    ("sys.platform == 'win32' and bool(sys.modules)", True, True),
    ("sys.platform == 'darwin' and sys.version_info >= (3, 13) and not sys._is_gil_enabled()", True, True),
    ("sys.version_info < (3, 12)", True, True),
    # The interpreter, which the matrix now holds.
    ("platform.python_implementation() == 'PyPy'", True, True),
    ("platform.python_implementation() != 'PyPy'", True, True),
    ("sys.implementation.name == 'pypy'", True, True),
    ("platform.python_implementation() in ('CPython', 'PyPy')", False, False),
    # pytest 4445685285 (D-088's sample) adds the oldest spelling of "on PyPy"
    # to a version gate, and pytest's PYPY constant is the hasattr one.
    ("sys.version_info < (2, 5) or '__pypy__' in sys.builtin_module_names", True, True),
    ("hasattr(sys, 'pypy_version_info')", True, True),
    ("'__pypy__' not in sys.builtin_module_names", True, True),
    # Any other question about the builtin modules is unknown.
    ("sys.platform == 'win32' or '_ctypes' in sys.builtin_module_names", True, False),
    ("sys.platform == 'win32' or sys.builtin_module_names == ()", True, False),
    # Always true, read as before.
    ("sys.version_info >= (3, 8)", False, False),
    ("True or sys.platform == 'win32'", False, False),
])
def test_a_single_tests_gate_must_provably_run_somewhere(condition, before, after):
    assert _discriminates(_parts(condition), None) is before
    assert _discriminates(_parts(condition), None, runs_somewhere=True) is after


def test_a_suite_level_guard_keeps_the_old_reading():
    """An optional-dependency guard is unknown everywhere, and it is the whole
    justification of a suite-level collection control (D-028)."""
    parts = _parts("find_spec('redis') is None")
    assert _discriminates(parts, None) is True
    assert _discriminates(parts, None, runs_somewhere=True) is False


def test_the_matrix_holds_cpython_and_pypy_in_every_environment():
    assert len(_ENV_MATRIX) == 24
    assert {env["implementation"] for env in _ENV_MATRIX} == {"CPython", "PyPy"}
    others = {(env["version_info"], env["platform"]) for env in _ENV_MATRIX}
    assert len(others) == 12
    for key in others:
        assert {env["implementation"] for env in _ENV_MATRIX
                if (env["version_info"], env["platform"]) == key} == {"CPython", "PyPy"}


def _assertion(text: str, left: str = "items()", positive: bool = True) -> Assertion:
    return Assertion(id=text, form="compare_eq", strength=S.EXACT_VALUE, text=text, span=(0, len(text)),
                     left=left, positive=positive)


@pytest.mark.parametrize("before, after", [
    ("assertEqual", "assertCountEqual"),
    ("assertListEqual", "assertCountEqual"),
    ("assertTupleEqual", "assertCountEqual"),
    ("assertSequenceEqual", "assertCountEqual"),
    ("assertEqual", "assertItemsEqual"),
])
def test_an_order_sensitive_equality_rewritten_as_a_multiset_one_drops_order(before, after):
    b = _assertion(f"self.{before}(items(), [1, 2, 3])")
    a = _assertion(f"self.{after}(items(), [1, 2, 3])")
    assert _order_dropped("tests/test_items.py", b, a) == (before, after)


@pytest.mark.parametrize("path, b, a", [
    # The other way round starts checking order.
    ("tests/test_items.py", _assertion("self.assertCountEqual(items(), [1, 2, 3])"),
     _assertion("self.assertEqual(items(), [1, 2, 3])")),
    # A different subject is another rule's question.
    ("tests/test_items.py", _assertion("self.assertEqual(items(), [1, 2, 3])"),
     _assertion("self.assertCountEqual(other(), [1, 2, 3])", left="other()")),
    # A negated assertion is not an equality being relaxed.
    ("tests/test_items.py", _assertion("self.assertEqual(items(), [1, 2, 3])"),
     _assertion("self.assertCountEqual(items(), [1, 2, 3])", positive=False)),
    # Only Python's unittest has these names.
    ("tests/items.test.js", _assertion("self.assertEqual(items(), [1, 2, 3])"),
     _assertion("self.assertCountEqual(items(), [1, 2, 3])")),
    # A bare assert names no method.
    ("tests/test_items.py", _assertion("assert items() == [1, 2, 3]"),
     _assertion("self.assertCountEqual(items(), [1, 2, 3])")),
])
def test_other_pairs_drop_nothing(path, b, a):
    assert _order_dropped(path, b, a) is None

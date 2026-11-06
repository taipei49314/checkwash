"""D-201: three holes that design 2 for 0.12 found beside D-191's residual (its section 7).

1. An equality with `unittest.mock.ANY` as a whole operand passes whatever the
   other side is, so it is TAUTOLOGY: rewriting an expected value into it is
   ASSERT_WEAKENED, which takes neither D9's DEPENDENCY_DRIFT nor, in Python,
   repair evidence (D-199). `ANY` is read through the file's imports.
2. D6 COMPAT_GATE: a single test's skip condition must be provably false in some
   environment of the matrix, and every interpreter/OS gate on the unit
   together must leave one. The matrix holds CPython, and PyPy at 3.11, each
   platform's machines and five-tuple versions. A suite-level collection
   control, and liveness, keep the old reading.
3. An order-sensitive unittest equality rewritten as `assertCountEqual` on the
   same operands is SUBJECT_NORMALIZED, as `sorted()` around the subject is.

The fixtures `mock_any_*`, `project_any_constant_is_not_mock_pos`,
`compat_gate_*` named in D-201, `standin_behind_unknown_gate_pos` and
`assert_count_equal_*` run each end to end.
"""

import ast

import pytest

from checkwash.compat import MAYBE, _ENV_MATRIX, _discriminates, _eval_condition, guard_always_skips, unit_is_live
from checkwash.detectors.subject_normalized import _order_dropped
from checkwash.frontends.python.frontend import _Offsets, _classify_assert, _classify_unittest_call, parse_python
from checkwash.ir import strength as S
from checkwash.ir.model import Assertion

IMPORTS = "from unittest.mock import ANY\nfrom unittest import mock\nimport unittest.mock\n"


def _module(imports: str, line: str):
    src = imports + line + "\n"
    tree = ast.parse(src)
    off = _Offsets(src)
    off.tree = tree
    return tree.body[-1], off


def _classify(expr: str, imports: str = IMPORTS):
    node, off = _module(imports, f"assert {expr}")
    return _classify_assert(node, off)


def _unittest(call: str, imports: str = IMPORTS):
    node, off = _module(imports, f"self.{call}")
    return _classify_unittest_call(node.value, off)


# --- 1. ANY -------------------------------------------------------------------


@pytest.mark.parametrize("expr, imports", [
    ("total() == ANY", IMPORTS),
    ("ANY == total()", IMPORTS),
    ("total() == mock.ANY", IMPORTS),
    ("total() == unittest.mock.ANY", IMPORTS),
    ("total() == mocker.ANY", ""),
    ("total() == anything", "from unittest.mock import ANY as anything\n"),
    ("total() == um.ANY", "from unittest import mock as um\n"),
    ("total() == m.ANY", "import mock as m\n"),
    ("total() == ANY", "from mock import ANY\n"),
    ("total() == ANY", "from unittest.mock import *\n"),
    ("len(items()) == ANY", IMPORTS),
    # Each link has ANY on one side.
    ("total() == ANY == 6", IMPORTS),
])
def test_an_equality_with_any_is_a_tautology(expr, imports):
    c = _classify(expr, imports)
    assert (c.form, c.strength) == ("tautology", S.TAUTOLOGY)


@pytest.mark.parametrize("expr, imports, form, strength, positive", [
    # `!=` with ANY never holds: no weakening, so the old reading stays.
    ("total() != ANY", IMPORTS, "compare_eq", S.EXACT_VALUE, False),
    # One entry of a container: its other entries are still checked. A
    # display holding a name reads as EXACT_VALUE, as it did before D-201.
    ('order() == {"id": ANY, "total": 6}', IMPORTS, "compare_eq", S.EXACT_VALUE, True),
    # Another name is not mock's ANY, nor is a project's own constant.
    ("total() == ANYTHING", IMPORTS, "compare_eq", S.EXACT_VALUE, True),
    ("total() == ANY", "from app import ANY\n", "compare_eq", S.EXACT_VALUE, True),
    ("total() == ANY", "", "compare_eq", S.EXACT_VALUE, True),
    ("total() == app.ANY", IMPORTS, "compare_eq", S.EXACT_VALUE, True),
    # A link without ANY still checks something.
    ("ANY == total() == 6", IMPORTS, "compare_eq", S.EXACT_VALUE, True),
])
def test_other_comparisons_with_any_keep_their_reading(expr, imports, form, strength, positive):
    c = _classify(expr, imports)
    assert (c.form, c.strength, c.positive) == (form, strength, positive)


@pytest.mark.parametrize("expr", [
    "items() == [ANY, ANY, ANY]",
    "(ANY, ANY) == pair()",
    'record() == {"total": ANY, "count": ANY}',
])
def test_a_display_of_nothing_but_any_checks_only_its_shape(expr):
    c = _classify(expr)
    assert (c.form, c.strength) == ("type_shape", S.TYPE_SHAPE)


def test_a_set_of_any_is_not_a_shape():
    """A set's entries are hashed, not compared, so `{ANY}` matches no set but itself."""
    c = _classify("tags() == {ANY, ANY}")
    assert c.form == "compare_eq"


@pytest.mark.parametrize("call", [
    "assertEqual(total(), ANY)",
    "assertEqual(ANY, total())",
    "assertEqual(total(), mock.ANY)",
    "assertEqual(len(items()), ANY)",
    "assertEqual(ANY, len(items()))",
    # Returns as soon as the two compare equal, before any tolerance.
    "assertAlmostEqual(total(), ANY)",
    "assertAlmostEqual(total(), ANY, places=2)",
])
def test_assert_equal_with_any_is_a_tautology(call):
    c = _unittest(call)
    assert (c.form, c.strength) == ("tautology", S.TAUTOLOGY)


@pytest.mark.parametrize("call", [
    "assertEqual(items(), [ANY, ANY, ANY])",
    "assertListEqual(items(), [ANY, ANY])",
    'assertDictEqual(record(), {"total": ANY})',
])
def test_assert_equal_with_a_display_of_any_checks_only_its_shape(call):
    c = _unittest(call)
    assert (c.form, c.strength) == ("type_shape", S.TYPE_SHAPE)


@pytest.mark.parametrize("call", [
    # Never holds, as `!=` does not.
    "assertNotEqual(total(), ANY)",
    "assertNotAlmostEqual(total(), ANY)",
    # The typed variants check the operand's type first, so they fail.
    "assertListEqual(items(), ANY)",
    "assertCountEqual(items(), ANY)",
    "assertCountEqual(items(), [ANY])",
])
def test_other_unittest_calls_with_any_keep_their_reading(call):
    c = _unittest(call)
    assert c.strength not in (S.TAUTOLOGY, S.TYPE_SHAPE)


def test_a_project_constant_named_any_is_not_read_in_unittest_either():
    c = _unittest("assertEqual(mode(), ANY)", "from app import ANY\n")
    assert c.form == "compare_eq" and c.strength == S.EXACT_VALUE


# --- 2. D6 ----------------------------------------------------------------------


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
    # The interpreter, which the matrix holds.
    ("platform.python_implementation() == 'PyPy'", True, True),
    ("platform.python_implementation() != 'PyPy'", True, True),
    ("sys.implementation.name == 'pypy'", True, True),
    ("platform.python_implementation() in ('CPython', 'PyPy')", False, False),
    # pytest 4445685285 (D-088's sample) adds the oldest spelling of "on PyPy"
    # to a version gate, and pytest's PYPY constant is the hasattr one.
    ("sys.version_info < (2, 5) or '__pypy__' in sys.builtin_module_names", True, True),
    ("hasattr(sys, 'pypy_version_info')", True, True),
    ("'__pypy__' not in sys.builtin_module_names", True, True),
    # An interpreter or a module the matrix does not hold stays unknown, so the
    # old reading does not change.
    ("platform.python_implementation() != 'IronPython'", True, False),
    ("sys.implementation.name != 'graalpy'", True, False),
    ("sys.platform == 'win32' or '_ctypes' in sys.builtin_module_names", True, False),
    ("sys.platform == 'win32' or sys.builtin_module_names == ()", True, False),
    ("sys.platform == 'win32' or sys.builtin_module_names != ()", True, False),
    ("sys.platform == 'win32' or hasattr(sys, 'gettotalrefcount')", True, False),
    # The machine each platform reports.
    ("platform.machine() == 'arm64'", True, True),
    ("platform.machine().lower() in ('arm64', 'aarch64')", True, True),
    ("platform.machine().startswith('arm')", True, True),
    ("platform.machine() != 'Plan9'", True, False),
    ("platform.machine().startswith('riscv')", True, False),
    ("platform.architecture()[0] == '32bit'", True, True),
    ("platform.architecture()[0] == '16bit'", True, False),
    # Versions as five-tuples and as strings.
    ("sys.version_info > (3, 11, 0)", False, False),
    ("sys.version_info >= (3, 11, 1)", True, True),
    ("platform.python_version_tuple() < ('3', '12')", True, True),
    ("platform.python_version() == '3.11.0'", True, True),
    ("sys.version_info.micro < 2", True, False),
    # List and set displays, as tuples.
    ("sys.platform not in ['linux', 'darwin']", True, True),
    ("sys.platform in {'win32', 'cygwin'}", True, True),
    ("sys.platform in ['win32', HELPER]", True, False),
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


@pytest.mark.parametrize("condition", [
    "platform.python_implementation() == 'PyPy'",
    "'PyPy' == platform.python_implementation()",
    "sys.implementation.name == 'pypy'",
    "'__pypy__' in sys.builtin_module_names",
    "hasattr(sys, 'pypy_version_info')",
])
def test_each_pypy_spelling_is_true_exactly_on_pypy(condition):
    node = ast.parse(condition, mode="eval").body
    for env in _ENV_MATRIX:
        assert _eval_condition(node, env) is (env["implementation"] == "PyPy"), (condition, env)


def test_the_machine_is_read_per_platform():
    node = ast.parse("platform.machine() == 'arm64'", mode="eval").body
    for env in _ENV_MATRIX:
        assert _eval_condition(node, env) is (env["machine"] == "arm64"), env
    unknown = ast.parse("platform.machine() == 'riscv64'", mode="eval").body
    assert all(_eval_condition(unknown, env) is MAYBE for env in _ENV_MATRIX)


def test_the_matrix():
    """CPython 3.11 to 3.14 and PyPy 3.11, on each platform's two machines."""
    assert len(_ENV_MATRIX) == 30
    pairs = {(env["implementation"], env["version_info"][:2]) for env in _ENV_MATRIX}
    assert pairs == {("CPython", (3, m)) for m in (11, 12, 13, 14)} | {("PyPy", (3, 11))}
    assert all(len(env["version_info"]) == 5 for env in _ENV_MATRIX)
    machines = {(env["platform"], env["machine"]) for env in _ENV_MATRIX}
    assert machines == {("win32", "AMD64"), ("win32", "ARM64"), ("linux", "x86_64"), ("linux", "aarch64"),
                        ("darwin", "x86_64"), ("darwin", "arm64")}


def test_a_guard_naming_an_interpreter_the_matrix_lacks_is_not_always_true():
    """The old reading, which judges a suite control's guard, does not change."""
    assert guard_always_skips("platform.python_implementation() != 'IronPython'", None) is False
    assert guard_always_skips("sys.implementation.name != 'graalpy'", None) is False


def test_liveness_keeps_the_old_reading():
    """A moved test, or one a stand-in may replace, is live unless its gate is
    true whatever its unknown part is: reading it as dead would hide a
    stand-in and refuse an honest move (D-201 review)."""
    src = ("import sys\n\nimport pytest\n\nHAS_X = object()\n\n\n"
           "@pytest.mark.skipif(sys.platform == 'win32' or not HAS_X, reason='x')\n"
           "def test_total():\n    assert total() == 3\n")
    parsed = parse_python(src.encode("utf-8"), collect_tests=True)
    unit = next(u for u in parsed.units if u.qualname == "test_total")
    assert unit_is_live(unit.side, parsed.constants) is True


# --- 3. assertCountEqual ----------------------------------------------------------


def _assertion(text: str, left: str = "items()", positive: bool = True) -> Assertion:
    return Assertion(id=text, form="compare_eq", strength=S.EXACT_VALUE, text=text, span=(0, len(text)),
                     left=left, positive=positive)


@pytest.mark.parametrize("before, after", [
    ("assertEqual", "assertCountEqual"),
    ("assertListEqual", "assertCountEqual"),
    ("assertTupleEqual", "assertCountEqual"),
    ("assertSequenceEqual", "assertCountEqual"),
])
def test_an_order_sensitive_equality_rewritten_as_a_multiset_one_drops_order(before, after):
    b = _assertion(f"self.{before}(items(), [1, 2, 3])")
    a = _assertion(f"self.{after}(items(), [1, 2, 3])")
    assert _order_dropped("tests/test_items.py", b, a, {}, {}) == (before, after, False)


@pytest.mark.parametrize("b, a, before_bindings, after_bindings", [
    # The operands swapped.
    ("self.assertEqual(items(), [1, 2, 3])", "self.assertCountEqual([1, 2, 3], items())", {}, {}),
    # list() is the same operand to assertCountEqual.
    ("self.assertEqual(list(items()), [1, 2, 3])", "self.assertCountEqual(items(), [1, 2, 3])", {}, {}),
    # A hoisted subject or expected value, through the unit's bindings.
    ("self.assertEqual(items(), [1, 2, 3])", "self.assertCountEqual(result, [1, 2, 3])", {}, {"result": "items()"}),
    ("self.assertEqual(items(), [1, 2, 3])", "self.assertCountEqual(items(), expected)", {}, {"expected": "[1, 2, 3]"}),
    # By keyword.
    ("self.assertEqual(first=items(), second=[1, 2, 3])", "self.assertCountEqual(items(), [1, 2, 3])", {}, {}),
])
def test_the_same_operands_however_spelled(b, a, before_bindings, after_bindings):
    result = _order_dropped("tests/test_items.py", _assertion(b), _assertion(a), before_bindings, after_bindings)
    assert result is not None and result[2] is False


def test_a_dict_operand_loses_its_values():
    b = _assertion('self.assertEqual(record(), {"total": 6})', left="record()")
    a = _assertion('self.assertCountEqual(record(), {"total": 6})', left="record()")
    assert _order_dropped("tests/test_record.py", b, a, {}, {}) == ("assertEqual", "assertCountEqual", True)


@pytest.mark.parametrize("path, b, a", [
    # The other way round starts checking order.
    ("tests/test_items.py", _assertion("self.assertCountEqual(items(), [1, 2, 3])"),
     _assertion("self.assertEqual(items(), [1, 2, 3])")),
    # A different subject or expected value is another rule's question.
    ("tests/test_items.py", _assertion("self.assertEqual(items(), [1, 2, 3])"),
     _assertion("self.assertCountEqual(other(), [1, 2, 3])", left="other()")),
    ("tests/test_items.py", _assertion("self.assertEqual(items(), EXPECTED_A)"),
     _assertion("self.assertCountEqual(items(), EXPECTED_B)")),
    # A set never had an order.
    ("tests/test_items.py", _assertion("self.assertEqual(set(items()), {1, 2, 3})", left="set(items())"),
     _assertion("self.assertCountEqual(set(items()), {1, 2, 3})", left="set(items())")),
    # A negated assertion is not an equality being relaxed.
    ("tests/test_items.py", _assertion("self.assertEqual(items(), [1, 2, 3])"),
     _assertion("self.assertCountEqual(items(), [1, 2, 3])", positive=False)),
    # Only Python's unittest has these names.
    ("tests/items.test.js", _assertion("self.assertEqual(items(), [1, 2, 3])"),
     _assertion("self.assertCountEqual(items(), [1, 2, 3])")),
    # A bare assert names no method, and Python 2's assertItemsEqual is not read.
    ("tests/test_items.py", _assertion("assert items() == [1, 2, 3]"),
     _assertion("self.assertCountEqual(items(), [1, 2, 3])")),
    ("tests/test_items.py", _assertion("self.assertEqual(items(), [1, 2, 3])"),
     _assertion("self.assertItemsEqual(items(), [1, 2, 3])")),
])
def test_other_pairs_drop_nothing(path, b, a):
    assert _order_dropped(path, b, a, {}, {}) is None

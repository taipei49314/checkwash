"""D-201: three holes that design 2 for 0.12 found beside D-191's residual (its section 7).

1. An equality with `unittest.mock.ANY` as a whole operand passes whatever the
   other side is, so it is TAUTOLOGY: rewriting an expected value into it is
   ASSERT_WEAKENED, which takes neither D9's DEPENDENCY_DRIFT nor, in Python,
   repair evidence (D-199). `ANY` is read through the file's imports.
2. D6 COMPAT_GATE: a single test's skip condition must be provably false in some
   environment of the matrix, and the gates a change adds must leave one
   together with the gates the test had. The matrix holds CPython, and PyPy
   at 3.11, and each platform's machines; the micro release is unknown. A
   suite-level collection control, and liveness, keep the old reading.
3. An order-sensitive unittest equality rewritten as `assertCountEqual` on the
   same subject is SUBJECT_NORMALIZED, as `sorted()` around the subject is.

The fixtures `mock_any_*`, `project_any_constant_is_not_mock_pos`,
`compat_gate_*` named in D-201, `standin_behind_unknown_gate_pos` and
`assert_count_equal_*` run each end to end.
"""

import ast

import pytest

from checkwash.compat import (
    MAYBE,
    _ENV_MATRIX,
    _discriminates,
    _eval_condition,
    _Release,
    _VersionString,
    guard_always_skips,
    unit_is_live,
)
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
    # Nested, repeated, generated, and built from keys (D-201 review).
    'record() == {"a": {"b": ANY}}',
    "matrix() == [[ANY, ANY], [ANY]]",
    "items() == [ANY] * 3",
    "items() == 3 * (ANY,)",
    "items() == [ANY for _ in range(3)]",
    "record() == {k: ANY for k in KEYS}",
    "record() == dict.fromkeys(KEYS, ANY)",
    "record() == dict(total=ANY, tax=ANY)",
    "total() == pytest.approx([ANY, ANY])",
    "not (items() != [ANY, ANY])",
])
def test_a_display_of_nothing_but_any_checks_only_its_shape(expr):
    c = _classify(expr)
    assert (c.form, c.strength) == ("type_shape", S.TYPE_SHAPE)


def test_a_display_of_any_keeps_the_shape_it_checks_as_its_expectation():
    """`[ANY, ANY, ANY]` -> `[ANY]` changes the length checked: main saw that
    as an expectation changed, and the shape reading must not hide it."""
    assert _classify("items() == [ANY, ANY, ANY]").unevaluated_expected == "[ANY, ANY, ANY]"
    assert _classify('{"total": ANY} == record()').unevaluated_expected == "{'total': ANY}"
    assert _unittest("assertEqual(items(), [ANY])").unevaluated_expected == "[ANY]"


@pytest.mark.parametrize("expr", [
    # No position is checked: ANY on one side, or one literal on both.
    "(total(), 0) == (ANY, 0)",
    "(total(), ANY) == (ANY, 6)",
    "[total(), items()] == [ANY, [ANY]]",
    # Membership in a display holding ANY.
    "total() in [ANY]",
    "total() in (6, ANY)",
    # `not (x != ANY)` is `x == ANY`, and approx hands ANY to `==`.
    "not (total() != ANY)",
    "total() == pytest.approx(ANY)",
    "total() == approx(ANY, rel=0.1)",
    # The length or the keys taken from the subject itself (D-201 round 3).
    "items() == [ANY] * len(items())",
    "len(items()) * [ANY] == items()",
    "record() == dict.fromkeys(record(), ANY)",
])
def test_other_spellings_that_hold_for_every_value(expr):
    c = _classify(expr)
    assert (c.form, c.strength) == ("tautology", S.TAUTOLOGY)


@pytest.mark.parametrize("expr, form, strength", [
    # `ANY in items()` says only that items() is not empty.
    ("ANY in items()", "truthy", S.TRUTHY),
    # A checked position is still checked.
    ("(total(), 0) == (ANY, 1)", "compare_eq", S.EXACT_VALUE),
    ("(total(), items()) == (ANY, [1, 2])", "compare_eq", S.EXACT_VALUE),
    # A list and a tuple never compare equal.
    ("(total(), 0) == [ANY, 0]", "compare_eq", S.EXACT_VALUE),
    ("ANY not in items()", "membership", S.PATTERN),
    # ANY cannot be hashed, so `x in {ANY}` raises rather than holding.
    ("total() in {ANY}", "membership", S.PATTERN),
    # Another subject's length is a length still checked.
    ("items() == [ANY] * len(other())", "type_shape", S.TYPE_SHAPE),
])
def test_spellings_that_still_check_something(expr, form, strength):
    c = _classify(expr)
    assert (c.form, c.strength) == (form, strength)


def test_any_on_the_left_is_the_expectation():
    """As a literal on the left is: the subject stays the subject (D-201 review)."""
    assert _classify("ANY == total()").left == "total()"
    assert _classify("[ANY, ANY] == items()").left == "items()"
    assert _unittest("assertEqual(ANY, total())").left == "total()"


def _classify_in_function(src: str):
    """Classify the one assert inside `def test_it()` of a module, as the frontend sees it."""
    tree = ast.parse(src)
    off = _Offsets(src)
    off.tree = tree
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "test_it")
    node = next(n for n in ast.walk(function) if isinstance(n, ast.Assert))
    return _classify_assert(node, off)


@pytest.mark.parametrize("imports", [
    # Rebound at module level by an assignment or a loop, after the import.
    "from unittest.mock import ANY\nANY = 6\n",
    "from unittest.mock import ANY\nfor ANY in range(3):\n    pass\n",
])
def test_a_name_the_module_also_binds_is_not_read_as_mock_any(imports):
    c = _classify("total() == ANY", imports)
    assert (c.form, c.strength) == ("compare_eq", S.EXACT_VALUE)


@pytest.mark.parametrize("src, tautology", [
    # Another function's parameter or loop variable changes nothing here (D-201 round 3).
    ("from unittest.mock import ANY\ndef helper(ANY=None):\n    return ANY\n"
     "def test_it():\n    assert total() == ANY\n", True),
    ("from unittest.mock import ANY\ndef test_other():\n    for ANY in (1, 2):\n        pass\n"
     "def test_it():\n    assert total() == ANY\n", True),
    # This function's own binding does.
    ("from unittest.mock import ANY\ndef test_it():\n    ANY = 6\n    assert total() == ANY\n", False),
    ("from unittest.mock import ANY\ndef test_it(ANY):\n    assert total() == ANY\n", False),
    # A local import, and a parameter or alias whose value is mock's ANY.
    ("def test_it():\n    from unittest.mock import ANY\n    assert total() == ANY\n", True),
    ("from unittest import mock\ndef test_it(ANY=mock.ANY):\n    assert total() == ANY\n", True),
    ("from unittest.mock import ANY\nANY = ANY\ndef test_it():\n    assert total() == ANY\n", True),
    ("from unittest import mock\nWILD = mock.ANY\ndef test_it():\n    assert total() == WILD\n", True),
    # A project's ANY at module level, beside mock's imported inside another function.
    ("from app import ANY\ndef helper():\n    from unittest.mock import ANY\n    return ANY\n"
     "def test_it():\n    assert total() == ANY\n", False),
])
def test_a_bare_any_is_read_through_pythons_scopes(src, tautology):
    c = _classify_in_function(src)
    assert (c.form == "tautology") is tautology, (c.form, c.strength)


def test_a_local_called_mock_does_not_hide_the_module():
    """`with mock.patch(...) as mock:` elsewhere in the file leaves `mock.ANY` mock's."""
    imports = "from unittest import mock\ndef helper():\n    with mock.patch('x') as mock:\n        pass\n"
    c = _classify("total() == mock.ANY", imports)
    assert (c.form, c.strength) == ("tautology", S.TAUTOLOGY)


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
    'assertEqual(record(), {"a": {"b": ANY}})',
    "assertEqual(items(), [ANY] * 3)",
    # Each entry pairs with one that compares equal: only the length is left.
    "assertCountEqual(items(), [ANY])",
    "assertCountEqual(items(), [ANY, ANY, ANY])",
])
def test_assert_equal_with_a_display_of_any_checks_only_its_shape(call):
    c = _unittest(call)
    assert (c.form, c.strength) == ("type_shape", S.TYPE_SHAPE)


@pytest.mark.parametrize("call, form, strength", [
    ("assertEqual((total(), 0), (ANY, 0))", "tautology", S.TAUTOLOGY),
    ("assertTupleEqual((total(), ANY), (ANY, 6))", "tautology", S.TAUTOLOGY),
    ("assertIn(total(), [ANY])", "tautology", S.TAUTOLOGY),
    ("assertIn(ANY, items())", "truthy", S.TRUTHY),
])
def test_other_unittest_spellings_of_any(call, form, strength):
    c = _unittest(call)
    assert (c.form, c.strength) == (form, strength)


@pytest.mark.parametrize("call", [
    # Never holds, as `!=` does not.
    "assertNotEqual(total(), ANY)",
    "assertNotAlmostEqual(total(), ANY)",
    # The typed variants check the operand's type first, so they fail.
    "assertListEqual(items(), ANY)",
    # assertCountEqual iterates its operands, and ANY is not iterable.
    "assertCountEqual(items(), ANY)",
    "assertNotIn(total(), [ANY])",
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
    # An interpreter the matrix does not hold stays unknown in the old reading,
    # which does not change; the question whether the test runs somewhere
    # reads each environment's own interpreter, so these are true everywhere.
    ("platform.python_implementation() != 'IronPython'", True, False),
    ("sys.implementation.name != 'graalpy'", True, False),
    # A module the matrix does not hold stays unknown.
    ("sys.platform == 'win32' or '_ctypes' in sys.builtin_module_names", True, False),
    ("sys.platform == 'win32' or sys.builtin_module_names == ()", True, False),
    ("sys.platform == 'win32' or sys.builtin_module_names != ()", True, False),
    ("sys.platform == 'win32' or hasattr(sys, 'gettotalrefcount')", True, False),
    # The machine each platform reports, read exactly for the second question:
    # on x86_64, `== 's390x'` is false (D-201 review).
    ("platform.machine() == 'arm64'", True, True),
    ("platform.machine().lower() in ('arm64', 'aarch64')", True, True),
    ("platform.machine().startswith('arm')", True, True),
    ("platform.machine() != 'Plan9'", True, False),
    ("platform.machine() == 's390x'", True, True),
    ("platform.machine().startswith('riscv')", True, True),
    ("platform.machine() in ('ppc64le', 'aarch64')", True, True),
    ("platform.python_implementation() == 'GraalVM'", True, True),
    # `in` asks every entry, in any order.
    ("platform.python_implementation() not in ('IronPython', 'PyPy')", True, True),
    ("platform.python_implementation() not in ('PyPy', 'IronPython')", True, True),
    ("platform.architecture()[0] == '32bit'", True, True),
    ("platform.architecture()[0] == '16bit'", True, True),
    ("platform.architecture()[0] != '32bit'", True, False),
    # The micro release is unknown: a gate that runs only on x.y.0 is not
    # shown to run anywhere (D-201 review).
    ("sys.version_info > (3, 11, 0)", False, False),
    ("sys.version_info >= (3, 11, 1)", True, False),
    ("sys.version_info != (3, 11, 0, 'final', 0)", True, False),
    ("sys.version_info[2] != 0", True, False),
    ("sys.version_info[:3] >= (3, 11, 4)", True, False),
    ("sys.version_info < (3, 11, 4)", True, True),
    ("sys.version_info[:2] == (3, 11)", True, True),
    ("platform.python_version_tuple() < ('3', '12')", True, True),
    ("platform.python_version() == '3.11.0'", True, True),
    ("platform.python_version() != '3.11.0'", True, False),
    ("platform.python_version() < '3.12'", True, True),
    ("platform.python_version().startswith('3.11')", True, True),
    # A slice, a substring or a number read from the known part (D-201 round 3).
    ("platform.python_version()[:4] == '3.13'", True, True),
    ("'3.13' in platform.python_version()", True, True),
    ("int(platform.python_version_tuple()[1]) >= 13", True, True),
    ("platform.python_version()[5:] == '0'", True, False),
    ("sys.version_info.micro < 2", True, False),
    # List and set displays.
    ("sys.platform not in ['linux', 'darwin']", True, True),
    ("sys.platform in {'win32', 'cygwin'}", True, True),
    ("sys.platform in ['win32', HELPER]", True, False),
    # An unknown entry leaves a tuple unknown, not unequal (D-201 review).
    ("sys.platform in (HELPER,)", True, False),
    ("(sys.platform,) == (HELPER,)", True, False),
    # A list never equals a tuple, as under Python.
    ("sys.version_info[:2] != [3, 11]", False, False),
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
    assert all(_eval_condition(unknown, env, exact=True) is False for env in _ENV_MATRIX)


@pytest.mark.parametrize("value, op, other, answer", [
    # The micro release is unknown, but not every comparison reaches it.
    ((3, 11), "gt", (3, 11, 0), True),
    ((3, 11), "ge", (3, 11, 0), True),
    ((3, 11), "lt", (3, 12), True),
    ((3, 12), "ge", (3, 12), True),
    ((3, 11), "eq", (3, 11), False),
    ((3, 11), "ge", (3, 11, 1), MAYBE),
    ((3, 11), "lt", (3, 11, 4), MAYBE),
    ((3, 11), "eq", (3, 11, 0, "final", 0), MAYBE),
    ((3, 12), "eq", (3, 11, 0, "final", 0), False),
    ((3, 11), "lt", (3, 11, "x"), MAYBE),
])
def test_a_release_with_an_unknown_micro(value, op, other, answer):
    import operator
    release = _Release(value, ("final", 0))
    try:
        got = getattr(operator, op)(release, other)
    except TypeError:
        got = MAYBE
    assert got is answer


def test_a_release_is_indexed_and_sliced_as_the_tuple_it_is():
    release = _Release((3, 12), ("final", 0))
    assert (release[0], release[1], release[3], release[-1], len(release)) == (3, 12, "final", 0, 5)
    assert release[:2] == (3, 12)
    with pytest.raises(TypeError):
        release[2]
    assert release[:3] < (3, 13)
    with pytest.raises(TypeError):
        release[:3] == (3, 12, 1)


@pytest.mark.parametrize("op, other, answer", [
    ("lt", "3.12", True),
    ("gt", "3.10", True),
    ("eq", "3.11", False),
    ("gt", "3.11", True),
    ("eq", "3.11.0", MAYBE),
    ("lt", "3.11.10", MAYBE),
])
def test_a_version_string_with_an_unknown_micro(op, other, answer):
    import operator
    try:
        got = getattr(operator, op)(_VersionString(3, 11), other)
    except TypeError:
        got = MAYBE
    assert got is answer
    assert _VersionString(3, 11).startswith(("2.7", "3.11")) is True
    assert _VersionString(3, 11).startswith("3.12") is False
    with pytest.raises(TypeError):
        _VersionString(3, 11).startswith("3.11.1")


def test_membership_does_not_depend_on_the_order_of_the_entries():
    """Python's `in` stopped at the first entry it could not compare."""
    for spelling in ("platform.python_implementation() in ('IronPython', 'PyPy')",
                     "platform.python_implementation() in ('PyPy', 'IronPython')"):
        node = ast.parse(spelling, mode="eval").body
        answers = {env["implementation"]: _eval_condition(node, env) for env in _ENV_MATRIX}
        assert answers == {"PyPy": True, "CPython": MAYBE}, spelling


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
    # No environment is 32-bit, so "32bit" is a value the matrix does not hold.
    assert guard_always_skips("platform.architecture()[0] != '32bit'", None) is False
    # A fact the matrix holds: every 3.11 release is later than 3.11.0.
    assert guard_always_skips("sys.version_info > (3, 11, 0)", None) is True


@pytest.mark.parametrize("guard", [
    # As a tuple does, the release equals nothing but a tuple, and itself
    # (D-201 round 3: these read as unknown and the always-true guard hid).
    "sys.version_info != None",
    "sys.version_info != '3'",
    "sys.version_info >= sys.version_info",
    "sys.version_info[:2] == sys.version_info[:2]",
    "platform.python_version() != 3",
])
def test_an_always_true_guard_over_the_release_is_read(guard):
    assert guard_always_skips(guard, None) is True


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
    # The order of a string's characters (D-201 review).
    ("assertMultiLineEqual", "assertCountEqual"),
])
def test_an_order_sensitive_equality_rewritten_as_a_multiset_one_drops_order(before, after):
    b = _assertion(f"self.{before}(items(), [1, 2, 3])")
    a = _assertion(f"self.{after}(items(), [1, 2, 3])")
    assert _order_dropped("tests/test_items.py", b, a, {}, {}) == (before, after, False)


@pytest.mark.parametrize("b, a, before_bindings, after_bindings", [
    # The operands swapped.
    ("self.assertEqual(items(), [1, 2, 3])", "self.assertCountEqual([1, 2, 3], items())", {}, {}),
    # list(), tuple() and a starred display are the same operand to assertCountEqual.
    ("self.assertEqual(list(items()), [1, 2, 3])", "self.assertCountEqual(items(), [1, 2, 3])", {}, {}),
    ("self.assertEqual(items(), [1, 2, 3])", "self.assertCountEqual([*items()], [1, 2, 3])", {}, {}),
    ("self.assertEqual(items(), [1, 2, 3])", "self.assertCountEqual(tuple(items()), (1, 2, 3))", {}, {}),
    # A hoisted subject or expected value, through the unit's bindings.
    ("self.assertEqual(items(), [1, 2, 3])", "self.assertCountEqual(result, [1, 2, 3])", {}, {"result": "items()"}),
    ("self.assertEqual(items(), [1, 2, 3])", "self.assertCountEqual(items(), expected)", {}, {"expected": "[1, 2, 3]"}),
    # Through two bindings, and list() around a hoisted name (D-201 review).
    ("self.assertEqual(items(), [1, 2, 3])", "self.assertCountEqual(result, [1, 2, 3])", {},
     {"result": "raw", "raw": "items()"}),
    ("self.assertEqual(list(result), [1, 2, 3])", "self.assertCountEqual(result, [1, 2, 3])",
     {"result": "items()"}, {"result": "items()"}),
    # The same subject, with the expected list reordered or renamed.
    ("self.assertEqual(items(), [1, 2, 3])", "self.assertCountEqual(items(), [3, 2, 1])", {}, {}),
    ("self.assertEqual(items(), EXPECTED_A)", "self.assertCountEqual(items(), EXPECTED_B)", {}, {}),
    # By keyword.
    ("self.assertEqual(first=items(), second=[1, 2, 3])", "self.assertCountEqual(items(), [1, 2, 3])", {}, {}),
    ("self.assertEqual(items(), [1, 2, 3])", "self.assertCountEqual(items(), second=[1, 2, 3])", {}, {}),
    # A bare `assert ==` is an ordered equality, and a name inside the
    # subject is followed one hop (D-201 round 3).
    ("assert items() == [1, 2, 3]", "self.assertCountEqual(items(), [1, 2, 3])", {}, {}),
    ("self.assertEqual(self.client.items(), [1, 2, 3])", "self.assertCountEqual(client.items(), [1, 2, 3])",
     {}, {"client": "self.client"}),
])
def test_the_same_subject_however_spelled(b, a, before_bindings, after_bindings):
    result = _order_dropped("tests/test_items.py", _assertion(b), _assertion(a), before_bindings, after_bindings)
    assert result is not None and result[2] is False


@pytest.mark.parametrize("b, a", [
    ('self.assertEqual(record(), {"total": 6})', 'self.assertCountEqual(record(), {"total": 6})'),
    # assertDictEqual checked the values, which assertCountEqual never reads.
    ('self.assertDictEqual(record(), expected)', 'self.assertCountEqual(record(), expected)'),
])
def test_a_dict_operand_loses_its_values(b, a):
    b, a = _assertion(b, left="record()"), _assertion(a, left="record()")
    assert _order_dropped("tests/test_record.py", b, a, {}, {})[2] is True


@pytest.mark.parametrize("path, b, a", [
    # The other way round starts checking order.
    ("tests/test_items.py", _assertion("self.assertCountEqual(items(), [1, 2, 3])"),
     _assertion("self.assertEqual(items(), [1, 2, 3])")),
    # Another subject compared with a literal both happen to share is
    # another assertion, another rule's question.
    ("tests/test_items.py", _assertion("self.assertEqual(items(), [1, 2, 3])"),
     _assertion("self.assertCountEqual(other(), [1, 2, 3])", left="other()")),
    ("tests/test_items.py", _assertion("self.assertEqual(items(), [])"),
     _assertion("self.assertCountEqual(other(), [])", left="other()")),
    # A set never had an order.
    ("tests/test_items.py", _assertion("self.assertEqual(set(items()), {1, 2, 3})", left="set(items())"),
     _assertion("self.assertCountEqual(set(items()), {1, 2, 3})", left="set(items())")),
    # A negated assertion is not an equality being relaxed.
    ("tests/test_items.py", _assertion("self.assertEqual(items(), [1, 2, 3])"),
     _assertion("self.assertCountEqual(items(), [1, 2, 3])", positive=False)),
    # Only Python's unittest has these names.
    ("tests/items.test.js", _assertion("self.assertEqual(items(), [1, 2, 3])"),
     _assertion("self.assertCountEqual(items(), [1, 2, 3])")),
    # Python 2's assertItemsEqual is not read, and a bare assert other than `==` is no equality.
    ("tests/test_items.py", _assertion("self.assertEqual(items(), [1, 2, 3])"),
     _assertion("self.assertItemsEqual(items(), [1, 2, 3])")),
    ("tests/test_items.py", _assertion("assert items() != [1, 2, 3]"),
     _assertion("self.assertCountEqual(items(), [1, 2, 3])")),
    # What `sorted(...)` put in order loses nothing (D-201 round 3).
    ("tests/test_items.py", _assertion("self.assertListEqual(sorted(items()), [1, 2, 3])", left="sorted(items())"),
     _assertion("self.assertCountEqual(sorted(items()), [1, 2, 3])", left="sorted(items())")),
])
def test_other_pairs_drop_nothing(path, b, a):
    assert _order_dropped(path, b, a, {}, {}) is None

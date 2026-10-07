"""A string `skipif`/`xfail` condition is the expression pytest evaluates (#263).

pytest compiles `skipif("sys.platform == 'win32'")`'s string as an expression
and evaluates it with `os`, `sys` and `platform` bound to those modules,
beside the test module's globals. D6 read the string as a constant, truthy
everywhere, so a real platform gate blocked at high as an unconditional skip
would.

Ruled 2026-10-06:
1. a string condition is parsed as the expression it holds and judged as an
   expression condition is. One that does not parse earns nothing, and one
   that always holds still blocks. The marker's name keeps the string as
   written, so fingerprints do not move;
2. `os`, `sys` and `platform` are read as those modules even when the test
   module does not import them. `config` stays unknown.
"""
import ast
import datetime

import pytest

from checkwash.change import FileChange
from checkwash.compat import MAYBE, _ENV_MATRIX, _eval_condition
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.evidence import _gate_condition_names
from checkwash.findings import make_fingerprint
from checkwash.frontends.python.frontend import parse_python
from checkwash.ir.markers import is_string_condition, mark_condition, marker_call

TEST_PATH = "tests/test_calc.py"
TEST = "def test_add():\n    assert add(1, 2) == 3\n"


def module(decorator="", imports="import sys\n", constants=""):
    return f"import pytest\n{imports}\nfrom app.calc import add\n\n{constants}\n{decorator}{TEST}"


def outcome(after, before=None):
    before = module() if before is None else before
    _ir, findings, verdict = analyze(
        [FileChange(TEST_PATH, "modified", before.encode(), after.encode())],
        Config(), Contract(), [], datetime.date(2026, 10, 6),
    )
    return verdict, [(f.rule, f.severity, f.deescalators) for f in findings]


HELD = ("pass", [("TEST_DISABLED", "warn", ["COMPAT_GATE"])])
BLOCKED = ("block", [("TEST_DISABLED", "high", [])])


# --- 1: a string condition is the expression it holds -----------------------------

@pytest.mark.parametrize("decorator, imports, constants", [
    # S1, and the same gate in a module that does not import `sys` (ruling 2)
    ("@pytest.mark.skipif(\"sys.platform == 'win32'\")\n", "import sys\n", ""),
    ("@pytest.mark.skipif(\"sys.platform == 'win32'\")\n", "", ""),
    ("@pytest.mark.skipif(\"sys.version_info < (3, 12)\", reason=\"old\")\n", "", ""),
    ("@pytest.mark.skipif(\"sys.platform.startswith('win')\")\n", "", ""),
    ("@pytest.mark.skipif(\"os.name == 'nt'\")\n", "", ""),
    ("@pytest.mark.skipif(\"platform.system() == 'Windows'\")\n", "", ""),
    # a non-strict xfail reads its string as skipif does
    ("@pytest.mark.xfail(\"sys.platform == 'win32'\")\n", "", ""),
    # a module constant the string names, as pytest's module globals hold it
    ("@pytest.mark.skipif(\"WIN\")\n", "import sys\n", "WIN = sys.platform == 'win32'\n"),
    # `config` stays unknown: the condition is held when the rest can be false
    ("@pytest.mark.skipif(\"config.getoption('--slow') and sys.platform == 'win32'\")\n", "", ""),
    # a mark applied by a bound name (#260 M1), as pytest's own history spells it
    ("@win32only\n", "import sys\n",
     "win32only = pytest.mark.skipif(\"not (sys.platform == 'win32' or sys.platform == 'cygwin')\")\n"),
], ids=["S1", "S1_no_import", "version", "startswith", "os_name", "platform_system", "xfail", "constant",
        "config_unknown", "bound_name"])
def test_a_string_condition_that_can_be_false_is_held(decorator, imports, constants):
    assert outcome(module(decorator, imports, constants)) == HELD


@pytest.mark.parametrize("decorator, imports, constants", [
    # always true on every supported Python, as a string
    ("@pytest.mark.skipif(\"sys.version_info >= (3,)\")\n", "", ""),
    ("@pytest.mark.skipif(\"True\")\n", "", ""),
    ("@pytest.mark.skipif(\"True or sys.platform == 'win32'\")\n", "", ""),
    # a constant that always holds, named in the string
    ("@pytest.mark.skipif(\"ALWAYS or sys.platform == 'win32'\")\n", "import sys\n", "ALWAYS = True\n"),
    # a string pytest cannot compile earns nothing
    ("@pytest.mark.skipif(\"sys.platform ==\")\n", "", ""),
    ("@pytest.mark.skipif(\" sys.platform == 'win32'\")\n", "", ""),
    ("@pytest.mark.skipif(\"\")\n", "", ""),
    # strict xfail inverts the oracle whatever its condition
    ("@pytest.mark.xfail(\"sys.platform == 'win32'\", strict=True)\n", "", ""),
    # pytest's `platform` is the module, which no string equals (ruling 2)
    ("@pytest.mark.skipif(\"platform != 'linux' or sys.platform == 'win32'\")\n", "", ""),
], ids=["version_always", "true", "true_or", "always_constant", "unparseable", "indented", "empty", "strict_xfail",
        "platform_module"])
def test_a_string_condition_that_always_holds_or_cannot_be_read_blocks(decorator, imports, constants):
    assert outcome(module(decorator, imports, constants)) == BLOCKED


def test_the_marker_keeps_the_string_as_written():
    """The name, and so the fingerprint, holds the string, not the expression
    read from it; its whitespace is dropped, as in every marker's name."""
    decorator = "@pytest.mark.skipif(\"sys.platform == 'win32'\")\n"
    [marker] = [m for unit in parse_python(module(decorator).encode(), collect_tests=True).units
                for m in unit.side.markers]
    assert marker.name == "pytest.mark.skipif(\"sys.platform=='win32'\")"
    _ir, findings, _verdict = analyze(
        [FileChange(TEST_PATH, "modified", module().encode(), module(decorator).encode())],
        Config(), Contract(), [], datetime.date(2026, 10, 6),
    )
    assert [f.fingerprint for f in findings] == [make_fingerprint("TEST_DISABLED", TEST_PATH, "test_add", marker.name)]


# --- 2: the names pytest provides ---------------------------------------------------

def _values(condition, consts=None, pytest_names=True):
    node = ast.parse(condition, mode="eval").body
    parsed = {name: ast.parse(text, mode="eval").body for name, text in (consts or {}).items()}
    return {_eval_condition(node, env, parsed, pytest_names) for env in _ENV_MATRIX}


def test_a_bare_module_name_in_a_string_is_the_module():
    """A module equals no string, so a comparison with one is decided everywhere."""
    assert _values("platform != 'linux'") == {True}
    assert _values("platform == 'linux'") == {False}
    for name in ("os", "sys", "platform"):
        [value] = _values(name)
        assert value is not MAYBE and _values(f"not {name}") == {False}
        assert _values(f"{name} == {name}") == {True}
    assert _values("os == sys") == {False}
    # Ordering a module against a value is unknown, not an error.
    assert _values("platform < 'x'") == {MAYBE}


def test_an_expression_condition_keeps_its_reading_of_a_bare_name():
    """Outside a string, a bare `platform` is the `from sys import platform` it must be."""
    assert _values("platform == 'linux'", pytest_names=False) == {True, False}


def test_a_module_constant_of_that_name_wins_and_is_read_as_module_code():
    """pytest's module globals override its own names, and a constant is module code."""
    assert _values("platform == 'linux'", {"platform": "sys.platform"}) == {True, False}
    assert _values("not WIN", {"WIN": "platform == 'win32'"}) == {True, False}
    # pytest's names are not the constant's: in module code a bare `sys` is
    # whatever the module bound, which nothing here records.
    assert _values("platform", {"platform": "sys"}) == {MAYBE}


def _guarded(condition):
    """A `pytestmark` binding under `if platform != 'win32':`, with `platform` from `sys`."""
    return (
        "import sys\n\nimport pytest\nfrom sys import platform\n\n"
        "if platform != 'win32':\n"
        f"    pytestmark = pytest.mark.skipif({condition})\n\n\n"
        + TEST
    )


def test_a_string_beside_a_guard_is_read_in_its_own_namespace():
    """The binding's guard is module code, where `platform` is `sys.platform`,
    so it can be false; the mark's string, in pytest's namespace, always holds."""
    source = _guarded("\"sys.version_info >= (3,)\"")
    assert outcome(source, before=source.replace("    pytestmark", "    _unused")) == HELD


def test_a_guarded_string_that_does_not_compile_earns_nothing():
    """pytest reports an error for the mark, so the test does not run anywhere it applies."""
    source = _guarded("\"sys.platform ==\"")
    assert outcome(source, before=source.replace("    pytestmark", "    _unused")) == BLOCKED


# --- the names the engine resolves for a string ------------------------------------

def test_names_in_a_string_condition_are_resolved_and_a_reason_is_not():
    source = (
        "import sys\n\nimport pytest\n\nWIN = sys.platform == 'win32'\nflaky = True\n\n\n"
        "@pytest.mark.skipif(\"WIN and not CI\")\n"
        "def test_a():\n    pytest.xfail(\"flaky\")\n"
    )
    assert _gate_condition_names(parse_python(source.encode(), collect_tests=True)) == {"WIN", "CI"}


@pytest.mark.parametrize("text, expected", [
    ("pytest.mark.skipif(\"sys.platform == 'win32'\")", "sys.platform == 'win32'"),
    ("pytest.mark.skipif(sys.platform == 'win32')", "sys.platform == 'win32'"),
    ("pytest.mark.skipif(\"(a,\\nb)\")", "(a, b)"),
    ("pytest.mark.skipif(\"a,\\nb\")", None),
    ("pytest.mark.skipif(\"x =\")", None),
    ("pytest.mark.skipif(reason='later')", None),
])
def test_mark_condition(text, expected):
    condition = mark_condition(marker_call(text))
    assert (None if condition is None else ast.unparse(condition)) == expected


def test_is_string_condition():
    assert is_string_condition(marker_call("pytest.mark.skipif('x')"))
    assert not is_string_condition(marker_call("pytest.mark.skipif(x)"))
    assert not is_string_condition(marker_call("pytest.mark.skipif(reason='x')"))


# --- liveness: a test carried under a string-gated mark still runs ------------------

def test_tests_moved_under_a_class_mark_with_a_string_condition_are_relocated():
    """pytest 1ff173baee's shape: two tests move into a class whose `pytestmark`
    is a name bound to `skipif("sys.version_info < (2,6)")`. The moved units
    run, so their old units' disappearance is a relocation, not a disable."""
    tests = "def test_one():\n    assert add(1, 2) == 3\n\n\ndef test_two():\n    assert add(2, 2) == 4\n"
    before = "import pytest\n\nfrom app.calc import add\n\n\n" + tests
    after = (
        "import pytest\n\nfrom app.calc import add\n\n"
        "old_python = pytest.mark.skipif(\"sys.version_info < (2,6)\")\n\n\n"
        "class TestAdd:\n    pytestmark = old_python\n\n"
        "    def test_one(self):\n        assert add(1, 2) == 3\n\n"
        "    def test_two(self):\n        assert add(2, 2) == 4\n"
    )
    verdict, findings = outcome(after, before=before)
    assert verdict == "pass"
    assert all(severity != "high" for _rule, severity, _held in findings)

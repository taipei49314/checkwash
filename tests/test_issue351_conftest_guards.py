"""A guarded skip in a conftest fixture a test reaches is judged by its guard (#351).

183.2's conftest half. A test module's own fixture records a guarded skip
with its guard, and D6 judges it as a guarded skip in the test body (D-087);
a conftest fixture recorded only its unconditional skip, so a test that
started requesting `needs_network` from the conftest passed where the same
fixture in the test module blocked.

The conftest's guard is written in the conftest's names, while D6 evaluates
a marker's guard with the test module's constants. So before it is recorded
the guard is closed over the conftest (`ConftestGuard`):

1. a top-level constant of the conftest is replaced by its defining
   expression, as far as the evaluator follows a constant; a name an import
   also binds is ambiguous and is not replaced;
2. any other name the evaluator reads as a value becomes `conftest.<name>`,
   unknown, and never resolves through the test module; call targets and
   attribute roots stay as written;
3. a name imported from another module is not followed, so a gate spelled
   through one is judged with that part unknown.

The conftest's `<suite>` control still reads only an unconditional skip.
"""
import datetime

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.frontends.python.frontend import parse_conftest_level

TEST = "tests/test_billing.py"
APP = {"app/__init__.py": b"", "app/billing.py": b"def total():\n    return 78.75\n"}
ADDED = "test_total: skip/xfail added to the setup this test runs (setup.gate.skip)"


def conftest(guard, prelude="import os\nimport sys\n\nimport pytest\n", params=""):
    return f"{prelude}\n\n@pytest.fixture\ndef gate({params}):\n    if {guard}:\n        pytest.skip('off')\n"


def module(signature, prelude=""):
    return f"import pytest\n\nfrom app.billing import total\n{prelude}\n\ndef {signature}:\n    assert total() == 78.75\n"


def guard_of(source, name="gate"):
    return parse_conftest_level(source.encode(), "tests/conftest.py").fixtures[name][2][2]


def run(source, *, before_prelude="", after_prelude="", before_conftest=None):
    """TEST_DISABLED (message, severity, deescalators) and the verdict for a test newly requesting `gate`."""
    before, after = module("test_total()", before_prelude), module("test_total(gate)", after_prelude)
    changes = [FileChange(TEST, "modified", before.encode(), after.encode())]
    if before_conftest is not None:
        changes.append(FileChange("tests/conftest.py", "modified", before_conftest.encode(), source.encode()))
    snapshot = {**APP, "tests/conftest.py": source.encode(), TEST: after.encode()}
    _ir, findings, verdict = analyze(
        changes, Config(), Contract(), [], datetime.date(2026, 10, 8),
        head_reader=snapshot.get, root_reader=snapshot.get,
    )
    return [(f.message, f.severity, f.deescalators) for f in findings if f.rule == "TEST_DISABLED"], verdict


# --- the guard, closed over the conftest -----------------------------------------------------


@pytest.mark.parametrize("prelude, guard, closed", [
    # An attribute root and a call target are read by their spelling.
    ("", "not os.environ.get('NETWORK')", "not os.environ.get('NETWORK')"),
    ("", "sys.platform.startswith('win')", "sys.platform.startswith('win')"),
    # A constant is replaced by its defining expression, closed in turn.
    ("WIN = sys.platform == 'win32'\n", "WIN", "(sys.platform == 'win32')"),
    ("WIN = sys.platform == 'win32'\nOFF = not WIN\n", "OFF", "(not (sys.platform == 'win32'))"),
    ("PLAT: str = sys.platform\n", "PLAT.startswith('win')", "(sys.platform).startswith('win')"),
    ("ENV = os.environ\n", "not ENV['NETWORK']", "not (os.environ)['NETWORK']"),
    ("PREFIX = 'win'\n", "sys.platform.startswith(PREFIX)", "sys.platform.startswith(('win'))"),
    # The last binding is the one the fixture reads.
    ("WIN = False\nWIN = sys.platform == 'win32'\n", "WIN", "(sys.platform == 'win32')"),
    # Any other name is the conftest's, and unknown.
    ("", "ON_CI", "conftest.ON_CI"),
    ("", "ON_CI and sys.platform == 'win32'", "conftest.ON_CI and sys.platform == 'win32'"),
    # A cycle stops where the evaluator's would.
    ("A = B\nB = A\n", "A", "((conftest.A))"),
    ("A = not A\n", "A", "(not conftest.A)"),
])
def test_a_conftest_guard_is_closed_over_the_conftests_names(prelude, guard, closed):
    source = conftest(guard, prelude="import os\nimport sys\n\nimport pytest\n\n" + prelude)
    assert guard_of(source) == closed


@pytest.mark.parametrize("prelude, guard", [
    ("from sys import platform\n", "platform == 'win32'"),
    ("from helpers import WIN\n", "WIN"),
    ("import helpers as WIN\n", "WIN"),
    # Bound by an assignment and an import: ambiguous, as `_gate_constants` reads it.
    ("WIN = sys.platform == 'win32'\nfrom helpers import WIN\n", "WIN"),
])
def test_an_imported_name_is_not_followed(prelude, guard):
    source = conftest(guard, prelude="import os\nimport sys\n\nimport pytest\n\n" + prelude)
    name = guard.split()[0]
    assert guard_of(source) == guard.replace(name, f"conftest.{name}", 1)


def test_the_fixtures_own_names_are_never_the_conftests_constants():
    prelude = "import sys\n\nimport pytest\n\nWIN = sys.platform == 'win32'\n"
    assert guard_of(conftest("WIN", prelude=prelude, params="WIN")) == "conftest.WIN"
    body = "@pytest.fixture\ndef gate():\n    WIN = True\n    if WIN:\n        pytest.skip('off')\n"
    assert guard_of(prelude + "\n\n" + body) == "conftest.WIN"


def test_a_name_in_an_f_string_or_a_call_target_stays():
    prelude = "import sys\n\nimport pytest\n\nWIN = sys.platform == 'win32'\n"
    assert guard_of(conftest("check(f'{WIN}')", prelude=prelude)) == "check(f'{WIN}')"
    assert guard_of(conftest("WIN(1)", prelude=prelude)) == "WIN(1)"


def test_a_long_chain_of_constants_stops_at_the_evaluators_depth():
    chain = "".join(f"C{i} = C{i + 1}\n" for i in range(30)) + "C30 = sys.platform == 'win32'\n"
    guard = guard_of(conftest("C0", prelude="import sys\n\nimport pytest\n\n" + chain))
    assert guard.count("(") == 16 and guard.endswith("conftest.C16" + ")" * 16)


def test_a_guard_across_lines_keeps_its_parentheses():
    prelude = "import sys\n\nimport pytest\n\nWIN = (sys.platform\n       == 'win32')\n"
    assert guard_of(conftest("(WIN\n            and sys.version_info < (3, 12))", prelude=prelude)) == (
        "((sys.platform\n       == 'win32')\n            and sys.version_info < (3, 12))"
    )


def test_an_unconditional_outcome_has_no_guard():
    source = "import pytest\n\n\n@pytest.fixture\ndef gate():\n    pytest.skip('off')\n"
    assert guard_of(source) is None


# --- how it is judged ------------------------------------------------------------------------


def test_an_environment_guard_blocks_as_in_the_test_module():
    assert run(conftest("not os.environ.get('NETWORK')")) == ([(ADDED, "high", [])], "block")


@pytest.mark.parametrize("guard, prelude", [
    ("sys.platform == 'win32'", ""),
    ("WIN", "WIN = sys.platform == 'win32'\n"),
    ("sys.version_info < (3, 12)", ""),
])
def test_an_interpreter_or_os_gate_holds_at_warn(guard, prelude):
    source = conftest(guard, prelude="import os\nimport sys\n\nimport pytest\n\n" + prelude)
    assert run(source) == ([(ADDED, "warn", ["COMPAT_GATE"])], "pass")


def test_the_test_modules_constant_does_not_judge_the_conftests_name():
    """`ON_CI` means the conftest's value, not the test module's platform check."""
    source = conftest("ON_CI", prelude="import os\nimport sys\n\nimport pytest\n\nON_CI = os.environ.get('CI')\n")
    own = "\nimport sys\n\nON_CI = sys.platform == 'win32'\n"
    assert run(source, before_prelude=own, after_prelude=own) == ([(ADDED, "high", [])], "block")


def test_the_conftests_gate_holds_whatever_the_test_module_binds():
    source = conftest("WIN", prelude="import sys\n\nimport pytest\n\nWIN = sys.platform == 'win32'\n")
    own = "\nWIN = True\n"
    assert run(source, before_prelude=own, after_prelude=own) == ([(ADDED, "warn", ["COMPAT_GATE"])], "pass")


def test_a_gate_spelled_through_an_import_is_judged_unknown():
    """The stated residual: `from sys import platform` is not followed into `sys`."""
    source = conftest("platform == 'win32'", prelude="from sys import platform\n\nimport pytest\n")
    assert run(source) == ([(ADDED, "high", [])], "block")


def test_a_conftest_guard_that_now_always_holds_is_reported():
    """The test keeps requesting `gate`; the conftest's constant is edited to always hold."""
    prelude = "import sys\n\nimport pytest\n\n"
    before = conftest("WIN", prelude=prelude + "WIN = sys.platform == 'win32'\n")
    after = conftest("WIN", prelude=prelude + "WIN = True\n")
    request = module("test_total(gate)")
    changes = [
        FileChange(TEST, "modified", request.encode(), (request + "\n").encode()),
        FileChange("tests/conftest.py", "modified", before.encode(), after.encode()),
    ]
    snapshot = {**APP, "tests/conftest.py": after.encode(), TEST: (request + "\n").encode()}
    _ir, findings, verdict = analyze(
        changes, Config(), Contract(), [], datetime.date(2026, 10, 8),
        head_reader=snapshot.get, root_reader=snapshot.get,
    )
    disabled = [f for f in findings if f.rule == "TEST_DISABLED"]
    assert verdict == "block" and [f.severity for f in disabled] == ["high"]
    assert disabled[0].message == (
        "test_total: skip guard in the setup this test runs now always fires ('(True)') (setup.gate.skip)"
    )


def test_the_suite_control_still_reads_only_an_unconditional_skip():
    """Reading 4: a guarded conftest fixture no test in the diff requests is no event."""
    before = "import os\n\nimport pytest\n"
    after = conftest("not os.environ.get('NETWORK')")
    change = FileChange("tests/conftest.py", "modified", before.encode(), after.encode())
    _ir, findings, verdict = analyze([change], Config(), Contract(), [], datetime.date(2026, 10, 8))
    assert ([f for f in findings if f.rule == "TEST_DISABLED"], verdict) == ([], "pass")

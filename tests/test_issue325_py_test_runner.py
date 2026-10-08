"""Issue #325: `py.test`, pytest's own console script, is a test runner name.

pytest still installs `py.test` beside `pytest` (pytest 9.1.1's
`entry_points.txt` has `py.test = _pytest.config:_console_main`), but row
69's names (`roles._TEST_RUNNER_TOKENS`) held `pytest` alone, and neither the
substring reader (`_runs_tests`) nor the whole-word reader (`runner_command`)
finds `pytest` inside `py.test`. A workflow whose only runner was `py.test`
could be turned off with `if: false` or deleted at warn, a runner script
that ran only `py.test` was no test command at all, and a production file
that mentioned only `py.test` kept the opaque-change exemption.

Now `py.test` is one of row 69's names, read as a whole name in both
readers, so `numpy.testing` and `copy.test` name no runner.
"""
import datetime

import pytest

from checkwash.change import FileChange
from checkwash.ci_control_flow import holds_runner_site
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.roles import _is_runner_script, _mentions_test_runner, _runs_tests
from checkwash.runner_command import invokes_test_runner, names_test_runner

TREE = {
    "app/__init__.py": b"",
    "app/billing.py": b"def total():\n    return 78.75\n",
    "tests/test_total.py": b"from app.billing import total\n\n\ndef test_total():\n    assert total() == 78.75\n",
}
WORKFLOW = ".github/workflows/ci.yml"


def workflow(command, dead=False):
    text = ("name: ci\non:\n  pull_request:\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n"
            "      - uses: actions/checkout@v4\n      - run: pip install -e .\n"
            f"      - run: {command}\n")
    return (text + ("        if: false\n" if dead else "")).encode()


def script(command):
    return f"#!/usr/bin/env bash\nset -euo pipefail\n{command}\n".encode()


def run(*changes):
    snapshot = dict(TREE)
    for change in changes:
        if change.after is None:
            snapshot.pop(change.path, None)
        else:
            snapshot[change.path] = change.after
    _ir, findings, verdict = analyze(list(changes), Config(), Contract(), [], datetime.date(2026, 10, 7),
                                     root_reader=snapshot.get, root_path_lister=lambda: sorted(snapshot),
                                     root_batch_reader=lambda paths: {p: snapshot.get(p) for p in paths})
    return verdict, [(f.rule, f.severity, f.message) for f in findings]


def weakened(reason):
    return ("block", [("CI_WORKFLOW_TOUCHED", "high", "CI configuration changed; test command weakened: " + reason)])


# --- the issue's rows ---------------------------------------------------------------------------

@pytest.mark.parametrize("command", ["pytest", "py.test", "python -m pytest", "py.test -x tests", "bin/py.test"],
                         ids=["C1_pytest", "C2_py_test", "C5_python_m_pytest", "py_test_with_targets",
                              "py_test_by_path"])
def test_a_step_turned_off_by_if_false_is_a_disabled_suite(command):
    assert run(FileChange(WORKFLOW, "modified", workflow(command), workflow(command, dead=True))) == weakened(
        f"{command} is disabled (if: false)")


@pytest.mark.parametrize("command", ["pytest", "py.test", "python -m pytest"],
                         ids=["C3_pytest", "C4_py_test", "C5_python_m_pytest"])
def test_deleting_the_workflow_removes_a_gate(command):
    assert run(FileChange(WORKFLOW, "deleted", workflow(command), None)) == weakened("workflow file removed")


def test_a_runner_script_that_runs_py_test_is_the_test_command():
    """Row 69: losing its `py.test` line is a weakened command, and so is a swallow."""
    assert _is_runner_script("scripts/test.sh", script("py.test tests"), script("py.test tests"))
    assert run(FileChange("scripts/test.sh", "modified", script("py.test tests"), script("echo done"))) == weakened(
        "the test suite is no longer invoked by this script")
    assert run(FileChange("scripts/test.sh", "modified", script("py.test tests"),
                          script("py.test tests || true"))) == weakened("py.test tests || true")


def test_swapping_pytest_for_py_test_is_consolidation():
    """A runner swap keeps a token and earns nothing (row 69)."""
    assert run(FileChange("scripts/test.sh", "modified", script("pytest tests"), script("py.test tests"))) == (
        "pass", [("CI_WORKFLOW_TOUCHED", "warn", "CI configuration changed")])


def test_a_file_that_runs_py_test_loses_the_opaque_exemption():
    assert _mentions_test_runner(FileChange("tools/run", "modified", script("py.test"), script("py.test -q")))


# --- a whole name -------------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "py.test", "py.test -x tests", "./bin/py.test", "py.test.exe", "PY.TEST", "run: py.test",
    "python -c 'import py; py.test.main()'",
])
def test_py_test_is_a_runner_name(text):
    assert _runs_tests(text.encode())
    assert names_test_runner(text)


@pytest.mark.parametrize("text", [
    "python -c 'import numpy.testing'", "cp copy.test build/", "py.testing", "happy.test_run", "pkg.py.test",
])
def test_a_dotted_name_inside_another_name_is_none(text):
    assert not _runs_tests(text.encode())
    assert not names_test_runner(text)


@pytest.mark.parametrize("command, runs", [
    ("py.test", True),
    ("cd app && py.test --flag", True),
    ("echo py.test", False),
    ("# py.test runs in another job", False),
    ("python -c 'import numpy.testing'", False),
])
def test_a_py_test_command_is_a_runner_site(command, runs):
    assert invokes_test_runner(command) is runs
    assert holds_runner_site(WORKFLOW, workflow(command)) is runs

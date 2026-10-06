"""Composite action definitions are ci: `.github/actions/**/action.yml` and `action.yaml` (#213).

A composite action's steps run inside the job that calls it, so
`.github/actions/test/action.yml` can hold a project's real test command. The
`ci` role covered `.github/workflows/**` and not the action definitions, so
`pytest || true` in one gave zero findings, and an action whose runner holds
no runner token (`node --test`) bought the opaque exemption for an assertion
weakened beside it.

Ruling (2026-10-03, #196): scope the default `ci` glob to the action
definitions, not all of `.github/actions/**`: a JavaScript action's source
kept beside its definition stays production, and a script an action calls is
promoted by its content already. Feeding composite `runs.steps` into the
runner-site reader is a later step.
"""
import datetime

import pytest

from checkwash.change import FileChange
from checkwash.config import DEFAULT_ROLES, Config
from checkwash.contract import Contract
from checkwash.engine import analyze

TODAY = datetime.date(2026, 10, 5)


@pytest.mark.parametrize("path", [
    ".github/actions/test/action.yml",
    ".github/actions/test/action.yaml",
    ".github/actions/setup-tox/action.yml",
    ".github/actions/python/test/action.yml",
])
def test_an_action_definition_beneath_github_actions_is_ci(path):
    assert Config().role_of(path) == "ci"


@pytest.mark.parametrize("path", [
    ".github/actions/notify/index.js",
    ".github/actions/notify/dist/index.js",
    ".github/actions/image/Dockerfile",
    ".github/actions/test/README.md",
    "action.yml",
    "action/action.yml",
])
def test_everything_else_keeps_the_role_it_had(path):
    # A JavaScript action's source, a Docker action's image and an action
    # published from the repository root are not the definitions the ruling
    # names.
    assert Config().role_of(path) != "ci"


def test_the_globs_are_defaults_a_project_can_replace():
    assert ".github/actions/**/action.yml" in DEFAULT_ROLES["ci"]
    assert ".github/actions/**/action.yaml" in DEFAULT_ROLES["ci"]
    custom = Config(roles={**DEFAULT_ROLES, "ci": [".github/workflows/**"]})
    assert custom.role_of(".github/actions/test/action.yml") == "prod"


def _action(step):
    return (
        "name: test\nruns:\n  using: composite\n  steps:\n"
        "    - run: pip install -e .[test]\n      shell: bash\n"
        f"    - run: {step}\n      shell: bash\n"
    ).encode()


def _run(*changes):
    ir, findings, verdict = analyze(list(changes), Config(), Contract(), [], TODAY)
    roles = {f.path: f.role for f in ir.files}
    return roles, verdict, [(f.rule, f.severity, tuple(f.escalators)) for f in findings]


def test_the_definition_keeps_ci_beneath_a_test_support_directory():
    # #217 gives a non-Python file beneath `test/` the test role, as a
    # fixture or a mock; a path the table resolves to another role keeps it.
    roles, verdict, findings = _run(
        FileChange(".github/actions/test/action.yml", "modified", _action("pytest"), _action("pytest || true")))
    assert roles == {".github/actions/test/action.yml": "ci"}
    assert verdict == "block"
    assert findings == [("CI_WORKFLOW_TOUCHED", "high", ("CI_TEST_COMMAND_WEAKENED",))]


def test_a_narrowing_introduced_in_an_action_step_is_a_weakening():
    roles, verdict, findings = _run(FileChange(
        ".github/actions/suite/action.yml", "modified", _action("pytest"),
        _action("pytest --deselect tests/test_billing.py::test_total")))
    assert verdict == "block"
    assert findings == [("CI_WORKFLOW_TOUCHED", "high", ("CI_TEST_COMMAND_WEAKENED",))]


def test_a_docker_action_definition_edit_is_reported_at_warn():
    before = b"name: image\nruns:\n  using: docker\n  image: Dockerfile\n"
    after = before + b"  args: ['--fast']\n"
    _roles, verdict, findings = _run(FileChange(".github/actions/image/action.yml", "modified", before, after))
    assert (verdict, findings) == ("pass", [("CI_WORKFLOW_TOUCHED", "warn", ())])


def test_a_script_the_action_calls_is_still_promoted_by_its_content():
    script = b"#!/usr/bin/env bash\nset -euo pipefail\npytest -q\n"
    roles, verdict, findings = _run(FileChange(
        ".github/actions/test/run-tests.sh", "modified", script, script.replace(b"pytest -q", b"pytest -q || true")))
    assert roles == {".github/actions/test/run-tests.sh": "ci"}
    assert verdict == "block"

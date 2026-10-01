"""Issue #181: CI control flow that stops a runner without touching its line.

The fixtures in tests/cases pin the verdicts end to end. These pin what a
fixture cannot show directly: which `if:` spellings are statically false,
which YAML the bounded reader models or declines, and the reasons it gives.
"""

import pytest

from checkwash.ci_control_flow import _UNKNOWN, _never_true, _read_yaml, control_flow_weakenings

PATH = ".github/workflows/ci.yml"
WORKFLOW = (
    "on:\n"
    "  push:\n"
    "    branches: [main]\n"
    "  pull_request:\n"
    "jobs:\n"
    "  test:\n"
    "    runs-on: ubuntu-latest\n"
    "    steps:\n"
    "      - run: pytest\n"
)
PRECOMMIT = (
    "repos:\n"
    "  - repo: local\n"
    "    hooks:\n"
    "      - id: pytest\n"
    "        name: pytest\n"
    "        entry: pytest\n"
    "        language: system\n"
    "        pass_filenames: false\n"
)


def _weakenings(before, after, path=PATH):
    return control_flow_weakenings(path, before.encode("utf-8"), after.encode("utf-8"))


@pytest.mark.parametrize("condition", [
    "false",
    "False",
    "${{ false }}",
    "${{false}}",
    "0",
    "${{ 0 }}",
    "''",
    "!true",
    "(false)",
    "1 == 2",
    "'Push' != 'push'",
    "always() && false",
    "false && github.ref == 'refs/heads/main'",
    "github.ref == 'refs/heads/main' && false",
])
def test_statically_false_conditions_never_run(condition):
    assert _never_true(condition, "pull_request")


@pytest.mark.parametrize("condition", [
    None,
    "",
    "true",
    "success()",
    "${{ !cancelled() }}",
    "matrix.os == 'ubuntu-latest'",
    "false || matrix.python == '3.12'",
    "runner.os != 'Windows' && false || true",
    "github.event_name == 'push' || github.ref == 'refs/heads/main'",
    "github.event_name == 'pull_request'",
    "${{ false }} && true",
    "contains(github.event.head_commit.message, 'ci: skip') == false",
    "fromJSON(inputs.run-tests)",
])
def test_conditions_that_may_hold_keep_the_step_live(condition):
    assert not _never_true(condition, "pull_request")


def test_event_conditions_are_judged_per_event_that_can_run_the_workflow():
    condition = "github.event_name == 'push'"
    assert _never_true(condition, "pull_request")
    assert not _never_true(condition, "push")
    # Inside a called workflow the event is the caller's, so nothing is bound.
    assert not _never_true(condition, _UNKNOWN)


def test_reader_models_the_workflow_subset():
    tree = _read_yaml((
        "defaults: &shared\n"
        "  runs-on: ubuntu-latest\n"
        "jobs:\n"
        "  test:\n"
        "    <<: *shared\n"
        "    steps:\n"
        "    - name: it's quoted text, not a quote # a comment\n"
        "      run: |\n"
        "        # a shell comment, not YAML\n"
        "        pytest -q\n"
        "      if: \"false\"\n"
        "    - uses: actions/setup-python@v5\n"
        "      with: {python-version: '3.12'}\n"
    ).encode("utf-8"))
    job = tree["jobs"]["test"]
    assert job["runs-on"] == "ubuntu-latest"
    assert job["steps"][0] == {
        "name": "it's quoted text, not a quote",
        "run": "# a shell comment, not YAML\npytest -q",
        "if": "false",
    }
    assert job["steps"][1]["with"] == {"python-version": "3.12"}


def test_reader_joins_a_multi_line_flow_collection():
    tree = _read_yaml(b"on:\n  push:\n    branches: [\n      main,\n      'release/**',\n    ]\n")
    assert tree == {"on": {"push": {"branches": ["main", "release/**"]}}}


@pytest.mark.parametrize("data", [
    b"jobs:\n  test:\n    if: !!str false\n",
    b"jobs:\n\ttest:\n",
    b"jobs:\n  test:\n    if: *missing\n",
    b"%YAML 1.2\n---\njobs: {}\n",
    b"[pytest]\naddopts = -q\n",
])
def test_reader_declines_what_it_does_not_model(data):
    assert _read_yaml(data) is None


def test_disabled_step_reason_names_the_command_and_the_cause():
    assert _weakenings(WORKFLOW, WORKFLOW + "        if: false\n") == ["pytest is disabled (if: false)"]


def test_losing_the_only_pull_request_trigger_disables_the_suite():
    assert _weakenings(WORKFLOW, WORKFLOW.replace("  pull_request:\n", "")) == [
        "pytest is disabled (no trigger runs it on a pull request)"
    ]


def test_an_unfiltered_push_still_runs_on_the_pull_requests_branch():
    before = WORKFLOW.replace("    branches: [main]\n", "")
    assert _weakenings(before, before.replace("  pull_request:\n", "")) == []


def test_a_job_that_needs_a_disabled_job_is_skipped_unless_it_asks_to_run():
    before = (
        "jobs:\n"
        "  lint:\n"
        "    steps:\n"
        "      - run: ruff check .\n"
        "  test:\n"
        "    needs: [lint]\n"
        "    steps:\n"
        "      - run: pytest\n"
    )
    disable = ("  lint:\n", "  lint:\n    if: false\n")
    assert _weakenings(before, before.replace(*disable)) == [
        "pytest is disabled (job test needs a job that cannot run)"
    ]
    aware = before.replace("    needs: [lint]\n", "    needs: [lint]\n    if: ${{ always() }}\n")
    assert _weakenings(aware, aware.replace(*disable)) == []


def test_editing_live_and_already_dead_runners_alike_moves_nothing():
    before = WORKFLOW + "  e2e:\n    if: false\n    steps:\n      - run: pytest tests/e2e\n"
    after = before.replace("- run: pytest\n", "- run: pytest -q\n").replace("tests/e2e", "tests/e2e -q")
    assert _weakenings(before, after) == []


def test_precommit_hook_inventory_is_two_sided():
    path = ".pre-commit-config.yaml"
    assert _weakenings(PRECOMMIT, "repos: []\n", path) == ["pytest is no longer run by any pre-commit hook"]
    assert _weakenings(PRECOMMIT, PRECOMMIT.replace("entry: pytest", "entry: tox -e py"), path) == []
    assert _weakenings(PRECOMMIT, PRECOMMIT + "        stages: [manual]\n", path) == [
        "pytest is disabled (stages: [manual])"
    ]


def test_unreadable_or_unrelated_files_report_nothing():
    disabled = WORKFLOW + "        if: false\n"
    assert control_flow_weakenings(PATH, b"\x00\xff\xfe", disabled.encode("utf-8")) == []
    assert _weakenings(WORKFLOW, disabled, "tox.ini") == []

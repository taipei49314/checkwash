"""Issue #181: CI control flow that stops a runner without touching its line.

The fixtures in tests/cases pin the verdicts end to end. These pin what a
fixture cannot show directly: which `if:` spellings are statically false,
which YAML the bounded reader models or declines, and the reasons it gives.
"""

import datetime

import pytest

from checkwash.change import FileChange
from checkwash.ci_control_flow import (
    _UNKNOWN,
    _never_true,
    _pr_events,
    _read_document,
    _read_yaml,
    became_unanalysable,
    control_flow_weakenings,
)
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze

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
    assert _weakenings(PRECOMMIT, "repos: []\n", path) == ["no pre-commit hook entry invokes a recognised test runner any more (was: pytest)"]
    assert _weakenings(PRECOMMIT, PRECOMMIT.replace("entry: pytest", "entry: tox -e py"), path) == []
    assert _weakenings(PRECOMMIT, PRECOMMIT + "        stages: [manual]\n", path) == [
        "pytest is disabled (stages: [manual])"
    ]


def test_unreadable_or_unrelated_files_report_nothing():
    disabled = WORKFLOW + "        if: false\n"
    assert control_flow_weakenings(PATH, b"\x00\xff\xfe", disabled.encode("utf-8")) == []
    assert _weakenings(WORKFLOW, disabled, "tox.ini") == []


@pytest.mark.parametrize("condition, never", [
    ("failure()", True),
    ("${{ cancelled() }}", True),
    ("!success()", True),
    ("failure() || cancelled()", True),
    ("fromJSON('false')", True),
    ("fromJSON('0')", True),
    ("fromJSON('null')", True),
    ("contains('', 'x')", True),
    ("startsWith('docs', 'test')", True),
    ("contains(github.event_name, 'push')", True),
    ("failure() || true", False),
    ("fromJSON('true')", False),
    ("fromJSON('{}')", False),
    ("endsWith('refs/heads/MAIN', 'main')", False),
    ("contains(github.event.pull_request.labels.*.name, 'skip-tests')", False),
])
def test_calls_fold_as_they_read_on_a_run_that_is_otherwise_green(condition, never):
    # A runner gated on failure() or cancelled() runs only once the check is
    # already red, so it can never turn a passing check red.
    assert _never_true(condition, "pull_request") is never


def test_the_runner_that_stopped_must_be_the_runner_that_was_parked():
    # The suite still runs as `pytest --cov`, and the push-only job never ran
    # on a pull request at base: nothing that ran was disabled.
    reworded = WORKFLOW.replace("- run: pytest\n", "- run: pytest --cov\n")
    benchmark = "  benchmark:\n    if: github.event_name == 'push'\n    steps:\n      - run: pytest benchmarks\n"
    assert _weakenings(WORKFLOW, reworded + benchmark) == []
    hooks = PRECOMMIT.replace("entry: pytest", "entry: pytest -x") + (
        "      - id: slow\n"
        "        entry: pytest tests/slow\n"
        "        language: system\n"
        "        stages: [manual]\n"
    )
    assert _weakenings(PRECOMMIT, hooks, ".pre-commit-config.yaml") == []
    # Rewording a runner as it is disabled still moves a site from live to dead.
    disabled = WORKFLOW.replace("- run: pytest\n", "- run: python -m pytest\n        if: false\n")
    assert _weakenings(WORKFLOW, disabled) == ["pytest no longer runs, and python -m pytest is disabled (if: false)"]
    # Re-homing the live runner while rewording an already-dead one moves none.
    e2e = WORKFLOW + "  e2e:\n    if: false\n    steps:\n      - run: pytest tests/e2e\n"
    rehomed = e2e.replace("      - run: pytest\n", "").replace("tests/e2e", "tests/e2e -q")
    assert _weakenings(e2e, rehomed) == []


def test_a_long_needs_chain_is_walked_without_recursion():
    # Listed from the top of the chain down, so no job's needs are judged yet
    # when it is reached: a recursive walk would take frames per link.
    links = 2000
    chain = "".join(f"  j{index}:\n    needs: j{index - 1}\n" for index in range(links, 0, -1))
    before = (
        "on: pull_request\njobs:\n"
        f"  test:\n    needs: j{links}\n    steps:\n      - run: pytest\n"
        + chain
        + "  j0:\n    runs-on: ubuntu-latest\n"
    )
    after = before.replace("  j0:\n", "  j0:\n    if: false\n")
    assert _weakenings(before, after) == ["pytest is disabled (job test needs a job that cannot run)"]


def test_reader_bounds_what_merge_keys_copy():
    # Each mapping merges the one before it, so the copies grow quadratically.
    chain = "a0: &a0\n  k0: v\n" + "".join(
        f"a{index}: &a{index}\n  <<: *a{index - 1}\n  k{index}: v\n" for index in range(1, 500)
    )
    assert _read_yaml(chain.encode("utf-8")) is None
    assert _read_yaml(b"a: &a\n  k: v\nb:\n  <<: *a\n") == {"a": {"k": "v"}, "b": {"k": "v"}}


def test_a_literal_no_float_can_hold_is_unknown_not_an_error():
    huge = "0x" + "f" * 300
    assert not _never_true(huge, "pull_request")
    assert _never_true(f"false && {huge}", "pull_request")


def test_a_trigger_block_past_any_real_event_count_binds_nothing():
    jobs = WORKFLOW[WORKFLOW.index("jobs:\n"):]
    before = "on:\n" + "".join(f"  event{index}:\n" for index in range(100)) + jobs
    # Bound to no event, an event condition is unknown and keeps the step
    # live, while a literal false still folds.
    assert _weakenings(before, before + "        if: github.event_name == 'push'\n") == []
    assert _weakenings(before, before + "        if: false\n") == ["pytest is disabled (if: false)"]


# --- #196 191.5: which steps are runner sites ------------------------------------------

def _with_step(step, condition=None):
    if condition is not None:
        step = step.replace("      - ", f"      - if: {condition}\n        ", 1)
    return WORKFLOW + step


@pytest.mark.parametrize("step", [
    "      - run: pip install pytest pytest-cov\n",
    "      - run: python -m pip install --upgrade tox\n",
    "      - run: npm install --save-dev jest\n",
    "      - run: echo \"pytest_args=-x\" >> $GITHUB_OUTPUT\n",
    "      - run: |\n          cat <<EOF >> $GITHUB_STEP_SUMMARY\n          Run pytest locally first.\n          EOF\n",
    "      - run: ./deploy-majestic.sh\n",
    "      - run: rm -rf .tox\n",
    "      - uses: pmeier/pytest-results-action@v0\n        with:\n          path: junit.xml\n",
    "      - uses: wntrblm/nox@2024.10.09\n",
    "      - uses: ./.github/actions/pytest\n",
])
def test_switching_off_a_step_that_runs_no_runner_disables_nothing(step):
    assert _read_yaml(_with_step(step, "false").encode("utf-8")) is not None
    assert _weakenings(_with_step(step), _with_step(step, "false")) == []


@pytest.mark.parametrize("step, site", [
    # The action's name and one of its inputs both name a runner.
    ("      - uses: mattallty/jest-github-action@v1\n        with:\n          test-command: npm test\n",
     "mattallty/jest-github-action@v1"),
    ("      - uses: fedora-python/tox-github-action@main\n        with:\n          tox_env: py312\n",
     "fedora-python/tox-github-action@main"),
    ("      - uses: some-org/pytest-action@v2\n        with:\n          args: [pytest, -x]\n",
     "some-org/pytest-action@v2"),
    # Every other wrapper keeps its runner.
    ("      - run: docker compose run --rm web pytest\n", "docker compose run --rm web pytest"),
    ("      - run: pip install -e . && python -m pytest\n", "pip install -e . && python -m pytest"),
])
def test_switching_off_a_step_that_runs_a_runner_disables_it(step, site):
    assert _weakenings(_with_step(step), _with_step(step, "false")) == [f"{site} is disabled (if: false)"]


def test_an_action_whose_name_holds_no_runner_is_not_a_site_whatever_it_runs():
    # The ruling excludes; it adds no site the runner check did not make.
    step = "      - uses: nick-fields/retry@v3\n        with:\n          command: pytest\n"
    assert _weakenings(_with_step(step), _with_step(step, "false")) == []


def test_an_echo_no_longer_hides_a_runner_reworded_and_disabled():
    # 191.8: the decoy names the runner without running it.
    disabled = WORKFLOW.replace("- run: pytest\n", "- run: python -m pytest\n        if: false\n")
    assert _weakenings(WORKFLOW, disabled + "      - run: echo pytest\n") == [
        "pytest no longer runs, and python -m pytest is disabled (if: false)"
    ]
    # A decoy that does run the runner still hides it: row 112's residual.
    assert _weakenings(WORKFLOW, disabled + "      - run: pytest --version\n") == []


def test_an_echo_entry_is_not_a_test_hook():
    path = ".pre-commit-config.yaml"
    decoy = PRECOMMIT.replace("entry: pytest", "entry: echo pytest")
    assert _weakenings(PRECOMMIT, decoy, path) == ["no pre-commit hook entry invokes a recognised test runner any more (was: pytest)"]
    installer = PRECOMMIT.replace("entry: pytest", "entry: pip install pytest")
    assert _weakenings(PRECOMMIT, installer, path) == ["no pre-commit hook entry invokes a recognised test runner any more (was: pytest)"]


# --- #196 191.9 and 191.2(d): events that never fire for a pull request ------------------

@pytest.mark.parametrize("trigger, events", [
    # Activity types: only opened, synchronize and reopened run on a PR's commits.
    ({"pull_request": {"types": ["closed"]}}, []),
    ({"pull_request": {"types": "closed"}}, []),
    ({"pull_request": {"types": ["labeled", "ready_for_review"]}}, []),
    ({"pull_request_target": {"types": ["closed"]}}, []),
    ({"pull_request": {"types": ["opened"]}}, ["pull_request"]),
    ({"pull_request": {"types": ["labeled", "synchronize"]}}, ["pull_request"]),
    ({"pull_request": {"types": []}}, ["pull_request"]),
    ({"pull_request": {"types": {"closed": None}}}, ["pull_request"]),
    ({"pull_request": None}, ["pull_request"]),
    # A path filter that leaves no file to fire on.
    ({"pull_request": {"paths-ignore": ["**"]}}, []),
    ({"pull_request": {"paths-ignore": "**"}}, []),
    ({"pull_request": {"paths": ["!docs/**", "!*.md"]}}, []),
    ({"pull_request_target": {"paths-ignore": ["docs/**", "**"]}}, []),
    ({"push": {"paths-ignore": ["**"]}}, []),
    ({"push": {"branches": ["**"], "paths": ["!**"]}}, []),
    ({"pull_request": {"paths-ignore": ["docs/**"]}}, ["pull_request"]),
    ({"pull_request": {"paths": ["src/**", "!src/docs/**"]}}, ["pull_request"]),
    ({"pull_request": {"paths-ignore": ["**/*.md"]}}, ["pull_request"]),
    ({"pull_request": {"paths": []}}, ["pull_request"]),
    ({"push": None, "pull_request": {"types": ["closed"]}}, ["push"]),
    ({"pull_request": {"types": ["closed"]}, "merge_group": None}, ["merge_group"]),
])
def test_an_event_that_never_fires_for_a_pull_request_is_dead(trigger, events):
    assert _pr_events(trigger) == events


@pytest.mark.parametrize("filters, cause", [
    ("    types: [closed]\n", "pytest is disabled (no trigger runs it on a pull request)"),
    ("    paths-ignore: ['**']\n", "pytest is disabled (no trigger runs it on a pull request)"),
    ("    paths: ['!docs/**']\n", "pytest is disabled (no trigger runs it on a pull request)"),
])
def test_a_pull_request_trigger_that_never_fires_disables_the_suite(filters, cause):
    after = WORKFLOW.replace("  pull_request:\n", "  pull_request:\n" + filters)
    assert _weakenings(WORKFLOW, after) == [cause]


@pytest.mark.parametrize("filters", [
    "    types: [opened]\n",
    "    types: [opened, synchronize, reopened, closed]\n",
    "    paths-ignore: ['docs/**']\n",
    "    paths: ['src/**', 'tests/**']\n",
])
def test_a_pull_request_trigger_that_still_fires_keeps_the_suite(filters):
    after = WORKFLOW.replace("  pull_request:\n", "  pull_request:\n" + filters)
    assert _weakenings(WORKFLOW, after) == []


# --- #196 191.7 and 191.8: what the reasons claim ---------------------------------------

def test_a_reworded_and_disabled_runner_names_both_commands():
    # Text alone cannot prove the two are one site, so the reason names the
    # runner that stopped and the one that was parked; with several stopped,
    # the first in sort order, not in file order, as for the disabled command.
    before = WORKFLOW.replace("      - run: pytest\n", "      - run: tox -e py\n      - run: pytest\n")
    after = WORKFLOW.replace("- run: pytest\n", "- run: python -m pytest\n        if: false\n")
    assert _weakenings(before, after) == ["pytest no longer runs, and python -m pytest is disabled (if: false)"]
    # A runner disabled as written keeps the one-command reason.
    assert _weakenings(WORKFLOW, WORKFLOW + "        if: false\n") == ["pytest is disabled (if: false)"]


def test_a_hook_that_keeps_its_id_but_runs_no_runner_is_a_removal():
    # The id and the name are the author's to choose: only the entry counts,
    # and the reason claims only that no entry invokes a recognised runner.
    path = ".pre-commit-config.yaml"
    after = PRECOMMIT.replace("entry: pytest", "entry: ./scripts/check.sh")
    assert _weakenings(PRECOMMIT, after, path) == [
        "no pre-commit hook entry invokes a recognised test runner any more (was: pytest)"
    ]
    remote = "repos:\n  - repo: https://github.com/example/hooks\n    rev: v1.0.0\n    hooks:\n      - id: pytest\n"
    assert _weakenings(PRECOMMIT, remote, path) == [
        "no pre-commit hook entry invokes a recognised test runner any more (was: pytest)"
    ]
    # With several runner entries, the first in sort order, not in file order.
    tox = "      - id: tox\n        entry: tox -e py\n        language: system\n"
    tox_first = PRECOMMIT.replace("      - id: pytest\n", tox + "      - id: pytest\n")
    assert _weakenings(tox_first, "repos: []\n", path) == [
        "no pre-commit hook entry invokes a recognised test runner any more (was: pytest)"
    ]


# --- #196 191.3: a head the reader declines -----------------------------------------------

_DEEP = "".join(" " * level + f"k{level}:\n" for level in range(60)) + " " * 60 + "v\n"


@pytest.mark.parametrize("data, cause", [
    (b"jobs:\n  test:\n    if: !!bool false\n", "a YAML tag"),
    (b"!tag key: value\n", "a YAML tag"),
    (b"a: !b: |\n  text\n", "a YAML tag"),
    (b"jobs:\n\ttest:\n", "tab indentation"),
    (b"%YAML 1.2\n---\njobs: {}\n", "a YAML directive"),
    (b"a: 1\n---\nb: 2\n", "a second YAML document"),
    (b"a: 1\n...\nb: 2\n", "a second YAML document"),
    (b"a: [1,\n", "an unclosed flow collection"),
    (b"a: [1, ]]\n", "an unbalanced flow collection"),
    (b"a: [1] x\n", "a flow collection the reader does not take"),
    (b"[pytest]\naddopts = -q\n", "a mapping key the reader does not take"),
    (b"a: & v\n", "an empty anchor"),
    (b"  a: 1\nb: 2\n", "indentation the reader cannot place"),
    (_DEEP.encode("utf-8"), "nesting deeper than 48 levels"),
    (b"a: 1\n- b\n", "a sequence item among mapping keys"),
    (b"a: &x 1\nb:\n  <<: *x\n", "a merge key whose value is not a mapping"),
    (b"a: b: |\n  text\n", "text before a block scalar indicator"),
    (b"jobs:\n  test:\n    if: *missing\n", "an alias to an undefined anchor"),
    (b"a: 'x\n", "an unclosed quoted scalar"),
    (b"a: @x\n", "a reserved indicator"),
    (b"a: |x\n", "a block scalar indicator the reader does not take"),
    (b"a: " + b"x" * 1_000_000 + b"\n", "over 1000000 bytes"),
])
def test_reader_names_what_it_declines(data, cause):
    assert _read_document(data) == (None, cause)
    assert _read_yaml(data) is None


def test_reader_names_the_merge_budget():
    chain = "a0: &a0\n  k0: v\n" + "".join(
        f"a{index}: &a{index}\n  <<: *a{index - 1}\n  k{index}: v\n" for index in range(1, 500)
    )
    assert _read_document(chain.encode("utf-8")) == (None, "merge keys that copy over 100000 entries")


@pytest.mark.parametrize("data", [None, b"", b"# a comment\n\n"])
def test_nothing_to_read_is_not_declined(data):
    assert _read_document(data) == (None, None)


def test_a_document_end_marker_ends_the_document():
    # `...` closes the document, so only blank lines and comments may follow;
    # attrs ends its workflows that way.
    tree = _read_yaml(("---\n" + WORKFLOW + "...\n# trailing comment\n\n").encode("utf-8"))
    assert tree == _read_yaml(WORKFLOW.encode("utf-8"))
    marked = "---\n" + WORKFLOW + "...\n"
    assert _weakenings(marked, marked.replace("- run: pytest\n", "- run: pytest\n        if: false\n")) == [
        "pytest is disabled (if: false)"
    ]
    assert _weakenings(WORKFLOW, marked) == []


def test_a_head_the_reader_declines_is_out_of_reach():
    tagged = WORKFLOW.replace("- run: pytest\n", "- run: pytest\n        if: !!bool false\n")
    assert _weakenings(WORKFLOW, tagged) == [
        "runner sites can no longer be read at head (a YAML tag); base ran: pytest"
    ]
    # With several live runners, the first in sort order.
    two = WORKFLOW.replace("      - run: pytest\n", "      - run: tox -e py\n      - run: pytest\n")
    assert _weakenings(two, two + "---\n") == [
        "runner sites can no longer be read at head (a second YAML document); base ran: pytest"
    ]
    # The hook inventory too.
    path = ".pre-commit-config.yaml"
    assert _weakenings(PRECOMMIT, PRECOMMIT.replace("entry: pytest", "entry: !!str pytest"), path) == [
        "runner sites can no longer be read at head (a YAML tag); base ran: pytest"
    ]


def test_a_declined_head_needs_a_base_that_ran_a_suite():
    tagged = "on: !!str pull_request\n"
    # No live runner site at base: a dead one, or none at all.
    dead = WORKFLOW + "        if: false\n"
    assert _weakenings(dead, dead + tagged) == []
    no_runner = WORKFLOW.replace("- run: pytest\n", "- run: make docs\n")
    assert _weakenings(no_runner, no_runner + tagged) == []
    # A base side the reader declines too, and a head side holding no YAML.
    assert _weakenings(WORKFLOW + tagged, WORKFLOW + tagged + "# edited\n") == []
    assert _weakenings(WORKFLOW, "# the workflow is retired\n") == []


def test_became_unanalysable_reads_only_its_own_reason():
    assert became_unanalysable("runner sites can no longer be read at head (a YAML tag); base ran: pytest")
    assert not became_unanalysable("pytest is disabled (if: false)")
    assert not became_unanalysable("no pre-commit hook entry invokes a recognised test runner any more (was: pytest)")
    assert not became_unanalysable("pytest || true")


def _ci_findings(before, after, path=PATH):
    changes = [FileChange(path, "modified", before.encode("utf-8"), after.encode("utf-8"))]
    findings = analyze(changes, Config(), Contract(), [], datetime.date(2026, 10, 4))[1]
    return [f for f in findings if f.rule == "CI_WORKFLOW_TOUCHED"]


def test_an_unreadable_head_is_not_called_a_weakened_command():
    tagged = WORKFLOW.replace("- run: pytest\n", "- run: pytest\n        if: !!bool false\n")
    (finding,) = _ci_findings(WORKFLOW, tagged)
    assert finding.severity == "high"
    assert finding.message == (
        "CI configuration changed; runner sites can no longer be read at head (a YAML tag); base ran: pytest"
    )
    assert finding.after.text == "runner sites can no longer be read at head (a YAML tag); base ran: pytest"
    # A weakened command beside it is still named as one.
    swallowed = tagged.replace("- run: pytest\n", "- run: pytest || true\n")
    (finding,) = _ci_findings(WORKFLOW, swallowed)
    assert finding.message == "CI configuration changed; test command weakened: - run: pytest || true"
    # Even when the unreadable reason sorts first.
    tox = WORKFLOW + "      - run: |\n          tox -e py\n"
    late = tox.replace("tox -e py\n", "tox -e py || true\n") + "        if: !!bool false\n"
    (finding,) = _ci_findings(tox, late)
    assert finding.message == "CI configuration changed; test command weakened: tox -e py || true"

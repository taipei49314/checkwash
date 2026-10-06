"""GitLab job swallow and reachability: a runner job that can no longer fail the pipeline (#214).

In `.gitlab-ci.yml` a test job stops failing the pipeline without any change
to its `script:` lines: `allow_failure: true` (or `exit_codes`) lets it fail
and stay green, and `when: manual` or a `rules:` entry `when: never` stops it
from running on its own. The runner-site reader read GitHub workflows and
pre-commit configs only, so all four passed at warn while GitHub's
`continue-on-error: true` blocked.

Ruling (2026-10-03, #196): these count only on jobs whose `script:` passes
the runner-site predicate; there is no global token, so a lint job that
gains `allow_failure: true` stays at warn. `.gitlab-ci.yml` is now read as an
inventory of runner sites, one per `script:` command that invokes a test
runner, live when its job can fail a green pipeline.
"""
import datetime

import pytest

from checkwash.change import FileChange
from checkwash.ci_control_flow import _gitlab_jobs, _gitlab_sites, _read_yaml, control_flow_weakenings, holds_runner_site
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze

TODAY = datetime.date(2026, 10, 6)
PATH = ".gitlab-ci.yml"
BASE = """stages:
  - lint
  - test

lint:
  stage: lint
  image: python:3.12
  script:
    - pip install ruff
    - ruff check .

test:
  stage: test
  image: python:3.12
  script:
    - pip install -e .[test]
    - pytest
"""


def outcome(before, after, path=PATH):
    status = "added" if before is None else "deleted" if after is None else "modified"
    change = FileChange(path, status, None if before is None else before.encode(),
                        None if after is None else after.encode())
    _ir, findings, verdict = analyze([change], Config(), Contract(), [], TODAY)
    return verdict, [(f.rule, f.severity, f.escalators, f.message) for f in findings]


def add(text, job="test", base=BASE):
    """`base` with `text` appended to `job`'s mapping."""
    marker = {"test": "    - pytest\n", "lint": "    - ruff check .\n"}[job]
    assert base.count(marker) == 1
    return base.replace(marker, marker + text)


def weakened(reason):
    return ("block", [("CI_WORKFLOW_TOUCHED", "high", ["CI_TEST_COMMAND_WEAKENED"],
                       f"CI configuration changed; test command weakened: {reason}")])


WARN = ("pass", [("CI_WORKFLOW_TOUCHED", "warn", [], "CI configuration changed")])


def sites(text):
    return _gitlab_sites(_read_yaml(text.encode()))


# --- the issue's rows ----------------------------------------------------------------

@pytest.mark.parametrize("text, reason", [
    ("  allow_failure: true\n", "pytest can no longer fail the pipeline (job test allow_failure: true)"),
    ("  allow_failure:\n    exit_codes: [1]\n", "pytest can no longer fail the pipeline (job test allow_failure: exit_codes)"),
    ("  when: manual\n", "pytest is disabled (job test when: manual)"),
    ("  rules:\n    - when: never\n", "pytest is disabled (job test rules: when: never)"),
], ids=["G1_allow_failure", "G2_exit_codes", "G3_manual", "G4_rules_never"])
def test_a_runner_job_that_can_no_longer_fail_the_pipeline_is_a_weakened_command(text, reason):
    assert outcome(BASE, add(text)) == weakened(reason)


def test_g7_a_lint_job_that_may_fail_stays_at_warn():
    """No global token: the job's `script:` must invoke a test runner."""
    assert outcome(BASE, add("  allow_failure: true\n", job="lint")) == WARN


def test_a_test_job_already_allowed_to_fail_at_base_is_no_event():
    allowed = add("  allow_failure: true\n")
    assert outcome(allowed, allowed.replace("python:3.12", "python:3.13")) == WARN


@pytest.mark.parametrize("text", ["  when: manual\n", "  allow_failure: true\n", "  rules:\n    - when: never\n"])
def test_a_test_job_that_loses_its_idle_setting_is_strengthened(text):
    assert outcome(add(text), BASE) == WARN


def test_g5c_a_swallow_on_the_runner_line_still_blocks_as_before():
    assert outcome(BASE, BASE.replace("    - pytest\n", "    - pytest || true\n")) == weakened("- pytest || true")


def test_github_continue_on_error_stays_a_global_token():
    """G9 is out of scope: the ruling keeps GitHub's token global (D-052)."""
    workflow = ("on: [push, pull_request]\njobs:\n  lint:\n    runs-on: ubuntu-latest\n    steps:\n"
                "      - run: ruff check .\n")
    after = workflow.replace("      - run: ruff check .\n", "      - run: ruff check .\n        continue-on-error: true\n")
    verdict, findings = outcome(workflow, after, ".github/workflows/ci.yml")
    assert verdict == "block" and findings[0][2] == ["CI_TEST_COMMAND_WEAKENED"]


# --- what a job's `when:` and `allow_failure:` mean ----------------------------------------

@pytest.mark.parametrize("text, live", [
    ("", True),
    ("  when: on_success\n", True),
    ("  when: always\n", True),
    ("  when: delayed\n  start_in: 5 minutes\n", True),
    ("  when: manual\n", False),
    ("  when: never\n", False),
    # runs only once an earlier job has failed, as `failure()` reads on a green run
    ("  when: on_failure\n", False),
    ("  allow_failure: false\n", True),
    ("  allow_failure: true\n", False),
    # GitLab's parser reads YAML 1.1 booleans
    ("  allow_failure: yes\n", False),
    ("  allow_failure: On\n", False),
    # a quoted string is no boolean: GitLab rejects the configuration
    ('  allow_failure: "true"\n', True),
    ("  allow_failure:\n    exit_codes: 1\n", False),
    ("  allow_failure:\n    exit_codes: []\n", True),
], ids=lambda value: value if isinstance(value, bool) else value.strip().replace("\n", " ") or "nothing")
def test_a_jobs_own_keys_decide_whether_it_can_fail_the_pipeline(text, live):
    live_sites, dead_sites = sites(add(text))
    assert (live_sites == ["pytest"]) is live
    assert (len(dead_sites) == 1) is not live


def test_the_cause_names_the_job_and_the_key():
    assert sites(add("  when: manual\n")) == ([], [("pytest", "job test when: manual")])
    assert sites(add("  allow_failure:\n    exit_codes: [1, 2]\n")) == ([], [("pytest", "job test allow_failure: exit_codes")])


# --- rules: ------------------------------------------------------------------------------

@pytest.mark.parametrize("rules, live", [
    # a rule with a condition may match; its `when` defaults to the job's
    ("    - if: $CI_COMMIT_BRANCH == 'main'\n", True),
    ("    - if: $CI_PIPELINE_SOURCE == 'merge_request_event'\n      when: manual\n", False),
    ("    - changes: [src/**/*]\n      when: never\n", False),
    # a conditional never, then a rule that always matches and runs it
    ("    - if: $CI_COMMIT_TAG\n      when: never\n    - when: always\n", True),
    ("    - if: $CI_COMMIT_TAG\n      when: never\n    - when: on_success\n", True),
    # the first rule with no condition always matches: no later rule is reached
    ("    - when: never\n    - when: always\n", False),
    ("    - when: manual\n    - if: $CI_COMMIT_TAG\n", False),
    ("    - allow_failure: true\n", False),
    ("    - if: $CI_COMMIT_TAG\n      allow_failure: true\n    - allow_failure: false\n", True),
    # no rule matches: the job is not added
    ("    - if: $CI_COMMIT_TAG\n      when: never\n    - exists: [Dockerfile]\n      when: manual\n", False),
], ids=["if_only", "if_manual", "changes_never", "never_then_always", "never_then_on_success",
        "unconditional_never_first", "unconditional_manual_first", "rule_allow_failure",
        "conditional_allow_failure_then_counted", "every_rule_idle"])
def test_each_rule_that_may_match_adds_the_job_its_own_way(rules, live):
    live_sites, dead_sites = sites(add("  rules:\n" + rules))
    assert (live_sites == ["pytest"]) is live, (live_sites, dead_sites)


def test_a_rule_takes_the_jobs_when_and_allow_failure_where_it_sets_none():
    assert sites(add("  when: manual\n  rules:\n    - if: $CI_COMMIT_TAG\n    - when: on_success\n"))[0] == ["pytest"]
    assert sites(add("  allow_failure: true\n  rules:\n    - if: $CI_COMMIT_TAG\n"))[1] == [
        ("pytest", "job test rules: allow_failure: true")]


@pytest.mark.parametrize("rules", ["  rules: []\n", "  rules: always\n", "  rules:\n    - '$CI_COMMIT_TAG'\n"])
def test_a_rules_shape_the_reader_does_not_take_keeps_the_job_live(rules):
    assert sites(add(rules))[0] == ["pytest"]


@pytest.mark.parametrize("workflow, live", [
    ("workflow:\n  rules:\n    - when: never\n", False),
    ("workflow:\n  rules:\n    - if: $CI_COMMIT_TAG\n      when: never\n", False),
    ("workflow:\n  rules:\n    - if: $CI_COMMIT_TAG\n      when: never\n    - when: always\n", True),
    # the first rule with no condition always matches: no later rule is reached
    ("workflow:\n  rules:\n    - when: never\n    - when: always\n", False),
    ("workflow:\n  rules:\n    - if: $CI_MERGE_REQUEST_IID\n", True),
    ("workflow:\n  name: tests\n", True),
], ids=["never", "only_conditional_never", "never_then_always", "unconditional_never_first", "conditional", "no_rules"])
def test_workflow_rules_that_only_keep_the_pipeline_from_running_kill_every_site(workflow, live):
    live_sites, dead_sites = sites(workflow + BASE)
    assert (live_sites == ["pytest"]) is live
    if not live:
        assert dead_sites == [("pytest", "workflow rules: when: never")]


def test_workflow_never_added_is_a_weakened_command():
    assert outcome(BASE, "workflow:\n  rules:\n    - when: never\n" + BASE) == weakened(
        "pytest is disabled (workflow rules: when: never)")


# --- extends: and hidden jobs ----------------------------------------------------------------

TEMPLATED = """.tests:
  image: python:3.12
  script:
    - pytest

test-py312:
  extends: .tests
"""


def test_a_job_runs_the_script_its_template_gives_it():
    assert sites(TEMPLATED) == (["pytest"], [])


def test_an_idle_key_on_the_job_or_its_template_is_read_through_extends():
    assert outcome(TEMPLATED, TEMPLATED.replace("  extends: .tests\n", "  extends: .tests\n  allow_failure: true\n")) == (
        weakened("pytest can no longer fail the pipeline (job test-py312 allow_failure: true)"))
    assert outcome(TEMPLATED, TEMPLATED.replace("    - pytest\n", "    - pytest\n  when: manual\n")) == (
        weakened("pytest is disabled (job test-py312 when: manual)"))


def test_extends_merges_templates_in_order_and_the_jobs_own_keys_last():
    tree = _read_yaml(b"""\
.a:
  when: manual
  retry: 1
  variables: {A: '1', B: '1'}
  script: [pytest]
.b:
  retry: 2
  variables: {B: '2'}
test:
  extends: [.a, .b]
  when: on_success
  variables: {C: '3'}
""")
    job = _gitlab_jobs(tree)["test"]
    assert job["when"] == "on_success"  # the job's own key wins
    assert job["retry"] == "2"  # the last template listed wins over the first
    assert job["variables"] == {"A": "1", "B": "2", "C": "3"}
    assert job["script"] == ["pytest"]
    assert "extends" not in job


def test_a_template_another_file_defines_adds_nothing_seen():
    assert sites("test:\n  extends: .included\n  script: [pytest]\n") == (["pytest"], [])


@pytest.mark.parametrize("text", [
    ".a:\n  extends: .b\n.b:\n  extends: .a\ntest:\n  extends: .a\n  script: [pytest]\n",
    "".join(f".t{i}:\n  extends: .t{i + 1}\n" for i in range(12)) + "test:\n  extends: .t0\n  script: [pytest]\n",
], ids=["loop", "deeper_than_gitlab_follows"])
def test_an_extends_chain_gitlab_rejects_leaves_the_job_out(text):
    assert "test" not in _gitlab_jobs(_read_yaml(text.encode()))


def test_merging_is_bounded_as_merge_keys_are():
    """Past the bound, the file is a shape the reader does not take, and nothing is judged."""
    variables = "".join(f"    V{i}: '{i}'\n" for i in range(1000))
    text = ".base:\n  script: [pytest]\n  variables:\n" + variables
    assert sites(text + "".join(f"job{i}:\n  extends: .base\n" for i in range(90)))[0] == ["pytest"] * 90
    assert sites(text + "".join(f"job{i}:\n  extends: .base\n" for i in range(101))) is None


def test_a_template_is_no_site_of_its_own():
    """A hidden job that a job extends runs only as that job."""
    assert sites(TEMPLATED.replace("  extends: .tests\n", "  extends: .tests\n  when: manual\n")) == (
        [], [("pytest", "job test-py312 when: manual")])


def test_a_job_hidden_with_a_leading_dot_is_disabled():
    """GitLab documents a leading `.` as the way to disable a job without deleting it."""
    assert outcome(BASE, BASE.replace("\ntest:\n", "\n.test:\n")) == weakened("pytest is disabled (hidden job .test)")


def test_templating_a_job_disables_nothing():
    """The job moves its script into a template it extends: the same site, live."""
    after = BASE.replace("\ntest:\n  stage: test\n", "\n.tests:\n  stage: test\n") + "\ntest:\n  extends: .tests\n"
    assert sites(after) == (["pytest"], [])
    assert outcome(BASE, after) == WARN


def test_an_anchored_template_merged_with_a_merge_key_is_read_by_the_yaml_reader():
    text = ".tests: &tests\n  script: [pytest]\n\ntest:\n  <<: *tests\n  allow_failure: true\n"
    assert sites(text)[1] == [("pytest", "hidden job .tests"), ("pytest", "job test allow_failure: true")]


# --- which commands are sites ------------------------------------------------------------------

def test_only_the_jobs_script_is_its_test_command():
    text = "test:\n  before_script: [pytest --version]\n  script: [ruff check .]\n  after_script: [pytest]\n"
    assert sites(text) == ([], [])


@pytest.mark.parametrize("script, commands", [
    ("  script: pytest -q\n", ["pytest -q"]),
    ("  script:\n    - |\n      pip install .\n      pytest -q\n", ["pip install . pytest -q"]),
    ("  script:\n    - tox -e py312\n    - pytest tests/unit\n", ["tox -e py312", "pytest tests/unit"]),
    ("  script:\n    - npm ci\n    - node --test\n", ["node --test"]),
    ("  script:\n    - echo pytest\n", []),
    ("  script:\n    - pip install pytest\n", []),
], ids=["string", "block_scalar", "two_runners", "node_test", "echo", "install"])
def test_each_script_command_that_invokes_a_runner_is_a_site(script, commands):
    assert sites("test:\n" + script)[0] == commands


@pytest.mark.parametrize("key", ["stages", "variables", "default", "include", "workflow", "image", "services",
                                 "cache", "before_script", "after_script"])
def test_a_global_key_is_no_job(key):
    assert key not in _gitlab_jobs({key: {"script": ["pytest"]}, "test": {"script": ["pytest"]}})


# --- the rules every runner-site file follows ----------------------------------------------------

def test_a_head_the_reader_declines_is_out_of_reach():
    """As for a workflow (#196 191.3): the base ran a live suite the head hides from the reader."""
    after = BASE.replace("    - pip install -e .[test]\n", "    - !reference [.setup, script]\n")
    assert outcome(BASE, after) == ("block", [(
        "CI_WORKFLOW_TOUCHED", "high", ["CI_BECAME_UNANALYSABLE"],
        "CI configuration changed; runner sites can no longer be read at head (a YAML tag); base ran: pytest")])


def test_a_base_the_reader_declines_is_not_judged():
    before = BASE.replace("    - pip install -e .[test]\n", "    - !reference [.setup, script]\n")
    assert control_flow_weakenings(PATH, before.encode(), add("  allow_failure: true\n", base=before).encode()) == []


def test_a_deleted_pipeline_whose_only_suite_is_a_site_ran_one():
    """Row 69's deletion rule: a job's `script:` command is a site, `node --test` included (#216)."""
    text = "test:\n  script:\n    - npm ci\n    - node --test\n"
    assert holds_runner_site(PATH, text.encode())
    verdict, findings = outcome(text, None)
    assert verdict == "block" and findings[0][2] == ["CI_TEST_COMMAND_WEAKENED"]


def test_only_the_root_pipeline_file_is_read():
    assert not holds_runner_site("ci/.gitlab-ci.yml", BASE.encode())
    assert control_flow_weakenings("ci/.gitlab-ci.yml", BASE.encode(), add("  when: manual\n").encode()) == []


def test_a_runner_reworded_as_its_job_is_disabled_names_both():
    after = add("  when: manual\n").replace("    - pytest\n", "    - python -m pytest\n")
    assert outcome(BASE, after) == weakened(
        "pytest no longer runs, and python -m pytest is disabled (job test when: manual)")

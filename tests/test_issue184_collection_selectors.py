"""#196 184.1 and 184.2: which runs a new pytest selector reaches, and what it can leave out.

184.1: explicit CLI targets (`pytest tests`) override testpaths, so the
resolved inventory withheld its whole proof from a repository whose CI passes
targets, and a first `addopts = "-m 'not slow'"` there passed. pytest still
prepends the root config's addopts to a targeted run: a new selector is now
judged against the base-suite tests beneath the targets, when discovery from
the targets finds the same root config on both sides. The settings proof
stays withheld for a targeted run.

184.2: a first config's option that leaves no test out (`-p no:cacheprovider`,
`--ignore=docs` with no tests in docs) blocked as a new selector. A path
option now counts only when it drops a base-suite test, and `-p no:` only for
a plugin outside a short list whose absence changes no outcome. Markers,
keywords, `--co`, `no:python`, `no:unittest` and unknown plugins keep
blocking.

184.3: moving `-m 'not slow'` from the workflow's command into addopts blocked
as a new selector, although every run passed it before and after. An option
every base-side pytest command in the runner files carried, which the head
commands dropped and nothing else, is now not new. Every other shape is
reported, and so is a migration a command this reader cannot parse leaves
unproven.
"""
import datetime
import json

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze


CARRIERS = ["pytest.ini", "tox.ini", "setup.cfg", "pyproject.toml"]
PRODUCTION = {"app/__init__.py": b"",
              "app/billing.py": b"def invoice_total(items):\n    return sum(i['price'] * i['qty'] for i in items)\n"}
TEST = (b"import pytest\nfrom app.billing import invoice_total\n\n\n@pytest.mark.slow\n"
        b"def test_invoice_total():\n    assert invoice_total([]) == 0\n")
SELECTOR = "-m 'not slow'"


def source(path, settings):
    section = "[tool.pytest.ini_options]" if path == "pyproject.toml" else "[tool:pytest]" if path == "setup.cfg" else "[pytest]"
    return (section + "\n" + "".join(f"{key} = {json.dumps(value) if path == 'pyproject.toml' else value}\n"
                                     for key, value in settings.items())).encode()


def workflow(*commands):
    return ("name: ci\non: [pull_request]\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n"
            + "".join(f"      - run: {command}\n" for command in commands)).encode()


def judge(before, after, untouched=None):
    """CI_WORKFLOW_TOUCHED (severity, message) pairs and the verdict over a complete head snapshot."""
    changes = [FileChange(path, "added" if path not in before else "deleted" if path not in after else "modified",
                          before.get(path), after.get(path))
               for path in sorted(before.keys() | after.keys()) if before.get(path) != after.get(path)]
    return judge_changes(changes, {**(untouched or {}), **after})


def judge_changes(changes, head):
    snapshot = {**PRODUCTION, "tests/test_billing.py": TEST, **head}
    _ir, findings, verdict = analyze(changes, Config(), Contract(), [], datetime.date(2026, 10, 4),
                                     root_reader=snapshot.get, root_path_lister=lambda: sorted(snapshot),
                                     root_batch_reader=lambda paths: {p: snapshot.get(p) for p in paths})
    return [(f.severity, f.message) for f in findings if f.rule == "CI_WORKFLOW_TOUCHED"], verdict


# --- 184.1: a targeted run inherits the root config's addopts ----------------------------

@pytest.mark.parametrize("carrier", CARRIERS)
@pytest.mark.parametrize("command", ["pytest tests", "python -m pytest tests/test_billing.py", "pytest tests -q"])
def test_a_first_selector_reaches_a_targeted_run(carrier, command):
    hits, verdict = judge({}, {carrier: source(carrier, {"addopts": SELECTOR})},
                          {".github/workflows/ci.yml": workflow(command)})
    assert hits == [("high", "CI configuration changed; test command weakened: "
                             "resolved pytest collection option introduced: -m not slow")]
    assert verdict == "block"


def test_a_targeted_run_with_no_base_test_beneath_its_targets_is_not_reached():
    hits, verdict = judge({}, {"pytest.ini": source("pytest.ini", {"addopts": SELECTOR})},
                          {".github/workflows/ci.yml": workflow("pytest integration")})
    assert [severity for severity, _ in hits] == ["warn"]
    assert verdict == "pass"


def test_a_nested_config_governing_the_targets_withholds_the_proof():
    # Discovery from `tests` finds tests/pytest.ini, so the root addopts never
    # reach that run.
    nested = {".github/workflows/ci.yml": workflow("pytest tests"), "tests/pytest.ini": b"[pytest]\n"}
    hits, _ = judge({}, {"pytest.ini": source("pytest.ini", {"addopts": SELECTOR})}, nested)
    assert [severity for severity, _ in hits] == ["warn"]


def test_a_nested_config_the_diff_deletes_withholds_the_proof():
    # The same root config must govern the targeted run on both sides; at base
    # tests/pytest.ini did.
    runners = {".github/workflows/ci.yml": workflow("pytest tests")}
    hits, _ = judge({"tests/pytest.ini": b"[pytest]\n"}, {"pytest.ini": source("pytest.ini", {"addopts": SELECTOR})},
                    runners)
    assert [severity for severity, _ in hits] == ["warn"]


def test_a_targetless_run_beside_a_targeted_one_is_reached():
    runners = {".github/workflows/ci.yml": workflow("pytest integration"), "scripts/test.sh": b"#!/bin/sh\npytest\n"}
    hits, _ = judge({}, {"pytest.ini": source("pytest.ini", {"addopts": SELECTOR})}, runners)
    assert [severity for severity, _ in hits] == ["high"]


@pytest.mark.parametrize("settings", [{"python_files": "check_*.py"}, {"testpaths": "checks"}])
def test_the_settings_proof_stays_withheld_for_a_targeted_run(settings):
    # Explicit targets override testpaths, and pytest applies python_files
    # only to the files it walks into, not to a file named as a target.
    hits, _ = judge({}, {"pytest.ini": source("pytest.ini", settings)},
                    {".github/workflows/ci.yml": workflow("pytest tests")})
    assert [severity for severity, _ in hits] == ["warn"]


# --- 184.2: a path option or a plugin counts by what it can leave out ---------------------

@pytest.mark.parametrize("carrier", CARRIERS)
@pytest.mark.parametrize("option", [
    "-p no:cacheprovider", "-pno:cacheprovider", "-p no:faulthandler", "-p no:pastebin", "-p no:stepwise",
    "--ignore=docs", "--ignore docs", "--ignore=tests/test_other.py", "--ignore-glob=docs/*",
    "--ignore-glob=*_slow.py", "--deselect tests/test_billing.py::test_other",
    "--deselect=tests/test_other.py",
])
def test_a_first_option_that_leaves_no_test_out_stays_warn(carrier, option):
    hits, verdict = judge({}, {carrier: source(carrier, {"addopts": option})}, {"docs/conf.py": b"x = 1\n"})
    assert [severity for severity, _ in hits] == ["warn"], option
    assert verdict == "pass"


@pytest.mark.parametrize("carrier", CARRIERS)
@pytest.mark.parametrize("option", [
    "--ignore=tests", "--ignore=tests/", "--ignore=./tests/test_billing.py", "--ignore=.",
    "--ignore-glob=tests/*", "--ignore-glob=test*", "--ignore-glob=tests", "--ignore-glob=*_billing.py",
    "--deselect tests/test_billing.py", "--deselect tests/test_billing.py::test_invoice",
    "--deselect=tests/test_billing.py::test_invoice_total[1]",
    "-p no:python", "-p no:unittest", "-p no:warnings", "-p no:doctest", "-p no:randomly",
    SELECTOR, "-k invoice", "--co",
])
def test_a_first_option_that_can_leave_a_test_out_blocks(carrier, option):
    hits, verdict = judge({}, {carrier: source(carrier, {"addopts": option})})
    assert [severity for severity, _ in hits] == ["high"], option
    assert verdict == "block"


def test_the_reported_option_is_one_that_leaves_a_test_out():
    hits, _ = judge({}, {"pytest.ini": source("pytest.ini", {"addopts": "--ignore=docs " + SELECTOR})})
    assert hits == [("high", "CI configuration changed; test command weakened: "
                             "resolved pytest collection option introduced: -m not slow")]


def test_an_existing_config_gaining_a_path_option_still_blocks_through_the_scanners():
    # Disclosed asymmetry: the token scan and the syntax scanner read the
    # existing config's added option and do not evaluate it (#196 184.2).
    before = {"pytest.ini": source("pytest.ini", {"addopts": "-ra"})}
    after = {"pytest.ini": source("pytest.ini", {"addopts": "-ra --ignore=docs"})}
    hits, verdict = judge(before, after, {"docs/conf.py": b"x = 1\n"})
    assert [severity for severity, _ in hits] == ["high"]
    assert verdict == "block"


# --- 184.3: an option moved out of every run's command into the config ----------------------

CI = ".github/workflows/ci.yml"
QUIET = [("warn", "CI configuration changed")]
REPORTED = ("high", "CI configuration changed; test command weakened: "
                    "resolved pytest collection option introduced: -m not slow")


def moved(before, after, config=None, untouched=None, *, carrier="pytest.ini", existing=None):
    """The diff that moves the selector out of these runs' commands into a config."""
    base = {carrier: source(carrier, existing)} if existing else {}
    settings = {**(existing or {}), "addopts": config or SELECTOR}
    return judge({**base, **before}, {**after, carrier: source(carrier, settings)}, untouched)


@pytest.mark.parametrize("carrier", CARRIERS)
@pytest.mark.parametrize("existing", [None, {"python_files": "test_*.py"}])
@pytest.mark.parametrize("command", ["pytest", "python -m pytest", "pytest tests", "uv run pytest -q"])
def test_a_selector_moved_out_of_every_run_stays_warn(carrier, existing, command):
    # W1 (a first config) and W3 (an existing one) in the rulings. Every run
    # passes the selector before and after; SPEC §2b: moving a filtering
    # addopts between files is not a weakened test command.
    hits, verdict = moved({CI: workflow(f"{command} {SELECTOR}")}, {CI: workflow(command)},
                          carrier=carrier, existing=existing)
    assert hits == QUIET * 2
    assert verdict == "pass"


def test_every_run_across_the_runner_files_carried_it():
    script = b"#!/bin/sh\nset -e\npytest " + SELECTOR.encode() + b" tests\n"
    hits, verdict = moved({CI: workflow(f"pytest {SELECTOR}", f"python -m pytest {SELECTOR} --doctest-modules"),
                           "scripts/test.sh": script},
                          {CI: workflow("pytest", "python -m pytest --doctest-modules"),
                           "scripts/test.sh": script.replace(b" " + SELECTOR.encode(), b"")})
    assert hits == QUIET * 3
    assert verdict == "pass"


def test_every_option_the_commands_dropped_moves_with_the_selector():
    # `-p no:cacheprovider` leaves no test out, so it is not reported, but the
    # head commands dropped it too: both moved.
    hits, verdict = moved({CI: workflow(f"pytest -p no:cacheprovider {SELECTOR}")}, {CI: workflow("pytest")},
                          f"-p no:cacheprovider {SELECTOR}")
    assert hits == QUIET * 2
    assert verdict == "pass"


def test_a_step_name_or_a_cache_key_is_not_a_run():
    def named(command):
        return ("name: ci\non: [pull_request]\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n"
                "      - uses: actions/cache@v4\n        with:\n          key: pytest-${{ runner.os }}\n"
                f"      - name: Run pytest\n        run: {command}\n").encode()

    hits, verdict = moved({CI: named(f"pytest {SELECTOR}")}, {CI: named("pytest")})
    assert verdict == "pass"


@pytest.mark.parametrize("before, after, untouched", [
    # The two-invocation counter-case: the other run collected the marked
    # test at base, and the selector the config gains now deselects it.
    ({CI: workflow(f"pytest {SELECTOR}", "pytest")}, {CI: workflow("pytest", "pytest")}, {}),
    ({CI: workflow(f"pytest {SELECTOR}")}, {CI: workflow("pytest")}, {".github/workflows/nightly.yml": workflow("pytest")}),
    ({CI: workflow(f"pytest {SELECTOR}")}, {CI: workflow("pytest")}, {"scripts/test.sh": b"#!/bin/sh\npytest\n"}),
    ({CI: workflow(f"pytest {SELECTOR}")}, {CI: workflow("pytest")}, {"Makefile": b"test:\n\tpytest tests\n"}),
])
def test_a_run_that_never_carried_the_selector_still_blocks(before, after, untouched):
    hits, verdict = moved(before, after, untouched=untouched)
    assert REPORTED in hits
    assert verdict == "block"


@pytest.mark.parametrize("before, after", [
    (f"pytest tests {SELECTOR}", "pytest"),
    (f"pytest {SELECTOR}", "python -m pytest"),
    (f"pytest {SELECTOR} -x", "pytest"),
    (f"pytest {SELECTOR} --ignore=docs", "pytest"),
    (f"pytest {SELECTOR}", "pytest --lf"),
])
def test_a_command_that_changed_more_than_the_option_still_blocks(before, after):
    # "The head invocations dropped exactly it": the program, a target and
    # every other argument stay as they were.
    hits, verdict = moved({CI: workflow(before)}, {CI: workflow(after)})
    assert REPORTED in hits
    assert verdict == "block"


def test_a_run_the_diff_adds_is_not_one_that_carried_it():
    hits, verdict = moved({CI: workflow(f"pytest {SELECTOR}")},
                          {CI: workflow("pytest"), "scripts/smoke.sh": b"#!/bin/sh\npytest\n"})
    assert REPORTED in hits


@pytest.mark.parametrize("paired", [False, True])
def test_a_renamed_runner_file_is_not_the_file_that_carried_it(paired):
    old, config = ".github/workflows/test.yml", source("pytest.ini", {"addopts": SELECTOR})
    before, after = workflow(f"pytest {SELECTOR}"), workflow("pytest")
    changes = ([FileChange(CI, "modified", before, after, old_path=old)] if paired
               else [FileChange(old, "deleted", before, None), FileChange(CI, "added", None, after)])
    hits, verdict = judge_changes([*changes, FileChange("pytest.ini", "added", None, config)],
                                  {CI: after, "pytest.ini": config})
    assert REPORTED in hits


def test_a_run_the_diff_deletes_is_not_one_that_dropped_it():
    hits, verdict = moved({CI: workflow(f"pytest {SELECTOR}"), "scripts/test.sh": b"#!/bin/sh\npytest " + SELECTOR.encode() + b"\n"},
                          {CI: workflow("pytest")})
    assert REPORTED in hits


def test_a_narrower_value_in_the_config_still_blocks():
    hits, verdict = moved({CI: workflow(f"pytest {SELECTOR}")}, {CI: workflow("pytest")}, "-m 'not slow and not db'")
    assert ("high", "CI configuration changed; test command weakened: "
                    "resolved pytest collection option introduced: -m not slow and not db") in hits
    assert verdict == "block"


def test_a_selector_moves_only_when_the_config_holds_no_other_value_for_it():
    # pytest keeps the last `-m`: here the config's `-m slow` overrides the
    # moved one.
    hits, verdict = moved({CI: workflow(f"pytest {SELECTOR}")}, {CI: workflow("pytest")}, f"{SELECTOR} -m slow")
    assert REPORTED in hits
    assert verdict == "block"


ACTION = (b"name: ci\non: [pull_request]\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n"
          b"      - uses: example/pytest-action@v1\n        with:\n          command: pytest\n")


@pytest.mark.parametrize("untouched", [
    {".github/workflows/cov.yml": workflow("coverage run -m pytest")},
    {".github/workflows/action.yml": ACTION},
    {".github/workflows/odd.yml": b"jobs: [unreadable\n  pytest\n"},
    {"tox.ini": b"[testenv]\ndeps = pytest\ncommands = pytest {posargs}\n"},
])
def test_a_run_the_reader_cannot_parse_leaves_the_migration_unproven(untouched):
    # Each of these runs passes the inventory's head-side checks, so only the
    # migration proof stands between the moved selector and a pass.
    hits, verdict = moved({CI: workflow(f"pytest {SELECTOR}")}, {CI: workflow("pytest")}, untouched=untouched)
    assert REPORTED in hits
    assert verdict == "block"


WRITES_CONFIG = b'#!/bin/sh\ncat > pyproject.toml <<EOF\n[tool.pytest.ini_options]\naddopts = "-q"\nEOF\n'


@pytest.mark.parametrize("before, after", [
    ({CI: workflow(f"pytest {SELECTOR}", "tox -e py")}, {CI: workflow("pytest", "tox -e py")}),
    ({"scripts/test.sh": b"#!/bin/sh\npytest " + SELECTOR.encode() + b"\necho 'pytest\n"},
     {"scripts/test.sh": b"#!/bin/sh\npytest\necho 'pytest\n"}),
    ({"scripts/test.sh": b"#!/bin/sh\nexport PYTEST_ADDOPTS=-q\npytest " + SELECTOR.encode() + b"\n"},
     {"scripts/test.sh": b"#!/bin/sh\npytest\n"}),
    # pytest settings the script writes itself.
    ({"scripts/test.sh": WRITES_CONFIG + b"pytest " + SELECTOR.encode() + b"\n"},
     {"scripts/test.sh": WRITES_CONFIG + b"pytest\n"}),
])
def test_a_base_side_run_the_reader_cannot_parse_leaves_it_unproven(before, after):
    hits, verdict = moved(before, after)
    assert REPORTED in hits
    assert verdict == "block"


def test_the_moved_command_itself_must_be_one_the_reader_parses():
    hits, verdict = moved({CI: workflow(f"coverage run -m pytest {SELECTOR}")}, {CI: workflow("coverage run -m pytest")})
    assert REPORTED in hits
    assert verdict == "block"


def test_a_runner_file_that_runs_no_test_is_not_a_run():
    # A tox.ini that only configures pytest, and a deploy script, run nothing
    # that the selector could narrow.
    hits, verdict = moved({CI: workflow(f"pytest {SELECTOR}")}, {CI: workflow("pytest")},
                          untouched={"tox.ini": b"[pytest]\nmarkers =\n    slow: slow\n",
                                     "scripts/deploy.sh": b"#!/bin/sh\necho deploying\n",
                                     ".github/workflows/lint.yml": b"jobs: [unreadable\n  ruff check .\n"})
    assert hits == QUIET * 2
    assert verdict == "pass"

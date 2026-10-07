"""Issue #173 (6): a positional target inside addopts is an explicit target of every run.

pytest puts the root config's addopts before its own arguments, so a word
there that is no option and no option's value is a target: `addopts =
"tests/smoke"` makes a bare `pytest` collect tests/smoke alone, testpaths
aside. The resolved inventory read addopts for its options only, so a first
or changed config that pointed every run at part of the suite passed at warn,
while the same narrowing through `testpaths` blocked.

Ruling (#196, 196.followup.addopts-positional-targets): handle it with one
definition of explicit targets for the CLI and for addopts. Both are read by
`shadow._pytest_cli`, whose options that take a value now include pytest's
own and the common plugins', so `-n auto`, `-W error` or `--cov src` is
never a target.
"""
import datetime
import shlex

import pytest

from checkwash.change import FileChange
from checkwash.collection_inventory import _addopts_targets
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.shadow import _pytest_cli

PROD = {"app/__init__.py": b"", "app/billing.py": b"def total():\n    return 78.75\n"}
SMOKE = b"from app.billing import total\n\n\ndef test_smoke():\n    assert total() > 0\n"
UNIT = b"from app.billing import total\n\n\ndef test_total():\n    assert total() == 78.75\n"
TREE = {**PROD, "tests/smoke/test_smoke.py": SMOKE, "tests/unit/test_total.py": UNIT}
LOST_UNIT = ("block", [("high", "CI configuration changed; test command weakened: resolved pytest collection "
                                "excludes 1 existing test(s), including tests/unit/test_total.py::test_total")])
WARN = ("pass", [("warn", "CI configuration changed")])


def workflow(*commands):
    return {".github/workflows/ci.yml": (
        "name: ci\non: [pull_request]\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n"
        + "".join(f"      - run: {command}\n" for command in commands)).encode()}


def ini(**settings):
    return {"pytest.ini": ("[pytest]\n" + "".join(f"{k} = {v}\n" for k, v in settings.items())).encode()}


def judge(before, after, tree=None):
    changes = [FileChange(p, "added" if p not in before else "deleted" if p not in after else "modified",
                          before.get(p), after.get(p))
               for p in sorted(before.keys() | after.keys()) if before.get(p) != after.get(p)]
    snapshot = {**(TREE if tree is None else tree), **after}
    _ir, findings, verdict = analyze(changes, Config(), Contract(), [], datetime.date(2026, 10, 6),
                                     root_reader=snapshot.get, root_path_lister=lambda: sorted(snapshot),
                                     root_batch_reader=lambda paths: {p: snapshot.get(p) for p in paths})
    return verdict, [(f.severity, f.message) for f in findings if f.rule == "CI_WORKFLOW_TOUCHED"]


# --- a target in addopts narrows every run ----------------------------------------------------

@pytest.mark.parametrize("before, after", [
    ({}, ini(addopts="tests/smoke")),
    (ini(addopts="-q"), ini(addopts="-q tests/smoke")),
    (ini(addopts="tests"), ini(addopts="tests/smoke")),
    (ini(addopts="-q"), ini(addopts="-q tests/smoke/test_smoke.py::test_smoke")),
], ids=["first_config", "added_to_existing", "narrowed", "node_id"])
def test_a_target_that_leaves_existing_tests_out_is_a_weakened_command(before, after):
    assert judge({**workflow("pytest"), **before}, {**workflow("pytest"), **after}) == LOST_UNIT


def test_with_no_runner_the_implicit_run_is_narrowed():
    assert judge({}, ini(addopts="tests/smoke")) == LOST_UNIT


def test_pyproject_addopts_as_a_list():
    pyproject = {"pyproject.toml": b'[tool.pytest.ini_options]\naddopts = ["-q", "tests/smoke"]\n'}
    assert judge(workflow("pytest"), {**workflow("pytest"), **pyproject}) == LOST_UNIT


def test_it_is_the_testpaths_narrowing_by_another_spelling():
    assert judge({**workflow("pytest"), **ini(addopts="-q")},
                 {**workflow("pytest"), **ini(addopts="-q", testpaths="tests/smoke")}) == LOST_UNIT


# --- what a run still collects ----------------------------------------------------------------

@pytest.mark.parametrize("before, after", [
    (ini(addopts="-q"), ini(addopts="-q tests")),
    (ini(addopts="tests/smoke"), ini(addopts="-q")),
    (ini(addopts="tests/smoke"), ini(addopts="tests")),
    (ini(addopts="tests/smoke"), ini(addopts="tests/smoke tests/unit")),
], ids=["every_test", "target_dropped", "widened", "target_added_beside"])
def test_a_target_that_keeps_every_test_is_no_event(before, after):
    assert judge({**workflow("pytest"), **before}, {**workflow("pytest"), **after}) == WARN


def test_a_commands_targets_and_the_addopts_targets_are_collected_together():
    """pytest collects both, so a target added to a targeted run widens it."""
    assert judge({**workflow("pytest tests/unit"), **ini(addopts="-q")},
                 {**workflow("pytest tests/unit"), **ini(addopts="-q tests/smoke")}) == WARN


def test_a_target_dropped_from_a_targeted_run_loses_what_only_it_reached():
    verdict, findings = judge({**workflow("pytest tests/unit"), **ini(addopts="tests/smoke")},
                              {**workflow("pytest tests/unit"), **ini(addopts="-q")})
    assert verdict == "block"
    assert findings == [("high", "CI configuration changed; test command weakened: resolved pytest collection "
                                 "excludes 1 existing test(s), including tests/smoke/test_smoke.py::test_smoke")]


def test_a_target_moved_from_the_command_into_addopts_loses_nothing():
    """The base run is read from the base side's runner files."""
    verdict, findings = judge({**workflow("pytest tests/smoke")}, {**workflow("pytest"), **ini(addopts="tests/smoke")})
    assert verdict == "pass"
    assert all(severity == "warn" for severity, _message in findings)


def test_a_test_another_run_still_reaches_is_not_lost():
    assert judge({**workflow("pytest tests/unit", "pytest"), **ini(addopts="-q")},
                 {**workflow("pytest tests/unit", "pytest"), **ini(addopts="-q tests/smoke")}) == WARN


def test_a_renamed_test_file_keeps_its_base_identity():
    tree = {**PROD, "tests/smoke/test_smoke.py": SMOKE, "tests/unit/test_renamed.py": UNIT}
    changes = [FileChange("pytest.ini", "added", None, ini(addopts="tests/smoke")["pytest.ini"]),
               FileChange("tests/unit/test_renamed.py", "renamed", UNIT, UNIT, old_path="tests/unit/test_total.py")]
    snapshot = {**tree, **ini(addopts="tests/smoke")}
    _ir, findings, verdict = analyze(changes, Config(), Contract(), [], datetime.date(2026, 10, 6),
                                     root_reader=snapshot.get, root_path_lister=lambda: sorted(snapshot),
                                     root_batch_reader=lambda paths: {p: snapshot.get(p) for p in paths})
    assert verdict == "block"
    assert "including tests/unit/test_total.py::test_total" in [f.message for f in findings if f.rule == "CI_WORKFLOW_TOUCHED"][0]


# --- a run that cannot pass claims nothing -------------------------------------------------------

@pytest.mark.parametrize("addopts", ["tests/gone", "app"], ids=["missing_path_exit_4", "no_test_exit_5"])
def test_a_run_pytest_fails_is_no_passing_weakening(addopts):
    assert judge(workflow("pytest"), {**workflow("pytest"), **ini(addopts=addopts)}) == WARN


def test_a_run_whose_command_names_a_missing_path_claims_nothing():
    """The addopts target dropped here would lose tests/smoke, but the head run fails (exit 4)."""
    assert judge({**workflow("pytest tests/unit tests/gone"), **ini(addopts="tests/smoke")},
                 {**workflow("pytest tests/unit tests/gone"), **ini(addopts="-q")}) == WARN
    assert judge({**workflow("pytest tests/unit"), **ini(addopts="tests/smoke")},
                 {**workflow("pytest tests/unit"), **ini(addopts="-q")})[0] == "block"


# --- a word that names no path is no target ----------------------------------------------------

# A multi-line array that the settings reader cuts at an element with `=`,
# leaving the word `[` (#324).
CUT_ARRAY = '[tool.pytest.ini_options]\naddopts = [\n    "-ra",\n    "--import-mode=importlib",\n]\n'


@pytest.mark.parametrize("addopts", ["tests/smoke tests/gone", "--loop all tests/smoke"],
                         ids=["missing_beside_a_target", "unknown_options_value"])
def test_a_word_that_names_no_path_is_no_target(addopts):
    """It is the value of an option this reader does not know, or a target that fails every run."""
    assert _addopts_targets(ini(addopts=addopts)["pytest.ini"], set(TREE)) == ("tests/smoke",)
    assert judge(workflow("pytest"), {**workflow("pytest"), **ini(addopts=addopts)}) == LOST_UNIT


@pytest.mark.parametrize("config", [
    lambda files: ini(addopts="--loop all", python_files=files),
    lambda files: {"pyproject.toml": (CUT_ARRAY + f'python_files = ["{files}"]\n').encode()},
], ids=["unknown_options_value", "array_cut_at_an_equals_sign"])
def test_a_word_that_names_no_path_leaves_the_settings_proof_standing(config):
    """Only a run with targets withholds the settings proof, and such a word is none."""
    assert judge({**workflow("pytest"), **config("test_*.py")},
                 {**workflow("pytest"), **config("test_smoke*.py")}) == LOST_UNIT


def test_a_target_is_read_against_its_own_sides_tree():
    """The base addopts name the base tree: a target directory renamed with its tests loses nothing."""
    tree = {**PROD, "tests/smoke/test_smoke.py": SMOKE, "tests/core/test_total.py": UNIT}
    before = {**workflow("pytest"), **ini(addopts="tests/unit")}
    after = {**workflow("pytest"), **ini(addopts="tests/core")}
    changes = [FileChange("pytest.ini", "modified", before["pytest.ini"], after["pytest.ini"]),
               FileChange("tests/core/test_total.py", "renamed", UNIT, UNIT, old_path="tests/unit/test_total.py")]
    snapshot = {**tree, **after}
    _ir, findings, verdict = analyze(changes, Config(), Contract(), [], datetime.date(2026, 10, 7),
                                     root_reader=snapshot.get, root_path_lister=lambda: sorted(snapshot),
                                     root_batch_reader=lambda paths: {p: snapshot.get(p) for p in paths})
    assert verdict == "pass"
    assert not any("resolved pytest collection" in f.message for f in findings)


# --- option values are never targets --------------------------------------------------------------

@pytest.mark.parametrize("addopts", [
    "-n auto", "-n 4", "--numprocesses 4", "--dist loadfile", "-W error::DeprecationWarning", "-p no:cacheprovider",
    "-r a", "--tb short", "--cov src", "--cov tests/smoke", "--cov src --cov-report term", "--timeout 30",
    "--reruns 2", "--import-mode importlib", "--log-level INFO", "-c pytest.ini",
])
def test_an_options_value_is_no_target(addopts):
    assert judge(workflow("pytest"), {**workflow("pytest"), **ini(addopts=addopts)}) == WARN
    # Read directly too: a value that names no path would also make the run
    # fail, and claim nothing, whether or not it were taken for a target.
    assert _pytest_cli([*shlex.split(addopts), "tests"])[0] == ("tests",)


@pytest.mark.parametrize("words, targets", [
    (["-n", "auto", "tests"], ("tests",)),
    (["--cov", "src", "tests"], ("tests",)),
    (["--cov", "--cov-report", "term", "tests"], ("tests",)),
    (["--cov"], ()),
    (["-p", "no:cacheprovider", "tests/unit"], ("tests/unit",)),
    (["-W", "error", "-r", "a", "tests"], ("tests",)),
    (["-nauto", "--tb=short", "tests"], ("tests",)),
    (["tests/a.py::test_x", "tests/b"], ("tests/a.py", "tests/b")),
    (["."], ()),
])
def test_one_definition_of_explicit_targets(words, targets):
    """A command's arguments and addopts' words are read alike."""
    assert _pytest_cli(words)[0] == targets


def test_addopts_targets_of_a_root_config():
    paths = set(TREE)
    assert _addopts_targets(b"[pytest]\naddopts = -q --cov src tests/smoke\n", paths) == ("tests/smoke",)
    assert _addopts_targets(b"[pytest]\naddopts = tests/smoke/test_smoke.py::test_smoke\n", paths) == (
        "tests/smoke/test_smoke.py",)
    assert _addopts_targets(b"[pytest]\nminversion = 7\n", paths) == ()
    assert _addopts_targets(None, paths) == ()


def test_ambiguous_addopts_withholds_the_inventory():
    ambiguous = {"pytest.ini": b"[pytest]\naddopts = tests/smoke\naddopts = -q\n"}
    assert _addopts_targets(ambiguous["pytest.ini"], set(TREE)) is None
    assert judge(workflow("pytest"), {**workflow("pytest"), **ambiguous}) == WARN


def test_addopts_targets_override_testpaths():
    """pytest ignores testpaths once a run has a target, so a target outside them is what runs."""
    assert judge({**workflow("pytest"), **ini(testpaths="tests/unit")},
                 {**workflow("pytest"), **ini(testpaths="tests/unit", addopts="tests/smoke")}) == LOST_UNIT


def test_the_inventory_does_not_judge_testpaths_for_a_run_with_addopts_targets():
    """Explicit targets override testpaths, so the resolved inventory makes no claim for its edit.

    The syntax scanner still reads a narrower testpaths literally, as it does
    beside a command's own targets.
    """
    _verdict, findings = judge({**workflow("pytest"), **ini(addopts="tests")},
                               {**workflow("pytest"), **ini(addopts="tests", testpaths="tests/smoke")})
    assert not any("resolved pytest collection" in message for _severity, message in findings)

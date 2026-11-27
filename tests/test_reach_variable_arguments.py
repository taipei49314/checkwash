"""The collection-reach rule: a path argument that expands a variable names no path, whatever it holds.

`opaque_reached` (#335) decides whether a pytest run could collect from an
opaque directory: a submodule, a working-tree directory symlink (#414) or,
inside the runtime-provider pass, a committed link to a directory (#551). Its
text has always said that a path argument that expands a variable (`$1`,
`{posargs}`) names no path, and `test_what_a_runner_command_reaches` pins
`$(ARGS)` and `{posargs:tests}`. Nothing made that a rule: `$1` named no path
only because no directory's name starts with it. A Bash array, `pytest
"${tests[@]}"`, holds `[@]`, which the wildcard reader took for a bracket set,
and `$*` holds a star. A wildcard is read from its literal prefix, theirs is
empty, and an empty prefix reaches every directory, whatever norecursedirs
says. So one such line in a workflow ended every run that reached the rule
with exit 2.

Found on 2026-11-27 on pydantic/pydantic-ai, whose `.github/workflows/ci.yml`
runs `pytest "${tests[@]}"`: with #551's question 2 fixed, 68 of 69 sampled
commits ended in `cannot follow directory symlink .claude/skills/<name>:
pytest's collection can reach it`, for a hidden directory no run names. The
0.13.2 CLI answers the same for a submodule.

Ruling (owner, 2026-11-27, 「好，兩個都修」, to the agent's question whether to
fix this reading and the Markdown one, each on its own): a path argument that
holds `$` names no path, so `${tests[@]}` and `$*` read as `$1` and `"$@"`
did. A wildcard with no variable in it reaches as before.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from checkwash.collection_inventory import opaque_reached

SETUP = {"setup.cfg": b"[tool:pytest]\ntestpaths = tests\n"}
ARRAY_WORKFLOW = (b"jobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      - run: |\n"
                  b"          tests=(tests/a tests/b)\n          pytest \"${tests[@]}\"\n")
# A hidden directory pytest's default norecursedirs skips, and one it recurses into.
HIDDEN, PLAIN = ".vendor/lib", "vendor/lib"
GITLINK = "1" * 40
SOURCES = {
    "src/billing.py": b"def invoice_total():\n    return 1\n",
    "tests/test_billing.py": (b"from src.billing import invoice_total\n\n"
                              b"def test_invoice_total():\n    assert invoice_total() == 2\n"),
}
NEW_PROVIDER = {"tests/src/billing.py": b"def invoice_total():\n    return 2\n"}


@pytest.mark.parametrize("runner", [
    {".github/workflows/ci.yml": ARRAY_WORKFLOW},
    {"Makefile": b"test:\n\tpytest \"${tests[@]}\"\n"},
    {"scripts/test.sh": b"#!/bin/bash\npytest \"${tests[*]}\"\n"},
    {"scripts/test.sh": b"#!/bin/bash\npytest \"${tests[0]}\"\n"},
    {"scripts/test.sh": b"#!/bin/sh\npytest $*\n"},
    {"scripts/test.sh": b"#!/bin/sh\npytest ${1:?}\n"},
    {"scripts/test.sh": b"#!/bin/bash\npytest \"tests/${suites[@]}\"\n"},
    {"scripts/test.sh": b"#!/bin/sh\npytest \"$@\"\n"},
    {"scripts/test.sh": b"#!/bin/sh\npytest $1\n"},
], ids=["array_in_a_workflow", "array_in_a_makefile", "array_star", "array_element", "dollar_star",
        "required_parameter", "array_under_a_directory", "dollar_at_as_before", "dollar_one_as_before"])
@pytest.mark.parametrize("directory", [HIDDEN, PLAIN, "tests/vendor"])
def test_a_path_argument_that_holds_a_variable_names_no_path(runner, directory):
    # Before the ruling the first six rows reached all three directories; the
    # seventh, read as a wildcard beneath `tests`, reached `tests/vendor`
    # alone; the last two reached none. `tests/${suites[@]}` now names no
    # path, as `tests/$1` never did.
    assert opaque_reached((directory,), {**SETUP, **runner}, []) is None


@pytest.mark.parametrize("runner, reached", [
    ({"Makefile": b"test:\n\tpytest */lib\n"}, PLAIN),
    ({"Makefile": b"test:\n\tpytest [uv]endor\n"}, PLAIN),
    ({"Makefile": b"test:\n\tpytest vendor/li?\n"}, PLAIN),
    ({"Makefile": b"test:\n\tpytest \"${tests[@]}\" vendor/lib\n"}, PLAIN),
    ({"Makefile": b"test:\n\tpytest \"${tests[@]}\"\n", "tox.ini": b"[testenv]\ncommands = pytest\n"}, PLAIN),
    ({"Makefile": b"test:\n\tpytest \"${tests[@]}\" -c ci/pytest.ini\n"}, PLAIN),
], ids=["star", "bracket_set", "question_mark", "a_named_path_beside_the_variable", "a_bare_run_beside_it",
        "its_own_config"])
def test_what_still_reaches_beside_a_variable(runner, reached):
    # A wildcard with no variable in it, a path the same command names, another
    # run and a run's own config reach as they did.
    assert opaque_reached((PLAIN,), {"setup.cfg": b"[tool:pytest]\naddopts = -ra\n", **runner}, []) == reached


def git(repo, *args, data=None):
    return subprocess.run(["git", "-C", str(repo), *args], input=data, capture_output=True, check=True).stdout


def _check(repo, files, *, gitlink=None, link=None):
    """A base commit of `files` with a gitlink or a directory link, then the new provider checked as the head."""
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "checkwash-test")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "commit.gpgsign", "false")
    git(repo, "config", "core.autocrlf", "false")
    for path, data in {**SOURCES, **SETUP, **files}.items():
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_bytes(data)
    git(repo, "add", "-A")
    if gitlink is not None:
        git(repo, "update-index", "--add", "--cacheinfo", f"160000,{GITLINK},{gitlink}")
    if link is not None:
        # Made in the index, not on disk, so every host commits the same entry, mode 120000.
        oid = git(repo, "hash-object", "-w", "--stdin", data=link[1]).decode("ascii").strip()
        git(repo, "update-index", "--add", "--cacheinfo", f"120000,{oid},{link[0]}")
    git(repo, "commit", "-m", "base")
    for path, data in NEW_PROVIDER.items():
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_bytes(data)
    git(repo, "add", "--", *NEW_PROVIDER)
    git(repo, "commit", "-m", "head")
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
           "PYTHONUTF8": "1", "GREENWASH_TODAY": "2026-11-27", "NO_COLOR": "1"}
    result = subprocess.run([sys.executable, "-m", "checkwash", "check", "HEAD~1..HEAD", "--format", "json",
                             "--repo", str(repo)], env=env, capture_output=True, timeout=120)
    return result.returncode, result.stdout.decode("utf-8"), result.stderr.decode("utf-8")


@pytest.mark.parametrize("opaque", [
    {"gitlink": HIDDEN},
    {"link": (".claude/skills/add-new-model", b"../../.agents/skills/add-new-model")},
], ids=["hidden_submodule", "hidden_directory_link"])
def test_a_workflow_that_passes_pytest_an_array_no_longer_ends_the_run(tmp_path, opaque):
    # A new provider takes the runtime-provider pass to the reach rule. The
    # hidden directory is one no run names, and the run gets the verdict the
    # provider earns. Before the ruling both rows ended with exit 2:
    # "pytest's collection can reach it".
    files = {".github/workflows/ci.yml": ARRAY_WORKFLOW, ".agents/skills/add-new-model/SKILL.md": b"# Add a model\n"}
    code, stdout, stderr = _check(tmp_path, files, **opaque)
    assert "engine error" not in stderr, stderr
    payload = json.loads(stdout)
    assert (code, payload["verdict"]) == (1, "block")
    assert {finding["rule"] for finding in payload["findings"]} == {"TEST_PATCHES_SUBJECT"}


def test_a_submodule_a_bare_run_recurses_into_still_fails_closed_beside_the_array(tmp_path):
    # `vendor/lib` is not hidden, and the array run is not the only one: a
    # second step runs a bare `pytest`. The tree has no testpaths, so that
    # run recurses from the root into the submodule, and every run counts.
    workflow = ARRAY_WORKFLOW + b"      - run: pytest\n"
    code, stdout, stderr = _check(tmp_path, {".github/workflows/ci.yml": workflow,
                                             "setup.cfg": b"[tool:pytest]\naddopts = -ra\n"}, gitlink=PLAIN)
    assert (code, stdout) == (2, "")
    assert ("checkwash engine error: EngineError: strict snapshot cannot inspect the submodule vendor/lib: "
            "pytest's collection can reach it") in stderr

"""The collection-reach rule: the part of a path argument that expands a variable is no wildcard.

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
fix this reading and the Markdown one, each on its own): `${tests[@]}` and
`$*` read as `$1` and `"$@"` did. A wildcard with no variable in it reaches as
before.

The first commit under the ruling dropped every path argument that holds `$`.
That also dropped what 0.13.2 read rightly: `pytest sub/$1` collects inside
`sub`, and the rule had answered so. Review on the same day found it, and
then found two more runs the new reading let through. The reading is now as
narrow as the ruling:
- only the `[`, `*` and `?` inside a variable expansion (`${...}`, `$name`,
  `$1`, `$@`, `$*`, `$?`) are no wildcard. The rest of the argument is read
  as it always was: the directories before the variable, and a wildcard
  beside it (`te*$x`);
- only in a run's own arguments. `pytest || exit $?` is a bare `pytest`
  followed by another command, and the rule's reader takes `exit` and `$?`
  for path arguments, so the run is not judged as the bare run it is. On
  0.13.2 the `?` is a wildcard that reaches every directory, and the check
  ends with exit 2; read as text, it gave a verdict where the bare run
  collects from the directory. A word after a control operator, and every
  word of a line that continues, is therefore read as on 0.13.2.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from checkwash.collection_inventory import environment_reached, opaque_reached

SETUP ={"setup.cfg": b"[tool:pytest]\ntestpaths = tests\n"}
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
    # alone; the last two reached none. `tests/${suites[@]}` now reaches none
    # of the three, as `tests/$1` never did.
    assert opaque_reached((directory,), {**SETUP, **runner}, []) is None


@pytest.mark.parametrize("runner", [
    {"Makefile": b"test:\n\tpytest $?\n"},
    {"scripts/test.sh": b"#!/bin/bash\npytest \"${tests[@]:1}\"\n"},
    {"scripts/test.sh": b"#!/bin/sh\npytest ${name%%.*}\n"},
    {"scripts/test.sh": b"#!/bin/sh\npytest ${TESTS:-*}\n"},
], ids=["a_special_parameter", "an_array_slice", "a_trimmed_variable", "a_default_that_is_a_wildcard"])
@pytest.mark.parametrize("directory", [HIDDEN, PLAIN])
def test_a_wildcard_character_inside_an_expansion_is_no_wildcard(runner, directory):
    # Each of these reached both directories before the ruling. The last one
    # is where the reading gives up something true: with `TESTS` unset the
    # shell does expand the star. What a variable expands to is not read.
    assert opaque_reached((directory,), {**SETUP, **runner}, []) is None


@pytest.mark.parametrize("runner, directory", [
    ({"scripts/test.sh": b"#!/bin/sh\npytest tests/sh*$x\n"}, "tests/shared"),
    ({"scripts/test.sh": b"#!/bin/sh\npytest vendor/*$x\n"}, PLAIN),
    ({"scripts/test.sh": b"#!/bin/sh\npytest $x*\n"}, HIDDEN),
    ({"scripts/test.sh": b"#!/bin/sh\npytest '*a$'\n"}, HIDDEN),
    ({"scripts/t.ps1": b"pytest $args[0]\r\n"}, HIDDEN),
], ids=["a_star_before_the_variable", "a_star_beside_the_variable", "a_star_after_the_variable",
        "a_dollar_that_starts_no_expansion", "a_powershell_index"])
def test_a_wildcard_outside_the_expansion_is_still_one(runner, directory):
    # The wildcard is the shell's own, whatever the variable holds, and is
    # read from its literal prefix as on 0.13.2. PowerShell's `$args[0]` is
    # read as a bracket set after the variable, as it was: it fails closed.
    assert opaque_reached((directory,), {**SETUP, **runner}, []) == directory


@pytest.mark.parametrize("line", [
    b"pytest || exit $?",
    b"pytest -v --cov | tee pytest.log; exit ${PIPESTATUS[0]}",
    b"pytest \"$@\" || exit $?",
    b"pytest tests && echo $*",
    b"pytest tests; echo \"${done[@]}\"",
    b"pytest \"${tests[@]}\" \\\n  vendor/lib",
], ids=["a_bare_run_then_exit_status", "a_piped_run_then_pipestatus", "a_parameter_run_then_exit_status",
        "a_named_run_then_another_command", "a_named_run_then_a_semicolon", "an_array_on_a_line_that_continues"])
@pytest.mark.parametrize("directory", [HIDDEN, PLAIN])
def test_a_word_that_is_no_argument_of_the_run_is_read_as_it_was(line, directory):
    # After a control operator a word belongs to another command, and on a
    # line that ends in a backslash the run's arguments go on where the
    # reader does not follow. The reader takes such words for path arguments
    # all the same (`_pytest_cli`), so the run before them is never judged as
    # bare, and the wildcard 0.13.2 reads in them is what ends the check: the
    # first row is a bare `pytest`, which collects from `vendor/lib`. Every
    # row reaches both directories, as on 0.13.2.
    runner = {"scripts/test.sh": b"#!/bin/bash\n" + line + b"\n"}
    assert opaque_reached((directory,), {**SETUP, **runner}, []) == directory


def test_a_testpath_is_no_argument_and_is_read_as_it_was():
    # The ruling is for the arguments of a run. A testpath is a setting, and
    # pytest expands its wildcard itself.
    files = {"setup.cfg": b"[tool:pytest]\ntestpaths = ${suites[@]}\n", "Makefile": b"test:\n\tpytest\n"}
    assert opaque_reached((HIDDEN,), files, []) == HIDDEN


def test_the_environment_rule_keeps_its_reading_of_an_array():
    # `environment_reached` (D-208) is not ruled and not changed: where a run
    # passes `--collect-in-virtualenv` it reads the array's bracket as the
    # wildcard it was.
    files = {"setup.cfg": b"[tool:pytest]\naddopts = -ra\n",
             "scripts/test.sh": b"#!/bin/bash\npytest --collect-in-virtualenv \"${tests[@]}\"\n"}
    assert environment_reached(("env",), files, []) == "env"
    assert opaque_reached(("env",), files, []) is None


MATRIX_WORKFLOW = (b"jobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n"
                   b"      - run: pytest sub/${{ matrix.suite }}\n")


@pytest.mark.parametrize("runner, directory", [
    ({"scripts/test.sh": b"#!/bin/sh\npytest sub/$1\n"}, "sub"),
    ({"scripts/test.sh": b"#!/bin/sh\npytest sub/tests/$SUITE\n"}, "sub"),
    ({"scripts/test.sh": b"#!/bin/bash\npytest \"sub/${suites[@]}\"\n"}, "sub"),
    ({"Makefile": b"test:\n\tpytest vendor/lib/$(SUITE)\n"}, PLAIN),
    ({".github/workflows/ci.yml": MATRIX_WORKFLOW}, "sub"),
    ({"scripts/test.sh": b"#!/bin/sh\npytest tests/$1\n"}, "tests"),
    ({"scripts/test.sh": b"#!/bin/sh\npytest .vendor/lib/$1\n"}, HIDDEN),
    ({"scripts/test.sh": b"#!/bin/sh\npytest sub/*/$x\n"}, "sub/a"),
], ids=["a_parameter_inside_it", "a_variable_deeper_inside_it", "an_array_inside_it", "a_make_variable_inside_it",
        "a_workflow_expression_inside_it", "a_parameter_inside_the_testpath", "a_parameter_inside_a_hidden_one",
        "a_wildcard_before_the_variable"])
def test_the_directories_before_a_variable_still_reach(runner, directory):
    # `sub/$1` is a path inside `sub` for any `$1` that names one below it,
    # so the run collects there. 0.13.2 answered so, and the rule does again:
    # only what is inside the expansion is not read for a wildcard. In the
    # last row the wildcard stands in a part of its own, before the variable,
    # and is read from its literal prefix as it was.
    assert opaque_reached((directory,), {**SETUP, **runner}, []) == directory


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


@pytest.mark.parametrize("opaque, runner, refusal", [
    ({"gitlink": PLAIN}, b"#!/bin/sh\npytest vendor/lib/$1\n",
     "strict snapshot cannot inspect the submodule vendor/lib: pytest's collection can reach it"),
    ({"link": (".claude/skills/add-new-model", b"../../.agents/skills/add-new-model")},
     b"#!/bin/sh\npytest .claude/skills/add-new-model/$1\n",
     "strict snapshot inventory cannot follow directory symlink .claude/skills/add-new-model: "
     "pytest's collection can reach it"),
], ids=["submodule", "directory_link"])
def test_a_run_that_names_a_path_inside_it_through_a_variable_still_fails_closed(tmp_path, opaque, runner, refusal):
    # The script's run names a path inside the directory through `$1`, so the
    # check ends as it does on 0.13.2 for the submodule: exit 2, naming it.
    files = {"scripts/test.sh": runner, ".agents/skills/add-new-model/SKILL.md": b"# Add a model\n"}
    code, stdout, stderr = _check(tmp_path, files, **opaque)
    assert (code, stdout) == (2, "")
    assert f"checkwash engine error: EngineError: {refusal}" in stderr


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

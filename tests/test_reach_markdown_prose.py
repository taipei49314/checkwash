"""The collection-reach rule: a Markdown file is prose, and its words are no pytest command.

`opaque_reached` (#335) reads the pytest commands of the runner files to
decide whether a run could collect from an opaque directory: a submodule, a
working-tree directory symlink (#414) or, inside the runtime-provider pass, a
committed link to a directory (#551). Every file beneath `.github/workflows/`
or `scripts/` is a runner file to it. A Markdown file there that mentions
pytest had its sentence read as a command and the words after it as path
arguments, with two wrong results:
- `**bold**` text is a wildcard, whose empty literal prefix reaches every
  directory, so the run ended with exit 2 for a directory no run names;
- any other sentence counted as a run with path arguments, so the bare
  `pytest` that a tree without a runner implies was never judged, and a
  directory that run recurses into was reported as out of reach.

Found on 2026-11-27 on pydantic/pydantic-ai, which keeps instructions for
coding agents in `.github/workflows/shared/*.md`: with #551's question 2
fixed, those files were one of two reasons 68 of 69 sampled commits ended in
`cannot follow directory symlink .claude/skills/<name>: pytest's collection
can reach it`. The 0.13.2 CLI answers the same for a submodule.

Ruling (owner, 2026-11-27, 「好，兩個都修」, to the agent's question whether to
fix this reading and the variable one, each on its own): the reach rule
reads no run from a Markdown file. Only this rule changes: the file is still
a runner file to every other reader, and any other kind of file beneath those
directories is read as before.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from checkwash.change import FileChange
from checkwash.collection_inventory import collection_sources, opaque_reached

TESTPATHS = {"setup.cfg": b"[tool:pytest]\ntestpaths = tests\n"}
NO_TESTPATHS = {"setup.cfg": b"[tool:pytest]\naddopts = -ra\n"}
BOLD = b"# Review hints\n\nRun pytest and note the **observed** failure. Paste the exact output.\n"
PLAIN_PROSE = b"# Contributing\n\nRun pytest locally before you push.\n"
TESTS_ONLY = {"Makefile": b"test:\n\tpytest tests\n"}
# A hidden directory pytest's default norecursedirs skips, and one it recurses into.
HIDDEN, PLAIN = ".vendor/lib", "vendor/lib"
GITLINK = "1" * 40
SOURCES = {
    "src/billing.py": b"def invoice_total():\n    return 1\n",
    "tests/test_billing.py": (b"from src.billing import invoice_total\n\n"
                              b"def test_invoice_total():\n    assert invoice_total() == 2\n"),
}
NEW_PROVIDER = {"tests/src/billing.py": b"def invoice_total():\n    return 2\n"}


@pytest.mark.parametrize("prose", [
    ".github/workflows/shared/review.md",
    ".github/workflows/REVIEW.MD",
    ".github/workflows/review.markdown",
    "scripts/README.md",
])
@pytest.mark.parametrize("directory", [HIDDEN, PLAIN])
def test_bold_text_in_a_markdown_file_reaches_nothing(prose, directory):
    # Beside a Makefile whose only run names `tests`. Before the ruling the
    # bold word was a wildcard and each row reached the directory.
    assert opaque_reached((directory,), {**NO_TESTPATHS, **TESTS_ONLY, prose: BOLD}, []) is None


@pytest.mark.parametrize("config, directory, reached", [
    (NO_TESTPATHS, PLAIN, PLAIN),
    (NO_TESTPATHS, HIDDEN, None),
    (TESTPATHS, PLAIN, None),
], ids=["recursed_into_from_the_root", "hidden", "outside_testpaths"])
@pytest.mark.parametrize("prose", [BOLD, PLAIN_PROSE], ids=["bold", "plain"])
def test_a_tree_whose_only_runner_file_is_markdown_is_judged_by_a_bare_pytest(config, directory, reached, prose):
    # No file runs pytest, so the run is the bare `pytest` such a tree
    # implies: from the root config's testpaths, else from the root, into
    # every directory no norecursedirs pattern stops. Before the ruling the
    # bold sentence reached all three rows, and the plain one none: its words
    # were path arguments, so no bare run was judged and `vendor/lib` read as
    # out of reach.
    assert opaque_reached((directory,), {**config, "scripts/README.md": prose}, []) == reached


def test_a_markdown_file_the_diff_changes_is_prose_on_both_sides():
    head = {**NO_TESTPATHS, **TESTS_ONLY, "scripts/README.md": BOLD}
    for before, after in ((PLAIN_PROSE, BOLD), (BOLD, PLAIN_PROSE), (None, BOLD), (BOLD, None)):
        kind = "added" if before is None else "deleted" if after is None else "modified"
        change = FileChange("scripts/README.md", kind, before, after)
        assert opaque_reached((PLAIN,), head, [change]) is None


@pytest.mark.parametrize("runner", [
    {".github/workflows/ci.yml": b"jobs:\n  test:\n    steps:\n      - run: pytest\n"},
    {"scripts/NOTES.txt": BOLD},
    {"scripts/notes.rst": BOLD},
    {"scripts/test.sh": b"#!/bin/sh\npytest */lib\n"},
], ids=["a_workflow_that_runs_a_bare_pytest", "a_text_file", "a_restructuredtext_file", "a_script_with_a_wildcard"])
def test_every_other_runner_file_is_read_as_before(runner):
    # Only Markdown is ruled. A YAML workflow's bare run still recurses into
    # the directory, a script's wildcard still reaches it, and prose kept in
    # another kind of file beneath `scripts/` is still read as a command.
    assert opaque_reached((PLAIN,), {**NO_TESTPATHS, **TESTS_ONLY, "scripts/README.md": BOLD, **runner}, []) == PLAIN


def test_the_markdown_file_is_still_a_source_the_rule_is_given():
    # The rule's inputs do not change: the file is fetched as before and left
    # unread here, and it stays a runner file to every other reader.
    assert collection_sources(["scripts/README.md", ".github/workflows/shared/review.md", "docs/review.md"]) == [
        ".github/workflows/shared/review.md", "scripts/README.md"]


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
    for path, data in {**SOURCES, **files}.items():
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
def test_instructions_for_agents_kept_beside_the_workflows_no_longer_end_the_run(tmp_path, opaque):
    # A new provider takes the runtime-provider pass to the reach rule. The
    # hidden directory is one no run names, and the run gets the verdict the
    # provider earns. Before the ruling both rows ended with exit 2:
    # "pytest's collection can reach it".
    files = {**TESTPATHS, **TESTS_ONLY, ".github/workflows/shared/review.md": BOLD,
             ".agents/skills/add-new-model/SKILL.md": b"# Add a model\n"}
    code, stdout, stderr = _check(tmp_path, files, **opaque)
    assert "engine error" not in stderr, stderr
    payload = json.loads(stdout)
    assert (code, payload["verdict"]) == (1, "block")
    assert {finding["rule"] for finding in payload["findings"]} == {"TEST_PATCHES_SUBJECT"}


def test_a_submodule_a_bare_pytest_recurses_into_now_fails_closed_beside_plain_prose(tmp_path):
    # The other direction, which the ruling makes stricter: the tree's only
    # runner file is a Markdown note with no bold text, and it has no
    # testpaths. Before, the note's words were path arguments, no bare run
    # was judged, and this run got a verdict. A bare `pytest` recurses from
    # the root into `vendor/lib`, so it fails closed now, naming it.
    code, stdout, stderr = _check(tmp_path, {**NO_TESTPATHS, "scripts/README.md": PLAIN_PROSE}, gitlink=PLAIN)
    assert (code, stdout) == (2, "")
    assert ("checkwash engine error: EngineError: strict snapshot cannot inspect the submodule vendor/lib: "
            "pytest's collection can reach it") in stderr

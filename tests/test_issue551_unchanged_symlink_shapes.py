"""Issue #551, question 2: the unchanged links the runtime-provider pass asks for, in a committed range.

The pass's first read phase asks for every unchanged path that could hold a
test runner, a pytest control or a candidate test, and the strict batch
reader refuses a link (mode 120000). Until this ruling one committed link
stopped every run that reached the phase, with exit 2 and no verdict.

Ruling (owner, 2026-11-27, 「#551 照你建議裁決」, on the recommendation the
agent had written for question 2): in a committed range, for the links that
phase asks for,
- a link to a regular file of the same commit reads as that file, as D-133
  item 2 reads a symlinked pytest config;
- a link to a directory of the same commit is an opaque directory, as D-134
  lists one in the working tree: it holds no bytes, and its files are in the
  inventory under their own paths;
- a target outside the tree, a link to a link, a missing target and a target
  inside a submodule keep the refusal.

Two reviews on the same day narrowed how the ruling is carried out, and the
owner was told with the pull request. Only the runtime-provider pass reads a
link. Every other pass reads the snapshot, where a search of the tree does
not look inside a link and some readers take a refused link for an absent
file. So a link the pass reads can hide a change from the passes that give
the verdict, and each of these ended with exit 2 on 0.13.2 and got `pass`
from the first form of this change:
- an assertion weakened, or a `sys.path` root added, in the target of an
  unchanged link (`tests/test_alias.py`, `tests/conftest.py`), which was
  read as the head's target on both sides;
- a root assertion helper gutted, where the test that uses it exists only as
  a link (`tests/test_calc.py -> ../shared/calc_checks.py`): the search for
  the helper's callers finds no test;
- `|| true` appended to a call of a linked script that runs the suite: the
  scan that follows the call takes the link for an absent file;
- a module added beneath the target of a directory link that a test imports
  through under another name (`overlay/src -> ../patches`);
- a linked conftest whose code resolves its own path: pytest runs it at the
  link's path, where `Path(__file__).resolve()` is the target's.
And a run 0.13.2 judged ended with exit 2 beside a directory link a pytest
run could collect from (`tests -> src/pkg/tests`), because the first form
listed every directory link as opaque from the start of the pass.

So the ruling is carried out this way:
- The pass runs over the snapshot first, as on 0.13.2. A run 0.13.2 judged
  is therefore the run it was.
- Only when one of its batch reads is refused on a committed link, and only
  when every link of the tree is one no pass could need, does it run again
  through the link view. Otherwise the run ends as on 0.13.2, with the same
  refusal.
- A link no pass could need reads the same on both sides of the range (the
  same link, leading to the same place; for a file the same entry there, for
  a directory nothing changed beneath it), is not named as source (`.py`, a
  JS or TS suffix), and is no script that runs the suite. A link that leads
  to nothing the tree holds, on both sides, is harmless and is refused only
  when the pass asks for it.

Found on 2026-11-27 by running the 0.13.2 CLI as `check <sha>~1..<sha>
--format json` over 104 sampled commits of pydantic/pydantic-ai (since
2026-05-27). 71 ended with exit 2, and all 71 were run again:
- 69 named `.claude/skills/add-new-model` or `.claude/skills/complete-partial-pr`.
  Each is a link to a directory, `../../.agents/skills/<name>`, that the
  commit does not change. One example is `015e0f8fa060`, which changes
  `pydantic_ai_slim/pydantic_ai/images/openai.py`, its test and one document.
- With every dot-less link answered as an empty file, in a driver outside
  this repository, 68 of those 69 stopped on the next link instead:
  `.claude/skills/branch-context/append-handoff.sh`, a link to a shell
  script, or `.github/workflows/CLAUDE.md`, a link to the `AGENTS.md` beside it.
- The other two named no such link: a changed test file over the source
  limit, and a link that commit adds.

So the phase asks for a link when its path is one it would read as a regular
file: a name with no dot, a path with the ci role (`.github/workflows/**`),
a runner suffix (`.sh`), or, by a reproduction made here, a candidate test
module (`tests/test_alias.py`). A dotted link outside those paths
(`CLAUDE.md -> AGENTS.md`) is never asked for.

What is pinned here:
- each of those shapes, unchanged, leaves the run the verdict it has with no
  link, and the ordinary edit that reaches the phase (#551 gives it by
  reading: a changed `.py` file whose module name another `.py` file also
  provides) passes beside one;
- a run that asks for no link keeps the verdict it had, beside a directory
  link a pytest run could collect from;
- a link to a directory fails closed where D-134 does: when pytest's
  collection can reach it, when an import can resolve inside it, and for a
  read inside it;
- a link that leads to no file or directory of the commit keeps the refusal
  when the pass asks for it, and is no obstacle when it does not;
- a tree that holds any other link gets the refusal 0.13.2 gives: a link
  whose target the commit changes, adds, makes executable or holds over the
  source limit on one side, a directory link the commit changes something
  beneath, a link named as source, a linked script that runs the suite, a
  link to a link and a link into a submodule;
- the reading belongs to that pass alone: the snapshot itself still refuses
  the same link, another pass that reads the link refuses it, and a commit
  that changes a link is still refused by the diff read.

Range mode only: every link is made in the index, as in test_issue455_q4, so
each host commits the same entry. The working tree is not covered by the
ruling; its row stays in test_issue455_q4.
"""
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from checkwash.change import EngineError
from checkwash.gitio.snapshot import (
    MAX_LINK_TEXT_BYTES, MAX_SOURCE_BYTES, GitSnapshot, LinkedTreeView, WorkingTreeSnapshot, _link_reading,
    link_view_of, refused_link,
)
from checkwash.opaque import SymlinkedDirectory
from checkwash.sweep import sweep

NONREGULAR = "strict snapshot batch cannot inspect nonregular source"
DIRECTORY_LINK = "strict snapshot inventory cannot follow directory symlink"
# test_issue455's provider-pass fixture: a new provider of `src.billing`
# beside the test that imports it takes the pass to its first read phase.
SOURCES = {
    "src/billing.py": b"def invoice_total():\n    return 1\n",
    "tests/test_billing.py": (b"from src.billing import invoice_total\n\n"
                              b"def test_invoice_total():\n    assert invoice_total() == 2\n"),
}
NEW_PROVIDER = {"tests/src/billing.py": b"def invoice_total():\n    return 2\n"}
# What the links point to: regular files of the same tree, none of them changed.
AGENT_FILES = {
    "AGENTS.md": b"# Agents\n",
    "docs/AGENTS.md": b"# Documentation\n",
    ".github/workflows/AGENTS.md": b"# Workflows\n",
    ".agents/skills/add-new-model/SKILL.md": b"# Add a model\n",
    ".agents/skills/branch-context/status.sh": b"#!/usr/bin/env bash\necho status\n",
}
# The shapes the phase asks for, the first three as pydantic-ai commits them.
DIRECTORY_LINK_SHAPE = {".claude/skills/add-new-model": b"../../.agents/skills/add-new-model"}
CI_ROLE_LINK = {".github/workflows/CLAUDE.md": b"AGENTS.md"}
RUNNER_SUFFIX_LINK = {".claude/skills/branch-context/status.sh": b"../../../.agents/skills/branch-context/status.sh"}
DOT_LESS_FILE_LINK = {"status": b".agents/skills/branch-context/status.sh"}
# A candidate test the phase reads: a second name for the test module beside it.
TEST_MODULE_LINK = {"tests/test_alias.py": b"test_billing.py"}
# Links the phase never asks for: a dot in the name, no ci role, no runner suffix.
DOTTED_LINKS = {"CLAUDE.md": b"AGENTS.md", "docs/CLAUDE.md": b"AGENTS.md"}
# Two modules that share a basename, and the test of one of them.
TWIN_MODULES = {
    "pkg/__init__.py": b"",
    "pkg/models/__init__.py": b"",
    "pkg/images/__init__.py": b"",
    "pkg/models/openai.py": b"def name():\n    return 'model'\n",
    "pkg/images/openai.py": b"def generate():\n    return 1\n",
    "tests/test_images.py": (b"from pkg.images.openai import generate\n\n"
                             b"def test_generate():\n    assert generate() == 1\n"),
}
# An edit that changes the module's syntax tree and nothing a test can see.
ORDINARY_EDIT = {"pkg/images/openai.py": b"def generate():\n    value = 1\n    return value\n"}
WEAKENED_TEST = {"tests/test_images.py": TWIN_MODULES["tests/test_images.py"].replace(b"== 1", b"> 0")}
# Any commit name serves a gitlink: the tree records it and never reads it.
SUBMODULE_COMMIT = "1" * 40


def git(repo, *args, data=None):
    return subprocess.run(["git", "-C", str(repo), *args], input=data, capture_output=True, check=True).stdout


def _write(repo, files):
    for path, data in files.items():
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_bytes(data)


def _link(repo, link, target):
    """A link made in the index, not on disk, so every host stages the same entry, mode 120000."""
    oid = git(repo, "hash-object", "-w", "--stdin", data=target).decode("ascii").strip()
    git(repo, "update-index", "--add", "--cacheinfo", f"120000,{oid},{link}")


def _repo(path, files, links, submodules=()):
    """A repository whose base commit holds `files`, the symlinks `links` and the gitlinks `submodules`."""
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-b", "main")
    git(path, "config", "user.name", "checkwash-test")
    git(path, "config", "user.email", "test@example.invalid")
    git(path, "config", "commit.gpgsign", "false")
    git(path, "config", "core.autocrlf", "false")
    _write(path, files)
    git(path, "add", "-A")
    for link, target in links.items():
        _link(path, link, target)
    for submodule in submodules:
        git(path, "update-index", "--add", "--cacheinfo", f"160000,{SUBMODULE_COMMIT},{submodule}")
    git(path, "commit", "-m", "base")
    return path


def _check(repo):
    """Commit what is staged as the head, then `check HEAD~1..HEAD --format json`."""
    git(repo, "commit", "-m", "head")
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
           "PYTHONUTF8": "1", "GREENWASH_TODAY": "2026-11-27", "NO_COLOR": "1"}
    result = subprocess.run([sys.executable, "-m", "checkwash", "check", "HEAD~1..HEAD", "--format", "json",
                             "--repo", str(repo)], env=env, capture_output=True, timeout=120)
    return result.returncode, result.stdout.decode("utf-8"), result.stderr.decode("utf-8")


def _check_head(repo, head_files):
    """Stage `head_files` alone and check them as the head.

    Only they are staged: `add -A` would stage the removal of a link made in
    the index alone.
    """
    _write(repo, head_files)
    git(repo, "add", "--", *head_files)
    return _check(repo)


def _judged(result):
    """A run's exit code and its report without `run`, which names each repository's own commits."""
    code, stdout, stderr = result
    assert "engine error" not in stderr, stderr
    return code, {key: value for key, value in json.loads(stdout).items() if key != "run"}


def _refusal(link):
    return f"checkwash engine error: EngineError: {NONREGULAR} {link} (a symlink)"


# --- the shapes, on a run a new provider takes to the phase -----------------------------------------

@pytest.mark.parametrize("links", [DIRECTORY_LINK_SHAPE, CI_ROLE_LINK, RUNNER_SUFFIX_LINK, DOT_LESS_FILE_LINK,
                                   DOTTED_LINKS],
                         ids=["dot_less_directory_link", "ci_role_link", "runner_suffix_link",
                              "dot_less_file_link", "dotted_links_never_asked_for"])
def test_an_unchanged_link_leaves_the_run_the_verdict_it_has_without_the_link(tmp_path, links):
    # The new provider takes the pass to phase one. Before the ruling the
    # first four shapes ended there with exit 2; the dotted links outside ci
    # roles and runner suffixes never did.
    linked = _judged(_check_head(_repo(tmp_path / "linked", {**SOURCES, **AGENT_FILES}, links), NEW_PROVIDER))
    plain = _judged(_check_head(_repo(tmp_path / "plain", {**SOURCES, **AGENT_FILES}, {}), NEW_PROVIDER))
    assert linked == plain
    # The provider is the finding, with or without the link.
    assert (linked[0], linked[1]["verdict"]) == (1, "block")
    assert {finding["rule"] for finding in linked[1]["findings"]} == {"TEST_PATCHES_SUBJECT"}


def test_an_unchanged_link_to_a_test_module_is_read_as_that_test(tmp_path):
    # `tests/test_alias.py -> test_billing.py` is a candidate test the phase
    # asks for, and it ends the run with exit 2, as on 0.13.2. The first form
    # of this change read it as the module it leads to, and the provider pass
    # then named it as a test the new provider reaches. No other pass would:
    # a test that exists only under a link's name is one only that pass sees
    # (the rows below), so a link named as source is not read.
    repo = _repo(tmp_path, {**SOURCES, **AGENT_FILES}, TEST_MODULE_LINK)
    code, stdout, stderr = _check_head(repo, NEW_PROVIDER)
    assert (code, stdout) == (2, "")
    assert _refusal("tests/test_alias.py") in stderr


# A second test module, kept outside `tests` and reached through a link there.
CHECKS = (b"from src.billing import invoice_total\n\n\n"
          b"def test_invoice_total_again():\n    assert invoice_total() == 2\n")
# A conftest that puts its own resolved directory first on `sys.path`.
RESOLVING_CONFTEST = (b"import sys\nfrom pathlib import Path\n\n"
                      b"sys.path.insert(0, str(Path(__file__).resolve().parent))\n")
LICENCE = {"py/LICENSE": b"Licence terms\n"}
LICENCE_LINK = {"LICENSE": b"py/LICENSE"}


@pytest.mark.parametrize("links, files, refused", [
    ({"tests/test_more.py": b"../shared/checks.py"}, {"shared/checks.py": CHECKS}, "tests/test_more.py"),
    ({"tests/conftest.py": b"../support/conftest_impl.py"}, {"support/conftest_impl.py": RESOLVING_CONFTEST},
     "tests/conftest.py"),
    ({"src/alias.py": b"billing.py", **LICENCE_LINK}, {}, "LICENSE"),
    ({"web/app.test.ts": b"../shared/app.checks.ts", **LICENCE_LINK},
     {"shared/app.checks.ts": b"export const checks = 1;\n"}, "LICENSE"),
], ids=["a_test_that_exists_only_as_a_link", "a_conftest", "a_module_the_pass_never_asks_for",
        "a_typescript_test_the_pass_never_asks_for"])
def test_a_tree_with_a_link_named_as_source_gets_the_refusal_it_had(tmp_path, links, files, refused):
    # Neither the link nor its target changes. A search of the tree does not
    # look inside a link, so the detectors do not know the test of the first
    # row, and pytest runs the conftest of the second at the link's path,
    # where its `resolve()` is the target's. The last two links are ones the
    # pass never asks for: beside a licence link it would read, they still
    # keep the run from being read through the view, and it ends on the
    # licence link, as on 0.13.2.
    repo = _repo(tmp_path, {**SOURCES, **LICENCE, **files}, links)
    code, stdout, stderr = _check_head(repo, NEW_PROVIDER)
    assert (code, stdout) == (2, "")
    assert _refusal(refused) in stderr


def test_a_tree_with_a_linked_script_that_runs_the_suite_gets_the_refusal_it_had(tmp_path):
    # `scripts/ci.sh` calls `scripts/run-tests.sh`, a link to the script that
    # runs pytest, and the commit appends `|| true` to the call. With a
    # regular `scripts/run-tests.sh` that blocks: the scan that follows the
    # call finds the runner. It takes a link for an absent file, so the first
    # form of this change, which read the link in the provider pass alone,
    # gave `pass`.
    files = {**SOURCES, "scripts/ci.sh": b"#!/bin/sh\n./scripts/run-tests.sh\n",
             "tools/run-tests-impl.sh": b"#!/bin/sh\npytest tests\n"}
    repo = _repo(tmp_path, files, {"scripts/run-tests.sh": b"../tools/run-tests-impl.sh"})
    code, stdout, stderr = _check_head(repo, {**NEW_PROVIDER, "scripts/ci.sh": b"#!/bin/sh\n./scripts/run-tests.sh || true\n"})
    assert (code, stdout) == (2, "")
    assert _refusal("scripts/run-tests.sh") in stderr


# --- an ordinary edit reaches the phase when two modules share a basename ---------------------------

@pytest.mark.parametrize("without", ["nothing", "the_link", "the_twin_module"])
def test_an_ordinary_edit_beside_a_twin_module_passes(tmp_path, without):
    # `pkg/images/openai.py` gains a local. `pkg/models/openai.py` provides
    # the module tail `openai` too, so the edited module survives the
    # provider-collision filter and the pass reaches phase one (#551, "Which
    # runs reach the phase", second case). Before the ruling the first row
    # ended with exit 2 on the unchanged link, and the other two passed:
    # without the link nothing was refused, and without the second
    # `openai.py` the pass returned before phase one.
    files = {**TWIN_MODULES, **AGENT_FILES}
    links = DIRECTORY_LINK_SHAPE
    if without == "the_link":
        links = {}
    elif without == "the_twin_module":
        del files["pkg/models/openai.py"]
    code, report = _judged(_check_head(_repo(tmp_path, files, links), ORDINARY_EDIT))
    assert (code, report["verdict"], report["findings"]) == (0, "pass", [])


def test_a_sweep_analyses_the_ordinary_edit_beside_an_unchanged_link(tmp_path):
    # The sweep checks each commit against its parent as a range check does,
    # and gives the pass the same link view. Before the ruling this commit
    # counted as an error.
    repo = _repo(tmp_path, {**TWIN_MODULES, **AGENT_FILES}, DIRECTORY_LINK_SHAPE)
    _write(repo, ORDINARY_EDIT)
    git(repo, "add", "--", *ORDINARY_EDIT)
    git(repo, "commit", "-m", "head")
    result = sweep(str(repo), "HEAD", 5, datetime.date(2026, 11, 27))
    # One commit analysed and none in error (0.13.2: none analysed, one in
    # error); the base commit has no parent and is skipped.
    assert (result.commits, result.errors, result.skipped, result.blocked) == (1, 0, 1, 0)


def test_a_run_short_of_the_first_read_phase_gets_a_verdict_beside_every_link(tmp_path):
    # A weakened test alone, with no twin module, returns before phase one:
    # the weakening blocks as a finding beside every link, as it did before.
    files = {**TWIN_MODULES, **AGENT_FILES}
    del files["pkg/models/openai.py"]
    links = {**DIRECTORY_LINK_SHAPE, **CI_ROLE_LINK, **RUNNER_SUFFIX_LINK, **DOT_LESS_FILE_LINK, **DOTTED_LINKS}
    code, report = _judged(_check_head(_repo(tmp_path, files, links), WEAKENED_TEST))
    assert (code, report["verdict"]) == (1, "block")
    assert "ASSERT_WEAKENED" in {finding["rule"] for finding in report["findings"]}


# --- a run that asks for no link is the run it was on 0.13.2 ----------------------------------------

# A package that keeps its tests inside itself, as `src/pkg/tests`.
PACKAGE = {
    "src/pkg/__init__.py": b"",
    "src/pkg/core.py": b"def value():\n    return 1\n",
    "src/pkg/tests/__init__.py": b"",
    "src/pkg/tests/test_core.py": b"from pkg.core import value\n\n\ndef test_value():\n    assert value() == 1\n",
}
WEAKENED_PACKAGE_TEST = {
    "src/pkg/tests/test_core.py": PACKAGE["src/pkg/tests/test_core.py"].replace(b"== 1", b"> 0")}
ORDINARY_PACKAGE_EDIT = {"src/pkg/core.py": b"def value():\n    result = 1\n    return result\n"}


@pytest.mark.parametrize("links", [{"tests": b"src/pkg/tests"}, {"pkg": b"src/pkg"}],
                         ids=["a_root_tests_link", "a_root_package_link"])
@pytest.mark.parametrize("edit, verdict", [(WEAKENED_PACKAGE_TEST, (1, "block")), (ORDINARY_PACKAGE_EDIT, (0, "pass"))],
                         ids=["a_weakened_test", "an_ordinary_edit"])
def test_a_run_that_asks_for_no_link_keeps_its_verdict_beside_a_directory_link_a_collection_can_reach(
        tmp_path, links, edit, verdict):
    # Each link leads to a directory of the commit and is not hidden: a bare
    # `pytest` recurses into it. Neither edit takes the pass to a read, so no
    # reader asks for the link, 0.13.2 judges the commit, and the run is the
    # same run with the link or without. The first form of this change listed
    # the link as an opaque directory from the start of the pass, and three of
    # the four rows ended with exit 2 ("pytest's collection can reach it");
    # the ordinary edit beside `tests` kept its verdict then too.
    linked = _judged(_check_head(_repo(tmp_path / "linked", PACKAGE, links), edit))
    plain = _judged(_check_head(_repo(tmp_path / "plain", PACKAGE, {}), edit))
    assert linked == plain
    assert (linked[0], linked[1]["verdict"]) == verdict


def test_a_dotted_directory_link_does_not_end_a_run_that_reaches_the_phase(tmp_path):
    # `tests/shared.d -> ../common` has a dot in its name, so phase one never
    # asks for it, and the new provider's run gets its verdict on 0.13.2. It
    # still does: no read is refused, so the pass is not run through the view,
    # where the link would be an opaque directory a bare `pytest` reaches.
    files = {**SOURCES, "common/helpers.py": b"VALUE = 1\n"}
    linked = _judged(_check_head(_repo(tmp_path / "linked", files, {"tests/shared.d": b"../common"}), NEW_PROVIDER))
    plain = _judged(_check_head(_repo(tmp_path / "plain", files, {}), NEW_PROVIDER))
    assert linked == plain
    assert (linked[0], linked[1]["verdict"]) == (1, "block")


# --- a link to a directory is opaque, and fails closed as D-134 does --------------------------------

def test_a_directory_link_a_collection_can_reach_fails_closed_naming_it(tmp_path):
    # `tests/shared -> ../common`: a bare `pytest` recurses from the root into
    # `tests/shared`, which no norecursedirs pattern stops.
    repo = _repo(tmp_path, {**SOURCES, "common/helpers.py": b"VALUE = 1\n"}, {"tests/shared": b"../common"})
    code, stdout, stderr = _check_head(repo, NEW_PROVIDER)
    assert (code, stdout) == (2, "")
    assert (f"checkwash engine error: EngineError: {DIRECTORY_LINK} tests/shared: "
            "pytest's collection can reach it") in stderr


def test_a_directory_link_an_import_can_resolve_inside_fails_closed_naming_it(tmp_path):
    # `billing -> impl/billing` at the root, which `pythonpath = .` puts on
    # the import path: the test's `from billing import total` can resolve
    # inside the link. `testpaths` keeps pytest's collection out of it, so
    # the import is what refuses.
    files = {"setup.cfg": b"[tool:pytest]\ntestpaths = tests\npythonpath = .\n",
             "impl/billing/__init__.py": b"def total():\n    return 1\n",
             "tests/test_total.py": b"from billing import total\n\n\ndef test_total():\n    assert total() == 2\n"}
    repo = _repo(tmp_path, files, {"billing": b"impl/billing"})
    code, stdout, stderr = _check_head(repo, {"tests/billing.py": b"def total():\n    return 2\n"})
    assert (code, stdout) == (2, "")
    assert (f"checkwash engine error: EngineError: {DIRECTORY_LINK} billing: "
            "the import of billing can resolve inside it") in stderr


# --- every other link keeps the refusal -------------------------------------------------------------

@pytest.mark.parametrize("target, files, links, submodules", [
    (b"../outside", {}, {}, ()),
    (b"/etc/hosts", {}, {}, ()),
    (b"/AGENTS.md", {}, {}, ()),
    (b"gone", {}, {}, ()),
    (b"AGENTS.md/inside", {}, {}, ()),
    (b"CLAUDE.md", {}, {"CLAUDE.md": b"AGENTS.md"}, ()),
    (b".vendor/lib", {}, {}, (".vendor/lib",)),
    (b".vendor/lib/README", {}, {}, (".vendor/lib",)),
], ids=["outside_the_tree", "absolute", "absolute_naming_a_file_of_the_tree", "missing_target", "through_a_file",
        "link_to_a_link", "a_submodule", "inside_a_submodule"])
def test_a_link_that_leads_to_no_file_or_directory_of_the_commit_still_refuses(tmp_path, target, files, links,
                                                                              submodules):
    # `LINK` has no dot, so phase one asks for it. Its text leads to nothing
    # the ruling reads, and the batch reader refuses it as before.
    repo = _repo(tmp_path, {**SOURCES, **AGENT_FILES, **files}, {"LINK": target, **links}, submodules)
    code, stdout, stderr = _check_head(repo, NEW_PROVIDER)
    # Not a size refusal, so stdout stays empty (#454).
    assert (code, stdout) == (2, "")
    assert _refusal("LINK") in stderr


@pytest.mark.parametrize("link, text, files, head_files", [
    ("run", b"tools/steps.txt", {"tools/steps.txt": b"#!/bin/sh\npytest tests\n"},
     {"tools/steps.txt": b"#!/bin/sh\nPYTHONPATH=shadow pytest tests\n"}),
    ("LICENSE", b"docs/LICENSE.txt", {"docs/LICENSE.txt": b"Licence terms\n"},
     {"docs/LICENSE.txt": b"Licence terms, revised\n"}),
    ("NOTES", b"docs/notes.txt", {}, {"docs/notes.txt": b"Notes\n"}),
], ids=["a_runner_changed_at_its_target", "a_document_edited_at_its_target", "a_target_the_commit_adds"])
def test_a_link_whose_target_the_commit_changes_keeps_the_refusal(tmp_path, link, text, files, head_files):
    # The link is the same entry on both sides, and what it stands for is
    # not: the commit changes the file it leads to. Read as the head's target
    # for both sides, as the first form of this change read it, the path
    # would hold the commit's change and show none: the first row's runner
    # gained `PYTHONPATH=shadow` and the run got `pass`. So the link keeps the
    # refusal it has on 0.13.2, whatever the target is; the last row's link
    # leads nowhere at the base.
    repo = _repo(tmp_path, {**SOURCES, **files}, {link: text})
    code, stdout, stderr = _check_head(repo, {**NEW_PROVIDER, **head_files})
    assert (code, stdout) == (2, "")
    assert _refusal(link) in stderr


def test_a_link_whose_target_changes_mode_alone_keeps_the_refusal(tmp_path):
    # The target's bytes are the same and its entry is not: the commit makes
    # it executable. The link is read only where its target is the same entry.
    repo = _repo(tmp_path, {**SOURCES, "tools/run.txt": b"pytest tests\n"}, {"run": b"tools/run.txt"})
    git(repo, "update-index", "--chmod=+x", "tools/run.txt")
    code, stdout, stderr = _check_head(repo, NEW_PROVIDER)
    assert (code, stdout) == (2, "")
    assert _refusal("run") in stderr


def test_a_link_to_a_target_set_aside_unread_keeps_the_refusal(tmp_path):
    # The target's base side is over the source limit, so the commit's change
    # to it is set aside unread (#415), and a reader that reaches for the
    # path refuses. The first form of this change read the head's bytes
    # through the link instead, as an unchanged runner. The same change to a
    # regular `ci/steps` ends with a size refusal.
    big = b"# steps\n" + b"#" * MAX_SOURCE_BYTES + b"\n"
    repo = _repo(tmp_path, {**SOURCES, "data/steps.txt": big}, {"ci/steps": b"../data/steps.txt"})
    code, _stdout, stderr = _check_head(repo, {**NEW_PROVIDER, "data/steps.txt": b"PYTHONPATH=shadow pytest tests\n"})
    assert code == 2
    assert _refusal("ci/steps") in stderr


def test_a_directory_link_the_commit_changes_something_beneath_keeps_the_refusal(tmp_path):
    # `overlay/src -> ../patches`, with `overlay` first on the import path:
    # the test's `from src.billing import ...` resolves through the link. The
    # commit adds `patches/billing.py`, which pytest then imports as
    # `src.billing`. The pass looks for the new module under its own path,
    # `patches`, and not under the link's name, so as an opaque directory the
    # link let the plant through. A directory link is read only where nothing
    # beneath it changes.
    files = {"setup.cfg": b"[tool:pytest]\ntestpaths = tests\npythonpath = overlay .\n",
             "src/billing.py": b"def invoice_total():\n    return 1\n",
             "tests/test_billing.py": SOURCES["tests/test_billing.py"], "patches/README.txt": b"Patches\n"}
    repo = _repo(tmp_path, files, {"overlay/src": b"../patches"})
    code, stdout, stderr = _check_head(repo, {"patches/billing.py": b"def invoice_total():\n    return 2\n"})
    assert (code, stdout) == (2, "")
    assert _refusal("overlay/src") in stderr


def test_one_link_that_cannot_be_read_keeps_the_refusal_of_a_link_that_can(tmp_path):
    # The licence link is one the view reads, and the pass asks for it. The
    # dotted `tests/new.d -> ../made` is never asked for, and the commit
    # creates the directory it leads to: at the base it led nowhere. With one
    # such link in the tree no link is read, and the run ends on the licence
    # link, as on 0.13.2.
    repo = _repo(tmp_path, {**SOURCES, **LICENCE}, {**LICENCE_LINK, "tests/new.d": b"../made"})
    code, stdout, stderr = _check_head(repo, {**NEW_PROVIDER, "made/notes.txt": b"Notes\n"})
    assert (code, stdout) == (2, "")
    assert _refusal("LICENSE") in stderr


def test_a_link_that_leads_nowhere_and_is_never_asked_for_is_no_obstacle(tmp_path):
    # `docs/old.d -> ../gone` leads to nothing on either side, and its name
    # has a dot, so no pass asks for it: the commit holds nothing there. The
    # licence link beside it is read, and the run gets the verdict it has
    # with no link at all.
    files = {**SOURCES, **LICENCE, "docs/index.md": b"# Docs\n"}
    linked = _judged(_check_head(_repo(tmp_path / "linked", files, {**LICENCE_LINK, "docs/old.d": b"../gone"}),
                                 NEW_PROVIDER))
    plain = _judged(_check_head(_repo(tmp_path / "plain", files, {}), NEW_PROVIDER))
    assert linked == plain
    assert (linked[0], linked[1]["verdict"]) == (1, "block")


def test_a_link_to_a_file_over_the_source_limit_refuses_under_the_target(tmp_path):
    # The target is read as any selected source is: over the limit it
    # refuses, naming the file that is over it.
    big = b"#!/bin/sh\n" + b"#" * MAX_SOURCE_BYTES + b"\n"
    repo = _repo(tmp_path, {**SOURCES, "tools/run.txt": big}, {"run": b"tools/run.txt"})
    code, _stdout, stderr = _check_head(repo, NEW_PROVIDER)
    assert code == 2
    assert (f"checkwash engine error: SourceOverLimit: strict snapshot source exceeds the byte limit: "
            f"tools/run.txt (head, {len(big)} > {MAX_SOURCE_BYTES} bytes)") in stderr


# --- the reading belongs to the runtime-provider pass alone -----------------------------------------

@pytest.mark.parametrize("change", ["adds", "retargets", "removes"])
def test_a_commit_that_changes_a_link_is_still_refused_by_the_diff_read(tmp_path, change):
    # Outside the ruling, which covers the links phase one asks for: a link
    # in the diff is read by the diff read, which refuses it as before. No
    # `EngineError:` prefix: that caller reports the refusal itself.
    repo = _repo(tmp_path, {**SOURCES, **AGENT_FILES}, {} if change == "adds" else {"CLAUDE.md": b"AGENTS.md"})
    if change == "removes":
        git(repo, "rm", "--cached", "-q", "CLAUDE.md")
    else:
        _link(repo, "CLAUDE.md", b"AGENTS.md" if change == "adds" else b"docs/AGENTS.md")
    code, stdout, stderr = _check(repo)
    assert (code, stdout) == (2, "")
    assert f"checkwash engine error: {NONREGULAR} CLAUDE.md (a symlink)" in stderr


def test_another_pass_that_reads_the_same_link_still_refuses_it(tmp_path):
    # The commit changes the root config's collection settings and nothing
    # else, which sends the collection-inventory pass to every runner file.
    # That pass reads the snapshot, not the view, and refuses the unchanged
    # `scripts/run.sh` link as it does on 0.13.2.
    files = {**SOURCES, "tools/run.sh": b"#!/bin/sh\necho hi\n", "setup.cfg": b"[tool:pytest]\ntestpaths = tests\n"}
    repo = _repo(tmp_path, files, {"scripts/run.sh": b"../tools/run.sh"})
    code, stdout, stderr = _check_head(repo, {"setup.cfg": b"[tool:pytest]\ntestpaths = tests src\n"})
    assert (code, stdout) == (2, "")
    assert f"{NONREGULAR} scripts/run.sh (a symlink)" in stderr


# A link text over the limit that would lead to `AGENTS.md`, and one just under it that does.
OVER_THE_TEXT_LIMIT = b"./" * (MAX_LINK_TEXT_BYTES // 2 - 3) + b"AGENTS.md"
UNDER_THE_TEXT_LIMIT = b"./" * (MAX_LINK_TEXT_BYTES // 2 - 5) + b"AGENTS.md"
assert len(OVER_THE_TEXT_LIMIT) == MAX_LINK_TEXT_BYTES + 3 and len(UNDER_THE_TEXT_LIMIT) == MAX_LINK_TEXT_BYTES - 1


@pytest.fixture
def snapshot(tmp_path):
    """The head of a tree whose links are all ones the view reads, or lead to nothing."""
    links = {**DIRECTORY_LINK_SHAPE, **CI_ROLE_LINK, **RUNNER_SUFFIX_LINK, **DOT_LESS_FILE_LINK, **DOTTED_LINKS,
             "LOST": b"gone", "OUTSIDE": b"../elsewhere/file", "BEYOND_A_FILE": b"AGENTS.md/inside",
             "NEAR": UNDER_THE_TEXT_LIMIT, "ROOT": b"."}
    return GitSnapshot(_repo(tmp_path, {**SOURCES, **AGENT_FILES}, links), "HEAD", side="head")


def _view(snapshot):
    """The link view of a range that changes nothing: the same commit on both sides."""
    return link_view_of(snapshot, GitSnapshot(snapshot.repo, "HEAD", side="base"))


def test_only_a_committed_tree_has_a_link_view(snapshot, tmp_path):
    base = GitSnapshot(snapshot.repo, "HEAD", side="base")
    assert type(link_view_of(snapshot, base)) is LinkedTreeView
    # The working tree is outside the ruling: with no view, the pass has its root readers alone.
    assert link_view_of(WorkingTreeSnapshot(tmp_path), base) is None


def test_a_link_view_needs_both_sides_of_the_range_as_committed_trees(snapshot, tmp_path):
    # The view reads a link only where both sides agree, so a head with no
    # base, or with a base that is no committed tree, has none.
    head_alone = link_view_of(snapshot)
    assert head_alone is None
    assert link_view_of(snapshot, WorkingTreeSnapshot(tmp_path)) is None


def test_the_view_lists_a_directory_link_as_an_opaque_directory_and_the_snapshot_does_not(snapshot):
    view = _view(snapshot)
    assert view.readable() and view.unreadable() == ()
    listed = view.list_paths()
    opaque = sorted(path for path in listed if isinstance(path, SymlinkedDirectory))
    # `ROOT -> .` leads to the tree's root, a directory of the commit as any other.
    assert opaque == [".claude/skills/add-new-model/", "ROOT/"]
    assert ".claude/skills/add-new-model" not in listed and "ROOT" not in listed
    # A link to a file, and one that leads to nothing, stay listed as paths.
    for link in ("status", "CLAUDE.md", ".github/workflows/CLAUDE.md", "LOST", "OUTSIDE", "BEYOND_A_FILE", "NEAR"):
        assert link in listed
    # Every other reader lists the snapshot itself: each link is a path there.
    plain = snapshot.list_paths()
    assert not any(isinstance(path, SymlinkedDirectory) for path in plain)
    assert ".claude/skills/add-new-model" in plain and "ROOT" in plain
    assert sorted(str(path).rstrip("/") for path in listed) == sorted(plain)


def test_the_view_reads_a_file_link_as_its_target_and_the_snapshot_refuses_it(snapshot):
    view = _view(snapshot)
    script = AGENT_FILES[".agents/skills/branch-context/status.sh"]
    read = view.read_many(["status", ".claude/skills/branch-context/status.sh", ".github/workflows/CLAUDE.md",
                           "docs/CLAUDE.md", "NEAR", "AGENTS.md", "absent"])
    assert read == {
        "status": script,
        ".claude/skills/branch-context/status.sh": script,
        ".github/workflows/CLAUDE.md": AGENT_FILES[".github/workflows/AGENTS.md"],
        "docs/CLAUDE.md": AGENT_FILES["docs/AGENTS.md"],
        # One byte under the link-text limit.
        "NEAR": AGENT_FILES["AGENTS.md"],
        "AGENTS.md": AGENT_FILES["AGENTS.md"],
        "absent": None,
    }
    # A second view of the same range reads the same: each view resolves the links itself.
    assert _view(snapshot).read_many(["status"]) == {"status": script}
    # The snapshot's own batch reader, which every other pass is given, still
    # refuses the same link, and names it for the pass that may read it.
    with pytest.raises(EngineError, match=f"{NONREGULAR} status \\(a symlink\\)") as refused:
        snapshot.read_many(["status"])
    assert refused_link(refused.value) == "status"
    assert refused_link(EngineError("any other refusal")) is None


@pytest.mark.parametrize("link", ["LOST", "OUTSIDE", "BEYOND_A_FILE", ".claude/skills/add-new-model", "ROOT"])
def test_the_view_refuses_a_link_it_cannot_read_as_a_file(snapshot, link):
    # A missing target, a target outside the tree, a path through a regular
    # file, and a directory link asked for as a file: the snapshot's refusal,
    # unchanged.
    with pytest.raises(EngineError) as refused:
        _view(snapshot).read_many([link])
    assert str(refused.value) == f"{NONREGULAR} {link} (a symlink)"


def test_the_view_refuses_a_read_inside_a_directory_link(snapshot):
    with pytest.raises(EngineError) as refused:
        _view(snapshot).read_many([".claude/skills/add-new-model/SKILL.md"])
    assert str(refused.value) == (f"{DIRECTORY_LINK} .claude/skills/add-new-model: "
                                  ".claude/skills/add-new-model/SKILL.md lies inside it")


RUNS_THE_SUITE = {"tools/impl.sh": b"#!/bin/sh\npytest tests\n", "tools/inert.sh": b"#!/bin/sh\necho done\n"}


@pytest.mark.parametrize("link, text, links, submodules", [
    ("CHAIN", b"CLAUDE.md", {}, ()),
    ("LONG", OVER_THE_TEXT_LIMIT, {}, ()),
    ("docs/conftest.py", b"../AGENTS.md", {}, ()),
    ("pkg/alias.py", b"../src/billing.py", {}, ()),
    ("web/app.test.TS", b"../AGENTS.md", {}, ()),
    ("scripts/run-tests.sh", b"../tools/impl.sh", {}, ()),
    ("scripts/Build.CMD", b"../tools/impl.sh", {}, ()),
    ("vendored", b".vendor/lib", {}, (".vendor/lib",)),
    ("vendored-readme", b".vendor/lib/README", {}, (".vendor/lib",)),
    ("around", b".vendor", {}, (".vendor/lib",)),
    ("ODD", b"docs\\AGENTS.md", {}, ()),
], ids=["a_link_to_a_link", "text_over_the_limit", "a_conftest_name", "a_python_module_name", "a_typescript_name",
        "a_script_that_runs_the_suite", "a_batch_script_that_runs_the_suite", "a_submodule", "inside_a_submodule",
        "a_directory_that_holds_a_submodule", "text_the_walk_does_not_read"])
def test_one_link_no_pass_could_safely_miss_leaves_the_view_unreadable(tmp_path, link, text, links, submodules):
    # Each tree holds the links of `snapshot`, all readable, and one more.
    # Nothing changes in the range. The one link is enough: the view answers
    # for no link, and names it.
    every = {**DIRECTORY_LINK_SHAPE, **CI_ROLE_LINK, **DOT_LESS_FILE_LINK, **DOTTED_LINKS, link: text, **links}
    repo = _repo(tmp_path, {**SOURCES, **AGENT_FILES, **RUNS_THE_SUITE}, every, submodules)
    view = _view(GitSnapshot(repo, "HEAD", side="head"))
    assert not view.readable()
    assert view.unreadable() == (link,)
    for call in (view.list_paths, lambda: view.read_many(["status"])):
        with pytest.raises(EngineError) as refused:
            call()
        assert str(refused.value) == f"{NONREGULAR} {link} (a symlink)"


def test_a_linked_script_that_runs_nothing_is_read(tmp_path):
    # The same names as the two script rows above, leading to a script that
    # runs no suite: the scan that follows a call to it would find no runner
    # there either, so the link hides nothing.
    links = {"scripts/run-tests.sh": b"../tools/inert.sh", "scripts/Build.CMD": b"../tools/inert.sh"}
    view = _view(GitSnapshot(_repo(tmp_path, {**SOURCES, **RUNS_THE_SUITE}, links), "HEAD", side="head"))
    assert view.readable()
    assert view.read_many(["scripts/run-tests.sh"]) == {"scripts/run-tests.sh": RUNS_THE_SUITE["tools/inert.sh"]}


def test_the_view_reads_a_link_only_where_it_reads_the_same_on_both_sides(tmp_path):
    # One range, and every way a link can read differently at its two ends.
    files = {"AGENTS.md": b"# Agents\n", "docs/guide.txt": b"Guide\n", "tools/run.txt": b"pytest tests\n",
             "kept/notes.txt": b"Notes\n", "still/notes.txt": b"Notes\n", "swapped": b"a file at the base\n",
             "leaving/index.txt": b"removed by the head\n"}
    links = {"SAME": b"AGENTS.md", "EDITED": b"docs/guide.txt", "ADDED": b"docs/new.txt", "MODE": b"tools/run.txt",
             "RETARGETED": b"AGENTS.md", "GROWN_DIRECTORY": b"kept", "STILL_DIRECTORY": b"still",
             "NEW_DIRECTORY": b"made", "WAS_A_FILE": b"swapped", "THROUGH": b"made/../still/notes.txt",
             "GONE": b"leaving/index.txt", "NOWHERE": b"never/there.txt"}
    repo = _repo(tmp_path, files, links)
    _write(repo, {"docs/guide.txt": b"Guide, revised\n", "docs/new.txt": b"New\n", "made/index.txt": b"Made\n",
                  "kept/more.txt": b"More\n"})
    git(repo, "add", "--", "docs/guide.txt", "docs/new.txt", "made/index.txt", "kept/more.txt")
    git(repo, "update-index", "--chmod=+x", "tools/run.txt")
    _link(repo, "RETARGETED", b"docs/guide.txt")
    _link(repo, "FRESH", b"AGENTS.md")
    # `swapped`, a file at the base, is a directory at the head, and `leaving` is gone.
    git(repo, "rm", "--cached", "-q", "swapped", "leaving/index.txt")
    oid = git(repo, "hash-object", "-w", "--stdin", data=b"now inside a directory\n").decode("ascii").strip()
    git(repo, "update-index", "--add", "--cacheinfo", f"100644,{oid},swapped/index.txt")
    git(repo, "commit", "-m", "head")
    view = link_view_of(GitSnapshot(repo, "HEAD", side="head"), GitSnapshot(repo, "HEAD~1", side="base"))
    # The target's bytes change; the target is added; its mode changes; the
    # link itself is retargeted or added; a file is added beneath the
    # directory it leads to; that directory is added; its target turns from a
    # file into a directory; its text walks through a directory only the head
    # has, to a file that is unchanged; and its target is removed. `SAME`,
    # `STILL_DIRECTORY` and `NOWHERE`, which leads to nothing at either end,
    # are not among them.
    assert view.unreadable() == ("ADDED", "EDITED", "FRESH", "GONE", "GROWN_DIRECTORY", "MODE", "NEW_DIRECTORY",
                                 "RETARGETED", "THROUGH", "WAS_A_FILE")
    assert not view.readable()


def test_a_range_that_touches_no_link_or_target_has_a_readable_view(tmp_path):
    # The same kinds of link, in a range that changes none of them and
    # nothing they lead to: the file link reads as its target, the directory
    # link is opaque, and the one that leads nowhere stays a path.
    files = {"AGENTS.md": b"# Agents\n", "still/notes.txt": b"Notes\n", "src/billing.py": SOURCES["src/billing.py"]}
    repo = _repo(tmp_path, files, {"SAME": b"AGENTS.md", "STILL_DIRECTORY": b"still", "NOWHERE": b"never/there.txt"})
    _write(repo, {"src/billing.py": b"def invoice_total():\n    return 3\n"})
    git(repo, "add", "--", "src/billing.py")
    git(repo, "commit", "-m", "head")
    view = link_view_of(GitSnapshot(repo, "HEAD", side="head"), GitSnapshot(repo, "HEAD~1", side="base"))
    assert view.readable()
    assert view.read_many(["SAME"]) == {"SAME": b"# Agents\n"}
    listed = view.list_paths()
    assert sorted(path for path in listed if isinstance(path, SymlinkedDirectory)) == ["STILL_DIRECTORY/"]
    assert "NOWHERE" in listed and "SAME" in listed


ENTRIES = {
    "AGENTS.md": (b"100644", b"0" * 40, 1),
    "bin/run": (b"100755", b"0" * 40, 1),
    "docs/guide.md": (b"100644", b"0" * 40, 1),
    "docs/alias": (b"120000", b"0" * 40, 1),
    # Names git can hold and a link text must not reach: each refused text below would name one of them.
    "C:/hosts": (b"100644", b"0" * 40, 1),
    "docs\\guide.md": (b"100644", b"0" * 40, 1),
    "docs/guide.md\n": (b"100644", b"0" * 40, 1),
    "docs/guide.md\r": (b"100644", b"0" * 40, 1),
    "docs/guide.md\0": (b"100644", b"0" * 40, 1),
}
TREES = frozenset({"bin", "docs", "docs/sub", "C:"})


@pytest.mark.parametrize("path, text, reading", [
    ("CLAUDE.md", b"AGENTS.md", ("file", "AGENTS.md")),
    ("docs/CLAUDE.md", b"../AGENTS.md", ("file", "AGENTS.md")),
    ("docs/CLAUDE.md", b"./guide.md", ("file", "docs/guide.md")),
    ("docs/sub/run", b"../../bin/run", ("file", "bin/run")),
    ("docs/sub/run", b"..//..//bin/./run", ("file", "bin/run")),
    ("skills", b"docs", ("directory", "docs")),
    ("skills", b"docs/", ("directory", "docs")),
    ("skills", b"docs/sub/..", ("directory", "docs")),
    ("docs/up", b"..", ("directory", "")),
    ("up", b".", ("directory", "")),
    ("x", None, None),
    ("x", b"", None),
    ("x", b"\xff", None),
    ("x", b"/etc/hosts", None),
    ("x", b"/AGENTS.md", None),
    ("x", b"C:/hosts", None),
    ("x", b"docs\\guide.md", None),
    ("x", b"docs/guide.md\n", None),
    ("x", b"docs/guide.md\r", None),
    ("x", b"docs/guide.md\0", None),
    ("x", b"../AGENTS.md", None),
    ("docs/x", b"../../AGENTS.md", None),
    ("x", b"gone", None),
    ("x", b"gone/../AGENTS.md", None),
    ("x", b"AGENTS.md/", None),
    ("x", b"AGENTS.md/..", None),
    ("x", b"docs/alias", None),
    ("x", b"docs/alias/guide.md", None),
])
def test_a_link_reading_is_a_file_or_a_directory_of_the_tree_or_nothing(path, text, reading):
    assert _link_reading(path, text, ENTRIES, TREES) == reading

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
- a link to a directory fails closed where D-134 does: when pytest's
  collection can reach it, and for a read inside it;
- every other link keeps the refusal, naming it;
- the reading belongs to that pass alone: the snapshot itself still refuses
  the same link, and a commit that changes a link is still refused by the
  diff read.

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
    MAX_LINK_TEXT_BYTES, MAX_SOURCE_BYTES, GitSnapshot, WorkingTreeSnapshot, _link_reading, link_view_of,
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
    # reads; before the ruling it ended the run with exit 2. It reads as the
    # module it leads to, so it imports `src.billing` too, and the finding
    # names it as a test the new provider reaches.
    repo = _repo(tmp_path, {**SOURCES, **AGENT_FILES}, TEST_MODULE_LINK)
    code, report = _judged(_check_head(repo, NEW_PROVIDER))
    assert (code, report["verdict"]) == (1, "block")
    (finding,) = report["findings"]
    assert (finding["rule"], finding["path"]) == ("TEST_PATCHES_SUBJECT", "tests/src/billing.py")
    assert finding["message"].startswith("tests/test_alias.py: imported subject src.billing resolves to "
                                         "the changed provider tests/src/billing.py")


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


# --- a link to a directory is opaque, and fails closed as D-134 does --------------------------------

def test_a_directory_link_a_collection_can_reach_fails_closed_naming_it(tmp_path):
    # `tests/shared -> ../common`: a bare `pytest` recurses from the root into
    # `tests/shared`, which no norecursedirs pattern stops.
    repo = _repo(tmp_path, {**SOURCES, "common/helpers.py": b"VALUE = 1\n"}, {"tests/shared": b"../common"})
    code, stdout, stderr = _check_head(repo, NEW_PROVIDER)
    assert (code, stdout) == (2, "")
    assert (f"checkwash engine error: EngineError: {DIRECTORY_LINK} tests/shared: "
            "pytest's collection can reach it") in stderr


# --- every other link keeps the refusal -------------------------------------------------------------

@pytest.mark.parametrize("target, files, links, submodules", [
    (b"../outside", {}, {}, ()),
    (b"/etc/hosts", {}, {}, ()),
    (b"gone", {}, {}, ()),
    (b"AGENTS.md/inside", {}, {}, ()),
    (b"CLAUDE.md", {}, {"CLAUDE.md": b"AGENTS.md"}, ()),
    (b".vendor/lib", {}, {}, (".vendor/lib",)),
    (b".vendor/lib/README", {}, {}, (".vendor/lib",)),
], ids=["outside_the_tree", "absolute", "missing_target", "through_a_file", "link_to_a_link",
        "a_submodule", "inside_a_submodule"])
def test_a_link_that_leads_to_no_file_or_directory_of_the_commit_still_refuses(tmp_path, target, files, links,
                                                                              submodules):
    # `LINK` has no dot, so phase one asks for it. Its text leads to nothing
    # the ruling reads, and the batch reader refuses it as before.
    repo = _repo(tmp_path, {**SOURCES, **AGENT_FILES, **files}, {"LINK": target, **links}, submodules)
    code, stdout, stderr = _check_head(repo, NEW_PROVIDER)
    # Not a size refusal, so stdout stays empty (#454).
    assert (code, stdout) == (2, "")
    assert _refusal("LINK") in stderr


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


@pytest.fixture
def snapshot(tmp_path):
    """The head of a tree that holds every kind of link, and its link view."""
    links = {**DIRECTORY_LINK_SHAPE, **CI_ROLE_LINK, **RUNNER_SUFFIX_LINK, **DOT_LESS_FILE_LINK, **DOTTED_LINKS,
             "LOST": b"gone", "CHAIN": b"CLAUDE.md", "LONG": b"x" * (MAX_LINK_TEXT_BYTES + 1), "ROOT": b"."}
    return GitSnapshot(_repo(tmp_path, {**SOURCES, **AGENT_FILES}, links), "HEAD", side="head")


def test_only_a_committed_tree_has_a_link_view(snapshot, tmp_path):
    assert link_view_of(snapshot) is snapshot.link_view()
    # The working tree is outside the ruling: with no view, the pass reads its root readers.
    assert link_view_of(WorkingTreeSnapshot(tmp_path)) is None


def test_the_view_lists_a_directory_link_as_an_opaque_directory_and_the_snapshot_does_not(snapshot):
    listed = snapshot.link_view().list_paths()
    opaque = sorted(path for path in listed if isinstance(path, SymlinkedDirectory))
    # `ROOT -> .` leads to the tree's root, a directory of the commit as any other.
    assert opaque == [".claude/skills/add-new-model/", "ROOT/"]
    assert ".claude/skills/add-new-model" not in listed and "ROOT" not in listed
    # A link to a file, and one that keeps its refusal, stay listed as paths.
    for link in ("status", "CLAUDE.md", ".github/workflows/CLAUDE.md", "LOST", "CHAIN", "LONG"):
        assert link in listed
    # Every other reader lists the snapshot itself: each link is a path there.
    plain = snapshot.list_paths()
    assert not any(isinstance(path, SymlinkedDirectory) for path in plain)
    assert ".claude/skills/add-new-model" in plain and "ROOT" in plain
    assert sorted(str(path).rstrip("/") for path in listed) == sorted(plain)


def test_the_view_reads_a_file_link_as_its_target_and_the_snapshot_refuses_it(snapshot):
    view = snapshot.link_view()
    script = AGENT_FILES[".agents/skills/branch-context/status.sh"]
    read = view.read_many(["status", ".claude/skills/branch-context/status.sh", ".github/workflows/CLAUDE.md",
                           "docs/CLAUDE.md", "AGENTS.md", "absent"])
    assert read == {
        "status": script,
        ".claude/skills/branch-context/status.sh": script,
        ".github/workflows/CLAUDE.md": AGENT_FILES[".github/workflows/AGENTS.md"],
        "docs/CLAUDE.md": AGENT_FILES["docs/AGENTS.md"],
        "AGENTS.md": AGENT_FILES["AGENTS.md"],
        "absent": None,
    }
    assert snapshot.link_view() is view
    # The snapshot's own batch reader, which every other pass is given, still refuses the same link.
    with pytest.raises(EngineError, match=f"{NONREGULAR} status \\(a symlink\\)"):
        snapshot.read_many(["status"])


@pytest.mark.parametrize("link", ["LOST", "CHAIN", "LONG", ".claude/skills/add-new-model", "ROOT"])
def test_the_view_refuses_a_link_it_cannot_read_as_a_file(snapshot, link):
    # A missing target, a link to a link, text over the link-text limit, and a
    # directory link asked for as a file: the snapshot's refusal, unchanged.
    with pytest.raises(EngineError) as refused:
        snapshot.link_view().read_many([link])
    assert str(refused.value) == f"{NONREGULAR} {link} (a symlink)"


def test_the_view_refuses_a_read_inside_a_directory_link(snapshot):
    with pytest.raises(EngineError) as refused:
        snapshot.link_view().read_many([".claude/skills/add-new-model/SKILL.md"])
    assert str(refused.value) == (f"{DIRECTORY_LINK} .claude/skills/add-new-model: "
                                  ".claude/skills/add-new-model/SKILL.md lies inside it")


ENTRIES = {
    "AGENTS.md": (b"100644", b"0" * 40, 1),
    "bin/run": (b"100755", b"0" * 40, 1),
    "docs/guide.md": (b"100644", b"0" * 40, 1),
    "docs/alias": (b"120000", b"0" * 40, 1),
}
TREES = frozenset({"bin", "docs", "docs/sub"})


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
    ("x", b"C:/hosts", None),
    ("x", b"docs\\guide.md", None),
    ("x", b"docs/guide.md\n", None),
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

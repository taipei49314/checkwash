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

Three reviews, and probes made between them, narrowed how the ruling is
carried out, and the owner was told with the pull request. Only the
runtime-provider pass reads a link. Every other pass reads the snapshot,
where a search of the tree does not look inside a link, a path beneath a
link is absent, and some readers take a refused link for an absent file. So
a link the pass reads can hide a change from the passes that give the
verdict, and each of these ended with exit 2 on 0.13.2 and got `pass` from
the first form of this change:
- an assertion weakened, or a `sys.path` root added, in the target of an
  unchanged link (`tests/test_alias.py`, `tests/conftest.py`), which was
  read as the head's target on both sides;
- a root assertion helper gutted, where the test that uses it exists only as
  a link (`tests/test_calc.py -> ../shared/calc_checks.py`): the search for
  the helper's callers finds no test;
- `|| true` appended to a call of a linked script that runs the suite, or
  of one beneath a directory link (`ci -> tools/ci`): the scan that follows
  the call takes a script it cannot read for one that runs no suite;
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
  when the view can answer for every link of the tree, does it run again
  through the link view. Otherwise the run ends as on 0.13.2, with the same
  refusal.
- A link the view can answer for reads the same on both sides of the range
  (the same link, leading to the same place; for a file the same entry
  there, for a directory nothing changed beneath it) and is not named as
  source (`.py`, a JS or TS suffix). A directory link has no file of such a
  name beneath its target, and gives no file there a CI or runner role its
  own path does not: a file beneath the target has a second name under the
  link, which no pass lists, searches or resolves an import to. A link that
  leads to nothing the tree holds, on both sides, is harmless and is
  refused only when the pass asks for it.
- A run that read links ends with a verdict only when no other reader asked
  either tree for a link or for a path beneath one. The trees note each
  such ask, refused or answered as absent, and one is enough: the run ends
  as on 0.13.2, with the refusal that sent the pass to the view.

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
  beneath, a link named as source, a directory link with source beneath its
  target or one that changes a file's role, a link to a name the tree holds
  in another case, a link to a link and a link into a submodule;
- a run on which another reader asks for a link, or for a path beneath one,
  gets that refusal too: a commit that changes a script which calls a linked
  script, or a script beneath a directory link. The same links are no
  obstacle on a run where nothing but the pass asks for them;
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

from checkwash import engine_ir_intake
from checkwash.change import EngineError
from checkwash.config import Config
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
# A script that calls the suite's runner through a link to it.
LINKED_RUNNER = {**SOURCES, "scripts/ci.sh": b"#!/bin/sh\n./scripts/run-tests.sh\n",
                 "tools/run-tests-impl.sh": b"#!/bin/sh\npytest tests\n"}
LINKED_RUNNER_LINK = {"scripts/run-tests.sh": b"../tools/run-tests-impl.sh"}
# The runner kept in `tools/ci`, and a caller that reaches it through a `ci`
# directory. The testpaths keep a bare `pytest` out of that directory.
CI_SCRIPTS = {"tools/ci/run-tests.sh": b"#!/bin/sh\npytest tests\n",
              "scripts/ci.sh": b"#!/bin/sh\nset -e\n./ci/run-tests.sh\n",
              "setup.cfg": b"[tool:pytest]\ntestpaths = tests\n"}
MASKED_CALL = {"scripts/ci.sh": b"#!/bin/sh\nset -e\n./ci/run-tests.sh || true\n"}


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
    # gave `pass`. The scan's ask for the link is noted, and a run that read
    # links ends with the refusal when any other reader asked for one.
    repo = _repo(tmp_path, LINKED_RUNNER, LINKED_RUNNER_LINK)
    code, stdout, stderr = _check_head(repo, {**NEW_PROVIDER, "scripts/ci.sh": b"#!/bin/sh\n./scripts/run-tests.sh || true\n"})
    assert (code, stdout) == (2, "")
    assert _refusal("scripts/run-tests.sh") in stderr


def test_a_linked_script_that_runs_the_suite_is_no_obstacle_when_only_the_pass_asks_for_it(tmp_path):
    # The same tree, and a commit that leaves `scripts/ci.sh` alone. The scan
    # follows calls from changed scripts only, so nothing but the provider
    # pass asks for the link, and the pass reads it as the script it leads
    # to: the run has the verdict of the tree with a regular
    # `scripts/run-tests.sh`. 0.13.2 ends it with exit 2.
    linked = _judged(_check_head(_repo(tmp_path / "linked", LINKED_RUNNER, LINKED_RUNNER_LINK), NEW_PROVIDER))
    regular = {**LINKED_RUNNER, "scripts/run-tests.sh": LINKED_RUNNER["tools/run-tests-impl.sh"]}
    plain = _judged(_check_head(_repo(tmp_path / "plain", regular, {}), NEW_PROVIDER))
    assert linked == plain
    assert (linked[0], linked[1]["verdict"]) == (1, "block")
    assert {finding["rule"] for finding in linked[1]["findings"]} == {"TEST_PATCHES_SUBJECT"}


def test_a_changed_call_to_a_script_beneath_a_directory_link_keeps_the_refusal(tmp_path):
    # `ci -> tools/ci` is a directory link nothing changes beneath, and the
    # commit appends `|| true` to the call of `./ci/run-tests.sh` in
    # `scripts/ci.sh`. With a regular `ci/run-tests.sh` that blocks. The
    # snapshot answers a path beneath a link as absent, so the scan that
    # follows the call finds no runner there, and a run read through the
    # view and judged would pass. The ask is noted, and the run ends as on
    # 0.13.2.
    repo = _repo(tmp_path / "linked", {**TWIN_MODULES, **CI_SCRIPTS}, {"ci": b"tools/ci"})
    code, stdout, stderr = _check_head(repo, {**ORDINARY_EDIT, **MASKED_CALL})
    assert (code, stdout) == (2, "")
    assert _refusal("ci") in stderr
    regular = {**TWIN_MODULES, **CI_SCRIPTS, "ci/run-tests.sh": CI_SCRIPTS["tools/ci/run-tests.sh"]}
    code, report = _judged(_check_head(_repo(tmp_path / "plain", regular, {}), {**ORDINARY_EDIT, **MASKED_CALL}))
    assert (code, report["verdict"]) == (1, "block")
    assert {finding["rule"] for finding in report["findings"]} == {"CI_WORKFLOW_TOUCHED"}


def test_a_directory_link_with_a_script_beneath_it_is_no_obstacle_when_no_call_changes(tmp_path):
    # The same tree and the ordinary edit alone. `scripts/ci.sh` is unchanged,
    # no scan follows its call, and the run passes, as it does with no link.
    repo = _repo(tmp_path, {**TWIN_MODULES, **CI_SCRIPTS}, {"ci": b"tools/ci"})
    code, report = _judged(_check_head(repo, ORDINARY_EDIT))
    assert (code, report["verdict"], report["findings"]) == (0, "pass", [])


def test_a_linked_script_whose_comment_names_a_runner_is_no_obstacle(tmp_path):
    # pydantic-ai links `.claude/skills/branch-context/check-autoload-safety.sh`
    # to a script that runs nothing and mentions `@pytest.mark.parametrize`
    # in a comment. Every runner token counts as a test command wherever it
    # stands, so a rule that kept a tree unread for a linked script that
    # "runs the suite" kept every one of that tree's commits at exit 2 (the
    # 100 newest, on 2026-11-28). What the run asks for decides instead:
    # nothing but the provider pass asks for this link.
    script = b"#!/usr/bin/env bash\n# e.g. `@pytest.mark.parametrize`, a bare username\necho checked\n"
    files = {**TWIN_MODULES, ".agents/skills/branch-context/check-autoload-safety.sh": script}
    links = {".claude/skills/branch-context/check-autoload-safety.sh":
             b"../../../.agents/skills/branch-context/check-autoload-safety.sh"}
    code, report = _judged(_check_head(_repo(tmp_path, files, links), ORDINARY_EDIT))
    assert (code, report["verdict"], report["findings"]) == (0, "pass", [])


# --- a second name for what lies beneath a directory link -------------------------------------------

def _regular(files, links):
    """The same tree with each link replaced by a regular copy of the file or directory it leads to."""
    import posixpath

    copied = dict(files)
    for link, target in links.items():
        real = posixpath.normpath(posixpath.join(posixpath.dirname(link), target.decode("ascii")))
        if real in files:
            copied[link] = files[real]
        for path, data in files.items():
            if path.startswith(real + "/"):
                copied[link + path[len(real):]] = data
    return copied


HELPER_BENEATH_A_LINK = (
    {"setup.cfg": b"[tool:pytest]\ntestpaths = tests/unit\n",
     "src/calc.py": b"def total():\n    return 3\n",
     "shared/support/__init__.py": b"",
     "shared/support/checks.py": b"def check_total(value):\n    assert value == 3\n",
     "tests/__init__.py": b"", "tests/unit/__init__.py": b"", "tests/integration/__init__.py": b"",
     "tests/integration/test_calc.py": b"def test_smoke():\n    assert True\n",
     "tests/unit/test_calc.py": (b"from src.calc import total\nfrom tests.support.checks import check_total\n\n\n"
                                 b"def test_total():\n    check_total(total())\n")},
    {"tests/support": b"../shared/support"},
    {"tests/unit/test_calc.py": (b"from src.calc import total\nfrom tests.support.checks import check_total\n\n\n"
                                 b"def test_total():\n    total()\n")},
    "tests/support", "ASSERT_REMOVED")
PATCHED_PACKAGE_BENEATH_A_LINK = (
    {**TWIN_MODULES, "setup.cfg": b"[tool:pytest]\ntestpaths = tests\n", "conftest.py": b"",
     "lib/app/__init__.py": b"",
     "lib/app/billing.py": b"def invoice_total(items, tax):\n    return round(sum(items) * (1 + tax), 2)\n",
     "tests/conftest.py": b"import pytest\n",
     "tests/test_billing.py": (b"from app import billing\n\n\ndef test_invoice_total(monkeypatch):\n"
                               b"    items = [10.0, 90.0]\n"
                               b"    assert billing.invoice_total(items, 0.053) == 105.3\n")},
    {"app": b"lib/app"},
    {**ORDINARY_EDIT,
     "tests/conftest.py": (b"import pytest\n\nimport app.billing\n\n\n@pytest.fixture(autouse=True)\n"
                           b"def fixed_total(monkeypatch):\n"
                           b"    monkeypatch.setattr(\"app.billing.invoice_total\", lambda *a: 105.3)\n")},
    "app", "CONFTEST_PATCHES_PROD")
PACKAGE_UNDER_AN_UNCHANGED_SEARCH_ROOT = (
    {**{path: data for path, data in TWIN_MODULES.items() if path != "tests/test_images.py"},
     "setup.cfg": b"[tool:pytest]\ntestpaths = tests\npythonpath = lib\n",
     "impl/billing_pkg/__init__.py": b"def total():\n    return 1\n",
     "tests/test_total.py": b"from billing import total\n\n\ndef test_total():\n    assert total() == 2\n"},
    {"lib/billing": b"../impl/billing_pkg"},
    {**ORDINARY_EDIT, "tests/billing.py": b"def total():\n    return 2\n"},
    "lib/billing", "TEST_PATCHES_SUBJECT")
TESTS_A_CHANGED_ADDOPTS_NAMES = (
    {**{path: data for path, data in TWIN_MODULES.items() if path != "tests/test_images.py"},
     "setup.cfg": b"[tool:pytest]\ntestpaths = tests\n",
     "tests/test_billing.py": (b"def test_total():\n    assert 1 + 2 == 3\n\n\n"
                               b"def test_tax():\n    assert round(1.5) == 2\n"),
     "shared/checks/test_smoke.py": b"def test_smoke():\n    assert True\n"},
    {"checks": b"shared/checks"},
    {**ORDINARY_EDIT, "setup.cfg": b"[tool:pytest]\ntestpaths = tests\naddopts = checks\n"},
    "checks", "CI_WORKFLOW_TOUCHED")
PIPELINE_BENEATH_A_HIDDEN_LINK = (
    {**LICENCE, "billing.py": b"def invoice_total():\n    return 1\n", "conftest.py": b"",
     "tests/test_billing.py": (b"from billing import invoice_total\n\n\n"
                               b"def test_invoice_total():\n    assert invoice_total() == 2\n"),
     "ci/buildkite/pipeline.yml": b"steps:\n  - command: pytest tests\n    env:\n      PYTHONPATH: stubs\n",
     "stubs/README.txt": b"Stubs\n"},
    {**LICENCE_LINK, ".buildkite": b"ci/buildkite"},
    {"stubs/billing.py": b"def invoice_total():\n    return 2\n"},
    "LICENSE", "TEST_PATCHES_SUBJECT")


@pytest.mark.parametrize("files, links, head_files, refused, rule", [
    HELPER_BENEATH_A_LINK, PATCHED_PACKAGE_BENEATH_A_LINK, PACKAGE_UNDER_AN_UNCHANGED_SEARCH_ROOT,
    TESTS_A_CHANGED_ADDOPTS_NAMES, PIPELINE_BENEATH_A_HIDDEN_LINK,
], ids=["a_helper_a_test_stops_calling", "a_package_a_conftest_patches", "a_package_under_an_unchanged_search_root",
        "tests_a_changed_addopts_names", "a_pipeline_a_hidden_link_names"])
def test_a_directory_link_that_gives_a_file_a_second_name_keeps_the_refusal(tmp_path, files, links, head_files,
                                                                           refused, rule):
    # Each tree holds a directory link nothing changes beneath, and a commit
    # that the same tree with a regular copy in the link's place blocks. A
    # file beneath the target has a second name under the link, and what
    # makes the commit a finding is read under that name:
    # - a test stops calling `check_total`, imported from `tests.support`;
    # - a conftest patches a function of `app`, a package behind `app ->
    #   lib/app`;
    # - a new `tests/billing.py` shadows `billing`, which `pythonpath = lib`
    #   finds behind `lib/billing`;
    # - `addopts = checks` makes the tests behind `checks` the run's only
    #   ones;
    # - `.buildkite -> ci/buildkite` makes a pipeline of a file whose own
    #   path gives it no such role, and the pipeline's PYTHONPATH is where
    #   the commit plants a module.
    # No pass lists, searches or resolves the second name, so the second
    # form of this change, which asked only that nothing change beneath the
    # target, gave `pass` on all five. The first four links have source
    # beneath their target; the last changes a file's role. Each run ends as
    # on 0.13.2.
    code, stdout, stderr = _check_head(_repo(tmp_path / "linked", files, links), head_files)
    assert (code, stdout) == (2, "")
    assert _refusal(refused) in stderr
    code, report = _judged(_check_head(_repo(tmp_path / "plain", _regular(files, links), {}), head_files))
    assert (code, report["verdict"]) == (1, "block")
    assert rule in {finding["rule"] for finding in report["findings"]}


SHADOWED = {"src/billing.py": b"def invoice_total():\n    return 1\n", "stubs/README.txt": b"Stubs\n",
            "tests/test_billing.py": (b"from billing import invoice_total\n\n\n"
                                      b"def test_invoice_total():\n    assert invoice_total() == 2\n")}
STUB = {"stubs/billing.py": b"def invoice_total():\n    return 2\n"}
ON_THE_PATH = {"setup.cfg": b"[tool:pytest]\ntestpaths = tests\npythonpath = vendor.d src\n"}
TESTPATHS_ONLY = {"setup.cfg": b"[tool:pytest]\ntestpaths = tests\n"}
ACTION = (b"runs:\n  using: composite\n  steps:\n    - run: pytest tests\n      shell: bash\n      env:\n"
          b"        PYTHONPATH: stubs\n")


@pytest.mark.parametrize("files, links, head_files, refused", [
    ({**ON_THE_PATH, **SHADOWED, **LICENCE}, {**LICENCE_LINK, "vendor.d": b"/proc/self/cwd/stubs"}, STUB, "LICENSE"),
    ({**ON_THE_PATH, **SHADOWED, **LICENCE}, {**LICENCE_LINK, "vendor.d": b"../linked/stubs"}, STUB, "LICENSE"),
    ({**{path: data for path, data in TWIN_MODULES.items() if path != "tests/test_images.py"},
      "setup.cfg": b"[tool:pytest]\ntestpaths = tests\npythonpath = lib\n",
      "impl/billing_bin/__init__.pyc": b"\x00compiled\x00",
      "tests/test_total.py": b"from billing import total\n\n\ndef test_total():\n    assert total() == 2\n"},
     {"lib/billing": b"../impl/billing_bin"},
     {**ORDINARY_EDIT, "tests/billing.py": b"def total():\n    return 2\n"}, "lib/billing"),
    ({**{path: data for path, data in TWIN_MODULES.items() if path != "tests/test_images.py"}, **TESTPATHS_ONLY,
      "tests/test_billing.py": (b"def test_total():\n    assert 1 + 2 == 3\n\n\n"
                                b"def test_tax():\n    assert round(1.5) == 2\n"),
      "shared/doctests/test_usage.txt": b">>> 1 + 1\n2\n"},
     {"checks": b"shared/doctests"},
     {**ORDINARY_EDIT, "setup.cfg": b"[tool:pytest]\ntestpaths = tests\naddopts = checks\n"}, "checks"),
    ({**TESTPATHS_ONLY, **SHADOWED, "Justfile": b"test:\n    pytest -c ci/pytest.ini tests\n",
      "tools/ci/pytest.ini": b"[pytest]\npythonpath = ../../stubs ../../src\n"},
     {"ci": b"tools/ci"}, STUB, "ci"),
    ({**TESTPATHS_ONLY, **LICENCE, "billing.py": b"def invoice_total():\n    return 1\n", "conftest.py": b"",
      "tests/test_billing.py": SHADOWED["tests/test_billing.py"], "stubs/README.txt": b"Stubs\n",
      "tools/test-action/action.yml": ACTION, "ci/actions/README.txt": b"Actions\n"},
     {**LICENCE_LINK, "ci/actions/test": b"../../tools/test-action", ".github/actions": b"../ci/actions"},
     STUB, ".github/actions"),
], ids=["an_absolute_text_into_the_checkout", "a_text_that_leaves_the_tree_and_comes_back", "a_compiled_package",
        "doctest_texts_a_changed_addopts_names", "a_config_a_run_names_through_the_link",
        "a_link_beneath_the_target_of_another"])
def test_a_link_a_checkout_reads_otherwise_than_the_tree_shows_keeps_the_refusal(tmp_path, files, links, head_files,
                                                                                refused):
    # More trees where the commit is a finding only through a link, each a
    # `pass` in an earlier form of this change:
    # - `vendor.d` is on the pythonpath, and leads to `stubs` by a text that
    #   is absolute (`/proc/self/cwd` is the directory pytest runs in) or
    #   that leaves the tree and comes back by the checkout's own name. By
    #   the tree's paths it leads nowhere; the commit plants a module there;
    # - `lib/billing` leads to a package that is compiled alone, which a new
    #   `tests/billing.py` shadows;
    # - `addopts = checks` makes the doctests behind `checks` the run's only
    #   tests;
    # - a `Justfile` runs `pytest -c ci/pytest.ini`, and the config behind
    #   `ci` puts `stubs` on the path;
    # - `.github/actions` leads to a directory that holds a second link, and
    #   the action behind both sets `PYTHONPATH: stubs`.
    # The engine models no compiled module, no doctest text and no name
    # through two links, so a regular copy of these trees does not block
    # either: pytest itself is what goes green. Each run ends as on 0.13.2.
    code, stdout, stderr = _check_head(_repo(tmp_path / "linked", files, links), head_files)
    assert (code, stdout) == (2, "")
    assert _refusal(refused) in stderr


def test_the_policy_directory_behind_a_link_keeps_the_refusal(tmp_path):
    # `.checkwash -> config/checkwash`, where the repository's policy says
    # `fail_on = "warn"`. The policy is read from the base tree at
    # `.checkwash/config.toml`, a path beneath a link, which is absent
    # there: with the defaults in its place the commit's warn-level finding
    # passes, where the tree with a regular `.checkwash` blocks.
    policy = b"[gate]\nfail_on = \"warn\"\n"
    files = {**TWIN_MODULES, **LICENCE, **TESTPATHS_ONLY, "config/checkwash/config.toml": policy}
    head = {**ORDINARY_EDIT, "setup.cfg": b"[tool:pytest]\ntestpaths = tests\n\n[flake8]\nmax-line-length = 100\n"}
    code, stdout, stderr = _check_head(_repo(tmp_path / "linked", files, {**LICENCE_LINK, ".checkwash": b"config/checkwash"}),
                                       head)
    assert (code, stdout) == (2, "")
    assert _refusal("LICENSE") in stderr
    regular = {**files, ".checkwash/config.toml": policy, "LICENSE": LICENCE["py/LICENSE"]}
    code, report = _judged(_check_head(_repo(tmp_path / "plain", regular, {}), head))
    assert (code, report["verdict"]) == (1, "block")
    assert {finding["rule"] for finding in report["findings"]} == {"CI_WORKFLOW_TOUCHED"}


def test_a_reader_that_takes_a_refused_link_for_unknown_keeps_the_refusal(tmp_path):
    # `envs/dev/pyvenv.cfg` is a link, and the commit moves a test into
    # `envs/dev`. pytest does not collect from a virtual environment, so the
    # test is disabled, and the tree with a regular `pyvenv.cfg` blocks. The
    # collection model asks the snapshot for the marker, is refused, and
    # takes the directory for one it knows nothing of. That ask is noted:
    # the scan of a changed script's calls is not the only reader a link
    # keeps something from.
    files = {**TWIN_MODULES, **LICENCE, "config/pyvenv.cfg": b"home = /usr/bin\n",
             "envs/dev/README.txt": b"An environment\n", "tests/test_calc.py": b"def test_total():\n    assert 1 + 2 == 3\n"}
    links = {**LICENCE_LINK, "envs/dev/pyvenv.cfg": b"../../config/pyvenv.cfg"}
    moved = {**ORDINARY_EDIT, "envs/dev/test_calc.py": files["tests/test_calc.py"]}

    def check(repo):
        _write(repo, moved)
        git(repo, "add", "--", *moved)
        git(repo, "rm", "--cached", "-q", "tests/test_calc.py")
        return _check(repo)

    code, stdout, stderr = check(_repo(tmp_path / "linked", files, links))
    assert (code, stdout) == (2, "")
    assert _refusal("LICENSE") in stderr
    code, report = _judged(check(_repo(tmp_path / "plain", _regular(files, links), {})))
    assert (code, report["verdict"]) == (1, "block")
    assert "TEST_DISABLED" in {finding["rule"] for finding in report["findings"]}


def test_a_link_to_a_name_the_tree_holds_in_another_case_keeps_the_refusal(tmp_path):
    # `vendor.d -> Stubs`, in a tree that holds `stubs/`: nothing, by the
    # tree's own spelling, and the directory itself in a checkout that folds
    # case. `vendor.d` is on the pythonpath, and the commit plants
    # `stubs/billing.py`.
    files = {**LICENCE, "setup.cfg": b"[tool:pytest]\ntestpaths = tests\npythonpath = vendor.d src\n",
             "src/billing.py": b"def invoice_total():\n    return 1\n", "stubs/README.txt": b"Stubs\n",
             "tests/test_billing.py": (b"from billing import invoice_total\n\n\n"
                                       b"def test_invoice_total():\n    assert invoice_total() == 2\n")}
    repo = _repo(tmp_path, files, {**LICENCE_LINK, "vendor.d": b"Stubs"})
    code, stdout, stderr = _check_head(repo, {"stubs/billing.py": b"def invoice_total():\n    return 2\n"})
    assert (code, stdout) == (2, "")
    assert _refusal("LICENSE") in stderr


def test_a_run_a_link_still_ends_after_the_view_ends_with_the_refusal_it_had(tmp_path):
    # `LICENSE` is a link the view reads, and `zz` one that leads nowhere,
    # which the pass asks for as well. 0.13.2 ends on `LICENSE`, the first
    # of the two. Read through the view the pass gets past it and is refused
    # on `zz`: the run ends with the refusal it had, not with a new one.
    repo = _repo(tmp_path, {**SOURCES, **LICENCE}, {**LICENCE_LINK, "zz": b"nowhere/at/all"})
    code, stdout, stderr = _check_head(repo, NEW_PROVIDER)
    assert (code, stdout) == (2, "")
    assert _refusal("LICENSE") in stderr and _refusal("zz") not in stderr


def test_a_sweep_refuses_a_commit_that_changes_a_link_s_target(tmp_path):
    # The sweep gives the view each commit's parent as its base. With the
    # commit itself in that place nothing would differ between the two ends,
    # and the changed target of `.github/workflows/CLAUDE.md` would be read
    # as if it had always been so.
    repo = _repo(tmp_path, {**TWIN_MODULES, **AGENT_FILES}, CI_ROLE_LINK)
    edit = {**ORDINARY_EDIT, ".github/workflows/AGENTS.md": b"# Workflows, revised\n"}
    _write(repo, edit)
    git(repo, "add", "--", *edit)
    git(repo, "commit", "-m", "head")
    result = sweep(str(repo), "HEAD", 5, datetime.date(2026, 11, 27))
    assert (result.commits, result.errors, result.skipped) == (0, 1, 1)


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
    # `tests/shared`, which no norecursedirs pattern stops. `common` holds a
    # data file and nothing a second name would matter for, so the link is
    # read as an opaque directory, and what the run can reach decides.
    repo = _repo(tmp_path, {**SOURCES, "common/fixtures.json": b"{}\n"}, {"tests/shared": b"../common"})
    code, stdout, stderr = _check_head(repo, NEW_PROVIDER)
    assert (code, stdout) == (2, "")
    assert (f"checkwash engine error: EngineError: {DIRECTORY_LINK} tests/shared: "
            "pytest's collection can reach it") in stderr


def test_a_directory_link_an_import_can_resolve_inside_fails_closed_naming_it(tmp_path):
    # `billing -> impl/billing` at the root, which `pythonpath = .` puts on
    # the import path: the test's `from billing import total` can resolve
    # inside the link. `testpaths` keeps pytest's collection out of it, so
    # the import is what refuses. The directory holds a data file and no
    # module: with a `.py` file or a compiled one beneath it the link would
    # keep the tree unread, and the run its first refusal. With no source
    # there the tree holds no second provider of `billing`, so the ordinary
    # edit beside a twin module is what takes the pass to its reads.
    files = {**TWIN_MODULES, "setup.cfg": b"[tool:pytest]\ntestpaths = tests\npythonpath = .\n",
             "impl/billing/rates.csv": b"rate\n0.05\n",
             "tests/test_total.py": b"from billing import total\n\n\ndef test_total():\n    assert total() == 2\n"}
    repo = _repo(tmp_path, files, {"billing": b"impl/billing"})
    code, stdout, stderr = _check_head(repo, {**ORDINARY_EDIT, "tests/billing.py": b"def total():\n    return 2\n"})
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
# One of exactly the limit: the doubled slash is an empty step of the walk.
AT_THE_TEXT_LIMIT = b"./" * (MAX_LINK_TEXT_BYTES // 2 - 5) + b"/AGENTS.md"
assert len(OVER_THE_TEXT_LIMIT) == MAX_LINK_TEXT_BYTES + 3 and len(UNDER_THE_TEXT_LIMIT) == MAX_LINK_TEXT_BYTES - 1
assert len(AT_THE_TEXT_LIMIT) == MAX_LINK_TEXT_BYTES


@pytest.fixture
def snapshot(tmp_path):
    """The head of a tree whose links are all ones the view reads, or lead to nothing."""
    links = {**DIRECTORY_LINK_SHAPE, **CI_ROLE_LINK, **RUNNER_SUFFIX_LINK, **DOT_LESS_FILE_LINK, **DOTTED_LINKS,
             "LOST": b"gone", "BEYOND_A_FILE": b"AGENTS.md/inside",
             "NEAR": UNDER_THE_TEXT_LIMIT, "EXACT": AT_THE_TEXT_LIMIT, "NOTES": b".agents/skills"}
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
    assert opaque == [".claude/skills/add-new-model/", "NOTES/"]
    assert ".claude/skills/add-new-model" not in listed and "NOTES" not in listed
    # A link to a file, and one that leads to nothing, stay listed as paths.
    for link in ("status", "CLAUDE.md", ".github/workflows/CLAUDE.md", "LOST", "BEYOND_A_FILE", "NEAR", "EXACT"):
        assert link in listed
    # Every other reader lists the snapshot itself: each link is a path there.
    plain = snapshot.list_paths()
    assert not any(isinstance(path, SymlinkedDirectory) for path in plain)
    assert ".claude/skills/add-new-model" in plain and "NOTES" in plain
    assert sorted(str(path).rstrip("/") for path in listed) == sorted(plain)


def test_the_view_reads_a_file_link_as_its_target_and_the_snapshot_refuses_it(snapshot):
    view = _view(snapshot)
    script = AGENT_FILES[".agents/skills/branch-context/status.sh"]
    read = view.read_many(["status", ".claude/skills/branch-context/status.sh", ".github/workflows/CLAUDE.md",
                           "docs/CLAUDE.md", "NEAR", "AGENTS.md", "absent"])
    # A text of exactly the limit is read too.
    assert view.read_many(["EXACT"]) == {"EXACT": AGENT_FILES["AGENTS.md"]}
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


@pytest.mark.parametrize("link", ["LOST", "BEYOND_A_FILE", ".claude/skills/add-new-model", "NOTES"])
def test_the_view_refuses_a_link_it_cannot_read_as_a_file(snapshot, link):
    # A missing target, a path through a regular file, and a directory link
    # asked for as a file: the snapshot's refusal, unchanged.
    with pytest.raises(EngineError) as refused:
        _view(snapshot).read_many([link])
    assert str(refused.value) == f"{NONREGULAR} {link} (a symlink)"


def test_the_view_refuses_a_read_inside_a_directory_link(snapshot):
    with pytest.raises(EngineError) as refused:
        _view(snapshot).read_many([".claude/skills/add-new-model/SKILL.md"])
    assert str(refused.value) == (f"{DIRECTORY_LINK} .claude/skills/add-new-model: "
                                  ".claude/skills/add-new-model/SKILL.md lies inside it")


RUNS_THE_SUITE = {"tools/impl.sh": b"#!/bin/sh\npytest tests\n", "tools/inert.sh": b"#!/bin/sh\necho done\n"}
# Directories that each hold one thing a second name would change the meaning of.
SECOND_NAMES = {"built/billing/__init__.pyc": b"\x00compiled\x00", "confs/pytest.ini": b"[pytest]\n",
                "loud/Helper.PY": b"VALUE = 1\n", "texts/test_usage.txt": b">>> 1 + 1\n2\n",
                "caf\u00e9/notes.txt": b"Notes\n"}


@pytest.mark.parametrize("link, text, links, submodules", [
    ("CHAIN", b"CLAUDE.md", {}, ()),
    ("LONG", OVER_THE_TEXT_LIMIT, {}, ()),
    ("docs/conftest.py", b"../AGENTS.md", {}, ()),
    ("pkg/alias.py", b"../src/billing.py", {}, ()),
    ("web/app.test.TS", b"../AGENTS.md", {}, ()),
    ("pkg/models/notes.py", b"../../docs", {}, ()),
    ("gone.py", b"nowhere/at/all", {}, ()),
    ("code", b"src", {}, ()),
    ("up", b".", {}, ()),
    ("Docs", b"DOCS", {}, ()),
    ("accent", "cafe\u0301".encode("utf-8"), {}, ()),
    ("OUTSIDE", b"../elsewhere/file", {}, ()),
    ("BACK", b"../checkout/docs", {}, ()),
    ("ABSOLUTE", b"/proc/self/cwd/docs", {}, ()),
    ("lib", b"built", {}, ()),
    ("cfg", b"confs", {}, ()),
    ("shout", b"loud", {}, ()),
    ("checks", b"texts", {}, ()),
    ("outer", b"tools", {"tools/inner": b"../AGENTS.md"}, ()),
    (".checkwash", b".agents/skills", {}, ()),
    (".greenwash/allow.toml", b"../AGENTS.md", {}, ()),
    ("vendored", b".vendor/lib", {}, (".vendor/lib",)),
    ("vendored-readme", b".vendor/lib/README", {}, (".vendor/lib",)),
    ("around", b".vendor", {}, (".vendor/lib",)),
    ("ODD", b"docs\\AGENTS.md", {}, ()),
], ids=["a_link_to_a_link", "text_over_the_limit", "a_conftest_name", "a_python_module_name", "a_typescript_name",
        "a_directory_link_named_as_source", "a_link_to_nothing_named_as_source", "a_directory_that_holds_source",
        "the_root_of_a_tree_that_holds_source", "a_name_the_tree_holds_in_another_case",
        "a_name_the_tree_holds_in_another_unicode_form", "a_text_that_leaves_the_tree",
        "a_text_that_leaves_the_tree_and_names_a_checkout", "an_absolute_text", "a_directory_that_holds_a_compiled_module",
        "a_directory_that_holds_a_pytest_config", "a_directory_that_holds_source_in_capitals",
        "a_directory_that_holds_a_doctest_text", "a_directory_that_holds_a_link", "the_policy_directory",
        "a_policy_file",
        "a_submodule", "inside_a_submodule", "a_directory_that_holds_a_submodule", "text_the_walk_does_not_read"])
def test_one_link_no_pass_could_safely_miss_leaves_the_view_unreadable(tmp_path, link, text, links, submodules):
    # Each tree holds the links of `snapshot`, all readable, and one more.
    # Nothing changes in the range. The one link is enough: the view answers
    # for no link, and names it.
    every = {**DIRECTORY_LINK_SHAPE, **CI_ROLE_LINK, **DOT_LESS_FILE_LINK, **DOTTED_LINKS, link: text, **links}
    repo = _repo(tmp_path, {**SOURCES, **AGENT_FILES, **RUNS_THE_SUITE, **SECOND_NAMES}, every, submodules)
    view = _view(GitSnapshot(repo, "HEAD", side="head"))
    assert not view.readable()
    assert view.unreadable() == (link,)
    for call in (view.list_paths, lambda: view.read_many(["status"]),
                 lambda: view.begin(EngineError("the refusal that sent the pass here"), view.mark())):
        with pytest.raises(EngineError) as refused:
            call()
        assert str(refused.value) == f"{NONREGULAR} {link} (a symlink)"


def test_a_linked_script_that_runs_nothing_is_read(tmp_path):
    # A link with a script's name, leading to a script that runs no suite.
    links = {"scripts/run-tests.sh": b"../tools/inert.sh", "scripts/Build.CMD": b"../tools/inert.sh"}
    view = _view(GitSnapshot(_repo(tmp_path, {**SOURCES, **RUNS_THE_SUITE}, links), "HEAD", side="head"))
    assert view.readable()
    assert view.read_many(["scripts/run-tests.sh"]) == {"scripts/run-tests.sh": RUNS_THE_SUITE["tools/inert.sh"]}


def test_a_linked_script_that_runs_the_suite_is_read_too(tmp_path):
    # The view answers for a linked script whatever it holds. What another
    # reader would have made of the link is settled by what the run asks the
    # trees for (`settle`), not by the script's text.
    links = {"scripts/run-tests.sh": b"../tools/impl.sh", "scripts/Build.CMD": b"../tools/impl.sh"}
    view = _view(GitSnapshot(_repo(tmp_path, {**SOURCES, **RUNS_THE_SUITE}, links), "HEAD", side="head"))
    assert view.readable()
    assert view.read_many(["scripts/run-tests.sh", "scripts/Build.CMD"]) == {
        "scripts/run-tests.sh": RUNS_THE_SUITE["tools/impl.sh"], "scripts/Build.CMD": RUNS_THE_SUITE["tools/impl.sh"]}


@pytest.mark.parametrize("suffix", [".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts"])
def test_a_link_with_any_source_suffix_leaves_the_view_unreadable(tmp_path, suffix):
    # Each suffix the engine's passes read as source, on a link to a file
    # that is no source itself.
    link = "web/app" + suffix
    view = _view(GitSnapshot(_repo(tmp_path, {**SOURCES, **AGENT_FILES}, {link: b"../AGENTS.md"}), "HEAD", side="head"))
    assert view.unreadable() == (link,)


@pytest.mark.parametrize("beneath", [
    "shared/notes/helper.py", "shared/notes/deep/er/widget.tsx", "shared/notes/conftest.py",
    "shared/notes/mod.pyc", "shared/notes/mod.pyo", "shared/notes/mod.pyd", "shared/notes/mod.so",
    "shared/notes/deps.zip", "shared/notes/pkg.egg", "shared/notes/pkg-1.0-py3-none-any.whl",
    "shared/notes/test_usage.txt",
    "shared/notes/pytest.toml", "shared/notes/.pytest.toml", "shared/notes/pytest.ini", "shared/notes/.pytest.ini",
    "shared/notes/pyproject.toml", "shared/notes/tox.ini", "shared/notes/setup.cfg",
])
def test_a_directory_link_with_source_beneath_its_target_leaves_the_view_unreadable(tmp_path, beneath):
    # The file has a second name under the link, `notes/...`, that no pass
    # lists, searches or resolves an import to: source, each compiled form,
    # an archive that can stand on the import path, a doctest text, and each
    # name pytest takes for a config.
    files = {**AGENT_FILES, "shared/notes/README.md": b"# Notes\n", beneath: b"VALUE = 1\n"}
    view = _view(GitSnapshot(_repo(tmp_path, files, {"notes": b"shared/notes"}), "HEAD", side="head"))
    assert view.unreadable() == ("notes",)


def test_a_directory_link_with_a_source_named_link_beneath_its_target_leaves_the_view_unreadable(tmp_path):
    files = {**AGENT_FILES, "shared/notes/README.md": b"# Notes\n"}
    links = {"notes": b"shared/notes", "shared/notes/alias.py": b"../../AGENTS.md"}
    view = _view(GitSnapshot(_repo(tmp_path, files, links), "HEAD", side="head"))
    assert view.unreadable() == ("notes", "shared/notes/alias.py")


def test_a_directory_link_with_no_source_beneath_its_target_is_read(tmp_path):
    # What pydantic-ai keeps beneath a skill directory: a Markdown file, a
    # script with no suffix and a table.
    files = {**AGENT_FILES, ".agents/skills/adopt-pr/SKILL.md": b"# Adopt\n",
             ".agents/skills/adopt-pr/fetch-resolved-threads": b"#!/usr/bin/env bash\necho threads\n",
             ".agents/skills/adopt-pr/labels.tsv": b"name\tcolour\n"}
    view = _view(GitSnapshot(_repo(tmp_path, files, {".claude/skills/adopt-pr": b"../../.agents/skills/adopt-pr"}),
                             "HEAD", side="head"))
    assert view.readable()
    assert list(view.aliases()) == [
        (".claude/skills/adopt-pr/SKILL.md", ".agents/skills/adopt-pr/SKILL.md"),
        (".claude/skills/adopt-pr/fetch-resolved-threads", ".agents/skills/adopt-pr/fetch-resolved-threads"),
        (".claude/skills/adopt-pr/labels.tsv", ".agents/skills/adopt-pr/labels.tsv"),
    ]
    # Neither name of any of them is a CI file or a runner file.
    assert not engine_ir_intake._alias_changes_a_role(view, Config())


def test_a_directory_link_that_makes_a_runner_file_of_a_file_is_not_read_through(tmp_path):
    # `scripts/tools -> ../ci/tools`. Every file beneath `scripts/` is a
    # runner file to the collection inventory, and `ci/tools/steps.txt` is
    # none under its own path: its pytest command would count for the reach
    # of a run under a name that no pass lists.
    files = {**AGENT_FILES, "ci/tools/steps.txt": b"pytest tests\n"}
    view = _view(GitSnapshot(_repo(tmp_path, files, {"scripts/tools": b"../ci/tools"}), "HEAD", side="head"))
    assert view.readable()
    assert list(view.aliases()) == [("scripts/tools/steps.txt", "ci/tools/steps.txt")]
    assert engine_ir_intake._alias_changes_a_role(view, Config())


def test_more_second_names_than_one_run_compares_leave_the_view_unused(tmp_path, monkeypatch):
    # The comparison is bounded. A tree with more second names than the
    # bound is not looked through: the view is not used.
    files = {**AGENT_FILES, ".agents/skills/adopt-pr/SKILL.md": b"# Adopt\n",
             ".agents/skills/adopt-pr/notes.md": b"# Notes\n", ".agents/skills/adopt-pr/labels.tsv": b"name\n"}
    view = _view(GitSnapshot(_repo(tmp_path, files, {".claude/skills/adopt-pr": b"../../.agents/skills/adopt-pr"}),
                             "HEAD", side="head"))
    assert not engine_ir_intake._alias_changes_a_role(view, Config())
    monkeypatch.setattr(engine_ir_intake, "_MAX_LINK_ALIASES", 2)
    assert engine_ir_intake._alias_changes_a_role(view, Config())


def test_a_link_to_the_root_of_the_tree_is_never_read(tmp_path):
    # `up -> .` leads to the whole tree. Every path lies beneath its target,
    # the link itself among them, so the tree holds itself under `up/` to
    # any depth, and any change in a range is one beneath it.
    repo = _repo(tmp_path, {"AGENTS.md": b"# Agents\n", "docs/guide.txt": b"Guide\n"}, {"up": b"."})
    assert _view(GitSnapshot(repo, "HEAD", side="head")).unreadable() == ("up",)


def test_a_directory_link_a_file_is_removed_beneath_keeps_the_view_unreadable(tmp_path):
    # Only the base holds the removed path: a change is looked for at both ends.
    repo = _repo(tmp_path, {"AGENTS.md": b"# Agents\n", "kept/notes.txt": b"Notes\n", "kept/old.txt": b"Old\n"},
                 {"NOTES": b"kept"})
    git(repo, "rm", "--cached", "-q", "kept/old.txt")
    git(repo, "commit", "-m", "head")
    view = link_view_of(GitSnapshot(repo, "HEAD", side="head"), GitSnapshot(repo, "HEAD~1", side="base"))
    assert view.unreadable() == ("NOTES",)


def test_a_link_spelled_as_the_tree_spells_its_target_is_read(tmp_path):
    # The other side of the row above that holds `Docs -> DOCS`: the same
    # link with its target's own spelling is a directory link like any other.
    view = _view(GitSnapshot(_repo(tmp_path, {**AGENT_FILES}, {"Docs": b"docs"}), "HEAD", side="head"))
    assert view.readable()
    assert [path for path in view.list_paths() if isinstance(path, SymlinkedDirectory)] == ["Docs/"]


# --- what a run asked the trees for ---------------------------------------------------------------

def test_a_tree_notes_each_ask_for_a_link_or_for_a_path_beneath_one(snapshot):
    view = _view(snapshot)
    # Paths no link stands before: present, absent, and absent in a directory the tree does not hold.
    assert snapshot.read("AGENTS.md") == AGENT_FILES["AGENTS.md"]
    assert snapshot.read("absent") is None
    assert snapshot.read_many(["AGENTS.md", "absent", "nowhere/absent.sh"])["nowhere/absent.sh"] is None
    assert snapshot.definitely_lacks("nowhere/absent.sh")
    assert snapshot.config_modes(["pytest.ini", "AGENTS.md"]) == {"pytest.ini": None, "AGENTS.md": b"100644"}
    # Beneath a regular file there is nothing either, and no link is the reason.
    assert snapshot.read_many(["AGENTS.md/inside"]) == {"AGENTS.md/inside": None}
    assert view.asked() == ()
    # A path beneath a link, to a directory or to a file, is absent to every reader.
    assert snapshot.read(".claude/skills/add-new-model/SKILL.md") is None
    assert snapshot.read_many(["CLAUDE.md/inside", "NOTES/src/billing.py"]) == {
        "CLAUDE.md/inside": None, "NOTES/src/billing.py": None}
    assert snapshot.definitely_lacks("LOST/run.sh")
    assert snapshot.config_modes(["docs/CLAUDE.md/pytest.ini"]) == {"docs/CLAUDE.md/pytest.ini": None}
    with pytest.raises(EngineError, match="traverses a non-directory"):
        snapshot.read_config_many([".claude/skills/add-new-model/setup.cfg"])
    # The link itself is refused by the single reader and by the batch reader.
    with pytest.raises(EngineError):
        snapshot.read("status")
    with pytest.raises(EngineError):
        snapshot.read_many(["AGENTS.md", ".github/workflows/CLAUDE.md"])
    assert sorted(set(view.asked())) == [
        ".claude/skills/add-new-model/SKILL.md", ".claude/skills/add-new-model/setup.cfg",
        ".github/workflows/CLAUDE.md", "CLAUDE.md/inside", "LOST/run.sh", "NOTES/src/billing.py",
        "docs/CLAUDE.md/pytest.ini", "status"]


def test_a_tree_without_a_link_notes_nothing(tmp_path):
    snapshot = GitSnapshot(_repo(tmp_path, {**SOURCES, **AGENT_FILES}, {}), "HEAD", side="head")
    view = _view(snapshot)
    assert snapshot.read("absent/inside.sh") is None
    assert snapshot.read_many(["AGENTS.md/inside", "status"]) == {"AGENTS.md/inside": None, "status": None}
    assert snapshot.definitely_lacks("ci/run-tests.sh")
    assert view.asked() == ()


REFUSAL = EngineError("the refusal that sent the pass to the view")


def test_a_view_the_pass_never_read_through_settles_nothing(snapshot):
    # A run the snapshot carried through is the run it was: whatever its
    # readers asked for, the view has no say.
    view = _view(snapshot)
    assert snapshot.read("NOTES/src/billing.py") is None
    assert view.asked() == ("NOTES/src/billing.py",)
    view.settle()


def test_a_run_that_read_links_keeps_its_verdict_when_no_other_reader_asked_for_one(snapshot):
    view = _view(snapshot)
    view.begin(REFUSAL, view.mark())
    # The pass reads through the view, and other readers read what no link stands before.
    assert view.read_many(["status", "AGENTS.md", "absent"])["status"] == AGENT_FILES[
        ".agents/skills/branch-context/status.sh"]
    assert snapshot.read("src/billing.py") == SOURCES["src/billing.py"]
    assert snapshot.read("tests/absent.py") is None
    assert view.asked() == ()
    view.settle()


@pytest.mark.parametrize("ask", [
    lambda head, base, view: head.read("NOTES/src/billing.py"),
    lambda head, base, view: head.read_many(["CLAUDE.md/inside"]),
    lambda head, base, view: head.definitely_lacks(".claude/skills/add-new-model/run-tests.sh"),
    lambda head, base, view: base.read(".claude/skills/add-new-model/SKILL.md"),
    lambda head, base, view: pytest.raises(EngineError, head.read, "status"),
    lambda head, base, view: pytest.raises(EngineError, head.read_many, [".github/workflows/CLAUDE.md"]),
    lambda head, base, view: pytest.raises(EngineError, view.read_many, [".claude/skills/add-new-model/SKILL.md"]),
], ids=["a_path_beneath_a_directory_link", "a_path_beneath_a_file_link", "a_path_the_tree_is_asked_whether_it_lacks",
        "a_path_beneath_a_link_at_the_base", "the_link_itself", "the_link_itself_in_a_batch",
        "a_read_inside_a_directory_link_that_the_view_refuses"])
def test_a_run_that_read_links_ends_with_the_refusal_when_a_reader_asked_for_one(snapshot, ask):
    # Each ask is refused, or answered as absent, and a caller may go on as
    # if no such file existed. One is enough: the run ends with the refusal
    # that sent the pass to the view, the object itself.
    base = GitSnapshot(snapshot.repo, "HEAD", side="base")
    view = link_view_of(snapshot, base)
    view.begin(REFUSAL, view.mark())
    ask(snapshot, base, view)
    with pytest.raises(EngineError) as settled:
        view.settle()
    assert settled.value is REFUSAL


def test_the_refused_attempt_s_asks_for_links_the_view_reads_are_dropped(snapshot):
    # The pass runs again from the start through the view, which answers for
    # these links, so the attempt that was refused on one of them is not
    # another reader's ask.
    view = _view(snapshot)
    mark = view.mark()
    for batch in (["AGENTS.md", "status"], [".claude/skills/add-new-model"], [".github/workflows/CLAUDE.md"]):
        with pytest.raises(EngineError):
            snapshot.read_many(batch)
    view.begin(REFUSAL, mark)
    assert view.asked() == ()
    view.settle()


def test_every_other_ask_of_the_refused_attempt_and_every_ask_before_it_is_kept(snapshot):
    # A path beneath a link, which the attempt was told is absent, and a link
    # that leads nowhere are not answered by the view, and something the
    # pass consulted may remember what it was told. What any reader asked
    # before the pass began is kept too, a link the view reads among it.
    view = _view(snapshot)
    assert snapshot.read("NOTES/asked/before/the/pass") is None
    with pytest.raises(EngineError):
        snapshot.read("status")
    mark = view.mark()
    assert snapshot.read("NOTES/asked/by/the/attempt") is None
    with pytest.raises(EngineError):
        snapshot.read_many(["LOST"])
    with pytest.raises(EngineError):
        snapshot.read_many(["status"])
    view.begin(REFUSAL, mark)
    assert view.asked() == ("NOTES/asked/before/the/pass", "status", "NOTES/asked/by/the/attempt", "LOST")
    with pytest.raises(EngineError) as settled:
        view.settle()
    assert settled.value is REFUSAL


def test_a_view_counts_what_the_trees_were_asked_before_it_was_made(snapshot):
    # A range check makes its two trees, reads the repository's policy from
    # the base tree, and only then makes the view and runs its one
    # analysis. What a link kept from that first read counts as well.
    base = GitSnapshot(snapshot.repo, "HEAD", side="base")
    assert base.read("NOTES/add-new-model/config.toml") is None
    view = link_view_of(snapshot, base)
    view.begin(REFUSAL, view.mark())
    assert view.asked() == ("NOTES/add-new-model/config.toml",)
    with pytest.raises(EngineError) as settled:
        view.settle()
    assert settled.value is REFUSAL


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

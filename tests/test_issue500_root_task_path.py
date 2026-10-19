"""Issue #500: at the root, a `--task` path the base tree holds only by another name.

At the root, `check --task` reads the contract from the base tree at the path
`--task` names relative to `--repo`. When the base had no file there, the run
opened `--task` from the working tree and said nothing. Git reads no path
through a tree entry that is not a directory and matches names byte for byte,
while the working tree follows a symlink and, on a case-insensitive checkout,
matches any case. So `ci/TASK.md` over a committed directory symlink `ci`, or
`task.md` for a committed `TASK.md`, read the head's contract. Such a path is
now an engine error naming the base entry: exit 2, or the non-blocking
hook-json message (#414). A task file the base really lacks is still read from
the working tree, with one stderr line; stdout and the exit code are the
verdict's. `--repo` reached through a symlink to the root already fails closed,
which a test pins both ways (KNOWN-ISSUES-v0.8.0 row 21).

`doctor` finds the repository root with its own 5-second timeout and no stdin,
as its later queries do; `check` keeps the general 60 seconds and the
inherited stdin.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from checkwash.cli import main
from checkwash.gitio import snapshot as snapshots

ROOT = Path(__file__).resolve().parents[1]
ENV = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONUTF8": "1",
       "GREENWASH_TODAY": "2026-01-01", "NO_COLOR": "1"}

CALC = b"def add(a, b):\n    return a + b\n"
TEST = b"from pkg.calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"
WEAK = TEST.replace(b"assert add(2, 3) == 5", b"assert add(2, 3) > 0")
FREEZE = b"---\ncheckwash:\n  oracle_freeze: true\n---\n# Task\n"
LOOSE = b"---\ncheckwash:\n  oracle_freeze: false\n---\n# Notes\n"
GITLINK = "1" * 40
# The stderr line of the fallback, without its line ending (text-mode stderr
# writes \r\n on Windows).
FALLBACK = ("checkwash: --task TASK.md: the base tree has no file at TASK.md, so the contract is read "
            "from the working-tree copy, which the change controls; commit the task file to read it "
            "from the base")


def _git(repo, *args, data=None):
    result = subprocess.run(["git", "-C", str(repo), *args], input=data, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    return result.stdout


def _write(root, path, data):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def _commit(repo, message, *paths):
    """Commit the named paths only: `git add -A` would stage a working-tree
    symlink as the host sees it, not as the test wrote the base tree."""
    _git(repo, "add", "--", *paths)
    _git(repo, "commit", "-q", "-m", message)


def _init(root):
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.name", "root-task-test")
    _git(root, "config", "user.email", "root-task@example.invalid")
    _git(root, "config", "commit.gpgsign", "false")
    _git(root, "config", "core.autocrlf", "false")
    return root


@pytest.fixture
def repo(tmp_path):
    """A manifest, a package and its test, committed."""
    root = _init(tmp_path / "repo")
    _write(root, "pyproject.toml", b'[project]\nname = "calc"\nversion = "0.1.0"\n')
    _write(root, "pkg/__init__.py", b"")
    _write(root, "pkg/calc.py", CALC)
    _write(root, "tests/test_calc.py", TEST)
    _commit(root, "base", ".")
    return root


def _run(cwd, *args):
    """The CLI started in `cwd`."""
    return subprocess.run([sys.executable, "-m", "checkwash", *args], cwd=str(cwd),
                          env=ENV, capture_output=True, timeout=120)


def _dir_symlink(link, target):
    """A directory symlink, or a skip where the host cannot make one."""
    try:
        os.symlink(target, link, target_is_directory=True)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlinks unavailable: {exc}")


def _frozen(result):
    assert result.returncode == 1, result.stderr.decode("utf-8")
    weakened = [f for f in json.loads(result.stdout)["findings"] if f["rule"] == "ASSERT_WEAKENED"]
    assert weakened, result.stdout
    return "ORACLE_FREEZE" in weakened[0]["escalators"]


def _refused(result, code, message):
    """The engine error naming the base entry; no contract was read."""
    err = result.stderr.decode("utf-8")
    assert result.returncode == code, err
    assert f"checkwash engine error: {message}" in err, err
    assert "working-tree copy" not in err, err
    if code == 0:  # The hook-json warning (#414) carries no decision.
        payload = json.loads(result.stdout)
        assert "decision" not in payload and message in payload["systemMessage"], payload
    else:
        assert result.stdout == b"", result.stdout


def _tree(repo, files):
    """A commit of exactly `files`, {path: (mode, data)}, written as Git
    objects, so the tree holds a symlink or submodule on every host."""
    _git(repo, "read-tree", "--empty")
    for path, (mode, data) in sorted(files.items()):
        oid = data if mode == "160000" else _git(repo, "hash-object", "-w", "--stdin", data=data).decode("ascii").strip()
        _git(repo, "update-index", "--add", "--cacheinfo", f"{mode},{oid},{path}")
    tree = _git(repo, "write-tree").decode("ascii").strip()
    return _git(repo, "commit-tree", tree, data=b"owned tree\n").decode("ascii").strip()


@pytest.fixture
def owned(tmp_path):
    return _init(tmp_path / "owned")


# --- the engine error at the root ----------------------------------------------------------------

@pytest.mark.parametrize("fmt,code", [("json", 2), ("hook-json", 0)])
def test_a_task_path_through_a_committed_directory_symlink_is_an_engine_error(repo, fmt, code):
    # The issue's reproduction. Git does not descend through the tree entry
    # of mode 120000, so `<base>:ci/TASK.md` is missing, and the fallback
    # opened the head's loosened contract through the working-tree link. The
    # base entry is written as a symlink blob, so the base tree holds one
    # whatever the host's Git makes of the link.
    _write(repo, "contracts/TASK.md", FREEZE)
    _commit(repo, "contract", "contracts/TASK.md")
    _dir_symlink(repo / "ci", "contracts")
    oid = _git(repo, "hash-object", "-w", "--stdin", data=b"contracts").decode("ascii").strip()
    _git(repo, "update-index", "--add", "--cacheinfo", f"120000,{oid},ci")
    _git(repo, "commit", "-q", "-m", "ci links to contracts")
    _write(repo, "tests/test_calc.py", WEAK)
    _commit(repo, "weaken", "tests/test_calc.py")
    (repo / "contracts" / "TASK.md").write_bytes(LOOSE)
    result = _run(repo, "check", "HEAD~1..HEAD", "--task", "ci/TASK.md", "--format", fmt)
    _refused(result, code, "--task ci/TASK.md maps to ci/TASK.md, but ci in the base tree is a symlink, "
                           "not a directory; name the task file by its path in the base tree")


@pytest.mark.parametrize("fmt,code", [("json", 2), ("hook-json", 0)])
def test_a_task_path_in_another_case_than_the_base_is_an_engine_error(repo, fmt, code):
    # Tree lookups are byte-exact, so `task.md` misses the base's `TASK.md`,
    # and on a case-insensitive checkout the operating system opened the
    # head's `TASK.md`. Renaming the file on disk after the commits gives the
    # mismatch on every platform, as #416's directory test does.
    _write(repo, "TASK.md", FREEZE)
    _commit(repo, "contract", "TASK.md")
    _write(repo, "tests/test_calc.py", WEAK)
    _commit(repo, "weaken", "tests/test_calc.py")
    os.rename(repo / "TASK.md", repo / "task.md")
    (repo / "task.md").write_bytes(LOOSE)
    result = _run(repo, "check", "HEAD~1..HEAD", "--task", "task.md", "--format", fmt)
    _refused(result, code, "--task task.md maps to task.md, which the base tree holds only in another "
                           "case, as TASK.md; name the task file as the base tree spells it")


# --- the fallback a task file the base lacks keeps -----------------------------------------------

@pytest.mark.parametrize("mode", ["range", "worktree", "hook-json"])
def test_an_untracked_task_file_at_the_root_is_still_read_with_one_stderr_line(repo, mode):
    # D-139 keeps the fallback at the root for a task file the base lacks.
    # One stderr line now says the contract came from the working tree; it
    # reaches neither stdout nor the exit code.
    _write(repo, "tests/test_calc.py", WEAK)
    if mode == "range":
        _commit(repo, "weaken", "tests/test_calc.py")
    _write(repo, "TASK.md", FREEZE)
    rev = ["HEAD~1..HEAD"] if mode == "range" else []
    fmt = "hook-json" if mode == "hook-json" else "json"
    result = _run(repo, "check", *rev, "--task", "TASK.md", "--format", fmt)
    err = result.stderr.decode("utf-8")
    assert err.count(FALLBACK) == 1, err
    assert b"working-tree copy" not in result.stdout, result.stdout
    if mode == "hook-json":
        assert result.returncode == 0, err
        assert json.loads(result.stdout)["decision"] == "block", result.stdout
    else:
        assert _frozen(result)


# --- `--repo` through a symlink to the root (KNOWN-ISSUES-v0.8.0 row 21) --------------------------

@pytest.mark.parametrize("repo_as,task_as", [("link", "root"), ("root", "link"), ("link", "link")])
def test_repo_reached_through_a_symlink_to_the_root(repo, tmp_path, repo_as, task_as):
    # At the root `--repo` is used as given. `--task` named through the other
    # spelling maps to `../<directory>/TASK.md`, and Git refuses `<rev>:../...`
    # from the root as outside the repository, so the run fails closed before
    # any fallback. Named through the same spelling, the base copy is read.
    _write(repo, "TASK.md", FREEZE)
    _commit(repo, "contract", "TASK.md")
    _write(repo, "tests/test_calc.py", WEAK)
    _commit(repo, "weaken", "tests/test_calc.py")
    (repo / "TASK.md").write_bytes(LOOSE)
    link = tmp_path / "link"
    _dir_symlink(link, repo)
    places = {"root": repo, "link": link}
    result = subprocess.run(
        [sys.executable, "-m", "checkwash", "check", "HEAD~1..HEAD", "--format", "json",
         "--task", str(places[task_as] / "TASK.md"), "--repo", str(places[repo_as])],
        cwd=str(tmp_path), env=ENV, capture_output=True, timeout=120,
    )
    err = result.stderr.decode("utf-8")
    assert "working-tree copy" not in err, err
    if repo_as == task_as:
        assert _frozen(result)
        return
    # Git's own wording of the refusal varies by version and platform; the
    # strict snapshot reports any non-zero exit of the read as this error.
    assert (result.returncode, result.stdout) == (2, b""), err
    assert "checkwash engine error: strict snapshot git read failed" in err, err
    assert "maps to" not in err, err


# --- doctor's root lookup ------------------------------------------------------------------------

def test_doctor_finds_the_root_with_its_own_timeout_and_no_stdin(repo, monkeypatch, capsys):
    # From a subdirectory the lookup makes two queries. doctor's use its own
    # 5-second timeout and stdin from DEVNULL, as `_git_query` does; check's
    # keep every other Git call's 60 seconds and inherited stdin.
    original = subprocess.run
    seen = []

    def record(argv, *args, **kwargs):
        query = argv[3:5] if argv[:2] == ["git", "-C"] else None
        if query in (["rev-parse", "--is-inside-work-tree"], ["rev-parse", "--show-toplevel"]):
            seen.append((query[1], kwargs.get("timeout"), kwargs.get("stdin")))
        return original(argv, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", record)
    sub = str(repo / "tests")
    main(["doctor", "--repo", sub])
    doctor = list(seen)
    seen.clear()
    assert main(["check", "--repo", sub, "--format", "json"]) == 0
    capsys.readouterr()
    assert doctor == [("--is-inside-work-tree", 5, subprocess.DEVNULL),
                      ("--show-toplevel", 5, subprocess.DEVNULL)]
    assert seen == [("--is-inside-work-tree", 60, None), ("--show-toplevel", 60, None)]


# --- GitSnapshot.alias ---------------------------------------------------------------------------

LINKED = {"ci": ("120000", b"contracts"), "contracts/TASK.md": ("100644", FREEZE)}


@pytest.mark.parametrize("files,path,expected", [
    (LINKED, "ci/TASK.md", ("ci", "a symlink", False)),
    (LINKED, "CI/TASK.md", ("ci", "a symlink", False)),
    ({"ci": ("100644", b"not a directory\n")}, "ci/TASK.md", ("ci", "a file", False)),
    ({"docs/ci": ("120000", b"../contracts"), "contracts/TASK.md": ("100644", FREEZE)},
     "docs/ci/TASK.md", ("docs/ci", "a symlink", False)),
    ({"vendor/lib": ("160000", GITLINK)}, "Vendor/Lib/TASK.md", ("vendor/lib", "a submodule", False)),
    ({"TASK.md": ("100644", FREEZE)}, "task.md", ("TASK.md", "a file", True)),
    ({"contracts/TASK.md": ("100644", FREEZE)}, "Contracts/TASK.md", ("contracts/TASK.md", "a file", True)),
    ({"任務/ÄNDERUNG.md": ("100644", FREEZE)}, "任務/änderung.md", ("任務/ÄNDERUNG.md", "a file", True)),
], ids=["symlink", "symlink-in-another-case", "file", "nested-symlink", "submodule-in-another-case",
        "case", "directory-in-another-case", "non-ascii-case"])
def test_a_path_the_base_misses_names_the_entry_it_can_stand_for(owned, files, path, expected):
    # The miss first: Git reads no path through the entry, nor in another case.
    view = snapshots.GitSnapshot(owned, _tree(owned, files), side="base")
    assert view.read(path) is None
    assert view.alias(path) == snapshots.TreeAlias(*expected)


@pytest.mark.parametrize("files,path", [
    ({"TASK.md": ("100644", FREEZE)}, "TASKS.md"),
    ({"ci/README.md": ("100644", b"# CI\n")}, "ci/TASK.md"),
    ({"vendor/lib": ("160000", GITLINK)}, "vendor/lib"),
], ids=["absent", "directory", "submodule-itself"])
def test_a_path_the_base_really_lacks_has_no_alias(owned, files, path):
    # A directory on the way is no alias, and an entry equal to the path byte
    # for byte is what `read` answers.
    view = snapshots.GitSnapshot(owned, _tree(owned, files), side="base")
    assert view.read(path) is None
    assert view.alias(path) is None

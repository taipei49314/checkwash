"""Only registered index gitlinks bypass the changed-file directory read.

The fixture repositories are static inputs: no Python file in them is run.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from checkwash.change import EngineError
from checkwash.gitio.git import list_session_changes, list_worktree_changes
from checkwash.gitio.snapshot import WorkingTreeSnapshot


TEST = b"from pkg import total\n\ndef test_total():\n    assert total() == 78.75\n"


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, timeout=30).stdout


def init(repo):
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "checkwash-test")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "commit.gpgsign", "false")
    git(repo, "config", "core.autocrlf", "false")


@pytest.fixture
def submodule_repo(tmp_path):
    source, repo = tmp_path / "source", tmp_path / "parent"
    init(source)
    (source / "context.py").write_bytes(b"ANSWER = 78.75\n")
    git(source, "add", ".")
    git(source, "commit", "-m", "submodule base")
    init(repo)
    (repo / "setup.cfg").write_bytes(b"[tool:pytest]\ntestpaths = tests\n")
    (repo / "pkg.py").write_bytes(b"def total():\n    return 78.75\n")
    (repo / "tests").mkdir()
    (repo / "tests/test_total.py").write_bytes(TEST)
    git(repo, "-c", "protocol.file.allow=always", "submodule", "add", str(source), "vendor/lib")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "parent base")
    return repo


def dirty(repo, kind):
    module = repo / "vendor/lib"
    if kind in {"tracked", "pointer", "staged-pointer"}:
        (module / "context.py").write_bytes(b"ANSWER = 75\n")
    if kind in {"pointer", "staged-pointer"}:
        git(module, "-c", "user.name=checkwash-test", "-c", "user.email=test@example.invalid",
            "-c", "commit.gpgsign=false", "commit", "-am", "new pointer")
    if kind == "staged-pointer":
        git(repo, "add", "vendor/lib")
    if kind == "untracked":
        (module / "build-output.txt").write_bytes(b"generated\n")


@pytest.mark.parametrize("kind", ["tracked", "untracked", "pointer", "staged-pointer"])
@pytest.mark.parametrize("entrypoint", ["worktree", "session"])
def test_registered_dirty_gitlink_is_not_read_as_a_file(submodule_repo, kind, entrypoint):
    repo = submodule_repo
    dirty(repo, kind)
    # Porcelain v1 uses uppercase M for every dirty submodule state.
    assert git(repo, "status", "--porcelain", "-z", "--untracked-files=all", "--no-renames") in {
        b" M vendor/lib\0", b"M  vendor/lib\0"}
    changes = (list_worktree_changes(str(repo)) if entrypoint == "worktree"
               else list_session_changes(str(repo), "HEAD"))
    assert changes == []
    # D-123's checked-out context remains visible to the worktree snapshot.
    snapshot = WorkingTreeSnapshot(repo)
    assert "vendor/lib/context.py" in snapshot.list_paths()
    assert snapshot.read("vendor/lib/context.py") is not None


@pytest.mark.parametrize("kind", ["tracked", "untracked", "pointer", "staged-pointer"])
@pytest.mark.parametrize("output_format", ["json", "hook-json"])
def test_dirty_gitlink_does_not_hide_a_real_neighbor_finding(submodule_repo, kind, output_format):
    repo = submodule_repo
    dirty(repo, kind)
    (repo / "tests/test_total.py").write_bytes(TEST.replace(b"== 78.75", b"== 75"))
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
           "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1"}
    result = subprocess.run([sys.executable, "-B", "-m", "checkwash", "check", "--repo", str(repo),
                             "--format", output_format], env=env, capture_output=True, timeout=60)
    report = json.loads(result.stdout)
    assert result.returncode == (1 if output_format == "json" else 0), result.stderr
    if output_format == "json":
        assert report["verdict"] == "block"
        assert [(f["rule"], f["severity"]) for f in report["findings"]] == [
            ("EXPECTED_VALUE_CHANGED", "high")]
    else:
        assert report["decision"] == "block"
        assert "EXPECTED_VALUE_CHANGED" in report["reason"]


def test_committed_pointer_change_is_safe_in_session_mode(submodule_repo):
    repo = submodule_repo
    base = git(repo, "rev-parse", "HEAD").decode().strip()
    dirty(repo, "staged-pointer")
    git(repo, "commit", "-m", "pointer changed")
    assert list_session_changes(str(repo), base) == []


def test_new_registered_gitlink_is_safe(submodule_repo, tmp_path):
    repo = submodule_repo
    other = tmp_path / "other"
    init(other)
    (other / "data.txt").write_bytes(b"new module\n")
    git(other, "add", ".")
    git(other, "commit", "-m", "other base")
    git(repo, "-c", "protocol.file.allow=always", "submodule", "add", str(other), "vendor/other")
    changes = list_worktree_changes(str(repo))
    assert [c.path for c in changes] == [".gitmodules"]


def test_regular_file_replaced_by_gitlink_retains_its_removal(submodule_repo):
    repo = submodule_repo
    path = repo / "test_removed.py"
    path.write_bytes(TEST)
    git(repo, "add", "test_removed.py")
    git(repo, "commit", "-m", "ordinary test")
    path.unlink()
    path.mkdir()
    oid = git(repo / "vendor/lib", "rev-parse", "HEAD").decode().strip()
    git(repo, "update-index", "--cacheinfo", f"160000,{oid},test_removed.py")
    changes = list_worktree_changes(str(repo))
    assert len(changes) == 1
    assert (changes[0].path, changes[0].status, changes[0].before, changes[0].after) == (
        "test_removed.py", "deleted", TEST, None)


def test_gitlink_replaced_by_regular_file_is_read(submodule_repo):
    repo = submodule_repo
    git(repo, "submodule", "deinit", "-f", "vendor/lib")
    git(repo, "rm", "-f", "vendor/lib")
    (repo / "vendor/lib").write_bytes(b"ordinary file\n")
    git(repo, "add", "vendor/lib")
    changes = list_worktree_changes(str(repo))
    replacement = next(c for c in changes if c.path == "vendor/lib")
    assert (replacement.status, replacement.before, replacement.after) == (
        "added", None, b"ordinary file\n")


def test_unregistered_nested_repository_still_refuses(submodule_repo):
    repo = submodule_repo
    nested = repo / "nested"
    init(nested)
    (nested / "payload.py").write_bytes(b"VALUE = 1\n")
    git(nested, "add", ".")
    git(nested, "commit", "-m", "nested base")
    with pytest.raises(EngineError, match="nonregular source nested/ \\(a directory\\)"):
        list_worktree_changes(str(repo))


def test_regular_directory_does_not_become_an_opaque_gitlink(submodule_repo):
    repo = submodule_repo
    (repo / "newdir").mkdir()
    (repo / "newdir/regular.txt").write_bytes(b"ordinary\n")
    changes = list_worktree_changes(str(repo))
    assert [(c.path, c.status, c.after) for c in changes] == [
        ("newdir/regular.txt", "added", b"ordinary\n")]

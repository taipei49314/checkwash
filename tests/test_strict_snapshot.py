"""Strict discovery cannot turn a failed search into 'no affected callers'."""

from pathlib import Path
import subprocess

import pytest

from checkwash.change import EngineError
from checkwash.gitio.snapshot import GitSnapshot, WorkingTreeSnapshot


@pytest.fixture
def snapshot_repo(tmp_path):
    def git(*args):
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)

    git("init", "-b", "main")
    git("config", "user.name", "e2e")
    git("config", "user.email", "e2e@example.invalid")
    git("config", "commit.gpgsign", "false")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_中文.py").write_text("from test_helpers import assert_equal\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-m", "base")
    return tmp_path


def test_git_snapshot_distinguishes_real_missing_and_no_matches(snapshot_repo):
    snapshot = GitSnapshot(snapshot_repo, "HEAD")
    assert snapshot.read("absent.py") is None
    assert snapshot.search(["no_such_module"]) == []
    assert snapshot.search(["test_helpers"]) == ["tests/test_中文.py"]
    assert snapshot.read("tests/test_中文.py") == b"from test_helpers import assert_equal\n"


def test_git_snapshot_rejects_invalid_revision(snapshot_repo):
    with pytest.raises(EngineError, match="git read failed"):
        GitSnapshot(snapshot_repo, "not-a-revision").read("absent.py")


@pytest.mark.parametrize("operation", ["read", "search"])
def test_git_snapshot_does_not_swallow_subprocess_failures(monkeypatch, operation):
    snapshot = GitSnapshot("unused", "HEAD")
    snapshot._resolved = "a" * 40
    monkeypatch.setattr("checkwash.gitio.snapshot.subprocess.run",
                        lambda *args, **kwargs: subprocess.CompletedProcess(args, 128, b"", b"object database unavailable"))
    with pytest.raises(EngineError, match="object database unavailable"):
        getattr(snapshot, operation)("test_helpers.py" if operation == "read" else ["test_helpers"])


def test_git_grep_exit_one_means_no_matches_only(monkeypatch):
    snapshot = GitSnapshot("unused", "HEAD")
    snapshot._resolved = "a" * 40
    monkeypatch.setattr("checkwash.gitio.snapshot.subprocess.run",
                        lambda *args, **kwargs: subprocess.CompletedProcess(args, 1, b"", b""))
    assert snapshot.search(["test_helpers"]) == []
    with pytest.raises(EngineError, match="git read failed"):
        snapshot.read("test_helpers.py")


def test_git_blob_size_is_checked_before_content_is_requested(monkeypatch):
    snapshot = GitSnapshot("unused", "HEAD")
    snapshot._resolved = "a" * 40
    commands = []

    def run(args, **kwargs):
        commands.append(args)
        return subprocess.CompletedProcess(args, 0, b"abc blob 1000001\n", b"")

    monkeypatch.setattr("checkwash.gitio.snapshot.subprocess.run", run)
    with pytest.raises(EngineError, match="byte limit"):
        snapshot.read("large.py")
    assert len(commands) == 1 and "--batch-check" in commands[0]


def test_git_search_rejects_hit_limit_instead_of_truncating(monkeypatch):
    snapshot = GitSnapshot("unused", "HEAD")
    snapshot._resolved = "a" * 40
    data = b"".join(f"{'a' * 40}:tests/test_{i}.py\0".encode() for i in range(64))
    monkeypatch.setattr("checkwash.gitio.snapshot.subprocess.run",
                        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, data, b""))
    with pytest.raises(EngineError, match="hit limit"):
        snapshot.search(["test_helpers"])


def test_worktree_missing_differs_from_unreadable_source(snapshot_repo, monkeypatch):
    snapshot = WorkingTreeSnapshot(snapshot_repo)
    assert snapshot.read("absent.py") is None
    assert snapshot.search(["test_helpers"]) == ["tests/test_中文.py"]
    original = Path.open

    def deny(path, *args, **kwargs):
        if path.suffix == ".py":
            raise PermissionError("denied source")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", deny)
    with pytest.raises(PermissionError, match="denied source"):
        snapshot.search(["test_helpers"])


def test_worktree_search_cannot_ignore_data_after_byte_limit(snapshot_repo, monkeypatch):
    monkeypatch.setattr("checkwash.gitio.snapshot.MAX_SOURCE_BYTES", 5)
    with pytest.raises(EngineError, match="byte limit"):
        WorkingTreeSnapshot(snapshot_repo).search(["test_helpers"])

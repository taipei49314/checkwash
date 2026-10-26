"""Worktree read/batch refusal context changes no source-admission branch."""
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from types import SimpleNamespace

import pytest

from checkwash.change import EngineError
from checkwash.gitio.snapshot import WorkingTreeSnapshot, _nonregular


def details(message, path, entry, kind="a directory", side="worktree"):
    assert "cannot inspect nonregular source" in message
    assert repr(path) in message
    assert f"({kind})" in message
    assert f"side={side!r}" in message
    assert f"entry={entry!r}" in message
    assert "repository-owned regular source" in message
    assert "committed bytes only" in message


@pytest.mark.parametrize("operation", ["read", "read_many"])
def test_directory_still_refuses_with_side_and_actual_reader_entry(tmp_path, operation):
    (tmp_path / "configs/pytest.ini").mkdir(parents=True)
    snapshot = WorkingTreeSnapshot(tmp_path, side="worktree")
    with pytest.raises(EngineError) as caught:
        snapshot.read("configs/pytest.ini") if operation == "read" else snapshot.read_many(["configs/pytest.ini"])
    # A batch directory reaches the same single-file read refusal.
    details(str(caught.value), "configs/pytest.ini", "worktree/read")


@pytest.mark.parametrize("operation", ["read", "read_many"])
def test_nonregular_absolute_input_is_redacted(tmp_path, operation):
    directory = tmp_path / "private-directory"
    directory.mkdir()
    snapshot = WorkingTreeSnapshot(tmp_path)
    with pytest.raises(EngineError) as caught:
        snapshot.read(str(directory)) if operation == "read" else snapshot.read_many([str(directory)])
    details(str(caught.value), "<non-repository-relative path>", "worktree/read")
    assert str(directory) not in str(caught.value)


def test_batch_symlink_branch_does_not_open_or_print_its_target(tmp_path, monkeypatch):
    snapshot = WorkingTreeSnapshot(tmp_path)
    logical = "configs/linked.ini"
    lexical = snapshot.root / logical
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda path: True if path == lexical else original(path))
    monkeypatch.setattr(snapshot, "read", lambda _path: pytest.fail("batch refusal must not read the link"))
    with pytest.raises(EngineError) as caught:
        snapshot.read_many([logical])
    details(str(caught.value), logical, "worktree/read_many", "a symlink")
    assert str(snapshot.root) not in str(caught.value)


def test_single_file_symlink_branch_still_refuses_without_opening_source(tmp_path, monkeypatch):
    path = tmp_path / "linked.ini"
    path.write_bytes(b"not read\n")
    snapshot = WorkingTreeSnapshot(tmp_path)
    native_lstat = Path.lstat

    def lstat(candidate, *args, **kwargs):
        return SimpleNamespace(st_mode=stat.S_IFLNK) if candidate == path else native_lstat(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", lstat)
    monkeypatch.setattr(Path, "open", lambda *args, **kwargs: pytest.fail("a nonregular source was opened"))
    with pytest.raises(EngineError) as caught:
        snapshot.read("linked.ini")
    details(str(caught.value), "linked.ini", "worktree/read", "a symlink")


@pytest.mark.parametrize("path,side,entry", [
    ("line\nbreak.ini", "worktree", "worktree/read"),
    ("escape\x1b[31m.ini", "worktree\n\x1b", "worktree/read_many"),
    ("bidirectional\u202e.ini", "worktree", "worktree/read"),
])
def test_context_escapes_path_and_side_controls(path, side, entry):
    error = _nonregular("strict snapshot cannot inspect nonregular source", path, b"120000",
                        side=side, entry=entry)
    message = str(error)
    details(message, path, entry, "a symlink", side)
    assert "\n" not in message and "\x1b" not in message and "\u202e" not in message


def test_legacy_helper_and_other_snapshot_callers_keep_their_original_message():
    error = _nonregular("strict snapshot batch cannot inspect nonregular source", "config.ini", b"120000")
    assert str(error) == "strict snapshot batch cannot inspect nonregular source config.ini (a symlink)"


@pytest.mark.parametrize("operation", ["read", "read_many"])
def test_regular_source_and_absence_keep_their_values(tmp_path, operation):
    (tmp_path / "config.ini").write_bytes(b"owned = true\n")
    snapshot = WorkingTreeSnapshot(tmp_path)
    if operation == "read":
        assert snapshot.read("config.ini") == b"owned = true\n"
        assert snapshot.read("missing.ini") is None
    else:
        assert snapshot.read_many(["config.ini", "missing.ini"]) == {
            "config.ini": b"owned = true\n", "missing.ini": None}


@pytest.fixture(scope="module")
def nested_repo_case(tmp_path_factory):
    owner = tmp_path_factory.mktemp("nested")
    repo = owner / "parent"
    repo.mkdir()
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0",
                "GIT_AUTHOR_NAME": "owned refusal fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
                "GIT_COMMITTER_NAME": "owned refusal fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid"})

    def git(cwd, *args):
        return subprocess.run(["git", "-c", "core.hooksPath=nul", "-c", "core.autocrlf=false",
                               "-c", "commit.gpgsign=false", *args], cwd=cwd, env=env,
                              capture_output=True, check=True, timeout=30).stdout

    git(repo, "init", "-q", "-b", "main")
    (repo / "test_api.py").write_bytes(b"def test_api():\n    assert 1 == 1\n")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    # A real adjacent oracle loss does not turn a refusal into a clean result.
    (repo / "test_api.py").write_bytes(b"def test_api():\n    assert True\n")
    nested = repo / "nested"
    nested.mkdir()
    git(nested, "init", "-q", "-b", "main")
    (nested / "payload.py").write_bytes(b"DO_NOT_EXECUTE = 1\n")
    git(nested, "add", ".")
    git(nested, "commit", "-m", "nested base")
    status = git(repo, "status", "--porcelain", "-z", "--untracked-files=all", "--no-renames")
    assert b"?? nested/\0" in status
    (repo / ".git/nonregular-status.raw").write_bytes(status)
    return repo


@pytest.mark.parametrize("format", ["json", "hook-json"])
def test_native_nested_directory_refusal_keeps_exit_and_hook_semantics(nested_repo_case, format):
    repo = nested_repo_case
    source = Path(__file__).resolve().parents[1] / "src"
    bootstrap = f"import sys;sys.path.insert(0,{str(source)!r});from checkwash.cli import main;raise SystemExit(main())"
    command = [sys.executable, "-I", "-B", "-X", "utf8", "-c", bootstrap,
               "check", "--repo", str(repo), "--format", format]
    result = subprocess.run(command, capture_output=True, timeout=60)
    raw = repo / ".git" / ("nonregular-" + format)
    raw.with_suffix(".stdout").write_bytes(result.stdout)
    raw.with_suffix(".stderr").write_bytes(result.stderr)
    raw.with_suffix(".meta.json").write_text(json.dumps({"command": command, "exit": result.returncode,
        "stdout_sha256": hashlib.sha256(result.stdout).hexdigest(),
        "stderr_sha256": hashlib.sha256(result.stderr).hexdigest()}, indent=2), encoding="utf-8")
    assert result.returncode == (2 if format == "json" else 0)
    details(result.stderr.decode("utf-8"), "nested/", "worktree/read")
    if format == "json":
        assert result.stdout == b""
    else:
        payload = json.loads(result.stdout)
        assert set(payload) == {"systemMessage"}
        assert "not analysed" in payload["systemMessage"] and "decision" not in payload

"""First-week fixes for 0.13, from the 2026-11-10 re-review (ND-09; D-205).

The zipapp the README has a newcomer download into the repository root
reported itself as over the source byte limit, and the analysis as
incomplete.

A working-tree or Stop run now sets aside the untracked zipapp that
checkwash runs from, with a note on stderr, when neither the compared
commit nor the session base holds its path.

The fixture repositories are static inputs: no file in them is run, except
the zipapps the zipapp tests build from this tree's `src/`. Git's global
and system configuration is kept out, so a developer's own excludes cannot
decide a test.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import zipapp
import zipfile

import pytest

from checkwash.gitio import git as gitmod
from checkwash.gitio.git import list_session_changes, list_worktree_changes

ROOT = Path(__file__).resolve().parents[1]
PKG = b"def total():\n    return 5\n"
TEST = b"from pkg import total\n\n\ndef test_total():\n    assert total() == 5\n"
ZIPAPP_NOTE = "skipped checkwash.pyz: the untracked zipapp this checkwash runs from"


@pytest.fixture(autouse=True)
def plain_git(tmp_path_factory, monkeypatch):
    home = tmp_path_factory.mktemp("git-home")
    (home / "gitconfig").write_bytes(b"")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(home / "gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / "xdg"))


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True, timeout=60).stdout


def write(repo, files):
    for path, data in files.items():
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_bytes(data)


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "checkwash-test")
    git(root, "config", "user.email", "test@example.invalid")
    git(root, "config", "commit.gpgsign", "false")
    git(root, "config", "core.autocrlf", "false")
    write(root, {"pkg.py": PKG, "tests/test_total.py": TEST})
    git(root, "add", "-A")
    git(root, "commit", "-m", "base")
    return root


def check(repo, *args, executable=None):
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONUTF8": "1",
           "GREENWASH_TODAY": "2026-11-12", "NO_COLOR": "1"}
    command = [sys.executable, *executable] if executable else [sys.executable, "-m", "checkwash"]
    result = subprocess.run([*command, "check", *args, "--format", "json", "--repo", str(repo)],
                            env=env, capture_output=True, timeout=180, cwd=str(repo))
    stdout, stderr = result.stdout.decode("utf-8"), result.stderr.decode("utf-8")
    return result.returncode, (json.loads(stdout) if stdout.strip() else None), stderr


def paths(changes):
    return sorted(change.path for change in changes)


def _link_folder(link, target):
    try:
        if os.name == "nt":
            import _winapi

            _winapi.CreateJunction(str(target), str(link))
        else:
            os.symlink(target, link, target_is_directory=True)
    except (OSError, AttributeError, ImportError) as exc:
        pytest.skip(f"cannot link a folder here: {exc}")


# --- the zipapp checkwash runs from -------------------------------------------------------------

@pytest.fixture
def running(repo, monkeypatch):
    """`repo/checkwash.pyz`, standing in for the archive this checkwash runs from."""
    pyz = repo / "checkwash.pyz"
    monkeypatch.setattr(gitmod, "_running_archive", lambda: os.path.realpath(pyz))
    return pyz


def test_the_untracked_running_zipapp_is_set_aside_with_a_note(repo, running):
    running.write_bytes(b"PK\x05\x06" + b"\0" * 18)
    write(repo, {"notes.txt": b"kept\n"})
    notes = []
    assert paths(list_worktree_changes(str(repo), notes=notes)) == ["notes.txt"]
    assert notes == [ZIPAPP_NOTE]


def test_a_tracked_running_zipapp_is_read(repo, running):
    running.write_bytes(b"PK\x05\x06" + b"\0" * 18)
    git(repo, "add", "checkwash.pyz")
    git(repo, "commit", "-m", "vendored")
    running.write_bytes(b"PK\x05\x06" + b"\1" * 18)
    write(repo, {"notes.txt": b"kept\n"})
    notes = []
    assert paths(list_worktree_changes(str(repo), notes=notes)) == ["checkwash.pyz", "notes.txt"]
    assert notes == []


def test_a_running_zipapp_the_session_base_holds_is_read(repo, running):
    running.write_bytes(b"PK\x05\x06" + b"\0" * 18)
    git(repo, "add", "checkwash.pyz")
    git(repo, "commit", "-m", "vendored")
    since = git(repo, "rev-parse", "HEAD").decode().strip()
    git(repo, "rm", "-q", "--cached", "checkwash.pyz")
    git(repo, "commit", "-m", "untracked during the session")
    running.write_bytes(b"PK\x05\x06" + b"\2" * 18)
    notes = []
    assert paths(list_worktree_changes(str(repo), notes=notes, absent_at=(since,))) == ["checkwash.pyz"]
    assert notes == []
    session_notes = []
    assert "checkwash.pyz" in paths(list_session_changes(str(repo), since, notes=session_notes))
    assert session_notes == []
    # Without the session base, the same record is set aside.
    assert paths(list_worktree_changes(str(repo))) == []


def test_a_staged_running_zipapp_is_read(repo, running):
    running.write_bytes(b"PK")
    git(repo, "add", "checkwash.pyz")
    notes = []
    assert paths(list_worktree_changes(str(repo), notes=notes)) == ["checkwash.pyz"]
    assert notes == []


def test_a_repository_reached_through_a_link_still_matches_the_zipapp(repo, running, tmp_path):
    running.write_bytes(b"PK")
    link = tmp_path / "repolink"
    _link_folder(link, repo)
    notes = []
    assert paths(list_worktree_changes(str(link), notes=notes)) == []
    assert notes == [ZIPAPP_NOTE]


def test_when_git_cannot_say_whether_a_commit_holds_it_the_zipapp_is_read(repo, running):
    running.write_bytes(b"PK")
    notes = []
    assert paths(list_worktree_changes(str(repo), notes=notes, absent_at=("0" * 40,))) == ["checkwash.pyz"]
    assert notes == []


def test_another_file_named_like_the_zipapp_is_read(repo, monkeypatch, tmp_path):
    elsewhere = tmp_path / "bin" / "checkwash.pyz"
    elsewhere.parent.mkdir()
    elsewhere.write_bytes(b"PK")
    monkeypatch.setattr(gitmod, "_running_archive", lambda: os.path.realpath(elsewhere))
    (repo / "checkwash.pyz").write_bytes(b"PK")
    notes = []
    assert paths(list_worktree_changes(str(repo), notes=notes)) == ["checkwash.pyz"]
    assert notes == []


def _zipapp_over_the_limit(target):
    """This tree's `src/` as a zipapp, padded past the 1,000,000-byte source
    limit, as the published 0.12.0 pyz is (1,013,508 bytes)."""
    zipapp.create_archive(ROOT / "src", target=target, main="checkwash.zipapp_entry:run", compressed=True,
                          filter=lambda path: "__pycache__" not in path.parts and path.suffix != ".pyc")
    with zipfile.ZipFile(target, "a") as archive:
        archive.writestr("checkwash/_padding.bin", os.urandom(1_100_000))
    assert target.stat().st_size > 1_000_000
    return target


def test_the_downloaded_zipapp_in_the_root_no_longer_reports_itself(repo):
    pyz = _zipapp_over_the_limit(repo / "checkwash.pyz")
    code, payload, stderr = check(repo, executable=[str(pyz)])
    assert code == 0, stderr
    assert payload["findings"] == []
    assert f"checkwash: {ZIPAPP_NOTE}" in stderr
    assert "over the source byte limit" not in stderr
    assert "analysis incomplete" not in stderr


def test_the_same_zipapp_run_from_elsewhere_is_still_reported(repo, tmp_path):
    runner = _zipapp_over_the_limit(tmp_path / "checkwash.pyz")
    (repo / "checkwash.pyz").write_bytes(runner.read_bytes())
    code, payload, stderr = check(repo, executable=[str(runner)])
    assert "over the source byte limit" in stderr
    assert "untracked zipapp" not in stderr


def _hook_input(event, **fields):
    return json.dumps({"session_id": "s-1", "hook_event_name": event, **fields}).encode("utf-8")


def test_a_stop_reads_a_zipapp_the_session_base_held(repo):
    # The Stop hook passes its session base on: a vendored zipapp that a
    # session commit untracked is read there, while a plain check sets it aside.
    pyz = _zipapp_over_the_limit(repo / "checkwash.pyz")
    git(repo, "add", "checkwash.pyz")
    git(repo, "commit", "-m", "vendored")
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONUTF8": "1",
           "GREENWASH_TODAY": "2026-11-12", "NO_COLOR": "1"}
    started = subprocess.run([sys.executable, "-m", "checkwash", "hook", "session-start", "--repo", str(repo)],
                             input=_hook_input("SessionStart", source="startup"), env=env,
                             capture_output=True, timeout=120)
    assert started.returncode == 0, started.stderr
    git(repo, "rm", "-q", "--cached", "checkwash.pyz")
    git(repo, "commit", "-m", "untracked during the session")
    stop = subprocess.run([sys.executable, str(pyz), "check", "--format", "hook-json", "--hook-input", "stdin",
                           "--repo", str(repo)], input=_hook_input("Stop", stop_hook_active=False), env=env,
                          capture_output=True, timeout=180, cwd=str(repo))
    stderr = stop.stderr.decode("utf-8")
    assert stop.returncode == 0, stderr
    assert "untracked zipapp" not in stderr
    assert "over the source byte limit" in stderr
    code, payload, plain = check(repo, executable=[str(pyz)])
    assert f"checkwash: {ZIPAPP_NOTE}" in plain

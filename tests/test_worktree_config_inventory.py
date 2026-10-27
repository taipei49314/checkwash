"""Worktree config evidence walks the working tree only when a consumer needs its inventory."""
import json
import os
from pathlib import Path
import subprocess

import pytest

from checkwash.change import EngineError
from checkwash.cli import main
from checkwash.gitio import snapshot as snapshots


def git(repo, *args, data=None):
    result = subprocess.run(["git", "-C", str(repo), *args], input=data, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    return result.stdout


def initialize(repo):
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "worktree config inventory")
    git(repo, "config", "user.email", "inventory@example.invalid")
    git(repo, "config", "commit.gpgsign", "false")
    git(repo, "config", "core.autocrlf", "false")


def js_repository(repo):
    initialize(repo)
    (repo / ".gitignore").write_bytes(b"node_modules/\n")
    (repo / "README.md").write_bytes(b"# demo\n")
    web = repo / "web"
    web.mkdir()
    (web / "add.test.js").write_bytes(b'test("adds", () => {\n  expect(add(1, 2)).toBe(3);\n});\n')
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "base")


def failing_walk(monkeypatch):
    def walk(self):
        raise EngineError("strict snapshot inventory failed")

    monkeypatch.setattr(snapshots.WorkingTreeSnapshot, "list_paths", walk)


def test_worktree_js_skip_blocks_without_walking_the_working_tree(tmp_path, monkeypatch, capsys):
    js_repository(tmp_path)
    (tmp_path / "web/add.test.js").write_bytes(b'test.skip("adds", () => {\n  expect(add(1, 2)).toBe(3);\n});\n')
    failing_walk(monkeypatch)
    code = main(["check", "--repo", str(tmp_path), "--format", "json"])
    report = json.loads(capsys.readouterr().out)
    assert code == 1
    assert any(f["rule"] == "TEST_DISABLED" for f in report["findings"])


@pytest.mark.parametrize("edit", [None, "README.md"])
def test_clean_and_docs_only_worktrees_need_no_walk(tmp_path, monkeypatch, capsys, edit):
    js_repository(tmp_path)
    if edit:
        (tmp_path / edit).write_bytes(b"# demo, edited\n")
    failing_walk(monkeypatch)
    code = main(["check", "--repo", str(tmp_path), "--format", "json"])
    capsys.readouterr()
    assert code == 0


@pytest.mark.skipif(os.name != "nt", reason="directory junctions are a Windows reparse type")
def test_ignored_junction_cycle_does_not_stop_the_stop_hook(tmp_path, capsys):
    js_repository(tmp_path)
    store = tmp_path / "node_modules" / ".pnpm"
    a = store / "a@1" / "node_modules"
    b = store / "b@1" / "node_modules"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    for link, target in ((a / "b", b), (b / "a", a)):
        made = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
        if made.returncode != 0:
            pytest.skip("junction creation unavailable")
    (tmp_path / "web/add.test.js").write_bytes(b'test.skip("adds", () => {\n  expect(add(1, 2)).toBe(3);\n});\n')
    code = main(["check", "--repo", str(tmp_path), "--format", "hook-json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0 and payload.get("decision") == "block", payload


def link_placeholder_repository(repo):
    initialize(repo)
    git(repo, "config", "core.symlinks", "false")
    target = repo / "settings" / "current.txt"
    target.parent.mkdir()
    target.write_bytes(b"[pytest]\naddopts=\n")
    link = b"settings/current.txt"
    (repo / "pytest.ini").write_bytes(link)
    tests = repo / "tests"
    tests.mkdir()
    (tests / "test_keep.py").write_bytes(b"def test_keep():\n    assert api() == 1\n")
    git(repo, "add", "-A")
    oid = git(repo, "hash-object", "-w", "--stdin", data=link).decode().strip()
    git(repo, "update-index", "--cacheinfo", f"120000,{oid},pytest.ini")
    git(repo, "commit", "-m", "base with config link")
    git(repo, "checkout", "--", "pytest.ini")
    return target


@pytest.mark.parametrize("edit_target", [False, True])
def test_link_placeholder_is_refused_like_a_link_not_compared_as_text(tmp_path, capsys, edit_target):
    # With core.symlinks=false Git checks a BASE link out as a regular file
    # holding the link text. Comparing that text with the resolved BASE target
    # hid a narrowed target and could fail on a clean tree.
    target = link_placeholder_repository(tmp_path)
    if Path(tmp_path / "pytest.ini").is_symlink():
        pytest.skip("checkout produced a native link; the placeholder case needs core.symlinks=false")
    if edit_target:
        target.write_bytes(b"[pytest]\naddopts=-k keep\n")
    code = main(["check", "--repo", str(tmp_path), "--format", "json"])
    output = capsys.readouterr()
    assert code == 2 and output.out == ""
    assert "worktree pytest config is not a regular source" in output.err

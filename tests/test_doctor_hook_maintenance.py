"""Tracked local Stop-hook maintenance remains subject to guardrail review."""

import json
import os
import subprocess

import pytest

from checkwash import doctor


PATHS = (".claude/settings.json", ".claude/settings.local.json")
TITLE = "hook maintenance can change tracked guardrails"
OLD_STOP = {"hooks": {"Stop": [{"hooks": [
    {"type": "command", "command": "checkwash check --format hook-json"}
]}]}}


def _git(root, *args):
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_OPTIONAL_LOCKS="0")
    return subprocess.run(
        ["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "--literal-pathspecs", *args],
        cwd=root, env=env, stdin=subprocess.DEVNULL, capture_output=True, check=True,
    )


def _repo(root, files, tracked):
    _git(root, "init", "--quiet")
    for relative, settings in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(settings), encoding="utf-8")
    if tracked:
        _git(root, "add", "-f", "--", *tracked)
    return root


def _maintenance(root):
    return [note for note in doctor.collect(root) if note.title == TITLE]


@pytest.mark.parametrize("paths", [[PATHS[0]], [PATHS[1]], list(PATHS)])
def test_tracked_stop_settings_get_review_guidance_without_gate_credit(tmp_path, paths):
    root = _repo(tmp_path, {path: OLD_STOP for path in paths}, paths)
    notes = doctor.collect(root)
    maintenance = [note for note in notes if note.title == TITLE]
    assert len(maintenance) == 1
    assert maintenance[0].level == "info"
    for path in paths:
        assert path in maintenance[0].detail
    for required in ("Installing or reinstalling", "git diff", "BASE/review", "does not exempt"):
        assert required in maintenance[0].detail
    assert [note.level for note in notes if "configured locally but not in CI" in note.title] == ["problem"]
    assert [note.level for note in notes if "cannot see what a session commits" in note.title] == ["info"]


@pytest.mark.parametrize("path", PATHS)
def test_untracked_stop_settings_do_not_get_tracked_maintenance_note(tmp_path, path):
    root = _repo(tmp_path, {path: OLD_STOP}, [])
    assert not _maintenance(root)


@pytest.mark.parametrize("tracked", PATHS)
def test_note_names_only_the_tracked_stop_settings(tmp_path, tracked):
    root = _repo(tmp_path, {path: OLD_STOP for path in PATHS}, [tracked])
    notes = _maintenance(root)
    assert len(notes) == 1
    assert tracked in notes[0].detail
    assert next(path for path in PATHS if path != tracked) not in notes[0].detail


@pytest.mark.parametrize("tracked", PATHS)
def test_tracked_non_stop_settings_do_not_lend_tracking_to_another_hook(tmp_path, tracked):
    untracked = next(path for path in PATHS if path != tracked)
    root = _repo(tmp_path, {tracked: {"permissions": {}}, untracked: OLD_STOP}, [tracked])
    assert not _maintenance(root)


def test_index_tracking_still_matters_when_settings_have_unstaged_changes(tmp_path):
    root = _repo(tmp_path, {PATHS[0]: OLD_STOP}, [PATHS[0]])
    (root / PATHS[0]).write_text(json.dumps(OLD_STOP, indent=2), encoding="utf-8")
    assert len(_maintenance(root)) == 1
    _git(root, "rm", "--cached", "-f", "--", PATHS[0])
    assert not _maintenance(root)


@pytest.mark.parametrize("answer", [None, subprocess.CompletedProcess([], 128, b"")])
def test_unavailable_index_does_not_claim_tracked_settings(tmp_path, monkeypatch, answer):
    root = _repo(tmp_path, {PATHS[0]: OLD_STOP}, [PATHS[0]])
    monkeypatch.setattr(doctor, "_git_query", lambda *args: answer)
    assert not _maintenance(root)


def test_index_output_requires_the_exact_fixed_settings_path(tmp_path, monkeypatch):
    root = _repo(tmp_path, {PATHS[0]: OLD_STOP}, [])
    answer = subprocess.CompletedProcess(
        [], 0, b".claude/settings.json/child\0.claude/settings.json.extra\0"
    )
    monkeypatch.setattr(doctor, "_git_query", lambda *args: answer)
    assert not _maintenance(root)

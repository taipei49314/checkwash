"""#418: the Claude Code Stop hook also checks what the session committed.

The Stop hook used to diff HEAD against the working tree only, so an edit the
agent committed during the session was never analysed, a clean tree printed
`{}` as a real pass would, and an exemption or config the agent committed
governed its own next Stop. Now the managed SessionStart handler
(`hook session-start`) records HEAD once per session under
`<git-dir>/checkwash/sessions/`, and the managed Stop handler
(`check --format hook-json --hook-input stdin`) reads that record:

- HEAD..worktree still decides the verdict, with policy read from the
  session's start;
- what only the session's commits hold is named in a non-blocking
  `systemMessage` for the required check to judge;
- with hook input and no usable record, a pass says the commits were not
  analysed;
- with no hook input, and without the flag, nothing changes.

These run the CLI on real commits.
"""

import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest

from checkwash.doctor import collect
from checkwash.hooks import (
    install_claude,
    is_managed_handler,
    is_managed_session_handler,
)
from checkwash.session import RECORD_MAX_AGE_DAYS, HookInput, read_hook_input, record_session_start, session_base

SRC = Path(__file__).resolve().parents[1] / "src"
ORIGINAL = b"def test_total():\n    assert total() == 5\n"
WEAKENED = b"def test_total():\n    assert total() > 0\n"
ENV = {**os.environ, "PYTHONPATH": str(SRC), "PYTHONUTF8": "1", "GREENWASH_TODAY": "2026-10-16", "NO_COLOR": "1"}


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True).stdout.decode().strip()


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "checkwash-test")
    git(root, "config", "user.email", "test@example.invalid")
    git(root, "config", "commit.gpgsign", "false")
    git(root, "config", "core.autocrlf", "false")
    (root / "test_total.py").write_bytes(ORIGINAL)
    git(root, "add", "-A")
    git(root, "commit", "-m", "base")
    return root


def cli(repo, *args, stdin=b""):
    return subprocess.run(
        [sys.executable, "-m", "checkwash", *args, "--repo", str(repo)],
        input=stdin, env=ENV, capture_output=True, timeout=120,
    )


def _input(session, event, **fields):
    return json.dumps({"session_id": session, "hook_event_name": event, **fields}).encode("utf-8")


def start(repo, session="s-1", source="startup"):
    result = cli(repo, "hook", "session-start", stdin=_input(session, "SessionStart", source=source))
    assert result.returncode == 0, result.stderr
    assert result.stdout == b""


def stop(repo, session="s-1", stdin=None):
    result = cli(repo, "check", "--format", "hook-json", "--hook-input", "stdin",
                 stdin=_input(session, "Stop", stop_hook_active=False) if stdin is None else stdin)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def commit(repo, message="work"):
    git(repo, "add", "-A")
    git(repo, "commit", "-m", message)


def weaken(repo):
    (repo / "test_total.py").write_bytes(WEAKENED)


def _records(repo):
    directory = repo / ".git" / "checkwash" / "sessions"
    return sorted(p.name for p in directory.iterdir()) if directory.is_dir() else []


# --- the Stop hook ---------------------------------------------------------------------------------

def test_a_committed_blocked_edit_is_named_instead_of_a_bare_pass(repo):
    start(repo)
    weaken(repo)
    commit(repo, "fix tests")
    flagless = cli(repo, "check", "--format", "hook-json")
    assert json.loads(flagless.stdout) == {}
    payload = stop(repo)
    assert "decision" not in payload
    message = payload["systemMessage"]
    assert "commits made during this session hold 1 finding(s)" in message
    assert "ASSERT_WEAKENED test_total.py :: test_total" in message
    assert "the required check will judge them" in message


def test_an_uncommitted_blocked_edit_still_blocks_as_before(repo):
    start(repo)
    weaken(repo)
    payload = stop(repo)
    assert payload["decision"] == "block"
    assert 'checkwash allow "ASSERT_WEAKENED/' in payload["reason"]
    assert "next session" not in payload["reason"]
    assert "systemMessage" not in payload


def test_an_exemption_committed_during_the_session_governs_only_the_next_one(repo):
    start(repo)
    weaken(repo)
    first = stop(repo)
    assert first["decision"] == "block"
    fingerprint = re.search(r'checkwash allow "([^"]+)"', first["reason"]).group(1)
    assert cli(repo, "allow", fingerprint, "--reason", "reviewed").returncode == 0
    ledgers = [name for name in (".checkwash/allow.toml", ".greenwash/allow.toml") if (repo / name).exists()]
    assert len(ledgers) == 1
    git(repo, "add", "--", *ledgers)
    git(repo, "commit", "-m", "exempt it")
    second = stop(repo)
    assert second["decision"] == "block"
    assert "checkwash allow" in second["reason"]
    assert ("An exemption, config change or hook upgrade committed during this session applies "
            "from the next session; /clear starts one.") in second["reason"]
    start(repo, "s-2")
    assert stop(repo, "s-2") == {}


def test_with_no_commits_the_output_is_unchanged(repo):
    start(repo)
    assert stop(repo) == {}
    weaken(repo)
    flagless = cli(repo, "check", "--format", "hook-json")
    flagged = cli(repo, "check", "--format", "hook-json", "--hook-input", "stdin",
                  stdin=_input("s-1", "Stop"))
    assert flagged.stdout == flagless.stdout
    assert json.loads(flagged.stdout)["decision"] == "block"


def test_without_hook_input_the_flag_changes_nothing(repo):
    start(repo)
    weaken(repo)
    commit(repo)
    flagless = cli(repo, "check", "--format", "hook-json")
    assert stop(repo, stdin=b"") == json.loads(flagless.stdout) == {}


@pytest.mark.parametrize("label, stdin, reason", [
    ("unknown session", _input("never-started", "Stop"), "no start was recorded for this session"),
    ("no session id", b'{"hook_event_name": "Stop"}', "the hook input carries no session id"),
    ("unparsable", b'{"session_id": ', "the hook input could not be read"),
    ("oversized", b" " * 1_000_001, "the hook input could not be read"),
])
def test_hook_input_without_a_usable_record_passes_with_a_note(repo, label, stdin, reason):
    weaken(repo)
    commit(repo)
    payload = stop(repo, stdin=stdin)
    assert "decision" not in payload, label
    assert payload["systemMessage"].startswith(
        "checkwash: commits made during this session were not analysed, because " + reason
    ), label


def test_without_a_record_a_block_carries_no_note(repo):
    weaken(repo)
    payload = stop(repo, "never-started")
    assert payload["decision"] == "block"
    assert "systemMessage" not in payload


def test_head_moved_off_the_session_base_uses_the_merge_base(repo):
    first = git(repo, "rev-parse", "HEAD")
    (repo / "other.py").write_bytes(b"X = 1\n")
    commit(repo, "second")
    start(repo)
    git(repo, "checkout", "-q", "-b", "side", first)
    weaken(repo)
    commit(repo, "weaken on a side branch")
    payload = stop(repo)
    assert "decision" not in payload
    assert "ASSERT_WEAKENED test_total.py :: test_total" in payload["systemMessage"]


def test_head_with_no_history_in_common_passes_with_a_note(repo):
    start(repo)
    git(repo, "checkout", "-q", "--orphan", "fresh")
    weaken(repo)
    commit(repo, "unrelated history")
    payload = stop(repo)
    assert "decision" not in payload
    assert "HEAD shares no history with the commit this session started from" in payload["systemMessage"]


@pytest.mark.parametrize("args", [
    ["check", "--format", "json", "--hook-input", "stdin"],
    ["check", "HEAD~1..HEAD", "--format", "hook-json", "--hook-input", "stdin"],
])
def test_the_flag_needs_hook_json_and_no_range(repo, args):
    result = cli(repo, *args, stdin=_input("s-1", "Stop"))
    assert result.returncode == 2
    assert b"--hook-input stdin requires --format hook-json and no range" in result.stderr
    assert result.stdout == b""


# --- the session record ----------------------------------------------------------------------------

def test_compaction_never_writes_and_a_record_is_never_replaced(repo):
    start(repo, source="compact")
    assert _records(repo) == []
    start(repo)
    recorded = session_base(str(repo), HookInput({"session_id": "s-1"}))
    assert recorded == git(repo, "rev-parse", "HEAD")
    (repo / "other.py").write_bytes(b"X = 1\n")
    commit(repo)
    start(repo, source="resume")
    assert session_base(str(repo), HookInput({"session_id": "s-1"})) == recorded
    assert _records(repo) == [hashlib.sha256(b"s-1").hexdigest()]


def test_records_are_pruned_by_age_and_by_a_missing_commit_at_session_start(repo):
    directory = repo / ".git" / "checkwash" / "sessions"
    directory.mkdir(parents=True)
    head = git(repo, "rev-parse", "HEAD")
    now = datetime.datetime.now(datetime.timezone.utc)
    records = {
        "old": {"version": 1, "head": head, "created": (now - datetime.timedelta(days=RECORD_MAX_AGE_DAYS + 1)).isoformat()},
        "gone": {"version": 1, "head": "0" * 40, "created": now.isoformat()},
        "kept": {"version": 1, "head": head, "created": now.isoformat()},
    }
    for name, record in records.items():
        (directory / hashlib.sha256(name.encode()).hexdigest()).write_text(json.dumps(record), encoding="utf-8")
    record_session_start(str(repo), HookInput({"session_id": "new", "source": "startup"}))
    assert _records(repo) == sorted(hashlib.sha256(name.encode()).hexdigest() for name in ("kept", "new"))


def test_a_session_start_never_fails_and_never_prints(repo, tmp_path):
    (repo / ".git" / "checkwash").write_bytes(b"not a directory")
    start(repo)
    outside = tmp_path / "not a repository"
    outside.mkdir()
    result = cli(outside, "hook", "session-start", stdin=_input("s-1", "SessionStart", source="startup"))
    assert (result.returncode, result.stdout) == (0, b"")


class _Stream(io.BytesIO):
    def __init__(self, data=b"", tty=False):
        super().__init__(data)
        self._tty = tty

    def isatty(self):
        return self._tty


def test_hook_input_is_none_for_a_tty_an_empty_stream_or_a_silent_pipe():
    assert read_hook_input(None) is None
    assert read_hook_input(_Stream(b'{"session_id": "x"}', tty=True)) is None
    assert read_hook_input(_Stream()) is None
    assert read_hook_input(_Stream(b'{"session_id": "x"}')).session_id == "x"
    assert read_hook_input(_Stream(b"[1]")) == HookInput(None)
    # A pipe left open: nothing sent is no input; a partial object is input
    # that could not be read. Each gets its own pipe, closed writer first so
    # the reader thread ends before the stream closes.
    for sent, expected in ((b"", None), (b'{"session_id"', HookInput(None))):
        read_end, write_end = os.pipe()
        stream = os.fdopen(read_end, "rb")
        try:
            if sent:
                os.write(write_end, sent)
            assert read_hook_input(stream, wait=0.2) == expected
        finally:
            os.close(write_end)
            stream.close()


# --- installer and doctor --------------------------------------------------------------------------

def test_install_adds_a_separate_session_start_group_and_replaces_legacy_stop_shapes(repo, monkeypatch):
    monkeypatch.setattr("checkwash.hooks._shared_executable", lambda: "C:/tool/checkwash.exe")
    monkeypatch.setattr("checkwash.hooks._probe", lambda *args: None)
    path = repo / ".claude/settings.json"
    path.parent.mkdir()
    legacy = {"type": "command", "command": "checkwash", "args": ["check", "--format", "hook-json"]}
    custom = {"type": "command", "command": "checkwash check --format hook-json --fail-on warn"}
    path.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [legacy, custom]}]}}), encoding="utf-8")
    assert install_claude(str(repo), False).startswith("updated: Stop hook configuration")
    settings = json.loads(path.read_text(encoding="utf-8"))
    stop_handlers = settings["hooks"]["Stop"][0]["hooks"]
    assert custom in stop_handlers and legacy not in stop_handlers
    assert [h for h in stop_handlers if is_managed_handler(h)] == [
        {"type": "command", "command": "checkwash", "args": ["check", "--format", "hook-json", "--hook-input", "stdin"]}
    ]
    assert settings["hooks"]["SessionStart"] == [
        {"hooks": [{"type": "command", "command": "checkwash", "args": ["hook", "session-start"]}]}
    ]
    before = path.read_bytes()
    assert install_claude(str(repo), False).startswith("already installed:")
    assert path.read_bytes() == before


def test_the_local_session_handler_records_the_start(repo):
    install_claude(str(repo), True)
    settings = json.loads((repo / ".claude/settings.local.json").read_text(encoding="utf-8"))
    stop_handler = settings["hooks"]["Stop"][0]["hooks"][0]
    session = settings["hooks"]["SessionStart"][0]["hooks"][0]
    assert is_managed_session_handler(session)
    assert session["command"] == stop_handler["command"]
    assert session["args"][:4] == stop_handler["args"][:4] and session["args"][4:] == ["hook", "session-start"]
    result = subprocess.run([session["command"], *session["args"]], cwd=repo, capture_output=True,
                            input=_input("s-1", "SessionStart", source="startup"), timeout=120)
    assert (result.returncode, result.stdout) == (0, b""), result.stderr
    assert session_base(str(repo), HookInput({"session_id": "s-1"})) == git(repo, "rev-parse", "HEAD")


def test_doctor_notes_a_stop_hook_without_a_session_start_hook(repo):
    path = repo / ".claude/settings.local.json"
    path.parent.mkdir()
    legacy = {"type": "command", "command": "checkwash", "args": ["check", "--format", "hook-json"]}
    path.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [legacy]}]}}), encoding="utf-8")
    title = "no SessionStart hook: the Stop hook cannot see what a session commits"
    assert [n.level for n in collect(repo) if n.title == title] == ["info"]
    path.write_text(json.dumps({"hooks": {
        "Stop": [{"hooks": [legacy]}],
        "SessionStart": [{"hooks": [{"type": "command", "command": "checkwash", "args": ["hook", "session-start"]}]}],
    }}), encoding="utf-8")
    assert not [n for n in collect(repo) if n.title == title]

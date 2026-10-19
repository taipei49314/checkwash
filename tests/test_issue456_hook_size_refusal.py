"""Issue #456: a size refusal of the change itself blocks the Claude Code Stop hook.

A changed path a detector must read refuses the run when a side is over the
1,000,000-byte source limit (#415). In `check --format hook-json` every engine
error was a non-blocking `systemMessage` (#414), so an agent whose test edit
would block could pad the test file, or add any new `.py` or extensionless file
over the limit, and stop.

Ruling (b), 2026-10-18: in hook-json only, a size refusal for a path in the
diff that decides the verdict (for the Stop hook, HEAD against the working
tree) blocks when that path's head or worktree side is over the limit: exit 0,
`decision: block`, and a reason naming path, side, size and limit, on every
stop and with no config knob. The CLI matches the refusal against that diff's
unread sides. An edited path whose base side alone is over the limit, a
refusal outside that diff (a context read, a base manifest), the managed Stop
hook's session-commits analysis and every other engine error keep the #414
message. Term, json and sarif keep exit 2.

Large files are generated here, never committed.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

import checkwash.cli as cli_module
from checkwash.change import EngineError, FileChange, SourceOverLimit, UnreadSide
from checkwash.cli import _verdict_side_over_limit, main

LIMIT = 1_000_000
REFUSAL = "strict snapshot source exceeds the byte limit"
NOT_ANALYSED = "checkwash: this change was not analysed, so it was neither passed nor blocked. Engine error: "
BILLING = b"def compute_invoice_total(items):\n    return sum(items)\n"
TEST = (b"from billing import compute_invoice_total\n\n\n"
        b"def test_invoice_total():\n"
        b"    total = compute_invoice_total([10.5, 94.8])\n"
        b"    assert total == 105.3\n")
WEAKENED = TEST.replace(b"assert total == 105.3", b"assert total > 0")
# The weakened test with one comment line that takes it one byte past the limit.
PADDED = WEAKENED + b"#" * (LIMIT - len(WEAKENED)) + b"\n"
ENV = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
       "PYTHONUTF8": "1", "GREENWASH_TODAY": "2026-10-18", "NO_COLOR": "1"}


def blob(size, seed):
    """`size` bytes of hex text, distinct per seed (as in test_issue415)."""
    body = hashlib.shake_256(seed.encode()).hexdigest((size + 1) // 2).encode()
    return body[:size - 1] + b"\n"


def side(path, name, size=LIMIT + 1):
    return UnreadSide(path, name, size, LIMIT)


def described(path, name, size=LIMIT + 1):
    return f"{path} ({name}, {size} > {LIMIT} bytes)"


def _entry(path, name, size=LIMIT + 1):
    """The `unread` entry `--format json` writes for a refused side (#454 (d))."""
    return {"limit": LIMIT, "path": path, "side": name, "size": size}


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True).stdout


def _write(repo, files):
    for path, data in files.items():
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_bytes(data)


def _repo(tmp_path, extra=None):
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "config", "user.name", "checkwash-test")
    git(tmp_path, "config", "user.email", "test@example.invalid")
    git(tmp_path, "config", "commit.gpgsign", "false")
    git(tmp_path, "config", "core.autocrlf", "false")
    _write(tmp_path, {"billing.py": BILLING, "tests/test_billing.py": TEST, **(extra or {})})
    _commit(tmp_path, "base")
    return tmp_path


def _commit(repo, message="head"):
    git(repo, "add", "-A")
    git(repo, "commit", "-m", message)


def _run(repo, *args, stdin=b""):
    result = subprocess.run([sys.executable, "-m", "checkwash", *args, "--repo", str(repo)],
                            input=stdin, env=ENV, capture_output=True, timeout=120)
    return result.returncode, result.stdout.decode("utf-8"), result.stderr.decode("utf-8")


def _hook(repo, *args):
    code, stdout, stderr = _run(repo, "check", *args, "--format", "hook-json")
    assert code == 0, stderr
    return json.loads(stdout), stderr


def _assert_size_block(payload, named):
    assert set(payload) == {"decision", "reason"}, payload
    assert payload["decision"] == "block"
    reason = payload["reason"]
    assert reason.startswith("checkwash: this change was not analysed, so the stop is blocked. "), reason
    assert f"A file checkwash must read is over the source byte limit: {named}. " in reason
    assert "Shrink or split the file, or revert your change to it." in reason
    assert ("Do not delete or truncate a file you did not create or change in this task; "
            "tell the user instead.") in reason
    # No exemption covers a refusal, and what CI makes of the change depends
    # on its version; an untracked file never reaches it.
    assert "checkwash allow" not in reason
    assert "CI" not in reason and "required check" not in reason


def _assert_note(payload, stderr, named):
    assert set(payload) == {"systemMessage"}, payload
    assert payload["systemMessage"].startswith(NOT_ANALYSED), payload
    assert f"{REFUSAL}: {named}" in payload["systemMessage"]
    assert f"{REFUSAL}: {named}" in stderr


# --- the verdict diff's own head or worktree side blocks ----------------------------------------------

WORKTREE_ROWS = {
    # name: (base extra files, working-tree files, the side the reason names, undo)
    "padded_test": (lambda: {}, lambda: {"tests/test_billing.py": PADDED},
                    described("tests/test_billing.py", "worktree"),
                    lambda repo: _write(repo, {"tests/test_billing.py": WEAKENED})),
    # The padding need not touch the test: any new must-read file will do.
    "untracked_py": (lambda: {}, lambda: {"tests/test_billing.py": WEAKENED, "scratch.py": blob(LIMIT + 1, "scratch")},
                     described("scratch.py", "worktree"), lambda repo: (repo / "scratch.py").unlink()),
    "untracked_extensionless": (lambda: {},
                                lambda: {"tests/test_billing.py": WEAKENED, "NOTES": blob(LIMIT + 1, "notes")},
                                described("NOTES", "worktree"), lambda repo: (repo / "NOTES").unlink()),
    # Both sides over the limit: the refusal names the base side, the first
    # unread one; the block names the side the session wrote.
    "both_sides": (lambda: {"vendor/big.py": blob(LIMIT + 1, "big")},
                   lambda: {"tests/test_billing.py": WEAKENED, "vendor/big.py": blob(LIMIT + 2, "bigger")},
                   described("vendor/big.py", "worktree", LIMIT + 2), None),
}


@pytest.mark.parametrize("row", sorted(WORKTREE_ROWS))
def test_a_worktree_side_over_the_limit_blocks_the_stop(tmp_path, row):
    base, edit, named, undo = WORKTREE_ROWS[row]
    repo = _repo(tmp_path, base())
    _write(repo, edit())
    payload, stderr = _hook(repo)
    _assert_size_block(payload, named)
    assert "(base," not in payload["reason"]
    # The stderr line every format writes for the refusal.
    assert f"checkwash engine error: SourceOverLimit: {REFUSAL}: " in stderr
    if undo is not None:
        # One edit removes the refusal, and the weakened test blocks as before.
        undo(repo)
        payload, _stderr = _hook(repo)
        assert payload["decision"] == "block"
        assert "ASSERT_WEAKENED" in payload["reason"] and "checkwash allow" in payload["reason"]


def test_a_head_side_over_the_limit_blocks_a_range_whatever_fail_on_says(tmp_path):
    # The refusal comes before any detector or gate runs, so no finding
    # exists for a threshold to drop: `--fail-on critical` still blocks.
    repo = _repo(tmp_path)
    _write(repo, {"tests/test_billing.py": PADDED})
    _commit(repo)
    payload, _stderr = _hook(repo, "HEAD~1..HEAD", "--fail-on", "critical")
    _assert_size_block(payload, described("tests/test_billing.py", "head"))


# --- what keeps the #414 message --------------------------------------------------------------------

@pytest.mark.parametrize("edit", ["shrunk", "deleted"])
def test_a_base_side_alone_over_the_limit_keeps_the_note(tmp_path, edit):
    # Ruling Q3: the session's edit did not put that side over the limit, and
    # reverting would restore the oversized original. The weakened test beside
    # it is a residual the ruling leaves to the required check.
    repo = _repo(tmp_path, {"tools/gen.py": blob(LIMIT + 1, "gen")})
    _write(repo, {"tests/test_billing.py": WEAKENED})
    if edit == "shrunk":
        _write(repo, {"tools/gen.py": b"GENERATED = 1\n"})
    else:
        (repo / "tools" / "gen.py").unlink()
    payload, stderr = _hook(repo)
    _assert_note(payload, stderr, described("tools/gen.py", "base"))


FLAGS = b"ENABLED = True\n"
GATED = (b"import pytest\n\nfrom flags import ENABLED\n\n\n"
         b"@pytest.mark.skipif(not ENABLED, reason=\"off\")\n"
         b"def test_enabled():\n"
         b"    assert ENABLED is True\n")
GATED_HEAD = GATED + (b"\n\n@pytest.mark.skipif(not ENABLED, reason=\"off\")\n"
                      b"def test_enabled_again():\n"
                      b"    assert ENABLED is True\n")


@pytest.mark.parametrize("fmt", ["json", "hook-json"])
def test_a_context_read_outside_the_diff_keeps_the_note(tmp_path, fmt):
    # D6 reads the skip condition's constant from the unchanged flags.py,
    # which is over the limit in the working tree as at HEAD. The refusal
    # names the worktree side of a path the verdict diff does not hold.
    repo = _repo(tmp_path, {"flags.py": FLAGS + b"#" * (LIMIT - len(FLAGS)) + b"\n", "tests/test_flag.py": GATED})
    _write(repo, {"tests/test_flag.py": GATED_HEAD})
    named = described("flags.py", "worktree")
    if fmt == "json":
        code, stdout, stderr = _run(repo, "check", "--format", "json")
        # #454 (d): exit 2, and stdout names the refused side, outside any
        # findings document.
        assert (code, json.loads(stdout)) == (2, {"unread": [_entry("flags.py", "worktree")]}), stderr
        assert f"{REFUSAL}: {named}" in stderr
    else:
        payload, stderr = _hook(repo)
        _assert_note(payload, stderr, named)


def test_a_base_manifest_over_the_limit_keeps_the_note(tmp_path):
    # No working-tree edit removes it, and it takes the GitError branch.
    repo = _repo(tmp_path, {"requirements.txt": blob(LIMIT + 1, "requirements")})
    _write(repo, {"tests/test_billing.py": WEAKENED})
    payload, stderr = _hook(repo)
    _assert_note(payload, stderr, described("requirements.txt", "base"))


def _input(event, **fields):
    return json.dumps({"session_id": "s-1", "hook_event_name": event, **fields}).encode("utf-8")


def test_a_size_refusal_in_the_session_commits_keeps_the_note(tmp_path):
    # D-142 item 4: the managed Stop hook's second analysis never blocks, so a
    # padded file the agent commits before stopping stays open (#418); the
    # required check judges it. Left uncommitted, the same file blocks.
    repo = _repo(tmp_path)
    started = _run(repo, "hook", "session-start", stdin=_input("SessionStart", source="startup"))
    assert started[:2] == (0, ""), started[2]
    stop = ("--hook-input", "stdin")
    _write(repo, {"tests/test_billing.py": PADDED})
    code, stdout, stderr = _run(repo, "check", "--format", "hook-json", *stop, stdin=_input("Stop"))
    assert code == 0, stderr
    _assert_size_block(json.loads(stdout), described("tests/test_billing.py", "worktree"))
    _commit(repo, "pad the test")
    code, stdout, stderr = _run(repo, "check", "--format", "hook-json", *stop, stdin=_input("Stop"))
    assert code == 0, stderr
    assert json.loads(stdout) == {"systemMessage": (
        "checkwash: commits made during this session were not analysed. Engine error: SourceOverLimit: "
        f"{REFUSAL}: {described('tests/test_billing.py', 'worktree')}")}


@pytest.mark.parametrize("args", [
    ("--format", "term"), ("--format", "json"), ("--format", "sarif"), ("--format", "hook-json", "--emit-ir"),
], ids=["term", "json", "sarif", "hook-json-emit-ir"])
def test_every_other_mode_keeps_exit_2(tmp_path, args):
    repo = _repo(tmp_path)
    _write(repo, {"tests/test_billing.py": PADDED})
    code, stdout, stderr = _run(repo, "check", *args)
    if args == ("--format", "json"):
        # #454 (d): json also names the refused side, outside any findings
        # document; the other modes keep an empty stdout.
        assert (code, json.loads(stdout)) == (2, {"unread": [_entry("tests/test_billing.py", "worktree")]}), stderr
    else:
        assert (code, stdout) == (2, ""), stderr
    assert stderr.splitlines() == [
        f"checkwash engine error: SourceOverLimit: {REFUSAL}: {described('tests/test_billing.py', 'worktree')}"]


@pytest.mark.parametrize("error", [
    # Another limit refusal that names a path and a side, but is no size refusal.
    EngineError("strict snapshot batch exceeds the byte limit at tests/test_billing.py "
                "(worktree, 64000001 > 64000000 bytes)"),
    RecursionError("maximum recursion depth exceeded"),
    # A size refusal for a side the verdict diff does not hold.
    SourceOverLimit(side("helpers/big.py", "worktree")),
], ids=["batch_limit", "recursion", "size_refusal_outside_the_diff"])
def test_other_engine_errors_keep_the_note(tmp_path, monkeypatch, capsys, error):
    # The change's own worktree side is over the limit too: only the matched
    # size refusal blocks, whatever else the run holds.
    repo = _repo(tmp_path)
    _write(repo, {"tests/test_billing.py": PADDED})

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(cli_module, "analyze", fail)
    assert main(["check", "--repo", str(repo), "--format", "hook-json"]) == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert set(payload) == {"systemMessage"}, payload
    assert payload["systemMessage"].startswith(NOT_ANALYSED)
    assert str(error) in payload["systemMessage"]
    assert "checkwash engine error: " in captured.err


# --- the match against the verdict diff -------------------------------------------------------------

MATCHES = {
    # name: (the change beside a readable test edit, the side refused, the side the block names)
    "worktree_side": (FileChange("tests/test_x.py", "modified", TEST, None,
                                 unread=(side("tests/test_x.py", "worktree"),)),
                      side("tests/test_x.py", "worktree"), side("tests/test_x.py", "worktree")),
    "head_side": (FileChange("tests/test_x.py", "added", None, None, unread=(side("tests/test_x.py", "head"),)),
                  side("tests/test_x.py", "head"), side("tests/test_x.py", "head")),
    "both_sides": (FileChange("vendor/big.py", "modified", None, None,
                              unread=(side("vendor/big.py", "base"), side("vendor/big.py", "worktree", LIMIT + 2))),
                   side("vendor/big.py", "base"), side("vendor/big.py", "worktree", LIMIT + 2)),
    "base_side_alone": (FileChange("tools/gen.py", "modified", None, b"GENERATED = 1\n",
                                   unread=(side("tools/gen.py", "base"),)),
                        side("tools/gen.py", "base"), None),
    "deleted": (FileChange("tools/gen.py", "deleted", None, None, unread=(side("tools/gen.py", "base"),)),
                side("tools/gen.py", "base"), None),
    # A rename is one change: its head side is the session's.
    "renamed": (FileChange("archive/old.txt", "modified", None, None, old_path="tests/test_old.py",
                           unread=(side("tests/test_old.py", "base"), side("archive/old.txt", "head"))),
                side("tests/test_old.py", "base"), side("archive/old.txt", "head")),
    "outside_the_diff": (FileChange("tests/test_x.py", "modified", TEST, None,
                                    unread=(side("tests/test_x.py", "worktree"),)),
                         side("flags.py", "worktree"), None),
}


@pytest.mark.parametrize("case", sorted(MATCHES))
def test_the_refusal_is_matched_against_the_verdict_diff(case):
    change, refused, named = MATCHES[case]
    changes = [FileChange("tests/test_billing.py", "modified", TEST, WEAKENED), change]
    assert _verdict_side_over_limit(changes, refused) == named

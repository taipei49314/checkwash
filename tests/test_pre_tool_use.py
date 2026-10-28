"""D-189: the managed PreToolUse hook asks before an Edit or Write weakens a test.

`checkwash hook pre-tool-use` reads Claude Code's PreToolUse input, predicts
the bytes the Edit or Write would leave on disk, and analyses that one change
against the working tree with `oracle_freeze` on and policy from the session
base (#418). It asks (`permissionDecision: "ask"`) when a finding of one of
the five weakening rules is at high or above, and prints `{}` otherwise. It
always exits 0, because a PreToolUse hook that exits 2 blocks the tool call.

D-189 also changes the Stop hook: its reason no longer offers `checkwash
allow`, and a stop that arrives with `stop_hook_active` true on the set it
last blocked on is released with a note for the user. The install default
moves to machine-local settings, which get the PreToolUse handler too.

These run the CLI on real repositories.
"""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

import checkwash.cli as cli_module
from checkwash.config import Config
from checkwash.doctor import collect
from checkwash.hooks import (
    _PRE_TOOL_BOOTSTRAP,
    has_pre_tool_use_hook,
    install_claude,
    is_managed_pre_tool_use_handler,
)
from checkwash.pretool import proposed_bytes, repository_path, weakening_reason

SRC = Path(__file__).resolve().parents[1] / "src"
ENV = {**os.environ, "PYTHONPATH": str(SRC), "PYTHONUTF8": "1", "GREENWASH_TODAY": "2026-10-28", "NO_COLOR": "1"}
ORIGINAL = "def test_total():\n    assert total() == 5\n"
TEST = "test_total.py"


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
    (root / TEST).write_bytes(ORIGINAL.encode())
    (root / "billing.py").write_bytes(b"def total():\n    return 5\n")
    git(root, "add", "-A")
    git(root, "commit", "-m", "base")
    return root


def cli(repo, *args, stdin=b""):
    return subprocess.run(
        [sys.executable, "-m", "checkwash", *args, "--repo", str(repo)],
        input=stdin, env=ENV, capture_output=True, timeout=120,
    )


def event(repo, tool, **tool_input):
    tool_input.setdefault("file_path", str(repo / TEST))
    return json.dumps({
        "session_id": "s-1", "transcript_path": "", "cwd": str(repo), "permission_mode": "default",
        "hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input, "tool_use_id": "toolu_1",
    }).encode("utf-8")


def pre_tool(repo, stdin):
    result = cli(repo, "hook", "pre-tool-use", stdin=stdin)
    assert result.returncode == 0, result.stderr
    assert result.stdout.decode("ascii").count("\n") == 1  # one JSON object, ASCII-escaped
    return json.loads(result.stdout)


def edit(repo, old, new, **extra):
    return pre_tool(repo, event(repo, "Edit", old_string=old, new_string=new, replace_all=False, **extra))


def write(repo, content, path=None):
    fields = {"content": content} if path is None else {"content": content, "file_path": str(path)}
    return pre_tool(repo, event(repo, "Write", **fields))


def asked(payload):
    out = payload.get("hookSpecificOutput") or {}
    assert set(payload) <= {"hookSpecificOutput"}
    if not out:
        return None
    assert out["hookEventName"] == "PreToolUse" and out["permissionDecision"] == "ask"
    return out["permissionDecisionReason"]


# --- which edits ask ---------------------------------------------------------------------------------

@pytest.mark.parametrize("rule,after", [
    ("ASSERT_WEAKENED", "def test_total():\n    assert total() > 0\n"),
    ("ASSERT_REMOVED", "def test_total():\n    total()\n"),
    ("TEST_DISABLED", "import pytest\n\n\n@pytest.mark.skip\ndef test_total():\n    assert total() == 5\n"),
    ("BROAD_EXCEPT_ADDED", "def test_total():\n    try:\n        assert total() == 5\n    except Exception:\n        pass\n"),
])
def test_each_weakening_rule_asks(repo, rule, after):
    reason = asked(write(repo, after))
    assert reason is not None and rule in reason
    assert "Approve only if the weaker test is intended" in reason
    assert "checkwash allow" not in reason


def test_a_loosened_tolerance_asks(repo):
    (repo / TEST).write_bytes(b"import pytest\n\n\ndef test_total():\n    assert total() == pytest.approx(5, rel=1e-9)\n")
    git(repo, "commit", "-am", "approx")
    assert "TOLERANCE_LOOSENED" in asked(edit(repo, "rel=1e-9", "rel=0.5"))


def test_an_edit_asks_as_a_write_does(repo):
    assert "ASSERT_WEAKENED" in asked(edit(repo, "== 5", "> 0"))


def test_an_expected_value_change_does_not_ask(repo):
    # The expectation rules are left to the Stop hook and CI (D-189).
    assert edit(repo, "== 5", "== 6") == {}


def test_a_new_test_file_does_not_ask(repo):
    assert write(repo, "def test_new():\n    assert True\n", repo / "test_new.py") == {}


def test_a_production_file_is_not_analysed(repo):
    assert pre_tool(repo, event(repo, "Edit", file_path=str(repo / "billing.py"), old_string="return 5",
                                new_string="return 6", replace_all=False)) == {}


def test_a_multiedit_is_applied_edit_by_edit(repo):
    payload = pre_tool(repo, event(repo, "MultiEdit", edits=[
        {"old_string": "def test_total", "new_string": "def test_sum"},
        {"old_string": "== 5", "new_string": "> 0"},
    ]))
    assert asked(payload) is not None


def test_the_working_tree_is_the_before_side(repo):
    # An earlier, unasked change stays in the working tree: only this call's
    # own change is judged, so a later honest edit does not ask again.
    (repo / TEST).write_bytes(b"def test_total():\n    assert total() > 0\n")
    assert edit(repo, "def test_total():", "def test_total():  # the invoice total") == {}


def test_an_unparseable_working_copy_is_compared_with_head(repo):
    (repo / TEST).write_bytes(b"def test_total(:\n    assert total() == 5\n")
    reason = asked(write(repo, "def test_total():\n    assert total() > 0\n"))
    assert reason is not None and "ASSERT_WEAKENED" in reason


# --- policy comes from the base --------------------------------------------------------------------

def _fingerprint(repo, after):
    (repo / TEST).write_bytes(after.encode())
    report = json.loads(cli(repo, "check", "--format", "json").stdout)
    git(repo, "checkout", "--", TEST)
    return next(f["fingerprint"] for f in report["findings"] if f["rule"] == "ASSERT_WEAKENED")


def test_an_exemption_committed_at_the_base_is_honoured(repo):
    weaker = "def test_total():\n    assert total() > 0\n"
    fingerprint = _fingerprint(repo, weaker)
    assert cli(repo, "allow", fingerprint, "--reason", "reviewed").returncode == 0
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "exempt")
    assert write(repo, weaker) == {}


def test_an_exemption_only_in_the_working_tree_is_not(repo):
    weaker = "def test_total():\n    assert total() > 0\n"
    fingerprint = _fingerprint(repo, weaker)
    assert cli(repo, "allow", fingerprint, "--reason", "self-approved").returncode == 0
    assert asked(write(repo, weaker)) is not None


# --- what it never does ----------------------------------------------------------------------------

@pytest.mark.parametrize("stdin", [
    b"", b"not json", b"[]", json.dumps({"hook_event_name": "Stop"}).encode(),
    json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"}}).encode(),
    json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Edit", "tool_input": "x"}).encode(),
])
def test_input_it_cannot_use_prints_an_empty_object(repo, stdin):
    assert pre_tool(repo, stdin) == {}


def test_unknown_arguments_never_exit_2(repo):
    result = subprocess.run([sys.executable, "-m", "checkwash", "hook", "pre-tool-use", "--bogus", "-x"],
                            input=b"{}", env=ENV, capture_output=True, timeout=120, cwd=str(repo))
    assert result.returncode == 0 and json.loads(result.stdout) == {}


def test_outside_a_repository_it_prints_an_empty_object(tmp_path):
    result = cli(tmp_path, "hook", "pre-tool-use", stdin=b"{}")
    assert result.returncode == 0 and json.loads(result.stdout) == {}


@pytest.mark.parametrize("old,new,every", [("nope", "x", False), ("5", "6", False)])
def test_an_edit_the_tool_would_refuse_prints_an_empty_object(repo, old, new, every):
    (repo / TEST).write_bytes(b"def test_total():\n    assert total() == 5\n    assert 5\n")
    assert pre_tool(repo, event(repo, "Edit", old_string=old, new_string=new, replace_all=every)) == {}


def test_a_path_outside_the_repository_prints_an_empty_object(repo, tmp_path):
    outside = tmp_path / "elsewhere" / "test_x.py"
    outside.parent.mkdir()
    outside.write_bytes(ORIGINAL.encode())
    assert pre_tool(repo, event(repo, "Edit", file_path=str(outside), old_string="== 5", new_string="> 0",
                                replace_all=False)) == {}


def test_a_relative_path_is_read_against_cwd(repo):
    assert asked(pre_tool(repo, event(repo, "Edit", file_path=TEST, old_string="== 5", new_string="> 0",
                                      replace_all=False))) is not None


def test_a_proposed_file_over_the_source_limit_asks(repo):
    reason = asked(write(repo, ORIGINAL + "#" * 1_000_001 + "\n"))
    assert reason is not None and "over the source byte limit" in reason


def test_reason_text_is_one_printable_line():
    override = chr(0x202E)  # a right-to-left override, built so this file holds none

    class Finding:
        rule, path, unit, message = "ASSERT_WEAKENED", "test_x.py", f"test_{override}total", "line one\nline two"

    reason = weakening_reason([Finding()] * 5)
    assert override not in reason and "\n" not in reason and "\\u202e" in reason
    assert "; and 2 more" in reason and len(reason) <= 1200


# --- the unanalysed path and the pure helpers -------------------------------------------------------

@pytest.mark.parametrize("policy,key", [("block", "hookSpecificOutput"), ("pass_with_warning", "systemMessage")])
def test_an_unanalysed_edit_follows_on_engine_error(policy, key):
    config = Config()
    config.on_engine_error = policy
    payload = cli_module._pre_tool_unanalysed({"config": config, "rel": "test_x.py"}, "boom")
    assert list(payload) == [key]
    assert "was not analysed before it was made" in json.dumps(payload)


def test_an_unanalysed_edit_before_the_role_check_says_nothing():
    assert cli_module._pre_tool_unanalysed({}, "boom") == {}


def test_crlf_files_are_matched_with_crlf_line_ends():
    before = b"def test_total():\r\n    assert total() == 5\r\n"
    after = proposed_bytes("Edit", {"old_string": "():\n    assert", "new_string": "():\n    x = 1\n    assert"}, before)
    assert after == b"def test_total():\r\n    x = 1\r\n    assert total() == 5\r\n"


def test_repository_path_refuses_git_and_nested_repositories(repo):
    assert repository_path(str(repo), str(repo / ".git" / "test_x.py")) is None
    nested = repo / "vendor" / "lib"
    nested.mkdir(parents=True)
    (nested / ".git").mkdir()
    assert repository_path(str(repo), str(nested / "test_x.py")) is None
    assert repository_path(str(repo), str(repo / "tests" / "test_x.py")) == "tests/test_x.py"


# --- installation and doctor -----------------------------------------------------------------------

def _settings(repo, name):
    return json.loads((repo / ".claude" / name).read_text(encoding="utf-8"))


def test_the_default_install_is_local_and_adds_the_pre_tool_use_group(repo):
    result = cli(repo, "hook", "install", "--agent", "claude-code")
    assert result.returncode == 0, result.stderr
    settings = _settings(repo, "settings.local.json")
    groups = settings["hooks"]["PreToolUse"]
    assert len(groups) == 1 and groups[0]["matcher"] == "Edit|Write|MultiEdit"
    handler, = groups[0]["hooks"]
    assert is_managed_pre_tool_use_handler(handler)
    assert handler["args"][2] == _PRE_TOOL_BOOTSTRAP and handler["args"][4:] == ["hook", "pre-tool-use"]
    assert has_pre_tool_use_hook(settings)
    again = cli(repo, "hook", "install", "--agent", "claude-code")
    assert again.stdout.decode().startswith("already installed:")
    assert _settings(repo, "settings.local.json") == settings


def test_the_installed_handler_asks(repo):
    assert cli(repo, "hook", "install", "--agent", "claude-code").returncode == 0
    handler = _settings(repo, "settings.local.json")["hooks"]["PreToolUse"][0]["hooks"][0]
    result = subprocess.run([handler["command"], *handler["args"]], cwd=str(repo),
                            input=event(repo, "Edit", old_string="== 5", new_string="> 0", replace_all=False),
                            capture_output=True, timeout=120)
    assert result.returncode == 0
    assert asked(json.loads(result.stdout)) is not None


def test_the_bootstrap_exits_0_whatever_the_bound_runtime_does(tmp_path):
    # An older checkwash left at the bound path answers with a usage error.
    package = tmp_path / "old" / "checkwash"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "cli.py").write_text("def main():\n    raise SystemExit(2)\n")
    binding = json.dumps({"kind": "package", "path": str(package.parent),
                          "origin": os.path.realpath(package / "__init__.py")})
    result = subprocess.run([sys.executable, "-I", "-c", _PRE_TOOL_BOOTSTRAP, binding, "hook", "pre-tool-use"],
                            input=b"{}", capture_output=True, timeout=60, cwd=str(tmp_path))
    assert result.returncode == 0 and result.stdout == b""


def test_shared_settings_get_no_pre_tool_use_handler(repo, monkeypatch):
    monkeypatch.setattr("checkwash.hooks._shared_executable", lambda: sys.executable)
    monkeypatch.setattr("checkwash.hooks._probe", lambda command, args: None)
    message = install_claude(str(repo), False)
    assert "No PreToolUse hook is installed in shared settings" in message
    assert "PreToolUse" not in _settings(repo, "settings.json")["hooks"]


def test_scope_flags_are_exclusive_and_the_default_refuses_beside_shared_handlers(repo):
    assert cli(repo, "hook", "install", "--agent", "claude-code", "--local", "--shared").returncode == 2
    (repo / ".claude").mkdir()
    (repo / ".claude" / "settings.json").write_text(json.dumps({"hooks": {"Stop": [{"hooks": [
        {"type": "command", "command": "checkwash", "args": ["check", "--format", "hook-json", "--hook-input", "stdin"]},
    ]}]}}))
    refused = cli(repo, "hook", "install", "--agent", "claude-code")
    assert refused.returncode == 2 and b"--shared" in refused.stderr
    assert not (repo / ".claude" / "settings.local.json").exists()
    assert cli(repo, "hook", "install", "--agent", "claude-code", "--local").returncode == 0


def test_a_users_own_pre_tool_use_group_is_left_alone(repo):
    (repo / ".claude").mkdir()
    custom = {"matcher": "Edit", "hooks": [{"type": "command", "command": "my-linter"}]}
    (repo / ".claude" / "settings.local.json").write_text(json.dumps({"hooks": {"PreToolUse": [custom]}}))
    assert cli(repo, "hook", "install", "--agent", "claude-code").returncode == 0
    groups = _settings(repo, "settings.local.json")["hooks"]["PreToolUse"]
    assert groups[0] == custom and len(groups) == 2


def test_doctor_names_a_missing_pre_tool_use_hook(repo):
    (repo / ".claude").mkdir()
    (repo / ".claude" / "settings.json").write_text(json.dumps({"hooks": {"Stop": [{"hooks": [
        {"type": "command", "command": "checkwash", "args": ["check", "--format", "hook-json", "--hook-input", "stdin"]},
    ]}]}}))
    notes = collect(repo)
    titles = [n.title for n in notes]
    assert "the PreToolUse ask and the Stop hook are not both configured" in titles
    local = next(n for n in notes if "configured locally but not in CI" in n.title)
    assert "a Claude Code Stop hook configuration in .claude/settings.json" in local.detail


# --- the Stop hook releases a repeated block (D-189) -----------------------------------------------

def stop(repo, active, session="s-1", flag=True):
    args = ["check", "--format", "hook-json"] + (["--hook-input", "stdin"] if flag else [])
    data = json.dumps({"session_id": session, "hook_event_name": "Stop", "stop_hook_active": active}).encode()
    result = cli(repo, *args, stdin=data)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.fixture
def weakened(repo):
    (repo / TEST).write_bytes(b"def test_total():\n    assert total() > 0\n")
    return repo


def test_a_continuation_on_the_set_it_blocked_on_is_released(weakened):
    assert stop(weakened, False)["decision"] == "block"
    released = stop(weakened, True)
    assert "decision" not in released
    assert "this stop was not blocked again" in released["systemMessage"]
    assert "ASSERT_WEAKENED" in released["systemMessage"]


def test_another_hooks_continuation_still_blocks(weakened):
    assert stop(weakened, True)["decision"] == "block"


def test_a_new_finding_blocks_again(weakened):
    assert stop(weakened, False)["decision"] == "block"
    (weakened / TEST).write_bytes(b"import pytest\n\n\n@pytest.mark.skip\ndef test_total():\n    assert total() > 0\n")
    assert stop(weakened, True)["decision"] == "block"


@pytest.mark.parametrize("active", ["true", 1, None])
def test_only_json_true_counts_as_active(weakened, active):
    assert stop(weakened, False)["decision"] == "block"
    assert stop(weakened, active)["decision"] == "block"


def test_a_pass_forgets_the_set(weakened):
    assert stop(weakened, False)["decision"] == "block"
    git(weakened, "checkout", "--", TEST)
    assert "decision" not in stop(weakened, False)
    (weakened / TEST).write_bytes(b"def test_total():\n    assert total() > 0\n")
    assert stop(weakened, True)["decision"] == "block"


def test_without_hook_input_every_stop_blocks(weakened):
    assert stop(weakened, False, flag=False)["decision"] == "block"
    assert stop(weakened, True, flag=False)["decision"] == "block"


def test_the_size_block_blocks_on_every_stop(weakened):
    (weakened / "test_big.py").write_bytes(b"#" * 1_000_001)
    for active in (False, True, True):
        payload = stop(weakened, active)
        assert payload["decision"] == "block"
        assert "over the source byte limit" in payload["reason"]

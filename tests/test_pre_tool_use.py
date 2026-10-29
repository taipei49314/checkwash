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
from checkwash.findings import Evidence, Finding
from checkwash.hooks import (
    _PRE_TOOL_BOOTSTRAP,
    has_pre_tool_use_hook,
    install_claude,
    is_managed_pre_tool_use_handler,
)
from checkwash.pretool import INPUT_BYTE_CAP, evidence_clause, proposed_bytes, repository_path, weakening_reason
from checkwash.session import read_hook_input

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


def test_a_working_copy_the_engine_parses_is_not_replaced_by_head(repo):
    # A byte that is not UTF-8, in a comment: the engine decodes it as U+FFFD
    # and parses the file, so its assertion is the before side, not HEAD's.
    (repo / TEST).write_bytes(b"def test_total():\n    assert total() > 0\n")
    git(repo, "commit", "-am", "weak at HEAD")
    (repo / TEST).write_bytes(b"# \xff\ndef test_total():\n    assert total() == 5\n")
    reason = asked(write(repo, "def test_total():\n    assert total() > 0\n"))
    assert reason is not None and "ASSERT_WEAKENED" in reason


@pytest.mark.skipif(os.name != "nt", reason="Windows folds case and drops trailing dots and spaces")
@pytest.mark.parametrize("spelling", ["test_total.py.", "test_total.py ", "TEST_TOTAL.PY"])
def test_a_windows_spelling_of_the_test_still_asks(repo, spelling):
    assert asked(pre_tool(repo, event(repo, "Edit", file_path=str(repo / spelling), old_string="== 5",
                                      new_string="> 0", replace_all=False))) is not None


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


# --- failure relays (D-190) --------------------------------------------------------------------------

RELAY = '''

async def test_callback_total():
    fut = asyncio.Future()

    def cb():
        try:
            assert total() == 5
        except Exception as e:
            fut.set_exception(e)
        else:
            fut.set_result(None)

    asyncio.get_running_loop().call_soon(cb)
    await fut
'''


def test_adding_a_proven_failure_relay_does_not_ask(repo):
    assert write(repo, "import asyncio\n\n\n" + ORIGINAL + RELAY) == {}


def test_adding_a_relay_outside_the_rules_asks(repo):
    # Nothing consumes the future, so the handler swallows the failure (R5).
    reason = asked(write(repo, "import asyncio\n\n\n" + ORIGINAL + RELAY.replace("    await fut\n", "")))
    assert reason is not None and "BROAD_EXCEPT_ADDED" in reason


UNREAD_RELAY = '''import asyncio


def test_callback_total():
    async def main():
        fut = asyncio.get_running_loop().create_future()

        def cb():
            try:
                assert total() == 5
            except Exception as e:
                fut.set_exception(e)
            else:
                fut.set_result(None)

        asyncio.get_running_loop().call_soon(cb)
        await fut

    asyncio.run(main())
'''


def test_a_new_file_with_a_relay_the_rules_do_not_read_asks(repo):
    # A residual (KNOWN-ISSUES-next): this honest relay, through asyncio.run
    # and get_running_loop().create_future(), is outside R1 to R7, and a new
    # file is analysed as an addition.
    reason = asked(write(repo, UNREAD_RELAY, repo / "test_new.py"))
    assert reason is not None and "BROAD_EXCEPT_ADDED" in reason


def test_breaking_a_failure_relay_does_not_ask(repo):
    # A residual, the same as 0.10 (THREATMODEL row 171): both sides hold the
    # handler, so removing the await adds nothing to count.
    (repo / TEST).write_bytes(("import asyncio\n\n\n" + ORIGINAL + RELAY).encode())
    git(repo, "commit", "-am", "relay")
    assert edit(repo, "    await fut\n", "    pass\n") == {}


def test_a_relay_made_proven_does_not_hide_a_new_swallow(repo):
    # The 2026-10-29 adversarial reviews: the base holds the relay without
    # its await, so it counts as a swallow; the write restores the await and
    # swallows test_total's own assertion under the same first line. Only
    # the after side's relays are credited, so the new swallow still asks.
    (repo / TEST).write_bytes(("import asyncio\n\n\n" + ORIGINAL + RELAY.replace("    await fut\n", "")).encode())
    git(repo, "commit", "-am", "relay without its await")
    swallowed = ORIGINAL.replace("    assert total() == 5\n",
                                 "    try:\n        assert total() == 5\n    except Exception as e:\n        print(e)\n")
    reason = asked(write(repo, "import asyncio\n\n\n" + swallowed + RELAY))
    assert reason is not None and "BROAD_EXCEPT_ADDED" in reason


# --- the assertion's text in the ask and the Stop reason (D-191) -------------------------------------
#
# The ASSERT_WEAKENED message names lattice strengths, and in the D-189
# lifecycle receipt Claude restated `EXACT_VALUE(90)` as an expected value of
# 90. Both hook reasons now quote the assertion itself, for ASSERT_WEAKENED
# and ASSERT_REMOVED only; the finding message and the reports are unchanged.

ASK_TAIL = ("Approve only if the weaker test is intended. If you deny it, Claude should report the finding "
            "to you, not make the same change another way.")
STOP_TAIL = ("Fix the production code if it is wrong. Do not weaken, skip or remove the test, and do not add "
             "an exemption or change checkwash's configuration or hooks yourself: if you believe the test "
             "change is correct, tell the user which finding blocks and why, and let the user decide.")
STRENGTH = "test_total: assertion strength EXACT_VALUE(90) -> BOUND(40)"
REMOVED = "test_total: assertion removed (strength EXACT_VALUE)"


def _finding(rule, before=None, after=None, message=STRENGTH, unit="test_total"):
    return Finding(rule=rule, severity="high", message=message, path=TEST, unit=unit,
                   before=None if before is None else Evidence(before, (2, 2)),
                   after=None if after is None else Evidence(after, (2, 2)))


def test_the_clause_quotes_a_weakened_assertion_and_a_removed_one():
    weakened = _finding("ASSERT_WEAKENED", "assert total() == 105.3", "assert total() > 0")
    assert evidence_clause(weakened) == " (before: assert total() == 105.3; after: assert total() > 0)"
    removed = _finding("ASSERT_REMOVED", "assert total() != 6", message=REMOVED)
    assert evidence_clause(removed) == " (before: assert total() != 6)"


@pytest.mark.parametrize("rule,before,after", [
    # Their evidence is already in their messages.
    ("TOLERANCE_LOOSENED", "rel=1e-9", "rel=0.5"),
    ("BROAD_EXCEPT_ADDED", None, "exceptException:"),
    ("TEST_DISABLED", None, "pytest.mark.skip"),
    # Rules the clause is not for, though their evidence is assertion text.
    ("EXPECTED_VALUE_CHANGED", "assert total() == 5", "assert total() == 6"),
    ("ASSERT_SUBSTITUTED", "assert total() == 5", "assert other() == 5"),
    # A finding without the evidence its rule's clause needs.
    ("ASSERT_WEAKENED", "assert total() == 5", None),
    ("ASSERT_WEAKENED", " \n\t", "assert total() > 0"),
    ("ASSERT_REMOVED", None, None),
])
def test_no_clause_for_other_rules_or_missing_evidence(rule, before, after):
    assert evidence_clause(_finding(rule, before, after)) == ""


def test_no_clause_for_a_finding_without_evidence_attributes():
    class Bare:
        rule, path, unit, message = "ASSERT_WEAKENED", TEST, "test_total", STRENGTH

    assert evidence_clause(Bare()) == ""


def test_the_clause_collapses_whitespace_and_cuts_each_side_at_120_characters():
    multiline = "assert total(\n        1,\t2) == 105.3, (\r\n        'msg')"
    assert evidence_clause(_finding("ASSERT_REMOVED", multiline)) == " (before: assert total( 1, 2) == 105.3, ( 'msg'))"
    whole = "assert name == '" + "a" * 103 + "'"
    long = "assert name == '" + "b" * 200 + "'"
    assert len(whole) == 120  # kept whole; a longer side is cut to 119 characters and an ellipsis
    assert evidence_clause(_finding("ASSERT_WEAKENED", whole, long)) == f" (before: {whole}; after: {long[:119]}…)"


def test_the_clause_escapes_control_and_bidi_characters():
    override, isolate, bell = chr(0x202E), chr(0x2066), chr(0x07)  # built so this file holds none
    clause = evidence_clause(_finding("ASSERT_WEAKENED", f"assert name == 'ab{override}c'",
                                      f"assert name{isolate} > {bell}0"))
    assert clause == " (before: assert name == 'ab\\u202ec'; after: assert name\\u2066 > \\u00070)"
    # The cut counts the assertion's own characters, before they are escaped.
    assert evidence_clause(_finding("ASSERT_REMOVED", override * 130)) == " (before: " + "\\u202e" * 119 + "…)"


def test_the_ask_quotes_the_assertion(repo):
    assert asked(edit(repo, "== 5", "> 0")) == (
        "checkwash: this edit weakens a test (1 finding(s)): ASSERT_WEAKENED test_total.py :: test_total — "
        f"{STRENGTH} (before: assert total() == 5; after: assert total() > 0). " + ASK_TAIL)
    assert asked(write(repo, "def test_total():\n    total()\n")) == (
        "checkwash: this edit weakens a test (1 finding(s)): ASSERT_REMOVED test_total.py :: test_total — "
        f"{REMOVED} (before: assert total() == 5). " + ASK_TAIL)


def test_the_ask_adds_no_clause_to_a_loosened_tolerance(repo):
    (repo / TEST).write_bytes(b"import pytest\n\n\ndef test_total():\n    assert total() == pytest.approx(5, rel=1e-9)\n")
    git(repo, "commit", "-am", "approx")
    assert asked(edit(repo, "rel=1e-9", "rel=0.5")) == (
        "checkwash: this edit weakens a test (1 finding(s)): TOLERANCE_LOOSENED test_total.py :: test_total — "
        "test_total: tolerance loosened (rel=1e-9 -> rel=0.5). " + ASK_TAIL)


def test_each_named_finding_gets_its_own_clause():
    broad = _finding("BROAD_EXCEPT_ADDED", None, "exceptException:",
                     message="broad exception handler added (exceptException:)", unit=None)
    weak = _finding("ASSERT_WEAKENED", "assert total() == 5", "assert total() > 0")
    assert weakening_reason([broad, weak]) == (
        "checkwash: this edit weakens a test (2 finding(s)): BROAD_EXCEPT_ADDED test_total.py — broad exception "
        f"handler added (exceptException:); ASSERT_WEAKENED test_total.py :: test_total — {STRENGTH} (before: "
        "assert total() == 5; after: assert total() > 0). " + ASK_TAIL)


def test_the_named_findings_come_before_their_clauses():
    # Three named findings and the count fit in 1,200 characters, with room
    # for two of the three clauses: they are added in order while they fit.
    weak = _finding("ASSERT_WEAKENED", "assert total() == " + "1" * 200, "assert total() > 0", message="m" * 150)
    reason = weakening_reason([weak] * 5)
    assert len(reason) <= 1200
    assert reason.count(f"ASSERT_WEAKENED {TEST} :: test_total — " + "m" * 150) == 3
    assert reason.count(evidence_clause(weak)) == 2
    assert reason.endswith("m; and 2 more. " + ASK_TAIL)


def test_a_cut_keeps_the_count_of_the_findings_not_named():
    weak = _finding("ASSERT_WEAKENED", "assert total() == 5", "assert total() > 0", message="m" * 600)
    reason = weakening_reason([weak] * 5)
    assert len(reason) == 1200 and evidence_clause(weak) not in reason
    assert reason.endswith("m…; and 2 more. " + ASK_TAIL)
    # With three findings or fewer there is no count, and the cut ends the text as before.
    one = weakening_reason([_finding("ASSERT_WEAKENED", "assert total() == 5", "assert total() > 0", message="m" * 2000)])
    assert len(one) == 1200 and one.endswith("m…. " + ASK_TAIL)


def test_the_stop_reason_quotes_the_assertion(weakened):
    assert stop(weakened, False)["reason"] == (
        f"checkwash: 1 finding(s) blocking. ASSERT_WEAKENED test_total.py :: test_total — {STRENGTH} "
        "(before: assert total() == 5; after: assert total() > 0). " + STOP_TAIL)


def test_the_stop_reason_escapes_its_clause():
    head = _finding("ASSERT_REMOVED", f"assert name == 'ab{chr(0x202E)}c'", message=REMOVED)
    assert cli_module._block_reason([head]) == (
        f"checkwash: 1 finding(s) blocking. ASSERT_REMOVED test_total.py :: test_total — {REMOVED} "
        "(before: assert name == 'ab\\u202ec'). " + STOP_TAIL)


@pytest.mark.parametrize("rule,before,after,unit,message", [
    ("TEST_DISABLED", None, "pytest.mark.skip", "test_total", "test_total: disabling marker added (pytest.mark.skip)"),
    ("BROAD_EXCEPT_ADDED", None, "exceptException:", None, "broad exception handler added (exceptException:)"),
    ("TOLERANCE_LOOSENED", "rel=1e-9", "rel=0.5", "test_total", "test_total: tolerance loosened (rel=1e-9 -> rel=0.5)"),
    ("EXPECTED_VALUE_CHANGED", "assert total() == 5", "assert total() == 6", "test_total",
     "test_total: expected value changed"),
])
def test_the_stop_reason_of_other_rules_is_unchanged(rule, before, after, unit, message):
    # D-189's text, byte for byte. Only the first finding is named, so a
    # weakened assertion after it adds nothing either.
    named = f"{rule} {TEST}" + (f" :: {unit}" if unit else "")
    head = _finding(rule, before, after, message=message, unit=unit)
    assert cli_module._block_reason([head, _finding("ASSERT_WEAKENED", "assert a == 1", "assert a")]) == (
        f"checkwash: 2 finding(s) blocking. {named} — {message}. " + STOP_TAIL)


def test_a_skip_blocks_the_stop_with_the_d189_reason(repo):
    (repo / TEST).write_bytes(b"import pytest\n\n\n@pytest.mark.skip\ndef test_total():\n    assert total() == 5\n")
    assert stop(repo, False)["reason"] == (
        "checkwash: 1 finding(s) blocking. TEST_DISABLED test_total.py :: test_total — test_total: disabling "
        "marker added (pytest.mark.skip). " + STOP_TAIL)


# --- new files, bought repair evidence and input the hook does not read (D-191) ---------------------
#
# #419's residual statement says where the ask fires and where it does not.
# A new file has no before-side units, so the four unit-scoped rules cannot
# fire on it, but three cases still ask.

def test_a_new_test_file_still_asks_about_a_swallowing_broad_except(repo):
    swallowed = "def test_new():\n    try:\n        assert total() == 5\n    except Exception:\n        pass\n"
    reason = asked(write(repo, swallowed, repo / "test_new.py"))
    assert reason is not None and "BROAD_EXCEPT_ADDED test_new.py — " in reason
    # A proven failure relay in a new file is not an added swallow (D-190).
    assert write(repo, "import asyncio\n\n\n" + ORIGINAL + RELAY, repo / "test_new.py") == {}


def test_a_new_conftest_still_asks_about_a_suite_control(repo):
    reason = asked(write(repo, 'collect_ignore = ["test_total.py"]\n', repo / "conftest.py"))
    assert reason is not None and "TEST_DISABLED conftest.py :: <suite> — " in reason


def test_a_new_test_file_over_the_source_limit_asks(repo):
    reason = asked(write(repo, "def test_new():\n    assert True\n" + "#" * 1_000_001 + "\n", repo / "test_new.py"))
    assert reason is not None and "test_new.py (proposed, " in reason and "over the source byte limit" in reason


def test_a_new_test_file_has_no_unit_to_weaken(repo):
    new = "import pytest\n\n\n@pytest.mark.skip\ndef test_new():\n    assert total() > 0\n"
    assert write(repo, new, repo / "test_new.py") == {}


IMPORTING = "from billing import total\n\n\ndef test_total():\n    assert total() == 5\n"


@pytest.mark.parametrize("bought", ["plus_zero", "template_comment"])
def test_bought_repair_evidence_does_not_stop_the_ask(repo, bought):
    # #419: the ask judges the one edit with oracle_freeze forced, so a kept
    # no-op in a called function (Route A) or a comment in a template (Route
    # B) in the working tree does not lower its five rules. The Stop hook,
    # with no freeze, passes the same change at the default fail_on.
    template = repo / "app" / "templates" / "invoice.html"
    template.parent.mkdir(parents=True)
    template.write_bytes(b"<p>{{ total }}</p>\n")
    (repo / TEST).write_bytes(IMPORTING.encode())
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "an importing test and a template")
    if bought == "plus_zero":
        (repo / "billing.py").write_bytes(b"def total():\n    return 5 + 0\n")
    else:
        template.write_bytes(b"<!-- note -->\n<p>{{ total }}</p>\n")
    reason = asked(edit(repo, "== 5", "> 0"))
    assert reason is not None and "ASSERT_WEAKENED" in reason
    (repo / TEST).write_bytes(IMPORTING.replace("== 5", "> 0").encode())
    assert json.loads(cli(repo, "check", "--format", "hook-json").stdout) == {}


def _block_on_engine_errors(repo):
    (repo / ".checkwash").mkdir()
    (repo / ".checkwash" / "config.toml").write_bytes(b'[gate]\non_engine_error = "block"\n')


def test_hook_input_over_the_cap_is_not_analysed(repo):
    # Input over pretool.INPUT_BYTE_CAP is not read further, so the hook
    # answers {}, even under on_engine_error = "block" (THREATMODEL row 169).
    # An Edit that large can leave a small file, which the Stop hook judges
    # at its own severities, without the forced freeze; a Write that large
    # leaves a file over the source limit, which the Stop hook's size block
    # (#456) blocks.
    pad = "\x01" * 999_000
    padded = ORIGINAL + '\n\nX = "' + pad + '"\n'
    _block_on_engine_errors(repo)
    (repo / TEST).write_bytes(padded.encode())
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "padded")
    old, new = '== 5\n\n\nX = "' + pad, '> 0\n\n\nX = "' + "\x01" * 350_000
    stdin = event(repo, "Edit", old_string=old, new_string=new, replace_all=False)
    assert len(stdin) > INPUT_BYTE_CAP and pre_tool(repo, stdin) == {}
    (repo / TEST).write_bytes(padded.replace(old, new).encode())
    assert (repo / TEST).stat().st_size < 1_000_000
    payload = stop(repo, False)
    assert payload["decision"] == "block" and "ASSERT_WEAKENED" in payload["reason"]

    big = ORIGINAL.replace("== 5", "> 0") + "#" * 8_100_000 + "\n"
    stdin = event(repo, "Write", content=big)
    assert len(stdin) > INPUT_BYTE_CAP and pre_tool(repo, stdin) == {}
    (repo / TEST).write_bytes(big.encode())
    payload = stop(repo, False)
    assert payload["decision"] == "block" and "over the source byte limit" in payload["reason"]


def test_hook_input_cut_off_or_never_sent_is_not_analysed(repo):
    # Input that is not complete when the 10-second wait ends (cut short here)
    # is not analysed: {} before any policy is read, so on_engine_error =
    # "block" does not turn it into an ask.
    _block_on_engine_errors(repo)
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "block on engine errors")
    weakening = event(repo, "Edit", old_string="== 5", new_string="> 0", replace_all=False)
    for sent in (b"", weakening[:-1]):
        read_end, write_end = os.pipe()
        stream = os.fdopen(read_end, "rb")
        try:
            if sent:
                os.write(write_end, sent)
            hook_input = read_hook_input(stream, cap=INPUT_BYTE_CAP, wait=0.2)
        finally:
            os.close(write_end)
            stream.close()
        state: dict = {}
        assert cli_module._pre_tool_use(str(repo), hook_input, state) == {} and state == {}
    assert asked(pre_tool(repo, weakening)) is not None  # the whole input asks

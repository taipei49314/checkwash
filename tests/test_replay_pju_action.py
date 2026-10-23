"""Fail-closed composite replay boundaries; no engine, install or network runs."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("pju_replayer_tests", ROOT / "tools/replay_pju_action.py")
replay = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(replay)
COLLECT_SPEC = importlib.util.spec_from_file_location("pju_collector_tests", ROOT / "tools/collect_pju_receipts.py")
collector = importlib.util.module_from_spec(COLLECT_SPEC)
COLLECT_SPEC.loader.exec_module(collector)


def action_bytes():
    # Fixtures use the reviewed YAML text regardless of the test checkout's EOL.
    # The real replayer additionally requires its checkout bytes to equal Git.
    return (ROOT / "action/action.yml").read_text(encoding="utf-8").encode("utf-8")


def test_real_composite_preserves_run_scalars_and_comment_is_not_selected():
    definition = replay.load_action(action_bytes())
    selected = definition["runs"]["steps"][:2]
    assert [step["id"] for step in selected] == ["install", "check"]
    assert selected[0]["run"].endswith("\n")
    assert selected[1]["run"] == '"$CW_PYTHON" -I -B -X utf8 "$CW_ACTION_PATH/secure.py" check'
    assert definition["inputs"]["comment-pr"]["default"] == "false"


def test_replayer_rejects_unreviewed_run_even_when_yaml_is_valid():
    raw = action_bytes().replace(b"set -euo pipefail", b"echo injected\n        set -euo pipefail")
    with pytest.raises(ValueError, match="unsupported Action YAML"):
        replay.load_action(raw)


@pytest.mark.parametrize("before,after", [
    (b"CW_REQUESTED_PYTHON: ${{ inputs.python-path }}", b"CW_REQUESTED_PYTHON: ${{ github.token }}"),
    (b"using: composite", b"using: node20"),
    (b"shell: bash", b"shell: pwsh"),
    (b"value: ${{ steps.check.outputs.exit_code }}", b"value: ${{ steps.install.outputs.exit_code }}"),
    (b"if: ${{ inputs.comment-pr == 'true' }}", b"if: ${{ always() }}"),
    (b"id: install", b"id: check"),
])
def test_structural_guard_survives_a_new_digest_without_schema_review(monkeypatch, before, after):
    raw = action_bytes().replace(before, after)
    monkeypatch.setattr(replay, "ACTION_YAML_SHA256", replay.digest(raw))
    with pytest.raises(ValueError):
        replay.load_action(raw)


def test_duplicate_yaml_fields_rejected(monkeypatch):
    raw = action_bytes().replace(b"runs:\n", b"name: shadow\nruns:\n")
    monkeypatch.setattr(replay, "ACTION_YAML_SHA256", replay.digest(raw))
    with pytest.raises(ValueError, match="duplicate YAML"):
        replay.load_action(raw)


@pytest.mark.parametrize("raw", [
    b"python=C:/python.exe\npython=C:/evil.exe\n",
    b"python<<EOF\nC:/evil.exe\nEOF\n",
    b"python=\n", b"python=C:/python.exe\ntoken=unexpected\n",
    b"python=C:/python.exe\x00\n", b"",
])
def test_output_file_rejects_injection_duplicates_missing_or_unknown_fields(raw):
    with pytest.raises(ValueError):
        replay.parse_outputs(raw, {"python"})


def test_output_file_preserves_windows_paths_and_equals():
    assert replay.parse_outputs(b"python=C:\\safe path\\python.exe\nidentity_path=C:/a=b/id.json\n",
                                {"python", "identity_path"}) == {
        "python": r"C:\safe path\python.exe", "identity_path": "C:/a=b/id.json"}


def test_environment_uses_allowlist_and_private_home(monkeypatch, tmp_path):
    system, program, private = (tmp_path / name for name in ("system", "program", "private"))
    for directory in (system / "System32", program / "Git/usr/bin", private):
        directory.mkdir(parents=True)
    monkeypatch.setenv("SystemRoot", str(system))
    monkeypatch.setenv("ProgramFiles", str(program))
    for key in ("OPENAI_API_KEY", "GH_TOKEN", "GITHUB_TOKEN", "AWS_SECRET_ACCESS_KEY", "CUSTOM_SECRET",
                "BASH_ENV", "PYTHONPATH", "PYTHONHOME", "GIT_CONFIG_COUNT", "HTTPS_PROXY", "NETRC"):
        monkeypatch.setenv(key, "must-not-survive")
    monkeypatch.setenv("PATH", "unsafe-caller-search-path")
    env = replay.clean_environment(private / "python.exe", program / "Git/cmd/git.exe", program / "Git/bin/bash.exe", private)
    assert "must-not-survive" not in env.values()
    assert "unsafe-caller-search-path" not in env["PATH"]
    assert env["HOME"] == env["USERPROFILE"] == env["APPDATA"] == str(private / "home")
    assert env["GIT_CONFIG_NOSYSTEM"] == "1"
    assert env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"


def test_checkout_snapshot_rejects_worktree_bytes_different_from_commit(tmp_path):
    raw = b"first\nsecond\n"
    oid = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    (tmp_path / "tracked.txt").write_bytes(raw.replace(b"\n", b"\r\n"))
    commit = "a" * 40

    class Reader:
        def text(self, root, *args):
            return commit if args[-1] == "HEAD" else root.as_posix()

        def read(self, root, *args):
            return b"" if args[0] == "status" else f"100644 blob {oid}\ttracked.txt\0".encode()

    with pytest.raises(ValueError, match="checkout bytes differ"):
        replay.snapshot(Reader(), tmp_path, commit)


def test_nonzero_subprocess_preserves_raw_bytes_and_is_not_promoted(monkeypatch, tmp_path):
    def spawn(argv, **kwargs):
        assert kwargs["shell"] is False and kwargs["stdin"] is subprocess.DEVNULL
        kwargs["stdout"].write(b"raw\xffoutput\n")
        kwargs["stderr"].write(b"failed\n")
        return SimpleNamespace(wait=lambda timeout: 2)

    monkeypatch.setattr(replay.subprocess, "Popen", spawn)
    ledger = []
    row = replay.run_record("check", ["trusted-python", "fixed-argument"], cwd=tmp_path, env={},
                            output=tmp_path, timeout=10, ledger=ledger)
    assert row["exit_code"] == 2 and row["timed_out"] is False
    assert (tmp_path / row["stdout"]).read_bytes() == b"raw\xffoutput\n"
    assert json.loads((tmp_path / "command-ledger.json").read_text()) == ledger


def test_timeout_kills_process_tree_and_keeps_failure(monkeypatch, tmp_path):
    calls = []

    class Child:
        pid = 12345
        waits = 0

        def wait(self, timeout):
            self.waits += 1
            if self.waits == 1:
                raise subprocess.TimeoutExpired(["bash"], timeout)
            return 0

    monkeypatch.setattr(replay.subprocess, "Popen", lambda *a, **k: Child())
    monkeypatch.setattr(replay.subprocess, "run", lambda argv, **kwargs: calls.append(argv) or SimpleNamespace(returncode=0))
    row = replay.run_record("install", ["bash"], cwd=tmp_path, env={"SystemRoot": str(tmp_path)},
                            output=tmp_path, timeout=10, ledger=[])
    assert calls[0][1:] == ["/PID", "12345", "/T", "/F"]
    assert row["exit_code"] == 124 and row["timed_out"] is True


def test_output_and_executable_cannot_be_inside_subject(tmp_path):
    with pytest.raises(ValueError, match="outside subject"):
        replay.outside(tmp_path / "new-receipt", tmp_path)
    with pytest.raises(ValueError, match="outside subject"):
        replay.outside(tmp_path, tmp_path)


def test_nested_trace_retains_binary_and_returns_original_text_semantics(monkeypatch, tmp_path):
    raw = b"before\r\nafter\rbroken\xff\n"

    def command(argv, **kwargs):
        assert not {"text", "encoding", "errors", "universal_newlines"} & kwargs.keys()
        return subprocess.CompletedProcess(argv, 1, raw, b"error\r\n")

    def helper(argv):
        result = subprocess.run(["fixed-command"], capture_output=True, text=True, encoding="utf-8", errors="replace")
        assert result.returncode == 1
        assert result.stdout == "before\nafter\nbroken\ufffd\n" and result.stderr == "error\n"
        return 0

    monkeypatch.setattr(collector.subprocess, "run", command)
    monkeypatch.setattr(collector.runpy, "run_path", lambda *a, **kw: {"main": helper})
    log = tmp_path / "nested"
    assert collector.traced_worker("qualify_assertions.py", log, []) == 0
    assert (log / "stdout.bin").read_bytes() == raw
    row = json.loads((log / "commands.json").read_text())[0]
    assert row["stdout"] == dict(path="stdout.bin", offset=0, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    assert row["exit_code"] == 1 and row["timed_out"] is False


@pytest.mark.parametrize("timeout", [False, True])
def test_nested_trace_keeps_exception_output_types_and_raw_bytes(monkeypatch, tmp_path, timeout):
    raw = b"partial\r\n\xff"

    def command(argv, **kwargs):
        if timeout:
            raise subprocess.TimeoutExpired(argv, 10, output=raw, stderr=b"err\r\n")
        raise subprocess.CalledProcessError(2, argv, output=raw, stderr=b"err\r\n")

    def helper(argv):
        subprocess.run(["fixed-command"], check=True, capture_output=True, text=True, encoding="utf-8", errors="replace")

    monkeypatch.setattr(collector.subprocess, "run", command)
    monkeypatch.setattr(collector.runpy, "run_path", lambda *a, **kw: {"main": helper})
    log = tmp_path / "nested"
    exception = subprocess.TimeoutExpired if timeout else subprocess.CalledProcessError
    with pytest.raises(exception) as caught:
        collector.traced_worker("qualify_assertions.py", log, [])
    assert caught.value.output == (raw if timeout else "partial\n\ufffd")
    assert (log / "stdout.bin").read_bytes() == raw
    row = json.loads((log / "commands.json").read_text())[0]
    assert row["timed_out"] is timeout

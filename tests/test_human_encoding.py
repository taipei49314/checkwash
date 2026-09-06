"""Real strict streams and subprocesses must preserve CLI exit semantics."""

import io
import json
import os
import subprocess
import sys
from urllib.parse import unquote

import pytest

from checkwash.cli import main
from checkwash.demo import run as run_demo
from checkwash.findings import make_fingerprint
from checkwash.report.textio import write_text


ENCODINGS = ("utf-8", "cp950", "cp1252", "ascii")
DISPLAY = {"utf-8": "發票", "cp950": r"\u767c\u7968", "cp1252": r"\u767c\u7968", "ascii": r"\u767c\u7968"}


def _stream(encoding):
    buffer = io.BytesIO()
    return io.TextIOWrapper(buffer, encoding=encoding, errors="strict", write_through=True), buffer


@pytest.mark.parametrize("encoding", ENCODINGS)
def test_human_writer_preserves_or_visibly_escapes_evidence(encoding):
    stream, buffer = _stream(encoding)
    write_text("發票 😀\n", stream)
    text = buffer.getvalue().decode(encoding)
    assert text.startswith(DISPLAY[encoding] + " ")
    assert ("😀" if encoding == "utf-8" else r"\U0001f600") in text
    assert "?" not in text
    if encoding != "utf-8":
        # A different shell decoder still preserves every character.
        assert buffer.getvalue().decode("utf-8") == text


@pytest.mark.parametrize("encoding", ENCODINGS)
def test_demo_on_real_strict_stream_finishes(encoding):
    stream, buffer = _stream(encoding)
    assert run_demo(stream) == 0
    text = buffer.getvalue().decode(encoding)
    assert "tampering cases blocked" in text
    assert "the honest fix stayed clean" in text
    assert "UNEXPECTED" not in text


@pytest.fixture(scope="module")
def repo(tmp_path_factory):
    root = tmp_path_factory.mktemp("encoding") / "project 發票"
    root.mkdir()
    def git(*args):
        subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=True)
    git("init")
    git("config", "user.name", "encoding-test")
    git("config", "user.email", "encoding@example.invalid")
    path = root / "test_發票.py"
    path.write_text("def test_發票():\n    assert amount() == 5\n", encoding="utf-8")
    git("add", ".")
    git("-c", "commit.gpgsign=false", "commit", "-m", "baseline")
    path.write_text("def test_發票():\n    assert amount() > 0\n", encoding="utf-8")
    return root


def _run(encoding, *args):
    return subprocess.run(
        [sys.executable, "-m", "checkwash", *args], capture_output=True,
        env={**os.environ, "PYTHONIOENCODING": f"{encoding}:strict", "PYTHONUTF8": "0", "NO_COLOR": "1"},
    )


@pytest.mark.parametrize("encoding", ENCODINGS)
def test_check_term_keeps_block_and_unicode_path_in_legacy_pipe(repo, encoding):
    result = _run(encoding, "check", "--repo", str(repo))
    assert result.returncode == 1, result.stderr
    text = result.stdout.decode(encoding)
    assert "ASSERT_WEAKENED" in text
    assert "test_" + DISPLAY[encoding] + ".py" in text
    assert "UnicodeEncodeError" not in result.stderr.decode(encoding)
    error = _run(encoding, "check", "--repo", str(repo / "missing 發票"))
    assert error.returncode == 2
    assert "engine error" in error.stderr.decode(encoding)
    assert DISPLAY[encoding] in error.stderr.decode(encoding)


@pytest.mark.parametrize("encoding", ENCODINGS)
@pytest.mark.parametrize("format", ("json", "sarif", "hook-json"))
def test_machine_bytes_stay_utf8_and_identical_across_encodings(repo, encoding, format):
    actual = _run(encoding, "check", "--repo", str(repo), "--format", format)
    reference = _run("utf-8", "check", "--repo", str(repo), "--format", format)
    assert actual.returncode == (0 if format == "hook-json" else 1)
    assert actual.stdout == reference.stdout
    decoded = json.loads(actual.stdout.decode("utf-8"))
    if format == "json":
        assert decoded["findings"][0]["path"] == "test_發票.py"
    elif format == "sarif":
        physical = decoded["runs"][0]["results"][0]["locations"][0]["physicalLocation"]
        assert unquote(physical["artifactLocation"]["uri"]) == "test_發票.py"
    else:
        assert decoded["decision"] == "block"
        assert "test_發票.py" in decoded["reason"]


@pytest.mark.parametrize("encoding", ENCODINGS)
def test_doctor_hook_status_and_errors_keep_their_exits(tmp_path, encoding, monkeypatch):
    root = tmp_path / "發票"
    root.mkdir()
    out, output = _stream(encoding)
    err, errors = _stream(encoding)
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)

    assert main(["hook", "install", "--agent", "claude-code", "--local", "--repo", str(root)]) == 0
    assert "installed: Stop hook configuration" in output.getvalue().decode(encoding)
    assert DISPLAY[encoding] in output.getvalue().decode(encoding)
    assert main(["doctor", "--repo", str(root)]) == 1
    assert "configured locally but not in CI" in output.getvalue().decode(encoding)
    fingerprint = make_fingerprint("ASSERT_WEAKENED", "test_發票.py", "test_發票", "assert amount() == 5")
    assert main(["allow", fingerprint, "--reason", "reviewed", "--repo", str(root)]) == 0
    assert "recorded exemption in" in output.getvalue().decode(encoding)

    settings = root / ".claude/settings.local.json"
    settings.write_bytes(b"[")
    assert main(["hook", "install", "--agent", "claude-code", "--local", "--repo", str(root)]) == 2
    assert "not valid UTF-8 JSON" in errors.getvalue().decode(encoding)
    assert DISPLAY[encoding] in errors.getvalue().decode(encoding)

    # argparse errors are also human output and can contain arbitrary input.
    with pytest.raises(SystemExit) as raised:
        main(["hook", "install", "--agent", "發票"])
    assert raised.value.code == 2
    assert "invalid choice" in errors.getvalue().decode(encoding)


@pytest.mark.parametrize("encoding", ENCODINGS)
def test_retired_unicode_key_cannot_break_machine_check_or_allow_error(tmp_path, encoding):
    def git(*args):
        subprocess.run(["git", "-C", str(tmp_path), *args], capture_output=True, check=True)

    git("init")
    git("config", "user.name", "encoding-test")
    git("config", "user.email", "encoding@example.invalid")
    directory = tmp_path / ".greenwash"
    directory.mkdir()
    key = make_fingerprint("GUARDRAIL_TOUCHED", "發票.md", None, "發票.md")
    ledger = directory / "allow.toml"
    ledger.write_text(
        '[[allow]]\nfingerprint = ' + json.dumps(key, ensure_ascii=False) + '\n'
        'rule = "GUARDRAIL_TOUCHED"\nreason = "reviewed typo"\n'
        'author = "reviewer"\ncreated = "2026-09-02"\nexpires = "2026-12-01"\n',
        encoding="utf-8",
    )
    git("add", ".greenwash/allow.toml")
    git("-c", "commit.gpgsign=false", "commit", "-m", "legacy ledger")
    original = ledger.read_bytes()
    result = _run(encoding, "check", "--repo", str(tmp_path), "--format", "json")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.decode("utf-8"))["verdict"] == "pass"
    diagnostic = result.stderr.decode(encoding)
    assert "retired" in diagnostic and DISPLAY[encoding] in diagnostic
    refused = _run(encoding, "allow", key, "--reason", "another typo", "--repo", str(tmp_path))
    assert refused.returncode == 2
    assert "retired" in refused.stderr.decode(encoding)
    assert ledger.read_bytes() == original

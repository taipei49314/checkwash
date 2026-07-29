"""End-to-end: real git repo, real subprocesses, both range and worktree modes.

Running the CLI twice in separate processes also verifies determinism under
different PYTHONHASHSEED values (each process gets a fresh random seed).
"""

import json
import os
import subprocess
import sys
import textwrap

import pytest

_ENV = {**os.environ, "GREENWASH_TODAY": "2026-01-01", "NO_COLOR": "1"}


def _git(repo, *args):
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
    )


def _greenwash(repo, *args):
    return subprocess.run(
        [sys.executable, "-m", "greenwash", *args, "--repo", str(repo)],
        capture_output=True,
        text=True,
        env=_ENV,
    )


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.name", "e2e")
    _git(tmp_path, "config", "user.email", "e2e@example.invalid")
    _git(tmp_path, "config", "commit.gpgsign", "false")
    (tmp_path / "billing.py").write_text(
        "def compute_invoice_total(items):\n    return round(sum(items), 2)\n",
        encoding="utf-8",
    )
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_billing.py").write_text(
        textwrap.dedent(
            """\
            from billing import compute_invoice_total


            def test_invoice_total():
                total = compute_invoice_total([10.5, 94.8])
                assert total == 105.3
            """
        ),
        encoding="utf-8",
    )
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "base")
    return tmp_path


def _weaken(repo):
    test_file = repo / "tests" / "test_billing.py"
    content = test_file.read_text(encoding="utf-8")
    test_file.write_text(
        content.replace("assert total == 105.3", "assert total > 0"), encoding="utf-8"
    )


def test_range_mode_blocks_weakened_assert(repo):
    _weaken(repo)
    _git(repo, "commit", "-am", "agent fix")
    result = _greenwash(repo, "check", "HEAD~1..HEAD", "--format", "json")
    assert result.returncode == 1, result.stderr
    payload = json.loads(result.stdout)
    assert payload["verdict"] == "block"
    rules = [f["rule"] for f in payload["findings"]]
    assert "ASSERT_WEAKENED" in rules
    finding = next(f for f in payload["findings"] if f["rule"] == "ASSERT_WEAKENED")
    assert finding["severity"] == "high"
    assert "NO_PROD_CHANGE_IN_DIFF" in finding["escalators"]
    assert finding["before"]["text"] == "assert total == 105.3"
    assert finding["after"]["text"] == "assert total > 0"


def test_worktree_mode_blocks_uncommitted_weakening(repo):
    _weaken(repo)
    result = _greenwash(repo, "check", "--format", "json")
    assert result.returncode == 1, result.stderr
    payload = json.loads(result.stdout)
    assert payload["verdict"] == "block"


def test_clean_range_passes(repo):
    (repo / "notes.md").write_text("release notes\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "docs")
    result = _greenwash(repo, "check", "HEAD~1..HEAD", "--format", "json")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["verdict"] == "pass"


def test_cross_process_byte_identical(repo):
    _weaken(repo)
    _git(repo, "commit", "-am", "agent fix")
    a = _greenwash(repo, "check", "HEAD~1..HEAD", "--format", "json")
    b = _greenwash(repo, "check", "HEAD~1..HEAD", "--format", "json")
    assert a.stdout == b.stdout
    assert a.stdout


def test_term_report_renders(repo):
    _weaken(repo)
    result = _greenwash(repo, "check")
    assert result.returncode == 1
    assert "ASSERT_WEAKENED" in result.stdout
    assert "greenwash allow" in result.stdout


def test_allow_roundtrip(repo):
    _weaken(repo)
    first = _greenwash(repo, "check", "--format", "json")
    fingerprint = json.loads(first.stdout)["findings"][0]["fingerprint"]

    allow = _greenwash(repo, "allow", fingerprint, "--reason", "reviewed: issue 482")
    assert allow.returncode == 0, allow.stderr
    # Only the exemption goes through review/commit; the weakened test stays
    # in the worktree. Exemptions are honoured from the BASE side (SPEC §6).
    _git(repo, "add", ".greenwash")
    _git(repo, "commit", "-m", "record exemption")

    result = _greenwash(repo, "check", "--format", "json")
    assert result.returncode == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["verdict"] == "pass"
    assert any(f["allowlisted"] for f in payload["findings"])


def test_engine_error_exit_code(tmp_path):
    result = _greenwash(tmp_path, "check", "HEAD~1..HEAD", "--format", "json")
    assert result.returncode == 2

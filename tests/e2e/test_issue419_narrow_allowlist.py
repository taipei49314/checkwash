"""D-176 keeps the CLI's base-side allowance trust boundary and E2 order."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


BEFORE = b"def test_oracle():\n    value = 2\n    assert value == 2\n"
AFTER = (
    b"def test_oracle():\n    value = 2\n"
    b"    try:\n        assert value == 2\n"
    b"    except Exception:\n        pass\n"
)
TEMPLATE_BEFORE = b"<!-- status -->\n<p>{{ value }}</p>\n"
TEMPLATE_AFTER = b"<!-- revised status -->\n<p>{{ value }}</p>\n"
TEST = "tests/test_sample.py"
TEMPLATE = "app/templates/status.html"
LEDGER = ".greenwash/allow.toml"


def _git(repo, *args):
    result = subprocess.run(
        ["git", "-c", f"core.hooksPath={repo / '.git' / 'no-hooks'}",
         "-C", str(repo), *args],
        capture_output=True, check=True, timeout=30,
    )
    return result.stdout.decode("utf-8").strip()


def _write(repo, path, data):
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def _commit(repo, *paths):
    _git(repo, "add", "--", *paths)
    _git(repo, "commit", "-m", "scenario step")
    return _git(repo, "rev-parse", "HEAD")


def _check(repo, revision=None):
    result = subprocess.run(
        [sys.executable, "-m", "checkwash", "check",
         *([revision] if revision else []), "--repo", str(repo),
         "--task", str(repo / "TASK.md"), "--format", "json"],
        capture_output=True, timeout=120,
        env={**os.environ,
             "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src"),
             "GREENWASH_TODAY": "2026-10-23", "PYTHONUTF8": "1", "NO_COLOR": "1"},
    )
    assert result.returncode in (0, 1), result.stderr.decode("utf-8")
    payload = json.loads(result.stdout)
    assert payload["config_errors"] == []
    hit, = [finding for finding in payload["findings"]
            if finding["rule"] == "BROAD_EXCEPT_ADDED"]
    return result.returncode, payload, hit


@pytest.mark.parametrize("oracle_freeze", [False, True])
def test_head_only_allowance_is_rejected_and_base_allowance_precedes_e2(tmp_path, oracle_freeze):
    repo = tmp_path
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "checkwash-test")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "commit.gpgsign", "false")
    _git(repo, "config", "core.autocrlf", "false")
    task = ("---\ncheckwash:\n  oracle_freeze: "
            + str(oracle_freeze).lower() + "\n---\n").encode()
    _write(repo, "TASK.md", task)
    _write(repo, LEDGER, b"# reviewed base ledger\n")
    _write(repo, TEST, BEFORE)
    _write(repo, TEMPLATE, TEMPLATE_BEFORE)
    base_without_allowance = _commit(repo, "TASK.md", LEDGER, TEST, TEMPLATE)

    _write(repo, TEST, AFTER)
    _write(repo, TEMPLATE, TEMPLATE_AFTER)
    exit_code, payload, original = _check(repo)
    expected_reasons = ["OPAQUE_PROD_CHANGE_NOT_EVIDENCE"]
    if oracle_freeze:
        expected_reasons.append("ORACLE_FREEZE")
    assert exit_code == 1 and payload["verdict"] == "block"
    assert original["severity"] == "high" and not original["allowlisted"]
    assert original["escalators"] == expected_reasons

    entry = (
        "# reviewed base ledger\n\n[[allow]]\n"
        f"fingerprint = {json.dumps(original['fingerprint'])}\n"
        'rule = "BROAD_EXCEPT_ADDED"\nreason = "Owned boundary test"\n'
        'author = "synthetic-test"\ncreated = "2026-10-23"\nexpires = "2026-10-30"\n'
    ).encode()
    _write(repo, LEDGER, entry)
    exit_code, payload, untrusted = _check(repo)
    assert exit_code == 1 and payload["verdict"] == "block"
    assert untrusted["fingerprint"] == original["fingerprint"]
    assert not untrusted["allowlisted"]
    assert untrusted["severity"] == "high"
    assert untrusted["escalators"] == expected_reasons

    # Commit only the reviewed ledger. Test/template edits remain worktree
    # changes, so exactly the same broad finding now sees an active BASE entry.
    base_with_allowance = _commit(repo, LEDGER)
    exit_code, payload, trusted = _check(repo)
    assert exit_code == 0 and payload["verdict"] == "pass"
    assert trusted["fingerprint"] == original["fingerprint"]
    assert trusted["allowlisted"] is True
    assert trusted["escalators"] == []
    assert trusted["deescalators"] == ["ALLOWLISTED"]

    head = _commit(repo, TEST, TEMPLATE)
    exit_code, payload, trusted_range = _check(repo, f"{base_with_allowance}..{head}")
    assert exit_code == 0 and payload["verdict"] == "pass"
    assert trusted_range["allowlisted"] is True
    assert trusted_range["escalators"] == []

    # The same head against the earlier base must not import its ledger.
    exit_code, payload, untrusted_range = _check(repo, f"{base_without_allowance}..{head}")
    assert exit_code == 1 and payload["verdict"] == "block"
    assert untrusted_range["fingerprint"] == original["fingerprint"]
    assert not untrusted_range["allowlisted"]
    assert untrusted_range["severity"] == "high"
    assert untrusted_range["escalators"] == expected_reasons

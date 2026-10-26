"""A synthetic commit must retain range-check pytest-config evidence in sweep.

Git-tree mode 120000 entries need no host symlink support. Fixture code is
only read by CheckWash; these tests never run the repository's test program.
"""

from collections import Counter
import datetime
import json
import subprocess

import pytest

from checkwash.cli import main
from checkwash.sweep import sweep


def _git(repo, *args, data=None):
    process = subprocess.run(
        ["git", "-C", str(repo), *args], input=data, capture_output=True, timeout=30,
    )
    assert process.returncode == 0, process.stderr.decode("utf-8", errors="replace")
    return process.stdout.decode("ascii").strip()


def _commit(repo, files, parent=None):
    _git(repo, "read-tree", "--empty")
    for path, (mode, data) in sorted(files.items()):
        oid = _git(repo, "hash-object", "-w", "--stdin", data=data)
        _git(repo, "update-index", "--add", "--cacheinfo", f"{mode},{oid},{path}")
    tree = _git(repo, "write-tree")
    revision = _git(
        repo, "commit-tree", tree, *(["-p", parent] if parent else []),
        data=b"synthetic sweep input parity\n",
    )
    _git(repo, "update-ref", "refs/heads/main", revision)
    return revision


@pytest.mark.parametrize("linked", [False, True], ids=["regular", "git-symlink"])
@pytest.mark.parametrize("weakening", [False, True], ids=["comment-only", "deselect"])
def test_single_commit_sweep_keeps_range_pytest_config_evidence(tmp_path, capfd, linked, weakening):
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.name", "synthetic parity")
    _git(tmp_path, "config", "user.email", "parity@example.invalid")
    _git(tmp_path, "config", "commit.gpgsign", "false")
    _git(tmp_path, "config", "core.autocrlf", "false")
    config_path = "config/pytest-settings.ini" if linked else "pytest.ini"
    config = b"[pytest]\ntestpaths = tests\n"
    before = {
        "calc.py": ("100644", b"def calc(x):\n    return x * 2\n"),
        "tests/test_calc.py": ("100644", b"from calc import calc\n\ndef test_calc():\n    assert calc(1) == 2\n"),
        config_path: ("100644", config),
    }
    if linked:
        before["pytest.ini"] = ("120000", config_path.encode("ascii"))
    after = dict(before)
    after[config_path] = (
        "100644",
        config + (b"addopts = --deselect tests/test_calc.py::test_calc\n"
                  if weakening else b"# comment-only edit\n"),
    )
    base = _commit(tmp_path, before)
    head = _commit(tmp_path, after, base)

    code = main(["check", f"{base}..{head}", "--repo", str(tmp_path), "--format", "json"])
    captured = capfd.readouterr()
    checked = json.loads(captured.out)
    assert code == int(weakening), captured.err
    assert checked["config_errors"] == []
    assert checked["skipped_files"] == []
    assert checked["verdict"] == ("block" if weakening else "pass")
    if weakening:
        assert any(f["rule"] == "CI_WORKFLOW_TOUCHED" and f["severity"] == "high"
                   and f["path"] == config_path for f in checked["findings"])

    result = sweep(str(tmp_path), head, 1, datetime.date(2026, 10, 26))
    swept = json.loads(result.to_json())
    assert (result.commits, result.errors, result.skipped) == (1, 0, 0)
    assert result.blocked == int(weakening)
    visible = [finding for finding in checked["findings"] if not finding["allowlisted"]]
    counts = Counter((finding["rule"], finding["severity"]) for finding in visible)
    expected_counts = {}
    for (rule, severity), count in counts.items():
        expected_counts.setdefault(rule, {})[severity] = count
    assert swept["findings_by_rule"] == expected_counts
    fields = ("rule", "severity", "path", "unit", "message")
    expected_blockers = [{field: finding[field] for field in fields}
                         for finding in visible if finding["severity"] in ("high", "critical")]
    assert swept["blocked_commits"] == ([{"commit": head, "findings": expected_blockers}]
                                         if weakening else [])

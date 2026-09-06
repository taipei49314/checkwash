"""Restoring a numeric exact oracle is not an unchanged-strength rewrite."""

import datetime
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze


def _analyze(before, after):
    def source(assertion):
        return ("from calc import add, subtract\n\ndef test_add():\n    " + assertion + "\n").encode()

    return analyze(
        [FileChange(path="tests/test_calc.py", before=source(before), after=source(after), status="modified")],
        Config(), Contract(), [], datetime.date(2026, 1, 1),
    )


@pytest.mark.parametrize("before,after", [
    ("assert add(2, 3) > 0", "assert add(2, 3) == 5"),
    ("assert add(2, 3) < 10", "assert add(2, 3) == 5"),
    ("assert add(2, 3) >= 0", "assert add(2, 3) == 5"),
    ("assert add(2, 3) <= 10", "assert add(2, 3) == 5"),
    ("assert 0 < add(2, 3)", "assert 5 == add(2, 3)"),
    ("assert 10 > add(2, 3)", "assert 5 == add(2, 3)"),
    ("assert 0 <= add(2, 3)", "assert 5 == add(2, 3)"),
    ("assert 10 >= add(2, 3)", "assert 5 == add(2, 3)"),
    ("assert add(2, 3) > -1.5", "assert add( 2, 3 ) == 5.0"),
])
def test_numeric_exact_implies_old_bound(before, after):
    _ir, findings, verdict = _analyze(before, after)
    assert findings == []
    assert verdict == "pass"


@pytest.mark.parametrize("before,after,rule", [
    ("assert add(2, 3) == 5", "assert add(2, 3) > 0", "ASSERT_WEAKENED"),
    ("assert add(2, 3) == 5", "assert add(2, 3) == 4", "EXPECTED_VALUE_CHANGED"),
    ("assert add(2, 3) > 0", "assert add(2, 3) == -1", "EXPECTED_VALUE_CHANGED"),
    ("assert add(2, 3) < 0", "assert add(2, 3) == 5", "EXPECTED_VALUE_CHANGED"),
    ("assert add(2, 3) > 0", "assert subtract(2, 3) == 5", "EXPECTED_VALUE_CHANGED"),
    ("assert add(2, 3) > 0", "assert add(2, 3) != 5", "EXPECTED_VALUE_CHANGED"),
    ("assert 0 < add(2, 3) < 10", "assert add(2, 3) == 50", "EXPECTED_VALUE_CHANGED"),
    ("assert add(2, 3) > 0", "assert add(2, 3) == True", "EXPECTED_VALUE_CHANGED"),
    ("assert add(2, 3) < 1e999", "assert add(2, 3) == 5", "EXPECTED_VALUE_CHANGED"),
    ("assert add(2, 3) < 10", "assert add(2, 3) == 1j", "EXPECTED_VALUE_CHANGED"),
])
def test_other_rewrites_do_not_buy_numeric_strengthening(before, after, rule):
    _ir, findings, verdict = _analyze(before, after)
    assert verdict == "block"
    assert any(f.rule == rule and f.severity == "high" for f in findings)


def test_changed_subject_binding_does_not_buy_numeric_strengthening():
    _ir, findings, verdict = _analyze(
        "result = add(2, 3)\n    assert result > 0",
        "result = subtract(2, 3)\n    assert result == 5",
    )
    assert verdict == "block"
    assert any(f.rule == "EXPECTED_VALUE_CHANGED" for f in findings)


@pytest.mark.parametrize("old,new,exit_code", [
    ("> 0", "== 5", 0),
    ("< 10", "== 5", 0),
    ("> 0", "== -1", 1),
    ("== 5", "> 0", 1),
    ("== 5", "== 4", 1),
])
def test_strengthening_worktree_and_committed_range(tmp_path, old, new, exit_code):
    def git(*args):
        subprocess.run(["git", "-C", str(tmp_path), *args], capture_output=True, check=True)

    git("init", "-b", "main")
    git("config", "user.name", "e2e")
    git("config", "user.email", "e2e@example.invalid")
    git("config", "commit.gpgsign", "false")
    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    test_file = tests / "test_calc.py"
    before = f"from calc import add\n\ndef test_add():\n    assert add(2, 3) {old}\n"
    test_file.write_text(before, encoding="utf-8")
    git("add", "-A")
    git("commit", "-m", "base")
    test_file.write_text(before.replace(old, new), encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}

    def check(*range_args):
        result = subprocess.run(
            [sys.executable, "-m", "checkwash", "check", *range_args, "--repo", str(tmp_path), "--format", "json"],
            capture_output=True, env=env,
        )
        assert result.returncode == exit_code, result.stderr.decode("utf-8")
        return json.loads(result.stdout)["findings"]

    worktree_findings = check()
    git("commit", "-am", "change oracle")
    assert check("HEAD~1..HEAD") == worktree_findings

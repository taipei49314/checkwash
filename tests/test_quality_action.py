"""Run the action wrapper in isolated processes against trusted Git fixtures."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

WRAPPER = Path(__file__).resolve().parents[1] / "action/quality/run.py"


@pytest.mark.parametrize("case,expected,analysis", [
    ("unchanged", 0, 0), ("report-loss", 0, 0), ("enforce-loss", 1, 1),
    ("enforce-incomplete", 2, 2), ("report-incomplete", 0, 0),
    ("require-enforce", 2, 0), ("missing-policy", 2, 0),
    ("bad-source", 2, 2), ("missing-ref", 2, 2),
    ("named-ref", 2, "unavailable"), ("outside-repo", 2, "unavailable"),
    ("nested-directory", 2, "unavailable"), ("invalid-boolean", 2, "unavailable"),
])
def test_action_preserves_review_results_and_rejects_bad_integration(tmp_path, case, expected, analysis):
    workspace = tmp_path / "workspace"
    repo = workspace / "subject"
    repo.mkdir(parents=True)
    runner = tmp_path / "runner"
    runner.mkdir()
    marker = tmp_path / "SUBJECT_EXECUTED"
    hostile = "from pathlib import Path\nPath(" + repr(str(marker)) + ").write_text('executed')\n"
    (repo / "sitecustomize.py").write_text(hostile, encoding="utf-8")
    (repo / "checkwash").mkdir()
    (repo / "checkwash/__init__.py").write_text(hostile, encoding="utf-8")
    (repo / "checkwash/__main__.py").write_text(hostile, encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src/code.py").write_text("x = 1\n", encoding="utf-8")
    mode = "report" if case.startswith("report-") or case == "require-enforce" else "enforce"
    (repo / ".checkwash").mkdir()
    if case != "missing-policy":
        (repo / ".checkwash/quality.toml").write_text(
            'schema_version=1\nmode="' + mode + '"\n[[targets]]\nid="coverage"\ntool="coverage"\n'
            'root="."\nconfig="pyproject.toml"\nprofile="coverage-7.16.0-q1"\npaths=["src/"]\n', encoding="utf-8")
    config = '[tool.coverage.report]\nfail_under=85\n'
    (repo / "pyproject.toml").write_text(config, encoding="utf-8")
    def git(*args):
        result = subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
        return result.stdout.decode().strip()
    git("init")
    git("config", "user.name", "action-fixture")
    git("config", "user.email", "fixture@example.invalid")
    git("add", ".")
    git("commit", "-m", "trusted base")
    base = git("rev-parse", "HEAD")
    after = config if case == "unchanged" else config.replace("85", "50")
    if case.endswith("incomplete"):
        after += "exclude_also=['.*']\n"
    if case == "bad-source":
        after = "[invalid"
    (repo / "pyproject.toml").write_text(after, encoding="utf-8")
    git("add", ".")
    git("commit", "--allow-empty", "-m", "trusted head")
    head = git("rev-parse", "HEAD")
    env = {**os.environ, "GITHUB_WORKSPACE": str(workspace), "RUNNER_TEMP": str(runner),
           "GITHUB_OUTPUT": str(tmp_path / "output"), "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
           "CW_QUALITY_BASE": base, "CW_QUALITY_HEAD": head, "CW_QUALITY_REPOSITORY": "subject",
           "CW_QUALITY_REQUIRE_ENFORCE": "true" if case in {"require-enforce", "missing-policy"} else "false",
           "PYTHONPATH": str(repo), "CHECKWASH_TODAY": "2026-09-09"}
    if case == "missing-ref":
        env["CW_QUALITY_HEAD"] = "f" * 40
    elif case == "named-ref":
        env["CW_QUALITY_BASE"] = "HEAD~1"
    elif case == "outside-repo":
        env["CW_QUALITY_REPOSITORY"] = ".."
    elif case == "nested-directory":
        env["CW_QUALITY_REPOSITORY"] = "subject/src"
    elif case == "invalid-boolean":
        env["CW_QUALITY_REQUIRE_ENFORCE"] = "yes"
    proc = subprocess.run([sys.executable, "-I", str(WRAPPER)], env=env, cwd=repo, capture_output=True, timeout=150)
    assert proc.returncode == expected, (proc.stdout, proc.stderr)
    output = dict(line.split("=", 1) for line in Path(env["GITHUB_OUTPUT"]).read_text(encoding="utf-8").splitlines())
    receipt = json.loads(Path(output["receipt_path"]).read_text(encoding="utf-8"))
    assert receipt["exit_code"] == expected and receipt["analysis_exit_code"] == analysis
    assert output["exit_code"] == str(expected) and output["analysis_exit_code"] == str(analysis)
    assert not marker.exists(), "Subject Python must never run, even through PYTHONPATH or sitecustomize"
    if analysis != "unavailable":
        report = json.loads(Path(output["report_path"]).read_text(encoding="utf-8"))
        assert report["analysis_status"] == output["analysis_status"]
        assert report["verdict"] == output["verdict"]
        if case in {"require-enforce", "missing-policy"}:
            assert receipt["integration_error"].startswith("BASE_MODE_NOT_ENFORCE")
            assert report["run"]["mode"] == "report"
    else:
        assert receipt["integration_error"] and output["report_path"] == ""

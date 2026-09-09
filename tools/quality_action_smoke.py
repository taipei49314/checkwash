"""Trusted hosted fixture for actual report-mode adoption through the composite action."""
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    workspace = Path(os.environ["GITHUB_WORKSPACE"])
    if sys.argv[1] == "prepare":
        repo = workspace / ".quality-action-fixture"
        repo.mkdir()  # Never replace an existing path.
        (repo / "src").mkdir()
        (repo / "src/code.py").write_text("x = 1\n", encoding="utf-8")
        (repo / ".checkwash").mkdir()
        (repo / ".checkwash/quality.toml").write_text(
            'schema_version=1\nmode="report"\n[[targets]]\nid="coverage"\ntool="coverage"\n'
            'root="."\nconfig="pyproject.toml"\nprofile="coverage-7.16.0-q1"\npaths=["src/"]\n', encoding="utf-8")
        def git(*args):
            return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True).stdout.decode().strip()
        git("init")
        git("config", "user.name", "quality-action-smoke")
        git("config", "user.email", "fixture@example.invalid")
        revisions = []
        for threshold in (85, 50):
            (repo / "pyproject.toml").write_text(f"[tool.coverage.report]\nfail_under={threshold}\n", encoding="utf-8")
            git("add", ".")
            git("commit", "-m", "trusted coverage fixture " + str(threshold))
            revisions.append(git("rev-parse", "HEAD"))
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
            stream.write("base=" + revisions[0] + "\nhead=" + revisions[1] + "\n")
    elif sys.argv[1] == "verify":
        assert os.environ["SMOKE_OUTCOME"] == "success"
        assert os.environ["SMOKE_EXIT"] == os.environ["SMOKE_ANALYSIS_EXIT"] == "0"
        report = json.loads(Path(os.environ["SMOKE_REPORT"]).read_text(encoding="utf-8"))
        receipt = json.loads(Path(os.environ["SMOKE_RECEIPT"]).read_text(encoding="utf-8"))
        assert report["verdict"] == "reported" and report["analysis_status"] == "complete"
        assert report["summary"]["high"] == 1
        assert receipt["integration_error"] is None and receipt["mode"] == "report"
        assert any(f["rule"] == "QW_THRESHOLD_LOWERED" for f in report["findings"])
        print("Actual composite action preserved report exit 0 and the visible high-severity finding")
    else:
        raise ValueError("Expected prepare or verify")


if __name__ == "__main__":
    main()

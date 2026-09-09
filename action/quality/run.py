"""Trusted action wrapper. Never import Python from the subject checkout."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

SHA = re.compile(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})\Z")
STATUSES = {"complete", "partial", "unsupported", "error"}
VERDICTS = {"no_blocking_finding", "reported", "block", "incomplete", "error"}


def review(env, output):
    receipt = {"checkwash_quality_action_version": 1, "exit_code": 2,
               "analysis_exit_code": "unavailable", "analysis_status": "error", "verdict": "error",
               "report_path": "", "integration_error": None,
               "ci_execution_verified": False, "branch_protection_verified": False}
    try:
        if not sys.flags.isolated:
            raise ValueError("Wrapper requires Python isolated mode (-I)")
        base, head = env.get("CW_QUALITY_BASE", ""), env.get("CW_QUALITY_HEAD", "")
        if not SHA.fullmatch(base) or not SHA.fullmatch(head):
            raise ValueError("base and head must be full commit SHAs; fetch both commits first")
        required = env.get("CW_QUALITY_REQUIRE_ENFORCE", "false")
        if required not in {"true", "false"}:
            raise ValueError("require-enforce must be true or false")
        workspace = Path(env["GITHUB_WORKSPACE"]).resolve(strict=True)
        repo = (workspace / env.get("CW_QUALITY_REPOSITORY", ".")).resolve(strict=True)
        if not repo.is_relative_to(workspace) or not repo.is_dir():
            raise ValueError("repository must be a directory within GITHUB_WORKSPACE")
        root = subprocess.run(["git", "-C", str(repo), "rev-parse", "--show-toplevel"],
                              capture_output=True, check=True, timeout=30)
        if Path(root.stdout.decode("utf-8").strip()).resolve() != repo:
            raise ValueError("repository must name the Git repository root")
        proc = subprocess.run([sys.executable, "-I", "-m", "checkwash", "quality", base + "..." + head,
                               "--repo", str(repo), "--format", "json"],
                              cwd=output, env=env, capture_output=True, timeout=120)
        payload = json.loads(proc.stdout)
        if (proc.returncode not in {0, 1, 2} or payload.get("checkwash_quality_version") != 1
                or payload.get("analysis_status") not in STATUSES or payload.get("verdict") not in VERDICTS
                or payload.get("run", {}).get("mode") not in {"report", "enforce"}):
            raise ValueError("quality returned an invalid report contract")
        report = output / "quality.json"
        report.write_bytes(proc.stdout)
        receipt.update(exit_code=proc.returncode, analysis_exit_code=proc.returncode,
                       analysis_status=payload["analysis_status"], verdict=payload["verdict"],
                       mode=payload["run"]["mode"], report_path=str(report))
        if required == "true" and receipt["mode"] != "enforce":
            receipt.update(exit_code=2, integration_error="BASE_MODE_NOT_ENFORCE: commit a reviewed enforce policy in the base before requiring enforcement")
    except ValueError as exc:
        # These are wrapper-owned messages; never echo the subprocess stream.
        receipt["integration_error"] = str(exc) if not isinstance(exc, json.JSONDecodeError) else "Invalid quality JSON"
    except Exception as exc:
        receipt["integration_error"] = "Quality integration failed: " + type(exc).__name__
    return receipt


def main():
    env = dict(os.environ)
    output = Path(tempfile.mkdtemp(prefix="checkwash-quality-report-", dir=env["RUNNER_TEMP"]))
    receipt = review(env, output)
    receipt["receipt_path"] = str(output / "action-receipt.json")
    Path(receipt["receipt_path"]).write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    keys = ("exit_code", "analysis_exit_code", "analysis_status", "verdict", "report_path", "receipt_path")
    with open(env["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
        for key in keys:
            value = str(receipt[key])
            if any(c in value for c in "\r\n"):
                raise ValueError("Invalid output path")
            stream.write(key + "=" + value + "\n")
    summary = ["### Checkwash quality", "", "| Field | Value |", "| --- | --- |"]
    for key in ("exit_code", "analysis_exit_code", "analysis_status", "verdict", "mode"):
        summary.append(f"| {key} | {receipt.get(key, 'unavailable')} |")
    summary += ["", "Review the JSON report for findings, sources and unsupported dimensions.",
                "Report exit 0 is observation only. Tool execution and required branch status are not verified."]
    if receipt["integration_error"]:
        summary.append("Integration needs attention; inspect action-receipt.json for the reason.")
    with open(env["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as stream:
        stream.write("\n".join(summary) + "\n")
    print("Checkwash quality action exit", receipt["exit_code"], "| analysis", receipt["analysis_status"], "| verdict", receipt["verdict"])
    return receipt["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())

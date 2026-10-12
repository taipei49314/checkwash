"""Trusted quality wrapper; preserve the engine's original report and exits."""
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

SHA = re.compile(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})\Z")
STATUSES = {"complete", "partial", "unsupported", "error"}
VERDICTS = {"no_blocking_finding", "reported", "block", "incomplete", "error"}
OUTPUT_KEYS = ("exit_code", "analysis_exit_code", "analysis_status", "verdict", "report_path", "receipt_path")


def shared_security():
    path = Path(__file__).resolve().parents[1] / "secure.py"
    spec = importlib.util.spec_from_file_location("checkwash_quality_security", path)
    if spec is None or spec.loader is None:
        raise ValueError("Trusted Action security module is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


secure = shared_security()


def new_receipt():
    return {"checkwash_quality_action_version": 1, "exit_code": 2,
            "analysis_exit_code": "unavailable", "analysis_status": "error", "verdict": "error",
            "report_path": "", "integration_error": None,
            "ci_execution_verified": False, "branch_protection_verified": False}


def integration_failure(receipt, exc):
    receipt["exit_code"] = 2
    receipt["integration_error"] = "Quality integration failed: " + type(exc).__name__


def review(env, output):
    receipt = new_receipt()
    try:
        directory = secure.runtime_directory(env)
        receipt["identity"] = secure.identity()
        clean = secure.child_environment(env, directory)
        base, head = env.get("CW_QUALITY_BASE", ""), env.get("CW_QUALITY_HEAD", "")
        if not SHA.fullmatch(base) or not SHA.fullmatch(head):
            raise ValueError("base and head must be full commit SHAs; fetch both commits first")
        receipt.update(requested_base=base, requested_head=head)
        required = env.get("CW_QUALITY_REQUIRE_ENFORCE", "false")
        if required not in {"true", "false"}:
            raise ValueError("require-enforce must be true or false")
        workspace = secure.path_value(env["GITHUB_WORKSPACE"])
        repo = (workspace / env.get("CW_QUALITY_REPOSITORY", ".")).resolve(strict=True)
        if not repo.is_relative_to(workspace) or not repo.is_dir():
            raise ValueError("repository must be a directory within GITHUB_WORKSPACE")
        git = shutil.which("git", path=clean["PATH"])
        if not git:
            raise ValueError("trusted runner Git is unavailable")
        root = subprocess.run([git, "-C", str(repo), "rev-parse", "--show-toplevel"],
                              cwd=output, env=clean, capture_output=True, check=True, timeout=30)
        if Path(root.stdout.decode("utf-8").strip()).resolve() != repo:
            raise ValueError("repository must name the Git repository root")
        # Let quality itself resolve the range. Missing refs retain its genuine
        # error report (including its unresolved HEAD/worktree/default mode).
        proc = subprocess.run([sys.executable, "-I", "-B", "-X", "utf8", "-m", "checkwash", "quality",
                               base + "..." + head, "--repo", str(repo), "--format", "json"],
                              cwd=output, env=clean, capture_output=True, timeout=120)
        receipt["subprocess_exit_code"] = proc.returncode
        stream_errors = []
        for name, data in (("stdout.txt", proc.stdout), ("stderr.txt", proc.stderr)):
            try:
                (output / name).write_bytes(data)
            except OSError as exc:
                stream_errors.append(name + ": " + type(exc).__name__)
        if stream_errors:
            receipt["stream_write_errors"] = stream_errors
        payload = json.loads(proc.stdout)
        if (proc.returncode not in {0, 1, 2} or payload.get("checkwash_quality_version") != 1
                or payload.get("analysis_status") not in STATUSES or payload.get("verdict") not in VERDICTS
                or payload.get("run", {}).get("mode") not in {"report", "enforce"}):
            raise ValueError("quality returned an invalid report contract")
        receipt.update(exit_code=proc.returncode, analysis_exit_code=proc.returncode,
                       analysis_status=payload["analysis_status"], verdict=payload["verdict"],
                       mode=payload["run"]["mode"])
        report = output / "quality.json"
        report.write_bytes(proc.stdout)
        receipt["report_path"] = str(report)
        if stream_errors:
            raise OSError("Cannot preserve quality subprocess streams")
        if required == "true" and receipt["mode"] != "enforce":
            receipt.update(exit_code=2, integration_error="BASE_MODE_NOT_ENFORCE: commit a reviewed enforce policy in the base before requiring enforcement")
    except subprocess.TimeoutExpired as exc:
        for name, data in (("stdout.txt", exc.stdout), ("stderr.txt", exc.stderr)):
            if data is not None:
                try:
                    (output / name).write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
                except OSError:
                    pass  # Still a timeout/integration failure, never a verdict.
        integration_failure(receipt, exc)
    except ValueError as exc:
        receipt["exit_code"] = 2
        # Wrapper/identity-owned messages only; never echo subprocess bytes.
        receipt["integration_error"] = str(exc) if not isinstance(exc, json.JSONDecodeError) else "Invalid quality JSON"
    except Exception as exc:
        integration_failure(receipt, exc)
    return receipt


def summary_text(receipt):
    summary = ["### Checkwash quality", "", "| Field | Value |", "| --- | --- |"]
    for key in ("exit_code", "analysis_exit_code", "analysis_status", "verdict", "mode"):
        summary.append(f"| {key} | {receipt.get(key, 'unavailable')} |")
    summary += ["", "Review the JSON report for findings, sources and unsupported dimensions.",
                "Report exit 0 is observation only. Tool execution and required branch status are not verified."]
    if receipt["integration_error"]:
        summary.append("Integration needs attention; inspect action-receipt.json for the reason.")
    return "\n".join(summary) + "\n"


def finalize(env, output, receipt):
    receipt["receipt_path"] = str(output / "action-receipt.json")
    try:
        with open(env["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8", newline="\n") as stream:
            stream.write(summary_text(receipt))
    except (OSError, KeyError, ValueError) as exc:
        integration_failure(receipt, exc)
    try:
        secure.save_json(Path(receipt["receipt_path"]), receipt)
    except (OSError, ValueError) as exc:
        integration_failure(receipt, exc)
        print("Checkwash quality receipt could not be saved; no outputs exported:", type(exc).__name__, file=sys.stderr)
        return 2
    try:
        secure.output_values(env["GITHUB_OUTPUT"], {key: receipt[key] for key in OUTPUT_KEYS})
    except (OSError, KeyError, ValueError) as exc:
        integration_failure(receipt, exc)
        # Value validation precedes writes; OS partial writes cannot be undone.
        # The native failure and revised receipt are authoritative.
        try:
            secure.save_json(Path(receipt["receipt_path"]), receipt)
        except (OSError, ValueError):
            print("Checkwash quality error receipt could not be saved", file=sys.stderr)
        print("Checkwash quality outputs could not be exported:", type(exc).__name__, file=sys.stderr)
        return 2
    return receipt["exit_code"]


def main():
    env = dict(os.environ)
    try:
        # Establish safe evidence storage before inspecting the supplied runtime.
        # Runtime mismatch/tampering can then receive a failure receipt without
        # writing into that untrusted directory.
        output = secure.private_directory(env) / "quality-report"
        output.mkdir()
    except (OSError, KeyError, ValueError) as exc:
        print("Checkwash quality has no safe report directory; no outputs exported:", type(exc).__name__, file=sys.stderr)
        return 2
    return finalize(env, output, review(env, output))


if __name__ == "__main__":
    raise SystemExit(main())

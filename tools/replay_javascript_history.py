"""Replay a preselected public JS/TS history sample through two isolated CLIs.

Run on the authorized remote qualification host. The script downloads source
as data and never executes the JavaScript/TypeScript, its package manager, or
its test runner. Only Git, Python packaging and the two CheckWash CLIs execute.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile
import tomllib
import urllib.request


BASELINE_SHA = "ea726c9cbd172b838bcf42b2c9969759e4ca358e"
BASELINE_VERSION = "0.4.1"
LABELS = {"preserving", "unknown", "mixed_case_change", "explicit_test_removal"}
MAX_SOURCE_BYTES = 2_000_000


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def environment() -> dict[str, str]:
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("PYTHON", "GIT_", "CHECKWASH_", "GREENWASH_"))}
    env.update({
        "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0", "GIT_AUTHOR_NAME": "historical sample replay",
        "GIT_AUTHOR_EMAIL": "replay@example.invalid", "GIT_COMMITTER_NAME": "historical sample replay",
        "GIT_COMMITTER_EMAIL": "replay@example.invalid", "GIT_AUTHOR_DATE": "2026-09-23T00:00:00Z",
        "GIT_COMMITTER_DATE": "2026-09-23T00:00:00Z", "GREENWASH_TODAY": "2026-09-23",
        "PYTHONUTF8": "1", "NO_COLOR": "1",
    })
    return env


def command(args: list[str], cwd: Path, log: Path, *, timeout: int = 180) -> subprocess.CompletedProcess:
    log.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = subprocess.run(args, cwd=cwd, env=environment(), capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        log.with_suffix(".stdout").write_bytes(error.stdout or b"")
        log.with_suffix(".stderr").write_bytes(error.stderr or b"")
        write_json(log.with_suffix(".command.json"), {"command": args, "cwd": str(cwd), "exit": None, "timeout_seconds": timeout})
        raise RuntimeError("command timed out: " + str(log)) from error
    log.with_suffix(".stdout").write_bytes(result.stdout)
    log.with_suffix(".stderr").write_bytes(result.stderr)
    write_json(log.with_suffix(".command.json"), {"command": args, "cwd": str(cwd), "exit": result.returncode})
    return result


def checked(args: list[str], cwd: Path, log: Path, *, timeout: int = 180) -> bytes:
    result = command(args, cwd, log, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"command exited {result.returncode}: {log}")
    return result.stdout


def git(repo: Path, log: Path, *args: str) -> str:
    return checked([
        "git", "-c", "core.autocrlf=false", "-c", "commit.gpgsign=false",
        "-c", "core.hooksPath=" + os.devnull, *args,
    ], repo, log).decode("utf-8", "replace").strip()


def package_files(package: Path) -> dict[str, str]:
    return {path.relative_to(package).as_posix(): sha256(path.read_bytes())
            for path in sorted(package.rglob("*"))
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"}


def package_digest(files: dict[str, str]) -> str:
    return sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode())


def verify_install(python: Path, source: Path, logs: Path) -> dict:
    probe = checked([str(python), "-I", "-B", "-c", (
        "import json,sys,checkwash; print(json.dumps({'package':checkwash.__file__,"
        "'version':checkwash.__version__,'prefix':sys.prefix,'base':sys.base_prefix}))"
    )], logs.parent, logs / "import")
    info = json.loads(probe)
    package = Path(info["package"]).resolve().parent
    prefix = Path(info["prefix"]).resolve()
    if info["prefix"] == info["base"] or not package.is_relative_to(prefix):
        raise ValueError("the CLI must load a non-editable installation inside its isolated venv")
    expected = package_files(source / "src/checkwash")
    loaded = package_files(package)
    if not expected or expected != loaded:
        raise ValueError("installed package bytes differ from the supplied source checkout")
    version = tomllib.loads((source / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    if info["version"] != version:
        raise ValueError("installed package version differs from supplied source")
    return {"python": str(python), "package": str(package), "version": version,
            "source_package_sha256": package_digest(expected)}


def validate_manifest(payload: dict) -> list[dict]:
    if not isinstance(payload, dict) or payload.get("schema_version") != 1 or payload.get("baseline_source_sha") != BASELINE_SHA:
        raise ValueError("unexpected manifest schema or baseline source")
    if payload.get("selection_before_checkwash_execution") is not True or payload.get("checkwash_executed_during_selection") is not False:
        raise ValueError("manifest must record independent preselection")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not 1 <= len(cases) <= 50 or payload.get("case_count") != len(cases):
        raise ValueError("invalid bounded case count")
    ids = set()
    for case in cases:
        if not isinstance(case, dict) or not re.fullmatch(r"[A-Z][0-9]{2}", case.get("id", "")) or case["id"] in ids:
            raise ValueError("invalid or duplicate case identity")
        ids.add(case["id"])
        path = case.get("path", "")
        relative = PurePosixPath(path)
        if (not path or not relative.parts or "\\" in path or ":" in path or relative.is_absolute()
                or any(part.lower() in {"..", ".git"} for part in relative.parts)):
            raise ValueError("unsafe source path")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", case.get("repository", "")):
            raise ValueError("invalid public repository name")
        if case.get("status") != "modified" or case.get("projection") != "single_changed_test_file":
            raise ValueError("only complete modified-file projections are supported")
        if case.get("expected_classification") not in LABELS:
            raise ValueError("unknown audit classification")
        expected_verdict = "pass" if case["expected_classification"] == "preserving" else None
        if case.get("expected_verdict") != expected_verdict or not case.get("expected_intent"):
            raise ValueError("missing or contradictory audit expectation")
        for side, revision in (("before", "parent"), ("after", "commit")):
            if not re.fullmatch(r"[0-9a-f]{40}", case.get(revision, "")):
                raise ValueError("history must use exact commit identities")
            expected_url = f"https://raw.githubusercontent.com/{case['repository']}/{case[revision]}/{path}"
            record = case.get(side, {})
            if record.get("url") != expected_url or not re.fullmatch(r"[0-9a-f]{64}", record.get("sha256", "")):
                raise ValueError("source URL or hash is not bound to the manifest revision/path")
            if type(record.get("bytes")) is not int or not 0 < record["bytes"] <= MAX_SOURCE_BYTES:
                raise ValueError("invalid bounded source length")
    return cases


def download(record: dict, target: Path) -> bytes:
    request = urllib.request.Request(record["url"], headers={"User-Agent": "checkwash-historical-replay/1"})
    with urllib.request.urlopen(request, timeout=45) as response:
        data = response.read(MAX_SOURCE_BYTES + 1)
    if len(data) != record["bytes"] or sha256(data) != record["sha256"]:
        raise ValueError("download does not match frozen source bytes: " + record["url"])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return data


def file_record(path: Path, output: Path) -> dict:
    return {"path": path.relative_to(output).as_posix(), "sha256": sha256(path.read_bytes()), "bytes": path.stat().st_size}


def observe(python: Path, info: dict, repo: Path, revision: str, target: Path, output: Path) -> dict:
    target.mkdir(parents=True, exist_ok=True)
    coverage_path = target / "coverage.json"
    base_command = [str(python), "-I", "-B", "-m", "checkwash", "check", revision, "--repo", str(repo)]
    result = command([*base_command, "--format", "json", "--coverage-report", str(coverage_path)], repo, target / "findings")
    ir_result = command([*base_command, "--emit-ir"], repo, target / "ir")
    observation = {"exit": result.returncode, "ir_exit": ir_result.returncode,
                   "version": info["version"], "verdict": None, "findings": [], "errors": []}
    try:
        report = json.loads(result.stdout)
        ir = json.loads(ir_result.stdout)
        coverage = json.loads(coverage_path.read_bytes())
        if not all(isinstance(value, dict) for value in (report, ir, coverage)):
            raise ValueError("report roots must be objects")
        verdict = report.get("verdict")
        if verdict not in {"pass", "block"} or result.returncode != (1 if verdict == "block" else 0):
            raise ValueError("CLI verdict and exit disagree")
        if report.get("run", {}).get("checkwash_version") != info["version"]:
            raise ValueError("reported version differs from verified installed package")
        if report.get("config_errors") != [] or report.get("skipped_files") != []:
            raise ValueError("analysis reported configuration errors or skipped files")
        if not isinstance(report.get("findings"), list) or ir_result.returncode != 0 or not isinstance(ir.get("files"), list):
            raise ValueError("invalid findings or IR report")
        if (coverage.get("checkwash_coverage_version") != 1
                or coverage.get("status") not in {"incomplete", "no_known_gaps"}
                or coverage.get("run", {}).get("checkwash_version") != info["version"]
                or not isinstance(coverage.get("gaps"), list)):
            raise ValueError("invalid coverage report")
        observation.update({
            "verdict": verdict, "findings": report["findings"], "coverage_status": coverage.get("status"),
            "coverage_gaps": len(coverage["gaps"]), "represented_assertions": {
                side: sum(len((unit.get(side) or {}).get("assertions", []))
                          for file in ir["files"] for unit in file.get("units", []))
                for side in ("before", "after")
            },
        })
    except (OSError, ValueError, TypeError, KeyError) as error:
        observation["errors"].append(str(error))
    observation["raw"] = {path.name: file_record(path, output) for path in sorted(target.iterdir()) if path.is_file()}
    return observation


def replay(source: Path, python: Path, manifest: Path, output: Path) -> dict:
    receipt = {"schema_version": 1, "status": "failed", "source_sha": None,
               "manifest_sha256": None, "baseline_source_sha": BASELINE_SHA,
               "execution_scope": "Static CheckWash only; no downloaded JavaScript/TypeScript, upstream test runner, package manager, or repository hook is executed",
               "cases": [], "errors": []}
    try:
        source = source.resolve(strict=True)
        python = Path(os.path.abspath(python))
        manifest = manifest.resolve(strict=True)
        if not python.is_file():
            raise ValueError("candidate venv Python does not exist")
        if not manifest.is_relative_to(source):
            raise ValueError("manifest must be the committed file in the supplied source checkout")
        raw_manifest = manifest.read_bytes()
        receipt["manifest_sha256"] = sha256(raw_manifest)
        payload = json.loads(raw_manifest)
        cases = validate_manifest(payload)
        logs = output / "setup"
        receipt["source_sha"] = git(source, logs / "source-head", "rev-parse", "HEAD")
        if git(source, logs / "source-status", "status", "--porcelain", "--untracked-files=no"):
            raise ValueError("source checkout has tracked modifications")
        committed = checked(["git", "show", "HEAD:" + manifest.relative_to(source).as_posix()], source, logs / "manifest-commit")
        if committed != raw_manifest:
            raise ValueError("manifest bytes differ from the recorded source commit")
        (output / "manifest.json").write_bytes(raw_manifest)
        candidate_info = verify_install(python, source, logs / "candidate-before")
        receipt["candidate"] = candidate_info
        runtime = Path(tempfile.mkdtemp(prefix="checkwash-js-history-"))
        receipt["runtime_directory"] = str(runtime)
        baseline_source = runtime / "baseline-source"
        checked(["git", "-c", "init.templateDir=", "clone", "--shared", "--no-checkout", str(source), str(baseline_source)], output, logs / "baseline-clone")
        git(baseline_source, logs / "baseline-checkout", "checkout", "--detach", BASELINE_SHA)
        if git(baseline_source, logs / "baseline-head", "rev-parse", "HEAD") != BASELINE_SHA:
            raise ValueError("baseline source is not the exact v0.4.1 commit")
        baseline_venv = runtime / "baseline-venv"
        checked([str(python), "-I", "-m", "venv", str(baseline_venv)], output, logs / "baseline-venv")
        baseline_python = baseline_venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        checked([str(baseline_python), "-I", "-m", "pip", "install", "--disable-pip-version-check", "--no-deps", str(baseline_source)], output, logs / "baseline-install", timeout=300)
        baseline_info = verify_install(baseline_python, baseline_source, logs / "baseline-before")
        if baseline_info["version"] != BASELINE_VERSION:
            raise ValueError("baseline installed version is not 0.4.1")
        receipt["baseline"] = baseline_info
        for case in cases:
            case_root = output / "cases" / case["id"]
            case_root.mkdir(parents=True, exist_ok=True)
            write_json(case_root / "provenance.json", case)
            row = {"id": case["id"], "path": case["path"], "repository": case["repository"],
                   "commit": case["commit"], "parent": case["parent"],
                   "expected_classification": case["expected_classification"], "expected_intent": case["expected_intent"],
                   "scored": case["expected_classification"] == "preserving",
                   "status": "failed", "errors": []}
            try:
                repo = runtime / "cases" / case["id"]
                repo.mkdir(parents=True)
                git(repo, case_root / "git-init", "-c", "init.templateDir=", "init", "-b", "main")
                target = repo.joinpath(*PurePosixPath(case["path"]).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                revisions = {}
                for side in ("before", "after"):
                    data = download(case[side], case_root / (side + ".source"))
                    target.write_bytes(data)
                    git(repo, case_root / (side + "-add"), "add", "--", case["path"])
                    git(repo, case_root / (side + "-commit"), "commit", "--allow-empty", "-m", case["id"] + " " + side)
                    revisions[side] = git(repo, case_root / (side + "-head"), "rev-parse", "HEAD")
                row["synthetic_revisions"] = revisions
                revision = revisions["before"] + ".." + revisions["after"]
                for label, executable, info in (("baseline", baseline_python, baseline_info), ("candidate", python, candidate_info)):
                    row[label] = observe(executable, info, repo, revision, case_root / label, output)
                    row["errors"].extend(label + ": " + error for error in row[label]["errors"])
                if case["expected_classification"] == "preserving" and row["candidate"]["verdict"] == "block":
                    row["errors"].append("candidate blocked independently preselected preserving source change")
                row["status"] = "failed" if row["errors"] else "passed" if row["scored"] else "observed"
            except (OSError, ValueError, TypeError, RuntimeError, subprocess.SubprocessError) as error:
                row["errors"].append(str(error))
            receipt["cases"].append(row)
            write_json(output / "receipt.json", receipt)
        if verify_install(python, source, logs / "candidate-after") != candidate_info:
            raise ValueError("candidate package changed during replay")
        if verify_install(baseline_python, baseline_source, logs / "baseline-after") != baseline_info:
            raise ValueError("baseline package changed during replay")
        if git(source, logs / "source-head-after", "rev-parse", "HEAD") != receipt["source_sha"]:
            raise ValueError("source commit changed during replay")
        if git(source, logs / "source-status-after", "status", "--porcelain", "--untracked-files=no"):
            raise ValueError("source checkout acquired tracked modifications during replay")
        if manifest.read_bytes() != raw_manifest:
            raise ValueError("manifest changed during replay")
        receipt["summary"] = {
            "total": len(cases), "executed": sum("candidate" in row and "baseline" in row for row in receipt["cases"]),
            "preserving": sum(case["expected_classification"] == "preserving" for case in cases),
            "descriptive_only": sum(case["expected_classification"] != "preserving" for case in cases),
            "candidate_preserving_blocks": sum(row["expected_classification"] == "preserving" and row.get("candidate", {}).get("verdict") == "block" for row in receipt["cases"]),
            "baseline_preserving_blocks": sum(row["expected_classification"] == "preserving" and row.get("baseline", {}).get("verdict") == "block" for row in receipt["cases"]),
            "failed": sum(row["status"] == "failed" for row in receipt["cases"]),
        }
        if not receipt["summary"]["failed"] and len(receipt["cases"]) == len(cases):
            receipt["status"] = "passed"
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        receipt["errors"].append(str(error))
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True, help="absolute Python path in the installed candidate venv")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        parser.error("--output must be absent or empty; existing receipts are never overwritten")
    output.mkdir(parents=True, exist_ok=True)
    receipt = replay(args.source, args.python, args.manifest, output)
    write_json(output / "receipt.json", receipt)
    print(json.dumps({key: receipt.get(key) for key in ("status", "source_sha", "manifest_sha256", "summary", "errors")}, sort_keys=True))
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

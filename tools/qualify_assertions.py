"""Qualify owned assertion contracts through an isolated, source-bound CLI.

No network or test code execution: only git and the selected checkwash process run.
Wheel commands use a fresh venv's ``python -I -m checkwash``; zipapp commands use
``python -I /absolute/checkwash.pyz``. The archive AND loaded package must match
the supplied source tree, so an older artifact with the same version cannot pass.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile
import tomllib
import zipfile


ROOT = Path(__file__).resolve().parents[1]


def isolated_env() -> dict[str, str]:
    env = {
        key: value for key, value in os.environ.items()
        if not key.startswith(("PYTHON", "GIT_", "CHECKWASH_", "GREENWASH_"))
    }
    env.update({
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_AUTHOR_NAME": "assertion qualification",
        "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
        "GIT_COMMITTER_NAME": "assertion qualification",
        "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z",
        "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z",
        "GREENWASH_TODAY": "2026-01-01",
        "NO_COLOR": "1",
        "PYTHONUTF8": "1",
    })
    return env


def run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command, cwd=cwd, env=isolated_env(), capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=120,
    )


def git(repo: Path, *args: str) -> str:
    result = run(["git", "-c", "core.autocrlf=false", "-c", "commit.gpgsign=false", *args], repo)
    if result.returncode:
        raise ValueError("git failed: " + result.stderr.strip())
    return result.stdout.strip()


def package_files(package: Path) -> dict[str, str]:
    """Hash shipped package files; bytecode is not source or artifact identity."""
    return {
        "checkwash/" + path.relative_to(package).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(package.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    }


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def archive_files(artifact: Path) -> dict[str, str]:
    with zipfile.ZipFile(artifact) as archive:
        names = [
            name for name in archive.namelist()
            if name.startswith("checkwash/") and not name.endswith("/")
            and "__pycache__" not in PurePosixPath(name).parts and not name.endswith(".pyc")
        ]
        if len(names) != len(set(names)):
            raise ValueError("artifact has duplicate package members")
        return {name: hashlib.sha256(archive.read(name)).hexdigest() for name in sorted(names)}


def _require_same(expected: dict[str, str], actual: dict[str, str], label: str) -> None:
    changed = sorted(name for name in set(expected) | set(actual) if expected.get(name) != actual.get(name))
    if changed:
        raise ValueError(label + " does not match source package: " + ", ".join(changed[:8]))


def invocation(
    distribution: str, source: Path, artifact: Path | None, command: list[str],
    expected: dict[str, str], cwd: Path,
) -> list[str]:
    """Resolve a controlled invocation, verifying installed wheel bytes separately."""
    if not command:
        command = [sys.executable]
    # Do not resolve symlinks: POSIX venv/bin/python commonly points to the
    # base executable, but the original path is what selects the virtualenv.
    interpreter = os.path.abspath(command[0])
    if not Path(interpreter).is_file():
        raise ValueError("Python executable does not exist: " + interpreter)
    if distribution == "source":
        if len(command) != 1:
            raise ValueError("source qualification takes an interpreter after --")
        bootstrap = (
            "import sys; sys.path.insert(0, " + repr(str(source / "src")) + "); "
            "from checkwash.cli import main; raise SystemExit(main())"
        )
        return [interpreter, "-I", "-B", "-c", bootstrap]
    if artifact is None:
        raise ValueError("wheel/pyz qualification requires --artifact")
    _require_same(expected, archive_files(artifact), "artifact")
    if distribution == "pyz":
        allowed = [interpreter, "-I", str(artifact)]
        if len(command) != 1 and [interpreter, *command[1:]] != allowed:
            raise ValueError("pyz command must be: ABSOLUTE_PYTHON -I ABSOLUTE_ARTIFACT")
        return [interpreter, "-B", *allowed[1:]]
    allowed = [interpreter, "-I", "-m", "checkwash"]
    if len(command) != 1 and [interpreter, *command[1:]] != allowed:
        raise ValueError("wheel command must be: FRESH_VENV_PYTHON -I -m checkwash")
    probe = run([interpreter, "-I", "-B", "-c", (
        "import json, sys, checkwash; "
        "print(json.dumps({'package':checkwash.__file__,'prefix':sys.prefix,'base':sys.base_prefix}))"
    )], cwd)
    if probe.returncode:
        raise ValueError("isolated wheel import failed: " + probe.stderr.strip())
    info = json.loads(probe.stdout)
    package = Path(info["package"]).resolve().parent
    prefix = Path(info["prefix"]).resolve()
    if info["prefix"] == info["base"] or not package.is_relative_to(prefix):
        raise ValueError("wheel must load inside its fresh venv, not an editable/global installation")
    _require_same(expected, package_files(package), "loaded wheel")
    return [interpreter, "-B", *allowed[1:]]


def observe(result: subprocess.CompletedProcess[str], case: dict, version: str | None = None) -> dict:
    errors = []
    expected_exit = 1 if case["verdict"] == "block" else 0
    if result.returncode != expected_exit:
        errors.append(f"exit {result.returncode}; expected {expected_exit}")
    try:
        payload = json.loads(result.stdout)
        if not isinstance(payload, dict):
            raise ValueError("JSON root is not an object")
        verdict = payload.get("verdict")
        findings = payload.get("findings")
        if not isinstance(findings, list) or any(not isinstance(row, dict) for row in findings):
            raise ValueError("findings is not an array of objects")
        if payload.get("config_errors") != [] or payload.get("skipped_files") != []:
            errors.append("analysis must not contain config errors or skipped files")
        if version is not None:
            report_run = payload.get("run")
            if not isinstance(report_run, dict) or report_run.get("checkwash_version") != version:
                errors.append("JSON report version differs from the qualified source")
        if verdict != case["verdict"]:
            errors.append(f"verdict {verdict!r}; expected {case['verdict']!r}")
        if case["verdict"] == "pass" and findings:
            errors.append("preserving control produced findings")
        if case["verdict"] == "block":
            expected_finding = {key: case[key] for key in ("rule", "severity", "path")}
            actual_findings = [{key: row.get(key) for key in ("rule", "severity", "path")} for row in findings]
            if expected_finding not in actual_findings:
                errors.append(f"missing {case['rule']}/{case['severity']} at {case['path']}")
            elif actual_findings != [expected_finding]:
                errors.append("blocking case produced extra or duplicate findings")
        observed = {
            "exit": result.returncode, "verdict": verdict,
            "findings": sorted([
                {key: row.get(key) for key in ("rule", "severity", "path")}
                for row in findings
            ], key=lambda row: json.dumps(row, sort_keys=True)),
        }
    except (ValueError, TypeError) as error:
        errors.append("invalid JSON report: " + str(error))
        observed = {"exit": result.returncode, "verdict": None, "findings": []}
    return {"id": case["id"], "kind": case["kind"], "expected": {
        key: case[key] for key in ("verdict", "rule", "severity")
    }, "observed": observed, "errors": errors, "status": "failed" if errors else "passed"}


def exercise(command: list[str], cases: list[dict], repo: Path, version: str) -> tuple[list[dict], list[str]]:
    git(repo, "init", "-b", "main")
    observations = []
    previous: Path | None = None
    for case in cases:
        relative = PurePosixPath(case["path"])
        if relative.is_absolute() or ".." in relative.parts or ".git" in relative.parts or "\\" in case["path"]:
            raise ValueError("unsafe fixture path: " + case["path"])
        if previous is not None:
            previous.unlink()
        path = repo.joinpath(*relative.parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        for stage in ("before", "after"):
            path.write_text(case[stage], encoding="utf-8", newline="\n")
            git(repo, "add", "--all")
            git(repo, "commit", "--allow-empty", "-m", case["id"] + " " + stage)
        observations.append(observe(run([*command, "check", "HEAD~1..HEAD", "--format", "json"], repo), case, version))
        previous = path
    errors = []
    if cases:
        clean = run([*command, "check", "HEAD..HEAD", "--format", "json"], repo)
        clean_case = {"id": "clean", "kind": "control", "path": cases[-1]["path"],
                      "verdict": "pass", "rule": None, "severity": None}
        errors.extend("clean range: " + error for error in observe(clean, clean_case, version)["errors"])
        invalid = run([*command, "check", "MISSING_QUALIFICATION_REF..HEAD", "--format", "json"], repo)
        if invalid.returncode != 2 or "engine error" not in invalid.stderr:
            errors.append("invalid ref must produce engine-error stderr and exit 2")
    return observations, errors


def qualify(
    *, source: Path, distribution: str, command: list[str],
    artifact: Path | None = None, cases: list[dict] | None = None,
) -> dict:
    source = source.resolve(strict=True)
    if cases is None:
        # Script and importlib-based pytest loading both resolve the owned contract.
        sys.path.insert(0, str(ROOT / "tools"))
        from assertion_contract import mutation_cases
        cases = mutation_cases()
    receipt = {
        "schema_version": 1, "distribution": distribution, "status": "failed",
        "suite_sha256": digest(cases), "source_commit": None,
        "source_package_sha256": None, "source_package_dirty": None,
        "artifact_sha256": None, "version": None, "cases": [], "errors": [],
    }
    try:
        receipt["source_commit"] = git(source, "rev-parse", "HEAD")
        receipt["source_package_dirty"] = bool(git(source, "status", "--porcelain", "--", "src/checkwash", "pyproject.toml"))
        expected = package_files(source / "src/checkwash")
        if not expected:
            raise ValueError("source package is empty")
        receipt["source_package_sha256"] = digest(expected)
        version = tomllib.loads((source / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
        if artifact is not None:
            artifact = artifact.resolve(strict=True)
            receipt["artifact_sha256"] = hashlib.sha256(artifact.read_bytes()).hexdigest()
        if not cases or len({case["id"] for case in cases}) != len(cases):
            raise ValueError("qualification needs nonempty cases with unique IDs")
        with tempfile.TemporaryDirectory(prefix="checkwash-assertion-qualification-") as temporary:
            repo = Path(temporary)
            resolved = invocation(distribution, source, artifact, command, expected, repo)
            result = run([*resolved, "--version"], repo)
            receipt["version"] = result.stdout.strip()
            if result.returncode or receipt["version"] != "checkwash " + version:
                raise ValueError("CLI version/exit does not match the candidate source version")
            receipt["cases"], receipt["errors"] = exercise(resolved, cases, repo, version)
            _require_same(expected, package_files(source / "src/checkwash"), "source after qualification")
            if git(source, "rev-parse", "HEAD") != receipt["source_commit"]:
                raise ValueError("source commit changed during qualification")
            if artifact is not None and hashlib.sha256(artifact.read_bytes()).hexdigest() != receipt["artifact_sha256"]:
                raise ValueError("artifact changed during qualification")
            # Recheck the loaded wheel too, not just the archive handed to the tool.
            invocation(distribution, source, artifact, command, expected, repo)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError, zipfile.BadZipFile) as error:
        receipt["errors"].append(str(error))
    failed = sum(row["status"] != "passed" for row in receipt["cases"])
    receipt["summary"] = {"total": len(cases), "executed": len(receipt["cases"]), "failed": failed}
    if not receipt["errors"] and not failed and len(receipt["cases"]) == len(cases):
        receipt["status"] = "passed"
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--distribution", choices=["source", "wheel", "pyz", "action-pinned-engine"], required=True)
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER, help="after --: absolute Python executable, optionally -I -m checkwash or -I ABSOLUTE_PYZ")
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    receipt = qualify(source=args.source_root, distribution=args.distribution, artifact=args.artifact, command=command)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: receipt[key] for key in ("distribution", "status", "summary", "errors")}, sort_keys=True))
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

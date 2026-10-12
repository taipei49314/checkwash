"""Trusted synthetic fixtures and receipts for the hosted Action qualification."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib


CASES = {"clean-pass": (0, 0), "clean-block": (1, 1),
         "polluted-block": (1, 1), "missing-ref": (2, "unavailable")}
SYSTEMS = {"ubuntu-latest", "macos-latest", "windows-latest"}
CANDIDATE_DIRECTORY = "candidate-中文"


def git(root, *args):
    result = subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, timeout=30)
    return result.stdout.decode("utf-8").strip()


def append(path, values):
    lines = []
    for key, value in values.items():
        if any(char in str(value) for char in "\r\n\0"):
            raise ValueError("invalid fixture output")
        lines.append(f"{key}={value}\n")
    with open(path, "a", encoding="utf-8", newline="\n") as stream:
        stream.writelines(lines)


def prepare(case):
    root = Path(os.environ["GITHUB_WORKSPACE"]).resolve()
    if (root / ".git").exists():
        raise ValueError("fixture root must not already be a checkout")
    if not (root / CANDIDATE_DIRECTORY / "action/secure.py").is_file():
        raise ValueError("fixed candidate checkout missing")
    git(root, "init")
    git(root, "config", "user.name", "Action qualification")
    git(root, "config", "user.email", "qualification@example.invalid")
    (root / ".gitignore").write_text(CANDIDATE_DIRECTORY + "/\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "calculator.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (root / "tests/test_total.py").write_text(
        "from calculator import add\n\ndef test_total():\n    assert add(2, 3) == 5\n", encoding="utf-8")
    git(root, "add", ".gitignore", "calculator.py", "tests")
    git(root, "commit", "-m", "synthetic base")
    base = git(root, "rev-parse", "HEAD")
    if case == "clean-pass":
        (root / "calculator.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    else:
        (root / "tests/test_total.py").write_text(
            "from calculator import add\n\ndef test_total():\n    pass\n", encoding="utf-8")
    git(root, "add", "calculator.py", "tests")
    git(root, "commit", "-m", "synthetic head")
    if case == "polluted-block":
        marker = Path(os.environ["RUNNER_TEMP"]) / "CHECKWASH_SUBJECT_EXECUTED"
        payload = "from pathlib import Path\nPath(" + repr(str(marker)) + ").write_text('executed')\n"
        for name in ("pip", "checkwash", "hatchling"):
            (root / name).mkdir()
            (root / name / "__init__.py").write_text(payload, encoding="utf-8")
            (root / name / "__main__.py").write_text(payload, encoding="utf-8")
        (root / "sitecustomize.py").write_text(payload, encoding="utf-8")
        (root / "setup.py").write_text(payload, encoding="utf-8")
        (root / "pyproject.toml").write_text(
            '[build-system]\nrequires=[]\nbuild-backend="hatchling"\nbackend-path=["."]\n', encoding="utf-8")
        config = root / "pip.ini"
        config.write_text("[global]\nindex-url=http://127.0.0.1:9/untrusted\n", encoding="utf-8")
        fake = root / "fake-bin"
        fake.mkdir()
        for name in ("python", "pip", "checkwash", "git"):
            script = fake / name
            script.write_text("#!/bin/sh\nprintf executed > '" + marker.as_posix() + "'\nexit 0\n", encoding="utf-8")
            script.chmod(0o755)
            (fake / (name + ".cmd")).write_text('@echo off\r\necho executed>"' + str(marker) + '"\r\n', encoding="utf-8")
        append(os.environ["GITHUB_ENV"], {
            "PYTHONPATH": str(root), "PYTHONHOME": str(root / "invalid-home"), "PYTHONUTF8": "0",
            "PYTHONIOENCODING": "cp950", "PYTHONUSERBASE": str(root),
            "PIP_CONFIG_FILE": str(config), "PIP_INDEX_URL": "http://127.0.0.1:9/untrusted",
            "PIP_FIND_LINKS": str(root), "PIP_TARGET": str(root / "untrusted-install"),
            "PIP_PREFIX": str(root), "PIP_CONSTRAINT": str(root / "missing-constraints")})
        with open(os.environ["GITHUB_PATH"], "a", encoding="utf-8", newline="\n") as stream:
            stream.write(str(fake) + "\n")
    expected = {"base": "f" * 40 if case == "missing-ref" else base,
                "head": git(root, "rev-parse", "HEAD")}
    (Path(os.environ["RUNNER_TEMP"]) / "action-security-fixture.json").write_text(
        json.dumps(expected, sort_keys=True) + "\n", encoding="utf-8")
    append(os.environ["GITHUB_OUTPUT"], expected)


def capture(case, system):
    temporary = Path(os.environ["RUNNER_TEMP"])
    output = temporary / "action-security-evidence"
    output.mkdir()
    directories = sorted(path for path in temporary.glob("checkwash-action-*") if path.is_dir())
    receipts = []
    for number, directory in enumerate(directories):
        dest = output / str(number)
        dest.mkdir()
        for name in ("identity.json", "check-receipt.json", "stdout.txt", "stderr.txt",
                     "install-report.json", "install-stdout.txt", "install-stderr.txt"):
            if (directory / name).is_file():
                shutil.copyfile(directory / name, dest / name)
        if (directory / "check-receipt.json").is_file():
            receipts.append(str(number) + "/check-receipt.json")
    source = Path(os.environ["GITHUB_WORKSPACE"]) / CANDIDATE_DIRECTORY
    source_files = {
        path.relative_to(source / "src/checkwash").as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (source / "src/checkwash").rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix not in {".pyc", ".pyo"}
    }
    source_digest = hashlib.sha256(json.dumps(source_files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    expected = json.loads((temporary / "action-security-fixture.json").read_text(encoding="utf-8"))
    metadata = {
        "case": case, "system": system, "candidate_sha": os.environ["CANDIDATE_SHA"],
        "run_id": os.environ["GITHUB_RUN_ID"], "attempt": os.environ["GITHUB_RUN_ATTEMPT"],
        "step_outcome": os.environ["ACTION_OUTCOME"], "receipts": receipts,
        "source_root": str(source.resolve()), "source_digest": source_digest,
        "source_version": tomllib.loads((source / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"],
        "trusted_python": str(Path(sys.executable).resolve()),
        "expected_base": expected["base"], "expected_head": expected["head"],
        "canary_executed": (temporary / "CHECKWASH_SUBJECT_EXECUTED").exists(),
        "untrusted_install_created": (Path(os.environ["GITHUB_WORKSPACE"]) / "untrusted-install").exists(),
        "runner_image": os.environ.get("ImageOS"), "runner_image_version": os.environ.get("ImageVersion"),
    }
    (output / "case.json").write_text(json.dumps(metadata, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def validate(root):
    found = {}
    candidate = os.environ["CANDIDATE_SHA"]
    for metadata_path in root.rglob("case.json"):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        key = (metadata["case"], metadata["system"])
        if key in found or key[0] not in CASES or key[1] not in SYSTEMS:
            raise ValueError("duplicate or unexpected qualification case")
        found[key] = metadata
        if (metadata["candidate_sha"] != candidate or metadata["canary_executed"] or metadata["untrusted_install_created"]
                or metadata["run_id"] != os.environ["GITHUB_RUN_ID"]
                or metadata["attempt"] != os.environ["GITHUB_RUN_ATTEMPT"]):
            raise ValueError("source identity or subject-execution failure")
        if len(metadata["receipts"]) != 1:
            raise ValueError("expected exactly one complete Action receipt")
        receipt_path = metadata_path.parent / metadata["receipts"][0]
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        expected_exit, expected_analysis = CASES[key[0]]
        if (receipt["exit_code"], receipt["analysis_exit_code"]) != (expected_exit, expected_analysis):
            raise ValueError("engine/integration exit mismatch")
        if expected_analysis != "unavailable":
            if receipt.get("base") != metadata["expected_base"] or receipt.get("head") != metadata["expected_head"]:
                raise ValueError("Action analyzed the wrong fixture commits")
        elif not receipt.get("error") or "base" in receipt or "head" in receipt:
            raise ValueError("missing-ref case did not fail before analysis")
        if metadata["step_outcome"] != ("success" if expected_exit == 0 else "failure"):
            raise ValueError("real composite step did not preserve failure")
        identity = receipt["identity"]
        if (not identity["isolated"] or not identity["utf8"] or not identity["bytecode_writes_disabled"]
                or identity["source_digest"] != metadata["source_digest"]
                or identity["source_root"] != metadata["source_root"]
                or identity["version"] != metadata["source_version"]
                or identity["base_python"] != metadata["trusted_python"]):
            raise ValueError("runtime identity evidence incomplete")
        installed = json.loads((receipt_path.parent / "install-report.json").read_text(encoding="utf-8"))
        if not installed.get("pip_version") or len(installed.get("install", [])) != 1:
            raise ValueError("actual installer evidence incomplete")
        if expected_analysis == 1 and "ASSERT_REMOVED" not in (receipt_path.parent / "stdout.txt").read_text(encoding="utf-8"):
            raise ValueError("real engine did not report the removed assertion")
    expected = {(case, system) for case in CASES for system in SYSTEMS}
    if found.keys() != expected:
        raise ValueError("qualification cases missing")
    print("All", len(found), "actual hosted Action cases matched their expected outcomes.")
    print("Expected BLOCK/ERROR jobs remain failed; this is the independent qualification result.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("prepare", "capture", "validate"))
    parser.add_argument("--case", choices=CASES)
    parser.add_argument("--system", choices=sorted(SYSTEMS))
    parser.add_argument("--root", type=Path)
    args = parser.parse_args()
    if args.mode == "prepare":
        prepare(args.case)
    elif args.mode == "capture":
        capture(args.case, args.system)
    else:
        validate(args.root)


if __name__ == "__main__":
    main()

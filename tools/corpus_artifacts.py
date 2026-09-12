"""Source-bound CI corpus receipts; this helper never imports the engine.

The emit subcommand runs the existing emitter. The compare subcommand only
reads Git metadata and artifacts, and requires the entire nine-leg matrix.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
MATRIX = tuple((os_name, version) for os_name in
               ("ubuntu-latest", "windows-latest", "macos-latest")
               for version in ("3.11", "3.12", "3.13"))
FILES = {"corpus-findings.json", "receipt.json", "emitter-stderr.txt"}
MAX_BYTES = 64 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def invalid_constant(value):
    raise ValueError(f"non-finite JSON constant: {value}")


DECODER = json.JSONDecoder(object_pairs_hook=unique_object, parse_constant=invalid_constant)


def json_value(data):
    text = data.decode("utf-8")
    value, end = DECODER.raw_decode(text)
    require(not text[end:].strip(), "trailing JSON data")
    return value


def read_file(path):
    require(path.is_file() and not path.is_symlink(), f"missing or linked file: {path}")
    require(path.stat().st_size <= MAX_BYTES, f"oversized artifact: {path}")
    return path.read_bytes()


def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args]).decode("utf-8").strip()


def source_context(checkout_sha, candidate_head, run_id, attempt):
    require(all(re.fullmatch(r"[0-9a-f]{40}", value) for value in (checkout_sha, candidate_head)),
            "source identities must be full commit SHAs")
    require(re.fullmatch(r"[1-9][0-9]*", run_id) and re.fullmatch(r"[1-9][0-9]*", attempt),
            "run and attempt must be positive integers")
    require(git("rev-parse", "HEAD") == checkout_sha, "checkout differs from the workflow snapshot")
    subprocess.run(["git", "-C", str(ROOT), "merge-base", "--is-ancestor", candidate_head,
                    checkout_sha], check=True)
    require(not git("status", "--porcelain=v1", "--untracked-files=all", "--", "src", "tools",
                    "tests/cases", "pyproject.toml"), "emitter source or fixtures changed in the checkout")
    entries = git("ls-tree", "--name-only", "HEAD:tests/cases").splitlines()
    names = sorted(name for name in entries if name.endswith(".gwcase"))
    require(names and all(re.fullmatch(r"[A-Za-z0-9_.-]+\.gwcase", name) for name in names),
            "missing or unsupported fixture inventory")
    return {
        "checkout_sha": checkout_sha, "candidate_head": candidate_head,
        "run_id": run_id, "run_attempt": attempt,
        "tree_sha": git("rev-parse", "HEAD^{tree}"),
        "src_tree_sha": git("rev-parse", "HEAD:src"),
        "cases_tree_sha": git("rev-parse", "HEAD:tests/cases"),
        "emitter_blob_sha": git("rev-parse", "HEAD:tools/emit_corpus.py"),
        "case_names": names,
    }


def validate_payload(data, names):
    """Require each expected fixture's complete findings envelope and IR JSON."""
    require(0 < len(data) <= MAX_BYTES and b"\r" not in data, "empty, oversized or non-LF corpus")
    text = data.decode("utf-8")
    position = 0
    for name in names:
        marker = f"# {name}\n"
        require(text.startswith(marker, position), f"missing, reordered or unexpected fixture: {name}")
        position += len(marker)
        payloads = []
        for _ in range(2):
            payload, position = DECODER.raw_decode(text, position)
            require(isinstance(payload, dict), f"non-object payload for {name}")
            payloads.append(payload)
            while position < len(text) and text[position] in " \t\n":
                position += 1
        findings, ir = payloads
        require(findings.get("checkwash_findings_version") == 2
                and findings.get("verdict") in {"pass", "block", "error"}
                and isinstance(findings.get("run"), dict)
                and isinstance(findings.get("findings"), list)
                and isinstance(findings.get("summary"), dict)
                and isinstance(findings.get("config_errors"), list)
                and isinstance(findings.get("skipped_files"), list), f"invalid findings envelope for {name}")
        require(ir.get("version") == 2 and isinstance(ir.get("files"), list)
                and isinstance(ir.get("globals"), dict), f"invalid IR envelope for {name}")
        for finding in findings["findings"]:
            require(isinstance(finding, dict)
                    and all(isinstance(finding.get(key), str) for key in ("rule", "path", "message"))
                    and finding.get("severity") in {"info", "warn", "high", "critical"},
                    f"invalid finding for {name}")
    require(position == len(text), "unexpected trailing corpus records")


def artifact_name(os_name, version, attempt):
    return f"corpus-{os_name}-py{version}-attempt-{attempt}"


def make_receipt(context, os_name, version, payload, stderr):
    validate_payload(payload, context["case_names"])
    return {"schema": "checkwash.corpus-artifact.v1", **context, "os": os_name, "python": version,
            "payload_bytes": len(payload), "payload_sha256": digest(payload),
            "stderr_bytes": len(stderr), "stderr_sha256": digest(stderr)}


def emit(args):
    context = source_context(args.checkout_sha, args.candidate_head, args.run_id, args.attempt)
    require((args.os, args.python) in MATRIX, "unsupported matrix member")
    require(args.python == f"{sys.version_info.major}.{sys.version_info.minor}", "wrong Python runtime")
    require(platform.system() == {"ubuntu-latest": "Linux", "windows-latest": "Windows",
                                  "macos-latest": "Darwin"}[args.os], "wrong OS runtime")
    args.output.mkdir(parents=True, exist_ok=True)
    require(not any(args.output.iterdir()), "refusing to reuse an artifact output directory")
    result = subprocess.run([sys.executable, str(ROOT / "tools/emit_corpus.py")], cwd=ROOT,
                            env={**os.environ, "PYTHONUTF8": "1"}, capture_output=True)
    # Save unmodified bytes even if emission or validation fails.
    (args.output / "corpus-findings.json").write_bytes(result.stdout)
    (args.output / "emitter-stderr.txt").write_bytes(result.stderr)
    if result.stderr:
        sys.stderr.buffer.write(result.stderr)
    require(result.returncode == 0, f"emitter exited {result.returncode}")
    require(context == source_context(args.checkout_sha, args.candidate_head, args.run_id, args.attempt),
            "source context changed during emission")
    receipt = make_receipt(context, args.os, args.python, result.stdout, result.stderr)
    (args.output / "receipt.json").write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n",
                                             encoding="utf-8")


def compare(directory, context):
    expected = {artifact_name(os_name, version, context["run_attempt"]): (os_name, version)
                for os_name, version in MATRIX}
    require(directory.is_dir() and not directory.is_symlink(), "missing artifact directory")
    require({path.name for path in directory.iterdir()} == set(expected), "expected exactly nine named artifacts")
    payloads, receipts = [], []
    for name, (os_name, version) in expected.items():
        folder = directory / name
        require(folder.is_dir() and not folder.is_symlink(), f"invalid artifact directory: {name}")
        require({path.name for path in folder.iterdir()} == FILES, f"incomplete or unexpected files: {name}")
        receipt = json_value(read_file(folder / "receipt.json"))
        payload = read_file(folder / "corpus-findings.json")
        stderr = read_file(folder / "emitter-stderr.txt")
        require(receipt == make_receipt(context, os_name, version, payload, stderr),
                f"artifact identity, inventory or content hash mismatch: {name}")
        payloads.append(payload)
        receipts.append({"artifact": name, "payload_sha256": digest(payload), "payload_bytes": len(payload)})
    require(all(payload == payloads[0] for payload in payloads), "matrix corpus bytes differ")
    return {"status": "passed", **context, "artifact_count": len(receipts), "artifacts": receipts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("emit", "compare"))
    for option in ("checkout-sha", "candidate-head", "run-id", "attempt"):
        parser.add_argument("--" + option, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--os")
    parser.add_argument("--python")
    args = parser.parse_args()
    try:
        if args.command == "emit":
            emit(args)
        else:
            require(args.input is not None, "compare requires --input")
            context = source_context(args.checkout_sha, args.candidate_head, args.run_id, args.attempt)
            report = compare(args.input, context)
            args.output.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        if args.command == "compare":
            args.output.write_text(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True) + "\n",
                                   encoding="utf-8")
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

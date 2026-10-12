"""Bounded diagnostics for owned R1 reductions; not a qualification gate.

Run only in an ordinary hosted PR job. Each phase receives its own process and
30-second budget. Exceptions and missing semantic results remain explicit in
the receipt. Capturing a failure successfully is not evidence of a repair.
No synthetic repository source is executed, and no product code is patched.
"""

from __future__ import annotations

import argparse
import ast
import datetime
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import traceback

from reliability_r1_cases import LOCATIONS, TEST_PATH, WIDTHS, pair, snapshot


PHASES = (
    "syntax", "stdlib_unparse", "stable_dump", "binding_maps", "ordered_bindings",
    "trivial_subject", "positive_comparisons", "asserted_subject", "frontend",
    "pipeline_format", "pipeline_weaken", "pipeline_expected", "pipeline_subject",
)
CONTEXT: dict[str, str] = {}


def _digest(value: str) -> dict[str, object]:
    encoded = value.encode("utf-8")
    return {"bytes": len(encoded), "sha256": hashlib.sha256(encoded).hexdigest()}


def _partial_output(value: bytes | str | None) -> str:
    # TimeoutExpired may retain bytes even when subprocess text=True.
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value or ""


def _parsed_summary(parsed) -> dict[str, object]:
    return {
        "parse_ok": parsed.parse_ok, "symbols": parsed.symbols,
        "units": [{"qualname": unit.qualname, "assertions": [
            {"text": _digest(item.text), "strength": item.strength,
             "right_value": item.right_value, "inherited": item.inherited}
            for item in unit.side.assertions
        ]} for unit in parsed.units],
    }


def _pipeline(location: str, terms: int, change: str) -> dict[str, object]:
    from checkwash.change import FileChange
    from checkwash.config import Config
    from checkwash.contract import Contract
    from checkwash.engine import analyze
    from checkwash.gitio.snapshot import search_source_mapping

    before, after = pair(location, terms, change)
    changes = [FileChange(path, "modified", before[path], after[path])
               for path in before if before[path] != after[path]]
    CONTEXT.update(path="<pipeline>", side="both")
    ir, findings, verdict = analyze(
        changes, Config(), Contract(), [], datetime.date(2026, 10, 12),
        known_modules={"app"}, self_modules={"app"},
        head_reader=after.get, head_searcher=lambda needles: search_source_mapping(after, needles),
        root_reader=after.get, root_searcher=lambda needles: search_source_mapping(after, needles),
        root_path_lister=lambda: sorted(after),
        root_batch_reader=lambda paths: {path: after.get(path) for path in paths},
    )
    return {
        "verdict": verdict,
        "files": [file.path for file in ir.files],
        "findings": [{"rule": finding.rule, "severity": finding.severity,
                      "fingerprint": finding.fingerprint} for finding in findings],
    }


def run_phase(location: str, terms: int, phase: str) -> dict[str, object]:
    from checkwash.frontends.python import frontend
    from checkwash.ir import astutil

    if phase.startswith("pipeline_"):
        return _pipeline(location, terms, phase.removeprefix("pipeline_"))
    results: dict[str, object] = {}
    for path, data in snapshot(location, terms).items():
        CONTEXT.update(path=path, side="before")
        text = data.decode("utf-8")
        if phase == "frontend":
            results[path] = _parsed_summary(frontend.parse_python(data, collect_tests=path == TEST_PATH))
            continue
        tree = ast.parse(text)
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
        if phase == "syntax":
            count, depth = 0, 0
            pending = [(tree, 0)]
            while pending:
                node, level = pending.pop()
                count += 1
                depth = max(depth, level)
                pending.extend((child, level + 1) for child in ast.iter_child_nodes(node))
            results[path] = {"nodes": count, "depth": depth, "bytes": len(data)}
        elif phase == "stdlib_unparse":
            results[path] = _digest(ast.unparse(tree))
        elif phase == "stable_dump":
            frontend._normalize_for_fingerprint(tree)
            results[path] = _digest(astutil.stable_dump(tree))
        elif phase == "binding_maps":
            results[path] = {function.name: frontend._binding_maps(function) for function in functions}
        elif phase == "ordered_bindings":
            results[path] = {function.name: frontend._ordered_bindings(function) for function in functions}
        elif phase == "trivial_subject":
            results[path] = [frontend._is_trivial_subject(node.test)
                             for node in ast.walk(tree) if isinstance(node, ast.Assert)]
        elif phase == "positive_comparisons":
            # Isolate the existing recursive transform from unparse. This
            # does not select a new implementation or mutate a product AST.
            results[path] = [_digest(astutil.stable_dump(astutil._PositiveComparisons().visit(node.test)))
                             for node in ast.walk(tree) if isinstance(node, ast.Assert)]
        elif phase == "asserted_subject":
            results[path] = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Assert):
                    statement = ast.get_source_segment(text, node)
                    if statement is None:
                        raise RuntimeError("owned assertion source segment is missing")
                    result = astutil.asserted_subject(statement)
                    results[path].append({"semantic_result_missing": result is None,
                                          "result": _digest(result) if result is not None else None})
        else:
            raise ValueError(f"unknown phase: {phase}")
    return results


def _worker(arguments) -> int:
    started = time.perf_counter()
    receipt = {"location": arguments.location, "terms": arguments.terms, "phase": arguments.phase}
    try:
        receipt.update(status="RETURNED", result=run_phase(arguments.location, arguments.terms, arguments.phase))
        code = 0
    except Exception as error:
        # Diagnostic capture only. This result is not fed to Checkwash as an
        # empty key, an empty AST, a PASS, or a claimed refusal-by-design.
        frames = traceback.extract_tb(error.__traceback__)
        receipt.update(
            status="EXCEPTION", exception_type=type(error).__name__, message=str(error),
            context=dict(CONTEXT), traceback=traceback.format_exc(),
            first_frames=[dict(file=f.filename, line=f.lineno, function=f.name) for f in frames[:12]],
            last_frames=[dict(file=f.filename, line=f.lineno, function=f.name) for f in frames[-12:]],
        )
        code = 1
    receipt["elapsed_seconds"] = time.perf_counter() - started
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return code


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True,
                            text=True, encoding="utf-8", timeout=30)
    return result.stdout.strip()


def _identity(engine_root: Path) -> dict[str, object]:
    import checkwash

    imported = Path(checkwash.__file__).resolve().parent
    expected = (engine_root / "src" / "checkwash").resolve()
    if imported != expected:
        raise RuntimeError(f"engine identity mismatch: imported {imported}, expected {expected}")
    files = {path.relative_to(imported).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
             for path in sorted(imported.rglob("*")) if path.is_file()
             and "__pycache__" not in path.parts and path.suffix not in (".pyc", ".pyo")}
    return {
        "engine_head": _git(engine_root, "rev-parse", "HEAD"),
        "engine_worktree_status": _git(engine_root, "status", "--porcelain"),
        "engine_package_path": str(imported), "engine_version": importlib.metadata.version("checkwash"),
        "engine_source_manifest": files,
        "python": sys.version, "executable": sys.executable, "platform": platform.platform(),
        "recursion_limit": sys.getrecursionlimit(),
        "github_sha": os.environ.get("GITHUB_SHA"), "github_run_id": os.environ.get("GITHUB_RUN_ID"),
        "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "collector_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "cases_sha256": hashlib.sha256(Path(__file__).with_name("reliability_r1_cases.py").read_bytes()).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--location", choices=LOCATIONS)
    parser.add_argument("--terms", type=int, choices=WIDTHS)
    parser.add_argument("--phase", choices=PHASES)
    parser.add_argument("--engine-root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.worker:
        if None in (args.location, args.terms, args.phase):
            parser.error("worker requires location, terms and phase")
        return _worker(args)
    if args.engine_root is None or args.output is None:
        parser.error("collector requires engine-root and output")
    report = {
        "purpose": "DIAGNOSTIC_CAPTURE_NOT_QUALIFICATION",
        "identity": _identity(args.engine_root.resolve()),
        "corpus": {f"{location}/{terms}": {name: {**_digest(data.decode("utf-8")),
                                                 "source_utf8": data.decode("utf-8")}
                    for name, data in snapshot(location, terms).items()}
                   for location in LOCATIONS for terms in WIDTHS},
        "per_phase_timeout_seconds": 30,
        "receipts": [],
    }
    infrastructure_errors = 0
    for terms in WIDTHS:
        for location in LOCATIONS:
            for phase in PHASES:
                key = {"location": location, "terms": terms, "phase": phase}
                command = [sys.executable, "-X", "utf8", str(Path(__file__).resolve()), "--worker",
                           "--location", location, "--terms", str(terms), "--phase", phase]
                try:
                    raw = subprocess.run(command, capture_output=True, text=True,
                                         encoding="utf-8", timeout=30)
                except subprocess.TimeoutExpired as error:
                    report["receipts"].append({**key, "status": "TIMEOUT", "seconds": 30,
                                               "stdout": _partial_output(error.stdout),
                                               "stderr": _partial_output(error.stderr)})
                    continue
                except OSError as error:
                    infrastructure_errors += 1
                    report["receipts"].append({**key, "status": "LAUNCH_FAILURE",
                                               "exception_type": type(error).__name__, "message": str(error)})
                    continue
                try:
                    receipt = json.loads(raw.stdout)
                    if not isinstance(receipt, dict):
                        raise ValueError("worker receipt is not an object")
                    if any(receipt.get(name) != value for name, value in key.items()):
                        raise ValueError("worker receipt does not match requested phase")
                    expected_code = 0 if receipt["status"] == "RETURNED" else 1
                    if receipt["status"] not in {"RETURNED", "EXCEPTION"} or raw.returncode != expected_code:
                        raise ValueError("inconsistent worker outcome")
                    receipt["worker_returncode"] = raw.returncode
                    receipt["worker_stderr"] = raw.stderr
                except (KeyError, TypeError, ValueError) as error:
                    infrastructure_errors += 1
                    receipt = {**key, "status": "INVALID_RECEIPT", "message": str(error),
                               "worker_returncode": raw.returncode, "stdout": raw.stdout, "stderr": raw.stderr}
                report["receipts"].append(receipt)
    report["summary"] = {status: sum(item["status"] == status for item in report["receipts"])
                         for status in ("RETURNED", "EXCEPTION", "TIMEOUT", "INVALID_RECEIPT", "LAUNCH_FAILURE")}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"purpose": report["purpose"], "summary": report["summary"]}, sort_keys=True))
    return 2 if infrastructure_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

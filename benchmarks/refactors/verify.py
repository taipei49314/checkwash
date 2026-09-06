"""Qualify execution of the historical legitimate-refactor corpus.

Each case ships production twice — correct and buggy — to check that both
test suites still distinguish that particular bug:

    BEFORE x PROD-GOOD -> passes      BEFORE x PROD-BUG -> FAILS
    AFTER  x PROD-GOOD -> passes      AFTER  x PROD-BUG -> FAILS

Checkwash then judges `BEFORE -> AFTER` with production unchanged. Catching one
seeded bug does not prove semantic equivalence of the tests: qualified mechanical
blocks still need human adjudication before being counted as false positives.

    python benchmarks/refactors/verify.py --output /new/path/receipt.json

20 of 30 blocked on 2026-08-13 (v0.1.25). See `README.md` for the families and
`results-2026-08-13.json` for that run.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import importlib.metadata
import json
import os
import pathlib
import platform
import re
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))

from checkwash import __version__  # noqa: E402
from checkwash.config import Config  # noqa: E402
from checkwash.contract import Contract  # noqa: E402
from checkwash.engine import FileChange, analyze  # noqa: E402
from checkwash.gitio.snapshot import search_source_mapping  # noqa: E402
from checkwash.pyenv import known_baseline  # noqa: E402

TODAY = datetime.date(2026, 1, 1)


def _text(value: bytes | None) -> str:
    return (value or b"").decode("utf-8", errors="replace")


def _run_tests(tests_dir: pathlib.Path, src_dir: pathlib.Path,
               timeout: float = 120) -> dict:
    """One subprocess supplies the exit, test counts and retained diagnostics.

    A nonzero exit alone never proves that the tests detected the bug. Pytest
    reports collection, setup and teardown problems as JUnit errors; even an
    assertion in setup is an error here, not a completed test failure.
    """
    env = {
        "PATH": "", "PYTHONPATH": str(src_dir.resolve()),
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", "C:\\Windows"),
    }
    with tempfile.TemporaryDirectory(prefix="refactor-pytest-") as temp:
        report = pathlib.Path(temp) / "junit.xml"
        command = [sys.executable, "-m", "pytest", "-q", "--no-header",
                   "-p", "no:cacheprovider", f"--junitxml={report}",
                   str(tests_dir.resolve())]
        observation = {
            "command": command, "cwd": str(tests_dir.parent.resolve()), "env": env,
            "exit_code": None, "status": "invalid", "reason": None,
            "counts": None, "stdout": "", "stderr": "", "junit_xml": None,
        }
        started = time.monotonic()
        try:
            proc = subprocess.run(command, capture_output=True,
                                  cwd=observation["cwd"], env=env, timeout=timeout)
            observation.update(exit_code=proc.returncode, stdout=_text(proc.stdout),
                               stderr=_text(proc.stderr))
        except subprocess.TimeoutExpired as exc:
            observation.update(reason="timeout", stdout=_text(exc.stdout),
                               stderr=_text(exc.stderr))
        except OSError as exc:
            observation["reason"] = f"launch_error: {exc}"
        observation["elapsed_seconds"] = time.monotonic() - started
        if report.exists():
            observation["junit_xml"] = report.read_text(encoding="utf-8")
        if observation["reason"] is not None:
            return observation
        try:
            suites = ET.fromstring(observation["junit_xml"] or "").findall("testsuite")
            if len(suites) != 1:
                raise ValueError("expected one pytest testsuite")
            suite = suites[0]
            counts = {key: int(suite.attrib[key])
                      for key in ("tests", "failures", "errors", "skipped")}
            cases = suite.findall("testcase")
            if (any(value < 0 for value in counts.values())
                    or counts["tests"] != len(cases)
                    or counts["failures"] != sum(c.find("failure") is not None for c in cases)
                    or counts["errors"] != sum(c.find("error") is not None for c in cases)
                    or counts["skipped"] != sum(c.find("skipped") is not None for c in cases)):
                raise ValueError("inconsistent pytest counts")
            observation["counts"] = counts
        except (ET.ParseError, KeyError, ValueError) as exc:
            observation["reason"] = f"missing_or_invalid_report: {exc}"
            return observation
        code = observation["exit_code"]
        if counts["tests"] == 0 or counts["errors"] or counts["skipped"]:
            observation["reason"] = "no_tests_errors_or_skips"
        elif code == 0 and counts["failures"] == 0:
            observation["status"] = "pass"
        elif code == 1 and counts["failures"] > 0:
            observation["status"] = "test_failure"
        else:
            observation["reason"] = "exit_does_not_match_test_result"
        return observation


def _rel(p: pathlib.Path, base: pathlib.Path) -> str:
    return str(p.relative_to(base)).replace("\\", "/")


def judge(before_root: pathlib.Path, after_root: pathlib.Path, src: pathlib.Path):
    paths = sorted(
        {_rel(p, before_root) for p in before_root.rglob("*.py")}
        | {_rel(p, after_root) for p in after_root.rglob("*.py")}
    )
    changes = []
    for path in paths:
        b, a = before_root / path, after_root / path
        changes.append(
            FileChange(
                path=path,
                status=("modified" if b.exists() and a.exists()
                        else "added" if a.exists() else "deleted"),
                before=b.read_bytes() if b.exists() else None,
                after=a.read_bytes() if a.exists() else None,
            )
        )
    head = {f"src/{_rel(p, src)}": p.read_bytes() for p in src.rglob("*.py")}
    # The synthetic repository is the full AFTER tree plus unchanged src.
    # Keep the legacy production lookup separate: its missing keys cannot
    # prove that a root/sibling assertion helper is absent.
    snapshot = {f"src/{_rel(p, src)}": p.read_bytes()
                for p in src.rglob("*") if p.is_file()}
    snapshot.update({_rel(p, after_root): p.read_bytes()
                     for p in after_root.rglob("*") if p.is_file()})
    _ir, findings, verdict = analyze(
        changes, Config(), Contract(), [], TODAY,
        known_modules=known_baseline() | {"app"},  # the corpora ship app.* by construction
        head_reader=head.get,
        head_searcher=lambda needles: [
            p for p, d in sorted(head.items()) if any(n.encode() in d for n in needles)
        ],
        root_reader=snapshot.get,
        root_searcher=lambda needles: search_source_mapping(snapshot, needles),
    )
    return verdict, sorted({f"{f.rule}/{f.severity}" for f in findings if not f.allowlisted})


def _sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest(root: pathlib.Path) -> dict:
    files = {_rel(p, root): _sha(p) for p in sorted(root.rglob("*"))
             if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"}
    digest = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    return {"sha256": digest, "files": files}


def _git(*args: str) -> str | None:
    proc = subprocess.run(["git", *args], cwd=ROOT, capture_output=True)
    return _text(proc.stdout).strip() if proc.returncode == 0 else None


def _inputs(cases_root: pathlib.Path, expected: pathlib.Path) -> dict:
    return {"engine_source": _manifest(ROOT / "src"),
            "verifier_sha256": _sha(pathlib.Path(__file__)),
            "corpus": _manifest(cases_root), "expected_sha256": _sha(expected)}


def _utc() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cases_root", type=pathlib.Path, nargs="?", default=HERE / "cases")
    parser.add_argument("--expected", type=pathlib.Path, default=HERE / "expected.json")
    parser.add_argument("--output", type=pathlib.Path, required=True,
                        help="new receipt path; existing files are never overwritten")
    args = parser.parse_args(argv)
    cases_root, out = args.cases_root.resolve(), args.output.resolve()
    expected_path = args.expected.resolve()
    if out.exists():
        parser.error(f"receipt already exists: {out}")
    document = json.loads(expected_path.read_text(encoding="utf-8"))
    expected = document.get("cases") if isinstance(document, dict) else None
    if not isinstance(expected, dict) or not expected:
        parser.error("--expected must contain a nonempty 'cases' object")
    if any(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", name) is None for name in expected):
        parser.error("case names must start with an ASCII letter/digit and contain only letters, digits, '_' or '-'")
    inputs = _inputs(cases_root, expected_path)
    receipt = {
        "schema_version": 1, "status": "incomplete", "started_at": _utc(),
        "engine_version": __version__, "analysis_date": TODAY.isoformat(),
        "source": {"commit": _git("rev-parse", "HEAD"),
                   "tree": _git("rev-parse", "HEAD^{tree}"),
                   "worktree_status": _git("status", "--porcelain")},
        "environment": {"python": sys.version, "executable": sys.executable,
                        "platform": platform.platform(),
                        "pytest": importlib.metadata.version("pytest")},
        "cases_root": str(cases_root), "expected_path": str(expected_path),
        "inputs": inputs, "expected_case_count": len(expected),
    }
    rows = []
    cases = {p.name: p for p in cases_root.iterdir() if p.is_dir()}
    for name in sorted(set(cases) | set(expected)):
        case = cases_root / name
        good, bug = case / "PROD-GOOD" / "src", case / "PROD-BUG" / "src"
        bt, at = case / "BEFORE" / "tests", case / "AFTER" / "tests"
        row = {"case": name, "valid": False, "checks": {}, "observations": {},
               "verdict": None, "rules": [], "error": None}
        try:
            missing = [str(p) for p in (good, bug, bt, at) if not p.is_dir()]
            if missing:
                raise ValueError(f"missing case directories: {missing}")
            for label, tests, src, wanted in (
                ("before_good_pass", bt, good, "pass"),
                ("before_bug_fail", bt, bug, "test_failure"),
                ("after_good_pass", at, good, "pass"),
                ("after_bug_fail", at, bug, "test_failure"),
            ):
                observation = _run_tests(tests, src)
                row["observations"][label] = observation
                row["checks"][label] = observation["status"] == wanted
            row["verdict"], row["rules"] = judge(case / "BEFORE", case / "AFTER", good)
            row["why"] = (case / "WHY.txt").read_text(encoding="utf-8").strip()
            row["valid"] = all(row["checks"].values()) and name in expected
        except Exception as exc:
            row["error"] = f"{type(exc).__name__}: {exc}"
        rows.append(row)
        valid, verdict, rules = row["valid"], row["verdict"], row["rules"]
        mark = ("QUALIFIED-BLOCK" if verdict == "block" else "silent") if valid else "INVALID"
        print(f"{case.name:26s} {mark:15s} {','.join(rules) or '-'}", flush=True)

    valid = [r for r in rows if r["valid"]]
    qualified_blocks = [r for r in valid if r["verdict"] == "block"]
    unchanged = inputs == _inputs(cases_root, expected_path)
    complete = bool(rows) and len(valid) == len(rows) and set(cases) == set(expected) and unchanged
    blocks = sum(r["verdict"] == "block" for r in rows)
    print(f"\noracle qualification: {len(valid)}/{len(rows)}")
    print(f"mechanical blocks:    {blocks}/{len(rows)}")
    print(f"qualified blocks:     {len(qualified_blocks)} (human adjudication pending)")
    if not complete:
        print("INCOMPLETE: the whole cohort has not qualified.")
    receipt.update(
        status="complete" if complete else "incomplete", finished_at=_utc(),
        inputs_unchanged=unchanged, cases=rows,
        summary={"total_cases": len(rows), "valid_cases": len(valid),
                 "invalid_cases": len(rows) - len(valid),
                 "qualified_block_observations": len(qualified_blocks),
                 "all_case_blocks": blocks,
                 "missing_cases": sorted(set(expected) - set(cases)),
                 "unexpected_cases": sorted(set(cases) - set(expected))},
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(receipt, indent=1, ensure_ascii=False) + "\n")
    print(f"receipt: {out} ({receipt['status']})", flush=True)
    return 0 if complete else 2


if __name__ == "__main__":
    raise SystemExit(main())

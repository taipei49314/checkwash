"""Replay the legitimate-refactor corpus. Any block here is a false positive.

Each case ships production twice — correct and buggy — so the claim "this
refactor is legitimate" is checked rather than asserted:

    BEFORE x PROD-GOOD -> passes      BEFORE x PROD-BUG -> FAILS
    AFTER  x PROD-GOOD -> passes      AFTER  x PROD-BUG -> FAILS

Both sides genuinely catch the bug. greenwash then judges `BEFORE -> AFTER` with
production unchanged, and **a block is a false positive by construction** —
there is no adjudication to argue about.

    python benchmarks/refactors/verify.py

20 of 30 blocked on 2026-08-13 (v0.1.25). See `README.md` for the families and
`results-2026-08-13.json` for that run.
"""

from __future__ import annotations

import datetime
import json
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))

from greenwash.config import Config  # noqa: E402
from greenwash.contract import Contract  # noqa: E402
from greenwash.engine import FileChange, analyze  # noqa: E402
from greenwash.pyenv import known_baseline  # noqa: E402

TODAY = datetime.date(2026, 1, 1)


def _passes(tests_dir: pathlib.Path, src_dir: pathlib.Path) -> bool:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--no-header",
         "-p", "no:cacheprovider", str(tests_dir)],
        capture_output=True,
        cwd=str(tests_dir.parent),
        env={
            "PATH": "",
            "PYTHONPATH": str(src_dir),
            "PYTHONDONTWRITEBYTECODE": "1",
            "SYSTEMROOT": "C:\\Windows",
        },
        timeout=120,
    )
    return proc.returncode == 0


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
    _ir, findings, verdict = analyze(
        changes, Config(), Contract(), [], TODAY,
        known_modules=known_baseline(),
        head_reader=head.get,
        head_searcher=lambda needles: [
            p for p, d in sorted(head.items()) if any(n.encode() in d for n in needles)
        ],
    )
    return verdict, sorted({f"{f.rule}/{f.severity}" for f in findings if not f.allowlisted})


def main() -> int:
    cases_root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "cases"
    rows = []
    for case in sorted(cases_root.iterdir()):
        if not case.is_dir() or not (case / "BEFORE").exists():
            continue
        good, bug = case / "PROD-GOOD" / "src", case / "PROD-BUG" / "src"
        bt, at = case / "BEFORE" / "tests", case / "AFTER" / "tests"
        checks = {
            "before_good_pass": _passes(bt, good),
            "before_bug_fail": not _passes(bt, bug),
            "after_good_pass": _passes(at, good),
            "after_bug_fail": not _passes(at, bug),
        }
        valid = all(checks.values())
        verdict, rules = judge(case / "BEFORE", case / "AFTER", good)
        rows.append({
            "case": case.name, "valid": valid, "checks": checks,
            "verdict": verdict, "rules": rules,
            "why": (case / "WHY.txt").read_text(encoding="utf-8").strip().replace("\n", " ")[:200],
        })
        mark = ("FALSE-POSITIVE" if verdict == "block" else "silent") if valid else "INVALID"
        print(f"{case.name:26s} {mark:15s} {','.join(rules) or '-'}", flush=True)

    valid = [r for r in rows if r["valid"]]
    fps = [r for r in valid if r["verdict"] == "block"]
    print(f"\nverified refactors: {len(valid)}/{len(rows)}")
    print(f"stayed silent:      {len(valid) - len(fps)}/{len(valid)}")
    print(f"FALSE POSITIVES:    {len(fps)}")
    for r in fps:
        print(f"  !! {r['case']}  ({', '.join(r['rules'])})")
    out = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else HERE / "results-latest.json"
    out.write_text(json.dumps(rows, indent=1, ensure_ascii=False) + "\n",
                   encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

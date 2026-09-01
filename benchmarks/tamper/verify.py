"""Replay the informed-adversarial tamper corpus. Nothing here is taken on trust.

Each case is a bug that was never fixed and a test suite that went green anyway:

    cases/<name>/src/app/<mod>.py      production, identical on both sides
    cases/<name>/before/tests/...      the suite as it was — must FAIL
    cases/<name>/after/tests/...       the suite after tampering — must PASS
    cases/<name>/WHY.txt               what the bug is, and why AFTER proves nothing

A case is only counted if pytest agrees: BEFORE red, AFTER green. Production is
never part of the diff greenwash judges — it is what the head snapshot holds —
so every case carries `NO_PROD_CHANGE_IN_DIFF` by construction.

    python benchmarks/tamper/verify.py

An **escape** is a verified case that greenwash does not block. There were 28 of
40 on 2026-08-13 (v0.1.25); see THREATMODEL 91, and `results-2026-08-13.json`
for the per-case verdicts that run produced.
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

from checkwash.config import Config  # noqa: E402
from checkwash.contract import Contract  # noqa: E402
from checkwash.engine import FileChange, analyze  # noqa: E402
from checkwash.pyenv import known_baseline  # noqa: E402

TODAY = datetime.date(2026, 1, 1)


def _pytest(case: pathlib.Path, side: str) -> bool:
    """True when the suite on this side passes."""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--no-header",
         "-p", "no:cacheprovider", str(case / side)],
        capture_output=True,
        cwd=str(case),
        env={
            "PATH": "",
            "PYTHONPATH": str(case / "src"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "SYSTEMROOT": "C:\\Windows",
        },
        timeout=120,
    )
    return proc.returncode == 0


def _rel(p: pathlib.Path, base: pathlib.Path) -> str:
    return str(p.relative_to(base)).replace("\\", "/")


def judge(case: pathlib.Path) -> tuple[str, list[str]]:
    before_dir, after_dir = case / "before", case / "after"
    paths = sorted(
        {_rel(p, before_dir) for p in before_dir.rglob("*.py")}
        | {_rel(p, after_dir) for p in after_dir.rglob("*.py")}
    )
    changes = []
    for path in paths:
        b, a = before_dir / path, after_dir / path
        changes.append(
            FileChange(
                path=path,
                status=("modified" if b.exists() and a.exists()
                        else "added" if a.exists() else "deleted"),
                before=b.read_bytes() if b.exists() else None,
                after=a.read_bytes() if a.exists() else None,
            )
        )
    head = {f"src/{_rel(p, case / 'src')}": p.read_bytes()
            for p in (case / "src").rglob("*.py")}
    _ir, findings, verdict = analyze(
        changes, Config(), Contract(), [], TODAY,
        known_modules=known_baseline() | {"app"},  # the corpora ship app.* by construction
        head_reader=head.get,
        head_searcher=lambda needles: [
            p for p, d in sorted(head.items()) if any(n.encode() in d for n in needles)
        ],
    )
    return verdict, sorted({f"{f.rule}/{f.severity}" for f in findings if not f.allowlisted})


def main() -> int:
    rows = []
    for case in sorted((HERE / "cases").iterdir()):
        if not case.is_dir():
            continue
        valid = (not _pytest(case, "before")) and _pytest(case, "after")
        verdict, rules = judge(case)
        rows.append({
            "case": case.name,
            "valid": valid,
            "verdict": verdict,
            "rules": rules,
            "why": (case / "WHY.txt").read_text(encoding="utf-8").strip(),
        })
        mark = "ESCAPE" if valid and verdict != "block" else ("blocked" if valid else "INVALID")
        print(f"{case.name:22s} {mark:8s} {','.join(rules) or '-'}")

    valid = [r for r in rows if r["valid"]]
    escapes = [r for r in valid if r["verdict"] != "block"]
    print(f"\nverified cases: {len(valid)}/{len(rows)}")
    print(f"blocked:        {len(valid) - len(escapes)}/{len(valid)}")
    print(f"escapes:        {len(escapes)}")
    (HERE / "results-latest.json").write_text(
        json.dumps(rows, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

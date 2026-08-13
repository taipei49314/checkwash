"""Both corpora, one number each, greenwash verdict only.

Recall (tamper): how many attacks block. Precision (refactors): how many honest
refactors stay silent. A5 is the same defect seen from both sides, so a change
that improves one and wrecks the other is not an improvement — this prints them
together so that cannot be reported separately by accident.

The pytest provenance for both corpora is established by their own verify.py
scripts; this replays only the verdict, which is what moves.
"""

from __future__ import annotations

import datetime
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from greenwash.config import Config  # noqa: E402
from greenwash.contract import Contract  # noqa: E402
from greenwash.engine import FileChange, analyze  # noqa: E402
from greenwash.pyenv import known_baseline  # noqa: E402

TODAY = datetime.date(2026, 1, 1)


def _rel(p: pathlib.Path, base: pathlib.Path) -> str:
    return str(p.relative_to(base)).replace("\\", "/")


def verdict(before_root: pathlib.Path, after_root: pathlib.Path, src: pathlib.Path):
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
    _ir, findings, v = analyze(
        changes, Config(), Contract(), [], TODAY,
        known_modules=known_baseline() | {"app"},  # the corpora ship app.* by construction
        head_reader=head.get,
        head_searcher=lambda needles: [
            p for p, d in sorted(head.items()) if any(n.encode() in d for n in needles)
        ],
    )
    return v, sorted({f.rule for f in findings if not f.allowlisted})


def main() -> int:
    tamper = json.loads((HERE / "tamper" / "expected.json").read_text(encoding="utf-8"))["cases"]
    blocked, newly, regressed = 0, [], []
    for name, spec in tamper.items():
        case = HERE / "tamper" / "cases" / name
        v, rules = verdict(case / "before", case / "after", case / "src")
        if v == "block":
            blocked += 1
            if spec["verdict"] != "block":
                newly.append((name, rules))
        elif spec["verdict"] == "block":
            regressed.append((name, rules))

    refac = json.loads((HERE / "refactors" / "expected.json").read_text(encoding="utf-8"))["cases"]
    fps, fixed, new_fps = 0, [], []
    for name, spec in refac.items():
        case = HERE / "refactors" / "cases" / name
        v, rules = verdict(case / "BEFORE", case / "AFTER", case / "PROD-GOOD" / "src")
        if v == "block":
            fps += 1
            if not spec["blocks"]:
                new_fps.append((name, rules))
        elif spec["blocks"]:
            fixed.append(name)

    print(f"RECALL   tamper attacks blocked : {blocked}/{len(tamper)}   (was 12)")
    print(f"PRECISION honest refactors blocked: {fps}/{len(refac)}   (was 20)")
    if newly:
        print(f"\nnewly caught ({len(newly)}):")
        for n, r in newly:
            print(f"  + {n:20s} {','.join(r)}")
    if regressed:
        print(f"\nRECALL REGRESSION ({len(regressed)}):")
        for n, r in regressed:
            print(f"  - {n:20s} {','.join(r) or 'no findings'}")
    if fixed:
        print(f"\nfalse positives fixed ({len(fixed)}):")
        for n in fixed:
            print(f"  + {n}")
    if new_fps:
        print(f"\nNEW FALSE POSITIVES ({len(new_fps)}):")
        for n, r in new_fps:
            print(f"  ! {n:26s} {','.join(r)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

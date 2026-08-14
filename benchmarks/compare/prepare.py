"""Materialize the two decoy worktrees the comparison harness consumes.

    python prepare.py <out_dir>
    # writes <out_dir>/arm-b/  (adversarial diffs applied)
    #        <out_dir>/arm-a/  (natural / honest diffs applied)

Then run.py against those two directories. This script does not invoke
swarm and does not invent a score.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DECOY = HERE.parent / "decoy"
MAKE_TASKS = DECOY / "make_tasks.py"
ARM_B = DECOY / "arm-adversarial-2026-07-30.json"
ARM_A = DECOY / "arm-natural-2026-07-30.json"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True)


def _arm_tasks(arm_path: Path) -> list[str]:
    arm = json.loads(arm_path.read_text(encoding="utf-8"))
    return [run["task"] for run in arm["runs"]]


def _rmtree(path: Path) -> None:
    def _onerror(func, p, _exc):
        os.chmod(p, stat.S_IWRITE)
        func(p)

    shutil.rmtree(path, onerror=_onerror)


def _copy_wanted(src: Path, dest: Path, names: list[str]) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for name in names:
        shutil.copytree(src / name, dest / name)


def _apply_arm(arm_path: Path, tasks_root: Path) -> list[str]:
    arm = json.loads(arm_path.read_text(encoding="utf-8"))
    failed: list[str] = []
    for run in arm["runs"]:
        name = run["task"]
        repo = tasks_root / name
        if not (repo / ".git").exists():
            failed.append(f"{name}: missing-repo")
            continue
        diff = run.get("diff") or ""
        if not diff.strip():
            failed.append(f"{name}: no-diff")
            continue
        _git(repo, "checkout", "--", ".")
        _git(repo, "clean", "-qfd")
        patch = repo / "_compare.patch"
        with open(patch, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(diff if diff.endswith("\n") else diff + "\n")
        applied = _git(repo, "apply", "--whitespace=nowarn", "_compare.patch")
        patch.unlink(missing_ok=True)
        if applied.returncode != 0:
            err = (applied.stderr or b"").decode("utf-8", "replace").strip()
            failed.append(f"{name}: patch-failed {err[:160]}")
    return failed


def prepare(out_dir: str) -> int:
    out = Path(out_dir)
    if not MAKE_TASKS.is_file():
        print(f"error: {MAKE_TASKS} missing — run from a greenwash checkout", file=sys.stderr)
        return 2
    for arm in (ARM_B, ARM_A):
        if not arm.is_file():
            print(f"error: recorded arm missing: {arm}", file=sys.stderr)
            return 2

    out.mkdir(parents=True, exist_ok=True)
    arm_b = out / "arm-b"
    arm_a = out / "arm-a"
    staging = out / "_tasks"
    if staging.exists():
        _rmtree(staging)
    staging.mkdir()
    proc = subprocess.run(
        [sys.executable, str(MAKE_TASKS), str(staging)],
        capture_output=True,
    )
    if proc.returncode != 0:
        print(proc.stderr.decode("utf-8", "replace"), file=sys.stderr)
        print("error: make_tasks.py failed", file=sys.stderr)
        return 2

    # make_tasks.py now materializes later probe tasks too. This comparison
    # is the 2026-07-30 12+12; extra unpatched repos would be scored as
    # cheats or honest fixes they are not.
    for dest in (arm_b, arm_a):
        if dest.exists():
            _rmtree(dest)
    _copy_wanted(staging, arm_b, _arm_tasks(ARM_B))
    _copy_wanted(staging, arm_a, _arm_tasks(ARM_A))
    _rmtree(staging)

    failed_b = _apply_arm(ARM_B, arm_b)
    failed_a = _apply_arm(ARM_A, arm_a)
    if failed_b or failed_a:
        for row in failed_b:
            print(f"arm-b {row}", file=sys.stderr)
        for row in failed_a:
            print(f"arm-a {row}", file=sys.stderr)
        return 2

    n_b = sum(1 for p in arm_b.iterdir() if (p / ".git").exists())
    n_a = sum(1 for p in arm_a.iterdir() if (p / ".git").exists())
    print(f"prepared {n_b} arm-b repos and {n_a} arm-a repos under {out}")
    print(f"next: python {HERE / 'run.py'} <python> <swarm-cli.js> {arm_b} {arm_a} <out.json>")
    return 0


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: python prepare.py <out_dir>", file=sys.stderr)
        print("See benchmarks/compare/README.md", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(prepare(sys.argv[1]))


if __name__ == "__main__":
    main()

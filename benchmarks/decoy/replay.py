"""Replay a recorded decoy arm against the current engine.

    python benchmarks/decoy/make_tasks.py <dir>
    python benchmarks/decoy/replay.py <arm.json> <dir>

Each arm records the diff a real agent produced. Replaying asks the only
question that matters between releases: **does the current build still block
what it blocked, and still pass what it passed?**

This lived in a scratch directory and ran because the author remembered to run
it. That is the same "green because it did not run" shape this project keeps
finding in its own gates, one level up — so it is in the repository now and
`tests/gates/test_recorded_arms.py` runs it in CI.

Verdicts come from the real CLI, not from calling `analyze()` directly: a
replay that takes a shortcut past the command users run can pass while the
command is broken.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass


@dataclass
class Result:
    task: str
    status: str  # "ok" | "missing-repo" | "no-diff" | "patch-failed"
    verdict: str | None = None  # "block" | "pass" | "engine_error"
    rules: tuple[str, ...] = ()


def _git(repo: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", repo, *args], capture_output=True)


def replay_arm(arm_path: str, tasks_root: str, python: str | None = None) -> list[Result]:
    python = python or sys.executable
    with open(arm_path, encoding="utf-8") as fh:
        arm = json.load(fh)
    # Pinned so a date-sensitive rule (allowlist expiry) cannot make the replay
    # drift with the calendar.
    env = {**os.environ, "GREENWASH_TODAY": "2026-07-30", "PYTHONUTF8": "1"}

    results: list[Result] = []
    for run in arm["runs"]:
        name = run["task"]
        repo = os.path.join(tasks_root, name)
        if not os.path.isdir(repo):
            results.append(Result(name, "missing-repo"))
            continue

        _git(repo, "checkout", "--", ".")
        _git(repo, "clean", "-qfd")

        diff = run.get("diff") or ""
        if not diff.strip():
            results.append(Result(name, "no-diff"))
            continue

        patch = os.path.join(repo, "_replay.patch")
        with open(patch, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(diff if diff.endswith("\n") else diff + "\n")
        applied = _git(repo, "apply", "--whitespace=nowarn", "_replay.patch")
        os.remove(patch)
        if applied.returncode != 0:
            results.append(Result(name, "patch-failed"))
            continue

        proc = subprocess.run(
            [python, "-m", "checkwash", "check", "--repo", repo, "--format", "json"],
            capture_output=True,
            env=env,
        )
        try:
            payload = json.loads(proc.stdout.decode("utf-8", "replace"))
            verdict = payload["verdict"]
            rules = tuple(sorted({f"{f['rule']}:{f['severity']}" for f in payload["findings"]}))
        except (json.JSONDecodeError, KeyError):
            verdict, rules = "engine_error", ()

        results.append(Result(name, "ok", verdict, rules))
        _git(repo, "checkout", "--", ".")
        _git(repo, "clean", "-qfd")
    return results


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    results = replay_arm(sys.argv[1], sys.argv[2])
    blocked = sum(1 for r in results if r.verdict == "block")
    passed = sum(1 for r in results if r.verdict == "pass")
    other = [r for r in results if r.status != "ok"]
    for r in results:
        detail = ",".join(r.rules) or "-"
        print(f"  {r.task:24} {r.status:12} {r.verdict or '':6} {detail}")
    print(f"\nblocked={blocked} passed={passed} not-replayed={len(other)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

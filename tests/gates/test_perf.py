"""Performance gate (agent-READ-ONLY thresholds).

greenwash is pitched as safe to run on a stop-hook, so the budget is part of
the contract, not a nice-to-have. Thresholds are generous enough not to be
flaky on a loaded laptop while still catching an order-of-magnitude
regression.

Budget checks compare the **median of three runs** against an unchanged
threshold (maintainer decision, 2026-09-01). One measurement was one roll of
the CI runner's dice: the macOS leg produced 4.01s on a docs-only commit
whose engine bytes had measured green hours earlier — a 60% swing with no
code change is infrastructure variance, and a gate that fails on it is the
flaky-check defect this repo has already had to fix three times elsewhere.
The median absorbs a single bad slice; a real regression still fails all
three runs.
"""

import datetime
import statistics
import time

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze

TODAY = datetime.date(2026, 1, 1)

# Measured ~0.2s and ~0.7s on the dev laptop after the O(1) source-segment
# and symbol-fingerprint fixes; budgets leave headroom for loaded CI without
# letting an order-of-magnitude regression back in.
BUDGET_LARGE_DIFF_S = 1.0  # 3000-line test diff
BUDGET_MANY_FILES_S = 2.5  # 500 changed files


def _test_module(n_tests: int, weaken: bool) -> bytes:
    lines = ["from app.calc import compute", ""]
    for i in range(n_tests):
        lines.append("")
        lines.append(f"def test_case_{i}():")
        lines.append(f"    value = compute({i})")
        if weaken and i % 3 == 0:
            lines.append("    assert value is not None")
        else:
            lines.append(f"    assert value == {i * 2}")
    return ("\n".join(lines) + "\n").encode()


def _median_elapsed(changes, runs: int = 3):
    """(median wall seconds, findings of the first run) for `analyze`.

    The engine is deterministic, so every run does identical work; only the
    runner's weather differs, which is exactly what the median removes.
    """
    samples = []
    first_findings = None
    for _ in range(runs):
        start = time.perf_counter()
        _ir, findings, _verdict = analyze(changes, Config(), Contract(), [], TODAY)
        samples.append(time.perf_counter() - start)
        if first_findings is None:
            first_findings = findings
    return statistics.median(samples), first_findings


def test_large_single_diff_within_budget():
    before = _test_module(600, weaken=False)
    after = _test_module(600, weaken=True)
    changes = [FileChange("tests/test_big.py", "modified", before, after)]
    elapsed, findings = _median_elapsed(changes)
    assert findings, "sanity: the weakened assertions must be found"
    assert elapsed < BUDGET_LARGE_DIFF_S, (
        f"median {elapsed:.2f}s over {BUDGET_LARGE_DIFF_S}s budget"
    )


def test_many_files_within_budget():
    changes = []
    for i in range(500):
        before = _test_module(4, weaken=False)
        after = _test_module(4, weaken=(i % 10 == 0))
        changes.append(FileChange(f"tests/test_mod_{i:03d}.py", "modified", before, after))
    elapsed, _findings = _median_elapsed(changes)
    assert elapsed < BUDGET_MANY_FILES_S, (
        f"median {elapsed:.2f}s over {BUDGET_MANY_FILES_S}s budget"
    )


@pytest.mark.parametrize("size", [200_000, 1_000_000])
def test_pathological_file_does_not_hang(size):
    # Attacker-controlled head side: a huge single-expression file must
    # degrade visibly, not wedge the engine.
    payload = ("x = " + "+".join(["1"] * (size // 2)) + "\n").encode()
    changes = [FileChange("app/generated.py", "modified", b"x = 1\n", payload)]
    start = time.perf_counter()
    ir, _findings, _verdict = analyze(changes, Config(), Contract(), [], TODAY)
    elapsed = time.perf_counter() - start
    assert elapsed < 10.0, f"{elapsed:.2f}s — pathological input must not hang"
    assert ir is not None

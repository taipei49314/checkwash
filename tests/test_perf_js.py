"""Performance of a large JS/TS test file through the engine (#235).

Parsing a JS/TS test file was quadratic in its size. `Bindings.scope()`
scanned every scope on each call, `_callback_body` rebuilt every token's
start position on each call, each unit re-read every arrow function in the
file, and each candidate call searched all the text before it for `new`.
Through `analyze()`, which parses both sides of the diff, a 2,600-line file
of 200 units took 28 s (a loaded cloud container, 2026-10-06), and 1.2 s
once each of those is linear.

`tests/gates/test_perf.py` measures Python diffs only. This budget sits
between the two timings with room on either side, as
`tests/test_perf_git.py`'s does: generous enough for a slow runner, tight
enough that the quadratic parse fails it. As the gate does, it compares the
median of three runs, so one slow slice of a shared runner does not fail it
(maintainer decision, 2026-09-01).
"""

import datetime
import statistics
import time

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze

BUDGET_LARGE_JS_FILE_S = 8.0
UNITS = 200


def _test_file(units: int) -> str:
    """One `describe` of `units` tests, each ten lines with an arrow function and one `expect`."""
    lines = ['import { describe, it, expect } from "vitest";', 'import { total } from "../src/total";', "",
             'describe("billing", () => {']
    for unit in range(units):
        lines.append(f'  it("unit {unit}", () => {{')
        lines.extend(f"    const v{k} = total([1, 2, 3]).map((x) => x * {k});" for k in range(10))
        lines.append(f"    expect(v0[0]).toBe({unit});")
        lines.append("  });")
    lines.append("});")
    return "\n".join(lines) + "\n"


def test_a_large_js_test_file_is_analysed_within_budget():
    before = _test_file(UNITS)
    after = before.replace("expect(v0[0]).toBe(0);", "expect(v0[0]).toBeDefined();", 1)
    change = FileChange("tests/billing.test.ts", "modified", before.encode(), after.encode())
    timings = []
    for _run in range(3):
        started = time.perf_counter()
        _ir, findings, verdict = analyze([change], Config(), Contract(), [], datetime.date(2026, 1, 1))
        timings.append(time.perf_counter() - started)
    # The work was done: the one weakened assertion of 200 units is found.
    assert verdict == "block"
    assert [(f.rule, f.unit) for f in findings] == [("ASSERT_WEAKENED", "unit 0")]
    elapsed = statistics.median(timings)
    assert elapsed < BUDGET_LARGE_JS_FILE_S, (
        f"a {before.count(chr(10))}-line JS test file took a median {elapsed:.2f} s "
        f"(budget {BUDGET_LARGE_JS_FILE_S} s): {timings}")

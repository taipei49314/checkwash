# Gates (agent-READ-ONLY)

Cumulative acceptance gates. A milestone may not advance while any earlier
gate is red. Gate *scripts and thresholds* are owned by the human maintainer;
coding agents may run them, never edit them (AGENTS.md).

## M0 gates (current)

1. Determinism: double-run byte-identical (tests/test_determinism.py) and
   cross-process byte-identical under fresh hash seeds (tests/e2e).
2. Cross-platform: the `byte-compare` CI job — every OS × Python emits
   byte-identical corpus findings.
3. Golden corpus: all `.gwcase` fixtures green (tests/test_cases_runner.py).
4. Rename safety: renamed/moved tests never read as deletions
   (tests/test_diffalign.py, moved_test_file_neg.gwcase).

## Deferred (M1+)

- Perf gate: 3000-line diff cold-start p95 < 800 ms; large-monorepo worktree
  check p95 < 1 s. Lands with the benchmark harness in M1.
- FP gate: high-severity findings on ≤ 3% of a 300-commit human-PR corpus.
- Recall gate vs decoy-task cheat corpus (incl. side-by-side run against
  swarm-orchestrator on the same corpus — see design addendum 2026-07-29).

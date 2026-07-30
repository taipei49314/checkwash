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

## M1 gates (current)

5. Perf (`tests/gates/test_perf.py`): 3000-line test diff under 1 s,
   500 changed files under 2.5 s, pathological single-expression files must
   degrade rather than hang. These caught a real 4.1 s regression the day
   they were written.
6. Every registered detector ships pos and neg `.gwcase` fixtures
   (`tests/test_detector_coverage.py`).

## Deferred

- FP gate: high-severity findings on ≤ 3% of a 300-commit human corpus,
  measured with `greenwash sweep` over ≥ 5 external repos. Harness done,
  population runs not yet performed — see benchmarks/README.md.
- Recall gate vs the decoy-task cheat corpus (incl. side-by-side run against
  swarm-orchestrator on the same corpus — see design addendum 2026-07-29).

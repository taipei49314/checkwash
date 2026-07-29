# STATE — read this first when taking over

Updated: 2026-07-29

## Where we are

M0 (pipeline + first detectors) **functionally complete**, first commit.

- Pipeline: gitio (range + worktree modes, rename-aware) → stdlib-ast Python
  frontend → alignment (qualname → shingle-fingerprint → backstop) → IR →
  detectors → gating → term/JSON reports. Zero runtime dependencies.
- Detectors live: `ASSERT_REMOVED`, `ASSERT_WEAKENED`, `TEST_DISABLED`.
- Gating: E1 (symbol-level, triviality-filtered), E2 (oracle_freeze),
  D1 (repair evidence), D2 (moved assertions/units), D3 (allowlist).
- CLI: `greenwash check [BASE..HEAD] | --format json | --emit-ir`,
  `greenwash allow FP --reason`. Exit codes 0/1/2.
- Tests: 38 green (13 .gwcase golden + frontend/alignment/determinism units
  + subprocess e2e incl. allow roundtrip). CI matrix + cross-OS byte-compare
  workflow written (unverified until pushed to GitHub).

## Decisions in force

- SPEC.md frozen (rule IDs, lattice, alignment params, severity=warn+escalators).
- DECISIONS: D-001 stdlib ast (not tree-sitter) for v0.1; D-002 uniform
  severity philosophy; D-003 exemptions visible-not-locked.
- Positioning: **no "first/only" claims** — swarm-orchestrator, AgentLint,
  mumei exist; we compete on blockable-by-default precision, zero-LLM,
  zero-execution, determinism. See README "Prior art" + design addendum.

## Next (M1)

1. Remaining 9+1 detectors (TOLERANCE_LOOSENED first — lattice already
   records epsilons; then SNAPSHOT_CODE_COCHANGE, EXPECTED_VALUE_HARDCODED,
   BROAD_EXCEPT_ADDED, SUPPRESSION_ADDED, CI_WORKFLOW_TOUCHED,
   GUARDRAIL_TOUCHED + EXEMPTION_ADDED flow, IMPORT_UNRESOLVED, SCOPE_DRIFT,
   HIDDEN_UNICODE). Each PR ships pos≥5/neg≥5 fixtures.
2. Decoy-task cheat corpus (30 tasks, run real agents, harvest diffs).
3. FP corpus: 300 human commits from 5 OSS repos incl. "fix flaky" commits.
4. Perf gate scripts under tests/gates/.

## Known limitations (documented, not hidden)

- Non-Python prod changes conservatively defuse E1 (THREATMODEL #4).
- `assertRaises`/custom helpers unclassified (fail-safe null strength).
- Worktree snapshot is read-per-file, not the incremental index plan yet.

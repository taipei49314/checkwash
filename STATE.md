# STATE — read this first when taking over

Updated: 2026-07-30 (post red-team round 2 — M0 audit complete)

## Where we are

M0 **complete, both adversarial review rounds absorbed**. 18 findings across
two rounds, every one reproduced by an independent skeptic before it was
accepted, every one fixed with a regression fixture or e2e test.

Round 2 (bypass + robustness lenses): 12 findings, 0 rejected.

1. **E1 was diff-global** — one dead prod constant (or a statement reorder,
   or an edit to an unrelated function) demoted every oracle finding to warn.
   Repair evidence is now symbol-relevant with one-hop call following
   (DECISIONS D-004); honest and indirect repairs still pass/warn.
2. Test class renamed out of pytest's `Test*` rule → whole class silently dead.
3. conftest.py never analysed → one hook could skip the entire suite.
4. Early `return` in a test body, and deleted `parametrize` rows.
5. D2 laundering via a sacrificial `@pytest.mark.skip` test.
6. `assert f(x) == f(x)` self-comparison kept EXACT_VALUE.
7. Worktree/hook mode still laundered test relocation (round-1 fix was
   range-mode only) — the mode the attacker actually runs under.
8. `BASE...HEAD` silently downgraded to two dots → base-branch commits
   disarmed E1 on every open PR.
9. JSON written in the ambient locale: not UTF-8, lossy for non-ASCII.
10. Case-only rename invisible in worktree mode (disk read-back).
11. RecursionError from a nesting bomb → traceback + exit 1 (reads as block).
12. Malformed base config/allowlist swallowed silently (fail-open), and
    `greenwash allow` could itself write invalid TOML from a Windows path.

Round 1 (correctness lens): 6 findings, all fixed:

1. cp1252 pipe crash → false exit-1 "block" (glyph fallback + encode-safe
   stdout; e2e tests force PYTHONIOENCODING=cp1252).
2. Class-level skip / module pytestmark / self.skipTest invisible to
   TEST_DISABLED (marker inheritance in frontend).
3. `git mv` of a test file out of collection laundered TEST_DISABLED
   (rename expansion + collectability rule; relocated bytes don't defuse E1).
4. normalize_text erased whitespace inside string literals → fake "moved
   verbatim" D2 de-escalation (string-aware normalizer).
5. Order-fallback pairing absorbed deleted assertEqual into added
   assertRaises → ASSERT_REMOVED suppressed (compatibility rule).
6. assertListEqual→assertEqual style no-op flagged as weakening (uniform
   container-literal upgrade across the *Equal family and plain `==`).

- Pipeline: gitio (range + worktree modes, rename-aware) → stdlib-ast Python
  frontend → alignment (qualname → shingle-fingerprint → backstop) → IR →
  detectors → gating → term/JSON reports. Zero runtime dependencies.
- Detectors live: `ASSERT_REMOVED`, `ASSERT_WEAKENED`, `TEST_DISABLED`.
- Gating: E1 (symbol-level, triviality-filtered), E2 (oracle_freeze),
  D1 (repair evidence), D2 (moved assertions/units), D3 (allowlist).
- CLI: `greenwash check [BASE..HEAD] | --format json | --emit-ir`,
  `greenwash allow FP --reason`. Exit codes 0/1/2.
- Tests: 71 green (30 .gwcase golden + frontend/alignment/determinism units
  + 19 subprocess e2e: allow roundtrip, cp1252 pipes, rename laundering in
  both modes, three-dot ranges, UTF-8 JSON, recursion bomb, malformed TOML).
  CI matrix + cross-OS byte-compare workflow written (unverified until
  pushed to GitHub).

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

- Opaque (non-Python / unparseable / deleted) prod changes still defuse E1
  (THREATMODEL #4). Touching an unrelated *Python* prod file no longer does.
- Repair evidence follows one call hop; deeper indirection fails toward
  flagging (THREATMODEL #5).
- `assertRaises`/custom helpers unclassified (fail-safe null strength).
- Worktree snapshot is read-per-file, not the incremental index plan yet.
- `_conftest_unit` watches a curated control list; exotic collection tricks
  are not covered.

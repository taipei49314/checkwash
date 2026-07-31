# STATE — read this first when taking over

Updated: 2026-07-30 (M1 measured: FP corpus + decoy corpus both run)

## Where we are

**M1 substantially complete.** 14 detectors implemented and fixture-covered,
perf gate green, and *both* benchmark corpora have actually been run — the
numbers live in `benchmarks/RESULTS.md` and `benchmarks/decoy/README.md`,
generated from the harnesses, never hand-typed. 116 tests green.

### The measurements, and what they cost

**False positives** — 1800 human commits across six OSS repos greenwash had
never seen. **40/1800 = 2.22%**, every repo under 4%, gate is ≤3%. Full
progression and what moved each step: `benchmarks/README.md`. The 48
oracle-rule blocks from round one were each triaged by an independent agent
reading the real diff: 14 spec-correct, 34 fixable, 0 unclear.

**Recall** — 12 decoy bug-fix tasks, real agents, two arms. Natural condition:
0 of 12 agents touched a test (12 true negatives; an honest result that cuts
against the loudest version of the pitch, recorded as such). Adversarial
condition: **0 of 12 caught on first measurement**, 12 of 12 after fixes.

The 0/12 was worth the entire exercise. Root cause: pytest's own untracked
`__pycache__/*.pyc` counted as an unanalysable production change and granted
repair evidence, disarming every escalation. Any user who had ever run their
tests was protected by nothing. Two more gaps fell out of the same run: "mild
weakening" excused exact→`approx(abs=0.01)`, and rewriting an expected literal
without changing its shape produced no finding at all (now
`EXPECTED_VALUE_CHANGED`).

M1 detectors added on top of M0's three: `TOLERANCE_LOOSENED` (kind-aware
direction, Decimal-only), `EXPECTED_VALUE_HARDCODED` (base-literal filtered),
`SNAPSHOT_CODE_COCHANGE`, `BROAD_EXCEPT_ADDED`, `SUPPRESSION_ADDED`,
`CI_WORKFLOW_TOUCHED` (+weakened-command escalator), `GUARDRAIL_TOUCHED`,
`IMPORT_UNRESOLVED` (vendored stdlib snapshot; off without a manifest),
`SCOPE_DRIFT` (glob-only), `HIDDEN_UNICODE`.

Two things M1 found by itself, worth knowing:
- `greenwash sweep` over greenwash's own history flagged a **real false
  positive** on commit 93e7ed1 — a test asserting `== "pass"` matched a prod
  constant `"pass"` that had always existed. Fixed by excluding base-side
  literals; fixture `hardcoded_existing_value_neg.gwcase`.
- The new perf gate failed at **4.1 s** for a 3000-line diff. Root causes:
  `ast.get_source_segment` re-splitting the file per call, and symbol
  fingerprinting via unparse→parse→dump on every symbol including test files.
  Now **0.21 s** (DECISIONS D-007).

## M0 (complete, both adversarial review rounds absorbed)

18 findings across two rounds, every one reproduced by an independent skeptic
before it was accepted, every one fixed with a regression fixture or e2e test.

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
- Tests: 116 green (66 .gwcase golden + frontend/alignment/determinism units
  + 19 subprocess e2e + perf and detector-coverage gates). CI matrix +
  cross-OS byte-compare workflow written (unverified until pushed to GitHub).

## Decisions in force

- SPEC.md frozen (rule IDs, lattice, alignment params, severity=warn+escalators).
- DECISIONS: D-001 stdlib ast (not tree-sitter) for v0.1; D-002 uniform
  severity philosophy; D-003 exemptions visible-not-locked.
- Positioning: **no "first/only" claims** — swarm-orchestrator, AgentLint,
  mumei exist; we compete on blockable-by-default precision, zero-LLM,
  zero-execution, determinism. See README "Prior art" + design addendum.

## M2 (adapters) — done

CLI `hook-json` format + `greenwash hook install --agent claude-code`
(idempotent, merges into existing .claude/settings.json), pre-commit hook
definition (`.pre-commit-hooks.yaml`), composite GitHub Action
(`action/action.yml`), and a CI `dogfood` job that runs greenwash on its own
PRs. 121 tests green; self-check on HEAD~3..HEAD is clean.

## Next

1. **Side-by-side against swarm-orchestrator** on both corpora, publishing
   both columns including the cases where it wins. Not started.
2. **Widen the decoy corpus**: more tasks, harder and more underspecified
   bugs, weaker models, retry pressure. Twelve tasks with one attempt each is
   a smoke test with teeth, not a benchmark with error bars — decoy/README
   says so and the claim must not outrun it.
3. **M2 adapters**: pre-commit, GitHub Action, Claude Code stop-hook, then
   dogfood on this repo's own PRs.
4. Fixture corpus toward pos≥5/neg≥5 per detector as real cases arrive; the
   coverage gate currently enforces ≥1 positive per detector and ≥10
   negatives overall.

## Working rule that has earned its place

Every measurement so far found a defect the code review did not: the sweep
found a false positive in greenwash's own history, the perf gate failed on
arrival at 4.1 s, and the decoy corpus found a bug that reduced the tool to
catching nothing. Build the harness before trusting the behaviour.

Its sharpest instance: after the M1 self-review I predicted the eight fixes
would bring httpx's 6.67% down. Re-running the sweep moved httpx by **zero**
commits — the real cause was that repair evidence never reached through an
unchanged intermediate module. Reasoning about the code produced a confident
wrong answer; re-running the measurement produced the right one. Re-measure
after every change, including the ones that "obviously" work.

## Known limitations (documented, not hidden)

- Opaque (non-Python / unparseable / deleted) prod changes still defuse E1
  (THREATMODEL #4). Touching an unrelated *Python* prod file no longer does.
- Repair evidence follows one call hop; deeper indirection fails toward
  flagging (THREATMODEL #5).
- `assertRaises`/custom helpers unclassified (fail-safe null strength).
- Worktree snapshot is read-per-file, not the incremental index plan yet.
- `_conftest_unit` watches a curated control list; exotic collection tricks
  are not covered.

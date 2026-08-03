# STATE — read this first when taking over

Updated: 2026-08-02 (second independent audit closed; still private)

## The number that matters right now

Two independent audits have now been run against this repository. The first
(an outside reader) found 11 defects in three passes, then ~20 more in a
fourth. The second (six parallel lenses, each finding reproduced with the real
CLI, each then re-run from scratch by a skeptic told to refute it) made 16
claims and **all 16 survived refutation**.

Between them, one of those audits reopened a bypass this file had listed as
Closed for days: `ast` reports `col_offset` in UTF-8 **bytes**, greenwash
treated it as characters, and a single CJK character anywhere on an assertion
line garbled every extracted source string — which silently disabled the
self-comparison check and every other text comparison in the tool.

The project's own review has still never found a defect of that class before
an outside pass did. Plan accordingly: the discovery rate has not levelled
off, and "we reviewed it carefully" has a measured track record here of zero.

## Known and unfixed, top of the next round

Adjudicating the 45 blocks turned up one false-positive class that is NOT
fixed, with two real examples in the corpus:

- **Skip conditions that name a module constant are invisible to D6.**
  `@pytest.mark.skipif(WIN, ...)` (click b761eda) and
  `@pytest.mark.xfail(PY_3_14_PLUS, ...)` (attrs 7373d88) are both bona fide
  compatibility gates. D6 only inspects `skipif` — never `xfail` — and only
  when the marker *text* literally contains `sys.version_info` / `sys.platform`
  / `platform.` / `os.name`. A constant defined three lines up in the same file
  defeats it. The fix is to resolve module-level constants from the file the
  frontend has already parsed, and to extend D6 to non-strict `xfail`.
  Measured cost of leaving it: 2 of 45 blocks, ~4.4%.

Also unfixed and now measured rather than assumed: **7.2% of the corpus
(130/1800) receives the blanket opaque-change exemption** — a production file
greenwash cannot read suppresses escalation for the entire diff
(THREATMODEL #4). That is the share of the pass rate that is not analysis. It
is the single largest hole in the tool and it is a design choice, not a bug,
but "2.50% block rate" should be read next to it.

## Why this is public again

Made public by the owner on 2026-08-03, after v0.1.2. What changed since the
75-minute public window on 2026-08-02 is not confidence — it is that several
things which used to be assertions are now checked by something that can fail:

- the `byte-compare` job is green on all nine matrix legs, and was verified
  green rather than assumed;
- the `dogfood` job now actually executes `action/action.yml` on every push. It
  never had; for the whole life of the project it reported "skipped" because it
  was gated to pull requests in a repo that has never had one;
- THREATMODEL's **Closed** column is machine-checked — each row names the
  fixture pinning it, and the suite fails if a row has nothing behind it;
- the benchmark numbers are regenerable from a clone, the sweeps are tracked
  with their corpus boundary commits, and `make_results.py` refuses to pair a
  sweep with an adjudication that does not describe it.

**What has NOT changed, and you should weigh it.** The defect-discovery rate
has not levelled off. On 2026-08-03 a second independent audit made sixteen
claims and a separate skeptic refuted none of them — including one that had
silently reopened a bypass this file listed as Closed. Two audits, roughly
thirty real defects, and the project's own review has still never found a
defect of that class before an outside pass did.

So read the labels here accordingly. "Closed" now means a test pins it, not
that it is safe. The most useful thing you can do with this repository is break
it: THREATMODEL keeps a public bypass list and every report becomes a fixture.

## Why it was private before

It was public for a few hours on 2026-08-02 and was taken back to private by
the owner, deliberately, because the defect-discovery rate had not levelled
off: a reader auditing the public repo found **eleven** real problems in three
passes, and the project found **none** of them on its own initiative in that
window. Every one was checkable from inside — a red CI job, a stale tag, a
contradiction between two files in the same directory.

The code is in good shape. The *process that decides when it is ready* is
not, and shipping under that process is what needs to stop. Do not flip this
public again on a judgement that it "looks done"; flip it when something
other than that judgement says so.

## Where we are

Tagged **v0.1.2**, CI green on every leg including `byte-compare`. M0–M3 are
done: 15 detectors, both benchmark corpora run, four adapters, the offline
`greenwash demo`, and the launch docs. Numbers live in
`benchmarks/RESULTS.md` and `benchmarks/decoy/README.md`, generated from the
harnesses, never hand-typed; the test count lives in the README and is pinned
by `tests/test_packaging.py` so it cannot drift.

**Not done:** the asciinema cast (needs a human at a terminal), and PyPI —
`pipx install greenwash` does not work yet and the README says so plainly.

### If you are taking over, read this part

> Anything this file, the README, or a commit message calls **done** is an
> unverified claim until you re-run the thing that proves it. The harnesses
> exist for that. Use them before you believe any of this.

That is not a general caution, it is the specific failure this project keeps
having. The eleven defects below were all found by an outside reader; the
project's own self-audits, run repeatedly and in good faith, produced zero of
them until a direction was pointed at. Self-review here reliably confirms
what it already believes. Treat "I checked it" as weaker evidence than a
green gate, and a green gate as weaker evidence than someone hostile looking.

### The measurements, and what they cost

**False positives** — 1800 human commits across six OSS repos greenwash had
never seen. **45/1800 = 2.50%**, every repo at or under 5%. Full
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
PRs. (121 tests green *at that milestone*; see README for the current count.)

## M3 (launch prep) — in progress

Done:
- **swarm-orchestrator comparison** (`benchmarks/compare/`): both tools detect
  all 12 decoy cheats; greenwash 12/12 block + 0/12 false block, swarm's
  structural signal 11/12 false-detect on honest fixes (hence advisory). Caveat
  documented loudly: Python is swarm's secondary ecosystem, no LLM judge. Not a
  "we win" — a measured statement of the discrimination difference.
- **60-second demo** (`examples/invoice/`): reproducible, and pinned by
  `tests/test_demo_reproduces.py` so it can never silently rot.

- **`greenwash demo`**: replays 8 real tampering cases + 1 honest fix, fully
  offline, from cases packaged in the wheel (`src/greenwash/demo_cases/`).
  Pinned by `tests/test_demo_command.py`, including that the cases load via
  `importlib.resources` — the exact path a pipx install reads them by.

M3 adversarial review of the newest code (PACKAGE_REPAIR, triviality filter,
self-comparison) found 3 defects, all reproduced and fixed (DECISIONS D-010,
THREATMODEL 23-25). The FP sweep was re-run after the fixes and held at
40/1800 = 2.22% — tightening PACKAGE_REPAIR closed the bypass at zero
precision cost on this corpus. README/CONTRIBUTING/docs carry the real
numbers; launch copy is in docs/launch.md.

M3 is done and shipped. Published private on 2026-08-02, then made public on
the owner's instruction after the pre-public audit; v0.1.1 is the current tag.

### What a reader of the public repo found (2026-08-02)

Eight defects, all reproduced before being accepted, all fixed. Recorded
because the pattern matters more than the list: every one was something the
project could have checked itself and had not.

1. **CI had been red on `byte-compare` since before v0.1.0** — the job that
   proves the README's byte-identical claim — and nobody looked. Cause:
   `tools/emit_corpus.py` wrote through text-mode stdout, so Windows emitted
   CRLF. The product path was always correct; the *proving harness* was the
   liar. The local "verified across 3.11/3.12/3.13" check was worthless
   because all three ran on Windows: three Pythons, one OS.
2. **Set literals were hash-seed dependent** (`repr({"a","b"})`), leaking
   non-determinism into finding messages and the IR. Now canonicalised.
3. **Three different test counts** in three documents. Now collected from the
   suite and pinned by a test.
4. **RESULTS.md still said the decoy corpus did not exist** while
   benchmarks/README said it was run — stale text hardcoded in the generator.
5. **"2.2% false positives" was the wrong name.** A block is not
   automatically a mistake. All 40 blocks of the current build were
   re-adjudicated: 24 false positive (1.33%), 16 legitimate policy block
   (0.89%), 0 unclear.
6. **The README pinned `@v0.1.0`, a tag two fixes behind main** — visitors
   read the fixed docs and installed the unfixed engine. `test_packaging.py`
   now diffs the pinned tag's `src/` against the working tree and fails.
7. **The CI matrix covered 3.11–3.12 while the README claimed 3.11–3.13.**
   3.13 added to the matrix rather than shrinking the claim.
8. **STATE.md itself described a world that no longer existed** — stale test
   counts, "repo is private", "flip to public" still listed as to-do.

## Later

- Record the asciinema cast; publish to PyPI.
- **Adjudicate the block split more than once.** The 1.33% is one agent, one
  pass, no inter-rater agreement. Two or three independent passes with
  agreement reported would make it solid; RESULTS.md says so.

- Widen the decoy corpus: more tasks, harder/underspecified bugs, weaker
  models, retry pressure. 12 tasks × 1 attempt is a smoke test with teeth.
- Fixture corpus toward pos≥5/neg≥5 per detector.

## Determinism, verified — and how the first verification fooled me

On 2026-07-31 I checked the byte-identical claim (SPEC §8) across Python
3.11.15 / 3.12.13 / 3.13.14, got an identical artifact on all three, and wrote
here that it was "the first measurement in this project that confirmed a claim
rather than breaking it."

**That was wrong, and the way it was wrong is the useful part.** All three
interpreters ran on Windows, so all three got the same CRLF translation from
`tools/emit_corpus.py`'s text-mode stdout. Three Pythons, one OS — the varying
axis I actually needed was the one I did not vary. Meanwhile the CI job that
*did* vary it had been failing for days, and I did not look at it. A green
local check plus a red ignored gate reads as confirmation and is the opposite.

Now: the emitter writes bytes, and the claim is proved on every push by the
`byte-compare` job across nine matrix legs (Linux/macOS/Windows × 3.11/3.12/
3.13). All nine emitted `d8ff2848…` on the run that fixed it. Trust that job,
not a local run.

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

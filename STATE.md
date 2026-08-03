# STATE — read this first when taking over

Updated: 2026-08-04 (v0.1.7: the probe arm drew blood twice, and the split has three judges)

## The 2026-08-04 round (v0.1.7): probes, escapes, and inter-rater agreement

Two campaigns ran in parallel, both from the STATE leverage list.

**The decoy probe arm.** Six new tasks aim a real agent (codex) at the
de-escalators that hold at warn by design. Result: **two escapes in six
attempts**, neither via the route its task baited —

- `STRICT = True` → `False` behind an existing `if not STRICT:
  pytest.skip(...)`. One line. Guard text unchanged, no marker event, test
  silenced. This was THREATMODEL 54, deferred over a fingerprint-migration
  fear that turned out to be unfounded: the fix evaluates *unchanged* guards
  under each side's resolved constants ("ran somewhere before, skips
  everywhere now" → TEST_DISABLED) and touches no identity, so recorded
  allowlists survive. Row 59, pinned.
- an autouse conftest fixture monkeypatching the test module's binding of
  the function under test — prod and tests byte-identical, every assertion
  checking a stand-in, with a comment *boasting* that the API stays
  unchanged. New rule `CONFTEST_PATCHES_PROD`: conftest `monkeypatch.setattr`
  aimed at first-party code or `request.module` is an oracle event;
  stdlib/third-party stubbing stays silent. Row 60, pinned. The cleverest
  cheat any agent has produced against this tool.

Both closures verified the full way: fixtures red-then-green, the recorded
escape diffs re-checked (both block), sweep re-run — **blocked set and
finding distributions byte-identical across all 1800 commits, so both new
rules cost zero on human history** — and the natural-condition arm on the
same six tasks came back 6/6 honest fixes, 0/6 touched a test, 0/6 false
blocks. The two untaken baits (D8 dead-symbol escort, D9 dependency-bump
escort) are now evidence about reachability, not an argument. Standing rule
from D-023: every future "open by design" residual gets a probe task, not a
paragraph.

**Inter-rater agreement.** Two additional raters re-adjudicated all 35
blocks blind. Pairwise agreement 94.3/91.4/91.4%, Fleiss' kappa **0.844**,
four commits with any disagreement, zero three-way splits. Published
categories are now the majority verdict — which flipped exactly one commit
(rich 48293cde88 → false positive, 2–1), moving the headline split to
**20 FP (1.11%) / 15 spec-correct (0.83%)**. All three raters' verdicts
ship in benchmarks/, and RESULTS states the measured agreement where the
"one judge, no second opinion" apology used to be. The floor analysis
survives re-rating: its flask/httpx counterexamples are unanimous or
2-1-retained; only the rich receipt weakened, and the mechanism it backed
stays dead via flask alone (D-024).

## The 2026-08-03 fifth round (v0.1.6): the biggest hole, measured and narrowed

THREATMODEL #4's blanket — any unreadable prod change suppresses E1 for the
whole diff — covered 130/1800 corpus commits (7.2% of the pass rate resting
on a blind spot, not analysis). An audit of what those files actually were
found the blanket mostly covered things nobody needed to read: mkdocs.yml
alone on 24 commits, .readthedocs on 13, `.pyi` stubs, flask's
requirements/*.in, example-app pyprojects, GitHub metadata — and five
commits whose "opaque" change was a deleted Python file fully parseable on
the base side.

Three cuts (D-022): role fixes where a role fits (`**/pyproject.toml` → ci,
`requirements*.in` → lockfile, bare `README` → docs); an explicit inert
list for prod-role files that cannot change runtime behaviour (stubs, docs
config, repo metadata — deliberately short, misses stay opaque, fails
toward flagging); deleted parseable Python analysed from its base side
instead of excused. What still grants the blanket is what greenwash
genuinely cannot read: other-language code, templates, data files,
unparseable Python.

Result: **opaque 130 → 45 (2.5%), and the blocked set did not move by one
commit** — 35 before, the same 35 after, zero new blocks, decoy 12/12 and
honest arm 0/12 both held. Every removed exemption had been protecting a
commit that passed on its own merits, which is the best possible outcome:
the number was fat, not load-bearing, and now the 2.5% that remains is the
real measure of the blind spot.

## The number that matters right now

**35/1800 = 1.94% block rate; adjudicated false positive 19/1800 = 1.06%.**
Down from 2.50% / 1.67% across three precision rounds in one day. Ten
adjudicated false positives cleared, zero commits newly blocked, every
spec-correct block still blocks (now 16 — one verdict moved *into* that
column on evidence), decoy corpus 12/12 on every re-run.

Two catches this day matter more than the clears. The first cut of the
feature-removal credit cleared two adjudicated-correct blocks and was
tightened before commit (v0.1.4 section). Then the v0.1.5 duplicate search
overturned an adjudication verdict in the tool's favour: a commit judged
"false positive — every deleted unit reappears in the same diff" turned out
to have deleted one real oracle that reappears *nowhere* (`git grep` at that
head is the proof), so the verdict — not the tool — was wrong. The
measurement apparatus is now catching errors on both sides of itself.

## The 2026-08-03 third round (v0.1.5): DUPLICATE_REMAINS

click 1103c5cac2 deleted `test_confirm_repeat`; an identical copy had lived
in an untouched file since the parent commit. No credit could see outside
the diff. Now D10 does: one batched `git grep -l -F "def <leaf>("` at head
(filesystem walk in worktree mode, the `=== head: ===` map in fixtures), at
most eight candidate files parsed, and the survivor must hash-match the
deleted body exactly, sit in a collectable untouched test file, and be live
under the D2 rule — a skipped or edited survivor earns nothing (THREATMODEL
58, both costume variants pinned). Not a multiset: an identical live
survivor keeps running the oracle no matter how many copies were deleted.

Same round, the honest misses: the flask rename FP (53b8f08218) stays
blocked — the real rewrite shrinks six strong assertions to two, and the
name-relation loosening drafted for it was deleted rather than shipped
without a payoff (the mass discipline is what closed bypass 45). And
a391797d00 was re-adjudicated false_positive → spec_correct as above.

## The 2026-08-03 fourth round: the residual 19 are a floor, and now it's proved

The attack on the remaining 19 ran its recon and closed without shipping
code — the correct outcome, reached the correct way. Three candidate
mechanisms (expectation edits explained by same-unit setup changes; weakened
assertions excused by surviving anchors or new real assertions; two-hop
prod-caller evidence) were each **killed at design time by a spec-correct
counterexample of the identical syntactic shape**: flask d98eb69a35 and rich
48293cde88 kill the first, httpx fc84f7f6eb and b5addb64f0 the second, httpx
4f6edf36e9 the third. Same shape on both sides of the adjudication; the
separator is semantic equivalence, which THREATMODEL #1/#7 deliberately
exclude. The full pairing is written up in benchmarks/README ("The floor").

What this means for the next taker: **do not spend another precision round
on the 19 without changing the design class.** The options are a semantic
layer (execution or a model — a different product), or reviewed
allowlisting as the last mile (which the per-fingerprint exemption flow
already provides). The corpus-side leverage that remains is elsewhere:
widen the decoy corpus (recall side), inter-rater agreement on the
adjudication (the split is still one judge's call), the 7.2% opaque
exemption (the largest hole in the tool), and the deferred guard-identity
migration (THREATMODEL 54).

Two independent audits have been run against this repository. The first
(an outside reader) found 11 defects in three passes, then ~20 more in a
fourth. The second (six parallel lenses, each finding reproduced with the real
CLI, each then re-run from scratch by a skeptic told to refute it) made 16
claims and **all 16 survived refutation**.

The project's own review has still never found a defect of that class before
an outside pass did. Plan accordingly: the discovery rate has not levelled
off, and "we reviewed it carefully" has a measured track record here of zero.

## The 2026-08-03 second round (v0.1.4): the false-positive list, class by class

The 28 adjudicated false positives decomposed into mechanisms; three were
fixable on principle this round:

- **Relocation credits died on any marker.** `disabled = bool(markers)` gated
  D2 moved-assertions, D5 restructure mass, and the split/rename budget — so
  a test carried across files *together with its own `skipif(WIN)`* was dead
  on arrival (click a391797d00 / 700798252a). Live now means "no markers, or
  D6-qualified compat gates only", evaluated with the same resolved
  constants. And a disappeared unit's whole normalized body is its own move
  credit (`moved_unit_hashes`, multiset, spent once), because an
  assertion-less smoke test has nothing in the D2 multiset to prove it moved.
- **D8 `PROD_SYMBOL_REMOVED`**: feature removal is the honest twin of test
  deletion (attrs 74007f67d2, httpx 59914c7690, starlette 856c904a6d /
  b133ab45ad). Removal shapes of TEST_DISABLED only, deleted-existing
  symbols only, connected by the test file's imports (before-side imports
  for a deleted file) or the `test_<module>` filename convention —
  b133ab45ad reaches its module only through
  `importlib.import_module("starlette.status")`, a string no static import
  list sees.
- **D9 `DEPENDENCY_DRIFT`**: expectation literals tracking a manifest change
  (httpx 0.28's compact JSON separators rewrote three starlette
  expectations: 100f05a66b, 5ccbc62175). Scoped to EXPECTED_VALUE_CHANGED
  exactly like PACKAGE_REPAIR.

**The catch that matters more than the clears.** The first cut of D8 counted
*any* vanished symbol — and symbol collection records assignments inside
function bodies, so a rewritten function "deleted" its old locals, and the
credit cleared **two adjudicated spec-correct blocks** (click b7e5fd4cc7 /
c3535905c7: fish completion rewritten, its multiline-help test deleted,
coverage genuinely gone — the headline cheat, laundered by touching the
function under repair). It was caught by the red-zone check — diffing every
sweep delta against the adjudication categories before accepting it — and a
deletion now counts only when no prefix of its qualname survives. Both
commits block again; four corpus FPs that had been riding the same loose
signal (attrs f520d9a89f, flask 06ea505ce2 / 53b8f08218, starlette
02b6ed7b18) went back to blocking with them, and the FP count is reported
with them in it. Every future de-escalator gets this reconciliation pass.

Verification: 6 of the round's first 11 fixtures failed on the v0.1.3 build
(the rest pin behavior that must not change); 14 new fixtures total, 223
tests green; nine targets re-checked live; decoy 12/12 twice (before and
after the tightening); the full sweep re-run twice with the red-zone
reconciliation on both; dogfood on the working tree: pass.

Still adjudicated-FP and still blocked, named honestly: deleted-duplicate
tests (click 1103c5cac2, and a391797d00's residual unit) need head-tree
enumeration greenwash does not do yet; the rewrite-class (private→public API
test rewrites, subject changes with in-diff compensation — most of httpx's
remainder) is the next design round.

## The 2026-08-03 round (v0.1.3): D6 constant resolution

The previous STATE said the fix was to "resolve module-level constants from
the file the frontend has already parsed" because "a constant defined three
lines up in the same file defeats it". **That diagnosis was wrong, and wrong
in a way that matters**: in *both* real cases the constant is imported —
click's `WIN` from `click/_compat.py`, a file **not in the diff at all**, and
attrs' `PY_3_14_PLUS` from `src/attr/_compat.py`, which happened to be in the
diff. attrs also had two blocking findings this file never mentioned:
imperative `pytest.xfail("...")` calls under `if PY_3_14_PLUS and not slots:`,
a spelling D6 had no channel for whatsoever. Read this file's diagnoses the
way it tells you to read its "done" claims.

What shipped, all of it fixture-pinned (10 new .gwcase + 2 e2e):

- **Constant resolution, three tiers**: same-file module constants → names
  imported from files in the diff → files read from the head snapshot
  (`gitio.read_base_file` in range/sweep mode, the working tree in worktree
  mode; `=== head: path ===` in .gwcase). The engine resolves eagerly into
  `FileIR.constants` so gating stays a pure function of the IR. Bounded
  (≤24 entries, ≤8 head reads), cycle-guarded, collision→unevaluable,
  shadowed-name→unevaluable; every failure direction is toward flagging.
- **Non-strict `xfail(cond)`** earns D6 like `skipif(cond)`; `strict=True`
  earns nothing (it inverts the oracle, it doesn't skip it).
- **Imperative skips carry their guards**: the frontend records the enclosing
  `if` conjunction (`not (...)` for else-branches) on the Marker (`guard`
  field, deliberately NOT part of identity/fingerprints so recorded allowlist
  entries survive). D6 evaluates the guard as the condition. Soundness: the
  recorded guard is a subset of the real conjuncts, so if the recorded part
  is false somewhere the real condition is false there too.
- **Always-true tightened from `is True` to truthy**: `skipif(FLAG)` with
  `FLAG = True` and a compat token smuggled into `reason=` used to *earn*
  credit (unresolvable → MAYBE → discriminates); it is now resolved, judged
  always-true, and denied. Cost on the 1800-commit corpus: zero.

Verification chain, in order: 7 of 10 new fixtures failed on the old build →
all 209 green after → both corpus commits re-checked live with the real CLI
(click high=0 warn=2, attrs high=0 warn=6, verdict pass, COMPAT_GATE visible
on every de-escalated finding) → full 6-repo sweep re-run against the same
recorded corpus pins, twice (second run to stamp the right version; block
sets byte-identical across runs) → decoy corpus replayed from the preserved
worktrees, 12/12 still block → dogfood on this round's own diff: pass.

## Known and unfixed, top of the next round

Still unfixed and still measured: **7.2% of the corpus (130/1800) receives
the blanket opaque-change exemption** — a production file greenwash cannot
read suppresses escalation for the entire diff (THREATMODEL #4). Unchanged by
this round, still the single largest hole, still a design choice rather than
a bug; read "2.39% block rate" next to it.

New gaps this round *created or documented*, none with corpus cost today:

- **Guard edits on imperative skips produce no finding.** The guard is not
  part of marker identity (kept out so existing allowlist fingerprints
  survive), so `if version < X: pytest.skip()` → `if True: pytest.skip()` is
  invisible to TEST_DISABLED — it was invisible before this round too, but
  now it is invisible *by documented choice*. Fixing it means putting the
  guard into the identity, which changes fingerprints and needs an allowlist
  migration story. Owner call.
- `skipif(condition=X)` keyword form and `unittest.skipIf` earn no credit
  (0 corpus hits; conservative FP risk, not a bypass).
- The MAYBE residual extends to guards: `if helper("sys.platform"): skip()`
  earns credit exactly as `skipif(helper("sys.platform"))` always has. Same
  class, same documented trade (refusing unevaluables blocked honest gates).

The 28 remaining adjudicated false positives are the next precision target;
their per-commit reasoning is in `benchmarks/RESULTS.md`.

## Owner actions: applied 2026-08-03 on the owner's explicit instruction

The v0.1.3 code round left SPEC.md / THREATMODEL.md / DECISIONS.md untouched
per AGENTS.md and queued three edits here. The owner then instructed they be
applied, which is the sanctioned path for those files. Applied in the
follow-up commit:

1. **SPEC.md §5, D6 row** rewritten to match the shipped semantics: skipif /
   non-strict xfail / guarded imperative skips, constants resolved up to the
   head snapshot, always-true means truthy, unresolvables stay unknown,
   strict xfail earns nothing.
2. **THREATMODEL**: "known and accepted" item 6 narrowed (constants are no
   longer among the unseen parts); rows **52–53** added as Closed (the two
   constant-blind FP shapes, pinned by `bypass:` claims in the
   `compat_gate_*_pos` fixtures, enforced by `test_threatmodel_pinned`); row
   **54** added as **Open** — guard edits on imperative skips produce no
   event, kept open deliberately because guard-in-identity would change
   fingerprints and invalidate recorded allowlists.
3. **DECISIONS D-019** records the whole design: eager engine-side
   resolution carried in the IR, token filter over resolved expressions,
   truthy always-true, xfail strictness stance, guard-not-in-identity with
   THREATMODEL 54 as its named cost, and `Marker.guard` + `FileIR.constants`
   as additive IR v1 fields without a version bump.

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

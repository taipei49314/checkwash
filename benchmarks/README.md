# Benchmarks — what is measured, and what is not

Two corpora back the "blockable by default" claim. This file says plainly
which numbers exist and which do not.

**What "reproducible" means here, precisely.** The decoy corpus is fully
reproducible from this clone: `decoy/make_tasks.py` materializes all twelve
repos, and the recorded agent diffs replay against them. The false-positive
corpus is six third-party repositories, which this clone cannot contain; the
sweep JSONs under `sweeps/` are tracked, and each records the newest and
oldest commit of the range it covered, so you can clone those six projects,
check out the recorded commit, and re-run the sweep to compare. Without that
pin the numbers were not checkable by anyone but the author, which was a fair
criticism.

`make_results.py` will refuse to publish the false-positive decomposition
unless the adjudication file describes exactly the set of commits the sweep
blocked — it names the unadjudicated and stale commits instead. Pairing a
fresh sweep with a stale adjudication produced a number that looked measured
and described a different population.

## 1. False-positive corpus (human-authored history)

The number that decides whether greenwash survives contact with a real team:
**how often does it block a commit a human wrote and reviewed?**

```bash
greenwash sweep HEAD --limit 300 --repo /path/to/some/python/repo
```

It reports `block_rate` plus per-rule/severity counts and dumps every blocked
commit with its high-severity findings, so each can be triaged by hand.

**Status: run.** Six active OSS Python projects (flask, httpx, attrs, click,
rich, starlette), 300 consecutive non-merge commits each — 1800 commits none
of which greenwash saw during development. Results in `RESULTS.md`, generated
by `make_results.py` so the document cannot drift from the measurement.

**A block rate is not a false-positive rate.** Some blocked commits really do
drop oracle coverage with nothing visible replacing it — the tool doing its
documented job, to be allowlisted by a reviewer. So the blocks are adjudicated
commit by commit, and `RESULTS.md` publishes the decomposition:

| measure | current build |
|---|---:|
| historical human-commit block rate | 1.94% |
| adjudicated **false positive** | **1.06%** |
| legitimate policy block | 0.89% |
| unclear | 0.00% |

Down from 2.50% / 1.67% over three precision rounds (v0.1.3–v0.1.5): skip
conditions are read with their constants resolved instead of grepped
(attrs 7373d88, click b761eda), relocated tests are recognised even when they
carry their own skip markers or hold no assertions (click 700798252a),
feature removals explain the removal of their tests (attrs 74007f67d2, httpx
59914c7690, starlette 856c904a6d / b133ab45ad), dependency bumps explain
expectation drift (starlette 100f05a66b / 5ccbc62175), and deleting one of
two identical copies is dedup when the survivor is found at head, live and
collectable (click 1103c5cac2). No commit became newly blocked, every
spec-correct block still blocks, and the decoy corpus still blocks 12/12.

The process cut both ways, twice. The first cut of the feature-removal
credit cleared two spec-correct blocks (a rewritten function's locals
counted as "deleted symbols") and was caught by reconciling the sweep delta
against the adjudication before it shipped. And the duplicate search
overturned one adjudication *verdict* in the tool's favour: click a391797d00
had been judged a false positive on the claim that every deleted unit
reappears in the same diff — `git grep` at that commit's head proves
test_prompt_cast_default reappears nowhere, so the verdict is now
spec-correct and the commit correctly stays blocked. Adjudicating blocks
instead of just counting them is what made both catches possible.

Two adjudication passes exist, of two different populations — the earlier one
does not describe the current build and is kept only as history:

- `adjudication-2026-08-03.json` — all 35 blocks of the **current** (v0.1.5)
  build: 19 false positive, 16 spec-correct, 0 unclear. Updated in place as
  v0.1.3–v0.1.5 stopped blocking ten of the 45 v0.1.2 blocks (all ten
  adjudicated false positive) and one verdict was re-categorised on
  reproducible evidence; the file's `method` note records exactly what
  changed and why.
- `adjudication-2026-08-02.json` — the 40 blocks of the v0.1.1 build:
  24 false positive, 16 spec-correct, 0 unclear. Kept as history; it does not
  describe the current build, and `make_results.py` now refuses to pair it
  with a sweep it does not match.
- `triage-2026-07-30.json` — the 48 oracle-rule blocks of the **first** round:
  34 fixable false positives, 14 spec-correct, 0 unclear. Those 34 mechanisms
  drove three precision rounds and are now regression fixtures.

### Measured progression

Each row is a full re-run of the same harness over the same 1800 commits.
`RESULTS.md` always holds the latest.

| block rate | what changed since the previous row |
|---:|---|
| 8.56% | first measurement, M1 detectors as designed |
| 2.61% | pre-commit hook bumps reclassified; TDD hardcode FP; mild-weakening band; unicode scan narrowed to source |
| 3.00% | +`EXPECTED_VALUE_CHANGED` — added for recall, and it cost precision |
| 2.83% | M1 self-review: 8 verified defects in the M1 code itself |
| 2.22% | repair evidence reaches through unchanged intermediate modules (`PACKAGE_REPAIR`) |
| 2.50% | second independent audit: 12 bypasses closed (raises the rate), 4 false-positive classes fixed (lowers it) |
| 2.39% | D6 resolves skip-condition constants (same file → in-diff imports → head snapshot), reads xfail and if-guarded imperative skips; always-true tightened to truthy at zero corpus cost |
| 2.00% | relocation liveness through compat gates + whole-unit move credit; `PROD_SYMBOL_REMOVED` (deleted-scope symbols only, after the locals version cleared two spec-correct blocks and was tightened); `DEPENDENCY_DRIFT` for expectation literals tracking manifest bumps |
| **1.94%** | `DUPLICATE_REMAINS`: a deleted unit whose identical live copy survives at head outside the diff is dedup — and the same search overturned one FP verdict (a391797d00) by proving the "relocated" unit reappears nowhere |

The 3.00% row is the honest shape of the trade-off: closing a recall hole
raised the false-positive rate, and only measurement showed by how much.

The last row is worth its own note, because reasoning got it wrong. After the
self-review I predicted those eight fixes would bring httpx (the worst repo,
6.67%) down. Re-running the sweep moved httpx by exactly zero commits. The
real cause was elsewhere: symbol-level repair evidence is built only from
files the diff touched, so a test calling `httpx.URL(...)` got no credit for a
fix in `httpx/_urlparse.py` sitting behind an unchanged `_urls.py`. Thirteen
of httpx's twenty blocks were that one blind spot.

### The floor: why the remaining 19 stay

After three precision rounds, an attempt was made on the remaining 19
adjudicated false positives (v0.1.5 population). Three candidate mechanisms
were designed, and **all three were killed at design time by spec-correct
counterexamples in the same corpus** — the strongest evidence this project
can produce that the residual is a floor, not a backlog:

- *"An expectation edit is explained by a change to the unit's own setup"*
  would clear httpx 71a1589928 (18 findings: `encode_request(...)` becomes
  `httpx.Request(...)` and every expected header dict gains `Host`) — and
  would also clear **flask d98eb69a35**, a spec-correct revert whose unit
  setup changes too while coverage genuinely drops. The fallback ("new
  expected value extends the old") dies on **rich 48293cde88**, spec-correct,
  where the new value literally contains the old.
- *"A weakened assertion whose unit gains a new real assertion, or whose
  expected value survives into one, is a rewrite"* would clear attrs
  ce89f5d11f (`match=` added and the exact check kept) — and would also
  clear **httpx fc84f7f6eb**, spec-correct, which replaces its origin checks
  with brand-new exact asserts on a different property. The same syntactic
  shape, EXACT_VALUE(90)→PATTERN(60) with the anchor inside the pair,
  appears as a false positive in click 1557e26522 and as a spec-correct
  block in **httpx b5addb64f0** (`== "ISO-8859-1"` widened to
  `in ("ISO-8859-1", "WINDOWS-1252")`).
- *"Follow prod callers two hops instead of one"* would connect
  db9072f998's rewritten `validate_path` to its tests — and would also hand
  repair evidence to **httpx 4f6edf36e9**, spec-correct, whose test sits one
  wrapper (`Response(...).links`) from the modified prod function.
  THREATMODEL #5's one-hop stance survives on evidence.

The pattern across all three: the same *syntactic* shape appears on both
sides of the adjudication, and what separates them is whether the rewrite is
semantically equivalent — the judgement THREATMODEL #1 and #7 deliberately
exclude from a zero-LLM, zero-execution differ. On this corpus the
adjudicated false-positive floor of that design is **~1.06%**, and each of
the 19 residuals names its cluster in the adjudication file: API-migration
rewrites (httpx 71a1589928 / 7947b56076 / cca62060cb / 9fd6f0ca66), unit-
internal co-changes (click bd131e1ab6 / e3c0898975 / bbe1eb6d41), equivalent
replacements after feature change (becbde5cf4 / cf0c36d337 / 90b805fda7 /
02b6ed7b18 / 06ea505ce2 / 777a89e232 / 53b8f08218 / f520d9a89f / bddd774ce0
/ ce89f5d11f / 1557e26522 / db9072f998). Lowering the floor honestly means
adding a semantic layer (execution or a model) — a different product with a
different threat model — or accepting reviewed allowlisting as the last
mile, which is what the per-fingerprint exemption flow is for.

## 2. Decoy-task corpus (recall)

Twelve bug-fix tasks with must-fail tests, run through real coding agents in
two conditions. **Status: run** — see `decoy/README.md`.

Headline: under natural conditions 0 of 12 agents touched a test at all; under
adversarial conditions greenwash caught 0 of 12 tampering diffs on first
measurement and 12 of 12 after the three bugs that exposure revealed were
fixed. One of those bugs — build artifacts granting repair evidence — meant
any user who had run their test suite was protected by nothing.

Rationale for building this rather than importing an academic benchmark: the
published reward-hacking suites are mostly system-level task sets whose cases
do not reduce cleanly to a before/after diff, which is the only shape
greenwash consumes.

## 3. Comparison against the nearest neighbour

**Status: run** — `compare/COMPARISON.md`, with the caveat stated loudly there
that the corpus is Python (greenwash's home, swarm's secondary ecosystem) and
both tools ran without an LLM judge.

On the 24 decoy diffs, both tools *detect* all 12 cheats; the difference is
discrimination. swarm's structural signal also fires on 11 of 12 honest fixes,
which is why it stays advisory; greenwash fires on 0 of 12 honest fixes, which
is what lets it block by default. Not "greenwash detects more" — "greenwash
separates tampering from honest work sharply enough to gate on it, on this
corpus." The tools are complementary; the comparison does not touch swarm's
JavaScript home turf.

## Rule

No number goes in the README, a badge, or a launch post until it comes out of
one of these harnesses on a clean checkout. Numbers that exist only in a
design document are not results.

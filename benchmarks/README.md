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
| historical human-commit block rate | 2.50% |
| adjudicated **false positive** | **1.67%** |
| legitimate policy block | 0.83% |
| unclear | 0.00% |

Both rose from the previous round (2.22% / 1.33%). Twelve bypasses were closed
in the 2026-08-03 build, and a tool that catches more also fires more; four
false-positive classes were fixed in the same build and the net was still
upward. That is the trade, reported as measured rather than as hoped.

Two adjudication passes exist, of two different populations — the earlier one
does not describe the current build and is kept only as history:

- `adjudication-2026-08-03.json` — all 45 blocks of the **current** build:
  30 false positive, 15 spec-correct, 0 unclear.
- `adjudication-2026-08-02.json` — the 40 blocks of the previous build:
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
| **2.50%** | second independent audit: 12 bypasses closed (raises the rate), 4 false-positive classes fixed (lowers it) |

The 3.00% row is the honest shape of the trade-off: closing a recall hole
raised the false-positive rate, and only measurement showed by how much.

The last row is worth its own note, because reasoning got it wrong. After the
self-review I predicted those eight fixes would bring httpx (the worst repo,
6.67%) down. Re-running the sweep moved httpx by exactly zero commits. The
real cause was elsewhere: symbol-level repair evidence is built only from
files the diff touched, so a test calling `httpx.URL(...)` got no credit for a
fix in `httpx/_urlparse.py` sitting behind an unchanged `_urls.py`. Thirteen
of httpx's twenty blocks were that one blind spot.

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

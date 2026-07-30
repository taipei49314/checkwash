# Benchmarks — what is measured, and what is not

Two corpora back the "blockable by default" claim. Both are reproducible from
a clone. This file says plainly which numbers exist and which do not.

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

Every oracle-rule block from the first round was triaged by an independent
agent reading the real diff (`triage-2026-07-30.json`): 14 spec-correct, 34
fixable false positives, 0 unclear. Those 34 mechanisms drove three precision
rounds and are now regression fixtures.

### Measured progression

Each row is a full re-run of the same harness over the same 1800 commits.
`RESULTS.md` always holds the latest.

| block rate | what changed since the previous row |
|---:|---|
| 8.56% | first measurement, M1 detectors as designed |
| 2.61% | pre-commit hook bumps reclassified; TDD hardcode FP; mild-weakening band; unicode scan narrowed to source |
| 3.00% | +`EXPECTED_VALUE_CHANGED` — added for recall, and it cost precision |
| 2.83% | M1 self-review: 8 verified defects in the M1 code itself |
| **2.22%** | repair evidence reaches through unchanged intermediate modules (`PACKAGE_REPAIR`) |

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

Running both corpora through swarm-orchestrator and publishing both columns,
including the cases where it wins. **Status: not started.**

## Rule

No number goes in the README, a badge, or a launch post until it comes out of
one of these harnesses on a clean checkout. Numbers that exist only in a
design document are not results.

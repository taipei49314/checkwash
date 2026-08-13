# Legitimate-refactor corpus — the false-positive side

60 test-suite refactors that a careful engineer would make and a reviewer would
approve. Every one keeps an oracle that still detects the bug.

- `CASE_*`: 30 mixed refactors (extraction, merge, split, fixtures, `approx`)
- `EXT_*`: 30 more of the single hardest family — a concrete assertion
  extracted into a shared, parameterised helper — generated after the
  reachable-assertion IR landed, to price exactly the line it has to draw

At v0.1.25 the first 30 blocked **20**. With the reachable-assertion IR
(v0.1.26) they block **17**, and the extraction arm arrives at **16 of 30**:
**33 of 60 overall**, decomposed below rather than averaged away.

```bash
python benchmarks/refactors/verify.py
```

## Why this corpus had to exist

The published false-positive rate — 21/1800 = 1.17% — is measured on six
libraries whose commits rarely restructure test helpers. That number is honest
about what it measured and useless as a guide to what happens when someone
*does* restructure them, and no amount of re-running the sweep would have said
so. It is the same failure that nearly shipped `TEST_PATCHES_SUBJECT` on a
"zero cost" that was really zero power (THREATMODEL 90).

So this corpus targets one shape deliberately: **moving where the assertion
lives.** That is precisely what greenwash models, and precisely what the sweep
corpus almost never does.

## Why a case counts

Nothing is taken on trust. Each case ships production **twice** — correct and
buggy — and four pytest runs must agree:

| | PROD-GOOD | PROD-BUG |
|---|---|---|
| `BEFORE/` | passes | **fails** |
| `AFTER/` | passes | **fails** |

Both sides genuinely catch the bug. So any block on the `BEFORE → AFTER` diff is
a false positive *by construction* — there is no judgement call and no
adjudication to argue about.

All 60 passed this filter on 2026-08-13.

## The result, v0.1.26 (baseline v0.1.25 in parentheses)

**33 of 60 false positives** — first arm 17 (was 20), extraction arm 16 at
first contact. The residue decomposes into named families, and only one of them
is a bug:

| family | ~count | status |
|---|---|---|
| the assertion moved to a helper in **another file** (`conftest.py`, `tests/helpers.py`) | 7 | tractable — reachability is same-file today, and the helper file is *in the diff*; the bounded next step |
| **unit identity changed** — merge, split, params fixture, `setUp` | 11 | a different family (`TEST_DISABLED`, not assertion motion); THREATMODEL 92's other half, own round |
| the shared assertion is **lattice-weaker** than the concrete asserts it replaced (`.endswith` for `==`, a truthy check, `approx`) | ~8 | **kept, deliberately** — the identical transition is what blocks 25 of 28 disguised-extraction attacks in the tamper corpus; trading those for these is refused, in writing |
| within-body extraction (fixture teardown, comparison object, `operator.eq`) | rest | mostly fixed by the reachable set; the leftovers are the two families above wearing other syntax |

What changed to get here: `UnitSide.assertions` now records the assertions a
unit *executes* (same-file call graph, invocation not mention), helper-borne
assertions carry an `inherited` flag, and `ASSERT_SUBSTITUTED` declines pairs
that cross the body boundary — extraction moves the slot, not the assertion.
The disguised-attack arm in `../tamper/` is the proof that declining there
gives nothing away.

## Files

- `cases/CASE_NNN_<mod>/`, `cases/EXT_NNN_<mod>/` — `WHY.txt`, `PROD-GOOD/`, `PROD-BUG/`, `BEFORE/`, `AFTER/`
- `verify.py` — four pytest runs per case, then greenwash; writes `results-latest.json`
- `results-2026-08-13.json` — the v0.1.25 baseline (first 30 cases), recorded before any A5 work
- `expected.json` — the current per-case table, enforced by `tests/gates/test_refactor_corpus.py`

# Legitimate-refactor corpus — the false-positive side

30 test-suite refactors that a careful engineer would make and a reviewer would
approve. Every one keeps an oracle that still detects the bug. **greenwash
blocks 20 of them.**

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

All 30 passed this filter on 2026-08-13.

## The result, v0.1.25

**20 false positives, 10 silent.** They cluster:

| cause | cases | what the refactor did |
|---|---|---|
| `ASSERT_REMOVED` — the assertion moved somewhere greenwash does not follow | 012, 017, 018, 019, 022, 023, 025, 030 | into a helper, a `conftest.py`, a fixture teardown, a method on a comparison object, `operator.eq` |
| `TEST_DISABLED` — unit identity changed | 011, 020, 021, 026, 027, 029 | two tests merged into one, one split into two, a params fixture, `setUp`, `if/raise` instead of `assertEqual` |
| `ASSERT_WEAKENED` | 024 | exact equality rewritten with `pytest.approx` and an explicit tolerance |

The first family is `docs/defence-design.md` A5 seen from the other side: the
same blindness that lets 28 of 40 attacks through also blocks the honest
refactors, because both hinge on greenwash not knowing which assertions a test
actually runs. A5 is therefore not only a recall change — the FP measurement is
what will say whether it is a net improvement, and this corpus is how.

## Files

- `cases/CASE_NNN_<mod>/` — `WHY.txt`, `PROD-GOOD/`, `PROD-BUG/`, `BEFORE/`, `AFTER/`
- `verify.py` — four pytest runs per case, then greenwash; writes `results-latest.json`
- `results-2026-08-13.json` — the v0.1.25 baseline, recorded before any A5 work

# Legitimate-refactor corpus — the false-positive side

60 test-suite refactors assembled as the historical false-positive arm. Each
ships a particular bug that the original and refactored tests are meant to catch.
The execution qualification below checks that claim; human review must still
decide whether the refactor preserves the intended semantics.

- `CASE_*`: 30 mixed refactors (extraction, merge, split, fixtures, `approx`)
- `EXT_*`: 30 more of the single hardest family — a concrete assertion
  extracted into a shared, parameterised helper — generated after the
  reachable-assertion IR landed, to price exactly the line it has to draw

At v0.1.25 the first 30 blocked **20**. With the reachable-assertion IR
(v0.1.26) they block **17**, and the extraction arm arrives at **16 of 30**:
**33 of 60 overall**, decomposed below rather than averaged away.

```bash
python benchmarks/refactors/verify.py --output /new/path/refactor-receipt.json
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

Each case ships production **twice** — correct and buggy — and four pytest runs
must agree for its execution to qualify:

| | PROD-GOOD | PROD-BUG |
|---|---|---|
| `BEFORE/` | passes | **fails** |
| `AFTER/` | passes | **fails** |

Both sides catching the seeded bug does not prove that their complete semantics
are equivalent. For example, a relaxed tolerance can still catch that bug while
accepting other values the original test rejected. The verifier reports
**qualified mechanical blocks**, which need human semantic adjudication before
they can be counted as false positives. The dated results below retain their
historical "false positives" terminology and counts; they are not new adjudication.

All 60 passed the historical exit-code-only filter on 2026-08-13. That filter
mistook every nonzero pytest exit for a test that caught the bug, including
collection and fixture errors. The historical records below remain unchanged.

The verifier now requires each good run to exit 0 with at least one test, no
failures, errors or skips. Each buggy run must exit 1 with at least one JUnit
test failure, no errors and no skips. Collection/import failures, fixture setup
or teardown errors, usage errors, no tests, timeouts, and missing or inconsistent
reports cannot establish the oracle claim. An assertion raised during fixture
setup or teardown is still a pytest error under this criterion; whether that
phase should qualify needs maintainer review. It is not an engine defect.

Each run retains its exit code, counts, stdout, stderr and JUnit report from
the same subprocess. A new receipt includes the engine version, source commit
and tree, worktree status, actual source/verifier/corpus content hashes, expected
table hash, environment, timestamps and all cases. Automatic third-party pytest
plugin loading is disabled in the subprocess environment. Inputs are hashed again
after the run to detect changes during measurement.

`--output` is required and must name a new file; neither historical results nor
an existing receipt can be overwritten. The optional positional argument selects
another cases directory; `--expected` selects its declared membership table.
That table must contain a nonempty `cases` object whose keys are directory names
starting with an ASCII letter/digit and containing only letters, digits, `_` or
`-`; invalid membership is rejected before measurement.
Missing and unexpected cases remain visible. An invalid or incomplete cohort
exits 2 and reports the full case denominator and mechanical block count. Exit 0
means every declared case completed all four checks against unchanged inputs.
Neither exit status establishes a false-positive rate or replaces human semantic
adjudication, held-out precision, adoption experience, or distribution verification.

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

2026-09-01 (issue #55, per-call-site inherited reaching): helper-borne
assertions are now inherited once per unit-level call site, so a merge whose
survivor calls the helper once per absorbed test conserves the oracle count —
CASE_020_windows (two tests become one function calling `check()` twice)
stops blocking, and the total became **24 of 60**.

2026-09-06 (PR #133, table consolidation): CASE_026_leap and CASE_029_flatten
stop blocking, and the then-current total was **22 of 60** (replayed by
`tests/gates/test_refactor_corpus.py`). `expected.json` is the per-case
truth; the family table above is kept as the v0.1.26 record.

2026-09-07 (issue #140, re-run): `results-latest.json` is `verify.py` re-run on
a clean checkout of `e6984de` (checkwash 0.3.1, the v0.3.0 engine) on
the estate runner pool (run 34137702148, attempt 1, Python 3.12,
pytest 9.1.1): all 240 pytest observations ran to a parsed report; **22 of
60** block, CASE_026_leap and CASE_029_flatten now pass, and every verdict
agrees with `expected.json`. The verifier marks the cohort *incomplete*: 3
cases (CASE_007_running_sum, CASE_008_slugify, CASE_019_normalize) do not qualify
under the post-#104 oracle because their seeded bug is caught by an assertion
inside a pytest fixture, which pytest reports as a setup/teardown ERROR rather
than a test failure (`valid: false` in the file, verdicts still recorded). The
2026-09-02 run accepted any non-zero exit, so it showed them as valid. The
file keeps the tracked row shape; the full receipt (schema_version 1: source
commit, environment, per-case observations) is at
`refs/heads/sweep-receipts/34137702148/1/refactor-results` in
estate-consolidation, sha256
`f9377b186c6a57794e48c944f711d1ec1aad148bb2b6d4438eaaefeff8afd675`.
No test pins this file; `expected.json` remains the enforced truth.

2026-09-12 (EC T-326, unreleased candidate): the source replay at `ebb6b2d`
in [CI run 34672934659](https://github.com/taipei49314/checkwash/actions/runs/34672934659)
identified CASE_006_fib, EXT_010_ordinal and EXT_029_basename as repaired
false positives. Their `expected.json` entries now require a passing verdict.
This is a current regression expectation update, not a rewrite of the
historical runtime results above. Candidate-wide runtime qualification and
additional repairs are recorded separately in the review PR.


The subsequent source replay at `04c4da4` in
[CI run 34673547069](https://github.com/taipei49314/checkwash/actions/runs/34673547069)
confirmed twelve more repaired false positives: CASE_009_parse_ints,
CASE_010_median, CASE_017_cap_words, CASE_018_interleave, CASE_022_safe_div,
CASE_025_all_equal, EXT_003_take, EXT_013_min_max, EXT_016_reverse_words,
EXT_022_fill_none, EXT_027_merge_unique and EXT_030_unquote. Their current
expectations require pass. That run also found three new regressions
(EXT_004_ceil_div, EXT_014_product and EXT_021_truncate); their existing pass
expectations remain in force. The historical measurements above are unchanged.


The replay at `b547201` in [CI run 34673998703](https://github.com/taipei49314/checkwash/actions/runs/34673998703)
confirmed the remaining three reviewed honest false positives now pass:
CASE_027_clip_index, EXT_005_rpad and EXT_008_is_sorted. Their current
expectations now require pass. The eighteen reviewed repairs concern this
dedicated 60-case cohort; they do not constitute a replay of the separate
90-case LLM refactor arm or the full historical 178-case corpus. Remaining
recorded blocks include an exact-to-approximate comparison, a mixed
identity-to-equality case, and two unqualified fixture-error cases. Full
runtime qualification still reports the three historical fixture errors.

## Files

- `cases/CASE_NNN_<mod>/`, `cases/EXT_NNN_<mod>/` — `WHY.txt`, `PROD-GOOD/`, `PROD-BUG/`, `BEFORE/`, `AFTER/`
- `verify.py` — four pytest runs per case, then checkwash; requires a new `--output` receipt path
- `results-2026-08-13.json` — the v0.1.25 baseline (first 30 cases), recorded before any A5 work
- `expected.json` — the current per-case table, enforced by `tests/gates/test_refactor_corpus.py`

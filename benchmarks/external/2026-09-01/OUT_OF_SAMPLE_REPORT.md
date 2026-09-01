# greenwash v0.1.49 — independent out-of-sample sweep (2026-09-01)

1300 human-reviewed commits across 8 projects, run as a black box via the
released `greenwash.pyz` on Windows / Python 3.12. The greenwash repository
itself was not modified. Maintainer-run (taipei49314), single rater.

## Headline

| project | in corpus? | blocked | rate | touching tests | opaque | engine errors |
|---|---|---|---|---|---|---|
| psf/requests | no | 0 / 100 | 0.00% | 15 | 3 | 0 |
| willmcgugan/rich | **yes** (six-project sweep) | 4 / 100 | 4.00% | 31 | 0 | 0 |
| pydantic/pydantic | no | 2 / 100 | 2.00% | 52 | 19 | 0 |
| fastapi/fastapi | no | 2 / 200 | 1.00% | 18 | 14 | 0 |
| aio-libs/aiohttp | no | 6 / 200 | 3.00% | 63 | 25 | 0 |
| celery/celery | no | 2 / 200 | 1.00% | 111 | 6 | 0 |
| psf/black | no | 16 / 200 | **8.00%** | 58 | 6 | 0 |
| httpie/httpie | no | 6 / 200 | 3.00% | 32 | 39 | 0 |
| **total** | | **38 / 1300** | **2.92%** | 380 | 112 | **0** |

Out-of-sample only (excluding rich): **34 / 1200 = 2.83%**. Zero engine errors
across all 1300 analyses.

## Adjudication highlights

- **rich** (in-corpus, kept for reference): all 4 blocks are the D-050
  two-commit-split family (`823de916d9`, `9303d77e8d`) + one
  `EXPECTED_VALUE_CHANGED` on "fix tests". All false positives, all already
  published residuals.
- **pydantic `69fd688e2d`** ("Split stdlib types tests into dedicated test
  files"): whole-file split with light edits in transit → D2 body-hash credit
  fails → **131 high TEST_DISABLED in one commit**. False positive; the
  THREATMODEL 92 unit-identity family at the largest scale observed. The
  unadjudicated `800f2f9089` is one TEST_DISABLED.
- **black = the outlier, and the diagnosis is clean.** 16/200 blocked, 41
  findings, nearly all `ASSERT_REMOVED (TRUTHY)` hitting the *same* units
  (`test_python37`, `test_check_diff_use_together`, `test_ipynb_*`) across
  many unrelated commits. `BlackTestCase(BlackBaseTestCase)` is a
  project-local base class whose assertions are custom helpers
  (`assertFormatEqual`, `black.assert_stable`) — the row-86 residual
  ("a project-local base is not resolved") plus the helper-assert culture
  `benchmarks/corpus-expansion.md` predicted would not be exercised by the
  six-repo corpus. This is that prediction landing: **the 8% is one repo's
  structural mismatch, not diffuse noise.**
- **httpie `3de7c82077`** ("Cleanup", 19 files): 112 high
  `EXPECTATION_DEFINITION_CHANGED` in one commit — expectation bindings moved
  during a broad cleanup. Presumed false positive, not fully adjudicated.
- **aiohttp `c52fe79c74` / `79b5f5fa5b`** ("Fix flaky test(s)"): ASSERT_REMOVED
  x3 / ASSERT_WEAKENED x2. Flaky-test fixes that drop timing/retry assertions
  are plausibly **legitimate policy blocks** (oracle coverage dropped with
  nothing replacing it) — the adjudication category, not tool error.
- **fastapi**: one CI_WORKFLOW_TOUCHED high, one EXPECTED_VALUE_HARDCODED high;
  **celery**: one EXPECTED_VALUE_CHANGED, one TEST_DISABLED x6. Not adjudicated.

## Reading for the maintainer

1. Diffuse FP rate outside the tuning corpus is ~1–3% and within the
   published band; the tail risk is concentrated, not spread: two repos
   account for 22 of 34 out-of-sample blocks, each via one named mechanism.
2. The corpus-expansion thesis is confirmed directionally: black (custom base
   class + helper asserts) and httpie/pydantic (expectation bindings in shared
   utils / large splits) are exactly the cultures the six sweep repos lack.
3. Candidate work items by observed cost: cross-file/base-class oracle
   resolution (row 86/91 residual, worth ~16 blocks on 200 black commits);
   whole-file-split relocation credit (D2/D10, worth the 131-finding pydantic
   event); nothing new observed in the E6/CI family.

## Reproduction

```bash
curl -LO https://github.com/taipei49314/greenwash/releases/latest/download/greenwash.pyz
git clone --depth 250 <repo> && cd <repo>
python ../greenwash.pyz sweep HEAD --limit 200
```

Raw sweep JSON for all 8 projects sits alongside this report
(`*_sweep.json`).

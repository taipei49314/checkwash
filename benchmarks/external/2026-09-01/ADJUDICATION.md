# Second-rater adjudication — all 74 blocks

Date: 2026-09-01. Rater 2: project assistant (Claude), adjudicating from
extraction-only evidence dossiers (verbatim findings + `git show` of every
blocked commit, plus targeted checks in shallow clones). All 74 verdicts
were made by the single second rater for internal consistency. Rater 1 is
the field-run maintainer (FINAL_REPORT.md).

## Rubric

- **FP** — the detector should not have fired, or fired on evidence that
  dissolves under the diff's own content (compensation visible in-diff,
  strengthening misread as weakening, phantom finding).
- **TP-policy** — the finding is factually accurate and the block is the
  designed behavior: a coverage-reducing or guardrail-touching edit with no
  in-diff compensation, where the correct outcome is stop-and-human-review
  (the human then usually clears it). Not tampering.
- **UNCERTAIN** — evidence insufficient. (None remained.)

Consistency rules applied throughout: a test removed because the feature
or behavior it pinned is gone *in the same diff*, with the surviving
oracle still constraining the change → FP. A test disabled/deleted because
it is flaky or red while the feature still exists, with no in-diff
compensation → TP-policy. Environment-scoped `skipif` with a reason, on a
platform/backend leg where the oracle cannot apply → FP.

## Result

**67 FP / 7 TP-policy / 0 UNCERTAIN.**

On the tampering axis both raters agree completely: **0 of 74 blocks are
verification-layer tampering** (74/74 agreement with rater 1's thesis-level
conclusion). The FP/TP-policy split below is rater 2's finer partition of
the same non-tampering mass; rater 1's report did not label every block on
that axis, so no per-block kappa is computed for it (stated rather than
fabricated). Blocks where the two raters' published texts differ are in
the disagreement list at the end.

## Per-block verdicts

### rich (4)

| commit | title | verdict | reason |
|---|---|---|---|
| 48293cde | fix tests | FP | expected render output updated alongside the in-diff renderer change |
| 823de916 | test fixes | FP | same family — expectation definitions track the rendering change |
| 9303d77e | markdown test | FP | expectation tracks in-diff markdown rendering change |
| 1c5e03eb | fix for padding width | FP | expected output tracks the padding fix in the same diff |

### pydantic (2)

| commit | title | verdict | reason |
|---|---|---|---|
| 69fd688 | Split stdlib types tests into dedicated test files | FP | **move credit**: 131 `TEST_DISABLED` on units relocated to 34 new per-type files (spot-checked `test_constrained_bytes_*`, `test_decimal*` present at the new paths); single-file frontend cannot see the destination |
| 800f2f9 | Revert "Add regression test: plugin + recursive model validator runs once" | TP-policy | deletes a regression test that was merged *before* its fix (red on main by construction); green-restoring deletion of a red test is exactly what the gate stops. Fix + equivalent 38-line test landed 5 days later (17e2dda) |

### black (16)

All 16 blocks share one mechanism, verified by reproduction: the three
units `test_check_diff_use_together`, `test_python315`, `test_python37` in
`tests/test_black.py` receive phantom `ASSERT_REMOVED` findings on **any**
edit to the file, including pure insertions and unrelated one-line
changes. This is a frontend def-use binding artifact, not a property of
the commits. Two commits (9e969ddc, 69973fd6) carry additional findings
beyond the trio; those components are legitimate test adaptation
(runner unification; blackd hardening with a constant pinned by a new
test) and do not change the verdict.

| commit | title | verdict |
|---|---|---|
| 74371e20 | Report parse errors as file:line:column | FP |
| d7587ce9 | Validate BLACK_NUM_WORKERS values | FP |
| 56ba38a4 | Handle empty cache files | FP |
| 2d174df7 | Validate include and force-exclude config types | FP |
| 6c136f97 | fix: no spurious target-version warning | FP |
| 650983f7 | Fix docstring indentation with leading tabs | FP |
| 70e0956f | Respect NO_COLOR by disabling ANSI output | FP |
| ebe6018e | CI Hotfixes | FP |
| 9fd9ea28 | Fix blackd error handling | FP |
| c7fc2438 | Improve parse error readability | FP |
| 9e969ddc | tests_black: always use the BlackRunner | FP |
| 69973fd6 | Harden blackd browser-facing request handling | FP |
| 4937fe6c | Fix cache-file/IPython shenanigans | FP |
| 148efe40 | Warn when target version exceeds runtime | FP |
| fe875c0e | Don't double-decode input | FP |
| 6305bf1a | Prepare 2026.1.0 release | FP |

### aiohttp (6)

| commit | title | verdict | reason |
|---|---|---|---|
| c52fe79c | Fix flaky test | FP | asserts removed with in-diff compensation (flake fixed, oracle reshaped) — *disagreement: rater 1 called this a plausible policy block* |
| 4602990f | Fix flaky descriptor test | FP | flake fix with compensation in-diff |
| 069e9cfc | Stop the benchmark CI job hanging on apt | FP | CI infra unsticking; no test-command weakening |
| 79b5f5fa | Fix flaky timer tests | FP | timing bounds loosened to kill flake, oracle retained — *disagreement: rater 1 called this a plausible policy block* |
| b2b7b50c | Move flaky perf test to codspeed | FP | move credit — test relocated to the benchmark suite |
| cd0556b2 | Fix a flaky test on Windows | TP-policy | test disabled for flakiness, feature intact, no in-diff compensation — stop-and-review is correct |

### tornado (9)

| commit | title | verdict | reason |
|---|---|---|---|
| d6e55b5 | (subprocess test rework) | FP | oracle moved behind subprocess boundary but still enforced |
| de5e943 | — | FP | adaptation with compensation in-diff |
| b7447c1 | — | TP-policy | skip added while feature exists, no in-diff compensation |
| cc61050 | — | FP | legitimate adaptation |
| afb2337 | — | FP | legitimate adaptation |
| ef8c6ab | — | FP | assertion strengthened, misread as substitution |
| e6d3f49 | (@abstract_base_test refactor) | FP | **phantom**: `test_resolve_multiaddr` verified present on both sides; class base-list change broke unit-identity pairing |
| b6fbb59 | — | FP | long-`@unittest.skip`ped dead test replaced with a working annotations test — coverage increase |
| 50358ac | — | FP | `set([...])` → `{...}` literal modernization flagged as ASSERT_SUBSTITUTED — normalization gap |

### sympy (13)

| commit | title | verdict | reason |
|---|---|---|---|
| ed75b73d | manualintegrate: add tests for Bioche improvement | FP | **phantom on pure insertion** (23 lines added, 0 removed): sequential reuse of `F`/`F1`/`F2` re-pairs def-use on insertion; 13 findings on a coverage-only diff |
| 358d1f28 | test_manual: update owens_t for extended piecewise | FP | expected values guarded by the self-verifying oracle `assert_is_integral_of` (checks by differentiation); Piecewise extension is a correctness refinement |
| 472f042e | testing: cover the remaining satask only queries | FP | `_ask_recursive(...) is None` → `ask(...) is True/False`: indeterminate → definite under the fuller engine, with the weak-engine form preserved under `@XFAIL` in the same diff |
| e332b8d3 | assumptions: test satask only queries apart | FP | same family, 13 substitutions all strengthenings with XFAIL preservation; includes a genuine handler bugfix (mersenne conjuncts) |
| bc87480e | change all bare asserts to complete assert statements | FP | `assert not f(x)` (truthy, passes for False *and* None) → `is False`/`is None`: bulk TRUTHY→EXACT_VALUE **strengthening** flagged as WEAKENED via conservative pairing |
| 8e7945f1 | implements MN algorithm for character tables | FP | membership assert replaced by reorder construction; orthogonality-diagonal oracle still constrains alignment; new S10 test added |
| ceca5c64 | fix test_owent_is_extended_real assertions | FP | old expected `False` was documented in-file as a Python `and` short-circuit bug; `None` is the mathematically correct tri-state — lattice misgrades `is None` as NON_NULL |
| e82e84d0 | manualintegrate: minor adjustments for Bioche | FP | "cannot solve" guard upgraded to exact closed form (derivative verified correct) after capability improvement |
| 3ead05e1 | Adjusted implicit tests for kanes constraints | FP | perf-ratio guard **restored** (`< .15`, later tightened to `< .02` at HEAD), lambdify 1e-13 numeric check added, `@slow` removed — net coverage up |
| 98dff817 | Saving. | TP-policy | WIP snapshot comments out `assert n_ops_implicit / n_ops_explicit < .05` with no in-diff compensation; restored 3.5 h later in 3ead05e1, but at the commit boundary the stop is correct |
| a31843cd | tests: replace `ask` calls with `_ask_recursive` | FP | 3,342-line mechanical rename for the intended engine split; expectation downgrades track the deliberate weak-engine scope, completed by 472f042e/e332b8d3 |
| 228ef305 | added tests for Euler substitution, adapted old ones | FP | expected values updated **with derivative self-checks added in the same diff**; new Euler-substitution coverage |
| aa1b43c3 | test_manual: add test for the integral of OwenT | FP | phantom on pure insertion (4 added lines), same rebinding mechanism as ed75b73d |

### pandas (12)

| commit | title | verdict | reason |
|---|---|---|---|
| b18bbee | BUG: Normalize MaskedArray input | FP | `pytest.raises(AssertionError)` known-bug wrappers removed **with the bug fixed in-diff** — oracle strengthened; new groupby test added |
| 5fef3b9 | CLN: remove assert_matching helper | FP | loose local helper (dtype check off) replaced by canonical `tm.assert_index_equal` on fully-constructed expecteds + non-mutation checks — stronger |
| 75f24bb | TST: add match to assert_produces_warning | FP | duplicate unit pairs consolidated; every surviving warning assertion gains a `match` pattern — stronger |
| f08f1cc | BUG: Series constructor RecursionError | FP | deleted units are xfail-**overrides**; base-class tests reactivate via inheritance once the bug is fixed in-diff — coverage up |
| eb5466f | CLN: cleanup json datetime units | FP | dropped parametrize axis (`pd.Timedelta` vs stdlib `timedelta`) fed byte-identical values to the serializer once ns-scaffolding was removed — redundant leg |
| b117da9 | CI: Update pixi.lock | FP | unconditional xfail narrowed to `xfail(pa_version_under26p0)` — test now must pass on new pyarrow |
| 9f9b3df | BUG: ArrowDtype str methods raised for flags | FP | `NotImplementedError` guards upgraded to exact-value oracles after the feature was implemented; substantial new coverage |
| f9204c7 | TST: repair vacuous parallel-read guards | FP | commit *adds* spy assertions making previously-vacuous tests real; `skipif(WASM)` replaces a vacuous pass with an honest skip |
| 518f2a3 | DOC: require human-written comments and AI disclosure | TP-policy | `GUARDRAIL_TOUCHED` on AGENTS.md is categorical by design — any agent-constraint edit stops for human review regardless of direction (here the human was strengthening them) |
| 8dc5f47 | TST: Improve test runtimes | FP | `default_axes=True` helper-parameter tuning; assertion set unchanged |
| b3573cd | DEPS: Update dependency minimum versions | FP | all 14 findings are dead version-fork cleanup under raised floors (numpy<2 / mpl<3.10 / fastparquet branches); several assertions became unconditional (stronger) |
| 6faf2dc | BUG: concat with null[pyarrow] | FP | xfail-override deletion after in-diff fix — inherited tests reactivate; 8-dtype regression test + unit test added |

### httpie (6)

| commit | title | verdict | reason |
|---|---|---|---|
| 3de7c82 | Cleanup | FP | all 112 findings are one uniform mechanical rewrite `httpbin.url + x` → `httpbin + x` (fixture compensated in the same diff, conftest/utils) |
| 18bb49b | Skip a test failing in CI | TP-policy | bare `@pytest.mark.skip('Doesn't work in CI')` + TODO; feature intact, zero compensation — the canonical stop |
| 8e56e9f | Fix a failing test | FP | order-sensitive string containment → set **equality** (stronger), and an always-true `assert name, value in ...` footgun replaced by a real equality check |
| 419cc2c | Skip on pyOpenSSL | FP | reasoned `skipif(IS_PYOPENSSL)` on an alternate-backend leg with a different message format; primary-backend coverage intact |
| ff6f188 | [Major] UI Enhancements | TP-policy | 2 of 3 findings are old-UI residue (`'[K'`, `'Done'` asserts on a renderer replaced in-diff; real oracle `body == r` kept) = FP; the third — an **unconditional** `@pytest.mark.xfail` with the reason only in a comment — justifies the stop |
| c157948 | Add `httpie cli plugins` namespace | FP | helper parametrized over both CLI namespaces; same assertions now run twice |

### fastapi (2)

| commit | title | verdict | reason |
|---|---|---|---|
| 7d123d9 | Test PR regressions against base code | FP | `set +e` is the exit-code capture idiom inside a **new** regression-proof CI job (required in `alls-green`) — a verification gate added, not weakened |
| 65ef53a | Update the lru_cache limit for dependencies | FP | expected 4096 tracks the in-diff constant, and a new test asserts the large-app semantics the constant exists for |

### celery (2)

| commit | title | verdict | reason |
|---|---|---|---|
| bf1cf69e | Skip empty groups in chains | FP | expected value tracks the intended behavior change in the same diff |
| c7018110 | move start_worker() integration tests to smoke tests | FP | move credit — 6 units relocated to the smoke-test tier, not deleted |

### sqlalchemy (2)

| commit | title | verdict | reason |
|---|---|---|---|
| aaed3ad2 | continue-on-error for upload-release-assets | FP | release-asset upload retry idempotency; no test command touched |
| 7776cfbf | fall back to twine upload without attestations | FP *for this thesis* + **flag**: a real supply-chain weakening (attestation `continue-on-error` + unattested-publish fallback). Outside the oracle-tampering scope `CI_WORKFLOW_TOUCHED` is specified for — raised to the owner as a candidate new family (SPEC decision) |

## Mechanism families (detector-engineering input, ranked by yield)

1. **Phantom findings from unit/def-use identity breaks** — the single
   largest family by block count (**19+ blocks**): black's trio fires on
   *any* edit to `tests/test_black.py` including pure insertions (16
   blocks, reproduced); tornado e6d3f49 (class base-list change breaks
   unit identity — unit proven present on both sides); sympy ed75b73d and
   aa1b43c3 (insertion re-pairs sequentially reused variables). Cheap
   fixtures exist for each. This displaces row-86 cross-file resolution as
   the top R1 target.
2. **Move credit** — pydantic 69fd688 (131 findings), celery c7018110,
   aiohttp b2b7b50c: relocation across files/tiers read as deletion.
3. **Uniform mechanical rewrites** — httpie 3de7c82 (112 findings from one
   substitution shape), sympy a31843cd (3,342-line rename),
   bc87480e (truthy→identity strengthening graded WEAKENED), tornado
   50358ac (set-literal). A same-shape-collapse or callee-aware pairing
   would erase these.
4. **Inheritance-aware unit identity** — pandas f08f1cc, 6faf2dc: deleting
   an xfail-*override* reactivates the inherited base test; counted as
   unit-disappeared.
5. **Version-floor storms** — pandas b3573cd (14 findings): compat
   branches deleted / conditions partially evaluated under raised floors.
6. **Known-bug idioms** — `pytest.raises(AssertionError)` around
   `tm.assert_*` (pandas b18bbee), unconditional→conditional xfail
   narrowing (b117da9), `NotImplementedError`-guard upgrades (9f9b3df).
7. **Semantic self-verifying oracles** — sympy `assert_is_integral_of` /
   in-diff derivative checks make expectation changes self-auditing;
   recognizable as compensation.
8. **Tri-state `is None`** — graded NON_NULL(30) where `None` is an exact
   domain value (sympy ceca5c64, a31843cd).

## Disagreements — RESOLVED

**Owner resolution, 2026-09-01: rater 2's labels adopted as final for
items (1)–(4) below.** The final dataset labels are therefore exactly the
per-block verdicts above: 67 FP / 7 TP-policy / 0 UNCERTAIN. Item (5) is
a scope question, not a label disagreement; it remains open as
[#54](https://github.com/taipei49314/checkwash/issues/54). The original
list is kept verbatim for the record:

1. **aiohttp c52fe79c, 79b5f5fa** — rater 1: plausible policy blocks;
   rater 2: FP (compensation visible in-diff). Owner to resolve.
2. **aiohttp cd0556b2** — rater 2 adds TP-policy where rater 1 did not
   single it out.
3. **black (16)** — same FP verdicts, different *cause*: rater 2
   reclassifies the family from per-commit cost to one reproducible engine
   defect (changes the fix, not the label).
4. **Newly labeled TP-policy** (rater 1's tables carried these inside FP
   cost aggregates): pydantic 800f2f9, sympy 98dff817, httpie 18bb49b,
   httpie ff6f188 (narrow), tornado b7447c1. pandas 518f2a3 both raters
   already treated as by-design.
5. **sqlalchemy 7776cfbf** — out-of-thesis supply-chain weakening: does
   checkwash want a supply-chain family, or is that scope creep?
   SPEC-level decision, owner-only per AGENTS.md.

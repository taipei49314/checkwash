# JS/TS history-replay corpus: results

Every number on this page is **in-sample** and names the two engines it
compares (SPEC §10.2 rule 1). None is a false-positive rate: no block on this
set has been adjudicated as a true or a false block. The class is ruled in
the [selection record](README.md).

Each release compares the previous release with its candidate on these
1,800 commits before its tag, and every commit whose outcome moves, except
an error that becomes a pass, goes to the owner first
([release procedure](../../docs/RELEASING.md#before-the-tag-the-fixed-corpus-comparison)).
The first two runs below were made before that step existed. Both count as its
results (owner ruling 2026-10-19, R27).

## Method

The first two runs used a checkwash-lab harness that calls the CLI once per commit
and engine, `check <parent>..<commit> --repo <clone> --format json`, with
the commit's first parent, and records each call's exit, verdict, findings
and stderr. Neither used `checkwash sweep`, the method the 2026-10-06 shape
names ([selection record](README.md)). So neither records
`commits_with_opaque_prod_change`, which only `checkwash sweep` writes
(`src/checkwash/sweep.py:71`): how many of these commits carry an opaque
production change is not known. How many passes rest on opaque-change
evidence is left instead to `cf-js131`, a report-only arm of #419's
combined lab sweep (owner ruling 2026-10-19, R30;
[#212](https://github.com/taipei49314/checkwash/issues/212#issuecomment-6261643029)).

`pass` and `block` are the verdicts of an analysed commit. `error` is an
exit 2, an input or engine error with no verdict.

## Run 1: v0.6.0 against the v0.7.0 candidate

| Item | Value |
|---|---|
| Purpose | v0.7.0 release preparation, reviewed before the v0.7.0 tag |
| Engines | v0.6.0 (`8c70efb`) and the preparation candidate, source `0d6c5ec4`, tree `5eb8336d`, each run as a qualified CLI artifact |
| Members | six repositories × 300 non-merge commits; `javascript-pairs.json`, SHA-256 `38ee9c2e…` |
| Host | EC pool (checkwash-lab workload `v070-release-cost`), three first-attempt batches |
| Record | [v0.7.0 release guide](../../docs/releases/v0.7.0-public-launch.md), "Complete fixed preparation evidence"; D-128 |

| v0.6.0 → candidate | Commits |
|---|---:|
| pass → pass | 1,734 |
| block → block | 37 |
| pass → block | 2 |
| pass → error | 27 |
| **total** | **1,800** |

The two new blocks are fixed ordinals 759 and 1362. The release guide names
their compatibility and expected-receiver alias limits. The 27 refusals are
lost analysed coverage. The owner's 「核准」 of 2026-10-12 accepted both, with
the raw findings unchanged: the two blocks as disclosed bounded risks, and
the 27 refusals among the 54 coverage losses (`STATE.md`, 2026-10-12). The
two blocks were not adjudicated as true or false.

## Run 2: v0.7.0 against v0.8.0

| Item | Value |
|---|---|
| Purpose | the `javascript` batch of the v0.8.0 acceptance sweep |
| Engines | v0.7.0 `d647a65` and v0.8.0 `f02b5d8`, the two release commits, each run from its `src/` tree |
| Members | 300 commits for each of the six repositories, each pinned commit of the selection among them; members SHA-256 `89d74c73…` |
| Host | LAPTOP-01AGNPJU under EC POLICY `checkwash-pju-sweep` (T-546), with manifest SHA-256 `c5bdcf0b…619ab4` approved before the run; labelled "human-authorized local PJU, NOT EC pool"; 12 in parallel |
| Time | 2026-10-15, 16:34:32Z to 17:38:39Z; 60 shards, each exit 0 |
| Record | checkwash-lab `954d802b`, `runs/acceptance-sweep-v080/20261016-pju/` (harness at `793fe135`) |

v0.8.0 was published at 17:00:03Z, while this batch ran. The owner had
chosen to release first and run the acceptance sweeps after publication
([release procedure](../../docs/RELEASING.md), v0.8.0), so this run was no
condition of the v0.8.0 tag.

| v0.7.0 → v0.8.0 | Commits |
|---|---:|
| pass → pass | 1,734 |
| block → block | 39 |
| error → pass | 25 |
| error → error | 2 |
| **total** | **1,800** |

No verdict moved: no pass → block, block → pass or analysed → error. The
harness compares each commit's outcome, verdict, finding keys and error. It
lists 27 changed rows, all of them v0.7.0 errors, and none among the 1,773
commits both versions analysed.

- **Error → pass, 25.** v0.7.0 refused a source over the 1,000,000-byte
  limit: luxon's `package-lock.json` (15 commits) and undici's
  `test/web-platform-tests/expectation.json` (10). v0.8.0 carries these
  files unread and passes, with the unread note (#415, D-135). What
  checkwash cannot see in the undici file is #468.
- **Error → error, 2.** Both versions refuse a symlinked source before any
  analysis: apollo-client `8a51ea63` (`.agents/skills/apollo-client`) and
  undici `0f1f8903` (`docs/README.md`).

## Run 3: v0.8.0 against the v0.9.0 candidate

This release comparison ran on 2026-10-20, 17:33:41Z to 18:55:19Z,
alongside the Python standard set. It used the same first-parent CLI
method with v0.8.0 `f02b5d8a07fa39ee1898881f66c571eb164cb11c` and candidate
`7d173fe8f26fb84362aa0a2adb69b4e8cb564622`, source tree
`17c3dd82bf597daa12e1257052e3b71f3323ca95`. The venue was human-authorized
local Linux Docker, **not EC pool**, under the explicit
[0.9.0 session grant](../../docs/RELEASING.md#v090-session-publication-authorization-2026-10-21);
Python 3.11.16. The source-bound
[record](../release-comparison/v0.9.0.json) names the manifest, raw-evidence
archive and verification hashes.

| v0.8.0 -> candidate | Commits |
|---|---:|
| pass -> pass | 1,759 |
| block -> block | 39 |
| error -> error | 2 |
| **total** | **1,800** |

No mandatory movement-review item was found across either set. Codex
recorded the complete comparison disposition under the session delegation;
it is not a claim of personal maintainer review. Both symlink refusals
listed in Run 2 remain errors with identical stderr in the two engines.
The 39 blocks remain unadjudicated. This is an in-sample comparison, not
a false-positive rate, and it does not replace the combined acceptance
sweep or other release gates.

## What these runs do not show

- **A false-positive rate.** The 39 commits that v0.7.0 and v0.8.0 both
  block are not adjudicated, so how many of them are false blocks is
  unknown. Run 1's two new blocks are not adjudicated either.
- **A held-out rate.** The set is in-sample. A held-out JS/TS measurement
  needs a new draw in `checkwash-corpus`, recorded before any engine runs
  on it (SPEC §10.2 rule 2). None is planned now (owner ruling 2026-10-19,
  R27): while the JS/TS rules still change, such a number goes stale with
  the next JS/TS round (rule 4).
- **The opaque share** (see Method).
- **Per-repository and per-rule counts.** They are not published here. Run
  1's are in its retained preparation receipts. Run 2's per-commit results
  stay on its host; the lab archive holds only the aggregate.

The counts above are copied from the records named in each table; the
repository split of run 2's errors is read from the harness's
`first-arm-errors.json`. Nothing was run again for this page.

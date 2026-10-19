# JS/TS history-replay corpus: the selection

**Correction (2026-10-09):** see [the additive correction](correction-2026-10-09.md) for the actual reading chronology, runner-evidence limits, omitted exclusions and the still-unverified held-out qualification; the original record below is preserved, except its last section, which the 2026-10-19 rulings replaced (**Decided**, below).

checkwash measures its Python false-positive cost on a fixed sweep of six
repositories, 300 non-merge commits each ([`../sweeps/`](../sweeps/README.md)).
JS/TS had no such corpus. The only JS history record is the 14-file diagnostic
sample in [`../javascript-history/v0.4.2/`](../javascript-history/v0.4.2/README.md),
which says it is not a representative false-positive rate. #212 is that corpus.

The maintainer ruled its shape on 2026-10-06:

- six JS/TS repositories, and the last 300 non-merge commits of each (1,800
  commits), run as consecutive whole-commit windows with `checkwash sweep`;
- the repositories, remotes, pinned commits and windows are recorded before
  any engine runs on them (SPEC §10.2 rule 2);
- the record and the results live here, under `benchmarks/`.

[`selection-2026-10-07.json`](selection-2026-10-07.json) is that record. It was
written before any checkwash engine ran on these histories. To confirm each
repository's runner and layout, the selection read only its package manifest
and its test-file paths at the pinned commit.

| repository | runner | layout | pinned commit |
|---|---|---|---|
| moment/luxon | Jest | `test/` | `f427515a38f6` |
| apollographql/apollo-client | Jest | `__tests__/` | `0cf7ebd59305` |
| honojs/hono | Vitest | colocated `*.test.ts` | `5f36607f67aa` |
| vuejs/core | Vitest | `__tests__/*.spec.ts` | `4ab865a848a1` |
| typeorm/typeorm | Mocha with chai | `test/` in a package | `67991e8d8299` |
| nodejs/undici | node:test | `test/` | `2def92487020` |

**Window.** A window is the 300 newest non-merge commits reachable from the
pinned commit (`git rev-list --no-merges -300 <commit>`). Each commit is
judged against its first parent, as `checkwash sweep` judges it. Every
repository has more than 300 such commits.

**Excluded.** Every repository the JS rounds, fixtures or replays have
already run on is left out. Their histories are in-sample, and the JSON lists
them.

**Decided (2026-10-19).** The rulings of 2026-10-06 and 2026-10-08 left two
of #212's questions for the release that ships the JS rounds: the class and
the release criterion. The owner ruled them, and what #212 delivers, on 2026-10-19
(owner ruling 2026-10-19, R27–R30):

- **Class: in-sample** (R28). SPEC §10.1 settles it: findings on the set,
  among them the two blocks the v0.7.0 candidate added, were read during
  the v0.7.0 preparation, which registered the set in-sample and nonblind
  (D-128), and #468 was triaged from undici's results in the v0.8.0
  acceptance sweep. In-sample is permanent for a repository, so these six
  can never be held out. They join axios, express and commander
  ([correction](correction-2026-10-09.md)) on the exclusion list of every
  future held-out draw. Recording them in `checkwash-corpus`
  (`records/holdout/spent-elsewhere.json`) is a write to that repository.
  It is pending its own authorization, together with #419's polyglot
  repositories.
- **What #212 delivers** (R27): each release compares the previous release
  with its candidate on these 1,800 commits. The two runs made so far count
  ([results](results.md)). A new held-out draw is not planned now.
- **Release criterion** (R29): a standing step of the
  [release procedure](../../docs/RELEASING.md). Every commit whose outcome
  moves, except an error that becomes a pass, goes to the owner before the
  tag. There is no rate threshold.
- **Row 131** (R30). THREATMODEL row 131 stays with #212. The report-only
  `cf-js131` arm of the combined lab sweep prices it, under a line
  registered before it runs (D-141, arm 7). #212 stays open for that.

Both runs checked each commit with `check`, one CLI run per commit and
engine, not with `checkwash sweep` as the shape above says
([method](results.md#method)). The selection JSON is the pre-run record and
keeps its `class: null`.

A JS/TS round's pull request no longer cites #212 for its false-positive
cost: the next release's comparison checks it. Statements already in open
issues stay as written.

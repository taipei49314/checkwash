# JS/TS history-replay corpus: the selection

**Correction (2026-10-09):** see [the additive correction](correction-2026-10-09.md) for the actual reading chronology, runner-evidence limits, omitted exclusions and the still-unverified held-out qualification; the original record below is preserved.

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

**Not decided yet.** The corpus gates the release that ships the JS rounds,
not their merges. Two of #212's questions are asked again when that release is
prepared:

- its class, in-sample or held-out (SPEC §10). No engine has run on these
  windows, so either label is still open;
- the release criterion.

The measurement compares that release's candidate with v0.6.0 on the same
windows. Its results will be added beside this record, labelled as SPEC
§10.2 requires.

# What is stable, what is not, and how you will be told

greenwash is `0.1.x`. That is not modesty and it is not a placeholder — it is
a statement about one specific thing, and everything else here is more stable
than the version number suggests. This page says which is which, because
"pre-release" on its own tells you nothing you can plan around.

## Frozen: change here is a breaking change

These are contracts. If one of them changes, the version's minor number
changes with it and `DECISIONS.md` carries the entry explaining why.

| contract | where it lives | what it means for you |
|---|---|---|
| Rule IDs | `SPEC.md` §4 | `ASSERT_WEAKENED` will never be renamed or reused for something else. Your allowlist entries and your log greps keep working |
| Severity model | `SPEC.md` §5 | Every detector reports at `warn`; only the escalator table promotes to `high`/`critical`. A detector will never start blocking on its own |
| Exit codes | `SPEC.md` §9 | `0` pass, `1` block, `2` engine error. A crash is never reported as a block — that distinction is gated by an end-to-end test, because it once was not |
| Finding fingerprints | `src/greenwash/findings.py` | A recorded exemption keeps matching. This has cost the project real features: a guard was deliberately kept out of marker identity so existing allowlists would survive (THREATMODEL 54, later closed another way) |
| IR / findings schema version | `greenwash.IR_VERSION`, `greenwash_findings_version` | `--format json` and `--emit-ir` output stays parseable. A shape change bumps the number |
| Config schema | `SPEC.md` §1, §6 | `.greenwash/config.toml` keys keep their meaning. A malformed config is reported, never silently ignored |
| Determinism | `SPEC.md` §8 | Same diff, same verdict — byte-identical across Linux, macOS and Windows on Python 3.11–3.13. Proved on every push by a job that diffs artifacts from all nine matrix legs |
| Zero runtime dependencies | `pyproject.toml` | Gated by a test. It is what makes the single-file build possible |
| Never executes your code | the whole design | greenwash reads ASTs. It does not import, run, or evaluate anything in the diff |

## Not frozen: this will change, on purpose

**Detector coverage grows, and growth can newly block something.** That is the
product. A diff that passed on v0.1.7 may block on v0.1.8 because a bypass was
closed — this has happened repeatedly and the whole ledger is in
`THREATMODEL.md`. Pin a version in CI if you need a stable gate; upgrade
deliberately, read the release notes, and expect the block set to move.

**The numbers move too.** The false-positive rate is re-measured against a
1800-commit corpus after every change that could affect it, and the
progression — including the round where closing a recall hole *raised* the
rate — is published in `benchmarks/README.md`.

## What "0.1.x" is actually saying

One thing: **the false-positive rate is not yet low enough to be invisible.**
It is 1.11% on 1800 human commits, adjudicated by three raters. On a
thousand-commit month that is roughly eleven commits a reviewer has to look at
and wave through. That is workable with the per-fingerprint exemption flow and
it is not nothing, and until it is smaller this stays 0.x.

Two further things a 1.0 would need, both open:

- **Python only.** A production file greenwash cannot read suppresses
  escalation for the whole diff (`THREATMODEL.md` #4). That share is measured
  and published rather than assumed, and a JS/TS frontend is what narrows it.
- **A bypass list that stops growing.** Six rows are marked **Open** outright
  today and four more are open-by-design or open-in-part. Every one is written
  down with the shape and the reason. The discovery rate has not levelled off,
  and the project says so in `STATE.md` rather than waiting for someone else
  to notice.

## How you will be told

- **Release notes** on every tag, with what moved and what it cost.
- **`THREATMODEL.md`** — every bypass, its status, and the fixture pinning it
  when it is closed. A row marked Closed with nothing behind it fails the test
  suite.
- **`DECISIONS.md`** — why, including the decisions that were wrong and were
  reversed. Two false positives shipped in one day are recorded there under
  the versions that introduced them.
- **`benchmarks/RESULTS.md`** — generated from the harness, never hand-typed.

## Upgrading

```bash
greenwash --version                 # what you have
greenwash check HEAD~1..HEAD        # what it says now
```

If a new version blocks something it used to pass, that is either a bypass
closing or a false positive shipping — and this project has done both. Read
the release notes; if it is the second, an issue with the diff is the most
valuable thing you can send, and it becomes a regression fixture with your
name on it.

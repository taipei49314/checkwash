# What is stable, what is not, and how you will be told

checkwash **v0.3.1 is alpha** (engine v0.3.0). Its versioned interfaces and
release checks support deliberate adoption, but its coverage, false-positive
cost and adoption evidence do not meet a 1.0 claim. This page separates those
contracts from the work still required. The
[public-launch brief](releases/v0.3.0-public-launch.md) records this release's
evidence and limitations.

**v0.3.0 (2026-09-07):** five file-wide rules have content-bound v2
fingerprints and retire their old path-only exemptions. This intentionally
breaks the matching promise below for those namespaces; existing v0.2.13
installations retain their broad keys. IR and findings versions are 2 since
v0.3.0 and 1 in v0.2.13. Read the [migration procedure and
runtime limits](remediation-upgrade.md) before upgrading.


> **Known break: v0.1.19 violates this guarantee on Python 3.13** and no
> release was cut for it. `ast.dump` was used as a structural key and its
> output tracks the AST's internal field set, which changes between Python
> releases. Fixed in v0.1.20 (D-038). Only the nine-way matrix could see it;
> every single-interpreter check passed.

## Frozen: change here is a breaking change

These are contracts. If one of them changes, the version's minor number
changes with it and `DECISIONS.md` carries the entry explaining why.

| contract | where it lives | what it means for you |
|---|---|---|
| Rule IDs | `SPEC.md` §4 | `ASSERT_WEAKENED` will never be renamed or reused for something else. Your allowlist entries and your log greps keep working |
| Severity model | `SPEC.md` §5 | Every detector reports at `warn`; only the escalator table promotes to `high`/`critical`. A detector will never start blocking on its own |
| Exit codes | `SPEC.md` §9 | `0` pass, `1` block, `2` engine error. A crash is never reported as a block — that distinction is gated by an end-to-end test, because it once was not |
| Finding fingerprints | `src/checkwash/findings.py` | Within a compatible release line, a recorded exemption keeps matching. v0.3.0 deliberately retires five path-only namespaces; its [upgrade notes](remediation-upgrade.md#reviewed-exemptions) define the break and re-review process. Other namespaces keep their identities |
| IR / findings schema version | `checkwash.IR_VERSION`, `checkwash_findings_version` | `--format json` and `--emit-ir` are versioned machine interfaces. A shape change bumps the number; see the pre-rename compatibility note below. `--format sarif` is a separate 2.1.0 projection (T2.1), not this schema |
| Config schema | `SPEC.md` §1, §6 | Both `.checkwash/config.toml` and `.greenwash/config.toml` are supported, with the precedence below. A malformed config is reported, never silently ignored |
| Determinism | `SPEC.md` §8 | Same diff, same verdict — byte-identical across Linux, macOS and Windows on Python 3.11–3.13. Proved on every push by a job that diffs artifacts from all nine matrix legs |
| Zero runtime dependencies | `pyproject.toml` | Gated by a test. It is what makes the single-file build possible |
| Never executes your code | the whole design | checkwash statically reads the diff. It does not import, run, or evaluate code under review |

Configuration and allowlists are read from the base of the reviewed diff.
For each filename, `.checkwash/` takes precedence over `.greenwash/` when both
contain that file. The `allow` writer and `doctor` use the matching file if it
exists, then an existing configuration directory (`.checkwash/` first). A
repository with neither directory still defaults to `.greenwash/`; this
release does not migrate that default. Protect both directories in
[CODEOWNERS](enterprise.md#4-codeowners).

## Machine findings contract (`FINDINGS_VERSION` / `IR_VERSION`)

`--format json` is the machine interface. Both numbers are **1 in
v0.2.13** and **2 since v0.3.0**. The envelope keys
below remain; the v0.3.0 IR adds reviewed-change evidence described in the
[upgrade notes](remediation-upgrade.md#machine-interfaces-and-sarif).

`checkwash.FINDINGS_VERSION` is the envelope. Current keys, closed:

| key | meaning |
|---|---|
| `checkwash_findings_version` | integer; this table |
| `run.base` / `run.head` | revision labels, not timestamps |
| `run.checkwash_version` | package version string |
| `findings` | array of finding objects |
| `summary` | counts for `info`, `warn`, `high`, `critical` |
| `skipped_files` | unparseable paths |
| `config_errors` | parse failures for base-side config/allow |
| `verdict` | `pass` or `block` |

Each finding object is the dataclass field set of `Finding`: `rule`,
`severity`, `message`, `path`, `unit`, `before`, `after`, `escalators`,
`deescalators`, `fingerprint`, `allowlisted`, `strength_drop`,
`strength_after`, `subject_changed`, `shape`. Evidence objects have
`text` and `span` (character offsets into CRLF→LF-normalized source).

`checkwash.IR_VERSION` is `--emit-ir`. The IR is a dataclass tree
serialized by `to_jsonable` (tuples become lists). A consumer should
key on `version` inside the payload, not on field order.

`--format sarif` is a **projection** of the same findings into SARIF
2.1.0. It does not bump `FINDINGS_VERSION`. Allowlisted findings are
omitted there.

**Pre-rename compatibility:** v0.2.12 and v0.2.13 emit the `checkwash_*` keys above,
with `FINDINGS_VERSION = 1`. Older consumers expecting
`greenwash_findings_version` or `run.greenwash_version` must adapt explicitly;
the legacy `greenwash` CLI alias does not provide aliases for JSON keys. The
rename is therefore a compatibility exception to account for when upgrading,
not evidence of an unchanged machine interface.

### When the number moves

- **Bump `FINDINGS_VERSION` or `IR_VERSION`** if a field is renamed,
  removed, or changes meaning, or if a required key is added.
- **Do not bump** for a new optional field, a new rule id, or a new
  `--format`. Rule ids themselves are frozen (table above).
- A bump is a breaking change: the minor version moves with it and
  `DECISIONS.md` records why. Pin the package in CI if you parse JSON.

`--format json` remains sorted keys, `ensure_ascii=False`, LF, UTF-8
bytes, no timestamps (SPEC §8).

## Not frozen: this will change, on purpose

**Detector coverage grows, and growth can newly block something.** That is the
product. A diff that passed on v0.1.7 may block on v0.1.8 because a bypass was
closed — this has happened repeatedly and the whole ledger is in
`THREATMODEL.md`. Pin a version in CI if you need a stable gate; upgrade
deliberately, read the release notes, and expect the block set to move.

**The numbers move too.** Re-measurement after behavior changes is the intended
procedure; published evidence must say what actually ran. The committed
1800-commit sweep artifacts record v0.3.0 (swept 2026-09-07 from the release
commit). `STATE.md` records that v0.2.11 to v0.2.13 carried the v0.1.46 baseline
forward without a fresh full sweep, because the corpus does not contain the
affected configuration directories. Original evidence
and the progression — including increases in false positives — are published
in [benchmarks/README.md](../benchmarks/README.md).

## Coverage and adoption cost

Python is the primary frontend. JS/TS support scans named `test`/`it` units
and a fixed set of `expect(...).matcher(...)` calls in `*.test.*` and
`*.spec.*` files with `js`, `jsx`, `ts`, `tsx`, `mjs`, or `cjs` extensions.
It is a bounded text scan, not a full JavaScript parser or a general assertion
library model. JS/TS production semantics remain unread; a production change
the engine cannot parse can still suppress escalation through the documented
opaque-change rule. A second-language checkbox does not establish broad
coverage.

The tracked six-repo sweep (engine 0.3.0, 2026-09-07) recorded **31 false
positives out of 1800 commits (1.72%)**, on a corpus used to tune the
detectors. Its adjudication combines an older three-rater study, later
two-rater additions and maintainer-only additions; the kappa is not a study
of all 46 entries in that adjudication.
The dedicated honest-refactor corpus instead has **22 blocks out of 60
(36.7%)**. These are different populations, and neither predicts another
repository's review cost. Original versions, dates and adjudication scope are
in [benchmarks](../benchmarks/README.md).

Known limitations remain in the [September catalog](adversarial-catalog-2026-09.md)
and [THREATMODEL](../THREATMODEL.md). A closed row means its named case has
evidence behind it, not that every variant is impossible. A growing catalog
can reflect better discovery; hiding new rows would not make adoption safer.

## What must change before 1.0

**Status: NOT MET.** Public availability as v0.3.1 is not a 1.0 readiness
decision. The release needs an evidence-backed acceptance review covering:

| Area | Evidence needed before a 1.0 decision | Current gap |
|---|---|---|
| Known low-cost failures | A dated catalog, an explicit in-scope priority set, case-level closure evidence and owner-accepted residuals | Remaining open work in the September catalog must retain its actual status; a summary cannot mark it closed |
| Adoption | Independently maintained repositories using an actual required check, with a recorded observation period and enough reviewed changes to exercise it | No completed adoption cohort is established by these documents |
| Refactor cost | Pre-agreed acceptance thresholds, adjudicated false blocks and review/exemption workload, measured on both dedicated refactors and adoption repositories | The 22/60 dedicated-refactor result (`benchmarks/refactors/expected.json`) remains a material adoption cost |
| Interfaces and operations | Version-specific compatibility notes and release qualification tied to the shipped artifacts | The pre-rename JSON compatibility exception and Action trust lag must be visible to adopters |

**Adoption-study proposal, not an adopted release threshold:** at least three
independently maintained repositories, 30 consecutive calendar days and at
least 20 reviewed changes per repository. The maintainer must agree the
cohort, traffic minimum and health thresholds before this can be used as a
gate. Record false blocks, exemptions and their review cost, engine errors,
required-check disablement and resolution time; an idle repository does not
demonstrate healthy usage. Where used, smallestlie contributes its actual
adoption results and limitations, not a readiness endorsement by association.

The next-quarter engineering focus is **refactor false positives**: shared
helpers, unit identity changes and the documented tradeoffs in the dedicated
corpus. Agree the desired reduction and acceptable coverage tradeoffs before
changing detector or de-escalation behavior. That program is separate from
the 0.2.x documentation and adoption fixes.

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
checkwash --version                 # what you have
checkwash check HEAD~1..HEAD        # what it says now
```

The v0.3.1 documentation pins the Action to v0.3.0 under the one-release
trust-lag policy; v0.3.1 is a documentation and metadata release on the v0.3.0
engine, so the pinned Action and the CLI run the same detector logic (D-057).
Treat each installed surface as its own versioned dependency; see the
[README](../README.md#required-check--the-only-configuration-that-blocks-a-merge).

If a new version blocks something it used to pass, that is either a bypass
closing or a false positive shipping — and this project has done both. Read
the release notes; if it is the second, an issue with the diff is the most
valuable thing you can send, and it becomes a regression fixture with your
name on it.

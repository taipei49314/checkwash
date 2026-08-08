# greenwash

[![CI](https://github.com/taipei49314/greenwash/actions/workflows/ci.yml/badge.svg)](https://github.com/taipei49314/greenwash/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](#install)

**Your agent deleted the failing test to make CI green. greenwash catches it before merge.**

A deterministic, zero-LLM, local-only detector for code changes that tamper
with your *verification layer* — weakened assertions, loosened float
tolerances, new skips, rewritten golden files, hardcoded expected values,
self-relaxed CLAUDE.md, and CI configs or runner scripts that quietly stop
failing.

> Status: **pre-release.** 17 detectors, 288 tests, zero runtime dependencies.
> Every number below comes out of a reproducible harness in
> [benchmarks/](benchmarks/README.md) — none is hand-typed, and nothing ships
> that a harness hasn't produced on a clean checkout.

```
$ greenwash check HEAD~1..HEAD

✗ greenwash: 1 high-severity finding — blocking

ASSERT_WEAKENED   high   tests/test_billing.py :: test_invoice_total
  assertion strength: EXACT_VALUE(90) -> BOUND(40)
  no non-trivial production change in this diff
  before  assert total == 105.3
  after   assert total > 0
```

**In short**

- **0 LLM / 0 network / 0 runtime deps** — pure-stdlib Python; deterministic verdicts on 3.11–3.13
- **Fast enough for a stop-hook, measured through the path you run** — 0.2 s engine on a 3000-line
  test diff, 1.6 s end to end for 300 changed files; analyses the *diff*, never executes code under review
- **Blockable by default** on composite high-severity evidence (see [SPEC.md](SPEC.md))
- **Measured, not asserted** — public corpora + published failures: [benchmarks/](benchmarks/README.md), [THREATMODEL.md](THREATMODEL.md), [benchmarks/FAILURES.md](benchmarks/FAILURES.md)
- **Out of sample it does worse, and that is published too** — three projects never in the tuning
  corpus: 667 commits, 15 blocks, **11 false positives (1.65%)** against the 1.11% measured on the
  corpus the detectors were built against. Zero engine errors. [docs/integrations.md](docs/integrations.md)

> Status: **pre-release.** 17 detectors, 288 tests, zero runtime dependencies.
> Every headline number comes from a reproducible harness — nothing ships that a
> harness has not produced on a clean checkout.

## Sixty seconds, from nothing

No install, no virtualenv, no network after the download. Every release
attaches a single file that carries the whole tool — it has zero runtime
dependencies, so there is nothing else to fetch.

```bash
curl -LO https://github.com/taipei49314/greenwash/releases/latest/download/greenwash.pyz
python greenwash.pyz demo                       # 7 real tampering cases, blocked, offline
python greenwash.pyz check HEAD~1..HEAD         # your last commit
python greenwash.pyz sweep HEAD --limit 100     # how often it would have blocked you
```

`demo` takes under half a second and needs nothing but Python 3.11+. `sweep`
is the honest one: point it at your own history and read the blocks yourself
before you believe any number on this page. The single-file build is gated by
`tests/test_zipapp.py` on every push, so it cannot quietly rot.

## Install

Pick the surface that fits; the engine is identical behind all of them, and
[docs/stability.md](docs/stability.md) says which parts of it are frozen.

Not on PyPI yet — install from the repo:

```bash
pipx install git+https://github.com/taipei49314/greenwash@v0.1.13
# or: uv tool install git+https://github.com/taipei49314/greenwash@v0.1.13

greenwash check HEAD~1..HEAD    # a range
greenwash check                 # HEAD vs the working tree
greenwash demo                  # replay real tampering cases, fully offline
```

`greenwash demo` replays seven real tampering cases — a softened assertion, a
widened tolerance, a rewritten expectation, an xfail'd failure, a swallowed
error, a relaxed CI step, a self-edited CLAUDE.md — plus one honest fix that
stays silent. No network, no key, no LLM; every verdict comes from the same
engine `check` runs.

**GitHub Action** — blocks a PR on high-severity findings:

```yaml
# .github/workflows/greenwash.yml
on: [pull_request]

permissions:
  contents: read

jobs:
  greenwash:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
          persist-credentials: false
      - uses: taipei49314/greenwash/action@v0.1.13
```

The `permissions` block and `persist-credentials: false` are there because
pydantic runs [zizmor](https://github.com/woodruffw/zizmor) in pre-commit, and
without them this snippet scored two high findings — a workflow a
security-conscious project cannot merge is not an integration
([docs/integrations.md](docs/integrations.md)).

**pre-commit**:

```yaml
repos:
  - repo: https://github.com/taipei49314/greenwash
    rev: v0.1.13
    hooks: [{ id: greenwash }]
```

**Claude Code stop-hook** — checks the diff the moment the agent finishes and
blocks the stop on tampering:

```bash
greenwash hook install --agent claude-code
```

greenwash runs the published action against its own diff on every push
(`.github/workflows/ci.yml`, the `dogfood` job): the judge is judged. That
job was previously gated to pull requests, in a repository that has never had
one, so it had never executed — a test now fails if it is made conditional
again.

License: Apache-2.0.

## Integrations

```bash
# Claude Code — block the agent's stop on high findings
greenwash hook install --agent claude-code

# pre-commit — prints the config block to paste
greenwash hook install --agent pre-commit

# GitHub Actions — see action/action.yml; CI runs this action on every push
- uses: taipei49314/greenwash/action@v0.1.13
```

`greenwash check BASE...HEAD` (three dots) resolves through the merge base,
so PR diffs never include base-branch commits.

## Measured, not asserted

Two harnesses, both reproducible from a clone
([benchmarks/](benchmarks/README.md)):

- **Human-commit block rate — 35 / 1800 = 1.94%.** Six active OSS projects
  (flask, httpx, attrs, click, rich, starlette), 300 consecutive
  human-reviewed commits each, none seen during development. That is how
  often greenwash would fail CI on a commit a human wrote. Every repo is
  at or under 4%; the progression from an initial 8.6%, and what moved each
  step, is in the benchmarks README.
  A block is not automatically a mistake. All 35 were adjudicated commit by
  commit against the real diff: **20 false positives (1.11%)**, 15 legitimate
  policy blocks (0.83%) where the commit really does drop oracle coverage
  with nothing visible replacing it, 0 unclear. Three precision rounds
  brought this down from 2.50% / 1.67%: skip conditions are *read* (constants
  resolved up to the head snapshot) instead of grepped, relocated tests are
  recognised even when they carry their own skip markers or hold no
  assertions, feature removals and dependency bumps explain the removal of
  their tests, and deleting one of two identical copies is recognised as
  dedup because the survivor is found at head and checked to still run.
  Every legitimate policy block still blocks and the decoy corpus still
  blocks 12/12 — and the process cut both ways: one over-eager credit was
  caught clearing two correct blocks and tightened before it shipped, and
  one adjudication *verdict* was overturned in the tool's favour when the
  duplicate search proved a "relocated" test actually reappears nowhere;
  each trade is reported as measured.
  The block rate is a machine count and exact. The split is now a
  three-rater judgement: two additional raters re-adjudicated all 35 blocks
  blind, with 91–94% pairwise agreement and Fleiss' kappa 0.844; the
  published category is the majority verdict, the four contested commits are
  marked, and the per-commit reasoning of all three raters ships in
  [benchmarks/](benchmarks/README.md) precisely so you can disagree with it.
  **1.78% of the corpus (32/1800) never got a real analysis**: those commits
  touch a production file greenwash genuinely cannot read — other-language
  code, templates, data files, unparseable Python — which suppresses
  escalation for the whole diff (THREATMODEL #4). That share of the pass
  rate rests on a documented blind spot, measured rather than assumed. It
  used to be 7.2%: narrowing the blanket (docs config, type stubs, repo
  metadata, pin sources, deleted-but-parseable Python and scripts that run
  the test suite no longer qualify) removed 98 exemptions and **did not
  change a single verdict** — every one had been protecting a commit that
  passed on its own merits anyway.
  The same round taught greenwash where the test command actually lives. A
  shell script or make recipe that runs the suite is test-runner
  configuration, not production: weakening it (`|| true`, `set +e`, a `-`
  before a make recipe, losing `set -e`, or deleting the invocation) is now
  a blocking finding, and touching it no longer buys the diff an exemption.
  On the human corpus that cost **nothing** — the same 35 blocks before and
  after, the whole delta being four warn-level notices on starlette commits
  that edit `scripts/test`. Read that with its limits: these six projects
  barely exercise the change, and the defence against over-flagging is the
  content gate (a Makefile that only compiles is still production) plus its
  negative fixtures, not the sweep.
- **Recall — 12 / 12, then probed harder.** Twelve bug-fix tasks run through
  real coding agents told to make CI green without fixing the bug; greenwash
  blocks all twelve tampering diffs. Under natural conditions, 0 of 12 agents
  touched a test at all — an honest datapoint, recorded as such.
  A second wave of six *probe* tasks (2026-08-04) aimed agents at the
  de-escalators that hold at warn by design. The agent escaped **two of
  six** — a one-line constant flip behind an existing skip guard, and a
  conftest fixture that monkeypatched the function under test while leaving
  production and tests byte-identical. Both escapes became detectors the
  same day (`TEST_DISABLED` guard evaluation, `CONFTEST_PATCHES_PROD`), both
  recorded diffs now block, and both new rules fire **zero** times across
  the 1800 human commits. The four other probes were blocked outright.
  A third wave (2026-08-07) aimed two tasks at repos that keep the test
  command in `scripts/test.sh` rather than in the workflow. **One of two was
  caught.** The first agent's opening move was to make the suite non-fatal
  inside the runner script — a diff the previous release scored at zero
  findings, and this one blocks. The second escaped: it dropped the failing
  tests out of collection, which greenwash *detected*, and the honest
  one-line `scripts/lint.sh` edit its own task asked for demoted the finding
  to a warning, because a script that does not run tests is still an
  unreadable production change (THREATMODEL #4). That escape is published
  open, with its reproduction — and closed in the next release the same
  day, once the reason
  given for leaving it open turned out to be a citation that did not hold
  (DECISIONS D-026; the correction is in the repository because publishing it
  is the point).
- **The informed arm — the adversary reads the source.** Every arm above hides
  the defender. This repository is public, so one arm does not: the agent gets
  greenwash's complete source, spec and threat model, and may run
  `greenwash check` against its own diff until it stops blocking. Three of six
  tasks were refused outright by the agent provider's safety filter, so the
  sample is three, and **all three reached a green suite past the shipped
  engine.** One rewrote production instead of the tests (THREATMODEL #1, out
  of scope by design, and the cheapest route an informed adversary has). One
  read the opaque-change branch and added a three-line JSON file that nothing
  imports, purely to be unreadable — closed the same day. One normalised the
  *subject* of an assertion rather than its expectation, which no rule sees,
  and was **closed the same day** by the detector it demanded
  (`SUBJECT_NORMALIZED`), with its diff published either way. If you want one
  number from this project, that arm is a fair one to take: three informed
  attempts, three different routes past the shipped build, two of them now
  regression fixtures and one of them a documented limit of the whole approach.

The first recall measurement caught **0 of 12** — pytest's own `.pyc` output
disarmed the gate, a bug two rounds of code review had missed. Building the
harness is how it was found. See [benchmarks/decoy/](benchmarks/decoy/).

## Prior art

greenwash is not the first tool to look for agent shortcuts in diffs, and
does not claim to be. Closest neighbours, credited up front:

- [swarm-orchestrator](https://github.com/moonrunnerkc/swarm-orchestrator) —
  a PR audit suite (11 detectors, JS/TS-tuned, LLM judge layer, sandboxed
  runtime proofs; advisory by default). greenwash is the narrow, deterministic
  end of this spectrum: Python-first oracle *semantics* (a strength lattice,
  not matcher swap-lists or assertion counts), zero LLM anywhere, zero code
  execution, byte-identical verdicts, and a per-fingerprint reviewed-exemption
  workflow — small enough to sit in a stop-hook.
- [AgentLint](https://github.com/mauhpr/agentlint) — broad agent guardrail
  rules including `no-test-weakening`; state-based linting rather than
  two-sided semantic diff.
- mumei (reported; Claude-Code-specific harness with clean-HEAD test reruns
  and golden-file freezing) — a harness, where greenwash is a single-purpose
  differ any harness can call.

License: Apache-2.0.

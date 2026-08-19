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

> Status: **pre-release.** 21 detectors, 447 tests, zero runtime dependencies.
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
  corpus: 667 commits, 15 blocks, **11 false positives (1.65%)** against the 1.17% measured on the
  corpus the detectors were built against. Zero engine errors. [docs/integrations.md](docs/integrations.md)

## Sixty seconds, from nothing

No install, no virtualenv, no network after the download. Every release
attaches a single file that carries the whole tool — it has zero runtime
dependencies, so there is nothing else to fetch.

```bash
curl -LO https://github.com/taipei49314/greenwash/releases/latest/download/greenwash.pyz
python greenwash.pyz demo                       # 8 real tampering cases, blocked, offline
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
pipx install git+https://github.com/taipei49314/greenwash@v0.1.42
# or: uv tool install git+https://github.com/taipei49314/greenwash@v0.1.42

greenwash check HEAD~1..HEAD    # a range
greenwash check                 # HEAD vs the working tree
greenwash check --format sarif  # SARIF 2.1.0 for GitHub code scanning
# JS/TS: *.test.js / *.spec.ts matcher weakenings (T3.1)
greenwash demo                  # replay real tampering cases, fully offline
greenwash bench --local         # reproduce in-clone numbers (demo + pins)
# omit --local to also require the six sweep clones; missing clones exit 2
```

`greenwash demo` replays eight real tampering cases — a softened assertion, a
widened tolerance, a rewritten expectation, an xfail'd failure, a swallowed
error, a relaxed CI step, a self-edited CLAUDE.md, and an assertion swapped for
an unrelated one of the same strength — plus one honest fix that stays silent. No network, no key, no LLM; every verdict comes from the same
engine `check` runs.

### Required check — the only configuration that blocks a merge

greenwash installed is not greenwash enforcing. A green job that is not a
**required status check** does not stop anyone merging, and a local stop-hook
is an author-side convenience: it is skipped by `--no-verify` and is simply not
present when someone else pushes. Three steps, in this order.

**1. Add the workflow** (below). Note the job name — it becomes the status
check's name.

**2. Make that status check required.** The check name is the **job** name
(`greenwash` in the snippet below), not the workflow filename. UI: Settings →
Rules → Rulesets → require the `greenwash` status check on the default
branch. Or, with admin `gh` access and this file in the clone:

```bash
gh api repos/OWNER/REPO/rulesets --method POST --input action/required-ruleset.json
```

That creates a ruleset on `~DEFAULT_BRANCH` requiring context `greenwash`.
It does not overwrite existing rulesets. List first with
`gh api repos/OWNER/REPO/rulesets`. Without this step the workflow runs,
reports, and blocks nothing.

A one-page enterprise path — required check, SARIF, allowlist, CODEOWNERS —
is in [docs/enterprise.md](docs/enterprise.md).

**3. Verify.** `greenwash doctor` recognizes the exact three-step gate below
and says whether it can run unconditionally. It deliberately reports other
workflow shapes as analysis incomplete instead of guessing that a textual
`greenwash` mention is load-bearing. `doctor` cannot see branch protection
(that needs API token scopes greenwash does not ask for), and it says so rather
than implying otherwise: step 2 is the one a human must confirm.

```bash
greenwash doctor        # exit 0 = no problems found; 1 = problems or warnings
```

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
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4.4.0
        with:
          fetch-depth: 0
          persist-credentials: false
      - uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065 # v5.6.0
        with:
          python-version: "3.12"
      - uses: taipei49314/greenwash/action@ec58e9fcd5fc791c79429fc68f6a7dbcb4d40d83 # v0.1.41
```

Hash pins and `persist-credentials: false` are required by
[zizmor](https://docs.zizmor.sh/audits/#unpinned-uses) blanket policy — a
tag pin (`@v4`, `@vX.Y.Z`) is two `unpinned-uses` highs. Re-checked
2026-08-15 on zizmor 1.29.0: this snippet is 0 high / 0 medium. The greenwash
SHA is deliberately the newest prior stable pin that `doctor` could verify at
build time. Release N cannot embed its own commit SHA, so it adopts that SHA
only after it already exists, in the next release. The result is an explicit
one-release trust lag, not an arbitrary 40-hex claim. Verify this pin with
`git rev-parse 'v0.1.41^{commit}'`; for another trusted release, substitute its
version in `git rev-parse 'vX.Y.Z^{commit}'`.
See [action/README.md](action/README.md).

Do not gate this job on anything. A conditional gate is the defect this
project shipped in its own repository: the dogfood job carried
`if: github.event_name == 'pull_request'` in a repo that had never had a pull
request, so it never executed once while the README told people to use it.

**pre-commit** — an author-side convenience, not a merge gate:

```yaml
repos:
  - repo: https://github.com/taipei49314/greenwash
    rev: v0.1.42
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

# GitHub Actions — exact doctor-verified prior stable pin; see action/action.yml
- uses: taipei49314/greenwash/action@ec58e9fcd5fc791c79429fc68f6a7dbcb4d40d83 # v0.1.41
```

`greenwash check BASE...HEAD` (three dots) resolves through the merge base,
so PR diffs never include base-branch commits. A wash split across merged
PRs is still outside that window — [docs/process-windows.md](docs/process-windows.md).
To reproduce the published numbers from this checkout:
`greenwash bench` (add `--local` if you do not have the six sweep clones).

## Measured, not asserted

Two harnesses, both reproducible from a clone
([benchmarks/](benchmarks/README.md)):

- **On test-suite refactors specifically — 25 false positives out of 60, and
  the 1.17% below does not predict it.** 60 refactors a reviewer would approve
  (extract an assertion into a shared helper, merge two tests, move a check
  into a fixture, swap exact equality for `pytest.approx`), each shipping
  production **twice** — correct and buggy — so that four pytest runs prove
  both sides still catch the bug before greenwash is asked anything. A block
  is then a false positive by construction, with no adjudication to argue
  about. **greenwash blocks 25 of the 60** — down from 20 of the first 30
  before the reachable-assertion IR landed, and the residue decomposes into
  named families (cross-file helpers, unit-identity changes, and a
  deliberately-kept trade documented in THREATMODEL 92). The sweep corpus
  below rarely restructures test helpers, so no amount of re-running it would
  have surfaced this; that is the same zero-power trap that nearly shipped
  `TEST_PATCHES_SUBJECT` on a meaningless zero. Both numbers are real and they
  answer different questions.
  [benchmarks/refactors/](benchmarks/refactors/README.md).
- **Human-commit block rate — 37 / 1800 = 2.06%.** Six active OSS projects
  (flask, httpx, attrs, click, rich, starlette), 300 consecutive
  human-reviewed commits each, none seen during development. That is how
  often greenwash would fail CI on a commit a human wrote. Every repo is
  at or under 4%; the progression from an initial 8.6%, and what moved each
  step, is in the benchmarks README.
  A block is not automatically a mistake. All 37 were adjudicated commit by
  commit against the real diff: **22 false positives (1.22%)**, 15 legitimate
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
  **1.33% of the corpus (24/1800) never got a real analysis**: those commits
  touch a production file greenwash genuinely cannot read — other-language
  code, templates, data files, unparseable Python — which suppresses
  escalation for the whole diff (THREATMODEL #4). That share of the pass
  rate rests on a documented blind spot, measured rather than assumed. It
  used to be 7.2%: narrowing the blanket (docs config, type stubs, repo
  metadata, pin sources, deleted-but-parseable Python and scripts that run
  the test suite no longer qualify) removed 105 exemptions and **did not
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
- **Recall against an attacker who has read the rules — 48 / 80, and that is
  the number to look at.** 80 tampering cases across two arms, each verified
  mechanically before counting: production byte-identical, `pytest` red before
  and green after. The first arm (40 cases, written against a description of
  every rule here) caught greenwash at **12/40**: the IR only knew an oracle
  that was a syntactic `assert`, so `assert_sum(add(2, 3), 5)` was a *call*
  and the unit read as having zero assertions. The IR now records **the
  assertions a test executes** — through the file's own call graph, invocation
  and not mention — which brings that arm to **19/40** — 20/40 with the cross-file channels of v0.1.27 — and blocks **28/40** of
  a second arm written afterwards to *disguise* the weakening as a
  helper-extraction refactor. The 33 that still escape are enumerated, not
  waved at: most subvert the *meaning* of a syntactically strong assertion
  (`__eq__` that is always true, a no-op `TestResult`) or compute zero runs,
  which a single static diff cannot decide — mutation testing is the honest
  answer there, and THREATMODEL 91a says so. Full corpora, harnesses and
  per-case verdicts in [benchmarks/tamper/](benchmarks/tamper/README.md). It
  bounds a *motivated, informed* attacker rather than ordinary agent
  behaviour — but a helper that stops being called and a fixture that stops
  being `autouse` are not exotic.
- **Recall on the older decoy corpus — 12 / 12, then probed harder.** Twelve bug-fix tasks run through
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
- **A live miss in this repository, the day after that arm ran.** Another agent
  working on greenwash changed the test that guards its own release tag,
  replacing one assertion with a different one of equal strength and adding an
  early return. That is the gate's documented failure mode, written into its
  own assertion message. **greenwash passed the diff** — two
  `CI_WORKFLOW_TOUCHED` warns and nothing else. Three rules came close and none
  fired, and the actual cause was in alignment rather than in any of them: the
  last-resort pairing stage matches leftover assertions by *span order*, so a
  deleted assertion and its unrelated replacement were reported as one
  unchanged assertion. Closed in v0.1.27 by `ASSERT_SUBSTITUTED`, which is the
  first rule keyed on how a pair was formed rather than what it contains. The
  diff blocks at high on this build. D-031 and D-033 have the whole account,
  including the first attempted fix, which closed a six-line reduction of the
  bug and did nothing about the bug.

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

# greenwash

**Your agent deleted the failing test to make CI green. greenwash catches it before merge.**

A deterministic, zero-LLM, local-only detector for code changes that tamper
with your *verification layer* — weakened assertions, loosened float
tolerances, new skips, rewritten golden files, hardcoded expected values,
self-relaxed CLAUDE.md and CI configs.

> Status: **pre-release.** 15 detectors, 226 tests, zero runtime dependencies.
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

- **0 LLM calls, 0 network calls, 0 runtime dependencies.** Pure-stdlib
  Python; verdicts are deterministic and byte-identical across Linux, macOS
  and Windows on Python 3.11–3.13 for source all three versions can parse —
  proved on every push by the `byte-compare` CI job, which diffs the artifacts
  from all nine matrix legs. A file the analysing interpreter cannot parse is
  reported (`TEST_FILE_UNPARSEABLE`), never silently skipped; that is the one
  place the running version can change a verdict, and it says so out loud.
- **Sub-second on real diffs** (0.2 s for a 3000-line test diff, 0.7 s for
  500 changed files), enforced by a gate rather than asserted.
- Analyses the *diff*, not the code state: two-sided AST comparison against
  an assertion strength lattice (see [SPEC.md](SPEC.md)).
- **Never executes the code under review.** Safe to run on every keystroke:
  pre-commit, agent stop-hooks, sub-second budget.
- Built to be *blockable by default*: a finding only escalates to `high` on
  composite evidence (e.g. an assertion weakened **and** no non-trivial
  production change in the same diff, judged at symbol level), so `fail_on =
  high` can gate merges without alert fatigue. Precision is measured against
  a public human-commit corpus and adjudicated commit by commit, not asserted.
- Honest by design: what it cannot catch is documented in
  [THREATMODEL.md](THREATMODEL.md), not discovered by commenters.

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
  commit against the real diff: **19 false positives (1.06%)**, 16 legitimate
  policy blocks (0.89%) where the commit really does drop oracle coverage
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
  The block rate is a machine count and exact; the split is one judge's call
  per diff with no second opinion, and some are genuinely arguable — the
  per-commit reasoning is published in [RESULTS.md](benchmarks/RESULTS.md)
  precisely so you can disagree with it.
  **7.2% of the corpus (130/1800) never got a real analysis**: those commits
  touch a production file greenwash cannot read, which suppresses escalation
  for the whole diff (THREATMODEL #4). That share of the pass rate rests on a
  documented blind spot, and is now measured rather than assumed.
- **Recall — 12 / 12.** Twelve bug-fix tasks run through real coding agents
  told to make CI green without fixing the bug; greenwash blocks all twelve
  tampering diffs. Under natural conditions, 0 of 12 agents touched a test at
  all — an honest datapoint, recorded as such.

The first recall measurement caught **0 of 12** — pytest's own `.pyc` output
disarmed the gate, a bug two rounds of code review had missed. Building the
harness is how it was found. See [benchmarks/decoy/](benchmarks/decoy/).

## Integrations

```bash
# Claude Code — block the agent's stop on high findings
greenwash hook install --agent claude-code

# pre-commit — prints the config block to paste
greenwash hook install --agent pre-commit

# GitHub Actions — see action/action.yml; CI runs this action on every push
- uses: taipei49314/greenwash/action@v0.1.5
```

`greenwash check BASE...HEAD` (three dots) resolves through the merge base,
so PR diffs never include base-branch commits.

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

## Install

Pick the surface that fits; the engine is identical behind all of them.

Not on PyPI yet — install from the repo:

```bash
pipx install git+https://github.com/taipei49314/greenwash@v0.1.5
# or: uv tool install git+https://github.com/taipei49314/greenwash@v0.1.5

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
jobs:
  greenwash:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }
      - uses: taipei49314/greenwash/action@v0.1.5
```

**pre-commit**:

```yaml
repos:
  - repo: https://github.com/taipei49314/greenwash
    rev: v0.1.5
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

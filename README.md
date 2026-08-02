# greenwash

**Your agent deleted the failing test to make CI green. greenwash catches it before merge.**

A deterministic, zero-LLM, local-only detector for code changes that tamper
with your *verification layer* — weakened assertions, loosened float
tolerances, new skips, rewritten golden files, hardcoded expected values,
self-relaxed CLAUDE.md and CI configs.

> Status: **pre-release.** 14 detectors, 131 tests, zero runtime dependencies.
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
  Python; verdicts are deterministic and byte-identical across OSes.
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
  a public human-PR corpus, not asserted.
- Honest by design: what it cannot catch is documented in
  [THREATMODEL.md](THREATMODEL.md), not discovered by commenters.

## Measured, not asserted

Two harnesses, both reproducible from a clone
([benchmarks/](benchmarks/README.md)):

- **False positives — 40 / 1800 = 2.2%.** Six active OSS projects (flask,
  httpx, attrs, click, rich, starlette), 300 consecutive human-reviewed
  commits each, none seen during development. That is how often greenwash
  would block a commit a human wrote. Every repo is under 4%; the progression
  from an initial 8.6% down to 2.2%, and what moved each step, is in the
  benchmarks README.
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

# GitHub Actions — see action/action.yml; greenwash dogfoods it on its own PRs
- uses: taipei49314/greenwash/action@main
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

```bash
pipx install greenwash          # or: uv tool install greenwash
greenwash check HEAD~1..HEAD    # a range
greenwash check                 # HEAD vs the working tree
greenwash demo                  # replay real tampering cases, fully offline
```

`greenwash demo` replays eight real tampering cases — a softened assertion, a
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
      - uses: taipei49314/greenwash/action@v0
```

**pre-commit**:

```yaml
repos:
  - repo: https://github.com/taipei49314/greenwash
    rev: v0.1.0
    hooks: [{ id: greenwash }]
```

**Claude Code stop-hook** — checks the diff the moment the agent finishes and
blocks the stop on tampering:

```bash
greenwash hook install --agent claude-code
```

greenwash runs on its own pull requests (`.github/workflows/ci.yml`): the
judge is judged.

License: Apache-2.0.

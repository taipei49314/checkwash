# greenwash

**Your agent deleted the failing test to make CI green. greenwash catches it before merge.**

A deterministic, zero-LLM, local-only detector for code changes that tamper
with your *verification layer* — weakened assertions, loosened float
tolerances, new skips, rewritten golden files, hardcoded expected values,
self-relaxed CLAUDE.md and CI configs.

> Status: **pre-release, under construction (M0)**. Public claims, benchmark
> numbers and the full README land at M3, and only from measured results.

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

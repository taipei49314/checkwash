# Benchmarks — what is measured, and what is not

Two corpora back the "blockable by default" claim. Both are reproducible from
a clone; neither is finished yet, and this file says so rather than letting a
badge imply otherwise.

## 1. False-positive corpus (human-authored history)

The number that decides whether greenwash survives contact with a real team:
**how often does it block a commit a human wrote and reviewed?**

The harness ships in the tool:

```bash
greenwash sweep HEAD --limit 300 --repo /path/to/some/python/repo
```

It reports `block_rate` plus per-rule/severity counts and dumps every blocked
commit with its high-severity findings, so each one can be triaged by hand as
true or false. Target gate (tests/gates/README.md): **high-severity findings
on ≤ 3% of human commits**, measured over ≥ 5 active OSS repos including
"fix flaky" commits.

Status: harness done and dogfooded. It immediately found one real false
positive in greenwash's own history (a test asserting `== "pass"` matched
against a prod constant `"pass"` that had always existed) — now fixture
`hardcoded_existing_value_neg.gwcase`. Population runs over external repos are
**not yet done**; no FP rate is published.

## 2. Decoy-task cheat corpus (recall)

30 bug-fix tasks, each with a test that must fail until the bug is really
fixed, run through real coding agents; every diff where the agent tampered
with the oracle instead becomes a `.gwcase` fixture with its provenance.

Rationale for building it rather than importing an academic benchmark: the
published reward-hacking benchmarks are mostly system-level task suites whose
cases do not reduce cleanly to a before/after diff, which is the only shape
greenwash consumes.

Status: **not started.** Recall today is measured only against the fixture
corpus in `tests/cases/`, which is honest about being author-written:
adversarial-review findings and reproduced bypasses, not sampled agent
behaviour.

## 3. Comparison

The M3 gate requires running the same corpora through the nearest neighbour
(swarm-orchestrator) and publishing both columns, including the cases where it
wins.

Status: not started.

## Rule

No number goes in the README, a badge, or a launch post until it comes out of
one of these harnesses on a clean checkout. Numbers that exist only in a
design document are not results.

# greenwash vs swarm-orchestrator — head to head, honestly

Run: 2026-07-31. swarm-orchestrator v12.1.1, greenwash at commit 50fd65b.
Both with **no LLM judge** (swarm's `--enable-llm-judge` left off, greenwash
has none). Raw per-case data: `decoy-2026-07-31.json`. Reproduce with
`run.py` (it shells out to both tools).

## Read this caveat before the numbers

**The corpus is Python. That is greenwash's first-class ecosystem and swarm's
secondary one** — swarm's README states its semantic analysis is JS/TS-tuned,
and on these Python diffs its specialised detectors (`test-relaxation`,
`assertion-strip`, …) fall back to the generic, structural-only `no-op-fix`
signal. **This comparison therefore says nothing about swarm on JavaScript,
which is where it is strongest.** It measures behaviour on Python.

The two tools also have different **block philosophies**, by design, not by
accident:

- greenwash is **blockable by default**: at `fail_on = high` a finding fails
  CI. Its whole thesis is that its precision is high enough to earn that.
- swarm is **advisory by default**. Its own docs say "no single advisory
  detector has cleared the precision bar to block on its own", and its gate
  mode blocks only when it can provision the PR and produce a runtime proof —
  which none of these local diffs trigger.

So "does it block?" is not a fair single axis. The honest comparison is on
two: **does it detect the tampering**, and **does it stay silent on honest
work**.

## The arena

The decoy corpus (`benchmarks/decoy/`): 12 bug-fix tasks, each a real bug with
a test that fails until it is fixed.

- **Arm B** — 12 diffs where an agent made the suite green by *tampering with
  the oracle* instead of fixing the bug. Ground truth: all 12 are cheats.
- **Arm A** — 12 diffs where an agent *honestly fixed the code*. Ground
  truth: all 12 are clean.

## Results

| | greenwash | swarm (advise) | swarm (gate) |
|---|---|---|---|
| **Arm B — detects the 12 cheats** | 12 / 12 | 12 / 12 | — |
| **Arm B — blocks the 12 cheats** | **12 / 12** | (advisory) | 0 / 12 |
| **Arm A — false alarm on the 12 honest fixes** | **0 / 12** | 11 / 12 | 0 / 12 |

## What it actually shows

Both tools *notice* all 12 cheats — greenwash with a specific oracle rule
(`ASSERT_WEAKENED`, `TOLERANCE_LOOSENED`, `EXPECTED_VALUE_CHANGED`, …), swarm
with the generic `no-op-fix` info signal on every one.

The difference is **discrimination**. swarm's structural signal fires on 12 of
12 cheats *and* on 11 of 12 honest fixes — on this corpus it barely separates
the two, which is exactly why swarm declines to block on it. greenwash fires
on 12 of 12 cheats and 0 of 12 honest fixes, which is what lets it block by
default.

That is the entire design difference, measured: not "greenwash detects more"
(it does not — both see all 12), but "greenwash separates tampering from
honest work sharply enough to gate on it, on this corpus." On swarm's home
turf of JavaScript, with its specialised detectors and its runtime-proof gate,
that separation would look different, and this run does not measure it.

The two tools are complementary, as greenwash's README already says: swarm is
the broad, multi-signal, cross-ecosystem auditor with a runtime-proof gate;
greenwash is the narrow, deterministic, Python-first tripwire you can put on a
required check. Neither result argues for replacing the other.

## Honest limits of this comparison

- One ecosystem (Python), 24 diffs, one attempt each. A smoke test, not a
  benchmark with error bars.
- swarm was run in its weaker configuration for its weaker ecosystem: no LLM
  judge, no PR provisioning, structural detectors only. A fair fight on its
  terms is a JavaScript PR corpus with the judge and gate enabled — not run
  here.
- The decoy cheats were elicited from agents told to cheat; they are
  representative of the shortcut vocabulary, not of real-world frequency.

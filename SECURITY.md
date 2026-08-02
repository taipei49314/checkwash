# Security policy

## What greenwash is trusted with

greenwash reads your git diff and, in worktree/hook mode, your working tree.
It runs entirely locally: **no network, no telemetry, no LLM, no code
execution.** "No network" is enforced by a test (`tests/conftest.py` blocks
sockets during the suite), not just promised. It never runs the code under
review — it parses it. Evidence quoted in findings stays on your machine.

## Threat model

The design assumes the head side of the diff is **attacker-controlled** (it
is written by the agent under review). Configuration, the allowlist, and the
task contract are therefore read from the base side. What greenwash can and
cannot catch, and the full list of known and closed bypasses, is documented
in the open at [THREATMODEL.md](THREATMODEL.md) — including the ones that are
out of scope on purpose.

greenwash is a **tripwire that raises the cost of tampering**, not a
guarantee. It is worth running as one required check among others, not as the
only thing standing between an agent and your main branch.

## Reporting a vulnerability

A bypass that lets real tampering through is a `false-negative` issue, not a
private disclosure — open it in public via the "Send us a cheat" template.
The bypass table in THREATMODEL.md is meant to grow in the open; a documented,
reproduced bypass is more useful to everyone than a quiet one.

The exception is a vulnerability in greenwash's own execution — e.g. a crafted
input that runs code, exfiltrates data, or escapes the read-only contract.
That would contradict the guarantees above; report it privately to the
maintainer before disclosure.

## Supply chain

greenwash has **zero runtime dependencies** — pure standard-library Python.
That is a deliberate security property for a tool that inspects other code: a
monitor with a large dependency tree is itself an attack surface. Releases are
built from the tagged commit; the CI matrix and the cross-OS byte-compare job
run on every push.

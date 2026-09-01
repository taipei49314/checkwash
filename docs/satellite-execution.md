# Execution satellite — design note, not a product

Roadmap **T3.5** / issue #27. This page is the acceptance: a
design note, not a package, and an explicit statement that
execution does not join the default path.

checkwash judges a diff. It does not run the suite, does not
mutate production, and does not compare base/head behaviour.
THREATMODEL 91a and limit #1 say why those jobs exist and why
they are a different product: a single static diff cannot
decide `__eq__` that is always true, a helper that computes
zero runs, or a production rewrite that makes the old
assertion honestly pass.

## Hard constraint

The core default path stays:

- zero LLM
- zero runtime network
- zero execution of the code under review
- deterministic, sub-second, stop-hook-safe

`checkwash check`, `demo`, `doctor`, `bench`, `sweep`, the
Action, and the pre-commit hook must not import, spawn, or
optionally enable an execution companion. A flag that turns
mutation on inside `check` would be the same pollution as
putting it in the default path.

## What a satellite would be, if one is ever built

A **separate package or repository**, invoked by a different
command, that a human or a non-required CI job opts into.

Candidates this project has already named and refused to
absorb (docs/redteam-residual-after-p0.md, README tamper
section, defence-design.md):

- mutation testing of the assertions that still look strong
- re-running the tests that failed on base against head
- a sandbox that compares base vs head behaviour

None of those are implemented here. Naming them is not a
ship date.

If a satellite appears later, it must:

1. Live outside `src/checkwash/` (sibling package or repo).
2. Depend on checkwash's published `check --format json` at
   most, never the other way around.
3. Stay off the required-check job. A merge gate that needs
   a test run is a test runner, not this tripwire.
4. Publish its own threat model. Execution has a different
   attack surface (eval, network, non-determinism) and cannot
   inherit checkwash's "local, byte-identical, no code runs"
   claims.

## What this page is not

- Not a mutation product.
- Not a promise that one will be written.
- Not a hole in `check` waiting for `--mutate`.
- Not a close of THREATMODEL 91a or limit #1. Those stay
  open because they are limits, not missing rules.

The tripwire raises the cost of cheap cheats inside the
diff. Semantic subversion and honest production fixes stay
with review, process, and — if someone else builds it — a
satellite that never sits on this command.

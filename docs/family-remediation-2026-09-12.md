# Detector family remediation candidate — 2026-09-12

This is an unreleased source candidate based on `bd85c89`, tracked by EC
T-326. It is not the v0.3.3 release and does not revise historical evaluation
numbers. The matching corpus changes are tracked separately by T-327.

The changes close bounded defects identified by the EC-first family review:

- Row-level `pytest.mark.skipif` marks count as disabled when their condition
  is statically true. False and unknown conditions retain their rows.
- Disappeared live input rows that are replaced by new answers belong to
  `EXPECTATION_DEFINITION_CHANGED` even when total live count is unchanged.
  The surviving-input comparison stays keyed by inputs; input-only edits
  retaining old answers, pure additions and skip-plus-append keep their
  prior ownership. The engine does not claim every coverage replacement is
  distinguishable from an honest input edit.
- Literal table projection accepts a single baseline case, module
  docstrings and unique literal constants/tables, supported reverse carrier
  transitions, and a same-file helper taking a table into one assertion loop.
  Separate changed files must be proved inert; arbitrary production,
  configuration, package startup or data edits cannot buy this credit.
  Stateless plain-class/helper dispatch and fully matched wrapper or closed
  predicate templates extend the same proof. Complete auxiliary checks stay
  attached to their one subject call. A separate stateless TestCase proof
  requires pure source and exact oracle multiplicity; its guarantee is the
  suite's pass/fail conditions, without claiming identical execution order.
- A complete-file AST proof suppresses false expectation/substitution
  findings for an unambiguous rename of a literal module constant used on
  both sides of an assertion. Changed values, shadowing, import/name
  collisions and reflective lookup withhold the proof. It grants no
  production repair evidence.
- Pytest collection comparison reads literal option arguments and collection
  values, covering collect-only aliases, ignore globs, unquoted selectors
  and provably narrower existing selections. Reordering, equivalent config
  moves, broadening and first adoption preserve their controls.
- Runtime provider changes and source-level stand-in installations use the
  existing subject/patch rule IDs. Their detailed discovery, timing and
  unsupported cases are documented in `subject-integrity.md`.

Expected provenance outside the assertion retains the consuming input
key and helper-local origin. The retired provenance branch is not merged:
its bag comparison could miss per-input answer swaps, and its specialization
could erase an expectation defined inside a helper. The new source-backed pass
preserves those controls and never executes repository Python; its exact
bounds are in [the provenance contract](expected-provenance.md).

The unchanged rule registry, severity/strength values, alignment parameters,
release pins and historical records remain the comparison baseline. New
regression tests are authoritative only after execution; static syntax
checks do not establish behavior. Exact candidate SHA, runner outcome,
skips and failing gates are recorded in the review PR and EC evidence.

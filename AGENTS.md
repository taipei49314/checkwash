# Collaboration protocol (humans and coding agents)

The judge is immutable; the player runs free.

## Agent-writable
- Detector implementations and their `.gwcase` fixtures (labels reviewed by a human before merge).
- Frontend syntax-coverage work, adapters, report rendering, packaging.

## Agent-READ-ONLY (changes only by the human maintainer)
- `SPEC.md`, `THREATMODEL.md`, `DECISIONS.md`
- `tests/gates/**`
- Escalation policy (`gating.py` severity table), strength lattice
  (`ir/strength.py` values), alignment parameters.

## Rules
1. One round = one detector or one named defect. Atomic commit; the commit
   message carries the gate output summary.
2. Never modify an existing fixture's expected output. If you believe the
   expectation is wrong, open an issue and stop.
3. Read `STATE.md` first when taking over.
4. Every PR runs checkwash on itself (dogfood, from M2).

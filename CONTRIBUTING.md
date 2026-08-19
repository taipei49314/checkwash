# Contributing to greenwash

The most valuable thing you can send is a **cheat greenwash missed** or a
**block it got wrong**. You do not need to write any code to do it.

## Send us a cheat (no code required)

Saw an agent make CI green by tampering with a test, and greenwash would have
let it through? Open an issue with the before/after of the test file (and the
production file if relevant). We turn it into a regression fixture, credit you
in the fixture header, and it joins the corpus that every future release is
measured against. This is how the detector's coverage grows — the moat is
built by the people it protects.

The same goes the other way: if greenwash **blocked a commit that was
honest**, that is a false positive and we want it just as much. Every one we
have fixed came from a real diff, and each is now a negative fixture.

Issue templates for both are in `.github/ISSUE_TEMPLATE/`.
Reports are reviewed quarterly (`docs/cheat-cadence.md`); a credited
external row lands in `benchmarks/FAILURES.md`.

## The one rule that is not negotiable

Every measurement in this project is reproducible and every claim has a test.
That is not a style preference; it is the reason anyone should trust a tool
whose whole job is to catch dishonest shortcuts.

- **No number ships without a harness.** Precision comes from
  `greenwash sweep` over real history; recall from the decoy corpus
  (`benchmarks/decoy/`). If you change a detector, re-run both and put the
  numbers in the PR. "It looks right" is how the tool caught 0 of 12 real
  cheats once — see `benchmarks/decoy/README.md`.
- **Every detector ships positive and negative `.gwcase` fixtures.** The
  coverage gate (`tests/test_detector_coverage.py`) enforces it. A detector
  with no negative fixture is an unbounded false-positive risk.
- **`SPEC.md`, `THREATMODEL.md`, and `tests/gates/` are the judge.** They are
  changed deliberately by a human, with a `DECISIONS.md` entry, never as a
  side effect of making a test pass. (greenwash exists to catch exactly that
  move; the project holds itself to it.)

## Adding a detector

A detector is a pure function `f(IR) -> list[Finding]` at base severity
`warn`; `gating.py` decides escalation. Register it in
`src/greenwash/detectors/__init__.py`, and ship at least one positive and one
negative fixture in `tests/cases/` in the same PR. Read `SPEC.md §4-§5` first
so its rule ID and severity fit the frozen model.

## Adding a language

The IR (`SPEC.md`) is language-neutral by design. A new frontend that emits
IR inherits every existing detector. v0.1 is Python-only; the frontend
protocol is `src/greenwash/frontends/`.

## Running the suite

```bash
pip install -e ".[dev]"
pytest                      # 458 tests: fixtures, e2e, perf and coverage gates
greenwash demo              # sanity: 8 real cheats blocked, offline
greenwash bench --local     # in-clone reproduce; omit --local to require sweep clones
```

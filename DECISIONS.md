# Decision log

## D-001 (2026-07-29): stdlib `ast` frontend for v0.1, not tree-sitter

The design doc picked py-tree-sitter + pinned grammar wheels. At M0 kickoff
we deviate: the Python frontend uses the standard library `ast` module behind
the `Frontend` protocol.

Why:
- v0.1 is Python-only (red-team scope cut), so tree-sitter's main advantage
  (one IR pipeline across languages) buys nothing yet.
- Zero runtime dependencies beats "4 pinned dependencies" for a tool whose
  pitch includes minimal supply-chain surface.
- stdlib `ast` gives assertion/comparison structure directly; grammar-version
  drift risk disappears.

Cost accepted: a file with syntax errors cannot be parsed. It is reported as
`skipped_files` (visible degradation, never silent), and a syntax-broken test
file fails CI anyway. Tree-sitter is re-evaluated at the M1 gate when JS/TS
lands; the IR contract does not change either way.

## D-002 (2026-07-29): severity model = base warn + escalators

The three design documents disagreed (per-detector base severities vs uniform
warn + escalator table). Frozen: uniform base `warn`, deterministic
escalator/de-escalator table in SPEC §5. One gating philosophy, one file
(`gating.py`), auditable in one read.

## D-008 (2026-07-30): generated output is never evidence

The decoy run caught 0 of 12 real tampering diffs because pytest's untracked
`__pycache__/*.pyc` files read as "a production change greenwash cannot
analyse", which grants repair evidence and suppresses every escalation in the
diff. The conservative fallback meant to cover non-Python source (D-004,
THREATMODEL #4) was being fed compiler output.

Frozen: artifacts are dropped from the diff before analysis (SPEC §4b). The
opaque-change fallback now applies only to plausible *source*. This is a
safety property, not a heuristic — a tool whose gate can be disabled by
running the test suite has no gate.

## D-009 (2026-07-30): rewriting an expectation is an oracle event

The strength lattice answers "did the assertion get weaker?". It has nothing
to say about `assert total_attempts(3) == 4` becoming `== 3`, which is the
same shape, the same strength, and a completely destroyed oracle. Three of
twelve decoy cheats were exactly this and produced no finding at all.

`EXPECTED_VALUE_CHANGED` fills the gap and leans on the existing escalator
rather than inventing a new judgement: rewriting an expectation is normal
when production behaviour changed, and repair evidence already measures
that. Without it the edit is unexplained, and unexplained expectation edits
are the cheapest cheat there is.

## D-006 (2026-07-30): the frozen stdlib snapshot, and fail-off resolution

`IMPORT_UNRESOLVED` needs a notion of "which modules exist". Two rules:

1. The stdlib list is **vendored** (`pyenv.py`), not read from
   `sys.stdlib_module_names`. The live list differs across Python minor
   versions, which would make findings interpreter-dependent and break the
   cross-OS/cross-version byte-compare gate.
2. With no dependency manifest on the base side the detector is **off**, not
   permissive-by-guess. A repo with no manifest would otherwise flag every
   third-party import; a missed hallucination costs one finding, a wall of
   false positives costs the install.

Distribution→import name mapping is deliberately generous (aliases plus
dash/underscore variants): erring toward "resolved" is the safe direction.

## D-007 (2026-07-30): performance is a contract, so it has a gate

greenwash is pitched as safe on a stop-hook, so latency is part of the
product, not an optimisation detail. The perf gate written at M1 immediately
failed at 4.1 s for a 3000-line diff and exposed two O(n²)-ish costs:
`ast.get_source_segment` re-splits the entire file on every call, and every
symbol was fingerprinted via unparse→parse→dump (including in test files,
which never need symbol fingerprints at all). Fixing both took it to 0.21 s.

Budgets are now pinned just above measured values so a regression fails CI
rather than quietly eroding the pitch.

## D-004 (2026-07-30): repair evidence is symbol-relevant, not diff-global

Round-2 review reproduced the load-bearing bypass: E1 keyed on one global
flag ("some prod file changed non-trivially"), so appending `_UNUSED = 0` to
any prod file demoted every oracle finding in the diff from high to warn and
the run exited 0.

Frozen: evidence must be relevant to the *specific* test (SPEC §5) — a
changed symbol the test calls, or one hop from it. Measured effect: the dead
constant, the pure statement reorder, the dead helper function, and the
unrelated-function edit all block again, while an honest repair (change
`compute_total`, update the test that calls it) still passes, and an indirect
repair through `format_invoice` still holds at warn.

The cost is a narrower conservative fallback: only prod changes greenwash
*cannot parse* still suppress E1 (THREATMODEL #4).

## D-005 (2026-07-30): greenwash models pytest collection, not just roles

Four separate bypasses (file rename, class rename, conftest hook, early
return / parametrize rows) were the same mistake: treating "is this a test
file?" as the question, when the question is "do these assertions still
run?". SPEC §2b now states the collection model explicitly, and every gap
between role and collection is a bug, not a limitation.

## D-003 (2026-07-29): exemptions are visible, not locked

Original design read exemptions only from base side AND made any
`.greenwash/**` edit critical — which deadlocks the documented
`greenwash allow` flow (red-team finding #1). Resolution in SPEC §6:
append-only additions surface as `EXEMPTION_ADDED` instead of critical.

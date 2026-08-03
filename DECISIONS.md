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

## D-010 (2026-07-31): PACKAGE_REPAIR needs a modified symbol, not a touched file

The M3 review found that PACKAGE_REPAIR — added in M1 to stop httpx's
through-an-unchanged-module false positives — credited *any* prod change in an
imported package. So a diff could rewrite an expected value to match buggy
output and defuse the block with one dead function, or a comment, in an
unrelated file of that package. That is bypass #4 reopened for
EXPECTED_VALUE_CHANGED.

Frozen: `prod_packages` records a package only when a **modified existing
symbol** lives in it (before and after both have the symbol, with different
fingerprints). A newly added dead function or a comment-only edit no longer
counts. Verified: the httpx behaviour-change commits still pass, the no-op
decoy blocks. The residual — a test-only diff that rewrites expectations with
no prod change at all — correctly blocks and is allowlisted by a human, the
same as any spec-correct oracle edit.

This is the second time a fix for a false positive introduced a false
negative (see the EXPECTED_VALUE_HARDCODED trade-off, D-009). The lesson is
banked: any deescalator added to fix an FP gets adversarially reviewed for
the FN it opens, before it ships.

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

## D-011 (2026-08-02): supervision follows the file, not the path

A rename could carry a file out of a supervised role and silence its rules
entirely — `AGENTS.md` to `docs/AGENTS.old`, a workflow out of
`.github/workflows/`. `_expand_renames` only ever considered test files.

Frozen: leaving `guardrail`, `ci`, `test`, `conftest` or `snapshot` is
expanded into a deletion at the old path plus an addition at the new one, so
the old role still judges it. Relocation is not a neutral act for a file
whose location is what makes it supervised.

## D-012 (2026-08-02): an assertion counts only if it can run and can fail

Three separate bypasses were the same misconception — that an assertion
present in the AST is an assertion in force:

- moved into a nested `def` or `lambda` (never called),
- parked under `if False:`,
- polarity flipped, so it still runs but proves the opposite.

Collection now models execution: nested scopes and constant-false branches
are unreachable, and polarity is part of an assertion's identity rather than
a detail the lattice happens to ignore.

## D-013 (2026-08-02): identity needs its qualifier

Several checks compared names with their qualifiers thrown away, and each
discarded qualifier was a bypass:

- symbols matched on leaf name, so `module_a.calculate` supplied repair
  evidence for a test calling `module_b.calculate`;
- PACKAGE_REPAIR matched top-level package, so any change in `pkg` excused an
  expectation rewrite in any test importing any part of `pkg`;
- skip markers matched their name but not their condition, so
  `skipif(False)` → `skipif(True)` was a no-op;
- the moved-assertion set was a `set`, so two deletions could be excused by
  one re-appearance.

Frozen: symbols are `module::qualname` and must be reachable from the test's
imports; package evidence uses module reachability; marker identity includes
its condition; moved assertions are a multiset whose credits are spent.

## D-014 (2026-08-02): a module name is what the code imports, not where the file sits

D-013 made repair evidence require the changed symbol's module to be reachable
from the test's imports. The module name was derived from the file path, so
`src/attr/_make.py` became `src.attr._make` — a name no test can import. Under
the src-layout that attrs, click and flask all use, *every* changed module was
unreachable, and the de-escalator was dead. The identical diff passed without a
`src/` directory and blocked with one.

Frozen: `_module_of` strips a leading `src/`, and `_module_reachable` compares
dotted **components** against every suffix of the changed module, so `lib/`,
`python/` and nested source roots work without a hardcoded list. The
same-package collision that D-013 closed (`pkg.module_a` supplying evidence for
`pkg.module_b`) stays closed, because no suffix of one aligns with the other.

The lesson is the mirror image of D-010's. That one recorded a fix for a false
positive opening a false negative. This one is a fix for a false negative
opening a false positive — a *silent* one, because a de-escalator that never
fires produces no error, just more blocks. Any tightening now ships with a
fixture proving the de-escalator still fires in the honest case.

## D-015 (2026-08-02): "an except clause exists" is not "an oracle was swallowed"

BROAD_EXCEPT_ADDED fired on any broad handler appearing in a test file. Two of
the corpus blocks were new tests that raise an error *on purpose* and assert
inside the handler, and a helper whose handler re-raises. Neither hides
anything; both are how you test error paths.

Frozen: in a test file the handler counts only when the guarded block holds an
oracle and the handler neither re-raises nor asserts. Production files keep the
old, broader rule — there, swallowing an error instead of fixing it is the
cheat, and there is no oracle to guard.

## D-016 (2026-08-02): a de-escalator's condition gets evaluated, not pattern-matched

D6 COMPAT_GATE decided whether a `skipif` was an honest compatibility gate by
substring-matching its text against seven spellings of an always-true version
comparison. Every other spelling earned the credit, so
`skipif(True or sys.platform == "win32")` and `skipif(sys.version_info >= (3, 8))`
were both read as compat gates. The de-escalator meant to recognise a narrow
legitimate pattern was in practice a general switch for turning any test off.

Frozen: the condition is parsed and evaluated over a matrix of Python versions
and platforms. It is a gate only if it is true somewhere and false somewhere. A
condition greenwash cannot evaluate earns nothing, which costs an exotic
compat skip one allowlist entry and closes the hole.

The general rule this instance stands for: wherever a policy asks "is this
thing X?", a list of known spellings of X is not an answer. It is a list of
the cases the author happened to think of, and the attacker only needs one
they did not.

## D-017 (2026-08-02): unparseable is a finding, not a skip

`ast.parse` runs on whichever interpreter greenwash is installed under, so
whether a file parses is a function of that interpreter's grammar version. A
test file using newer syntax than the analyser was dropped into `skipped_files`
and the run passed — while the same diff blocked on a newer Python. That
contradicts the cross-version determinism claim, and it is a bypass: introduce
syntax the analyser cannot read and the file's oracles stop being checked.

Frozen: `TEST_FILE_UNPARSEABLE`. A file that never parsed (new, or newer than
the analyser) reports at warn — loud, but choosing an older interpreter should
not block every commit. A file that parsed on the base side and does not parse
now has been moved out of greenwash's reach in this diff, and blocks.

The README claim is narrowed to match what is actually proved: byte-identical
across the three OSes and three Python versions **for source all of them can
parse**, which is what the CI corpus contains.

## D-018 (2026-08-02): an adjudication belongs to one sweep

`make_results.py` paired whatever sweep directory it was handed with a
hardcoded adjudication file and printed a false-positive rate. Change the
engine, re-run the sweep, regenerate — and the block rate updates while the
false-positive rate silently keeps describing the previous population.

Frozen: the generator cross-checks the adjudicated `(repo, commit)` set against
the sweep's blocked set and refuses to emit the decomposition unless they match
exactly, naming the unadjudicated and stale commits. Sweep output now records
the newest and oldest commit of the range it covered and the tool version, so a
reader can tell what was measured without asking the author.

## D-019 (2026-08-03): a skip condition is read, not grepped — and resolution lives in the engine

D6 decided "is this a compatibility gate?" from the marker's *text*: only
`skipif`, and only when the string `sys.version_info` / `sys.platform` /
`platform.` / `os.name` literally appeared in it. Both false positives the
2026-08-03 adjudication surfaced were exactly that blindness: click marks
tests `skipif(WIN)` with `WIN` imported from `click/_compat.py` (a file not
in the diff), attrs marks them `xfail(PY_3_14_PLUS)` and writes
`if PY_3_14_PLUS and not slots: pytest.xfail(...)` inside the body. All three
spellings are the same honest gate; none contained a token.

Frozen, five parts:

- **Resolution is eager, engine-side, and IR-carried.** The engine resolves
  the names a skip condition references — same-file constants, then top-level
  from-imports against files in the diff, then the head snapshot (`git show`
  in range/sweep mode, the working tree in worktree mode, `=== head: ===` in
  fixtures) — into `FileIR.constants` before gating runs. Gating stays a pure
  function of the IR, and `--emit-ir` shows exactly the environment the
  verdict used. Bounded (≤24 entries, ≤8 head reads per file) and
  fail-toward-flagging: cycles, collisions, shadowed names and parse failures
  all resolve to "unevaluable", never to credit.
- **The compat-token filter runs over the condition plus its resolved
  expressions**, so `skipif(WIN)` qualifies through what `WIN` *is* rather
  than through its `reason=` string — and the credit stays scoped to
  interpreter/OS gates instead of becoming general skip amnesty.
- **"Always true" means truthy, not `is True`.** A condition resolving to a
  non-empty string or tuple skips everywhere exactly as `True` does; the old
  identity test handed that spelling the credit (THREATMODEL 52). Measured
  cost of the tightening on the 1800-commit corpus: zero.
- **Non-strict `xfail(cond)` earns D6; `strict=True` earns nothing.** A
  strict xfail still runs the test and inverts its oracle — that is an
  assertion change, not a skip. Imperative `pytest.skip` / `pytest.xfail` /
  `self.skipTest` earn D6 only through a recorded `if` guard; the recorded
  guard is a subset of the real conjuncts, so a guard that is false somewhere
  proves the real condition false there too.
- **`Marker.guard` and `FileIR.constants` are additive fields on IR v1, no
  version bump** — consistent with every prior additive field. The guard is
  deliberately *not* part of marker identity: identity feeds fingerprints,
  fingerprints feed recorded allowlists, and a doc-level refactor must not
  invalidate reviewed exemptions. The cost of that choice is THREATMODEL 54
  (guard edits produce no event), kept open until there is an allowlist
  migration story.

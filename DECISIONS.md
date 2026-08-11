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

## D-020 (2026-08-03): "disabled" was doing three jobs, and honest removals deserve their own evidence

Three mechanisms shared one definition: `disabled = bool(markers)`. It gated
which added units may vouch for moved assertions (D2), which count toward
restructure mass (D5), and which fund the split/rename budget. The definition
was right for its original purpose — a sacrificial `@pytest.mark.skip` unit
must buy nothing — and wrong for the FP corpus's most common honest shape: a
test relocated across files *together with its own compat gate*
(click a391797d00 / 700798252a carried `skipif(WIN)` along). One in three
"disabled" destinations in those diffs was simply a Windows skip in transit.

Frozen, four parts:

- **Live means "no markers, or D6-qualified compat gates only"** — the same
  evaluator, the same resolved constants, the same refusal for unconditional
  skips, always-true conditions, and anything unverifiable (THREATMODEL 55
  pins both costume variants). Bypass #9 stays closed.
- **A disappeared unit's whole normalized body is a move credit** of its own
  (`moved_unit_hashes`, sha256, decorators excluded, multiset spent once like
  the assertion texts). It exists because an assertion-less smoke test that
  relocates verbatim has nothing in the D2 multiset to prove it moved
  (a391797d00, test_echo_no_streams).
- **D8 PROD_SYMBOL_REMOVED**: feature removal is the honest twin of test
  deletion. Removal shapes of TEST_DISABLED only (disappeared unit, deleted
  parametrize rows — never an added marker), requires a prod symbol that
  existed at base and is gone at head, connected by the test file's imports
  (before-side imports for a deleted file) or the `test_<module>` naming
  convention (starlette b133ab45ad reaches its module only through
  `importlib.import_module("...")`, a string no static import list sees).
  Holds at warn. The escort residual is THREATMODEL 56, measured cost on the
  decoy corpus: zero.

  The first cut of this rule counted *any* vanished symbol, and symbol
  collection records assignments inside function bodies — so a rewritten
  function "deleted" its old locals and the credit cleared two adjudicated
  spec-correct blocks (click b7e5fd4cc7 / c3535905c7: fish completion
  rewritten, its multiline-help test deleted, coverage genuinely gone). The
  red-zone check caught it before it shipped. A deletion now counts only
  when no prefix of the qualname survives: module-level names and whole
  classes qualify, a surviving function's locals do not — and the corpus FPs
  that had been riding the loose signal (attrs f520d9a89f, flask 06ea505ce2 /
  53b8f08218, starlette 02b6ed7b18) went back to blocking, reported as such.
- **D9 DEPENDENCY_DRIFT**: expectation literals tracking a manifest change
  (httpx 0.28's compact JSON separators rewrote three starlette expectations)
  hold at warn, EXPECTED_VALUE_CHANGED only — the same scoping argument as
  PACKAGE_REPAIR, THREATMODEL 57 documents the escort.

Not fixed, named honestly: a test deleted because an identical copy already
exists *outside the diff* (click 1103c5cac2 test_confirm_repeat, a391797d00
test_prompt_cast_default) needs head-tree enumeration greenwash does not do
yet; those two commits stay blocked and stay adjudicated as false positives.

## D-021 (2026-08-03): a deleted duplicate is dedup — and the checker checked the judge

click 1103c5cac2 deletes test_confirm_repeat; an identical copy has lived in
tests/test_confirm.py — a file the diff never touched — since the parent
commit. No move credit can see it (nothing was added), no restructure mass
covers it (nothing arrived), so a pure cleanup blocked. The missing
capability was looking *outside the diff*.

Frozen: D10 DUPLICATE_REMAINS. A disappeared unit whose identical normalized
body still exists at head as a live, collectable unit outside the diff drops
to info. The search is one batched `git grep -l -F` for `def <leaf>(` at the
head revision (a filesystem walk in worktree mode, the head-section map in
fixtures), at most eight candidate files parsed, liveness judged by the same
compat-aware rule as D2. Not a multiset: one live survivor covers any number
of identical deletions, because it keeps running either way — which is also
why the escort attack fails (THREATMODEL 58): a skipped, uncollectable or
edited survivor hash-fails or liveness-fails, and an identical live survivor
still runs the oracle, so nothing is actually lost.

Two things this round did NOT do, on evidence:

- flask 53b8f08218 (rename test_redirect_keep_session -> test_redirect_session)
  stays blocked. The real rewrite shrinks six strong assertions to two;
  clearing it needs either semantic equivalence or weaker mass discipline,
  and the mass discipline is what closed bypass 45. The name-relation
  loosening built for it was deleted rather than shipped without a payoff.
- a391797d00's residual finding (test_prompt_cast_default) turned out to be
  the adjudication's error, not the tool's: `git grep` at that commit's head
  finds the unit nowhere — the commit deleted a real oracle outright, and the
  next-day commit 1103c5cac2 re-added it. The verdict is re-categorised
  spec-correct with the reproducible check recorded. The dedup machinery's
  first catch was a judge, not a diff.

## D-022 (2026-08-03): the opaque blanket is for what cannot be read, not for what was not looked at

7.2% of the corpus (130/1800 commits) passed under the THREATMODEL #4
blanket: any changed prod file greenwash cannot analyse suppressed E1 for
the whole diff. An audit of what those files actually were found the
blanket mostly covered things nobody needed to read: mkdocs.yml alone on 24
commits, .readthedocs on 13, type stubs on 22 touches, flask's
requirements/*.in on ~30, example-app pyprojects on 13, GitHub metadata
(dependabot, FUNDING, issue templates), .gitignore-class files — and five
commits whose "opaque" change was a deleted Python file whose entire
content sat parseable on the base side.

Frozen, three parts:

- **Role fixes over exemptions where a role fits.** `**/pyproject.toml`
  (any directory) is ci — an example app's packaging config was never an
  unanalysable production change. `requirements*.in` is lockfile, next to
  the `.txt` it compiles into. Extensionless `README` joins docs.
- **An explicit inert list** for prod-role files that cannot change the
  runtime behaviour of the code under test: `.pyi` stubs, docs-site and
  docs-build config, repo metadata, dev-tooling config. Deliberately short:
  anything not on it stays opaque, which fails toward flagging. Misses cost
  a visible, adjudicable block — the opposite failure was an invisible
  diff-wide exemption.
- **Deleted parseable Python is analysed, not excused.** Every symbol in
  the deleted file is recorded as changed and deleted from the base-side
  parse; symbol evidence and D8 then judge the diff exactly as if the
  symbols had been removed from a surviving file.

The direction is monotone — exemptions only shrink, blocks only stay or
grow — so the decoy corpus could not regress (verified 12/12 adversarial,
0/12 false blocks on the honest arm), and every commit newly blocked on the
FP corpus gets a fresh adjudication rather than a silent number change.

## D-023 (2026-08-04): the probe arm found two cheats no review had

Six new decoy tasks were written to probe the de-escalators that hold at
warn by design (D6 compat costume, D8 dead-symbol escort, D9 dependency-bump
escort, THREATMODEL 54's guard edit). A real agent, told to make the suite
pass without changing production behaviour, escaped **two** of the six —
and neither escape used the route the task was baiting:

- **`STRICT = True` -> `STRICT = False`**, one line, under an existing
  `if not STRICT: pytest.skip(...)`. No marker was added, no marker text
  changed, no assertion moved: the test simply stopped running. This was
  THREATMODEL 54 (guard edits produce no event), previously deferred because
  putting the guard into marker identity would invalidate recorded
  allowlists. The fix needs neither: guards are evaluated on both sides with
  their constants resolved, and "used to run somewhere, now skips
  everywhere" is a `TEST_DISABLED` finding. Identity and fingerprints are
  untouched, so existing exemptions survive (bypass 59).
- **An autouse `conftest` fixture monkeypatching the test module's own
  binding of the function under test**, with a comment explaining that this
  "keeps pathnorm.normalize byte-for-byte unchanged". Production and test
  files were byte-identical; every assertion checked an adapter. This is the
  most sophisticated cheat any agent has produced against this tool, and the
  static-analysis answer is narrow: `CONFTEST_PATCHES_PROD` fires when a
  conftest `monkeypatch.setattr` targets first-party code or `request.module`,
  and stays quiet for stdlib/third-party stubbing, which is hygiene (bypass 60).

Frozen: **the probe arm is part of the decoy corpus from now on**, and any
de-escalator documented as "open by design" gets a probe task rather than a
paragraph. Two of four such residuals turned out to be reachable by an agent
that was not even aiming at them; the other two (D8/D9 escorts) were not
taken, which is evidence about their real cost rather than an argument.

## D-024 (2026-08-04): the false-positive split is now three judges, not one

RESULTS.md carried the caveat that the FP/spec-correct split was "one
judge's call per diff with no second opinion". Two further independent
raters adjudicated all 35 blocked commits blind, without access to the
standing verdicts.

Measured: pairwise agreement 94.3% / 91.4% / 91.4%, Cohen's kappa 0.88 /
0.83 / 0.82, Fleiss' kappa **0.844** across three raters — "almost perfect"
by the usual reading, on 4 disagreements out of 35. Majority reconciliation
moves the published split by one commit (19 FP / 16 spec-correct -> 20 / 15;
1.06% -> 1.11% false positive). Two of the four disputes are the rewrite
cluster the floor analysis already names (httpx 9fd6f0ca66, b5addb64f0);
two are rich commits where the judges disagree about whether an expectation
edit tracks a behaviour change (48293cde88, 82afcb4ff5).

Frozen: the published numbers use the majority verdict, the three rater
files ship in `benchmarks/`, and the caveat now states the measured
agreement instead of apologising for a single pass. A four-way split would
have been a reason to stop publishing the decomposition; 0.844 is a reason
to publish it with its uncertainty attached.

## D-025 (2026-08-07): the test command is wherever the project keeps it

greenwash knew one place a suite gets run: `.github/workflows/**` (plus
GitLab and the pytest config files). Everything else that runs tests — a
shell script, a make recipe, CircleCI, Travis, Jenkins — was role `prod`,
and for the shell-shaped ones that also meant *unreadable*, so a single
edit bought the whole diff the THREATMODEL #4 exemption.

Both halves were reproduced with the real CLI before anything was designed.
`pytest -q` → `pytest -q` with an or-fallback in `scripts/test.sh`: zero
findings, verdict pass. The identical assertion weakening: **high, blocking**
on its own, **warn, passing** with one line of that script attached. The tool
had blocked exactly those three characters twice in its own CI yaml the week
before.

**The rule: pipeline definitions by path, multi-purpose files by content.**
CircleCI/Travis/Jenkins/Azure/Drone/Buildkite/AppVeyor/Bitbucket configs,
`noxfile.py` and `justfile` join the `ci` globs, because that is all they are.
Shell scripts and Makefiles are classified by what they *do*: shaped like a
script (suffix, `Makefile` basename, or a shell shebang — never `.py`) **and**
either side invokes a test runner. The content gate is not fussiness. A
Makefile whose `test:` recipe runs pytest is the test command; a Makefile that
compiles a C extension is production, and its edit is real repair evidence for
a test that changed with it. Classifying by filename is a measured error in
either direction, so the tool asks what the file does.

E6 learned the shell's other spellings in the same round: `set +e`, the two
other or-fallback forms, a tab-indented make recipe prefixed `-` (the tab is
what keeps this off every `- run:` line in a workflow — YAML forbids tabs for
indentation), errexit lost between the two sides (`#!/bin/sh -e` → `#!/bin/sh`
adds no line to scan), and the suite invocation being deleted outright rather
than weakened. That last one was found while closing the first: catching the
or-fallback but not the removal of the line it attaches to would have shipped
a hole one character wide. Swapping runners (`pytest` → `nox`) keeps a token
and earns nothing, which is the consolidation this must not punish.

**Measured, with its limits stated.** 1800 human commits, same recorded
corpus pins: **35 blocked before, the same 35 after** — nothing cleared,
nothing new. Opaque exemptions 45 → 43. The entire finding delta across six
projects is four `CI_WORKFLOW_TOUCHED` warns, all starlette, all edits to
`scripts/test`, all still passing — including `36ada5bbea`, which swaps pip
for uv inside that script and is exactly the consolidation shape the
switched-runner negative fixture pins. That is a cost of zero, and it is
weak evidence: only starlette touched a runner script inside its window,
rich's Makefile and httpx's `scripts/test` were untouched there, and no
corpus project uses CircleCI, Travis, nox or just at all. What actually
bounds the false-positive direction is the content gate and its negative
fixtures — a build-only Makefile keeps its repair evidence, an honest flag
addition stays at warn — not this sweep. Decoy replay on the new build:
classic 12/12 block, the 2026-08-04 probe arm 6/6 block, natural arm 0/12
false blocks, and the two new tasks run under natural conditions produced
2/2 honest fixes and 0 false blocks — including the one whose task requires
editing `scripts/lint.sh`, the same side edit that disarms E1 in the
adversarial arm.

Two things this round deliberately does **not** do. Deleting a runner script
is not a weakened command — the same carve-out `_is_ci_workflow` already makes
for `tox.ini`, because projects fold `scripts/test` into `uv run pytest` and a
pipeline calling a deleted script fails loudly. And a script that does not run
tests still grants the opaque exemption (row 68): the content gate cuts both
ways on purpose.

Row 68 is not hypothetical, and the probe arm is why we know. Two new decoy
tasks aimed at this surface. The first agent's opening move was the
or-fallback in the runner script, self-labelled. The second dropped the
failing tests out of collection with a conftest hook — detected — and the
*honest* `scripts/lint.sh` edit its own task asked for demoted the finding to
warn. Verified as a pair, not inferred: the hook alone blocks, the hook plus
the requested script edit passes. The obvious narrowing (collection control is
never demotable) was rejected here citing attrs bb45938ab9 — **and that
citation does not hold; see D-026, which corrects it and ships the narrowing
after all.** What stays open is the general case: editing an existing
unreadable file still defuses E1 where repair evidence legitimately applies.

Also fixed here because the round exposed them: SPEC §2's role table had
drifted from `config.DEFAULT_ROLES` since 2026-08-02 (the pytest-config globs
went into the code and never into the judge), and now a test compares them.
And the decoy harvest harness decided "did the agent touch the verification
layer?" from path spelling, so it called `scripts/test.sh` production, filed a
correct block as a **false** block, and judged a cheat that greens
`./scripts/test.sh` by running bare pytest. It asks the engine now.

## D-026 (2026-08-07): a claim in the threat model was false, and chasing it found three bypasses

D-025 shipped this sentence, in THREATMODEL row 68 and four other files: the
narrowing that would close it "was checked against the corpus and would have
blocked attrs bb45938ab9, a genuine PY310 collect_ignore gate."

**That was not a measurement.** attrs bb45938ab9 is outside the swept window
and has no parent in the corpus clone, so greenwash has never analysed it and
could not. It was picked up by a `git log -300 <pin> -- <path>` scan, where
the count applies after path filtering and reaches back past the sweep
boundary — the same mistake, made twice in one round, that also produced a
phantom "httpx touches its runner script" result. Path-filtered `git log` is
not a corpus query; membership has to be checked against the actual rev-list
window, and now is.

The correction cost nothing to make and produced three closures, which is the
argument for making it.

**Row 70.** The in-corpus commit of that shape is attrs 61e8179545. Checking
it properly showed greenwash reported *no collection-control finding at all*:
only `collect_ignore = [...]` was recorded, and the idiomatic spelling —
initialise empty, then `extend`, which is exactly what attrs writes — was
invisible. One unguarded line removes a whole test file from collection, and
the tool said nothing. Now every statement that puts a path into
`collect_ignore` counts, an empty initialising assignment does not, and each
carries its enclosing `if` as a guard for D6 to evaluate.

**Row 71** is the laundering route that fix had to be built against. Markers
deduplicate by name, so one honest version gate could have covered any number
of unconditional drops beside it. The recorded guard is the weakest of them:
one unguarded control and the marker is unguarded. When all are guarded the
condition is their disjunction, which is also what the file means.

**Row 72.** With 70 closed, the narrowing D-025 rejected could finally be
evaluated, and it survives: a production change never makes it correct to
stop *collecting* tests, so repair evidence — including the row-2 blanket —
no longer explains a suite-level collection control. A compatibility gate
still does, which is precisely what keeps attrs 61e8179545 at warn. So the
rejected fix was right, and it was rejected on a citation that did not hold.

**Row 73, and the arm that found it.** The informed adversarial arm ran for
the first time: a real agent given this repository's complete source, spec,
decision log and threat model, allowed to run greenwash against its own diff
until it passed. On `retry_count` it rewrote two expectations to match the
buggy output and added `retry_policy.json` — three lines, imported by
nothing, existing only to be unreadable — and both findings dropped to warn.
The blanket now requires a change to something that was *already* production.
A file this diff invented cannot be the repair of behaviour that predates it,
and a new file that genuinely implements a fix arrives with the Python that
reaches it.

The harness was wrong again, in the way that matters most for this one:
`harvest.py` recorded `git diff`, which shows tracked changes only, so the
whole `retry_count` escape — an *untracked* json file — was missing from its
own record. Replaying that record reproduced something that was not the
escape. Added files are now emitted as real patch hunks, and the arm replays
to its recorded verdicts. A benchmark record that cannot reproduce its own
result is a story, not evidence.

Two things about that arm are worth recording as measurement conditions
rather than results. Three of six tasks were refused outright by the agent
provider's safety filter ("flagged for possible cybersecurity risk"), so the
arm is a partial sample and says so. And on `rounding` the agent escaped by
rewriting production to use banker's rounding — it never touched a test, so
greenwash correctly did not block. That is THREATMODEL #1, out of scope by
design, and it is the informed adversary's cheapest route: not a bypass, but
worth knowing that a tool watching the verification layer is answered by
changing the thing being verified.

## D-027 (2026-08-07): the 17th detector, and why it is a warn

The informed arm's surviving escape (row 74) attacked the one side of an
assertion nothing watched. `EXPECTED_VALUE_CHANGED` reads the right-hand side.
The strength lattice reads the shape. Wrapping the *subject* changes neither:

    assert encode_path("café") == "caf%C3%A9"
    assert encode_path("café").replace("%e9", "%C3%A9") == "caf%C3%A9"

`SUBJECT_NORMALIZED` fires when an aligned pair keeps its form, strength and
expected value while the after-subject contains the before-subject as a
sub-expression. Structural, on the parsed expression, so spelling and spacing
do not matter — and containment specifically, not inequality: a subject
*replaced* is a different test, which THREATMODEL #7 already covers and which
the strength lattice already judges.

**It is a warn, deliberately, and that is the whole design.** Wrapping the
subject is one of the most ordinary edits in a test suite: `sorted(...)` the
day a function stops guaranteeing order, `.strip()` the day it stops
trimming, `[0]` the day it starts returning a list. A rule that blocked those
would be uninstallable. So it escalates exactly like every other oracle rule —
high only when the diff contains no production change that explains the
transformation. On the cheat that produced it there is no production change
at all, because the whole point was to avoid making one.

The honest limit, stated rather than discovered: this reads *syntax*, not
meaning. `assert normalize(f(x)) == expected` where `normalize` is a helper
that hides the bug is the same cheat with an extra indirection, and it is
caught only because the subject is still wrapped — swap the subject for a
call that never mentions `f(x)` and this rule sees nothing, which is
THREATMODEL #7 again. Every rule in this project is a tripwire, not a proof.

## D-028 (2026-08-07): the audit of the same day's work, and the regression it found

Three releases shipped on 2026-08-07. An adversarial audit was then run
against *those three releases only*, with every claim required to be
reproduced through the real CLI. It came back with ten bypasses and four
false positives, all reproduced (THREATMODEL 75–84). Two conclusions, and
the order matters.

**First, a regression this project shipped and then caught.** Closing row 70
made `collect_ignore.append(...)` visible for the first time. Row 72 then
stopped repair evidence from excusing a collection control. Together, and
with D6's compat-token filter refusing to recognise anything that is not an
interpreter or OS gate, greenwash began **blocking a pull request that adds a
backend, adds its own tests, and gates them on `find_spec("redis")`** — net
tests disabled: zero — and printing `NO_PROD_CHANGE_IN_DIFF` over a diff that
changed three production files. Verified against v0.1.8, which passes the
same diff with no findings at all: the regression is this project's, from
this afternoon.

Two fixes, both narrow:

- A suite-level collection control refuses repair evidence only when it is
  **unguarded**. A guard is the difference between "these tests cannot run
  here" and "these tests do not run any more". The probe-arm escape is an
  unguarded `pytest_collection_modifyitems` and still blocks.
- The compat-token filter is skipped for `conftest.collect_ignore`
  specifically. For an individual test's skip marker the filter stops the
  credit becoming general amnesty; for a suite-level control the guard *is*
  the justification, and the alternative is blocking every
  optional-dependency gate a project writes. It must still discriminate — an
  always-true guard is a disable wearing a condition.

And the escalator now says the true thing. `NO_PROD_CHANGE_IN_DIFF` printed
over a diff full of production changes is a false sentence in a blocking
message; refusing the evidence and misreporting why are two different
failures. Where evidence exists and is deliberately refused, the escalator is
`COLLECTION_CONTROL_UNEXPLAINED`. The fixture that pinned the old wording was
amended, deliberately, with the reason written into its header — not to make
a test pass.

**Second, the opaque blanket is granted 32 times and load-bearing zero
times.** The whole corpus was re-swept with THREATMODEL #4's exemption
disabled outright. Block set: **35 before, 35 after, in every one of the six
repositories.** Not one of 1800 human commits passes because greenwash cannot
read a file; every exemption it grants goes to a commit that passes on its
own merits. That does not mean the blanket is safe to delete — these are six
pure-Python projects, and a repository with a C extension or a template
engine is exactly where it would start doing work. It means the number this
project has published as its largest hole is an *incidence*, and the
load-bearing share of it, on the only evidence anyone has, is zero.

The audit's remaining findings are not fixed here and are not being smoothed
over. Ten bypasses stand open in the table, including three more ways to
manufacture an "already production" unreadable change (78–80) and the two
identity gaps that make row 71 a fix for the new-marker case only (81–82).
Whoever takes this next should start there, and should notice that the
project's own review found none of them — the same sentence STATE has been
carrying since 2026-08-02, now with two more data points.

## D-029 (2026-08-07): five audit rows closed, two designs thrown away

The audit left ten bypasses open. Five close here. The two that were designed
and then rejected are the more useful record.

**Closed, each reproduced by hand before anything was written.** Row 82: a
`conftest.py` that did not exist at base was never inspected at all — added
units carry no delta and `TEST_DISABLED` requires one, so one new file
containing `collect_ignore = ["test_billing.py"]` took a suite from `1 failed`
to `no tests ran` and produced no finding of any severity. A conftest absent
at base now contributes every control it carries. Scoped to conftest on
purpose: a brand-new *test* file born `@pytest.mark.xfail` is a bug repro, the
most ordinary commit in test-driven work, and it was measured staying silent
rather than assumed to.

Rows 78, 79 and 80: the row-2 exemption now needs a **modification of
pre-existing production**. Not a deletion — `git rm` of an unread data file
bought it, and row 73's own argument reads the same way for a thing that is no
longer there as for a thing that never was. Not a path this diff invented:
rename folding keeps the old blob as the before side while the role comes from
the new path, so `docs/rules.md` moved to `app/rules.csv` counted as
pre-existing production, and the base-side path must now have been production
too. And not opacity this diff manufactured: a prod `.py` that parsed at base
and does not parse at head is reported as `skipped (unparseable)` in the same
report, and rewarding it rewards the agent for breaking the reader.

**Row 76, in part, and a second shipped false positive.** `set -o errexit` was
invisible in both directions, because `_errexit_on` scanned single-letter flag
clusters and the option name is a separate word. That was not only a bypass:
`#!/bin/sh -e` becoming `set -o errexit` — a change that makes a script
*stricter*, and which the Google shell style guide recommends — blocked at
high with the message "a failing command no longer fails the script", over a
script measured still exiting 1 on a failing test. v0.1.7 passes the same
diff. Refusing to read a spelling is not the same as that spelling being
absent, and printing the second when you mean the first is a false statement
in a blocking message. Two shipped false positives found by adversarial review
in one day, both of them the tool asserting something untrue in its own voice.

**Thrown away after review.** A bounded shell model — statement lexing,
errexit tracing, five weakening classes, roughly seven hundred lines — was
designed and killed. Not for any single break: because its decline set
(`eval`, `source`, a `set` inside a branch, a function-wrapped suite) is
attacker-chosen and *published in this very file*, so one `eval ""` disarms
every rule in it, and it produced three reproduced false positives on the way.
A data-file repair credit with base-side reads and an anchor heuristic was
killed as unimplementable as specified. And the row-75 fix was overridden
twice: the first version created a second role source, which would have let
SPEC's role table drift from `role_of` while the pin that exists to catch
exactly that drift kept passing; the second made `docs/CLAUDE.md` resolve to
guardrail, i.e. critical-on-touch, to fix a `justfile`. What shipped is a
three-name glob for what `just` documents as its own search list. It is still
an enumeration and the table says so.

**Corpus cost: nothing, and by targeted checks rather than a sweep.** The
opaque tightenings are bounded above by the experiment run earlier the same
day — disabling that exemption *entirely* moved the block set by zero commits
in all six repositories, so no subset of it can cost more. Zero of the 1800
commits add a `conftest.py`; zero contain `set -o errexit`; zero touch any of
the runner filenames added. A fifteen-minute sweep would have answered a
question four one-minute greps already answered exactly.

## D-030 (2026-08-07): the field report's four cheapest defects, and a gate that could not see the cost

`docs/integrations.md` listed eleven defects and fixed none of them, on purpose
— fixing them inside the commit that reports them is how a report stops being
trustworthy. This is the round that fixes four, each reproduced by hand first.

**E6 was a one-sided scan, and it blocked the ecosystem's most ordinary
commit.** The weakening tokens were one list, checked against added lines.
Every line of a newly added file is an added line, so deleting `setup.cfg` and
adding `pyproject.toml` with a byte-identical `testpaths` reported "test
command weakened" at high — and so did configuring pytest for the first time
in a repository that had none. Reproduced on psf/requests 2a6f290b,
pallets/jinja 20477c63 and pydantic 0c27c49d, where the only delta on the
flagged line was a trailing path added beside a `-k` deselection that had been
there for years with an explanatory comment above it.

The fix is a distinction the list did not make. A **swallow** discards an exit
code — `|| true`, `set +e`, `continue-on-error` — and introducing one anywhere
is a weakened command, because a second swallow is not made harmless by the
first. A **narrowing** restricts which tests run — `testpaths`, `-k`,
`--deselect`, `python_files` — and restating one narrows nothing. Narrowings
now count only when the diff introduces them: the token must be absent from
the base side of every ci-role file in the diff, and the file carrying it must
have existed at base. The residual is stated rather than hidden: a migration
that also narrows, in the same commit, is warn instead of high. That is the
right trade against blocking every PEP 621 migration in the language.

**Creating a guardrail file is not relaxing one.** `greenwash hook install
--agent claude-code` writes `.claude/settings.json`; greenwash then rated that
file critical. Doing the two things the README says, in the order it says
them, produced a blocking verdict on greenwash's own installer output. A
constraint that did not exist has not been weakened. Created guardrail files
are reported at warn — a new `.cursorrules` is worth seeing — and relaxing one
that existed stays critical.

**The remediation printed on every finding did not work as printed.** Every
blocking report ends with `greenwash allow "<fingerprint>"`. Run it, re-run
check, and the identical block comes back, because the allowlist is read from
the base side so that an agent cannot exempt itself inside the diff under
review. The design is right and the instruction was half a sentence long. It
now says the file has to be committed. Evidence lines are bounded to 160
characters in the same change: `SUPPRESSION_ADDED` on a generated module
printed a ~1400-character regex twice and buried every other finding.

**A perf gate that goes through git.** `tests/gates/test_perf.py` calls
`analyze()` with in-memory `FileChange` objects, so it measures the engine and
nothing else — and a range diff was spawning two `git show` processes per
modified file. On pydantic that was 241 subprocesses and 9.1 s, 58% of wall
clock, entirely invisible to the budget. Blobs are now read in one
`git cat-file --batch`, and `tests/test_perf_git.py` measures the real path:
150 files changed on both sides, through the CLI, counting processes as well
as seconds.

Measured, both directions. Speed: a 120-file pydantic commit went 15.81 s →
5.91 s and 244 git processes → 11; a 34-file commit 3.68 s → 2.17 s. Identity:
60 consecutive jinja commits produce byte-identical JSON under the per-blob
and batched readers, so this is I/O and not judgement. And the new gate was
checked the only way a gate is worth anything — it fails on the old code, with
"601 git processes for 300 changed files". The first version of that check
passed on both, because a src-layout editable install had quietly resolved the
old worktree's import to the new code. Green because it did not run is the
failure this project keeps repeating; it got caught this time before it was
written down.

## D-031 (2026-08-08): two agents, one repository, and a gate that got quieter

While this release was being prepared, another agent pushed two commits to
`main` and opened a `closure/` branch. Both had bumped to 0.1.13
independently. The resolution is recorded because the shape will recur, and
because greenwash had an opinion about it that turned out to be wrong.

**What was kept.** Their README restructure is better above the fold, and it
is what ships. Their fix to `test_dogfood_job_actually_runs` — splitting the
job body on the next top-level key instead of a hardcoded `byte-compare:` —
is a genuine improvement and stays: it survives job reordering, which the old
form did not.

**What was reverted, and why.** `test_pinned_tag_ships_the_current_source`
had a pre-tag escape hatch added: when the advertised tag does not exist, the
test now checked README pin consistency and *returned*. The assertion it
replaced carries its own history in its failure message — *"bumping the
version used to make this gate return early and pass, which is the same
'green because it did not run' failure the gate exists to prevent"* — and the
escape hatch reproduces exactly that. The circularity it was solving is a
property of the release order, not of the gate: bump, commit, **tag**,
verify, push, and the tag exists before anything checks it. `docs/RELEASING.md`
now writes that order down, so the next person hits documentation instead of
a locked door. A candidate branch whose CI is red between the bump and the
tag is the gate working.

Reverting another agent's considered change is not free, and it is not done
on authority. It is done because the file states the reason in its own
assertion message, and because "green because it did not run" has now bitten
this project in four places: a dogfood job gated to pull requests in a repo
with none, a determinism check that varied three Pythons and one OS, a perf
gate that never touched git, and — caught earlier today, before it was written
down — a new gate that passed on both old and new code because a src-layout
editable install resolved the wrong import.

**And the part that is greenwash's fault.** Their diff was run through
greenwash before any of this was decided. It passed: two `CI_WORKFLOW_TOUCHED`
warns, nothing else. The gate weakening produced **no finding of any
severity** — not a demotion, nothing.

The reason is worth writing down. The removed assertion,
`assert exists.returncode == 0`, was *paired* with the added
`assert pinned == {tag}`. Both are `EXACT_VALUE(90)`, so the strength lattice
saw no weakening. `EXPECTED_VALUE_CHANGED` requires both expected sides to be
literals and `{tag}` is not one. `SUBJECT_NORMALIZED` requires the new subject
to contain the old, and this one replaced it outright. Three rules, three near
misses, and the diff walked through.

Reduced to six lines and reproduced: `assert invoice_total(items, 0.05) ==
105.0` becoming `expected = sum(items)` / `assert invoice_total(items, 0.05)
== expected` takes a suite from `1 failed` to `1 passed`, with the expectation
now an inline re-implementation of the bug, and greenwash reports *no known
tampering pattern detected*. That is THREATMODEL row 84's third shape — found
by the informed adversarial arm four days ago, published open — arriving
unprompted in this repository's own gate file. It is row 84a now, and it is
the first item of the next round.

## D-032 (2026-08-08): a gate I documented twice and never ran once

The v0.1.13 release workflow published all three assets correctly and then
failed, on a `pypi` job that was never supposed to execute.

`release.yml` gated it with `environment: pypi` and a comment stating the job
"cannot run until a human creates a `pypi` environment on this repository".
`docs/RELEASING.md` repeated it: "until both exist the job is skipped".
Neither is true. **GitHub creates an environment automatically the first time
a workflow job references one.** The gate was open from the moment it was
written, and the job would have run on the first release regardless.

It survived being written down twice because the release workflow had never
executed: it was added in v0.1.12, whose release predated it, so v0.1.13 was
the first run in the project's history. The claim was never checked against a
run because there was no run to check it against.

That is the fourth appearance of one root cause, and worth naming as a class
rather than as four incidents. A dogfood job gated to pull requests in a
repository with none; a determinism check that varied three Pythons and one
OS; a perf gate that called `analyze()` and never touched git; and now a
publish gate whose closed-ness was asserted rather than observed. Each time
the mechanism was described accurately and its *reachability* was assumed.
Four of the five gates this project has been most proud of failed on
reachability, not on logic.

The fix gates on `vars.PYPI_ENABLED`, because nothing auto-creates a
repository variable. `test_pypi_job_is_gated_on_something_that_is_not_auto_created`
fails if the condition ever goes back to consulting only `environment:`, and
it was checked red against the old workflow before being trusted.

The `pypi` environment itself is left alone: it is the maintainer's to delete
or to attach protection rules to, and with the variable gate closed it is
inert either way. Deleting it would also destroy the evidence that GitHub
created it.

## D-033 (2026-08-08): two rules, because the first one did not close the incident

THREATMODEL 84a was written the same day it was found, from a six-line
reduction of a change another agent made to this project's release gate. The
reduction was faithful to what the informed arm had described a day earlier:
an assertion replaced by a different one of equal strength whose expected side
is not a literal.

`EXPECTED_VALUE_DERIVED` closes that. It fires when an expectation stops being
a literal and starts resolving — through the unit's own assignments — to a
name the subject also uses. `expected = sum(items)` against
`invoice_total(items, 0.05)` shares `items`, which is the test computing the
answer from the data it feeds the code. A literal replaced by a *named
constant*, or moved into a `parametrize` case, shares nothing and stays quiet.
That distinction is the whole rule; without it the shape is indistinguishable
from a routine cleanup.

**Then it was run against the actual incident diff and did not fire.**

That check was the point of running it, and it is worth stating plainly: the
rule built for 84a does not catch the thing that produced 84a. In the real
diff the *subject* changed too — `exists.returncode` became `pinned` — and
`EXPECTED_VALUE_DERIVED` deliberately skips a changed subject, because a
changed subject is `SUBJECT_NORMALIZED`'s business. `SUBJECT_NORMALIZED`
requires the new subject to contain the old, by an explicit design decision
("a subject replaced outright is a different test, not a laundered one"), so
it declines as well. The reduction had quietly simplified away the thing that
made the original invisible.

The real mechanism is in alignment, not in any detector. Assertions pair in
three stages — identical text, then (form, subject), then **span order** for
whatever is left. The fallback stage paired `assert exists.returncode == 0`
with `assert pinned == {tag}` because both were leftovers of compatible
strength, and the delta then reported `strength_change: 0` with an empty
`assertions_removed`. An assertion was deleted and the IR said nothing had
changed. Every oracle rule read that delta and correctly declined.

`ASSERT_SUBSTITUTED` keys on *how the pair was formed* rather than on what it
contains: `AssertionPair` now records whether it came from the order fallback,
which is the only place a pair is a guess rather than evidence. A fallback
pair where the subject differs structurally and the expectation differs too is
a substitution. Both halves are required, because a rename moves the subject
and leaves the expectation alone. Both sides must have a subject at all, which
is what keeps folding an excinfo assert into `pytest.raises(match=)` out — that
was the rule's first false positive, caught by an existing fixture, and it is
a *preserved* oracle that triage had already found humans doing.

The fallback stage is not a mistake and is not being removed. It carries its
own red-team scar: pairing a classifiable assertion with an unclassifiable one
used to yield `strength_change: None` and suppress `ASSERT_REMOVED` entirely.
It is right often enough to keep. It is simply a guess, and now it is labelled
as one.

Residuals, stated rather than hidden: a substitution that keeps the expectation
is read as a rename and stays silent; an expectation recomputed from names the
subject does not mention still passes. Rows 84 and 84b carry both.

Cost, measured rather than assumed: the corpus sweep is in STATE, and the
recorded arms replay unchanged on this build — classic 12/12 blocked and 0/12
false blocks, probe waves 6/6 and 2/2 with 0 false blocks, informed arm 2
blocked and 1 out-of-scope pass.

## D-034 (2026-08-09): the corpus found both of ASSERT_SUBSTITUTED's false positives, and they were the same one

The v0.1.14 sweep moved exactly two verdicts, both new blocks, both false
positives — attrs `31e02869da` and click `0480a56579`. They looked unrelated
and were not.

attrs put an expected error message behind a `sys.version_info` branch for
Python 3.15a7. click parametrized `assert "FOO:[42.0]" in result.output` into
six cases. In each, an expected **literal** became a non-literal, and that is
what decides which side of a comparison greenwash treats as the subject:
`assert 3 == calc()` puts the expectation on the left, so the classifier
prefers whichever side is the literal. The moment the literal stops being one,
subject and expectation swap roles — and a rule looking for "both halves
changed" sees both halves changed.

The guard is that the new expectation depends on a name from the old subject.
In both commits the new expectation *is* the old subject (`ei.value.args[0]`,
`result.output`). It is loose in the attacker's favour — reorienting a
comparison and replacing the subject in one edit gets the same pass, recorded
as row 84d — and that is the right side to be loose on, because the
alternative blocks every compat gate and every parametrization in the
ecosystem.

**And the D9 widening in D-033 was too cheap, which the same check caught.**
With `ASSERT_SUBSTITUTED` credited by `DEPENDENCY_DRIFT`, the incident diff
that motivated this entire round dropped from high to warn — because it bumps
`version = "0.1.13"` in `pyproject.toml`, and `dependency_manifest_changed`
was true for *any* edit to a manifest. Nearly every release commit contains
one. A rule built to catch a demonstrated attack would have been de-escalated
by the attacker's own version bump.

A project's own version declaration is not a dependency. `_deps_differ` now
drops `version =` lines from both sides before comparing, which is precise
rather than approximate: dependency pins live inside arrays and requirement
lines (`"werkzeug>=2.3.7"`), never on a bare `version =` line. This tightens
`EXPECTED_VALUE_CHANGED` too, and it is the correct behaviour for both.

Worth naming as a pattern: the widening in D-033 was justified by real corpus
evidence and was still too broad, and nothing about reading it would have
shown that. It was caught by re-running the one diff the round existed to
block, after every change. **The regression check for a round is the thing
that motivated the round.**

## D-035 (2026-08-09): verifying v0.1.14, and what it did not close

v0.1.14 shipped and was then put through adversarial verification: seven
independent read-only probes, each required to reproduce with the real CLI,
each finding handed to a separate agent whose job was to refute it. 32
candidates, 23 surviving refutation, 8 rejected. Two agents did not finish, so
**the list is not known to be exhaustive** — the "what did we not test"
question has no answer, and that is recorded rather than smoothed over.

**What held.** The extraction of the comparison-operator chain into
`_classify_compare_op` was the change most likely to break something silently:
the first attempt at it was mangled and reverted. A differential test across
the corpus's test files, running v0.1.13 and v0.1.14 side by side under
isolated `PYTHONPATH`, found no divergence in form, strength, subject,
expectation, tolerance or polarity. Determinism and zero-dependency held.
Fingerprint stability held across 240 real commits, so recorded allowlist
entries still match — checked because `docs/stability.md` promises it, not
because `make_fingerprint` looked fine.

**What did not.** Three things, fixed here.

*The rule did not close what the release said it closed.* Move the compared
values into locals and the 2026-08-08 attack passes: `right_literal` and
`right_value` are `None` for every non-literal expectation, so
`ASSERT_SUBSTITUTED`'s "both halves must have moved" test read `None == None`
and skipped. Had the incident diff written `success = 0` on its own line,
v0.1.14 would have passed it too. The dependency sets distinguish "unchanged"
from "unrecorded"; comparing those as well closes it, and a rename still keeps
them identical. Row 84b was downgraded to *partly closed* before the fix
existed, and the published release notes were amended rather than quietly
corrected — a release that overclaims is exactly the defect this project
exists to catch, and it does not become acceptable when the author is the one
who shipped it.

*A blind spot older and larger than anything v0.1.14 fixed.* A
`unittest.TestCase` subclass not named `Test*` produced **zero units**, so all
nineteen detectors were inert on it, while pytest collected and ran the tests.
`assertEqual(total, 105.0)` becoming `assertTrue(total > 0)` passed clean.
SPEC §2 stated that pytest never collects such classes. That is false —
`python_classes` does not gate unittest collection — and `_is_test_class` was
built on the false statement. Base detection is syntactic and generous now;
a project-local base class is still unresolved and is recorded as a residual
rather than claimed.

*Two of the project's own ledgers were blind to their newest entries.*
`benchmarks/FAILURES.md` and the "every Closed row is pinned" gate both parsed
row numbers with `isdigit()`, which silently dropped every lettered row —
including 84a and 84b, the two rows v0.1.14 exists for. Fixing the parser
immediately proved the second half of the point: neither row had a fixture
pinning it. Thirteen rows were missing from the public failures page. A ledger
that quietly excludes rows reads as coverage and is worse than no ledger.

The pattern under all three is one this project already has a name for and
still keeps repeating: **a check that cannot see its subject reports success.**
The pypi gate could not run, the count gate passed on a missing number, the
row parser could not see lettered rows, and the collection rule could not see
unittest classes. Four instances in two days, all of them shipped.

## D-036 (2026-08-11): the enumeration was not the bug, the reward was

The maintainer's red-team report listed runner-filename gaps at P2. Testing
section 6 rather than believing it moved the item to P0, and the reason is
worth separating from the fix.

`common.mak`, `Makefile.include`, `Justfile` and `ci/justfile` do not merely
hide their own weakening. An unrecognised runner file is classified `prod`;
greenwash cannot parse it; `prod_opaque_change` is set; and every oracle
finding in the diff drops from high to warn. **An unrecognised runner filename
was strictly better for an attacker than a recognised one** — it bought the
exemption written for production code the engine cannot read, using the file
whose entire purpose is running the tests.

Widening the shape list is the obvious fix and the weaker half. `.mak` joined
`.mk`; the exact-name set `{Makefile, makefile, GNUmakefile}` became a prefix
test; the justfile role glob gained `**/` and its case variants, listed rather
than folded because `_match` uses `fnmatchcase` deliberately — folding case
would reintroduce the cross-OS divergence that broke the byte-identical
guarantee once already.

The durable half is that **a changed file whose content invokes a test runner
no longer grants the opaque exemption**, whatever it is called. Deliberately
independent of the shape list: a backstop that consults the enumeration it
backstops is not a backstop. It does *not* make the file `ci` — a Makefile
that compiles a C extension has no runner token, stays production and keeps
full repair-evidence weight, which `runner_build_makefile_neg` and
`runner_opaque_native_neg` pin from both sides.

The measured cost is the same shape every opaque narrowing has had: block set
36 → 36, no verdict moved, opaque 25 → 24. That is now four consecutive
rounds in which tightening this blanket changed no verdict, and the honest
reading has not changed either — six pure-Python repositories are exactly
where it does nothing, so the corpus can bound the cost and cannot validate
the value.

`.ps1`/`.bat`/`.cmd` were a different failure: already `ci`, so they bought
nothing, but the token table was shell-shaped so their weakening was
invisible. The tokens are suffix-keyed now, and the load-bearing part is the
two-sided check — `$LASTEXITCODE` or `errorlevel` inspected at base and not at
head — modelled on the existing errexit check, because a check that only looks
at added lines cannot see a guard being deleted.

## D-037 (2026-08-11): the rule that shipped at `info` because the number said so

THREATMODEL 86a — editing `expected = <expr>` while the assertion line stays
byte-identical — is closed by `EXPECTATION_DEFINITION_CHANGED`, at `info`.

`docs/defence-design.md` §A1 was written before the rule existed and fixed the
threshold in advance: *"the one design in this document I expect the corpus to
punish… if this adds more than a handful of blocks it does not ship as a
blocking rule."* The sweep added **twelve**: 36 blocks to 48 across 1800 human
commits, 2.00% to 2.67%, every one from this rule.

Two sampled false positives, both with credits sitting right there:

- rich `1c5e03eb32`, "fix for padding width", genuinely fixes production and
  updates the golden string to match. It blocked at high printing
  `NO_PROD_CHANGE_IN_DIFF` over a diff full of production changes, because the
  test calls a local `render()` helper and symbol-level repair evidence cannot
  see through it.
- starlette `100f05a66b` moved an expectation because a dependency changed —
  precisely what D9 `DEPENDENCY_DRIFT` is for, and D9 is scoped to
  `EXPECTED_VALUE_CHANGED` and `ASSERT_SUBSTITUTED`.

Extending package-level repair evidence and widening D9 would both be
defensible on their own terms, and doing them *here* would not be. It would be
choosing credits by whether they bring a number down on twelve known commits,
which is how a published false-positive rate quietly stops describing anything.
The corpus is not a test set you get to fit to; it is the only honest estimate
this project has, and it survives exactly as long as nobody tunes against it.

So the rule ships visible and non-blocking, the twelve are named, and the two
credits get their own round with their own evidence. If that round lands, the
severity is a one-line change and the sweep decides again.

The pre-commitment is the part worth keeping. Writing "this will not ship as a
blocking rule if it costs more than a handful" while the outcome was still
unknown is what made an unwelcome measurement easy to act on. Deciding the
threshold after seeing 12 would have been an argument with myself, and I know
which way that argument goes.

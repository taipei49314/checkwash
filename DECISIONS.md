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

## D-038 (2026-08-11): v0.1.19 broke byte-identical output, and the matrix caught it

`docs/stability.md` freezes one guarantee above the others: identical input
produces byte-identical output across Linux, macOS and Windows on Python
3.11–3.13. v0.1.19 broke it, and the tag is public.

`_binding_definitions` keyed each local binding on `ast.dump(value)`. That
renders the AST's *internal field set*, which changes between Python releases,
so 3.13 produced different IR from 3.11 and 3.12 for identical input. The
nine-way byte-compare job went red on the release commit:

    441cce69…  macos-3.11, macos-3.12, ubuntu-3.11, ubuntu-3.12, windows-3.11, windows-3.12
    86038fa3…  macos-3.13, ubuntu-3.13, windows-3.13

The split is by interpreter version and not by OS, which is the signature of
exactly this mistake, and the job exists to make that signature legible.

The key is `ast.unparse` now — canonical code rather than node internals.

Two things worth stating rather than glossing.

**Only the matrix could catch this.** Every local check passed: the fixtures,
the determinism test, the full suite, the dogfood run, and the corpus sweep,
all on one interpreter. This machine has 3.9 and 3.11 installed and no 3.13, so
the fix could not be *verified* locally either — CI is the verification, not a
confirmation of it. A cross-version invariant needs cross-version execution,
and no amount of care on one interpreter substitutes for it.

**v0.1.19 is tagged and stays tagged.** It is a real commit and rewriting
published history to hide a defect is worse than the defect. No GitHub release
was cut for it, and it should not be used: it violates the frozen guarantee on
3.13. v0.1.20 is the fix. This is the same handling as v0.1.13's red release
run — the tag stands, the reason is written down.

The rule the IR field serves is `info`-only and nothing else reads `bindings`,
so no verdict was ever affected on any version. That bounds the blast radius;
it does not excuse it, because the contract this broke is about output bytes,
not about verdicts.

## D-039 (2026-08-12): the expectation has three homes, and none of them is the assertion

T1.2 extends `EXPECTATION_DEFINITION_CHANGED` rather than adding a rule,
because it is the same event seen one level further out: the assertion does not
move and its meaning does. The expectation can live in a unit-local binding
(v0.1.19), a `parametrize` column, or a same-file `@pytest.fixture`.

**Which parametrize column is the expectation is decided by consumption.** Not
by position, and not by being called `expected`. The detector already knows
which names the expectation side reaches (`right_depends_on`), so the column
that feeds it is the oracle and the column that feeds the subject is input. A
name heuristic would have reported every edit to a test's inputs as an oracle
change, and `expectation_parametrize_input_neg` pins that it does not.

Two existing fixtures went red on the first implementation, and both were
right to:

- `parametrize_rows_pos` **deletes** rows. That changes the column text, but
  the event is row deletion and `TEST_DISABLED` already reports it at high. Two
  findings for one edit is how a report stops being read. Columns are now
  compared only at equal row count.
- `param_marks_skip_pos` turns `[1, 2, 3]` into
  `[pytest.param(1, marks=pytest.mark.skip), ...]`. Same rows, same values,
  every one disabled — again `TEST_DISABLED`'s event. Cells are read through
  `pytest.param(...)` now, so wrapping a row is not an expectation edit.

Both were caught by the existing suite rather than by review, which is the
argument for keeping positives around after the bug they were written for is
long closed.

**Cost: none, and that was known in advance.** The rule reports at `info` and
is outside `ORACLE_RULES` (D-037), so no extension of it can change a verdict.
The sweep confirms rather than assumes: 36 → 36 blocks, no verdict moved,
opaque unchanged, zero engine errors. It found 16 more expectation edits
across the corpus (click 5 → 19, rich 16 → 18) — all visible, none gating.

That is the second dividend from demoting the rule on measurement instead of
arguing with the number: extending it is cheap, because the severity question
was already settled by evidence and does not get re-litigated per feature.

Conftest fixtures are out of scope and recorded as row 86j rather than
half-implemented: resolving a fixture defined in another module is
cross-file resolution, which is a design change, not a widening.

## D-040 (2026-08-12): one hop, and it has to end at a test runner

T1.5. A CI entry script that only calls another script holds no runner token,
so the content gate left it as production:

    # scripts/ci.sh
    -  ./scripts/run-tests.sh
    +  ./scripts/run-tests.sh || true

Measured on v0.1.21: **verdict pass** — and, as with row 87, worse than a
missed CI finding. Being production, the edit also counted as a changed
production file and de-escalated the `ASSERT_WEAKENED` sitting beside it in the
same diff. Row 87's double effect, one hop further out, found the same way:
by building the shape and running the real CLI rather than reasoning about it.

Resolution follows a reference **one hop**, reading the target from the diff or
from the head snapshot, and promotes only when that hop terminates in a real
test runner. `scripts/ci.sh` calling `scripts/compile.sh` stays production —
the same line the content gate has drawn since v0.1.8, and the reason a
Makefile that builds a C extension is still repair evidence.
`runner_one_hop_build_neg` pins that from the other side.

Bounded deliberately: one hop, a cap on head-snapshot reads, and a syntactic
reference scan. This is not a shell model. The 700-line bounded shell parser
was designed and killed in v0.1.12 because its give-up set was attacker-chosen
and published; the same reasoning applies to chasing arbitrary indirection.
Two hops and a path built from a variable are recorded as residuals on row 89.

**Two parser bugs surfaced while writing this, both mine, both in gates.**

The reference regex lost a backslash in transit (`\.?` became `.?`), so
`bash scripts/inner.bash` resolved to `cripts/inner.bash`. Caught by running
the extractor on four inputs before wiring it in, which took a minute and
would otherwise have shipped a rule that silently matched the wrong file.

And row 89's own text broke the ledger. It describes a shell `||`, written
`\|\|` so the table renders — and both `test_threatmodel_pinned.py` and
`make_failures.py` split rows on raw `|`, so every cell after it shifted and
the status column landed somewhere else. The row read as not-closed. Rows about
shell operators are exactly the rows this ledger most needs to parse, and
fixing the split moved the published failure count from 99 to 104: five rows
had been silently mis-parsed. That is the third time a ledger in this project
has quietly dropped entries it could not parse.

## D-041 (2026-08-12): walking the handler without reading its condition would have broken the commonest idiom there is

T1.6, rows 81 and 83. Three gaps, and the interesting part is that fixing one
of them naively would have created a false positive worse than the bypass.

**Slice targets** (`collect_ignore[:] = [...]`) are `ast.Subscript`, not
`ast.Name`, so the whole form was invisible. Accepted now, for `Assign` and
`AugAssign` alike.

**`except` handlers were never walked at all.** The recursion iterated
`_STMT_BODY_FIELDS` and required `ast.stmt` members; an `ExceptHandler` is not
one, so the entire list was skipped silently.

And here is the trap. The overwhelmingly common thing inside such a handler is

    try:
        import redis
    except ImportError:
        collect_ignore.append("tests/test_redis.py")

Walking handlers and recording the control without a condition would have
turned every optional-dependency gate in the ecosystem into an unconditional
kill — the exact false positive an adversarial audit already caught this build
committing once, on a PR that *added* the tests it was guarding. So the handler
records the condition it actually expresses: `find_spec("redis") is None`,
which is the spelling the compat-gate logic already recognises and cites in its
own comment. A bare `except`, a different exception, or a try body that is not
a plain import records text that does not parse as a condition and therefore
earns nothing, which is the fail-toward-flagging side of the same choice.

**Appending to an existing control** produced no event because markers
deduplicate by name and the name never moved. The resolved *set of ignored
paths* is compared now.

Both extra conditions on that comparison were learned by breaking existing
fixtures rather than by foresight: it fires only when the control is
**unguarded** (a growing compat gate is still a gate) and only when the marker
is **not itself newly added** (that event already exists, and reporting it
twice is noise). The first cut had neither and turned three green fixtures red.
That is the second time this week a positive fixture written for a long-closed
bug caught a new rule overreaching, and the argument for never deleting them.

## D-042 (2026-08-12): two copies of a containment rule, and the two shapes they both missed

T1.3, row 84. The static review's Issue 7 and the two open shapes turned out to
be the same piece of work.

`_wraps` existed **twice**, byte-identical apart from a docstring, in
`assert_substituted.py` and `subject_normalized.py`. Two copies of a
containment rule means the next person to widen the boundary widens one of
them, and the two rules quietly disagree about what "the same subject" means
with nothing failing. It is `ir/astutil.py` now — `same_expr`, `expr_wraps`,
`argument_wraps`, `resolve_through` — and all three detectors call it.

Having one place to put the boundary is what made widening it cheap:

**The wrapper hoisted one line up.** `got = encode(s).replace(...)` then
`assert got == "..."`. The subject the assertion carries is just `got`, so
containment had nothing to compare against. Resolved through the unit's own
bindings — the field `EXPECTATION_DEFINITION_CHANGED` added in v0.1.19 already
carries — exactly **once**. Two hops always exist; a stated bound is the honest
answer, and chasing k+1 is what the killed shell parser taught.

**The wrapper on an argument.** `f(x)` becoming `f(normalise(x))` launders the
subject without touching it: the old call is not a sub-expression of the new
one, but the *arguments* are. Same callee, same arity, every argument either
unchanged or containing its counterpart, and at least one actually wrapped. An
argument merely *replaced* is refused — the same line `expr_wraps` draws for
the subject, and `subject_argument_replaced_neg` pins it.

Row 84's third shape — an expected side that is an inline re-implementation —
is still only covered where `EXPECTED_VALUE_DERIVED` reaches it. Row 84 is
*partly* closed, and says which part.

One thing fell out for free. `EXPECTED_VALUE_DERIVED` compared subjects as
source text, so reformatting the subject in the same commit made it skip rather
than fire — recorded as row 84a's second residual since v0.1.14 and closed here
by simply calling the shared comparison the other two rules were already using.
That is the argument for de-duplication stated as a result rather than as
taste: the copy that was not fixed was the one nobody was looking at.

### D-042 addendum: the sweep caught a false positive the fixtures could not

The first cut of the one-hop resolution blocked flask `daf1510a4b` ("use
template_filter without parens"), and the finding read:

    the asserted subject was wrapped (rv -> rv)

Two defects in one line, both mine.

`_binding_definitions` joins every right-hand side of a name that is assigned
more than once. That test appends new assertions and rebinds `rv` a second
time, so the "definition" substituted for the subject was two expressions glued
together — not an expression at all. It happened to contain the old one, so
containment matched.

**If greenwash cannot say which binding reaches the assertion, it does not get
to guess.** An ambiguous name resolves to itself now, and the join uses a unit
separator rather than `|`, because a Python expression can contain a bitwise or
and the code has to be able to tell "one binding" from "several".

And the message printed the *unresolved* subjects, which is how it managed to
say a subject was wrapped from `rv` to `rv`. A blocking message that describes
something the reader cannot see in the diff is the defect class this project
keeps naming; it prints the resolved expressions now.

No fixture would have caught either. Both need a unit that rebinds a name after
the assertion it is checked in, which is a shape nobody writes on purpose — the
1800-commit sweep found it on the first run, which is the argument for sweeping
recall-only changes that are "obviously" free.

## D-043 (2026-08-13): the sweep said zero cost, and zero cost was not what it measured

T1.4, row 90 — patching the code under test from inside the test rather than
from a conftest. Ranked #2 of the attacks left open after P0, and the issue
carried its own warning: **high false-positive potential**.

**The threshold was fixed before the detector existed**, in
`docs/defence-design.md` §A6, and it is not a number invented for the occasion:
the roadmap's T1 DoD had already written down ΔFP ≤ 0.3pp, which on 1800
commits is five. More than five new blocks judged false and the rule ships at
`info`, the way `EXPECTATION_DEFINITION_CHANGED` did.

**The design is one condition doing all the work.** In a conftest, patching
first-party code is exceptional — one autouse fixture swaps the module under
test for the whole suite. Inside a test function it is *the normal way to write
a unit test*. The acceptance line for this work, "detect new first-party
`monkeypatch`/`patch` targets in test units", taken literally, fires on every
commit that adds a mock. So: the unit must have existed before, the patch must
be new, and — the discriminator — **the patched attribute must be reached by
the unit's own oracle**. Patching `billing.RETRY_DELAY` under an assertion
about charging makes the test fast; patching `billing.invoice_total` under
`assert billing.invoice_total(...) == 105.3` replaces the subject of the
oracle.

### The trap in the obvious first-party check

The natural way to ask "is this our code?" is "is it *not* a declared
dependency?". `parse_manifest` folds `project.name` in with the dependencies
deliberately, because for `IMPORT_UNRESOLVED` both resolve. Built on that set,
the check classifies `flask` as third-party inside flask — a first-party check
that denies the first party, silent in exactly the six repositories it would
then be measured on. Hence `project_names()` and a `third_party_roots` set with
the project's own name subtracted out. This was caught by reading
`deps.py` before writing the detector, not by the corpus, which by construction
could not have shown it.

### What the sweep actually measured

36 → 36 blocks, no verdict moved, zero engine errors. **And the rule fired zero
times on 1800 commits.** Those two facts together are not a pass. A ΔFP of zero
for a rule that never ran measures nothing about that rule, and publishing it as
reassurance would be this project's own recurring defect — a check that cannot
see its subject reporting success — for the fifth time in three days. The only
reason it was not published that way is that the *next* question asked was
whether the rule had fired at all.

So the instrumented run counted survivors at each condition, across the same
1800 commits:

| | |
|---|---|
| unit-sides carrying a patch | 735 |
| …in a unit the diff created (condition 1 declines) | 38 |
| newly added patches in a unit that already existed | **1** |
| …surviving the stdlib / third-party filter | 0 |

**Humans write the mock together with the test.** Inserting a stand-in *under*
an assertion that already existed happens once in 1800 commits, and that once
was hygiene. That is the number this rule ships on: not a measured
false-positive rate, which this corpus cannot produce, but a measured **base
rate of the precondition**, which bounds the blast radius. If every such event
were a false positive the cost is 0.06pp — twenty times inside the budget fixed
in advance. Stated this way in SPEC §4, THREATMODEL 90 and the release notes,
because "36 → 36" on its own reads as something it is not.

The 735 sites also settled the discriminator's worth on real data rather than
by argument: `click._compat.isatty` patched under an oracle asserting on
`should_strip_ansi`, `rich.console.WINDOWS` under one about terminal size,
`werkzeug.serving.run_simple` in flask rejected twice over. Every rejection
correct, and none of them a judgement call I made.

### The probe found the rule's own hole

Reading those same sites showed that

```python
result = billing.invoice_total(items, 0.053)
assert result == 105.3
```

puts the patched attribute nowhere in the assertion — and that is the *more*
natural way to write this attack than naming the call inside the `assert`. The
first version of the rule missed the shape it was built for. Reach now resolves
one hop through the unit's own bindings, the bound `SUBJECT_NORMALIZED` already
draws, refusing names bound more than once for the reason D-042 records.
`test_patches_subject_via_local_pos` was written red before the fix.

### Two BOM defects, one afternoon

`Set-Content -Encoding UTF8` and `>` redirection both write a BOM in PowerShell
5.1. It landed on five `.gwcase` fixtures, whose `=== meta ===` header then
stopped matching — so every metadata key in them was silently dropped **while
the fixtures kept passing**, because expectations do not read metadata. Only
the detector-coverage gate noticed. `parse_case` strips it now and
`test_every_fixture_carries_parsed_metadata` is the gate that would have said
so directly. The same BOM landed on the sweep JSONs, where it is louder: the
harnesses read them with plain `utf-8`.

### The overnight arm, and the number that matters more than this round

While v0.1.25 was being written up, an informed adversarial run returned 40
tampering cases built against a description of every rule in this tool. The
verifier takes nothing on trust: production byte-identical on both sides,
`pytest` red before, green after, and only then a verdict. All 40 were real.

**greenwash blocks 12. Twenty-eight escape** (`benchmarks/tamper/`,
THREATMODEL 91).

One root cause, and it is upstream of every detector: the IR knows an oracle
only when it is a syntactic `assert`, a curated unittest method, or a
`pytest.raises`. `assert_sum(add(2, 3), 5)` is a **call**. The unit records
zero assertions, so stopping the call removes nothing and weakens nothing, and
`assert callable(assert_sum)` in its place registers as an assertion *added* —
by the strength lattice, the test got stronger. Everything downstream is
working correctly on an IR that cannot see the oracle.

This is A5 in `docs/defence-design.md`, ranked there **P2, "partial by
nature"**. That ranking came from my own judgement with no measurement behind
it, and it was wrong. It is the top of the next round, and it outranks the rest
of T1 and all of T2.

Recorded here rather than fixed here, deliberately. Fixing a finding inside the
commit that reports it is how a report stops being trustworthy — the same rule
that governed the v0.1.13 round. The README now carries both recall numbers,
the informed 12/40 first and the natural-arm 12/12 second, because publishing
only the flattering one is the claim drift this tool exists to catch.

### A false count in the file that calls itself frozen

SPEC §4's table had twenty rows under the sentence "All fourteen are live" —
six rules of drift in the document that defines the rule IDs. STATE.md's
detector count has been recomputed from the registry since 2026-08-04; the
SPEC's never was, so the weaker claim was the one being checked.
`test_spec_rule_table_covers_the_registry` and
`test_spec_rule_count_prose_matches_the_table` close that.

## D-044 (2026-08-13): the IR now records the assertions a test executes

The A5 round (#37, THREATMODEL 91). One modelling decision replaced, no new
rule added, and the rule set's *meaning* got smaller: `ASSERT_REMOVED` is now
literally "the reachable set shrank".

**What changed.** `_collect_unit` computes the unit's executed scopes — itself,
plus same-file functions, lambdas, classes and `@contextmanager`s it invokes,
through the file's call graph to depth 4. Assertions in an invoked helper join
the unit's set flagged `inherited`; assertions in a nested def nothing calls
leave it (that bug predates the attack that exposed it — `ast.walk` counted
them as live since M0). Two definitions carry everything, both corrected by
prototype rather than argument, both now docstrings in `frontend.py`:
*reaching means invocation, not mention*, and *construction is not invocation*.

**The slot rule.** `ASSERT_SUBSTITUTED` declines any fallback pair that crosses
the body boundary (`a.inherited != b.inherited`), in both directions —
extraction and inlining move the slot, not the assertion. The disguised-attack
arm is why this is safe to say: 25 of its 28 blocks come from the strength drop
(`ASSERT_WEAKENED`) that survives the decline untouched.

**Numbers, all four corpora at once** (score.py exists so they cannot be
reported separately): attacks 12/40 → 19/40, disguised arm 28/40 at first
contact, refactor FPs 20/30 → 17/30, extraction arm 16/30. Both sides of the
same blindness, moving together — which was the pre-registered acceptance
criterion, alongside the sweep threshold.

**The refused trade, in writing.** ~8 extraction FPs exist because the shared
assertion is lattice-weaker than the concrete asserts it replaced. The same
transition is the disguised arm's whole detection surface. Fixing those FPs
costs those catches; refused, and THREATMODEL 92 says so.

**Estimates corrected by measurement, third and fourth of the round:** the
prototype's "10 reachability escapes" was a miscount (three were
vacuous-subject edits — the assert stays, its subject becomes `for n in nums
if False` / `mismatches[:0]` / `pred` without the call — a separate family
with one clean syntactic signal: a called subject becoming a bare name). And a
double-count bug (an invoked *nested* def's assert collected once by the body
walk and again as inherited) was caught by a fixture pinning one finding and
getting two. Every number this project has published without a harness behind
it has been wrong; the sentence is now load-bearing.

**Sweep reconciliation.** 36 → 36 blocks, zero verdict movement, and one
sub-blocking delta, reconciled by A/B against a v0.1.25 worktree rather than
guessed at: click `1aa2d53d63ff`, where two TEST_DISABLED findings on a
relocated test changed de-escalator — `ASSERTION_MOVED` (info) became
`RESTRUCTURED` (warn) — because the moved unit calls a helper, its multiset
now carries the helper's inherited assertion text, and the destination file
has no such helper to match it. One commit in 1800, still de-escalated, and
the direction is toward more visible rather than less. The refinement (match
the move credit on own-body assertions only) is a follow-up, not a
pre-release patch to an already-measured build.

**Worker provenance.** Two of the four corpora were generated overnight by
cheap worker models from prompts that made their output mechanically
verifiable — production shipped twice, four pytest runs, no trust required.
One returned a generator script instead of files; the script was read before
anything ran, and its embedded cases were re-verified by this repo's own
harness rather than its own validator. The pattern held: quantity from the
workers, judgement and verification here.

## D-045 (2026-08-13): cross-file helpers — two channels, one falsified prediction, one corrected line

The A5-x round (v0.1.27), scoped deliberately small at the owner's request:
the corpora showed exactly two mechanisms, and only those two shipped.

**Import channel**: a unit-invoked name bound by top-level `from M import f`
where `M` is a same-directory test/conftest sibling — parsed straight from the
change bytes (memoised), so resolution cannot depend on the order the sweep
loop visits paths; head snapshot for out-of-diff helpers, capped reads.
**Fixture channel**: a fixture the unit requests by parameter name (same file
or same-dir conftest) contributes every assert lexically inside it; autouse
counts only from a conftest the diff touches (a head-only autouse would add
identical asserts to both sides — no rule could see a delta, every unit would
gain unearned oracle mass). A fixture nobody requests contributes nothing,
which is what newly blocks the drop-the-autouse attack (tamper 040).

**The falsified prediction, kept as falsified.** The pre-registration named
CASE_019 as going silent. The channel instead made its teardown assert visible
as what it is: `== "hello world"` become `"hello world" in calls`, membership
for equality — the lattice-weaker family THREATMODEL 92 keeps deliberately.
Five predictions held, one was corrected in the document that made it, and
`oracle_fixture_teardown_refused_trade.gwcase` pins the corrected behaviour.

**The line the disguised arm corrected.** An own container-literal comparison
extracted into a parametrised helper drops EXACT_STRUCT→EXACT_VALUE because a
parameter cannot be a literal. The first cut of the decline checked only the
strengths — and three disguised attacks walked through it, their helpers
comparing `sorted(got) == sorted(expected)` or via `set(...)`: same lattice
drop, same dependency set, and the transformation *is* the weakening. The
shipped decline requires the expectation to be the **bare parameter name**
(`Assertion.bare_expectation`); the wide version was reverted the same hour it
was measured. 13-FPs-for-3-attacks is the same trade shape as
8-for-25, and it was refused for the same reason.

**Ledger, fully explained**: tamper 47→**48**/80 (040 newly blocked, zero
regressions); refactor FPs 33→**25**/60 — the six named predictions, plus
EXT_007/020/028 whose fixture-returning-checker lives in the test file itself
(the same-file half of the fixture channel; unpredicted, mechanism verified
before being counted). Corpus judges now declare `app` as a known module —
the corpora ship `app.*` by construction, and the IMPORT_UNRESOLVED warns on
every new helper file were harness under-specification, not engine findings.

## D-046 (2026-08-19): depth-1 reachability is not evidence for a leaf name

*Maintainer-approved frozen-zone change (gating.py), applied by the audit
round, D-038 reference in the code comment corrected to this entry.*

**Incident.** The 2026-08-19 external audit reopened bypass #35 through the
fix that closed it. `_symbol_match` accepts a leaf-name hit when the changed
symbol's module is "reachable" from the test's imports — but
`_module_reachable` is alignment at depth ≥ 1, and a root-level import
(`from app import billing`, recorded as `"app"`) reaches **every** module in
the package at exactly depth 1. Measured with the real CLI: weaken the
assertion, edit a same-leaf-name function in a sibling module the test never
reads (`app/util.py::calculate` while the test exercises
`app.billing.calculate`), verdict **pass** with `REPAIR_EVIDENCE`. The
row-35 closure held only for imports deeper than the root.

**Frozen:** a leaf-name hit grants evidence only with (a) ≥2 aligned
components between the changed module and some import, or (b) a dotted call
in the unit whose first component **is** the changed module's leaf — the
honest root-import shape (`from app import billing; billing.calculate()`
over a real change to `app.billing::calculate`) keeps its credit through
(b). Full-qual matches and the `imports is None` fallback are unchanged.
`_module_alignment` is the shared implementation; `_module_reachable`
remains `>= 1` for every other consumer, so PACKAGE_REPAIR and the
src-layout fix are untouched — which also means the audit's X4 shape
(root import + any sibling symbol edit feeding `_package_evidence`) is
**unchanged by design**: it is structurally the httpx case PACKAGE_REPAIR
exists for, and closing it would re-block the 13 httpx commits the rule
was measured on. Filed as a THREATMODEL row instead.

**Cost accepted:** an aliased root import (`from app import billing as b;
b.calculate()`) loses clause (b) and reads as no evidence — visible at
warn, allowlistable. Priced below reopening the sibling hole. The same
audit's PACKAGE_REPAIR/X4 and fingerprint-rename residuals are stated as
THREATMODEL rows rather than half-fixed here.

**Verification:** fixtures `root_import_sibling_sameleaf_pos` (the attack
blocks at high) and `root_import_same_module_neg` (the honest shape keeps
REPAIR_EVIDENCE); the audit's original scratch repo flips pass → block;
arms/tamper/refactor corpora unchanged; dogfood clean.

## D-054 (2026-09-03): a created config that relaxes the defaults is a modification — issue #79

*Owner decision, option A of two; THREATMODEL row 100.*

D-030 made a **created** guardrail file warn instead of critical because
`checkwash hook install --agent claude-code` writes `.claude/settings.json`
and the tool was blocking its own installer's output. Its sentence — "a
constraint that did not exist has not been relaxed" — is true of a hook
file and false of checkwash's own `config.toml`: with no file the defaults
are in force, and a new file that disables a detector or raises `fail_on`
relaxes them. The owner reproduced the consequence on v0.2.11 in both
configuration directories: create the config with `[detectors] disable`
(warn, pass), weaken the test on the next diff (nothing). Because
configuration is read base-side, the planting commit is the only place the
plant can be caught, and at warn it never blocked under the default
`fail_on`. Same-commit plants were already blocked, which is why the
one-commit reproduction of issue #68 did not surface this.

Ruling: creation of `.checkwash/config.toml` / `.greenwash/config.toml` is
E4 like a modification **iff** the created content loosens the defaults —
any `detectors.disable` entry, or `gate.fail_on` above `high`. Everything
else keeps D-030: tightening-only or comment-only creations warn with
`GUARDRAIL_CREATED`; hook and instruction files warn; an unparseable created
config warns (defaults stay in force; the parse error surfaces on the next
diff). Implementation: `engine._created_config_loosens` reads the head-side
bytes through `load_config`; `DiffGlobals.guardrail_configs_created_loosening`
carries the verdict; the finding's message names what the file did. SPEC §4
carries the exception in the `GUARDRAIL_TOUCHED` row.

Option B — also rating `roles` overrides in a created config critical — was
declined: a role table can widen or narrow the test set and the tool cannot
tell a monorepo's first honest table from a narrowing one, so B would block
every adoption PR to close a shape nobody has demonstrated. It is recorded
as the open residual on row 100, next to the D-003 sibling (pre-seeding
`allow.toml` with the fingerprint of the weakening to come), which stays a
visible per-fingerprint `EXEMPTION_ADDED` because it is reviewable and
narrow where a `disable` is blanket.

Measured: three positive fixtures and one control, two end-to-end tests,
five predicate tests; no existing fixture expectation changed; the six-repo
sweep cannot move (no corpus repository carries either directory) and was
not re-run. Shipped in v0.2.12.

## D-053 (2026-09-02): corpora are tuning or held-out, and a rate says which — SPEC §10

*Owner instruction; the policy section itself is SPEC §10.*

The README had said the 1800-commit corpus was "none seen during
development". It was unseen exactly once — the first measurement
(8.56%, 2026-07-30) — and had been re-run after every precision round
since, with the blocked diffs read and rules shaped on them; 23 of the 42
rule ids postdate that first sweep. Nothing in SPEC, THREATMODEL or this
log had defined the difference between a corpus the detectors were tuned on
and one nobody had read, and each out-of-sample set so far (2026-08-07,
2026-09-01) was consumed into a fix round after one use.

Ruling, as SPEC §10: in-sample is a property of the repository and is
permanent once any window was swept in a precision round, any blocked diff
read, or any finding triaged; held-out is never swept and never read;
adjudicating or reading spends a set, publishing a raw block rate does not.
Every published rate carries its class and engine version (held-out also
its draw date); held-out sets are drawn and recorded in `checkwash-corpus`
before any engine runs on them; one measurement, then adjudication spends
them; a held-out number belongs to its engine version and goes stale when
detector logic changes (pins, renames and docs do not stale it); the
prediction — "worse than in-sample" is the prior — is written before the
sweep; the labels are pinned by tests and an untraceable number is removed.
Transition stated in §10.3: no held-out number exists for the current
engine, the two earlier figures are stale and spent, and the README and
STATE labels plus their tests land with the first draw.

Wording fixed the same day in README (#66) and the archived launch notes
(#67). Not done yet: the first draw, and the label tests.

## D-052 (2026-09-02): supply-chain weakening declined as scope creep — issue #54

*Maintainer-delegated scope ruling (THREATMODEL row 96).*

The 2026-09-01 field run surfaced sqlalchemy `7776cfbf`: attestation signing
made `continue-on-error` with a silent unattested-publish fallback. Same
*shape* as the tool's thesis — a verification step quietly unenforced — but
ruled out of scope (decision delegated by the maintainer, recorded on issue
#54), on three structural grounds: (1) a different threat model — nothing
about the correctness of the code under test is hidden; (2) no mechanical
adjudication exists — "tampering or legitimate resilience policy" is a
per-project judgement, and the motivating commit itself adjudicates as a
deliberate, correct maintainer choice, so the family's false positives would
be matters of opinion, dissolving the measured-not-asserted contract; (3) FP
cost would land in the CI family that holds a no-change verdict across 2,300
field-run commits. Proper owners: SLSA / sigstore / GitHub artifact
attestations / zizmor. Behaviour unchanged: `CI_WORKFLOW_TOUCHED` still warns
on the edit. Separately noted, opposite direction: that warn's message ("test
command weakened") anchored to a non-test step is off-thesis wording —
narrowing the anchor to the test-running command is a candidate precision
round, not a family.

## D-051 (2026-08-26): module constants become the fourth expectation source

*Maintainer-directed frozen-zone change (SPEC.md §4 row, detector source arm, IR fields).*

**Incident.** The 2026-08-25 census put 29.2% of the corpus's named
expectations (445/1526) in module-level constants — the largest single blind
bucket — and the probe confirmed total blindness: `EXPECTED_TOTAL = 105.0` →
`100.0` at module scope, assertion byte-identical, verdict pass, zero
findings from all 21 rules.

**Frozen:** `EXPECTATION_DEFINITION_CHANGED` reads a fourth source — the
file's own top-level constants, carried on
`FileIR.module_constants`/`module_constants_before`, canonicalized with
`ast.unparse` on both sides (the raw-segment comparison would relive the
binding channel's first false positive), last-wins per side (module
execution order — an appended `EXPECTED = evil` at the bottom of the file is
caught with none of the unit channel's branch machinery), consumed-by-the-
expectation only, subject-closure excluded (T1.10). The merged D6
environment is explicitly NOT the comparison input: it resolves cross-file
with a head reader on one side only, and an asymmetric environment must
never feed a two-sided comparison. Pre-registered gate held on every line:
sweep 41→42, gone zero, the one new block (click `5989375dc3`) adjudicated
false — the compensation is visible in the reviewed diff, the tool cannot
connect an import-audit test that calls no production symbol, the
`1c5e03eb32` failed-connection family — inside the five-of-1800 budget;
tamper 48/80 and refactor 25/60 case-for-case unmoved, and these single-diff
arms genuinely exercise the arm, unlike the refused prior-window channel.
Stated residuals, each its own round if ever taken: imported constants,
conftest constants, constants moved under a top-level `if` (row 95's
module-scope cousin). Weakening the canonicalization, the consumed filter,
or the subject-closure exclusion reverts this decision.

## D-050 (2026-08-26): the prior-window pardon is refused — the two-commit split stays open

*Maintainer-approved refusal; no frozen text changes, the source tree reverts to v0.1.45.*

**Incident.** The promotion round's second residual — production lands first,
the test golden catches up test-only, in-diff repair evidence rightly finds
nothing (`823de916d9`, adjudicated false) — got its obvious fix built and
measured behind a pre-registered gate: a `REPAIR_EVIDENCE_PRIOR`
de-escalator fed by the five first-parent commits before the analyzed diff,
with every conservative clause the in-diff channel has and three more. The
gate was P1–P4 all hold or no ship. P4 (zero unpredicted movement) broke:
the sweep removed a second, unpredicted block (`7022e202245b`), because on
merge-flow history "five commits" is five first-parent steps — measured at
19 commits average on click, 57 max — and that window carried whole merged
pull requests whose combined diff reached `rich/progress.py`, which
`test_columns` calls directly.

**Decided:** the channel is refused, not repaired. Three structural reasons
beyond the breach, each measured or constructive: the window's stated
exposure was off by an order of magnitude on the corpus it was tuned
against; a prior credit is never spent, so one stranger's repaired change
keeps pardoning subsequent edits to the same expectation for the rest of
the window — a shape the in-diff purchase cannot produce, since it forces
the attacker to author the artifact in the reviewed diff; and the pardon
removes the explaining artifact from the reviewer's view entirely. The
repairs exist (per-commit non-merge enumeration, unit-level spent credit,
sha-bearing messages) and were declined together: they make the pardon
channel more machinery than some detectors, in the trust path, to buy back
two adjudicated-false blocks of 1800 that are already published as the
promotion's price. Same refusal shape as THREATMODEL 92. Re-attempting a
cross-commit pardon requires a new decision superseding this one, and its
pre-registration must state window semantics in *commits reachable*, not
first-parent steps.

## D-049 (2026-08-26): the gated-alternative guard — additions are not edits, in both channels

*Maintainer-directed frozen-zone change (SPEC.md §4 row, detector guard, IR field).*

**Incident.** rich `c8abbb3bd2` ("Fix test for Python 3.13") wrapped a golden
in `if sys.version_info >= (3, 13):` and kept the old string verbatim in the
`else`. Both raters judged the block false: nothing was replaced, the
pre-3.13 comparison stayed byte-for-byte, an alternative was *added*. The
parametrize channel has excluded exactly this event class since it shipped
(`_column_values_edited`: "Only a same-length column with different cells is
an expectation edit"); the binding channel was a bare `!=` — the identical
event excluded in one channel and reported in the other.

**Frozen:** the binding channel spares a changed key only when three clauses
hold at once — the after side has more definitions; every before-side
definition survives verbatim (multiset containment, because
`_binding_definitions` walks breadth-first and order is not a contract); and
the name's bindings are pairwise branch-exclusive (`if`/`match` arms),
recorded by the frontend on `UnitSide.exclusive_bindings`. The third clause
is the correction the port demands: parametrize rows are parallel items,
bindings are sequential rebinds where the last one reaches the assertion, so
a same-length guard alone would have silenced `expected = honest` followed
by `expected = evil` — which fires today and is pinned to keep firing
(`expectation_definition_sequential_rebind_pos`). Each clause is pinned by
the fixture its own mutation turns red; the mirror arm order has its own
fixture so the guard is not fitted to the one observed spelling. The
residual is structural honesty's price: the guard reads branch structure,
not branch truth, and the tautological gate that walks through it is
THREATMODEL row 95, open by design. Weakening any clause, or widening the
exclusion beyond `if`/`match` arms, reverts this decision.

## D-048 (2026-08-25): #86a promoted — EXPECTATION_DEFINITION_CHANGED joins ORACLE_RULES

*Maintainer-approved frozen-zone change (gating.py ORACLE_RULES, SPEC.md §4 row, detector base severity).*

**Incident.** Issue #36 held promotion until the §A1 line (≤ 5 new blocks
judged false on the 1800-commit sweep) was met. The round that met it also
found the ledger's promotion premise was stale twice over: STATE's recorded
"+4" was measured by drivers hard-coded (`sys.path.insert`) onto a
**v0.1.42 clone eighteen commits behind the shipping tree** — on v0.1.43 the
true cost is **+5** (37→42, all rich, gone 0), the fifth block appearing
because A6 correctly stopped a blank-line `pyproject.toml` edit from buying
`DEPENDENCY_DRIFT`. And "promotion is a one-line `ORACLE_RULES` add" was
false: the detector was the tree's only sub-`warn` emitter (`info`), so a
credited finding would have sat below every peer and below `fail_on="warn"`,
silently contradicting SPEC §4's "base severity of every finding is `warn`"
and D-002; and the non-oracle credit branch in gating carried a comment
promising the rule "stays info and outside ORACLE_RULES" — unreachable the
moment it joined. All five new blocks were adjudicated (two blind raters
each, 1–1 splits reconciled, dissents preserved:
`benchmarks/adjudication-2026-08-25.json`): **five false, zero defensible**.
With exactly five new blocks the ≤ 5 line cannot arithmetically fail, so it
is reported as evidence, not as a gate that discriminated; the incremental
precision of the promotion on honest history is 0/5 and is published as the
price.

**Frozen:** `EXPECTATION_DEFINITION_CHANGED` is in `ORACLE_RULES`, base
severity `warn`, escalating and de-escalating exactly as its peer oracle
rules; membership of `ORACLE_RULES` is machine-pinned by
`tests/test_oracle_rules_pinned.py` (every member exists in REGISTRY, no §4
row of a member may claim it cannot gate, and the membership itself is
frozen in the test). The eleven re-pinned fixtures carry the promotion
(seven at high with `NO_PROD_CHANGE_IN_DIFF`, four negs at warn with their
credits — `expectation_definition_repaired_neg` now pins its
`REPAIR_EVIDENCE`, without which the mutation check passes on a broken
promotion). THREATMODEL 86a is **Partly closed**: the residuals (55.5%
visible surface, module constants 29.2% blind, one-token assertion-line
evasions, closure poisoning, alpha/unit renames, purchasable repair) are in
the row, each reproduced against the promoted build on 2026-08-25.
Un-promoting, re-basing the detector below `warn`, or shipping an
`ORACLE_RULES` edit without its fixture-and-ledger round reverts this
decision.

## D-047 (2026-08-19): D7's frozen text said PATTERN; the code, the fixtures and row 13 said EXACT_VALUE

*Maintainer-approved frozen-zone change (SPEC.md §5).*

**Incident.** The 2026-08-19 external audit found the frozen SPEC table row
D7 ("landed ≥ PATTERN") contradicting the implementation
(`gating.py: strength_after >= 90`), the four pinning fixtures
(`mild_weaken_neg`, `mild_weaken_reformat_neg`, `mild_weaken_subject_changed_pos`,
`row13_exact_to_approx_pos`) and THREATMODEL row 13 ("landing on APPROX is
never mild") — three artefacts against one line of text, and the text was
the odd one out. The window of disagreement is exactly the drop-<30
transitions that land at 60–89 (70→60 in neither row 13 nor the code).

**Frozen:** the SPEC text now states the implemented and pinned behaviour —
mild means "still inside the exact family" (≥ EXACT_VALUE). Relaxing the
code to the old text was rejected: it contradicts row 13's measured design
and would hold APPROX→PATTERN slides at warn. The code's own stale comment
("or landed below PATTERN") was corrected in the same round. No behaviour
changed; `projD`-shape 70→60 transitions block as before.

**Verification:** all four D7 fixtures green unchanged; full suite and
corpus gates unchanged; dogfood clean.

## D-055 (2026-09-06): content-bound exemptions — next minor candidate

The owner approved the remediation plan and then authorized merging its
implementation and delivered contract patch on 2026-09-06. The named-defect
commits and local/CI evidence remain individually reviewable. This records
the owner's merge authorization, not a release or a separate independent
human review of fixture labels.

The per-fingerprint promise was broader than it sounded: five file-wide
rules used only rule and path as identity. A typo approval could also waive
removal of an AGENTS constraint, and a Python-version approval could waive
continue-on-error. Follow-up controls confirmed parser, scope, and strict-warn
snapshot variants. The real AGENTS rename-residue entry was also reused on
later policy content; its cleanup is separately reviewed.

Use validated before AND after digests plus path/status/role/rename metadata
and the rule's relevant structured context, canonical JSON and complete SHA256.
Before-only hashing still conflates two different edits from the same base.
Whitespace compression is inappropriate for arbitrary policy/workflow text,
so only CRLF is normalized. Version this identity as v2; retire known legacy
namespaces without removing their parsed records. Keep unaffected identities,
expiry, fail-on, severity, strength/alignment, and base-side policy unchanged.
The old record cannot be automatically migrated because its reason does not
preserve the reviewed content. Missing required evidence fails as an engine
error; direct IR consumers and the full pipeline share the same identity.

This breaks a frozen fingerprint contract and adds required evidence for these
rules: IR_VERSION and FINDINGS_VERSION move to 2, retaining the checkwash_*
keys. Ship only in a new minor release (0.3.0 proposed), under the existing
weekly slot and tag-parity procedure. Do not waive the release gate to make a
candidate green. Under the one-release Action trust lag, fixed CLI artifacts
and promotion of their verified Action SHA are separate completion points.

Validation must preserve per-commit before/after controls, parser/scope/prod
context controls, legacy base-side rejection, append-only ledger evidence,
ordinary expiry behavior, package/zipapp installs, and pinned corpus comparison.
Historical benchmark records are not overwritten. Exact counts and runtime
qualification belong in the execution receipts, not an unmeasured prediction.

Cleanup does not get a new escape hatch. A same-ledger approval changes the
very content it would approve; maintainers must review the exact tightening
diff through their existing governance route. Removing the legacy entry from
head does not clean old bases, and rolling back to an old engine can reactivate
its broad key. Prefer a forward fix or a previously qualified fixed release.

## D-056 (2026-09-07): v0.3.0 shipped, measured after release, and the maintainer pass written by the operator under authorization

The next-minor candidate of D-055 was released as v0.3.0 on 2026-09-07 (tag
`4387097`, PyPI 0.3.0, Release assets; estate T-197). The owner froze the line
after the release — no bump, tag or release without a new decision — and
cancelled the weekly slot. The recommended Action pin stays v0.2.13 under the
one-release trust lag.

Two things were measured after release rather than promised, both on the
estate runner pool from clean checkouts and never on a work machine:

- The six-repository sweep was re-run on the release commit (RELEASING: a
  round that changed detector behaviour must re-sweep). 46 of 1800 blocked,
  gone 0, new 4, all adjudicated false in a maintainer single pass
  (`benchmarks/adjudication-2026-09-07.json`). click 61bdc2ae81 is the price
  of #135's row-keyed comparison and was accepted as such on 2026-09-07
  rather than reverting #135 or adding a credit for the shape (estate
  T-171); click c498ced0e7, flask 0a00e1b608 and httpx 7985f685ca are
  `EXPECTED_VALUE_CHANGED` call-shape rewrites the reference arm had blocked
  since v0.2.12 that nobody had adjudicated because the tracked record stayed
  at v0.1.46. The floor moved 1.50% → 1.72%; `make_results.py` and
  `make_failures.py` now read the engine-version key the sweep has written
  since the v0.2.0 rename (`corpus.checkwash_version`), falling back to the
  old one.
- The LLM-arm record `llm-2026-09-03` (178 families) was re-judged through
  the zipapp's CLI on a real two-commit repository per family, not
  in-process: the corpus harness's in-process judge fails its own calibration
  on v0.3.0 because it lacks the strict-snapshot wiring the product adapters
  use (checkwash-corpus #15), so its verdicts are not the user path on this
  line. 79 of 88 escape families still pass (9 newly blocked, all at high)
  and 65 of 90 honest families still block (25 now pass); on v0.2.13,
  in-process, 85 of 88 and 90 of 90 (#132, #130).

The maintainer pass for the round — THREATMODEL row 101 closed and pinned
end-to-end, rows 102 and 102a added (skip-marked rows by identity; the
deleted-plus-appended residual left open by design), the 86a cost sentence,
the remediation section's release status and measured effect, the
false-positive table's #130 entry, SPEC §2b's delegation source and §4's two
rule rows, the STATE narrative, and this entry — was written by the operator
on 2026-09-07 under the owner's explicit authorization; these files are
otherwise the maintainer's alone. Every number in it comes from a receipt
named above, and the owner reviews the wording as any other change.

Recorded here because the release found it: the cross-interpreter
byte-compare gate failed on Python 3.13 the first time it ran on the
candidate (`ast.dump` omits empty fields there), and `stable_dump` now pins
the pre-3.13 text in both places that digested it, so keys computed on 3.11
and 3.12 are unchanged and 3.13 agrees with them.

## D-057 (2026-09-07): v0.3.1 — a documentation and metadata release so PyPI reads what the repository says

The owner unfroze the line for one release and asked for it to be frozen
again once the process had been checked ("解凍 然後都確認沒流程沒問題就再凍結").
The reason is mechanical: PyPI renders the README at the tag, and v0.3.0's tag
predates the tracked sweep record (#141), the maintainer pass (#142) and the
guide-link change (#139), so the project page still showed 42/1800, 27 false
positives, engine v0.1.46, 24 of 60 and the v0.2.13 guide. A version number
cannot be re-uploaded, so the fix is a release whose only content change is
the documentation.

What v0.3.1 contains: the version strings, the README install pins and pyz
links, the one-release trust lag (the recommended Action pin advances from
v0.2.13 to v0.3.0 — the Action now carries the v0.3.0 detector changes, which
the README says), the STATE section for the slot, and this entry. No file
under `src/checkwash/` changed except the version string and the doctor's
expected Action pin constant; no detector logic changed.

RELEASING says a round that changed only documentation must name the targeted
checks that stood in for the corpus sweep. They are: the full suite gate on
the release commit run by `release_slot.py` on LAPTOP-01AGNPJU;
`tests/test_state_claims.py`, `tests/test_docs_links.py` and
`tests/test_packaging.py` (README install pins, tag parity, the documented
Action snippet) on the patched release commit; and the release PR's CI,
including the byte-compare job across the nine OS/Python legs. The sweep
record of 2026-09-07 (run 34121457167) describes this engine exactly.

Cut by `release_slot.py slot --force-release` on LAPTOP-01AGNPJU — a work
machine, which the owner's rule allows for releases — after LAPTOP-16NUA5I8,
the designated release host, went offline; pushes went over SSH because the
host's `gh` token lacks the `workflow` scope the trust-lag edit of
`.github/workflows/checkwash.yml` needs over HTTPS. The line is frozen again
after this release: no bump, tag or release without a new owner decision.

## D-058 (2026-09-07): v0.3.2 — a second documentation and metadata release so PyPI carries the corrected current-state sentences

The owner unfroze the line once more ("解凍", 2026-09-07) after a pre-launch
read of the public pages found sentences that contradicted each other on the
same page: README line 80 still said 24 blocks out of 60 while line 181 said
22/60, and `docs/stability.md`, `docs/enterprise.md` and four family pages
still named v0.2.13 as the release or as the recommended Action pin. PR #146
fixed the repository (issue #140 tracks the runtime record separately). The
PyPI description of 0.3.1 is the README at tag v0.3.1 and cannot be replaced,
so a release is again the only way to make the project page read what the
repository says. D-057 applies unchanged: same reason, same shape.

What v0.3.2 contains: the version strings, the README install pins and pyz
links, the one-release trust lag (the recommended Action pin advances from
v0.3.0 to v0.3.1 — the same v0.3.0 engine, because v0.3.1 changed no
detector), the STATE section for the slot, the v0.3.2 wording of the
current-state sentences PR #146 touched, and this entry. No file under
`src/checkwash/` changed except the version string and the doctor's expected
Action pin constant; no detector logic changed.

The checks that stood in for the corpus sweep (RELEASING): the full suite
gate on the release commit run by `release_slot.py` on LAPTOP-01AGNPJU;
`tests/test_state_claims.py`, `tests/test_docs_links.py`,
`tests/test_documentation_contracts.py` and `tests/test_packaging.py` on the
patched release commit; and the release PR's CI, including the byte-compare
job across the nine OS/Python legs. The sweep record of 2026-09-07 (run
34121457167) describes this engine exactly.

Cut by `release_slot.py slot --force-release` on LAPTOP-01AGNPJU as in
D-057. The line is frozen again after this release: no bump, tag or release
without a new owner decision.

## D-059 (2026-09-12): bounded family remediation, unreleased

The owner requested an EC-first audit and then asked to fix the confirmed
family defects. EC T-326 records that task; its task-local contract grant
permits only the corresponding SPEC/THREATMODEL clauses and regression
expectations that explicitly pinned those defects. No release or merge is
part of this grant.

The count-only vanished/arrived row residual gains a separate answer-change
owner, while the existing row-keyed comparison and input-only controls stay
intact. Literal table projection accepts additional source-proved carriers
and inert module context instead of relaxing the ordinary restructure gate.
Whole-file literal constant renames receive a narrow AST proof; CI collection
settings are compared by literal values as well as newly added tokens.
Runtime providers and assignment/setattr installations must identify a
first-party target consumed by an existing oracle, with before/after timing
and complete source inventory where discovery requires it.

The first full candidate sweep exposed three new false-positive blocks.
Unchanged ordinary assertions now retain their native expectation owner;
the additive provenance pass is reserved for an assertion helper, literal
loop or changed assertion structure. Parameter input evidence additionally
tracks an unchanged produced function's evaluated decorator inputs and
literal input/answer-copy row rewrites with concrete multiplicity. These are
syntactic input-role checks, not a claim of arbitrary callee dependence or
preserved concrete coverage. Surviving-input answer changes remain with the
original row-keyed rule. The detailed limits and no-op-callee residual are in
[the input-role contract](docs/param-input-roles.md).

The detailed candidate boundaries are in
[the remediation notes](docs/family-remediation-2026-09-12.md). Earlier
decisions and measurements remain historical evidence. This entry claims
neither a new measured catch rate nor a release; the review PR records actual
validation outcomes and any remaining failures.

## D-060 (2026-09-21): issue #93 contract — input laundering is an oracle event, unreleased

The owner was asked to resolve the observed issue set, and issue #93 needed a
contract decision before any code: three frozen fixtures pinned "an edited
input is an honest change that must stay silent" (`[]` expectations), and the
issue's live evidence showed the same shape used to stop exercising a frozen
bug. Presented with the review doc's options, the maintainer adopted the
bounded `SUBJECT_INPUT_CHANGED` predicate and the reclassification of all
three frozen expectations in the same decision (estate T-436).

The predicate is deliberately narrower than the issue's request. It fires
only when the assertion's oracle is untouched (form, strength, polarity,
tolerance and the expected side all unchanged), the subject is a plain call
with the structurally same callee and a provider defined identically on both
sides, and every changed argument resolves to a concrete literal on both
sides — directly, or through the straight-line local binding / module
constant the assertion reads (`reaching` first). A literal `parametrize`
spelling pairs a vanished live row with an arriving one that keeps the
consumed answer beside different input cells, and only when the vanished
input does not survive with a different answer, which remains
EXPECTATION_DEFINITION_CHANGED's row-keyed event. What stays silent is the
point of the bound: a rename resolving to the same value (#87's control), a
computed argument, a changed callable or provider, a new test, a shared
producer the expectation also reads (T1.10's principle carried to the input
side — changing it moves both sides of the comparison, so it explains
itself), a row reorder and a pure row addition.

The three reclassified fixtures keep their original job: each still proves
its own rule (EXPECTATION_DEFINITION_CHANGED twice, SUBJECT_NORMALIZED once)
does *not* fire on the shape, while the expectation list now names
SUBJECT_INPUT_CHANGED. THREATMODEL row 103 records the family and its
residuals; row 102a's "unresolved by design" clause is updated to match.

No sweep cost is claimed in this entry. The rule escalates through repair
evidence like every oracle rule, and the corpus replay on the runner pool
decides whether the bound holds; if it adds more than a handful of blocks on
honest history, the visible-but-non-blocking demotion path of D-048 is the
pre-registered answer, not a widening of the predicate.

## D-061 (2026-09-21): issues #85 and #88's import sibling — spelling rounds on rows 60 and 90, unreleased

Two of the seventeen scoped issues were not new families but new spellings of
acts rows 60 and 90 were already Closed against, filed from smallestlie wave
M6 attack catalogs. Both are repaired in the T-436 candidate, and both
repairs are bounds on an existing contract rather than a new one.

Issue #85 (CW-M6-FABLE-04) spelled the row-60 stand-in with the builtin:
`setattr(request.module, "invoice_total", reference_total)` behind a
`if original is not None:` guard. The execution-proof installation trace
only enters statically selected branches, so the guard hid the install; the
unconditional spelling was already caught as a side effect of the #91
repairs. The conftest presence scan — which reports patch API calls in
unknown branches by design — now recognizes the unshadowed builtin
`setattr`, the attribute store `request.module.x = v`, the dictionary store
`vars(request.module)["x"] = v`, and `monkeypatch.setitem(vars(...))`, all
bounded to `request.module`. The boundary is capture timing: writing the
test module's own namespace rewrites what a live assertion reads at call
time, while writing a first-party module object cannot rewrite a from-import
the consumer already captured — that act stays with the trace's execution
proof, pinned by `test_attribute_fixture_does_not_rewrite_a_captured_from_import`.
A `getattr`-captured save/restore pair reports one finding, not two, and a
module- or function-local rebinding of `setattr`/`vars`/`getattr` turns the
native reading off. Mutating an object the test owns remains configuration.

The #88 sibling (CW-M6-FABLE-05) spelled the row-90 stand-in as an import:
`from app.reference import reference_total as invoice_total`, leaving every
assertion byte-identical. The trace now treats an import that rebinds a
captured name to a different provider as an installation at import time,
with two ownership bounds: both endpoints must be repository-owned, and the
old provider must still exist after the diff — following a deleted module's
rename is what honest production moves look like, and a same-provider
re-alias is the family's rename control. `import X as Y` swaps get the
symmetric reading.

THREATMODEL rows 60 and 90 record the spelling rounds; SPEC §4 trigger text
names the same bounds. Each shape carries pos/neg `.gwcase` fixtures, and
the corpus replay on the runner pool decides whether the bounds hold.

## D-062 (2026-09-21): issue #130 consolidation round — Boolean identity/equality pairing, unreleased

The consolidation projection (row 92) refused to pair `assert f(x) is True`
with the same oracle restated as a literal table row's `== expected`, so an
honest parametrize/fixture/loop consolidation read as `TEST_DISABLED`/high.
The same spelling change in place is silent: the frozen lattice rates
`is True` and `== True` identically (compare_eq, EXACT_VALUE). A projection
stricter than the ordinary path punishes the carrier, not the act.

`pair_boolean_comparisons` now pairs identity and equality spellings on the
same Boolean constant in both directions, behind the existing closed
Boolean-result proof; `_boolean` additionally admits the `startswith`/`isdigit`
calls the closed-module grammar already allows, since those receivers are
str-derived or raise. Bounds, each chosen for consistency with the ordinary
path rather than convenience: None expectations are not paired (the ordinary
path owns `is None` → `== None` as `EXPECTED_VALUE_CHANGED`), non-Boolean
identity spellings are not paired (interning makes `is` on str/bytes an
unreliable oracle to begin with), and a value flip inside a paired row stays
`EXPECTED_VALUE_CHANGED`.

Re-judge of the 90-case LLM honest-refactor folder (`checkwash-corpus`
records/stress/llm-2026-09-03/false_positives) on this candidate: 77 pass.
Of the 13 still blocking, 7 are adjudicated true blocks this row refuses to
trade (dropped exact assertions 049/061, oracle loss 028, fixture-assertion
removal 051, lattice weakening 055, derived oracles 077/084) and 6 sit on
documented carrier boundaries (raise-style 034, nested closure parametrize
044, cross-fixture derived arithmetic 064, recursive reimplementation 065,
None-row consolidations 047/080). THREATMODEL row 92 records the round;
`tests/test_identity_comparison_pairs.py` pins both directions.

The same commit repairs CI drift left by the #93 landing: the
input-only-change contract test now names `SUBJECT_INPUT_CHANGED` as owner,
the three subject-input fixtures carry `bypass: 103`, and the documented
detector/test counts, STATE table and `benchmarks/FAILURES.md` are
regenerated to the registry.

## D-063 (2026-10-01): v0.5.0 — fingerprint changes from the #172–#181 round

The fixes in PRs #183–#191 keep the finding and IR JSON shapes, rule IDs,
the severity model and exit codes, but change the fingerprint of some
existing findings: `CI_WORKFLOW_TOUCHED` (#173, #174, #181), `TEST_DISABLED`
on JS/TS units now read as disabled rather than removed and on deleted
chai-only units (#176, #178, #180), and `SCOPE_DRIFT` /
`SNAPSHOT_CODE_COCHANGE` where a file's role changed (#174, #175).
Fingerprints are a frozen contract, so the release is minor: v0.5.0, chosen
by the maintainer. Allowlist entries recorded on v0.4.2 for these shapes
must be re-recorded; the release guide lists them. The fixed 1,800-commit
sweep matches v0.4.2 in blocked commits, blocking findings and per-rule
counts; it records no fingerprints.

## D-064 (2026-10-02): previous-release verdict gate — first acceptance list

#201 adds a hosted gate (`.github/workflows/verdict-gate.yml`,
`tools/verdict_gate.py`) that runs the previous release and the candidate
through the CLI on the same cases and fails on any block -> pass that
`tests/gates/verdict_gate_accepted.toml` does not accept. The maintainer
ruled #201's four defaults on 2026-10-02: the acceptance file lives in
`tests/gates` and is maintainer-edited, rows awaiting a ruling are
`undecided`, the gate is advisory on pull requests and required at release
time, and the bootstrap runs are authorized.

The first acceptance list holds 44 `known-regression` entries: every case
labelled `block` that v0.5.0 passes, each tied to its open family issue
(#197, #198, #199). It accepts known regressions until their fixes land;
it accepts nothing new. The first hosted run (36983670433, PR #203) also
pinned 73 baseline blocks and a 67-case v0.4.2 -> v0.5.0 canary. The
in-process matrices had 68: #197 B7's rename-with-edit is a delete plus an
add to git, and deleting a test under `.github/workflows/` blocks.

The maintainer was away. The agent wrote this entry and the acceptance file
under his delegation of 2026-10-02 ("完全開放授權 但只限於checkwash相關").
Later the same day, given the full list of entries and of the label calls,
the maintainer accepted the agent's recommendations ("照你建議走"). That was
an acceptance, not a line-by-line review, so a later review may still revise
an entry or a label.

## D-065 (2026-10-02): next release — the recommended Action advances to v0.5.0

At the next release, the recommended Action follows the one-release trust lag
and advances to v0.5.0. It is not held at v0.4.2. The v0.5.0 engine carries
the block -> pass regressions filed as #197, #198 and #199, but v0.4.2 still
has the silent bypasses that v0.5.0 closed (#172 and #174-#179), and the
#197 family needs a layout or a visibly odd shebang. Python-only users only
gain. That release's guide must name #197, #198 and #199 as known
regressions of the Action's pinned engine, beside the fixes the Action does
not have yet. The agent recommended this on 2026-10-02 and the maintainer
accepted it ("照你建議走"). It is a judgement, not a measurement: neither
version has a JS/TS history replay.

## D-066 (2026-10-02): a suite control's escalator is a fact about the diff (#205)

A blocking `TEST_DISABLED` on a conftest `<suite>` control printed
`NO_PROD_CHANGE_IN_DIFF` over a diff that changed production (#199 row P5).
D-028 attached `COLLECTION_CONTROL_UNEXPLAINED` only where repair evidence
exists and is deliberately refused. A `<suite>` unit calls nothing, so for it
that reduced to the opaque blanket: a readable production edit elsewhere in
the diff gave it no evidence, and the false sentence D-028 removed came back.

An unguarded suite-level control never earns repair evidence (D-028), so
whether evidence exists says nothing about it. What the reader needs is
whether the diff changed production. A blocking unguarded suite control now
carries `COLLECTION_CONTROL_UNEXPLAINED` when the diff changes any
production-role file, and `NO_PROD_CHANGE_IN_DIFF` only when it changes none.
Generated artifacts are dropped before role bookkeeping and are not
production-role changes. This wider test was chosen over #205's suggested
`prod_symbols_changed`/`prod_opaque_change`: a comment-only edit, a deleted
data file, a rename or a production file that stops parsing is still a
production change, and the narrower test would print the false sentence over
those too. Severity, verdict, de-escalators and fingerprints do not move; only
the reason string does.

For suite controls this departs from SPEC §5's E1 condition ("no repair
evidence"), so SPEC §4 and the E1 row now say so. Unit-level findings keep E1
as SPEC defines it. Their wording (THREATMODEL 86h, `docs/integrations.md` §6)
is not decided here, so one report can carry both labels.

The agent proposed this in #207 and named both departures. The maintainer
accepted it on 2026-10-02 and asked for the documents to follow the code
("照建議 文件跟 code同步"); the agent wrote this entry and the SPEC text under
that instruction.

## D-067 (2026-10-03): IR_VERSION stays 2 for the additive JS fields (X.ir-policy)

The 2026-10-03 rulings add optional IR fields and correct one JS value:
`FileIR.test_obligations` (#197, 197.Q3), Assertion `predicate` and
`operand_source` (#198), and JS `positive`, restored to the meaning
`ir/model.py` documents (#198). The maintainer ruled them one question
(X.ir-policy): all of them keep IR_VERSION 2. A new optional field with a
default is additive (docs/stability.md, "When the number moves"), and the JS
`positive` correction restores the documented meaning instead of changing it.
`tests/test_fingerprint_scope.py` keeps pinning IR_VERSION 2.

What a consumer sees: `--emit-ir` output gains `test_obligations` on every
FileIR now, and `predicate` and `operand_source` on every Assertion after the
#198 round. The v0.5.0 release guide's "IR JSON shapes … are unchanged"
(docs/releases/v0.5.0-public-launch.md:70) stays true for v0.5.0 only; the
next release guide carries one line naming these keys. 199.Q4 declines a
Marker `kind` field because marker names are already frozen identity, not
because new fields are forbidden.

`test_obligations` (197.Q3): a JS/TS test path whose role SPEC §2 resolves
before `test` keeps its published role, so no fingerprint that includes the
role moves, and every test rule reads the file through one helper,
`judged_as_test`. A pin test forbids a raw `role == "test"` comparison
outside that helper.

The agent wrote this entry in the #197 dual-obligation PR, as the rulings'
X.doc-batch asks; the maintainer approves it there.

## D-068 (2026-10-03): only collection controls withhold the collection inventory (#199)

The resolved collection inventory (#173) withheld its proof when any head
conftest carried any marker on its `<suite>` unit. v0.5.0 mints one for every
conftest fixture whose setup always ends in skip or xfail. One such fixture
anywhere in the tree, requested or not, therefore turned a narrowing that only
the inventory reports from block into warn (#199 M1-M8). Two runtime hooks
already withheld it before v0.5.0 (#199 H1, R1).

Rulings 199.Q1 and 199.Q2: only the collection controls of SPEC §2b withhold,
with `pytest_plugins` and a conftest that does not parse. These are
`collect_ignore`/`collect_ignore_glob`, the `pytest_ignore_collect` and
`pytest_collection_modifyitems` hooks, `add_marker(...skip)` and a
`pytestmark` mark. No runtime control withholds, whether a fixture or an
execution or report hook. The test is still collected, and the control is
reported where it is planted (TEST_DISABLED high at `<suite>`). M1-M8, H1 and
R1 now block. K1 (`collect_ignore`) still passes at warn.

199.Q4: one predicate over marker names tells the kinds apart, in
`frontends/python/conftest_controls.py`. The inventory and TEST_DISABLED both
read it; there is no `kind` field on Marker. A name it does not classify
joins no reader, and `tests/test_conftest_controls.py` lists every place the
Python frontend mints one. Neither the IR nor any fingerprint changes.
TEST_DISABLED's `shape` still calls every conftest suite control
`collection_control`, runtime ones included. Relabelling them would change
what the findings JSON means, and needs its own entry.

Cost: a tightening against both tags for repositories whose conftest carries a
runtime hook, guarded makereport or rerun handlers included. Its size is not
measured. The fixed Python sweep must measure it before the next release. If
it shows real false positives in repositories that carry hooks, the ruling
falls back to 199.Q1 (b): only fixture markers stop withholding, which still
restores M1-M8. 199.Q3 is not done: a collection control anywhere in the tree
still withholds for the whole repository.

The agent wrote this entry in the #199 fix PR, as the rulings' X.doc-batch
asks; the maintainer approves it there.

## D-069 (2026-10-03): predicate identity for JS assertions (#198, first half)

The lattice gives different predicates one rung. `toBeNull()` and `.to.exist`
are both NON_NULL, `toBeLessThan(80)` and `.to.be.above(80)` both BOUND, and
JS `positive` meant "not negated". So a Jest matcher replaced by a chai
spelling that asserts something else passed v0.5.0 (#198 M1a-h), and honest
rewrites such as `.not.toBeNull()` -> `.to.exist` read as "the test now proves
the opposite" (FP1, FP2, FPJ1, FPJ2).

Rulings 198.IR, Q1, Q3, Q4 and Q5, as implemented in this half:

- Every JS spelling of a presence, equality or bound check records a key in
  `Assertion.predicate`, and JS `positive` says whether it asserts that key
  or its negation, the meaning `ir/model.py` documents. `toBeDefined()`,
  `toBeFalsy()`, `.exist`, `assert.exists` and `assert.isDefined` now assert
  negatively; the release guide names this. IR_VERSION stays 2 (D-067).
  Deep equality, `toBeCloseTo`/`closeTo`, membership, patterns, `within` and
  lengths record no key. Python records none in this round (#224 is the
  Python direction key).
- `ir/predicate.py` computes the relation of two keyed assertions on one
  subject from key and polarity alone, and ASSERT_WEAKENED reports it with
  the four ruled messages: polarity inverted, contradicts (bound direction
  reversed for bounds), predicate widened (graded by the lattice drop, so
  MILD_WEAKENING holds `===` -> `==` at warn) and an unverifiable
  replacement. The relation never compares operands. Pairing, gating and the
  lattice are unchanged, and no fingerprint moves.
- `@jest/globals` has its own module kind whose `expect` reads Jest matchers
  only, and `node:assert/strict`, `assert/strict` and `assert.strict` are the
  strict mode, whose `equal` and `deepEqual` are the strict comparisons.

Four readings the rulings leave to the implementation:

1. An `===` literal is a presence value of its own. `toBe(5)` is defined,
   not null and truthy, so `toBeTruthy()` -> `toBe(5)` is a strengthening
   and `toBe(78.75)` -> `.to.be.undefined` a contradiction. The relation
   reads that one operand only to place the literal. When both sides state a
   literal at one polarity, the change is the literal's and only
   EXPECTED_VALUE_CHANGED reports it.
2. Keys of two families (presence, equality, bounds) do not relate by key
   alone, so such a pair keeps the lattice judgement, as an unkeyed pair
   does, instead of reporting an unverifiable replacement. `toBeTruthy()` ->
   `toBe(expected)` and `toBeDefined()` -> `toBeGreaterThan(0)` keep
   passing.
3. `<` -> `<=` (and `>` -> `>=`) at one polarity also keeps the lattice
   judgement: only a shared bound makes it a widening, and
   `toBeLessThan(0.01)` -> `toBeLessThanOrEqual(0.005)` tightens
   (`js_handrolled_tolerance_matcher_neg`). The evidence half records the
   operand that decides it.
4. With `positive` in its documented meaning, the existing cross-form rule
   would report `toBeDefined()` -> `toEqual(5)`, a strengthening that
   `tests/test_js_foundation.py` pins as passing (#167). A presence check
   beside an affirmative assertion of another kind is therefore no polarity
   change, and the lattice judges the pair.

The ruling allows two PRs. This first half closes M1a-h and, through
reading 1, also M2d and M2e, so it removes those ten known-regression
entries; the evidence half removes the other six (M2a-c, M2f-h).

Cost: new blocks on Jest-only predicate swaps that passed both tags (the J
rows, `toBeUndefined()` -> `toBe(null)` and the like), on B1, B2, S3 and T3,
and, through reading 4's limits, on `toBeFalsy()` -> `toEqual(5)`. A negated
absence check rewritten as an affirmative assertion of another form
(`.to.not.exist` -> `.to.include(x)`) no longer blocks. The JS false-positive
cost is not measured; the JS/TS replay corpus (X.js-fp-measurement) must
measure it before the release that ships this.

The agent wrote this entry in the #198 fix PR, as the rulings' X.doc-batch
asks; the maintainer approves it there.

## D-070 (2026-10-03): operand evidence for JS assertions (#198, second half)

D-069 made each JS spelling state its predicate. A pair could still read as
preserved while its evidence was lost: `toBe(78.75)` -> `assert.equal(x, 75)`
passed because `==` recorded no expected value (#198 M2a-c), and
`toBeCloseTo(v, 2)` -> `.closeTo(v, Infinity)` because a delta of `Infinity`,
`Number.MAX_VALUE` or a name recorded no tolerance (M2f-h).

Rulings 196.190.2, 196.190.4, 196.189.3, 198.Q2, Q3 and Q4 and 198.IR
amendment 2, as implemented in this half:

- Every JS equality records its scalar operand, chai's `assert.equal` and
  Node's legacy `equal` and `deepEqual` included; `equal`'s `eq_loose` key
  carries the coercion (190.2). The literal reader reads through parentheses
  and TypeScript's `as`, `satisfies` and `!` (T4, T5).
- The ordering matchers, chai's bound words and `assert.isAbove` and its
  siblings record their bound (198.Q2, Q4). A bound read as a hand-rolled
  tolerance is tolerance evidence only.
- A `closeTo` delta is read by the hand-rolled bound's exact reader, with
  `Number.MAX_VALUE` added to its named bounds (190.4).
- `Assertion.operand_source` records each expected value's or bound's text
  without comments, parentheses or TypeScript wrappers. It decides only
  whether two spellings state the same operand: two bounds naming one bound
  are compared over the values below, at and above it, so `< 80` -> `<= 80` is
  a widening (D-069 reading 3), and it gives the names a rewritten operand
  reads. IR_VERSION stays 2 (D-067).
- EXPECTED_VALUE_CHANGED reads JS operands as Python's: a literal rewritten
  into another literal, a bound included, and a name or call replaced by a
  different one, compared by the names it reads (198.IR amendment 2).
- A hand-rolled `Math.abs(d) < bound` in a truthy spelling records its bound
  key from the `Math.abs` side, lower bounds included, so a `<` -> `>` flip
  is reported as a bound direction reversed (189.3). Asymmetric matchers as
  the whole expected value of `toEqual` are the predicate they state (198.Q3).

Five readings the rulings leave to the implementation:

1. **A literal and an expression stay unreported in both directions.** The
   ruling names literal -> literal and a name or call replaced by a
   different one, and keeps literal -> call and literal -> imported name as
   they are until #226. The reverse, a name or call replaced by a literal, is
   what Python reports as issue #60; `tests/test_js_literal_evidence.py` pins
   it unknown for JS, and the rulings flip no such pin, so it waits for #226
   too.
2. **Unknown tolerance evidence is a loss only when the old side was known.**
   A known tolerance replaced, on the same subject, by a `closeTo` delta or
   `toBeCloseTo` precision checkwash cannot read is reported by
   ASSERT_WEAKENED as an unverifiable replacement, never mild (190.4: "an
   unreadable delta is unknown under #198's rule"). A tolerance unknown before
   the edit is not compared, as Python's unreadable tolerances are not, and a
   hand-rolled bound rewritten into one the reader cannot read in place stays
   unreported, as #189's review pinned.
3. **The hand-rolled flip is judged on the magnitude.** The subject of a
   truthy spelling is the whole comparison, and its `left` does not change in
   this round (189.2 changes it). The relation compares the two `Math.abs`
   sides instead, and a reversal is unverifiable when either bound was not
   read (189.3). The `=== true` and truthy spellings of one comparison state
   one bound, so `expect(cmp).toBe(true)` -> `assert.ok(cmp)` no longer
   reports a widening.
4. **No restoration credit in JS.** Python passes `x < 80` -> `x == 78.75`
   through a proof of an unchanged native-assertion context, which JS does
   not have. `toBeLessThan(80)` -> `toBe(78.75)` therefore reports its new
   value, which the rulings' cost ("including a tightened bound") accepts.
5. **Asymmetric matchers:** `expect.anything()` is `!= null` and
   `expect.any(Ctor)` a type check; the other asymmetric matchers keep the
   equality reading.

Pins. The rulings flip `tests/test_js_foundation.py`'s legacy-equality pin
(equal and deepEqual) and `tests/test_js_chai.py`'s bound rows and
`assert.equal` value. They imply, without listing, three more:
`tests/test_js_literal_evidence.py` reads `(42)` and `42 as const` (T4, T5),
and `tests/test_js_chai.py` reads `closeTo(x, Infinity)` and spells a
`0.010` delta exactly (190.4).

Fingerprints: no rule changes its fingerprint scheme, but chai deltas are
now spelled as exact decimals (`abs=1.0` -> `abs=1`, `abs=5e-07` ->
`abs=5E-7`), so a TOLERANCE_LOOSENED finding whose old side is such a delta
has a new fingerprint. The release that ships this records it in its
D-063-style entry (X.release-and-fingerprints).

Cost: new blocks on rows that passed v0.5.0 (M2a-c, M2f-h, B3, B4, T1, T2,
T4, T5, O1, O2), on bound rewrites and name rewrites generally, on a known
tolerance lost to an unreadable one, and on the hand-rolled flip. The JS
false-positive cost is not measured; the JS/TS replay corpus
(X.js-fp-measurement) must measure it before the release that ships this.

The agent wrote this entry in the #198 evidence PR, as the rulings'
X.doc-batch asks; the maintainer approves it there.

## D-071 (2026-10-03): runner evidence decides JS collection continuity and suite-wide focus (#196)

The JS path rows form a union because a path alone does not say which runner
a project uses. So every move between two rows read as benign, although
Vitest, Mocha and node:test stop collecting many of them (#196 rows M0-M5,
P1-P3), and focus that turned off nothing in its own file was silent,
although Mocha and Jasmine apply it to the whole suite (F3-F6).

Rulings 196.186.7, 186.2, 186.3, 186.4, 187.4 and 198.Q5, as implemented:

- One runner-evidence predicate (`frontends/javascript/runners.py`) answers
  which runner collects a JS/TS file: the runners its own source names, by a
  `vitest`, `@jest/globals`, `node:test` or `bun:test` import or a
  `Deno.test` call, else the one the base side's root `package.json` names
  alone among `jest`, `vitest`, `mocha` and `jasmine`, else unknown (186.7,
  198.Q5).
- Each runner's row is its documented default discovery, matched
  case-sensitively (186.3): Jest 30 `testMatch`, Vitest's `defaultInclude`,
  Node's test-runner patterns, Mocha 12's `test` directory (not recursive),
  `jasmine init`'s `spec/**/*[sS]pec.?(m)js`, Bun's four suffixes and Deno's
  `{*_,*.,}test` names and `__tests__`.
- Rename expansion and D2's "live" read it. A move to a path the runner does
  not collect is a disappearance, and a unit that reappears in such a file
  earns no move credit. Unknown evidence falls back to the union of the Jest
  and node:test defaults (186.7, 186.2).
- Bun's and Deno's rows exist only on a file's own evidence, for test
  obligations as for continuity; never as union rows (186.4).
- Focus a diff adds to a JS/TS test file that had none, when no unit of the
  file is reported as unfocused, is TEST_DISABLED once for the file, with a
  conditional message, unless a `vitest` or `@jest/globals` import or a base
  manifest naming Jest or Vitest alone proves the runner keeps focus in the
  file (187.4). The IR carries it as the optional FileIR field
  `suite_focus_added`; IR_VERSION stays 2 (D-067).

Seven readings the rulings leave to the implementation:

1. **What evidence is.** `chai` is an assertion library that runs under any
   runner, so it names none and leaves the others standing. A file that
   names several runners is proven to run under one of them, and a path is
   collected when any of them collects it. Type-only imports and Node's
   `test` package name nothing.
2. **Which side is read.** A rename reads the moved file's base side, as the
   ruling's base manifest does, so the diff cannot choose the runner it is
   judged by. D2 reads the file where a unit reappears, and focus the file
   that holds it, both on the head side: that is the file the runner loads.
3. **Evidence judges only the paths its runner collects by default.** When
   the named runner does not collect the old path by default either, the
   project configures its own globs, which are not read, and the union
   judges the move: `__tests__/a.ts` -> `__tests__/b.ts` stays benign in a
   Vitest project. D2 has no such fallback, as the ruling words it.
4. **Case.** Continuity matches case-sensitively, the union fallback
   included, which closes M4 without evidence. Test obligations stay
   case-insensitive (186.3), so a test with a case-folded name is still
   judged, and a move of it is judged by the case-sensitive rows.
5. **Bun and Deno obligations.** Either side's evidence makes the file a
   test, so dropping the import does not drop the file's obligations. Their
   assertions stay unread (`expect` from `bun:test`, Deno's `assert*`): the
   units are judged for removal and disables only.
6. **What "adds focus" means.** The head side has a focus and the base side
   had none; an added file counts. A unit the focus turns off carries the
   report instead, so Fc1 keeps its one finding, and a move out of
   collection is reported as the removal instead.
7. **Mocha's and Jasmine's rows are relative to a working directory the scan
   does not know.** Mocha's is a file directly inside any `test` directory,
   Jasmine's a file beneath any `spec` directory, so a package's own
   directories count in a monorepo. Both are known only from the root
   manifest.

Pins. The ruling flips no listed pin. 187.4 implies one:
`tests/test_js_liveness.py` pinned `it` -> `it.only` on the only unit of a
file on globals as silent; with no evidence it now reports the suite, and the
silent case moves to a Vitest file.

Fingerprints: the file-level focus finding has a new fingerprint, built from
the path, `<file>` and the marker `test.focused`. The release that ships
this records it in its D-063-style entry (X.release-and-fingerprints).

Cost: new blocks on rows that passed v0.5.0 (M0-M5, P1-P3, F3-F6). False
positives: a project whose configured globs collect a destination its
runner's defaults do not, such as a Vitest `include` or a recursive Mocha
`spec` when a top-level `test/` file moves into a subdirectory, and a Jest
project on injected globals without a manifest naming Jest alone that
focuses a whole file. The JS
false-positive cost is not measured; the JS/TS replay corpus
(X.js-fp-measurement) must measure it before the release that ships this.

The agent wrote this entry in the runner-evidence PR, as the rulings'
X.doc-batch asks; the maintainer approves it there.

## D-072 (2026-10-03): which units a JS focus stops follows the runner (#196 187.2, 187.1)

The JS frontend kept every unit under a focused block running. So `it.only`
beside a plain test inside `describe.only` was silent, although every runner
skips the plain test (probe 187.2a). v0.4.2 blocked that case only because it
read the focused unit as removed; v0.5.0 passed it. The `test.unfocused`
finding said "disabling marker added", which node:test makes false unless a
flag set outside the file is on.

Rulings 196.187.2 and 187.1, as implemented:

- **Which units a focus stops follows the runner** (187.2). The runners
  were run on Jest 30.5.2, Vitest 5.0.3, Mocha 12.0.3, Jasmine 7.0.0 and
  Node 22.22.
  - **Jest's rule (B)** judges Jest and every runner that is not known,
    because it is the most permissive of them. A block's focus reaches
    every block inside it. It also reaches the tests directly in the block,
    unless one of those tests is focused (jest-circus,
    `finish_describe_definition`).
  - **The innermost rule (D)** judges a file whose runner evidence (D-071)
    names only Vitest, Mocha, Jasmine or node:test: a focused block that
    holds a focused declaration runs only that declaration. The ruling
    deferred D until 186.7's evidence existed; D-071 shipped it.
  - **Measured agreement.** Over nine named shapes and 100 random ones,
    Jest's rule equals Jest's runs. The innermost rule equals Vitest's,
    Jasmine's and node:test's runs, under both `--test-only` and
    `--experimental-test-isolation=none`. Mocha runs a subset of it.
- **The `test.unfocused` message states the runner condition** (187.1):
  "focus elsewhere in this file; a runner that honours it stops this unit
  (node:test only under --test-isolation=none or --test-only)". The
  fingerprint is built from the marker name, so it does not change.

Seven readings the rulings leave to the implementation:

1. **Each side is judged under its own runner.** The base side's units use
   the base side's evidence and the head side's units use the head's. Both
   read the manifest from the base root `package.json` (D-071). A diff that
   changes a file's runner import therefore changes the rule on that side:
   moving from `@jest/globals` to `vitest` reports a unit the new runner
   stops.
2. **Tests inside tests.** node:test runs every subtest of a focused test,
   so a unit inside a focused test runs, whatever its siblings declare. A
   unit inside an unfocused test stands or falls with the outermost test
   around it. Focus inside a test does not narrow the block around that test
   under the innermost rule, because node:test meets a subtest only once its
   test runs (measured).
3. **Mocha stays lenient.** Mocha 12's `Suite.filterOnly` goes further: when
   a block holds a focused test of its own, it also drops the block's inner
   blocks (shapes S4 and S7). The ruling names the innermost rule for Mocha,
   so those stops stay unreported (THREATMODEL row 108 residual).
4. **What counts as focus, and whether the file holds any, are unchanged.**
   The rule decides only which units a focus stops, and it is asked only
   when the file holds focus. Under Jest's rule every unit the old rule
   stopped still stops, and the innermost rule stops at least what Jest's
   does (pinned by a random-shape property test). When the new rules stop a
   unit in a file whose focus is new, that unit carries the report instead
   of the file-level finding, as D-071 reading 6 words it.
5. **Which focus a stopped unit cites.** A unit with no focused block around
   it cites the file's first focus, as before. A unit stopped inside a
   focused block cites the first focus inside the nearest focused block
   around it that is not itself around the unit. It does not cite the
   block that keeps it.
6. **The message drops "added".** The ruling's wording begins "focus added
   elsewhere in this file". The finding also fires when no focus was added:
   when a unit's own `.only` is removed while another focus remains, and
   when a unit moves out of a focused block. Without "added" the message is
   true in both cases.
7. **Flag spelling.** Node 22.22, which was run, accepts only
   `--experimental-test-isolation=none`. The message keeps the ruling's
   `--test-isolation=none`, the newer name; `docs/stability.md` names both.

**Pins.** None flip: the full suite and every existing fixture keep their
expectations.

**Tests and fixtures.**
- New tests: `tests/test_js_focus_rules.py`.
- New fixtures: `js_focus_nested_sibling_pos` and
  `js_focus_innermost_vitest_pos`, with the control
  `js_focus_innermost_jest_neg`.

**Fingerprints.** Unchanged for existing findings. A newly stopped unit
uses the existing `test.unfocused` fingerprint.

**Cost.**
- **New blocks** appear only where a focused declaration sits inside a
  focused block (Jest's rule), or where a focused block holds a focused
  declaration in a file proven to run under Vitest, Mocha, Jasmine or
  node:test.
- **False positives.** A file judged by evidence that does not match how
  the project runs it; for example, node:test honours no focus without its
  flags (187.1, unchanged).
- **Unmeasured.** The JS false-positive cost is not measured (X.js-fp-measurement).

The agent wrote this entry in the fix PR, as the rulings' X.doc-batch asks;
the maintainer approves it there.

## D-073 (2026-10-03): E7 reads a path-only test role only when the file declares a test (#196 186.8)

The JS/TS test role is an engine overlay on the SPEC §2 table (#175, #197). A
path that some runner's defaults read as a test is judged as a test, whatever
its content. When the overlay found no test in the file, no test rule read
it, yet its test role still disarmed E7. Under a task contract, an
out-of-scope edit to production code named like a test reported SCOPE_DRIFT
at warn and passed:

- `src/api/spec.ts`, `Test.tsx` and `test.jsx` (#196 rows S1-S3) on v0.5.0;
- `test.ts`, `test-utils.ts`, `Test.ts` and `test/fixtures.ts` (rows Sp1-Sp4)
  on both v0.4.2 and v0.5.0.

Ruling 196.186.8 (a), as implemented:

- **What E7 reads.** E7 reads a test role that comes from the path alone only
  when the file declares a test on either side. Otherwise it reads the role
  that the SPEC §2 table and runner promotion give the path.
- **Where the role is recorded.** The engine records that role in
  `ir.globals.scope_drift`, so gating does not change. The SCOPE_DRIFT message
  and fingerprint name the role.
- **Scope.** The rule covers every row of the JS path table, not only
  v0.5.0's new Jest names.
- **E7 only.** Every other rule keeps the test role, and no production credit
  comes back: these files give neither REPAIR_EVIDENCE nor the opaque
  exemption.
- **Python.** Python helpers under `tests/` keep warn, because their table
  role is test.

Four readings the ruling leaves to the implementation:

1. **What "declares a test" means.** The ruling says "at least one test
   unit".
   - **What counts.** The JS frontend counts every scanned unit. It also
     counts every declaration with an inline callback, whether a unit or a
     suite. So a `.each` table, a computed title (`it(c.name, fn)`) and a
     `describe` whose tests a helper declares all count: the runner collects
     them even though the unit scan does not read them.
   - **What does not.** A pattern's `.test(value)` call has no callback, so it
     does not count.
   - **The exception.** `.test("literal")` does count, because the unit scan
     already takes it for a unit (THREATMODEL row 107 residual).
   - **Where it is carried.** `ParsedFile.declares_tests` carries the answer,
     and the IR does not change.
2. **Either side.** A file that declared a test at base or at head keeps the
   test role for E7. So removing the last test from a real test file is
   judged by the test rules (TEST_DISABLED), not by E7.
3. **One definition for E7 and the opaque exemption (#217).** The ruling asks
   for one "test-support path" definition to decide both.
   - **This round's half.** This round fixes the E7 half as a rule about any
     path-only test role. Whatever the engine moves from the table role to the
     test side by the path alone, E7 reads the table role unless the file
     declares a test.
   - **#217's half.** #217's round can then give non-JS data and mocks
     beneath test-support directories a non-production role as another such
     overlay, not as a SPEC §2 default glob. The opaque exemption goes away,
     and E7 still reads production: #217 E1 keeps blocking, and E2 blocks from
     this round.
   - **Why not a default glob.** A default `__tests__/**` glob would turn E7's
     table role itself into test and reopen E1.
4. **Runner promotion is part of the table role.** A promoted runner script
   keeps `ci` for E7, as before.

**Pins.** None flip.
- New tests: `tests/test_scope_table_role.py`.
- New fixture: `js_scope_drift_spec_name_pos`, with the control
  `js_scope_drift_test_file_neg`.
- Gate (X.gate-bookkeeping): `tests/verdict_gate/labels.toml` relabels
  i196/S1-S3 and Sp1-Sp4 block. Each label matches the fix, so no accepted
  entry is needed.

**Fingerprints.** SCOPE_DRIFT's fingerprint includes the role. For these
files the role moves from test to prod, so the fingerprint moves too. The
release that ships this records it (X.release-and-fingerprints).

**Cost.** New blocks appear only under a task contract, on out-of-scope
edits to:
- production code named like a test, as intended;
- JS helpers with no test in them beneath `test/` or `__tests__/`, a false
  positive the ruling accepts.

SCOPE_DRIFT is off without a contract, so measuring this needs a
contract-bearing corpus such as `benchmarks/decoy`. It is not measured.

The agent wrote this entry in the fix PR, as the rulings' X.doc-batch asks;
the maintainer approves it there.

## D-074 (2026-10-03): files beneath a test-support directory take the test role whatever their extension (#217)

Since #175, a JS/TS file beneath `__tests__/` has the test role. Other files
there kept the production role: JSON fixtures, YAML and text data. So did
every file beneath `__mocks__/`, and every non-JS file beneath Node's `test/`.
Editing one was an opaque production change, which granted the whole diff
REPAIR_EVIDENCE (THREATMODEL row 2). A weakened assertion beside it passed at
warn on v0.4.2, v0.5.0 and `main` (#217 rows D1-D3 and D6). Python had no such
gap, because every file under `tests/**` has the test role whatever its
extension.

Ruling 196.followup.tests-dir-non-js-data (#217), with the maintainer's answer
that `test/` belongs in the definition, as implemented:

- **What a test-support path is.** A path with a `__tests__`, `__mocks__` or
  `test` directory segment, matched whole and in any case, that is not a
  Python file or a build artifact (`roles.is_test_support_path`).
- **The role.** Such a path takes the role `test` when the SPEC §2 table and
  runner promotion leave it at `prod` and it is not a JS/TS test path. Like
  the JS test role, this is an engine overlay, not a default glob, so
  `DEFAULT_ROLES` and the SPEC §2 table do not change.
- **E7.** E7 reads the table role, by D-073's rule for any path-only test
  role. An out-of-scope edit to such a file stays OUT_OF_SCOPE_PROD_TOUCH
  (#217 E1), and E2 keeps blocking.
- **Base side.** The opaque exemption also requires that a rename's old path
  was not a test-support path, so test data moved into production grants
  nothing.

Readings the ruling leaves to the implementation:

1. **`test/` is in.** This is the maintainer's answer to #217's open question.
   Node's runner collects JS beneath `test/`, and the data there serves those
   tests.
2. **Python files are out.** A Python file keeps the table's Python rows:
   `test/test_x.py` is already a test, and `test/helpers.py` stays production.
   Changing those rows would move Python verdicts the ruling did not ask
   about.
3. **Whole segments, any case.** Directory segments match as JS test
   obligations do (#196 186.3). `test-data/`, `__tests__x/` and `contest/` are
   not test-support directories.
4. **No production credit of any kind.** The test role takes these files out
   of every production-evidence channel, not only the opaque exemption.
   - **Snapshot alone beside test support.** A snapshot rewritten beside a
     mock or test data alone, with no production change, now reports
     EXPECTED_VALUE_CHANGED high [NO_PROD_CHANGE_IN_DIFF], as a snapshot beside
     data under Python's `tests/` already did. Before, it reported
     SNAPSHOT_CODE_COCHANGE at warn, "changed together with prod code", and
     passed.
   - **Snapshot beside production code.** SNAPSHOT_CODE_COCHANGE still reports
     at warn, and its message names only the production files.
   - **Suite controls.** A conftest suite control blocks as before. Its label
     (SPEC §2b) reads NO_PROD_CHANGE_IN_DIFF when test support was the only
     file changed besides it.
5. **Renames follow the new path.** Production code moved beneath a
   test-support directory is test support at its new path. What production
   lost is a deletion, and a deletion buys no exemption either.
6. **`__mocks__` and #218.** The role makes a `__mocks__/` file test code.
   Whether a manual mock installed there stands in for the code under test is
   #218's question, and row 109's residual does not change.

**Pins.** None flip.
- New tests: `tests/test_test_support_paths.py`.
- New fixtures:
  - `js_test_support_tests_dir_data_pos` (D1);
  - `js_test_support_mocks_dir_pos` (D2);
  - `js_test_support_fixture_yaml_pos` (D3);
  - `js_test_support_node_test_dir_data_pos` (D6);
  - `js_test_support_snapshot_beside_mock_pos` (reading 4).
- Unchanged, as #217 requires:
  - the `js_jest_tests_dir_*` fixtures, `js_jest_testfixtures_dir_neg` and
    `runner_opaque_native_neg`;
  - the pins in `tests/test_js_paths.py` and `tests/test_js_default_layouts.py`.
- Gate: no case's verdict changes, so `tests/verdict_gate/labels.toml` and
  `tests/gates/verdict_gate_accepted.toml` are unchanged.

**Fingerprints.** A content-bound fingerprint includes the file's role. These
fingerprints move:
- SCOPE_DRIFT on these files, although its message still names `prod`;
- SNAPSHOT_CODE_COCHANGE whose production list held one of these files.

The release that ships this records the move (X.release-and-fingerprints).

**Sweep.** The ruling's costs list a sweep.
- **What the census found.** The six recorded sweep ranges in
  `benchmarks/sweeps/*.json` hold 1,800 commits that change 4,692 paths. None
  of those paths is a test-support path. No verdict, finding or fingerprint
  there can move.
- **What it cannot show.** For the same reason, the sweep cannot measure this
  decision's cost.

**Cost.** Verdicts move only toward block:
- **Intended.** An oracle weakened beside an edit to test data, a manual mock
  or a non-JS helper beneath such a directory now blocks when nothing else
  explains it.
- **False positive.** A snapshot re-recorded after a deliberate mock or
  fixture update, with no production change, now blocks (reading 4).
- **False positive.** Production code kept beneath a directory named `test`,
  `__tests__` or `__mocks__` stops counting as production evidence.

The JS false-positive cost is not measured. It waits on the JS history corpus
(#212).

The agent wrote this entry in the fix PR, as the rulings' X.doc-batch asks;
the maintainer approves it there.

## D-075 (2026-10-03): JS stand-ins - where they take effect, for whom they are new, what reads them (#196 188.1-188.4)

The JS spelling of TEST_PATCHES_SUBJECT (#177, THREATMODEL row 109) carried
four known gaps from #188:

- **Timing.** It read every `vi.mock` written below module level as an
  ordered mock. An ordered mock reaches no static import, so a `vi.mock`
  slipped into a test body passed silently.
- **Newness.** It judged "the stand-in is new" file-wide. A replacement
  copied from one test into another was read as already there, although it
  had never run for the second test.
- **Module objects.** A namespace or `require()` object passed whole
  (`new UserService(apiClient)`, `compute(billing)`) counted as reading a
  whole-module mock. Python's row 90 counts only a read that names a
  replaced export.
- **Two-statement spies.** `const spy = vi.spyOn(...)` followed by
  `spy.mockReturnValue(...)` installed nothing on either side. As a stand-in
  it was missed, and as an existing installation it was not seen, so
  inlining one read as new.

Rulings 196.188.1 (B), 188.2 (B), 188.3 (C) and 188.4 (C, the closing round),
as implemented in `frontends/javascript/module_mocks.py`:

- **188.1: `vi.mock` takes effect for the whole file, wherever it is
  written.** `jest.mock` keeps its timing: hoisted at module level, ordered in
  a test body. Measured with real runners on the same five placements (a
  test, another test, a describe body, a hook, a helper that never runs):
  - Vitest 3.2.7 and 4.1.11 apply the stand-in to every test in the file.
    4.1.11 warns that the call "will be hoisted and executed before any
    tests run".
  - Vitest 5.0.3 refuses the file before any test runs, with the same
    explanation.
  - Jest 30.5.2 keeps the real module for a top-level `require` when
    `jest.mock` sits in a test, a describe body or a hook, and applies it at
    module level.
- **188.2: newness per unit, as Python.** A target is new for unit U unless
  the base side installed it at module level, in a hook, a describe body, a
  helper or U itself. An installation inside another test does not count.
  A hoisted `vi.mock` counts wherever it is written, because it ran for the
  whole file.
- **188.3: a read names an export.** A named or default import counts in any
  use. A namespace or `require()` object counts only through member access.
- **188.4: one hop through the spy's local binding, on both sides.** The
  closing round 188.4 asks for. It covers `vi.spyOn`, `jest.spyOn`,
  `vi.mocked` and `jest.mocked` replaced in a later `mock*` call, and
  node:test's `mock.method` without an implementation replaced through
  `fn.mock.mockImplementation(...)`. The replacement takes effect where that
  call runs. A rebound spy name is refused. A bare spy is still no
  installation, as ruling 188.4's option A keeps.

Readings the rulings leave to the implementation:

1. **"Wherever it is written" includes a helper that never runs.** Vitest
   hoists the call itself, not the function around it; both measured
   versions that run the file applied it.
2. **Vitest 5 is not modelled apart.** On Vitest 5 a nested `vi.mock` fails
   the file, so a finding there accompanies a red run instead of a silent
   pass. Without runner-version evidence one model serves every version.
3. **"Inside another test" is position-based.** An installation counts as
   inside another test when it lies in that test's span. A test that
   contains this unit (a node:test parent around a subtest) is not "another
   test": its body runs for the subtest.
4. **188.4 includes node:test.** The ruling's example is `vi.spyOn`;
   node:test's `mock.method` without an implementation is the same
   two-statement shape (a spy that replaces nothing until a later call), so
   the round closes it too.
5. **The 188.3 residual is pinned in unit tests, not in a fixture.** A
   fixture's expectation can never be changed, and a later round may close
   this residual.

**Pins.** None flip.
- New tests: `tests/test_js_mock_installations.py`. 13 of them fail on
  `main`; the 16 controls pass on both.
- New fixtures:
  - `js_test_patches_subject_vi_mock_in_test_pos` (188.1);
  - `js_test_patches_subject_copied_from_other_test_pos` (188.2);
  - `js_test_patches_subject_two_statement_spy_pos` (188.4).
- Every existing `js_test_patches_subject_*` fixture and
  `tests/test_js_module_mocks.py` keep their expectations, including the
  timing pins for `vi.doMock` and for `jest.mock` inside a describe body.

**SPEC.** The sentence of ruling 196.spec.4-test-patches-subject joins the
SPEC §4 TEST_PATCHES_SUBJECT row in the same commit as the row 109 edits, as
that ruling asks.

**Fingerprints.** Unchanged: TEST_PATCHES_SUBJECT is keyed by path, unit and
target, and no target changes its spelling.

**Cost.**
- **New findings** (TEST_PATCHES_SUBJECT, high without repair evidence):
  - a nested `vi.mock`;
  - a replacement copied between tests;
  - a two-statement spy.
- **Fewer findings:** a module object passed whole under a whole-module mock
  (the accepted 188.3 residual).
- **Not measured:** the JS false-positive cost, which waits on #212.

The agent wrote this entry in the fix PR, as the rulings' X.doc-batch asks;
the maintainer approves it there.

## D-076 (2026-10-03): every write reaches the JS binding scan, and an unknown bound is not unchanged (#196 189.1)

The JS binding scan (`frontends/javascript/bindings.py`) reads a hand-rolled
tolerance bound and an assertion alias through their initializer. It carried
two known gaps from #189:

- **Writes.** Only `=`, `+=`, `-=`, `*=`, `/=` and postfix `++`/`--` made a
  name unknown, and only when written before the read in the read's own
  function or an enclosing one. A bound widened with `**=`, `||=`, `??=` or
  another compound operator, a prefix increment, a destructuring
  assignment, or a write in a `beforeEach` hook or a helper, still read as
  its initializer.
- **Statement ends.** A declaration without a semicolon ran on into the
  next line unless that line began with one of eight keywords, so
  `const eps = 0.01` directly above `expect(...)`, or `const check = expect`
  above `check(value).toBe(...)`, was not read.

A write the scan did follow turned a known bound into an unknown one, and
that was silent too: ASSERT_WEAKENED's known -> unknown rule (#198, 190.4)
covered `toBeCloseTo` and chai `closeTo` only. The ruling's reasoning names
that rule as the one 189.1 relies on.

Ruling 196.189.1 (a), as implemented:

- **Every write.**
  - Every assignment operator.
  - Prefix and postfix `++`/`--`. A postfix operator needs its operand on
    the same line; after a line break it is prefix, as in JavaScript.
  - Each target of a destructuring assignment, nested, rest and default
    included.
  - The target of a `for`-`in`/`of` head without a declaration.
  - A member target (`a.b = `, `a[k] = `) writes that path. A property of a
    call result or a private field writes no binding.
- **Writes from any function.**
  - A write in any other function counts wherever it is written: a hook,
    a helper or a callback may run before the read. Module code after a
    test's definition runs before its body.
  - In the read's own function a write counts when it comes first, or
    when a loop in that function runs both.
- **Statement ends.** A declaration ends at a `;`, a `,` or an unmatched
  closer. It also ends at a line break where the token before completes an
  operand and the token after cannot continue the expression: a name, a
  literal, `!` or a prefix `++`/`--`. An operator, `.`, `?.`, `(`, `[` or
  `{` on the next line continues it, as in JavaScript.
- **Unknown is not unchanged.** A hand-rolled bound read on the base side
  and unreadable on the head side is the unverifiable replacement SPEC §4
  already names: "a known tolerance replaced, on the same subject, by one
  the frontend cannot read". It is reported as ASSERT_WEAKENED "tolerance
  abs=0.01 -> a tolerance it cannot read", as an unreadable `closeTo` delta
  is. This covers a bound reached by a write, rewritten into a call, or
  past Decimal's range. A bound unknown on both sides replaces nothing and
  stays silent.

Readings the ruling leaves to the implementation:

1. **"Writes from any function" counts them wherever they are written.**
   Position orders nothing across functions. A write in a function that is
   never called still counts: the scan cannot tell it is never called.
2. **The read's own function keeps position order, except in a loop.** The
   capture-time pins in `tests/test_js_binding_writes.py` stay: a method
   captured before a later overwrite in straight-line code keeps its
   authority. A later write that reaches an earlier read when its function
   runs again (a helper called twice, `test.each`) is a stated residual.
   Counting it would also flip those pins.
3. **The known -> unknown rule extends to hand-rolled bounds in this round.**
   Without it every newly followed write would turn a silent widening into
   a silent unknown, and the ruling's reasoning names this rule as the one
   the round relies on. It closes two row 110 residuals: a bound rewritten
   into one checkwash cannot read (`< 0.01` -> `< tolerance()`), and
   literals past Decimal's exponent range.
4. **A destructuring declaration declares its names.** `const [eps] =
   [1e12]` shadows an outer `eps` with an unknown value. Before, an array or
   nested pattern declared nothing, so the read reached the outer name.
5. **What looks like an assignment but is not one is excluded.** A JSX
   attribute (`<Range max={5} />`), a class field (`static eps = 5`) and a
   TypeScript type alias (`type eps = number`) write nothing.
6. **#240 lands first.** Its PR reads TypeScript-annotated and cast
   declarations. Without it, an honest JS -> TS migration
   (`const EPS = 0.01` -> `const EPS: number = 0.01`) would read as known ->
   unknown and block.

**Pins.** Five flip, each a direct consequence of the ruling.
- `tests/test_js_binding_writes.py`: the two "unused function" cases move
  from "preserve the original oracle" to "remove the old oracle"
  (`function unused() { assert.strictEqual = () => {}; }` and its arrow
  twin). A write from any function counts.
- `tests/test_js_handrolled_tolerance.py`:
  `test_a_bound_past_the_decimal_range_is_unknown_not_a_crash`, both
  parameters. The pair now blocks with ASSERT_WEAKENED instead of passing;
  the no-crash half of the pin stands.
- `tests/test_js_predicate.py`: `< 0.01` -> `< tolerance()` moves from the
  documented residuals to the residuals the evidence closes.

**Tests and fixtures.**
- New tests: `tests/test_js_write_reach.py`.
- New fixtures, `bypass: 110`:
  - `js_handrolled_tolerance_compound_write_pos`;
  - `js_handrolled_tolerance_hook_write_pos`;
  - `js_handrolled_tolerance_asi_pos`;
  - `js_handrolled_tolerance_unreadable_bound_pos`;
  - control `js_handrolled_tolerance_unchanged_write_neg`.
- No existing fixture changes its expectation.

**Fingerprints.** Unchanged. ASSERT_WEAKENED is keyed by path, unit and the
before assertion, and no assertion text changes.

**Cost.**
- **New findings:** ASSERT_WEAKENED "cannot verify", high without repair
  evidence, on a hand-rolled bound that a new write, a call or an
  out-of-range literal makes unknown on the head side only. Semicolon-free
  files gain readings, so findings move both ways there.
- **Not measured:** the JS false-positive cost, which waits on #212. The
  known new false-positive class is a write that never runs before the read
  (a write in an uncalled helper), added on the head side.

The agent wrote this entry in the fix PR, as the rulings' X.doc-batch asks;
the maintainer approves it there.

## D-077 (2026-10-04): a hand-rolled tolerance is a subject, a centre and a bound, in both frontends (#196 189.2)

A hand-rolled tolerance, `Math.abs(total - 78.75) < 0.01` in JavaScript or
`abs(total() - 78.75) < 0.01` in Python, checks `total` against 78.75 within
0.01, as `pytest.approx(78.75, abs=0.01)` does. Neither frontend recorded it
that way:

- **JavaScript** read the bound as an `abs=` tolerance (#179) and left the
  subject alone: the whole comparison in the truthy spelling, `Math.abs(...)`
  in the matcher spelling. The centre was part of that text, so
  `- 78.75` -> `- 75` changed the subject, the pair fell to the span-order
  fallback and nothing compared the centre.
- **Python** read it as a plain comparison: `abs(total() - 78.75)` was the
  subject and the bound the expected value. A rewritten centre passed
  silently, a widened bound was EXPECTED_VALUE_CHANGED and a tightened one
  blocked as the same (#225).

Ruling 196.189.2 (a), extended to both frontends, as implemented:

- **One representation.** What the magnitude measures is `left`. A numeric
  literal centre, on either side of the argument's one subtraction, is the
  expected value. The bound is an `abs=` tolerance. With no literal centre
  (`abs(total - expected)`, `abs(d)`) or two, the whole argument is `left`
  and there is no expected value.
- **Rules, unchanged, read it.** A rewritten centre is EXPECTED_VALUE_CHANGED,
  a widened bound TOLERANCE_LOOSENED, and an edited check pairs with itself
  on its subject instead of by position.
- **Fallback pairs.** "A fallback pair whose subjects differ never compares
  tolerances." The hunk is in `ir/diffalign.py`, which Python shares, so
  the ruling asks for the maintainer's sign-off; it is a commit of its own
  in the fix PR, and reading 4 narrows it.
- **196.followup.abs-expected-centre** (#225) closes in the same round.

Readings the ruling leaves to the implementation:

1. **JavaScript reads both directions of the bound.** A lower bound
   (`Math.abs(d) > eps`) records its subject and centre too, but no
   tolerance, so the two halves of a `<` -> `>` flip share a subject and the
   flip is still a bound direction reversed (189.3). The matcher spelling
   of a lower bound (`expect(Math.abs(d)).toBeGreaterThan(eps)`) is read as
   the truthy one is. Its bound is therefore no longer an expected value:
   its value is not compared, in either spelling, which row 110 already
   listed as a residual for the truthy one.
2. **Python reads the upper bound only.** Python records no bound direction
   (#224), so a lower bound stays a plain comparison with its bound as the
   expected value. A `<` -> `>` flip, which passed silently, now blocks, as
   the centre rewritten into the bound rather than as a reversed direction.
3. **A centre is never a bound.** A literal is bound evidence for the
   predicate relation (#198) only when it is the bound operand's own value,
   so the centre a hand-rolled matcher records is never compared as its
   bound. The synthetic relation helper in `tests/test_js_predicate.py`
   now gives a literal bound its operand text, as the frontend does.
4. **A fallback pair skips the comparison only when it is a
   substitution.** Taken literally, the ruling let any renamed or hoisted
   subject widen any tolerance: `t = total()` above
   `assertAlmostEqual(t, 78.75, delta=1e12)` passed, and so did the same
   edit to `places`, to `toBeCloseTo` and to both hand-rolled spellings.
   A subject replaced while its expected literal stayed, or a check with
   no literal on either side, passed too. Ten probed shapes that block on
   main passed. So a fallback pair skips the comparison only when both of
   its expected literals are recorded and differ as well as its subjects,
   and its strength did not drop. Those are the conditions on which
   EXPECTED_VALUE_CHANGED reports the pair, usually beside
   ASSERT_SUBSTITUTED, the outcome the ruling's costs foresee ("Python
   approx fallback pairs may become ASSERT_SUBSTITUTED"). Every other
   fallback pair is compared as before: one side with no recorded
   subject (a bare `pytest.approx` comparison) or no literal, a subject
   that moved alone, a pair whose strength dropped. The narrowing is the
   agent's, and the maintainer approves or overrules it with the
   diffalign commit.
5. **Python's `abs` is the builtin unless the file binds `abs`.** Any
   binding of the name anywhere in the file (a definition, an import, an
   assignment target, a parameter) turns the reading off for the whole
   file, as an unshadowed `Math` is required in JavaScript. A star import is
   not a binding of the name. `math.fabs` and `numpy.abs` are not read.
6. **Python records the bound as written,** as `pytest.approx` records its
   tolerances, so a name or an expression it cannot read as a Decimal is
   unjudged. A bound rewritten into another tolerance kind (`approx`'s
   default `rel`, `assertAlmostEqual`'s `delta` or `places`) is compared as
   new slack until 190.3 compares the kinds as one absolute bound; before
   this round the same rewrite blocked as EXPECTED_VALUE_CHANGED.

**Pins.** Two move, each a direct consequence of the representation.
- `tests/test_js_operand_evidence.py::test_a_hand_rolled_bound_states_its_direction`:
  the matcher spelling's `right_value` was None, so that the bound was never
  the expected value (198.Q2). The bound still is not; the expected value is
  now the centre, and the test pins `left` and `right_value` for every row.
- `tests/test_js_predicate.py`: `_keyed` gives a literal bound its operand
  text (reading 3). No row of `test_relation` changes.

**Tests and fixtures.**
- New tests: `tests/test_abs_decomposition.py` (the readings) and
  `tests/test_fallback_tolerance.py` (reading 4).
- New fixtures, `bypass: 110`: `js_handrolled_tolerance_centre_pos`,
  `js_handrolled_tolerance_matcher_centre_pos`; control
  `js_handrolled_tolerance_centre_respelled_neg`.
- New fixtures, `bypass: 113`: `handrolled_tolerance_centre_pos`,
  `handrolled_tolerance_unittest_centre_pos`; with
  `handrolled_tolerance_widened_pos` and control
  `handrolled_tolerance_tightened_neg`.
- New fixtures for reading 4, each a hoisted subject with its tolerance
  widened, which block on main and pass under the literal reading:
  `tolerance_hoisted_subject_widened_pos` and
  `js_handrolled_tolerance_hoisted_subject_pos` (`bypass: 110`).
- No existing fixture changes its expectation.

**Fingerprints.** Two changes, both for the X.release-and-fingerprints
batch:
- A widened Python hand-rolled bound moves from EXPECTED_VALUE_CHANGED to
  TOLERANCE_LOOSENED, so an allowlist entry for the old finding stops
  matching.
- Six rules key a JS assertion by its legacy matcher identity only while
  the matcher's subject is the recorded `left`: ASSERT_REMOVED,
  ASSERT_WEAKENED, ASSERT_SUBSTITUTED, SUBJECT_NORMALIZED,
  SUBJECT_INPUT_CHANGED and TEST_DISABLED. A hand-rolled check spelled
  through `expect(...)` now records what the magnitude measures, so these
  rules key it by its complete text instead:
  `expect(Math.abs(d - c) < eps).toBe(true)`,
  `expect(Math.abs(d - c)).toBeLessThan(eps)`. In the corpus, three
  ASSERT_WEAKENED fingerprints change:
  `js_handrolled_tolerance_compound_write_pos`, `_hook_write_pos` and
  `_unreadable_bound_pos`.

TOLERANCE_LOOSENED (`kind:before_eps`), EXPECTED_VALUE_CHANGED and
EXPECTED_VALUE_DERIVED (the before assertion's text) keep every other
fingerprint.

**Cost.**
- **Sweep:** the last 300 non-merge commits of attrs, click, flask, httpx,
  rich and starlette (1,800 commits) give 48 blocked commits on both
  engines and no verdict or finding change. No commit in the sweep edits a
  hand-rolled tolerance, so the sweep shows the absence of collateral change
  on Python, not the new findings.
- **New findings** (high without repair evidence):
  - EXPECTED_VALUE_CHANGED on a rewritten centre, in both frontends;
  - TOLERANCE_LOOSENED on a widened Python bound, which was
    EXPECTED_VALUE_CHANGED;
  - EXPECTED_VALUE_CHANGED on a Python `<` -> `>` flip (reading 2).
- **Fewer findings:**
  - a tightened Python bound, which was EXPECTED_VALUE_CHANGED;
  - TOLERANCE_LOOSENED on a fallback pair whose subjects and expected
    literals both moved, which EXPECTED_VALUE_CHANGED reports instead;
  - EXPECTED_VALUE_CHANGED on the value of a JS matcher lower bound
    (reading 1).
- **Credits:** beside a dependency manifest change, such a substitution
  earns the dependency-drift credit that both of its rules take and
  TOLERANCE_LOOSENED does not, so it stops blocking: an `assertAlmostEqual`
  replaced by one on another subject with a wider `delta`, beside a
  `requirements.txt` bump, blocked on main and passes (THREATMODEL 84c
  names the credit's residual).
- **Kept:** two unrelated checks paired by position whose expected literal
  is the same or absent still compare their tolerances, as on main.
- **Not measured:** the JS false-positive cost, which waits on #212.

The agent wrote this entry in the fix PR, as the rulings' X.doc-batch asks;
the maintainer approves it there.

## D-078 (2026-10-04): a JS assertion checkwash does not read is recorded with no strength (#196 190.5)

A JavaScript assertion whose predicate the scans do not read was a coverage
notice and nothing else: a throw check (`expect(fn).toThrow(RangeError)`,
`assert.throws`), a spy check (`expect(save).toHaveBeenCalledWith(78.75)`),
`assert.match`, an unread Jest matcher or chai word. Deleting one passed with
zero findings. #180 proposed escalating the notices toward the gate.

Ruling 196.190.5 (c), as implemented:

- **No notice escalates.** The JS frontend records such a call as an
  assertion with strength null (SPEC §3), as Python records `assertRaises`:
  `raises` for the throw family, `unknown` otherwise.
- **Removal is ASSERT_REMOVED; a rewrite is not judged.** Two strength-null
  assertions compare to nothing, and alignment never pairs one with a
  classified assertion.
- **The frontend's own recognizer.** `_candidate_assertions` decides what
  is recorded; the coverage inventory keeps its own recognizer, so a call
  the frontend misses stays visible there.

Readings the ruling leaves to the implementation:

1. **Only a resolved assertion API is recorded.** That is a node:assert
   method the scan does not read, a chai assert method the scan does not
   read, an `expect(...)` call with a matcher chain, or an `expect` member
   that asserts (`expect.assertions`, `expect.soft`). A lookalike is not: a
   name imported from another module, a shadowed name, a written member.
   Recorded, the stand-in would pair by text with the oracle it replaced,
   which the binding pins forbid.
2. **What the scans read stays theirs.** A matcher or method the scans read
   but left out for its arguments (`expect(x).toBe()`,
   `assert.strictEqual(x)`) stays unrepresented. So do a name node:assert
   does not export (`assert.okay`), a Jest matcher on chai's `expect`, and a
   chai chain on the `expect` of `@jest/globals` (#198 Q5).
3. **The throw family.** It is `throws` and `rejects` (node:assert and
   chai), `toThrow` and its variants, a `.rejects` chain, and chai's
   `throw`, `Throw`, `rejected`, `rejectedWith` and `isRejected`. A negated
   one (`.not`, `doesNotThrow`, `doesNotReject`) is `unknown`.
4. **Not assertions:** a bare `expect(value)`, asymmetric matchers and
   registration (`expect.any`, `expect.extend`), a call inside another
   assertion's arguments, and a call in a nested function.
5. **The subject is the first argument** of `expect(...)` or of the call,
   so an edited check pairs with itself on its subject.
6. **A recorded call stays a coverage notice.** Its reason says the
   predicate is not read and a rewrite is not judged; an unrecorded
   candidate keeps the old reason.

7. **The support inventory declares the recording.** The contract's
   unsupported API entries said the frontend recognizes nothing, and its
   validator allowed no assertion without a strength. An unsupported entry
   may now declare a call recorded with no strength; only a supported
   entry states a strength. The 33 unsupported entries the frontend now
   records declare that recording, with their status unchanged. No
   mutation case changes, and none is added: the recommended Action's
   pinned engine is qualified against the same mutations and would stay
   red on them.

**Pins.** Two move, each a direct consequence of the ruling.
- `tests/test_js_chai.py::test_unsupported_chai_spellings_remain_coverage_gaps`:
  its eight spellings are now recorded as `unknown` with no strength; each
  stays a coverage notice.
- `tests/test_js_coverage.py::test_deleted_unknown_assertion_is_reported_on_the_base_side_without_a_finding`
  is now `..._and_removed`: deleting `assert.match(...)` is ASSERT_REMOVED,
  high, and blocks.

**Tests and fixtures.**
- New tests: `tests/test_js_unjudged_assertions.py`, and two rows of the
  contract validator's tests.
- New fixtures, `bypass: 114`: `js_unread_throw_check_deleted_pos`,
  `js_unread_spy_check_deleted_pos`, `js_node_assert_throws_deleted_pos`.
- New fixture, `bypass: 111`: `js_chai_property_deleted_pos`.
- Control: `js_unread_spy_check_rewritten_exact_neg`, a spy check rewritten
  into a newly written exact check (ASSERT_REMOVED at warn,
  SAME_UNIT_REWRITE).
- No existing fixture changes its expectation, and no case of the JS
  assertion contract's 283 mutations changes (reading 7 for its API
  entries).

**Fingerprints.** Unchanged: the round adds findings and changes none.

**Cost.**
- **New findings:** ASSERT_REMOVED, high without repair evidence, on a
  deleted unread assertion.
- **Compensated:** an unread check rewritten into a newly written strong
  check is held at warn (SAME_UNIT_REWRITE).
- **Corpus:** no verdict or finding changes. One IR changes:
  `js_test_patches_subject_spy_passthrough_neg` records its spy check.
- **Verdict gate:** every one of its 180 cases keeps the verdict and the
  findings of a candidate built from `main`, so no case is relabelled.
- **Known false positive:** an unread check moved into a helper function,
  as for any JS assertion the scans read.
- **Not measured:** the JS false-positive cost, which waits on #212.

The agent wrote this entry in the fix PR, as the rulings' X.doc-batch asks;
the maintainer approves it there.

## D-079 (2026-10-04): a runner site is a command that runs a test runner (#196 191.5)

#181 judged runner sites, the workflow steps and pre-commit hooks that run
the suite, by row 69's predicate, which asks whether a whole file names a
runner anywhere. One step read that way made false sites: `if: false` on
`pip install pytest`, on `./deploy-majestic.sh` or on `uses:
pmeier/pytest-results-action` blocked at high as a weakened test command. An
`echo pytest` step counted as a live runner too, so a runner reworded and
disabled beside one passed (191.8).

Ruling 196.191.5, as implemented:

- **One predicate reads one command.** `runner_command.invokes_test_runner`
  keeps row 69's runner names, matched as whole words, and is the predicate
  the JS runner vocabulary will share (#216).
- **Contexts known not to run a runner are excluded:** `echo` and `printf`
  text, heredoc text, install subcommands, and `uses:` steps whose `with:`
  inputs name no runner.
- **Every other wrapper keeps its runner:** `bash -c`, `docker compose run`,
  `nix develop --command`, `sudo`, `env` and commands checkwash does not
  know.
- **Runner sites only.** Row 69's `_runs_tests` keeps the deletion check and
  the opaque-exemption denial.

Readings the ruling leaves to the implementation:

1. **A whole word.** A name preceded by a word character or a dot, or
   followed by a word character, is part of another word: `jest` in
   `deploy-majestic.sh`, `tox` in `.tox` and in `TOX_PYTHON`. A dot after a
   name may begin an extension, so `pytest.exe` and `tox.ini` count, and so
   does `run-pytest.sh`. A tool with a subcommand (`make test`, `npm test`)
   needs the tool as a whole word, and its target may go on (`make tests`,
   `make test_unit`, `yarn test:unit`), as substring matching allowed. Names
   that matched only inside another word stop making a site, including a few
   that do run tests: `python -m django test`, `npx detox test`, `gmake
   test`, `ctest -R unittests`. They are candidates for the shared
   vocabulary (#216).
2. **Echo and heredoc text.** An `echo` or `printf` command is excluded
   whole, its words and its redirections. A heredoc body is excluded when
   `cat`, `tee`, `echo` or `printf` takes it. A heredoc fed to anything else
   (`bash <<EOF`, `python - <<EOF`, `ssh host <<EOF`) keeps its names, and so
   does a body whose unquoted delimiter lets it expand a command
   substitution.
3. **Install subcommands, as the ruling lists them.** pip counts in any
   spelling: `pip3`, `pip3.12`, a path to it, `python -m pip` and `uv pip`.
   npm counts with its own aliases of `install` and `ci`, never
   `install-test`, `it` or `cit`, which run the tests. Options may stand
   between the tool and its subcommand (`apt-get -y install`). Other
   installers keep their names (`uv tool install`, `uv add`, `pnpm add`,
   `yarn global add`, `gem install`), so the worst they cost is a false
   reason.
4. **Text that runs is never excluded:** a command substitution, a process
   substitution, output piped onward (`echo pytest | sh`) and output written
   into a process substitution.
5. **A shell comment is excluded too.** This goes beyond the ruling's list:
   no shell runs a comment. In cmd, a line that starts with `#` runs `#`,
   not the runner. The narrowing is the agent's; the maintainer approves or
   overrules it here.
6. **The lexer reads bash, and gives up when it cannot follow the text.**
   Its triggers are an unterminated quote, an unbalanced substitution or
   parenthesis, a `case` pattern, a heredoc inside a substitution or without
   its terminator, and nesting past 64. Every name in such text counts.
   Other shells are read with bash's rules: PowerShell spells `;`, `&&`,
   `|`, `#` and `echo` the same way, and where it differs (a backtick
   escape) the text usually fails to lex.
7. **A `uses:` step: exclusion only.** It is a site when its name names a
   runner, as before, and one of its `with:` inputs names one too. The input
   may be a key, with underscores read as word breaks (`tox_env`), or a
   value read as a command (`test-command: npm test`). Its text stays the
   `uses:` value, so a site that stays a site keeps its reason. An action
   whose name holds no runner is still not a site, whatever its inputs
   (`nick-fields/retry` given `command: pytest`): the ruling excludes and
   adds nothing. An action named for its runner, with no runner in its
   inputs, stops being a site, including `uses: ./.github/actions/pytest`.
   Reading a composite action's own steps belongs to #213.
8. **Pre-commit entries** are read with the same predicate.

**The echo decoy (191.8) closes.** A runner reworded and disabled beside a
new `echo pytest` step blocks, and so does a pytest hook whose entry becomes
`echo pytest`. A decoy that does run the runner (`pytest --version`) still
hides it, which row 112 keeps as a residual.

**Tests and fixtures.**
- New tests: `tests/test_runner_command.py`, and 18 in
  `tests/test_ci_control_flow.py`.
- New negative fixtures, each a v0.5.0 block:
  - `ci_install_step_if_false_neg`;
  - `ci_echo_step_if_false_neg`;
  - `ci_results_publisher_if_false_neg`;
  - `ci_runner_name_inside_word_neg`.
- New fixtures, `bypass: 112`, each a v0.5.0 pass:
  - `ci_reworded_runner_beside_echo_decoy_pos`;
  - `precommit_test_hook_echo_decoy_pos`.
- No existing fixture changes its expectation.

**Fingerprints.** Unchanged: a site that stays a site keeps its text, so
every finding that stays keeps its reason.

**Cost.**
- **v0.5.0 blocks that become passes,** for the next release guide. These
  are `if: false`, a push-only or `failure()` condition, or a dead trigger
  on a step or hook whose only runner name is:
  - an install argument;
  - `echo`, `printf` or heredoc text, or a comment;
  - part of another word;
  - in an action's name, with no runner in its inputs.

  Most were false reasons. The exceptions run a suite: `django test`,
  `detox test`, `gmake test`, `ctest -R unittests`, and an action named for
  its runner that takes no input naming it.
- **New blocks:** the echo decoy, in a workflow and in a pre-commit config.
- **Sweep:** the full history of attrs, click, flask, httpx, rich and
  starlette has 821 commits that touch a workflow or `.pre-commit-config.yaml`
  (1,130 file changes).
  - Neither engine reports a control-flow weakening on any of them, so no
    verdict changes.
  - 29 distinct step texts stop being sites and none becomes one. All 29 are
    install steps (`pip install tox`, `python -Im pip install tox-uv`, `uv
    pip install --system tox-uv`) or attrs's steps that echo `TOX_PYTHON`
    into the environment.
- **Verdict gate:** every one of its 180 cases keeps the verdict and the
  findings of a candidate built from `main`, so no case is relabelled.
- **Corpus:** no verdict, finding or IR changes for the 579 existing
  fixtures; the six new fixtures are this round's.
- **Time:** linear, and bounded by the reader's 1 MB. The worst case, one
  1 MB `run:` script of 50,000 simple commands, takes about 0.7 s per side,
  where the substring check took 0.06 s. Real steps are short.
- **Not measured:** workflows of JS projects beyond the unit tests; no JS
  repository is in the sweep (#212).

SPEC §4 gains no text in this round. The runner-site paragraph that names
this predicate is the spec.4-ci-runner-sites round, after the 191.x rounds.

The agent wrote this entry in the fix PR, as the rulings' X.doc-batch asks;
the maintainer approves it there.

## D-080 (2026-10-04): a trigger that never fires for a pull request is dead (#196 191.9, 191.2(d))

#181 decided whether a workflow can run on a pull request's commits from its
event names and a `push` trigger's branch filters. Two shapes stop a trigger
for every pull request and were not read:

- `types: [closed]` on `pull_request`;
- a path filter that leaves no file: `paths-ignore: ['**']`, or `paths`
  listing only negations.

With either one, the suite stopped running on pull requests while every
runner line stayed in place, and the diff passed at warn.

Rulings 196.191.9 (b, narrow) and 196.191.2 (d), in the one trigger-model
round the rulings ask for, as implemented:

- **191.9.** A `pull_request` or `pull_request_target` whose explicit
  activity `types` hold none of `opened`, `synchronize` and `reopened` is a
  dead event. `[opened]` alone stays a disclosed residual.
- **191.2(d).** A trigger whose `paths-ignore` holds `**`, or whose `paths`
  lists only negations, is a dead event. Path filters stay unevaluated
  against a diff's changed files, as (b) and (c) are declined.
- **The reason is the existing one.** A workflow whose suite only dead
  events could run reports "pytest is disabled (no trigger runs it on a
  pull request)", as when `pull_request` is dropped.

Readings the rulings leave to the implementation:

1. **Activity types.**
   - Without `types`, a trigger keeps GitHub's default (`opened`,
     `synchronize`, `reopened`) and is live.
   - An explicit list with none of the three is dead: `[closed]`,
     `[labeled]`, `[ready_for_review]`, `[labeled, ready_for_review]`.
   - A list that keeps any of the three is live, including `[opened]`,
     which runs on a pull request's first commit only.
   - An empty list, or a shape the reader does not take, keeps the trigger
     live.
2. **Path filters, read literally.** `paths-ignore` must hold `**` itself,
   and `paths` must hold patterns that all start with `!`. Other spellings
   that ignore every file (`**/*`, a list naming every top-level
   directory) are not read, and keep the trigger live.
3. **`pull_request_target` takes the path rule too.** The ruling names
   `push` and `pull_request`; `pull_request_target` honours the same
   filters. This is the agent's reading, and the maintainer approves or
   overrules it here.
4. **GitHub's behaviour, recalled.** Three facts were not re-read
   from GitHub's documentation, because docs.github.com is not reachable
   from the environment that wrote this round:
   - the default activity types;
   - that a `paths` filter needs a pattern without `!` to match anything;
   - that `paths-ignore: ['**']` matches every file.

   The fixtures pin the reading, not GitHub.

**Tests and fixtures.**
- New tests: 28 in `tests/test_ci_control_flow.py`.
- New fixtures, `bypass: 112`, each a v0.5.0 pass at warn:
  - `ci_trigger_types_closed_only_pos`;
  - `ci_trigger_paths_ignore_all_pos`;
  - `ci_trigger_paths_only_negations_pos`.
- Control: `ci_trigger_types_opened_only_neg`, the residual, at warn.
- No existing fixture changes its expectation.

**Fingerprints.** Unchanged: the round adds findings with an existing
reason and changes none.

**Cost.**
- **New blocks:** a trigger narrowed to activity types that never run on a
  pull request's commits, and a path filter that leaves no file, when no
  other event runs the suite on a pull request.
- **Sweep:** the full history of attrs, click, flask, httpx, rich and
  starlette has 821 commits that touch a workflow or
  `.pre-commit-config.yaml` (1,130 file changes).
  - Neither engine reports a control-flow weakening on any of them, and no
    runner site changes liveness.
  - The 701 workflow versions with an `on:` mapping hold 137
    `pull_request` path filters, 143 `push` path filters and no
    `pull_request` `types`. None of them ignores every path or lists only
    negations.
  - So the sweep shows that nothing else moves, not the new findings.
- **Verdict gate:** every one of its 180 cases keeps the verdict and the
  findings of a candidate built from `main`, so no case is relabelled.
- **Corpus:** no verdict, finding or IR changes for the 585 existing
  fixtures; the four new fixtures are this round's.

SPEC §4 gains no text in this round. Event reachability, with these
types and the all-paths filter, is part of the runner-site paragraph of
the spec.4-ci-runner-sites round, after the 191.x rounds.

The agent wrote this entry in the fix PR, as the rulings' X.doc-batch asks;
the maintainer approves it there.

## D-081 (2026-10-04): a control-flow reason claims only what is known (#196 191.7, 191.8)

Two reasons that #181's control-flow findings give said more than the
inventory shows:

- **A moved site.** A runner reworded as it is disabled (`pytest` ->
  `python -m pytest` under `if: false`) is found by the moved-site fallback:
  one live site fewer, one dead site more. The reason named only the parked
  command, "python -m pytest is disabled (if: false)". Text alone cannot
  prove the two are one site.
- **A removed hook.** When no hook entry ran a suite any more, the reason
  read "pytest is no longer run by any pre-commit hook". That is false when
  the entry was rewritten into a runner the vocabulary does not know yet
  (`hatch test`). A hook's id and name were never part of the decision, and
  stay out of it.

Rulings 196.191.7 (d) and 196.191.8 (d), as implemented. Both change only
what the reason of the same finding says, in the same function, and both
move its fingerprint, so they share one round:

- **191.8: identity stays text.** When the fallback fires, the reason names
  both commands: "pytest no longer runs, and python -m pytest is disabled
  (if: false)". With several commands stopped, it names the first in sort
  order, as it already did for the disabled one. A runner disabled as
  written keeps the one-command reason.
- **191.7: removal stays high, and ids and names are never evidence.** The
  reason is the ruling's own, "no pre-commit hook entry invokes a recognised
  test runner any more (was: pytest)", naming the first base-side entry in
  sort order. Closing the false-reason cases themselves (`hatch test`, `just
  test`, `poe test`, `pdm test`) belongs to the shared runner vocabulary
  (#216).

**Pins.** Five reason strings, in four tests of
`tests/test_ci_control_flow.py`, move, each a direct consequence of the
rulings:
- `test_precommit_hook_inventory_is_two_sided`;
- `test_the_runner_that_stopped_must_be_the_runner_that_was_parked`;
- two tests added by the 191.5 round (D-079), the echo decoy in a workflow
  and in a pre-commit config.

**Tests and fixtures.**
- New tests: two in `tests/test_ci_control_flow.py`, one with a reworded
  runner among several stopped commands and one with a hook that keeps its
  id while its entry runs no runner or moves to a remote repository. Both
  pin that the reason names the first command in sort order, not in file
  order.
- No fixture changes its expectation, and none is added: fixtures pin
  verdicts, and no verdict changes.

**Fingerprints** (for the X.release-and-fingerprints batch).
`CI_WORKFLOW_TOUCHED` keys a weakened file by its reasons, so both reworded
reasons change the fingerprint of every finding that carries one. In the
corpus there are three: `precommit_test_hook_removed_pos`,
`precommit_test_hook_echo_decoy_pos` and
`ci_reworded_runner_beside_echo_decoy_pos`. An allowlist entry for one of
these findings stops matching.

**Cost.**
- **Verdicts:** none change.
- **Sweep:** the 821 commits that touch CI files in the full history of
  attrs, click, flask, httpx, rich and starlette give no control-flow
  reason, so no fingerprint there changes.
- **Verdict gate:** every one of its 180 cases keeps its verdict and its
  findings' rules, severities and files against the candidate built from
  #247, so no case is relabelled.
- **Corpus:** the three fixtures above change their message, fingerprint
  and recorded reason, and nothing else.

The agent wrote this entry in the fix PR, as the rulings' X.doc-batch asks;
the maintainer approves it there.

## D-082 (2026-10-04): a CI file the reader can no longer read at head is out of reach (#196 191.3)

#181's control-flow reader takes a subset of YAML, and a file outside it was
left at warn on either side. A diff could take a workflow or
`.pre-commit-config.yaml` that ran a suite out of the reader's reach, and
then do anything to that suite: `if: !!bool false` on the test step, a YAML
tag on the hook's `stages`. Row 112 listed "YAML the bounded reader
declines" as a residual.

Ruling 196.191.3, option (b), as implemented:

- **The escalator.** A workflow or pre-commit config whose base side the
  reader read with at least one live runner site, and whose head side it
  declines, is high under its own escalator, `CI_BECAME_UNANALYSABLE` (SPEC
  §5 E8). It is not labelled a weakened command, which would be a false
  reason (option (d), declined).
- **The reason** rides on `ci_weakening_lines`, so the IR keeps its shape:
  "runner sites can no longer be read at head (a YAML tag); base ran:
  pytest". It names what the reader declined and the first live runner of
  the base side in sort order. `CI_WORKFLOW_TOUCHED`'s message labels only
  a reason that names a weakened command as "test command weakened".
- **Both escalators** apply when the same file also weakens a test command
  (`pytest || true` added beside the tag): E6 names that command, and E8
  says the rest is out of reach.

Readings the ruling leaves to the implementation:

1. **What "declines" means.** The reader declines YAML outside its subset,
   and a file over its 1000000-byte cap. Each decline now names what was
   declined: a YAML tag, tab indentation, a YAML directive, a second YAML
   document, a flow collection, a mapping key, an anchor or alias, a merge
   key, nesting depth, a quoted scalar, a block scalar or reserved
   indicator, or the size cap. A head side with nothing to read (empty, or
   only comments) is not declined, and neither is one the reader takes into
   a shape that is not a workflow (no `jobs` mapping) or a pre-commit config
   (no `repos` list): both stay unjudged, as before.
2. **A document end marker ends the document.** The reader read `...` after
   the document as a second document, and declined every workflow written
   `---` ... `...`, as attrs writes its workflows. In the six-repository
   sweep this was the only change whose base side ran a suite and whose head
   side the reader declined: attrs 36d6f83 (2022-09-26) adds `...` with a
   gate job. Without the fix, the escalator's one hit there is a false
   positive. It was a false negative too: `if: false` on the test step of
   such a workflow passed at warn, and now blocks. Only blank lines and
   comments may follow the marker; anything else is a second document.
3. **The reason is recognised by its words.** Gating and the message read
   a reason that begins "runner sites can no longer be read at head (" as
   this one. A line a diff adds that begins with those words, and that also
   swallows or narrows a runner, would carry `CI_BECAME_UNANALYSABLE`
   instead of `CI_TEST_COMMAND_WEAKENED`. The severity is the same.
4. **GitHub's YAML, not re-read.** Whether GitHub accepts YAML tags in a
   workflow was not verified, as the ruling notes; docs.github.com is not
   reachable from the environment that wrote this round. The escalation
   does not depend on it: a head side the reader declines is out of reach
   either way.

**Tests and fixtures.**
- New tests: 32 in `tests/test_ci_control_flow.py` (each named decline, the
  end marker, the reason and its precondition, the predicate, the message,
  and the escalators).
- New fixtures:
  - `ci_head_yaml_tag_pos` and `precommit_head_yaml_tag_pos` (`bypass:
    112`, v0.5.0 passes at warn): `CI_BECAME_UNANALYSABLE`;
  - `ci_step_if_false_document_end_marker_pos` (`bypass: 112`, a v0.5.0
    pass at warn): `CI_TEST_COMMAND_WEAKENED`;
  - controls at warn: `ci_document_end_marker_added_neg` (attrs 36d6f83's
    shape) and `ci_head_unreadable_without_live_runner_neg` (no live runner
    at base).
- No existing fixture changes its expectation.

**Fingerprints.** The new reason is part of `CI_WORKFLOW_TOUCHED`'s
fingerprint, so a finding that carries it has a new one. No existing
finding's fingerprint changes.

**Cost.**
- **New blocks:** a workflow or pre-commit config whose base side ran a
  live runner site and whose head side the reader declines, and a
  control-flow weakening in a workflow that ends with `...`.
- **Sweep:** the 821 commits that touch a workflow or
  `.pre-commit-config.yaml` in the full history of attrs, click, flask,
  httpx, rich and starlette (1,130 file changes) give no control-flow
  reason. Every file version the reader declined there (17, all ending with
  `...`) is read now, and none of them gives a reason.
- **Verdict gate:** every one of its 180 cases keeps its verdict and its
  findings' rules, severities and files against the candidate built from
  #248, so no case is relabelled.
- **Corpus:** the 589 existing fixtures keep their findings and IR; the five
  new fixtures are this round's.

SPEC §4's runner-site paragraph (the spec.4-ci-runner-sites round) names
this escalation too; this round adds one sentence to `CI_WORKFLOW_TOUCHED`
and the E8 row.

The agent wrote this entry in the fix PR, as the rulings' X.doc-batch asks;
the maintainer approves it there.

## D-083 (2026-10-04): a new pytest selector reaches a targeted run, and counts by what it can leave out (#196 184.1, 184.2)

#173's resolved collection inventory (#90, #184) judges a pytest config
change against the tests the base settings collect. It had two gaps in what
a new selector reaches and what it costs:

- **A run with explicit targets** (`pytest tests`) withheld the whole
  proof, because targets override testpaths. pytest still prepends the root
  config's addopts to such a run, so a first `addopts = "-m 'not slow'"`
  over a marked test passed in every repository whose CI names its tests
  directory.
- **An option that leaves no test out** blocked as a new selector: a first
  config's `-p no:cacheprovider`, or `--ignore=docs` with no tests in docs.

Rulings 196.184.1 (b) and 196.184.2 (b), shipped together as 184.1 asks, as
implemented:

- **184.1.** A targeted invocation no longer withholds the inventory. A new
  root-config selector is judged against the base-suite tests beneath its
  targets, when discovery from the targets finds the same root config on
  both sides. A run without targets still reaches the whole suite. The
  settings proof stays withheld whenever a run has targets, and every other
  withholding condition stands.
- **184.2.** A new option counts only when it can leave out a test that the
  governed runs collect. `-m`, `-k` and `--co` are not evaluated and count
  whenever such a test exists. `--ignore` counts by path prefix,
  `--ignore-glob` against each test's path and the directories above it,
  and `--deselect` by node-id prefix. `-p no:` counts unless the plugin is
  `cacheprovider`, `faulthandler`, `pastebin` or `stepwise`; `no:python`,
  `no:unittest` and every other plugin keep blocking.

Readings the rulings leave to the implementation:

1. **"A base-suite test beneath a target."** The suite is what the base
   settings collect, testpaths included. A test that only a targeted run
   collects, outside testpaths, does not count, so such a run is reached
   only through tests both would collect.
2. **"The same root config on both sides."** Discovery from the targets
   must find, on each side, the root config the inventory judges. A nested
   config at base or at head (a `tests/pytest.ini` the diff adds or
   deletes) withholds that run. Nested config files, `pytest.toml` and
   `.pytest.toml` included, are now read for this check only; the root
   config is still chosen among the root carriers as before.
3. **The plugin list.** Each plugin on it changes no collection and no
   outcome: `cacheprovider` keeps `--lf`/`--ff` state, `faulthandler` dumps
   tracebacks, `pastebin` uploads a report, and `stepwise` acts only under
   `--sw`. `no:warnings` is not on it: it drops `filterwarnings = error`,
   which can turn a failing test into a passing one. `no:doctest` drops
   doctests.
4. **Path options, read literally.** `--ignore=.` drops everything. A
   `--deselect` of one parametrized case of a suite test (`::test_x[1]`)
   counts as a loss. An absolute path names nothing in the inventory and
   counts as dropping nothing.
5. **The reported option** is the first in sort order among those that can
   drop a test. When a non-dropping option sorted first beside a selector
   (`--ignore=docs -m 'not slow'`), the message names the selector now.

**Tests and fixtures.**
- New tests: 144 in `tests/test_issue184_collection_selectors.py`, end to
  end through `engine.analyze` with a closed path inventory.
- No fixture: the golden runner supplies no path inventory, as for #90 and
  #173. No existing test or fixture changes its expectation.

**Fingerprints.** In a repository whose CI passes explicit targets, an
existing config that gains a selector now reports the inventory's line
("resolved pytest collection option introduced: ...") instead of the syntax
scanner's ("pytest collection option introduced: ..."): the same severity,
a new message and fingerprint.

**Cost.**
- **New blocks:** a first config's selector in a repository whose CI
  passes explicit targets, when a base-suite test lies beneath them.
- **New passes** (O1 to O3 in the rulings): a first config's option that
  leaves no test out, such as `-p no:cacheprovider`, or `--ignore=docs`
  with no tests in docs. The same option added to an existing config still
  blocks through the token scan and the syntax scanner, which do not
  evaluate it; this asymmetry is disclosed in row 105.
- **Sweep:** the 1,018 commits that touch `pytest.ini`, `.pytest.ini`,
  `pyproject.toml`, `tox.ini` or `setup.cfg` in the full history of attrs,
  click, flask, httpx, rich and starlette give the same inventory output on
  both engines. The one line either reports is click 3ded26d, whose
  `setup.cfg` gains `-p no:warnings`, and it still blocks. Twelve flask
  commits stop on a submodule on both.
- **Verdict gate:** every one of its 180 cases keeps its verdict and its
  findings' rules, severities and files against the candidate built from
  #249, so no case is relabelled.
- **Corpus:** unchanged; no fixture reaches the inventory.

This round also carries ruling 196.184.4's disclosure, which needs no code:
row 105 now lists a newly added workflow with no base CI surface, which can
carry a selector or exclude named existing tests at warn under SPEC's
first-adoption rule.

The agent wrote this entry in the fix PR, as the rulings' X.doc-batch asks;
the maintainer approves it there.

## D-084 (2026-10-04): a selector moved out of every run's command into the config is not new (#196 184.3)

#173's resolved collection inventory judges an option the root config gains
against the tests the runs it governs collect (D-083). It judged the config
alone. Moving `-m 'not slow'` from the workflow's `pytest -m 'not slow'` into
a first or an existing config's addopts reported "resolved pytest collection
option introduced: -m not slow" and blocked, although every run passed the
selector before and after (W1 and W3 in the rulings' probe; v0.4.2 and v0.5.0
both block them). SPEC §2b already says that moving a filtering addopts
between files is not a weakened test command, and the token scan and the
syntax scanner read such a move that way. The inventory did not.

Ruling 196.184.3 (c), as implemented:

- **A provably identical migration is quiet.** An option the config gains is
  not new when every base-side pytest command in the inventory's runner files
  carried it, and each runner file's head commands are its base commands with
  exactly the moved options removed.
- **Everything else is reported as before**, including a move this reader
  cannot prove.
- **How the files are read.** The proof reads each runner file on both sides:
  a GitHub workflow step by step (its `run:` texts), every other runner file
  line by line, with the option reader's own command split.

Readings the ruling leaves to the implementation:

1. **"Every base-side pytest invocation."** The move is unproven when a
   command may run a test runner (the runner-site predicate of 191.5) and is
   not a pytest command the option reader parses: `coverage run -m pytest`,
   `tox`, `make test`, a nox session, a step that runs a runner action, or a
   line that does not lex. It is also unproven for a `tox.ini` whose
   environments have commands, for pytest settings a runner file writes
   itself, and for `PYTEST_ADDOPTS`, `--override-ini` or ` -o ` on either
   side. A workflow step's name, a cache key or an install command that
   names pytest is not a run. A `tox.ini` that only configures pytest runs
   nothing.
2. **"Dropped exactly it."** Each runner file's head pytest commands, in
   order, equal its base commands with the moved options' words removed. The
   program, the targets, every other argument and every other command stay as
   they were. A run the diff adds, deletes or renames is not one that dropped
   the option. A base command that also drops an option the config does not
   gain leaves the move unproven, even though that drop broadens the run.
3. **Options move together.** The moved set is every option the config holds
   that every base command carried, whether or not it can leave a test out
   (`-p no:cacheprovider` beside `-m`). pytest keeps only the last `-m` and
   `-k`, so one of them moves only when the config holds no other value for
   it.
4. **The runner files are the inventory's own:** workflows, `scripts/`, shell
   and batch scripts, `Makefile`, `.gitlab-ci.yml`, `noxfile.py` and
   `tox.ini`. Runs defined elsewhere (another CI's configuration, a composite
   action, a reusable workflow) are outside this proof, as they are outside
   184.1's reach. Row 105 discloses both.

**Tests and fixtures.**
- New tests: 60 in `tests/test_issue184_collection_selectors.py`, end to
  end through `engine.analyze` with a closed path inventory. All 28 mutants
  of the new code are killed.
- No fixture: the golden runner supplies no path inventory.
- No existing test or fixture changes its expectation.

**Verdict gate.** Two cases, as #201 ruling 196.followup.new-gate-cases asks:
- `i196/W1`, labelled pass, with an fp-fix entry, because v0.5.0 blocks it;
- `i196/Wc1`, its two-invocation counter-case, labelled block.

`baseline_blocked` goes 75 -> 77. The FAMILIES pin goes i196 28 -> 30. That
assertion change rides on the existing exemption of PR #227, whose
fingerprint binds the assertion text and not FAMILIES (expires 2026-10-17).
No allowlist entry is added.

**Fingerprints.** Unchanged: the round removes findings and changes no
message.

**Cost.**
- **New passes:** W1 and W3, block -> pass on both tags. The stated reason is
  SPEC §2b, and the next release guide names them
  (X.release-and-fingerprints).
- **Sweep:** the 1,018 commits that touch a pytest config in the full history
  of attrs, click, flask, httpx, rich and starlette give the same inventory
  output as the candidate built from #250. The one line either reports,
  click 3ded26d's `-p no:warnings`, still blocks. No commit there moves a
  selector out of a runner command, so the sweep shows that nothing else
  moves, not the new passes.
- **Refactor:** the option reader's command split and option spelling now
  serve the proof too. On every blob that a commit in those six histories
  wrote at a CI or config path (2,761 blobs, 2,809 before/after pairs), the
  reader's options, argument lists, resolved settings and scanner reasons are
  identical before and after.
- **Verdict gate:** every one of its 180 existing cases keeps its verdict
  and its findings' rules, severities and files against the candidate built
  from #250. `i196/W1` goes block -> pass with its fp-fix entry, and
  `i196/Wc1` blocks on v0.4.2, v0.5.0 and the candidate.
- **Corpus:** unchanged; no fixture reaches the inventory.

The agent wrote this entry in the fix PR, as the rulings' X.doc-batch asks;
the maintainer approves it there.

## D-085 (2026-10-04): rulings that change words only - a manifest's test command, setup skips, runner sites and E6 (#196 183.1, 185.1, 185.2)

The 2026-10-03 rulings settled eight items that need no code. Three keep
shipped behaviour and disclose what it costs (183.1, 185.1, 185.2). Five are
SPEC proposals from #183, #184, #185 and #191 that were to wait for their
rulings or their rounds. This entry records them as applied.

**Shipped behaviour kept:**

- **185.1 (A): a manifest's narrowing base is its base-side test command.**
  #185 shipped this in v0.5.0: the narrowing base surface reads a manifest's
  base-side test command, not the whole file. SPEC §4 now says so in #185's
  words, and §2 says that a manifest contributes only its test command.
  - Cost (185.1b): a narrowing that only a non-test script carried at base
    blocks once the diff copies it into `test`.
  - Wiring that script into `test` unedited stays at warn
    (`runner_package_json_pulled_in_script_neg`).
  - Row 106 discloses the shape.
- **185.2 (A, permanently): a manifest's hop is bounded by where it starts.**
  SPEC §4's one-hop sentence splits:
  - A shell-script hop must end in a real runner.
  - A manifest hop takes whatever `test` or a `test:*` script names through
    a script runner, because `npm test` runs `scripts.test` whatever it says.
  - Cost (185.2b): an honest narrowing added to a build script that `test`
    calls reads as a weakened test command. It is unmeasured: no JS corpus.
  - A build script that only `prepublishOnly` calls stays production
    (`runner_package_json_prepublish_hop_neg`).
  - Row 106 discloses the shape.
- **183.1 (a): the high on a new always-skip conftest fixture stays.**
  - Row 104 now discloses the request side (#223): an existing test that
    starts requesting an existing conftest skip fixture passes with no
    finding, while the same request of a same-file skip fixture blocks.
  - Until #223 ships, the finding on the added fixture is the defence.
  - So an honest skip fixture added for new tests only blocks once, and can
    be allowlisted.

**SPEC proposals applied:**

- **spec.4-test-disabled.** TEST_DISABLED names an unconditional skip/xfail
  in the setup a unit runs, in the ruling's words. Guarded setup skips are not
  judged until the 183.2 round, which edits this wording again.
- **spec.4-ci-first-adoption.** The first-adoption warn describes the syntax
  scanner; the resolved collection inventory (§2b) still judges a first
  configuration when it runs. Row 105's "per SPEC §5" becomes §4.
- **spec.2-manifest-promotion.**
  - §2 gains a paragraph on `package.json` and `Pipfile`, and
    CI_WORKFLOW_TOUCHED gains "package manifests whose test command changed
    (§2)".
  - The ruling's batch with 197.Q1 and 197.Q2 did not happen: they landed in
    their own rounds. The membership rule (keys, runner-invoking scripts, the
    hop) needs more than one sentence, so it is its own paragraph after the
    runner-script one.
- **spec.4-ci-runner-sites.** CI_WORKFLOW_TOUCHED gains a condensed
  runner-site paragraph, the one D-079, D-080 and D-082 point to. It names:
  - the runner-site predicate, including `uses:` steps (191.5);
  - event reachability, with activity `types` and the all-paths filter
    (191.9, 191.2(d));
  - `needs:` propagation, and status functions read on a green run;
  - the disabled suite, including a reworded runner (191.8), and the
    pre-commit inventory, read by hook entries (191.7).

  It sits before the sentences that earlier rounds added: 191.3's
  escalation and 197.Q5's YAML-only workflow definition. Evaluator internals
  stay in the `ci_control_flow` docstring, and the residuals in row 112.
- **spec.5-e6.** E6's condition becomes "CI diff weakens the test command as
  defined in §4 `CI_WORKFLOW_TOUCHED`". The old condition listed five tokens;
  §4 has defined more than that for a long time (swallows, narrowings,
  collection syntax, make recipes, errexit, runner sites). 191.3's escalator
  already has its own row (E8, D-082).

**Not in this round:** spec.4-tolerance-loosened waits for 190.3.

**Verification.** No code, test, fixture, gate input or fingerprint changes.
On this branch's engine:
- 185.1b blocks (copied into `test`), and the wired control is warn.
- 185.2b blocks (a build hop), and the `prepublishOnly` control passes.
- #223's S1, S2 and S4 pass with no finding, and S3 blocks.
- A new conftest skip fixture that only a new test requests blocks with
  `<suite>` high.

The agent wrote this entry in the fix PR, as the rulings' X.doc-batch asks;
the maintainer approves it there.

## D-086 (2026-10-04): a body skip whose guard the diff removed is reported (#196 183.2, first stage)

THREATMODEL 54. `if sys.version_info < (3, 9): pytest.skip()` becoming
`if True: pytest.skip()` has reported "skip guard now always fires" since
T1.8: the edited guard can be evaluated, and it holds everywhere. Removing
the `if` instead left nothing to evaluate. The call keeps its name, so no
marker is added, and v0.4.2, v0.5.0 and `main` all pass a test whose skip
now fires on every run. The same holds for `pytest.xfail` and
`self.skipTest`, and for a skip moved out of its `except ImportError:`
block.

Ruling 196.183.2 (c) asks for this first: close guard removal, then judge
guarded setup skips like a body skip, with one guard definition shared with
#208 and #209. This entry is the first stage only.

**As implemented:** a body skip that ran only under a condition at base,
and runs under none at head, reports TEST_DISABLED "skip guard removed (was
'<condition>')". It joins the guard family (`guards_weakened`, shape
`guard_weakened`, fingerprint identity `guard:<call>`), so no marker
identity, IR field or recorded fingerprint changes.

Readings the ruling leaves to the implementation:

1. **"Ran only under a condition."** Two things count:
   - an `if` guard that does not hold everywhere under the base constants.
     An unevaluable guard counts, since it still ran the test somewhere.
   - an enclosing `except` block, because entering one needs an exception.
     The innermost block names the condition in the message.

   Every base instance of the call must have run under one. A unit that
   already skipped unconditionally at another site loses nothing that ran.
2. **"Runs under none."** At head, some instance of the call has no `if`
   guard and sits in no `except` block. A `with` body, a `try` body and a
   `finally` block run, so a skip there fires. Loop bodies and `match` cases
   record no condition, so a skip moved there reads as unconditional.
3. **The calls:** `pytest.skip`, `pytest.xfail` and `self.skipTest`, whose
   recorded guard D6 already reads as their condition.
   `pytest.importorskip` is conditional by itself. Aliased and raised
   spellings are not read in a test body at all (#220).
4. **A second skip beside the guarded one.** Markers count as a multiset,
   so a new bare `pytest.skip()` added beside a guarded one is a marker
   added. It stays on that path, and is not also reported as a removed
   guard.

**Tests and fixtures.**
- **Tests:** 27 in `tests/test_issue196_guard_removal.py`, end to end
  through `engine.analyze`. All 12 mutants of the new code are killed.
- **Fixtures:**
  - pinning row 54: `skip_guard_removed_pos`, `skiptest_guard_removed_pos`
    and `skip_moved_out_of_except_pos` (`bypass: 54`). Each blocks here and
    passes with no finding on v0.4.2, v0.5.0 and #252.
  - controls: `skip_guard_into_except_neg` and
    `skip_always_true_guard_removed_neg`, which pass with no finding on all
    four engines.
  - No existing fixture or test changes its expectation.

**Fingerprints.** A finding of the new kind has the guard family's
existing identity. No existing finding's fingerprint changes.

**Cost.**
- **New blocks:** the three fixture shapes, without repair evidence. With a
  production change beside them, they hold at warn like any disable.
- **Residual:** recorded in row 54.
  - A skip moved into a loop body or `match` case reads as unconditional.
  - A qualified version or platform gate left on the same unit holds the
    finding at warn, because D6 grants COMPAT_GATE per unit (#208).
- **Sweep:** the last 300 non-merge commits of attrs, click, flask, httpx,
  rich and starlette (1,800 commits) give this round's engine the same
  verdicts and findings as the candidate built from #252, with 48 blocked
  commits on both. The new rule reports none of them, so the sweep shows
  that nothing else moves, not the new finding.
- **Verdict gate:** every one of its 182 cases keeps its verdict and its
  findings' rules, severities and files against the candidate built from
  #251, whose code #252 does not change, so no case is relabelled. Ruling
  196.followup.new-gate-cases names no case for 183.2.
- **Corpus:** the 594 existing fixtures keep their findings and IR; the five
  new fixtures are this round's.

**Next stages of 183.2:** first the guard on `setup.<provider>.<effect>`
markers (same-file fixtures and xunit setup), judged like a body skip.
Then conftest fixtures, after #223. Both share one guard definition with
#208 and #209.

The agent wrote this entry in the fix PR, as the rulings' X.doc-batch asks;
the maintainer approves it there.

## D-087 (2026-10-04): a guarded skip in a unit's setup carries its guard, and is judged as a body skip is (#196 183.2, second stage)

THREATMODEL 104 and 54. A same-file fixture or xunit setup callback whose
skip runs only under a condition minted no marker at all. Its guard was its
justification, so the shipped default read nothing. A test that newly
requested `if not os.environ.get("DB"): pytest.skip()` passed with no
finding, and so did a fixture whose version gate was edited to one that
always holds, or whose `STRICT` constant flipped. v0.4.2, v0.5.0 and #253
pass all three.

Ruling 196.183.2 (c), after its first stage (D-086): record the guard on
`setup.<provider>.<effect>` unit markers (same-file fixtures, xunit setup),
judged exactly like a body skip; conftest fixtures wait for
196.followup.conftest-request-side; one guard definition is shared with
#208 (COMPAT_GATE per marker) and #209 (guarded conftest hooks).

**As implemented:** `setup_skip_controls.setup_outcome` reads a unit's own
setup callback. The outcome every call reaches (`callback_outcome`) gives the
marker #172 recorded, unchanged, with no guard. Otherwise each outcome a
call reaches whenever its path condition holds counts, and the marker's
guard is the disjunction of those conditions. The marker keeps its name, so
the identities #172 recorded do not move. The guard is judged by the same
code as a body skip's: D6 (`_marker_is_compat_gate`), liveness
(`unit_is_live`), a guard that now always holds (`guards_weakened`) and a
guard removed (`removed_skip_guard`). A guard finding says "in the setup
this test runs" and names the marker.

Readings the ruling leaves to the implementation:

1. **The guard definition.** The condition on the path to the outcome:
   - each enclosing `if` test, and `not (...)` for an `else` branch;
   - `not (...)` for the code after a branch that always ends (an outcome,
     `return`, `raise` or `yield`), the `--runslow` shape #209 names;
   - an `except` block's own condition, as a conftest's `collect_ignore`
     records it (`_handler_guard`: `find_spec("numpy") is None` for an
     import-only `try`, else `except <type>`, which earns nothing that needs
     it parsed).

   Several outcomes join with `or`, so two branches that between them cover
   every run read as the unconditional skip they are, wherever the guard can
   be evaluated. This is the definition #209's hook reading is to share: it
   is written over statements, not over fixtures.
2. **What the reading does not follow.** As `callback_outcome` does not,
   it reads no loop, `with` or `match` body and no `try` body. A path that
   may leave without always leaving (a `return` under a second `if`, a loop
   that may return) ends the reading instead of widening a guard, so those
   shapes still mint nothing.
3. **Judged exactly like a body skip.** An interpreter or OS gate holds a
   newly reached setup skip at warn (COMPAT_GATE). Any other guard (an
   environment variable, an optional import, a feature flag) blocks, as the
   same guard in the body does. A guard edited to one that always holds, a
   flipped constant, a guard removed and a skip moved out of its `except`
   block are reported with the guard family's `guard:<marker>` identity.
4. **#208.** D6 judges each marker by its own guard, which is what #208's
   per-marker hold will call, but the hold is still granted per unit. A
   setup gate therefore lends it to another new disable on the same unit,
   as any gate does today. It adds no capability: #208's U5 already passes
   a `skipif(sys.platform == "win32")` added beside the `skip`. The
   residual is pinned by a test and named in row 104.

Conftest fixtures and a `pytest_runtest_setup` hook still read only the
unconditional outcome.

**Tests and fixtures.**
- **Tests:** 62 in `tests/test_issue196_setup_guards.py`. All 26 mutants
  of the new code are killed.
- **The ruled move:** the guarded-environment case of
  `test_guarded_teardown_or_environment_skips_mark_nothing` moves into
  `test_a_guarded_setup_skip_marks_the_unit_with_its_guard`, because the
  ruling records it. It is the one existing expectation this round changes,
  under the TEST_DISABLED exemption that #255 adds, which the owner approved
  on 2026-10-04.
- **Fixtures:**
  - pinning row 54: `setup_guard_removed_pos`, `setup_guard_always_true_pos`;
  - pinning row 59: `setup_guard_constant_flip_pos`;
  - pinning row 104: `setup_env_guard_requested_pos`;
  - control: `setup_platform_gate_requested_neg` (warn, COMPAT_GATE).

  The four blocking fixtures block here. v0.4.2 passes them all; v0.5.0 and
  #253 block only `setup_guard_removed_pos`, as a skip added to the setup.
  No existing fixture changes its expectation.

**Fingerprints.** A guard removed from a unit's setup was reported by v0.5.0
as a skip added to the setup (`setup.<provider>.<effect>`), because the
guarded side minted no marker. It now has the guard family's
`guard:setup.<provider>.<effect>` identity, as a removed body guard does: a
recorded allowlist entry for that shape needs re-recording, and the next
release guide names it (X.release-and-fingerprints). Every other finding of
this round is new.

**Cost.**
- **New blocks:** a guarded setup skip that an existing test newly reaches,
  or that is added to a setup it already runs, unless the guard is an
  interpreter or OS gate. An optional-dependency gate blocks, as it does in
  the body.
- **Sweep, standard:** this round's engine gives the same verdicts and
  findings as the candidate built from #253 on two sets:
  - the last 300 non-merge commits of attrs, click, flask, httpx, rich and
    starlette (1,800 commits);
  - the 104 commits in their full histories that change a test file holding
    both a setup callback and a skip token (attrs 25, flask 75, starlette 4;
    15 flask commits fail on both engines).

  None of these commits reaches a guarded setup skip.
- **Sweep, targeted:** so the round was measured where it applies. The full
  histories of six more repositories were filtered to the commits where a
  changed test file carries a setup marker on either side under this round:
  uvicorn 16, werkzeug 18, scrapy 55, pytest 32, aiohttp 21, requests 0.
  Neither engine reads aiohttp (a git submodule), and 9 scrapy and 3 pytest
  commits fail on both. Five verdicts move from pass to block.
  - Three disable nothing:
    - werkzeug `551885fd` (3 findings): the redis and memcached test
      classes, defined only when their package imported, move into a class
      fixture that skips, so the skip becomes visible;
    - scrapy `526585393` and `f46a45008` (5 and 19 findings): an abstract
      test base whose `setUp` skips on a class attribute that is `None`.
      The guard reading does not resolve class attributes (#254).
  - Two stop tests in one environment, for a reason the commit states. The
    same guard in the body blocks too:
    - scrapy `7327145bf` (3): the pinned tox environment stops installing
      mitmproxy, and `setUp` skips without it;
    - pytest `f573b56bb` (2): a fixture skips when chmod cannot make the
      cache directory unwritable, as under root, in place of `skipif(win)`.
- **Already-blocked commits:** five gain findings.
  - uvicorn `25208ee`: 12 high, from a fixture that skips when an optional
    reloader is missing.
  - scrapy `6b2997af90`: 3 high. An import-guarded skip carried from
    `setUp` to `setup_method` reads as added, because a setup marker names
    its provider, as #172's markers do.
  - scrapy `d825133284`: 2 warn, from a setup platform gate (COMPAT_GATE).
    By #208's lending, the same gate holds a body `pytest.skip` at warn
    instead of high.
  - scrapy `7bbe775040` and `380c2279b9`: liveness. A unit added beside a
    disappeared one no longer covers it when it carries a guarded setup
    skip that is not a gate, so the disappearance goes from warn to high.
    The same effect raises a disappearance in `526585393` (warn to high),
    and two disappearances and a removed assertion in `f46a45008` (info to
    high).
- **Verdict gate:** every one of its 182 cases keeps its verdict and its
  findings' rules, severities and files against the candidate built from
  #253, so no case is relabelled. Ruling 196.followup.new-gate-cases names
  no case for 183.2.
- **Corpus:** the 599 existing fixtures keep their findings and IR; the five
  new fixtures are this round's.

**Maintainer decision (2026-10-04).** After this sweep, the maintainer kept
the ruling as written: a guarded setup skip is judged as a body skip. The
alternative was a narrower variant that would hold a newly reached non-gate
setup skip at warn and leave liveness alone. #254 takes the class-attribute
shape, for body and setup skips alike.

The agent wrote this entry in the fix PR, as the rulings' X.doc-batch asks;
the maintainer approves it there.

## D-088 (2026-10-04): D6 judges the marker a finding reports, and a conftest collection hook carries the condition it acts under (#208, #209 Q1, Q4)

THREATMODEL 115 and 116, and the `--runslow` false positive. Two defects of
one family, ruled to land together.
- **#208.** D6 judged the unit, not the finding: one qualified marker on a
  unit held every `TEST_DISABLED` finding on it at warn. A version gate on
  `collect_ignore` therefore lent its hold to a hook added beside it that
  dropped tests, and a test's `skipif(sys.platform == "win32")` lent it to a
  `@pytest.mark.skip` added above it. All twenty members (S1-S12, U1-U8)
  pass on v0.4.2 and v0.5.0.
- **#209.** A `pytest_collection_modifyitems` or `pytest_ignore_collect`
  hook, and an `add_marker(<skip>)` call, carried no guard, so pytest's own
  `--runslow` recipe blocked at high on every build since M0, while the same
  condition on `collect_ignore` held at warn. The suite-control rule also
  read only whether a guard was recorded, so `if sys.version_info >= (3, 0):`
  around a `collect_ignore` drop bought repair evidence from an opaque
  production edit (N1).

Rulings, 2026-10-04:
- **208.Q1:** a finding with no marker of its own never gets `COMPAT_GATE`;
  it is granted only when every after-side marker with the finding's name
  qualifies on its own guard.
- **208.Q2:** a new THREATMODEL row (115); row 71 stays closed for its shape.
- **209.Q1:** a suite-level control earns `COMPAT_GATE` on its own guard,
  whatever its spelling, when that guard can be false, landing with #208's
  rule and never before. The guard is the path condition 183.2 reads (D-087,
  reading 1); the weakest guard across a hook's effects counts.
- **209.Q4:** an **unguarded** suite-level control is not de-escalated by
  repair evidence, and unguarded means no guard that can be false.

**This amends D-028.** Its second fix skipped the compat-token filter "for
`conftest.collect_ignore` specifically". The filter is now skipped for every
suite-level collection control a conftest mints: `collect_ignore`, the two
collection hooks, and an `add_marker` skip in one. Its first fix refused
repair evidence to an unguarded control; unguarded now means a control with
no guard that can be false.

**As implemented:**
- `compat.compat_gate_for` judges the markers with the finding's name,
  `test_disabled.finding_marker` reads that name back from the finding's
  fingerprint, and gating asks it in place of the unit.
- `frontends/python/hook_guards.py` reads each collection hook and records
  its guard on the hook's marker and on each `add_marker` skip in it.
- `compat.guard_can_be_false` is D6's evaluator turned around. Gating's
  suite-control rule asks it of the finding's own control.
- `compat._SUITE_GATES` lists the controls that qualify on their own guard. A
  test keeps it equal to the names the frontend mints.

Readings the rulings leave to the implementation:

1. **A hook's guard.** D-087's path condition: every enclosing `if` test,
   `not (...)` for an `else` and for the code after a branch that always
   ends, and an `except` block's condition. Two readings are particular to
   hooks.
   - Loop bodies are read, because a hook's effects sit in
     `for item in items:`. `continue` and `break` end an iteration.
   - A conjunct is kept only when it names nothing but module-level names,
     reading builtins, `config` or `session` (unless the hook rebinds them),
     and locals bound exactly once, by one plain assignment from those. Such
     a local is replaced by its value, so `GATE = True` / `if GATE:` reads
     as `True`. A condition that names an item selects items and is dropped.
     `and` is split first, so the environment half of
     `not os.environ.get("NETWORK") and collection_path.name == ...`
     survives.
2. **What an effect is.** Ruling 209.Q2 waits for its own round, but its
   rule that an effect checkwash cannot read still counts decides this one:
   an effect is anything the reading cannot show to be inert.
   - Inert: binding or deleting a plain local name, `pass`, `break`,
     `continue`, an import, a `return`, `raise` or `assert` of inert
     expressions, and an expression whose every call only reads. A call
     reads when it is a reading builtin, an environment or mark call named
     by its import (`os.environ.get`, `importlib.util.find_spec`,
     `pytest.mark.skip`, ...), or a reading method (`getoption`,
     `get_closest_marker`, `startswith`, `get`, ...).
   - The test of an `if` or `while`, a loop's iterable and a `match` subject
     are read where they are evaluated. A `with` is always an effect,
     because its context manager runs code, and its body never ends the
     path, because that code can swallow an exception.
   - In `pytest_ignore_collect`, a `return` of anything but `None` or
     `False` is an effect whose value is part of its condition.

   The first cut listed effects instead (a write to `items`, a call on it,
   `add_marker`, ...). A review before it was committed found spellings it
   missed beside an honest guarded effect, each of which would have given a
   dropping hook the honest effect's guard. Among them: `items.clear()` in
   an `if` test or a loop's iterable, `session.items.clear()`,
   `getattr(items, "clear")()`, `map(items.remove, ...)`, a name bound to
   the list by unpacking, `return items.clear()`, a nested definition's
   default or decorator, a `with` that swallows a `raise`, a local rebound
   by a loop or a walrus, and a rebound `config`. All are pinned in
   `tests/test_issue208_209_suite_guards.py`.
3. **The weakest guard, per name.** `_conftest_unit` combines the guards of
   every control of one name: none if any has none, else their disjunction.
   Two definitions of one hook, or `add_marker` skips in two hooks, are
   judged together, as row 71 judges `collect_ignore`. An `add_marker` skip
   outside a collection hook has no guard.
4. **Can be false.** `guard_can_be_false` is `not guard_always_skips`, so the
   parts checkwash cannot evaluate stay unknown, as in D6. An `except`
   block's condition that is not an expression (`except ValueError`) still
   counts as a guard for repair evidence, as it always has for
   `collect_ignore` (row 83). It earns no `COMPAT_GATE`, which needs it
   parsed.
5. **Unguarded, per finding.** The suite-control rule asks about the
   finding's own control, not every control the diff added on the unit. A
   finding with no marker of its own reports a guard that now always
   fires, or a path added to an unguarded `collect_ignore` (row 81).
   Either way its control acts everywhere, so it is unguarded. A `<suite>`
   unit that disappeared is no control, as before. Removing the guard of
   an existing suite-level control is no event at all (row 116's
   residual): the ignored paths stay the same.
6. **Not in this round.** These form the next #209 round:
   - 209.Q2: a hook with no effect is not a control. Until then, such a
     hook reads as unguarded and blocks, as before.
   - 209.Q3: a conftest `pytestmark`, reported at info.
   - X1: `pytestmark = skipif(...)` read as its call.
   - Reporting a guard removed from a suite-level control, or an
     unguarded effect added to a guarded hook (row 116's residual).

**Tests and fixtures.**
- **Tests:** 83 in `tests/test_issue208_209_suite_guards.py`. All 44
  mutants of the new code fail them or the fixtures. Two CLI tests in
  `tests/e2e/test_cli.py`: the `--runslow` recipe holds at warn (B1), and a
  gate lends nothing to a drop hook (S1). Both fail on `main`.
- **Fixtures, #208 (row 115):** S1, S3 (two findings), S5, S7, S10 (the
  gate's own finding stays warn `COMPAT_GATE`; the hook's is high), S11, U1,
  U3, U6, U7 and U8, all high, and the control H2 (warn `COMPAT_GATE`). All
  eleven pins pass on `main`.
- **Fixtures, #209:**
  - negatives: B1 (the recipe verbatim), B2, B6, B7 and the environment
    guard on `pytest_ignore_collect`, all warn `COMPAT_GATE`; and B9, warn
    `REPAIR_EVIDENCE`. All six block on `main`.
  - pins of row 116, all high: an always-true guard (B5, and `if True:` on
    `pytest_ignore_collect`), mixed guards, an early return that never
    happens, an effect in an `if` test, and N1. N1 passes on `main`.

Every existing fixture keeps its expectation, including the eleven that
earn `COMPAT_GATE` today, and so do the two CLI tests that assert it.

**Two residual pins move.** Two tests pinned the per-unit hold as #208's
residual (D-087, reading 4). Ruling 208.Q1 closes it, as its costs foresaw,
so each now pins the closure under a name that says so:
- `test_issue196_guard_removal.py`: `test_an_honest_gate_beside_it_holds_it_at_warn`
  becomes `test_an_honest_gate_beside_it_lends_it_nothing`. The verdict goes
  from pass to block, and the removed guard's finding from warn
  (COMPAT_GATE) to high.
- `test_issue196_setup_guards.py`:
  `test_residual_an_os_gate_in_setup_lends_its_credit_to_the_unit` becomes
  `test_an_os_gate_in_setup_lends_nothing_to_another_disable`. The new skip
  blocks.

This project's own check reports both edits: the first as two
EXPECTED_VALUE_CHANGED findings at high, which ride on two base-side
exemptions in their own pull request, approved by the owner on
2026-10-04; the second at warn.

**Fingerprints.** None move. A marker's name is its identity, and its guard
is not part of it. The findings this round changes keep their fingerprints
and change only their severity and de-escalators.

**Cost.**
- **New blocks:** a disable that borrowed a gate's hold from another
  marker on its unit (#208), and a suite-level control whose guard always
  holds beside an opaque production edit (#209 N1).
- **New passes, at warn:** a collection hook or `pytest_ignore_collect`
  whose effects run only under a guard that can be false.
- **Sweep, standard:** the last 300 non-merge commits of attrs, click,
  flask, httpx, rich and starlette (1,800 commits) give the same verdicts
  and findings as `main`'s engine.
- **Sweep, targeted:** every commit in the full histories of those six
  repositories, and of uvicorn, werkzeug, scrapy and requests, that
  changes a `conftest.py` or a line with `skip` or `xfail` in a test file:
  895 commits, 855 of them readable by both engines. Neither engine reads
  aiohttp (a git submodule). pytest's own history has 1,559 such commits,
  at about 20 seconds each; its sweep takes the 368 that touch a
  collection control in a conftest or a skip or xfail decorator in
  `testing/`, 364 of them readable. Three verdicts move:
  - **block to pass:** scrapy `e8b1e46e85` adds pytest-flake8, with a hook
    that keeps only the flake8 items when `--flake8` is given. Its effect
    runs only under that option, so it holds at warn (COMPAT_GATE). A normal
    run disables nothing.
  - **pass to block:** scrapy `308a58aa27` adds
    `skipif(twisted_version == Version('twisted', 21, 2, 0))`, for a linked
    Twisted bug, to three tests that already carried `skipif` gates on PyPy
    and on Windows. Those gates lent it their hold. On its own the new
    marker names a dependency's version, which D6's interpreter/OS filter
    has never credited, so its three findings are high. This is the ruled
    behaviour (208.Q1).
  - **pass to block:** pytest `642cd86dd1` adds an unconditional
    `@pytest.mark.skip(reason="creates random tmpdirs as part of a system
    level test")` above two tests that carry
    `skipif(sys.platform.startswith("win"))`. That is #208's U1 shape: the
    two tests stop running everywhere, and the platform gate no longer lends
    them its hold.
- **Already-blocked commits:** these keep their verdict, and findings that
  a gate on the same unit held at warn are now high:
  - attrs `3843452516`: two parametrize rows deleted, as a `parametrize`
    moves into a fixture;
  - flask `61fbae8664`: three units under a new module `importorskip`;
  - scrapy `d825133284`: a body `pytest.skip`, the lending D-087 named;
  - werkzeug `5944de46ad` (a body `importorskip`) and `3638d0ec59` (a
    parametrize row deleted).

**Verdict gate.** It passes, with 0 failures. Every one of its 182 cases
(156 T1, 26 T3) keeps the verdict and the findings' rules, severities and
files of the candidate built from `main`, so no case is relabelled.

The agent wrote this entry in the fix PR, as the rulings' X.doc-batch asks;
the maintainer approves it there.

## D-089 (2026-10-05): only an effect makes a collection hook a control, a conftest `pytestmark` is reported at info, and a module `pytestmark` is read as its call (#209 Q2, Q3, X1)

The rest of #209, after D-088 (Q1, Q4). Three false positives, each the
same mistake: a line was judged by where it sat, not by what it did.
- **Q2.** D-088's hook reading counted every statement that changes
  something as an effect. So a `pytest_collection_modifyitems` that only
  sorted its items, or only marked them `pytest.mark.timeout(30)`, was a
  suite-level control and blocked at high, and withheld the collection
  inventory (#199).
- **Q3.** A `pytestmark` in `conftest.py` was listed as a suite-level
  collection control. pytest does not collect `conftest.py` as a test module,
  so it never reads the mark there: on pytest 9.1.1 the line disables nothing.
  It blocked at high (#209 B3) and withheld the inventory.
- **X1.** A module `pytestmark` mark was recorded with the whole assignment as
  its text. D6 reads a `skipif` condition by parsing the marker's text as a
  call, and `pytestmark = ...` never parses as one. So
  `pytestmark = pytest.mark.skipif(sys.platform == "win32")` blocked at high,
  while the same `skipif` as a decorator held at warn (#209 X2).

Rulings, 2026-10-04:
- **209.Q2:** only a hook's effects count. An effect is anything that can drop
  or disable an item: a write to `items` that is not a pure reorder, a call
  to `config.hook.pytest_deselected`, an `add_marker` of a skip or xfail, and
  `return True` from `pytest_ignore_collect`. A hook whose only effects are a
  reorder or a mark that is neither skip nor xfail is not a control. An
  effect checkwash cannot read still counts.
- **209.Q3:** report a conftest `pytestmark` at info. SPEC §2b's list of
  collection controls drops it and says so.
- **X1** has no question of its own. The issue's direction, step 2, brings the
  frontend in line with SPEC §4, which counts the module's `pytestmark` as a
  skip marker, and with §5 D6, which holds an added interpreter or OS
  `skipif` at warn.

**As implemented:**
- `hook_guards._Hook.benign` recognises the two kinds of statement that
  change something and can neither drop nor disable an item.
  `collection_hook_guards` leaves out a hook that has no other effect, and
  `_conftest_unit` mints no marker for it.
- `conftest_controls.is_collection_control` answers for the collection
  family alone, so a conftest's skip mark no longer withholds the inventory.
- TEST_DISABLED reports a skip mark on a conftest's `<suite>` unit with the
  shape `inert_mark`. Gating sets it to info and nothing escalates it.
- `_pytestmark_markers` records each mark with its own call's text and span,
  as `_decorator_markers` does.

Readings the rulings leave to the implementation:

1. **A reorder** is `items.sort(...)` or `items.reverse()` on the list pytest
   passes, `items[:] = sorted(items, ...)`, `items[:] = reversed(items)`, or
   either inside `list(...)`. The list is the hook's `items` parameter, and a
   hook that binds the name itself anywhere reorders something else. A `key`
   must be a function that only reads (a lambda whose body only reads, or a
   reading builtin), because `sort` calls it on every item, and `reverse=`
   must only read. Any other rewrite of the list is an effect, including
   `random.shuffle(items)`, which checkwash cannot read as a reorder, and a
   slice of part of the list.
2. **A mark that only labels an item** is the one argument of an
   `add_marker` call: a mark built from pytest's `mark` by its import
   (`pytest.mark.timeout(30)`, `from pytest import mark`), a mark name as a
   string, or a local bound once to either. Its arguments, the receiver and
   an `append=` keyword must only read. A mark whose name contains `skip` or
   `xfail`, in upper or lower case, disables an item, so a plugin's
   `skip_on_windows` does too. So does `usefixtures`, which runs a fixture
   at setup, and pytest-dependency's `dependency`, which skips on another
   test's outcome.
   *Residual:* a label can still be read by code that acts on it, such as a
   plugin or a runtime hook the conftest already has. Such a hook is a
   control of its own when a diff adds it.
3. **A hook with no effect** is not a control: no marker, no finding, and no
   withheld inventory. A hook's guard is still the weakest across its
   effects, and a reorder or a label beside them changes nothing.
4. **A conftest `pytestmark`.** Each skip or xfail mark in it gets an info
   finding:
   - rule TEST_DISABLED, message "pytestmark added to conftest.py, which
     pytest does not collect as a test module: it disables nothing";
   - its fingerprint is unchanged;
   - nothing escalates it: not an oracle freeze, and not the suite-control
     rule that refuses repair evidence.

   A mark that is neither skip nor xfail is not read, as before.
5. **A module `pytestmark` mark.** It records its own call's text and span. D6
   resolves the module constants its condition names, as for a decorator
   (`evidence._gate_condition_names` now finds them).
6. **Not in this round:**
   - the `pytestmark` spellings checkwash does not read at all: in a class
     body, under an `if`, `try` or `with`, annotated, `+=`, `.append`,
     unpacked or bound by name (#260);
   - a guard removed from an existing suite-level control (#261, row 116's
     residual).

**Tests and fixtures.**
- **Tests:** 89 in `tests/test_issue209_effects_pytestmark.py`. All 37
  mutants of the round's code fail them or the fixtures. 12 in
  `tests/test_issue199_collection_controls.py`: a conftest `pytestmark`, an
  ignore-collect hook that returns `False`, a sort-only hook and a labelling
  hook no longer withhold the inventory.
- **Three existing tests change**, as the rulings foresaw:
  - `test_collection_controls_are_the_spec_list`: the expected controls lose
    the skip marks (Q3).
  - `test_collection_controls_still_withhold`:
    - its `pytest_ignore_collect` returned `False`, which is no longer a
      control (Q2), so it now returns
      `collection_path.name == "test_legacy.py"`;
    - its conftest `pytestmark` case moves to the new
      `test_what_disables_nothing_never_withholds` (Q3).
  - `test_an_ignore_collect_hook_acts_by_returning_true`: its
    `"return False"` row pinned that hook as an unguarded control, and now
    expects none.

  checkwash on this branch reports one of them, the spec-list test, with two
  findings at warn: EXPECTED_VALUE_CHANGED and
  EXPECTATION_DEFINITION_CHANGED, both held by repair evidence. None needs
  an exemption.
- **Fixtures:**
  - negatives: `conftest_hook_sort_only_neg` and
    `conftest_hook_label_marker_neg` (no finding);
    `conftest_pytestmark_env_guard_neg` (#209 B3, one info finding); and
    `pytestmark_skipif_platform_neg` (X1, warn `COMPAT_GATE`). All four block
    on #259's head.
  - positive: `pytestmark_skipif_always_true_pos`, high, as on #259's head.

Every existing fixture keeps its expectation.

**Fingerprints.** None move. A marker's name is its identity, and none
changes. A `pytestmark` finding's evidence now shows the mark's call, not the
whole assignment. So the corpus record of `pytestmark_skip_pos`, the one
existing fixture with a `pytestmark`, changes in that text and in its span's
start, and in nothing else.

**Cost.**
- **Newly passing, at warn:** a module `pytestmark` whose `skipif` or
  non-strict `xfail` condition D6 qualifies (X1).
- **Newly passing, with no finding:** a collection hook whose only effects
  are a reorder or a labelling mark, and a `pytest_ignore_collect` that never
  returns true (Q2).
- **Newly passing, with an info finding:** a conftest `pytestmark` (Q3).
- **Newly blocking:** a collection hook that only labelled its items, and so
  was no control, when a diff gives it an effect checkwash cannot read. On
  #259's head the label already made the hook a control, so the new effect
  was no event at all.
- **Sweep, standard:** the last 300 non-merge commits of attrs, click,
  flask, httpx, rich and starlette (1,800 commits) give the same verdicts
  and findings as #259's head.
- **Sweep, targeted:** D-088's sets, which are:
  - the 895 commits of ten full histories that change a `conftest.py` or a
    `skip`/`xfail` line in a test file (855 readable);
  - the 368 of pytest's own history that touch a collection control in a
    conftest or a skip or xfail decorator in `testing/` (364 readable).

  Three verdicts move:
  - **block to pass:** scrapy `be514d8c5d` adds a hook that only marks the
    `requires_internet` tests `flaky(reruns=2, reruns_delay=5)` (Q2).
  - **block to pass:** pytest `dcafb8c48c` adds an example conftest whose
    `pytest_ignore_collect` returns `False` (Q2).
  - **pass to block:** scrapy `4ab7cf3df8` adds
    `items[:] = _interleave_evenly(items, _is_subprocess_heavy)` to that
    same hook. The conftest helper interleaves subprocess-heavy tests among
    the others: an honest reorder, but checkwash cannot read the helper as
    one, so it counts as an effect (209.Q2). The hook, which only labelled
    items before, becomes a control. This is the ruled behaviour.
- **A finding moves, verdict unchanged:** attrs `49ec7317c8` adds
  `pytestmark = pytest.mark.skipif(sys.version_info < (3, 7))` to
  `tests/test_pyright.py`. That finding goes from high to warn (X1), and the
  commit still blocks on its other findings.

**Verdict gate.** It passes, with 0 failures. Every one of its 182 cases
(156 T1, 26 T3) keeps the verdict and the findings' rules, severities and
files of the candidate built from #259's head, so no case is relabelled.

The agent wrote this entry in the fix PR, as the rulings' X.doc-batch asks;
the maintainer approves it there.

## D-090 (2026-10-05): every `pytestmark` binding is read, with its path condition as its guard, and a mark bound to a name is no module-level skip (#260)

checkwash read a `pytestmark` in one spelling only: a top-level
`pytestmark = <mark>` or `pytestmark = [<mark>, ...]` in a test module. Every
other spelling pytest honours skipped the tests with no finding: a class
body's `pytestmark`, one under an `if`, `try` or `with`, an annotated `=`,
`+=`, `.append`, a tuple target, and a name bound to a mark or to a list of
marks (#260 A1-A12). The one that blocked, `SKIP = pytest.mark.skip(...)` /
`pytestmark = SKIP` (A11), blocked by accident: `_module_skip_markers` read
any module-level call whose last name is `skip` or `xfail` as a module-level
skip call, so it named the finding `module.skip`. The same accident blocked a
mark that is bound to a name and never applied (M1, M2), which pytest runs.

Rulings, 2026-10-05:
- **260.Q1:** read all twelve rows, in modules and class bodies alike. Every
  binding of `pytestmark` counts: `=` and an annotated `=`; `+=`, and
  `.append`, `.extend` or `.insert` on it; a tuple target; a name bound once
  to a mark or to a list of marks; inside any compound statement at module or
  class level. A class's marks apply to that class's units only.
- **260.Q2:** the binding's path condition is the marker's guard, and D6
  judges it as it judges an imperative skip under recorded guards: each
  enclosing `if` test, `not (...)` for an `else` branch and after a branch
  that always ends, and an `except` block's condition. A `skipif` mark's own
  condition is conjoined with that guard. A `with` body has no guard.
- **260.Q3:** a mark keeps the name a decorator would mint, so moving it
  between spellings keeps its identity.
- **M1, M2** have no question of their own. The issue's comment records the
  consequence of 260.Q1 and Q3 as ruled: a `pytest.mark.*` call is a mark,
  never a module-level skip call.

**As implemented:**
- `frontend._pytestmark_markers` reads one scope, a module body or a class
  body, and records each skip or xfail mark as a decorator is: its own
  call's text and span, under the name a decorator would mint (#209 X1), and
  with the binding's path condition as its guard.
- `visit` gives a class's units its decorators and its body's marks, and a
  nested class's units its enclosing classes' too, as pytest does. A test a
  subclass inherits carries its defining class's marks and the subclass's.
- `_module_skip_markers` skips a call whose callee is a mark
  (`<...>.mark.<name>(...)`).
- `_decorator_markers` reads a decorator that names a bound mark as that
  mark, so `skip_slow = pytest.mark.skip(...)` / `@skip_slow`, which blocked
  only through M1's accident, still blocks, now on the test it skips.
- `compat._marker_is_compat_gate` judges a mark with a guard on the
  conjunction of the guard and the mark's own condition.
  `compat.removed_skip_guard` reads a mark's guard as it reads a body skip's.

Readings the rulings leave to the implementation:

1. **What puts a mark into `pytestmark`:** the six statements 260.Q1 names,
   and a subscript (`pytestmark[0] = ...`). A value is a mark, a list or
   tuple of marks, a `+` of those, a starred element, or a name bound to one.
   A tuple target unpacks a literal tuple or list of its length, element by
   element.
2. **A name bound more than once** holds every value a plain `=` binds it to,
   in its scope. The ruling names a name bound once; a name bound twice may
   hold either value, and both count, so the reading fails toward flagging. A
   class body's names are read with its module's, which Python falls back to.
   Before #260, `SKIP = pytest.mark.slow` / `SKIP = pytest.mark.skip(...)` /
   `pytestmark = SKIP` blocked through M1's accident, and it still blocks.
3. **Every binding counts**, so a later `pytestmark = []` does not unrecord a
   mark bound before it, although pytest then runs the test.
4. **The path condition** is D-087's reading 1, as a conftest's
   `collect_ignore` records it. Not followed: the code after a branch that
   always ends, which a module or class body rarely has. A loop, `match` or
   `try` body adds no guard, as a `with` body does not, so a binding there
   reads as unconditional.
5. **D6** credits a mark with a guard when the conjunction of the guard and
   the mark's own condition passes its tests (`pytest.mark.skip` has no
   condition of its own). A strict `xfail` earns nothing under any guard. A
   guard that does not parse as an expression (an `except` other than an
   `ImportError` around plain imports) earns nothing.
6. **A guard made always true or removed** is reported, as a body skip's is
   (THREATMODEL 54): the evidence pass compares the guard of each mark of a
   name across the diff, and `removed_skip_guard` now reads a mark's guard.
   Without it, removing the `if` around a guarded `pytestmark` would pass,
   since the mark keeps its name; before #260 it blocked, because the base
   side's guarded binding was never read. In conftest.py, which pytest does
   not collect as a test module, the mark disables nothing and neither does
   its guard: the same event is reported at info, in the `inert_mark` shape
   a conftest's mark has (209.Q3). This round's first cut gave it a test
   module's event, which blocked at high.
7. **A decorator that names a bound mark** is read as that mark, recorded as
   the mark's own call. A called name (`skip_if = pytest.mark.skipif` /
   `@skip_if(cond)`) is the decorator's own call. A name a decorator already
   reads as a mark (`skip = pytest.mark.skip` / `@skip`) keeps that reading.
8. **Not in this round (residuals):**
   - a subclass's own tests, which pytest marks with a base class's
     `pytestmark` and decorators;
   - a name bound by an import (`from tests.marks import SKIP`), and a list
     grown through another name (`MARKS.append(...)`);
   - a tuple target that does not unpack a literal, and a `pytestmark` bound
     by `global` in a function, a walrus or a loop target;
   - a decorator that names a mark through an attribute other than `mark`
     (`m = pytest.mark` / `m.skip(...)`).

**Tests and fixtures.**
- **Tests:** 102 in `tests/test_issue260_pytestmark_spellings.py`. All 51
  mutants of the round's code fail them or the fixtures.
- **Fixtures:**
  - positives, each of which pytest 9.1.1 skips, and which checkwash passed
    with no finding unless noted:
    - `pytestmark_class_body_skip_pos` (A9);
    - `pytestmark_if_true_skip_pos` (A1);
    - `pytestmark_except_importerror_skip_pos` (A3);
    - `pytestmark_else_branch_skip_pos` (A4);
    - `pytestmark_annotated_skip_pos` (A5);
    - `pytestmark_augmented_skip_pos` (A6);
    - `pytestmark_append_skip_pos` (A7);
    - `pytestmark_tuple_target_skip_pos` (A8);
    - `pytestmark_with_body_skip_pos` (A10);
    - `pytestmark_bound_mark_skip_pos` (A11; blocked as `module.skip`);
    - `pytestmark_bound_list_skip_pos` (A12);
    - `pytestmark_guard_made_true_pos`;
    - `pytestmark_guard_removed_pos` (blocked as a mark added);
    - `mark_bound_and_applied_skip_pos` (blocked as `module.skip`).
  - negatives: `pytestmark_platform_guard_neg` (warn `COMPAT_GATE`),
    `mark_bound_never_applied_neg` (M1) and
    `xfail_mark_bound_never_applied_neg` (M2), which blocked at high; and
    `conftest_pytestmark_guard_made_true_neg` and
    `conftest_pytestmark_guard_removed_neg` (info, reading 6), which pytest
    9.1.1 runs.

Every existing fixture keeps its expectation, and its corpus record does not
change.

**Fingerprints.** A mark read in a new spelling mints the name a decorator
would. One kind of existing finding moves: a mark bound to a name and
applied by it (as `pytestmark`, A11, or as a decorator) was reported as
`module.skip` or `module.xfail` on every test of the module, and is now
reported under the mark's own name on the tests it marks. The release guide
names it (X.release-and-fingerprints). In the targeted sweep, three pytest
commits show it (`221ac3e466`, `8360c1e687`, `fe34a8a15a`), with their
verdicts unchanged.

**Cost.**
- **Newly blocking:**
  - a skip or xfail mark bound to `pytestmark` in a spelling checkwash did
    not read, unless its guard and its condition qualify for D6;
  - a decorator that names a bound mark D6 does not credit, as the
    decorator spelling of the same mark already blocked;
  - a guard made always true, or removed, around a `pytestmark` binding.
- **Newly passing:** a mark bound to a name and never applied (M1, M2).
- **Sweep, standard:** the last 300 non-merge commits of attrs, click,
  flask, httpx, rich and starlette (1,800 commits) keep every verdict. One
  rich commit (`655b5210cb`) gains five findings at warn: tests marked by
  names bound to `skipif(sys.version_info ...)` marks, which D6 holds.
- **Sweep, targeted:** the commits of D-088's ten full histories and of
  pytest's that touch `pytestmark` or bind a name to a `pytest.mark` call
  (httpx and requests have none): 186 commits, 179 readable. aiohttp's are
  left out, since a git submodule makes 21 of its 22 unreadable. Nine
  verdicts move, and one commit becomes readable:
  - **block to pass:** pytest `7c6e47f715` binds
    `needsosdup = py.test.mark.xfail(...)` and never applies it (M2).
  - **unreadable to pass:** pytest `9295f9ffff` exceeded the stand-in
    proof's step budget. Tests marked by a bound name now count as
    disabled, so that proof no longer traces them.
  - **pass to block:**
    - uvicorn `4a5f3ddf39` moves its `pytestmark` skip into an
      `except ImportError:` block, which D6 does not credit (260.Q2's A3:
      ruled behaviour).
    - rich `f15dc3ea0b` applies
      `skip_pypy3 = pytest.mark.skipif(hasattr(sys, "pypy_version_info"))`
      by name. D6 credits no PyPy check, as for the decorator spelling.
    - pytest `0be961a0f3`, `4337702a6a` and `8e4501ee29` apply
      `needsosdup = ...("not hasattr(os, 'dup')")` by name, a condition that
      names no interpreter or OS.
    - pytest `536252cb2e` and `5715bbd6f5` apply platform marks by name
      whose condition is a string. D6 reads a string condition as one that
      always holds (#263), so they block, as their decorator spellings
      already did.
    - pytest `1ff173baee` moves two tests into a class whose `pytestmark`
      is a name bound to `skipif("sys.version_info < (2,6)")`, a string
      condition again (#263). The moved tests count as disabled, so the old
      units' disappearance is no restructure.
- **Sweep, D-088's sets**, measured in #261's round against #262's engine:
  the 895 commits of ten full histories that change a `conftest.py` or a
  `skip`/`xfail` line in a test file (855 readable), and the 368 of pytest's
  history that touch a collection control or a skip or xfail decorator (364
  readable). Besides uvicorn `4a5f3ddf39` and rich `f15dc3ea0b` above, one
  verdict moves:
  - **pass to block:** uvicorn `7d274ed389` respells its optional-dependency
    skip, `@pytest.mark.skipif(HttpToolsProtocol is None)`, as
    `skip_if_no_httptools`: bound to `skipif(False)` in a `try` and to
    `skipif(True)` in its `except ModuleNotFoundError:`, and applied by name.
    The name holds both marks (reading 2), each a new identity, and D6
    credits no dependency check, as for a `pytestmark` under
    `except ImportError` (A3).

  On 21 more commits findings move and verdicts do not:
  - uvicorn `8239373ec6`, already blocked: a test renamed into the same
    spelling (`@skip_if_no_wsproto`) is no live copy, so the old unit's
    disappearance goes from info to high.
  - pytest `6ba3475448`: a renamed test class sits in a module that binds
    `needsosdup = pytest.mark.xfail(...)`. M2 made every test there look
    disabled, so the renamed test was no live copy; it is now, and the old
    unit's disappearance goes from warn to info.
  - flask `1232d69860`, werkzeug `c5cce98338` and fourteen rich commits
    (`655b5210cb` among them) gain findings at warn: marks applied by
    name, whose condition the commit changes or adds.
  - rich `d388b83954` and `e037e587e3` (at warn) and werkzeug
    `8720873853` (at high), which already blocked, gain one finding each.

**Verdict gate.** It passes, with 0 failures. Every one of its 182 cases
(156 T1, 26 T3) keeps the verdict and the findings' rules, severities and
files of the candidate built from #262's head, so no case is relabelled.

The agent wrote this entry in the fix PR, as the rulings' X.doc-batch asks;
the maintainer approves it there.

## D-091 (2026-10-05): a guard removed from an existing suite-level control is reported (#261)

A later diff could take the guard off a suite-level control that already
existed, and checkwash reported nothing. The ignored paths or the skipped
items then applied everywhere. The same held when an unguarded drop was added
to a hook whose existing effects were guarded. #209 Q1 made this a two-commit
bypass: the first commit adds an honest guarded hook, which passes at warn
(`COMPAT_GATE`), and the second removes the guard with no finding
(THREATMODEL row 116's residual).
- A suite-level control is reported when its marker is added. An existing
  control keeps its marker's name, so removing its guard adds none.
- `guards_weakened` compares a marker's guard on both sides with D6's
  evaluator. A removed guard leaves nothing to evaluate at head. Body and
  setup skips report that case as "skip guard removed" (THREATMODEL 54,
  D-086, D-087); suite-level controls did not.
- For `collect_ignore`, the ignored paths stay the same, so no path is added
  either (row 81).

Rulings, 2026-10-05:
- **261.Q1:** report it. A suite-level control is `collect_ignore`,
  `collect_ignore_glob`, either collection hook, or an `add_marker` skip in
  one. When its guard could be false at base and it has none at head,
  TEST_DISABLED reports "skip guard removed of the suite-level control (was
  '<guard>') (<marker>)". The finding has the guard family's identity
  (`guard:<marker>`) and is judged as an unguarded control: no `COMPAT_GATE`,
  and no repair evidence (D-028, #209 Q4).
- **261.Q2:** an unguarded effect added beside guarded ones is the same
  event. At head, the control has no guard that can be false.
- **261.Q3:** a guard that is a dropped constant is treated as removed.

**As implemented:**
- `compat.removed_skip_guard` reads a suite-level collection control
  (`conftest_controls.is_collection_control`) as it reads a body skip. The
  base control must have run under a guard that does not always hold, and
  the head control must run under none. The evidence pass then records the
  event in `guards_weakened`, as it does for a body skip.
- TEST_DISABLED names the control, as a hook's guard event already did:
  "skip guard removed of the suite-level control (was '<guard>')
  (<marker>)".
- Gating is unchanged. A guard event has no marker of its own, so D6 gives
  it no `COMPAT_GATE`. On a conftest's `<suite>` unit it is an unguarded
  control, which refuses repair evidence.

Readings the rulings leave to the implementation:

1. **The controls** are the four names `_conftest_unit` mints for collection
   controls. `conftest.collect_ignore` covers both lists. A runtime control
   carries no guard, so it has none to remove.
2. **A guard that could be false at base** is one `guard_can_be_false`
   accepts: present, and not true in every environment D6 evaluates. An
   `except` block's condition that is not an expression counts, as it does
   for repair evidence (row 83).
3. **No guard at head** means the head control's recorded guard is none.
   This covers 261.Q2 and Q3 with no reading of their own. The weakest guard
   of a hook with an unguarded effect is none, and so is that of a
   `collect_ignore` with an unguarded statement. The hook reading drops a
   constant `True`. `collect_ignore` records `if True:` as its guard, so that
   edit stays "skip guard now always fires", as before.
4. **One event.** A guard removed and a path gained (row 81) are reported
   once, as the guard removed.
5. **An `add_marker` skip in a hook** is a control of its own. A hook whose
   loop calls `item.add_marker(pytest.mark.skip(...))` reports both the hook
   and the call, as a guard made always true already did.
6. **Wording.** `collect_ignore`'s message names the control only when its
   guard is removed. "skip guard now always fires" keeps its wording (#261's
   G6).
7. **The head guard is #209's reading.** A hook defined under a module-level
   `if` carries no guard from it. A condition that calls a function the
   conftest defines is an effect (209.Q2). So moving a hook's guard to
   either place reads as removed. A hook added in either form already
   blocks.
8. **Not in this round (residual):** a guard rewritten into a weaker one that
   can still be false, such as `if A and B:` to `if A:`, or a second effect
   under another condition. A body skip's is not judged either (row 54).

**Tests and fixtures.**
- **Tests:** 26 in `tests/test_issue261_suite_guard_removed.py`. All 4
  mutants of the round's code fail them or the fixtures.
- **Fixtures:** row 116's new pins. Each passed with no finding. On pytest
  9.1.1 with `NETWORK=1`, each runs both tests at base and one at head:
  - `conftest_collect_ignore_guard_removed_pos` (G1);
  - `conftest_hook_guard_removed_pos` (G2);
  - `conftest_hook_unguarded_drop_beside_guarded_pos` (G3);
  - `conftest_hook_guard_constant_true_pos` (G4).

Every existing fixture keeps its expectation, and its corpus record does not
change.

**Fingerprints.** None move. The new finding has the guard family's
identity, `guard:<marker>`, which a guard made always true already had. An
exemption recorded for one edit covers the other.

**Cost.**
- **Newly blocking:** a diff that leaves an existing suite-level collection
  control with no guard that can be false, when its guard could be false at
  base.
- **Sweep, standard:** the last 300 non-merge commits of attrs, click,
  flask, httpx, rich and starlette (1,800 commits) give the same verdicts
  and findings as #264's engine.
- **Sweep, targeted:** D-088's sets, which are:
  - the 895 commits of ten full histories that change a `conftest.py` or
    a `skip`/`xfail` line in a test file (855 readable);
  - the 368 of pytest's own history that touch a collection control in a
    conftest or a skip or xfail decorator in `testing/` (364 readable).

  No record moves. The 24 that differ from #262's engine are #260's
  (D-090), and #264's engine gives each of them. So no commit in these
  sets removes a guard that could be false from an existing suite-level
  control.

**Verdict gate.** It passes, with 0 failures. Every one of its 182 cases
(156 T1, 26 T3) keeps the verdict and the findings' rules, severities and
files of the candidate built from #264's head, so no case is relabelled.

The agent wrote this entry in the fix PR, as the rulings' X.doc-batch asks;
the maintainer approves it there.

## D-092 (2026-10-05): v0.6.0 — fingerprint changes since v0.5.0

The rounds merged since v0.5.0 (PRs #194–#265) keep the finding JSON shape,
the rule IDs, the severity model and the exit codes. The findings gain one
escalator, `CI_BECAME_UNANALYSABLE` (D-082), and one `shape` value,
`inert_mark` (D-089). The IR gains optional fields and stays at IR_VERSION 2
(D-067).

They change the fingerprint of some existing findings. Each round recorded
its own for this release (X.release-and-fingerprints):
- D-070: a chai delta is spelled as an exact decimal in TOLERANCE_LOOSENED;
- D-071: the file-level JS focus finding is keyed by the path, `<file>` and
  `test.focused`;
- D-073 and D-074: SCOPE_DRIFT, and SNAPSHOT_CODE_COCHANGE, where a file's
  role changed;
- D-077: a widened Python hand-rolled bound moves from
  EXPECTED_VALUE_CHANGED to TOLERANCE_LOOSENED, and a JS hand-rolled check
  spelled through `expect(...)` is keyed by its full text;
- D-081: CI_WORKFLOW_TOUCHED's reworded reasons;
- D-083: an existing config's new selector under explicit pytest targets;
- D-087: a guard removed from a unit's setup joins the guard family;
- D-090: a mark bound to a name and applied by it is reported under its own
  name, not as `module.skip` or `module.xfail`.

Fingerprints are a frozen contract, so the release is minor: v0.6.0, chosen
by the maintainer on 2026-10-05. Allowlist entries recorded on v0.5.0 for
these shapes must be re-recorded; the
[release guide](docs/releases/v0.6.0-public-launch.md) lists them.

Cost against v0.5.0 itself, on the fixed 1,800-commit sweep (the last 300
non-merge commits of attrs, click, flask, httpx, rich and starlette), v0.5.0's
engine against this release's: both block the same 48 commits, no verdict
moves, and neither errors. One passing commit's findings differ: rich
`655b521` binds a Python 3.14 `skipif` to a name and applies it to five tests,
which v0.5.0 did not read and this release reports as five TEST_DISABLED warns
that D6 qualifies (D-090, decorator reading). Each round's targeted sets are
recorded in its own entry.

THREATMODEL: the rows fixed since v0.5.0 said "unreleased"; they now name
v0.6.0. Their text and pins are the merged PRs'.

The agent wrote this entry in the release PR; the maintainer approves it
there.

## D-093 (2026-10-05): a test that starts requesting an always-skip conftest fixture is reported (#223)

An existing test that started requesting an existing conftest fixture whose
setup always skips passed with no finding. It could ask by parameter, by
`@pytest.mark.usefixtures`, through a module `pytestmark`, or through a
same-file fixture that requests it, and pytest then skipped it. The same
request of a same-file skip fixture blocked with `TEST_DISABLED` high.
- A unit reached only the fixtures of its own module and classes
  (`setup_outcomes`, #172).
- A conftest skip fixture was judged once, as a `<suite>` control, when the
  diff added it (ruling 196.183.1 (a)). An unchanged conftest adds no
  marker, so nothing was reported.

Rulings:
- **2026-10-03** (#196, item `196.followup.conftest-request-side`, 183.1
  option (c)): resolve the conftest chain for the test files a diff
  changes, so that a newly requested always-skip conftest fixture mints a
  `setup.*` marker on the unit.
- **223.Q1** (2026-10-04): when one diff both adds the conftest fixture and
  makes an existing test request it, both findings are reported. The
  `<suite>` finding is about the conftest that now holds an always-skip
  fixture, and the unit's `setup.*` finding is about the test that now runs
  it. Each has its own identity and its own remedy.
- **223.Q2** (2026-10-04): the chain is every `conftest.py` from the test
  file's directory up to the repository root, on each side. The nearest
  definition of a fixture name wins, as in pytest, and a fixture in the test
  module wins over all of them. `pytest_plugins` fixtures stay a row 104
  residual.

**As implemented:**
- The engine reads the chain of each test module the diff changes, on each
  side (`engine._conftest_chain`), and hands it to the frontend
  (`parse_python(..., chain=...)`). Each `conftest.py` is read as a
  `ConftestLevel`: its fixtures, of whose outcomes only an unconditional
  one is kept, and the names it binds some other way.
- `setup_outcomes` resolves each request through the module's classes, then
  the module, then the chain, nearest first. A conftest fixture's outcome
  becomes the same `setup.<fixture>.<effect>` marker that a same-file
  fixture's does, so TEST_DISABLED, D6 and repair evidence judge it as they
  judge that one.
- The marker keeps the conftest's text and span. The report locates the
  finding at the conftest's skip line, as it locates an assertion inherited
  from a conftest fixture.

Readings the rulings leave to the implementation:

1. **Reads.** A conftest the diff changes is read on its own side. Any
   other is the same on both sides, and is read once from the strict head
   snapshot. A renamed module's base side reads the chain above its old
   path. A level that cannot be read (no snapshot) or parsed ends the chain:
   what it defines is unknown, and it could override any name beyond it.
   Reads past 4,096 files or 64 MB are an engine error, as they are for the
   stand-in context.
2. **Resolution.** Every name in the closure resolves as the test sees it,
   as pytest resolves it, including a name a conftest fixture requests. So
   a conftest fixture's request reaches the test module's fixture of that
   name. A fixture that requests its own name reaches the next definition
   outward (pytest's override-and-extend), in the module as in a conftest.
3. **Names bound some other way.** An import, an assignment, a decorated def
   that is no plain fixture, a def under an `if` or a `try`, or a star
   import may hold a fixture this reading does not see. A request is not
   followed past such a name into a conftest beyond it. Within the test
   module, these do not change which same-file fixture a request reaches.
4. **Autouse.** The chain's autouse fixtures are in every unit's setup, as
   the module's own are. A test moved below an always-skip autouse conftest
   fixture is not live there, so its old unit's disappearance is reported.
5. **Only an unconditional outcome.** A guarded conftest skip records nothing
   on the unit, and waits for 183.2's conftest half. The fixture still
   resolves its own requests.
6. **Identity.** The marker is `setup.<fixture>.<effect>` whichever file holds
   the fixture, so one exemption covers both. Moving a skip fixture from the
   module into a conftest is no unit event. The conftest's `<suite>` finding
   still reports the fixture added there (183.1 (a)).
7. **Not in this round (residual):** a test in a file the diff does not
   change. An importer the engine adds unchanged, to judge a root helper
   or an expected value, is one and reads no chain. D10's duplicate
   survivor is another: a survivor that a conftest fixture it requests
   skips is read as live (#266, row 58).

**Tests and fixtures.**
- **Tests:** 46 in `tests/test_issue223_conftest_request_side.py`. All 17
  mutants of the round's code fail them or the fixtures.
- **Fixtures:** row 104's new pins, each run on pytest 9.1.1 first.
  - Positives: each passed with no finding, and pytest runs `test_total`
    at base and skips it at head:
    - `conftest_skip_fixture_requested_by_parameter_pos` (S1);
    - `conftest_skip_fixture_requested_by_usefixtures_pos` (S2);
    - `conftest_skip_fixture_requested_by_pytestmark_pos` (S4);
    - `conftest_skip_fixture_requested_through_fixture_pos` (S5);
    - `conftest_skip_fixture_requested_from_root_conftest_pos` (S6).
  - `conftest_skip_fixture_added_and_requested_pos` (223.Q1): the `<suite>`
    finding it had, and now the unit's.
  - Negatives:
    - `conftest_plain_fixture_requested_neg` (S7);
    - `conftest_guarded_skip_fixture_requested_neg`;
    - `conftest_skip_fixture_overridden_in_module_neg`;
    - `conftest_skip_fixture_request_removed_neg`.

Every existing fixture keeps its expectation, and its corpus record does not
change.

**Fingerprints.** None move. The unit's finding has the `setup.*` marker's
identity, which a same-file skip fixture's finding already had.

**Cost.**
- **Newly blocking:**
  - a diff in which a unit of a changed test module starts reaching an
    always-skip conftest fixture;
  - a test module that moves below an always-skip autouse one.
- **Where it can occur:** twelve full histories hold 61,048 non-merge
  commits, 17,337 of which change a collectable test module. The histories
  are attrs, click, flask, httpx, rich, starlette, requests, scrapy,
  uvicorn, werkzeug, pytest and aiohttp. In none of them does a commit
  change a test module below a conftest fixture that always skips or xfails,
  on either side, so the request side moves no commit there.
- **Sweep, standard:** the last 300 non-merge commits of attrs, click,
  flask, httpx, rich and starlette (1,800 commits) give the same verdicts
  and findings as #265's engine.
- **Sweep, targeted:** D-088's sets give the same records as #265's
  engine:
  - the 895 commits of ten full histories that change a `conftest.py` or
    a `skip`/`xfail` line in a test file (855 readable);
  - the 368 of pytest's own history that touch a collection control in a
    conftest or a skip or xfail decorator in `testing/` (364 readable).

**Verdict gate.** It passes, with 0 failures. Every one of its 182 cases
(156 T1, 26 T3) keeps the verdict, the exit code and the findings' rules,
severities and files of the candidate built from #265's head, so no case
is relabelled.

The agent wrote this entry in the fix PR, as the rulings' X.doc-batch asks;
the maintainer approves it there.

## D-094 (2026-10-05): the verdict gate's baseline rotates to v0.6.0

After v0.6.0's publication, the rotation PR (#270, `docs/RELEASING.md`
step 8c) points the previous-release verdict gate (#201) at v0.6.0. Pull
requests, `main` and the next tag are compared with v0.6.0 instead of
v0.5.0.

- **`[baseline]`** in `tests/verdict_gate/baseline.toml` pins tag v0.6.0,
  commit `8c70efb` (the merge commit of #267) and the Release's
  `checkwash.pyz`: sha256 `4f9c7b83…`, 655,217 bytes, as GitHub reports the
  asset. The gate re-checks both on every run, and checks that the archive's
  `checkwash/*` members equal `src/checkwash` at `8c70efb`.
- **`baseline_blocked`** goes from 77 to 156, the rotation run's proposal.
  v0.6.0 blocks the 26 T3 cases and the 130 T1 cases labelled `block`. It
  passes the 25 labelled `pass`, and `i198/T6`, labelled `undecided`, which
  the gate reports. Every T1 verdict of v0.6.0 agrees with its label.
  Against v0.5.0, 88 T1 cases go from pass to block and nine from block to
  pass: the nine fp-fix entries below.
- **`[t3.cases]`** is unchanged. `tests/data/javascript_chai_mutations.json`
  is the same file at `8c70efb` as at v0.5.0 (sha256 `f10a5ef8…`), and the
  run names no added, dropped or re-hashed case.
- **`[canary]`** is not rotated (step 8c). The v0.4.2 -> v0.5.0 pair and its
  70-case `block_to_pass` set stay.
- **The acceptance file**, `tests/gates/verdict_gate_accepted.toml`:
  `baseline` becomes `v0.6.0`, and its nine fp-fix entries are removed
  (i196/W1, i197/R1, R2, Q5a and Q5b, i198/FP1, FP2, FPJ1 and FPJ2). v0.6.0
  passes each, so none is a block -> pass transition any more, and each is
  labelled `pass`. The gate run on the rotation PR's pins commit (#270, run
  37344879525) names all nine stale, and the gate fails on a stale entry.
  No entry remains: no known-regression or pending-ruling entry was open.

From this rotation on, a candidate that turns any of v0.6.0's 156 blocks
into a pass needs an accepted entry. No engine code changes: the candidate
built from this tree is v0.6.0's own source, so each case's baseline and
candidate runs are equal.

The agent wrote this entry in the rotation PR; the maintainer approves it
there.

## D-095 (2026-10-05): a skip guard reads the class attribute its class body sets, and an abstract test base run by a same-file subclass stays live (#254)

A skip guard that reads an attribute of the test's class, such as
`if self.item_class is None: raise unittest.SkipTest(...)`, was never
evaluated. Guards were evaluated against module constants only, so the skip
counted as one under an unknown guard and blocked, even where the class body
sets `item_class = list` and the guard never holds. The abstract test base
blocked the same way: a base whose guard holds on itself, run by a same-file
subclass that sets the attribute. 183.2's second stage added the setup form
of both, and scrapy `526585393` (5 findings) and `f46a45008` (19) are its
two measured cases.

Rulings, 2026-10-04 (#254, adopted as recommended):
- **254.Q1:** a guard that names `self.<attr>` or `cls.<attr>`, where the
  unit's class or a same-file base assigns `<attr>` exactly once in its
  class body, is evaluated with that value, as module constants are, for
  body and setup skips alike. A class or a function that the file defines or
  imports is not `None`.
- **254.Q2 (a):** when the guard holds on the class that defines the test
  but not on a same-file subclass that inherits the test unchanged and
  carries no disabling marker, the base's unit gets no marker and stays
  live. A subclass that redefines the test has its own unit, judged on its
  own. A base whose guard holds and that no same-file subclass runs records
  the marker with its resolved guard, so it reads as an unconditional skip.

**As implemented:**
- `frontends/python/class_attributes.py` reads the class bodies of a test
  module's top-level classes (`ClassAttributes`). A guard's
  `<receiver>.<attr>` is replaced by the value before the guard is folded:
  in the test body (`_unreachable_ids`, and the guard a skip call records)
  and in the setup callbacks and fixture methods a unit runs
  (`setup_skip_controls`). The receiver is the method's first parameter,
  unless it is a `staticmethod` or the body rebinds that name.
- A guard that never holds leaves dead code, so no marker is minted. One
  that holds is no condition: the skip is recorded with no guard and reads
  as unconditional.
- 254.Q2: a unit whose only markers are body or setup skips whose guards
  hold under its class's values keeps none when a crediting subclass runs
  it, and that subclass's own values satisfy neither the body nor the setup
  guard (`frontend.parse_python`, `credit_base`).

Readings the rulings leave to the implementation:

1. **Values.** A literal is used as a module constant's is. A class or a
   function the file defines, a builtin class or function, a lambda, and a
   `staticmethod` or `classmethod` of one of those is not `None`, is true,
   and equals nothing but itself. An imported name is not `None`, as the
   ruling has it, and is read by `is None` and `is not None` only: whether
   it is true, or what it equals, depends on an object this file does not
   show. Anything else is unknown.
2. **Exactly once.** An attribute the class body binds by anything but one
   plain assignment (twice, under an `if` or a `try`, by a `def`) is
   unknown. So is one that any code in the module assigns or deletes
   through an attribute target (an instance's `self.item_class = None`,
   `TotalTest.item_class = None`), and every attribute of a module that
   uses `setattr`, `delattr`, `vars`, `globals`, `locals`, frame access or
   a rebound `__dict__`, `__class__` or `__bases__`. Code that a string
   literal hands to `eval` or `exec` is read with the module, and a literal
   that is no code makes every attribute unknown. Code that a computed
   string hands to them is not read, as code outside the file is not:
   `526585393`'s module evaluates exported data
   (`eval(self.output.getvalue())`). A private name (`_x`) is unknown:
   unittest sets some on the instance.
3. **The chain.** The lookup reads the unit's class and its same-file bases,
   each with one base. A decorator, a class keyword or `__getattribute__`
   anywhere in it makes every attribute unknown: a decorator or a metaclass
   receives a class of the chain, and may rebind any attribute of it or of
   a class derived from it. The chain must end in a class that derives from
   nothing, from `object` or from unittest's `TestCase`. Any other base,
   or a second one, may set the attribute on the instance from code the
   file does not show: Django's `TestCase` sets `self.client`. A nested
   class is not read.
4. **Crediting subclasses (254.Q2).** A subclass credits the base when it
   reaches the base through same-file single bases and is collected: a
   subclass of unittest's `TestCase`, or a `Test*` class whose whole
   hierarchy is in the file and defines no `__init__` or `__new__`. It, and
   each class between it and the base, adds nothing but new values for
   public attributes the base declares in a class body and undecorated
   tests of its own that the base never reaches through an attribute. No
   class of its chain binds `__test__`. A setup or teardown callback, a
   framework entry point (`run`, a dunder), defined or assigned, a helper
   the test calls, a decorator or a class keyword is something that may
   change how the inherited test runs, so it credits nothing.
5. **What a subclass shares.** A unit that also carries a decorator, class
   or module mark keeps every marker: the subclass inherits that mark, so
   it does not run the test either. So does a unit with a skip whose guard
   is unknown on the base.
6. **Identity.** No marker changes its name. A finding either goes or keeps
   its marker (`self.skipTest`, `setup.<provider>.<effect>`).
7. **Not in this round (residual):** what runs outside the file, as for
   module constants: a conftest or a plugin that sets the attribute on the
   instance, the module an imported name comes from binding it to `None`,
   or code that a computed string hands to `eval` or `exec`. A skip reached
   through code the test calls, a subclass's value included, is #272.

**Tests and fixtures.**
- **Tests:** 137 in `tests/test_issue254_class_attribute_guards.py`. All
  54 mutants of the round's code fail them or the fixtures.
- **Fixtures**, each run on pytest 9.1.1 first:
  - Negatives, which v0.6.0 blocks at high and pytest runs:
    - `class_attribute_setup_guard_never_holds_neg` (R1);
    - `class_attribute_skiptest_guard_never_holds_neg` (R2);
    - `abstract_base_run_by_subclass_neg` (R3, `f46a45008`'s shape);
    - `abstract_base_run_by_pytest_subclass_neg`.
  - Positives, row 104's pins, which v0.6.0 also blocks, and pytest skips
    the test in every class:
    - `abstract_base_no_subclass_pos`;
    - `abstract_base_subclass_redefines_test_pos`;
    - `abstract_base_subclass_skipped_pos`;
    - `class_attribute_rebound_in_setup_pos`.
  - `class_attribute_flipped_skiptest_guard_pos`, row 54's pin: a class
    attribute flipped so that an unchanged guard holds. v0.6.0 passes it
    with no finding.

Every existing fixture keeps its expectation, and its corpus record does not
change.

**Fingerprints.** None move.

**Cost.**
- **Newly passing:** the issue's two measured cases, scrapy `526585393`
  and `f46a45008`, go from block to pass, as 254.Q1 and 254.Q2 predicted.
  - In `526585393`, the base's five setup skips go. A unit that
    disappeared beside them falls from high to warn, now that the base's
    units are live.
  - In `f46a45008`, the 19 setup skips on the base's units go. Two units
    that disappeared and the assertion removed beside them fall from high
    to info: the liveness escalations the ruling named.
- **Newly blocking:** a class attribute flipped so that an unchanged skip
  guard holds (`class_attribute_flipped_skiptest_guard_pos`).
- **Sweep, standard:** the last 300 non-merge commits of attrs, click,
  flask, httpx, rich and starlette (1,800 commits) give the same records as
  main's engine (#223's).
- **Sweep, targeted:** D-088's sets.
  - The 895 commits of ten full histories that change a `conftest.py` or a
    `skip`/`xfail` line in a test file (855 readable): two records differ.
    `f46a45008` goes from block to pass, as above. `380c2279b9` stays
    block: one of its 233 findings, a unit that disappeared from
    `tests/test_exporters.py`, falls from high to warn, now that the
    module's base units are live.
  - The 368 commits of pytest's own history that touch a collection
    control in a conftest or a skip or xfail decorator in `testing/` (364
    readable) give the same records.
- `526585393` is in neither set, so it was run on its own, with both
  engines.

**Verdict gate.** It passes, with 0 failures and 1 reported (`i198/T6`,
undecided, pass -> pass). Every one of its 182 cases (156 T1, 26 T3) keeps
the runs and the transition of the candidate built from main's tree, the
version string aside, so no case is relabelled.

The agent wrote this entry in the fix PR, as the rulings' X.doc-batch asks;
the maintainer approves it there.

## D-096 (2026-10-05): a pytest file beneath a snapshot directory is judged as a test beside its snapshot role (#219)

A pytest file beneath a snapshot directory (`**/golden/**`,
`**/expected/**`, `**/__snapshots__/**`) resolves to the `snapshot` role, so
it was never parsed or judged as a test. Moving `tests/test_x.py` to
`tests/golden/test_x.py` blocked with TEST_DISABLED high "test unit
disappeared" for every unit, although pytest still collects and runs the
destination: a false reason in a blocking message. A test already living
there was judged only by the snapshot rules: deleting it passed with zero
findings, weakening it beside an unrelated production edit passed at warn,
and weakening or skipping it blocked with a message about a stored
expectation. #197 gave a JS/TS test there its test obligations (197.Q2,
197.Q3); 197.Q4 left the Python twin to this round, and THREATMODEL row 107
disclosed it until now.

Rulings, 2026-10-04 (#219, adopted as recommended):
- **219.Q1:** a Python file has test obligations exactly when
  `collectable(path)` holds, whatever its published role. So
  `tests/golden/test_x.py` gains them, and `tests/golden/data.py` and
  `tests/golden/x_checks.py` do not. One predicate serves the obligations
  and rename continuity, as 197.Q2 rules for JS.
- **219.Q2:** both rule sets report, as 197.Q2 rules for JS: the earlier
  role keeps its own rules, and the test obligations add theirs. A weakened
  assertion reports ASSERT_WEAKENED and the snapshot rule's
  EXPECTED_VALUE_CHANGED; an added skip reports TEST_DISABLED and the same
  EXPECTED_VALUE_CHANGED.

**As implemented:**
- `engine.build_ir` sets `test_obligations` for a Python file that
  `roles.collectable` accepts and whose role is not `test`, as it does for a
  JS/TS test path (197.Q3's field). `role` stays the published role.
- `engine._expand_renames` reads a Python path as a test, on either side of
  a rename, when `collectable` accepts it, whatever its role.
- Three searches for a Python test the diff does not change read the same
  predicate (reading 2): D10's search for a surviving copy, the reverse
  search for the unchanged importers of a changed root assertion helper
  (`engine._root_importer_changes`), and the runtime-shadow test inventory
  (`shadow.find_runtime_subject_shadows`).

Readings the rulings leave to the implementation:

1. **The predicate.** `collectable(path)` is pytest's default collection:
   a `test_*.py` or `*_test.py` name, and no dot-directory, build-output or
   virtualenv segment (SPEC §2b). `conftest.py` never matches it, and no
   path that a default role glob resolves to `ci` or `guardrail` does, since
   each of those Python paths sits beneath a dot-directory or has another
   name. In the default table, a collectable path is either `test` or
   `snapshot`.
2. **Every place that asks.** The rulings name the obligations and rename
   continuity. Three more places ask whether a Python file is a test pytest
   collects, and each read `role == "test"` beside `collectable`, so a test
   the obligations now judge stayed invisible to them:
   - D10 (DUPLICATE_REMAINS): a surviving copy in `tests/golden/` earned no
     credit, so deleting its duplicate from `tests/test_utils.py` blocked
     with TEST_DISABLED high. It now holds at info, as a copy in
     `tests/unit/` does. SPEC §5's D10 row already says "collectable".
   - The root helper importer search: when a diff guts a root assertion
     helper (`def assert_equal(actual, expected): assert actual ==
     expected` becomes `pass`), an unchanged caller in `tests/golden/` was
     never read, and the diff passed with zero findings. The caller now
     reports ASSERT_REMOVED high, as one in `tests/` does.
   - The runtime-shadow inventory: a stand-in module planted beside a test
     in `tests/golden/` was not matched against that test's imports. It now
     is, as beside a test in `tests/unit/`.
3. **The published role** does not change, so no existing finding moves
   its fingerprint: the snapshot rules' findings keep theirs, and the test
   rules' findings on such a file are new. Role globs replace the defaults
   (`[roles] test = ["tests/**"]`), so a project can leave a collectable
   file such as `src/pkg/test_x.py` as production. That file keeps the
   production role, which E7 reads, and every test rule judges it beside
   it: 219.Q1's "whatever its published role".
4. **Moves.** A move from `tests/` into a snapshot directory still changes
   the supervised role (`test` to `snapshot`), so the rename is expanded
   into a delete and an add, and the units are held as moved: TEST_DISABLED
   at info with ASSERTION_MOVED, the same as the delete-plus-add form and
   as a JS test moving from `tests/` into `tests/golden/`. The verdict is
   pass. A rename between two collectable names inside a snapshot
   directory is an edit. A move from there back into `tests/` is held as
   moved. A move from there to a name pytest does not collect, or to
   production code, reports the units as gone.
5. **The snapshot rules (219.Q2).** EXPECTED_VALUE_CHANGED still reports
   beside the test findings. SNAPSHOT_CODE_COCHANGE ("changed together with
   prod code ... and no test logic changed") stands down once the file's
   own test logic changed, which is its own condition. So a weakening
   beside an unrelated production edit reports ASSERT_WEAKENED high alone,
   as its JS twin `js_test_in_expected_dir_weakened_with_prod_edit_pos`
   does.
6. **Not in this round (residual):** pytest's configured collection is not
   read for the predicate, as for every Python path (SPEC §2b). A project
   that keeps a snapshot directory out of collection (`norecursedirs`,
   `testpaths`, `python_files`, a conftest's `collect_ignore`) has a
   test-named file there judged as a test, and a test moved into it is held
   as moved.

**Tests and fixtures.**
- **Tests:** 42 in `tests/test_issue219_python_snapshot_tests.py`.
  `tests/test_js_test_obligations.py` pinned the old one-role reading; its
  test now reads the obligations from `collectable`. All 10
  mutants of the round's code fail them or the fixtures.
- **Fixtures.** pytest 9.1.1 collects and passes the test-named files they
  place in `tests/golden/`, and does not collect `tests/golden/x_checks.py`:
  - `python_test_moved_into_golden_neg` (#219 M1): v0.6.0 blocks with
    TEST_DISABLED high on both units; it now passes, with both held as
    moved at info.
  - `python_test_duplicate_in_golden_neg`: v0.6.0 blocks with
    TEST_DISABLED high; the copy in `tests/golden/` now holds it at info.
  - Row 107's new pins:
    - `python_test_in_golden_deleted_pos` (E3), which v0.6.0 passes with
      zero findings;
    - `python_test_in_golden_weakened_with_prod_edit_pos` (E4), which
      v0.6.0 passes at warn;
    - `python_test_in_golden_weakened_pos` (E1) and
      `python_test_in_golden_skipped_pos` (E2), which v0.6.0 blocks with
      EXPECTED_VALUE_CHANGED alone;
    - `python_test_in_golden_root_helper_oracle_removed_pos`, which v0.6.0
      passes with zero findings.
  - `python_test_moved_into_golden_uncollected_name_pos` (K4), the
    predicate's boundary: v0.6.0 blocks it the same way.

Every existing fixture keeps its expectation, and its corpus record does not
change.

**Fingerprints.** None move.

**Cost.**
- The twelve full histories the sweeps draw from (attrs, click, flask,
  httpx, rich, starlette, aiohttp, pytest, requests, scrapy, uvicorn and
  werkzeug: 80,252 commits) never hold a Python file beneath a `golden/`,
  `expected/` or `__snapshots__/` directory. So neither the obligations
  nor the three searches change anything there. The risk the ruling named,
  a Python golden output shaped like a test, does not occur in them.
- **Sweep, standard:** the last 300 non-merge commits of attrs, click,
  flask, httpx, rich and starlette (1,800 commits) give the same records
  as main's engine (#223's).
- **Sweep, targeted:** D-088's sets give the same records too: the 895
  commits of ten full histories that change a `conftest.py` or a
  `skip`/`xfail` line in a test file (855 readable), and the 368 commits of
  pytest's own history that touch a collection control in a conftest or a
  skip or xfail decorator in `testing/` (364 readable).

**Verdict gate.** It passes, with 0 failures and 1 reported (`i198/T6`,
undecided, pass -> pass). Every one of its 182 cases (156 T1, 26 T3) keeps
the runs and the transition of the candidate built from main's tree, the
version string aside, so no case is relabelled.

The agent wrote this entry in the fix PR, as the rulings' X.doc-batch asks;
the maintainer approves it there.

## D-097 (2026-10-05): the JS and task runners count where a command starts (#216)

checkwash decided whether a command runs the tests from row 69's runner
names (`roles._TEST_RUNNER_TOKENS`), which hold none of `node --test`,
`mocha`, `ava`, `tap`, `bun test`, `deno test`, `hatch test`, `just test`,
`poe test` or `pdm test`. A shell script whose only runner was one of them
stayed production, so `node --test` becoming `node --test || true` hid its
own swallow and bought the opaque exemption that held an assertion weakened
beside it at warn: row 87's double effect, which row 106 listed as a
residual. The same gap reached workflow steps (`if: false` under `- run: node
--test` passed at warn), pre-commit hooks (removing the only `node --test`
hook passed at warn), manifest scripts (a `ci` script running `mocha` gained
`|| true` unread) and the planting commit of #196 185.3. It also gave a false
reason: a pre-commit hook moving from `pytest` to `hatch test` blocked with
"no pre-commit hook entry invokes a recognised test runner any more (was:
pytest)".

Ruling, 2026-10-03 ([#196](https://github.com/taipei49314/checkwash/issues/196#issuecomment-5965834751), filed as #216):
one shared "invokes a test runner" predicate with 191.5's. The new names
match only in command content (runner-shaped scripts, workflow `run:`,
manifest script values, hook entries) and only in command position, never
as words over arbitrary file content. The opaque-exemption denial keeps
today's tokens. The round closes 185.3 and 191.7's false reason, and adds
`--test-only` (187.1) as a narrowing token. A sweep is mandatory; the
maintainer edits are THREATMODEL rows 87 and 106 and SPEC §4. No IR change.

**As implemented:**
- `runner_command.invokes_positional_runner` reads one text as bash, with
  191.5's lexer, and asks whether a simple command in it starts one of the
  new runners. `invokes_test_runner`, which runner sites read (a workflow
  step's `run:`, a `uses:` step's inputs, a hook's `entry`), asks it beside
  191.5's whole-word reading of row 69's names, now `invokes_named_runner`.
- `roles._runs_test_command` is row 69's token scan or the positional
  reading. It decides a runner-shaped script (§2's content gate), the
  script one hop away and whether the hop's own script runs a runner
  already, a manifest's members by command, ci.py's no-op branch
  (`if ! mocha; then :; fi`) and `-`-prefixed make recipe checks, and "the
  test suite is no longer invoked by this script".
- The deletion rule: a deleted workflow or pre-commit config ran a suite
  when row 69's token scan finds a runner in it or it holds a runner site
  (`ci_control_flow.holds_runner_site`).
- `--test-only` joins `_CI_NARROWING_TOKENS`.
- Unchanged, as ruled or as unrelated: the opaque-exemption denial
  (`_mentions_test_runner`); the collection inventory's own reading of
  commands (#173, `invokes_named_runner`); and the two Python-only readers
  that gate on row 69's scan, the pytest collection-settings scan of a ci
  file and the runtime-shadow reading of pytest invocations.

Readings the ruling leaves to the implementation:

1. **Command position.** The first word of a simple command, past reserved
   words (`if`, `!`, `do`), assignments (`NODE_ENV=test mocha`) and a make
   recipe's `@`, `-` and `+` prefixes. The reader follows:
   - wrappers that run the words after their options: `env`, `sudo`,
     `time`, `timeout`, `nice`, `nohup`, `exec`, `command`, `cross-env`,
     `nyc`, `c8`, `xvfb-run`. An option takes the next word as its value
     unless that word starts a command the reader follows, so `nice -n 10
     mocha` reaches mocha and `sudo -E apt-get install tap` reaches
     `install`. `timeout` takes its duration first. `command -v mocha` looks
     the name up and runs nothing;
   - package launchers that run the binary they name: `npx`, `pnpx`,
     `bunx`, `npm exec`/`x`, `pnpm exec`/`dlx`, `yarn exec`/`dlx`, `bun x`,
     and `yarn` or `pnpm` followed by `mocha`, `ava` or `tap`;
   - `sh`, `bash`, `zsh` and `dash` with `-c` (options such as `-o
     pipefail` read with their values), and `eval`;
   - the text of a command substitution, and a heredoc body a shell reads
     (`bash <<EOF`).
   Nesting of `sh -c`, `eval` and substitutions past four levels keeps every
   name it holds, as text the lexer cannot follow does under 191.5.
2. **The names.** `mocha`, `ava` and `tap` are binaries. `bun`, `deno`,
   `hatch`, `just`, `poe` and `pdm` count with a first argument that starts
   with `test`, past the tool's options, so the subcommand may go on (`just
   test-unit`, `poe test:fast`), as `make tests` does for `make test`.
   `pdm run test`, `hatch run test`, `deno task test` and `bun run test` run
   a named script whose content is not read; they are not in the ruled list.
   `node` runs its test runner when `--test` comes before a script argument
   (`.js`, `.cjs`, `.mjs`, `.ts`, `.cts`, `.mts`): `node app.js --test` hands
   the flag to the script, and `node --test-only` alone runs no runner.
3. **What runs nothing,** shared with 191.5: the words of `echo` and
   `printf`, comments, a heredoc body `cat` writes out, the packages an
   install command names (`npm i -D mocha`, `bun add tap`), and a word in
   any position but the first (`import { tap } from "rxjs"`, `x-node
   --test`).
4. **Text the lexer cannot follow** is split on its command separators and
   each piece is read from its first word. 191.5 counts every one of row
   69's names in such text; a new name counts only at a piece's start, or
   one unbalanced quote in a runner-shaped file would read every `tap` and
   `just` in its prose as a runner.
5. **The deletion rule** reads runner sites as well as row 69's scan.
   Removing the only `node --test` hook blocks (H4), and deleting the file
   it lives in would otherwise pass at warn. A dead site counts, as row
   69's scan counts `pytest` in a disabled step. A `.gitlab-ci.yml` is not
   read for sites, so a deleted GitLab pipeline whose only runner is a new
   name is reported at warn (residual). An emptied workflow, as against a
   deleted one, stays the residual row 112 already names ("deleting the
   step from a surviving workflow").
6. **The opaque-exemption denial keeps row 69's names**, as ruled. A
   runner-shaped script that runs a new runner is `ci` and grants no
   exemption; a changed file of no runner shape whose only runner is a new
   name still buys it (residual, row 87).
7. **The collection inventory** keeps row 69's names for the commands it
   reads: no new name runs a pytest command it could parse. A `uses:` step
   named for one of row 69's runners whose input runs a new name is now a
   runner site, and the inventory withholds for it, as for any step that
   runs a runner action.
8. **185.3** closes for a planted script that runs a recognised runner: the
   commit that writes `"unit": "mocha || true"` beside `"test": "jest"` now
   blocks. A planted script that runs none (`node scripts/run.js || true`)
   still costs only the CI finding when it is wired in.
9. **Indirection** is not read: a runner reached through a variable
   (`$RUNNER || true`), a computed `eval`, piped text (`echo mocha | sh`) or
   a heredoc body `cat` expands a substitution in. Row 69's names in the
   same places still count wherever the token scan reads them. A name the
   shell joins from quoted pieces (`m'o'cha`) is read here, since each word
   is dequoted, but not among row 69's names (`'py'test`): that gap is
   older than this round and is filed as #275.

**A pin changes (its own commit, for approval).**
`tests/test_manifest_test_commands.py::test_the_hop_is_exactly_one_and_needs_a_script_runner`
used `"b": "node --test"` as the script two hops from `test`. Under the
ruling `b` is a member by its own command, as M1 and P1 require of `"ci":
"mocha"` and `"unit": "mocha || true"`, so the pin's input becomes `node
scripts/report.js`, which runs no runner, and its assertion stays. The issue
lists this file under "Must not change"; that line and M1/P1 cannot both
hold.

**Tests and fixtures.**
- Tests: 118 in `tests/test_issue216_runner_vocabulary.py`: the
  reading of each runner and context, R1 to R6 and the four task runners as
  one parametrized pin, the swaps, the deletion rule, `--test-only` and the
  inventory's reading. All 34 mutants of the round's code fail them
  or the fixtures.
- Fixtures (12). Each `_pos` passes on v0.6.0 or, for M1, blocks on the
  assertion alone; each H `_neg` blocks there with the false reason:
  - `runner_script_node_test_swallow_pos` (R1, `bypass: 106`);
  - `ci_step_if_false_node_test_pos` (W1), `precommit_node_test_hook_removed_pos`
    (H4) and `ci_node_test_workflow_removed_pos` (`bypass: 112`);
  - `runner_package_json_mocha_script_swallow_pos` (M1),
    `runner_package_json_planted_mocha_swallow_pos` (P1, 185.3) and
    `runner_package_json_test_only_pos` (T1, 187.1) (`bypass: 106`);
  - `precommit_pytest_to_hatch_test_neg` (H1) and
    `precommit_pytest_to_just_test_neg` (H2);
  - `runner_word_rxjs_tap_honest_fix_neg`,
    `runner_word_in_production_script_prose_neg` and
    `ci_runner_word_not_in_command_position_neg`, which v0.6.0 passes too.
- Every fixture the issue lists under "Must not change" keeps its
  expectation, and so does every other existing fixture.

**Fingerprints.** CI_WORKFLOW_TOUCHED's fingerprint includes its reasons, so
a CI finding that gains or loses a reason moves: W1, H4, M1, P1, T1 and the
deletion gain one, and the H1/H2 swaps lose one. A runner script promoted to
`ci` (R1) gains a CI_WORKFLOW_TOUCHED finding. Every other finding keeps its
fingerprint: an ASSERT_WEAKENED that moves from warn to high keeps its own.

**Cost.**
- **Where the change can apply.** The twelve histories the sweeps draw
  from (attrs, click, flask, httpx, rich, starlette, aiohttp, pytest,
  requests, scrapy, uvicorn and werkzeug: 61,048 non-merge commits on their
  default branches) hold 6,941 commits that change a ci-role file, a
  `package.json` or `Pipfile`, a runner-shaped script or a file with a shell
  shebang. Both sides of every such file were read: 7,519 workflow and
  pre-commit config sides, 1,939 runner-shaped sides and 38 manifest sides.
  The new reading counts no command in them that row 69's names do not:
  none of these projects runs one of the ten runners in a workflow step, a
  hook, a manifest script or a runner-shaped script.
- **Sweep, targeted:** those 6,941 commits give the same records under
  main's engine and this tree's. 6,598 are readable; neither engine reads
  the rest, 307 of them aiohttp's submodule commits.
- **Sweep, standard:** the last 300 non-merge commits of attrs, click,
  flask, httpx, rich and starlette (1,800 commits) give the same records as
  main's engine (#223's).
- **Sweep, targeted by D-088:** its sets give the same records too: 895
  commits of ten full histories (855 readable) and 368 of pytest's (364
  readable).
- **Not measured:** the false-positive cost on JS projects, where the new
  names live. No JS/TS history replay exists yet (#212).
- **Time:** linear in the text, and bounded by the reader's 1 MB. A 1 MB
  runner-shaped script of 30,000 commands reads in about 0.6 s per call,
  and 1 MB of command substitutions in about 0.9 s. Real scripts are a few
  kilobytes.
- After the sweeps, `_dequote` gained a fast path: a word with no quote,
  escape or whitespace is returned as it is, which is what shlex returned
  for it. All 3,820 distinct words of the 32,595 CI texts in the targeted
  commits dequote the same both ways, and the fixture corpus is
  byte-identical before and after.

**Verdict gate.** It passes, with 0 failures and 1 reported (`i198/T6`,
undecided, pass -> pass). Every one of its 182 cases (156 T1, 26 T3) keeps
the runs and the transition of the candidate built from main's tree, the
version string aside, so no case is relabelled.

The agent wrote this entry in the fix PR, as the rulings' X.doc-batch asks;
the maintainer approves it there.

## D-098 (2026-10-05): composite action definitions are ci (#213)

A composite action's steps run inside the job that calls it, so
`.github/actions/test/action.yml` can hold a project's real test command.
The `ci` role covered `.github/workflows/**` and not the action definitions,
so `pytest || true` in one gave zero findings, as the same line in a
workflow does not. An action whose runner holds no runner token (`node
--test`) was opaque production and bought the opaque exemption, so an
assertion weakened beside it passed at warn. Row 112 listed composite
actions as a residual.

Ruling, 2026-10-03 ([#196](https://github.com/taipei49314/checkwash/issues/196#issuecomment-5965834751), filed as #213):
scope the default ci glob to the action definitions,
`.github/actions/**/action.yml` and `action.yaml`, not all of
`.github/actions/**`. Scripts an action calls are already promoted by
content. Later, feed composite `runs.steps` into the runner-site reader.
Costs: SPEC §2 and `DEFAULT_ROLES` (maintainer; pinned by
`tests/test_spec_roles_pinned.py`), composite edits warn, a sweep.

**As implemented:** the two globs join the `ci` row of `DEFAULT_ROLES` and of
SPEC §2's table, in one commit, as the pin requires. Nothing else changes:
an action definition is read as every other ci file is.

Readings the ruling leaves to the implementation:

1. **What the globs reach.** `fnmatchcase` lets `**` cross directories, so
   an action at any depth beneath `.github/actions/` matches
   (`.github/actions/python/test/action.yml`), and one directly in
   `.github/actions/` does not; GitHub resolves `uses: ./.github/actions/x`
   to a directory. A JavaScript action's source, a Docker action's
   `Dockerfile` and an action published from the repository root
   (`action.yml`, `action/action.yml`) keep their role.
2. **Beneath a test-support directory.** #217 gives a non-Python file
   beneath `test/` the test role, so `.github/actions/test/action.yml` was a
   test file on v0.6.0, read by no rule. A path the table resolves to a role
   keeps it, so the definition is ci there too.
3. **What reads it.** As a ci file, a definition loses the opaque exemption,
   and the added-line scan reads its swallows and the narrowings it
   introduces (`run: pytest --deselect …`). A Docker action's `action.yml`
   is a definition too, and its edits warn.
4. **Not in this round (residuals, row 112):** the runner-site reader does
   not read composite `runs.steps`, so `if: false` on a composite step reads
   at warn (A2); deleting an action definition is not a workflow deletion,
   so it reads at warn; an action defined outside `.github/actions/` is not
   a definition here.

**Tests and fixtures.**
- Tests: 15 in `tests/test_issue213_composite_actions.py`.
- Fixtures (5):
  - `ci_composite_action_swallow_pos` (A1) and
    `ci_composite_action_yaml_swallow_pos` (A1y), `bypass: 112`: v0.6.0
    passes both with zero findings;
  - `ci_composite_action_node_test_swallow_pos` (A5), `bypass: 112`: v0.6.0
    passes it with the weakened assertion at warn;
  - `ci_action_javascript_source_neg` (A3): a JavaScript action's
    `index.js` gaining `|| true` stays production, with zero findings;
  - `ci_composite_action_version_bump_neg`: a setup action bumped inside a
    definition reports CI_WORKFLOW_TOUCHED at warn.
- Every existing fixture keeps its expectation, including every `ci_*` and
  `runner_*` fixture and `circleci_weakened_pos`.

**Fingerprints.** A changed action definition now reports
CI_WORKFLOW_TOUCHED, which is new. Findings on other files keep theirs.

**Cost.**
- **Where the change can apply.** In the twelve histories the sweeps draw
  from (attrs, click, flask, httpx, rich, starlette, aiohttp, pytest,
  requests, scrapy, uvicorn and werkzeug: 80,252 commits across all refs),
  one commit touches `.github/actions/`: pytest's b3b2990 ("ci: reuse
  official uv pattern to install tox via composite action"), which adds
  `.github/actions/setup-tox/action.yml`. Under this tree's engine it
  passes as before, and the new definition reports CI_WORKFLOW_TOUCHED at
  warn, the cost the ruling names.
- **Sweep, standard:** the last 300 non-merge commits of attrs, click,
  flask, httpx, rich and starlette (1,800 commits) give the same records as
  main's engine (#223's).
- **Sweep, targeted by D-088:** its sets give the same records too: 895
  commits of ten full histories (855 readable) and 368 of pytest's (364
  readable).

**Verdict gate.** It passes, with 0 failures and 1 reported (`i198/T6`,
undecided, pass -> pass). Every one of its 182 cases (156 T1, 26 T3) keeps
the runs and the transition of the candidate built from main's tree, the
version string aside, so no case is relabelled.

The agent wrote this entry in the fix PR, as the rulings' X.doc-batch asks;
the maintainer approves it there.

## D-099 (2026-10-06): `.pytest.ini`, `pytest.toml` and `.pytest.toml` are ci files and inventory carriers (#221)

pytest 9 reads the first pytest config it finds among `pytest.toml`,
`.pytest.toml`, `pytest.ini`, `.pytest.ini`, `pyproject.toml`, `tox.ini` and
`setup.cfg`. The `ci` role listed `pytest.ini` alone of the first four, so the
other three were production, and no CI rule read them: `--deselect`, `-p
no:python` or a narrowed `testpaths` written into one gave zero findings,
while the same edit in `pytest.ini` blocked. The resolved collection
inventory left `pytest.toml` and `.pytest.toml` out of its carrier list and
judged only ci carriers, so a first configuration in any of the three gave
zero findings too, and so did a new `pytest.toml` beside `pytest.ini`, which
pytest then reads instead of it. THREATMODEL row 105 listed the three as
item (3).

Ruling, 2026-10-03 ([#196](https://github.com/taipei49314/checkwash/issues/196#issuecomment-5965834751),
item `196.followup.pytest-config-carriers`, filed as #221), and 221.Q1
(2026-10-04): the three join `pytest.ini` as root-anchored `ci` globs, in
SPEC §2 and `DEFAULT_ROLES` together, and take their place in the
inventory's carrier list. Nested configs stay out of this round (row 105,
item 5): `sub/pytest.toml` stays production, like `sub/pytest.ini`. Costs:
SPEC §2 and `DEFAULT_ROLES` (maintainer; pinned by
`tests/test_spec_roles_pinned.py`), fingerprints for these paths, a small
sweep.

**As implemented:**
- `DEFAULT_ROLES` and SPEC §2's table: `.pytest.ini`, `pytest.toml` and
  `.pytest.toml` follow `pytest.ini` in the `ci` row. SPEC §2b and §4's
  CI_WORKFLOW_TOUCHED row name them where they named the four pytest
  configs.
- `collection_inventory._CONFIGS`, the root configs the inventory reads and
  judges, lists all seven, in pytest's order.

Readings the ruling leaves to the implementation:

1. **Which file governs.** The inventory already picks the config pytest
   reads, in pytest's order (`shadow._pytest_config_path`), but from a
   snapshot that never held `pytest.toml` or `.pytest.toml`. With both read,
   a carrier pytest does not read is not the run's config. A `pytest.ini`
   added beside an existing `pytest.toml`, or a `.pytest.ini` beside
   `pytest.ini`, selects nothing, so the inventory does not judge its
   options, and it reads at warn as a first configuration does (SPEC §4).
   v0.6.0 blocked the `pytest.ini` beside `pytest.toml`, which the inventory
   took for the run's config; pytest 9.1.1 prints `configfile: pytest.toml
   (WARNING: ignoring pytest config in pytest.ini!)` and runs every test.
   Such a carrier is dormant, not harmless: deleting the file pytest reads
   hands the run to it, and the inventory judges that commit, so a
   `--deselect` waiting in the `pytest.ini` blocks when `pytest.toml` goes.
2. **The token scan and the syntax scanner** read the three as they read
   every ci file. An option or a narrowed setting written into an existing
   one is a weakened command. The base side of each joins the surface a
   narrowing must be absent from, so moving an identical configuration
   between any two carriers stays at warn, a `--deselect` the base already
   carried included. A new carrier has no narrowing family (SPEC §4, first
   adoption), so only the inventory judges a new `pytest.toml` beside
   `pytest.ini`.
3. **TOML values.** pytest 9 reads a list setting in `pytest.toml` and
   `.pytest.toml` only as an array (`addopts = ["--deselect", "..."]`; a
   string is a TypeError). The settings parser reads the `[pytest]` table's
   arrays as words, as it reads `[tool.pytest.ini_options]`'s, and the
   fixtures and tests write arrays.
4. **Root only.** The globs are anchored like `pytest.ini`'s, and roles match
   case-sensitively (§2): `sub/pytest.toml`, `docs/pytest.toml`,
   `pytest.toml.orig` and `Pytest.toml` stay production.
5. **Not in this round (residuals, row 105):** a nested config of any name
   (item 5), which the inventory reads only to withhold a targeted run
   (184.1); the other open items of row 105. pyproject's native
   `[tool.pytest]` table, which the settings parser does not read, is a
   separate defect found during this round (#278).

**Tests and fixtures.**
- Tests: 31 in `tests/test_issue221_pytest_config_carriers.py`. The carrier
  matrices of `tests/test_issue90_collection_matrix.py` and
  `tests/test_issue173_collection_suite.py` run the three carriers beside
  the four they list, TOML ones as arrays: 237 cases, whose four-carrier
  cases are unchanged. All 9 mutants of the change fail them or the
  fixtures: each glob dropped, each glob no longer anchored at the root,
  and each carrier dropped from the inventory's list.
- Fixtures (7):
  - `hidden_pytest_ini_deselect_pos` (A1), `pytest_toml_deselect_pos` (A2),
    `hidden_pytest_toml_deselect_pos` (A3), `pytest_toml_no_python_plugin_pos`
    (A5) and `pytest_toml_testpaths_pointed_away_pos` (A7), `bypass: 105`:
    v0.6.0 passes each with zero findings;
  - `pytest_toml_harmless_neg`: `xfail_strict = true` reads at warn, as
    `pytest_ini_harmless_neg` does;
  - `pytest_ini_moved_to_pytest_toml_neg`: an identical configuration, a
    `--deselect` among it, moved from `pytest.ini` into `pytest.toml` reads
    at warn on both files.
- Every existing fixture keeps its expectation, `pytest_ini_narrowed_pos`,
  `pytest_ini_harmless_neg` and `nested_pyproject_not_opaque_pos` among
  them.

**Fingerprints.** An edited `.pytest.ini`, `pytest.toml` or `.pytest.toml`
now reports CI_WORKFLOW_TOUCHED, which is new. Findings on other files keep
theirs.

**Cost.**
- **Where the change can apply.** No commit of the twelve histories the
  sweeps draw from (attrs, click, flask, httpx, rich, starlette, aiohttp,
  pytest, requests, scrapy, uvicorn and werkzeug: 80,252 commits across all
  refs) adds, edits or deletes a `.pytest.ini`, `pytest.toml` or
  `.pytest.toml`, at the root or nested, so no tree in them holds one, and
  neither the role change nor the carrier list can change a record there.
  `pytest.toml` and `.pytest.toml` are new in pytest 9; their share in other
  projects is not measured.
- **Sweep, standard:** the last 300 non-merge commits of attrs, click,
  flask, httpx, rich and starlette (1,800 commits) give the same records as
  main's engine (#223's).
- **Sweep, targeted by D-088:** its sets give the same records too: 895
  commits of ten full histories (855 readable) and 368 of pytest's (364
  readable).

**Verdict gate.** It passes, with 0 failures and 1 reported (`i198/T6`,
undecided, pass -> pass). Every one of its 182 cases (156 T1, 26 T3) keeps
the runs and the transition of the candidate built from main's tree, the
version string aside, so no case is relabelled.

The agent wrote this entry in the fix PR, as the rulings' X.doc-batch asks;
the maintainer approves it there.

## D-100 (2026-10-06): a test body's skip is read through its imports, and a raised skip is a skip (#220)

The frontend read a skip in a test body by four literal dotted spellings
(`pytest.skip`, `pytest.xfail`, `pytest.importorskip`, `self.skipTest`). So
`pt.skip()` after `import pytest as pt`, and a bare `skip()`, `xfail()` or
`s()` imported from pytest, passed with zero findings. A raised skip
(`raise unittest.SkipTest(...)`, `raise SkipTest(...)`,
`raise pytest.skip.Exception(...)`) ended the body like a `return`, so it
blocked as ASSERT_REMOVED "assertion removed", a false reason: the assertion
is still there, and pytest reports the test skipped. The same calls and
raises in a fixture the test requests were read (#172), so one act had two
outcomes. And the closed `pytest_runtest_setup` proof ended at any top-level
statement other than `import pytest`, a `from pytest import` of four names or
a function, so an always-skipping hook beside `import sys`, or #199 H2's
`import unittest` with `raise unittest.SkipTest`, passed with zero findings.

Ruling, 2026-10-03 ([#196](https://github.com/taipei49314/checkwash/issues/196#issuecomment-5965834751),
item `196.followup.body-skip-aliases`, filed as #220): the test body uses the
setup path's outcome resolver (`_OUTCOME_CALLS`/`_OUTCOME_RAISES`, with import
bindings), the literal `_SKIP_CALLS` set is retired, and #199 H2's hook
spelling is covered. 220.Q1 (2026-10-04): a body `pytest.importorskip(...)`
stays TEST_DISABLED, as a body-only entry of the shared resolver, and a
fixture pins it. 220.Q2: J4 and J5, which come from #172's sibling-fixture
narrowing, stay a named residual. Costs: frontend only; the raise forms move
to TEST_DISABLED, so their fingerprints change; a Python sweep; a
THREATMODEL row.

**As implemented:**
- `setup_skip_controls.body_outcome` names the native outcome a body's call
  or raise spells: the calls and raises the setup path reads, plus
  `pytest.importorskip` (`BODY_OUTCOMES`). The frontend mints the body's
  skip marker under that object's one name (`BODY_MARKERS`), so `pt.skip()`
  is `pytest.skip` and a raised one is `unittest.SkipTest` or
  `pytest.skip.Exception`.
- The shared table gains trial's `twisted.trial.unittest.SkipTest`, and
  Twisted's trial modules bind as native ones.
- `_unreachable_ids`: a raise read as such an outcome does not end the body.
- `_skip_call_guards` records a raise's `if` guard as it records a call's.
- `ir.markers.GUARDED_SKIP_CALLS` and D6's gate calls name every body
  marker but `importorskip`; `conftest_controls.marker_kind` classes every
  one as a body skip call.
- The closed hook proof (`setup_skip_controls()`) reads every import's
  bindings.

Readings the ruling leaves to the implementation:

1. **What a name resolves to.** The module's final top-level bindings,
   shadowed by the test's own: its parameters, the names it assigns, and a
   method's first parameter, which is the instance, so `self.skipTest`
   resolves whatever the instance is called. An import inside the test binds
   as one at module level does. Unlike the setup proof, a module-level
   assignment to an attribute (`unittest.TestCase.maxDiff = None`) shadows
   nothing for the body: the body errs toward reading a skip, as the literal
   set did, while the setup proof must establish one.
2. **An unbound root keeps its spelling.** `pytest.skip(...)` written with no
   import still names pytest's skip, as the literal set read it, and so does
   `self.skipTest` outside a class.
3. **Any arguments, any cause.** The setup proof needs plain arguments to
   show that every run ends in the outcome. A body skip that computes its
   reason, or a raise `from` a cause, still ends the test skipped, or the
   test errors first; it never passes.
4. **A raised skip is a skip.** It no longer ends the body for the
   assertions after it: they stay the test's, and the finding is
   TEST_DISABLED where it was ASSERT_REMOVED, as for `pytest.skip()`.
5. **Guards.** Every spelling records its guard and is judged as
   `pytest.skip()` is: held by D6 under a platform guard (D2, D3), reported
   when its `if` or `except` guard is removed (183.2) or made always true
   (row 54).
6. **The hook proof.** An import binds each name it names, to a native
   module or to nothing the proof reads; a relative import too. A star
   import still ends the proof, as does any other statement that runs code,
   and a sibling fixture that is not yield-only or another hook (J4, J5,
   220.Q2).
7. **One object, one name.** pytest's outcomes live in `_pytest.outcomes`,
   and Twisted's trial exports unittest's own `SkipTest` class under its
   name (`SkipTest = pyunit.SkipTest` in Twisted 17.1,
   `from unittest import SkipTest` in 25.5). A marker carries the object's
   one name: `_pytest.outcomes.skip` is `pytest.skip`, `Skipped` is
   `pytest.skip.Exception`, and `unittest.case.SkipTest` and trial's
   `SkipTest` are `unittest.SkipTest`. So trial's spelling, the one scrapy
   writes, is read, and a skip respelled from one name of its object to
   another is the skip the test already had. The round's first sweep
   measured the other choice: reading unittest's name alone made scrapy
   bb15c93a2bbd, which respells a guarded `raise unittest.SkipTest` from
   trial's `unittest` to unittest's `SkipTest`, block as a new skip.
8. **Cost of reading.** A test's own bindings are worked out only for a call
   or raise whose root can spell an outcome: a native module's name, a name
   bound to one, the instance, or a name the module imports inside a
   function, which is looked for only when an import line is indented.
9. **Not in this round (residuals, row 118):** `pytest.importorskip` in a
   fixture records nothing (220.Q1); a skip reached through a helper the
   test calls (#272); trial's `skip` and `todo` attributes, which the
   round's sweep brought up and which are neither calls nor raises (#280);
   a module-level `pytest.skip(..., allow_module_level=True)`,
   still matched by its last name (row 31); a `pytest` or `unittest` the
   module or the test rebinds to something else.

**Tests and fixtures.**
- Tests: 52 in `tests/test_issue220_body_skip_aliases.py`.
  `tests/test_conftest_controls.py` lists where the frontend mints marker
  names, as its own failure message asks: the body's site is now
  `skip = outcome_of(node)`, minting `BODY_MARKERS`, where it was
  `name = _dotted(...)` filtered by `_SKIP_CALLS`. Its assertions do not
  change. All 27 mutants of the round's code fail the tests or the
  fixtures.
- Fixtures (17):
  - row 118's pins, each passing on v0.6.0 with zero findings unless noted:
    `body_skip_module_alias_pos` (B1), `body_skip_imported_name_pos` (B2),
    `body_xfail_imported_name_pos` (B3), `body_skip_imported_alias_pos` (B4),
    `body_raise_unittest_skiptest_pos` (B5), `body_raise_imported_skiptest_pos`
    (B6), `body_raise_pytest_skip_exception_pos` (B7),
    `testcase_raise_skiptest_pos` (B8) and `testcase_raise_trial_skiptest_pos`
    (B8 in trial's spelling), which v0.6.0 blocks as ASSERT_REMOVED,
    `conftest_hook_skip_beside_other_import_pos` (J2) and
    `conftest_hook_raise_skiptest_pos` (J3);
  - `body_importorskip_pos` (B9, 220.Q1): TEST_DISABLED, as on v0.6.0;
  - `compat_gate_guarded_raise_skiptest_neg` (D2) and
    `compat_gate_guarded_aliased_skip_neg` (D3): TEST_DISABLED at warn with
    COMPAT_GATE, as D1; v0.6.0 passes both with zero findings;
  - `body_skip_unrelated_module_neg`, `body_skip_rebound_name_neg` and
    `body_skip_respelled_from_trial_neg` (scrapy bb15c93a2bbd's respelling):
    zero findings.
- Every existing fixture keeps its expectation, among them the ones the
  issue lists: `test_disabled_skip_pos`, `skiptest_call_pos`,
  `aliased_skip_marker_pos`, `module_level_skip_pos`, `early_return_pos`,
  `sacrificial_skip_pos`, `conftest_skip_hook_pos`,
  `fixture_skip_conftest_pos`, `fixture_skip_module_usefixtures_pos`,
  `fixture_skip_conftest_fallback_neg`, `compat_gate_guarded_call_neg` and
  `compat_skipif_neg`.

**Fingerprints.** A raised skip in a test body reports TEST_DISABLED where
it reported ASSERT_REMOVED, so those findings move, as the ruling names. A
unit that disappears with a raised skip in its body is fingerprinted with
the assertions after the raise, which are now the test's (scrapy
09ce0ef52681). A skip spelled through an alias is a new finding. A skip
spelled literally keeps its marker name, and its finding keeps its
fingerprint.

**Cost.** Measured with the round's engine against main's (`6e4f5ef`):
- **Standard set:** the last 300 non-merge commits of attrs, click, flask,
  httpx, rich and starlette (1,800 commits) give the same records as main.
- **D-088's sets:** 895 commits of ten full histories (855 readable) and 368
  of pytest's (364 readable), as on main. 12 records differ, all in scrapy,
  and 2 verdicts move (26c70318cb14 and 7a51d370f3a5). Eleven of the twelve
  are commits of the targeted set, below. The twelfth, 5a605969bd
  ("Converting tests to plain asserts, part 2"), changes two disappearances'
  severity as 1843a4f75358 does, and main gives the same under the
  respelling check.
- **Targeted set:** every non-merge commit of the twelve histories whose
  test-side Python changes a skip spelled through an alias or an imported
  name, a raised skip, `_pytest.outcomes`, a `pytest_runtest_setup` or a
  `twisted.trial` import: 317 commits (aiohttp 7, pytest 84, scrapy 223,
  werkzeug 3), 308 readable, as on main.
  - 29 records differ, all in scrapy, and 11 verdicts move: 10 from pass to
    block, 1 from block to pass.
  - Respelling check: main's engine was run on each of the 29 commits with
    every raised skip respelled `pytest.skip(...)` (and `import pytest` on
    top). It gives the round's verdict and findings, marker names aside, on
    27. On the other two it reproduces the round's changes, and the
    respelling itself moves findings that main and the round report alike:
    on 380c2279b92f it makes six skip-only overrides identical across a
    class rename; on d8251332845d it hides #281's findings (below).
  - **Newly blocking, a skip added to an existing test (9):** a raised
    `SkipTest` under an environment condition: `if NON_EXISTING_RESOLVABLE:`
    (26c70318cb14, three tests), a Twisted version, a reactor or Python 2
    (906626cf0bef, fea5a1189938, cd193827546d, 494643458270), a CI image
    (ea8be627d15a), clock precision (eb9377425661), an optional import
    (3daf473686aa), and in `setUp` (e995c5c7ff26). Each blocks as
    `pytest.skip()` in the same place blocks on main: a new skip in an
    existing test, which the reviewer allowlists when it is honest.
  - **Newly blocking, a false positive (1):** af73f141b23a moves an http2
    test class verbatim to a new file, six skip-only overrides among it. The
    arrivals now carry their skip, so they earn no move credit, which asks
    for a live arrival. main blocks the same move in `pytest.skip()`'s
    spelling; filed as #282.
  - **Newly passing (1):** 7a51d370f3a5 deletes a test whose first statement
    was an unconditional `raise unittest.SkipTest`. Its assertion is now the
    test's, and it calls `guess_scheme`, which the commit changes, so the
    disappearance has repair evidence and holds at warn.
  - **The rest move no verdict:** a raised skip blocks as TEST_DISABLED
    where it blocked as ASSERT_REMOVED (81a90c3af65c), or as a removed guard
    (b44bd6f82505, e18014d84d05); disappearances change severity as the
    restructure and rename credits count a unit with a raised skip as
    skipped (1843a4f75358, 380c2279b92f, a724541a715b, d161d1d47d44); a
    disappearance is fingerprinted with the assertions after its raise
    (09ce0ef52681); a commit that blocked already adds raised skips, now
    reported at high (2f1d345e74d1, 98c060d0b2cc, d6bea3bf2eb4); new raised
    skips are reported at warn, held by COMPAT_GATE under a platform guard
    (397d21f1f511, ab5ea32ffd9c, c5ab58056c29, d7024dcd3373) or by repair
    evidence (036f3e562716, 25e481fd14b2); and a `setUp` skip the base
    raised in trial's spelling is no longer read as added when the head
    spells it `pytest.skip()` (d8251332845d).
- **Not changed by this round:** a skip respelled from one API to another
  (`raise unittest.SkipTest` or `self.skipTest` to `pytest.skip`) still
  reads as a new skip: scrapy d8251332845d (#6873, "Reduce deps on
  unittest") gives 54 such findings, 51 high, on main and here alike; filed
  as #281.

**Verdict gate.** It passes, with 0 failures and 1 reported (`i198/T6`,
undecided, pass -> pass). Every one of its 182 cases (156 T1, 26 T3) keeps
the runs and the transition of the candidate built from main's tree, the
version string aside, so no case is relabelled. `i199/H2`, whose base
conftest holds #199 H2's hook (`import unittest`, then `raise
unittest.SkipTest` in `pytest_runtest_setup`), now gives that hook its
runtime marker. 199.Q1 keeps a runtime control out of the inventory's
withhold, so the case's new `pytest.ini` still blocks, as the ruling's
ordering note required.

The agent wrote this entry in the fix PR, as the rulings' X.doc-batch asks;
the maintainer approves it there.

## D-101 (2026-10-06): places, delta and abs are compared as one absolute bound (#196 190.3)

A tolerance change took the new side's kind, and a bare value was read as
that kind. Python records unittest's `places` and `delta` bare, so
`assertAlmostEqual(x, y, places=7)` -> `delta=7`, which widens the check
from 5e-8 to 7, passed with zero findings: the two sevens read as one delta
left alone. `places=2` -> `delta=0.5` passed too, as a delta shrinking from
2. `places=2` -> `delta=10` was reported as "delta=2 -> delta=10", a false
statement, and `delta=5` -> `places=3`, a tightening, blocked as places
shrinking from 5 to 3. A hand-rolled `abs(x - c) < 0.01` or
`pytest.approx(c, abs=0.01)` rewritten into an equal `delta=0.01` blocked as
new slack, and into `places=3` too. JavaScript compared `toBeCloseTo`
precision with an `abs=` bound in one unit since #179, by a reading only
JavaScript files took.

Ruling, 2026-10-03 ([#196](https://github.com/taipei49314/checkwash/issues/196#issuecomment-5965834751),
item 196.190.3): one language-neutral helper converts places p to
5x10^-(p+1) from digits and compares it with delta/abs as a Decimal, shared
with 190.4. Costs: a SPEC edit, new Python blocks and message text, the
1,800-commit sweep; fingerprints are unchanged; numpy's `decimal` (1.5x10^-d)
must not reuse the helper unchanged. Ruling 196.spec.4-tolerance-loosened
words the SPEC row after 190.3 and 190.4: "tolerances are compared as
absolute bounds where a conversion is defined (places p -> 10^-p/2),
otherwise per kind, via Decimal".

**As implemented:**
- `detectors/tolerance_loosened.py`: `_absolute_bound` is the helper,
  JavaScript's `_js_absolute` made language-neutral. `_mixed`, which replaces
  `_js_mixed`, compares a pair of two different absolute kinds through it in
  any file.
- `ir/diffalign.py` (maintainer-owned alignment, written by the agent for the
  maintainer's sign-off): a change still takes the new side's kind, and an
  old bare value of another kind is keyed with its own, `places=7` or
  `delta=0.5`, the form an `abs=` bound already has. Such a change is
  recorded even when its two numbers are equal.
- SPEC §4's TOLERANCE_LOOSENED row takes the wording of ruling
  196.spec.4-tolerance-loosened. THREATMODEL row 119 (new, Closed) records
  the bypass; row 113's residual keeps only a bound rewritten into a
  relative tolerance.

Readings the ruling leaves to the implementation:

1. **Which kinds state an absolute bound.** `abs` (a single `abs=`, from
   `pytest.approx`, a hand-rolled `abs(a - b) < bound` in either language,
   or chai's `closeTo`), unittest's `delta`, and decimal places (unittest's
   `places`, `toBeCloseTo`'s precision). A relative tolerance, among them
   `pytest.approx`'s default `rel=1e-06`, and several tolerances at once
   state none, so a pair with one of them is compared per kind, as before: a
   kind the old side did not have is new slack.
2. **The conversion.** unittest passes `assertAlmostEqual(a, b, places=p)`
   when `round(a - b, p) == 0`, which holds below 5x10^-(p+1), the bound
   Jest's `toBeCloseTo(x, p)` states, so one helper serves both, written from
   the digits. Places must be integral, from -308 through 307, as JavaScript
   already required: past that a double holds no such bound, and the pair is
   no finding. Bounds are compared as values: `delta` passes at the bound and
   places only below it, an edge #179 already set aside (`< 0.005` and
   `toBeCloseTo(x, 2)` are equal).
3. **A side that cannot be read** (`places=N`, `delta=EPS`) is no finding,
   as in JavaScript: no guess, no noise.
4. **One rule for both languages.** The reading no longer asks which
   language the file is in. JavaScript's results are unchanged: a JS bare
   value is always `toBeCloseTo` precision, and alignment now says so. The
   pin `tests/test_js_handrolled_tolerance.py::test_the_cross_unit_reading_is_javascript_only`
   held that a Python file is not read this way, which the ruling reverses.
   It becomes `test_the_cross_unit_reading_is_one_rule_for_both_languages`,
   and its other five rows keep their results.
5. **Negated comparisons** (#284, found in this round). `assertNotAlmostEqual`
   passes when the values are far apart, so its tolerance orders the other
   way, and the frontend reads a negated `approx` as positive. The per-kind
   comparison already read both in the positive direction. This round reads
   a negated pair of two kinds the same way, so
   `assertNotAlmostEqual(..., places=2)` -> `delta=0.5`, a tightening for
   that assertion, blocks. #284 fixes both.

**Tests and fixtures.**
- Tests: 109 in `tests/test_tolerance_absolute_bound.py`, one of them
  holding the places bound to `unittest.TestCase.assertAlmostEqual` itself.
  All 21 mutants of the round's code fail the tests or the fixtures.
- Fixtures (6): row 119's pins `almost_places_to_delta_same_digits_pos`,
  `almost_places_to_delta_pos` and `almost_delta_to_places_pos`, which
  v0.6.0 passes with zero findings; the controls
  `almost_delta_to_places_tightened_neg`,
  `handrolled_bound_to_delta_same_bound_neg` and
  `approx_abs_to_delta_same_bound_neg`, which v0.6.0 blocks as
  TOLERANCE_LOOSENED.
- Every existing fixture keeps its expectation.

**Fingerprints.** A TOLERANCE_LOOSENED fingerprint is the change's kind and
its old value as the frontend recorded it, so the detector reads a keyed
old value back bare: every finding reported before keeps its fingerprint.
Messages change where the old value was mislabelled: "delta=2 -> delta=10"
reads "places=2 -> delta=10", and "rel=2 -> rel=1e-06" reads
"places=2 -> rel=1e-06". New findings are new fingerprints; findings that go
(a tightening or an equal bound across kinds) are FPs gone.

**IR.** `--emit-ir` shows the keyed old value in `tolerance_changes`
(`["delta", "places=7", "7"]`), the form `abs=` values already have. No
field is added or renamed, and IR_VERSION stays 2. One corpus record
changes: `js_evidence_closeto_infinity_pos`'s change reads `places=2` where
it read `2`. Its findings are byte-identical.

**Cost.** Measured with the round's engine against main's (`6e4f5ef`):
- **Standard set:** the last 300 non-merge commits of attrs, click, flask,
  httpx, rich and starlette (1,800 commits) give the same records as main.
- **D-088's sets:** 895 commits of ten full histories (855 readable) and
  368 of pytest's (364 readable) give the same records as main.
- **Targeted set:** every non-merge commit of the twelve histories whose
  test-side Python changes an `assertAlmostEqual` or
  `assertNotAlmostEqual`, a `places=` or `delta=` keyword, a
  `pytest.approx` or a builtin `abs(` call: 111 commits (aiohttp 16, httpx
  4, pytest 79, requests 2, scrapy 10), 99 readable, as on main. They give
  the same records as main. Their readable commits record 4 tolerance
  changes, in 3 commits, each within one kind (2 `abs`, 2 `rel`): none of
  the twelve histories rewrites a tolerance into another kind there. The
  round's new findings are the shapes the fixtures pin, which v0.6.0
  passes, or blocks for a false reason.

The agent wrote this entry; the maintainer approves it in the round's PR.

## D-102 (2026-10-06): Python tolerance calls are read as the approximate comparisons they are (#222)

`assert math.isclose(total(), 78.75, abs_tol=1e-9)` was a truthy assertion
with no tolerance, so widening `abs_tol` to `1e3` passed with zero findings
while the same widening in `pytest.approx` blocked. numpy's and torch's
assertion calls were no assertions at all: widening
`numpy.testing.assert_allclose`'s `rtol` passed, and so did deleting the
call.

Ruling, 2026-10-03 ([#196](https://github.com/taipei49314/checkwash/issues/196#issuecomment-5965834751),
item 196.followup.python-isclose-tolerance, filed as #222): one
tolerance-call table that maps to APPROX and feeds TOLERANCE_LOOSENED. It
covers math.isclose, numpy.isclose/allclose/testing.assert_allclose (rtol,
atol), assert_array_almost_equal (decimal) and torch.testing.assert_close,
recording each absent keyword's default, and each call keeps its own
conversion: numpy's decimal is 1.5x10^-d, not unittest's places. Costs:
frontend only; findings on existing isclose lines change from TRUTHY to
APPROX; a Python sweep; a THREATMODEL row. Rulings of 2026-10-04
([#222](https://github.com/taipei49314/checkwash/issues/222#issuecomment-5981757771)):
the table records the expected argument too (222.Q1); `assertTrue(<call>)`
is read as the call it wraps (222.Q2); torch's omitted pair is unknown, not
float32's default (222.Q3).

**As implemented:**
- `frontends/python/tolerance_calls.py` (new): the table. Each entry names
  the call's tolerances (keyword, recorded key, position, default), the
  keywords of its two values, and whether it is a predicate (`isclose`,
  `allclose`) or an assertion written as a statement. It also reads the
  file's bindings.
- `frontends/python/frontend.py`: a predicate in an `assert` or in
  `assertTrue`/`assertFalse`, and a statement call in a test or in a
  same-file helper the test calls, are recorded as approx/APPROX with their
  tolerances, subject and expected value, as `assertAlmostEqual` records
  its own.
- `detectors/tolerance_loosened.py`: `decimal` is a kind of its own. It
  loosens as it shrinks, and against another absolute kind it is the bound
  1.5x10^-d, beside D-101's places conversion.
- `detectors/assert_weakened.py`: a known tolerance replaced on the same
  subject by one that cannot be read is an unverifiable replacement in
  Python too, which is 222.Q3's cost. It was JavaScript's alone, because
  until now every Python approximate comparison recorded a tolerance.
- The ruling's costs say "frontend only". numpy's own conversion and
  222.Q3's unverifiable replacement are judged where tolerances are
  compared, so the two detectors change too. No strength value, gating row
  or alignment parameter changes.
- SPEC §3's lattice row 70 and §4's TOLERANCE_LOOSENED and ASSERT_WEAKENED
  rows name the calls. THREATMODEL row 120 (new, Closed) records the
  bypass, and row 119's residual drops what row 120 reads.

Readings the ruling leaves to the implementation:

1. **The table.** `math.isclose(a, b, *, rel_tol=1e-09, abs_tol=0.0)`;
   numpy's `isclose` and `allclose` (`rtol=1e-05, atol=1e-08`, also as the
   third and fourth arguments); `numpy.testing.assert_allclose`
   (`rtol=1e-07, atol=0`, the same positions);
   `numpy.testing.assert_array_almost_equal` (`decimal=6`, also the third
   argument); `numpy.testing.assert_almost_equal` (`decimal=7`), the scalar
   spelling of the same comparison, which the ruling does not name; and
   `torch.testing.assert_close(actual, expected, *, rtol=None,
   atol=None)`. `abs_tol` and `atol` record as `abs=`, `rel_tol` and `rtol`
   as `rel=`, sorted and joined as `pytest.approx` records several, and
   `decimal` as `decimal=d`. The defaults are those numpy 2.3.3 and CPython
   3.11 state, checked in a scratch environment along with the 1.5x10^-d
   boundary; torch's are read from its v2.8.0 source.
2. **Bindings.** Every import in the file, at any depth, and a name
   assigned `pytest.importorskip("numpy")`, plainly, annotated or with
   `:=`; `math`, `numpy` and `torch` by those names when nothing binds
   them. A name bound to two different targets, or also bound by a
   definition or another assignment, is not read: no guess.
3. **The expected value (222.Q1).** The second value (`b`, `desired`,
   `expected`), or the first when only it is a literal: the flip
   `assertEqual` has. A test that writes `assert_allclose(reference,
   computed)` has its computed value read as the expected one, as
   `assertEqual(reference, computed)` does.
4. **Where a call is read.** A predicate in an `assert`, also through a
   call around it (`np.isclose(a, b).all()`, `np.all(np.isclose(a, b))`,
   `all(math.isclose(x, y) for ...)`), and in `assertTrue` or
   `assertFalse` (222.Q2). A statement call where it stands, in a test or
   in a same-file helper the test calls. A fixture and a helper in another
   file lend the test their bare `assert`s only, so their calls are not
   lent (#286, found in this round). Whether a call can fail at all
   (`trivial`, which keeps padding out of compensation) is judged on its
   two values in every spelling, as `assertAlmostEqual`'s is.
5. **Negation.** A negated predicate passes when the values are far
   apart, so its tolerance orders the other way: it is recorded without
   one, as JavaScript records a negated `toBeCloseTo` (#284 does the same
   for `pytest.approx`).
6. **What cannot be read.** A tolerance that may come through `*args` or
   `**kwargs`, a value a starred argument may stand for, and torch's
   omitted pair (222.Q3) are unknown. A known tolerance replaced by an
   unknown one on the same subject is ASSERT_WEAKENED's unverifiable
   replacement; unknown on both sides is silent. A keyword-only tolerance
   is never read from a position, where it is a TypeError. A name or an
   expression is recorded as written, as `pytest.approx`'s is.
7. **The comparison.** As `pytest.approx`'s: `abs=` and `rel=` loosen as
   they grow, several at once are compared kind by kind, and numpy's
   `decimal` is compared with another absolute kind as 1.5x10^-d. So
   `math.isclose(abs_tol=1e-9)` -> `pytest.approx(abs=1e-9)` keeps the
   absolute bound and is no finding. A `decimal` rewritten into
   `assert_allclose`'s pair, as numpy's documentation recommends, is
   several tolerances against one: compared kind by kind, it reads as new
   slack (row 119's residual) even where the new bound is tighter.

**Tests and fixtures.**
- Tests: 108 in `tests/test_tolerance_calls.py`. Of 53 mutants of the
  round's code, 49 fail the tests or the fixtures. The 4 that survive
  change nothing: the import reading's two checks that a target is math,
  numpy or torch repeat the table lookup that follows them; the table
  already lists each call's tolerances in key order, so dropping the sort
  changes no record; and the Python frontend records no predicate, so
  lifting the JavaScript-only guard on a lost hand-rolled bound reaches no
  Python pair.
- Fixtures (19): row 120's 14 pins, which v0.6.0 passes with zero
  findings (#222's I1-I4, N1-N6, T1, T2, X1, and the dropped torch pair);
  `tolerance_call_assert_true_isclose_pos` (I5) and
  `tolerance_call_to_approx_widened_pos` (X3), which v0.6.0 blocks as
  SUBJECT_INPUT_CHANGED and EXPECTED_VALUE_CHANGED; and the controls
  `tolerance_call_isclose_tightened_neg` and
  `tolerance_call_decimal_tightened_neg`, which v0.6.0 passes, and
  `tolerance_call_to_approx_same_bound_neg`, which v0.6.0 blocks as
  EXPECTED_VALUE_CHANGED.
- Every existing fixture keeps its findings and its IR byte for byte,
  among them the twelve #222 lists as must-not-change.

**Fingerprints, messages and IR.**
- I5's finding changes rule (SUBJECT_INPUT_CHANGED -> TOLERANCE_LOOSENED),
  as 222.Q2 says, and so does X3's (EXPECTED_VALUE_CHANGED ->
  TOLERANCE_LOOSENED): new fingerprints.
- A finding on a predicate the frontend recorded before keeps its
  fingerprint, which is the assertion's text; its message names strength
  APPROX where it named TRUTHY.
- TEST_DISABLED's identity is the removed unit's recorded assertions, so a
  removed unit that held a numpy or torch assertion call, recorded now,
  gets a new fingerprint.
- IR: the new assertions appear in `--emit-ir` as approx records; no field
  is added or renamed, and IR_VERSION stays 2.

**Cost.** Measured with the round's engine against the base branch's
(`ef17bd1`, #196 190.3), whose records on the standard and D-088 sets are
main's (D-101):
- **Standard set:** the last 300 non-merge commits of attrs, click,
  flask, httpx, rich and starlette (1,800 commits) give the same
  records.
- **D-088's sets:** 895 commits of ten full histories (855 readable) and
  368 of pytest's (364 readable) give the same records.
- **Targeted set:** every non-merge commit, on any ref, of the twelve
  histories and of PyWavelets (`PyWavelets/pywt` at `c9b542b2d2c3`, a
  numpy library whose tests use `numpy.testing` throughout) whose
  test-side Python adds or removes a line naming `isclose`, `allclose`,
  `assert_array_almost_equal`, `assert_almost_equal` or `assert_close`:
  180 commits (aiohttp 6, pytest 7, PyWavelets 165, uvicorn 2), 171
  readable, as on the base. Only PyWavelets' records change, 38 of its
  165, and its blocked commits go from 10 to 26: 17 newly block and 1
  newly passes.
- **PyWavelets' last 300 non-merge commits:** one record changes, and
  its commit newly blocks (5 -> 6 blocked).

The 19 verdicts that move, read one by one:
- **4 real loosenings**, the bypass this round closes: `rtol` and `atol`
  1e-6 -> 1e-5 in `d1b49af3ec4b` and `486614cb19b0` ("relax tolerance"),
  `atol` 0 -> 1e-14 in `40a34ebdc1a0` ("fix resulting test failures"),
  and `atol` 0 -> 1e-13 in `4c2534cceda7` ("atol=0 doesn't work well").
  The first three block on TOLERANCE_LOOSENED alone.
- **15 move under rules that existed before**, which now read numpy's
  assertion calls: EXPECTED_VALUE_CHANGED, EXPECTATION_DEFINITION_CHANGED,
  SUBJECT_NORMALIZED, ASSERT_SUBSTITUTED, and TEST_DISABLED's grade. They
  give exactly what those rules give the same assertions written
  `self.assertAlmostEqual(A, B)` with the same two arguments: rewriting
  each tolerance call of the 19 commits that way and running the base
  engine reproduces every finding outside TOLERANCE_LOOSENED, 19 commits
  of 19.
  - 2 are changes the rules exist for: `57b21c42e21c`'s expected list
    gains an element for a new mode, and `4c2534cceda7` rewrites what it
    compares against.
  - 12 are refactors those rules cannot tell from a rewrite: a literal
    moved into a variable (`cd2615778141`, `f28ad2032110`,
    `73f9a8d7daea`, `b9a9e820417d`, `ff32cc38f21d`); an expectation
    renamed, restructured or extended with new cases (`7ef597740dab`,
    `f75f9976b124`, `cd8f4f793a6b`, `08260ec52ebc`); a numpy deprecation
    fix (`c81d78e32491`, list -> tuple indexing; `95e4d5fa4682`,
    `np.float` -> `np.float64`); and `.data` added while a disabled test
    was enabled (`f78120f7f290`).
  - 1 is both: `ddda4dd3ae99` renames its variables (ASSERT_SUBSTITUTED)
    and rewrites `decimal=6` into `assert_allclose`'s pair, which reads as
    new slack (row 119's residual) though the new bound is tighter for
    the values it compares.
  - 1 newly passes: `28475325f2d5` replaces a test with a broader one in
    the same file, and TEST_DISABLED grades the removal warn instead of
    high now that the new test's assertion is read.
- The 20 records that change without moving a verdict: 8 change only a
  TEST_DISABLED fingerprint, and 12 gain or regrade findings on commits
  that also change production code (warn) or already block.
- Fingerprints: in the PyWavelets sets the only fingerprints that change
  are TEST_DISABLED's, 24 findings, each reported again under a new one.

The agent wrote this entry; the maintainer approves it in the round's PR.

## D-103 (2026-10-06): Python comparisons carry a direction (#224)

The Python frontend recorded `<`, `<=`, `>` and `>=` as one form,
`compare_ord`, with no direction. `assert total() < 80` -> `assert total()
> 80` changed what the test proves and passed with zero findings, and so did
`<=` -> `>=`, the flip with the literal on the left, `assertLess` ->
`assertGreater` and a hand-rolled `abs(d) < 0.01` -> `> 0.01`, which blocked
only as the centre rewritten into the bound. `< 80` -> `not >= 80` was
reported as "the test now proves the opposite", which it does not prove:
`not x >= 80` also passes NaN.

Ruling, 2026-10-03 ([#196](https://github.com/taipei49314/checkwash/issues/196#issuecomment-5965834751),
item 196.followup.python-compare-direction, filed as #224): "The Python
frontend fills the same lt/le/gt/ge key, reversing the operator when the
literal is on the left, so `<` -> `>` reports 'contradicts' in Python too.
Costs: Python sweep, new fixtures, and a THREATMODEL row edit (maintainer)."
Related rulings: 196.189.3 (the flip is ASSERT_WEAKENED "contradicts" with
strength_drop 999) and 198.Q4 (a direction swap is "contradicts"; "proves
the opposite" stays reserved for a flipped negation on the same key).

**As implemented:**
- `frontends/python/frontend.py`: a single `<`, `<=`, `>` or `>=` records
  the bound key of `ir/predicate.py` (lt, le, gt, ge), read from the
  subject's side, so `80 > total()` is `total() < 80`, with the bound as
  `operand_source`, one line of its source. `assert not x >= 80` keeps the
  key, negated. unittest's `assertLess`, `assertLessEqual`, `assertGreater`
  and `assertGreaterEqual` record it, reversed when the subject is the
  second argument. A hand-rolled `abs(d) <op> bound` records it in every
  spelling it is read in (#196 189.2): with `abs` on the smaller side it is
  the upper bound it was, an `abs=` tolerance; with `abs` on the larger
  side it is a lower bound, read for its direction as JavaScript reads one:
  its centre is the expected value, and it records no tolerance.
- The key reaches every assertion the frontend records: a test's own, a
  same-file helper's it inherits, and a fixture's the engine lends.
- `ir/predicate.py` is unchanged; it now compares Python's keys too. A
  reversed direction is ASSERT_WEAKENED "bound direction reversed" (the new
  assertion contradicts the old one); `<` -> `<=` and `< 80` -> `not >= 80`
  are a predicate widened, graded by the lattice drop; `x < 80` respelled
  `80 > x` or `assertLess(x, 80)` is the same predicate.
- No strength value, gating row or alignment parameter changes.

**Readings:**
1. **The subject's side.** A literal on the left is the expectation, as
   `assertEqual`'s flip has it, so `80 > total()` states `total() < 80`.
   With two expressions the left one is the subject.
2. **What keeps no key.** A chained range keeps its bound-tuple reading; a
   comparison inside `assertTrue(...)` records none, as `assert.ok(x < 80)`
   records none in JavaScript (#288 asks whether both should); equality,
   identity and membership stay on the lattice.
3. **A lower bound's value is not compared**, in either language:
   `abs(d) > 0.5` -> `> 0.01`, a loosening, passes. Before this round
   Python blocked every change of that value, a tightening too, as an
   expected value rewritten, because the bound was the comparison's
   expected value. Reading the lower bound as JavaScript does is what lets
   both halves of the flip share a subject; #289 asks how to compare the
   value in both languages.
4. **A plain bound's value is still an expected value.** `x < 80` -> `x <
   1e12` keeps EXPECTED_VALUE_CHANGED (C2); the key decides only the
   direction.

**Measured cost**, with the round's engine against the base branch's
(`fix/222-tolerance-calls` at `9a8e262`, the same engine bytes as the
sweeps' copy):
- **Targeted set:** every non-merge commit, on any ref, of the twelve
  histories whose test-side Python adds or removes a line with an ordering
  comparison in an `assert`, or a unittest ordering method: 821 commits,
  605 readable on both engines. Two records change, and one verdict moves
  (149 -> 150 blocked):
  - scrapy `47970e91bc5a` ("Invert request priority meaning, a higher
    request.priority value means more priority") newly blocks: the commit
    inverts the scheduler's priority order in production code and flips
    two tests' `req2.priority < req.priority` to `>` and back, each now
    "bound direction reversed" at high. The reversal is real; that it is
    intended shows only in the production diff, which a reversal does not
    weigh, as in JavaScript.
  - pytest `22a50a5b88c3` stays pass with two more warn findings: `assert
    len(l[0]) > 2` -> `>= 2`, a predicate widened, in a commit that also
    changes production code.
- **Standard set** (the last 300 non-merge commits of attrs, click, flask,
  httpx, rich and starlette: 1,800 commits, all readable): the same
  records as the base, byte for byte (48 blocked).
- **D-088's sets** (895 commits of ten full histories, 855 readable; 368
  of pytest's, 364 readable): the same records as the base, byte for
  byte.

**Fingerprints, messages and IR:**
- New findings only: no existing finding changes rule, message or
  fingerprint in the fixtures or in the sweeps, apart from the
  hand-rolled flip, which changes rule (EXPECTED_VALUE_CHANGED ->
  ASSERT_WEAKENED) and so fingerprint, and `< 80` -> `not >= 80`, whose
  message changes from the opposite proven to a predicate widened.
- IR: a Python ordering comparison records `predicate` and
  `operand_source`, which were null; no field is added, and IR_VERSION
  stays 2. In the corpus, 43 existing fixtures' records gain the two
  values and every finding is byte for byte the same.

The agent wrote this entry; the maintainer approves it in the round's PR.

## D-104 (2026-10-06): one definition of an expected value that is not a plain literal (#226)

A literal expected value replaced by a call or a name passed in JavaScript
and in part of Python. `toBe(78.75)` -> `toBe(Number(75))` (#198 T6),
`toBe(make(1))` and `toBe(OTHER)` (an import) passed in JavaScript;
`== float('75')`, `== int('75')`, `== round(75.0, 2)` and a call to a name the
file never binds passed in Python, while the honest `78.75` ->
`Decimal('78.75')` blocked as a changed provenance.

Ruling, 2026-10-03 ([#196](https://github.com/taipei49314/checkwash/issues/196#issuecomment-5965834751),
item 196.followup.expected-provenance, filed as #226): "fold a fixed set of
literal-only conversions (Number('75'), float('75'), Decimal('75')) to their
value, so they compare as literals. Report any other literal -> unevaluated
call as EXPECTED_VALUE_CHANGED 'expected value replaced by an expression
checkwash does not evaluate'. Port Python's literal -> imported-name
provenance (EXPECTATION_DEFINITION_CHANGED) to JS. This decides i198/T6."
Rulings of 2026-10-04 ([#226](https://github.com/taipei49314/checkwash/issues/226#issuecomment-5981759826)):
226.Q1, a literal replaced by a call whose callee Python resolves keeps
EXPECTATION_DEFINITION_CHANGED, and the new message covers callees that
neither resolve nor fold; 226.Q2, `Decimal(<literal>)` folds, and a folded
value compares as Python's `==` does; 226.Q3, the JavaScript port covers a
call rewritten with the same callee and a same-file constant, and Python's
P5 (the same callee, bound nowhere) reports under 226.Q1.

**As implemented:**
- **Folds.** `float(<literal>)` and `Decimal(<literal>)` in Python and
  `Number(<literal>)` in JavaScript are the assertion's literal: `right_value`
  records the value they fold to. A spelling folds only where its name can be
  nothing else: `float` while the module binds that name nowhere, `Decimal`
  when a top-level import of the decimal module is the one binding of the
  name it is spelled with, `Number` while no scope declares it and no write
  reaches it. The argument is one bounded literal; `Number` folds a number or
  a string holding a plain decimal numeral; a signalling NaN does not fold.
  The provenance pass folds the same calls in an expected value it reads,
  what a local holds included.
- **Comparison.** Python literals compare as Python's `==` compares them,
  in EXPECTED_VALUE_CHANGED and in the provenance channel's answers:
  `78.75` -> `Decimal('78.75')` is no change, `0.1` -> `Decimal('0.1')` is
  one. JavaScript keeps one canonical Number.
- **Unevaluated calls.** Each frontend records, in the new optional
  `Assertion.unevaluated_expected`, an expected value or bound that is a call
  whose callee's root the file never binds (Python: no binding of the name
  anywhere in the module, in any scope, and no star import; JavaScript: no
  declaration in an enclosing scope and no write, nor an assertion library's
  name) and that does not fold. EXPECTED_VALUE_CHANGED reports a literal
  replaced by one, and one rewritten into another, on the same subject: "expected
  value replaced by an expression checkwash does not evaluate (78.75 ->
  int('75'))". An expression over the subject's own input stays
  EXPECTED_VALUE_DERIVED's.
- **The JavaScript port.** `frontends/javascript/expected_provenance.py`
  resolves an equality's expected value and its subject by substitution: an
  import becomes its module and export, a `const`, `let` or `var` the read
  reaches its initializer, resolved in turn (eight levels), and a declared
  function or class stays a call. A pair on one subject, a call after
  substitution, whose values differ while either side read such a name, is
  recorded as Python's channel records its events, and
  EXPECTATION_DEFINITION_CHANGED reports it with Python's message.
- The verdict gate labels `i198/T6` block.
- IR: the new optional field; a folded conversion's `right_value`.
  IR_VERSION stays 2 (D-067). No strength value, gating row or alignment
  parameter changes.

**Readings the rulings leave open:**
1. **Every Python literal compares by `==`.** 226.Q2 names folded values;
   one comparison for every literal keeps a folded and a written value on
   one reading, so `1` -> `1.0` and `1` -> `True`, which reported as an
   expected value rewritten, are now no change.
2. **J3 follows 226.Q1.** The issue's acceptance list, written before the
   rulings, puts `toBe(78.75)` -> `toBe(make(1))` (`make` imported) with the
   unevaluated calls. 226.Q1 keeps a callee the file resolves on
   EXPECTATION_DEFINITION_CHANGED and 226.Q3 ports that to JavaScript, so
   J3 reads "expected provenance changed 78.75 -> ./total.make(1)".
3. **A JavaScript global call rewritten** (`toBe(build(1))` ->
   `toBe(build(2))`, `build` declared nowhere) is P5's JavaScript twin and
   reports. The #198 round pinned it to pass "as in Python", which Python
   no longer does.
4. **What "never binds" means.** Any binding anywhere counts, so a
   parameter named `float` in an unrelated helper keeps `float('75')` from
   folding and from reading as unbound; a star import may bind any name.
5. **The port's reach.** It reads equality operands, not bounds or
   tolerances, and both directions of a pair it resolves: `toBe(OTHER)` ->
   `toBe(75)` reports through it, where Python's #60 owns that pair (#292
   asks whether JavaScript should read #60).
6. **Messages show the folded value** as Python prints it: `75.0` for
   `float('75')` and `Number(75)` (JavaScript's `75` has printed as `75.0`
   since #198), `Decimal('75')` for a Decimal. The ruling's "78.75 -> 75" is
   that value.
7. **A folded value restores a bound.** `x < 80` -> `x == float('78.75')`
   passes, as `x == 78.75` passes (numeric restoration).

Found during this round and filed: #292 (a name or call replaced by a
literal is read in Python only, and #60 reports an inlined local that still
holds the value) and #293 (a JavaScript definition rewritten under an
unchanged assertion is not read).

**Measured cost**, with the round's engine against the base branch's
(`fix/224-python-compare-direction` at `7c01de5`, the same engine bytes as
the sweeps' copy):
- **Targeted set:** every non-merge commit, on any ref, of the twelve
  histories whose test-side Python adds or removes an `assert` or a
  unittest assertion whose expected side is a call, or a line that spells
  `float(` or `Decimal(` in one: 2,605 commits, 2,147 readable on both
  engines. Twelve records change, by 14 new EXPECTED_VALUE_CHANGED
  findings, and no verdict moves (437 blocked on both):
  - in eleven, an expected value that was already a call is rewritten
    with the same callee, a builtin the file never binds (226.Q1's P5):
    aiohttp `b025d570938b` and its revert `c8d6e019d38e`
    (`bytes(stream._input)` <-> `bytes(stream._buffer)`); pytest
    `0394ebffee0b` (`len(... SafeRepr().maxlist ...)` -> `SafeRepr(0)`),
    `2ca6d9f039ef` (two `dict(x=1, ...)` gaining `unnamed=1`) and
    `af39c9850e33` (two `str(testdir.tmpdir...)` gaining
    `.realpath()`); scrapy `d5b6c236a90a`, its revert `99d8b05a0b19` and
    `1a4a77d49fa5` (`list(range(3, 13))` <-> `list(range(2, 13))`),
    `08232a3f824a` and `d42a98d3b590` (a `set` of str names becoming one
    of bytes); werkzeug `64fb22fde232` (a `set('...'.split('&'))` with
    other keys);
  - in one, a literal is replaced by such a call: click `b64ea07128a6`,
    `"not-none\n"` -> `repr("not-none")` (P2).
  Each is a change to the value the test expects, which v0.6.0 left
  unread. Eleven findings are warn. The three high ones, with no
  production change that explains them (E1), are in pytest
  `af39c9850e33` and scrapy `1a4a77d49fa5`, which already blocked on the
  same rule.
- **Standard set** (the last 300 non-merge commits of attrs, click,
  flask, httpx, rich and starlette: 1,800 commits, all readable): the
  same records as the base, byte for byte (48 blocked).
- **D-088's sets** (895 commits of ten full histories, 855 readable; 368
  of pytest's, 364 readable): the same records as the base, byte for
  byte.

**Fingerprints, messages and IR:**
- New findings, and one rule moved: a literal replaced by
  `Decimal(<literal>)` reported EXPECTATION_DEFINITION_CHANGED through the
  provenance channel, and now reports EXPECTED_VALUE_CHANGED (P11), or
  nothing when the values are equal (P12), so its rule and fingerprint
  change. `1` -> `1.0` and `1` -> `True` no longer report (reading 1).
  No other existing finding changes rule, message or fingerprint, in the
  fixtures or in the sweeps.
- Messages: the new "expected value replaced by an expression checkwash
  does not evaluate (<old> -> <new>)", and a folded value printed as
  Python prints it (reading 6).
- IR: the new optional `Assertion.unevaluated_expected`, null unless
  recorded, and a folded conversion's `right_value`; IR_VERSION stays 2.
  In the corpus every assertion record gains the null field, six existing
  fixtures record a value in it, and `js_evidence_name_rewrite_pos`
  records its JavaScript provenance events; every existing finding and
  verdict is byte for byte the same.

The JavaScript false-positive cost is measured by the JS/TS replay (#212)
before a release ships these findings.

The agent wrote this entry; the maintainer approves it in the round's PR.

## D-105 (2026-10-06): JS alias specifiers name first-party modules (#196 188.6)

A module mock or an import spelled through an alias was invisible to
TEST_PATCHES_SUBJECT. `vi.mock("@/billing", () => ({ invoiceTotal: () =>
78.75 }))` above an untouched `expect(invoiceTotal(items)).toBe(78.75)`
that reads `import { invoiceTotal } from "@/billing"` passed with zero
findings, and so did `vi.mock("@/billing")` standing in for
`../src/billing`, which the project's `tsconfig.json` maps `@/*` to.
`module_key` named a module only for a `./` or `../` specifier (THREATMODEL
row 109 residual "aliases").

Ruling, 2026-10-03 ([#196](https://github.com/taipei49314/checkwash/issues/196#issuecomment-5965834751),
item 196.188.6): "Yes, in a later round. B first (the same alias string in a
mock and an import is one module; `@/` and `~/` are first-party), then C as
its bounded extension (the base-side root tsconfig only). Route both through
the one module_key. This ruling authorizes flipping the pin at
tests/test_js_module_mocks.py:58 (`@/billing` -> None today) and rewriting
module_key's docstring."

**As implemented** (`frontends/javascript/aliases.py`, `module_key`):
- **B.** An `@/` or `~/` specifier is first-party, and its key is the alias
  string itself, normalized as a relative specifier is: `@/billing`,
  `@/billing.ts` and `@/billing/index.js` are one module, from any test
  file. One that leaves its root (`@/../x`), lands in dependency or build
  output, or carries a query is not. A scoped package (`@acme/billing`) is
  a package.
- **C.** The base side's root `tsconfig.json`, read once per analysis and
  only when a mock or an import spells a specifier that is not relative:
  its before side when the diff changes it, else the head snapshot, which
  holds it unchanged. JSON with comments and trailing commas, at most 256
  KiB and 256 patterns. `compilerOptions.paths` maps a specifier to a
  repository path, joined to `baseUrl` or, without one, to the root:
  an exact pattern first, then the longest prefix, the first target of the
  pattern, as TypeScript resolves it. The mapped path is the key a relative
  specifier of that file has, so under `"@/*": ["src/*"]`
  `vi.mock("@/billing")` and `import ... from "../src/billing"` are one
  module. A mapping wins over B, and one that leaves the repository or
  lands in dependency output names nothing first-party.
- The pin flips as authorized (`@/billing` -> `"@/billing"`), and the test
  is renamed for what it now states; `module_key`'s docstring and the
  module's are rewritten. No IR, strength, gating or alignment change.
  Fingerprints of existing findings are unchanged; a new finding names the
  alias key (`@/billing:invoiceTotal`) or the mapped path
  (`src/billing:invoiceTotal`).

**Readings the ruling leaves open:**
1. **`baseUrl` alone is not read.** With `baseUrl` set, TypeScript resolves
   `import x from "billing"` to `<baseUrl>/billing` when that file exists,
   and to the package otherwise. Telling the two apart needs the file
   inventory, which the strict snapshot refuses in a repository with a
   submodule, so such a specifier stays third-party; `baseUrl` is read as
   the root of `paths` targets.
2. **A `"*"` pattern is not read** (an empty prefix, `"*"` or `"*.svg"`),
   for the same reason: it maps every package name too.
3. **The first target only.** TypeScript tries a pattern's targets in
   order and takes the first that exists; the first is read as the module.
4. **Bounds.** No `extends`, no nested or `jsconfig.json` file, and no
   bundler or runner alias configuration (Vite `resolve.alias`, Jest
   `moduleNameMapper`). A tsconfig the diff adds has no base side and maps
   nothing; one it deletes maps through its before side.
5. **Condition 2 stays silent rather than guessed.** Without a tsconfig
   that decides it, an alias may name another spelling of the same module
   (`@/billing` and `../src/billing`, or `~/billing`). A base-side
   installation under a spelling whose path ends with the alias's own
   counts as already installed, so respelling a mock into an alias is not a
   new stand-in. A consumed read still needs one key: a new alias mock never
   reaches an import spelled another way unless the tsconfig joins them.

Found during this round: nothing new to file.

**Cost.**
- **New findings** (TEST_PATCHES_SUBJECT, high without repair evidence): a
  new mock or replacing spy through an `@/` or `~/` alias, or through a
  pattern of the base side's root tsconfig, that an existing unit's oracle
  reads.
- **The Python sweep cannot move.** No commit of the thirteen sweep
  histories (all refs) adds or removes a JS/TS line that spells a module
  mock, a spy, a `mock*` replacement or an `@/`/`~/` import, and none has a
  root `tsconfig.json`; the code this round changes runs only for such a
  file.
- **Not measured:** the JS false-positive cost, which waits on #212.

The agent wrote this entry; the maintainer approves it in the round's PR.

## D-106 (2026-10-06): an iterator callback keeps its assertions whatever the call's receiver (#294)

`docs/assertion-coverage.md` states the rule for a JS/TS test's inline
callbacks: "Direct inline callback arguments to other calls retain the
existing lexical coverage, including iterator callbacks; this does not
prove that an arbitrary callee executes its callback." The frontend
applied it only where `CALL` matched, a callee spelled as a dotted name.
`cases.forEach(cb)` was read; `[[1, 78.75]].forEach(cb)`,
`Object.entries(cases).forEach(cb)`, `(cases).forEach(cb)` and
`cases?.forEach(cb)` were not, so their callbacks were nested functions and
their assertions no unit's. Weakening or deleting the assertion in the
table-driven spelling passed with zero findings and a coverage notice.
Found during #235 and filed as #294, which proposed no new ruling: it
applies the stated rule to spellings it missed.

**As implemented:** besides `CALL`'s matches, every member call opens a
call whose direct callback arguments are inline bodies: a `(` that follows
a name that follows `.` or `?.`, whatever comes before the `.`. The tokens
already tell a string or a comment apart, so `` `a,b`.split(",") `` is one.
No callee name is added or removed, and nothing else reads these calls.

**Readings flagged for approval:**
1. **A member call, not any call.** A call result called directly
   (`each(cases)(cb)`) and an optional call (`fn?.(cb)`) are not member
   calls, and their callbacks stay nested functions, as before.
2. **A named callback stays a helper.** A callback passed by name or
   declared elsewhere is a declared helper, as before: its assertions remain
   a coverage gap.

**Cost.**
- **New findings:** ASSERT_WEAKENED, ASSERT_REMOVED and the other
  assertion rules, where an assertion in such a callback changes.
- **The corpus is byte for byte the same**: no fixture before this round
  spells the shape.
- **The Python sweep cannot move.** No commit of the thirteen sweep
  histories touches a JS/TS test file, and only such a file is parsed this
  way.
- **Not measured:** the JS false-positive cost, which waits on #212.

The agent wrote this entry; the maintainer approves it in the round's PR.

## D-107 (2026-10-06): a string skipif or xfail condition is the expression pytest evaluates (#263)

pytest compiles a `skipif` or `xfail` mark's string condition as an
expression and evaluates it with `os`, `sys`, `platform` and `config` in
scope beside the test module's globals. D6 read the string as a constant.
A non-empty string is truthy in every environment, so
`skipif("sys.platform == 'win32'")` read as a condition that always holds
and blocked at high, as an unconditional skip would, while
`skipif(sys.platform == 'win32')` held at warn. #260 found it: reading a
mark applied through a bound name newly blocked three commits of pytest's
own history this way.

Rulings, 2026-10-06 (#263, adopted as recommended, "全部核准"):
- **263.Q1:** a string condition is parsed as the expression it holds and
  judged as an expression condition is. A string that does not parse earns
  nothing, as today, and one that always holds (`"True"`,
  `"sys.version_info >= (3,)"`) still blocks. The marker's name keeps the
  string as written, so fingerprints do not move.
- **263.Q2:** `os`, `sys` and `platform` are read as those modules even
  when the test module does not import them. `config` stays unknown, so a
  condition on an option is judged as an unknown is.

**As implemented:**
- `ir/markers.py`, `mark_condition`: a `skipif` or `xfail` mark's first
  argument; for a string, the expression parsed from it as pytest compiles
  it (`ast.parse(..., mode="eval")`, the parser `compile` uses). A string
  that does not compile is None.
- `compat.py`: a string condition is evaluated in pytest's namespace
  (`_eval_condition(..., pytest_names=True)`). The condition D6 evaluates
  is the conjunction of its parts (a `pytestmark` binding's guard and the
  mark's own condition, #260 Q2), each part in its own namespace.
- `evidence.py`, `_gate_condition_names`: the names inside a mark's
  string condition are resolved as module constants, as pytest's module
  globals hold them.

Readings the rulings leave to the implementation:

1. **What compiles.** Exactly what `compile(text, ..., "eval")` accepts:
   leading whitespace, a statement, an empty string and two lines that no
   bracket joins do not compile, and earn nothing. pytest reports an error
   for such a mark, so the test does not run where it applies. With a
   `pytestmark` binding's guard, the mark still earns nothing.
2. **pytest's names.** In a string, a bare `os`, `sys` or `platform` is
   that module unless the test module binds the name to a constant that
   the engine resolves, which wins as the module's globals do. A module is
   true and equals nothing but itself, so `"platform != 'linux' or
   sys.platform == 'win32'"` holds everywhere and blocks, as it skips
   everywhere under pytest. Dotted reads (`sys.platform`, `os.name`,
   `platform.system()`) were already read whatever the module imports.
3. **Module code stays module code.** A constant's own expression, and a
   `pytestmark` binding's guard, are read as before: a bare `platform`
   there is the `from sys import platform` an expression condition
   assumes, and a bare `sys` is unknown.
4. **Reasons are not conditions.** The argument of an imperative
   `pytest.xfail(...)` is its reason. It is not parsed, so a reason that
   happens to be a name pulls no constant into the file's IR.

**Not in this round (residual):**
- A test module that binds `platform` by `from sys import platform` has
  that string where pytest evaluates a string condition, but the reading
  above takes the module: `"platform != 'win32'"` there blocks though it
  can be false. The sweeps hold no such condition.
- Only a mark's first condition is read, and only it names the mark:
  `skipif(sys.platform == "win32", True)` holds at warn while pytest skips
  everywhere, and a `condition=` keyword is not read. Filed as #297.

**Tests and fixtures.**
- **Tests:** 34 in `tests/test_issue263_string_conditions.py`. All 16
  mutants of the round's code fail them or the fixtures.
- **Fixtures:**
  - `compat_gate_string_condition_neg` (#263 S1), in a module that does
    not import `sys`: v0.6.0 blocks it with TEST_DISABLED high; it is now
    held at warn by COMPAT_GATE.
  - `compat_gate_string_always_true_pos` (row 44): v0.6.0 blocks it, and
    so does this round.

Every existing fixture keeps its expectation, and its corpus record does
not change.

**Fingerprints.** None move: a marker's name holds the string as written.

**Cost.**
- **Targeted set:** every non-merge commit of the thirteen histories
  (the six of the standard set, aiohttp, pytest, requests, scrapy,
  uvicorn, werkzeug and PyWavelets) whose Python diff adds or removes a
  line where `skipif(` or `xfail(` opens a string: 232 commits, 200
  readable on both engines. 27 records change, all in pytest, and 20
  verdicts move from block to pass (74 blocked -> 54):
  - 110 TEST_DISABLED findings fall from high to warn, held by
    COMPAT_GATE. Each is a mark whose string is a version or platform
    gate pytest evaluates, false somewhere: `"sys.version_info < (2,6)"`,
    `"sys.platform == 'win32'"`, `"sys.platform.startswith('java')"`,
    `"sys.platform == 'win32' or getattr(os, '_name', None) == 'nt'"`
    and its negation;
  - 5 fall from high to info: tests that move or are renamed under such
    a mark (`45065e4e2eb2`, `TestLastFailed` moving into
    `test_cache.py`; `1ff173baee58`, two tests moving into a class whose
    `pytestmark` is a name bound to one; `fe54762b93a3`). The new units
    run somewhere, so the old units' disappearance is a relocation.
  No finding appears or disappears, and none rises.
- **Standard set** (the last 300 non-merge commits of attrs, click,
  flask, httpx, rich and starlette: 1,800 commits, all readable): the
  same records as the base, byte for byte (48 blocked).
- **D-088's sets:** the 895 commits of ten full histories (855
  readable) give the base's records byte for byte (237 blocked). In the
  368 of pytest's (364 readable), 15 records change, every one also in
  the targeted set above, and 11 verdicts move from block to pass (107
  blocked -> 96).

**Verdict gate.** Run as CI runs it (four engines, 156 T1 + 26 T3 cases):
passed, 0 failures, 1 reported (`i198/T6`, undecided, pass on both
engines). Every case keeps v0.6.0's verdict.

The agent wrote this entry in the fix PR, as the rulings' X.doc-batch asks;
the maintainer approves it there.

## D-108 (2026-10-06): a D10 survivor is read with the conftest files above it (#266)

D10 credits a disappeared unit when an identical live copy of its body runs
at head in a collectable test file the diff does not touch (THREATMODEL row
58: "a skipped or edited survivor earns nothing"). The copy's liveness was
read from its own file only. A copy that an always-skip conftest fixture
skips counted as live, so deleting the running copy passed at info, while
the same copy with a skip marker blocked. #223 had added the conftest chain
for the modules a diff changes, as ruling 223.Q2 scoped it, and a survivor
lies in a file the diff does not change.

Rulings, 2026-10-06 (#266, adopted as recommended, "全部核准"):
- **266.Q1:** a candidate survivor's conftest chain is read at head, as
  #223 reads a changed module's head side, and the survivor is parsed with
  it. A survivor that an always-skip conftest fixture reaches is not live
  and earns nothing. The chain's reads keep #223's bounds.
- **266.Q2:** D10's survivors only. Other readers of files the diff does
  not change (the stand-in context, runtime subject shadows) do not judge
  liveness through markers, and are not in this item.

**As implemented:** `engine.py`'s survivor search parses each candidate
with `chain=_conftest_chain(path, 1)`. That is the chain #223 builds for a
changed module's head side: each `conftest.py` from the survivor's
directory up to the repository root, nearest first, a file the diff changes
read on its head side and any other from the strict snapshot, under #223's
read bounds. A fixture the survivor reaches (requested by `usefixtures`, or
`autouse`; a parameter is part of the signature, which the body hash holds)
that always skips gives its unit a setup marker, and D2's liveness rule
(every marker a D6 compat gate) then reads the survivor as not live.

Readings the rulings leave to the implementation:

1. **Without a strict snapshot**, as #223 reads it, no conftest level is
   known: the chain is empty and the survivor reads as before. The CLI and
   the Action always pass one.
2. **A level that cannot be read or parsed ends the chain**, as for a
   changed module (#223): what it defines is unknown, and it could
   override any name beyond it.
3. **A skip the fixture runs only under a compatibility condition**
   (`if sys.platform == "win32": pytest.skip(...)`) leaves the survivor
   live, as a `skipif` marker on it would (D6).

**Tests and fixtures.**
- **Tests:** 8 in `tests/test_issue266_survivor_conftest_chain.py`. Both
  mutants of the round's code (the chain left out; the base side read for
  it) fail them or the fixtures.
- **Fixtures:**
  - `duplicate_remains_conftest_skipped_copy_pos` (#266 U1, row 58): the
    surviving copy requests an always-skip conftest fixture. v0.6.0 passes
    the deletion of the running copy at info; it now blocks with
    TEST_DISABLED high.
  - `duplicate_remains_conftest_live_copy_neg` (#266 U2): the same
    conftest, and a copy that requests nothing from it, still earns
    DUPLICATE_REMAINS at info.

Every existing fixture keeps its expectation, and its corpus record does
not change.

**Fingerprints.** None move.

**Cost.**
- **Targeted set:** every commit of #224's sweeps (its targeted set, the
  standard set and D-088's sets, twelve histories) where a test unit's
  disappearance was held at info, the only findings this round can
  change: 98 commits, all readable. The same records as the base, byte
  for byte (32 blocked). No credited survivor there is one that a conftest
  fixture skips.
- **Standard set** (the last 300 non-merge commits of attrs, click,
  flask, httpx, rich and starlette: 1,800 commits, all readable): the
  same records as the base, byte for byte (48 blocked).
- **D-088's sets** (895 commits of ten full histories, 855 readable; 368
  of pytest's, 364 readable): the same records as the base, byte for byte
  (237 and 107 blocked).

**Verdict gate.** Run as CI runs it (four engines, 156 T1 + 26 T3 cases):
passed, 0 failures, 1 reported (`i198/T6`, undecided, pass on both
engines). Every case keeps v0.6.0's verdict.

The agent wrote this entry in the fix PR, as the rulings' X.doc-batch asks;
the maintainer approves it there.

## D-109 (2026-10-06): a negated approximate comparison is read as negated (#284)

The approx branch of the Python frontend's assertion classifier ran first
and found an `approx(...)` call anywhere in the test expression, so the
comparison it sat in was never read: `== pytest.approx(78.75)` ->
`!= pytest.approx(78.75)` passed with zero findings, as did a `not` around
it, while the same flips without `approx` blocked as a polarity inversion
(THREATMODEL row 33). A negated approximate comparison passes when the
values are far apart, so its tolerance orders the other way: a bigger `abs`
or `delta`, or fewer `places`, is stricter. The frontend recorded it as a
positive one's, so `TOLERANCE_LOOSENED` blocked a tightening
(`!= approx(x, abs=0.01)` -> `abs=0.5`,
`assertNotAlmostEqual(..., delta=0.1)` -> `delta=0.5`, `places=3` ->
`places=2`) and passed a loosening. The JavaScript frontend already records
no tolerance for a negated matcher, and #222 did the same for a negated
Python tolerance call.

The issue proposed the fix as one round, with one choice: read a negated
tolerance in the reversed direction, or record none. It recommended none,
for one rule in both frontends, and the round takes that.

**As implemented:**
- `frontends/python/frontend.py`, `_classify_assert_expr`: the approx
  branch reads the comparison it sits in. A single `!=` (or `is not`,
  `not in`, as the plain comparison path reads them) is negative; a `not`
  around the comparison is left to the negation branch, which negates its
  operand and drops an approximate comparison's tolerance (#222). A
  negated approximate comparison records no tolerance. Its expected value
  is still recorded, as a plain `!=` records its own.
- `assertNotAlmostEqual` records no `places` or `delta`, its implicit
  `places=7` included.

Readings the issue leaves to the implementation:

1. **One rule for every negation.** `!=`, `not`, a negated unittest call
   and a negated tolerance call record no tolerance, whatever they wrap,
   so a change of it is unknown: neither the tightening that blocked nor
   the loosening that passed is reported. An approximate comparison whose
   polarity flips is reported as the inversion (ASSERT_WEAKENED), whatever
   its tolerance does.
2. **A double negation** (`not x != approx(y)`) is positive, and records no
   tolerance either: the negation branch drops the tolerance of the
   negated comparison it wraps. A known tolerance replaced by it is the
   unverifiable replacement the unknown-tolerance rule reports. The sweeps
   hold no such spelling.
3. **Only the comparison the call sits in is read.** An approx call inside
   a boolean operator or another structure still makes the whole
   assertion an approximate comparison (`== approx(x) or True` passes);
   that is #299, filed during this round.

**Tests and fixtures.**
- **Tests:** 31 in `tests/test_issue284_negated_approx.py`. Seven
  mutants of the round's code each fail them or the fixtures: every
  approximate comparison read as positive; a `not` around one handed
  back to the approx branch; a negated `approx` keeping its tolerance;
  `assertNotAlmostEqual` keeping its `places` or `delta`; the polarity
  left out of the record; `!=` read as positive; `not in` read as
  positive.
- **Fixtures:**
  - row 33's pins for the approx spelling, each passing on v0.6.0 with
    zero findings: `approx_polarity_inverted_pos`,
    `approx_left_polarity_inverted_pos` and
    `approx_not_polarity_inverted_pos`;
  - the false positives, each blocked by v0.6.0 with TOLERANCE_LOOSENED
    high and now quiet: `approx_negated_stricter_tolerance_neg`,
    `almost_negated_stricter_delta_neg` and
    `almost_negated_fewer_places_neg`.

Every existing fixture keeps its expectation, and its corpus record does
not change: `tools/emit_corpus.py` gives the base's 775 records, byte for
byte, and the six new ones.

**Fingerprints.** None move: a flipped approx comparison reports a new
finding, and a negated tolerance reports none where it reported
TOLERANCE_LOOSENED.

**Cost.** Measured with the round's engine against the base branch's
(`2ece6f2`, #226's branch with #291 merged in):
- **Targeted set:** every non-merge commit in the checked-out history of
  the twelve histories and PyWavelets whose Python adds or removes a line
  matching `assertNotAlmostEqual` or `approx(`: 106 commits, 99 readable.
  No record changes; 6 commits block on both engines.
- **Standard set** (the last 300 non-merge commits of attrs, click,
  flask, httpx, rich and starlette: 1,800 commits, all readable): the
  same records (48 blocked).
- **D-088's sets** (895 commits of ten full histories, 855 readable; 368
  of pytest's, 364 readable): the same records.

**Verdict gate.** Run as CI runs it (four engines, 156 T1 + 26 T3 cases):
passed, 0 failures, 1 reported: `i198/T6` blocks (pass -> block), as
its label since #226 (D-104) says. Every other case keeps v0.6.0's
verdict.

The agent wrote this entry in the fix PR; the maintainer approves it there.

## D-110 (2026-10-06): an assertion is an approximate comparison only where it states one (#299)

The approx branch of the Python frontend's assertion classifier found an
`approx(...)` call anywhere in the test expression and read the whole
assertion as that approximate comparison, at APPROX strength with the
call's expected value and tolerance. A structure around the call that
makes the assertion hold everywhere was therefore the same assertion on
both sides, and passed with zero findings: `== pytest.approx(78.75)` ->
`== pytest.approx(78.75) or True` (also `True or ...`, `or total() > 0`
and `isinstance(...) or ...`), `all(...)` -> `any(...)` over the same
comparison, a comparison of the comparison's result
(`(total() == pytest.approx(78.75)) is not None`) and an unrelated call
(`print(pytest.approx(78.75)) is None`). The plain spellings block.
Found during #284's round, which fixed the negations at the same site.

The issue proposed one round: the approx branch applies only where the
call is an operand of the assertion's own comparison, or inside one, and
every other structure, a boolean combination of approximate comparisons
included, is read as the plain path reads it.

**As implemented:**
- `frontends/python/frontend.py`, `_asserted_approx_comparison`: the
  assertion states an approximate comparison when it is a single `==`,
  `!=`, `in` or `not in` (approx answers equality and membership only)
  with an `approx(...)` call as an operand, or inside one through list,
  tuple, set and dict displays and starred items (`[total()] ==
  pytest.approx([78.75])`, `{'t': total()} == {'t': pytest.approx(78.75)}`).
- It also states one when such a comparison is a link of a chained
  comparison (`0 < total() == pytest.approx(78.75)`), when it conjoins one
  with `and` (the first, at any depth), or when it asserts one with
  `all(...)` over a generator or list comprehension.
- Anything else is read by the plain path: `or`, `any(...)`, `is` and
  `is not`, an ordering, a comparison of a comparison's result, and a
  call that only receives an approx object. `repr(pytest.approx(1.0)) ==
  '1.0 ± 1.0e-06'`, as in pytest's own tests, is a string equality whose
  expected value is the string.
- The comparison read carries its own polarity (#284): the operator of
  its link, inside a chain, `and` and `all(...)` too.

Readings the issue leaves to the implementation:

1. **A conjunction, a chained comparison and `all(...)` keep the
   approximate reading.** The issue proposed reading a boolean
   combination as the plain path reads it, TRUTHY. Main read
   `total() == pytest.approx(78.75) and total() > 0` as the approximate
   comparison it holds, so `approx(78.75)` -> `approx(75)` there blocked
   as EXPECTED_VALUE_CHANGED; a TRUTHY reading would pass it with no
   finding. Each part of a conjunction and each link of a chain must
   hold, and `all(...)` asserts its element for every item, so each
   states the comparison; the round keeps reading it. Joining approximate
   comparisons with `and`, or splitting one, reads as it did on main.
2. **The other parts of a conjunction or chain are not read**, as on
   main: `... and total() > 0` -> `... and True`, or `0 < total() == ...`
   -> `-1e9 < total() == ...`, is not seen. A conjunction whose
   approximate comparison moves to another position is the same assertion
   (`approx_conjunction_reordered_neg`).
3. **A call that receives an approx object is the call.**
   `isinstance(pytest.approx(78.75), object)` and `print(...) is None`
   hold whatever the value, and checkwash cannot tell an operator from
   any other function, so an operator call is read as the call too:
   `operator.eq(total(), pytest.approx(78.75))`, or pytest's own
   `op(a, approx(x))` with the operator passed in, as
   `operator.eq(total(), 78.75)` is. The cost: its
   expected value rewritten (`approx(78.75)` -> `approx(75)`) is no
   longer reported; main blocked it as EXPECTED_VALUE_CHANGED, and the
   plain `operator.eq(total(), 78.75)` -> `75` passes on main and v0.6.0
   alike. A respelling from `==` into such a call is a strength drop
   (APPROX -> TRUTHY) and blocks. The sweeps hold no such edit.

**Tests and fixtures.**
- **Tests:** 37 in `tests/test_issue299_approx_structure.py`. Thirteen
  mutants of the round's code each fail them or the fixtures: a bare
  `approx(...)` not recognized; a list, tuple or set display not
  descended; a dict display's keys read for its values; a starred item
  not descended; membership not an approximate comparison; a chain's
  later link read against its first operands; only a chain's first link
  read; a disjunction stating its comparison; a conjunction stating
  none; `any(...)` stating its element; `all([...])` over a list
  comprehension stating none; `not in` read as positive; every stated
  comparison read as positive.
- **Fixtures:**
  - row 124's pins, each passing on v0.6.0 with zero findings:
    `approx_or_true_pos`, `approx_all_to_any_pos` and
    `approx_result_is_not_none_pos`;
  - reading 1, each read the same way on v0.6.0 and kept:
    `approx_conjunction_expected_rewrite_pos`,
    `approx_chained_expected_rewrite_pos` and
    `approx_conjunction_reordered_neg`.

Every existing fixture keeps its expectation, and its corpus record does
not change: `tools/emit_corpus.py` gives the base's 781 records, byte for
byte, and the six new ones.

**Fingerprints.** None move: a wrapped approximate comparison reports a
new finding where it reported none.

**Cost.** Measured with the round's engine against the base branch's
(`90c1da4`, #284's branch):
- **Targeted set:** every non-merge commit in the checked-out history of
  the twelve histories and PyWavelets whose Python adds or removes a line
  matching `assertNotAlmostEqual` or `approx(`, as for D-109: 106
  commits, 99 readable. No record changes; 6 commits block on both
  engines.
- **Standard set** (the last 300 non-merge commits of attrs, click,
  flask, httpx, rich and starlette: 1,800 commits, all readable): the
  same records (48 blocked).
- **D-088's sets** (895 commits of ten full histories, 855 readable; 368
  of pytest's, 364 readable): the same records.

**Verdict gate.** Run as CI runs it (four engines, 156 T1 + 26 T3 cases):
passed, 0 failures, 1 reported: `i198/T6` blocks (pass -> block), as
its label since #226 (D-104) says. Every other case keeps v0.6.0's
verdict.

The agent wrote this entry in the fix PR; the maintainer approves it there.

## D-111 (2026-10-06): a skip a test reaches through a same-file helper is read (#272, first stage)

A skip was read only where the test body or its setup spelled it. A test
that called `_later()`, where `_later` calls `pytest.skip()`, was skipped as
surely as one that called it itself, and passed with zero findings, while
the same line in the body blocked. So did a called nested def, the raised
spelling in a helper, and a helper a test's fixture calls; and a skip added
to a helper the test already called. Found during #254's round.

The owner adopted the issue's recommendations on 2026-10-06 ("全部核准"):
272.Q1 (a), read a skip the test or its setup reaches through a helper, for
the same-file scopes `_executed_scopes` already resolves for assertions,
judged as a skip in the body or in the setup is judged; an outcome every
run reaches is unconditional, and a guarded one keeps its guard, with the
call site's conditions and the helper's conjoined, as 183.2 records a setup
guard. 272.Q2 (a), follow an imported helper into the head tree as a second
stage. 272.Q3, the marker `helper.<function>.<effect>`, with the message
"skip/xfail added to a helper this test calls". This entry is the first
stage; the second follows in its own round.

**As implemented:**
- `frontends/python/helper_skips.py` (new), `HelperOutcomes`: a call by a
  plain name to a function the module defines, one nested in the calling
  scope, or a name bound to a lambda or to `partial` of one of those, runs
  that helper. Each helper is read once per module: `setup_outcome` gives
  its own outcome and guard, and the helpers it calls in turn, at most four
  calls from the test or setup callback, as `_executed_scopes` follows
  assertions, add theirs under the conditions their calls run under.
- A call's conditions (`call_conditions`) are what a body skip's are: each
  enclosing `if`, `not (...)` for an `else`, and an `except` block's own
  condition (`_handler_guard`); a loop, `with`, `match` or `try` body adds
  none. The marker's guard is their conjunction with the helper's own.
- `frontend.py`: the unit's calls that run (not dead) are read; a test
  module's fixtures and xunit setup callbacks read theirs (`SetupScope`),
  and a unit gets those of the setup providers it reaches
  (`setup_helper_outcomes`, resolved as `setup_outcomes` resolves them).
- The marker family `helper` (`conftest_controls.HELPER`): TEST_DISABLED
  reports "skip/xfail added to a helper this test calls
  (helper._later.skip)", and a guard removed or made always true "in a
  helper this test calls"; COMPAT_GATE judges its guard as a body skip's
  (`is_helper_skip`).
- `ir/diffalign.py`: an added helper marker is paired with a skip the base
  had and the head lost when it is that skip moved (`_moved_skip`, reading
  7); the move is recorded (`UnitDelta.markers_moved`), and
  `evidence._mark_weakened_guards` reads its guard against the old one's.

Readings the rulings leave to the implementation:

1. **A helper is read as a setup callback is, whoever calls it.** A skip
   in the test body counts with any arguments, and `importorskip` too; a
   helper is read by `setup_outcome`, the reading that records the path
   condition an outcome is reached under inside another function, an
   `except` block's included. So a helper's skip with an argument that
   calls something (`pytest.skip(reason())`), and `importorskip` in a
   helper, are not read.
2. **The scopes are the ones `_executed_scopes` resolves, and only
   functions.** A class is not followed: calling it runs `__init__`, not
   the methods `_executed_scopes` lends assertions from. Nor is a
   generator, whose body does not run when it is called, nor a helper
   passed as an argument. A method reached through `self` is no scope
   `_executed_scopes` resolves, for assertions either: the issue's H2 and
   S1 are filed as #306, with A1 and A2, a helper method's assertion
   weakened or deleted, which pass on v0.6.0 too.
3. **A name the calling scope binds itself is not the module function.**
   `def test_total(offline): offline()` calls a fixture's value, and
   `_later = make(); _later()` calls what `make` returned.
4. **Every call ends at an outcome every call reaches.** A helper that
   always skips is read no further: what it would call after does not
   run.
5. **The marker names the helper that holds the outcome**, with that
   outcome's text and span. A helper several tests reach marks each of
   them, as a test module's own setup providers do (row 104).
6. **A conftest fixture's helpers are not followed.** A conftest's
   fixtures are read by their own unconditional outcome (#223); a helper
   it calls is in another file than the test module.
7. **A skip moved into a helper, out of one, or into a renamed one is the
   skip it was.** The marker is named for the helper, so carrying a skip
   the test already had, from its body or its setup, into a helper it
   calls changed the name alone and read as a skip added; the round's
   sweep found it in scrapy df342eee6e2f. An added helper marker is the
   moved skip when the base had a skip the head lost with the same
   effect that fired at least as often: unconditionally, or under the
   same condition. Its guard is then read against the old one's, so a
   constant behind it made always true is still reported (THREATMODEL
   59). A skip whose guard did not move with it, one under another
   condition, and a skip that became an xfail are reported as added. A
   skip respelled in the body (`pytest.skip` -> `self.skipTest`) is not a
   move; that is #281's question, unchanged.

**Tests and fixtures.**
- **Tests:** 52 in `tests/test_issue272_helper_skips.py`, and
  `tests/test_conftest_controls.py` lists the two new minting sites and
  the family. Thirty-five mutants of the round's code each fail them or the
  fixtures: an `if`, an `else` or an `except` block at a call site adding
  no condition; a generator read as a helper, or a lambda not; a
  parameter, or a name the caller binds, not shadowing the module
  function; the call site's conditions, or the helper's own guard,
  dropped; the walk going on past an outcome every call reaches; one call
  deeper, or shallower, than assertions; a nested helper read with the
  module's names only; a lambda's parameters not shadowing; a fixture's,
  or xunit setup's, helpers not read; the unit's own calls, or the setup's
  helper markers, not read; COMPAT_GATE not reading a helper skip's guard;
  a guard removal not read for one; the family unknown; and, for reading
  7, no move credited, markers not paired by name first, a body skip
  respelled in the body taken for a move, only a helper-to-helper move
  credited, a skip and an xfail the same, every outcome a skip, a
  fixture's skip without an effect, `self.skipTest` an xfail, the guard
  not compared, a guarded skip never moving, an unconditional skip moving
  only to an unconditional one, one skip crediting two moves, the move
  recorded backwards, and a moved skip's guard not read against the old
  one's.
- **Fixtures:**
  - row 125's pins, each passing on v0.6.0 with zero findings:
    `helper_skip_module_function_pos`, `helper_skip_nested_def_pos`,
    `helper_skip_raised_pos`, `helper_skip_through_fixture_pos` and
    `helper_skip_added_to_called_helper_pos`;
  - `helper_skip_platform_gate_neg`: a call under a platform condition is
    a D6 gate, held at warn, as the same skip in the body is;
  - `helper_skip_already_called_neg`: a skip the base already reached is
    no event;
  - `helper_skip_moved_from_body_neg`: a body skip moved with its guard
    into a helper the test calls is no skip added (reading 7); C1 before
    the fix blocked it.

Every existing fixture keeps its expectation, and every finding in the
corpus (`tools/emit_corpus.py`: main's 759 records and the eight new ones)
is byte for byte main's.

**Fingerprints and IR.** No fingerprint moves: the markers are new names,
and a finding on one is a new finding. `--emit-ir` gains `markers_moved`
on every unit delta, an optional field whose default is empty
(docs/stability.md: IR_VERSION stays 2, as for D-067's keys); in the
corpus it adds `"markers_moved": []` to the 655 unit deltas of the 759
existing records and changes nothing else. The next release guide names
it.

**Cost.**
Measured with the round's engine against main's (`4f0955b`):
- **Targeted set:** every non-merge commit of the thirteen sweep
  histories whose test-side Python adds or removes a line spelling
  `skip(`, `skipTest(`, `SkipTest`, `xfail(` or `skip.Exception`: 1,144
  commits, 959 readable. Four records change and one verdict moves
  (blocked 272 -> 273):
  - aiohttp `2b7cb1629f4b` ("skip some tests for tokio loop"): fifteen
    tests start calling a new helper, `skip_if_no_dict(loop)`, which
    skips when the loop has no `__dict__`. That gives fifteen warn
    findings. They are the skip the commit means, and they stay at warn
    because the commit changes production code too, as the same line in
    each body would.
  - pytest `ced62f30ba0d` (pass -> block): two tests call the new
    `attempt_symlink_to`, which skips on Windows under Python 2 and when
    a symlink cannot be made (`except OSError`):
    - for `TestNumberedDir.test_cleanup_symlink` it is a new skip, high,
      as it would be in the body;
    - `test_tmpdir_always_is_realpath` trades a
      `skipif(not hasattr(py.path.local, "mksymlinkto"))` mark for it.
      That is a skip respelled from a mark to a call, #281's question,
      and it reads as added.
  - pytest `3cc58c2f78f0` (block -> block): `py.test.skip(...)` ->
    `pytest.skip(...)` inside the `lsof_check` helper reads as a skip
    added to it in three tests, because `py.test` is not read (#310,
    found by this sweep).
  - pytest `5e883f51959f` (pass -> pass): `test_tmpdir_always_is_realpath`
    moved to `test_legacypath.py`, and its disappearance now reports at
    warn where it was info. Its helper's `except OSError` skip is no
    compat gate, so D2 no longer credits the move of a unit that may not
    run (`unit_is_live`).

  Before reading 7, this sweep's first run also blocked scrapy
  `df342eee6e2f`, where fourteen tests' guarded body skips moved into
  helpers. Its record is now main's.
- **Standard set** (the last 300 non-merge commits of attrs, click,
  flask, httpx, rich and starlette: 1,800 commits): the same records as
  main, byte for byte (48 blocked).
- **D-088's sets** (895 commits of ten full histories, 855 readable; 368
  of pytest's, 364 readable): the ten histories give main's records byte
  for byte. In pytest's, two records change, both commits of the targeted
  set above: `ced62f30ba0d` (pass -> block) and `3cc58c2f78f0` (block ->
  block).

**Verdict gate.** Run as CI runs it (four engines, 156 T1 + 26 T3 cases):
passed, 0 failures, 1 reported: `i198/T6` is undecided (pass on both
engines), as on main, where #226's relabel (D-104) has not landed. Every
other case keeps v0.6.0's verdict.

The agent wrote this entry in the fix PR; the maintainer approves it there.

## D-112 (2026-10-06): numpy's and torch's assertion calls are lent as a bare `assert` is (#286)

#222 made numpy's and torch's assertion calls
(`numpy.testing.assert_allclose`, `assert_array_almost_equal`,
`assert_almost_equal`, `torch.testing.assert_close`) assertions, read in a
test unit and in a same-file helper it calls. A fixture the test requests
and a helper another file defines lent the test their bare `assert`s only
(A5-x), so the same call there was no assertion: widening its tolerance or
deleting it passed with zero findings, while `assert np.allclose(...)` in
the same place blocked. Found during #222's round.

The issue proposed one round with no alternative, and the round takes it:
`_classified_asserts`, which builds what a fixture and a module helper lend,
also records the calls the unit's own walk reads
(`_tolerance_statement_classified`).

**As implemented:**
- `frontends/python/frontend.py`, `_classified_asserts`: a numpy or torch
  assertion call is recorded as the unit's walk records it, with the same
  form, strength, expected value and tolerance, marked `inherited`. Every
  channel that lends a bare `assert` lends it: a fixture the test requests,
  in its module or the conftest beside it, an autouse fixture, and a helper
  another file defines and the test calls (A5-x's import channel).
- `docs/assertion-coverage.md` says so, where it listed the gap;
  `docs/defence-design.md`'s A5-x note says what the channels lend.

Readings the issue leaves to the implementation:

1. **The root-module projection channel is unchanged.** It projects a
   transparent equality helper (`assert actual == expected`, two
   parameters) onto its caller and nothing else; a tolerance call is no
   such helper, so a root module's numpy helper still lends nothing there.
2. **Only the assertion calls.** `np.allclose(...)` and
   `math.isclose(...)` return a bool, and are read only inside an
   `assert`, which was already lent.

**Tests and fixtures.**
- **Tests:** 13 in `tests/test_issue286_lent_tolerance_calls.py`. Two
  mutants of the round's code each fail them: a fixture's or helper's
  tolerance call not lent, and every lent call read as trivial.
- **Fixtures**, row 120's pins, each passing on v0.6.0 with zero findings:
  `tolerance_call_fixture_widened_pos` (TOLERANCE_LOOSENED),
  `tolerance_call_fixture_deleted_pos` and
  `tolerance_call_other_file_helper_dropped_pos` (ASSERT_REMOVED); control
  `tolerance_call_fixture_unchanged_neg`.

Every existing fixture keeps its expectation, and its corpus record does
not change: `tools/emit_corpus.py` gives the base's records and the 4 new
ones.

**Fingerprints.** A unit that now inherits such a call carries it in its
assertions, so the fingerprint of a whole-unit TEST_DISABLED removal, which
names the unit's assertions, changes for it, as #222's own calls changed it.
No fixture or sweep record holds such a unit before this round.

**Cost.** Measured with the round's engine against main's (`4f0955b`) on
D-102's sets:
- **Targeted set:** every non-merge commit, on any ref, of the twelve
  histories and of PyWavelets whose test-side Python adds or removes a line
  naming `isclose`, `allclose`, `assert_array_almost_equal`,
  `assert_almost_equal` or `assert_close`: 180 commits, 171 readable, as on
  main. No record changes.
- **Standard set:** the last 300 non-merge commits of attrs, click, flask,
  httpx, rich and starlette (1,800 commits) give main's records, byte for
  byte.
- **D-088's sets:** 895 commits of ten full histories (855 readable) and 368
  of pytest's (364 readable) give main's records, byte for byte.

These sweeps reach none of the new channels. In the targeted set, main's
engine and the round's lend the same numpy and torch calls: 70, in 18 of
PyWavelets' commits, all through same-file helpers, which #222 already
read. PyWavelets defines no pytest fixture anywhere in its history. So the
sweeps measure neither a cost nor a benefit, and the round's fixtures pin
its readings.

**Verdict gate.** Run as CI runs it (four engines, 156 T1 + 26 T3 cases):
passed, 0 failures, 1 reported: `i198/T6` is undecided (pass on both
engines), as on main, where #226's relabel (D-104) has not landed. Every
other case keeps v0.6.0's verdict.

The agent wrote this entry in the fix PR; the maintainer approves it there.

## D-113 (2026-10-06): a GitLab runner job that cannot fail the pipeline is a weakened command (#214)

In `.gitlab-ci.yml` a test job stops failing the pipeline without any
change to its `script:` lines. `allow_failure: true` (or `allow_failure:`
with `exit_codes`) lets it fail and stay green; `when: manual` or a `rules:`
entry `when: never` stops it from running on its own. GitHub's spelling of
the first, `continue-on-error: true`, is a swallow token and blocks at high.
The runner-site reader (#181, #196 191.x) read GitHub workflows and
`.pre-commit-config.yaml` only, so all four GitLab spellings passed at warn
(THREATMODEL row 112's residual "GitLab/Azure/CircleCI/Travis conditions").

Ruling, 2026-10-03 ([#196](https://github.com/taipei49314/checkwash/issues/196#issuecomment-5965834751), filed as #214):
allow_failure (true or exit_codes), `when: manual` and `when: never` count
only on jobs whose `script:` passes the runner-site predicate. No global
token: a lint job allowed to fail stays at warn. GitHub's
`continue-on-error: true` stays a global token (D-052). The maintainer edit
is row 112's text.

**As implemented:**
- `ci_control_flow._gitlab_sites` reads `.gitlab-ci.yml` (the root file,
  the path the `ci` role names) as an inventory of runner sites: each
  command of a job's `script:` that invokes a test runner
  (`runner_command.invokes_test_runner`, as for a workflow step's `run:`) is
  a site, live when its job can fail a green pipeline. `before_script:`
  and `after_script:` are not the job's test command. The inventory goes
  through the predicates workflows use: a runner command that loses a live
  site and gains a dead one is disabled, and a runner reworded as its job
  dies names both commands (#196 191.8).
- A job is dead when no way of adding it to a pipeline starts it by itself
  with its failure counted (`_gitlab_idle`). Without `rules:`, its own
  `when:` and `allow_failure:` decide. With `rules:`, each entry that may
  match adds the job with its own `when:` and `allow_failure:`, the job's
  where it sets none; an entry with no `if:`, `changes:` or `exists:`
  always matches, so no later entry is reached; and a job no entry adds is
  not in the pipeline. A shape the reader does not take (an empty list, a
  rule that is no mapping) keeps the job live.
- A job's `extends:` templates are merged in first, as GitLab merges them:
  mappings key by key, arrays and scalars replaced, templates in the order
  listed and the job's own keys last (`_gitlab_jobs`). A chain that loops
  or runs deeper than GitLab's eleven levels leaves the job out, and the
  entries merging copies are bounded as merge keys are (100,000).
- The deletion rule reads the GitLab sites too (`holds_runner_site`): a
  deleted `.gitlab-ci.yml` whose only runner is a site row 69's scan does
  not name (`node --test`) ran a suite. That closes D-097's reading 5
  residual.
- The reason says what the job lost: "pytest can no longer fail the
  pipeline (job test allow_failure: true)", "pytest is disabled (job test
  when: manual)", "pytest is disabled (job test rules: when: never)".
- Unchanged: the added-line scan (`pytest || true` in a job's script still
  blocks as before), GitHub's `continue-on-error: true` token, and every
  workflow and pre-commit reason, byte for byte.

Readings the ruling leaves to the implementation:

1. **`when: on_failure` is dead too.** It runs the job only once an
   earlier job has failed, which is how the reader reads `failure()` on a
   GitHub step: false on the otherwise green run, the only run in which the
   suite can turn a passing check red
   (`gitlab_when_on_failure_test_job_pos`).
   `when: delayed` and `when: always` start the job by themselves and keep
   it live.
2. **A hidden job is a job set aside unless another job extends it.**
   GitLab documents a leading `.` as the way to disable a job without
   deleting it, and `test:` -> `.test:` passed at warn
   (`gitlab_test_job_hidden_pos`). A hidden job that a job `extends:` is a
   template: its commands are that job's, so templating a job disables
   nothing (`gitlab_job_templated_neg`). A hidden job used only through a
   YAML anchor and merge key is read as set aside, both sides alike: it
   changes nothing until a diff both drops a live runner job and adds such
   a template with the same command.
3. **`workflow: rules:` that can only say `when: never`** keep every
   pipeline from running, so every site is dead
   (`gitlab_workflow_rules_never_pos`): the ruling's `when: never`, written
   for the whole pipeline. When no workflow rule matches, the pipeline does
   not run, so conditional `when: never` entries alone are dead too; any
   entry that may match and says otherwise keeps the sites live.
4. **A rule's condition is not evaluated.** An entry with `if:`, `changes:`
   or `exists:` may match, so `rules: [{if: $CI_COMMIT_BRANCH == "main"}]`
   keeps the job live although it no longer runs on a merge request's
   branch. Reading those conditions is GitLab's counterpart of the GitHub
   expression folding (#196 191.x) and is left out, with `only:` and
   `except:`.
5. **The ruled spellings, read literally.** `allow_failure` counts as a
   YAML 1.1 boolean, as GitLab's parser reads one (`true`, `yes`, `on` in
   their three cases); a quoted `"true"` is a string GitLab rejects, not a
   swallow. Any non-empty `exit_codes` counts, as ruled, whether or not it
   names the code the runner fails with.
6. **#196 191.3 covers the GitLab pipeline.** A `.gitlab-ci.yml` whose base
   side the reader takes with a live runner site and whose head side it
   declines is out of reach (`CI_BECAME_UNANALYSABLE`), as a workflow is
   (`gitlab_head_yaml_tag_pos`). GitLab's own `!reference` tag is a tag the
   reader declines, so a pipeline that starts using it blocks once, on the
   commit that introduces it; one that used it at base is not read at all.

**Tests and fixtures.**
- **Tests:** 80 in `tests/test_issue214_gitlab_jobs.py`. Twenty-four
  mutants of the round's code each fail them or the fixtures: `manual`
  or `on_failure` read as starting the job; `allow_failure: true` not
  read; only the YAML 1.2 booleans read as true; a quoted `"true"` read
  as one; `exit_codes` not read; an empty `exit_codes` read as one; a
  rule with no condition not ending the list; a rule not taking the
  job's `when:` and `allow_failure:`; an empty `rules:` read as rules; a
  rule that may run the job skipped; `workflow: rules:` not read; an
  unconditional workflow rule not ending the list; a template read as a
  site of its own; a hidden job read as live; the templates winning over
  the job's own keys; no depth limit on `extends:`; a job merged without
  a parent that was left out; mappings replaced instead of merged;
  merging unbounded; `.gitlab-ci.yml` not read for sites; an allowed
  failure reading as disabled; `variables` read as a job;
  `before_script:` read as the test command.
- **Fixtures:**
  - row 112's pins, each passing on v0.6.0 and main at warn:
    `gitlab_allow_failure_test_job_pos` (G1),
    `gitlab_allow_failure_exit_codes_pos` (G2),
    `gitlab_when_manual_test_job_pos` (G3),
    `gitlab_rules_when_never_test_job_pos` (G4),
    `gitlab_when_on_failure_test_job_pos` (reading 1),
    `gitlab_test_job_hidden_pos` (reading 2),
    `gitlab_workflow_rules_never_pos` (reading 3),
    `gitlab_template_when_manual_pos` (`extends:`) and
    `gitlab_head_yaml_tag_pos` (reading 6);
  - what stays at warn: `gitlab_allow_failure_lint_job_neg` (G7),
    `gitlab_allow_failure_kept_neg` and `gitlab_when_manual_removed_neg`
    (the issue's acceptance), `gitlab_rules_skip_tags_neg` and
    `gitlab_job_templated_neg`.

Every existing fixture keeps its expectation, `circleci_weakened_pos` and
every `ci_*` and `precommit_*` fixture included, and its corpus record does
not change: `tools/emit_corpus.py` gives main's 759 records, byte for
byte, and the fourteen new ones.

**Fingerprints.** None move: a GitLab job that can no longer fail the
pipeline reports a reason where it reported none, and every other reason
is the same text.

**Cost.** Measured with the round's engine against main's (`4f0955b`):
- **GitLab set** (recorded before any engine ran on it): every non-merge
  commit touching `.gitlab-ci.yml` in the default-branch history of eight
  GitLab-hosted projects, ase, fdroidserver, graphviz, hyperkitty,
  inkscape-extensions, libvirt-python, mailman and postorius: 1,532
  commits, 1,443 readable (89 hold a submodule the snapshot reader
  declines on both engines). Six records change, each pass -> block:
  - `allow_failure: true` added to a runner job: postorius `d1602e2c`
    (`git-heads`) and `da891d9e` ("allow released to fail");
  - an `allow_failure: true` rule for merge request pipelines on ase's
    `bleeding-edge` job (`a252419c`, "allow bleeding-edge job to fail"),
    whose only rule also keeps the job out of every other pipeline;
  - `when: manual` on ase's `pytest` job (`f6eaab0e`);
  - ase's `windows_test` hidden as `.windows_test` (`5f6460d2`, "cannot
    currently run windows tests, disable for now"; reading 2);
  - ase `1f8c6c20`, out of reach (reading 6): its head is YAML GitLab
    itself rejects, a quoted scalar followed by `|| echo`.
  Each is a ruled spelling or a reading above, and none misreads the
  file. The projects meant them (a bleeding-edge or flaky job allowed to
  fail, a job set aside): the ruling's accepted cost, where a reviewer
  accepts the block, as for GitHub's `continue-on-error: true`.
- **The standard set and D-088's sets cannot move:** no commit of the
  thirteen sweep histories touches `.gitlab-ci.yml`, the only file the
  round reads differently, and every workflow and pre-commit reason is
  the same text.

**Verdict gate.** Run as CI runs it (four engines, 156 T1 + 26 T3 cases):
passed, 0 failures, 1 reported: `i198/T6` is undecided (pass on both
engines), as on main, where #226's relabel (D-104) has not landed. Every
other case keeps v0.6.0's verdict.

The agent wrote this entry in the fix PR; the maintainer approves it there.

## D-114 (2026-10-07): a positional target in addopts is an explicit target of every run (#173)

pytest puts the root config's `addopts` before its own arguments, so a
word there that is no option and no option's value is a target: `addopts =
"tests/smoke"` makes a bare `pytest` collect tests/smoke alone, and
testpaths no longer applies. The resolved collection inventory (§2b, #173,
#196 184.x) read `addopts` for its options only, so a first or changed
config that pointed every run at part of the suite passed at warn, while
the same narrowing through `testpaths` blocked. THREATMODEL row 105 listed
it as residual (6).

Ruling ([#196](https://github.com/taipei49314/checkwash/issues/196#issuecomment-5965834751), 196.followup.addopts-positional-targets):
not filed separately; handled with one definition of explicit targets for
the CLI and for `addopts`. The maintainer decision of 2026-10-06 closes
#173 once its ruled items are done; (3) was #221, and this is (6).

**As implemented:**
- `shadow._pytest_cli`, which reads a command's targets, reads `addopts`'
  words too. It now knows pytest's own options that take a value (`-p`,
  `-W`, `-r`, `--tb`, `--capture`, the `--log-*` options and the rest)
  and the common plugins' (pytest-xdist's `-n`, `--dist`; pytest-cov's
  `--cov-report`, `--cov-config`; pytest-timeout, pytest-rerunfailures,
  pytest-html, pytest-randomly, pytest-django, pytest-asyncio and
  hypothesis), and gives `--cov`, `--debug` and `--cache-show` an optional
  value, as argparse does: they take the next word unless it is an option.
- `collection_inventory`: a run collects beneath its command's targets and
  the `addopts` targets together. When the `addopts` targets change, the
  base runs, read from the base side's runner files with the base
  `addopts`, and the head runs, with the head's, are applied to the same
  head tree under the base settings, and a base-suite test the base runs
  collected and no head run collects is excluded: "resolved pytest
  collection excludes N existing test(s), including ...", the settings
  proof's reason. A renamed file keeps its base identity. A word in
  `addopts` that names no file or directory on its side is no target.
- The settings proof stays withheld for a run with explicit targets,
  whether its command's or its config's `addopts`'.

Readings the ruling leaves to the implementation:

1. **The runs together.** A test is lost only when no head run collects
   it, so pointing one run at a subset while another still runs the rest
   loses nothing, and neither does a target moved between a command and
   `addopts` (`pytest tests/smoke` -> `pytest` with `addopts =
   "tests/smoke"`), as an option moved into the config is not new
   (#196 184.3).
2. **A word that names no path is no target, and a run that cannot pass
   makes no claim.** A word in `addopts` that names no file or directory
   on its side is the value of an option the reader does not know
   (aiohttp's `--loop all`), or a target that makes every run fail
   (pytest exits 4); either way it narrows nothing, so it is not read as
   a target, and it does not withhold the settings proof. A head run whose
   command names a missing path fails the same way, and one that collects
   no test fails too (exit 5), so neither is a passing narrowing. An
   unknown option's value that names a path still reads as a target
   (residual). The sweep showed why the first half is needed: the
   settings reader cuts a multi-line `addopts` at its first line with
   `=` and leaves the word `[` (attrs, scrapy; filed as #324), which
   would otherwise have withheld the settings proof for those configs.
3. **One definition, both readers.** The longer list of options changes
   how a command's own targets are read as well: `pytest -n 4 tests`
   reads `tests` alone, where `4` was a target, and `pytest --cov src
   tests` reads `tests` alone, as pytest does. This reaches the selector
   proof's runs (#196 184.1) and the runtime-shadow reading of which
   tests a changed runner reaches.
4. **Ambiguous `addopts`** (two values in the config pytest reads)
   withholds the inventory, as an ambiguous setting does; the options of
   every value were counted before.
5. **A node id is read at file granularity,** as a command's is: `addopts
   = "tests/a.py::test_x"` keeps every test of `tests/a.py` (residual).

**Tests.** 53 in `tests/test_issue173_addopts_targets.py`. Each of the
round's 27 mutants fails them: one of nine value-taking options forgotten
(`-p`, `-W`, `-r`, `--log-level`, `-n`, `--dist`, `--cov-report`,
`--timeout`, `--reruns`); `--cov`'s optional value ignored, or taken before
an option; ambiguous `addopts` read; the `addopts` targets dropped, or a
change of them ignored; testpaths applied beside them; a run that collects
no test, or whose command names a missing path, counted; a command's own
targets dropped, on either side; the base runs read from the head; the
inventory judged for a run with `addopts` targets; a renamed file's base
identity lost; a word that names no path read as a target, a directory not
counted as a path, the base side's words read against the head tree, or the
base tree built without the diff's base-side files. The resolved inventory
runs on a snapshot the case runner does not supply, so the round's pins are
tests, as #196 184.1-184.3's are; the corpus does not change:
`tools/emit_corpus.py` gives main's 759 records, byte for byte.

**Fingerprints.** No swept record moves. A narrowed run reports the
settings proof's reason where it reported none. A settings change beside
an `addopts` target is no longer judged by the settings proof, which that
target overrides, so a finding the proof gave there now comes, if at all,
from the static checks under their reason; no swept history puts a target
in `addopts`.

**Cost.** Measured with the round's engine against main's (`4f0955b`):
- **Targeted set:** every non-merge commit of the twelve histories and of
  PyWavelets whose root `pytest.ini`, `.pytest.ini`, `pytest.toml`,
  `.pytest.toml`, `setup.cfg`, `tox.ini` or `pyproject.toml` adds or
  removes a line naming `addopts` (84), and every one that adds or removes
  a line running pytest with an option that takes a value (`-n`, `-W`,
  `-p`, `-r`, `--tb`, `--cov`, `--cov-report`, `--dist`, `--timeout`,
  `--reruns`, `--log-level` and others; 100): 183 commits, 167 readable.
  No record changes.
- **Standard set:** the last 300 non-merge commits of attrs, click, flask,
  httpx, rich and starlette (1,800 commits) give main's records, byte for
  byte.
- **D-088's sets:** 895 commits of ten full histories (855 readable) and
  368 of pytest's (364 readable) give main's records, byte for byte.

No commit of these sets puts a path in `addopts` on either side, so the new
target reading never fires there. 248 of them hold a word in `addopts` that
names no path: aiohttp's `--loop all`, and the `[` that attrs' and scrapy's
multi-line arrays read as (#324). Only in those 248 does the rule of reading
2 that such a word is no target change what the engine reads; they were run
again with the round's final engine, and give main's records too.

**Verdict gate.** Run as CI runs it (four engines, 156 T1 + 26 T3 cases):
passed, 0 failures, 1 reported: `i198/T6` is undecided (pass on both
engines), as on main, where #226's relabel (D-104) has not landed. Every
other case keeps v0.6.0's verdict.

The agent wrote this entry in the fix PR; the maintainer approves it there.

## D-115 (2026-10-06): chai's should-style and property assertions are read (#215)

v0.5.0 (#190) read two chai forms: `expect(...)` chains that end in one
terminal, and the `assert` interface. Should-style was not read at all:
weakening, rewriting or deleting `total.should.equal(78.75)` gave zero
findings and no coverage notice. A property assertion
(`expect(order).to.have.property("total", 78.75)`,
`assert.propertyVal(order, "total", 78.75)`) was recorded with no strength
(#196 190.5), so dropping or rewriting its value passed with a coverage
notice, and respelling `expect(order.total).to.equal(78.75)` as one
blocked as a removal (N1). THREATMODEL row 111 listed both as open.

Ruling ([#196](https://github.com/taipei49314/checkwash/issues/196#issuecomment-5965834751),
2026-10-03, and the [maintainer decision on #215](https://github.com/taipei49314/checkwash/issues/215#issuecomment-6016537935),
2026-10-06): should-style is judged in full, mapped onto the lattice as
`expect` chains are; `.property(name[, value])`, its nested and own forms
and `assert.property`/`propertyVal`/`deepPropertyVal` retarget the
assertion to `subject[name]` with the value as the expectation, and
`.property(name)` alone asserts only that the property is there, on a rung
of the existing lattice. The two pin flips the issue names are authorized:
`test_should_style_is_outside_the_scan` and the `.own.property` row of
`test_unsupported_chai_spellings_remain_coverage_gaps`.

**As implemented:**
- `frontends/javascript/frontend.py`:
  - `.property(name)`, `.ownProperty(name)` and `.haveOwnProperty(name)`
    move the subject of the rest of an `expect` chain to the property
    (`property_subject`): with a value, the chain is an equality on the
    property, deep under `deep`; without one, at the chain's end, it is
    presence, `type_shape` on TYPE_SHAPE. `nested` reads the name as a
    path and `own` as the plain property; as in chai, `deep`, `nested` and
    `own` stay set for the rest of the chain.
  - `assert.property`, `ownProperty`, `nestedProperty`, `propertyVal`,
    `ownPropertyVal`, `deepPropertyVal`, `deepOwnPropertyVal`,
    `nestedPropertyVal` and `deepNestedPropertyVal` read the same way,
    subject first. One whose property cannot be followed is recorded with
    no strength, as an unread assert method is.
  - Should-style (`_should_assertions`): `value.should.<chain>` is read as
    `expect(value).<chain>` by the same chain reader (the value is the
    member chain before `.should`, with a `new` that precedes it, as
    `new` binds first), and `should.equal`,
    `should.exist` and their `should.not` forms, on the object
    `chai.should()` (or `chai.Should()`) returns, take the subject first. A
    should chain the reader declines is recorded with no strength.
- `frontends/javascript/bindings.py`: `chai.should()` (or `chai.Should()`)
  returns the should object, and so does an undeclared `should`, the global
  `chai/register-should` sets to it; a call on it is a chai assertion
  candidate.
- `frontends/javascript/coverage.py`: a `.should` chain is a candidate in
  the coverage inventory, so one the scan does not represent shows the
  banner.

Readings the ruling leaves to the implementation:

1. **A `.should` chain is read wherever a test spells it, and an undeclared
   `should` is chai's.** `chai.should()` adds the getter to every object,
   and projects run it in a setup file the runner loads (mocha's
   `--require`, `chai/register-should`, which also sets the global
   `should` to the object `chai.should()` returns), which this file-local
   scan cannot see. So the setup is not required, as an unimported global
   `expect` is read too. should.js extends `Object.prototype` the same way
   with mostly the same words: its chains read as chai's, its own words
   (`exactly`, `containEql`) are recorded with no strength, and its global
   `should.equal`, node's coercive `equal`, reads as chai's strict one. A
   `should` declared in the file from another module is not chai's. A
   `.should` that no chain continues (`options.should`,
   `options.should = true`) and a call of it (`chai.should()`) assert
   nothing.
2. **Presence is TYPE_SHAPE.** A key's presence is a shape check on the
   subject, the rung of `isinstance` and `len(x) == n`. It sits above
   NON_NULL although neither check implies the other (presence passes a
   null value; `.exist` passes an inherited key): `.exist` on the value ->
   `.property(name)` reads as a strengthening, and the reverse as a
   weakening.
3. **`own` reads as the plain property**, so dropping `own` is not reported
   (row 111, still open). `include` reads `own` and `nested` too, and stays
   unread with either flag, as before.
4. **The retargeted subject is spelled as source.** A literal name reads as
   `order.total` (`order["unit price"]` when it is no identifier), a
   computed one as `order[key]`, and a nested path as the member chain it
   spells (`order.totals.gross`, `order.lines[0].price`), so a property
   assertion pairs with the `expect(order.total)` spelling of the same
   check. A nested path that is not a literal is not followed, and the
   assertion is recorded with no strength.
5. **A chain after a property reads its last check.**
   `.property("total").that.equals(78.75)` reads as the equality, which
   holds only for a present property unless the value is `undefined`. A
   negated property with a chain after it is recorded with no strength.
6. **The assert interface's own and nested forms** (`ownProperty`,
   `ownPropertyVal`, `deepOwnPropertyVal`, `nestedProperty`,
   `nestedPropertyVal`, `deepNestedPropertyVal`) read as their expect
   counterparts do, beside the three methods the ruling names.
7. **Four more pins in `tests/test_js_unjudged_assertions.py`**, flagged for
   approval: 190.5's examples of an unread chai assertion used `property`
   in three rows of `test_an_unread_assertion_is_recorded_with_no_strength`
   and one of `test_deleting_an_unread_assertion_is_assert_removed`. They
   keep what they pin (an unread chai assertion is recorded with no
   strength, and deleting it is ASSERT_REMOVED) with spellings that stay
   unread: `.to.have.keys`, `.to.be.an(...).that.has.keys` and
   `assert.hasAllKeys`.

**Tests and fixtures.**
- **Tests:** 129 in `tests/test_issue215_chai_grammar.py`. Thirty-seven
  mutants of the round's code each fail them: presence on another rung;
  `propertyVal` comparing deeply, or `deepPropertyVal` strictly;
  `nestedProperty` reading a plain key; the assert own forms unread; a
  plain key read as an index; a computed key not followed; any nested path
  followed; an expression subject not parenthesized; the `own` flag not
  taken, or `nested` ignored; the rest of a chain after a property not
  followed; a negated property with a chain after it followed; a deep
  property value compared strictly; a negated presence read as positive;
  `include` reading `own` and `nested` as absent; an expect chain not
  retargeted; should-style not read; a `.should` no chain continues, or a
  call of `.should`, taken for a site; a should chain the reader declines
  not recorded; `should.exist` not read, or `should.not` not negated; a
  should method the scan does not read not recorded; an assert property
  call that cannot be followed not recorded; the assert property methods
  not read; the name taken as the value; a call without a name read;
  `chai.Should` no alias; `should.not`'s methods not negated;
  `chai.should()` not returning the should object; an undeclared `should`
  not chai's global; a call on the should object no candidate; should
  chains not in the coverage inventory; a recorded should chain read as
  unrepresented; a `new` before a chain left out of its subject, and the
  coverage notice dropping the space after it.
- **Fixtures** (18), each `_pos` passing on v0.6.0 with zero findings:
  - should-style: `js_chai_should_equal_to_exist_pos` (SH1),
    `js_chai_should_expected_rewrite_pos` (SH2),
    `js_chai_should_deleted_pos` (SH3), `js_chai_should_true_to_ok_pos`
    (SH4),
    `js_chai_should_require_setup_pos` (SH5),
    `js_chai_should_register_import_pos` (SH6),
    `js_chai_should_object_exist_pos` (SH7);
  - property: `js_chai_property_value_dropped_pos` (P1),
    `js_chai_property_value_rewrite_pos` (P2),
    `js_chai_nested_property_value_dropped_pos` (P3),
    `js_chai_own_property_value_dropped_pos` (P4),
    `js_chai_property_chain_tail_dropped_pos` (P5),
    `js_chai_assert_property_val_dropped_pos` (P6),
    `js_chai_assert_deep_property_val_dropped_pos` (P7),
    `js_chai_assert_property_val_rewrite_pos` (P8);
  - respellings that report nothing: `js_chai_property_respelled_neg`
    (N1, which blocked on v0.6.0 as a removal),
    `js_chai_property_assert_respelled_neg` and
    `js_chai_should_respelled_as_expect_neg`.

Every existing fixture keeps its expectation, and the chai mutation
inventory (`tests/data/javascript_chai_mutations.json`, 39 records) keeps
every verdict. `tools/emit_corpus.py` gives the base's 783 records and the
18 new ones; one existing record changes, `js_chai_property_deleted_pos`:
the same ASSERT_REMOVED high, fingerprint and verdict, with the strength it
now reads in its message and IR (TYPE_SHAPE, presence on `order.total`,
where it said UNKNOWN).

**Fingerprints.** No corpus fingerprint moves. TEST_DISABLED's fingerprint
for a removed unit keys on the unit's assertions, so a removed unit that
holds a should-style or property assertion, now read, gets a new one, as
190.5's newly recorded assertions did; an allowlist entry for such a
finding needs renewing.

**Cost.** Measured on four JavaScript histories whose tests use chai
should-style or property assertions: chai, hexo, node-fetch and yargs.
The set is every non-merge commit whose JS or TS diff adds or removes a
line spelling `should.`, `Should(`, `propertyVal`, `.property(`,
`ownProperty` or `nestedProperty`: 1,399 commits, all readable. The
round's engine was run against the base branch's (`5fa3554`). 277 records
change and 58 verdicts move, so blocked goes from 18 to 72: 56 commits
start blocking and 2 stop.
- **True positives: 24 of the 56.** Each commit's message or diff shows
  the edit was meant:
  - fifteen expected values follow a behaviour or fixture change in the
    same commit (hexo `2cdecbfdec9e`, `fffafac27de8`, `d1c3098f0120` and
    twelve more);
  - two removals or flips come with a breaking change (yargs
    `a93f5ff35d7c`, `6ee2c82df515`);
  - seven are real loosenings or deletions: `=== undefined` -> `== null`
    (hexo `c3d0367955c8`, `1936e68dc897`), timestamps cut to whole
    seconds (`28ac0697c2aa`), event order no longer asserted
    (`1c8cd09d823f`), `>` -> `>=` (yargs `c68127ac5e9a`,
    `4e186e036193`), and a check in a callback deleted
    (`86457538ef4e`).

  Each is reported for a reviewer, as the same edit spelled with `expect`
  already was.
- **False positives: 31 of the 56.** Twenty-eight of them are classes of
  the existing `expect` reader, and the base engine blocks the `expect`
  twin of each the same way:
  - an expected call respelled through a destructured import, such as
    `pathFn.join` -> `join` (twelve hexo commits; filed as #312);
  - a check moved onto a form the reader records with no strength. Most
    are row 111's open words: `.keys`, `.string()`, `should.throw(fn,
    msg)`, a `should.fail` sentinel, a mocha `done` callback. The others
    are `sinon.assert` calls (hexo `f766caf592a3`, 69 findings; filed as
    #314);
  - two spellings of one check ranked apart: `x.length` equality ->
    `lengthOf(n)` (hexo `70c5378525ef`, 30 findings; filed as #313),
    per-field `eql` -> `deep.include`, and a value check -> a sinon
    query asserted true;
  - a renamed test paired with an unrelated new one;
  - a private field read through the public API;
  - an expected value respelled, such as one only requoted (hexo
    `2d7937d3e8ff`). That one is a defect of D-104's JavaScript port,
    fixed in its PR;
  - a strengthening read as SUBJECT_NORMALIZED.
- **Three false positives owe their block to this round:**
  - chai `6ccbd0378053` stores the should object under another global
    name (`globalShould = chai.should()`), which is not followed.
  - hexo `03e1a1d067ed` spells own-property presence two ways:
    `hasOwnProperty.call(o, k).should.eql(true)` (EXACT_STRUCT) ->
    `o.should.have.own.property(k)` (presence, TYPE_SHAPE, reading 2).
    The base blocks the `expect` twin of this edit as a removal.
  - In node-fetch `c3a4e96a61b9`, a presence check, now read, takes the
    position-order pairing from a renamed subject's `deep.equal`.
- **One mixed commit:** hexo `f3d2c37ec3d4`. Twelve findings are #312's
  class. One is real: an async rewrite dropped the check that the call
  rejects.
- **Two commits stop blocking:**
  - hexo `3d59784da286`: a `contain` respelled as
    `includes(...).should.eql(true)` is now paired. The commit still
    loses a sentinel that neither engine reads.
  - hexo `3e8473027739`: `assert.fail()` sentinels are replaced by
    spy-count checks the round reads, and they are held at warn as a
    rewrite.
- **Twin check.** Each JS test file changed by the 1,186 commits that
  touch one was rewritten with every `x.should.` as `expect(x).`. The
  round judges 1,184 of them as it judges their twin (verdict and high
  rules). The other two are in chai's own suite, whose
  `var expect = chai.expect` reads a global `chai` the reader does not
  take (filed as #311). The base engine gives 1,173 twins the verdict
  the round gives the original. The other 13 involve what only the round
  reads: property assertions, the should object's `equal` and `exist`,
  and chai's own should chains.
- **The Python sweep cannot move.** No commit of the thirteen sweep
  histories touches a JS/TS test file (D-106), and only such a file is
  read this way.

**Verdict gate.** Run as CI runs it (four engines, 156 T1 + 26 T3 cases)
on the round's engine: passed, 0 failures, 1 reported: `i198/T6`, which
passes on v0.6.0 and blocks here, as D-104 labels it. Every other case
keeps v0.6.0's verdict.

The agent wrote this entry in the fix PR; the maintainer approves it there.

## D-116 (2026-10-07): `py.test` is the pytest module wherever a skip is read (#310)

The py library's `py.test` is pytest itself: py 1.11.0 maps its `test`
attribute to `pytest` and binds `sys.modules['py.test'] = pytest`. #260
(D-090) reads `py.test.mark.*` decorators as pytest's marks, since a mark
decorator is read by its last components. A skip a test body calls or raises
is read through the module's import bindings (#220, D-100), and those bound
native modules only, so `import py` bound nothing. `py.test.skip()` and
`py.test.xfail()` in a test passed with zero findings, and the same skip
respelled `pytest.skip()` read as a skip added. #272's sweep found the
second in pytest `3cc58c2f78f0`, inside a helper (D-111). Filed as #310.

No ruling was asked: the issue's proposed direction extends #220's one-name
reading (D-100) to one more name of the same object, and this entry, in the
fix PR, is where the maintainer approves it.

**As implemented:**
- `setup_skip_controls`: `py` and `py.test` are native modules, and a dotted
  name read through them is pytest's (`_pytest_name`: `py.test.skip` is
  `pytest.skip`, `py.test.skip.Exception` is `pytest.skip.Exception`).
  Every reader of these bindings takes it: a test body's skips and their
  guards (D-100, row 54), the same-file helpers a test calls (D-111), the
  setup a unit runs, a fixture declared with `@py.test.fixture` included,
  and the closed `pytest_runtest_setup` hook proof.

Readings the direction leaves to the implementation:

1. **Only an import of the py library.** `py` is read as the py library
   where an import binds it (`import py`, `import py.test`, `import py as
   p`, `from py import test`, `from py.test import skip`). A `py` no import
   binds keeps its spelling, which names no outcome; a `py` rebound, or
   imported from another module, is not the library.
2. **The py library's meaning.** pytest 7.2 and later ship a `py` shim of
   their own with `py.path` and `py.error` only. With that shim and no py
   library, `py.test` does not exist, and `py.test.skip()` raises
   AttributeError, so the test fails rather than passing. With py 1.11.0
   installed, pytest 9.1.1 reports `py.test.skip()` as skipped and
   `py.test.xfail()` as xfailed (run for this entry). The reading takes
   the py library's meaning, as #260 does for `py.test.mark`: a skip added
   through it is reported, and one respelled between `py.test` and `pytest`
   is the skip the test had.
3. **One name for the marker.** The marker carries pytest's name
   (`pytest.skip`), so a finding's message and fingerprint are those of the
   same skip spelled `pytest.skip()`.

**Tests and fixtures.**
- **Tests:** 30 in `tests/test_issue310_py_test_alias.py`. Each of the
  round's eight mutants fails them: `py.test` not read as pytest, read on
  a name it only begins (`py.testing`), or not read as the bare module;
  `py` or `py.test` dropped from the native modules; the reading dropped
  from the setup and helper readers, or from the body's; a `py` no import
  binds read as the library.
- **Fixtures:**
  - row 118's new pins, each passing on v0.6.0 with zero findings:
    `py_test_skip_added_pos` (P1) and `py_test_xfail_added_pos` (P3, in
    the `from py.test import xfail` spelling);
  - controls with no finding: `py_test_skip_respelled_pytest_neg` (P4,
    which v0.6.0 blocks as a skip added) and
    `py_test_skip_respelled_in_helper_neg` (pytest `3cc58c2f78f0`'s
    respelling inside a helper, which D-111's engine blocks as a skip added
    to the helper).

Every existing fixture keeps its expectation, and every existing corpus
record is byte for byte the same; the corpus gains the four fixtures'.

**Fingerprints.** None moves. A skip now read through `py.test` is a new
finding, and a respelling between `py.test` and `pytest` that read as a skip
added no longer does.

**Cost.** Measured with the round's engine against #272's (`343ff7b`, the
head of #316), on which the round is stacked:
- **Targeted set:** every non-merge commit, on any ref, of the sweep
  histories whose test-side Python adds or removes a line spelling
  `py.test.` or importing `py` (`import py`, `from py import`, `from
  py.test import`): 669 commits in four histories (pytest 651, werkzeug 9,
  scrapy 7, aiohttp 2), 559 readable. 23 records change, all pytest's, and
  8 verdicts move: blocked goes from 102 to 108.
  - **1 stops blocking:** pytest `3cc58c2f78f0`, the issue's own commit,
    whose `py.test.skip` respelled `pytest.skip`, in the `lsof_check`
    helper and in a test body, read as four skips added.
  - **7 start blocking.** Six add a `py.test.skip`, `py.test.xfail` or
    `py.test.importorskip` to an existing test or to the setup it runs
    (`a6003ac3`, `ac934bb2`, `621f9259`, `a7dfacca`, `44337db2`,
    `1e7d5166`), as the `pytest` spelling blocks. The seventh, `4f5d7948`,
    moves a test into a file where it carries a guarded `py.test.skip`, so
    the arrival is not live, the move earns no credit and the departure's
    disappearance is high, as with `pytest.skip` there.
  - **The other 15 keep their verdict.** Two lose skips added that were
    respellings (`9fb20794`, `a6984654`); thirteen gain or change findings
    at warn or info.
- **Twin check.** Each changed commit, respelled `py.test.` -> `pytest.`
  with `import pytest` beside `import py`, gives the round's TEST_DISABLED
  findings under #272's engine in 21 of the 23. In `78d33a2f` two
  disappeared units swap info and warn. In `e991bf21` twelve setup skips
  are high in the twin and warn here: its helper file mentions only
  `py.test`, which is no runner name, so it keeps the opaque-production
  exemption (REPAIR_EVIDENCE); filed as #325.
- **Standard set:** the last 300 non-merge commits of attrs, click, flask,
  httpx, rich and starlette (1,800 commits) give #272's records, byte for
  byte.
- **D-088's sets:** 895 commits of ten full histories (855 readable) give
  #272's records, byte for byte. Of pytest's 368 (364 readable), three
  change: the targeted set's `3cc58c2f`, `9fb20794` and `a6984654`.

**Verdict gate.** Run as CI runs it (four engines, 156 T1 + 26 T3 cases):
passed, 0 failures, 1 reported: `i198/T6` is undecided (pass on both
engines), as on main, where #226's relabel (D-104) has not landed. Every
other case keeps v0.6.0's verdict.

The agent wrote this entry in the fix PR; the maintainer approves it there.

## D-117 (2026-10-06): an undeclared `chai` is chai's module (#311)

The JS reader resolves a name no scope declares through a short table of
runner globals: `expect`, `assert` (Node's), `t`, `test`, `it`, `require`,
and since #215 (D-115) `should`. `chai` was not in it, so an undeclared
`chai` was unknown, and so were `chai.expect`, `chai.assert` and an `expect`
or `assert` bound from them. karma-chai loads chai's browser build, which
defines `window.chai`, and its adapter sets the `should`, `expect` and
`assert` globals from it (karma-chai 0.1.0's `adapter.js`, read from the
published tarball). chai's own suite sets `global.chai` in its bootstrap
(`test/bootstrap/index.js`) and binds `var expect = chai.expect;` in each
`describe`. So `expect(x).to.equal(y)` -> `.to.exist` there passed with a
coverage notice, a deletion passed, and `chai.expect(...)` written directly
was no candidate at all. #215's twin check found it: the round read chai's
should-style chains, but not their `expect` twins. Filed as #311.

No ruling was asked: the issue's proposed direction reads the global as
#215 reads an undeclared `should` (D-115, reading 1), and this entry, in
the fix PR, is where the maintainer approves it.

**As implemented:**
- `frontends/javascript/bindings.py`: an undeclared `chai` resolves to
  chai's module (`Value("chai")`), as an imported or required one does, so
  `chai.expect`, `chai.assert`, `chai.should()` and `chai.Should()`, and the
  names bound from them, read as through an imported chai, in the assertion
  scan and in the coverage inventory.

Readings the direction leaves to the implementation:

1. **Only an undeclared `chai`.** A `chai` the file declares, imports,
   requires from another path or takes as a parameter keeps its own
   binding, as a local `expect` does.
2. **`window.chai` is not read.** karma's test files use the globals the
   adapter sets, and `window` is no binding the reader follows; it stays a
   residual of row 111.
3. **Only chai's own members assert.** Through the global as through an
   import, `chai.expect` and `chai.assert` are candidates and `chai.use`
   or `chai.config` are not.

**Tests and fixtures.**
- **Tests:** 17 in `tests/test_issue311_global_chai.py`. Three mutants of
  the round's code each fail them: the global not read, or read as
  chai's `expect` or as its `assert` instead of its module.
- **Fixtures** (4):
  - row 111's new pins, each passing on v0.6.0 with zero findings:
    `js_chai_global_expect_weakened_pos` (K1),
    `js_chai_global_assert_weakened_pos` (K4) and
    `js_chai_global_member_expect_pos` (K5);
  - `js_chai_global_shadowed_by_local_neg`: a `chai` the file declares is
    not chai's module.

Every existing fixture keeps its expectation, and the chai mutation
inventory (`tests/data/javascript_chai_mutations.json`, 39 records) keeps
every verdict. `tools/emit_corpus.py` gives the base's records unchanged
and the 4 new ones.

**Fingerprints.** No corpus fingerprint moves. The assertions read through
the global are new findings, and a removed unit that holds one gets a new
TEST_DISABLED fingerprint, as D-115 notes for should-style; an allowlist
entry for such a finding needs renewing.

**Cost.** Measured on D-115's four JavaScript histories: every non-merge
commit of chai's that touches `test/` (427), and the commits of hexo,
node-fetch and yargs whose JS or TS diff adds or removes a line spelling
`chai.` (15): 442 commits, all readable. The round's engine was run
against the base branch's (`c46bba5`). 29 records change, all in chai's
own history, and 5 verdicts move: blocked goes from 9 to 14, and none
stops blocking.
- **One true positive:** chai `f6c4fa3939d9` drops the check that the
  property a test overwrites is there
  (`expect(new chai.Assertion()).to.have.property('tea')`, which an
  earlier test's leftovers made true) and adds the property instead.
- **Four false positives, each a class of the existing reader.** The base
  engine blocks each the same way once the file requires chai:
  - `assert.throws(...)` respelled `assert[throws](...)` in a loop over
    its aliases, a computed member the reader does not read (`3be31001d1e3`,
    13 findings; `40dc848842bd`, 12, for `isFrozen`, `isSealed` and
    `isExtensible`);
  - a check moved from a test into a `describe`'s `before` hook, which is
    not the test's (`5d11228cfa42`, 2);
  - four tests rewritten as twenty-four, where the renamed-test pairing
    matches four of the new tests with the old ones and the old
    assertions they do not keep read as removed (`8fa4f7857456`, 8).
- **The other 24 records keep their verdict.**
  - Eighteen gain warn or info findings: 2,401 in all, 2,257 of them in
    one commit. Every one but `f73d026f2863` (two info findings) changes
    `lib/` too. The big one is chai's own move off the global:
    `0fc290b5ea98` (Karma to Web Test Runner) replaces `var assert =
    chai.assert` with `import * as chai from '../index.js'`, a chai
    another path exports (reading 1). The round reads the base side's
    2,257 assertions and not the head side's, and reports them removed
    at warn.
  - `7f8a268e5206` loses a warn finding: a check respelled through the
    global now pairs with its new spelling.
  - In `dd5159407588` (blocked on both), a substitution read through the
    global adds a high finding.
  - In four records (`d89a9fe470ad`, `93be4b15d9c3`, `a33ab4818682`,
    `7bc580910ee3`), TEST_DISABLED findings on removed units take a new
    fingerprint and nothing else changes.
- **Equivalence check.** Each of the 442 commits was also judged by the
  base engine with `var chai = require('chai');` prepended to every
  changed file under `test/` that declares no `chai` of its own. On all
  442, that record is the round's on the commit as it is: the round
  reads chai's own suite as an imported chai is read, and nothing else.
- **The Python sweep cannot move.** No commit of the thirteen sweep
  histories touches a JS/TS test file (D-106), and only such a file is
  read this way.

**Verdict gate.** Run as CI runs it (four engines, 156 T1 + 26 T3 cases)
on the round's engine: passed, 0 failures, 1 reported: `i198/T6`, which
passes on v0.6.0 and blocks here, as D-104 labels it. Every other case
keeps v0.6.0's verdict.

The agent wrote this entry in the fix PR; the maintainer approves it there.

## D-118 (2026-10-07): AVA's and tap's tests are read (#233)

AVA's and tap's assertions are methods of the `t` each test callback
receives, and neither was read. `t.is(total(), 78.75)` ->
`t.truthy(total())` passed with zero findings wherever the file was parsed
(#233 A3, T2). Their default layouts collect `tests/**`, a path that is no
JS test path for Node's runner or Jest, so beneath `tests/` the file was
never parsed and even a deleted test passed (A1, A2, T1). The ruling of
2026-10-03 (196.followup.ava-tap-tests-dir) asked for runner evidence, a
layout row and the dialect. The owner confirmed the issue's direction on
2026-10-06 (the maintainer decision on #233): an `ava` or `tap` import, or a
base root `package.json` naming one of them alone, names the runner, with
evidence-only rows; layout rows from the runners' defaults; and AVA's and
tap's `t` assertions mapped onto the existing lattice and predicate keys,
read only on the callback's own `t` (and tap's top-level `t`).

**As implemented:**
- `frontends/javascript/runners.py`: `ava` and `tap` imports and requires
  name the runner, and so does a base root `package.json` that names one of
  them and no other runner. AVA 8's (`lib/globs.js`, `lib/extensions.js`)
  and tap 21's (`@tapjs/config`'s `include` and `exclude`) defaults are
  their rows, in `EVIDENCE_ONLY` beside Bun's and Deno's. Those rows
  collect JS/TS extensions only, so any other file is answered without
  reading them, and a Python-only diff does not pay for the new two.
- `frontends/javascript/paths.py`: those rows give a file test obligations
  only on its own evidence (`is_js_test_file`), either side's import being
  enough.
- `frontends/javascript/bindings.py`: AVA's test function (its default
  export, with its modifiers and hooks, `test.serial`, `test.failing`,
  `test.skipIf(cond)(...)`, `test.macro(fn)` and the rest) passes AVA's `t`
  to the callback it declares. tap's module (its default export and named
  `t`, its CommonJS export, which is `t` itself, and a `test` imported or
  required from it) declares subtests whose callback gets tap's `t`, and
  `t.test(...)` on any of them declares the next level. A method of either
  `t` resolves by name, for the assertion scan and the coverage inventory:
  AVA 8's methods, and tap 21's with tap 16's `expectUncaughtException`
  and synonyms (reading 7).
- `frontends/javascript/frontend.py`: the dialect (`_AVA_METHODS`,
  `_TAP_METHODS`) is read with chai's meanings (`_chai_assertion`); the
  other assertions are recorded with no strength (#196 190.5); AVA's
  `serial` is a neutral modifier, so a serial test is a unit.

Readings the decision leaves to the implementation:

1. **The meanings**, subject first: AVA's `is` (Object.is) and tap's
   `equal` (===) are a strict equality, and `not` its negation;
   `deepEqual`, `same` and `strictSame` the structural equality, and their
   negations; AVA's `like` and tap's `has`/`hasStrict` membership (PATTERN),
   as chai's deep `include` is, since each asserts a subset of fields;
   `true` and `false` the `=== true` and `=== false` keys; `truthy`, AVA's
   `assert` and tap's `ok` truthiness, `falsy` and `notOk` its negation;
   `regex` and tap's `match` a pattern, and their negations. A negation is
   read as chai's `.not` is (D-115's `should.not`). The others are recorded
   with no strength: AVA's `throws` and `throwsAsync` and tap's `throws` and
   `rejects` as `raises`, and `notThrows`, `snapshot`, `fail`, tap's `type`,
   `hasProp` and its forms, `matchOnly`, `matchStrict` and their negations,
   `resolves`, `resolveMatch`, `emits`, `error`, `matchSnapshot`,
   `resolveMatchSnapshot` and tap 16's `expectUncaughtException` as
   `unknown`. `t.pass()`, `t.plan(n)` and an assertion AVA skips
   (`t.is.skip(...)`) assert nothing.
2. **tap's `same` is loose for scalars** (`==`), and it reads as the
   structural equality, as Node's legacy `deepEqual` does. So
   `t.equal(x, 5)` -> `t.same(x, 5)` is not reported, as
   `assert.strictEqual(x, 5)` -> `assert.deepEqual(x, 5)` is not.
3. **Whose `t`.** A `t` is read where it is the first parameter of a
   callback passed to AVA's test function or to one of tap's declarers, and
   where it is tap's root `t`, inside a test unit. tap's root test is no
   unit: an assertion at a tap file's top level, outside every subtest, is a
   coverage notice, as a call outside a test unit is for every runner. An
   object named `t`, a `t` the file writes over, a `t` passed to a helper
   and tape's `t` are not read.
4. **tap's module exports by name what tap 16 or tap 21 exports.** tap 21's
   ES module exports some assertions (`ok`, `same`, `match`, ...) and not
   others; tap 16's exports `equal`, `strictSame`, `rejects` and a few more.
   A name one of them does not export throws on import under it, before any
   test runs, so reading the union hides nothing. A synonym or `hasProp` is
   `t`'s only. tap's CommonJS export is `t`, which has every method.
5. **The manifest counts AVA and tap among the runners**, as the decision
   says, so a root `package.json` that names Jest and AVA, or Mocha and
   tap, is now a mix and unknown, where it proved Jest or Mocha before.
   Continuity then falls back to the union of the Jest and node:test
   defaults, and focus to Jest's rule.
6. **AVA's `.only` stays in its file.** AVA runs each test file in a worker
   with a runner of its own (`lib/worker/base.js`), so its focus is read as
   Jest's and Vitest's is: added to a file whose units it turns off none of,
   it is not reported for the whole suite.
7. **tap 16's synonyms are read; older names are not.** tap 16 deprecated
   and tap 18 removed the synonyms its `lib/synonyms.js` defines
   (`t.deepEqual`, `t.equals`, `t.isDeeply`, `t.isa`, `t.true`, ..., and
   the all-lowercase and snake_case spelling of every camelCase name, 214
   in all). Each reads as the method it names, as tap 16 runs it; under tap
   18 or later a synonym throws, so reading one hides nothing. The sweep's
   tap histories use them (yargs's `t.deepEqual`, node-lru-cache's
   `t.similar` and `t.isa`). Not read: AVA's names before 1.0 (`t.ok`,
   `t.same`, `t.regexTest`), AVA's macro objects
   (`test.macro({exec(t) {}})`), tap's `t.skip(name, fn)`, `t.todo(...)`
   and `t.only(...)`, which declare no unit, so a subtest respelled
   `t.skip(...)` reads as removed, and a test whose callback is a function
   the file names rather than writes inline, as AVA's macro form
   `test(title, macro, ...args)` does: it lends the unit nothing, as a
   declared function lends no other runner's test anything (#320). A test
   that gets its runner through another module
   (`import test from './helpers/test.js'`) is not one of their test paths.

**Tests and fixtures.**
- **Tests:** 209 in `tests/test_issue233_ava_tap.py`. Fifty-four mutants of
  the round's code each fail them or the fixtures: an `ava` or `tap`
  import, require, default import or manifest entry not read; a modifier,
  a hook, the curried `skipIf` or a receiver path not followed; tap's
  named exports read as `t`'s methods, or read as tap 21's alone; a meaning
  or its polarity changed; the throw family, an unread method or a bound
  method's name not recorded; a member of a call's result read as `t`; a
  layout row or exclusion changed; AVA's rows or focus scope dropped; tap
  16's synonyms not looked up, their lowercase or snake_case spellings
  dropped, or an entry of the table lost; `resolveMatchSnapshot` or
  `expectUncaughtException` not recorded; a synonym on a `t` the file
  writes over not a coverage notice.
- **Fixtures** (12), each `_pos` passing on v0.6.0 with zero findings:
  - row 107: `js_ava_tests_dir_unit_deleted_pos` (A1);
  - row 126: `js_ava_tests_dir_weakened_pos` (A2), `js_ava_is_to_truthy_pos`
    (A3), `js_ava_expected_rewrite_pos`, `js_tap_tests_dir_weakened_pos`
    (T1), `js_tap_equal_to_ok_pos` (T2), `js_tap_assertion_deleted_pos` and
    `js_tap16_synonym_weakened_pos`;
  - controls with no finding on either:
    `js_tests_dir_helper_without_runner_neg` (a JS file under `tests/` that
    names neither runner),
    `js_ava_true_respelled_as_is_neg`, `js_tap_same_respelled_strict_neg`
    and `js_tap16_synonym_respelled_neg`.

Every existing fixture keeps its expectation, and `tools/emit_corpus.py`
gives the base's 805 records byte for byte and the 12 new ones. The chai
mutation inventory (`tests/data/javascript_chai_mutations.json`, 39
records) keeps every verdict.

**Fingerprints, messages and IR.** No corpus fingerprint moves. A coverage
diagnostic for an AVA or tap call names its family (`AVA assertion
candidate ...`, `tap assertion candidate ...`). The IR does not change
shape.

**Cost.** Measured on five JavaScript histories whose tests use AVA or
tap: got and execa (AVA), node-semver and node-lru-cache (tap), and yargs
(tap until 2014). The set is every non-merge commit whose JS or TS diff
adds or removes a line calling a method of a `t` (`t.<name>(`): 1,766
commits, 1,764 readable on both engines. The round's engine was run
against the base branch's (`c704a0c`). 311 records change and 40 verdicts
move, so blocked goes from 34 to 58: 32 commits start blocking and 8 stop.
- **The 8 that stop were false blocks.** A test respelled `test.serial(...)`
  read as one that disappeared (TEST_DISABLED high), because `serial` was
  no modifier the reader knew: execa `7bf6ac26`, `9435a34a`, `45475e7d`,
  `ff22803f`, `9a2b00f4`, `2ddec78c` and `f0715464`, and got `0863bcd5`.
- **True positives: 15 of the 32.** Each commit's diff shows the edit was
  meant:
  - four loosen a check: an IP that may now also be `::1` (got
    `8122d96e`), an error code that may be either of two (got
    `891dcbea`), an exit-code name replaced by `t.true(failed)` (execa
    `55337f79`), and a message cut to its first words (execa `5587ae1d`);
  - eight replace or delete a check: got `81fc00aa` (tests named for
    stripping a standard port now assert a non-standard one, and an
    `instanceof` check is gone), `48b817ee`, `464515f1` and `2bc2b90f`;
    execa `9a641b0c`, `e55dc8bd` and `0070738c`; and yargs `58798d8d`,
    whose finding says the expected value stayed the same when the
    expected object was rewritten too: a JS object or array is never
    compared as an expected value (filed as #323);
  - three rewrite an expected value with the behaviour or input it follows
    (execa `68986b79`, node-lru-cache `ac2a7f49`, yargs `50451226`).

  Each is reported for a reviewer, as the same edit spelled with
  node:assert or chai already was.
- **False positives: 16 of the 32, each a class of the existing reader.**
  The base engine blocks the node:assert or chai twin of each class the
  same way (probed one by one):
  - eight move checks into a function the test names as its callback, an
    AVA macro (execa `97c0a0bd`, `da7aec7a`, `81f0b2d4`, `282d1895`,
    `6cf1c5e7` and `14485c75`), or into a helper the test calls with its
    `t` (execa `c09bb188`, node-semver `cb71dbbd`). Filed as #320, and
    named in row 126's residuals;
  - two respell a `t.fail()` sentinel in `try`/`catch` as `t.throws(...)`
    (got `21c5c78d`, `39bf8282`);
  - one drops a `t.notThrows(...)` around a call the test awaits anyway
    (execa `1861b5eb`);
  - one moves a negation from the subject into the assertion,
    `t.truthy(!x)` -> `t.false(x)` (got `f5e227ed`; filed as #322);
  - one respells an expected string as a template literal (got
    `a03201fb`; filed as #321);
  - one splits a test in two, and destructuring makes the halves' subjects
    the same names (execa `f5172cde`);
  - one moves checks into nested subtests with their subjects respelled
    (node-semver `18c21b24`);
  - one migrates a file from tap to mocha and chai, renaming the tests and
    the subject's variable (yargs `d1f082c3`).
- **One mixed commit:** got `f7500d47` (tests rewritten with
  `async`/`await`) drops a real check, the synchronous throw of the
  callback API; the rest is a test split into five with one title and
  `t.throws` respelled as `t.fail` sentinels.
- **Two defects of the round, fixed before this measure.** A first run
  blocked node-semver `24af4615`, because tap's `t.resolveMatchSnapshot`
  was missing from the methods recorded with no strength, and yargs
  `1ed92b97`, whose tap 0.x `t.deepEqual` was not yet read (reading 7).
- **The other 271 records keep their verdict.** In 230 the round adds
  findings, among them 1,071 ASSERT_REMOVED, 424 TEST_DISABLED and 205
  ASSERT_WEAKENED at warn; every one is at warn or info except in five
  commits that block on both engines. The largest two:
  - execa `698a1b84` moves the suite from AVA to node:test. The base engine
    read only the node side; the round reads both, and holds its 507
    findings at warn.
  - got `0a79ccbe` renames its tests to `.ts` under an AVA configuration
    for TypeScript. AVA's default extensions are `js` and `mjs`, and a
    configured extension is not read, as configured globs are not, so 313
    tests read as leaving AVA's collection, at warn.

  In 25 records TEST_DISABLED findings at warn or info are dropped or
  change severity, and in 39 only a fingerprint or a message changes.
- **The Python sweep cannot move.** No commit of the thirteen sweep
  histories touches a JS/TS test file (D-106), and only such a file is
  read this way.

**Verdict gate.** Run as CI runs it (four engines, 156 T1 + 26 T3 cases)
on the round's engine: passed, 0 failures, 1 reported: `i198/T6`, which
passes on v0.6.0 and blocks here, as D-104 labels it. Every other case
keeps v0.6.0's verdict.

The agent wrote this entry in the fix PR; the maintainer approves it there.

## D-119 (2026-10-07): a multi-line pytest setting is read to its end (#324)

`pytest_collection.collection_settings` kept reading a value's
continuation lines only while each was indented and held no `=`. A TOML
array therefore stopped at its first element with `=`
(`"--import-mode=importlib"`, `"--ignore=docs"`), and only the words
before it were read, starting with `[`. An INI continuation that started
with `--cov-report=term` read as nothing. An array whose first element
sat on the opening line was never continued, and an INI value continued
only when its first line was empty. A selector added to such a value
(`-m "not slow"`) passed with CI_WORKFLOW_TOUCHED at warn, where the same
edit to a one-line value blocked (THREATMODEL row 42). The cut also
worked the other way: the same options respelled from a multi-line array
onto one line read as a selector introduced, and blocked. attrs'
`pyproject.toml` array (2025-09) and scrapy's (since 2024-11) were cut
this way, and starlette's `setup.cfg` continuation (2020) read as
nothing. Found by #173's sweep (D-114) and filed as #324.

No ruling was asked: the reader's own comment said it read INI
continuation lists and multi-line TOML arrays, and this is where it did
not. This entry, in the fix PR, is where the maintainer approves it.

**As implemented:**
- A TOML array runs to the line that closes it, counted by its brackets
  outside strings and comments, whatever its elements hold, and is read
  as one literal.
- A value that opens with neither a bracket nor a quote is an INI value.
  It continues over every indented line after it, as iniconfig continues
  it, whether its first line is empty or not. Blank and comment lines
  inside it are skipped, and do not end it.
- A line a value spans is not read again as a setting or a section.
- A quoted value is never continued, so an indented TOML key after a
  string stays a setting.

Readings left to the implementation:

1. **The kind of a value is read from its first line**, since one reader
   serves INI and TOML files alike: an opening bracket is a TOML array, a
   quote a TOML string, and anything else an INI value. In an INI file a
   quoted value is continued by iniconfig all the same, so the indented
   lines after `addopts = "-ra"` are still not read: filed as #327, to be
   read by the section the value sits in.
2. **An indented line that looks like a setting belongs to the value
   above it** in an INI file, as iniconfig reads it (`addopts =` /
   `    -ra` / `    testpaths = x` is one addopts value).

**Tests.** `tests/test_issue324_multiline_addopts.py` (20): #324's P2, P4
and I1, and an INI value continued after a first word, block, as its
controls P3 and I2 do; a value respelled on one line is no event; the
values pytest reads from attrs', scrapy's and starlette's configs; where
a value ends; and the bracket depth of an array line. #173's test of a
word that names no target keeps its expectation: the array it uses is now
read whole and still names no target. Four fixtures: three pins of row 42
(P2, P4 and I1) and one neg, a multi-line array respelled on one line,
which the old reader blocked.

**Cost.** The old and new readers' parse of every pytest config file,
at any depth and on either side, was compared on every commit of the
standard set (1,800), of D-088's sets (1,263) and of the 2,849 commits
that touch a config in 13 histories. It differs on 986: 108 of the
standard set (attrs), 269 of D-088's sets (scrapy 241, uvicorn 25,
attrs 2, starlette 1) and 609 of the config commits (scrapy 417,
aiohttp 108, uvicorn 54, attrs 26, starlette 4). No other commit can
change. #173's engine and this one judged all 986:
- 982 keep their records byte for byte, every one of the standard
  set's and D-088's sets' among them, and 140 block on both engines.
- 4 of aiohttp's config commits go from pass to an engine error.
  aiohttp vendors `vendor/llhttp` as a submodule, and the strict
  snapshot inventory rejects a tree that holds one. Their `addopts`
  edits (`-p pytest_cov`, `--cov`, `--showlocals`, the `-m`
  expression) are now read and change the collection settings, so the
  inventory is read. 49 of aiohttp's 108 already end in that error on
  #173's engine, and v0.6.0 gives it for a test edit in such a tree:
  filed as #335.

**Verdict gate.** Run as CI runs it (four engines, 156 T1 + 26 T3 cases):
passed, 0 failures, 1 reported: `i198/T6` is undecided (pass on both
engines), as on main, where #226's relabel (D-104) has not landed. Every
other case keeps v0.6.0's verdict.

The agent wrote this entry in the fix PR; the maintainer approves it there.

## D-121 (2026-10-07): a quoted pytest setting is read by its section (#327)

D-119 read a value's kind from its first line, since one reader serves INI
and TOML files alike, and a value that opened with a quote was a TOML
string, never continued. In an INI file the quote is part of the value:
iniconfig continues it over the indented lines after it, as it continues
any other, and pytest splits `addopts` with `shlex`, which drops the
quotes. A selector added beneath `addopts = "-ra"` in `setup.cfg`,
`pytest.ini` or `tox.ini` therefore ran (`['-ra', '-m', 'not slow']`) and
passed with CI_WORKFLOW_TOUCHED at warn, where the same selector on the
value's first line blocked (THREATMODEL row 42). The cut also worked the
other way: the same options respelled onto one line read as a selector
introduced, and blocked. Found while fixing #324 (D-119's reading 1) and
filed as #327.

No ruling was asked: the reader's own contract is to read the value pytest
reads, and #327's proposed fix is what D-119's reading 1 left open. This
entry, in the fix PR, is where the maintainer approves it.

**As implemented** (#327's proposal):
- `[tool:pytest]`, which only `setup.cfg` holds, is INI: a quoted value
  continues over its indented lines like any other, blank and comment
  lines skipped.
- `[tool.pytest.ini_options]`, which only `pyproject.toml` holds, is TOML:
  a string is never continued, so an indented key after it stays a
  setting.
- `[pytest]` is INI in `pytest.ini` and `tox.ini` but TOML in pytest 9's
  `pytest.toml`. A quoted value there continues over its indented lines up
  to a line that reads as a TOML setting: a bare key, which never starts
  with `-`, or a quoted key, then `=`. In an INI file such a line would
  hand pytest `name` and `=` as paths, and pytest stops with a usage
  error (exit 4), so ending the value there hides no passing weakening.

Reading left to the implementation:

1. **A line that reads as a TOML setting ends the value**, and is read as
   a setting of its own, rather than being skipped while the value goes on
   over the lines after it (the issue's "except a line"). In `pytest.toml`
   every line after a key belongs to that key or to the next one, never to
   the string above it.

**Tests.** `tests/test_issue327_quoted_ini_value.py` (20): #327's Q1 and
Q2, `tox.ini` beside them and the control Q3 block; a quoted value
respelled on one line is no event; the values pytest reads in each
section, a setting-shaped line inside an INI value among them; and the
lines that read as a TOML setting. #324's tests keep their expectations;
their docstring says the quote is now read by its section. Four fixtures:
two pins of row 42 (Q1 and Q2); one guard, an indented key after a string
in `pytest.toml` narrowed, which blocks on both engines and pins that the
string does not swallow it; and one neg, a quoted continuation respelled
on one line, which #324's reader blocked.

**Cost.** Every blob at a pytest configuration path (`pytest.ini`,
`.pytest.ini`, `pytest.toml`, `.pytest.toml`, `tox.ini`, `setup.cfg`,
`pyproject.toml`) on every ref of the thirteen sweep histories, 3,685
blobs, was read by #324's reader and by this one: each that mentions
pytest gives the same `collection_settings`, `collection_options` and
`resolved_collection_settings` on both, so no commit of those histories
can change its record. The same holds for every blob at any path in
those histories, 317,869 in all, that holds a pytest section header
(`[pytest]`, `[tool:pytest]` or `[tool.pytest.ini_options]`).

**Verdict gate.** Run as CI runs it (four engines, 156 T1 + 26 T3 cases):
passed, 0 failures, 1 reported: `i198/T6` is undecided (pass on both
engines), as on main, where #226's relabel (D-104) has not landed. Every
other case keeps v0.6.0's verdict.

The agent wrote this entry in the fix PR; the maintainer approves it there.

## D-122 (2026-10-07): stand-ins in JS setup files are reported (#218)

`jest.mock("./src/billing", () => ({ invoiceTotal: () => 78.75 }))` above
an untouched `expect(invoiceTotal(items)).toBe(78.75)` blocks when it is
written in the test file (row 109, #177). Written in a setup file, which
the runner loads before every test file, it passed with zero findings:
setup files have the production role, and the mock scan read only the
file that holds the assertion. So did `jest.enableAutomock()` there and
`"automock": true` in package.json. Row 109 listed this as a residual,
row 60's JS twin. Filed from #196 as #218.

**Ruling** (2026-10-06, the owner adopting the recommendations in one
reply, "全部核准"; #218's ruling comment): the carriers are
`setupTests.{js,ts}` (Create React App's `src/setupTests`), the files the
base side's root `package.json` names in `jest.setupFiles` /
`jest.setupFilesAfterEnv`, `jest.setup.*` and `vitest.setup.*`;
`jest.config.*` and `vitest.config.*` stay residual. A first-party
`jest.mock` / `vi.mock` / replacing spy in a carrier (S1-S3),
`jest.enableAutomock()` in a carrier (S6) and `"automock": true` in
`package.json` (S5) are stand-ins; a rewritten manual mock under
`__mocks__/` (S4) stays a known limitation. They are reported under
TEST_PATCHES_SUBJECT, with no new rule ID. S7 (`automock` in
`jest.config.js`) stays residual; S8, the opaque exemption an edited
`jest.config.js` buys, waits for its own ruling.

**As implemented** (`frontends/javascript/setup_files.py`):
- A carrier is read by the scan a test file goes through
  (`module_mocks._Side`), so first-party means what it means in row 109:
  `./` and `../` inside the repository, `@/` and `~/`, and the base side's
  root tsconfig.json `paths`. A third-party or builtin mock is hygiene.
- Judged like CONFTEST_PATCHES_PROD: an installation is the event when
  no base-side carrier in the diff installed it, and which test reads it
  is not resolved. It is reported as TEST_PATCHES_SUBJECT with no unit,
  so, as for every finding with no unit, only an opaque production
  change is repair evidence. The message names the setup file and what
  it replaces.
- A mock moved between carriers, reformatted, or in a renamed carrier is
  not new; a carrier the diff adds is new in full, as is a helper renamed
  into one.
- `automock` in the root package.json is compared with the base side's.
- The event rides in `subject_installations` with no unit, so no IR field
  is added and IR_VERSION stays 2 (D-067).

Readings left to the implementation:

1. **A partial mock is covered by any base-side mock of its module.**
   Which exports a partial factory replaces is read only as every name
   it spells, and that set moves with any edit to the factory's body
   (excalidraw `51ea1849`: `super.getContent()` ->
   `super.getContent(new Set())`, which read as a new stand-in). So an
   existing partial mock widened to replace another export is not new, a
   residual; a partial mock turned into a whole-module mock is new, and
   a member spy covers only its member.
2. **A listed setup file is spelled `./x` or `<rootDir>/x`**, and
   resolved as Jest resolves it, extension-insensitive
   (`<rootDir>/test/setup` is `test/setup.js`); any other entry names a
   package. Only the base side's listing counts, as ruled, so a setup
   file under another name that only the head side lists stays residual.
3. **`automock` is on only when it is `true`.** A string or a number is a
   configuration error Jest reports, not a stand-in.

**Tests.** `tests/test_issue218_setup_file_standins.py` (69): the issue's
rows S0c-S7; a replacing spy in a file listed in `setupFilesAfterEnv`;
partial factories, aliases and hygiene; what is new against the base
side (moved, reformatted, renamed, widened, a helper renamed into a
carrier, automock already on or turned off); the carriers by name and by
listing; and a diff without a carrier, which reads no manifest. Eleven
fixtures: seven pins of row 109 (S1, S1b, S2, S3, S5, S6 and the listed
spy), each passing with zero findings on v0.6.0 and #326's engine, and
four controls (a third-party mock, a jest-dom import, a mock moved
between carriers and reformatted, and S7).

**Cost.** In the 21 histories the sweeps read (8 JS, 13 Python), no
commit touches a carrier, and no root `package.json` blob sets `automock`
or lists setup files, so no record of the standard set, of D-088's sets
or of the JS histories can change. Two JS projects with setup files were
cloned for this measure, and the channel was run on every commit that
touches a carrier or the root `package.json`:
- excalidraw (4,118 commits; 613 such commits, 24 touching
  `setupTests.ts`): 3 are flagged, each adding a partial `vi.mock` of a
  first-party module to `setupTests.ts` (font loading,
  `@excalidraw/common`). Each is an honest global stand-in, the event the
  ruling names. The full engine reports each at warn, since each diff
  also changes production it cannot read, so no verdict moves. Before
  reading 1, two more commits that edited an existing partial factory's
  body were flagged; with it, neither is.
- mastodon (22,536 commits; 1,826 such commits, 3 touching
  `app/javascript/mastodon/test_setup.js`, which its `package.json`
  listed in `jest.setupFiles`): none is flagged.

A new global mock with no unreadable production change beside it would
block at high, as a new conftest patch does.

**Verdict gate.** Run as CI runs it (four engines, 156 T1 + 26 T3 cases)
on the round's engine: passed, 0 failures, 1 reported: `i198/T6`, which
passes on v0.6.0 and blocks here, as D-104 labels it. Every other case
keeps v0.6.0's verdict.

The agent wrote this entry in the fix PR; the maintainer approves it there.

## D-123 (2026-10-07): a git submodule is a directory whose content is unknown (#335)

In range mode, every pass that read the path inventory raised "strict
snapshot inventory cannot inspect a submodule". A repository whose tree
holds a gitlink got an engine error (exit 2) for nearly any change to a
Python test or to pytest's settings: a rewritten expected value was not
blocked, and an added test was not passed. Found during #324's sweep
(aiohttp vendors `vendor/http-parser`, later `vendor/llhttp`; flask held
`docs/_themes`). The owner adopted the issue's proposed ruling on
2026-10-07: a submodule is a directory whose content is unknown, a pass
that needs a fact from inside one fails closed naming its path, and every
other pass proceeds over the rest of the tree.

**As implemented:**
- **The inventory.** `GitSnapshot.list_paths` lists a gitlink as its path
  with a trailing slash (`vendor/lib/`), and `split_inventory` sets it
  apart. A consumer that does not split it reads it as an unsafe path and
  fails, as every inventory read failed before. A read inside a submodule
  raises "strict snapshot cannot inspect the submodule vendor/lib:
  vendor/lib/calc.py lies inside it".
- **Imports.** The runtime-provider pass's import walk fails closed where
  a location at or under a submodule could decide the import: ahead of the
  first regular package on the path, or on a package path that
  `pkgutil.extend_path` extends, once the walk gets that far.
- **Collection.** `opaque_reached` reads, on each side of the diff, whether
  a pytest run could collect from a submodule. Four passes ask before they
  rely on the tree's tests: the collection-inventory comparison, the
  runtime-provider pass, the stand-in installation pass (for a submodule
  beneath a changed conftest) and the root assertion-helper importer
  search.
- **Unchanged:** the empty-needle search still rejects a tree with a
  submodule, because the startup-context proof needs every Python source;
  that proof stays withheld there, as before.

**Readings flagged for approval:**
1. **What reaches.** The runs are the runner files' pytest commands on
   each side, `tox.ini`'s included, or the bare `pytest` a tree without one
   implies. A run reaches a submodule when a path argument names it, a path
   inside it or a directory above it; a run without one collects from the
   root config's `testpaths`, else from the root, into every directory no
   `norecursedirs` pattern stops. A setting read two ways counts both ways.
   An undecodable config or a run's own `-c` config reaches every
   submodule, and a runner file whose pytest command does not parse is a
   run without path arguments. A path argument that expands a variable
   (`$1`, `{posargs}`) names no path, as the ruling's "a path argument
   naming it" reads. Not read: `-o` overrides, `addopts` path arguments,
   and `--ignore`, which can only keep a run out. An option's value the
   parser reads as a path argument (`pytest -n 4`) is #343.
2. **A pointer move.** A diff that moves a submodule's pointer changes code
   checkwash does not read, and is judged as any such change: it passes.
3. **The head's inventory.** The inventory is the head side's. A submodule
   only the base holds is not listed, so a diff that removes one is not
   checked for what a collection reached in it.
4. **Worktree mode reads what is checked out.** A checked-out submodule's
   files are read as part of the tree, as before.
5. **A test of a submodule's code.** A test that imports from a submodule
   is judged as usual where no pass needs a fact from inside it: its own
   oracle is compared. A pass that needs one, such as an expected value
   defined there or a stand-in installed on a module object from there,
   fails closed.

**Measured cost**, with the round's engine against `main` at `5f5ec46`
(the same engine bytes as the sweeps' copies):
- **Standard set** (the last 300 non-merge commits of attrs, click,
  flask, httpx, rich and starlette: 1,800 commits, all readable) and
  **D-088's sets** (895 commits of ten full histories; 368 of pytest's,
  364 readable): every record is `main`'s, byte for byte, but those of
  D-088's 28 flask commits whose tree holds `docs/_themes`. Each exited 2
  on `main`; 11 now block, 14 pass and 3 exit 2, naming the submodule.
  The ten histories' readable commits go from 855 to 880.
- **The config commits that hold a submodule:** of the 2,849 commits that
  touch a pytest config in 13 histories (#324's list), flask's 45 and
  aiohttp's 142 whose tree holds one, with D-088's 28 for flask (72
  commits, one in both):
  - flask: on `main` 49 exited 2 and 23 passed; now 18 block, 48 pass
    and 6 exit 2;
  - aiohttp: on `main` 76 exited 2 and 66 passed; now 12 block, 123 pass
    and 7 exit 2.
- **Against the same engine with the gitlinks dropped from the
  inventory** (the tree read as if it held none), each of those 214
  records is the same, byte for byte, but the 7 where a run reaches a
  submodule, which exit 2 naming it:
  - flask's 6 reach `docs/_themes` from the root. Four (2012 to 2014)
    have no pytest config, and a runner file whose test command has no
    path argument: a bare `py.test`, or `python run-tests.py`, which
    checkwash does not parse as a pytest run. In two (2016) the
    `norecursedirs = ... docs` that would keep it out sits in a
    `[pytest]` section of `setup.cfg`, which checkwash, like current
    pytest, does not read;
  - aiohttp's `3e2fe7937e` adds a Makefile run with its own config,
    `pytest -c pytest.ci.ini`.
  aiohttp's 6 other exits are the same with the gitlinks dropped: 5 hit
  the stand-in node limit (#345) and 1 a symlinked nested config (#346).
- **So each new block is the engine's verdict on the same commit with
  the gitlinks dropped.** The 30 (flask 18, aiohttp 12), from 2012 to
  2026, are test refactors, test-config edits and workflow edits; their
  high findings are TEST_DISABLED (13 commits), CI_WORKFLOW_TOUCHED (8),
  ASSERT_REMOVED (4), EXPECTED_VALUE_CHANGED (3),
  EXPECTATION_DEFINITION_CHANGED (2), and ASSERT_WEAKENED,
  CONFTEST_PATCHES_PROD and SUBJECT_NORMALIZED (1 each).
- **The corpus is byte for byte the same**: no fixture holds a gitlink.

The agent wrote this entry; the maintainer approves it in the round's PR.

## D-124 (2026-10-07): a skip a test reaches through a helper it imports is read (#272, second stage)

D-111 read a skip a test reaches through a same-file helper. A test that
imported the helper instead, `from tests.helpers import offline`, and called
`offline()` was skipped as surely, and passed with zero findings (#272's
H5): an imported helper was not followed.

Ruling 272.Q2 (a), adopted by the owner on 2026-10-06 ("全部核准"): follow
the import into the head tree, as #223 follows the conftest chain, as a
second stage after the same-file reading. 272.Q3's marker applies:
`helper.<function>.<effect>`.

**As implemented:**
- `frontends/python/helper_skips.py`: `imported_helper_names` reads the
  names a test module's top-level `from M import f` binds, the imports
  `_top_level_from_imports` reads for an imported assertion helper
  (absolute, and same-directory package-relative). `HelperOutcomes` takes
  them (`ImportedHelpers`): a call by such a plain name, in the test, in its
  setup or in a same-file helper on the way, runs the imported function,
  unless the calling scope binds the name itself. `HelperModule` reads the
  module for what calling each of its functions ends in, with the module's
  own names, branch constants and same-file helpers, as a test module's are
  read.
- `engine.py`: the module is the one an imported assertion helper resolves
  to (`_merge_crossfile_oracles`): a dotted module's path from the
  repository root, a dotless one's beside the test. It is read as the
  conftest chain is (`_helper_module`): a file the diff changes on its own
  side, any other once from the strict head snapshot, within the chain's
  read limits, past which the run is an engine error. Only a test or
  conftest module is read. Each side of a test module the diff changes
  reaches it, and so does a D10 survivor (D-108).
- `frontend.py`: the marker keeps the helper file's text and span, and
  `marker_origins` names that file, so a report locates the finding at the
  helper's skip, as it locates a conftest fixture's (#223).

Readings the ruling leaves to the implementation:

1. **Only an outcome every call reaches.** As a conftest fixture's outcome
   is (D-093 reading 5), a guarded skip in an imported helper records
   nothing: its guard is written in another module's names, which
   COMPAT_GATE would read in the test module's. The conditions at the call
   site still guard the marker, as in D-111, so a call under a platform
   condition holds at warn.
2. **One hop.** What the imported module imports in turn is not followed;
   its own same-file helpers are.
3. **The module an imported assertion helper resolves to, and only a test
   or conftest module.** A helper in a package's `__init__.py`
   (`from tests import requires_db`), a module found through another
   `sys.path` entry, a deeper relative import and a production module are
   not followed.
4. **A name bound once.** A name another top-level statement binds as well
   is not followed, since which binding a call sees depends on order; nor
   is any name once a top-level star import may rebind it. An attribute
   call (`helpers.offline()`) is no call by a plain name.
5. **D10's survivors read their imported helpers too**, as they read their
   conftest chain (D-108): a survivor whose setup calls an imported helper
   that always skips is not live.

**Tests and fixtures.**
- **Tests:** 34 in `tests/test_issue272_imported_helper_skips.py`. Each
  of the 20 mutants of the round's code fails them or the round's
  fixtures.
- **Fixtures** (row 125):
  - `helper_skip_imported_module_pos` (H5) and
    `helper_skip_imported_relative_pos` (a package-relative import whose
    module raises the skip in its own helper), each passing with zero
    findings on v0.6.0 and on `main`;
  - `helper_skip_imported_platform_gate_neg`: a call under a platform
    condition holds at warn (COMPAT_GATE);
  - `helper_skip_imported_already_called_neg`: a skip the base already
    reached is no event.

**Cost.** Measured with the round's engine against main's (`b2e0eb5`):
- **Targeted set:** every non-merge commit of the thirteen sweep histories
  (62,800 commits), searched for a test module the commit changes that, on
  either side, calls by a plain name a function a top-level
  `from M import f` binds, where M resolves, as the round's engine
  resolves it, to a test or conftest module in which calling `f` ends in
  an outcome every call reaches. No commit does, so the new reading
  changes no record there. The same search finds H5 in a synthetic
  history.
- **Standard set** (the last 300 non-merge commits of attrs, click,
  flask, httpx, rich and starlette: 1,800 commits): main's verdicts and
  finding fingerprints for every record (48 blocked, no engine error).
- **D-088's sets** (895 commits of ten full histories; 368 of pytest's):
  main's verdicts and finding fingerprints for every record (247 and 95
  blocked). The 15 and 4 engine errors are the same read limits on both
  sides.
- **Speed:** the perf gate's cases, timed in the cloud container with
  the sweeps paused: 500 changed files take 2.25 s (median of nine runs),
  main's 2.32 s; the 3,000-line diff takes 0.61 to 0.72 s, main's 0.59 to
  0.62 s. Reading each test module's top-level imports costs about 16 ms
  of the 500-file case.

**Verdict gate.** Run as CI runs it (four engines, 156 T1 + 26 T3 cases):
passed, 0 failures, 1 reported: `i198/T6` (pass -> block), as on main.
No case changes its verdict.

The agent wrote this entry in the fix PR; the maintainer approves it there.

## D-125 (2026-10-07): what a stand-in names outside its own call is read one hop (#196 188.5)

THREATMODEL rows 109 and 90 left two shapes as residuals:

- **JS: names a partial factory merges in from outside.** A partial
  `vi.mock` factory that spread a `vi.hoisted` object,
  `({ ...(await importOriginal()), ...mocks })`, replaced `invoiceTotal` in
  silence. The factory spells `mocks`, not `invoiceTotal`.
- **Python: targets built at runtime.** `mocker.patch(TARGET)` with
  `TARGET = "app.billing.invoice_total"` was no patch at all.

v0.6.0 and `main` pass every such shape with zero findings.

Ruling 196.188.5, adopted by the owner on 2026-10-06 ("全部核准"): choose A
now, and make C the closing round. C reads names one hop through
`vi.hoisted` or a mock-prefixed object literal, and treats only what stays
unreadable as opaque. Python's targets built at runtime are handled in the
same family.

**As implemented:**
- **JS** (`module_mocks._Side._factory_names`). A partial factory builds on
  the real module. It may replace every name it spells, as before, and now
  also every name carried by an object it merges in:
  - a spread in its own body's object literals;
  - an `Object.assign` argument;
  - a name it returns.

  The real module adds no name: the call itself, a name bound to it, or what
  is left of it after destructuring. An object written in the factory adds
  none either, since its names are spelled there.

  A name bound outside the factory is read one hop, as `vi.hoisted(...)`
  whose callback returns an object literal, or as an object literal. What
  stays unreadable makes the factory opaque, which is a whole-module mock.
- **Python** (`frontend._patch_call_target`, `detectors/test_patches.py`). A
  target built at runtime is read one hop, and only from a patcher:
  - the patchers: `patch`, `mock.patch`, `unittest.mock.patch`,
    `mocker.patch` and the other pytest-mock fixtures, `monkeypatch.setattr`
    and `setitem` (or `mp.`), and `patch.object`;
  - what is read: a name bound once to a string literal, in the test or
    else in the module; `__name__`; and an f-string or `+` of those.

  A target that stays unreadable is opaque, and its attribute is `*`. An
  opaque attribute of a known object counts as reached when the assertions
  reach that object. A target of which nothing is known counts as reached
  when the assertions reach anything.

Readings the ruling leaves to the implementation:

1. **Any object literal, whatever its name.** The ruling names a
   mock-prefixed object literal, because Jest's `mock` prefix is what lets a
   hoisted `jest.mock` factory reach a variable at all. A literal bound to
   any other name is read too:
   - `doMock` and `unstable_mockModule` are not hoisted, and reach any
     variable;
   - under a hoisted mock, an unprefixed reference fails before any test
     runs.
2. **Only the factory's own body merges.** None of these merges anything
   into the module:
   - a spread inside a function nested in the factory
     (`wrap: (o) => ({ ...o })`), or a value such a function returns;
   - a rest parameter;
   - an array or call spread;
   - a destructuring rest.

   A method or an arrow behind a TypeScript return annotation
   (`fetch(url: URL): Promise<ArrayBuffer> { ... }`) is nested too. The
   bindings keep it out of their function scopes, so the round finds its
   body itself; the targeted set found the shape in excalidraw.
3. **Opaque is a whole-module mock.** An unreadable source may carry any
   name, so the factory may replace every export. A setup file's opaque
   factory is reported for its whole module.
4. **Python reads a computed target only from a patcher.** A literal
   `"pkg.mod.attr"` is read from any `.patch(...)`, as before. A computed
   one there is as likely `client.patch(url)`, an HTTP request.
5. **`__name__` is the test module.** A target built from it replaces the
   test's own code, so no patch is recorded. attrs does this with
   `f"{__name__}.A"` in `tests/test_slots.py`.
6. **One hop.** These are not resolved, and each is opaque, so it fails
   toward flagging:
   - a loop variable;
   - a parameter;
   - a name bound twice, or bound to an f-string;
   - a helper call.

   Residual: a computed target through `monkeypatch.context()`'s receiver
   (`m.setattr(TARGET, v)`), which names no patcher.
7. **A target provably no string installs nothing.** A patcher given one
   raises TypeError instead, so no patch is recorded. That covers a
   constant that is no string, and a name bound once to a def, a class or
   an imported module (`import x`), in the test or else the module.
   pytest's own `monkeypatch.setattr(A, "y")` under
   `pytest.raises(TypeError)` is the case (b4f046b777). Two bindings stay
   unreadable, since each may hold a string:
   - `from m import x`, which may bind a string constant;
   - a parameter, even one named like a module-level function, since a
     fixture's parameter holds what the fixture returns.

**Tests and fixtures.**
- **Tests:** 72 in `tests/test_issue196_188_5_merged_sources.py`. Each of
  the 42 mutants of the round's code fails them or the round's fixtures.
- **Row 109 fixtures:**
  - `js_test_patches_subject_hoisted_spread_pos`;
  - `js_test_patches_subject_mock_prefixed_spread_pos`;
  - `js_test_patches_subject_opaque_spread_pos`;
  - control: `js_test_patches_subject_hoisted_spread_other_export_neg`.
- **Row 90 fixtures:**
  - `test_patches_subject_runtime_constant_pos`;
  - `test_patches_subject_runtime_fstring_pos`;
  - `test_patches_subject_runtime_opaque_pos`;
  - controls: `test_patches_subject_runtime_own_module_neg` and
    `test_patches_subject_http_client_patch_neg`.
- Each `_pos` fixture passes with zero findings on v0.6.0 and on `main`.
- No existing fixture changes its expectation.

**Fingerprints.** Every finding is new except one. A new opaque partial
factory in a setup file is named for its module (`src/billing`), where
`main` named it `part of src/billing`.

**Cost.** Measured with the round's engine against main's (`23cf967`):
- **Targeted sets:** every non-merge commit of the 23 sweep histories that
  changes a file holding what the round reads, on either side.
  - **Python** (13 histories, 62,800 commits): a test or conftest module
    that calls a patcher with a target that is no string literal. 350
    commits: aiohttp 78, attrs 14, pytest 256, werkzeug 2. All 350
    records are main's: 288 pass, 38 blocked, and 24 unjudged on both
    sides (23 engine errors at the same read limits, and pytest's root
    commit). The first run found one record that was not: pytest's
    `b4f046b777` adds `monkeypatch.setattr(A, "y")` under
    `pytest.raises(TypeError)` to `test_setattr`, where `A` is a class
    the test defines. It read as an opaque patch, a new warn. Reading 7
    fixed that.
  - **JS** (10 histories, 36,707 commits): a JS or TS file that spells a
    module mock and a spread, `Object.assign` or the real module. 84
    commits, all in excalidraw (mastodon, a blobless clone, was read on
    its 58 test-like paths). All 84 records are main's (82 pass, 2
    blocked). The first run found two that were not, both excalidraw's
    `setupTests.ts` (`62228e0bbb`, `b479f3bd65`). It spreads the real
    module beside a class whose method carries a TypeScript return
    annotation (`getContent(): Promise<string>`), and that method's
    `return` read as the factory's. The factory was therefore opaque, and
    its warn named the whole font module instead of part of it. Reading
    2's annotated bodies fixed that, so the two records are main's again.
- **Standard set** (the last 300 non-merge commits of attrs, click,
  flask, httpx, rich and starlette: 1,800 commits): main's verdicts and
  finding fingerprints for every record (48 blocked, no engine error).
- **D-088's sets** (895 commits of ten full histories; 368 of pytest's):
  main's verdicts and finding fingerprints for every record (247 and 95
  blocked). The 15 and 4 engine errors are the same read limits on both
  sides.
- The standard set and D-088's sets ran on the round's engine before
  readings 2 (annotated bodies) and 7 (no string) were added. Neither can
  change a record there:
  - reading 2 is in the JS frontend alone;
  - reading 7 only drops patches from calls the Python targeted set
    covers, which is every commit of these histories whose changed tests
    hold such a call, and its final run is main's.
- **Speed:** the perf gate's cases, timed in the cloud container with the
  sweeps paused: 500 changed files take 2.27 s (median of nine runs),
  main's 2.26 s; the 3,000-line diff takes 0.61 and 0.64 s, main's 0.72
  and 0.64 s.

**Verdict gate.** Run as CI runs it (four engines, 156 T1 + 26 T3 cases):
passed, 0 failures, 1 reported: `i198/T6` (pass -> block), as on main.
No case changes its verdict.

The agent wrote this entry in the fix PR, as the rulings' X.doc-batch asks;
the maintainer approves it there.

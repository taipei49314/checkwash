# Threat model

greenwash is a **deterministic tripwire that raises the cost of cheating**.
It is not a guarantee, and it never claims "no cheating" — report wording is
fixed at "no known tampering pattern detected".

## Attacker model

The head side of the diff — including the entire working tree in hook mode —
is attacker-controlled. The attacker is a coding agent (or a human) trying to
make CI green without doing the requested work.

## What greenwash catches (v0.1)

Oracle-layer attacks visible in the diff: deleted/weakened assertions,
self-comparisons that can never fail, tests disabled by any of the pytest
idioms (function/class/module markers, `self.skipTest`, conftest collection
hooks), tests removed from collection by renaming the file or the class,
assertions parked behind an early `return`, deleted parametrize rows.
(M1:) loosened tolerances, rewritten snapshots, hardcoded expectations, broad
exception swallowing, suppression comments, CI/guardrail self-relaxation,
hallucinated imports, scope drift, hidden Unicode.

## What greenwash cannot catch — known and accepted

1. **Honest-looking dishonesty.** An agent that rewrites production logic so
   a bad test passes "honestly" is, at the diff layer, in principle
   undecidable. This is the fundamental limit of the approach.
2. **Out-of-band tampering.** An agent with shell access can edit
   `.git/greenwash/` state, remove the hook, or bypass the CLI entirely.
   Pair with CI-side checks (base-side config, required checks) for that.
3. **Curation gaps.** Custom assertion helpers, hamcrest-style matchers, and
   indirect assertions via fixtures are invisible until curated. Coverage is
   measured and reported, not assumed.
4. **Opaque prod changes (v0.1).** Repair evidence is computed from Python
   ASTs. A changed prod file greenwash cannot analyse counts as evidence and
   therefore *suppresses* the E1 escalation; an agent can exploit this by
   touching one such file. The blanket has been narrowed twice: touching an
   unrelated *Python* prod file stopped working when evidence went
   symbol-level, and as of v0.1.6 the exemption is no longer granted by
   deleted-but-parseable Python files (their symbols are read from the base
   side and judged like any other change), by type stubs, or by docs-site
   config, dependency-pin sources and repo metadata (the explicit inert list
   in `engine.py`; nested `pyproject.toml` and `requirements*.in` moved to
   the ci/lockfile roles). What still grants it — deliberately — is a change
   greenwash genuinely cannot read: code in another language, templates,
   runtime data files, and Python that does not parse. Narrowed further when
   the JS/TS frontend lands (v0.2).
5. **Indirection beyond one hop.** Repair evidence follows the call graph one
   hop from the test. A change three layers down, with no closer signal, is
   treated as unrelated (fails safe toward flagging, not toward silence).
6. **A skip condition greenwash cannot evaluate.** D6 refuses the
   compatibility-gate credit only when the condition is provably true —
   truthy — in every supported environment *and* under every assignment to
   the parts it cannot see. Module constants are no longer among the unseen
   parts: `skipif(WIN)`, non-strict `xfail(PY_3_14_PLUS)` and if-guarded
   imperative skips are evaluated with the constant resolved from the test
   file, from a file in the same diff, or from the head snapshot, and a
   constant that resolves to something always-truthy earns nothing (rows
   52–53). What remains unresolvable — helper calls, relative or
   whole-module imports, chains crossing more than one module — still
   defaults toward granting when a compat token is present:
   `skipif(check("sys.platform"))` earns the credit today, in a marker and
   in an `if` guard alike. Tightening to "any unknown means no credit" was
   tried and rejected: it blocked three honest compatibility skips in the
   corpus, and real gates routinely reference helpers. The finding stays
   visible at `warn` either way.
7. **Equivalent rewrites of an assertion.** When both the subject and the
   strength of an assertion change at once — a private-API check rewritten
   against the public API, say — greenwash cannot verify the replacement is
   equivalent and blocks. Accepted deliberately: the deescalator that would
   excuse it would also excuse replacing an exact comparison with a wide
   `approx()`, which was the most popular cheat in the decoy run. This limit
   is now *measured*, not just asserted: three candidate de-escalators for
   the residual false positives were each killed at design time by a
   spec-correct commit of the identical syntactic shape (the pairings are in
   benchmarks/README, "The floor"). On the 1800-commit corpus this design's
   adjudicated false-positive floor is ~1.17% — by the majority of three
   raters (Fleiss' kappa 0.844), and machine-checked against the
   adjudication file by `tests/test_state_claims.py`.

## Known bypasses (public list — contributions welcome)

Maintained here on purpose: every bypass reported becomes a regression
fixture. See CONTRIBUTING ("Send us a cheat") once published.

**How much this column is worth.** "Closed" used to be nothing but the author's
word. It has been wrong twice: row 10 sat here marked Closed while one
non-ASCII character on the line reopened it, and a claim that the GitHub Action
was dogfooded shipped while the CI job that would have proved it had never once
executed. So the column is now checked: each row names the fixture that pins
it (`bypass:` in the fixture's meta block), and `tests/test_threatmodel_pinned.py`
fails if any Closed row has nothing behind it.

That gate cannot prove a bypass is *closed* — row 10 had a fixture and the
fixture was simply too narrow. It only makes "Closed with nothing behind it"
unshippable, and makes the mapping visible so you can attack the fixture
instead of trusting the table. Building it turned up seven rows (13, 14, 17, 20,
21, 25, 36) that had been marked Closed for days with no test pinning them at
all. All of them still held when a fixture was finally written — but nobody
knew that until it was.

| # | Bypass | Status |
|---|---|---|
| 1 | Rewrite prod logic so the weak test passes honestly | Out of scope (documented limit) |
| 2 | Touch a non-Python / unparseable prod file to defuse E1 | **Narrowed** (v0.1.6, again v0.1.8) — docs config, stubs, repo metadata, pin sources, deleted-but-parseable Python and now any script that runs the test suite no longer qualify; other-language code, templates, data files, unparseable Python and scripts that do something else still do, until the JS/TS frontend. Row 68 |
| 3 | Remove the hook / run outside greenwash | Out of scope; use CI required checks |
| 4 | Add a dead constant, reorder defs, or edit an unrelated function to defuse E1 | **Closed** — evidence is symbol-relevant, not diff-global |
| 5 | `git mv` / plain `mv` a test file out of collection | **Closed** in both range and worktree mode |
| 6 | Rename the test class out of pytest's `Test*` rule | **Closed** |
| 7 | conftest hook that skips the whole suite | **Closed** (curated control list) |
| 8 | Early `return`, deleted parametrize rows | **Closed** |
| 9 | Sacrificial `@pytest.mark.skip` test absorbing deleted assertions via D2 | **Closed** — disabled units are not "live" |
| 10 | `assert f(x) == f(x)` self-comparison | **Closed** (TAUTOLOGY) |
| 11 | Pass `BASE...HEAD` so base-branch commits defuse E1 | **Closed** (merge-base resolved) |
| 12 | Leave a build artifact (`.pyc`, `dist/`, …) in the diff to grant repair evidence | **Closed** — artifacts are dropped before analysis |
| 13 | Replace an exact comparison with a wide `pytest.approx(...)` | **Closed** — landing on APPROX is never "mild" |
| 14 | Wrap both sides in `sorted()` to make an ordered check order-blind | **Closed** — a changed subject is not a style change |
| 15 | Rewrite the expected literal to whatever the buggy code returns | **Closed** — `EXPECTED_VALUE_CHANGED` |
| 16 | Swallow the assertion in a broad `try/except` inside the test | **Closed** — oracle rule in test files |

| 17 | Put the test under a directory named `mybuild/` so artifact filtering drops it | **Closed** — segment-anchored matching |
| 18 | Edit `TASK.md` in the same diff to drop `oracle_freeze` or widen scope | **Closed** — contract read base-side |
| 19 | `skipif(sys.version_info >= (3, 0))` as a fake compat gate | **Closed** |
| 20 | Add `assert str(1) == "1"` as padding to fake compensation for deleted oracles | **Closed** — vacuous assertions do not count |
| 21 | Widen a *positional* tolerance: `approx(9.0, 0.001)` → `approx(9.0, 1e6)` | **Closed** |
| 22 | `except AssertionError: pass` around the assertion | **Closed** |

Bypasses 12–16 were found by running real coding agents against decoy
bug-fix tasks (`benchmarks/decoy/`), not by inspection. Bypass 12 in
particular made the tool catch **0 of 12** real tampering diffs.

| 23 | Rewrite an expected value while touching an *unrelated* file in an imported package to earn PACKAGE_REPAIR | **Closed** — credit needs a *modified existing symbol*, not any file change |
| 24 | `assert f(x) == f(x) + 0` — self-comparison behind an identity op | **Closed** — identity ops stripped before the check |
| 25 | Pad a faked compensation with `assert str(1) == "1"` (vacuous) | **Closed** — triviality recognised (and, conversely, a local named `sum` is *not* mistaken for the builtin) |

| 26 | `git mv AGENTS.md docs/AGENTS.old` — escape the guardrail role by renaming | **Closed** — leaving a supervised role is itself the event |
| 27 | Move a workflow out of `.github/workflows/` | **Closed** — same rule; removal escalates like a weakened command |
| 28 | Move an assertion into a never-called nested `def` (or `lambda`) | **Closed** — nested scopes do not execute |
| 29 | Park an assertion under `if False:` | **Closed** — constant-condition branches are unreachable |
| 30 | `skipif(False)` → `skipif(True)` | **Closed** — a marker's identity includes its condition |
| 31 | Module-level `pytest.skip(..., allow_module_level=True)` / `importorskip` | **Closed** |
| 32 | `import pytest as p` then `@p.mark.skip` | **Closed** — markers matched on trailing components, not the literal string |
| 33 | `== 42` → `!= 42` (also `is`/`is not`, `in`/`not in`, `assertTrue`/`assertFalse`) | **Closed** — polarity is part of the assertion |
| 34 | Delete the same assertion twice, re-add one copy — both excused as "moved" | **Closed** — the moved set is a multiset again, each credit spent once |
| 35 | Change `module_a.calculate` to supply evidence for a test calling `module_b.calculate` | **Closed** — symbols are module-qualified and must be reachable from the test's imports |
| 36 | An unrelated `except AssertionError: pass` riding on a sibling test's repair evidence | **Closed** — file-scoped findings earn no unit's evidence |
| 37 | Widen `abs` while leaving `rel` alone | **Closed** — every tolerance compared independently |
| 38 | Put the expectation on the left: `assert 3 == calc()` | **Closed** — the literal side is the expectation, either way |
| 39 | Hand-edit an exemption past the 180-day cap | **Closed** — the cap is enforced on read, not only on write |

Bypasses 17–22 came from adversarially reviewing the M1 code after it
shipped. Bypasses 23–25 from reviewing the M3 code (the newest deescalators)
the same way. Every one was a defect in detector code written to catch
cheating — including PACKAGE_REPAIR, added in M1 to *fix* a false positive,
which reopened bypass #4 until this pass caught it.

Bypasses 26–39 were all found by one outside reader auditing the public
repository, in a single pass, after four rounds of the project's own
adversarial review had declared it done. That ratio is the most important
number in this file.

| # | Bypass | Status |
|---|---|---|
| 40 | `__test__ = False` at module or class scope de-collects everything | **Closed** — pytest's oldest collection switch is now modelled |
| 41 | `pytest.param(..., marks=pytest.mark.skip)` on every row: the row count never changes | **Closed** — a row counts only if it runs |
| 42 | Narrow `python_files` / `testpaths`, or add `addopts = -k ...`, in `pytest.ini` / `tox.ini` / `setup.cfg` / `pyproject.toml` | **Closed** — those files had no role at all; they are now test-runner config |
| 43 | `git mv tests/test_x.py build/test_x.py` (or `.attic/`, `dist/`, `htmlcov/`, any dot-dir) | **Closed** — collectability models `norecursedirs`, not just the filename |
| 44 | Any always-true `skipif` outside seven hardcoded spellings — `skipif(True or sys.platform == "win32")`, `skipif(sys.version_info >= (3, 8))`, `skipif(os.name != "java")` | **Closed** — the condition is evaluated over an environment matrix; unverifiable conditions earn nothing |
| 45 | Delete 5 tests / 7 exact assertions, add 1 weak test with a similar name | **Closed** — SPLIT_OR_RENAMED now requires arriving oracle mass to cover what was lost |
| 46 | `assert "" in str(x)` / `assert len(x) >= 0` as compensation padding | **Closed** — unfalsifiable shapes are TAUTOLOGY, not oracles |
| 47 | One non-ASCII character on the assertion line, reopening #10 | **Closed** — `ast` col_offset is a UTF-8 byte offset and is now translated to characters |
| 48 | `if not True:` / `if 1 == 2:` / `if False and x:` / `for _ in []:` / an unmatchable `match` | **Closed** — branch conditions are constant-folded, not pattern-matched |
| 49 | `assert (cond, "message")` — the always-true tuple assert | **Closed** — TAUTOLOGY |
| 50 | `assertIs` → `assertIsNot` (the unittest spelling was never in the map) | **Closed** |
| 51 | Introduce syntax the analysing interpreter cannot parse; the file is skipped and the run passes | **Closed** — `TEST_FILE_UNPARSEABLE`, high when the file used to parse |

Bypasses 40–51 came from a second independent audit (2026-08-02), run as six
parallel lenses with a separate skeptic re-running every repro from an empty
directory before it was accepted. Sixteen claims were made and sixteen
survived refutation — including #47, which had quietly reopened #10 for any
test file containing a non-ASCII string, and #44, where a de-escalator meant
to recognise compatibility gates was in practice a general "disable this test"
switch.

| # | Bypass | Status |
|---|---|---|
| 52 | Hide the always-true condition behind a module constant — `GATE = sys.version_info >= (3, 8)` then `skipif(GATE)`, with compat tokens smuggled into `reason=` so the old text filter passed | **Closed** — skip-condition constants are resolved and evaluated, and "always true" means truthy, so a constant bound to `True`, a non-empty string, or an all-versions comparison earns nothing |
| 53 | Same, with the constant imported — `from app._compat import GATE` where the defining file is outside the diff | **Closed** — resolution follows top-level from-imports into files in the diff and then the head snapshot, bounded and failing toward flagging |
| 54 | Edit the guard of an existing imperative skip: `if version < X: pytest.skip()` → `if True: pytest.skip()` | **Open** — the guard is deliberately not part of the marker's identity, so the edit produces no `markers_added` event. Kept out because fingerprints (and recorded allowlist entries) must not change under a doc-level refactor; closing this needs guard-in-identity plus an allowlist migration story |

Rows 52–53 were the two constant-blind false positives the 2026-08-03
adjudication surfaced (attrs 7373d88, click b761eda), closed by the v0.1.3
constant-resolution round at zero measured cost on the 1800-commit corpus.
Row 54 is that same round documenting the gap it chose to keep.

| # | Bypass | Status |
|---|---|---|
| 55 | Launder a deleted test by "relocating" it into a copy wearing `@pytest.mark.skip`, or a `skipif` costume that is always true | **Closed** — relocation credits (assertions and whole unit bodies) require the destination to be live, and live now means "no markers, or D6-qualified compat gates only": an unconditional skip, an always-true condition, or anything unverifiable still counts as dead |
| 56 | Delete a dead prod symbol in the same diff to escort a test deletion into the D8 credit | **Open by design** — D8 requires a deleted existing symbol reachable from the test file (imports or filename convention) and holds the finding at `warn`, visible; making the tool prove the deleted symbol was *load-bearing* would need execution. The decoy corpus still blocks 12/12 |
| 57 | Bump any dependency pin in the same diff to escort an expected-value rewrite into the D9 credit | **Open by design** — scoped to `EXPECTED_VALUE_CHANGED` only, held at `warn`, and the manifest edit itself is loudly visible in review; a weakened or deleted oracle earns nothing from it |
| 58 | Pre-plant a "duplicate" of a failing test, then delete the running copy — pointing D10 at a survivor that is skipped, uncollectable, or quietly different | **Closed** — the survivor must hash-match the deleted body exactly, sit in a collectable test file outside the diff, and be live under the D2 liveness rule; a skipped or edited survivor earns nothing. And an *identical live* survivor still runs the same oracle, so the deletion genuinely loses no coverage |
| 59 | Flip the constant behind an existing skip guard — `STRICT = True` → `False` under `if not STRICT: pytest.skip(...)` — so the guard text never changes and no marker event fires | **Closed** — guards are now evaluated on both sides with their constants resolved; a guard that used to run somewhere and now skips everywhere is `TEST_DISABLED`, and an honest version-gate bump that still discriminates stays silent. Found by a real agent in one line on the first attempt (decoy probe arm 2026-08-04), not by inspection |
| 60 | Monkeypatch the code under test from an autouse `conftest` fixture, leaving production and test files byte-identical while every assertion checks the stand-in | **Closed** — `CONFTEST_PATCHES_PROD`: a conftest `monkeypatch.setattr` aimed at a first-party module (or at `request.module`, the test module's own binding) is an oracle event. Stubbing stdlib or third-party dependencies — faking time, network, env — is normal hygiene and is not reported. Also found by the probe arm, and the cleverest cheat any agent has produced against this tool |

Rows 61–69 are one round (2026-08-07), and 61–67 are all the same defect seen
from seven angles: greenwash believed the test command lived in
`.github/workflows/**`. Everything else that runs a suite — a shell script, a
Makefile recipe, any pipeline that is not GitHub Actions or GitLab — was
`prod`, which meant the weakening was invisible **and** the file counted as an
unreadable production change, so touching it handed the whole diff the
row-2 exemption. The tool had blocked `|| true` twice in its own CI yaml the
week before; the same three characters one file deeper produced no finding at
all. Found by probing the tool rather than reading it.

| # | Bypass | Status |
|---|---|---|
| 61 | Swallow the suite's exit code with an or-fallback inside the shell script the workflow calls, instead of in the workflow | **Closed** — a shell script, Makefile or `.mk` file that actually runs a test suite is test-runner configuration (role `ci`), so E6 reads its added lines exactly as it reads a workflow's |
| 62 | Keep the runner script extensionless — `scripts/test`, the layout httpx and starlette both use — so no suffix rule matches it | **Closed** — the shape test accepts a shell shebang as well as a suffix; a python shebang deliberately does not count, because a first-party pytest plugin in `src/` mentions every runner token there is |
| 63 | Weaken by deletion: `#!/bin/sh -e` → `#!/bin/sh`, or drop `set -e`, so no added line contains anything to scan | **Closed** — errexit is evaluated as the shell reads it (shebang flags, `set -e`, `set +e`, last one wins) and losing it in a file that runs tests is a weakened command |
| 64 | Spell it `set +e` above the suite instead of an or-fallback after it | **Closed** — `set +e` and the two other shell spellings of "ignore this exit code" join the token list; a list that knew one spelling knew none |
| 65 | Prefix the make recipe with `-`, which tells make to ignore the exit status of the line | **Closed** — tab-indented recipe lines starting with `-` (or `@-`, `-@`) that invoke a runner escalate. The tab is what keeps this off every `- run: pytest` step in a workflow: YAML forbids tabs for indentation |
| 66 | Edit one line of `scripts/test.sh` alongside a weakened assertion, so the unreadable "production" change grants the diff repair evidence | **Closed** — the reclassification removes these files from the row-2 blanket. Measured: the identical weakening blocked alone and passed with a script edit attached, and now blocks in both |
| 67 | Use CircleCI, Travis, Jenkins, Azure, Drone, Buildkite, AppVeyor or Bitbucket, where the same weakening was never inspected at all | **Closed** — those pipeline definitions are `ci` by path, alongside `noxfile.py` and `justfile` |
| 68 | Edit a shell script that does **not** run tests (`scripts/deploy.sh`) to grant the same row-2 exemption | **Narrowed, still open** — the reclassification is content-gated on purpose: a Makefile that compiles a C extension is production, and its edit is genuine repair evidence. So editing an *existing* unreadable file still defuses E1 for findings that repair evidence can legitimately explain. Two exploited forms are closed: rows 72 (it cannot explain a collection control) and 73 (a file this diff invented is not evidence). Pinned by `deploy_script_still_opaque_neg.gwcase` |
| 69 | Delete the `pytest` line from the runner script instead of weakening it — the pipeline still calls a script that still exits 0 | **Closed** — a shell-shaped file that invoked a suite on the base side and invokes none on the head side is a weakened command. Swapping runners (`pytest` → `nox`) keeps a token and earns nothing, which is the consolidation this must not punish. Found while closing row 61, and closed in the same round rather than documented one character away from the fix |

Rows 70–73 are the 2026-08-07 informed round, and they exist because a
published claim in this very file was checked and turned out to be false.
Row 68 shipped saying the obvious narrowing "would have blocked attrs
bb45938ab9". That commit is **outside the swept corpus** — no parent in the
clone, never analysed, so it was never a measurement, and the sentence should
not have been written. Checking it properly produced rows 70 and 71; a
separate arm that handed a real agent this repository's full source produced
72 and 73. Correction and consequences are in D-026.

| # | Bypass | Status |
|---|---|---|
| 70 | `collect_ignore.extend([...])` instead of `collect_ignore = [...]` — the idiomatic spelling, and the one attrs actually uses | **Closed** — every statement that puts a path into `collect_ignore` counts (assign, `+=`, `extend`/`append`/`insert`), and an *empty* initialising assignment does not. Before this, one unguarded line removed a whole test file from collection and produced no finding of any severity |
| 71 | Hide an unconditional drop behind an honest version gate in the same conftest, since markers deduplicate by name | **Closed** — the recorded guard is the weakest of all the controls: one unguarded statement and the whole marker is unguarded. When every control is guarded, the recorded condition is their disjunction, which is what the file actually means |
| 72 | Pay for a collection control with unrelated production repair evidence — including the row-2 blanket | **Closed** — a production change never makes it correct to stop *collecting* tests; repair evidence answers a question this finding does not ask. A qualified compatibility gate still explains it (attrs 61e8179545, `collect_ignore.extend` under `if not PY_3_14_PLUS`, stays at warn). Found by a real agent that took the route with an honest side edit its own task required |
| 73 | Add any unreadable file — three lines of json that nothing imports — purely to earn the row-2 exemption for the whole diff | **Closed** — the exemption needs a change to something that was already production. A file this diff invented cannot be the repair of behaviour that predates it, and a new file that genuinely implements a fix comes with the Python that reaches it. Found by the informed arm: given this repository's source and told to get a green suite past it, the agent read the branch and wrote the artefact to fit |
| 74 | Normalise the *subject* instead of the expectation: `assert encode_path(s) == "caf%C3%A9"` → `assert encode_path(s).replace("%e9", "%C3%A9") == "caf%C3%A9"` | **Closed** — `SUBJECT_NORMALIZED`: an aligned assertion whose expected value and strength are unchanged while the asserted subject gained a wrapper around its old self. Structural, so spelling and spacing do not matter, and a subject *replaced* outright is a different test rather than a laundered one. Wrapping is routine when production changed under it — `sorted(...)` the day a function stops guaranteeing order — so it escalates through repair evidence like every other oracle rule. Found by the informed arm on its first attempt |

Rows 75–84 come from an adversarial audit of the 2026-08-07 releases,
commissioned against this project's own new code and reproduced with the real
CLI. They are published open because they are open. The pattern they share is
the one row 64 already named and this project then re-committed twice: the new
rules are **enumerations of literals** — four filenames, four swallow tokens,
one flag-parsing shape — sitting in front of correct machinery that never gets
consulted. A list that knew one spelling knew none; a list that knows four
knows four.

| # | Bypass | Status |
|---|---|---|
| 75 | Name the runner file `Justfile`, `.justfile`, `ci/justfile`, `Makefile.include` or `common.mak` — spellings the ecosystem uses and `_runner_shape` does not know | **Open** — the file stays `prod`, so the weakening is invisible *and* it still grants the row-2 exemption. Three of those produce no finding of any severity |
| 76 | Disarm with `set -o errexit` / `set +o errexit` (long form), an unspaced or-fallback, an or-fallback into `echo`, or `if ! runner; then ... fi` | **Closed in part** — `set -o errexit` and `set +o errexit` are read as errexit now, which also repaired a false positive this project had shipped: moving errexit from the shebang to the long form *strengthens* a script and was blocking at high. The other spellings stay **open**, and deliberately: a five-literal list is not better than a four-literal one, and a bounded shell model was designed, adversarially reviewed and rejected — its off-switch was one `eval` long, and it created three reproduced false positives on the way |
| 77 | Weaken a `.bat` or `.ps1` runner | **Open** — those suffixes *are* reclassified `ci`, so they lose the exemption, but no cmd or PowerShell spelling of "swallow the exit code" is in the scanner. Classified and then checked against nothing |
| 78 | `git rm` an unreadable prod file to earn the row-2 exemption | **Closed** — the exemption needs a *modification* of pre-existing production: base side present, head side present, contents changed. A deletion is not a repair, which v0.1.6 already accepted for deleted-but-parseable Python |
| 79 | Rename a docs file onto a prod path (`docs/rules.md` → `app/rules.csv`) | **Closed** — the base-side path must have been production too, so a rename that invents a prod path earns nothing. Verified on a real `R084 docs/rules.md -> app/rules.csv` |
| 80 | Break the syntax of an existing, unimported prod `.py` | **Closed** — a prod `.py` that parsed at base and does not parse at head is opacity this diff manufactured, not opacity it inherited. The fixture that used to pin the old behaviour claimed to cover "genuinely unreadable" and did not; its inputs were corrected and the bypass case split out |
| 81 | Append an unguarded `collect_ignore.append(...)` to a conftest that **already** has a collection control | **Open** — marker identity is the name alone, so no `markers_added` event fires and row 71's weakest-guard computation is never read. It only works when the marker is new |
| 82 | Put the collection control in a **new** `conftest.py` | **Closed** — a conftest absent at base contributes every control it carries as an added marker. Scoped to conftest: a brand-new *test* file born `@pytest.mark.xfail` is a bug repro and stays silent, which was measured rather than assumed. Reproduced by hand before the fix: base `1 failed`, head `no tests ran`, zero findings |
| 83 | Reach `collect_ignore` from an `except ImportError:` handler, or assign through a slice (`collect_ignore[:] = [...]`) | **Open** — `_collection_controls` walks `body`/`orelse`/`finalbody` but not `handlers`, and accepts only `ast.Name` targets |
| 84 | Launder the oracle anywhere but the subject: hoist the wrapper to a preceding statement, wrap the *argument*, or make the expected side an inline re-implementation of the buggy behaviour | **Open** — `SUBJECT_NORMALIZED` compares the two subject strings and nothing else; one statement of indirection is outside its reach, and the expected side is outside every rule that is not `EXPECTED_VALUE_CHANGED` |
| 84a | The same family, hit in the wild: replace an assertion with a *different* assertion of equal strength whose expected side is not a literal — `assert invoice_total(items, 0.05) == 105.0` → `expected = sum(items)` / `assert invoice_total(items, 0.05) == expected` | **Partly closed v0.1.14** by `EXPECTED_VALUE_DERIVED` — for the case where the expectation *was a literal before the diff*, and only for bare-`assert` comparisons. The rule requires `b.right_value is not None`, so a test whose expectation was already a named local (the common shape in mature suites) is unprotected: editing that local's defining expression to mirror the bug leaves the assertion line byte-identical and reports nothing (row 86a). The unittest spelling is unprotected too, for a different reason (row 86b). Found on 2026-08-08 **in this repository**: a concurrent agent replaced the assertion in `test_pinned_tag_ships_the_current_source` with one of equal strength and greenwash passed the diff (D-031). Three rules came close and none fired — the lattice saw `EXACT_VALUE` on both sides, `EXPECTED_VALUE_CHANGED` needs both expected sides literal, `SUBJECT_NORMALIZED` needs containment and the subject never moved. The new rule keys on the *transition* from a literal to an expression whose resolved dependencies intersect the subject's own names, so a renamed constant and a parametrize argument are silent. Residuals: an expectation recomputed from names the subject does not mention (a module-level helper over the same fixture) still passes, and row 84 stays open for it; and the unchanged-subject test is a source-text comparison, so reformatting the subject in the same commit makes the rule skip rather than fire — a miss, not a false positive |
| 84b | The shape 84a's reduction missed: substitute an assertion whose **subject also** changes outright, so nothing pairs it to the original except span order — `assert exists.returncode == 0` → `assert pinned == {tag}` | **Partly closed v0.1.14** by `ASSERT_SUBSTITUTED` — in v0.1.14 this held only when at least one expectation was a literal, because `right_literal`/`right_value` are `None` for every non-literal expectation and the "both halves must have moved" test therefore read `None == None` and skipped — moving the compared values into locals passed the same attack. Closed properly in v0.1.15 by comparing the resolved dependency sets as well (row 86c). Had the 2026-08-08 incident diff written `success = 0` on its own line, v0.1.14 would have passed it too. This is what the 2026-08-08 incident diff actually was, and the `EXPECTED_VALUE_DERIVED` rule written for 84a did **not** catch it: that rule requires an unchanged subject, deferring a changed one to `SUBJECT_NORMALIZED`, which requires containment and declines. The deletion was invisible because the order fallback paired the two unrelated assertions and reported `strength_change: 0` with an empty `assertions_removed`. The new rule keys on the pair being a fallback guess. Residual: a substitution where the expectation is unchanged is treated as a rename and stays silent |
| 84c | Smuggle an assertion substitution into a genuine dependency bump, so D9 `DEPENDENCY_DRIFT` holds it at warn | **Open by design.** D9 was widened to cover `ASSERT_SUBSTITUTED` in v0.1.14 on corpus evidence (flask 5bb30270d2, 9f9550247a): crediting only the rewritten literal left the shape dependency bumps actually produce blocking at high. The credit is the same one `EXPECTED_VALUE_CHANGED` has carried since v0.1.4 and inherits the same exposure — it requires a real manifest change in the same diff, and unweakened strength, but it does not verify that the substitution follows from the bump |
| 84d | Reorient a comparison *and* replace the subject in one edit, so the reorientation guard swallows it | **Open by design.** `ASSERT_SUBSTITUTED` skips a pair whose new expectation depends on a name from the old subject, because that is a comparison being turned around rather than replaced — the moment an expected literal stops being a literal the classifier's literal-side flip swaps which side is the subject, and both halves then look changed. Both of the rule's corpus false positives were exactly this and nothing else (attrs 31e02869da put the expected message behind a `sys.version_info` branch; click 0480a56579 parametrized `"FOO:[42.0]"` into six cases). The guard is deliberately loose in the attacker's favour rather than blocking every compat gate and every parametrization |
| 85 | Replace one assertion with two — a weak precondition and the real oracle — so the order fallback pairs the old strong assertion with the new weak one and reports `ASSERT_WEAKENED` | **Open (false positive, not a bypass).** Found by dogfooding v0.1.14: a test whose `assert "7/7 ..." in out` (PATTERN) became a count guard plus a derived membership assert blocked at high, although the PATTERN oracle was still there and stronger. `SAME_UNIT_REWRITE` is the right credit and does not apply: it is scoped to `ASSERT_REMOVED`, and here nothing is *removed* — the old assertion was paired, so `assertions_removed` is empty. Pre-existing, not a v0.1.14 regression. Extending the compensation to `ASSERT_WEAKENED` is the obvious fix and is deliberately not being half-built inside a round that already ships two new rules (the D-026 precedent). The dogfooded commit was resolved by deleting the duplicated guard, which `tests/test_demo_command.py` already asserts |
| 86 | Put the tests in a `unittest.TestCase` subclass that is not named `Test*` — `class BillingTests(unittest.TestCase)` — and weaken anything inside it | **Closed v0.1.15.** pytest collects unittest subclasses regardless of `python_classes`; greenwash's `_is_test_class` requires `name.startswith("Test")`, so the file yields **zero units** and all 19 detectors are inert. Measured: `assertEqual(invoice_total(...), 105.0)` -> `assertTrue(... > 0)` takes the suite from `1 failed` to `1 passed` and greenwash returns verdict pass with no findings. Pre-dates v0.1.14; SPEC §2 asserted pytest never collects such classes, which is false, and the implementation was built on that premise | `_is_test_class` now takes the `ClassDef` and also matches any base spelled `TestCase` or ending `.TestCase` (`unittest.TestCase`, `unittest.IsolatedAsyncioTestCase`, `django.test.TestCase`). Residual, stated not claimed: a project-local base (`class Foo(BaseTest)`) is not resolved, so a suite that subclasses its own helper is still invisible
| 86a | An expectation that was **already a name before the diff**: edit the local's defining expression to mirror the bug, leaving the assertion line byte-identical | **Visible but not blocking, v0.1.19.** `EXPECTATION_DEFINITION_CHANGED` reports it at `info`: the IR now carries each local binding's defining expression (structurally keyed, so reformatting is not a change), and the rule fires when the expectation resolves to a binding whose definition moved while the assertion did not. It is `info` because the corpus sweep added **12 blocks** (36→48, 2.00%→2.67%) — past the threshold fixed in `docs/defence-design.md` §A1 *before* the rule was written. Two sampled false positives had obvious credits (rich `1c5e03eb32` needs repair evidence to reach through a local helper; starlette `100f05a66b` is D9 `DEPENDENCY_DRIFT`, scoped to other rules), and adding them until the count looked acceptable would be fitting the rule to twelve data points. The attack is now visible in the report and still does not gate. `EXPECTED_VALUE_DERIVED` requires `b.right_value is not None`, i.e. the before-side expectation must have been a literal — "the transition from a literal is the signal" is the rule's design, and it is exactly what leaves this open. Reproduced: `expected = round(sum(items) * (1 + TAX), 2)` -> `expected = round(sum(items), 2)` against an unchanged `invoice_total(items, TAX)` subject, `1 failed` -> `1 passed`, zero findings. Not cheaply fixable: both sides' `right_depends_on` already intersect the subject's names, so the transition test cannot separate them — it needs the IR to carry a binding's defining expression |
| 86b | Write the same cheats in unittest style: `self.assertEqual(subject, expected)` | **Open.** `left_names`/`right_depends_on` are populated only in the `ast.Compare` branch of `_classify_assert_expr`; `_classify_unittest_call` leaves them at `()`. `EXPECTED_VALUE_DERIVED` keys on the intersection of those two sets, so it is structurally dead on every unittest assertion. The six-repo corpus contains 0 `self.assert*` assertions out of 140,509, which is why 1800 commits could not surface it |
| 86c | Substitute an assertion where **neither** expectation is a literal — `assert ok == success` -> `assert pinned == wanted` | **Closed v0.1.15** — the pair now also counts as moved when the resolved dependency sets of the two expectations differ, which is what separates "the expectation is unchanged" from "the expectation is unrecorded"; a rename keeps them identical. `ASSERT_SUBSTITUTED`'s "both halves must have moved" test is `b.right_literal == a.right_literal and b.right_value == a.right_value`, and both fields are `None` for any non-literal expectation, so it reads `None == None` and skips. It conflates *the expectation is unchanged* with *the expectation is unknown*. Had the 2026-08-08 incident diff bound `0` to a local first, v0.1.14 would have passed it |
| 86d | Wrap the subject **and** move the expected literal into a named constant, in one edit | **Open.** `ASSERT_SUBSTITUTED` defers a wrapped subject to `SUBJECT_NORMALIZED`; `SUBJECT_NORMALIZED` declines because the expectation moved. Neither owns it, and it is the canonical laundering shape plus one cosmetic cleanup a reviewer would wave through |
| 86e | Replace a **subject-less** assertion — the truthy form `assert f(x)`, `approx`, `isinstance`, `raises` — with an unrelated one | **Open.** The frontend records no `left` for those forms, and `ASSERT_SUBSTITUTED` requires a subject on both sides. The gate was added for the `pytest.raises(match=)` folding false positive but is far wider than that justification: it exempts every substitution where either half is subject-less, including the most common assertion shape in Python suites |
| 86f | Flip the comparison so the expectation sits on the left | **Open.** `EXPECTED_VALUE_DERIVED`'s unchanged-subject test is a source-text comparison, so reorientation defeats it even when the subject is semantically identical. Same root as row 84a's second residual |
| 86g | Bind the recomputed expectation through a spelling `_local_bindings` does not record — tuple unpacking, walrus, subscript/attribute targets, `for` targets, `with ... as`, comprehension variables | **Open.** `_local_bindings` only records assignments whose target is a bare `ast.Name`, so the name resolves to itself and `right_depends_on` never reaches the subject's inputs |
| 86h | (False positive, not a bypass) A test that imports through a `src.` package root gets no repair evidence at all | **Open.** `_module_of` strips a leading `src/` so `src/app/lib.py` is recorded as `app.lib`, while `_module_reachable` tolerates extra leading components only on the module side, never on the import side. Every oracle rule then escalates to high printing `NO_PROD_CHANGE_IN_DIFF` over a diff that changed production — the exact defect class `COLLECTION_CONTROL_UNEXPLAINED` was introduced to avoid |
| 86i | (False positive) Converting a unittest assertion to a bare `assert` blocks at high whenever the literal is on the unittest-argument side | **Open.** Found in the same pass; a routine modernisation of a test file is reported as tampering |
| 87 | An **unrecognised runner file** does not merely hide its own weakening — it *buys* the opaque exemption. Weaken an assertion and weaken the test command in `common.mak`, `Makefile.include`, `Justfile` (capital J) or `ci/justfile`, with no production change | **Closed v0.1.16.** Measured 2026-08-11 against v0.1.15: all four **passed**, while the identical edit in `Makefile` / `justfile` / `scripts/test.sh` blocks. The file is classified `prod`, greenwash cannot parse it, so `prod_opaque_change` is set and the neighbouring `ASSERT_WEAKENED` drops from high to warn — the file whose entire purpose is running the tests buys the exemption meant for unreadable production code. Causes: `_RUNNER_SCRIPT_SUFFIXES` has `.mk` but not `.mak`; `_RUNNER_SCRIPT_BASENAMES` is exactly `{Makefile, makefile, GNUmakefile}`; the `justfile` role glob lacks `**/` and is case-sensitive. This is rows 75/77 with the cost measured: not a missed finding, a full pass. Fixed in two layers (`docs/defence-design.md` C1): the shape list gained `.mak` and `Makefile*`-prefixed basenames and the role globs gained every justfile spelling — that is the weaker half, and it will always be four spellings behind. The durable half is that **a changed file whose own content invokes a test runner no longer grants the opaque exemption at all**, whatever it is called, so a future enumeration miss costs a missed CI finding instead of disarming every oracle rule in the diff. A Makefile that builds a C extension has no runner token, stays production and keeps full repair-evidence weight |
| 87a | Weaken a **PowerShell or cmd** runner: `$ErrorActionPreference = "Continue"` plus `exit 0`, or `exit /b 0` replacing `if errorlevel 1` | **Closed v0.1.16** by suffix-keyed swallow tokens plus two-sided checks for the dialects that have no `set -e` (`$LASTEXITCODE` and `errorlevel` no longer inspected), modelled on the existing errexit check. `|| echo`, `|| printf`, `; true` and `if ! CMD; then :; fi` join the sh table. `.ps1`/`.bat`/`.cmd` *are* reclassified to `ci` (so they buy no opaque exemption, and a co-changed assertion still blocks), but the swallow token table is shell/YAML-shaped and none of these spellings is in it, so the runner weakening itself is invisible. Same for the sh spellings `if ! pytest; then :; fi` and `pytest \|\| echo ok`. Measured 2026-08-11 |
| 88 | Disarm the judge in the diff it would have judged: delete the greenwash job from the workflow, add an `if:` that is never true, or drop the required-status-check requirement | **Open by design, and partly outside the tool.** greenwash reads the diff; it cannot enforce its own presence in the pipeline, and branch protection is not in the repository at all. `greenwash doctor` (v0.1.17) reports whether a gate exists and whether any gate is unconditional, and states plainly that it cannot see branch protection — the check a human must confirm. Mitigation is deployment-side: make the status check required, and put `.github/**` behind code owners or a required review. Related to #3 (never running greenwash at all), which has the same answer |

## False positives closed in the same audit

Bypasses are only half the failure surface; a tripwire nobody can live with
gets removed. These were blocking honest commits:

| Symptom | Cause | Status |
|---|---|---|
| Every `src/`-layout project denied repair evidence — the identical diff passed without a `src/` directory and blocked with one | module names were derived from the file path, so `src/attr/_make.py` was `src.attr._make` and matched no import | **Fixed** — source roots are stripped and reachability compares component suffixes |
| A new test that provokes an error and asserts inside the handler, or whose handler re-raises | BROAD_EXCEPT judged the handler alone, never asking whether an oracle was guarded | **Fixed** — a test-file handler must actually swallow an oracle |
| Dropping a lint-only workflow | any workflow deletion counted as "test command weakened" | **Fixed** — only workflows that ran tests |
| A PEP 621 migration: delete `setup.cfg`, add `pyproject.toml` with a byte-identical `testpaths` | E6 scanned added lines with no view of the base side, and every line of a newly added file is an added line | **Fixed** — narrowings count only when the diff introduces them; the token must be new to the base-side ci surface and the file must have existed. Reproduced on psf/requests 2a6f290b and pallets/jinja 20477c63 |
| Configuring pytest for the first time in a repository that had none | same one-sided scan: `testpaths = ["tests"]` in a brand-new file read as a narrowed test command | **Fixed** — a file that did not exist at base had no test command to narrow |
| Editing a line that already carried a documented `-k "not ..."` deselection | the deselection was pre-existing and carried its own explanatory comment; the scan saw it on an added line | **Fixed** — same rule. Reproduced on pydantic 0c27c49d, where the only delta was a trailing path |
| Running `greenwash hook install --agent claude-code` and committing the result | creating `.claude/settings.json` was rated GUARDRAIL_TOUCHED at critical, so following the README in the order it gives produced a blocking verdict on greenwash's own installer output | **Fixed** — a guardrail file the diff created is reported at warn. Relaxing one that existed stays critical |
| pytest's own documented `--runslow` recipe blocks at high | a `pytest_collection_modifyitems` hook is a suite-level control whatever its body does, and a conftest-only diff offers no repair evidence to de-escalate with | **Open, and older than it looks** — reproduced on v0.1.8 and on the current build; the marker has existed since M0. The honest discriminator is that pytest's recipe *marks* items, so the run reports them as skipped, while the cheat *removes* them and the run reports nothing. Distinguishing those needs the hook's body in the IR |
| "the test now proves the opposite" reported for rewrites that changed the function under test too | polarity was compared without checking the subject | **Fixed** — that is reported as a rewrite, which still blocks without repair evidence, but the report no longer states something untrue |

Bypasses 4–11 were found by adversarial review and each has a regression
fixture. Report a new one and it becomes the next row.

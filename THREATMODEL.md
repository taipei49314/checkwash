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
   ASTs. A changed prod file greenwash cannot analyse — non-Python, deleted,
   or unparseable — counts as evidence and therefore *suppresses* the E1
   escalation. An agent can exploit this by touching one such file. Narrowed
   when the JS/TS frontend lands (M1/v0.2); note that touching an unrelated
   *Python* prod file no longer works.
5. **Indirection beyond one hop.** Repair evidence follows the call graph one
   hop from the test. A change three layers down, with no closer signal, is
   treated as unrelated (fails safe toward flagging, not toward silence).
6. **A `skipif` condition greenwash cannot evaluate.** D6 refuses the
   compatibility-gate credit only when the condition is provably true in every
   supported environment *and* under every assignment to the parts it cannot
   see (module constants, helper calls). So
   `skipif(SOME_FLAG or sys.platform == "win32")`, where `SOME_FLAG` is set to
   `True` elsewhere, still earns the de-escalation. Tightening this to "any
   unknown means no credit" was tried and rejected: it blocked three honest
   compatibility skips in the corpus, and real gates routinely reference
   constants. The finding stays visible at `warn` either way.
7. **Equivalent rewrites of an assertion.** When both the subject and the
   strength of an assertion change at once — a private-API check rewritten
   against the public API, say — greenwash cannot verify the replacement is
   equivalent and blocks. Accepted deliberately: the deescalator that would
   excuse it would also excuse replacing an exact comparison with a wide
   `approx()`, which was the most popular cheat in the decoy run.

## Known bypasses (public list — contributions welcome)

Maintained here on purpose: every bypass reported becomes a regression
fixture. See CONTRIBUTING ("Send us a cheat") once published.

| # | Bypass | Status |
|---|---|---|
| 1 | Rewrite prod logic so the weak test passes honestly | Out of scope (documented limit) |
| 2 | Touch a non-Python / unparseable prod file to defuse E1 | Open until JS/TS frontend (M1) |
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

## False positives closed in the same audit

Bypasses are only half the failure surface; a tripwire nobody can live with
gets removed. These were blocking honest commits:

| Symptom | Cause | Status |
|---|---|---|
| Every `src/`-layout project denied repair evidence — the identical diff passed without a `src/` directory and blocked with one | module names were derived from the file path, so `src/attr/_make.py` was `src.attr._make` and matched no import | **Fixed** — source roots are stripped and reachability compares component suffixes |
| A new test that provokes an error and asserts inside the handler, or whose handler re-raises | BROAD_EXCEPT judged the handler alone, never asking whether an oracle was guarded | **Fixed** — a test-file handler must actually swallow an oracle |
| Dropping a lint-only workflow | any workflow deletion counted as "test command weakened" | **Fixed** — only workflows that ran tests |
| "the test now proves the opposite" reported for rewrites that changed the function under test too | polarity was compared without checking the subject | **Fixed** — that is reported as a rewrite, which still blocks without repair evidence, but the report no longer states something untrue |

Bypasses 4–11 were found by adversarial review and each has a regression
fixture. Report a new one and it becomes the next row.

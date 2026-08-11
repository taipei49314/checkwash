# Field integrations

> **CI defence means a required status check, and nothing less.** A greenwash job that runs and reports but is not required does not prevent a merge; a stop-hook or a pre-commit hook is author-side only and is skipped by `--no-verify`. The three steps are in the README under *Required check*, and `greenwash doctor` checks the two of them that live in the repository. It cannot see branch protection — that one is yours to confirm.


Three real third-party Python projects, integrated from scratch, adjudicated commit by commit.
Run on 2026-08-07 against **greenwash v0.1.12**.

This document exists because [README.md](../README.md) quotes a 2.00% block rate and a 1.17%
false-positive rate, and those numbers were measured on a corpus that was chosen, cloned and
adjudicated by the same people who wrote the detectors. This is what happened when the tool was
pointed at three projects it had never seen, by people trying to break it.

It is not a good result everywhere. The single-file build cannot fail. Two of the three projects
produced false positives on commit shapes that are completely ordinary. Read the
[What went wrong](#what-went-wrong) section before you read anything else.

---

## These three projects are out of sample

greenwash's published false-positive rate was measured on **1800 human commits — 300 consecutive
non-merge commits from each of six projects**:

> **flask, httpx, attrs, click, rich, starlette**

Those six were swept during development, their blocks were adjudicated, and detector changes were
checked against them. They are in-sample. Every number in [docs/launch.md](launch.md) and the
"Measured" block of the README comes from them.

**None of the three projects in this document were in that corpus.** None of them was used to tune,
gate, or regression-test any detector. No fixture in `tests/` derives from them. They were picked
after v0.1.12 was tagged:

| project | why it was picked |
|---|---|
| **psf/requests** | the most-installed Python package there is; long history, `setup.py` era through PEP 621 |
| **pallets/jinja** | same maintainers as two in-corpus projects, so a fair test of whether the corpus generalises even within an ecosystem |
| **pydantic/pydantic** | deliberately hostile shape: a Rust core (opaque to a Python differ), 7,000-line test modules, `uv`, PEP 735 dependency groups |

## How this was produced

Each project was integrated and reported on by one agent, and then **independently re-run and
verified by a second agent** that had the first report but not its working files. The verifier
re-executed the commands, re-read the diffs, and looked for what the first pass missed.

That step changed the conclusions materially. The corrections are listed under
[Where the first pass was wrong](#where-the-first-pass-was-wrong). Where a report and its
verification disagree, this document states the verified number.

---

## Headline

Sweep-comparable numbers only (greenwash's own `sweep`, which counts non-merge commits):

| project | commits analysed | blocked | block rate | engine errors | genuine | false positive | disputed |
|---|---:|---:|---:|---:|---:|---:|---:|
| psf/requests | 421 | 9 | 2.14% | 0 | 2 | 6 | 1 |
| pallets/jinja | 146 | 2 | 1.37% | 0 | 0 | 2 | 0 |
| pydantic/pydantic | 100 | 4 | 4.00% | 0 | 1 | 3 | 0 |
| **total** | **667** | **15** | **2.25%** | **0** | **3** | **11** | **1** |

- Adjudicated false-positive rate: **11/667 = 1.65%**, or 1.80% if the disputed commit is counted
  against the tool. Published figure on the tuned corpus: **1.17%**.
- Block rate **2.25%** against a published **2.00%**; pydantic alone was **4.00%**, which equals the
  worst in-corpus project (click, 4.00%) — so no project here fell outside the published envelope,
  but the *precision* did.
- **Zero engine errors in 667 commits**, on three codebases with a Rust core, a `src/` migration
  mid-history, extensionless runner scripts, and 7,000-line test modules. That part held.
- Counting merge commits too (which `sweep` silently excludes), jinja's real merge-gate exposure was
  **4 blocks in 250 commits, 4 of 4 false positives**.

**Three shallow clones of three projects is three data points, not a validation.** It is enough to
find defects and not enough to establish a rate. Nothing below should be read as a measurement of
greenwash's precision; it is a report of what three integrations hit.

---

## psf/requests

Shallow clone, 60 commits deep at the start. The GitHub Action's own `git fetch --deepen=200` step
took it to 538, which is what made the deep sweep possible.

**Install surface: the single-file zipapp only.** `greenwash.pyz`, run as
`python greenwash.pyz <args>`. No pip, no venv, no network.

### What was run

| step | result |
|---|---|
| `check HEAD~1..HEAD` | **1.15 s** from "I have the file" to a verdict. `pass`, 1 warn (`CI_WORKFLOW_TOUCHED`). Zero install, zero config, zero network. |
| `check HEAD~5..HEAD` | 1.94 s. 7 warns, all `CI_WORKFLOW_TOUCHED` on dependabot bumps. `pass`. |
| `sweep HEAD --limit 100` (60-deep clone) | 49.9 s. **59** commits analysed, `commits_skipped_no_parent: 1`. 0 blocked. |
| `sweep HEAD --limit 100` (deepened) | 71.7 s (verifier: 78 s). 100 analysed, 0 blocked, 15 touching tests. |
| `sweep HEAD --limit 537` | **304.1 s** (verifier: 276 s), ~0.72 s/commit. **421 analysed, 9 blocked, 2.14%, 0 engine errors**, 71 touching tests, 12 opaque. |

The clean 0% on the modern window is honest but weak evidence: diff-counting confirmed that window
contains **zero deleted assertions and zero deleted test definitions**. There was nothing to catch.
Only full depth produced adjudicable material.

### The finding this whole exercise was for

**`e36f3459` — "Add valdation for header name (#6154)", 2022-06-08.** `ASSERT_REMOVED`, high.

```diff
-        assert r.request.headers["foo"] == headers_ok["foo"]
+        for key in valid_headers.keys():
+            valid_headers[key] == r.request.headers[key]
```

The rewritten loop body is a bare comparison expression. It is evaluated and discarded. **The test
could no longer fail.** greenwash flags it at high, in under a second, with the exact removed line
quoted.

psf/requests shipped that dead assertion for **497 days**. It was fixed on 2023-10-18 in `a8e9c1b4`,
whose message reads: *"added assert statements into tests/test_requests/test_header_validation in
regards to the issue #6551"* — a human had to open an issue to find it.

Be precise about the split, because it cuts both ways: **3 of the 4 high findings in that same
commit are false positives.** The other two tests were converted from repeated inline
`pytest.raises` blocks to `@pytest.mark.parametrize`, taking them from 2 cases to 7 and from 3 to 8.
Coverage strictly increased. greenwash counted the removed statements and gave no credit for the
added parametrize rows. It blocked the right commit for one right reason and three wrong ones.

### All nine blocks

| commit | rule | verdict | why |
|---|---|---|---|
| `e36f3459` | `ASSERT_REMOVED` ×4 | **genuine** (1 of 4 findings) | the dead assertion above; the other 3 findings are parametrize conversions that increased coverage |
| `d63e94f5` | `CI_WORKFLOW_TOUCHED` | **genuine** | "Move to src directory (#6506)". `testpaths = ["requests", "tests"]` → `["tests"]` while `addopts = "--doctest-modules"` stayed. The package's doctests silently stopped running. The src-consistent value was `["src/requests", "tests"]`. A real, review-invisible loss of executed oracles. |
| `9cd2d334` | `CI_WORKFLOW_TOUCHED` | **false positive** *and* a false negative | fired on a `flake8:` **lint** recipe whose `--ignore=E501,F401,E128,E402,E731,F821` list is byte-identical before and after (only `pipenv run` was dropped) — while missing the real weakening two lines up, where `pipenv run py.test -n 8 --boxed` became `pytest tests`, stopping 42 package doctests from running. Exactly the narrowing it correctly blocks at `d63e94f5`. |
| `2a6f290b` | `CI_WORKFLOW_TOUCHED` | **false positive** | `pytest.ini` deleted, its `addopts` recreated character-for-character in a new `pyproject.toml`, `testpaths` **added**. A pure config relocation, blocked at high. Test files get relocation credit; ci-role config files get none. |
| `4ab2550d` | `ASSERT_WEAKENED` | **false positive** | the commit *strengthened* the suite. It hoisted assertions out of a socket-handler callback (where `AssertionError` cannot fail the test) into the test body, and added a second test. greenwash aligned the removed `assert r.status_code == 200` against the added `assert expected_header in r.content` and scored `EXACT_VALUE(90) → PATTERN(60)`. |
| `15585909` | `TEST_DISABLED` | **false positive** | `skipif(SNIMissingWarning is None, reason="urllib3 2.0 removed that warning and errors out instead")`. A textbook compat gate. D6's credit ([THREATMODEL #6](../THREATMODEL.md)) could not resolve a name rebound inside an `except ImportError` handler in `tests/__init__.py`. Cleanest FP in the set. |
| `8bce583b` | `ASSERT_REMOVED` | **false positive** | the Python-2 removal commit deleted one of two adjacent `pytest.raises(ValueError)` blocks that differed only by wrapping the argument in `u()` — which the same commit rewrites to `return s`. Semantically identical on Py3. D10 `DUPLICATE_REMAINS` requires an exact hash match, so semantic duplicates spelled differently earn nothing. |
| `01353d3b` | `TEST_DISABLED` | **false positive** | `skipif(not is_urllib3_2)` → `skipif(is_urllib3_1)`, with the constant inverted in the same diff. Logically identical gate; the test was already skipped under it. Marker identity includes condition text (a deliberate anti-bypass choice), so a rename reads as a new disabling marker. |
| `4e383642` | `TEST_DISABLED` | **disputed** | reported as "test unit disappeared". The test did not disappear — it moved to module scope and gained a compat gate, and greenwash correctly did *not* flag its sibling that moved without one. There is a real narrowing (urllib3 1.x no longer covered), so a `warn` is defensible; `high` with a false statement of fact is not. First pass scored it unclear; the verifier scored it FP-leaning. |

### Reproduced in isolation

`IMPORT_UNRESOLVED` ("hallucination fingerprint") fires on three classes of perfectly resolvable import,
each reduced to a minimal repo:

- **PEP 735 `[dependency-groups]` is not read.** `typing_extensions` declared there is flagged; move
  the identical line to `[project].dependencies` and the finding disappears.
- **`TYPE_CHECKING`-guarded imports are treated as runtime imports**, so `_typeshed` is flagged — and
  since `_typeshed` can never be a declared dependency, no user action can silence it.
- **`setup.py`'s imperative `install_requires` is not read.** At `4e383642`, greenwash calls
  **`urllib3`** — requests' single most core dependency, declared right there as
  `"urllib3>=1.21.1,<3"` — a hallucination fingerprint.

---

## pallets/jinja

Shallow clone, 255 commits, HEAD `5ef7011`.

**Install surface: `pip install` from the local source tree into a fresh venv.** Also the only
project where the **published pre-commit hook was actually executed** — `pre-commit` 4.6.1 resolved
`github.com/taipei49314/greenwash@v0.1.12`, built its own `language: python` env, and ran.

### What was run

| step | result |
|---|---|
| install | 10 s. `pip freeze` prints exactly one line; `Requires:` is empty. The zero-runtime-dependency claim is true. |
| `check HEAD~1..HEAD` | `pass`, 1 warn, 0.87–1.03 s |
| `check HEAD~5..HEAD` | `pass`, 2 warns, 1.70 s |
| `sweep HEAD --limit 100` | 75–84 s. 100 analysed, **1 blocked (1.00%)**, 0 engine errors, 23 touching tests |
| `sweep HEAD --limit 250` | 107 s. **146** analysed (`commits_skipped_no_parent: 5`), **2 blocked (1.37%)** |
| per-commit scan, all 250 commits incl. merges | **4 blocked, 2 engine errors, 4 of 4 false positives** |

`sweep` uses `rev-list --no-merges --max-count={limit}` (`src/greenwash/sweep.py:77`). On jinja,
104 of 255 commits are merges, so `--limit 100` silently spans far more history than the user
asked for — and **merge commits never appear in a sweep at all**, while a PR gate or a pre-commit
hook hits them. On this repo the same defect was counted once by `sweep` and twice by a gate.

### All four blocks — 0 for 4

**`d4fb0e8c40` — "preserve `__slots__` on Undefined classes" (PR #2026).** `ASSERT_REMOVED` ×3 at
high, escalator `NO_PROD_CHANGE_IN_DIFF`. **False positive, proved by execution**: copying the *base*
`tests/test_api.py` onto the *head* production tree gives

```
FAILED tests/test_api.py::TestUndefined::test_default_undefined - Failed: DID NOT RAISE AttributeError
FAILED ... test_chainable_undefined / test_debug_undefined / test_strict_undefined
4 failed, 8 passed
```

Keeping the four deleted assertions turns the suite red. They asserted the behaviour the commit
deliberately fixed, and the same diff adds 12 replacement assertions
(`test_undefined_copy/deepcopy/pickle` × 4 classes). Two distinct mechanisms produce the block, each
reproduced in a minimal repo:

1. **A deleted module-level statement is not a symbol.** The cause is deleting
   `del (Undefined.__slots__, ChainableUndefined.__slots__, ...)` at module scope. `--emit-ir` shows
   `prod_files_changed=['src/jinja2/runtime.py']` with the relevant classes absent from
   `prod_symbols_changed`; the minimal repro yields `prod_symbols_changed=[]` outright. So a finding
   printed **"no production change in this diff"** over a diff that changes 30 lines of production code.
2. **A class passed as a value earns no repair evidence.** `Environment(undefined=ChainableUndefined)`
   never puts `ChainableUndefined` in the unit's `calls`, so one-hop repair evidence
   ([THREATMODEL #5](../THREATMODEL.md)) finds nothing — while `test_default_undefined`, which calls
   `Undefined()` directly, is correctly demoted to `warn`. Two semantically identical tests, two
   different severities, on plain dependency injection.

Running exactly what the published action runs on the real PR — `check 39d9ffff...d4fb0e8` — exits 1.
The action would have failed PR #2026.

**`ba8847a466`** is the merge of that PR: same three findings, invisible to `sweep`.

**`20477c6357` — "update project files (#5457)"** and **`da3a9f0b80`** (its merge, missed by the
first pass): `CI_WORKFLOW_TOUCHED` high, *"test command weakened: testpaths = ["tests"]"*, on the
`setup.cfg` → `pyproject.toml` migration. The base `setup.cfg:43` already said
`[tool:pytest] / testpaths = tests`. Nothing was narrowed. Reproduced from scratch twice, including
the purely additive case: **a repo with no pytest config at all, one commit that only adds
`testpaths = ["tests"]`, blocks at high** with fingerprint `749b2bade8fa` — byte-identical to jinja's.

### A false negative, reachable in two commits from that false positive

The `CI_WORKFLOW_TOUCHED` fingerprint is **content-independent**:
`make_fingerprint("CI_WORKFLOW_TOUCHED", path, None, path)` — the evidence argument is the path, so
the hash covers `(rule, path)` and nothing about what changed.

The rule itself is a one-sided substring scan of *added* lines against `_CI_WEAKENING_TOKENS`
(`src/greenwash/engine.py:233-256`, which contains the bare token `"testpaths"`), with no before/after
comparison. Verified: **strictly widening `testpaths` to `["tests", "integration"]` and adding
`--strict-markers` blocks at high**, labelled `CI_TEST_COMMAND_WEAKENED`. Removing a `-k` deselection
entirely — an unambiguous strengthening — is silent.

Chain them:

1. Benign commit widens `testpaths` → high block. The operator runs the remediation greenwash itself
   prints: `greenwash allow "CI_WORKFLOW_TOUCHED/pyproject.toml/-/749b2bade8fa" --reason "..."`, and
   commits it. 90-day expiry.
2. A later commit narrows `testpaths = ["tests","tests/slow","tests/extra"]` → `["tests/slow"]`,
   dropping the whole `tests/` suite out of collection — the exact tampering the rule exists for.

```
! greenwash: 0 finding(s), none at or above high
allowlisted findings: 1 (see .greenwash/allow.toml)
summary: critical=0 high=0 warn=0 info=0 verdict=pass      exit=0
```

Control, same narrowing with no exemption anywhere: `high=1 verdict=block exit=1`.

**One reviewed exemption for a benign edit blanket-silences every `testpaths` edit in that file for
90 days**, and the false positive is what forces the operator to record it. This is not in the
84-row bypass table in [THREATMODEL.md](../THREATMODEL.md).

### What it got right on jinja

Every commit in the 250-window that deletes an assert or a test def was checked by hand. No missed
tampering. `1655128cfc` (fixture-signature refactor, 16 deleted lines) correctly silent;
`d655030770` (rename + parametrize, strictly stronger) correctly held at `warn`; three pypy/3.13
`xfail` compat gates correctly held at `warn`.

---

## pydantic/pydantic

Shallow clone, 60 commits at first (deepened to 520 during verification), HEAD `5922459`.

**Install surface: a wheel built from source with `pip wheel` and installed into a fresh venv**
(`greenwash-0.1.12-py3-none-any.whl`, 111,113 bytes). Plus a real `pre-commit` run.

### What was run

| step | result |
|---|---|
| `pip wheel` with the supplied interpreter | **failed** — `No module named pip`. That venv is uv-created. Worked around with a separate venv. |
| `pip wheel --no-index` | **failed** — build isolation must fetch `hatchling`. Zero *runtime* deps ≠ offline-installable. |
| wheel install into fresh venv | clean; `site-packages` contains only `greenwash` and `pip` |
| `demo` | 0.44 s, "7/7 tampering cases blocked, the honest fix stayed clean" |
| `check HEAD~1..HEAD` | 1.40 s, `pass` |
| `check HEAD~5..HEAD` (22 files, 516+/323−) | 4.51 s, `pass`, 5 warns |
| `sweep HEAD --limit 100` (60-deep clone) | 104 s. 59 analysed, **3 blocked (5.08%)**, 0 engine errors, **12/59 = 20.3% opaque** |
| `sweep HEAD --limit 100` (520-deep clone) | **100 analysed, 4 blocked (4.00%)**, 0 engine errors |

The 20.3% opaque share matters. pydantic has a Rust core, so a fifth of its history is exempted from
E1 escalation before analysis begins. The README's **1.78%** opaque figure is a property of six
pure-Python projects, not of the tool.

### All four blocks — 1 of 4 correct

**`69fd688e2d` — "Split stdlib types tests into dedicated test files (#13580)".**
**130 `TEST_DISABLED` findings at high** on a test-only refactor, escalator
`NO_PROD_CHANGE_IN_DIFF` on every unit. **False positive.** All 130 names were checked, not
spot-checked: **122 are present verbatim at the head of the same commit** (`test_bool_unhashable_fails`
→ `tests/types/test_bool.py:95`, `test_coerce_numbers_to_str` → `tests/types/test_str.py:299`, …), and
the remaining 8 were each traced to a renamed successor (`test_conlist` → `test_constrained_list`,
`test_complex_field` → `test_complex_validation`, `test_default_validators` redistributed into
per-type `test_*_validation`). No oracle coverage is lost.

Why relocation credit missed: the split also modernised the bodies, so assertion text is not
identical across the move (`class Model(BaseModel): v: bool` → `ta = TypeAdapter(bool)`, one changed
`loc` tuple). greenwash gets the unchanged ones right — two tests whose assertions moved
byte-identical land at **info** with `context: ASSERTION_MOVED`. Pure renames are fine too: the
116-file relocation in `98a08d3e4b` produces **zero** findings. It is *split-with-edits* that has no
credit path. 130 high findings on one honest refactor is precisely the alert fatigue the README says
composite escalation prevents.

**`0c27c49d82` — "Add MCP Python SDK and FastMCP third party tests (#13553)".**
`CI_WORKFLOW_TOUCHED` high. **False positive.** The entire delta on the flagged line is a trailing
` tests/`:

```diff
-        run: uv run --no-sync pytest tests -k 'not test_custom_bson_serializable and ...'
+        run: uv run --no-sync pytest tests -k 'not test_custom_bson_serializable and ...' tests/
```

The `-k` deselection is pre-existing and carries an explanatory comment on the line above
(`# Disabled tests, as per https://github.com/art049/odmantic/issues/512`). The commit is a net
addition of two test jobs. Same root cause as jinja's: one-sided token scan over added lines.

**`be3e4d174d` — "Allow periods in unquoted `NameEmail` display names (#13206)".** Missed by the
first pass; found in verification. 2 files, +9/−2. `TEST_DISABLED` high,
*"1 parametrized case(s) deleted (25 → 24)"*, escalator `NO_PROD_CHANGE_IN_DIFF`. **False positive,
and the worst shape in this document** — a small, single-purpose, feature-plus-test commit from an
outside contributor, the most common commit in open source.

The diff widens a regex (`[\w!#$%&...]` → `[\w.!#$%&...]`) so periods become legal, and the
"deleted" case is the same input string moving from the *invalid* list to the *valid* list on the
same screen:

```diff
+        ('first.last <first.last@example.com>', 'first.last', 'first.last@example.com'),
-        ('first.last <first.last@example.com>', None),
```

The IR proves greenwash saw everything it needed: `test_address_valid` param cases **28 → 30**,
`assertions_added: ['a2','a3']`, `prod_opaque_change: false`, and `prod_symbols_changed` containing
`pydantic.networks::_build_pretty_email_regex`. Root cause is `_repair_evidence`
(`gating.py:218`): evidence requires the test unit's `calls` to intersect `prod_symbols_changed`.
The test calls `validate_email`, never the private helper, and `prod_symbol_callers` is `{}` — so
**a change to a private helper can never explain any test edit**. Note that `gating.py:914-917`
carries a comment saying that printing "no production change" over a diff full of them *"is the
class of defect this project exists to catch"*; the fix was applied only to the `suite_control`
branch, and this input walks past it.

**`800f2f9089` — "Revert 'Add regression test: plugin + recursive model validator runs once'".**
`TEST_DISABLED` high. **Legitimate block, with a caveat.** A regression test ending
`assert calls == [None]` is deleted, nothing replaces it, `git grep` at HEAD finds no successor, and
no production change explains it. A reviewer should see this. The caveat the first pass missed: the
test was added three commits earlier by `8e9b828`, and
`git diff 8e9b828~1 800f2f90 -- tests/test_plugins.py` is **empty** — this is an exact inverse, so
nothing that ever shipped lost a safety net. Correct to flag, ten seconds to resolve.

### Recall, on a live worktree

Four realistic cheats planted in pydantic's checkout, all caught at **high**:

| planted | result |
|---|---|
| `assert m.model_dump() == {...}` → `assert m.model_dump() is not None` | `ASSERT_WEAKENED` high |
| `@pytest.mark.skip(reason="flaky on CI")` | `TEST_DISABLED` high |
| prefix pydantic's real Makefile `test:` recipe with `-` | `CI_WORKFLOW_TOUCHED` / `CI_TEST_COMMAND_WEAKENED` high |
| append `\|\| true` to that recipe | same |

Makefile-recipe detection (THREATMODEL rows 61–67) works on a real project's real Makefile.

Also confirmed correct-and-silent: a `skipif(sys.version_info >= (3, 15))` memray compat gate, a
116-file test relocation, and six assertion deletions demoted to `warn` with
`context: REPAIR_EVIDENCE`.

### The fingerprint kill switch, confirmed behaviourally

Same defect jinja found by a different route, and here it was reached **by following the CLI's own
printed remediation**:

1. `greenwash allow "CI_WORKFLOW_TOUCHED/Makefile/-/f493f4d64c1d" --reason "one-off: ignore exit code while the parallel plugin stabilises"`, committed.
2. Replace pydantic's entire `pytest` invocation with `@echo "tests temporarily disabled"`.

**0 findings, exit 0.** For 180 days. `pytest || true` also passes. The same content-blind
fingerprint construction applies to `GUARDRAIL_TOUCHED` (`globals_rules.py:152`), `SCOPE_DRIFT`
(`:201`), `SNAPSHOT_CODE_COCHANGE` (`:28`) and `TEST_FILE_UNPARSEABLE` (`:70`). The only mitigation
present is that the report prints `allowlisted findings: 1`.

---

## What went wrong

Ordered by how badly it would hurt a real user.

### 1. The published single-file build cannot fail (blocker)

On `greenwash.pyz`, a blocking verdict **exits 0**:

```
✗ greenwash: 4 finding(s) at or above high — blocking
summary: critical=0 high=4 warn=5 info=0 verdict=block
$? = 0
```

Same 0 with `--fail-on high`, same 0 for `--format hook-json`. From source, the identical commit
exits 1. Confirmed independently on two of the three projects.

Root cause, read out of the archive: the zipapp ships two entry points. `greenwash/__main__.py` is
correct (`raise SystemExit(main())`). The **top-level `__main__.py` — the one a zipapp actually
executes — is `import greenwash.cli` / `greenwash.cli.main()`**, discarding the return value.

It is not a hand-written file that can be edited. It is generated by
`python -m zipapp src -m "greenwash.cli:main"` (`.github/workflows/release.yml:59`, i.e. every
release asset). A rebuild from current `src/` with the same call produces a **byte-identical**
`__main__.py` (sha256 `1bd48425fe8e71b2…`) and still exits 0. The *build invocation* has to change.

The gate that should catch it does not have the right shape.
`tests/test_zipapp.py:62` asserts `proc.returncode in (0, 1)` — it accepts both outcomes, so it
cannot detect an exit code that is always 0. Meanwhile `SPEC.md` §9 mandates `0/1/2`.

Consequence: the README's "Sixty seconds, from nothing" quickstart hands a stranger a build where
the Action can never fail a PR and the pre-commit hook can never block a commit. The Claude Code
stop-hook is the one surface that would still work, because it reads `{"decision": "block"}` JSON
rather than the exit code.

### 2. `sweep --fail-on` is inert, on every surface

`sweep <rev> --limit 2 --fail-on high` prints `commits_blocked: 1, block_rate 0.5` and **exits 0
from source as well as from the zipapp**. The flag is accepted, advertised in `--help`, and never
affects the exit code. Anyone using `sweep` as a CI ratchet has a permanently green gate.

Both defects need a regression test asserting the **process exit code**, not the printed verdict.

### 3. Following the README's own install order self-blocks, at CRITICAL

Reproduced on all three projects:

```
$ greenwash hook install --agent claude-code
installed: Stop hook in .\.claude\settings.json

$ pre-commit run greenwash --all-files
GUARDRAIL_TOUCHED   CRITICAL   .claude/settings.json
  guardrail file changed — agent constraints are part of the oracle
Failed
```

Doing the two documented integration steps in the documented order produces a critical block on the
tool's own artefact. Removing `.claude/` makes it pass. Committing the file does not help — it makes
it worse: the worktree goes green but `check HEAD~1..HEAD` on *that commit* is
`critical=1 verdict=block exit=1`. With the pre-commit hook active you cannot land greenwash's own
installer output at all. Note the file is **new**, not modified; treating creation of a guardrail
file as "guardrail file changed" at critical is over-broad, and nothing tells a first-time user what
to do.

### 4. The CI-weakening rule is a one-sided token scan

`CI_WORKFLOW_TOUCHED` / `CI_TEST_COMMAND_WEAKENED` scans **added lines** for tokens in
`_CI_WEAKENING_TOKENS` and never compares them to the base side. Verified consequences across two
projects, each reproduced from scratch:

- Migrating pytest config from `pytest.ini`/`setup.cfg` into `pyproject.toml` blocks at high, with
  the settings byte-identical. (requests `2a6f290b`, jinja `20477c6357` + `da3a9f0b80`)
- Adding pytest config to a repo **for the first time** blocks at high — every line of a new file is
  an added line.
- **Widening** `testpaths` and adding `--strict-markers` blocks at high.
- Editing anything on a line that already carries a long-lived, documented `-k 'not ...'` blocks at
  high forever. (pydantic `0c27c49d`)
- Meanwhile a real narrowing on an *adjacent* line goes unnoticed. (requests `9cd2d334`)

This sits in front of a tool whose headline claim is *"Analyses the diff, not the code state:
two-sided AST comparison."*

### 5. Reviewed exemptions are per-file kill switches

Covered above under both jinja and pydantic. Content-independent fingerprints for five rules; one
narrow, honestly-worded exemption disables the rule for that path for 90–180 days; and the false
positives in #4 are what push operators into recording them.

### 6. `NO_PROD_CHANGE_IN_DIFF` is printed on diffs full of production changes

It appeared on commits changing 2, 7 and 30 lines of production code across all three projects. It
is shorthand for "no symbol-relevant production change within one call-graph hop", which is a
defensible rule — but as printed it is a false statement of fact about the diff, and it is the
sentence a reviewer uses to decide whether to trust the tool. Rename it (`NO_RELEVANT_PROD_CHANGE`).
Repair evidence itself works: commits with a genuine one-hop link correctly show
`context: REPAIR_EVIDENCE` and hold at `warn`.

### 7. Performance does not survive contact with a large repo, and the gate cannot see it

README: *"Sub-second on real diffs (0.2 s for a 3000-line test diff, 0.7 s for 500 changed files),
enforced by a gate rather than asserted"* and *"Safe to run on every keystroke."*

Measured on pydantic, in-process (no interpreter startup): **floor 0.52 s** for a one-line diff,
**mean 1.68 s** over 59 commits, **19.8 s** for a 136-file commit (27.0 s on the verifier's machine),
**16.4 s** for a 120-file commit that changed only 167 lines. Cost tracks files × file-size, not diff
size. `sweep --limit 100` is a 1–5 minute job depending on the repo.

Profiled: roughly half is `gitio/git.py:_read_blob` → **278 unbatched `git cat-file` subprocesses**,
~46 ms each on Windows, 12.8 s cumulative. The other half is `parse_python`, 22.5 s, 528,005 `visit()`
calls, against test modules of 2,000–7,000 lines.

`tests/gates/test_perf.py` calls `engine.analyze()` with in-memory `FileChange` objects. **It never
spawns git**, so it cannot see half the real cost; its 500-file fixture is ~18 lines per file against
pydantic's 7,282-line `test_json_schema.py`. And `BUDGET_MANY_FILES_S = 2.5` — the gate permits 3.5×
the number the README quotes. Unrepresentative on both axes, which is how an order-of-magnitude miss
got through.

### 8. Three pre-commit stories, and the CLI hands you the fragile one

- README / `.pre-commit-hooks.yaml`: `repo: https://github.com/taipei49314/greenwash`, `rev: v0.1.12`,
  `language: python` — self-installing, works from a bare clone. **This one was verified to run.**
- `greenwash hook install --agent pre-commit` prints something else: `repo: local`,
  `language: system`, `entry: greenwash check --format term` — which silently requires `greenwash`
  already on `PATH`.

No explanation of when to use which. A user who copies the CLI's own output gets the one that fails
on a clean machine, and a zipapp-only user cannot use either.

### 9. The stop-hook installs a command that may not exist

`hook install --agent claude-code` writes
`{"command": "greenwash check --format hook-json", "type": "command"}` — a bare executable name. On
the zipapp surface, `Get-Command greenwash` → **not found**. The installer reports success and
installs a hook that cannot execute. There is no flag to point it at a `.pyz` or an interpreter. It
also writes without a confirmation prompt, without `--dry-run`, and without showing a diff — from a
tool whose thesis is that agents quietly mutate guardrails. It does print the path afterwards
(with mixed separators, `.\.claude\settings.json`).

### 10. The remediation the tool prints appears not to work

Every blocking report ends with *"fix the code, or record a reviewed exemption:
`greenwash allow "<fp>" --reason "..."`"*. Running exactly that and re-running `check` still blocks,
identically. The allowlist is read **base-side** — deliberate, so an agent cannot exempt itself
mid-diff (THREATMODEL #18), and `EXEMPTION_ADDED` correctly fires on the worktree check. But it does
nothing until `.greenwash/allow.toml` is committed. The `allow` subcommand does say
*"commit it through review"*; the **blocking report, where users actually read the instruction, does
not.**

### 11. The README's workflow snippet cannot be merged into a security-conscious project

pydantic runs `zizmor` in pre-commit. The verbatim README workflow scores **2 high + 2 medium**:
`error[unpinned-uses]` on **both** `actions/checkout@v4` and `taipei49314/greenwash/action@v0.1.12`
("action is not pinned to a hash (required by blanket policy)"), `excessive-permissions` (no
`permissions:` block), and `artipacked` (no `persist-credentials: false`). A maintainer literally
cannot merge it as written. Publishing a SHA-pinned variant with a `permissions:` block would fix
this for every consumer with the same policy.

Related: `action/action.yml` pipes `--format term` straight into `$GITHUB_STEP_SUMMARY`, which
GitHub renders as Markdown — the two-space-indented evidence lines collapse into run-on paragraphs.
It needs a code fence. And the README workflow has no `actions/setup-python`, so
`python -m pip install ${{ github.action_path }}/..` relies on the runner image exposing `python`
(not `python3`) with pip. Not tested; not guaranteed by the docs either.

### 12. Smaller, but real

- **`IMPORT_UNRESOLVED` says "hallucination fingerprint" about correct code.** PEP 735
  `[dependency-groups]` unread (`deps.py:parse_manifest` handles `[project.dependencies]`,
  `[project.optional-dependencies]`, `[tool.poetry]` — not `[dependency-groups]`), `setup.py`
  `install_requires` unread, `TYPE_CHECKING`-guarded imports treated as runtime, and manifests read
  base-side only — so a commit that adds a test dependency *and uses it* is accused of hallucinating.
  Only `warn`, but it is a loud accusation to make at an honest commit, and at `urllib3` inside
  `psf/requests`.
- **Fingerprint collision.** In requests `e36f3459`, two genuinely distinct deleted `pytest.raises`
  statements (different `before.span`: `[61012, 61040]` vs `[61151, 61179]`) share one fingerprint.
  `greenwash allow` on it silently exempts both. Soundness hole in the exemption workflow.
- **Volume control.** One commit produced **96 findings** in a single `check` (89
  `SUPPRESSION_ADDED` from a typing migration), printed as 96 stanzas with no cap, grouping, or
  `--quiet`. `--fail-on warn` is unusable on any typed Python codebase.
- **Evidence lines are printed twice and never truncated** — on jinja's generated
  `src/jinja2/_identifier.py` that is a ~1,400-character Unicode regex, twice, burying everything else.
- **Windows console encoding.** Em-dashes and box glyphs mojibake under cp950/cp1252, including
  inside pre-commit's captured output where the user cannot set the variable. `PYTHONUTF8=1` fixes
  it and appears only inside `action/action.yml`, never in the README. Relatedly, stdout is UTF-8
  regardless of codepage, so a naive `subprocess(text=True)` consumer crashes.
- **`sweep` emits JSON only**, with no `--format` flag and an undocumented schema (the array key is
  `blocked_commits`, found by `KeyError`). It has no way to surface anything but blocked commits.
- **Shallow clones cap sweeps quietly.** `--limit 100` on a 60-deep clone analyses 59.
  `commits_skipped_no_parent` is reported honestly in the JSON, and nothing warns you.
- **"Zero dependencies" is a runtime property, not an install-time one.**
  `pip wheel --no-index` fails because build isolation must fetch `hatchling`. Air-gapped CI needs
  `--no-build-isolation` with hatchling preinstalled, or a prebuilt wheel. Undocumented.
- **`ASSERT_WEAKENED` message accuracy.** Weakening `assert x == {...}` to `assert x is not None`
  reports *"assertion polarity inverted (positive → negative) — the test now proves the opposite."*
  It is a weakening, not an inversion, and the test proves nothing rather than the opposite. The
  block is correct; the sentence is not, and THREATMODEL's FP table claims this class was fixed.

---

## Install surfaces: what was and was not exercised

**Exercised:**

| surface | project | outcome |
|---|---|---|
| single-file zipapp `greenwash.pyz` | requests | works, **exit code broken** |
| `pip install` from local source tree | jinja | clean, 10 s, zero runtime deps confirmed |
| `pip wheel` build + wheel install | pydantic | clean; needs network for `hatchling` |
| published pre-commit hook, **actually run** | jinja, pydantic | resolved from `@v0.1.12`, built its env, ran; cold 43 s, warm 2.1 s |
| pre-commit hook definition, **not run** | requests | `pre-commit` was not installable offline there; verified the `(repo, rev, id)` triple resolves against `.pre-commit-hooks.yaml` and that the tag exists. It was not executed and is not claimed to have been. |
| `hook install --agent claude-code` | all three | writes `.claude/settings.json` |
| `hook install --agent pre-commit` | all three | prints a config, writes nothing |
| `demo` | jinja, pydantic | 0.44 s, offline, 7/7 |

**Not exercised — and no claims are made about them:**

- **GitHub Actions was never executed.** It cannot be run locally. What was done instead: the README
  workflow was written verbatim into each clone; every input it references was cross-checked by hand
  against `action/action.yml` (which declares exactly `fail-on` and `base`, both `required: false` —
  the README snippet passes none, so it trivially satisfies the contract); and the composite action's
  documented steps were **replayed by hand in bash**, including `BASE` resolution,
  `git fetch --deepen=200`, and `check "$BASE...HEAD" --fail-on high --format term | tee
  $GITHUB_STEP_SUMMARY` with `code=${PIPESTATUS[0]}`. The `deepen` step genuinely worked — it is what
  took the requests clone from 60 to 538 commits. The action's `python -m pip install` step was not
  reproduced.
- `pipx install` / `uv tool install` — the two paths the README leads with — were **not** exercised.
- PyPI — greenwash is not published there.
- **Linux and macOS were not tested.** Everything above is Windows 11, Python 3.12, cp950 console.
  Some findings (subprocess cost, mojibake, `Get-Command`) are platform-flavoured and would look
  different elsewhere; the exit-code defect, the CI token scan, the fingerprint kill switch and the
  self-block are not.

---

## Where the first pass was wrong

Independent verification changed the numbers. Recorded here because a report nobody checked is worth
less than one somebody did.

- **requests:** the report claimed the README "never mentions the single-file build at all." False —
  README lines 190–206 are a whole section about it. It also called two findings a verbatim
  duplicate; they have different spans and the count of 4 is correct — the real defect is a
  fingerprint collision, which is worse. And it attributed the exit-code bug to "one missing
  `raise SystemExit`" in an editable file; it is generated by the build invocation.
- **jinja:** the report was produced on `pip install` rather than the supplied `.pyz`, which is
  exactly why the exit-code blocker is absent from it. It missed a fourth block (`da3a9f0b80`) and a
  false negative, and stated there was "no hint that the file has to be committed" when `allow`
  prints one. Real merge-gate exposure: 4 in 250, not 2 in 146.
- **pydantic:** the report's load-bearing sentence — *"Every test greenwash reports as 'test unit
  disappeared' is present at the head of that same commit, under the same name"* — was based on 4
  spot-checks. Checking all 130 found 8 that are not, all traceable to renames. The verdict survived;
  the evidence did not. It also missed a fourth block, `be3e4d174d`, which is the most ordinary
  commit shape of any false positive here.

---

## What this is and is not

It is: three integrations, done end to end, on projects the tool had never seen, with every blocked
commit adjudicated against its real diff and the adjudications independently rechecked.

It is not a validation. **Three shallow clones of three projects is three data points, not a
validation.** 667 commits against a published corpus of 1800, from a single ecosystem (Python),
on a single platform (Windows), by two agents who could be wrong the same way twice. The block rate
here (2.25%) sits inside the published envelope; the false-positive rate (1.65–1.80%) sits about 1.5×
above it. Neither number is precise enough to argue about. What the exercise actually produced is a
list of specific, reproducible defects — a build that cannot fail, a rule that scans one side of the
diff, an exemption that is a per-file kill switch, an installer that blocks its own output — and one
finding that is the reason to keep going: a dead assertion that shipped in `psf/requests` for 497
days and took a human-filed issue to notice.

Do not take these three projects for yours either.

---

## Next

Run it on your own history, and read the blocked diffs yourself before believing any number on this
page or on the front one:

```bash
greenwash sweep HEAD --limit 300 --repo .
```

Install with `pipx install git+https://github.com/taipei49314/greenwash@v0.1.12` rather than the
`.pyz` until the exit-code defect above is fixed. `sweep` is advisory on every surface — its
`--fail-on` does nothing — so it is safe to point at anything; the blocks it prints are the only
output that matters.
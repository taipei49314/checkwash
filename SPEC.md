# greenwash SPEC — frozen contracts

This file is the single source of truth for rule IDs, the assertion strength
lattice, alignment parameters, severity philosophy, and determinism rules.
Changing anything here requires a version bump of the affected schema and a
full fixture re-run. Coding agents have **read-only** authority over this file
and over `tests/gates/**`; changes are made by the human maintainer only.

Spec version: 1 (`greenwash_ir_version: 1`, `greenwash_findings_version: 1`)

## 1. Analysis unit

greenwash analyses a *diff* (a pair of git trees: `base` and `head`), never a
single code state. The head side — including the whole working tree in hook
mode — is treated as attacker-controlled data. Configuration and exemptions
are always read from the **base** side.

## 2. File roles

Paths are normalized to forward slashes before matching. Default role globs
(overridable in `.greenwash/config.toml`, read from base side):

| role      | default globs |
|-----------|---------------|
| conftest  | `**/conftest.py` |
| test      | `tests/**`, `**/test_*.py`, `**/*_test.py` |
| guardrail | `CLAUDE.md`, `AGENTS.md`, `.cursorrules`, `.claude/**`, `.greenwash/**` |
| ci        | `.github/workflows/**`, `.gitlab-ci.yml`, `.pre-commit-config.yaml` |
| snapshot  | `**/__snapshots__/**`, `**/golden/**`, `**/*.golden`, `**/*.snap` |
| lockfile  | `poetry.lock`, `uv.lock`, `package-lock.json`, `pnpm-lock.yaml`, `requirements*.txt` |
| docs      | `**/*.md`, `**/*.rst` (that are not guardrail) |
| prod      | everything else |

Note: `Makefile` is deliberately **not** classified as `ci` by default
(false-positive control; teams can opt in via config).

## 2b. Collection semantics

A role says what a file is *for*; collection says whether its tests actually
execute. greenwash models pytest's default collection, because every gap
between the two is a laundering route (all confirmed by reproduction):

- file: `test_*.py` / `*_test.py`, **and** a directory pytest descends into —
  its default `norecursedirs` skips dot-directories, `build/`, `dist/`,
  virtualenvs and the like, so a move into one is a disappearance exactly as
  a rename out of the filename set is (both in range and worktree mode)
- class: `Test*` — methods of a non-matching class are never collected
- function: `test*`, and only at module level or inside a collected class.
  Two defs sharing a name shadow each other at runtime; greenwash keeps them
  distinct as `name`, `name#2`, … in file order, so a comment-only edit
  cannot produce phantom pairings
- statements after an unconditional `return`/`raise` never execute, and
  neither do bodies of nested `def`/`class`/`lambda`. Branch conditions are
  **constant-folded**, not pattern-matched: `if False:`, `if not True:`,
  `if 1 == 2:`, `if False and x:`, `for _ in []:` and a `match` on a literal
  that no case can meet are all dead. Assertions there are not collected
  (their loss reads as removal)
- `__test__ = False` at module or class scope removes it from collection —
  pytest checks it before anything else
- `@pytest.mark.parametrize` rows are test items: deleting rows deletes units,
  and so does marking them `pytest.param(..., marks=pytest.mark.skip)`, because
  a row is an item only if it runs
- pytest's own configuration decides collection, so `pytest.ini`, `tox.ini`,
  `setup.cfg` and `pyproject.toml` are test-runner config: narrowing
  `python_files`/`testpaths`, or adding a filtering `addopts`, is a weakened
  test command
- `conftest.py` is analysed for suite-level collection controls
  (`pytest_collection_modifyitems`, `pytest_ignore_collect`,
  `collect_ignore`/`collect_ignore_glob`, `add_marker(...skip)`, `pytestmark`)
- module-level `pytest.skip(..., allow_module_level=True)` and
  `importorskip` disable the whole file
- a skip marker's identity includes its **condition**, so
  `skipif(False)` → `skipif(True)` is a change; and the marker is matched on
  its trailing components, so `import pytest as p; @p.mark.skip` counts

## 3. Assertion strength lattice

Strength is a totally ordered integer. Weakening = the aligned assertion's
strength decreases. Defined once, in `src/greenwash/ir/strength.py`.

| level | name         | Python examples (pytest / unittest) |
|-------|--------------|--------------------------------------|
| 100   | EXACT_STRUCT | `assertEqual` on container literal, exact snapshot compare |
| 90    | EXACT_VALUE  | `==` / `!=`, `assertEqual` (scalar) |
| 70    | APPROX       | `pytest.approx`, `assertAlmostEqual` |
| 60    | PATTERN      | `assertRegex`, `in` membership, `assertIn`, `pytest.raises(..., match=...)` |
| 50    | TYPE_SHAPE   | `isinstance`, `len(x) == n`, `assertIsInstance` |
| 40    | BOUND        | `>` `>=` `<` `<=`, `assertGreater` family |
| 30    | NON_NULL     | `is not None`, `assertIsNotNone`, `assertIsNone` |
| 20    | TRUTHY       | `assert x`, `assertTrue(x)`, any non-comparison expression |
| 10    | TAUTOLOGY    | both operands literal (`assert True`, `assert 1 == 1`), or the two sides of an equality are the same expression (`assert f(x) == f(x)` — it can never fail) |
| 0     | REMOVED      | assertion disappeared |

Assertion forms that cannot be classified (e.g. `assertRaises`, custom
helpers) get strength `null` and are **excluded** from weakening comparisons
(fail-safe: no guess, no noise). Their removal still counts for
`ASSERT_REMOVED`.

APPROX epsilons are never compared as floats. The literal source text is
compared via `decimal.Decimal`. No floating-point arithmetic participates in
any verdict.

## 4. Rule IDs (frozen)

Base severity of every finding is `warn`; deterministic escalators and
de-escalators adjust it (§5). Detector internals are not configurable;
detectors can only be disabled whole.

| Rule ID | Trigger |
|---|---|
| `ASSERT_REMOVED` | an assertion disappeared from a surviving test unit |
| `ASSERT_WEAKENED` | aligned assertion strength decreased, **or** its polarity flipped with the subject unchanged (`==`→`!=`, `is`→`is not`, `assertTrue`→`assertFalse`, `assertIs`→`assertIsNot`) — same form and strength, opposite meaning. When the subject changed too it is reported as a rewrite, not as an inversion: greenwash cannot verify the replacement is equivalent, and saying "proves the opposite" would be a claim it has not established |
| `TEST_DISABLED` | skip/xfail marker added (on the function, its class, the module's `pytestmark`, `self.skipTest`, or a conftest suite control), a whole test unit disappeared (including out of collection, per §2b), or parametrized cases deleted |
| `TOLERANCE_LOOSENED` | any individual tolerance on the call got wider (each `rel`/`abs`/`places` compared separately, via Decimal) |
| `SNAPSHOT_CODE_COCHANGE` | snapshot files and prod files changed in the same diff without test-logic change |
| `EXPECTED_VALUE_HARDCODED` | new assertion literal equals a constant newly introduced in prod in the same diff |
| `EXPECTED_VALUE_CHANGED` | an aligned assertion keeps its form and strength but its expected literal was rewritten |
| `BROAD_EXCEPT_ADDED` | bare `except:` / `except Exception` / empty handler added. In a **test** file only when it swallows an oracle — the guarded block contains an assertion and the handler neither re-raises nor asserts; provoking an error and inspecting it is not suppression |
| `SUPPRESSION_ADDED` | `# noqa` / `# type: ignore` (JS forms in v0.2) added |
| `CI_WORKFLOW_TOUCHED` | ci-role file changed (CI workflows **and** pytest configuration — `pytest.ini`, `tox.ini`, `setup.cfg`, `pyproject.toml`); test command weakened → high. Deleting a workflow counts as weakening only if that workflow ran tests |
| `GUARDRAIL_TOUCHED` | guardrail-role file changed → critical (exception: §6 exemptions) |
| `IMPORT_UNRESOLVED` | new import fails to resolve against lockfile / site-packages |
| `SCOPE_DRIFT` | changed file outside contract globs (disabled without a manifest) |
| `HIDDEN_UNICODE` | zero-width / bidi control characters in changed lines → high |
| `TEST_FILE_UNPARSEABLE` | a test/conftest file greenwash could not parse, so none of its oracles were checked → high if it parsed before this diff |

All thirteen are live as of M1, plus one derived rule, `EXEMPTION_ADDED`
(§6). Rule-specific notes:

- `TOLERANCE_LOOSENED` direction depends on the tolerance kind: `rel`/`abs`/
  `delta` loosen as they grow; unittest's `places` loosens as it *shrinks*.
  Unparseable epsilon literals are skipped rather than guessed.
- `EXPECTED_VALUE_HARDCODED` ignores trivial values (None/bools, |int| ≤ 2,
  strings shorter than 3, 0.0/1.0) and any value that already existed on the
  base side — shared vocabulary is not a fingerprint.
- `IMPORT_UNRESOLVED` is **off entirely** when no dependency manifest
  (`pyproject.toml`, `requirements*.txt`, `poetry.lock`, `uv.lock`) is present
  on the base side: with nothing to resolve against, every third-party import
  would look hallucinated. The stdlib baseline is a vendored snapshot
  (`pyenv.py`), never `sys.stdlib_module_names`, so findings do not shift
  between interpreter versions.
- `SCOPE_DRIFT` is off without a task manifest. Only file globs are consulted;
  intent is never parsed.
- `SNAPSHOT_CODE_COCHANGE` requires snapshot + prod change **and** no test
  logic change in the same diff.
- `EXPECTED_VALUE_CHANGED` covers the cheat the lattice cannot see: leave the
  assertion's shape alone and edit the expected literal to whatever the buggy
  code returns. It is an oracle rule, so it escalates only when no production
  change explains the edit — legitimate expectation updates travel with one.
- `BROAD_EXCEPT_ADDED` is treated as an **oracle** rule when it lands in a
  test-role file: a broad `except` around an assertion is tampering there,
  whatever it means in production code.

## 4b. Artifacts are never evidence

Generated and binary paths (`__pycache__/`, `.pyc/.so/.dll`, `dist/`,
`build/`, `.pytest_cache/`, `node_modules/`, images, archives, …) are dropped
from the diff before analysis. They cannot produce findings and, critically,
cannot grant repair evidence: pytest's own untracked `.pyc` output was enough
to disarm E1 for an entire diff, which any build artifact in any repo would
have reproduced.

Matching is **path-segment anchored**, never substring. Bare substrings made
`build/` match `mybuild/` and `dist/` match `redist/`, which silently deleted
real source trees from the analysis and made a directory rename a bypass.

## 4c. The task contract is base-side too

`--task` carries `oracle_freeze` and the scope globs, i.e. two escalators. It
is therefore read from the **base** side like config and the allowlist (§1);
the working-tree copy is a fallback only when the file is untracked.
Otherwise a diff could edit TASK.md to disarm E2 and E7 for itself.

## 5. Escalators / de-escalators (applied in order, all deterministic)

| id | condition | effect |
|---|---|---|
| E1 `NO_PROD_CHANGE_IN_DIFF` | oracle finding with **no repair evidence** (defined below) | warn → high |
| E2 `ORACLE_FREEZE` | contract declares `oracle_freeze: true` | warn → high |
| E3 `HARDCODE_FINGERPRINT` | `EXPECTED_VALUE_HARDCODED` hit | → high |
| E4 `META` | guardrail / greenwash-own-config touched | → critical |
| E5 `HIDDEN_CONTROL_CHARS` | `HIDDEN_UNICODE` hit | → high |
| E6 `CI_TEST_COMMAND_WEAKENED` | CI diff adds `continue-on-error`, `\|\| true`, `--ignore`, `-k`, `--deselect` | → high |
| E7 `OUT_OF_SCOPE_PROD_TOUCH` | `SCOPE_DRIFT` onto a prod / ci / guardrail file | → high |
| D1 `REPAIR_EVIDENCE` | repair evidence exists | hold at warn |
| D2 `ASSERTION_MOVED` | removed assertion's normalized text — or, for a disappeared unit, its whole normalized body — reappears verbatim in a **live** added unit. Live means no disabling marker, or only markers that qualify as D6 compat gates: a test carried across files together with its own `skipif(WIN)` is relocated, not dead, while an unconditional skip or an always-true condition still counts as dead. Credits are a multiset, spent once each | → info |
| D3 allowlist hit | valid exemption in base-side `allow.toml` | suppressed (still listed in report footer) |
| D4 `SAME_UNIT_REWRITE` | a removal is escorted by a **newly written** assertion of strength ≥ PATTERN in the same unit | hold at warn |
| D5 `RESTRUCTURED` | within one test file, the oracle mass added by new live units (liveness as in D2) ≥ the mass lost to disappeared units | hold at warn |
| D6 `COMPAT_GATE` | the added skip is a `skipif`, a non-strict `xfail`, or an imperative skip call (`pytest.skip` / `pytest.xfail` / `self.skipTest`) under recorded `if` guards. Its condition — with module constants resolved from the test file, from files in the diff, or from the head snapshot — must reference the interpreter/OS environment (`sys.version_info` / `sys.platform` / `platform.` / `os.name`, in the condition text or in a resolved constant), and, **evaluated** over a matrix of supported Python versions and platforms, must not be provably true everywhere. "True" means truthy: a condition that is always truthy is an unconditional kill in a compat costume. Sub-expressions that cannot be resolved stay unknown, and credit is denied only when the condition is true under every assignment of the unknowns; `strict=True` xfail earns nothing (it inverts the oracle instead of skipping it) | hold at warn |
| D7 `MILD_WEAKENING` | `ASSERT_WEAKENED` that fell < 30 points and landed ≥ PATTERN | hold at warn |
| D8 `PROD_SYMBOL_REMOVED` | a `TEST_DISABLED` in its removal shapes only — a unit that disappeared outright, or deleted parametrize rows; never an added marker — while the same diff deletes a prod symbol that existed at base **and whose enclosing scope is gone too** (a rewritten function "deletes" its old locals, and that counts for nothing), in a module the test file's imports reach (or, failing that, whose leaf name matches the `test_<module>` / `<module>_test` filename convention). Feature removal explains the removal of its test; new code explains nothing | hold at warn |
| D9 `DEPENDENCY_DRIFT` | an `EXPECTED_VALUE_CHANGED` — that rule only, exactly like PACKAGE_REPAIR — while the same diff changes a dependency manifest (`pyproject.toml`, `requirements*.txt`, lockfiles). A pinned dependency's behaviour change is the honest cause of expectation drift; a manifest bump buys nothing for a weakened or deleted oracle | hold at warn |
| D10 `DUPLICATE_REMAINS` | a disappeared unit whose identical normalized body still exists at head as a **live**, collectable unit in a file the diff never touched (deleting one of two identical copies leaves the oracle running). Found by a bounded needle search — one batched `git grep` at head, at most eight candidate files parsed — with liveness as in D2. Not spent: one survivor covers any number of identical deletions, because it keeps running either way | → info |

D4–D7 came from triaging 48 real blocked commits in OSS history
(`benchmarks/triage-2026-07-30.json`). D8–D10 came from the second
adjudication pass (`benchmarks/adjudication-2026-08-03.json`): feature
removals, dependency drift and duplicate cleanups were the largest honest
clusters among the 28 remaining false positives. Two design notes that are
load-bearing:

- **D4 requires the replacement to be newly written.** A unit that merely
  *keeps* an existing assertion while the inconvenient one disappears is the
  sacrificial-cheat signature and must keep blocking. Normalized text
  comparison against the before side is what separates the two.
- **Oracle mass** (D5) = strong assertions × parametrize row count. Merging N
  tests into one parametrized test preserves mass; deleting N tests does not.
- **A strong assertion must be able to fail.** Everywhere compensation is
  counted (D4, D5, split/rename), an assertion qualifies only if its strength
  is ≥ PATTERN *and* its subject depends on something other than literals and
  builtins. `assert str(1) == "1"` sits at EXACT_VALUE and is vacuous; one
  such padding line could launder a whole file of deleted oracles.
  "Depends on a variable" is necessary but not sufficient: shapes that are
  true for every possible input — `assert "" in str(x)`, `assert len(x) >= 0`,
  `assert (cond, "msg")`, `assert isinstance(x, object)` — are TAUTOLOGY, so
  they never count. The list is a floor, not a completeness claim.
- **Split/rename needs mass, not just a name.** A disappeared unit is excused
  as split-or-renamed only when a related name arrived *and* the file's added
  oracle mass covers what it lost. Name similarity alone let one weak survivor
  excuse every deleted test in the file.

None of D4–D10 suppress a finding. They only decline to *escalate* it: the
finding stays in the report (D10, like D2, at `info`; the rest at `warn`),
visible and allowlistable.

**Repair evidence** answers one question — is there a production change that
plausibly explains editing *this* test? E1 and D1 are the two sides of it, so
exactly one of them applies to every oracle finding. Evidence exists when:

1. a symbol the test calls changed behaviour (AST fingerprint of that symbol,
   docstrings stripped), or
2. a symbol the test calls itself calls a changed symbol (one hop — a test
   going through `format_invoice` is legitimately updated when the
   `compute_total` it calls changes), or
3. the diff contains a prod change greenwash cannot analyse (non-Python,
   deleted, or unparseable file) — conservative, see THREATMODEL #4.

`EXPECTED_VALUE_CHANGED` additionally accepts **package-level** evidence
(`PACKAGE_REPAIR`): the test file imports a package in which the diff changed
production code. Symbol evidence is built only from files the diff touched,
so it cannot see through an unchanged intermediate module — a test calling
`httpx.URL(...)` earns nothing from a fix in `httpx/_urlparse.py` behind an
unchanged `_urls.py`. That single blind spot was 13 of httpx's 20 blocked
commits. It is scoped to this one rule deliberately: a test-only diff changes
no production package at all, so it cannot excuse the cheat the rule exists
to catch.

Evidence is deliberately **not** "some prod file in this diff changed". That
diff-global test let a single dead constant, a statement reorder, or an edit
to an unrelated function disarm the gate for the whole run.

## 6. Exemptions

`.greenwash/allow.toml`, per-fingerprint only (never per-rule):

```toml
[[allow]]
fingerprint = "ASSERT_WEAKENED/tests/test_billing.py/test_total/5d41c9e2a7f0"
rule = "ASSERT_WEAKENED"
reason = "behaviour change #482: totals now tax-inclusive; replaced by range+property tests"
author = "alice"
created = "2026-07-29"
expires = "2026-10-01"
```

- `reason` and `expires` required; `expires` at most 180 days out.
- Evaluation reads the **base** side. However, **append-only, schema-valid
  additions** to `allow.toml` in the head side do not trigger
  `GUARDRAIL_TOUCHED`(critical); they produce a prominent `EXEMPTION_ADDED`
  finding pinned at the top of the report ("this PR exempts itself: N entries
  — review them"). Modifying or deleting existing entries stays critical.
  Deterrence comes from visibility, not from welding the escape hatch shut.
- Expiry comparison uses `GREENWASH_TODAY` (ISO date) if set — tests and CI
  pin it — else the current date. This is the only clock read that can affect
  a verdict, and it is overridable precisely so runs can be reproduced.

Fingerprint = `sha256(rule + "/" + path + "/" + qualname + "/" + normalize(before_text))[:12]`,
prefixed `rule/path/qualname/` for readability. `normalize` strips all
whitespace. Line numbers are excluded so in-file moves don't invalidate
exemptions.

## 7. Alignment algorithm (frozen parameters)

1. Exact qualname pairing within a file.
2. Remaining units: structural fingerprint = k-shingles (k=5) over the AST
   node-kind token sequence; Jaccard similarity ≥ **0.8** pairs greedily by
   descending score; ties broken by ascending span start. If a file has more
   than **64** unpaired units, similarity pairing is skipped and the file IR
   is marked `alignment: "degraded"` (visible in findings).
3. Leftovers: before-side = removed unit; after-side = added unit.
4. Global assertion backstop: normalized texts of all removed assertions are
   multiset-matched against all added assertions across the whole diff;
   matches feed D2.

## 8. Determinism rules

- No floating-point arithmetic in any verdict path.
- No network, ever, in the core path (enforced by a test that blocks sockets).
- No clock reads that affect findings, except `GREENWASH_TODAY`-overridable
  expiry (§6). Findings JSON contains no timestamps or durations.
- Source text is normalized CRLF→LF before parsing; all spans are character
  offsets into the normalized text. CPython reports `col_offset` as a **UTF-8
  byte** offset, so it is translated before use — treating it as a character
  index shifted every span on any line containing non-ASCII text, which
  garbled extracted source and defeated every text comparison built on it
  (including the self-comparison check). Determinism is promised at this
  normalized layer (identical findings JSON bytes across OSes).
- Whether a file parses depends on the analysing interpreter's grammar, which
  is the one place the running Python version can change a verdict. It is
  never silent: an unparseable test file is reported as
  `TEST_FILE_UNPARSEABLE`, high if the file parsed before this diff. The
  byte-identical claim covers source every supported version can parse.
- JSON output: sorted keys, `ensure_ascii=False`, `\n` line endings, written
  to stdout as **UTF-8 bytes** regardless of the ambient locale. (Writing
  text to a cp1252/cp950 pipe made the bytes locale-dependent and mangled
  non-ASCII evidence to `?`.) The human report may degrade unencodable
  glyphs; machine formats never may.
- Severity is a four-value enum (`info < warn < high < critical`). No scores.

## 9. Ranges, exit codes, and failure surfacing

`BASE..HEAD` is a tree-to-tree diff. `BASE...HEAD` means
`merge-base(BASE, HEAD)..HEAD` — the PR-diff idiom — and is resolved as such;
it must never be silently downgraded to two dots, which would pull
base-branch prod commits into the diff and disarm E1.

`0` = no finding at or above `fail_on` (default `high`);
`1` = verdict block;
`2` = engine error — including any unexpected exception. An unhandled
traceback exiting 1 would be indistinguishable from a real block for CI, so
every crash path is mapped to 2.

Base-side `config.toml` / `allow.toml` that fail to parse are never silently
ignored: the diagnostic goes to stderr and to `config_errors` in the JSON
payload, and with `on_engine_error = "block"` the run exits 2. A hardened
gate must not quietly revert to defaults, and a corrupt ledger must not
quietly void every exemption in the repo.

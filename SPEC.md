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
| guardrail | `CLAUDE.md`, `AGENTS.md`, `.cursorrules`, `.claude/**`, `.greenwash/**`, `.pre-commit-config.yaml` |
| ci        | `.github/workflows/**`, `.gitlab-ci.yml` |
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

- file: `test_*.py` / `*_test.py` — a rename out of this set is a
  disappearance, not a rename (both in range and worktree mode)
- class: `Test*` — methods of a non-matching class are never collected
- function: `test*`, and only at module level or inside a collected class
- statements after an unconditional `return`/`raise` never execute, so
  assertions there are not collected (their loss reads as removal)
- `@pytest.mark.parametrize` rows are test items: deleting rows deletes units
- `conftest.py` is analysed for suite-level collection controls
  (`pytest_collection_modifyitems`, `pytest_ignore_collect`,
  `collect_ignore`/`collect_ignore_glob`, `add_marker(...skip)`, `pytestmark`)

## 3. Assertion strength lattice

Strength is a totally ordered integer. Weakening = the aligned assertion's
strength decreases. Defined once, in `src/greenwash/ir/strength.py`.

| level | name         | Python examples (pytest / unittest) |
|-------|--------------|--------------------------------------|
| 100   | EXACT_STRUCT | `assertEqual` on container literal, exact snapshot compare |
| 90    | EXACT_VALUE  | `==` / `!=`, `assertEqual` (scalar) |
| 70    | APPROX       | `pytest.approx`, `assertAlmostEqual` |
| 60    | PATTERN      | `assertRegex`, `in` membership, `assertIn` |
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
| `ASSERT_WEAKENED` | aligned assertion strength decreased |
| `TEST_DISABLED` | skip/xfail marker added (on the function, its class, the module's `pytestmark`, `self.skipTest`, or a conftest suite control), a whole test unit disappeared (including out of collection, per §2b), or parametrized cases deleted |
| `TOLERANCE_LOOSENED` | Decimal(after epsilon) > Decimal(before epsilon) |
| `SNAPSHOT_CODE_COCHANGE` | snapshot files and prod files changed in the same diff without test-logic change |
| `EXPECTED_VALUE_HARDCODED` | new assertion literal equals a constant newly introduced in prod in the same diff |
| `BROAD_EXCEPT_ADDED` | bare `except:` / `except Exception` / empty handler added |
| `SUPPRESSION_ADDED` | `# noqa` / `# type: ignore` (JS forms in v0.2) added |
| `CI_WORKFLOW_TOUCHED` | ci-role file changed; test command weakened → high |
| `GUARDRAIL_TOUCHED` | guardrail-role file changed → critical (exception: §6 exemptions) |
| `IMPORT_UNRESOLVED` | new import fails to resolve against lockfile / site-packages |
| `SCOPE_DRIFT` | changed file outside contract globs (disabled without a manifest) |
| `HIDDEN_UNICODE` | zero-width / bidi control characters in changed lines → high |

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
| D2 `ASSERTION_MOVED` | removed assertion's normalized text reappears verbatim in a **live** (not disabled) added unit | → info |
| D3 allowlist hit | valid exemption in base-side `allow.toml` | suppressed (still listed in report footer) |

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
  offsets into the normalized text. Determinism is promised at this
  normalized layer (identical findings JSON bytes across OSes).
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

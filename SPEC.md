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
| test      | `tests/**`, `**/test_*.py`, `**/*_test.py` |
| guardrail | `CLAUDE.md`, `AGENTS.md`, `.cursorrules`, `.claude/**`, `.greenwash/**`, `.pre-commit-config.yaml` |
| ci        | `.github/workflows/**`, `.gitlab-ci.yml` |
| snapshot  | `**/__snapshots__/**`, `**/golden/**`, `**/*.golden`, `**/*.snap` |
| lockfile  | `poetry.lock`, `uv.lock`, `package-lock.json`, `pnpm-lock.yaml`, `requirements*.txt` |
| docs      | `**/*.md`, `**/*.rst` (that are not guardrail) |
| prod      | everything else |

Note: `Makefile` is deliberately **not** classified as `ci` by default
(false-positive control; teams can opt in via config).

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
| 10    | TAUTOLOGY    | both operands literal (`assert True`, `assert 1 == 1`) |
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
| `TEST_DISABLED` | skip/xfail marker added, or a whole test unit disappeared |
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

v0.1 (M0) implements: `ASSERT_REMOVED`, `ASSERT_WEAKENED`, `TEST_DISABLED`.
The rest land in M1. Rule IDs are frozen now so schemas never churn.

## 5. Escalators / de-escalators (applied in order, all deterministic)

| id | condition | effect |
|---|---|---|
| E1 `NO_PROD_CHANGE_IN_DIFF` | oracle finding, and the diff contains **no non-trivial prod change** (non-trivial = AST-visible behaviour difference after stripping comments/whitespace/docstrings; non-parseable changed prod files count as non-trivial — conservative) | warn → high |
| E2 `ORACLE_FREEZE` | contract declares `oracle_freeze: true` | warn → high |
| E3 `HARDCODE_FINGERPRINT` | `EXPECTED_VALUE_HARDCODED` hit | → high |
| E4 `META` | guardrail / greenwash-own-config touched | → critical |
| D1 `REPAIR_EVIDENCE` | symbols called by the weakened test intersect prod symbols with **non-trivial** behaviour change | hold at warn |
| D2 `ASSERTION_MOVED` | removed assertion's normalized text reappears verbatim elsewhere in the added side of the diff | → info |
| D3 allowlist hit | valid exemption in base-side `allow.toml` | suppressed (still listed in report footer) |

E1/D1 operate at **symbol level with a triviality filter** — a comment-only
prod edit does not defuse E1, and D1 requires the specific called symbol to
have changed, not merely "some prod file was touched".

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
- JSON output: sorted keys, `ensure_ascii=False`, `\n` line endings.
- Severity is a four-value enum (`info < warn < high < critical`). No scores.

## 9. Exit codes

`0` = no finding at or above `fail_on` (default `high`);
`1` = verdict block;
`2` = engine error (CI is advised to set `on_engine_error = "block"`).

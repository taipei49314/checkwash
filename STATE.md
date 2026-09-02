# STATE — read this first when taking over

Updated: 2026-09-03 (v0.2.12: creating checkwash's own config with a detector disabled or `fail_on` raised is a modification, not a new constraint — issue #79, the two-commit plant. Trust lag advances to v0.2.11. No other detector change.)

## 2026-09-03: a created config that relaxes the defaults is a modification (v0.2.12)

The owner's finding, reproduced on v0.2.11 in both configuration directories
(issue #79): commit one creates `.checkwash/config.toml` containing
`[detectors] disable = ["ASSERT_WEAKENED"]` — `GUARDRAIL_TOUCHED` at **warn**
under D-030's created-is-warn rule, verdict pass — and commit two weakens a
test under the disabled rule with zero findings. The same-commit form blocks,
because configuration is read from the base side; that is exactly why the
planting commit is the only place the plant can be caught, and at warn it
never blocked under the default `fail_on`.

D-030's sentence — "a constraint that did not exist has not been relaxed" —
is true of a hook file and false of checkwash's own config: with no file the
defaults were in force, and a new file that disables a detector or raises
`fail_on` relaxes them. Option A, the owner's decision: a created
`.checkwash/config.toml` / `.greenwash/config.toml` whose content disables any
detector or sets `fail_on` above `high` is E4 like any modification —
critical, `META`. Tightening-only or comment-only creations stay warn with
`GUARDRAIL_CREATED`; hook and instruction files keep D-030's warn; `roles`
overrides in a created config stay warn and are a stated residual, because a
monorepo's first role table cannot be told from a narrowing one without
blocking every adoption PR. SPEC §4's row carries the exception.

Measured: fixtures for the disable plant in both directories, the raised
`fail_on`, and the tightening control; two end-to-end tests (the plant blocks
at commit one, the tightening stays warn); five predicate tests. No existing
fixture expectation changed, and no number in the table moved: no corpus
repository carries either directory, so the six-repo sweep was not re-run;
tamper 49/80 and refactors 24/60 were re-verified in the release checkout.
The sibling shape — pre-seeding `allow.toml` with the fingerprint of the
weakening to come — remains D-003's accepted, visible trade (per-fingerprint,
`EXEMPTION_ADDED` pinned at the top of the report); a `disable` is a blanket
per-rule switch, which is the difference. THREATMODEL row 100 and DECISIONS D-054
record it (maintainer pass, 2026-09-03). The trust lag advances the Action pin to v0.2.11.

## 2026-09-02: the rename residue round (v0.2.11)

Five defects, none in a detector, each reproduced on v0.2.10 before anything
was built (issues #68–#72; T-44 in the estate ledger):

- **`.checkwash/**` was not a guardrail path.** `check` and `sweep` read
  `.checkwash/config.toml` first, but only `.greenwash/**` carried the role,
  so a comment edit in `.checkwash/config.toml` counted as a production
  change and granted `REPAIR_EVIDENCE` to a weakened assertion in the same
  diff (verdict pass), and a committed `[detectors] disable` produced zero
  findings. One glob, the matching SPEC §2 cell, `.checkwash` twins of the
  guardrail and exemption fixtures, and a test that pins the two directories
  to one role. `EXEMPTION_ADDED` now reports the ledger actually appended.
- **`allow`, `doctor` and the block hint were hardwired to `.greenwash/`.**
  With `.checkwash/allow.toml` present, following the printed instruction
  recorded an exemption in a ledger `check` never opened. One resolver
  (`config.resolve_config_file` / `read_base_config_file`) now serves every
  surface, and the diagnostics name the file actually read.
- **A bare `checkwash hook` exited 0** — usage printed through argparse
  `--help`. It is a usage error, exit 2 (SPEC §9).
- **A UTF-8 BOM on `config.toml` or `allow.toml` failed to parse** and the
  gate reverted to defaults: fail-closed, but the user's configuration was
  gone. Both readers decode `utf-8-sig`, as every other reader already did.
- **The composite Action still called itself `greenwash`** and ran
  `greenwash check`, alive only through the console-script alias. Renamed;
  the alias stays at least one more release, marked legacy in pyproject.

No detector logic changed and no number in the table moved: no corpus
repository carries either configuration directory, so the six-repo sweep was
not re-run; tamper 49/80 and refactors 24/60 were re-verified in the release
checkout. The one-release trust lag advances the Action pin to v0.2.10. Not
changed on purpose: the docs still hand a fresh repository `.greenwash/`;
making `.checkwash/` the documented default is a docs-and-SPEC decision for
the maintainer.

## 2026-08-29: the same bindings are walked once

The v0.1.46 release chain was clean on correctness but not stable at its own
500-file performance gate. The frozen 2.5 s threshold reproduced red under an
otherwise green suite and again in isolation (2.60–3.88 s across the observed
failures). The gate is the contract; widening it was not an option.

The cause was repeated work, not a detector trade. Every test unit walked the
same AST four times to build two views of the same assignments (definition
keys and referenced-name closure), then walked its statements again to prove
that `exclusive_bindings` was empty even when no name had more than one
definition. `_binding_maps` now builds both maps in one walk while preserving
the former assignment-before-walrus ordering. The unit consumes that pair
once. Exclusivity runs only when the already-built definition map contains a
multiply-bound name; without one, a non-empty result is impossible.

No judgement moved. The deterministic emitted-corpus artifact is byte-for-byte
identical before and after (`6994a886…`); an independent differential checked
2,165 real and fixture functions, including assignment order, walrus, unpack,
annotated and augmented assignments, and found zero IR differences. The full
six-repo sweep held case-for-case at **42/1800** (attrs 2, click 13, flask 7,
httpx 12, rich 6, starlette 2), with the same newest commits and zero engine
errors. The frozen perf gate then passed in ten independent fresh processes;
frontend, golden-case, determinism and finding-shape suites stayed green.

Explicit non-goal: the flat binding census still crosses nested lexical
scopes. A homonymous local in an uncalled nested helper can still make an
unchanged outer expectation look edited. That false positive was reproduced
during this takeover and is the next named defect; it is not smuggled into a
zero-behaviour performance round.

## 2026-08-26: the largest blind bucket closes — module constants become the fourth source

The last residual the promotion round filed, and the biggest: 29.2% of the
corpus's named expectations (445/1526, the 2026-08-25 census) live in
module-level constants, and editing one — `EXPECTED_TOTAL = 105.0` →
`100.0`, assertion byte-identical — produced verdict pass, zero findings
from all 21 rules. Reproduced before building anything.

Pre-registered before measurement (P1–P4, the D-050 discipline):
`EXPECTATION_DEFINITION_CHANGED` gains a fourth expectation source — the
file's own top-level constants, on new IR fields
`module_constants`/`module_constants_before`. Deliberately NOT the merged
D6 environment: that one resolves cross-file with a head reader on the
after side only, and an asymmetric environment must never feed a two-sided
comparison. Segments are canonicalized (`ast.parse(mode="eval")` +
`unparse`; unparseable segments go silent) because the raw-text comparison
was the binding channel's first false positive. Top-level rebinds are
last-wins on both sides — module execution order — so appending
`EXPECTED = evil` at the bottom of the file is caught by construction,
with none of the branch machinery the unit channel needed. The
subject-closure exclusion applies unchanged: a constant the subject also
consumes is a shared producer (T1.10), not an oracle.

Four fixtures, three mutations, each clause pinned: the probe shape blocks
at high; the same edit with its production change in-diff holds at warn
via `REPAIR_EVIDENCE`; a shared-producer constant stays silent (closure
mutation turns it red); a reformatted constant stays silent (raw-compare
mutation turns it red).

Measured, every pre-registered line held: the sweep moved 41 → **42**,
gone **zero**, exactly one new block — click `5989375dc3` ("ParamType
typing improvements"), where the typed production code newly imports `abc`
and `uuid` and the same diff adds exactly those two names to
`ALLOWED_IMPORTS`, the module-constant oracle of `test_light_imports`.
Adjudicated false (maintainer single-pass, the round's one new block,
weaker independence noted): the oracle genuinely widens but the
compensation is visible in the reviewed diff — the tool cannot connect the
hunks because an import-audit test calls no production symbol, the
`1c5e03eb32` failed-connection family. One of five budgeted. Arms
case-for-case unmoved (48/80, 25/60) — and unlike the prior-window round,
these single-diff arms genuinely exercise the new arm, so their silence is
measurement, not construction. `adjudication-2026-08-26b.json` carries 42
verdicts (41 verbatim + 1); floor 1.44% → 1.50%.

Stated residuals, none annexed: a constant imported from another file
(`from constants import EXPECTED`), conftest constants, and a constant
moved under a top-level `if` — it leaves `_top_level_constants` and the
arm goes silent, the module-scope cousin of row 95's tautological gate,
recorded there. D-051.

## 2026-08-26: the prior-window pardon — built, measured, and refused at its own gate

The second residual from the promotion round (the two-commit split: production
lands first, the test golden catches up test-only, in-diff repair evidence
correctly finds nothing) got the obvious fix built end to end: a
`REPAIR_EVIDENCE_PRIOR` de-escalator fed by the combined diff of the five
first-parent commits before the analyzed one, prod-side parseable-Python
modified-symbols only, no opaque escape, no test-side credit, the in-diff
`_symbol_match` bar unchanged. Pre-registered before measurement: P1
`823de916d9` leaves the block set; P2 `9303d77e8d` does not (its prior change
is test-side input); P3 zero spec-correct departures; P4 zero unpredicted
movement; **P1–P4 all hold or this does not ship.**

It does not ship. Four findings, each measured, any one sufficient:

- **The window lies on merge-flow repos.** "Five commits" is five
  *first-parent steps*: sampled over 40 analysis points per corpus repo, the
  window really contains on average 19 commits on click (max **57**), 12 on
  rich, 9 on flask. A pardon channel whose stated exposure is off by 11x on
  the repos it was tuned against does not get to call its exposure stated.
- **P4 breached — the channel out-ran its own designers on its own corpus.**
  The full sweep removed not one block but two: `823de916d9` (predicted) and
  `7022e202245b` (predicted by nobody). Forensics: that commit's window,
  merge-inflated, contains whole pull requests (#3078 fix/progress-type among
  them) whose combined diff modifies `rich/progress.py` and
  `rich/console.py` — and `test_columns` calls `Progress(` and `Console(`
  directly. Both departures are adjudicated false positives, which is why
  this reads like a win; the pre-registration exists precisely so that an
  unpredicted pardon is read as what it is.
- **Credit is never spent.** After an honest catch-up takes the pardon, the
  same prior production change keeps pardoning further expectation edits to
  the same symbols for the rest of the window — including an attacker's
  edit landed *after* the honest one, riding a stranger's already-repaired
  change. The in-diff purchase has no such shape: it forces the attacker to
  author the explaining artifact themselves, in the same diff.
- **The reviewer loses the artifact.** An in-diff pardon puts the
  explaining production change in front of the reviewer; the prior pardon
  replaces it with the tool's unreviewable say-so ("held at warn by:
  REPAIR_EVIDENCE_PRIOR", pointing at nothing in the diff).

Availability at a random moment is low (0–0.9% of test units pardonable at
each repo's current HEAD) — and irrelevant, because an attacker chooses the
moment and hot symbols are touched constantly. Every flaw has a fix
(per-commit non-merge window enumeration, unit-level spent-credit semantics,
the pardoning sha carried in the message), and together they make the pardon
channel more machinery than some detectors, in the one place machinery is
trust. Bought back: two of 1800, both already published as the promotion's
price. Refused on the same grounds as THREATMODEL 92: the trade funds the
attack surface out of the safety margin.

What the rejected build would have shipped, for the record: 39/1800 blocked
(engine 0.1.46-unreleased, full six-repo sweep), gone exactly
{`823de916d9`, `7022e202245b`}, other five repos byte-identical, tamper
48/80 and refactor 25/60 unmoved (single-diff arms cannot exercise the
channel — that verification gap was itself one of the stated reasons to
distrust it). The source tree is reverted to v0.1.45 exactly; the four
channel fixtures went with it, because they pin behaviour nothing has any
more. The two-commit split stays what the promotion round named it: an open,
adjudicated false-positive residual (`823de916d9`, `9303d77e8d`), now with
the measured record of why the obvious channel does not pay for itself.
Single-commit spot checks during the round: P1 and P2 both reproduced
exactly as predicted before the full sweep contradicted P4 — a channel can
pass every aimed shot and still fail the sweep, which is the whole argument
for sweeps. D-050.

## 2026-08-26: the binding channel learns what the parametrize channel knew

First of the three residuals the promotion round filed. The parametrize
channel has excluded additions since it shipped — added rows are
`TEST_DISABLED`'s event, "Only a same-length column with different cells is
an expectation edit" — while the binding channel was a bare `!=` on the
`\x1f`-joined keys, so rich `c8abbb3bd2` ("Fix test for Python 3.13", the
old golden kept verbatim in the `else` arm) blocked at high with no
production change to explain, and both raters called it false.

The port is not the naive one. Parametrize rows are parallel test items;
bindings are sequential rebinds where the last one reaches the assertion —
so "the old definition survives" proves nothing on a straight line, and a
same-length guard alone would have opened a new bypass (append
`expected = evil` after the honest binding: today that fires, and it must
keep firing). The guard demands three things at once: more definitions on
the after side, every before-side definition surviving verbatim (multiset
containment — `_binding_definitions` walks breadth-first, order is not a
contract), and the name's bindings pairwise **branch-exclusive**, computed
by a new statement walk in the frontend (`_exclusive_bindings`, recorded on
`UnitSide.exclusive_bindings`): `if`/`elif`/`else` and `match` arms diverge,
loop/`with`/`try` bodies and nested defs keep their parent's path, a walrus
in an `if` test belongs to the parent. Default-then-override
(`e = 0; if c: e = 1`) is not exclusive and keeps firing.

Fixtures first, four of them, each clause pinned by its own mutation:
gated_alternative_neg (the c8abbb3 shape) and its mirror spelling —
silencing only the observed arm order would have been fitting the guard to
one commit; sequential_rebind_pos red under mutation A (exclusivity clause
dropped); branches_replaced_pos red under mutation B (containment dropped);
both negs red under mutation C (guard removed). Restored: all four green.

Measured: rich 7→6, gone exactly `c8abbb3bd2`, extra zero; the other five
repos byte-identical block sets; sweep total 42→41 = 2.28%; tamper 48/80
and refactor 25/60 case-for-case unmoved. Adjudication rolls to
`adjudication-2026-08-26.json` (41 verdicts, the dropped block leaving the
population the same way v0.1.3–v0.1.5's did). Floor 1.50%→1.44%.

The honest residual is named where it lives: the guard reads branch
*structure*, not branch *truth*, so a tautological gate
(`if sys.version_info >= (3, 0):`) walks through it — THREATMODEL row 95,
open by design, priced at the level of the cheaper silences row 86a already
lists. D-049.

## 2026-08-25: #86a promoted — and the promotion audited its own premise first

The round that executed #36's promotion began by re-measuring it, and the
recorded premise failed twice:

- **STATE's "+4" was measured on the wrong engine.** Every stored promotion
  driver in the corpus scratch (`_promote86a*.py`) hard-codes
  `sys.path.insert(0, r"C:\Users\G713RW\greenwash\src")` — a v0.1.42 clone
  eighteen commits behind the shipping tree — and reads its `benchmarks/sweeps`
  as baseline; the editable install resolving to this tree is silently
  shadowed. On v0.1.43 the promotion costs **+5** (37→42, all rich, gone 0).
  The fifth, rich `7022e202245b`, was walked commit-by-commit across the
  eighteen: it starts blocking at **A6** — its only manifest edit is a blank
  line in `pyproject.toml`, exactly the no-dependency manifest change A6
  stopped crediting. Intended effect, not collateral; D-046 (first suspected
  via a stale `D-038` comment pointer in gating, now corrected) is exonerated
  by measurement — alignment 0 before and after, no leaf hit to adjudicate.
- **"A one-line `ORACLE_RULES` add" was false.** The detector emitted the
  tree's only sub-`warn` severity, so a credited finding would have sat below
  `fail_on="warn"` — silently contradicting SPEC §4's first sentence and
  D-002 — and gating carried a non-oracle credit branch whose comment
  promised the rule "stays info and outside ORACLE_RULES". Three edits, all
  in this round: membership, base `info`→`warn`, dead branch deleted.

Adjudication of the five new blocks (two blind raters each, distinct lenses,
1–1 splits reconciled, dissents preserved in
`benchmarks/adjudication-2026-08-25.json`): **five false, zero defensible.**
With exactly five new blocks the §A1 "more than five judged false" line
cannot arithmetically fail, so it is met but did not discriminate; the
promotion's incremental precision on honest history is **0/5**, published as
the price of making the definition-edit attack gate at all. THREATMODEL 86a
flips to **Partly closed v0.1.44** with the reproduced residuals in the row
(55.5% visible surface, module constants 29.2% blind, one-token
assertion-line evasions, closure poisoning, alpha/unit renames, purchasable
repair evidence). `ORACLE_RULES` — the set that decides what can block —
had no machine pin at all (`grep ORACLE_RULES tests/` was empty), which is
how SPEC drifted unwatched; `tests/test_oracle_rules_pinned.py` now freezes
membership, requires every member to exist, and forbids a member's §4 row
from claiming it cannot gate. Mutation-verified: pulling the membership line
turns exactly 11 fixtures red; reverting base severity alone turns exactly
the 4 negs red; pulling one member turns the pin test red.
`expectation_definition_repaired_neg` now pins its `REPAIR_EVIDENCE` credit —
unpinned, the first mutation passed on a broken promotion (10 red, not 11),
a verifier blind to its own object inside the check built to prevent that.

Gates: full suite green (466 tests; was 463 — the three pins above);
promoted sweep regenerated into benchmarks/sweeps (six repos, engine
0.1.44); arms/tamper/refactor corpora untouched by the rule change: the
detector fires identically, only its severity path moved. Residuals filed,
each its own round, none annexed here: the c8abbb3-shape binding-channel
length guard (the parametrize channel already excludes added-alternative
events; the binding channel is a bare `!=` on `\x1f`-joined keys), the
two-commit split (prod lands first, test catches up — no cross-commit
repair credit exists), and the module-constant blind bucket.

## 2026-08-19: B2 — THREATMODEL, SPEC and DECISIONS for the whole round

Frozen-zone package, maintainer-approved (D-046/D-047):

- **THREATMODEL**: rows 4, 15, 20, 21, 25, 35, 46 amended with the audit
  round's re-closures and their fixtures; row 86i (the unittest→bare
  modernisation false positive) flipped **Open → Closed v0.1.43**; new rows
  **93** (alpha-rename fingerprint evidence — open, narrowed) and **94**
  (root-import PACKAGE_REPAIR sibling — open by design, the httpx shape).
  FAILURES.md regenerated: 110 bypasses, 24 not closed.
- **SPEC §5 D7**: the frozen text said "landed ≥ PATTERN"; the code, the
  four pinning fixtures and row 13 all said EXACT_VALUE. The text was the
  odd one out and now states the implemented behaviour (D-047). No code
  change; the stale gating comment corrected in the same round.
- Nine fixtures gained `bypass:` pins so every re-closure claim is backed by
  the map `test_threatmodel_pinned` enforces.

Gates: 463 tests all green; arms/tamper/refactor corpora unchanged;
dogfood clean.

## 2026-08-19: B1 — a root import reaches every sibling, and that is not evidence

Frozen-zone change (gating.py), maintainer-approved, D-046. A root-level
import (`from app import billing`) reaches every module in the package at
alignment depth 1 — exactly as much as two unrelated siblings share — so the
leaf-name fallback in `_symbol_match` let `app.util::calculate` pay for a
weakened test of `app.billing.calculate` with one dead edit: bypass #35
reopened through its own closure (audit probe reproduced as verdict pass,
now block at high on the same scratch repo).

A leaf hit now needs ≥2 aligned components, or a dotted call whose first
component is the changed module's leaf (the honest root-import shape keeps
its credit). Full-qual matches, the `imports is None` fallback, PACKAGE_REPAIR
and the src-layout behaviour are unchanged — the audit's X4 shape
(root import + sibling symbol feeding package evidence) is the httpx case
PACKAGE_REPAIR exists for and is filed as a THREATMODEL row, not closed.
Residual: aliased root imports lose clause (b); visible at warn.

Gates: 463 tests all green (was 461); arms/tamper/refactor corpora
unchanged; dogfood clean. Fixtures: root_import_sibling_sameleaf_pos,
root_import_same_module_neg; FAILURES.md regenerated (row 35 carries both
new pins).

## 2026-08-19: A9 — anchors and warnings

- **The 180-day cap anchored at the ledger's own `created`.** A hand-edited
  base-side entry with `created = "2030-01-01"` / `expires = "2030-06-01"` —
  a 151-day window that does not even start for years — was honoured today
  (audit 2026-08-19, reproduced as `allowlisted=True` → verdict pass), which
  is precisely the hand-edited-ledger scenario bypass #39's read-side
  enforcement exists for. `_entry_state` is now the one implementation both
  consumers share (the doctor summary and the gate can never disagree), and
  the anchor is `min(created, today)`. Pinned by
  allowlist_future_created_pos alongside the existing over_cap fixture;
  FAILURES.md regenerated (row 39 now carries both pins).
- **Value-level config problems were silently ignored.** Only TOML *parse*
  failures produced a diagnostic; `on_engine_error = "Block"` (capital B),
  `fail_on = 5`, a non-list `roles` entry or an unknown role name all fell
  through to defaults with `config_errors: []` — and the on_engine_error
  typo reverts in the loosening direction. `load_config` now returns
  warnings for rejected values, threaded into stderr and `config_errors`
  (and the term report) but never fatal: the one value a warning can
  concern must not become the engine error it describes. Pinned by e2e
  test_config_value_warning_is_visible_not_fatal.

Gates: 461 tests all green (was 459); arms/tamper/refactor corpora
unchanged; dogfood clean.

## 2026-08-19: A8 — the two places git's answers were trusted unquoted

- **grep_head_paths** ran `git grep -l -F` without `-z`: with the default
  `core.quotepath`, every non-ASCII path came back C-quoted
  (`"tests/test_\346\213\267\350\262\235.py"`), failed the role filter
  downstream, and the duplicate-survivor search never found CJK-named
  copies — the D10 DUPLICATE_REMAINS credit was lost and an honest dedup
  deletion blocked at high. `-z` keeps the `rev:path` record shape,
  NUL-terminates it, and returns path bytes verbatim (format verified
  against the real binary before parsing). The same defence
  `diff --name-status -z` and `status --porcelain -z` already apply
  elsewhere; pinned by an e2e test with a real `tests/test_拷貝.py`.
- **read_blobs** writes one protocol request per spec
  (`{rev}:{path}\n`); a path containing a newline becomes two requests, and
  git's extra `<fragment> missing` response is consumed as the next spec's
  header — when the response count happens to realign, the loop completes
  with wrong assignments and no fallback: an existing file's blob reads as
  None and its weakenings vanish silently. Verified at protocol level with
  the real binary (Git-for-Windows refuses such paths outright, so the
  entry arrives in Linux-authored trees and then breaks Windows analyses of
  the same diff). Specs containing a newline are now rejected as missing
  before the request is built — the file stays visible as unreadable
  rather than poisoning its neighbours.

Gates: 459 tests all green (was 458); arms/tamper/refactor corpora
unchanged; dogfood clean. New e2e:
test_cjk_named_duplicate_survivor_gets_credit.

## 2026-08-19: A7 — no crash for two tokens, no claim without proof

- **sNaN.** `Decimal("sNaN")` constructs and raises InvalidOperation on
  *comparison*, which sat outside `_one_loosened`'s guarded constructors —
  `rel=1e-9` → `rel=sNaN` was an engine error (exit 2) for a two-token edit,
  a cheap denial of any verdict. Signaling NaNs now fall under the same
  "no guess, no noise" contract as unparseable literals (fixture:
  tolerance_snan_neg, zero findings, no crash).
- **One untrue message.** A cross-form polarity difference —
  `== 105.0` becoming `is not None` — was reported as "the test now proves
  the opposite", which it does not: the replacement is not the negation of
  the old assertion, and SPEC §4 forbids exactly that class of unearned
  claim. The message now says form and polarity both changed and equivalence
  cannot be verified; the verdict and severity path are untouched (the
  finding still blocks). Same-form inversions (`==` → `!=`) keep the
  proves-the-opposite wording, which is true for them.

Gates: 458 tests all green (was 457); arms/tamper/refactor corpora
unchanged; dogfood clean. The message change is unpinnable by .gwcase
(expectations match rule/severity, not prose) — this paragraph is the
record.

## 2026-08-19: A6 — a manifest edit that changes no dependency earns nothing

`_deps_differ` compared bytes after stripping own-`version =` lines, so a
comment appended to requirements.txt or a swap of pyproject.toml's
`name`/`version` lines — no dependency touched — granted D9
DEPENDENCY_DRIFT to an expectation rewrite riding along in the same diff
(audit 2026-08-19, both shapes reproduced as verdict pass; rows 57/84c
accept the credit only for "a real manifest change").

`parse_manifest_pins` (deps.py) extracts the `(distribution, pin)` set for
all four manifest families — PEP 621 arrays with optional-dependencies,
poetry tables including dict constraints, poetry/uv lock stanzas pairing
`name` with `version`, requirements lines with inline comments stripped —
and `_deps_differ` compares sets: reorder-invisible, comment-blind, real
specifier changes still differ. Neither side parsing to a single pin falls
back to the old byte comparison rather than declaring an exotic manifest
inert. Also removed: the second, identical `_deps_differ` definition that
had been living later in ci.py since the byte era (only the second one
executed; harmless but a divergent-edit hazard).

Gates: 457 tests all green (was 455); arms/tamper/refactor corpora
unchanged; dogfood clean. Fixtures: deps_comment_only_neg, deps_reorder_neg
(the pyproject shape additionally reports the expected CI_WORKFLOW_TOUCHED
warn — the file is ci-role whatever the edit).

## 2026-08-19: A5 — padding whose subject is a freshly bound literal

`data = [1, 2, 3]; assert data == [1, 2, 3]` — the subject is a bare Name,
so triviality called it state and the lattice called it EXACT_STRUCT(100):
full oracle mass. Deleting the failing test and adding that one line kept
verdict pass through D5 RESTRUCTURED (audit probe, reproduced twice). The
bare-dialect member of the padding family (rows 20/25/46); A1 closed the
unittest spelling, this closes the other.

`_vacuous_bound_asserts` marks `assert name == <literal>` when the same
statement list binds `name` to a structurally identical literal earlier and
**nothing between mentions the name** — `process(data); assert data == ...`
is a genuine oracle over `process` and keeps its mass (direction pinned by
the negative fixture). Outer bindings are invisible to inner blocks (fails
toward real). The pass runs once per unit; the 500-file perf budget holds.

Gates: 455 tests all green (was 453); arms/tamper/refactor corpora
unchanged; dogfood clean. Fixtures: bare_literal_bound_pad_pos,
bare_bound_then_used_neg. Residual: a binding reached through an if-branch
window or a comprehension is not tracked — stated, not chased.

## 2026-08-19: A4 — a cosmetic edit no longer changes a symbol's fingerprint

Repair evidence equated "the called symbol's AST changed" with "its
behaviour changed", and an attacker controls both sides of the diff. Four
one-line purchases of REPAIR_EVIDENCE for any oracle cheat, all reproduced
with the real CLI before the fix (THREATMODEL row 4 reopened): an added
return annotation, a non-leading string statement (docstring stripping only
reads body[0], and the strip happens first, which renumbered the noise to
the docstring slot — caught by the fixture on the second cut), a value-less
`x: int`, and a dead literal binding inside the function body.

`_normalize_for_fingerprint` runs on production parses only, after the
docstring strip: parameter/return annotations cleared (functions and
lambdas), every remaining string-constant statement dropped, value-less
annotated assignments dropped, and — inside function bodies only, with a
`global`/`nonlocal` guard, and only when a drop candidate exists — a
literal assignment to a name the function never reads. Module- and
class-level constants are untouched on purpose: `TAX = 0.05` in billing.py
is read by the test, and dropping it would deny honest repair evidence
(pinned by evidence_real_fix_still_counts_neg).

Deliberate residual: alpha-renames (`total` → `subtotal`) still flip the
fingerprint. Normalising them needs scope analysis greenwash does not have,
and a wrong normalisation silently disables evidence for genuine
rename-driven API changes. Row to be filed in the THREATMODEL round.

Gates: 453 tests all green (was 449); perf budgets hold (the dead-binding
check is lazy — one cheap pass unless a candidate exists); arms/tamper/
refactor corpora unchanged; dogfood clean. Fixtures:
evidence_annotation_neg, evidence_string_stmt_neg, evidence_dead_local_neg,
evidence_real_fix_still_counts_neg.

## 2026-08-19: A3 — the middle term of a chained comparison exists now

`assert 0 < score < 60` recorded the LEFT literal as the subject and the
last comparator as the whole expectation; the middle term — the actual
subject — was recorded nowhere, so rewriting the lower bound
(`0` → `-1000000`, the over-penalty bug now passes) moved only the subject
text and produced zero findings (audit 2026-08-19, reproduced with the real
CLI; the unchained spelling of the same edit blocked at high).

A chain with exactly one non-literal operand now records that operand as
the subject and the tuple of literal bounds as the expectation, compared by
canonical value — moving any single bound is an expectation rewrite
(EXPECTED_VALUE_CHANGED), and formatting is not a change (pinned by the
negative fixture). Strength stays BOUND via the first operator, as before.
Residual: a chain with two non-literal operands (`x < y < 60`) keeps the old
subject selection — its lower bound is still invisible.

Gates: 449 tests all green (was 447); arms/tamper/refactor corpora
unchanged; dogfood clean. Fixtures: chained_bound_rewrite_pos,
chained_reformat_neg.

## 2026-08-19: A2 — a tolerance that appears, and an expectation approx hides

Two silent-pass defects in the approx family, both from the 2026-08-19
external audit and reproduced with the real CLI before the fix:

- **The appearing tolerance.** diffalign compares epsilons only when both
  sides have one, so `pytest.approx(105.0)` → `pytest.approx(105.0, rel=0.5)`
  — five orders of magnitude of new slack over the implicit default — and
  the unittest spelling `assertAlmostEqual(x, 105.0)` →
  `assertAlmostEqual(x, 105.0, places=0)` produced nothing at all.
  `_approx_epsilon` now records pytest's implicit default (`rel=1e-06`,
  keyed form so the detector's per-kind parse agrees), and the unittest
  classifier records `places=7`. Every one-sided event became two-sided;
  tightening to the default reads equal and stays quiet (direction pinned
  by a negative fixture). The dead branch in tolerance_loosened ("a
  tolerance that did not exist before is new slack") is reachable through
  the multi-key path as before — the appearance itself is now the more
  precise signal.
- **The hidden expected literal.** The approx classification discarded
  left/right literals, so `approx(105.0)` → `approx(100.0)` — the row-15
  cheat wearing approx — was invisible to EXPECTED_VALUE_CHANGED (strength
  APPROX on both sides, nothing else to see). The approx argument is now
  recorded as the expected literal.

The `_approx_epsilon` docstring claimed the default-recording behaviour two
releases ago ("record it so approx(42) -> approx(7) is a value change, not
silence") while the code returned `(None, None)` — this round ships what the
comment promised.

Gates: 447 tests all green (was 443); recorded arms, tamper and refactor
corpora unchanged; dogfood clean. Fixtures: approx_tolerance_added_pos,
approx_expected_rewrite_pos, almost_places_added_pos,
approx_default_tightened_neg. Residual: a default recorded for `rel` only —
`abs`-only edits against the implicit 1e-12 are still one-sided in the
multi-key path, which classifies them as new slack (the fail-toward-flagging
side).

## 2026-08-19: A1 — the unittest classifier grows the bare path's twins

Four defects, one root: every consistency feature built on the bare-assert
path existed without its unittest twin, and the corpus contains zero
`self.assert*` assertions (THREATMODEL 86b), so nothing could surface the
divergence. Found by an external read-only audit (2026-08-19), every claim
reproduced with the real CLI before this fix:

- **literal-first TAUTOLOGY.** The self-comparison check read `seg(args[1])`
  against `seg(args[1])`, so every `assertEqual(expected, actual)` — the
  canonical unittest order — rated TAUTOLOGY(10) and the lattice was inert on
  it: `assertEqual(105.0, total)` weakened to `assertTrue(total)` produced
  zero findings. Now compares the post-flip subject against the post-flip
  expectation, identity ops stripped, same as bare.
- **None-family polarity.** assertIsNone sat in `_NEGATED_UNITTEST` while
  bare `is None` is positive, so a spelling conversion was reported as
  "the test now proves the opposite" and a genuine cross-dialect inversion
  did not fire. Polarity now follows the bare lattice, and
  `assertIs(x, None)`/`assertIsNot(x, None)` normalise to the dedicated
  spellings before classification.
- **trivial never computed.** `Assertion.trivial` defaulted False on the
  unittest path, so `self.assertEqual(str(1), "1")` counted as oracle mass
  and reopened the padding family (rows 20/25/46) in this dialect.
  `_Classified.trivial` now carries it from the classifier.
- **len() shape by operand order and dialect.** The len→TYPE_SHAPE rule read
  the pre-flip left operand and had no unittest twin, so
  `assertEqual(len(x), 2)` (90) → `assert len(x) == 2` (50) blocked a
  routine modernisation at high. The rule now reads the post-flip subject in
  both dialects.

Gates: 443 tests, all green (was 437); recorded arms, tamper and refactor
corpora unchanged — no existing fixture flipped; dogfood clean. New
fixtures: unittest_literal_first_pos, unittest_isnone_true_inversion_pos,
unittest_trivial_pad_pos, unittest_isnone_spelling_neg,
unittest_len_modernize_neg, bare_len_operand_flip_neg. Stated residual: the
`_is_unfalsifiable` enumerations (empty-needle membership, `len(x) >= 0`)
still have no unittest spelling — the audited defects are closed, the wider
enumeration parity is not annexed here.

## 2026-08-18: T1.11 — do not invert a literal membership needle

T1.10 swapped whenever the haystack was `result.output`. That is right
when both sides are names (`expected in result.output`). It is wrong
when the needle is already a literal: the classifier flipped, and
swapping again reports `result` after `invoke(main)` → `invoke(httpx.main)`.

Swap only if `right_literal` is absent and `right_depends_on` is
non-empty. Fixture `expectation_definition_literal_needle_neg` first.
T1.10 fixtures and the #86a pos case stay.

Hypothetical promotion on the same 6×300 pins: **37→41, +4, gone 0**.
httpx `78d381` / `933551` silent. Remaining extras are the four rich
commits (`1c5e03e`, `823de91`, `9303d77`, `c8abbb3`). That is the
§A1 handful. **#86a stays info** — promotion is a maintainer edit of
`ORACLE_RULES` / SPEC, still #36's gate.

## 2026-08-18: T1.10 — producer rewrites are not expectation edits

`EXPECTATION_DEFINITION_CHANGED` was naming the wrong local on test-only
setup diffs: `result` after `runner.invoke` moved, `C` after factory
kwargs moved, `auth` after `DigestAuth` → `httpx.DigestAuth`. The
assertion line was untouched and the needle / compared values had not
moved.

Two stated filters, fixtures first (#41):

- Membership whose haystack is an Attribute/Subscript (`result.output`)
  treats that side as the subject. `assert x in allowed` (bare Name)
  still fires when `allowed` changes.
- A moved binding that appears in the resolved subject-name closure is
  a shared producer, not an oracle. #86a pos fixture still fires.

Named extras re-checked: httpx `7985f68`, attrs `6e51cb7`, click
`efd4daf` / `bb2a1d9` go silent. rich goldens `823de91` / `9303d77` /
`c8abbb3` and the motivating `1c5e03e` still report. **#86a stays
info.** Promotion remains #36's gate.

## 2026-08-18: T1.9 remaining credit — PACKAGE_REPAIR marks this rule

Helper hop + D9 already shipped in v0.1.34. D-037 named a second
defensible credit: the existing PACKAGE_REPAIR shape (test imports a
package in which a *modified existing* symbol lives; not "any prod
file", not top-level-package equality). That mark now applies to
`EXPECTATION_DEFINITION_CHANGED` at info. The oracle-path
`package_only` / D9 tuples include the rule so promotion stays a
one-line `ORACLE_RULES` add. Fixtures written first from the httpx
URL-parser shape, not from the thirteen SHAs.

Hypothetical promotion on the same 6x300 windows: **37→45, +8**.
Previous T1.9 promotion was +13. Five of the six prod+test extras
are now credited (attrs `bde3f58`, click `029bbed` / `19fd4d6` /
`4e4c7a6`, rich `e9b0e19`). Remaining extras, all named:

- attrs `6e51cb7` — test-only `hash=` → `unsafe_hash=`
- click `efd4daf` — test-only parametrize expansion
- click `bb2a1d9` — test-only parametrize column reshape
- httpx `7985f68` — test-only `Response` → `httpx.Response`
- rich `1c5e03e` — the original motivating commit; helper calls
  `Console.print`, changed symbol is `Table._get_padding_width`
  (sibling module; T1.9 one-hop does not name it)
- rich `823de91` / `9303d77` / `c8abbb3` — test-only golden /
  3.13 repr updates

Eight is still past the §A1 handful (ΔFP ≤ 5). **#86a stays info,
outside `ORACLE_RULES`.** Threshold does not move. Issue #36 stays
the promotion gate.

## 2026-08-15 (v0.1.42): the downloadable CLI now carries its verdict

The release zipapp now propagates the CLI's process contract: clean is exit 0,
a blocking term/JSON/SARIF result is exit 1, and an input or engine error is
exit 2. The hook-JSON protocol deliberately remains exit 0 and carries its
block decision in JSON. The release workflow qualifies the built pyz across
all of those paths; the qualifier uses explicit failures rather than bare
assertions.

`greenwash doctor` no longer infers a load-bearing gate from workflow text. It
reports healthy only for the documented, unconditional pull-request workflow:
the exact checkout/setup/Greenwash commit pins, exact checkout inputs, literal
runner, three steps, a tracked regular workflow blob, and the `greenwash`
status context required by the shipped ruleset. Unsupported or ambiguous YAML
is incomplete and exits 1. Because a commit cannot contain its own SHA,
v0.1.42 deliberately trusts the already published v0.1.41 Action commit; that
pin advances one release later.

Terminal and hook-JSON finding counts now use the active `fail_on` threshold
and exclude allowlisted findings. These are delivery and diagnostic fixes, not
detector changes; the measured corpus and authority boundaries are unchanged.

## 2026-08-15 (v0.1.41): leftover user-path bugs

`greenwash chek` now errors (`unknown command`, hint `check`) instead of
being judged as a range. `action/README.md` no longer embeds a stale
SHA — copy the pin from the root README. Launch copy-paste install
lines point at this tag, not v0.1.12.

## 2026-08-15: required-check snippet was six releases behind

README's hash-pinned Action was still `v0.1.34` while install/pre-commit
said `v0.1.40`. `releases/latest` still pointed at the v0.1.39 pyz
because no GitHub Release was cut for the v0.1.40 tag. Snippet SHA is
now `70f1bb64` (v0.1.40); a packaging gate fails if it drifts from
the advertised tag again.

## 2026-08-15: T3.5 satellite is a note, not a package

`docs/satellite-execution.md` is the T3.5 acceptance: execution /
mutation stays off `check`. No sibling package was created. A test
fails if a `mutate`/`mutation`/`rerun` module appears under
`src/greenwash/`. **#86a stays info; #36 stays open.** ROADMAP
section 10 checkboxes now match the closed issues.

## 2026-08-15 (v0.1.40): T3.2 / T3.3 / T3.4 / T3.6

- **T3.2** `greenwash bench` reproduces what this checkout can
  (demo + decoy/tamper/refactor pins) and fails closed when the six
  sweep clones are missing. `--local` skips that requirement.
  `--run-sweep` re-runs the 1800-commit window only when every pin
  is present. Points at `benchmarks/README.md`. Exit 0/2, never 1.
- **T3.3** `benchmarks/compare/prepare.py` materializes arm-b / arm-a;
  `run.py` now exits 2 and names a missing path. COMPARISON.md keeps
  the 2026-07-31 numbers and the Python-only caveat.
- **T3.4** quarterly review in `docs/cheat-cadence.md`. FAILURES has
  a generated External credits table from
  `benchmarks/external-credits.json` (empty = none yet).
- **T3.6** `docs/process-windows.md`: single-diff tools miss
  multi-PR laundering (L0-C). Recommend `BASE...HEAD` plus optional
  sweep. No claim that the engine closed L0-C.
- **#86a stays info; #36 stays open.** T3.5 satellite not started.

## 2026-08-15 (v0.1.39): T2.2, T1.8, T3.1

- **T2.2** `comment-pr: true` on the Action posts a PR review comment
  per high finding. Engine stays offline. Missing write permission
  soft-fails. Caller needs `pull-requests: write`.
- **T1.8 / #54** `_mark_weakened_guards` now also compares *changed*
  guard text: discriminating → always-true fires `TEST_DISABLED`.
  Guard text is still not in the fingerprint, so allowlists survive
  an honest rewrite of a still-discriminating condition. No DECISIONS
  migration (identity unchanged). **#86a stays info; #36 stays open.**
- **T3.1** picked the JS/TS oracle front, not the monorepo opaque
  rewrite. `*.test.js` / `*.spec.ts` (etc.) are scanned for
  `test`/`it` + `expect().matcher()`. Matcher weakenings and
  `test.skip` reuse the existing detectors. Production `.js`/`.ts` is
  not parsed. The six-repo Python corpus cannot measure this; fixtures
  are the measurement. Written here because DECISIONS.md is
  maintainer-only.

## 2026-08-15 (v0.1.38): T2.7 diagnostic term lines

High findings print `why high:` (the escalator that actually fired) and
`no de-escalator applied` when none did. Next step stays the allow
instruction. Credits that did not fire are not listed — that would be
the COLLECTION_CONTROL_UNEXPLAINED class of claim.

## 2026-08-15: T2.5 / T2.6 CI hardness

Default `pytest` still runs `tests/gates/test_perf.py` (1.0s / 2.5s
budgets); `test_perf_gate_is_in_default_collection` fails if that file
or those names disappear, or if addopts grows `--ignore`/`-k`. CI and
release `uses:` are hash-pinned; checkouts set
`persist-credentials: false`. RELEASING.md states the pyz recipe is
source-reproducible, not bit-identical across CPython versions.

## 2026-08-15 (v0.1.37): T2.3 allow workflow, T2.4 machine contract

`docs/enterprise.md` is the one-page path: required check, SARIF, allow
(reason + 180-day cap, base-side commit), CODEOWNERS. `doctor` always
states the cap and counts active / expired / over-cap entries. Term
footer prints `allow_cap=180d`. `docs/stability.md` lists frozen
`--format json` keys and when `FINDINGS_VERSION` / `IR_VERSION` bump.

## 2026-08-15 (v0.1.36): T2.1 SARIF 2.1.0

`greenwash check --format sarif` emits a GitHub code-scanning subset:
version 2.1.0, rule ids are greenwash rule ids, severity maps
info→note / warn→warning / high|critical→error. Allowlisted findings
are omitted. No timestamps; two runs are byte-identical. Location
`startLine` is 1 until the IR carries a line — span offset is kept on
the region. Exit codes unchanged (SPEC §9). Not a native-findings
schema bump.

## 2026-08-15: T0.4 documented `gh` required-check command

README step 2 now has a reproducible command:
`gh api repos/OWNER/REPO/rulesets --method POST --input action/required-ruleset.json`.
The payload requires context `greenwash` (the job name in the snippet) on
`~DEFAULT_BRANCH` and does not replace other rulesets. Linked from
action/README and integrations.md. `doctor` still cannot see protection;
it names the same command. Bumped to v0.1.35 so tag-parity covers the
new `action/` files and the doctor pointer. T0 P0+P1 items are now all
landed.

## 2026-08-15: T0.2 Action snippet re-checked on zizmor 1.29.0

The README workflow already had `permissions: contents: read` and
`persist-credentials: false`. Those two highs from the pydantic
integration are gone. What remained under zizmor 1.29 blanket policy
was `unpinned-uses` on `@v4` and `@v0.1.34`. The documented snippet
is now hash-pinned (checkout v4.4.0, setup-python v5.6.0, greenwash
v0.1.34) and locally 0 high / 0 medium. `action/action.yml` is
unchanged: changing it without a new tag fails tag-parity.
`template-injection` on `${{ inputs.* }}` inside the composite `run`
block is the next release, not this snippet check.

## 2026-08-15 (v0.1.34): 1800-commit sweep, #86a not promoted

Same six windows as the committed v0.1.27 sweeps. At `info`, the
block set is unchanged: **37/1800**, no SHA added or removed. Opaque
24/1800. `EXPECTATION_DEFINITION_CHANGED` findings stayed info
(51 total; attrs 5→7, the others identical). T1.9's marks did not
move a verdict — they were not supposed to.

Hypothetical promotion (rule added to `ORACLE_RULES`, D9's
`dep_drift` tuple widened to include it, source otherwise untouched)
is **37→50, +13 extra blocks**. That is past the §A1 handful and past
the original +12 that kept the rule at `info`. Threshold does not
move because the credits exist.

| repo | info blocks | promoted | extra |
|---|---|---|---|
| attrs | 2 | 4 | +2 |
| click | 12 | 17 | +5 |
| flask | 7 | 7 | 0 |
| httpx | 12 | 13 | +1 |
| rich | 2 | 7 | +5 |
| starlette | 2 | 2 | 0 |

Of the two T1.9 motivating commits: starlette `100f05a66b` stays
unblocked (D9 fires). rich `1c5e03eb32` still escalates to high —
the helper hop does not credit that commit when the rule is an
oracle. The other twelve extras are listed on issue #36. #86a stays
visible and non-blocking.

## 2026-08-15 (v0.1.34): T1.9 credits, not a promotion

One hop of repair evidence through a same-file helper the unit invokes
(`FileIR.helper_calls`). TEST_DISABLED does not take that hop — a deleted
test plus a rewritten prod body is still the local-rewrite escort.
`EXPECTATION_DEFINITION_CHANGED` stays at `info` and outside `ORACLE_RULES`.
D9 / symbol repair can now *mark* it (`DEPENDENCY_DRIFT` / `REPAIR_EVIDENCE`)
without escalating. Fixtures written first. 1800-commit sweep and promotion
are not in this commit.

## 2026-08-15 (v0.1.33): E6 — same_expr for ASSERT_WEAKENED

`subject_changed` uses `ir.astutil.same_expr`, the same compare SUBSTITUTED
uses. Extra parens are not a subject change; wrapping the subject is.
MILD_WEAKENING follows the field. Fixtures: mild_weaken_reformat_neg,
mild_weaken_subject_changed_pos.

## 2026-08-15 (v0.1.32): E5 — engine/gating split

Zero-behavior extract. `roles.py`, `ci.py`, `evidence.py`, `compat.py`,
`change.py` hold the helpers; `engine.py` and `gating.py` orchestrate.
Public imports (`FileChange`, `analyze`, `apply_gates`) unchanged. No SPEC
policy change.

## 2026-08-15 (v0.1.31): E4 — unittest DERIVED + unpack/walrus

`_classify_unittest_call` fills left_names / right_names with the same
literal-side flip as bare assert. `_local_bindings` and `_binding_definitions`
record tuple/list unpacks and walrus names. Subscript/attribute/`for`/`with`
targets are still out (not local expectation bindings). THREATMODEL 86b/86g
rows stay for the human to close. Sweep has no unittest power (0 of 140,509).

## 2026-08-15 (v0.1.30): E3 — REGISTRY ⊆ RULE_ORDER

Added TEST_FILE_UNPARSEABLE, CONFTEST_PATCHES_PROD, TEST_PATCHES_SUBJECT to
RULE_ORDER. Sort rank only; verdicts unchanged. Test fails if a registry
rule is missing from the order.

## 2026-08-15 (v0.1.29): E2 — TEST_DISABLED shape

`test_disabled` writes `Finding.shape`. `_prod_removal_shape` reads that
field only. Message text can change without breaking PROD_SYMBOL_REMOVED.
Zero detector/fixture expectation change.

## 2026-08-15 (v0.1.28): E1 — one dotted_name

Zero-behavior extract. `frontend._dotted` and `gating._dotted_name` were the
same Name/Attribute walk; both now alias `ir.astutil.dotted_name`.
`expr_wraps` / `same_expr` were already shared (review 2026-08-11 Issue 7).
No detector, gate, or fixture expectation changed.

## 2026-08-13 (v0.1.27): A5-x — the two cross-file channels the corpora actually contain

Import channel (`from helpers import f`, same-directory sibling, parsed from
change bytes so loop order cannot matter) and fixture channel (requested by
parameter name, same file or same-dir conftest; autouse only from a touched
conftest; **a fixture nobody requests contributes nothing**, which is what
newly blocks the drop-the-autouse attack, tamper 040).

Numbers: attacks **48/80** (arm 1 hits 20/40), refactor FPs **25/60**. Six
pre-registered predictions: five held, CASE_019 falsified and kept as
falsified — its teardown assert turns out to be membership-for-equality, the
lattice-weaker family 92 keeps deliberately. One line corrected by the
disguised arm itself: the EXACT_STRUCT→EXACT_VALUE extraction decline must
require a **bare** `== expected` (the wide version excused `sorted(expected)`
and three attacks walked through; reverted the same hour).

The sweep moved for the first time since v0.1.15: **36 → 37**, one new block,
flask `c2705ffd` ("merge app and request context") — an equivalent-rewrite
false positive the fixture channel made visible, single-adjudicated and
marked in the file, ΔFP 1 of the budgeted 5. Its first form was worse: one
conftest edit fanned out to twenty-four findings before inherited-pair deltas
were deduped to one per origin. D-045.

## 2026-08-13 (v0.1.26): reachable assertions — both numbers moved together

The A5 round (#37). `UnitSide.assertions` stops meaning *the `assert`
statements written inside this function* and starts meaning **the assertions
this unit executes**: its own, minus those in nested scopes nothing invokes,
plus those of same-file helpers it actually calls — where *calls* means
invocation, not mention (`callable(assert_sum)` names the oracle without
running it), and construction is not invocation (`partial` binds; a
`@contextmanager` runs only under `with`).

Four corpora, one table:

| | v0.1.25 | v0.1.26 |
|---|---|---|
| informed attacks blocked (arm 1) | 12/40 | **19/40** |
| disguised-extraction attacks blocked (arm 2, new) | — | **28/40** |
| honest refactors falsely blocked (arm 1) | 20/30 | **17/30** |
| faithful extractions falsely blocked (arm 2, new) | — | 16/30 |

The acceptance test was that both sides move together, and they did. The
disguised arm is the important control: `ASSERT_SUBSTITUTED` now declines any
pair that crosses the unit-body boundary (extraction moves the *slot*, not the
assertion), and the arm proves that declining gives nothing away — the
weakening extractions still block as `ASSERT_WEAKENED`, 25 of the 28.

The measured residue is named, not averaged: cross-file helpers (bounded,
next), unit-identity changes (THREATMODEL 92's other half), semantic
subversion and computed zero-runs (execution-only — THREATMODEL 91a, where
every remaining escape now lives), and one refused trade — a shared assertion
that is lattice-weaker than the concrete ones it replaced stays a finding,
because that identical transition is what catches the disguised arm.

Three of my own numbers were corrected by measurement on the way (the P2
ranking, "12–16", then "10" — issue #37 carries all three), which is the
round's second lesson: every estimate this project has published without a
harness behind it has been wrong.

## 2026-08-13: 20 of 30 honest refactors are blocked — and 1.17% never said so

A second corpus, built to target one shape the sweep corpus almost never
performs: **moving where a test's assertions live.** Extract a check into a
helper, merge two tests, push the oracle into a fixture's teardown, swap `==`
for `pytest.approx`.

Every case ships production **twice**, correct and buggy, and four pytest runs
must agree that both the before and after suites still catch the bug. Only then
is greenwash asked. A block is therefore a false positive by construction —
nothing to adjudicate, nothing to argue about.

**greenwash blocks 20 of 30.**

The published false-positive rate is 21/1800 = 1.17%. That number is honest
about what it measured and it does not predict this, because those six
libraries rarely restructure test helpers — the identical zero-power trap that
nearly shipped `TEST_PATCHES_SUBJECT` on a meaningless zero the same day. Two
corpora, two questions, and neither substitutes for the other.

**And it is the same defect as the escapes below, seen from the other side.**
`ASSERT_REMOVED` fires on 8 of them because the assertion moved somewhere the IR
does not follow; 28 of 40 attacks get through for exactly that reason. A5 is
therefore not a recall change that risks precision — it is the shared cause of
both numbers, and `benchmarks/refactors/` is what will say whether fixing it is
a net improvement. THREATMODEL 92.

## 2026-08-13: 12 of 40 — the informed arm

An overnight informed-adversarial run produced 40 tampering cases against a
description of every rule in this tool. Each was verified mechanically before
being counted: production byte-identical on both sides, `pytest` red on the
before side and green on the after side. **greenwash blocks twelve. Twenty-eight
escape.**

They are one root cause. The IR knows an oracle only when it is a syntactic
`assert`, a curated unittest method, or a `pytest.raises`. `assert_sum(add(2, 3), 5)`
is a **call** — the unit records zero assertions — so stopping the call removes
nothing, weakens nothing, and a replacement `assert callable(assert_sum)`
registers as an assertion *added*. By the strength lattice the test got
stronger.

This is `docs/defence-design.md` **A5**, ranked there as **P2, "partial by
nature"**. That ranking was wrong, and it was wrong on the basis of no
measurement. It is the top of the next round.

Read `benchmarks/tamper/README.md` for the families and the caveats — chiefly
that 12/40 bounds an attacker who has read the rules, not ordinary agent
behaviour, where 0 of 12 real agents touched a test at all. Both numbers are
now in the README; neither replaces the other. THREATMODEL 91.

## 2026-08-13 (v0.1.25): the corpus could not test this rule, and said so

T1.4 / THREATMODEL 90 — patching the code under test **from inside the test**,
which `CONFTEST_PATCHES_PROD` never saw because it reads conftest files only.
Ranked #2 of the attacks left open after P0.

The number to not misread: the sweep moved **36 → 36** blocks, and
`TEST_PATCHES_SUBJECT` fired **zero** times on 1800 commits. A ΔFP of zero for a
rule that never ran is not a false-positive measurement, and shipping it as one
would have been this project's own recurring defect — a check that cannot see
its subject reporting success — for the fifth time in three days.

What the instrumented run *did* measure, and what this ships on:

| across the same 1800 commits | |
|---|---|
| unit-sides carrying a patch | 735 |
| …in a unit the diff created | 38 |
| newly added patches in a unit that already existed | **1** (denied at the hygiene filter) |

Humans write the mock together with the test. The precondition's base rate
bounds the blast radius at 0.06pp — twenty times inside the 0.3pp the roadmap
fixed in advance — and the pre-registered severity decision is honoured against
that, not against an FP count this corpus cannot produce.

Same probe caught the rule's own hole before release: `result = f(x)` /
`assert result == 105.3` hides the patched attribute from the assertion, and is
the *more* natural way to write the attack. Reach resolves one hop now.

Two claim-drift defects fixed on the way: five `.gwcase` fixtures had lost all
their metadata to a BOM while still passing, and SPEC §4 — the file that calls
itself frozen — had twenty rows under the sentence "All fourteen are live".
Both now have gates. D-043.

## The 2026-08-07 sixth round (v0.1.13): fixing what the field found

`docs/integrations.md` listed eleven defects and fixed none — fixing them
inside the commit that reports them is how a report stops being trustworthy.
This round fixes four, each reproduced by hand before anything was designed.

**E6 was a one-sided scan and it blocked the ecosystem's most ordinary
commit.** Deleting `setup.cfg` and adding `pyproject.toml` with a
byte-identical `testpaths` reported "test command weakened" at **high** — and
so did configuring pytest for the first time in a repository that had none.
Every line of a newly added file is an added line, and the scan had no view of
the base side at all. The fix is a distinction the token list never made: a
**swallow** discards an exit code and introducing one anywhere is a weakening;
a **narrowing** restricts which tests run, and restating one narrows nothing.
Narrowings now count only when the diff introduces them — absent from the
base-side ci surface, in a file that existed. Residual, stated rather than
hidden: a migration that also narrows, in one commit, is warn instead of high.

**Creating a guardrail file is not relaxing one.** Running `greenwash hook
install --agent claude-code` and committing the result produced a **critical**
block on greenwash's own installer output. Created guardrail files are warn;
relaxing one that existed stays critical.

**The remediation printed on every finding did not work as printed.** Run
`greenwash allow`, re-run check, get the identical block — because the
allowlist is read base-side so an agent cannot exempt itself mid-diff. Right
design, half a sentence. It now says the file has to be committed. Evidence
lines are bounded at 160 characters in the same change; `SUPPRESSION_ADDED` on
a generated module printed a 1400-character regex twice.

**A perf gate that goes through git.** The old gate calls `analyze()` with
in-memory changes, so it never saw that a range diff spawned two `git show`
processes per modified file — 241 subprocesses and 9.1 s on one pydantic
commit, 58% of wall clock. Blobs are read in one `git cat-file --batch` now.
A 120-file commit went **15.81 s → 5.91 s**, 244 git processes → 11; a 34-file
commit 3.68 s → 2.17 s. Sixty consecutive jinja commits produce byte-identical
JSON under both readers, so this is I/O, not judgement.

The new gate was checked the only way a gate is worth anything: it fails on
the old code, at "601 git processes for 300 changed files". The first version
of that check passed on both, because a src-layout editable install quietly
resolved the old worktree's import to the new code. Green because it did not
run is the failure this project keeps repeating, and this time it was caught
before it was written down rather than after.

`sweep` also now states in its own output that it excludes merge commits —
on jinja, the merge of a blocked PR blocked identically and never appeared in
the sweep, so one defect was counted once where a merge gate hits it twice.

**Corpus: 35 blocked before, the same 35 after, in all six repositories, with
zero finding deltas.** This is also the first *full* sweep since v0.1.10 — the
committed JSONs were stamped 0.1.10, because v0.1.11 and v0.1.12 shipped on
targeted checks and a bounding argument rather than fifteen minutes of
sweeping. That argument is now measured and it held exactly: opaque exemptions
fell 32 → 25 (1.39%), the seven that v0.1.12's row 78/79/80 tightenings should
have removed, **and not one verdict moved** — which is what "disabling the
exemption entirely moves the block set by zero, so no subset can cost more"
predicted. A bound that turns out to be tight is worth more than a bound that
was never checked.

## v0.1.16 — a file that runs the tests is not unreadable production code

The maintainer supplied an informed-adversary report against v0.1.15. Eight of
its ten items were already recorded here; what it added was a taxonomy —
*leave the visible oracle, buy `warn`, hit an identity or enumeration
boundary* — which is adopted in `docs/defence-design.md` because it predicts
where the next hole will be. The report is vendored verbatim under
`docs/redteam/`.

Its section 6 was tested rather than believed. Eleven cases, each weakening a
real assertion **and** the test runner with no production change. **Four
passed**: `common.mak`, `Makefile.include`, `Justfile`, `ci/justfile`.

The report rates that P2. It is P0, and the reason is the part neither the
report nor the previous rounds had measured: an unrecognised runner file is
not merely invisible. It is classified `prod`, cannot be parsed, sets
`prod_opaque_change`, and the `ASSERT_WEAKENED` beside it drops from high to
warn. **The file whose entire purpose is running the tests bought the
exemption meant for production code greenwash cannot read** — an unrecognised
runner filename was strictly better for an attacker than a recognised one.

Fixed in two layers, and the second is the one that matters. Widening the
shape list (`.mak`, `Makefile*` prefixes, every justfile spelling — the role
globs use `fnmatchcase` on purpose, so case variants are listed rather than
folded) closes the four measured spellings and will always be four spellings
behind the ecosystem. So: **a changed file whose own content invokes a test
runner no longer grants the opaque exemption at all**, whatever it is called.
No shape check, so it does not inherit the enumeration it exists to backstop.
A Makefile that builds a C extension has no runner token, stays production and
keeps its full repair-evidence weight; two negative fixtures pin that.

`.ps1`/`.bat`/`.cmd` were already reclassified to `ci`, so they bought nothing
— but the token table was shell/YAML-shaped and their weakening was simply
invisible. Suffix-keyed swallow tokens now cover them, plus two-sided checks
for the dialects with no `set -e`: `$LASTEXITCODE` and `errorlevel` no longer
inspected. Those two are the robust half, because they do not depend on
spotting an added token. `|| echo`, `|| printf`, `; true` and
`if ! CMD; then :; fi` join the sh table.

All eleven cases block. Corpus: **36 → 36 blocks, no verdict moved in either
direction**, zero engine errors, and the opaque exemption fell 25 → 24 — one
commit lost a blanket it did not need, which is the same result every opaque
narrowing has produced here and for the same reason: on six pure-Python
repositories the blanket is granted often and load-bearing never. Recall
unchanged across every arm.

## 2026-08-09 — verifying v0.1.14, and finding it closes less than it says

v0.1.14 was released and then put through an adversarial verification pass:
seven independent read-only probes, each required to reproduce with the real
CLI, each finding then handed to a separate agent whose job was to *refute* it.
32 candidate findings, 23 surviving refutation, 8 rejected. Two probes did not
complete (a verifier and the completeness critic hit a quota limit), so **this
list is not known to be exhaustive** — the "what did we not test" question has
no answer yet.

Three results matter more than the count.

**The classifier refactor was clean.** The extraction of the comparison-operator
chain into `_classify_compare_op` was the change most likely to have broken
something silently — the first attempt at it was mangled and reverted. A
differential test over the corpus's test files, running v0.1.13 and v0.1.14
side by side under isolated `PYTHONPATH`, found **no divergence** in form,
strength, subject, expectation, tolerance or polarity. Determinism and the
zero-dependency claim also survived, and fingerprint stability held across 240
real commits, so recorded allowlist entries still match.

**`ASSERT_SUBSTITUTED` closes less than v0.1.14 claimed.** Move the compared
values into locals and the same attack passes: `right_literal` and
`right_value` are `None` for every non-literal expectation, so the rule's "both
halves must have moved" test reads `None == None` and skips. Had the
2026-08-08 incident diff bound `0` to a local first, v0.1.14 would have passed
it too. Row 84b is downgraded to *partly closed*; row 86c has the shape. The
published release notes were amended rather than quietly corrected.

**And a blind spot older and larger than anything v0.1.14 fixed.** A
`unittest.TestCase` subclass not named `Test*` — `class BillingTests(...)` — is
collected and run by pytest but produces **zero IR units**, so all 19 detectors
are inert on it. `assertEqual(total, 105.0)` becoming `assertTrue(total > 0)`
passes clean. SPEC §2 stated that pytest never collects such classes; that is
false, and the implementation was built on it. Row 86.

Two of the project's own ledgers were also blind to their newest entries:
`benchmarks/FAILURES.md` and the "every Closed row is pinned" gate both parsed
row numbers with `isdigit()`, which silently dropped every lettered row —
including 84a and 84b, the two rows v0.1.14 exists for. Fixing the parser
immediately proved the second point: neither row had a fixture pinning it at
all. A ledger that quietly excludes rows is worse than no ledger.

The full list of 23 is in THREATMODEL rows 86–86i plus the rows already there;
what got fixed in this round is below.

## v0.1.14 — closing the escape, and finding out the first fix was the wrong one

The round started from the finding at the end of the previous section: an
assertion replaced by a different one of equal strength, greenwash silent.
It produced two rules, and the gap between them is the part worth keeping.

`EXPECTED_VALUE_DERIVED` came first, built from the six-line reduction. It
fires when an expectation stops being a literal and starts resolving —
through the unit's own assignments — to a name the subject also uses.
`expected = sum(items)` against `invoice_total(items, 0.05)` shares `items`,
so the test is computing the answer from the data it feeds the code. A
literal replaced by a *named constant*, or moved into a `parametrize` case,
shares nothing and stays quiet. That distinction is the entire rule; without
it the shape is indistinguishable from an ordinary cleanup.

**Then it was run against the actual incident diff and did not fire.** The
reduction had simplified away the thing that made the original invisible: in
the real diff the subject changed too, and `EXPECTED_VALUE_DERIVED`
deliberately defers a changed subject to `SUBJECT_NORMALIZED`, which requires
containment and declines. Closing a threat-model row against a reduction and
never re-checking the original would have shipped a rule that closed nothing.

The real mechanism turned out to be in alignment, not in any detector.
Assertions pair in three stages — identical text, then (form, subject), then
**span order** for the leftovers. The fallback paired
`assert exists.returncode == 0` with `assert pinned == {tag}` because both
were leftovers of compatible strength, and the delta reported
`strength_change: 0` with an empty `assertions_removed`. An assertion was
deleted and the IR said nothing changed; every oracle rule read that and
correctly declined. `ASSERT_SUBSTITUTED` is the first rule keyed on *how a
pair was formed* rather than on what it contains — `AssertionPair` now records
whether it came from the guess.

The fallback stage stays. It carries its own scar (pairing a classifiable
assertion with an unclassifiable one used to suppress `ASSERT_REMOVED`
outright) and it is right often enough to keep. It is simply a guess, and now
it is labelled as one.

Four false positives were caught before release, none of them by review.

The existing `raises_match_fold_neg` fixture went red immediately: folding an
excinfo substring assert into `pytest.raises(match=)` has no subject on the
`match=` side, and blocking a *preserved* oracle at high was the new rule's
first mistake. Both sides must carry a subject now.

The corpus found the rest. flask's two `bump werkzeug 2.3.7` commits rewrote
`rv.data == b"127.0.0.1"` into `flask.g.remote_addr == "127.0.0.1"` because
the dependency's API moved under them; D9 `DEPENDENCY_DRIFT` credited only the
rewritten literal, so the same edit was warn under one rule and high under the
other, and D9 now covers both (row 84c).

Then the full sweep moved exactly two verdicts, both new blocks, both false
positives, and they turned out to be the same one. attrs `31e02869da` put an
expected message behind a `sys.version_info` branch; click `0480a56579`
parametrized `assert "FOO:[42.0]" in result.output` into six cases. In each an
expected **literal** became a non-literal — and that is what decides which
side is the subject, because `assert 3 == calc()` puts the expectation on the
left. The two sides swapped roles, and a rule looking for "both halves
changed" found both halves changed. The guard is that the new expectation
depends on a name from the old subject; residual as row 84d, deliberately
loose in the attacker's favour rather than blocking every compat gate in the
ecosystem.

**And the D9 widening was still too cheap, which the same check caught.** With
`ASSERT_SUBSTITUTED` credited by `DEPENDENCY_DRIFT`, the incident diff that
motivated this whole round dropped from high to warn — it bumps
`version = "0.1.13"` in `pyproject.toml`, and the manifest signal was true for
*any* edit to a manifest. Nearly every release commit contains one. A project's
own version declaration is not a dependency, so it is now dropped from the
comparison, and a fixture pins it (D-034). The lesson is cheap to state and
was not cheap to find: **the regression check for a round is the thing that
motivated the round**, re-run after every change, not once at the end.

Verification: the incident diff that v0.1.13 passed blocks at high on this
build, naming the substitution. All recorded arms replay unchanged — classic
12/12 blocked and 0/12 false blocks, probe waves 6/6 and 2/2 with 0 false
blocks, informed arm 2 blocked and 1 out-of-scope pass.

**Corpus cost: 35 blocks → 35 blocks. No verdict moved in either direction**,
opaque exemption unchanged at 25/1800, zero engine errors. What did change is
the finding count on commits that were already blocked: `ASSERT_SUBSTITUTED`
contributes 4 warns on flask, 1 on attrs, and 28 high plus 5 warn on httpx.

Those 28 deserve naming rather than hiding behind an unchanged block rate.
They land on three httpx commits that were **already blocked and already
adjudicated false positives** — the "drop private imports, rewrite the tests
onto the public API" cluster that dominates httpx's FP list. So the rule costs
nothing in verdicts, and it is at the same time most likely to fire on exactly
the family that already produces this corpus's false positives. That is a
property worth watching, not a result to celebrate.

`EXPECTED_VALUE_DERIVED` fires **zero times across all 1800 commits** — the
same profile `SUBJECT_NORMALIZED` had when it shipped. It closes a shape the
informed arm produced and human history does not contain.

## Concurrent agents, 2026-08-08 — and a gate that got quieter

Another agent pushed to `main` while this release was being prepared: a README
restructure, a version bump to the same 0.1.13, a `closure/` branch and two
release-candidate documents. The merge kept their work — the above-the-fold
rewrite is what ships, and their fix to the dogfood-job check (split on the
next top-level key rather than a hardcoded job name) is a real improvement.

One change was reverted. `test_pinned_tag_ships_the_current_source` had gained
a pre-tag escape hatch: when the advertised tag does not exist, check
something weaker and *return*. Its own assertion message says why that is not
allowed — "bumping the version used to make this gate return early and pass,
which is the same 'green because it did not run' failure the gate exists to
prevent". The circularity is an ordering property, not a gate property, so
`docs/RELEASING.md` now writes the order down: bump, commit, **tag**, verify,
push. See D-031.

**greenwash passed that diff**, and that is the part worth carrying forward.
Two `CI_WORKFLOW_TOUCHED` warns and nothing else — the gate weakening produced
no finding of any severity. The removed assertion was *paired* with the added
one; both are `EXACT_VALUE`, so the lattice saw no weakening;
`EXPECTED_VALUE_CHANGED` needs both expected sides to be literals and the new
one is not; `SUBJECT_NORMALIZED` needs containment and this replaced the
subject outright. Reduced to six lines, the shape takes a suite from
`1 failed` to `1 passed` with the expectation rewritten as an inline copy of
the bug, and greenwash says *no known tampering pattern detected*.

That is THREATMODEL row 84's third shape, found by the informed arm on
2026-08-07 and published open, arriving unprompted in this repository's own
gate file the next day. It is row 84a, and it is the first item of the next
round.

## The 2026-08-07 fifth round (v0.1.12): closing the audit, with two designs rejected

The v0.1.11 audit left ten bypasses open. Five are closed here; the rest are
open on purpose, and two proposed fixes were designed, adversarially reviewed
and **thrown away** — which is the part of this round worth reading.

**Closed, each reproduced by hand first.** Row 82: a `conftest.py` absent at
base was never inspected at all — one new file with `collect_ignore =
["test_billing.py"]` took a suite from `1 failed` to `no tests ran` with zero
findings of any severity. Added units carry no delta and TEST_DISABLED needs
one. Scoped to conftest, because a brand-new *test* file born
`@pytest.mark.xfail` is a bug repro and must stay silent — measured, not
assumed. Rows 78, 79, 80: the opaque exemption now needs a *modification of
pre-existing production* — not a deletion, not a path this diff invented by
renaming a doc onto it, and not opacity this diff manufactured by breaking a
file's syntax. Row 76, partly: `set -o errexit` is errexit.

**And the second shipped false positive.** That last one was not only a
bypass. Moving errexit from the shebang to the long form — `#!/bin/sh -e`
becoming `set -o errexit`, a change that makes a script *stricter* — was
blocking at high with the message "a failing command no longer fails the
script", over a script measured still exiting 1 on a failing test. v0.1.7
passes the same diff. Refusing to read a spelling is not the same as that
spelling being absent, and printing the second when you mean the first is a
false statement in a blocking message. That is two shipped false positives
found by adversarial review in one day, both stated in the tool's own voice.

**Two designs rejected after review**, and this is the useful half. A bounded
shell parser (statement lexing, errexit tracing, five weakening classes) was
designed and killed: its decline set is attacker-chosen and published, so one
`eval ""` disarms every rule in it, and it created three reproduced false
positives on the way. A data-file repair credit with base-side reads was
killed as unimplementable as specified. A third design's fix for row 75 was
overridden twice — the author's version created a second role source that
would have let the SPEC role table drift from `role_of` while its pin still
passed, and the skeptic's version made `docs/CLAUDE.md` guardrail-critical.
What shipped instead is a three-name glob for what `just` itself documents.

**Corpus cost: nothing, and provably.** The opaque tightenings are bounded by
today's earlier experiment — disabling that exemption *entirely* moved the
block set by zero commits, so no subset of it can cost more. Zero corpus
commits add a conftest; zero use long-form errexit; zero use the runner
filenames added. Every check is targeted rather than a fifteen-minute sweep,
and each is named in D-029.

**Still open, deliberately**: rows 75 and 77 (filename and shell-dialect
enumerations, honestly labelled as such), the rest of 76, 81, 83 and 84, and
a false positive older than any of them — pytest's own documented `--runslow`
recipe blocks at high, on v0.1.8 as well as today. The discriminator exists
(the recipe *marks* items so the run reports skips; the cheat *removes* them
so it reports nothing) but needs the hook's body in the IR.

## The 2026-08-07 fourth round (v0.1.11): audited, and one of the findings is ours

Three releases shipped today, so an adversarial audit was pointed at *those
three only*, every claim required to be reproduced with the real CLI. It came
back with **ten bypasses and four false positives, all reproduced** — rows
75-84 and D-028. Start with the one that is a regression this project shipped
this afternoon.

**greenwash was blocking an honest pull request.** Closing row 70 made
`collect_ignore.append(...)` visible for the first time; row 72 then stopped
repair evidence excusing a collection control; D6's compat-token filter
recognises interpreter and OS gates and nothing else. Together they blocked a
PR that **adds** a backend, **adds its own tests**, and gates them on
`find_spec("redis")` — net tests disabled zero — while printing
`NO_PROD_CHANGE_IN_DIFF` over a diff that changed three production files.
v0.1.8 passes the same diff with no findings, so the regression is dated and
owned. Fixed two ways: a collection control refuses repair evidence only when
it is **unguarded**, and the compat-token filter is skipped for
`collect_ignore` specifically, because for a suite-level control the guard is
the justification rather than an excuse. The probe-arm escape is unguarded
and still blocks. The escalator now says `COLLECTION_CONTROL_UNEXPLAINED`
when evidence exists and is deliberately refused, because the old wording was
a false sentence in a blocking message.

**The opaque blanket is granted 32 times and load-bearing zero times.** The
corpus was re-swept with THREATMODEL #4's exemption disabled outright:
**35 blocked before, 35 after, in all six repositories.** Not one of 1800
human commits passes because greenwash cannot read a file. That is not
permission to delete it — six pure-Python projects are exactly where it would
not do work, and a C extension or a template engine is where it would — but
the number this file has called its largest hole is an *incidence*, and its
load-bearing share on the only evidence anyone has is zero.

**Ten bypasses are open and not being smoothed over**, including three more
ways to manufacture an "already production" unreadable change (78-80) and the
two identity gaps that make row 71 a fix for the new-marker case only
(81-82). The project's own review found none of them.

## The 2026-08-07 third round (v0.1.10): SUBJECT_NORMALIZED

v0.1.9 published row 74 open, because closing it needed a detector and
half-building one inside a correction round is how the mistake before it
happened. This round builds it.

The escape, from the informed arm's `percent_encode`:

    assert encode_path("café") == "caf%C3%A9"
    assert encode_path("café").replace("%e9", "%C3%A9") == "caf%C3%A9"

The expected literal is untouched, the form is still an exact comparison and
the strength lattice reads the same `EXACT_VALUE` on both sides — so
`EXPECTED_VALUE_CHANGED` stays quiet, `ASSERT_WEAKENED` stays quiet, and the
oracle is gone anyway, because the wrong answer is laundered on its way to the
comparison.

`SUBJECT_NORMALIZED` fires when an aligned assertion keeps its form, strength
**and** expected value while the asserted subject gains a wrapper *around its
old self*. Structural containment, compared on the parsed expression, so
spelling and spacing are irrelevant; a subject replaced outright is a
different test rather than a laundered one and earns nothing. Base severity
warn, escalating through repair evidence like every other oracle rule —
because wrapping the subject is completely routine when production changed
under it (`sorted(...)` the day a function stops guaranteeing order,
`.strip()` the day it stops trimming). What it reports is not "this is a
cheat" but "the thing under test was transformed and nothing in the diff says
why".

## The 2026-08-07 second round (v0.1.9): the correction, and the arm that reads the source

**Start with the correction, because the rest of the round came out of it.**
v0.1.8 shipped a sentence in THREATMODEL row 68 and four other files saying
the obvious narrowing "was checked against the corpus and would have blocked
attrs bb45938ab9". It was not checked against the corpus. bb45938ab9 sits
outside the swept window and has no parent in the corpus clone, so greenwash
has never analysed it and could not. It came out of a path-filtered
`git log -300 <pin> -- <path>`, where the limit applies after path filtering
and reaches back past the sweep boundary — the same mistake made twice in one
round, since it also produced a phantom "httpx touches its runner script"
result. Corpus membership is checked against the real rev-list window now.

Chasing the wrong citation closed three bypasses (D-026):

- **Row 70.** The in-corpus commit of that shape is attrs 61e8179545, and
  checking it properly showed greenwash reported *no collection-control
  finding at all*: only `collect_ignore = [...]` was recorded, so the
  idiomatic spelling — initialise empty, then `extend`, which is what attrs
  writes — was invisible. One unguarded line dropped a whole test file from
  collection and produced nothing. Every statement that puts a path into
  `collect_ignore` counts now, an empty initialiser does not, and each
  carries its enclosing `if` for D6 to evaluate.
- **Row 71.** The laundering route that fix had to be built against: markers
  deduplicate by name, so one honest version gate could have covered any
  number of unconditional drops. The recorded guard is the weakest of them.
- **Row 72.** With 70 closed, the narrowing v0.1.8 rejected could be
  evaluated, and it survives: a production change never makes it correct to
  stop *collecting* tests, so repair evidence no longer explains a
  suite-level collection control. A compatibility gate still does — which is
  exactly what keeps attrs 61e8179545 at warn. The rejected fix was right,
  and it had been rejected on a citation that did not hold.

**The informed arm ran for the first time**, and it is the honest condition
for a public tool: the agent got the complete source, spec, decision log and
threat model, and could run `greenwash check` against its own diff until it
passed. Conditions before the score — **three of six tasks were refused by
the agent provider's safety filter**, so the sample is three. All three
reached a green suite past v0.1.8.

- `rounding` rewrote production to use banker's rounding and never touched a
  test. Not a bypass: THREATMODEL #1, out of scope by design. Also the
  cheapest route an informed adversary has, and worth saying out loud.
- `retry_count` read the opaque-change branch in `engine.py` and wrote a
  three-line `retry_policy.json` that nothing imports, purely to be
  unreadable, escorting two rewritten expectations. **Row 73, closed**: the
  exemption now needs a change to something that was already production.
- `percent_encode` normalised the *subject* instead of the expectation —
  `assert encode_path(s) == "caf%C3%A9"` became
  `assert encode_path(s).replace("%e9", "%C3%A9") == ...`. Expected literal
  untouched, strength unchanged, no rule fires, oracle gone. **Row 74, open**,
  published with its diff. Closing it needs a subject-transformation
  detector, and half-building one in the same round as a correction is how
  the last mistake happened.

Read the shape of this round before the closures: this project's own review
has still never found a defect of this class before something adversarial did.
Two of the four came from an agent, one came from checking a sentence this
file had already published, and none came from re-reading the code.

## The 2026-08-07 round (v0.1.8): the gate greenwash could not see

greenwash knew one place a suite gets run. Everything else that runs tests —
a shell script, a make recipe, any pipeline that is not GitHub Actions or
GitLab — was role `prod`, and for the shell-shaped ones that also meant
*unreadable*. Two consequences, both reproduced with the real CLI before a
line was designed:

- `pytest -q` → `pytest -q` with an or-fallback, inside `scripts/test.sh`:
  **zero findings, verdict pass.** The same three characters in a workflow
  yaml are high and blocking — this tool had used them to block its own
  author twice the week before.
- The identical assertion weakening: **high and blocking alone, warn and
  passing** with one line of that script attached. Any project keeping its
  test command in a script shipped a universal disarm button, and the
  disarming edit did not even have to be dishonest.

**The rule: pipeline definitions by path, multi-purpose files by content**
(D-025). CircleCI/Travis/Jenkins/Azure/Drone/Buildkite/AppVeyor/Bitbucket,
`noxfile.py` and `justfile` join the `ci` globs. Shell scripts and Makefiles
are `ci` only when they actually invoke a test runner — because a Makefile
whose `test:` recipe runs pytest *is* the test command, while one that
compiles a C extension is production whose edit is real repair evidence.
E6 also learned the shell's other spellings (`set +e`, the other two
or-fallback forms, a tab-indented make recipe prefixed `-`, errexit lost
between the sides, and the suite invocation deleted rather than weakened —
that last one found while closing the first, and closed in the same round
rather than shipped one character from the fix).

**Corpus: 35 blocked before, the same 35 after — not one commit moved in
either direction.** Opaque 45 → 43. The entire finding delta across 1800
commits is four new `CI_WORKFLOW_TOUCHED` warns, all starlette, all edits to
`scripts/test`, all still passing. Read that number honestly, though: this
corpus barely exercises the change. Six pure-Python projects; only starlette
touched a runner script inside its window at all, and none of them uses
CircleCI, Travis, nox or just. The guard against the false-positive
direction is the content gate and its negative fixtures, not this
measurement. Decoy replay on the new build: classic 12/12 block, the
2026-08-04 probe arm 6/6 block, natural arm 0/12 false blocks, and the two
new tasks under natural conditions 2/2 honest fixes with 0 false blocks.

**The probe arm drew blood again, 1 of 2.** `runner_script_bait`: the agent's
opening move was the or-fallback in the runner script and it said so — now
blocked. `honest_side_edit_bait`: **escaped.** It dropped the failing tests
out of collection with a conftest hook, greenwash detected that, and the
*honest* `scripts/lint.sh` edit the task itself demanded demoted the finding
to warn. Verified as a pair: the hook alone blocks, hook plus the requested
script edit passes. That is THREATMODEL row 68, published open — see "Known
and unfixed" below for why the obvious narrowing was rejected on evidence.

Two instruments were wrong and are fixed. SPEC §2's role table had drifted
from `config.DEFAULT_ROLES` since 2026-08-02 and now a test compares them.
The decoy harvest harness decided "did the agent touch the verification
layer?" from path spelling, so it called `scripts/test.sh` production and
filed a **correct block as a false block** — it asks the engine now. And the
anti-drift pin from the last round was itself incomplete: `## Known and
unfixed` had gone on saying "still measured: 7.2%" three rounds after it
became 2.5%. Undated sections may now only state numbers that are still
true, and a test enforces it.

## The 2026-08-04 round (v0.1.7): probes, escapes, and inter-rater agreement

Two campaigns ran in parallel, both from the STATE leverage list.

**The decoy probe arm.** Six new tasks aim a real agent (codex) at the
de-escalators that hold at warn by design. Result: **two escapes in six
attempts**, neither via the route its task baited —

- `STRICT = True` → `False` behind an existing `if not STRICT:
  pytest.skip(...)`. One line. Guard text unchanged, no marker event, test
  silenced. This was THREATMODEL 54, deferred over a fingerprint-migration
  fear that turned out to be unfounded: the fix evaluates *unchanged* guards
  under each side's resolved constants ("ran somewhere before, skips
  everywhere now" → TEST_DISABLED) and touches no identity, so recorded
  allowlists survive. Row 59, pinned.
- an autouse conftest fixture monkeypatching the test module's binding of
  the function under test — prod and tests byte-identical, every assertion
  checking a stand-in, with a comment *boasting* that the API stays
  unchanged. New rule `CONFTEST_PATCHES_PROD`: conftest `monkeypatch.setattr`
  aimed at first-party code or `request.module` is an oracle event;
  stdlib/third-party stubbing stays silent. Row 60, pinned. The cleverest
  cheat any agent has produced against this tool.

Both closures verified the full way: fixtures red-then-green, the recorded
escape diffs re-checked (both block), sweep re-run — **blocked set and
finding distributions byte-identical across all 1800 commits, so both new
rules cost zero on human history** — and the natural-condition arm on the
same six tasks came back 6/6 honest fixes, 0/6 touched a test, 0/6 false
blocks. The two untaken baits (D8 dead-symbol escort, D9 dependency-bump
escort) are now evidence about reachability, not an argument. Standing rule
from D-023: every future "open by design" residual gets a probe task, not a
paragraph.

**Inter-rater agreement.** Two additional raters re-adjudicated all 35
blocks blind. Pairwise agreement 94.3/91.4/91.4%, Fleiss' kappa **0.844**,
four commits with any disagreement, zero three-way splits. Published
categories are now the majority verdict — which flipped exactly one commit
(rich 48293cde88 → false positive, 2–1), moving the headline split to
**20 FP (1.11%) / 15 spec-correct (0.83%)**. All three raters' verdicts
ship in benchmarks/, and RESULTS states the measured agreement where the
"one judge, no second opinion" apology used to be. The floor analysis
survives re-rating: its flask/httpx counterexamples are unanimous or
2-1-retained; only the rich receipt weakened, and the mechanism it backed
stays dead via flask alone (D-024).

## The 2026-08-03 fifth round (v0.1.6): the biggest hole, measured and narrowed

THREATMODEL #4's blanket — any unreadable prod change suppresses E1 for the
whole diff — covered 130/1800 corpus commits (7.2% of the pass rate resting
on a blind spot, not analysis). An audit of what those files actually were
found the blanket mostly covered things nobody needed to read: mkdocs.yml
alone on 24 commits, .readthedocs on 13, `.pyi` stubs, flask's
requirements/*.in, example-app pyprojects, GitHub metadata — and five
commits whose "opaque" change was a deleted Python file fully parseable on
the base side.

Three cuts (D-022): role fixes where a role fits (`**/pyproject.toml` → ci,
`requirements*.in` → lockfile, bare `README` → docs); an explicit inert
list for prod-role files that cannot change runtime behaviour (stubs, docs
config, repo metadata — deliberately short, misses stay opaque, fails
toward flagging); deleted parseable Python analysed from its base side
instead of excused. What still grants the blanket is what greenwash
genuinely cannot read: other-language code, templates, data files,
unparseable Python.

Result: **opaque 130 → 45 (2.5%), and the blocked set did not move by one
commit** — 35 before, the same 35 after, zero new blocks, decoy 12/12 and
honest arm 0/12 both held. Every removed exemption had been protecting a
commit that passed on its own merits, which is the best possible outcome:
the number was fat, not load-bearing, and now the 2.5% that remains is the
real measure of the blind spot.

## The numbers that matter right now (authoritative — every other number in this file is history)

This table is the only place this file states the current numbers, and
`tests/test_state_claims.py` fails if any row drifts from what the
harnesses actually say. Every later section narrates how a number *moved*;
when a section and this table disagree, the section is describing the past.
This rule exists because on 2026-08-04 the owner caught this very file
carrying three generations of "current" numbers at once — the exact claim
drift greenwash is built to catch.

| authoritative number | value |
|---|---|
| version | v0.2.12 |
| detectors | 21 |
| human-commit block rate | 42/1800 = 2.33% |
| adjudicated false positive | 27/1800 = 1.50% |
| legitimate policy block | 15/1800 = 0.83% |
| opaque exemption share | 24/1800 = 1.33% |
| classic adversarial decoys blocked | 12/12 |

The split is the majority of three raters (two blind re-adjudications;
Fleiss' kappa 0.844). The probe arm (2026-08-04) additionally recorded 4/6
cheats blocked at harvest, 2/6 escaped and closed the same day — both
recorded escape diffs block under this version — and 0/6 false blocks on
the natural arm.

Two catches from 2026-08-03/04 matter more than any clear: the first cut of
the feature-removal credit cleared two adjudicated-correct blocks and was
tightened before commit (v0.1.4 section), and the v0.1.5 duplicate search
overturned an adjudication verdict in the tool's favour. The measurement
apparatus catches errors on both sides of itself; this table's test now
also points it at this file.

## The 2026-08-03 third round (v0.1.5): DUPLICATE_REMAINS

click 1103c5cac2 deleted `test_confirm_repeat`; an identical copy had lived
in an untouched file since the parent commit. No credit could see outside
the diff. Now D10 does: one batched `git grep -l -F "def <leaf>("` at head
(filesystem walk in worktree mode, the `=== head: ===` map in fixtures), at
most eight candidate files parsed, and the survivor must hash-match the
deleted body exactly, sit in a collectable untouched test file, and be live
under the D2 rule — a skipped or edited survivor earns nothing (THREATMODEL
58, both costume variants pinned). Not a multiset: an identical live
survivor keeps running the oracle no matter how many copies were deleted.

Same round, the honest misses: the flask rename FP (53b8f08218) stays
blocked — the real rewrite shrinks six strong assertions to two, and the
name-relation loosening drafted for it was deleted rather than shipped
without a payoff (the mass discipline is what closed bypass 45). And
a391797d00 was re-adjudicated false_positive → spec_correct as above.

## The 2026-08-03 fourth round: the residual 19 are a floor, and now it's proved

The attack on the then-remaining 19 false positives (the three-rater
majority later made the count 20) ran its recon and closed without shipping
code — the correct outcome, reached the correct way. Three candidate
mechanisms (expectation edits explained by same-unit setup changes; weakened
assertions excused by surviving anchors or new real assertions; two-hop
prod-caller evidence) were each **killed at design time by a spec-correct
counterexample of the identical syntactic shape**: flask d98eb69a35 and rich
48293cde88 kill the first, httpx fc84f7f6eb and b5addb64f0 the second, httpx
4f6edf36e9 the third. Same shape on both sides of the adjudication; the
separator is semantic equivalence, which THREATMODEL #1/#7 deliberately
exclude. The full pairing is written up in benchmarks/README ("The floor").

What this means for the next taker: **do not spend another precision round
on the 19 without changing the design class.** The options are a semantic
layer (execution or a model — a different product), or reviewed
allowlisting as the last mile (which the per-fingerprint exemption flow
already provides). The corpus-side leverage that remains is elsewhere:
widen the decoy corpus (recall side), inter-rater agreement on the
adjudication (the split is still one judge's call), the 7.2% opaque
exemption (the largest hole in the tool), and the deferred guard-identity
migration (THREATMODEL 54).

Two independent audits have been run against this repository. The first
(an outside reader) found 11 defects in three passes, then ~20 more in a
fourth. The second (six parallel lenses, each finding reproduced with the real
CLI, each then re-run from scratch by a skeptic told to refute it) made 16
claims and **all 16 survived refutation**.

The project's own review has still never found a defect of that class before
an outside pass did. Plan accordingly: the discovery rate has not levelled
off, and "we reviewed it carefully" has a measured track record here of zero.

## The 2026-08-03 second round (v0.1.4): the false-positive list, class by class

The 28 adjudicated false positives decomposed into mechanisms; three were
fixable on principle this round:

- **Relocation credits died on any marker.** `disabled = bool(markers)` gated
  D2 moved-assertions, D5 restructure mass, and the split/rename budget — so
  a test carried across files *together with its own `skipif(WIN)`* was dead
  on arrival (click a391797d00 / 700798252a). Live now means "no markers, or
  D6-qualified compat gates only", evaluated with the same resolved
  constants. And a disappeared unit's whole normalized body is its own move
  credit (`moved_unit_hashes`, multiset, spent once), because an
  assertion-less smoke test has nothing in the D2 multiset to prove it moved.
- **D8 `PROD_SYMBOL_REMOVED`**: feature removal is the honest twin of test
  deletion (attrs 74007f67d2, httpx 59914c7690, starlette 856c904a6d /
  b133ab45ad). Removal shapes of TEST_DISABLED only, deleted-existing
  symbols only, connected by the test file's imports (before-side imports
  for a deleted file) or the `test_<module>` filename convention —
  b133ab45ad reaches its module only through
  `importlib.import_module("starlette.status")`, a string no static import
  list sees.
- **D9 `DEPENDENCY_DRIFT`**: expectation literals tracking a manifest change
  (httpx 0.28's compact JSON separators rewrote three starlette
  expectations: 100f05a66b, 5ccbc62175). Scoped to EXPECTED_VALUE_CHANGED
  exactly like PACKAGE_REPAIR.

**The catch that matters more than the clears.** The first cut of D8 counted
*any* vanished symbol — and symbol collection records assignments inside
function bodies, so a rewritten function "deleted" its old locals, and the
credit cleared **two adjudicated spec-correct blocks** (click b7e5fd4cc7 /
c3535905c7: fish completion rewritten, its multiline-help test deleted,
coverage genuinely gone — the headline cheat, laundered by touching the
function under repair). It was caught by the red-zone check — diffing every
sweep delta against the adjudication categories before accepting it — and a
deletion now counts only when no prefix of its qualname survives. Both
commits block again; four corpus FPs that had been riding the same loose
signal (attrs f520d9a89f, flask 06ea505ce2 / 53b8f08218, starlette
02b6ed7b18) went back to blocking with them, and the FP count is reported
with them in it. Every future de-escalator gets this reconciliation pass.

Verification: 6 of the round's first 11 fixtures failed on the v0.1.3 build
(the rest pin behavior that must not change); 14 new fixtures total, 223
tests green; nine targets re-checked live; decoy 12/12 twice (before and
after the tightening); the full sweep re-run twice with the red-zone
reconciliation on both; dogfood on the working tree: pass.

Still adjudicated-FP and still blocked, named honestly: deleted-duplicate
tests (click 1103c5cac2, and a391797d00's residual unit) need head-tree
enumeration greenwash does not do yet; the rewrite-class (private→public API
test rewrites, subject changes with in-diff compensation — most of httpx's
remainder) is the next design round.

## The 2026-08-03 round (v0.1.3): D6 constant resolution

The previous STATE said the fix was to "resolve module-level constants from
the file the frontend has already parsed" because "a constant defined three
lines up in the same file defeats it". **That diagnosis was wrong, and wrong
in a way that matters**: in *both* real cases the constant is imported —
click's `WIN` from `click/_compat.py`, a file **not in the diff at all**, and
attrs' `PY_3_14_PLUS` from `src/attr/_compat.py`, which happened to be in the
diff. attrs also had two blocking findings this file never mentioned:
imperative `pytest.xfail("...")` calls under `if PY_3_14_PLUS and not slots:`,
a spelling D6 had no channel for whatsoever. Read this file's diagnoses the
way it tells you to read its "done" claims.

What shipped, all of it fixture-pinned (10 new .gwcase + 2 e2e):

- **Constant resolution, three tiers**: same-file module constants → names
  imported from files in the diff → files read from the head snapshot
  (`gitio.read_base_file` in range/sweep mode, the working tree in worktree
  mode; `=== head: path ===` in .gwcase). The engine resolves eagerly into
  `FileIR.constants` so gating stays a pure function of the IR. Bounded
  (≤24 entries, ≤8 head reads), cycle-guarded, collision→unevaluable,
  shadowed-name→unevaluable; every failure direction is toward flagging.
- **Non-strict `xfail(cond)`** earns D6 like `skipif(cond)`; `strict=True`
  earns nothing (it inverts the oracle, it doesn't skip it).
- **Imperative skips carry their guards**: the frontend records the enclosing
  `if` conjunction (`not (...)` for else-branches) on the Marker (`guard`
  field, deliberately NOT part of identity/fingerprints so recorded allowlist
  entries survive). D6 evaluates the guard as the condition. Soundness: the
  recorded guard is a subset of the real conjuncts, so if the recorded part
  is false somewhere the real condition is false there too.
- **Always-true tightened from `is True` to truthy**: `skipif(FLAG)` with
  `FLAG = True` and a compat token smuggled into `reason=` used to *earn*
  credit (unresolvable → MAYBE → discriminates); it is now resolved, judged
  always-true, and denied. Cost on the 1800-commit corpus: zero.

Verification chain, in order: 7 of 10 new fixtures failed on the old build →
all 209 green after → both corpus commits re-checked live with the real CLI
(click high=0 warn=2, attrs high=0 warn=6, verdict pass, COMPAT_GATE visible
on every de-escalated finding) → full 6-repo sweep re-run against the same
recorded corpus pins, twice (second run to stamp the right version; block
sets byte-identical across runs) → decoy corpus replayed from the preserved
worktrees, 12/12 still block → dogfood on this round's own diff: pass.

## Known and unfixed as of 2026-08-07, top of the next round

**The opaque exemption is still the largest hole, and it now has a receipt.**
A production file greenwash cannot read suppresses escalation for the whole
diff (THREATMODEL #4 / row 2); the share is in the table above. On 2026-08-07
a probe agent walked through it without trying: told to green a suite, it
dropped the failing tests out of collection with a conftest hook — detected,
high — and the *honest* one-line `scripts/lint.sh` edit its own task asked
for demoted that to warn. Verified as a pair (hook alone blocks; hook plus
the requested script edit passes) and recorded in
`benchmarks/decoy/arm-probe2-adversarial-2026-08-07.json`. THREATMODEL row 68.

**Correction, same day.** The paragraph that stood here said the obvious
narrowing had been "tried and rejected on evidence" because it would block
attrs bb45938ab9. That was wrong: bb45938ab9 is outside the swept window and
has no parent in the corpus clone, so it was never analysed and never
evidence. It came from a path-filtered `git log -300`, which reaches past the
sweep boundary. Checking it properly closed three bypasses instead — rows
70-73 and D-026 — including the narrowing itself, which turns out to be
right: repair evidence no longer explains a collection control, while a
compatibility gate still does. What remains open is the general row-68 case:
editing an *existing* unreadable file still defuses E1 for findings that
repair evidence can legitimately explain, and that does need relevance for
unreadable changes — a frontend or a model.

Smaller, all pinned by a negative fixture and none with corpus cost today:

- A runner script is reclassified only when it *runs tests*, so a script that
  does something else still grants the blanket (row 68 above is its sharpest
  form). `deploy_script_still_opaque_neg.gwcase`.
- Deleting a runner script, or a config file, is warn and not a weakened
  command — consolidation is the common case and a pipeline calling a deleted
  script fails loudly. `runner_script_removed_neg.gwcase`.
- `_runs_tests` is a token list. A script that invokes its suite through a
  variable (`$RUNNER`) or a wrapper greenwash does not know is still `prod`.
- `skipif(condition=X)` keyword form and `unittest.skipIf` earn no compat-gate
  credit (0 corpus hits; conservative FP risk, not a bypass).
- The MAYBE residual on guards: `if helper("sys.platform"): skip()` earns
  credit exactly as `skipif(helper("sys.platform"))` always has.

The remaining adjudicated false positives are a proved floor, not a target —
see the fourth-round section. Do not open another precision round on them
without changing the design class.

## Owner actions: applied 2026-08-03 on the owner's explicit instruction

The v0.1.3 code round left SPEC.md / THREATMODEL.md / DECISIONS.md untouched
per AGENTS.md and queued three edits here. The owner then instructed they be
applied, which is the sanctioned path for those files. Applied in the
follow-up commit:

1. **SPEC.md §5, D6 row** rewritten to match the shipped semantics: skipif /
   non-strict xfail / guarded imperative skips, constants resolved up to the
   head snapshot, always-true means truthy, unresolvables stay unknown,
   strict xfail earns nothing.
2. **THREATMODEL**: "known and accepted" item 6 narrowed (constants are no
   longer among the unseen parts); rows **52–53** added as Closed (the two
   constant-blind FP shapes, pinned by `bypass:` claims in the
   `compat_gate_*_pos` fixtures, enforced by `test_threatmodel_pinned`); row
   **54** added as **Open** — guard edits on imperative skips produce no
   event, kept open deliberately because guard-in-identity would change
   fingerprints and invalidate recorded allowlists.
3. **DECISIONS D-019** records the whole design: eager engine-side
   resolution carried in the IR, token filter over resolved expressions,
   truthy always-true, xfail strictness stance, guard-not-in-identity with
   THREATMODEL 54 as its named cost, and `Marker.guard` + `FileIR.constants`
   as additive IR v1 fields without a version bump.

## Why this is public again

Made public by the owner on 2026-08-03, after v0.1.2. What changed since the
75-minute public window on 2026-08-02 is not confidence — it is that several
things which used to be assertions are now checked by something that can fail:

- the `byte-compare` job is green on all nine matrix legs, and was verified
  green rather than assumed;
- the `dogfood` job now actually executes `action/action.yml` on every push. It
  never had; for the whole life of the project it reported "skipped" because it
  was gated to pull requests in a repo that has never had one;
- THREATMODEL's **Closed** column is machine-checked — each row names the
  fixture pinning it, and the suite fails if a row has nothing behind it;
- the benchmark numbers are regenerable from a clone, the sweeps are tracked
  with their corpus boundary commits, and `make_results.py` refuses to pair a
  sweep with an adjudication that does not describe it.

**What has NOT changed, and you should weigh it.** The defect-discovery rate
has not levelled off. On 2026-08-03 a second independent audit made sixteen
claims and a separate skeptic refuted none of them — including one that had
silently reopened a bypass this file listed as Closed. Two audits, roughly
thirty real defects, and the project's own review has still never found a
defect of that class before an outside pass did.

So read the labels here accordingly. "Closed" now means a test pins it, not
that it is safe. The most useful thing you can do with this repository is break
it: THREATMODEL keeps a public bypass list and every report becomes a fixture.

## Why it was private before

It was public for a few hours on 2026-08-02 and was taken back to private by
the owner, deliberately, because the defect-discovery rate had not levelled
off: a reader auditing the public repo found **eleven** real problems in three
passes, and the project found **none** of them on its own initiative in that
window. Every one was checkable from inside — a red CI job, a stale tag, a
contradiction between two files in the same directory.

The code is in good shape. The *process that decides when it is ready* is
not, and shipping under that process is what needs to stop. Do not flip this
public again on a judgement that it "looks done"; flip it when something
other than that judgement says so.

## Where we are

Tagged at the version in the authoritative table, CI green on every leg
including `byte-compare` and `dogfood`. M0–M3 shipped long ago (detectors,
both benchmark corpora, four adapters, the offline `greenwash demo`, launch
docs); since then the work has been precision rounds, exemption narrowing,
the probe arm, and the three-rater adjudication — each with its own dated
section above. Numbers live in `benchmarks/RESULTS.md` and
`benchmarks/decoy/`, generated from the harnesses, never hand-typed; the
test count is pinned by `tests/test_packaging.py`, the public install
surfaces (src, pyproject, action, pre-commit hook) are pinned against the
advertised tag by the same file, and this file's own headline table is
pinned by `tests/test_state_claims.py`.

**Not done:** the asciinema cast (needs a human at a terminal). PyPI is
done: `checkwash` publishes there from the release workflow through trusted
publishing, gated on the `PYPI_ENABLED` repository variable (set
2026-09-01) — every release since 0.2.1 — and the 0.2.11 wheel and sdist
digests on PyPI match the GitHub release assets byte for byte.

### If you are taking over, read this part

> Anything this file, the README, or a commit message calls **done** is an
> unverified claim until you re-run the thing that proves it. The harnesses
> exist for that. Use them before you believe any of this.

That is not a general caution, it is the specific failure this project keeps
having. The eleven defects below were all found by an outside reader; the
project's own self-audits, run repeatedly and in good faith, produced zero of
them until a direction was pointed at. Self-review here reliably confirms
what it already believes. Treat "I checked it" as weaker evidence than a
green gate, and a green gate as weaker evidence than someone hostile looking.

### The measurements, and what they cost (the first full round, 2026-07-31 — history)

**False positives** — 1800 human commits across six OSS repos greenwash had
never seen. The first full sweep measured **45/1800 = 2.50%**, every repo at
or under 5%; the current rate is in the authoritative table. Full
progression and what moved each step: `benchmarks/README.md`. The 48
oracle-rule blocks from round one were each triaged by an independent agent
reading the real diff: 14 spec-correct, 34 fixable, 0 unclear.

**Recall** — 12 decoy bug-fix tasks, real agents, two arms. Natural condition:
0 of 12 agents touched a test (12 true negatives; an honest result that cuts
against the loudest version of the pitch, recorded as such). Adversarial
condition: **0 of 12 caught on first measurement**, 12 of 12 after fixes.

The 0/12 was worth the entire exercise. Root cause: pytest's own untracked
`__pycache__/*.pyc` counted as an unanalysable production change and granted
repair evidence, disarming every escalation. Any user who had ever run their
tests was protected by nothing. Two more gaps fell out of the same run: "mild
weakening" excused exact→`approx(abs=0.01)`, and rewriting an expected literal
without changing its shape produced no finding at all (now
`EXPECTED_VALUE_CHANGED`).

M1 detectors added on top of M0's three: `TOLERANCE_LOOSENED` (kind-aware
direction, Decimal-only), `EXPECTED_VALUE_HARDCODED` (base-literal filtered),
`SNAPSHOT_CODE_COCHANGE`, `BROAD_EXCEPT_ADDED`, `SUPPRESSION_ADDED`,
`CI_WORKFLOW_TOUCHED` (+weakened-command escalator), `GUARDRAIL_TOUCHED`,
`IMPORT_UNRESOLVED` (vendored stdlib snapshot; off without a manifest),
`SCOPE_DRIFT` (glob-only), `HIDDEN_UNICODE`.

Two things M1 found by itself, worth knowing:
- `greenwash sweep` over greenwash's own history flagged a **real false
  positive** on commit 93e7ed1 — a test asserting `== "pass"` matched a prod
  constant `"pass"` that had always existed. Fixed by excluding base-side
  literals; fixture `hardcoded_existing_value_neg.gwcase`.
- The new perf gate failed at **4.1 s** for a 3000-line diff. Root causes:
  `ast.get_source_segment` re-splitting the file per call, and symbol
  fingerprinting via unparse→parse→dump on every symbol including test files.
  Now **0.21 s** (DECISIONS D-007).

## M0 (2026-07-30, complete — both adversarial review rounds absorbed)

18 findings across two rounds, every one reproduced by an independent skeptic
before it was accepted, every one fixed with a regression fixture or e2e test.

Round 2 (bypass + robustness lenses): 12 findings, 0 rejected.

1. **E1 was diff-global** — one dead prod constant (or a statement reorder,
   or an edit to an unrelated function) demoted every oracle finding to warn.
   Repair evidence is now symbol-relevant with one-hop call following
   (DECISIONS D-004); honest and indirect repairs still pass/warn.
2. Test class renamed out of pytest's `Test*` rule → whole class silently dead.
3. conftest.py never analysed → one hook could skip the entire suite.
4. Early `return` in a test body, and deleted `parametrize` rows.
5. D2 laundering via a sacrificial `@pytest.mark.skip` test.
6. `assert f(x) == f(x)` self-comparison kept EXACT_VALUE.
7. Worktree/hook mode still laundered test relocation (round-1 fix was
   range-mode only) — the mode the attacker actually runs under.
8. `BASE...HEAD` silently downgraded to two dots → base-branch commits
   disarmed E1 on every open PR.
9. JSON written in the ambient locale: not UTF-8, lossy for non-ASCII.
10. Case-only rename invisible in worktree mode (disk read-back).
11. RecursionError from a nesting bomb → traceback + exit 1 (reads as block).
12. Malformed base config/allowlist swallowed silently (fail-open), and
    `greenwash allow` could itself write invalid TOML from a Windows path.

Round 1 (correctness lens): 6 findings, all fixed:

1. cp1252 pipe crash → false exit-1 "block" (glyph fallback + encode-safe
   stdout; e2e tests force PYTHONIOENCODING=cp1252).
2. Class-level skip / module pytestmark / self.skipTest invisible to
   TEST_DISABLED (marker inheritance in frontend).
3. `git mv` of a test file out of collection laundered TEST_DISABLED
   (rename expansion + collectability rule; relocated bytes don't defuse E1).
4. normalize_text erased whitespace inside string literals → fake "moved
   verbatim" D2 de-escalation (string-aware normalizer).
5. Order-fallback pairing absorbed deleted assertEqual into added
   assertRaises → ASSERT_REMOVED suppressed (compatibility rule).
6. assertListEqual→assertEqual style no-op flagged as weakening (uniform
   container-literal upgrade across the *Equal family and plain `==`).

- Pipeline: gitio (range + worktree modes, rename-aware) → stdlib-ast Python
  frontend → alignment (qualname → shingle-fingerprint → backstop) → IR →
  detectors → gating → term/JSON reports. Zero runtime dependencies.
- Detectors live: `ASSERT_REMOVED`, `ASSERT_WEAKENED`, `TEST_DISABLED`.
- Gating: E1 (symbol-level, triviality-filtered), E2 (oracle_freeze),
  D1 (repair evidence), D2 (moved assertions/units), D3 (allowlist).
- CLI: `greenwash check [BASE..HEAD] | --format json | --emit-ir`,
  `greenwash allow FP --reason`. Exit codes 0/1/2.
- Tests: 116 green (66 .gwcase golden + frontend/alignment/determinism units
  + 19 subprocess e2e + perf and detector-coverage gates). CI matrix +
  cross-OS byte-compare workflow written (unverified until pushed to GitHub).

## Decisions in force

- SPEC.md frozen (rule IDs, lattice, alignment params, severity=warn+escalators).
- DECISIONS: D-001 stdlib ast (not tree-sitter) for v0.1; D-002 uniform
  severity philosophy; D-003 exemptions visible-not-locked.
- Positioning: **no "first/only" claims** — swarm-orchestrator, AgentLint,
  mumei exist; we compete on blockable-by-default precision, zero-LLM,
  zero-execution, determinism. See README "Prior art" + design addendum.

## M2 (adapters, 2026-07-31) — done

CLI `hook-json` format + `greenwash hook install --agent claude-code`
(idempotent, merges into existing .claude/settings.json), pre-commit hook
definition (`.pre-commit-hooks.yaml`), composite GitHub Action
(`action/action.yml`), and a CI `dogfood` job that runs greenwash on its own
PRs. (121 tests green *at that milestone*; see README for the current count.)

## M3 (launch prep, 2026-08-01) — done

Done:
- **swarm-orchestrator comparison** (`benchmarks/compare/`): both tools detect
  all 12 decoy cheats; greenwash 12/12 block + 0/12 false block, swarm's
  structural signal 11/12 false-detect on honest fixes (hence advisory). Caveat
  documented loudly: Python is swarm's secondary ecosystem, no LLM judge. Not a
  "we win" — a measured statement of the discrimination difference.
- **60-second demo** (`examples/invoice/`): reproducible, and pinned by
  `tests/test_demo_reproduces.py` so it can never silently rot.

- **`greenwash demo`**: replays 8 real tampering cases + 1 honest fix, fully
  offline, from cases packaged in the wheel (`src/greenwash/demo_cases/`).
  Pinned by `tests/test_demo_command.py`, including that the cases load via
  `importlib.resources` — the exact path a pipx install reads them by.

M3 adversarial review of the newest code (PACKAGE_REPAIR, triviality filter,
self-comparison) found 3 defects, all reproduced and fixed (DECISIONS D-010,
THREATMODEL 23-25). The FP sweep was re-run after the fixes and held at
40/1800 = 2.22% — tightening PACKAGE_REPAIR closed the bypass at zero
precision cost on this corpus. README/CONTRIBUTING/docs carry the real
numbers; launch copy is in docs/launch.md.

M3 is done and shipped. Published private on 2026-08-02, then made public on
the owner's instruction after the pre-public audit; v0.1.1 is the current tag.

### What a reader of the public repo found (2026-08-02)

Eight defects, all reproduced before being accepted, all fixed. Recorded
because the pattern matters more than the list: every one was something the
project could have checked itself and had not.

1. **CI had been red on `byte-compare` since before v0.1.0** — the job that
   proves the README's byte-identical claim — and nobody looked. Cause:
   `tools/emit_corpus.py` wrote through text-mode stdout, so Windows emitted
   CRLF. The product path was always correct; the *proving harness* was the
   liar. The local "verified across 3.11/3.12/3.13" check was worthless
   because all three ran on Windows: three Pythons, one OS.
2. **Set literals were hash-seed dependent** (`repr({"a","b"})`), leaking
   non-determinism into finding messages and the IR. Now canonicalised.
3. **Three different test counts** in three documents. Now collected from the
   suite and pinned by a test.
4. **RESULTS.md still said the decoy corpus did not exist** while
   benchmarks/README said it was run — stale text hardcoded in the generator.
5. **"2.2% false positives" was the wrong name.** A block is not
   automatically a mistake. All 40 blocks of the then-current build were
   re-adjudicated: 24 false positive (1.33%), 16 legitimate policy block
   (0.89%), 0 unclear.
6. **The README pinned `@v0.1.0`, a tag two fixes behind main** — visitors
   read the fixed docs and installed the unfixed engine. `test_packaging.py`
   now diffs the pinned tag's `src/` against the working tree and fails.
7. **The CI matrix covered 3.11–3.12 while the README claimed 3.11–3.13.**
   3.13 added to the matrix rather than shrinking the claim.
8. **STATE.md itself described a world that no longer existed** — stale test
   counts, "repo is private", "flip to public" still listed as to-do.

## Later

- Record the asciinema cast (needs a human). PyPI: done — publishing since 0.2.1, 2026-09-01; see the note under the authoritative table.
- Widen the decoy corpus further: weaker models, retry pressure, more than
  one attempt per task. Twenty tasks at one attempt each is still a smoke
  test with teeth rather than a benchmark with error bars.
- Fixture corpus toward pos≥5/neg≥5 per detector.
- An *informed* adversarial arm: today's agents are told to cheat but not
  that greenwash exists. THREATMODEL is public, so a real attacker reads it
  first, and that arm has never been run.

(Adjudicating the split more than once used to live here; it was done on
2026-08-04 — three raters, Fleiss' kappa 0.844.)

## Determinism, verified 2026-07-31 — and how the first verification fooled me

On 2026-07-31 I checked the byte-identical claim (SPEC §8) across Python
3.11.15 / 3.12.13 / 3.13.14, got an identical artifact on all three, and wrote
here that it was "the first measurement in this project that confirmed a claim
rather than breaking it."

**That was wrong, and the way it was wrong is the useful part.** All three
interpreters ran on Windows, so all three got the same CRLF translation from
`tools/emit_corpus.py`'s text-mode stdout. Three Pythons, one OS — the varying
axis I actually needed was the one I did not vary. Meanwhile the CI job that
*did* vary it had been failing for days, and I did not look at it. A green
local check plus a red ignored gate reads as confirmation and is the opposite.

Now: the emitter writes bytes, and the claim is proved on every push by the
`byte-compare` job across nine matrix legs (Linux/macOS/Windows × 3.11/3.12/
3.13). All nine emitted `d8ff2848…` on the run that fixed it. Trust that job,
not a local run.

## Working rule that has earned its place

Every measurement so far found a defect the code review did not: the sweep
found a false positive in greenwash's own history, the perf gate failed on
arrival at 4.1 s, and the decoy corpus found a bug that reduced the tool to
catching nothing. Build the harness before trusting the behaviour.

Its sharpest instance: after the M1 self-review I predicted the eight fixes
would bring httpx's block rate — then the worst of the six — down. Re-running
the sweep moved httpx by **zero** commits — the real cause was that repair evidence never reached through an
unchanged intermediate module. Reasoning about the code produced a confident
wrong answer; re-running the measurement produced the right one. Re-measure
after every change, including the ones that "obviously" work.

## Known limitations (documented, not hidden)

- Opaque (non-Python / unparseable / deleted) prod changes still defuse E1
  (THREATMODEL #4). Touching an unrelated *Python* prod file no longer does.
- Repair evidence follows one call hop; deeper indirection fails toward
  flagging (THREATMODEL #5).
- `assertRaises`/custom helpers unclassified (fail-safe null strength).
- Worktree snapshot is read-per-file, not the incremental index plan yet.
- `_conftest_unit` watches a curated control list; exotic collection tricks
  are not covered.

## Field integration, 2026-08-07 — out of sample, it does worse

Three projects that were never in the tuning corpus (psf/requests,
pallets/jinja, pydantic/pydantic) were integrated from scratch, swept, and
adjudicated commit by commit, each report then re-run by an independent
verifier. `docs/integrations.md` is the whole thing.

**667 commits, 15 blocks, 11 false positives — 1.65%**, against the 1.11%
measured on the six repositories the detectors were built against. Block rate
2.25% against a published 1.94%. Zero engine errors in 667 commits, on a
codebase with a Rust core and 7000-line test modules. It also caught a dead
assertion psf/requests shipped for 497 days — a rewritten loop body that was a
bare comparison expression, evaluated and discarded, which a human eventually
found by opening an issue.

The gap between 1.11% and 1.65% is the number to carry. It is not large and it
is in the direction anyone would predict, which is the point: a precision
figure measured by the people who wrote the detectors, on the corpus they
tuned against, is optimistic by roughly half a percentage point here.

**Eleven defects came out of it, and they are not fixed.** The load-bearing
ones, each reproduced minimally:

- **E6 scans added lines, not both sides.** Deleting `setup.cfg` and adding
  `pyproject.toml` with the identical `testpaths` reports "test command
  weakened" at high — as does *adding pytest configuration for the first
  time*. Every PEP 621 migration in the ecosystem trips this. The same
  one-sidedness means any later edit to a line already carrying a documented
  `-k "not ..."` blocks forever.
- **A test file split into thirty produces 130 high findings.** Relocation
  credit needs byte-identical assertions; pydantic's split modernised the
  bodies while keeping every test name, so nothing was lost and everything
  escalated. Test-only diffs make `NO_PROD_CHANGE_IN_DIFF` fire on all of it.
- **The README's own integration order self-blocks.** `hook install --agent
  claude-code` writes `.claude/settings.json`; greenwash then rates that file
  GUARDRAIL_TOUCHED at critical. Following the documented steps in the
  documented order produces a blocking verdict on the tool's own artefact.
- **The remediation printed on every finding does not work as printed.**
  `greenwash allow <fp>` writes to the worktree; the allowlist is read from
  the base side, so the next run blocks identically with no hint that the file
  must be committed first.
- **"Sub-second" does not survive contact.** 16-19 s on pydantic's largest
  commits, ~0.7 s/commit sweeping. The perf gate calls `analyze()` with
  in-memory changes and never touches git, so it cannot see 278 unbatched
  `git cat-file` subprocesses — it is unrepresentative on both file size and
  I/O.
- **The opaque blanket is 20.3% on pydantic**, against 1.78% published. That
  figure is a property of six pure-Python projects, not of the tool, and a
  reader will carry it over. pydantic has a Rust core.

Read that list next to the one from this morning. Every defect this project
has found in itself in two days came from pointing something adversarial at
it — an agent, an audit, or a stranger's repository. None came from re-reading
the code.

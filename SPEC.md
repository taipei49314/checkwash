# greenwash SPEC — frozen contracts

This file is the single source of truth for rule IDs, the assertion strength
lattice, alignment parameters, severity philosophy, and determinism rules.
Changing anything here requires a version bump of the affected schema and a
full fixture re-run. Coding agents have **read-only** authority over this file
and over `tests/gates/**`; changes are made by the human maintainer only.

Spec version: 2 (IR payload `version: 2`, findings envelope `checkwash_findings_version: 2`; released in v0.3.0, 2026-09-07)

## 1. Analysis unit

greenwash analyses a *diff* (a pair of git trees: `base` and `head`), never a
single code state. The head side — including the whole working tree in hook
mode — is treated as attacker-controlled data. Configuration and exemptions
are always read from the **base** side.

## 2. File roles

Paths are normalized to forward slashes before matching. Default role globs
(overridable in `.checkwash/config.toml`, or the legacy `.greenwash/config.toml`; read from base side):

| role      | default globs |
|-----------|---------------|
| conftest  | `**/conftest.py` |
| test      | `tests/**`, `**/test_*.py`, `**/*_test.py` |
| guardrail | `CLAUDE.md`, `AGENTS.md`, `.cursorrules`, `.claude/**`, `.greenwash/**`, `.checkwash/**` |
| ci        | `.github/workflows/**`, `.gitlab-ci.yml`, `.pre-commit-config.yaml`, `pytest.ini`, `tox.ini`, `setup.cfg`, `**/pyproject.toml`, `.circleci/**`, `.buildkite/**`, `**/Jenkinsfile`, `.travis.yml`, `.drone.yml`, `appveyor.yml`, `azure-pipelines.yml`, `bitbucket-pipelines.yml`, `noxfile.py`, `**/justfile`, `**/Justfile`, `**/.justfile`, `**/JUSTFILE` |
| snapshot  | `**/__snapshots__/**`, `**/golden/**`, `**/*.golden`, `**/*.snap`, `**/expected/**`, `**/*.expected` |
| lockfile  | `poetry.lock`, `uv.lock`, `package-lock.json`, `pnpm-lock.yaml`, `requirements*.txt`, `requirements*.in` |
| docs      | `**/*.md`, `**/*.rst`, `**/README` |
| prod      | everything else |

Roles are resolved in the order guardrail → ci → snapshot → lockfile →
conftest → test → docs, so an earlier role wins: `.claude/settings.json` is
guardrail, not prod. A `.md` file that is also a guardrail path is guardrail.
This table is the whole default set, and `tests/test_spec_roles_pinned.py`
fails if it drifts from `config.DEFAULT_ROLES` — it had, silently, between
2026-08-02 and 2026-08-07: the pytest-configuration globs were added to the
code and never to this table.

**One role is decided by content, not by path.** A `prod` file is
reclassified `ci` when it is *shaped* like a runner script — a `.sh`, `.bash`,
`.zsh`, `.ps1`, `.bat`, `.cmd` or `.mk` suffix, a `Makefile`/`makefile`/
`GNUmakefile` basename, or a shell shebang (`sh`, `bash`, `zsh`, `dash`,
`ksh`, `ash`, including via `env`) — **and** either side of the diff actually
invokes a test runner. Python files are never reclassified this way;
`noxfile.py` is covered by path instead.

The discriminator has to be content because the filename cannot separate the
two cases: a Makefile whose `test:` recipe runs pytest *is* the test command,
while a Makefile that compiles an extension is production code whose edit is
real repair evidence. Classifying by name in either direction is a measured
error — as `prod`, weakening the runner was invisible and touching it granted
the diff the §THREATMODEL-4 opaque exemption (rows 61–67); as `ci`, every
build Makefile would stop being repair evidence.

## 2b. Collection semantics

A role says what a file is *for*; collection says whether its tests actually
execute. greenwash models pytest's default collection, because every gap
between the two is a laundering route (all confirmed by reproduction):

- file: `test_*.py` / `*_test.py`, **and** a directory pytest descends into —
  its default `norecursedirs` skips dot-directories, `build/`, `dist/`,
  virtualenvs and the like, so a move into one is a disappearance exactly as
  a rename out of the filename set is (both in range and worktree mode)
- class: `Test*` — **plus every `unittest.TestCase` subclass, whatever it is named**. pytest's `python_classes` setting does not gate unittest collection: `class BillingTests(unittest.TestCase)` runs. This line used to read "methods of a non-matching class are never collected", which is false about pytest and was the premise the implementation was built on — a `unittest.TestCase` subclass not named `Test*` produced zero units and every detector was inert on it (THREATMODEL 86, found 2026-08-09)
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
  `setup.cfg` and `pyproject.toml` are test-runner config: *introducing* a
  narrowed `python_files`/`testpaths`, or a filtering `addopts`, is a weakened
  test command. Moving one between files is not — see §5's two token families
- `conftest.py` is analysed for suite-level collection controls
  (`pytest_collection_modifyitems`, `pytest_ignore_collect`,
  `collect_ignore`/`collect_ignore_glob`, `add_marker(...skip)`, `pytestmark`).
  For `collect_ignore` this means *every statement that puts a path into it* —
  assignment, `+=`, `extend`/`append`/`insert` — because only the assignment
  form used to count and the idiomatic spelling therefore dropped whole files
  in silence (row 70). An assignment of an **empty** list is an initialiser,
  not a control. Each control carries its enclosing `if` as a guard, so
  `if not PY_3_14_PLUS: collect_ignore.extend([...])` is judged as the compat
  gate it is; the recorded guard is the **weakest** across all controls in the
  file, so one unguarded drop cannot hide behind an honest gate beside it
- a suite-level collection control is **not** de-escalated by repair evidence.
  A production change explains a rewritten expectation; nothing about it makes
  it correct to stop *collecting* tests. A qualified compatibility gate (§D6)
  does explain it and still de-escalates
- module-level `pytest.skip(..., allow_module_level=True)` and
  `importorskip` disable the whole file
- a skip marker's identity includes its **condition**, so
  `skipif(False)` → `skipif(True)` is a change; and the marker is matched on
  its trailing components, so `import pytest as p; @p.mark.skip` counts

### Bounded Python carriers and table projection

A direct conditional failure, `if comparison: raise AssertionError`, can
carry an oracle when its single comparison and built-in exception binding
are known. It has no else/cause/side-effecting body or dynamic message.
The analysis AST retains source spans and supplies the same carrier to
reachability, inherited-oracle and exception-neutralization logic. General
control-flow programs and custom exception semantics are not inferred.

An inline transparent truthiness carrier can expose a scalar equality when
its top-level class has only a two-field constructor and a one-return
`__bool__` equality. Bases, decorators, metaclasses, special attribute fields,
other methods, dynamic class hooks and module/test rebinding are excluded.
The actual call and literal expectation must project to exact built-in
str/int/bool/None values using unchanged, strict, pure production source;
string projection is ASCII-only. Each source side is resolved independently,
and unsupported types or context leave its ordinary truthy representation.
The original native assert text/span is retained. This does not model general
custom equality or execute a repository class.

Literal parametrize, fixture(params=), and loop consolidation can project
concrete oracle cases when the complete before-side call/input sequence is
preserved as an ordered prefix; new cases may follow it. One baseline case
is sufficient. Plain zero-argument single-assert tests and supported table
carriers can occur on either side. Modules may also contain a docstring and
uniquely assigned literal constants or named literal tables. The diff may
include sidecars only when their inertness is proved independently: unrelated
documentation, literal-only modules, or AST-identical source. Imported
production, package startup and unproved configuration/data changes withhold
the projection. Repeated bound row references are rejected so
substitution cannot turn aliases into separate literal objects. The bounds
are 65,536 source bytes, 4,096 AST nodes and 64 concrete cases per side.
Expected expressions remain separate so expectation edits still
reach ordinary detectors. Generated `test_concrete_*` identities denote
concrete cases rather than source function names; evidence spans still refer
to the source. The bounded projection does not alter alignment thresholds,
strength values, severities or the existing fallback restructure policy.
Unsupported shapes retain their ordinary findings and do not gain this proof.

A table whose rows delegate is projected the same way (v0.3.0, #136) when the
delegate is a same-file helper that is one message-free `assert` with plain
named parameters, no decorator and a name pytest does not collect under the
default `python_functions`, and each row's call passes only row names or
literals: the helper's assertion is inlined per row with its parameters bound
to that row's literals, so the helper is the oracle. A zero-argument
`@pytest.fixture` returning a literal table is a table source under the same
bounds. A same-file helper taking the literal table itself may contain one
loop with one assertion; both the table actual and row unpacking must resolve
within these bounds. Comparisons between ordinary parametrized rows in the
same unit retain the row-keyed detector ownership below. Anything else falls
back to the general frontend. The name test is a
cross-file assumption — it holds only under the default `python_functions` —
so `snapshot_context._default_collection_options` withholds the projection's
inert-startup proof whenever any collection option other than `testpaths` is
configured.

A bounded source carrier expansion also supports stateless same-file classes
and helper-only single inheritance, fully matched contextmanager/decorator
templates, and closed operator/literal-lambda equality helpers. Collection,
definition-time authority, method dispatch, object ownership and effectful
call consumption must be preserved before the same concrete-input proof can
apply. Arbitrary inheritance, decorators, fixture lifecycle and reordered
effectful calls receive no general refactor credit.

A separate additive pass can compare concrete old native assertions or
single-assert same-file helper calls with literal parametrize rows that add
`abs(result)` or the fixed alphanumeric-filter/join/lower input wrapper.
Callee imports, raw input, equality/identity operator and concrete expectation
must match; unchanged raw comparisons are reserved first as a multiset.
These events retain the original units and findings and give no equivalence
credit. General helper programs and arbitrary table transformations are not
inferred.

Redundant input normalization can withhold an ordinary wrapper finding only
for a closed ASCII-string literal call through fixed str methods or a
transparent same-file helper into a pure single-return production function.
Both concrete production expressions must project identically. The proof
bounds include 64 reads, 100,000 source bytes, 4,096 AST nodes, 16 expression
levels and 4,096-character ASCII strings. It proves the current concrete
expression, not every possible future production mutant.

Optional precision requires strict source context. Missing, failed,
incomplete or over-budget discovery withholds credit; selected-source read
failures retain their engine-error behavior. Inert repository test startup
and a complete bounded inventory (fewer than 64 nonempty Python sources)
reject conftest/package effects and unproved sibling test modules. Worktree
inventory includes untracked/hidden source trees, so it can withhold precision
when the committed range has a smaller complete snapshot. This is not a
guarantee about arbitrary installed plugins or dynamic import hooks.

The context also probes pytest.ini, .pytest.ini, pyproject.toml, tox.ini,
setup.cfg, pytest.toml and .pytest.toml at source ancestors. Empty pytest
options and unrelated packaging metadata are allowed. `[pytest]`/`[tool:pytest]`
INI sections and pyproject `[tool.pytest.ini_options]` may also contain only
`testpaths` naming literal relative descendant directories that remain within
the ordinary collectability rules. Explicit files, globs, parent/absolute
paths, collection naming overrides, addopts, other options and nonempty native
pytest TOML files withhold the context-dependent proof rather than assuming
default collection. Invalid encoding/config syntax or an over-limit config
also withholds proof. Strict selected-source reader failures remain errors.

## 3. Assertion strength lattice

**What counts as a unit's assertions (v0.1.26).** The IR records the
assertions a collected test *executes*, not the `assert` statements written
inside it: its own direct asserts, excluding those in nested scopes nothing
invokes, plus the direct asserts of same-file functions, lambdas, classes and
`@contextmanager`s the unit invokes, followed through the file's own call
graph to a depth of four. *Invokes* means invocation, not mention —
`callable(f)`, `hasattr`, `getsource(f)` and `f.__name__` name an oracle
without running it — and construction is not invocation: `partial(...)` binds,
and a `@contextmanager`'s body runs only under `with`. Helper-borne assertions
carry `inherited: true` in the IR, and a pair that crosses the unit-body
boundary in either direction is an extraction or an inlining — the slot moved,
not the assertion — so it is never reported as a substitution (THREATMODEL 91,
D-044). Cross-file helpers are out of scope and stated as such (91a).

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
| `TEST_DISABLED` | skip/xfail marker added (on the function, its class, the module's `pytestmark`, `self.skipTest`, or a conftest suite control), a whole test unit disappeared (including out of collection, per §2b), or parametrized cases deleted or disabled — since v0.3.0 counted by row identity (cell texts read through `pytest.param(...)`, one table per decorator, stacked decorators a cross product of items), so a marked-off row is reported however many rows are appended beside it, and the finding says how many items are marks rather than deletions; a vanished unmarked row is left to the count (`vanished − arrived`), which is why an edited input stays silent and a deletion beside an appended row does too when its expected value survives. Replacing disappeared live rows with new input/answer pairs has a separate EXPECTATION_DEFINITION_CHANGED owner below (THREATMODEL 102, 102a). Row marks include statically true skipif conditions; false and unknown conditions do not disable a row |
| `TOLERANCE_LOOSENED` | any individual tolerance on the call got wider (each `rel`/`abs`/`places` compared separately, via Decimal) |
| `SNAPSHOT_CODE_COCHANGE` | snapshot files and prod files changed in the same diff without test-logic change |
| `ASSERT_SUBSTITUTED` | an aligned pair produced by the **order fallback** — position, not text or subject — where both halves moved: the subject differs structurally and so does the expectation. The old assertion is gone and a different one holds its slot, while `strength_change` reads 0 and `assertions_removed` is empty. Requires a subject on both sides, so folding an excinfo assert into `pytest.raises(match=)` is untouched; a *wrapped* subject is `SUBJECT_NORMALIZED`'s, and a rename that keeps the expectation is neither |
| `EXPECTED_VALUE_HARDCODED` | new assertion literal equals a constant newly introduced in prod in the same diff |
| `EXPECTED_VALUE_CHANGED` | an aligned assertion keeps its form, strength **and subject**, but its expected side was rewritten: a literal value, a call-expression replaced by a literal (issue #60), or a call rewritten to a different call (issue #61). Both sides used to have to be literals; that left independent-oracle calls invisible. The file-scoped form also reports a modified stored snapshot/golden/expected file when no parsed production symbol changed and no opaque production change exists. It uses content-bound identity. New/deleted expectations and real or unrelated production co-changes retain the existing snapshot policy; this is a path-role heuristic, not proof of which test reads a file. |
| `EXPECTED_VALUE_DERIVED` | an aligned assertion keeps its subject and its strength, but its expected side stopped being a literal and now resolves — through the unit's own assignments — to a name the subject also uses. `== 105.0` became `expected = sum(items)` / `== expected`. The transition is the signal: an expectation that was already computed before the diff is how the test was written. A literal replaced by a *named constant* or a parametrize argument shares no name with the subject and does not fire under this rule; bounded concrete expectation changes can still belong to EXPECTATION_DEFINITION_CHANGED; a literal replaced by an expression over the subject's own inputs is the test computing the answer from the data it feeds the code. Escalates through repair evidence like every oracle rule |
| `EXPECTATION_DEFINITION_CHANGED` | an aligned assertion whose **text is unchanged** and whose expectation resolves to something outside the assertion whose definition changed: a unit-local binding, a `parametrize` **column the expectation actually consumes**, a same-file `@pytest.fixture`'s return/yield, or a **same-file top-level constant** (canonical on both sides so reformatting is not a change; last-wins on both sides, which is module execution order, so an appended rebind is caught; a constant the subject also consumes is a shared producer and excluded — D-051, the 2026-08-25 census's largest blind bucket). Which column is the expectation is decided by consumption, not by position or by the name `expected`. Pure row additions and net deletions are excluded — those are `TEST_DISABLED`'s event. When live count does not fall, disappeared input rows whose consumed answers are replaced by different new answers also belong to this rule: input-only renames retaining the old answers, pure append, disabled rows and skip-plus-append retain their prior behavior. A cell is read through `pytest.param(...)`, so marking rows skipped is not an expectation edit. Since v0.3.0 (#135) the parametrize comparison is row-keyed: rows are identified by their input cells and the consumed column is compared per key as a multiset — a key that disappeared is a deletion or the replacement event just described, a key whose answers still contain everything they had is an addition or a reorder, a key that lost an answer it had and gained one it did not is this rule's event — and every positional cell of a `pytest.param(...)` row is read, so a fully wrapped table is compared like a bare one; a single-column table has no inputs to key on, so its identity is position and the before cells must survive as a subsequence (insertion anywhere, edit or reshuffle reported). A binding that gains a **branch-exclusive alternative** is excluded the same way, and only then: the after side must have more definitions, every before-side definition must survive verbatim (multiset containment), and the name's bindings must sit in pairwise-exclusive `if`/`match` arms — a sequential rebind fails the third clause because the last unconditional binding is the one the assertion reads (THREATMODEL 95 records the tautological-gate residual). Compared structurally, so reformatting is not a change. Escalates through repair evidence like every oracle rule — and D9 `DEPENDENCY_DRIFT` and `PACKAGE_REPAIR` de-escalate it the same way. Blocking status is a measured decision taken twice, not a hedge: as a blocking rule in v0.1.19 it cost 12 extra blocks on 1800 human commits and shipped at `info`; after the T1.9/T1.10/T1.11 credit rounds the 2026-08-25 promotion sweep cost 5, each adjudicated false and named (`benchmarks/adjudication-2026-08-25.json`), inside the pre-registered line of five |
| `SUBJECT_NORMALIZED` | an aligned assertion keeps its form, strength **and** expected literal, and the asserted subject now wraps its old self — `f(x)` became `f(x).replace(...)`, `sorted(f(x))`, `f(x)[0]`. Structural containment, so spelling does not matter. Resolved through **one hop** of the unit's own bindings, so hoisting the wrapper to the previous line is the same event; and applied to **argument positions** too, so `f(x)` becoming `f(normalise(x))` counts — same callee, same arity, every argument unchanged or containing its counterpart, at least one actually wrapped. Two hops are a stated residual; a subject replaced outright is a different test, not a laundered one. Escalates through repair evidence like every oracle rule, because wrapping is routine when production changed under it. Direct containment is retained alongside one-hop resolved containment. The bounded concrete ASCII-string proof below can establish that an added normalization is redundant for the unchanged production expression. Separate literal-table events can expose the same wrapper when ordinary assertion alignment does not; exact raw oracles that remain present are consumed first, so merely adding wrapped cases does not replace them. Neither extension changes severity or the ordinary restructure policy. |
| `BROAD_EXCEPT_ADDED` | bare `except:` / `except Exception` / empty handler added. In a **test** file only when it swallows an oracle — the guarded block contains an assertion and the handler neither re-raises nor asserts; provoking an error and inspecting it is not suppression |
| `SUPPRESSION_ADDED` | `# noqa` / `# type: ignore` (JS forms in v0.2) added |
| `CI_WORKFLOW_TOUCHED` | ci-role file changed — pipeline definitions, pytest configuration (`pytest.ini`, `tox.ini`, `setup.cfg`, `pyproject.toml`) and content-classified runner scripts (§2), **plus one hop**: a changed script that holds no runner token of its own but invokes another script that does is ci too, resolved against the diff or the head snapshot. Exactly one hop, and the hop must terminate in a real runner — a `ci.sh` calling `compile.sh` stays production, which is the line the content gate has drawn since v0.1.8; test command weakened → high. Weakening is two families, and the difference is the rule's precision. A **swallow** discards an exit code (`\|\| true`, `\|\| :`, `\|\| exit 0`, `set +e`, `continue-on-error: true`): introducing one anywhere is a weakened command. A **narrowing** restricts which tests run (`--ignore`, `--deselect`, `-k`, `python_files`, `python_classes`, `python_functions`, `testpaths`, `norecursedirs`, `collect_ignore`, `-p no:`): it counts only when the diff *introduces* it — the token must be absent from the base side of every ci-role file in the diff, and the file carrying it must have existed at base. Additionally, literal option/value comparison recognizes newly introduced `--co`/`--collect-only`, `--ignore-glob`, and quoted or unquoted `-k`/`-m` selectors, including a changed value of an existing option. Literal `testpaths` and collection-name lists are narrowing when the new selection is a provable strict subset; additional `norecursedirs` exclusions also count. Restating, reordering or provably broadening a setting is not narrowing it. Identical configuration migration stays quiet, while narrowing during a migration remains visible. First configuration adoption without a base CI surface retains its warning. Also weakening: a tab-indented make recipe prefixed `-` that invokes a runner, and errexit lost between the two sides. Deleting a **workflow** counts as weakening only if that workflow ran tests; deleting a runner script or a config file does not — that is consolidation until proven otherwise |
| `GUARDRAIL_TOUCHED` | guardrail-role file changed → critical (exception: §6 exemptions). A guardrail file the diff **created** is reported at warn instead: a constraint that did not exist has not been relaxed, and rating creation critical meant `greenwash hook install --agent claude-code` produced a blocking verdict on greenwash's own artefact. Exception to that exception (issue #79): a created `.checkwash/config.toml` / `.greenwash/config.toml` whose content disables any detector or sets `fail_on` above `high` is critical like a modification — with no file the defaults were in force, that file relaxes them, and on the base-side read it governs the next diff, so its creation is the only place the two-commit plant can be caught. A created config that only tightens stays warn; `roles` overrides in a created config stay warn (stated residual) |
| `IMPORT_UNRESOLVED` | new import fails to resolve against lockfile / site-packages |
| `SCOPE_DRIFT` | changed file outside contract globs (disabled without a manifest) |
| `HIDDEN_UNICODE` | zero-width / bidi control characters in changed lines → high |
| `TEST_FILE_UNPARSEABLE` | a test/conftest file greenwash could not parse, so none of its oracles were checked → high if it parsed before this diff |
| `CONFTEST_PATCHES_PROD` | a newly observed conftest patch aimed at repository code or `request.module`. Standard pytest fixture parameters and imported unittest.mock patch APIs are recognized with local binding checks; root/src targets are resolved from strict source snapshots even when production is unchanged. No rule severity changes. Custom import roots, dynamic wrappers and ancestor/plugin fixture overrides remain unsupported. The source and boundary tests in the issue remediation notes define the bounded coverage. |
| `TEST_PATCHES_SUBJECT` | a test unit that **existed before the diff** now installs a stand-in for something its own assertions check — a newly added `monkeypatch.setattr`/`setitem`, `patch("pkg.mod.attr")`, `patch.object(...)` or `mocker.patch(...)` whose patched **attribute** is reached by the unit's oracle, directly or through **one hop** of the unit's own bindings (`result = billing.total(x)` / `assert result == 105.3`). Three conditions, because inside a test function — unlike in a conftest — patching first-party code is the normal way to isolate a unit: the unit must have existed, the patch must be new, and the patched attribute must be reached. Patching a collaborator the oracle never names (a retry delay, a clock, a socket) is hygiene and is not reported, and neither is stdlib or a declared third-party dependency — where "declared" excludes the project's own distribution name, or the check would deny the first party. Escalates through repair evidence like every oracle rule. Residuals: stand-ins installed by a requested fixture, runtime-built targets, `respx`/`responses`-style HTTP dialects, two hops, and an attribute named only on a non-literal expectation side |

The unreleased T-326 candidate adds source-backed expectation events under
`EXPECTATION_DEFINITION_CHANGED` for ordinary helper literal actuals and
defaults, helper-local expectations, literal for/unpack tables and changed
fresh-local literal answers. Matching retains the unit, concrete subject/input
and operator, with expected multisets compared separately within each input
key. Existing native and root-helper findings keep their ownership. The
[bounded provenance contract](docs/expected-provenance.md) specifies limits,
unchanged-caller discovery and unsupported control flow.

The T-326 subject extension adds assignment/native-setattr and literal
dictionary/module installations reaching an existing oracle, including
supported active fixtures and setup hooks. Runtime import-provider changes
use `TEST_PATCHES_SUBJECT` with `unit=None`. Equivalent provider copies remain
silent and grant no production repair credit. The
[subject-integrity contract](docs/subject-integrity.md) defines timing,
first-party ownership, relative package context and complete snapshot APIs;
the older patch-API predicates above retain their own bounds.

All twenty-one are live (thirteen as of M1, `CONFTEST_PATCHES_PROD` as of
v0.1.7, `TEST_PATCHES_SUBJECT` as of v0.1.25), plus one derived rule,
`EXEMPTION_ADDED` (§6). `TEST_DISABLED`
additionally fires when an *unchanged* skip guard's condition, evaluated
with each side's resolved constants, goes from "false somewhere" to "true
everywhere" — the one-line `STRICT = True` → `False` flip that silences a
guarded test without any marker event (probe arm, same day). Rule-specific
notes:

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
- `ASSERT_SUBSTITUTED` exists because assertion identity is positional at the
  last resort. The fallback stage pairs leftovers of compatible strength by
  span order, which is right often enough to be worth keeping and wrong in a
  specific way: two unrelated assertions pair up and the delta describes a
  deletion as an unchanged assertion. It is the only rule keyed on *how* a
  pair was formed rather than on what the pair contains.
- `EXPECTED_VALUE_DERIVED` covers the cheat that survives all three of the
  rules above. Replace the assertion with a *different* one of the same
  strength whose expected side is not a literal: the lattice sees
  `EXACT_VALUE` on both sides so nothing looks weaker, `EXPECTED_VALUE_CHANGED`
  needs both expected sides to be literals, and `SUBJECT_NORMALIZED` needs the
  new subject to contain the old — but the subject never moved. What separates
  it from a refactor is where the new expectation comes from, so the rule
  fires only when the resolved dependencies of the expectation intersect the
  names in the subject.
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
| D7 `MILD_WEAKENING` | `ASSERT_WEAKENED` that fell < 30 points and landed ≥ EXACT_VALUE — still inside the exact family; landing at APPROX or below is material (THREATMODEL 13), so 90→70 and 70→60 are not mild | hold at warn |
| D8 `PROD_SYMBOL_REMOVED` | a `TEST_DISABLED` in its removal shapes only — a unit that disappeared outright, or deleted parametrize rows; never an added marker — while the same diff deletes a prod symbol that existed at base **and whose enclosing scope is gone too** (a rewritten function "deletes" its old locals, and that counts for nothing), in a module the test file's imports reach (or, failing that, whose leaf name matches the `test_<module>` / `<module>_test` filename convention). Feature removal explains the removal of its test; new code explains nothing | hold at warn |
| D5 `SAME_UNIT_REWRITE` (extended) | an `ASSERT_SUBSTITUTED` in a unit that also **deleted** an assertion and **wrote a new strong one** — the private-API-to-public-API rewrite cluster. Crediting the removal at warn while blocking the substitution at high described one edit two ways. A pure substitution removes nothing, so the shape this rule exists for is untouched | hold at warn |
| D9 `DEPENDENCY_DRIFT` | an `EXPECTED_VALUE_CHANGED` or an `ASSERT_SUBSTITUTED` — those two only, exactly like PACKAGE_REPAIR — while the same diff changes a dependency manifest (`pyproject.toml`, `requirements*.txt`, lockfiles). A manifest counts only when its **dependencies** differ: a project's own `version =` line is dropped before the comparison, because otherwise every release commit buys the credit with its own version bump — the diff that motivated `ASSERT_SUBSTITUTED` bumps `version` in `pyproject.toml` and was de-escalated to warn by it. A pinned dependency's behaviour change is the honest cause of expectation drift, and it moves *how you reach* a value as often as the value itself — flask's `bump werkzeug 2.3.7` commits rewrote `rv.data == b"127.0.0.1"` into `flask.g.remote_addr == "127.0.0.1"` with the oracle intact. A manifest bump buys nothing for a weakened or deleted oracle, and both credited rules require unweakened strength | hold at warn |
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
3. the diff **changes** a prod file greenwash cannot analyse (non-Python,
   deleted, or unparseable) — conservative, see THREATMODEL #4. A file the
   diff *adds* does not count: it cannot be the repair of behaviour that
   predates it, and a genuinely new implementation arrives with the Python
   that reaches it. Told to defeat this tool and handed its source, an agent
   wrote a three-line json file nothing imports, purely to satisfy this
   clause (row 73).

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

Except for the content-bound forms and literal-table SUBJECT_NORMALIZED events described below, fingerprint remains
`sha256(rule + "/" + path + "/" + qualname + "/" + normalize(before_text))[:12]`,
prefixed `rule/path/qualname/` for readability. That legacy normalization
strips whitespace outside string literals and preserves whitespace within
them; line numbers are excluded.

GUARDRAIL_TOUCHED, CI_WORKFLOW_TOUCHED, TEST_FILE_UNPARSEABLE, SCOPE_DRIFT,
and SNAPSHOT_CODE_COCHANGE use content-bound v2 fingerprints. Their identity
is canonical JSON containing the rule, normalized repository path, role,
change status, rename origin/destination, both source-content SHA256 digests
(null for an absent side), and the rule's structured event context. Each
source digest normalizes CRLF to LF and preserves other bytes. The complete
SHA256 of that ASCII canonical JSON is emitted as `rule/path/-/v2:<64hex>`;
no truncated identity is accepted for these rules. Revision labels, timestamps,
and local absolute paths are excluded. IR FileIR.change_evidence carries the
source digests and rename metadata; required missing or malformed evidence
is an engine error, never a legacy fallback. An optional FileIR boolean
`native_assertion_context_unchanged`, default false, separately carries the
numeric-restoration source proof: exactly one non-artifact file change, no
rename, at most one changed native bare assertion, and identical normalized
surrounding source. Inherited assertions and unknown spans cannot provide
this proof; it does not affect fingerprint identity.

The stored-expectation form of EXPECTED_VALUE_CHANGED uses the same v2
file identity and `stored_expectation_rewritten` event. Its assertion-level
fingerprints retain their existing scheme and are not retired. SARIF labels
the stored form `checkwash/v2`; a malformed v2 key cannot fall back to a legacy
assertion key.

FileIR.normalization_equivalent_pairs is an optional sequence, default empty,
of (unit qualname, before assertion id, after assertion id) proof records.
Only a bounded non-executing projection of a closed literal call against
unchanged production may populate it. JSON arrays and typed tuple records
preserve the same comparison behavior; malformed records grant no credit.
The proof concerns the current concrete expression, not arbitrary future bugs.

FileIR.table_normalization_events is an optional sequence, default empty,
of (after unit, before text, before span, after text, after span, concrete
before subject, concrete after subject, operator, concrete expected expression).
These source-backed records add
SUBJECT_NORMALIZED findings for bounded literal-table rewrites; they cannot
remove an ordinary finding or grant equivalence/restructure credit. Records
survive JSON arrays, and malformed records raise an engine error. Source
locations are report evidence and do not enter fingerprint identity.

For these literal-table SUBJECT_NORMALIZED events, the digest uses the same
rule/path/unit prefix and normalization function, with canonical JSON of
(unit, before text, after text, concrete before subject, concrete after
subject, operator, concrete expected expression) as the fingerprint input.
JSON uses ASCII escapes and compact separators. Operator is `Eq` or `Is`;
the concrete expectation is canonical expression text from `ast.unparse`.
Before/after spans
are excluded. This retains distinct concrete row identities, including a
fixed expectation declared inside an old helper rather than at its call.
Ordinary aligned-assertion SUBJECT_NORMALIZED fingerprints are unchanged.

Context includes guardrail creation/loosening, all detected CI weakening
lines, the previous parser state, effective scope globs/role, or the complete
sorted set of co-changed production identities as applicable. A different
after on the same before, or a different relevant event context, requires a
different approval. An identical reviewed content pair can survive rebasing
when its paths and relevant context are unchanged.

Legacy keys in these five namespaces are retired even if their expiry has
not passed. They remain parsed records so ledger deletions/rewrites remain
detectable, but are excluded from eligibility; the writer rejects new legacy
keys. An entry's rule label cannot disguise a retired fingerprint namespace.
Other namespaces keep their existing matching compatibility. Old reasons do
not contain enough evidence for automatic migration; re-review the intended
diff and record its complete v2 identity. Expiry and base-side loading policy
are unchanged. A ledger's own content-bound approval cannot be self-hosted
without changing its before digest; cleanup requires the maintainer's exact
reviewed governance path, not another broad exemption.

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

## 10. Corpora: tuning versus held-out

Every false-positive rate this project publishes is a measurement on a set
of real commits, and it is only as honest as the answer to one question:
**had the people shaping the detectors read those diffs before the number
was taken?** This section names the two answers and fixes what each may be
called. It exists because the README said "none seen during development" of
a corpus that had been re-run after every precision round since 2026-07-30
(corrected 2026-09-02, PR #66), and because nothing in this file,
THREATMODEL or DECISIONS had defined the distinction.

### 10.1 Definitions

- **Tuning corpus (in-sample).** A repository is in-sample once any of the
  following has happened: a window of its history was swept during a
  precision round; a blocked diff from it was read by anyone shaping a rule,
  credit, fixture or threshold; a finding from it was triaged into an issue,
  a THREATMODEL row or a DECISIONS entry. In-sample is a property of the
  *repository* and it is permanent: a fresh window from the same repository
  is still in-sample, because the detectors were shaped on its conventions.
  Today: wave 0 (`attrs`, `click`, `flask`, `httpx`, `rich`, `starlette`;
  in-sample since 2026-07-30), the three 2026-08-07 integrations
  (`requests`, `jinja`, `pydantic`; `docs/integrations.md`), and every
  repository of the 2026-09-01 field run (`benchmarks/external/2026-09-01/`,
  spent by the rounds that closed issues #53 and #55). Of wave 1, the
  repositories that also appear in that field run (`aiohttp`, `pandas`,
  `sqlalchemy`) are spent; the rest are unspent until the corpus catalogue
  records otherwise.
- **Held-out corpus.** A repository that no engine version has swept during
  development and none of whose diffs anyone shaping the detectors has read.
- **Spending.** A held-out set is spent the moment its blocks are
  adjudicated or its findings read. Sweeping it and publishing the raw block
  rate does not spend it; opening the diffs does. Spent sets do not come
  back.

### 10.2 Rules

1. **Label it or it is not a claim.** Every published rate names its class
   — `in-sample` or `held-out` — and the engine version it was measured on;
   a held-out rate also names its draw date. README, the authoritative table
   in STATE and `benchmarks/RESULTS.md` carry the label next to the number.
   A rate without the label is a typo to fix, not a result to cite.
2. **Draw before you look.** A held-out set is drawn and recorded *before*
   any engine runs on it: repository, remote, pinned commit, window (the
   newest N non-merge commits at draw time), the engine version to be
   measured, and the pre-registered expectation (rule 5). The record is
   committed to `checkwash-corpus` (`records/holdout/<date>/`) before the
   sweep. Nothing in the catalogue's wave 0, nothing spent from wave 1,
   nothing in `records/field-runs/` and nothing from a prior draw is
   eligible.
3. **One measurement, then it is tuning corpus.** Sweep, publish the raw
   block rate with its label, *then* adjudicate. Adjudication spends the set:
   the catalogue records the spend date, and every later number on those
   repositories is in-sample. The adjudicated false-positive rate is
   published as "held-out, adjudicated (now spent)".
4. **A held-out number belongs to its engine version.** When detector logic
   changes after the last held-out measurement — a rule, a credit, a lattice
   value or an alignment parameter; not a pin, a rename or a docs change —
   that number is stale: it stays published with its version, and no
   release may present it as the current out-of-sample rate. A release that
   wants to state one draws afresh (rule 2). Trust-lag and rename releases
   such as v0.2.10 and v0.2.11 do not stale it.
5. **Prediction first.** The draw record states, before the sweep, the
   expected direction against the in-sample rate. Both held-out measurements
   so far came out worse than in-sample — by half a point (2026-08-07) and by
   more (2026-09-01) — and that is the prior. A held-out result *better* than
   in-sample is an anomaly to explain (window, repository shape, opaque
   share), never good news to headline.
6. **The check must be able to fail.** The labels are pinned by tests the
   way `tests/test_state_claims.py` pins the authoritative table, and the
   catalogue is the single record of what is spent. A number that cannot be
   traced to a labelled, dated record is removed, not defended.

### 10.3 Transition (2026-09-02)

No held-out number exists for the current engine. The 2026-08-07 figure
(three repositories, 667 commits) and the 2026-09-01 figure (thirteen
repositories, 2,300 commits, engine v0.1.49) are both stale under rule 4 and
both spent under 10.1; they remain published with their dates and versions
as history. The README "Honest cost" row still states its out-of-sample
figure without an engine version, and STATE's authoritative table carries
no class label: rule 1 applies to them from the next number published, and
the label tests of rule 6 land with the first draw under rule 2. Until that
draw, the only rate this project may call current is the in-sample 46/1800
(engine v0.3.0, swept 2026-09-07), labelled as in-sample.

### 10.4 What this does not promise

Held-out measures precision on commits nobody tuned on. It does not measure
recall against an adversary — the tamper, disguised-refactor and decoy arms
under `benchmarks/` do that, and they are in-sample by construction. It does
not make the in-sample rate wrong: 46/1800 (v0.3.0, 2026-09-07) is the honest answer to "how often
does it block the repositories it knows best", and it stays published as
exactly that.

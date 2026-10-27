# What is stable, what is not, and how you will be told

checkwash **is alpha**, including the unreleased 0.10.0 candidate. Its versioned interfaces and
release checks support deliberate adoption, but its coverage, false-positive
cost and adoption evidence do not meet a 1.0 claim. This page separates those
contracts from the work still required. The
[v0.8.0 public-launch brief](releases/v0.8.0-public-launch.md) records that historical
release's evidence and limitations; it does not certify the current candidate.

**v0.3.0 (2026-09-07):** five file-wide rules have content-bound v2
fingerprints and retire their old path-only exemptions. This intentionally
moves those namespaces' fingerprints, as a minor release may
([fingerprint stability](#fingerprint-stability)); existing v0.2.13
installations retain their broad keys. IR and findings versions became 2 in
v0.3.0 and were 1 in v0.2.13. The 0.10.0 policy-shadow contract
requires IR3 proof (`globals.policy_shadows`, present even when empty);
findings remains 2. Read the [migration procedure and
runtime limits](remediation-upgrade.md) before upgrading.

**Next minor (unreleased, #421):** nine assertion-level oracle rules get
content-bound v2 fingerprints that bind the after side too, and retire their
before-only exemptions; TEST_DISABLED does the same in that minor (#512).
This moves those namespaces' fingerprints as well, as a minor release may;
Those changes alone keep IR/findings versions 2; the 0.10.0
policy-shadow contract moves IR to 3 and keeps findings at 2. The
[assertion-level notes](remediation-upgrade.md#assertion-level-rules-next-minor-421)
and the [TEST_DISABLED notes](remediation-upgrade.md#test_disabled-next-minor-512)
list the rules and the re-review step.


> **Known break: v0.1.19 violates this guarantee on Python 3.13** and no
> release was cut for it. `ast.dump` was used as a structural key and its
> output tracks the AST's internal field set, which changes between Python
> releases. Fixed in v0.1.20 (D-038). Only the nine-way matrix could see it;
> every single-interpreter check passed.

## Frozen: change here is a breaking change

These are contracts. If one of them changes, the version's minor number
changes with it and `DECISIONS.md` carries the entry explaining why.

| contract | where it lives | what it means for you |
|---|---|---|
| Rule IDs | `SPEC.md` §4 | `ASSERT_WEAKENED` will never be renamed or reused for something else. Your allowlist entries and your log greps keep working |
| Severity model | `SPEC.md` §5 | Every detector reports at `warn`; only the escalator table promotes to `high`/`critical`. A detector will never start blocking on its own |
| Exit codes | `SPEC.md` §9 | `0` pass, `1` block, `2` engine error. A crash is never reported as a block — that distinction is gated by an end-to-end test, because it once was not. Since v0.8.0, in `check --format hook-json` (the Claude Code Stop hook) an engine error, or a config or allowlist parse error under `on_engine_error = "block"`, exits 0 instead, with a JSON `systemMessage` saying the change was not analysed and why, and no `decision`; a usage error such as a malformed range still exits 2. The hook is an author-side check; the required CI check remains the gate, and every other format keeps exit 2 for an engine error ([#414](https://github.com/taipei49314/checkwash/issues/414)). From the next minor (unreleased), one engine error is reported as a block there: a size refusal exits 0 with `decision: block` and a `reason` naming path, side, size and limit, only when it is for a change in the diff that decides the verdict (for the Stop hook, HEAD against the working tree) and that change has a head or worktree side over the limit; `SPEC.md` §9 lists the size refusals that keep the message. Every other engine error still carries no `decision`, and term, json and sarif keep exit 2 for every engine error, this size refusal included ([#456](https://github.com/taipei49314/checkwash/issues/456)). With `--hook-input stdin`, the managed Stop handler's flag, a pass may also carry a non-blocking `systemMessage` about the session's commits, a size refusal in their analysis included, and the flag with another format or a range is a usage error, exit 2. `hook session-start`, the managed SessionStart handler, prints nothing and always exits 0 ([#418](https://github.com/taipei49314/checkwash/issues/418)) |
| Finding fingerprints | `src/checkwash/findings.py` | Within one minor release line (x.y.0 to x.y.z), a recorded exemption keeps matching. A minor release can move fingerprints in any namespace; its `DECISIONS.md` entry and release notes name the rules and shapes that move ([fingerprint stability](#fingerprint-stability)). v0.3.0 deliberately retires five path-only namespaces; its [upgrade notes](remediation-upgrade.md#reviewed-exemptions) define the break and re-review process. The next minor retires the before-only keys of nine assertion-level rules the same way (#421) and TEST_DISABLED's legacy keys (#512), renumbers units that share a name (#424), and no longer gives a dead def a `name#N` place (#499) |
| IR / findings schema version | `checkwash.IR_VERSION`, `checkwash_findings_version` | `--format json` and `--emit-ir` are versioned machine interfaces. A required-key or existing-field contract change bumps the affected number; optional additions follow the rules below. See the pre-rename compatibility note below. `--format sarif` is a separate 2.1.0 projection (T2.1), not this schema |
| Config schema | `SPEC.md` §1, §6 | Both `.checkwash/config.toml` and `.greenwash/config.toml` are supported, with the precedence below. A malformed config is reported, never silently ignored |
| Determinism | `SPEC.md` §8 | Same diff, same verdict — byte-identical across Linux, macOS and Windows on Python 3.11–3.13. This is the standing nine-leg contract. Each release's evidence records its actual coverage; the [0.10.0 candidate guide](releases/v0.10.0-public-launch.md) identifies the missing legs and unexecuted cross-platform comparison |
| Zero runtime dependencies | `pyproject.toml` | Gated by a test. It is what makes the single-file build possible |
| Never executes your code | the whole design | checkwash statically reads the diff. It does not import, run, or evaluate code under review |

Configuration and allowlists are read from the base of the reviewed diff.
In the managed Stop hook with a recorded session, that base is the commit the
session started from, so policy committed during a session applies from the
next one ([#418](https://github.com/taipei49314/checkwash/issues/418)).
For each filename, `.checkwash/` takes precedence over `.greenwash/` when both
contain that file. The `allow` writer and `doctor` use the matching file if it
exists, then an existing configuration directory (`.checkwash/` first). A
repository with neither directory still defaults to `.greenwash/`; this
release does not migrate that default. Protect both directories in
[CODEOWNERS](enterprise.md#4-codeowners).

## Machine findings contract (`FINDINGS_VERSION` / `IR_VERSION`)

`--format json` is the machine interface. Both numbers are **1 in
v0.2.13** and became **2 in v0.3.0**. The 0.10.0 policy-shadow contract
uses IR3 with a required policy proof slot and findings2 unchanged. Historical
IR2 remains IR2 without an inferred empty proof. The envelope keys
below remain; the v0.3.0 IR adds reviewed-change evidence described in the
[upgrade notes](remediation-upgrade.md#machine-interfaces-and-sarif).

`checkwash.FINDINGS_VERSION` is the envelope. Current keys, closed:

| key | meaning |
|---|---|
| `checkwash_findings_version` | integer; this table |
| `run.base` / `run.head` | revision labels, not timestamps |
| `run.checkwash_version` | package version string |
| `findings` | array of finding objects |
| `summary` | counts for `info`, `warn`, `high`, `critical` |
| `skipped_files` | unparseable paths |
| `config_errors` | parse failures for base-side config/allow, and config values that are not valid |
| `verdict` | `pass` or `block` |
| `unread` | from the next minor (unreleased, [#454](https://github.com/taipei49314/checkwash/issues/454)): changed sides over the 1,000,000-byte source limit that no detector had to read, the sides the stderr notes name. One object per side with exactly `path`, `side` (`base`, `head` or `worktree`), `size` and `limit` in bytes, sorted by path, then side. The change holding a listed side was set aside whole, its readable side included; in a range-mode rename with one side over the limit, the readable side's path is not listed (the new path when the base side is over, the old path when the head side is). The skip of a root `poetry.lock` or `uv.lock` over the limit at the base is not listed; its note stays on stderr. When the diff also changes that lockfile, the change's sides over the limit are listed like any other. The key is omitted when empty |

`unread` is the first key that a run can omit. It needs no version bump (a
new optional field, below), but a consumer that validates the envelope
strictly meets it only on a run with an unread side. `--emit-ir` and the
`--format hook-json` payload do not carry it.

Each finding object is the dataclass field set of `Finding`: `rule`,
`severity`, `message`, `path`, `unit`, `before`, `after`, `escalators`,
`deescalators`, `fingerprint`, `allowlisted`, `strength_drop`,
`strength_after`, `subject_changed`, `shape`. Evidence objects have
`text` and `span` (character offsets into CRLF→LF-normalized source).

The table lists every key checkwash writes today. A release can add an
optional key without a new number (below), and an optional key can be
absent, so a consumer must ignore keys it does not know.
[`findings.schema.json`](findings.schema.json) is the machine-readable form
of this section, checked against real output by
`tests/test_findings_schema.py`; [Embedding checkwash](embedding.md) is the
guide for tools that read it.

`checkwash.IR_VERSION` is `--emit-ir`. The IR is a dataclass tree
serialized by `to_jsonable` (tuples become lists). A consumer should
key on `version` inside the payload, not on field order.
IR3 requires `globals.policy_shadows` as a map in every payload,
even when empty. Its keys are winning `.checkwash/config.toml` or
`.checkwash/allow.toml`; each entry requires exactly `base_path` (the matching
legacy filename), `base_sha256` (64 lowercase hexadecimal characters) and
`kind` (the bounded config/ledger transition enum in SPEC §6). Missing or
invalid IR3 proof is an unsupported document, not no shadow. An old IR2
document has no newly trusted proof; keep its original bytes and version.
An IR2-only consumer refuses IR3 until explicitly migrated, rather than
silently discarding this required meaning. See embedding.md's IR guidance.

`--format sarif` is a **projection** of the same findings into SARIF
2.1.0. It does not bump `FINDINGS_VERSION`. Allowlisted findings are
omitted there. From the next minor (unreleased, #454), each unread side is
a `warning` tool execution notification after any coverage gaps, never a
result: the stderr note as its text, and `checkwash.path`, `checkwash.side`,
`checkwash.size` and `checkwash.limit` as its properties. A head or
worktree side names the file as its location; a base side has none.

**Pre-rename compatibility:** v0.2.12 and v0.2.13 emit the `checkwash_*` keys above,
with `FINDINGS_VERSION = 1`. Older consumers expecting
`greenwash_findings_version` or `run.greenwash_version` must adapt explicitly;
the legacy `greenwash` CLI alias does not provide aliases for JSON keys. The
rename is therefore a compatibility exception to account for when upgrading,
not evidence of an unchanged machine interface.

### When the number moves

- **Bump `FINDINGS_VERSION` or `IR_VERSION`** if a field is renamed,
  removed, or changes meaning, or if a required key is added.
- **Do not bump** for a new optional field, a new rule id, a new escalator
  or de-escalator label, a new TEST_DISABLED `shape` value (as in D-092), a
  moved fingerprint, or a new `--format`. Rule ids themselves are frozen
  (table above).
- A bump is a breaking change: the minor version moves with it and
  `DECISIONS.md` records why. Pin the package in CI if you parse JSON.

`--format json` remains sorted keys, `ensure_ascii=False`, LF, UTF-8
bytes, no timestamps (SPEC §8).

### Fingerprint stability

A fingerprint is the key an exemption records. Compare it for equality
only: its unit part can contain `/`, and its last part has more than one
form.

- Within one minor release line a recorded exemption keeps matching. Before
  v0.5.0, the patch releases v0.3.4, v0.4.1 and v0.4.2 moved some keys
  without saying so; there has been no patch release since.
- A minor release can move fingerprints in any namespace. Its
  `DECISIONS.md` entry and its release notes name the rules and shapes
  whose keys move. `checkwash_findings_version` does not move for this.
- An exemption whose key moved no longer applies: the finding is gated as
  if it had never been exempted, and can block. When a key format is
  retired, `check` reports the entry on stderr, `allow` refuses the old key
  and `doctor` warns. A key that changed in any other way matches nothing,
  without a message.
- New findings bring new keys in any release, because detector coverage
  grows.

[Embedding checkwash](embedding.md#upgrade-notes) lists what each release
since v0.6.0 moved.

### Separate assertion-coverage report

Current source supports `checkwash check --coverage-report FILE` alongside any
existing output format. This uses its own `checkwash_coverage_version: 1`
envelope; it does not add keys to findings JSON or emitted IR. Bounded coverage
gaps appear on stderr and as SARIF tool execution warnings, without changing
findings or verdicts. `no_known_gaps` is not a completeness claim. See the
[report schema and limits](assertion-coverage.md). A JS assertion call whose
predicate checkwash does not read (a throw or spy check, an unread matcher) is
recorded with no strength and stays in the report; deleting it is
`ASSERT_REMOVED` because the frontend records it
([#196](https://github.com/taipei49314/checkwash/issues/196) 190.5).

## Not frozen: this will change, on purpose

**Detector coverage grows, and growth can newly block something.** That is the
product. A diff that passed on v0.1.7 may block on v0.1.8 because a bypass was
closed — this has happened repeatedly and the whole ledger is in
`THREATMODEL.md`. Pin a version in CI if you need a stable gate; upgrade
deliberately, read the release notes, and expect the block set to move.

**The numbers move too.** Re-measurement after behavior changes is the intended
procedure; published evidence must say what actually ran. The committed
1800-commit sweep artifacts record v0.3.0 (swept 2026-09-07 from the release
commit). `STATE.md` records that v0.2.11 to v0.2.13 carried the v0.1.46 baseline
forward without a fresh full sweep, because the corpus does not contain the
affected configuration directories. Original evidence
and the progression — including increases in false positives — are published
in [benchmarks/README.md](../benchmarks/README.md).

## Coverage and adoption cost

Python is the primary frontend. JS/TS support scans named `test`/`it` units
and a fixed set of `expect(...).matcher(...)` calls in `*.test.*` and
`*.spec.*` files, including JSX/TSX. Jest's default layout adds every
JavaScript/TypeScript file beneath a `__tests__/` directory and exact
`test`/`spec` filenames, JSX/TSX included. Node default test paths also cover
`test/` directories and `test-*`, `*-test`, `*_test` and exact `test` filenames
with `js`, `cjs`, `mjs`, `ts`, `cts`, or `mts` extensions. AVA's and tap's
defaults (`tests/`, tap's `__test__/` and `*.tests.*`) cover a file that
imports or requires `ava` or `tap`, whose `t` assertions are read
([#233](https://github.com/taipei49314/checkwash/issues/233)), so a Python
project's JS helpers under `tests/` stay production. Configured test globs
are not read. A guardrail, CI or snapshot path inside these layouts keeps that
role, and so does a path under a `roles` glob for `ci`, `snapshot`, `lockfile`
or `conftest` in the checkwash config. Such a file is still judged as a test,
beside that role's own rules
([#197](https://github.com/taipei49314/checkwash/issues/197)). A shell shebang
or a `Makefile` name prefix does not make a test file a CI script. Under a task
contract, a file that is a test only by its path and declares no test on either
side is judged by its table role for the out-of-scope escalation, so an edit to
production code named like a test outside the contract's scope blocks
([#196](https://github.com/taipei49314/checkwash/issues/196#issuecomment-5945152490),
186.8); every other rule still reads it as a test.
Any other file beneath a `__tests__/`, `__mocks__/` or `test/` directory,
Python files aside, serves the tests: it takes the test role whatever its
extension, as every file under Python's `tests/` does, so an edit to fixture
data or a manual mock is not production repair evidence
([#217](https://github.com/taipei49314/checkwash/issues/217)). The out-of-scope
escalation still judges such a file as production.
Build artifacts and dependencies remain excluded.
Since v0.4.1 ([#164](https://github.com/taipei49314/checkwash/issues/164)),
checkwash also recognizes `assert.equal`, `assert.strictEqual`,
`assert.deepEqual`, and `assert.deepStrictEqual` changing to `assert.ok` or
`assert(value)`, plus the corresponding `t.assert` methods; v0.4.0 does not.
It resolves bounded static Node and Jest/Vitest imports, simple aliases, and
lexical shadows. Unknown lookalikes do not acquire assertion
strength. A name that any write may have reached, from any function, is
unknown rather than its first value, and a declaration ends where JavaScript
ends it, with or without a semicolon
([#196](https://github.com/taipei49314/checkwash/issues/196) 189.1). In a
hand-rolled `Math.abs(x - 78.75) < bound`, and in its Python `abs(...)` twin,
the subject is what the magnitude measures and a literal centre is the
expected value, so a rewritten centre is reported
([#225](https://github.com/taipei49314/checkwash/issues/225), 189.2). Dynamic aliases and semantic equivalence of arbitrary predicates
inside `assert(value)` / `assert.ok(value)` remain outside this model.
Since v0.5.0, checkwash also reports
`TEST_PATCHES_SUBJECT` when an existing JS unit's own assertion reads a newly
installed stand-in for a first-party module or member: `vi.mock`, `jest.mock`,
their ordered forms, node:test `mock.module`, or a replacing spy (issue #177).
Only `./` and `../` specifiers count as first-party, and since #196 188.6
the `@/` and `~/` aliases and the patterns of the base side's root
`tsconfig.json` `paths`; hooks and other bundler aliases stay outside
([installation contract](subject-integrity.md#javascript-module-mocks-and-replacing-spies)).
Since #218, a stand-in installed from a setup file the runner loads before
every test file (`setupTests.{js,ts}`, `jest.setup.*`, `vitest.setup.*`, or
one the root `package.json` names in `jest.setupFiles`), and Jest's
`automock` turned on there or in `package.json`, is reported too, with no
unit, as a conftest patch is.
Since v0.6.0, a `vi.mock` takes effect for the whole file wherever it is
written, as Vitest hoists it. A stand-in is new for each test that did not
already have it, so one copied in from another test is reported. A spy
replaced in a second statement is read. A module object passed whole names
no export
([#196](https://github.com/taipei49314/checkwash/issues/196#issuecomment-5945152490),
188.1-188.4).
Unit liveness is read once, the same way at every declaration level (#176,
#178): `.skip`, `.todo`, the `x`-prefixed globals, Vitest `skipIf`/`runIf` and
the `skip`/`todo` keys of an inline options object disable a unit, and
`.fails`/`.failing` or `{ fails }` invert its oracle. On `describe`, `suite` or
`context` these reach every unit declared inside the block's callback.
`.only`, `fit`/`fdescribe` and `{ only }` focus the file, and a unit the focus
stops is reported as no longer running under a runner that honours it.
node:test honours it only under `--test-only` or `--test-isolation=none`
(`--experimental-test-isolation=none` on Node 22), flags outside the scan, and
the finding says so
([#196](https://github.com/taipei49314/checkwash/issues/196#issuecomment-5945152490),
187.1). Which units a focus stops follows the runner (187.2), as measured on
Jest 30, Vitest 5, Mocha 12, Jasmine 7 and Node 22. Jest's rule, the most
permissive of them, judges Jest and any runner that is not known: a focused
block runs the units inside it unless a unit placed directly beside them is
focused. The innermost rule judges a file whose imports or base manifest name
only Vitest, Mocha, Jasmine or node:test: a focused block that holds a
focused declaration runs only that declaration. Every subtest of a focused
test runs. Mocha is stricter still, since a block that holds a focused test
also drops its inner blocks, and that stays unreported. Focus that a diff
adds to a file that had none, and that leaves no unit in the file unfocused,
is reported once for the file: Mocha and Jasmine apply focus to the whole
suite, so every test outside the file stops
([#196](https://github.com/taipei49314/checkwash/issues/196#issuecomment-5945152490),
187.4). It stays quiet only when the runner is proven to keep focus in the
file: a `vitest`, `@jest/globals` or `ava` import, or a base-side root
`package.json` whose dependencies name Jest, Vitest or AVA and no other runner
(AVA runs each file in a worker of its own, #233). A node:test import is no
such proof. The `x`/`f`-prefixed globals count only with a
literal name or an inline callback, so a `fit(points)` helper call focuses
nothing.
`t.skip()`/`t.todo()` on the callback's own context parameter and Mocha's
`this.skip()` count wherever they sit in the callback; the `if` around them is
not recorded, and a call that passes a function (tap's `t.skip(name, fn)`)
declares a subtest instead. Every reason a unit does not run is its own
marker, so re-enabling a skipped unit while a committed `.only` still holds
the focus adds no disable. Only literal conditions are decided; any other
condition is reported as a conditional disable with no compatibility-gate
credit. Hooks, block callbacks defined elsewhere, destructured contexts and
`test.extend` functions stay outside this model. Since
[#428](https://github.com/taipei49314/checkwash/issues/428) (unreleased), a
`test.each`, `it.each` or `test.for` table is one unit, named by its title as
written, whose liveness is read as any unit's and whose rows are its test
items: a deleted row, or a plain test turned into a table of no rows or of
rows that cannot be counted, is reported as no longer running. In v0.8.0
these tables are not scanned at all: their assertions, their rows and their
deletion go unchecked. The rows of a `describe.each` table are still not
read.
It is a bounded text scan, not a full JavaScript parser or a general assertion
library model. JS/TS production semantics remain unread, so a modified
production file the engine cannot parse is the only repair evidence a JS/TS
test can earn. It still suppresses escalation there, through the documented
opaque-change rule, until the JS/TS history replay
([#212](https://github.com/taipei49314/checkwash/issues/212)) prices a
change. In v0.9.0 it does the same for a Python test or conftest:
[#419](https://github.com/taipei49314/checkwash/issues/419)'s refusal, which
on main since #464 made a weakened, removed, skipped or loosened assertion,
or an added broad `except`, high beside such a change, is turned off after
the combined sweep's pre-registered stop (D-171). A package manifest's test command is not production
(issue #174): when a diff changes what `package.json` runs as its tests —
`scripts.test`, `test:*` scripts, scripts that invoke a recognised runner, and
the scripts `test` and `test:*` name through `npm run`, `yarn`, `pnpm`,
`bun run` or `run-s` (one hop) — or a Pipfile `[scripts]` entry of that kind,
the manifest is CI configuration for that diff. It grants no opaque exemption,
and a swallowed exit code or an introduced narrowing that the diff writes into
those commands is a weakened test command; a script the diff only starts
calling, unedited, is not text the diff wrote. A manifest side the stdlib
reader refuses (`json`/`tomllib`) cannot show its test command unchanged, so
any edit to it counts as one and both sides are then scanned whole. A side
over the 1,000,000-byte source limit is not read at all: `check` exits 2 and
names the file, its side, its size and the limit (#415). Dependency and version edits
that leave those commands unchanged are treated as before. The JS runners `node --test`,
`mocha`, `ava`, `tap`, `bun test` and `deno test`, and the task runners
`hatch test`, `just test`, `poe test` and `pdm test`, count only where a
command starts, in a manifest script, a shell runner script, a workflow step
or a pre-commit hook, and never as words elsewhere: an rxjs `tap` or a comment
that names mocha runs nothing
([#216](https://github.com/taipei49314/checkwash/issues/216)). A second-language checkbox does not establish broad
coverage.

The tracked six-repo sweep (engine 0.3.0, 2026-09-07) recorded **31 false
positives out of 1800 commits (1.72%)**, on a corpus used to tune the
detectors. Its adjudication combines an older three-rater study, later
two-rater additions and maintainer-only additions; the kappa is not a study
of all 46 entries in that adjudication.
The historical dedicated honest-refactor record has **22 blocks out of 60
(36.7%)**. Its stricter runtime receipt qualifies 57 cases, with three
existing fixture-phase errors and 20 qualified block observations. The
v0.3.3 candidate retained those counts; the original records are not rewritten.
A separate pre-release source replay for v0.3.4 records 4/60 all-case blocks
and 2/57 qualified blocks, retaining the same three fixture errors. The
[versioned evidence](releases/v0.3.4-public-launch.md#evidence-and-its-limits)
names its exact source and does not replace the historical dataset.
The refactor and six-repository sweep are different populations; neither predicts another
repository's review cost. Original versions, dates and adjudication scope are
in [benchmarks](../benchmarks/README.md).

Known limitations remain in the [September catalog](adversarial-catalog-2026-09.md)
and [THREATMODEL](../THREATMODEL.md). A closed row means its named case has
evidence behind it, not that every variant is impossible. A growing catalog
can reflect better discovery; hiding new rows would not make adoption safer.

## What must change before 1.0

**Status: NOT MET.** Public availability as v0.8.0 is not a 1.0 readiness
decision. The release needs an evidence-backed acceptance review covering:

| Area | Evidence needed before a 1.0 decision | Current gap |
|---|---|---|
| Known low-cost failures | A dated catalog, an explicit in-scope priority set, case-level closure evidence and owner-accepted residuals | Remaining open work in the September catalog must retain its actual status; a summary cannot mark it closed |
| Adoption | Independently maintained repositories using an actual required check, with a recorded observation period and enough reviewed changes to exercise it | No completed adoption cohort is established by these documents |
| Refactor cost | Pre-agreed acceptance thresholds, adjudicated false blocks and review/exemption workload, measured on both dedicated refactors and adoption repositories | The retained [2026-09-07 / v0.3.1 runtime snapshot](../benchmarks/refactors/results-latest.json) records 22/60 blocks. The current 0.10 [static ledger](../benchmarks/refactors/expected.json) has 6/60; it is not fresh runtime qualification or an adoption study |
| Interfaces and operations | Version-specific compatibility notes and release qualification tied to the shipped artifacts | The pre-rename JSON compatibility exception and Action trust lag must be visible to adopters |

**Adoption-study proposal, not an adopted release threshold:** at least three
independently maintained repositories, 30 consecutive calendar days and at
least 20 reviewed changes per repository. The maintainer must agree the
cohort, traffic minimum and health thresholds before this can be used as a
gate. Record false blocks, exemptions and their review cost, engine errors,
required-check disablement and resolution time; an idle repository does not
demonstrate healthy usage. Where used, smallestlie contributes its actual
adoption results and limitations, not a readiness endorsement by association.

The next-quarter engineering focus is **refactor false positives**: shared
helpers, unit identity changes and the documented tradeoffs in the dedicated
corpus. Agree the desired reduction and acceptable coverage tradeoffs before
changing detector or de-escalation behavior. That program is separate from
the 0.2.x documentation and adoption fixes.

## How you will be told

- **Release notes** on every tag, with what moved and what it cost.
- **`THREATMODEL.md`** — every bypass, its status, and the fixture pinning it
  when it is closed. A row marked Closed with nothing behind it fails the test
  suite.
- **`DECISIONS.md`** — why, including the decisions that were wrong and were
  reversed. Two false positives shipped in one day are recorded there under
  the versions that introduced them.
- **`benchmarks/RESULTS.md`** — generated from the harness, never hand-typed.

## Upgrading

```bash
checkwash --version                 # what you have
checkwash check HEAD~1..HEAD        # what it says now
```

Since 2026-10-14 the README recommends the newest verified release's Action
instead of the one before it; the v0.8.0 documentation pins the v0.8.0 Action,
which closes the Action trust boundary (#372). See the
[v0.8.0 evidence and limits](releases/v0.8.0-public-launch.md).
Treat each installed surface as its own versioned dependency; see the
[README](../README.md#required-check--the-only-configuration-that-blocks-a-merge).

If a new version blocks something it used to pass, that is either a bypass
closing or a false positive shipping — and this project has done both. Read
the release notes; if it is the second, an issue with the diff is the most
valuable thing you can send, and it becomes a regression fixture with your
name on it.

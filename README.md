# checkwash

[![PyPI](https://img.shields.io/pypi/v/checkwash.svg)](https://pypi.org/project/checkwash/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](https://github.com/taipei49314/checkwash/blob/main/LICENSE)

**Check whether a code change weakens your tests.**

A test can pass after it stops checking something useful. checkwash reads
your Git diff and flags known patterns such as deleted assertions, skipped
tests, relaxed expectations, and CI checks that stop failing.

```diff
- assert total == 105.3
+ assert total > 0
```

The new assertion accepts many incorrect totals. checkwash flags changes
like this for review, including changes written by coding agents.

**Runs locally. No LLM. No network during analysis. Never executes your code.**

The examples below use the verified 0.13.1 release. For the current CLI download
and Action pin, see the [installation guide](https://github.com/taipei49314/checkwash/blob/main/docs/install.md).

Start in one of three ways: **Claude Code hooks**, **the CLI on a repository**,
or **the GitHub Action** as a required check.

## Use it with Claude Code

You need **Python 3.11+, Git and Claude Code**. Install the CLI, then run the
hook installer from the root of your repository:

```bash
pipx install checkwash==0.13.1
checkwash hook install --agent claude-code --local
```

This writes checkwash's hooks to `.claude/settings.local.json`, your
machine-local Claude Code settings (`--local` is the default; `--shared`
writes `.claude/settings.json` without the PreToolUse prompt):

- **Stop hook:** checks the working tree and the session's commits when Claude
  is about to finish (paired with a `SessionStart` hook that records where the
  session began). On a blocking finding, it stops Claude and returns the
  finding so Claude can restore the test or explain what blocked.
- **PreToolUse ask (`--local` only):** prompts before an `Edit`, `Write` or
  `MultiEdit` of a Python test file leaves a `high` finding under one of five
  weakening rules (`ASSERT_WEAKENED`, `ASSERT_REMOVED`, `TEST_DISABLED`,
  `TOLERANCE_LOOSENED`, `BROAD_EXCEPT_ADDED`). Non-interactive `claude -p`
  runs deny such edits because nobody can answer; the interactive prompt
  itself is not verified in automated tests.

Both hooks are author-side checks: edits made through `Bash` bypass the
PreToolUse ask, and engine errors in the Stop hook report a non-blocking note
(except working-tree files over the size limit). To enforce verdicts on merges,
configure the required CI check under [Use it in CI](#use-it-in-ci). Hook
limits are documented in the
[0.11.0 known issues](https://github.com/taipei49314/checkwash/blob/main/docs/KNOWN-ISSUES-v0.11.0.md).

## Try it on a repository

You need **Python 3.11+ and Git**. Download the single-file zipapp and run the
built-in offline examples first.

Windows PowerShell (including 5.1, where `curl` aliases `Invoke-WebRequest`):

```powershell
curl.exe -LO https://github.com/taipei49314/checkwash/releases/download/v0.13.1/checkwash.pyz
python checkwash.pyz --version
python checkwash.pyz demo
```

macOS/Linux or Git Bash:

```bash
curl -LO https://github.com/taipei49314/checkwash/releases/download/v0.13.1/checkwash.pyz
python checkwash.pyz --version
python checkwash.pyz demo
```

You can also [download `checkwash.pyz` in your browser](https://github.com/taipei49314/checkwash/releases/download/v0.13.1/checkwash.pyz).
Then, from a Git repository with at least two commits:

```bash
python checkwash.pyz check HEAD~1..HEAD
```

- **Uncommitted changes:** `python checkwash.pyz check`
- **Branch review from merge base:** `python checkwash.pyz check BASE...HEAD` (`BASE..HEAD` compares the two snapshots directly)
- **Hands-on walkthrough:** follow [`examples/invoice`](https://github.com/taipei49314/checkwash/blob/main/examples/invoice/README.md) to watch a failing test, a one-line shortcut edit that makes it green without fixing the bug, and checkwash's block.

Running `check` from a subdirectory analyses the whole repository from its Git
root and notes that root on `stderr`
([#416](https://github.com/taipei49314/checkwash/issues/416)). For JSON/SARIF
output and machine integration, see the
[embedding guide](https://github.com/taipei49314/checkwash/blob/main/docs/embedding.md)
and [stability contracts](https://github.com/taipei49314/checkwash/blob/main/docs/stability.md).

## Use it in CI

To stop a merge, make the **`checkwash` status check required** in your
repository's branch rules. Installing the tool or adding a workflow alone
does not enforce its verdict.

<a id="required-check--the-only-configuration-that-blocks-a-merge"></a>

Save this as `.github/workflows/checkwash.yml`:

```yaml
# .github/workflows/checkwash.yml
on: [pull_request]

permissions:
  contents: read

jobs:
  checkwash:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          fetch-depth: 0
          persist-credentials: false
      - uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0
        with:
          python-version: "3.12"
      - uses: taipei49314/checkwash/action@62656df812372c085b4d32c7864fcdfaccd0318a # v0.13.1
```

After the workflow runs once, open **Settings → Rules → Rulesets** and require
the `checkwash` status context (keep the job unconditional). Repository
administrators with a clone of this project can also add the ruleset via:

```bash
gh api repos/OWNER/REPO/rulesets --method POST --input action/required-ruleset.json
```

`checkwash doctor` checks the local workflow file (it cannot inspect live
GitHub branch protection). When upgrading, update the CLI and local hooks
before bumping the Action pin; see [CI details](#ci-details-doctor-and-the-pin).

## When checkwash blocks

| Result | What to do |
|---|---|
| **Pass · exit 0** | No finding requires blocking under your configuration. Keep running your normal test suite and code review. |
| **Block · exit 1** | Read the finding and the diff. It may be weakened verification or a false positive. |
| **Error · exit 2** | Resolve the input or analysis error before relying on the result. |

The default threshold is **high**: a visible **warn** still passes.

**Read the finding.** For the diff at the top of this page inside
`test_invoice_total` in `tests/test_billing.py`, checkwash prints:

```text
ASSERT_WEAKENED   HIGH   tests/test_billing.py :: test_invoice_total
  test_invoice_total: assertion strength EXACT_VALUE(90) -> BOUND(40)
  why high: NO_PROD_CHANGE_IN_DIFF
  no de-escalator applied
  before  assert total == 105.3
  after   assert total > 0
```

`EXACT_VALUE(90) -> BOUND(40)` ranks assertion strength before and after;
`why high` names the escalator (`NO_PROD_CHANGE_IN_DIFF`, or
`REPAIR_EVIDENCE_REFUSED` when weakened alongside a production edit). Use
`checkwash check --format json` for machine-readable output.

**Fix the change, or record a reviewed exemption.** If the test was weakened
by mistake, restore it and fix the code. If the weaker test is intentional,
record a time-boxed exemption (90 days default, 180 max) using the fingerprint
printed in the report:

```bash
checkwash allow "<the fingerprint from the report>" --reason "why the weaker test is correct"
```

Configuration and exemptions are read strictly from the **base** side of the
diff (comparing `.checkwash/` against any `.greenwash/` predecessor), so a PR
cannot exempt or relax rules for itself: merge the ledger entry through code
review first, and protect `.checkwash/` and `.greenwash/` with
[CODEOWNERS](https://github.com/taipei49314/checkwash/blob/main/docs/enterprise.md#4-codeowners)
([exemption rules](https://github.com/taipei49314/checkwash/blob/main/docs/enterprise.md#3-allowlist--reviewed-time-boxed-base-side)).

For a local `main...branch` check, merge or rebase onto the updated `main` so
the common ancestor includes the exemption. On GitHub, push to the pull
request branch or use **Update branch** to trigger a new pull request event.
Re-running an old job uses the original event's commits.

**Report a false block.** If checkwash blocks an honest change, check the
[failure ledger](https://github.com/taipei49314/checkwash/blob/main/benchmarks/FAILURES.md)
first, then open an [issue](https://github.com/taipei49314/checkwash/issues)
with the **checkwash blocked honest work** template (`checkwash check --format json`
plus the diff). Accepted reports become regression fixtures crediting the
reporter.

## Know the limits

**checkwash is alpha.** A pass means no known tampering pattern was flagged at
or above your threshold; it does not prove a change is correct or honest.
Python is the primary supported language; JS/TS support covers a bounded set of
patterns.

Four core limits to know before relying on a pass:

- **Test files are found by default naming conventions.** Python files are
  scanned when named `test_*.py` or `*_test.py` outside pytest's default
  ignored directories (`build/`, `dist/`, `venv/`, dot-directories), reading
  only default pytest test names; non-default filenames such as
  `tests/pricing_tests.py` or Django `tests.py` emit an `analysis incomplete`
  note on `check` (`stderr`, terminal report and SARIF) when changed, and are
  not parsed as test units even if `pyproject.toml` collects them. JS/TS scans zero-configuration Jest
  and Node paths (`*.test.*`, `*.spec.*`, `__tests__/**`, `.js`/`.ts` under
  `test/`, and `tests/` files importing `ava` or `tap`), without reading
  `jest.config.*`, `vitest.config.*`, `.mocharc.*` or `package.json` `jest`
  collection rules.
- **A JS/TS pass covers fewer patterns than Python.** Fewer assertion and
  helper idioms are modelled in JS/TS, and runner config changes that silently
  drop test files are not read.
- **Editing agent-instruction files blocks, except strict inert EOF appends to root `CLAUDE.md`.**
  Changes to root `AGENTS.md`, `.cursorrules`, `.claude/**`, `.checkwash/**`
  or `.greenwash/**`—and any prepend, mid-file insertion, adjacent append without
  a blank line, deletion, edit, reorder, or fence/comment/`---`/`[label]:` addition
  in root `CLAUDE.md`—escalate `GUARDRAIL_TOUCHED` to `critical`.
  Strict inert appends at the end of root `CLAUDE.md` separated by a blank line
  (`GUARDRAIL_ADDITIVE`), appended exemption entries (`EXEMPTION_ADDED`), and newly
  created guardrail files that do not weaken checkwash config stay at `warn`.
- **Claude Code hooks are author-side helpers, not a merge gate.** Only the
  required CI check in range mode enforces verdicts on pull requests.

**Honest refactors and behaviour changes can require exemptions.** Weakened,
removed, skipped or loosened Python assertions (and weakened, loosened or
skipped JS/TS assertions) refuse production repair evidence
(`REPAIR_EVIDENCE_REFUSED`), so removing a deprecated API with its assertion or
rewriting a test beside a behaviour change requires a reviewed `checkwash allow`
entry. On the project's 60-case refactor corpus (57 strictly qualified), the
expected-verdict table (`benchmarks/refactors/expected.json`) and the published
0.12.0 CLI mark **6 of 60** as blocking (4 among the 57, including known false
blocks `CASE_020_windows` and `CASE_029_flatten`). Changed files over
**1,000,000 bytes** are not read (non-Python assets/docs warn on `stderr`;
test, CI, guardrail, `.py` or pytest config files over the cap exit 2).

<details>
<summary>Customizing guarded instruction files (for example, unguarding CLAUDE.md)</summary>

Subdirectory instruction files, `CLAUDE.local.md`, lowercase `claude.md`,
`.gitattributes` working-tree-encoding rules, and other agents' config filenames
are not guarded by default. `GUARDRAIL_ADDITIVE` on root `CLAUDE.md` covers only
strict inert appends at end-of-file separated by a blank line (no `---`, code
fences, HTML comments, `[label]:` definitions or `Cf`/`Default_Ignorable`
characters), and stays at `warn` even if an appended plain-text line contradicts
earlier prose or adds an `@path` import.

To let a blocking guardrail edit through, record a reviewed exemption or
override `[roles].guardrail` in a base-side `.checkwash/config.toml` (or
`.greenwash/config.toml` if your repository uses that directory):

```toml
[roles]
guardrail = ["AGENTS.md", ".cursorrules", ".claude/**", ".checkwash/**", ".greenwash/**"]
```

Because this list replaces the default, keep `.checkwash/**` and
`.greenwash/**` in it so checkwash continues guarding its own config and
ledger. Creating a new config file is a `warn`; editing an already-tracked
config is itself a `critical` guardrail edit until merged to the base.

</details>

<details>
<summary>Repair-evidence residuals, JS/TS table scope and refactor-corpus provenance</summary>

`REPAIR_EVIDENCE` describes related changes in the same diff; it does not prove
a repair is semantically valid, and a no-op production edit (such as `+ 0`) can
earn it ([#419](https://github.com/taipei49314/checkwash/issues/419)). From
0.12.0 ([0.13.0 known issues](https://github.com/taipei49314/checkwash/blob/main/docs/KNOWN-ISSUES-v0.13.0.md),
[0.12.0 known issues](https://github.com/taipei49314/checkwash/blob/main/docs/KNOWN-ISSUES-v0.12.0.md),
[0.11.0 known issues](https://github.com/taipei49314/checkwash/blob/main/docs/KNOWN-ISSUES-v0.11.0.md)),
weakened/removed/skipped/loosened Python assertions and weakened/loosened/skipped
JS/TS assertions take no repair evidence (`REPAIR_EVIDENCE_REFUSED`). By
default, rewritten expected values, substituted assertions (including a
weakening respelled as one), test deletions escorted by a renamed private
symbol, and JS/TS removed assertions/units, deleted parametrize rows, dead-code
parked units and stand-in/subject edits still accept repair evidence; to block
those too, set `fail-on: warn` in the Action (`checkwash doctor` will then
exit 1 because it proves only a step without `with:`) or run `checkwash check --task`
with a base-side `oracle_freeze` contract
([enterprise hardening guide](https://github.com/taipei49314/checkwash/blob/main/docs/enterprise.md#7-hardening-against-bought-repair-evidence-419)).

In JS/TS (since v0.9.0, [#428](https://github.com/taipei49314/checkwash/issues/428)),
each `test.each`, `it.each` and `test.for` table with a static title is a unit
whose rows are counted when written as an inline array, tagged template or
same-file `const` used only as a table; `describe.each` rows and computed-title
tables remain unread.

For the 60-case refactor corpus, **6 of 60** (4 of 57 strictly qualified) is
the static source readback retained since the
[D-185 dispositions](https://github.com/taipei49314/checkwash/blob/main/docs/oracle-context-dispositions-0.10.0.md)
and matched by the published 0.12.0 CLI on Windows (2026-11-10 UTC). Earlier
historical snapshots in the repository record 22/60 blocks (36.7%) at v0.3.1
(`benchmarks/refactors/results-latest.json`) and 4/60 (2/57 strictly qualified,
with three fixture errors) in a pre-v0.3.4 source replay; those historical
records are preserved unchanged and are selected examples rather than a general
false-positive rate.

</details>

<details>
<summary>Which files over the 1,000,000-byte limit stop the run, and how each output reports them</summary>

Since v0.9.0 ([#454](https://github.com/taipei49314/checkwash/issues/454),
[#455](https://github.com/taipei49314/checkwash/issues/455)), oversized
non-Python assets, lockfiles, docs and non-Python production sources are set
aside without earning repair evidence: `--format json` lists them under
`unread`, SARIF emits a tool execution notification, and terminal output prints
a `!` note (opening with `analysis incomplete` when there are zero findings);
`--format hook-json` and `--emit-ir` omit `unread`.

Any oversized file a detector or import resolver must read—test, conftest, CI,
guardrail, snapshot, JS setup, runner script, `.py` module, pytest config
(`pytest.ini`, `.pytest.ini`, `pytest.toml`, `.pytest.toml`, `tox.ini`,
`setup.cfg`, `pyproject.toml`) at any depth, or non-generated `scripts/**`
file—stops the run with exit 2 (`--format json` prints `{"unread": [...]}`
except on an unread symlinked pytest-config target in range mode; term and
SARIF stay empty). checkwash streams up to 64,000,000 bytes per Git side and
inspects the first 200 bytes of oversized sides solely to detect shell shebangs
(an extensionless file with a side over 64 MB still stops the run). Generated
paths (`build/`, `dist/`, `node_modules/`) are set aside unless they match `.py`,
pytest config, CI, runner script or unknown-shebang extensionless rules. At the
base, oversized root `poetry.lock`/`uv.lock` warn on `stderr`, while oversized
root `pyproject.toml` or `requirements*.txt` exit 2 across term/json/SARIF. In
the Claude Code Stop hook (`--format hook-json`), engine errors report a
non-blocking message and exit 0, except when a file changed by the hook's diff
exceeds the limit in the working tree, which blocks the stop and asks to
shrink, split or revert it ([#456](https://github.com/taipei49314/checkwash/issues/456);
see [subject integrity](https://github.com/taipei49314/checkwash/blob/main/docs/subject-integrity.md)).

</details>

Try it on your own changes before making it required.
[Coverage and limitations](https://github.com/taipei49314/checkwash/blob/main/docs/stability.md#coverage-and-adoption-cost)
· [Known gaps](https://github.com/taipei49314/checkwash/blob/main/docs/adversarial-catalog-2026-09.md)
· [0.13.1 known issues](https://github.com/taipei49314/checkwash/blob/main/docs/KNOWN-ISSUES-v0.13.1.md)
· [0.13.0 known issues](https://github.com/taipei49314/checkwash/blob/main/docs/KNOWN-ISSUES-v0.13.0.md)
· [0.12.0 known issues](https://github.com/taipei49314/checkwash/blob/main/docs/KNOWN-ISSUES-v0.12.0.md)

## CI details: doctor and the pin

The recommended Action and CLI above are both **v0.13.1** (GitHub Release and
PyPI on 2026-11-22). Always upgrade the CLI and its local
hooks first, then update the Action SHA in `.github/workflows/checkwash.yml`.
[Enterprise setup](https://github.com/taipei49314/checkwash/blob/main/docs/enterprise.md)
· [Action reference](https://github.com/taipei49314/checkwash/blob/main/action/README.md)

<details>
<summary>Pin verification, release tag geometry (A vs M), Dependabot/zizmor and &lt;= v0.7.0 advisory</summary>

**Development snapshots:** source on `main` may be ahead of the published CLI.
[The advertised-release manifest](https://github.com/taipei49314/checkwash/blob/main/release/advertised.toml)
records the verified version, tag commit and artifact digests behind the
commands above.

**Which commit is the recommended pin?** From v0.12.0 (D-200), the release tag
points directly at the release's Action commit:
`git rev-parse 'vX.Y.Z^{commit}'`. Because an Action commit cannot embed its own commit SHA,
each release from v0.11.0 (D-194) has two commits: its Action
commit `A`, and the release merge `M` (which differs only in setting `doctor`'s
own Action pin line to `A`). PyPI distributions and `checkwash.pyz` are built from `M`, while
`checkwash check` in the Action does not import `doctor` and behaves
identically at `A` and `M`. Installing the CLI from a Git release tag installs
`A`, whose `doctor` rejects that release's own Action pin (`exit 1`)—install
the CLI from PyPI or `checkwash.pyz` instead. (For v0.11.0 only, the tag
pointed at `M`, so its Action commit was `git rev-parse 'vX.Y.Z^2^1'`; up to
v0.10.0 the tag pointed at the single release commit.)

**Pin updaters and `doctor`:** because v0.12.0+ tags point at the Action
commit, Dependabot, Renovate and zizmor's `ref-version-mismatch` audit resolve
`# v0.13.1` directly to the SHA `doctor` 0.13.1 accepts (inferred from those
tools' documentation, not run; the published 0.13.1 CLI accepts the v0.13.1 pin above and
v0.13.0's pin, while `doctor` 0.13.0 accepts only v0.12.0 and v0.13.0
pins and exits 1 on the v0.13.1 pin).

**Advisory for Action `<= v0.7.0`:** Action releases up to v0.7.0 ran
`python -m pip` and `checkwash` with the PR checkout as working directory,
allowing a PR to shadow `pip` or `checkwash` ([#372](https://github.com/taipei49314/checkwash/pull/372),
fixed in v0.8.0). Pin the v0.13.1 Action above; see
[SECURITY.md](https://github.com/taipei49314/checkwash/blob/main/SECURITY.md#known-issue-action-trust-boundary).

</details>

## More options and evidence

<a id="install"></a>
<details>
<summary>Install as a CLI or try the included examples</summary>

If you already use pipx, install the fixed version:

```bash
pipx install checkwash==0.13.1

checkwash check HEAD~1..HEAD
checkwash demo                  # 8 tampering cases, blocked, offline
```

`checkwash demo` replays eight tampering cases and one honest fix. Five of
the eight are adapted from this project's decoy corpus: coding agents were
pointed at small repositories with a failing test and asked to make the
suite pass without fixing the bug (given only the task, none of the twelve
touched a test). One was found in this project's own release gate; two are
synthetic. The demo prints each case's origin. It illustrates known
patterns; it is not a coverage guarantee.
You can run the same examples with `python checkwash.pyz demo`.

</details>

<a id="measured-not-asserted"></a>
<details>
<summary>Read the measurements and their limits</summary>

The historical six-repo sweep recorded **46 / 1800 = 2.56%** blocks:
**31 false positives (1.72%)**, 15 legitimate
  policy blocks (0.83%). The tracked artifacts record engine **v0.3.0**
(the release commit, swept 2026-09-07) on a corpus used to tune the
detectors, not a held-out result.

**1.33% of the corpus (24/1800) records opaque production changes**.
That flag does not establish that each verdict changed or each diff was unanalyzed.

Review methods vary: the three-rater agreement study covers an older
35-diff cohort, not all 46 blocks. The dedicated **22/60 refactor** result
(`benchmarks/refactors/results-latest.json`, a dated v0.3.1 snapshot) is a
separate population; the general-commit rate does not predict it.

[Measurements and source data](https://github.com/taipei49314/checkwash/blob/main/benchmarks/README.md)
· [Generated results](https://github.com/taipei49314/checkwash/blob/main/benchmarks/RESULTS.md)
· [Failure ledger](https://github.com/taipei49314/checkwash/blob/main/benchmarks/FAILURES.md)

</details>

| Looking for… | Start here |
|---|---|
| Installation checks, versions and first use | [Installation guide](https://github.com/taipei49314/checkwash/blob/main/docs/install.md) · [0.13.1 release guide](https://github.com/taipei49314/checkwash/blob/main/docs/releases/v0.13.1-public-launch.md) · [Release history](https://github.com/taipei49314/checkwash/blob/main/docs/releases/README.md) |
| JSON/SARIF contracts and upgrades | [Stability](https://github.com/taipei49314/checkwash/blob/main/docs/stability.md) · [Embedding guide](https://github.com/taipei49314/checkwash/blob/main/docs/embedding.md) · [Findings schema](https://github.com/taipei49314/checkwash/blob/main/docs/findings.schema.json) |
| Assertion support, coverage warnings and artifact checks | [Assertion coverage](https://github.com/taipei49314/checkwash/blob/main/docs/assertion-coverage.md) |
| Required checks and reviewed exemptions | [Enterprise setup](https://github.com/taipei49314/checkwash/blob/main/docs/enterprise.md) |
| Contributing or reporting a problem | [Contributing](https://github.com/taipei49314/checkwash/blob/main/CONTRIBUTING.md) · [Issues](https://github.com/taipei49314/checkwash/issues) · [Security reports](https://github.com/taipei49314/checkwash/blob/main/SECURITY.md) |
| Readiness for 1.0 | [Criteria — not met](https://github.com/taipei49314/checkwash/blob/main/docs/stability.md#what-must-change-before-10) |

Related project: [checkwash-prove](https://github.com/taipei49314/checkwash-prove)
(experimental) executes your test suite against concrete mutants to show what
protection a test change dropped.

The package also includes a limited quality preview for coverage, Ruff and
mypy configuration review. [Setup and CI adoption guide](https://github.com/taipei49314/checkwash/blob/main/docs/quality-adoption.md).
Its frozen legacy-byte comparison remains red; publication does not establish
natural-case acceptance or effective enforcement.

Alpha pre-release. 22 detectors, 23379 tests (collection denominator).
Zero runtime dependencies. [Apache-2.0](https://github.com/taipei49314/checkwash/blob/main/LICENSE).

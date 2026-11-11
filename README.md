# checkwash

[![CI](https://github.com/taipei49314/checkwash/actions/workflows/ci.yml/badge.svg)](https://github.com/taipei49314/checkwash/actions/workflows/ci.yml)
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

The new assertion accepts many incorrect totals. checkwash can flag changes
like this for review, including changes written by coding agents.

**Runs locally. No LLM. No network during analysis. Never executes your code.**

The install commands and Action pin below name v0.12.0, the latest release
whose public files are verified
([release history](https://github.com/taipei49314/checkwash/blob/main/docs/releases/README.md)).

Start in one of three ways, each below: Claude Code hooks, the CLI on a
repository, or the GitHub Action as a required check.

## Use it with Claude Code

You need **Python 3.11+, Git and Claude Code**. Install the CLI, then run the
hook installer from the root of your repository:

```bash
pipx install checkwash==0.12.0
checkwash hook install --agent claude-code --local
```

This writes checkwash's hooks to `.claude/settings.local.json`, the
machine-local Claude Code settings.

- The **Stop hook** checks the working tree against HEAD when Claude is about
  to stop. On a blocking finding it blocks the stop and gives Claude the
  finding. A SessionStart hook in the same file records where each session
  starts, so the Stop hook also checks what the session commits.
- From 0.11.0, a local install also adds a **PreToolUse ask**.
  When an Edit, Write or MultiEdit of a Python test file would leave a finding
  of one of five weakening rules (`ASSERT_WEAKENED`, `ASSERT_REMOVED`,
  `TEST_DISABLED`, `TOLERANCE_LOOSENED` and `BROAD_EXCEPT_ADDED`) at high, the
  hook asks you before the edit is made. In a `claude -p` run nobody can
  answer, so such an edit is denied; the interactive prompt is not verified in
  any mode. From 0.11.0 a local install is the default, and `--shared` writes
  `.claude/settings.json` with no PreToolUse ask.

Both hooks are author-side checks. An edit made through Bash never reaches the
ask. When the Stop hook cannot analyse a change, it says so and does not block
the stop, except for a changed file over the size limit (see "Know the
limits"). Neither hook can stop someone else's merge: the required check under
"Use it in CI" is the gate. The 0.11.0 hooks' limits are in the
[0.11.0 known issues](https://github.com/taipei49314/checkwash/blob/main/docs/KNOWN-ISSUES-v0.11.0.md).

## Try it on a repository

You need **Python 3.11+ and Git**. Download and try the offline examples first.

Windows PowerShell (including 5.1):

```powershell
curl.exe -LO https://github.com/taipei49314/checkwash/releases/download/v0.12.0/checkwash.pyz
python checkwash.pyz --version
python checkwash.pyz demo
```

PowerShell 5.1 aliases `curl` to `Invoke-WebRequest`; use `curl.exe` as written.
macOS/Linux or Git Bash:

```bash
curl -LO https://github.com/taipei49314/checkwash/releases/download/v0.12.0/checkwash.pyz
python checkwash.pyz --version
python checkwash.pyz demo
```

Then, from the root of a repository with at least two commits:

```bash
python checkwash.pyz check HEAD~1..HEAD
```

This checks your last commit. Start with a change you already understand.
You can also [download the file in your browser](https://github.com/taipei49314/checkwash/releases/download/v0.12.0/checkwash.pyz).
For uncommitted changes use `python checkwash.pyz check`. For a branch review,
use `python checkwash.pyz check BASE...HEAD` to compare from the merge base;
`BASE..HEAD` compares the two named snapshots directly.

To watch checkwash block a weakened test in a small repository, follow
[`examples/invoice`](https://github.com/taipei49314/checkwash/blob/main/examples/invoice/README.md):
a failing test, a one-line edit that makes it pass without fixing the bug,
and the block. It needs a clone of this repository, pytest and an installed
`checkwash`.

From a subdirectory, `check` analyses the whole repository from its Git root
and says so in one line on stderr (since v0.8.0,
[#416](https://github.com/taipei49314/checkwash/issues/416)). Before v0.8.0,
run it from the repository root.

For JSON/SARIF output and more examples, see the [embedding guide](https://github.com/taipei49314/checkwash/blob/main/docs/embedding.md) and the [stability contracts](https://github.com/taipei49314/checkwash/blob/main/docs/stability.md).

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
      - uses: taipei49314/checkwash/action@532f74ab070a924b23e2cc70e5d0091a05d8401d # v0.12.0
```

After the workflow runs, open **Settings → Rules → Rulesets** and require
the `checkwash` status context. Keep the job unconditional.

If you administer the repository and have this project's ruleset file,
you can instead create the rule with:

```bash
gh api repos/OWNER/REPO/rulesets --method POST --input action/required-ruleset.json
```

This adds a ruleset; it does not replace existing ones. `checkwash doctor`
can inspect the local workflow, but cannot verify live branch protection.
`doctor` 0.12.0 accepts the pin above and v0.11.0's. `doctor` 0.11.0 accepts
only v0.11.0's and v0.10.0's, so it reports the pin above as an unsupported
SHA ("workflow analysis incomplete", exit 1): upgrade the CLI and its local
hooks before the Action pin.

## When checkwash blocks

| Result | What to do |
|---|---|
| **Pass · exit 0** | No finding requires blocking under your configuration. Keep running your normal tests and review. |
| **Block · exit 1** | Read the finding and the diff. It may be weakened verification or a false positive. |
| **Error · exit 2** | Resolve the input or analysis error before relying on the result. |

The default threshold is **high**: a visible **warn** can still pass.

**Read the finding.** Each finding names its rule, its severity, and the file
and test it is in. If the change at the top is the whole diff, made in
`test_invoice_total` in `tests/test_billing.py`, the finding reads:

```text
ASSERT_WEAKENED   HIGH   tests/test_billing.py :: test_invoice_total
  test_invoice_total: assertion strength EXACT_VALUE(90) -> BOUND(40)
  why high: NO_PROD_CHANGE_IN_DIFF
  no de-escalator applied
  before  assert total == 105.3
  after   assert total > 0
```

`EXACT_VALUE(90) -> BOUND(40)` ranks the assertion's strength before and
after; 90 is not the value the test expected. `why high` names what raised the
finding: here the diff changes no production file
(`NO_PROD_CHANGE_IN_DIFF`); from 0.12.0 a weakened test blocks beside a
production change too (`REPAIR_EVIDENCE_REFUSED`). `checkwash check --format json` gives the same
findings as JSON.

**Fix the change, or record a reviewed exemption.** If the test was weakened
by mistake, restore it, and fix the code if the restored test fails. If the
weaker test is intended, the report also prints a `checkwash allow` command
with the finding's fingerprint, and the ledger file to commit:

```bash
checkwash allow "<the fingerprint from the report>" --reason "why the weaker test is correct"
```

Configuration and exemptions are read from the base side of the diff, so a
change cannot exempt itself: commit the entry through review, and it applies
to the next diff once it is on the base. Since v0.10.0, a newly winning
`.checkwash` config or allowance is compared with its BASE `.greenwash`
predecessor, so a change cannot approve its own relaxation either. An entry
needs a reason and expires after 90 days by default, 180 at most. Keep
`.checkwash/` and `.greenwash/` behind
[code owners](https://github.com/taipei49314/checkwash/blob/main/docs/enterprise.md#4-codeowners).
From 0.11.0, the Stop hook tells Claude not to add an exemption
itself but to tell you which finding blocks and why, and the PreToolUse ask
asks you to approve only if the weaker test is intended.
[Exemption rules](https://github.com/taipei49314/checkwash/blob/main/docs/enterprise.md#3-allowlist--reviewed-time-boxed-base-side)

**Report a false block.** If the change is honest and checkwash blocks it,
look for it in the [failure ledger](https://github.com/taipei49314/checkwash/blob/main/benchmarks/FAILURES.md)
first, then open an [issue](https://github.com/taipei49314/checkwash/issues)
with the **checkwash blocked honest work** template, giving the diff and the
`checkwash check --format json` output. A report becomes a regression
fixture, and the ledger credits the reporter.

## Know the limits

**checkwash is alpha.** A pass does not prove that a change is correct or honest.
Python is the main language supported; JS/TS support covers a limited set of
test patterns. Known gaps remain.

Four limits to know before you rely on a pass:

- **Test files are found by name.** A Python file is read as a test when its
  name is `test_*.py` or `*_test.py`, pytest's default patterns, and it is
  not under a directory pytest skips by default (`build/`, `dist/`, `venv/`,
  a dot-directory); inside it, only pytest's default test names are read. A
  weakened assertion in `tests/pricing_tests.py` or in a Django `tests.py`
  passes with no finding and no notice, even when your pytest configuration
  (`python_files`, `python_functions`, `python_classes`, `testpaths`)
  collects it. JS/TS test files are found by the zero-configuration defaults
  of Node's test runner and Jest, such as `*.test.*` and `*.spec.*` names,
  files under `__tests__/`, and `.js` or `.ts` files under `test/` (a `.jsx`
  or `.tsx` file there is not read). A file that is a test only because it
  sits under `tests/` (unless it imports `ava` or `tap`), or because your
  runner configuration collects it, is not read.
- **A JS/TS pass covers less than a Python one.** Like any pass, it means
  only that nothing at or above the threshold was found; in JS/TS fewer
  patterns are modelled, and only in the test files checkwash read. Which
  tests a runner configuration collects (`jest.config.*`, `vitest.config.*`,
  `.mocharc.*`, the `jest` key of `package.json`) is not read, so a change
  there that stops tests from being collected passes with no finding.
- **Editing an agent-instruction file blocks.** Any change to a tracked
  `CLAUDE.md`, `AGENTS.md` or `.cursorrules` at the repository root, or to a
  tracked file under the root's `.claude/`, `.checkwash/` or `.greenwash/`,
  is `GUARDRAIL_TOUCHED` at critical, one added line included. Two
  exceptions: an entry added to the exemption ledger is `EXEMPTION_ADDED` at
  warn, and creating one of these files is a warn unless it is a checkwash
  config that disables a detector or raises `fail_on`. The same names in a
  subdirectory, and other agents' instruction files, are not guarded. To let
  an edit through, record a reviewed exemption for it, or replace the
  `guardrail` role's paths in a base-side `.checkwash/config.toml`. For
  example, to stop guarding `CLAUDE.md` and keep the rest:

  ```toml
  [roles]
  guardrail = ["AGENTS.md", ".cursorrules", ".claude/**", ".checkwash/**", ".greenwash/**"]
  ```

  The list replaces the default one, so keep `.checkwash/**` and
  `.greenwash/**` in it: without them checkwash stops reporting edits to its
  own config and ledger. Creating the config is a warn; adding the table to
  a config that is already tracked is itself a guardrail edit and blocks; if
  your config is `.greenwash/config.toml`, edit that file instead. Once the
  list is on the base side, checkwash does not report edits to `CLAUDE.md`
  at all.
- **The Claude Code hooks are author-side checks, not a merge gate.** They
  run only on the author's machine. When the Stop hook hits an engine error
  it says so and lets Claude stop, whatever `on_engine_error` says, unless a
  file it must read is over the size limit below in the working tree. An
  edit made through Bash never reaches the PreToolUse ask. Only the required
  check under "Use it in CI" stops a merge.

An edit that changes nothing, such as `+ 0` in a function a test calls or
one line in a template or `AUTHORS`, can still hold a weakened Python or
JS/TS test at warn in 0.11.0, which passes at the default threshold. From
0.12.0 ([0.12.0 known issues](https://github.com/taipei49314/checkwash/blob/main/docs/KNOWN-ISSUES-v0.12.0.md)) a
weakened, removed, skipped or loosened Python assertion takes no repair
evidence at all, and neither does a weakened, loosened or skipped JS/TS one
(D-199). That blocks honest changes too: a deprecated API removed with an
assertion on it, a test rewritten beside a behaviour change. Each needs a
reviewed exemption. A rewritten expected value or a substituted assertion
still takes the evidence, a weakening respelled as one of them included,
and so does a test deletion that a renamed private symbol escorts; in JS/TS
so do a removed assertion or test, deleted parametrize rows, a test parked
in dead code and a stand-in or subject change
([what still passes and how to block it](https://github.com/taipei49314/checkwash/blob/main/docs/enterprise.md#7-hardening-against-bought-repair-evidence-419)).
Read the [0.12.0 known issues](https://github.com/taipei49314/checkwash/blob/main/docs/KNOWN-ISSUES-v0.12.0.md)
and the [earlier limits they build on](https://github.com/taipei49314/checkwash/blob/main/docs/KNOWN-ISSUES-v0.11.0.md)
before relying on a pass.

`REPAIR_EVIDENCE` describes related changes in the same diff; it does not
prove a repair is correct, and an edit that changes nothing can earn it
(#419). From 0.12.0, `REPAIR_EVIDENCE_REFUSED` marks a finding
that such a change reached and whose rule takes none (D-199). To block the
rest, set the
Action's `fail-on: warn`
(`checkwash doctor` then reports "workflow analysis incomplete" and exits 1,
which is expected: it proves only a checkwash step with no `with:`), or run
`checkwash check --task` in a CLI step of your own with a base-side
`oracle_freeze` contract (the Action has no task input); both block more
honest changes too. From 0.11.0, on a local hook install, the
Claude Code PreToolUse hook asks before an Edit, Write or MultiEdit of a
Python test leaves a finding of its five weakening rules at high, whatever
repair evidence the rest of the working tree holds; its limits are in the
[0.11.0 known issues](https://github.com/taipei49314/checkwash/blob/main/docs/KNOWN-ISSUES-v0.11.0.md).

In v0.8.0, JS/TS `test.each`, `it.each` and `test.for` tables are not
scanned: an assertion weakened or deleted in one, an edited row or a deleted
table passes. In v0.9.0, each such table is a test
unit, and its rows are read when they can be counted (an inline array or a
tagged template, or a same-file `const` read only as a table). The rows of a
`describe.each` table stay unread, and a table with a computed title is not a
unit ([#428](https://github.com/taipei49314/checkwash/issues/428)).

Legitimate refactors can be flagged. The project keeps a corpus of 60 test
refactors, 57 of them strictly qualified. Its expected-verdict table
(`benchmarks/refactors/expected.json`) marks **6 of 60** as blocking, 4 of
them among the 57: the six the v0.10.0 table retains after the
[D-185 dispositions](https://github.com/taipei49314/checkwash/blob/main/docs/oracle-context-dispositions-0.10.0.md), including the known
legitimate-refactor false blocks `CASE_020_windows` and `CASE_029_flatten`.
This is a static source readback; the published 0.12.0 CLI blocks the same
six (run on Windows, 2026-11-10 UTC). The corpus's retained runtime
snapshot, from v0.3.1, records 22 blocks out of 60 (36.7%), and a source
replay before v0.3.4 records 4/60 blocks, including 2/57 strictly qualified
cases; three existing fixture errors remain. The later readback does not
rewrite those historical runtime results. These are selected examples, not a
general false-positive rate.

A changed file over 1,000,000 bytes is not read. An image, data file,
lockfile, document or non-Python production source that large is reported on
stderr and earns no repair evidence.

<details>
<summary>Which files over the limit stop the run, and how each output and the Stop hook report them</summary>

Since v0.9.0
([#454](https://github.com/taipei49314/checkwash/issues/454)), `--format json`
also lists it under `unread`, SARIF names it in a tool execution
notification, and the term report adds a `!` line and, when there is no
finding, opens with "analysis incomplete"; the Stop hook's JSON and
`--emit-ir` do not name it. A file a detector must read (test, conftest, CI,
guardrail, snapshot, JS setup, runner script or test-command file) that large
stops the run with exit 2, naming it. So do a `.py` module
that large, whether added, deleted, renamed or edited, and a pytest
configuration file (`pytest.ini`, `.pytest.ini`, `pytest.toml`,
`.pytest.toml`, `tox.ini`, `setup.cfg`, `pyproject.toml`) at any depth:
either can change the module a test's import resolves to. So do any
non-generated file under the root `scripts/` directory, read for the pytest
commands it runs, and any other changed file that large the analysis needs
as context. A shell shebang gives a file the shape of a runner script, whatever
its name, except a `.py` module or a JS/TS test file.
Since v0.9.0
([#455](https://github.com/taipei49314/checkwash/issues/455)), checkwash reads
the first 200 bytes of a side over the limit to tell, and uses them for
nothing else; a Git side is streamed and checked against its object id.
Where those bytes are read, a file that large whose side starts with a shell
shebang stops the run, naming that side, whatever its suffix (a `.py` module
or a JS/TS test file that large stops the run anyway, by its own rule). A
file with no extension (a dotfile such as `.envrc` counts) without one, such
as a `README` or a `LICENSE`, is set aside like any document, unless another
rule above makes it one a detector must read. v0.8.0 reads no byte of such a
side, so every file with no extension that large stops the run there. In v0.9.0
a Git side over 64,000,000 bytes is not streamed, so its first bytes are not
known: a file with no extension still stops the run when one of its Git sides
is that large, and a suffixed file whose shebang is only on such a side is
still set aside.
When a file that large stops the run, since v0.9.0
`--format json` prints `{"unread": [...]}` on stdout instead of nothing: one
`unread` entry, for the side the run refused. It is not a findings document,
and term and SARIF output stay empty. With a range, json output stays empty
too when the refused file is a symlinked pytest configuration's target that
no detector must read.
Generated output (`build/`, `dist/`, `node_modules/` and the like) is set
aside like a production source unless it is a Python module, a pytest
configuration, a CI file, a runner script or a file with no extension whose
shebang is not known. A root
`poetry.lock` or `uv.lock` that large at the base is skipped with a note on
stderr, and the skip is not listed under `unread`; when the diff also changes
that lockfile, the change's sides over the limit are listed like any other. A
root `pyproject.toml` or `requirements*.txt` that large at the base stops
every run, naming it: term, json and SARIF output exit 2 and name it on
stderr only. The Claude Code Stop hook (`--format hook-json`) reports an
engine error, this one included, as a non-blocking "not analysed" message
on stdout that quotes the error, and exits 0.
Since v0.9.0, when the run stops on a file the hook's diff
changes and that file's working-tree side is over the limit, the hook blocks
the stop instead, naming the file and asking to shrink, split or revert it
([#456](https://github.com/taipei49314/checkwash/issues/456)). A file whose
base side alone is over the limit, a root manifest over it at the base, and a
padded file committed before the stop keep the message; the full list is in
[subject integrity](https://github.com/taipei49314/checkwash/blob/main/docs/subject-integrity.md).

</details>

Try it on your own changes before making it required. [Coverage and limitations](https://github.com/taipei49314/checkwash/blob/main/docs/stability.md#coverage-and-adoption-cost)
· [Known gaps](https://github.com/taipei49314/checkwash/blob/main/docs/adversarial-catalog-2026-09.md)

## CI details: doctor and the pin

The recommended Action and the CLI above are both **v0.12.0**.
Record which version you use. [Full setup and exemptions](https://github.com/taipei49314/checkwash/blob/main/docs/enterprise.md)

**Development snapshots:** the source in this checkout may be newer than the
published CLI. [The advertised-release manifest](https://github.com/taipei49314/checkwash/blob/main/release/advertised.toml)
records the version, tag commit and download bytes behind the installation commands
above. New changes require their own candidate evidence and remain unreleased
until the publication record verifies them; candidate CI success does not mean
that the recommended Action pin includes them.

**Advisory: Action trust boundary.** Every published Action release up to and
including v0.7.0 runs `python -m pip` and then `checkwash` with the pull
request's checkout as the working directory, so a module in that checkout (for
example a top-level `pip` package) can replace the installer and then the
checker, and the pull request can tamper with the result it is judged by. Under
checkwash's threat model that applies to every pull request it judges. v0.8.0
fixes it ([#372](https://github.com/taipei49314/checkwash/pull/372)); pin the
v0.12.0 Action above. If you stay on v0.7.0 or earlier, treat a pass as
advisory, review the pull request before merging and keep `comment-pr` off.
[Known issue](https://github.com/taipei49314/checkwash/blob/main/SECURITY.md#known-issue-action-trust-boundary)

**Which commit is the recommended pin?** The release's Action commit, which
from v0.12.0 (D-200) is the commit the tag points to:
`git rev-parse 'vX.Y.Z^{commit}'`. A release cannot embed its own commit SHA,
so from v0.11.0 (D-194) a release has two commits: its Action commit, and the
release merge, which differs from it in one line, `doctor`'s own Action pin,
set to the Action commit. The PyPI package and the pyz are built from the
merge. The Action runs only `checkwash check`, which does not import
`doctor`, so it runs the same check at either commit. A release's `doctor`
accepts two Action pins: the one recommended before the release and the
release's own Action commit. The v0.11.0 tag points at the merge, so v0.11.0's
Action commit is the tag's second parent's parent,
`git rev-parse 'vX.Y.Z^2^1'`. Up to v0.10.0 the pin was the commit the tag
points to.

From v0.12.0, a CLI installed through Git from a release tag is the Action
commit's, and its `doctor` rejects that release's own Action pin ("workflow
analysis incomplete", exit 1). Install the CLI from PyPI or the pyz.

Pin updaters such as Dependabot and Renovate follow the `# vX.Y.Z` comment and
propose the commit the tag points to; what this paragraph says about them
and about zizmor is inferred from those tools' documentation, not run. From
v0.12.0 that commit is the release's Action commit, which that release's
`doctor` accepts, and zizmor's `ref-version-mismatch` audit should not
report the comment. For a v0.11.0 pin they can propose the v0.11.0 merge,
which `doctor` rejects, and zizmor can report the comment; an update to
v0.12.0 proposes v0.12.0's Action commit, which `doctor` 0.12.0 accepts and
`doctor` 0.11.0 rejects. So upgrade the CLI and its local hooks first, then
the Action pin. The
recommended v0.12.0 Action includes the engine published as checkwash 0.12.0
(GitHub Release 2026-11-07, PyPI 2026-11-08, Asia/Taipei). A CLI upgrade does
not update an existing Action.
[Action reference](https://github.com/taipei49314/checkwash/blob/main/action/README.md)

## More options and evidence

<a id="install"></a>
<details>
<summary>Install as a CLI or try the included examples</summary>

If you already use pipx, install the fixed version:

```bash
pipx install checkwash==0.12.0

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
| Installation checks, versions and first use | [v0.12.0 publication record](https://github.com/taipei49314/checkwash/blob/main/docs/releases/v0.12.0-publication-verification.md) · [v0.12.0 release guide](https://github.com/taipei49314/checkwash/blob/main/docs/releases/v0.12.0-public-launch.md) · [Release history](https://github.com/taipei49314/checkwash/blob/main/docs/releases/README.md) |
| JSON/SARIF contracts and upgrades | [Stability](https://github.com/taipei49314/checkwash/blob/main/docs/stability.md) · [Embedding guide](https://github.com/taipei49314/checkwash/blob/main/docs/embedding.md) · [Findings schema](https://github.com/taipei49314/checkwash/blob/main/docs/findings.schema.json) |
| Assertion support, coverage warnings and artifact checks | [Assertion coverage](https://github.com/taipei49314/checkwash/blob/main/docs/assertion-coverage.md) |
| Required checks and reviewed exemptions | [Enterprise setup](https://github.com/taipei49314/checkwash/blob/main/docs/enterprise.md) |
| Contributing or reporting a problem | [Contributing](https://github.com/taipei49314/checkwash/blob/main/CONTRIBUTING.md) · [Issues](https://github.com/taipei49314/checkwash/issues) · [Security reports](https://github.com/taipei49314/checkwash/blob/main/SECURITY.md) |
| Readiness for 1.0 | [Criteria — not met](https://github.com/taipei49314/checkwash/blob/main/docs/stability.md#what-must-change-before-10) |

Related projects: [checkwash-corpus](https://github.com/taipei49314/checkwash-corpus)
and [smallestlie](https://github.com/taipei49314/smallestlie) hold evaluation work.

The package also includes a limited quality preview for coverage, Ruff and
mypy configuration review. [Setup and CI adoption guide](https://github.com/taipei49314/checkwash/blob/main/docs/quality-adoption.md).
Its frozen legacy-byte comparison remains red; publication does not establish
natural-case acceptance or effective enforcement.

Alpha pre-release. 22 detectors, 22862 tests (collection denominator).
Zero runtime dependencies. [Apache-2.0](https://github.com/taipei49314/checkwash/blob/main/LICENSE).

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

**v0.3.0 replaces five file-wide exemption rules with content-bound ones.**
In v0.2.13 those rules could reuse a recorded approval for a later change to
the same path; v0.3.0 retires their path-only keys. The [upgrade notes](https://github.com/taipei49314/checkwash/blob/main/docs/remediation-upgrade.md)
describe the content-bound replacement, retired keys, and installation fixes.

**v0.3.3 fixes two measured false positives involving shared immutable fixture
parameters.** It retains the existing execution-context and bounded-oracle
checks. [Release evidence and remaining limits](https://github.com/taipei49314/checkwash/blob/main/docs/releases/v0.3.3-public-launch.md)

## Try it

You need **Python 3.11+ and Git**. Download and try the offline examples first.

Windows PowerShell (including 5.1):

```powershell
curl.exe -LO https://github.com/taipei49314/checkwash/releases/download/v0.3.3/checkwash.pyz
python checkwash.pyz --version
python checkwash.pyz demo
```

PowerShell 5.1 aliases `curl` to `Invoke-WebRequest`; use `curl.exe` as written.
macOS/Linux or Git Bash:

```bash
curl -LO https://github.com/taipei49314/checkwash/releases/download/v0.3.3/checkwash.pyz
python checkwash.pyz --version
python checkwash.pyz demo
```

Then, from a repository with at least two commits:

```bash
python checkwash.pyz check HEAD~1..HEAD
```

This checks your last commit. Start with a change you already understand.
You can also [download the file in your browser](https://github.com/taipei49314/checkwash/releases/download/v0.3.3/checkwash.pyz).
For uncommitted changes use `python checkwash.pyz check`. For a branch review,
use `python checkwash.pyz check BASE...HEAD` to compare from the merge base;
`BASE..HEAD` compares the two named snapshots directly.

| Result | What to do |
|---|---|
| **Pass · exit 0** | No finding requires blocking under your configuration. Keep running your normal tests and review. |
| **Block · exit 1** | Read the finding and the diff. It may be weakened verification or a false positive. |
| **Error · exit 2** | Resolve the input or analysis error before relying on the result. |

The default threshold is **high**: a visible **warn** can still pass.
`REPAIR_EVIDENCE` describes related changes in the same diff; it does not
prove a repair is correct.

For JSON/SARIF output and more examples, see the [usage guide](https://github.com/taipei49314/checkwash/blob/main/docs/releases/v0.3.3-public-launch.md#try-it-on-a-change-you-understand).

## Know the limits

**v0.3.3 is alpha.** A pass does not prove that a change is correct or honest.
Python is the main language supported; JS/TS support covers a limited set of
test patterns. Known gaps remain.

Legitimate refactors can be flagged: the dedicated honest-refactor corpus
records **22 blocks out of 60 (36.7%)**. The stricter runtime verifier
qualifies 57 cases; three have existing fixture errors, and 20 of the qualified
cases block. Try it on your own changes before making
it required. [Coverage and limitations](https://github.com/taipei49314/checkwash/blob/main/docs/stability.md#coverage-and-adoption-cost)
· [Known gaps](https://github.com/taipei49314/checkwash/blob/main/docs/adversarial-catalog-2026-09.md)

## Use it in CI

To stop a merge, make the **`checkwash` status check required** in your
repository's branch rules. Installing the tool or adding a workflow alone
does not enforce its verdict.

The recommended Action is pinned to **v0.3.2**; the CLI above is **v0.3.3**.
The shared-fixture precision fix below is in the CLI; the prior-release Action does not include it.
Record which version you use. [Full setup and exemptions](https://github.com/taipei49314/checkwash/blob/main/docs/enterprise.md)

<a id="required-check--the-only-configuration-that-blocks-a-merge"></a>
<details>
<summary>Copy the GitHub Actions workflow and require the check</summary>

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
      - uses: taipei49314/checkwash/action@4ad6e31019dd40e69f46f3f0ac24d37bbdad31ac # v0.3.2
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

**Why the older Action pin?** A release cannot embed its own commit SHA,
so the documented Action adopts a verified pin from the prior release.
v0.3.2 carries the v0.3.0 engine (content-bound exemptions, parametrize row
identity, table-oracle delegation, schema 2). v0.3.3 adds a bounded precision
fix for multiple consumers of immutable literal fixture parameters; the
recommended v0.3.2 Action does not yet include that fix. To verify another trusted release, use
`git rev-parse 'vX.Y.Z^{commit}'`.
[Action reference](https://github.com/taipei49314/checkwash/blob/main/action/README.md)

</details>

## More options and evidence

<a id="install"></a>
<details>
<summary>Install as a CLI or try the included examples</summary>

If you already use pipx, install the fixed version:

```bash
pipx install checkwash==0.3.3
# or from the release tag:
pipx install git+https://github.com/taipei49314/checkwash@v0.3.3

checkwash check HEAD~1..HEAD
checkwash demo                  # 8 real tampering cases, blocked, offline
```

`checkwash demo` replays eight real tampering cases and one honest fix.
It illustrates known patterns; it is not a coverage guarantee.
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
(`benchmarks/refactors/expected.json`, replayed by `tests/gates/`) is a
separate population; the general-commit rate does not predict it.

[Measurements and source data](https://github.com/taipei49314/checkwash/blob/main/benchmarks/README.md)
· [Generated results](https://github.com/taipei49314/checkwash/blob/main/benchmarks/RESULTS.md)
· [Failure ledger](https://github.com/taipei49314/checkwash/blob/main/benchmarks/FAILURES.md)

</details>

| Looking for… | Start here |
|---|---|
| Installation checks, versions and first use | [v0.3.3 guide](https://github.com/taipei49314/checkwash/blob/main/docs/releases/v0.3.3-public-launch.md) |
| JSON/SARIF contracts and upgrades | [Stability](https://github.com/taipei49314/checkwash/blob/main/docs/stability.md) |
| Required checks and reviewed exemptions | [Enterprise setup](https://github.com/taipei49314/checkwash/blob/main/docs/enterprise.md) |
| Contributing or reporting a problem | [Contributing](https://github.com/taipei49314/checkwash/blob/main/CONTRIBUTING.md) · [Issues](https://github.com/taipei49314/checkwash/issues) · [Security reports](https://github.com/taipei49314/checkwash/blob/main/SECURITY.md) |
| Readiness for 1.0 | [Criteria — not met](https://github.com/taipei49314/checkwash/blob/main/docs/stability.md#what-must-change-before-10) |

Related projects: [checkwash-corpus](https://github.com/taipei49314/checkwash-corpus)
and [smallestlie](https://github.com/taipei49314/smallestlie) hold evaluation work.

The unreleased quality preview also has a [setup and CI adoption guide](docs/quality-adoption.md) for coverage, Ruff and mypy.

Alpha pre-release. 21 detectors, 2376 tests in the current source tree.
Zero runtime dependencies. [Apache-2.0](https://github.com/taipei49314/checkwash/blob/main/LICENSE).

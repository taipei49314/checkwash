# Adopt the quality preview

This source preview adds coverage, Ruff and mypy configuration review alongside
the existing test-oracle check. It is not included in the published v0.3.3 tag.
Use a separately reviewed exact preview commit to try it. Natural-case labels,
completeness evaluation and release approval remain outstanding; these setup
commands do not establish production enforcement maturity.

## 1. Generate and review a draft

From a Git repository using one or more supported tools:

```sh
checkwash quality profiles --details
checkwash quality init > quality-draft.toml
```

`init` only prints a draft; it never writes or replaces `.checkwash/quality.toml`.
Save to a separate draft file: shell redirection directly to an existing policy
would truncate that file before Checkwash starts. Existing quality policies are
rejected; edit them deliberately and use `doctor` instead.

Discovery checks the requested root using the packaged precedence rules. Only
tools with configuration at that root are proposed. Each tool's sole packaged
model is offered as an assumption requiring review, **not an observed installed
version**. Check the exact version in your lockfile and real CI invocation. A
version not matching a qualified model remains unsupported; changing the profile
string does not qualify that version. `profiles --details` includes supported
settings, defaults, model boundaries, digests and native qualification receipts.

The draft uses report mode. Review the source paths, configuration selection and
model versions, then install it as `.checkwash/quality.toml`. Inferred paths cover
visible Python files under the requested root; common build/environment directories
are omitted only from draft suggestions. These suggestions do not assert which
files your tools actually check. Explicit paths are repository-relative literals:

```sh
checkwash quality init --tool coverage --tool mypy --paths src/ --paths tests/
checkwash quality init --root packages/api --tool ruff --paths packages/api/src/
checkwash quality init --format json
```

Repeat `--tool`/`--paths` as needed. An explicitly requested tool with no discovered
configuration fails without producing a partial policy. For multiple monorepo
roots, review separate drafts before installation, combine targets with unique
IDs, and use explicit configuration paths where required by the support matrix.
The generator does not recursively invent independent targets or silently merge
an existing policy. Add relevant `version_files` after review if version-source
changes should make later comparisons incomplete.

## 2. Diagnose the local setup

```sh
checkwash quality doctor
checkwash quality doctor --format json
```

Doctor checks the working policy and configuration with the same bounded model
as a review, counts matching tracked Python sources and compares the policy bytes
with HEAD. It supplies remediation for unsupported settings, invalid paths,
unresolved context, empty tracked scope and a new or uncommitted policy. It returns
0 for `configured`, 2 for `needs_attention` or `error`, including in report mode.

Setup JSON has its own `checkwash_quality_setup_version: 1`, an
`authority: advisory_only` marker and explicit false flags for tool-version,
CI-execution and branch-protection verification. `configured` means the local
setup can be analyzed under its declared assumptions. It is not a review verdict.
Setup output cannot authorize exemptions or change another invocation's policy.

Review and commit the policy, then compare a real change:

```sh
checkwash quality BASE...HEAD --format json
```

The policy at the merge base owns that comparison. Adding the policy in a PR does
not make it govern that same PR. Report exit 0 can still contain high findings or
incomplete analysis. Keep those visible during adoption; investigate unsupported
context without removing real checks just to obtain a complete report.

## 3. Connect a separate PR status

The separate `action/quality` composite action accepts full fetched base/head
commit SHAs, runs the three-dot comparison, preserves the original JSON and
0/1/2 exit, and adds a job summary. It requires Python 3.11+. Its installer builds
the reviewed action source in a private temporary virtual environment; installation
may fetch build dependencies. Analysis itself remains offline and does not execute
subject code. This action does not post PR comments or change branch protection.

Example for a consumer repository; replace `<reviewed-quality-sha>` with the full
immutable commit you reviewed. It must contain this preview action. Do not use a
local action from the subject PR checkout as your trusted checker.

```yaml
name: Checkwash quality
on: pull_request
permissions:
  contents: read
jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
        with:
          ref: ${{ github.event.pull_request.head.sha }}
          fetch-depth: 0
          persist-credentials: false
      - uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97
        with:
          python-version: '3.12'
      - id: quality
        uses: taipei49314/checkwash/action/quality@<reviewed-quality-sha>
        with:
          base: ${{ github.event.pull_request.base.sha }}
          head: ${{ github.event.pull_request.head.sha }}
          require-enforce: 'false'
      - uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a
        if: always()
        with:
          name: checkwash-quality
          path: |
            ${{ steps.quality.outputs.report_path }}
            ${{ steps.quality.outputs.receipt_path }}
          if-no-files-found: error
```

The action expects both commits and their ancestry to be available. Missing refs,
invalid inputs, timeout and malformed output return 2 rather than a pass. A subject
repository must be its Git root inside `GITHUB_WORKSPACE`; a subdirectory or an
external path is rejected. For multiple checkouts, use `repository: subject`.

| Output | Meaning |
| --- | --- |
| `exit_code` | Action result, including integration failure |
| `analysis_exit_code` | Original checker exit, or `unavailable` |
| `analysis_status`, `verdict` | Original report fields when a valid report exists |
| `report_path` | JSON path in runner temp; empty if no valid report was produced |
| `receipt_path` | Integration receipt, including a mode mismatch or input error |

Installation failure stops before review and has no report outputs; the job and
artifact step remain visibly failed. Temporary paths are unique per invocation.
Publish reports with the artifact step even when the review blocks.

After evaluating report-mode results and completing the acceptance work, a team
can separately review a base-policy change to `mode = "enforce"`. Set
`require-enforce: 'true'` in its trusted workflow and require that status through
the team's branch rules. This option returns action exit 2 if the base is still
report/discovery mode; it preserves the original report and `analysis_exit_code`
instead of relabeling them. It does not alter the core severity policy or grant
enforcement to a head-only configuration.

GitHub references: [composite-action metadata](https://docs.github.com/en/actions/reference/workflows-and-actions/metadata-syntax)
and [pull-request event semantics](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#pull_request).

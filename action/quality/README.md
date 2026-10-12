# Quality Action boundary

This page describes the current source candidate. The recommended published
Action pin is still v0.6.0 alongside the published v0.7.0 CLI; those deployment
pins do not acquire source changes automatically. Public delivery still needs
a qualified release containing this repair and a separately approved update
of the recommended immutable Action pin. This page does not recommend an
unreleased commit. Passing security qualification does not authorize a tag,
release or public-pin update, or establish quality-preview maturity.

The [adoption guide](../../docs/quality-adoption.md) describes the future setup
after that publication and pin decision: a separate clean hosted job whose
checker comes from its trusted published pin, not the PR checkout.
Fetch the full base/head ancestry (`fetch-depth: 0`), keep checkout credentials
disabled, and do not run subject code before the review. No secret or review
comment token is needed.

`python-path` accepts an absolute trusted Python 3.11+ executable, normally
`${{ steps.python.outputs.python-path }}` from setup-python. Omission uses
setup-python's `pythonLocation`; callers that previously relied only on
ambient PATH must now provide one of these trusted selections. Missing,
relative or subject-contained selections fail. Shell startup, trusted OS
directories and the initial interpreter remain the caller's responsibility;
checks after startup cannot undo an already-compromised runner.

The installer reuses the main Action's private venv, explicit UTF-8, sanitized
build-child environment, fixed pip index and no-runtime-dependency install.
Build dependencies may still be fetched. It rejects installed source/content,
metadata or version mismatches and unexpected bytecode/cache files before any
Checkwash import. This binds the package to the pinned source; it does not
attest the OS, interpreter or build-dependency supply chain. Isolation flags
and content checks are not recovery from malicious code already running in
the job.

Analysis uses that verified interpreter, a private cwd and clean Git/child
environment. `repository` remains a Git root within `GITHUB_WORKSPACE`;
full input SHAs are passed to the quality engine unchanged. Three-dot
comparison and base-owned quality policy are unchanged. A missing ref returns
the original quality error JSON and analysis exit 2, even if that early error
report still has unresolved `HEAD`/`worktree` labels and default report mode.
The Action receipt stores requested refs separately from report labels.

The six outputs remain `exit_code`, `analysis_exit_code`, `analysis_status`,
`verdict`, `report_path` and `receipt_path`. Report-mode high findings can return
0; enforce-mode blocking findings return 1; input/engine/integration errors
return 2. `require-enforce: true` adds exit 2 when the report's base mode is
not enforce and retains the original analysis/report. It does not grant
enforcement to head-only policy or change quality severity.

Raw engine stdout/stderr stay in private artifacts and do not enter workflow
commands. The summary contains only bounded report fields. Summary/receipt
failure occurs before normal output export; output-write failure returns 2
and updates the receipt when writable. OS partial writes cannot be rolled
back, so preserve native step outcome as well as outputs. If even a safe
runner-temp report directory is unavailable, the step fails without claiming
a report or outputs. Installation failures still occur before the six review
outputs exist.

`ci_execution_verified` and `branch_protection_verified` remain false. Review
of declarations does not prove that coverage/Ruff/mypy ran or that a branch
rule requires the status. The independent quality Action qualification uses
owned fixtures across three OSes; main Action qualification does not replace
it. Negative enforce/error cases retain their native failed outcomes and are
assessed by a separate qualification job, not `continue-on-error`.

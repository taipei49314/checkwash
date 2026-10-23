# PJU receipts and required checks

Nelson instructed on 2026-10-23: “把 PJU 測試收據接上必過檢查，處理 #561 的 dogfood 阻擋，檢查通過後合併，再繼續收斂剩下的 issue。”
This implements the standing CheckWash/PJU rule recorded in
[EC T-606 POLICY](https://github.com/taipei49314/estate-consolidation/blob/e9ce2342fc4834f5b5d580461b26f8784b64481a/POLICY.md).

All product execution happens on **LAPTOP-01AGNPJU**. The existing
`quality-candidate-intake.yml` manual entry also accepts a receipt-verification
mode. Hosted jobs read data and publish GitHub check runs; they do not execute
candidate product code, tests, builds or Action helpers. The previous hosted
test workflows remain disabled. The repository ruleset is unchanged.

## Trust and scope

An audited collector runs from a fixed source outside the candidate checkout.
It records the exact clean candidate head/base/tree, hostname, runtime, complete
commands and raw exits/logs. It builds and qualifies source, wheel and pyz,
retains the wheel/sdist/pyz bytes, runs the local test suite and replays the
published composite Action's real Bash blocks with their inputs and outputs.
Test subprocesses receive no GitHub token. A separate authorized publisher
commits the evidence and supplies its immutable commit and manifest digest
through a maintainer-authenticated manual dispatch.

The bridge trusts that controlled publication and dispatch, not a JSON author
field, Git author string, candidate-provided URL or the word `passed`. This is
maintainer-backed execution evidence, **not hardware remote attestation**.
Anyone able to modify trusted bridge code or dispatch as the maintainer remains
inside this trust boundary; receipt hashes alone cannot prove where a process ran.

The verifier reads exact Git source bytes and checks the receipt manifest,
contract inventory, complete case identities, qualification and build receipts,
artifact hashes, original command exits and JUnit results. Missing, failed,
malformed or mismatched evidence produces no successful required check. It
rechecks the live open PR head and base before validation and publication.

Only the publisher job receives `checks: write`. It creates these completed
checks for the tested head with GitHub Actions' identity:

- `checkwash` — the published pinned Action, actual high-severity threshold,
  actual PR base/head and successful install/check exits.
- `candidate assertion contract (source)`.
- `candidate assertion contract (wheel)` — includes the corresponding sdist.
- `candidate assertion contract (pyz)`.

The three contract contexts keep their existing GitHub Actions App binding.
The publisher's job name is not a required check name; skipped workflow jobs
cannot masquerade as successful product checks. Merge uses the exact verified
head only after the required checks are read back with their expected source.

The Action result is labelled **PJU local composite replay**, not a GitHub
runner execution. Python/OS versions absent from the local receipt are
`NOT_RUN`, including native Linux/macOS and their cross-platform comparison.
The four checks do not assert full historical matrix coverage or grant a release.
Existing platform-specific and release acceptance conditions remain in force.

## Bootstrap and operation

The existing intake workflow already has `workflow_dispatch` on main. A reviewed
branch version can therefore verify the first receipt before this bridge merges;
its exact workflow SHA is part of admission. This avoids bypassing branch
protection to introduce the bridge. Intake mode retains its existing behavior.

Before dispatch, freeze the workflow and collector source, target PR/base/head,
evidence commit and manifest digest. Save that admission in the task's execution
record. Do not dispatch arbitrary candidate helpers. After completion read back
the check names, App IDs, target head, conclusions and run/evidence links.
A source or base change requires new evidence; a prior success is not reused.

The initial PR #561 also repeated the venue rule in AGENTS.md, producing a
critical guardrail finding. A proposed base-side exemption then correctly
produced a second guardrail finding for the allowlist itself. Both failed
receipts are preserved. The final migration instead carries the standing rule
through EC POLICY, STATE.md and the testing/release documents. Existing
AGENTS.md already requires reading STATE.md and every-PR dogfood, and contains
no conflicting test venue. The redundant AGENTS edit and proposed exemption
are removed; no severity, comparison base, guardrail or fixture expectation
is changed. The final complete diffs still require real passing receipts.

PJU unavailability or missing capabilities is `NOT_RUN`, with no remote fallback.
Sweep and model/adjudication approvals remain separate; this bridge adds none.

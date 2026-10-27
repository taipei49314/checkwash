# CheckWash inactive-fixture followup backup

Snapshot UTC: `2026-10-27T00:47:29.907029+00:00`. Purpose: `COMMITTED_INACTIVE_FIXTURE_FOLLOWUP_BACKUP_NOT_ACCEPTANCE_NOT_RELEASE`.

Committed candidate: **`1be28ce5de72dcb617818077aaf11e3b1cf7a976`**, separate from the prior fbc baseline.
[PR 572](https://github.com/taipei49314/checkwash/pull/572) is a draft. The repair goal remains incomplete.
The fixed candidate has 323 targeted tests passing (exit 0). Parent-range self-check: PASS, exit 0,
0 high / 3 warn. Integration-range self-check: **BLOCK, exit 1, 3 high / 12 warn**.

Full suite: **IN_PROGRESS / NO_TERMINAL_RECEIPT in this snapshot**. Its live directory is wholly
excluded; only the frozen intent may be included. Separate stage9 source/wheel/pyz qualification
work is **IN_PROGRESS / NO_TERMINAL_RECEIPTS_SELECTED** as a combined followup effort. This does
not claim every worker has started. No stage9 live partial/result is included and none is called PASS.
Prior fbc qualifications do not qualify changed candidate bytes.
Historical PR-body and WIP records retain their own dates and failed/unsafe/uncommitted states.

Backup/source-guard baseline only: `fbc9374dc3bcbfc47f403aec0c36e6b51dd7b86c`. Previous evidence checkpoint: `4fc76cca99b4f19dedd26ee94da202daf85d5142`.
The handoff metadata tree inherits its parent's product root and is **not** the candidate source.
Restore the separate candidate commit 1be28ce5de72dcb617818077aaf11e3b1cf7a976 for candidate work.
The frozen [stage7 continuation](work/ux-stage7/00-CONTINUE.md) and per-run receipts provide
source-specific evidence; original fbc/stage5 and historical prototype evidence stay immutable.

This backup performs no merge, tag, release or qualification and grants no product acceptance.
No new 1.0 authorization is granted: Nelson must decide before 1.0. No historical/model batch is admitted.
MANIFEST.json binds all exported raw bytes. Python, XML and diff inputs use text transport
suffixes and are not automatically executed. No ZIP/runtime is included. The exact stage5
metadata helper pins remain required for this preservation tool.

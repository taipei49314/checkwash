# Committed inactive-fixture evidence backup tool

This metadata-only derivative starts from the frozen, reviewed stage7 tool
SHA256 `2a70b0b1d2d4b3b1fdafce18c721b2173be3937e68bef47b4e4e68b5f4e60452`.
The exact unchanged stage5 privacy/publisher helper pins remain required.
Privacy inspection retains its default false exception flag, and the complete
original fbc source/index/seal/main/tags guard is still invoked unchanged.

Fixed evidence parent: `4fc76cca99b4f19dedd26ee94da202daf85d5142`.
New prefix: `handoff/checkwash-inactive-fixture-followup-20261027`.
Output: `outputs/checkwash-inactive-fixture-followup-20261027`.
`source_sha=fbc9374dc3bcbfc47f403aec0c36e6b51dd7b86c` identifies only the
original baseline guarded at `work/checkwash-ux`; it is not the followup source.
The separate `candidate_sha=1be28ce5de72dcb617818077aaf11e3b1cf7a976` is the
committed followup at `work/checkwash-inactive-fixture` / draft PR572.

The additional candidate guard requires clean exact HEAD, the fixed raw
`input-hashes.json` SHA256 `256074c9d24bc24c0cfc91aea7d3bce49bb5bf14250abe397ecc9fe788261732`,
all 3087 physical tracked bytes, identical regular stage0 index and HEAD-tree
membership/modes/blob IDs, stable index and main/tags. Both original and new
guards run before/after planning and immediately before/after any later push.
The new guard uses fixed read-only `git -C` commands without changing the
reviewed publisher's repository global or loosening its original source guard.
This worktree's index is outside the generated task: a separate exact-path
reader allows only `C:/Users/nelson/dev/checkwash/.git/worktrees/checkwash-inactive-fixture/index`,
after matching `--absolute-git-dir` and rejecting links/reparse/nonregular nodes
through its entire parent chain. General `read_regular` remains task-only and
byte-identical to stage7. No external index bytes are exported, only its hash.

Only the explicit frozen stage7 selection is exported, with raw byte hashes.
Checkpoint-pack/runs/cache/temp/runtime/binary inputs are excluded. Python,
XML and diff files are exported with appended `.txt`; original bytes stay
unchanged. The entire live `final/inactive-fixture-full-suite-311-r1` directory
is excluded even if it later gains files; its frozen launch intent is included.
All historical WIP failures and unsafe/uncommitted records retain their dates.

Current-snapshot outcomes are checked against the selected native receipts,
JUnit and raw self-check JSON: 323 targeted passes / exit0; parent self-check
PASS / exit0 / 0H3W; integration BLOCK / exit1 / 3H12W. Full suite is
IN_PROGRESS / NO_TERMINAL_RECEIPT in this snapshot. Separate stage9 candidate
source/wheel/pyz qualification work is IN_PROGRESS as a combined effort, with
NO_TERMINAL_RECEIPTS_SELECTED here; no per-worker start/completion or PASS is
inferred and no stage9 partial/result is included. The goal remains incomplete; this is not a
merge, release, 1.0 authorization, acceptance or a replacement for prior raw.
The parent handoff product root is metadata ancestry, not candidate source.

Default mode plans only. `--prepare` writes the fixed new output with
exclusive creation and refuses any differing existing bytes. Neither mode
writes Git objects/index/refs or runs products/tests/models. A later
`--publish` is reserved to root after independent review and requires the exact
reviewed plan digest. It retains the alternate-index additions-only check,
single expected remote/ref, fixed parent, no hooks, normal nonforce push with
`--no-follow-tags`, and pre/post source/input/output checks. An unknown or
failed push stops with prepared raw recovery receipts; it is not retried here.

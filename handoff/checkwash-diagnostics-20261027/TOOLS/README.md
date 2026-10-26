# Stage6 diagnostic supplement — prepared, not executed

This tool has not been executed, imported, dry-run, or used to push. It is an
owned metadata controller, not a new product qualification or acceptance check.
It does not change the frozen stage5 controllers, outputs, source or ZIPs.

Fixed product source: fbc9374dc3bcbfc47f403aec0c36e6b51dd7b86c.
Fixed first and only parent: ec4b80ac162d1fbdb73c329ee39d87992d4fbafe.
Branch: handoff/core-010-pju-20261027-8a8941dc.
New prefix: handoff/checkwash-diagnostics-20261027/.
New local output: outputs/checkwash-diagnostics-20261027/.
Purpose: DIAGNOSTIC_SUPPLEMENT_NOT_ACCEPTANCE_NOT_RELEASE.

## Required frozen selection

Root supplies a UTF8 JSON file with exactly these top-level keys:

    {
      "source_sha": "fbc9374dc3bcbfc47f403aec0c36e6b51dd7b86c",
      "purpose": "DIAGNOSTIC_SUPPLEMENT_NOT_ACCEPTANCE_NOT_RELEASE",
      "root_frozen": true,
      "files": [
        {
          "source": "work/ux-stage6/completion-audit/report.md",
          "export": "work/ux-stage6/completion-audit/report.md",
          "bytes": 0,
          "sha256": "REPLACE_WITH_ACTUAL_RAW_SHA256"
        }
      ]
    }

The example row is illustrative and deliberately not runnable. Every actual
row must have the exact current integer bytes and lowercase raw SHA256, with
only source/export/bytes/sha256 keys. Explicitly freeze all desired diagnostics,
existing raw observations, inert proposals and review metadata before making
the list. Active/incomplete drafts must not be declared frozen merely to meet
the backup deadline. This tool never auto-selects the whole live stage6 tree.

Only stage6 task-relative regular inputs are admitted. Runtime/cache/.git/tmp
and checkpoint-pack directory components are refused. UTF8 text without NUL
or ZIP content is required. Outputs are .md/.json/.patch/.txt; .py must export
to its exact original path plus .txt (.py.txt). Other source text can retain its
path or append .txt. Raw bytes are never edited or interpreted as new PASS.
No ZIP, wheel, pyz, binary runtime or whole global memory is included.

The two current controller files are explicitly exported as TOOLS/*.txt and
TOOLS/README.md; the surrounding checkpoint-pack tree is never selected. The
generated MANIFEST maps every other exported file and excludes itself only.
Source/purpose, NONPASS_NOT_REASSESSED and the old complete backup are explicit.

## Unmodified signed dependencies

The wrapper loads only the exact already reviewed metadata bytes below, with
their __main__ guards false. No product or analyzed fixture code is imported:

- stage5/checkpoint-pack/pack_checkpoint.py:
  ab1ab82cb38f8271a7b8bcbded31f35cc7f43e752a1e5ed7c8c0b9aba2a08928.
- stage5/checkpoint-pack/publish_checkpoint.py:
  9b559a07f3e46fdb2b4bf8614a06c9aa135d7bb5aafb37b60bba9f6a4be4b7be.

Restore both from the preceding fbc evidence bundle's BUNDLE-TOOLS, preserving
their work/ux-stage5/checkpoint-pack paths, if using a new task workspace.
The source fbc checkout, stage5 PIN/seal/source ZIP and3084 physical members
must still match. Git history must contain ec4 and the required source objects;
text or a source ZIP alone is not a Git history backup.

The original privacy inspect function is called with its default header flag
false. There is **no new privacy exception** and the approved stage5 audit
source exception is not enabled for stage6. Private-name/exact-private-file/
key/URL and recursive archive checks still inspect original bytes. A refusal
stops the tool; it does not silently omit the offending evidence. Matched
private values are not printed. The scan is bounded, not a universal secrets
guarantee.

## Workflow after independent source review

Commands below are future instructions, not receipts. This preparation has
run none of them. Use the existing task runtime; no venv/install/host change.

1. Plan only (read-only Git/network; only owned local plan receipts are written):

       python -I -B -X utf8 work/ux-stage6/checkpoint-pack/diagnostic_checkpoint.py --selection FROZEN.json --label diagnostics-r1

2. Prepare the new output, without Git writes or pushing:

       python -I -B -X utf8 work/ux-stage6/checkpoint-pack/diagnostic_checkpoint.py --selection FROZEN.json --label diagnostics-r1 --prepare

   Only fresh files or exact already-identical bytes are permitted. Existing
   changed/unlisted output stops preparation. Parent components are checked
   for links/reparse points before writes; no old stage5 output is touched.

3. Root reviews the current plan, source/helper pins, selection, manifest and
   all copied bytes. Publish only its exact digest:

       python -I -B -X utf8 work/ux-stage6/checkpoint-pack/diagnostic_checkpoint.py --selection FROZEN.json --label diagnostics-r1 --publish --expect-plan-sha256 REVIEWED64HEX

The plan digest omits per-run timestamps and includes the source seal/index/
local main-tag snapshot, helper/controller pins, parent and exact payload.
Any input/source/parent/controller change stops the operation. Source3084,
product index bytes and local main/tags are checked before and after. No
qualification is rerun. The sole push is normal nonforce, no-follow-tags,
no-submodule recursion, invocation-only mirrorfalse, one approved effective
GitHub origin, and owned empty hooks. No global Git configuration is changed.

Git writes use a private index. Only additions under the new prefix are allowed;
no old path/banner/ZIP, main, tag or release is changed. A prepared commit receipt
is saved before push. The remote ref must first equal exact ec4 and afterwards
equal the prepared commit. On timeout/unknown result preserve all receipts and
reconcile the actual remote outcome; do not blindly repeat. After a successful
push this one-parent tool intentionally refuses another run against a moved
branch. Root's remote blob/API readback remains a separate operation.

Backup timing does not approve remaining golden/corpus costs, self-dogfood
findings, merge/publication or1.0. Human-authorized PJU execution remains
HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL; no pool investigation is performed.

# Artifact working-backup publisher

The destination repository `taipei49314/checkwash` is public. This tool does
not create private visibility, encryption or an ACL. Historical PRIVATE/private
strings inside the frozen artifact package mean only a nonrelease working
snapshot. New remote/local wrappers state this before other facts.

This derivative starts from the frozen stage8 metadata-only controller
SHA256 `36606ae79ffa445548a532cdfc62e82b2da2dc354b9fd6c2d366498a00c937b7`.
Baseline `source_sha=fbc9374dc3bcbfc47f403aec0c36e6b51dd7b86c` remains the
unchanged stage5 source/privacy mapping guard. Separate committed product code
is `candidate_sha=1be28ce5de72dcb617818077aaf11e3b1cf7a976` / draft PR572,
with a clean physical/index/HEAD 3087-file candidate guard. A metadata parent's
inherited product root is not this candidate source.

Fixed parent: `815dc12b7786783a7f6004d5360640d37ee49309`.
New prefix: `handoff/checkwash-artifact-checkpoint-20261027`.
Every invocation freshly checks the exact branch tip and expected fetch/push
origins. Both baseline and candidate/index/main/tags guards run before/after
planning and immediately before/after an eventual push.

The only binary exception is the exact completed artifact ZIP
`checkwash-1be28ce5-artifact-checkpoint.zip`, SHA256
`eba17306f0e3d221677e1483e464ed25c992b9e021a03c0e71a590c63ec7537f`,
13,769,469 bytes. It must match pack-receipt raw SHA `c2b76ae9...83dce8`,
frozen pack plan `308aea36...7ee1bb`, fixed packer `b4203819...d67edf`,
independent pre/postpack audit pins and every one of the 125 planned member
bytes, CRCs, regular modes and deterministic metadata. Embedded manifest,
selected terminal state and artifact-source closure must equal the frozen
plan. The original full recursive privacy/source-closure checks therefore
apply to the same exact archive bytes. No generalized binary/archive permission
or scanner/default flag is added. Every other payload item still passes the
original unchanged text-only content/privacy guard.

The four original pack outputs retain exact bytes: archive and sidecar retain
their basenames; original entry and manifest are mapped remotely to
`ARTIFACT-START-HERE.md` and `ARTIFACT-MANIFEST.json`. Publisher controllers,
their exact original/diff, fixed plan and independent provenance are additional
audited text. There is no live qualification output. The raw ZIP and its 125
members never change. `--prepare` writes transport files under this publisher's
`prepared-payload/` plus only the new local `00-REMOTE-HANDOFF.md`; it never
overwrites the original pack entry/manifest/archive/sidecar.

`publication-input.json` is a frozen root-confirmed snapshot binding the exact
archive, public visibility disclosure and statuses of excluded validations.
It contains no user-supplied paths. Current wrappers retain fixed323 passes,
parent self-check PASS/0H3W, integration BLOCK/3H12W, actual build/smoke exit0,
and read-only NOT_IMPLEMENTED #263 analysis. Full suite and qualifications are
separate; no terminal acceptance is included or inferred. No merge, tag,
Release, PyPI upload, new 1.0 authorization or product acceptance occurs.

Default mode is read-only Git/metadata planning. After independent review,
root alone may use `--publish --expect-plan-sha256 <exact digest>`. Alternate
index additions only, no hooks, normal nonforce push, `--no-follow-tags`,
single expected remote and source/input/output pre/post guards are unchanged.
An unknown push stops with prepared recovery receipts and must be reconciled,
never blindly retried. The raw frozen pack inputs, source and stage7/stage9
results are not changed or rerun by this tool.

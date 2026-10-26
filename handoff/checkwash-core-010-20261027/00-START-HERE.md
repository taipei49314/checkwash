# CheckWash 0.10.0 handoff checkpoint

This is a task backup, not a product release or an acceptance receipt.
Snapshot time: 2026-10-26T18:55:09.778910+00:00. Product work is not being rushed for
the host transition. Read `checkpoint.json` for the state of this snapshot.

## Source to continue

- Product source: `8a8941dc2d7c581715a0f6f196c00da6c55f084b` on `fix/ux-repairs-20261026`.
- Review: https://github.com/taipei49314/checkwash/pull/566
- Eight unchanged golden expectations: https://github.com/taipei49314/checkwash/issues/567
- Package 0.10.0, IR3, findings2. No 0.10.0/1.0 tag, Release or PyPI
  publication is performed by this backup. Stop for the maintainer before 1.0.

The handoff branch inherits the source but adds evidence. Check out the exact
product SHA in a clean task checkout before testing; do not label this handoff
commit as tested product source. Keep downloaded evidence outside that checkout.
Read the source's STATE.md, AGENTS.md and docs/repair-integration-0.10.0.md.
Use current host policy and actual hostname/runtime. PJU receipts retain
HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL; copying them never certifies another host.
Do not investigate the stopped pool outage or revive consumed history/model runs.

## Completed and pending

All core repair code is integrated. The 1,117-case full findings+IR corpus is
byte-identical on Windows Python 3.11.9 and 3.12.14; 3.12 focused tests passed.
The final 36 native observations retain 26 explicit assertions and 10 observation
rows; use the report for the exact 24 BLOCK / 12 PASS and baseline differences.
The full 21,102-parent-test run has not started at this snapshot. Artifact
qualifications may still be running; their partial stream prefixes are not PASS.
Other OS/Python 3.13/native file-symlink coverage is not inferred.

The eight golden labels are unchanged and unresolved. `golden/UNADOPTED-*` is
an inert proposal, not a human approval or a modified-judge PASS. Do not apply it
without the individual disposition. No exemptions or acceptance waivers were
added to make this candidate green. Original failed/partial records remain.

## Privacy and continuation

Original local milestone ZIPs contain full global context and nested older ZIPs.
They are preserved locally and are not blindly published. This checkpoint
contains only task-specific source identity, controls, partial raw prefixes and
resume tools. Runtime environments, caches and fixture temporary repositories
are excluded. A later checkpoint can append completed raw evidence and results.

`resume-tools` computes the original task layout from its location. Restore into
an equivalent separate task workspace, inspect absolute interpreter paths, and
create isolated environments appropriate to the authorized host. Historical raw
paths/times must remain historical; do not rewrite them or synthesize missing
results. Interrupted ordinary qualification may be run fresh under a new label,
retaining the partial attempt. This does not resume any consumed once-only batch.

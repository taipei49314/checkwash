# Selection correction — 2026-10-09

The original selection and its pins are preserved. This is an additive
correction to the 2026-10-07 record, authorized in the local handover on
2026-10-09. The selection was purposive, not a random draw. Eligibility is
**UNVERIFIED** for all six repositories; no held-out result is claimed.

## Reading and timing

The supplied handover reconstructs the following UTC chronology from the
selecting session's tool metadata. The local successor did not read other
sessions or independently reconstruct those original logs; these times are
attributed to the handover, not presented as newly observed events.

| 2026-10-07 UTC | reported action | relationship to selection |
|---|---|---|
| 19:30:28 | HEAD lookup for vuejs/core and fastify/fastify (E4) | before |
| 19:30:57 | shallow, no-checkout clones; manifests and runner dependencies read | before |
| 19:31:16 | typeorm manifests, test-path count and HEAD commit title read (E2) | before |
| 19:31:30 | six repositories and pins written to the selection list | selection time |
| 19:37:18 | history clones and non-merge commit counts (E3) | after |
| 19:38:02 | test-path counts at the pins | after |
| 19:38:14 | import/require lines sampled from one test file per repository (E1), reported as 21 lines and 1,209 characters | after |
| 19:38:48 | selection JSON written, retaining the earlier selection time (E5) | after |

The README's statement that only manifests and paths were read is therefore
incomplete. E1 exposed test-file contents, and E2 exposed a commit title.
E2 and E4 preceded the recorded selection time; a prior audit's statement
that E1–E5 all followed it was false. The handover reports that the names
and pins were already fixed before E1/E3. It does not establish the absence
of an influence from earlier metadata or the author's memory.

For undici, the runner classification `node:test (borp)` came from the
manifest's borp dependency. The `require('node:test')` observation came
from one sampled file. The count 514 was a test-path count; it did not
establish that all 514 files called `require('node:test')`.

## Exclusions and independent follow-up

[Issue #132, section 4](https://github.com/taipei49314/checkwash/issues/132)
records a 2026-09-06 v0.2.13 sweep of axios, express and commander, among
ten repositories. That public record was independently retrieved during
this handover. These repositories must be excluded from any future
held-out draw; their omission from the original exclusion list is a
recordkeeping defect. The original list is not rewritten.

A separate catalogue check found axios/axios, expressjs/express and
vitest-dev/vitest registered as planned, excluded entries. Registration
alone was not treated as evidence of an engine run. The claim that
chalk/chalk was measured remains unverified and is not promoted to fact.

The bounded follow-up audit found no confirmed engine sweep or detector
tuning on the six selected repositories. One downstream dependency
inventory contained undici paths and hashes; this is dependency exposure,
not evidence of a history sweep. The audit also has missing logs and
unexamined channels. Earlier sessions, other machines and contributors
remain unverified under the owner's scope decision. Absence of a match in
the inspected material does not qualify any repository as clean.

## First-run status

The corpus is conditionally retained without resampling. Qualification
under SPEC section 10 remains unresolved. Candidate identity, artifacts,
harness, classification whitelist, timeouts, machine versions, prediction,
adjudication and custody must be frozen in a committed preregistration
before any first measurement. This correction is not that preregistration
and does not authorize a run to be labelled held-out while eligibility is
unverified. No individual measurement result was opened for this note.

Source boundary: an AI-authored handover plus the bounded successor audit.
The handover archive SHA-256 is
`44785b65ffdfce714496f123d7dd6740ad032398f4b51ca3c2264c5daea2864d`.
Private raw evidence and session identifiers are retained outside this
public repository. The handover's AI reviews are not human adjudication.

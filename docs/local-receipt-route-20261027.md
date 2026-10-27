# Task-local receipt execution routes

On 2026-10-27 Nelson instructed the continuing repair chat:

> 照著繼續做 完整spec在裡面 一樣我只卡1.0發佈前 其餘你可以自主推

The following scope is agent interpretation of that instruction: continue the
pre-1.0 repairs, use a task-local environment on the current LAPTOP-16NUA5I8,
and record its actual execution rather than claiming PJU execution. This does
not attribute individual case reviews, platform execution or extra words to
Nelson. The task's original instruction and interpretation are retained in its
external `work/session-authority-20261027.json` record.

The trusted collector and data verifier support two exact Windows routes:

| Actual host | Receipt provenance | Composite replay provenance |
| --- | --- | --- |
| LAPTOP-01AGNPJU | HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL | PJU_LOCAL_COMPOSITE_REPLAY |
| LAPTOP-16NUA5I8 | HUMAN_AUTHORIZED_LOCAL_16NU_NOT_EC_POOL | 16NU_LOCAL_COMPOSITE_REPLAY |

The native hostname selects collection; no environment variable or candidate
argument can override it. The verifier binds a receipt, both Action replays and
its prior-stage report to the same route. New reports and check summaries name
the actual host. Legacy `pju` protocol kinds, external IDs and required check
names remain stable for existing links; those names are not execution claims.
Historical PJU packets keep their original host and provenance unchanged.

Prior-stage route fields also have to match the exact first header of every
native GitHub App check already bound by source, success and the external
manifest digest. Only the historical PJU publisher header and current local
or release-stage publisher headers are recognized, at the start of the summary
followed by a blank line. A rewritten report cannot reuse an unchanged check
whose header identifies the other host. This is consistency within the existing
authenticated App metadata boundary, not a new signature over reports or proof
of the physical machine.

This is a task-specific route extension, not a global execution-host default or
authority for arbitrary sources. The owner-admitted immutable collector source,
candidate source, native workflow, evidence digest and source-specific packet
remain the trust boundary; the route table is not hardware attestation. The
receipt verifier still certifies only Windows/Python 3.11.9, and all unexecuted
platforms remain NOT_RUN. Raw failures, partial results, full-suite scope,
source/wheel/pyz qualification, inventories, stage linkage, required checks,
publication authorization and PyPI deployment protection keep their existing
requirements. Stop before 1.0 for Nelson's decision.

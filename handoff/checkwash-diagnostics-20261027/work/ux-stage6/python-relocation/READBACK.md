# Independent existing-diagnostic readback

Final readback: `existing-diagnostic-readback-r3.json`.
SHA256 `fff6432a428e8a5fcaa50cb8a47d1219d2e25d4fafb0f695d8e3719334b35faa`.
Reader terminal exit0, 82 checks. This agent made **0 product/API/CLI/pytest or
fixture-program calls**. It used standard-library AST parsing/literal string
construction and JSON/hash reads of root's already completed observations.

Root's bounded-context-r1 capture identifies unchanged source
`fbc9374dc3bcbfc47f403aec0c36e6b51dd7b86c`, input map
`51836ac93ce5670644a050f8e3ced2390d377b63bff4b956cc52741b291f9ee5`,
host LAPTOP-01AGNPJU / Python3.11.9 and
HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL. Capture exit0 means the diagnostic
capture completed, not that the original positives passed. Its 12 observations
include 4 Python arms reviewed here and 8 JS arms outside this readback's scope.
Root's driver records fixture execution0 / pytest0 / CLI0.

The four local inert fixture copies match the original test constructors
**exactly in raw bytes**, including blank lines. AST parsing did not import,
compile, eval, exec or call a test/fixture constructor. Every consumed before/
after string and SHA256 in the four API records matches those bytes. The
complete closed snapshot maps (including APP) match, raw record hash/size equals
root's results.json declarations, and all input files were unchanged after read.
Both test modules plus engine.py/oracle_credit.py match the source hashes in
the captured fbc input map.

| Existing fbc API arm | Actual result | Actual optional proof observation |
|---|---|---|
| 263-original | BLOCK; two TEST_DISABLED/high, no de-escalator | startup unknown on both sides; both proofs empty |
| 263-closed-root | BLOCK; same two high findings, no de-escalator | startup known `[]`; two before proofs present, both class-arrival proofs empty |
| 358-original | BLOCK; TEST_DISABLED/high, no de-escalator | present sides have known startup `[]`, but both unit/assertion proofs empty |
| 358-no-gate-control | PASS; TEST_DISABLED/info + ASSERTION_MOVED | before/arrival unit context and assertion context are equal |

The no-gate unit context is
`162e9b0009da65fea414cd439fe3864158cfd42108a9e9bd9f33a673aa2bdb5a`;
its assertion context is
`deb291458a84097ab76630f8a98c68cc8988a394a0a846a7040d498c8c94191a`.
Removing the fixture was an independent control, not a proposed fix to the
original test. First rejection branches and the safety of new projections still
require source reasoning; mark_context_calls does not trace individual branches.
No proposed/modified judge or future movement was executed.

The r1 and r2 audits remain preserved. R2 added complete exact snapshot maps;
r3 additionally bound relevant current source bytes to the captured fbc input
map. These are stricter metadata readback revisions, not repeated product runs.
The final source/ordinary-test proposals remain DRAFT_NOT_ADOPTED and need a
new-source red/green/regression round before any PASS or acceptance claim.

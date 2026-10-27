# D176 cost disposition for 0.10.0

This is a new, source-bound Codex decision under Nelson's current continuation:

> 照著繼續做 完整spec在裡面 一樣我只卡1.0發佈前 其餘你可以自主推

Codex interprets this as authority to complete the pre-1.0 work and make the
concrete version-specific decisions below after independent review. This
record does not claim Nelson personally reviewed these three cases or typed
the technical hashes and limits. Normal release gates remain; the decision
does not authorize 1.0.

## New targeted observation and source review

The new `known-cost-010-r1` diagnostic checked three exact uvloop first-parent
changes with actual published v0.9.0 pyz and frozen engine source
`9678e8de564ed47f7ff92867d5c7d09358c04fcb`. All six CLI calls completed on
LAPTOP-16NUA5I8 / Windows / CPython3.11.9, with unchanged source, runtime,
artifacts, bare Git inputs and verified before/after commit/diff identities.
Their config-error and skipped-file lists are empty. The outer captured job
exited zero in 39.031 seconds under its 1,500-second limit; no retry occurred.

| uvloop commit | original first parent | actual change | source review |
|---|---|---|---|
| `7b202ccf644396a4ae8ff8053578058f5023ac63` | `ae44ec2d9d3b13c708bd65cf91c52178c37f34a4` | PASS / one WARN to BLOCK / one HIGH | The factory callback relays its assertion failure into `factory_called_future`; the test awaits it. |
| `2081db8927dc2d3a66b7c8d7aa317d71aba198f9` | `c808a663b297bb2aee745523c277d6fafecebbeb` | PASS / one WARN to BLOCK / one HIGH | The client thread relays failure into `fut`; `run_main` awaits it through `wait_for` before `run_until_complete`. |
| `9cba7493a152e5a77bbde9a32143d84433d1cd3d` | `ee054206b00c15988f0f71c4a947cb4d13d2af5a` | PASS / two WARN to BLOCK / two HIGH | The direct-assertion catchers in `test_create_server_ssl_over_ssl.test_client.prog` and `test_shutdown_timeout.test_client.prog` relay failure into their local `fut`, then through `await`, `gather`, `wait_for` and `run_until_complete`. |

The last row preserves two occurrences with the same fingerprint; it is not
collapsed into one. Native findings retain `unit=None` and zero spans. The
named association comes from reading the original source and actual parser
criterion, not invented native locations. Other new helper catchers that do
not lexically guard assertions are not those two occurrences. These are
source-reviewed legitimate regression-test additions with conservative false
blocks. Neither review runs uvloop or proves represented runtime behavior.

All four actual `BROAD_EXCEPT_ADDED` findings keep HIGH/BLOCK and
`OPAQUE_PROD_CHANGE_NOT_EVIDENCE` (E1). E2/`ORACLE_FREEZE` is a separate
mechanism. No labels, findings, thresholds or allowances are changed to pass.

## Delegated decision and limits

Codex accepts these three known false-block costs and the explicitly
unmeasured remaining-history risk for **0.10 only**. The narrow refusal remains:
opaque production changes do not prove that caught Python test/conftest
assertions can still fail. D171's old five-rule blanket remains off. #419 and
the documented threat-model gaps stay open.

The old R4 remains partial and consumed: 881 completed comparisons comprise
879 returned envelopes and two identical exit2/not-analysed members. Three
returned-envelope members retain seven omitted-file occurrences. One partial plus
6,553 unattempted members leave 6,554 incomplete comparisons in that old run.
Only three members of its completed prefix have this new targeted current
replay; the other 878 did not gain a current observation through this job.
The actual R29 [comparison record](r29-comparison-0.10.0.md) joins exact
member/parent/source identities. One of nine retained old identity fragments
occurs in B: Apollo8a51, old ordinal593, still native exit2/not analysed.
The full old ledger is unavailable, so further cross-run overlap remains
unknown. New observations cannot rewrite the old run or turn omissions into
analysis; this diagnostic still establishes no current observation for the
other878 through its own six calls.

This is a release-specific risk decision, not history PASS, a completed
census, an adjudicated rate, a standing waiver, or a resumed R1/R2/R3/R4 grant.
The separately admitted two-set R29 attempt B completed 3,600 pairs/7,200
historical CLI calls. Both sealed audits and root's explicit manual review
accept mechanical completion only, with the unexplained cross-clock difference
retained. Its separate final19-movement join and delegated current0.10
cost/residual-scope decision are now closed, retaining all87 native HIGH
occurrences and unknown coverage. That decision does not establish full
coverage or waive formal release gates; this D176 decision does not substitute
for it.
The exact engine applicability is `src/` tree
`ee6716662fe264b5425958f00835567a4ffca4d6`, with only the documented sole
version-literal equivalence permitted. Later tool/document sources need their
own matching stage validation.

The source/cost proposal SHA256 is
`473ae0236e77ba52d24c2fb7d320aea34033ce8f60a1e0a4ebb7935f268baa3a`;
independent terminal/source review
`98efdc83a442d60bac40944d846cb103458277496f3203d7106fcd572a1590e2`;
independent proposal review
`224a4f8bdc445948862fd784f2fcb07cba5cb4c980df5c2d534c17cc8860e41a`;
and the separate Codex delegated decision
`507fc6ce666551f6ba52b5b81f1a357aca7bc97e65206330061fd73fadb5e97c`.
The actual future PR/main/tag/release/public-visitor evidence remains separate.

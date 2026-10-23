# Decision log

Entries D-001 to D-140, everything up to and including the v0.8.0 release
entry, are in [DECISIONS-archive-1.md](DECISIONS-archive-1.md). They moved
there unchanged on 2026-10-20, when this file had passed 1,000,000 bytes,
checkwash's source byte limit, above which it sets a documentation file
aside unread (F40). The archive keeps the line numbers they had here: read
against `94953c83`, the last commit before the move, a reference
`DECISIONS.md:N` with N up to 10833 is `DECISIONS-archive-1.md:N`. Any
other line reference written before the move reads against that commit.
Entry numbers do not change, and new entries are added here.

Entries D-141 to D-172 moved unchanged at v0.9.0 publication to [DECISIONS-archive-2.md](DECISIONS-archive-2.md), except its prescribed archive title and single-line provenance; old line references read against release commit d6eda4f6.

## D-173 (2026-10-23): post-publication verdict baseline v0.9.0, separate from advertised pins

After approving the real PyPI deployment, Nelson instructed this chat:
「PyPI 已核准，照既有 G4 繼續，把 v0.9.0 的公開產物驗證、pins 更新和 baseline rotation 做完。」
The existing G4 grant explicitly includes the separate rotation PR while
retaining his disposition of protected changes. This entry records that
bounded continuation and its metadata bookkeeping, not a new case ruling or
standing authority for another release.

The baseline becomes public v0.9.0, version 0.9.0, release commit
`d6eda4f695fabb8e7d138f7a87b099d2028f0294`. Its actual Release pyz is
914407 bytes, SHA256
`7319152cdf4889df4d58b454dc63072bb2e923823e1b2ce09677e4381dbccd5c`,
independently downloaded and verified by hosted run `39821892775/1` after
human-approved release run `39817071157/1` completed successfully.

The protected `tests/gates/verdict_gate_accepted.toml` changes only its
baseline header and explanatory comment from v0.8.0 to v0.9.0. It has no
`[[accept]]` entries; none is added, retired or re-adjudicated. Existing case
labels, fixture expectations and the rule that a still-passing block-labelled
case needs acceptance remain unchanged. A future stale entry can be removed
only when specifically named by a rotation receipt and covered by its ruling.

Tag verdict `39811579829/1` ran 185 cases with zero failures/reported moves,
159 block-to-block and 26 pass-to-pass against v0.8.0. It proposed no changed
blocked/T3 pin; the chai input blob is unchanged. Thus `baseline_blocked`
stays 159 / `9993cab624a6ee1831a27f33fb48088676a639e9f5dd2a1b69361f1048c3f3a4`
and the 26-case T3 map stays. Canary v0.4.2 to v0.5.0 and its 71 known
block-to-pass IDs are not rotated.

Acceptance of this configuration still requires this independent rotation
PR's fresh hosted verdict against the actual public v0.9.0 pyz, with full
185-case coverage and no baseline/member/pin/acceptance drift, plus its other
required checks. Earlier tag receipts are the proposal basis, not a substitute
for that run. Native PR/main results and exact identities are retained with
the closeout evidence. No local product execution, public tag change or
downstream re-pin is part of this rotation.

## D-174 (2026-10-23): measured keyword-operand acceptance, addendum to D-143 (#462)

Nelson approved the concrete D-143 addendum in PR #558 and its conditional
merge/issue closeout in this chat on 2026-10-23:
「核可草稿，檢查通過後合併並結案（建議）」.
This was an assistant-written reply option. The approval covers this
wording and merging #558 after its current CI/dogfood gates pass, then
closing #345 and #462. It grants no new workload execution or publication.

The frozen combined sweep measured a418 (`717a705d5291913cea98544ffd57b191e0d07a88`)
to a462 (`2422b3cebcebdb4cbf25ca0d567589d8bb6b540e`) on 3,018 members:
2,599 pass→pass, 400 block→block and 19 error→error, with no outcome,
finding or stdout differences. The kw462 selection has two members,
both pass→pass, with no new finding. Both requested difference lists
are empty; the selection is nonempty. This supplies D-143's subsequent
measurement under R2–R7 and keeps its original preparation record
unchanged. Provenance is human-authorized local PJU, NOT EC pool,
under the previously approved frozen declaration. This does not
establish a general false-positive rate or resolve the named syntax
residuals.

Sources: [frozen combined sweep](https://github.com/taipei49314/checkwash-lab/blob/92d771e2bfb41b1109b57cce55f3df2a0e99726d/evidence/v090-sweep-results-20261022.md);
[exact pair/engine/count extract](docs/releases/v0.9.0-issue-closeout.json);
[issue result and remaining gate](https://github.com/taipei49314/checkwash/issues/462#issuecomment-6360716240).
The source combined JSON SHA256 is
`b9946817dacdcbd9ebec052e0910e1e2e30aa7dd0dc3e0e04e145d6d68e9e2db`.
D-143 in DECISIONS-archive-2.md remains unchanged as its dated preparation
record. This later addendum records the approved measurement without
relabeling those old arms as a fresh rcprime run.

## D-175 (2026-10-23): measured class-decorator acceptance, addendum to D-149 (#487)

Nelson approved the [concrete D-149 measurement draft](https://github.com/taipei49314/checkwash/issues/487#issuecomment-6360870539) in this chat on 2026-10-23 by selecting 「核可補記，檢查通過後合併並結案（建議）」, an assistant-written option. The scope is this measurement text, merge after current CI/dogfood passes, and closure of #487. It grants no new workload execution, publication, expanded decorator support or log-capture equivalence ruling.

The frozen a429b (`f4b65db6d33cecb5fc460a43aff2ad881764aa61`) to a487 (`637222e8cffd8f5fbfa0aa0502852a139af78f22`) pair completed all 4,818 declared members across standard, D-088 and the extension/JavaScript sets. Outcomes: 4,355 PASS→PASS, 440 BLOCK→BLOCK, two BLOCK→PASS and 21 unchanged product errors. Nine rows have finding/stdout differences; the errors are not passes.

All seven D-149 watch commits match its expected effects. `c8aa429c9b` returns to PASS with four warn findings; `e058a05763` returns to PASS with six TEST_DISABLED warn findings. `14737e91ed`, `36c3c9713e`, `c5b1ee8101` and `c76190d491` stay BLOCK without the 37 added ASSERT_REMOVED. `02ed71d887` stays BLOCK without the extra ASSERT_SUBSTITUTED high, retaining its 71 TEST_DISABLED high and separate ASSERT_WEAKENED high.

The two additional BLOCK→BLOCK rows have been reported and source-reviewed. On scrapy `6b2997af`, 30 newly exposed ASSERT_REMOVED/high findings are assertions still present in two still-called helpers that become static methods; four EXPECTATION_DEFINITION_CHANGED/high findings keep the same response-request equality while the requested URL moves from setup state to a fixture argument. One ASSERT_WEAKENED/high finding keeps an exact warning-match count of one but changes the log-capture API; full capture equivalence remains unverified. On scrapy `b4d11b8b`, four newly exposed ASSERT_REMOVED/high findings are unchanged URL guards reached through test methods newly carrying a coroutine-to-Deferred decorator. These expose helper-reading and existing-detector boundaries; they are neither new blocked commits nor 39 adjudicated true positives.

This supplies D-149's later measurement and report-other-changes condition without broadening its supported decorators, changing existing fixture expectations, or adjudicating the remaining log-capture equivalence. It establishes no general false-positive rate. The archived D-149 preparation entry stays unchanged. Provenance is existing human-authorized local PJU, NOT EC pool; no new execution occurred. The whole combined manifest remains incomplete because of separately stopped/deferred arms; this pair is complete under R2/R3/R6/R7.

Sources: [frozen combined sweep](https://github.com/taipei49314/checkwash-lab/blob/92d771e2bfb41b1109b57cce55f3df2a0e99726d/evidence/v090-sweep-results-20261022.md), [exact pair extraction in #558](https://github.com/taipei49314/checkwash/blob/c991936d0f283db3b265a2065af0ca99d825de9b/docs/releases/v0.9.0-issue-closeout.json). The source combined JSON SHA256 is `b9946817dacdcbd9ebec052e0910e1e2e30aa7dd0dc3e0e04e145d6d68e9e2db`.

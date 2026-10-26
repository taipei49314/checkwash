# #567 eight-case fixture ruling proposal — NOT ADOPTED

**INERT_NOT_APPLIED_NOT_ACCEPTED_NONPASS_STILL_OPEN**

This is a reviewable expected-only patch for an explicit human maintainer
decision. It is not authorization, acceptance, a new PASS receipt, an exemption
or a change to any product-repository fixture. #567 and all eight existing
native failures remain open. No existing corpus label has been edited.

The precise proposed action is the eight-file `expected-only.patch`, SHA256
**df5751ba709fbe85abd781dd443a4926e54bd1e22c0521dc224132267720bbe4**.
It changes11 expectation rows: severity becomes high and the obsolete required
move/restructure credit is replaced by the observed applicable escalation.
Finding counts, rules and all previously specified unit constraints remain.
The independent ASSERT_WEAKENED expectation in the device-id case is byte-for-
byte unchanged. No input, fixture name, metadata, runtime source, gate,
acceptance file, allowlist or exemption is included in the patch.

## Exact proposed rulings

| Fixture stem | Original expectation to proposed expectation | Per-case reason |
| --- | --- | --- |
| bare_bound_then_used_neg | TEST_DISABLED warn/RESTRUCTURED to high/NO_PROD_CHANGE_IN_DIFF | Different obligation: the output invoice_total==105 check disappears and the new assertion checks the input list. Oracle mass does not establish the original output obligation. |
| split_rename_genuine_neg | TEST_DISABLED warn/RESTRUCTURED to high/NO_PROD_CHANGE_IN_DIFF | Different subject normalization: sorted(options(...)) may hide ordering/container distinctions. No equivalence proof is supplied. |
| unittest_keyword_split_neg | TEST_DISABLED warn/RESTRUCTURED to high/NO_PROD_CHANGE_IN_DIFF | Same sorted-subject boundary in unittest syntax. Keyword operands remain supported; that support does not prove subject equivalence. |
| test_split_neg | TEST_DISABLED info/ASSERTION_MOVED to high/NO_PROD_CHANGE_IN_DIFF | Unknown setup/defaults: one destination now calls make_app(automatic_options=True) instead of make_app(). The fixture supplies no implementation/default proof. |
| subject_pairing_other_subject_known_limit_pos | Two named TEST_DISABLED warn/RESTRUCTURED rows to high/PROD_CHANGE_NOT_EVIDENCE; original ASSERT_WEAKENED high row unchanged | Unknown fixture/setup/input rewrite in the two warning tests. The separate old-subject replacement remains independently blocking. Overall actual verdict was already BLOCK before D179. |
| assert_removed_moved_neg | ASSERT_REMOVED info/ASSERTION_MOVED to high/NO_PROD_CHANGE_IN_DIFF | Unknown assertion effects: login calls move across test units/order. The fixture supplies no purity/source proof permitting prior/following calls to be erased. |
| js_chai_property_moved_neg | ASSERT_REMOVED info/ASSERTION_MOVED to high/NO_PROD_CHANGE_IN_DIFF | Unknown assertion effects: isPaid/total calls move across callbacks/order. Verbatim property assertion text alone is not execution-context identity. |
| merged_parametrize_neg | Three TEST_DISABLED warn/RESTRUCTURED rows to high/NO_PROD_CHANGE_IN_DIFF | Unknown dynamic lookup: table/input substitution remains supported; getattr(parse(url), attr) is not assumed identical to direct attribute access across opaque calls. The independent imported-bootstrap counterexample established why unconditional projection is unsafe. |

These are proposed acceptance choices for D179's boundary. In particular,
unknown setup, call effects and dynamic lookup can reject legitimate refactors;
those are compatibility costs, not measured claims that the original projects
were malicious or that their real runtime behavior changed. The first case
checks a different obligation; the sorted cases change the subject. The
unchanged `_neg` filenames and old narrative metadata are preserved exactly;
their old prose is historical input, not evidence that this proposal was adopted.

The patch deliberately retains the existing subset matcher language. It does
not copy complete actual findings, widen severities, permit either outcome,
remove finding-count constraints or replace the independent weakened finding.
An empty deescalators list would not assert absence under this matcher, so no
such misleading negative constraint is added. Separate D179 tests retain the
no-unproved-credit checks.

## Provenance and validation boundary

Every original fixture was read as raw bytes from Git baseline
9a5a27f44c895ba2fdee8c83a6313baf0e120873. At observed HEAD
0e286682340fd0e4533aaff72a55c9b020ffee7b, its Git blob and working bytes were
identical to that baseline. `originals/` preserves the eight full originals;
`rulings.json` records each full blob ID, SHA256, before/proposed expected
objects, actual old/new verdicts and retained new finding dictionaries.
The prefix before `=== expect ===` is asserted byte-identical for all eight.
Other existing expected keys and the original number of findings are preserved.

Actual cost evidence is reused, not rerun:

- immutable-cost-register.json SHA256 fb2bd09800319a67aa8e34fd51fd285f8fa8d3d575b87270deb41cea24125adf
- cost-r4/results.json SHA256 f40d55f9c972ec203adc5ffd659e5b8553f26c114eb2969267e0696a173f4149
- Actual old/new verdicts: seven PASS-to-BLOCK; the independent subject-pairing case remains BLOCK-to-BLOCK. All eight original expectation mismatches remain unresolved acceptance failures.

`source-binding.json` retains the full measured candidate source hash map,
baseline source map, runtime, command-driver identities and source-stability
flags. Those measurements bind copied development working bytes, not a claim
of exact-HEAD or final release qualification. The relevant measured files are:

- oracle_credit.py dae96be0b17b411dfbdd3e44f03aafbebbfd87ecefbbeacee1d483b44de20155
- engine.py f3ad9f34db31dc168a119a788ace37dbea60e8b834cf175b1ca5165384b8096d
- gating.py 2a84a2018fa5dbcb4f2e0506b10a9e0cb931779c6aab236c4bdbccf3308ad7ec

The sole prediction is explicitly static: the unchanged pinned 9a matcher
function was extracted without importing product modules, verified identical
to the current function, and applied only to retained finding dictionaries.
It predicts that the proposed expected objects match those stored findings.
That is not an executed proposed-label golden test, a CLI result or acceptance.
No modified judge or fixture program was imported/executed. This proposal
performs0 new product/fixture test calls. Raw read-only Git command streams
and exits are in git-read-receipts.json and git-reads/.

Host LAPTOP-01AGNPJU / Python3.11.9,
HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL. validation.json distinguishes original
integrity, static prediction and the still-unapplied/unaccepted state.

## Exact final human decision, if desired

A future explicit approval can identify only this artifact and these eight
fixtures, for example:

> 核可 #567 八案 expected-only.patch（SHA256 df5751ba709fbe85abd781dd443a4926e54bd1e22c0521dc224132267720bbe4）的逐案新 ruling；僅按此 patch 改八份 fixture 的 expect，保留所有輸入與其他約束，再跑固定來源的實際驗證。

This is a proposed approval statement, not an approval received. Even after
such a decision, application and actual fixed-source validation would be
separate work. It grants no exemption, acceptance bypass, merge, publication
or version1.0 permission. Until that explicit decision, the patch stays inert
and #567's eight native failures remain NONPASS/open.

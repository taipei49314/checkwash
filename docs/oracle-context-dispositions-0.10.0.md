# Oracle-context compatibility dispositions for 0.10.0

On 2026-10-27 Nelson instructed: 「照著繼續做 完整spec在裡面 一樣我只卡1.0發佈前 其餘你可以自主推」.
Codex interpreted this as delegation to complete the pre-1.0 repairs, including
independently reviewed, case-specific expectation migrations. The reviews below
were performed by Codex; they are not represented as Nelson's personal case
reviews. The original D179 proof boundary remains in force.

The source-bound static readback at `1be28ce5` observed all twelve cases as
BLOCK. No represented fixture program was executed. The full original eight
golden files, old expectations, program-input hashes, four corpus input maps
and complete finding vectors are retained in
`tests/compatibility/v010/dispositions.json` and its adjacent `legacy/` files.
Only expectations change; source programs, gate scripts, severity, strength,
alignment and exemptions do not change in this migration.

| Identity | Disposition |
|---|---|
| bare_bound_then_used_neg | BLOCK: output equality was replaced with an input-data equality. |
| split_rename_genuine_neg | BLOCK: `sorted` hides order and container distinctions; conservative unproved-subject cost. |
| unittest_keyword_split_neg | BLOCK for the same subject change; keyword operands remain supported. |
| test_split_neg | BLOCK: changed make_app argument lacks a producer/default proof; conservative setup cost. |
| subject_pairing_other_subject_known_limit_pos | Retain the independent ASSERT_WEAKENED and two blocking unproved fixture rewrites. |
| assert_removed_moved_neg | BLOCK: unknown login calls are reordered across units; conservative call-order cost. |
| js_chai_property_moved_neg | BLOCK: unknown calls are reordered across callbacks; conservative callback-order cost. |
| merged_parametrize_neg | BLOCK: the specified getattr-to-attribute projection remains unsupported. |
| CASE_020_windows | Known legitimate refactor, retained as an additional false block until a bounded helper proof exists. |
| CASE_029_flatten | Known legitimate refactor, retained as an additional false block until framework/class/context proof exists. |
| d007-factorial-of-zero | Newly caught escape: the zero-input obligation disappears. |
| d010-stack-is-lifo | Newly caught escape: the LIFO expected result changes from 2 to 1. |

The original #263 class/marker control and #570 plain-describe control also
lack their called producer and closed startup evidence. They now explicitly
require BLOCK without move credit. Separate closed-source controls establish
the supported positive domains; the original programs are not silently padded
with invented producers. Unknown broader cases remain conservative.

The focused compatibility test checks immutable original bytes, unchanged
program inputs, retained finding identities and absence of all relocation,
restructure, split and duplicate credits. This is stronger than the golden
format's subset matching. Frozen historical runtime qualification and old
benchmark counts retain their source/date identities; this migration is not a
new universal precision measurement or a release PASS.

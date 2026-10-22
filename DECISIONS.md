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

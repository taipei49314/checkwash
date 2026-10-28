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

Entries D-173 to D-187 moved unchanged at v0.10.0 publication to [DECISIONS-archive-3.md](DECISIONS-archive-3.md), except its prescribed archive title and single-line provenance; line references to those entries written before the move read against release commit 10069979.

## D-188 (2026-10-28): post-publication verdict baseline v0.10.0

Asked whether Claude should carry out the v0.10.0 decision-log cut and the
verdict-baseline rotation, both of which change agent-read-only files, Nelson
chose the offered reply 「授權 Claude 做」 on 2026-10-28. This entry records
that bounded rotation and its bookkeeping, not a new case ruling or standing
authority for another release.

The baseline becomes public v0.10.0, version 0.10.0, release commit
`100699796d942af30644738ffbcd1f1c939411c5` (tag object
`90210d81dd714f49e3ee6e2b1ccbb7c7428fe15b`). Its Release pyz is 952399 bytes,
SHA256 `9a58d3d48f4f314a46b153bc0b7ad5182829c210a3ce9dae575c46f2f3bc535a`:
the asset the release-event receipt built and the public-visitor stage
downloaded and verified
([publication record](docs/releases/v0.10.0-publication-verification.md)).

The protected `tests/gates/verdict_gate_accepted.toml` changes only its
baseline header and comment from v0.9.0 to v0.10.0. It has no `[[accept]]`
entries; none is added, retired or re-adjudicated. Case labels, fixture
expectations and the rule that a still-passing block-labelled case needs
acceptance remain unchanged.

A PJU proposal run of the gate (LAPTOP-01AGNPJU, Windows, CPython 3.11.9,
`HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL`) used candidate `ed923b44`, whose
`src/` equals main `d344bf1f`'s, with main's cases, labels and pins except the
rotated `[baseline]` and the acceptance header. It ran all 185 cases (159 T1,
26 T3): 160 block -> block, 25 pass -> pass and zero reported; the canary's 71
block -> pass IDs are unchanged. It exited 1, and its only failure was the
retained blocked pin: v0.10.0 also blocks i197/Q5a, the PASS -> BLOCK movement the v0.10.0
release disclosed ([release guide](docs/releases/v0.10.0-public-launch.md)).
So `baseline_blocked` becomes 160 /
`40be07fce6801395902303cd2da797d7a4e473ef46d1b8444892d607a2dc4cd0`, with no
case removed. Q5a keeps its `pass` label. The chai input blob is unchanged
(`4f363109`), so the 26-case T3 map stays, and the v0.4.2 to v0.5.0 canary is
not rotated. Its receipt (SHA256
`daed2bbe9d6e4138a693b770c87ab2ca723ef78f1cee089890acac00bf360d01`), summary
and output are kept on `evidence/v0100-rotation-proposal-20261028`
(`f07ed1f2`).

Hosted test workflows remain disabled. Accepting this configuration requires
the rotation PR's own PJU release-stage receipt, which downloads the public
v0.10.0 pyz again and runs the full gate with these pins with zero failures,
plus the PR's required checks. The proposal run is the basis, not a
substitute. No public tag change or downstream re-pin is part of this
rotation.

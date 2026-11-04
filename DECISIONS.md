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

Entries D-188 to D-196 moved unchanged at v0.11.0 publication to [DECISIONS-archive-4.md](DECISIONS-archive-4.md), except its prescribed archive title and single-line provenance; line references to those entries written before the move read against release commit 34555301.

## D-197 (2026-11-04): post-publication verdict baseline v0.11.0

The v0.11.0 decision-log cut and this verdict-baseline rotation change
agent-read-only files. Their basis is Nelson's answer of 2026-10-28, which
the 0.11.0 delegation section of [RELEASING](docs/RELEASING.md#v0110-release-under-the-pre-10-delegation-2026-11-03)
quotes. That session ran over Remote Control, so Claude's message at
09:04:19Z listed the choices in its text, the first as
「開始：同時確認發版後的 decision log 切檔和 baseline 輪替也照上次做。」 (start;
this also confirms that the decision-log cut and the baseline rotation after
the release are done as last time). At 09:05:05Z Nelson answered 「開始」, the
first button's label. Claude wrote that message, the button's option text
and the label, and the answer adds no words to them. Last time was #575 for
0.10.0 (D-188). Agent interpretation, as RELEASING states it: the answer
covers only changes of that bounded shape, entries moved to the archive
unchanged and a rotation that adds, retires or re-adjudicates no accepted
entry. This entry records the cut and that bounded rotation, not a new case
ruling or standing authority for another release.

The cut moves D-188 to D-196, the whole log at release commit `34555301`, to
[DECISIONS-archive-4.md](DECISIONS-archive-4.md): line 1 retitled, line 2
one provenance line, lines 3-2631 byte-identical to `DECISIONS.md` at
`34555301` and at their old numbers. No document links to an anchor in a
moved entry.

The baseline becomes public v0.11.0, version 0.11.0, release commit
`34555301de3d5ea4b2c8e4470b797a06d0a1e395` (tag object
`2f5ac3fecaddfe5f99ae6e6e129b4d73abb3dfc0`). Its Release pyz is 996040 bytes,
SHA256 `3cadde1349fd32ee05e8527601f842c19a16455ec30fae719e33556c60ed7654`:
the asset the release-event receipt built and the public-visitor stage
downloaded and verified
([publication record](docs/releases/v0.11.0-publication-verification.md)),
and the digest the GitHub Releases API reports. Under scheme S (D-194) the
recommended Action pin is the Action commit A (`25715031`), not M; the gate's
baseline is the released pyz, so it pins M.

The protected `tests/gates/verdict_gate_accepted.toml` changes only its
baseline header and comment from v0.10.0 to v0.11.0. It has no `[[accept]]`
entries; none is added, retired or re-adjudicated. Case labels, fixture
expectations and the rule that a still-passing block-labelled case needs
acceptance remain unchanged.

A PJU proposal run of the gate (LAPTOP-01AGNPJU, Windows, CPython 3.11.9,
`HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL`) used candidate `f38a2307`, the
rotation's pins commit, whose `src/` equals main `78dba277`'s, with main's
cases and labels and the public v0.11.0 pyz as its baseline engine. It ran
all 185 cases (159 T1, 26 T3): 160 block -> block, 25 pass -> pass and zero
reported, and passed with no failure, so it proposed no pin, entry or T3
change: v0.11.0 blocks the same 160 cases as v0.10.0, and
`baseline_blocked` stays 160 /
`40be07fce6801395902303cd2da797d7a4e473ef46d1b8444892d607a2dc4cd0`. The
canary's 71 block -> pass IDs are unchanged. The chai input file is the same
blob (`4f363109`) at `34555301` as at `10069979`, so the 26-case T3 map
stays, and the v0.4.2 to v0.5.0 canary is not rotated. The run's receipt
(SHA256 `98d04534a7b8641b38aaf6a08057348520b2c09a42cbe87231df5a3e63ec4bb6`),
summary and output are kept on `evidence/v0110-rotation-proposal-20261104`
(`6147195d`).

Hosted test workflows remain disabled. Accepting this configuration requires
the rotation PR's own PJU release-stage receipt, which downloads the public
v0.11.0 pyz again and runs the full gate with these pins with zero failures,
plus the PR's required checks. The proposal run is the basis, not a
substitute. No public tag change or downstream re-pin is part of this
rotation.

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

Entries D-197 to D-201 moved unchanged at v0.12.0 publication to [DECISIONS-archive-5.md](DECISIONS-archive-5.md), except its prescribed archive title and single-line provenance; line references to those entries written before the move read against tag commit 532f74ab, where the file is the same as at release merge ffaf4ed8.

## D-202 (2026-11-08): post-publication verdict baseline v0.12.0, and i198/S1 relabelled block

The v0.12.0 decision-log cut and this verdict-baseline rotation change
agent-read-only files, and a case label changes only by maintainer ruling.
Nelson's answer of 2026-10-28 covered the cut and the rotation only after
0.11.0 (the 0.12.0 delegation section of
[RELEASING](docs/RELEASING.md#v0120-release-under-the-pre-10-delegation-2026-11-07)),
so Claude asked first. After #593 merged, the next-step box Claude wrote
asked 「step 9 要照建議開始嗎？」 (start step 9 as recommended?) with the buttons
「照建議開始」 and 「先不要」, and Claude's message that followed
(2026-11-07T21:06:38Z) listed what the recommendation includes, four items,
quoted here without their bold markup:
「切檔：DECISIONS.md 裡的 D-197～D-201（71 KB）移到 `DECISIONS-archive-5.md`，指向這幾條的連結改指 archive-5。新的 DECISIONS.md 從 D-202 開始，D-202 記這次輪替。」
(the cut);
「輪替：verdict baseline 從 v0.11.0 換成 v0.12.0（commit A、pyz `4ef6eda2…`、1,013,508 B）。先跑 proposal run，預期唯一的變化是 `baseline_blocked` 從 160 變 161，多出的那個是 i198/S1。結果不一樣的話，我會停下來回報。」
(the rotation, with a proposal run first, the expected change 160 -> 161 in
`baseline_blocked` from i198/S1 alone, and a stop on any other result);
「i198/S1 標籤從 `pass` 改成 `block`：算你的維護者裁決，寫進 labels.toml 和 D-202。」
(the label change, as his maintainer ruling); and
「驗證照常：PJU 收據、4 個必要檢查、1 個子 agent 審查。合併前會再問你。」
(the usual verification, and a separate merge question). The message also
said the label and the rotation could be decided apart and that the label
would stay `pass` if he wanted only the rotation. At 2026-11-08T02:44:42Z
Nelson answered 「照建議開始」 (start as recommended), the first button's label.
Claude wrote the question, both labels and the message, and the answer adds
no words to them. Agent interpretation: the answer covers changes of the
shape the four items name, entries moved to the archive unchanged, a
rotation whose only proposed movement is i198/S1 joining the blocked set,
and that one label; any other movement would have stopped the work. This
entry records the cut, that rotation and that ruling, not standing authority
for another release or another label.

The cut moves D-197 to D-201, the whole log at tag commit `532f74ab` (the
same file as at release merge `ffaf4ed8` and at main `25823bbb`), to
[DECISIONS-archive-5.md](DECISIONS-archive-5.md): line 1 retitled, line 2
one provenance line, lines 3-1092 byte-identical to `DECISIONS.md` at
`25823bbb` and at their old numbers. Twelve links in six documents were
named after a moved entry and pointed at `DECISIONS.md`, and the v0.12.0
release guide linked its "changes D-197 to D-201" there; all thirteen now
point at the archive. No document links to an anchor in a moved entry.

The baseline becomes public v0.12.0, version 0.12.0, commit
`532f74ab070a924b23e2cc70e5d0091a05d8401d`, the tag's peeled commit and the
release's Action commit A (tag object
`6f8b8b7a95f8c6070a0c4bfb1e3ea5a9cb534fe2`). Its Release pyz is 1013508
bytes, SHA256 `4ef6eda2d4ff5b378c12874f43b825be3ce2d8ef97c2f1c5f44bfae06ee18cb2`:
the asset the release-event receipt built and the public-visitor stage
downloaded and verified
([publication record](docs/releases/v0.12.0-publication-verification.md)),
and the digest the GitHub Releases API reports. The pyz is built from the
release merge M `ffaf4ed8`; under D-200 the gate binds its members to A's
`src/checkwash` with `doctor.py`'s own Action pin line set to A, A's two pin
lines being equal. The proposal run below checked that binding: the public
pyz's 218 `checkwash/*` members equal A's with that line set, and its CLI
reports 0.12.0. Since scheme S (D-194) separated the Action pin from the
release commit, this is the first rotation in which the recommended Action
pin, the advertised commit and the baseline commit are one commit again, so
a release-stage receipt's baseline source is the pinned Action checkout
([RELEASING](docs/RELEASING.md#the-releases-own-action-pin-scheme-s-d-194)).

i198/S1 becomes `block` under the third item. Its Vitest test replaces
`toBeNull()` with chai's `.to.exist` beside a production edit. v0.11.0
passed it, taking the production edit as repair evidence for the weakening;
0.12.0 blocks it, because D-199 refuses that evidence to a JS/TS loosening.
Its `pass` label came from #198's Acceptance section ("S1, S2, S4, S5 keep
verdict pass (a warn finding is fine)"), written when #198 was registered on
2026-10-02, before D-199. With `block`, a later engine that passes the case
again needs a `known-regression` entry under the label anchor instead of an
`fp-fix` one. S2, S4 and S5 keep `pass`, and v0.12.0 passes them.

The protected `tests/gates/verdict_gate_accepted.toml` changes only its
baseline header and comment from v0.11.0 to v0.12.0. It has no `[[accept]]`
entries; none is added, retired or re-adjudicated. Fixture expectations,
every other label and the rule that a still-passing block-labelled case
needs acceptance remain unchanged.

A PJU proposal run of the gate (LAPTOP-01AGNPJU, Windows, CPython 3.11.9,
`HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL`; the gate from main `25823bbb`)
used candidate `70ff0489`, the rotation's pins commit with the new label,
whose `src/` equals main `25823bbb`'s, with its cases and labels and the
public v0.12.0 pyz as its baseline engine. It ran all 185 cases (159 T1, 26
T3) in 3 minutes 24 seconds: 161 block -> block, 24 pass -> pass and zero
reported. Of the 161, 160 are labelled `block`, i198/S1 among them, and
i197/Q5a keeps its `pass` label (D-188). Its only failure was the blocked
pin, `baseline-blocked-drift`: v0.12.0 blocks i198/S1, so `baseline_blocked`
goes from 160 / `40be07fce6801395902303cd2da797d7a4e473ef46d1b8444892d607a2dc4cd0`
to 161 / `55aed7f5f15d00352d838f49f9d21e86e1f3dffbf09452c3d16455e6dde90245`,
which adds i198/S1 and removes no case. It proposed no accept entry, engine
pin, T3 change or canary change, so the run has the shape the second item
named, and this entry pins the observed set. The canary's 71 block -> pass
IDs are unchanged. The chai input file is the same blob (`4f363109`) at
`532f74ab` as at `34555301`, so the 26-case T3 map stays, and the v0.4.2 to
v0.5.0 canary is not rotated. The run's receipt (SHA256
`72e8055a4b1a7f48c1c265268e98f3fdf08691331140b508d7f8d1bd6199b0a8`),
summary and output are kept on `evidence/v0120-rotation-proposal-20261108`
(`fc7dadc2`).

Hosted test workflows remain disabled. Accepting this configuration requires
the rotation PR's own PJU release-stage receipt, which downloads the public
v0.12.0 pyz again and runs the full gate with these pins with zero failures,
plus the PR's required checks. The proposal run is the basis, not a
substitute. No public tag change or downstream re-pin is part of this
rotation.

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
Review found five older links of the same kind that earlier cuts left: the
v0.11.0 release guide's link for D-189 to D-196, and two "Details" links
each in KNOWN-ISSUES-next and KNOWN-ISSUES-v0.9.0 for D-163 and D-164. They
now point at archive 4 and archive 2.

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
whose `src/` equals main `25823bbb`'s, with its cases and labels and, as
its baseline engine, the public v0.12.0 pyz: the copy the public-visitor
stage downloaded from the Release, whose size and SHA256 equal the pin. It
ran all 185 cases (159 T1, 26
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
(`fc7dadc2`). That receipt records the host and the four engines; the
gate's commit, the runtime, the start and end times and the exit code (1,
from the blocked-pin failure) come from the run's directory on PJU, which
was not published.

Hosted test workflows remain disabled. Accepting this configuration requires
the rotation PR's own PJU release-stage receipt, which downloads the public
v0.12.0 pyz again and runs the full gate with these pins with zero failures,
plus the PR's required checks. The proposal run is the basis, not a
substitute. No public tag change or downstream re-pin is part of this
rotation.

## D-203 (2026-11-08): toward 1.0: 0.x outreach resumes as a trial; the fifteen frozen P0/P1 issues gate 1.0; #212 is narrowed to a blind rating of 0.12's eleven JS/TS moves and closes with its caveats; #428 closes as fixed; one macOS check per release; the cohort answers are research design, not a frozen protocol; a string-chain test regains its at-limit check, not counted for now as a sixth weakening

**Approval.** Claude wrote this entry in the pull request that records it,
#597. `DECISIONS.md` and `THREATMODEL.md` are maintainer text (AGENTS.md).
Nelson's 2026-11-08 answer says that a concrete pull request's L1 and L2
follow the existing process, and that the answer does not stand in for a
final diff not yet shown. So the pull request asked him to approve, by name
and before it merges, this entry with THREATMODEL row 131 (L1) and the
"What must change before 1.0" section of `docs/stability.md` (L2).

Claude described both texts in the conversation and linked the pull
request, whose head was then `7a7cb136ec6ca8b7207cd779b84fec16e8222970`,
after main was taken in. At 2026-11-12T14:08:05Z Claude asked
「#597 的 L1／L2 核可，收據過了就用 merge commit 合併嗎？」 (approve #597's L1
and L2, and merge with a merge commit once the receipt passes?), and he
chose 「核可並合併」 (approve and merge). Claude wrote the question and both
buttons; the other was 「我先看 PR」 (let me look at the pull request first).

The answer approves the two texts as they stand at that commit. It also
approves the merge, once the pull request's PJU receipt and the four
required checks pass. This paragraph is the only change made to the entry
after it.

**Authority.**

- At 2026-11-08T12:57:56Z Nelson asked 「1.0等我的決定是什麼」 (what are the
  decisions 1.0 is waiting on from me?).
- At 13:19:00Z Claude answered, in a Claude Code session on
  LAPTOP-01AGNPJU, with seven decisions, each with options, their
  consequences and a recommendation. Claude wrote the list, the options and
  the recommendations; the message offered no buttons.
- At 13:24:11Z Nelson answered in three lines: 「重啟對外 上1.0」 (restart
  outreach; go for 1.0), 「都看過 可以照建議」 (I have read them all; follow
  the recommendations) and 「macos採用你的建議」 (for macOS, adopt your
  recommendation).
- On that answer #212's rating ran and #428 closed (items 3 and 4). At
  15:18:06Z Claude sent a second list: the rulings only he could make, the
  questions its drafts raised, with options and recommendations Claude
  wrote, and a correction of its own estimate of when 1.0 could come.
- At 15:58:03Z Nelson answered item by item in his own words, beginning
  「我看過補充評估，這輪照以下決定推進，不要記成「其餘全部照原建議」。」
  (I have read the supplementary assessment; this round goes ahead on the
  decisions below; do not record it as "everything else as originally
  recommended"). He ended
  「具體 PR 的 L1／L2、正式標註批次及 1.0 發布仍依既有流程；這份回覆不替代尚未呈現的最終 diff 或 1.0 發版核可。」
  (the concrete pull requests' L1 and L2, the formal labelling batches and
  the 1.0 release still follow the existing process; this reply does not
  stand in for a final diff not yet shown or for approval of the 1.0
  release).

Claude maintains checkwash under Nelson's 2026-10-27 delegation
(「Checkwash 一樣給你」, with 「一樣我只卡1.0發佈前 其餘你可以自主推」;
[RELEASING](docs/RELEASING.md)). 「上1.0」 directs the work toward 1.0. It
is not the explicit one-time authorization for version 1.0.0 that
AGENTS.md rule 5 requires, and the stop before 1.0 stands. Whose words:
each Chinese quote in this entry is Nelson's own, at the time given,
except those marked as Claude's recommendations and the 2026-10-26 row of
item 8, which is text he pasted. Claude wrote the recommendations, the
English glosses and everything else in this entry, under the delegation;
none of it is Nelson's personal review.

**What is decided.**

1. *0.x outreach resumes as a trial with no quantitative quality promise,
   and the 1.0 quality goals stay.* At 15:58:
   「先恢復 0.x 對外試用，正式 1.0 的品質目標保留；以下尚待修訂的研究設計，不必全部卡住不帶量化品質承諾的試用招募文。」
   (first resume 0.x outreach as a trial; the formal 1.0 quality goals
   stay; the research design below, still to be revised, need not all hold
   up a recruiting post for the trial that makes no quantitative quality
   promise). A trial result is not 1.0 acceptance evidence (item 8,
   question 1), and the outreach itself is not tracked in this repository.
   On the post he wrote
   「這輪不為現稿擴大 benchmarks 的數字准入規則。」
   (this round does not widen benchmarks' admission rule for numbers for
   the current draft), so `benchmarks/README.md`'s rule for numbers in a
   launch post stays as it is, and 「README 第一屏這次不改。」 (the README's
   first screen does not change this time). His other answers on the
   post's wording and on the threshold the outreach is to pre-register,
   which is not frozen yet, concern no file here.
2. *The fifteen frozen P0/P1 issues are a precondition for 1.0, not for
   outreach.* Claude recommended
   「不當對外的前提，改當 1.0 的前提。」
   (not a precondition for outreach; make it one for 1.0), and
   「都看過 可以照建議」 adopted it. They are the fifteen open P0/P1 issues
   read on 2026-10-18 that R1 of the 2026-10-19 ruling lists
   ([#419](https://github.com/taipei49314/checkwash/issues/419#issuecomment-6261642679)):
   #212, #414, #416, #418, #419, #421, #422, #424, #428, #429, #431, #432,
   #456, #462 and #496. On 2026-11-08 fourteen are closed, #419 as D-191's
   documented residual and #428 under item 4, and #212 closes on this
   entry (item 3). A closed issue is not a fixed cost; item 3's caveats say
   so for #212.
3. *#212 is narrowed to a blind rating of the eleven JS/TS commits that
   0.12.0 moved from pass to block, and closes with three caveats.*

   *The design.* Claude recommended
   「兩個盲評 agent 只評那 11 筆，分歧由你裁決。建議一個用 Claude 子 agent、一個用 Argon，換一個模型家族」
   (two blind rater agents rate only those eleven, and he rules where they
   disagree; one a Claude sub-agent and one Argon, another model family)
   and said
   「但這改掉了原本選的設計和範圍，Argon 也超出 11-04 定的使用範圍，要你明說。」
   (but this changes the design and scope chosen before, and Argon goes
   beyond the use set on 2026-11-04, so he must say so explicitly). His
   13:24 answer adopted it, and at 15:58 he wrote
   「同意將 POLICY 中 #212 的舊設計改為本次具名的兩位盲評、由我裁分歧；同意關閉 EC PR #226，T-602、T-603 以 `CANCELLED` 退場，保留原準備成果、失敗紀錄與歷史授權狀態。」
   (he agrees to change #212's old design in POLICY to the two blind
   raters named this time, with him settling disagreements; he agrees to
   close EC PR #226 and to retire EC T-602 and T-603 as `CANCELLED`,
   keeping their preparation, their failure records and their historical
   authorization state), and on Argon
   「Argon 用途限本次 #212 及之後具名的 cohort 標註；正式標註批次仍到時具名核可，不擴成通用模型批次授權。」
   (Argon's use is limited to this #212 rating and to cohort labelling
   named later; a formal labelling batch is still approved by name when it
   comes, and this is no general authorization for model batches). This
   replaces the design chosen on 2026-10-19 (R21, R30): two raters over the
   55 commits that the report-only counterfactual cf-js131 moved, as
   independent agents on the estate's pool with arbitration
   ([testing on PJU](docs/testing-on-pju.md)). The estate recorded the
   change the same day: EC POLICY commit `227236bc` (EC T-646) adds the row
   `checkwash-212-blind-raters-20261108`, which replaces only the #212
   sentence of `checkwash-pju-tests`; EC T-602 and T-603 were retired as
   `CANCELLED`, and EC PR #226 was closed.

   *The eleven* are the JS/TS commits of #212's fixed 1,800 that 0.12.0
   blocks and v0.11.0 passed
   ([RELEASING](docs/RELEASING.md#v0120-release-under-the-pre-10-delegation-2026-11-07);
   THREATMODEL row 131): hono `5463db27`, `c831020f` and `f0b094db`;
   typeorm `324c46cd`, `46d5b843`, `b9aa8355`, `c6745f3d`, `df09802e` and
   `ff00a3cd`; undici `2764d996`; and vue-core `8b44b021`. All eleven are
   among cf-js131's 55 (its frozen case manifest, checkwash-lab
   `cee6b8b7`); the other 44 are not rated.

   *Fixed before the rating.* Commit `cac11989` of the private
   checkwash-lab repository (branch `evidence/cw212-rating-20261108`,
   2026-11-08T13:37:59Z) holds the packet, which Claude assembled from
   upstream diffs and messages, and the rubric, which Claude wrote. The
   packet has each commit's diff against its first parent and its verbatim
   message, read from the GitHub API, with a trimmed copy of undici
   `2764d996`'s diff to read first, and no checkwash output.
   The rubric asks whether the commit reduces what its tests verify (Q1)
   and whether a deliberate change in the same commit, visible in its
   production diff or its message, explains each reduction (Q2), and it
   derives the verdict: `PASS_EXPECTED` when nothing is reduced or every
   reduction is explained, `BLOCK_EXPECTED` when one is not, `UNCLEAR`
   otherwise; `honest_but_weaker` marks a commit whose every reduction is
   explained though its tests check less. It names the raters, a Claude
   Code sub-agent (Claude Opus 5.5) and Gemini 4 Argon (High) through the
   Antigravity CLI, neither of whom sees the other's labels or any
   checkwash output; an agreed verdict stands, and a disagreement goes to
   Nelson. It says that the eleven are not a random sample, so a count over
   them is not a rate, and that no count changes checkwash by itself: any
   change it suggests is a separate decision for Nelson. It registers no
   decision line. R30's line was registered for cf-js131's 55 and is not
   applied to the eleven, and none is added after the fact. After rater A
   was dispatched (13:38:40Z) and the runner's secret scan refused Argon's
   first attempt, `5175d6a6` (13:39:07Z) changed only Argon's
   `request.md`, which rater A was not given, to record why the run allows
   two secret-scan hits, base64 WebAssembly modules in undici's vendored
   parser files; this was before the Argon run (13:39:14Z).

   *After the fact.* The ratings ran on the 13:24 answer. The explicit word
   that Claude's recommendation asked for, on the changed design and on
   Argon, came at 15:58, after both ratings had run, so EC POLICY's row is
   an after-the-fact record of the design, not a pre-registration. While
   the ratings ran, EC POLICY `checkwash-pju-tests` still named the pool
   design. Both
   raters ran on LAPTOP-01AGNPJU (`HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL`;
   receipt `c90708e4`). Rater A was dispatched at 13:38:40Z, and the Argon
   run (agy 1.5.3, exit 0, 30 file reads, none denied) ran from 13:39:14Z to
   13:53:43Z. Both ratings, the run's receipts and the comparison were saved
   at `c61702b9` (14:00:25Z); the comparison says that its column of
   checkwash's findings was added only after both ratings were saved. The
   verdicts agreed on ten, all `PASS_EXPECTED`. On vue-core `8b44b021`
   rater A gave `UNCLEAR` and rater B `BLOCK_EXPECTED`, and on typeorm
   `ff00a3cd` they differed only in `honest_but_weaker`. Nelson ruled both
   at 15:58:
   「第 11 筆 Vue：判 `UNCLEAR`。 斷言確實放寬，但已有 transitionstart 時序註解及依賴更新。缺少這次升級與測試修改的因果證據，不等於已證實沒有正當理由。保留原盲評；之後補證據時另記補充判讀。」
   (commit 11, Vue: `UNCLEAR`; the assertion was loosened, but there are a
   comment on transitionstart timing and a dependency update; lacking
   causal evidence that links this upgrade and the test change is not
   proof that there was no good reason; the blind ratings stay, and
   evidence found later is recorded as a separate supplementary reading)
   and
   「第 9 筆 TypeORM：維持 `PASS_EXPECTED`，`honest_but_weaker=true`。 按這份 rubric 的歷史覆蓋口徑，被移除 API 的行為確實不再受測，但同 commit 移除 API，理由正當。這不代表現存 API 的測試品質退步。」
   (commit 9, TypeORM: `PASS_EXPECTED` stays, with `honest_but_weaker`
   true; by this rubric's reading of historical coverage, the removed API's
   behaviour is no longer tested, but the same commit removes the API,
   which is a good reason; it does not mean the tests of the APIs that
   remain got weaker). `arbitration.md` at `e1f7119a` records the rulings
   (its sentence on cf-js131's 55 corrected at `445f6225`) and the result: `PASS_EXPECTED` 10, `BLOCK_EXPECTED` 0, `UNCLEAR` 1;
   `honest_but_weaker` 7 (hono `c831020f` and `f0b094db`, typeorm
   `324c46cd`, `46d5b843`, `c6745f3d` and `ff00a3cd`, undici `2764d996`).
   For hono `5463db27` and typeorm `b9aa8355` and `df09802e` both raters
   found no reduction at all, while 0.12.0 raised high `ASSERT_WEAKENED`
   findings on them; whether those findings misread the tests is not ruled
   here. The result is on
   [#212](https://github.com/taipei49314/checkwash/issues/212#issuecomment-6723728427),
   with its execution receipt in the
   [next comment](https://github.com/taipei49314/checkwash/issues/212#issuecomment-6724069716).

   *Closing, also after the fact.* At 15:58:
   「#212 可以在結果、範圍變更及殘餘完成記錄後關閉，但要明寫：」
   (#212 may close once the result, the change of scope and the residual
   are recorded, but it must say plainly:)
   「這是選定的 11 筆，不是一般誤擋率。」
   (these are 11 selected commits, not a general false-block rate),
   「其中 10 筆兩位均判應放行，實際卻新增阻擋；即使部分屬產品刻意攔下的誠實變弱，仍是使用者的審查／豁免成本。」
   (both raters judged 10 of them as commits that should pass, yet they are
   newly blocked; even where some are honest weakenings the product stops
   on purpose, each is a review or exemption cost to users) and
   「關閉 issue 不代表這項成本已修好，也不代表原本 55 筆全部完成評審。」
   (closing the issue does not mean this cost is fixed, nor that all of the
   original 55 were reviewed). This entry, STATE, the #212 row of
   KNOWN-ISSUES-next, THREATMODEL row 131 and the JS/TS replay's selection
   record carry the result, the change of scope and the residual with
   those caveats. #212 closes after this pull request merges, and its
   closing comment repeats them. Recording the residual is not its
   acceptance for 1.0, which item 6 leaves to the residual register. The
   rubric also says the result is recorded in that register; the register
   is Claude's draft outside this repository, not changed by this entry,
   and #212's result goes into it before the 1.0 candidate.
4. *#428 closes as fixed.* Its fix shipped in v0.9.0. Claude recommended
   「算已修：v0.9.0 的合併 sweep 有 4,818 列，沒有任何判決改變。剩下的量測移進 #504（1.0 之後），關掉 #428」
   (treat it as fixed: v0.9.0's combined sweep has 4,818 rows and no
   verdict changed; move the remaining measurements to #504, after 1.0,
   and close #428), and 「都看過 可以照建議」 adopted it. #428 closed as
   completed at 2026-11-08T13:29:26Z, with this decision in its
   [closing comment](https://github.com/taipei49314/checkwash/issues/428#issuecomment-6722098644),
   and [#504](https://github.com/taipei49314/checkwash/issues/504)'s body
   lists the measurements #428 kept open as not scheduled before 1.0:
   D-152's targeted selection over the 13 in-sample JS histories (S1) with
   its engine replay (S2), and the review of E1's Jest, Vitest and Bun
   empty-table observations. No new scan runs: the estate's prepared scan,
   EC T-602, is retired (item 3). The residuals stay where they are stated:
   `describe.each` rows in THREATMODEL rows 108 and 157, the rest in
   KNOWN-ISSUES.
5. *One macOS verification per release; its workflow comes in its own
   pull request.* Claude recommended
   「改 POLICY，每次發版對 M 跑一次 GitHub 代管的 macOS」
   (change the policy so that each release runs GitHub-hosted macOS once
   against M), with a one-time try of the Claude Code hooks on a real Mac
   that Nelson borrows, and
   「D-170 的那兩個測試一起決定」
   (decide D-170's two tests together), and 「macos採用你的建議」 adopted
   it. At 15:58 he set its scope:
   「同意每版一次 macOS 驗證，也同意對 v0.12.0 補跑一次；先把設計及 workflow 補完整：」
   (one macOS verification per release, and one catch-up run for v0.12.0;
   complete the design and the workflow first:)
   「除完整測試和語料比對，須驗實際將發布／已發布的 wheel、pyz，記錄 SHA256。」
   (besides the full tests and the corpus comparison, verify the wheel and
   the pyz actually to be published or already published, and record their
   SHA256),
   「v0.12.0 優先用原已發布成品。同一個 M 重建，若未證明 bytes 相同，只能稱重建成品驗證。」
   (for v0.12.0, prefer the artifacts already published; a rebuild from the
   same M is only a verification of rebuilt artifacts unless its bytes are
   shown to be the same),
   「明定產品測試失敗與 `NOT_RUN` 如何影響發版。「不是 branch required status」不表示可以忽略失敗。」
   (state how a product test failure and `NOT_RUN` affect a release; not
   being a branch's required status does not mean that a failure can be
   ignored),
   「D-170 選 A，保留兩個效能預算的 skip，清楚揭露 Mac 這兩項未驗；Windows／Linux 結果不當成 Mac 效能證明。」
   (D-170: option A; the two performance budgets stay skipped, with a plain
   disclosure that these two are not verified on a Mac; Windows and Linux
   results are not evidence of Mac performance),
   「POLICY、CLAUDE.md 及相關規則同步實際採用的範圍。」
   (EC POLICY, CLAUDE.md and the related rules follow the scope actually
   adopted) and
   「借 Mac 手測 hook 仍作一次性觀察記錄，不替代正式成品驗證。」
   (testing the hooks by hand on a borrowed Mac stays a one-time
   observation and does not replace the formal verification of the
   artifacts). So the two budget checks of `tests/gates/test_perf.py` stay
   skipped on macOS at 1.0: D-170 kept them skipped "until they are
   revisited before 1.0", this is that revisit, and the file does not
   change. The workflow, what it runs, how its result enters a release's
   record and how a failure or `NOT_RUN` affects the release come with the
   pull request that adds it, together with the documents that describe
   the two skips. Until EC POLICY `checkwash-pju-tests`
   ([testing on PJU](docs/testing-on-pju.md)), which keeps checkwash's
   tests on LAPTOP-01AGNPJU with no hosted fallback, allows the run, macOS
   stays NOT_RUN, as for v0.10.0 to v0.12.0; changing that policy is the
   estate's step. The hook test on a borrowed Mac is recorded as a one-time
   observation, not as release evidence. This entry adds no workflow.
6. *1.0's residuals are accepted item by item at the 1.0 candidate.*
   Claude recommended
   「我整理成一頁「1.0 殘餘清單」，你看完核可一次」
   (Claude compiles a one-page "1.0 residual list", and he approves it once
   after reading it), and 「都看過 可以照建議」 adopted it. At 15:58 he set
   when and how:
   「04 殘餘清單留到候選版時再核可，不能用 Closed／Partly closed 的總數代替逐項風險接受。」
   (the residual list, Claude's draft numbered 04, waits for approval until
   the candidate, and a total of Closed or Partly closed rows cannot stand
   in for accepting each risk item by item). The register is not in this
   repository, and this entry approves none of it. Each delegated
   acceptance so far excludes 1.0: each D-176 disposition "does not
   authorize 1.0".
7. *1.x keeps the fingerprint rule.* Claude recommended
   「1.x 照 0.x 的規則 → 偵測器可以照常修，但升 minor 時，使用者的豁免可能失效。」
   (1.x keeps 0.x's rule: detectors can be fixed as usual, but on a minor
   upgrade users' exemptions may stop matching) and
   「分類欄位等真的有嵌入者再做。」
   (the classification field waits until there really is an embedder), and
   「都看過 可以照建議」 adopted both. So in 1.x, as now, a minor release
   may move fingerprints in any namespace, its decision entry and release
   notes naming the rules and shapes that move, and within one minor line a
   recorded exemption keeps matching
   ([stability](docs/stability.md#fingerprint-stability)). The optional
   classification field, proposed in a text Nelson pasted on 2026-10-26,
   waits for an embedder who needs it.
8. *The adoption floor and the study design are research-design
   decisions, not a frozen protocol.* At 15:58 he answered the nine cohort
   questions of Claude's second list; Claude wrote the questions, their
   options and the recommendations. His answers, with Claude's glosses:
   1. 「第 1 題：同意分兩段。 先做 0.x 試用；固定候選版後另開正式輪，試用結果不冒充正式驗收。」
      (two stages: a 0.x trial first, then, once a candidate is fixed, a
      formal round of its own; trial results do not pass for formal
      acceptance)
   2. 「第 2 題：同意。 採用者主動加入、同意資料用途，我對該倉沒有寫入權；招募時說清楚資料、模型處理與計時負擔。」
      (adopters join on their own initiative and agree to the use of their
      data, and he has no write access to their repositories; recruiting
      states plainly the data, the model processing and the timing burden)
   3. 「第 3 題：修改後採用。 被拿去修工具的倉仍保留在採用及健康紀錄，分暴露／未暴露層呈現，不能把出問題的倉剔除後只報順利者。是否能計入 A 的新證據，先解決 SPEC §10／G15；改叫 `new evidence (PR-unit)` 不會自行取得資格。」
      (adopted with a change: a repository whose reports are used to fix
      the tool stays in the adoption and health records, shown in exposed
      and unexposed strata, and the repositories with problems cannot be
      dropped to report only the smooth ones; whether such a repository
      counts as new evidence for A waits until SPEC §10 and the draft
      specification's G15 are resolved, and calling it
      `new evidence (PR-unit)` does not qualify it by itself)
   4. 「第 4 題：20 可作活躍度下限。 不把它說成與舊每倉 100 等價，也不只憑較晚交接筆記自動覆蓋舊批准。正式 1.0 採用門檻隨整套方案定稿；若取代舊決定，明記取代範圍。「人類按合併」也不自動等於實質審查。」
      (20 can serve as an activity floor; it is not to be called equivalent
      to the old 100 per repository, and a later handover note does not by
      itself override the old approval; the formal 1.0 adoption threshold
      is settled with the whole design, and if it replaces an old decision
      it states what it replaces; a human pressing merge is not by itself a
      substantive review)
   5. 「第 5 題：先修改。 使用者關閉或撤回 PR 要另列為放棄，不能直接算誤擋成功解除；最終 100% 跑完不能取代完成時限。事件少可以不設不穩定的 p95 門檻，但仍保留逐筆等待、最大成本與放棄紀錄。」
      (revise first: a pull request its user closes or withdraws is listed
      apart as abandoned, not counted as a false block resolved; completing
      100% in the end does not replace a time limit for completing; with
      few events an unstable p95 threshold may be left out, but each wait,
      the largest cost and the abandonments are still recorded)
   6. 「第 6 題：暫不鎖定 100 筆／180 天。 先從試用確認正常重構流量和記錄負擔，再定正式數量、期限及追蹤結束條件。」
      (100 pull requests and 180 days are not locked yet; the trial first
      shows the flow of normal refactors and the recording burden, and then
      the formal count, the deadline and the end of tracking are set)
   7. 「第 7 題：同意雙模型初標的設計，但補人類盲抽一致案例。 不能只裁分歧而完全不查共同偏誤。Argon 用途限本次 #212 及之後具名的 cohort 標註；正式標註批次仍到時具名核可，不擴成通用模型批次授權。」
      (two models label first, and a human also samples, blind, cases where
      they agree; settling only the disagreements without checking for a
      shared bias is not enough; Argon's limits as in item 3)
   8. 「第 8 題：同意 PJU 標準化重跑。 同時保留實際採用中的首次結果、延遲與人工成本，不能用重跑結果替代真實困擾。」
      (a standardized rerun on PJU, keeping the first results, the delays
      and the human cost seen in actual adoption; a rerun's result cannot
      replace the trouble users really met)
   9. 「第 9 題：與第 6 題一起重整。 2% 可以是觀察樣本的驗收尺，不能宣稱證明母體誤擋率不超過 2%；最低 100 筆先不要獨立定死。」
      (reworked with question 6: 2% can be the acceptance ruler for the
      observed sample, but cannot be claimed to prove that the population's
      false-block rate is at most 2%; a minimum of 100 is not to be fixed
      on its own yet)

   He also corrected Claude's 15:18 message:
   「請修正「工時改只揭露就能加快」的說明：A 的 cohort 層若仍要求 100 筆，取消 B 工時門檻也不會解除等待。 8～33 個月只是依假設推算，不是實測預測。本輪不藉此自動取消既有品質目標。」
   (correct the statement that making the time measure disclosure-only
   would make things faster: if A's cohort layer still requires 100,
   cancelling B's time threshold does not end the wait; 8 to 33 months is
   only an extrapolation from assumptions, not a measured prediction; this
   round does not use it to cancel the existing quality goals). Claude's
   message had said that 1.0 waits for at least 100 normal refactor pull
   requests from the natural cohort on the 1.0 candidate, that with only
   minimal traffic this would take 8 to 33 months, from a share of normal
   refactors that was assumed, not measured, and that making the time
   measure disclosure-only would shorten the wait.

   A and B are the first two measures of the refactor-cost row of a
   proposal that Nelson pasted on 2026-10-26 at 08:10:02Z, under his words
   「這邊一樣 先討論」 (same here, discuss first); it was drafted outside that
   Claude session, which does not record by whom. The row reads
   「以 1.0 候選版的確切 SHA，依指定版本的計算協定驗證：新證據上的 unnecessary merge-block rate on normal refactors ≤2%；自然採用中的實測人工成本平均 ≤30 秒／合格 PR；完整揭露固定 60 案的歷史回歸結果。樣本不足或關鍵結果缺測不得記為通過。」
   (verified on the exact SHA of the 1.0 candidate under a pinned version
   of the measurement protocol: on new evidence, an unnecessary
   merge-block rate on normal refactors of at most 2%; in natural
   adoption, measured human handling cost averaging at most 30 seconds per
   qualifying PR; full disclosure of the fixed 60 cases' historical
   regression results; insufficient samples or missing key results are not
   a pass). At 08:12:15Z he answered Claude's four questions on it, ending
   「可以開完整規格了」 (go ahead with the full specification). Claude's draft
   protocol of that day names the first measure A and the second B; it is
   not in this repository and is not frozen. Claude reads this row as the
   quality goals that item 1 keeps; question 9 sets how its 2% is read.

   The old 100 of question 4 is the estate's record EC T-157 (D1): three
   repositories, 30 consecutive days each and at least 100 reviewed
   changes each, with health thresholds (D3), drafted by Codex on
   2026-09-06 and recorded as approved on 2026-09-07 by a Claude session
   on LAPTOP-16NUA5I8 on Nelson's 「6條都幫我搞定 授權」 (get all six done
   for me; authorized). The 20 is the figure of stability's adoption-study
   proposal. On 2026-10-14 Claude asked whether the adoption study's
   thresholds pass as proposed, Nelson answered
   「照建議，先修 #414 和 #415」 (as recommended; fix #414 and #415 first),
   and Claude's handover notes of 2026-10-15 recorded the 20 as his
   threshold. Neither figure was ever in this repository as an adopted
   threshold. Stability's 1.0 section now says that 20 is an activity floor
   only and points here.

   None of these answers is a frozen protocol: no sample size, duration,
   stopping rule or threshold is fixed in this repository, and nothing is
   measured against the goals until a protocol is frozen here. A formal
   labelling batch is approved by name when it comes (question 7).
9. *A string-chain test regains its at-limit check, and replay item 392
   is not counted, for now, as a sixth unexplained weakening.* At 15:58:
   「同意補回 forced-fallback 路徑在剛好達到 node limit 時仍成功的驗證，保留新版 path／side 及錯誤訊息檢查，不要整段回退。」
   (put back the check that the forced-fallback path still succeeds when
   the node count is exactly at the limit, keep the newer path, side and
   error-message checks, and do not revert the whole block) and
   「但先不要把它算成第六筆無理由弱化。packet 截掉了重要任務內容，完整紀錄有恢復 #391 測試的脈絡。保留 packet-only 標籤與完整脈絡判讀的區別；補測試不自動等於確認「完全沒有理由」。」
   (but do not count it yet as a sixth weakening without a reason: the
   packet cut important task content, and the full record shows the
   context of restoring #391's tests; keep the packet-only label apart
   from the full-context reading; putting the test back does not by itself
   confirm that there was no reason at all).

   Replay item 392 of the 2026-10-28 session replay (D-189's *Why*; D-195
   names its repository) is an agent edit of 2026-10-14T03:08:38Z to
   `test_subject_counts_the_complete_reconstructed_tree` in
   `tests/test_string_chain_syntax.py`. Reading only its packet, both of
   Claude's labelling passes called it a loosening with no reason in its
   context. The packet clips the sub-agent's task text, which the parent
   Claude session's workflow computed. The full transcript shows that task:
   rebuild the closed draft #391 on #439, taking "#391's five new test
   files" and restoring "#391's side=/path= keywords and #389-style message
   expectations where the earlier port had rewritten them for main". The
   edit replaced the earlier port's form of this test, from a local commit
   `207b9ad6` (2026-10-14T10:43:22+08:00) that was never pushed, which
   anchored main's old refusal message and, beyond #391, also checked that
   the fallback's tree is read at exactly the limit, with #391's own test:
   the function main has had since `37d59b7c` (merged with #441) is the
   one at #391's head `e63ba5b5`, line for line. The at-limit check was
   never in #391 or on main.

   The test now checks again, after the over-limit refusal with its path,
   side and count, that with the limit set to the node count `_syntax`
   reads the forced fallback's complete tree, called with the same path
   and side keywords, and that the first parse failed and the fallback
   parsed again. Other tests read a tree at exactly the limit only through
   a native parse:
   `tests/test_standin_source_limits.py::test_real_trees_at_and_below_the_ruled_limit_are_readable`
   for this pass and
   `tests/test_issue469_limit_messages.py::test_trees_up_to_the_shared_limit_are_read`
   for the subject-replacement pass; on the fallback path the count was
   pinned only through the refusal's message. No test is added, so the
   documented test count does not move. The replay's labels are not
   changed, and this entry does not rule on the edit's reason.

**Not changed.** No `src/`, SPEC, `tests/gates`, fixture, label, workflow
or `benchmarks/README.md` change. THREATMODEL changes only row 131's
verdict sentence on JS/TS adjudication and its prose on the eleven. Row
157 still names D-152's sweep for the new blocks on honest table edits,
whose measurements are now listed on #504 (item 4); whether that row
changes is Nelson's to decide. Row 2 still says that none of D-199's
eleven JS/TS moves is adjudicated; on 2026-11-07 Nelson kept row 2 and
item 4 as they were (「先不要改」), so it is unchanged here, and whether it
now changes is his to decide. `docs/testing-on-pju.md` changes only its
restatement of EC POLICY's sentence on #212's raters, to follow the
estate's POLICY commit (item 3). RELEASING's stop before 1.0 and its
fixed-corpus step, and AGENTS.md, are unchanged. No cohort protocol, sample size, duration
or threshold is frozen, and stability's table carries none of the
2026-10-26 numbers. The residual register (item 6) is not approved.

**Maintainer text.** This entry and THREATMODEL row 131 (L1). The pull
request also changes STATE, stability's 1.0 section (L2), two
KNOWN-ISSUES-next rows, one sentence of `docs/testing-on-pju.md`, one dated
note in the JS/TS replay's selection record and one test in
`tests/test_string_chain_syntax.py`; none of them is agent-read-only.

**What runs before merge.** On LAPTOP-01AGNPJU
(`HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL`): `tests/test_string_chain_syntax.py`,
`tests/test_standin_source_limits.py`, `tests/test_docs_links.py`,
`tests/test_documentation_contracts.py`, `tests/test_state_claims.py` (the
failures ledger included), `tests/test_threatmodel_pinned.py` and
`tests/test_packaging.py`'s documented count; in a scratch copy, the
restored check under the mutation `nodes >= _MAX_SOURCE_NODES` in
`_syntax`, which by reading fails it while the refusal check beside it
still passes; checkwash's own check on the pull request's range at
`--fail-on high`; and the pull request's PJU receipt, whose intake sets the
four required checks. Other platforms: NOT_RUN.

## D-204 (2026-11-11): one hosted verification per release, on GitHub-hosted macOS and Linux, in two checkpoints; the macOS skip of the two budget checks kept at 1.0

**Approval.** Claude wrote this entry in the pull request that implements
it, #599. `DECISIONS.md` is maintainer text (AGENTS.md), and Nelson's
2026-11-08 answer says that a concrete pull request's L1 and L2 follow the
existing process, so the pull request asked him to approve this entry (L1)
with the Determinism row of `docs/stability.md` (L2). Claude sent him both
texts as they stood at `30b83d075d7ebaf0257d9833e409bf9e2d6c6ffe`, and at
2026-11-11T13:58:22Z, to Claude's question
「D-204（L1）和 stability 的 Determinism 列（L2）照 PR 的文字核可嗎？」 (approve
D-204 (L1) and stability's Determinism row (L2) as the pull request words
them?), he chose 「核可 L1 和 L2」 (approve L1 and L2). Claude wrote the
question and both buttons; the other was 「我先看文字」 (let me read the text
first). The answer approves the two texts, not the merge. This paragraph is
the only change made to the entry after it.

**What was asked.** On 2026-11-08 Claude listed the decisions checkwash 1.0
waits for, with options and a recommendation for each; Claude wrote the
list, the options and the recommendations. Item 4, on macOS, offered as
option A 「改 POLICY，每次發版對 M 跑一次 GitHub 代管的 macOS」 (change POLICY
so that each release runs one GitHub-hosted macOS check against M) and
recommended 「A，再加上發文前借一台真的 Mac，測一次 Claude Code hook（跟今天給你的建議一樣）。D-170 的那兩個測試一起決定。」
(A, and before the post borrow a real Mac to test the Claude Code hooks
once; decide D-170's two tests with it). At 13:24:11Z Nelson answered,
among two other lines, 「macos採用你的建議」 (for macOS, adopt your
recommendation). At 15:58:03Z he wrote of macOS:

> 同意每版一次 macOS 驗證，也同意對 v0.12.0 補跑一次；先把設計及 workflow 補完整：
>
> * 除完整測試和語料比對，須驗實際將發布／已發布的 wheel、pyz，記錄 SHA256。
> * v0.12.0 優先用原已發布成品。同一個 M 重建，若未證明 bytes 相同，只能稱重建成品驗證。
> * 明定產品測試失敗與 `NOT_RUN` 如何影響發版。「不是 branch required status」不表示可以忽略失敗。
> * D-170 選 A，保留兩個效能預算的 skip，清楚揭露 Mac 這兩項未驗；Windows／Linux 結果不當成 Mac 效能證明。
> * POLICY、CLAUDE.md 及相關規則同步實際採用的範圍。
> * 借 Mac 手測 hook 仍作一次性觀察記錄，不替代正式成品驗證。

(Claude's translation: agreed to one macOS verification per release, and to
one run for v0.12.0; complete the design and the workflow first. Besides the
full tests and the corpus comparison, verify the wheel and pyz that will be
or have been published, recording their SHA256. For v0.12.0 prefer the
files originally published; a rebuild from the same M whose bytes are not
proven equal may only be called a rebuilt-artifact verification. State how
a product test failure and `NOT_RUN` affect a release; "not a branch
required status" does not mean a failure may be ignored. D-170: option A,
keep the two performance-budget skips and disclose clearly that these two
are not verified on a Mac; Windows and Linux results are not taken as Mac
performance evidence. Bring POLICY, CLAUDE.md and the related rules in line
with the scope actually adopted. The hand test of the hooks on a borrowed
Mac stays a one-time observation and does not replace the formal
verification of the published files.)

On 2026-11-10 Nelson asked for a fresh review of the project
(「從新審一次checkwash」). Its plan, which Claude wrote, asked whether the
hosted verification should cover macOS only or Linux too, and offered as
D-甲 「同一個新 workflow，每版一次，跑 macOS 和 Linux 兩條，Linux 那條順便用真的 Action 跑一次 README 的設定。」
(one new workflow, once per release, running macOS and Linux, the Linux
side also running the real Action once with the README's setup). On
2026-11-11 he answered the plan's table of direction questions with six
lines, one of them 「G3 D」. Claude asked 「G3 的「D」是指 D-甲（每版一次，macOS 和 Linux 都跑）嗎？」
with the buttons 「是，D-甲」 and 「D-乙，只補 macOS」, and he answered
「是，D-甲」 (02:51:04Z). To 「要我現在把 macOS 設計稿改寫成含 Linux 的版本嗎？」
(shall I rewrite the macOS design to include Linux now?) he answered
「開始改設計」 (start rewriting the design). Claude rewrote the design, had
one sub-agent review it, and put nine questions with a recommendation for
each. To 「02c 第 11 節除 POLICY 列以外的八題，都照建議嗎？」 (the eight
questions of section 11 other than the POLICY row: all as recommended?),
with the buttons 「都照建議」 and 「我逐題答」, he answered 「都照建議」
(11:38:11Z). To 「POLICY 列照 02c 第 8.1 節入帳，然後照順序開始做嗎？」 (enter
the POLICY row as in section 8.1 of 02c, then start in order?), with the
buttons 「照這樣入帳並開始」 and 「我先看列的文字」, he answered
「照這樣入帳並開始」 (enter it like this and start; 11:46:59Z). A review
before the row was entered found two statements in it wrong: the date of
Claude's options and the sentence on the job's token. Claude asked
「POLICY 列要照這兩處更正後再入帳嗎？」 with the buttons 「照兩處更正入帳」 and
「照原文入帳」, and he answered 「照兩處更正入帳」 (enter it with the two
corrections; 12:23:16Z). The row was entered with both corrections, at EC
commit `a46c91f68cc5daf0c30ce809afc5f6b5f8519c7f`. Claude wrote every
question and button. The nine questions and the recommendations are in the
evidence of EC T-647,
`evidence/requests/baeb05f5-7bb3-4682-8d7b-e5d33c56eb4e/checkwash-hosted-policy-authority.md`.

**Decision.**

1. *One verification, two checkpoints, two systems (question 1).*
   `.github/workflows/release-hosted.yml`, dispatched only, from main, on
   LAPTOP-01AGNPJU, and holding `contents: read` only, verifies each release
   once on GitHub-hosted `macos-latest` and `ubuntu-latest` with Python 3.11
   to 3.13, in two checkpoints dispatched separately. `source-at-M` runs once
   M is on main and before the tag: the whole suite, the source
   assertion-contract qualification and the fixed corpus at M on six legs,
   and the composite Action at A once on `ubuntu-latest` with Python 3.12 on
   M's release range. `published-artifacts` runs once `publish-assets` has
   attached the Release's files and before Nelson is asked to approve the
   `pypi` deployment: the published wheel, sdist and pyz are checked against
   the release record and downloaded on six legs, the wheel installed and
   run, the pyz run, both qualified, and all three inventoried against M;
   the sdist is not installed. One `both` dispatch is only for a version
   published before the workflow existed. The workflow rebuilds none of the
   published files; the Action builds its own engine from A, as it does for
   any user. EC POLICY `checkwash-release-hosted-verification-20261111` (EC
   T-647) allows the hosted runs;
   [RELEASING, "Hosted release verification"](docs/RELEASING.md#hosted-release-verification)
   has the checks.
2. *A failure stops the release, and is reported to Nelson.* No tag after a
   failed `source-at-M`. After a failed `published-artifacts`: no request
   for the PyPI approval, no step-8 pin promotion, the notice below in the
   Release notes, the fix in a new version, and the tag and the Release left
   as they are (not moved, deleted or marked prerelease; their files not
   deleted or replaced). A failure includes a timing test that fails on a
   hosted runner, and Claude reports the measured seconds (question 7); on
   Linux the two perf-gate budget checks must run and pass, and on macOS
   they must be skipped for their recorded reason. When the release has a
   PJU six-leg batch, a Linux leg whose test-case count differs from the
   batch's for the same tree is a failure too; Claude checks that from the
   legs' summaries. No run is repeated to obtain a pass. Only a runner,
   GitHub or PyPI service failure, including a cancellation by GitHub that
   neither a timeout nor a person caused, allows one rerun of the whole run.
   A run that refuses its own dispatch before any test (a malformed input, a
   dispatch from another branch, or one before `publish-assets` attached the
   files) is recorded and dispatched again. An unavailable hosted runner
   leaves its legs `NOT_RUN`; no self-hosted, larger or paid runner stands
   in. Nelson may decide another remedy than these.
3. *The notice (question 2).* Question 2 proposed the macOS design's
   notice with a new heading and the rest unchanged, and Nelson agreed.
   Claude then also changed the second sentence, which said "the hosted
   macOS verification", to name the system, to match the heading; that
   change is part of what approving this entry approves. The notice reads:

   > **Hosted verification failed for this release (〔macOS／Linux〕).** Its
   > published files failed the hosted verification on 〔macOS／Linux〕 (run
   > 〔id〕, 〔date〕): 〔one line〕. This version was not published to PyPI
   > and is not the version the README recommends; the fix ships as
   > v〔next〕. Details: 〔link to the RELEASING paragraph〕.

   Editing a published Release is still asked of Nelson at the time, in one
   line; the wording is not reviewed again.
4. *`NOT_RUN` (question 3).* A checkpoint that was not dispatched, or any
   of whose legs did not complete after the one allowed rerun, holds the
   release until Nelson accepts that checkpoint's `NOT_RUN` for that
   version in his own words, naming the system that did not run. The
   pre-1.0 delegation does not cover that acceptance.
5. *The Action (question 8).* It runs from a checkout of A by a local path,
   because a `uses:` value must be a literal and cannot take an expression;
   that checkout sits in the subject's workspace, and the engine judges
   allowlist expiry as on M's commit date. GitHub's resolution of
   `taipei49314/checkwash/action@<A>`, the pull-request trigger and the
   Action blocking a change stay `NOT_RUN`. No extra dispatch that runs the
   README's pin verbatim, and no blocking case, are added.
6. *v0.12.0 (question 9).* One `both` run, Linux and the Action included,
   on M `ffaf4ed86ecc2baeb8cc008487a44d8495da9177` and on the files GitHub
   Release 437647350 and PyPI 0.12.0 serve, after this merges and before
   the outreach post, recorded as supplementary evidence after publication.
   His 2026-11-08 「同意每版一次 macOS 驗證，也同意對 v0.12.0 補跑一次」 named
   macOS; the wider run is what he took with 「都照建議」.
7. *The macOS skip of the two budget checks, option A, done as A1
   (question 4).* The two budget checks of `tests/gates/test_perf.py` have
   been skipped on macOS since a maintainer decision of 2026-10-01; D-170
   kept that skip until a revisit before 1.0. This is that revisit: the
   skip stays at 1.0, and the file does not change. The release records,
   KNOWN-ISSUES and `docs/enterprise.md` say that these two budgets are not
   verified on a Mac and that Windows and Linux timings are not evidence of
   macOS performance. On Linux they run and gate.
8. *Determinism coverage (question 5).* `docs/stability.md`'s Determinism
   row says what this verification adds, and that the one-run nine-leg
   comparison stays unexecuted.
9. *The hooks on a borrowed Mac.* Nelson's own try is a one-time
   observation, recorded as his; it is not release evidence and replaces
   neither checkpoint.

Claude's design, which the POLICY row names as Claude's: holding two
checkpoints as one verification, not rebuilding the published files, and
applying the published-file checks and the consequences of a failure or
`NOT_RUN` to Linux too. Nelson's 2026-11-08 words name macOS. Question 6
asked him to confirm these three, and he answered it with
「照這樣入帳並開始」; 「都照建議」 had answered the other eight questions.

**Not changed.** Each pull request's tests still run on PJU (EC POLICY
`checkwash-pju-tests`); hosted Windows does not run; `release.yml`; the
release bridge and its missing-platform list, since the receipts still hold
no Linux or macOS leg; the required checks; the disabled hosted test
workflows (`ci.yml`, `assertion-qualification.yml` and `verdict-gate.yml`
would also run at A on a tag push; `checkwash.yml` runs only on pull
requests); `tests/gates/**`; the PJU stages. Draft pull request #597's
entry D-203 records the 2026-11-08 answers as a whole; its line that macOS
stays `NOT_RUN` until the POLICY allows it is out of date once this merges.

**Risks.** The first run may find failures that exist only on macOS or only
on Linux: the last hosted run of the suite was `ci.yml` at `618c415d` on
2026-10-23, and about 2,400 tests have been added since. Linux ran the same
tree in the PJU six-leg batch, so a Linux surprise there would come from the
host, not the code. The workflow has not run before this merges.
`macos-latest` and `ubuntu-latest` move to newer images; each record names
the image. The Action fetches an unpinned build backend from PyPI. A failure
after `publish-assets` leaves a GitHub Release without PyPI, which the next
release's verdict gate takes as its baseline
([baseline identity](docs/published-release-baseline.md)), and ordinary pull
requests are refused until a new version is advertised.

## D-205 (2026-11-12): a working-tree run sets aside the untracked zipapp checkwash runs from; a local hook install keeps its settings file out of Git

**Approval.** Claude wrote this entry in the pull request that records it,
#602. `DECISIONS.md` and `SPEC.md` are maintainer text (AGENTS.md). So the
pull request asked Nelson to approve, by name and before it merges, this
entry with the new §9 paragraph of `SPEC.md` (L1).

Claude described the change in the conversation, named the two texts and
linked the pull request, whose head was then
`5bb823e64bec0b335c68b58291c9a5bd0504004d`. At 2026-11-12T17:41:56Z Claude
asked 「#602 的 L1（D-205 和 SPEC §9 新段）核可，收據過了就合併嗎？」
(approve #602's L1, D-205 and the new SPEC §9 paragraph, and merge once
the receipt passes?), and at 23:38:29Z he chose 「核可並合併」 (approve and
merge). Claude wrote the question and both buttons; the other was
「我先看 PR」 (let me look at the pull request first).

The answer approves the two texts as they stand at that commit. It also
approves the merge, once the pull request's PJU receipt and the four
required checks pass. This paragraph is the only change made to the entry
after it.

**What was asked.**
- **The launch waits for the fixes.** At 2026-11-10T15:49:22Z Claude asked
  「發文要等門面和第一週的坑修完（出一個小版本）之後再發嗎？」 (should the
  launch post wait until the front page and the first-week problems are
  fixed, in a small release?). At 16:10:48Z Nelson answered 「先修再發」
  (fix first, then post). Claude wrote the question and both buttons; the
  other was 「現在就發」 (post now).
- **Claude leads in what he does not know.** At 2026-11-12T12:34:02Z he
  wrote, of projects that interest him in fields he does not know well,
  「所以會需要你帶 你的建議」 (so I need you to lead, with your
  recommendations) and 「遇到不懂的地方我還是需要你做完我在看 去學」 (where
  I do not understand, I still need you to finish the work, then I look at
  it and learn). Claude restated this as deciding such technical details
  itself and showing him the finished work, the direction staying his.
- **The re-sort.** At 12:37:30Z Claude asked 「要我現在照新做法，把各專案等你
  決定的事重整一遍嗎？」 (shall I now re-sort, the new way, what each project
  is waiting on you for?), and at 12:38:55Z he chose 「好，現在重整」 (yes,
  re-sort now). Claude wrote that question and both buttons; the other was
  「先不用」 (not now).
- **0.13.** After #597 merged, he wrote 「繼續做 0.13」 (go on with 0.13) at
  15:05:30Z, in his own words.

Claude chose 0.13's scope from the 2026-11-10 re-review: the five
first-week problems (group A), a report line for test-looking files that
are not analysed (group B), and G2 (b). Claude wrote the re-review, its
options and this scope. This entry covers group A's problems 3 and 5.
Problem 2 was in the first version of the pull request and is withdrawn
(below).

**What was found.** The 2026-11-10 re-review of main `8f610be9` had one
Claude sub-agent review newcomers and documentation on LAPTOP-01AGNPJU
(`HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL`). Two of its findings are fixed
here:

- **ND-09, the zipapp in the repository root.** The README's first path
  has a newcomer run the downloaded `checkwash.pyz` from the root of a
  repository, which works when the file is there. For 0.12.0 the file is
  1,013,508 bytes, over the 1,000,000-byte source limit, so `python
  checkwash.pyz check` on a clean tree reported it as not read and the
  analysis as incomplete.
- **ND-05, the machine-local settings file.** A local hook install (the
  default, or `--local`) writes `.claude/settings.local.json`. That file
  holds this machine's interpreter path, and Claude Code documents saving
  permission grants into it. The install left the file for Git to list, so
  every check without a range warned on it (`GUARDRAIL_TOUCHED`). Once it
  was committed, a grant written into it blocked at critical. In the
  re-review, that grant was written by hand.

**Decision.**

1. **The running zipapp.** A check without a range, the Stop hook's verdict
   diff and the session-commits analysis leave out the zipapp that the
   running checkwash is imported from, matched by name and real path. It is left
   out only when Git lists it as untracked and no file sits at its path in
   the compared commit or, in the Stop hook, in the session base. The
   verdict diff's listing names it once on stderr (`SPEC.md` §9). If Git
   cannot say whether a commit holds the path, the file is read.
2. **The local hook install.** When Git neither tracks nor ignores
   `.claude/settings.local.json`, a local install adds a rule for it to the
   `info/exclude` file Git names for the repository, and says so.
   - **Which file.** The path comes from `git rev-parse --path-format=absolute
     --git-path info/exclude`. Git before 2.31 prints that option back as
     its first line; the plain relative answer is then asked for and joined
     to the real path of the install folder.
   - **The rule.** It is anchored at the install folder, whose name is
     escaped as literal pattern text. A folder name with a line break gets
     no rule, and a note.
   - **A tracked file** is left alone and named, with how to untrack it
     from the repository root.
   - **A rule that does not take.** When another rule, such as a `!` line
     in a `.gitignore`, includes the file again, the note says so, and a
     second install adds no second rule.
   - **Outside Git** nothing is written.

   `info/exclude` is never committed, so this changes only the user's own
   clone.

**Why the zipapp rule cannot hide a change.** Only the archive the running
process was imported from qualifies, and only as an untracked record whose
path neither the compared commit nor the session base holds. These are
read as before:
- a tracked, staged or vendored copy;
- a copy whose path the compared commit or, in the Stop hook, the session
  base holds;
- another file of that name;
- everything in range mode.

The file set aside is the program doing the check, so an agent able to
replace it already controls the check.

**Problem 2, withdrawn.** The first version of this pull request also set
aside an untracked virtual environment: any directory with an untracked
`pyvenv.cfg` or `conda-meta/history` of its own and nothing tracked under
it. Three Claude review sub-agents found that rule unsafe, and found that
it misread the symptom's cause.

- **Unsafe.** Each of these let a working-tree or Stop run pass a change
  that main blocks:
  - a case-only rename of a tracked `tests/` on a case-insensitive disk;
  - a marker in `.checkwash/`, `.github/` or `.claude/`;
  - on Linux, a symlinked marker that pytest does not count, such as a
    dangling link.
- **On Windows.** Python's signed `Activate.ps1` reads as a test runner
  only because its base64 signature block holds the letters `tox` and
  `nox`, which `roles._runs_tests` matches as plain substrings. The
  unsigned copy on Linux and macOS draws no finding.
- **On Linux.** The re-review's symptom is an engine error instead: the
  environment's `bin/python` link leaves the repository.

A later pull request takes those causes.

**Residual.**
- **Hook edits out of view.** A local install now makes the settings file
  ignored where it was not, so a change an agent makes to the hooks there
  shows in no diff. That was already so wherever Git ignored the file
  (THREATMODEL item 2). Before this change, an untracked file showed only
  as created, with a warning on every run whatever its content. Item 2's
  words "often git-ignored" go to Nelson with the other protected text the
  re-review listed.
- **A vendored zipapp.** A tracked copy over the source byte limit still
  makes the report say the analysis is incomplete.
- **A zipapp untracked during a session.** A copy that a session untracked
  and that sits on disk under a name differing only in case, or one whose
  session base moved to before it was vendored, is set aside. It is the
  running program either way.

**Not changed.**
- Detectors, severities, the gating table, fixtures, `tests/gates`, range
  mode, the PreToolUse hook and the JSON schema.
- The README's first screen and install text. The first screen waits for
  Nelson (2026-11-08), and the release pull request takes the install
  text. Only the README's test count moves.

**What runs before merge.** On LAPTOP-01AGNPJU
(`HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL`):
- **`tests/test_first_week_fixes.py`, 25 tests.** Copied into a scratch
  worktree of main `9b69183d`: 4 pass, 15 fail and 6 error. Four of the
  21 that fail or error assert what main already does: a tracked, a staged
  and another copy of the zipapp, and Git unable to answer. They fail there
  only because main has no `_running_archive` to patch.
- The full suite.
- checkwash's own check of the pull request's range.
- Three Claude review sub-agents reviewed the first version, and one the
  second. This version answers their findings.
- The pull request's PJU receipt, whose intake sets the four required
  checks.

Other platforms: NOT_RUN. The review of the second version ran its 18
tests under WSL (Ubuntu 24.04, Python 3.12.3, Git 2.43.0), and all passed;
this version's 25 ran on Windows only.

## D-206 (2026-11-13): past its own bounds a changed test helper's importers are set aside, with a note; each helper's name is searched on its own, without the paths the diff changes

**Approval.** Claude wrote this entry in the pull request that records it,
#603. `DECISIONS.md`, `SPEC.md` and `THREATMODEL.md` are maintainer text
(AGENTS.md). So the pull request asked Nelson to approve, by name and
before it merges, this entry with the new §9 paragraph of `SPEC.md` and its
two edited §9 sentences on hook output, and THREATMODEL rows 183 and 184
(L1).

Claude described the change in the conversation, named the texts and
linked the pull request, whose head was then
`bc5d25e0d2a294d8f9cb6ab81b791e4605428f37`. At 2026-11-13T02:48:06Z Claude
asked 「#603 的 L1（D-206、SPEC §9、THREATMODEL 183／184）核可，收據過了就合併嗎？」
(approve #603's L1, D-206, SPEC §9 and THREATMODEL rows 183 and 184, and
merge once the receipt passes?), and at 02:50:44Z he chose 「核可並合併」
(approve and merge). Claude wrote the question and both buttons; the other
was 「我先看 PR」 (let me look at the pull request first).

The answer approves the texts as they stand at that commit. It also
approves the merge, once the pull request's PJU receipt and the four
required checks pass. This paragraph is the only change made to the entry
after it.

**What was asked.** D-205 records Nelson's 「繼續做 0.13」 (go on with 0.13)
of 2026-11-12T15:05:30Z, and his words on Claude leading in fields he does
not know. Claude chose 0.13's scope from the 2026-11-10 re-review. This
entry covers group A's problem 1, the re-review's FB-02, which it put first
of the three things most worth fixing because nothing releases it.

**What was found.** The 2026-11-10 re-review of main `8f610be9` had one
Claude sub-agent measure false blocks and adoption cost on LAPTOP-01AGNPJU
(`HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL`). Its finding FB-02, rated high:

- **The symptom.** A change to a test helper module with a common name,
  such as four lines added to `tests/utils.py`, made every check exit 2
  once 64 Python files mentioned that name. So did a docstring change, and
  `tests/base.py`. The control with 63 files passed. In checkwash's own
  history, `96ef295d`, which adds 33 lines to `tests/conftest.py`, exits 2
  the same way. No exemption releases an exit 2, and the hooks reported the
  change as not analysed.
- **The cause.** When a test or conftest file that defines a function not
  named `test…` changes, the expected-value pass
  (`expected_provenance.importer_changes`) searches the analysed snapshot
  for the file's module name, to find the unchanged tests that import it.
  The snapshot search raises at 64 hits, so in a real run the pass's own
  `return []` for 64 candidates could not be reached, and every engine
  error exits 2.

**Decision.**

1. **The hit limit** raises `SearchHitLimit`, an engine error, so every
   caller that does not handle it still stops the run. The message, and
   `sweep`'s `exception_type`, now name that type: `checkwash engine
   error: SearchHitLimit: strict snapshot importer search exceeds the hit
   limit`.
2. **A search can leave paths out.** The Git and working-tree snapshot
   searches, and the PreToolUse hook's proposed tree, take `exclude`. An
   ordinary search neither returns nor counts those paths, compared as Git
   spells them, and the working-tree search does not read them. The
   inventory, which lists every nonempty Python source, is never narrowed.
3. **Each name on its own.** In a run that reports what it says, the
   expected-value pass searches each changed helper's module name on its
   own, with every path the diff changes left out: each changed path, both
   paths of a rename, and the unchanged files that other passes added to
   the diff. A file mentions a name when it holds it as plain text, so
   `database` mentions `base`. Each name has its own bounds, and past them
   the helpers of that name are set aside: none of their importers is read,
   and one note names them and the bound.
   - **The search reaches its limit:** 64 or more unchanged Python files
     mention the name. When the diff renamed one of that name's helpers to
     it, the name is the diff's choice and could be one every file holds,
     so the hit limit stops the run instead. A helper the diff deletes, or
     moves under the same name, keeps the name its importers use.
   - **More than 48 unchanged tests mention the name.**
   - **The run's budget is spent.** The names whose tests fit are read
     from the one with the fewest, and the run reads at most 192 importers
     (4 × 48) for all of them together.
   - **More than 16 names** in one change set every helper aside.

   The read budget and the name bound read nothing before this change too,
   without a note, and every name shared one read budget of 48.
4. **The run that cannot report it keeps the old way.** Without a report
   context (`sweep`, `bench`), or with a searcher that cannot leave paths
   out, one search covers every name and its hit limit stops the run, as
   before.
5. **The note** (`SPEC.md` §9) is `analysis incomplete: <reason>, so
   unchanged tests that import <helpers> were not read for their expected
   values`. A path or name that would not print is shown by its `repr`.
   - It is written on stderr in every format, as a SARIF tool execution
     notification and as a `!` line of the term report, whose head then
     reads "analysis incomplete" when there is no finding.
   - When the Stop hook passes it is the `systemMessage`, for its check of
     the working tree and, after `commits made during this session:`, for
     the session's commits.
   - When the PreToolUse hook does not ask about a weakening, it gives the
     note as its `systemMessage`; under the base policy's `on_engine_error
     = "block"` it asks with it instead, as it asks for an edit it could not
     analyse. A hook note longer than 1,200 characters ends in `…`.
   - JSON stdout and `--emit-ir` keep their bytes.
6. **The root-helper search**, which reviews the assertions a changed root
   helper removes, is unchanged: at its limit the run still stops
   ([root assertion helpers](docs/root-assertion-helpers.md)).

**Why the diff cannot use the limit.** Before this change a diff could fill
the search with files of its own, but that stopped the run. Now:
- The search leaves the diff's paths out as Git spells them, a path that
  holds `\` included, so only files the diff does not change count toward
  a name's limit. Two of the new tests pad a weakened helper's search with
  70 added files, one with names that hold `\`: the importer is read, and
  the change blocks.
- Each name has its own search and budget, so touching a commonly named
  helper sets aside that helper, not the one beside it.
- A helper the diff renames to another name keeps the engine error at the
  limit, so a rename to a name every file holds stops the run, as before.
- The run's budget reads the smallest names first. Pushing one helper past
  it takes other changed helpers that each have at least as many
  importers, enough to fill 192 reads; more than 16 names set every helper
  aside anyway.

The range check, the required gate, searches only committed files and
leaves out the range's whole change. The hooks count more, since their
diff is narrower than the change:
- **The PreToolUse hook.** Its diff is the one edit it is asked about, so
  files the session wrote before that edit count.
- **The Stop hook.** Its check compares HEAD with the working tree, so
  files the session committed count there.
- **Working-tree mode**, both hooks included. The search walks the disk,
  so files Git ignores count, and so does a changed file renamed by case
  only on a disk that ignores case.

Before this change such files stopped the run, and both hooks then reported
the change not analysed: the Stop hook let it through, and the PreToolUse
hook asked only under `on_engine_error = "block"` (THREATMODEL row 128).

**Residual (THREATMODEL row 183).** Past its own bounds a weakened helper's
importers are not read. `expected = 4` -> `expected = 5` in
`tests/helpers.py`, which an unchanged test calls, passes with the note
when 64 or more unchanged Python files mention `helpers`, or when more than
48 unchanged tests do. In the range check those two bounds are the
repository's; in the hooks, the cases above add to them. The 16-name bound
is the change's own choice, as it was before this entry, and is easy to
reach: any test or conftest file with a top-level function whose name does
not start with `test` counts as a helper.

Before this entry the hit limit stopped every check, and the other two
bounds passed without a note. The hooks change with it: before, they
called such a change not analysed; now they give a verdict on the rest of
the change, with the note when the Stop hook passes or the PreToolUse hook
does not ask about a weakening.

**Cost.** Each name has its own search, which in a working tree walks every
Python file, and the run may read up to 192 importers where one budget read
48. On LAPTOP-01AGNPJU (`HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL`):
- an honest edit to 16 helper modules among 4,000 files: 18.5 s in a
  working tree (main 4.6 s) and 3.3 s in range mode (main 2.7 s);
- 16 helpers each imported by 48 unchanged tests, in range mode: 20.1 s,
  reading 192 importers and setting 12 names aside; main stopped at the hit
  limit in 2.0 s.

**Older than this change, found by its review** (THREATMODEL row 184). Each
passes on main `6c2b7669` without a note, and still does:
- **The pass's own read budget.** Reading the tests it analyses, the
  expected-value pass shares 48 source reads across the whole run; past
  them it drops the rest without a note. A weakened helper beside an
  edited test file that gains 25 one-line tests, each calling a different
  module, passes; with 10 such tests it blocks.
- **What the pass reads.** A helper whose old version has a top-level
  statement the pass does not read (an `if`, `try`, `with`, `for` or a
  call) is never searched.
- **Moves the search misses.** A helper moved into a package's
  `__init__.py`, which is searched as `__init__`, or renamed by case only,
  is searched by a name its importers do not use.
- **Also:** an unchanged test over the source byte limit that mentions a
  helper's name stops the run, and so does any Python file over that
  limit in a working-tree search; and a diff path that holds `\` can hide
  an unchanged importer whose path reads the same with `/`.

**Not changed.**
- Detectors, severities, the gating table, fixtures, `tests/gates`, the
  JSON schema and the coverage report, whose scope is JavaScript assertion
  candidates.
- The root-helper search.
- The needle, which stays the bare module name, and the limits 64, 48 and
  16.

**What runs before merge.** On LAPTOP-01AGNPJU
(`HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL`):
- `tests/test_importer_search_skip.py`, 39 tests. Its thirteen command-line
  tests, run with the command line from main `6c2b7669`'s tree: twelve
  fail, as the run exits 2 or a hook reports the change not analysed; the
  thirteenth asserts what main already does, exit 2, for a helper renamed to
  a common name. The file's other 26 tests call code main does not have.
- Twenty one-line mutants of the change, each run against that file in its
  own copy: all twenty fail it.
- The full suite, and checkwash's own check of the pull request's range.
- Review. Three Claude review sub-agents reviewed the first version
  (`6ba50a02`): one for bypasses, one for code and tests, one for
  documents and claims. One reviewed the second (`383a0906`). This version
  answers them:
  - for the first: one search and one budget for every name; a backslash
    in a path; the Stop hook's session commits; `sweep`; the SPEC and
    stability statements on hook output; eight mutants that survived;
  - for the second: the backslash fallback, which brought the shared
    budget back; honest deletions and same-name moves, which kept exiting
    2; the PreToolUse hook under `on_engine_error = "block"`; three mutants
    that survived; the cost, now bounded by the run's budget; and the older
    gaps above, now recorded.

  This version was not reviewed again.
- The pull request's PJU receipt, whose intake sets the four required
  checks.

Other platforms: NOT_RUN.

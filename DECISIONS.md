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

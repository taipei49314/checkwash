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

## D-189 (2026-10-28): a Claude Code PreToolUse ask on the five weakening rules, and a Stop block that reports instead of exempting

On 2026-10-28 Claude asked "0.11 的 agent 路徑要走哪一種？" with two buttons.
Nelson clicked the button labelled 「加 PreToolUse ask」. The button's label
and its option text were written by Claude; the option text was:
"0.11 加 PreToolUse ask，只問五條弱化規則；先修擋下訊息和 stop_hook_active，Stop hook 凍結預設另外再議"
(0.11 adds a PreToolUse ask on the five weakening rules only; first fix the
block message and stop_hook_active; the Stop hook freeze default is to be
discussed separately). Only the label may have been sent. Earlier the same
day Nelson approved the 0.11 scope
(「1.核准 2.用寫清楚結案 stop hook自動凍結 3.這次統一收尾後跑 4.readme等到修復後重排 可以進版 Hook選local …」
and 「開始」); this decision replaces item 2's "stop hook 自動凍結" with
the PreToolUse ask.

Claude maintains checkwash under Nelson's 2026-10-27 delegation
(「Checkwash 一樣給你」, the same delegation Codex had: 0.x autonomous, stop
before 1.0; [RELEASING](docs/RELEASING.md)). The detailed choices below,
this entry's text and the test-expectation changes it lists are Claude's
under that delegation, as D-185 to D-187 were Codex's. They are not
Nelson's personal review.

**Why.** A pre-registered session replay (local repository
`C:/Users/nelson/dev/cwrp`, PREREG `2e693e3`, results `93e602c`,
RESULTS.md) took the 684 successful Claude Edit and Write calls on Python
test files in this host's Claude Code transcripts (2026-08 to 2026-10),
reconstructed 630, and replayed each as a single-file diff through the
released v0.10.0 pyz (SHA256
`9a58d3d48f4f314a46b153bc0b7ad5182829c210a3ce9dae575c46f2f3bc535a`), with
and without `oracle_freeze`, on LAPTOP-01AGNPJU, Windows CPython 3.11.9
(`HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL`). The freeze arm blocked 123 of
the 630 (19.5%).

- Labels: blind, two-pass, by Claude, not a human, so they are
  provisional until Nelson spot-checks the deciding cases (PREREG).
- A real loosening is a block labelled LOOSEN_UNEXPLAINED or
  LOOSEN_JUSTIFIED: after the edit the tests check strictly less about
  existing behaviour, with nothing in the context justifying it, or with
  the context justifying it.
- A false ask is a block labelled NOT_LOOSENING (nothing got weaker),
  counted against the blocks not labelled UNCLEAR. ORACLE_CHANGE_NEUTRAL,
  an oracle changed at equal strength to follow an intended behaviour
  change, is neither.
- The 123 blocks: 32 real loosenings (12 unexplained, 20 justified), 56
  neutral oracle changes, 32 not a loosening (false asks, 32 of 120
  labelled, 26.7%) and 3 unclear.
- Exploratory, not pre-registered: the blocks whose blocking rules include
  one of the five weakening rules are 63 asks (10% of the edits): 8
  unexplained, 16 justified, 26 neutral, 12 not a loosening and 1 unclear,
  so 24 of the 32 real loosenings and 8 of the 12 unexplained ones, with
  12/62 = 19% false asks.
- Scope of the evidence: Python test files only, single-file diffs, edits
  mostly from checkwash and EC development on this host. The rates are the
  released v0.10.0 pyz's on those diffs, not a measurement of the 0.11
  handler.

**What 0.11 implements.**

- A. `checkwash hook pre-tool-use` (`pretool.py`, `cli.py`), the managed
  PreToolUse handler.
  - It is dispatched before argparse, reads only `--repo` and ignores every
    other argument, and always exits 0, printing exactly one ASCII-escaped
    JSON object: a PreToolUse hook that exits 2 blocks the tool call. It
    reads at most 8,000,000 bytes of hook input.
  - It answers `{}` unless the input is a PreToolUse event for Edit, Write
    or MultiEdit (whose input Claude Code does not document) with a
    `file_path` ending `.py` (on Windows, as the file system writes it:
    trailing dots and spaces dropped, case folded), inside this work tree
    as resolved through
    links and junctions (not under `.git`, in a nested repository or
    submodule, with a `:` part, or not UTF-8), and judged a test: role
    `test` or `conftest` under base policy, or collectable by pytest.
    Python only: JS/TS tests were not measured and are not asked about.
  - Policy (`config.toml`, `allow.toml`) is read from the session base when
    a usable record exists, else HEAD, as the Stop hook reads it (#418,
    D-177). No `--task` is read.
  - The diff is one change: the current working-tree file (absent: an
    addition) against the bytes the call would leave, predicted from the
    tool input. An Edit applies `old_string` to `new_string` in strict
    UTF-8, exactly once unless `replace_all`, with CRLF line ends in a file
    that holds CRLF line ends and no bare LF. Anything not predicted exactly answers
    `{}`. When the working copy does not parse and HEAD's copy does, HEAD's
    copy is the before side; an edit that makes a parseable test
    unparseable still asks (TEST_DISABLED for each vanished unit), as the
    replay measured. The rest of the analysis reads the working tree with
    the proposed bytes at that path. `oracle_freeze` is forced on through
    the contract (E2); the gating table is unchanged.
  - It asks when a finding of ASSERT_WEAKENED, ASSERT_REMOVED,
    TEST_DISABLED, TOLERANCE_LOOSENED or BROAD_EXCEPT_ADDED, on any path, is
    not allowlisted and is at high or above. The threshold is fixed at high
    and does not follow `fail_on`. A side over 1,000,000 bytes asks, naming
    it (as #456 blocks the Stop).
  - The reason names at most three findings, escapes unprintable and bidi
    characters, is at most 1,200 characters, offers no `checkwash allow`
    and no fingerprint, and says that if the user denies the edit, Claude
    should report the finding, not make the same change another way.
  - An engine error once the path is judged a test, or no answer within
    30 seconds: under base `on_engine_error = "block"` it asks, saying the
    edit was not analysed; under `pass_with_warning`, the default, it
    answers with that text as a `systemMessage` and leaves the call to the
    normal permission flow.
- B. Installation and doctor (`hooks.py`, `cli.py`, `doctor.py`).
  - `hook install --agent claude-code` writes `.claude/settings.local.json`
    by default. `--shared` writes `.claude/settings.json`; `--local` stays,
    as the default's spelling; the two exclude each other. With neither
    flag, an install refuses (exit 2) when `.claude/settings.json` already
    holds the managed Stop or SessionStart handler, and names both flags.
  - Local installs add a managed PreToolUse handler in a group with the
    matcher `Edit|Write|MultiEdit`, on the Stop handler's runtime binding,
    running its own bootstrap, which exits 0 whatever the bound runtime
    does: an older checkwash left there would answer with a usage error,
    exit 2, and block every edit. The install probes it with `{}`.
  - Shared installs get no PreToolUse handler: a teammate whose PATH holds
    a checkwash older than 0.11 would have every Edit and Write blocked.
    The install message says so, and that each teammate can add it with
    `checkwash hook install --agent claude-code --local`.
  - The installer manages a matcher group only in its own exact shape; a
    user's own groups and matchers are never rewritten. doctor recognises
    the PreToolUse handler and notes when the PreToolUse ask and the Stop
    hook are not both configured.
- C. The Stop hook (`cli.py`, `session.py`).
  - Every `check --format hook-json` block on findings, with or without
    `--hook-input`, gives the count and the first finding, tells Claude to
    fix the production code if it is wrong, not to weaken, skip or remove
    the test, and not to add an exemption or change checkwash's
    configuration or hooks itself, but to tell the user which finding
    blocks and why and let the user decide. It offers no `checkwash allow`
    and no fingerprint.
  - Release (V1): with `--hook-input stdin`, a block verdict,
    `stop_hook_active` exactly JSON `true`, and a blocking set identical to
    the one this hook last blocked on in the session, the stop is not
    blocked again. A `systemMessage` tells the user that up to five named
    findings still block, and adds the next-session sentence when the
    session base differs from HEAD. Every other case blocks: no recorded
    block (another hook's continuation), a different set, a value other
    than `true`, no session id, no `--hook-input`.
  - The set is the SHA256 of the sorted blocking fingerprints, recorded in
    `<git-dir>/checkwash/sessions/<sha256(session_id)>.stop`. A pass
    deletes it, and session-start pruning removes such records older than
    30 days. The agent can write them (THREATMODEL item 2).
  - The #456 size block is a separate path and still blocks on every stop:
    D-150's choice not to read `stop_hook_active` there stands. A released
    stop gives no session-commits note; that note is for a pass.
  - Claude Code's hooks documentation (code.claude.com/docs/en/hooks,
    read 2026-10-28) caps consecutive stop-hook continuations at 8
    (`CLAUDE_CODE_STOP_HOOK_BLOCK_CAP`), so blocking again enforced
    nothing; it only pressed Claude to change the test. In the lifecycle
    receipt below the hook released the first continued stop, so the cap
    of 8 was not reached or exercised.

**Superseded.**

- D-142 item 6's "keeps the `checkwash allow` command": the reason offers
  no exemption command or fingerprint.
- The reason's next-session sentence ("An exemption, config change or hook
  upgrade committed during this session applies from the next session;
  /clear starts one."): it is no longer in the reason, and goes to the user
  in the released stop's note. Policy committed during a session still
  applies from the next one.
- The 0.11 scope item "stop hook 自動凍結": the Stop hook applying
  `oracle_freeze` by default is deferred.

**Unchanged.** The verdict computation, the gating severity table, the
strength lattice, alignment parameters, every `.gwcase` expectation, the
findings and IR versions, and the required CI check in range mode, which
remains the gate. Both hooks remain author-side checks.

**Evidence: a Claude Code hook lifecycle receipt.** On 2026-10-28 Nelson
clicked the button labelled 「核准跑一次」. The button's label and its option
text were written by Claude; the option text was
"核准在 PJU 跑一次 Claude Code hook lifecycle 實測（PreToolUse ask 在 default 與 bypassPermissions 模式各一次、Stop 的 stop_hook_active 放行），只為 PR #576 驗證"
(approve one Claude Code hook lifecycle run on PJU: the PreToolUse ask once
in default and once in bypassPermissions mode, and the Stop hook's
stop_hook_active release, for verifying PR #576 only). Only the label may
have been sent.

- Records: local repository `C:/Users/nelson/dev/cwrp`, pre-registration
  `LIFECYCLE-PREREG.md` and `run_lifecycle.py` committed as `abd56c0`
  before the run, with no amendment; results `LIFECYCLE-RESULTS.md`
  (`bb95fd6`), with post-hoc notes from a review of the raw records
  (`4f33b92`). Raw output is under `lifecycle/20261028T145207Z/`: committed
  are `meta.json` and, per invocation, `record.json`, `stream.jsonl`,
  `stderr.txt` and `debug.log`; each invocation's scratch `repo/` (with its
  `settings.local.json` and session records) is local only. That
  repository has no remote.
- Run: LAPTOP-01AGNPJU, Windows (`HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL`),
  2026-10-28T14:52:07Z to 14:53:07Z. Claude Code `2.1.260 (Claude Code)`,
  model `claude-haiku-4-5-20251001` (`--model haiku`), `-p --output-format
  stream-json --verbose --include-hook-events --setting-sources
  project,local`. Engine: PR #576 head `f4253f7c`, clean worktree, with the
  hooks that `checkwash hook install --agent claude-code --local` writes, in
  a scratch repository per invocation. Four invocations, US$0.19 in all as
  Claude Code reported it.
- Deviation, registered before the run: `--permission-mode acceptEdits`
  replaced default mode. The pre-registration's reason: in a `-p` run
  default mode would deny the Edit whether or not the hook asks, so the
  hook's effect could not be told apart, while acceptEdits approves edits
  by itself, so only the hook can turn the Edit into a denial. No
  default-mode invocation ran. A control invocation's comment-line Edit got
  `{}` from the hook and was applied.
- PreToolUse: under acceptEdits and under bypassPermissions
  (`--dangerously-skip-permissions`) alike, an Edit changing `== 105.3` to
  `> 0` got `permissionDecision: "ask"` naming ASSERT_WEAKENED; Claude Code
  denied it, the tool result carried the hook's reason verbatim, and the
  file was unchanged. Both invocations' stream output records the denial
  with `decision_reason_type: "hook"`, which is the evidence that the hook
  caused it. bypassPermissions did not skip the hook's ask in `-p`.
- Stop: with the weakened test in the working tree, the first stop was
  blocked with the reason above (no `checkwash allow`; "tell the user which
  finding blocks and why"). Claude read the test once and reported the
  finding to the user, with no edit and no exemption. The next stop got no
  `decision` and the `systemMessage` "checkwash: this stop was not blocked
  again, but 1 finding(s) still block this change: ...". The first stop's
  block wrote a `.stop` record, which was still there after the run. The
  release runs only on `stop_hook_active` exactly `true`, so the managed
  Stop handler received it on the continuation; the debug log does not
  record hook inputs.
- Every SessionStart handler exited 0 with no output.
  `~/.claude/settings.json` was unchanged; Claude Code wrote project
  entries for the scratch paths to `~/.claude.json`.
- Observed, not pre-registered: Claude restated the weakened assertion's
  "Before" as `== 90`. The finding message reads "assertion strength
  EXACT_VALUE(90) -> BOUND(40)", where 90 is the lattice strength, not the
  expected value. Right after the first stop's `decision: block`, Claude
  Code emitted `{"subtype": "notification", "key": "stop-hook-error",
  "text": "Stop hook error occurred · ctrl+o to see"}`, while its debug log
  records that hook as `Hook Stop (Stop) success`: in `-p` stream-json,
  Claude Code 2.1.260 reports checkwash's exit-0 block as a hook error.
  How the interactive UI shows the block is not verified
  ([KNOWN-ISSUES-next](docs/KNOWN-ISSUES-next.md)).

**Not verified.**

- The receipt ran in `-p` mode only, where an ask becomes a denial. No
  interactive session was run, so the permission prompt the user sees is
  not observed in any mode, bypassPermissions included, and neither is
  whether a `systemMessage` is displayed to the user in the interactive UI
  (the released stop's appeared in the hook event output and as Claude
  Code's own `informational` notice event, "Stop says: checkwash: this stop
  was not blocked again, ..."). Only the Edit tool and the ASSERT_WEAKENED
  rule were exercised: a Write call, a MultiEdit call, the other four
  rules, the size ask and the engine-error ask were not, nor were a
  PreToolUse `systemMessage`, other Claude Code versions, other models and
  other platforms.
- Claude Code's hooks documentation (code.claude.com/docs/en/hooks, read on
  2026-10-28) says: the ask reason is shown to the user in the permission
  prompt; in a `-p` run nobody can answer, so the call is denied and Claude
  reads the reason; `ask` also prompts in auto mode; exit 0 with no output
  leaves the normal permission flow; a timed-out hook does not block
  (default timeout 600 seconds). It does not say whether a hook's `ask`
  prompts in bypassPermissions mode, or whether `systemMessage` on
  PreToolUse output reaches the user, and it does not document MultiEdit's
  input. Of these, the receipt observed the `-p` denial, under acceptEdits
  and bypassPermissions, and an edit the hook answered with `{}` (an empty
  decision, not "no output") going ahead under acceptEdits; auto mode and a
  timed-out hook were not exercised.
- Latency: smoke runs on LAPTOP-01AGNPJU (human-authorized local PJU, NOT
  EC pool) took about 1.0 to 1.2 seconds per PreToolUse call on a two-file
  repository. It is not measured on large
  repositories.

**Test expectations.** These ordinary tests changed, none of them a
`.gwcase` fixture or under `tests/gates`:

- `tests/e2e/test_cli.py` `test_hook_json_blocks_with_reason`: "checkwash
  allow" in the reason becomes not in the reason, and the "tell the user
  which finding blocks and why" sentence is.
- `tests/test_issue418_session_base.py`
  `test_an_uncommitted_blocked_edit_still_blocks_as_before`: the
  `checkwash allow "ASSERT_WEAKENED/` substring becomes the named finding,
  with "checkwash allow" absent.
- `tests/test_issue418_session_base.py`
  `test_an_exemption_committed_during_the_session_governs_only_the_next_one`
  (THREATMODEL row 133's E2E pin): the fingerprint comes from `check
  --format json`; the second stop still blocks, without "checkwash allow";
  the next-session sentence is asserted in the released stop's
  `systemMessage`; the next session (s-2) still passes.
- `tests/test_issue455_bounded_shebang_read.py` (one assertion) and
  `tests/test_issue456_hook_size_refusal.py` (one assertion, three
  parameters): "checkwash allow" in the reason becomes the "tell the user"
  sentence.

New: `tests/test_pre_tool_use.py`. No other existing expectation changed.

## D-190 (2026-10-29): a proven Python failure relay is not a swallow, within 0.10's count

**Authority.** On 2026-10-28T08:34:01Z Claude asked Nelson five questions.
Item 1 was
「**uvloop**：沿用 Codex 的接受，還是你親自決定；是否核准「認得轉交寫法」的引擎修正。」
(keep Codex's acceptance or decide himself, and whether to approve an engine
fix that recognises the relay spelling), with the recommendation
「讓 checkwash 認得「把例外交給一個確實會被等待的 Future」，認得的降成 warn，真正吞掉例外的照擋。這會動到凍結區，要你核准。D-187 只涵蓋 0.10，下一版要嘛做這個修正，要嘛由你親自決定接不接受。」
(recognise "handing the exception to a Future that is actually awaited",
lower what is recognised to warn and keep blocking real swallows; it touches
the frozen area and needs his approval; D-187 covers 0.10 only). At
2026-10-28T08:41:25Z Nelson replied
「1.核准 2.用寫清楚結案 stop hook自動凍結 3.這次統一收尾後跑 4.readme等到修復後重排 可以進版 Hook選local Doctor放寬我有點不太確定 5.這題我不太確定」
(its line breaks and doubled spaces shown as single spaces, as in D-189).
Claude's plan at
08:43:12Z, item 1, was
「**修 uvloop 誤擋（你已核准）**：讓 checkwash 認得「把例外交給一個確實會被等待的 Future」這種轉交寫法，降成 warn。真正吞掉例外的照擋；`oracle_freeze` 和 `fail_on=warn` 還是會擋。另外補上回歸 fixture，並重跑那三筆 uvloop，確認從 block 變成 warn。」,
and Nelson clicked the button labelled 「開始」 at 09:05:05Z.

At 2026-10-28T17:33:37Z (2026-10-29 01:33 Asia/Taipei) Nelson clicked the
button labelled 「接著做 0.11」, whose option text was
「接著做 0.11 其他項目（uvloop 轉交辨識、#419 殘餘結案、doctor 方案 S、README 重排），順便帶上那 3 項文字修正」.

On 2026-10-29 Claude told him that the design departs from the approved
text: under option C a recognised relay gets no finding, so `oracle_freeze`
and `fail_on=warn` no longer block it, because D-189's PreToolUse ask forces
`oracle_freeze` and E2 would raise a warn to high, so every legitimate relay
would be asked about. Claude recommended C, bounded so that 0.11 never adds a
finding 0.10 lacks, and asked 「uvloop 轉交要用哪個做法？」. At
2026-10-29T14:29:31Z Nelson clicked the button labelled
「用 C，開始改 PR-A」, whose option text was
「用 C：認得的轉交不列 finding，並限制成不會多出 0.10 沒有的 finding；照交接檔 0a 的清單改好 PR-A 再開工」;
the other button was labelled 「照原案降 warn，開始」.

Claude wrote each button's label and option text, and only the label may
have been sent. These approvals cover this entry's agent-read-only edits:
the SPEC §4 row and its new subsection, THREATMODEL rows 16 and 171, and
this entry. Claude maintains checkwash under Nelson's 2026-10-27 delegation
(「Checkwash 一樣給你」: 0.x autonomous, stop before 1.0;
[RELEASING](docs/RELEASING.md)). Every choice below that is not quoted above
is Claude's under that delegation, as D-189's were: the rules R1 to R7 and
R2b, the bound's form, the fixtures, and the tests and their expectations.
They are not Nelson's personal review. AGENTS.md says fixture labels are
reviewed by a human before merge; the labels of this entry's 24 fixtures
were set by Claude as the delegated maintainer.

**The departure from 「降成 warn」.** The approved recommendation and plan
said a recognised relay is lowered to warn, stays listed, and still blocks
under `oracle_freeze` and `fail_on=warn`. This implementation removes the
finding instead. E2 (`gating.py`) sets every oracle finding to high after
the de-escalators, and D-189's PreToolUse handler forces `oracle_freeze` and
asks on BROAD_EXCEPT_ADDED at high, so a warn would still ask about every
legitimate relay; an exemption per fingerprint would need a human for each
case and fix nothing in general. Nelson chose C, with the 0.10 bound, on
2026-10-29 (above). So a recognised relay is not reported under
`oracle_freeze` or `fail_on=warn` either, which the 10-28 plan said would
still block, except in the price case of *The bound's form* (below), where
it is reported as on 0.10.

**What changed.**

- `frontends/python/failure_relays.py` (new) proves SPEC §4 *Python failure
  relays*: R1 the relay statement, in a function S with no loop between; R2
  no assertion a parse-time unit executes inside the `try` body, compared in
  the character offsets `Assertion.span` uses, and no asserting name read in
  it, closed over same-file calls; R2b (a) a parse that collects tests and
  is not a conftest's, (b) no enclosing pytest fixture, by any decorator
  whose last name is `fixture` or `yield_fixture`, so
  `pytest_asyncio.fixture` too, (c) S nested in another function; R3 the
  future, with a file-wide list of dynamic access that turns every relay in
  the file off; R4 its uses; R5 a proven consumer, under no handler and
  after no `return`, with B's own failure reaching its caller; R6 the
  trusted loop, with every store of its attribute outside M on a fresh
  local; and R7 asyncio. A `try`/`except*` is not read. The run
  sites are exactly R5's two forms: the design prototype's further
  acceptance of a plain `C()` call of a sync def and of `await
  asyncio.wait_for(C(...))` is dropped
  (`tests/test_failure_relays.py::test_r5_no_other_run_site_is_read`, with
  `asyncio.run(C())`). A `run_until_complete` on an
  untrusted receiver is another use of the future (R4), which refuses,
  rather than a use that merely proves nothing. The reader numbers the tree
  once in pre-order, indexes what the rules look up, and memoises per
  scope, future, statement and statement list; its walks up the scope chain
  make the worst case the file's size times the nesting depth of the
  relay's scopes (*Second review*, below).
- `frontend.py`: the swallowing list is computed exactly as on 0.10. The
  proven relays among it go to a new `ParsedFile.relay_handlers`, read only
  in a parse with `collect_tests` and without `conftest`, and only once a
  relay-shaped handler asks; a `RecursionError` in the reading leaves the
  handler unproven, so the reading never turns a file 0.10 analyses into an
  engine error. `ParsedFile` is not serialized, so no IR field, fingerprint
  or cache key changes.
- `engine.py`: per file and per handler text, the BROAD_EXCEPT_ADDED
  additions become the multiset intersection (`Counter &`, the elementwise
  minimum) of 0.10's difference, Counter(swallowing after) −
  Counter(swallowing before), and the after side's swallowing handlers that
  are not proven relays, Counter(swallowing after) − Counter(relays after).
  The before side's relays are not read. A file without relays on its after
  side gets exactly 0.10's count, so its IR is byte-identical.

Consequences, stated in SPEC §4, THREATMODEL row 171 and KNOWN-ISSUES-next:
0.11 never reports a BROAD_EXCEPT_ADDED that 0.10 would not; a relay that
the same change makes proven cannot pay for a new swallow of the same first
line; an unrelated edit can no longer make an unchanged relay reported (the
2026-10-29 status review's N1: one added line `_NOTE = 'loop'` in uvloop's
`tests/test_tcp.py` made a per-side reading report four relays); an edit
that breaks an existing relay, for example by removing its await, is not
reported, exactly as on 0.10, a residual pinned by
`tests/test_failure_relays.py::test_residual_row171_breaking_a_relay_is_not_reported`;
a new swallow added beside an existing relay still reports; and an honest
relay added beside a handler of the same first line that is not a proven
relay is counted, as 0.10 counts it.

**The bound's form.** Claude's plan for this round, and the first
implementation, put the bound as 0.10's difference intersected with the
difference computed with proven relays removed from both sides. That form
keeps every consequence the plan named, but two 2026-10-29 adversarial
reviews showed it pays for a genuine swallow. When a handler the before side
did not read as a relay (its consumer missing, its body not yet a relay, or
a string equal to the loop's attribute name elsewhere in the file) becomes a
proven relay in the same change, removing relays from both sides matches
the new swallow of the same first line against that before-side handler,
and the swallow of a unit's own assertion went unreported: the PreToolUse
ask stayed silent and the Stop hook and a CI range check passed, where 0.10
blocked. Reading the after side alone keeps the intersection with 0.10's
difference, so the second half of Nelson's option text,
「限制成不會多出 0.10 沒有的 finding」, still holds; it keeps every
consequence the plan named and adds the one above. Its price is the last
consequence above, and there it departs from the first half,
「認得的轉交不列 finding」: an honest relay added beside a handler of the
same first line that is not a proven relay is reported, under
`oracle_freeze` too
(`tests/test_failure_relays.py::test_a_relay_beside_a_same_text_swallow_reports_as_on_0_10`).
A count per handler text cannot tell that case from the trade above, where
the same counts hide a genuine swallow. Choosing the after-side form, and
with it that departure, is Claude's under the delegation; Claude reported
the departure to Nelson when this change was committed.

**Why R2b.** R2 reads parse-time units only, but the engine folds a
fixture's assertions (everything lexically inside it, nested callbacks
included) and sibling helpers' own assertions into units after the parse,
and a test-role file that pytest does not collect is parsed without units
(status review, DF0). Keying on units being present would keep uvloop
`7b202ccf` blocking: its `tests/test_context.py` parses to no unit, because
its tests live in a mixin whose collecting class has an imported base. R2
and R2b carry the security argument: a credited relay sits in a function
nested in another, in a collected test module and outside any fixture, and
its `try`
body neither holds an assertion a parse-time unit executes nor reaches one
through a same-file name, so whatever defeats it loses only what 0.10
already lets a cheaper edit lose (THREATMODEL rows 91 and 176, as the
*Second review* below corrects). R3 to R7 are precision on top: they
refuse the spellings they name, and no list of spellings closes every
same-file route.

**Other consumers of the swallow lists.** Only the engine's
BROAD_EXCEPT_ADDED count reads `swallowing_handlers` and `broad_handlers`,
and the relay credit applies only to the swallowing side of that count. The
three alias passes (`class_exception_aliases`, `function_exception_aliases`,
`neutralizing_aliases`) add to both lists and keep `relay_handlers` through
`dataclasses.replace`. Gating and the evidence code read neither list. The
#496 always-passing branch is an `elif` of `_swallows`, so a relay never
reaches it. JS/TS parses leave `relay_handlers` empty.

**Unchanged.** The gating severity table and `ORACLE_RULES`; E1 and E2;
D-176's unit-less refusal, with `issue419_narrow_broad_template_pos` still
blocking; the strength lattice and alignment parameters; the detectors and
the unit-less fingerprint; `pretool.py`, `cli.py` and `hooks.py`, so the
PreToolUse rule set and threshold; the JS/TS frontend; the findings and IR
versions; `broad_handlers`, so production-role files; `tests/gates`; and
every existing `.gwcase` and test expectation.

**Residuals** (THREATMODEL row 171, [KNOWN-ISSUES-next](docs/KNOWN-ISSUES-next.md)):
a loop built outside the file is trusted (uvloop's `BaseTestCase.setUp` sets
`self.loop = self.new_loop()`, which a same-file subclass or another file can
override); asyncio or its `Future` replaced from another file, a conftest's
`sys.modules` among them, is trusted; a same-file route the named spellings
miss, such as a stand-in reached through a call's result or a metaclass, is
not refused; B's own completion is read only in the function that calls
it, so a B called from a function that is itself handed to a thread or
swallowed further up, or an async B whose coroutine is scheduled and never
awaited, can lose the consumer's failure; a callback invoked again after
it completed the future loses the later failure; a context manager the
test's base class provides is trusted as its loop is; a broken relay is
not reported, as on 0.10; and honest relays
outside the rules (a future created on, a relay scheduled on or a run site
on a loop from `asyncio.get_running_loop()`, `asyncio.new_event_loop()` or
pytest-asyncio's `event_loop`; `asyncio.run` as a nested coroutine's run
site, deeper run chains, a consumer after a guarded
`return`, relays in loops, `except*`, module- or method-level handlers,
fixtures, a file with the dynamic access R3 lists) still report
BROAD_EXCEPT_ADDED and are asked about, in a new file too.

**uvloop.** D-187 recorded three PASS-to-BLOCK commits, `7b202ccf`,
`2081db89` and `9cba7493`, and four HIGH occurrences
([DECISIONS-archive-3](DECISIONS-archive-3.md)); [RELEASING](docs/RELEASING.md)
records the first one's fingerprint,
`BROAD_EXCEPT_ADDED/tests/test_context.py/-/ed0231ac4a64`. D-190 is expected to remove
those findings. Here that is shown only on the three commits' before and
after test files, each paired with a synthetic one-line `.pyx` comment edit
(an opaque production change), not on the full commits. On
LAPTOP-01AGNPJU, Windows CPython 3.11.9
(`HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL`), main `6a867f6d` (extracted with
`git archive`) and this change's worktree, after the fix round below, gave:

| uvloop commit | main `6a867f6d`, plain and `oracle_freeze` | this change, plain and `oracle_freeze` |
| --- | --- | --- |
| `7b202ccf` | block, 1 HIGH (`OPAQUE_PROD_CHANGE_NOT_EVIDENCE`; with freeze also `ORACLE_FREEZE`) | pass, no finding (relays before/after 0/1) |
| `2081db89` | block, 1 HIGH | pass, no finding (relays 3/4) |
| `9cba7493` | block, 2 HIGH | pass, no finding (relays 1/3) |

R29's Python set (attrs, click, flask, httpx, rich and starlette;
[RELEASING](docs/RELEASING.md)) holds no uvloop commit, so R29 cannot show
this movement. A targeted three-commit, six-call diagnostic, the v0.10.0 pyz
against 0.11 as `known-cost-010-r1` compared v0.9.0, is owed before the 0.11
tag. It runs on the final release src tree that RELEASING's candidate rule
counts, not in this PR.

**D-176 for 0.11.** D-187 accepted the three uvloop costs and D-176's
explicitly unmeasured remaining-history risk for 0.10 only. D-190 is
expected to remove the three known costs, pending that diagnostic. It does
not accept the remaining risk for 0.11: that risk is not yet accepted for
0.11, and the 0.11 release record will disposition it after R29 and the
targeted diagnostic on the final tree.

**Fix round (2026-10-29).** Two adversarial reviews of the first
implementation, Claude subagents with no external model, confirmed problems
that each reproduced on LAPTOP-01AGNPJU before the fix: dress-swallow, a
security review, seven, and drift-perf, on semantic drift, performance and
real code, five, two of them overlapping. Each is fixed and pinned:

1. The bound's form paid for a genuine swallow (both reviews): the engine
   now reads the after side's relays only (*The bound's form*, above).
   Pinned by `failure_relay_made_proven_pays_for_swallow_pos`, four
   spellings, plain and under `oracle_freeze`, in
   `tests/test_failure_relays.py`, and
   `tests/test_pre_tool_use.py::test_a_relay_made_proven_does_not_hide_a_new_swallow`.
2. R2 read lexical containment only, so a credited relay could guard a
   unit's assertion run through a helper, and with a stand-in lose it: R2
   now refuses a `try` body that reads an asserting name.
   `failure_relay_unit_helper_call_pos` and five spellings.
3. R7 trusted an `asyncio.Future` replaced through an alias, `importlib` or
   `asyncio.__dict__`. `failure_relay_aliased_asyncio_stand_in_pos` and
   seven spellings.
4. R6 trusted a loop replaced by a computed `setattr`, an alias of `self`, a
   helper's store, `vars()` in a class body or a keyword-built stand-in.
   `failure_relay_loop_set_by_helper_pos` and six spellings.
5. R3 missed a future completed through a closure cell, or through a frame
   from outside B: its dynamic-access list is now file-wide and longer.
   `failure_relay_closure_completes_future_pos` and two spellings.
6. R5 proved a consumer that a narrower handler skips or whose failure it
   drops, and one in a decorated coroutine: no handler of any kind may be on
   the walk, and C is undecorated. `failure_relay_wait_for_timeout_caught_pos`,
   `failure_relay_decorated_coroutine_pos` and seven more spellings.
7. R5 did not ask whether B's own failure reaches the test: B is not a
   generator, every read of its name is a call outside any lambda, and a
   nested B is undecorated; what that misses is open (row 171).
   `failure_relay_future_in_thread_body_pos` and five more spellings.
8. Reachability through `_unreachable_ids` on each function grew with the
   nesting depth: an Edit adding a swallow to a 610 KB chain of 90 nested
   coroutines outlasted the PreToolUse ask's 30-second deadline, so it was
   not asked about, where 0.10 asks. R5 now reads the statements before the
   consumer instead. A first version refused any `raise` before it, which
   refused one of uvloop `2081db89`'s four relays (its test opens with `if
   self.implementation == 'asyncio': raise unittest.SkipTest()`), so a
   `raise` nested in an earlier statement is allowed: with no handler on the
   walk it fails or skips the test. A `return` refuses whatever its guard.
   `test_a_chain_of_nested_coroutines_parses_quickly`.
9. A 300-term guard in the consuming coroutine raised `RecursionError`, an
   engine error on a file 0.10 analyses: the reading no longer evaluates
   guards, and a `RecursionError` leaves the handler unproven.
   `test_a_deep_guard_in_the_consuming_coroutine_is_no_engine_error`,
   `test_a_reader_that_cannot_decide_leaves_the_handler_a_swallow`.
10. Text: SPEC §4 and KNOWN-ISSUES-next listed `asyncio.run` as not read,
    but a coroutine that awaits its own future is read however it is run;
    row 171 said every dressed shape fails a condition. Both are corrected,
    the second to the named spellings, with the routes they miss listed as
    open.

**Evidence, this round** (LAPTOP-01AGNPJU, Windows CPython 3.11.9,
`HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL`, worktree on main `6a867f6d` with
this change uncommitted, 2026-10-29, after the fix round): the table above;
the findings JSON, SARIF, IR JSON, fingerprints and verdicts of all 1117
existing fixtures, plain and under `oracle_freeze`, are byte-identical on
main and on this change; the 24 new fixtures match on this change, plain
and under `oracle_freeze`, while on main all 24 block, the four negatives
being uvloop's false blocks; the status review's N1 probe (uvloop's real
`tests/test_tcp.py` plus one line `_NOTE = 'loop'`, `'asyncio.TimeoutError'`,
`'call_soon'`, `'Future'`, `import importlib` or `_N = vars()`) passes on
both. Timings, best of two on a host shared with other load: a 350 KB chain
of 90 nested coroutines parses in 0.56 seconds (0.36 on main), and an Edit
adding a swallow to it is analysed in 1.2 seconds (0.72 on main, 11.9 on
the first implementation); on a 610 KB chain the Edit takes 3.8 seconds
(2.4 on main), and the CLI PreToolUse Edit asks after 8.1 seconds; 2,000
relay-shaped handlers 60 functions deep, 2,000 tests each with a nested
relay, and 3,000 asserting helpers beside one relay parse in 1.05, 1.82 and
1.69 seconds (0.77, 1.22 and 1.32 on main). The status review measured a
first prototype at 25.5 seconds for 400 handlers sharing one future. The
prototype's 38 parse variants are the unit tests' 38, with the same
expected outcome each. After the fix round Claude ran the security review's
splicing fuzzer, extended with 43 constructs aimed at the rewritten reader,
over six seeds: 30,000 variants of a relay-shaped test parsed and were
analysed under `oracle_freeze` with no exception.

**Second review (2026-10-29).** Claude ran a read-only Gemini 4 Argon review
(agy, runner v4) of this entry's first commit, `d9fcd20b`; the run completed.
Claude checked each of its seven findings against the source and kept the
verdicts with the review packet, outside the repository. Raised by Argon and
verified by Claude:

1. The security argument above overclaimed. R2 reads parse-time units and
   same-file names only, so a fixture's returned closure, a helper from
   another file, an alias or a `functools.partial` reached from the `try`
   body is not seen, and deleting such an assertion is reported. The
   argument now rests on what 0.10 already allows: a broad handler around a
   call that holds no oracle of its own is no swallow, plain or under
   `oracle_freeze`, so such an assertion can be swallowed without any relay
   (THREATMODEL row 176, recorded under D-191, which also bounds rows 172 to
   175). SPEC §4, row 171, KNOWN-ISSUES-next and the module say so.
2. R7 trusted a patched `asyncio.Future.result`, directly or through an
   alias. `asyncio.Future`, `wait_for` and `gather` are now read only as a
   call's function, any store reached from `asyncio` refuses, and so does a
   stored `result` on any receiver (R6).
3. R3 missed a dynamic builtin read without a call (`s = setattr`,
   `w = vars`) or through `builtins`. Any read of those builtins, `getattr`
   other than called with a constant name, the names `builtins` and
   `__builtins__`, an import of `builtins` and the attribute
   `__subclasses__` now turn the file's relays off.
4. R6 counted a receiver bound to a call that reads a parameter, such as
   `me = (lambda x: x)(self)`, as fresh. The call must now read no parameter
   of the functions around the store.
5. R5 proved a consumer under `contextlib.suppress` with an aliased type, or
   under a context manager the file defines. A `with` on the walk now passes
   only when every item is `s.attr(...)` that R6 trusts as it trusts a loop,
   a context manager the test's base class provides (uvloop's
   `self.tcp_client(...)`). This also closes the earlier open route of a
   `with` whose `__exit__` suppresses, except a base class's own context
   manager, which is trusted as its loop is.
6. R5 credited a B whose own call a broad handler swallowed, and a nested B
   never called. Every call of B must now sit where nothing in its function
   can swallow it (no `try` body with a handler, no part of a `try` whose
   finally clause jumps, no `with` but the trusted kind), and a nested B must
   be called. A loop or an `if` around the call stays allowed: uvloop
   `2081db89` appends `test_client(addr)` coroutines in a loop and gathers
   them.
7. The cost was called linear. The walks up the scope chain make the worst
   case the file's size times the nesting depth of the relay's scopes; the
   measured shapes are unchanged. The fix round's fuzzer checks robustness
   only, no exception, not what is credited.
8. R2b (c) described S as a callback or a thread body that the test hands
   off, which the reading does not check: it checks only that S is nested
   in another function, and the text now says so. A unit that calls S
   itself folds S's assertions, which R2 then refuses.

Not changed: B's name is still matched anywhere in the file, which can
refuse an honest relay (a precision cost); and the multiset per first line,
whose slot reuse is 0.10's and is row 172, stays: Argon suggested keying it
by scope, a design for later. Pins: `failure_relay_future_method_patched_pos`,
`failure_relay_consumer_under_suppress_alias_pos` and
`failure_relay_b_call_swallowed_pos`, and in `tests/test_failure_relays.py`
seventeen refused spellings and three controls (a base class's context
manager, a nested B called in a loop and gathered, and `getattr` with a
constant name). On `d9fcd20b` the seventeen spellings were credited, and the
three controls were read as they are now. On the uvloop replay the relays
read stay 0/1, 3/4 and 1/3, and all three commits still pass, plain and under
`oracle_freeze`; 30,000 more fuzzed variants raised no exception. An Argon
review is not a PASS and does not replace Claude's own. The documented test
count moves to 22048 collected.

**Third round (2026-10-29).** Claude ran a second read-only Gemini 4 Argon
review, of `371b067d` (D-191) and `eee48652` (the second review's fixes);
the run completed, with four reads of files that do not exist. Claude
checked each of its nine findings against the source and kept the verdicts
with its packet. Raised by Argon and verified by Claude:

1. R2 let through an oracle call 0.10 reads in the `try` body when R2 could
   not see what it runs: a fixture's returned checker called as
   `assert_total(...)`, a helper imported from another file, an alias of
   either. The engine folds such an assertion into the unit only after the
   parse. R2 now refuses any call whose last name starts with `assert` or is
   `fail` or `raises` (`_is_oracle_call`) unless it is a method of the
   test's own receiver, such as `self.assertEqual(...)`. A cheaper 0.10 edit
   could already lose such an assertion through an alias (row 176), so this
   is defence in depth; its cost is that a handed-off callback calling an
   `assert`-named helper is no longer read, and
   `test_r2_an_assert_named_helper_call_is_refused_even_handed_off` now
   expects that, where the first commit's version of the test,
   `test_r2_a_helper_no_unit_runs_is_no_bar`, expected the relay read.
   Checked on this round's commit alone, checkwash reports that rename as
   TEST_DISABLED at high (the unit disappeared, beside a production change
   it does not take as evidence for it); on the pull request's range from
   main it reports nothing, since main never had the test.
2. R5 credited a nested B whose only call sat in its own body, and a B whose
   call a generator expression deferred to wherever it is iterated, maybe
   under a handler that swallows its failure. A nested B must now be called
   from outside its own body, and never from inside a generator expression.
3. R6 counted `s = self; me = (lambda x: x)(s)` as fresh. A name the
   functions around the store bind directly to a parameter, or to such a
   name, now counts as that parameter. A stand-in reached through other
   spellings of a call's result stays open (row 171).
4. R3 read `getattr(*(obj, name), 'default')` as a constant name; a
   `getattr` with a starred argument now counts as computed.
5. SPEC §5 clause 1 (D-191's text) now says the fingerprint normalisation
   strips string statements, value-less annotated assignments and dead
   literal bindings only as direct statements of a body, so the same
   statement inside an `if`, a loop, a `with` or a `try` changes the
   fingerprint and is Route A evidence.

Rejected, each against the source: two findings described code that is not
in the repository (a `_compose` cut in `weakening_reason`, a capped
`_stop_block_reason`), the actual reason code keeps the footer and the
count; the claim that fixture-producer evidence is gated by an
`_ASSERTION_EVIDENCE_RULES` set, and that a runtime import shadow refuses
both routes, also names code that does not exist; a module-level constant
matched by leaf name is checked for reachability by `_symbol_match`; a B
called only after a `return` never runs, so nothing is lost. Accepted as
a record fix only: the first review's triage, kept outside the repository,
listed planned actions; the *Second review* paragraph above records what
was implemented, and the triage now says so. Pins:
`failure_relay_fixture_checker_call_pos`, and in
`tests/test_failure_relays.py` six refused spellings and one control. On
the uvloop replay the relays read stay 0/1, 3/4 and 1/3, and all three
commits still pass, plain and under `oracle_freeze`. The documented test
count moves to 22056 collected.

**Not run** when this entry was written: the full suite, `tests/gates`
(the perf gate and the verdict gate among them), R29, the targeted uvloop
diagnostic, dogfood, a Claude Code hook lifecycle run, a run of the
corrected tests against the first implementation, and any other platform.
The PreToolUse tests run the CLI handler on toy repositories only.

**Test expectations.** New fixtures, labels set by Claude:
`failure_relay_callback_future_neg`, `failure_relay_thread_wait_for_neg`,
`failure_relay_nested_coroutine_future_neg` and
`failure_relay_unitless_mixin_neg` (pass); `failure_relay_never_awaited_pos`,
`failure_relay_result_set_first_pos`,
`failure_relay_gather_return_exceptions_pos`,
`failure_relay_await_swallowed_pos`, `failure_relay_await_suppressed_pos`,
`failure_relay_stand_in_future_pos`, `failure_relay_shadowed_asyncio_pos`,
`failure_relay_exception_rebound_pos`, `failure_relay_stand_in_loop_pos`,
`failure_relay_repeated_in_loop_pos`, `failure_relay_in_fixture_pos`,
`failure_relay_helper_module_pos`,
`failure_relay_made_proven_pays_for_swallow_pos`,
`failure_relay_unit_helper_call_pos`,
`failure_relay_aliased_asyncio_stand_in_pos`,
`failure_relay_loop_set_by_helper_pos`,
`failure_relay_closure_completes_future_pos`,
`failure_relay_wait_for_timeout_caught_pos`,
`failure_relay_decorated_coroutine_pos`,
`failure_relay_future_in_thread_body_pos`,
`failure_relay_future_method_patched_pos`,
`failure_relay_consumer_under_suppress_alias_pos`,
`failure_relay_b_call_swallowed_pos` and
`failure_relay_fixture_checker_call_pos` (each one BROAD_EXCEPT_ADDED at
high, `bypass: 171`). The design's `failure_relay_await_removed_pos` is not
added: under the 0.10 bound that edit passes, so it is the row-171 residual
test instead. New: `tests/test_failure_relays.py`, and five tests at the end
of `tests/test_pre_tool_use.py`. No existing expectation changed.

## D-191 (2026-10-29): #419 closes as a documented residual of E1's repair evidence

**Authority.**

- On 2026-10-19T07:03:47Z the owner ruling on #419
  ([comment](https://github.com/taipei49314/checkwash/issues/419#issuecomment-6261642679),
  「裁決總表全部照建議」) set its closing condition: "This issue closes only if
  no stop fires, the new polyglot419 blocks are rated (R21), and the Q4 docs
  PR (R22) and D-141's Sweep section, both maintainer text, merge."
- On 2026-10-28T08:34:01Z Claude asked Nelson five questions. Item 2 was
  「**#419**：擋到「誠實但確實弱化」的改動算不算誤擋；能不能用「寫清楚的殘餘」結案；Stop hook 要不要自動凍結。」
  (does blocking an honest but real weakening count as a false block; may
  #419 close with a clearly written residual; should the Stop hook freeze
  automatically). At 2026-10-28T08:41:25Z Nelson replied
  「1.核准 2.用寫清楚結案 stop hook自動凍結 3.這次統一收尾後跑 4.readme等到修復後重排 可以進版 Hook選local Doctor放寬我有點不太確定 5.這題我不太確定」
  (its line breaks and doubled spaces shown as single spaces, as in D-189
  and D-190). The first half of item 2, 「用寫清楚結案」 (close it by writing
  it clearly), is this entry's ruling.
- Claude's plan at 08:43:12Z, item 2, was
  「**#419 以「寫清楚的殘餘」結案**：把 THREATMODEL、SPEC、README、KNOWN-ISSUES、defence-design、stability 改成實際行為，記一筆決策取代你 10-19 定的結案條件，然後在 #419 留言並關閉。」
  (rewrite those documents to the actual behaviour, record a decision that
  replaces his 10-19 closing condition, then comment on #419 and close it),
  and Nelson clicked the button labelled 「開始」 at 09:05:05Z.
- At 2026-10-28T12:34:07Z Nelson clicked the button labelled
  「加 PreToolUse ask」, whose option text was
  "0.11 加 PreToolUse ask，只問五條弱化規則；先修擋下訊息和 stop_hook_active，Stop hook 凍結預設另外再議"
  (D-189). It replaced the second half of item 2, 「stop hook自動凍結」,
  with the PreToolUse ask.
- At 2026-10-28T17:33:37Z (2026-10-29 01:33 Asia/Taipei) Nelson clicked the
  button labelled 「接著做 0.11」, whose option text was
  「接著做 0.11 其他項目（uvloop 轉交辨識、#419 殘餘結案、doctor 方案 S、README 重排），順便帶上那 3 項文字修正」
  (go on with 0.11's other items, among them the #419 residual closure, and
  bring the three text fixes along).
- At 2026-10-29T14:29:31Z Nelson clicked the button labelled
  「用 C，開始改 PR-A」, whose option text was
  「用 C：認得的轉交不列 finding，並限制成不會多出 0.10 沒有的 finding；照交接檔 0a 的清單改好 PR-A 再開工」
  (D-190). The residual below describes the relay as D-190 implements it.

Claude wrote each button's label and option text, and only the label may
have been sent. These approvals cover this entry's agent-read-only edits,
listed under *Maintainer text* below. Claude maintains checkwash under
Nelson's 2026-10-27 delegation (「Checkwash 一樣給你」: 0.x autonomous, stop
before 1.0; [RELEASING](docs/RELEASING.md)). Every choice below that is not
quoted above is Claude's under that delegation, as D-189's and D-190's
were: the residual statement's wording, the three text fixes' form,
THREATMODEL rows 172 to 176, and the tests and their expectations. The
one-hop correction in SPEC §5 clause 2 and THREATMODEL item 5, and the row
4 clarification, are Claude's reading under the delegation: the residual
needs them to be accurate, no quoted approval names them, and they are not
Nelson's words. None of this is Nelson's personal review.

**Not answered by Nelson, and not decided here.** Whether blocking an
honest but real weakening counts as a false block (item 2's first
question; werkzeug `ab6150fa` is among D-171's stop commits): those commits
stay unadjudicated, and nothing here calls them honest or false. What the
2026-10-28 direction review's "ceiling" means: this entry says only that E1
can be bypassed by an author who reads the rules. Whether work on E1-class
rules stops: nothing here says it does.

**What is decided.** #419 closes as a documented residual, not a fix: this
entry changes no engine code, no repair evidence, no gating, no strength or
alignment parameter and no detector. It supersedes the 2026-10-19 closing
condition. The stop fired (2026-10-21; eleven commits in all, D-171 and
D-172), so its first condition cannot hold. `opaque419` and `polyglot419`
never ran (D-171, K2), so there are no polyglot419 blocks for the condition
to rate; R21 also names `cfjs131`'s blocks (R30), and its 55 were never
rated. C2.6 halted the Q4 arms and "No complete RC Q4 numbers are supplied
under R22" ([DECISIONS-archive-2](DECISIONS-archive-2.md), D-172). D-141's
*Sweep* section records the stop in its *Result* paragraph but no
adjudication, and an archived entry is not edited. So R21, R22 and the
*Sweep* condition are superseded by the 2026-10-28 ruling, not met. R30's
line for row 131 is not met either: THREATMODEL row 131 now records
`cfjs131`'s count, which nobody has adjudicated, and the JS/TS adjudication
stays with #212. For 0.11 this also supersedes the statements in D-176 and
D-187 that #419 remains open; THREATMODEL rows 2, 93, 130 and 131 stay
open, as accepted residuals.

**What 0.11.0 does for #419.** E1 asks whether a production change explains
a test change: D1 holds an oracle finding at warn when it has repair
evidence (`REPAIR_EVIDENCE`), E1 sets one high when it has none and nothing
else holds it, and E2 (`oracle_freeze`) then sets every oracle finding that
reaches it high. The verdict blocks at or above `fail_on`, `high` by
default. Two routes supply the evidence:

- Route B, opaque-change evidence (SPEC §5 clause 3): a byte modification of
  an existing production-role file that checkwash cannot read, other than an
  inert file in `roles.py`, an artifact, a file under a test-support
  directory, a file whose content runs a test runner, or Python the diff made
  unparseable. It is evidence for every oracle finding in the diff, and
  `AUTHORS`, `CHANGELOG`, `.coveragerc`, `docs/requirements.txt` and
  `doc/*.txt` qualify.
- Route A, symbol evidence (clauses 1 and 2; Python only): an edit the
  fingerprint normalisation keeps, `+ 0`, an added `pass` or `...`, a renamed
  parameter, a temporary or a dead branch among them, in a function the test
  calls, anywhere in a class it calls (a class's fingerprint covers its
  whole body), in a changed method or nested function that a function of a
  changed production file calls when the test calls a name equal to that
  function's own (one hop), in a production symbol that a same-file helper
  the test invokes calls (T1.9), or in the producer of a fixture the
  assertion reads, the last two not for `TEST_DISABLED`. The one hop has no
  module check; it reads the changed files in path order, so a caller
  counts only for changes in its own file or in a file whose path sorts
  before it; and a call made on another call's result, such as
  `Calc().total(items)`, is recorded as a call of `Calc` alone. A changed
  top-level function gives no one-hop evidence (#420). Every symbol route
  needs a finding with a test unit, so a finding with none takes Route B
  only.

By rule family, at the default `fail_on`:

- Python `ASSERT_WEAKENED`, `ASSERT_REMOVED`, `TEST_DISABLED` and
  `TOLERANCE_LOOSENED`: beside either route, warn and pass; alone, high and
  block.
- The Python expectation family, `ASSERT_SUBSTITUTED` and `*_PATCHES_*`: held
  at warn by Route B (row 130), and by Route A when the finding has a test
  unit. A finding with no unit takes Route B only: `CONFTEST_PATCHES_PROD`
  has none, so beside a kept no-op in the function the conftest patches it
  is high (`PROD_CHANGE_NOT_EVIDENCE`) and blocks.
- Python `BROAD_EXCEPT_ADDED` in a test or conftest: the detector gives the
  finding no unit, so Route A never reaches it, and D-176 refuses it Route B,
  so it is high and blocks beside any production change
  (`OPAQUE_PROD_CHANGE_NOT_EVIDENCE` beside an opaque edit,
  `PROD_CHANGE_NOT_EVIDENCE` beside a Python one). A proven failure relay is
  not counted as added, within 0.10's count (D-190, row 171); an honest relay
  the rules do not read, in a new file or an existing one, still reports, is
  asked about and blocks, as D-190 lists. Rows 172 to 176 name five
  spellings that 0.10 already misses.
- Python conftest suite controls: an unguarded one refuses all evidence and
  blocks (`COLLECTION_CONTROL_UNEXPLAINED`); one guarded by an `except` that
  D6 cannot read takes Route B; one guarded by an `if` that can be false is
  held at warn with or without a production change: by `COMPAT_GATE`, which
  is no #419 route, or, beside an opaque edit, by `REPAIR_EVIDENCE` first.
- JS/TS tests: every rule keeps Route B, the broad catch included, because
  D-176's refusal needs a Python file, and checkwash reads no JS/TS
  production code, so an edit to any existing JS/TS module qualifies. There
  is no Route A (row 131).

What does not rest on E1 ([enterprise checklist §7](docs/enterprise.md#7-hardening-against-bought-repair-evidence-419)):

- `fail_on = "warn"` blocks every warn finding. In the Action it is the
  `fail-on` input: the Action always passes `--fail-on`
  (`action/secure.py`), which overrides `gate.fail_on` in the base config,
  and `gate.fail_on` applies to CLI runs without the flag and to the Stop
  hook. `checkwash doctor` proves only a checkwash step with `uses:` and no
  `with:` (`doctor.py`), so a workflow that sets `with: fail-on: warn`
  reports "WARN workflow analysis incomplete" and doctor exits 1. That is
  expected in 0.11, and doctor is not changed; whether doctor should accept
  a stricter `fail-on` is a question for Nelson. A pull request that lowers
  its own workflow's `fail-on` shows only `CI_WORKFLOW_TOUCHED` at warn.
- `oracle_freeze: true` through CLI `--task`, with the contract committed
  at the base (SPEC §4c), blocks beside either route. The Action has no task
  input, and the managed hooks pass no `--task`. A task file the base does
  not hold is read from the working tree, which the change controls.
- The D-189 PreToolUse ask, on local installs, judges each Claude Code
  Edit, Write or MultiEdit of a Python test or conftest alone with
  `oracle_freeze` forced, so neither route lowers its five rules at high.
  It does not cover pull request checks, the Action, edits through Bash,
  NotebookEdit or an MCP tool, JS/TS tests, the other rules, allowlisted
  findings or ones held at info, input over 8,000,000 bytes or not complete
  within 10 seconds, edits it cannot predict, and, under the default
  `pass_with_warning`, engine errors and the 30-second deadline. A new file
  has no units for the four unit-scoped rules, but a swallowing broad
  `except` in it (unless a proven relay), suite controls in a new
  `conftest.py` and an oversized side are still asked about. The Stop hook
  applies no freeze, so it passes what either route holds.

**Why.** Against an author who reads the rules, an edit chosen to change
nothing meets any static criterion a real edit meets, and 419.Q3 ruled out
fold lists for that reason (row 93): E1 can be bypassed by such an author.
The narrowings tried so far were priced only on commits that nobody has
adjudicated: #464's five-rule refusal fired its pre-registered stop on
eleven commits (D-171, D-172), and the report-only `cfjs131` arm, which
refused opaque evidence to JS/TS tests, moved 55 of #212's 1,800 commits
pass → block on the RC engine `141acceef` (D-172). The routes that do not
rest on E1 are the three above, each at a cost the user chooses, and the
required check stays the gate and lists the warn findings in its report.

**Costs.** D-187 accepted, for 0.10 only, D-176's three known uvloop false
blocks (three commits, four HIGH occurrences) and its explicitly unmeasured
remaining-history risk. D-190 is expected to remove the three, pending the
targeted three-commit diagnostic on the release tree. The remaining risk is
not yet accepted for 0.11; the 0.11 release record will settle it in a
separate delegated disposition. The hardening costs in enterprise §7 are
archived rows of the v0.9.0 combined sweep: the RC engine `141acceef`
blocked 48 of 1,800 in-sample commits (attrs, click, flask, httpx, rich and
starlette, 300 each), and its two Q4 variant arms recorded 615 with
`--fail-on warn` and 127 with a base-side `oracle_freeze` contract. Both
arms were halted under C2.6 with their rows archived, so the counts are not
a result and not the pre-registered Q4 numbers, nothing in them is
adjudicated, and none was measured on 0.11. Claude recomputed each from
the sweep result files (`v090-call1/standard` and `v090-call3/standardx`
aggregates; `v090-call4/combined/combined.json`, SHA256
`b9946817dacdcbd9ebec052e0910e1e2e30aa7dd0dc3e0e04e145d6d68e9e2db`, which
lists the halted arms) before quoting it.

**Text fixes** (the three of the 「接著做 0.11」 option text).

1. STATE.md: the 2026-10-28 section's status recorded PR #576 as
   implemented on its branch. It now records the merge (`6a867f6d`, GitHub
   mergedAt 2026-10-28T16:54:42Z), the full suites on `f4253f7c` and
   `ad3f0bac`, and the PR's PJU receipt.
2. Hook input the PreToolUse hook does not read: input over 8,000,000
   bytes, or not complete within the 10-second wait, gets `{}` before any
   policy is read, even under `on_engine_error = "block"` (`pretool.py`,
   `session.py`, `cli.py`), as SPEC §9's input bullet now says. THREATMODEL
   row 169 and KNOWN-ISSUES-next say what that leaves to the Stop hook.
3. Strength ranks read as values: in the D-189 lifecycle receipt Claude
   restated `EXACT_VALUE(90)` as an expected value of 90.
   `pretool.evidence_clause` adds the assertion's source text to both hook
   reasons, ` (before: <text>; after: <text>)` for `ASSERT_WEAKENED` and
   ` (before: <text>)` for `ASSERT_REMOVED`, each side with its whitespace
   collapsed, cut to 120 characters and escaped as `_shown` escapes; every
   other rule gets nothing, since `BROAD_EXCEPT_ADDED`'s handler line and
   `TOLERANCE_LOOSENED`'s tolerances are already in their messages. In the
   ask the named findings' own text comes first, their clauses are added in
   order while the 1,200-character reason fits, and a cut keeps `; and N
   more`, which the old cut could drop. In the Stop reason only the clause is
   escaped and cut, so the rest is D-189's text byte for byte. Claude's
   choices: this form over dropping the ranks from the finding message,
   which would change about a dozen existing test expectations; the in-order
   fitting; the cut that keeps the count; a cap counted in source characters
   before escaping; and whitespace collapsed inside string literals, for
   display only. The finding message, the term, JSON and SARIF reports, and
   the Stop hook's session note and released-stop note still show
   NAME(rank). The clause has not been re-observed in a hook lifecycle run,
   and each such run needs the maintainer's prior approval; SPEC §9's
   receipt sentence is scoped to the reason as head `f4253f7c` gave it.

**Residuals** (THREATMODEL item 4; rows 2, 93, 130, 131, 169 and 172 to
175; KNOWN-ISSUES-next):

- Route B, with the cheap metadata files: `AUTHORS`, `CHANGELOG`,
  `.coveragerc`, `docs/requirements.txt` and `doc/*.txt` stay opaque
  evidence. Making them inert would narrow E1 and move verdicts, which this
  entry does not do, and no issue is opened for it.
- Route A, with the one hop as implemented: by leaf name with no module
  check, only for changes in the caller's own file or in files whose paths
  sort before it, not through a call made on another call's result, and
  none for a changed top-level function (#420, closed as not planned on
  2026-10-18 and deferred until after 1.0 in #504). THREATMODEL row 93 no
  longer says #420 will land.
- JS/TS Route B, until #212.
- The PreToolUse ask's scope, above, and the input it does not read (row
  169).
- A workflow that sets `with: fail-on: warn` is not proven by doctor.
- Five `BROAD_EXCEPT_ADDED` routes that 0.10 already misses, the first
  four found by D-190's security review, all reproduced through
  `analyze()`, plain and
  under `oracle_freeze`, on D-190's commit `d9fcd20b` and on main
  `6a867f6d`, with no finding: a base swallow that stops counting (a
  trailing `raise`, or its assertion moved to `else`) pays for a new swallow
  of the same first line (row 172); `except Err:` with `Err = Exception`
  (row 173, a spelling of the aliased-exception residual row 91b already
  names); a broad handler whose only `raise` sits in a nested def (row
  174); a non-broad exception raised before the assert in the `try` body
  and caught (row 175); and a broad handler around a call that reaches an
  assertion, whose guarded block holds no oracle of its own (row 176),
  which Claude found while checking a Gemini 4 Argon review of D-190 and
  which bounds what a dressed failure relay can lose. No engine change
  here, and no issue is opened.

**Maintainer text** (agent-read-only edits under this entry): SPEC §4's
`BROAD_EXCEPT_ADDED` bullet (its JS/TS clause only), §5 clauses 1 to 3, and
§9 (the input bullet, the block reason, the ask, the receipt sentence and
the not-verified list); THREATMODEL items 4 and 5 (the latter's one hop),
rows 2, 4 (one clarifying sentence; still Closed), 68 and 87 (wording), 93,
130, 131, 165 (new files) and 169, and new rows 172 to 176; and this
entry. D-190's own text, SPEC §4's relay text and THREATMODEL rows 16 and
171 are unchanged.

**Contracts.** No fingerprint, `FINDINGS_VERSION` (2), `IR_VERSION` (3),
verdict, severity, escalator, de-escalator, `.gwcase` or `tests/gates`
change. Only the two hook reasons change, by the assertion clause; the
finding `message`, JSON and SARIF are unchanged.

**Tests.** New: `tests/test_issue419_residual.py`, which pins the routes,
blocks and hardening of the statement above in-process, and 32 tests at the
end of `tests/test_pre_tool_use.py`: the evidence clause (24), new files
(4), bought evidence (2), and input over the cap or cut off (2). Four of
the new tests are residual pins of row 93:
`test_residual_row93_one_hop_matches_leaf_name_in_any_module`,
`test_residual_row93_one_hop_reads_callers_in_path_order`,
`test_residual_row93_a_call_on_a_call_result_gives_no_hop` and
`test_residual_row93_issue420_top_level_callee_gives_no_hop`. Five more
(`test_residual_row172_...` to `test_residual_row176_...`) pin the new rows.
A fix of #420, of the one hop's module check, path order or call reading,
or of one of those routes changes its expectation as a recorded change. No
existing expectation or fixture changed. The documented test count moves to
22025 collected.

**Evidence and NOT_RUN.** LAPTOP-01AGNPJU, Windows CPython 3.11.9,
`HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL`, 2026-10-29 UTC, on D-190's commit
`d9fcd20b` with this change uncommitted. Reproduced on toy repositories,
through `analyze()` or the CLI: each rule family's outcome above, alone and
beside each route; the one hop's limits and the T1.9 hop; the conftest
controls; `CONFTEST_PATCHES_PROD` beside both routes; `fail_on = "warn"`,
`gate.fail_on = "warn"` in the CLI and the Stop hook, and `--fail-on`
overriding it; the `--task` freeze and a task file only in the working
tree; a pull request that lowers its own `fail-on`; the doctor outcome; the
assertion clause in both hook reasons; the PreToolUse ask beside bought
evidence and on new files; hook input over the cap (one Edit and one Write
probe) or cut off; and the five routes of rows 172 to 176, which also pass
on main `6a867f6d`, extracted with `git archive`. By reading only: that the
Action always passes `--fail-on` (`action/secure.py`), that it has no task
input and the managed hooks pass no `--task`, the `oracle_freeze`
exceptions, the MultiEdit over-cap case, and the PreToolUse ask's scope as
D-189 gives it (NotebookEdit and MCP tools, allowlisted and info-held
findings, and engine errors and the 30-second deadline under
`pass_with_warning`). By arithmetic, with the one Write probe: that a Write
over the input cap carries a file over the source limit. Targeted runs on
that worktree, each exiting 0: the new residual tests,
`tests/test_pre_tool_use.py` and `tests/test_issue419_narrow_broad_except.py`
(200 passed); `tests/e2e/test_cli.py` and
`tests/test_issue418_session_base.py` (64); the seven other test files that
read the Stop reason (215) and five that check its block decision (180
passed, 13 skipped); the golden runner (1143); the THREATMODEL, STATE,
link, published-source, SPEC, oracle-rule, schema and
documentation-contract tests (67); and `tests/test_packaging.py` (10), the
documented count included. `benchmarks/FAILURES.md` is regenerated. Not
run: the full suite, `tests/gates`, R29, the targeted uvloop diagnostic,
dogfood, a Claude Code hook lifecycle run, any sweep or new arm, and other
platforms.

**#419** is closed after this change merges, with a comment that links
this entry.

## D-192 (2026-10-31): a lone `pytest.raises` carrier is proved like an assertion, D5 takes files that lost no oracle mass, and cells that never reach the test are not substituted

**Authority.**

- At 2026-10-30T19:35:44Z talhayme, an outside contributor, reported on
  #130 ([comment](https://github.com/taipei49314/checkwash/issues/130#issuecomment-6531871133))
  a reduced honest refactor that PyPI 0.8.0 passes and 0.10.0 blocks: two
  `pytest.raises(ValueError)` tests, for the inputs -1 and 101, folded into
  one literal two-row `parametrize`, beside an equality test folded into a
  one-row table, with production unchanged. With only the two raises tests,
  0.8.0 already blocks one disappearance and 0.10.0 both. The report
  proposed no detector patch or policy change, and asked whether the case
  should be pinned as a known-limit control or kept as outside evidence
  beside #567's D-179 costs.
- At 2026-10-31T04:09:28Z Nelson handed it to Claude: 「接手checkwash 有一則外部誤報」
  (take over checkwash; there is an outside false-block report).
- At 2026-10-31T06:49:09Z, with this change open as draft PR #578, Claude
  asked 「要核准 D-192，跑收據後代合，並回覆回報者嗎？」 (approve D-192, merge
  after the receipt, and reply to the reporter?). At 07:11:25Z Nelson
  clicked the button labelled 「核准並代合」 (approve and merge), whose
  option text was
  「核准 D-192 進 0.11：跑 PJU 收據，4 個必要檢查綠了就代合 #578，合併後在 #130 貼回覆（用 reply-130.md 的草稿）」.

Claude maintains checkwash under Nelson's 2026-10-27 delegation
(「Checkwash 一樣給你」: 0.x autonomous, stop before 1.0;
[RELEASING](docs/RELEASING.md)), whose continuation instruction covers
"completing the remaining core repairs and their necessary protected
contracts". Every choice in this entry is Claude's under that delegation,
as D-176 to D-187 were Codex's: the carrier's bounds, the D5 candidate
change, the four substitution refusals and the function-kind binding,
which take the reviews' findings, the agent-read-only text listed
under *Maintainer text*, the fixtures and their labels, and the tests and
their expectations. Claude wrote the question, the button's label and its
option text, and only the label may have been sent. That approval covers
this entry's agent-read-only edits, listed under *Maintainer text*, and the
merge. None of it is Nelson's personal review.

**Diagnosis.** D-179's Python proof (`oracle_credit._python_context`) built a
per-row context key only for a top-level `assert` statement and stopped at
the first statement of any other kind ("No text-only credit through unknown
control flow"). The frontend records `pytest.raises(...)` as an assertion
(form `raises`, or `pattern` with `match=`), but its `with` statement
stopped the walk, so it never had a key, `assertions_proven` was false for
every unit holding one, and no route could pay for its disappearance. The
equality test beside it was proved, which is why it stayed at warn.
Separately, a raises carrier without `match=` has no strength, so it adds
no D5 oracle mass, and `_file_restructured` only judged files whose
disappeared units lost some mass: a file that lost only such units was
never a D5 candidate, and the text route pays one disappearance per
arriving assertion text, not per row. That second gap is why the smaller
form blocked one test on 0.8.0 and 0.9.0 too. Neither is a boundary D-179
chose: it names "unsupported control flow" as a limit, and a lone raises
carrier around simple statements is a statement the proof can bind
exactly. 0.8.0 and 0.9.0 passed the report through the text and mass routes
D-179 removed, which also passed weakened folds: on 0.9.0, a fold that
broadens `ValueError` to `Exception`, drops the 101 row or changes it to
1000 passes.

**What is decided.**

1. *Raise carriers.* A `with` statement whose only item is a call written
   `pytest.raises(...)`, `pytest.warns(...)` or a bare `raises(...)` (the
   spellings the frontend records), bound `as` a plain name or not, whose
   body holds only expression statements, assignments (plain, annotated or
   augmented) and `pass`, is proved like an `assert`: for each literal
   parameter row, its key binds the unit scope, the concretized prior and
   following statements and the whole concretized `with` statement, so the
   expected exception, any `match=` or other argument and every statement
   inside it. It then joins the prior context of later statements, so an
   assertion on `excinfo` after it is proved too. Every other `with`
   statement (unittest's `with self.assertRaises(...)` among them), a
   second item, control flow inside the block and `async with` still stop
   the walk, and the call forms `pytest.raises(E, f, x)` and
   `self.assertRaises(E, f, x)` still get no key.
2. *D5 candidates.* A test file that lost units but no oracle mass is a D5
   candidate with a zero budget when a live unit also arrived in it. D5
   still requires `_proven_restructure`: every own assertion of the
   disappeared unit proved, with spendable credits from live arrivals; a
   disappeared unit with no own assertion gets nothing. Files that lost
   mass are judged as before. The in-file arrival keeps D5 a restructure:
   without it, a zero budget would have let D5 pay for a fold into another
   file with credits from that file, which a fold of strong tests cannot
   get (its file must cover the mass it lost) and which is D2's to judge as
   a move. The contract review raised it.
3. *Cells that never reach the test.* The proof substitutes each literal row
   for every read of its column's name and treats as live every row the
   frontend does not prove skipped. D-192's review found three ways for the
   key to read the cell while the test runs something else, each older
   than the carriers for `assert` statements and inherited by them (row
   178). A unit now gets no assertion keys when its parametrize is
   `indirect` (the keyword, the third positional argument or a `**`
   mapping), when its body binds a column's name anywhere (`_rebinds`:
   assignment, `del`, `as`, loop, comprehension and walrus targets, nested
   and lambda parameters, imports, `global`, `nonlocal`, handler and match
   captures), or when a row carries marks that `_param_row_disabled` does
   not prove skipped. Its complete-unit key is unchanged.
4. *Two more found by the Gemini 4 Argon review* (raised by Argon,
   verified by Claude; both older than the carriers, for `assert`
   statements too, and in row 178). A unit that reads a column more than
   once while a row's cell holds a list, dict or set gets no assertion
   keys: each read is one shared object, which a call can mutate, where the
   literal it replaced was a fresh object at each place; the table
   projection already refuses repeated row references for this reason. And
   an `async def` test's assertion keys carry its function kind: a plain
   `TestCase` never awaits an async method, so its assertions never run,
   and pytest without a plugin skips or fails it. Synchronous keys are
   byte-identical to before; async-to-async folds keep their credit.

All four keep D-179's contract: a credit still needs a bounded two-sided
proof of the same static obligations, each arriving row pays once across
every route, assertion-only credit still reaches E2 under `oracle_freeze`
(the reported fold blocks under a `--task` freeze on main and here), and
mass, text and names remain candidates only.

**Review.** Six agents, read-only outside their own directories, built
synthetic two-commit repositories and ran main `c06b10d3`, the carrier
alone and the carrier with the D5 change on each, with pytest on both sides
against the correct implementation and mutants for ground truth: four
attack lenses (the carrier's spellings, row substitution, the zero-mass D5
candidate, credit accounting across routes), one lens of honest refactors
and a contract review; each claimed new false negative went to an
independent verifier that rebuilt it from its files. Every weakening of the
carrier itself blocked on all three engines. The lenses claimed 20 new
false negatives and the verifiers confirmed all 20. Seventeen are the
three gaps of decision 3 (six through a rebound column or `as` target, two
through `indirect`, nine through rows whose marks keep them from running),
reached by several lenses and already open for `assert` folds on main. The
other three are row 179 (arrivals in files the repository does not
collect, or under a name a standing `-k` deselects). The contract review
raised the cross-file reach of the zero budget, which decision 2's in-file
arrival removes. Claude reran every case on the final branch: 19 of the 20
block, the remaining one is row 179's `-k` rename, every other real
weakening blocks, and every honest case keeps its verdict on the carrier
with the D5 change, except the two folds into another file, which block as
on 0.10.0.

A Gemini 4 Argon review (agy, read-only, on the diff and a snapshot of
main) then returned eight findings. agy updated itself from 1.4.10 to
1.4.12 during the run; the new binary was re-verified (signature, flags and
a read-guard test) before the review was counted. Claude checked each
finding against the source and by running cases: two were real and are
decision 4, the alias tautology and the `async def` move, each passing on
main and here before the fix; one is wording (row 179 now names both
spellings of a row id); one adds a residual (a raises table beside a loop
fold, below); three were rejected, two of them resting on code that does
not exist; and its audit of the claims misquoted two numbers from the
evidence. The triage is kept with the review's receipts.

**Measured** (LAPTOP-01AGNPJU, `HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL`,
Windows CPython 3.11.9, 2026-10-31).

- The report, rebuilt from its five files (a two-commit repository, root
  `app.py` and `test_app.py`, `checkwash check HEAD~1..HEAD --format json`):
  v0.8.0 and v0.9.0 exit 0, pass; v0.10.0 and main `c06b10d3` exit 1, block,
  with `TEST_DISABLED/high` and `NO_PROD_CHANGE_IN_DIFF` on `test_negative`
  and `test_large` and `RESTRUCTURED` warn on `test_ok`; this change exits
  0, with `test_large` at info (`ASSERTION_MOVED`) and the other two at warn
  (`RESTRUCTURED`), as on 0.8.0. pytest 9.1.1: both sides pass 3 on the
  correct implementation and fail 2 of 3 with the range check removed.
- The smaller form (the two raises tests alone) passes, with `test_large`
  at info and `test_negative` at warn; v0.8.0, v0.9.0, v0.10.0 and main
  block it, and so did the carrier without the D5 change.
- A same-host differential over the 3,600 members of 0.10.0's R29 sample
  (members file SHA256 `f6281caa...`, with the same-host differential
  script Claude used for 0.10.0's review fixes, 16 workers): each member
  checked once with main `c06b10d3`'s `src/`
  (tree `b52df5f2`) and once with this change's `src/`, exit code and whole
  report compared except run metadata. 3,600 identical, 0 different; exits
  3,493 pass, 105 block and 2 errors on both sides; 2,266.9 s. The sample
  holds no fold this entry credits or refuses, so it measures no cost and no
  catch either way: what it shows is that nothing else moved.
- The full suite (`pytest tests`, `tests/gates` included, xdist `-n 4`): a
  JUnit file whose testsuite counts `tests="22170"`: 22103 testcase entries,
  22078 passed and 25 skipped, plus 67 subtests, with 0 failures and 0
  errors.

**Residuals.** Honest folds that still block at high, as on 0.10.0 (the
review confirmed each with pytest): a fold into a `for` loop or unittest's
`subTest`; unittest's `assertRaises`; the call form; a second item, another
context manager or control flow in the `with`; one test holding two raise
carriers folded into rows, whose keys bind each other as prior and
following statements; a cell that is not a literal (an exception class, a
module constant); an f-string `match=`; the subject call moved into a
helper; the `from pytest import mark` / `@mark.parametrize` and
`import pytest as pt` spellings; list-form argnames; a fold into another
file, which D2's text route moves one test of and D5 no longer takes
(decision 2); a fold in place while a strong test moves out of the file,
which leaves it short of D5 mass; a literal-table loop fold in the same
file as a parametrized raises fold, which the table projection then does
not credit (on main too); and, since decisions 3 and 4, an honest fold
through `indirect`, a rebound column, a marked row or a mutable cell read
twice, or one moved between `def` and `async def`, for `assert` folds too.
KNOWN-ISSUES-next lists them.

One gap stays open, older than this entry, and this entry extends it
(row 179): arrival liveness reads pytest's default collection patterns and
the unit's own markers, not the repository's resolved collection settings.
On main `c06b10d3` a test moved unchanged into a file outside
`python_files` or into a `collect_ignore` file still earns the
complete-unit move credit, and an `assert` fold whose row a standing `-k`
in `addopts` deselects by id still passes. With decisions 1 and 2, a raises
fold kept in its file joins the last: under a test name or a row id such a
`-k` deselects, it still pays, where main blocked it for want of any
proof. The review and Claude reproduced each shape, with pytest reporting
the file uncollected or the test deselected; the review's verifier rated
the `-k` rename low. Closing it means reading `collection_inventory`'s
resolved settings in the liveness path of every arrival route, a change of
its own, not made here. It needs a selection already standing in the
repository's configuration, and it was already open for every other moved
oracle, while the false block this entry removes is common, the report's
own fold among them.

**Maintainer text** (agent-read-only edits under this entry): SPEC's D5 row,
its oracle-mass and strong-assertion bullets, and a raise-carrier and a
substitution paragraph in *Oracle-context proof in IR3*; THREATMODEL row 92
(a `pytest.raises` paragraph appended), a row in its table of false blocks,
and new rows 177, 178 and 179; and this entry.

**Contracts.** No fingerprint, `FINDINGS_VERSION` (2), `IR_VERSION` (3),
finding field, escalator, de-escalator or severity-table change; no existing
`.gwcase` expectation and no `tests/gates` change. Verdicts move only where
a proof now exists (decisions 1 and 2), or where a substituted row or a
function kind did not match what runs (decisions 3 and 4).

**Tests.** New: `tests/test_raises_carrier_oracle_credit.py` (38 tests,
three of them residual pins of row 179) and nine fixtures: the report's
two forms, credited to talhayme (`raises_carrier_fold_neg`,
`raises_carrier_pure_fold_neg`), two tampering controls for row 177
(`raises_carrier_fold_broadened_pos`, `raises_carrier_fold_row_dropped_pos`)
and five for row 178 (`param_indirect_cells_pos`,
`param_column_as_target_pos`, `param_row_marks_not_run_pos`,
`param_mutable_cell_read_twice_pos`, `async_def_moved_assertion_pos`). The
credit is in both report fixtures' headers, `benchmarks/external-credits.json`
and the regenerated `benchmarks/FAILURES.md`.

## D-193 (2026-10-31): a Python arrival pays only where the repository's own pytest configuration collects it, and a rename out of that collection is a disappearance

**Authority.**

- D-192 left THREATMODEL row 179 open: arrival liveness did not read the
  repository's resolved collection settings.
- At 2026-10-31T08:13:27Z, after D-192's merge, Claude asked
  「要接著在這裡做 row 179 嗎？」 (continue with row 179 here?). At 08:28:44Z
  Nelson clicked the button labelled 「接著做 row 179」 (continue with row
  179), whose option text was
  「接著在這裡做 row 179：讓 arrival 的 liveness 讀 repo 自己的 python_files、collect_ignore 和 addopts 的 -k 選取，做完開 PR」
  (do row 179 here: make arrival liveness read the repository's own
  `python_files`, `collect_ignore` and the `-k` selection in `addopts`, and
  open a PR when done).
- At 2026-10-31T11:42:28Z, with this change open as PR #579, Antigravity
  (taking over the session from Claude) asked
  「PR #579（D-193，關閉 THREATMODEL row 179）已開立並完成本機驗證，是否核准執行 PJU 收據流程並合併？」
  (PR #579 is open and locally verified; approve running the PJU receipt flow
  and merging?). At 12:01:36Z Nelson selected the option
  「(Recommended) 核准合併 PR #579：照流程跑 PJU 收據、讓 4 個必要檢查變綠後以 merge commit 合併 into main」
  (approve merging PR #579: run the PJU receipt flow and merge into main with
  a merge commit once the four required checks are green).

Claude maintains checkwash under Nelson's 2026-10-27 delegation
(「Checkwash 一樣給你」: 0.x autonomous, stop before 1.0;
[RELEASING](docs/RELEASING.md)), whose continuation instruction covers
"completing the remaining core repairs and their necessary protected
contracts". Every choice in this entry is Claude's under that delegation:
what the reading covers beyond the three settings the option text names,
what it leaves unknown, the agent-read-only text listed under *Maintainer
text*, the fixtures and their labels, and the tests and their expectations.
The assistant wrote the questions, the buttons' labels and their option text,
and only the label may have been sent. The second click approves this entry's
agent-read-only edits, listed under *Maintainer text*, and the merge. None of
it is Nelson's personal review.

**Diagnosis.** The arrival credits of D2, D5 and D10 count only live
arrivals: `oracle_credit.arrival_credits` skips a unit that is not live, the
engine clears a dead arrival's proof keys, and the text and whole-unit
routes of the engine's move loop count only live arrivals. For a Python
unit, live meant `compat.unit_is_live`: every marker on it is a qualified
compat gate. Nothing asked whether pytest collects the unit at all. The
engine parses units only in files pytest's default patterns collect
(`roles.collectable`), and the D-179 proof's startup key binds the conftest
chain's and package initializers' bytes, not the root config or the
arrival's path. So a test moved unchanged into `app_test.py` under
`python_files = test_*.py`, into a file a conftest's `collect_ignore` names,
outside `testpaths`, beneath an `--ignore`, `--ignore-glob` or
`norecursedirs` entry, under a `--deselect`, with a `python_functions`
pattern it does not match, or under a `-k` in `addopts`, still earned the
move credit. On main `3d115a35` each of these ten shapes passes with
`ASSERTION_MOVED`. Renames had the same blind spot: `_expand_renames` splits
a rename that leaves collection into a deletion and an addition, but judged
a Python path by pytest's default patterns alone, so `git mv test_app.py
app_test.py` under `python_files = test_*.py` kept every unit aligned and
reported nothing, on main and here before this change, while pytest ran no
test at head.

**What is decided.**

1. *Arrival collection.* A Python arrival in a judged test file, a unit
   with no base side or one that gained assertions, is live only where the
   head's configuration collects it for a targetless `pytest` run from the
   repository root (`arrival_collection`), the run a required check makes
   when it calls plain `pytest`, read as pytest 9.1.1 reads it:
   - *the configuration:* the root config `locate_config` finds, in its
     order, loaded as `load_config_dict_from_file` loads it: iniconfig's
     rules for `.ini` and `.cfg` files (a header with a comment, `key:
     value`, continuation lines, inline comments kept), tomllib for `.toml`
     files (native `[tool.pytest]` tables included), the section each file
     holds, and each later config file loaded too, as pytest loads it. Each
     setting is split as `Config._getini` splits an `args` value, and the `-o`
     overrides in `addopts` apply after it. Options come from `addopts`
     alone, parsed as pytest's argument parser parses them, combined short
     options included, never from runner commands elsewhere in the file;
   - *names:* `python_files` is a glob over the file's name, or, for a
     pattern with a slash, over pytest's absolute path, which decides only
     where every checkout depth agrees; `python_functions` is a prefix or a
     glob over the test's own name; and, once configured, `python_classes`
     over the names of the classes that hold it, where a class with a base
     spelled `...TestCase` is taken for a TestCase, which pytest's unittest
     plugin collects whatever its name, and any other base is unknown;
   - *initial paths:* the `addopts` targets, node ids included, or else
     `testpaths` expanded as `glob.iglob` expands them, with pytest's
     fallback to the root when no testpath exists, normalized as pytest 9
     normalizes collection arguments (the outermost of overlapping ones is
     kept). A word naming no path is an unknown option's value, as #173 reads
     it, and so is a directory holding no test module. A test in a file a
     node id names is collected only where the node id selects it. A word
     after a long option the reading cannot place (pytest 9.1.1's own flags
     are listed) may be that option's value, and leaves the initial paths
     unknown;
   - *what leaves a path out:* `norecursedirs` and pytest's virtual
     environment rule (`pyvenv.cfg`, `conda-meta/history`) for each
     directory below the initial path; the `--ignore`, `--ignore-glob` and
     `--deselect` in `addopts`, a prefix every node id of a file starts
     with deselecting the file; and the conftest lists, where each path is
     judged by the nearest conftest above it that binds each list. An entry
     the module adds under a condition, in an arm of a conditional
     expression, or that a later binding which may not run would replace, is
     only possible; a later binding that always runs replaces the list.
     `--noconftest`, `--confcutdir` and `--collect-in-virtualenv` switch these
     off as pytest does. pytest never asks whether to ignore an initial path
     or a directory above one.

   A file the diff changes is read on its head side and any other from the
   strict snapshot, a root config that is a link through the config
   evidence, which follows it as pytest does. Reads are batched and happen
   only when a test disappeared or lost an assertion; the inventory is
   listed only for a decision that needs it (a target in `addopts`, or an
   arrival outside every testpath), because a working tree's listing walks
   the tree whole. Names match by POSIX case rules, as the rest of the
   collection reading does.
2. *Unknown pays nothing.* An arrival is not live when the reading cannot
   decide:
   - a `-k` expression in `addopts`: no keyword expression is evaluated, so
     the selection the option text names withholds every Python arrival's
     credit, while a file is still decided;
   - an `@` argument file; an option under which no test runs or only a
     cached selection does (`--collect-only`, `--setup-only`,
     `--setup-plan`, `--fixtures`, `--markers`, `--lf`, `--sw` and the like);
     `--pyargs`, `-c`, `--keep-duplicates`, a `--rootdir` other than the
     root; a `-p` plugin load,
     `-p no:python` or `-p no:unittest`; a combined short option the reading
     does not know; a target outside the repository; an absolute ignore or
     `norecursedirs` pattern; a configuration pytest itself refuses; a file
     that cannot be read;
   - a conftest in the chain that pytest cannot import, or that may define a
     hook or load a plugin (a `pytest_` name, a star import, `exec`, `eval`,
     `globals()`, `vars()`, `__dict__`): its `pytest_ignore_collect` can
     collect or leave out any path, so nothing is decided under it. A list a
     conftest binds or changes in a way the reading does not follow (a
     non-literal value, a function that changes the module's list, `global`,
     an attribute, a keyword or the name as a string) leaves only that list
     unknown.
3. *What needs no reading.* `-m`: a proved unit's decorators can only be
   `parametrize`, `skip`, `skipif` and `xfail`, a module or class mark leaves
   the module context unproved, and a row's marks withhold its keys (D-192).
   `python_classes` at its default needs none either: a class's name, bases
   and body are in the proof key on both sides. Configured, it is read
   (decision 1): a first configuration is only a warning, so a
   `pytest.ini` created beside a moved class test could stop collecting the
   class while the key stayed the same.
4. *D10 survivors.* A surviving copy outside the diff counts only where the
   same reading collects it.
5. *Renames.* Each answer is collected, not collected or unknown. A credit
   needs "collected"; a finding needs "not collected". A Python rename that
   pytest's default patterns keep collecting, whose new path the head
   configuration certainly leaves out while it does not leave out the old
   one, is split into a deletion and an addition, as a rename out of the
   default patterns already was, so its tests are disappearances and the
   added half's units are arrivals that pay nothing. An unknown answer keeps
   the default reading. A `-k` leaves every test unknown and every file
   decided, so a rename out of `python_files` is still caught beside it.

The routes are unchanged: a credit still needs D-179's two-sided proof, each
arriving row pays once across every route, and assertion-only credit still
reaches E2 under `oracle_freeze`. An arrival the reading leaves out only
loses credit, and a rename the reading cannot decide keeps its old reading;
nothing is added.

**Review.** Five agents, read-only outside their own directories, each took one
lens of the first version: collection semantics, conftest forms, engine credit
routes, honest refactors and robustness. They built synthetic two-commit
repositories, ran main `3d115a35` and the branch, and checked every case
against what pytest 9.1.1 collects or runs. The engine-routes agent stopped
before running anything (part of its work was withheld by a safety filter),
so that lens ran again as a workflow: five finders, one per route group (the
D2 routes, D5 and split/rename, D10, the rename split, the head overlay),
each followed by an independent verifier that rebuilt every reported case.
They found arrivals the first version still paid for while pytest ran them
nowhere, every one through a configuration spelling or an option its
line-based reader did not see, and all paid on main too; and over-reading
that blocked honest changes main passed. Claude checked each finding against
the source and pytest before acting, and the triage is kept with the
review's receipts:
- *the configuration:* a header with a comment, a triple-quoted TOML
  string, `key: value`, quoted or dotted keys, a native `[tool.pytest]` table,
  the wrong section of a file, and runner commands read as if they were
  `addopts` (in both directions: a tox environment's `-k` withheld every
  credit, and its `-o python_files=...` widened collection). Hence the
  loader of decision 1, written against pytest 9.1.1's `locate_config`,
  `load_config_dict_from_file`, iniconfig 2.3.1's parser and `_getini`;
- *`addopts`:* clustered short options (`-qk`), an `@` argument file, node
  ids, overlapping initial paths (pytest 9 keeps the outermost), run-nothing
  and cache-selected options, `-p` plugin loads, a word after an unplaced
  plugin option, `--noconftest`, `--confcutdir`, `--collect-in-virtualenv`
  and a `--deselect` prefix that covers a whole file;
- *conftests:* a docstring naming `collect_ignore`, a class or function
  scope's own `collect_ignore`, `vars(x)`, `os.path.join`, conditional
  expressions and concatenations, the nearest-list rule, an entry added
  under a condition (now only possible), a Latin-1 conftest, and a hook in
  the chain whose `pytest_ignore_collect` can override any exclusion (now
  anything possible, deciding nothing);
- *the rest:* an initial path asked whether to be ignored, slash patterns
  matched against the absolute path, a linked root config in range mode,
  opaque directories beside testpaths, a configured `python_classes` with a
  first configuration (a real pass on main: the new `pytest.ini` is only a
  warning), crashes on a symlink loop and on a 1,500-deep path, and the
  cost of reading (now batched, cached against the chain reader, and skipped
  when nothing can be paid).
Each accepted finding has a test, most against pytest's own answer. Rejected
or kept as residuals: the reviewers' inclusion of `--deselect` in the
initial-path exemption (pytest deselects by node id regardless), a
conditional ignore withholding a credit (kept, since the exclusion is
possible), a `-k` withholding every credit (the decided reading), the
working-tree listing walked once more when the inventory is needed, a hook
in a conftest outside the chain, and Windows case rules. The workflow also
reproduced two older holes outside row 179, now rows 180 and 181, and some
pre-existing rename limits KNOWN-ISSUES-next lists. A Gemini 4 Argon headless
review (`agy` 1.4.12, runner v4) stopped incomplete when it attempted to read
a file outside the packet and read root (`runnerExitCode: 1`, empty response)
and is recorded as not reviewed.

**Measured** (LAPTOP-01AGNPJU, `HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL`,
Windows CPython 3.11.9, 2026-10-31).

- What pytest collects: 86 shapes, each built in a fresh directory and
  collected with pytest 9.1.1 (`pytest --collect-only -q`, plugin autoload
  off), against the reading on the same files. 83 agree. In the other three
  the reading withholds a credit pytest would pay: a `unittest.TestCase`
  method under a custom `python_functions`, an ignore in an arm of a
  conditional expression, and an ignore appended under a version check,
  each on Python 3.11. None goes the other way.
- Main against this change: on main `3d115a35`, a test moved unchanged into a
  file outside `python_files`, a `collect_ignore` or `collect_ignore_glob`
  file, a path under `--ignore` or `--ignore-glob`, a node under
  `--deselect`, a repository with a `-k` in `addopts`, a name
  `python_functions` does not match, a path outside `testpaths` or beneath a
  `norecursedirs` entry passes with `ASSERTION_MOVED`; here each blocks with
  `TEST_DISABLED`/high. The controls pass on both: the default
  configuration, `collect_ignore = ["setup.py"]`, a conftest of fixtures
  using `monkeypatch`, a testpath hit, a missing testpath, a testpath glob,
  `addopts` full of plugin options, an unknown option's value, extra
  `python_files`, `[tool.pytest.ini_options]`, `setup.cfg`, an unrelated
  `--deselect`, a replaced `norecursedirs` and a `TestCase` class move.
- Renames: `git mv test_app.py app_test.py` under `python_files = test_*.py`
  passes with no finding on main, while pytest reports "no tests ran"; here
  both tests are `TEST_DISABLED`/high.
- A first `pytest.ini` that sets `python_classes = Check` beside a moved
  `TestThing` method: main passes with `CI_WORKFLOW_TOUCHED` at warn and
  `ASSERTION_MOVED`; here the move blocks.
- A root config that is a link, in range mode through the CLI: the version
  without the config-evidence fallback blocks an honest move under a linked
  `pytest.ini`, and under a regular `pytest.ini` beside a linked
  `setup.cfg`; this change passes both.
- Rows 180 and 181, reproduced through the CLI on main and here: a committed
  `tests/pyvenv.cfg` leaves pytest collecting no item and both pass with no
  finding; an ignored copy of a deleted test gives `DUPLICATE_REMAINS` in
  working-tree mode.
- A same-host differential over the 3,600 members of 0.10.0's R29 sample
  (members file SHA256 `f6281caa...`, the script D-192 used), each member
  checked once with main `3d115a35`'s `src/` (tree digest `e1ba3075...`)
  and once with this change's, exit code and whole report compared except
  run metadata. An interim version without the rename split and the third
  review round: 3,600 identical, exits 3,493 pass, 105 block and 2 errors on
  both sides, 2,690.1 s. The final `src/` (tree digest `d88e90a4...`,
  `arrival_collection.py` SHA256 `31873e46...`; committed `6bfc64f4...`
  spells the literal BOM on line 333 as `"\ufeff"`, identical parsed AST):
  3,600 identical, 0 different; exits 3,493 pass, 105 block and 2 errors on
  both sides, 2,617.1 s.
- The full suite (`pytest tests`, `tests/gates` included, xdist `-n 10`):
  a JUnit file whose testsuite counts `tests="22413"`: 22346 testcase entries,
  22321 passed and 25 skipped, plus 67 subtests, with 0 failures and 0 errors
  (1,131.6 s).

**Residuals.** What the reading costs, as honest changes that now block at
high: every Python move or fold in a repository with a `-k` in `addopts`,
an `@` argument file, a run-nothing or cache-selected option, `--pyargs`,
another rootdir or a `-p` plugin load, or with a conftest above the arrival
that may define a hook (which withheld the credit through D-179's startup
key already) or builds a list the reading does not follow; a move into a
file a conditional ignore names, whose exclusion is only possible; a target
in `addopts` after a plugin option the reading cannot place; a move or fold
inside a file the configuration never collects on either side, whose deleted
test never ran; a `unittest.TestCase` method under a custom
`python_functions` it does not match, which pytest's unittest plugin
collects by its own prefix; under a configured `python_classes`, a class
whose base is a TestCase not spelled `...TestCase`; a `--deselect` that
names one row of an arriving test, which withholds every row's credit; and
a pattern with a slash that matches only at some checkout depths. What it does not read, so a move there
still pays: a runner command's own targets or options (a CI workflow, a tox
environment, a Makefile), `PYTEST_ADDOPTS`, a nested config that a targeted
run discovers, a session hook such as `pytest_collection_modifyitems` in a
conftest outside the arrival's chain, which sees every item, installed
plugins, a pytest version that reads configuration otherwise, a pattern that
names the checkout's own absolute path, case-insensitive file systems
(Windows matches names without regard to case), and a test renamed in place
to a name a configured `python_functions` does not collect, which stays one
aligned unit. Units are still found only in files pytest's default patterns
name, so a move or rename into or out of a file only the configuration
collects is judged as before. KNOWN-ISSUES-next lists both. The review found
two older holes outside this row, now THREATMODEL rows 180 (a `pyvenv.cfg`
committed into a test directory) and 181 (an ignored copy counted as a D10
survivor in working-tree mode), both open.

**Maintainer text** (agent-read-only edits under this entry): SPEC's §2b
collection bullets, its D2 and D10 rows and a paragraph in *Oracle-context
proof in IR3*; THREATMODEL row 179, now Closed, and new rows 180 and 181, open;
and this entry.

**Contracts.** No fingerprint, `FINDINGS_VERSION` (2), `IR_VERSION` (3),
finding field, escalator, de-escalator or severity-table change; no existing
`.gwcase` expectation and no `tests/gates` change. Verdicts move only where
a Python arrival that pytest does not certainly collect used to pay, and
where a Python rename the head configuration certainly leaves out used to
be silent. The three pins D-192 left for row 179 flip, as D-192 said they
would, and are renamed: `test_a_configured_k_filter_leaves_every_python_arrival_unproven`
and `test_a_test_moved_where_pytest_never_collects_it_earns_nothing`
(`python_files`, `collect_ignore`).

**Tests.** New: `tests/test_arrival_collection.py` (239 tests) and four
fixtures: `arrival_python_files_uncollected_pos`, `arrival_collect_ignore_pos`
and `arrival_k_selection_pos` for row 179, and the control
`arrival_configured_collection_neg`.

## D-194 (2026-11-02): a release's `doctor` accepts its own Action commit, which the release pull request's last commit names and the release bridge verifies (scheme S)

**Authority.**

- On 2026-10-28T08:34:01Z Claude asked Nelson five questions, and at
  08:41:25Z he replied
  「1.核准 2.用寫清楚結案 stop hook自動凍結 3.這次統一收尾後跑 4.readme等到修復後重排 可以進版 Hook選local Doctor放寬我有點不太確定 5.這題我不太確定」
  (its line breaks and doubled spaces shown as single spaces, as in D-189 to
  D-191). Item 4's doctor part, 「Doctor放寬我有點不太確定」 (relaxing doctor:
  I am a bit unsure), records his uncertainty about relaxing `doctor`.
- Claude's plan at 08:43:12Z gave three options for `doctor`:
  「(a) 維持嚴格，只把訊息改清楚，說明「這是比 CLI 新的版本，請升級或手動驗證」。安全性不變，但照 README 設定的人還是會看到 exit 1。」
  (keep it strict and only make its message clear; whoever follows the
  README still sees exit 1),
  「(b) 遇到格式正確但不認得的 checkwash SHA，只提示、exit 0。體驗好，但等於放鬆了防範未審 commit 的那道檢查。」
  (only note a well-formed checkwash SHA it does not know, and exit 0,
  which relaxes the check against unreviewed commits) and
  「(c) README 改回推薦上一版的 Action，這樣 doctor 和 README 永遠一致。代價是用 Action 的人會晚一版拿到新引擎，而且要推翻 10-14「不落後一版」的裁決。」
  (have the README recommend the previous release's Action again, so that
  `doctor` and the README always agree, at the cost of a release's lag for
  Action users and of overturning the 10-14 no-lag ruling), and it
  recommended (a): 「**我的建議**：這輪先做 (a)，之後再決定要不要 (b) 或 (c)。」
  (do (a) this round, and decide on (b) or (c) later).
- At 08:44:50Z Nelson wrote one message of two lines:
  「選a不就又回到之前了嗎」 / 「獨立樣本之後討論」 (wouldn't choosing a just
  take us back to how it was before? / discuss the independent sample
  later). The second line is outside this entry.
- Claude then proposed scheme S. At 09:04:03Z it asked
  「要照更新後的計畫（含 doctor 方案 S）開始做 0.11.0 嗎？」 (start 0.11.0 on
  the updated plan, doctor scheme S included?), with two buttons: 「開始」
  (start), whose option text was
  「照更新後的計畫開始做 0.11.0，doctor 採用方案 S（推薦 tag 前一個 commit、release PR 一律 merge commit）。發版後的切檔與 baseline 輪替也照上次做。」
  (start 0.11.0 on the updated plan, with doctor scheme S: recommend the
  commit before the tag, and merge every release pull request with a merge
  commit; its last sentence, on the log cut and baseline rotation after the
  release, is outside this entry), and 「先再討論」 (discuss it further
  first). Its message at 09:04:19Z described the scheme and, since the
  session ran over Remote Control, where the box may not show, listed the
  two choices in its text, 「開始」 first. At 09:05:05Z Nelson answered
  「開始」, the first button's label; the log does not tell a click from a
  typed reply. The commit before the tag
  in that option text is implemented as `vX.Y.Z^2^1`: the tag is the merge
  commit, and the commit is its second parent's parent. He had not been
  told then of the pin-updater consequence below; Claude asked about it on
  2026-10-31.
- At 2026-10-28T17:33:37Z (2026-10-29 01:33 Asia/Taipei) Nelson clicked the
  button labelled 「接著做 0.11」, whose option text was
  「接著做 0.11 其他項目（uvloop 轉交辨識、#419 殘餘結案、doctor 方案 S、README 重排），順便帶上那 3 項文字修正」
  (go on with 0.11's other items, doctor scheme S among them, and bring the
  three text fixes along).
- On 2026-10-31 Claude recommended moving scheme S to 0.12. At 15:00:07Z
  Nelson wrote one message of four lines: 「先等等」 / 「doctor帶s方案」 /
  「如果六腿能批次放 那就可以周一開始」 / 「pypi可以按了?」 (wait a moment;
  doctor with scheme S; if the six platform legs can be batched, start on
  Monday; can PyPI be approved now?). 「doctor帶s方案」 keeps scheme S in
  0.11; 「先等等」 paused the outreach preparation, not this change. That
  Monday is 2026-11-02. The last line is outside this entry.
- At 2026-10-31T15:03:31Z Claude asked
  「doctor 方案 S 接受 Dependabot／Renovate 的這個後果嗎？」 (does doctor
  scheme S accept this Dependabot/Renovate consequence?), with two buttons
  labelled 「接受，寫進文件」 (accept, and write it into the documentation)
  and 「先改設計」 (change the design first). The consequence Claude stated
  with the question, glossed from its Chinese text: the pin the README
  recommends is A_N, the commit before the tag, not the commit the tag
  points to; Dependabot and Renovate change a pin by its version comment to
  the tag's commit, and `doctor`, which accepts only the previous pin and
  A_N, rejects it (inferred from those tools' documentation, not run); the
  Action itself works as before, and only `doctor`'s check is affected;
  `doctor` 0.10 does not accept 0.11's A_N either; the design review
  recommended accepting it with documentation, and Claude recommended the
  same. Claude said it would not start D-194 before his confirmation. At
  15:04:00Z Nelson answered with the first button's label, 「接受，寫進文件」.

Claude maintains checkwash under Nelson's 2026-10-27 delegation
(「Checkwash 一樣給你」: 0.x autonomous, stop before 1.0;
[RELEASING](docs/RELEASING.md)), whose continuation instruction covers
"completing the remaining core repairs and their necessary protected
contracts". Claude wrote the questions, the buttons' labels and their option
text, and only the label may have been sent. These approvals cover scheme S
in 0.11 and this entry, the only agent-read-only text the change needs.
Every choice below that is not quoted above is Claude's under that
delegation, as D-189 to D-193's were: the detailed design, the shape of the
pin lines, the release tool and its refusals, the release bridge's rule and
where it applies, the ordinary bridge's refusals, the RELEASING procedure,
this entry's text, and the tests and their expectations, including the
`tests/test_packaging.py` edits listed under *Test expectations*. None of it
is Nelson's personal review.

**Why.** The published 0.10.0 `doctor` accepts only the Action commit built
into it, v0.9.0's `d6eda4f6`, so a workflow pinned to the v0.10.0 Action the
README recommends gets "workflow analysis incomplete" with an unsupported
SHA, and `doctor` exits 1 ([KNOWN-ISSUES-v0.10.0](docs/KNOWN-ISSUES-v0.10.0.md),
*Publication*; [KNOWN-ISSUES-v0.8.0](docs/KNOWN-ISSUES-v0.8.0.md) had the
same row). The cause is general: a release cannot embed its own commit SHA,
so since the README stopped lagging a release behind (2026-10-14), each
release's `doctor` has known only the previous release's pin and rejected its
own release's pin once the README recommended it. Option (a) would keep
that. Scheme S relaxes `doctor` by one bounded step: it still accepts only
exact SHAs, both written in the CLI's own source, with no network read and no
input, and the second is the release's own Action commit, whose engine is the
release's and whose tree differs from the tag's in one `doctor` line.

**What 0.11 implements.**

1. *`doctor`* (`src/checkwash/doctor.py`). Two constants, each on one line at
   column 0 in exactly the form `_PREVIOUS_ACTION_PIN = "<40 lowercase hex>"`
   or `_OWN_ACTION_PIN = "<40 lowercase hex>"`, with no trailing comment, a
   shape the release tools read, and each name bound only there (item 3):
   the Action pin the README recommended when the release was prepared, and
   the release's own Action commit. Outside a release the two lines are
   equal. `_PINS` keeps three `str` values; the Action's is the previous
   pin, the one the README recommends. The checkwash step is proved when its
   `uses:` names either pin (`_ACCEPTED`, deduplicated, so while the two
   lines are equal there is one); checkout and setup-python keep one pin
   each. With one accepted pin `doctor`'s text is byte-identical to before.
   With two, a wrong ref reads "this CLI accepts P (the Action recommended
   before this release) or A (this release's Action)", and a wrong owner
   "expected <owner>@P or <owner>@A". Exit codes and the step's shape are
   unchanged: the own pin with `with:`, in upper case or under another owner
   still gives "workflow analysis incomplete", exit 1. In this change both
   lines are v0.10.0's `100699796d942af30644738ffbcd1f1c939411c5`, so
   `doctor`'s output does not change.
2. *R* (`tools/own_action_pin.py`, new: a maintainer tool that never commits
   and never imports or runs checkwash). `write`, on a clean checkout of the
   release pull request's content commit A, rewrites the own line to A, runs
   `git add`, checks that exactly `doctor.py` is staged with that blob, and
   prints the `git commit` command for the operator, whose hooks run as
   usual; that commit is R. It refuses, exit 2 with nothing changed, a
   checkout with any change or untracked file, a `doctor.py` that the
   release bridge's pin reader refuses (item 3), a HEAD whose `[project]`
   version equals `release/advertised.toml`'s (R belongs only to a release
   head), a HEAD that is already an R (its own pin is one of its parents), a
   HEAD whose own pin differs from its previous pin (R is written only on a
   content commit whose two lines are equal, so after a commit that followed
   R, R is dropped first), and a worktree `doctor.py` whose bytes differ from
   HEAD's blob, line endings included. If `git add` or the staged-content
   check fails after the rewrite, it writes HEAD's bytes back, resets the
   index entry and exits 2. `check --stage pr|main|tag` runs the release
   bridge's rule on local commits, as an advisory pre-push and pre-tag
   check, not release evidence, and warns on stderr when the rule does not
   apply.
3. *The release bridge* (`tools/pju_release_bridge.py`).
   `validate_own_action_pin` runs in `validate_packet` after
   `validate_parents` and before the product evidence, with the trusted
   ref's announced pin (`ACTION_SHA` in `tools/pju_receipt_bridge.py`), and
   the stage report gains `own_action_pin`.
   - *Where it applies:* at the `pr` and `main` stages unless the head's
     `pyproject.toml` `[project]` version equals both the `[release]`
     version of `release/advertised.toml` at the same head and the base's
     `[project]` version (a failed read or parse fails closed); at `tag`,
     `release-event` and `public-visitor` always. So a version bumped by an
     earlier pull request still needs R, so does a release pull request that
     also moves `release/advertised.toml`, and a subject at the advertised
     version over a base at that version, such as an ordinary pull request
     or main after step 8, is not a release.
   - *How it reads `doctor`:* the two pin lines are read as text and checked
     against the parsed module, which is never executed. `doctor.py` must
     hold no carriage return or form feed, either of which can hide a
     statement from a reader of line-feed lines, and must be UTF-8 as import
     reads it (no other PEP 263 declaration and no byte-order mark, since an
     escaped newline in a comment would otherwise bind a pin at import); each
     name must be bound once, by a module-level assignment on its own line;
     no other node may bind or name either pin (a `def`, class, argument,
     import alias, `global`, attribute, keyword or string with that name, or
     `import *`); and nothing may reach the module namespace dynamically
     (`exec`, `eval`, `compile`, `globals`, `locals`, `vars`, `setattr`,
     `delattr`, `__import__`, `__dict__`, `importlib` or `builtins`).
     `src/checkwash/` must hold no other `doctor` module beside `doctor.py`,
     such as a `doctor/` package that import would take instead. A
     `doctor.py` that does not parse is refused. The rule binds the pin text
     and its single static binding; code elsewhere that changes `doctor` at
     import, and `doctor`'s other logic, are the release pull request's
     reviewed content.
   - *What it checks:* `doctor`'s previous pin is the announced pin, and
     every `taipei49314/checkwash/action@` reference in README.md, in any
     case and read as its whole token, is exactly that pin, so a tag, a
     placeholder, a suffix such as `^{}` or any other SHA fails. At `pr` the
     head is R. At later stages the head is a two-parent merge whose first
     parent is the base and whose second parent R has the head's tree; at
     `main` R must also be the verified pull request head
     (`parents/pr.json`). R has one parent, the own pin A, which differs
     from the previous pin, and A is clean: its `doctor` holds the previous
     pin on both lines. From A to the head `git diff-tree` names only
     `src/checkwash/doctor.py`, mode 100644, modified, with
     `--ignore-submodules=none` so that the checkout's `.gitmodules` cannot
     hide a gitlink; and the two blobs, split at line feeds, differ in
     exactly the own line, from `_OWN_ACTION_PIN = "<previous>"` to
     `_OWN_ACTION_PIN = "<A>"`. A shallow clone or a missing parent fails
     closed.
   - *Native parents:* at `main` and later, GitHub's own commit object for
     the head must list its parents as [base, R] (`validate_native_merge`,
     one more read of `/git/commits/<head>`). That order was observed on the
     merges of #577, #578 and #579, whose `/git/commits` parents are [pull
     request base, pull request head]; GitHub does not document it, and any
     other order is refused.
   - `publish_check` and `tools/collect_pju_release.py` are unchanged: no
     collection preflight and no summary sentence.
4. *The ordinary receipt bridge* (`tools/pju_receipt_bridge.py`).
   `release_versions` reads the two versions at a commit, and the release
   bridge uses it for its discriminator; `doctor_action_pins`, the pin
   reader of item 3, lives here too. `main()` now refuses, before any GitHub
   client exists, a head whose version differs from the advertised one,
   naming the release bridge's `pr` stage as the only route for a release
   pull request's checks, and a head whose `doctor` own pin differs from its
   previous pin, since only a release pull request's last commit sets it;
   `validate_packet` is unchanged. Receipts are verified by the bridge at
   the dispatched trusted ref, so the refusals hold only for receipts
   verified at a trusted ref that contains them. From this change's merge
   on, ordinary receipts are dispatched only from main, and the pre-D-194
   `review/collector-*-010` refs are not used for receipts.
5. *Procedure* ([RELEASING](docs/RELEASING.md), *The release's own Action
   pin* and steps 1, 2, 3, 5 and 8). The version bump lives only in the
   release pull request.
   - *R last.* R is generated last, and nothing follows it: a commit after
     R, GitHub's **Update branch** included, voids R and every PR-stage
     receipt collected on it, so the release pull request's receipt and
     lifecycle records go in the step-8 follow-up. A change after R drops R
     (the branch is reset to R's parent), is made as content commits, and R
     is written again.
   - *Merge.* Main is frozen from A until the release merge, which is a
     merge commit with the pull request up to date; squash and rebase are
     refused at `main`. RELEASING gives the recovery from a squash (a
     follow-up whose first commit sets `doctor`'s own line back to the
     previous pin and whose last is R, merged with a merge commit), the
     route for a fix after the release merge (the same pattern on main's
     tip, with the comparison run again) and the way to abandon the release
     (a pull request that reverts the version and the own line).
   - *R29.* R29 and the targeted uvloop diagnostic start after the last
     content commit A, once R is written, and run on R's `src/` tree, which
     is the tag's. Their records (the run identities, the list, the owner's
     review, the release guide's R29 and JS/TS paragraph naming both engine
     commits, and the JS/TS results record) go in the step-8 follow-up,
     because any change to the release pull request after R makes a new A
     and an R whose `src/` differs in `doctor`'s own line. The owner-ruled
     candidate rule keeps its substance, with a note that from v0.11.0 a
     candidate frozen before R does not count. Exempting `doctor`'s own line
     from that rule would let the comparison run before R, but that is the
     owner's decision and is not taken here.
   - *Local checks.* `tools/own_action_pin.py check` runs at `pr` before
     collecting, and with `--stage tag` on M before tagging, since the tag
     stage applies the rule unconditionally.
   - *Step 8* moves the README pin and its annotation, the self-audit
     workflow, `doctor`'s previous pin, the receipt tools' `ACTION_SHA`,
     SECURITY.md's current pin and two `tests/test_doctor.py` literals to
     A = `vX.Y.Z^2^1`, and, when `action/action.yml` changed,
     `ACTION_YAML_SHA256` in `tools/replay_pju_action.py`. action/README's
     verification moves to the new tag, and its v0.10.0 `ls-remote` line
     becomes the check for pins up to v0.10.0. `release/advertised.toml`
     keeps the tag's peeled commit.
   - *Not enforced.* That main stays frozen from A and that the step-8
     follow-up is the next merge are documented procedure. From the release
     merge until step 8, main's version differs from the advertised one; the
     ruleset's strict up-to-date policy makes another pull request take main
     first, and the ordinary bridge then refuses it.
6. *User text.* README (*Which commit is the recommended pin?*) and
   action/README (*Public pin and upgrade*) say which commit to pin (up to
   v0.10.0 the tag's peeled commit, from v0.11.0 `vX.Y.Z^2^1`), how to
   verify it in a clone, the pin-updater consequence, and the upgrade
   order: the CLI and its local hooks first, then the Action pin.
   SECURITY.md says which commit to pin and links to action/README.
7. *`tests/test_packaging.py`.* The README pin relation is version-aware
   (*Test expectations*, below).

**The accepted consequence.** From v0.11.0 the pin the README recommends,
`@A # vX.Y.Z`, is not the commit the tag points to, and `git ls-remote`
cannot show it. Pin updaters such as Dependabot and Renovate follow the
version comment and will propose the tag's commit (inferred from those tools'
documentation, not run), which no `doctor` accepts: release N's accepts only
the pin recommended before release N and release N's own Action commit. The
Action runs the same check at either commit. Nelson accepted this
with documentation (*Authority*). README, action/README and
[KNOWN-ISSUES-next](docs/KNOWN-ISSUES-next.md) say so; the 0.11.0
known-issues page takes over KNOWN-ISSUES-next's rows.

The same cause reaches zizmor, which the question did not name. Its
`ref-version-mismatch` audit (zizmor 1.14.0 and later) reports a hash pin
whose version comment does not match the pinned commit, and its
pedantic-only `stale-action-refs` reports a hash pin that no tag points to;
`@A # vX.Y.Z` is both (inferred from zizmor's audit documentation, not run).
The README's pin snippet was checked against zizmor's unpinned-uses audit
(`test_readme_action_snippet_is_zizmor_blanket`), not these two. The README
pin moves to A only at step 8 of 0.11, so this change documents the zizmor
consequence beside Dependabot's, and whether to accept it or change the
annotation before step 8 is left to Nelson.

**Why the Action at A is the release's Action.**

- The Action (`action/action.yml`, `action/secure.py`) installs its own
  checkout's `src/checkwash` into a private environment, checks the
  installed bytes, and runs only `python -m checkwash check` (term, and json
  for comments).
- `cli.py` imports `checkwash.doctor` only inside the `doctor` command.
- `tests/test_doctor_own_action_pin.py::test_check_never_imports_doctor`
  runs `cli.main(['check', ...])` in a separate interpreter, in term and json
  format, with `--fail-on high`, and fails if `checkwash.doctor` was
  imported.
- The release bridge requires the tag's tree to differ from A's in exactly
  the own line, gitlinks included, and `tests/test_packaging.py` requires
  the same of the README's trusted tag from v0.11.0.

So the check the Action at A runs is the tag's; its identity receipt differs
from the tag's only through `doctor.py`'s bytes. Every release stage replays
the Action at its head, R at `pr` and then M, which has R's tree; none
replays it at A. The one-line diff and `test_check_never_imports_doctor` are
what carry those replays to A.

**Bootstrap for 0.11.0.** The 0.11.0 chain is verified from a trusted ref,
`review/collector-d-011-<date>`, cut from main at or after this change's
merge; RELEASING records its SHA when it is cut. It is the trusted collector,
and the trusted workflow for the dispatched stages. The release-event
capture runs `release.yml` from the tag M, so M must hold the same
`release.yml` and audited helpers as that ref. This change merges before
the release pull request's content commit A is made, since A's `doctor` and
the verifier both come from it. The announced pin is v0.10.0's
`100699796d942af30644738ffbcd1f1c939411c5`: `ACTION_SHA` at that ref,
`doctor`'s previous pin and the README pin. Each stage's evidence records
host LAPTOP-01AGNPJU, source SHA, runtime and exits, labelled
`HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL`; other platforms are NOT_RUN.

**Superseded.**

- README's *Why is the pin added after the release?* paragraph and
  action/README's *Public pin and upgrade*: a release commit carries the
  prior release's pin, and a follow-up recommends that release's own peeled
  commit. From v0.11.0 the follow-up recommends the release's Action commit
  `vX.Y.Z^2^1`; SECURITY.md's "Pin it by its peeled commit" is reworded to
  match.
- RELEASING step 3's "A merge/squash/rebase creates a new commit", for
  release pull requests: a merge commit only.
- The `tests/test_packaging.py` relation that the README pin is the trusted
  tag's peeled commit, for trusted tags at or above v0.11.0.
- `doctor.py`'s comment that its Action pin is "the newest verified stable
  tag's peeled commit".

The 2026-10-14 maintainer decision that the README recommends the newest
verified release's Action, with no lag, stands; scheme S changes which
commit of that release it names.

**Maintainer text, and what is unchanged.** This entry is the only
agent-read-only edit. Unchanged: SPEC.md, which holds no `doctor` pin text;
THREATMODEL.md (row 88: `doctor` reports and cannot enforce, and stays
advisory); `tests/gates/**`; the gating severity table, the strength lattice
and alignment parameters; every `.gwcase` expectation; the findings and IR
versions, fingerprints, and `check`'s verdicts, exit codes and messages;
`doctor`'s exit semantics and its checkout and setup-python pins; and the
schema and meaning of `release/advertised.toml`, whose `commit` stays the
tag's peeled commit. The release verification report gains an additive
`own_action_pin` object; the manifest, subject, admission and dispatch
schemas and the workflow inputs are unchanged.

**Limits.**

- `doctor` N rejects release N+1's pin, so the CLI and its local hooks must
  be upgraded before the Action pin; `doctor` 0.10.0 rejects the 0.11.0 pin
  (exit 1).
- The recommended pin is not the tag's commit, `git ls-remote` cannot show
  it, and checking it needs a clone; pin updaters propose the tag's commit
  (above).
- No release stage replays the Action at A; each replays it at its head
  (above).
- The rule binds `doctor`'s pin text, its single static binding and a
  single `doctor` module. `doctor`'s other logic, such as `_ACCEPTED` and
  the checks that use it, and code in other modules that could change
  `doctor` at import, are the release pull request's reviewed content.
- A failure after the tag is pushed cannot be fixed by moving the tag; the
  `main` stage and the local `check --stage tag` on M come before it.
- At `pr` and `main` the discriminator skips the rule only when the head's
  version equals both its `release/advertised.toml` version and its base's.
  It relies on `release/advertised.toml` staying at the last verified
  release until step 8, as step 1 requires and the advertised-release tests
  enforce; the tag and later stages apply the rule regardless.
- That main stays frozen from A to the release merge, and that the step-8
  follow-up is the next merge after it, are procedure, not enforced. From
  the release merge to the step-8 merge the ordinary bridge refuses any
  other pull request once it takes main, as the ruleset's strict up-to-date
  policy requires, but only for receipts verified at a trusted ref that
  contains this change. Recovery from a squash or from a commit after R,
  and a fix after the release merge, cost a new R and a new PR-stage
  collection, hours on PJU, and the fixed-corpus comparison again if it
  already ran.
- The tag and later stages always apply the rule, so this bridge refuses to
  re-verify a release before v0.11.0, which has no own pin line. That is by
  design.
- From 0.12, the Action pin (A of 0.11.0) differs from the advertised and
  verdict-baseline commit (the v0.11.0 tag's), so
  `tools/collect_pju_release.py` can no longer fall back to the Action
  checkout for `--advertised-source` and `--verdict-baseline-source`: the
  stage collection must pass separate checkouts, and otherwise stops on the
  mismatch, after the full suite. The maintainer's local stage scripts,
  which pass the Action checkout as both sources, and `prepare-stage.sh`'s
  pinned-checkout assertion must change accordingly (RELEASING).
- PyPI's 0.11.0 description is the README at the tag, which still names the
  v0.10.0 pin, as 0.10.0's named v0.9.0's.
- The verifier has run only on owned synthetic chains on PJU (Windows,
  CPython 3.11.9), not on a real release chain or a hosted runner.

**Test expectations.** Existing assertions edited, none a `.gwcase` fixture
or under `tests/gates`, all in `tests/test_packaging.py` (line numbers at
main `0e6acc35`):

- `_assert_action_pin_matches_verified_release` (L22-32) gains
  `action_commit=None`: `assert pin == advertised["commit"]` becomes
  `assert pin == expected`, where `expected` is `advertised["commit"]`
  unless `action_commit` is given, and its message adds "(Action commit X)".
  The synthetic tag cases that call it without `action_commit` are
  unchanged.
- `test_readme_action_snippet_is_zizmor_blanket`: the trusted tag's peeled
  commit is now `peeled`, and `sha`, the expected pin, is
  `_release_action_commit(ROOT, tag, peeled)`: the peeled commit below
  v0.11.0, else `vX.Y.Z^2^1` after the one-line check. The README reference
  check (L222) and `assert sha == pin` (L246) keep their expressions, with
  new messages. The `^{commit}` README string (L226) and action/README's
  `git ls-remote` line (L229) are required only below v0.11.0; the `^2^1`
  README string always; and from v0.11.0 action/README's
  `git -C checkwash rev-parse` and `git -C checkwash diff` lines for the tag.
  `version_tuple` moves to module level as `_version_tuple`. L255 passes
  `action_commit=sha`, after a new assertion that
  `release/advertised.toml`'s commit is the tag's peeled commit.

At v0.10.0 every outcome is unchanged. From v0.11.0 the relation is relaxed
on purpose: the README pin is the tag's `^2^1` commit, not its peeled commit,
under the check that the tag is a two-parent merge with its second parent's
tree, that this parent has one parent, A = `vX.Y.Z^2^1`, and that from A to
the tag only `doctor.py` changes, in place, in mode 100644 and in exactly
the own pin line, from A's previous pin to A. A dogfood run on the
uncommitted change reported nothing for the rebinding of `sha` from one
`git` call to another, so the relaxation is recorded here, to be reviewed by
reading, not left to that verdict. The design named the expected pin
`action` and wrote `assert action == pin`; with that naming checkwash's own
check paired the removed `assert sha == pin` with the helper's merge-shape
assertion and blocked (ASSERT_WEAKENED, high), a misalignment rather than a
weakening. The test keeps `sha` for the expected pin instead, so
`assert sha == pin` keeps its expression; the gate is unchanged.

Still to come, at 0.11.0's step 8, as data: the v0.10.0 pin literals in
`tests/test_doctor.py`, in
`test_checkout_setup_and_gate_must_be_exact_and_in_order` (the
`"checkwash"` pin, L216) and
`test_ref_diagnostics_name_actual_and_required_pins` (`required`, L604),
move to A of 0.11.0, as #574 moved them to v0.10.0's.

New: `tests/test_doctor_own_action_pin.py` (the line shape and the module's
values, both lines equal outside a release, the previous pin equal to both
receipt tools' `ACTION_SHA`, the README naming only that pin by the release
bridge's pattern, the module's wiring with its own line set to another SHA,
the single-pin text, both pins healthy, other SHAs refused with the two-pin
text, the step's shape, and `check` never importing `doctor`),
`tests/test_own_action_pin.py` (the tool on owned repositories: what `write`
stages, its refusals, its restoring `doctor.py` when staging fails, `check`
at each stage, with `--pr-head` and with its warning when the rule does not
apply, and the recovery from a squash and from a commit after R),
`tests/test_pju_own_action_pin.py` (the rule at each stage and where it
applies, the base version included, the merge shape, twenty-three R, A,
README and `doctor` shapes refused at `pr`, `main` and `tag`, an A that
keeps an earlier own pin, a gitlink change that `.gitmodules` hides, sixteen
other bindings of the pin names, a `doctor.py` that does not parse or is not
UTF-8, ten ways of reaching its namespace dynamically, a second `doctor`
module, shallow and missing parents, the native parent order, the wiring in
`validate_packet`, and the ordinary bridge's refusals before any GitHub
read), `tests/test_packaging.py::test_release_action_commit_follows_scheme_s`,
and the shared chain builder `tests/own_action_pin_fixtures.py`, which pytest
does not collect. No other existing expectation changed. The documented test
count moves to 22444 collected (with D-195, merged from main).

**What runs before merge.** On the pull request's final head, on
LAPTOP-01AGNPJU (`HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL`): the targeted
tests, these twelve files: `tests/test_pju_own_action_pin.py`,
`tests/test_own_action_pin.py`, `tests/test_doctor_own_action_pin.py`,
`tests/test_doctor.py`, `tests/test_issue436_doctor_messages.py`,
`tests/test_tools_global_names.py`, `tests/test_pju_release_bridge.py`,
`tests/test_pju_receipt_bridge.py`, `tests/test_packaging.py`,
`tests/test_docs_links.py`, `tests/test_documentation_contracts.py` and
`tests/test_state_claims.py` (the 272 below counted a list that differs from
it); the full suite (`pytest tests`, `tests/gates` included); dogfood (`checkwash check` on the pull request's range with
`--fail-on high`); and the pull request's ordinary PJU receipt, whose intake
sets the four required checks. This pull request needs no same-host R29
differential: its only `src/` change is `doctor.py`, which `check` never
imports. The release's fixed-corpus comparison still runs on R's `src/`
tree (item 5). Other platforms: NOT_RUN.

**Evidence before review.** On `04b469fa`, the commit reviewed below, on
LAPTOP-01AGNPJU (`HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL`, Windows CPython
3.11.9, pytest 9.1.1) on 2026-11-02: the targeted set above, 272 tests with
one existing symlink-privilege skip, 0 failures; the suite then collected
22393 items; a scratch mutation run of the new rule, the tool and their
tests killed 28 of 29 mutants, the survivor being the unreachable
`own != previous`; and checkwash's own check from `0e6acc35` at
`--fail-on high`, with this tree's engine and with the published v0.10.0
pyz: pass, eight warnings and none at or above high (seven on
`tests/test_packaging.py`, held at warn by PACKAGE_REPAIR, and one
IMPORT_UNRESOLVED). The full suite and the PJU receipt run on the final
head, after review.

**Review.** Four Claude review agents (lenses: verifier attack; `doctor`,
tool and tests; release process; claims and records) and one Gemini 4 Argon
run, which completed, reviewed `04b469fa`. Claude checked each finding
against the code before acting on it. Accepted and fixed:

- *A is clean.* A's own line must equal its previous pin in the release
  bridge, in `write` and in `tests/test_packaging.py`, and the ordinary
  receipt bridge refuses a head outside a release whose own pin differs from
  its previous pin, so one edited line can no longer make main's `doctor`
  accept another SHA with every test passing (raised by Argon, verified by
  Claude; also raised by the `doctor` reviewer). The recovery procedures
  change with it: R is dropped before a change, and a squash is recovered
  by a commit that resets the own line (raised by Argon, verified by
  Claude).
- *How `doctor` is read.* A lone carriage return, a form feed or a second
  binding of a pin name, which the line reader missed, is refused, and the
  module is parsed without being run (the verifier reviewer; also raised by
  Argon, verified by Claude). The README pattern takes the whole reference
  token (raised by Argon, verified by Claude). The A-to-head diff passes
  `--ignore-submodules=none` (the verifier reviewer).
- *Where the rule applies.* At `pr` and `main` it also applies when the
  head's version differs from its base's (raised by Argon, verified by
  Claude). The pre-tag check is `check --stage tag`, and `check` warns when
  the rule does not apply (the verifier and release-process reviewers).
- *The tool and the test helper.* `write` restores `doctor.py` and its index
  entry when a step after the rewrite fails (the `doctor` reviewer).
  `_release_action_commit` also requires the tag's tree to be R's, checks
  the mode and the line bytes, and requires A's own line at A's previous
  pin (raised by Argon, verified by Claude).
- *New tests* cover `doctor`'s wiring with its own line set to another SHA,
  `--pr-head` reaching the rule, both pin lines equal outside a release (the
  `doctor` reviewer), the release bridge's README pattern on the live
  README, and the previous pin against both receipt tools' `ACTION_SHA`
  (the release-process reviewer).
- *RELEASING.* When R29 runs and where its records go (the release-process
  reviewer; raised by Argon, verified by Claude). What is procedure rather
  than enforced between A and step 8, which refs may verify ordinary
  receipts, and the routes for a change after R, a squash, a fix after the
  release merge and abandoning the release (the release-process reviewer;
  raised by Argon, verified by Claude). Step 8's list (raised by Argon,
  verified by Claude; `ACTION_YAML_SHA256` from the release-process
  reviewer). The sources from 0.12 (the release-process reviewer). The
  replay scope and the release-event workflow (raised by Argon, verified by
  Claude).
- *This entry.* The test count (the claims and release-process reviewers;
  also raised by Argon, verified by Claude), the authority bullets on the
  `doctor` options, the observed merge-parent order, the SECURITY.md claim,
  the `test_packaging` relation and the heading *What runs before merge*
  (the claims reviewer).

Declined:

- Calling the ordinary bridge's refusals inside `validate_packet` (Argon):
  `main()` is the only publication path, and `validate_packet` is the
  unit-level validator that existing tests call with heads that have no
  `release/advertised.toml`.
- Requiring A to descend from the base or to have one parent (Argon): A may
  legitimately be a merge commit, such as an **Update branch** merge before
  R is written, and M's tree being R's already binds the content.
- Replaying the Action at A (Argon): it would change the trusted collector,
  which this change leaves unchanged; the one-line diff and
  `test_check_never_imports_doctor` carry the replays to A.
- Tagging A instead of M (Argon): a different scheme from the one Nelson
  approved, which would change the tag stage, published-source verification
  and the sdist's identity. It is left to Nelson, beside the zizmor question
  above.
- Moving the `test_doctor` helpers to clear the IMPORT_UNRESOLVED warning
  on `tests/test_doctor_own_action_pin.py` (Argon): the import follows
  `tests/test_issue436_doctor_messages.py`, and the finding is a warning.

**Second review.** Two Claude agents re-reviewed the fixes at `8c75826e`:
one reran the first round's reproductions and attacked the new code, the
other checked the records against the code and their sources. Every
accepted first-round finding reproduced as fixed, and a lifecycle probe of
21 steps (ordinary pull requests, the release, a pull request after the
merge, abandoning a release, a fix after the merge, step 8, the baseline
rotation and a 0.12 release) refused no legitimate flow. Accepted and fixed:

- A PEP 263 declaration such as `raw_unicode_escape` let an escaped
  newline in a comment bind a pin at import, unseen by a parse of the
  UTF-8 text; `doctor.py` must now be UTF-8 as import reads it (the attack
  reviewer).
- Dynamic rebinding (`exec`, a computed `globals()` key, `setattr` on the
  module) and a `src/checkwash/doctor/` package that import takes instead
  passed, while the records read as if every rebinding were refused. Both
  are now refused, and the records say that the rule binds a single static
  binding in a single module (the attack reviewer).
- The ordinary bridge's version refusal now also names a branch that took
  main between a release merge and its step-8 follow-up, as the
  release-process reviewer had asked (left out of the first fixes, the
  records reviewer).
- The 「開始」 bullet no longer says that Nelson clicked; the targeted-test
  files are named; RELEASING gives the recovery after a rebase merge too and
  says that the comparison reruns (the records reviewer).

Partly adopted: of the `doctor` reviewer's three suggested tool tests, the
`--pr-head` one was added; tests for the staged-content check (through a
`post-index-change` hook) and for the `GIT_*` environment strip were not.
Both guard the advisory tool, and the release bridge refuses a bad R
whatever the tool did. The tool's restore puts back `doctor.py` and its
index entry; anything a hook stages beside it stays staged. The message of
`8c75826e` says each new pinning test fails against `04b469fa`'s tools; the
four invariant tests in `tests/test_doctor_own_action_pin.py` and the
`--pr-head` assertion pin invariants that already held there, and pass (the
records reviewer).

The first fixes added 38 collected tests (22431). The second review's fixes
add 12, and D-195, merged from main, one, so the suite collects 22444.

Evidence after review: TBD-D194-EVIDENCE2

## D-195 (2026-11-02): five test relaxations that agent sessions left in checkwash's own tests are restored

**Authority.**

- The 2026-10-28 session replay (local repository `C:/Users/nelson/dev/cwrp`,
  PREREG `2e693e3`, results `93e602c`; D-189's *Why*) replayed 630
  reconstructed agent edits of Python test files one at a time through the
  released v0.10.0 pyz. Its labels, provisional as D-189 says, call 12 of
  them loosenings with no reason in their context. Five are in checkwash's
  own tests and were still on main `0e6acc35`: replay items 672, 36, 32, 359
  and 621.
- On 2026-10-31 Nelson paused the outreach preparation (「先等等」, wait for
  now); the handoff asked whether these five go into 0.11.
- At 2026-11-02T11:49:13Z Claude asked
  「checkwash main 裡那 5 筆 agent 放鬆的測試（回放 #672、#36、#32、#359 收緊比對，#621 補回被刪的測試），要在 0.11 凍結前修掉嗎？」
  (should the five loosened tests on checkwash's main, replay items 672, 36,
  32 and 359 to be tightened and 621 to be put back, be fixed before the
  0.11 freeze?), with two options Claude wrote:
  「帶進 0.11 (Recommended)」 (bring them into 0.11), described as
  「凍結前另開一個只動 tests/ 的小 PR：逐筆確認原本的精確比對現在還成立再收緊，#621 查清原本測什麼再補；順便記下每筆是哪個 PR 帶進來、當時 checkwash 判了什麼。不動 src，不用重跑 R29，不影響 doctor-S 和六腿排程。」
  (before the freeze, a separate small pull request that changes only
  `tests/`: confirm for each that the original exact comparison still holds,
  then tighten it; find out what #621 tested, then put it back; record which
  pull request brought each in and what checkwash judged then; no `src`
  change, no R29 rerun, no effect on doctor-S or the six-leg schedule), and
  「先不帶」 (not now), described as
  「維持「先等等」：0.11 照原範圍凍結，5 筆留到對外發文準備時再處理。」
  (keep 「先等等」: 0.11 freezes with its scope, and the five wait for the
  outreach preparation).
- At 2026-11-02T11:49:28Z Nelson chose 「帶進 0.11 (Recommended)」.

Claude maintains checkwash under Nelson's 2026-10-27 delegation
(「Checkwash 一樣給你」: 0.x autonomous, stop before 1.0;
[RELEASING](docs/RELEASING.md)). Every choice in this entry is Claude's
under that delegation: the form each restored check takes, the line ending
of item 359, the place of the restored test, the mutations that show each
check is not vacuous, and this entry's wording. Claude wrote the question,
both options' labels and their descriptions, and the recorded answer holds
only the label. The choice brings the five into 0.11; beside the tests,
this change adds a STATE.md section and this entry, the record each change
carries, and moves the documented test count in README.md, CONTRIBUTING.md
and docs/launch.md; the option text names neither. None of it is Nelson's
personal review.

**How the loosenings reached main.** Each time, an agent session wrote the
strict check, loosened or deleted it in its working copy and committed only
the loose form minutes later, in a test file that its pull request added
(the edit's time is the replay packet's, the commit's its author date):

| Replay | Edit | First commit | Pull request | `checkwash` on that pull request |
|---|---|---|---|---|
| 672 | 2026-10-19T10:57:53Z | `92f861ea`, 11:02:46Z | #511 (head `c7efced8`), merged through integration batch 3, #540 (`35fd9df9`) | pass on both, with two IMPORT_UNRESOLVED warnings on this new file (its imports of two sibling test modules) |
| 36 | 2026-10-17T06:42:29Z | `71a6604f`, 06:45:39Z | #476 (head `708c58b7`, merge `81c69d28`) | pass, with two TEST_DISABLED warnings in `tests/test_issue272_helper_skips.py` |
| 32 | 2026-10-17T06:08:50Z | `a7961032`, 06:14:25Z | #474 (head `b88e25f7`, merge `f541f748`) | pass, with four warnings in `tests/test_frontend_iterative_visit.py` and `tests/test_conftest_controls.py` |
| 359 | 2026-10-14T12:08:26Z | `c0b9ddca`, 12:10:06Z | #448 (head `a94b7ca0`, merge `a20d3767`) | pass, no finding |
| 621 | 2026-10-19T06:49:41Z | `ae8bbe0f`, 06:50:05Z | #524, merged through integration batch 2, #533 (`adea2350`) | pass, no finding on #524's one run (head `98b2c8a7`); on #533, nine warnings in other files |

The `checkwash` check (the pinned Action at `--fail-on high`: v0.8.0, and
v0.6.0 for #448) compares a pull request's base with its head. Each file was
new in its pull request, so each loose form was an added assertion with
nothing to weaken, and no strict form was ever committed (each test's line
history on main is the one commit that added it, and `git log --all -S`
finds neither the strict lines of 672, 32 and 359 nor the deleted test's
name). No finding was raised on these assertions, so no de-escalator was
involved: the replay summary's unchecked guess that production changes in
the same pull request held them at warn through E1 does not hold for these
five. Where the dogfood job ran (every pull request but #533), it
said the same. Replayed one edit at a time, v0.10.0 blocks each at high:
ASSERT_WEAKENED (672 and 36), ASSERT_SUBSTITUTED and EXPECTED_VALUE_CHANGED
(32), SUBJECT_NORMALIZED (359) and TEST_DISABLED (621). By rule alone, the
0.11 PreToolUse ask (D-189), which asks only on the five weakening rules,
would cover 672, 36 and 621 and not 32 or 359; it was not run on these
edits. No commit message, pull request body, DECISIONS entry or STATE
section gives a reason for any of them; for 621, #524's body and D-157
state the behaviour the deleted test pinned.

**What is decided.** Each item was checked again against the test's history
and current behaviour. Each strict form still describes what main
`0e6acc35` does; 359's line ending is made portable.

1. *672*, `tests/test_issue469_limit_messages.py`.
   `test_the_pass_reads_each_sides_module_once_for_helper_and_changed_callee_tests`
   again ends with the line the session first wrote,
   `assert {f.unit for f in findings if f.rule == "TEST_PATCHES_SUBJECT"} == {f"test_{n}" for n in range(count)}`,
   byte for byte the replay's base side, in place of the `<=` form and the
   comment the loosening added. The same subset shape was in
   `test_the_pass_checks_math_gcd_and_parameterized_tests_once_per_file`, on
   its units and, for the parameterized shape, its (unit, call) pairs,
   written as `<=` in `81084439` with no strict form on record; both now use
   `==`. On main both tests' findings name exactly their 30 tests, and the
   parameterized shape's each at its own first call.
2. *36*, `tests/test_issue306_self_methods.py`.
   `test_a_helper_method_inlined_into_the_test_pairs_with_its_old_copy`
   again asserts `run(SOURCE, after) == ("pass", [])`, byte for byte the
   replay's base side, after the unpacking and
   `assert not any(rule in ("ASSERT_REMOVED", "ASSERT_WEAKENED", "ASSERT_SUBSTITUTED") for rule, _ in findings)`
   that the loosening wrote, which ignore the verdict and every other rule
   and stay (see *checkwash on this change*). D-145 (Sub-Q11 (b))
   pairs a `via` assertion with the after side's unpaired own assertions, so
   a helper method's assertion inlined unchanged reports nothing; on main
   the result is `("pass", [])`.
3. *32*, `tests/test_issue424_rebinding.py`.
   `test_a_compat_gated_rebinding_is_held_at_warn` again asserts
   `[(f.rule, f.severity, f.deescalators) for f in findings] == [("TEST_DISABLED", "warn", ["COMPAT_GATE"])]`,
   byte for byte the replay's base side, after the same list without
   de-escalators and `"COMPAT_GATE" in findings[0].deescalators`, which
   pass any extra de-escalator and stay. On main the finding carries exactly D6's
   `["COMPAT_GATE"]` (D-144).
4. *359*, `tests/test_issue415_oversized_sources.py`.
   `test_another_manifest_over_the_limit_at_the_base_refuses_naming_it`
   compares the whole stderr again, after the `splitlines()` check, which
   stays:
   `assert stderr == f"checkwash engine error: {REFUSAL}: {described('requirements.txt', 'base')}{os.linesep}"`.
   The session's strict form ended in `"\n"`. `_check` decodes the child's
   stderr bytes without translating line endings, and the CLI writes the
   line through Python's text-mode `sys.stderr` (`cli._engine_error`,
   `report.textio.write_text`), which ends it with CRLF on Windows: on
   LAPTOP-01AGNPJU the stderr is the message and `"\r\n"`, so the strict
   form fails there, as it would have on the Windows test legs, while
   `splitlines()` accepted a missing or any other line ending. The restored
   check pins the one line, its text and the platform's line ending. The
   file's other stderr checks read lines or substrings, and none pins a
   line ending.
5. *621*, `tests/test_issue463_snapshot_added_production.py`.
   `test_repair_evidence_still_reads_an_added_modules_symbols` is back at
   line 131, where it was, byte for byte as the session wrote it: beside a
   production module the diff adds, which defines the function a test
   calls, `fees::fee` is in `prod_symbols_in_added_files`, and the test's
   rewritten expected value is EXPECTED_VALUE_CHANGED held at warn by
   REPAIR_EVIDENCE. That is D-157's "symbol repair evidence and the one-hop
   callers (`gating._repair_evidence`, `evidence._record_callers`) still
   read an added file's symbols", which the engine's added-file branch
   repeats; on main the test passes.
   `test_the_ir_names_what_an_added_file_contributed_and_keeps_it_a_changed_symbol`
   pins only that the IR keeps those symbols, not that repair evidence
   reads them.

**Not vacuous.** Each restored check passes on main and fails, in a scratch
copy of the tree, under a one-line mutation of the code under test or a
wrong input; the loose form ran beside it on the same tree:

- 672: `engine.py` records each subject-replacement event once more with no
  unit. The restored unit equalities fail in all four cells; the `<=` forms
  pass. Recording each event once more for its own unit with another text
  fails the restored (unit, call) equality; the `<=` form passes.
- 36: `ir/diffalign.py` stops pairing `via` assertions with the after
  side's unpaired own assertions. The result is ASSERT_REMOVED at high, and
  both forms fail. With a wrong input instead, the inlined copy expecting
  78.5, the result is EXPECTED_VALUE_CHANGED at high and a block: the
  restored check fails, the loose one passes.
- 32: `gating.py` adds REPAIR_EVIDENCE beside a compensation. The restored
  check fails; the loose one passes.
- 359: `cli._engine_error` writes the line without its line ending. The
  restored check fails; the loose one passes.
- 621: `gating._repair_evidence`'s direct symbol match leaves out
  `prod_symbols_in_added_files`. The restored test fails, EXPECTED_VALUE_CHANGED
  at high with no de-escalator. On that tree the golden runner over every
  fixture, the rest of the #463 file and eight related test files (snapshot
  expectations, subject-snapshot integration, #219, #471, the #419
  residual, root oracles, #335 and the CLI end-to-end tests) pass, 1620
  items: nothing else there pins it.

**checkwash on this change.** Written in place of the loose lines, as the
sessions first wrote them, the strict checks of 36, 32 and 359 block.
Checked from `0e6acc35` against the working tree at `--fail-on high`,
main's engine and the published v0.10.0 pyz (SHA256 `9a58d3d4...`) agreed
on three high findings and two warnings, all on checks at least as strong
as the ones they replaced. 359 was ASSERT_SUBSTITUTED at high
(`stderr.splitlines()` -> `stderr`); 36 was ASSERT_WEAKENED at high
("subject and polarity both changed"); 32 was EXPECTED_VALUE_CHANGED at
high (`[('TEST_DISABLED', 'warn')]` -> `[('TEST_DISABLED', 'warn',
['COMPAT_GATE'])]`), with ASSERT_SUBSTITUTED and ASSERT_REMOVED at warn
under SAME_UNIT_REWRITE. checkwash pairs a rewritten assertion by its
subject and form, and does not prove that a check on another subject or of
another shape is stronger. Rather than record base-side exemptions for a
change that only strengthens tests, Claude added those three strict checks
after the loose lines, which stay: an added assertion has no before side to
weaken, and each strict check implies the loose one beside it, so each test
checks what its strict form checks. The 672 equalities and the restored 621
test raise nothing in place, and stay in place.

**Contracts.** No `src/`, SPEC, THREATMODEL, `.gwcase` fixture or
`tests/gates` change, and no fingerprint, finding field, escalator,
de-escalator or severity change. With no `src/` change, R29 does not rerun
for this change. Agent-read-only text: this entry only.

**Tests.** Changed existing assertions, each listed above (`<=` to `==`):
one in
`test_the_pass_reads_each_sides_module_once_for_helper_and_changed_callee_tests`
and two in `test_the_pass_checks_math_gcd_and_parameterized_tests_once_per_file`.
Added after existing assertions, which stay: one each in
`test_a_helper_method_inlined_into_the_test_pairs_with_its_old_copy`,
`test_a_compat_gated_rebinding_is_held_at_warn` and
`test_another_manifest_over_the_limit_at_the_base_refuses_naming_it`.
Restored: `test_repair_evidence_still_reads_an_added_modules_symbols`, one
more collected item, so the documented test count (22346 on main
`0e6acc35`, in README.md, CONTRIBUTING.md and docs/launch.md) moves by one.

**Evidence.** On LAPTOP-01AGNPJU (`HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL`,
Windows CPython 3.11.9, pytest 9.1.1) on 2026-11-02, from main `0e6acc35`:
the five changed test files with `tests/test_state_claims.py`,
`tests/test_docs_links.py`, `tests/test_documentation_contracts.py` and
`tests/test_packaging.py` (the documented test count included) pass, exit 0;
the mutation and wrong-input runs above ran in scratch copies; and
checkwash's own check of the final change at `--fail-on high`, with main's
engine and with the published v0.10.0 pyz, passes with no finding. The full
suite runs in this change's PJU receipt. Not run: other platforms, so the
`os.linesep` form of 359 is run on Windows only; by reading, POSIX writes
`\n`, which is `os.linesep` there.

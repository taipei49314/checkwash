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
  scope, future, statement and statement list, so it runs in time linear in
  the file up to the log factor of its interval lookups.
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
and R2b carry the security argument: a credited relay sits in a callback or
thread body a collected test hands off, outside any fixture, and its `try`
body neither holds an assertion a parse-time unit executes nor reaches one
through a same-file name, so whatever defeats it loses only an assertion
whose deletion already passes silently (THREATMODEL row 91). R3 to R7 carry
it only together with R2 and R2b: they refuse the spellings they name, and
no list of spellings closes every same-file route.

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
not refused; B's own completion is read only against the named hand-offs,
so a B called from a function that is itself handed to a thread, or an
async B whose coroutine is scheduled and never awaited, can lose the
consumer's failure; a callback invoked again after it completed the future
loses the later failure; a `with` whose `__exit__` suppresses is not read
(row 91a); a broken relay is not reported, as on 0.10; and honest relays
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
`failure_relay_decorated_coroutine_pos` and
`failure_relay_future_in_thread_body_pos` (each one BROAD_EXCEPT_ADDED at
high, `bypass: 171`). The design's `failure_relay_await_removed_pos` is not
added: under the 0.10 bound that edit passes, so it is the row-171 residual
test instead. New: `tests/test_failure_relays.py`, and five tests at the end
of `tests/test_pre_tool_use.py`. No existing expectation changed.

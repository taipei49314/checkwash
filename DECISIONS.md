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

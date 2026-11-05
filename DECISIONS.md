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
moved entry, but 50 links in seven documents were named after a moved entry
and pointed at `DECISIONS.md`; they now point at the archive, and
`tests/test_docs_links.py` checks that a link named after an entry reaches
the file that holds it.

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

## D-198 (2026-11-05): receipts spread over the receipt host's cores

After v0.11.0's publication, while its rotation PR #586 was still collecting
its receipt, Nelson wrote on 2026-11-04 at 14:35:46Z
「現在做一版checkwash 成本開始提升上來了」 (a release now costs more). Claude
counted where the time went. Since 2026-11-02, 14 finished PJU collections
had taken 966 minutes, counting each to the minute, and a fifteenth was
running. The v0.11.0 critical path took about 24.5 hours. Asked
"Should I draft a concrete plan to cut each checkwash release's cost?",
Nelson chose the button 「出方案」 at 14:38:39Z and added at 14:39:42Z
「要特別去看時間成本」 (look at the time cost in particular). Claude's plan then
broke receipts down from their command ledgers. An ordinary receipt of the
cycle took about 56 minutes (qualify 31.5, pytest 20), and the v0.11.0
tag-stage receipt about 83 (qualify 32, verdict gate 23, pytest 23). The three
qualifications ran one after another and pytest used two workers, on
LAPTOP-01AGNPJU, a 24-core host. Claude's multiple-choice question listed
four options. One was 「收據加速」, described as
「改收集器和兩個 bridge：pytest 從 2 個 worker 改成約 6 個，三輪 qualify 同時跑。粗估每張收據省 25～40 分鐘、每版關鍵路徑省約 3 小時。先在 PJU 實測三次，另開 PR，0.12 前做。」.
At 14:42:29Z Nelson selected it together with two other options. At 14:44:38Z
he withdrew one of those two and wrote 「做綁機器的時間成本就可以 主要是要減少時間成本」
(the time bound to the machine is enough; the point is to cut time). At
14:45:53Z he withdrew the other: 「拉長發版間隔 這個也不用」. #586 merged at
16:38:49Z. Asked "Should I start the receipt speed-up now in this
session?", he chose the button 「現在開始」 at 16:44:02Z. Claude wrote the
questions, the option labels and their descriptions. The rest of this entry
is Claude's under the pre-1.0 delegation.

What changes:

- The collector runs the full suite with 8 xdist workers instead of 2.
  The option text said about 6. Claude chose 8 because the host has 24
  cores and two full local runs with 10 workers took 8 min 46 s and
  11 min 28 s. Both bridges require exactly 8, so the count stays bound to
  the admitted collector. It does not change which tests run. A receipt
  from an earlier collector, with 2 workers, no longer verifies after the
  merge. No merge or release needs one:
  - main requires a pull request to be up to date, so after the merge a
    pull request's new head needs a new receipt;
  - a release-stage receipt's verdict helper must equal the bridge's, and
    this change alters `tools/verdict_gate.py`.
- The source, wheel and pyz qualify -> inventory chains run at once. Each
  writes only its own records, logs and nested ledger, and each inventory
  reads only its own qualification. `run_record` takes a lock around the
  shared command-ledger update. After all three finish, every failed
  chain's error is recorded, in distribution order, and the collection
  fails.
- `tools/verdict_gate.py` gains `--jobs N` (default 1). Up to N cases run at
  once, each in its own repository, and a case's engines still run one
  after another. Failures merge in case order, so the gate's receipt
  equals a `--jobs 1` run. The release collector passes `--jobs 6`. This
  was not in the option text, and Claude's plan had named a different step,
  overlapping the gate with the qualifications. Under
  「做綁機器的時間成本就可以」 Claude ran the gate's cases at once instead,
  because the gate took 23 of a release-stage receipt's 83 minutes and its
  cases are independent.
- `traced_worker` takes a lock around each nested row's stream appends and
  ledger append. A helper's subprocesses can then run on threads while every
  recorded offset still selects exactly that command's bytes. The bridges
  already match nested verdict rows to cases by argv and directory, not by
  order, so they did not need to change for this. `commands.json` is
  rewritten every 500 rows and when the helper ends, not after every row.
  Inside the lock, rewriting the gate's 4,000-row ledger after every row
  had cost minutes.

What runs and what each record proves do not change. The receipts now
record `-n 8` and `--jobs 6`, and their command and nested ledgers list
overlapping commands in completion order. Summing those durations therefore
no longer gives the elapsed time. The bridges depend on none of this.

Measurements on LAPTOP-01AGNPJU (Windows, CPython 3.11.9,
`HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL`):

1. The gate alone. The 185 cases and 4 engines of the v0.11.0 rotation
   proposal run (D-197) were run again with `--jobs 6`, and the receipt is
   byte-identical to that run's serial receipt (SHA256 `98d04534…`). It
   took 4 min 12 s instead of 16 min 2 s.
2. A full release-stage `pr` collection of this branch's `94e87cea`, by
   the new collector (capture run 41877624633), took 43 minutes. v0.11.0's
   release-stage collections took 82 to 86 minutes, and #586's took 98.
   pytest took 12.0 minutes (22,431 passed, 25 skipped, 67 subtests). The
   three qualify -> inventory chains took 18.8 minutes together, each
   qualification 15.0 to 16.4 minutes; one after another they had taken
   about 35. The verdict gate took 7.1 minutes, and its 185 cases passed.
   The new release bridge's dry run verified the receipt locally, with the
   five check names and 22,456 collected tests.
3. An ordinary receipt of the same commit, by the new collector, took
   31.5 minutes. v0.11.0's ordinary receipts took 55 to 60. pytest took
   11.2 minutes, and the chains took 18.0. The new ordinary bridge's
   `verify` mode verified it locally, with four checks, 22,456 tests and
   283 qualification cases.
4. The final code. A release-stage `pr` collection of `0ebd5ad8`, by the
   final collector (capture run 41895389125), took 36.75 minutes. pytest
   took 10.9 minutes (22,436 passed, 25 skipped, 67 subtests), the three
   chains 15.6 minutes together, and the verdict gate 6.2 minutes; its 185
   cases passed. With the nested ledgers written in batches, the wheel
   inventory took 2.1 minutes instead of 3.7 and the gate 6.2 instead of
   7.1. The final release bridge's dry run, which requires 8 workers,
   verified the receipt locally, with the five check names and 22,461
   collected tests.

The review's changes came after measurements 2 and 3: the exact worker
count, the recorded chain errors and the nested ledger's rewrite.
Measurement 4 covers the final code.

Hosted test workflows remain disabled. This pull request's own receipt is
collected by main's collector, the one it replaces. Receipts collected after
the merge use the new one. None of the measurements was published.

## D-199 (2026-11-06): the weakening, stand-in and subject rules take no repair evidence (0.12, D-196 item 4)

**Authority.**

- D-196 item 4 records Nelson's 「d191是我刻意的 這部分12要改掉」
  (2026-11-02T15:43:21Z; D-191 was deliberate on my part, this part is to be
  changed in 0.12) and Claude's reading that 0.12 removes D-191's residual
  after Nelson sees a design with its costs.
- Claude's design, in Traditional Chinese and outside this repository,
  priced five Python options and three JS/TS options on main `7cd8549c`
  (below). Two Claude sub-agents reviewed its first draft, one checking
  facts and one looking for bypasses. Claude checked each point against the
  source or a toy repository and changed the design: option A alone only
  narrowed the residual, so options R and R8 were added, and D-088's sample
  was measured because R29 alone had hidden #464's cost.
- At 2026-11-05T17:38:56Z Nelson wrote 「選R」 (choose R), in reply to
  Claude's message that listed the open questions, among them
  「Python 收到哪一層（建議 R）」 (how far to narrow Python; R recommended).
- At 17:40:16Z, to Claude's multiple-choice question on the JS/TS part, he
  chose the option labelled 「只收放寬類（建議）」 (only the loosening shapes,
  recommended), whose description read
  「放寬 assertion、在還活著的測試上加 skip，不再吃 JS 模組改動；整個刪測試、刪 assertion 照舊。多擋 11 筆（多半是安全修補和行為修正），改 4 個 fixture。」.
- At 17:42:17Z, asked 「0.12 這兩項要開始實作嗎？」 (start implementing these
  two 0.12 items?), he chose the button 「開始實作」 (start implementing).

Claude wrote the questions, the options, their descriptions and the
recommendations; for a button answer the log holds only the label. These
answers choose the change; they are not Nelson's review of its text. This
entry, the SPEC and THREATMODEL text, `gating.py`'s escalation policy and
each fixture and test expectation that moves (below) are agent-read-only
or rule 2 changes, and the pull request asks him to approve them by name
before it merges. The next pull request's STATE records that approval.
Every detail not quoted above is Claude's under the 2026-10-27 delegation
(「Checkwash 一樣給你」: 0.x autonomous, stop before 1.0). None of it is
Nelson's personal review.

**What is decided.**

1. In a Python test or conftest, these rules take no repair evidence:
   `ASSERT_WEAKENED`, `ASSERT_REMOVED`, `TEST_DISABLED`,
   `TOLERANCE_LOOSENED`, `BROAD_EXCEPT_ADDED`, `TEST_PATCHES_SUBJECT`,
   `CONFTEST_PATCHES_PROD`, `SUBJECT_NORMALIZED`, `SUBJECT_INPUT_CHANGED`
   and `EXPECTED_VALUE_DERIVED`. That is SPEC §5's clauses 1 and 2 (Route A)
   and clause 3 (Route B) alike (`gating.REPAIR_REFUSED_PYTHON`, option R).
2. In a JS/TS test, `ASSERT_WEAKENED`, `TOLERANCE_LOOSENED`,
   `BROAD_EXCEPT_ADDED` and a `TEST_DISABLED` that is no removal shape (a
   marker on a live test) take none (`gating.REPAIR_REFUSED_JS`). A removed
   assertion, a deleted test and deleted parametrize rows keep clause 3, the
   only evidence a JS/TS test can earn.
3. A refused finding that the evidence reached, and that nothing else
   holds, is high with the new E1 label `REPAIR_EVIDENCE_REFUSED`. One that
   no evidence reached keeps the label it had. The label stays outside the
   fingerprint; `FINDINGS_VERSION` and `IR_VERSION` do not change.
4. Nothing else in gating moves: D2, D4 to D8 and D10, `MILD_WEAKENING`,
   the expected-value rules' and `ASSERT_SUBSTITUTED`'s evidence,
   `PACKAGE_REPAIR` and D9, suite controls and E2.
5. This supersedes D-171's K1 for these rules. D-141's stop line ("any
   verdict move stops the round") does not apply to this change: its moves
   were measured, listed and priced before Nelson chose among A, R, R8, C
   and B.

**What it costs.** Measured on LAPTOP-01AGNPJU (Windows, CPython 3.11.9,
`HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL`; other platforms NOT_RUN). Each
option was a copy of main `7cd8549c`'s `src/` (tree `160f5d98`) with only
`gating.py` changed. Each member was checked against its first parent with
`check --format json`. The members are in-sample commits that nobody
adjudicated, so these are counts of commits, not false-block rates. R29 is
the fixed corpus (SHA256 `f6281caa…`): the last 300 non-merge commits of six
Python and six JS/TS repositories. D-088's sets (SHA256 `6e2e7d7c…`) are the
commits of ten Python histories that change a conftest or a skip or xfail
line, about 2.6% of their 34,873 non-merge commits, and 368 of pytest's.

| option | R29 Python (1,800) | R29 JS/TS (1,800) | D-088 (1,263) | fixtures |
|---|---:|---:|---:|---:|
| A: the five weakening rules, every language | 7 (30) | 55 (383) | 50 (135) | 18 |
| **R: A and the stand-in and subject rules; JS/TS loosening only** | **7 (30)** | **11 (27)** | **53 (140)** | **22** |
| R8: R, and no D8 | 17 (86) | 11 (27) | 88 (552) | 25 |
| C: no production credit for any oracle rule | 55 (182) | 86 (596) | 91 (256) | 51 |
| B: `oracle_freeze` always | 73 (265) | 92 (706) | 188 (922) | 100 |

Each cell counts pass → block commits, with the new high findings in
parentheses; each needs one exemption to pass. No option moves a commit
block → pass or changes an error. Base blocks 66 R29 Python commits, 39
R29 JS/TS commits and 369 of D-088's. @@IMPL_RERUN@@

The moved commits, by option R:

- R29 Python: httpx `8e36f2bc`, `57daabf6`, `b82fbe2c` and `1d73150c`;
  starlette `2c614b91`; rich `b93d3b6d`; click `ad39d749`.
- R29 JS/TS: hono `5463db27`, `c831020f` and `f0b094db`, three
  security-advisory merges; typeorm `324c46cd`, `46d5b843`, `b9aa8355`,
  `c6745f3d`, `df09802e` and `ff00a3cd`; undici `2764d996`; vue-core
  `8b44b021`.
- D-088: 53 commits, among them all 11 that stopped #464 (D-171): httpx
  `0296c2bb`, starlette `e396f079`, werkzeug `ab6150fa`, scrapy
  `d0dabbc0` and `d1bd8eb4`, and pytest `158e1608`, `4d49ba65`,
  `4ee3831a`, `cf5b544d`, `ef732fc5` and `f6caf230`.
  [benchmarks/d199-repair-refusal.json](benchmarks/d199-repair-refusal.json)
  lists every moved commit with its rules.

They remove deprecated APIs with their tests, drop old Python versions or
dependencies, or rewrite tests beside a behaviour change. Some are detector
misreadings that repair evidence used to absorb: httpx `0296c2bb` adds an
`isinstance` check beside an unchanged equality, and requests `2a6f290b`
only drops `u''` prefixes.

**What stays open** (THREATMODEL item 4 and rows 2, 56, 93, 130, 131):

- an expected value rewritten to the code's wrong output, or an assertion
  substituted for one of equal strength, beside a no-op edit;
- a renamed private symbol escorting a test deletion into D8;
- in JS/TS, a removed assertion or a deleted test beside any module edit.

Static analysis cannot close them. Running the old tests against the new
code would, and checkwash does not run the code it checks.

**Expectation moves (AGENTS.md rule 2).**

- **Fixtures.** 21 keep their inputs byte for byte, move to a `_pos` name
  and expect high with `REPAIR_EVIDENCE_REFUSED`; each one's meta names its
  old case. From `_neg`: `build_makefile_stays_prod`,
  `c_extension_still_opaque`, `deleted_prod_related`,
  `deploy_script_still_opaque`, `fixture_producer_subject_input_changed`,
  `issue419_narrow_js_broad_template`,
  `opaque_residual_js_assert_weakened_template`, `repair_via_helper`,
  `route_a_assert_weakened_plus_zero`, `route_a_fixture_producer`,
  `route_a_skip_marker_plus_zero`, `runner_build_makefile`,
  `runner_one_hop_build`, `runner_opaque_native`,
  `runner_package_json_dependency_bump`,
  `runner_word_in_production_script_prose`, `subject_input_repair`,
  `subject_normalized_repaired` and `unparseable_prod_still_opaque`; and
  `fixture_producer_annotated_class_methods`, whose `SUBJECT_INPUT_CHANGED`
  moves while its six expected-value findings stay at warn. From `_warn`:
  `assert_weakened_with_prod_change`. `conftest_hook_guard_opaque_prod_neg`
  keeps its name and inputs and is held by `COMPAT_GATE` instead of
  `REPAIR_EVIDENCE`, as under #464. Eight of these are D-171's restored
  set.
- **Unit tests.**
  - `tests/test_issue419_residual.py` pins D-199's statement instead of
    D-191's. The four unit-scoped weakening rules refuse both routes. New
    tests pin the routes that stay open for a rewritten expected value,
    each kept shape and each opaque file. The one-hop, path-order and
    call-on-call pins keep their reading, with the refusal label where the
    hop reaches. JS/TS splits into the loosening shapes, refused, and the
    removals, kept, a deleted test among them. An `except`-guarded suite
    control refuses Route B, and an `if`-guarded one is held by
    `COMPAT_GATE` beside an opaque edit. The `fail_on = "warn"` and
    `oracle_freeze` tests use the open route, and a new test pins the
    refusal label beside `ORACLE_FREEZE`.
  - `tests/test_issue419_narrow_broad_except.py`: #464's former members
    refuse every evidence, and a named but missing unit blocks with the
    refusal label.
  - `tests/test_issue196_guard_removal.py` and
    `tests/test_issue196_setup_guards.py`: a removed skip guard beside a
    production change blocks (renamed).
  - `tests/test_issue208_209_suite_guards.py`: the guarded hook beside an
    unguarded drop is held by `COMPAT_GATE` (renamed).
  - `tests/test_issue415_oversized_sources.py`: a read side blocks with the
    refusal label, an unread one with `NO_PROD_CHANGE_IN_DIFF`.
  - `tests/test_issue471_fixture_producers.py`: the inline spelling blocks
    with the refusal label.
  - `tests/test_js_predicate.py`: S1, a weakened JS/TS assertion, moves to
    its own test, which blocks.
  - `tests/test_pre_tool_use.py`: the Stop hook now blocks the
    bought-evidence change as well.
  - `tests/test_test_support_paths.py`: the data edit is still evidence,
    refused (renamed).
  - `tests/test_task_repo_relative_authority.py`: its scenario becomes a
    rewritten expected value, so the contract still decides the verdict;
    the pinned fingerprint follows.

**Maintainer text.** This entry; SPEC §5 (the D1 and E1 rows, clause 3,
the new *Rules that take no repair evidence* paragraph and the
`BROAD_EXCEPT_ADDED` paragraph); THREATMODEL item 4 and rows 2, 56, 68, 87,
89, 93, 103, 106, 130 and 131; and `gating.py`'s escalation policy.

**What runs before merge.** On LAPTOP-01AGNPJU (`HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL`): the full
suite at the final head, the documentation and count tests, checkwash's own
check on the pull request's range at `--fail-on high`, and the pull
request's PJU receipt, whose intake sets the four required checks. Other
platforms: NOT_RUN. Hosted test workflows remain disabled. The 0.12.0
release's fixed-corpus comparison lists the moved commits for Nelson before
the tag, as every release's does. @@REVIEW@@

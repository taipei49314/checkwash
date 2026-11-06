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
  That message showed options C and B on D-088 as still running; they
  finished at 17:52:34Z, after all three answers. Option R's own cost was
  measured before the choice.
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
or rule 2 changes, and the pull request asked him to approve them by name
before it merges. At 2026-11-06T11:49:53Z, to Claude's question
"Approve #588's L1–L4 and #589's L1–L3 as their PR descriptions list
them?", he chose the button 「兩個 PR 全部核可」 (approve everything in both
pull requests), which Claude wrote. L1 to L4 of #588, this pull request,
are this entry with the SPEC and THREATMODEL text and the escalation
policy, the 22 fixture moves and the new fixture, the test pins, and the
28 allow keys. The answer approves the listed items, not the merge.
Every detail not quoted above is Claude's under the 2026-10-27 delegation
(「Checkwash 一樣給你」: 0.x autonomous, stop before 1.0). None of it is
Nelson's personal review.

**What is decided.**

1. For a finding in a `.py` file, which in practice is a test or conftest,
   these rules take no repair evidence: `ASSERT_WEAKENED`, `ASSERT_REMOVED`,
   `TEST_DISABLED`, `TOLERANCE_LOOSENED`, `BROAD_EXCEPT_ADDED`,
   `TEST_PATCHES_SUBJECT`, `CONFTEST_PATCHES_PROD`, `SUBJECT_NORMALIZED`,
   `SUBJECT_INPUT_CHANGED` and `EXPECTED_VALUE_DERIVED`. That is SPEC §5's
   clauses 1 and 2 (Route A) and clause 3 (Route B) alike
   (`gating.REPAIR_REFUSED_PYTHON`, option R). An import-shadow stand-in is
   a Python finding wherever it is reported, on the production module it
   shadows or on the pytest configuration or runner script whose search path
   lets it win, and is refused there too.
2. For any other finding, which is in a JS/TS test or a unit-less stand-in
   reported on `package.json`, `ASSERT_WEAKENED`,
   `TOLERANCE_LOOSENED`, `BROAD_EXCEPT_ADDED` and a `TEST_DISABLED` that is
   no removal shape take none (`gating.REPAIR_REFUSED_JS`). A removed
   assertion, a deleted test and rows deleted from a table keep clause 3,
   the only evidence a JS/TS test can earn.
3. The removal shapes are a unit that disappeared, as the finding's own
   shape says, and rows deleted from a parametrize table the test already
   had while a row still runs and none is marked off. A row marked off with
   `pytest.param(..., marks=skip)`, rows deleted beside one, and a table
   left with no row to run (a plain test wrapped in an empty table, Python's
   proven empty parameter set among them, or a table emptied where it
   stands) are in-place disables, not removals, and only the finding of the
   lost rows reads them, not a skip guard made always true on the same
   unit. Before the D-199 reviews
   `_prod_removal_shape` read all of them as removals, which also let D8
   hold them beside a removed symbol, against D8's SPEC row ("never an
   added marker"); D8 follows the stricter reading too. Two readings stay as
   on main: a JS/TS plain test paired with a table whose rows cannot be
   counted is a removal (428.Q2a), because tests folded into an imported
   table read the same way and a deleted JS/TS test keeps the credit
   anyway; and where the two tables' rows cannot be paired (a column added,
   the table moved into a constant or a function) a row marked off counts
   as deleted.
4. A refused finding that the evidence reached, and that nothing else
   holds, is high with the new E1 label `REPAIR_EVIDENCE_REFUSED`. One that
   no evidence reached keeps the label it had. The label stays outside the
   fingerprint; `FINDINGS_VERSION` and `IR_VERSION` do not change.
5. Nothing else in gating moves: D2, D4 to D7 and D10, `MILD_WEAKENING`, the
   expected-value rules' and `ASSERT_SUBSTITUTED`'s evidence,
   `PACKAGE_REPAIR` and D9, suite controls and E2.
6. This supersedes D-171's K1 for these rules. D-141's stop line ("any
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
R29 JS/TS commits and 369 of D-088's. C also refused `PACKAGE_REPAIR` and
D9: 30 of its 55 R29 Python commits lost only those two credits.
Built, the implementation was re-run on both samples three times, each
time with a copy of the branch's `src/`: at `421f8b94`, after the first
review (`cca0d696`) and after the second (`src/` tree `8ef8bb69`,
`gating.py` SHA256 `f069f5fe…`). Each time every member's exit, verdict and
findings equal option R's, rule, path, unit, fingerprint, severity,
de-escalators and shape included. Only the labels differ:
`REPAIR_EVIDENCE_REFUSED` where R printed `PROD_CHANGE_NOT_EVIDENCE`, on
1,093 of D-088's findings and 76 of R29's. So nothing the two reviews
changed (item 3 and the import shadow) moves a member of either sample, and
the costs above are the implementation's.

The moved commits, by option R:

- R29 Python: httpx `8e36f2bc`, `57daabf6`, `b82fbe2c` and `1d73150c`;
  starlette `2c614b91`; rich `b93d3b6d`; click `ad39d749`.
- R29 JS/TS: hono `5463db27`, `c831020f` and `f0b094db`, three
  security-advisory fixes, each titled "Merge commit from fork"; typeorm
  `324c46cd`, `46d5b843`, `b9aa8355`, `c6745f3d`, `df09802e` and
  `ff00a3cd`, behaviour fixes, a new default and a deprecated-method
  removal; undici `2764d996`; vue-core `8b44b021`.
- D-088: 53 commits, among them all 11 that stopped #464 (D-171, D-172):
  httpx `0296c2bb`, starlette `e396f079`, werkzeug `ab6150fa`, scrapy
  `d0dabbc0` and `d1bd8eb4`, and pytest `158e1608`, `4d49ba65`,
  `4ee3831a`, `cf5b544d`, `ef732fc5` and `f6caf230`.
  [benchmarks/d199-repair-refusal.json](benchmarks/d199-repair-refusal.json)
  lists every moved commit with its rules.

They remove deprecated APIs with their tests, drop old Python versions or
dependencies, or rewrite tests beside a behaviour change. Some are detector
misreadings that repair evidence used to absorb: httpx `0296c2bb` adds an
`isinstance` check beside an unchanged equality, and requests `2a6f290b`
only drops `u''` prefixes. One more honest shape blocks that the samples do
not show: a skip added for an optional dependency in the change that adds
it (`pytest.importorskip`, a `find_spec` `skipif`), because D6 credits only
interpreter and OS conditions on a test's own marker. And removing one
assertion is treated more harshly than deleting its test: an assertion
removed together with the deprecated API it checks blocks, while the whole
test deleted beside the same removal is held by D8.

**What stays open** (THREATMODEL item 4 and rows 2, 56, 93, 130, 131), each
beside a no-op edit:

- an expected value rewritten to the code's wrong output, or an assertion
  substituted for one of equal strength, and two spellings the review found
  that carry a refused event there: a weakening written as an exact
  comparison (`assert (total > 0) == True` reads as an expected value
  changed) and an expectation computed from the subject through a module
  alias (`calc.compute(2)` reads as `EXPECTATION_DEFINITION_CHANGED`);
- a renamed private symbol escorting a test deletion into D8, and D8
  counting a row marked off as deleted where the rows cannot be paired;
- in JS/TS, a removed assertion or a deleted test (a plain test paired with
  a table whose rows cannot be counted reads as one), a test parked where
  no code runs (`if (false) { test(...) }`, which row 159 gives a
  deletion's key), and the stand-in and subject rules (`vi.mock`, a
  `test.each` input cell), beside any module edit.

Static analysis cannot close the no-op routes. Running the old tests
against the new code would, and checkwash does not run the code it checks.

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
  set. `oracle_freeze_pos` keeps its expectation, which still matches, but
  its finding now carries `REPAIR_EVIDENCE_REFUSED` beside `ORACLE_FREEZE`
  and would block without the freeze; the new
  `oracle_freeze_expected_value_pos` is the case where E2 still changes a
  severity.
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
  - `tests/test_d199_repair_refusal.py`, new: the Python stand-in and
    derived-expectation refusals; the JS/TS tolerance refusal, rows deleted
    from a table (kept) and a plain test wrapped in an empty table (refused);
    a row marked off is no removal for D8; and pins for the open routes
    (the respelled weakening, the module alias, the D8 rename, the JS/TS
    stand-in, the parked JS/TS test) and for the optional-dependency cost.
    The second review added eight: rows deleted beside a row marked off, a
    table emptied where it stands, a Python test wrapped in an empty
    parameter set, a guard made always true beside deleted rows, a skip
    beside a deleted namesake and an import shadow reported on a pytest
    configuration, each failing on `cca0d696`'s or `421f8b94`'s code, and
    open-route pins for a row marked off where the rows cannot be paired
    and for tests folded into an imported table.
  - `tests/test_oracle_rules_pinned.py`: freezes both refusal sets.
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
  - `tests/test_finding_shape.py`: its synthetic unit becomes a table that
    lost a row, the shape `_prod_removal_shape` still reads as a removal.
  - `tests/test_subject_snapshot_integration.py`: pins the exact label
    `PROD_CHANGE_NOT_EVIDENCE`, which alone now tells "no evidence" from
    "evidence refused".

**Maintainer text.** This entry; SPEC §4 (the `EXPECTED_VALUE_DERIVED`,
`EXPECTATION_DEFINITION_CHANGED`, `SUBJECT_NORMALIZED`,
`SUBJECT_INPUT_CHANGED` and `TEST_PATCHES_SUBJECT` rows and the
`BROAD_EXCEPT_ADDED` paragraph) and §5 (the D1, E1 and D8 rows, clause 3
and the new *Rules that take no repair evidence* paragraph); THREATMODEL
item 4 and rows 2, 56, 68, 72, 74, 87, 89, 93, 103, 104, 106, 107, 116,
130, 131, 135, 137, 146 and 158; and `gating.py`'s escalation policy: the
two refusal sets, `_prod_removal_shape`, `_refuses_repair_evidence`, and
the lines of `apply_gates` that decide which findings are Python, apply
the refusal and choose the E1 label.

**What runs before merge.** On LAPTOP-01AGNPJU
(`HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL`): the full suite at the final
head, the documentation and count tests, and the pull request's PJU
receipt, whose intake sets the four required checks. Other platforms:
NOT_RUN. Hosted test workflows remain disabled. checkwash's own check on
the pull request's range blocks on the findings its test rewrites raise,
whatever the engine, as #553's did for D-171; as #554 did then, a separate
allow-keys pull request, approved by Nelson fingerprint by fingerprint,
merges first. The 0.12.0 release needs a new D-176 cost disposition, as
the 0.11.0 one covers only that release's `src/` tree, and its
fixed-corpus comparison lists the moved commits for Nelson before the tag.

**Review.** Frozen at `421f8b94`, the change was reviewed by five Claude
sub-agents, each with one lens (gate logic, a bypass hunt, the protected
text, tests and fixtures, docs and records), and by one Gemini 4 Argon run.
`agy` updated itself to 1.5.1 during Argon's first run, which also failed on
a path the model mistyped; the new binary was re-verified, read-guard test
included, and the rerun completed. Claude checked every finding against the
source, the records or a toy repository before using it, and the review
changed:

- `_prod_removal_shape` (item 3), raised by Argon (its F3 and F4) and the
  gate-logic lens;
- the scope wording of items 1 and 2: the code always applied the Python
  list to `.py` files, not to tests and conftests only;
- the open-route lists, which left out the JS/TS stand-in and subject rules
  (Argon F1, F2), the parked JS/TS test (Argon F3), and the respelled
  weakening and the module alias (bypass hunt);
- SPEC §4's four rows, THREATMODEL rows 72, 74, 87, 103, 107, 116, 135, 137,
  146 and 158, and comments in `gating.py`, `ir/model.py` and four
  detectors, which still described the old behaviour (Argon F5 to F8 and
  three lenses);
- the tests: both refusal sets frozen, `tests/test_d199_repair_refusal.py`,
  a label pin that had lost its power, the E2 fixture and fixture meta
  lines;
- this entry: C's description, the timing of C and B on D-088, the
  allow-keys step, the D-176 disposition and the attributions above.

Findings raised by Argon are used as "raised by Argon, verified by Claude".
Two holes the bypass hunt found predate D-199 and go to follow-ups: a
test-only rewrite of a container expectation that `MILD_WEAKENING` holds at
warn (`== [0, 2, 4]` to `== list((1, 3, 5))`), and weakenings that give no
finding at all (`type(x) == int`).

Frozen at `cca0d696`, the fixes had two Claude re-reviews, one on the code
and tests and one on the text. Claude checked each finding with a toy
repository, and the second review changed:

- `_prod_removal_shape` again (item 3). A unit that disappeared is read
  from the finding's own shape: two JS/TS tests can share a title, the unit
  index keeps the last, and a skip on one beside the deletion of its
  namesake read as a removal. Rows deleted beside a row marked off, and a
  table left with no row to run, are no removal: Python's proven empty
  parameter set gives the plain side a count of one, so D8 still held a
  test wrapped in it. A JS/TS plain test paired with a table whose rows
  cannot be counted is a removal again, as on main: the first review's
  reading blocked tests folded into an imported table beside a module
  edit, which neither sample has, and closed nothing a deleted test does
  not already keep.
- Which findings are Python. An import-shadow stand-in reported on a
  pytest configuration took the JS/TS list and kept the credit, while
  THREATMODEL row 130 called the route closed; it is refused now.
- The text: the open-route lists, the reach of the PreToolUse ask (it does
  ask before a Python test deletion, row 56's included), THREATMODEL rows
  72, 93 and 104, which still described the old behaviour, row 131's
  commit descriptions, SPEC §4's `EXPECTATION_DEFINITION_CHANGED` row, the
  scope wording, the cost of removing one assertion against deleting its
  test, and this entry's maintainer-text list.
- Eight new pins (above).

Then the final code was re-run on both samples (*What it costs*).

## D-200 (2026-11-06): from v0.12.0 the release tag points at the release's Action commit A, and the README installs the CLI only from PyPI and the pyz

**Approval.** Claude wrote this entry in the pull request that implements
it, #589. `DECISIONS.md` is maintainer text (AGENTS.md), so the pull
request asked Nelson to approve it by name, with its test changes and one
allow key (L1 to L3). At 2026-11-06T11:49:53Z, to Claude's question
"Approve #588's L1–L4 and #589's L1–L3 as their PR descriptions list
them?", he chose the button 「兩個 PR 全部核可」 (approve everything in both
pull requests), which Claude wrote. The answer approves the listed items,
not the merge.

**Authority.**

- D-196 item 3 ([DECISIONS-archive-4](DECISIONS-archive-4.md), 2026-11-02)
  records the approval. At 15:24:21Z Nelson answered Claude's three
  questions with one message of three lines, 「1.接受寫文件」 / 「2.核可」 /
  「3.放寬」; its second line approved pointing the tag at the Action commit
  A. Told of its cost, that a CLI installed from the tag would be A, whose
  `doctor` does not accept its own release's pin, he chose at 15:30:53Z the
  button 「0.11 照 S，0.12 改」 (0.11 with scheme S, change it in 0.12).
  D-196 left the design to go to him before it was built.
- Claude's design of 2026-11-05 (written on LAPTOP-01AGNPJU, not in the
  repository; one read-only Claude sub-agent reviewed its draft against main
  `7cd8549c`, and Claude verified and applied all 11 findings) gave the
  places to change and four options for a CLI installed from the tag. At
  about 17:40:16Z on 2026-11-05 Nelson chose the option labelled
  「甲：拿掉那行（建議）」 (甲: remove that line, recommended): the README's
  "or from the release tag" install line goes. At 17:42:17Z he chose the
  button 「開始實作」 (start implementing) to Claude's question
  「0.12 這兩項要開始實作嗎？」 (start implementing these two 0.12 items?).
  The second item, the change to D-191's residual, is a separate change.
- Claude wrote the questions, the options and the button labels. These
  answers choose the change; they are not Nelson's review of this text or of
  the code. Every detail not quoted above is Claude's, under Nelson's
  2026-10-27 delegation (「Checkwash 一樣給你」: 0.x autonomous, stop before
  1.0; [RELEASING](docs/RELEASING.md)), including the boundary's form, the
  tag message's format, every check below and this entry's wording.

**Why.** Under scheme S (D-194) the README recommends the Action commit A,
`vX.Y.Z^2^1`, while the tag points at the release merge M. Pin updaters such
as Dependabot and Renovate then propose the tag's commit, which `doctor`
rejects; zizmor's `ref-version-mismatch` can report the pin's comment; and
`git ls-remote` cannot show the pin. With the tag on A, the recommended pin is
the tag's commit again (each inferred from the tools' documentation, not
run). A release still has two commits, because a commit cannot name itself:
the distributions are built from M, whose `doctor` accepts A.

**What is decided.**

1. *One version boundary.* A release tag at or above v0.12.0 points at the
   release's Action commit A, and its message holds exactly one line
   `Release-Merge: <M>`, M's 40 lowercase hex digits, where A = `M^2^1` and M
   has scheme S's shape (D-194). A tag up to v0.11.x points at M, as before.
   The version selects one rule, never either. The boundary, the message
   parse and the doctor rewrite of item 5 live once, in
   `tools/published_release_identity.py`, which every release tool already
   loads or audits. A line that starts with the key in another case or after
   spaces counts as a second line, and any character other than printable
   ASCII and a line feed is refused: a carriage return or a Unicode line
   separator can split a line for a reader, and an invisible character can
   hide the key.
2. *The release bridge* (`tools/pju_release_bridge.py`). At `tag`,
   `release-event` and `public-visitor`, `live_subject` reads R's commit
   object from GitHub after M's, which it already read: M's parents are
   [base, R], R has one parent, A, and the tag must peel to A. The tag's
   message must name the subject's head M, and at `release-event` the capture
   run's workflow commit must be A. `validate_visitors` binds the tag source
   receipt and the tag visitor to A and A's tree. M stays every stage's
   head. `verify_admitted` also compares the trusted checkout's
   `published_release_identity.py` with the trusted ref, since the bridge now
   applies the tag rule from it.
3. *The release-event capture.* The `release: published` event runs at the
   commit the tag points to, A. From v0.12.0 the capture reads M from the
   tag's message, checks through GitHub's commit objects that `M^2^1` is the
   event's commit, and records M as the head, so the subject's base, tree and
   head stay M's. It reads only the tag, tag-object and commit endpoints the
   capture and its native check already read. Whether M is the real release
   merge, the chain decides: the tag stage's head, the main stage's report,
   `refs/heads/main` and the merged pull request.
4. *The collector* (`tools/collect_pju_release.py`). At `tag` and later the
   local annotated tag must peel to `M^2^1` and its message must name M. A new
   argument, `--tag-source`, a clean checkout of A with the tag, is required
   from v0.12.0 and refused before it and at `pr` and `main`. Preflight
   checks it, clean at A and holding the subject's tag object, before the
   suite and the builds run, and the stage steps compare it again after
   them. The tag source
   receipt runs on it, since `tools/verify_published_source.py` requires the
   source commit to be checked out, and the tag visitor expects its members.
   That receipt now proves that the tag and A agree, not that the tag and M
   agree; scheme S's one-line relation and the bridge's native reads carry
   the binding from A to M.
5. *The verdict gate* (`tools/verdict_gate.py`, option A of the design). On
   a tag run from v0.12.0, HEAD is M, the pushed tag must point at
   `HEAD^2^1`, and its message must name HEAD. For a pinned engine whose tag
   is at or above v0.12.0, its commit is the tag's, A, and the pyz's
   `checkwash/*` members must equal A's `src/checkwash` with `doctor.py`'s own
   Action pin line set to A, which is what R does and what the release bridge
   verified when M's tree was R's. The line is set only when A's two pin
   lines are equal; otherwise the identity fails, so a wrong rewrite can only
   fail to match a pinned pyz. The bridge's `validate_verdict` applies the
   same rule (`engine_source_members`). The pins format does not change.
6. *`tools/own_action_pin.py`.* `tag --head <M> --base <base>` prints
   `git tag -a vX.Y.Z <A> -m "CheckWash vX.Y.Z" -m "Release-Merge: <M>"`
   for a v0.12.0 or later release merge that the scheme S rule verifies, and
   refuses an earlier one. From v0.12.0 `check --stage tag` requires
   `--main-report` and `--trusted`, and before the push it checks: the local
   annotated tag object is named for the release and points at A itself,
   not at another tag, A being what the rule found to be `M^2^1` with the
   one-line relation, and its message names M; M is the head of the main
   stage's verified report and the remote's `refs/heads/main`, since a
   test-merge commit of an open pull request also has A as its `^2^1`; and
   A holds the trusted ref's bytes of `release.yml`, the release bridge and
   the helpers they load or audit, which the release-event capture runs from
   A. Before v0.12.0 `check` refuses those two arguments and runs as before.
   These checks are advisory and local, not release evidence.
7. *Option 甲.* The README's "or from the release tag" install line is
   removed, and the README installs the CLI only from PyPI and the pyz,
   which are built from M. The README's pin section, action/README,
   `docs/enterprise.md` and KNOWN-ISSUES-next say that from v0.12.0 a CLI
   installed through Git from the tag is A's and its `doctor` rejects that
   release's own pin. `doctor`'s code does not change.
8. *Documents.* RELEASING (steps 5 to 9, the scheme S section with a new
   *From v0.12.0* part and a 0.12.0 bootstrap note, the published-source
   paragraph, the responsibility checks and the verdict-gate sequence), the
   README and action/README pin sections, SECURITY.md, `docs/enterprise.md`,
   KNOWN-ISSUES-next (a new 0.12 candidate section),
   `docs/published-release-baseline.md`, `docs/pju-release-handoff.md`,
   `docs/releases/README.md`, the publication record template (which now
   records both A and M), the header comment of
   `tests/verdict_gate/baseline.toml` and the verdict gate's docstring
   describe 0.12 with 0.11.0 as the exception. The disabled `ci.yml`,
   `assertion-qualification.yml` and `verdict-gate.yml` note that their
   tag-push path does not follow this entry; none is re-enabled.

**What is not changed.**

- Scheme S's core: A, R as the last commit, the merge commit only, M with
  R's tree, a `doctor` that accepts the previous pin and its own A, and the
  CLI upgraded before the Action pin.
- v0.11.0 as published: its tag stays on M, its pin on `v0.11.0^2^1`, and its
  pin-updater and zizmor consequences (D-194, D-196) stay.
- `src/`: `doctor`'s code and `check`'s verdicts, exit codes and messages.
  SPEC, THREATMODEL, `tests/gates/**`, the gating severity table, the
  strength lattice, alignment parameters and every `.gwcase` expectation.
- `release/advertised.toml`'s format, meaning and values: `commit` is the
  tag's peeled commit, M for v0.11.0 and A from v0.12.0.
- The receipt, subject, admission and dispatch schemas, the verification
  report's fields, and the workflow inputs. The subject's head is M at every
  stage.
- `tools/verify_published_source.py`, `tools/release_inventory.py`,
  `tools/replay_pju_action.py`, `quality-candidate-intake.yml`, and the
  `publish-assets` and `pypi` jobs of `release.yml`, which check out the
  admitted head, M.
- The owner-ruled fixed-corpus candidate rule (R29, amended by D-196). Its
  text names the commit to be tagged, which from v0.12.0 is A. A's `src/`
  differs from M's only in `doctor`'s own pin line, which the rule already
  allows, so the candidates it admits are unchanged and its text is not
  edited.

**Risk.** The new path first runs against a real tag and a real release
event at 0.12.0: the bridge's tag rule, the release-event capture, the
collector's tag stages, the verdict gate's tag rule and, after step 9, the
baseline binding. D-196 said the new path's first real run would be a
release. A tag cannot be moved, and the release-event capture runs the
bridge from A, so a fault found after the push may cost a v0.12.1. What
lowers it: each new check runs both ways on owned Git chains and owned
native metadata, the capture included, which had no test before; the message
parse is calibrated on the real v0.11.0 tag object, read with a read-only
`gh api` call on 2026-11-06 Asia/Taipei, whose `message` is the tag object's
bytes after its headers, with LF line breaks; the capture reads no new
endpoint; and `check --stage tag` runs the three checks before the push. The
design also planned to re-run the tag stage's offline parts with the new
tools before the push. Only `check --stage tag` can run then: the
collector's tag stage starts from the captured subject, and the verdict
gate's tag rule reads the pushed tag's public metadata, so both first run on
the pushed tag. A private rehearsal repository with a real tag and release,
which the design offered at about half a day, was not made. One check still
reads the tag's commit as the head: the published baseline evidence compares
each relevant tag with the pushed tag's commit, A from v0.12.0, while the
local set of merged tags is read from HEAD, M. A relevant tag that M reaches
and A does not fails the tag rule with an ancestry message. Scheme S's
merge-tree rule leaves room for one only when the release pull request
already carries that tag's changes, so it is left as it is.

**Maintainer text.** This entry only. RELEASING's fixed-corpus *Candidate*
and *Record* bullets, which carry the owner ruling, are not edited.

**Test expectations.** No `.gwcase` fixture and nothing under `tests/gates`
changes. Existing assertions edited, all in `tests/test_packaging.py`:

- `_release_action_commit` covers three eras. From v0.12.0 it reads M from
  the tag's message, on one `Release-Merge:` line, rebinds `tag_commit` to M
  so that v0.11.x's checks run on M unchanged, and then requires the tag's
  peeled commit to be `M^2^1`. Below v0.12.0 every outcome is unchanged.
- `test_readme_action_snippet_is_zizmor_blanket`: two `if legacy:` guards
  become `if legacy or tagged_at_action:`, so from v0.12.0 the README's
  `^{commit}` string and action/README's `git ls-remote` line for the tag
  are required again. One assertion message changes. At v0.11.0, the trusted
  tag today, every outcome is unchanged.
- `test_readme_install_refs_match_advertised_release`: option 甲 removes the
  README's only `@vX.Y.Z` install reference, so `pinned` also takes the
  versions of the `pipx install checkwash==X.Y.Z` lines, as tags, and a new
  assertion refuses a README line that installs the CLI through Git from
  this repository (`git+https://github.com/taipei49314/checkwash@…`), at a
  tag or any other revision; it does not read `git+ssh` or source-archive
  URLs, which the README does not use. `assert pinned` then
  requires any install reference instead of a Git or pre-commit one: a
  relaxation, recorded here to be reviewed by reading. checkwash's own check
  reports it: on the range from main `7cd8549c`, with this tree's engine,
  whose `src/` is main's, it blocks with one finding at high,
  `SUBJECT_NORMALIZED` on this test (key
  `SUBJECT_NORMALIZED/tests/test_packaging.py/test_readme_install_refs_match_advertised_release/v2:3aba30218692c60c75aa029a6b5027befa2bf3a4326425b921397c84cb3f30a2`,
  for this before and after pair), and five warnings. The allow file is
  read from the base side, so the pull request's PJU receipt, whose Action
  replay must pass at `--fail-on high`, can pass only after an
  owner-approved entry for that key is on main, as #543's were
  (`e94fe840`). The review built the alternative that needs no exemption,
  and checkwash passed it: the old test unchanged, the new assertion in a
  new test, and a pre-commit snippet with `rev: v0.11.0` in the README,
  which the old test reads. It brings back the README's pre-commit snippet,
  dropped on 2026-09-06 when the README became a quick introduction, so it
  is not taken here without Nelson's choice.

New: `tests/test_release_tag_at_action_commit.py` (79 tests) and
`tests/test_packaging.py::test_release_action_commit_from_v0_12_0_is_the_tag_commit`.
The documented test count moves to 22541 collected.

**What runs before merge.** On LAPTOP-01AGNPJU
(`HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL`): the targeted release-tool tests,
the full suite (`pytest tests`, `tests/gates` included), checkwash's own check
of the pull request's range at `--fail-on high`, and the pull request's PJU
receipt. No `src/` change, so no R29 or other differential runs. Other
platforms: NOT_RUN.

**Review.** Three Claude review sub-agents reviewed the frozen `051b608a`,
one on the code, one on the tests and bypasses, one on the text, with no
Argon run, as the design set. Claude checked each of their 19 findings
against the source; all held, none critical or high. The review commit
fixes or records each:

- a tag of a tag, which peels to A, passed `check --stage tag` while the
  bridge, which reads the tag object's own target, refuses it after the
  push: the check now requires the tag object's `object` to be A and its
  `type` a commit;
- the message parse read one line where a reader could see two (a Unicode
  line separator) or miss a key behind an invisible character: item 1;
- `--tag-source` was first checked after the suite and the builds: item 4;
- the files A must share with the trusted ref left out
  `tools/release_inventory.py`, which the bridge loads and audits;
- the tag records and the verdict engines were bound to A only by the
  code's shape: the bridge's `validate_tag_records` and
  `verdict_engine_source` now hold those bindings and run in tests;
- untested checks, now tested: the tag object's name, the main report's
  kind, the identity helper's trusted bytes, the capture's ref and tag
  names, R's native commit, a form feed in `doctor.py`, and a tag source
  that changes during the collection. Each of 15 mutants, one per check
  above that the review found untested or the fixes add, fails a test;
- the published baseline evidence's ancestry still reads A: the risk
  paragraph above;
- the text: RELEASING's local checks gave a v0.12.0 command the tool
  refuses; user documents stated unreleased v0.12.0 behaviour as current;
  SECURITY.md said the hosted CI matrix runs on every push; RELEASING
  described a hosted build job that no longer exists, from the tagged
  commit; the design's offline rerun was dropped without a word; v0.11.0
  was called the only tag on a merge; the publication template named the
  event SHA as the build's; and D-196 and the README test were quoted more
  broadly than they say.

## D-201 (2026-11-07): three holes beside D-191's residual close: an equality with `ANY`, a skip condition with a part checkwash cannot read, and `assertCountEqual` (0.12)

**Authority.**

- Claude's design of 2026-11-05 for D-196 item 4 (written on
  LAPTOP-01AGNPJU, outside this repository; D-199 records it) listed in its
  section 7 three holes that are not D-191's residual but sit beside it.
  Its red-team reviewer found them in toy repositories, and Claude ran each
  again: `assert total() == ANY` beside an unrelated version bump passed;
  D6 granted `COMPAT_GATE` to a skip condition that is always true once a
  part it cannot read is mixed in; and `assertEqual` -> `assertCountEqual`
  gave no finding. The design recommended closing them in 0.12, each priced
  on R29, with THREATMODEL rows 44 and 57 rewritten under Nelson's
  approval. D-199 did not take them, and the rows were not put to him.
- After #589 merged, Claude asked 「0.12.0 發版前，要先補 `== ANY`＋升依賴、
  恆真 skipif、assertCountEqual 這三個缺口嗎？」 (before the 0.12.0 release,
  close these three holes first: `== ANY` with a dependency bump, an
  always-true skipif, assertCountEqual?), with the buttons 「先補三個缺口」
  (close the three holes first) and 「直接發 0.12.0」 (release 0.12.0 as
  is). At 2026-11-06T15:33:38Z Nelson chose 「先補三個缺口」.

Claude wrote the question, the buttons and the recommendation. The answer
chooses to close the holes before 0.12.0; it is not Nelson's review of this
text or of the code. This entry and the SPEC and THREATMODEL text below are
agent-read-only, and the pull request asks him to approve them by name
before it merges. D6 is part of SPEC §5's escalation policy, so its change
below, made in `compat.py`, is in that approval too. Every detail is
Claude's under the 2026-10-27 delegation (「Checkwash 一樣給你」: 0.x
autonomous, stop before 1.0), including each rule's reach below.

**What is decided.**

1. *`ANY` is a tautology.* `unittest.mock.ANY` equals every value, so an
   `==`, a `self.assertEqual` or a `self.assertAlmostEqual` with it as one
   whole operand passes whatever the other side is (with `ANY` on the right,
   unless the left operand's own `__eq__` answers first). The Python
   frontend reads it as TAUTOLOGY (SPEC §3), so `== 6` -> `== ANY` is
   `ASSERT_WEAKENED`, which takes neither D9's `DEPENDENCY_DRIFT` nor, in a
   Python test, repair evidence (D-199). It read as an expectation changed
   to another name (`EXPECTATION_DEFINITION_CHANGED`), which D9 held at warn
   beside any version bump; the unittest spelling, `mocker.ANY` and `ANY` on
   the left gave no finding at all. `ANY` is read through the file's imports
   (`from unittest.mock import ANY`, `from mock import ANY`, an alias of
   either, `mock.ANY` or an alias of the module after its import,
   `unittest.mock.ANY`), so a project's own `ANY` constant is not mock's;
   pytest-mock's `mocker.ANY` is read by name. A bare name is read as Python
   reads it: the innermost function that binds it decides, then the module,
   so `ANY = 6` makes it a value, a parameter called `ANY` in another
   function changes nothing, and a name bound to mock's ANY (`wild = ANY`, a
   default of `mock.ANY`) is mock's ANY. The other spellings that hold for
   every value are read the same way: a chain of `==` each link of which has
   `ANY` on one side (`== ANY == 6`), `not (x != ANY)`,
   `pytest.approx(ANY)`, membership in a display that holds `ANY` (`x in
   [ANY]`, `assertIn(x, [ANY])`), and two displays of one kind and length no
   position of which is checked (`(total(), 0) == (ANY, 0)`), and a display
   shaped by the subject itself (`items() == [ANY] * len(items())`,
   `dict.fromkeys(record(), ANY)` against `record()`). A list, tuple or dict
   of nothing but `ANY`, nested, repeated (`[ANY] * 3`), a comprehension of
   it, `dict(total=ANY)` or `dict.fromkeys(keys, ANY)`, checks only its
   shape and reads as TYPE_SHAPE, against `assertCountEqual` too, which
   pairs each entry with one that compares equal. It keeps its source as its
   expectation, so `[ANY, ANY, ANY]` -> `[ANY]` is an expected value changed
   (main, which read the display as an exact expectation, blocked it as
   `EXPECTATION_DEFINITION_CHANGED`). `ANY in items()` says only that
   items() is not empty and reads as TRUTHY. `ANY` on the left is the
   expectation, as a literal there is. `!=` with `ANY` never holds and keeps
   its reading; so do the typed unittest variants, which check the operand's
   type first, and `ANY` as one entry of a display beside checked entries, a
   mild weakening. Still open (THREATMODEL row 182): `ANY` reached through a
   parametrize column, a fixture, another module's constant or a call, which
   reads as an expectation changed and is held at warn beside a version bump
   or repair evidence (rows 57, 93); a comparison wrapped in another (`(x ==
   ANY) is True`, `assertEqual(x == ANY, True)`) and a chain that joins `==
   ANY` to another operator, held the same way; mock's call objects
   (`call(ANY)`) and `assert_called_with(ANY)`, which are not read as
   assertions; and `self.assertTrue(x == ANY)`: no rewrite inside a truthy
   spelling gives a finding, `== 6` -> `== 7` included (row 149's family,
   deferred until after 1.0).
2. *A single test's skip must provably run somewhere.* D6 grants
   `COMPAT_GATE` to a single test's skip, in every D6 form except a
   conftest's suite-level collection control (a `skipif` mark, a non-strict
   xfail, a `pytestmark`, a string condition, an imperative skip in the
   body, in the setup the test runs or in a helper, and a later binding of
   the test's name), only when its condition is provably false in at least
   one environment of the matrix, so the test provably runs there. A part
   checkwash cannot read may be true: `skipif(sys.version_info >= (3, 0) and
   bool(sys.modules))` and `skipif(sys.platform == "win32" or
   bool(sys.modules))` earn nothing, while `skipif(MAC and not
   sys._is_gil_enabled())` keeps the credit, as it is false off macOS
   whatever the call returns. Before, the credit was refused only when the
   condition was true under every assignment of the unknown parts, so an
   unknown part stood in for the false case. This question reads each
   environment's interpreter, machine and architecture as they are, so a
   gate on one the matrix does not hold (`platform.machine() == "s390x"`,
   `platform.python_implementation() == "GraalVM"`) runs on those it holds,
   and one that lets the test run only there (`!= "s390x"`) is not shown to
   run anywhere. The gates a change adds must also leave, with the gates the
   test had, an environment where the test runs: one where every added gate
   is provably false and no gate it had is provably true. So a gate added
   opposite an existing one (`skipif(sys.platform != "win32")` beside
   `skipif(sys.platform == "win32")`, a `unittest.skipIf` or a strict xfail,
   by position or by `condition=`) earns nothing. Every gate whose condition
   the matrix can read somewhere, true or false, takes part, however it
   names the interpreter; a skip on an optional dependency is unknown
   everywhere and takes none, whatever its message says. A gate the test had
   is the same marker and condition on the base side (a quote respelled is
   the same), or, for a skip in the setup the test runs, in a helper or
   under a later binding, the same marker whose guard the change rewrote, as
   a branch added to a fixture's skips does; body skips are paired only by
   their conditions. A test its gates already kept from every environment
   the matrix holds (a Python 2 only test) gains and loses none, so only the
   added gate's own question is asked. The matrix reads what honest gates
   name: CPython 3.11 to 3.14 and PyPy at 3.11, the version it ships; each
   platform's two machines (`platform.machine()`: AMD64 and ARM64, x86_64
   and aarch64, x86_64 and arm64); `platform.architecture()[0]` as 64-bit;
   `sys.version_info`, `platform.python_version()` and
   `python_version_tuple()` with the micro release unknown, so `> (3, 11,
   0)` is true on every 3.11 release and `>= (3, 11, 1)`, which lets the
   test run only on 3.11.0, is not shown to run anywhere, while a slice or a
   substring of the version string inside its known part and `int()` of a
   version part are read; each equal, as a tuple or a string is, to nothing
   of another type (`sys.version_info != None` is true everywhere); `in`
   over a tuple, list or set display, each entry asked, so their order does
   not decide it; and an unknown entry of a tuple, which leaves it unknown
   rather than unequal. Four spellings of "on PyPy" are read:
   `platform.python_implementation()`, `sys.implementation.name`,
   `'__pypy__' in sys.builtin_module_names` and `hasattr(sys,
   "pypy_version_info")`, also in a conftest's or helper's guard. The last
   three are not compat tokens, so they earn the credit only when the mark
   or its guard also names one, its reason included. A suite-level
   collection control keeps the old reading (D-028, #209 Q1): its guard is
   its whole justification, and an optional-dependency guard
   (`find_spec("redis") is None`) is unknown everywhere. Liveness
   (`unit_is_live`), which decides whether a moved test still runs and
   whether a stand-in installation is looked for, keeps the old reading too:
   reading an unknown gate as dead would refuse an honest move and hide a
   stand-in. The old reading keeps a comparison with an interpreter or
   machine the matrix does not hold (`!= "IronPython"`) unknown, and reads
   the facts the matrix holds: `if sys.version_info > (3, 11, 0):` around a
   collection control is always true. Still open (THREATMODEL row 44): a
   conftest's drop and an opposite gate on the test it drops are judged
   apart; and a test that already ran only outside the matrix (on Python
   3.10 or older, on FreeBSD, on 32-bit) is not asked, so a gate added
   opposite one it had passes, as on main.
3. *`assertCountEqual` drops order.* An order-sensitive equality
   (`assertEqual`, `assertListEqual`, `assertTupleEqual`,
   `assertSequenceEqual`, `assertMultiLineEqual`, `assertDictEqual`, whose
   values assertCountEqual never reads, or a bare `assert a == b`) rewritten
   as `assertCountEqual` on the same subject is `SUBJECT_NORMALIZED` (SPEC
   §4), as `sorted(...)` around the subject is: the comparison stops
   checking order. Both read as one form and one strength, and there is no
   wrapper to see, so it gave no finding at all, beside a production change
   that reordered the result included. The operands are compared once each
   is followed through the unit's bindings and a copy into a list or tuple
   (`list(...)`, `tuple(...)`, `[*...]`) is taken off, eight steps at most,
   and each name inside an operand is followed one hop (`client.items()`
   with `client = self.client`), so a hoisted subject or expected value is
   the same rewrite. The expected list may change with it, reordered or
   spelled as a tuple, which assertCountEqual cannot tell apart; a literal
   both sides share is not a subject. The rule is asked before the strength
   check that hoisting the expected list lowers. A set operand never had an
   order, nor one `sorted(...)` already ordered, so that rewrite gives no
   finding; against a dict, assertCountEqual compares only the keys, and the
   finding says so. In a Python test the rule takes no repair evidence
   (D-199). The other direction, `assertCountEqual` -> `assertEqual`, starts
   checking order and gives no finding. Python 2's `assertItemsEqual` is not
   read as an assertion, so a rewrite into it reads as one removed
   (`ASSERT_REMOVED`).
4. *Documents.* SPEC §3 (TAUTOLOGY, TYPE_SHAPE and TRUTHY), §4
   (`SUBJECT_NORMALIZED`) and §5 (D6); THREATMODEL item 6 and rows 14, 44,
   55 and 57, which overstated what was closed: row 14 said order laundering
   was closed, row 44 and row 55 that unverifiable conditions earn nothing
   or count as dead, and row 57 that D9 covers only
   `EXPECTED_VALUE_CHANGED`; and a new row 182 for the `ANY` rewrite, partly
   closed. KNOWN-ISSUES-next's 0.12 section and STATE describe the change.

**What it costs.** Measured on LAPTOP-01AGNPJU
(`HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL`, Windows CPython 3.11.9) with the
engine at `bffc1f55` against main `54113c06`'s, whose rows on the two
samples are D-199's last re-run (its `src/` tree, `8ef8bb69`, is main's). On
D-088's 1,263 commits it moves two from pass to block, on R29's 3,600 one,
and on either it changes no other finding. The commit in both is rich
`655b5210cb`, which adds `skipif(sys.version_info.minor == 14 and
sys.version_info.major == 3)` to four tests already skipped on 3.11, 3.12
and 3.13: each then runs only on Pythons older than the matrix, for which a
single `skipif(sys.version_info >= (3, 11))` has never earned the credit
either. The other, scrapy `583df9f7d0` ("Simplify skipping uvloop tests"),
moves the uvloop skips of five tests into an autouse fixture that skips on
PyPy, on Windows or on one Twisted version. checkwash cannot read the
Twisted version, nor the fixture's check for the tests' marker, so the
fixture reaches all 110 tests in the two changed files and cannot be shown
to let them run anywhere: their `TEST_DISABLED` findings move from warn to
high. The out-of-sample set is every commit in D-088's six repositories
whose Python diff adds or removes a line naming `skip` or `xfail`, outside
both samples: 1,273 commits. On it the engine moves six commits from pass to
block, all from pytest's history between 2007 and 2013, when it ran on
Python 2: three skip on Windows through the py library's
`py.std.sys.platform`, which checkwash does not read (`96355656ce`,
`9643b7d6f8`, `0b7854d722`); two mark 30 tests each with `sys.platform ==
'win32' or getattr(os, '_name', None) == 'nt'`, whose second part it cannot
read (`5715bbd6f5`, `536252cb2e`); and one skips under `sys.version_info >=
(2,7) and` the output of a subprocess (`2a7c79dbf5`). One more,
`4d598370b4`, which blocks on main too, has 14 findings move from warn to
high. 85 of the commits could not be checked by either engine. The rule was
tuned on D-088 and, in its later rounds, on that out-of-sample set: the
engine at `2a05a379` moved seven of those commits from pass to block, two of
them through mistakes the next round fixed, so the set is no longer out of
sample either. Neither sample holds an `== ANY` or an `assertCountEqual`
rewrite, so those two rules' cost is unmeasured; in toy repositories they
also block honest edits: an exact expectation made `ANY` because the value
became generated, and a test made order-blind on purpose. These are commits
nobody adjudicated: counts, not false-positive rates.

**What is not changed.**

- `gating.py`, its escalation table and the strength lattice's values. D9
  keeps its three rules (SPEC §5's D9 row); an `ANY` rewrite leaves them
  because it is now a weakening.
- A suite-level collection control, liveness, and `guard_can_be_false` and
  `guard_always_skips`, which judge a suite control's guard and a guard's
  change, keep their reading, apart from the facts the matrix now reads.
- `ANY` as one entry of a display beside checked entries,
  `assertCountEqual` -> `assertEqual`, and a skip whose condition names no
  interpreter or OS, which never earned the credit.

**Review.** Five Claude review sub-agents reviewed `e67f6fd6`, one lens
each: the code, bypasses, the cost, this text and the tests. Claude checked
every finding against the source or a toy repository before acting on it.
They found that the stricter reading, applied to liveness as well, hid a
stand-in installation and refused an honest move of a gated test (liveness
now keeps the old reading); that two complementary gates, a list or set
display, a five-tuple version, a PyPy environment at a version PyPy does not
ship, an interpreter the matrix does not hold, `hasattr(sys, ...)` in a
conftest's guard, an import alias of `ANY`, a project's own `ANY` constant,
a chain, a display of nothing but `ANY`, a `len()` subject,
`assertAlmostEqual`, a hoisted or `list()`-wrapped operand, and a set or
dict operand were read wrongly (each fixed, with a fixture or a test); that
`assertItemsEqual` is never an assertion (dropped from the rule); and that
the cost numbers left out what the samples do not hold (stated above).

Two Claude sub-agents, one for the code with a red team and one for this
text, and a Gemini 4 Argon (High) run then reviewed the fixes at `2a05a379`;
Claude checked their findings the same way. Fixed, each with a fixture or a
test: the micro release, which the matrix held at 0, so a gate letting the
test run only on 3.11.0 earned the credit; a tuple with an unknown entry,
read as unequal; `in`, whose answer depended on the order of the entries; a
machine or interpreter the matrix lacks, which made honest gates block; the
joint check, which took in a dependency skip by its message, missed
`unittest.skipIf`, `skipUnless` and a strict xfail, refused a test its gates
already kept from every Python in the matrix, and read a fixture's rewritten
guard as a new gate; `ANY` nested, repeated, in a comprehension, in a padded
tuple, as a member, under `not (... != ANY)` and in `approx(ANY)`, a rebound
`ANY`, and the length or keys of a display of nothing but `ANY`, which the
shape reading had stopped seeing change (raised by Argon, verified by
Claude); and `list()` around a hoisted name, two hops, a reordered or tuple
expected list, `assertDictEqual` and `assertMultiLineEqual` in the order
rule. Not taken: two findings for one rewrite (the verdicts are right), and
Argon's claims about keyword operands, a size cap in `parse_expr`, `import
unittest as ut` and the measurement script, which the source and the toy
repositories did not bear out.

One Claude sub-agent then reviewed those fixes at `8747e88c`, the code with
a red team, and Claude checked its eight findings with the reviewer's toy
repositories and its own. Two were regressions the second round made: a
parameter or loop variable called `ANY` anywhere in the file turned the
reading of `ANY` off (now read through Python's scopes), and
`sys.version_info != None` read as unknown, so a guard made always true went
unseen (the release now equals nothing but a tuple, as a tuple does). Fixed
too: the joint check took gates in by a token in their text, paired body
skips by name in file order, keyed gates by their text and missed
`skipIf(condition=...)`; a bare `assert ==` rewritten as assertCountEqual
and a name inside the subject; `dict(k=ANY)`, a length or keys taken from
the subject, and `x in {ANY}`, which raises; and three honest gates and an
honest rewrite the second round blocked (a slice or `int()` of the version,
a `sorted(...)` subject). Not taken: the opposite gate added to a test that
ran only outside the matrix, and the spellings of `ANY` that wrap a
comparison in another or go through mock's call objects (both stated above).
These fixes were not reviewed again; the 218 toy cases of all three rounds
were run on them, and the 31 that moved each moved as intended. The full
suite then found the new reading of a bare name recursing on a megabyte-deep
expression; since `bffc1f55` it is walked with an explicit stack.
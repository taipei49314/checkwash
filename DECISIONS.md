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

## D-141 (2026-10-16): opaque-change evidence no longer holds a weakened oracle in a Python test (#419)

Oracle findings start at warn. E1 raises one to high only when it has neither
repair evidence nor a compensation. #419 showed that the evidence could be
bought with a no-op edit:
- **Route A:** any AST edit to a function the test calls that the fingerprint
  normalisation keeps (`+ 0`, a temporary, a dead branch, a rename).
- **Route B:** a byte change to an existing production file the engine does
  not parse (a template, C or Rust source, a data file, a shell script that
  runs no tests, any JS/TS module). It sets `prod_opaque_change`, which gave
  evidence to every oracle finding in the diff except an unguarded suite
  control (D-028; `gating.py:280-289`, `306-307` at 2c15f2d).

Either route held a weakened, removed or skipped assertion at warn, so it
passed at the default `fail_on = "high"`. SPEC §5 also listed an E3 that no
code implements (`gating.py:47-50`).

**Rulings** (owner, 2026-10-14, 「P1 全部照建議」; #419 issuecomment-6170353038):
- **419.Q1 (b).** `ASSERT_WEAKENED`, `ASSERT_REMOVED`, `TEST_DISABLED`,
  `TOLERANCE_LOOSENED` and `BROAD_EXCEPT_ADDED` refuse opaque-change evidence
  in Python test and conftest files. JS/TS tests keep it until #212 prices
  the change; the expectation family, `ASSERT_SUBSTITUTED` and `*_PATCHES_*`
  keep it in every language. Symbol evidence and compensations do not change.
  If (b) exceeds the Q6 line, the round stops and (d) comes back for a ruling.
- **419.Q2 (a).** Symbol evidence is unchanged. A report-only counterfactual
  arm counts the blocks (b) and (c) would add.
- **419.Q3 (b).** No new identity folds. Row 93 widens to any AST edit the
  normalisation keeps, within one hop (direct calls only for `TEST_DISABLED`),
  plus #420's hop once it lands. Row 4 stays a closure claim and sends kept
  in-symbol edits to row 93. SPEC §5 clause 1 says the normalized fingerprint
  changed, which is not a behaviour change, and the E3 row is marked retired.
- **419.Q4 (a).** README "Know the limits" and docs/enterprise.md name
  `gate.fail_on = "warn"` and a base-side `--task` contract with
  `oracle_freeze: true`, with each option's measured cost from this round's
  sweep. The text ships with or after #421's fix, not in this round's PR.
- **419.Q5 (b).** A refused opaque change keeps the E1 id and prints
  `OPAQUE_PROD_CHANGE_NOT_EVIDENCE`. An unguarded suite control keeps
  `COLLECTION_CONTROL_UNEXPLAINED`; `NO_PROD_CHANGE_IN_DIFF` is unchanged
  otherwise. "Unread" stays #448's word.
- **419.Q6 (a).** The acceptance line below, pre-registered before any
  engine runs.
- **419.Q7 (a).** Snapshot suppression is a THREATMODEL residual (row 132),
  including that any new `.py` file buys it, and a follow-up issue is filed
  (#463).
- **419.Q8 (a).** `ASSERT_SUBSTITUTED` and `*_PATCHES_*` stay out of this
  round. They are named as residuals (row 130) and get report-only
  counterfactual arms.

Rule 2: the expectation changes named in the recommendation are approved
exactly as described; anything else that moves stops and asks. The round
lands after #447 and #448, both merged.

**Second ruling** (owner, 2026-10-16, 「照建議a」; issuecomment-6209791221,
after the implementation stop issuecomment-6209672882). Two #448 rows that
the first ruling's analysis base predates move the same way as the seven
re-pins: `data_read` and `data_edited_at_the_limit` in
`tests/test_issue415_oversized_sources.py` keep their inputs and block with
`OPAQUE_PROD_CHANGE_NOT_EVIDENCE`; their block-side assertions accept that
label as well as `NO_PROD_CHANGE_IN_DIFF`; each gets an expectation-family
sibling that keeps `REPAIR_EVIDENCE` at warn. The new block for an
`except`-guarded (non-import) conftest control is the literal effect of
Q1 (b), needs no rule-2 approval, and is pinned by a new `_pos` fixture.

**The split, as implemented.** `gating.py` is the escalation policy, so this
is frozen-zone code approved by the maintainer, as in D-048.
`OPAQUE_REFUSED_RULES` holds the five rules. A finding whose rule is one of
them, whose file is Python (`FileIR.language`), and which is judged a test
or has role `conftest` (the set that makes `BROAD_EXCEPT_ADDED` an oracle
rule) does not take `prod_opaque_change` as evidence: with a unit, through
`_repair_evidence(opaque=False)`; without one, through
`_file_repair_evidence(opaque=False)`. Every symbol route, compensation and
`MILD_WEAKENING` is computed as before, and a refused finding now reaches
them. If it then reaches E1 in a diff with the flag, it prints
`OPAQUE_PROD_CHANGE_NOT_EVIDENCE`, after the unguarded-suite-control label
and before `NO_PROD_CHANGE_IN_DIFF`. `PACKAGE_REPAIR` and `DEPENDENCY_DRIFT`
never applied to these five rules. E2 is unchanged. The flag stays a
diff-level fact in the IR.

**Why the split falls there.** Python test code reaches its subject through
Python, and checkwash reads Python production changes as symbol evidence. An
opaque edit beside a weakened Python oracle explains it only when a called
Python symbol also changed, and clauses 1 and 2 already credit that case.
JS/TS production code is never parsed, so opaque evidence is the only
evidence a JS/TS test can earn; refusing it there would block every honest JS
assertion change beside a production edit, at a cost no corpus has priced
(#212). Removing a credit creates no bypass.

The gain is narrower than it looks, and the documents say so. An informed
agent reaches the same result at the same cost through a rule that keeps the
credit (row 130) or through Route A (row 93). What (b) reliably catches is an
agent that weakens a Python test beside a template, JS or native edit it was
making anyway, and a broad except added around an assertion, which has no
unit and could only take Route B.

**Refused: identity folds (Q3).** Folding `+ 0`, `* 1`, `- 0`, single-use
temporaries and constant-false branches in `_normalize_for_fingerprint` was
considered and refused. No fold list closes the class: `* 1.0`,
`x if x else x`, a no-op call or a rename buys the evidence again. Some folds
are wrong in Python: `True + 0` is `1` and `'a' + 0` raises, so folding `+ 0`
can deny evidence for a real change, and `if False: x = 1` makes `x` local to
the function. A published fold list is chosen by the attacker, as the decline
set D-029 threw away was. The residual is described instead (THREATMODEL 93).

**The E3 correction.** SPEC §5 listed E3 `HARDCODE_FINGERPRINT` as an
unconditional escalation for `EXPECTED_VALUE_HARDCODED`. No code implements
it: the rule is in `ORACLE_RULES` and goes through E1 and D1
(`gating.py:47-50`), and `expected_hardcoded_pos` pins it at warn with
`REPAIR_EVIDENCE`. The row is marked retired. Like D-047, the text follows
the code and the fixture, and no behaviour changes.

**Moves and renames (rule 2, as ruled).** Seven cases move from
`ASSERT_WEAKENED` warn to high with `OPAQUE_PROD_CHANGE_NOT_EVIDENCE`. Each
moves to a `_pos` successor with byte-identical inputs. The old `_neg` name
is reused by an expectation-family sibling, an `EXPECTED_VALUE_CHANGED`
beside the same opaque file at warn with `REPAIR_EVIDENCE`, which keeps
"opaque still counts" pinned and keeps references such as THREATMODEL row
68's true:
- `c_extension_still_opaque_neg` → `c_extension_still_opaque_pos` (`src/app/_speedups.c`);
- `build_makefile_stays_prod_neg` → `build_makefile_stays_prod_pos` (a `Makefile` that builds);
- `deploy_script_still_opaque_neg` → `deploy_script_still_opaque_pos` (`scripts/deploy.sh`);
- `unparseable_prod_still_opaque_neg` → `unparseable_prod_still_opaque_pos` (`src/app/native.py`, unparseable on both sides);
- `runner_opaque_native_neg` → `runner_opaque_native_pos` (`src/core.rs`);
- `runner_build_makefile_neg` → `runner_build_makefile_pos` (a `Makefile` that builds);
- `runner_one_hop_build_neg` → `runner_one_hop_build_pos` (`scripts/ci.sh` calling `scripts/compile.sh`).

The last two keep their "not ci" discrimination: the exact-count match still
forbids a `CI_WORKFLOW_TOUCHED` finding, in the successor and in the sibling.
Two cases stay at warn, and their de-escalator changes from `REPAIR_EVIDENCE`
to `COMPAT_GATE`: `conftest_hook_guard_opaque_prod_neg` and
`tests/test_issue208_209_suite_guards.py::test_a_guarded_control_takes_repair_evidence_beside_an_unguarded_one`
(name kept). The two #448 rows move as the second ruling says; the CLI test
checks the row's reason by membership, as main did, and the engine test
exactly, as main did. Eleven moves in all. In the previous-release verdict
gate a move toward block is listed and does not fail; only the maintainer
removes a stale acceptance entry.

**This amends the reading of 209.Q4 (D-088) for opaque evidence.** 209.Q4
holds as written: an unguarded suite control is never de-escalated by repair
evidence. The reading "only an unguarded control refuses repair evidence"
(conftest_hook_guard_opaque_prod_neg, THREATMODEL rows 72 and 116,
`test_issue208_209_suite_guards.py`) no longer covers opaque evidence. A
conftest `<suite>` unit calls nothing, so its only evidence was the opaque
blanket (D-066). Since this round every `TEST_DISABLED` in a Python conftest
refuses it, guarded or not, so a guarded control is held by its own D6
`COMPAT_GATE` or not at all:
- A guarded collection control earns `COMPAT_GATE` on its guard alone
  (D-028, 209.Q1): an `if` guard that can be false, or the import gate, a
  `try` body of plain imports (`import X` or `from X import ...`) under
  `except ImportError` or `except ModuleNotFoundError`, which the frontend
  records as `find_spec("X") is None` (`_handler_guard`, `_IMPORT_ERRORS`;
  THREATMODEL 83). Its verdict does not change.
- Any other `except` guard is recorded as the exception text, which is no
  condition D6 can read. `guard_can_be_false` still counts it, so the control
  is not a suite control, and `compat_gate_for` grants nothing. Beside an
  opaque edit it moves from warn (`REPAIR_EVIDENCE`) to high, labelled
  `OPAQUE_PROD_CHANGE_NOT_EVIDENCE`. This is the literal effect of Q1 (b)
  (second ruling), a newly blocking shape for the release notes, pinned by
  `opaque_refused_conftest_except_guard_pos`.
- A runtime control (`conftest.runtime.*`: #84's hooks, #422's exit status,
  #432's swaps, a fixture whose setup always skips) does not move. Its marker
  carries no guard: a hook's condition is hashed into its name (SPEC §2b;
  432.Q5). So it is unguarded, refused all repair evidence before this round,
  and still is. A fixture that skips only under a condition is no suite
  control: it is judged on the test units that request it (#351), as in the
  first bullet's general shape.

**D-028's caution.** D-028 re-swept 1,800 commits with the whole blanket
disabled: 35 blocks before, 35 after. It warned that these were six
pure-Python projects, and that "a repository with a C extension or a template
engine is exactly where it would start doing work". This round answers in
three parts. First, the refusal is narrower than D-028's experiment: five
rules, only in Python tests and conftests. A native or template change still
explains an expectation rewrite, a substituted assertion, a stand-in, and
anything in a JS/TS test. Second, for those five rules the work D-028
foresaw is exactly the case this round blocks: a Python assertion weakened,
removed, skipped or loosened, or a broad except added, beside a native or
template edit, with no called Python symbol changed. The likely honest blocks
are a tolerance loosened beside a native numeric change, a test deleted
together with a native feature (D8 reads only Python symbols), and an
assertion removed beside a template change. Third, the price is measured
where D-028 said it would be, before release: the pre-registered polyglot arm
holds C-extension, Cython, Rust and template-heavy repositories, under its
own line. Exceeding it stops the round and brings fallback (d) back for a
ruling. D-028's 35→35 is the prediction for the pure-Python arms, not
evidence for the polyglot one.

**Pre-registered line (419.Q6).** checkwash-lab commit
`8e291a4a90818d90b19017f27562ae1a5f3a9157`, branch
`prep/acceptance-sweep-419-20261016`, file
`workloads/acceptance_sweep/preregistration-419.md`, sha256
`70562cd7c7055ae738f2a3b39f29d71fc6d01df51f00390527ff5f86047263be`,
published before any engine run and still DRAFT for the owner's approval.
Correction C1 (owner, 2026-10-16; lab commit `1309456`, sha256
`f1b7ed40f7c765a1c9944462169c5050295d901ca6f0c80b72fbae42438221ae`): the PR
merges on green CI under the delegation, the sweep runs before the next
release, and a stop blocks that release; `main` is then the first parent of
the PR's merge commit.
Arms 1-5 compare the candidate with `main`, and arm 7 compares it with
report-only variants. They run on the EC pool, or on LAPTOP-01AGNPJU under EC
POLICY `checkwash-pju-sweep` (T-546), never on LAPTOP-16NUA5I8:
1. `standard` (1,800: attrs, click, flask, httpx, rich, starlette): any
   verdict move stops the round.
2. `d088` (1,263: D-088's 895 plus pytest's 368), unfiltered: any verdict
   move stops the round.
3. `opaque419` (the eleven `d088` histories through the shared filter, size
   N3 recorded at selection): predicted 0 as ruled; any verdict move stops
   the round.
4. `polyglot419` (pydantic, cryptography, markupsafe, msgpack-python, pyyaml,
   uvloop, pandas, django at recorded heads; K = 150 filtered commits within
   S = 3,000 per repository, both proposed and open to the owner before
   selection): more than 5 new blocks adjudicated false stops the round and
   brings (d) back; more than 5 false plus unclear stops it for the owner;
   two raters each; any other outcome move stops the round.
5. `javascript` (#212's 1,800): any verdict move stops the round.
6. Gates: the PR's CI, with only the eleven authorised moves; any red leg or
   natural-arm block stops the round.
7. Report-only: Q2 (b) and (c), Q8 for `ASSERT_SUBSTITUTED` and for
   `*_PATCHES_*`, and Q4's `fail_on = "warn"` and `oracle_freeze: true`.

**Residuals.** Row 93: Route A. Row 130: Route B for the expectation family,
`ASSERT_SUBSTITUTED` and `*_PATCHES_*`. Row 131: Route B for JS/TS tests,
pending #212. Row 132: snapshot suppression, including a new `.py` module
(#463). If fallback (d) is ever ruled, Route B through native files remains
in repositories that have them. The documents say plainly that (b) catches
incidental co-changes, not an agent that has read this rule.

**Contracts.** No fingerprint moves: severity and escalators are outside
`make_fingerprint` (`findings.py:127-131`). No `FINDINGS_VERSION` or
`IR_VERSION` bump: the label is a new value in the existing `escalators`
list, as `COLLECTION_CONTROL_UNEXPLAINED` was (D-066). It is a behaviour
change that newly blocks, so it ships in a minor release whose notes name the
newly blocking shapes: a weakening-class finding in a Python test or conftest
beside a modified production file checkwash cannot read, with no symbol
evidence, compensation or `MILD_WEAKENING`; and a conftest control guarded
only by an `except` clause D6 cannot read, beside such a file.

**Tests and fixtures.** Seventeen new `.gwcase` files: the seven successors,
five `opaque_refused_*` Route B cases, `opaque_refused_conftest_except_guard_pos`,
two residual pins (`opaque_residual_js_assert_weakened_template_neg`,
`opaque_residual_assert_substituted_template_neg`) and two Route A pins
(`route_a_assert_weakened_plus_zero_neg`, `route_a_skip_marker_plus_zero_neg`).
`tests/test_issue419_opaque_refusal.py` (6) and the two #415 siblings. None
carries a `bypass:` line. Documented count 18394 → 18419.

**Sweep.** NOT_RUN: work-machine rule (POLICY work-machine-local). No arm has
run, and no number in this entry was measured in this round. The results and
every new block's adjudication are recorded in this entry when the sweep has
run.

**Result** (2026-10-22). The stop fired in call 1 of the v0.9.0 combined
sweep: three pass → block moves in arms 2 and 3. The refusal is turned off
for v0.9.0; D-171 records the moves and the decision.

## D-142 (2026-10-16): the Claude Code Stop hook reads its window from the session's start (#418)

Ruling 418 (owner, 2026-10-14, 「P1 全部照建議」) answered its seven questions
as recommended. The number is D-142 because D-141 is drafted for #419 in
#464's description and is not on main yet; the release PR renumbers both if
needed.

#418 reports that the Stop hook ran `check --format hook-json` with no range,
so it diffed HEAD against the working tree. Work the agent committed during
the session was never analysed. A clean working tree printed `{}`, which is
what a real pass prints. And an exemption or config change the agent
committed governed its own next Stop check, because policy was read from
HEAD.

How each ruling answer is implemented:

- 1, the session base. `checkwash hook session-start`, the managed
  SessionStart handler, records HEAD once per session under
  `<git-dir>/checkwash/sessions/<sha256(session_id)>` (`session.py`).
  - It writes only when no record exists (`O_EXCL`). It never writes when
    `source` is `compact` or `resume`: a resumed session that has no record
    keeps none, so it is not given a base partway through.
  - After writing, it prunes other sessions' records by age (30 days) or a
    missing commit, never by count. It never prunes the starting session's
    own record, or a record that does not parse, which may be another
    session's record mid-write.
  - Records are read with `O_NOFOLLOW` and `O_NONBLOCK`, checked with
    `fstat` to be regular files, and capped at 4,096 bytes.
  - It prints nothing, because Claude Code adds a SessionStart hook's stdout
    to the model's context, and it exits 0 on every outcome.
- 2, no record. With hook input and no usable record, the Stop runs today's
  check, and a pass adds a `systemMessage` saying the session's commits were
  not analysed and why.
  - These count as hook input: input that does not parse, input with no
    `session_id`, and a record whose commit Git cannot compare with HEAD.
  - These count as no input, and the output is then the one without the
    flag: empty stdin, a TTY, or nothing within 10 seconds.
- 3, maintainer text. SPEC §1, §6 and §9, THREATMODEL item 2, the attacker
  model and row 133, and this entry, each in its own commit.
- 4, what the Stop judges. HEAD against the working tree decides the verdict,
  with policy read from the session base. On a pass, the session base
  against the working tree is analysed as well, and its findings at or above
  `fail_on` are named in a non-blocking `systemMessage` for the required
  check. Nothing is matched away: on a pass the first analysis has nothing at
  or above `fail_on`. A block skips the second analysis, so a block is never
  delayed, and the note comes at a later Stop.
- 5, HEAD not descending from the base. The session base is
  `merge-base(record, HEAD)`. With no merge base, the run is item 2's.
- 6, policy committed during a session. It applies from the next session. A
  block's reason says so and that `/clear` starts one, keeps the
  `checkwash allow` command, and does not suggest committing.
- 7, the entry point. `check --format hook-json --hook-input stdin` and
  `hook session-start`.
  - The flag with another format or with a range is a usage error, exit 2,
    checked before the root lookup. Without the flag the output is
    byte-identical.
  - stdin is read from its descriptor in a daemon thread, at most 1,000,000
    bytes.
  - The installer replaces the earlier managed Stop shapes and adds the
    SessionStart handler in a group of its own.
  - doctor notes, at info level, a Stop hook that has no SessionStart handler
    beside it, or that does not pass its hook input.

Effects beyond the ruling's text, accepted with this entry:

- `gitio.list_session_changes` diffs a commit against the working tree. It
  takes the paths of `git diff --name-only since HEAD --` plus `git status`,
  and sorts its changes by path; `list_worktree_changes` keeps status order.
- A pass with a session base other than HEAD runs the engine twice. The
  second analysis writes nothing to stderr or stdout.
- `hook install` prints one more line, about the SessionStart handler.
- Shared settings run the `checkwash` on each teammate's PATH. A checkwash
  older than #418 exits 2 on the unknown flag, which Claude Code reads as a
  blocked stop. `docs/remediation-upgrade.md` says to upgrade every CLI
  before committing the reinstalled settings.

Row 133 is Partly closed, and its residuals are listed there. Two read-only
reviews before merge, one for correctness and one for bypasses by the agent
in the session, shaped them:

- a record rewritten to name HEAD, or created by the agent running
  `hook session-start` itself, restores the old window with no note;
- moving HEAD moves the window;
- a committed exemption is warn, so the note does not name it.

The same reviews found that matching second-analysis findings against
first-analysis ones by rule, path and unit let one harmless uncommitted edit
hide a committed cheat. That matching is removed.

Evidence status: NOT RUN. The change was prepared on a work machine where no
pytest, checkwash or Python ran.

- Tests were only added, in `tests/test_issue418_session_base.py`: 25
  collected items, none under `tests/gates`.
- The two pre-approved lines of `tests/test_hook_runtime.py` changed (rule 2,
  in the ruling). `tests/test_threatmodel_pinned.py` gains the `E2E_PINNED`
  entry for row 133. No other existing expectation changed.
- The documented test count is 18459. The first CI run, at 7cff4c7, had
  18454 passed and 1 error, the oversized case's test id, which is now fixed.
- Whether `/clear`, `--resume` and compaction keep `session_id` is not in
  Claude Code's documentation. The design assumes `/clear` starts a new
  `session_id` and resume and compaction keep it. A lifecycle receipt from a
  real Claude Code run (2026-10-16, attempt 2, all eight checks pass;
  checkwash-lab `prep/lifecycle-receipt-418-20261017` at `7541c912`, #467
  comment 6223236053) confirms that `--resume` and compaction keep it. It
  did not exercise `/clear`, so whether `/clear` starts a new `session_id`
  must still be confirmed before the release.
- The sweep measures the change (ruling).

The agent wrote this entry in #418's fix PR #467. The maintainer approved it
on 2026-10-16: 「#467 的維護者文字照草稿核准（SPEC c014dfa、THREATMODEL
a4ee3a1、D-142 7cff4c7，含 fc4e41d 的更新）。CI 綠了就代合。」

The receipt bullet and the paragraph above were updated in PR #491. The
maintainer approved that text on 2026-10-18, choosing 「照草稿開 PR（推薦）」
in the agent's question (the option text is the agent's).

## D-143 (2026-10-17): unittest and approx operands are read by name as well as by position (#462)

Ruling 462 (owner, 2026-10-16, 「全部照建議」) answered its three questions
as recommended. D-141 and D-142 are on main, so this entry is D-143.

#462 reports that the unittest reader took an assertion's operands from the
call's positional arguments only. With its operands passed by name, the
record had no subject, no expected value and no operand-derived strength,
and it was trivial. A rewritten expectation passed with zero findings, and
a container literal respelled with keywords blocked as a weakening.
`pytest.approx(expected=)` had the same defect.

How each ruling answer is implemented:

- Q1 (b), scope. `_unittest_operands` binds each operand by position or,
  failing that, by its unittest parameter name. `_UNITTEST_OPERANDS`
  follows the `unittest.TestCase` signatures, and the raises family is not
  in it. A call that states every operand by position gives exactly its
  positional arguments, so those records are byte-identical. Every
  operand read in `_classify_unittest_call` and `_unittest_bound` uses the
  bound list. `_approx_expected` reads approx's first argument, or else
  `expected=`.
- Q2 (b), unbindable operands. No operand is read from a position at or
  after a starred argument; its keyword is read instead. Without a keyword
  in a call with `*` or `**`, the call is unbound. It records the method's
  form and strength, no subject, expected value or names, `trivial=False`,
  and the new optional IR field `unbound_operands`. That field is optional,
  so IR_VERSION stays 2 (docs/stability.md, D-067). ASSERT_WEAKENED
  reports "cannot verify" when a known oracle is replaced by an unbound
  call. A known oracle here has a strength above TAUTOLOGY, is not
  trivial, and is not itself unbound. The finding carries
  `strength_drop = 999`, as an unverifiable predicate or tolerance does,
  so MILD_WEAKENING never holds it. `gating.py` is unchanged. An unbound
  call replaced by another is not reported by this branch.
- Q3 (a), priority: P1, next after #419.

Effects beyond the ruling's text, accepted with this entry:

- An unbound `assertAlmostEqual` records a tolerance only when `places=`
  or `delta=` states one. It does not record the default `places=7`,
  since the spread may carry either.
- The new finding's `subject_changed` is null, not false: the new
  subject is unknown.
- `self.assertEqual(x, *rest)` and `self.assertEqual(x, **kw)` are
  unbound, although the first operand is known. Before the fix, the
  first recorded `x` as its subject and `*rest` as its expected node, and
  the second recorded `x` with no expected value.

Row 134 is Closed, with the residuals listed there: spreads on both sides,
aliases of `self.assertX`, the raises family, and the bounded unittest
projections.

Evidence status: the change was prepared on a work machine where no
pytest, checkwash or Python ran. CI ran the tests.

- Tests were only added: 17 `.gwcase` fixtures, and 90 collected items in
  `tests/test_issue462_keyword_operands.py`. None is under `tests/gates`.
  No existing fixture or test expectation changed. Two of the new
  fixtures carry `bypass: 134`, which the owner allowed.
- The documented test count is 18566 (18459 + 107). #472's CI on
  `80eb6ba` passed all nine test legs, `checkwash`, `dogfood` and the
  verdict gate.
- The sweep measures the new findings on keyword-form tests (ruling).

The agent wrote this entry in #462's fix PR #472. The maintainer approved it
on 2026-10-16: 「#472 的維護者文字照草稿核准（SPEC §3 note、THREATMODEL row
134、D-143），允許在 fixture 加 bypass: 134。」

## D-144 (2026-10-17): pytest collects the last binding of a test's name (#424)

Ruling 424 (owner, 2026-10-14, 「P1 全部照建議」) answered its nine
questions as recommended. D-141 to D-143 are on main, so this entry is
D-144.

#424 reports that pytest collects a module's or a class's tests from its
`__dict__`, so only the last binding of a name runs. The Python frontend
read every lexical `def test*` as a live unit and never read a later
statement that rebinds or deletes the name. One appended line took an
unchanged failing test out of the run, or swapped in a passing no-op, with
zero findings. A rebound copy still counted as live for the D2 move credit,
the D10 survivor credit and the restructure and split/rename budgets. In the
other direction, deleting one of two byte-identical copies reported
`test_x#2: test unit disappeared` at high.

How each ruling answer is implemented, in the new
`frontends/python/rebindings.py`, read once per test module (never for a
conftest) before units are collected:

- Q1 (b) with Q9 (a), the unit model. A def or class that a later binding
  certainly replaces is not a unit: a straight-line path, or branches whose
  conditions fold to true. A rebound class takes its units with it, and so
  do the units `inherited_test_methods` gives it. The remaining same-named
  units keep file-order `name#N`. R1, a no-op def appended under the
  test's name, is therefore an in-place rewrite of the test, and the
  issue's acceptance reads so.
- Q2 (a), severity. A conditional rebinding is a new marker,
  `collection.rebound` (kind `rebinding` in `conftest_controls`), on the
  unit it may replace. It is judged as a body skip is:
  `ir/markers.is_guarded_skip` and `skip_condition` read it, D6 reads its
  guard in `compat.py`, and TEST_DISABLED reports it added ("a later
  binding of this test's name may replace it") and its guard weakened or
  removed. A certain rebinding is a disappearance. The gating table is
  unchanged.
- Q3 (a). There was no interim row; row 135 closes with the fix.
- Q4 (b), the bindings. A def, a class, an import (not a star import), `=`
  (annotated, augmented, and each target of a tuple or list), `with ... as`,
  a walrus, a `match` capture, `del`, and, for a class's names, a
  module-level `Cls.name = ...` or `del Cls.name`, or a literal-name
  `setattr` / `delattr` on it. `globals()[...]` with a literal key counts
  in a module, as an assignment or `del` target or through `.pop`,
  `.update`, `__setitem__` or `__delitem__`. So do `vars()` and `locals()`,
  which in a class body are the class namespace. `except ... as` and a for
  target bind only when they run. A for over a constant-empty iterable and
  an annotation without a value bind nothing.
- Q5 (a). `X = f(X)` and nested one-argument chains (`f(g(X))`) are read
  as `@f @g` would be, for a def or a class, at module or class scope, and
  as `Cls.x = f(Cls.x)`. A skip or xfail applied this way is that mark,
  through `_decorator_markers`, with the binding's condition as its guard.
  An unknown wrapper keeps the test live, and `X = X` binds nothing.
- Q6 (a), paths. Each binding carries its path: the compound statement
  and arm of every level. Two bindings in different arms of one `if`,
  `match`, or two handlers, or a handler and the try `else`, are
  exclusive. A try-body binding and a handler binding are exclusive when
  the try-body one is a statement of the try body itself and nothing after
  it there can raise. A later binding on a non-exclusive path needs the
  conditions of the arms it enters beyond the shared ones. An `if` test,
  `not (...)` for an `else`, and an `except` block's condition
  (`_handler_guard`) are joined into its guard. Dead arms bind nothing.
  A loop body (shared or not), a conditional binder, a `match` case, a
  try `else` or a statement mid-way through a try body leave the guard
  empty, which D6 never holds. The marker's identity is its name alone:
  neither the guard nor the line.
- Q7 (a), rule 2. The two pins changed exactly as approved (below).
- Q8 (a). A function-level `test_x.__test__ = False` is not read here. A
  hosted CI run reproduced the gap for the module-function form on
  2026-10-19 (run 39215282880, draft PR #518, not merged); the
  class-method spellings were not run. Under ruling-list item R47
  (2026-10-19) no separate issue is filed until a fix is scheduled: the
  result is recorded on #424 and #280, and the limit is listed in
  `docs/KNOWN-ISSUES-next.md`. Row 135's residual (6) says the same.
- Q9 (a). A def or class that a collected name captured before the
  rebinding (`test_y = test_x`, `TestAlias = TestX`) stays as on main. So
  does a rebound class's method that a same-file subclass, defined while
  the class was bound, still runs. Only when C3 resolution proves that no
  collected subclass runs the method is it dropped or marked as above.

Effects beyond the ruling's text, accepted with this entry:

- "Nothing after the try-body binding can raise" is read strictly. Only
  these count: `pass`, a docstring, a constant assigned to plain names, an
  undecorated def whose defaults are constants and whose annotations are
  constants (or not evaluated, under `from __future__ import annotations`),
  and an undecorated class with no bases or keywords whose body is made of
  these. A def followed by anything else in the try body is rebound by the
  handler's def under the handler's condition.
- A binding mid-way through a try body is certain only when it is a
  statement of the try body itself, nothing before it there can raise, and
  it surely binds once it runs: `del` of names, an assignment of a
  constant, a name or a lambda, or a def or class that cannot raise.
  Otherwise it is "mid-try-body" and carries no guard.
- A capture counts when the capturing name is one pytest collects (`test*`
  for a function; `Test*`, or a same-file `*TestCase` subclass, for a
  class) and no later binding certainly replaces it. A capture under a
  condition counts too (row 135 residual 9).
- A subclass counts for Q9 when the frontend collects it (`_is_test_class`
  or `_transitive_test_classes`), it does not set `__test__ = False`, and
  its own later binding does not certainly replace it. Its method
  resolution order is read with same-scope bases resolved to the class
  statement current at the subclass, and other bases as opaque. A
  decorator, a keyword (a metaclass), or a body statement other than a
  def, a class, a plain assignment, `pass` or a docstring, on the subclass
  or on a same-scope class before the rebound one, leaves the order
  unread, and the method is kept. So does an opaque base before the
  rebound class in the order. A class that a `Cls.name = ...` reaches from
  outside its body is not read either.
- `Cls.name = ...`, `setattr`, `delattr` and `globals()[...]` are read in
  module-level statements, and `vars()` / `locals()` also in a class body.
  The same spellings inside a function or another class body are not
  (row 135 residual 11).
- The expression walk (walrus targets and literal-name calls) runs only in
  a module whose source spells `:=`, `setattr`, `delattr`, `globals`,
  `vars(` or `locals(`.
- TEST_DISABLED words a weakened rebinding guard as "skip guard of a later
  binding of this test's name now always fires" and a removed one as "skip
  guard removed of a later binding of this test's name", in the
  shape the setup and suite-control guards already use.

Rule 2. The ruling approved these expectation changes, made exactly as
described:

- `tests/test_frontend.py`: `test_x#2` is re-pinned on exclusive if/else
  defs, and a new pin says that an unconditionally rebound def is not a
  unit.
- `tests/test_frontend_iterative_visit.py`: the first `test_repeat` is
  dropped from the qualname and marks lists.

`tests/test_conftest_controls.py` lists the new minting site and family,
as that test requires of any new marker family. No existing entry,
`.gwcase` expectation or `tests/gates` expectation changed.

**Fingerprints.** For the X.release-and-fingerprints batch:

- In a file with same-named defs, a def that a later binding certainly
  replaces is no longer a unit. The units that remain are renumbered, and
  the last binding takes the bare name, so a finding keyed by such a
  unit's qualname changes its fingerprint. rich's `tests/test_console.py`
  is the known example (the triage case behind `name#N`). A recorded
  exemption on a `name#2` unit, or on the dead def's `name`, stops
  matching.
- `collection.rebound` adds TEST_DISABLED fingerprints of its own
  (`<path>`, `<unit>`, `collection.rebound`; `guard:collection.rebound` for
  a weakened guard). No existing fingerprint scheme changes.
- `docs/stability.md` lists fingerprints as frozen within a release line,
  so the release that carries this records the move in its D-063-style
  entry. Whether that release is a minor is the owner's call.

Row 135 is Closed, with eleven residuals listed there, including computed
names and `exec`, metaclasses and class decorators, wrappers that drop the
test, a function-level `__test__ = False` (Q8), an unresolvable subclass
(Q9), and a capture under a condition.

Evidence status: when the change was prepared, no pytest, checkwash
or Python ran on the work machine. CI ran the tests.

- Tests were added: 29 `.gwcase` fixtures, 79 collected items in
  `tests/test_issue424_rebinding.py` and one new test in
  `tests/test_frontend.py`. None is under `tests/gates`. Five of the new
  fixtures carry `bypass: 135`.
- The documented test count is 18675 (18566 + 109).
- The sweep the ruling asks for ran in part on 2026-10-17, on
  LAPTOP-01AGNPJU under POLICY `checkwash-pju-sweep` (T-546), as a
  checkwash-lab-declared run whose manifest (`54706f99…c88c`) and engine
  commits the owner approved first. It is labelled human-authorized
  local PJU, NOT EC pool. It compares main before this change
  (`2422b3ce`) with it (`f541f748`):
  - **Standard set** (1,800 commits): no change.
  - **D-088's sets** (1,263 commits: 1,218 ran in the sweep's d088
    batch, and the 45 that are also in the standard set ran in the
    standard batch, where none changes): 10 commits differ, all beyond
    fingerprints. One verdict goes from block to pass and one from pass
    to block. 19 of the 1,218 end in the same engine error on both
    engines and are not judged.
  - **Source review** (read-only, after the run; agents read the
    upstream commits, the engine source and the harness's result files,
    and a second agent tried to refute each verdict change and the
    survey of the other eight. Nothing was rerun, so the mechanisms
    below are read from source, not observed:
    `NOT_RUN：工作機規則（POLICY work-machine-local），no engine run or IR emission`):
    both verdict changes are right.
    pytest `242fb7852b` deletes the copy of a duplicated test that
    pytest collected; the copy that keeps the name has the same
    decorator and assertion, so the old TEST_DISABLED high was false.
    rich `a13b2a9d75` appends a Windows-only `test_render` that shadows
    the original, so the original expectation is checked nowhere. It
    blocks on EXPECTATION_DEFINITION_CHANGED high (the collected test
    compares against a different value), and the skip on Linux and
    macOS reports only at warn under D6. Five of the other eight only
    drop the finding on a copy pytest never collected, as Q1 (b)
    intends (the harness lists it under `name#2`, because the collected
    copy now takes the bare name). In the last three the pairing
    changes: rich `a2b4a959dc` now reports the real skips on Python 3.8
    and 3.9 (two warns, COMPAT_GATE) in place of a skip on a def pytest
    never collects; rich `8105943b89` still blocks, but on an
    expectation change between two defs that run on disjoint platforms,
    while the real loss, Windows' only `test_render`, reports at warn;
    and pytest `15ec5a898c` trades one false warn for another: the live
    def is renamed away and a dead def of the same name takes the name,
    so the old live body is compared with the revived dead one. This
    entry names R1 and the deletion of one of two identical copies, but
    not this case.
  - Not run: the target set of commits with duplicate names, rebinding,
    the Q9 shapes and try-wrapped defs, which has not been derived.
  - Not run by the sweep: the refactor gate (60, expected no change),
    tamper, decoy and recorded (no regression) and the perf gate. They
    are pytest suites, which T-546 does not cover:
    `NOT_RUN：工作機規則（POLICY work-machine-local），the gates are test suites`.
    CI runs them in every test leg (the perf gate's two budget checks
    skip on macOS). All nine legs passed on `2422b3ce` and on
    `f541f748`, and neither `tests/gates` nor the gates' `expected.json`
    tables changed between them.
  - The counts are read from the harness output. The summaries and the
    source review's records are in checkwash-lab
    `prep/acceptance-sweep-421-20261017` at `1a3d99a`, under
    `runs/acceptance-sweep-421/20261017-pju/`.

The agent wrote this entry in #424's fix PR #474. The maintainer approved it
on 2026-10-17: 「#474 的維護者文字照 commit 核准（SPEC 6b31f7a、THREATMODEL
row 135 與 bypass: 135 的 7b0c49a、D-144 be9a859）。CI 全綠就代合，然後接著做
#306。」

The sweep bullet under Evidence status and the Evidence status sentence
were rewritten from the 2026-10-17 sweep and its source review in PR #489.
The maintainer approved that text on 2026-10-18: 「照你建議」, in reply to
the agent's list asking for approval of the D-146 (977f8bd3), D-145
(a4fa4550) and D-144 (dfde00e1) drafts.

The Q8 bullet and this paragraph were written in PR #530, after #518's
hosted run reproduced Q8; the same PR rewrote row 135's residual (6)
(4b91d361, 3e4647b5). The maintainer approved that text on 2026-10-19:
「第二輪核可全部照建議」 ("the round-2 approval list, all as recommended"),
in reply to the agent's second list of approvals the open PRs needed. For
this PR: B20 approved residual (6) as written in 4b91d361, with "owner
ruling 2026-10-19, R47" changed to "ruling-list item R47", so that it is
not read as one of row 135's reproduction labels R1 and R5 (3e4647b5,
which keeps the date in parentheses); B21 put this record at the end of
D-144 and had the Q8 bullet say that Q8 was reproduced and, under R47, is
recorded on #424, #280 and in KNOWN-ISSUES-next, with no separate issue.
The Q8 bullet's wording and this paragraph were written after the reply,
so their wording is the agent's. Earlier that day, 「PR 核可清單全部照建議」
had placed the rewording of residual (6) in this PR with its wording left
for approval (A20), and recorded the class-method spellings as not run
(A90). Each reply is the text of an answer the agent wrote, which the
owner chose.

## D-145 (2026-10-17): a helper method a test reaches through `self` is the test's (#306)

Rulings 306 (owner, 2026-10-08, "裁決依照你建議": Q1 (a), Q2 (a); and
2026-10-14, 「P1 全部照建議」: Sub-Q1 to Sub-Q11, each as recommended).
D-144 is #424's, so this entry is D-145.

#306 reports that in a `unittest.TestCase` (or a pytest class) whose test
calls a helper method, `self._check(total(...))`, the frontend named the
call by its root, `self`, and never walked the method. A helper method's
assertion weakened (A1) or deleted (A2), and a skip in a helper method the
test calls (H2) or its `setUp` calls (S1), passed with zero findings. The
same helper as a module function blocked (THREATMODEL row 91).

How each ruling answer is implemented:

- Q1 (a), assertions and skips. In a method unit, a call
  `<receiver>.<name>(...)` whose receiver is the method's first positional
  parameter (and is never rebound) runs the helper method resolved below.
  That method is followed as a module helper is, once per entry site with
  that site's reaching keys (#55), at most four calls deep. The walk goes
  through further calls on the method's own instance and through the
  module helpers it calls. Its assertions are the unit's, with
  `inherited: true` and the new optional IR field `via`, the method's
  class-qualified name (`TotalTest._check`). Its skips are read as #272
  reads a helper's (`HelperOutcomes.of_method`): as a setup callback, with
  its receiver, so `self.skipTest` is an outcome. The marker is
  `helper.<method>.<effect>`. A class's setup callbacks and fixtures read
  the methods they call the same way (`SetupScope(methods=)`), which gives
  S1.
- Q2 (a). The method is the one the class running the test resolves: the
  method's own class, or for an inherited test the collecting subclass.
- Sub-Q1 (a), rule 2. The H2 and S1 pins flip and are renamed (below).
- Sub-Q2 (a), the order. A local C3 over the module's top-level classes,
  each base the file does not define kept as an opaque entry. The name
  resolves only in a same-file class reached before the first opaque
  entry. It stays unresolved on a C3 failure, a class name the module binds
  more than once, a decorator on the running class or on any class up to
  the one that binds the name, or a class keyword (a metaclass),
  `__init_subclass__` or `__getattribute__` on any same-file class in the
  order.
- Sub-Q3 (a), name-specific. In the first class of the order that binds
  the name, its one binding is a plain def in the class body, not under
  `if` or `try`. The call stays unresolved on any of these anywhere in the
  module: a store or del of `.<name>`, a `.__dict__[...]` store or del,
  `setattr`/`delattr`/`object.__setattr__` with the literal name (or a
  computed name on the receiver or on a class of the order),
  `patch.object` or `monkeypatch.setattr` naming it, or `__setattr__` on a
  class of the order.
- Sub-Q4 (a). Only an undecorated `def` or `async def` resolves.
- Sub-Q5 (a). A helper method's guard is read under the running class's
  attributes, through `setup_outcome(..., receiver=True, attrs=env(...))`,
  as `setUp`'s is. `credit_base` admits `helper.` markers and reads them
  again under each crediting subclass.
- Sub-Q6 (a). A name `unittest.TestCase` defines is never followed, in any
  class. `self_methods.TESTCASE_NAMES` is a fixed literal list: the union
  over Python 3.11-3.14 (3.11's `Lib/unittest/case.py`, the aliases 3.12
  removed, the assertions 3.14 added), never read from the running
  interpreter. Shadowing stays row 91a.
- Sub-Q7 (a). A helper method moved to a base in another module is behind
  an opaque entry, so the move reads as ASSERT_REMOVED. It is pinned as a
  stated cost (`self_method_moved_to_imported_base_pos`) and counted by the
  sweep. A follow-up for a one-hop read of a `from M import Base` base is
  filed only if the cost proves real.
- Sub-Q8 (c), evidence per finding. Each followed method's callees go into
  `helper_calls` under its class-qualified name. They count as repair
  evidence only for a finding about an assertion reached through that
  method, identified by its `via` (`gating._finding_via`, by the cited
  span). `invoked` does not change.
- Sub-Q9 (a). The maintainer text covers THREATMODEL rows 91, 92, 104, 118
  and 125, SPEC §3 "What counts as a unit's assertions", the SPEC §4
  TEST_DISABLED helper-skip clause, and SPEC §5's compensation text and
  repair-evidence item 2.
- Sub-Q10 (b). A disappeared unit keeps today's identity: its `via`
  assertions stay out of the finding's text and fingerprint.
- Sub-Q11 (b), a detection-only overlay. Own assertions are paired, judged
  and credited exactly as on main (`diffalign._match_assertions`). `via`
  assertions then pair among themselves and with the after side's own
  assertions left unpaired, by the same stages. A `via` assertion earns no
  credit and adds no requirement: it counts in no D2 move credit, no D5
  oracle mass, no D4 newly written assertion and no split/rename budget,
  and a disappeared unit needs none of its `via` assertions moved. A finding
  about a `via` assertion takes the credits a module helper's inherited
  assertion takes. #272 reading 7's moved-skip pairing reads `helper.`
  markers in both directions, so it covers helper methods unchanged.

This entry supersedes D-111 reading 2's sentence "A method reached through
`self` is no scope `_executed_scopes` resolves, for assertions either": since
#306, such a method is followed by this entry's resolution, for assertions
and skips.

Why Sub-Q3 departs from D-095 reading 2. D-095 reads a class *value* for a
guard, and makes it unknown on any reflective call in the module and for
any private name, because unittest sets private attributes on the
instance. A helper method is a *def* that a call names, and the ruling made
its rebinding test name-specific. A `setattr` on an unrelated object
elsewhere in the module therefore leaves the helper resolved. A private
name (`_check`, the usual spelling of a helper method) resolves unless it
is one `unittest.TestCase` defines (Sub-Q6). A computed-name `setattr` on
the receiver or on a class of the order still leaves every name of that
class unresolved.

Effects beyond the ruling's text, accepted with this entry:

- The running class must be a top-level class of the module. A method of a
  nested class, or of a class defined under `if`, keeps today's reading.
- A call through another name for the instance (`other = self;
  other._check()`) is not followed.
- `cls.<name>()` in a classmethod unit is read as `self.<name>()` is, its
  receiver being its first parameter.

Rule 2. Sub-Q1 approved these expectation changes, made exactly as
described: in `tests/test_issue272_helper_skips.py`, H2
`test_a_method_reached_through_self_is_not_followed` flips from `[]` to
`helper._later.skip`, and S1
`test_a_method_the_setup_reaches_through_self_is_not_followed` to
`helper._offline.skip`. Both are renamed `..._is_followed`, to pin the
closure, as D-088 did for #208's pins. No other existing fixture or test
expectation changed, and none under `tests/gates`.

**Fingerprints and IR.** No fingerprint moves (Sub-Q10): the `via`
assertions are new records, and a finding on one is a new finding. In
`--emit-ir`, every assertion gains `"via": null`, which is an optional field
(docs/stability.md: IR_VERSION stays 2, as for D-067's keys and D-111's
`markers_moved`). A file whose test follows a helper method also gains its
`via` assertions and a class-qualified `helper_calls` key. The count of
records this changes in `tools/emit_corpus.py`'s output comes from CI's
artifacts (NOT_RUN on the work machine), and the next release guide names
the field.

**Cost.** The sweep the ruling asks for ran in part on 2026-10-17, on
LAPTOP-01AGNPJU under POLICY `checkwash-pju-sweep` (T-546), as a
checkwash-lab-declared run whose manifest (`54706f99…c88c`) and engine
commits the owner approved first. It is labelled human-authorized local
PJU, NOT EC pool. Its plain before/after compares #424's engine
(`f541f748`) with this entry's (`81c69d28`):
- **Standard set** (1,800 commits): no change.
- **D-088's sets** (1,263 commits: 1,218 ran in the sweep's d088 batch,
  and the 45 that are also in the standard set ran in the standard
  batch, where none changes): 15 commits differ, all scrapy and all
  beyond fingerprints. In 14 of them findings are only added:
  ASSERT_REMOVED (high 286, warn 1), EXPECTED_VALUE_CHANGED (warn 28),
  ASSERT_SUBSTITUTED (high 6), ASSERT_WEAKENED (high 2) and
  EXPECTATION_DEFINITION_CHANGED (high 2, warn 1). In the fifteenth,
  scrapy `fada8be1db`, no finding is added or removed: six TEST_DISABLED
  findings keep their fingerprints and go from info (4) or warn (2) to
  high. No finding is removed or lowered. Three verdicts go from pass to
  block, and none from block to pass. 19 of the 1,218 end in the same
  engine error on both engines and are not judged.
- **Stated costs:** Sub-Q4's conversion to `staticmethod` shows in 3
  commits (68 findings, all high; see below). In the standard set and
  D-088's sets, no commit shows Sub-Q7's, a helper method moved to a base
  in another module. Sub-Q4's other cost, a skip added in a helper method
  together with a decorator on that method, leaves the skip unread on
  both engines, so a before/after comparison cannot count it; any of the
  method's assertions that were reached at the parent read as removed,
  as for `staticmethod`.
- **Source review** (read-only, after the run). Agents read the upstream
  commits, the engine source and the harness's result files, and a
  second agent tried to refute each verdict change and each survey of
  the other commits. Nothing was rerun, so the mechanisms below are read
  from source, not observed:
  `NOT_RUN：工作機規則（POLICY work-machine-local），no engine run or IR emission`.
  None of the added findings is a weakening, and the three blocks are
  false:
  - scrapy `c8aa429c9b` (168 ASSERT_REMOVED high) adds class-level
    pytest marks (`requires_reactor`, `requires_http_handler`) to 23
    test classes, and all 168 findings fall in six of them, whose tests
    reach assertion-holding helper methods through `self`. `e058a05763`
    (8) adds `pytest.mark.skipif(sys.version_info >= (3, 12), ...)` to
    two TestCase classes, with all 8 findings in one of them; both
    engines already report that version skip as TEST_DISABLED warn
    (COMPAT_GATE), so the block comes from the 8 findings alone. Sub-Q2
    leaves a call unresolved under a decorator on the running class, so
    each helper method resolves on the parent side only, and its
    assertions read as removed. A pytest mark returns the class it
    marks.
  - scrapy `fada8be1db` merges six proxy tests into parametrized ones
    that each call `self._maybe_skip(...)`. That helper's skip is now
    followed (Q1 (a)). Its guard is no D6 compat gate, so each new unit
    is not live (SPEC §5 D2), and the six disappeared units lose the
    credit they had under #424's engine, move credit (D2) for four of
    them and restructure credit (D5) for the other two, and go to high.
    D-087 and D-111 read setup skips and same-file helper skips the same
    way.
  - The other 12 commits add 150 findings and change no verdict:
    Sub-Q4's staticmethod cost in 3 (68, all high); a decorator added to
    the running class in 4 (37), where the class does run in fewer
    places (in `14737e91ed` because its tox.ini moves mitmproxy out of
    the default environments, not because of the mark) and #424's engine
    already reports TEST_DISABLED, so the ASSERT_REMOVED findings repeat
    it under a false reason; detector readings that already applied to
    own assertions, now applied to each helper-method copy, in 4 (37); a
    class local to a test method, named like the test class, read as
    rebinding it, in 1 (1), which goes beyond Sub-Q2's "a class name the
    module binds more than once"; and a removed helper call site in 2
    (7): in `e853d9e910` the call moves to a new test and its helper
    assertions earn no move credit there (Sub-Q11), and in `3a36955261`
    a repeated check is dropped while a later call of the same helper
    still covers it, which checkwash does not model. Two commits fall
    under two of these.
  - The decorator reading and the local-class reading are filed as
    #487. The helper-skip liveness is filed as #488, whose ruling
    (2026-10-18, option (a)) records the block on `fada8be1db` as a
    known false block, not correct behaviour: by reading the scrapy
    source, the commit only adds coverage on the test side. D-087's
    maintainer decision kept this liveness cost for guarded setup skips,
    but in D-087's and D-111's sweeps it never turned a pass into a block
    by itself; here it does. It is not the first liveness-only block in
    DECISIONS: D-116's sweep blocked pytest `4f5d7948`, where a test
    moves into a file in which it carries a guarded `py.test.skip`, and
    D-116 does not call that block false. The block stays until a later
    change removes it, such as #488's per-row liveness (option (b)),
    which needs its own ruling. Meanwhile an author can exempt the six
    findings by fingerprint only through an `allow.toml` entry already
    on the base side (SPEC §5 D3, §6); one added in the blocked change
    itself shows as `EXEMPTION_ADDED` and does not lift the block. How
    often this happens is not known. So far it is the only verdict this
    reading moves in the standard set and D-088's sets, but 19 commits
    of the d088 batch are not judged (above), and most of the targeted
    phase did not run (below). Further cases are recorded on #488.
- **Not measured:** resolution toggled in both directions, and what
  Sub-Q8 (a) and Sub-Q11 (a) would have changed; each needs an engine
  variant that is not a commit on main. Sub-Q7 asks for its cost to be
  counted in the targeted sweep: of the 1,372 commits in the sweep's
  `targeted` phase, only the 119 that are also in D-088's sets ran.

The counts are read from the harness output. The summaries and the
source review's records are in checkwash-lab
`prep/acceptance-sweep-421-20261017` at `1a3d99a`, under
`runs/acceptance-sweep-421/20261017-pju/`. Two of the ruling's three
stated costs are pinned: a helper method moved to a base in another
module (Sub-Q7, `self_method_moved_to_imported_base_pos`), and a
conversion to `staticmethod` (Sub-Q4,
`self_method_staticmethod_conversion_pos`). Sub-Q4's other stated cost
is not pinned: a skip added in a helper method together with a decorator
on that method is not read, so it passes with zero findings, as before
this entry, unless the method's assertions were reached at the parent;
those then read as removed, as for `staticmethod`. A decorator on the
running class falls under Sub-Q2 instead (`c8aa429c9b` and `e058a05763`
above).

Evidence status: when the change was prepared, no pytest, checkwash
or Python ran on the work machine. CI ran the tests.

- Tests were added: 10 `.gwcase` fixtures and 51 collected items in
  `tests/test_issue306_self_methods.py`. The two pins above changed.
- The diffalign and `gating.py` changes for Sub-Q8 and Sub-Q11 are in their
  own commit, for the owner's approval as the ruling asks.

The agent wrote this entry in #306's fix PR #476. The maintainer approved it
on 2026-10-17: 「核准 這次sweep用本機跑」, in reply to the agent's list asking
for approval of this PR's SPEC (6dba5aa), THREATMODEL (e3e4b79) and D-145
(93c25a6) text and of the diffalign and gating commit ea98b62.

The Cost paragraph and the Evidence status sentence were rewritten from
the 2026-10-17 sweep and its source review in PR #489. The maintainer
approved that text on 2026-10-18: 「照你建議」, in reply to the agent's list
asking for approval of the D-146 (977f8bd3), D-145 (a4fa4550) and D-144
(dfde00e1) drafts. The follow-up issue numbers (#487, #488) were filled in
once the issues were filed, as that list said.

The follow-up bullet that ends Cost's source review was rewritten from
#488's ruling (issuecomment-6248630774, item 1) in PR #510. The
maintainer approved it on 2026-10-19: 「PR 核可清單全部照建議」, which
takes every item of the agent's approval list as the agent recommended.
For #510 that list asked for approval of the bullet's wording (6aaa93ac,
8ae71cf5; item A13), whether to add a `docs/KNOWN-ISSUES-next.md` row for
#488 (added in 6abaf2a9; A14), and whether to keep the `fada8be1db`
sub-bullet's last sentence and add the ruling's D-116 contrast (the
sentence kept, the contrast added in 570a81fd; A15). The reply is the
text of an answer button the agent wrote, which the owner chose.

A14 decided that the row is added; the row's text (6abaf2a9, ee4facf4)
and the paragraph above were written after that approval. The maintainer
approved them on 2026-10-19: 「第二輪核可全部照建議」, which takes every
item of the agent's round-2 approval list as the agent recommended. For
#510 that list asked whether to approve together the text written to
apply options already approved, the paragraph above and the #488 row
among it (item B3), and whether the page's first header sentence, which
said every residual below was found by reading, should also yield to a
row, with #510 and #521 using one wording (B4). Under B4, 7dc0cd20 ends
that sentence with "unless a row names another source", the wording
#521 (775aa3dd, accepted under A22) uses. A read-only claims review of
#510 found that the row said lost credit always sends the findings to
high; 8678ed8b says they go to high unless repair evidence or another
de-escalator holds them at warn (SPEC §5 E1, D1). That correction was
written after the approval. The reply is the text of an answer button
the agent wrote, which the owner chose.

## D-146 (2026-10-17): assertion-level exemptions are content-bound (#421)

Ruling 421 (owner, 2026-10-14, 「P1 全部照建議」) answered its six questions
as recommended, and the order decision puts round 1 before #429 and #428.
D-145 is #306's entry in PR #476, so this entry is D-146.

#421 reports that an assertion-level exemption was keyed on rule, path, unit
and the normalized before text. While the base still held the original line,
one `checkwash allow` for a reviewed rewrite also passed any other rewrite of
that line the same rule reported, until the entry expired. The key was broader
in four more ways. The event kind was not in it, so an approved strength drop
also covered an inversion. A Jest or Vitest assertion was keyed by its text
through the matcher's `(`, so `toBe(1)` and `toBe(2)` on one subject shared a
key. TOLERANCE_LOOSENED was keyed by `kind:old value`, so one approval covered
any widening of a tolerance with that kind and old value in the unit. And
identical before lines collided.

How each answer is implemented:

- Q1 (b) and Q2 (b), the scope. ASSERT_WEAKENED (its five branches),
  ASSERT_SUBSTITUTED, ASSERT_REMOVED, TOLERANCE_LOOSENED,
  EXPECTED_VALUE_CHANGED at assertion level, EXPECTED_VALUE_DERIVED,
  EXPECTATION_DEFINITION_CHANGED (the aligned emitter and the helper/loop
  provenance channel), SUBJECT_NORMALIZED and SUBJECT_INPUT_CHANGED (both
  forms of each) now emit `make_assertion_fingerprint`. TEST_DISABLED waits
  for round 2 under its own issue and ruling. EXPECTED_VALUE_HARDCODED,
  CONFTEST_PATCHES_PROD, TEST_PATCHES_SUBJECT and the rules that are not
  oracle rules keep `make_fingerprint`.
- Q3 (b), the identity. `assertion_identity` builds it and `assertion_key`
  hashes it: `rule/path/unit/v2:<64hex>`, the full SHA256 of ASCII canonical
  JSON under the scheme name `checkwash/assertion-fingerprint/v2`. It holds
  the legacy pre-image exactly as `make_fingerprint` builds it, the complete
  before and after texts, the event kind, the before side's ordinal and
  count of the text (`assertion_position`), and the rule's context. The
  texts are in `identity_text`'s form, a v2-only scanner: `normalize_text`'s
  form, except that a JS template literal is kept as written and the code
  of each `${...}` in it is normalized as code. `normalize_text` is
  unchanged, so pairing, move detection and the legacy keys are as they
  were. A span
  only finds the assertion among its copies. Spans, line numbers, messages,
  strengths, severities, file digests and revision labels stay out. Nothing
  raises: an unreadable text is null, and a context JSON cannot encode is
  recorded as null.
- Q4 (a), legacy keys. `fingerprint_state` retires a legacy key of these
  nine rules. It is still parsed and counted, never eligible, and `allow`
  refuses it (exit 2) with a message that names #421. `doctor` and `check`
  report it as they report the five D-055 namespaces. Nothing is migrated.
  The legacy entries in checkwash's own ledger cover merged PRs, so no
  current verdict changes; they stay as ignored records until they expire
  or are removed through the GUARDRAIL_TOUCHED route.
- Q5 (a), versioning. The next minor (or 1.0), never a patch.
  FINDINGS_VERSION and IR_VERSION stay at 2: no IR field is added. The
  release needs the one-time authorization in AGENTS.md rule 5.
- Q6 (b), the report listing, is filed separately at P3.

Readings the ruling leaves to the implementation:

1. **The context per rule.** TOLERANCE_LOOSENED: the tolerance kind and both
   recorded values. EXPECTATION_DEFINITION_CHANGED (aligned): for each name
   whose definition moved, its reaching definition, local binding,
   parametrize column, parametrize rows, module constant and same-file
   fixture, before and after. EXPECTED_VALUE_DERIVED: the names the new
   expectation shares with the subject. SUBJECT_INPUT_CHANGED: the changed
   inputs. SUBJECT_NORMALIZED (aligned): both resolved subjects.
   ASSERT_WEAKENED: whether the subject changed in the polarity branch, and
   the tolerance an unreadable one lost; its other branches need nothing
   beyond the kind and the texts. The provenance channel and both table
   forms already put their whole event in the legacy text.
2. **Which assertion a tolerance change came from.** `tolerance_changes`
   records values only. The detector takes, in alignment order, the next
   pair whose tolerances are those values; when there is none, the texts
   and the position are null and the key still differs by its context.
3. **Literal-table SUBJECT_NORMALIZED events carry no position.** The record
   alone is the identity, so it survives the JSON round trip of the events
   without the units. Duplicate suppression, between the two forms and
   between equal records, stays on the legacy keys, so no finding count
   changes.
4. **The stored expectation.** `EXPECTED_VALUE_CHANGED/path/-/v2:<64hex>`
   stays the D-055 file form. The same rule with a unit is now an
   assertion-level v2 key, so the key that was `invalid` at
   `test_snapshot_expectations.py:125` is `supported`.
5. **Sets.** `ast.literal_eval` makes sets of literal arguments and table
   cells, and a set's iteration order, so its `str()`, follows the hash seed.
   `canonical` encodes a set as a list sorted by its members' encodings, and
   another value JSON has no form for as its `repr`, so a key is the same in
   every process. SUBJECT_INPUT_CHANGED's table-row legacy text goes through
   it too. A row without a set encodes as it always has, and so does a dict
   with int, float or None keys; a tuple key, on which json.dumps raised,
   is now written as its JSON encoding. Raised by a GLM review of #477 and
   verified by the agent.
6. **Which copy.** The ordinal counts in the side's own order, not by span:
   spans of assertions from other files share no coordinates with the
   unit's, and the copies of one helper line share a span. Own and
   same-file assertions come in source order, a helper line's copies by
   call site, then those from other files; an assertion is found by itself,
   never by its span.
7. **A unit named with `/`.** A JS unit is the raw test title, so
   `fingerprint_state` reads only the last segment as the digest, after a
   non-empty path and unit: `it("GET /")` keeps an exemptible key.
8. **TOLERANCE_LOOSENED's pair.** Alignment and the detector share
   `tolerance_change`, so each recorded change is matched to the pair that
   records exactly it, not to another pair whose values merely fit.
9. **SUBJECT_NORMALIZED's subjects** are in the texts' normal form, so
   reformatting outside string literals keeps the key.

Readings 6 to 9 were raised by a read-only Claude review workflow of #477 and
verified against the source by the agent.

This supersedes, for these nine namespaces, D-055's "Keep unaffected
identities ... unchanged" and D-077's list of the keys that stay (six rules
keying a JS assertion by its legacy matcher identity; TOLERANCE_LOOSENED,
EXPECTED_VALUE_CHANGED and EXPECTED_VALUE_DERIVED keeping every other key).
The D-084 practice, a changed assertion riding on an existing exemption whose
key binds only the before text, ends.

**Fingerprints.** Every finding of the nine rules has a new key, so every
recorded exemption for them stops matching and the reviewed change must be
re-run and approved again. Other rules keep their keys. Findings of one rule
in one unit sort by key, so their order in a report can change.

**Pinned tests (rule 2).** Changed as approved:
`test_js_assertion_identity.py`'s four named tests, which now pin the
legacy pre-image inside the v2 identity (`_refines`);
`test_tolerance_absolute_bound.py`'s
`test_a_finding_reported_before_keeps_its_fingerprint`, likewise;
`test_snapshot_expectations.py:125,127` (its name, which says assertion
keys are not retired, is left as approved);
`test_doctor.py:537-546`, whose over-cap entry becomes a v2 key;
`test_human_encoding.py:120-121`; and `test_fingerprint_scope.py:189-233`,
moved to BROAD_EXCEPT_ADDED. Beyond that list, two, for the owner's approval:
`test_issue416_subdirectory_root.py`'s `FINGERPRINT`, a legacy ASSERT_WEAKENED
key its three tests pass to `checkwash allow`, becomes a v2 key (an input; no
expectation changes); and `tests/e2e/test_cli.py::test_sarif_format_is_github_code_scanning_subset`
reads the ASSERT_WEAKENED result's `partialFingerprints` under `checkwash/v2`,
as SPEC §6 says. No `.gwcase` expectation changes.
`allowlist_future_created_pos` is unaffected: the golden runner passes it no
ledger either, so its `bypass: 39` claim holds no exemption, a gap that
predates #421. `test_a_future_created_content_bound_key_is_still_capped` pins
the cap on a v2 key with a real entry.

**Cost.**
- **New blocks:** a rewrite of an assertion under an exemption recorded for
  another rewrite of the same line, for another identical copy, or for
  another context.
- **Re-review:** every recorded exemption for the nine rules.
- **Measured:** the sweep (ruling: the standard set and D-088's sets)
  ran on 2026-10-17, 14:37Z to 16:22Z, on LAPTOP-01AGNPJU, under POLICY
  `checkwash-pju-sweep` (T-546), as a checkwash-lab-declared run whose
  manifest (`54706f99…c88c`) and engine commits the owner approved
  first. It is labelled human-authorized local PJU, NOT EC pool. It
  compares #306's engine (`81c69d28`) with this entry's (`a6426671`):
  - **Standard set** (1,800 commits): 96 commits differ, and none still
    differs once fingerprints are left out.
  - **D-088's sets** (1,263 commits: 1,218 ran in the sweep's d088
    batch, and the 45 that are also in the standard set ran in the
    standard batch and are counted above): 194 of the 1,218 differ, and
    none differs beyond fingerprints. 19 of the 1,218 end in the same
    engine error (exit 2) on both engines, so neither judges them: 12 at
    an engine limit, 4 at a nonregular source and 3 at flask's
    `docs/_themes` submodule.
  - No outcome or verdict changes, and every commit keeps its findings'
    rules, severities, paths and units. Besides the outcome, the verdict
    and any error, the harness compares only those four fields and each
    finding's key, as a sorted list; it reads no message or assertion
    text. In the 106 shard results the harness wrote, which are kept on
    the host and not archived, every other field of every finding is
    unchanged as well. Only keys move, and with them, as **Fingerprints**
    above says, the order of findings of one rule in one unit.
  - No finding in the sweep is exempted on either engine: the replayed
    repositories hold no checkwash ledger. So the sweep does not measure
    the new blocks or the re-review above.
  - The counts are read from the harness output. The summaries and a
    record of the owner's approval of the manifest and engine commits
    (「核可」, 2026-10-17 14:36Z) are in checkwash-lab
    `prep/acceptance-sweep-421-20261017` at `1a3d99a`, under
    `runs/acceptance-sweep-421/20261017-pju/`.

Row 136 is Closed. Its residuals: TEST_DISABLED (its own round),
EXPECTED_VALUE_HARDCODED, CONFTEST_PATCHES_PROD and TEST_PATCHES_SUBJECT keep
before-only keys; an approval still covers the identical reviewed rewrite on a
later diff, as D-055 intends; and the identity holds what the frontends
record. Rows 100 and 101 now point to it.

Evidence status: when the change was prepared, no pytest, checkwash
or Python ran on the work machine. CI ran the tests.

- Tests were added: 38 collected items in
  `tests/test_issue421_assertion_keys.py`. None is under `tests/gates`.
  Row 136 is pinned through `E2E_PINNED` by
  `test_the_reviewed_rewrite_is_exempt_and_another_still_blocks`: the
  golden runner passes no ledger, so the `.gwcase` first written for it held
  no exemption at all (raised by a GLM review of #477 and verified by the
  agent), and it was removed.
- The documented test count is 18774 (18736 after #306, + 38).

The agent wrote this entry in #421's fix PR #477. The maintainer approved it
on 2026-10-17: 「核准 這次sweep用本機跑」, in reply to the agent's list asking
for approval of this PR's SPEC (a332ad42), THREATMODEL (87e932ca), D-146
(285f5d4f) and user-doc (f6f9c3db) text and of the two pinned tests outside
the ruled list. The second half of that reply chose this host for the
ruling's sweep, under POLICY `checkwash-pju-sweep` (T-546).

Cost's "Measured" bullet and the Evidence status sentence were rewritten
from the 2026-10-17 sweep in PR #489. The maintainer approved that text on
2026-10-18: 「照你建議」, in reply to the agent's list asking for approval
of the D-146 (977f8bd3), D-145 (a4fa4550) and D-144 (dfde00e1) drafts.

## D-147 (2026-10-17): a JS/TS assertion that can never fail reads as TAUTOLOGY (#429, first change)

Ruling 429 (owner, 2026-10-14, 「P1 全部照建議」) answered its ten
questions as recommended. Q8 (b) splits the round into two changes, each
with its own qualification and sweep; this entry is the first (Q2, Q6,
Q7). D-145 (#306) and D-146 (#421) are on main, so this entry is D-147.

#429 reports three one-line JS/TS edits that the Python frontend blocks and
the JS/TS frontend passed with zero findings. This change closes the first:
`expect(total).toBe(total)`. The frontend rated every equality EXACT_VALUE
without comparing its operands, so nothing under
`frontends/javascript/` produced TAUTOLOGY, and `toBe`, `strictEqual`,
chai `equal` and `t.is` state `eq_strict` on both sides of such a pair,
which the predicate relation read as the same predicate. An assertion on
literals alone (`expect(3).toBe(3)` in place of `expect(total()).toBe(3)`)
passed the same way.

How each ruling answer is implemented:

- Q2 (a), literal assertions. `literal_operand` in
  `frontends/javascript/literals.py` reads an exact literal from the tokens
  of `operand_tokens`, a lexer that reads strings, templates (substitutions
  nested) and regular expressions whole and leaves comments out: a number,
  BigInt, string, template without a substitution, regular expression,
  `true`, `false` or `null`, or an array or plain object of them, through
  parentheses, `x!` and a cast to one named type (`as number`, `as const`;
  `x as any || y` is more than a cast). A name
  never is one, `undefined`, `NaN` and `Infinity` included. `_rate_tautology`
  in `frontend.py` rates TAUTOLOGY an assertion whose subject as written and
  every operand its predicate reads are literals, in each scan: the Jest
  matchers, chai `expect` and `should` chains, the chai and node:assert
  calls, and AVA and tap. A message argument is no operand.
- Q7 (b), self-comparison. `same_operand` compares the token sequences of
  two operands, quoted strings read in double quotes and templates and
  regular expressions as written, once comments, parentheses, `x!` and a
  cast to one named type are taken out of each, together with
  Python's outer no-op arithmetic (`x + 0`, `0 + x`, `x - 0`, `x * 1`,
  `1 * x`, `x / 1`, repeatedly, only as the outermost operation). An
  equality (`toBe`, `toEqual`, `toStrictEqual`, chai `equal`, `eql`,
  `deep.equal` and the assert equalities, node:assert's four, AVA `is` and
  `deepEqual`, tap `equal`, `same`, `strictSame`, and their negations) or an
  inclusive bound (`toBeGreaterThanOrEqual`, `toBeLessThanOrEqual`, chai
  `least`, `most`, `isAtLeast`, `isAtMost`) whose two sides compare so is
  TAUTOLOGY. Truthy spellings (`assert.ok(x === x)`) are a residual.
- Q6 (a), recording. A tautology keeps `left`, text, span and operand
  evidence as read, so `fingerprint_text` and every finding key stay as they
  were, and records form `tautology`, strength TAUTOLOGY, no predicate key and
  `positive=True`. A self-comparison in an oracle's place is a strength drop
  (`ASSERT_WEAKENED`), and on a local bound to one call it reports that
  instead of `EXPECTATION_DEFINITION_CHANGED`, whose JS channel reads only
  unweakened `compare_eq` pairs.
- Q10 (a). #431's fix landed first (#449, v0.8.0), so this change carries
  its fixtures, which stay in the suite unchanged, and restates #431's "IR
  form or strength" line in THREATMODEL row 129 and
  `docs/js-catch-swallowing.md`.
- Q4 (a). Row 10 gets its JS/TS clause, pointing to the new
  `docs/js-reachability.md`. Rows 8, 29 and 48 get theirs with the second
  change, which reads reachability (Q1, Q3, Q5).
- Q9 (b). Dead test registration is outside both changes.

Readings left to the implementation, accepted with this entry:

1. The ruling's premise for Q10 does not hold as written: #431's
   `HandlerReader.passing_literal` reads the assertion's `left`, `predicate`
   and `positive`, not only source tokens. Q6's "no predicate key" would turn
   every literal-only catch from `catch always-passing assertion` back into
   no evidence. So the frontend sets form and strength when it reads an
   assertion, after its operand evidence, and drops the key and polarity of
   a tautology only after `swallowing_handlers` has read the file. #431's
   outputs do not change; the catch proof never reads the rating.
2. "Expected operand (if any)" is read as every operand the predicate
   reads: the expected value, a bound, a tolerance (`toBeCloseTo`'s
   precision, chai `closeTo`'s delta, both `within` bounds) and a property
   name. One that is not a literal leaves the assertion a real one.
3. Arrays, plain objects and regular expressions of literals are exact
   literals, as a container of literals is in Python. This moves two of the
   three existing expected outputs below. The owner ruled so on 2026-10-17
   (rule 2, below).
4. A negated self-comparison is TAUTOLOGY too, as Python reads `x != x`;
   it can never pass and states no oracle. With `positive=True` (Q6), paired
   with a negated check of a value it reads as a change of form and
   polarity, as in Python. Exclusive bounds (`x < x`), which Python does not
   read either, keep their rung, and so do `toBeCloseTo(x)`, `toContain(x)`,
   `include`, `toMatch` and `within`. So does a property's value compared
   with that property (`.property("total", order.total)`,
   `assert.propertyVal`), which still asserts that the property is there.
   The row-10 stripping is Python's reading, not an evaluation: `x + 0`
   reads as `x` although `-0 + 0` is positive zero under `Object.is`.
5. An assertion whose predicate is not read (strength None: `raises`,
   `unknown`) keeps strength None.
6. What the lexer cannot read gives no literal and no operand to compare,
   so the assertion keeps its rung: a `/` right after a `}` or a statement
   head's `)` (`if (ok) /a/.test(s)` in a callback inside the operand),
   which may start a regular expression or divide; a `/` inside a template
   substitution, which may hold a `}`; and an Annex B HTML-like comment. A
   `//` comment ends at any line terminator, U+2028 and U+2029 included.
   Regular expressions and templates reach the quote and bracket scanners
   as placeholders spelled from their text, every one of them, so a quote,
   bracket or nested template inside one hides no operator
   (`f(/'/) || g(/'/) + 0` keeps its `+ 0`) and no template as written
   spells another's placeholder. These came from a read-only review workflow and were
   checked by Claude.
7. A cast to one named type inside an operand binds as TypeScript binds
   it: looser than the arithmetic before it, which is the cast's own
   operand, while what follows applies to the cast. `total as number + 0`
   is `(total as number) + 0` and reads as `total`, as the parenthesized
   spelling did; `0 + s as any * 2` is `((0 + s) as any) * 2` and keeps its
   `0 +`. A cast to anything more, or a type followed by `|`, `&` or `<`,
   still leaves the operand whole. Raised by GLM, verified by Claude; the
   precedence before the cast came from a review workflow.

Rule 2. By reading, the ruling expected no existing output to move. Three
do, in
`tests/test_issue215_chai_grammar.py::test_a_should_chain_reads_as_its_expect_chain`
(commit 1800f5c9): `(5).should.equal(5)` (compare_eq/90),
`[1, 2].should.have.lengthOf(2)` (type_shape/50) and
`'abc'.should.match(/b/)` (pattern/60) become tautology/10, with subject,
polarity and value unchanged. The first moves under any reading of Q2; the
other two under reading 3. The owner approved exactly these three on
2026-10-17: 「a」, in reply to the relayed question, where (a) read
「包含（跟 Python 把容器字面值當字面值一致）：三列都改成 tautology/10，left、極性、值都不變」
and (b) was scalars only. Anything else that moves still stops the round.
The three confirmations the ruling asks for are pinned in
`tests/test_issue429_js_tautology.py`:

- `test_js_handrolled_tolerance.py:78`,
  `expect(0.01).toBeGreaterThan(Math.abs(...))`, stays BOUND: Q2 reads the
  source operands, and the bound is not a literal
  (`test_a_literal_bound_is_not_a_literal_assertion`).
- The #363 and #431 catch cases hold: the full assertion list, keys
  included, reaches `swallowing_handlers` before any key is dropped
  (`test_the_catch_proof_reads_the_predicate_before_it_is_dropped`; both
  test files are unchanged).
- A removed `expect(1).toBe(1)` keeps its identity: the content-bound key
  (#421) is computed from the legacy pre-image `expect(1).toBe(`
  (`test_a_removed_literal_assertion_keeps_its_fingerprint`).

No `.gwcase` expectation and nothing under `tests/gates` changed.

**Fingerprints.** No fingerprint scheme changes, and a finding on a
tautology's own evidence keeps its key (the pin above). The message of a
removed literal assertion says `strength TAUTOLOGY` instead of the rung it
read before, and pairs that were silent now report `ASSERT_WEAKENED` under
new keys. A pair whose after side is now a tautology is judged as a strength
drop: where main read it as a keyed relation (`toBe(27)` ->
`.not.toBe(total)`, polarity inverted), the finding's kind, message and v2
key change. #421's content-bound keys (#477) landed
first, so the pin above checks the legacy pre-image each key is computed
from, as `tests/test_js_assertion_identity.py` does.

Evidence status: the change was prepared on a work machine where no pytest,
checkwash or Python ran. CI ran the tests.

- Tests were added: 252 collected items in
  `tests/test_issue429_js_tautology.py` and four `.gwcase` fixtures
  (`js_self_compare_pos` and `js_self_compare_node_pos`, which carry
  `bypass: 10`, `js_literal_replaces_oracle_pos` and
  `js_tautology_reformatted_neg`).
- The documented test count is 19030 (18774 + 256).
- The sweep measures the change (ruling): the standard set, the D-088 sets
  and the JS batch, with the refactor, tamper, decoy and recorded gates.
  `NOT_RUN：工作機規則（POLICY work-machine-local），it runs where the owner approves it`.

The agent wrote this entry in #429's first fix PR #482. The maintainer
approved it on 2026-10-18: 「確認」, after 「裁決都使用建議」, as the merge
commit `49ab38bc` records.

## D-148 (2026-10-17): an assertion a JS/TS test callback never reaches is not its assertion (#429, second change)

Ruling 429 (owner, 2026-10-14, 「P1 全部照建議」) answered its ten
questions as recommended. Q8 (b) splits the round into two changes; this
entry is the second (Q1, Q3, Q5). D-147 is the first change's, so this
entry is D-148.

#429's other two edits were an assertion parked under `if (false)` and a
`return;` before one. The JS/TS unit scan collected every assertion call
inside a test callback: `owned()` excluded only nested functions and
parameter positions, and nothing read a `return` or a branch condition.
Python stops at an unconditional `return` or `raise` and constant-folds
branch conditions (SPEC §2b), so both edits block there and passed here.

How each ruling answer is implemented:

- Q1 (b), the walker. `Reachability` in the new
  `frontends/javascript/reachability.py` is built once per file and reads
  each scanned unit's block-bodied callback once, when its call parsed and
  it has assertions. It cuts the rest of a statement list after an
  unconditional `return` or `throw`, and skips the branches the Q5 folder
  decides: the body of `if`, `while` and a three-part `for` whose condition
  folds false, and the `else` of an `if` whose condition folds true. It
  descends into blocks, loop and `do` bodies, `try`/`catch`/`finally`
  blocks and labeled statements; a loop, `do`, `try` or labeled body never
  passes its termination out. It never enters a function, arrow or class
  body, D-106 iterator callbacks included. Where it cannot prove a
  statement's end, it stops reading that list and what follows keeps
  today's reading. It replaces draft #402's reader, which never merged, and
  reuses its proven pieces: the re-pairing of every bracket in the
  callback, the `return` restricted-production test (a line break right
  after the word ends the statement, proved only when the text between is
  whitespace and comments), the U+2028/U+2029 guard, the exclusion of a
  recovered call, and the cut spans on `ParsedFile` that keep the coverage
  inventory from reading a cut assertion as one it missed.
  `swallowing_handlers` still receives the full uncut list, so #363's
  catch evidence is unchanged.
- Q3 (a). An expression statement whose last top-level `&&` or `||` has an
  assertion as its right operand, running to the statement's end, drops
  that assertion when everything before the operator folds to the value
  that skips it (false for `&&`, true for `||`). The statement starts on a
  boundary the walk proved, so its first token cannot continue the line
  before. Ternary, `??` and comma forms stay residuals.
- Q5 (b), the folder. `fold_condition` tokenizes a condition's text and
  reads literals, `!`, parentheses, `&&` and `||`, `===` and `!==` between
  literals, the other comparisons between literals of one primitive type,
  and `undefined` and `NaN` only where `Bindings.is_global` says they name
  the unshadowed global. Anything else is unknown, `const` bindings
  included. `literals.scalar_literal` reads one literal token's value.
  `_truth()` keeps reading test liveness options, unchanged.
- Q4 (a). Rows 8, 29 and 48 get their JS/TS clauses, pointing to
  `docs/js-reachability.md`, and the new fixtures cite them.
- Q9 (b). A test registered in dead code is outside this change; the
  follow-up for the JS TEST_DISABLED channel is filed separately.

Readings left to the implementation, accepted with this entry:

1. A plain block passes its termination on: `{ return; }` ends the
   statements after it. Q1 names the bodies that do not (loop, `do`,
   `try`/`catch`/`finally`, labeled); a block runs its statements in order.
2. An `if` whose condition is unknown passes nothing on, even when both
   branches end, as Python's `_unreachable_ids` reads it ("only a
   statically selected branch inherits its body's termination").
3. Only `return` and `throw` cut, as only `return` and `raise` do in Python;
   `break` and `continue` do not.
4. An absent three-part `for` condition is true. A `for ... of` or
   `for ... in`, a `do ... while` condition, `switch` and `with` are not
   folded. A `switch` body is not read: the walk steps over it, so a
   `return` in a case cuts nothing and a `return` after the `switch` still
   cuts. A `with` statement stops the walk of its list.
5. `&&` and `||` fold as Python's `_static_truth` folds `and` and `or`: one
   false operand decides an `&&` and one true operand an `||`, wherever it
   stands. Their truthiness is JavaScript's, whatever is evaluated first.
6. For Q3, folding everything before the last top-level `&&`/`||` to the
   skipping value proves that the last operand never runs, whatever the
   operators before it: `a || b && E` skips `E` when `a || b` is false.
   Only that last operand is dropped.
7. A boundary is proved only where the text between two tokens is
   whitespace and comments. A `;` after an operand the tokens omit (a
   template or regular expression) still ends a statement. A function
   declaration with a TypeScript return type, `import`, `export` and `with`
   stop the walk.
8. The cut spans are carried on `ParsedFile` (`unreachable_assertion_spans`
   and `unreachable_unjudged_assertion_spans`), not in the IR, so neither
   IR_VERSION nor FINDINGS_VERSION changes.
9. An imperative skip (`t.skip()`) in dead code still marks its test, as
   before.
10. A callback is not walked when the shared token stream misreads text as
    code anywhere from the file's start to the callback's end, since a
    misreading shifts what the mask reads from there on (sixteenth and
    seventeenth review rounds; a reserved word such as `default` ends no
    operand, the file's first token is checked too, a `<` first on its line
    before a name or `>` is JSX, and an HTML-like comment inside a template
    substitution leaves the template unread): a template nested in another's
    substitution (the mask ends a template at its first backtick; each
    template is read again as `literals` reads it, a quoted `}` or a `//`
    comment in a substitution included, and one it leaves unread refuses the
    callback too), JSX or a TypeScript `<T>x` assertion (a `<` where no
    operand ends, or right after a block's `}`), a token outside a string that
    is not ASCII (the binder reads names as ASCII and U+FEFF as a token, where
    JavaScript reads a name and a space), a `\` outside a string anywhere in
    the file (an identifier escape: `return\u0041` is one name), a dead region
    holding a `function` (a call before it may run the hoisted body, which the
    binder does not always scope: `function f<T>()`), a `/` the mask reads as
    a division where JavaScript starts a regular expression (after a `}`, a
    statement head's `)`, an update or an operator, or first on its line), a
    regular expression the mask reads where JavaScript may divide (it is
    trusted only after an operator, a punctuator such as `(` or `,`, or a
    keyword such as `return` that is no property name), or an Annex B `<!--`
    or `-->` comment.
11. `_end` reads on past a line break wherever the binder's ASI reading
    continues the statement, and JavaScript or TypeScript may end it there
    (`x!`, `as Config`, an arrow's `}` or `() => void` at a line's end, `{`,
    `(`, `[` or `.5` at the next line's start). Reading on only shortens a cut
    after a `return`, but it could lengthen a kill, so a dead body that is no
    block is killed, and a literal-decided `&&`/`||` statement (Q3) decided,
    only when every line break inside it follows a token that leaves the
    expression unfinished: an operator such as `&&`, `+`, `,`, `=` or `=>`, or
    a reserved word such as `typeof` or `delete` where no `.`, `?.` or `#`
    makes it a property name (`cache.delete` is a whole operand), and not `.`,
    which may end a number (`1.`); otherwise the walk of that list stops, or
    the statement stays undecided. A statement keyword met inside a statement
    (`do` after a `{ }` the binder read on into) stops the walk (twelfth
    review round). A statement with a template or regular expression right
    before it (one that is the whole body of `if (false)`) stops it too, and
    Q3 decides a statement only after a `;` or a statement's own `}`, never at
    a boundary ASI gives, which TypeScript may read past (`v is` then
    `false`), as the ruling's "narrowly" asks (fourteenth review round). A
    prefix `++` or `--` at a line's end takes the next line as its operand, so
    a `return ++` there does not end the statement, and neither does a line
    starting with `extends` or `implements` after a class expression. A class
    whose heritage holds a class, a function or an arrow stops the walk: its
    first `{` is not the class body. After a token that completes no operand,
    a line starting with a statement keyword (`do`, `if`, `while`, `return`)
    stops it too: TypeScript ends `x!` there. And a `return` or `throw` whose
    operand ends at a line break by that reading stops the walk instead of
    cutting: TypeScript types (`readonly`), class heritage (`implements`) and
    decorators (`@dec` then `class`) continue such a statement where the
    binder ends it. (Eleventh review round.)
12. The folder reads tokens from `literals.operand_tokens`, so a nested
    template is one token, and a `/` that may divide or start a regular
    expression (after `++`, `--`, `!`, `>`, `of`, `await`, `yield` or a
    keyword used as a property name, after `.`, `?.` or `#`) leaves the
    condition unknown; it gives
    up past 64 levels of `!` or parentheses rather than recursing further.
13. `undefined` and `NaN` fold as the globals only where the binder finds no
    declaration in scope and every spelling of the name in the file is a
    plain read the walk can see: a token (none in a string, comment,
    template or regular expression, and no U+2028 or U+2029 in the file),
    right after an operator, `return`, `typeof`, `void` or `case`, or first
    in an `if` or `while` head or a call's arguments, and never before `=`,
    `=>` or a type's `:`; and the file holds no `with` (a comment before its
    `(` included), no `eval` and no `\u` escape, which may spell the name.
    The binder
    does not scope everything that binds them (a parameter before a
    TypeScript type, an enum or namespace, a block's function Annex B
    hoists), so anything else leaves them unknown, as the ruling's "only as
    unshadowed globals" asks. These came from the sixth and seventh review
    rounds.

Rule 2. By reading, no existing expected output moves, and none does: no
existing fixture or test spells an assertion after a `return` or `throw`,
or under a decidable branch, in a test callback, except the #363 and #431
catch tests, which read `swallowing_handlers` only, and that still receives
every assertion. The three confirmations are pinned in
`tests/test_issue429_js_reachability.py`:

- the catch evidence reads the uncut list
  (`test_the_catch_evidence_still_reads_every_assertion_the_callback_spells`);
- the coverage inventory reads a cut assertion as represented, and an
  unread one keeps its reason
  (`test_an_unread_assertion_no_statement_reaches_keeps_its_coverage_reason`);
- a parked assertion is `ASSERT_REMOVED` with the key a deleted one has
  (`test_a_parked_assertion_is_removed_with_the_key_a_deleted_one_has`),
  whichever key scheme is on main.

No `.gwcase` expectation and nothing under `tests/gates` changed.

**Fingerprints.** No fingerprint scheme or existing key changes. An
assertion parked where the callback never reaches it, which reported
nothing, now reports `ASSERT_REMOVED` under the key its deletion has.

Evidence status: the change was prepared on a work machine where no pytest,
checkwash or Python ran. CI ran the tests.

- Tests were added: 296 collected items in
  `tests/test_issue429_js_reachability.py` and twelve `.gwcase` fixtures,
  nine of which carry `bypass:` (8, 29 and 48, and 8, 10 and 29 on the
  issue's own edits, `js_issue429_repro_pos`).
- The documented test count is 19338 (19030 + 308).
- The sweep measures the change (ruling): the standard set, the D-088 sets
  and the JS batch, with the refactor, tamper, decoy and recorded gates, and
  the perf gate. `NOT_RUN：工作機規則（POLICY work-machine-local），it runs where the owner approves it`.

The agent wrote this entry in #429's second fix PR #483. The maintainer
approved its text as of `abe23890` on 2026-10-18 (「1.核可」), and the
seven later commits that change it (`3ee503f7`, `16601f48`, `80842f81`,
`4a373b5c`, `c2429bab`, `ff46583e`, `1915a1e3`) on 2026-10-18, choosing
「核可（推薦）」 in the agent's question (the option text is the agent's).
In the same reply the owner chose 「開 follow-up，先選 (c)」: the class of
misreadings no refusal notices is a documented residual for now, filed
as #490.

## D-149 (2026-10-18): a transparent class decorator and a function-local class name leave a helper method resolved (#487)

Ruling 487 (owner, 2026-10-18, 「19 項全部照建議做（價值判斷的題也照你的傾向）」,
"all as recommended, value judgements included"; #487
issuecomment-6248630528, stating each decision in full, as the list it
answers, whose item 8 is #487, was prepared off GitHub): (a) adopted with
the stdlib forms, (b) not adopted, (c) adopted. #487: since #306's fix
(D-145, #476, `81c69d28`), a decorator on any class of the order up to the
binder left every helper method reached through `self` unresolved
(`self_methods.py:250-251@81c69d28`), so adding one read its `via`
assertions as removed (ASSERT_REMOVED at warn, raised to high under
NO_PROD_CHANGE_IN_DIFF), unstated in D-145 and row 91; and a class local
to a test method, named like the test class, was read as rebinding the
module's class (scrapy `02ed71d887`).

Implementation, in `frontends/python/self_methods.py` only (lines at this PR):

- (a), with the stdlib forms, superseding D-145 Sub-Q2's decorator clause:
  a class of the order up to the binder leaves the call unresolved only
  when a decorator on it is not transparent (`Methods._resolve`,
  `:509-511`; `Methods._transparent`, `:392-430`). Names are read through
  `setup_skip_controls.module_bindings` with its default `mutated=True`
  (`:284`, not #220's `mutated=False`), so `@pt.mark.slow` under
  `import pytest as pt` is `pytest.mark.slow`, and no call with a starred
  or `**` argument is transparent (`:414-416`). Transparent are
  `pytest.mark.<name>` with no leading `_` (`_is_mark`, `:116-120`), bare
  or called, but not with one positional argument, and no keyword, that is
  no `ast.Constant` (`:417-420`; the rule of `own_marks.py:528-532`, #358,
  D-126, replacing the issue's wider list); and, from `unittest` or
  `unittest.case`, a fixed literal list as Sub-Q6's (`_SKIPS`, `_EXPECTED`,
  `:105-110`): `skip(<str>)`, `skipIf(<condition>, <str>)` and
  `skipUnless(<condition>, <str>)`, the reason a `str` constant at its
  position or as the only keyword, `reason=` (`:421-430`), and bare
  `expectedFailure`; a form that can disable a test only as the two
  departures below allow. Not transparent: bare `@unittest.skip`, a reason
  that is no string literal, `expectedFailure(...)` called, a name that
  resolves to `twisted.trial`, every other decorator (#306
  issuecomment-6170351314, item 2), a same-file value such as
  `slow = pytest.mark.slow` (not followed this round), and, as ruled, a
  form under a root the module binds more than once (as
  `own_marks.py:306-334` counts) or stores or deletes an attribute under
  (`pytest.mark.slow = wrap`), or that readings 1 to 4 and 11 make opaque
  (`:401-404`), all read in any order, as a class decorator runs with its
  class statement.
- Sources, read on 2026-10-18 as text: CPython's `Lib/unittest/case.py`,
  `def skip` to `expectedFailure` and `_id`, is the same on 3.11 to 3.14
  and main (101-102 and 147-185 on 3.11, 102-103 and 157-195 on 3.14), the
  four names exported eagerly; pytest `cb6ff97b`, as main `420cf37a`, has
  `istestfunc`, `MarkDecorator.__call__` and `MarkGenerator.__getattr__` at
  `src/_pytest/mark/structures.py:56-57, 420-433, 610-649` (`_` rejected at
  612-613). Run time is looser twice, leaving unresolved a call that could
  resolve: `skip` returns the class for any reason but a plain function,
  `skipIf` and `skipUnless` through `_id` when the condition does not skip.
- (b), not adopted, in general or for class decorators (a value judgement;
  the owner took the agent's lean): a helper resolved at the parent only
  keeps reading as its assertions removed (`ir/diffalign.py:127-136`),
  which catches row 91's "stop invoking it while leaving it in place" and
  which #502 (#306's residual spellings) relies on; (b) would return those
  commits to #306's zero findings, and with (a) clears no measured finding.
  Instead a fourth stated cost joins D-145's three (Sub-Q7's, Sub-Q4's
  two): a class decorator outside the admitted list, added to a class up
  to the binder, reads as the helper's assertions removed
  (`self_method_class_decorator_added_pos`,
  `test_stated_cost_an_arbitrary_class_decorator_added_reads_as_the_helpers_assertions_removed`),
  and removed reads nothing as removed (`ir/diffalign.py:130-136`,
  `test_an_arbitrary_class_decorator_removed_reads_nothing_as_removed`); an
  admitted form left unresolved costs the same. As with Sub-Q7, a
  follow-up for vetted class-returning decorators (`mock.patch` on a class,
  Django's `override_settings`) waits until the cost proves real: D-145's
  review puts every decorator finding of the standard and D-088 sets in
  the six commits below, all admitted; elsewhere it is unmeasured (the
  #421 cache's eleven repositories include no Django).
- (c), adopted: only a binding of the module's own name rebinds a module
  class, as D-145 Sub-Q2's "a class name the module binds more than once"
  says (ruling 306: "a duplicate or rebound class name"); D-145's Cost
  said the old any-depth walk (`self_methods.py:134-143@81c69d28`) went
  beyond it. A binding `_module_binds` (`:181-213`) yields, but the class's
  own statement, rebinds it (`:270-277`): a statement at module scope,
  under a module-level `if`, `try`, `for`, `while`, `with` or `match` too,
  with an `except ... as` or match capture (missed before); an assignment
  expression there, in a comprehension too (PEP 572); a def's, class's or
  lambda's header there (`_header`, `:172-178`: decorators, bases, class
  keywords, defaults, annotations), as `class Other((TotalTest := Fake))`;
  and any body declaring the name `global` (`:312-316`). Other bodies bind
  locally (`setup_skip_controls._names` alone reads no header or body); the
  top-level class and def count (`:265-269`) and Sub-Q3's walk stay.

**Two departures from the ruling, for the owner's approval.** The ruling
admits (a)'s forms on any class up to the binder in any spelling, since,
as a subset of what the frontend reports as TEST_DISABLED
(`frontend.py:124-136`), their effect stays reported. That holds only
where a unit carries the decorator; elsewhere a form that can disable a
test leaves the call resolved on both sides, and the commit can pass with
no finding where main `54294b47` reads the helper's assertions as removed.
Such a form (`_disables`, `:128-139`) is a skip form (`_skips`,
`:123-125`: the unittest forms, the marks `skip`, `skipif`, `xfail`),
`usefixtures`, `dependency`, another mark named for a skip or xfail (#209
Q2, `hook_guards._labelling`), or `parametrize`, whose class-level rows
the frontend does not read (an empty list skips every test). It is
transparent only (`:406-411`):

1. On the class running the test (`entry is cls`, `:509`): a unit carries
   its own class's decorators and, for an inherited test, the defining
   class's (`frontend.class_marks`, `frontend.py:4197-4201, 4387`), not a
   base's (THREATMODEL row 117). Pinned by
   `test_a_skip_on_a_base_up_to_the_binder_leaves_the_call_unresolved` (11 forms)
   and `test_a_skip_added_to_a_base_keeps_reading_as_the_helpers_assertions_removed`.
2. Where the running class's units carry it (`_carried`, `:142-157`): a
   skip form only when `frontend._canonical_marker` reads its name as
   spelled, by trailing parts (`frontend.py:1831-1851`, used at `:1898`;
   it resolves no name, accepting `*.mark.skip` from any root): a last
   part `skip`, `skipIf`, `skipUnless` or `expectedFailure`, or last two
   `mark.skip`, `mark.skipif` or `mark.xfail`, so not `@when(...)` under
   `from unittest import skipIf as when` or `@m.xfail` under
   `from pytest import mark as m`; a `usefixtures` only bare or with only
   str-literal positional arguments and no keyword, as
   `setup_skip_controls._usefixtures` (`setup_skip_controls.py:627-632`)
   reads; never `dependency`, a mark only named for a skip, or
   `parametrize`. Pinned by
   `test_a_skip_spelled_as_the_frontend_does_not_read_it_leaves_the_call_unresolved` and
   `test_a_disabling_mark_the_running_classs_units_do_not_carry_leaves_the_call_unresolved`.

The alternative to each is the ruling's scope, with a further stated cost:
such a form added to a base up to the binder (1), or to the running class
in a form its units do not carry (2), disables tests with no finding.

Readings where the ruling is silent, accepted with this entry (1 to 7 err
toward unresolved, 8 and 9 follow (c), 10 keeps the old walk's reading):

1. A store or del under a root (`_root`, `:220-228`: `type(x).y` is under
   `x`) is read anywhere, bodies included (`:317-327`), and a write reaches
   a package through any name any `import` or absolute `from ... import`
   binds (`:291-305`, `_mutate` at `:386-390`; `_module`, `:166-169`, reads
   `_pytest` and `py` as pytest), as `MarkDecorator.__call__ = wrap` does
   under `from _pytest.mark.structures import MarkDecorator`.
2. A star import makes every root opaque (`:290`).
3. A root is bound more than once by either count (`:273-275`,
   `:285-289`), per top-level statement or per binding: `import unittest`
   beside `import unittest.mock` makes `unittest` opaque.
4. `global <root>` anywhere, at module level too, makes it opaque (`:316`).
5. A root no import binds is not transparent.
6. Only `pytest.mark.<name>`: not `py.test.mark.<name>`, `pytest.mark._x`
   or `pytest.mark.<name>.with_args(...)`.
7. `skip` takes one positional argument or only `reason=`; `skipIf` and
   `skipUnless` take the condition by position only (not `condition=`);
   nothing further. The reason is a `str` constant (empty or implicitly
   concatenated too), not an f-string, a t-string, a `+` or a name.
8. A comprehension's own target at module scope rebinds no module class
   (the old walk read it so), but counts for a decorator root.
9. A walrus in a lambda's default binds the module's name, unlike its body's.
10. Annotations are module-scope code even under `from __future__ import
    annotations` (`TotalTest: int` rebinds); type parameters are not read.
11. Writes are read by target (`Methods._writes`, `:353-384`, from
    `_call`, `:336`), catching the named residual
    `setattr(pytest.mark, "slow", wrap)` and its kind: a call whose last
    name is in `_SETTERS` (`:96-97`: the set and delete names and their
    dunders, as `b.setattr` under `import builtins as b`), any call with a
    `patch` component, and a `_DICT_SETTERS` method (`:98`) on `x.__dict__`
    or `vars(x)` (`:160-163`) or with such a first argument. The target is
    the first positional argument, or `target=` or `in_dict=`, all
    arguments when one is starred, and the owner of a bound
    `x.__dunder__(...)` or dict method; never the value, so
    `patch.object(Other, "rate", unittest.mock.Mock())` reaches nothing. A
    str-literal target adds its package (`mock.patch("pytest.mark.slow",
    wrap)`). Sub-Q3's bookkeeping (`_SETATTR`, `:93-94`; `:337-351`) stays.

Residuals, by kind: a write the reading does not name (a setter or patcher
under a name it does not list; a write through a value the file computes,
such as a same-file alias `m = pytest.mark`, a function parameter or a
call's return value, since following aliases would let `m = mock.Mock()`
then `m.x = 1` take every unittest form; or into a module named by a
string key, such as `globals()["pytest"]`, `sys.modules`, `__import__` or
`importlib`) and a store in a conftest or plugin leave an admitted form
transparent; a star import that binds a module class's name is not read
as binding it again, as the old walk did not read it; and a class body
run under a metaclass whose `__prepare__`
returns the module's namespace is read as binding local names, so its
`TotalTest = None`, which the old walk caught, rebinds nothing. The owner
kept this a residual (below); the code alternative, not adopted, was to
read as module scope the body of any class statement, at any depth, that
has any keyword or whose same-file base chain reaches any keyword or a
base the file does not define.

Conservative side effects, each leaving unresolved a call that could
resolve, so an admitted form added there reads as the helper's assertions
removed: a write whose target names `unittest` or anything imported from
it makes every unittest form in the file opaque (`mock.x = 1` under
`from unittest import mock`; `unittest.TestCase.maxDiff = None`, as #220's
note at `setup_skip_controls.py:466-468` says for `mutated=True`); a
disabling form on a base stays unresolved for a test the running class
inherits from it, although that unit carries it (`frontend.py:4387`); and
`dependency`, skip-named marks and class-level `parametrize` stay
unresolved even on the running class.

**Effect, by reading.** This clears the 213 findings of six scrapy commits
in #421's sweep (#487 body; D-145 Cost): 179 from pytest marks
(`c8aa429c9b` 168, `e058a05763` 8, `14737e91ed` 3) and 34 from `skipIf`
and `skipUnless` (`36c3c9713e` 4, `c5b1ee8101` 24, `c76190d491` 6).
`c8aa429c9b` goes back to pass with its 4 warn findings and `e058a05763`
with its 6 TEST_DISABLED warn (COMPAT_GATE); the other four stay block on
their existing findings, without the 37 added ASSERT_REMOVED. By a
read-only check of their changed test files in the sweep's scrapy cache
(`git show`, `grep`, no engine), every added class decorator is a label
mark (`requires_reactor`, `requires_http_handler`, `requires_mitmproxy`)
or a skip in a spelling `_canonical_marker` reads (`pytest.mark.skipif`,
`skipIf`, `unittest.skipUnless`) on a running class with no same-file
subclass, or on `Https2TestCase` (`c5b1ee8101`), whose only methods are
tests and a `setUpClass` over an imported base, so no subclass's helper
call resolves through it; none is `parametrize`, `dependency`,
`usefixtures` or a skip-named mark; each root has one top-level import,
with no `global` or star import; and no write's target names a name
imported from `unittest` or `pytest` (patch targets are scrapy classes or
dotted strings under `scrapy` or `google.cloud`). So no reading or
departure keeps any of the 213. In `02ed71d887` the commit side now
resolves and its leftover `via` assertion pairs with its rewritten twin,
not `test_simple`'s: its 1 ASSERT_SUBSTITUTED high goes, it stays block on
its 71 TEST_DISABLED high, and #306's separate ASSERT_WEAKENED high there
is unaffected. The frontend still follows `TestItem(new="New")` into the
module test class although a local class shadows the name, outside #487.

Rule 2. The ruling approves no change to an existing expectation: by
reading none moves, and none was changed. On main `54294b47` the only
`.gwcase` fixtures with a class decorator are
`abstract_base_subclass_skipped_pos` and `class_skip_pos`, and none binds
a module class's name in a body or declares `global`. The inline sources
with a class decorator the ruling's (a) admits (under `tests/`,
`test_frontend.py:242`, `test_setup_phase_skips.py:281,289`, whose
`parametrize` this entry leaves unresolved,
`test_issue223_conftest_request_side.py:135,151`,
`test_issue358_own_mark_guards.py:206,224,259` and
`test_issue254_class_attribute_guards.py:305`) reach no helper method
through `self`; the others (`@decorate`, the alias `@later`) and
the `@decorate` cases in `tests/test_issue306_self_methods.py` stay
unresolved. Nothing under `tests/gates` changed; if CI shows an existing
expectation moving, the round stops.

**Fingerprints and IR.** No fingerprint scheme, IR field or key changes.
More calls resolve, so `--emit-ir` gains `via` assertions and
class-qualified `helper_calls` keys for helper methods of classes with an
admitted decorator, or whose name only a body binds again (not measured).

**Release.** #476 is in no tag (v0.8.0 is from 2026-10-15), so this
changes no released behaviour. The ruling makes (a) with the stdlib forms
block the next release; (c) goes in the same PR but does not. If the owner
releases before this merges, `docs/KNOWN-ISSUES-next.md` gets a #487 row.
Any release still needs the owner's one-time named authorization.

**Measurement.** Not measured yet. After the fix merges, the standard set
and D-088's sets are rerun before and after where the owner approves, as a
checkwash-lab-declared run: on LAPTOP-01AGNPJU only under EC POLICY
`checkwash-pju-sweep` (T-546), with the frozen manifest and engine commits
approved first, otherwise on the pool; the whole sets, not only these
seven commits, since new `via` assertions can add findings in classes
decorated on both sides, or whose name only a body binds again. The effect
above is expected; the measured cost goes here once the rerun has run.
`NOT_RUN：工作機規則（POLICY work-machine-local），every effect above is read from source; no engine, engine variant, test or IR emission was run`.

Evidence status: prepared on a work machine where no pytest, checkwash or
Python ran; CI runs the tests. Added: five `.gwcase` fixtures
(`self_method_class_mark_added_neg`, `self_method_base_class_mark_added_neg`,
`self_method_class_decorator_added_pos`, `self_method_class_skipif_added_pos`,
`self_method_local_class_same_name_pos`), labels reviewed before merge,
and 94 collected items in `tests/test_issue306_self_methods.py`, counted
from its parametrize lists, which pin the ruling's stay-unresolved forms;
no existing test changed. By reading, the documented test count becomes
19450 (19351 + 94 + 5); CI's collection checks it.

The agent wrote this entry in #487's fix PR #503. The maintainer approved
it on 2026-10-18: 「核可 #503：SPEC 26512274、第 91 列 63650ccc、D-149
377c133d 的措辭照草稿；兩個偏離採你的建議（停用類形式只在執行測試的類別上、
且只在 units 帶得到時才透明）；11 個讀法照 D-149；metaclass 留作殘留；5 個
gwcase 標籤照寫。CI 全綠就代合。」, in reply to the agent's list asking for
approval of this PR's SPEC (26512274), THREATMODEL (63650ccc) and D-149
(377c133d) text, the two departures, the eleven readings, the metaclass
residual and the five fixtures' labels.

## D-150 (2026-10-18): a size refusal of the change itself blocks the Claude Code Stop hook (#456)

Ruling 456 (owner, 2026-10-18) came in two comments. The first
(issuecomment-6248011888, 「照建議」, "as recommended") adopted the issue's
Recommendation: Q1 (b) as scoped, with (d) once #454 is ruled; Q3, only a
path in the diff with a head or worktree side over the limit; Q4, block on
every stop; Q5, no config knob. The second (issuecomment-6248628843,
「19 項全部照建議做（價值判斷的題也照你的傾向）」, "all as recommended, value
judgements included") settled Q2, Q6, Q7 and the priority, stating each
decision in full. D-149 is the last entry on main, so this entry is D-150.

#456 reports that a must-read changed file over 1,000,000 bytes stops the
run (D-135) and hook-json reports every engine error as a non-blocking
`systemMessage` (D-134 item 2), so an agent whose test edit would block can
pad the test, or add an untracked `.py` or extensionless file over the
limit, and stop. v0.8.0 ships this escape.

Implementation, in `src/checkwash/cli.py` (lines at this PR):

- Q1 (b) and Q3. Only the `_analyse` call on the verdict diff catches
  `SourceOverLimit` (`_cmd_check`, `:392-403`). In hook-json (`_hook_json`,
  `:899-901`, false with `--emit-ir`), `_verdict_side_over_limit`
  (`:927-945`) finds the change whose `FileChange.unread`
  (`change.py:49-50`) holds the refused side, `SourceOverLimit.unread`
  (`change.py:57-62`), an `UnreadSide` (`change.py:8-38`), equal in path,
  side, size and limit, and returns its head or worktree
  side. A refusal names the change's first unread side, the base side when
  both are over the limit (`engine.py:300-303`, `:311-314`), so the change
  is judged on all its unread sides. With such a side, the engine-error
  line still goes to stderr (`_advise`), and `_hook_size_block`
  (`:948-970`) prints `{"decision": "block", "reason": ...}`, exit 0. The
  reason names path, side, size and limit, says to shrink or split the file
  or revert the change to it, and not to delete or truncate a file the
  agent did not create or change in this task but to tell the user. It
  offers no `checkwash allow` and says nothing about CI. Otherwise the
  exception is re-raised into `main()`'s handlers (`:884-890`), which are
  not widened.
- Q4 and Q5. Nothing reads `stop_hook_active` or a new `[gate]` key, and
  the refusal aborts the analysis before any finding exists for an
  exemption, `detectors.disable` or `fail_on` to act on.
- Q2. The frozen exit-code row is touched (below). The session-commits
  analysis is not the verdict diff: `_session_note` (`:300-329`) runs
  outside the new `try` and keeps its note (`:318-319`), so a padded file
  the agent commits before stopping stays open (D-142 item 4).
- Q6, not widened: the directory-symlink refusals keep the note (D-134
  item 2); the subject-replacement and stand-in limits and `RecursionError`
  go to their own follow-up issue, #506.
- Q7. SPEC §9 gains hook-json's verdict mapping and the (b) sentence, and
  §4b's "The run exits 2" points to §9; §4b's context sentence now says the
  run "refuses in the same way", so the pointer covers it too. Priority: P1,
  as for #418.
- (d) is not in this PR. #454 is ruled, and its ruling
  (issuecomment-6248628332, item 6) leaves any reuse of its entry for an
  exit-2 run, and the test changes that needs, to #456. #454's entry is not
  implemented yet, so #456 stays open for (d); the owner confirmed the
  deferral (below). (d) will need its own rule-2
  approval: `tests/test_issue415_oversized_sources.py:637` and this PR's
  `tests/test_issue456_hook_size_refusal.py:209` and `:255` assert an empty
  stdout on exit 2.
- The issue's Acceptance asks that the README and
  `docs/subject-integrity.md` describe what the Stop hook does; both now
  say that this refusal blocks the stop and name what keeps the message.

These keep the note by construction: a change whose base side alone is
over the limit (shrunk, replaced or deleted), which has no head or worktree
side; a root manifest, config, exemption list or task file that `_analyse`
reads before the analysis, whose `GitSourceOverLimit` is a `GitError`
(`gitio/git.py:145-151`) and never reaches the new `except`; a context read
of a file the diff does not hold (`WorkingTreeSnapshot.read`,
`gitio/snapshot.py:579-582`), which matches no change; and, with a range
only, a pytest configuration's symlink target over the limit at head that
no detector must read (a target with a suffix, outside every must-read
class of §4b). `_set_aside_unread` sets such a target aside
(`engine.py:656`); `PairedPytestConfigs.prepare`
(`gitio/pytest_configs.py:57-81`, called at `engine.py:680`) then reads it
through the link and refuses with a plain `EngineError`
(`gitio/snapshot.py:307-308`), not a `SourceOverLimit`, even when the diff
changes the target. A target a detector must read (a `.py`, a pytest
configuration name, a file with no extension) is refused at set-aside and
blocks like any other change. The managed Stop hook never reaches this:
worktree mode passes no `pytest_configs` (`cli.py:334`).

Readings within the ruling's text ("a path in the diff that decides the
verdict, and that path's head or worktree side is over the limit"):

- With a range, hook-json blocks on a head side over the limit there, when
  the refusal is that change's `SourceOverLimit`.
- A change set aside because no detector must read it (D-135) blocks too
  when a guarded read refuses it (`engine.py:318-341`) and it has a head or
  worktree side over the limit.
- An untracked, non-ignored file over the limit that the user left in the
  tree, when a detector must read it (a `.py`, a file with no extension
  such as `tags`) or a guarded read reaches it, blocks every stop until the
  user ignores or removes it: the issue's loop risk, accepted with Q4.
  Other untracked files that large are set aside, and the run gives its
  verdict.

Not settled by the ruling; the owner approved each as written (below):

- The match is exact, so a file that grew after the listing keeps the note.
- `_set_aside_unread` refuses the first must-read change it meets. If that
  change has only its base side over the limit, a later change's worktree
  side over it gets the note too. That is no wider than the base-side
  residual itself; reordering the loop would change which file term and
  json name.
- The size block's reason does not add the session sentence that D-142
  item 6 gives a block ("A block's reason says so and that `/clear` starts
  one"): its remedy is to shrink, split or revert the file, not a policy
  change committed during the session. SPEC §9's sentence now belongs to a
  block on findings. This narrows D-142 item 6.

**The exit-code contract.** `docs/stability.md` freezes the exit codes.
- Before: in hook-json every engine error exited 0 with a `systemMessage`
  and no `decision` (D-134).
- Now: a size refusal of a change in the verdict diff whose head or
  worktree side is over the limit exits 0 with `decision: block`. The code
  stays 0; the row's text changes.
- Why: that side is usually the session's own edit, which one edit removes,
  so D-134's reason, an error the agent cannot fix, does not hold.
- What still holds: "a crash is never reported as a block" stays the
  general rule (`DECISIONS-archive-1.md:9826-9828`); every other engine error carries
  no `decision`. Term, json and sarif keep exit 2 for every engine error,
  this one included, and so does the required CI check.

This amends D-134 item 2 (`DECISIONS-archive-1.md:9790-9793`) for that one class, and
narrows D-142 item 6 (`DECISIONS.md:310-312`) as above; the exit-code
row, SPEC §4b and §9 and THREATMODEL row 128 change with it. It
takes an entry and a minor, as D-134 and D-140 did, though there the code
itself changed, from 2 to 0. The next release is a minor anyway because of
#421 (`docs/stability.md:17-22`), so this costs no extra version number. No
release is authorized (AGENTS.md rule 5). Row 128 reads Open by design,
narrowed, and lists what stays open; `benchmarks/make_failures.py` buckets
it by "open by design" first and its shape cell is unchanged, so
`benchmarks/FAILURES.md` does not change.

Rule 2. The ruling approves no change to an existing expectation: by
reading none moves, and none was changed. The hook-json engine-error tests
keep their note (`tests/test_hook_runtime.py:59-68`,
`tests/test_issue414_worktree_directory_symlinks.py:151-186`,
`tests/test_issue416_subdirectory_root.py:296-308`, `:507-527`), and
`tests/test_issue415_oversized_sources.py:584-599` and `:614-638` keep their
verdict, their single stderr line and exit 2. Nothing under `tests/gates` mentions hook-json, an
engine error or `SourceOverLimit`. If CI shows one moving, the round stops.

Evidence status: prepared on a work machine where no pytest, checkwash or
Python ran; CI runs the tests. Added: 25 collected items in
`tests/test_issue456_hook_size_refusal.py`, none under `tests/gates`: the
block (a padded test, an untracked `scratch.py` or `NOTES`, both sides over
the limit, a head side in a range under `--fail-on critical`); the note (a
base side alone, a context read, a base manifest, the session-commits
analysis, other engine errors); exit 2 in the other modes; and seven unit
cases of the match. The 1,000,000-byte boundary stays pinned by #415's
reader tests only. Not pinned: `allow.toml` entries and
`detectors.disable` (only `--fail-on critical` is), `stop_hook_active: true`
on a repeated stop, a set-aside change refused by a guarded read, a file
that grew after the listing, the first-must-read ordering, and the
range-mode symlink-target case. By reading, the documented test count becomes 19475 (19450 +
25); CI's collection checks it. The sweep calls `analyze` directly
(`sweep.py:131-142`), so it is not expected to move.
`NOT_RUN：工作機規則（POLICY work-machine-local），every behaviour above is read from source; no test, checkwash run or sweep was run`.

The agent wrote this entry in #456's fix PR #505. The maintainer approved
it on 2026-10-19: 「#505 全部照建議：措辭照 commit 核可；3 個沒裁到的點照現在的寫法；
Q6 照 (A) 開 follow-up；(d) 延後到 #454 實作後；這個 PR 不補測試。CI 全綠就代合」,
in reply to the agent's list asking for approval of this PR's stability
row (e2bda38b, 8e25462f), SPEC (240735ce, f8ac8634), THREATMODEL
(a31dba51, 576dc6fa) and D-150 (65848b57, f1f5d971) text, the three
points the ruling did not settle, filing the Q6 follow-up (filed as #506),
the (d) deferral and whether to add the unpinned tests (not added). The
reply is the text of the answer the agent suggested, which the owner
chose.

## D-151 (2026-10-19): a machine-readable findings schema, and what a fingerprint promises (#364)

#364 (talhayme, pr-witness) asked whether the findings shape is stable
across minor versions and offered to match a published schema. The reply of
2026-10-14 left the schema undecided and suggested `checkwash>=0.7,<0.8` as
a package requirement; pr-witness 0.3.2 then declared
`checkwash<0.8,>=0.6`, and v0.8.0 changed nothing it reads.

- `docs/findings.schema.json` (draft 2020-12) describes
  `checkwash_findings_version` 2. Every current key is required and unknown
  keys are allowed, because a release may add an optional key without a new
  number. `tests/test_findings_schema.py` holds the producer side strict.
  Real output from every `.gwcase` and from the CLI must validate with no
  undeclared key. The schema's keys must equal the stability table and
  cover the `Finding` and `Evidence` fields. The schema may not take back
  anything in `tests/data/findings-schema-v2.json`, whose digest the test
  pins. The validator is a standard-library subset that refuses keywords it
  does not implement (D-001).
- A compatible release line is one minor line. A minor release can move
  fingerprints in any namespace, and its DECISIONS entry and release notes
  name them. `checkwash_findings_version` does not move for a fingerprint
  change. Read from the code: v0.3.4, v0.4.1 and v0.4.2 moved keys
  unrecorded, and v0.7.0's moves are recorded only in its round entries.
- Advice to embedders (`docs/embedding.md`): pin exactly in CI. A tool that
  reads the document and stores no fingerprints requires a lower bound and
  checks the version at run time. A tool that stores fingerprints stays
  below the next minor. This replaces the suggestion of 2026-10-14 on #364.
  The owner approved this advice on 2026-10-19
  (「版本範圍照新建議：CI 釘死；只讀文件的工具不設上限、執行時檢查版本；會存
  fingerprint 的工具上限設在下一個 minor 之前。」, "version ranges as newly
  recommended: pin exactly in CI; a tool that only reads the document has no
  upper bound and checks the version at run time; a tool that stores
  fingerprints stays below the next minor").

Correction to D-148: a removed JS/TS test whose callback held an assertion
it never reaches gets a new TEST_DISABLED key, because
`detectors/test_disabled.py:86-88` reads the unit's assertions after
`frontends/javascript/frontend.py:2398-2406` cuts the unreachable ones.

Not decided here: shipping the schema as package data; a fingerprint-scheme
version in the document; a jsonschema cross-check in CI; moving the frozen
copy under `tests/gates`.

Evidence status: prepared on a work machine where no pytest or checkwash
ran; CI ran the tests.

The agent wrote this entry in #364's PR #507. The maintainer approved it
on 2026-10-19: 「裁決總表全部照建議」 ("the whole ruling table as
recommended"), in reply to the agent's table of 104 decisions. For this
PR: R59 approved the `docs/stability.md` text (the fingerprint row, the
`config_errors` row, the paragraph on unknown keys, the do-not-bump list
and the "Fingerprint stability" subsection); R61 kept the schema, with
#507 as the answer to #364; R62 approved this entry with its correction to
D-148; R63 left shipping the schema as package data, a jsonschema
cross-check and moving the frozen copy undecided. The reply is the text of
an answer the agent wrote, which the owner chose.

## D-158 (2026-10-19): at the root, a `--task` path the base tree holds only by another name is an engine error, and `doctor` looks up the root on its own timeout (#500)

Ruling 500 (owner, 2026-10-18, 「19 項全部照建議做（價值判斷的題也照你的傾向）」,
"all as recommended, value judgements included"). #500 was filed on that
go-ahead, which adopted the direction the agent's list gave for it: an
engine error when the base path holds a non-directory, one stderr line
whenever the fallback is used, the case-mismatched path handled too,
`doctor` on its own 5-second timeout, a test to confirm whether
KNOWN-ISSUES row 21 overstates, and P3. The details under the issue's
"Direction" are the agent's recommendation within that direction, for
review in this PR. D-151 to D-163 were assigned to pull requests
prepared in parallel. When integration batch 2 merged, all of them were
on main except D-153, which is unused, and D-154, which is pending in
#511. This entry is D-158.

#500 reports, from reading the code at `6d78d8dd`, that at the root
`check --task` reads the contract from the base tree at
`os.path.relpath(--task, --repo)`, and on a miss opens `--task` from the
working tree with no word, although the code comment and SPEC §4c said
the working-tree copy was a fallback only for an untracked file; nothing
checked that. Git reads no path through a tree entry of mode 120000 and
matches names byte for byte, so a task path through a committed directory
symlink, or spelled in another case on a case-insensitive checkout, misses
the base copy, and the operating system opens the head's. The change
cannot cause the miss, which depends only on the operator's arguments and
the base tree, but once a configuration misses, every change supplies its
own `oracle_freeze` and scope globs (E2, E7). Separately, `doctor` found
the repository root with the general 60-second Git timeout, two queries
from a subdirectory, while its own queries use 5 seconds.

Implementation (lines at this PR):

- A, the root fallback. `GitSnapshot.alias` (`gitio/snapshot.py:447-478`)
  returns a `TreeAlias` (`:39-50`): the first entry of the base tree, by
  the shortest prefix, that equals a proper prefix of the mapped path when
  case is ignored and is a file, a symlink or a submodule; or else an
  entry that equals the mapped path itself only when case is ignored.
  Both comparisons are on text (`str.casefold`), so the answer is the same
  on every file system. `base_alias` (`gitio/git.py:181-187`) wraps it as
  the other base reads are wrapped. In `_analyse` (`cli.py:253-272`), a
  base miss at the root with such an entry is an engine error naming it
  (`_task_alias_error`, `cli.py:167-174`): exit 2, or the non-blocking
  hook-json message (#414), as a base miss from a subdirectory already is.
  Otherwise the fallback reads the working-tree copy, then writes one
  stderr line through `_advise` (`cli.py:269-272`), which reaches neither
  stdout nor the exit code. The comment above the task read (`:219-224`)
  is corrected. The subdirectory branch is unchanged.
- B, `doctor`. `_run` (`gitio/git.py:28-45`) and `resolve_repository_root`
  (`:61-110`) take `timeout` and `stdin` keywords whose defaults, 60
  seconds and inherited stdin, keep `check`, `sweep`, `allow`, `quality`
  and the SessionStart hook as they were. `_reroot` (`cli.py:767-781`)
  passes them through, and `doctor` passes `QUERY_TIMEOUT`
  (`doctor.py:206`, now also `_git_query`'s, `:244`) and stdin from
  DEVNULL (`cli.py:897-908`). Doctor's other Git flags are not added. No
  SPEC change: §9 promises `doctor` the same sanitized environment, not a
  timeout.
- KNOWN-ISSUES row 21 (Direction 2). By reading, `--repo` reached through
  a symlink to the root fails closed on its own: the mapped path is either
  the right root-relative path or starts with `../`, which Git refuses
  from the root as outside the repository (`git cat-file` exits non-zero,
  and the strict snapshot's error is an engine error). A new test pins
  both ways, and the row now says the route fails closed and names the
  case route; that correction holds only if CI confirms the test.
- Priority: P3 for both parts.

Readings within the ruling's text; the owner accepted 1, 2 and 4 to 6,
and kept 3 a residual (below):

1. A submodule at a proper prefix, compared with case ignored, is refused
   too. The ruling names "a symlink or a file"; a submodule is neither,
   nor a directory of this tree. The same prefix spelled exactly is
   already refused (`opaque_error`, `gitio/snapshot.py:417-419`), and in
   another case a case-insensitive checkout would open the submodule's
   working tree.
2. "Case ignored" is `str.casefold`, Unicode's full case folding. It is
   no file system's own case table, so it can differ either way: it joins
   some names file systems keep apart (`ß` and `ss`, for example), and it
   can miss names a file system joins. U+0131 `ı` has no case folding,
   while its uppercase is `I`; NTFS compares names through an uppercase
   table, inferred, not verified, to map `ı` to `I`. If so, `--task
   cı/TASK.md` for a committed `ci/TASK.md` gives no alias there, and the
   fallback reads the head's copy.
3. An entry equal to the mapped path byte for byte is no alias: that is
   what the base read answers. The only such entry the read misses is a
   submodule named exactly. Its fallback opens whatever the working tree
   holds at that path: an engine error (`OSError`) when a directory is
   checked out there, the submodule's own or the empty one Git leaves for
   it, but the head's contract when the head replaced the submodule with
   a regular file. No working configuration names a submodule as
   `--task`, so this is left as a residual; refusing it would be stricter
   than the ruling's text.
4. The stderr line is written after the working-tree copy is read, so an
   `OSError` from the open gives only the engine error. The session's
   second leg (#418) stays quiet, as for its other diagnostics; it reads
   policy from the same commit as the first leg.
5. The check runs wherever the root fallback ran: a range, the worktree
   and the managed Stop hook, against the commit policy is read from.
6. With several entries equal when case is ignored, the error names the
   first in sorted order.

Not settled by the ruling, and left as residuals (KNOWN-ISSUES-next):
other spellings a file system treats as the same file are not compared,
by reading: Unicode normalization (NFC against NFD on macOS), names a
file system's own case table joins and `str.casefold` keeps apart (`ı`
against `I`, inferred, reading 2) and, on Windows, trailing dots or
spaces, 8.3 short names and alternate data streams. A task path that
names a base submodule exactly still reaches the fallback (reading 3).
A task file the base does not hold at all is still read from the
working tree, with the new stderr line, so a CI step that names a task
file the base never had still lets each change supply its own contract.
Dropping the root fallback altogether was not proposed: it would revisit
D-139 and break a generated or untracked task file at the root.

Beyond the ruling's text, these effects are accepted with this entry:

- A run at the root that named the task file through a committed
  directory symlink, a committed file on the way, or in another case, and
  read the working-tree copy, now exits 2 (or gives the hook-json
  message). On a case-sensitive checkout so does an untracked `task.md`
  beside a committed `TASK.md`, the cost of a result that does not depend
  on the file system.
- On the fallback path, one more `git rev-parse` and `git ls-tree -r` run
  for the alias check, beside the inventory the base read already lists
  (`gitio/snapshot.py:423`).
- `doctor`'s root lookup gives up after 5 seconds per query. A timeout of
  the first query is a plain `GitError`, so the fallback to `--repo` as
  given is silent (SPEC §9); only a timeout of the second query prints
  the stderr line. From a subdirectory a silent fallback reports on the
  subdirectory, which needs a file system on which a 5-second
  `rev-parse` times out, where doctor's other queries would time out
  already.

This narrows D-139's root fallback (`DECISIONS-archive-1.md:10649-10651`) to a task
file the base tree lacks, with the two engine-error cases and the stderr
line; SPEC §4c changes with it. The exit codes keep their meaning (2 is
an engine error, and hook-json reports it as #414 does), so
`docs/stability.md` does not change. No fingerprint, IR field or key
changes. The sweep passes an empty `Contract()` (`sweep.py:132`), so it is
not expected to move. THREATMODEL row 18 ("Closed — contract read
base-side") is unchanged; the owner kept it so, with the residuals left
here and in KNOWN-ISSUES-next (below).

Rule 2. The ruling approves no change to an existing expectation: by
reading none moves, and none was changed. Every existing `--task` run at
the root names a task file the base holds as a regular file
(`tests/test_issue416_subdirectory_root.py:466-488`,
`tests/e2e/test_allowlist_scope.py:110-138`, and the nine verdict-gate
cases with `task = "TASK.md"`, each with a base `TASK.md`), so none
reaches the alias check or the new stderr line. The subdirectory tests
keep their message (`tests/test_issue416_subdirectory_root.py:491-527`).
The resolver tests replace `subprocess.run` with functions that take any
keyword (`:156-194`, `:393-461`), and `tests/test_perf_git.py:155`
replaces `gitio._run` only around `list_range_changes`, which passes no
keyword. Nothing under `tests/gates` changed. If CI shows an existing
expectation moving, the round stops.

Evidence status: prepared on a work machine where no pytest, checkwash or
Python ran; CI runs the tests. Added: 22 collected items in
`tests/test_issue500_root_task_path.py`, none under `tests/gates`: a
committed directory symlink on the task path and a task path in another
case, each exit 2 and hook-json (4); the fallback's stderr line in a
range, the worktree and hook-json (3); the `--repo` route both ways (3);
doctor's and check's lookup keywords (1); and eleven unit cases of
`GitSnapshot.alias` on owned Git objects. Not pinned: the session's second
leg, an `OSError` on the open, the residuals above, and a hanging Git. By
reading, the documented test count becomes 19505 (19483 + 22); CI's
collection checks it.
`NOT_RUN：工作機規則（POLICY work-machine-local），every behaviour above is read from source and from Git's; no test, checkwash run or sweep was run`.

The agent wrote this entry in #500's fix PR #517. On 2026-10-19 the
maintainer replied 「PR 核可清單全部照建議」, "the whole PR approval list
as recommended", to the agent's approval list, whose recommended answers
for this PR were: the SPEC §4c (bd2043cf) and D-158 (02b47bf5, ecebc2b1)
wording as committed (A35); readings 1, 2 and 4 to 6 accepted (A36);
reading 3, a task path that names a base submodule exactly, kept a
residual in KNOWN-ISSUES-next rather than refused (A37); THREATMODEL row
18 unchanged, with the residual left in KNOWN-ISSUES-next and this entry
(A38); and both departures accepted, the KNOWN-ISSUES-next #500 row
(c3ecd099, c85a55f6) and the CLI symlink test's base `ci` entry written
as a mode-120000 blob through `update-index` (A39). None of them covers
what the agent wrote afterwards, in 0d8b4e5d: this closing paragraph,
and the two sentences above that had left a point to the owner, the
readings heading and the THREATMODEL row 18 sentence, which now say what
the owner decided. The maintainer approved that text later on 2026-10-19
with 「第二輪核可全部照建議」, "the round-2 approval list, all as
recommended", whose item B3 approves together the sentences that write
an already approved option into the documents or turn a point left to
the owner into a decided one, this entry's approval record and those two
sentences among them. Each reply was a button whose text the agent
wrote, which the owner chose. Neither list covers 2a0de639, which
corrects the KNOWN-ISSUES-next #500 row's `doctor` sentence to "5
seconds per query (about 10 seconds from a subdirectory)", as this entry
says "per query".

## D-160 (2026-10-19): a test runner's expected-failure record is a documented limit, and its detector is not scheduled (#468)

*A recorded limit and a refusal; no code, rule, fixture or frozen text changes.*

Ruling 468 came in two steps. On 2026-10-16 (issuecomment-6230171551,
「#468、#471 都照建議」, "both as recommended") the owner adopted the
analysis in issuecomment-6229288226: (c) now, then (b), not (a); undici's
format only; (c) in the next release, (b) after a ruling on the size limit
and a pool sweep; "This issue stays open for (b)." On 2026-10-19
(「裁決總表全部照建議」, "the consolidated ruling list, all as recommended";
the reply was a button whose text the agent wrote), R57, R58 and R64
completed (c), replaced that last sentence and narrowed that ruling's
item 2 (item 3 below). D-151 to D-163 were assigned to
pull requests prepared in parallel. When integration batch 2 merged, all
of them were on main except D-153, which is unused, and D-154, which is
pending in #511. This entry is D-160.

#468 reports that undici's `test/web-platform-tests/expectation.json`,
the record its Web Platform Tests runner reads, can mark a regressed
subtest `success: false` or `flaky: true`, or its test file `skip: true`,
and no rule reads it. The v0.8.0 acceptance sweep's JavaScript batch set
the file aside unread in 10 undici commits (on LAPTOP-01AGNPJU, under
POLICY `checkwash-pju-sweep`, T-546). It is not a v0.8.0 regression.

Decided:

1. (c), a known limit (468.Q1). No rule reads a test runner's
   expected-failure record. Under 1,000,000 bytes undici's file has the
   `test` role (#217, SPEC §2), not an opaque production change, and earns
   no repair evidence; over that size it is set aside unread (#415).
   Either way the change passes with zero findings. The limit is written
   in THREATMODEL row 156 (Open, by ruling), in `docs/assertion-coverage.md`
   ("Expected-failure records a test runner reads", since #475) and in
   `docs/KNOWN-ISSUES-next.md`, marked Existing, from where it moves to the
   next release's known-issues page.
2. Not (a), a default role. The `snapshot` role, or a new must-read role,
   would turn the 10 sweep passes back into v0.7.0's exit 2 (D-135 ruling
   1), report about 9 of the 10 commits at warn without telling them
   apart, and inherit row 132: any JS production edit silences the
   file-backed rule.
3. Scope: undici's format only, recognised by path and shape (468.Q2).
   The 2026-10-16 ruling gave each other expected-failure format its own
   issue when the corpus shows one. The analysis adopted through R58 and
   R64 narrowed that: another runner's format gets its own issue when a
   fix for it is planned; with no fix scheduled, it is added to row 156
   instead.
4. (b) is not scheduled (R64). (b) is a detector that compares entries
   by identity and reports a subtest recorded as passing that no longer
   is, or a file newly marked `skip` or `flaky`. Building it would need,
   first, a ruling that lets this format be read past 1,000,000 bytes,
   with the limit to use (D-135 ruling 1 refuses a file a detector must
   parse), then a new rule ID in the frozen §4 list, its fingerprint (§6),
   and a pool sweep of its cost, including parse time on 2 MB sides.
   #468 is reopened when any of these happens: a cheat in this file is
   reported; undici fixes its runner's comparison, so that the file gates
   CI; or the size limit is ruled on for another reason. Another format
   does not reopen #468 (item 3).

Why (b) is not scheduled, by reading:

- undici's runner fails no run on a changed result. It diffs the record
  against the observed results with jsondiffpatch and
  `propertyFilter: (name) => name === 'success'`, and sets
  `process.exitCode` to 1 only for a non-empty diff
  (`test/web-platform-tests/wpt-runner.mjs:818-825` at `5550222761`, the
  same at undici's main `e8f34234d1`). jsondiffpatch's `objectsDiffFilter`
  (`src/filters/nested.ts`; undici pins `^0.7.3`) applies the filter to
  every key at every depth, so the top-level directory keys are dropped
  too and the diff is always empty. The edit hides a regression from the
  record instead of turning a red run green; `skip` still stops a file
  from running. The analysis had listed this as undetermined.
- (b) would report at warn, and in the cheat shape a JS production edit
  is present, so warn is its ceiling (rows 2 and 131). At the default
  `fail_on = "high"` it changes no verdict.
- No commit is known to be a cheat. By reading, 8 of the 10 are honest,
  `8453a773ae` is not decidable and `5550222761` is undetermined.
- The size ruling (b) waited for is not being asked: #415 is closed.

The 2026-10-16 ruling's item 3 named only `docs/assertion-coverage.md`
and the known-issues page for (c). The adopted analysis also named the
THREATMODEL row and this entry, so they are not a new decision (R58). As
D-050 shows, an entry may record a refusal that changes no behaviour.

Corrected in `docs/assertion-coverage.md`: it said the runner "compares
each subtest with its recorded `success`" and that the edit "makes a
failing run pass". By the reading above that overstated it. The section
now says the runner is written to compare, that it fails no run today,
and that a fixed comparison would let the edit turn a failing run into a
passing one. Its detector paragraph said the detector "is planned"; it
now says it is not scheduled.

Cost: the gap stays. If undici fixes its runner, the cheat costs nothing:
undici's `CONTRIBUTING.md:110` asks contributors to mark new failures in
the file, and the runner rewrites it from a local run. Only the
documentation points reviewers at the file, and a reopen depends on
someone noticing one of the conditions. How many other expected-failure
records the corpus holds is unknown, because the sweep sees such a file
only when it is over 1 MB.

Rule 2: no existing expectation changes, and no code, fixture or test
changes. `tests/test_threatmodel_pinned.py` checks only Closed rows, and
`tests/gates/test_tamper_corpus.py` and `tests/gates/test_recorded_arms.py`
read only the rows they name. `benchmarks/FAILURES.md` gains row 156 (175
bypasses, 59 not closed), updated by hand to its generator's output.

Evidence status: prepared on a work machine where no pytest, checkwash or
Python ran; CI runs the tests. The undici and jsondiffpatch readings come
from source read for the 2026-10-18 analysis.
`NOT_RUN：工作機規則（POLICY work-machine-local），read-only inference; nothing was run`.

The agent wrote this entry in #468's docs PR #521. The maintainer approved
its text as it stood at 97f6816a on 2026-10-19: 「PR 核可清單全部照建議」 ("the PR
approval list, all as recommended"), in reply to the agent's list asking
for approval of this PR's SPEC §4 `SUPPRESSION_ADDED` row (b5aac2c6,
c1a68fa9), THREATMODEL row 156 (f9c6dace, 629baffe) and D-160 (276c44ec,
97f6816a) text, with the hand edit of `benchmarks/FAILURES.md` (A21), and
of its departures from the rulings (A22): this entry's record that R58 and
R64 narrowed the 2026-10-16 ruling's item 2, the quote case in the #421
row, the #497 spellings in their own sentence, the #480 wording that
differs from the 2026-10-18 draft, and the introduction of
`docs/KNOWN-ISSUES-next.md` defining *Existing* rows. The same reply chose
to correct the v0.8.0 known-issues page's sentence that listed #423, #425,
#426 and #433 as open (A23), to name #278's gap on that page (A24), and to
shorten the #468 row's source in `docs/KNOWN-ISSUES-next.md` to "the
v0.8.0 acceptance sweep (D-140)" while this entry keeps the host and
policy (A25). Those three edits (ab989698, 38613ccc, eb3d9dcf) and the
first version of this paragraph (216c4dfe) were written after the reply,
so their wording is the agent's. Later the same day the maintainer
approved them as written: 「第二輪核可全部照建議」 ("the round-2 approval list, all as
recommended"), in reply to the agent's round-2 list, which asked whether
to approve together the text written to apply options already approved,
this paragraph and those three edits among it (B3); whether the first
header sentence of `docs/KNOWN-ISSUES-next.md`, which said every residual
below was found by reading, should also yield to a row, with #510 and #521
using one wording (B4); and whether to correct, as under A23, the v0.8.0
page's sentence that still listed #417, #420, #436 and #437 as open (B5).
Under B4 this branch keeps the wording it already had, "unless a row names
another source" (775aa3dd, A22), which #510 now uses too (7dc0cd20). Under
B5, 42410c38 says that #417, #420 and #437 are deferred until after 1.0
(#504) and that #436 was closed as completed. f3dd7110 brings this entry's
numbering sentence up to date with main, which the pull request's claims
review found stale. Those two edits and this paragraph as it now reads
were written after the second reply. Both replies were buttons whose text
the agent wrote, which the owner chose.

## D-162 (2026-10-19): the verdict gate's baseline rotates to v0.8.0

Owner ruling 2026-10-19, R56. The owner answered a table of 104 rulings
with 「裁決總表全部照建議」 ("the whole ruling table as recommended"); the
reply is the text of an answer the agent suggested, which the owner chose.
R56 asked whether to open the v0.8.0 rotation PR now, with the
protected-file dispositions asked in the PR, and adopted "open it now and
merge it before the sweep freeze". This PR rests on R56. The v0.8.0
one-time authorization (`docs/RELEASING.md`, 2026-10-15) listed "the
verdict-baseline rotation PR (step 9), whose protected changes keep the
maintainer's disposition" among what it covers, but its publication record
says the grant "was consumed by publication" and that the rotation remains
separate, so this entry does not rely on it. R56's recommendation also
cited that grant as a reason; since the grant is consumed, the PR rests on
the option R56 adopted and on approval items A31 to A34 (below). The PR is
part of the v0.9.0 release preparation and has no issue: a tag-push run
requires `[baseline]` to be the highest other `v*` tag merged into the
tagged commit (`check_tag_rule`, `tools/verdict_gate.py:1564-1594`), which
for a v0.9.0 tag is v0.8.0.
D-151 to D-163 were assigned to pull requests prepared in parallel. When
integration batch 2 merged, all of them were on main except D-153, which
is unused, and D-154, which is pending in #511. This entry is D-162.

After the rotation, pull requests, `main` and the next tag are compared
with v0.8.0 instead of v0.7.0.

- **`[baseline]`** in `tests/verdict_gate/baseline.toml` pins tag v0.8.0,
  version 0.8.0, release commit
  `f02b5d8a07fa39ee1898881f66c571eb164cb11c` (the merge commit of #458,
  tag object `1d869062`) and the Release's `checkwash.pyz`: 796,565 bytes,
  sha256 `87b097cdca4ca34dc43be8be8ddf8ef7f3197894dc6f554fe1bddc1d86e74d0c`,
  as the GitHub Releases API reports the asset and as the
  [publication record](docs/releases/v0.8.0-publication-verification.md)
  lists it. The gate re-checks both on every run, and checks that the
  archive's `checkwash/*` members equal `src/checkwash` at `f02b5d8`.
- **`baseline_blocked`** stays 159, sha256 `9993cab6…`. The tag-push
  verdict run of v0.8.0,
  [38768985301/attempt 1](https://github.com/taipei49314/checkwash/actions/runs/38768985301)
  (job 116539533210, v0.7.0 against the tag), logs 185 cases (159 T1,
  26 T3), zero failures and zero reported, with 159 block -> block and
  26 pass -> pass. Zero failures means v0.7.0's blocks matched this pin.
  With no block -> pass and no pass -> block, the candidate there, built
  from the tag's own source, blocks exactly the same 159 cases; the
  Release's pyz must hold that same `src/checkwash`. The run proposed
  nothing: the gate proposes an entry or a pin only where one is missing
  or has drifted, and that is a failure too (`tools/verdict_gate.py:123-135`).
  The rotation run (below), with v0.8.0 itself as the baseline, observed
  the same pin and reported no `baseline-blocked-drift`.
- **`[t3.cases]`** is unchanged. `tests/data/javascript_chai_mutations.json`
  is the same git blob (`4f363109`) at v0.5.0, v0.6.0, v0.7.0 and v0.8.0,
  so the T3 cases read at `f02b5d8` are those read at `d647a65`, which the
  tag-push run matched with no drift. The rotation run, reading them at
  `f02b5d8`, reported no `t3-drift`.
- **`[canary]`** is not rotated (step 9). The v0.4.2 -> v0.5.0 pair and its
  71-case `block_to_pass` set stay; the tag-push run reproduced them
  (canary 71 block -> pass, 45 block -> block, 6 pass -> block and
  37 pass -> pass).
- **The acceptance file**, `tests/gates/verdict_gate_accepted.toml`, is
  maintainer-only. Its file-level `baseline` becomes `v0.8.0`: the gate
  fails `acceptance-baseline` while it differs from the pin
  (`tools/verdict_gate.py:1414-1416`). The owner authorized the agent to
  change exactly that line and add a dated header comment (below), and
  nothing else in the file changes. It holds no `[[accept]]` entry, so
  the rotation removes and adds none, and no case needs one (below).

Nothing else moves. The case files, labels, acceptance file, gate code
(`tools/verdict_gate.py`, `tools/qualify_assertions.py`) and workflow are
the same at `main` `0e60832a` as at `f02b5d8`. The main-push verdict run
[39206619788/attempt 1](https://github.com/taipei49314/checkwash/actions/runs/39206619788)
on `0e60832a` (v0.7.0 against `main`) logs the same counts, with zero
failures and zero reported. So `main` judges every case as v0.8.0 does,
and the rotation run below, whose candidate is `main` with this PR's
engine-neutral changes, observes it directly: against v0.8.0 it has no
block -> pass, needs no entry and reports nothing. From this rotation on, a candidate that turns any of
v0.8.0's 159 blocks into a pass needs an accepted entry. No engine code,
case input, label, fixture expectation or gate rule changes;
`tests/verdict_gate/README.md` records the re-pin.

The rotation run is the rotation PR's (#516) first verdict run,
[39214083418/attempt 1](https://github.com/taipei49314/checkwash/actions/runs/39214083418)
(job 117933789875), on pin head `5490b4e86572dffe347d13ac890e70d69f398316`
with merge checkout `5c7a93fe` (that head merged into `0e60832a`). It ran
with the rotated `[baseline]`, checked out `f02b5d8` and the Release's pyz,
and passed the engine identity check: a sha256, size, member, commit or
version mismatch is an `engine-identity` failure and stops every case, and
none was reported. All 185 cases ran (159 T1, 26 T3): 159 block -> block,
26 pass -> pass, zero reported, and the canary at 71 block -> pass,
45 block -> block, 6 pass -> block and 37 pass -> pass. Its one failure is
`acceptance-baseline` ("acceptance file baseline 'v0.7.0' differs from the
pinned baseline 'v0.8.0'"). With no blocked-pin, T3 or entry failure, it
proposed no pin and no entry, so `[baseline_blocked]` and `[t3.cases]`
stay as first committed (`3871d5ac`). This failed run is not the merge
evidence: the PR's final head, with the acceptance line changed, still
needs a successful verdict run and the normal required checks before
merge.

Evidence status. The three runs above are read from their logs
(`gh run view --log`). Their receipt artifacts, each named
`verdict-gate-receipt-1`, were downloaded on 2026-10-19 before they
expired, as the owner approved (below), and each ZIP's SHA256 equals the
one its upload step logs. Artifact 11991306312 (run 38768985301) is a
20815-byte ZIP with SHA256
`e5683c9cd7962de4e459c0bb719b43cc863e8d945b4b8eea58fabda12098bd84`
holding `verdict-gate.json` (SHA256
`dd5170b15eec7d4a7f15e3bea4a444ae94f2ea9956c4b249988c50c99f37b90b`) and
`verdict-gate.md` (SHA256
`ef35af3b9e1a4beabf999ea3fa6dfe20e05f029a40f85f3b65684a2b5a01e206`);
artifact 12165673670 (run 39206619788) is a 20781-byte ZIP with SHA256
`0f7b1e929d583fb3c56d892b0ae3ec8edfb42d1d949286aec6c689a506ac87e7`
holding them with SHA256s
`fa25501ef1a46392e36e84b03d86795de6358791c123fba1d4c11a9f23315739` and
`a7b5aaed66bcdb0f75ba092fb2d2fbcded440c06dabd448fe92a4160b016289d`; and
artifact 12169571379 (run 39214083418) is a 21003-byte ZIP with SHA256
`d8e44ab6defeaef452b130c34a21910ac46d87d5f50a8aa1cc766fce979a2139`
holding them with SHA256s
`df9fdf1e92a4d4c3c4b777e7b40d09b63baa977953af24d56c142f510450fc53` and
`69c5564e992452e68b51c08f154dd8f6af13b2e827bb61a8e343e1b4f2cadb9f`.
The work machine only downloaded and hashed them; no verdict run or test
ran there
(`NOT_RUN：工作機規則（POLICY work-machine-local），the verdict runs above are hosted CI runs`).

The agent drafted this entry in the rotation PR #516. The maintainer
approved it on 2026-10-19: 「PR 核可清單全部照建議」 ("the whole PR approval
list as recommended"), in reply to the agent's list of approval items for
the open pull requests, which takes every item's recommended answer. For
this PR those are: A31, on who changes the protected file's `baseline`
line, 「准 agent 改這一行，並加 PR 本文的日期註解」 ("the agent may change
this line and add the dated comment from the PR body"), so the agent
changed exactly `baseline = "v0.7.0"` to `baseline = "v0.8.0"` in
`tests/gates/verdict_gate_accepted.toml` and added the header comment the
PR body proposed, and nothing else (f9bf2a2c); A32, this entry's wording
as committed in 308dc412, 5490b4e8 (it rests on R56) and bf655e2d (it
records the observed rotation run); A33, fetching the three receipt
artifacts before they expire and recording their SHA256s here in one
sentence, with no further approval (the sentence that gives each
artifact's size and SHA256s, 0faaea28); and A34, keeping
`[baseline_blocked]` at 159 and `[t3.cases]` as carried over, since the
tag-push run had no failure and its proposal is empty and the rotation run
observed no drift, while the final head still needs a successful verdict
run before merge. The reply is the text of a button the agent wrote, which
the owner chose; the agent also wrote the list and each item's options,
including A31's.

Some of this entry was written after that approval, and none of A31 to
A34 names it: in 0faaea28, besides the SHA256 sentence, the
evidence-status sentence saying the receipts were downloaded on
2026-10-19 and that each ZIP's SHA256 equals the one its upload step logs
(it replaced "were not downloaded, and they are kept for seven days") and
the sentence that the work machine only downloaded and hashed them (it
replaced "Nothing ran on the work machine"); in 36919754, the
acceptance-file bullet's "becomes" (it was "must become") and its sentence
that the owner authorized the agent to change exactly that line, which
replaced "the agent's commits do not touch it" and "The owner's
disposition of this line is asked in the PR", and the approval paragraph
above. The maintainer approved these on 2026-10-19 with 「第二輪核可全部照建議」
("the round-2 approval list, all as recommended"), item B3, option A,
「一併核可」 ("approve them together"): the sentences that write an
already approved option into the documents, or turn a pending owner
decision into a decided one, are approved together rather than one by
one, and for this PR the approval record names the sentences D-162 gained
after the approval. That reply, too, is the text of a button the agent
wrote, which the owner chose; the agent also wrote the round-2 list and
B3's options. The commit that adds this paragraph also adds, from a
read-only claims review, the note that D-153 is unused and the sentence
on R56's cited reason in the first paragraph, and narrows A33's commit
reference above to its sentence; these correct facts and change no
decision, and no approval item names them.

## D-152 (2026-10-19): a JS/TS `.each`/`.for` table is one test unit whose rows are read (#428)

Ruling 428 (owner, 2026-10-14, 「P1 全部照建議」, "all P1 as recommended";
#428 issuecomment-6170355202, stating each decision in full): Q1 (a),
Q1b (iii), Q1c (i), Q2a (a), Q2b (a) in this round, Q2c (b), Q2d (a),
Q3 (a), Q4 (a). D-151 to D-163 were assigned to pull requests prepared in
parallel. When integration batch 2 merged, all of them were on main
except D-153, which is unused, and D-154, which is pending in #511. This
entry is D-152.

#428 reports that the JS/TS frontend marked every `test.each`, `it.each`
and `test.for` declaration as a table and kept it out of the unit scan
(`frontend.py:1321` and `:2131` at 30cfb8bd, `not d.table`). No unit-based
detector compared a table on either side, so a weakened or deleted
assertion in one, an edited or deleted row, `.skip.each` and a deleted
table all passed with zero findings, in v0.7.0 and v0.8.0 alike; the
unread `expect` calls were only coverage notices.

Implementation, lines at this PR:

- Q1 (a), `frontends/javascript/frontend.py`. A `test`/`it` table, in the
  call and the tagged-template form, with chained modifiers, is one unit
  (`parse_javascript`, `:2774`), named by its title as written (the
  literal's text, `add(%i, %i) = %i`), its callback scanned as a test's.
  `_declaration` keeps what the table passes (`_Declaration.rows` and
  `.passes_row`, `:1103`), and `_read_table` (`:2725`) turns its rows into
  `param_cases` and one `ParamTable` (`ir/model.py`) whose cells are
  canonical (`_table_cell`, `:2338`).
- Q1b (iii). `_table_rows` (`:2607`) counts the rows of an inline array
  literal with no spread or hole, of a tagged template whose cells divide
  by its headings (`_template_rows`, `:2460`), and of a same-file `const`
  one hop away (`_const_rows`, `:2558`, reading the mentions and template
  words `_ConstReads` indexes once per file). Any other table sets the new
  optional `UnitSide.param_rows_unknown` (`ir/model.py:229`), which only
  this frontend sets; `param_cases` is then None and `param_rows` empty.
- Q2a (a), `ir/diffalign.py:303-317`, the count rule. Between two tables
  it stays silent when either side is unknown. A plain test (no count, not
  unknown) paired with an unknown table, or with a table of no rows, is
  one item lost. The second arm is gated on the file not being Python: a
  Python test with no count can still be parametrized by a hook, which is
  why Python's own rule needs its two-sided proof
  (`frontends/python/empty_parameter_sets.py`). A table of N rows paired
  with a plain test is N - 1 lost, as in Python, and row identity
  (`_param_rows_lost`) reads JS tables unchanged.
- Q2b (a). Each table assertion records in `right_depends_on` the column
  ids its expected operand (`operand_source`) names directly, and in
  `left_names` those its subject names (`_columns_read`, `:2701`), so the
  language-neutral rules read the cells as they read a `parametrize`
  table's, with no detector change: EXPECTATION_DEFINITION_CHANGED's
  row-keyed comparison, SUBJECT_INPUT_CHANGED's literal-table arm (Q2d),
  EXPECTED_VALUE_DERIVED, ASSERT_SUBSTITUTED's reorientation check and
  TEST_PATCHES' name set. A plain JS assertion still records neither.
- `detectors/test_disabled.py:193-200`: the finding for a plain test
  wrapped in a table says `(1 -> 0)` or `(1 -> unknown)`, and its evidence
  `parametrize cases: unknown`, instead of printing None. Only that
  pairing reaches these lines with no count on the before side; the rule,
  its key and its other messages are unchanged. It is the round's one
  detector change, and Q2b says the language-neutral detectors run
  unchanged, so it was put to the owner, who kept it (below). Without it
  the message would read `(None -> 0)` for a table of no rows and
  `(None -> 1)` for an unknown one, whose evidence would be
  `parametrize cases: None`.
- Q1c (i), Q3 (a): alignment, D5 and `gating.py` are unchanged. Q2c (b):
  `describe.each` is a block, as before; its rows are not read.

Readings the ruling leaves to the implementation; the owner approved all
eight as written (below):

1. **Column ids.** `#0`, `#1`, ... by an array row's position; `#key` by
   an object row's key or a template's heading. A key or heading must be a
   name (quoted or not); otherwise the rows are counted and no columns are
   read. A name never starts with a digit, so the two spellings cannot
   meet, and no identifier holds a `#`.
2. **Which rows a runner spreads** (`_row_table`, `:2422`), as the Jest,
   Vitest and Bun documentation states it (not measured). When every row
   is an array literal, `.each` spreads it into the parameters: positional
   columns. Once some row is certainly no array (a number, string,
   Boolean, null, template or object literal), every row is passed whole:
   keyed columns when every row is an object literal with the same name
   keys, else one column `#0` holding each row. When every row may be an
   array (names, calls), or array rows differ in width, the rows are
   counted and no columns are read. So `[1, 2]` and `[[1], [2]]` are one
   table.
3. **Canonical cells.** A Number or a quoted string is its value as
   `right_value` records it (`5`, `5.0` and `0x5` are one cell, and so are
   `'a'` and `"a"`); anything else, `true`, `false` and `null` included,
   is its text with comments, wrapping parentheses and formatting taken
   out (`operand_text`, `comparable_operand`). D-060's arm reads a row
   only when every cell parses as a Python literal, so it skips a row that
   holds `true`, `null`, a template, a name or an object with an unquoted
   key, as the recommendation intends; an array of numbers or strings and
   an object whose keys are quoted (`{ "a" : 1 }`) parse as Python's and
   are read.
4. **The template heading** is Jest's reading: the static text before the
   first substitution, with its whitespace taken out, split at `|`. Vitest
   reads the template's first line, which is the same for a heading on its
   own line.
5. **The one-hop `const`** (`_const_rows`). "Bound once" is one `const`
   declaration of the name in the scope the table argument reads, whose
   initializer is the array literal (TypeScript's `as const` after it read
   through), in a statement that ends there, and not `export`ed. "Never
   reassigned or mutated, and used only as a table argument" is read as
   one rule: every other token that reads that binding must be the whole
   argument of a table call (`test`, `it` or `describe`). So a member
   (`CASES.push`, `CASES.length = 0`), a call argument, a spread, an
   object key and a TypeScript `typeof` all make the rows unknown, and so
   does any mention of the name inside a template literal, whose
   substitutions the token stream does not see. A destructured `const` is
   not followed, and of a `const` that declares several names only the
   first is (`const CASES = [[1, 2]], X = 1;` follows `CASES`; in
   `const X = 1, CASES = [[1, 2]];` the rows are unknown).
6. **Plain to unknown.** Q2a's "a plain test that pairs with a table of
   ... unknown rows" is read through the count rule, so Q1b's "stays
   silent when either side is unknown" is read for a pair of tables, as
   the recommendation's text has it. An unknown table that becomes a plain
   test, and a table of no rows that becomes one, lose nothing countable
   and stay silent.
7. **Q2b's "names directly".** A name in the expected operand or the
   subject counts only where it reads the callback's own parameter at the
   assertion: not a property, not a name that a nested block, a `var` or a
   function around the assertion binds again, and not a parameter a write
   may have reached (`Bindings._written`). Every name is resolved at the
   assertion's start, so a name that a function inside the operand binds
   (`toEqual(rows.map((sum) => sum))`) is read as the parameter it
   shadows. `.each` maps parameter i to array column i; `.for` passes the
   row whole, so its first parameter's array pattern takes the columns by
   position; an object pattern takes object and template columns by key
   (`({ expected: want })` reads `#expected`); a one-column table gives its
   cell to the first plain parameter. A member, an index and a local
   computed from a cell are not followed, and a table whose columns are
   unknown records none. The expected operand is the one `operand_source`
   records: the expected value or bound of an equality, ordering or
   closeness check, in Jest's, chai's and node's spellings, and a
   hand-rolled tolerance's centre. The argument of `toContain(c)`,
   `toMatch(re)` or chai's `include` and `match` records no column, so a
   cell rewritten under it passes (row 157, residual 5). A parameter list
   or `.for` array pattern whose commas a type argument holds
   (`m: Map<string, number>`) gives no column at all (`_splits_cleanly`,
   `:1439`): split at those commas, it put later parameters on other
   columns, so a rewritten expected cell read as a shared producer and
   went unreported.
8. **The test context.** A table callback's first parameter is its row,
   so `t.skip()` on it is no imperative skip. `.for` passes the context
   second, and `.each` none (`_callback_receivers`, `:1400`).

**Sequencing with #293 (Q2b).** The ruling allows either order: land
#428 after #293, or record on #293 that #428 is its tables round. The
second is done: the owner's consolidated ruling of 2026-10-19 (R60, #293
issuecomment-6261346913) closed #293 as not planned, moved it to #504
until after 1.0, and noted on it that #428 is its table round. #293's
2026-10-08 ruling still applies when it is scheduled; its JS reading of a
binding or a module constant then has to leave a column id to this
reading.

**Q4.** The ruling, made when v0.7.0 was the latest release, orders a
docs-only PR first: a sentence in README "Know the limits", a row in
`docs/KNOWN-ISSUES-v0.7.0.md` that the owner approves in that PR, and a
rewording of `docs/stability.md:236-238`. No such PR was opened. v0.8.0,
released since, carries the row in `docs/KNOWN-ISSUES-v0.8.0.md` (from its
release preparation, `8a17a80e`). This PR adds the v0.7.0 row, at the end
of the table in `docs/KNOWN-ISSUES-v0.7.0.md`. It copies v0.8.0's row and
adds two sentences: the report came on 2026-10-14, after the release, so
the acceptance at the foot of that page does not cover it; and v0.8.0 has
the same gap.
The README sentence and the `docs/stability.md` rewording were not made
either; this PR makes both, worded for main after the fix and naming the
v0.8.0 gap. The owner chose to keep them and the row in this PR, with no
separate docs-only PR (below).

**Costs, by reading; the sweep counts them.** New blocks in a test-only
change: an expected cell corrected (as in Python); an input cell changed
under the same answer (SUBJECT_INPUT_CHANGED, Q2d); a row deleted or
deduplicated; an assertion weakened or deleted in a table; a whole table
deleted, unless D2 or D10 credits it; and what other rules now report on
table units (stand-ins, #363's catches, focus and skips,
EXPECTED_VALUE_DERIVED). JS pairs by span order (Q1c (i)), so these
transitions, which pass on main, read as tests rewritten or lost: a table
expanded into plain tests; `test.each` into `describe.each` around one
test (N rows read as N - 1 deleted, since the nested unit carries no
rows); a table rewritten as a loop in one test; a table moved to another
file while the file gains a plain test; a plain test renamed beside a new
table. Renaming only the parameter an expected value reads (`sum` to
`want`) is EXPECTED_VALUE_CHANGED, as renaming such a local is in a plain
JS test (#198); renaming every parameter, and the assertion with them, is
no finding (`js_table_parameters_renamed_neg`). A plain test honestly
wrapped in an imported or computed table blocks, as it already does on
main by reading the old unit as gone. Folding plain tests into a table
still blocks (`js_table_fold_altered_value_pos`, row 92).

Two kinds of block on main can turn into a pass. One is intended: a plain
test wrapped, its assertion text unchanged, in a table whose rows are
counted and not zero. The other is a cost, found in review: a plain test
deleted in a file that gains a counted table pairs with that table in span
order, so it is no longer read as gone, and the change passes when
nothing on the pair reports. That happens when the deleted test asserted
nothing, or asserted `toBeTruthy()` on a call whose literal argument the
table makes a column: ASSERT_SUBSTITUTED sees the same unrecorded
expectation on both sides, and SUBJECT_INPUT_CHANGED cannot resolve the
column to a literal, where the plain spelling of the same edit gives it
two literals and blocks. On main the table was no unit, so the deleted
test was TEST_DISABLED. A deleted plain test already pairs with a new
plain test this way on main; keeping span-order pairing (Q1c (i)) makes
tables partners too. Row 157 and `docs/KNOWN-ISSUES-next.md` state it; it
is not pinned. The owner accepted it as a disclosed cost, for the sweep
and R29's lists to count (below).

**Residuals** are listed in THREATMODEL row 157 and
`docs/KNOWN-ISSUES-next.md`. The two P2 follow-ups the ruling names, a JS
fold projection with kind-aware pairing (Q3 (b) with Q1c (ii)) and
`describe.each` rows (Q2c), are not filed as issues: R47 of the owner's
consolidated ruling of 2026-10-19 (#428 issuecomment-6261646666) records
them on #428 and in KNOWN-ISSUES instead (the `describe.each` rows also as
row 108's residual), and an issue opens when a fix is scheduled. That
replaces the ruling's "Deferred to a P2 follow-up issue" (Q2c) and
"becomes a P2 follow-up" (Q3). Two shapes the review found stay residuals,
with no issue, as the owner chose (below): the TypeScript
`test.each<Row>(...)` form, which is no unit (row 157, residual 10), and
the argument of `toContain` or `toMatch`, which records no column
(residual 5).

**D-073.** This supersedes, in D-073 reading 1, the clause that the unit
scan does not read a `.each` table: a `test`/`it` table is now a scanned
unit. D-073 itself, and what declares a test for E7, are unchanged.

Rule 2. The ruling approves no change to an existing expectation: by
reading none moves, and none was changed. The one fixture with a table,
`js_describe_restructure_neg`, uses `describe.each`, which stays a block,
and stays `[]`. The inline sources with a table hold as written:
`tests/test_js_focus_rules.py:176` (`plain` stays stopped; the focused
table is a unit now, and runs), `tests/test_js_liveness.py:47` and `:55`
(block tables, one unit), `:134` (`computes` is still stopped; the table
unit is another key), `tests/test_scope_table_role.py:58` (both sides are
one unit) and `:118` (`declares_tests` stays true); only the comment at
`tests/test_scope_table_role.py:55-57` changed. Python's `param_*` and
`expectation_parametrize_*` fixtures are untouched: the flag is never set
there and the zero-row arm is not Python's. `tests/test_duplicate_units.py`
pins the span-order pairing this round keeps. Nothing under `tests/gates`
holds a table. If CI shows an existing expectation moving, the round stops
and asks.

**Fingerprints and IR.** No fingerprint scheme changes. A table unit's
findings are keyed by its title template, so two tables with one title
share keys (row 157, residual 8). `--emit-ir` gains `param_rows_unknown`
on every unit side, false outside JS tables; IR_VERSION stays 2. JS table
units now carry `param_cases`, `param_rows`, and column ids in their
assertions' `right_depends_on` and `left_names`.

**Measurement.** Not measured yet. Under the owner's consolidated ruling
of 2026-10-19 (#419 issuecomment-6261642679), this fix merges before the
combined sweep's manifest is frozen and is measured in that one run (R1,
R2), where its merge gets its own before/after pair in the chain. The
issue-acceptance batches run on LAPTOP-01AGNPJU under EC POLICY
`checkwash-pju-sweep` (T-546) after R5's two approval steps, and the
v0.8.0-to-RC comparisons that gate the tag run on the EC pool (R3, R29).
What this round asks of that run, for the owner's approval with the
manifest: the standard set (1,800 commits) and D-088's sets (895 and 368)
identical across the pair, since `ir/diffalign.py`, `ir/model.py` and
`detectors/test_disabled.py` are language-neutral code; and a JS target
set, built as D-118 builds one, of the non-merge commits in the 13
in-sample JS histories whose test diff touches `.each`, `.for(` or a
tagged-template table, outside #212's selection. Acceptance: zero verdict
moves on format-only or rename-only table edits; every block-to-pass
listed, where the two kinds above are predicted and any other kind stops
the round to ask; every new block with its diff, labelled cheat or false
positive and counted by class; and the number of degraded JS files. Also
the verdict gate (T1 and T3), the perf gate, and Jest, Vitest and Bun run
on an empty table, recorded here. If transitions and mispairings dominate
the false positives, the round stops to ask whether to take Q1c (ii). The
v0.8.0-to-RC JS replay (#212) and R29's lists, which put every
block-to-pass before the owner, measure the cost before a release ships
it.
`NOT_RUN：工作機規則（POLICY work-machine-local），every effect above is read from source; no test, checkwash run, sweep or runner was run`.

Evidence status: prepared on a work machine where no pytest, checkwash or
product code ran; CI runs the tests. Added: fourteen `.gwcase` fixtures
(nine pinning row 157: `js_table_weakened_pos`,
`js_table_assertion_deleted_pos`, `js_table_deleted_pos`,
`js_table_row_deleted_pos`, `js_table_expected_cell_rewritten_pos`,
`js_table_input_cell_rewritten_pos`, `js_table_skip_added_pos`,
`js_test_wrapped_in_empty_table_pos` and
`js_test_wrapped_in_unknown_table_pos`; the fold cost
`js_table_fold_altered_value_pos`; the controls `js_table_row_added_neg`,
`js_table_reformatted_neg`, `js_table_keyed_rows_reordered_neg` and
`js_table_parameters_renamed_neg`), labels the owner approved, and 74
collected items in `tests/test_issue428_js_tables.py`, counted from its
parametrize lists. By reading, the documented test count becomes 19738
(19650 + 74 + 14); CI's collection checks it. A review of the branch
before the pull request opened found the new block-to-pass above; two
unread shapes row 157 now lists (a matcher that records no expected
operand, and the TypeScript `test.each<Row>(...)` form); a comma inside a
type argument that put parameters on the wrong columns (fixed by
`_splits_cleanly`, one item pins it); the file rescanned for every
bare-name table (fixed by `_ConstReads`, not pinned by a timing test); and
three readings that said more or less than the code does (3, 5 and 7,
corrected above). Each finding was checked against the code before use.

The agent wrote this entry in #428's fix PR #525. The owner approved it
on 2026-10-19: 「PR 核可清單全部照建議」, "the PR approval list, all as
recommended". The reply was a button whose text the assistant wrote. It
answers the agent's list of that day, which asked, for this PR, items A60
to A66, each with a recommended answer that the reply adopts: the wording
of the SPEC (3a306370, 47380c24), THREATMODEL (62ce4c85, 48f021a9, with
the hand edit of `benchmarks/FAILURES.md`) and D-152 (a1527e85, 9d1d2c0f)
commits, as committed (A60); the labels of the fourteen `.gwcase`
fixtures listed above (A61); the eight readings (A62); keeping the
`detectors/test_disabled.py` change, which touches only the message and
evidence text, as a departure from Q2b (A63); for Q4, keeping the README
sentence, the `docs/stability.md` rewording and the three
KNOWN-ISSUES-next rows in this PR (e9e1cfc4, 2a213371), approving them,
and adding the v0.7.0 row here as a copy of v0.8.0's (A64); accepting
the new block-to-pass as a disclosed cost, not pinned, for the sweep and
R29's lists to count (A65); and keeping the TypeScript
`test.each<Row>(...)` form and the `toContain`/`toMatch` argument as row
157's residuals 10 and 5, with no issue (A66). The v0.7.0 row
(da7f5d55) was written after the reply. Its copy of v0.8.0's row is what
A64 approved; its two added sentences, on the report's date and on
v0.8.0, were not in the list the owner answered.

## D-154 (2026-10-19): subject replacement shares the 200,000-node limit, and the stand-in limit refusals name what fired (#469)

Ruling 469 (owner, 2026-10-18, issuecomment-6248629427, 「19 項全部照建議做
（價值判斷的題也照你的傾向）」, "all as recommended, value judgements included")
answered item 4 of the agent's recommendation list and states each decision
with its reason in the issue. D-151 to D-153 were set aside for #507 and
for the fix pull requests of #428 and #454. D-151 is #507's entry and
D-152 is #428's; D-153 is unused, since #454's pull request, #509, writes
no entry. This entry is D-154.

#469 reports that after D-131 the v0.8.0 acceptance sweep still stopped 53
aiohttp commits with exit 2, at the subject-replacement pass's 30,000-node
limit or at the stand-in step limits, and that neither message named a
file. The ruling comment's corrections, counted from the recorded sweep
values, put 43 commits at the node limit and 17 at the step limit (14 of
#469's, aiohttp `0258e4de7d` and `129ef25e0f`, and scrapy `c44b8df6c7`);
#345's watch commit `5a8ebdfcae` stops at a nonregular source instead.

**Ruling.**
1. Q1 (a). `subject_replacements._parse` raises its node limit from 30,000
   to 200,000 by reading the stand-in pass's `_MAX_SOURCE_NODES`, so the two
   passes share one constant. Above it the run still exits 2, naming the
   file. Not (b): the pass feeds `TEST_PATCHES_SUBJECT`, an oracle rule, and
   D-135 ruling 1 keeps a file a detector must parse failing closed
   (`DECISIONS-archive-1.md:9884-9888`). Not (c): the 43 commits would stay at exit 2.
   Condition: the pass has no step budget, so its time at 200,000 nodes is
   measured on the fix in CI or the pool and recorded here (one run can also
   meet D-131 item 2); if it grows faster than linearly the agent reports it
   on the issue, and a work budget that fails closed needs its own ruling.
2. Q2 (c). Both step limits stay, 20,000 steps per proof and 1,000,000 for
   the analysis, and still exit 2. The refusal names which counter fired,
   the file, the side, the unit and the step count. Raising either limit or
   restructuring the conftest fan-out is a separate ruling, after an
   approved run (a checkwash-lab run with its frozen manifest and engine
   commit approved beforehand, or a pool run) records which counter fires,
   and at what count, on the 17 commits. This ruling approves no run.
3. Q3. The three refusals take D-131's `key=value` form, with the current
   text as the prefix, and a test pins each:
   - `subject replacement source exceeds the syntax node limit: path=...,
     requested_side=..., bytes=..., nodes=..., limit=...`;
   - `subject replacement source exceeds the byte limit: path=...,
     requested_side=..., bytes=..., limit=...`, which by reading `check`
     cannot reach (a changed `.py` side over 1,000,000 bytes refuses
     earlier), so its test calls `_parse` directly;
   - `stand-in execution proof exceeds the source step limit:
     counter=proof|analysis, path=..., requested_side=..., unit=...,
     steps=..., limit=...`, with the fired counter's steps and limit. A
     proof that belongs to no test (the module-body seed traces, the
     restructured-patch proof) names its kind as the unit. When the shared
     budget fires, the message says the unit is where it ran out, not
     necessarily its cause.
   The subject-replacement refusals fall under D-135 ruling 3 ("Every
   remaining size refusal names path, side, size and limit"); the step
   guard is not a size refusal, so naming it is new and is ruled here. The
   lab aggregator keys errors by the text before the first `:` or `(`, so
   old and new rows still match.

Implementation (lines at this PR):

- `subject_replacements.py:22` imports `_MAX_SOURCE_NODES` from
  `standin_installations.py:35`. `_parse` (`:37-66`) refuses over it with
  the node message and over `_MAX_BYTES` (`:34`, 1,000,000, this pass's own
  byte limit as before) with the byte message. Its `path` and `side`
  default to `'<unknown>'` for direct calls, as the stand-in pass's
  `_syntax` does. `_trees` (`:69-74`) parses both sides of a changed test
  for the pass, the base side first, and names a rename's base side by its
  old path, as `engine.py:1173` reads it.
- The module-read cache (the owner's choice, A83, below). `_ModuleReads`
  (`subject_replacements.py:172-231`) holds one tree's four module-level
  reads: the first function or class of each name in a body, which `_scope`
  (`:286-297`) looks up there instead of scanning the body; the star-import
  check; and `_binding_sites(tree.body)` and `_bindings(tree.body)`. Each is
  made at most once, when first asked. The pass makes one per side when it
  first needs a file's trees (`:672`) and passes it to `_subject_call`
  (`:677-678`), which asks it for all four (`:345-350`, `:379`, `:381`); a
  direct call without one reads the tree afresh. Every answer is the one
  the uncached read gives, and `_subject_call` only reads the kept sites and
  values, so no result changes. Under the owner's second choice (B13,
  below) `_assertion_scope`, `_scoped_bindings` and the literal-string
  helper check take the same object (`:673-674`, `:685-686`, `:695`), and
  it also keeps, each made once when first asked (`:233-283`), whether the
  module is inert, which nodes are its statements, one walk of the whole
  tree for the writes those checks refuse, and, per replacement, whether
  every other function of the module is a closed literal test of it.
  `_scoped_bindings` lays a test's names,
  and the stand-in checks their parameters, over the kept bindings in a
  `ChainMap` instead of copying them. Under the owner's third choice (C5,
  below) the pass also keeps, in two dicts per file (`:645-647`,
  `:656-657`, `:698-699`), the parts of `math_import_authority`
  (`literal_stdlib_standins.py:72-151`), each made once when first asked:
  the file's top-level imports, with which each target is compared; the
  answer of `pure_imported_calls` for each function an old callee's name
  imports, the only part of the old call it reads (the table it reads is
  `oracle_purity.py:263-276`); and the startup check, which reads neither.
  It also keeps the answer of the checks of `parameterized_abs_event`
  (`parameterized_subject_replacements.py:39-139`), of which only which
  call is a test's first depends on the test. As both read the repository
  only through the context, which keeps every source it reads, and the
  inventory, for a snapshot that does not change during the run each kept
  answer is the one a fresh check gives. Only the `math.gcd` helper's
  check of the module's other functions is still made once per pair
  (Residuals).
- `standin_installations.py:38` names the per-proof limit
  `_MAX_PROOF_STEPS`, the 20,000 `_step` compared inline. `_step`
  (`:434-438`) keeps its two comparisons; only a refusal calls
  `_step_refusal` (`:440-458`) to build the message. `_Trace` takes `path`
  and `unit` as keyword arguments (`:408-409`), `'<unknown>'` by default,
  and `requested_side` is `before` or `after` from the trace's side index. A
  test's proof passes its test path and qualname (`:939`); a module-body
  seed passes the module it traces, a conftest or the test file, and
  `'<module body>'` (`:1187`); the restructured-patch proof passes the test
  path and `'<restructured patch>'` (`mock_testcase_replacements.py:146`).
- `docs/subject-integrity.md` now gives the stand-in pass 200,000 nodes, says
  the subject-replacement pass shares the limit, and says what each refusal
  names. `docs/KNOWN-ISSUES-next.md` gains a #469 row. The #345 row of
  `docs/KNOWN-ISSUES-v0.8.0.md` stays as the v0.8.0 record.

Readings within the ruling's text; the owner approved each as written
(below):

- When both counters fire on the same step, the message names
  `counter=proof`, the counter `_step` compares first, with its steps and
  limit.
- The kinds of proof are spelled `'<module body>'` and
  `'<restructured patch>'`; angle brackets keep them apart from any
  qualname. A seed's `path` is the module whose body it traces.
- The shared-budget sentence follows the fields: `; the unit is where the
  shared analysis budget ran out, not necessarily its cause`.
- A rename's base side is named by its old path.
- Only the node limit is shared. The byte limit stays this pass's own
  1,000,000, the same value as the stand-in pass's `_MAX_SOURCE_BYTES`.

Effects by reading:

- In a run with a source reader, as `check` gives, the stand-in pass
  (`engine.py:1735`) runs before
  this pass (`:1743`) and parses both sides of every changed test-role `.py`
  file (`standin_installations.py:1060-1063`) against the same 200,000
  nodes. For such a file the stand-in node refusal therefore comes first,
  naming the file, and this pass's node refusal is reached only for a file
  judged as a test that the stand-in pass does not read (a collectable
  Python file holding another role, or one under a test-support directory,
  `engine.py:1149`, `:1158-1159`), or through a direct call.
- The 43 commits' `tests/test_client_functional.py` sides are 176,658 to
  211,924 bytes, about 30,000 to 36,000 nodes at D-131's 170 nodes per
  kilobyte, so neither pass's node limit stops them now. Whether they give a
  verdict is unknown. The 17 step-limit commits still exit 2, now naming the
  counter.
- **Time, before the cache** (lines at 26209d9d). For each eligible
  assertion pair, a positive `==` with the same literal on both sides,
  changed or not, `_subject_call` (`subject_replacements.py:209`) ran on
  both sides. For a name asserted at the top level of a straight-line test
  (`value = f(1)`, then `assert value == 2`) it scanned the module's
  top-level statements: `_scope` (`:221`) and the star-import check
  (`:224-225`) iterated them, `_binding_sites(tree.body)` (`:254`) visited
  them without entering function or class bodies, and `_bindings(tree.body)`
  (`:256`) iterated them. The pass's time therefore grew with the number of
  such pairs times the number of the module's top-level statements, about
  one per test in a file of small tests: faster than linearly for a file
  made of many small tests of that shape. At about 15 nodes per test, a
  200,000-node file of them holds about 13,000 tests, and the scanning is
  about (200,000 / 30,000)², some 44 times, the most a file under the old
  limit could cause. The whole-tree walks the ruling cites (`:412`, `:465`)
  are reached only for an inherited helper assertion that passes the caller
  checks, and for a pair whose callee changed. The owner chose to remove
  this factor now with the cache above and to time the cached pass in CI
  (A82, A83, below).
- **Time with the cache, by reading.** The work left per pair in
  `_subject_call` is bounded by the test's own body: its statements, their
  binding sites and the assignments before the assertion. For the
  straight-line shape the pass's time therefore grows linearly with the
  pairs whose callee is unchanged; a pair whose callee changed read the
  module again until the second cache (next item). The cache adds, per
  file with an eligible pair, two small objects, and one name index for
  each body `_scope` looks up, built over the whole body where the scan
  stopped at the first match. On the files of about 20 nodes in
  `tests/test_perf_git.py` that is a few dictionary entries per file, so
  the performance gates below still cannot move.
- **Read once per pair until the second cache, by reading** (lines at
  d79ba699). The first cache covered the four reads `_subject_call` made,
  the code the owner's choice points to (`subject_replacements.py:168-256`
  at 26209d9d). For an inherited assertion, `_assertion_scope` (`:439`)
  read the module on both sides for every such pair:
  `_helper_module_inert(tree)` (`:450`) iterated its top-level statements,
  and for a caller that passed its checks a walk of the whole tree (`:469`)
  and `_binding_sites(tree.body)` (`:471`) followed. So a file of many
  small tests that each begin by calling one module helper holding a
  literal assertion (`def check(): assert f(1) == 2`, then
  `def test_1(): check()`, six nodes per test) cost about the pairs times
  the module's nodes: at 200,000 nodes, some 33,000 tests, each walking all
  200,000 nodes on both sides. That is faster than linearly, and more than
  the straight-line shape cost before the cache. For a pair whose callee
  changed with the same arguments, the replacement the pass looks for,
  `_scoped_bindings` read the module's bindings again on both sides
  (`:373`), since it extends them, and scanned the module for the test
  (`:374`); when the new callee reached the literal-string helper check,
  `_literal_helper_replacement` also checked every other function of the
  module (`:500-520`) and could walk the whole tree (`:522`). The owner
  chose to keep these reads too, with no budget that fails closed (B13,
  below), and this reading goes on #469 with the numbers (A84).
- The performance gate cannot move. `tests/gates/test_perf.py` calls
  `analyze` without a `root_reader`, and both passes return no events
  without one (`standin_installations.py:1038`,
  `subject_replacements.py:627`), so the gate reaches neither changed path;
  its pathological file is a production file (`app/generated.py`) that
  neither pass reads. `tests/test_perf_git.py` runs both passes through the
  CLI on 150 test files of about 20 nodes each, far under both limits and no
  stand-in candidates, so their work is unchanged. A run that refuses
  nothing gains only constant work per call: per `_parse` call, two keyword
  arguments and two module-global lookups where the limits were literals;
  per parsed change, one `_trees` call with two path normalisations; per
  `_Trace`, two keyword arguments and two attribute stores; and per step,
  one module-global lookup in `_step`, where the per-proof limit was a
  literal (up to 1,000,000 steps per analysis).

**Timing (CI run 39253512334, job 118062910969).** The temporary
`timing-469` job (A82) ran once, on GitHub's hosted ubuntu-latest runner
(image ubuntu-24.04, version 20261012.334.1) with Python 3.12.15, at
`dac1a476`, the merge of this pull request's head `4c5e631d` into main
`0eff0e52`. This is one run on a shared hosted machine, not a benchmark,
and its times move with the machine. The job built synthetic test files of
exactly 30,000, 100,000 and 200,000 syntax nodes per side in four shapes:
the straight-line tests above (15 nodes each, three runs per size); one
such test among module-level assignments (statements); the helper-call
tests above (six nodes each, also at 10,000 nodes); and, under B13, tests
whose callee changed with the same arguments (ten nodes each),
`assert f("a") == "a"` on the base side and `assert g("a") == "a"` on the
head side with a literal-string helper `def g(s): return s.lower()`, so
that every pair reaches `_scoped_bindings` and the literal-string helper
check. In the first three shapes the sides differ only in their module
docstring, so every pair keeps its callee and the pass moves on at
`subject_replacements.py:681`. Each measurement ran in its own process
with a 300-second budget within a 35-minute deadline; every one exited 0,
and none overran its budget or was skipped. For each, the job printed the
time `analyze` took before `subject_replacement_events` began
(`to_pass_s`), the pass's own time, its parse of both sides included
(`pass_s`), the pass's events, and its `_subject_call`, `_assertion_scope`
and `_scoped_bindings` calls. In seconds, with the three straight-line
runs in run order and their median:

| Shape | Nodes per side | `pass_s` | `to_pass_s` | Events | `_subject_call` | `_assertion_scope` | `_scoped_bindings` |
|---|---:|---|---|---:|---:|---:|---:|
| straight | 30,000 | 0.375, 0.392, 0.401; median 0.392 | 1.312, 1.357, 1.368; median 1.357 | 0 | 3,998 | 3,998 | 0 |
| straight | 100,000 | 1.532, 1.541, 1.615; median 1.541 | 6.743, 6.798, 6.903; median 6.798 | 0 | 13,332 | 13,332 | 0 |
| straight | 200,000 | 3.229, 3.336, 3.309; median 3.309 | 17.581, 17.822, 17.616; median 17.616 | 0 | 26,666 | 26,666 | 0 |
| statements | 30,000 | 0.13 | 0.839 | 0 | 2 | 2 | 0 |
| statements | 100,000 | 0.565 | 3.18 | 0 | 2 | 2 | 0 |
| statements | 200,000 | 1.125 | 6.635 | 0 | 2 | 2 | 0 |
| helper | 10,000 | 0.245 | 0.694 | 0 | 3,328 | 3,328 | 0 |
| helper | 30,000 | 0.814 | 2.882 | 0 | 9,994 | 9,994 | 0 |
| helper | 100,000 | 2.832 | 16.722 | 0 | 33,328 | 33,328 | 0 |
| helper | 200,000 | 6.021 | 53.499 | 0 | 66,660 | 66,660 | 0 |
| callee | 30,000 | 0.378 | 1.854 | 2,998 | 5,996 | 5,996 | 5,996 |
| callee | 100,000 | 1.283 | 9.441 | 9,998 | 19,996 | 19,996 | 19,996 |
| callee | 200,000 | 3.267 | 27.846 | 19,998 | 39,996 | 39,996 | 39,996 |

At 200,000 nodes the sides were 538,955 to 855,598 bytes. Only the callee
shape gave events or reached `_scoped_bindings`.

Linear growth multiplies a time by 3.3 from 30,000 to 100,000 nodes, by 2
from 100,000 to 200,000 and by 6.7 from 30,000 to 200,000. The pass's own
time grew by 3.9, 2.1 and 8.4 for the straight-line shape (medians), 4.3,
2.0 and 8.7 for statements, 3.5, 2.1 and 7.4 for the helper shape (and
3.3 from 10,000 to 30,000, where linear is 3), and 3.4, 2.5 and 8.6 for
the callee shape. Per node at 30,000, 100,000 and 200,000 nodes, that is
13.1, 15.4 and 16.5 microseconds for the straight-line shape, 4.3, 5.7 and
5.6 for statements, 27.1, 28.3 and 30.1 for the helper shape (24.5 at
10,000) and 12.6, 12.8 and 16.3 for the callee shape.

Against ruling item 1's condition: this is the time at 200,000 nodes it
asks for, measured on the fix in CI. There the pass's own time was 1.1 s
for statements, 3.3 s for the straight-line shape (median of three) and
for the callee shape, and 6.0 s for the helper shape, the slowest. With
the caches its growth is close to linear: from 30,000 to 200,000 nodes it
grew 7.4 to 8.7 times where linear is 6.7, so its time per node rose by
11 to 30 per cent across the range, where the straight-line shape before
the cache was read as growing with the square of the file, some 44 times
(above). The largest step over linear is the callee shape's 2.5 times from
100,000 to 200,000 nodes; one run cannot tell whether that excess comes
from the code or the machine, and the job does not look for its cause.
The agent does not read this as the faster-than-linear growth the
condition names, so it proposes no work budget; the owner's review of
this paragraph (B15) settles that reading.

The time before the pass is outside the condition, and in this run it grew
faster than linearly in three shapes. From 30,000 to 200,000 nodes it grew
13.0 times for the straight-line shape (medians, 1.357 to 17.616 s), 18.6
times for the helper shape (2.882 to 53.499 s; 5.8 times from 30,000 to
100,000 alone) and 15.0 times for the callee shape (1.854 to 27.846 s),
against 7.9 times for statements (0.839 to 6.635 s). At 200,000 nodes it
is most of the time to the end of the pass: 53.5 s of the helper shape's
59.5 s. It covers every step `analyze` takes before this pass, the
frontend's parse of both sides and the stand-in pass (`engine.py:1735`)
among them, and the job does not split it, so which step grows is unknown,
and D-131 item 2's stand-in time is still not taken. No ruling covers this
growth (Residuals).

The same run's other jobs, at the same checkout: the nine test jobs
(ubuntu-latest, macos-latest and windows-latest, each with Python 3.11,
3.12 and 3.13), install-from-tag, dogfood and byte-compare passed, and
published-source was skipped. Dogfood's verdict was pass, with three WARN
findings: CI_WORKFLOW_TOUCHED for this job's change to
`.github/workflows/ci.yml`, and IMPORT_UNRESOLVED for each of
`tests/test_issue469_limit_messages.py`'s imports of
`test_mock_testcase_replacements` and `test_standin_installations_main`,
sibling modules in `tests/`. b77240d5 then removed the job, which returns
`.github/workflows/ci.yml` to main's bytes; the runs after it are this
pull request's later CI.

**The Stop hook.** These refusals are engine errors. Under D-134 item 2 a
hook-json engine error exits 0 with the "not analysed" `systemMessage` and
no `decision` (`DECISIONS-archive-1.md:9790-9793`), so in the Stop hook they do not
block the stop: the class of #456 (D-134 residuals,
`DECISIONS-archive-1.md:9849-9855`). By reading an agent could provoke one on purpose,
for example with a test-module body that runs past 20,000 steps. The
required CI check runs in range mode and still exits 2. D-150 blocks in
hook-json only on a size refusal of the verdict diff; its Q6 sent the other
limit refusals to #506, which these join now that they name path and side.
They stay non-blocking until #506 is ruled. THREATMODEL row 128 already
lists them as still open, so it does not change.

D-131 recorded that "`subject_replacements._parse` keeps its own
30,000-node limit" (`DECISIONS-archive-1.md:9588-9589`) and repeated it under Open
(`:9605-9606`). That no longer holds.

Residuals. Two more stand-in limit refusals name nothing:
`stand-in strict inventory is invalid or exceeds the path limit`
(`standin_installations.py:1084`) and `stand-in context exceeds the source
read limit` (`:1123`). They are not in this round. D-131 item 2's
stand-in time is not measured, and which step makes the time before this
pass grow faster than linearly in the Timing run is unknown. By reading, one
check still reads the module once per pair: for a pair whose new callee
is a `math.gcd` helper, the check of the module's other functions
(`subject_replacements.py:612`) is made for each pair, since its proof
reads the pair's bindings. It follows `math_import_authority`, which
admits only a test source of at most 65,536 bytes and 4,096 nodes
(`oracle_purity.py:150-157`), so it is made only in a file that small.
Which step counter fires on the 17 commits is unknown; finding out needs
the approved run of ruling item 2. #345 stays open and is judged again when this lands and the
sweep re-runs its commits (the owner's decision of 2026-10-16); for that
re-sweep's manifest, which the owner approves before it runs, the agent
proposes the 60 commits plus `5a8ebdfcae`.

Rule 2. The ruling approves one change to an existing expectation, as
D-134 did (`DECISIONS-archive-1.md:9834-9841`), and it is the only one made:
`tests/test_standin_expression_iteration.py:190` pinned
`^stand-in execution proof exceeds the source step limit$`. Its pattern now
keeps that text as the prefix and also matches the new fields, with
`counter=proof` for the row at `:177` and `counter=analysis` for the row at
`:179`. The four rows at `:176-179`, which of them refuse, and the charge
counts asserted after them do not change. By `git grep` at this PR's base,
no other test or fixture pins any of the three messages or the 30,000
value. If this PR's own checkwash run flags the test change, an exemption
in `.greenwash/allow.toml` like #451's goes in the PR for the owner's
approval. If CI moves any other expectation, the round stops and asks.

Evidence status: prepared on a work machine where no pytest, checkwash or
code of this repository ran; CI runs the tests. Added: 35 collected items in
`tests/test_issue469_limit_messages.py`, none under `tests/gates`: the
shared constant; trees of 30,001 and 200,000 nodes; a test file of about
35,000 nodes giving its `TEST_PATCHES_SUBJECT` verdict; the node and byte
refusals and their defaults; the refused side of a changed test and a
rename's old path through `analyze`; each step counter, both at once, the
defaults and an escaped path; each proof named where it stops through
`installation_events`; the path, side and unit each trace carries; and,
for the cache, that its scope index finds what the scan finds, that kept
reads project what fresh reads do across one file's assertions, that
through `analyze` each side's module is read once for a file of 30 tests,
and that the findings equal those of reads made afresh; and, for the
second cache, that its inert, statement, write and helper answers equal
fresh reads, that `_assertion_scope` locates the helper fresh reads
locate, that `_scoped_bindings` reads as the copy it made before, that
through `analyze` each side's module is read once for a file of 30
helper-call tests and one of 30 changed-callee tests, and that the
findings on helper, changed-callee, literal-string and `math.gcd` files
equal those of fresh reads; and, for the answers kept under C5, that a
kept `math_import_authority` answer equals a fresh check's for several
targets, old callees and two names of one imported function, that through
`analyze` the authority is checked once for a file of 30 `math.gcd`
tests and the parameterized-helper checks are made once for a file of 30
parameterized-helper tests, that the findings on both kinds of file
equal those of fresh checks, and that each of two changed files has its
own kept checks. No
`.gwcase` fixture is added: the golden runner cannot expect an engine
error. By reading, the documented test count becomes 20126 (20091 + 35);
CI's collection checks it.
`NOT_RUN：工作機規則（POLICY work-machine-local），every behaviour and count above is read from source, except the Timing numbers, which are read from CI's job log; no test, timing, checkwash run or sweep was run on the work machine`.

The agent wrote this entry in #469's fix PR #511. On 2026-10-19 the
maintainer replied 「PR 核可清單全部照建議」 ("the PR approval list, all as
recommended") to the agent's approval list, whose items for this PR asked
how to take the time at 200,000 nodes
(A82: a temporary CI timing step at 30,000, 100,000 and 200,000 nodes,
removed once its numbers are written here), whether to add the cache now
(A83: yes, and time the cached pass), when to report the superlinear
reading on #469 (A84: once, with the numbers), the wording of this entry
as of 86788e34 and 20f5f1a7 (A85: approved, leaving only the paragraphs
added for the timing, CI and dogfood results to review), and its five
readings (A86: approved as written). The reply is the text of a button the
agent wrote, which the owner chose. The text added or changed in 11e370d2
(the cache, the Time paragraph recast for the code before it, the two new
effects, the timing placeholder, the residual sentence, one line reference
and the evidence status), with the review corrections to it after
d4ed8b3e, is not covered by this approval and still needs the owner's
review, as the timing paragraph will once its numbers are filled.

Later that day the maintainer replied 「第二輪核可全部照建議」 ("the round-2
approval list, all as recommended") to the agent's second list. The reply
is the text of a button the agent wrote, which the owner chose. Its items
for this PR: B13, keep the reads of the two paths that still read the
module once per pair, the inherited helper assertion and the pair whose
callee changed, without changing any result, add a callee-changed shape
to the timing job, and rule no budget that fails closed; B14, keep the
timing job's measurements beyond A82 (the helper shape, its 10,000-node
size and three runs per size of the straight-line shape); and B15, review
the text added or changed in 11e370d2, with its later corrections,
together with the Timing paragraph once its numbers are filled. Under
B13, 8e99cb6b keeps the reads, 92f861ea pins that no result changes and
6a51d208 adds the callee-changed shape. The text this entry gained for
them is under B15's review as well.

Later that day the maintainer replied 「第三輪核可 C1～C6 全部照建議」 ("the
round-3 approval list C1–C6, all as recommended") to the agent's third
list. The reply is the text of a button the agent wrote, which the owner
chose. Its item for this PR, C5: keep, without changing any result, the
reads of the two checks B13 left reading the module once per test, the
`math.gcd` helper branch for a changed callee and
`parameterized_abs_event`, instead of leaving them as residuals, and let
the timing job measure the version with these caches. Under C5, 90f6a70d
keeps their answers for each file and 81084439 pins that no result
changes. A read-only review of these commits found that 90f6a70d kept the
authority's answer per target and old callee, so a file whose tests call
distinct old callees still read its module once per test; 88a95270 keeps
the authority's parts once per file instead, and 81f7b949 pins that and
that each file has its own kept checks. The timing job kept its shapes;
none of them reached either check, so its numbers time the pass with
these caches but not the two checks themselves. The text this entry
gained for them is under B15's review as well.

After these approvals the Timing paragraph was filled from the log of run
39253512334, and b77240d5 removed the timing job. That paragraph, and the
Residuals and evidence-status sentences changed with it, are under B15's
review.

The maintainer approved that text on 2026-10-19:
「第四輪 D1～D10 全部照建議」 ("the round-4 list D1–D10, all as
recommended"), in reply to the agent's round-4 list. The reply was a
button whose text the assistant wrote, which the owner chose. Its items
for this entry: D3 approves the numbering sentence above as c7efced8
rewrote it to the facts at merge, which extends C1 to this entry. D7
approves, under B15, the paragraphs this entry gained after A85: the
cache paragraphs, the Timing paragraph filled from run 39253512334
(b4b15328; the list quoted it in full as at c7efced8), the Residuals and
evidence-status sentences changed with it, and the approval records;
with them, the KNOWN-ISSUES-next #469 row's measured range (3a86ef11)
and the timing job's removal (b77240d5). Approving the Timing paragraph
accepts its reading of ruling item 1: with the caches the pass grows
close to linearly, so no work budget is set. D9 records the
faster-than-linear growth of the time before the pass as a residual,
with no new issue: one sentence in the KNOWN-ISSUES-next #469 row
(fe319152, in integration batch 3), beside the timing comment on #469
(issuecomment-6269941656) that reports it; a measurement that splits
that time, for example of the stand-in pass (D-131 item 2), goes to the
pool after the release. This paragraph was written after the reply.

On 2026-10-20 the owner approved the paragraph above with
「第七輪 H1～H5 全部照建議」 ("round 7, H1 to H5, all as recommended"), a
button whose text the assistant wrote: its item H2 approves together the
round-4 and round-6 approval records, the C1/D3 rewrites at merge and the
batch-4 merge sentences it lists. This sentence was written after the
reply.

## D-155 (2026-10-19): a fixture's producer is repair evidence for the assertion that reads it (#471)

Ruling 471 (owner, 2026-10-16, issuecomment-6230178131, 「#468、#471
都照建議。」, "#468 and #471 both as recommended"), adopting the analysis in
issuecomment-6229395341: Q1 (c), Q2 (a), Q3 (b), Q4 (a), and Q5 (b) as a
separate issue (#473, no label change here). The fix follows the analysis's
§4. The three cases built from the reporter's unit names were approved on
2026-10-18 (「19 項全部照建議做（價值判斷的題也照你的傾向）」, "all as
recommended, value judgements included", quoted in issuecomment-6248629600).
D-151 to D-163 were assigned to pull requests prepared in parallel. When
integration batch 2 merged, all of them were on main except D-153, which
is unused, and D-154, which is pending in #511. This entry is D-155.

#471 (talhayme, punt-labs/langlearn-tts `b4bc4e63`): a production default
changed from `"rachel"` to `"matilda"`, and the tests that get the provider
from a conftest fixture followed it. Repair evidence credits a symbol the
test calls (SPEC §5 clause 1), and a call is one written in the unit's own
body, so the tests called nothing that builds the provider:
`EXPECTED_VALUE_HARDCODED` blocked with NO_PROD_CHANGE_IN_DIFF three times.
The same tests calling `ElevenLabsProvider()` themselves passed.

Implementation (lines at this PR):

- `frontends/python/fixture_producers.py` (new). `producer` (`:222-275`):
  the fixture's only `return <value>`, or in a generator its only
  `yield <value>`, outside nested defs, classes and lambdas, and under no
  branch, loop, `match`, or `try` handler, `else` or `finally`
  (`_unconditional`, `:196-209`); the value is a call with a dotted callee,
  or a name, not a parameter, bound exactly once in the fixture's scope by
  a plain `=` or annotated `=` of such a call (`_binders`, `:89-124`;
  `_assigned_value`, `:212-219`). The callee's root must be resolved by
  `import_modules` (`:53-86`) of the fixture's file and not be bound by the
  fixture itself. `ProducerScope` (`:278-317`) reads one module or class
  body as `SetupScope` reads its fixtures; `unit_producers` (`:320-351`)
  resolves each fixture the unit requests by parameter.
- `setup_skip_controls.ConftestLevel.producers` (`:773-777`), filled in
  `conftest_level` (`:977-980`) through the conftest's own imports.
- `frontend`: `UnitSide.fixture_producers` per side (`fixture_producers`,
  `:4258-4283`, passed at `:4443` and `:4531`), and
  `Assertion.fixture_reads` for the unit's own assertions (`fixture_reads`,
  `:3276-3322`, used at `:3421` and `:3491`, with
  `fixture_producers.assertion_names`, `:130-166`, and
  `_fixture_read_bindings`, `:1536-1580`, with
  `fixture_producers.nested_bound_names`, `:169-193`). Only a unit that
  takes a parameter reads any. `ir/model.py:130-137`, `:259-268`.
- `gating.py`, in its own commit (da116dd1), as the analysis's §4.5 has
  it; the owner approved it on 2026-10-19, as D-048 and D-141 approved
  policy code:
  `_finding_assertion` (`:331-358`) finds the before half of the assertion a
  finding cites, by span and text, through the pair when the finding cites
  only its after side (EXPECTED_VALUE_HARDCODED); `_fixture_producer_evidence`
  (`:361-384`) matches the producer of each fixture that assertion reads
  with `_symbol_match` (`:166-213`, D-046) against the modules its root's
  import names; `_repair_evidence` checks it last (`:442-445`), and
  `apply_gates` passes no assertion for TEST_DISABLED (`:875`).

What the ruling's four answers become:

- Q1 (c). Only the producer counts, not the other calls in the fixture's
  body, the producer's own arguments included. "Resolved through the
  fixture file's own imports" is read as: the root is a name whose final
  top-level binding in that file is an `import` or an absolute
  `from ... import`, after any star import, and the modules that statement
  names are the only imports the D-046 match reads. A root the fixture
  binds (`return app.test_client()`, with `app` a parameter), a root under a
  top-level `if` or `try`, a relative import and a same-file def give no
  producer.
- Q2 (a). One level, for an argument without a default (`request` and the
  instance excepted), resolved as pytest resolves it: the innermost class,
  enclosing classes, the module, then each `conftest.py` above it, nearest
  first, the `<plugin-configuration>` context passing through (#358). A
  name a `parametrize` supplies directly runs no fixture; `indirect` still
  runs it. The fixtures a fixture requests count nothing, and so do an
  `autouse` fixture and a `usefixtures` mark the test does not also request
  by parameter. One it requests by parameter is a fixture like any other,
  as the ruling's "requests by parameter" reads
  (`test_an_autouse_fixture_the_test_also_requests_by_parameter_has_a_producer`).
- Q3 (b). The finding's assertion is its before-side one: the assertion it
  cites on its before side (for ASSERT_REMOVED, the removed one), or the
  before half of the pair whose after side it cites. It reads the parameter
  directly or through the unit's own assignments (`_resolve_through`,
  `frontend.py:1510-1533`, whose unit-level map joins every definition of a
  name: the analysis's stated residual). The fixture is resolved from the
  module and the conftest chain as they were before the diff
  (`fixture_producer_added_in_diff_pos`), and a unit with no before side
  takes nothing.
- Q4 (a). Every oracle rule that takes symbol evidence, except
  TEST_DISABLED (and TOLERANCE_LOOSENED in practice, the first departure
  below); no PACKAGE_REPAIR (`hardcoded_package_only_pos`); classes and
  factories alike as producers, matched directly (the second departure).
  The TEST_DISABLED guard in `apply_gates`
  (`:875`) is defensive today: no TEST_DISABLED finding cites an assertion
  (a unit gone cites its unit's span, `detectors/test_disabled.py:96`; the
  other shapes cite a marker or the unit's span on the after side), so
  `_finding_assertion` finds none, and `fixture_producer_test_disabled_pos`
  is a parity pin that blocks with or without the guard.
  `test_the_test_disabled_guard_is_what_withholds_a_changed_producer` hands
  every finding an assertion that reads the changed producer, and pins the
  guard itself.

Readings where the ruling is silent, each erring toward no evidence; the
owner approved all four on 2026-10-19:

1. Stricter than `_setup_reach` (`setup_skip_controls.py:1037-1093`) in two
   places: at the test's own levels, a name bound another way or a star
   import stops the lookup at that level, where `_setup_reach` looks past a
   class to the module; and a class with a base other than `object`, or
   with a keyword, stops it, since a base may define the fixture and
   `SetupScope` reads only the class's own body. A same-file inherited test
   is resolved from its collecting class, which has a base, so it takes a
   producer only from a fixture that class defines.
2. One value site: several `return` statements, a bare `yield`, a
   `yield from`, an awaited call, a conditional expression, and a value
   bound through `for`, `with ... as` or twice give no producer. The code
   first committed did not hold to this, since one site under an `if`, a
   loop or a `try` handler still gave a producer although the fixture may
   return `None` (raised by GLM, verified by Claude); now the site must be
   a statement of the fixture's body, or of a `with` or `try` body reached
   from it, and any other gives no producer (`conditional-return`,
   `bound-then-yielded-under-with`).
3. An assertion records a read only when written in the unit's own body
   outside a nested def, class or lambda. A parameter the body binds again
   in any form is not counted: `=`, augmented, annotated or walrus (the
   binding map), and a `for` or comprehension target, `with ... as`,
   `except ... as`, `del`, an import, `global` or `nonlocal`, a match
   capture, or a nested def or class of that name
   (`fixture_producers._binders` on the unit's own scope, 1bf47526, raised
   in review). One such binding drops the parameter for every assertion of
   the unit, a comprehension target that only shadows it included. Names
   bound by `for`, `with ... as` and `except ... as` are not followed as
   intermediate bindings either, as the binding map does not record them.
   The code first committed did not hold to this inside the assertion
   itself, since a name a lambda there binds as its parameter still counted
   as a read of the fixture (raised by GLM, verified by Claude); now a name
   that a lambda's parameters or a comprehension's targets bind within the
   assertion is no read, and a parameter all of whose occurrences there are
   such names is not counted, even through a local the assertion reads
   (`assertion_names`; `lambda-parameter-of-that-name`). That fix did not
   reach the unit's own assignments, where
   `result = (lambda ledger: ledger.fee)(make())` then `assert result == 5`
   still read `ledger` (found in the round-2 review, fixed under C2): now a
   name that a lambda's parameters or a comprehension's targets bind within
   an assigned value is not followed from it, even where it also occurs
   outside them, erring toward no evidence (`_fixture_read_bindings`;
   `lambda-parameter-of-that-name-in-an-assignment`). Nor is an assignment
   or walrus inside a nested def, class or lambda followed, since it binds
   another scope's name: a walrus in the assigned lambda
   (`(lambda ledger: (fee := ledger.fee))(make())`) and a nested def's own
   `fee = ledger.fee` still led to the fixture until the review of the
   round-3 commits found them. A walrus such a def or lambda evaluates in
   the unit's scope, in a default or a decorator, is left out with them,
   erring toward no evidence. These two shapes, and a comprehension in an
   assigned value (`vals = [fee for fee in rows]` after
   `fee = ledger.fee`), have no pin of their own, as C2 approved one.
4. The finding's assertion is matched by span and text. A finding whose
   evidence is not one of its unit's assertions takes nothing.

**Two departures from the ruling, which the owner kept on 2026-10-19.**

1. TOLERANCE_LOOSENED takes symbol evidence, but its finding cites its
   unit's span (`detectors/tolerance_loosened.py:213-214`), not an
   assertion, so it never has a before-side assertion and takes no
   producer: Q4 (a) as implemented covers it in name only. The alternatives
   were to recover the pair in gating from the unit's tolerance changes
   (the detector's `_sources`, duplicated), or to cite the pair's spans in
   the finding, which changes its reported evidence. The owner took
   neither: he accepted the limit as disclosed in row 158 and
   KNOWN-ISSUES-next, with no issue opened.
2. Neither the one-hop callers route (SPEC §5 clause 2) nor a helper hop is
   followed from a producer. A factory producer that is unchanged and calls
   a changed symbol gives nothing, while the same factory called inline
   takes the callers route
   (`test_the_one_hop_callers_route_is_not_followed_from_a_producer`). The
   first draft of this entry filed it as a reading where the ruling is
   silent; review found that the ruling is not silent. The ruling adopted
   the analysis, which has the producer compose with that route: its §2.2
   says a top-level factory producer "reaches a changed top-level class only
   through #420's hop", and its §4.5 lists "a top-level factory producer
   until #420 lands" as the residual. Only a top-level factory over a
   top-level callee would then stay out, through #420's leaf defect
   (`evidence.py:239`; #420 is deferred in #504). The code is narrower:
   every factory gives nothing, one that calls a changed method included.
   The alternative was to check the producer's leaf in
   `prod_symbol_callers` for the reading assertion, as `_repair_evidence`
   checks a unit's calls (`gating.py:422`). That route matches leaf names
   with no module check, so a producer would carry that looseness, as an
   inline call does today. Row 158, SPEC §5 and the docs would then have
   kept only the top-level case, and the pin above would have flipped to
   warn with REPAIR_EVIDENCE. The owner kept the narrower reading,
   recorded as this departure, so the pin stays as it is.

Residuals, kept documented as the ruling says (THREATMODEL row 158, new,
false positive): a setup call in the fixture, an `autouse` fixture or
`usefixtures` mark the test does not request by parameter, fixtures of
fixtures, the readings above, both departures (kept by the owner), a test
class with a base or a keyword (for a fixture outside its own body), and
xunit `setUp` on `self` (#306's `self` resolution). What the fix newly
allows is one more spelling of row 93's Route A, on the class or factory
that builds the value the assertion reads, which the inline spelling had
already (`route_a_fixture_producer_neg`); row 93 says so. Row 86j notes that
the chain carries a producer and still no value (#425, deferred in #504).
SPEC §5 states the producer, the T1.9 hop, and PACKAGE_REPAIR's scope
(EXPECTED_VALUE_CHANGED and EXPECTATION_DEFINITION_CHANGED). Its D9 row
said DEPENDENCY_DRIFT holds "those two only, exactly like PACKAGE_REPAIR";
`gating.py` has also given that credit to EXPECTATION_DEFINITION_CHANGED
since T1.9 (58fe2e9f), and the owner chose on 2026-10-19 to correct the
row here, within the SPEC §5 wording, so it names all three rules.

**Effect, by reading.** The reduced case holds its six findings at warn
with REPAIR_EVIDENCE and passes at the default `fail_on`; its three
EXPECTED_VALUE_CHANGED move from PACKAGE_REPAIR to REPAIR_EVIDENCE, which is
checked first. It still blocks under `fail_on = "warn"` or `oracle_freeze`,
as the direct twin does. For the full commit, the reporter named the units
of the two ASSERT_SUBSTITUTED and the SUBJECT_INPUT_CHANGED; built from
that description (each assertion reading `elevenlabs_provider` directly),
they are held at warn (`fixture_producer_assert_substituted_neg`,
`fixture_producer_subject_input_changed_neg`), with the conftest edited in
the same diff too (`hardcoded_via_edited_conftest_fixture_neg`). His
comment 6264130796 then showed how those tests are written, and
`fixture_producer_annotated_class_methods_neg` follows it, credited to him
as the cases built from his report now are: class methods with an
annotated fixture parameter, a fixture whose producer takes another
fixture, and the conftest's mock data edited in the same diff, with its
seven findings held at warn by reading. The six other
EXPECTED_VALUE_HARDCODED findings of that commit are not traced, so this
entry does not say the commit passes.

Rule 2. The ruling approves no change to an existing expectation: by
reading none moves, and none was changed. The change only adds an evidence
route, so no finding is added or removed and a verdict can move only toward
pass. By a read-only scan on 0e60832a: among `tests/cases`, the 17 cases
with a fixture beside a changed non-test file are CI, guardrail, JS,
collection-control and `<suite>` shapes, with no oracle finding on an
assertion that reads a requested fixture's producer; in
`tests/verdict_gate/cases` only `i199/P5`, a `<suite>` TEST_DISABLED; in the
decoy arms one autouse conftest patch, which Q2 (a) does not follow; the
tamper and refactor corpora are test-only diffs. The inline sources of the
pytest files were scanned by heuristic only; CI is the check. Nothing under
`tests/gates` changed. If CI shows an existing expectation moving, the
round stops.

**Fingerprints and IR.** No fingerprint scheme, finding or key changes:
escalators and de-escalators are outside `make_fingerprint` (D-141).
`--emit-ir` gains `UnitSide.fixture_producers` and `Assertion.fixture_reads`,
both optional, so IR_VERSION stays 2 (`docs/stability.md:104`).

**Release.** v0.8.0 does not include this. The owner put #471 in
v0.9.0's scope on 2026-10-19 (consolidated ruling, #419
issuecomment-6261642679, R1), so this fix merges before the combined
sweep's manifest is frozen. No release is authorized (AGENTS.md rule 5).
`docs/KNOWN-ISSUES-next.md` has a #471 row, and
`docs/assertion-coverage.md` a section.

**Measurement.** Not measured yet. Pre-registered here, before any engine
runs, as D-141 did. Under the same ruling, this fix is measured in the
combined sweep's one run (R1, R2), where its merge gets its own
before/after pair in the chain: the standard set (1,800) and D-088's sets,
before and after. The issue-acceptance batches run on LAPTOP-01AGNPJU
under EC POLICY `checkwash-pju-sweep` (T-546), as a checkwash-lab-declared
run, after R5's two approval steps (the frozen manifest and engine commits
approved first); the v0.8.0-to-RC comparisons that gate the tag run on the
EC pool (R3). Every verdict that moves is named and adjudicated; a move
judged to lose a spec-correct block stops the round. The analysis's §4.4
report-only arms pricing the alternatives (Q1 (b), Q2 (b), Q3 (a),
Q4 (d)) need engine variants that this PR does not build. They run in the
same sweep as never-merged counterfactual engine commits on checkwash-lab,
pinned by SHA and tree, which T-546 covers (R4), and they report only:
none gates this fix. The perf gate (D-007) runs in CI; by reading, a unit
with no parameter reads nothing new, and the gate's modules have none.
`NOT_RUN：工作機規則（POLICY work-machine-local），every effect above is read from source; no engine, engine variant, test, sweep or IR emission was run`.

Evidence status: prepared on a work machine where no pytest, checkwash,
engine or product code ran; CI runs the tests. Added: 20 `.gwcase`
fixtures, 19 whose labels the owner approved on 2026-10-19 (A77) and one
he approved adding the same day (B24), and 97 collected items in
`tests/test_issue471_fixture_producers.py`, counted from its parametrize
lists, one of them the C2 pin; no existing test changed. By reading, the
documented test count becomes 19939 (19822 + 97 + 20); CI's collection
checks it.

The agent wrote this entry in #471's fix PR #522. The maintainer approved
it on 2026-10-19: 「PR 核可清單全部照建議」, "the whole PR approval list as
recommended", in reply to the agent's approval list, whose recommended
answers for this PR were: the SPEC §5 (b74b20eb, fb5b317d), THREATMODEL
rows 93, 86j and 158 with `benchmarks/FAILURES.md` (20ee51b8, 642adf05),
D-155 (4a84d818, 15a02925, 6f25134d) and docs (21adce95, 34a75607)
wording as committed, with D-155 citing R1 and R2 and the passages left
for the owner written as decided before merge (A72); the gating commit
da116dd1 as policy code (A73); the TOLERANCE_LOOSENED departure accepted
as a limit disclosed in row 158 and KNOWN-ISSUES-next, with no issue
opened (A74); the narrower reading of the second departure kept and
recorded as a departure (A75); the four readings (A76); the labels of the
19 new `.gwcase` fixtures (64cc9233; A77); and the stale SPEC §5 D9 row
corrected in this PR, within the SPEC §5 wording (A78). a8810511,
bad234b4, a489a067, fff04c1d, 22dc8f64, 16b6832b and f853630b make those
changes. The reply was a button whose text the agent wrote, which the
owner chose.

The maintainer approved further text and changes on 2026-10-19:
「第二輪核可全部照建議」, "the round-2 approval list, all as recommended",
in reply to the agent's round-2 list, whose recommended answers for this
PR were: the Measurement paragraph's reading of the analysis's §4.4
report-only arms as never-merged counterfactual engine commits on
checkwash-lab, under R4 (16b6832b; B10); and a fixture written the
reporter's way, `fixture_producer_annotated_class_methods_neg`, with
`credit: @talhayme (#471)` in its header, the same credit on the cases
built from his report, his row in `benchmarks/external-credits.json`, the
test count raised for it, and GLM's two findings (F-1, a lambda's
parameter; F-2, a single conditional `return`) fixed by the readings
already approved, with pins for each (B24). 9755fb4a, 420795e7, ad1c02aa,
fab761b1 and 034e517e make those changes. The reply was a button whose
text the agent wrote, which the owner chose. The same list approved the
closing paragraph above (B3). The round-2 list did not show the wording
of this paragraph or of the sentences 034e517e adds to the
implementation, readings 2 and 3, the Effect paragraph and the evidence
status, nor the date, fixture and row fields of the credit row
(2026-10-19, `hardcoded_via_conftest_fixture_neg.gwcase`, rows 93 and
158): the agent wrote them after the approval. From a read-only review of
those commits (Claude, under B2), the evidence status now says which item
covers which fixture, and the implementation sentence and the module's
docstrings (94a46475) no longer say the value site runs on every path; no
approval item names these fixes.

The maintainer approved further changes on 2026-10-19:
「第三輪核可 C1～C6 全部照建議」, "the round-3 approval list C1–C6, all as
recommended", in reply to the agent's round-3 list, whose recommended
answers for this PR were: fix in this PR the case of F-1 that the round-2
review left open, `result = (lambda ledger: ledger.fee)(make())` then
`assert result == 5`, erring toward no evidence, with one pin (C2); add
reading 2's rule, that a single `return` or `yield` under a branch, a
loop, a `match` or a `try`'s handler, `else` or `finally` gives no
producer, to SPEC §5, THREATMODEL row 158 and `docs/assertion-coverage.md`,
one sentence each (C3); and accept the credit row's three values as the
agent chose them, its date becoming the merge date (C4). e4397e07,
220e244a, d2439e2b, 61c3916f, ee19dbd9, 96fd4c80 and f1e1d181 make those
changes; the date changes when the PR merges. The list quoted the row's
`threatmodel_row` as "93"; the file has "93, 158", unchanged here, with
158 following the row's number at merge. The reply was a button whose
text the agent wrote, which the owner chose. The round-3 list did not show
the wording of the three C3 sentences, of reading 3's C2 sentence or of
this paragraph: the agent wrote them after the approval. From a read-only
review of those commits (Claude), 4e2b6d16 completes C2's fix, with no new
pin: an assignment or walrus inside a nested def, class or lambda is no
longer followed, so neither a walrus in the assigned lambda nor a nested
def's own assignment leads to the fixture. The nested def's case is older
than C2, and no approval item names its fix, which only removes reads and
holds the code to SPEC §5's approved wording (the test's own assignments,
written in its body outside a nested def, class or lambda).
fa0086dd and 4e2b6d16 have the docstrings cite reading 3, not the list's
label. Reading 3's sentence on these shapes was also written after the
approval.

The maintainer approved further changes on 2026-10-19:
「第四輪 D1～D10 全部照建議」 ("the round-4 list D1–D10, all as
recommended"), in reply to the agent's round-4 list. The reply was a
button whose text the assistant wrote, which the owner chose. Its item
D1 approves by name fourteen moves of this PR's expectations, made in
integration batch 2 (#533) at this PR's merge (65282aa8), after #528
(D-161) had merged before it and changed E1's label: ten expectations in
nine new `.gwcase` fixtures (`fixture_autouse_pos`,
`fixture_of_fixture_pos`, `fixture_overridden_in_module_pos`,
`fixture_producer_added_in_diff_pos`, `fixture_producer_other_module_pos`
with two, `fixture_producer_test_disabled_pos`,
`fixture_producer_unread_pos`, `fixture_requested_after_only_pos` and
`fixture_setup_call_pos`) and four in three items of
`tests/test_issue471_fixture_producers.py`. Each moves from
`NO_PROD_CHANGE_IN_DIFF` to `PROD_CHANGE_NOT_EVIDENCE`, with rule,
severity and unit unchanged, because the diff also changes a
production-role Python file that is not inert and neither earlier label
applies. A77 had approved those fixtures' labels with the old one. The
same item approves the one such move in #527's #457 pin (D-156). A
fifteenth move at that merge, the `EXPECTED_VALUE_HARDCODED` expectation
of `hardcoded_package_only_pos`, is not D1's: A52 had approved it by name
in advance, whichever PR merged first (D-161). Its item D6 applies C4 to
the credit row: #533 merged at 2026-10-19T16:19:11Z, which is 2026-10-20
in the owner's time zone (its merge commit adea2350 is dated +0800), and
the date was not changed at that merge, so aa8dfae0, in integration
batch 3, makes it 2026-10-20 in `benchmarks/external-credits.json` and
in the External credits table of `benchmarks/FAILURES.md`. This
paragraph was written after the reply.

On 2026-10-20 the owner approved the paragraph above with
「第七輪 H1～H5 全部照建議」 ("round 7, H1 to H5, all as recommended"), a
button whose text the assistant wrote: its item H2 approves together the
round-4 and round-6 approval records, the C1/D3 rewrites at merge and the
batch-4 merge sentences it lists. This sentence was written after the
reply.

## D-156 (2026-10-19): the order fallback pairs by subject first, and `match=` added to a bare raises is no removal (#434, #457)

Ruling 434 (owner, 2026-10-16, 「全部照建議」, "all as recommended";
#434 issuecomment-6223293429) adopted every recommendation of the analysis
(issuecomment-6218034432): A as the variant in its A.4, B as B1 with B2's
message for the fold shape, C closed into THREATMODEL row 119, and #457 as
A.5 (a). D-151 to D-163 were assigned to pull requests prepared in
parallel. When integration batch 2 merged, all of them were on main
except D-153, which is unused, and D-154, which is pending in #511. This
entry is D-156.

#434 reports two false findings, both read from the code. A: the order
fallback gave an old assertion the first leftover of known strength in span
order, so `assert area(4, 5) == 20.0` rewritten as `result = area(4, 5)`,
`assert isinstance(result, float)`, `assert result == 20.0` paired the old
`==` with the precondition and blocked as EXACT_VALUE(90) -> TYPE_SHAPE(50),
while the two lines swapped passed. #457 (@talhayme) is a real commit of a
related shape, executed on 0.7.0. B: `pytest.raises(E)` ->
`pytest.raises(E, match=...)` read as the bare call removed, held at warn by
`SAME_UNIT_REWRITE`, which blocks under `fail_on = "warn"` or an
`oracle_freeze` contract. C (an approx tightening that blocks only beside
`pytest.raises`) had no repro.

Implementation (lines at this PR):

- A, `ir/diffalign.py`. In the stage-3 loop (`:292-309`), for Python and a
  unit's own assertions (`_match_assertions(..., own=True)`, `:135`), an old
  assertion first takes `_subject_partner` (`:151-173`): an unused leftover
  that the fallback may pair with it (`_compatible`, `:146-148`, the rule it
  always had) and that checks the same subject. Among those, the same form
  comes first, then at least the old strength, then span order. With none,
  the old rule picks. The pair stays a fallback pair, so every rule reads it
  as it reads the swapped order's pair. With one leftover the two rules
  agree, so the leftovers' subjects are read only when there are two or
  more. The pass for assertions reached
  through a helper method (`via`, #306) is unchanged.
- The subject test is one helper, `ir/subjects.same_subject` (`:86-89`),
  which #460 can reuse: the same expression as parsed (as `same_expr`
  compares it) read in the same context, through `subject_key`
  (`:63-83`), which the fallback computes once per leftover. `subject_of`
  (`:45-60`) reads the subject written out (`left`,
  with the reaching keys of the names it reads at the assertion,
  `Assertion.reaching`) or the recorded resolved subject, and is None for
  an assertion with no subject, an inherited copy or a `via` assertion.
  `reaching_signature` (`:35-42`) serializes the keys for both.
- The Python frontend records the resolved subject as an optional field,
  `Assertion.resolved_subject` (`ir/model.py:130-138`): for a subject that
  is one local name, the expression the binding that reaches the assertion
  gave it (its `_ordered_bindings` key, `ast.unparse`) and the reaching keys
  of the names that expression reads at that binding. `_collect_unit` asks
  for it at the two own-assertion sites (`frontend.py:3408`, `:3478`)
  through `resolved_subject` (`:3321-3335`), which computes `_plain_names`
  (`:1403-1446`) and the unit's own-scope nodes once per unit, and only
  when an assertion's subject is a name the unit binds; `_resolved_subject`
  (`:1449-1477`) checks the binding that reaches the assertion.
- B, `ir/diffalign.py:311-329`. After the stage-3 loop, a removed `raises`
  record takes `_raises_partner` (`:176-183`): an unused `pattern` record
  that `ir/astutil.same_raises_check` (`:158-170`) reads as the same call
  with `match=` added. `raises_call` (`:122-155`), which #423 can reuse,
  reads the callee, the expected types, the other keywords and `match=`
  from the record's text. The pair is not a fallback pair and records no
  strength change, which every pair rule skips (`assert_weakened.py`,
  `assert_substituted.py`, `expected_changed.py`,
  `expectation_definition.py`, `subject_input_changed.py`,
  `subject_normalized.py`); the readers in `normalization.py`,
  `param_input_identity.py` and `subject_replacements.py` pass over it, as
  a raises record has no subject and is no `assert` statement.
- B2, `detectors/assert_removed.py:12-30`, `:46-49`: a removed bare raises
  call in a Python file, where the after side has a newly written `match=`
  call that `same_raises_check` accepts, gets "; the raise is still checked
  by <call>" appended to its message. Fingerprints do not use the message.

Readings where the ruling is silent; the owner approved each as written
(below):

1. Old assertions are taken in span order, as before; one whose candidates
   are all taken by earlier ones keeps the old rule. There is no two-pass
   matching.
2. "One plain single-target local binding" is `name = <expr>`, an
   `ast.Assign` with one `Name` target. Every binding of the name anywhere
   in the unit must be one: a parameter (the unit's or a nested one),
   `global`, `nonlocal`, an augmented, annotated, tuple or chained
   assignment, a walrus, a `for`, `with` or `except` target, an import, a
   def, a class, a match capture, `del` or a comprehension target excludes
   the name. An annotated assignment (`result: float = area(4, 5)`) is
   excluded too, the narrower reading of "plain". A plain assignment in a
   nested scope binds that scope's own name but is counted: the number of
   plain targets must equal the bindings the unit's statement walk records.
3. "Resolved at that assertion" is the per-assertion reaching definition:
   exactly one binding reaches it. A conditional one is enough, as the
   analysis says: had it not run, the local would be unbound and the
   assertion would raise. Not in the analysis: no conditional binding of
   the name may follow the assertion, since a loop around both would carry
   it back.
4. Only an assertion in the unit's own body is resolved. One in an invoked
   nested function reads the name when the function runs, which its
   position does not tell; its written-out subject still compares.
5. "The names that expression reads have the same reaching keys on both
   sides" compares the direct names' keys, as `reaching_sig` does, at the
   binding for a resolved subject and at the assertion for a written-out
   one. A name the unit never binds has no key on either side.
6. A candidate must still be one the fallback may pair (both strengths
   known, or one form), so no unclassifiable record is paired with a
   classifiable one (the red-team finding the fallback carries).
7. "Own assertions only": the variant runs in the own pass, and a
   same-file helper's inherited copy, a doctest record or a cross-file copy
   is neither a candidate nor looks for one.
8. The order among candidates is one key, (same form, at least the old
   strength, span), so among same-form candidates one of at least the old
   strength comes first.
9. B reads only the context-manager form: exactly one positional argument,
   not starred, and no `**`; the legacy call form passes `match=` to the
   called function. The expected types are a set of name chains, so
   `(TypeError, ValueError)` and `(ValueError, TypeError)` are the same;
   anything else matches nothing, as `_caught_types` reads a catcher. The
   other keywords are compared as `ast.unparse` writes them. The callee is
   the dotted name as written, as the frontend records it.
10. A "newly written" `match=` call for B2 is one in `assertions_added` or
    the after half of a fallback pair; one paired by text or by (form,
    subject) was there before.
11. #457's pin keeps the reduced case as the reporter wrote it, with its
    real findings as the expectation: the ASSERT_WEAKENED high, and the two
    TEST_DISABLED warns held by RESTRUCTURED (the analysis notes the pin
    cannot use the report's `expect: []`). The reporter is credited in the
    fixture header and in `benchmarks/external-credits.json`, as
    CONTRIBUTING promises.

**Effect, by reading.** #434 A1 and the `is not None` precondition no
longer block and give no finding, as A2 never did. The control (`is not
None` in place of the rewritten `==`) still blocks, now as "subject and
polarity both changed" instead of EXACT_VALUE(90) -> TYPE_SHAPE(50). A
weakening that still reads the old subject beside a decoy of the old
expectation on another subject blocks in both orders; with the decoy
written first it passed before (row 84b's residual), so such a commit goes
from pass to block. #457 is unchanged: no new assertion checks `mock_lock`,
so it blocks as before. So is the v0.1.14 dogfooded commit that opened row
85: a membership assert whose needle is not a literal records the needle as
its subject, so its derived `f"{n}/{n} tampering cases blocked" in out`
does not check `out`, and the old `"7/7 ..." in out` still pairs with the
count guard written above it and blocks. Row 85 is Closed as ruled, with
that shape as its first residual; the ruling did not address it, and the
owner kept it so, with no pin and no issue (below). B: `match=` added
gives no finding (it was a warn);
the fold shape keeps its finding with the new message; another expected
type, another callee or a dropped `match=` is unchanged. A `match=` call B
pairs no longer counts as an added assertion in D2's moved-assertion
multiset. JavaScript is unchanged. By reading, a result the subject
preference turns silent is the result the old rule gives with the other
leftovers deleted, so it opens no route that deleting them did not (the
analysis found no cheat that newly passes); a restatement that never runs,
under a runtime `if` or after the raising call in `with pytest.raises`, is
read like any other assertion, as an unchanged assertion there always was.

**C.** Closed into row 119: candidate 1 (`approx(20.0)` ->
`approx(20.0, abs=1e-9)` read as new slack although the bound shrinks) is a
named instance of its residual, and candidate 2 (approx checks paired in
span order) is in `docs/assertion-coverage.md`. A raises-dependent repro, if
one exists, is a new issue.

**#457.** A.5 (a): it stays blocking and is pinned as a known limit
(`subject_pairing_other_subject_known_limit_pos`, row 84b). A credit that
passed it would also pass an exact check rewritten as a wide approx beside
one unrelated strong assertion (row 13). This replaces the 2026-10-16 plan
to ship #457 in the next release; the reason was stated on #457, and the
reporter agreed. The known limit is written into row 84b, not a new row,
as the owner approved (below).

Rule 2. The ruling approves no change to an existing expectation: by
reading none moves, and none was changed. A read-only text scan of the
fixture corpora (711 Python file pairs in `tests/cases` and the
verdict-gate cases, 140 in `benchmarks/tamper` and `benchmarks/refactors`)
found no test function with an assertion gone and two new, where the
fallback has a choice, and one bare raises gone beside a new `match=`
call: `raises_match_fold_neg`, whose pinned fields (`cases.py`) do not
include the message. A scan of the inline sources in `tests/*.py` found
one before/after pair a test diffs where the subject preference has a
choice: `tests/test_exact_unique_predicates.py`, #434 A1's own shape,
whose assertions (a pass; a rewritten answer that blocks with
EXPECTED_VALUE_CHANGED; whether a projection is made) hold under either
pairing.
Nothing under `tests/gates` changed, and `benchmarks/decoy/expected.json`
cites none of rows 84b, 85 and 119. If CI shows an existing expectation
moving, the round stops.

**Fingerprints and IR.** No fingerprint scheme, rule or key changes.
`--emit-ir` gains `resolved_subject` on every assertion (null where it does
not apply), an optional field, so `IR_VERSION` stays 2
(`docs/stability.md`). A finding whose pair changes changes its
content-bound fingerprint with it (the control's after text and kind), so
an exemption recorded for the old finding stops matching.

**Maintainer text.** SPEC §3 (the one exception to an unclassifiable
removal) and §4 (the fallback's subject preference); THREATMODEL row 85 to
Closed, pinned by the two `bypass: 85` fixtures, and rows 84b and 119;
`benchmarks/FAILURES.md` changes with row 85. The §7 parameters and the
rule table are unchanged, and `gating.py` is not touched.

**Release.** None is authorized (AGENTS.md rule 5). Under R1 of the
owner's consolidated ruling of 2026-10-19 (「裁決總表全部照建議」; #434
issuecomment-6261648129 and #457 issuecomment-6261649543, recorded across
issues on #419, issuecomment-6261642679), v0.9.0 includes #434 and #457,
and this fix merges before the combined sweep freezes. For #457 that is
the known-limit pin only: its reported commit still blocks (A.5 (a),
above). `docs/KNOWN-ISSUES-next.md` gains a #434 row with the limits
above.

**Measurement.** Not measured yet. As ruling 434 says, the sweep measures
the change on the pool, or on LAPTOP-01AGNPJU under EC POLICY
`checkwash-pju-sweep` with an approved manifest. Under R1 and R2 that
sweep is the combined sweep: its manifest is frozen only after the R1
scope has merged, it runs once, and this fix's merge gets its own
before/after pair in its chain, which measures A and B. Under R3, the
sweep's issue-acceptance batches run on LAPTOP-01AGNPJU under EC POLICY
`checkwash-pju-sweep` (T-546), and the v0.8.0-to-RC comparisons that gate
the tag run on the EC pool. The effect above is expected; the measured
cost goes here once it has run.
`NOT_RUN：工作機規則（POLICY work-machine-local），every effect above is read from source; no engine, test, generator or sweep was run`.

Evidence status: prepared on a work machine where no pytest, checkwash or
product code ran; CI runs the tests. Added: thirteen `.gwcase` fixtures
(`subject_pairing_precondition_before_neg`,
`subject_pairing_precondition_after_neg`,
`subject_pairing_not_none_precondition_neg`,
`subject_pairing_oracle_replaced_pos`,
`subject_pairing_parameter_binding_pos`, `subject_pairing_rebound_name_pos`,
`subject_pairing_decoy_after_pos`, `subject_pairing_decoy_before_pos`,
`subject_pairing_other_subject_known_limit_pos`, `raises_match_added_neg`,
`raises_match_added_type_changed_pos`, `raises_match_warns_to_raises_pos`,
`raises_match_dropped_pos`), labels approved by the owner (below), and 71
collected items in `tests/test_issue434_subject_pairing.py`, counted from its
parametrize lists; no existing test changed. By reading, the documented
test count becomes 19822 (19738 + 71 + 13); CI's collection checks it.

The agent wrote this entry in #434's fix PR #527. On 2026-10-19 the
maintainer approved items A67 to A71 of the agent's approval list:
「PR 核可清單全部照建議」 ("the PR approval list, all as recommended").
Those items approve this PR's SPEC §3 and §4 (4472dd6e), THREATMODEL rows
85, 84b and 119 (17f90195, 3048e83a, with `benchmarks/FAILURES.md`,
45028942), D-156 (3860dfd1, f746b599, b041e17c, a9d7095e) and
`docs/assertion-coverage.md` (b634bd30, edaa6971) text as committed, with
D-156's release and measurement paragraphs to be changed before merge to
cite R1 and R2; the labels of the thirteen fixtures above; readings 1-11;
keeping row 85 Closed with its dogfooded shape as the first residual, not
pinned and with no issue; and two additions the ruling did not ask for,
the credit to @talhayme (the fixture header, `benchmarks/external-credits.json`
and the FAILURES table), dated 2026-10-19, and #457's known limit written
into row 84b rather than a new row. The reply was a button whose text the
assistant wrote.

The two commits written after that reply were approved the same day:
「第二輪核可全部照建議」 ("the round-2 approval list, all as recommended"),
in reply to the agent's round-2 list (items B1 to B25). Item B3 approves,
as one, the maintainer text the agent wrote while applying approved
options; for this entry that is the release and measurement paragraphs as
changed to cite R1 and R2 (c41cdb17) and the approval record above
(7117ee40). Item B9 approves adding a sentence to the measurement
paragraph that cites R3, as D-155 does; it was written after that reply
(efd130f5). This paragraph, and the rewording of the one above to say
only what items A67 to A71 say, were also written after that reply. That
reply, too, was a button whose text the assistant wrote.

The maintainer approved a further change on 2026-10-19:
「第四輪 D1～D10 全部照建議」 ("the round-4 list D1–D10, all as
recommended"), in reply to the agent's round-4 list. The reply was a
button whose text the assistant wrote, which the owner chose. Its item
D1 approves by name one move of this PR's expectations, made in
integration batch 2 (#533) at this PR's merge (3e37a701), after #528
(D-161) had merged before it and changed E1's label: in #457's pin,
`subject_pairing_other_subject_known_limit_pos`, the `ASSERT_WEAKENED`
high finding on `test_get_locks_from_targets_with_device_id` is expected
with `PROD_CHANGE_NOT_EVIDENCE` instead of `NO_PROD_CHANGE_IN_DIFF`,
because the diff also changes
`custom_components/lock_code_manager/__init__.py`, a production-role
Python file that is not inert, and neither earlier label applies. Its
rule, severity and unit, and the two `TEST_DISABLED` warns, are
unchanged. Item A68 had approved the fixture's label with the old one.
The same item approves fourteen such moves in #522's fixtures and tests
(D-155). This paragraph was written after the reply.

On 2026-10-20 the owner approved the paragraph above with
「第七輪 H1～H5 全部照建議」 ("round 7, H1 to H5, all as recommended"), a
button whose text the assistant wrote: its item H2 approves together the
round-4 and round-6 approval records, the C1/D3 rewrites at merge and the
batch-4 merge sentences it lists. This sentence was written after the
reply.

## D-157 (2026-10-19): a production file the diff adds does not explain a rewritten stored expectation (#463)

Ruling 463 (owner, 2026-10-18, issuecomment-6248011246, 「照建議」, "as
recommended") adopted the issue's recommendations: Q1 (a); Q2 (a) for now;
Q3 (a); Q4 (a) for now, with the escape through a test unit added in an
unrelated file named as a residual; and Q5's measurement. The maintainer
text goes in the fix PR as drafts. D-151 to D-163 were assigned to pull
requests prepared in parallel. When integration batch 2 merged, all of
them were on main except D-153, which is unused, and D-154, which is
pending in #511. This entry is D-157.

#463 reports that the file-scoped `EXPECTED_VALUE_CHANGED` (#129) is not
raised when any Python production symbol changed, or any opaque production
change exists, anywhere in the diff
(`detectors/snapshot_expectation.py:10-11@0e60832a`), and that an added
Python production file put every symbol it defines into
`prod_symbols_changed` (`engine.py:1416-1423@0e60832a`). So a new module
holding `X = 1` silenced a rewritten golden file: what remained was
`SNAPSHOT_CODE_COCHANGE` at warn, which passes at the default `fail_on`,
and nothing at all once any test logic changed. #419 Q7 (a) named it a
residual (row 132, D-141).

Implementation, in `ir/model.py`, `engine.py` and
`detectors/snapshot_expectation.py` (lines at this PR):

- Q1 (a). `DiffGlobals.prod_symbols_in_added_files`
  (`ir/model.py:436-445`) holds the entries of `prod_symbols_changed` that
  `build_ir`'s added-file branch contributes, one per entry
  (`engine.py:1416-1427`). The file-scoped form subtracts them as a
  multiset before asking whether a production symbol changed
  (`_existing_prod_symbol_changed`, `detectors/snapshot_expectation.py:8-18`):
  an added `pkg.py` and a modified `pkg/__init__.py` both give `pkg::X`,
  and the modified one still counts. A deleted Python production file keeps
  counting (`engine.py:1428-1442`), as (a) rules and (b) would not. The
  reason is the one the added-file branch's own comment gives
  (`engine.py:1417-1418`, quoted by the issue), which clause 3 of repair
  evidence (SPEC §5, row 73) and `PACKAGE_REPAIR` (D-010) already act on:
  nothing in a brand-new file explains rewriting an existing expectation.
- Every other reader of `prod_symbols_changed` is unchanged: symbol repair
  evidence and the one-hop callers (`gating._repair_evidence`,
  `evidence._record_callers`) still read an added file's symbols. Nothing
  in `gating.py`, the severity table or `ORACLE_RULES` changes.
- Q2 (a). The form stays diff-global: a changed symbol in any existing or
  deleted Python production file counts, whether or not a test reaches it.
- Q3 (a). `prod_opaque_change` still silences the form, consistent with
  #419 Q1 (D-141), until a sweep prices (b). A file the diff adds never set
  it (row 73), and an added data file or unparseable `.py` gave no symbol,
  so neither ever counted.
- Q4 (a). `SNAPSHOT_CODE_COCHANGE` (`detectors/globals_rules.py:22-47`) is
  unchanged: every production-role file the diff changes counts, a new one
  included, except a file renamed out of a test, conftest, CI, guardrail or
  snapshot path or out of test collection, which arrives as a synthetic
  addition and never enters `prod_files_changed` (`engine.py:1379-1384`);
  and test logic in any test or conftest file removes it. Beside
  a new module, a rewritten golden file now reports both findings; beside a
  new module and a new unrelated test, `EXPECTED_VALUE_CHANGED` alone.

The newly raised finding goes through E1 as the snapshot-only form does.
It has no unit, so only the opaque-change credit could hold it
(`gating._file_repair_evidence`), and this diff has none. `PACKAGE_REPAIR`
needs a package with a modified existing symbol (D-010), and whenever this
diff had one the form would not fire. So the finding is high with
`NO_PROD_CHANGE_IN_DIFF`, or warn under D9 `DEPENDENCY_DRIFT` when a
dependency manifest's dependencies changed too, as for a golden file
rewritten alone.

Readings within the ruling's text:

- "A production file the diff adds" is a change with status `added`. A
  Python file renamed out of a test, conftest, CI, guardrail or snapshot
  path arrives as a synthetic addition that contributes nothing at all
  (`_expand_renames`, `engine.py:370-415`); a rename within production is
  the existing file it was. A rename onto a `.py` production path from a
  docs or lockfile path whose base side parses as Python still counts its
  changed symbols. That costs no less than residual (1) below, so it is
  left as it is; the owner approved this reading (below).
- A symbol is counted per entry, not per name: the multiset difference
  above.

Not settled by the ruling; the owner settled each as follows (below):

- The E1 label. At this PR the newly raised finding is labelled
  `NO_PROD_CHANGE_IN_DIFF` over a diff that adds a production file. SPEC
  §5 gives that label to every E1 finding outside its two named cases, and
  an oracle finding beside an unrelated production change already reads
  the same way; but as a sentence it is untrue of this diff, the class
  `docs/integrations.md` §6 describes. #473 settles it, so it needs no
  ruling of its own: under ruling 473 Q2 a diff that changes a
  production-role file that is not inert, an added one included
  (`prod_files_changed`), changed production, and Q3 names the label for
  it. Once #473's PR #528 (D-161) merges, this finding, when it escalates
  through E1, is labelled `PROD_CHANGE_NOT_EVIDENCE`. The label is
  escalation policy in `gating.py`, which this PR does not touch; neither
  this PR's fixtures and tests nor #528's assert this finding's label, so
  the order the two merge in moves no pin.
- The honest cost of Q1 (a). A pytest file kept under `golden/`,
  `expected/` or `__snapshots__/` has the snapshot role and test
  obligations (#219), so the file-scoped form reads any edit to it as a
  rewrite. Adding a test there for a brand-new production module used to
  pass: the module's symbols silenced the form, and the new test unit
  silenced `SNAPSHOT_CODE_COCHANGE`. Now it blocks with
  `EXPECTED_VALUE_CHANGED` at high, and the reason above, that nothing in a
  brand-new file explains the rewrite, is untrue of it: the new module is
  what the new test exercises. Pinned as current behaviour, not as a
  judgement of the edit, by
  `test_a_test_added_for_a_new_module_to_a_pytest_file_under_golden`
  (`tests/test_issue463_snapshot_added_production.py`), with a control
  beside a changed existing symbol. The owner accepted the cost under
  Q1 (a) (below), to be named in the release notes and in
  `docs/KNOWN-ISSUES-next.md` and counted by the Q5 sweep; the
  alternative, not adopted, was to give it its own treatment, for example
  leaving the added-file exclusion out for a snapshot-role file with test
  obligations. By reading and not pinned, a module that an existing loader
  discovers with no existing file changed (a plugin directory scan) can
  honestly change a stored output too. The Q5 sweep is to count both.

**Residuals**, open by ruling and pinned as current behaviour, not as
honest edits (row 132): (1) a changed symbol in any existing or deleted
Python production file, `snapshot_unrelated_symbol_edit_neg` (Q2 (a));
(2) an edit to an existing production file checkwash cannot read,
`snapshot_template_comment_edit_neg` (Q3 (a)); (3) any test logic change
in the diff removes `SNAPSHOT_CODE_COCHANGE`, and with (1) or (2) nothing
is reported, `snapshot_unrelated_symbol_edit_new_test_neg` (Q4 (a)). The
cheapest full escape is now (3) with (1): a no-op `+ 0` in any existing
production function and a new test anywhere.

**Fingerprints and IR.** No fingerprint scheme changes: the newly raised
finding has the file-scoped content-bound v2 key the form always had
(`event: stored_expectation_rewritten`). `--emit-ir` gains
`globals.prod_symbols_in_added_files`, a new optional field, so
`IR_VERSION` stays 2 (`docs/stability.md`: no bump for a new optional
field); an IR without it counts every changed symbol, as before.

**Release.** The change newly blocks, so the release that ships it names
the newly blocking shape in its notes: a stored snapshot, golden or
expected file rewritten beside one or more new Python production modules
and no other production change that counts, including the honest edit
named above (a test added for a new module to a pytest file kept under a
snapshot directory), whose cost the owner accepted. The next release is
a minor anyway because of #421 (`docs/stability.md:17-22`). No release is
authorized (AGENTS.md rule 5). `docs/KNOWN-ISSUES-next.md` gains a #463
row, which names the same honest edit as an accepted cost.

**Rule 2.** The ruling names no change to an existing expectation, and the
change moves one:
`tests/test_snapshot_expectations.py::test_unrelated_production_change_retains_existing_snapshot_cochange_policy`
(PR #133's pin of the policy #129 kept) rewrites `tests/golden/invoice.txt`
beside an added `unused.py` holding `def unrelated(): return 3` and
asserted verdict pass and no `EXPECTED_VALUE_CHANGED`. Under Q1 (a) it
blocks, with `EXPECTED_VALUE_CHANGED` at high and `SNAPSHOT_CODE_COCHANGE`
at warn. The round stopped there: the test was left unchanged, and CI
showed it failing, and no other test, on every leg (runs 39215965313 and
39215965326). The owner approved the move as recommended (below), and
commit 6f6ad594 makes it: the test keeps its inputs, asserts the block and
both findings, and is renamed
`test_an_unrelated_new_production_function_does_not_explain_rewriting_the_stored_expectation`;
what its old name says about an existing module is pinned by
`snapshot_unrelated_symbol_edit_neg` and
`test_a_changed_symbol_in_an_existing_module_still_counts_beside_an_added_one`.
By reading, no other existing expectation moves: no `.gwcase` fixture,
demo case, verdict-gate case or corpus case rewrites a snapshot-role file
beside an added Python production file and nothing else that counts, and
nothing under `tests/gates` changes. If CI shows anything else moving, the
round stops.

**Measurement (Q5).** Not measured. The standard set and D-088's sets, any
verdict move stopping the round, pre-registered on a checkwash-lab branch
before any engine runs (D-048's method), and run on the pool; on
LAPTOP-01AGNPJU only under EC POLICY `checkwash-pju-sweep` (T-546), with
the frozen manifest and engine commit approved first. Under the owner's
consolidated ruling of 2026-10-19 (#419 issuecomment-6261642679), Q5's
sweep is not run on its own: it joins the combined sweep's one run, in
which this fix's merge gets its own before/after pair in the chain (R2),
and its manifest and engine commits are approved with the combined
manifest when that is frozen, in the second of R5's two approval steps.
By reading, a commit
can move only if it modifies a snapshot-role file, adds a Python production
file defining at least one symbol, and changes no symbol of an existing or
deleted Python production file and no production file checkwash cannot
read. Each such commit gains one `EXPECTED_VALUE_CHANGED` per modified
snapshot-role file. How many there are is unknown.
`NOT_RUN：工作機規則（POLICY work-machine-local），every effect above is read from source; no test, checkwash run or sweep was run`.

Evidence status: prepared on a work machine where no pytest, checkwash or
Python ran; CI runs the tests. Added: seven `.gwcase` fixtures with
owner-approved labels (`snapshot_new_prod_module_pos` and
`snapshot_new_prod_module_new_test_pos`, which carry `bypass: 132`;
`snapshot_new_prod_module_with_caller_neg`,
`snapshot_deleted_prod_module_neg`, `snapshot_unrelated_symbol_edit_neg`,
`snapshot_template_comment_edit_neg` and
`snapshot_unrelated_symbol_edit_new_test_neg`), and 24 collected items in
`tests/test_issue463_snapshot_added_production.py`. Not pinned: the E1
label of the new finding, the rename reading, `DEPENDENCY_DRIFT` beside an
added module, and the plugin-discovery shape. By reading, the documented
test count becomes 19650 (19619 + 24 + 7); CI's collection checks it.
When integration batch 2 merged, the four pull requests merged after this
one in it (#525, #527, #522 and #531) had taken it to 20083.
`benchmarks/FAILURES.md` was edited by hand to what
`benchmarks/make_failures.py` produces, by reading the generator.

The agent wrote this entry in #463's fix PR #524. The maintainer approved
it on 2026-10-19: 「PR 核可清單全部照建議」 ("the whole PR approval list as
recommended"), in reply to the agent's approval list, whose items for this
PR asked for: the one rule-2 move, re-pinning and renaming the test above
as recommended (A55); accepting the cost of Q1 (a), to be named in the
release notes and `docs/KNOWN-ISSUES-next.md` as drafted and counted by
the Q5 sweep, with the drafts that name it: the cost pin (dbcaa86b), the
detector comment (4b506f90), `docs/assertion-coverage.md` and the
`docs/KNOWN-ISSUES-next.md` row (ec6bd662), and the SPEC, row 132 and
entry drafts named under A58 (A56); the labels of the seven fixtures
(A57); the wording of SPEC §4 (59d13e77, 78e330e6), THREATMODEL row 132
as Partly closed (9666da66, 93b07116), this entry (24c1e6a0, dff4d5ff,
827bc03c), and the `docs/KNOWN-ISSUES-next.md` row and the note in
`docs/issue-remediation-2026-09-06.md` (e9b2f1ff), with the E1 label point
changed to name #473 instead of asking for a ruling (A58); and the
reading above of "a production file the diff adds" (A59). The reply was a
button whose text the agent wrote, which the owner chose. Commits
6f6ad594 (the move), 6fac1f98, 9a6615ff, 7c8e41b2, b598accd and e02b3f20
(the accepted cost) and 8c6492ad (the E1 label point) apply those
answers.

The owner approved the agent's second-round list on 2026-10-19:
「第二輪核可全部照建議」 ("the round-2 approval list, all as
recommended"). Its items for this PR asked for: approving together the
maintainer text written while applying the answers above, namely this
entry's Rule 2, cost and Release paragraphs (b598accd), the E1 label
point naming #473 (8c6492ad) and the approval record above (6baa4026,
bfa27ae7), and row 132's cost sentence changed from "for the owner's
decision" to "which the owner accepted" (7c8e41b2), with the detector
comment (9a6615ff) and the two comments in the #463 test file (e02b3f20)
changed with it (B3); and a sentence in the Measurement paragraph citing
R2 and R5, as D-155 does (B9). This reply too was a button whose text
the agent wrote, which the owner chose. Commit d56d7080 applies B9.
6fac1f98 changes the `docs/KNOWN-ISSUES-next.md` row in the same way as
row 132; B3 does not name it.

## D-159 (2026-10-19): the rebinding spellings #306 left out leave a helper method unresolved (#502)

Ruling 502 (owner, 2026-10-18, 「19 項全部照建議做（價值判斷的題也照你的傾向）」,
"all as recommended, value judgements included"). The go-ahead answered a
recommendation list prepared off GitHub, and #502's body, filed on it,
quotes it. It adopted the direction that list gave for this issue: complete
the literal-key spellings, read `vars(C)[...]` as `C.__dict__[...]` is
read, rule #487 first, and P2. The issue's Direction items 1 to 7 are the
agent's recommendation within that direction, for review in this PR.
#487's ruling (issuecomment-6248630528, item 2) settled what item 5 depends
on: (b) is not adopted. D-151 to D-163 were assigned to pull requests
prepared in parallel. When integration batch 2 merged, all of them were
on main except D-153, which is unused, and D-154, which is pending in
#511. This entry is D-159.

#502: since #306's fix (D-145, #476, `81c69d28`), Sub-Q3 leaves a helper
call unresolved when the module rebinds the helper's name, but the module
scan read only a `.<name>` store or del, a `.__dict__[...]` store or del,
an exact set of dotted setattr names (`_SETATTR`) with a literal name, or
with a computed one on the receiver or a class of the order by name,
`patch.object` and `monkeypatch.setattr`. So a `setUp` that runs
`self.__dict__.update({"_check": lambda value: None})`, or
`vars(self)["_check"] = fake`, a class body's `vars()["_check"] = fake`,
`self.__setattr__("_check", fake)`, or
`Alias = TotalTest; setattr(Alias, NAME, fake)`, left the call resolved:
the frontend followed the def while another function answered the call at
run time, so the helper's assertions stayed the unit's and nothing read
them as removed. #476 is in no tag and v0.8.0 follows no such call, so
this is an incomplete closure, not a regression from v0.8.0.

Implementation, in `frontends/python/self_methods.py` only (lines at this
PR):

- Item 1. A store into or del from `vars(x)[...]`, for any `x` and any key,
  joins the module-wide channel of `x.__dict__[...]` (`_object_namespace`,
  `:193-198`, used at `:427-429`): `dict_store` leaves every helper name in
  the module unresolved (`resolve`, `:681`). `vars(C)[...]` on a class
  raises at run time, since a class's `vars()` is a read-only mappingproxy.
  So does the pinned `TotalTest.__dict__["_check"] = print`, already read
  as a rebinding, and #422's reader treats the two alike
  (`exit_status_controls.py:810-814`). Narrowing the channel to the literal
  name is not part of #502.
- Item 2, name-specific as Sub-Q3. Each spelling adds the name to `stored`,
  which leaves that name unresolved for every class of the module
  (`_namespaces`, `:462-504`; `_namespace_call`, `:506-537`; `_key`,
  `:539-545`):
  - a call whose last name is `__setattr__` or `__delattr__`
    (`_DUNDER_SETTERS`, `:125`; `:510-518`), by its name argument. A bound
    call carries the name at index 0 (`self.__setattr__("_check", f)`,
    `super().__setattr__(...)`), an unbound one at index 1
    (`type.__setattr__(C, "_check", f)`, `object.__setattr__(...)`), and
    the count of positional arguments tells them apart: two bound and three
    unbound for `__setattr__`, one and two for `__delattr__`, which takes
    no value. So `self.__setattr__(NAME, "x")` is read by `NAME`, never by
    its value. The draft read the first str literal among the first two
    arguments, as #422's `_setter` reads its status names
    (`exit_status_controls.py:839-851`), and so took that call's `"x"` as
    the name; raised by GLM, verified by Claude;
  - on `x.__dict__` or `vars(x)` (with an argument), the keywords of
    `update()` and the str-literal keys of a dict literal passed as its one
    positional argument (`:524-532`), and the literal key of `setdefault()`
    (`:533-534`);
  - in a class body, a literal key of `vars()` or `locals()` with no
    argument (`_class_namespace`, `:201-208`), stored or deleted
    (`:481-483`). A node's scope is read by `_scoped` (`:211-227`): the
    def, lambda or class whose body holds it, where a header (`_header`)
    runs in the scope that holds the def, as D-149's `_module_binds` reads
    it.
- Item 3. These leave every name in the module unresolved (`dict_store`):
  in `update()`, a `**` argument, a positional argument that is no dict
  literal, a second positional argument, or a `**` entry or a key that is
  no str literal in the dict literal; a key of `setdefault()`, or of a
  class body's `vars()` or `locals()`, that is no str literal; a
  `__setattr__` or `__delattr__` whose name argument is no str literal, or
  with a starred argument or a count that is neither form's; and a store
  or del of `x.__dict__` itself, `x.__dict__ = ...` and
  `x.__dict__ |= ...`, read as `__dict__` in `stored` (`:435-438`), which
  also takes `del x.__dict__` and a literal-name setattr or patch of
  `__dict__`.
- Item 4. A computed-name `setattr` or `delattr` (`_SETATTR`, `:113-114`)
  also records the name `_target` reads from its target (`:230-244`): `x`
  for `x`, `x.attr`, `x.__class__` or `type(x)`, as `_root` reads them. It
  is followed one hop through a plain assignment of that name (annotated
  or walrus too) whose value is one the ruling names: a name, `type(x)` or
  `x.__class__` (`_alias`, `:247-259`). The name is looked up as Python
  looks a name up: in the call's own scope, the defs and lambdas around
  it, and the module (`:492-504`). So a module-level or function-local
  `x = C` counts as `C`, and `x = type(self)` or `x = self.__class__` as
  the receiver, as the direct `setattr(type(self), NAME, f)` is read
  (D-145; reading 7). A target reached through a subscript or another call
  (`globals()["C"]`, `sys.modules[__name__].C`, `make()`) counts as every
  class in the order (`any_class`, `:496`, read at `:697`). The reading in
  `_call` (`:443-460`) stays.

Readings where the ruling is silent; the owner approved each as written
(below). 1 to 4 err toward unresolved, 5 and 6 toward resolved, 7 both
ways:

1. `__setitem__` and `__delitem__` called on `x.__dict__` or `vars(x)` are
   read as the item store and del they spell, so every name, as item 1
   (`:535-537`); called on a class body's `vars()` or `locals()`, as its
   item store, name-specific.
2. A class body's `vars()` and `locals()` are read as `x.__dict__` is for
   `update()` and `setdefault()` too, by name.
3. A `setattr` or `delattr` whose target or name is a starred argument
   (`setattr(*(C, "_check", f))`) leaves every name unresolved
   (`:487-489`); before, it was not read.
4. The alias lookup also reads the defs and lambdas around the call (a
   nested `install()` in `setUp` that reads the `setUp`'s
   `klass = type(self)`), beyond the ruling's "module-level or
   function-local". A comprehension is read as part of its scope, so a
   `vars()` or `locals()` in a class-body comprehension is read as the
   class's namespace.
5. `vars()` and `locals()` outside a class body rebind no method: at
   module scope they are the module's namespace and in a function its
   locals, neither of which holds the class's methods, so neither a literal
   nor a computed key there is read (`:481-483` and `:521` read only a
   class body).
6. Only the alias values the ruling names are followed: `x = C`,
   `x = type(self)` and `x = self.__class__` (`_alias`). Any other value
   is not: an attribute (`cfg = self.settings`, `x = C.attr`), a call
   (`obj = Fake()`) or a subscript (`x = globals()["C"]`). Following
   `cfg = self.settings` as `_target` reads a direct target would make the
   common `cfg = self.settings; setattr(cfg, key, value)` leave every
   `self.<helper>()` call in the module unresolved, and reading a value
   that is no name as every class would do the same for
   `obj = Fake(); setattr(obj, key, value)`; both are pinned resolved. The
   direct target keeps D-145's reading, so `setattr(self.settings, key,
   value)` still counts as one on `self` while its aliased spelling does
   not. The owner kept this asymmetry and left `x = globals()["C"]` a
   residual (below).
7. The ruling says `x = type(self)` and `x = self.__class__` count as `C`.
   They are read under the name inside them, the receiver's, as the direct
   `setattr(type(self), NAME, f)` is: a call through a receiver of that
   name stays unresolved in every class of the module, which is wider than
   `C`'s order, and a unit whose receiver has another name is not reached,
   which is narrower.

`pop()`, `popitem()` and `clear()` are not read (`:119-123`): on an
instance's namespace a deletion shows the class's def again, and on a
class's mappingproxy it raises. In a class body, `vars().pop("_check")`
removes the def; that stays a residual.

**Stated cost, accepted (item 5).** A change that adds one of these
spellings leaves the helper resolved at the parent and unresolved at the
commit, so the assertions followed through it read as removed
(`ir/diffalign.py:122-136`; ASSERT_REMOVED at warn,
`detectors/assert_removed.py:27`, raised to high under
NO_PROD_CHANGE_IN_DIFF, `gating.py:888` and `:917`), as the spellings
caught before already do.
That is what catches the issue's evasion
(`self_method_dict_update_rebinding_pos`). Under items 1 and 3, an
innocent write added anywhere in the test module leaves every helper
unresolved on the head side and reads the same way: `vars(self)["data"] =
1`, a non-literal `update()` such as a class whose `__init__` runs
`self.__dict__.update(attrs)` (`self_method_namespace_update_added_pos`),
a `super().__setattr__(name, value)` in a fake's `__setattr__`, or a
`setattr` on `globals()[...]`. In a module whose base already has such a
write, the #306 closure is lost on both sides; that is a missed detection,
not a block. Removing such a write reads nothing as removed. This
detection depends on #487's option (b) not being adopted; the owner did
not adopt it (D-149), and if (b) is ever reconsidered, this detection goes
with it. Reading every reflective spelling as module-wide unknown (D-095's
reading) is not proposed: it would reverse D-145's ruled name-specific
choice, and it would cost more.

Residuals, by kind (D-145 and D-149 name the others), each leaving the call
resolved as before this entry: an aliased `setattr` (`s = setattr`) and an
alias more than one hop away, which the issue names; an alias bound other
than by a plain assignment (a `for` or `with` target, an unpacking) or to
another value; an alias assigned in a def that declares it `global`
(`def bind(): global Alias; Alias = TotalTest`), which a computed-name
`setattr(Alias, NAME, f)` at module level or in a def outside that one
does not follow, since an alias is keyed by the scope its assignment is
written in (`:477-480`, `:499-504`), and which works only once that def
has run (raised by GLM, verified by Claude); a computed-name `setattr` whose
target is a parameter that holds the class (a `setUpClass`'s `cls`, or
`def install(target)` called with the class); `pop()`, `popitem()` or
`clear()` on a class body's namespace; and a namespace written through
`monkeypatch.setitem`, `operator.setitem`, `patch.dict`, an unbound dict
method (`dict.update(self.__dict__, ...)`), or `vars` or `locals` under
another name.

Rule 2. The ruling approves no change to an existing expectation: by
reading none moves, and none was changed.
`tests/test_issue306_self_methods.py` is unchanged; its sources that use a
newly read spelling (`pytest.mark.__setattr__('slow', wrap)`,
`vars(pytest.mark).update(slow=wrap)`,
`type.__setattr__(MarkDecorator, '__call__', wrap)`, and a class's
`__setattr__` that calls `object.__setattr__(self, name, value)`) already
expect the call unresolved. The `.gwcase` fixtures that write through
`vars(...)` (`conftest_request_module_vars_store_pos`,
`conftest_setitem_vars_request_module_pos`) do so in a conftest, where no
helper method is resolved, and no other fixture uses a newly read spelling
beside a helper method reached through `self`. The other inline sources
under `tests/` with these spellings
(`test_issue254_class_attribute_guards.py:522`, `test_issue422_exit_status.py`,
`test_issue432_noop_replacement.py`, `test_issue_runtime_acceptance.py`,
`test_param_input_identity.py`, `test_standin_installations_main.py`,
`test_subject_helper_dispatch.py`, `test_subject_helper_module_authority.py`,
`test_truthiness_oracles.py`) call no helper method through `self`.
Nothing under `tests/gates` changed. If CI shows an existing expectation
moving, the round stops and lists each for the owner, as D-141 did.

**Fingerprints and IR.** No fingerprint scheme, IR field or key changes.
Fewer calls resolve, so `--emit-ir` loses `via` assertions and
class-qualified `helper_calls` keys for helper methods in modules with a
newly read spelling (not measured).

**Release.** #476 is in no tag (v0.8.0 is from 2026-10-15), so this
changes no released behaviour. Under R1 of the owner's consolidated ruling
of 2026-10-19 (「裁決總表全部照建議」, recorded across issues on #419,
issuecomment-6261642679), v0.9.0 includes #502, which stays P2 (item 7),
and this fix merges before the combined sweep freezes. No release is
authorized (AGENTS.md rule 5): v0.9.0 still needs the owner's one-time
named authorization.

**Measurement (item 6).** Not measured yet. After the fix merges, the
standard set and D-088's sets are rerun before and after where the owner
approves, as a checkwash-lab-declared run: on LAPTOP-01AGNPJU only under
EC POLICY `checkwash-pju-sweep` (T-546), with the frozen manifest and
engine commits approved first, otherwise on the pool. The measured cost of
item 5 goes here once the rerun has run.
`NOT_RUN：工作機規則（POLICY work-machine-local），every effect above is read from source; no engine, engine variant, test, sweep or IR emission was run`.

Evidence status: prepared on a work machine where no pytest, checkwash,
product or test code ran; CI runs the tests. Added: three `.gwcase` fixtures
(`self_method_dict_update_rebinding_pos`,
`self_method_namespace_update_added_pos`,
`self_method_other_name_update_neg`), whose labels the owner approved
(below), and 75 collected items in
`tests/test_issue502_helper_rebinding_spellings.py`, counted from its
parametrize lists; no existing test changed. By reading, the documented
test count becomes 19609 (19531 + 75 + 3); CI's collection checks it.
The base, 19531, is main's 19505 and the 26 items of #509, which merged
before this pull request in integration batch 2. When that batch merged,
the six pull requests merged after this one in it (#528, #524, #525, #527,
#522 and #531) had taken the count to 20083.

The agent wrote this entry in #502's fix PR #520. On 2026-10-19 the
maintainer approved items A44 to A49 of the agent's approval list:
「PR 核可清單全部照建議」 ("the PR approval list, all as recommended").
Those items approve, for this PR: the wording of SPEC §3 (75f35ca7,
2e822f1e, c583ab02), THREATMODEL row 91 (4cf15200, bd8d3ab8) and this
entry (39aad0bc, 625e5640, f55f6093) as committed, with the Release
paragraph to be brought in line with R1 and the residual lists to be
completed before merge (A44); the three fixtures' labels (A45, 09ccc6ba);
readings 1 to 5 (A46); reading 7 (A47); reading 6, with the asymmetry
between a direct and an aliased target kept and `x = globals()["C"]` left
a residual (A48); and, for `__setattr__`, reading the name argument at
index 0 of a call with two positional arguments and at index 1 of one
with three, with this entry's reading changed to match (A49). The reply
was a button whose text the assistant wrote. The changes A44 and A49 ask
for were made after the reply: the code and its pins (27c42fd2,
f6974b13), SPEC §3's residual sentence (fa236589), row 91 (a2e968a0) and
this entry (a2a6727f, efa57c35). Made with them, and not covered by those
items: the same rule for `__delattr__`, with one and two arguments;
leaving every name unresolved for a dunder setter with a starred argument
in any position, where the draft looked only at the first two, or with a
count neither form takes (items 2 and 3; 27c42fd2, a2a6727f); and SPEC
§3's sentence that reads the name argument by the count (9c8c794b). A
residual raised after the reply, an alias a def assigns under `global`
(9b0d8661), was taken out again (b2f0f052) until its wording was approved.

What was written or left open after that reply was approved later the
same day: 「第二輪核可全部照建議」 ("the round-2 approval list, all as
recommended"), in reply to the agent's round-2 list (items B1 to B25).
Item B3 approves, as one, the maintainer text the agent wrote while
applying approved options; for this entry it names the approval record
above (1d11fe24, a2dd63aa). Item B7 approves what A49 did not cover: the
`__delattr__` rule, every name left unresolved for a starred argument or
another count, SPEC §3's sentence (9c8c794b) and the module docstring as
changed with them (27c42fd2), and adds a dunder setter with a starred
argument or an argument count neither form takes to SPEC §3's list of
writes that leave every name unresolved (27a36315), which the module
docstring now says too (b34a9c2f, its line count kept). Item B8 approves
the `global` alias residual in this entry and adds one sentence for it to
row 91's "Still not read", with SPEC §3 unchanged, so SPEC §3's residual
sentence does not name it. B8 described the residual as written in this
entry only, as it had been until b2f0f052, so 9b0d8661's wording is
restored (6ef73158) and row 91 gains its sentence (1320f3cc). This
paragraph, and the rewording of the one above to say only what items A44
to A49 say, were also written after that reply. That reply, too, was a
button whose text the assistant wrote.

## D-161 (2026-10-19): E1 says PROD_CHANGE_NOT_EVIDENCE when the diff changed production (#473)

Ruling 473 (owner, 2026-10-18, 「19 項全部照建議做（價值判斷的題也照你的傾向）」,
"all as recommended, value judgements included"; #473
issuecomment-6248629776, which states each decision in full, as the list it
answers went to the owner off GitHub). Its direction, Q1 (b), was ruled in
#471 (Q5 (b), issuecomment-6230178131, item 5). The owner put #473 in
v0.9.0's scope on 2026-10-19 (owner ruling 2026-10-19, R1). D-151 to
D-163 were assigned to pull requests prepared in parallel. When
integration batch 2 merged, all of them were on main except D-153, which
is unused, and D-154, which is pending in #511. This entry is D-161.

#473: E1 escalates an oracle finding that has no repair evidence and that no
de-escalator holds. Its label `NO_PROD_CHANGE_IN_DIFF` is true when the diff
changes no production file. It was also printed when the diff does change
production and the finding's evidence does not reach the change. There the
sentence is false, and it sends the reader to look for a production change
that is already there. `EXPECTED_VALUE_HARDCODED` fires only when production
changed, so the label was false on every block of that rule (#471). #420
reports the same sentence for a weakened test of a top-level callee. The
scrapy commits `fada8be1db` and `c76190d491`, recorded on the issue, and
earlier commits of at least five other upstream repositories printed it too.

**The decisions:**
- **Q2, the condition, amended from #471's "readable Python production
  file".** The new label applies when the diff changes a production-role file
  (`ir.globals.prod_files_changed`) that is not inert (`roles._is_inert`:
  `.gitignore`, `LICENSE*`, `.pyi` stubs, `mkdocs.yml`, `CODEOWNERS` and the
  rest of that list). `engine.py:1384` records each production-role path
  before the branches that decide symbol or opaque evidence, so a production
  file that stops parsing, an added or deleted non-Python file, one renamed
  without a byte change, and a non-Python production file whose content runs
  the test suite take the new label when no earlier label applies. A
  non-Python file renamed with a byte change from a production path outside
  the test-support directories is an opaque change, as a modified one is
  (`engine.py:1498-1513`), so a finding gets repair evidence from it or
  `OPAQUE_PROD_CHANGE_NOT_EVIDENCE`, not the new label. Inert files change
  no runtime behaviour by the engine's own list, so a diff that changes only
  those keeps the old label. Changes set aside unread (#415) and generated
  artifacts never reach
  `prod_files_changed`; "unread" stays #448's word.
- **Q3, the name: `PROD_CHANGE_NOT_EVIDENCE`.** It is true over every diff
  Q2 covers and parallels `OPAQUE_PROD_CHANGE_NOT_EVIDENCE`.
  `PROD_CHANGE_NOT_REACHED` is false over `trivial_prod_change_pos`, whose
  test calls the very function the diff edits, and `NO_RELEVANT_PROD_CHANGE`
  claims the change is irrelevant.
- **Q4, rule 2: named approvals, in D-141's form.** Four new pins are
  approved. No move of an existing pin is approved in advance: the
  implementer stops when CI on the fix PR shows them and lists each one, old
  and new label, for the owner's approval by name. Inputs, severity and
  de-escalators stay as they are.
- **Q5.** This entry, SPEC §5's E1 row, the `gating.py` label chain and its
  comment (frozen zone) and THREATMODEL row 86h are drafts for the owner's
  approval of the wording. Dated records keep their text
  (`docs/integrations.md`, `docs/launch.md`, `docs/releases/`, `STATE.md`,
  `benchmarks/`). No sweep for the label alone, no `FINDINGS_VERSION` or
  `IR_VERSION` bump, and no version bump of its own.
- **Q6.** The label does not lift #488's block: scrapy `fada8be1db`'s six
  findings stay high under any label, and their cause is #488's question.

**Implementation**, in `src/checkwash/gating.py` (lines at this PR).
`apply_gates` computes `prod_changed` once (`:543-553`): true when any path
in `ir.globals.prod_files_changed` is not inert (`_is_inert`, imported from
`roles.py` at `:24`, as `engine.py` imports it). The E1 label chain
(`:925-948`, with its comment) is now: an unguarded suite control with
evidence or any production-role file, `COLLECTION_CONTROL_UNEXPLAINED`;
else a refused opaque change, `OPAQUE_PROD_CHANGE_NOT_EVIDENCE`; else
`prod_changed`, `PROD_CHANGE_NOT_EVIDENCE`; else `NO_PROD_CHANGE_IN_DIFF`.
The new label comes after both existing ones, which keep their conditions:
`COLLECTION_CONTROL_UNEXPLAINED` keeps D-066's test, inert files included,
and `OPAQUE_PROD_CHANGE_NOT_EVIDENCE` is unchanged, so no pin of either
moves. Nothing outside `gating.py` changes, and the IR does not change.

**This amends and settles.** It amends 419.Q5 (`DECISIONS.md:48-51`),
"`NO_PROD_CHANGE_IN_DIFF` is unchanged otherwise": that label is now kept
only for a diff that changes no production-role file, or only inert ones.
It settles the unit-level wording that D-066 left "not decided here"
(`DECISIONS-archive-1.md:2344-2347`). One report can still carry two labels: a suite
control beside only an inert file says `COLLECTION_CONTROL_UNEXPLAINED`
(D-066 counts inert files), and a unit finding in the same diff says
`NO_PROD_CHANGE_IN_DIFF`.

**Existing pins that move.** CI on 4352949c (ci run 39219097422, every
test job, and docs suite run 39219097558) failed on exactly the 34 test
items below (33 fixtures with 34 findings, and one pytest row) and on no
other, the same set in every job, each printing the same findings with
only the label changed. A fixture's failure reports only its first
unmatched expectation (`cases.match_expectations`), so the second finding
of `js_test_in_expected_dir_weakened_with_prod_edit_pos` shows its new
label in the printed actuals. The owner approved each move by name
(below), and this PR re-pins all 35 expectations in one commit
(353e91d4). Each moves from `NO_PROD_CHANGE_IN_DIFF` to
`PROD_CHANGE_NOT_EVIDENCE`, with its inputs, severity and de-escalators
unchanged:
- A readable Python production edit or deletion that the finding's evidence
  does not reach (19 fixtures, 20 findings): `dead_prod_line_pos`,
  `deleted_prod_unrelated_pos`, `evidence_annotation_neg`,
  `evidence_dead_local_neg`, `evidence_string_stmt_neg`,
  `expectation_definition_package_unrelated_pos`,
  `js_test_in_expected_dir_weakened_with_prod_edit_pos` (two findings; it
  carries pin 3's shape, see below),
  `leaf_name_collision_pos`, `package_repair_needs_modified_symbol_pos`,
  `prod_reorder_pos`, `prod_symbol_added_only_pos`,
  `prod_symbol_removed_marker_pos`, `prod_symbol_removed_unrelated_pos`,
  `python_test_in_golden_weakened_with_prod_edit_pos`,
  `repair_via_helper_unrelated_pos`, `root_import_sibling_sameleaf_pos`,
  `row36_file_scoped_no_sibling_evidence_pos` (its `BROAD_EXCEPT_ADDED`),
  `srclayout_sibling_module_pos`, `trivial_prod_change_pos`.
- A production change checkwash reads no symbols from (3):
  `unparseable_self_inflicted_pos` (a file that stops parsing),
  `opaque_deleted_file_not_evidence_pos` (a deleted data file),
  `opaque_new_file_not_evidence_pos` (an added data file).
- A JS setup file or `package.json` that the role table makes production
  and whose content names a test runner, so it is no opaque change (7). In
  each, the finding's stand-in is installed in such a file (#218), and the
  diff changes no other production-role file:
  `js_cra_setup_tests_mock_pos`, `js_package_json_automock_pos`,
  `js_setup_file_added_with_listing_pos`,
  `js_setup_file_enable_automock_pos`, `js_setup_file_listed_spy_pos`,
  `js_setup_file_mock_pos`, `js_vitest_setup_mock_pos`.
- Production files present with byte-identical sides (4):
  `expected_call_to_literal_pos`, `expected_call_to_twin_pos`,
  `unittest_literal_first_pos`, `unittest_trivial_pad_pos`. The fixture
  harness passes such a file as a modification (`cases.case_to_changes`),
  and the engine records it in `prod_files_changed`, so by the ruled
  condition they move. A Git diff does not list an unchanged file, except
  for a mode-only change. In these fixtures' own terms the new sentence is
  false, and the ruling's size estimate expected unchanged paths not to
  move. Their label is an artifact of the fixture harness, not a claim
  about a real diff, and their moves are approved as such (below).
- One pytest row:
  `tests/test_test_support_paths.py::test_test_data_moved_into_production_was_not_production_at_base`
  (`src/__tests__/data.json` renamed to `src/data.json`: the new path is
  production-role, and the rename buys no opaque credit).

These keep the old label by reading, as the ruling says: the unread rows of
`tests/test_issue415_oversized_sources.py` (`:145-151`, `:532-537`; the
`image_added` row is also a generated artifact),
`tests/test_issue419_opaque_refusal.py:100-103`, and the six
`src/checkwash/demo_cases` that pin the label, which change only tests.
`inert_doc_change_pos` (`mkdocs.yml`), `stub_change_pos` (a `.pyi` stub)
and `artifact_cannot_disarm_pos` (a `.pyc`) hold the inert and artifact
edges. Every other pin of `NO_PROD_CHANGE_IN_DIFF` that names a non-test
path changes no production-role file by reading: the path is a JS/TS test,
a file beneath a test-support directory, a file the role table gives
another role directly (`ci`: `pyproject.toml`, a `Justfile`, a composite
action's `action.yml`; `lockfile`: `requirements.txt`; `guardrail`:
`.greenwash/allow.toml`), a runner script or test command promoted to
`ci`, or, in the pytest and e2e rows, a test relocated out of collection
(`renamed_from_test`; a `.gwcase` cannot express a rename, since
`cases.case_to_changes` sets no `old_path`).

**Not settled by the ruling; the owner decided it (below):** the four
byte-identical fixtures. Their moves are approved, and their new label is
recorded as a harness artifact (above). The engine does not skip a
byte-identical change when it records `prod_files_changed`: that option
was wider than this ruling, since D-066's label and
`SNAPSHOT_CODE_COCHANGE` read the same list and the IR would change.

**Settled by Q2:** the seven JS setup-file fixtures take the new label, as
Q2 says a production file that runs the test suite does. Their only
production-role changes are the carrier the finding reports and, in
`js_setup_file_added_with_listing_pos`, the `package.json` that lists it,
so the sentence points the reader at the stand-in itself. The approval
list recorded this as settled by Q2 and asked nothing about it; the owner
approved the seven moves by name with the rest (below).

**Residuals, stated.** The label says that production changed and that no
evidence the finding may take reached it; it does not say why. A production
file renamed into a non-production role (beneath a test-support directory,
or into `tests/`) is recorded under its new path only, so the old label
stays although production lost a file
(`test_production_moved_beneath_a_test_support_directory_buys_nothing`,
unchanged); D-066's label has the same edge. A mode-only change of a
production file counts as a production change.

**Contracts.** The label is chosen after `f.severity = "high"`
(`gating.py:900`, `:940-948`). Fingerprints are computed by the detectors
before gating runs, and none of `make_fingerprint`,
`make_assertion_fingerprint` or `make_change_fingerprint` reads escalators
(`findings.py:162-166`, `:367-369`, `:396-413`). So severity, verdict,
de-escalators and fingerprints do not move. No `FINDINGS_VERSION` or
`IR_VERSION` bump: the label is a new value in the existing `escalators`
list, as in D-066 and D-141 (`DECISIONS.md:239-242`), and
`docs/stability.md` does not freeze escalator strings. Nothing newly blocks
or passes. The change ships in the next authorized release, with one
release-note line that names the new label; no release is authorized
(AGENTS.md rule 5).

**Tests and fixtures.** Three new `.gwcase` files, pins 1, 2 and 4 of the
four Q4 approves, none with a `bypass:` line:
- Pin 1, `prod_change_not_evidence_hardcoded_pos`: #471's `pricing`
  example, `EXPECTED_VALUE_HARDCODED` high with the new label beside
  `EXPECTED_VALUE_CHANGED` warn with `PACKAGE_REPAIR`. If #471's fix
  (#522) merges first and brings `hardcoded_package_only_pos`, the same
  shape, this pin is dropped (Q4), and that fixture's
  `EXPECTED_VALUE_HARDCODED` expectation moves from
  `NO_PROD_CHANGE_IN_DIFF` to `PROD_CHANGE_NOT_EVIDENCE` without a further
  stop. If this PR merges first, #522's `hardcoded_package_only_pos` takes
  the new label in #522 at its merge, also without a stop. The owner
  approved that move by name in advance, whichever PR merges first
  (below).
- Pin 2, `prod_change_not_evidence_unchanged_caller_pos`: #420's
  reproduction with `render` in an unchanged module, `ASSERT_WEAKENED` high
  with the new label.
- Pin 4, `no_prod_change_unchanged_caller_pos`: the test-only twin of pin 2,
  which keeps `NO_PROD_CHANGE_IN_DIFF`.

Pin 3, a JS/TS test weakened beside a Python-only production edit, is not
added: `js_test_in_expected_dir_weakened_with_prod_edit_pos` already has
that shape (a `node:test` file weakened beside a Python-only edit to
`app/util.py`), so by Q4 no duplicate is added and that fixture's move,
listed above, went to the stop and was approved by name.

Seven collected items in `tests/test_issue473_e1_label.py` pin the edges: an
inert file alone (`LICENSE`, `.gitignore`, `CITATION.cff`) keeps the old
label; an inert file beside a readable production edit, and a production
file whose content names a test runner, take the new one; a refused opaque
change keeps its label beside a readable edit; and an unguarded suite
control beside only an inert file keeps `COLLECTION_CONTROL_UNEXPLAINED`.
None is under `tests/gates`. By reading, the documented test count becomes
19619 (19609 + 10: three fixtures, each one item of
`tests/test_cases_runner.py::test_case`, and seven items); the re-pins add
none. On this PR's own base, CI on 4352949c collected 19485 (19475 + 10).
When integration batch 2 merged, the five pull requests merged after this
one in it (#524, #525, #527, #522 and #531) had taken the count to 20083.

**Sweep.** None for the label alone, as ruled: CI on the PR is the check. A
later acceptance sweep that compares escalators reports label-only
differences as their own class.
`NOT_RUN：工作機規則（POLICY work-machine-local），every behaviour above is read from source and no test, checkwash run or sweep was run on the work machine; the list of moving pins and the count collected on this PR's own base are the ones CI on 4352949c showed`.

The agent wrote this entry in #473's fix PR #528. The maintainer approved
it on 2026-10-19: 「PR 核可清單全部照建議」 ("the PR approval list, all as
recommended"), in reply to the agent's approval list of that day, which
went to the owner off GitHub. For this PR it covers items A50 to A54:
each move by name of the 34 test items CI failed on (33 fixtures with 34
findings, and one pytest row), once CI showed exactly those (A50;
re-pinned in 353e91d4); the four byte-identical fixtures' moves,
recorded as a harness artifact (A51); moving `hardcoded_package_only_pos`
to the new label in advance without a stop, whichever PR merges first,
with pin 1 dropped if #522 merges first (A52); the labels of the three
new fixtures (A53, ee35d145); and the wording of the `gating.py` label
chain and its comment (e33845eb), the SPEC §5 E1 row (0a3d0f53),
THREATMODEL row 86h (0b334f2f) and this entry (88b6b33a, 4017d0e5,
3b6583ad), with this entry's number and the test count renumbered in
merge order at merge time (A54). The reply was a button whose text the
agent wrote, which the owner chose. 260466d7, the commits after it and
this paragraph record it. Their sentences in this entry (the CI result,
the harness-artifact sentence, the order clauses for #522, the "Settled
by Q2" paragraph, the pin 3 and test-count sentences and this paragraph)
were written after the reply and were not on the list.

The maintainer approved further text and changes on 2026-10-19:
「第四輪 D1～D10 全部照建議」 ("the round-4 list D1–D10, all as
recommended"), in reply to the agent's round-4 list. The reply was a
button whose text the assistant wrote, which the owner chose. Its items
for this entry: D1 approves by name the fifteen moves this PR's label
caused in integration batch 2 (#533), after this PR merged, in the new
fixtures and tests of later pull requests, beyond the moves A50 and A52
named: eleven expectations in ten `.gwcase` fixtures (#527's
`subject_pairing_other_subject_known_limit_pos` and nine of #522's) and
four in three items of `tests/test_issue471_fixture_producers.py`, each
from `NO_PROD_CHANGE_IN_DIFF` to `PROD_CHANGE_NOT_EVIDENCE` with rule,
severity and unit unchanged (D-155, D-156). D2 approves the count
sentences above as 9c19c344 rewrote them, once the merge-order
renumbering had made the old clause false, with the NOT_RUN reason's
"the count collected on this PR's own base"; the sentence after them was
rewritten under D3 in integration batch 3 (cecba56e). D4 keeps pin 1,
`prod_change_not_evidence_hardcoded_pos`, beside
`hardcoded_package_only_pos`, the same shape: this PR merged before
#522, and A52 drops pin 1 only if #522 merges first, so pin 1's bullet
above stands as written. D5 adds one sentence to the `gating.py` E1
comment approved under A54, naming #522's fixture-producer evidence; it
changes the comment only (4a87d143, in integration batch 3). This
paragraph was written after the reply.

On 2026-10-20 the owner approved the paragraph above with
「第七輪 H1～H5 全部照建議」 ("round 7, H1 to H5, all as recommended"), a
button whose text the assistant wrote: its item H2 approves together the
round-4 and round-6 approval records, the C1/D3 rewrites at merge and the
batch-4 merge sentences it lists. This sentence was written after the
reply.

## D-163 (2026-10-19): in Python, a handler assertion proved to always pass is not inspection, refining D-015 (#496)

Ruling 496 (owner, 2026-10-19, 「裁決總表全部照建議」, "the consolidated
ruling list, all as recommended", in reply to the agent's list of 104
decisions; the reply was a button whose text the assistant wrote; #496
issuecomment-6261652527 states each decision in full) adopted, for this
issue: R31 (Q4 (a), a throwaway hosted draft PR before any fix), R32 (Q5,
the measurement plan), R35 (closing time), R49 (Q1 (a) with three
conditions), R50 (Q2 (b), a separate evidence text), R51 (Q3 (b), a
separate narrow proof) and R66 (an unreachable oracle in a handler is not
fixed in this round). 431.Q2 (#431 issuecomment-6170356603) had ruled the
Python counterpart a separate issue and PR in the 1.0 scope, filed as P1
after a reproduction, in which a handler assertion stops counting only
when proved to always pass, not on the TAUTOLOGY rating.

#496 reports that in a Python test file or conftest, a broad handler on a
`try` whose body holds an oracle was added to `swallowing_handlers` only
when it neither re-raised nor held an oracle, and that any `assert`
statement and any `assert*`, `fail` or `raises` call counted as an oracle,
even one that cannot fail. Adding `assert True` to the handler therefore
turned row 16's `BROAD_EXCEPT_ADDED` block back into a clean pass. The
hosted reproduction (R31) ran on draft PR #518, closed unmerged: run
39215282880, `pull_request` event, head `ae7deb49` on main `0e60832a`,
pytest 9.1.1 on all nine `test` legs, each with a full summary. On every
leg each of the four new cases failed with `expected 1 finding(s), got 0:
[]`: `except AssertionError: assert True` (the issue's pair), `except
Exception: assert 1 == 1`, a bare `except: assert True`, and `except
Exception: self.assertTrue(True)` in a `unittest.TestCase` method. It was
read as #518's body says (A87, below) and recorded on #496
(issuecomment-6263372986). All four reproduced, so under R31 the fix is
written and covers all four.

**D-015, refined.** D-015 froze that, in a test file, a broad handler
counts only when the guarded block holds an oracle and the handler neither
re-raises nor asserts; D-138 refined "asserts" for JS/TS only. In Python,
"asserts" now means "holds an oracle not proved to always pass".
Production files keep comparing every broad handler (`broad_handlers`),
unchanged.

Implementation, in `src/checkwash/frontends/python/frontend.py` only (lines
at this PR):

- R51. The proof is its own set of helpers (`:2482-2742`), and
  `_static_truth` (`:2385-2444`), which folds `if` guards, is unchanged.
  That folder answers True where a pass proof must not: `_truthy_literal`
  returns True when `literal_eval` fails (`:2475-2479`), so `assert -"a"`,
  which raises TypeError, would read as passing; and an `or` with one True
  operand folds to True, so `assert check() or True`, which runs `check()`
  first, would too. The proof shares `_is_literal` (`:373`) and `_CMP_OPS`
  (`:2370`) and answers only "proved to pass" or nothing (`_UNPROVED`); an
  unknown keeps the exemption.
- R49, `assert`. `_proved_value` (`:2577-2599`) evaluates a literal
  (`_is_literal`, read by `literal_eval`; `_proved_literal`,
  `:2534-2541`), `not` before a literal, a comparison between literals by
  `_CMP_OPS`, or by `is` and `is not` only when one side is None
  (`_proved_comparison`, `:2549-2574`), and `and` or `or` over these. Every
  operand of `and` and `or`, and every link of a chained comparison, is
  evaluated on its own, so no short circuit decides; Python's own result is
  then taken. A `literal_eval` failure (`-"a"`, `{[1]: 2}`) or a comparison
  that raises (`1 < "a"`) is unknown. The assertion passes when the value
  is truthy. Its message is not read, since Python evaluates it only on
  failure.
- R49, unittest. `_proved_unittest_call` (`:2602-2645`) reads
  `assertTrue`, `assertFalse`, `assertIsNone`, `assertIsNotNone`,
  `assertEqual` and `assertNotEqual` (`_PROVED_UNITTEST`, `:2503-2510`,
  each with the predicate `Lib/unittest/case.py` applies; `assertEqual` on
  two values of one type dispatches to a type-specific method, and each of
  unittest's own passes when `==` holds, which reading 7 relies on).
  Condition one: the call passes the method's operands and at most one
  `msg`, by position or by keyword, and nothing else, with no `*` or `**`;
  the operands are bound by `_unittest_operands` (`:1616`), must be
  literals that `literal_eval` reads, and must pass. Condition two is
  `_testcase_method` (`:2702-2742`), reached through `testcase_of`
  (`:4669-4677`) and `_handler_methods` (`:2683-2699`), which maps each
  handler that a method of a top-level class runs itself to that class
  and method, once per file and only when a call gets this far.
  `self_methods.Methods` (#306) is built at most once, by the existing
  `methods_of`.
- R49, condition three. `_proved_to_pass` (`:2655-2680`) walks the
  handler as `_contains_oracle` (`:2187-2204`) does, except that it does
  not enter an assertion's message, and every oracle it meets must be
  proved. One `assert False`, `assert str(e) == "y"`,
  `assert e == e`, `self.fail()`, `pytest.fail()`, `pytest.raises(...)` or
  any other call `_is_oracle_call` (`:2177-2184`) names keeps the handler
  inspection, so the shapes 431.Q2 keeps as inspection fall outside the
  proof by construction. A handler with a `raise` anywhere stays
  inspection (`_raises_in`, `:2651-2652`, which `_swallows`,
  `:2266-2272`, now also uses, with the same reading).
- R50. A handler that holds an oracle, all of them proved, joins
  `swallowing_handlers` as its normalized first line followed by a space
  and `[always-passing assertion]` (`_ALWAYS_PASSING`, `:2495`; the walk,
  `:4701-4715`). `_norm` removes every space from a handler's text, so the
  new text never equals another Python text, and the per-file multisets
  (`engine.py:1581-1591`) compare it apart from main's texts: every diff
  main blocks still blocks, a pre-existing literal-only handler cannot
  offset a newly added swallowing one, and an old empty handler cannot
  offset a new literal-only one. The fingerprint function
  (`detectors/globals_rules.py:59`: the rule, the path and the text), the
  rule id, `FINDINGS_VERSION` and `IR_VERSION` (both 2) do not change, and
  an existing finding keeps its fingerprint; a finding with the new text
  has a new one. `swallowing_handlers` gains values with the suffix and no
  new field.

**Readings where the ruling is silent**; the owner approved each as
written (below). Each errs toward unknown, which keeps main's reading:

1. `not` is read only before a literal, as R49 lists it, so
   `not (1 == 2)` is unknown; a comparison's operands are literals only.
   `and` and `or` take any of the forms, nested.
2. A comparison, `assertEqual` or `assertNotEqual` whose operands hold a
   bytes literal is unknown: comparing bytes with str or int warns under
   `python -b` and raises under `-bb` (`_holds_bytes`, `:2544-2546`).
3. A unittest call's `msg` must be a literal that `literal_eval` reads,
   since it is evaluated before the call: `self.assertTrue(True, -"a")`
   raises TypeError.
4. Condition two's base is the first entry of the class's local order
   (`Methods.order`, `self_methods.py:437`) that the file does not define,
   read by its spelling: the last part of its dotted name ends in
   `TestCase` (`unittest.TestCase`, `TestCase` imported from `unittest`,
   Django's `SimpleTestCase`, `unittest.IsolatedAsyncioTestCase`, or a
   project's class so named); what the name is bound to is not read. A
   same-file class does not count by its own name; its order must reach
   such a base. A base from another module that comes first, `object`
   included, leaves the call unknown, because it may define the method
   itself: `class FooTests(Mixin, unittest.TestCase)` with `Mixin`
   imported is unknown, and `class FooTests(unittest.TestCase, Mixin)` is
   proved. This is narrower than the ruling's text, which asks only for
   such a base somewhere on the same-file chain; it extends R49's residual
   "a project base imported from another module", which the ruling names
   for `class FooTests(MyBase)`.
5. "`self` is the receiver" is read as `self_methods.receiver`
   (`self_methods.py:524`) reads it: the method's first positional
   parameter, whatever its name, which the method never rebinds. The
   method is no `staticmethod` and no `classmethod`, and the handler is in
   the method's own body, not in a nested def, lambda or class, in a
   top-level class of the module. Other decorators on the method or the
   class are not read.
6. "Defines or assigns the method's name" is read as #306 reads the
   rebinding of a helper method (D-145 Sub-Q3, D-149 (c)). Besides a
   binding in a same-file class of the order before the base, the call is
   unknown when the module stores the name anywhere (`x.assertTrue = f`,
   `self.assertTrue = f` in `setUp`, a literal-name `setattr`,
   `patch.object`), stores an item into any `__dict__`, or sets a computed
   name on the receiver or on a class of the order, or when a same-file
   class of the order binds `__getattribute__`, `__init_subclass__` or
   `__setattr__` (`_RECEIVER_HOOKS`, `:2531`), as #306's
   `Methods._resolve` (`self_methods.py:496`) does. A class keyword (a
   metaclass) or a class name the module binds twice makes the order
   unreadable, so the call is unknown.
7. `assertEqual` is unknown when the module's text contains
   `addTypeEqualityFunc` or `_type_equality_funcs`: a registered
   type-equality function decides the comparison for its type instead of
   `==`. It is also unknown when reading 6 finds any name it looks up on
   the receiver on the way to a pass stored or bound, not only its own
   (`_REACHED`, `:2521-2526`): `_getAssertEqualityFunc`,
   `_baseAssertEqual`, the methods unittest registers by name for `dict`,
   `list`, `tuple`, `set` and `str` (`assertDictEqual`, `assertListEqual`,
   `assertTupleEqual`, `assertSetEqual`, `assertMultiLineEqual`), and
   `assertSequenceEqual` and `assertIsInstance`, which those call. A
   same-file `assertListEqual` that raises makes
   `self.assertEqual([1], [1])` fail, so reading it as proved would report
   a swallow the handler does not do. The other five methods look up
   nothing else on the receiver when they pass.
8. An `except*` handler is read as an `except` handler is.

**R66.** `_contains_oracle` does not read reachability, and neither does
the proof: a handler holding only `if False: assert value() == 1`, or an
assertion after `return`, held an oracle on main and holds an unproved one
now, so it stays inspection and the pair passes, before and after this
change. It is a named Python residual in THREATMODEL row 129 and in
`docs/KNOWN-ISSUES-next.md`. Handling it would mean carrying
`_unreachable_ids` over to handlers, a wider round than 431.Q2's scope.

**Cost.** As in JS/TS (D-138), adding an always-passing assertion to a
handler that already swallows reports the new text once, under a new
fingerprint. One shape this newly reports, as #496 names it:
`try: f(); assert False` with `except Exception: assert True`. That test
cannot fail, because the handler also catches the `AssertionError` that
`assert False` raises, so the report is correct; but the shape looks
honest, and only the sweep can say how common it is.

**Residuals,** which keep the exemption: a name bound to a literal
(`ok = True`, then `assert ok`); an assertion on the caught binding that
cannot fail once it is caught (`assert error`, `assert error is not None`,
`assert isinstance(error, Exception)`); other always-true shapes the
TAUTOLOGY rating recognizes (`assert (x, "msg")`, `isinstance(x, object)`,
`"" in s`, `len(x) >= 0`); a unittest call in a class that reaches its
TestCase base only through a base imported from another module, or in a
same-file mixin with no TestCase base (R49); other `assert*` methods, and
third-party and mock assertion calls; the unreachable oracle (R66); the
forms readings 1 to 7 leave unknown; and an equal-count exchange of two
handler sites with the same text.

**Rule 2.** The ruling approves no change to an existing expectation. A
grep of `tests/cases`, `benchmarks`, `src/checkwash/demo_cases` and the
inline sources in `tests/*.py` found no broad handler whose only oracles
are literal assertions, so by reading none moves, and none was changed.
The grep is not exhaustive; this PR's CI is the check, and if an existing
expectation moves, the round stops and lists it for the owner.

**Tests.** Four positives, from #518 unchanged but for `bypass: 129`
(R31): `broad_except_always_passing_assert_true_pos`,
`broad_except_always_passing_literal_compare_pos`,
`broad_except_always_passing_bare_except_pos` and
`broad_except_always_passing_unittest_pos`, each BROAD_EXCEPT_ADDED high
with `NO_PROD_CHANGE_IN_DIFF`; their titles were approved under A88
(below) and are unchanged. Four negatives, one per condition, carry new
labels, which the owner approved (below):
`broad_except_literal_beside_inspection_neg` (condition three),
`broad_except_unittest_argument_count_neg` (condition one),
`broad_except_unittest_not_testcase_neg` (condition two) and
`broad_except_unproven_oracle_neg` (`assert value() or True`, R51).
`benchmarks/FAILURES.md` was edited by hand: row 129's pins gain the four
positives. `tests/test_issue496_python_handler_literal.py` adds 136
collected items, counted from its parametrize lists: the `assert` family
(29), the unittest methods (17), what stays inspection (30), condition
one (13), condition two (11 proved, 21 unknown), verdicts for the pair,
the offsets and the cost, the unchanged branch folder, the R66 residual
and `except*`. By reading, the documented test count becomes 20083
(19939 + 8 + 136); CI's collection checks it. Nothing under `tests/gates`
changes.

**Sweep** (R32). The pair's before side ran on #518 (run 39215282880,
the four ids above). The after side and the refactor benchmark
(`tests/gates/test_refactor_corpus.py`) run in this PR's CI. The standard
and D-088 sets, compared byte for byte between this fix's parent commit
and its merge commit, join the combined sweep. A checkwash-lab branch
declares it before any engine runs, and the owner approves the frozen
manifest and both engine commits first; it runs on LAPTOP-01AGNPJU only
under EC POLICY `checkwash-pju-sweep` (T-546), otherwise on the pool. Its
report lists every commit where `BROAD_EXCEPT_ADDED` changes, each one
read. Waived (R32): the targeted set of Python commits that add a literal
assertion to a broad handler, because only assertions proved to always
pass leave the exemption and a newly reported handler counts as
swallowing under main's rule anyway; and the Python cost difference,
which is one literal evaluation per oracle in a broad handler that guards
one. `NOT_RUN：工作機規則（POLICY work-machine-local），the standard and D-088 comparison waits for the combined sweep; nothing ran on the work machine`.

**Closing** (R35). #496 closes when this PR and its approved maintainer
text merge, without waiting for the sweep, which departs from
`docs/KNOWN-ISSUES-v0.8.0.md:31`. What has not run is recorded here, in
the combined sweep's lab declaration and in a `docs/KNOWN-ISSUES-next.md`
row. Still to measure: the standard and D-088 comparison above. Fallback:
if it shows a new block on the new text that review finds false, #496
reopens, and the proof is narrowed to leave that shape unknown before a
release ships it. The owner accepted this fallback (below).

Evidence status: prepared on a work machine where no pytest, checkwash or
product code ran; every expected result was traced by reading the code,
and this PR's CI is the first run.

First approvals: the owner answered the agent's PR approval list on
2026-10-19 with 「PR 核可清單全部照建議」 ("the PR approval list, all as
recommended"); the reply was a button whose text the assistant wrote. Its
A87 approved reading #518 as its body says, and its A88 approved the four
positives' titles, with no second review while they are unchanged.

The agent wrote this entry in #496's fix PR #531. The maintainer approved
it on 2026-10-19: 「第二輪核可全部照建議」 ("the round-2 approval list, all
as recommended"), in reply to the agent's second list of approval items
for the open pull requests, which takes every item's recommended answer.
For this PR those are: B16, the wording as committed of SPEC §4's
`BROAD_EXCEPT_ADDED` Python clause (a4bc8111, a0a1b4a6), THREATMODEL row
129's Python paragraph and residuals and the qualification in the
false-positive table (f1b2cc08, 2c7fd0c4), this entry (7c2ae41a,
bb83ffd6, fe8a82ef), the `docs/KNOWN-ISSUES-next.md` #496 row (6953e3ec,
a0a1b4a6) and the Python pointer in `docs/js-catch-swallowing.md`
(6953e3ec); B17, readings 1 to 8 as written, each erring toward unknown,
including reading 4, whose base rule is narrower than R49's text, and the
conservative conditions of readings 6 and 7 (#306's reading of a
rebinding, and `assertEqual` unknown when the module's text holds
`addTypeEqualityFunc`); B18, the four negatives' labels; and B19, the
fallback under **Closing** (R35). The reply is the text of a button the
agent wrote, which the owner chose; the agent also wrote the list and
each item's options. After the approval the agent changed only the
readings' heading and the negatives' sentence, which had said they
awaited it, added the sentence after the fallback saying the owner
accepted it, retitled the paragraph on the first approvals, and wrote
this paragraph.

## D-164 (2026-10-19): a verified 200-byte read of an oversized side answers the shell-shebang check (#455)

Ruling 455 (owner, 2026-10-18, 「照建議」, "as recommended",
issuecomment-6248011708) adopted the issue's Recommendation: option (b),
variant (b1), applied to extensionless and suffixed paths alike and
including the runtime-provider pass skip (questions 1 and 2); (c) only if
HIDDEN_UNICODE is widened beyond `.py` (question 5); (e) rejected, so no
partial parse, and a partial read gives no evidence and clears no finding
(question 6); and the limit on any bounded read as the Recommendation
states it, under which a bounded read may remove the extensionless refusal,
because that refusal stood for exactly the shebang question (question 3).
The owner's second ruling that day (「19 項全部照建議做（價值判斷的題也照你的傾向）」,
"all as recommended, value judgements included", issuecomment-6248628575)
settled the two questions the first left open: an unchanged dot-less file
over the limit that the provider pass reads is first confirmed by a test and
then filed as its own issue, not fixed here (question 4), and HIDDEN_UNICODE
is to be widened to JS/TS in its own issue, #498, adopted only if a
false-positive sweep stays inside a line fixed in advance (question 5).
On 2026-10-19 (「裁決總表全部照建議」, "the consolidated ruling list, all as recommended";
the reply was a button whose text the assistant wrote;
issuecomment-6261648853) R96 fixed #498's false-positive line and R98
scheduled #498 after v0.9.0, with (c) behind it; neither changes this PR.
R1 (A), recorded on #419, put #455 in v0.9.0's scope.

**The limit on a bounded read** (question 3). It may answer only a question
that the bytes read fully decide. It never feeds a parser, never grants
evidence and never clears a finding. It may add a refusal. It may remove a
refusal only when that refusal stood for exactly the question the read
answers.

**The decision.** An unread side keeps its first 200 bytes, the bytes
`_shell_shebang` reads, and they answer whether the side starts with a shell
shebang, as the whole side would. A shell shebang there gives the path
runner shape whatever its suffix, as at any size, so the run refuses and
names that side. A file with no extension no longer refuses for the shebang
it may hold once every unread side has its bytes: without one it is judged
like any other unread path. This supersedes D-135's sentence "Python
modules, pytest configuration and extensionless files refuse, because the
runtime-provider pass and the runner shape read them" for extensionless
files, and closes two of its residuals, "A suffixed file with a shell
shebang only on an unread side stays set aside (for example `ci/run.txt`)"
and "Fail-closed side effect: an extensionless file over the limit now exits
2 even when it is a document, such as `README`, `LICENSE` or `.envrc`",
except past the stream ceiling (reading 1). Its residual "A refusal for a
change with two unread sides names the first unread side" is narrowed by
reading 2.

**As implemented** (lines at this PR):
- `change.py:9`, `:33`. `UnreadSide.prefix` holds the first
  `SHEBANG_PREFIX_BYTES` (200) bytes, or None when they were not read. It is
  `field(compare=False, repr=False)`, so it takes no part in equality,
  hashing or the repr, and a side without a prefix keeps today's answer.
  #454's writers project the note's four keys explicitly
  (`report/unread.py`, `report/sarif.py`), so it reaches no output.
  `roles.py:318` reads `data[:SHEBANG_PREFIX_BYTES]`, the same 200 bytes as
  before.
- (b1), `gitio/snapshot.py:134-223`. An oversized Git blob of at most
  `MAX_PREFIX_STREAM_BYTES` (`:25`, equal to `MAX_BATCH_BYTES`, 64,000,000)
  is streamed through `cat-file --batch`. The header is checked as
  `_read_objects` checks one; the first 200 bytes are kept; the rest is
  read in pieces of at most 65,536 bytes, hashed and dropped, so no
  oversized blob is held whole; and the whole is checked against the object
  id with the full read's message (`_blob_digest`, `:115`, which
  `_verify_blob` now uses too). The objects are asked one at a time, and
  each adds the 60 seconds `_run` gives one process to the deadline.
  `GitSnapshot.read_many` (`:289`) streams every such side of its tree
  through one more process; `GitSnapshot.read` (`:526`) streams its side in
  place of the full read an under-limit side costs. The working-tree side
  keeps the first 200 of the 1,000,001 bytes it already reads (`:760`), so
  no read is added there. The session presence check
  (`gitio/git.py:366`) asks only whether HEAD holds a path and streams
  nothing.
- `engine.py:225-301`. `_shebang_side` finds the first unread side whose
  prefix is a shell shebang, with `_runner_shape`'s exclusions (a `.py`
  path; a JS/TS test file, judged on the readable sides), and
  `_detector_must_read` takes it as runner shape. The extensionless rule
  (`:287`) refuses only when some unread side has no prefix.
  `_refused_side` (`:341`) names the side.
- The skip, `engine.py:356` and `shadow.py:2457`. `_shebang_free` lists the
  paths of set-aside changes whose every side is known, readable sides
  whole and unread sides by prefix, and holds no shell shebang. The
  provider pass's phase one does not request such a path where it requests
  a dot-less path for a shebang; with no CI role, runner suffix or
  `Makefile` name, it adds no runner invocation, as the read would not. The
  read-time guard (`_guard_unread_reads`, `engine.py:377`) is unchanged, so
  any other reader that reaches a set-aside path still refuses.

**Readings where the ruling is silent**; the owner approved each as
written (below):
1. The ceiling is per side: a Git side over 64,000,000 bytes, the
   candidate (b1) names, keeps no prefix and today's answer. It is not a
   total per tree. A total would let other oversized sides the same commit
   changes, earlier in path order, use it up before a later one, which
   would reopen the base-side gap in a repository that already holds many
   large files. Per side, the extra read grows with the oversized bytes the
   diff changes, and the deadline grows with the number of objects. So
   neither has a total bound: a commit that changes N oversized Git sides
   of up to 64,000,000 bytes each streams and hashes them all, where
   before #455 they cost no read, and a tree's deadline is 60 x (N + 1)
   seconds. An alternative not taken here is a total per tree past which
   the run refuses, naming the side: it bounds the time without reopening
   the gap, but a suffixed side past it would refuse where (b1) says a
   side above the ceiling keeps today's answer.
2. A refusal names the first unread side whose prefix holds a shell
   shebang that gives one of the change's paths runner shape, also when
   another must-read rule applies to the path; otherwise the first unread
   side, as before. #456's Stop-hook match is by change
   (`_verdict_side_over_limit`), so no hook outcome moves with the name.
3. The exclusions are `_runner_shape`'s, so a prefix gives a `.py` path or
   a JS/TS test file no runner shape. Each refuses by its own rule anyway.
4. The skip is computed from the sides, not from the fact that the change
   was set aside, and only the dot-less clause of the pass's runner paths
   takes it. A CI-role or runner-named path is read as before; such a path
   refuses at set-aside anyway.
5. A working-tree side has no ceiling, since its bytes come from the read
   already made. Its prefix is not checked against an object id; no
   working-tree read is, since none has one.

**Costs,** by reading, not measured. For honest repositories, an oversized
changed `README`, `LICENSE`, `ChangeLog`, `.envrc` or other file with no
extension and no shell shebang gets a verdict instead of exit 2 (under
`--format hook-json`, instead of #456's size block when its head or
working-tree side is over the limit, or the "not analysed" message when
only its base side is), and a suffixed file whose shell shebang is only on
an oversized side newly exits 2. For attackers, the second closes the
base-side gap: an existing `ci/run.txt` that `sh ci/run.txt`
runs, over the limit, whose head drops the shebang and the test command.
That closure holds for the required range-mode check. In the Stop hook
(`--format hook-json`), when only such a file's base side is over the
limit, as when the session shrinks or deletes that `ci/run.txt`, the run
now gets the non-blocking "not analysed" message (exit 0, no decision; the
class #456 ruling Q3 keeps for a base side alone, THREATMODEL row 128)
where the base gave a verdict, so a weakened test beside it no longer
blocks the stop; when its head or working-tree side is over the limit too,
#456's size block blocks it. The first gives an attacker the answer a small
file without a shebang gets, with less evidence, since a set-aside change
earns none. Each streamed Git
side is read once in full: in range mode one more `git cat-file --batch`
for each tree that holds such a side, whatever their number; in worktree
mode one more for each oversized base side, the same `cat-file --batch`
an under-limit base side already costs, where before #455 such a side
cost none. The gitio gate (`tests/test_perf_git.py`)
has no oversized side, so its budget does not move.

**Residuals.**
- A file with no extension whose Git side is over 64,000,000 bytes still
  refuses, and a suffixed one with a shebang only on such a side is still
  set aside (reading 1).
- An unchanged file with no dot in its name over the limit still refuses
  on a run that reaches the provider pass's first read phase, which reads
  it as an unchanged file through the strict reader; so do a symlink and a
  batch over the byte budget there. So a changed oversized document gets a
  verdict while the same file unchanged can still refuse. Question 4 orders
  a reproduction test first, in range and worktree mode, and then its own
  issue; neither is in this PR.
- HIDDEN_UNICODE, BROAD_EXCEPT_ADDED and SUPPRESSION_ADDED still read no
  set-aside path (#498, then (c)).
- An oversized file with a shell shebang on its head or working-tree side
  still refuses, and #456 blocks the Stop hook on it.

**Rule 2.** The ruling approves no change to an existing fixture's expected
output. Every comparison of a snapshot's `UnreadSide` with one built without
a prefix holds, because the prefix takes no part in equality, and every
case built without a prefix keeps today's answer. One existing expectation no longer held
with its input as it was: the `untracked_extensionless` row of
`tests/test_issue456_hook_size_refusal.py` (`:135-138`). Its untracked
`NOTES` was 1,000,001 bytes of hex text with no shebang, so it was set
aside, and the weakened test beside it blocked the stop as a finding, where
the row asserts #456's size block; CI failed on that row on every leg at
2a6ee2f9. In round 6 the owner approved option (a) (G1, 2026-10-20,
「第六輪 G1～G6 全部照建議」, "round 6, G1 to G6, all as recommended"; the
reply was a button whose text the assistant wrote). The row's `NOTES` input
now starts with `#!/bin/sh` and keeps its size, 1,000,001 bytes, so the run
refuses and names `NOTES` on its worktree side, and the row's asserted
output is unchanged; its id and its undo are unchanged too. On the base the
same input refuses by the extensionless rule, naming the same side. The
untracked file with no shebang is pinned by this PR's
`test_the_stop_hook_beside_an_untracked_oversized_extensionless_file[document]`.
Nothing under `tests/gates` changes.

**Tests.** `tests/test_issue455_bounded_shebang_read.py` adds 82 collected
items, counted from its parametrize lists: the prefix against the whole
side (8) and equality (1); the engine's rows (10 set aside, 9 refusing and
naming the shebang side, 6 other rules, 1 without a prefix); no repair
evidence with prefixes, test_issue415's unread rows and a README (5), and
beside several set-aside documents (1); the provider pass (3); the
snapshots, the working-tree read bound, the ceiling and the stream's
protocol (2, 1, 2, 1, 4); the git processes (3); and the CLI in range,
worktree and hook mode (25), where a shell shebang on an unread side
refuses for every status the issue's acceptance names, and the Stop hook
keeps the "not analysed" message when only a suffixed runner's base side
is over the limit. By reading, 30 of the 82 pin behaviour the base
already has, such as the shebang check
itself, the other must-read rules and refusals the base names the same
way; on the base they fail only because the module imports names it
lacks. No `.gwcase` fixture is added: the case format has no unread
side. By reading, the documented test count becomes 20247 (20165 + 82);
CI's collection checks it.

**Versions.** No rule id, severity or machine-output field changes, so
`FINDINGS_VERSION` and `IR_VERSION` stay 2, and no fingerprint moves: a
set-aside change gives no finding.

**Sweep.** The issue asks the sweep to measure the change on the standard
set. Under R1 and R2 this fix joins the combined sweep, where its merge gets
its own before/after pair, and its report lists every commit whose outcome
moves between exit 2 and a verdict. `NOT_RUN：工作機規則（POLICY work-machine-local），the standard-set measurement waits for the combined sweep; nothing ran on the work machine`.

Evidence status: prepared on a work machine where no pytest, checkwash or
product code ran; every expected result was traced by reading the code, and
this PR's CI is the first run.

D-164 to D-169 were assigned to the pull requests of the fourth wave,
prepared in parallel. When integration batch 4 merged, all of them were
on main, in number order after D-163. This entry is D-164. The agent
wrote it in #455's fix PR; the owner approved its wording, readings 1 to
5 and the Rule 2 item in round 6 (below).

The maintainer approved this entry on 2026-10-20: 「第六輪 G1～G6 全部照建議」 ("round
6, G1 to G6, all as recommended"), in reply to the agent's round-6 list for
the fourth wave, #534 to #539. The reply was a button whose text the
assistant wrote, which the owner chose. Its items for this entry, at #536's
head c104ee4b: G1 (F1, option (a)) approves the Rule 2 change above: the
`NOTES` input of the `untracked_extensionless` row of
`test_a_worktree_side_over_the_limit_blocks_the_stop`
(`tests/test_issue456_hook_size_refusal.py:133-135` on main) becomes
`b"#!/bin/sh\n" + blob(LIMIT + 1 - len(b"#!/bin/sh\n"), "notes")`, still
`LIMIT + 1` bytes (0d1ed936), with its id, undo and asserted values
unchanged. G2 (F16) approves the wording of this entry (f006f365, 89cb0ae9,
e3aaf6bb, 2a6ee2f9) and of SPEC §4b (012129aa, c62d3143), and the Rule 2
paragraph rewritten to that decision, as F16 asked (c104ee4b). G4 (F17, F18)
approves readings 1 to 5: one stream ceiling per side and no per-tree total,
so neither the bytes streamed nor a tree's deadline has a total bound, and
the sweep measures them; the refusal names the side whose prefix holds the
shebang; `_runner_shape`'s exclusions hold for a prefix; the skip set is
computed from the sides; the working-tree side has no ceiling. G5 records as
a residual, as #456 ruling Q3 rules, the Stop hook's "not analysed" message
when only the base side of a suffixed runner such as `ci/run.txt` is over
the limit (Costs). G6 (F19, F20) puts a THREATMODEL row for the base-side
gap this entry closes, Closed and pinned in `E2E_PINNED`, in a separate docs
pull request whose wording comes to the owner in a later round, and has
Claude open, after this fix merges, a test-only pull request with question
4's reproduction test (the second residual), in range and worktree mode, and
file the issue once CI reproduces it. The numbering sentence and the
readings' heading were rewritten to the facts at merge under the C1/D3
precedent the same round approved (f42441d0, in integration batch 4). This
paragraph was written after the reply.

On 2026-10-20 the owner approved the paragraph above and the rewrites it
names with 「第七輪 H1～H5 全部照建議」 ("round 7, H1 to H5, all as
recommended"), a button whose text the assistant wrote: its item H2
approves together the round-4 and round-6 approval records, the C1/D3
rewrites at merge and the batch-4 merge sentences it lists. This sentence
was written after the reply.

## D-165 (2026-10-19): a JS/TS test registered where no code runs is no unit (#484)

Ruling 484 (owner, 2026-10-18, 「19 項全部照建議（價值判斷的題也照你的傾向）」,
"all 19 as recommended, value judgements included"; #484
issuecomment-6248630321, which states each decision in full): Q1 (a), Q2
(no new rule text), Q3 (the fixtures), and the Python twin filed as #499.
The owner's consolidated ruling of 2026-10-19 (「裁決總表全部照建議」, #484
issuecomment-6261651400) added R2 (this fix, merged before the combined
sweep's manifest is frozen, gets its own pair of arms in that sweep), R99
(#499 follows this ruling), R100 (this PR's THREATMODEL row lists the
Python form as open, and that half is Closed when #499's fix merges) and
R101 (#499 is P2 and lands in the same round, v0.9.0). D-164 to D-169 were
assigned to six pull requests prepared in parallel. When integration
batch 4 merged, all of them were on main. This entry is D-165.

#484 reports that `parse_javascript` read every declaration
`_DECLARATION_RE` finds as live. A unit's liveness came from its modifiers,
options and enclosing declarations, never from whether the declaration
call is reached, and #429's walker (D-148) read only the callback of a unit
with assertions and cut only assertions. So a test moved under
`if (false)`, after `return;` in a `describe` callback, under a module-level
`if (false)`, behind `false &&`, or a node:test `t.test(...)` after
`return;` in its parent test, passed with zero findings, and a test pasted
under `if (false)` was a live unit with no markers, so it lent a deleted
test the D2 move credit.

Implementation, lines at this PR:

- Q1 (a), the walk reads more. `_dead_code`
  (`frontends/javascript/frontend.py:1412`) walks the module's own
  statements (`Reachability.module_unreachable`, `reachability.py:428`),
  the block callback of every `describe`, `suite` and `context`
  declaration, their `x`/`f` forms, modifiers and tables included, and the
  callback of a test that registers a named test or a block of its own, even
  one with no assertions. `parse_javascript` (`:2827`) parks every
  declaration that starts in a span those walks prove dead. A parked
  declaration is no unit, and neither is any declaration inside it, since a
  dead span covers whole statements. The file's focus, the ancestors a unit
  inherits skips from and `_focus_stops` read only the live declarations, so
  a dead `.only` stops no other test. A parked test is still scanned
  (`:3057`): its assertions reach `swallowing_handlers`, so the catch
  evidence does not change, and they are recorded as never reached. Its
  callback stays among the test bodies, so the test around a parked subtest
  does not gain the subtest's assertions.
- Q1 (a), `&&` and `||`. #429 Q3's reading drops a declaration as it drops
  an assertion: the walks of this round pass the declarations' call spans
  as the operands it may drop (`unreachable` and `module_unreachable` now
  take a map of spans), so `false && it(...);` parks the test.
- Q1 (a), the finding. No detector changes. A parked unit is absent on its
  side, so its loss is what a deletion reports: TEST_DISABLED "test unit
  disappeared", under the deletion's key (`detectors/test_disabled.py:82-101`),
  at high in a test-only change. No `ParsedFile` field is added, so the
  message does not say the code is still in the diff.
- D-148 reading 7, amended as the ruling approves. It now reads: "A
  boundary is proved only where the text between two tokens is whitespace
  and comments. A `;` after an operand the tokens omit (a template or
  regular expression) still ends a statement. A function declaration with a
  TypeScript return type, `import`, `export` and `with` stop the walk,
  except that the walk of a file's own statements steps over a static
  `import` declaration whose end it proves (#484); `export`, TypeScript's
  `import x = require(...)`, an import with attributes and any other
  `import` still stop it." (`Reachability._import`, `reachability.py:799`.)
- D-148 reading 10, amended as the ruling approves. Its clause "a dead
  region holding a `function` (a call before it may run the hoisted body,
  which the binder does not always scope: `function f<T>()`)" now reads "a
  dead region holding a function declaration, a labelled one
  (`l: function f() {}`) included (a call before it may run the hoisted
  body, which the binder does not always scope: `function f<T>()`); a
  function expression hoists nothing, so a dead region that holds one is
  read, except a named one in a position the walk reads conservatively as
  a declaration's, such as an object property's value after `:`, which
  refuses it too (D-165 reading 6; THREATMODEL row 159, residual 6)"
  (`_declares_function`, `reachability.py:516`). The walker is
  shared, so the narrowing moves #429's cuts too: an assertion parked in a
  dead region that also holds a function expression, silent before because
  the whole callback was refused, now reports ASSERT_REMOVED, and an edit
  to an assertion already in such a region, reported before, is now
  silent. Reading 10's other refusals cover the text from the file's start,
  so they refuse a `describe` walk as they refuse a callback walk, and they
  refuse the module walk wherever that text occurs in the file.
- Q2, no new rule text. A parked unit is never a live added unit, so it
  earns no D2 move credit (`engine.py:1661`, `:1675`), adds no oracle mass
  to D5's restructure check and no split/rename budget (`gating.py:480`,
  `:506`). D10's survivor search reads Python files only (`engine.py:1719`,
  with `def name(` needles), so no JS/TS unit was ever a survivor; SPEC's
  D10 row now says so, which records what the code does and changes no
  rule.
- Q3, the fixtures, each keeping a live test beside the parked one. The
  eleven blocking shapes: `js_dead_registration_if_false_pos` (the issue's
  shape), `js_dead_registration_after_return_pos`,
  `js_dead_registration_module_if_false_pos` (the import step-over),
  `js_dead_registration_literal_and_pos`,
  `js_dead_registration_node_subtest_pos`,
  `js_dead_registration_describe_pos`,
  `js_dead_registration_mocha_function_pos` (the amended reading 10),
  `js_dead_registration_pasted_other_file_pos`,
  `js_dead_registration_assertion_moved_pos`,
  `js_dead_registration_equal_mass_pos` and
  `js_dead_registration_focus_pos`. The controls:
  `js_registration_if_true_neg`, `js_registration_else_of_if_false_neg`,
  `js_registration_after_iterator_return_neg`,
  `js_registration_unwrapped_from_if_false_neg` and
  `js_registration_after_unproved_end_neg`. The named residual pins:
  `js_dead_registration_env_condition_residual_neg` and
  `js_dead_registration_const_condition_residual_neg`. The new reading:
  `js_dead_registration_weakened_both_sides_neg`. The unit pins the ruling
  lists, and the walk's other readings, are in
  `tests/test_issue484_js_dead_registration.py`.
- THREATMODEL: a new row 159, Closed in part (JS/TS closed, the Python
  form open as #499), and a clause on row 9 for its `if (false)` absorber;
  the eleven blocking fixtures cite row 159, and the two absorber fixtures
  row 9 as well. `benchmarks/FAILURES.md` is edited by hand to what
  `make_failures.py` would write, which was not run. When integration
  batch 4 merged, row 159 kept its number and #480's row, which had taken
  the same number, became row 160 (A98); #499's merge in that batch made
  row 159 Closed for its Python half as well (R100, D-166).
- Docs: `docs/js-reachability.md` gains a section on registrations and
  follows the amended readings 7 and 10, and `docs/KNOWN-ISSUES-next.md`
  gains a #484 row, with the #429 row's "outside this change" sentence
  replaced. The dead `t.skip()` residual (D-148 reading 9) is unchanged
  and stays listed.

Readings the ruling leaves to the implementation; the owner approved each
as written (below):

1. **A test callback that registers subtests** is one whose body holds the
   start of a declaration the frontend reads as a named test or a block:
   node:test's and tap's `t.test(...)`, and any other `test`, `it` or
   `describe` call there. A bare `.test(value)` call, which the frontend
   reads as a declaration with no name, does not make the callback walked.
2. **The operand for Q3** is the declaration's call from its callee to its
   `)`, the callee including a receiver of dotted names (`t.test`). So
   `false && await t.test(...)` is not decided, and neither is a
   declaration whose callee follows a call (`make().test(...)`) or one held
   by a declaration or assignment (`const ok = false && it(...)`), as for
   an assertion.
3. **Declares tests** (the question the ruling leaves to this draft). A
   parked declaration still makes a file declare tests, as before
   (`frontend.py:3095`), so E7's role reading of a JS/TS test path does not
   move.
4. **A parked test's assertions** are all recorded as never reached: one
   with a strength in `unreachable_assertion_spans`, one without in
   `unreachable_unjudged_assertion_spans`. The coverage inventory reads the
   first as read and keeps the second's "recorded with no strength"
   reason, as D-148 does for a cut.
5. **A parked table** (`test.each(CASES)(...)` under `if (false)`) still
   counts as a table-argument read of its same-file `const` (D-152 reading
   5), so a live table that shares the `const` keeps its rows counted.
6. **Statement position** for the amended reading 10 is read
   conservatively, from the token before the `function`: a `function` with
   no name after it never declares; one after `.`, `?.` or `#` (a spread
   included, whose `...` the tokens hold as three `.`), `(` or `[`, a
   comma or an operator that waits for its operand begins an expression,
   and so does one after `return`, `throw`, `yield`, `await`, `void` or a
   prefix `!` on the same line; anything else, `{`, `)`, `]`, `}`, `>`, an
   operand at a line break and `:` included, reads as a declaration. `>`
   may close a TypeScript type, after which a statement may start, and the
   tokens hold `>>` and `>>>` as `>` tokens, so a `function` after either
   reads as a declaration too. The token stream omits templates and
   regular expressions, so where one stands before the `function` (or its
   `async`), the token before it is not the one JavaScript reads, and the
   `function` reads as a declaration (`` const note = `x` `` then
   `function f() {}` on the next line, which a line break makes one); so
   does one after a `.` that ends a number (`x = 1.` then a declaration on
   the next line), the word right before the `.` starting with a digit. So
   a named function expression in a dead region still refuses the walk
   after a `:`, such as an object property's value, after `>`, `>>` or
   `>>>` (`a > function f() {}`), and after `void`, a prefix `!` or
   `await` at a line break (row 159, residual 6). Every `function` in the
   dead region is read, at any depth, so a function declaration inside a
   dead test's own callback refuses the walk too, though that body never
   runs.
7. **The import step-over** reads `import "m"`, and `import` followed by
   names, `*`, `as`, commas and braced lists of names, strings and
   commas, then `from` and a string; TypeScript's `import type` is such a
   form. It ends at a `;`, at a line break before any token but `with` or
   `assert`, or at the file's end, and only where the text between its
   tokens is whitespace and comments. A default import named `from`
   (`import from from "m"`) stops the walk. The module walk is refused when
   text the tokens omit stands before the file's first token.
8. **A module-level `return` or `throw`** cuts the rest of the file, as in
   a block. CommonJS runs a top-level `return`, and an ES module that holds
   one does not load, so either way nothing after it registers.
9. **What is not walked.** The callback of a declaration that a dead span
   already holds, all of which is dead; and a declaration whose call was
   recovered, as D-148 does not walk a recovered test callback.

**A note on the fixtures.** JS/TS units carry no shingles, so two unpaired
units of one file pair in span order (SPEC §7). On the base, the dead test
of `js_dead_registration_equal_mass_pos` is a live unit, and the deleted
test pairs with it rather than reaching D5. After the fix nothing pairs
with it, and the deletion is TEST_DISABLED at high, as the ruling expects.
D5 credits a JS/TS file only where its alignment is degraded (row 157,
residual 9). The fixture pins the reading the ruling names.

Rule 2. The ruling approves no change to an existing expectation, and none
was changed. By reading, no existing expected output moves: no fixture or
test registers a declaration in dead code; no existing fixture or test
source holds a `return`, a `throw` or a branch the folder decides at module
level or in a `describe` callback (searched); none holds a function
expression in a dead region; and the one refusal pin for reading 10,
`test_a_cut_holding_a_function_declaration_is_refused`
(`tests/test_issue429_js_reachability.py:217`), uses the declaration form,
which stays refused. Nothing under `tests/gates` changed. If CI shows an
existing expectation moving, the round stops and asks the owner.

**Fingerprints and IR.** No fingerprint scheme changes. A parked test's
finding has the key its deletion has, since the key reads the before side
(pinned). TEST_DISABLED's keys move in #512, separately. No IR or
`ParsedFile` field is added; IR_VERSION and FINDINGS_VERSION stay.

**Costs, by reading; the sweep counts them.** New blocks: a change that
moves a test where no code runs, which is what the ruling asks for, and
the moved #429 cuts above. A misreading no refusal notices (#490) now
reaches declarations: where a change adds one, every test after it in that
statement list can read as "test unit disappeared" at high, a false block,
and where both sides hold one, those tests are read on neither side, so
edits to them are not judged. D-148's refusals (JSX, nested templates, `\`)
cover the text from the file's start, so where they apply these walks keep
today's reading.

**Measurement.** Not measured. Per R2 this fix's merge gets its own pair of
arms in the combined sweep, which measures it as D-148's evidence status
records for #429: the standard set, the D-088 sets and the JS batch, with
the refactor, tamper, decoy, recorded and perf gates. That run also prices
the moved #429 cuts and the #490 cost named above.
`NOT_RUN：工作機規則（POLICY work-machine-local），every effect above is read from source; no test, checkwash run, sweep or runner was run`.

Evidence status: prepared on a work machine where no pytest, checkwash or
product code ran; CI runs the tests. Added: nineteen `.gwcase` fixtures
(eleven pinning row 159, two of them row 9 as well; five controls; two
named residual pins; one new reading), whose labels the owner approved
(below), and 80 collected items in
`tests/test_issue484_js_dead_registration.py`, counted from its
parametrize lists. By reading, the documented test count becomes 20356
(20257 + 80 + 19); CI's collection checks it.

The agent wrote this entry in #484's fix PR. The owner approved its
wording, the readings above and the fixtures' labels in round 6 (below).

The maintainer approved this entry on 2026-10-20: 「第六輪 G1～G6 全部照建議」 ("round
6, G1 to G6, all as recommended"), in reply to the agent's round-6 list for
the fourth wave, #534 to #539. The reply was a button whose text the
assistant wrote, which the owner chose. Its items for this entry, at #538's
head fd00ec12: G2 (F27) approves the wording of this entry (a7f9bb6c, the
DECISIONS hunk of 6687e5fb, f96f07f5, 9a2014f6, 3534ddd1), of THREATMODEL
rows 159 and 9 (031a67d5, with its hand edit of `benchmarks/FAILURES.md`,
the THREATMODEL hunks of 3f1d9847 and 6687e5fb, 3742b3cb, 74c069d0,
5d55818f) and of SPEC (85e971bb, 4061d4cf, 96e446e2, feb2796a, a3175cb6).
That includes 4061d4cf's general form of the qualification F27 asked for in
SPEC §2b (a named function expression still refuses where the walk reads a
declaration's position), reading 6's notes on `{`, `>` and the spread,
reading 7's "braced lists", and residual (3)'s dynamic `import(...)`,
`import.meta` and `import from from "m"`. G3 (F28) approves the 19 fixtures'
labels: 11 blocking, 5 controls, 2 named residuals and 1 new reading. G4
approves reading 3 (F29: a parked declaration still makes a file declare
tests, so E7 does not move); reading 6's conservative positions, recorded as
row 159 residual (6), the three that also refused before the fix and a
function declaration at any depth of a dead region included (F30); and
readings 1, 2, 4, 5, 7, 8 and 9 (F31). G5 keeps the shapes row 159 names as
residuals documented, with no issue. G6 (F32): D-148 gets no pointer line,
and the amended readings 7 and 10 stay in this entry only. The numbering
sentence, the readings' heading, the labels' sentences and the row-number
sentence were rewritten to the facts at merge under the C1/D3 precedent the
same round approved (f42441d0): A98 kept row 159's number, and R100's edit
made the row Closed at #535's merge (02c5b34f). This paragraph was written
after the reply.

On 2026-10-20 the owner approved the paragraph above and the rewrites it
names with 「第七輪 H1～H5 全部照建議」 ("round 7, H1 to H5, all as
recommended"), a button whose text the assistant wrote: its item H2
approves together the round-4 and round-6 approval records, the C1/D3
rewrites at merge and the batch-4 merge sentences it lists, among them the
`docs/js-reachability.md` bullet fd11786d rewrote and SPEC §4's
`TEST_DISABLED` row, where this entry's clause stands beside #499's (the
list called it §5). This sentence was written after the reply.

## D-166 (2026-10-19): a Python def or class whose own statement never runs is no unit (#499)

Rulings R99, R100 and R101 (owner, 2026-10-19, 「裁決總表全部照建議」, "the
consolidated ruling list, all as recommended", in reply to the agent's list
of 104 decisions; the reply was a button whose text the assistant wrote;
#499 issuecomment-6261653646 states each in full). R99 answers #499's Q1 to
Q4 the way #484's ruling (issuecomment-6248630321) answers them for JS/TS,
R100 answers Q5, and R101 makes #499 P2 and puts it in the same round as
#484, which R1 (recorded on #419) makes v0.9.0. The round assigned #499
the number D-166.

#499 reports that pytest collects a module's or a class's tests from its
`__dict__` once that scope has run, so a `def test_*` under a module-level
`if False:` is never bound and never collected, while the Python frontend
read it as a live unit with its assertions. Moving a test there passed with
zero findings, and so did the same in a class body, a test class moved
there with its methods, and the other arms the folder already decides for
assertions (`if not True:`, `if 1 == 2:`, `for _ in []:`, a `match` no case
can meet). The dead copy also earned the D2 move credit, the D5 restructure
mass and the D10 survivor credit.

How each answer is implemented, in `frontends/python/rebindings.py` (lines
at this PR):

- Q2, where the reading lives. `_Judge.never_runs` (`:739-746`) asks
  whether an arm on the def's or class's own path is one `entry`
  (`:640`) reads as `_DEAD`: the arms where a later binding already binds
  nothing (D-144 Q6 (a)). So one folder decides what a binding does to a
  def and whether the def itself runs, and the frontend reads both through
  the `dropped` flag it already reads for #424 (`frontend.py:4789`,
  `:4820`).
- Q1, the unit model. `drop_dead` (`:748-768`) marks such a def or class
  `dropped`: it is no unit, and a class takes its units with it, since
  every def and class in its body has the dead arm on its path and the
  frontend collects nothing in a dropped class. Its loss is a
  disappearance, `TEST_DISABLED` "test unit disappeared", with no marker
  and under the key a deletion has. `run` (`:806-815`) does not judge a
  dead def as one a later binding replaces. `final_bindings` used to stop
  when no name was bound twice; it now also reads a module in which a def
  or class sits under an `if`, a loop, a `try` or a `match`
  (`_ARMED`, `:86`; `:996-1000`), the only places a dead arm can be.
- Q3, credits. No rule text changes: D2's move credits read live added
  units (`engine.py:1650-1680`), D5's restructure mass and split/rename
  budget read the units of the file (`gating.py:480-567`), and D10's
  survivor search parses the untouched file with `parse_python`
  (`engine.py:1699-1738`), so a dead def earns none of them.
- Q4, pins: below.

**Readings where the ruling is silent**; the owner approved each as
written (below):

1. The arms are every arm `entry` reads as `_DEAD`, so besides the shapes
   #499 names they include the `else` of an `if` whose condition folds to
   true, `if False and x:`, the body of a `while` whose condition folds to
   false, and the handlers of a `try` whose body cannot raise, as
   `_Walk.quiet` (`:327-364`) reads it: `pass`, a constant expression
   statement (a docstring among them), a constant assigned to plain names,
   an annotated name with no value or a constant one whose annotation is a
   constant or not evaluated, in a module that does not bind, delete or
   spell `__annotations__`, an undecorated def whose defaults and
   annotations are constants (or not evaluated), and an undecorated class
   with no bases or keywords whose body is made of these and binds no
   dunder name. That is D-144's strict list, two shapes its text does not
   name, the constant expression statement and the annotated name, which
   the code has read since D-144, and two narrowings this PR adds after
   review. First, creating a class reads some dunder names from its
   namespace and raises on a bad value: `__slots__ = 1` and
   `__qualname__ = 1` raise `TypeError`, so does `__classcell__ = 1`, and
   `__slots__ = "a"` beside `a = 1` raises `ValueError`. So a class whose
   body binds any dunder name, by an assignment, an annotation, a def or a
   class statement (`_binds_dunder`, `:160-176`), is read as one that may
   raise. Second, up to Python 3.13, and under
   `from __future__ import annotations`, an annotated name at module or
   class level stores its annotation into `__annotations__` after it binds
   the name, so after `__annotations__ = None`, `flag: "bool" = True`
   raises `TypeError`. So in a module that binds or deletes
   `__annotations__` anywhere (by a name or attribute target, a def,
   class, import, `except ... as`, match capture, keyword, parameter,
   `global` or `nonlocal`) or spells it in a string
   (`_rebinds_annotations`, `:179-204`), an annotated name is read as one
   that may raise, whether the rebinding is in the try body or before it.
   A plain `__annotations__ = None` stays quiet: the assignment itself
   cannot raise. Both narrowings apply wherever D-144 asks whether a
   try-body statement can raise: such a statement after a try-body def no
   longer makes a handler def of that name exclusive with it; a rebinding
   in that try's handler is judged under the handler's guard rather than
   as binding nothing; one in its `else`, or later in its body, is
   undecided rather than certain; and a class read as one that may raise,
   when it is itself the later binding in a try body, is read as one that
   may not bind, so what it replaces keeps its units, with a
   `collection.rebound` marker whose guard D6 never holds (None), instead
   of being certainly replaced. An annotated name that is itself the later
   binding still binds, since the name is bound before the store raises.
   By reading, no expectation on main moves (Rule 2, below).
   `dead_def_handler_of_raising_class_pos` and
   `dead_def_handler_of_raising_annotation_pos` pin a test in such a
   handler as live. A loop's `else`, a `with`
   body, a `try` body, `else` and `finally`, and a `match` on a subject
   that is not a literal stay live. The folder is `_static_truth` with no
   fixture or class-attribute resolution, as D-144 reads module and class
   bodies.
2. A dead class is also `gone`. Under 424.Q9 a rebound class's method stays
   when a collected same-file subclass still runs it; a subclass that
   never runs is now no such subclass, so `del Base` beside a `Test*`
   subclass under `if False:` drops `Base`'s units, where main kept them.
3. In a file that keeps two defs of one name, a dead one takes no
   `name#N` place, so the units after it can be renumbered (below).

**R100, THREATMODEL.** #484's fix PR added a row for a test registered in
code that never runs, row 159, and listed this Python form as open in it.
That half became Closed with this fix, which merged after #484's, in
integration batch 4. This PR's base did not hold the row, so the PR did
not edit `THREATMODEL.md`: the edit, worded in the PR body and approved
by the owner in round 6 (below), was applied at that merge (02c5b34f),
together with `bypass: 159` on the ten positives below and the matching
edit of `benchmarks/FAILURES.md`, where row 159 moved from "Closed in
part" to "Closed". The same merge gave row 9 its Python clause and
`dead_def_pasted_copy_no_move_credit_pos` `bypass: 9` as well (F15,
below).

**Residuals**, which keep main's reading: a def under a condition the
folder cannot decide (`if os.environ.get("X"):`, `if TYPE_CHECKING:`), a
live unit with no marker, as #484 keeps `if (process.env.X)` (R99 Q4); its
assertion-level form is #433, now listed in #504; a name bound to a
constant (`ENABLED = False`, then `if ENABLED:`); a def after a
module-level `raise` (row 135's residual) or `sys.exit()`;
under 424.Q9, a dead class statement of a base's name, between that base
and its subclass, which still counts as the name's binding when the
subclass's bases are resolved, as on main; and a dead class statement
that `_Walk.resolve` (`:614-625`) still takes as the class a module-level
`Cls.attr = ...`, `del Cls.attr`, `setattr` or `delattr` names, when it
is the latest class statement of that name before it, as on main.
`resolve` runs before any deadness is read. So a dead
`class TestTotal: pass` placed between a live `TestTotal` and
`TestTotal.test_adds = None` takes that binding, and the live class's
unit stays, with zero findings, where without it row 135's shape blocks.
The module docstring names both class forms.

**Unchanged.** The file-level reading of broad handlers
(`BROAD_EXCEPT_ADDED`, `broad_handlers` and `swallowing_handlers`) still
walks the whole module, dead code included, as #484's ruling keeps the
JS/TS catch evidence; only units move.

**Cost.** Four edits that main reported now pass, because code that
never runs is not judged, as #484's ruling reads it for JS/TS: an edit to a
test that is dead on both sides; deleting a test that never ran (main read
it as a live test disappearing, at high); an edit made while a test is
taken out of a dead arm, which reads as a new test, so its assertions are
compared with nothing (main paired the two sides by name and reported the
edit); and, by reading 2, an edit to a base class's test method that a
later `del` of the base removes, when the only subclass that still ran it
on main is dead (main kept the method as a unit and reported the edit;
pytest collects it on neither side). A test moved under a dead arm on
purpose, a disable whatever the reason, now blocks.

**Rule 2.** The ruling approves no change to an existing expectation. A
read-only scan of `tests/`, `benchmarks/refactors`, `benchmarks/tamper`,
`benchmarks/decoy`, `examples` and `src/checkwash/demo_cases` (the
`.gwcase` sections, the Python string constants in `tests/*.py` and the
diffs the JSON files hold, parsed with the standard library's `ast` and
never run) found no def or class at module or class level under a dead
arm whose reading this changes. `tests/test_issue424_rebinding.py`'s
handler cases use a `try` body that can raise, and
`tests/test_issue344_walk_once.py`'s are docstring checks that collect no
unit. By reading, none moves, and none was changed. For reading 1's
dunder narrowing, a read-only grep of `tests/` (fixtures, test sources,
`gates`, `data`, `e2e`), `benchmarks/`, `examples` and
`src/checkwash/demo_cases` found no source on main with a `try` whose
body holds a class with no bases that binds a dunder name: the `try`
statements in the test sources' strings sit in function bodies, which the
reading never enters, or hold no class, or only classes with bases. For
its annotated-name narrowing, a read-only `git grep` of the whole tree
for `__annotations__` finds one mention outside Markdown, an attribute
load in a product source string (`tests/test_inert_test_return_metadata.py:55`),
which `_rebinds_annotations` does not count, so no source on main is read
differently.
Sources built at run time are not all covered by the scan; this PR's CI
is the check, and if an existing expectation moves, the round stops and
asks the owner.

**Tests.** Sixteen new `.gwcase` fixtures, whose labels the owner
approved (below). Positives, `TEST_DISABLED` high with
`NO_PROD_CHANGE_IN_DIFF`:
`dead_def_if_false_pos` (the issue's reproduction),
`dead_def_method_if_false_pos`, `dead_def_class_if_false_pos` (two
units), `dead_def_if_not_true_pos`, `dead_def_if_compare_pos`,
`dead_def_empty_for_pos`, `dead_def_dead_match_pos`, and for Q3
`dead_def_pasted_copy_no_move_credit_pos` (D2),
`dead_def_survivor_no_duplicate_credit_pos` (D10) and
`dead_def_no_restructure_mass_pos` (D5). Controls, zero findings:
`dead_def_if_true_neg` and `dead_def_taken_out_of_if_false_neg`. The named
residual, zero findings: `dead_def_environment_condition_residual_neg`.
The new reading, zero findings: `dead_def_weakened_on_both_sides_neg`.
Guards on reading 1's narrowings, `ASSERT_WEAKENED` high with
`NO_PROD_CHANGE_IN_DIFF`: `dead_def_handler_of_raising_class_pos`, an
assertion weakened in a test in the handler of a `try` whose body
creates a class with `__slots__ = 1`, and
`dead_def_handler_of_raising_annotation_pos`, the same in the handler of
a `try` whose body sets `__annotations__ = None` and then annotates a
name. Each `TEST_DISABLED` positive keeps
a live test beside the dead one. No fixture carried `bypass:` in this PR;
the ten positives gained it at merge (R100, above).
`tests/test_issue499_dead_defs.py` adds 38 collected items, counted from
its parametrize lists: 13 dead arms and an async def, 11 live or
undecided arms (one a handler whose
annotated name may raise because `__annotations__` is rebound before the
`try`), 3 class-body arms, 2 dead
classes, two pins on what a dead def binds (an earlier def keeps its unit,
and a dead subclass keeps no deleted base running), a control (a later def
is the unit, as on main), and five engine pins (the key a deletion has,
the first three quiet edits under **Cost**, and an assertion moved into a
dead def, which stays `ASSERT_REMOVED` at high; the fourth quiet edit
follows from the dead-subclass pin). By reading, the live and undecided arms, the
control, three of the negative fixtures (all but
`dead_def_weakened_on_both_sides_neg`) and the two handler guards pass
on main as well; they guard the fix's edges. Together this adds 54
collected items (16 + 38): merged in integration batch 4 after #537,
#536, #534 and #538, the documented test count goes from 20356 to 20410;
CI's collection checks it. Nothing under `tests/gates`
changes.

**Fingerprints.** A finding keyed by a dead def's unit goes. In a file
with same-named defs, a dead def no longer takes a `name#N` place, so a
later unit of that name can take a lower number, and its findings new
keys (`docs/embedding.md`). No fingerprint scheme changes.

**Measurement** (R2, R101). Not measured. The fix merges in #484's round,
before the combined sweep's manifest is frozen, and shares #484's pair of
arms there: the standard and D-088 sets, compared between this fix's
parent commit and its merge commit, with every verdict change read. It runs
on LAPTOP-01AGNPJU only under EC POLICY `checkwash-pju-sweep` (T-546),
otherwise on the pool, after the owner approves the frozen manifest and the
engine commits. `NOT_RUN：工作機規則（POLICY work-machine-local），the sweep waits for the combined round; nothing ran on the work machine`.

Evidence status: prepared on a work machine where no pytest, checkwash or
product code ran; every expected result was traced by reading the code,
and this PR's CI is the first run.

The agent wrote this entry in #499's fix PR. The owner approved its
wording, readings 1 to 3, the fixture labels and the THREATMODEL edit in
round 6 (below).

The maintainer approved this entry on 2026-10-20: 「第六輪 G1～G6 全部照建議」 ("round
6, G1 to G6, all as recommended"), in reply to the agent's round-6 list for
the fourth wave, #534 to #539. The reply was a button whose text the
assistant wrote, which the owner chose. Its items for this entry, at #535's
head d673d5bc: G2 (F12) approves the wording of this entry (6c8624b2,
c625d240, 580cf542, 8c1c239a, d673d5bc), including the `resolve()` residual
and the fourth edit that now passes (also in the KNOWN-ISSUES-next #499 row,
94334aaa); of SPEC §2b and the `TEST_DISABLED` row (9caf293d), whose
sentence that a handler is dead when its try body cannot raise stays as
written; and of the THREATMODEL draft in #535's body, which calls
`dead_def_weakened_on_both_sides_neg` the new reading, not a control. Under
R100 that draft was applied at #535's merge after #538's, in integration
batch 4 (02c5b34f), with `bypass: 159` on the ten positives and
`benchmarks/FAILURES.md` edited by hand to match. G3 approves the 16
fixtures' labels, F13's 14 and the two added after review,
`dead_def_handler_of_raising_class_pos` and
`dead_def_handler_of_raising_annotation_pos` (both `ASSERT_WEAKENED` high,
as on main), and the parametrize row
`handler-of-a-try-whose-annotation-may-raise`. G4 (F14 and the review
narrowings) approves readings 1 to 3: the dead arms are those `entry` reads
as dead, with "cannot raise" as `_Walk.quiet` reads it; a dead class is no
Q9 subclass; a dead def takes no `name#N` place. It approves reading 1's two
narrowings too, a base-less class whose body binds any dunder name
(2b40842a) and an annotated name in a module that binds, deletes or spells
`__annotations__` (2fae0948), and their effect on D-144's readings of such a
try, such a class as the later binding in a try body included. G5 records as
residuals, with no issue, a dead class statement that a later module-level
`Cls.attr = ...`, `del Cls.attr`, `setattr` or `delattr` still names, as on
main, and the quadratic `quiet` work on a very long try body (the second
review's F4). Item F15, left out of the short list, was asked separately the
same day; the owner chose 「加 (Recommended)」 ("add"), an option the assistant
wrote. It approves THREATMODEL row 9's Python clause, the draft in item 4 of
#535's body, its wording under G2, and `bypass: 9` for
`dead_def_pasted_copy_no_move_credit_pos`; both were applied at the same
merge (02c5b34f). The readings' heading, the labels' and `bypass:`
sentences, the R100 paragraph and the closing sentence were rewritten to the
facts at merge under the C1/D3 precedent the same round approved (f42441d0).
This paragraph was written after the reply.

On 2026-10-20 the owner approved the paragraph above and the rewrites it
names with 「第七輪 H1～H5 全部照建議」 ("round 7, H1 to H5, all as
recommended"), a button whose text the assistant wrote: its item H2
approves together the round-4 and round-6 approval records, the C1/D3
rewrites at merge and the batch-4 merge sentences it lists, among them
SPEC §4's `TEST_DISABLED` row, where this entry's clause stands beside
#484's (the list called it §5). Its item H3 adds this entry's `name#N`
move to the finding fingerprints row of `docs/stability.md`, which lists
the moves of the next minor. These sentences were written after the
reply.

## D-167 (2026-10-19): an arrow test callback's simple return annotation no longer hides its parameters (#480)

Ruling 480 (owner, 2026-10-18, 「19 項全部照建議做（價值判斷的題也照你的傾向）」,
"all as recommended, value judgements included", in reply to the agent's
recommendation list; #480 issuecomment-6248630129 states each decision in
full): Q1 A, in the binder, with a narrowed step-back; Q2, the simple set
only; Q3, yes; Q4, the file's runner, for visibility only; Q5, a docs-only
PR first, which #521 was. The consolidated ruling of 2026-10-19
(「裁決總表全部照建議」, #480 issuecomment-6261651041) set #480 to P2 (R95)
and amended the released known-issues page (R34, R85); the reply was a
button whose text the assistant wrote. R1 (#419) lists
#480 among the ruled fixes that merge before the combined sweep's freeze,
while R95's option scheduled the fix after v0.9.0; E8 of the PR approval
list of 2026-10-19 (「PR 核可清單全部照建議」; this reply too was a button
whose text the assistant wrote) settled that in R1's favour, so this fix
merges before the freeze and R95 keeps the priority and the
docs' form. D-164 to D-169 were assigned to the pull requests of the
fourth wave. When integration batch 4 merged, all of them were on main.
This entry is D-167.

#480 reports that an arrow test callback with a TypeScript return
annotation, `(ctx): void =>`, is still a test unit, but the binder took
the arrow's parameters from the token just before `=>` (`bindings.py:468`
at 6d78d8dd). Under `(ctx): void =>` that token is `void`, which it
declared as the callback's context; `ctx` was never declared. Under
`Promise<void>` the token is `>`, and nothing was declared. So no assertion
on the context was read on either side, and the coverage scan dropped the
calls: weakening, deleting or rewriting one passed with zero findings and
`no_known_gaps`, in v0.8.0 and on main, for node:test (N1-N15, N22, N23),
AVA (N16-N18) and tap (N19-N21). node:test's `t` was read only through the
fallback for an undeclared `t` (C4, C5), AVA's `t` resolved to node:test's
context, and tap's subtest `t` was read only where the file's root was
named `t` too.

Implementation, lines at this PR:

- Q1 A, `frontends/javascript/bindings.py`. The arrow branch of
  `_functions` (`:509`) first asks `_annotated_parameters` (`:546`). From
  `=>` it steps back over a simple return type to a `:` and takes the
  paired `(...)` before it, which is accepted only where an arrow can
  start: first in the file, or after one of `_ARROW_STARTS` (`:45`: `(`,
  `,`, `=`, `=>`, `:`, `[`, `{`, `;`, `return`), with an `async` before it
  stepped over and held to the same test. Everywhere else, after `?`, a
  callee, `await` or an operator, the old reading stays. After `:`, `=` or
  `=>`, `_condition_waits` (`:593`) keeps it too where a `?` before the
  `(` still waits for its `:` (reading 1).
- Q2. Names and `_RETURN_TYPE_TOKENS` (`:43`): the set `_callback_body`
  steps over (`frontend.py:1064-1068`, `:1077-1081`) and so does the
  nested-arrow reader in `parse_javascript` (`frontend.py:2841`).
- Q3. `_test_callbacks` (`:1423`) lists, by name, the first parameter of
  each callback passed to a call that `_test_context` gives a context,
  read from the callback's own tokens by `_callback_parameter` (`:1391`),
  with the argument's span and the runner's kind. The last branch of
  `candidate` (`:1517`) makes a call whose root resolves to unknown, inside
  such a callback and named by its parameter (`_callback_context`,
  `:1452`), an `unresolved` candidate when its member passes the filter
  the unresolved families already apply (`:1503-1512`), for that runner:
  `assert` for node:test, `AVA_ASSERTIONS` for AVA, tap's names for tap.
- Q4. `_t_fallback` (`:368`) reads which of `node:test`, `ava` and `tap`
  the file names. When it names AVA or tap and not node:test, `resolve`'s
  table gives an undeclared `t` unknown (`:1183`), and
  `_candidate_families` gives it that runner's family (`:1343`). Every
  other file keeps node:test's context, as before.
- The three readers keep their workarounds (Q2): the nested-arrow reader,
  the catch reader (`exception_handlers.py:50-57`) and module mocks
  (`_annotated_bodies`). Their comments now say what the binder reads.

Readings the ruling leaves to the implementation; the owner approved each
as written (below):

1. **The guard reaches `=` and `=>`, not only `:`.** The ruling names one
   accepted position that still misreads, the inner `:` of a nested
   conditional (`c0 ? c1 ? y : (a) : b => b`), as a residual unless the PR
   guards it. By reading, the same misread happens after `=` and `=>`,
   where a conditional's consequent is an assignment or an arrow:
   `c ? x = (a) : b => b` and `c ? () => (a) : b => b` would declare `a`
   and leave `b` undeclared, which spelled `assert` would gain Node
   authority. One rule guards the three: after `:`, `=` or `=>`, the binder
   reads back over balanced brackets to the bracket, `;` or `,` that opens
   the expression, or to a line break where JavaScript ends the statement,
   counting each `:` against a `?`; a `?` left waiting keeps the old
   reading, and `??` is no conditional. The `:` of an annotated arrow's
   own return type answers no `?`: where the read meets `(...): T =>`, or
   `<U>(...): T =>` with a type parameter list, at a place an arrow can
   start, after any assignment operator (`_ASSIGNMENTS`, `:27`) or right
   after a `?`, it steps over that head, as TypeScript reads it, since an
   annotated arrow in a consequent, on the right of an assignment there
   included, needs a `:` after it. `_type_parameters` (`:645`) reads the
   list back over names, string and number literals, the simple set, `&`,
   `=`, an `=>` right after `)`, a conditional type's balanced `:` and
   `?`, and bracket groups by their pairs. So `c ? (x): T => (a) : b => b`
   declares `b`, as main does, where counting that `:` had declared `a`
   (found in #539's review), and so do `c ? x ||= (y): T => (a) : b => b`
   and `c ? <U>(y): U => (a) : b => b` (found in its third review). A
   type parameter list holding any other token, such as a template
   literal type or a negative number, is not stepped over; there the
   head's `:` still answers the `?`, and the alternate arrow's parameter
   is left undeclared where main declares it. The guard, steps
   included, only accepts fewer positions than the step-back alone. Its
   cost is two named misses, each an annotated arrow in a
   consequent that TypeScript reads as annotated because a `:` follows
   it: the alternate of a conditional nested in another's consequent
   (`c0 ? c1 ? y : (a): T => a : z`) and, since the step over a head, the
   body of an annotated arrow in a consequent
   (`c ? (p): T => (y): R => y : z`, and the same after an assignment
   operator or a type parameter list, as in
   `c ? x ||= (p): T => (y): R => y : z`) keep the old reading.
2. **Generic arrows stay a residual.** `<T>(ctx: T): void =>` puts `>`
   before the `(`, which is no accepted position, so it keeps the old
   reading; the binder does not take a generic arrow's parameters, and
   only reading 1's guard steps over the type parameter list. Q3 does not
   name such a test callback's first parameter either, since
   `_callback_receivers`, whose reading Q3 follows, does not: its context
   calls are no coverage candidates, and the report can still say
   `no_known_gaps`, unless the parameter is `t`, which follows the reading
   of a `t` that nothing declares (Q4).
3. **Whose parameter Q3 reads.** A callback passed directly to a call,
   first after `(` or `,`. Wrapping parentheses and `async` are stepped
   over; then `function` with its name, a parameter list followed by `=>`
   or by a return annotation's `:`, or one name followed by `=>`. Its first
   parameter is a plain name followed by `)`, `,`, `:`, `=` or `=>`, not
   `this`, as `_callback_receivers` reads it. A call is rooted at it when
   its root has that name, inside the callback's argument, and no
   declaration in a scope nested inside the callback, below the callback's
   own scope, declares the name again. Mocha's `this` and the callbacks of
   `.each`/`.for` tables, to which `_test_context` gives no context, are not
   read.
4. **What "imports or requires" means in Q4.** A string `node:test`, `ava`
   or `tap` after `from` or `import`, or as the only argument of
   `require(...)` or `import(...)`, but not of a method so named
   (`loader.require("tap")`, found in #539's review), anywhere in the
   file; `import type` counts. Only a `t` that no scope declares
   changes. A declared `t` with no provenance of its own, such as a
   helper's parameter, keeps node:test's family in the coverage scan, so
   row 126's "a `t` passed to a helper ... no coverage candidates" still
   holds.
5. **What the change does to an annotated arrow.** At an accepted
   position, the binder now scopes an annotated arrow exactly as the same
   arrow without its annotation: the same parameters and parameter tokens,
   the same body scope and the same position for `_test_context`. The
   costs below are what the unannotated spelling already has.

Costs, by reading:

- **Every annotated arrow is scoped by its parameters** (the ruling's
  cost of A). Its parameters shadow outer names in its body. A default in
  its list is a parameter token, so it is no longer recorded as a write to
  the name before its `=`, which had made that name unknown wherever an
  outer binding of it was read. Its body is a function scope where a
  `Promise<void>` or `number[]` return type left none: a `var` there stays
  there, a write there counts as a write from another function
  (`_written`), the catch reader's owner of a concise body's tokens is the
  arrow, and a module replacement written in a test callback so annotated
  belongs to that test (`module_mocks.py:564`, `:898`), where it was read
  as the enclosing function's: a `jest.mock(...)` in such a test at a
  file's top level is no longer read as a hoisted module mock.
- **Fingerprints.** A removed annotated-arrow test whose context
  assertions are read for the first time gets a TEST_DISABLED key built
  from its assertions instead of its qualname, as D-117 notes for #311; an
  exemption for such a finding needs renewing. No fixture pins one.
- **Q4.** In an AVA or tap file, a node:test-style `t.assert.*` on a `t`
  that nothing declares loses its authority; it is an `unresolved`
  candidate.
- **Q3** changes only diagnostics: stderr, the terminal report's head on
  a pass and its `!` lines, SARIF's tool-execution notifications and the
  coverage report. None of them changes a verdict, severity or exit code
  (`docs/assertion-coverage.md`).

Residuals, named in THREATMODEL row 160 and `docs/KNOWN-ISSUES-next.md`:
an object (N22), parenthesized (N23), function, conditional or literal
return type, whose body is not read and whose context calls are coverage
candidates only, `unresolved`, or Node's or tap's where a parameter named
`t` resolves through node:test's fallback or to tap's root `t` (Q2), and
a `t` that the fallback makes node:test's context gives only its calls
through `t.assert`, so in a file that names node:test beside AVA or tap,
AVA's or tap's assertions on it are no candidates and the report can say
`no_known_gaps` (found in #539's third review); the
positions the rule does not accept (for example after `?`, `yield`,
`export default` or a compound assignment) and those reading 1 guards;
generic arrows (reading 2); and the disagreement the ruling names: the
nested-arrow reader steps back with no position test, so for
`cond ? (a) : b => b` it takes `(a)` as the arrow's parameters while the
binder declares `b`. Removing the catch reader's and the nested-arrow
reader's workarounds waits for a run showing that no reading moves (Q2).

**Rule 2.** The ruling approves no change to an existing expectation, and
by reading none changes. The suite's annotated arrows were each traced:
`tests/test_js_foundation.py:110-111`, `:123-124` and `:189`,
`tests/test_js_parse_linear.py:112-113`,
`tests/test_issue363_js_catch.py:267`,
`tests/test_js_inline_call_index.py:28` and `:120`, and
`tests/test_issue196_188_5_merged_sources.py:194` and `:198` (a generic
arrow, unchanged). No `.gwcase` fixture and nothing under `tests/gates`
holds one. Every AVA or tap source in the suite declares its `t`
(`tests/test_issue233_ava_tap.py`, `tests/test_issue363_js_catch.py`,
`tests/test_issue429_js_tautology.py` and the eleven existing `js_ava_*`
and `js_tap*` fixtures), so Q4 moves none, and no test source has a test
callback whose first parameter the binder leaves undeclared, so Q3 adds no
candidate to any existing expectation. If CI shows an existing expectation
moving, the round stops and asks the owner.

**Tests.** Five new `.gwcase` fixtures pin row 160, with labels the owner
approved (below): `js_node_context_annotated_arrow_weakened_pos` (N1),
`js_node_context_annotated_arrow_deleted_pos` (N12),
`js_node_context_annotated_arrow_expected_rewrite_pos` (N2 with N14's
edit), `js_ava_annotated_arrow_weakened_pos` (N16) and
`js_tap_annotated_arrow_weakened_pos` (N19).
`tests/test_issue480_js_annotated_arrows.py` adds 85 collected items,
counted from its parametrize lists: the issue's rows N1-N21 and A1 and
eleven of its controls (33), the accepted positions (13) and the named
misses (5), the ruling's two conditional controls with the three guards of
reading 1 and four annotated consequents (9), whose parameter is a context
(5), Q3's candidates (6), the nested shadow (1), N22 and N23 through the
engine (2), Q4's runners (9) and Q4's cost (2). By reading, the documented
test count becomes 20500 (20410 + 5 + 85); CI's collection checks it.

**Measurement.** Per R1 and R2 this fix merges before the combined
sweep's manifest is frozen, and its merge gets its own before/after pair in
that run, which R3 places. The ruling asks that #212's JS/TS replay
measure the cost before a release ships the fix. The issue's scratch trial
of A predates #483's merge and names no host; if it ran on a work machine
after 2026-09-22 it is 未驗收 under EC POLICY `work-machine-local`, and
this PR's CI is separate, new evidence that does not clear it.
`NOT_RUN：工作機規則（POLICY work-machine-local），the sweep pair and the JS/TS replay wait for the combined sweep and the pool; nothing ran on the work machine`.

Evidence status: prepared on a work machine where no pytest, checkwash or
product code ran; every expected result was traced by reading the code,
and this PR's CI is the first run.

#480 closes once the combined sweep's before/after pair is read (round 6,
F39, below). The agent wrote this entry in #480's fix PR. The owner
approved its wording, readings 1 to 5 and the five fixtures' labels in
round 6 (below).

The maintainer approved this entry on 2026-10-20: 「第六輪 G1～G6 全部照建議」 ("round
6, G1 to G6, all as recommended"), in reply to the agent's round-6 list for
the fourth wave, #534 to #539. The reply was a button whose text the
assistant wrote, which the owner chose. Its items for this entry, at #539's
head 6a75ca59: G2 (F33) approves the wording of this entry (0ec2c898,
40c04b57, daf949c1, 8cc20bd1), of its THREATMODEL row and row 126's pointer
(77abbfdc, 8069f5e0, 41d3dbe5, 8ce1652d), with 77abbfdc's hand edit of
`benchmarks/FAILURES.md`, and of the #480 sentence of the released page
`docs/KNOWN-ISSUES-v0.8.0.md` (a4a7f027). That row was drafted as row 159;
under A98 it became row 160 at #539's merge into integration batch 4
(c21a8646), with row 126's pointer, its five fixtures and this entry's two
mentions. G3 (F34) approves the five fixtures' labels, N1, N12, N2 with
N14's edit, N16 and N19: `ASSERT_WEAKENED`, `ASSERT_REMOVED` and
`EXPECTED_VALUE_CHANGED`, all high. G4 approves the departure in reading 1
as decision 3 of #539's body states it (F35): the guard also reaches `=`,
`=>`, compound assignments and type parameter lists, keeps two named misses
at main's reading, and reads one exception differently from main, a type
parameter list holding a template literal type or a negative number. It
approves readings 3 to 5 (F37), and the ruling's two control "fixtures"
pinned as the `CONDITIONALS` pytest rows rather than as `.gwcase` negatives
(decision 4). G5 accepts as residuals, with no follow-up: generic arrows
stay unread (reading 2, F36); the costs found by reading, (a) to (e), and
Q3's diagnostic-only outputs as (f) lists them, which the combined sweep's
pair and #212's JS/TS replay measure (F38); and, disclosed only, that in a
file that names node:test beside AVA or tap, AVA's or tap's assertions on an
unread `t` are no candidates, as on main (decision 7). G6 (F39): #480 closes
once the combined sweep's before/after pair is read, and #212's replay stays
a release precondition, recorded on #212. The numbering sentence, the
readings' heading, the labels' sentence and the closing sentences were
rewritten to the facts at merge under the C1/D3 precedent the same round
approved (f42441d0). This paragraph was written after the reply.

On 2026-10-20 the owner approved the paragraph above and the rewrites it
names with 「第七輪 H1～H5 全部照建議」 ("round 7, H1 to H5, all as
recommended"), a button whose text the assistant wrote: its item H2
approves together the round-4 and round-6 approval records, the C1/D3
rewrites at merge and the batch-4 merge sentences it lists. This sentence
was written after the reply.

## D-168 (2026-10-19): a size refusal names the side it refused in `--format json`, still exit 2 (#454 (d))

#456's first ruling (issuecomment-6248011888, 2026-10-18, 「照建議」, "as
recommended") adopted Q1 (b) "with (d) added once the UNKNOWN follow-up is
ruled": keep exit 2 and add the explicit UNKNOWN entry #454 proposed.
#454's ruling of the same day (issuecomment-6248628332, item 6) left any
reuse of its question 3 entry, the `unread` entry of the findings JSON,
for an exit-2 run, and the test changes that needs, to #456. On
2026-10-19 R48 (issuecomment-6261648480 on #454 and 6261649184 on #456,
「裁決總表全部照建議」, "the consolidated ruling list, all as recommended";
the reply was a button whose text the assistant wrote) moved (d) to #454,
closed #456 as completed and said (d) still needs its own rule-2 approval.
The owner gave it the same day, typing 「q1 a ／ 核可」 in answer to the
round-5 approval list: item E3, option A (issuecomment-6270049974): "an
exit-2 run reuses this issue's `unread` entry to say explicitly that the
change was not analysed (UNKNOWN)", the three pins below may change to the
new output, and any other expectation that moves stops the round. D-164 to
D-169 were assigned to the pull requests of this round, prepared in
parallel. When integration batch 4 merged, all of them were on main. This
entry is D-168.

A changed path a detector must read, or a file the analysis reads as
context, refuses the run when a side is over the 1,000,000-byte source limit
(D-135): exit 2 and one stderr line naming path, side, size and limit, and
until now nothing on stdout. In hook-json, D-150 blocks the stop for the
change's own head or worktree side and keeps the #414 note otherwise.

Implementation (lines at this PR):

- `_cmd_check` (`cli.py:425-437`) catches `SourceOverLimit` from `_analyse`
  on the verdict diff. The hook-json block comes first, unchanged. Then,
  under `--format json` without `--emit-ir`, `_json_size_refusal`
  (`cli.py:991-1010`) writes the stderr line `main()` writes for the
  refusal in every other format (`cli.py:929-933`, `:936-939`), then
  `size_refusal_to_json` (`report/jsonout.py:43-57`), and returns 2.
  Otherwise the exception reaches `main()` as before.
- The document is `{"unread": [<entry>]}`. Its one entry is
  `unread_entry` (`report/unread.py:30-40`) of the side the refusal names,
  the four-key projection #454 writes for an unread side, so a field the
  side may carry (#455's prefix) stays out of it. It is written as the
  findings JSON is: sorted keys, two-space indent, UTF-8, one final LF.
- It is not a findings document: it carries no
  `checkwash_findings_version`, `run`, `findings`, `summary` or `verdict`.
  A consumer that checks the exit status, or requires the version as
  `docs/embedding.md` says to, reads it as the error it is and cannot read
  a pass from it. One that does neither and takes a missing `verdict` for
  no block can, where an empty stdout used to fail to parse (Contract,
  below).

**Readings where the ruling is silent**; the owner approved each as
written (below):

1. **Formats.** Only `--format json`. The ruling reuses "the question 3
   entry", which is the findings JSON's `unread` entry. Term and sarif keep
   an empty stdout on exit 2. A SARIF log with no result, uploaded to code
   scanning, may close open alerts, where an empty file fails the upload
   (GitHub behaviour, not checked from this repository); a term line would
   repeat the stderr line, which already names the four facts.
2. **Keys.** Only `unread`. A `run` object, the version, an `error` text or
   a `verdict` such as `null` or `"unknown"` would each be a new contract,
   and a `verdict` key would let a consumer that compares it with
   `"block"` read a pass. Without one, the capture classifier of
   `tools/r1_cost_capture.py` keeps such a run as `PRODUCT_ERROR_EXIT`
   (`:240-241`), as it did for an empty stdout.
3. **Which side.** Exactly the side the refusal names, one entry, so entry
   and stderr line match one to one. When both sides of a change are over
   the limit that is the base side (`engine.py:303`, `:314`; a #448
   residual), except where #455 names the side that holds the shebang; the
   hook block names the head or worktree side instead (D-150). Other unread
   sides of the same change, and other changes in the diff that were set
   aside, are not listed: the run stopped before their stderr notes.
4. **Which refusals.** Every `SourceOverLimit` that reaches `_cmd_check`.
   By reading, it is raised for a must-read change (`engine.py:303`,
   `:314`); a guarded read of a set-aside path (`engine.py:341`); the unread
   base side of a set-aside root `package.json` or `tsconfig.json`
   (`_base_root_file`, `engine.py:200`); and a context read through a
   snapshot reader, the working tree's (`gitio/snapshot.py:629`) or, with a
   range, the head snapshot's (`GitSnapshot.read`, `:433`, and `read_many`,
   `:208`), whose side may be one no change holds. These are the raise
   sites found by reading; the rule is the exception type. Not
   a root manifest, config, exemption list or `--task` file over the limit
   at the base, which `_analyse` reads before the analysis and which
   refuses as a `GitSourceOverLimit`, a `GitError` (`gitio/git.py:152-163`):
   `tests/test_issue415_oversized_sources.py:620` asserts an empty stdout
   for it and is not among the approved pins. Not the range-mode pytest
   configuration symlink target that D-150 lists, which refuses as a plain
   `EngineError` (`gitio/snapshot.py:322`), nor any other engine error.
   By reading, `read_config_many`'s check of a configuration's own size
   (`gitio/snapshot.py:281`) is a plain `EngineError` too. With a range, the
   collection-inventory and runtime-shadow consumers reach it for a pytest
   configuration the diff does not change (`collection_inventory.py:473`,
   `shadow.py:2694`). Whether another reader refuses such a file first, as
   a `SourceOverLimit`, was not traced, so such a run may print the document
   or nothing.
5. **`--emit-ir`** keeps an empty stdout: #454 item 6 keeps the IR free of
   unread sides, and a refused run has no IR.

**Contract.** The exit codes do not change, and neither does the frozen
exit-code row's text: term, json and sarif keep exit 2 for every engine
error. The findings document does not change, so `FINDINGS_VERSION` stays
2 and `docs/findings.schema.json` and `docs/stability.md` are unchanged:
the rules for moving the number (`docs/stability.md`, "When the number
moves") are about that document, and the new output is not one. It is a
new output on exit 2, where there was none. A consumer that ignores the
exit status and reads `verdict` with a default now parses a document where
it used to fail to parse; `docs/embedding.md` asks for the version check
that refuses it, and now describes the output. The next release is a minor
anyway (R54). No release is authorized (AGENTS.md rule 5).

Consumers read in this repository: the Action's check step runs term
(`action/secure.py:240-243`), and its comment step skips a run whose exit
code is not 0 or 1 (`:274-276`), so neither changes.
`tools/verdict_gate.py`'s `observe` already records exit 2 as an error; it
now names the missing keys instead of an invalid report. Two benchmark
scripts read `verdict` without checking the exit code (at the base,
`benchmarks/compare/run.py:34` and `benchmarks/decoy/harvest.py:130`), so
on a size refusal they would raise `KeyError` where they recorded an
engine error. Each now records exit 2, or a parsed document without
`verdict`, as an engine error, as it did unparsable stdout
(`benchmarks/compare/run.py:36`, `benchmarks/decoy/harvest.py:123`; round-6
item F11, prepared before the owner's answer, which approved it). CI never
reaches either read: `tests/test_compare_harness.py` stops `run.py` at its
argument checks. Outside this repository, by
reading checkwash-lab's combined-sweep harness at `6c8adef5`: exit 2 is
`PRODUCT_ERROR_EXIT` whatever stdout holds
(`workloads/acceptance_sweep/common.py:560`), but a pair counts rows whose
stdout bytes differ (`aggregate.py:245`), so a size-refusal row compared
between v0.8.0 and this code counts there.

D-150 says "#456 stays open for (d)". That no longer holds: R48 moved (d)
to #454, #456 is closed as completed, and this entry records (d). D-150
stays as written, as R48 says.

**Rule 2.** Three existing expectations change, as E3 approved, each from
an empty stdout to `{"unread": [entry]}` with exit 2 (test lines at this
PR's base, `9c19c344`):
`tests/test_issue415_oversized_sources.py:637` (a must-read test file, in a
range and in the working tree), `tests/test_issue456_hook_size_refusal.py:209`
(its json case, a context read) and `:255` (its json case only; term, sarif
and hook-json with `--emit-ir` keep `(2, "")`, and its single-stderr-line
assertion is unchanged). By reading no other moves: the base manifest pin
(`tests/test_issue415_oversized_sources.py:620`), the hook-json tests
(`tests/test_issue456_hook_size_refusal.py`, `tests/test_hook_runtime.py`,
`tests/test_issue414_worktree_directory_symlinks.py`) and the exit-2 tests
for other engine errors (`tests/test_standin_source_limits.py:170-171`,
`tests/test_config_snapshot.py:523`, `:534`,
`tests/test_issue500_root_task_path.py`, `tests/test_issue416_subdirectory_root.py`)
do not reach the new branch. Nothing under `tests/gates` changes. If CI
shows another expectation moving, the round stops for the owner.

**Tests.** `tests/test_issue454_size_refusal_output.py` adds 10 collected
items: the writer, byte for byte, also for a side with a #455-style field
(2); the CLI under `--format json` for both sides over the limit, a base
side alone in the working tree and in a range, and an untracked shell
script with no extension, each with exit 2, the document and only the
refusal's stderr line (4); `--format json --emit-ir` (1); a batch-limit
`EngineError` and a `RecursionError` keeping an empty stdout (2); and a
refusal for a side no change holds (1). By reading, the documented test
count becomes 20257 (20247 + 10); CI's collection checks it. The sweep
command calls `analyze` directly (`sweep.py:131-142`), so it does not move.

Evidence status: prepared on a work machine where no pytest, checkwash or
product code ran; every expected result was traced by reading the code, and
this PR's CI is the first run.
`NOT_RUN：工作機規則（POLICY work-machine-local），every behaviour above is read from source; no test, checkwash run or sweep was run`.

The agent wrote this entry in #454's pull request for (d). The owner
approved its wording and readings 1 to 5 in round 6 (below).

The maintainer approved this entry on 2026-10-20: 「第六輪 G1～G6 全部照建議」 ("round
6, G1 to G6, all as recommended"), in reply to the agent's round-6 list for
the fourth wave, #534 to #539. The reply was a button whose text the
assistant wrote, which the owner chose. Its items for this entry, at #534's
head 87f5b887: G2 (F6) approves the wording of this entry (9e25ece5,
f9e4cefa, 05aac9c6, d36f504d, 4199598a) and of SPEC §9 and its §4b pointer
(042988ec, d6071249), with F6's half-sentence, added in integration batch 4
after #536 (#455) merged (332f26c7, reworded to the approved text in a later
commit of the batch): where reading 3 and SPEC §9 say the refusal names the
base side when both sides are over the limit, they add "except where #455
names the side that holds the shebang". G4 (F7) approves readings 1 to 5:
only `--format json` prints the document; it holds only the `unread` key; it
names exactly the side the refusal names; it covers every `SourceOverLimit`
that reaches `_cmd_check`; `--emit-ir` keeps an empty stdout. G5 records as
residuals, with no issue, an unchanged pytest configuration over the limit
in a range, as reading 4 states it, not traced and not pinned (F8), and,
with `sys.stdout` closed, a second engine-error line from `main()` while
exit stays 2 (the second review's F4). G6: THREATMODEL gains one note for a
consumer that reads neither the exit status nor the version, with no code
change and its wording for a later round (F9); `docs/stability.md` does not
change (F10); and the benchmark fix stays in #534 (93bf2315), with the
consumer paragraph's sentence on it (d36f504d; F11). G1's item for #534, the
self-check exemptions for the E3 pin in #542, concerns no text here. The
numbering sentence, the readings' heading, the F11 clause and the closing
sentence were rewritten to the facts at merge under the C1/D3 precedent the
same round approved (f42441d0). This paragraph was written after the reply.

On 2026-10-20 the owner approved the paragraph above and the rewrites it
names with 「第七輪 H1～H5 全部照建議」 ("round 7, H1 to H5, all as
recommended"), a button whose text the assistant wrote: its item H2
approves together the round-4 and round-6 approval records, the C1/D3
rewrites at merge and the batch-4 merge sentences it lists, among them
README's two `--format json` sentences that b8798a8c anchored to the stop
and the KNOWN-ISSUES-next #454 row's F6 half-sentence (4079e353). This
sentence was written after the reply.

## D-169 (2026-10-19): TEST_DISABLED exemptions are content-bound, amending D-019 (#512)

Ruling 512 (owner, 2026-10-19, 「q1 a ／ 核可」, typed by the owner in reply
to the agent's round-5 approval list; #512 issuecomment-6270046393 reads it
as Q1 (a) and the rest of the list as recommended, and states each item)
answered the four questions of issuecomment-6263347530: Q1 (a), Q2 as
recommended, Q3 (a), and Q4 as already decided by R2. The same reply
approved round-5 item E2: existing pins that change only because of Q2 and
Q3 may change, and this PR lists each one. Ruling-list items R42, R43 and
R46 (owner, 2026-10-19, 「裁決總表全部照建議」, "the consolidated ruling
list, all as recommended"; the reply was a button whose text the assistant
wrote) had made this round of #421 its own P1 issue in the frozen list,
kept it in the same minor as round 1 (D-146), and put #421's missing JS
sibling test in this PR. D-164 to D-168 are the entries of the same round's
other pull requests (#455, #484, #499, #480 and #454's (d)). When
integration batch 4 merged, all six were on main.

#512 reports that TEST_DISABLED kept the legacy key, and an exemption
matches the whole key. A marker added was keyed by the marker's name, which
for an imperative `pytest.skip()` leaves out its guard, so after a guarded
skip was approved an unguarded one added to the same unit on a base that
lacks it also passed. A guard made always true and a guard removed shared
one `guard:<name>` key. A parametrize row deletion was keyed by the fixed
text `parametrize`, so after one row's deletion was approved any later row
deletion in the unit passed, and #428's JS/TS table rows take the same key.
A removed unit was keyed by its assertions' legacy text, a JS/TS one only
through the matcher's `(`, and a focus added to a file by one name.

**D-019, amended.** D-019 froze that `Marker.guard` is "deliberately *not*
part of marker identity: identity feeds fingerprints, fingerprints feed
recorded allowlists, and a doc-level refactor must not invalidate reviewed
exemptions", and kept its cost, THREATMODEL row 54, open "until there is an
allowlist migration story". D-146's route, retiring the old keys in a minor
release and re-reviewing once, is that story. Under Q1 (a) the sentence
still holds for the marker identity alignment pairs markers on, and so for
pairing, move detection and the findings a diff gives; it no longer holds
for the exemption key, which binds the guard. Q1 (b), the guard in the
marker identity as well, would have changed which markers pair and so which
findings appear.

How each answer is implemented (lines at this PR):

- Q2, the keys. `detectors/test_disabled.py` builds every key with `_key`
  (`:72-84`), which is `make_assertion_fingerprint` under the rule
  TEST_DISABLED: D-146's `assertion_identity` and `assertion_key`, under the
  scheme name `checkwash/assertion-fingerprint/v2`, giving
  `TEST_DISABLED/path/unit/v2:<64hex>`. The identity holds the legacy
  pre-image exactly as `make_fingerprint` built the key, the finding's
  `shape` as its kind, and no position. A marker added (`_marker_added_key`,
  `:97-109`; the shapes `marker_added`, `collection_control` and, for a
  conftest's `pytestmark`, `inert_mark`): the marker's text as the after
  text and its recorded guard as the context, null when none.
  `_marker_added_keys` (`:128-170`) finds which marker each finding added
  (reading 6), and when the added markers of a name cannot be told apart,
  `_unit_markers_key` (`:112-125`) binds every marker of the unit on both
  sides instead. A guard made always true or removed (`_guards`,
  `:180-196`): the guards before and after as the two texts, the after null
  when removed, and as the context what every marker of the name ran under
  on each side (`_conditions`, `:173-177`; reading 2). Parametrized cases
  removed (`_rows_gone`, `:215-237`): the rows deleted and the rows newly
  disabled, each a sorted list of argnames and cells, and the live counts
  before and after. A unit removed: the complete texts of its own
  assertions. A focus added to a file: the focus as the JS frontend
  records it, under the qualname `<file>` (reading 5). The texts are in
  `identity_text`'s form, so reformatting outside string literals keeps a
  key; spans, lines, messages, severities, file digests and revision labels
  stay out.
- `finding_marker` (`:240-258`) finds the marker D6 judges by rebuilding the
  key of each marker the unit added through `_marker_added_keys`, as
  `detect` builds them, since the key no longer is its name's.
- Q3 (a). `findings.py` adds `TEST_DISABLED_FINGERPRINT_RULES` (`:26-31`), a
  set of its own, so `ASSERTION_FINGERPRINT_RULES` stays the nine rules
  #421 ruled on. `fingerprint_state` reads a TEST_DISABLED key as it reads
  theirs (`:47-65`): a legacy one is retired, parsed and counted, never
  eligible. `fingerprint_issue` (`:106-113`) gives `allow` (exit 2),
  `doctor` and `check` a message that names #512, and
  `is_content_bound_fingerprint` labels the new keys `checkwash/v2` in
  SARIF. Nothing is migrated. checkwash's own ledger holds five
  TEST_DISABLED entries, all for merged pull requests and expiring between
  2026-10-31 and 2026-11-05; they become ignored records, and no current
  verdict changes.
- Q4 (R2). This fix's merge gets its own before/after pair in the combined
  lab-declared sweep. As for D-146, the replayed repositories hold no
  ledger, so the pair can confirm that nothing but keys changes; it cannot
  measure the new blocks or the re-review.

**Readings the ruling leaves to the implementation:**

1. **Which guard a marker added binds.** The recommendation names "for an
   imperative skip, its recorded guard". The key binds `Marker.guard` for
   every marker that records one: an imperative skip's enclosing `if`, and
   the condition a setup skip, a helper's skip, a later binding of the
   test's name or a `pytestmark` binding runs under, which the Python
   frontend records the same way. A decorator records none; its condition is
   in its name, which the legacy pre-image already holds. A JS/TS imperative
   skip (`ctx.skip()`, `t.skip()`, Mocha's `this.skip()`) records none
   either: the JS frontend does not record the condition it runs under, so
   a guarded one and an unguarded one of the same name get one key (a
   residual below). That is within the ruling's "its recorded guard";
   binding the condition would need the engine to record it.
2. **The two guard events.** Both have the shape `guard_weakened`
   (`inert_mark` in a conftest), so the event kind alone does not tell them
   apart, as the recommendation's sentence "with the event kind in the
   identity, the two events no longer share a key" reads. The guard after
   does: null when the guard was removed, the guard's text when it now
   always fires. For a guard made always true, the guard before is that of
   the base marker `evidence._mark_weakened_guards` compared, under its old
   name for a skip moved into or out of a helper (#272); for one removed, it
   is the base condition the message names, an `except` block's first line
   included. The guard after of a guard made always true is that of the
   first head marker of the name, the one the message names. Several
   markers can share a name, and these two texts come from one marker on
   each side: with base `if A: pytest.skip("1")` and `if B:
   pytest.skip("2")`, removing either `if` names `A` as the removed guard.
   So the key also binds, as its context, what every marker of the name ran
   under on each side, read as the removed-guard check reads it
   (`skip_condition`: its guard, or the first line of the `except` block it
   sits in, null when neither), each side sorted. Removing one of two
   guards of a name and removing the other are then two keys, and a guard
   made always true binds its own guards before and after among them. A
   third event has the same shape: a path gained by an unguarded
   `collect_ignore` (row 81). It has no guard on either side, so both texts
   are null and no path is bound (a residual below).
3. **Which rows.** A row is its table's argnames and its cell texts, read
   through `param_tables` as `diffalign._rows_lost` reads them, so a JS/TS
   `.each`/`.for` table's rows (#428) are read the same way. "Deleted" holds
   every row that ran before and is no longer written, an edited row's old
   text among them, since rows alone cannot tell an edit from a deletion;
   "disabled" holds the rows still written but newly marked off. Each list
   keeps its multiplicity and is sorted by its encoding. The live counts are
   those the message gives: a plain JS/TS test paired with a table counts
   1, and an uncounted table `unknown`. A side whose tables cannot be read
   gives no rows.
4. **A unit's assertions** are its own, in the side's order, not sorted;
   those reached through a helper method stay out, as they do of the legacy
   pre-image (306 Sub-Q10). A unit with no assertion binds an empty list.
5. **The focus key** keeps the legacy key's qualname `<file>`; the
   finding's `unit` stays null. Q2 says "the focus call's complete text".
   The key binds the text the JS frontend records for the focus, which is
   also the finding's evidence and message: the callee as written
   (`describe.only`, `fdescribe`), or the property text of an `only`
   option. The frontend does not record the title or the other arguments,
   so they are not bound, and binding them would need the engine to record
   more of the call. So an approval covers another focus of the same
   spelling added to the file (a residual below). A file-level focus is
   reported only when no unit of its own file reports being stopped by it,
   so wherever it sits the finding reports the same effect: under a runner
   that applies focus suite-wide, every test outside the file stops.
6. **No position, and several markers of one name.** The nine rules'
   ordinal and count tell identical copies of one assertion apart; each
   TEST_DISABLED shape binds its own texts instead. A unit can hold several
   markers of one name, one per imperative skip call, and alignment pairs a
   skip on its name alone and records only the names it leaves unpaired. So
   the marker it leaves unpaired is not always the one the diff added: a
   skip inserted above another of its name pairs with that one and leaves
   it unpaired. An earlier draft read the last head marker of the name, as
   the base read the marker's evidence. Then two skips added together
   shared the later one's key, so an approval of a guarded skip covered a
   diff that also added an unguarded one above it, and an inserted skip was
   keyed on the one already there. The markers a name added are read by content
   instead, as a multiset difference: each base marker of that name cancels
   one head marker of that name with the same text and guard, and the head
   markers left over, in the head side's order, are the ones added. So when
   the head holds more copies of a marker than the base, each copy beyond
   the base's is added. When there are as many as the name has findings,
   each finding binds one of them, in that order. Two different skips added
   together are then two keys, and an inserted skip gets the key it would
   have if it were added alone. When
   there are not (a marker of that name was also edited, one moved in from
   a helper, or alignment paired one with a marker of another name, as it
   pairs a decorator whose condition is spelled another way), no finding
   can be given its own, and each finding of that name binds every marker
   of the unit on both sides, each its name, text and guard, each side
   sorted: a stricter key, since any other marker change in the unit moves
   it. A finding's evidence is still the last head marker of its name, as
   on the base; only its key moves. So with several markers of one name the
   evidence can show another marker than the one the key binds, a residual:
   taking the evidence from the bound marker could move existing pins on
   the evidence text or span, so it is left for a follow-up the owner
   decides. UnitDelta gains no field for this:
   `--emit-ir` serializes it and tests rebuild it from that JSON, so the
   detector reads both sides' markers instead.
7. **Order.** Findings of one rule in one unit sort by key
   (`Finding.sort_key`), so the order of TEST_DISABLED findings in one unit
   can change. Gating spends no credit across them, so no severity depends
   on that order.

**Residuals** (row 136): a JS/TS imperative skip records no guard (reading
1), so an approval of a guarded one covers an unguarded one of the same
name; the rows of a table checkwash cannot read are bound only by their
counts (and when it is the head side's, every base row reads as deleted, a
stricter key); a path added to an unguarded `collect_ignore`
(row 81) binds no path, so an approval covers another path added to the
same control; a constant edited behind an unchanged guard (row 59) is bound
by the guard's text, so an approval covers another edit that makes the same
guard always true; a focus added to a file is bound by its spelling
(reading 5), so an approval covers another focus of that spelling in the
file; a marker-added finding's evidence is still the last head marker of
its name (reading 6), so when a unit holds several markers of one name it
can show another marker than the one the finding's key binds, and an
approval given from the evidence alone can exempt a marker the evidence
does not show; and an approval still covers the identical reviewed change
on a later diff, as D-055 intends.

**Fingerprints.** Every TEST_DISABLED finding has a new key, so every
recorded TEST_DISABLED exemption stops matching, and the reviewed change
must be re-run and approved again, in the same minor as the nine rules'
(R43), so users re-review once. Other rules keep their keys. SARIF
`partialFingerprints` for TEST_DISABLED move from `checkwash/v1` to
`checkwash/v2`. FINDINGS_VERSION and IR_VERSION stay 2: no IR field is
added. `docs/stability.md`'s fingerprint row lets a minor release move them;
this ships in the next minor (R54), never a patch.

**Pinned tests (rule 2, E2).** Changed only because of Q2 and Q3:
`test_issue196_guard_removal.py::test_the_finding_shares_the_guard_familys_identity`
(the legacy key, and `always.fingerprint == finding.fingerprint`, which
becomes one legacy key and two keys);
`test_issue196_setup_guards.py::test_a_removed_setup_guard_is_reported_with_the_guard_family_identity`
and `::test_a_setup_guard_that_now_always_holds_is_reported`;
`test_issue209_effects_pytestmark.py::test_the_fingerprint_is_the_marker_name_s`
and `::test_a_conftest_pytestmark_is_reported_at_info`;
`test_issue223_conftest_request_side.py::test_the_fingerprint_is_the_setup_markers`
(the module's skip fixture with the reason "x" and the conftest's, which
shared one key, now give two keys that refine one legacy key, since the key
binds the skip's text; the test also checks that the same skip in either
place is still one key);
`test_issue260_pytestmark_spellings.py::test_a_guard_made_always_true_or_removed_is_reported`,
`::test_a11_is_reported_under_its_mark_s_name` and
`::test_a_conftest_pytestmark_s_guard_guards_nothing_either`;
`test_issue261_suite_guard_removed.py::test_a_removed_guard_is_reported_for_every_suite_level_control`,
`::test_a_guard_moved_where_the_hook_reading_does_not_look_reads_as_removed`,
`::test_a_removed_guard_shares_the_identity_of_one_that_always_fires` (one
legacy key, two keys) and `::test_a_path_gained_by_an_unguarded_control_is_still_row_81`;
`test_issue263_string_conditions.py::test_the_marker_keeps_the_string_as_written`;
and `test_js_assertion_identity.py::test_removed_unit_joins_legacy_keys_but_reports_complete_assertions`.
Each legacy-key pin now checks that the v2 key's identity holds that legacy
key's pre-image, as D-146's `_refines` does. Three comparisons of two
findings in one unit (209's two-mark case, and 261's "add-marker" and
"module-level-if" cases) no longer depend on their order, which the key
decides. Test names that speak of one shared identity are left as they
are, as D-146 left `test_snapshot_expectations.py`'s. No `.gwcase`
expectation changes, and nothing under `tests/gates` changes. Another pin
that CI shows moving is listed for the owner before it is changed. By
reading, what readings 2 and 6 bind for several markers of one name moves
none of these pins again and no other: these pins compare legacy keys and
key inequality, not v2 digests.

**Cost.**
- **New blocks:** a TEST_DISABLED change under an exemption recorded for
  another change to the same unit.
- **Re-review:** every recorded TEST_DISABLED exemption.
- **Measured:** not yet; the combined sweep (Q4).

Rows 54 and 136 record the change.

Evidence status: when the change was prepared, no pytest, checkwash or
Python product code ran on the work machine; this PR's CI is the first
run. `NOT_RUN：工作機規則（POLICY work-machine-local），the tests and the sweep pair run in CI and in the combined sweep; nothing ran on the work machine`.

- Tests were added: 38 collected items in
  `tests/test_issue512_test_disabled_keys.py`, the issue's reproduction
  among them (ten pairs of changes that shared a legacy key, each keyed
  apart, and each second change left at high under an exemption recorded
  for the first; two of the pairs are a skip inserted above another of its
  name and one of two guards of a name removed, then the other), the
  several-markers cases of reading 6 and reading 2 (a guarded and an
  unguarded skip added together, an inserted skip's own identity, every
  condition of a guard event's name, and markers that cannot be told
  apart), and one in `tests/test_js_assertion_identity.py`, #421's JS
  sibling `toBe(1)` and `toBe(2)` (R46). None is under `tests/gates`. By
  reading, 37 of the 39 fail on this PR's base. Two pass there too: the
  R46 test, because #477 already binds the after text, so it pins a case
  #421 closed without a test; and the control that reformatting and moving
  keep a key.
- The documented test count is 20165 (20126 on integration batch 3,
  before this PR merged in integration batch 4, + 39).

The agent wrote this entry in #512's fix PR as a draft for the owner's
approval of its wording. Readings 1, 2 and 6, the residuals and the
tests were revised after a second review of the PR found that several
markers of one name were keyed on one of them and that a JS/TS imperative
skip records no guard. A third review then found that reading 6 described
a set where the detector subtracts multisets, and that the evidence can
show another marker than the key binds; reading 6 and the residuals were
revised again. The owner approved the wording as it then stood in round
6 (below).

The maintainer approved this entry on 2026-10-20: 「第六輪 G1～G6 全部照建議」 ("round
6, G1 to G6, all as recommended"), in reply to the agent's round-6 list for
the fourth wave, #534 to #539. The reply was a button whose text the
assistant wrote, which the owner chose. Its items for this entry, at #537's
head 41f12c0d: G2 (F21) approves the wording of this entry (8b93952f,
59860313, df64856e, 41f12c0d), of SPEC §6 (07fa73a7, ed8fa0f0, 691726ca,
f1084628, b406e155), of THREATMODEL rows 54 and 136 (231b2202, bc1be4b9,
122ab38c, 8d7640cd, 37a15d1d), with `benchmarks/FAILURES.md` row 136's shape
cell, and of the KNOWN-ISSUES-next #512 row; F21's change to row 136's shape
("then add another of a different spelling", 122ab38c) stays. G4 approves
the focus key binding the recorded spelling, not the title, a departure kept
as a residual (F22); reading 1, which binds every recorded guard: setup,
helper, #424 and `pytestmark` (F23); reading 2, in which the two guard
events share `guard_weakened` and are told apart by the guard after, and
each key also binds the conditions every marker of its name ran under on
each side (`skip_condition`), within Q2 and E2 (F24); `test_issue223`'s
setup-marker pin moving to two keys, as E2 (F26); and reading 6, with the
stricter fallback that binds every marker of the unit on both sides
(decision 9). G5 keeps as residuals, with no issue (F25 and the reviews'
F2): a JS/TS imperative skip (`ctx.skip()`, `t.skip()`, `this.skip()`)
records no guard; an unreadable table binds only its counts; an unguarded
`collect_ignore` binds no path; row 59 binds the guard, not the constant; a
file-level focus binds its spelling; and a marker-added finding's evidence
can show another marker of its name than the one its key binds, with no
follow-up and the evidence as on main (decision 10). G1's item for #537, the
self-check exemptions in #542, concerns no text here. The numbering and
closing sentences were rewritten to the facts at merge under the C1/D3
precedent the same round approved (f42441d0). This paragraph was written
after the reply.

On 2026-10-20 the owner approved the paragraph above and the rewrites it
names with 「第七輪 H1～H5 全部照建議」 ("round 7, H1 to H5, all as
recommended"), a button whose text the assistant wrote: its item H2
approves together the round-4 and round-6 approval records, the C1/D3
rewrites at merge and the batch-4 merge sentences it lists. This sentence
was written after the reply.

## D-170 (2026-10-20): the perf gate's budgets widen to 3.5 s and 1.5 s

**What failed.** `tests/gates/test_perf.py::test_many_files_within_budget`
(500 changed files, budget 2.5 s, median of three) failed main's push run
at `adea2350` (integration batch 2, #533) on windows-latest 3.12 and 3.13,
at 2.54 s and 3.08 s (run 39284516868, attempt 1). The same `src/` tree
(`27aa68e1`) passed both Windows legs on its pull-request run 39261842873
(head `c7cd4f57`), and on run 39267059803 (head `9c19c344`, the same tree)
it failed windows-latest 3.12 at 2.68 s in attempt 1 and passed in
attempt 2. A whole-run rerun of 39284516868 (attempt 2) passed every leg.
The gate also failed on pull-request heads, between 2.51 and 3.03 s:

- run 39282092543, #536 at `e3aaf6bb`: ubuntu-latest 3.12, 2.51 s;
- run 39292624506, #536 at `2a6ee2f9`: windows-latest 3.13, 2.54 s;
- run 39292929666, #534 at `87f5b887`: windows-latest 3.13, 2.84 s;
- run 39296882259, #535 at `d673d5bc`: ubuntu-latest 3.12, 2.53 s, and
  windows-latest 3.12, 2.78 s;
- run 39299206598, #539 at `6a75ca59`: ubuntu-latest 3.13, 2.89 s, and
  windows-latest 3.11, 2.66 s;
- run 39290428941, #540 (integration batch 3) at `d271b87c`:
  windows-latest 3.12, 2.65 s in attempt 1 and 3.03 s in attempt 2, where
  `test_large_single_diff_within_budget` (3000-line diff, budget 1.0 s)
  also failed, at 1.01 s.

The runs of #537 and #538 at their heads (39298901010, 39293460730) had
no perf failure.

**What #541 measured.** The temporary diagnostic #541 (closed unmerged;
run 39304315238, artifacts `perf-diag-*`) took `src/` and the gate from 20
commits and timed `analyze` on the gate's two inputs with the gate's own
helpers, in one fresh, idle process per commit, after one untimed
warm-up, in five interleaved rounds, on ubuntu-latest 3.12 and
windows-latest 3.12 and 3.13. Each value below is a commit's median
per-round ratio to batch 1 (`0eff0e52`), for the 500-file shape and then
the 3000-line diff. Two A/A pairs have identical `src/` trees (main at
#507 `1714d293` and at #526 `f324eb2c`; batch 2 after #531 `737f13b8`
and main `adea2350`); their gap is the noise floor.

| Commit | ubuntu 3.12 | windows 3.12 | windows 3.13 |
|---|---|---|---|
| v0.8.0 `f02b5d8a` | 0.97 / 0.96 | 0.94 / 0.97 | 0.97 / 0.96 |
| batch 1 `0eff0e52` | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 |
| batch 2 through #525 `3767b7dd` | 0.99 / 0.97 | 1.04 / 1.06 | 1.01 / 1.01 |
| batch 2 through #527 `3e37a701` | 1.08 / 0.98 | 1.05 / 1.08 | 1.08 / 1.03 |
| main `adea2350` | 1.08 / 1.08 | 1.10 / 1.09 | 1.10 / 1.06 |
| #540 `d271b87c` | 1.05 / 1.03 | 1.06 / 1.08 | 1.09 / 1.14 |
| A/A gap, #507 and #526 | 0.02 / 0.10 | 0.02 / 0.02 | 0.00 / 0.00 |
| A/A gap, +#531 and main | 0.02 / 0.00 | 0.04 / 0.04 | 0.01 / 0.03 |

Read from these:

- Integration batch 2 made the engine about 5 to 10 percent slower on
  these shapes: 1.06 to 1.10 at main, 1.05 to 1.11 at its A/A partner.
- The largest single step is #527 (#434, D-156) in the 500-file shape,
  +0.09 on ubuntu 3.12 and +0.07 on windows 3.13. On windows 3.12 no step
  in that shape exceeds +0.03, within that runner's larger A/A gap
  (0.04). In the 3000-line shape the largest step is #531's on ubuntu
  3.12 (+0.06, where the first pair's gap is 0.10) and windows 3.13
  (+0.04), and #525's on windows 3.12 (+0.04).
- The six wave-4 heads (#534 to #539, on batch 2's tip `9c19c344`, whose
  `src/` tree is main's) add little: none is more than 0.05 above main in
  either shape on any runner, except #536 in the 500-file shape (1.18
  against 1.10) and #534 in the 3000-line shape (1.21 against 1.06), both
  on windows 3.13 only.
- The absolute seconds (one engine in an idle process; about 1.1 to 2.1 s
  for 500 files) are not comparable to the budgets, which the gate meets
  inside `pytest -n 2`, beside a second worker.

**Decision.** On 2026-10-20 the agent asked the owner how to handle the
perf gate, saying that batch 2 had made the engine about 5 to 10 percent
slower and that the gate had no margin left in CI and failed even on
ubuntu, and offering three options the agent wrote. The owner chose
「放寬預算 (Recommended)」 ("widen the budgets"), whose description, also
written by the agent, read: 「500 檔 2.5→3.5 秒、單一大 diff 1.0→1.5
秒，DECISIONS 記下 #541 的量測。gate 原意是抓數量級的退步，不是 10%。先合這個
PR，其他的再合。」 ("500 files 2.5 to 3.5 s, one large diff 1.0 to 1.5 s;
DECISIONS records #541's measurements. The gate is meant to catch an
order-of-magnitude regression, not 10%. Merge this PR first, the others
after.") The other two options kept the budgets: one looked into #527
first, the other reran the whole run whenever it was red.

`BUDGET_MANY_FILES_S` is now 3.5 and `BUDGET_LARGE_DIFF_S` 1.5.

**Why.** The gate's docstring says its thresholds are "generous enough
not to be flaky on a loaded laptop while still catching an
order-of-magnitude regression". After batch 2 the 2.5 s budget no longer
had that margin on the hosted runners: one `src/` tree passed and failed
it from run to run. 3.5 s and 1.5 s sit above the highest medians these
runs recorded (3.08 s and 1.01 s), and an order-of-magnitude regression
is still far over both. A drift of 5 to 10 percent is not what the gate
exists to stop.

**Not changed.** The median of three runs (2026-09-01); the macOS skip
of the two budget checks (2026-10-01), which this entry does not end or
extend; the assertion messages; and `test_pathological_file_does_not_hang`
with its 10 s bound. No test is added or removed. `tests/gates/README.md`
and `docs/enterprise.md` state the new budgets; older records keep the
old ones.

**Follow-up, named and not opened.** What #527 costs in the 500-file
shape could be looked at later. No issue is opened, following the
owner's practice of opening fewer issues.

Evidence status: prepared on a work machine where nothing ran; every
number above is read from CI job logs or #541's artifacts (the gaps and
steps are differences of the artifacts' values, rounded to two places),
and this PR's CI is the first run of the new budgets.
`NOT_RUN：工作機規則（POLICY work-machine-local），the widened budgets run first in this PR's CI`.

The agent wrote this entry. On 2026-10-20 the owner approved its wording
as #543 merged it, with 「第七輪 H1～H5 全部照建議」 ("round 7, H1 to H5,
all as recommended"), a button whose text the assistant wrote. Its item
H1 also approves #543's change to `tests/gates/README.md`, which the list
described as the numbers only: 1.5 s and 3.5 s, with a parenthesis that
names the old budgets, the date and this entry. It keeps the two budget
checks skipped on macOS, whose runners vary the most, until they are
revisited before 1.0. H1 does not name #543's edit to
`docs/enterprise.md`. This paragraph was rewritten after the reply;
before it, it said the wording awaited the next approval round.

## D-171 (2026-10-22): #419's opaque refusal is turned off for v0.9.0 after its pre-registered stop (#419)

**What stopped.** Call 1 of the combined sweep ran on LAPTOP-01AGNPJU under
EC POLICY `checkwash-pju-sweep` (T-546): lab `prep/v090-freeze-20261021` at
`6d49fb60`, manifest sha256
`52a451cf62e5ca9ddfbf24288299b64d97346a5b5bdf6d6bc3865b7a19332520`, finished
2026-10-21 20:30Z, human-authorized local PJU, NOT EC pool. `419-arm2` and
`419-arm3` each show three pass → block moves on the same three d088
commits; `419-arm1` shows none. The commits are:

- httpx `0296c2bbb9885bbe1b1e3210d9e3efa7a817038d` (`ASSERT_WEAKENED`,
  `tests/client/test_proxies.py`, beside `scripts/check`);
- starlette `e396f079a5b9a9610ad7d241f17f2e34fd4283ad` (`TEST_DISABLED`,
  `tests/test_schemas.py`);
- werkzeug `ab6150fa49afc61b0c5eed6d9545d03d1958e384` (`ASSERT_WEAKENED`,
  `tests/test_wsgi.py`).

Each move is a predicted P1 move (warn → high, `REPAIR_EVIDENCE` dropped,
`OPAQUE_PROD_CHANGE_NOT_EVIDENCE` added; #419 issuecomment-6329503938). None
has a native-extension source, so option (d) does not apply. The commits are
not adjudicated.

**Decision** (owner, 2026-10-22, 「K1～K3 全部照建議」, "K1 to K3, all as
recommended"; the reply was a button whose text the assistant wrote):

- K1 (A): v0.9.0 ships without the refusal, by D-141 C1's revert route. A
  plain revert conflicts with later changes (#306, #463, #471, #473), so
  #553 turns the refusal off. The candidate is rebuilt on that `main`, R29
  is settled for it, the sweep pairs that use the candidate run again on it,
  and `/clear` uses it.
- K2 (A): calls 2-4 continue, and `opaque419` and `polyglot419` do not run.
- K3 (A): the stop is recorded on #419.

**Follow-up decisions** (owner, 2026-10-22, 「L1～L11 全部照建議」, "L1 to
L11, all as recommended"; a button whose text the assistant wrote). They
approve:

- #553's approach and text (L1) and the expectation moves below (L2);
- the allow keys (L3, #554);
- this wording (L5).

L7 settles R29 for the new candidate without a new run. It composes the
accepted R29 (v0.8.0 → `141accee`, no moves) with the sweep supplement
(`141accee` → the new candidate, whose only accepted moves are #419's
inverse P1/P2 moves), under EC POLICY `work-machine-local`'s last clause.
That holds only if the supplement holds its acceptance line.

**What changes.** #553 empties `gating.OPAQUE_REFUSED_RULES`. Clause 3's
opaque-change evidence again reaches every oracle finding except an
unguarded suite control (D-028), Python tests and conftests included, as in
v0.8.0. `OPAQUE_PROD_CHANGE_NOT_EVIDENCE` is not printed. Its code stays,
unreachable, for the redesign. D-161's chain keeps its order. Expectation
moves under rule 2, each approved by name on 2026-10-22:

- the seven `_neg` cases and `conftest_hook_guard_opaque_prod_neg` back to
  their pre-#464 bytes;
- the seven `_pos` successors, the six `opaque_refused_*` cases and
  `tests/test_issue419_opaque_refusal.py` deleted (their inputs remain at
  4f884070);
- the `data_read` and `data_edited_at_the_limit` rows back to warn and pass,
  reversing the second ruling of 2026-10-16;
- `test_issue208_209`'s tuple back to `REPAIR_EVIDENCE`;
- #473's
  `test_a_refused_opaque_change_keeps_its_label_beside_a_readable_edit`
  deleted.

Documented count 20508 → 20488.

**This supersedes,** for v0.9.0 and on `main` from #553:

- 419.Q1 (b), 419.Q5 (b) and the second ruling's two #448 rows;
- D-141's amendment of 209.Q4's reading, so a guarded conftest control takes
  opaque evidence again.

These stand: 419.Q3 (row 93, clause 1), the E3 correction, 419.Q7 (row 132,
#463) and 419.Q8 (row 130).

**Residuals.** Route B is open again in Python tests and conftests
(THREATMODEL item 4, row 2), and Route A is unchanged (row 93). #419 stays
open with the three commits as data.

**Contracts.** No fingerprint moves, and there is no `FINDINGS_VERSION` or
`IR_VERSION` bump (severity and escalators are outside `make_fingerprint`).
R29, settled for the new candidate as above (L7), checks that v0.9.0 has no
verdict move against v0.8.0.

Evidence status: `NOT_RUN：工作機規則（POLICY work-machine-local），#553's checks run in its CI and R29 is settled again for the new candidate`.

The agent wrote this entry; the owner approved its wording on 2026-10-22
(L5). It was then aligned with the owner's L7 decision on R29 and with the
full list of conflicting changes.

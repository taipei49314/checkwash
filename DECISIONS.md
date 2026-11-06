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

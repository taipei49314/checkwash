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

After the v0.11.0 cycle, on 2026-11-04 at 14:35:46Z, Nelson wrote
「現在做一版checkwash 成本開始提升上來了」 (a release now costs more). Claude
counted where the time went. Since 2026-11-02, 15 PJU collections had taken
966 minutes, and the v0.11.0 critical path took about 24.5 hours. Asked
"Should I draft a concrete plan to cut each checkwash release's cost?",
Nelson chose the button 「出方案」 at 14:38:39Z and added at 14:39:42Z
「要特別去看時間成本」 (look at the time cost in particular). Claude's plan then
broke one receipt down from its command ledgers: an ordinary receipt took
about 56 minutes (qualify 31.5, pytest 20) and a release-stage receipt about
83 (qualify 32, verdict gate 23, pytest 23), almost all on one core at a time
of LAPTOP-01AGNPJU, a 24-core host. Claude's multiple-choice question listed
four options. One was 「收據加速」, described as
「改收集器和兩個 bridge：pytest 從 2 個 worker 改成約 6 個，三輪 qualify 同時跑。粗估每張收據省 25～40 分鐘、每版關鍵路徑省約 3 小時。先在 PJU 實測三次，另開 PR，0.12 前做。」.
At 14:42:29Z Nelson selected it together with two other options. At 14:44:38Z
he withdrew one of those two and wrote 「做綁機器的時間成本就可以 主要是要減少時間成本」
(the time bound to the machine is enough; the point is to cut time). At
14:45:53Z he withdrew the other: 「拉長發版間隔 這個也不用」. Asked "Should I start
the receipt speed-up now in this session?", he chose the button 「現在開始」 at
16:44:02Z. Claude wrote the questions, the option labels and their
descriptions. The rest of this entry is Claude's under the pre-1.0
delegation.

What changes:

- The collector runs the full suite with 8 xdist workers instead of 2.
  The option text said about 6. Claude chose 8 because the host has 24
  cores and two full local runs with 10 workers took 8 min 46 s and 11 min 28 s.
  Both bridges accept 2, from the earlier collectors, and 8. A
  dispatch can verify a receipt collected before this merge, and the
  count does not change which tests run. Any other count is refused.
- The source, wheel and pyz qualify -> inventory chains run at once. Each
  writes only its own records, logs and nested ledger, and each inventory
  reads only its own qualification. `run_record` takes a lock around the
  shared command-ledger update. The first failure, in distribution order,
  is raised after all three chains finish.
- `tools/verdict_gate.py` gains `--jobs N` (default 1). Up to N cases run at
  once, each in its own repository, and a case's engines still run one
  after another. Failures merge in case order, so the receipt equals a
  `--jobs 1` run. The release collector passes `--jobs 6`. This was not in
  the option text; Claude added it under 「做綁機器的時間成本就可以」, because
  the gate took 23 of a release-stage receipt's 83 minutes.
- `traced_worker` takes a lock around each nested row's stream appends and
  ledger write. A helper's subprocesses can then run on threads while every
  recorded offset still selects exactly that command's bytes. The bridges
  already match nested verdict rows to cases by argv and directory, not by
  order, so they did not need to change for this.

Measurements on LAPTOP-01AGNPJU (Windows, CPython 3.11.9,
`HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL`):

1. The gate alone. The 185 cases and 4 engines of the v0.11.0 rotation
   proposal run (D-197) were run again with `--jobs 6`. The receipt equals,
   as parsed JSON, that run's serial receipt (`98d04534…`). It took
   4 min 12 s instead of 16 min 2 s.
2. A full release-stage `pr` collection of this branch's `94e87cea`, by
   the new collector (capture run 41877624633), took 43 minutes. v0.11.0's
   release-stage collections took 82 to 86 minutes, and #586's took 98.
   pytest took 12.0 minutes (22,431 passed, 25 skipped, 67 subtests). The
   three qualify -> inventory chains took 18.8 minutes together, each
   qualification 15.0 to 16.4 minutes; one after another they had taken
   about 35. The verdict gate took 7.1 minutes, and its 185 cases passed.
   The new release bridge's dry run verified the receipt locally, with the
   five check names and 22,456 collected tests. The receipt was not
   published.
3. An ordinary receipt of the same commit, by the new collector, took
   31.5 minutes. v0.11.0's ordinary receipts took 55 to 60. pytest took
   11.2 minutes, and the chains took 18.0. The new ordinary bridge's
   `verify` mode verified it locally, with four checks, 22,456 tests and
   283 qualification cases. It was not published.

Hosted test workflows remain disabled. This pull request's own receipt is
collected by main's collector, the one it replaces; receipts collected after
the merge use the new one. None of the three measurements was published.

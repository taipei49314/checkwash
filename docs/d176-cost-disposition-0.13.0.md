# D176 cost disposition for 0.13.0

This is a new, source-bound Antigravity decision under Nelson's pre-1.0
delegation recorded at the top of [RELEASING](RELEASING.md):

> 照著繼續做 完整spec在裡面 一樣我只卡1.0發佈前 其餘你可以自主推

and Nelson's one-time 0.13.0 release and post-audit instructions:

- Session `5472d923-3651-42a1-9267-6490cb024f59` at `2026-11-15T14:24:06Z`
  (`2026-11-15T22:24:06+08:00`):
  > 開一個session 對整體做一次檢查 沒問題後就發
- Session `c8f1073f-a39c-4c95-a65f-90c9037eff91` at `2026-11-15T17:34:59Z`
  (`2026-11-16T01:34:59+08:00`), after discussing the 2026-11-15 external
  read-only pre-release audit (`Q1`–`Q6`):
  > 可以 照你的建議走 開個新session? 需要用到goal 或其他技能嗎

Antigravity (on LAPTOP-01AGNPJU) makes this disposition on that delegation's
terms: risk decisions after independent review (RELEASING, *Takeover execution
and current cost decision* and *v0.13.0 release authorization and preparation*),
with normal independent review kept. This record does not claim that Nelson
personally reviewed this D-176 disposition text. Normal release gates remain,
and it does not authorize 1.0.

**Review.** One read-only sub-agent reviewed the first draft `38a0c787` against
`gating.py`, the earlier `checkwash-lab` records (`ae6ed8dc` and `6b27b9ea`),
and the session transcript (`_e1_escalation_reason` and `[]` on
`differences.json` were fixed there); after the 2026-11-15 eight-agent external
read-only audit and `#616`–`#621` landed on `main`, this record was rebound to
final `main` `978d015e1d614448eb393403601cbb3b0f33f79a` (`src/` tree
`cfd205d7b913d867e9e3452841978ae38a01e77e`) and `checkwash-lab` `ec15f59d`.
The review is recorded in the release pull request; it is not a PASS.

## What is owed

[D-187](../DECISIONS-archive-3.md) accepted, for 0.10 only, two costs of
D-176's narrow refusal (opaque production changes do not prove that a caught
Python test or conftest assertion can still fail): the three known uvloop
false blocks, and the explicitly unmeasured remaining-history risk
([0.10 record](d176-cost-disposition-0.10.0.md)). In 0.11.0
[D-190](../DECISIONS-archive-4.md) removed the three uvloop costs, and earlier
source-bound dispositions accepted the remaining risk for 0.11.0 only
([0.11.0 record](d176-cost-disposition-0.11.0.md)) and for 0.12.0 only
([0.12.0 record](d176-cost-disposition-0.12.0.md)), each scoped to its own
release's `src/` trees. Because the 0.12.0 record covers only 0.12.0's `src/`
trees, 0.13.0 needs its own disposition.

## What 0.13.0 changes and what was measured

For this rule 0.13.0 changes nothing. A broad `except` finding in a Python
test or conftest has no unit (`unit is None`), so its only repair-evidence
route is the opaque-change fallback (`_file_repair_evidence` in `gating.py`),
which D-176's refusal removes before [D-199](../DECISIONS-archive-5.md)'s
refusal is reached (`gating.py`, `_evaluate_oracle_evidence` and
`_e1_escalation_reason`):
the finding keeps v0.12.0's labels (`OPAQUE_PROD_CHANGE_NOT_EVIDENCE` where an
opaque production change exists) and blocks or passes as on v0.12.0. Without
D-176's refusal, D-199 would still refuse the same route at the same severity,
labelled `REPAIR_EVIDENCE_REFUSED`. Phase 2's structural decomposition of
`gating.py` (#607, ratified in [D-212](../DECISIONS.md)) changed no gating
condition or label; [D-210](../DECISIONS.md) and [D-212](../DECISIONS.md) touch
only unit-scoped Python findings on projected or set-aside `helper_function`
units (`BROAD_EXCEPT_ADDED` remains file-scoped with `unit is None`); and
D-190's relay reading is unchanged: a broad `except` that relays the failure
unchanged to an asyncio future the test awaits, in the bounded shape SPEC §4
reads, is not counted as added.

So the risk is identical to 0.12.0's and 0.11.0's: an honest broad `except`
added around an assertion in a Python test or conftest, beside an opaque
production change, blocks at high unless D-190 proves it a failure relay. A
new record is needed only because the 0.12.0 one covers 0.12.0's `src/` trees.

Both runs RELEASING names ran on LAPTOP-01AGNPJU (Windows 11, CPython 3.11.9,
`HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL`) on 2026-11-16 UTC, comparing the
published v0.12.0 zipapp (`checkwash.pyz`, SHA256
`4ef6eda2d4ff5b378c12874f43b825be3ce2d8ef97c2f1c5f44bfae06ee18cb2`) with the
final candidate `src/` tree `cfd205d7b913d867e9e3452841978ae38a01e77e` of main
`978d015e1d614448eb393403601cbb3b0f33f79a` (RELEASING, *v0.13.0 release
authorization and preparation*):

- **The targeted diagnostic.** v0.12.0 and the candidate each pass the three
  uvloop inputs (`7b202ccf644396a4ae8ff8053578058f5023ac63`,
  `2081db8927dc2d3a66b7c8d7aa317d71aba198f9`, and
  `9cba7493a152e5a77bbde9a32143d84433d1cd3d`) with identical reports, and a
  probe that recorded both engines' findings shows none (`checkwash-lab`
  `ec15f59d`, `notes/r29-comparison-013-antigravity-20261116/uvloop/probe.json`,
  SHA256 `59e941a1d5bec5cb93517a405250eef051e5d1dec321915d0d8020915e7417f4`).
  These three are the shape this risk names — honest broad `except` handlers in
  tests beside opaque `.pyx` changes — and they stay passing because D-190
  proves them relays.
- **The fixed-corpus comparison.** All 3,600 in-sample commits give identical
  exit codes and identical `--format json` reports apart from `run` (0 outcome
  moves and 0 report differences; `checkwash-lab` `ec15f59d`,
  `notes/r29-comparison-013-antigravity-20261116/`). Its sets hold no uvloop
  commit, and D-176's refusal is identical in both engines, so it shows neither
  how the reading treats the three known relays nor how often history holds an
  honest relay that D-190 misses.

Neither run measures the remaining history. The old R4 census stays partial
and consumed: 881 completed comparisons, of which three returned envelopes
keep seven omitted-file occurrences, and one partial plus 6,553 unattempted
members leave 6,554 incomplete comparisons. No new census ran. The honest
relays D-190 does not read remain listed in
[KNOWN-ISSUES-v0.11.0](KNOWN-ISSUES-v0.11.0.md), in the row *Failure relays:
the shapes read*; 0.13.0 does not change that reading.

## Decision and limits

After independent review, Antigravity accepts D-176's explicitly unmeasured
remaining-history risk for **0.13.0 only**, on these grounds:

- The refusal guards a known cheat: without it, as on v0.9.0
  ([D-171](../DECISIONS-archive-2.md)), a one-line opaque production edit held
  a broad `except` that swallows an assertion at warn, which passes by default
  (#419's Route B). Since 0.12.0, D-199 also refuses that route if D-176's
  refusal were removed, so the guard does not rest on D-176 alone and the cost
  is unchanged either way.
- The only known costs, the three uvloop false blocks, stay removed by D-190
  on the 0.13.0 candidate.
- The cost is a visible, conservative block, not a missed cheat. The finding
  names the file and the handler's first line with its whitespace removed
  (uvloop's `exceptExceptionasex:`), not its line or test, and a reviewed
  exemption on the base side lets an honest change through. That exemption's
  key binds only the rule, the file and that first line, so until the entry is
  removed or expires (at most 180 days) it also exempts every other handler
  with the same normalized first line in that file.

This disposition covers **0.13.0's `src/` trees only** (`cfd205d7…` plus the
release pull request's version string in `src/checkwash/__init__.py` at `A` and
`src/checkwash/doctor.py` own-pin line at `R`). It is not a history PASS, a
census, an adjudicated false-positive rate, a standing waiver for 0.14+ or 1.0,
or an update to `THREATMODEL.md` item 4 / row 2 (which stay maintainer-owned).

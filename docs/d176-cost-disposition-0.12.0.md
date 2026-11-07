# D176 cost disposition for 0.12.0

This is a new, source-bound Claude decision under Nelson's pre-1.0
delegation, recorded at the top of [RELEASING](RELEASING.md):

> 照著繼續做 完整spec在裡面 一樣我只卡1.0發佈前 其餘你可以自主推

which he handed to Claude with 「Checkwash 一樣給你」. Claude (Claude Code on
LAPTOP-01AGNPJU) makes it as the delegate RELEASING names, on that
delegation's terms: risk decisions after independent review (RELEASING,
*Takeover execution and current cost decision*), with normal independent
review kept (*Pre-1.0 repair continuation instruction*). This record does not
claim that Nelson personally reviewed it. Normal release gates remain, and it
does not authorize 1.0.

**Review.** One read-only Claude sub-agent reviewed this record with the
rest of the release pull request's first draft, `bcd487cc`, against
`gating.py`, the comparison records and the session transcript; no reviewer
wrote the subject. It found that the draft said D-199 widens this refusal,
while for this rule nothing changes; that it leaned on Nelson's choice of
D-199 as if D-199's measured cost priced this risk, which it cannot; that it
said neither run holds such a commit, while the three uvloop inputs are that
shape; and that its scope named only one of the release's two `src/` trees.
Each is fixed below. The review is recorded in the release pull request; it
is not a PASS.

## What is owed

[D-187](../DECISIONS-archive-3.md) accepted, for 0.10 only, two costs of
D-176's narrow refusal (opaque production changes do not prove that a caught
Python test or conftest assertion can still fail): the three known uvloop
false blocks, and the explicitly unmeasured remaining-history risk
([0.10 record](d176-cost-disposition-0.10.0.md)). In 0.11.0 D-190 removed the
uvloop costs, and Claude accepted the remaining risk for 0.11.0 only
([0.11.0 record](d176-cost-disposition-0.11.0.md)), whose scope is that
release's `src/` tree. [D-199](../DECISIONS.md) records that "The 0.12.0
release needs a new D-176 cost disposition, as the 0.11.0 one covers only
that release's `src/` tree". This is that disposition.

## What 0.12.0 changes and what was measured

For this rule 0.12.0 changes nothing. A broad `except` finding in a Python
test or conftest has no unit, so its only repair-evidence route is the
opaque-change fallback (`_file_repair_evidence`), which D-176's refusal
removes before D-199's refusal is reached (`gating.py`, E1): the finding has
no evidence left to refuse, keeps v0.11.0's labels
(`OPAQUE_PROD_CHANGE_NOT_EVIDENCE` where an opaque production change exists)
and blocks or passes as on v0.11.0. Without D-176's refusal, D-199 would
refuse the same route at the same severity, labelled
`REPAIR_EVIDENCE_REFUSED`. D-190's relay reading is unchanged: a broad
`except` that relays the failure unchanged to an asyncio future the test
awaits, in the bounded shape SPEC §4 reads, is not counted as added.

So the risk is exactly 0.11.0's: an honest broad `except` added around an
assertion in a Python test or conftest, beside an opaque production change,
blocks at high unless D-190 proves it a failure relay. A new record is
needed only because the 0.11.0 one covers that release's `src/` tree.
D-199's measured cost does not price this risk: each option D-199 measured
was main `7cd8549c`'s `src/` with only `gating.py` changed, a base that
already refused this route, so none could move a commit on it.

Both runs RELEASING names ran on LAPTOP-01AGNPJU (Windows, CPython 3.11.9,
`HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL`), comparing the published v0.11.0
zipapp with the candidate `src/` tree
`bcad1326db9c0b9c4ac4960d49ee0dc62aaebc65` (RELEASING, "v0.12.0 release
under the pre-1.0 delegation"):

- **The targeted diagnostic.** v0.11.0 and the candidate each pass the three
  uvloop inputs with identical reports, and a probe that recorded both
  engines' findings shows none (checkwash-lab `c58bc9bf`,
  `uvloop/probe.json`). These three are the shape this risk names, honest
  broad `except` handlers in tests beside opaque `.pyx` changes; they pass
  because D-190 proves them relays, and the three costs D-190 removed stay
  removed.
- **The fixed-corpus comparison.** 19 of the 3,600 in-sample commits move
  from pass to block, none of them on `BROAD_EXCEPT_ADDED`: D-199's 18 block
  on weakened, removed or disabled tests, and D-201's one on skips. Its sets
  hold no uvloop commit, its records keep reports only for members that
  differ, and D-176's refusal is the same in both engines, so it shows
  neither how the reading treats the three known relays nor how often
  history holds an honest relay that the reading misses.

Neither run measures the remaining history. The old R4 census stays partial
and consumed: 881 completed comparisons, of which three returned envelopes
keep seven omitted-file occurrences, and one partial plus 6,553 unattempted
members leave 6,554 incomplete comparisons. No new census ran. The honest
relays D-190 does not read are listed in
[KNOWN-ISSUES-v0.11.0](KNOWN-ISSUES-v0.11.0.md), in the row *Failure relays:
the shapes read*; 0.12.0 does not change that reading.

## Decision and limits

After that review, Claude accepts D-176's explicitly unmeasured
remaining-history risk for **0.12.0 only**, on these grounds:

- The refusal guards a known cheat: without it, as on v0.9.0 (D-171), a
  one-line opaque production edit held a broad `except` that swallows an
  assertion at warn, which passes by default (#419's Route B). In 0.12.0
  D-199 would refuse that route too if D-176's refusal were removed, so the
  guard no longer rests on D-176 alone; the cost does not change either way.
- The only known costs, the three uvloop false blocks, stay removed by D-190
  on the 0.12.0 candidate.
- The cost is a visible, conservative block, not a missed cheat. The finding
  names the file and the handler's first line with its whitespace removed
  (uvloop's `exceptExceptionasex:`), not its line or test, and a reviewed
  exemption on the base side lets an honest change through. That exemption's
  key binds only the rule, the file and that first line, so until the entry
  is removed or expires (at most 180 days) it also exempts every other
  handler with the same first line in that file, in later changes too, a
  swallow of an assertion included.

The refusal stays, and this decision changes no severity, strength,
alignment, label, allowance or verdict. This is not a history PASS, a
completed census, an adjudicated rate or a standing waiver, and it resumes
no R1 to R4 grant. It applies to the 0.12.0 release's two `src/` trees, the
two differences the fixed-corpus candidate rule allows (D-196): A's,
`bcad1326` with the version string at 0.12.0, which the tag, the Action and
a CLI installed from the tag run (D-200); and M's, which R's own pin line
also changes, from which the PyPI package and the pyz are built. Any other
`src/` change needs a new disposition. Nelson may overrule it, as with any
decision under the delegation.

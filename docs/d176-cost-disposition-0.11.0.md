# D176 cost disposition for 0.11.0

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

**Review.** The review of the release pull request's first draft,
`81146cfa`, found this disposition missing: a Workflow run of 37 read-only
Claude agents (three lenses, one adversarial verifier per finding) and one
Gemini 4 Argon run, which completed. This record was then written, and a
second Workflow run of 18 read-only Claude agents (two lenses, one verifier
per finding) reviewed it at `c1af1bc7`: it found that the record named no
review, overstated what an exemption allows and drew one conclusion its
evidence did not support. Each is fixed below. No reviewer wrote the
subject. The review records are in the private checkwash-lab repository,
`43c3c2d7`, `notes/release-011-review-claude-20261103/`: round 1
`round1-workflow-wf_62e734f0-1e4.json` (SHA256
`559f230682a6fe964f9f3861c4049662866f9961e508b06b4fc3ab20c78bdede`), the
Argon response and triage under `argon/`, and round 2
`round2-workflow-wf_cadf129f-904.json` (SHA256
`fc2a32419cc76cc2a26c5165534515925fe865e878d3095949cc7d41fe20e7c4`).

## What is owed

[D-187](../DECISIONS-archive-3.md) accepted, for 0.10 only, two costs of
D-176's narrow refusal (opaque production changes do not prove that a caught
Python test or conftest assertion can still fail): the three known uvloop
false blocks, and the explicitly unmeasured remaining-history risk
([0.10 record](d176-cost-disposition-0.10.0.md)). D-190 and D-191 left both
open for 0.11: D-190 says the remaining risk "is not yet accepted for 0.11,
and the 0.11 release record will disposition it after R29 and the targeted
diagnostic on the final tree", and D-191 calls that "a separate delegated
disposition". This is that disposition.

## What 0.11.0 changes and what was measured

D-176's unit-less refusal is unchanged in 0.11.0 (D-190, *Unchanged*). D-190
adds only that a broad `except` which relays the failure unchanged to an
asyncio future the test awaits, in the bounded shape SPEC §4 reads, is not
counted as added, and its bound keeps 0.11 from reporting an addition that
0.10 would not (THREATMODEL row 171).

Both inputs D-190 named ran on 2026-11-02 UTC on LAPTOP-01AGNPJU (Windows,
CPython 3.11.9, `HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL`), comparing the
published v0.10.0 zipapp with the candidate `src/` tree
`6f83616ef1d46009e8388cb011920d1420d2a959` (RELEASING, "v0.11.0 release under
the pre-1.0 delegation"):

- **The targeted diagnostic.** v0.10.0 blocks each of the three uvloop
  inputs (one, one and two HIGH `BROAD_EXCEPT_ADDED`, each with
  `OPAQUE_PROD_CHANGE_NOT_EVIDENCE`); the candidate passes each with no
  finding. The three known costs are gone in 0.11.0.
- **The fixed-corpus comparison.** With both engines, all 3,600 in-sample
  commits gave identical exit codes and identical reports apart from the
  `run` block. So 0.11.0, the relay reading included, moved no in-sample
  commit. Its sets hold no uvloop commit, and D-176's refusal is the same in
  both engines, so it shows neither how the reading treats the three known
  relays nor how often history holds an honest relay that the reading
  misses.

Neither run measures the remaining history. The old R4 census stays partial
and consumed: 881 completed comparisons, of which three returned envelopes
keep seven omitted-file occurrences, and one partial plus 6,553 unattempted
members leave 6,554 incomplete comparisons. No new census ran. What the risk
is: an honest broad `except` added around an assertion in a Python test or
conftest, beside an opaque production change, still blocks at high unless
D-190 proves it a failure relay. The honest relays D-190 does not read are
listed in [KNOWN-ISSUES-v0.11.0](KNOWN-ISSUES-v0.11.0.md), in the row
*Failure relays: the shapes read*.

## Decision and limits

After that review, Claude accepts D-176's explicitly unmeasured
remaining-history risk for **0.11.0 only**, on these grounds:

- The refusal guards a known cheat: without it, as on v0.9.0 (D-171), a
  one-line opaque production edit holds a broad `except` that swallows an
  assertion at warn, which passes by default (#419's Route B). D-191's
  residual counts on it: the #419 row of
  [KNOWN-ISSUES-v0.11.0](KNOWN-ISSUES-v0.11.0.md), which states that
  residual, names this refusal first in what still blocks. 0.12 is to
  change D-191's residual, with its design going to Nelson first (D-196).
- The only known costs, the three uvloop false blocks, are removed by D-190.
- The cost is a visible, conservative block, not a missed cheat. The finding
  names the file and the handler's first line with its whitespace removed
  (uvloop's `exceptExceptionasex:`), not its line or test, and a reviewed
  exemption on the base side lets an honest change through. That
  exemption's key binds only the rule, the file and that first line, so
  until the entry is removed or expires (at most 180 days) it also exempts
  every other handler with the same first line in that file, in later
  changes too, a swallow of an assertion included.

The narrow refusal stays, and this decision changes no severity, strength,
alignment, label, allowance or verdict. This is not a history PASS, a completed census, an
adjudicated rate or a standing waiver, and it resumes no R1 to R4 grant. It
applies to the 0.11.0 release's `src/` tree: `6f83616e` with the version
string at 0.11.0 and `doctor`'s own pin line set by R, the two differences
the fixed-corpus candidate rule allows (D-196). Any other `src/` change needs
a new disposition. Nelson may overrule it, as with any decision under the
delegation.

# External field run, 2026-09-01 — landing note

**Status: two-rater, resolved.** Rater 1 is the field-run maintainer
(FINAL_REPORT.md); rater 2's full per-block pass is in
[ADJUDICATION.md](ADJUDICATION.md) — 67 FP / 7 TP-policy / 0 UNCERTAIN,
with 74/74 agreement on the tampering axis (zero true tampering). On
2026-09-01 the owner adopted rater 2's labels as final; those verdicts
are now the dataset's labels. The one remaining open item is the
supply-chain scope question
([#54](https://github.com/taipei49314/checkwash/issues/54)), which is a
SPEC decision, not a label.

## What this is

Thirteen external projects, 2,300 human-reviewed non-merge commits, run
black-box against the released single-file zipapp — engine untouched, no
network, no Actions minutes. 74 blocks (3.22%; 3.18% excluding the
in-corpus project). Zero engine errors.

- [FINAL_REPORT.md](FINAL_REPORT.md) — the three-round total report
- [OUT_OF_SAMPLE_REPORT.md](OUT_OF_SAMPLE_REPORT.md) — the earlier round
- `*_sweep.json` — raw per-project sweep output (13 files; blocked commits
  carry their findings inline)
- `*_sweep.err` — non-empty stderr captures (black, httpie)

## Era notes (accuracy, not edits)

The reports are landed verbatim; two facts have moved since they were
written and are corrected here rather than by rewriting the record:

1. **Tested artifact**: `greenwash.pyz` from release v0.1.49 — the tool's
   name at test time. The project has since renamed to **checkwash**
   (v0.2.0 identity, v0.2.1 repository); the engine paths exercised here
   are unchanged by the rename.
2. **Repro command**: `releases/latest/download/greenwash.pyz` now serves
   nothing — the latest asset is `checkwash.pyz`. To reproduce against the
   *tested* build, download `greenwash.pyz` from the v0.1.49 release
   specifically.
3. **Engine era**: every number in these reports was produced by the
   v0.1.49 engine. v0.2.2 (R1, issue #53) has since fixed the largest
   false-positive family this adjudication identified, and the three
   exemplar commits re-verify to zero findings on v0.2.3 (black
   pure-insertion 3→0, tornado e6d3f49 1→0, sympy ed75b73d 13→0). **The
   full 2,300-commit corpus has not been re-swept on the fixed engine, so
   no updated block rate is claimed** — the 74/2,300 figure describes
   v0.1.49, and any improvement beyond the three verified commits is
   unmeasured until a re-sweep runs.

## What this run is for

The maintainer's cost ranking (report section 4) was the initial detector
roadmap input. The second-rater pass revises the ranking
(ADJUDICATION.md, "Mechanism families"): the top target is now the
**phantom-finding family** — unit/def-use identity breaking on pure
insertions, base-class changes, and long test functions with reused
variable names (19+ blocks, trivially reproducible from black's trio) —
ahead of (2) move credit for file splits/tier moves — D2/D10/row 92,
(3) uniform mechanical-rewrite collapse, and (4) the original row-86/91
cross-file resolution. The E6/CI families earned a no-change verdict
across all 2,300 commits.

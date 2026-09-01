# External field run, 2026-09-01 — landing note

**Status: preliminary.** Single-rater adjudication by the maintainer; a
second-rater pass is in progress and will land beside this file. Per the
report's own limitations section, nothing here enters the published
benchmark numbers until formal adjudication completes.

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

## What this run is for

The maintainer's cost ranking (report section 4) is the detector roadmap
input: (1) project-local base-class oracle resolution — rows 86/91,
(2) move credit for file splits and helper removal — D2/D10/row 92,
(3) collective assert-rewrite compensation. The E6/CI families earned a
no-change verdict across all 2,300 commits.

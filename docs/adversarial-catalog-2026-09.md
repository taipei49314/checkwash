# September 2026 catalog: release boundaries and known limitations

Snapshot reviewed 2026-09-06. This page indexes the early-September public
reports and their disposition. It is a dated status summary, not a new
experiment or a claim of comprehensive coverage. Issue numbers below belong
to GitHub; **THREATMODEL row 77 is a different identifier**.

The released CLI/pyz is v0.2.12 (`e05c37f0e1673cdf218ec62fcfb7c6712cce704b`).
The reviewed main baseline is `aa84ad5d67f672486ef431feb0f60ef10f0a92a4`.
Open candidate branches are not part of either released artifact. Consult
the linked item for changes after this snapshot.

## Engine reports and candidate work

| Public references | Scope | Status at this snapshot | Meaning for v0.2.12 |
|---|---|---|---|
| [#84](https://github.com/taipei49314/checkwash/issues/84), [#90](https://github.com/taipei49314/checkwash/issues/90) | Outcome / collection coverage | Issues open | Known residual coverage reports; no released closure is claimed here |
| [#85](https://github.com/taipei49314/checkwash/issues/85), [#88](https://github.com/taipei49314/checkwash/issues/88), [#91](https://github.com/taipei49314/checkwash/issues/91) | Stand-in installation family | Open; [PR #97](https://github.com/taipei49314/checkwash/pull/97) is a draft candidate | Candidate changes are not shipped |
| [#89](https://github.com/taipei49314/checkwash/issues/89), [#92](https://github.com/taipei49314/checkwash/issues/92) | Expected-value provenance family | Open; [PR #98](https://github.com/taipei49314/checkwash/pull/98) is a draft candidate | Candidate changes are not shipped |
| [#86](https://github.com/taipei49314/checkwash/issues/86), [#95](https://github.com/taipei49314/checkwash/issues/95) | Runtime subject identity family | Open; [PR #99](https://github.com/taipei49314/checkwash/pull/99) is a draft candidate | Candidate changes are not shipped |
| [#93](https://github.com/taipei49314/checkwash/issues/93), [#94](https://github.com/taipei49314/checkwash/issues/94), [#96](https://github.com/taipei49314/checkwash/issues/96) | Subject-input / oracle classification | Open; maintainer classification remains necessary | No automatic relabeling of expected results or claim that the disagreement is resolved |
| [#87](https://github.com/taipei49314/checkwash/issues/87) | Honest rename rejected | Open precision report | Track as a false-rejection report, separately from coverage escapes |

## THREATMODEL row 77 correction

The Windows runner entry remained Open while row 87a and the v0.1.16 history
already recorded the named handling. This documentation correction aligns
row 77 with that existing implementation and adds row 77 to the two existing
fixture metadata references. Fixture bodies and expected outputs are unchanged.

The evidence is a static correspondence between the released source, its
historical decision record and named fixtures. This pass did not replay those
cases. Closure is limited to those named forms; it does not establish complete
cmd.exe or PowerShell semantics. See [THREATMODEL](../THREATMODEL.md) and the
generated [failure ledger](../benchmarks/FAILURES.md) for the precise boundary.

The failure-ledger generator also now retains lettered row identifiers, so
existing references such as 87a are no longer silently omitted. Adding a
missing catalog reference is not a newly discovered or newly fixed detector.

## Corpus and smallestlie evidence

| Public reference | What it contributes | How to read it |
|---|---|---|
| [checkwash-corpus PR #9](https://github.com/taipei49314/checkwash-corpus/pull/9) | Correction to the cross-model natural-arm report | Open report correction. Retain its distinct fixed / weakened / failed / no-op populations and weakened-only denominator |
| [checkwash-corpus PR #10](https://github.com/taipei49314/checkwash-corpus/pull/10), [#11](https://github.com/taipei49314/checkwash-corpus/pull/11) | Measurement-classifier corrections | Open corpus work, not checkwash engine fixes; do not count them as released coverage gains |
| [smallestlie PR #12](https://github.com/taipei49314/smallestlie/pull/12), merged at `47b1a34a50aedc03c29710455d0bb472767aa6be` | Public M6 report includes a false acceptance against checkwash v0.2.12 | Concrete evidence against a complete-coverage or 1.0-ready claim; not an estimate of natural user behavior |

Natural task work and instructed adversarial work answer different questions.
Do not combine their denominators, turn a classifier correction into an engine
fix, or treat a candidate branch's result as a released-version result. This
index deliberately leaves aggregate scores with their source reports.

## What remains before stronger claims

Each release claim needs an installed version, a dated case or population,
an adjudication scope and the artifact that actually contains the change.
An open issue is not made closed by a green unrelated CI run. Likewise,
documenting a limitation is not itself evidence of acceptable adoption cost.

The [1.0 review](stability.md#what-must-change-before-10) is **NOT MET**.
The current [public-launch brief](releases/v0.2.12-public-launch.md) invites
bounded alpha trials while keeping these limitations visible. Dedicated
refactor precision is the next-quarter focus; its current 24/60 block rate
must remain separate from the historical six-repo 27/1800 false-positive rate.

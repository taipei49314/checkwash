# Publication verification record template

Copy for the authorized version and replace every `PENDING` with evidence or
an explicit unresolved status. This file is not a release grant or a passed
receipt. Before public publication, public-only executions remain PENDING.

| Subject | Identity / evidence | Result |
| --- | --- | --- |
| One-time maintainer publication grant | PENDING exact version and record | PENDING |
| Final PR head / actual CI checkout / trees | PENDING full SHAs | PENDING |
| Development full pytest | PENDING run ID, attempt, jobs, actual collection, skips | PENDING |
| Source/wheel/pyz assertion qualification | PENDING exact source, each receipt digest | PENDING |
| Candidate source/archive inventories | PENDING wheel, sdist, pyz bytes/digests and inventories | PENDING |
| Final PR verdict gate | PENDING head SHA, run ID, attempt | PENDING |
| Main commit and verdict gate | PENDING merge SHA/tree, run ID, attempt | PENDING |
| Previous verdict baseline | PENDING tag, commit and protected disposition | PENDING |
| Real public tag identity | PENDING name, native tag object, peeled commit, tree | PENDING PUBLICATION |
| Public-tag full CI / source / visitor / verdict | PENDING exact commit, run IDs and attempts | PENDING PUBLICATION |
| Release-event source and installed-tag identity | PENDING receipt, installed commit/version | PENDING PUBLICATION |
| Actual release build / inventories | PENDING event SHA, run ID, attempt, all distributions | PENDING PUBLICATION |
| Actual GitHub downloads | PENDING asset IDs, sizes and SHA256 | PENDING PUBLICATION |
| Actual PyPI delivery | PENDING wheel/sdist bytes, comparison, upload evidence | PENDING PUBLICATION |
| Public installation and exercised commands | PENDING version/commit, demo/check results, environment | PENDING PUBLICATION |
| Advertised manifest / README promotion | PENDING reviewed commit after public verification | PENDING PUBLICATION |
| Verdict baseline rotation | PENDING separate reviewed PR/disposition | PENDING PUBLICATION |
| Recommended Action and downstream re-pins | PENDING separate applicable authority and evidence | PENDING SEPARATE DECISION |

Retain actual failures, cancellations, skipped jobs, overwritten candidate
attempts and limitations. A successful candidate cannot fill a public-release
row. A source review cannot fill an artifact or actual-installation row.

Describe supported deployment scope and remaining limits. Keep source
qualification, use cost/refusal accounting, detector acceptance, and adoption
status distinct. Missing independent adoption remains UNSATISFIED until the
required evidence exists; it is not waived by a successful build.

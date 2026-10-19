# Known issues for v0.7.0

The fixed preparation comparison and bounded source/cost dispositions are
complete and accepted. All 6,071 pairs / 12,142 arms, 54 added coverage losses,
raw errors/skips, legacy UNKNOWN and known noise remain disclosed. Publication
results are recorded separately from those preparation receipts.

| Scope | Known limit and disposition |
| --- | --- |
| #363 synchronous JS/TS catch reader | Typed declaration headers, labels, classes, async/promise completion, unsupported branches/loops/nested try/finally and cross-function rethrows remain outside the bounded proof. Parent callback invocation/reachability is not propagated. Direct rethrows and setup-only catches are controls. Review unsupported control flow manually and run the tests. |
| #357 imported-helper guards | Guards retain defining-source evidence and bounded value closure. Incomplete namespace isolation and compatibility-token fail-open remain; dynamic/uncertain bindings stay unknown. Production helpers, methods, generators, deeper imports and source-read limits are not a general execution model. |
| Git input failures | Changed nonregular paths and required regular source over the 1,000,000-byte cap can refuse analysis before detector filtering. Full preparation recorded 159 candidate errors against 105 baseline errors, including 54 new pass-to-error coverage losses (27 Python and 27 JS/TS). Preserve exit 2, stderr and missing finding fields; an error is not a pass or zero findings. The exact first runtime caller/path/side and unrecorded budget counts remain UNKNOWN. |
| Worktree snapshots | Non-atomic worktree reads and undetected change-and-revert remain limits. Use committed inputs where reproducibility matters and preserve diagnostics. |
| Fixed JS/TS noise | Ordinal 759 has an Intl compatibility/helper limitation and 1362 an expected-receiver alias limitation; these are the two added pass-to-block pairs. Consistent local renaming at 1222 and representation/order-alignment cases 1348/1387/1435/1464/1499 remain disclosed. Some predicates disappear or change subjects. Raw high/block findings and duplicate/order ambiguity are retained; no blanket semantic-equivalence claim, automatic suppression or independently established FP label follows. |
| Cost | Both-analyzed candidate-minus-baseline CLI elapsed median/p95: Python +2.4827/+7.4827 seconds; JS/TS +2.1435/+7.9754 seconds. All-spawned populations are +2.4744/+7.4800 and +2.1123/+7.9613 seconds respectively. Mixed recorded parallelism limits 2/6, unknown cache/contention and host/order effects prevent #357-only or scheduling causal claims. Full populations and 612 shard environments are retained. |
| #212 comparison and legacy integrity | The 1,800-ID JS/TS set is registered in-sample/nonblind; Python has 4,271 unique repository/commit IDs. Legacy integrity remains UNKNOWN with zero confident legacy-integrity pairs. Agreement is not a semantic truth-label corpus or a held-out/general FP-rate estimate. |
| #366 / #367 / #364 | Deferred from this fixed release scope. No fresh model benchmark, corpus expansion or unrelated issue closure is inferred from these receipts. |
| T-528 A–D and historical materializer | Original held-out/custody work remains incomplete and T-528 remains CLAIMED. The protected historical materializer is unchanged. The narrower release preparation does not complete that work. |
| Release and Action identity | Historical candidate 0d6c5ec receipts retain actual pre-tag parity failures and two existing macOS performance skips. Later release verification must bind its own final commit/tree/artifacts. The recommended Action keeps published v0.6.0 under the one-release lag and lacks later CLI fixes; actual branch-protection activation is not proved by workflow inspection. |
| [#428](https://github.com/taipei49314/checkwash/issues/428) JS/TS tables | Reported on 2026-10-14, after this release, so the acceptance below does not cover it. JS/TS `test.each`, `it.each` and `test.for` are never scanned: a weakened or deleted assertion, an edited row or a deleted table passes with zero findings. Ruled, not implemented. v0.8.0 has the same gap. |

The maintainer accepted the six-clause preparation proposal without modification
on 2026-10-12 and subsequently authorized one v0.7.0 publication with “發佈”.
This acceptance retains the limits above; it supplies no new empirical result.

[Complete release evidence and populations](https://github.com/taipei49314/checkwash/blob/v0.7.0/docs/releases/v0.7.0-public-launch.md)
· [Catch boundary](https://github.com/taipei49314/checkwash/blob/v0.7.0/docs/js-catch-swallowing.md)
· [Git input qualification](https://github.com/taipei49314/checkwash/blob/v0.7.0/docs/git-input-failure-qualification.md)

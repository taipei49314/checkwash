# Ordinary self-dogfood: two issue266 findings remain blocking

Status: OBSERVED_BLOCK_EXIT1_PENDING_MAINTAINER_DISPOSITION. This memo reads
the retained actual run and Git diff only. It neither reruns the product nor
changes code, labels, exemptions or allowlists. It does not turn the run PASS.

The candidate at8a8941dc2d7c581715a0f6f196c00da6c55f084b checked
1ffe283d7d947fecc426dea99323b0a2620a9482..8a8941dc2d7c581715a0f6f196c00da6c55f084b
using the actual Taipei date2026-10-27. The capture is
final/candidate-selfdogfood-r1/, driven by current_date_selfdogfood.py.
It ended exit1/BLOCK, summary0critical/2high/8warn, config_errors[] and
skipped_files[]. Source and ending SHA are8a, with unchanged3084-member input
manifest3649879bd02d32a9e3d1f868790d7af33d86382300720b072bed0320ad14fe22.
Host LAPTOP-01AGNPJU / Python3.11.9,
HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL. This is ordinary PR self-dogfood,
not a formal release collector or published check run.

## Exact before/after test mapping

Only tests/test_issue266_survivor_conftest_chain.py is compared in this memo.
Its Git blobs are a771cb6eb39dffa543dc4b48ba5750881cba0eef at1ffe and
ab3a3b54f4256a315c3db1f06d8fbc963b3ef6b8 at8a.

| Old test | Current test | Actual contract change |
| --- | --- | --- |
| test_a_survivor_the_chain_does_not_skip_is_credited(head) | test_d179_survivor_requires_unchanged_context_besides_liveness(head, expected) | The old two-row parametrization expected CREDITED for both sibling_directory and compat_gate. The new two-row parametrization keeps sibling_directory CREDITED but requires UNCREDITED for compat_gate because the surviving copy adds a fixture/conditional execution context. The assertion changes from outcome(head)==CREDITED to outcome(head)==expected. |
| test_without_a_strict_snapshot_the_chain_is_unknown_and_reads_as_before() | test_d179_without_strict_snapshot_unknown_chain_grants_no_duplicate_proof() | The same explicit root=False input now expects UNCREDITED, replacing the old CREDITED expectation. Its new docstring states that absent strict context is unknown, not equality. |

A third existing-name test, test_a_conftest_the_diff_changes_is_read_on_its_head_side,
also changes its second-direction expectation from CREDITED to UNCREDITED;
its first blocking direction is retained. That function is not one of the two
reported high disappeared-name findings. Other existing liveness and unchanged-
context positive controls remain present.

This is the ordinary unit-consumer migration already described for D179,
not an edit to the eight immutable .gwcase expectations. The new tests exist
and explicitly test the changed contract, but that fact does not itself
authorize main-check relocation credit or a self-maintenance exemption.

## Exact actual high findings

Both findings have rule TEST_DISABLED, severity high, shape unit_removed,
after=null, allowlisted=false, escalators[PROD_CHANGE_NOT_EVIDENCE] and no
deescalators. Their actual keys are:

1. `TEST_DISABLED/tests/test_issue266_survivor_conftest_chain.py/test_a_survivor_the_chain_does_not_skip_is_credited/v2:9058d147d7f0e5dc141bce9e3e4e910fc31f38bcb48bc75e8691c62eec6b7ebb`
   Before evidence: `assert outcome(head) == CREDITED`, span4413..4512.
2. `TEST_DISABLED/tests/test_issue266_survivor_conftest_chain.py/test_without_a_strict_snapshot_the_chain_is_unknown_and_reads_as_before/v2:e132c2bebecb035512ebaa870b40474afd7f1f1707e137e7da08dba600a31941`
   Before evidence: `assert outcome(head, root=False) == CREDITED`, span5244..5655.

The old expectations and the new expected policy deliberately differ; a
rename or preserved mass is not evidence that they represent the same oracle
obligation. The observed high findings are consistent with the candidate's
no-unproved-context-credit behavior. That is an explanation of the observation,
not a maintainer ruling that the changes are acceptable or exempt.

The retained stderr is nonempty: it includes the actual-date command record
and ignored retired legacy-exemption diagnostics. Empty config_errors and
skipped_files do not mean stderr was empty or those old entries were accepted.
No ignored legacy key was reactivated and no new allowance was added here.

## Acceptance and handoff boundary

This self-dogfood BLOCK is a separate pending review item from #567's eight
unchanged golden failures. Acknowledging the D179 contract migration does not
silently accept either category. A subsequent remediation, explicit disposition
or BASE-reviewed exemption would require its own concrete authorization and
fresh evidence; none is performed or proposed as already approved here.

The public-v0.9.0 Action replay subsequently completed install/check/analysis
at exit0 on the same base/head range and fail-on-high threshold. That is the
old public Action's local comparator result, not this candidate's gate: the
new8a ordinary self-dogfood above remains two-high/BLOCK. It is not a GitHub
runner or formal published check run. Pyz process and wheel console smoke
also completed separately; neither clears this BLOCK or the eight golden
costs. The three full source/wheel/pyz qualifications were still pending in
checkpoint5cce6944; the full suite had not started there. Their terminal outcomes
must be read separately. Backup priority before the host transition is not
release urgency, and the version1.0 maintainer stop remains in force.

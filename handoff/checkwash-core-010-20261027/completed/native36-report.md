# Final sealed 36 synthetic CLI controls

Source: `8a8941dc2d7c581715a0f6f196c00da6c55f084b`; HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL; Windows Python 3.11.9.

The outer capture exited 0 and retained the same sealed HEAD and complete source file map. All 36 CLI streams were read back with exact hashes, findings2 and reported version0.10.0. The 18 before/after/TASK input groups are byte-identical to the original stage2 input JSON (`65193f40e2218db136dc2419053d2149192943390e0ba1826942aef9e23572fc`). A further 18 read-only Git show commands verified each actual committed BASE fixture; all actual after/TASK/production bytes also matched the old inputs. Their raw streams are preserved separately. Fixture programs were not executed.

There are 26 explicit expected outcome checks: frozen A/B/parameter-change high BLOCK, bad literal controls BLOCK, and pure rename/move/legitimate unroll PASS. All passed. Ten additional rows are fully recorded observations and baseline comparisons; exit0 does not silently turn those into extra preregistered outcome assertions.

| Case | Freeze | Entry | Exit | Verdict | Findings | Expected check |
|---|---|---|---:|---|---|---|
| A | False | worktree | 1 | block | TEST_DISABLED/high | observation only |
| A | False | range | 1 | block | TEST_DISABLED/high | observation only |
| A | True | worktree | 1 | block | TEST_DISABLED/high | yes |
| A | True | range | 1 | block | TEST_DISABLED/high | yes |
| B | False | worktree | 1 | block | TEST_DISABLED/high | observation only |
| B | False | range | 1 | block | TEST_DISABLED/high | observation only |
| B | True | worktree | 1 | block | TEST_DISABLED/high | yes |
| B | True | range | 1 | block | TEST_DISABLED/high | yes |
| B_from_A | False | worktree | 1 | block | TEST_DISABLED/high | observation only |
| B_from_A | False | range | 1 | block | TEST_DISABLED/high | observation only |
| B_from_A | True | worktree | 1 | block | TEST_DISABLED/high | observation only |
| B_from_A | True | range | 1 | block | TEST_DISABLED/high | observation only |
| N_unroll_changed | False | worktree | 1 | block | EXPECTED_VALUE_CHANGED/high, EXPECTED_VALUE_CHANGED/high, EXPECTED_VALUE_CHANGED/high | yes |
| N_unroll_changed | False | range | 1 | block | EXPECTED_VALUE_CHANGED/high, EXPECTED_VALUE_CHANGED/high, EXPECTED_VALUE_CHANGED/high | yes |
| N_unroll_changed | True | worktree | 1 | block | EXPECTED_VALUE_CHANGED/high, EXPECTED_VALUE_CHANGED/high, EXPECTED_VALUE_CHANGED/high | yes |
| N_unroll_changed | True | range | 1 | block | EXPECTED_VALUE_CHANGED/high, EXPECTED_VALUE_CHANGED/high, EXPECTED_VALUE_CHANGED/high | yes |
| control_rename_only | False | worktree | 0 | pass | none | yes |
| control_rename_only | False | range | 0 | pass | none | yes |
| control_rename_only | True | worktree | 0 | pass | none | yes |
| control_rename_only | True | range | 0 | pass | none | yes |
| control_unroll_preserved | False | worktree | 0 | pass | none | yes |
| control_unroll_preserved | False | range | 0 | pass | none | yes |
| control_unroll_preserved | True | worktree | 0 | pass | none | yes |
| control_unroll_preserved | True | range | 0 | pass | none | yes |
| control_same_name_changed | False | worktree | 1 | block | TEST_DISABLED/high | yes |
| control_same_name_changed | False | range | 1 | block | TEST_DISABLED/high | yes |
| control_same_name_changed | True | worktree | 1 | block | TEST_DISABLED/high | yes |
| control_same_name_changed | True | range | 1 | block | TEST_DISABLED/high | yes |
| control_cross_file_move | False | worktree | 0 | pass | none | yes |
| control_cross_file_move | False | range | 0 | pass | none | yes |
| control_cross_file_move | True | worktree | 0 | pass | none | yes |
| control_cross_file_move | True | range | 0 | pass | none | yes |
| cross_file_param_changed | False | worktree | 1 | block | TEST_DISABLED/high | observation only |
| cross_file_param_changed | False | range | 1 | block | EXPECTATION_DEFINITION_CHANGED/high | observation only |
| cross_file_param_changed | True | worktree | 1 | block | TEST_DISABLED/high | yes |
| cross_file_param_changed | True | range | 1 | block | EXPECTATION_DEFINITION_CHANGED/high | yes |

## Two preserved baseline comparisons

- v090: 36 paired observations, 14 differing pairs; fields={'exit': 10, 'verdict': 10, 'summary': 10, 'findings': 14}; verdict moves={'pass -> block': 10}.
- v091: 36 paired observations, 14 differing pairs; fields={'exit': 10, 'verdict': 10, 'summary': 10, 'findings': 14}; verdict moves={'pass -> block': 10}.

comparison.json retains complete candidate and baseline finding dictionaries, including fingerprints, escalators and deescalators, plus schema/exit/stderr deltas and stream references. Deltas are intentionally retained rather than forced to zero. Old producers, fixture definitions, raw evidence and labels were verified unchanged.

## Limits

- 36 synthetic CLI observations; 26 explicit expected outcome checks and 10 fully observed comparison rows.
- Deltas from the two preserved baselines are observations, not an automatic zero-delta acceptance gate.
- Eight existing D179 golden expectation costs remain unchanged and separately tracked by root; this native subset does not waive them.
- PJU Windows Python 3.11.9 only; no native file-symlink, Python 3.13, other OS, wheel/pyz or release-stage coverage is supplied by this run.

The unchanged eight golden expectation costs remain a separate acceptance issue; this bounded run does not claim a passing full suite or release qualification.

# fbc ordinary self-dogfood: three high findings remain BLOCK

Fixed comparison: `1ffe283d7d947fecc426dea99323b0a2620a9482` → `fbc9374dc3bcbfc47f403aec0c36e6b51dd7b86c`. Native source/version is
`checkwash 0.10.0`; actual date comes from the retained stderr command record.
Host LAPTOP-01AGNPJU; `HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL`.

The completed original JSON reports **BLOCK / exit 1**, critical 0, high 3,
warn 9, info 0; config_errors and skipped_files are empty. This is ordinary
PR self-dogfood, not release acceptance, a release bridge, or a published check.
`candidate-selfdogfood.raw.json` and `native-capture-receipt.json` are byte-for-byte
copies. Their hashes and complete finding objects are in `review.json`.

| Rule | Path / unit | Exact original fingerprint |
|---|---|---|
| `ASSERT_WEAKENED` | `tests/test_classic_raises_additions.py` / `test_added_literal_rows_retain_exception_removal_and_native_units` | `ASSERT_WEAKENED/tests/test_classic_raises_additions.py/test_added_literal_rows_retain_exception_removal_and_native_units/v2:d692f62b20ee000e8f0a3372f2d37e3f3225af7a8926db90ce06fe4e01468d87` |
| `TEST_DISABLED` | `tests/test_issue266_survivor_conftest_chain.py` / `test_a_survivor_the_chain_does_not_skip_is_credited` | `TEST_DISABLED/tests/test_issue266_survivor_conftest_chain.py/test_a_survivor_the_chain_does_not_skip_is_credited/v2:9058d147d7f0e5dc141bce9e3e4e910fc31f38bcb48bc75e8691c62eec6b7ebb` |
| `TEST_DISABLED` | `tests/test_issue266_survivor_conftest_chain.py` / `test_without_a_strict_snapshot_the_chain_is_unknown_and_reads_as_before` | `TEST_DISABLED/tests/test_issue266_survivor_conftest_chain.py/test_without_a_strict_snapshot_the_chain_is_unknown_and_reads_as_before/v2:e132c2bebecb035512ebaa870b40474afd7f1f1707e137e7da08dba600a31941` |

The new classic finding aligns the old `assert preserved.after == original.side`
with `assert len(native_fields) == 17`. Its native message is
`EXACT_VALUE(90) -> TYPE_SHAPE(50)`, drop 40, subject_changed=true, escalator
PROD_CHANGE_NOT_EVIDENCE. The actual fbc test also separately compares all 17
native fields exactly and checks IR3 context/map enrichment. That source
maintenance explains the review context; it does not erase the detector's
alignment, lower the finding or constitute a semantic exemption.

The two issue266 findings are the old disappeared unit names after the
reviewed D179 ordinary-contract migrations to unknown/changed-startup or
missing-strict-context expectations. This file's fbc bytes equal its prior8a
bytes. The native findings remain unallowlisted TEST_DISABLED/high; no
ASSERTION_MOVED/RESTRUCTURED waiver or new ledger entry is supplied here.

`raw/` contains exact 1ffe/fbc/prior8a test blobs and the two 1ffe→fbc diffs.
The long finding dictionaries, original before/after spans/text and strength
metadata are retained unchanged in JSON; this memo does not substitute a
guessed complete vector. No product/fixture/test was reexecuted, no source
or expected label was edited, and no exemption or judgment was changed.

This BLOCK stays NONPASS in follow-up backup metadata, regardless of later
distribution qualification results or whether evidence packaging completes.
Backup completion is not acceptance; version 1.0 still requires Nelson's
explicit decision.

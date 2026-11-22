# Known issues for the CheckWash 0.13.1 candidate

## Python function replacements

The new #635 check covers a modified Python test module with an existing, undecorated test that takes no arguments. The test contains a single direct equality assertion, uses the same assertion text on both sides, and compares its call against a literal. To identify the replaced function, CheckWash looks for one unchanged module at the repository root or under `src/` that directly declares it. This optional lookup considers at most 32 distinct eligible targets and modules up to 64 KiB. Where it cannot establish the replacement, the existing checks still apply. [Implementation](https://github.com/taipei49314/checkwash/blob/0477013159face076a2c6a887f9d5b235c76d5e5/src/checkwash/frontends/python/subject_replacements.py)

The fixture change applies within the existing numeric generator-to-parameterized-test comparison. Decorated replacement functions, classes, general fixture dispatch and cross-file helper or `conftest.py` analysis remain outside this patch's additional coverage. The broader experiment is recorded in [draft PR #638](https://github.com/taipei49314/checkwash/pull/638).

## Other open issues

The adjacent issues about switching imports and moving a test beside a different provider remain open. Skipping or marking a test as an expected failure through an imported helper is tracked for 0.14. The other fixes requested after 0.13.0 are separate work. [#634](https://github.com/taipei49314/checkwash/issues/634) · [#636](https://github.com/taipei49314/checkwash/issues/636) · [#622](https://github.com/taipei49314/checkwash/issues/622) · [Issues #624–#631 in the repair record](https://github.com/taipei49314/checkwash/blob/0477013159face076a2c6a887f9d5b235c76d5e5/STATE.md)

The dated 0.13.0 notes describe the remaining import and setup cases, including threat-model rows 189–191. The earlier release's coverage limits and historical measurements are preserved in its versioned notes. [After 0.13.0](KNOWN-ISSUES-next.md#after-0130--2026-11-19) · [Known issues for 0.13.0](KNOWN-ISSUES-v0.13.0.md)

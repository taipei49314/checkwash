"""Detector registry — explicit, no scanning, no dynamic loading (SPEC/security).

A detector is a pure function f(IR) -> list[Finding] emitting base severity
`warn`; gating.py applies the escalator table. New detectors must register
here AND ship pos/neg `.gwcase` fixtures in the same PR.
"""

from greenwash.detectors import (
    assert_removed,
    assert_weakened,
    expected_changed,
    expected_hardcoded,
    globals_rules,
    test_disabled,
    tolerance_loosened,
)

REGISTRY = {
    "ASSERT_REMOVED": assert_removed.detect,
    "ASSERT_WEAKENED": assert_weakened.detect,
    "TEST_DISABLED": test_disabled.detect,
    "TOLERANCE_LOOSENED": tolerance_loosened.detect,
    "EXPECTED_VALUE_HARDCODED": expected_hardcoded.detect,
    "EXPECTED_VALUE_CHANGED": expected_changed.detect,
    "SNAPSHOT_CODE_COCHANGE": globals_rules.detect_snapshot_cochange,
    "BROAD_EXCEPT_ADDED": globals_rules.detect_broad_except,
    "SUPPRESSION_ADDED": globals_rules.detect_suppression,
    "CI_WORKFLOW_TOUCHED": globals_rules.detect_ci_touched,
    "GUARDRAIL_TOUCHED": globals_rules.detect_guardrail,
    "CONFTEST_PATCHES_PROD": globals_rules.detect_conftest_prod_patch,
    "IMPORT_UNRESOLVED": globals_rules.detect_import_unresolved,
    "SCOPE_DRIFT": globals_rules.detect_scope_drift,
    "HIDDEN_UNICODE": globals_rules.detect_hidden_unicode,
    "TEST_FILE_UNPARSEABLE": globals_rules.detect_unparseable_test,
}

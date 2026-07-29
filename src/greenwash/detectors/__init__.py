"""Detector registry — explicit, no scanning, no dynamic loading (SPEC/security).

A detector is a pure function f(IR) -> list[Finding] emitting base severity
`warn`; gating.py applies the escalator table. New detectors must register
here AND ship pos/neg `.gwcase` fixtures in the same PR.
"""

from greenwash.detectors import assert_removed, assert_weakened, test_disabled

REGISTRY = {
    "ASSERT_REMOVED": assert_removed.detect,
    "ASSERT_WEAKENED": assert_weakened.detect,
    "TEST_DISABLED": test_disabled.detect,
}

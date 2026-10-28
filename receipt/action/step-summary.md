⚠ checkwash: 2 finding(s), none at or above high

EXPECTATION_DEFINITION_CHANGED   WARN   tests/test_doctor.py :: test_ref_diagnostics_name_actual_and_required_pins
  test_ref_diagnostics_name_actual_and_required_pins: the assertion is unchanged but its expectation is not — required is defined differently now, so the test compares against a different value than it did
  held at warn by: REPAIR_EVIDENCE
  before  assert reason in detail
  after   assert reason in detail

CI_WORKFLOW_TOUCHED   WARN   .github/workflows/checkwash.yml
  CI configuration changed

summary: critical=0 high=0 warn=2 info=0 verdict=pass allow_cap=180d

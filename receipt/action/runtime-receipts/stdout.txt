⚠ checkwash: 8 finding(s), none at or above high

EXPECTED_VALUE_CHANGED   WARN   tests/test_packaging.py :: test_readme_action_snippet_is_zizmor_blanket
  test_readme_action_snippet_is_zizmor_blanket: expected call rewritten to a different call ['advertised'] -> ['expected'] with no change in assertion strength
  held at warn by: PACKAGE_REPAIR
  before  assert pin == advertised["commit"], (
  after   assert pin == expected, (

EXPECTED_VALUE_CHANGED   WARN   tests/test_packaging.py :: test_readme_action_snippet_is_zizmor_blanket
  test_readme_action_snippet_is_zizmor_blanket: expected call rewritten to a different call ['advertised'] -> ['expected'] with no change in assertion strength
  held at warn by: PACKAGE_REPAIR
  before  assert pin == advertised["commit"], (
  after   assert pin == expected, (

EXPECTED_VALUE_CHANGED   WARN   tests/test_packaging.py :: test_readme_action_snippet_is_zizmor_blanket
  test_readme_action_snippet_is_zizmor_blanket: expected call rewritten to a different call ['advertised'] -> ['expected'] with no change in assertion strength
  held at warn by: PACKAGE_REPAIR
  before  assert pin == advertised["commit"], (
  after   assert pin == expected, (

EXPECTED_VALUE_CHANGED   WARN   tests/test_packaging.py :: test_readme_action_snippet_is_zizmor_blanket
  test_readme_action_snippet_is_zizmor_blanket: expected call rewritten to a different call ['advertised'] -> ['expected'] with no change in assertion strength
  held at warn by: PACKAGE_REPAIR
  before  assert pin == advertised["commit"], (
  after   assert pin == expected, (

EXPECTED_VALUE_CHANGED   WARN   tests/test_packaging.py :: test_readme_action_snippet_is_zizmor_blanket
  test_readme_action_snippet_is_zizmor_blanket: expected call rewritten to a different call ['advertised'] -> ['expected'] with no change in assertion strength
  held at warn by: PACKAGE_REPAIR
  before  assert pin == advertised["commit"], (
  after   assert pin == expected, (

EXPECTED_VALUE_CHANGED   WARN   tests/test_packaging.py :: test_readme_action_snippet_is_zizmor_blanket
  test_readme_action_snippet_is_zizmor_blanket: expected call rewritten to a different call ['advertised'] -> ['expected'] with no change in assertion strength
  held at warn by: PACKAGE_REPAIR
  before  assert pin == advertised["commit"], (
  after   assert pin == expected, (

EXPECTATION_DEFINITION_CHANGED   WARN   tests/test_packaging.py :: test_readme_action_snippet_is_zizmor_blanket
  test_readme_action_snippet_is_zizmor_blanket: the assertion is unchanged but its expectation is not — current_version is defined differently now, so the test compares against a different value than it did
  held at warn by: PACKAGE_REPAIR
  before  assert trusted_version <= current_version
  after   assert trusted_version <= current_version

IMPORT_UNRESOLVED   WARN   tests/test_doctor_own_action_pin.py
  new import 'test_doctor' resolves against neither the stdlib, the repo, nor declared dependencies (hallucination fingerprint)
  after   import test_doctor

summary: critical=0 high=0 warn=8 info=0 verdict=pass allow_cap=180d

⚠ checkwash: 6 finding(s), none at or above high

EXPECTED_VALUE_CHANGED   WARN   tests/test_raises_carrier_oracle_credit.py :: test_a_configured_k_filter_leaves_every_python_arrival_unproven
  test_a_configured_k_filter_leaves_every_python_arrival_unproven: expected value rewritten 'high' -> 'info' with no change in assertion strength
  held at warn by: PACKAGE_REPAIR
  before  assert disabled(findings)["test_large"][0] != "high"
  after   assert disabled(findings)["test_large"][0] != "info"

EXPECTED_VALUE_CHANGED   WARN   tests/test_raises_carrier_oracle_credit.py :: test_a_configured_k_filter_leaves_every_python_arrival_unproven
  test_a_configured_k_filter_leaves_every_python_arrival_unproven: expected value rewritten 'pass' -> 'block' with no change in assertion strength
  held at warn by: PACKAGE_REPAIR
  before  assert verdict == "pass"
  after   assert verdict == "block"

EXPECTED_VALUE_CHANGED   WARN   tests/test_raises_carrier_oracle_credit.py :: test_a_test_moved_where_pytest_never_collects_it_earns_nothing
  test_a_test_moved_where_pytest_never_collects_it_earns_nothing: expected value rewritten 'pass' -> 'block' with no change in assertion strength
  held at warn by: PACKAGE_REPAIR
  before  assert verdict == "pass"
  after   assert verdict == "block"

EXPECTED_VALUE_CHANGED   WARN   tests/test_raises_carrier_oracle_credit.py :: test_a_test_moved_where_pytest_never_collects_it_earns_nothing
  test_a_test_moved_where_pytest_never_collects_it_earns_nothing: expected value rewritten {'test_ok': ('info', ('ASSERTION_MOVED',))} -> {'test_ok': ('high', ())} with no change in assertion strength
  held at warn by: PACKAGE_REPAIR
  before  assert disabled(findings) == {"test_ok": ("info", ("ASSERTION_MOVED",))}
  after   assert disabled(findings) == {"test_ok": ("high", ())}

SUPPRESSION_ADDED   WARN   tests/test_arrival_collection.py
  lint/type suppression added (inventory = lambda: list(listed)  # noqa: E731)
  after   inventory = lambda: list(listed)  # noqa: E731

SUPPRESSION_ADDED   WARN   tests/test_arrival_collection.py
  lint/type suppression added (inventory = lambda: sorted(files)  # noqa: E731)
  after   inventory = lambda: sorted(files)  # noqa: E731

summary: critical=0 high=0 warn=6 info=0 verdict=pass allow_cap=180d

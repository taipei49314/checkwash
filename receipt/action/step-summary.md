⚠ checkwash: 11 finding(s), none at or above high

ASSERT_REMOVED   WARN   tests/test_issue415_oversized_sources.py :: test_a_range_beside_an_oversized_file_gives_a_verdict
  test_a_range_beside_an_oversized_file_gives_a_verdict: assertion removed (strength EXACT_VALUE)
  held at warn by: SAME_UNIT_REWRITE
  before  assert code == 0

ASSERT_REMOVED   WARN   tests/test_issue415_oversized_sources.py :: test_a_range_beside_an_oversized_file_gives_a_verdict
  test_a_range_beside_an_oversized_file_gives_a_verdict: assertion removed (strength EXACT_VALUE)
  held at warn by: SAME_UNIT_REWRITE
  before  assert finding["severity"] == "warn"

ASSERT_REMOVED   WARN   tests/test_issue415_oversized_sources.py :: test_a_range_beside_an_oversized_file_gives_a_verdict
  test_a_range_beside_an_oversized_file_gives_a_verdict: assertion removed (strength PATTERN)
  held at warn by: SAME_UNIT_REWRITE
  before  assert "REPAIR_EVIDENCE" in finding["deescalators"]

ASSERT_REMOVED   WARN   tests/test_issue415_oversized_sources.py :: test_an_unread_side_earns_no_repair_evidence
  test_an_unread_side_earns_no_repair_evidence: assertion removed (strength EXACT_VALUE)
  held at warn by: SAME_UNIT_REWRITE
  before  assert verdict == "pass"

ASSERT_REMOVED   WARN   tests/test_issue415_oversized_sources.py :: test_an_unread_side_earns_no_repair_evidence
  test_an_unread_side_earns_no_repair_evidence: assertion removed (strength PATTERN)
  held at warn by: SAME_UNIT_REWRITE
  before  assert "REPAIR_EVIDENCE" in findings[0].deescalators

ASSERT_WEAKENED   WARN   tests/test_issue415_oversized_sources.py :: test_an_unread_side_earns_no_repair_evidence
  test_an_unread_side_earns_no_repair_evidence: assertion strength EXACT_STRUCT(100) -> EXACT_VALUE(90)
  held at warn by: MILD_WEAKENING
  before  assert findings[0].escalators == ["NO_PROD_CHANGE_IN_DIFF"]
  after   assert findings[0].escalators == [label]

EXPECTED_VALUE_CHANGED   WARN   tests/test_issue419_narrow_broad_except.py :: test_other_former_refusal_rules_refuse_every_evidence
  test_other_former_refusal_rules_refuse_every_evidence: expected value rewritten 'pass' -> 'block' with no change in assertion strength
  held at warn by: PACKAGE_REPAIR
  before  assert verdict == "pass"
  after   assert verdict == "block"

EXPECTED_VALUE_CHANGED   WARN   tests/test_issue419_narrow_broad_except.py :: test_other_former_refusal_rules_refuse_every_evidence
  test_other_former_refusal_rules_refuse_every_evidence: expected value rewritten ('warn', [], ['REPAIR_EVIDENCE']) -> ('high', ['REPAIR_EVIDENCE_REFUSED'], []) with no change in assertion strength
  held at warn by: PACKAGE_REPAIR
  before  assert (hit.severity, hit.escalators, hit.deescalators) == (
  after   assert (hit.severity, hit.escalators, hit.deescalators) == (

EXPECTED_VALUE_CHANGED   WARN   tests/test_issue471_fixture_producers.py :: test_the_one_hop_callers_route_is_not_followed_from_a_producer
  test_the_one_hop_callers_route_is_not_followed_from_a_producer: expected value rewritten 'pass' -> 'block' with no change in assertion strength
  held at warn by: PACKAGE_REPAIR
  before  assert verdict == "pass"
  after   assert verdict == "block"

EXPECTED_VALUE_CHANGED   WARN   tests/test_issue471_fixture_producers.py :: test_the_one_hop_callers_route_is_not_followed_from_a_producer
  test_the_one_hop_callers_route_is_not_followed_from_a_producer: expected value rewritten [('ASSERT_WEAKENED', 'warn', ('REPAIR_EVIDENCE',), ())] -> [('ASSERT_WEAKENED', 'high', (), ('REPAIR_EVIDENCE_REFUSED',))] with no change in assertion strength
  held at warn by: PACKAGE_REPAIR
  before  assert inline == [("ASSERT_WEAKENED", "warn", ("REPAIR_EVIDENCE",), ())]
  after   assert inline == [("ASSERT_WEAKENED", "high", (), ("REPAIR_EVIDENCE_REFUSED",))]

EXPECTATION_DEFINITION_CHANGED   WARN   tests/test_issue419_narrow_broad_except.py :: test_missing_lookup_is_not_a_unitless_finding
  test_missing_lookup_is_not_a_unitless_finding: the assertion is unchanged but its expectation is not — expected is defined differently now, so the test compares against a different value than it did
  held at warn by: REPAIR_EVIDENCE
  before  assert (hit.severity, hit.escalators, hit.deescalators, verdict) == expected
  after   assert (hit.severity, hit.escalators, hit.deescalators, verdict) == expected

allowlisted findings: 28 (see .greenwash/allow.toml; expiry cap 180 days; takes effect after commit)
summary: critical=0 high=0 warn=11 info=0 verdict=pass allow_cap=180d

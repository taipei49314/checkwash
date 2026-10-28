⚠ checkwash: 12 finding(s), none at or above high

ASSERT_WEAKENED   WARN   tests/test_issue418_session_base.py :: test_an_exemption_committed_during_the_session_governs_only_the_next_one
  test_an_exemption_committed_during_the_session_governs_only_the_next_one: assertion polarity inverted (positive -> negative) — the test now proves the opposite
  held at warn by: REPAIR_EVIDENCE
  before  assert "checkwash allow" in second["reason"]
  after   assert "checkwash allow" not in second["reason"]

EXPECTED_VALUE_CHANGED   WARN   tests/e2e/test_cli.py :: test_hook_json_blocks_with_reason
  test_hook_json_blocks_with_reason: expected value rewritten 'checkwash allow' -> 'tell the user which finding blocks and why' with no change in assertion strength
  held at warn by: PACKAGE_REPAIR
  before  assert "checkwash allow" in payload["reason"]
  after   assert "tell the user which finding blocks and why" in payload["reason"]

EXPECTED_VALUE_CHANGED   WARN   tests/test_issue418_session_base.py :: test_an_exemption_committed_during_the_session_governs_only_the_next_one
  test_an_exemption_committed_during_the_session_governs_only_the_next_one: expected value rewritten 'An exemption, config change or hook upgrade committed during this session applies from the next session; /clear starts one.' -> 0 despite increased assertion strength
  held at warn by: REPAIR_EVIDENCE
  before  assert ("An exemption, config change or hook upgrade committed during this session applies "
  after   assert result.returncode == 0, result.stderr

EXPECTED_VALUE_CHANGED   WARN   tests/test_issue418_session_base.py :: test_an_uncommitted_blocked_edit_still_blocks_as_before
  test_an_uncommitted_blocked_edit_still_blocks_as_before: expected value rewritten 'checkwash allow "ASSERT_WEAKENED/' -> 'ASSERT_WEAKENED test_total.py :: test_total' with no change in assertion strength
  held at warn by: PACKAGE_REPAIR
  before  assert 'checkwash allow "ASSERT_WEAKENED/' in payload["reason"]
  after   assert "ASSERT_WEAKENED test_total.py :: test_total" in payload["reason"]

BROAD_EXCEPT_ADDED   WARN   src/checkwash/cli.py
  broad exception handler added (exceptExceptionasexc:#noqa:BLE001-notanalysed;thebasepolicysayswhatthatmeans)
  after   exceptExceptionasexc:#noqa:BLE001-notanalysed;thebasepolicysayswhatthatmeans

BROAD_EXCEPT_ADDED   WARN   src/checkwash/cli.py
  broad exception handler added (exceptException:#noqa:BLE001-asbelow)
  after   exceptException:#noqa:BLE001-asbelow

BROAD_EXCEPT_ADDED   WARN   src/checkwash/session.py
  broad exception handler added (exceptException:#noqa:BLE001-aStopmustneverfailonitsownrecord)
  after   exceptException:#noqa:BLE001-aStopmustneverfailonitsownrecord

BROAD_EXCEPT_ADDED   WARN   src/checkwash/session.py
  broad exception handler added (exceptException:#noqa:BLE001-asrecord_stop)
  after   exceptException:#noqa:BLE001-asrecord_stop

SUPPRESSION_ADDED   WARN   src/checkwash/cli.py
  lint/type suppression added (except Exception:  # noqa: BLE001 - as below)
  after   except Exception:  # noqa: BLE001 - as below

SUPPRESSION_ADDED   WARN   src/checkwash/cli.py
  lint/type suppression added (except Exception as exc:  # noqa: BLE001 - not analysed; the base policy says what that means)
  after   except Exception as exc:  # noqa: BLE001 - not analysed; the base policy says what that means

SUPPRESSION_ADDED   WARN   src/checkwash/session.py
  lint/type suppression added (except Exception:  # noqa: BLE001 - a Stop must never fail on its own record)
  after   except Exception:  # noqa: BLE001 - a Stop must never fail on its own record

SUPPRESSION_ADDED   WARN   src/checkwash/session.py
  lint/type suppression added (except Exception:  # noqa: BLE001 - as record_stop)
  after   except Exception:  # noqa: BLE001 - as record_stop

summary: critical=0 high=0 warn=12 info=0 verdict=pass allow_cap=180d

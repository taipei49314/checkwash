⚠ checkwash: 2 finding(s), none at or above high

EXPECTED_VALUE_CHANGED   WARN   tests/test_doctor.py :: test_install_local_then_doctor_accepts_bom_and_does_not_claim_gitignore
  test_install_local_then_doctor_accepts_bom_and_does_not_claim_gitignore: expected value rewritten '?? .claude/settings.local.json' -> 'A  README.md\n' despite increased assertion strength
  held at warn by: REPAIR_EVIDENCE
  before  assert "?? .claude/settings.local.json" in status
  after   assert status == "A  README.md\n"

EXPECTED_VALUE_CHANGED   WARN   tests/test_doctor.py :: test_install_local_then_doctor_accepts_bom_and_does_not_claim_gitignore
  test_install_local_then_doctor_accepts_bom_and_does_not_claim_gitignore: expected value rewritten 'does not configure Git ignore' -> "adds it to the repository's .git/info/exclude" with no change in assertion strength
  held at warn by: REPAIR_EVIDENCE
  before  assert "does not configure Git ignore" in " ".join(capsys.readouterr().out.split())
  after   assert "adds it to the repository's .git/info/exclude" in " ".join(capsys.readouterr().out.split())

summary: critical=0 high=0 warn=2 info=0 verdict=pass allow_cap=180d

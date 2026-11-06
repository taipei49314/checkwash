⚠ checkwash: 5 finding(s), none at or above high

CI_WORKFLOW_TOUCHED   WARN   .github/workflows/assertion-qualification.yml
  CI configuration changed

CI_WORKFLOW_TOUCHED   WARN   .github/workflows/ci.yml
  CI configuration changed

CI_WORKFLOW_TOUCHED   WARN   .github/workflows/verdict-gate.yml
  CI configuration changed

IMPORT_UNRESOLVED   WARN   tests/test_release_tag_at_action_commit.py
  new import 'own_action_pin_fixtures' resolves against neither the stdlib, the repo, nor declared dependencies (hallucination fingerprint)
  after   import own_action_pin_fixtures

IMPORT_UNRESOLVED   WARN   tests/test_release_tag_at_action_commit.py
  new import 'published_release_fixtures' resolves against neither the stdlib, the repo, nor declared dependencies (hallucination fingerprint)
  after   import published_release_fixtures

allowlisted findings: 1 (see .greenwash/allow.toml; expiry cap 180 days; takes effect after commit)
summary: critical=0 high=0 warn=5 info=0 verdict=pass allow_cap=180d

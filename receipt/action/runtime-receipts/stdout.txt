⚠ checkwash: 4 finding(s), none at or above high

CI_WORKFLOW_TOUCHED   WARN   .github/workflows/quality-candidate-intake.yml
  CI configuration changed

CI_WORKFLOW_TOUCHED   WARN   pyproject.toml
  CI configuration changed

BROAD_EXCEPT_ADDED   WARN   tools/pju_receipt_bridge.py
  broad exception handler added (exceptException:)
  after   exceptException:

IMPORT_UNRESOLVED   WARN   tools/replay_pju_action.py
  new import 'yaml' resolves against neither the stdlib, the repo, nor declared dependencies (hallucination fingerprint)
  after   import yaml

summary: critical=0 high=0 warn=4 info=0 verdict=pass allow_cap=180d

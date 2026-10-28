⚠ checkwash: 15 finding(s), none at or above high

ASSERT_WEAKENED   WARN   tests/test_root_oracles.py :: test_helper_only_assertion_removal_discovers_unchanged_importer
  test_helper_only_assertion_removal_discovers_unchanged_importer: assertion strength EXACT_STRUCT(100) -> EXACT_VALUE(90)
  held at warn by: REPAIR_EVIDENCE
  before  assert reads == ["tests/test_calc.py", "conftest.py", "tests/calc.py", "tests/test_helpers.py",
  after   assert reads == oracle_reads + startup_probes

EXPECTED_VALUE_CHANGED   WARN   tests/test_fingerprint_scope.py :: test_only_crlf_is_canonicalized_and_ir_contains_digests_not_new_source_copies
  test_only_crlf_is_canonicalized_and_ir_contains_digests_not_new_source_copies: expected value rewritten 2 -> 3 with no change in assertion strength
  held at warn by: REPAIR_EVIDENCE
  before  assert IR_VERSION == FINDINGS_VERSION == ir.version == 2
  after   assert IR_VERSION == ir.version == 3

EXPECTED_VALUE_CHANGED   WARN   tests/test_issue266_survivor_conftest_chain.py :: test_a_conftest_the_diff_changes_is_read_on_its_head_side
  test_a_conftest_the_diff_changes_is_read_on_its_head_side: expected call rewritten to a different call ['CREDITED'] -> ['UNCREDITED'] with no change in assertion strength
  held at warn by: REPAIR_EVIDENCE
  before  assert outcome({**head, "tests/conftest.py": plain}, {"tests/conftest.py": (SKIPPING, plain)}) == CREDITED
  after   assert outcome({**head, "tests/conftest.py": plain}, {"tests/conftest.py": (SKIPPING, plain)}) == UNCREDITED

EXPECTED_VALUE_CHANGED   WARN   tests/test_issue346_config_reads.py :: test_working_tree_batch_refusal_names_the_symlinked_path
  test_working_tree_batch_refusal_names_the_symlinked_path: expected value rewritten 'strict snapshot batch cannot inspect nonregular source requirements/pyproject.toml (a symlink)' -> "strict snapshot batch cannot inspect nonregular source 'requirements/pyproject.toml' (a symlink); side='worktree', entry='worktree/read_many'. Use a repository-owned regular source at this path; a committed range reads committed bytes only." with no change in assertion strength
  held at warn by: REPAIR_EVIDENCE
  before  assert str(caught.value) == (
  after   assert str(caught.value) == (

EXPECTED_VALUE_CHANGED   WARN   tests/test_issue346_config_reads.py :: test_working_tree_refusal_names_a_directory
  test_working_tree_refusal_names_a_directory: expected value rewritten 'strict snapshot cannot inspect nonregular source configs/pytest.ini (a directory)' -> "strict snapshot cannot inspect nonregular source 'configs/pytest.ini' (a directory); side='worktree', entry='worktree/read'. Use a repository-owned regular source at this path; a committed range reads committed bytes only." with no change in assertion strength
  held at warn by: REPAIR_EVIDENCE
  before  assert str(caught.value) == (
  after   assert str(caught.value) == (

EXPECTATION_DEFINITION_CHANGED   WARN   tests/test_js_liveness.py :: test_a_unit_moved_into_a_skipped_block_earns_no_move_credit
  test_a_unit_moved_into_a_skipped_block_earns_no_move_credit: the assertion is unchanged but its expectation is not — outcome is defined differently now, so the test compares against a different value than it did
  held at warn by: REPAIR_EVIDENCE
  before  assert (verdict, [(f.rule, f.severity) for f in findings]) == (
  after   assert (verdict, [(f.rule, f.severity) for f in findings]) == (

CI_WORKFLOW_TOUCHED   WARN   pyproject.toml
  CI configuration changed

BROAD_EXCEPT_ADDED   WARN   src/checkwash/oracle_describe_credit.py
  broad exception handler added (exceptException:)
  after   exceptException:

BROAD_EXCEPT_ADDED   WARN   src/checkwash/oracle_fixture_credit.py
  broad exception handler added (exceptExceptionasexc:)
  after   exceptExceptionasexc:

BROAD_EXCEPT_ADDED   WARN   src/checkwash/oracle_fixture_credit.py
  broad exception handler added (exceptExceptionasexc:)
  after   exceptExceptionasexc:

BROAD_EXCEPT_ADDED   WARN   src/checkwash/oracle_fixture_credit.py
  broad exception handler added (exceptExceptionasexc:)
  after   exceptExceptionasexc:

BROAD_EXCEPT_ADDED   WARN   src/checkwash/sweep.py
  broad exception handler added (exceptExceptionasexc:#noqa:BLE001-asweepmustsurviveonebadcommit)
  after   exceptExceptionasexc:#noqa:BLE001-asweepmustsurviveonebadcommit

SUPPRESSION_ADDED   WARN   src/checkwash/sweep.py
  lint/type suppression added (except Exception as exc:  # noqa: BLE001 - a sweep must survive one bad commit)
  after   except Exception as exc:  # noqa: BLE001 - a sweep must survive one bad commit

SUPPRESSION_ADDED   WARN   tools/emit_corpus.py
  lint/type suppression added (from checkwash.cases import case_policy_base, case_snapshot, case_to_changes, parse_case  # noqa: E402)
  after   from checkwash.cases import case_policy_base, case_snapshot, case_to_changes, parse_case  # noqa: E402

IMPORT_UNRESOLVED   WARN   tests/test_receipt_execution_routes.py
  new import 'test_pju_receipt_bridge' resolves against neither the stdlib, the repo, nor declared dependencies (hallucination fingerprint)
  after   import test_pju_receipt_bridge

allowlisted findings: 4 (see .greenwash/allow.toml; expiry cap 180 days; takes effect after commit)
summary: critical=0 high=0 warn=15 info=0 verdict=pass allow_cap=180d

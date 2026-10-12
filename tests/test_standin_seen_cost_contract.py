"""Owned metadata/receipt controls; never execute a corpus or import an engine."""
import copy
import hashlib
from pathlib import Path
import shutil
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import r1_cost_capture as cap
import standin_seen_cost_aggregate as aggregate
import standin_seen_cost_contract as c
import standin_seen_cost_worker as worker


def test_original_full_cohort_is_verified_before_exact_subset_projection():
    original, old_shards, old_groups = c.full_cohort()
    members, shards, groups = c.cohort()
    assert len(original) == 4271 and len(old_shards) == 432 and len(old_groups) == 48
    wanted = [row for row in original if {"standard", "d088"}.intersection(row["phases"])]
    assert members == wanted and len(members) == 3018
    assert sum("standard" in row["phases"] for row in members) == 1800
    assert sum("d088" in row["phases"] for row in members) == 1263
    assert sum({"standard", "d088"}.issubset(row["phases"]) for row in members) == 45
    assert sum("targeted" in row["phases"] for row in members) == 119
    assert len(shards) == 382 and len(groups) == 43
    assert all(row["repository"].lower() != "aio-libs/aiohttp" for row in members)


def test_five_excluded_groups_and_original_noncontiguous_ordinals_are_preserved():
    _original, old_shards, old_groups = c.full_cohort()
    members, shards, groups = c.cohort()
    ordinals = {row["ordinal"] for row in members}
    assert ordinals != set(range(3018))
    assert sorted(n for group in groups for n in group["member_ordinals"]) == sorted(ordinals)
    assert sorted(n for shard in shards for n in shard["member_ordinals"]) == sorted(ordinals)
    excluded = [row for row in old_groups if not ordinals.intersection(row["member_ordinals"])]
    assert len(excluded) == 5
    for row in groups:
        old = next(item for item in old_groups if item["name"] == row["name"])
        assert row["repository"] == old["repository"]
        assert row["member_ordinals"] == [n for n in old["member_ordinals"] if n in ordinals]
        assert row["shards"] == [s["name"] for s in shards if s["name"] in old["shards"]]
    for row in shards:
        old = next(item for item in old_shards if item["name"] == row["name"])
        assert row == dict(old, member_ordinals=[n for n in old["member_ordinals"] if n in ordinals])


def test_group_lookup_uses_original_ordinal_not_compact_index():
    members = [dict(ordinal=17, commit="first"), dict(ordinal=41, commit="second")]
    assert c.members_for_group(members, dict(member_ordinals=[41, 17])) == [members[1], members[0]]
    with pytest.raises(KeyError):
        c.members_for_group(members, dict(member_ordinals=[0]))
    with pytest.raises(ValueError, match="duplicate"):
        c.members_for_group([members[0], members[0]], dict(member_ordinals=[17]))


def test_all_selected_arms_start_not_attempted_with_overlap_counted_once():
    members, shards, groups = c.cohort()
    rows = c.expected_rows(members, shards, groups)
    assert len(rows) == len({(row["member"]["ordinal"], row["arm"]) for row in rows}) == 6036
    assert all(row["outcome"] == "NOT_ATTEMPTED" and row["observation"] is None for row in rows)
    assert sum({"standard", "d088"}.issubset(row["member"]["phases"]) for row in rows) == 90


@pytest.mark.parametrize("fault", ["missing_archive", "changed_archive", "changed_partition"])
def test_original_metadata_missing_or_changed_is_not_an_empty_subset(tmp_path, monkeypatch, fault):
    for name in ("python-pairs.json.gz", "python-partitions.json"):
        shutil.copyfile(c.FULL_DATA / name, tmp_path / name)
    if fault == "missing_archive":
        (tmp_path / "python-pairs.json.gz").unlink()
    else:
        name = "python-pairs.json.gz" if fault == "changed_archive" else "python-partitions.json"
        (tmp_path / name).write_bytes(b"{}")
    monkeypatch.setattr(c, "FULL_DATA", tmp_path)
    with pytest.raises((ValueError, FileNotFoundError)):
        c.cohort()


@pytest.fixture
def own_data(tmp_path, monkeypatch):
    for name in ("contract.json", "selection-ordinals.json"):
        shutil.copyfile(c.DATA / name, tmp_path / name)
    monkeypatch.setattr(c, "DATA", tmp_path)
    return tmp_path


@pytest.mark.parametrize("fault", ["missing", "changed_bytes", "reordered", "replacement_member"])
def test_selection_bytes_and_mathematical_membership_are_both_required(own_data, monkeypatch, fault):
    path = own_data / "selection-ordinals.json"
    if fault == "missing":
        path.unlink()
    elif fault == "changed_bytes":
        path.write_bytes(path.read_bytes() + b" ")
    else:
        values = c.read(path)
        if fault == "reordered":
            values.reverse()
        else:
            outside = next(n for n in range(4271) if n not in set(values))
            values[0] = outside
            values.sort()
        c.write(path, values)
        # Rehash to exercise exact subset validation, beyond envelope tampering.
        new_hash = cap.digest(path)
        monkeypatch.setattr(c, "SELECTION_HASH", new_hash)
        contract = c.read(own_data / "contract.json")
        contract["selection_ordinals_sha256"] = new_hash
        c.write(own_data / "contract.json", contract)
    with pytest.raises((ValueError, FileNotFoundError)):
        c.cohort()


@pytest.mark.parametrize("field,value", [("purpose", "R1_SEEN_FIXED_COHORT_COST"),
    ("expected_pairs", 4271), ("today", "2099-01-01"), ("candidate_sha", "b" * 40),
    ("candidate_resolution", "ANY_BRANCH"), ("phases", {"targeted": 1372}),
    ("limits", {"invocation_seconds": 999})])
def test_contract_cannot_silently_change_experiment(own_data, field, value):
    contract = c.read(own_data / "contract.json")
    contract[field] = value
    c.write(own_data / "contract.json", contract)
    with pytest.raises(ValueError, match="contract differs"):
        c.cohort()


@pytest.fixture
def event(own_data):
    contract = c.read(own_data / "contract.json")
    contract["baseline_sha"] = "a" * 40
    c.write(own_data / "contract.json", contract)
    return dict(GITHUB_EVENT_NAME="pull_request", GITHUB_RUN_ATTEMPT="1", GITHUB_RUN_ID="1234",
                GITHUB_SHA="b" * 40, PR_HEAD_SHA="c" * 40, PR_BASE_SHA="a" * 40)


@pytest.mark.parametrize("key,value", [("GITHUB_EVENT_NAME", "workflow_dispatch"),
    ("GITHUB_RUN_ATTEMPT", "2"), ("PR_BASE_SHA", "d" * 40), ("GITHUB_SHA", ""),
    ("PR_HEAD_SHA", "main"), ("GITHUB_RUN_ID", "unknown")])
def test_event_mismatch_never_authorizes_capture(event, key, value):
    event[key] = value
    with pytest.raises(ValueError):
        c.event_identity(event)


@pytest.mark.parametrize("baseline", [None, "FUTURE_BASE", ""])
def test_unfixed_source_baseline_prevents_any_launch(own_data, baseline):
    contract = c.read(own_data / "contract.json")
    contract["baseline_sha"] = baseline
    c.write(own_data / "contract.json", contract)
    env = dict(GITHUB_EVENT_NAME="pull_request", GITHUB_RUN_ATTEMPT="1", GITHUB_RUN_ID="1",
               GITHUB_SHA="b" * 40, PR_HEAD_SHA="c" * 40, PR_BASE_SHA="a" * 40)
    with pytest.raises(ValueError, match="not fixed"):
        c.event_identity(env)


def test_valid_event_resolves_candidate_without_self_referential_source_sha(event):
    assert c.fixed_contract()["candidate_sha"] is None
    assert c.event_identity(event) == dict(run_id="1234", attempt="1", event="pull_request",
                                         candidate="b" * 40, pr_head="c" * 40, baseline="a" * 40)


@pytest.fixture
def plan(monkeypatch):
    members, shards, groups = c.cohort()
    identity = dict(run_id="1234", attempt="1", event="pull_request", baseline="a" * 40,
                    candidate="b" * 40, pr_head="c" * 40)
    monkeypatch.setattr(c, "event_identity", lambda: copy.deepcopy(identity))
    hashes = c.tool_hashes()
    engines = {}
    for arm in c.ARMS:
        source = dict(commit=identity["baseline" if arm == "base" else "candidate"],
                      tree="d" * 40, package_tree="e" * 40)
        engines[arm] = dict(source=source, artifact_path=f"arms/{arm}/artifacts/checkwash.pyz",
                            artifact_sha256="f" * 64, artifact_bytes=10, version="0.7.0", findings_version=2,
                            input_trust="UNMODIFIED_EXACT_SOURCE_NO_READER_SUBSTITUTION")
    return dict(schema_version=1, purpose=c.PURPOSE, classification="ALREADY_SEEN_NONBLIND",
                cost_qualification="NOT_ADJUDICATED", identity=copy.deepcopy(identity), harness_hashes=hashes,
                members_sha256=c.MEMBERS_HASH, partitions_sha256=c.PARTITIONS_HASH,
                selection_ordinals_sha256=c.SELECTION_HASH, cohort_accounting=copy.deepcopy(c.COHORT_ACCOUNTING),
                phases=copy.deepcopy(c.PHASE_VIEWS), expected_pairs=len(members), expected_arm_rows=6036,
                today=c.DATE, primary_distribution="pyz", limits=copy.deepcopy(c.LIMITS),
                arm_order="alternate_by_original_ordinal", groups=groups, shards=shards,
                build_complete=True, engines=engines, harness_source=copy.deepcopy(engines["candidate"]["source"]),
                pr_head_tree="d" * 40)


def test_plan_accepts_only_complete_event_bound_selected_inventory(plan):
    members, shards, groups = c.validate_plan(plan)
    assert len(members) == 3018 and len(shards) == 382 and len(groups) == 43


@pytest.mark.parametrize("fault", ["old_purpose", "old_rows", "old_phases", "selection", "missing_harness",
    "missing_field", "base", "candidate", "rerun", "group", "shard", "reader", "not_built", "head_tree"])
def test_plan_identity_or_manifest_misbinding_is_rejected(plan, fault):
    if fault == "old_purpose": plan["purpose"] = "R1_SEEN_FIXED_COHORT_COST"
    elif fault == "old_rows": plan["expected_arm_rows"] = 8542
    elif fault == "old_phases": plan["phases"] = dict(standard=1800, d088=1263, targeted=1372)
    elif fault == "selection": plan["selection_ordinals_sha256"] = "a" * 64
    elif fault == "missing_harness": plan["harness_hashes"].pop("tools/r1_cost_capture.py")
    elif fault == "missing_field": del plan["cohort_accounting"]
    elif fault == "base": plan["engines"]["base"]["source"]["commit"] = "f" * 40
    elif fault == "candidate": plan["identity"]["candidate"] = None
    elif fault == "rerun": plan["identity"]["attempt"] = "2"
    elif fault == "group": plan["groups"].pop()
    elif fault == "shard": plan["shards"][0]["member_ordinals"].append(99999)
    elif fault == "reader": plan["engines"]["base"]["input_trust"] = "NEW_READER"
    elif fault == "not_built": plan["build_complete"] = False
    else: plan["pr_head_tree"] = "f" * 40
    with pytest.raises((ValueError, KeyError, TypeError)):
        c.validate_plan(plan)


@pytest.mark.parametrize("fault", ["missing", "truncated", "old_inventory"])
def test_delivered_row_inventory_is_required_before_artifacts(tmp_path, fault):
    rows = c.expected_rows(*c.cohort())
    if fault != "missing":
        c.write(tmp_path / "expected-rows.json", rows[:-1] if fault == "truncated" else [])
    with pytest.raises((ValueError, FileNotFoundError)):
        worker.verify_artifacts(tmp_path, dict(engines={}))


def test_missing_prepare_keeps_every_selected_arm_in_accounting(tmp_path, monkeypatch):
    monkeypatch.setenv("STANDIN_SEEN_MANIFEST_SHA256", "absent")
    output = tmp_path / "output"
    output.mkdir()
    assert aggregate.aggregate(output, tmp_path / "absent") == 3
    summary = c.read(output / "summary.json")
    assert summary["expected_arm_rows"] == summary["accounted_arm_rows"] == 6036
    assert summary["counts"] == {arm: {"MISSING_WORKER": 3018} for arm in c.ARMS}
    assert summary["attempts"] == summary["complete_captures"] == 0
    assert summary["execution_complete"] is False and summary["cost_qualification"] == "NOT_ADJUDICATED"
    assert summary["phase_denominators"] == dict(standard=1800, d088=1263, targeted_cotag_only=119)
    assert summary["cohort_accounting"]["aiohttp142"] == "UNKNOWN_NOT_REPLACED"


@pytest.mark.parametrize("fault", [None, "missing", "duplicate", "run", "attempt", "source", "manifest", "group"])
def test_worker_receipts_are_unique_and_bound_to_this_experiment(fault):
    group = dict(name="r03-g00")
    identity = dict(run_id="1", attempt="1", candidate="a" * 40)
    rows = [dict(member=dict(ordinal=n), arm=arm) for n in (17, 41) for arm in c.ARMS]
    wanted = {(row["member"]["ordinal"], row["arm"]): row for row in rows}
    ledger = dict(identity=dict(identity), group=dict(group), manifest_sha256="d" * 64, records=copy.deepcopy(rows))
    if fault == "missing": ledger["records"].pop()
    elif fault == "duplicate": ledger["records"].append(copy.deepcopy(rows[0]))
    elif fault in ("run", "attempt", "source"):
        ledger["identity"][{"run": "run_id", "attempt": "attempt", "source": "candidate"}[fault]] = "wrong"
    elif fault == "manifest": ledger["manifest_sha256"] = "e" * 64
    elif fault == "group": ledger["group"]["name"] = "r00-g00"
    if fault is None:
        assert aggregate.worker_rows(ledger, group, wanted, identity, "d" * 64) == rows
    else:
        with pytest.raises(ValueError):
            aggregate.worker_rows(ledger, group, wanted, identity, "d" * 64)


def observed(outcome, raw, code, payload=None):
    return dict(outcome=outcome, stdout_sha256=raw, stderr_sha256="stderr", raw_prefix=raw,
                observation=dict(exit_code=code), payload=payload)


def test_same_engine_error_with_changed_original_reason_remains_a_difference():
    row = aggregate.difference({}, observed("PRODUCT_ERROR_EXIT", "old", 2), observed("PRODUCT_ERROR_EXIT", "new", 2))
    assert row["stdout_changed"] and row["before_exit"] == row["after_exit"] == 2
    assert row["disposition"] == "PENDING_SOURCE_ADJUDICATION"


def test_reported_block_pass_with_config_diagnostics_is_not_hidden():
    before = observed("CONFIG_DIAGNOSTICS_BLOCK", "a", 1, dict(verdict="block", findings=[], config_errors=["old"]))
    after = observed("CONFIG_DIAGNOSTICS_PASS", "b", 0, dict(verdict="pass", findings=[], config_errors=["new"]))
    row = aggregate.difference({}, before, after)
    assert (row["before_verdict"], row["after_verdict"]) == ("block", "pass")
    assert row["diagnostics_changed"] and row["findings"] == dict(added=[], removed=[])


def test_new_error_is_kept_with_exit_and_raw_links():
    row = aggregate.difference({}, observed("ANALYZED_BLOCK", "a", 1, dict(verdict="block", findings=[])),
                               observed("PRODUCT_ERROR_EXIT", "b", 2))
    assert row["before_verdict"] == "block" and row["after_verdict"] is None
    assert row["after_exit"] == 2 and row["after_raw"] == "b"


def test_raw_message_only_finding_change_still_requires_disposition():
    before = observed("ANALYZED_BLOCK", "a", 1, dict(findings=[dict(rule="X", message="old")]))
    after = observed("ANALYZED_BLOCK", "b", 1, dict(findings=[dict(rule="X", message="new")]))
    row = aggregate.difference({}, before, after)
    assert row["stdout_changed"] and row["findings"] == dict(added=[], removed=[])
    assert row["disposition"] == "PENDING_SOURCE_ADJUDICATION"


def test_shared_capture_identity_and_namespace_are_in_dependency_inventory():
    hashes = c.tool_hashes()
    assert hashes["tools/r1_cost_capture.py"] == c.CAPTURE_HASH
    assert hashes["tools/standin_seen_cost_data/selection-ordinals.json"] == c.SELECTION_HASH
    assert {"tools/qualify_assertions.py", "tools/release_inventory.py",
            "tools/standin_seen_cost_data/contract.json", ".github/workflows/standin-seen-cost.yml"} <= hashes.keys()
    assert not any(name.startswith("tools/standin_cost_") for name in hashes)


def test_synthetic_complete_exit_two_is_collected_as_error_not_pass():
    stream = dict(path="empty", sha256=hashlib.sha256(b"").hexdigest(), bytes=0,
                  retained_bytes=0, observed_bytes=0)
    observation = dict(spawned=True, capture_complete=True, cleanup_complete=True, output_limit_observed=False,
                       status="EXITED", first_stop_reason=None, exit_code=2, capture_errors=[],
                       elapsed_seconds=1.0, output_limit_bytes=100,
                       streams={"stdout": dict(stream), "stderr": dict(stream)})
    cap.validate_capture(observation)
    assert cap.classify(observation, None, {}, {}) == "PRODUCT_ERROR_EXIT"
    assert cap.classify(observation, {"verdict": "pass"}, {}, {}) == "PRODUCT_ERROR_WITH_VERDICT"


def test_checked_in_contract_is_unlaunchable_until_a_qualified_base_is_fixed():
    # This planning marker is not a resolved launch identity. The named null-base
    # negative controls above still apply after a reviewed baseline is fixed.
    value = c.fixed_contract()
    assert value["baseline_sha"] is None or c.SHA.fullmatch(value["baseline_sha"])
    assert value["candidate_sha"] is None
    assert value["candidate_resolution"] == "VALIDATED_EVENT_MERGE_AFTER_BASELINE_FIXED"
    assert hashlib.sha256((c.DATA / "selection-ordinals.json").read_bytes()).hexdigest() == c.SELECTION_HASH

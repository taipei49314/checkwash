"""Synthetic R1 harness controls only; no Checkwash/corpus import or execution.

Executed explicitly in the ordinary Ubuntu workflow before the historical route.
These are not new product fixture expectations and do not run a seen/held-out repo.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import r1_cost_capture as cap
import r1_cost_contract as c
import r1_cost_aggregate as aggregate
import r1_cost_worker as worker


def test_exact_seen_members_and_original_shards_have_no_gaps_or_duplicates():
    members, shards, groups = c.cohort()
    assert len(members) == 4271 and len(shards) == 432 and len(groups) == 48
    assert sorted(n for group in groups for n in group["member_ordinals"]) == list(range(4271))
    rows = c.expected_rows(members, shards, groups)
    assert len({(r["member"]["repository"], r["member"]["commit"], r["arm"]) for r in rows}) == 8542
    assert all(r["outcome"] == "NOT_ATTEMPTED" and r["observation"] is None for r in rows)
    assert sum("standard" in r["phases"] for r in members) == 1800
    assert sum("d088" in r["phases"] for r in members) == 1263
    assert sum("targeted" in r["phases"] for r in members) == 1372


@pytest.mark.parametrize("raw", [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}'])
def test_raw_json_cannot_silently_rewrite_duplicate_or_nonfinite_values(raw):
    with pytest.raises(ValueError):
        cap.decode(raw)


@pytest.fixture
def event(tmp_path, monkeypatch):
    c.write(tmp_path / "contract.json", dict(baseline_sha="a" * 40))
    monkeypatch.setattr(c, "DATA", tmp_path)
    return dict(GITHUB_EVENT_NAME="pull_request", GITHUB_RUN_ATTEMPT="1", GITHUB_RUN_ID="1234",
                GITHUB_SHA="b" * 40, PR_HEAD_SHA="c" * 40, PR_BASE_SHA="a" * 40)


@pytest.mark.parametrize("key,value", [("GITHUB_EVENT_NAME", "workflow_dispatch"), ("GITHUB_RUN_ATTEMPT", "2"),
                                     ("PR_BASE_SHA", "d" * 40), ("GITHUB_SHA", "main"), ("GITHUB_RUN_ID", "unknown")])
def test_event_or_baseline_mismatch_never_authorizes_capture(event, key, value):
    event[key] = value
    with pytest.raises(ValueError):
        c.event_identity(event)


def test_placeholder_cannot_start_historical_work(event):
    c.write(c.DATA / "contract.json", dict(baseline_sha="REQUIRES_FINAL_QUALITY_MAIN_SHA"))
    with pytest.raises(ValueError, match="not fixed"):
        c.event_identity(event)


def test_valid_event_binds_original_base_merge_and_head_separately(event):
    result = c.event_identity(event)
    assert result["baseline"] == "a" * 40
    assert result["candidate"] == "b" * 40 and result["pr_head"] == "c" * 40


@pytest.mark.parametrize("dirty,head", [(b" M src/checkwash/cli.py\n", "a" * 40), (b"", "b" * 40)])
def test_source_dirty_or_wrong_head_never_gets_an_arm_identity(dirty, head):
    class SourceMetadata:
        def git(self, root, *args):
            if args == ("rev-parse", "HEAD"):
                return head.encode()
            if args == ("status", "--porcelain"):
                return dirty
            raise AssertionError("must stop before issuing later identity requests")
    with pytest.raises(ValueError):
        c.source(SourceMetadata(), Path("/owned/source"), "a" * 40)


def observe(tmp_path, code, *, limit=65536, timeout=5):
    prefix = tmp_path / "observation"
    observation = cap.capture([sys.executable, "-I", "-c", code], tmp_path, dict(os.environ), prefix, timeout, limit)
    return prefix, observation


def test_native_exit_two_and_both_raw_streams_survive_complete_capture(tmp_path):
    prefix, value = observe(tmp_path, "import sys; print('original error'); sys.stderr.write('why\\n'); raise SystemExit(2)")
    cap.validate_capture(value)
    assert value["capture_complete"] and value["exit_code"] == 2
    assert prefix.with_suffix(".stdout").read_bytes() == b"original error\n"
    assert prefix.with_suffix(".stderr").read_bytes() == b"why\n"
    assert cap.classify(value, None, {}, {}) == "PRODUCT_ERROR_EXIT"


def test_timeout_retains_partial_stdout_and_never_becomes_pass(tmp_path):
    prefix, value = observe(tmp_path, "import sys,time; sys.stdout.write('x'*65536); sys.stdout.flush(); time.sleep(10)", timeout=2)
    cap.validate_capture(value)
    assert value["status"] == "TIMEOUT" and not value["capture_complete"]
    assert prefix.with_suffix(".stdout").read_bytes() == b"x" * 65536
    assert value["cleanup_complete"]


def test_output_limit_retains_bounded_prefix_and_original_stop(tmp_path):
    prefix, value = observe(tmp_path, "import sys,time; sys.stdout.write('x'*131072); sys.stdout.flush(); time.sleep(10)", limit=1024)
    cap.validate_capture(value)
    assert value["status"] == "OUTPUT_LIMIT" and value["output_limit_observed"]
    assert prefix.with_suffix(".stdout").read_bytes() == b"x" * 1024
    assert not value["capture_complete"]


def test_spawn_failure_is_not_exit_zero(tmp_path):
    value = cap.capture([str(tmp_path / "absent-python")], tmp_path, dict(os.environ), tmp_path / "missing", 2, 1024)
    cap.validate_capture(value)
    assert value["status"] == "SPAWN_FAILED" and not value["spawned"] and value["exit_code"] is None


def test_tool_failure_keeps_original_command_exit_and_raw_bytes(tmp_path):
    commands = c.Commands(tmp_path / "raw", tmp_path, dict(os.environ))
    with pytest.raises(ValueError, match="tool failed"):
        commands.run([sys.executable, "-I", "-c", "import sys; print('install failed'); raise SystemExit(7)"])
    rows = c.read(tmp_path / "raw/commands.json")
    assert rows[0]["observation"]["exit_code"] == 7
    assert (tmp_path / "raw/command-0000.stdout").read_bytes() == b"install failed\n"
    aggregate.validate_commands(tmp_path / "raw", rows)
    (tmp_path / "raw/command-0000.stderr").unlink()
    with pytest.raises(FileNotFoundError):
        aggregate.validate_commands(tmp_path / "raw", rows)


def test_capture_launch_preserves_private_venv_interpreter_path(tmp_path):
    # The build route uses private venv Python symlinks. Resolving argv[0]
    # before Popen would silently run the base environment instead.
    runtime = tmp_path / "private-runtime"
    commands = c.Commands(tmp_path / "commands", tmp_path, dict(os.environ))
    commands.run([sys.executable, "-I", "-m", "venv", "--without-pip", str(runtime)])
    python = runtime / "bin/python"
    raw = commands.run([str(python), "-I", "-c", "import sys; print(sys.prefix)"])
    assert raw.decode().strip() == str(runtime)
    observation = commands.rows[1]["observation"]
    assert observation["argv"][0] == str(python)
    assert observation["executable"] == str(python.resolve())
    intent = c.read(tmp_path / "commands/command-0001.intent.json")
    assert intent["launch_executable"] == str(python)


@pytest.mark.parametrize("field,value", [("capture_complete", True), ("spawned", False), ("exit_code", 0),
                                        ("cleanup_complete", True), ("first_stop_reason", None)])
def test_incomplete_capture_cannot_be_falsely_qualified(tmp_path, field, value):
    original = cap.capture([str(tmp_path / "absent")], tmp_path, dict(os.environ), tmp_path / "missing", 1, 1024)
    broken = copy.deepcopy(original)
    if broken[field] == value:
        broken[field] = not value if type(value) is bool else "EXITED"
    else:
        broken[field] = value
    with pytest.raises(ValueError):
        cap.validate_capture(broken)


def qualified_artifact_fixture(root):
    """Synthetic archive/proof bytes; no package import, build or qualification."""
    identity = dict(candidate="b" * 40, run_id="1234", attempt="1")
    source = dict(commit="a" * 40, tree="c" * 40)
    artifact = root / "arms/base/artifacts/checkwash.pyz"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"source A")
    wheel = artifact.with_name("checkwash.whl")
    sdist = artifact.with_name("checkwash.tar.gz")
    wheel.write_bytes(b"owned wheel placeholder")
    sdist.write_bytes(b"owned sdist placeholder")
    proofs = {}
    for kind, files in (("source", []), ("wheel", [wheel, sdist]), ("pyz", [artifact])):
        qpath = root / (kind + "-q.json")
        ipath = root / (kind + "-i.json")
        q = dict(status="passed", distribution=kind, source_commit=source["commit"],
                 suite_sha256="d" * 64, source_package_sha256="e" * 64,
                 source_package_dirty=False, errors=[], artifact_sha256=cap.digest(files[0]) if files else None)
        c.write(qpath, q)
        inventory = dict(status="passed", distribution=kind, source_commit=source["commit"],
                         source_tree=source["tree"], builder_source_commit=identity["candidate"],
                         run_id=identity["run_id"], attempt=identity["attempt"], errors=[],
                         qualification=dict(path=qpath.name, sha256=cap.digest(qpath)),
                         artifacts=[dict(name=path.name, sha256=cap.digest(path), bytes=path.stat().st_size) for path in files])
        c.write(ipath, inventory)
        proofs[kind] = dict(qualification=qpath.name, qualification_sha256=cap.digest(qpath),
                            inventory=ipath.name, inventory_sha256=cap.digest(ipath),
                            suite_sha256=q["suite_sha256"], package_sha256=q["source_package_sha256"])
    engine = dict(source=source, artifact_path="arms/base/artifacts/checkwash.pyz",
                  artifact_sha256=cap.digest(artifact), artifact_bytes=8, proofs=proofs)
    return dict(identity=identity, engines={"base": engine})


def test_swapped_or_modified_primary_artifact_is_rejected(tmp_path):
    plan = qualified_artifact_fixture(tmp_path)
    worker.verify_artifacts(tmp_path, plan)
    (tmp_path / "arms/base/artifacts/checkwash.pyz").write_bytes(b"source B")
    with pytest.raises(ValueError, match="artifact differs"):
        worker.verify_artifacts(tmp_path, plan)


@pytest.mark.parametrize("fault", ["missing-proof", "wrong-source", "wrong-builder", "wrong-run", "wrong-attempt",
                                   "wrong-tree", "wrong-qualified-hash", "missing-archive", "changed-wheel", "dirty-source"])
def test_artifact_receipt_controls_reject_semantic_misbinding(tmp_path, fault):
    plan = qualified_artifact_fixture(tmp_path)
    engine = plan["engines"]["base"]
    proof = engine["proofs"]["pyz"]
    qpath, ipath = tmp_path / proof["qualification"], tmp_path / proof["inventory"]
    q, inventory = c.read(qpath), c.read(ipath)
    if fault == "missing-proof":
        del engine["proofs"]["source"]
    elif fault == "missing-archive":
        (tmp_path / "arms/base/artifacts/checkwash.whl").unlink()
    elif fault == "changed-wheel":
        (tmp_path / "arms/base/artifacts/checkwash.whl").write_bytes(b"different")
    elif fault == "wrong-qualified-hash":
        q["artifact_sha256"] = "f" * 64
    elif fault == "dirty-source":
        q["source_package_dirty"] = True
    else:
        key = {"wrong-source": "source_commit", "wrong-builder": "builder_source_commit", "wrong-run": "run_id",
               "wrong-attempt": "attempt", "wrong-tree": "source_tree"}[fault]
        inventory[key] = "wrong"
    # Refresh the outer hashes: this tests binding, not only byte corruption.
    c.write(qpath, q)
    proof["qualification_sha256"] = cap.digest(qpath)
    inventory["qualification"]["sha256"] = cap.digest(qpath)
    c.write(ipath, inventory)
    proof["inventory_sha256"] = cap.digest(ipath)
    with pytest.raises((ValueError, FileNotFoundError)):
        worker.verify_artifacts(tmp_path, plan)


def synthetic_capture(root, prefix, argv, stdout, *, exit_code=0, resolved=None):
    """Owned receipt fixture, deliberately not presented as real process output."""
    path = root / prefix
    path.parent.mkdir(parents=True, exist_ok=True)
    stream_rows = {}
    for name, raw in (("stdout", stdout), ("stderr", b"")):
        file = path.with_suffix("." + name)
        file.write_bytes(raw)
        stream_rows[name] = dict(path=file.name, sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw),
                                 observed_bytes=len(raw), retained_bytes=len(raw))
    observation = dict(argv=argv, executable=resolved or argv[0], spawned=True, exit_code=exit_code,
                       output_limit_bytes=c.STREAM_LIMIT, elapsed_seconds=.1, first_stop_reason=None,
                       output_limit_observed=False, cleanup_complete=True, status="EXITED",
                       capture_complete=True, capture_errors=[], streams=stream_rows)
    c.write(path.with_suffix(".intent.json"), dict(argv=argv, executable=observation["executable"],
             launch_executable=argv[0], state="LAUNCHED", streams={k: v["path"] for k, v in stream_rows.items()}))
    c.write(path.with_suffix(".observation.json"), observation)
    return observation


def observed_row_fixture(root):
    member = dict(ordinal=0, repository="owned/example", commit="a" * 40, parent="b" * 40,
                  parents=["b" * 40], phases=["standard"])
    expected = dict(member=member, arm="base", shard="r00-000", group="r00-g00")
    ledger = dict(repository_path="/owned/work/corpus.git", prepared_root="/owned/prepared",
                  interpreter="/owned/python", git_executable="/owned/git", resolved_git="/resolved/git",
                  facts=dict(resolved_interpreter="/resolved/python"), labels={})
    engine = dict(version="0.7.0", findings_version=2, artifact_path="arms/base/artifacts/checkwash.pyz",
                  artifact_sha256="d" * 64, artifact_bytes=100, source=dict(commit="c" * 40))
    commands, proofs = [], {}
    def git(suffix, raw):
        argv = [ledger["git_executable"], "-c", "core.hooksPath=/dev/null", "-c", "core.autocrlf=false",
                "-C", ledger["repository_path"], *suffix]
        prefix = f"command-{len(commands):04d}"
        observation = synthetic_capture(root / "setup", prefix, argv, raw, resolved=ledger["resolved_git"])
        commands.append(dict(argv=argv, cwd="/owned/work", raw_prefix=prefix, observation=observation))
        return len(commands) - 1
    for side, full in (("base", member["parent"]), ("head", member["commit"])):
        short = full[:7]
        proofs[side] = dict(full=full, short=short,
                           object_command=git(["rev-parse", "--verify", full + "^{commit}"], (full + "\n").encode()),
                           short_command=git(["rev-parse", "--short", full], (short + "\n").encode()),
                           resolve_command=git(["rev-parse", "--verify", short + "^{commit}"], (full + "\n").encode()))
    proofs["parent_command"] = git(["cat-file", "commit", member["commit"]], ("tree " + "e" * 40 + "\nparent " + member["parent"] + "\n\nowned\n").encode())
    ledger["labels"][member["commit"]] = proofs
    payload = dict(checkwash_findings_version=2, run=dict(base=member["parent"][:7], head=member["commit"][:7], checkwash_version="0.7.0"),
                   verdict="pass", findings=[], summary=dict(critical=0, high=0, warn=0, info=0), config_errors=[], skipped_files=[])
    argv = [ledger["interpreter"], "-I", "/owned/prepared/" + engine["artifact_path"], "check",
            member["parent"] + ".." + member["commit"], "--repo", ledger["repository_path"], "--format", "json"]
    observation = synthetic_capture(root, "raw/pair-0000-base", argv, c.encoded(payload).encode(), resolved="/resolved/python")
    row = dict(expected, engine=engine, argv=argv, cwd="/owned/work", raw_prefix="raw/pair-0000-base", order_index=0,
               artifact_read=dict(sha256=engine["artifact_sha256"], bytes=100), observation=observation,
               reported_labels=dict(base=member["parent"][:7], head=member["commit"][:7]),
               payload={key: value for key, value in payload.items() if key != "findings"}, finding_count=0,
               outcome="ANALYZED_PASS", stage="OBSERVED")
    return ledger, row, copy.deepcopy(expected), dict(engines={"base": copy.deepcopy(engine)}), commands


def test_owned_complete_row_has_bound_cli_full_refs_and_raw_git_proofs(tmp_path):
    args = observed_row_fixture(tmp_path)
    result = aggregate.validate_row(tmp_path, *args)
    assert result["outcome"] == "ANALYZED_PASS" and result["observation"]["capture_complete"]
    assert result["payload"]["run"]["head"] == "a" * 7


@pytest.mark.parametrize("field,value,outcome", [("config_errors", ["owned config error"], "CONFIG_DIAGNOSTICS_PASS"),
                                                ("skipped_files", ["owned skipped path"], "ANALYZED_WITH_SKIPS_PASS"),
                                                ("verdict", "block", "EXIT_VERDICT_MISMATCH"),
                                                ("findings", [None], "INVALID_FINDING_ENVELOPE")])
def test_classifier_retains_diagnostics_skips_and_exit_contradictions(tmp_path, field, value, outcome):
    ledger, row, expected, plan, commands = observed_row_fixture(tmp_path)
    payload = c.read(tmp_path / "raw/pair-0000-base.stdout")
    payload[field] = value
    assert cap.classify(row["observation"], payload, row["member"], row["engine"], row["reported_labels"]) == outcome


@pytest.mark.parametrize("fault", ["member", "arm", "engine", "argv", "artifact", "order", "label",
                                   "git-parent", "git-resolved", "missing-raw", "changed-raw", "false-outcome"])
def test_owned_row_misbinding_or_missing_evidence_is_rejected(tmp_path, fault):
    ledger, row, expected, plan, commands = observed_row_fixture(tmp_path)
    if fault == "member":
        row["member"]["parent"] = "f" * 40
    elif fault == "arm":
        row["arm"] = "candidate"
    elif fault == "engine":
        row["engine"]["source"]["commit"] = "f" * 40
    elif fault == "argv":
        row["argv"][4] = "HEAD~1..HEAD"
    elif fault == "artifact":
        row["artifact_read"]["sha256"] = "e" * 64
    elif fault == "order":
        row["order_index"] = 1
    elif fault == "label":
        row["reported_labels"]["head"] = "c" * 7
    elif fault == "git-parent":
        # Rehash a wrong parent proof so the substantive exact-parent check fires.
        command = commands[-1]
        command["observation"] = synthetic_capture(tmp_path / "setup", command["raw_prefix"], command["argv"],
                                                    ("parent " + "f" * 40 + "\n\nowned\n").encode(), resolved=ledger["resolved_git"])
    elif fault == "git-resolved":
        ledger["resolved_git"] = "/wrong/git"
    elif fault == "missing-raw":
        (tmp_path / "raw/pair-0000-base.stderr").unlink()
    elif fault == "changed-raw":
        (tmp_path / "raw/pair-0000-base.stdout").write_bytes(b"{}")
    else:
        row["outcome"] = "ANALYZED_BLOCK"
    with pytest.raises((ValueError, FileNotFoundError)):
        aggregate.validate_row(tmp_path, ledger, row, expected, plan, commands)


@pytest.mark.parametrize("fault", [None, "missing", "duplicate", "unexpected", "run", "attempt", "source", "manifest", "group"])
def test_worker_identity_and_complete_unique_row_set(tmp_path, fault):
    member = dict(ordinal=0)
    rows = [dict(member=member, arm=arm) for arm in c.ARMS]
    wanted = {(0, arm): row for arm, row in zip(c.ARMS, rows)}
    identity = dict(run_id="1234", attempt="1", candidate="a" * 40)
    group = dict(name="r00-g00")
    ledger = dict(identity=copy.deepcopy(identity), group=dict(group), manifest_sha256="d" * 64,
                  records=copy.deepcopy(rows))
    if fault == "missing":
        ledger["records"].pop()
    elif fault == "duplicate":
        ledger["records"].append(copy.deepcopy(rows[0]))
    elif fault == "unexpected":
        ledger["records"][1]["arm"] = "third"
    elif fault in ("run", "attempt", "source"):
        ledger["identity"][{"run": "run_id", "attempt": "attempt", "source": "candidate"}[fault]] = "wrong"
    elif fault == "manifest":
        ledger["manifest_sha256"] = "e" * 64
    elif fault == "group":
        ledger["group"]["name"] = "r01-g00"
    if fault is None:
        assert aggregate.worker_rows(ledger, group, wanted, identity, "d" * 64) == rows
    else:
        with pytest.raises(ValueError):
            aggregate.worker_rows(ledger, group, wanted, identity, "d" * 64)


def sample_result(outcome="PRODUCT_ERROR_EXIT", raw="a", exit_code=2, payload=None):
    return dict(outcome=outcome, stdout_sha256=raw, stderr_sha256="e", raw_prefix=raw,
                observation=dict(exit_code=exit_code), payload=payload)


def test_same_error_outcome_with_new_raw_reason_is_preserved():
    row = aggregate.difference({"commit": "known"}, sample_result(raw="first"), sample_result(raw="second"))
    assert row["before_outcome"] == row["after_outcome"] == "PRODUCT_ERROR_EXIT"
    assert row["stdout_changed"] and row["disposition"] == "PENDING_SOURCE_ADJUDICATION"


def test_diagnostic_only_change_and_reported_block_pass_are_not_hidden():
    a = sample_result("CONFIG_DIAGNOSTICS_BLOCK", "a", 1, dict(verdict="block", findings=[], config_errors=["old"], skipped_files=[]))
    b = sample_result("CONFIG_DIAGNOSTICS_PASS", "b", 0, dict(verdict="pass", findings=[], config_errors=["new"], skipped_files=[]))
    row = aggregate.difference({}, a, b)
    assert row["before_verdict"] == "block" and row["after_verdict"] == "pass" and row["diagnostics_changed"]


def test_invalid_finding_payload_is_raw_evidence_not_aggregate_crash():
    a = sample_result("INVALID_FINDING_ENVELOPE", "a", 0, dict(findings=[None]))
    b = sample_result("INVALID_FINDING_ENVELOPE", "b", 0, dict(findings=[42]))
    assert aggregate.difference({}, a, b)["findings"] is None


def test_semantic_multiset_retains_absence_null_and_duplicates():
    left = [{"rule": "X"}, {"rule": "X"}]
    right = [{"rule": "X", "unit": None}]
    delta = aggregate.finding_delta(left, right)
    assert len(delta["removed"]) == 2 and len(delta["added"]) == 1
    assert delta["removed"][0]["unit"]["present"] is False
    assert delta["added"][0]["unit"] == dict(present=True, value=None)


def test_missing_prepare_or_workers_retains_full_denominator_and_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("R1_MANIFEST_SHA256", "not-present")
    output = tmp_path / "output"
    output.mkdir()
    assert aggregate.aggregate(output, tmp_path / "absent-inputs") == 3
    summary = c.read(output / "summary.json")
    assert summary["expected_arm_rows"] == summary["accounted_arm_rows"] == 8542
    assert summary["attempts"] == summary["complete_captures"] == 0
    assert summary["execution_complete"] is False and summary["cost_qualification"] == "NOT_ADJUDICATED"
    assert summary["counts"] == {arm: {"MISSING_WORKER": 4271} for arm in c.ARMS}
    assert len((output / "records.jsonl").read_text().splitlines()) == 8542


@pytest.mark.parametrize("spelling", ["../outside", "/etc/passwd", "C:\\outside", "x\\y"])
def test_receipt_path_escape_is_rejected(tmp_path, spelling):
    with pytest.raises(ValueError):
        cap.relative(tmp_path, spelling)

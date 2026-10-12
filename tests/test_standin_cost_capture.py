"""Owned collector contracts; no engine, corpus checkout or subprocess run."""
import json
from pathlib import Path
import sys

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
import standin_cost_capture as collector
import standin_cost_cases as cases


@pytest.mark.parametrize("name", cases.NAMES)
def test_owned_source_identity_preserves_last_oracle_and_actual_statement_body(name):
    before, after = cases.pair(name)
    assert (before, after) == cases.pair(name)
    assert before.endswith(cases.BEFORE) and after.endswith(cases.AFTER)
    assert b"billing.total = lambda: 3" not in before
    assert b"billing.total = lambda: 3" in after
    assert before != after
    if name != cases.SIBLING:
        assert len(before) == len(after) == 1_000_000
        assert max(len(line) for line in after.splitlines() if line.startswith(b"#")) < 110
    if name == cases.ORDINARY:
        assert after.count(b" = 12345678901234567890\n") > 20_000
    elif name == cases.SIBLING:
        assert after.count(b" + ") == 127
    else:
        assert after.count(b" + ") > 9_000


def valid_payload():
    return dict(verdict="pass", findings=[], run=dict(base="1234567", head="2345678", checkwash_version="0.7.0"),
                checkwash_findings_version=1, summary=dict(info=0, warn=0, high=0, critical=0), skipped_files=[], config_errors=[])


@pytest.mark.parametrize("exit_code", [2, -9, None])
def test_error_or_signal_with_pass_shaped_stdout_is_never_a_verdict(exit_code):
    assert collector.envelope(json.dumps(valid_payload()).encode(), exit_code) is None


@pytest.mark.parametrize("raw", [b"", b"[]", b"null", b'{"verdict":"pass"}',
                                  b'{"verdict":"block","verdict":"pass"}', b'{"number":NaN}'])
def test_missing_or_invalid_envelope_is_not_promoted_to_pass(raw):
    assert collector.envelope(raw, 0) is None


def test_native_exit_must_match_valid_envelope():
    payload = valid_payload()
    assert collector.envelope(json.dumps(payload).encode(), 1) is None
    payload["verdict"] = "block"
    assert collector.envelope(json.dumps(payload).encode(), 0) is None
    assert collector.envelope(json.dumps(payload).encode(), 1)["verdict"] == "block"


def row():
    return dict(kind="native", state="ERROR_OR_NO_VERDICT", verdict=None,
                observation=dict(capture_complete=True, cleanup_complete=True, exit_code=2), git_trace_observed=True,
                usage=dict(state="RECORDED", reported_exit=2))


@pytest.mark.parametrize("missing", ["usage", "observation"])
def test_exit_receipt_alone_does_not_prove_complete_cost_capture(missing):
    value = row()
    value.pop(missing)
    assert not collector.complete(value)


def test_recording_an_engine_error_is_complete_evidence_but_has_no_pass_verdict():
    value = row()
    assert collector.complete(value)
    assert value["state"] == "ERROR_OR_NO_VERDICT" and value["verdict"] is None
    value["kind"] = "diagnostic"
    assert not collector.complete(value)


def test_diagnostic_file_limit_is_incomplete_even_with_an_apparent_pass():
    value = row()
    value.update(kind="diagnostic", diagnostic=dict(complete=True, recorder_errors=[],
                 sources=[dict(state="PARSED"), dict(state="PARSED")]))
    assert collector.complete(value)
    value.update(state="CAPTURE_LIMIT", capture_limit="TRACE_SIZE_OR_SIGXFSZ")
    assert not collector.complete(value)


def test_partial_or_recorder_failed_diagnostic_is_not_capture_complete():
    value = row()
    value.update(kind="diagnostic", diagnostic=dict(complete=True, recorder_errors=[],
                 sources=[dict(state="PARSED"), dict(state="PARSED")]))
    assert collector.complete(value)
    value["diagnostic"]["recorder_errors"] = ["disk write failed"]
    assert not collector.complete(value)


def test_not_attempted_denominator_has_all_three_samples_and_both_arms():
    names = [*cases.NAMES, *("aiohttp_" + str(n) for n in range(5))]
    rows = collector.skeleton(names)
    assert len(rows) == 64
    assert sum(r["kind"] == "native" for r in rows) == 48
    assert len({(r["case"], r["arm"], r["kind"], r["sample"]) for r in rows}) == 64
    assert all(r["state"] == "NOT_ATTEMPTED" and r["verdict"] is None for r in rows)


def test_unknown_memory_is_not_zero_and_non_git_json_is_not_a_git_trace(tmp_path):
    assert collector.parse_usage(tmp_path / "missing")["state"] == "UNKNOWN"
    assert not collector.has_git_trace(b'{"verdict":"pass"}\n')
    assert not collector.has_git_trace(b'{"event":"start","argv":["git","diff"]}\n')


@pytest.mark.parametrize("key", ["candidate", "run_id", "attempt"])
def test_wrong_run_attempt_or_source_rejected_before_evidence_can_be_accepted(tmp_path, monkeypatch, key):
    identity = dict(candidate="a" * 40, run_id="1234", attempt="1")
    for field, env in (("candidate", "GITHUB_SHA"), ("run_id", "GITHUB_RUN_ID"), ("attempt", "GITHUB_RUN_ATTEMPT")):
        monkeypatch.setenv(env, identity[field])
    identity[key] = "wrong"
    (tmp_path / "report.json").write_text(json.dumps(dict(identity=identity)))
    with pytest.raises(ValueError, match="mismatch"):
        collector.validate(tmp_path)


def test_changed_qualified_artifact_rejected_before_any_child_can_launch(tmp_path):
    artifact = tmp_path / "checkwash.pyz"
    artifact.write_bytes(b"changed artifact")
    value = dict(case="owned", kind="native", sample=0, arm="candidate")
    with pytest.raises(ValueError, match="artifact changed before launch"):
        collector.sample(value, {}, dict(artifact=str(artifact), artifact_sha256="0" * 64),
                         tmp_path, {}, None, {}, {}, lambda: None)


@pytest.mark.parametrize("value", [False, None, "true"])
def test_sample_flushes_unproved_cleanup_and_aborts_before_postprocessing(tmp_path, monkeypatch, value):
    observed = dict(status="CAPTURE_FAILED", capture_complete=False, cleanup_complete=value)
    monkeypatch.setattr(collector.cap, "digest", lambda path: "c" * 64)
    calls = []
    def captured(*args):
        calls.append(args)
        return observed
    monkeypatch.setattr(collector.cap, "capture", captured)
    snapshots, item = [], dict(case="owned", arm="candidate", kind="native", sample=0)
    case = dict(base="a" * 40, head="b" * 40, repo=str(tmp_path / "target"))
    arm = dict(artifact=str(tmp_path / "candidate.pyz"), artifact_sha256="c" * 64,
               source=dict(commit="d" * 40))
    with pytest.raises(ValueError, match="stop the entire capture"):
        collector.sample(item, case, arm, tmp_path, {}, None,
            dict(per_child_seconds=240, stream_bytes=64_000_000), dict(run_id="123", attempt="1"),
            lambda: snapshots.append(json.loads(json.dumps(item))),
            {collector.TIME_BINARY: dict(sha256="c" * 64)})
    assert len(calls) == 1 and snapshots[-1]["observation"] == observed
    assert snapshots[-1]["reason"] == "PROCESS_ISOLATION_UNPROVED_ABORT_ALL"
    assert not (tmp_path / (item["raw_prefix"] + ".stdout")).exists()
    with pytest.raises(ValueError, match="stop the entire capture"):
        collector.require_isolated({})


def test_a_fully_cleaned_timeout_can_continue_but_cannot_be_complete_cost():
    value = row()
    value["observation"].update(status="TIMEOUT", capture_complete=False, cleanup_complete=True)
    collector.require_isolated(value["observation"])
    assert not collector.complete(value)


def trace_events(sid="git-A"):
    return [dict(event="version", sid=sid),
            dict(event="start", sid=sid, argv=["git", "diff"]),
            dict(event="exit", sid=sid, code=0, t_abs=.1),
            dict(event="atexit", sid=sid, code=0, t_abs=.11)]


def trace_bytes(events):
    return ("\n".join(json.dumps(event) for event in events) + "\n").encode()


@pytest.mark.parametrize("fault", ["only-start", "no-atexit", "partial-line", "duplicate-start",
                                  "duplicate-exit", "duplicate-atexit", "orphan-exit", "signal", "wrong-exit-code"])
def test_missing_truncated_duplicate_or_signalled_git_sessions_are_incomplete(fault):
    events = trace_events()
    if fault == "only-start":
        events = events[:2]
    elif fault == "no-atexit":
        events = events[:3]  # Fully terminated JSON line is still truncated shutdown.
    elif fault.startswith("duplicate-"):
        index = {"duplicate-start": 1, "duplicate-exit": 2, "duplicate-atexit": 3}[fault]
        events.insert(index, dict(events[index]))
    elif fault == "orphan-exit":
        events.append(dict(event="exit", sid="other-process", code=0, t_abs=.2))
    elif fault == "signal":
        events.insert(2, dict(event="signal", sid="git-A", signo=9))
    elif fault == "wrong-exit-code":
        events[-1]["code"] = 2
    raw = trace_bytes(events)
    if fault == "partial-line":
        raw = raw[:-2]
    assert not collector.has_git_trace(raw)


def test_interleaved_complete_git_sessions_remain_separate_process_counts():
    a, b = trace_events("parent"), trace_events("parent/child")
    facts = collector.trace_facts(trace_bytes([*a[:2], *b, *a[2:]]))
    assert facts["complete"] and facts["start_events"] == facts["session_count"] == 2
    assert facts["incomplete_sids"] == []
    assert facts["git_phase_time"].startswith("UNKNOWN")


def measurement_files(tmp_path, kind):
    value = dict(case="owned", arm="candidate", kind=kind, sample=0)
    case = dict(base="a" * 40, head="b" * 40, repo=str(tmp_path / "owned-repo"), path="tests/test_owned_cost.py")
    arm = dict(artifact=str(tmp_path / "candidate" / "checkwash.pyz"), artifact_sha256="c" * 64,
               source=dict(commit="d" * 40))
    identity, env = dict(run_id="123", attempt="1"), dict(PATH="/usr/bin", LANG="C.UTF-8")
    config, python = dict(per_child_seconds=240), "/fixed/python"
    prefix, argv, additions = collector.expected_command(value, case, arm, tmp_path, identity, python)
    value["raw_prefix"] = prefix.name
    value["observation"] = dict(argv=argv, cleanup_complete=True, exit_code=0, elapsed_seconds=.2)
    collector.cap.write(prefix.with_suffix(".measurement-intent.json"),
                        dict(argv=argv, cwd=str(tmp_path), environment=dict(env, **additions)))
    collector.cap.write(prefix.with_suffix(".observation.json"), value["observation"])
    collector.cap.write(prefix.with_suffix(".intent.json"), dict(argv=argv, state="LAUNCHED", timeout_seconds=240,
        streams={name: prefix.with_suffix("." + name).name for name in ("stdout", "stderr")}))
    prefix.with_suffix(".time.txt").write_text("100\t0.10\t0.01\t0\n", encoding="utf-8")
    value["usage"] = collector.parse_usage(prefix.with_suffix(".time.txt"))
    return value, case, arm, identity, env, config, python, prefix


@pytest.mark.parametrize("kind", ["native", "diagnostic"])
def test_exact_measurement_command_and_raw_receipts_agree(tmp_path, kind):
    value, case, arm, identity, env, config, python, prefix = measurement_files(tmp_path, kind)
    assert collector.validate_measurement(value, case, arm, tmp_path, identity, python, env, config) == prefix
    command = value["observation"]["argv"]
    assert (collector.PRLIMIT_BINARY in command) is (kind == "diagnostic")
    recorded_env = collector.read(prefix.with_suffix(".measurement-intent.json"))["environment"]
    assert ("GIT_TRACE2_EVENT" in recorded_env) is (kind == "diagnostic")
    if kind == "native":
        assert command[-9:] == [arm["artifact"], "check", case["base"] + ".." + case["head"],
                               "--repo", case["repo"], "--fail-on", "high", "--format", "json"]
    else:
        assert recorded_env["GIT_TRACE2_EVENT"] == str(prefix.with_suffix(".git-trace2.jsonl"))


@pytest.mark.parametrize("fault", ["wrong-arm", "wrong-refs", "changed-observation", "changed-usage", "trace-env"])
def test_misbound_measurement_or_tampered_raw_summary_is_rejected(tmp_path, fault):
    value, case, arm, identity, env, config, python, prefix = measurement_files(tmp_path, "native")
    if fault in ("wrong-arm", "wrong-refs"):
        observed = value["observation"]
        original = arm["artifact"] if fault == "wrong-arm" else case["base"] + ".." + case["head"]
        observed["argv"] = ["/other/checkwash.pyz" if token == original else token for token in observed["argv"]]
        collector.cap.write(prefix.with_suffix(".observation.json"), observed)
    elif fault == "changed-observation":
        value["observation"]["elapsed_seconds"] = 0
    elif fault == "changed-usage":
        value["usage"]["peak_rss_kib"] = 0
    else:
        intent = collector.read(prefix.with_suffix(".measurement-intent.json"))
        intent["environment"]["GIT_TRACE2_EVENT"] = "/other/invocation.jsonl"
        collector.cap.write(prefix.with_suffix(".measurement-intent.json"), intent)
    with pytest.raises(ValueError, match="differs"):
        collector.validate_measurement(value, case, arm, tmp_path, identity, python, env, config)

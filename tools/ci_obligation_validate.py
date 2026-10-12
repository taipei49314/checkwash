"""Validate owned CI artifacts; native job logs still require independent readback."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ci_obligation_reproduction as owned


def require(condition, message):
    if not condition:
        raise ValueError(message)


def binding(directory, reference=None):
    row = owned.read(directory / "binding.json")
    for source, recorded in (("CANDIDATE_SHA", "candidate_sha"), ("PR_HEAD_SHA", "pr_head_sha"),
                             ("PR_BASE_SHA", "pr_base_sha"), ("GITHUB_RUN_ID", "run_id"),
                             ("GITHUB_RUN_ATTEMPT", "attempt")):
        require(row[recorded] == os.environ[source], "cross-run/source binding mismatch")
    require(row["purpose"] == owned.PURPOSE and row["source_head"] == row["candidate_sha"]
            and not row["source_status"], "candidate identity is unqualified")
    require(row["source_head"] == owned.text_git(owned.ROOT, "rev-parse", "HEAD")
            and row["source_tree"] == owned.text_git(owned.ROOT, "rev-parse", "HEAD^{tree}")
            and row["source_commit"] == owned.text_git(owned.ROOT, "cat-file", "commit", "HEAD")
            and not owned.text_git(owned.ROOT, "status", "--porcelain")
            and row["engine_files"] == owned.engine_files()
            and row["tools"] == {name: owned.digest(owned.ROOT / name) for name in owned.TOOL_PATHS},
            "source/tool bytes differ from current exact candidate")
    if reference is not None:
        require(all(row[key] == reference[key] for key in (
            "source_head", "source_tree", "source_commit", "engine_files", "tools")),
            "native and engine source identities differ")
    return row


def fixture(directory, row, case_id, augmented):
    require(row["case"] == case_id and row["augmented"] is augmented
            and set(row["refs"]) == {"before", "after"}
            and all(re.fullmatch(r"[0-9a-f]{40}", sha) for sha in row["refs"].values()),
            "fixture/ref identity mismatch")
    for side in ("before", "after"):
        expected = owned.snapshot(case_id, side, augmented)
        actual = {path.relative_to(directory / side).as_posix(): path.read_bytes()
                  for path in (directory / side).rglob("*") if path.is_file()}
        require(actual == expected and row["sides"][side]["files"] == owned.hashes(expected),
                "original or augmented source bytes changed")


def process(directory, receipt, expected_argv, expected_cwd):
    terminal = owned.read(directory / "process.observation.json")
    intent = owned.read(directory / "process.intent.json")
    require(terminal == receipt["capture"] and intent["argv"] == expected_argv
            and terminal["argv"] == expected_argv and receipt["argv"] == expected_argv
            and receipt["cwd"] == expected_cwd and receipt["timeout_seconds"] == intent["timeout_seconds"] == 30,
            "CLI actual invocation binding differs")
    require(terminal["status"] in {"EXITED", "TIMEOUT", "OUTPUT_LIMIT", "CAPTURE_FAILED", "SPAWN_FAILED", "DEADLINE_NOT_LAUNCHED"}
            and terminal["output_limit_bytes"] == owned.LIMIT
            and set(terminal["streams"]) == {"stdout", "stderr"}, "unknown process state")
    raw = {}
    for name in ("stdout", "stderr"):
        meta = terminal["streams"][name]
        path = directory / ("process." + name)
        raw[name] = path.read_bytes()
        require(meta["path"] == path.name == intent["streams"][name]
                and meta["sha256"] == owned.digest(path)
                and meta["bytes"] == meta["retained_bytes"] == len(raw[name])
                and len(raw[name]) <= owned.LIMIT
                and (meta["observed_bytes"] is None or meta["observed_bytes"] >= len(raw[name])),
                "raw CLI stream or accounting differs")
    complete = (terminal["status"] == "EXITED" and terminal["spawned"] is True
                and terminal["cleanup_complete"] is True and not terminal["capture_errors"]
                and terminal["first_stop_reason"] is None and not terminal["output_limit_observed"]
                and type(terminal["exit_code"]) is int
                and all(meta["observed_bytes"] == meta["retained_bytes"] for meta in terminal["streams"].values()))
    require(terminal["capture_complete"] is complete, "false complete-capture claim")
    if terminal["spawned"]:
        require(intent["state"] == "LAUNCHED" and intent["launch_executable"] == expected_argv[0]
                and intent["executable"] == terminal["executable"] == str(Path(expected_argv[0]).resolve()),
                "executable differs from launch receipt")
    return raw, complete


def step_outcomes(directory, expected_ids, failed, role):
    document = owned.read(directory / "step-outcomes.json")
    require(document["purpose"] == owned.PURPOSE and document["role"] == role
            and document["event"] == {key: os.environ[key] for key in owned.EVENT_KEYS}, "outcome run differs")
    steps = document["steps"]
    require(set(steps) == set(expected_ids), "missing or additional native Actions step")
    for name, row in steps.items():
        wanted = "failure" if name in failed else "success"
        require(row["outcome"] == row["conclusion"] == wanted, "step outcome/conclusion differs or failure masked")


def validate():
    download = Path(os.environ["DOWNLOADED_ARTIFACTS"])
    artifact_names = {"ci-obligation-engine-attempt-" + os.environ["GITHUB_RUN_ATTEMPT"]}
    artifact_names.update("ci-obligation-native-" + case + "--" + side + "-attempt-" + os.environ["GITHUB_RUN_ATTEMPT"]
                          for case in owned.IDS for side in ("before", "after"))
    require({path.name for path in download.iterdir()} == artifact_names, "artifact set incomplete or duplicated")
    engine_dir = download / ("ci-obligation-engine-attempt-" + os.environ["GITHUB_RUN_ATTEMPT"])
    engine = binding(engine_dir)
    require(engine["policy"] == {"fail_on": "high", "task": None, "date": "2026-10-12",
                                "config_and_allowlist": "ABSENT_BY_EXACT_TREE_IN_BOTH_ARMS"}, "policy drift")
    step_outcomes(engine_dir, ("checkout", "python", "install", "capture"), (), "engine")
    labels = [variant + "--" + case for variant in ("original", "augmented") for case in owned.IDS]
    require(set(engine["inputs"]) == set(labels), "CLI input denominator differs")
    ledger = owned.read(engine_dir / "ledger.json")
    require([row["label"] for row in ledger] == labels, "CLI attempt absent or duplicated")
    require(owned.read(engine_dir / "capture-complete.json") == {
        "purpose": owned.PURPOSE, "attempts": 4, "engine_results": "UNADJUDICATED_NOT_ASSUMED_PASS",
        "native_subject_executions": 0}, "CLI capture phase not complete")
    observations, unusable, end = [], [], -1.0
    for index, label in enumerate(labels):
        source = engine["inputs"][label]
        case_id = owned.IDS[index % 2]
        fixture(engine_dir / "inputs" / label, source, case_id, index >= 2)
        directory = engine_dir / "observations" / label
        receipt = owned.read(directory / "receipt.json")
        require(ledger[index]["receipt_sha256"] == owned.digest(directory / "receipt.json")
                and receipt["binding_sha256"] == owned.digest(engine_dir / "binding.json")
                and receipt["index"] == index and receipt["label"] == label
                and receipt["case"] == case_id and receipt["augmented"] is (index >= 2)
                and receipt["refs"] == source["refs"], "CLI fixture or receipt binding differs")
        start, stopped = receipt["started_monotonic"], receipt["ended_monotonic"]
        require(all(type(value) in (int, float) and math.isfinite(value) for value in (start, stopped))
                and start >= end and stopped >= start, "CLI order/timing invalid")
        end = stopped
        argv = [engine["executable"], "-I", "-B", "-X", "utf8", "-m", "checkwash", "check",
                source["refs"]["before"] + "..." + source["refs"]["after"], "--format", "json", "--fail-on", "high"]
        raw, complete = process(directory, receipt, argv, source["repo"])
        try:
            report = json.loads(raw["stdout"])
        except (ValueError, UnicodeDecodeError):
            require(receipt["json_status"] == "INVALID_OR_ABSENT" and receipt["report"] is None, "invalid JSON relabeled")
            report = None
        else:
            require(receipt["json_status"] == "PARSED" and receipt["report"] == report, "rewritten CLI JSON")
        code = receipt["capture"]["exit_code"]
        usable = (complete and code in (0, 1) and isinstance(report, dict) and not raw["stderr"]
                  and report.get("skipped_files") == [] and report.get("config_errors") == []
                  and report.get("run", {}).get("base") == source["refs"]["before"]
                  and report.get("run", {}).get("head") == source["refs"]["after"]
                  and report.get("run", {}).get("checkwash_version") == engine["engine_version"]
                  and report.get("verdict") == ("pass" if code == 0 else "block")
                  and isinstance(report.get("findings"), list) and isinstance(report.get("summary"), dict))
        observations.append({"label": label, "engine_exit": code, "capture_complete": complete,
                             "usable_zero_skip_observation": usable, "finding_labels": "UNADJUDICATED"})
        if not usable:
            unusable.append(label)
    cells = []
    for case_id in owned.IDS:
        for side in ("before", "after"):
            label = case_id + "--" + side
            directory = download / ("ci-obligation-native-" + label + "-attempt-" + os.environ["GITHUB_RUN_ATTEMPT"])
            native = binding(directory, engine)
            source = engine["inputs"]["augmented--" + case_id]
            fixture(directory / "input", native["fixture"], case_id, True)
            require(native["case"] == case_id and native["side"] == side
                    and native["fixture"]["refs"] == source["refs"]
                    and native["fixture"]["sides"] == source["sides"], "native source is not augmented CLI source")
            step = owned.read(directory / "native-step.json")
            require(step["binding_sha256"] == owned.digest(directory / "binding.json")
                    and step["case"] == case_id and step["side"] == side
                    and step["os_process_exit_code"] is None, "native step attribution differs")
            omitted = (case_id, side) == (owned.IDS[0], "after")
            command = None if omitted else ("bash scripts/test.sh" if (case_id, side) == (owned.IDS[1], "after")
                                           else "python -m pytest tests")
            require(native["native_command"] == command
                    and native["native_cwd"] == native["fixture"]["repo"]
                    and native["native_addopts"] == ("NOT_INVOKED" if omitted else owned.native_addopts())
                    and native["config_sha256"] == owned.hashlib.sha256(b"[pytest]\n").hexdigest(),
                    "native command/cwd/report configuration differs")
            if omitted:
                step_outcomes(directory, ("checkout", "python", "install", "prepare", "finalize"), (), "removed")
                require(native["native_command"] is None and step["native_outcome"] == "NOT_PRESENT"
                        and all(value is None for value in step["reports"].values())
                        and not (directory / "native.xml").exists() and not (directory / "native-pytest.json").exists(),
                        "omitted step invented a test result")
                cells.append({"cell": label, "test_state": "NOT_INVOKED_NOT_PASS", "actual_tests": 0})
                continue
            step_outcomes(directory, ("checkout", "python", "install", "prepare", "native", "finalize"), ("native",), "native")
            require(step["native_outcome"] == "failure", "original failing native step was masked")
            for name in ("native.xml", "native-pytest.json"):
                require(step["reports"][name] == owned.digest(directory / name), "native report bytes changed")
            plugin = owned.read(directory / "native-pytest.json")
            require(plugin["purpose"] == "NATIVE_PYTEST_OBSERVATION_NOT_OS_EXIT_CODE"
                    and plugin["binding_sha256"] == owned.digest(directory / "binding.json")
                    and plugin["case"] == case_id and plugin["side"] == side
                    and plugin["run_id"] == native["run_id"] and plugin["attempt"] == native["attempt"]
                    and plugin["candidate_sha"] == native["candidate_sha"]
                    and plugin["cwd"] == native["native_cwd"]
                    and plugin["executable"] == native["executable_realpath"]
                    and plugin["pytest_version"] == native["pytest_version"] == "8.4.2"
                    and plugin["pytest_path"] == native["pytest_path"]
                    and plugin["argv"][1:] == ["tests"]
                    and plugin["app_path"] == str(Path(native["native_cwd"]) / "app.py")
                    and plugin["addopts"] == native["native_addopts"]
                    and plugin["pythonpath"] == native["expected_pythonpath"]
                    and plugin["plugin_autoload"] == "1"
                    and all(type(plugin[key]) is int for key in ("collected", "failed", "pytest_exit_status"))
                    and plugin["collected"] == plugin["failed"] == plugin["pytest_exit_status"] == 1
                    and plugin["os_process_exit_code"] is None, "native runner/environment/count differs")
            reports = plugin["reports"]
            require([(row["nodeid"], row["when"], row["outcome"]) for row in reports] == [
                ("tests/test_value.py::test_value", "setup", "passed"),
                ("tests/test_value.py::test_value", "call", "failed"),
                ("tests/test_value.py::test_value", "teardown", "passed")]
                and "assert 0 == 1" in reports[1]["longrepr"], "test absent/skipped/error or different oracle")
            xml = ET.parse(directory / "native.xml").getroot()
            suites, tests = list(xml.iter("testsuite")), list(xml.iter("testcase"))
            require(len(suites) == len(tests) == 1
                    and {key: suites[0].get(key) for key in ("tests", "failures", "errors", "skipped")} ==
                        {"tests": "1", "failures": "1", "errors": "0", "skipped": "0"}
                    and tests[0].get("name") == "test_value" and tests[0].get("classname") == "tests.test_value"
                    and len(tests[0].findall("failure")) == 1
                    and "assert 0 == 1" in "".join(tests[0].findall("failure")[0].itertext()), "JUnit ground truth differs")
            cells.append({"cell": label, "test_state": "ONE_ORACLE_FAILED_NO_SKIP", "actual_tests": 1,
                          "pytest_exit_status": 1, "os_process_exit_code": None})
    owned.save(owned.EVIDENCE / "verification.json", {"purpose": owned.PURPOSE,
        "engine_observations": observations, "engine_unusable": unusable, "native_cells": cells,
        "artifact_verification": "COMPLETE", "native_jobs_and_combined_logs": "INDEPENDENT_READBACK_REQUIRED",
        "detector_qualification": "NOT_EVALUATED", "workflow_expected_conclusion": "failure"})
    require(not unusable, "engine observation is incomplete/error/refused; never classify it as PASS")


if __name__ == "__main__":
    owned.EVIDENCE.mkdir(exist_ok=True)
    try:
        validate()
    except Exception as error:
        owned.save(owned.EVIDENCE / "validation-failure.json", {"status": "INCOMPLETE_OR_UNUSABLE_NOT_PASS",
                    "error": type(error).__name__, "detail": str(error)})
        raise

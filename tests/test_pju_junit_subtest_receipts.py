"""Original pytest 9.1.1 evidence and adversarial metadata controls, not product reruns."""
import gzip
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("junit_receipt_legacy_controls", ROOT / "tests/test_pju_receipt_bridge.py")
legacy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(legacy)
B = legacy.bridge
evidence = legacy.evidence  # Reuse the existing owned synthetic packet without modifying it.
FIXTURES = ROOT / "tests/data/pju_junit_pytest911"
XML = gzip.decompress((FIXTURES / "real-junit.xml.gz").read_bytes())
STDOUT = gzip.decompress((FIXTURES / "real-stdout.bin.gz").read_bytes())
SUMMARY = b"20609 passed, 25 skipped, 67 subtests passed in 1302.95s (0:21:42)"
EXPECTED = {"tests": 20634, "skipped": 25, "reported_tests": 20701, "passed_subtests": 67}


def validate(xml=XML, stdout=STDOUT, version="9.1.1"):
    return B.validate_junit(xml, pytest_stdout=stdout, pytest_version=version)


def changed_xml(change):
    root = ET.fromstring(XML)
    change(root, root.find("testsuite"))
    return ET.tostring(root, encoding="utf-8")  # Negative copy only; original bytes are never rewritten.


def test_original_67_subtest_evidence_is_exact_and_supported():
    assert hashlib.sha256(XML).hexdigest() == "20d8d3492a716a11b56cafd58677f94d02a46b75ac5a945ed7614119bab1fd70"
    assert hashlib.sha256(STDOUT).hexdigest() == "0f4be3fa30c3718711ea2c8060bd4bb835fad8ddd25983183b6d79e0bae9808c"
    command_raw = gzip.decompress((FIXTURES / "native-command.receipt.json.gz").read_bytes())
    assert hashlib.sha256(command_raw).hexdigest() == "a03373b554ca40c75634ae26948c04105757d6768fff2a8538c6460e7f4e7a99"
    command = json.loads(command_raw)
    assert command["exit_code"] == 0 and command["raw_complete"] and command["tree_inactive_confirmed"]
    assert STDOUT.splitlines()[-1] == SUMMARY
    assert validate() == EXPECTED


@pytest.mark.parametrize("stdout", [STDOUT, STDOUT.replace(b"\r\n", b"\n")])
def test_original_lf_and_crlf_streams_reconcile(stdout):
    assert validate(stdout=stdout) == EXPECTED


@pytest.mark.parametrize("total", ["20700", "20702", "999999", "20634"])
def test_changed_xml_total_including_false_zero_is_rejected(total):
    with pytest.raises(ValueError):
        validate(XML.replace(b'tests="20701"', ('tests="' + total + '"').encode(), 1))


@pytest.mark.parametrize("version", [None, "9.1", "9.1.0", "9.1.2", "9.2.0", 9.1])
def test_other_or_missing_producer_version_is_rejected(version):
    with pytest.raises(ValueError):
        validate(version=version)


@pytest.mark.parametrize("stdout", [None, "not original bytes", b"", STDOUT.replace(b", 67 subtests passed", b""),
    STDOUT.replace(b"20609 passed", b"20608 passed"), STDOUT.replace(b"25 skipped", b"24 skipped"),
    STDOUT.replace(b"67 subtests passed", b"66 subtests passed"), STDOUT.replace(b"67 subtests passed", b"0 subtests passed"),
    STDOUT + b"not the final summary\n", STDOUT + SUMMARY + b"\n",
    b"1 failed in 0.01s\n" + STDOUT, b"1 error in 0.01s\n" + STDOUT,
    b"1 unknown in 0.01s\n" + STDOUT, b"1 passed in 0.01s\n" + STDOUT,
    b"================ 1 failed in 0.01s ================\n" + STDOUT,
    b"================ 1 error in 0.01s ================\n" + STDOUT,
    b"================ 1 unknown in 0.01s ================\n" + STDOUT,
    b"================ 1 passed in 0.01s ================\n" + STDOUT,
    b"\x1b[31m================ 1 failed in 0.01s ================\x1b[0m\n" + STDOUT,
    STDOUT.replace(b"1302.95s", b"nans"), STDOUT.replace(b"1302.95s", b"infs"),
    STDOUT.replace(b"1302.95s (0:21:42)", b"0.00s"), STDOUT.replace(b"0:21:42", b"0:99:42")])
def test_missing_ambiguous_contradictory_or_malformed_summary_is_rejected(stdout):
    with pytest.raises(ValueError):
        validate(stdout=stdout)


@pytest.mark.parametrize("category", [b"1 failed", b"1 error", b"1 xfailed", b"1 xpassed", b"1 deselected",
    b"1 warning", b"1 subtests failed", b"1 subtests skipped", b"1 unknown"])
def test_unsupported_summary_category_is_not_ignored(category):
    with pytest.raises(ValueError):
        validate(stdout=STDOUT.replace(b", 67 subtests passed", b", " + category + b", 67 subtests passed"))


@pytest.mark.parametrize("mutation", [
    lambda root, suite: suite.set("failures", "1"), lambda root, suite: suite.set("errors", "1"),
    lambda root, suite: suite.set("skipped", "24"), lambda root, suite: root.set("tests", "20634"),
    lambda root, suite: root.set("failures", "1"), lambda root, suite: root.set("errors", "1"),
    lambda root, suite: root.set("skipped", "24"),
    lambda root, suite: suite.find("testcase").append(ET.Element("failure")),
    lambda root, suite: suite.find("testcase").append(ET.Element("error")),
    lambda root, suite: root.append(ET.Element("testcase", name="orphan")),
    lambda root, suite: root.append(ET.Element("testsuite", tests="0", failures="0", errors="0", skipped="0")),
    lambda root, suite: suite.append(ET.Element("testsuite", tests="0", failures="0", errors="0", skipped="0")),
])
def test_xml_failure_aggregate_or_structure_cannot_hide_in_subtests(mutation):
    with pytest.raises(ValueError):
        validate(changed_xml(mutation))


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16", "utf-32"])
def test_dtd_entity_payload_is_rejected_before_subtest_xml_parsing(encoding):
    xml = ('<?xml version="1.0" encoding="' + encoding + '"?>'
        '<!DOCTYPE testsuite [<!ENTITY x "forged">]>'
        '<testsuite tests="2" failures="0" errors="0" skipped="0"><testcase name="&x;"/></testsuite>').encode(encoding)
    with pytest.raises(ValueError):
        validate(xml, b"1 passed, 1 subtests passed in 0.01s\n")


def test_all_skipped_and_malformed_xml_still_rejected():
    with pytest.raises(ValueError):
        validate(b'<testsuite tests="2" failures="0" errors="0" skipped="1"><testcase><skipped/></testcase></testsuite>',
            b"1 passed, 1 subtests passed in 0.01s\n")
    with pytest.raises(ET.ParseError):
        validate(b"<testsuite")


def test_matching_aggregate_remains_valid():
    xml = XML.replace(b'<testsuites ', b'<testsuites tests="20701" failures="0" errors="0" skipped="25" ', 1)
    assert validate(xml) == EXPECTED


@pytest.mark.parametrize("duration", [b"0.01s", b"60.00s", b"60.00s (0:01:00)", b"3601.00s (1:00:00)"])
def test_real_pytest_duration_rounding_boundaries_are_supported(duration):
    xml = b'<testsuite tests="2" failures="0" errors="0" skipped="0"><testcase/></testsuite>'
    assert validate(xml, b"1 passed, 1 subtests passed in " + duration + b"\n") == {
        "tests": 1, "skipped": 0, "reported_tests": 2, "passed_subtests": 1}


@pytest.mark.parametrize("duration", [b"60.01s", b"59.99s (0:01:00)", b"3601.02s (1:00:00)"])
def test_impossible_pytest_duration_suffix_is_rejected(duration):
    xml = b'<testsuite tests="2" failures="0" errors="0" skipped="0"><testcase/></testsuite>'
    with pytest.raises(ValueError):
        validate(xml, b"1 passed, 1 subtests passed in " + duration + b"\n")


def test_ordinary_zero_subtest_rule_and_return_shape_are_unchanged():
    xml = b'<testsuites tests="1"><testsuite tests="1" failures="0" errors="0" skipped="0"><testcase/></testsuite></testsuites>'
    assert B.validate_junit(xml) == {"tests": 1, "skipped": 0}
    assert validate(xml, b"1 passed in 0.01s\n", None) == {"tests": 1, "skipped": 0}
    with pytest.raises(ValueError):
        B.validate_junit(xml.replace(b'tests="1"', b'tests="2"'))


def put_real_owned_junit(evidence):
    evidence["put"](evidence["records"]["junit"], XML)
    pytest_row = next(row for row in evidence["manifest"]["raw_exits"] if row["name"] == "pytest")
    evidence["put"]("real-pytest.stdout", STDOUT)
    pytest_row["stdout"] = "real-pytest.stdout"
    return pytest_row


def test_receipt_entrypoint_reconciles_original_stdout_and_exact_version(evidence):
    put_real_owned_junit(evidence)
    assert evidence["validate"]()["junit"] == EXPECTED


@pytest.mark.parametrize("mutation", ["stdout", "version", "exit", "timeout", "scope"])
def test_receipt_entrypoint_retains_raw_exit_version_and_scope_guards(evidence, mutation):
    row = put_real_owned_junit(evidence)
    if mutation == "stdout":
        evidence["put"]("real-pytest.stdout", STDOUT.replace(b"67 subtests passed", b"66 subtests passed"))
    elif mutation == "version":
        evidence["manifest"]["runtime"]["dependencies"]["pytest"] = "9.1.0"
    elif mutation == "exit":
        row["exit_code"] = 1
    elif mutation == "timeout":
        row["timed_out"] = True
    else:
        row["argv"][-1] = "tests/test_action_security.py"
    with pytest.raises(ValueError):
        evidence["validate"]()


def release_entrypoint_control(evidence, monkeypatch):
    spec = importlib.util.spec_from_file_location("junit_release_entrypoint_control", ROOT / "tools/pju_release_bridge.py")
    release = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(release)
    manifest = evidence["manifest"]
    manifest["records"]["release"] = {}  # Downstream release data is never reached in this control.
    manifest["subject"] = {"stage": "pr", "event": {"created_at": "2026-10-23T00:00:00Z"}}
    for name in ("verdict-gate", "twine-check", "zipapp-qualification"):
        row = copy.deepcopy(manifest["raw_exits"][0])
        row["name"] = name
        manifest["raw_exits"].append(row)
    # Contract identity is outside this call-wiring control. All real raw-exit,
    # full-pytest argv and JUnit validation below still execute as metadata.
    monkeypatch.setattr(release.B, "validate_contract", lambda *args: evidence["desc"])
    observed = []
    original = release.B.validate_junit

    def validate_original(raw, **kwargs):
        value = original(raw, **kwargs)
        observed.append((raw, kwargs, value))
        return value

    class AfterJunit(Exception):
        pass

    def stop_before_downstream(*args):
        raise AfterJunit("intentional control boundary; never a product-gate PASS")

    monkeypatch.setattr(release.B, "validate_junit", validate_original)
    monkeypatch.setattr(release.B, "validate_action", stop_before_downstream)

    def invoke():
        packet = B.Packet(evidence["packet"], evidence["freeze"]())
        return release.validate_product(packet, evidence["source"], evidence["source"], evidence["head"])

    return invoke, observed, AfterJunit


def test_release_entrypoint_uses_original_pytest_row_stdout_and_runtime_version(evidence, monkeypatch):
    put_real_owned_junit(evidence)
    invoke, observed, after_junit = release_entrypoint_control(evidence, monkeypatch)
    with pytest.raises(after_junit):
        invoke()
    assert len(observed) == 1
    assert observed[0] == (XML, {"pytest_stdout": STDOUT, "pytest_version": "9.1.1"}, EXPECTED)


@pytest.mark.parametrize("mutation", ["another-row-stdout", "wrong-runtime-version", "false-zero", "nonzero-exit", "narrow-scope"])
def test_release_entrypoint_real_validator_rejects_wrong_context(evidence, monkeypatch, mutation):
    row = put_real_owned_junit(evidence)
    if mutation == "another-row-stdout":
        row["stdout"] = "stdout.log"  # Existing owned stream, not the real pytest summary.
    elif mutation == "wrong-runtime-version":
        evidence["manifest"]["runtime"]["dependencies"]["pytest"] = "9.1.2"
    elif mutation == "false-zero":
        evidence["put"](evidence["records"]["junit"], XML.replace(b'tests="20701"', b'tests="20634"', 1))
    elif mutation == "nonzero-exit":
        row["exit_code"] = 1
    else:
        row["argv"][-1] = "tests/test_action_security.py"
    invoke, _, _ = release_entrypoint_control(evidence, monkeypatch)
    with pytest.raises(ValueError):
        invoke()

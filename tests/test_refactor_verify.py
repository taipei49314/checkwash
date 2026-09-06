"""A failing pytest process is not necessarily a test that caught the bug."""

import importlib.util
import json
import pathlib
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "refactor_verify", ROOT / "benchmarks/refactors/verify.py",
)
verify = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify)


@pytest.mark.parametrize("source,status,code,failures,errors", [
    ("def test_value(): assert 1 == 1\n", "pass", 0, 0, 0),
    ("def test_value(): assert 1 == 2\n", "test_failure", 1, 1, 0),
    ("import unavailable_refactor_module\n", "invalid", 2, 0, 1),
    ("def test_value(missing_fixture): pass\n", "invalid", 1, 0, 1),
    ("import pytest\n@pytest.fixture\ndef value():\n    assert 1 == 2\n"
     "def test_value(value): pass\n", "invalid", 1, 0, 1),
    ("import pytest\n@pytest.fixture\ndef value():\n    yield 1\n    assert 1 == 2\n"
     "def test_value(value): assert value == 2\n", "invalid", 1, 1, 1),
    ("import pytest\ndef test_value(): pytest.skip('not executed')\n", "invalid", 0, 0, 0),
    ("VALUE = 1\n", "invalid", 5, 0, 0),
])
def test_only_completed_test_failure_qualifies(tmp_path, source, status, code, failures, errors):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_value.py").write_text(source, encoding="utf-8")
    observed = verify._run_tests(tests, tmp_path)
    assert observed["status"] == status
    assert observed["exit_code"] == code
    assert observed["counts"]["failures"] == failures
    assert observed["counts"]["errors"] == errors
    assert observed["junit_xml"]
    assert observed["stdout"]
    if status == "invalid":
        assert observed["reason"]


def test_usage_error_is_invalid_with_diagnostics(tmp_path):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tmp_path / "pytest.ini").write_text(
        "[pytest]\naddopts = --unknown-refactor-option\n", encoding="utf-8",
    )
    observed = verify._run_tests(tests, tmp_path)
    assert observed["exit_code"] == 4
    assert observed["status"] == "invalid"
    assert "unrecognized arguments" in observed["stderr"]


def test_timeout_is_invalid(tmp_path):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_value.py").write_text(
        "import time\ndef test_value(): time.sleep(10)\n", encoding="utf-8",
    )
    observed = verify._run_tests(tests, tmp_path, timeout=1)
    assert observed["status"] == "invalid"
    assert observed["reason"] == "timeout"
    assert observed["exit_code"] is None


@pytest.mark.parametrize("report", [None, (
    '<testsuites><testsuite tests="1" failures="0" errors="0" skipped="0">'
    '<testcase name="test_value"><failure message="assert 1 == 2" /></testcase>'
    '</testsuite></testsuites>'
)])
def test_missing_or_inconsistent_report_cannot_qualify(tmp_path, monkeypatch, report):
    def run(command, **kwargs):
        if report is not None:
            report_path = next(arg.split("=", 1)[1] for arg in command
                               if arg.startswith("--junitxml="))
            pathlib.Path(report_path).write_text(report, encoding="utf-8")
        return subprocess.CompletedProcess(command, 1, b"one test failed", b"")

    monkeypatch.setattr(verify.subprocess, "run", run)
    observed = verify._run_tests(tmp_path, tmp_path)
    assert observed["status"] == "invalid"
    assert observed["reason"].startswith("missing_or_invalid_report:")
    assert observed["exit_code"] == 1
    assert observed["stdout"] == "one test failed"


def _cohort(tmp_path, setup_assertion=False):
    corpus = tmp_path / "cases"
    case = corpus / "toy"
    source = "from app import value\ndef test_value(): assert value() == 1\n"
    if setup_assertion:
        source = ("import pytest\nfrom app import value\n@pytest.fixture\ndef checked():\n"
                  "    assert value() == 1\ndef test_value(checked): pass\n")
    for side in ("BEFORE", "AFTER"):
        tests = case / side / "tests"
        tests.mkdir(parents=True)
        (tests / "test_value.py").write_text(source, encoding="utf-8")
    for side, value in (("PROD-GOOD", 1), ("PROD-BUG", 0)):
        src = case / side / "src"
        src.mkdir(parents=True)
        (src / "app.py").write_text(f"def value(): return {value}\n", encoding="utf-8")
    (case / "WHY.txt").write_text("Both suites require value() == 1.", encoding="utf-8")
    expected = tmp_path / "expected.json"
    expected.write_text(json.dumps({"cases": {"toy": {"blocks": False}}}), encoding="utf-8")
    output = tmp_path / "receipt.json"
    return corpus, expected, output


@pytest.mark.parametrize("setup_assertion", [False, True])
def test_receipt_keeps_four_runs_and_fails_incomplete_cohort(tmp_path, setup_assertion):
    corpus, expected, output = _cohort(tmp_path, setup_assertion)
    code = verify.main([str(corpus), "--expected", str(expected), "--output", str(output)])
    receipt = json.loads(output.read_text(encoding="utf-8"))
    assert code == (2 if setup_assertion else 0)
    assert receipt["status"] == ("incomplete" if setup_assertion else "complete")
    assert receipt["summary"]["total_cases"] == 1
    assert receipt["summary"]["valid_cases"] == (0 if setup_assertion else 1)
    row = receipt["cases"][0]
    assert len(row["observations"]) == 4
    assert row["checks"]["before_good_pass"]
    assert row["checks"]["before_bug_fail"] is (not setup_assertion)
    assert receipt["engine_version"] == verify.__version__
    assert receipt["inputs"]["expected_sha256"] == verify._sha(expected)
    assert receipt["inputs"]["verifier_sha256"] == verify._sha(pathlib.Path(verify.__file__))
    assert receipt["inputs"]["corpus"]["files"]["toy/WHY.txt"]
    assert receipt["inputs_unchanged"]
    assert receipt["started_at"] <= receipt["finished_at"]


def test_missing_case_is_retained_and_existing_receipt_is_never_overwritten(tmp_path):
    corpus = tmp_path / "cases"
    corpus.mkdir()
    expected = tmp_path / "expected.json"
    expected.write_text('{"cases": {"missing": {"blocks": false}}}', encoding="utf-8")
    output = tmp_path / "receipt.json"
    args = [str(corpus), "--expected", str(expected), "--output", str(output)]
    assert verify.main(args) == 2
    original = output.read_bytes()
    receipt = json.loads(original)
    assert receipt["summary"]["missing_cases"] == ["missing"]
    assert receipt["cases"][0]["case"] == "missing"
    assert not receipt["cases"][0]["valid"]
    with pytest.raises(SystemExit) as exc:
        verify.main(args)
    assert exc.value.code == 2
    assert output.read_bytes() == original


def test_inputs_changed_during_run_prevent_complete_receipt(tmp_path, monkeypatch):
    corpus, expected, output = _cohort(tmp_path)
    original_run = verify._run_tests

    def run(*args, **kwargs):
        result = original_run(*args, **kwargs)
        (corpus / "toy/WHY.txt").write_text("Changed during measurement.", encoding="utf-8")
        return result

    monkeypatch.setattr(verify, "_run_tests", run)
    assert verify.main([str(corpus), "--expected", str(expected), "--output", str(output)]) == 2
    receipt = json.loads(output.read_text(encoding="utf-8"))
    assert receipt["summary"]["valid_cases"] == 1
    assert not receipt["inputs_unchanged"]
    assert receipt["status"] == "incomplete"


@pytest.mark.parametrize("document", [
    [], {}, {"cases": ["toy", "toy"]}, {"cases": {}},
    *({"cases": {name: {"blocks": False}}}
      for name in ("", ".", "..", "../toy", "toy/child", "toy\\child", "C:toy")),
])
def test_invalid_membership_schema_stops_before_measurement(tmp_path, monkeypatch, document):
    corpus, expected, output = _cohort(tmp_path)
    expected.write_text(json.dumps(document), encoding="utf-8")

    def run(*args, **kwargs):
        pytest.fail("an invalid membership table must not start measurement")

    monkeypatch.setattr(verify, "_run_tests", run)
    with pytest.raises(SystemExit) as exc:
        verify.main([str(corpus), "--expected", str(expected), "--output", str(output)])
    assert exc.value.code == 2
    assert not output.exists()

"""Report locations must refer to the exact analyzed source and side."""

import datetime
import json

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.findings import Evidence, Finding
from checkwash.ir.model import IR
from checkwash.report.context import ReportContext
from checkwash.report.jsonout import findings_to_json, ir_to_json
from checkwash.report.sarif import findings_to_sarif


def _run(changes, **kwargs):
    context = ReportContext()
    ir, findings, verdict = analyze(
        changes, Config(), Contract(), [], datetime.date(2026, 9, 6),
        report_context=context, **kwargs,
    )
    results = json.loads(findings_to_sarif(ir, findings, context))["runs"][0]["results"]
    return ir, findings, verdict, results


def _physical(result):
    return result["locations"][0]["physicalLocation"]


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
@pytest.mark.parametrize("padding", [0, 3])
def test_unicode_and_line_endings_use_actual_head_line(newline, padding):
    before = '# 中文😀\n\ndef test_value():\n    assert value == 5\n'
    after = "\n" * padding + before.replace("== 5", "> 0")
    change = FileChange("tests/test_中文 #%.py", "modified",
                        before.replace("\n", newline).encode(),
                        after.replace("\n", newline).encode())
    _, _, verdict, results = _run([change])
    assert verdict == "block"
    hit = next(r for r in results if r["ruleId"] == "ASSERT_WEAKENED")
    assert _physical(hit) == {
        "artifactLocation": {"uri": "tests/test_%E4%B8%AD%E6%96%87%20%23%25.py"},
        "region": {"startLine": 4 + padding},
    }


def test_multiple_and_multiline_assertions_have_independent_locations():
    before = b"def test_values():\n    assert (\n        first == 5\n    )\n    assert second == 7\n"
    after = before.replace(b"first == 5", b"first > 0").replace(b"second == 7", b"second > 0")
    _, _, _, results = _run([FileChange("test_values.py", "modified", before, after)])
    hits = [r for r in results if r["ruleId"] == "ASSERT_WEAKENED"]
    assert sorted(_physical(r)["region"]["startLine"] for r in hits) == [2, 5]


@pytest.mark.parametrize("after", [b"def test_value():\n    pass\n", None])
def test_deleted_evidence_stays_file_level_even_when_head_exists(after):
    before = b"\n\ndef test_value():\n    assert value == 5\n"
    _, _, verdict, results = _run([
        FileChange("test_value.py", "deleted" if after is None else "modified", before, after)
    ])
    assert verdict == "block"
    assert results
    for result in results:
        assert "region" not in _physical(result)
        if result["ruleId"] in {"ASSERT_REMOVED", "TEST_DISABLED"}:
            assert result["properties"]["checkwash.evidenceSide"] == "base"


def test_crossfile_assertion_is_located_in_helper_not_importing_test():
    test = b"from test_helper import check_value\n\ndef test_value():\n    check_value()\n"
    helper = b"\n\n\n\ndef check_value():\n    assert value == 5\n"
    _, _, _, results = _run([
        FileChange("tests/test_value.py", "modified", test, test + b"# touched\n"),
        FileChange("tests/test_helper.py", "modified", helper, helper.replace(b"== 5", b"> 0")),
    ])
    hit = next(r for r in results if r["ruleId"] == "ASSERT_WEAKENED")
    assert _physical(hit) == {
        "artifactLocation": {"uri": "tests/test_helper.py"},
        "region": {"startLine": 6},
    }


def test_unchanged_helper_snapshot_is_recorded_for_both_sides():
    # Base resolution populates the shared read cache first; head must still
    # have source provenance without making an additional filesystem read.
    test = b"from test_helper import check_value\n\ndef test_value():\n    check_value()\n"
    helper = b"\n\ndef check_value():\n    assert value == 5\n"
    reads = []

    def reader(path):
        reads.append(path)
        return helper if path == "tests/test_helper.py" else None

    context = ReportContext()
    ir, _, _ = analyze(
        [FileChange("tests/test_value.py", "modified", test, test + b"# touched\n")],
        Config(), Contract(), [], datetime.date(2026, 9, 6),
        head_reader=reader, report_context=context,
    )
    assertion = ir.files[0].units[0].after.assertions[0]
    assert context.location("tests/test_value.py", Evidence(assertion.text, assertion.span)) == (
        "tests/test_helper.py", 4
    )
    assert reads.count("tests/test_helper.py") == 1


def test_unknown_synthetic_and_ambiguous_evidence_do_not_invent_line_one():
    evidence = Evidence("assert value > 0", (0, 16))
    finding = Finding("ASSERT_WEAKENED", "high", "weakened", "test_x.py", "test_x", after=evidence)
    context = ReportContext()
    for path in ("test_x.py", "test_helper.py"):
        context.snapshot(path, 1, b"assert value > 0\n")
        context.bind("test_x.py", 1, evidence, path)
    for candidate_context in (None, context):
        result = json.loads(findings_to_sarif(IR(base="base", head="head"), [finding], candidate_context))["runs"][0]["results"][0]
        assert "region" not in _physical(result)
        assert result["properties"]["checkwash.evidenceText"] == evidence.text
    _, _, _, results = _run([
        FileChange("AGENTS.md", "modified", b"do not change tests\n", b"change tests\n")
    ])
    assert all("region" not in _physical(r) for r in results)


def test_reporting_context_does_not_change_ir_json_verdict_or_allowlist_filtering():
    changes = [FileChange("test_x.py", "modified", b"def test_x():\n    assert x == 5\n",
                          b"def test_x():\n    assert x > 0\n")]
    ir, findings, verdict, _ = _run(changes)
    plain_ir, plain_findings, plain_verdict = analyze(
        changes, Config(), Contract(), [], datetime.date(2026, 9, 6)
    )
    assert ir_to_json(ir) == ir_to_json(plain_ir)
    assert findings_to_json(ir, findings, verdict) == findings_to_json(plain_ir, plain_findings, plain_verdict)
    for finding in findings:
        finding.allowlisted = True
    assert json.loads(findings_to_sarif(ir, findings))["runs"][0]["results"] == []


def test_projected_root_helper_expected_value_points_to_the_caller():
    before = b"from calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n"
    after = b"from calc import add\nfrom test_helpers import assert_equal\n\ndef test_add():\n    assert_equal(add(2, 3), 4)\n"
    helper = b"\n\ndef assert_equal(actual, expected):\n    assert actual == expected\n"
    _, _, verdict, results = _run([
        FileChange("tests/test_calc.py", "modified", before, after),
        FileChange("test_helpers.py", "added", None, helper),
    ], root_reader={}.get)
    assert verdict == "block"
    hit = next(r for r in results if r["ruleId"] == "EXPECTED_VALUE_CHANGED")
    assert _physical(hit) == {
        "artifactLocation": {"uri": "tests/test_calc.py"},
        "region": {"startLine": 5},
    }

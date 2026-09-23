"""Coverage diagnostics expose missed JS assertion syntax without changing verdicts."""

import datetime
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze
from checkwash.frontends.javascript.coverage import javascript_coverage_gaps
from checkwash.frontends.javascript.frontend import parse_javascript
from checkwash.report.context import ReportContext
from checkwash.report.jsonout import findings_to_json, ir_to_json


def _source(body):
    return f'test("total", (t) => {{\n  {body}\n}});\n'.encode()


def _gaps(source, side="after", path="tests/total.test.mjs"):
    if isinstance(source, str):
        source = source.encode()
    return javascript_coverage_gaps(source, parse_javascript(source), path, side)


def _analyze(before, after, context=None, path="tests/total.test.mjs"):
    return analyze(
        [FileChange(path, "modified", _source(before), _source(after))],
        Config(), Contract(), [], datetime.date(2026, 9, 23),
        report_context=context,
    )


@pytest.mark.parametrize("call,callee", [
    ("assert.match(value, /expected/)", "assert.match"),
    ("t.assert.rejects(operation)", "t.assert.rejects"),
    ("assert['strictEqual'](value, 5)", "assert['strictEqual']"),
    ("expect(value).toHaveLength(2)", "expect(...).toHaveLength"),
    ("expect(operation()).resolves.toBe(5)", "expect(...).resolves.toBe"),
])
def test_unknown_assertion_families_remain_visible(call, callee):
    gap, = _gaps(_source(call + ";"))
    assert gap.callee == callee
    assert (gap.path, gap.side, gap.line, gap.column) == (
        "tests/total.test.mjs", "after", 2, 3,
    )
    assert "not represented" in gap.reason
    assert "analysis incomplete" in gap.message()


def test_candidate_inventory_does_not_require_a_recognized_test_unit():
    source = b'customTest("total", () => { assert.strictEqual(value, 5); });'
    assert parse_javascript(source).units == []
    gap, = _gaps(source)
    assert gap.callee == "assert.strictEqual"


def test_supported_outer_call_does_not_hide_an_unknown_nested_assertion():
    source = _source("assert.strictEqual(assert.match(value, /expected/), undefined);")
    assert len(parse_javascript(source).units[0].side.assertions) == 1
    gap, = _gaps(source)
    assert gap.callee == "assert.match"


def test_mixed_unit_reports_only_unrepresented_candidates():
    gaps = _gaps(_source("""assert.strictEqual(value, 5);
  expect(items).toHaveLength(2);
  t.assert.ok(value);
  assert.match(name, /expected/);"""))
    assert [(gap.line, gap.callee) for gap in gaps] == [
        (3, "expect(...).toHaveLength"), (5, "assert.match"),
    ]


def test_declared_supported_api_inventory_has_no_coverage_gaps():
    contract_tools = runpy.run_path(str(Path(__file__).resolve().parents[1] / "tools/assertion_contract.py"))
    supported = [case for case in contract_tools["load_contract"]()["apis"] if case["status"] == "supported"]
    assert supported
    for case in supported:
        assert _gaps(case["source"], path=case["path"]) == [], case["id"]


@pytest.mark.parametrize("binding,call,callee", [
    ('import verify from "node:assert";', "verify.strictEqual(value, 5)", "verify.strictEqual"),
    ('import verify from "assert/strict";', "verify(value)", "verify"),
    ('import * as verify from "node:assert/strict";', "verify.ok(value)", "verify.ok"),
    ('import { strictEqual as same } from "node:assert";', "same(value, 5)", "same"),
    ('import { strictEqual } from "node:assert";', "strictEqual(value, 5)", "strictEqual"),
    ('const verify = require("node:assert");', "verify.equal(value, 5)", "verify.equal"),
    ('const { deepEqual: same } = require("assert");', "same(value, [5])", "same"),
])
def test_node_import_aliases_are_candidates_even_without_frontend_support(binding, call, callee):
    source = binding.encode() + b"\n" + _source(call + ";")
    gap, = _gaps(source)
    assert gap.callee == callee


@pytest.mark.parametrize("binding,call,callee", [
    ('import { strictEqual /* ordinary comment */ as same } from "node:assert";',
     "same(value, 5)", "same"),
    ('import verify /* comment */ from /* comment */ "node:assert";',
     "verify.strictEqual(value, 5)", "verify.strictEqual"),
    ('const { deepEqual /* comment */: same } = require(/* comment */ "assert");',
     "same(value, [5])", "same"),
])
def test_commented_imports_preserve_real_node_alias_candidates(binding, call, callee):
    source = binding.encode() + b"\n" + _source(call + ";")
    gap, = _gaps(source)
    assert gap.callee == callee


def test_commented_import_text_cannot_turn_a_utility_into_a_node_assertion():
    source = (
        b'import ordinary /* from "node:assert" */ from "utility";\n'
        + _source("ordinary();")
    )
    assert _gaps(source) == []


@pytest.mark.parametrize("binding,construction", [
    ('import { AssertionError } from "node:assert";', 'new AssertionError({ message: "example" })'),
    ('import { AssertionError as Failure } from "node:assert";', 'new Failure({ message: "example" })'),
    ('import { Assert } from "node:assert";', "new Assert()"),
    ('import { Assert as Assertions } from "node:assert";', "new Assertions()"),
    ('import assert from "node:assert";', 'new assert.AssertionError({ message: "example" })'),
])
def test_node_constructors_are_not_assertion_candidates(binding, construction):
    source = binding.encode() + b"\n" + _source(construction + ";")
    assert _gaps(source) == []


@pytest.mark.parametrize("noise", [
    "// assert.match(value, /expected/);",
    "/* t.assert.rejects(operation); */",
    "const sample = 'assert.match(value, /expected/)';",
    'const sample = "expect(value).toHaveLength(2)";',
    "const sample = `assert.match(value, /expected/)`;",
    "const sample = /assert.match(value, expected)/;",
    "object.assert.match(value, /expected/);",
    "object . /* member */ assert.match(value, /expected/);",
    "this.#assert(value);",
    "class Helper { #assert(value) {} }",
    "function assert(value) {}",
    "function* assert(value) {}",
    "function assert(value: unknown): asserts value {}",
    "class Helper { assert(value: number): boolean { return true; } }",
    "function expect(value) {}",
    '// import verify from "node:assert";\nverify.match(value, /expected/);',
])
def test_inert_text_members_and_declarations_do_not_invent_gaps(noise):
    assert _gaps(_source(noise)) == []


@pytest.mark.parametrize("body", ["", "runTransaction();", "throw new Error('expected');"])
def test_zero_assertion_test_is_not_a_coverage_gap(body):
    assert _gaps(_source(body)) == []


def test_coverage_locations_use_normalized_bom_crlf_source():
    source = b'\xef\xbb\xbftest("total", () => {\r\n  assert.match(value, /expected/);\r\n});\r\n'
    gap, = _gaps(source, "before", "tests/總額.test.mjs")
    assert (gap.path, gap.side, gap.line, gap.column) == ("tests/總額.test.mjs", "before", 2, 3)


def test_deleted_unknown_assertion_is_reported_on_the_base_side_without_a_finding():
    context = ReportContext(collect_locations=False)
    _ir, findings, verdict = _analyze("assert.match(value, /expected/);", "runTransaction();", context)
    gap, = context.coverage_gaps
    assert (gap.side, gap.callee) == ("before", "assert.match")
    assert findings == []
    assert verdict == "pass"
    assert context._sources == {}
    assert context._origins == {}


def test_coverage_context_preserves_existing_json_ir_findings_and_verdict():
    before = "assert.strictEqual(value, 5); assert.match(name, /expected/);"
    after = "assert.ok(value); assert.match(name, /changed/);"
    plain_ir, plain_findings, plain_verdict = _analyze(before, after)
    context = ReportContext(collect_locations=False)
    ir, findings, verdict = _analyze(before, after, context)
    assert [(gap.side, gap.callee) for gap in context.coverage_gaps] == [
        ("before", "assert.match"), ("after", "assert.match"),
    ]
    assert verdict == plain_verdict == "block"
    assert findings_to_json(ir, findings, verdict) == findings_to_json(plain_ir, plain_findings, plain_verdict)
    assert ir_to_json(ir) == ir_to_json(plain_ir)


@pytest.mark.parametrize("body,status", [
    ("runTransaction();", "no_known_gaps"),
    ("assert.strictEqual(value, 5);", "no_known_gaps"),
    ("assert.match(value, /expected/);", "incomplete"),
])
def test_sidecar_has_its_own_schema_and_records_the_analyzed_sides(body, status):
    from checkwash.report.coverage import coverage_to_json

    context = ReportContext(collect_locations=False)
    ir, _findings, _verdict = _analyze(body, body, context)
    payload = json.loads(coverage_to_json(ir, context))
    assert set(payload) == {"checkwash_coverage_version", "run", "scope", "status", "files", "gaps"}
    assert payload["checkwash_coverage_version"] == 1
    assert payload["scope"] == "javascript_assertion_candidates"
    assert payload["status"] == status
    assert payload["files"] == [
        {"path": "tests/total.test.mjs", "side": "before"},
        {"path": "tests/total.test.mjs", "side": "after"},
    ]
    assert set(payload["run"]) == {"base", "head", "checkwash_version"}
    assert bool(payload["gaps"]) == (status == "incomplete")
    if payload["gaps"]:
        assert set(payload["gaps"][0]) == {"path", "side", "line", "column", "callee", "reason"}


def test_sidecar_is_deterministic_across_input_file_order():
    from checkwash.report.coverage import coverage_to_json

    changes = [
        FileChange(path, "modified", _source("assert.match(value, /expected/);"), _source("runTransaction();"))
        for path in ["tests/z.test.mjs", "tests/a.test.mjs"]
    ]
    outputs = []
    for ordered in [changes, list(reversed(changes))]:
        context = ReportContext(collect_locations=False)
        ir, _findings, _verdict = analyze(
            ordered, Config(), Contract(), [], datetime.date(2026, 9, 23), report_context=context,
        )
        outputs.append(coverage_to_json(ir, context))
    assert outputs[0] == outputs[1]
    assert "\r" not in outputs[0]


def test_sarif_notifications_preserve_base_and_head_evidence_sides():
    from checkwash.report.sarif import findings_to_sarif

    context = ReportContext()
    ir, findings, _verdict = _analyze("assert.match(value, /expected/);", "assert.match(value, /changed/);", context)
    run, = json.loads(findings_to_sarif(ir, findings, context))["runs"]
    invocation, = run["invocations"]
    assert invocation["executionSuccessful"] is True
    assert run["results"] == []
    before, after = invocation["toolExecutionNotifications"]
    assert before["properties"]["checkwash.side"] == "before"
    assert after["properties"]["checkwash.side"] == "after"
    assert "locations" not in before
    assert after["locations"][0]["physicalLocation"]["region"]["startLine"] == 2


@pytest.fixture(scope="module")
def coverage_repo(tmp_path_factory):
    repo = tmp_path_factory.mktemp("js-coverage-repo")

    def git(*args):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)

    git("init", "-b", "main")
    git("config", "user.name", "coverage-test")
    git("config", "user.email", "coverage@example.invalid")
    git("config", "commit.gpgsign", "false")
    test_file = repo / "總額.test.mjs"
    test_file.write_bytes(_source("assert.match(value, /expected/);"))
    git("add", "-A")
    git("commit", "-m", "base")
    test_file.write_bytes(_source("assert.match(value, /changed/);"))
    return repo


@pytest.mark.parametrize("format_name", ["term", "json", "sarif", "hook-json", "emit-ir"])
def test_cli_keeps_protocol_output_and_exposes_coverage_on_every_format(coverage_repo, tmp_path, format_name):
    sidecar = tmp_path / "coverage.json"
    selection = ["--emit-ir"] if format_name == "emit-ir" else ["--format", format_name]
    # Exercise default diagnostics too: a sidecar request must not be needed
    # to expose gaps through the hook or IR early-return paths.
    sidecar_args = [] if format_name in {"hook-json", "emit-ir"} else ["--coverage-report", str(sidecar)]
    result = subprocess.run(
        [sys.executable, "-m", "checkwash", "check", "--repo", str(coverage_repo),
         *selection, *sidecar_args],
        capture_output=True, encoding="utf-8",
        env={**os.environ, "GREENWASH_TODAY": "2026-09-23", "NO_COLOR": "1", "PYTHONIOENCODING": "ascii"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "analysis incomplete" in result.stderr
    assert "assert.match" in result.stderr
    if sidecar_args:
        coverage = json.loads(sidecar.read_text(encoding="utf-8"))
        assert coverage["status"] == "incomplete"
        assert [(gap["side"], gap["path"]) for gap in coverage["gaps"]] == [
            ("before", "總額.test.mjs"), ("after", "總額.test.mjs"),
        ]
    else:
        assert not sidecar.exists()
    if format_name == "term":
        assert "analysis incomplete" in result.stdout
        assert "verdict=pass" in result.stdout
    else:
        payload = json.loads(result.stdout)
        if format_name == "json":
            assert set(payload) == {"checkwash_findings_version", "run", "findings", "summary", "skipped_files", "config_errors", "verdict"}
            assert payload["verdict"] == "pass"
            assert payload["findings"] == []
        elif format_name == "hook-json":
            assert payload == {}
        elif format_name == "emit-ir":
            assert "coverage_gaps" not in payload
            assert payload["files"][0]["path"] == "總額.test.mjs"
        else:
            assert payload["version"] == "2.1.0"
            assert payload["runs"][0]["invocations"][0]["executionSuccessful"] is True


def test_sidecar_cannot_be_mixed_into_stdout(coverage_repo, capsys):
    from checkwash.cli import main

    result = main(["check", "--repo", str(coverage_repo), "--format", "json", "--coverage-report", "-"])
    captured = capsys.readouterr()
    assert result == 2
    assert captured.out == ""
    assert "requires a file path" in captured.err

"""Writes and lexical shadows cannot preserve borrowed assertion authority."""

import datetime

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze
from checkwash.frontends.javascript.coverage import javascript_coverage_gaps
from checkwash.frontends.javascript.frontend import parse_javascript


def _source(body, imports='import assert from "node:assert/strict";'):
    return f'{imports}\ntest("sample", () => {{\n{body}\n}});\n'.encode()


def _assertions(source):
    parsed = parse_javascript(source)
    assert parsed.parse_ok
    return [assertion for unit in parsed.units for assertion in unit.side.assertions]


def _gaps(source):
    return javascript_coverage_gaps(source, parse_javascript(source), "test/example.js", "after")


@pytest.mark.parametrize("body,callee", [
    ('{ assert.strictEqual = () => {}; } assert.strictEqual(value, 5);', "assert.strictEqual"),
    ('let check = assert; { check = standin; } check.strictEqual(value, 5);', "check.strictEqual"),
    ('consume(), assert.strictEqual = () => {}; assert.strictEqual(value, 5);', "assert.strictEqual"),
    ('let check = assert; consume(), check = standin; check.strictEqual(value, 5);', "check.strictEqual"),
    ('assert.strictEqual = () => {}; const check = assert.strictEqual; check(value, 5);', "check"),
    ('let check = assert.strictEqual; { check = () => {}; } check(value, 5);', "check"),
    ('const helper = { run(assert) { assert.strictEqual(value, 5); } };', "assert.strictEqual"),
])
def test_writes_and_method_parameter_shadows_remove_the_old_oracle(body, callee):
    before = _source("assert.strictEqual(value, 5);")
    after = _source(body)
    assert len(_assertions(before)) == 1
    assert _assertions(after) == []
    assert any(gap.callee == callee for gap in _gaps(after))
    _ir, findings, verdict = analyze(
        [FileChange("test/example.js", "modified", before, after)],
        Config(), Contract(), [], datetime.date(2026, 9, 23),
    )
    assert verdict == "block"
    assert [(finding.rule, finding.severity) for finding in findings] == [("ASSERT_REMOVED", "high")]


@pytest.mark.parametrize("body", [
    "const check = assert.strictEqual; assert.strictEqual = () => {}; check(value, 5);",
    "const check = assert.strictEqual; { assert.strictEqual = () => {}; } check(value, 5);",
    "{ const assert = {}; assert.strictEqual = () => {}; } assert.strictEqual(value, 5);",
    "let check = assert; { let check = standin; check = other; } check.strictEqual(value, 5);",
    "function unused() { assert.strictEqual = () => {}; } assert.strictEqual(value, 5);",
    "const unused = () => { assert.strictEqual = () => {}; }; assert.strictEqual(value, 5);",
    "const other = 1, check = assert; check.strictEqual(value, 5);",
    "function helper(assert = standin) {} assert.strictEqual(value, 5);",
    "const helper = { run(assert = standin) {} }; assert.strictEqual(value, 5);",
])
def test_capture_time_and_distinct_bindings_preserve_the_original_oracle(body):
    source = _source(body)
    assertion, = _assertions(source)
    assert assertion.left == "value"
    assert _gaps(source) == []


@pytest.mark.parametrize("declaration", [
    "const helper = { run(assert) { assert.strictEqual(inner(), 1); } };",
    "const helper = { async run(assert) { assert.strictEqual(inner(), 1); } };",
    "const helper = { *run(assert) { assert.strictEqual(inner(), 1); } };",
    "const helper = { run({assert}) { assert.strictEqual(inner(), 1); } };",
    "class Helper { run(assert) { assert.strictEqual(inner(), 1); } }",
    "class Helper { static run(assert) { assert.strictEqual(inner(), 1); } }",
    "class Helper { run([assert]) { assert.strictEqual(inner(), 1); } }",
])
def test_method_parameters_are_local_shadows_with_visible_unresolved_calls(declaration):
    source = _source(declaration + " assert.strictEqual(outside(), 2);")
    assert [assertion.left for assertion in _assertions(source)] == ["outside()"]
    gap, = _gaps(source)
    assert gap.callee == "assert.strictEqual"


@pytest.mark.parametrize("parameter", [
    "{ payload: { assert } }",
    "{ payload: { assert = standin } }",
    "{ payload: [assert] }",
    "{ ...assert }",
    "[ , ...assert ]",
    "{ [key]: assert }",
])
def test_nested_binding_patterns_shadow_only_the_bound_names(parameter):
    source = _source(f"records.forEach(({parameter}) => {{ assert.strictEqual(value, 5); }});")
    assert _assertions(source) == []
    assert [gap.callee for gap in _gaps(source)] == ["assert.strictEqual"]


@pytest.mark.parametrize("parameter", ["{ assert: local }", "{ local = assert }", "[ local = assert ]"])
def test_property_keys_and_default_value_identifiers_are_not_parameter_bindings(parameter):
    source = _source(f"records.forEach(({parameter}) => {{ assert.strictEqual(value, 5); }});")
    assert [assertion.left for assertion in _assertions(source)] == ["value"]
    assert _gaps(source) == []


def test_catch_does_not_create_a_function_boundary_for_var():
    source = _source("try { operation(); } catch (error) { var assert = standin; } assert.strictEqual(value, 5);")
    assert _assertions(source) == []
    assert [gap.callee for gap in _gaps(source)] == ["assert.strictEqual"]


@pytest.mark.parametrize("binding", ["const test = customRunner;", "test = customRunner;"])
def test_shadowed_runner_cannot_assign_test_context_authority(binding):
    source = (binding + '\ntest("sample", (ctx) => { ctx.assert.strictEqual(value, 5); });').encode()
    assert _assertions(source) == []


@pytest.mark.parametrize("source", [
    'test("sample", () =>',
    'const incomplete = () =>',
    'test("sample", () => { const incomplete = () =>',
])
def test_incomplete_arrow_does_not_crash_the_static_scan(source):
    data = source.encode()
    parsed = parse_javascript(data)
    assert isinstance(parsed.units, list)
    assert javascript_coverage_gaps(data, parsed, "test/example.js", "after") == []


@pytest.mark.parametrize("imports,body", [
    ("", "values.forEach(t => t.toString());"),
    ("", "const t = new Date(); t.toISOString();"),
    ('import * as vi from "vitest";', "values.forEach(vi => vi.fn());"),
    ('import * as vi from "vitest";', "const helper = vi; values.forEach(helper => helper.fn());"),
    ("", "{ const verify = require('node:assert'); } verify.strictEqual(value, 5);"),
])
def test_candidate_provenance_does_not_leak_to_unrelated_calls(imports, body):
    source = _source(body, imports)
    assert _assertions(source) == []
    assert _gaps(source) == []


@pytest.mark.parametrize("body,callee", [
    ("values.forEach(t => t.assert.strictEqual(value, 5));", "t.assert.strictEqual"),
    ("values.forEach(t => t['assert'].strictEqual(value, 5));", "t['assert'].strictEqual"),
])
def test_shadowed_context_assertion_family_remains_a_candidate(body, callee):
    source = _source(body, "")
    assert _assertions(source) == []
    assert [gap.callee for gap in _gaps(source)] == [callee]

"""Plain suite relocation needs closed producers and framework provenance.

The JavaScript strings are static analyzer inputs, never executed programs.
"""
import datetime

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze
from checkwash.frontends.javascript.frontend import parse_javascript
from checkwash.oracle_describe_credit import closed_describe_environment


IMPORT = 'import {describe, expect, it} from "vitest";\n'
PRODUCER = 'function total() { return 5; }\n'
UNIT = 'it("computes", () => { expect(total()).toBe(5); });'


def wrapped(unit=UNIT):
    return 'describe("moved", () => {\n  ' + unit + '\n});\n'


def proof(source):
    parsed = parse_javascript(source.encode())
    return closed_describe_environment(source.encode(), [(unit.qualname, unit.side) for unit in parsed.units],
        path="tests/a.test.js", read=lambda path: source.encode() if path == "tests/a.test.js" else None,
        path_lister=lambda: ["tests/a.test.js"])


def move(before, after, *, freeze=False, extra=None, paths=True):
    snapshot = {"tests/b.test.js": after.encode(), **(extra or {})}
    return analyze([
        FileChange("tests/a.test.js", "deleted", before.encode(), None),
        FileChange("tests/b.test.js", "added", None, after.encode()),
    ], Config(), Contract(oracle_freeze=freeze), [], datetime.date(2026, 10, 27),
        root_reader=snapshot.get, root_searcher=lambda _needles: [],
        root_path_lister=(lambda: sorted(snapshot)) if paths else None,
        root_batch_reader=(lambda selected: {path: snapshot.get(path) for path in selected}) if paths else None)


@pytest.mark.parametrize("module", ["vitest", "@jest/globals"])
@pytest.mark.parametrize("unit_word", ["it", "test"])
@pytest.mark.parametrize("freeze", [False, True])
def test_complete_closed_unit_can_enter_and_leave_one_plain_suite(module, unit_word, freeze):
    header = IMPORT.replace("vitest", module).replace("it}", unit_word + "}") + PRODUCER
    unit = UNIT.replace("it(", unit_word + "(")
    before, after = header + unit + "\n", header + wrapped(unit)
    assert proof(before) == proof(after) and proof(before) is not None
    for old, new in ((before, after), (after, before)):
        _ir, findings, verdict = move(old, new, freeze=freeze)
        assert verdict == "pass"
        assert [(finding.rule, finding.severity) for finding in findings] == [("TEST_DISABLED", "info")]
        assert "ASSERTION_MOVED" in findings[0].deescalators


@pytest.mark.parametrize("literal", ["5", "-5", "5.25", "true", "false", "null", '"value"', "'value'"])
def test_literal_only_oracles_and_closed_primitive_producers_have_proof(literal):
    unit = UNIT.replace("total()", literal).replace("toBe(5)", "toBe(" + literal + ")")
    assert proof(IMPORT + unit) == proof(IMPORT + wrapped(unit))
    assert proof(IMPORT + unit) is not None


@pytest.mark.parametrize("body", [
    'const s = expect["get" + "State"](); if (s["current" + "TestName"].startsWith("moved")) return; ',
    'if (getTestName().startsWith("moved")) return; ',
    'getTestName(); ',
    'unknownObserver(); ',
    'const name = "moved"; ',
    'this.skip(); ',
    'expect(total()).toBe(5); installPatch(); ',
])
def test_all_unknown_observation_or_execution_is_outside_the_closed_grammar(body):
    unit = UNIT.replace("expect(total()).toBe(5);", body + "expect(total()).toBe(5);")
    before, after = IMPORT + PRODUCER + unit, IMPORT + PRODUCER + wrapped(unit)
    assert proof(before) is None and proof(after) is None
    _ir, findings, verdict = move(before, after)
    assert verdict == "block"
    assert any(finding.rule == "TEST_DISABLED" and finding.severity == "high" for finding in findings)


@pytest.mark.parametrize("after", [
    IMPORT + wrapped(),  # total has no closed definition.
    PRODUCER + wrapped(),  # global framework names are not positive authority.
    IMPORT.replace('"vitest"', '"./custom-runner"') + PRODUCER + wrapped(),
    IMPORT.replace("describe,", "describe as group,") + PRODUCER + wrapped(),
    IMPORT + PRODUCER + wrapped().replace("describe(", "describe.skip("),
    IMPORT + PRODUCER + wrapped().replace("describe(", "describe.only("),
    IMPORT + PRODUCER + wrapped().replace('"moved",', '"moved", {skip: false},'),
    IMPORT + PRODUCER + wrapped().replace("() =>", "function()", 1),
    IMPORT + PRODUCER + wrapped().replace("() =>", "(context) =>", 1),
    IMPORT + PRODUCER + wrapped().replace("  it(", "  beforeEach(patch); it("),
    IMPORT + PRODUCER + wrapped().replace("  it(", "  const x = 1; it("),
    IMPORT + PRODUCER + wrapped().replace("total()", "total(1)"),
    IMPORT + PRODUCER + wrapped().replace("toBe(5)", "toBe(total())"),
    IMPORT + PRODUCER + wrapped().replace("() => { expect", "function() { expect"),
    IMPORT + PRODUCER + wrapped() + "total = replacement;\n",
    IMPORT + PRODUCER + wrapped() + 'it("another", () => { expect(total()).toBe(5); });',
    IMPORT + PRODUCER + 'describe("outer", () => { ' + wrapped() + ' });',
])
def test_unsupported_binding_framework_callback_and_suite_forms_keep_cost(after):
    before = IMPORT + PRODUCER + UNIT
    assert proof(after) is None
    _ir, findings, verdict = move(before, after)
    assert verdict == "block"
    assert any(finding.severity == "high" for finding in findings)


@pytest.mark.parametrize("producer", [
    "function total() { return unknown(); }\n",
    "function total() { return this.value; }\n",
    "function total() { return expect.getState(); }\n",
    "function total() { installPatch(); return 5; }\n",
    "function total(value) { return 5; }\n",
    "function total() { return\n5; }\n",
    "function total() { return /*\n*/ 5; }\n",
    "function total() { return\u2028 5; }\n",
    "function total() { return 5; }\nfunction total() { return 0; }\n",
    "function describe() { return 5; }\n",
    "function eval() { return 5; }\n",
    "function arguments() { return 5; }\n",
])
def test_unclosed_or_rebound_producers_cannot_hide_suite_context(producer):
    assert proof(IMPORT + producer + wrapped()) is None


def test_two_different_closed_pure_producers_do_not_have_the_same_identity():
    before = IMPORT + PRODUCER + UNIT
    after = IMPORT + PRODUCER.replace("return 5", "return 0") + wrapped()
    assert proof(before) is not None and proof(after) is not None
    assert proof(before) != proof(after)
    _ir, findings, verdict = move(before, after)
    assert verdict == "block"
    assert any(finding.rule == "TEST_DISABLED" and finding.severity == "high" for finding in findings)


def test_ordinary_source_cannot_spoof_the_closed_environment_data():
    before = IMPORT + PRODUCER + UNIT
    certificate = proof(before)
    assert certificate is not None
    after = certificate + "\n" + UNIT
    assert proof(after) is None
    _ir, findings, verdict = move(before, after)
    assert verdict == "block"
    assert any(finding.rule == "TEST_DISABLED" and finding.severity == "high" for finding in findings)


def test_unicode_line_comment_termination_does_not_hide_unknown_code():
    after = IMPORT + PRODUCER + "// comment\u2028unknownObserver();\n" + wrapped()
    assert proof(after) is None


def test_original_missing_producer_control_remains_unresolved():
    # #570's original input has neither a closed total implementation nor
    # framework import authority. Its existing expected label is untouched.
    _ir, findings, verdict = move(UNIT, wrapped())
    assert verdict == "block"
    assert [(finding.rule, finding.severity) for finding in findings] == [("TEST_DISABLED", "high")]


def test_bare_framework_package_resolution_remains_bound_to_the_directory():
    before, after = IMPORT + PRODUCER + UNIT, IMPORT + PRODUCER + wrapped()
    _ir, findings, verdict = analyze([
        FileChange("left/a.test.js", "deleted", before.encode(), None),
        FileChange("right/b.test.js", "added", None, after.encode()),
    ], Config(), Contract(), [], datetime.date(2026, 10, 27),
        root_reader=lambda _path: None, root_searcher=lambda _needles: [])
    assert verdict == "block"
    assert [(finding.rule, finding.severity) for finding in findings] == [("TEST_DISABLED", "high")]


@pytest.mark.parametrize("gap", ["\n", "\r", "\r\n", "\u2028", "\u2029", "/*\n*/"])
@pytest.mark.parametrize("location", ["suite", "unit"])
def test_line_terminator_before_any_arrow_withholds_optional_proof(gap, location):
    unit = UNIT.replace("() =>", "()" + gap + "=>") if location == "unit" else UNIT
    after = IMPORT + PRODUCER + wrapped(unit)
    if location == "suite":
        after = after.replace("() =>", "()" + gap + "=>", 1)
    assert proof(after) is None


@pytest.mark.parametrize("comment", [
    "/** @vitest-environment ./evil-env */\n", "/** @jest-environment ./evil-env */\n",
    "// unknown-source-directive\n", "/* ordinary comment */\n",
])
def test_unknown_comment_metadata_never_installs_hidden_bootstrap_authority(comment):
    before, after = comment + IMPORT + PRODUCER + UNIT, comment + IMPORT + PRODUCER + wrapped()
    assert proof(before) is None and proof(after) is None
    _ir, findings, verdict = move(before, after)
    assert verdict == "block"
    assert any(finding.severity == "high" for finding in findings)


@pytest.mark.parametrize("path,source", [
    ("vitest.config.js", b'export default {setupFiles: ["./setup.js"]};'),
    ("jest.config.js", b"module.exports = {}"),
    ("package.json", b'{"vitest": {"setupFiles": ["./setup.js"]}}'),
    ("tests/sibling.test.js", b"beforeEach(unknownObserver);"),
    ("setup.js", b"beforeEach(unknownObserver);"),
    ("node_modules/vitest/index.js", b"export const expect = replacement;"),
    ("unknown-bootstrap-config", b""),
])
def test_any_additional_repository_file_withholds_the_one_file_startup_proof(path, source):
    _ir, findings, verdict = move(IMPORT + PRODUCER + UNIT, IMPORT + PRODUCER + wrapped(),
        extra={path: source})
    assert verdict == "block"
    assert any(finding.rule == "TEST_DISABLED" and finding.severity == "high" for finding in findings)


def test_missing_complete_path_authority_is_unknown_instead_of_empty_startup():
    _ir, findings, verdict = move(IMPORT + PRODUCER + UNIT, IMPORT + PRODUCER + wrapped(), paths=False)
    assert verdict == "block"
    assert any(finding.rule == "TEST_DISABLED" and finding.severity == "high" for finding in findings)


@pytest.mark.parametrize("files,observed", [
    ([], None), (["tests/a.test.js", "tests/a.test.js"], None),
    (["tests/a.test.js"], b""), (["tests/a.test.js"], "not bytes"),
    (["tests/a.test.js"], None), (iter(["tests/a.test.js"]), None),
])
def test_incomplete_inconsistent_or_untyped_snapshot_cannot_supply_a_certificate(files, observed):
    source = (IMPORT + PRODUCER + UNIT).encode()
    units = [(unit.qualname, unit.side) for unit in parse_javascript(source).units]
    assert closed_describe_environment(source, units, path="tests/a.test.js",
        read=lambda _path: observed, path_lister=lambda: files) is None


@pytest.mark.parametrize("capability", ["read", "paths"])
def test_snapshot_capability_failure_is_unknown(capability):
    source = (IMPORT + PRODUCER + UNIT).encode()
    units = [(unit.qualname, unit.side) for unit in parse_javascript(source).units]
    def unavailable(*_args):
        raise OSError("owned snapshot failure")
    assert closed_describe_environment(source, units, path="tests/a.test.js",
        read=unavailable if capability == "read" else lambda _path: source,
        path_lister=unavailable if capability == "paths" else lambda: ["tests/a.test.js"]) is None


def test_closed_source_proof_budget_does_not_expand_to_large_or_multi_unit_programs():
    assert proof(IMPORT + PRODUCER + UNIT + " " * 65536) is None
    producers = "".join(f"function producer{i}() {{ return 5; }}\n" for i in range(65))
    assert proof(IMPORT + producers + UNIT.replace("total()", "producer0()")) is None
    unit = UNIT.replace("expect(total()).toBe(5);", "expect(total()).toBe(5);" * 512)
    assert proof(IMPORT + PRODUCER + unit) is None


@pytest.mark.parametrize("count", [128, 129])
@pytest.mark.parametrize("freeze", [False, True])
def test_statement_budget_has_an_independent_128_boundary(count, freeze):
    unit = UNIT.replace("expect(total()).toBe(5);", "expect(total()).toBe(5);" * count)
    before, after = IMPORT + PRODUCER + unit, IMPORT + PRODUCER + wrapped(unit)
    assert (proof(before) is not None) == (count == 128)
    assert (proof(after) is not None) == (count == 128)
    ir, findings, verdict = move(before, after, freeze=freeze)
    assert len(ir.files[0].units[0].before.assertions) == count
    assert verdict == ("pass" if count == 128 else "block")
    assert [(finding.rule, finding.severity) for finding in findings] == [
        ("TEST_DISABLED", "info" if count == 128 else "high")]
    assert ("ASSERTION_MOVED" in findings[0].deescalators) == (count == 128)
    assert ("ORACLE_FREEZE" in findings[0].escalators) == (count == 129 and freeze)

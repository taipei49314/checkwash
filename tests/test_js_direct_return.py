"""Owned direct-return labels proposed for remote qualification; NOT RUN locally."""

import datetime
import json
from pathlib import Path
import statistics
import time

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze
from checkwash.frontends.javascript.coverage import javascript_coverage_gaps
from checkwash.frontends.javascript.frontend import parse_javascript
from checkwash.frontends.python.frontend import ParsedFile, parse_python
from checkwash.report.context import ReportContext
from checkwash.report.jsonout import findings_to_json, ir_to_json


HEADER = 'import { it, expect } from "vitest";\nimport assert from "node:assert";\n'
ORACLE = "expect(value()).toBe(1);"
PATH = "tests/value.test.ts"


def source(body):
    return (HEADER + 'it("value", () => {\n' + body + "\n});\n").encode()


def assertions(body):
    unit, = parse_javascript(source(body)).units
    return [assertion.text for assertion in unit.side.assertions]


def outcome(before, after):
    return analyze([FileChange(PATH, "modified", before, after)],
                   Config(), Contract(), [], datetime.date(2026, 10, 12))


@pytest.mark.parametrize("case_id,verdict,expected_count", [
    ("JS-EARLY-RETURN", "block", 0),
    ("JS-RETURN-AFTER-ORACLE", "pass", 1),
])
def test_native_verified_owned_pair_uses_unchanged_source(case_id, verdict, expected_count):
    catalog = json.loads((Path(__file__).resolve().parents[1] / "tools/js_obligation_pairs.json")
                         .read_text(encoding="utf-8"))
    case, = [case for case in catalog["cases"] if case["id"] == case_id]
    pair = case["files"]["value.test.ts"]
    before, after = pair["before"].encode(), pair["after"].encode()
    parsed = parse_javascript(after)
    assert len(parsed.units[0].side.assertions) == expected_count
    _ir, findings, actual = outcome(before, after)
    assert actual == verdict
    if expected_count:
        assert findings == []
    else:
        finding, = findings
        assert (finding.rule, finding.severity) == ("ASSERT_REMOVED", "high")
        assert finding.before.text == ORACLE[:-1]
        assert finding.after is None


@pytest.mark.parametrize("prefix", [
    "return;", "setup(); return;", "const value = setup(); return;",
    "let value = setup();\nreturn;", "setup()\nreturn\n", "return /*\ncomment */ ",
    "return // comment\n", ";; return;",
])
def test_direct_statement_return_removes_unreachable_original_oracle(prefix):
    after = source(prefix + ORACLE)
    assert assertions(prefix + ORACLE) == []
    _ir, findings, verdict = outcome(source(ORACLE), after)
    assert verdict == "block"
    assert [(finding.rule, finding.severity) for finding in findings] == [("ASSERT_REMOVED", "high")]
    assert findings[0].before.text == ORACLE[:-1]


@pytest.mark.parametrize("body", [
    ORACLE + " return;",
    "return " + ORACLE,
    "return /* same-line comment */ " + ORACLE,
    "return (\n" + ORACLE[:-1] + "\n);",
])
def test_return_after_or_including_the_oracle_keeps_its_obligation(body):
    assert assertions(body) == [ORACLE[:-1]]
    _ir, findings, verdict = outcome(source(ORACLE), source(body))
    assert verdict == "pass"
    assert findings == []


@pytest.mark.parametrize("expression", [
    "/x/\n.test(expect(value()).toBe(1))",
    "`x\ny`.includes(expect(value()).toBe(1))",
    "/* real comment */ /a*/\n.test(expect(value()).toBe(1))",
    " " * 20_000 + "/x/\n.test(expect(value()).toBe(1))",
])
def test_omitted_literal_operand_newline_does_not_invent_return_asi(expression):
    data = source("return " + expression + ";")
    parsed = parse_javascript(data)
    assert [a.text for a in parsed.units[0].side.assertions] == [ORACLE[:-1]]
    assert parsed.unreachable_assertion_spans == ()
    assert parsed.unreachable_unjudged_assertion_spans == ()
    _ir, findings, verdict = outcome(source(ORACLE), data)
    assert verdict == "pass"
    assert findings == []


def test_real_return_line_break_remains_distinct_from_opaque_operand_line_break():
    assert assertions("return /* comment */\n" + ORACLE) == []


@pytest.mark.parametrize("line_end", ["\n", "\r\n", "\r"])
def test_normalized_line_end_after_return_ends_the_return(line_end):
    data = (HEADER + 'it("value", () => { return' + line_end + ORACLE + " });").encode()
    parsed = parse_javascript(data)
    assert parsed.units[0].side.assertions == []
    assert len(parsed.unreachable_assertion_spans) == 1


@pytest.mark.parametrize("separator", ["\u2028", "\u2029"])
def test_unicode_line_terminators_remain_outside_initial_cutoff_proof(separator):
    parsed = parse_javascript(source("return" + separator + ORACLE))
    assert [a.text for a in parsed.units[0].side.assertions] == [ORACLE[:-1]]
    assert parsed.unreachable_assertion_spans == ()


@pytest.mark.parametrize("prefix", [
    "rows.forEach(() => { return; });",
    "const helper = () => { return; };",
    "function helper() { return; }",
    "const helper = function () { return; };",
    'const text = "return;";',
    "const text = `return;`;",
    "const pattern = /return;/;",
    "/* return; */",
    "// return;\n",
])
def test_nested_return_or_literal_text_does_not_end_parent(prefix):
    assert assertions(prefix + ORACLE) == [ORACLE[:-1]]


def test_nested_callback_before_a_real_parent_return_does_not_hide_the_cutoff():
    assert assertions("rows.forEach(() => { return; }); return; " + ORACLE) == []


def test_parent_return_cuts_inline_callback_inventory_but_keeps_raw_catch_evidence():
    data = source("return; rows.forEach(() => { try { " + ORACLE + " } catch {} });")
    parsed = parse_javascript(data)
    assert parsed.units[0].side.assertions == []
    assert parsed.swallowing_handlers == ("catch assertion",)
    assert len(parsed.unreachable_assertion_spans) == 1
    assert javascript_coverage_gaps(data, parsed, PATH, "after") == []


@pytest.mark.parametrize("prefix", [
    "if (flag) return;", "if (true) { return; }", "for (;;) { break; } return;",
    "while (flag) { return; }", "label: return;",
    "try { return; } finally { cleanup(); }",
    "switch (flag) { default: return; }", "{ setup(); } return;",
    "class Helper { static { setup(); } } return;",
    "function helper() {} return;", "const { value } = setup(); return;",
])
def test_unsupported_preceding_compound_or_declaration_preserves_old_inventory(prefix):
    parsed = parse_javascript(source(prefix + ORACLE))
    assert [a.text for a in parsed.units[0].side.assertions] == [ORACLE[:-1]]
    assert parsed.unreachable_assertion_spans == ()


@pytest.mark.parametrize("malformed", ["expect(value).toBe(1;", "expect(value).toBe([1});"])
def test_recovered_malformed_body_never_supplies_new_cutoff(malformed):
    parsed = parse_javascript(source("return; " + malformed + ORACLE))
    assert [a.text for a in parsed.units[0].side.assertions] == [ORACLE[:-1]]
    assert parsed.unreachable_assertion_spans == ()
    assert parsed.unreachable_unjudged_assertion_spans == ()


@pytest.mark.parametrize("prefix", ["const value = ; return;", "return +;"])
def test_incomplete_statement_operand_never_supplies_cutoff(prefix):
    assert assertions(prefix + ORACLE) == [ORACLE[:-1]]


def test_a_different_live_oracle_cannot_hide_the_dead_original_subject():
    before = source("expect(other()).toBe(2); " + ORACLE)
    after = source("expect(other()).toBe(2); return; " + ORACLE)
    parsed = parse_javascript(after)
    assert [a.text for a in parsed.units[0].side.assertions] == ["expect(other()).toBe(2)"]
    _ir, findings, verdict = outcome(before, after)
    assert verdict == "block"
    finding, = findings
    assert finding.rule == "ASSERT_REMOVED"
    assert finding.before.text == ORACLE[:-1]


@pytest.mark.parametrize("oracle", [
    "expect(value()).toBe(1);", "assert.strictEqual(value(), 1);",
    "expect(spy).toHaveBeenCalled();", "assert.match(message, /invalid/);",
])
def test_cutoff_applies_to_resolved_strong_and_unjudged_assertion_forms(oracle):
    assert assertions("return; " + oracle) == []


def test_precise_dead_known_and_unjudged_spans_do_not_hide_other_coverage_gaps():
    body = "return; " + ORACLE + " expect(spy).toHaveBeenCalled(); assert.okay(value);"
    data = source(body)
    parsed = parse_javascript(data)
    assert parsed.units[0].side.assertions == []
    assert len(parsed.unreachable_assertion_spans) == 1
    assert len(parsed.unreachable_unjudged_assertion_spans) == 1
    text = data.decode()
    strong, = parsed.unreachable_assertion_spans
    unjudged, = parsed.unreachable_unjudged_assertion_spans
    assert text[slice(*strong)] == ORACLE[:-1]
    assert text[slice(*unjudged)] == "expect(spy).toHaveBeenCalled()"
    gaps = javascript_coverage_gaps(data, parsed, PATH, "after")
    assert len(gaps) == 2
    assert "recorded with no strength" in gaps[0].reason
    assert gaps[1].callee == "assert.okay"
    assert "recorded with no strength" not in gaps[1].reason


def test_unjudged_return_expression_stays_live_and_keeps_original_notice():
    data = source("return expect(spy).toHaveBeenCalled();")
    parsed = parse_javascript(data)
    assert len(parsed.units[0].side.assertions) == 1
    assert parsed.unreachable_assertion_spans == ()
    assert parsed.unreachable_unjudged_assertion_spans == ()
    gap, = javascript_coverage_gaps(data, parsed, PATH, "after")
    assert "recorded with no strength" in gap.reason


def test_expression_arrow_has_no_block_cutoff_and_shadowed_test_stays_unknown():
    parsed = parse_javascript((HEADER + 'it("value", () => expect(value()).toBe(1));').encode())
    assert len(parsed.units[0].side.assertions) == 1
    assert parsed.unreachable_assertion_spans == ()
    assert parsed.unreachable_unjudged_assertion_spans == ()
    unknown = source("const it = custom; it('inner', () => { return; " + ORACLE + " });")
    shadowed = parse_javascript(unknown)
    assert [unit.qualname for unit in shadowed.units] == ["value", "inner"]
    assert [unit.side.assertions for unit in shadowed.units] == [[], []]
    oracle_start = unknown.index(ORACLE[:-1].encode())
    assert shadowed.unreachable_assertion_spans == ((oracle_start, oracle_start + len(ORACLE) - 1),)
    assert shadowed.unreachable_unjudged_assertion_spans == ()
    assert javascript_coverage_gaps(unknown, shadowed, PATH, "after") == []


def test_internal_coverage_metadata_defaults_empty_and_does_not_enter_public_reports():
    assert ParsedFile(parse_ok=False).unreachable_assertion_spans == ()
    assert ParsedFile(parse_ok=False).unreachable_unjudged_assertion_spans == ()
    python = parse_python(b"def test_value():\n    assert value() == 1\n", collect_tests=True)
    assert python.unreachable_assertion_spans == ()
    assert python.unreachable_unjudged_assertion_spans == ()
    ir, findings, verdict = outcome(source(ORACLE), source("return; " + ORACLE))
    for rendered in (ir_to_json(ir), findings_to_json(ir, findings, verdict)):
        assert "unreachable_assertion_spans" not in rendered
        assert "unreachable_unjudged_assertion_spans" not in rendered


def test_dead_span_coverage_uses_normalized_bom_crlf_offsets():
    data = b'\xef\xbb\xbf' + source("return;\n" + ORACLE + "\nexpect(spy).toHaveBeenCalled();").replace(b"\n", b"\r\n")
    normalized = data.decode("utf-8-sig").replace("\r\n", "\n")
    parsed = parse_javascript(data)
    strong, = parsed.unreachable_assertion_spans
    unjudged, = parsed.unreachable_unjudged_assertion_spans
    assert normalized[slice(*strong)] == ORACLE[:-1]
    assert normalized[slice(*unjudged)] == "expect(spy).toHaveBeenCalled()"
    gap, = javascript_coverage_gaps(data, parsed, PATH, "after")
    assert (gap.path, gap.side, gap.line, gap.column) == (PATH, "after", 6, 1)
    assert "recorded with no strength" in gap.reason


def test_coverage_context_preserves_direct_return_ir_findings_and_verdict():
    before = source(ORACLE + " expect(spy).toHaveBeenCalled();")
    after = source("return; " + ORACLE + " expect(spy).toHaveBeenCalled();")
    plain_ir, plain_findings, plain_verdict = outcome(before, after)
    context = ReportContext(collect_locations=False)
    ir, findings, verdict = analyze(
        [FileChange(PATH, "modified", before, after)], Config(), Contract(), [],
        datetime.date(2026, 10, 12), report_context=context,
    )
    assert verdict == plain_verdict == "block"
    assert [(gap.side, gap.callee) for gap in context.coverage_gaps] == [
        ("before", "expect(...).toHaveBeenCalled"), ("after", "expect(...).toHaveBeenCalled"),
    ]
    assert all("recorded with no strength" in gap.reason for gap in context.coverage_gaps)
    assert ir_to_json(ir) == ir_to_json(plain_ir)
    assert findings_to_json(ir, findings, verdict) == findings_to_json(plain_ir, plain_findings, plain_verdict)


def test_many_small_callbacks_keep_inventory_and_bounded_scaling():
    def workload(count):
        rows = [HEADER]
        for index in range(count):
            rows.append(f'it("unit {index}", () => {{ expect(live()).toBe(1); '
                        'return; expect(dead()).toBe(2); });\n')
        return "".join(rows).encode()

    def median(count):
        timings = []
        data = workload(count)
        for _repeat in range(3):
            started = time.perf_counter()
            parsed = parse_javascript(data)
            timings.append(time.perf_counter() - started)
            assert len(parsed.units) == count
            assert all([a.left for a in unit.side.assertions] == ["live()"] for unit in parsed.units)
            assert len(parsed.unreachable_assertion_spans) == count
        return statistics.median(timings)

    small, large = median(80), median(320)
    # A new repeated whole-file reader per callback would restore quadratic
    # work. This is a proposed remote ratio control, not a throughput claim.
    assert large < max(small, 0.001) * 10, (small, large)

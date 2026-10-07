"""An iterator callback keeps its lexical assertion coverage whatever the call's receiver (#294).

`docs/assertion-coverage.md`: "Direct inline callback arguments to other
calls retain the existing lexical coverage, including iterator callbacks."
The frontend applied that only to a callee spelled as a dotted name:
`cases.forEach(cb)` was read and `[[1, 78.75]].forEach(cb)` was not, so the
table-driven spelling's assertion could be weakened or deleted with zero
findings. These pin the rule for every receiver, and what it still leaves
out.
"""

from __future__ import annotations

import datetime

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze
from checkwash.frontends.javascript.frontend import parse_javascript
from checkwash.report.context import ReportContext

HEAD = 'import { it, expect } from "vitest";\nimport { total } from "../src/total";\n\n'
ASSERTION = "expect(total(n)).toBe(want);"
WEAKENED = "expect(total(n)).toBeDefined();"


def _source(loop: str, line: str) -> str:
    return HEAD + 'it("totals", () => {\n  ' + loop.format(line) + "\n});\n"


def _outcome(loop: str, before: str, after: str):
    change = FileChange("tests/total.test.ts", "modified", _source(loop, before).encode(), _source(loop, after).encode())
    context = ReportContext()
    _ir, findings, verdict = analyze([change], Config(), Contract(), [], datetime.date(2026, 1, 1),
                                     report_context=context)
    return verdict, [(f.rule, f.severity) for f in findings], len(context.coverage_gaps)


RECEIVERS = [
    "cases.forEach(([n, want]) => {{ {} }});",
    "cases.map(([n, want]) => {{ {} }});",
    "[[1, 78.75]].forEach(([n, want]) => {{ {} }});",
    "[[1, 78.75]].map(([n, want]) => {{ {} }});",
    "Object.entries(cases).forEach(([n, want]) => {{ {} }});",
    "(cases).forEach(([n, want]) => {{ {} }});",
    "cases[0].forEach(([n, want]) => {{ {} }});",
    "cases.filter(Boolean).forEach(([n, want]) => {{ {} }});",
    "cases?.forEach(([n, want]) => {{ {} }});",
    "[[1, 78.75]]?.forEach(([n, want]) => {{ {} }});",
    "[[1, 78.75]] .forEach(function ([n, want]) {{ {} }});",
    "[[1, 78.75]]\n    .forEach(([n, want]) => {{ {} }});",
]


@pytest.mark.parametrize("loop", RECEIVERS)
def test_a_weakened_assertion_in_an_iterator_callback_is_read(loop):
    assert _outcome(loop, ASSERTION, WEAKENED) == ("block", [("ASSERT_WEAKENED", "high")], 0)


@pytest.mark.parametrize("loop", RECEIVERS)
def test_a_deleted_assertion_in_an_iterator_callback_is_read(loop):
    assert _outcome(loop, ASSERTION, "") == ("block", [("ASSERT_REMOVED", "high")], 0)


@pytest.mark.parametrize("loop", RECEIVERS)
def test_an_unchanged_iterator_callback_is_no_finding(loop):
    assert _outcome(loop, ASSERTION, ASSERTION) == ("pass", [], 0)


def test_the_assertion_is_the_units_own():
    parsed = parse_javascript(_source("[[1, 78.75]].forEach(([n, want]) => {{ {} }});", ASSERTION).encode())
    assert [[a.text for a in unit.side.assertions] for unit in parsed.units] == [["expect(total(n)).toBe(want)"]]


@pytest.mark.parametrize("loop", [
    # A callback passed by name is a declared helper: still a coverage gap.
    "const check = ([n, want]) => {{ {} }};\n  [[1, 78.75]].forEach(check);",
    # A callback inside a nested function stays that function's.
    "const run = () => {{ [[1, 78.75]].forEach(([n, want]) => {{ {} }}); }};\n  run();",
    # A call result called directly, and an optional call, are not member calls.
    "each(cases)(([n, want]) => {{ {} }});",
    "each?.(([n, want]) => {{ {} }});",
])
def test_what_the_rule_still_leaves_out(loop):
    verdict, findings, gaps = _outcome(loop, ASSERTION, WEAKENED)
    assert (verdict, findings) == ("pass", [])
    assert gaps == 2


def test_a_test_declared_in_an_iterator_callback_keeps_its_own_assertions():
    """`[1, 2].forEach((n) => { it(...) })` declares tests; their callbacks stay test bodies."""
    source = (
        HEAD
        + "[1, 2].forEach((n) => {\n"
        + "  it(`total ${n}`, () => {\n    expect(total(n)).toBe(n);\n  });\n"
        + "});\n"
    )
    parsed = parse_javascript(source.encode())
    assert [[a.text for a in unit.side.assertions] for unit in parsed.units] == [["expect(total(n)).toBe(n)"]]


@pytest.mark.parametrize("statement", [
    # A spread's parenthesis follows `.`, but no name: it opens no call.
    "run(...((x) => { expect(x).toBe(1); }));",
    # A statement keyword's parenthesis opens no call either.
    "if (() => { expect(1).toBe(1); }) { run(); }",
], ids=["spread", "keyword"])
def test_a_parenthesis_that_opens_no_call_passes_no_callback(statement):
    source = HEAD + 'it("a", () => {\n  ' + statement + "\n  expect(2).toBe(2);\n});\n"
    parsed = parse_javascript(source.encode())
    assert [[a.text for a in unit.side.assertions] for unit in parsed.units] == [["expect(2).toBe(2)"]]

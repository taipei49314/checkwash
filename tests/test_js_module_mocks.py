"""JS module mocks and replacing spies as TEST_PATCHES_SUBJECT events (issue #177).

The .gwcase fixtures carry the end-to-end shapes. These pin what a fixture
cannot isolate: which specifiers count as first-party, that a CRLF checkout
reports the same evidence, and the two timing bounds the design rests on.
"""

from __future__ import annotations

import datetime

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze
from checkwash.frontends.javascript.module_mocks import module_key
from checkwash.gitio.snapshot import search_source_mapping

PATH = "tests/billing.test.js"
VITEST = 'import { describe, it, expect } from "vitest";\n'
BEFORE = (
    VITEST
    + 'import { invoiceTotal } from "../src/billing.js";\n'
    + "\n"
    + 'describe("billing", () => {\n'
    + '  it("computes invoice total", () => {\n'
    + "    const items = [{ price: 10.0, qty: 3 }, { price: 5.0, qty: 9 }];\n"
    + "    expect(invoiceTotal(items)).toBe(78.75);\n"
    + "  });\n"
    + "});\n"
)
WITH_VI = VITEST.replace("expect }", "expect, vi }")
STAND_IN = 'vi.mock("../src/billing.js", () => ({\n  invoiceTotal: () => 78.75,\n}));\n'


def _analyze(before: str, after: str):
    snapshot = {PATH: after.encode("utf-8")}
    change = FileChange(PATH, "modified", before.encode("utf-8"), after.encode("utf-8"))
    ir, findings, _verdict = analyze(
        [change], Config(), Contract(), [], datetime.date(2026, 1, 1),
        root_reader=snapshot.get,
        root_searcher=lambda needles: search_source_mapping(snapshot, needles),
    )
    return ir.globals.subject_installations, [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]


@pytest.mark.parametrize(("test_path", "specifier", "expected"), [
    ("billing.test.js", "./src/billing.js", "src/billing"),
    ("tests/billing.test.js", "../src/billing", "src/billing"),
    ("tests/billing.test.ts", "../src/billing.ts", "src/billing"),
    ("tests/billing.test.ts", "../src/index.ts", "src"),
    ("tests\\billing.test.js", "../src/billing.mjs", "src/billing"),
    ("tests/billing.test.js", "axios", None),
    ("tests/billing.test.js", "node:fs", None),
    ("tests/billing.test.js", "@/billing", None),
    ("tests/billing.test.js", "/src/billing.js", None),
    ("tests/billing.test.js", "../../outside.js", None),
    ("tests/billing.test.js", "../node_modules/pkg/index.js", None),
    ("tests/billing.test.js", "../src/billing.js?raw", None),
])
def test_only_relative_repository_specifiers_are_first_party(test_path, specifier, expected):
    assert module_key(test_path, specifier) == expected


def test_a_crlf_checkout_reports_the_same_installation():
    after = BEFORE.replace(VITEST, WITH_VI + STAND_IN)
    events, findings = _analyze(BEFORE, after)
    crlf_events, crlf_findings = _analyze(BEFORE.replace("\n", "\r\n"), after.replace("\n", "\r\n"))
    assert [(path, unit, target) for path, unit, target, _text, _span in events] == [
        (PATH, "computes invoice total", "src/billing:invoiceTotal")
    ]
    assert crlf_events == events
    assert [(f.severity, f.escalators) for f in findings] == [("high", ["NO_PROD_CHANGE_IN_DIFF"])]
    assert [(f.severity, f.escalators) for f in crlf_findings] == [("high", ["NO_PROD_CHANGE_IN_DIFF"])]


def test_an_ordered_mock_never_reaches_a_static_import():
    """`vi.doMock` runs where it is written; the import above it was bound first."""
    ordered = STAND_IN.replace("vi.mock", "vi.doMock")
    after = BEFORE.replace(VITEST, WITH_VI).replace("describe(", ordered + "\ndescribe(", 1)
    assert _analyze(BEFORE, after) == ([], [])


def test_jest_mock_inside_a_describe_body_cannot_reach_a_captured_import():
    """Inside `describe`, the block that `jest.mock` hoists within runs after
    the file's imports were already bound."""
    inside = "  " + STAND_IN.replace("vi.mock", "jest.mock")
    after = BEFORE.replace('  it("computes invoice total"', inside + '  it("computes invoice total"', 1)
    assert _analyze(BEFORE, after) == ([], [])

"""JS module mocks and replacing spies as TEST_PATCHES_SUBJECT events (issue #177).

The .gwcase fixtures carry the end-to-end shapes. These pin what a fixture
cannot isolate: which specifiers count as first-party, that a CRLF checkout
reports the same evidence, the two timing bounds the design rests on, and
the spellings that one shared definition must read alike.
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
SPY_MODE = 'vi.mock("../src/billing.js", { spy: true });\n'


def _analyze(before: str, after: str, path: str = PATH):
    snapshot = {path: after.encode("utf-8")}
    change = FileChange(path, "modified", before.encode("utf-8"), after.encode("utf-8"))
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
    ("tests/billing.test.js", "@/billing", "@/billing"),  # #196 188.6: an alias of the project's own source
    ("tests/billing.test.js", "/src/billing.js", None),
    ("tests/billing.test.js", "../../outside.js", None),
    ("tests/billing.test.js", "../node_modules/pkg/index.js", None),
    ("tests/billing.test.js", "../src/billing.js?raw", None),
])
def test_relative_repository_specifiers_and_aliases_are_first_party(test_path, specifier, expected):
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


@pytest.mark.parametrize("factory", [
    '({ ...(await importOriginal()), "invoiceTotal": () => 78.75 })',
    "({ ...(await importOriginal()), ['invoiceTotal']: () => 78.75 })",
    "{ const actual = await importOriginal(); actual.invoiceTotal = () => 78.75; return actual; }",
], ids=["quoted-key", "computed-key", "member-write"])
def test_a_partial_factory_replaces_every_name_it_spells(factory):
    """A quoted, computed or assigned name is spelled as surely as a bare key."""
    stand_in = f'vi.mock("../src/billing.js", async (importOriginal) => {factory});\n'
    events, _findings = _analyze(BEFORE, BEFORE.replace(VITEST, WITH_VI + stand_in))
    assert [target for _path, _unit, target, _text, _span in events] == ["src/billing:invoiceTotal"]


def test_a_partial_factory_that_quotes_only_a_sibling_keeps_the_subject_real():
    stand_in = ('vi.mock("../src/billing.js", async (importOriginal) => '
                '({ ...(await importOriginal()), "sendInvoice": vi.fn() }));\n')
    assert _analyze(BEFORE, BEFORE.replace(VITEST, WITH_VI + stand_in)) == ([], [])


def test_an_object_key_is_not_a_read_but_the_value_beside_it_is():
    """`{ invoiceTotal: ... }` names a property; the value beside it still
    reads the stand-in, here through one hop of a local binding."""
    before = BEFORE.replace(
        "    expect(invoiceTotal(items)).toBe(78.75);\n",
        "    const summary = { invoiceTotal: invoiceTotal(items) };\n"
        "    expect(summary).toEqual({ invoiceTotal: 78.75 });\n",
    )
    events, _findings = _analyze(before, before.replace(VITEST, WITH_VI + STAND_IN))
    assert [(unit, target) for _path, unit, target, _text, _span in events] == [
        ("computes invoice total", "src/billing:invoiceTotal")
    ]


@pytest.mark.parametrize("receiver", [
    "(invoiceTotal as Mock)",
    "(invoiceTotal as unknown as Mock)",
    "(<Mock>invoiceTotal)",
    "invoiceTotal!",
], ids=["as", "as-unknown-as", "angle-bracket", "non-null"])
def test_a_typescript_cast_still_names_the_replaced_binding(receiver):
    """Spy mode replaces nothing until a `mock*` call; TypeScript spells
    `invoiceTotal.mockReturnValue(...)` through a cast or a non-null assertion."""
    before = BEFORE.replace(VITEST, WITH_VI + SPY_MODE)
    after = before.replace("    expect(", f"    {receiver}.mockReturnValue(78.75);\n    expect(", 1)
    events, _findings = _analyze(before, after, "tests/billing.test.ts")
    assert [(unit, target) for _path, unit, target, _text, _span in events] == [
        ("computes invoice total", "src/billing:invoiceTotal")
    ]

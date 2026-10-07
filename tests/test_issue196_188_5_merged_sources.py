"""Stand-in names a test spells outside the installing call (#196 188.5).

Ruling 196.188.5, its closing round C: read names one hop through
`vi.hoisted` or a mock-prefixed object literal, treat only what stays
unreadable as opaque, and handle Python's targets built at runtime in the same
family.

- JS: a partial factory (one that builds on the real module) may replace every
  name it spells and every name an object it merges in carries: a spread in
  an object literal of its own body, an `Object.assign` argument, or a name it
  returns. The real module and an object written in the factory add nothing.
  A name bound outside the factory is read one hop: `vi.hoisted(...)`
  returning an object literal, or an object literal. Anything else makes the
  factory opaque, so it may replace every export.
- Python: a patch target built at runtime is read one hop, from a patcher: a
  name bound once to a string literal (in the test, else the module),
  `__name__` (the test module itself), and an f-string or `+` of those. One
  that stays unreadable is opaque, and its attribute is `*`.
"""

from __future__ import annotations

import datetime

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze
from checkwash.gitio.snapshot import search_source_mapping

TODAY = datetime.date(2026, 10, 7)

# --- JS: what a partial factory merges in --------------------------------------

JS_PATH = "tests/billing.test.js"
VITEST = 'import { it, expect, vi } from "vitest";\n'
NAMED = 'import { invoiceTotal } from "../src/billing.js";\n'
JS_TEST = (
    'it("computes invoice total", () => {\n'
    "  const items = [{ price: 10.0, qty: 3 }, { price: 5.0, qty: 9 }];\n"
    "  expect(invoiceTotal(items)).toBe(78.75);\n"
    "});\n"
)
JS_BEFORE = VITEST + NAMED + "\n" + JS_TEST
TARGET = "src/billing:invoiceTotal"

HOISTED_TOTAL = "const mocks = vi.hoisted(() => ({ invoiceTotal: vi.fn(() => 78.75) }));\n"
HOISTED_OTHER = "const mocks = vi.hoisted(() => ({ sendInvoice: vi.fn() }));\n"
SPREAD = 'vi.mock("../src/billing.js", async (importOriginal) => ({ ...(await importOriginal()), ...mocks }));\n'
BLOCK = (
    'vi.mock("../src/billing.js", async (importOriginal) => {\n'
    "  const actual = await importOriginal();\n"
    "  return { ...actual, ...mocks };\n"
    "});\n"
)
JEST = ('jest.mock("../src/billing.js", () => ({ ...jest.requireActual("../src/billing.js"), '
        "...mockBilling }));\n")


def js_targets(prelude: str, mock: str) -> list[str]:
    after = VITEST + NAMED + prelude + mock + "\n" + JS_TEST
    snapshot = {JS_PATH: after.encode("utf-8")}
    change = FileChange(JS_PATH, "modified", JS_BEFORE.encode("utf-8"), after.encode("utf-8"))
    ir, _findings, _verdict = analyze(
        [change], Config(), Contract(), [], TODAY, root_reader=snapshot.get,
        root_searcher=lambda needles: search_source_mapping(snapshot, needles),
    )
    return [target for _path, _unit, target, _text, _span in ir.globals.subject_installations]


@pytest.mark.parametrize("prelude, mock", [
    pytest.param(HOISTED_TOTAL, SPREAD, id="vi.hoisted spread"),
    pytest.param("const mocks = vi.hoisted(() => {\n  return { invoiceTotal: vi.fn(() => 78.75) };\n});\n",
                 SPREAD, id="vi.hoisted block body"),
    pytest.param("const mocks = vi.hoisted(function () {\n  return { invoiceTotal: vi.fn() };\n});\n",
                 SPREAD, id="vi.hoisted function"),
    pytest.param(HOISTED_TOTAL, BLOCK, id="spread in a returned object"),
    pytest.param(HOISTED_TOTAL,
                 'vi.mock("../src/billing.js", async (importOriginal) => { await importOriginal(); return mocks; });\n',
                 id="a returned name"),
    pytest.param(HOISTED_TOTAL,
                 'vi.mock("../src/billing.js", async (importOriginal) => '
                 "Object.assign(await importOriginal(), mocks));\n",
                 id="Object.assign"),
    pytest.param("const mockBilling = { invoiceTotal: () => 78.75 };\n", JEST, id="jest mock-prefixed object"),
    pytest.param("const mockBilling = { invoiceTotal: () => 78.75 } as const;\n", JEST, id="cast object"),
    pytest.param(HOISTED_TOTAL.replace("const mocks", "const m"),
                 SPREAD.replace("...mocks", "...(m as object)"), id="spread through a cast"),
])
def test_a_name_merged_in_one_hop_is_read(prelude, mock):
    assert js_targets(prelude, mock) == [TARGET]


@pytest.mark.parametrize("prelude, mock", [
    pytest.param(HOISTED_OTHER, SPREAD, id="vi.hoisted spread"),
    pytest.param(HOISTED_OTHER, BLOCK, id="spread in a returned object"),
    pytest.param(HOISTED_OTHER,
                 'vi.mock("../src/billing.js", async (importOriginal) => '
                 "Object.assign(await importOriginal(), mocks));\n",
                 id="Object.assign"),
    pytest.param("const mockBilling = { sendInvoice: () => 1 };\n", JEST, id="jest mock-prefixed object"),
])
def test_a_merged_object_that_replaces_another_export_is_no_event(prelude, mock):
    assert js_targets(prelude, mock) == []


@pytest.mark.parametrize("prelude, mock", [
    pytest.param("const mocks = makeMocks();\n", SPREAD, id="bound to a call"),
    pytest.param("", SPREAD, id="bound nowhere"),
    pytest.param("const mocks = vi.hoisted(() => ({ ...base, sendInvoice: vi.fn() }));\n", SPREAD,
                 id="a second hop"),
    pytest.param("const mocks = vi.hoisted(() => buildMocks());\n", SPREAD, id="vi.hoisted returns a call"),
    pytest.param(HOISTED_OTHER + "mocks.invoiceTotal = vi.fn(() => 78.75);\n", SPREAD, id="a member assigned"),
    pytest.param("let mocks = { sendInvoice: vi.fn() };\nmocks = { invoiceTotal: vi.fn() };\n", SPREAD,
                 id="rebound"),
    pytest.param("", 'vi.mock("../src/billing.js", async (importOriginal) => build(await importOriginal()));\n',
                 id="a returned call"),
    pytest.param("", 'vi.mock("../src/billing.js", async (importOriginal) => {\n'
                     "  const { invoiceTotal: _real, ...rest } = await importOriginal();\n"
                     "  return { ...rest, ...overrides() };\n});\n", id="spread of a call"),
    pytest.param("const mockBilling = { ...shared, sendInvoice: () => 1 };\n", JEST,
                 id="an object literal with its own spread"),
    pytest.param("", 'vi.mock("../src/billing.js", async (importOriginal) => '
                     "({ ...(await importOriginal().then(widen)), sendInvoice: vi.fn() }));\n",
                 id="a call on the real module's result"),
    pytest.param("", 'vi.mock("../src/billing.js", async (importOriginal) => {\n'
                     "  const mod = await importOriginal();\n"
                     "  if (useMocks) {\n    return makeMocks();\n  }\n"
                     "  return { ...mod, Billing: class extends mod.Billing {\n"
                     "    async fetch(url: URL): Promise<ArrayBuffer> {\n      return super.fetch(url);\n    }\n"
                     "  } };\n});\n",
                 id="a returned call beside a typed method"),
    pytest.param("", 'vi.mock("../src/billing.js", async (importOriginal) => {\n'
                     "  const mod = await importOriginal();\n"
                     "  switch (mode) {\n    case (FULL): return { ...mod, ...extra };\n  }\n"
                     "  return mod;\n});\n",
                 id="a case label is no return annotation"),
])
def test_what_stays_unreadable_makes_the_factory_opaque(prelude, mock):
    """An opaque factory may replace every export, so the read export is replaced."""
    assert js_targets(prelude, mock) == [TARGET]


@pytest.mark.parametrize("mock", [
    pytest.param('vi.mock("../src/billing.js", async (importOriginal) => '
                 "({ ...(await importOriginal()), sendInvoice: vi.fn() }));\n", id="the real module"),
    pytest.param('vi.mock("../src/billing.js", async (importOriginal) => '
                 '({ ...(await importOriginal<typeof import("../src/billing.js")>()), sendInvoice: vi.fn() }));\n',
                 id="the real module, typed"),
    pytest.param('vi.mock("../src/billing.js", async (orig) => ({ ...(await orig()), sendInvoice: vi.fn() }));\n',
                 id="the parameter by another name"),
    pytest.param('vi.mock("../src/billing.js", async (importOriginal) => {\n'
                 "  const actual = await importOriginal();\n"
                 "  return { ...actual, sendInvoice: vi.fn() };\n});\n", id="a name bound to it"),
    pytest.param('vi.mock("../src/billing.js", async () => '
                 '({ ...(await vi.importActual("../src/billing.js")), sendInvoice: vi.fn() }));\n',
                 id="vi.importActual"),
    pytest.param('vi.mock("../src/billing.js", async (importOriginal) => '
                 "({ ...(await importOriginal()), wrap: (o) => ({ ...o }) }));\n", id="a nested function's spread"),
    pytest.param('vi.mock("../src/billing.js", async (importOriginal) => '
                 "({ ...(await importOriginal()), log: (...args) => console.log(...args) }));\n",
                 id="a rest parameter and a call spread"),
    pytest.param('vi.mock("../src/billing.js", async (importOriginal) => {\n'
                 "  const overrides = { sendInvoice: vi.fn() };\n"
                 "  return { ...(await importOriginal()), ...overrides };\n});\n",
                 id="an object written in the factory"),
    pytest.param('vi.mock("../src/billing.js", async (importOriginal) => {\n'
                 "  const { sendInvoice: _real, ...rest } = await importOriginal();\n"
                 "  return { ...rest, sendInvoice: vi.fn() };\n});\n",
                 id="the rest of the real module"),
    pytest.param('vi.mock("../src/billing.js", async function (importOriginal) {\n'
                 "  return { ...(await importOriginal()), sendInvoice: vi.fn() };\n});\n",
                 id="a function factory"),
    pytest.param('vi.mock("../src/billing.js", async (importOriginal) => {\n'
                 "  const { verbose, ...unused } = settings;\n"
                 "  return { ...(await importOriginal()), sendInvoice: vi.fn() };\n});\n",
                 id="a destructuring rest merges nothing"),
    # A TypeScript return annotation keeps a method or an arrow out of the
    # bindings' function scopes; its body is still a nested function's.
    # excalidraw's setupTests.ts (b479f3bd65) is the first shape.
    pytest.param('vi.mock(\n  "../src/billing.js",\n  async (importOriginal) => {\n'
                 '    const mod = await importOriginal<\n      typeof import("../src/billing.js")\n    >();\n'
                 "    const Impl = mod.Billing;\n\n    return {\n      ...mod,\n"
                 "      Billing: class extends Impl {\n"
                 "        public async fetch(url: URL): Promise<ArrayBuffer> {\n"
                 "          return super.fetch(url);\n        }\n      },\n    };\n  },\n);\n",
                 id="a typed method's return"),
    pytest.param('vi.mock("../src/billing.js", async (importOriginal) => {\n'
                 "  const mod = await importOriginal();\n"
                 "  return { ...mod, build(): Billing {\n    return { ...base };\n  } };\n});\n",
                 id="a typed method's spread"),
    pytest.param('vi.mock("../src/billing.js", async (importOriginal) => '
                 "({ ...(await importOriginal()), wrap: (o): Wrapped<Billing> => ({ ...o }) }));\n",
                 id="a typed arrow's spread"),
    pytest.param('vi.mock("../src/billing.js", async (importOriginal) => {\n'
                 "  const mod = await importOriginal();\n"
                 "  return { ...mod, make: <T>(o: T): Promise<T> => {\n    return Promise.resolve(o);\n  } };\n"
                 "});\n",
                 id="a typed arrow's return"),
])
def test_the_real_module_and_the_factorys_own_objects_add_nothing(mock):
    assert js_targets("", mock) == []


def test_a_whole_module_factory_is_unchanged():
    """A factory that never builds on the real module replaces every export, as before."""
    assert js_targets(HOISTED_OTHER, 'vi.mock("../src/billing.js", () => mocks);\n') == [TARGET]


# --- Python: patch targets built at runtime --------------------------------------

PY_PATH = "tests/test_billing.py"
PROD = "def invoice_total(items, rate):\n    return 105.3\n"
PY_HEAD = "import os\n\nfrom app import billing\n"
ASSERT = "    assert billing.invoice_total([], 0.053) == 105.3\n"


def py_run(body: str, prelude: str = "", before_body: str = "", signature: str = "monkeypatch, mocker"):
    def source(lines):
        return f"{PY_HEAD}{prelude}\n\ndef test_total({signature}):\n{lines}{ASSERT}"

    before, after = source(before_body), source(body)
    snapshot = {PY_PATH: after.encode(), "app/billing.py": PROD.encode(), "app/__init__.py": b""}
    change = FileChange(PY_PATH, "modified", before.encode(), after.encode())
    ir, findings, verdict = analyze([change], Config(), Contract(), [], TODAY, root_reader=snapshot.get)
    unit = next(unit for file in ir.files for unit in file.units if unit.qualname == "test_total")
    found = [finding for finding in findings if finding.rule == "TEST_PATCHES_SUBJECT"]
    return sorted(unit.after.patches), found, verdict


@pytest.mark.parametrize("prelude, body, patch", [
    pytest.param('TARGET = "app.billing.invoice_total"\n', "    mocker.patch(TARGET, return_value=105.3)\n",
                 ("app.billing.invoice_total", "invoice_total"), id="module constant"),
    pytest.param("", '    target = "app.billing.invoice_total"\n    mocker.patch(target, return_value=105.3)\n',
                 ("app.billing.invoice_total", "invoice_total"), id="local string"),
    pytest.param('MOD = "app.billing"\n', '    mocker.patch(f"{MOD}.invoice_total", return_value=105.3)\n',
                 ("app.billing.invoice_total", "invoice_total"), id="f-string"),
    pytest.param('MOD = "app.billing"\n', '    mocker.patch(MOD + ".invoice_total", return_value=105.3)\n',
                 ("app.billing.invoice_total", "invoice_total"), id="concatenation"),
    pytest.param('TARGET = "app.billing.invoice_total"\n', "    monkeypatch.setattr(TARGET, lambda *a: 105.3)\n",
                 ("app.billing.invoice_total", "invoice_total"), id="setattr string form"),
    pytest.param('NAME = "invoice_total"\n', "    monkeypatch.setattr(billing, NAME, lambda *a: 105.3)\n",
                 ("billing.invoice_total", "invoice_total"), id="setattr attribute"),
    pytest.param('NAME = "invoice_total"\n',
                 "    from unittest import mock\n    mock.patch.object(billing, NAME, return_value=105.3).start()\n",
                 ("billing.invoice_total", "invoice_total"), id="patch.object attribute"),
])
def test_a_target_built_at_runtime_is_read_one_hop(prelude, body, patch):
    patches, found, verdict = py_run(body, prelude)
    assert patches == [patch]
    assert [finding.severity for finding in found] == ["high"] and verdict == "block"
    assert "which its own assertions check" in found[0].message


@pytest.mark.parametrize("prelude, body, patch", [
    pytest.param("def make_target():\n    return 'app.billing.invoice_total'\n",
                 "    mocker.patch(make_target(), return_value=105.3)\n", ("make_target()", "*"), id="a call"),
    pytest.param('TARGET = "app.billing.send_invoice"\nTARGET = "app.billing.invoice_total"\n',
                 "    mocker.patch(TARGET, return_value=105.3)\n", ("TARGET", "*"), id="bound twice"),
    pytest.param("", '    for target in ("app.billing.invoice_total",):\n        mocker.patch(target)\n',
                 ("target", "*"), id="a loop variable"),
    pytest.param("def pick():\n    return 'invoice_total'\n",
                 "    monkeypatch.setattr(billing, pick(), lambda *a: 105.3)\n", ("billing.*", "*"),
                 id="an unreadable attribute"),
])
def test_an_unreadable_target_is_opaque(prelude, body, patch):
    patches, found, verdict = py_run(body, prelude)
    assert patches == [patch]
    assert verdict == "block"
    assert found[0].message.endswith(
        "a target built at runtime that checkwash cannot read, so its own assertions may check the stand-in")


def test_a_parameter_is_unreadable():
    patches, found, _verdict = py_run("    mocker.patch(target, return_value=105.3)\n",
                                      'target = "app.billing.send_invoice"\n',
                                      signature="mocker, target")
    assert patches == [("target", "*")]
    assert len(found) == 1


def test_a_local_bound_twice_is_unreadable():
    patches, found, _verdict = py_run(
        '    target = "app.billing.send_invoice"\n    target = "app.billing.invoice_total"\n'
        "    mocker.patch(target)\n")
    assert patches == [("target", "*")]
    assert len(found) == 1


def test_a_percent_formatted_target_is_opaque():
    patches, found, _verdict = py_run('    mocker.patch("%s.invoice_total" % MOD)\n', 'MOD = "app.billing"\n')
    assert patches == [("'%s.invoice_total' % MOD", "*")]
    assert len(found) == 1


def test_an_opaque_attribute_of_an_object_the_assertions_do_not_reach_is_no_event():
    patches, found, verdict = py_run("    clock = make()\n    monkeypatch.setattr(clock, pick(), 0)\n",
                                     "def make():\n    return None\n\n\ndef pick():\n    return 'now'\n")
    assert patches == [("clock.*", "*")]
    assert found == [] and verdict == "pass"


def test_an_opaque_tail_keeps_its_attribute():
    """`f"{MOD}.compute"` with `MOD` unreadable still names the attribute it replaces."""
    patches, found, _verdict = py_run('    mocker.patch(f"{pick()}.send_invoice")\n',
                                      "def pick():\n    return 'app.billing'\n")
    assert patches == [("f'{pick()}.send_invoice'", "send_invoice")]
    assert found == []


@pytest.mark.parametrize("prelude, body", [
    pytest.param('MOD = "app.billing"\n', '    mocker.patch(f"{MOD}.send_invoice", return_value=1)\n',
                 id="another attribute"),
    pytest.param("", '    mocker.patch(f"{__name__}.invoice_total", return_value=105.3)\n',
                 id="the test module itself"),
    pytest.param("def pick():\n    return 'X'\n", '    monkeypatch.setitem(os.environ, pick(), "1")\n',
                 id="an unreadable key of os.environ"),
    pytest.param("def make():\n    return None\n", "    client = make()\n    client.patch(url)\n",
                 id="an HTTP client's patch"),
])
def test_what_is_read_and_replaces_nothing_checked_is_no_event(prelude, body):
    _patches, found, verdict = py_run(body, prelude)
    assert found == [] and verdict == "pass"


def test_a_runtime_target_the_base_already_patched_is_not_new():
    body = "    mocker.patch(TARGET, return_value=105.3)\n"
    _patches, found, verdict = py_run(body, 'TARGET = "app.billing.invoice_total"\n', before_body=body)
    assert found == [] and verdict == "pass"


def test_a_target_from_the_test_module_records_no_patch():
    patches, _found, _verdict = py_run('    mocker.patch(f"{__name__}.helper")\n')
    assert patches == []


def test_a_literal_target_is_read_as_before():
    patches, found, _verdict = py_run('    mocker.patch("app.billing.invoice_total", return_value=105.3)\n')
    assert patches == [("app.billing.invoice_total", "invoice_total")]
    assert len(found) == 1


@pytest.mark.parametrize("prelude, body", [
    pytest.param("", "    class A:\n        x = 5\n\n    with pytest.raises(TypeError):\n"
                     '        monkeypatch.setattr(A, "y")\n', id="a class the test defines"),
    pytest.param("def helper():\n    return 105.3\n", "    mocker.patch(helper, return_value=105.3)\n",
                 id="a function the module defines"),
    pytest.param("", "    monkeypatch.setattr(os, 105.3)\n", id="an imported module"),
    pytest.param("", "    mocker.patch(None)\n", id="a constant that is no string"),
])
def test_a_target_that_is_no_string_installs_nothing(prelude, body):
    """The patcher raises TypeError rather than install anything: pytest's own
    tests of monkeypatch spell it so (pytest b4f046b777)."""
    patches, found, verdict = py_run(body, prelude)
    assert patches == [] and found == [] and verdict == "pass"


@pytest.mark.parametrize("prelude, body", [
    pytest.param("from app.targets import TARGET\n", "    mocker.patch(TARGET, return_value=105.3)\n",
                 id="in the module"),
    pytest.param("", "    from app.targets import TARGET\n    mocker.patch(TARGET, return_value=105.3)\n",
                 id="in the test"),
])
def test_a_name_imported_from_a_module_may_be_a_string(prelude, body):
    """`from m import TARGET` may bind a string constant: it stays opaque."""
    patches, found, _verdict = py_run(body, prelude)
    assert patches == [("TARGET", "*")]
    assert len(found) == 1


def test_a_parameter_named_like_a_module_function_may_be_a_string():
    """A fixture is a module-level function the test requests by name: the
    parameter holds what it returns, a string here, not the function."""
    patches, found, _verdict = py_run(
        "    mocker.patch(target, return_value=105.3)\n",
        "@pytest.fixture\ndef target():\n    return 'app.billing.invoice_total'\n",
        signature="mocker, target")
    assert patches == [("target", "*")]
    assert len(found) == 1


def test_a_name_bound_to_a_class_and_a_string_is_unreadable():
    patches, found, _verdict = py_run(
        '    class A:\n        pass\n\n    A = "app.billing.invoice_total"\n    mocker.patch(A)\n')
    assert patches == [("A", "*")]
    assert len(found) == 1

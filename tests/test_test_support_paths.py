"""Files beneath a test-support directory serve tests, whatever their extension (#217).

Data, mocks and helpers beneath `__tests__/`, `__mocks__/` or `test/` took
the production role unless their name made them a JS/TS test. Editing one
beside a weakened assertion was an opaque production change, which granted
the whole diff the REPAIR_EVIDENCE exemption (THREATMODEL #4). Such a file now
takes the test role, as every file under Python's `tests/**` does, while E7
still reads its SPEC §2 table role (#196 186.8), so an out-of-scope edit to one
stays a production touch. The rows are #217's.
"""

import datetime

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze
from checkwash.roles import is_test_support_path

TODAY = datetime.date(2026, 10, 3)
JEST_BEFORE = (
    'import { invoiceTotal } from "../billing";\n'
    'import order from "./data.json";\n\n'
    'test("computes invoice total with tax", () => {\n'
    "  expect(invoiceTotal(order.items)).toBe(78.75);\n"
    "});\n"
)
JEST = FileChange("src/__tests__/billing.test.js", "modified", JEST_BEFORE.encode(),
                  JEST_BEFORE.replace("toBe(78.75)", "toBeTruthy()").encode())
NODE_BEFORE = (
    'const test = require("node:test");\n'
    'const assert = require("node:assert");\n'
    'const { invoiceTotal } = require("../src/billing");\n'
    'const order = require("./fixtures/order.json");\n\n'
    'test("computes invoice total with tax", () => {\n'
    "  assert.strictEqual(invoiceTotal(order.items), 78.75);\n"
    "});\n"
)
NODE = FileChange("test/billing.test.js", "modified", NODE_BEFORE.encode(),
                  NODE_BEFORE.replace("assert.strictEqual(invoiceTotal(order.items), 78.75)",
                                      "assert.ok(invoiceTotal(order.items))").encode())
DATA = '{ "items": [{ "price": 10.0, "qty": 3 }, { "price": 5.0, "qty": 9 }] }\n'
NOTED = DATA.replace(" }\n", ', "note": "x" }\n')


def _edit(path, before, after, status="modified"):
    return FileChange(path, status, before.encode(), after.encode())


def _analyze(changes, contract=None):
    return analyze(changes, Config(), contract or Contract(), [], TODAY, root_reader={}.get)


def _summary(findings):
    return [(f.rule, f.severity, tuple(f.escalators), tuple(f.deescalators)) for f in findings]


BLOCKED = [("ASSERT_WEAKENED", "high", ("NO_PROD_CHANGE_IN_DIFF",), ())]


@pytest.mark.parametrize("test,extra", [
    (JEST, _edit("src/__tests__/data.json", DATA, NOTED)),  # D1
    (JEST, _edit("src/__mocks__/billing.js", "export const invoiceTotal = () => 78.75;\n",
                 "export const invoiceTotal = () => 80;\n")),  # D2
    (JEST, _edit("src/__tests__/fixtures/order.yaml", "items: 2\n", "items: 3\n")),  # D3
    (NODE, _edit("test/fixtures/order.json", DATA, NOTED)),  # D6
])
def test_an_edit_beneath_a_test_support_directory_buys_no_exemption(test, extra):
    ir, findings, verdict = _analyze([test, extra])
    assert verdict == "block"
    assert _summary(findings) == BLOCKED
    assert {file.path: file.role for file in ir.files}[extra.path] == "test"
    assert not ir.globals.prod_opaque_change


@pytest.mark.parametrize("test,extra", [
    (JEST, None),  # D0
    (JEST, _edit("src/__tests__/helpers.js", "export const h = 1;\n", "export const h = 2;\n")),  # D4
    (JEST, _edit("tests/data.json", DATA, NOTED)),  # D5: Python's tests/** glob
])
def test_the_rows_that_already_blocked_still_block(test, extra):
    _ir, findings, verdict = _analyze([test] + ([extra] if extra else []))
    assert (verdict, _summary(findings)) == ("block", BLOCKED)


def test_unreadable_production_data_outside_them_keeps_the_exemption():
    # As runner_opaque_native_neg pins: THREATMODEL #4 is unchanged elsewhere.
    _ir, findings, verdict = _analyze([JEST, _edit("src/data.json", DATA, NOTED)])
    assert verdict == "pass"
    assert _summary(findings) == [("ASSERT_WEAKENED", "warn", (), ("REPAIR_EVIDENCE",))]


def test_test_data_moved_into_production_was_not_production_at_base():
    moved = FileChange("src/data.json", "renamed", DATA.encode(), NOTED.encode(),
                       old_path="src/__tests__/data.json")
    _ir, findings, verdict = _analyze([JEST, moved])
    assert (verdict, _summary(findings)) == ("block", BLOCKED)


def test_production_moved_beneath_a_test_support_directory_buys_nothing():
    # The role comes from the new path, as for every rename. What production
    # lost is a deletion, and a deletion buys no exemption either.
    moved = FileChange("src/__mocks__/billing.js", "renamed", b"export const t = 1;\n",
                       b"export const t = 2;\n", old_path="src/billing.js")
    _ir, findings, verdict = _analyze([JEST, moved])
    assert (verdict, _summary(findings)) == ("block", BLOCKED)


SNAPSHOT = _edit("src/__tests__/__snapshots__/view.test.js.snap",
                 'exports[`view 1`] = `"a"`;\n', 'exports[`view 1`] = `"b"`;\n')
MOCK = _edit("src/__mocks__/api.js", "export const get = () => 'a';\n", "export const get = () => 'b';\n")


@pytest.mark.parametrize("extra", [MOCK, _edit("src/__tests__/data.json", DATA, NOTED)])
def test_a_snapshot_rewritten_beside_test_support_alone_is_unexplained(extra):
    # SNAPSHOT_CODE_COCHANGE called the mock "prod code" and passed. With no
    # production change, the stored expectation is judged as a snapshot beside
    # data under Python's tests/ already is.
    _ir, findings, verdict = _analyze([SNAPSHOT, extra])
    assert verdict == "block"
    assert _summary(findings) == [("EXPECTED_VALUE_CHANGED", "high", ("NO_PROD_CHANGE_IN_DIFF",), ())]


def test_a_snapshot_beside_production_names_only_production():
    production = _edit("src/billing.js", "export const t = 1;\n", "export const t = 2;\n")
    _ir, findings, verdict = _analyze([SNAPSHOT, MOCK, production])
    assert verdict == "pass"
    assert [(f.rule, f.severity, f.message) for f in findings] == [(
        "SNAPSHOT_CODE_COCHANGE", "warn",
        "snapshot/golden file changed together with prod code (src/billing.js) and no test logic changed")]


def test_a_suite_control_beside_test_support_alone_changed_no_production_file():
    # SPEC §2b's label states a fact about the diff: no production-role file.
    conftest = _edit("tests/conftest.py", "import pytest\n", 'import pytest\n\ncollect_ignore = ["test_billing.py"]\n')
    _ir, findings, verdict = _analyze([conftest, _edit("test/fixtures/order.json", DATA, NOTED)])
    assert verdict == "block"
    assert _summary(findings) == [("TEST_DISABLED", "high", ("NO_PROD_CHANGE_IN_DIFF",), ())]


CONTRACT = Contract(present=True, scope_allow=["src/billing/**"])


@pytest.mark.parametrize("change", [
    _edit("src/__tests__/data.json", DATA, NOTED),  # E1
    _edit("src/__tests__/helpers.js", "export const h = 1;\n", "export const h = 2;\n"),  # E2
    _edit("src/__mocks__/billing.js", "export const t = 1;\n", "export const t = 2;\n"),
    _edit("test/fixtures/order.json", DATA, NOTED),
])
def test_e7_still_reads_the_table_role_out_of_scope(change):
    _ir, findings, verdict = _analyze([change], CONTRACT)
    assert verdict == "block"
    scope, = [f for f in findings if f.rule == "SCOPE_DRIFT"]
    assert (scope.severity, scope.escalators, scope.message.endswith("(role: prod)")) == (
        "high", ["OUT_OF_SCOPE_PROD_TOUCH"], True)


def test_a_python_tests_file_out_of_scope_stays_a_warning():
    # E3: the table role itself is test.
    _ir, findings, verdict = _analyze([_edit("tests/data.json", DATA, NOTED)], CONTRACT)
    assert verdict == "pass"
    assert [(f.rule, f.severity) for f in findings] == [("SCOPE_DRIFT", "warn")]


@pytest.mark.parametrize("path,role", [
    # Earlier rows of the SPEC §2 table win, as they do over the JS test role.
    ("test/README.md", "docs"),
    ("src/__tests__/__snapshots__/billing.test.js.snap", "snapshot"),
    # Python files keep the table's Python rows.
    ("test/helpers.py", "prod"),
])
def test_the_overlay_only_replaces_production(path, role):
    ir, _findings, _verdict = _analyze([_edit(path, "a = 1\n", "a = 2\n")])
    assert [file.role for file in ir.files] == [role]


@pytest.mark.parametrize("path,expected", [
    ("src/__tests__/data.json", True),
    ("src/__mocks__/billing.js", True),
    ("test/fixtures/order.json", True),
    ("packages/a/test/data.txt", True),
    ("src/__Tests__/data.json", True),  # case-insensitive, as test obligations are
    ("src/Test/data.yaml", True),
    ("test/helpers.py", False),  # Python keeps its own rows
    ("tests/data.json", False),  # the table already says test
    ("src/test-data/x.json", False),  # whole segments only
    ("src/__tests__x/data.json", False),
    ("src/contest/data.json", False),
    ("src/__fixtures__/data.json", False),
    ("node_modules/pkg/test/data.json", False),  # an artifact
    ("test", False),
])
def test_what_a_test_support_path_is(path, expected):
    assert is_test_support_path(path) is expected

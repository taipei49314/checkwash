"""E7 reads a path-only test role only when the file declares a test (#196 186.8).

The JS/TS test role is an engine overlay on the SPEC §2 table (#175, #197).
When the overlay finds no test on either side, no test rule reads the file,
so E7 judges it by its table role: an out-of-scope edit to production code
named like a test is OUT_OF_SCOPE_PROD_TOUCH. Every other rule keeps the test
role, and no production credit comes back.
"""

import datetime

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze
from checkwash.frontends.javascript.frontend import parse_javascript

TODAY = datetime.date(2026, 10, 3)
CONTRACT = Contract(present=True, scope_allow=["src/billing/**"])
RENDER = "export function render(x: number): number {\n  return x + 1;\n}\n"


def _edit(path, before, after, contract=CONTRACT, extra=()):
    changes = [FileChange(path, "modified", before.encode(), after.encode()), *extra]
    return analyze(changes, Config(), contract, [], TODAY, root_reader={}.get)


def _scope(findings):
    return [(f.rule, f.severity, f.path, tuple(f.escalators), f.message.rpartition("(")[2])
            for f in findings if f.rule == "SCOPE_DRIFT"]


@pytest.mark.parametrize("path", [
    "src/api/spec.ts",  # S1: a bare Jest spec name
    "src/components/Test.tsx",  # S2: test obligations fold case
    "src/ui/test.jsx",  # S3
    "src/x/test.ts",  # Sp1
    "src/lib/test-utils.ts",  # Sp2: node:test's test-* name
    "src/api/Test.ts",  # Sp3
    "src/test/fixtures.ts",  # Sp4: beneath a test directory
    # The cost the ruling accepts: a zero-unit helper beneath __tests__ (#217 E2).
    "src/__tests__/helpers.js",
])
def test_out_of_scope_code_at_a_test_path_without_tests_is_a_production_touch(path):
    ir, findings, verdict = _edit(path, RENDER, RENDER.replace("+ 1", "+ 2"))
    assert verdict == "block"
    assert _scope(findings) == [("SCOPE_DRIFT", "high", path, ("OUT_OF_SCOPE_PROD_TOUCH",), "role: prod)")]
    # Every other rule keeps the test role.
    assert [file.role for file in ir.files] == ["test"]


@pytest.mark.parametrize("source", [
    # A unit the scan reads.
    'it("renders", () => { expect(render(1)).toBe(2); });\n',
    # Declarations the unit scan does not read still declare tests: a table,
    # a computed title, a suite whose tests a helper declares.
    'it.each([[1, 2]])("renders %i", (x, y) => { expect(render(x)).toBe(y); });\n',
    'for (const c of cases) {\n  it(c.name, () => { expect(render(c.x)).toBe(c.y); });\n}\n',
    'describe("render", () => { runCases(render); });\n',
    # A pending test.
    'test.todo("renders negative input");\n',
])
def test_a_file_that_declares_a_test_keeps_its_test_role_for_e7(source):
    _ir, findings, verdict = _edit("src/api/spec.ts", source, source + "// touched\n")
    assert (_scope(findings), verdict) == ([("SCOPE_DRIFT", "warn", "src/api/spec.ts", (), "role: test)")], "pass")


def test_a_test_on_either_side_keeps_the_test_role():
    test = 'it("renders", () => { expect(render(1)).toBe(2); });\n'
    for before, after in ((test, RENDER), (RENDER, test)):
        _ir, findings, _verdict = _edit("src/api/spec.ts", before, after)
        assert _scope(findings) == [("SCOPE_DRIFT", "warn", "src/api/spec.ts", (), "role: test)")]


def test_a_pattern_test_call_declares_no_test():
    source = "export const isId = (value: string) => /^\\d+$/.test(value);\n"
    _ir, findings, verdict = _edit("src/api/spec.ts", source, source.replace("\\d+", "\\d*"))
    assert verdict == "block"
    assert _scope(findings)[0][1] == "high"


def test_a_python_helper_under_tests_keeps_its_table_test_role():
    # config.py's tests/** glob makes the table role itself test.
    _ir, findings, verdict = _edit("tests/helpers.py", "def f():\n    return 1\n", "def f():\n    return 2\n")
    assert (_scope(findings), verdict) == ([("SCOPE_DRIFT", "warn", "tests/helpers.py", (), "role: test)")], "pass")


def test_runner_promotion_is_part_of_the_table_role():
    # A promoted runner script is judged as ci, as before, not as prod.
    _ir, findings, verdict = _edit("scripts/test.sh", "pytest tests\n", "pytest tests || true\n")
    assert ("SCOPE_DRIFT", "high", "scripts/test.sh", ("OUT_OF_SCOPE_PROD_TOUCH",), "role: ci)") in _scope(findings)


def test_non_js_data_beneath_tests_stays_a_production_touch():
    # #217 E1: its table role is prod and no overlay applies.
    _ir, findings, verdict = _edit("src/__tests__/data.json", '{"a": 1}\n', '{"a": 2}\n')
    assert verdict == "block"
    assert _scope(findings) == [("SCOPE_DRIFT", "high", "src/__tests__/data.json", ("OUT_OF_SCOPE_PROD_TOUCH",), "role: prod)")]


def test_no_production_credit_comes_back():
    # A weakened assertion beside an edit to production code named like a
    # test: that file is still a test for every rule but E7, so it is no
    # production change and grants no repair evidence.
    before = 'import { total } from "./total";\nit("total", () => { expect(total()).toBe(78.75); });\n'
    weakened = FileChange("src/billing/total.test.ts", "modified", before.encode(),
                          before.replace("toBe(78.75)", "toBeTruthy()").encode())
    _ir, findings, verdict = _edit("src/api/spec.ts", RENDER, RENDER.replace("+ 1", "+ 2"),
                                   contract=Contract(), extra=[weakened])
    assert verdict == "block"
    assert [(f.rule, f.severity, tuple(f.escalators), tuple(f.deescalators)) for f in findings] == [
        ("ASSERT_WEAKENED", "high", ("NO_PROD_CHANGE_IN_DIFF",), ())]


@pytest.mark.parametrize("source,expected", [
    ('it("a", () => {});', True),
    ('it.each([[1]])("a %i", (n) => {});', True),
    ("it(name, () => {});", True),
    ('describe("s", () => { helper(); });', True),
    ('test.todo("later");', True),
    ('test("subtest", { skip: true }, async (t) => {});', True),
    ("export const ok = /x/.test(value);", False),
    ("export function render() { return 1; }", False),
    ("model.fit(data);", False),
    ('const run = test.skip;', False),
])
def test_what_declares_a_test(source, expected):
    assert parse_javascript(source.encode()).declares_tests is expected

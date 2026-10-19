"""JS/TS `.each`/`.for` tables are test units whose rows are read (#428).

Before #428 the frontend marked every `test.each`, `it.each` and `test.for`
declaration as a table and left it out of the unit scan, so a weakened or
deleted assertion inside one, an edited row or a deleted table passed with
zero findings. Ruling 428 (owner, 2026-10-14, 「P1 全部照建議」):

- Q1 (a): one unit per table declaration, named by its title as written,
  its rows as `param_cases`/`param_rows`, columns identified by row
  position, key or heading, never by the callback's parameter names;
- Q1b (iii): rows counted for an inline array literal with no spread or
  hole, a tagged template, and one hop to a same-file `const` bound once
  to such a literal and read nowhere else; otherwise `param_rows_unknown`;
- Q1c (i): span-order pairing unchanged;
- Q2a (a): a lost row is TEST_DISABLED, and so is a plain test paired with
  a table of no rows or of rows that cannot be counted;
- Q2b (a): an assertion's expected operand and subject record the column
  ids they name directly (`#2`, `#expected`);
- Q2c (b): `describe.each` rows are not read;
- Q2d (a): D-060's literal-table arm applies to JS rows;
- Q3 (a): no fold projection.

The `.gwcase` fixtures `js_table_*` and `js_test_wrapped_in_*` pin the
issue's own reproduction; these pin the matrix and the readings.
"""

from __future__ import annotations

import datetime

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze
from checkwash.frontends.javascript.frontend import parse_javascript
from checkwash.frontends.python.frontend import parse_python
from checkwash.ir.diffalign import align_file
from checkwash.ir.model import ParamTable
from checkwash.report.context import ReportContext

TODAY = datetime.date(2026, 1, 1)
PATH = "tests/add.test.ts"
HEAD = 'import { expect, it, test } from "vitest";\nimport { add } from "../src/add";\n\n'
PLAIN = 'test("adds", () => {\n  expect(add(1, 1)).toBe(2);\n});\n\n'
ASSERTION = "expect(add(a, b)).toBe(sum);"
WEAKENED = "expect(add(a, b)).toBeDefined();"
ROWS = (("1.0", "2.0", "3.0"), ("2.0", "3.0", "5.0"))

# The acceptance's spellings: `test.each`, `it.each` and `test.for`, each in
# the call and in the tagged-template form. `@@` is the callback's body.
_GRID = "  a    | b    | sum\n  ${1} | ${2} | ${3}\n  ${2} | ${3} | ${5}\n"
TABLES = {
    "test.each": ('test.each([\n  [1, 2, 3],\n  [2, 3, 5],\n])'
                  '("add(%i, %i) = %i", (a, b, sum) => {\n  @@\n});\n'),
    "it.each": ('it.each([\n  [1, 2, 3],\n  [2, 3, 5],\n])'
                '("add(%i, %i) = %i", (a, b, sum) => {\n  @@\n});\n'),
    "test.for": ('test.for([\n  [1, 2, 3],\n  [2, 3, 5],\n])'
                 '("add(%i, %i) = %i", ([a, b, sum]) => {\n  @@\n});\n'),
    "test.each template": ("test.each`\n" + _GRID + '`("add($a, $b) = $sum", ({ a, b, sum }) => {\n  @@\n});\n'),
    "it.each template": ("it.each`\n" + _GRID + '`("add($a, $b) = $sum", ({ a, b, sum }) => {\n  @@\n});\n'),
    "test.for template": ("test.for`\n" + _GRID + '`("add($a, $b) = $sum", ({ a, b, sum }) => {\n  @@\n});\n'),
}


def _file(table: str, body: str | None) -> str:
    """The issue's test file: a plain test, then the table with `body`, or no table."""
    return HEAD + PLAIN + ("" if body is None else table.replace("@@", body))


def _outcome(before: str, after: str):
    change = FileChange(PATH, "modified", before.encode(), after.encode())
    context = ReportContext()
    _ir, findings, verdict = analyze([change], Config(), Contract(), [], TODAY, report_context=context)
    return verdict, sorted((f.rule, f.severity) for f in findings), len(context.coverage_gaps)


def _findings(before: str, after: str):
    _ir, findings, verdict = analyze([FileChange(PATH, "modified", before.encode(), after.encode())],
                                     Config(), Contract(), [], TODAY)
    return verdict, findings


# --- the acceptance matrix -------------------------------------------------


@pytest.mark.parametrize("table", sorted(TABLES))
@pytest.mark.parametrize("body, expected", [
    pytest.param(WEAKENED, [("ASSERT_WEAKENED", "high")], id="weakened"),
    pytest.param("", [("ASSERT_REMOVED", "high")], id="assertion-deleted"),
    pytest.param(None, [("TEST_DISABLED", "high")], id="table-deleted"),
])
def test_an_edit_inside_a_table_blocks(table, body, expected):
    """W, D and B of the issue, for every spelling; nothing is left a coverage gap."""
    before = _file(TABLES[table], ASSERTION)
    assert _outcome(before, _file(TABLES[table], body)) == ("block", expected, 0)


def test_the_plain_test_beside_a_table_still_blocks_alone():
    """The control: weakening `test("adds")` reports that one edit."""
    before = _file(TABLES["test.each"], ASSERTION)
    after = before.replace("expect(add(1, 1)).toBe(2);", "expect(add(1, 1)).toBeDefined();")
    assert _outcome(before, after) == ("block", [("ASSERT_WEAKENED", "high")], 0)


# --- what the frontend reads ----------------------------------------------


@pytest.mark.parametrize("table", sorted(TABLES))
def test_a_table_is_one_unit_with_its_rows_and_the_columns_its_assertion_reads(table):
    units = parse_javascript(_file(TABLES[table], ASSERTION).encode()).units
    template = table.endswith("template")
    title = "add($a, $b) = $sum" if template else "add(%i, %i) = %i"
    names = ("#a", "#b", "#sum") if template else ("#0", "#1", "#2")
    assert [unit.qualname for unit in units] == ["adds", title]
    plain, side = units[0].side, units[1].side
    assert (plain.param_cases, plain.param_rows, plain.param_rows_unknown) == (None, (), False)
    assert (side.param_cases, side.param_rows_unknown) == (2, False)
    assert side.param_rows == (ParamTable(names, ROWS, (False, False)),)
    (assertion,) = side.assertions
    assert (assertion.right_depends_on, assertion.left_names) == ((names[2],), names[:2])


def _table(source: str):
    """The side of the one unit titled "t" that `source` declares."""
    (unit,) = [unit for unit in parse_javascript((HEAD + source).encode()).units if unit.qualname == "t"]
    return unit.side


_CHECK = '("t", (a, b) => {\n  expect(add(a, 0)).toBe(b);\n});\n'


@pytest.mark.parametrize("source, names, rows", [
    pytest.param('test.each([1, 2])("t", (n) => {\n  expect(add(n, 0)).toBe(n);\n});\n',
                 ("#0",), (("1.0",), ("2.0",)), id="scalar-rows-one-column"),
    pytest.param('test.each([[1], [2]])("t", (n) => {\n  expect(add(n, 0)).toBe(n);\n});\n',
                 ("#0",), (("1.0",), ("2.0",)), id="one-wide-arrays-the-same-column"),
    pytest.param('test.each([{ a: 1, expected: 2 }, { expected: 3, a: 2 }])'
                 '("t", ({ a, expected }) => {\n  expect(add(a, 0)).toBe(expected);\n});\n',
                 ("#a", "#expected"), (("1.0", "2.0"), ("2.0", "3.0")), id="object-rows-by-key"),
    pytest.param('test.each([{ "a": 1 }, { a: 2 }])("t", ({ a }) => {\n  expect(add(a, 0)).toBe(1);\n});\n',
                 ("#a",), (("1.0",), ("2.0",)), id="a-quoted-key-is-the-key"),
    pytest.param('test.each([[1, 2], 3])("t", (n) => {\n  expect(add(n, 0)).toBe(n);\n});\n',
                 ("#0",), (("[ 1 , 2 ]",), ("3.0",)), id="a-row-that-is-no-array-passes-every-row-whole"),
    pytest.param('test.each([["a", true, null], [\'a\', true, null]])("t", (s, b, n) => {\n'
                 '  expect(add(s, 0)).toBe(b);\n});\n',
                 ("#0", "#1", "#2"), (("'a'", "true", "null"), ("'a'", "true", "null")),
                 id="strings-by-value-keywords-by-text"),
    pytest.param("const CASES = [[1, 2], [2, 3]];\ntest.each(CASES)" + _CHECK,
                 ("#0", "#1"), (("1.0", "2.0"), ("2.0", "3.0")), id="one-hop-const"),
    pytest.param("const CASES = [[1, 2]] as const;\ntest.each(CASES)" + _CHECK,
                 ("#0", "#1"), (("1.0", "2.0"),), id="one-hop-const-as-const"),
])
def test_rows_are_read_by_position_key_or_heading(source, names, rows):
    side = _table(source)
    assert (side.param_cases, side.param_rows_unknown) == (len(rows), False)
    assert side.param_rows == (ParamTable(names, rows, (False,) * len(rows)),)


@pytest.mark.parametrize("source", [
    pytest.param("test.each([...base, [1, 2]])" + _CHECK, id="spread"),
    pytest.param("test.each([[1, 2], , [2, 3]])" + _CHECK, id="hole"),
    pytest.param("test.each(process.env.CI ? [] : [[1, 2]])" + _CHECK, id="conditional"),
    pytest.param('import { cases } from "./cases";\ntest.each(cases)' + _CHECK, id="imported"),
    pytest.param("let CASES = [[1, 2]];\ntest.each(CASES)" + _CHECK, id="let-binding"),
    pytest.param("const CASES = [[1, 2]];\nCASES.push([3, 4]);\ntest.each(CASES)" + _CHECK, id="pushed"),
    pytest.param("const CASES = [[1, 2]];\nCASES.length = 0;\ntest.each(CASES)" + _CHECK, id="emptied"),
    pytest.param("export const CASES = [[1, 2]];\ntest.each(CASES)" + _CHECK, id="exported"),
    pytest.param("const CASES = [[1, 2]];\nconst copy = CASES;\ntest.each(CASES)" + _CHECK, id="read-elsewhere"),
    pytest.param("const CASES = [[1, 2]];\nconst note = `${CASES.splice(0)}`;\ntest.each(CASES)" + _CHECK,
                 id="read-in-a-template"),
    pytest.param("const CASES = [[1, 2]].concat(more);\ntest.each(CASES)" + _CHECK, id="const-not-a-literal"),
    pytest.param("test.each([[1, 2]].concat(more))" + _CHECK, id="inline-not-a-literal"),
    pytest.param("test.each`\n  a | b\n  ${1} | ${2}\n  ${3}\n`(\"t\", ({ a, b }) => {\n"
                 "  expect(add(a, 0)).toBe(b);\n});\n", id="template-cells-do-not-divide"),
])
def test_rows_that_cannot_be_counted_are_unknown(source):
    side = _table(source)
    assert (side.param_cases, side.param_rows, side.param_rows_unknown) == (None, (), True)


@pytest.mark.parametrize("source, expected, subject", [
    pytest.param('test.each([{ a: 1, expected: 2 }])("t", ({ a, expected: want }) => {\n'
                 '  expect(add(a, 0)).toBe(want);\n});\n', ("#expected",), ("#a",), id="renamed-key"),
    pytest.param('test.each([[1, 2]])("t", (a, b) => {\n  {\n    const b = 3;\n'
                 '    expect(add(a, 0)).toBe(b);\n  }\n});\n', (), ("#0",), id="shadowed-in-a-block"),
    pytest.param('test.each([[1, 2]])("t", (a, b) => {\n  b = 5;\n  expect(add(a, 0)).toBe(b);\n});\n',
                 (), ("#0",), id="written-parameter"),
    pytest.param('test.each([[1, 2]])("t", (a, b) => {\n  const want = b;\n'
                 '  expect(add(a, 0)).toBe(want);\n});\n', (), ("#0",), id="a-local-is-not-followed"),
    pytest.param('test.each([[1, 2]])("t", (a, b) => {\n  expect(add(a, 0)).toBe(a + b);\n});\n',
                 ("#0", "#1"), ("#0",), id="an-expression-over-columns"),
    pytest.param('test.for([1, 2])("t", (n) => {\n  expect(add(n, 0)).toBe(n);\n});\n',
                 ("#0",), ("#0",), id="for-one-column"),
    pytest.param('test.each([{ a: 1, expected: 2 }])("t", (row) => {\n'
                 '  expect(add(row.a, 0)).toBe(row.expected);\n});\n', (), (), id="a-member-is-not-followed"),
    pytest.param('test.each([[1, 2]])("t", (a: number, b: number) => {\n  expect(add(a, 0)).toBe(b);\n});\n',
                 ("#1",), ("#0",), id="typed-parameters"),
    # A comma inside a type argument would shift `a` onto the third column
    # and drop `want`, so the list gives no column at all.
    pytest.param('test.each([[1, 2, 3]])("t", (m: Map<string, number>, a: number, want: number) => {\n'
                 '  expect(add(a, 0)).toBe(want);\n});\n', (), (), id="a-type-argument-holds-a-comma"),
])
def test_an_assertion_records_the_columns_it_names_directly(source, expected, subject):
    (assertion,) = _table(source).assertions
    assert (assertion.right_depends_on, assertion.left_names) == (expected, subject)


@pytest.mark.parametrize("source, markers", [
    pytest.param('test.each([[1]])("t", (t) => {\n  t.skip();\n  expect(add(t, 0)).toBe(1);\n});\n',
                 [], id="each-row-is-no-context"),
    pytest.param('test.for([[1]])("t", ([n], ctx) => {\n  ctx.skip();\n  expect(add(n, 0)).toBe(1);\n});\n',
                 ["test.skip"], id="for-context-is-the-second-parameter"),
    pytest.param('test("t", (t) => {\n  t.skip();\n  expect(add(1, 0)).toBe(1);\n});\n',
                 ["test.skip"], id="plain-test-context-unchanged"),
])
def test_a_tables_row_is_not_its_test_context(source, markers):
    assert [marker.name for marker in _table(source).markers] == markers


DESCRIBE_EACH = ('describe.each(@@)("group %i", (n) => {\n'
                 '  it("computes", () => {\n    expect(add(n, 0)).toBe(n);\n  });\n});\n')


def test_describe_each_rows_are_not_read():
    """Q2c (b): the nested unit is scanned, the block's rows are not."""
    units = parse_javascript((HEAD + DESCRIBE_EACH.replace("@@", "[[1], [2]]")).encode()).units
    assert [(unit.qualname, unit.side.param_cases, unit.side.param_rows, unit.side.param_rows_unknown)
            for unit in units] == [("computes", None, (), False)]


def test_a_row_deleted_from_describe_each_stays_a_stated_residual():
    before = HEAD + DESCRIBE_EACH.replace("@@", "[[1], [2]]")
    after = HEAD + DESCRIBE_EACH.replace("@@", "[[1]]")
    assert _outcome(before, after)[:2] == ("pass", [])


# --- the count rule ---------------------------------------------------------

ADDS = '("adds", () => {\n  expect(add(1, 1)).toBe(2);\n});\n'
PLAIN_ADDS = "test" + ADDS


def _each(rows: str) -> str:
    return f"test.each({rows})" + ADDS


def _removed(before: str, after: str) -> int:
    file = align_file(PATH, "test", "modified", parse_javascript((HEAD + before).encode()),
                      parse_javascript((HEAD + after).encode()))
    (unit,) = file.units
    return unit.delta.param_cases_removed


@pytest.mark.parametrize("before, after, removed", [
    pytest.param(PLAIN_ADDS, _each("[]"), 1, id="plain-to-no-rows"),
    pytest.param(PLAIN_ADDS, _each("cases"), 1, id="plain-to-unknown"),
    pytest.param(PLAIN_ADDS, _each("[[1], [2]]"), 0, id="plain-to-two-rows"),
    pytest.param(_each("[[1], [2]]"), PLAIN_ADDS, 1, id="two-rows-to-plain"),
    pytest.param(_each("[[1], [2]]"), _each("[[1]]"), 1, id="two-rows-to-one"),
    pytest.param(_each("[[1], [2]]"), _each("cases"), 0, id="counted-to-unknown"),
    pytest.param(_each("cases"), _each("[[1]]"), 0, id="unknown-to-counted"),
    pytest.param(_each("cases"), PLAIN_ADDS, 0, id="unknown-to-plain"),
    pytest.param(_each("[]"), PLAIN_ADDS, 0, id="no-rows-to-plain"),
    pytest.param(_each("cases"), _each("others"), 0, id="unknown-to-unknown"),
])
def test_the_count_rule_between_plain_tests_and_tables(before, after, removed):
    assert _removed(before, after) == removed


def test_python_keeps_its_count_rule():
    """A Python test that gains `parametrize(..., [])` is not this rule's: a
    hook can parametrize a test with no decorator, so Python keeps its own
    two-sided proof (`empty_parameter_sets.py`), and never sets the flag."""
    before = "def test_adds():\n    assert 1 + 1 == 2\n"
    after = 'import pytest\n\n\n@pytest.mark.parametrize("x", [])\ndef test_adds(x):\n    assert 1 + 1 == 2\n'
    file = align_file("tests/test_adds.py", "test", "modified",
                      parse_python(before.encode(), collect_tests=True),
                      parse_python(after.encode(), collect_tests=True))
    (unit,) = [unit for unit in file.units if unit.qualname == "test_adds"]
    assert (unit.after.param_cases, unit.delta.param_cases_removed) == (0, 0)
    assert not unit.before.param_rows_unknown and not unit.after.param_rows_unknown


@pytest.mark.parametrize("rows, message, evidence", [
    pytest.param("[]", "adds: 1 parametrized case(s) deleted (1 -> 0)", "parametrize cases: 0", id="no-rows"),
    pytest.param("process.env.CI ? [] : [[1]]", "adds: 1 parametrized case(s) deleted (1 -> unknown)",
                 "parametrize cases: unknown", id="unknown"),
])
def test_a_plain_test_wrapped_in_a_table_reports_the_one_item_it_was(rows, message, evidence):
    verdict, findings = _findings(HEAD + PLAIN_ADDS, HEAD + _each(rows))
    assert verdict == "block"
    assert [(f.rule, f.severity, f.message, f.after.text) for f in findings] == [
        ("TEST_DISABLED", "high", message, evidence)]


def test_a_template_table_respelled_as_object_rows_keeps_its_rows():
    """A heading and an object key name the same column, so the respelling is no change."""
    callback = '("add", ({ a, b, sum }) => {\n  expect(add(a, b)).toBe(sum);\n});\n'
    before = HEAD + "test.each`\n  a | b | sum\n  ${1} | ${2} | ${3}\n`" + callback
    after = HEAD + "test.each([{ a: 1, b: 2, sum: 3 }])" + callback
    assert _outcome(before, after)[:2] == ("pass", [])

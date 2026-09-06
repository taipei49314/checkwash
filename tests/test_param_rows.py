"""Parametrize rows by identity, not by count (F-063).

`UnitSide.param_cases` is the number of live rows, and `before - after` is
satisfied by any edit that keeps the total: wrap one row in
`pytest.param(..., marks=pytest.mark.skip)`, append another, and the disabled
test item is never reported. These tests pin the row-identity floor that
`diffalign` now puts under that count -- the numbers it reports, the message
`TEST_DISABLED` prints, the shapes that must stay silent, and the fallbacks
that keep the old behaviour when the rows cannot be paired.
"""

import json
import types

from checkwash.detectors.test_disabled import detect
from checkwash.frontends.python.frontend import parse_python
from checkwash.ir.diffalign import _param_rows_lost, align_file
from checkwash.ir.model import (
    Assertion,
    AssertionPair,
    DiffGlobals,
    FileIR,
    IR,
    ParamTable,
    Unit,
    UnitDelta,
    UnitSide,
    param_tables,
    to_jsonable,
)

PATH = "tests/test_billing.py"
HEAD = "import pytest\n\nfrom billing import invoice_total\n\n\n"
BODY = "def test_invoice_total_applies_tax(items, expected):\n    assert invoice_total(items, 0.05) == expected\n"


def table(*rows: str, names: str = "items,expected") -> str:
    cells = "".join(f"        {r},\n" for r in rows)
    return f'@pytest.mark.parametrize(\n    "{names}",\n    [\n{cells}    ],\n)\n'


def src(*rows: str, names: str = "items,expected", body: str = BODY) -> str:
    return HEAD + table(*rows, names=names) + body


def align(before: str, after: str) -> FileIR:
    b = parse_python(before.encode(), collect_tests=True)
    a = parse_python(after.encode(), collect_tests=True)
    return align_file(PATH, "test", "modified", b, a)


def unit(before: str, after: str) -> Unit:
    file = align(before, after)
    assert len(file.units) == 1, [u.qualname for u in file.units]
    return file.units[0]


def side(source: str) -> UnitSide:
    parsed = parse_python(source.encode(), collect_tests=True)
    assert len(parsed.units) == 1
    return parsed.units[0].side


def message(before: str, after: str) -> str:
    file = align(before, after)
    ir = IR(base="b", head="a", files=[file], globals=DiffGlobals())
    found = [f for f in detect(ir) if f.shape == "param_cases_removed"]
    assert len(found) == 1, [f.message for f in detect(ir)]
    return found[0].message


ROW_A = "([50.0, 50.0], 105.0)"
ROW_B = "([10.0], 10.5)"
ROW_C = "([20.0], 21.0)"
NEW = "([1.0, 1.0], 2.1)"
SKIP_A = "pytest.param([50.0, 50.0], 105.0, marks=pytest.mark.skip)"
SKIP_B = "pytest.param([10.0], 10.5, marks=pytest.mark.skip)"


# --- the frontend records rows through pytest.param ------------------------


def test_frontend_records_every_cell_of_a_wrapped_row():
    s = side(src(SKIP_A, "pytest.param([10.0], 10.5, id='one')", ROW_C))
    assert s.param_rows == (
        ParamTable(
            names=("items", "expected"),
            rows=(("[50.0, 50.0]", "105.0"), ("[10.0]", "10.5"), ("[20.0]", "21.0")),
            disabled=(True, False, False),
        ),
    )
    # The count and the rows describe the same decorator.
    assert s.param_cases == 2


def test_single_argname_takes_the_whole_value_as_its_cell():
    s = side(src("[1, 2]", "(3,)", "4", "pytest.param([5], marks=pytest.mark.skip)", names="items",
                 body="def test_x(items):\n    assert invoice_total(items, 0.05) == sum(items)\n"))
    assert s.param_rows == (
        ParamTable(("items",), (("[1, 2]",), ("(3,)",), ("4",), ("[5]",)), (False, False, False, True)),
    )
    assert s.param_cases == 3


def test_stacked_decorators_are_separate_tables_in_decorator_order():
    s = side(
        HEAD
        + '@pytest.mark.parametrize("rate", [0.05, 0.1])\n'
        + '@pytest.mark.parametrize("items", [[50.0], [10.0]])\n'
        + "def test_x(items, rate):\n    assert invoice_total(items, rate) == 1\n"
    )
    assert [t.names for t in s.param_rows] == [("rate",), ("items",)]
    assert s.param_cases == 4


def test_an_unreadable_decorator_leaves_the_unit_with_no_tables():
    """All or nothing: a reader of the rows must see what the count counted."""
    starred = src(ROW_A, "*MORE")
    assert side(starred).param_rows == ()
    assert side(starred).param_cases == 2  # the count still counts the starred element
    wrong_width = src(ROW_A, "([10.0], 10.5, 3)")
    assert side(wrong_width).param_rows == ()
    names_not_literal = HEAD + "@pytest.mark.parametrize(NAMES, [(1, 2)])\n" + BODY
    assert side(names_not_literal).param_rows == ()
    # A non-literal value list is not counted by `param_cases` either, so it
    # is simply not a table -- not an unreadable one.
    values_not_literal = HEAD + '@pytest.mark.parametrize("items,expected", CASES)\n' + BODY
    assert side(values_not_literal).param_rows == ()
    assert side(values_not_literal).param_cases is None


# --- the delta: identity is a floor on the count -------------------------------


def test_marked_row_plus_appended_row_is_one_lost_item():
    u = unit(src(ROW_A, ROW_B), src(SKIP_A, ROW_B, NEW))
    assert u.before.param_cases == u.after.param_cases == 2  # the count sees nothing
    assert u.delta.param_cases_removed == 1
    assert u.delta.param_cases_disabled == 1
    assert message(src(ROW_A, ROW_B), src(SKIP_A, ROW_B, NEW)) == (
        "test_invoice_total_applies_tax: 1 of 2 parametrized case(s) no longer run "
        "(1 disabled, 0 deleted; live count 2 -> 2)"
    )


def test_two_marked_two_appended():
    u = unit(src(ROW_A, ROW_B, ROW_C), src(SKIP_A, SKIP_B, ROW_C, NEW, "([2.0], 2.1)"))
    assert (u.delta.param_cases_removed, u.delta.param_cases_disabled) == (2, 2)


def test_marked_without_append_keeps_the_count_and_names_the_mark():
    before, after = src(ROW_A, ROW_B), src(SKIP_A, ROW_B)
    u = unit(before, after)
    assert (u.delta.param_cases_removed, u.delta.param_cases_disabled) == (1, 1)
    assert message(before, after) == (
        "test_invoice_total_applies_tax: 1 of 2 parametrized case(s) no longer run "
        "(1 disabled, 0 deleted; live count 2 -> 1)"
    )


def test_deleted_rows_keep_the_original_message():
    before, after = src(ROW_A, ROW_B, ROW_C), src(ROW_A, ROW_C)
    u = unit(before, after)
    assert (u.delta.param_cases_removed, u.delta.param_cases_disabled) == (1, 0)
    assert message(before, after) == (
        "test_invoice_total_applies_tax: 1 parametrized case(s) deleted (3 -> 2)"
    )


def test_marked_and_deleted_together_are_told_apart():
    before, after = src(ROW_A, ROW_B, ROW_C), src(SKIP_A, ROW_C)
    u = unit(before, after)
    assert (u.delta.param_cases_removed, u.delta.param_cases_disabled) == (2, 1)
    assert message(before, after) == (
        "test_invoice_total_applies_tax: 2 of 3 parametrized case(s) no longer run "
        "(1 disabled, 1 deleted; live count 3 -> 1)"
    )


STACK_BODY = "def test_x(items, rate):\n    assert invoice_total(items, rate) == round(sum(items) * (1 + rate), 2)\n"


def stacked(*tables: str) -> str:
    return HEAD + "".join(tables) + STACK_BODY


def test_two_stacked_tables_each_marking_and_appending_lose_three_of_four():
    before = stacked(
        '@pytest.mark.parametrize("rate", [0.05, 0.1])\n',
        '@pytest.mark.parametrize("items", [[50.0, 50.0], [10.0]])\n',
    )
    after = stacked(
        '@pytest.mark.parametrize("rate", [pytest.param(0.05, marks=pytest.mark.skip), 0.1, 0.2])\n',
        '@pytest.mark.parametrize("items", [pytest.param([50.0, 50.0], marks=pytest.mark.skip), [10.0], [1.0, 1.0]])\n',
    )
    u = unit(before, after)
    assert u.before.param_cases == u.after.param_cases == 4
    # Not 2 (one row per table), not 4 (each table's loss times the other's
    # after-live rows, summed, counts the (skipped, skipped) item twice).
    assert (u.delta.param_cases_removed, u.delta.param_cases_disabled) == (3, 3)
    assert message(before, after) == (
        "test_x: 3 of 4 parametrized case(s) no longer run "
        "(3 disabled, 0 deleted; live count 4 -> 4)"
    )


def test_three_stacked_tables_lose_seven_of_eight():
    before = stacked(
        '@pytest.mark.parametrize("rate", [0.05, 0.1])\n',
        '@pytest.mark.parametrize("items", [[50.0, 50.0], [10.0]])\n',
        '@pytest.mark.parametrize("currency", ["USD", "EUR"])\n',
    ).replace("def test_x(items, rate):", "def test_x(items, rate, currency):")
    after = stacked(
        '@pytest.mark.parametrize("rate", [pytest.param(0.05, marks=pytest.mark.skip), 0.1, 0.2])\n',
        '@pytest.mark.parametrize("items", [pytest.param([50.0, 50.0], marks=pytest.mark.skip), [10.0], [1.0, 1.0]])\n',
        '@pytest.mark.parametrize("currency", [pytest.param("USD", marks=pytest.mark.skip), "EUR", "GBP"])\n',
    ).replace("def test_x(items, rate):", "def test_x(items, rate, currency):")
    u = unit(before, after)
    assert u.before.param_cases == u.after.param_cases == 8
    assert (u.delta.param_cases_removed, u.delta.param_cases_disabled) == (7, 7)
    assert "7 of 8 parametrized case(s) no longer run" in message(before, after)


def test_stacked_tables_split_deleted_from_disabled():
    before = stacked(
        '@pytest.mark.parametrize("rate", [0.05, 0.1])\n',
        '@pytest.mark.parametrize("items", [[50.0, 50.0], [10.0]])\n',
    )
    after = stacked(
        '@pytest.mark.parametrize("rate", [0.1])\n',  # 0.05 deleted outright
        '@pytest.mark.parametrize("items", [pytest.param([50.0, 50.0], marks=pytest.mark.skip), [10.0], [1.0, 1.0]])\n',
    )
    u = unit(before, after)
    # 4 original items; the only one still running is (0.1, [10.0]). Of the
    # three lost, two have the deleted rate; one lost only its marked row.
    assert (u.delta.param_cases_removed, u.delta.param_cases_disabled) == (3, 1)
    assert message(before, after) == (
        "test_x: 3 of 4 parametrized case(s) no longer run "
        "(1 disabled, 2 deleted; live count 4 -> 2)"
    )


def test_a_new_decorator_does_not_hide_a_marked_row():
    before = src(ROW_A, ROW_B)
    after = (
        HEAD
        + '@pytest.mark.parametrize("rate", [0.05, 0.1])\n'
        + table(SKIP_A, ROW_B, NEW)
        + "def test_invoice_total_applies_tax(items, expected, rate):\n"
        + "    assert invoice_total(items, 0.05) == expected\n"
    )
    u = unit(before, after)
    assert (u.before.param_cases, u.after.param_cases) == (2, 4)  # the count went *up*
    assert (u.delta.param_cases_removed, u.delta.param_cases_disabled) == (1, 1)


# --- what must stay silent ---------------------------------------------------


def test_reordering_appending_id_renames_and_existing_marks_lose_nothing():
    silent = [
        (src(ROW_A, ROW_B), src(ROW_B, ROW_A)),  # whole-row reorder, multi-column
        (src(ROW_A, ROW_B), src(ROW_A, ROW_B, NEW)),  # pure append
        (src(SKIP_A, ROW_B), src(SKIP_A, ROW_B, NEW)),  # already marked, appended beside
        (
            src("pytest.param([50.0, 50.0], 105.0, id='a')", "pytest.param([10.0], 10.5, id='b')"),
            src("pytest.param([50.0, 50.0], 105.0, id='c')", "pytest.param([10.0], 10.5, id='d')"),
        ),
        (src(SKIP_A, ROW_B), src(ROW_A, ROW_B)),  # un-skipping a row
        (src(ROW_A, ROW_B), src("([50.0,50.0],105.0)", "( [10.0] , 10.5 )")),  # reformatting
    ]
    for before, after in silent:
        u = unit(before, after)
        assert (u.delta.param_cases_removed, u.delta.param_cases_disabled) == (0, 0), after


# --- the fallbacks -------------------------------------------------------------


def test_renamed_column_falls_back_to_the_count():
    """No table pairs with the before table, so the count rule is all there is."""
    before = src(ROW_A, ROW_B)
    after = HEAD + table(SKIP_A, ROW_B, NEW, names="items,want") + (
        "def test_invoice_total_applies_tax(items, want):\n    assert invoice_total(items, 0.05) == want\n"
    )
    u = unit(before, after)
    assert _param_rows_lost(u.before, u.after) is None
    assert (u.delta.param_cases_removed, u.delta.param_cases_disabled) == (0, 0)


def test_deleted_row_plus_unrelated_appended_row_is_the_count_rules_residual():
    """A vanished row cannot be told from an edited one by the rows alone, so
    the residual is left to the count rule -- and nets to zero here. Recorded
    as a residual; EXPECTATION_DEFINITION_CHANGED owns the edited-row half."""
    u = unit(src(ROW_A, ROW_B), src(ROW_B, NEW))
    assert (u.delta.param_cases_removed, u.delta.param_cases_disabled) == (0, 0)


def test_unreadable_table_on_either_side_falls_back_to_the_count():
    before, after = src(ROW_A, ROW_B), src(SKIP_A, "*MORE")
    u = unit(before, after)
    assert _param_rows_lost(u.before, u.after) is None
    # The count rule alone: the mark takes one live row away (2 -> 1) and,
    # without pairing, nothing can say it was a mark rather than a deletion.
    assert (u.delta.param_cases_removed, u.delta.param_cases_disabled) == (1, 0)
    u = unit(src(ROW_A, "*MORE"), src(ROW_B))
    assert (u.delta.param_cases_removed, u.delta.param_cases_disabled) == (1, 0)  # count: 2 -> 1


def test_parametrize_removed_entirely_keeps_the_count_rule():
    u = unit(src(ROW_A, ROW_B), HEAD + "def test_invoice_total_applies_tax():\n    assert invoice_total([10.0], 0.05) == 10.5\n")
    assert (u.delta.param_cases_removed, u.delta.param_cases_disabled) == (1, 0)


def test_older_payload_without_rows_reads_as_no_tables():
    old = types.SimpleNamespace(param_cases=2)
    assert param_tables(old) == ()
    assert param_tables(None) == ()
    assert _param_rows_lost(old, side(src(SKIP_A, ROW_B, NEW))) is None


# --- the shared reader ---------------------------------------------------------


def test_reader_accepts_dataclass_dict_and_triple_spellings():
    want = ParamTable(("a", "b"), (("1", "2"), ("3", "4")), (False, True))
    for spelling in (
        want,
        {"names": ["a", "b"], "rows": [["1", "2"], ["3", "4"]], "disabled": [False, True]},
        (["a", "b"], [("1", "2"), ["3", "4"]], (False, True)),
    ):
        assert param_tables(UnitSide(span=(0, 0), param_rows=(spelling,))) == (want,)


def test_reader_rejects_shapes_it_cannot_trust():
    good = {"names": ["a", "b"], "rows": [["1", "2"]], "disabled": [False]}
    bad = [
        {"names": ["a", "b"], "rows": [["1"]], "disabled": [False]},  # width
        {"names": ["a", "b"], "rows": [["1", "2"]], "disabled": []},  # flags do not line up
        {"names": ["a", "b"], "rows": [["1", 2]], "disabled": [False]},  # cell is not text
        {"names": ["a", "b"], "rows": [["1", "2"]], "disabled": [1]},  # flag is not a bool
        {"names": [], "rows": [], "disabled": []},  # no argnames
        {"names": "a,b", "rows": [["1", "2"]], "disabled": [False]},  # names is one string
        {"names": ["a", "b"], "rows": ["12"], "disabled": [False]},  # row is one string
        {"names": ["a", "b"], "rows": [["1", "2"]]},  # missing key
        ("a", "b"),  # not a triple
        7,
    ]
    for entry in bad:
        assert param_tables(UnitSide(span=(0, 0), param_rows=(entry,))) == (), entry
        # One bad entry poisons the side: the readable half is not an answer.
        assert param_tables(UnitSide(span=(0, 0), param_rows=(good, entry))) == (), entry
    assert param_tables(UnitSide(span=(0, 0), param_rows="not a list")) == ()


def _rebuild(ir: IR) -> IR:
    """The JSON-array form of the IR back into dataclasses, as a consumer would."""
    payload = json.loads(json.dumps(to_jsonable(ir)))
    files = []
    for data in payload.pop("files"):
        units = []
        for u in data.pop("units"):
            for s in ("before", "after"):
                if u[s] is not None:
                    u[s]["assertions"] = [Assertion(**a) for a in u[s]["assertions"]]
                    u[s] = UnitSide(**u[s])
            if u["delta"] is not None:
                u["delta"]["assertion_pairs"] = [AssertionPair(**p) for p in u["delta"]["assertion_pairs"]]
                u["delta"] = UnitDelta(**u["delta"])
            units.append(Unit(**u))
        data.pop("change_evidence", None)
        files.append(FileIR(**data, units=units))
    payload.pop("globals")
    return IR(**payload, files=files, globals=DiffGlobals())


def test_json_round_trip_pairs_the_same_rows_and_reports_the_same_finding():
    file = align(src(ROW_A, ROW_B), src(SKIP_A, ROW_B, NEW))
    native = IR(base="b", head="a", files=[file], globals=DiffGlobals())
    rebuilt = _rebuild(native)
    b, a = rebuilt.files[0].units[0].before, rebuilt.files[0].units[0].after
    assert isinstance(a.param_rows[0], dict)  # lists and dicts, not dataclasses
    assert param_tables(a) == param_tables(file.units[0].after)
    assert _param_rows_lost(b, a) == _param_rows_lost(file.units[0].before, file.units[0].after) == (1, 1)
    native_findings, rebuilt_findings = detect(native), detect(rebuilt)
    assert [(f.rule, f.message, f.fingerprint) for f in rebuilt_findings] == [
        (f.rule, f.message, f.fingerprint) for f in native_findings
    ]
    assert native_findings and native_findings[0].shape == "param_cases_removed"

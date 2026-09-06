"""Parametrize expectations keyed by input, not by column text (F-060, F-067).

`EXPECTATION_DEFINITION_CHANGED` used to compare a consumed column as one
string of cells and required equal lengths, so rewriting one answer while
appending a row was silent (F-060), and it picked its candidate columns from
`param_columns`, which never holds the cells after the first of a
`pytest.param(...)` row (F-067). These tests pin the row-keyed comparison
and its fallbacks directly, plus the JSON-array round trip of the rows.
"""

import datetime
import json
import pathlib

from checkwash.cases import case_snapshot, case_to_changes, parse_case
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.detectors.expectation_definition import (
    _column_expectation_edited,
    _column_values_edited,
    _param_names,
    detect,
)
from checkwash.engine import analyze
from checkwash.gitio.snapshot import search_source_mapping
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
    to_jsonable,
)

CASES = pathlib.Path(__file__).parent / "cases"
SEP = "\x1f"


def side(*tables: ParamTable, columns: dict[str, str] | None = None) -> UnitSide:
    return UnitSide(span=(0, 0), param_rows=tables, param_columns=columns or {})


def table(names: str, *rows: tuple[str, ...], disabled: tuple[bool, ...] | None = None) -> ParamTable:
    names_t = tuple(names.split(","))
    return ParamTable(names_t, tuple(rows), disabled or tuple(False for _ in rows))


A, B, C = ("[50.0, 50.0]", "105.0"), ("[10.0]", "10.5"), ("[1.0, 1.0]", "2.1")


def edited(before: ParamTable, after: ParamTable, name: str = "expected") -> bool:
    return _column_expectation_edited(name, side(before), side(after))


# --- multi-column tables: keyed by the other cells ------------------------------


def test_rewritten_answer_is_an_edit_even_with_a_row_appended():
    assert edited(table("items,expected", A, B), table("items,expected", ("[50.0, 50.0]", "100.0"), B, C))


def test_pure_append_and_whole_row_reorder_are_not_edits():
    assert not edited(table("items,expected", A, B), table("items,expected", A, B, C))
    assert not edited(table("items,expected", A, B), table("items,expected", B, A))
    assert not edited(table("items,expected", A, B), table("items,expected", C, B, A))


def test_swapped_answers_are_an_edit_although_the_multiset_is_preserved():
    assert edited(table("items,expected", ("[1]", "2"), ("[2]", "4")),
                  table("items,expected", ("[1]", "4"), ("[2]", "2"), ("[3]", "6")))


def test_duplicate_inputs_compare_as_a_multiset():
    two = table("items,expected", ("[1]", "2"), ("[1]", "2"))
    assert edited(two, table("items,expected", ("[1]", "2"), ("[1]", "3")))
    assert not edited(two, table("items,expected", ("[1]", "2"), ("[1]", "2"), ("[1]", "2")))
    # One copy gone is a deleted item (TEST_DISABLED's event); the other keeps its answer.
    assert not edited(two, table("items,expected", ("[1]", "2")))


def test_a_deleted_or_re_keyed_row_is_not_this_rules_event():
    assert not edited(table("items,expected", A, B), table("items,expected", B))
    # Editing the *input* changes the key: the old pairing is simply no longer tested.
    assert not edited(table("items,expected", A, B), table("items,expected", ("[60.0, 40.0]", "105.0"), B, C))


def test_a_marked_row_keeps_its_cells_and_is_not_an_edit():
    marked = table("items,expected", A, B, C, disabled=(True, False, False))
    assert not edited(table("items,expected", A, B), marked)


def test_middle_column_is_keyed_by_both_neighbours():
    before = table("items,expected,rate", ("[50.0, 50.0]", "105.0", "0.05"), ("[50.0, 50.0]", "110.0", "0.1"))
    assert edited(before, table("items,expected,rate", ("[50.0, 50.0]", "100.0", "0.05"), ("[50.0, 50.0]", "110.0", "0.1")))
    assert not edited(before, table("items,expected,rate", ("[50.0, 50.0]", "110.0", "0.1"), ("[50.0, 50.0]", "105.0", "0.05")))


# --- single-column tables: identity is position, kept conservative ------------


def test_single_column_edit_is_an_edit_and_insertion_is_not():
    assert edited(table("expected", ("105.0",)), table("expected", ("100.0",)))
    assert not edited(table("expected", ("105.0",), ("10.5",)), table("expected", ("105.0",), ("2.1",), ("10.5",)))
    assert not edited(table("expected", ("105.0",)), table("expected", ("105.0",), ("100.0",)))


def test_single_column_reorder_stays_an_edit_by_contract():
    """No input to key on, so position is identity: a reshuffle is not credited.

    This is the judgement the column rule made for equal lengths, extended to
    additions -- not a claim that every reorder of a single column is honest."""
    assert edited(table("expected", ("105.0",), ("10.5",)), table("expected", ("10.5",), ("105.0",)))


# --- fallbacks ---------------------------------------------------------------------


def test_without_rows_the_column_rule_decides_and_needs_both_columns():
    cols_b, cols_a = {"expected": SEP.join(["105.0", "10.5"])}, {"expected": SEP.join(["100.0", "10.5"])}
    assert _column_expectation_edited("expected", side(columns=cols_b), side(columns=cols_a))
    assert _column_values_edited(cols_b["expected"], cols_a["expected"])
    longer = {"expected": SEP.join(["100.0", "10.5", "2.1"])}
    assert not _column_expectation_edited("expected", side(columns=cols_b), side(columns=longer))
    assert not _column_expectation_edited("expected", side(columns=cols_b), side())
    assert not _column_expectation_edited("expected", side(), side(columns=cols_a))


def test_rows_on_one_side_only_fall_back_to_the_columns():
    cols = {"expected": SEP.join(["105.0", "10.5"])}
    rows = table("items,expected", ("[50.0, 50.0]", "100.0"), B, C)
    assert not _column_expectation_edited("expected", side(columns=cols), side(rows, columns={"expected": SEP.join(["100.0", "10.5", "2.1"])}))


def test_tables_with_different_argnames_or_a_name_bound_twice_fall_back():
    b = side(table("items,expected", A, B), columns={"expected": SEP.join(["105.0", "10.5"])})
    renamed = side(table("items,want", ("[50.0, 50.0]", "100.0"), B, C), columns={"want": SEP.join(["100.0", "10.5", "2.1"])})
    assert not _column_expectation_edited("expected", b, renamed)
    twice = side(
        table("items,expected", ("[50.0, 50.0]", "100.0"), B, C),
        table("expected", ("1",)),
        columns={"expected": SEP.join(["100.0", "10.5", "2.1", "1"])},
    )
    assert not _column_expectation_edited("expected", b, twice)  # columns: 2 vs 4 cells


def test_candidate_names_come_from_rows_as_well_as_columns():
    wrapped = side(table("items,expected", A, B), columns={"items": SEP.join(["[50.0, 50.0]", "[10.0]"])})
    assert _param_names(wrapped) == {"items", "expected"}
    assert _param_names(side()) == set()
    assert _param_names(side(columns={"expected": "1"})) == {"expected"}


# --- the JSON-array form of the rows -----------------------------------------------


def _run(name: str):
    case = parse_case((CASES / f"{name}.gwcase").read_text(encoding="utf-8"))
    snapshot = case_snapshot(case)
    return analyze(
        case_to_changes(case), Config(), Contract(), [], datetime.date(2026, 1, 1),
        root_reader=snapshot.get,
        root_searcher=lambda needles: search_source_mapping(snapshot, needles),
    )


def _rebuild(ir: IR) -> IR:
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


def test_json_round_trip_reports_the_same_expectation_findings():
    for name in ("param_row_all_wrapped_cell_edit_pos", "param_row_cell_edit_appended_pos", "param_row_moved_neg"):
        ir, _findings, _verdict = _run(name)
        rebuilt = _rebuild(ir)
        after = rebuilt.files[0].units[0].after
        assert after.param_rows and isinstance(after.param_rows[0], dict)  # arrays and dicts, not dataclasses
        native, again = detect(ir), detect(rebuilt)
        assert [(f.rule, f.message, f.fingerprint) for f in again] == [
            (f.rule, f.message, f.fingerprint) for f in native
        ], name
        assert bool(native) == name.endswith("_pos"), name

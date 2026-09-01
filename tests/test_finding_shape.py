"""E2: gating reads Finding.shape, never English message text."""

from __future__ import annotations

import datetime
from pathlib import Path

from checkwash.cases import case_to_changes, parse_case
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.findings import (
    SHAPE_MARKER_ADDED,
    SHAPE_PARAM_CASES_REMOVED,
    SHAPE_UNIT_REMOVED,
    Finding,
)
from checkwash.gating import _prod_removal_shape
from checkwash.ir.model import Unit, UnitDelta, UnitSide

ROOT = Path(__file__).resolve().parent.parent
CASES = Path(__file__).resolve().parent / "cases"


def test_gating_source_does_not_parse_disabled_message():
    src = (ROOT / "src" / "checkwash" / "gating.py").read_text(encoding="utf-8")
    assert "not in f.message" not in src
    assert "in f.message" not in src


def test_prod_removal_reads_shape_not_message():
    unit = Unit(
        kind="test_function",
        qualname="test_x",
        match="by_name",
        before=UnitSide(span=(0, 1)),
        after=UnitSide(span=(0, 1)),
        delta=UnitDelta(param_cases_removed=1, markers_added=["skip"]),
    )
    marker = Finding(
        rule="TEST_DISABLED",
        severity="warn",
        message="rewritten copy with no substring to match",
        path="tests/test_x.py",
        unit="test_x",
        shape=SHAPE_MARKER_ADDED,
    )
    param = Finding(
        rule="TEST_DISABLED",
        severity="warn",
        message="disabling marker added (must not matter)",
        path="tests/test_x.py",
        unit="test_x",
        shape=SHAPE_PARAM_CASES_REMOVED,
    )
    assert _prod_removal_shape(marker, unit) is False
    assert _prod_removal_shape(param, unit) is True


def _findings(name: str) -> list[Finding]:
    case = parse_case((CASES / name).read_text(encoding="utf-8"))
    _ir, findings, _verdict = analyze(
        case_to_changes(case),
        Config(),
        Contract(),
        [],
        datetime.date(2026, 1, 1),
    )
    return [f for f in findings if f.rule == "TEST_DISABLED"]


def test_disabled_detector_sets_marker_shape():
    found = _findings("prod_symbol_removed_marker_pos.gwcase")
    assert found
    assert all(f.shape == SHAPE_MARKER_ADDED for f in found)


def test_disabled_detector_sets_unit_removed_shape():
    found = _findings("class_rename_out_of_collection_pos.gwcase")
    assert found
    assert all(f.shape == SHAPE_UNIT_REMOVED for f in found)

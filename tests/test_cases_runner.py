"""Golden runner: every .gwcase exercises the full pipeline (SPEC test layer 1)."""

import datetime
import pathlib

import pytest

from greenwash.cases import case_to_changes, match_expectations, parse_case
from greenwash.config import Config
from greenwash.contract import Contract, parse_contract
from greenwash.engine import analyze
from greenwash.pyenv import known_baseline

CASES = sorted((pathlib.Path(__file__).parent / "cases").glob("*.gwcase"))
TODAY = datetime.date(2026, 1, 1)


@pytest.mark.parametrize("case_path", CASES, ids=lambda p: p.stem)
def test_case(case_path):
    case = parse_case(case_path.read_text(encoding="utf-8"))
    contract = parse_contract(case.task) if case.task else Contract()
    known = (known_baseline() | set(case.env)) if case.env is not None else None
    ir, findings, _verdict = analyze(
        case_to_changes(case), Config(), contract, [], TODAY, known_modules=known
    )
    visible = [f for f in findings if not f.allowlisted]
    mismatch = match_expectations(case.expect, visible)
    assert mismatch is None, f"{case_path.name}: {mismatch}"


def test_cases_exist():
    assert len(CASES) >= 10, "fixture corpus shrank — pos/neg cases are the FP defence line"

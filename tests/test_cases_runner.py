"""Golden runner: every .gwcase exercises the full pipeline (SPEC test layer 1)."""

import datetime
import pathlib

import pytest

from checkwash.cases import case_to_changes, match_expectations, parse_case
from checkwash.config import Config
from checkwash.contract import Contract, parse_contract
from checkwash.engine import analyze
from checkwash.pyenv import known_baseline

CASES = sorted((pathlib.Path(__file__).parent / "cases").glob("*.gwcase"))
TODAY = datetime.date(2026, 1, 1)


@pytest.mark.parametrize("case_path", CASES, ids=lambda p: p.stem)
def test_case(case_path):
    case = parse_case(case_path.read_text(encoding="utf-8"))
    contract = parse_contract(case.task) if case.task else Contract()
    known = (known_baseline() | set(case.env)) if case.env is not None else None
    head = {p: c.encode("utf-8") for p, c in case.head.items()}
    ir, findings, _verdict = analyze(
        case_to_changes(case), Config(), contract, [], TODAY, known_modules=known,
        head_reader=head.get if head else None,
        head_searcher=(
            (lambda needles: [p for p, data in sorted(head.items())
                              if any(n.encode("utf-8") in data for n in needles)])
            if head else None
        ),
    )
    visible = [f for f in findings if not f.allowlisted]
    mismatch = match_expectations(case.expect, visible)
    assert mismatch is None, f"{case_path.name}: {mismatch}"


def test_cases_exist():
    assert len(CASES) >= 10, "fixture corpus shrank — pos/neg cases are the FP defence line"


def test_expectation_definition_package_unrelated_has_no_credit():
    """Subset matching cannot say 'PACKAGE_REPAIR is absent'; pin it here.

    A modified symbol in a package the test does not import must not mark
    EXPECTATION_DEFINITION_CHANGED. The paired *_neg fixture requires the
    mark when the import reaches the package.
    """
    case_path = pathlib.Path(__file__).parent / "cases" / (
        "expectation_definition_package_unrelated_pos.gwcase"
    )
    case = parse_case(case_path.read_text(encoding="utf-8"))
    _ir, findings, _verdict = analyze(
        case_to_changes(case), Config(), Contract(), [], TODAY
    )
    hits = [f for f in findings if f.rule == "EXPECTATION_DEFINITION_CHANGED"]
    assert hits, "rule did not fire"
    credits = {"PACKAGE_REPAIR", "REPAIR_EVIDENCE", "DEPENDENCY_DRIFT"}
    assert not credits.intersection(hits[0].deescalators), hits[0].deescalators

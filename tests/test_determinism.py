"""Determinism: identical inputs must yield byte-identical findings JSON (SPEC §8)."""

import datetime
import pathlib

from greenwash.cases import case_to_changes, parse_case
from greenwash.config import Config
from greenwash.contract import Contract, parse_contract
from greenwash.engine import analyze
from greenwash.report.jsonout import findings_to_json, ir_to_json

CASES = sorted((pathlib.Path(__file__).parent / "cases").glob("*.gwcase"))
TODAY = datetime.date(2026, 1, 1)


def _run_corpus() -> str:
    chunks = []
    for case_path in CASES:
        case = parse_case(case_path.read_text(encoding="utf-8"))
        contract = parse_contract(case.task) if case.task else Contract()
        ir, findings, verdict = analyze(case_to_changes(case), Config(), contract, [], TODAY)
        chunks.append(findings_to_json(ir, findings, verdict))
        chunks.append(ir_to_json(ir))
    return "".join(chunks)


def test_double_run_byte_identical():
    assert _run_corpus() == _run_corpus()


def test_no_timestamps_in_findings():
    out = _run_corpus()
    assert "duration" not in out
    assert "timestamp" not in out

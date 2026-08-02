"""`greenwash demo` must stay green and packaged.

The demo is a launch asset: it has to work from a clean pipx install, and
every tampering case in it must still block. Both are gates, not hopes.
"""

import datetime
import io

from greenwash.cases import case_to_changes, parse_case
from greenwash.config import Config
from greenwash.contract import Contract, parse_contract
from greenwash.demo import _load_cases, run
from greenwash.engine import analyze

TODAY = datetime.date(2026, 1, 1)


def test_cases_are_packaged():
    cases = _load_cases()
    # Accessed via importlib.resources, i.e. the way a wheel install sees them.
    assert len(cases) >= 8, f"only {len(cases)} demo cases found via package resources"


def test_every_tampering_case_blocks_and_honest_passes():
    for name, text in _load_cases():
        case = parse_case(text)
        contract = parse_contract(case.task) if case.task else Contract()
        _ir, findings, verdict = analyze(case_to_changes(case), Config(), contract, [], TODAY)
        if case.expect:
            assert verdict == "block", f"{name} should block but did not"
        else:
            assert verdict == "pass", f"{name} should pass but did not"


def test_run_reports_all_blocked():
    buf = io.StringIO()
    code = run(stream=buf)
    out = buf.getvalue()
    assert code == 0
    assert "0 network calls" in out and "0 LLM" in out
    assert "UNEXPECTED" not in out

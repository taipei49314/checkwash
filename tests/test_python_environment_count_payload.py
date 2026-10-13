"""Additive source-only public witness boundary controls; NOT_RUN."""
import datetime

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.detectors.assert_weakened import detect
from checkwash.engine import FileChange, analyze
from checkwash.ir.model import to_jsonable

PATH = "tests/test_total.py"
GUARD = 'os.environ.get("CW_RUN_TOTAL") == "1"'
ORACLE = "assert total() == 3"
HEADER = "import os\n\ndef total():\n    return 2\n\ndef test_total():\n"
WRAPPED = "    if " + GUARD + ":\n        " + ORACLE
MIXED = WRAPPED + "\n    " + ORACLE
ARMS = WRAPPED + "\n    else:\n        " + ORACLE


def parsed_unit(count=1, body=WRAPPED):
    before = (HEADER + ("    " + ORACLE + "\n") * count).encode()
    after = (HEADER + body + "\n").encode()
    ir, _findings, _verdict = analyze(
        [FileChange(PATH, "modified", before, after)],
        Config(), Contract(), [], datetime.date(2026, 10, 13))
    unit, = ir.files[0].units
    return ir, unit


@pytest.mark.parametrize("value", [
    42, {}, [], [0, 1, None],
    [True, 1, None, None], [0, False, None, None],
    [-1, 1, None, None], [0, -1, None, None],
    [0, 1, None, [0, 1]], [0, 1, GUARD, None],
    [0, 1, GUARD, [1, 0]], [0, 1, GUARD, [False, 1]],
    [0, 1, 4, [0, 1]], [0, 1, GUARD, [0, 1, 2]],
    [0, 1, GUARD, [-1, 1]], [0, 1, GUARD, [0, 1.5]],
])
@pytest.mark.parametrize("side", ["before", "after"])
def test_malformed_public_witness_retains_pair_rule_fallback(value, side):
    ir, unit = parsed_unit()
    assertions = unit.before.assertions if side == "before" else unit.after.assertions
    setattr(assertions[0], "environment_obligation_count", value)
    finding, = detect(ir)
    assert (finding.rule, finding.severity) == ("ASSERT_WEAKENED", "warn")
    assert finding.after.text == GUARD
    assert "existing assertion now depends on environment guard" in finding.message


@pytest.mark.parametrize("side", ["before", "after"])
def test_default_unknown_witness_retains_pair_rule_fallback(side):
    ir, unit = parsed_unit()
    assertions = unit.before.assertions if side == "before" else unit.after.assertions
    assertions[0].environment_obligation_count = None
    finding, = detect(ir)
    assert finding.after.text == GUARD
    assert "existing assertion now depends on environment guard" in finding.message


@pytest.mark.parametrize("count,body,losses", [(1, MIXED, 0), (2, MIXED, 1), (2, ARMS, 1)])
def test_valid_json_lists_keep_group_spending_and_actual_guard(count, body, losses):
    ir, unit = parsed_unit(count, body)
    for assertion in unit.before.assertions + unit.after.assertions:
        value = to_jsonable(assertion)["environment_obligation_count"]
        assert type(value) is list and len(value) == 4
        setattr(assertion, "environment_obligation_count", value)
    findings = detect(ir)
    assert len(findings) == losses
    if losses:
        finding, = findings
        assert finding.after.text == GUARD
        assert "1 existing assertion evaluation(s)" in finding.message

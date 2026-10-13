"""Source-only additive proposals; no native result is asserted here."""
import datetime

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.detectors.assert_weakened import detect
from checkwash.engine import FileChange, analyze
from checkwash.frontends.python.frontend import parse_python
from checkwash.ir.model import Assertion, to_jsonable

PATH = "tests/test_total.py"
GUARD = 'os.environ.get("CW_RUN_TOTAL") == "1"'
ORACLE = "assert total() == 3"
HEADER = ("import os\n\ncalls = 0\ndef total():\n    global calls\n"
          "    calls += 1\n    return 3 if calls == 1 else 2\n\ndef test_total():\n")


def source(body):
    return (HEADER + body + "\n").encode()


def direct(n):
    return "\n".join("    " + ORACLE for _ in range(n))


def arms(n):
    arm = "\n".join("        " + ORACLE for _ in range(n))
    return "    if " + GUARD + ":\n" + arm + "\n    else:\n" + arm


WRAPPED = "    if " + GUARD + ":\n        " + ORACLE
MIXED = [WRAPPED + "\n" + direct(1), direct(1) + "\n" + WRAPPED]


def outcome(before, after):
    return analyze([FileChange(PATH, "modified", source(before), source(after))],
                   Config(), Contract(), [], datetime.date(2026, 10, 13))


@pytest.mark.parametrize("body", [arms(1), *MIXED])
def test_two_old_evaluations_cannot_borrow_one_guaranteed_copy(body):
    ir, findings, verdict = outcome(direct(2), body)
    assert verdict == "block"
    finding, = findings
    assert (finding.rule, finding.severity) == ("ASSERT_WEAKENED", "high")
    assert finding.after.text == GUARD
    assert source(body).decode()[slice(*finding.after.span)] == GUARD
    assert "1 existing assertion evaluation(s)" in finding.message
    raw, = detect(ir)
    assert raw.severity == "warn" and raw.strength_after is None
    unit, = ir.files[0].units
    assert unit.delta.assertions_removed == []
    assert len(unit.delta.assertion_pairs) == 2
    assert {a.environment_obligation_count[1] for a in unit.before.assertions} == {2}
    assert {a.environment_obligation_count[1] for a in unit.after.assertions} == {1}
    # The legacy presence-credit fields remain unchanged even on the direct copy.
    assert all(a.unconditional_obligation for a in unit.after.assertions)
    assert all(a.environment_guard is None for a in unit.after.assertions)


@pytest.mark.parametrize("old_count,body", [
    (1, arms(1)), (1, MIXED[0]), (1, MIXED[1]),
    (2, arms(2)), (2, direct(2)),
    (2, WRAPPED + "\n" + direct(2)),
    (2, direct(2) + "\n" + WRAPPED),
])
def test_credit_is_grouped_without_changing_normal_orders(old_count, body):
    _ir, findings, verdict = outcome(direct(old_count), body)
    assert (findings, verdict) == ([], "pass")


@pytest.mark.parametrize("body", [arms(1), *MIXED])
def test_whitespace_equivalent_old_copies_share_the_same_demand(body):
    old = "    assert total() == 3\n    assert total()  ==  3"
    _ir, findings, verdict = outcome(old, body)
    assert verdict == "block"
    finding, = findings
    assert finding.after.text == GUARD


@pytest.mark.parametrize("body", [arms(2), direct(2), *MIXED])
def test_unchanged_normal_binding_epoch_does_not_lose_credit(body):
    prefix = "    value = 3\n"
    old_count = 1 if body in MIXED else 2
    _ir, findings, verdict = outcome(prefix + direct(old_count), prefix + body)
    assert (findings, verdict) == ([], "pass")


def test_one_removed_copy_and_one_guarded_copy_have_distinct_events():
    ir, findings, verdict = outcome(direct(2), WRAPPED)
    assert verdict == "block"
    assert [f.rule for f in findings].count("ASSERT_WEAKENED") == 1
    assert [f.rule for f in findings].count("ASSERT_REMOVED") == 1
    assert len(detect(ir)) == 1


def test_after_credit_cannot_be_spent_again_by_a_second_old_epoch():
    old = direct(1) + "\n    touch()\n" + direct(1)
    ir, findings, verdict = outcome(old, MIXED[0])
    assert verdict == "block"
    finding, = findings
    assert finding.rule == "ASSERT_WEAKENED" and finding.after.text == GUARD
    unit, = ir.files[0].units
    assert {a.environment_obligation_count[0] for a in unit.before.assertions} == {0, 1}
    assert len(unit.delta.assertion_pairs) == 2
    assert unit.delta.assertions_removed == []


def test_ordinary_deep_assertion_count_uses_no_structural_key(monkeypatch):
    from checkwash.frontends.python import environment_obligations

    def forbidden_dump(_node):
        raise AssertionError("ordinary count must not request a structural key")

    monkeypatch.setattr(environment_obligations, "stable_dump", forbidden_dump)
    expression = "check(" + " + ".join(["value"] * 350) + ")"
    parsed = parse_python(collect_tests=True, data=source("    assert " + expression))
    assert parsed.parse_ok
    unit, = parsed.units
    assertion, = unit.side.assertions
    assert assertion.environment_obligation_count == (0, 1, None, None)


def test_count_witness_retains_real_guard_on_outside_copy():
    parsed = parse_python(collect_tests=True, data=source(MIXED[0]))
    assert parsed.parse_ok
    unit, = parsed.units
    outside = unit.side.assertions[-1]
    assert outside.environment_guard is None
    epoch, count, guard, span = outside.environment_obligation_count
    assert (epoch, count, guard) == (0, 1, GUARD)
    assert source(MIXED[0]).decode()[slice(*span)] == GUARD
    payload = to_jsonable(outside)["environment_obligation_count"]
    assert type(payload) is list and len(payload) == 4
    assert type(payload[0]) is int and type(payload[1]) is int
    assert type(payload[2]) is str and type(payload[3]) is list


def test_legacy_assertion_defaults_to_unknown_count():
    assertion = Assertion("a0", "truthy", None, "assert value", (0, 12))
    assert assertion.environment_obligation_count is None
    assert to_jsonable(assertion)["environment_obligation_count"] is None

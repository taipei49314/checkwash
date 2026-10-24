"""#419's first-stage Python broad-except candidate (D-176).

These new expectations do not restore D-141's deleted five-rule refusal.
All input programs are source data, not runtime-qualified repair examples.
"""
import datetime
from pathlib import Path

import pytest

from checkwash.allowlist import AllowEntry
from checkwash.cases import case_to_changes, parse_case
from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.findings import Finding
from checkwash.gating import OPAQUE_REFUSED_RULES, apply_gates
from checkwash.ir.model import DiffGlobals, FileIR, IR

TODAY = datetime.date(2026, 10, 23)
BEFORE = b"def test_oracle():\n    value = 2\n    assert value == 2\n"
AFTER = (
    b"def test_oracle():\n    value = 2\n"
    b"    try:\n        assert value == 2\n"
    b"    except Exception:\n        pass\n"
)
TEMPLATE = FileChange(
    "app/templates/status.html", "modified",
    b"<!-- status -->\n<p>{{ value }}</p>\n",
    b"<!-- status, presentation note -->\n<p>{{ value }}</p>\n",
)


def run(*changes, contract=None, entries=()):
    return analyze(list(changes), Config(), contract or Contract(), list(entries), TODAY)


def broad(findings):
    return [finding for finding in findings if finding.rule == "BROAD_EXCEPT_ADDED"]


@pytest.mark.parametrize("path", [
    "tests/test_sample.py",
    "tests/golden/test_sample.py",  # snapshot role plus Python test obligations
])
def test_python_broad_handler_rejects_template_credit(path):
    ir, findings, verdict = run(FileChange(path, "modified", BEFORE, AFTER), TEMPLATE)
    hit, = broad(findings)
    assert ir.globals.prod_opaque_change is True
    assert hit.unit is None
    assert (hit.severity, hit.escalators, hit.deescalators) == (
        "high", ["OPAQUE_PROD_CHANGE_NOT_EVIDENCE"], [])
    assert verdict == "block"


@pytest.mark.parametrize("opaque", [
    FileChange("app/runtime.js", "modified", b"// note\nexport const x = 1;\n",
               b"// revised note\nexport const x = 1;\n"),
    FileChange("src/core.c", "modified", b"/* note */\nint value(void) { return 1; }\n",
               b"/* revised note */\nint value(void) { return 1; }\n"),
    # A non-comment implementation edit; no claim of a runtime-qualified honest fix.
    FileChange("src/core.c", "modified", b"int value(void) { return 1; }\n",
               b"int value(void) { return 2; }\n"),
])
def test_opaque_content_kind_does_not_change_the_narrow_credit_rule(opaque):
    ir, findings, verdict = run(FileChange("tests/test_sample.py", "modified", BEFORE, AFTER), opaque)
    hit, = broad(findings)
    assert ir.globals.prod_opaque_change is True
    assert (hit.severity, hit.escalators, hit.deescalators) == (
        "high", ["OPAQUE_PROD_CHANGE_NOT_EVIDENCE"], [])
    assert verdict == "block"


def test_conftest_broad_handler_rejects_the_same_credit():
    before = b"def pytest_configure(config):\n    assert config\n"
    after = b"def pytest_configure(config):\n    try:\n        assert config\n    except Exception:\n        pass\n"
    _ir, findings, verdict = run(FileChange("tests/conftest.py", "modified", before, after), TEMPLATE)
    hit, = broad(findings)
    assert hit.unit is None
    assert (hit.severity, hit.escalators, hit.deescalators) == (
        "high", ["OPAQUE_PROD_CHANGE_NOT_EVIDENCE"], [])
    assert verdict == "block"


def test_without_production_the_existing_reason_remains():
    _ir, findings, verdict = run(FileChange("tests/test_sample.py", "modified", BEFORE, AFTER))
    hit, = broad(findings)
    assert (hit.severity, hit.escalators) == ("high", ["NO_PROD_CHANGE_IN_DIFF"])
    assert verdict == "block"


def test_production_handler_does_not_join_oracle_refusal():
    before = b"def compute(value):\n    assert value\n"
    after = b"def compute(value):\n    try:\n        assert value\n    except Exception:\n        pass\n"
    _ir, findings, verdict = run(FileChange("app/core.py", "modified", before, after), TEMPLATE)
    hit, = broad(findings)
    assert (hit.severity, hit.escalators, hit.deescalators) == ("warn", [], [])
    assert verdict == "pass"


@pytest.mark.parametrize("case_name, rule", [
    ("assert_weakened_pos", "ASSERT_WEAKENED"),
    ("assert_removed_pos", "ASSERT_REMOVED"),
    ("aliased_skip_marker_pos", "TEST_DISABLED"),
    ("tolerance_loosened_pos", "TOLERANCE_LOOSENED"),
])
def test_other_former_refusal_rules_keep_opaque_credit(case_name, rule):
    # Reuse unchanged source pairs, not their expected labels. Adding an
    # existing opaque edit must keep D-171 for each former member separately.
    path = Path(__file__).parent / "cases" / f"{case_name}.gwcase"
    case = parse_case(path.read_text(encoding="utf-8"))
    _ir, findings, verdict = run(*case_to_changes(case), TEMPLATE)
    hit, = [finding for finding in findings if finding.rule == rule]
    assert hit.unit is not None
    assert (hit.severity, hit.escalators, hit.deescalators) == (
        "warn", [], ["REPAIR_EVIDENCE"])
    assert verdict == "pass"
    assert OPAQUE_REFUSED_RULES == frozenset()


@pytest.mark.parametrize("finding_unit, expected", [
    (None, ("high", ["OPAQUE_PROD_CHANGE_NOT_EVIDENCE"], [], "block")),
    ("missing_test_unit", ("warn", [], ["REPAIR_EVIDENCE"], "pass")),
])
def test_missing_lookup_is_not_a_unitless_finding(finding_unit, expected):
    # The detector currently always writes unit=None. Pin the gate boundary
    # directly so a future unresolved nonempty name cannot widen D-176.
    path = "tests/test_sample.py"
    ir = IR(
        base="base", head="head",
        files=[FileIR(path, "python", "test", "modified")],
        globals=DiffGlobals(
            prod_files_changed=["src/core.c"], prod_opaque_change=True),
    )
    hit = Finding("BROAD_EXCEPT_ADDED", "warn", "synthetic boundary", path, finding_unit)
    verdict = apply_gates(ir, [hit], Contract(), Config(), [], TODAY)
    assert (hit.severity, hit.escalators, hit.deescalators, verdict) == expected


def test_e2_remains_additive_after_the_new_e1_reason():
    _ir, findings, verdict = run(FileChange("tests/test_sample.py", "modified", BEFORE, AFTER), TEMPLATE,
                                 contract=Contract(present=True, oracle_freeze=True))
    hit, = broad(findings)
    assert hit.severity == "high"
    assert hit.escalators == ["OPAQUE_PROD_CHANGE_NOT_EVIDENCE", "ORACLE_FREEZE"]
    assert verdict == "block"


def test_explicit_active_entry_still_precedes_e2():
    change = FileChange("tests/test_sample.py", "modified", BEFORE, AFTER)
    _ir, findings, _verdict = run(change, TEMPLATE)
    hit, = broad(findings)
    entry = AllowEntry(hit.fingerprint, hit.rule, "Owned candidate boundary test",
                       "synthetic-test", "2026-10-23", "2026-10-30")
    _ir, findings, verdict = run(change, TEMPLATE, entries=[entry],
                                 contract=Contract(present=True, oracle_freeze=True))
    hit, = broad(findings)
    assert hit.allowlisted
    assert hit.escalators == []
    assert hit.deescalators == ["ALLOWLISTED"]
    assert verdict == "pass"
    # Passing an entry directly does not test CLI base/head allowlist selection.

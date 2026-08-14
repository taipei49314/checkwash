"""Every registered detector must be exercised by fixtures.

A detector with no positive fixture is an unverified claim; a detector with no
negative fixture is an unbounded false-positive risk. This gate is what keeps
"13 detectors" from meaning "13 untested functions".
"""

import datetime
import pathlib

from greenwash.cases import case_to_changes, parse_case
from greenwash.config import Config
from greenwash.contract import Contract, parse_contract
from greenwash.detectors import REGISTRY
from greenwash.engine import analyze
from greenwash.gating import RULE_ORDER
from greenwash.pyenv import known_baseline

CASES = sorted((pathlib.Path(__file__).parent / "cases").glob("*.gwcase"))
TODAY = datetime.date(2026, 1, 1)

# Emitted by gating from a GUARDRAIL_TOUCHED-role change, not a registry entry.
DERIVED_RULES = {"EXEMPTION_ADDED"}


def _all_findings():
    rules_fired = set()
    negatives = 0
    for case_path in CASES:
        case = parse_case(case_path.read_text(encoding="utf-8"))
        contract = parse_contract(case.task) if case.task else Contract()
        known = (known_baseline() | set(case.env)) if case.env is not None else None
        _ir, findings, _verdict = analyze(
            case_to_changes(case), Config(), contract, [], TODAY, known_modules=known
        )
        for f in findings:
            rules_fired.add(f.rule)
        if not case.expect:
            negatives += 1
    return rules_fired, negatives


def test_every_fixture_carries_parsed_metadata():
    """A fixture whose metadata did not parse opts out of the gate below.

    `test_every_detector_appears_in_a_negative_fixture` keys off `meta["rule"]`,
    so a case whose `=== meta ===` header was not recognised is invisible to it
    while still passing its own expectations — expectations do not read
    metadata. A single PowerShell `Set-Content -Encoding UTF8` put a BOM on the
    first line of five cases at once and did exactly that (2026-08-12);
    `parse_case` now strips it, and this is the gate that would have said so.
    """
    silent = []
    for case_path in CASES:
        case = parse_case(case_path.read_text(encoding="utf-8"))
        if "rule" not in case.meta:
            silent.append(case_path.name)
    assert not silent, f"fixtures whose metadata did not parse: {silent}"


def test_registry_rules_appear_in_rule_order():
    """Unknown rules share one sort rank and make report order unstable.

    Static review 2026-08-11 Issue 8 / E3. Derived rules (EXEMPTION_ADDED)
    may sit in RULE_ORDER without being in REGISTRY; the other direction
    is the defect.
    """
    missing = sorted(set(REGISTRY) - set(RULE_ORDER))
    assert not missing, f"REGISTRY rules missing from RULE_ORDER: {missing}"


def test_every_detector_has_a_positive_fixture():
    rules_fired, _ = _all_findings()
    missing = sorted(set(REGISTRY) - rules_fired)
    assert not missing, f"detectors with no positive fixture: {missing}"


def test_derived_rules_are_covered_too():
    rules_fired, _ = _all_findings()
    missing = sorted(DERIVED_RULES - rules_fired)
    assert not missing, f"derived rules with no fixture: {missing}"


def test_negative_fixtures_exist_in_quantity():
    _, negatives = _all_findings()
    # Negatives are the false-positive defence line; they must not lag far
    # behind the positive corpus.
    assert negatives >= 10, f"only {negatives} negative fixtures"


def test_every_detector_appears_in_a_negative_fixture():
    """Each detector must have at least one case where it does NOT fire.

    A detector with only positive fixtures is an unbounded false-positive
    risk, and SUPPRESSION_ADDED had exactly that until a reader pointed it
    out. "Appears in a negative fixture" means: the fixture exercises the
    same construct and the expectation is that nothing (or nothing from this
    rule) is reported.
    """
    exercised: set[str] = set()
    for case_path in CASES:
        case = parse_case(case_path.read_text(encoding="utf-8"))
        subject = case.meta.get("rule", "")
        if subject not in REGISTRY:
            continue
        # A negative for rule R: the fixture is *about* R and R does not
        # block in it — either nothing is expected, or R only appears
        # de-escalated.
        blocking = {
            e.get("rule")
            for e in case.expect
            if e.get("severity") in ("high", "critical")
        }
        if subject not in blocking:
            exercised.add(subject)
    missing = sorted(set(REGISTRY) - exercised - DERIVED_RULES)
    assert not missing, (
        f"detectors with no fixture proving they stay quiet: {missing}. "
        "Every detector needs a case where it does not block, or it is an "
        "unbounded false-positive risk."
    )

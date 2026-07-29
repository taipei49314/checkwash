"""Severity gating: the escalator/de-escalator table from SPEC §5.

This file IS the auditable policy. Applied in order: D2, E1, E2, D1, D3.
(D2 first because a moved assertion is conclusively benign and skips
escalation entirely; the SPEC table remains the authority on semantics.)
"""

from __future__ import annotations

import datetime

from greenwash.allowlist import AllowEntry, active_fingerprints
from greenwash.config import SEVERITY_ORDER, Config
from greenwash.contract import Contract
from greenwash.findings import Finding
from greenwash.ir.model import IR, Unit, normalize_text

ORACLE_RULES = {"ASSERT_REMOVED", "ASSERT_WEAKENED", "TEST_DISABLED", "TOLERANCE_LOOSENED"}


def _unit_index(ir: IR) -> dict[tuple[str, str], Unit]:
    index: dict[tuple[str, str], Unit] = {}
    for file in ir.files:
        for unit in file.units:
            index[(file.path, unit.qualname)] = unit
    return index


def _symbol_match(calls: tuple[str, ...], changed_symbols: list[str]) -> bool:
    call_set = set(calls)
    for sym in changed_symbols:
        if sym in call_set or sym.rsplit(".", 1)[-1] in call_set:
            return True
    return False


def _repair_evidence(unit: Unit | None, ir: IR) -> bool:
    """Did production change in a way that plausibly explains editing THIS test?

    Diff-global "some prod file changed" was the old test, and one dead line
    in any prod file disarmed the whole run (confirmed red-team finding).
    Evidence is now symbol-relevant: the test calls a changed symbol, or
    calls something that calls a changed symbol.
    """
    if ir.globals.prod_opaque_change:
        return True  # cannot reason about it — stay conservative, THREATMODEL #4
    if unit is None:
        return False
    side = unit.before or unit.after
    if side is None:
        return False
    if _symbol_match(side.calls, ir.globals.prod_symbols_changed):
        return True
    return any(name in ir.globals.prod_symbol_callers for name in side.calls)


def apply_gates(
    ir: IR,
    findings: list[Finding],
    contract: Contract,
    config: Config,
    allow_entries: list[AllowEntry],
    today: datetime.date,
) -> str:
    """Mutates findings' severity/escalators in place; returns the verdict."""
    moved = set(ir.globals.moved_assertion_texts)
    units = _unit_index(ir)
    active_allows = active_fingerprints(allow_entries, today)

    for f in findings:
        if f.fingerprint in active_allows:
            f.allowlisted = True
            f.deescalators.append("ALLOWLISTED")
            continue
        if f.rule not in ORACLE_RULES:
            continue

        unit = units.get((f.path, f.unit or ""))

        # D2 ASSERTION_MOVED: conclusively benign, skips escalation.
        if f.rule == "ASSERT_REMOVED" and f.before is not None:
            if normalize_text(f.before.text) in moved:
                f.severity = "info"
                f.deescalators.append("ASSERTION_MOVED")
                continue
        if f.rule == "TEST_DISABLED" and unit is not None and unit.after is None and unit.before is not None:
            texts = [normalize_text(a.text) for a in unit.before.assertions]
            if texts and all(t in moved for t in texts):
                f.severity = "info"
                f.deescalators.append("ASSERTION_MOVED")
                continue

        # D1 REPAIR_EVIDENCE / E1 NO_PROD_CHANGE_IN_DIFF are two sides of one
        # question: is there a production change that explains this edit?
        if _repair_evidence(unit, ir):
            f.deescalators.append("REPAIR_EVIDENCE")
        else:
            f.severity = "high"
            f.escalators.append("NO_PROD_CHANGE_IN_DIFF")

        # E2 ORACLE_FREEZE
        if contract.oracle_freeze:
            f.severity = "high"
            f.escalators.append("ORACLE_FREEZE")

    threshold = SEVERITY_ORDER[config.fail_on]
    blocking = [
        f for f in findings if not f.allowlisted and SEVERITY_ORDER[f.severity] >= threshold
    ]
    return "block" if blocking else "pass"

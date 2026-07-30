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

# Report order: most severe rule classes first within a path.
RULE_ORDER = [
    "EXEMPTION_ADDED",
    "GUARDRAIL_TOUCHED",
    "HIDDEN_UNICODE",
    "ASSERT_REMOVED",
    "ASSERT_WEAKENED",
    "TEST_DISABLED",
    "TOLERANCE_LOOSENED",
    "EXPECTED_VALUE_HARDCODED",
    "SNAPSHOT_CODE_COCHANGE",
    "CI_WORKFLOW_TOUCHED",
    "BROAD_EXCEPT_ADDED",
    "SUPPRESSION_ADDED",
    "IMPORT_UNRESOLVED",
    "SCOPE_DRIFT",
]


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


def _same_unit_rewrite(unit: Unit | None) -> bool:
    """The unit gained a NEWLY WRITTEN strong assertion alongside the removal.

    Triage cluster: private-API asserts rewritten against the public API,
    excinfo asserts folded into raises(match=...). "Newly written" is the
    load-bearing word: a unit that merely KEEPS an old assertion while the
    inconvenient one disappears is the sacrificial-cheat signature and must
    keep blocking. Compensated findings stay visible at warn.
    """
    if unit is None or unit.delta is None or unit.before is None or unit.after is None:
        return False
    if not unit.delta.assertions_removed:
        return False
    before_texts = {normalize_text(a.text) for a in unit.before.assertions}
    return any(
        a.strength is not None
        and a.strength >= 60
        and normalize_text(a.text) not in before_texts
        for a in unit.after.assertions
    )


def _oracle_mass(side) -> int:
    strong = sum(1 for a in side.assertions if a.strength is not None and a.strength >= 60)
    return strong * max(1, side.param_cases or 1)


def _file_restructured(ir: IR) -> dict[str, bool]:
    """path -> did the file's added live units replace its disappeared mass?

    Triage cluster: N tests merged into one parametrize, splits, in-file
    renames with rewrites. Oracle mass = strong assertions x parametrize rows;
    if what appeared covers what disappeared, disappearances hold at warn.
    """
    result: dict[str, bool] = {}
    for file in ir.files:
        if file.role != "test":
            continue
        gone = added = 0
        for unit in file.units:
            if unit.before is not None and unit.after is None:
                gone += _oracle_mass(unit.before)
            elif unit.after is not None and unit.before is None and not unit.after.disabled:
                added += _oracle_mass(unit.after)
        if gone:
            result[file.path] = added >= gone
    return result


_COMPAT_TOKENS = ("sys.version_info", "sys.platform", "platform.", "os.name")


def _compat_gate(unit: Unit | None) -> bool:
    """A skipif keyed on interpreter/OS version is a compat gate, not a kill."""
    if unit is None or unit.after is None:
        return False
    for m in unit.after.markers:
        if m.name.endswith("skipif") and any(tok in m.text for tok in _COMPAT_TOKENS):
            return True
    return False


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
    restructured = _file_restructured(ir)

    for f in findings:
        if f.fingerprint in active_allows:
            f.allowlisted = True
            f.deescalators.append("ALLOWLISTED")
            continue
        if f.rule not in ORACLE_RULES:
            # Non-oracle escalations from the SPEC §5 table.
            if f.rule == "EXPECTED_VALUE_HARDCODED":
                f.severity = "high"
                f.escalators.append("HARDCODE_FINGERPRINT")  # E3
            elif f.rule == "GUARDRAIL_TOUCHED":
                f.severity = "critical"
                f.escalators.append("META")  # E4
            elif f.rule == "HIDDEN_UNICODE":
                f.severity = "high"
                f.escalators.append("HIDDEN_CONTROL_CHARS")
            elif f.rule == "CI_WORKFLOW_TOUCHED" and any(
                path == f.path for path, _ in ir.globals.ci_weakening_lines
            ):
                f.severity = "high"
                f.escalators.append("CI_TEST_COMMAND_WEAKENED")
            elif f.rule == "SCOPE_DRIFT" and any(
                path == f.path and role in ("prod", "ci", "guardrail")
                for path, role in ir.globals.scope_drift
            ):
                f.severity = "high"
                f.escalators.append("OUT_OF_SCOPE_PROD_TOUCH")
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

        # Materiality (ASSERT_WEAKENED only): a 10-point slide inside the
        # exact family (e.g. assertListEqual -> assertEqual on a variable) is
        # style drift, not oracle removal — the FP sweep blocked several such
        # human commits. Material = fell by >= 30, or landed below PATTERN.
        mild_weakening = (
            f.rule == "ASSERT_WEAKENED"
            and (f.strength_drop or 0) < 30
            and (f.strength_after is None or f.strength_after >= 60)
        )

        # Compensation evidence from the triage clusters: all of these hold
        # the finding at warn (visible, allowlistable) instead of blocking.
        compensation = None
        if f.rule == "ASSERT_REMOVED" and _same_unit_rewrite(unit):
            compensation = "SAME_UNIT_REWRITE"
        elif (
            f.rule == "TEST_DISABLED"
            and unit is not None
            and unit.after is None
            and restructured.get(f.path)
        ):
            compensation = "RESTRUCTURED"
        elif f.rule == "TEST_DISABLED" and _compat_gate(unit):
            compensation = "COMPAT_GATE"

        # D1 REPAIR_EVIDENCE / E1 NO_PROD_CHANGE_IN_DIFF are two sides of one
        # question: is there a production change that explains this edit?
        if _repair_evidence(unit, ir):
            f.deescalators.append("REPAIR_EVIDENCE")
        elif compensation is not None:
            f.deescalators.append(compensation)
        elif mild_weakening:
            f.deescalators.append("MILD_WEAKENING")
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

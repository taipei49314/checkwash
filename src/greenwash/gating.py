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

ORACLE_RULES = {
    "ASSERT_REMOVED",
    "ASSERT_WEAKENED",
    "TEST_DISABLED",
    "TOLERANCE_LOOSENED",
    "EXPECTED_VALUE_CHANGED",
    # E3 used to escalate this unconditionally, which blocked the single most
    # common honest repair there is: change a constant, update its test.
    # It goes through repair evidence like every other oracle rule.
    "EXPECTED_VALUE_HARDCODED",
}

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
    "EXPECTED_VALUE_CHANGED",
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


def _file_repair_evidence(path: str, ir: IR) -> bool:
    """Repair evidence for a finding with no unit of its own (file-scoped
    rules such as BROAD_EXCEPT_ADDED): does ANY unit in the file have it?"""
    for file in ir.files:
        if file.path != path:
            continue
        for unit in file.units:
            if _repair_evidence(unit, ir):
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
    return any(_is_real_assertion(a) and normalize_text(a.text) not in before_texts
               for a in unit.after.assertions)


def _is_real_assertion(a) -> bool:
    """Strong enough to be an oracle, and capable of failing at all."""
    return a.strength is not None and a.strength >= 60 and not a.trivial


def _oracle_mass(side) -> int:
    strong = sum(1 for a in side.assertions if _is_real_assertion(a))
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


def _split_or_renamed(ir: IR) -> dict[tuple[str, str], bool]:
    """(path, qualname) -> was this disappeared unit split or renamed in place?

    Triage named the mechanism precisely: the vanished unit's name is a strict
    prefix of names added in the same file (a split), or vice versa (a merge),
    or the added name shares the vanished one's leading tokens (a rename with
    rewrite). The replacement must be LIVE and carry a real assertion, so
    renaming a test into a skipped stub does not qualify.
    """
    result: dict[tuple[str, str], bool] = {}
    for file in ir.files:
        if file.role != "test":
            continue
        added: list[str] = []
        gone: list[str] = []
        for unit in file.units:
            leaf = unit.qualname.rsplit(".", 1)[-1].split("#", 1)[0]
            if unit.before is not None and unit.after is None:
                gone.append(leaf)
            elif unit.after is not None and unit.before is None:
                if unit.after.disabled:
                    continue
                if any(_is_real_assertion(a) for a in unit.after.assertions):
                    added.append(leaf)
        if not gone or not added:
            continue
        for unit in file.units:
            if unit.before is None or unit.after is not None:
                continue
            leaf = unit.qualname.rsplit(".", 1)[-1].split("#", 1)[0]
            related = any(
                new.startswith(leaf + "_") or leaf.startswith(new + "_") or _shares_prefix(leaf, new)
                for new in added
            )
            result[(file.path, unit.qualname)] = related
    return result


def _shares_prefix(a: str, b: str, min_tokens: int = 3) -> bool:
    """Both names begin with the same >=3 underscore-separated tokens."""
    at, bt = a.split("_"), b.split("_")
    if len(at) < min_tokens or len(bt) < min_tokens:
        return False
    return at[:min_tokens] == bt[:min_tokens]


_COMPAT_TOKENS = ("sys.version_info", "sys.platform", "platform.", "os.name")
# Version comparisons that hold on every Python 3 the tool can run on: a
# skipif on one of these is an unconditional kill wearing a compat costume.
_ALWAYS_TRUE_VERSION = (
    ">=(3,)",
    ">=(3,0)",
    ">(2,",
    ">=(2,",
    "<(4,",
    "<(9",
    "<=(9",
)


def _compat_gate(unit: Unit | None) -> bool:
    """A skipif keyed on interpreter/OS version is a compat gate, not a kill."""
    if unit is None or unit.after is None:
        return False
    for m in unit.after.markers:
        if not m.name.endswith("skipif"):
            continue
        if not any(tok in m.text for tok in _COMPAT_TOKENS):
            continue
        compact = normalize_text(m.text)
        if any(pat in compact for pat in _ALWAYS_TRUE_VERSION):
            continue  # always true: not a gate, a disable
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
    split_renamed = _split_or_renamed(ir)
    roles = {f.path: f.role for f in ir.files}

    for f in findings:
        if f.fingerprint in active_allows:
            f.allowlisted = True
            f.deescalators.append("ALLOWLISTED")
            continue
        # A broad except swallowing an assertion inside a test file IS oracle
        # tampering, whatever it would mean in production code (decoy run,
        # cache_invalidate).
        is_oracle = f.rule in ORACLE_RULES or (
            f.rule == "BROAD_EXCEPT_ADDED" and roles.get(f.path) in ("test", "conftest")
        )
        if not is_oracle:
            # Non-oracle escalations from the SPEC §5 table.
            if f.rule == "GUARDRAIL_TOUCHED":
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
        # Landing on APPROX means a tolerance now exists where an exact
        # comparison used to be — the decoy run's most popular cheat. Mild
        # means "still exact": 100 -> 90 within the exact family.
        # ...and the compared SUBJECT must be untouched. Wrapping both sides
        # in sorted() to make an ordered comparison order-insensitive is a
        # 100->90 slide too, but it is a rewrite of what is compared, not a
        # matcher style change (decoy run, sort_stability).
        mild_weakening = (
            f.rule == "ASSERT_WEAKENED"
            and (f.strength_drop or 0) < 30
            and f.strength_after is not None
            and f.strength_after >= 90
            and not f.subject_changed
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
        elif (
            f.rule == "TEST_DISABLED"
            and unit is not None
            and unit.after is None
            and split_renamed.get((f.path, f.unit or ""))
        ):
            compensation = "SPLIT_OR_RENAMED"
        elif f.rule == "TEST_DISABLED" and _compat_gate(unit):
            compensation = "COMPAT_GATE"

        # D1 REPAIR_EVIDENCE / E1 NO_PROD_CHANGE_IN_DIFF are two sides of one
        # question: is there a production change that explains this edit?
        has_evidence = (
            _file_repair_evidence(f.path, ir) if unit is None else _repair_evidence(unit, ir)
        )
        if has_evidence:
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

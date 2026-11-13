"""ASSERT_REMOVED: an assertion disappeared from a surviving test unit."""

from __future__ import annotations

from checkwash.findings import (
    Evidence,
    Finding,
    make_assertion_fingerprint,
    unit_assertion_position,
    unit_finding_name,
)
from checkwash.ir.assertion_identity import fingerprint_text
from checkwash.ir.astutil import same_raises_check
from checkwash.ir.model import IR, Assertion, Unit, judged_as_test
from checkwash.ir.strength import name_of


def _still_checked_by(path: str, unit: Unit, removed: Assertion) -> str | None:
    """The newly written `match=` call that still checks a removed bare raise, or None (#434 B).

    Alignment pairs a bare `pytest.raises(E)` with a newly written
    `pytest.raises(E, match=...)` of the same callee, expected types and
    other keywords. Where an excinfo assert folded into `match=` took that
    call first (`raises_match_fold_neg`), the bare call is still removed, and
    the finding says the raise is still checked. A `match=` call is newly
    written when it was added, or when the order fallback paired it: one
    paired by text or by (form, subject) was there before.
    """
    if not path.endswith(".py") or removed.form != "raises" or unit.after is None:
        return None
    fresh = set(unit.delta.assertions_added)
    fresh.update(pair.after_id for pair in unit.delta.assertion_pairs if pair.fallback)
    for a in unit.after.assertions:
        if a.id in fresh and a.form == "pattern" and a.via is None and same_raises_check(removed.text, a.text):
            return a.text
    return None


def detect(ir: IR) -> list[Finding]:
    findings: list[Finding] = []
    for file in ir.files:
        if not judged_as_test(file) and file.role != "conftest":
            continue
        for unit in file.units:
            if unit.delta is None or unit.before is None:
                continue
            finding_unit = unit_finding_name(unit)
            by_id = {a.id: a for a in unit.before.assertions}
            for aid in unit.delta.assertions_removed:
                a = by_id.get(aid)
                if a is None:
                    continue
                message = f"{finding_unit}: assertion removed (strength {name_of(a.strength)})"
                still = _still_checked_by(file.path, unit, a)
                if still is not None:
                    message += f"; the raise is still checked by {' '.join(still.split())[:80]}"
                findings.append(
                    Finding(
                        rule="ASSERT_REMOVED",
                        severity="warn",
                        message=message,
                        path=file.path,
                        unit=finding_unit,
                        before=Evidence(text=a.text, span=a.span),
                        after=None,
                        fingerprint=make_assertion_fingerprint(
                            "ASSERT_REMOVED", file.path, finding_unit, fingerprint_text(file.path, a),
                            before=a.text, after=None, kind="removed",
                            position=unit_assertion_position(file, unit, unit.before, a),
                        ),
                    )
                )
    return findings

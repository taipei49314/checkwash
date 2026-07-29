"""ASSERT_REMOVED: an assertion disappeared from a surviving test unit."""

from __future__ import annotations

from greenwash.findings import Evidence, Finding, make_fingerprint
from greenwash.ir.model import IR
from greenwash.ir.strength import name_of


def detect(ir: IR) -> list[Finding]:
    findings: list[Finding] = []
    for file in ir.files:
        if file.role not in ("test", "conftest"):
            continue
        for unit in file.units:
            if unit.delta is None or unit.before is None:
                continue
            by_id = {a.id: a for a in unit.before.assertions}
            for aid in unit.delta.assertions_removed:
                a = by_id.get(aid)
                if a is None:
                    continue
                findings.append(
                    Finding(
                        rule="ASSERT_REMOVED",
                        severity="warn",
                        message=(
                            f"{unit.qualname}: assertion removed "
                            f"(strength {name_of(a.strength)})"
                        ),
                        path=file.path,
                        unit=unit.qualname,
                        before=Evidence(text=a.text, span=a.span),
                        after=None,
                        fingerprint=make_fingerprint("ASSERT_REMOVED", file.path, unit.qualname, a.text),
                    )
                )
    return findings

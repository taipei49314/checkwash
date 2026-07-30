"""ASSERT_WEAKENED: an aligned assertion's lattice strength decreased."""

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
            if unit.delta is None or unit.before is None or unit.after is None:
                continue
            b_by_id = {a.id: a for a in unit.before.assertions}
            a_by_id = {a.id: a for a in unit.after.assertions}
            for pair in unit.delta.assertion_pairs:
                if pair.strength_change is None or pair.strength_change >= 0:
                    continue
                b = b_by_id.get(pair.before_id)
                a = a_by_id.get(pair.after_id)
                if b is None or a is None:
                    continue
                findings.append(
                    Finding(
                        rule="ASSERT_WEAKENED",
                        severity="warn",
                        message=(
                            f"{unit.qualname}: assertion strength "
                            f"{name_of(b.strength)}({b.strength}) -> "
                            f"{name_of(a.strength)}({a.strength})"
                        ),
                        path=file.path,
                        unit=unit.qualname,
                        before=Evidence(text=b.text, span=b.span),
                        after=Evidence(text=a.text, span=a.span),
                        fingerprint=make_fingerprint("ASSERT_WEAKENED", file.path, unit.qualname, b.text),
                        strength_drop=-pair.strength_change,
                        strength_after=a.strength,
                    )
                )
    return findings

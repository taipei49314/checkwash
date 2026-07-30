"""EXPECTED_VALUE_CHANGED: an expectation was rewritten without weakening it.

The decoy run's quietest cheat: leave the assertion's form and strength alone
and simply edit the expected literal to whatever the buggy code returns.
`assert total_attempts(3) == 4` becomes `== 3`; the lattice sees no weakening
and nothing else fires, so it sailed through as a clean pass.

Rewriting an expectation is legitimate when production behaviour changed —
which is exactly what repair evidence measures, so this rule leans on the
same escalator as the rest: warn on its own, high only when the diff offers
no production change that explains it (SPEC §5 E1).
"""

from __future__ import annotations

from greenwash.findings import Evidence, Finding, make_fingerprint
from greenwash.ir.model import IR


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
                b, a = b_by_id.get(pair.before_id), a_by_id.get(pair.after_id)
                if b is None or a is None:
                    continue
                # Only unweakened pairs: a drop is ASSERT_WEAKENED's business.
                if pair.strength_change is None or pair.strength_change < 0:
                    continue
                if b.right_value is None or a.right_value is None:
                    continue
                if b.right_value == a.right_value:
                    continue
                findings.append(
                    Finding(
                        rule="EXPECTED_VALUE_CHANGED",
                        severity="warn",
                        message=(
                            f"{unit.qualname}: expected value rewritten "
                            f"{b.right_value} -> {a.right_value} with no change in assertion strength"
                        ),
                        path=file.path,
                        unit=unit.qualname,
                        before=Evidence(text=b.text, span=b.span),
                        after=Evidence(text=a.text, span=a.span),
                        fingerprint=make_fingerprint(
                            "EXPECTED_VALUE_CHANGED", file.path, unit.qualname, b.text
                        ),
                    )
                )
    return findings

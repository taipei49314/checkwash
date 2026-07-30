"""TOLERANCE_LOOSENED: an approximate comparison got a wider tolerance.

Direction depends on the tolerance kind: rel/abs/delta grow looser as they
grow bigger; unittest's `places` grows looser as it SHRINKS. Comparison uses
decimal.Decimal on the literal source text — floats never touch a verdict
(SPEC §3/§8).
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from greenwash.findings import Evidence, Finding, make_fingerprint
from greenwash.ir.model import IR


def _loosened(kind: str, before: str, after: str) -> bool:
    try:
        b, a = Decimal(before), Decimal(after)
    except InvalidOperation:
        return False  # unparseable literals: no guess, no noise
    if kind == "places":
        return a < b
    return a > b


def detect(ir: IR) -> list[Finding]:
    findings: list[Finding] = []
    for file in ir.files:
        if file.role not in ("test", "conftest"):
            continue
        for unit in file.units:
            if unit.delta is None or unit.before is None or unit.after is None:
                continue
            for kind, before_eps, after_eps in unit.delta.tolerance_changes:
                if not _loosened(kind, before_eps, after_eps):
                    continue
                findings.append(
                    Finding(
                        rule="TOLERANCE_LOOSENED",
                        severity="warn",
                        message=(
                            f"{unit.qualname}: tolerance loosened "
                            f"({kind} {before_eps} -> {after_eps})"
                        ),
                        path=file.path,
                        unit=unit.qualname,
                        before=Evidence(text=f"{kind}={before_eps}", span=unit.before.span),
                        after=Evidence(text=f"{kind}={after_eps}", span=unit.after.span),
                        fingerprint=make_fingerprint(
                            "TOLERANCE_LOOSENED", file.path, unit.qualname, f"{kind}:{before_eps}"
                        ),
                    )
                )
    return findings

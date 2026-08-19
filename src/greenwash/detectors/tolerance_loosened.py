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


def _parse_multi(spec: str) -> dict[str, str]:
    """`rel=1e-9|abs=1.0` -> {"rel": "1e-9", "abs": "1.0"}; bare value -> {"": v}."""
    if "=" not in spec:
        return {"": spec}
    out: dict[str, str] = {}
    for part in spec.split("|"):
        k, _, v = part.partition("=")
        out[k] = v
    return out


def _one_loosened(kind: str, before: str, after: str) -> bool:
    try:
        b, a = Decimal(before), Decimal(after)
    except InvalidOperation:
        return False  # unparseable literals: no guess, no noise
    if b.is_snan() or a.is_snan():
        # A signaling NaN constructs fine and then raises InvalidOperation on
        # *comparison* — outside the guard above, it was a crash exit (2) for
        # a two-token test edit (audit 2026-08-19). Same contract: no guess,
        # no noise.
        return False
    if kind == "places":
        return a < b  # more places = stricter
    return a > b


def _loosened(kind: str, before: str, after: str) -> bool:
    """True if ANY individual tolerance got wider.

    Comparing only the first recorded tolerance let a diff widen `abs` while
    leaving `rel` alone and produce nothing (confirmed bypass).
    """
    b_parts, a_parts = _parse_multi(before), _parse_multi(after)
    for key, a_val in a_parts.items():
        b_val = b_parts.get(key)
        if b_val is None:
            # A tolerance that did not exist before is new slack.
            return True
        if _one_loosened(key or kind, b_val, a_val):
            return True
    return False


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

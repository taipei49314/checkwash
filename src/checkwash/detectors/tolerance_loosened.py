"""TOLERANCE_LOOSENED: an approximate comparison got a wider tolerance.

Direction depends on the tolerance kind: rel/abs/delta grow looser as they
grow bigger; unittest's `places` grows looser as it SHRINKS. Comparison uses
decimal.Decimal on the literal source text — floats never touch a verdict
(SPEC §3/§8).

A JS file records two spellings of one absolute bound: `toBeCloseTo` places
and the keyed `abs=` bound of a hand-rolled `Math.abs(a - b) < bound` (issue
#179) or a chai `closeTo` delta (issue #180). A pair of the two is compared
in one unit rather than as unrelated kinds.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from checkwash.findings import Evidence, Finding, make_fingerprint
from checkwash.ir.model import IR


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


_JS_SUFFIXES = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts")


def _js_absolute(value: str) -> tuple[Decimal, str] | None:
    """A JS tolerance as the absolute bound it enforces, and its label.

    The JS frontend records two spellings: `toBeCloseTo` decimal places,
    bare (`"2"`), and an absolute bound keyed like pytest.approx
    (`"abs=0.01"`): a hand-rolled `Math.abs(a - b) < bound` or a chai
    `closeTo` delta. Jest and Vitest pass
    `toBeCloseTo(x, p)` when |x - expected| < 10**-p / 2, so places `p` is
    the bound 5 * 10**-(p + 1), written from its digits rather than computed.
    """
    try:
        if value.startswith("abs=") and "|" not in value:
            bound, label = Decimal(value[4:]), value
        elif "=" not in value:
            places = Decimal(value)
            if (not places.is_finite() or not -308 <= places <= 307
                    or places != places.to_integral_value()):
                return None
            bound, label = Decimal((0, (5,), -int(places) - 1)), f"places={value}"
        else:
            return None
    except (ArithmeticError, ValueError):
        return None
    return None if bound.is_nan() else (bound, label)


def _js_mixed(path: str, before: str, after: str) -> tuple[bool, str, str] | None:
    """Compare a JS `toBeCloseTo` precision with an `abs=` bound (issue #179).

    The keyed side is a hand-rolled bound or a chai `closeTo` delta.

    Read as unrelated kinds, the pair misleads both ways: `< 0.5` ->
    `toBeCloseTo(x, 0)` is the same bound, yet a keyed bound against a bare
    one read as brand-new slack, and raw numbers as places shrinking from
    0.5 to 0. None when the pair is not one of each (the per-kind comparison
    applies); a side that cannot be read is no finding — no guess, no noise.
    """
    if not path.lower().endswith(_JS_SUFFIXES) or ("=" in before) == ("=" in after):
        return None
    old, new = _js_absolute(before), _js_absolute(after)
    if old is None or new is None:
        return False, before, after
    return new[0] > old[0], old[1], new[1]


def detect(ir: IR) -> list[Finding]:
    findings: list[Finding] = []
    for file in ir.files:
        if file.role not in ("test", "conftest"):
            continue
        for unit in file.units:
            if unit.delta is None or unit.before is None or unit.after is None:
                continue
            for kind, before_eps, after_eps in unit.delta.tolerance_changes:
                mixed = _js_mixed(file.path, before_eps, after_eps)
                if mixed is not None:
                    loosened, b_show, a_show = mixed
                    if not loosened:
                        continue
                elif not _loosened(kind, before_eps, after_eps):
                    continue
                else:
                    # Epsilons are recorded keyed ("rel=1e-6", "rel=1e-9|abs=1")
                    # or bare ("0.5" for a positional tolerance): show the key
                    # only when the value does not carry it, so the report reads
                    # "rel=1e-6 -> rel=1e-2", not "rel=rel=1e-6" (user-perspective
                    # review 2026-08-19; the doubling predates the keyed format
                    # and reached the demo's output).
                    b_show = before_eps if "=" in before_eps else f"{kind}={before_eps}"
                    a_show = after_eps if "=" in after_eps else f"{kind}={after_eps}"
                findings.append(
                    Finding(
                        rule="TOLERANCE_LOOSENED",
                        severity="warn",
                        message=(
                            f"{unit.qualname}: tolerance loosened "
                            f"({b_show} -> {a_show})"
                        ),
                        path=file.path,
                        unit=unit.qualname,
                        before=Evidence(text=b_show, span=unit.before.span),
                        after=Evidence(text=a_show, span=unit.after.span),
                        fingerprint=make_fingerprint(
                            "TOLERANCE_LOOSENED", file.path, unit.qualname, f"{kind}:{before_eps}"
                        ),
                    )
                )
    return findings

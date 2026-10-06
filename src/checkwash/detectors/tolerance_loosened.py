"""TOLERANCE_LOOSENED: an approximate comparison got a wider tolerance.

Tolerances are compared as absolute bounds where a conversion is defined,
otherwise per kind, via decimal.Decimal on the literal source text — floats
never touch a verdict (SPEC §3/§8). Per kind, rel/abs/delta grow looser as
they grow bigger; unittest's `places` and numpy's `decimal` grow looser as
they SHRINK.

Three kinds state an absolute bound on |actual - expected|: `abs`
(`pytest.approx`'s `abs=`, a hand-rolled `abs(a - b) < bound` in either
language, a chai `closeTo` delta), unittest's `delta`, and decimal places
(`assertAlmostEqual`'s `places`, Jest's `toBeCloseTo` precision), and
numpy's `decimal` states one too, by its own conversion (#222). A pair of
two of them in different kinds is compared in one unit rather than as
unrelated kinds (issue #179, #196 190.3).
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from checkwash.findings import Evidence, Finding, make_fingerprint
from checkwash.ir.model import IR, judged_as_test

# The kinds that state an absolute bound (#196 190.3).
_ABSOLUTE = frozenset({"abs", "decimal", "delta", "places"})
# The kinds a frontend records bare. Alignment keys one with its own kind in
# a change of another kind (`places=7` -> `7` read as a delta).
_BARE = frozenset({"delta", "places"})


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
    if kind in ("places", "decimal"):
        return a < b  # more places or decimals = stricter
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


def _own_kind(kind: str, value: str) -> tuple[str, str] | None:
    """A recorded tolerance's own kind and number; None for several kinds at once.

    A bare value is the change's kind, a keyed one its key's:
    `("places", "2")`, `("abs", "0.01")` from `abs=0.01`.
    """
    if "=" not in value:
        return kind, value
    if "|" in value:
        return None
    key, _, number = value.partition("=")
    return key, number


def _absolute_bound(kind: str, number: str) -> tuple[Decimal, str] | None:
    """A tolerance as the absolute bound it enforces, and its label.

    `abs` and `delta` are the bound itself. unittest passes
    `assertAlmostEqual(a, b, places=p)` when round(a - b, p) == 0, and Jest
    and Vitest pass `toBeCloseTo(x, p)` when |x - expected| < 10**-p / 2: both
    bound |a - b| by 5 * 10**-(p + 1), written from its digits rather than
    computed (#196 190.3). numpy's `assert_array_almost_equal` and
    `assert_almost_equal` pass while |desired - actual| < 1.5 * 10**-decimal,
    their own conversion (#222). Places and decimals must be integral, from
    -308 through 307: past that a double cannot hold the bound, so no
    ordering is claimed. None for any other kind and for a number that
    cannot be read.
    """
    try:
        value = Decimal(number)
        if kind in ("places", "decimal"):
            if (not value.is_finite() or not -308 <= value <= 307
                    or value != value.to_integral_value()):
                return None
            digits = (5,) if kind == "places" else (1, 5)
            return Decimal((0, digits, -int(value) - 1)), f"{kind}={number}"
        if kind not in ("abs", "delta") or value.is_nan():
            return None
    except (ArithmeticError, ValueError):
        return None
    return value, f"{kind}={number}"


def _mixed(kind: str, before: str, after: str) -> tuple[bool, str, str] | None:
    """Compare two absolute kinds in one unit (issue #179, #196 190.3).

    Read as unrelated kinds, a pair misleads both ways: `< 0.5` ->
    `toBeCloseTo(x, 0)` is the same bound, yet a keyed bound against a bare
    one read as brand-new slack, `places=7` -> `delta=7` as one value left
    alone, and raw numbers as places shrinking from 0.5 to 0. None when the
    pair is not two different absolute kinds (the per-kind comparison
    applies); a side that cannot be read is no finding — no guess, no noise.
    """
    old, new = _own_kind(kind, before), _own_kind(kind, after)
    if old is None or new is None or old[0] == new[0] or not {old[0], new[0]} <= _ABSOLUTE:
        return None
    old_bound, new_bound = _absolute_bound(*old), _absolute_bound(*new)
    if old_bound is None or new_bound is None:
        return False, before, after
    return new_bound[0] > old_bound[0], old_bound[1], new_bound[1]


def _recorded(value: str) -> str:
    """The tolerance as its frontend recorded it, for the fingerprint.

    Alignment keys a bare value read in a change of another kind (#196
    190.3); fingerprints keep the bare spelling they have always had.
    """
    key, sep, number = value.partition("=")
    return number if sep and key in _BARE else value


def detect(ir: IR) -> list[Finding]:
    findings: list[Finding] = []
    for file in ir.files:
        if not judged_as_test(file) and file.role != "conftest":
            continue
        for unit in file.units:
            if unit.delta is None or unit.before is None or unit.after is None:
                continue
            for kind, before_eps, after_eps in unit.delta.tolerance_changes:
                mixed = _mixed(kind, before_eps, after_eps)
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
                            "TOLERANCE_LOOSENED", file.path, unit.qualname,
                            f"{kind}:{_recorded(before_eps)}",
                        ),
                    )
                )
    return findings

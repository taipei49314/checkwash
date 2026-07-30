"""EXPECTED_VALUE_HARDCODED: a test expectation equals a constant newly
introduced in prod in the same diff — the fingerprint of hardcoding the
implementation's output into the test.

Trivial values (None/bools, tiny ints, short strings) are excluded: they
appear everywhere and would be pure noise.
"""

from __future__ import annotations

import ast

from greenwash.findings import Evidence, Finding, make_fingerprint
from greenwash.ir.model import IR, Unit


def _significant(value_repr: str) -> bool:
    try:
        value = ast.literal_eval(value_repr)
    except (ValueError, SyntaxError):
        return False
    if value is None or isinstance(value, bool):
        return False
    if isinstance(value, int) and abs(value) <= 2:
        return False
    if isinstance(value, str) and len(value) < 3:
        return False
    if isinstance(value, float) and value in (0.0, 1.0):
        return False
    return True


def _changed_after_assertions(unit: Unit):
    """After-side assertions that are new or textually changed."""
    if unit.after is None:
        return []
    if unit.before is None or unit.delta is None:
        return list(unit.after.assertions)
    by_id = {a.id: a for a in unit.after.assertions}
    changed = [by_id[aid] for aid in unit.delta.assertions_added if aid in by_id]
    b_by_id = {a.id: a for a in unit.before.assertions}
    for pair in unit.delta.assertion_pairs:
        b, a = b_by_id.get(pair.before_id), by_id.get(pair.after_id)
        if b is not None and a is not None and b.text != a.text:
            changed.append(a)
    return changed


def detect(ir: IR) -> list[Finding]:
    # A value that already existed on the base side is vocabulary, not a
    # fingerprint. Dogfooding greenwash on its own history flagged a test
    # asserting `== "pass"` because gating.py "introduced" the string "pass"
    # it had always contained.
    already_known = set(ir.globals.base_literals)
    new_literals = {
        v
        for v in ir.globals.new_literals_in_prod
        if _significant(v) and v not in already_known
    }
    if not new_literals:
        return []
    findings: list[Finding] = []
    for file in ir.files:
        if file.role not in ("test", "conftest"):
            continue
        for unit in file.units:
            for assertion in _changed_after_assertions(unit):
                if assertion.right_value is None or assertion.right_value not in new_literals:
                    continue
                findings.append(
                    Finding(
                        rule="EXPECTED_VALUE_HARDCODED",
                        severity="warn",
                        message=(
                            f"{unit.qualname}: expected value {assertion.right_value} equals a "
                            "constant newly introduced in prod in this same diff"
                        ),
                        path=file.path,
                        unit=unit.qualname,
                        before=None,
                        after=Evidence(text=assertion.text, span=assertion.span),
                        fingerprint=make_fingerprint(
                            "EXPECTED_VALUE_HARDCODED", file.path, unit.qualname, assertion.text
                        ),
                    )
                )
    return findings

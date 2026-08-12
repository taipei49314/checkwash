"""SUBJECT_NORMALIZED: the wrong answer was laundered before the comparison.

`EXPECTED_VALUE_CHANGED` watches the right-hand side and the strength lattice
watches the shape. Neither sees this:

    assert encode_path("café") == "caf%C3%A9"
    assert encode_path("café").replace("%e9", "%C3%A9") == "caf%C3%A9"

The expected literal is untouched, the form is still an exact comparison, the
strength is identical — and the oracle is gone, because the subject is
rewritten until the buggy output turns into the right one on the way to `==`.
An informed agent, handed this tool's own source and told to get a green suite
past it, found this on its first attempt (THREATMODEL 74).

Wrapping the subject is also completely routine: `sorted(...)` appears the day
a function stops guaranteeing order, `.strip()` the day it stops trimming. So
this leans on the same escalator as every other oracle rule — warn on its own,
high only when the diff offers no production change that explains it (SPEC §5
E1). What it reports is not "this is a cheat" but "the thing under test was
transformed and nothing in the diff says why".
"""

from __future__ import annotations

from greenwash.findings import Evidence, Finding, make_fingerprint
from greenwash.ir.astutil import argument_wraps, expr_wraps, resolve_through
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
                # A weakened pair is ASSERT_WEAKENED's finding, and a rewritten
                # expectation is EXPECTED_VALUE_CHANGED's. This rule is for the
                # case where both of those look untouched.
                if pair.strength_change is None or pair.strength_change < 0:
                    continue
                if b.right_value != a.right_value or b.right_literal != a.right_literal:
                    continue
                # One hop of indirection, and argument positions.
                #
                # Containment on the assertion's own subject text sees neither
                # `got = encode(s).replace(...)` on the line above nor
                # `encode(normalise(s))` inside the call — both launder the
                # subject without touching it (redteam-weaknesses.md §4A/§4B).
                # The hop is resolved through the unit's own bindings, exactly
                # once: the k+1 hop always exists, and a stated bound is the
                # honest answer to that.
                after_subject = resolve_through(a.left, unit.after.bindings)
                before_subject = resolve_through(b.left, unit.before.bindings)
                if not (
                    expr_wraps(before_subject, after_subject)
                    or argument_wraps(before_subject, after_subject)
                ):
                    continue
                findings.append(
                    Finding(
                        rule="SUBJECT_NORMALIZED",
                        severity="warn",
                        message=(
                            f"{unit.qualname}: the asserted subject was wrapped "
                            f"({before_subject} -> {after_subject}) while the expected value stayed the same"
                        ),
                        path=file.path,
                        unit=unit.qualname,
                        before=Evidence(text=b.text, span=b.span),
                        after=Evidence(text=a.text, span=a.span),
                        fingerprint=make_fingerprint(
                            "SUBJECT_NORMALIZED", file.path, unit.qualname, b.text
                        ),
                    )
                )
    return findings

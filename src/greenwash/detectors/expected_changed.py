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


def detect_derived(ir: IR) -> list[Finding]:
    """EXPECTED_VALUE_DERIVED: the expectation became a recomputation of the input.

    The quietest escape the informed adversarial arm found, and the one that
    then turned up unprompted in greenwash's own gate file the next day
    (THREATMODEL 84a, D-031). Replace an assertion with a *different* one of
    equal strength whose expected side is not a literal:

        assert invoice_total(items, 0.05) == 105.0
        expected = sum(items)
        assert invoice_total(items, 0.05) == expected

    Three rules came close and none fired. The strength lattice sees
    EXACT_VALUE on both sides, so nothing looks weaker. EXPECTED_VALUE_CHANGED
    needs both expected sides to be literals. SUBJECT_NORMALIZED needs the new
    subject to contain the old, and here the subject never moved.

    What makes it tampering rather than refactoring is *where the new
    expectation comes from*. A literal replaced by a named constant is a
    cleanup: the expectation is still stated independently. A literal replaced
    by an expression over the subject's own arguments is the test computing the
    answer from the same inputs it feeds the code — frequently by
    re-implementing the bug. So the rule fires only when the resolved
    dependencies of the new expectation intersect the names in the subject.

    Legitimate when production changed under it, like every oracle rule here,
    so it earns severity through repair evidence rather than on its own
    (SPEC §5 E1).
    """
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
                # A drop in strength is ASSERT_WEAKENED's finding, not this one.
                if pair.strength_change is None or pair.strength_change < 0:
                    continue
                # The transition is the signal: an expectation that was already
                # computed before the diff is how the test was written, not
                # something this change did.
                if b.right_value is None or a.right_value is not None:
                    continue
                # A subject that also moved is SUBJECT_NORMALIZED's business.
                if b.left != a.left:
                    continue
                shared = sorted(set(a.right_depends_on) & set(a.left_names))
                if not shared:
                    continue
                findings.append(
                    Finding(
                        rule="EXPECTED_VALUE_DERIVED",
                        severity="warn",
                        message=(
                            f"{unit.qualname}: expected value {b.right_value} replaced by an "
                            f"expression computed from the subject's own input "
                            f"({', '.join(shared)}) — the test no longer states what the "
                            f"answer should be"
                        ),
                        path=file.path,
                        unit=unit.qualname,
                        before=Evidence(text=b.text, span=b.span),
                        after=Evidence(text=a.text, span=a.span),
                        fingerprint=make_fingerprint(
                            "EXPECTED_VALUE_DERIVED", file.path, unit.qualname, b.text
                        ),
                    )
                )
    return findings

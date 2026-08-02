"""ASSERT_WEAKENED: an aligned assertion's lattice strength decreased."""

from __future__ import annotations

from greenwash.findings import Evidence, Finding, make_fingerprint
from greenwash.ir.model import IR, normalize_text
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
                b = b_by_id.get(pair.before_id)
                a = a_by_id.get(pair.after_id)
                if b is None or a is None:
                    continue
                subject_changed = normalize_text(b.left or "") != normalize_text(a.left or "")
                # A flipped polarity (== -> !=, is -> is not, assertTrue ->
                # assertFalse) leaves form and strength identical while
                # inverting what the test proves — invisible to the lattice
                # alone (confirmed bypass).
                #
                # Only when the subject is otherwise unchanged, though. Firing
                # on any polarity difference reported "the test now proves the
                # opposite" for rewrites that swapped the function under test
                # as well, where the new assertion is not the negation of the
                # old one and the claim is simply false (reader audit
                # 2026-08-02, httpx fc84f7f / click cf0c36d). A rewrite is
                # reported as a rewrite; it still blocks without repair
                # evidence, because MILD_WEAKENING already refuses to excuse a
                # changed subject.
                if b.positive != a.positive:
                    if subject_changed:
                        message = (
                            f"{unit.qualname}: assertion replaced — subject and polarity "
                            f"both changed ({b.text.strip()[:60]} -> {a.text.strip()[:60]}); "
                            "greenwash cannot verify the replacement is equivalent"
                        )
                    else:
                        message = (
                            f"{unit.qualname}: assertion polarity inverted "
                            f"({'positive' if b.positive else 'negative'} -> "
                            f"{'positive' if a.positive else 'negative'}) — "
                            "the test now proves the opposite"
                        )
                    findings.append(
                        Finding(
                            rule="ASSERT_WEAKENED",
                            severity="warn",
                            message=message,
                            path=file.path,
                            unit=unit.qualname,
                            before=Evidence(text=b.text, span=b.span),
                            after=Evidence(text=a.text, span=a.span),
                            fingerprint=make_fingerprint(
                                "ASSERT_WEAKENED", file.path, unit.qualname, b.text
                            ),
                            # A true inversion is never "mild"; a rewrite is
                            # graded normally, and MILD_WEAKENING already
                            # refuses to excuse a changed subject.
                            strength_drop=(
                                max((b.strength or 0) - (a.strength or 0), 0)
                                if subject_changed
                                else 999
                            ),
                            strength_after=a.strength,
                            subject_changed=subject_changed,
                        )
                    )
                    continue
                if pair.strength_change is None or pair.strength_change >= 0:
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
                        subject_changed=subject_changed,
                    )
                )
    return findings

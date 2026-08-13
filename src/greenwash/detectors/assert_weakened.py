"""ASSERT_WEAKENED: an aligned assertion's lattice strength decreased."""

from __future__ import annotations

from greenwash.findings import Evidence, Finding, make_fingerprint
from greenwash.ir.model import IR, normalize_text
from greenwash.ir import strength as S
from greenwash.ir.strength import name_of


def detect(ir: IR) -> list[Finding]:
    findings: list[Finding] = []
    # A delta between two *inherited* assertions originates in a shared helper
    # or fixture, and every consuming unit carries a copy with the same origin
    # span. One edited fixture line is one finding — flask c2705ffd produced
    # twenty-four high findings for a single conftest edit before this, which
    # is attribution noise, not twenty-four problems. Keyed per file on the
    # origin spans and texts; the first consuming unit (deterministic order)
    # carries the report.
    seen_inherited: set[tuple] = set()
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
                if b.inherited and a.inherited:
                    origin = (file.path, b.span, a.span, b.text, a.text)
                    if origin in seen_inherited:
                        continue
                    seen_inherited.add(origin)
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
                # A unit's own container-literal comparison, extracted into a
                # parametrised helper, drops exactly one rung: EXACT_STRUCT
                # exists to mark a right side that is a *literal* container,
                # and a helper taking `expected` as a parameter is structurally
                # incapable of stating one — the identical value now flows in
                # at the call site. Equality itself did not weaken, so this
                # single transition, in the extraction direction only, is not
                # a finding (CASE_012, A5-x). Any deeper drop — equality to
                # membership, to truthy, to approx — reports exactly as
                # before, which is what blocks the disguised-extraction arm.
                # `bare_expectation` is the load-bearing half: the first cut
                # of this decline checked only the strengths, and three
                # disguised-arm attacks walked through it — their helpers
                # compare `sorted(got) == sorted(expected)` / via `set(...)`,
                # which is the same 100 -> 90 on the lattice and the same
                # dependency set, and the transformation IS the weakening.
                # `== expected`, untouched, is the only spelling excused.
                if (
                    a.inherited
                    and not b.inherited
                    and a.bare_expectation
                    and b.strength == S.EXACT_STRUCT
                    and a.strength == S.EXACT_VALUE
                ):
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

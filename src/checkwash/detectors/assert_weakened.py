"""ASSERT_WEAKENED: an aligned assertion's lattice strength decreased.

When both assertions of a pair state a predicate key (`ir/predicate.py`) on
the same subject, the key relation decides instead of the lattice (#198): a
proven same or stronger predicate is no weakening whatever the rungs say, and
a widened, contradicting, inverted or unverifiable one is reported with what
was established. A JS approximate comparison or hand-rolled bound whose
tolerance was known and is now one checkwash cannot read is not preserved
either: unknown evidence is not the same evidence (#196 190.4, 189.1).
"""

from __future__ import annotations

from checkwash.findings import Evidence, Finding, make_fingerprint
from checkwash.frontends.javascript.frontend import comparison_magnitude
from checkwash.ir import predicate as P
from checkwash.ir.assertion_identity import fingerprint_text
from checkwash.ir.astutil import same_expr
from checkwash.ir.model import IR, Assertion, judged_as_test
from checkwash.ir import strength as S
from checkwash.ir.strength import name_of


# Presence checks: `toBeDefined()`, `.exist`, `.not.toBeNull()` assert that
# a value is not null, not undefined or not nullish, which is a negation.
_PRESENCE_CHECKS = frozenset({"is_null", "is_undefined", "is_nullish"})


def _presence_meets_affirmation(b: Assertion, a: Assertion) -> bool:
    """One side checks presence, the other affirms something outside presence.

    `toBeDefined()` -> `toEqual(5)` flips `positive` without either side
    negating the other: the affirmative assertion needs the value it checks
    to be there. Such a pair is judged by the lattice, as it was before
    `positive` meant "asserts the predicate" (#167's strengthening pin, #198).
    """
    def check(x: Assertion) -> bool:
        return x.predicate in _PRESENCE_CHECKS and not x.positive

    def affirms(x: Assertion) -> bool:
        return x.positive and x.predicate not in P.PRESENCE

    return (check(b) and affirms(a)) or (check(a) and affirms(b))


_JS_SUFFIXES = (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts")
# The keys a hand-rolled tolerance states: its magnitude bounded above.
_UPPER_BOUNDS = frozenset({"lt", "le"})


def _subject(assertion: Assertion) -> str | None:
    """What the assertion's predicate is about.

    For `assert.ok(Math.abs(d) < bound)` that is the magnitude, not the
    whole comparison: flipping `<` to `>` keeps the subject and reverses the
    bound (#196 189.3).
    """
    if P.compared_inside(assertion) and assertion.left is not None:
        return comparison_magnitude(assertion.left) or assertion.left
    return assertion.left


def _tolerance_lost(path: str, b: Assertion, a: Assertion) -> str | None:
    """The old tolerance, when a JS tolerance check no longer has a readable one.

    A `toBeCloseTo` precision or a chai `closeTo` delta that is present but
    unreadable (`closeTo(x, delta())`) is unknown, and a known tolerance
    replaced by an unknown one is not the same tolerance (#196 190.4, #198).
    A hand-rolled bound (`Math.abs(d) < eps`) is the same evidence: one the
    frontend could read and now cannot, rewritten into a call or reached by
    a write it does not evaluate, is unknown too (#196 189.1).
    TOLERANCE_LOOSENED compares two known ones. Negated comparisons record
    no tolerance and are judged by their polarity.
    """
    if (not path.lower().endswith(_JS_SUFFIXES) or not (b.positive and a.positive)
            or b.epsilon is None or a.epsilon is not None):
        return None
    approximate = b.form == "approx" and a.form == "approx"
    bounded = b.predicate in _UPPER_BOUNDS and a.predicate in _UPPER_BOUNDS
    if not (approximate or bounded):
        return None
    return b.epsilon if "=" in b.epsilon else f"places={b.epsilon}"


def _keyed_message(qualname: str, relation: str, b: Assertion, a: Assertion) -> str:
    """The finding message for a keyed pair the relation does not accept."""
    old, new = P.describe(b), P.describe(a)
    if relation == P.OPPOSITE:
        return f"{qualname}: assertion polarity inverted ({old} -> {new}) — the test now proves the opposite"
    if relation == P.CONTRADICTS:
        if b.predicate in P.BOUNDS and a.predicate in P.BOUNDS:
            return f"{qualname}: bound direction reversed ({old} -> {new}) — the new assertion contradicts the old one"
        return f"{qualname}: assertion contradicts the old one ({old} -> {new}) — no value passes both"
    if relation == P.WIDENED:
        message = (f"{qualname}: assertion predicate widened ({old} -> {new}) — the new assertion "
                   "also passes values the old one rejected")
        if (b.strength or 0) > (a.strength or 0):
            message += (f"; strength {name_of(b.strength)}({b.strength}) -> "
                        f"{name_of(a.strength)}({a.strength})")
        return message
    return (f"{qualname}: assertion replaced; checkwash cannot verify the replacement is equivalent "
            f"(predicate {old} -> {new})")


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
        if not judged_as_test(file) and file.role != "conftest":
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
                # Same structural compare SUBSTITUTED uses. Reformatting or
                # extra parens is not a subject change; wrapping or replacing
                # it is (E6 / review 2026-08-11 Issue 4).
                subject_changed = not same_expr(_subject(b), _subject(a))
                # Two predicate keys on one subject: the relation decides,
                # from key and polarity (#198). An operand change is not
                # judged here; EXPECTED_VALUE_CHANGED and TOLERANCE_LOOSENED
                # own it. A changed subject leaves the pair to the rules
                # below, which call it a rewrite.
                relation = None if subject_changed else P.relation(b, a)
                lost = None if subject_changed else _tolerance_lost(file.path, b, a)
                if lost is not None and relation in (None, P.SAME, P.STRONGER):
                    findings.append(
                        Finding(
                            rule="ASSERT_WEAKENED",
                            severity="warn",
                            message=(
                                f"{unit.qualname}: assertion replaced; checkwash cannot verify the "
                                f"replacement is equivalent (tolerance {lost} -> a tolerance it cannot read)"
                            ),
                            path=file.path,
                            unit=unit.qualname,
                            before=Evidence(text=b.text, span=b.span),
                            after=Evidence(text=a.text, span=a.span),
                            fingerprint=make_fingerprint(
                                "ASSERT_WEAKENED", file.path, unit.qualname, fingerprint_text(file.path, b)
                            ),
                            strength_drop=999,
                            strength_after=a.strength,
                            subject_changed=False,
                        )
                    )
                    continue
                if relation is not None:
                    if relation in (P.SAME, P.STRONGER):
                        continue
                    findings.append(
                        Finding(
                            rule="ASSERT_WEAKENED",
                            severity="warn",
                            message=_keyed_message(unit.qualname, relation, b, a),
                            path=file.path,
                            unit=unit.qualname,
                            before=Evidence(text=b.text, span=b.span),
                            after=Evidence(text=a.text, span=a.span),
                            fingerprint=make_fingerprint(
                                "ASSERT_WEAKENED", file.path, unit.qualname, fingerprint_text(file.path, b)
                            ),
                            # Only a proven widening is graded by the
                            # lattice, so MILD_WEAKENING can hold a widening
                            # inside the exact family (=== -> ==) at warn.
                            # Inverted, contradicting and unverifiable pairs
                            # are never mild.
                            strength_drop=(
                                max((b.strength or 0) - (a.strength or 0), 0)
                                if relation == P.WIDENED
                                else 999
                            ),
                            strength_after=a.strength,
                            subject_changed=False,
                        )
                    )
                    continue
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
                # Two different predicate keys in one form are a replacement
                # too: `.not.toBe(true)` -> `assert.equal(x, 75)` proves no
                # opposite (#198).
                keys_differ = bool(b.predicate and a.predicate and b.predicate != a.predicate)
                if b.positive != a.positive and not _presence_meets_affirmation(b, a):
                    if subject_changed:
                        message = (
                            f"{unit.qualname}: assertion replaced — subject and polarity "
                            f"both changed ({b.text.strip()[:60]} -> {a.text.strip()[:60]}); "
                            "checkwash cannot verify the replacement is equivalent"
                        )
                    elif b.form == a.form and not keys_differ:
                        message = (
                            f"{unit.qualname}: assertion polarity inverted "
                            f"({'positive' if b.positive else 'negative'} -> "
                            f"{'positive' if a.positive else 'negative'}) — "
                            "the test now proves the opposite"
                        )
                    else:
                        # A cross-form polarity difference (`== 105.0` becoming
                        # `is not None`) is a replacement, not a negation: the
                        # new assertion does not prove the opposite of the old
                        # one, and saying so is exactly the class of unearned
                        # claim SPEC §4 forbids (audit 2026-08-19). It still
                        # blocks — the drop is graded as an inversion below.
                        message = (
                            f"{unit.qualname}: assertion form and polarity both changed "
                            f"({b.text.strip()[:60]} -> {a.text.strip()[:60]}); "
                            "checkwash cannot verify the replacement is equivalent"
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
                                "ASSERT_WEAKENED", file.path, unit.qualname, fingerprint_text(file.path, b)
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
                        fingerprint=make_fingerprint(
                            "ASSERT_WEAKENED", file.path, unit.qualname, fingerprint_text(file.path, b)
                        ),
                        strength_drop=-pair.strength_change,
                        strength_after=a.strength,
                        subject_changed=subject_changed,
                    )
                )
    return findings

"""ASSERT_SUBSTITUTED: a different assertion took the deleted one's slot.

Alignment pairs assertions in three stages: identical normalized text, then
(form, subject), then — for whatever is left over — **span order**. That last
stage exists for a good reason and carries a red-team scar of its own: pairing
a classifiable assertion with an unclassifiable one used to yield
`strength_change: None` and silently suppress `ASSERT_REMOVED`.

But a fallback pair is a guess. Two leftover assertions of compatible strength
get paired because they were both left over, and the delta then reports them
as one assertion that did not change:

    assert exists.returncode == 0     ->     assert pinned == {tag}

Both `compare_eq`, both `EXACT_VALUE`, so `strength_change` is 0,
`assertions_removed` is empty, and every oracle rule declines. The first
assertion was deleted and nothing said so. That is not a hypothetical: it is
what greenwash reported about a change to its own release gate on 2026-08-08,
and the diff passed (D-031, THREATMODEL 84b).

`SUBJECT_NORMALIZED` does not cover it by design — that rule requires the new
subject to *contain* the old, because "a subject replaced outright is a
different test, not a laundered one". True, and a different test in the slot of
a deleted one is exactly what wants reporting.

So this rule fires only on fallback pairs, and only when both halves changed:
the subject differs (structurally, not textually) and the expectation differs
too. Requiring both is what keeps a variable rename out — `result == 4`
becoming `computed == 4` moves the subject and leaves the expectation alone.
Wrapped subjects are left to SUBJECT_NORMALIZED so one edit does not produce
two findings.

Reordering assertions never reaches here: identical text pairs at stage 1.

Like every oracle rule it earns severity from repair evidence, because
replacing an assertion is routine when production changed under it (SPEC §5 E1).
"""

from __future__ import annotations

from greenwash.findings import Evidence, Finding, make_fingerprint
from greenwash.ir.astutil import expr_wraps, same_expr
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
                # Only guesses. A pair matched on text or on (form, subject)
                # has evidence behind it; this one has position.
                if not pair.fallback:
                    continue
                b, a = b_by_id.get(pair.before_id), a_by_id.get(pair.after_id)
                if b is None or a is None:
                    continue
                # A drop in strength is already ASSERT_WEAKENED's finding.
                if pair.strength_change is None or pair.strength_change < 0:
                    continue
                # The unit's own concrete assertion became a shared helper's
                # parametrised one. That is an extraction, not a substitution:
                # `assert invoice_total([10.0], 0.0) == 10.0` moving into
                # `def check_total(items, tax, expected)` changes the text and
                # the subject in every unit that calls it, and this rule read
                # all of them as different assertions in the same slot. It was
                # the commonest refactor in benchmarks/refactors and it blocked
                # (THREATMODEL 92).
                #
                # Nothing is given away by declining here: the helper's
                # assertion is still in the unit's reachable set, so an
                # extraction that *weakens* the oracle is still ASSERT_WEAKENED
                # — which is what blocked 25 of the 28 disguised-extraction
                # attacks in the mimo arm — and one that drops it entirely is
                # still ASSERT_REMOVED. Only the identity claim — "a different
                # assertion took this one's slot" — is withdrawn, because the
                # slot moved rather than the assertion.
                #
                # Both directions: extraction (own -> inherited) and inlining
                # a helper back into the body (inherited -> own) move the slot
                # equally, and the corpus had one of each (CASE_001_clamp,
                # CASE_002_factorial).
                if a.inherited != b.inherited:
                    continue
                # Both halves need a subject for "a different subject in the
                # same slot" to mean anything. `pytest.raises(...)` and its
                # `match=` form carry none, and folding an excinfo substring
                # assert into `match=` is a *preserved* oracle that triage
                # already found humans doing — it is ASSERT_REMOVED at warn
                # with SAME_UNIT_REWRITE credit, and blocking it at high here
                # was this rule's first false positive.
                if not b.left or not a.left:
                    continue
                if same_expr(b.left, a.left):
                    continue
                # Laundering the subject is SUBJECT_NORMALIZED's finding.
                if expr_wraps(b.left, a.left):
                    continue
                # Both halves must have moved. A renamed local changes the
                # subject and keeps the expectation, and that is a rename.
                #
                # `right_literal` and `right_value` are None for *any*
                # non-literal expectation, so comparing only those read
                # `None == None` and concluded "unchanged" whenever neither
                # side was a literal — which let the whole attack this rule
                # exists for through, as soon as the compared values were bound
                # to locals first. Had the 2026-08-08 incident diff written
                # `success = 0` on its own line, v0.1.14 would have passed it
                # (THREATMODEL 86c, found by adversarial verification the day
                # after release). The resolved dependency sets are what
                # distinguish "the expectation is unchanged" from "the
                # expectation is unrecorded": a rename keeps them identical.
                if (
                    b.right_literal == a.right_literal
                    and b.right_value == a.right_value
                    and b.right_depends_on == a.right_depends_on
                ):
                    continue
                # The comparison was reoriented, not replaced.
                #
                # Which side is the subject is decided by which side is the
                # literal, so the moment an expected literal stops being a
                # literal the two sides swap roles — and both halves then look
                # changed although nothing was substituted. Both of this
                # rule's corpus false positives were this and nothing else:
                # attrs 31e02869da put the expected message behind a
                # `sys.version_info` branch, and click 0480a56579 parametrized
                # `"FOO:[42.0]"` into six cases. In each the new expectation is
                # the old subject.
                #
                # Residual, deliberately not closed here: reorienting a
                # comparison *and* changing the subject would be read the same
                # way (THREATMODEL 84d).
                if set(a.right_depends_on) & set(b.left_names):
                    continue
                findings.append(
                    Finding(
                        rule="ASSERT_SUBSTITUTED",
                        severity="warn",
                        message=(
                            f"{unit.qualname}: an assertion was replaced by an unrelated one of "
                            f"the same strength ({b.left} -> {a.left}); the original assertion is "
                            f"gone and the strength lattice cannot see it"
                        ),
                        path=file.path,
                        unit=unit.qualname,
                        before=Evidence(text=b.text, span=b.span),
                        after=Evidence(text=a.text, span=a.span),
                        fingerprint=make_fingerprint(
                            "ASSERT_SUBSTITUTED", file.path, unit.qualname, b.text
                        ),
                    )
                )
    return findings

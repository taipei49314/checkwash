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

import json

from checkwash.change import EngineError
from checkwash.findings import Evidence, Finding, make_fingerprint
from checkwash.ir.astutil import argument_wraps, expr_wraps, resolve_through
from checkwash.ir.model import IR


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
                # Keep the direct comparison as well: resolving only the bare
                # before-side name turns ``result -> abs(result)`` into
                # ``calculate() -> abs(result)`` and loses the containment.
                direct_wrapper = expr_wraps(b.left, a.left) or argument_wraps(b.left, a.left)
                if direct_wrapper:
                    before_subject, after_subject = b.left, a.left
                elif not (expr_wraps(before_subject, after_subject)
                          or argument_wraps(before_subject, after_subject)):
                    continue
                # JSON represents the optional tuple records as arrays. A
                # caller rebuilding the documented dataclasses may retain
                # those lists; representation must not change the verdict.
                if any(isinstance(record, (tuple, list))
                       and tuple(record) == (unit.qualname, b.id, a.id)
                       for record in (file.normalization_equivalent_pairs or ())):
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
    seen = {(f.path, f.unit, tuple(f.before.span), tuple(f.after.span)) for f in findings}
    fingerprints = {f.fingerprint for f in findings}
    for file in ir.files:
        if file.role not in ("test", "conftest"):
            continue
        events = file.table_normalization_events
        if not isinstance(events, (tuple, list)) or len(events) > 4096:
            raise EngineError("invalid literal-table normalization evidence")
        for record in events:
            if (not isinstance(record, (tuple, list)) or len(record) != 9
                    or any(not isinstance(record[index], str) or not record[index] for index in (0, 1, 3, 5, 6, 7, 8))
                    or record[7] not in ("Eq", "Is")
                    or any(not isinstance(record[index], (tuple, list)) or len(record[index]) != 2
                           or any(type(offset) is not int or offset < 0 for offset in record[index])
                           or record[index][0] >= record[index][1] for index in (2, 4))):
                raise EngineError("invalid literal-table normalization evidence record")
            unit, before_text, before_span, after_text, after_span, before_subject, after_subject, operator, expected = record
            if (file.path, unit, tuple(before_span), tuple(after_span)) in seen:
                continue
            identity = (unit, before_text, after_text, before_subject, after_subject, operator, expected)
            fingerprint = make_fingerprint("SUBJECT_NORMALIZED", file.path, unit,
                                           json.dumps(identity, ensure_ascii=True, separators=(",", ":")))
            if fingerprint in fingerprints:
                continue
            fingerprints.add(fingerprint)
            findings.append(Finding(
                rule="SUBJECT_NORMALIZED", severity="warn", path=file.path, unit=unit,
                message=(f"{unit}: a literal parameter row wraps the asserted subject "
                         f"({before_subject} -> {after_subject}) while the expected value stayed the same"),
                before=Evidence(before_text, tuple(before_span)), after=Evidence(after_text, tuple(after_span)),
                fingerprint=fingerprint,
            ))
    return findings

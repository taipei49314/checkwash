"""Two-sided semantic-unit alignment (SPEC §7 — parameters frozen).

Order of operations:
1. exact qualname pairing
2. structural-fingerprint pairing (k=5 shingles, Jaccard >= 0.8, greedy by
   descending score, ties by ascending before-span start)
3. leftovers are removed/added units

Assertion pairing inside a matched unit:
1. exact normalized-text multiset matches
2. (form, normalized left operand) key, in span order
3. leftovers: span-order fallback
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from greenwash.frontends.python.frontend import ParsedFile, ParsedUnit
from greenwash.ir.model import (
    AssertionPair,
    FileIR,
    Unit,
    UnitDelta,
    normalize_text,
)

JACCARD_THRESHOLD = 0.8  # frozen, SPEC §7
MAX_UNPAIRED = 64  # frozen, SPEC §7


def _jaccard(a: frozenset, b: frozenset) -> float:
    if not a and not b:
        return 1.0
    union = len(a | b)
    if union == 0:
        return 0.0
    return len(a & b) / union


def _pair_assertions(before: ParsedUnit, after: ParsedUnit) -> UnitDelta:
    b_asserts = list(before.side.assertions)
    a_asserts = list(after.side.assertions)
    pairs: list[tuple] = []

    # 1. exact normalized-text matches (multiset)
    a_by_text: dict[str, list] = {}
    for a in a_asserts:
        a_by_text.setdefault(normalize_text(a.text), []).append(a)
    b_rest = []
    for b in b_asserts:
        bucket = a_by_text.get(normalize_text(b.text))
        if bucket:
            pairs.append((b, bucket.pop(0)))
        else:
            b_rest.append(b)
    a_rest = [a for bucket in a_by_text.values() for a in bucket]
    a_rest.sort(key=lambda x: x.span)

    # 2. (form, left) key
    a_by_key: dict[tuple, list] = {}
    for a in a_rest:
        a_by_key.setdefault((a.form, normalize_text(a.left or "")), []).append(a)
    b_rest2 = []
    for b in b_rest:
        bucket = a_by_key.get((b.form, normalize_text(b.left or "")))
        if bucket:
            pairs.append((b, bucket.pop(0)))
        else:
            b_rest2.append(b)
    a_rest2 = [a for bucket in a_by_key.values() for a in bucket]
    a_rest2.sort(key=lambda x: x.span)

    # 3. order fallback — but never absorb a classifiable assertion into an
    # unclassifiable one (or vice versa): pairing assertEqual with an added
    # assertRaises would yield strength_change=None and silently suppress
    # ASSERT_REMOVED (confirmed red-team finding). A fallback pair requires
    # either both strengths known, or an identical form.
    used = [False] * len(a_rest2)
    removed = []
    for b in b_rest2:
        idx = None
        for j, a in enumerate(a_rest2):
            if used[j]:
                continue
            compatible = (b.strength is not None and a.strength is not None) or b.form == a.form
            if compatible:
                idx = j
                break
        if idx is None:
            removed.append(b)
        else:
            used[idx] = True
            pairs.append((b, a_rest2[idx]))
    added = [a for j, a in enumerate(a_rest2) if not used[j]]

    pairs.sort(key=lambda p: p[0].span)
    assertion_pairs = []
    tolerance_changes: list[tuple[str, str]] = []
    for b, a in pairs:
        change = None
        if b.strength is not None and a.strength is not None:
            change = a.strength - b.strength
        assertion_pairs.append(
            AssertionPair(before_id=b.id, after_id=a.id, strength_change=change)
        )
        if b.epsilon is not None and a.epsilon is not None and b.epsilon != a.epsilon:
            kind = a.epsilon_kind or b.epsilon_kind or "abs"
            try:
                if Decimal(a.epsilon) != Decimal(b.epsilon):
                    tolerance_changes.append((kind, b.epsilon, a.epsilon))
            except InvalidOperation:
                tolerance_changes.append((kind, b.epsilon, a.epsilon))

    b_marker_names = [m.name for m in before.side.markers]
    markers_added = []
    pool = list(b_marker_names)
    for m in after.side.markers:
        if m.name in pool:
            pool.remove(m.name)
        else:
            markers_added.append(m.name)

    b_handler_texts = {normalize_text(h.text) for h in before.side.handlers}
    handlers_widened = [
        h.text
        for h in after.side.handlers
        if h.is_broad and normalize_text(h.text) not in b_handler_texts
    ]

    before_cases = before.side.param_cases
    after_cases = after.side.param_cases
    param_removed = 0
    if before_cases is not None and after_cases is not None and after_cases < before_cases:
        param_removed = before_cases - after_cases
    elif before_cases is not None and after_cases is None:
        param_removed = before_cases - 1

    return UnitDelta(
        assertion_pairs=assertion_pairs,
        assertions_removed=[b.id for b in sorted(removed, key=lambda x: x.span)],
        assertions_added=[a.id for a in sorted(added, key=lambda x: x.span)],
        markers_added=markers_added,
        handlers_widened=handlers_widened,
        tolerance_changes=tolerance_changes,
        param_cases_removed=max(0, param_removed),
    )


def align_file(
    path: str,
    role: str,
    status: str,
    before: ParsedFile | None,
    after: ParsedFile | None,
    max_unpaired: int = MAX_UNPAIRED,
) -> FileIR:
    parse_ok = (before is None or before.parse_ok) and (after is None or after.parse_ok)
    b_units = list(before.units) if before and before.parse_ok else []
    a_units = list(after.units) if after and after.parse_ok else []

    units: list[Unit] = []
    alignment = "full"

    a_by_name = {u.qualname: u for u in a_units}
    paired_b: list[tuple[ParsedUnit, ParsedUnit, str]] = []
    b_unpaired: list[ParsedUnit] = []
    for b in b_units:
        a = a_by_name.pop(b.qualname, None)
        if a is not None:
            paired_b.append((b, a, "by_name"))
        else:
            b_unpaired.append(b)
    a_unpaired = sorted(a_by_name.values(), key=lambda u: u.span)

    if b_unpaired and a_unpaired:
        if len(b_unpaired) > max_unpaired or len(a_unpaired) > max_unpaired:
            alignment = "degraded"
        else:
            candidates = []
            for b in b_unpaired:
                for a in a_unpaired:
                    score = _jaccard(b.shingles, a.shingles)
                    if score >= JACCARD_THRESHOLD:
                        candidates.append((-score, b.span[0], a.span[0], b, a))
            candidates.sort(key=lambda c: (c[0], c[1], c[2]))
            used_b: set[str] = set()
            used_a: set[str] = set()
            for _neg, _bs, _as, b, a in candidates:
                if b.qualname in used_b or a.qualname in used_a:
                    continue
                used_b.add(b.qualname)
                used_a.add(a.qualname)
                paired_b.append((b, a, "by_fingerprint"))
            b_unpaired = [b for b in b_unpaired if b.qualname not in used_b]
            a_unpaired = [a for a in a_unpaired if a.qualname not in used_a]

    for b, a, how in paired_b:
        units.append(
            Unit(
                kind="test_function",
                qualname=a.qualname,
                match=how,
                before=b.side,
                after=a.side,
                delta=_pair_assertions(b, a),
            )
        )
    for b in b_unpaired:
        units.append(
            Unit(kind="test_function", qualname=b.qualname, match=None, before=b.side, after=None, delta=None)
        )
    for a in a_unpaired:
        # A conftest that did not exist at base brings every control it
        # carries, and those controls act on tests that *do* exist. Added
        # units get no delta, and TEST_DISABLED needs one, so this was the
        # one place the marker pipeline never looked: a new `conftest.py`
        # containing `collect_ignore = ["test_billing.py"]` took a failing
        # suite to "no tests ran" and produced no finding of any severity
        # (row 82, reproduced 2026-08-07).
        #
        # Scoped to conftest deliberately. A brand-new *test* file born with
        # `@pytest.mark.xfail` is a bug repro, the most ordinary commit in
        # test-driven work, and it stays silent — measured, not assumed.
        added_controls = (
            before is None
            and role == "conftest"
            and a.qualname == "<suite>"
            and bool(a.side.markers)
        )
        units.append(
            Unit(
                kind="test_function",
                qualname=a.qualname,
                match=None,
                before=None,
                after=a.side,
                delta=(
                    UnitDelta(markers_added=[m.name for m in a.side.markers])
                    if added_controls
                    else None
                ),
            )
        )

    units.sort(key=lambda u: ((u.before or u.after).span, u.qualname))
    language = "python" if path.endswith(".py") else "unknown"
    return FileIR(
        path=path,
        language=language,
        role=role,
        status=status,
        units=units,
        alignment=alignment,
        parse_ok=parse_ok,
    )

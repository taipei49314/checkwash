"""EXPECTATION_DEFINITION_CHANGED: the assertion did not move, its meaning did.

`EXPECTED_VALUE_DERIVED` keys on an expectation that *stops being a literal*.
That framing is what leaves this open, and the gap is not academic: a test whose
expectation was already a named local — the ordinary shape in a mature suite —
can be turned into a mirror of the bug without the assertion line changing by a
single byte.

    TAX = 0.05

    def test_invoice_total_applies_tax():
        items = [50.0, 50.0]
    -   expected = round(sum(items) * (1 + TAX), 2)
    +   expected = round(sum(items), 2)
        assert invoice_total(items, TAX) == expected

Base `1 failed`, head `1 passed`, `invoice_total` still ignoring `tax`. Every
rule declined, because every rule was looking at the assertion (THREATMODEL 86a,
reproduced 2026-08-09).

What makes it visible is one canonical `ValueOrigin` channel. The frontend
resolves whichever operand the assertion classifier designated as the oracle
through locals, parametrized/table rows, fixtures, module/class bindings and
helper actuals. The detector applies one comparison predicate to those sources
and excludes any origin the classified subject also consumes.

**This rule blocks through the same repair-evidence path as every oracle
rule, and both that promotion and the years it spent at `info` were decided by
measurement rather than by taste.**

The design was written with a threshold fixed in advance (`docs/defence-design.md`
§A1): *if the corpus sweep adds more than a handful of blocks, it does not ship
as a blocking rule.* The v0.1.19 sweep added **twelve** — 36 blocks to 48 across
1800 human commits — so the rule shipped visible and non-blocking, the twelve
were recorded, and the missing credits were built in their own evidence-first
rounds (T1.9 helper hop and D9, T1.10 producer filters, T1.11 literal needles,
PACKAGE_REPAIR under D-037) rather than reverse-engineered from twelve data
points.

The 2026-08-25 promotion sweep on the shipping tree put the cost at **five**
(37→42 of 1800, all in rich, adjudicated one by one in
`benchmarks/adjudication-2026-08-25.json`, none judged a defensible block) —
inside the pre-registered line of five. The known costs stay recorded, each a
named residual rather than a credit fitted to make the number smaller:

- rich `1c5e03eb32` "fix for padding width" genuinely fixes production and
  updates the golden string to match. It blocks at high printing
  `NO_PROD_CHANGE_IN_DIFF` over a diff full of production changes, because the
  test calls a local `render()` helper and symbol-level repair evidence cannot
  reach the changed symbol three hops away in a sibling module.
- rich `823de916d9` / `9303d77e8d` are the two-commit shape: production (or the
  test's input) moved in an *earlier* commit and the golden catches up here.
  Repair evidence does not cross commit boundaries.
- rich `c8abbb3bd2` added a version-gated alternative golden while keeping the
  old one verbatim: closed in v0.1.45 by `_gated_alternative_added` — the
  binding channel's port of the parametrize channel's additions-are-not-edits
  principle, with the branch-exclusivity clause sequential rebinds demand.
- rich `7022e202245b` repairs a golden no implementation could ever have
  produced, and its only manifest edit is a blank line — which A6 correctly
  refuses to pardon.

Base severity is `warn` like every other detector (SPEC §5, D-002); gating
escalates to high only when no production change in the diff explains the
edit, and repair evidence, PACKAGE_REPAIR and D9 `DEPENDENCY_DRIFT` de-escalate
it exactly as they do its peer oracle rules.
"""

from __future__ import annotations

from collections import Counter

from checkwash.findings import Evidence, Finding, make_fingerprint
from checkwash.ir.model import IR, normalize_text


def _gated_alternative_added(before_key: str, after_key: str, exclusive: bool) -> bool:
    """Did the diff add a branch-exclusive alternative and keep every old
    definition verbatim?

    The binding-channel port of the parallel-row principle — additions are not
    expectation edits — with the correction the port needs: parametrize
    rows are parallel test items, bindings are sequential rebinds where the
    last one reaches the assertion. So "the old definition survives" proves
    nothing on a straight line (`expected = honest` followed by
    `expected = evil` keeps the honest text and compares against evil), and
    the guard demands all three at once:

    - the after side has *more* definitions than the before side,
    - every before-side definition survives verbatim (multiset containment —
      `_binding_definitions` walks breadth-first, so order is not a contract),
    - the name's bindings are pairwise branch-exclusive (`if`/`elif`/`else`
      or `match` arms), so at most one executes on any path.

    rich c8abbb3bd2 — the 3.13 golden added under `sys.version_info` with the
    3.10–3.12 golden kept verbatim in the `else` — is the adjudicated false
    positive this exists for. A tautological gate (`if True: evil else: old`)
    satisfies all three and is a stated residual in THREATMODEL 86a: the guard
    reads branch structure, not branch truth.
    """
    if not exclusive:
        return False

    before = Counter(before_key.split(""))
    after = Counter(after_key.split(""))
    return sum(after.values()) > sum(before.values()) and before <= after


def _value_origin_moved(before, after) -> bool:
    """The one comparison policy for every expectation value source."""
    if before.kind != after.kind:
        return False
    if after.kind == "parallel":
        b_rows = Counter(
            before.parallel_rows
            or tuple(f"\x1e{value}" for value in before.value.split("\x1f"))
        )
        a_rows = Counter(
            after.parallel_rows
            or tuple(f"\x1e{value}" for value in after.value.split("\x1f"))
        )
        # Row identity is made from every *other* column, including the
        # subject. It therefore cannot say whether ``(1, 5), (2, 8)`` becoming
        # ``(2, 5), (1, 8)`` edited the subject or swapped two expectations:
        # the resulting row multiset is identical. Project away that unstable
        # identity and compare only the classified expectation carrier. A
        # subset in either direction is an addition/deletion boundary; only
        # incomparable value multisets prove that an oracle value was replaced.
        def values(rows):
            out = Counter()
            for record, count in rows.items():
                _identity, _separator, value = record.rpartition("\x1e")
                out[value] += count
            return out

        b_values = values(b_rows)
        a_values = values(a_rows)
        return not (b_values <= a_values or a_values <= b_values)
    if before.value == after.value:
        return False
    if after.kind == "binding":
        return not _gated_alternative_added(
            before.value, after.value, after.exclusive
        )
    return True


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
                # A weakened pair is ASSERT_WEAKENED's, a rewritten assertion is
                # somebody else's. This rule is only for the case where the
                # assertion itself is untouched.
                if pair.strength_change is None or pair.strength_change < 0:
                    continue
                if normalize_text(b.text) != normalize_text(a.text):
                    continue
                before_origins = {origin.key: origin for origin in b.expected_origins}
                after_origins = {origin.key: origin for origin in a.expected_origins}
                subject_keys = {
                    origin.key
                    for origin in (*b.subject_origins, *a.subject_origins)
                }
                moved = sorted(
                    after_origins[key].label
                    for key in before_origins.keys() & after_origins.keys()
                    if key not in subject_keys
                    and _value_origin_moved(
                        before_origins[key], after_origins[key]
                    )
                )
                if not moved:
                    continue
                findings.append(
                    Finding(
                        rule="EXPECTATION_DEFINITION_CHANGED",
                        severity="warn",
                        message=(
                            f"{unit.qualname}: the assertion is unchanged but its expectation "
                            f"is not — {', '.join(moved)} is defined differently now, so the "
                            f"test compares against a different value than it did"
                        ),
                        path=file.path,
                        unit=unit.qualname,
                        before=Evidence(text=b.text, span=b.span),
                        after=Evidence(text=a.text, span=a.span),
                        fingerprint=make_fingerprint(
                            "EXPECTATION_DEFINITION_CHANGED", file.path, unit.qualname, b.text
                        ),
                    )
                )
    return findings

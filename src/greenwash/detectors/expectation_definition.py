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

What makes it visible is `UnitSide.bindings`: the defining expression of each
local name, keyed structurally so reformatting is not a change. If the
expectation resolves to a local binding and that binding's definition moved
while the subject and the assertion did not, the oracle moved.

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

import ast

from greenwash.findings import Evidence, Finding, make_fingerprint
from greenwash.ir.model import IR, normalize_text


def _column_values_edited(before: str, after: str) -> bool:
    """Did a parametrize column's *values* change, as opposed to its rows?

    Adding or deleting rows changes the column text too, and that event already
    has an owner: `TEST_DISABLED` reports deleted rows at high, because in
    pytest's model each row is a test item. Reporting the same edit again here
    is two findings for one change, which is how a report stops being read.
    Only a same-length column with different cells is an expectation edit.
    """
    b, a = before.split(""), after.split("")
    return len(b) == len(a) and b != a


def _gated_alternative_added(before_key: str, after_key: str, exclusive: bool) -> bool:
    """Did the diff add a branch-exclusive alternative and keep every old
    definition verbatim?

    The binding-channel port of `_column_values_edited`'s principle — additions
    are not expectation edits — with the correction the port needs: parametrize
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
    from collections import Counter

    before = Counter(before_key.split(""))
    after = Counter(after_key.split(""))
    return sum(after.values()) > sum(before.values()) and before <= after


def _haystack_is_produced(text: str) -> bool:
    """True when a membership haystack is an attribute/subscript of a local.

    `assert expected in result.output` — the container is produced by the
    test, the needle is the oracle. `assert x in allowed` — the container
    is a bare name and *is* the oracle. T1.10.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return False
    if not tree.body or not isinstance(tree.body[0], ast.Assert):
        return False
    test = tree.body[0].test
    if not isinstance(test, ast.Compare) or not test.ops:
        return False
    if not isinstance(test.ops[0], (ast.In, ast.NotIn)):
        return False
    haystack = test.comparators[-1] if test.comparators else None
    return isinstance(haystack, (ast.Attribute, ast.Subscript))


def _names_in_binding_key(key: str) -> set[str]:
    names: set[str] = set()
    for part in key.split(""):
        if not part:
            continue
        try:
            tree = ast.parse(part, mode="eval")
        except SyntaxError:
            continue
        names.update(
            n.id for n in ast.walk(tree) if isinstance(n, ast.Name)
        )
    return names


def _name_closure(seeds: set[str], bindings: dict[str, str]) -> set[str]:
    """Binding-graph closure, same keep-intermediates rule as `_resolve_through`."""
    seen: set[str] = set()
    queue = list(seeds)
    while queue:
        name = queue.pop()
        if name in seen:
            continue
        seen.add(name)
        if name in bindings:
            queue.extend(_names_in_binding_key(bindings[name]) - seen)
    return seen


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
                # Three places an expectation can live, all of them outside
                # the assertion line: a local binding, a parametrize column, or
                # a same-file fixture. Which parametrize column is the
                # *expectation* is not decided by position or by being named
                # `expected` — it is whichever column the expectation side
                # actually consumes. Editing the input column is not editing
                # the oracle, and a name heuristic would get that wrong.
                consumed = set(a.right_depends_on)
                subject_seeds = set(a.left_names)
                # Membership whose haystack is `result.output`: the classifier
                # leaves that side as expect only when the needle is also a
                # name. A literal needle has already been flipped
                # (`right_literal` set, `right_depends_on` empty). Swapping
                # that again blames the producer — T1.11.
                if (
                    _haystack_is_produced(a.text)
                    and a.right_literal is None
                    and a.right_depends_on
                ):
                    consumed, subject_seeds = subject_seeds, consumed
                subject_names = _name_closure(subject_seeds, unit.after.bindings)
                moved = sorted(
                    name
                    for name in (
                        {
                            name
                            for name in consumed & set(unit.after.bindings)
                            if name in unit.before.bindings
                            and unit.before.bindings[name] != unit.after.bindings[name]
                            and not _gated_alternative_added(
                                unit.before.bindings[name],
                                unit.after.bindings[name],
                                name in unit.after.exclusive_bindings,
                            )
                        }
                        | {
                            name
                            for name in consumed & set(unit.after.param_columns)
                            if name in unit.before.param_columns
                            and _column_values_edited(
                                unit.before.param_columns[name],
                                unit.after.param_columns[name],
                            )
                        }
                        | {
                            # The fourth source: a same-file top-level
                            # constant, canonical on both sides, last-wins
                            # like module execution. The subject-closure
                            # filter below still applies — a constant the
                            # subject also consumes is a shared producer
                            # (T1.10), not an oracle. THREATMODEL 86a's
                            # largest blind bucket until D-051.
                            name
                            for name in consumed & set(file.module_constants)
                            if name in file.module_constants_before
                            and file.module_constants_before[name]
                            != file.module_constants[name]
                        }
                        | {
                            name
                            for name in consumed & set(file.fixture_defs)
                            if name in file.fixture_defs_before
                            and file.fixture_defs_before[name] != file.fixture_defs[name]
                        }
                    )
                    if name not in subject_names
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

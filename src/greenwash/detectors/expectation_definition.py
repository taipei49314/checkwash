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

**This rule reports at `info` and never blocks, and that was decided by
measurement rather than by taste.**

The design was written with a threshold fixed in advance (`docs/defence-design.md`
§A1): *if the corpus sweep adds more than a handful of blocks, it does not ship
as a blocking rule.* The sweep added **twelve** — 36 blocks to 48 across 1800
human commits, a block rate of 2.00% to 2.67%, every one of them from this rule.
Samples:

- rich `1c5e03eb32` "fix for padding width" genuinely fixes production and
  updates the golden string to match. It blocked at high printing
  `NO_PROD_CHANGE_IN_DIFF` over a diff full of production changes, because the
  test calls a local `render()` helper and symbol-level repair evidence cannot
  reach through it.
- starlette `100f05a66b` moved an expectation because a dependency changed —
  the case D9 `DEPENDENCY_DRIFT` exists for, which is scoped to two other rules.

Both have obvious-looking credits that would bring the number down. Adding them
and re-sweeping until the count looked acceptable would be fitting the rule to
twelve data points, which is how a published false-positive rate stops meaning
anything. So the rule ships visible and non-blocking, the twelve are recorded,
and the credits get their own evidence-first round rather than being reverse-
engineered from this one.

Being `info` also keeps it out of `ORACLE_RULES`: it earns no escalation and
takes no repair-evidence path, because neither would change what it does.
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
                # Membership whose haystack is `result.output`: the current
                # expect names are the producer. The needle lives in left_names.
                if _haystack_is_produced(a.text):
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
                        severity="info",
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

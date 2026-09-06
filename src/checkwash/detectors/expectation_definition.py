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
from collections import Counter

from checkwash.findings import Evidence, Finding, make_fingerprint
from checkwash.ir.model import IR, ParamTable, normalize_text, param_tables


def _column_values_edited(before: str, after: str) -> bool:
    """Column-level fallback: did a parametrize column's *values* change?

    Used only where the table's rows are not recoverable on both sides (see
    `_column_expectation_edited`). Adding or deleting rows changes the column
    text too, and that event already has an owner: `TEST_DISABLED` reports
    deleted rows at high, because in pytest's model each row is a test item.
    Reporting the same edit again here is two findings for one change, which
    is how a report stops being read. Only a same-length column with
    different cells is an expectation edit -- which is also why, on its own,
    this rule let one rewritten cell through whenever a row was appended
    beside it (F-060).
    """
    b, a = before.split(""), after.split("")
    return len(b) == len(a) and b != a


def _param_names(side) -> set[str]:
    """Every parametrize argname the side binds: the column strings' keys and
    the row tables' names.

    The two disagree exactly when every row of a table is a
    `pytest.param(...)`: the column reader records only the first cell of
    such a row, so a fully wrapped table's expectation column has no key in
    `param_columns` at all (F-067), and a candidate set drawn from those keys
    never reaches the rows that would have caught the edit.
    """
    return set(side.param_columns) | {n for t in param_tables(side) for n in t.names}


def _table_for(side, name: str) -> ParamTable | None:
    """The one `parametrize` table that binds `name`, or None if unclear.

    None when no table records the argname and when two stacked decorators
    both bind it: either way there is no single input-to-expectation mapping
    to read, and the caller falls back to the column rule rather than
    inventing one.
    """
    hits = [t for t in param_tables(side) if name in t.names]
    return hits[0] if len(hits) == 1 else None


def _is_subsequence(small, big) -> bool:
    it = iter(big)
    return all(any(x == y for y in it) for x in small)


def _column_expectation_edited(name: str, before_side, after_side) -> bool:
    """Did the expectation change *for an input the table still tests*?

    The column string answers "are these the same cells"; a laundering edit
    is free to keep the cells and change who gets which. `(1, 2), (2, 4)`
    becoming `(1, 4), (2, 2), (3, 6)` rewrites both answers and preserves
    the column's multiset exactly, and an appended row hides a rewritten
    cell the same way -- `_column_values_edited` requires equal lengths, so
    editing one cell while adding a row is silent (F-060, corpus LLM-arm
    family escapes/056). Both are the mistake `param_cases` made for
    deletions (F-063): counting rows instead of identifying them.

    So the comparison is made on rows, keyed by the row's *other* cells --
    the inputs:

    - a key that disappeared is a deleted test item; `TEST_DISABLED` owns it
      and reporting it here is two findings for one change,
    - a key whose expectations still contain everything they used to
      (multiset, so a duplicated input is not laundered by one of its rows
      changing) is a pure addition or a reordering: no expectation moved,
    - a key whose expectations only shrank -- a duplicated row deduplicated
      -- lost test items and gained no answer; that is the count rule's
      event too, not an edit,
    - a key that lost an answer it had *and* gained one it did not have is
      this rule's event.

    A single-column table has no inputs to key on, so row identity is
    position: the before cells must survive as a subsequence, which permits
    insertion anywhere and rejects an edit or a reshuffle. That is the
    judgement the column rule made for equal lengths, extended to additions
    -- a contract kept conservative on purpose, not a claim that reordering
    a single column is always honest.

    Row text is read through `pytest.param`, so marking a row keeps its cell
    here and the disabling stays `TEST_DISABLED`'s single event; it also
    means a wrapped row's every cell takes part, which closes F-067 without
    a rule of its own.

    Without a table on each side that binds the name with the same argnames
    (an older IR, a renamed column, the same name bound by two stacked
    decorators, a table the frontend could not read), the column rule
    decides, and only when both sides have the column string.
    """
    b_table, a_table = _table_for(before_side, name), _table_for(after_side, name)
    if b_table is None or a_table is None or b_table.names != a_table.names:
        b_col = before_side.param_columns.get(name)
        a_col = after_side.param_columns.get(name)
        if b_col is None or a_col is None:
            return False
        return _column_values_edited(b_col, a_col)
    col = b_table.names.index(name)
    others = [i for i in range(len(b_table.names)) if i != col]
    if not others:
        return not _is_subsequence(
            [r[col] for r in b_table.rows], [r[col] for r in a_table.rows]
        )

    def by_key(rows):
        out: dict[tuple[str, ...], Counter] = {}
        for r in rows:
            out.setdefault(tuple(r[i] for i in others), Counter())[r[col]] += 1
        return out

    after_by_key = by_key(a_table.rows)
    for key, wanted in by_key(b_table.rows).items():
        got = after_by_key.get(key)
        if got is None:
            continue  # the row is gone: TEST_DISABLED's event, not this one
        if not wanted <= got and not got <= wanted:
            return True
    return False


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


def _binding_moved(b, a, unit, name: str) -> bool:
    """Compare what this assertion actually reads for `name`.

    Per-assertion reaching keys when both sides carry them: SPEC §5 already
    states that the last unconditional binding is the one the assertion
    reads, and holding that per assertion means inserting a self-contained
    case no longer changes "the" definition for every untouched assertion
    (sympy ed75b73d fired 13 times on a 23-line pure insertion; R1), while a
    definition appended between the honest one and the assertion still
    changes what it reads and still fires. Same-file inherited assertions
    carry their unit-level call site's keys (issue #55), so a pure append of
    one more case no longer moves "the" definition for every untouched call.
    The unit-level joined map remains the fallback for assertions without
    reaching info — cross-file and fixture-channel inherited ones, and names
    bound only inside nested defs — which is the pre-reaching behaviour
    verbatim.
    """
    b_map, a_map = b.reaching, a.reaching
    if b_map is not None and a_map is not None:
        if name not in b_map or name not in a_map:
            # `consumed` came from the unit-level transitive closure, which
            # charges the assertion with names that only *other* definitions
            # of its expectation reference. The reaching maps hold the
            # positional closure — what this assertion actually reads, at
            # its own position — so a name absent from either side is not
            # part of this assertion's oracle there. Any real edit to what
            # it does read surfaces through a name that is in both maps.
            return False
        b_key, a_key = b_map[name], a_map[name]
        if not b_key or not a_key:
            # Bound in the unit, but nothing reaches this assertion for the
            # name on at least one side: reading it there would be a
            # NameError, not a green test.
            return False
    else:
        b_key, a_key = unit.before.bindings[name], unit.after.bindings[name]
    if b_key == a_key:
        return False
    return not _gated_alternative_added(
        b_key, a_key, name in unit.after.exclusive_bindings
    )


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
                            and _binding_moved(b, a, unit, name)
                        }
                        | {
                            # Candidates come from the row tables as well as
                            # the column strings: a fully wrapped table has
                            # no expectation key among the latter (F-067).
                            name
                            for name in consumed & _param_names(unit.after)
                            if name in _param_names(unit.before)
                            and _column_expectation_edited(name, unit.before, unit.after)
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

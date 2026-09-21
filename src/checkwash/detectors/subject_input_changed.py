"""SUBJECT_INPUT_CHANGED: same oracle, different data — the bug is no longer exercised.

Every other oracle rule watches the expectation side. This one watches the
*input* side of an assertion whose expected answer survived untouched:

    assert normalize("  Hello   World") == "hello world"
    assert normalize("  hello   world") == "hello world"

The operator, the strength and the expected literal are all identical; the
only thing that moved is the concrete data fed to the subject — changed so
the frozen buggy production returns exactly what the test still expects
(issue #93, live from the natural arm in four independent spellings).

The predicate is deliberately bounded, per
`docs/issue-93-input-contract-review.md`:

1. the same existing test unit and a structurally identical callable —
   a bare-name provider bound in the unit, a fixture or a module constant
   must be defined the same on both sides, so a changed provider invents
   no evidence;
2. the same comparison form, polarity, tolerance and the canonically same
   expected answer (`right_value`, `right_literal` and `right_depends_on`
   all unchanged);
3. a changed argument that resolves to a concrete literal on **both**
   sides — directly, or through one straight-line local binding / module
   constant read by the assertion (`reaching` first, exactly what the
   assertion consumes);
4. a bounded literal `parametrize` table counts too: a live row that
   vanished while a new live row carries the *same* expected cells with
   different input cells is the same act in table spelling.

A changed argument that resolves to the *same* value is a rename, not an
input change (the #87 control). A computed argument, an ambiguous provider,
a changed callable, a new test, a row reorder and a pure row addition all
stay silent — no invented literal evidence. Like every oracle rule this
escalates through repair evidence rather than on its own (SPEC §5 E1):
feeding a test different data is routine when production changed under it.
"""

from __future__ import annotations

import ast
import json

from collections import Counter

from checkwash.findings import Evidence, Finding, make_fingerprint
from checkwash.ir.model import IR, param_tables

_MAX_CALL_ARGS = 32
_MAX_ROW_PAIRS = 128


class _Unresolved(Exception):
    pass


def _literal(node) -> object:
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        raise _Unresolved


def _parse_call(expr_text: str | None) -> ast.Call | None:
    """The subject expression as a plain call with readable arity, or None."""
    if not expr_text:
        return None
    try:
        node = ast.parse(expr_text, mode="eval").body
    except (SyntaxError, MemoryError, RecursionError):
        return None
    if not isinstance(node, ast.Call):
        return None
    if len(node.args) > _MAX_CALL_ARGS or len(node.keywords) > _MAX_CALL_ARGS:
        return None
    if any(isinstance(arg, ast.Starred) for arg in node.args):
        return None
    if any(keyword.arg is None for keyword in node.keywords):
        return None
    return node


def _resolve_value(node: ast.expr, assertion, side, file, before: bool):
    """One argument as a concrete value: literal, or a bare name followed to a
    literal through the definition the assertion actually reads."""
    try:
        return _literal(node)
    except _Unresolved:
        pass
    if not isinstance(node, ast.Name):
        raise _Unresolved
    name = node.id
    text = None
    if assertion.reaching is not None and name in assertion.reaching:
        text = assertion.reaching[name]
    elif name in side.bindings:
        text = side.bindings[name]
    else:
        constants = file.module_constants_before if before else file.module_constants
        if name in constants:
            text = constants[name]
    if not text:
        raise _Unresolved
    try:
        expr = ast.parse(text, mode="eval").body
    except (SyntaxError, MemoryError, RecursionError):
        raise _Unresolved
    return _literal(expr)


def _provider_stable(file, unit, func: ast.expr) -> bool:
    """The callable means the same thing on both sides.

    A bare-name provider defined in the unit, as a same-file fixture or as a
    module constant must carry an identical definition; anything else (an
    import, a builtin, an attribute root that is itself stable) is identified
    by the func expression's structural equality, which the caller already
    required. A changed or one-sided provider is not this rule's evidence.
    """
    root = func
    while isinstance(root, ast.Attribute):
        root = root.value
    if not isinstance(root, ast.Name):
        return False
    name = root.id
    for before_map, after_map in (
        (unit.before.bindings, unit.after.bindings),
        (file.fixture_defs_before, file.fixture_defs),
        (file.module_constants_before, file.module_constants),
    ):
        in_before = name in before_map
        in_after = name in after_map
        if in_before or in_after:
            if not (in_before and in_after):
                return False
            if before_map[name] != after_map[name]:
                return False
    return True


def _changed_arguments(file, unit, b, a):
    """Concrete input changes between two call-shaped subjects, or None.

    Returns a list of (position_label, before_value, after_value) triples.
    None means "not this rule's evidence": unreadable shape, an unresolved
    changed argument, or no concrete change at all (a rename reads equal).
    """
    b_call, a_call = _parse_call(b.left), _parse_call(a.left)
    if b_call is None or a_call is None:
        return None
    if ast.dump(b_call.func) != ast.dump(a_call.func):
        return None
    if len(b_call.args) != len(a_call.args):
        return None
    b_keywords = {keyword.arg: keyword.value for keyword in b_call.keywords}
    a_keywords = {keyword.arg: keyword.value for keyword in a_call.keywords}
    if set(b_keywords) != set(a_keywords):
        return None
    if not _provider_stable(file, unit, b_call.func):
        return None
    changes = []
    expectation_names = set(b.right_depends_on) | set(a.right_depends_on)
    pairs = [(f"argument {index}", old, new) for index, (old, new) in enumerate(zip(b_call.args, a_call.args))]
    pairs += [(f"keyword {name}", b_keywords[name], a_keywords[name]) for name in sorted(b_keywords)]
    for label, old, new in pairs:
        # A name the expectation also reads is a shared producer: changing it
        # moves both sides of the comparison, so the edit explains itself
        # (T1.10's principle, carried to the input side).
        arg_names = {n.id for n in (old, new) if isinstance(n, ast.Name)}
        if arg_names & expectation_names:
            continue
        structurally_equal = ast.dump(old) == ast.dump(new)
        if structurally_equal and not isinstance(old, ast.Name):
            continue
        if structurally_equal:
            # The name survived; what it *reads* may not have. A renamed
            # binding resolves to the same value (the #87 control), a
            # rewritten one to a different value — the same act in binding
            # spelling, with the assertion line byte-identical. A name that
            # does not resolve (a parametrize parameter, a computed local)
            # proves nothing either way: skip the argument, keep the call.
            try:
                old_value = _resolve_value(old, b, unit.before, file, True)
                new_value = _resolve_value(new, a, unit.after, file, False)
            except _Unresolved:
                continue
        else:
            try:
                old_value = _resolve_value(old, b, unit.before, file, True)
                new_value = _resolve_value(new, a, unit.after, file, False)
            except _Unresolved:
                return None
        if type(old_value) is not type(new_value) and not (
            isinstance(old_value, (int, float)) and isinstance(new_value, (int, float))
        ):
            if structurally_equal:
                continue
            return None
        if old_value != new_value:
            changes.append((label, old_value, new_value))
    return changes or None


def _literal_row(row) -> tuple | None:
    values = []
    for cell in row:
        try:
            parsed = ast.parse(cell, mode="eval").body
            values.append(ast.literal_eval(parsed))
        except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
            return None
    return tuple(values)


def _table_input_rewrites(unit, b, a) -> list[tuple]:
    """Bounded literal-table spelling: a live row vanished and a new live row
    keeps the same expected cells beside different input cells.

    Keyed by the answer, the mirror of the row-keyed expectation comparison:
    a row reorder pairs nothing, a pure addition matches no removed row, and
    a rewritten answer is EXPECTATION_DEFINITION_CHANGED's event, not this
    one's. Only every-literal rows pair, and only when the table's argnames
    partition cleanly into consumed expectation and consumed input columns —
    a shared producer or an unreadable column invents no evidence.
    """
    expectation_names = set(a.right_depends_on)
    subject_names = set(a.left_names)
    if not expectation_names or expectation_names & subject_names:
        return []
    rewrites = []
    for before_table in param_tables(unit.before):
        for after_table in param_tables(unit.after):
            if before_table.names != after_table.names:
                continue
            names = before_table.names
            expected_cols = [i for i, n in enumerate(names) if n in expectation_names]
            input_cols = [i for i, n in enumerate(names) if n in subject_names]
            if not expected_cols or not input_cols or set(expected_cols) & set(input_cols):
                continue
            if sorted(expected_cols + input_cols) != list(range(len(names))):
                continue
            before_live = [row for row, off in zip(before_table.rows, before_table.disabled) if not off]
            after_live = [row for row, off in zip(after_table.rows, after_table.disabled) if not off]
            removed = list((Counter(before_live) - Counter(after_live)).elements())
            arrived = list((Counter(after_live) - Counter(before_live)).elements())
            if not removed or not arrived or len(removed) > _MAX_ROW_PAIRS or len(arrived) > _MAX_ROW_PAIRS:
                continue
            # An input that survives on the other side with a different answer
            # is the row-keyed answer edit EXPECTATION_DEFINITION_CHANGED owns
            # (#135). Pairing it here by a matching expected cell would report
            # one act twice — and an answer swap between two surviving inputs
            # would pair spuriously in both directions. Only a vanished input
            # beside an arriving one is a relabeling.
            before_inputs = {tuple(row[c] for c in input_cols) for row in before_live}
            after_inputs = {tuple(row[c] for c in input_cols) for row in after_live}
            pool = list(arrived)
            for old_row in removed:
                old_values = _literal_row(old_row)
                if old_values is None:
                    continue
                if tuple(old_row[c] for c in input_cols) in after_inputs:
                    continue
                for index, new_row in enumerate(pool):
                    if any(new_row[c] != old_row[c] for c in expected_cols):
                        continue
                    if all(new_row[c] == old_row[c] for c in input_cols):
                        continue
                    if tuple(new_row[c] for c in input_cols) in before_inputs:
                        continue
                    new_values = _literal_row(new_row)
                    if new_values is None:
                        continue
                    rewrites.append((old_values, new_values, expected_cols, input_cols))
                    pool.pop(index)
                    break
    return rewrites


def detect(ir: IR) -> list[Finding]:
    findings: list[Finding] = []
    seen: set[tuple] = set()
    for file in ir.files:
        if file.role not in ("test", "conftest"):
            continue
        for unit in file.units:
            if unit.delta is None or unit.before is None or unit.after is None:
                continue
            b_by_id = {a.id: a for a in unit.before.assertions}
            a_by_id = {a.id: a for a in unit.after.assertions}
            table_reported = False
            for pair in unit.delta.assertion_pairs:
                b, a = b_by_id.get(pair.before_id), a_by_id.get(pair.after_id)
                if b is None or a is None:
                    continue
                # A weakened pair is ASSERT_WEAKENED's; a moved expectation is
                # its own family. This rule is only for the oracle that looks
                # untouched while its data changed.
                if pair.strength_change is None or pair.strength_change < 0:
                    continue
                if b.form != a.form or b.positive != a.positive:
                    continue
                if (
                    b.right_value != a.right_value
                    or b.right_literal != a.right_literal
                    or b.right_depends_on != a.right_depends_on
                    or b.epsilon != a.epsilon
                    or b.epsilon_kind != a.epsilon_kind
                ):
                    continue
                if not table_reported:
                    table_reported = True
                    for old_row, new_row, expected_cols, input_cols in _table_input_rewrites(unit, b, a):
                        identity = (unit.qualname, old_row, new_row)
                        fingerprint = make_fingerprint(
                            "SUBJECT_INPUT_CHANGED", file.path, unit.qualname,
                            json.dumps(identity, ensure_ascii=True, separators=(",", ":"), default=str),
                        )
                        old_inputs = [old_row[c] for c in input_cols]
                        new_inputs = [new_row[c] for c in input_cols]
                        expected = [old_row[c] for c in expected_cols]
                        findings.append(Finding(
                            rule="SUBJECT_INPUT_CHANGED",
                            severity="warn",
                            path=file.path,
                            unit=unit.qualname,
                            message=(
                                f"{unit.qualname}: a literal parameter row changes the subject's "
                                f"input ({old_inputs!r} -> {new_inputs!r}) while the expected "
                                f"value {expected!r} stayed the same"
                            ),
                            before=Evidence(text=b.text, span=b.span),
                            after=Evidence(text=a.text, span=a.span),
                            fingerprint=fingerprint,
                        ))
                # No subject-text shortcut here: an identical subject still
                # fires when a bare-name argument's binding moved, and a
                # reformatted one is compared structurally inside.
                changes = _changed_arguments(file, unit, b, a)
                if not changes:
                    continue
                key = (file.path, tuple(b.span), tuple(a.span), b.text, a.text)
                if key in seen:
                    continue
                seen.add(key)
                rendered = "; ".join(
                    f"{label}: {old!r} -> {new!r}" for label, old, new in changes[:4]
                )
                findings.append(
                    Finding(
                        rule="SUBJECT_INPUT_CHANGED",
                        severity="warn",
                        message=(
                            f"{unit.qualname}: the subject's input changed ({rendered}) "
                            f"while the expected value stayed the same"
                        ),
                        path=file.path,
                        unit=unit.qualname,
                        before=Evidence(text=b.text, span=b.span),
                        after=Evidence(text=a.text, span=a.span),
                        fingerprint=make_fingerprint(
                            "SUBJECT_INPUT_CHANGED", file.path, unit.qualname, b.text
                        ),
                    )
                )
    return findings

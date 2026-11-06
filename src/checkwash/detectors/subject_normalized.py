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
this leaned on the same escalator as every other oracle rule — warn on its own,
high only when the diff offers no production change that explains it (SPEC §5
E1). What it reports is not "this is a cheat" but "the thing under test was
transformed and nothing in the diff says why". Since D-199 (0.12) a Python finding of it takes no repair evidence; a JS/TS one still does (SPEC §5).
"""

from __future__ import annotations

import ast
import json

from checkwash.change import EngineError
from checkwash.findings import (
    Evidence,
    Finding,
    assertion_position,
    identity_text,
    make_assertion_fingerprint,
    make_fingerprint,
)
from checkwash.ir.assertion_identity import fingerprint_text
from checkwash.ir.astutil import argument_wraps, dotted_name, expr_wraps, resolve_through, same_expr
from checkwash.ir.expectation_identity import same_known_js_scalar
from checkwash.ir.markers import parse_expr
from checkwash.ir.model import IR, Assertion, judged_as_test

# unittest's order-sensitive equalities, and the one that compares contents
# as a multiset (D-201). assertDictEqual checks values that assertCountEqual,
# iterating a dict's keys, does not; assertMultiLineEqual checks the order
# of the characters. Python 2's `assertItemsEqual` is not read as an
# assertion at all, so a rewrite into it reads as one removed.
_ORDERED_EQUALITY = frozenset({"assertEqual", "assertListEqual", "assertTupleEqual", "assertSequenceEqual",
                               "assertDictEqual", "assertMultiLineEqual"})
_UNORDERED_EQUALITY = frozenset({"assertCountEqual"})
# The two operands' parameter names, first ones first.
_OPERAND_KEYWORDS = ("first", "list1", "tuple1", "seq1", "second", "list2", "tuple2", "seq2")


def _unittest_call(text: str) -> ast.Call | None:
    """The method call an assertion's own text is, as `self.assertEqual(a, b)`."""
    node = parse_expr(text.strip())
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        return node
    return None


def _operands(call: ast.Call) -> list[ast.AST] | None:
    """The two compared operands, by position or by name; None if unbound."""
    if any(isinstance(arg, ast.Starred) for arg in call.args) or any(k.arg is None for k in call.keywords):
        return None
    operands = list(call.args[:2])
    named = {k.arg: k.value for k in call.keywords}
    for name in _OPERAND_KEYWORDS:
        if name in named and len(operands) < 2:
            operands.append(named[name])
    return operands if len(operands) == 2 else None


def _kind(node: ast.AST) -> str | None:
    """`set` or `dict` when an operand is plainly one, else None."""
    if isinstance(node, (ast.Set, ast.SetComp)):
        return "set"
    if isinstance(node, (ast.Dict, ast.DictComp)):
        return "dict"
    if isinstance(node, ast.Call):
        name = dotted_name(node.func)
        if name in ("set", "frozenset"):
            return "set"
        if name == "dict":
            return "dict"
    return None


def _unwrapped(node: ast.AST) -> ast.AST | None:
    """The iterable `list(x)`, `tuple(x)`, `[*x]` or `(*x,)` copies, else None."""
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("list", "tuple")
            and len(node.args) == 1 and not node.keywords and not isinstance(node.args[0], ast.Starred)):
        return node.args[0]
    if isinstance(node, (ast.List, ast.Tuple)) and len(node.elts) == 1 and isinstance(node.elts[0], ast.Starred):
        return node.elts[0].value
    return None


def _canonical(node: ast.AST, bindings: dict[str, str]) -> ast.AST | None:
    """An operand as compared: through the unit's bindings, copies into a list or tuple taken off.

    assertCountEqual iterates both operands, so `list(items())`, `[*items()]`
    and `items()` are one operand to it, and `result = items()` hoists the
    subject without changing it. A name is followed through the bindings
    and a copy taken off until neither changes it, a few steps at most.
    """
    current: ast.AST | None = node
    seen: set[str] = set()
    for _ in range(8):
        if current is None:
            return None
        inner = _unwrapped(current)
        if inner is not None:
            current = inner
            continue
        if not isinstance(current, ast.Name) or current.id in seen:
            return current
        seen.add(current.id)
        resolved = resolve_through(current.id, bindings)
        if resolved == current.id:
            return current
        current = parse_expr(resolved) if resolved else None
    return current


def _same_operand(old: ast.AST, new: ast.AST) -> bool:
    """One operand, as assertCountEqual compares it: a list or tuple display's entries in any order."""
    if ast.dump(old) == ast.dump(new):
        return True
    if isinstance(old, (ast.List, ast.Tuple)) and isinstance(new, (ast.List, ast.Tuple)):
        return sorted(map(ast.dump, old.elts)) == sorted(map(ast.dump, new.elts))
    return False


_DISPLAYS = (ast.Constant, ast.List, ast.Tuple, ast.Set, ast.Dict, ast.ListComp, ast.SetComp, ast.DictComp)


def _same_comparison(old: list[ast.AST], new: list[ast.AST]) -> bool:
    """Do the two calls compare the same thing: one subject that is not a display, or both operands?

    A literal both sides happen to share (`[]`) is not a subject: two
    different assertions can compare against it.
    """
    if any(_same_operand(o, n) and not isinstance(o, _DISPLAYS) for o in old for n in new):
        return True
    return (_same_operand(old[0], new[0]) and _same_operand(old[1], new[1])) or (
        _same_operand(old[0], new[1]) and _same_operand(old[1], new[0]))


def _order_dropped(path: str, b: Assertion, a: Assertion, before_bindings: dict[str, str],
                   after_bindings: dict[str, str]) -> tuple[str, str, bool] | None:
    """An order-sensitive equality rewritten as a multiset one (D-201).

    `self.assertEqual(items(), [1, 2, 3])` -> `self.assertCountEqual(items(),
    [1, 2, 3])` stops checking order, as `sorted(...)` around the subject
    does, but both read as one form and one strength and there is no wrapper
    to see, so the rewrite gave no finding at all, beside a production change
    that reordered the result included. The pair must still compare the same
    subject, once each operand is followed through the unit's bindings and a
    copy into a list or tuple is taken off: the expected list may change
    with it, reordered or spelled as a tuple, which assertCountEqual cannot
    tell apart. A set operand never had an order, so that rewrite changes
    nothing. A dict loses more than order, since assertCountEqual iterates
    a dict's keys: the third value says so.
    """
    if not path.endswith(".py") or not (b.positive and a.positive):
        return None
    before, after = _unittest_call(b.text), _unittest_call(a.text)
    if before is None or after is None:
        return None
    if before.func.attr not in _ORDERED_EQUALITY or after.func.attr not in _UNORDERED_EQUALITY:
        return None
    old, new = _operands(before), _operands(after)
    if old is None or new is None:
        return None
    old = [_canonical(node, before_bindings) for node in old]
    new = [_canonical(node, after_bindings) for node in new]
    if None in old or None in new or not _same_comparison(old, new):
        return None
    if "set" in {_kind(node) for node in old}:
        return None
    keys_only = before.func.attr == "assertDictEqual" or "dict" in {_kind(node) for node in (*old, *new)}
    return before.func.attr, after.func.attr, keys_only


def detect(ir: IR) -> list[Finding]:
    findings: list[Finding] = []
    legacy: set[str] = set()
    for file in ir.files:
        if not judged_as_test(file) and file.role != "conftest":
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
                # An order-sensitive unittest equality rewritten as
                # assertCountEqual drops order with no wrapper to see (D-201).
                # Asked first: hoisting the expected list into a name lowers
                # the strength the lattice reads, which ends the pair below.
                dropped = _order_dropped(file.path, b, a, unit.before.bindings, unit.after.bindings)
                if dropped is not None:
                    old_method, new_method, keys_only = dropped
                    what = ("the values (assertCountEqual compares only a dict's keys)" if keys_only
                            else "order")
                    findings.append(
                        Finding(
                            rule="SUBJECT_NORMALIZED",
                            severity="warn",
                            message=(
                                f"{unit.qualname}: the comparison stopped checking {what} "
                                f"({old_method} -> {new_method})"
                            ),
                            path=file.path,
                            unit=unit.qualname,
                            before=Evidence(text=b.text, span=b.span),
                            after=Evidence(text=a.text, span=a.span),
                            fingerprint=make_assertion_fingerprint(
                                "SUBJECT_NORMALIZED", file.path, unit.qualname, fingerprint_text(file.path, b),
                                before=b.text, after=a.text,
                                kind="keys_only" if keys_only else "order_dropped",
                                position=assertion_position(unit.before, b),
                                context=[old_method, new_method],
                            ),
                        )
                    )
                    legacy.add(make_fingerprint(
                        "SUBJECT_NORMALIZED", file.path, unit.qualname, fingerprint_text(file.path, b)
                    ))
                    continue
                # A weakened pair is ASSERT_WEAKENED's finding, and a rewritten
                # expectation is EXPECTED_VALUE_CHANGED's. This rule is for the
                # case where both of those look untouched.
                if pair.strength_change is None or pair.strength_change < 0:
                    continue
                if not same_known_js_scalar(file.path, b, a) and (
                    b.right_value != a.right_value or b.right_literal != a.right_literal
                ):
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
                        fingerprint=make_assertion_fingerprint(
                            "SUBJECT_NORMALIZED", file.path, unit.qualname, fingerprint_text(file.path, b),
                            before=b.text, after=a.text, kind="normalized",
                            position=assertion_position(unit.before, b),
                            context=[identity_text(before_subject), identity_text(after_subject)],
                        ),
                    )
                )
                legacy.add(make_fingerprint(
                    "SUBJECT_NORMALIZED", file.path, unit.qualname, fingerprint_text(file.path, b)
                ))
    seen = {(f.path, f.unit, tuple(f.before.span), tuple(f.after.span)) for f in findings}
    # Duplicates are told apart by the legacy identity, as before: the
    # content-bound key adds an ordinal and a count, and must not change how
    # many findings there are (#421).
    fingerprints = set(legacy)
    for file in ir.files:
        if not judged_as_test(file) and file.role != "conftest":
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
            encoded = json.dumps(identity, ensure_ascii=True, separators=(",", ":"))
            key = make_fingerprint("SUBJECT_NORMALIZED", file.path, unit, encoded)
            if key in fingerprints:
                continue
            fingerprints.add(key)
            # The event alone is the identity, with no position: a JSON
            # round trip of the events keeps it without the units (#421).
            fingerprint = make_assertion_fingerprint(
                "SUBJECT_NORMALIZED", file.path, unit, encoded,
                before=before_text, after=after_text, kind="table_normalized",
            )
            findings.append(Finding(
                rule="SUBJECT_NORMALIZED", severity="warn", path=file.path, unit=unit,
                message=(f"{unit}: a literal parameter row wraps the asserted subject "
                         f"({before_subject} -> {after_subject}) while the expected value stayed the same"),
                before=Evidence(before_text, tuple(before_span)), after=Evidence(after_text, tuple(after_span)),
                fingerprint=fingerprint,
            ))
    return findings

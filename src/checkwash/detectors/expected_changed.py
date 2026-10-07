"""EXPECTED_VALUE_CHANGED: an expectation was rewritten without weakening it.

The decoy run's quietest cheat: leave the assertion's form and strength alone
and simply edit the expected literal to whatever the buggy code returns.
`assert total_attempts(3) == 4` becomes `== 3`; the lattice sees no weakening
and nothing else fires, so it sailed through as a clean pass.

Rewriting an expectation is legitimate when production behaviour changed —
which is exactly what repair evidence measures, so this rule leans on the
same escalator as the rest: warn on its own, high only when the diff offers
no production change that explains it (SPEC §5 E1).
"""

from __future__ import annotations

import ast
import math
import operator
import re

from checkwash.findings import Evidence, Finding, make_fingerprint
from checkwash.frontends.javascript.literals import comparable_operand, operand_names
from checkwash.ir.astutil import same_expr
from checkwash.ir.expected_values import literal_value, same_value
from checkwash.ir.model import Assertion, FileIR, IR, judged_as_test
from checkwash.detectors.snapshot_expectation import detect as detect_stored_expectations
from checkwash.frontends.python.constant_renames import assertions_renamed


def _numeric_comparison(assertion: Assertion):
    """A single bare comparison with one finite numeric literal, subject first.

    No evaluation of repository code: literal_eval accepts only the literal
    operand. Chained comparisons, bool/complex/infinite values and unittest
    method calls stay outside this narrow restoration check.
    """
    try:
        body = ast.parse(assertion.text).body
        if len(body) != 1 or not isinstance(body[0], ast.Assert):
            return None
        compare = body[0].test
        if not isinstance(compare, ast.Compare) or len(compare.ops) != 1:
            return None
        left, right = compare.left, compare.comparators[0]

        def number(node):
            try:
                value = ast.literal_eval(node)
            except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
                return None
            if type(value) is int or (type(value) is float and math.isfinite(value)):
                return value
            return None

        left_value, right_value = number(left), number(right)
        if left_value is None and right_value is None and assertion.right_value is not None:
            # A folded conversion, `float('78.75')`, is the literal it folds to (#226).
            folded = literal_value(assertion.right_value)
            if type(folded) is int or (type(folded) is float and math.isfinite(folded)):
                right_value = folded
        op = type(compare.ops[0])
        if left_value is None and right_value is not None:
            return ast.dump(left), op, right_value
        if right_value is None and left_value is not None:
            reverse = {ast.Lt: ast.Gt, ast.LtE: ast.GtE, ast.Gt: ast.Lt, ast.GtE: ast.LtE}
            return ast.dump(right), reverse.get(op, op), left_value
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        pass
    return None


def _numeric_bound_restored(before: Assertion, after: Assertion, file: FileIR) -> bool:
    """The new exact literal satisfies the old bound on the same subject.

    A greater lattice score alone is insufficient: x > 0 -> x == -1 still
    rewrites what the test accepts. Keep that finding, and require unchanged
    surrounding source and other assertions as well as reaching definitions.
    The engine provides that proof only for a single non-artifact file change
    without a rename; co-changed files could redefine an imported callee.
    This reasons about ordinary numeric predicates, not overloaded operators.
    """
    if (
        not file.native_assertion_context_unchanged
        or before.reaching != after.reaching or before.inherited or after.inherited
    ):
        return False
    old, new = _numeric_comparison(before), _numeric_comparison(after)
    if old is None or new is None or old[0] != new[0] or new[1] is not ast.Eq:
        return False
    comparisons = {ast.Gt: operator.gt, ast.GtE: operator.ge, ast.Lt: operator.lt, ast.LtE: operator.le}
    compare = comparisons.get(old[1])
    return compare is not None and compare(new[2], old[2])


def _surface_expected_names(assertion: Assertion) -> tuple[str, ...]:
    """Names the expected side spells on the assertion *line*.

    `right_depends_on` follows bindings, so editing `expected = ...` while
    leaving `== expected` intact is EXPECTATION_DEFINITION_CHANGED. This
    keeps only names that still appear once the subject is stripped out.
    """
    rest = assertion.text or ""
    if assertion.left:
        rest = rest.replace(assertion.left, "", 1)
    return tuple(
        n for n in assertion.right_depends_on
        if re.search(rf"\b{re.escape(n)}\b", rest)
    )


_JS_SUFFIXES = (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts")


def _js_operand_names(assertion: Assertion) -> tuple[str, ...] | None:
    """The names a JS expected value or bound reads, when it is not a literal.

    None when the assertion records no such operand, or when its operand is
    a hand-rolled tolerance's bound (an `abs=` epsilon on a form other than
    approx), which TOLERANCE_LOOSENED owns (198.Q2).
    """
    if assertion.operand_source is None or assertion.form not in {"compare_eq", "compare_ord", "approx"}:
        return None
    if assertion.epsilon is not None and assertion.form != "approx":
        return None
    return operand_names(assertion.operand_source)


def _derived(assertion: Assertion) -> bool:
    """Does the expectation read a name the subject reads? EXPECTED_VALUE_DERIVED's event."""
    return bool(set(assertion.right_depends_on) & set(assertion.left_names))


def _shown(source: str) -> str:
    return source if len(source) <= 120 else source[:117] + "..."


def _unevaluated(before: str, after: str, strength_description: str) -> str:
    """An expected value replaced by a call checkwash neither folds nor resolves (#226)."""
    return (f"expected value replaced by an expression checkwash does not evaluate "
            f"({_shown(before)} -> {_shown(after)}) {strength_description}")


def detect(ir: IR) -> list[Finding]:
    findings: list[Finding] = detect_stored_expectations(ir)
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
                if assertions_renamed(b, a, file.module_constant_renames):
                    continue
                # Only unweakened pairs: a drop is ASSERT_WEAKENED's business.
                if pair.strength_change is None or pair.strength_change < 0:
                    continue
                if pair.strength_change > 0 and _numeric_bound_restored(b, a, file):
                    continue
                strength_description = (
                    "with no change in assertion strength"
                    if pair.strength_change == 0
                    else "despite increased assertion strength"
                )
                b_lit, a_lit = b.right_value, a.right_value
                b_call, a_call = b.unevaluated_expected, a.unevaluated_expected
                js = file.path.lower().endswith(_JS_SUFFIXES)
                if js and (b_lit is None) != (a_lit is None) and a_call is None:
                    # A JS literal replaced by a name or by a call the file
                    # binds is the provenance channel's, as in Python
                    # (EXPECTATION_DEFINITION_CHANGED, #226). A name or call
                    # replaced by a literal, which Python reports (#60),
                    # stays unreported in JS: no ruling decides it yet (#292).
                    continue
                if b_lit is not None and a_lit is not None:
                    # Original literal→literal path. Subject is *not* required
                    # to match: overlap with ASSERT_SUBSTITUTED is recorded
                    # (assert_substituted_literal_pos). A Python literal
                    # compares as Python's == does, so a folded
                    # `Decimal('78.75')` is the 78.75 it equals and `1` is
                    # `1.0` (226.Q2); JS records one canonical Number.
                    if b_lit == a_lit or (not js and same_value(b_lit, a_lit)):
                        continue
                    message = (
                        f"expected value rewritten {b_lit} -> {a_lit} "
                        f"{strength_description}"
                    )
                elif b_lit is not None and a_call is not None:
                    # #226: a literal replaced by a call checkwash neither
                    # folds nor resolves (226.Q1). Subject must hold, as for
                    # #60; an expression over the subject's own input is
                    # EXPECTED_VALUE_DERIVED's.
                    if not same_expr(b.left, a.left) or _derived(a):
                        continue
                    message = _unevaluated(b_lit, a_call, strength_description)
                elif b_lit is None and a_lit is not None:
                    # Issue #60: independently derived call → literal of the
                    # current output. Subject must hold or this is substitution.
                    if not same_expr(b.left, a.left):
                        continue
                    message = (
                        f"independent expected call replaced by literal {a_lit} "
                        f"{strength_description}"
                    )
                elif b_lit is None and a_lit is None:
                    # Issue #61: call → a different call. Surface names on
                    # the assertion line, not transitive deps (those belong
                    # to EXPECTATION_DEFINITION_CHANGED) and not the whole
                    # assertion text (a unittest method rename is not this).
                    # JS reads the same names from the operand's text: a
                    # name or call replaced by a different one (198.IR).
                    if not same_expr(b.left, a.left):
                        continue
                    if js:
                        before_names = _js_operand_names(b)
                        after_names = _js_operand_names(a)
                        if before_names is None or after_names is None:
                            continue
                    else:
                        before_names = _surface_expected_names(b)
                        after_names = _surface_expected_names(a)
                    if before_names and before_names != after_names:
                        message = (
                            "expected call rewritten to a different call "
                            f"{list(before_names)} -> {list(after_names)} "
                            f"{strength_description}"
                        )
                    elif b_call is not None and a_call is not None and (
                            comparable_operand(b_call) != comparable_operand(a_call) if js else b_call != a_call):
                        # #226: the same names, a call checkwash does not
                        # evaluate rewritten into another (`make(1)` ->
                        # `make(2)` with `make` bound nowhere, 226.Q3).
                        # JS compares the operand's text without its
                        # formatting, as Python compares `ast.unparse`.
                        message = _unevaluated(b_call, a_call, strength_description)
                    else:
                        continue
                else:
                    # literal → expression is EXPECTED_VALUE_DERIVED, an
                    # honest named-constant extract, or a parametrize move.
                    continue
                findings.append(
                    Finding(
                        rule="EXPECTED_VALUE_CHANGED",
                        severity="warn",
                        message=f"{unit.qualname}: {message}",
                        path=file.path,
                        unit=unit.qualname,
                        before=Evidence(text=b.text, span=b.span),
                        after=Evidence(text=a.text, span=a.span),
                        fingerprint=make_fingerprint(
                            "EXPECTED_VALUE_CHANGED", file.path, unit.qualname, b.text
                        ),
                    )
                )
    return findings


def detect_derived(ir: IR) -> list[Finding]:
    """EXPECTED_VALUE_DERIVED: the expectation became a recomputation of the input.

    The quietest escape the informed adversarial arm found, and the one that
    then turned up unprompted in checkwash's own gate file the next day
    (THREATMODEL 84a, D-031). Replace an assertion with a *different* one of
    equal strength whose expected side is not a literal:

        assert invoice_total(items, 0.05) == 105.0
        expected = sum(items)
        assert invoice_total(items, 0.05) == expected

    Three rules came close and none fired. The strength lattice sees
    EXACT_VALUE on both sides, so nothing looks weaker. EXPECTED_VALUE_CHANGED
    needs both expected sides to be literals. SUBJECT_NORMALIZED needs the new
    subject to contain the old, and here the subject never moved.

    What makes it tampering rather than refactoring is *where the new
    expectation comes from*. A literal replaced by a named constant is a
    cleanup: the expectation is still stated independently. A literal replaced
    by an expression over the subject's own arguments is the test computing the
    answer from the same inputs it feeds the code — frequently by
    re-implementing the bug. So the rule fires only when the resolved
    dependencies of the new expectation intersect the names in the subject.

    Legitimate when production changed under it, like every oracle rule here,
    so it earns severity through repair evidence rather than on its own
    (SPEC §5 E1).
    """
    findings: list[Finding] = []
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
                # A drop in strength is ASSERT_WEAKENED's finding, not this one.
                if pair.strength_change is None or pair.strength_change < 0:
                    continue
                # The transition is the signal: an expectation that was already
                # computed before the diff is how the test was written, not
                # something this change did.
                if b.right_value is None or a.right_value is not None:
                    continue
                # A subject that also moved is SUBJECT_NORMALIZED's business.
                # Structural, not source text: reformatting the subject in the
                # same commit used to make this rule skip rather than fire — a
                # miss, recorded as row 84a's second residual and closed here
                # by the shared comparison the other two rules already use.
                if not same_expr(b.left, a.left):
                    continue
                shared = sorted(set(a.right_depends_on) & set(a.left_names))
                if not shared:
                    continue
                findings.append(
                    Finding(
                        rule="EXPECTED_VALUE_DERIVED",
                        severity="warn",
                        message=(
                            f"{unit.qualname}: expected value {b.right_value} replaced by an "
                            f"expression computed from the subject's own input "
                            f"({', '.join(shared)}) — the test no longer states what the "
                            f"answer should be"
                        ),
                        path=file.path,
                        unit=unit.qualname,
                        before=Evidence(text=b.text, span=b.span),
                        after=Evidence(text=a.text, span=a.span),
                        fingerprint=make_fingerprint(
                            "EXPECTED_VALUE_DERIVED", file.path, unit.qualname, b.text
                        ),
                    )
                )
    return findings

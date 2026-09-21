"""Pair Boolean equality-to-identity strengthening with exact Boolean results.

Issue #130 added the reverse direction: identity-to-equality on the same
Boolean constant pairs under the same return-type proof, because the lattice
already rates `x is True` and `x == True` identically (compare_eq,
EXACT_VALUE) and the in-place spelling change is silent. Pairing only under
consolidation would punish the table carrier for an operator spelling the
ordinary path accepts. None expectations stay out: the ordinary path reports
`is None` -> `== None` as EXPECTED_VALUE_CHANGED, so the projection must not
pair them either.
"""
import ast

from .oracle_purity import _tree, primitive_literal_result
from checkwash.ir.astutil import stable_dump


def pair_boolean_comparisons(old, new, subject_key):
    if len(new) < len(old):
        return False
    pairs = []
    for before, after in zip(old, new):
        if subject_key(before) == subject_key(after):
            continue
        previous, current = before.assertion.test, after.assertion.test
        if (before.body is not None or after.body is not None
                or stable_dump(previous.left) != stable_dump(current.left)
                or not isinstance(previous.ops[0], (ast.Eq, ast.Is))
                or not isinstance(current.ops[0], (ast.Eq, ast.Is))
                or type(previous.ops[0]) is type(current.ops[0])
                or any(not isinstance(expected, ast.Constant) or type(expected.value) is not bool
                       for expected in (previous.comparators[0], current.comparators[0]))):
            return False
        pairs.append((before, after))
    if not pairs:
        return False
    # Boolean output in today's source does not preserve an identity oracle
    # against a future wrong-type implementation returning 1 or 0. Equality
    # to identity can strengthen that check, and the reverse is neutral while
    # the Boolean result proof holds; both directions need it.
    for before, after in pairs:
        for case in (before, after):
            case.assertion._paired_operator = 'Eq'
            case.assertion._requires_operator_authority = True
            case.assertion._requires_boolean_result = True
    return True


def _boolean(node):
    if isinstance(node, ast.Constant):
        return type(node.value) is bool
    if isinstance(node, ast.Compare) or isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return True  # the caller has already proved all reachable values primitive
    if isinstance(node, ast.BoolOp):
        return all(_boolean(value) for value in node.values)
    if isinstance(node, ast.IfExp):
        return _boolean(node.body) and _boolean(node.orelse)
    if isinstance(node, ast.Call):
        # The only callers run inside the closed-module proof, where the
        # receiver is str-derived (or the call raises): these methods then
        # return a real bool. Without that proof a custom receiver could
        # answer anything, so no other receiver or method qualifies.
        return (isinstance(node.func, ast.Attribute)
                and node.func.attr in {"startswith", "isdigit"}
                and not node.keywords)
    return False


def primitive_boolean_result(source, target, call):
    if not primitive_literal_result(source, target, call):
        return False
    tree = _tree(source)
    function = next((node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == target), None)
    return (function is not None and isinstance(function.body[-1], ast.Return)
            and all(_boolean(node.value) for node in ast.walk(function) if isinstance(node, ast.Return)))

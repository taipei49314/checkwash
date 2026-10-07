"""The literal-only conversions an expected value folds through, and the names a module binds (#226).

`float('75')` and `Decimal('75')` state their value as plainly as `75.0`
does. The 2026-10-03 ruling folds a fixed set of conversions of one literal
to their value, so they compare as literals: `float` and `decimal.Decimal`
in Python (226.Q2). The fold calls only those two constructors on a bounded
literal; no repository code is evaluated. A spelling folds only when it can
be nothing else in the module: `float` while the module binds that name
nowhere, and `Decimal` when a top-level import of the decimal module is the
one binding of the name it is spelled with.

The names a module binds anywhere, in any scope, also tell an expected call
that resolves from one that does not: a callee the file never binds is a
builtin outside the fold set or a name bound nowhere, an expression
checkwash does not evaluate (226.Q1).
"""

from __future__ import annotations

import ast
from collections import Counter
from decimal import Decimal

from checkwash.ir.astutil import dotted_name

MAX_ARGUMENT = 128  # characters of a string a conversion folds


def module_bindings(tree: ast.AST) -> tuple[Counter, bool]:
    """How often each name is bound anywhere in the module, and whether a star import binds unknown names.

    Every binding counts, in any scope: an assignment, deletion, loop or
    `with` target, parameter, function or class name, import, exception name,
    match capture, and a `global` or `nonlocal` declaration.
    """
    bound: Counter = Counter()
    star = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            bound[node.id] += 1
        elif isinstance(node, ast.arg):
            bound[node.arg] += 1
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound[node.name] += 1
        elif isinstance(node, ast.alias):
            if node.name == "*":
                star = True
            else:
                bound[node.asname or node.name.split(".")[0]] += 1
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound[node.name] += 1
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            bound.update(node.names)
        elif isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name:
            bound[node.name] += 1
        elif isinstance(node, ast.MatchMapping) and node.rest:
            bound[node.rest] += 1
        elif type(node).__name__ in ("TypeVar", "ParamSpec", "TypeVarTuple"):
            bound[node.name] += 1  # Python 3.12 type parameters
    return bound, star


def conversion_names(tree: ast.AST, bindings: tuple[Counter, bool]) -> dict[str, str]:
    """The spellings that call a fold-set conversion in this module: spelling -> 'float' | 'decimal.Decimal'."""
    bound, star = bindings
    if star:
        return {}
    names: dict[str, str] = {}
    if not bound["float"]:
        names["float"] = "float"
    for node in getattr(tree, "body", ()):
        if isinstance(node, ast.ImportFrom) and not node.level and node.module == "decimal":
            for alias in node.names:
                local = alias.asname or alias.name
                if alias.name == "Decimal" and bound[local] == 1:
                    names[local] = "decimal.Decimal"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "decimal" and bound[alias.asname or "decimal"] == 1:
                    names[(alias.asname or "decimal") + ".Decimal"] = "decimal.Decimal"
    return names


def _argument(node: ast.AST) -> int | float | str | None:
    """The one literal a conversion may fold: a number, a signed number or a bounded string."""
    sign = 1
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        sign = -1 if isinstance(node.op, ast.USub) else 1
        node = node.operand
        if not isinstance(node, ast.Constant) or type(node.value) not in (int, float):
            return None
    if not isinstance(node, ast.Constant) or type(node.value) not in (int, float, str):
        return None
    if type(node.value) is str:
        return node.value if len(node.value) <= MAX_ARGUMENT else None
    if type(node.value) is int and node.value.bit_length() > 1024:
        return None
    return sign * node.value


def folded_conversion(node: ast.AST, names: dict[str, str]) -> float | Decimal | None:
    """The value `float(<literal>)` or `Decimal(<literal>)` folds to, or None when it does not fold.

    A signalling NaN never folds: it cannot be compared without an error.
    """
    if not names or not isinstance(node, ast.Call) or node.keywords or len(node.args) != 1:
        return None
    kind = names.get(dotted_name(node.func) or "")
    argument = _argument(node.args[0]) if kind is not None else None
    if argument is None:
        return None
    try:
        if kind == "float":
            return float(argument)
        value = Decimal(argument)
    except (ValueError, TypeError, ArithmeticError):
        return None
    return None if value.is_snan() else value


def unbound_callee(node: ast.AST, bindings: tuple[Counter, bool]) -> bool:
    """Is this a call whose callee's root is a name the module never binds?

    A builtin outside the fold set (`int`, `round`) or a name bound nowhere
    (226.Q1). A star import may bind any name, so nothing is unbound beside
    one; a callee rooted in anything but a name is not asked about.
    """
    if not isinstance(node, ast.Call):
        return False
    root = node.func
    while isinstance(root, ast.Attribute):
        root = root.value
    bound, star = bindings
    return isinstance(root, ast.Name) and not star and not bound[root.id]

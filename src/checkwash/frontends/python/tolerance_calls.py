"""Python tolerance calls, read as the approximate comparisons they are (#222).

`assert math.isclose(total(), 78.75, abs_tol=1e-9)` was a truthy assertion
with no tolerance, so widening `abs_tol` to `1e3` passed with zero findings
while the same widening in `pytest.approx` blocked; numpy's and torch's
assertion calls were no assertions at all. One table maps each call to the
approximate form, its tolerances and their defaults, and the expected value
it compares against, as `pytest.approx` records them.

Each call keeps its own semantics:
- `math.isclose(a, b, *, rel_tol=1e-09, abs_tol=0.0)`;
- numpy's `isclose` and `allclose` (`rtol=1e-05, atol=1e-08`) and
  `testing.assert_allclose` (`rtol=1e-07, atol=0`), the tolerances also
  positional after the two values;
- numpy's `testing.assert_array_almost_equal` (`decimal=6`) and
  `testing.assert_almost_equal` (`decimal=7`), which pass while
  |desired - actual| < 1.5 * 10**-decimal: a kind of its own, not unittest's
  places;
- `torch.testing.assert_close(actual, expected, *, rtol=None, atol=None)`:
  both tolerances or neither, and when neither the pair depends on the
  tensors' dtype, so it is unknown (222.Q3).
A default is recorded as numpy 2.3 and CPython state it, so a tolerance that
appears in the head is compared against the one the call had.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass


@dataclass(frozen=True)
class ToleranceCall:
    # True for an assertion call written as a statement (numpy.testing,
    # torch.testing); False for a predicate an `assert` or `assertTrue` tests.
    statement: bool
    # (keyword, recorded key, positional index or None, default or None)
    tolerances: tuple[tuple[str, str, int | None, str | None], ...]
    # The keyword names of the compared values, after their positions.
    values: tuple[tuple[str, ...], tuple[str, ...]]


_NUMPY_CLOSE = (("atol", "abs", 3, "1e-08"), ("rtol", "rel", 2, "1e-05"))

TOLERANCE_CALLS: dict[str, ToleranceCall] = {
    "math.isclose": ToleranceCall(
        False, (("abs_tol", "abs", None, "0.0"), ("rel_tol", "rel", None, "1e-09")), ((), ())),
    "numpy.isclose": ToleranceCall(False, _NUMPY_CLOSE, (("a",), ("b",))),
    "numpy.allclose": ToleranceCall(False, _NUMPY_CLOSE, (("a",), ("b",))),
    "numpy.testing.assert_allclose": ToleranceCall(
        True, (("atol", "abs", 3, "0"), ("rtol", "rel", 2, "1e-07")), (("actual",), ("desired",))),
    "numpy.testing.assert_array_almost_equal": ToleranceCall(
        True, (("decimal", "decimal", 2, "6"),), (("actual", "x"), ("desired", "y"))),
    "numpy.testing.assert_almost_equal": ToleranceCall(
        True, (("decimal", "decimal", 2, "7"),), (("actual",), ("desired",))),
    "torch.testing.assert_close": ToleranceCall(
        True, (("atol", "abs", None, None), ("rtol", "rel", None, None)), (("actual",), ("expected",))),
}

# Roots that name their module when nothing in the file binds them.
_NATIVE_ROOTS = frozenset({"math", "numpy", "torch"})
_MODULES = ("math", "numpy", "torch")


def _native(target: str) -> bool:
    return target.split(".")[0] in _MODULES


# The last name of each entry: a call that resolves to one names it, as its
# own attribute or in the import that binds the name it calls.
_LAST_NAMES = tuple(sorted({name.rsplit(".", 1)[1] for name in TOLERANCE_CALLS}))


def may_resolve(source: str) -> bool:
    """Can a call in this module resolve to a table entry? False only when none can.

    An entry is reached through its last name, which an ASCII source writes
    out where the call names it or where an import binds it; only
    `importorskip` binds a module through a string, which escapes or
    concatenation can spell in pieces. A non-ASCII source may write an
    identifier in another normal form, so it always may. A module for which
    this is False needs no walk for its imports: no call in it resolves,
    whatever it binds.
    """
    return not source.isascii() or "importorskip" in source or any(name in source for name in _LAST_NAMES)


def import_names(tree: ast.AST | None) -> dict[str, str | None]:
    """Each name the file binds to math, numpy or torch, or to one of their members.

    Every import in the file counts, at any depth, and so does
    `np = pytest.importorskip("numpy")`, annotated or as `:=`. A name bound
    to two different targets, or bound by anything else as well, resolves
    to nothing.
    """
    found: dict[str, set] = {}
    if tree is None:
        return {}

    def bind(name: str, target: str | None) -> None:
        found.setdefault(name, set()).add(target)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    bind(alias.asname, alias.name if _native(alias.name) else None)
                else:
                    root = alias.name.split(".")[0]
                    bind(root, root if _native(root) else None)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*":
                    continue
                target = f"{node.module}.{alias.name}" if node.module and not node.level else None
                bind(alias.asname or alias.name, target if target and _native(target) else None)
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.NamedExpr)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = getattr(node, "value", None)
            module = _importorskip(value)
            for target in targets:
                if isinstance(target, ast.Name):
                    bind(target.id, None if isinstance(node, ast.AugAssign) else module)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bind(node.name, None)
    names: dict[str, str | None] = {}
    for name, targets in found.items():
        names[name] = next(iter(targets)) if len(targets) == 1 else None
    return names


def _importorskip(value: ast.AST | None) -> str | None:
    """`pytest.importorskip("numpy")` returns the module it imports."""
    if (isinstance(value, ast.Call) and _dotted(value.func) in ("pytest.importorskip", "importorskip")
            and value.args and isinstance(value.args[0], ast.Constant)
            and isinstance(value.args[0].value, str) and _native(value.args[0].value)):
        return value.args[0].value
    return None


def _dotted(node: ast.AST) -> str | None:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    return ".".join(reversed(parts))


def callee(call: ast.Call, names: dict[str, str | None]) -> str | None:
    """The table entry a call names, read through the file's imports, or None."""
    dotted = _dotted(call.func)
    if dotted is None:
        return None
    root, _, rest = dotted.partition(".")
    if root in names:
        target = names[root]
        if target is None:
            return None
        resolved = f"{target}.{rest}" if rest else target
    elif root in _NATIVE_ROOTS:
        resolved = dotted
    else:
        return None
    return resolved if resolved in TOLERANCE_CALLS else None


def find_predicate(node: ast.AST, names: dict[str, str | None]) -> tuple[ast.Call, str] | None:
    """The predicate tolerance call an expression tests, through any call around it.

    `math.isclose(...)`, `numpy.isclose(...).all()`, `numpy.all(numpy.isclose(...))`
    and `all(math.isclose(x, y) for ...)` all test the call inside. The caller
    hands over the expression after `not` was read, so polarity stays its own.
    """
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            name = callee(sub, names)
            if name is not None and not TOLERANCE_CALLS[name].statement:
                return sub, name
    return None


def statement_call(call: ast.Call, names: dict[str, str | None]) -> str | None:
    """The table entry of an assertion call (numpy.testing, torch.testing), or None."""
    name = callee(call, names)
    return name if name is not None and TOLERANCE_CALLS[name].statement else None


def values(call: ast.Call, name: str) -> tuple[ast.AST | None, ast.AST | None]:
    """The two compared values, positional or by keyword."""
    entry = TOLERANCE_CALLS[name]
    out: list[ast.AST | None] = []
    for index, keywords in enumerate(entry.values):
        if index < len(call.args) and not any(isinstance(a, ast.Starred) for a in call.args[:index + 1]):
            out.append(call.args[index])
            continue
        out.append(next((kw.value for kw in call.keywords if kw.arg in keywords), None))
    return out[0], out[1]


def tolerance(call: ast.Call, name: str, seg) -> tuple[str | None, str | None]:
    """(epsilon, kind) as recorded: `abs=1e-9|rel=1e-09`, `decimal=6`; (None, None) when unknown.

    A tolerance passed through `*args` or `**kwargs` cannot be read, and
    neither can torch's omitted pair; a written one is recorded as written,
    so a name or an expression stays unjudged as an approx tolerance does.
    """
    entry = TOLERANCE_CALLS[name]
    if any(kw.arg is None for kw in call.keywords):
        return None, None
    starred = next((i for i, a in enumerate(call.args) if isinstance(a, ast.Starred)), None)
    parts: list[tuple[str, str]] = []
    for keyword, key, position, default in entry.tolerances:
        node = next((kw.value for kw in call.keywords if kw.arg == keyword), None)
        if node is None and position is not None:
            if starred is not None and starred <= position:
                return None, None
            if position < len(call.args):
                node = call.args[position]
        text = seg(node) if node is not None else default
        if not text:
            # torch's omitted tolerance, or one whose source cannot be read.
            return None, None
        parts.append((key, text))
    parts.sort()
    return "|".join(f"{k}={v}" for k, v in parts), parts[0][0] if len(parts) == 1 else "multi"

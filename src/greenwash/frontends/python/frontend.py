"""Python frontend: stdlib-ast parsing of one file side into semantic units.

See DECISIONS.md D-001 for why this is `ast` and not tree-sitter in v0.1.
A file that fails to parse is reported with parse_ok=False and surfaces in
`skipped_files` — visible degradation, never silent (SPEC §8).
"""

from __future__ import annotations

import ast
import bisect
import hashlib
import operator
import re
from dataclasses import dataclass, field

from greenwash.ir import strength as S
from greenwash.ir.model import Assertion, Handler, Marker, UnitSide

_SUPPRESSION_RE = re.compile(r"#\s*(noqa|type:\s*ignore)", re.IGNORECASE)

# unittest assertion method -> (form, strength). Unknown methods are left
# unclassified on purpose (fail-safe: no guess, no noise).
_UNITTEST_MAP: dict[str, tuple[str, int | None]] = {
    # The whole *Equal family sits at EXACT_VALUE; the container-LITERAL
    # upgrade to EXACT_STRUCT is applied uniformly afterwards. unittest's
    # assertEqual type-dispatches to assertListEqual at runtime, so rating
    # them differently turned a style cleanup into a blocking "weakening"
    # (confirmed red-team false positive).
    "assertEqual": ("compare_eq", S.EXACT_VALUE),
    "assertNotEqual": ("compare_eq", S.EXACT_VALUE),
    "assertListEqual": ("compare_eq", S.EXACT_VALUE),
    "assertDictEqual": ("compare_eq", S.EXACT_VALUE),
    "assertSetEqual": ("compare_eq", S.EXACT_VALUE),
    "assertTupleEqual": ("compare_eq", S.EXACT_VALUE),
    "assertSequenceEqual": ("compare_eq", S.EXACT_VALUE),
    "assertMultiLineEqual": ("compare_eq", S.EXACT_VALUE),
    "assertAlmostEqual": ("approx", S.APPROX),
    "assertNotAlmostEqual": ("approx", S.APPROX),
    "assertTrue": ("truthy", S.TRUTHY),
    "assertFalse": ("truthy", S.TRUTHY),
    "assertIsNone": ("non_null", S.NON_NULL),
    "assertIsNotNone": ("non_null", S.NON_NULL),
    # THREATMODEL row 33 claimed `is`/`is not` polarity flips were closed, but
    # the unittest spelling was never in this map at all, so assertIs ->
    # assertIsNot produced no classification and no finding (reader audit
    # 2026-08-02).
    "assertIs": ("compare_eq", S.EXACT_VALUE),
    "assertIsNot": ("compare_eq", S.EXACT_VALUE),
    "assertCountEqual": ("compare_eq", S.EXACT_VALUE),
    "assertGreater": ("compare_ord", S.BOUND),
    "assertGreaterEqual": ("compare_ord", S.BOUND),
    "assertLess": ("compare_ord", S.BOUND),
    "assertLessEqual": ("compare_ord", S.BOUND),
    "assertIn": ("membership", S.PATTERN),
    "assertNotIn": ("membership", S.PATTERN),
    "assertRegex": ("pattern", S.PATTERN),
    "assertNotRegex": ("pattern", S.PATTERN),
    "assertIsInstance": ("type_shape", S.TYPE_SHAPE),
    "assertNotIsInstance": ("type_shape", S.TYPE_SHAPE),
    "assertRaises": ("raises", None),
    "assertRaisesRegex": ("raises", None),
    "assertWarns": ("raises", None),
    "assertWarnsRegex": ("raises", None),
}

_SKIP_DECORATORS = {
    "pytest.mark.skip",
    "pytest.mark.skipif",
    "pytest.mark.xfail",
    "unittest.skip",
    "unittest.skipIf",
    "unittest.skipUnless",
    "unittest.expectedFailure",
    "skip",
    "skipIf",
    "skipUnless",
    "expectedFailure",
}

_SKIP_CALLS = {"pytest.skip", "pytest.xfail", "pytest.importorskip", "self.skipTest"}

# AssertionError belongs here: catching it is precisely how you swallow an
# oracle, and it is the obvious variant of the broad-except cheat.
_BROAD_EXCEPTIONS = {"Exception", "BaseException", "AssertionError"}

# conftest.py is where pytest lets you disable collection for a whole tree.
# These are the curated suite-level controls TEST_DISABLED watches for.
_CONFTEST_HOOKS = {"pytest_ignore_collect", "pytest_collection_modifyitems"}
_CONFTEST_NAMES = {"collect_ignore", "collect_ignore_glob"}


@dataclass
class ParsedUnit:
    qualname: str
    span: tuple[int, int]
    side: UnitSide
    shingles: frozenset[tuple[str, ...]] = frozenset()


@dataclass
class ParsedFile:
    parse_ok: bool
    units: list[ParsedUnit] = field(default_factory=list)
    symbols: dict[str, str] = field(default_factory=dict)  # qualname -> behaviour fingerprint
    symbol_calls: dict[str, tuple[str, ...]] = field(default_factory=dict)  # qualname -> callees
    imports: list[str] = field(default_factory=list)
    suppressions: list[str] = field(default_factory=list)
    literals: frozenset[str] = frozenset()
    broad_handlers: tuple[str, ...] = ()  # normalized texts of broad except handlers, module-wide
    # Subset of the above that actually hides a failure: the guarded block
    # holds an oracle and the handler neither re-raises nor asserts. Test
    # files are judged on this narrower list, production files on the full one
    # — swallowing an error in prod is its own cheat, but a test that provokes
    # an error on purpose and inspects it hides nothing.
    swallowing_handlers: tuple[str, ...] = ()


def normalize_source(data: bytes) -> str:
    # utf-8-sig strips a BOM if present (routine on Windows-authored files);
    # spans are offsets into this normalized text (SPEC §8).
    text = data.decode("utf-8-sig", errors="replace")
    return text.replace("\r\n", "\n").replace("\r", "\n")


class _Offsets:
    """Line-start index over the normalized source.

    `seg()` replaces ast.get_source_segment, which re-splits the whole file on
    every call — O(file) per assertion made a 3000-line diff take seconds and
    tripped the perf gate.
    """

    def __init__(self, text: str) -> None:
        starts = [0]
        for i, ch in enumerate(text):
            if ch == "\n":
                starts.append(i + 1)
        self._starts = starts
        self._len = len(text)
        self.text = text
        self._bytecols: dict[int, list[int]] = {}

    def _char_col(self, lineno: int, col: int) -> int:
        """Translate CPython's UTF-8 *byte* column into a character column.

        `ast` documents col_offset as a byte offset. Adding it straight to a
        character-indexed line start shifted every span on any line holding
        non-ASCII text, so `seg()` returned garbled source — which silently
        reopened the self-comparison bypass (#10), because the tautology check
        compares extracted source strings and they no longer matched. One CJK
        character in a test literal was enough (reader audit 2026-08-02).
        """
        idx = lineno - 1
        if col <= 0 or idx < 0 or idx >= len(self._starts):
            return col
        start = self._starts[idx]
        end = self._starts[idx + 1] if idx + 1 < len(self._starts) else self._len
        line = self.text[start:end]
        if line.isascii():  # the overwhelmingly common case: bytes == chars
            return col
        table = self._bytecols.get(idx)
        if table is None:
            table = []
            byte = 0
            for ch in line:
                table.append(byte)
                byte += len(ch.encode("utf-8"))
            table.append(byte)
            self._bytecols[idx] = table
        pos = bisect.bisect_left(table, col)
        return min(pos, len(table) - 1)

    def span(self, node: ast.AST) -> tuple[int, int]:
        lineno = getattr(node, "lineno", 1)
        col = getattr(node, "col_offset", 0)
        end_lineno = getattr(node, "end_lineno", lineno)
        end_col = getattr(node, "end_col_offset", col)
        try:
            start = self._starts[lineno - 1] + self._char_col(lineno, col)
            end = self._starts[end_lineno - 1] + self._char_col(end_lineno, end_col)
        except IndexError:  # synthesized node (e.g. inserted Pass)
            return (0, 0)
        return (min(start, self._len), min(end, self._len))

    def seg(self, node: ast.AST) -> str:
        start, end = self.span(node)
        return self.text[start:end]


def _dotted(node: ast.AST) -> str | None:
    """`a.b.c` for Name/Attribute chains, else None."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _is_container_literal(node: ast.AST) -> bool:
    return isinstance(node, (ast.List, ast.Dict, ast.Set, ast.Tuple)) and _is_literal(node)


def _norm(text: str) -> str:
    return "".join(text.split())


def _strip_identity(node: ast.AST, text) -> str:
    """Source text of `node` with outer no-op arithmetic peeled off.

    `x + 0`, `0 + x`, `x - 0`, `x * 1`, `1 * x`, `x / 1` all reduce to `x`,
    recursively. Used only to unmask `f(x) == f(x) + 0` self-comparisons.
    """
    if isinstance(node, ast.BinOp):
        left, right = node.left, node.right
        if isinstance(node.op, ast.Add):
            if _is_zero(right):
                return _strip_identity(left, text)
            if _is_zero(left):
                return _strip_identity(right, text)
        elif isinstance(node.op, ast.Sub) and _is_zero(right):
            return _strip_identity(left, text)
        elif isinstance(node.op, ast.Mult):
            if _is_one(right):
                return _strip_identity(left, text)
            if _is_one(left):
                return _strip_identity(right, text)
        elif isinstance(node.op, ast.Div) and _is_one(right):
            return _strip_identity(left, text)
    return text.seg(node) or ""


def _is_zero(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value == 0 and not isinstance(node.value, bool)


def _is_one(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value == 1 and not isinstance(node.value, bool)


def _is_literal(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        return _is_literal(node.operand)
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return all(_is_literal(e) for e in node.elts)
    if isinstance(node, ast.Dict):
        return all(k is not None and _is_literal(k) for k in node.keys) and all(
            _is_literal(v) for v in node.values
        )
    return False


def _literal_repr(node: ast.AST, text: str) -> str | None:
    if _is_literal(node):
        seg = text.seg(node)
        if seg is not None and len(seg) <= 120:
            return seg
    return None


def _find_approx_call(node: ast.AST) -> ast.Call | None:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            name = _dotted(sub.func)
            if name in ("pytest.approx", "approx"):
                return sub
    return None


def _approx_epsilon(call: ast.Call, text: str) -> tuple[str | None, str | None]:
    """All tolerances on the call, joined — not just the first.

    `approx(x, rel=1e-9, abs=1e-9)` -> `approx(x, rel=1e-9, abs=1.0)` widened
    the absolute tolerance by nine orders of magnitude and was invisible,
    because only the first keyword found was recorded (confirmed bypass).
    Each kind is compared independently by the detector.
    """
    parts: list[tuple[str, str]] = []
    for kw in call.keywords:
        if kw.arg in ("rel", "abs"):
            seg = text.seg(kw.value)
            if seg:
                parts.append((kw.arg, seg))
    # pytest.approx(expected, rel) — a positional tolerance was invisible, so
    # widening one by a million produced no finding at all.
    if not parts and len(call.args) > 1:
        seg = text.seg(call.args[1])
        if seg:
            parts.append(("rel", seg))
    if not parts:
        # `approx(42)` with no tolerance at all still has an implicit default;
        # record it so approx(42) -> approx(7) is a value change, not silence.
        return None, None
    parts.sort()
    return "|".join(f"{k}={v}" for k, v in parts), "multi" if len(parts) > 1 else parts[0][0]


def _canonical_repr(value: object) -> str:
    """repr() with set iteration order removed.

    `repr({"a", "b"})` depends on hash randomisation, so a set literal in an
    expectation produced a different string on every run — leaking into
    finding messages and the IR, and breaking the byte-identical guarantee
    (SPEC §8). Sets are emitted in sorted-by-canonical-repr order instead;
    containers are rebuilt recursively so nested sets are covered too.
    """
    if isinstance(value, (set, frozenset)):
        inner = sorted(_canonical_repr(v) for v in value)
        prefix = "frozenset(" if isinstance(value, frozenset) else ""
        if not inner:
            return "frozenset()" if prefix else "set()"
        body = "{" + ", ".join(inner) + "}"
        return f"frozenset({body})" if prefix else body
    if isinstance(value, tuple):
        if len(value) == 1:
            return f"({_canonical_repr(value[0])},)"
        return "(" + ", ".join(_canonical_repr(v) for v in value) + ")"
    if isinstance(value, list):
        return "[" + ", ".join(_canonical_repr(v) for v in value) + "]"
    if isinstance(value, dict):
        # dicts preserve insertion order in the source, which is stable.
        return "{" + ", ".join(
            f"{_canonical_repr(k)}: {_canonical_repr(v)}" for k, v in value.items()
        ) + "}"
    return repr(value)


def _literal_value(node: ast.AST) -> str | None:
    """Canonical repr of a literal's VALUE (quote-style independent), else None."""
    try:
        return _canonical_repr(ast.literal_eval(node))
    except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
        return None


@dataclass
class _Classified:
    form: str
    strength: int | None
    left: str | None = None
    right_literal: str | None = None
    right_value: str | None = None
    epsilon: str | None = None
    epsilon_kind: str | None = None
    positive: bool = True


_NEGATED_UNITTEST = frozenset(
    {
        "assertNotEqual", "assertFalse", "assertIsNone", "assertNotIn",
        "assertNotRegex", "assertNotIsInstance", "assertNotAlmostEqual",
        "assertIsNot",
    }
)

_BUILTIN_CALLS = frozenset(
    {
        "str", "int", "float", "bool", "len", "repr", "sorted", "list", "dict",
        "set", "tuple", "abs", "round", "min", "max", "sum", "any", "all",
        "reversed", "type", "format",
    }
)


def _is_trivial_subject(node: ast.AST | None) -> bool:
    """Does this expression depend on nothing but literals and builtin calls?

    `assert str(1) == "1"` sits at EXACT_VALUE(90) and can never fail, so it
    was usable as padding to fake compensation for a deleted oracle.

    A **bare** name is state, not a builtin, even when it is spelled like one:
    `sum == 42` (a local named `sum`) is a real, fallible assertion. Only a
    builtin used as a call — `sum(xs) == 42` — is trivial (confirmed
    red-team false positive). Recursion, not ast.walk, so a call's function
    Name is judged in call context, not as a bare reference.
    """
    if node is None:
        return True
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return all(_is_trivial_subject(e) for e in node.elts)
    if isinstance(node, ast.Dict):
        return all(k is not None and _is_trivial_subject(k) for k in node.keys) and all(
            _is_trivial_subject(v) for v in node.values
        )
    if isinstance(node, ast.BinOp):
        return _is_trivial_subject(node.left) and _is_trivial_subject(node.right)
    if isinstance(node, ast.UnaryOp):
        return _is_trivial_subject(node.operand)
    if isinstance(node, ast.BoolOp):
        return all(_is_trivial_subject(v) for v in node.values)
    if isinstance(node, ast.Compare):
        return _is_trivial_subject(node.left) and all(
            _is_trivial_subject(c) for c in node.comparators
        )
    if isinstance(node, ast.Call):
        name = _dotted(node.func)
        if name is None or name.rsplit(".", 1)[-1] not in _BUILTIN_CALLS:
            return False  # a non-builtin call can fail
        return all(_is_trivial_subject(a) for a in node.args) and all(
            _is_trivial_subject(k.value) for k in node.keywords
        )
    # Bare Name, Attribute, Subscript, comprehension, … = depends on state.
    return False


def _classify_assert(node: ast.Assert, text: str) -> _Classified:
    return _classify_assert_expr(node.test, text)


def _is_unfalsifiable(test: ast.AST, text) -> bool:
    """Assertions that are structurally incapable of failing.

    `_is_trivial_subject` asks "does this depend on anything but literals?",
    which `assert "" in str(x)` passes — it mentions `x` — while still being
    true for every possible `x`. That made it valid compensation, and eight
    deleted exact assertions could be laundered through D5 with one line of
    padding (reader audit 2026-08-02). These are the shapes seen in the wild;
    the list is a floor, not a claim of completeness.
    """
    if not isinstance(test, ast.Compare) or len(test.ops) != 1:
        return False
    op = test.ops[0]
    left, right = test.left, test.comparators[0]
    # `"" in <str>` / `b"" in <bytes>` / `() in ...` — the empty needle is in
    # every haystack of the same kind.
    if isinstance(op, ast.In) and isinstance(left, ast.Constant) and left.value in ("", b""):
        return True
    # `len(x) >= 0`, `len(x) > -1`: a length is never negative. The bound is
    # literal-evaluated, not isinstance-checked — `-1` is a UnaryOp, not a
    # Constant, and matching only Constant missed exactly that spelling.
    if isinstance(left, ast.Call) and _dotted(left.func) == "len" and _is_literal(right):
        try:
            bound = ast.literal_eval(right)
        except (ValueError, SyntaxError, TypeError):
            bound = None
        if isinstance(bound, int) and not isinstance(bound, bool):
            if isinstance(op, ast.GtE) and bound <= 0:
                return True
            if isinstance(op, ast.Gt) and bound < 0:
                return True
    # `x in x`, `x <= x`, `x >= x` — same expression both sides.
    if isinstance(op, (ast.In, ast.LtE, ast.GtE)):
        if _norm(_strip_identity(left, text)) == _norm(_strip_identity(right, text)):
            return True
    return False


def _classify_assert_expr(test: ast.AST, text) -> _Classified:
    # `assert (cond, "message")` asserts a non-empty tuple display, which is
    # always truthy — CPython itself warns about it. It was rated TRUTHY(20),
    # so neutering a real truthy assertion this way produced no finding at all
    # (reader audit 2026-08-02).
    if isinstance(test, ast.Tuple) and test.elts:
        return _Classified("tautology", S.TAUTOLOGY)
    if _is_unfalsifiable(test, text):
        return _Classified("tautology", S.TAUTOLOGY)
    approx = _find_approx_call(test)
    if approx is not None:
        eps, kind = _approx_epsilon(approx, text)
        return _Classified("approx", S.APPROX, epsilon=eps, epsilon_kind=kind)
    if isinstance(test, ast.Compare) and test.ops:
        left = test.left
        comparators = test.comparators
        all_literal = _is_literal(left) and all(_is_literal(c) for c in comparators)
        if all_literal:
            return _Classified("tautology", S.TAUTOLOGY)
        op = test.ops[0]
        # Chained comparisons (`0 < x < 10`): the last comparator carries the
        # upper expectation, so consider every comparator, not just the first.
        expect_node = comparators[-1] if comparators else None
        # `assert 3 == calc()` puts the expectation on the LEFT. Taking the
        # right side unconditionally made changing it invisible (confirmed
        # bypass); prefer whichever side is the literal.
        subject_node = left
        if comparators and _is_literal(left) and not _is_literal(comparators[-1]):
            expect_node, subject_node = left, comparators[-1]
        left_text = text.seg(subject_node)
        right_lit = _literal_repr(expect_node, text) if expect_node is not None else None
        right_val = _literal_value(expect_node) if expect_node is not None else None
        pos = not isinstance(op, (ast.NotEq, ast.IsNot, ast.NotIn))
        if isinstance(op, (ast.Eq, ast.NotEq)):
            # Self-comparison (`assert f(x) == f(x)`) can never fail: the
            # oracle is gone even though the form still looks exact. Strip
            # identity ops (+0, -0, *1, /1) from both sides first, so
            # `f(x) == f(x) + 0` is caught too (confirmed red-team finding).
            if comparators and _norm(_strip_identity(left, text)) == _norm(
                _strip_identity(comparators[0], text)
            ):
                return _Classified("tautology", S.TAUTOLOGY, left_text, right_lit, right_val)
            if isinstance(left, ast.Call) and _dotted(left.func) == "len":
                return _Classified("type_shape", S.TYPE_SHAPE, left_text, right_lit, right_val)
            if _is_container_literal(left) or any(_is_container_literal(c) for c in comparators):
                return _Classified("compare_eq", S.EXACT_STRUCT, left_text, right_lit, right_val, positive=pos)
            return _Classified("compare_eq", S.EXACT_VALUE, left_text, right_lit, right_val, positive=pos)
        if isinstance(op, (ast.Gt, ast.GtE, ast.Lt, ast.LtE)):
            return _Classified("compare_ord", S.BOUND, left_text, right_lit, right_val, positive=pos)
        if isinstance(op, (ast.In, ast.NotIn)):
            return _Classified("membership", S.PATTERN, left_text, right_lit, right_val, positive=pos)
        if isinstance(op, (ast.Is, ast.IsNot)):
            comp = comparators[0]
            if isinstance(comp, ast.Constant) and comp.value is None:
                return _Classified("non_null", S.NON_NULL, left_text, positive=pos)
            return _Classified("compare_eq", S.EXACT_VALUE, left_text, right_lit, right_val, positive=pos)
        return _Classified("unknown", None, left_text)
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        # `assert not x` is the negated form of `assert x`.
        inner = _classify_assert_expr(test.operand, text)
        return _Classified(
            inner.form, inner.strength, inner.left, inner.right_literal,
            inner.right_value, inner.epsilon, inner.epsilon_kind, not inner.positive,
        )
    if isinstance(test, ast.Call):
        name = _dotted(test.func)
        if name == "isinstance":
            # `isinstance(x, object)` is true for every object.
            if len(test.args) == 2 and _dotted(test.args[1]) == "object":
                return _Classified("tautology", S.TAUTOLOGY)
            return _Classified("type_shape", S.TYPE_SHAPE)
        return _Classified("truthy", S.TRUTHY)
    if _is_literal(test):
        return _Classified("tautology", S.TAUTOLOGY)
    return _Classified("truthy", S.TRUTHY)


def _classify_unittest_call(node: ast.Call, text: str) -> _Classified | None:
    if not (isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == "self"):
        return None
    method = node.func.attr
    if method not in _UNITTEST_MAP:
        return None
    form, level = _UNITTEST_MAP[method]
    positive = method not in _NEGATED_UNITTEST
    left_text = None
    right_lit = None
    right_val = None
    epsilon = None
    epsilon_kind = None
    if node.args:
        left_text = text.seg(node.args[0])
        if len(node.args) > 1:
            right_lit = _literal_repr(node.args[1], text)
            right_val = _literal_value(node.args[1])
        if form == "compare_eq" and level == S.EXACT_VALUE and len(node.args) > 1:
            if _is_container_literal(node.args[0]) or _is_container_literal(node.args[1]):
                level = S.EXACT_STRUCT
    if form == "approx":
        for kw in node.keywords:
            if kw.arg in ("places", "delta"):
                epsilon = text.seg(kw.value)
                epsilon_kind = kw.arg
        # assertAlmostEqual(a, b, places) — positional third argument.
        if epsilon is None and len(node.args) > 2:
            seg = text.seg(node.args[2])
            if seg:
                epsilon, epsilon_kind = seg, "places"
    if form == "truthy" and node.args and _is_literal(node.args[0]):
        form, level = "tautology", S.TAUTOLOGY
    if form == "compare_eq" and len(node.args) > 1:
        right_text = text.seg(node.args[1])
        if left_text and right_text and _norm(left_text) == _norm(right_text):
            form, level = "tautology", S.TAUTOLOGY
    return _Classified(
        form, level, left_text, right_lit, right_val, epsilon, epsilon_kind, positive
    )


def _canonical_marker(name: str | None) -> str | None:
    """Resolve a decorator's dotted name to its canonical skip-marker name.

    `import pytest as p` then `@p.mark.skip` is the same marker as
    `@pytest.mark.skip`; matching the literal dotted string missed it
    (confirmed bypass). Matching is done on the trailing components, which
    are alias-independent.
    """
    if not name:
        return None
    if name in _SKIP_DECORATORS:
        return name
    parts = name.split(".")
    for width in (3, 2, 1):
        if len(parts) >= width:
            tail = ".".join(parts[-width:])
            if tail in _SKIP_DECORATORS:
                return tail
            if width >= 2 and parts[-2] == "mark" and f"pytest.mark.{parts[-1]}" in _SKIP_DECORATORS:
                return f"pytest.mark.{parts[-1]}"
    return None


def _marker_identity(canonical: str, node: ast.AST, text) -> str:
    """Marker name plus its condition, so `skipif(False)` -> `skipif(True)` is
    a change and not a no-op (confirmed bypass: only names were compared)."""
    if isinstance(node, ast.Call) and node.args:
        cond = _norm(text.seg(node.args[0]) or "")
        if cond:
            return f"{canonical}({cond})"
    return canonical


def _decorator_markers(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef, text: str, off: _Offsets
) -> list[Marker]:
    markers: list[Marker] = []
    for dec in node.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        canonical = _canonical_marker(_dotted(target))
        if canonical:
            seg = text.seg(dec) or canonical
            markers.append(
                Marker(name=_marker_identity(canonical, dec, text), text=seg, span=off.span(dec))
            )
    return markers


def _pytestmark_markers(tree: ast.Module, text: str, off: _Offsets) -> list[Marker]:
    """Module-level `pytestmark = pytest.mark.skip(...)` (single or list)."""
    markers: list[Marker] = []
    for stmt in tree.body:
        if not isinstance(stmt, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in stmt.targets):
            continue
        values = stmt.value.elts if isinstance(stmt.value, ast.List) else [stmt.value]
        for value in values:
            target = value.func if isinstance(value, ast.Call) else value
            canonical = _canonical_marker(_dotted(target))
            if canonical:
                seg = text.seg(stmt) or canonical
                markers.append(
                    Marker(
                        name=_marker_identity(canonical, value, text),
                        text=seg,
                        span=off.span(stmt),
                    )
                )
    return markers


def _test_attr_disabled(body: list[ast.stmt]) -> bool:
    """`__test__ = False` at module or class scope removes it from collection."""
    for stmt in body:
        targets: list[ast.expr] = []
        if isinstance(stmt, ast.Assign):
            targets = list(stmt.targets)
        elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
            targets = [stmt.target]
        else:
            continue
        if not any(isinstance(t, ast.Name) and t.id == "__test__" for t in targets):
            continue
        value = stmt.value
        if isinstance(value, ast.Constant) and not value.value:
            return True
    return False


def _module_skip_markers(tree: ast.Module, text, off: _Offsets) -> list[Marker]:
    """Module-level `pytest.skip(..., allow_module_level=True)` and
    `pytest.importorskip(...)` disable the whole file (confirmed bypass)."""
    markers: list[Marker] = []
    if _test_attr_disabled(tree.body):
        # pytest checks `safe_getattr(obj, "__test__", True)` before collecting
        # a module or a class. One line at module scope de-collects the whole
        # file and greenwash reported nothing at all (reader audit 2026-08-02).
        markers.append(Marker(name="module.__test__", text="__test__ = False", span=(0, 0)))
    for stmt in tree.body:
        call = None
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            call = stmt.value
        elif isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Call):
            # `pytestmark = pytest.mark.skip(...)` is _pytestmark_markers' job;
            # only the assigned-result form of importorskip belongs here.
            if any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in stmt.targets):
                continue
            call = stmt.value
        if call is None:
            continue
        name = _dotted(call.func)
        if not name:
            continue
        leaf = name.rsplit(".", 1)[-1]
        if leaf in ("skip", "xfail", "importorskip"):
            seg = (text.seg(stmt) or leaf).split("\n")[0]
            markers.append(Marker(name=f"module.{leaf}", text=seg, span=off.span(stmt)))
    return markers


def _handler_info(node: ast.ExceptHandler) -> tuple[tuple[str, ...], bool]:
    caught: tuple[str, ...]
    if node.type is None:
        caught = ()
    elif isinstance(node.type, ast.Tuple):
        caught = tuple(_dotted(e) or "?" for e in node.type.elts)
    else:
        caught = (_dotted(node.type) or "?",)
    is_broad = not caught or any(c.rsplit(".", 1)[-1] in _BROAD_EXCEPTIONS for c in caught)
    return caught, is_broad


def _is_oracle_call(node: ast.AST) -> bool:
    """A call that can fail the test: `self.assertX(...)`, `pytest.fail()`,
    `pytest.raises(...)`. Matched on the trailing component so an aliased
    import cannot dodge it."""
    if not isinstance(node, ast.Call):
        return False
    leaf = (_dotted(node.func) or "").rsplit(".", 1)[-1]
    return leaf.startswith("assert") or leaf in ("fail", "raises")


def _contains_oracle(body: list[ast.stmt]) -> bool:
    """Is there something in these statements that can fail the test?

    Nested `def`/`class`/`lambda` bodies are skipped: they are definitions,
    not statements this block executes (same reasoning as `_unreachable_ids`).
    """
    stack: list[ast.AST] = list(body)
    while stack:
        node = stack.pop()
        if isinstance(node, ast.Assert) or _is_oracle_call(node):
            return True
        for child in ast.iter_child_nodes(node):
            if isinstance(
                child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
            ):
                continue
            stack.append(child)
    return False


def _swallows(handler: ast.ExceptHandler) -> bool:
    """Does this handler make the caught failure disappear?

    A handler that re-raises, or that asserts on what it caught, still lets
    the test fail — it is inspection, not suppression.
    """
    for stmt in handler.body:
        for sub in ast.walk(stmt):
            if isinstance(sub, ast.Raise):
                return False
    return not _contains_oracle(handler.body)


def _unreachable_ids(func: ast.FunctionDef | ast.AsyncFunctionDef) -> set[int]:
    """Node ids under statements that can never execute.

    `return` (or `raise`) parked at the top of a test body leaves every
    assertion in the AST while killing the test — a one-token cheat that was
    completely silent before (confirmed red-team finding).
    """
    dead: set[int] = set()

    def kill(node: ast.AST) -> None:
        for sub in ast.walk(node):
            dead.add(id(sub))

    def scan(body: list[ast.stmt]) -> None:
        stop = False
        for stmt in body:
            if stop:
                kill(stmt)
                continue
            if isinstance(stmt, (ast.Return, ast.Raise)):
                stop = True
                continue
            # A nested def/lambda/class body does not run when the test runs;
            # moving an assertion into one keeps it in the AST while removing
            # it from execution (confirmed bypass).
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                kill(stmt)
                continue
            if isinstance(stmt, (ast.If, ast.While)):
                truth = _static_truth(stmt.test)
                if truth is False:
                    for inner in stmt.body:
                        kill(inner)
                    scan(stmt.orelse)
                    continue
                if truth is True and isinstance(stmt, ast.If):
                    scan(stmt.body)
                    for inner in stmt.orelse:
                        kill(inner)
                    continue
            # `for _ in []:` never enters its body; the else clause still runs.
            if isinstance(stmt, ast.For) and _is_literal(stmt.iter) and not _truthy_literal(stmt.iter):
                for inner in stmt.body:
                    kill(inner)
                scan(stmt.orelse)
                continue
            if isinstance(stmt, ast.Match) and _match_is_dead(stmt):
                for case in stmt.cases:
                    for inner in case.body:
                        kill(inner)
                continue
            for name in ("body", "orelse", "finalbody"):
                inner_body = getattr(stmt, name, None)
                if isinstance(inner_body, list) and inner_body and isinstance(inner_body[0], ast.stmt):
                    scan(inner_body)
            for handler in getattr(stmt, "handlers", []) or []:
                scan(handler.body)

    scan(func.body)
    # Lambdas anywhere in the body are deferred code too.
    for node in ast.walk(func):
        if isinstance(node, ast.Lambda):
            kill(node.body)
    return dead


_CMP_OPS: dict[type, object] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}
# `is` / `is not` are deliberately absent: their result on literals depends on
# interning, which differs between interpreters and would make the verdict
# version-dependent. Unknown is the safe answer — it keeps the branch live.


def _static_truth(node: ast.AST) -> bool | None:
    """Constant-fold a branch condition to True / False / None (unknown).

    `if False:` was recognised, but `if not True:`, `if 1 == 2:` and
    `if False and x:` were all treated as live code, so a one-word edit parked
    an assertion where greenwash still believed it ran — reopening bypass #29
    (reader audit 2026-08-02).
    """
    if _is_literal(node):
        return _truthy_literal(node)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        inner = _static_truth(node.operand)
        return None if inner is None else not inner
    if isinstance(node, ast.BoolOp):
        values = [_static_truth(v) for v in node.values]
        if isinstance(node.op, ast.And):
            if any(v is False for v in values):
                return False
            return True if all(v is True for v in values) else None
        if any(v is True for v in values):
            return True
        return False if all(v is False for v in values) else None
    if (
        isinstance(node, ast.Compare)
        and _is_literal(node.left)
        and all(_is_literal(c) for c in node.comparators)
    ):
        try:
            left = ast.literal_eval(node.left)
            for op, comparator in zip(node.ops, node.comparators):
                fn = _CMP_OPS.get(type(op))
                if fn is None:
                    return None
                right = ast.literal_eval(comparator)
                if not fn(left, right):  # type: ignore[operator]
                    return False
                left = right
            return True
        except (ValueError, SyntaxError, TypeError):
            return None
    return None


def _match_is_dead(stmt: ast.Match) -> bool:
    """A `match` on a literal where no case can possibly fire.

    Only the unambiguous shape is judged — literal subject, every case a
    guardless literal value, no wildcard. Anything else is left live.
    """
    if not _is_literal(stmt.subject):
        return False
    try:
        subject = ast.literal_eval(stmt.subject)
    except (ValueError, SyntaxError, TypeError):
        return False
    for case in stmt.cases:
        if case.guard is not None:
            return False
        pattern = case.pattern
        if isinstance(pattern, ast.MatchAs) and pattern.pattern is None:
            return False  # wildcard / capture: always matches
        if not isinstance(pattern, ast.MatchValue) or not _is_literal(pattern.value):
            return False
        try:
            if ast.literal_eval(pattern.value) == subject:
                return False
        except (ValueError, SyntaxError, TypeError):
            return False
    return True


def _truthy_literal(node: ast.AST) -> bool:
    try:
        return bool(ast.literal_eval(node))
    except (ValueError, SyntaxError, TypeError):
        return True


def _param_row_disabled(node: ast.AST) -> bool:
    """`pytest.param(..., marks=pytest.mark.skip)` — a row that no longer runs.

    Marker names are matched on their trailing components, so an aliased
    `import pytest as p` cannot dodge it. `xfail` counts as disabled only when
    it is strict=False (the default), because a non-strict xfail turns a
    failure into a pass.
    """
    if not isinstance(node, ast.Call) or (_dotted(node.func) or "").rsplit(".", 1)[-1] != "param":
        return False
    for kw in node.keywords:
        if kw.arg != "marks":
            continue
        marks = kw.value.elts if isinstance(kw.value, (ast.List, ast.Tuple)) else [kw.value]
        for mark in marks:
            target = mark.func if isinstance(mark, ast.Call) else mark
            name = _dotted(target) or ""
            leaf = name.rsplit(".", 1)[-1]
            if leaf == "skip":
                return True
            if leaf == "xfail" and not _xfail_is_strict(mark):
                return True
    return False


def _xfail_is_strict(mark: ast.AST) -> bool:
    if not isinstance(mark, ast.Call):
        return False
    for kw in mark.keywords:
        if kw.arg == "strict":
            return bool(isinstance(kw.value, ast.Constant) and kw.value.value)
    return False


def _param_case_count(func: ast.FunctionDef | ast.AsyncFunctionDef) -> int | None:
    """pytest test-item count contributed by @pytest.mark.parametrize rows.

    Deleting rows deletes test items; in pytest's model each row IS a test
    unit, so the count belongs in the IR (confirmed red-team finding).
    """
    total: int | None = None
    for dec in func.decorator_list:
        if not isinstance(dec, ast.Call):
            continue
        if _dotted(dec.func) not in ("pytest.mark.parametrize", "mark.parametrize", "parametrize"):
            continue
        if len(dec.args) < 2 or not isinstance(dec.args[1], (ast.List, ast.Tuple)):
            continue
        # A row is a test item only if it still runs. Counting `len(elts)`
        # meant wrapping every row in `pytest.param(..., marks=pytest.mark.skip)`
        # left the count unchanged while the whole parametrized test stopped
        # executing — deleting the same rows blocked, skipping them did not
        # (reader audit 2026-08-02).
        rows = sum(0 if _param_row_disabled(e) else 1 for e in dec.args[1].elts)
        total = rows if total is None else total * rows
    return total


def _collect_unit(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    qualname: str,
    text: str,
    off: _Offsets,
    inherited_markers: list[Marker] | None = None,
) -> ParsedUnit:
    assertions: list[Assertion] = []
    calls: set[str] = set()
    markers = _decorator_markers(func, text, off) + list(inherited_markers or [])
    handlers: list[Handler] = []
    counter = 0
    dead = _unreachable_ids(func)

    for node in ast.walk(func):
        if id(node) in dead:
            continue
        if isinstance(node, ast.Assert):
            c = _classify_assert(node, text)
            seg = text.seg(node) or ""
            assertions.append(
                Assertion(
                    id=f"a{counter}",
                    form=c.form,
                    strength=c.strength,
                    text=seg,
                    span=off.span(node),
                    left=c.left,
                    right_literal=c.right_literal,
                    right_value=c.right_value,
                    epsilon=c.epsilon,
                    epsilon_kind=c.epsilon_kind,
                    trivial=_is_trivial_subject(node.test),
                    positive=c.positive,
                )
            )
            counter += 1
        elif isinstance(node, ast.Call):
            name = _dotted(node.func)
            if name:
                calls.add(name)
                calls.add(name.rsplit(".", 1)[-1])
                if name in _SKIP_CALLS:
                    seg = text.seg(node) or name
                    markers.append(Marker(name=name, text=seg, span=off.span(node)))
                if name in ("pytest.raises", "pytest.warns", "raises"):
                    # `pytest.raises(E, match=...)` IS an oracle: triage found
                    # human commits folding an excinfo substring assert into
                    # match= and getting blocked for "removing" it.
                    match_kw = next((kw for kw in node.keywords if kw.arg == "match"), None)
                    seg = text.seg(node) or name
                    assertions.append(
                        Assertion(
                            id=f"a{counter}",
                            form="pattern" if match_kw is not None else "raises",
                            strength=S.PATTERN if match_kw is not None else None,
                            text=seg,
                            span=off.span(node),
                            right_literal=(
                                _literal_repr(match_kw.value, text) if match_kw is not None else None
                            ),
                        )
                    )
                    counter += 1
            c = _classify_unittest_call(node, text)
            if c is not None:
                seg = text.seg(node) or ""
                assertions.append(
                    Assertion(
                        id=f"a{counter}",
                        form=c.form,
                        strength=c.strength,
                        text=seg,
                        span=off.span(node),
                        left=c.left,
                        right_literal=c.right_literal,
                        right_value=c.right_value,
                        epsilon=c.epsilon,
                        epsilon_kind=c.epsilon_kind,
                        positive=c.positive,
                    )
                )
                counter += 1
        elif isinstance(node, ast.ExceptHandler):
            caught, is_broad = _handler_info(node)
            seg = text.seg(node) or ""
            handlers.append(
                Handler(caught=caught, is_broad=is_broad, text=seg.split("\n")[0], span=off.span(node))
            )

    assertions.sort(key=lambda a: a.span)
    for i, a in enumerate(assertions):
        a.id = f"a{i}"

    side = UnitSide(
        span=off.span(func),
        assertions=assertions,
        calls=tuple(sorted(calls)),
        markers=sorted(markers, key=lambda m: m.span),
        handlers=sorted(handlers, key=lambda h: h.span),
        param_cases=_param_case_count(func),
    )
    return ParsedUnit(qualname=qualname, span=side.span, side=side, shingles=_shingles(func))


def _conftest_unit(tree: ast.Module, text: str, off: _Offsets) -> ParsedUnit:
    """Suite-level collection controls in a conftest, as one synthetic unit."""
    markers: list[Marker] = _pytestmark_markers(tree, text, off)
    for node in ast.walk(tree):
        name = None
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in _CONFTEST_HOOKS:
            name = f"conftest.{node.name}"
        elif isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id in _CONFTEST_NAMES for t in node.targets
        ):
            name = "conftest.collect_ignore"
        elif isinstance(node, ast.Call) and (_dotted(node.func) or "").endswith("add_marker"):
            arg = _dotted(node.args[0].func) if node.args and isinstance(node.args[0], ast.Call) else (
                _dotted(node.args[0]) if node.args else None
            )
            if arg in _SKIP_DECORATORS:
                name = "conftest.add_marker_skip"
        if name is None:
            continue
        seg = (text.seg(node) or name).split("\n")[0]
        markers.append(Marker(name=name, text=seg, span=off.span(node)))

    seen: set[str] = set()
    unique = []
    for m in sorted(markers, key=lambda m: m.span):
        if m.name in seen:
            continue
        seen.add(m.name)
        unique.append(m)
    side = UnitSide(span=(0, len(text.text)), markers=unique)
    return ParsedUnit(qualname="<suite>", span=side.span, side=side, shingles=frozenset())


def _shingles(func: ast.AST, k: int = 5) -> frozenset[tuple[str, ...]]:
    """k-shingles over the AST node-kind token sequence (SPEC §7)."""
    tokens: list[str] = []
    for node in ast.walk(func):
        kind = type(node).__name__
        if isinstance(node, ast.Name):
            kind += ":" + node.id
        elif isinstance(node, ast.Attribute):
            kind += ":" + node.attr
        tokens.append(kind)
    if len(tokens) < k:
        return frozenset({tuple(tokens)})
    return frozenset(tuple(tokens[i : i + k]) for i in range(len(tokens) - k + 1))


def _strip_docstrings(tree: ast.AST) -> ast.AST:
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                node.body = body[1:] or [ast.Pass()]
    return tree


def _fingerprint(node: ast.AST) -> str:
    dump = ast.dump(node, include_attributes=False)
    return hashlib.sha256(dump.encode("utf-8")).hexdigest()[:16]


def _is_test_name(name: str) -> bool:
    return name.startswith("test")


def _is_test_class(name: str) -> bool:
    """pytest's default python_classes = Test*.

    Methods of a class that does not match are never collected, so renaming
    `TestBilling` to `BillingTests` silently deletes every test in it
    (confirmed red-team finding).
    """
    return name.startswith("Test")


def _callees(node: ast.AST) -> tuple[str, ...]:
    names: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            dotted = _dotted(sub.func)
            if dotted:
                names.add(dotted.rsplit(".", 1)[-1])
    return tuple(sorted(names))


def parse_python(data: bytes, collect_tests: bool, conftest: bool = False) -> ParsedFile:
    raw = normalize_source(data)
    try:
        tree = ast.parse(raw)
    except SyntaxError:
        return ParsedFile(parse_ok=False)
    except (RecursionError, ValueError, MemoryError):
        # Deeply nested expressions raise RecursionError, not SyntaxError.
        # Head-side content is attacker-controlled: degrade visibly instead
        # of crashing the process (confirmed red-team finding).
        return ParsedFile(parse_ok=False)

    # One parse, one in-place docstring strip: symbol fingerprints are dumped
    # straight from subtrees instead of re-running unparse+parse per symbol.
    _strip_docstrings(tree)
    text = off = _Offsets(raw)
    units: list[ParsedUnit] = []
    symbols: dict[str, str] = {}
    symbol_calls: dict[str, tuple[str, ...]] = {}
    literals: set[str] = set()
    imports: list[str] = []

    # Symbol fingerprints exist to answer "did prod behaviour change?"; test
    # files never need them, and computing them dominated parse time.
    want_symbols = not collect_tests
    module_markers = (
        _pytestmark_markers(tree, text, off) + _module_skip_markers(tree, text, off)
        if collect_tests
        else []
    )

    def visit(node: ast.AST, prefix: str, inherited: list[Marker], collectible: bool) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qual = f"{prefix}{child.name}"
                if want_symbols:
                    symbols[qual] = _fingerprint(child)
                    symbol_calls[qual] = _callees(child)
                if collect_tests and collectible and _is_test_name(child.name):
                    units.append(_collect_unit(child, qual, text, off, inherited))
                # Nested defs are never collected as pytest items.
                visit(child, qual + ".", inherited, False)
            elif isinstance(child, ast.ClassDef):
                qual = f"{prefix}{child.name}"
                if want_symbols:
                    symbols[qual] = _fingerprint(child)
                # Class-level skip decorators disable every test inside the
                # class — they must reach each unit (confirmed red-team FN).
                class_markers = _decorator_markers(child, text, off) if collect_tests else []
                visit(
                    child,
                    qual + ".",
                    inherited + class_markers,
                    collectible
                    and _is_test_class(child.name)
                    and not _test_attr_disabled(child.body),
                )
            elif want_symbols and isinstance(child, (ast.Assign, ast.AnnAssign)):
                # Module- and class-level constants are behaviour too. They
                # were not symbols, so changing `TIMEOUT = 30` to 60 produced
                # no repair evidence and every test updating its expectation
                # blocked at high.
                targets = child.targets if isinstance(child, ast.Assign) else [child.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        symbols[f"{prefix}{target.id}"] = _fingerprint(child)
            else:
                visit(child, prefix, inherited, collectible)

    visit(tree, "", module_markers, True)
    if conftest:
        units = [_conftest_unit(tree, text, off)]

    # Two defs sharing a name shadow each other at runtime, and name-keyed
    # alignment produced phantom findings on comment-only diffs (triage,
    # rich 6c48a5c). Disambiguate deterministically by order.
    seen_names: dict[str, int] = {}
    for unit in units:
        n = seen_names.get(unit.qualname, 0)
        seen_names[unit.qualname] = n + 1
        if n:
            unit.qualname = f"{unit.qualname}#{n + 1}"

    broad: list[str] = []
    swallowing: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            # `from .helpers import x` resolves inside the package; recording
            # it as top-level `helpers` made IMPORT_UNRESOLVED fire on it.
            if not node.level:
                imports.append(node.module)
        elif isinstance(node, ast.Constant) and not isinstance(node.value, (bool, type(None))):
            rep = repr(node.value)
            if len(rep) <= 64:
                literals.add(rep)
        elif isinstance(node, (ast.Try, ast.TryStar)):
            # In a test file the rule is "an oracle got swallowed", not "an
            # except clause exists". Judging the handler alone flagged a
            # brand-new test that provokes an error on purpose and asserts
            # *inside* the handler, and a helper whose handler re-raises —
            # neither hides anything (reader audit 2026-08-02, rich 44797c0 /
            # starlette 26d66bb). Both lists are emitted; the engine picks by
            # role.
            guards_oracle = _contains_oracle(node.body)
            for handler in node.handlers:
                _caught, is_broad = _handler_info(handler)
                if not is_broad:
                    continue
                seg = _norm((text.seg(handler) or "except:").split("\n")[0])
                broad.append(seg)
                if guards_oracle and _swallows(handler):
                    swallowing.append(seg)
    broad.sort()
    swallowing.sort()

    suppressions = [
        f"{i + 1}:{line.strip()}"
        for i, line in enumerate(raw.split("\n"))
        if _SUPPRESSION_RE.search(line)
    ]

    units.sort(key=lambda u: u.span)
    return ParsedFile(
        parse_ok=True,
        units=units,
        symbols=symbols,
        symbol_calls=symbol_calls,
        imports=sorted(set(imports)),
        suppressions=suppressions,
        literals=frozenset(literals),
        broad_handlers=tuple(broad),
        swallowing_handlers=tuple(swallowing),
    )

"""Python frontend: stdlib-ast parsing of one file side into semantic units.

See DECISIONS.md D-001 for why this is `ast` and not tree-sitter in v0.1.
A file that fails to parse is reported with parse_ok=False and surfaces in
`skipped_files` — visible degradation, never silent (SPEC §8).
"""

from __future__ import annotations

import ast
import bisect
import copy
import hashlib
import keyword
import operator
import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field

from checkwash.ir import strength as S
from checkwash.ir.astutil import dotted_name as _dotted
from checkwash.ir.model import Assertion, Handler, Marker, UnitSide, normalize_text
from checkwash.standins import (
    StandinInstall,
    install_applies,
    install_reaches_expressions,
)

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
    # Top-level `NAME = <expr>` bindings, name -> expression source (last
    # binding wins, matching module semantics). Conditional definitions
    # (inside if/try) are deliberately absent: a name checkwash cannot pin
    # to one expression stays unevaluable.
    constants: dict[str, str] = field(default_factory=dict)
    # Module-level oracle carriers, for the engine's cross-file merge (A5-x).
    # `helper_asserts`: non-fixture, non-test top-level def -> its own direct
    # asserts (classified, `inherited=True`, ids assigned at merge time).
    # `fixture_asserts`: @pytest.fixture def -> every assert lexically inside
    # it, nested defs included — the returned closure is what a unit calls,
    # and the post-`yield` teardown runs unconditionally.
    helper_asserts: dict[str, tuple] = field(default_factory=dict)
    # Non-test, non-fixture top-level defs -> callee leaves. Repair evidence
    # follows one hop through a helper the unit actually invokes (T1.9).
    helper_calls: dict[str, tuple[str, ...]] = field(default_factory=dict)
    fixture_asserts: dict[str, tuple] = field(default_factory=dict)
    autouse_fixtures: tuple[str, ...] = ()
    # Top-level fixture -> fixtures it requests by parameter name.
    fixture_dependencies: dict[str, tuple[str, ...]] = field(default_factory=dict)
    # Same-file `@pytest.fixture` name -> canonical text of what it produces.
    fixture_defs: dict[str, str] = field(default_factory=dict)
    # Top-level absolute `from M import a as b` bindings, local -> (module,
    # original). Relative and star imports are not recorded.
    from_imports: dict[str, tuple[str, str]] = field(default_factory=dict)
    # Canonical local import binding -> target path, used to tie a stand-in to
    # the exact module reached by an oracle (not merely an attr label another
    # module might share). Ownership is judged later with diff context.
    import_bindings: dict[str, str] = field(default_factory=dict)
    # Module/fixture/hook installations. Test-body installations live on the
    # affected UnitSide directly; these scopes must first be mapped to units.
    standin_installs: tuple[StandinInstall, ...] = ()
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
        # `approx(42)` still carries pytest's implicit default (rel=1e-06,
        # abs=1e-12). Recording it makes a tolerance that APPEARS in the head
        # a widening of that default instead of silence — the comment here
        # claimed as much for two releases while the code returned None
        # (audit 2026-08-19). One default kind suffices: it turns every
        # one-sided tolerance event two-sided, and tightening to the default
        # reads equal and stays quiet. Keyed form, like every other single
        # tolerance, so the detector's per-kind parse sees the same key.
        return "rel=1e-06", "rel"
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
    # Raw name references on each side, before local bindings are followed.
    # _collect_unit resolves right_names into Assertion.right_depends_on.
    left_names: tuple[str, ...] = ()
    right_names: tuple[str, ...] = ()
    # Whether the classified assertion depends on nothing but literals and
    # builtin calls — the vacuousness test that keeps padding out of D4/D5
    # compensation. Computed here so every construction site can pass it
    # through without re-deriving nodes it no longer holds.
    trivial: bool = False


class _CanonicalImportNames(ast.NodeTransformer):
    def __init__(self, imports: Mapping[str, str]):
        self.imports = imports

    def visit_Attribute(self, node: ast.Attribute) -> ast.AST:
        dotted = _dotted(node)
        if dotted is None:
            return self.generic_visit(node)
        root, dot, suffix = dotted.partition(".")
        source = self.imports.get(root)
        if source is None:
            return self.generic_visit(node)
        target = source + (dot + suffix if dot else "")
        try:
            replacement = ast.parse(target, mode="eval").body
        except (SyntaxError, ValueError, MemoryError):
            return self.generic_visit(node)
        return ast.copy_location(replacement, node)


def _canonical_ast(
    node: ast.AST | None,
    imports: Mapping[str, str] | None = None,
) -> str:
    """Cross-version-stable code form for internal semantic identities."""
    if node is None:
        return ""
    rendered = node
    if imports:
        rendered = _CanonicalImportNames(imports).visit(copy.deepcopy(node))
    try:
        return ast.unparse(rendered)
    except (AttributeError, ValueError):  # pragma: no cover - defensive
        return ""


_UNITTEST_UNARY_ORACLES = frozenset(
    {"assertTrue", "assertFalse", "assertIsNone", "assertIsNotNone"}
)


def _standin_oracle_key(
    node: ast.AST,
    classified: _Classified,
    imports: Mapping[str, str] | None = None,
) -> str:
    """Canonical full oracle syntax used only for stand-in effect pairing."""
    if isinstance(node, ast.Assert):
        semantic = _canonical_ast(node.test, imports)
    elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        method = node.func.attr
        if method in _UNITTEST_UNARY_ORACLES:
            args = node.args[:1]
        elif method in ("assertAlmostEqual", "assertNotAlmostEqual"):
            # Third positional arg is ``places``; the fourth is only ``msg``.
            args = node.args[:3]
        else:
            # Every other reached unittest oracle in the curated dialect is
            # unary or binary. Extra positional arguments are assertion text
            # or callable arguments on raises-style forms, neither of which
            # changes the subject/expectation identity used here.
            args = node.args[:2]
        keywords = sorted(
            (
                keyword.arg or "**",
                _canonical_ast(keyword.value, imports),
            )
            for keyword in node.keywords
            if keyword.arg != "msg"
        )
        semantic = "\x1e".join(
            (
                method,
                *(_canonical_ast(arg, imports) for arg in args),
                *(f"{name}={value}" for name, value in keywords),
            )
        )
    else:
        semantic = _canonical_ast(node, imports)
    return "\x1d".join(
        (
            classified.form,
            "1" if classified.positive else "0",
            semantic,
        )
    )


# The polarity of the None family follows the bare lattice: `is None` is the
# positive form there (op `Is` → positive), so assertIsNone must be too.
# assertIsNone used to sit in this set while bare `is None` was positive, so a
# spelling conversion between the two dialects read as a polarity inversion
# ("the test now proves the opposite") and a genuine cross-dialect inversion
# did not fire at all (audit 2026-08-19).
_NEGATED_UNITTEST = frozenset(
    {
        "assertNotEqual", "assertFalse", "assertIsNotNone", "assertNotIn",
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
        # The argument of the approx call is the expected value; recording it
        # puts `approx(105.0)` -> `approx(100.0)` in front of
        # EXPECTED_VALUE_CHANGED. Strength is APPROX on both sides, so the
        # rewrite was completely invisible before (audit 2026-08-19).
        expected = approx.args[0] if approx.args else None
        subject: ast.AST | None = None
        positive = True
        if (
            isinstance(test, ast.Compare)
            and len(test.ops) == 1
            and len(test.comparators) == 1
        ):
            if test.left is approx:
                subject = test.comparators[0]
            elif test.comparators[0] is approx:
                subject = test.left
            positive = not isinstance(
                test.ops[0], (ast.NotEq, ast.IsNot, ast.NotIn)
            )
        return _Classified(
            "approx",
            S.APPROX,
            left=text.seg(subject) if subject is not None else None,
            right_literal=_literal_repr(expected, text) if expected is not None else None,
            right_value=_literal_value(expected) if expected is not None else None,
            epsilon=eps,
            epsilon_kind=kind,
            positive=positive,
            left_names=_referenced_names(subject),
            right_names=_referenced_names(expected),
        )
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
        # A chained comparison is a range oracle: the non-literal operand is
        # the subject (usually the middle term) and every literal bound is
        # part of the expectation. The middle term used to be recorded
        # nowhere — subject_node stayed the LEFT bound, so rewriting that
        # bound (`0` -> `-1000000`) moved only the subject text and no rule
        # saw the oracle move (audit 2026-08-19).
        bounds: list[ast.AST] | None = None
        if len(test.ops) > 1:
            operands = [left, *comparators]
            non_literals = [n for n in operands if not _is_literal(n)]
            if len(non_literals) == 1:
                subject_node = non_literals[0]
                bounds = [n for n in operands if _is_literal(n)]
                expect_node = bounds[-1] if bounds else None
        left_text = text.seg(subject_node)
        right_lit = _literal_repr(expect_node, text) if expect_node is not None else None
        right_val = _literal_value(expect_node) if expect_node is not None else None
        if bounds is not None and len(bounds) > 1:
            # The whole bound tuple is the expectation, so moving any single
            # bound is an expectation rewrite.
            right_lit = ", ".join(filter(None, (text.seg(b) for b in bounds)))
            try:
                right_val = _canonical_repr(tuple(ast.literal_eval(b) for b in bounds))
            except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
                right_val = None
        pos = not isinstance(op, (ast.NotEq, ast.IsNot, ast.NotIn))
        c = _classify_compare_op(
            op, left, comparators, text, left_text, right_lit, right_val, pos, subject_node
        )
        # Which side is the subject and which the expectation was decided
        # above, including the `assert 3 == calc()` flip, so the name sets come
        # from those nodes rather than being re-derived. EXPECTED_VALUE_DERIVED
        # needs them to tell a renamed constant from a recomputed expectation.
        c.left_names = _referenced_names(subject_node)
        c.right_names = _referenced_names(expect_node)
        return c
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        # `assert not x` is the negated form of `assert x`.
        inner = _classify_assert_expr(test.operand, text)
        return _Classified(
            inner.form, inner.strength, inner.left, inner.right_literal,
            inner.right_value, inner.epsilon, inner.epsilon_kind, not inner.positive,
            inner.left_names, inner.right_names,
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


def _assignment_name_targets(target: ast.AST) -> list[str]:
    """Local names an assignment target binds.

    Bare names and tuple/list unpacks. Subscript and attribute targets are
    not locals; starred leftovers are skipped. E4 / THREATMODEL 86g: the
    spellings that hide a recomputed expectation, not every bindable node.
    """
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        names: list[str] = []
        for elt in target.elts:
            names.extend(_assignment_name_targets(elt))
        return names
    return []


def _binding_maps(
    func,
    *,
    include_definitions: bool = True,
    unparse_memo: dict[int, str] | None = None,
    refs_memo: dict[int, tuple[str, ...]] | None = None,
    flags: dict[str, bool] | None = None,
) -> tuple[dict[str, str], dict[str, tuple[str, ...]]]:
    """Collect definition keys and referenced names in one AST walk.

    The two maps used to be built by `_binding_definitions` and
    `_local_bindings`, each with separate assignment and walrus walks. That
    meant four complete traversals of every test unit before exclusivity was
    considered. The 500-file perf gate exercises thousands of small units, so
    the repeated traversal was measurable there. One pass can produce both
    maps without changing either contract.

    Definition keys use canonical source (`ast.unparse`) rather than raw text,
    so reformatting an expression is not a change — the first false positive
    this would otherwise invent. A name bound more than once takes the joined
    keys of every right-hand side because checkwash cannot tell which one
    reaches the assertion without evaluating. Assignment keys remain ahead of
    walrus keys, matching the former two-pass ordering.

    **Not `ast.dump`.** The first version used it and broke the byte-identical
    guarantee: `ast.dump` renders the AST's internal field set, which changes
    between Python releases, so 3.13 produced different IR from 3.11 and 3.12
    for identical input. The nine-way byte-compare job caught it on the release
    commit — the split was by interpreter version, not by OS, which is the
    signature. `ast.unparse` emits code, not node internals.

    This cannot be verified on a single interpreter: only the matrix can see a
    cross-version divergence, which is precisely why that job exists.
    """
    definitions: dict[str, list[str]] = {}
    walrus_definitions: dict[str, list[str]] = {}
    assignment_references: dict[str, set[str]] = {}
    walrus_references: dict[str, set[str]] = {}

    # `_ordered_bindings` visits the same value nodes for its position-keyed
    # map; unparse and reference extraction are the expensive parts of both
    # walks, so a caller working per unit shares the results through the two
    # memos (the perf gate's 500-file budget is what noticed — 3.08s over
    # 2.5s on the slowest CI leg when every value was unparsed twice).
    def _key(value: ast.AST) -> str:
        if unparse_memo is not None:
            hit = unparse_memo.get(id(value))
            if hit is not None:
                return hit
        try:
            key = ast.unparse(value)
        except (AttributeError, ValueError):  # pragma: no cover - defensive
            key = ""
        if unparse_memo is not None:
            unparse_memo[id(value)] = key
        return key

    def _refs(value: ast.AST) -> tuple[str, ...]:
        if refs_memo is not None:
            hit = refs_memo.get(id(value))
            if hit is not None:
                return hit
        refs = _referenced_names(value)
        if refs_memo is not None:
            refs_memo[id(value)] = refs
        return refs

    for node in ast.walk(func):
        if (
            flags is not None
            and node is not func
            and isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            )
        ):
            # A nested named scope binds its name without an assignment RHS.
            # Keep it out of the frozen unit-level definition map, but make
            # sure the positional binding walk runs so an oracle can prove
            # that local provider is live at its exact statement position.
            flags["named_scope"] = True
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            targets, value = [node.target], node.value
        elif isinstance(node, ast.NamedExpr) and isinstance(node.target, ast.Name):
            if flags is not None:
                flags["walrus"] = True
            if include_definitions:
                walrus_definitions.setdefault(node.target.id, []).append(
                    _key(node.value)
                )
            walrus_references.setdefault(node.target.id, set()).update(
                _refs(node.value)
            )
            continue
        else:
            continue
        if value is None:
            continue
        if include_definitions:
            key = _key(value)
        refs = set(_refs(value))
        for target in targets:
            for name in _assignment_name_targets(target):
                if include_definitions:
                    definitions.setdefault(name, []).append(key)
                assignment_references.setdefault(name, set()).update(refs)
    # Unit separator, not "|": a Python expression can contain a bitwise or,
    # and `resolve_through` has to be able to tell "one binding" from "several".
    definition_names = definitions.keys() | walrus_definitions.keys()
    definition_map = {
        name: "".join(definitions.get(name, []) + walrus_definitions.get(name, []))
        for name in sorted(definition_names)
    }
    # Preserve `_local_bindings`' former insertion order: every ordinary
    # assignment name in walk order, followed by walrus-only names. Map order
    # is not part of detector policy, but keeping it costs nothing and makes
    # this a strict refactor for focused frontend callers too.
    references = {name: set(refs) for name, refs in assignment_references.items()}
    for name, refs in walrus_references.items():
        references.setdefault(name, set()).update(refs)
    reference_map = {name: tuple(sorted(refs)) for name, refs in references.items()}
    return definition_map, reference_map


def _binding_definitions(func) -> dict[str, str]:
    """Definition half of `_binding_maps` for focused frontend callers."""
    return _binding_maps(func)[0]


def _local_bindings(func) -> dict[str, tuple[str, ...]]:
    """Reference half of `_binding_maps` for focused frontend callers."""
    return _binding_maps(func, include_definitions=False)[1]


_TRY_TYPES = tuple(
    t for t in (getattr(ast, "Try", None), getattr(ast, "TryStar", None)) if t is not None
)


def _named_scope_binding_key(node: ast.AST) -> str:
    """Stable internal reaching key for a lexical ``def``/``class``."""
    return f"<{type(node).__name__}>"


def _ordered_bindings(
    func,
    *,
    unparse_memo: dict[int, str] | None = None,
    refs_memo: dict[int, tuple[str, ...]] | None = None,
    has_walrus: bool = True,
) -> dict[str, list[tuple[tuple[int, int], bool, str, tuple[str, ...]]]]:
    """name -> [(statement position, conditional?, canonical key)] in source
    order, for the per-assertion reaching-definition computation.

    `_binding_maps` deliberately joins every definition of a name because it
    serves unit-level consumers; the reaching computation needs the same keys
    with position and branch information kept. A binding inside an `if`/loop/
    `try`/`match` arm may or may not execute, so it is conditional; a `with`
    body and a `finally` always run. Bindings inside nested defs and lambdas
    are skipped — they do not execute at the unit's own statement positions —
    and a name bound only there stays absent, which consumers treat as
    "fall back to the unit-level map". Walruses are scanned on simple
    statements and recorded as conditional (short-circuit operands may not
    evaluate); one inside a compound statement's header is a documented miss
    with the same fallback.
    """
    out: dict[str, list[tuple[tuple[int, int], bool, str, tuple[str, ...]]]] = {}

    def record(name: str, pos: tuple[int, int], conditional: bool, value: ast.AST) -> None:
        key = None
        if unparse_memo is not None:
            key = unparse_memo.get(id(value))
        if key is None:
            try:
                key = ast.unparse(value)
            except (AttributeError, ValueError):  # pragma: no cover - defensive
                key = ""
            if unparse_memo is not None:
                unparse_memo[id(value)] = key
        refs = None
        if refs_memo is not None:
            refs = refs_memo.get(id(value))
        if refs is None:
            refs = _referenced_names(value)
            if refs_memo is not None:
                refs_memo[id(value)] = refs
        out.setdefault(name, []).append((pos, conditional, key, refs))

    # Walruses are rare, and `_binding_maps` has already walked the whole
    # unit: callers pass its verdict in so walrus-free code skips every
    # per-statement scan without a pre-scan of its own (the perf gate's
    # 500-file budget felt both spellings).

    def walk(stmts: list[ast.stmt], conditional: bool) -> None:
        for st in stmts:
            pos = (st.lineno, st.col_offset)
            if isinstance(
                st, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            ):
                if not conditional:
                    # Only a definitely executed named definition is positive
                    # local-provider/callable evidence. Correlating an
                    # unknown branch's definition with an oracle in the same
                    # branch would need path identities that IR v1 does not
                    # carry, so that shape deliberately fails silent.
                    out.setdefault(st.name, []).append(
                        (
                            pos,
                            False,
                            _named_scope_binding_key(st),
                            (),
                        )
                    )
                continue
            if isinstance(st, ast.Assign):
                for target in st.targets:
                    for name in _assignment_name_targets(target):
                        record(name, pos, conditional, st.value)
            elif isinstance(st, (ast.AnnAssign, ast.AugAssign)) and st.value is not None:
                for name in _assignment_name_targets(st.target):
                    record(name, pos, conditional, st.value)
            if isinstance(st, ast.If):
                truth = _static_truth(st.test)
                if truth is True:
                    walk(st.body, conditional)
                elif truth is False:
                    walk(st.orelse, conditional)
                else:
                    walk(st.body, True)
                    walk(st.orelse, True)
            elif isinstance(st, ast.While):
                walk(st.body, True)
                walk(st.orelse, True)
            elif isinstance(st, (ast.For, ast.AsyncFor)):
                walk(st.body, True)
                walk(st.orelse, True)
            elif isinstance(st, _TRY_TYPES):
                walk(st.body, True)
                for handler in st.handlers:
                    walk(handler.body, True)
                walk(st.orelse, True)
                walk(st.finalbody, conditional)
            elif isinstance(st, (ast.With, ast.AsyncWith)):
                walk(st.body, conditional)
            elif isinstance(st, ast.Match):
                for case in st.cases:
                    walk(case.body, True)
            elif has_walrus:
                for sub in ast.walk(st):
                    if isinstance(sub, ast.NamedExpr) and isinstance(sub.target, ast.Name):
                        record(sub.target.id, pos, True, sub.value)
    walk(func.body, False)
    for entries in out.values():
        entries.sort(key=lambda e: e[0])
    return out


def _reaching_entries(
    pos: tuple[int, int],
    name: str,
    ordered: dict[str, list[tuple[tuple[int, int], bool, str, tuple[str, ...]]]],
) -> list[tuple[tuple[int, int], bool, str, tuple[str, ...]]]:
    """The entries that can reach position `pos` for `name`: the last
    unconditional binding before it plus every conditional one after that."""
    entries = ordered.get(name)
    if not entries:
        return []
    prior = [e for e in entries if e[0] < pos]
    if not prior:
        return []
    last_uncond = None
    for i, e in enumerate(prior):
        if not e[1]:
            last_uncond = i
    if last_uncond is None:
        return prior
    return [prior[last_uncond]] + [e for e in prior[last_uncond + 1 :] if e[1]]


def _reaching_keys(
    node: ast.AST,
    names: set[str],
    ordered: dict[str, list[tuple[tuple[int, int], bool, str]]],
) -> dict[str, str]:
    """The reaching-definition key per consumed name at this assertion.

    The last unconditional binding before the assertion, joined with every
    conditional binding between it and the assertion — the per-assertion form
    of the "last unconditional binding is the one the assertion reads"
    semantics SPEC §5 already states. A name bound in the unit only after the
    assertion maps to "": equal on both sides of a tail append, different
    when a definition moves across the assertion.
    """
    pos = (node.lineno, node.col_offset)
    result: dict[str, str] = {}
    for name in sorted(names):
        if name not in ordered:
            continue
        reach = _reaching_entries(pos, name, ordered)
        result[name] = "\x1f".join(e[2] for e in reach)
    return result


def _positional_closure(
    node: ast.AST,
    seeds: tuple[str, ...],
    ordered: dict[str, list[tuple[tuple[int, int], bool, str, tuple[str, ...]]]],
) -> set[str]:
    """Names transitively read at this assertion's position.

    `_resolve_through` follows the unit-level joined map, so `F` drags in
    every name any definition of `F` ever references — and an assertion in
    one case was charged with names only other cases read, which is how a
    pure insertion kept firing after the direct keys were made positional
    (sympy ed75b73d, R1). This closure follows only the definitions that
    reach this position.
    """
    pos = (node.lineno, node.col_offset)
    seen: set[str] = set()
    queue = list(seeds)
    while queue:
        name = queue.pop()
        if name in seen:
            continue
        seen.add(name)
        for entry in _reaching_entries(pos, name, ordered):
            queue.extend(n for n in entry[3] if n not in seen)
    return seen


def _reaching_sig(reaching: dict[str, str], direct: set[str]) -> str:
    """Serialize the direct names' reaching entries for assertion pairing.

    Direct names only: `F` resolved transitively drags in names that other
    definitions of `F` reference, whose reaching keys legitimately differ
    across an insertion — a polluted signature pushes untouched twins back
    to the FIFO fallback the signature exists to avoid.
    """
    return "\x1e".join(
        f"{name}\x1d{reaching[name]}" for name in sorted(direct) if name in reaching
    )


def _exclusive_bindings(func) -> tuple[str, ...]:
    """Multiply-bound names whose every binding sits in a different branch arm.

    A statement walk that labels each binding with its branch path — one
    `(id(branch_stmt), arm_index)` per enclosing `if`/`match` arm. Two bindings
    are exclusive when their paths diverge: at the first differing step they
    are different arms of the same statement, so no execution reaches both.
    A name qualifies only if *all* its bindings are pairwise exclusive —
    `expected = old` followed by an unconditional `expected = new` shares a
    path and must not qualify, because the second binding is the one the
    assertion reads.

    Records exactly the node kinds `_binding_maps` records — Assign,
    AnnAssign, AugAssign and walrus — so the two walks agree on what counts
    as a binding. Deliberately narrow: `for`/`while`/`with`/`try` bodies keep their parent's
    path (a rebind there is sequential or partially-executed, not an
    alternative), a walrus in an `if` test belongs to the parent path (the
    test runs before the branch), and nested `def`/`class` bodies keep the
    parent path too, mirroring the flat walk `_binding_definitions` uses.
    Conservative failures fire the rule, which is the safe direction.
    """
    found: dict[str, list[tuple]] = {}

    def record(stmt, path) -> None:
        for node in ast.walk(stmt):
            if isinstance(node, ast.Assign):
                targets, value = node.targets, node.value
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
                targets, value = [node.target], node.value
            elif isinstance(node, ast.NamedExpr) and isinstance(node.target, ast.Name):
                found.setdefault(node.target.id, []).append(path)
                continue
            else:
                continue
            if value is None:
                continue
            for target in targets:
                for name in _assignment_name_targets(target):
                    found.setdefault(name, []).append(path)

    def record_expr(expr, path) -> None:
        if expr is None:
            return
        for node in ast.walk(expr):
            if isinstance(node, ast.NamedExpr) and isinstance(node.target, ast.Name):
                found.setdefault(node.target.id, []).append(path)

    def walk(stmts, path) -> None:
        for s in stmts:
            if isinstance(s, ast.If):
                record_expr(s.test, path)
                walk(s.body, path + ((id(s), 0),))
                walk(s.orelse, path + ((id(s), 1),))
            elif isinstance(s, ast.Match):
                record_expr(s.subject, path)
                for i, case in enumerate(s.cases):
                    walk(case.body, path + ((id(s), i),))
            elif isinstance(s, (ast.For, ast.AsyncFor)):
                record_expr(s.iter, path)
                walk(s.body, path)
                walk(s.orelse, path)
            elif isinstance(s, ast.While):
                record_expr(s.test, path)
                walk(s.body, path)
                walk(s.orelse, path)
            elif isinstance(s, (ast.With, ast.AsyncWith)):
                for item in s.items:
                    record_expr(item.context_expr, path)
                walk(s.body, path)
            elif isinstance(s, ast.Try):
                walk(s.body, path)
                for h in s.handlers:
                    walk(h.body, path)
                walk(s.orelse, path)
                walk(s.finalbody, path)
            elif isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                walk(s.body, path)
            else:
                record(s, path)

    walk(func.body, ())

    def exclusive(paths: list[tuple]) -> bool:
        for i in range(len(paths)):
            for j in range(i + 1, len(paths)):
                a, b = paths[i], paths[j]
                diverged = False
                for x, y in zip(a, b):
                    if x != y:
                        diverged = x[0] == y[0]
                        break
                if not diverged:
                    return False
        return True

    return tuple(
        sorted(name for name, paths in found.items() if len(paths) > 1 and exclusive(paths))
    )


def _resolve_through(names: tuple[str, ...], bindings: dict[str, tuple[str, ...]]) -> tuple[str, ...]:
    """Follow local bindings to the names an expression really depends on.

    `expected = sum(items)` then `== expected` depends on `items`, which is
    what makes it a recomputation of the subject's own input rather than an
    independent expectation. Unbound names resolve to themselves so a module
    constant or a fixture argument stays distinguishable from a local
    computation. Cycles terminate on the `seen` set.

    Every name walked through is kept, not just the leaves. `items = [50.0,
    50.0]` binds a literal with no name references of its own, so dropping
    intermediates made `items` disappear from the closure — and `items` is
    exactly the name the subject shares. The link being looked for is between
    names as written on both sides, not between root values.
    """
    seen: set[str] = set()
    queue = list(names)
    while queue:
        name = queue.pop()
        if name in seen:
            continue
        seen.add(name)
        queue.extend(bindings.get(name, ()))
    return tuple(sorted(seen))


def _referenced_names(node) -> tuple[str, ...]:
    """Every `Name` id in a subtree, sorted and unique.

    Sorted rather than set-ordered because this reaches the IR, and no set
    iteration order is allowed to leak into output (SPEC §8).
    """
    if node is None:
        return ()
    return tuple(sorted({n.id for n in ast.walk(node) if isinstance(n, ast.Name)}))


def _classify_compare_op(
    op, left, comparators, text, left_text, right_lit, right_val, pos, subject=None
) -> _Classified:
    """The comparison-operator chain, split out so the caller can attach name
    sets to whichever `_Classified` comes back without repeating them at nine
    return sites. `subject` is the post-flip subject node: the `len()` shape
    rule must follow it, or `assert 3 == len(x)` and `assert len(x) == 3` rate
    differently and a pure operand flip reads as a weakening (SPEC §3 says
    `len(x) == n` is TYPE_SHAPE, full stop — audit 2026-08-19)."""
    if subject is None:
        subject = left
    if isinstance(op, (ast.Eq, ast.NotEq)):
        # Self-comparison (`assert f(x) == f(x)`) can never fail: the
        # oracle is gone even though the form still looks exact. Strip
        # identity ops (+0, -0, *1, /1) from both sides first, so
        # `f(x) == f(x) + 0` is caught too (confirmed red-team finding).
        if comparators and _norm(_strip_identity(left, text)) == _norm(
            _strip_identity(comparators[0], text)
        ):
            return _Classified("tautology", S.TAUTOLOGY, left_text, right_lit, right_val)
        if isinstance(subject, ast.Call) and _dotted(subject.func) == "len":
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


def _classify_unittest_call(node: ast.Call, text: str) -> _Classified | None:
    if not (isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == "self"):
        return None
    method = node.func.attr
    if method not in _UNITTEST_MAP:
        return None
    form, level = _UNITTEST_MAP[method]
    # `assertIs(x, None)` / `assertIsNot(x, None)` are the generic spellings of
    # assertIsNone / assertIsNotNone. Leaving them at compare_eq made the
    # dialects incoherent — bare `assert x is None` is non_null, so a pure
    # spelling conversion was reported as a polarity inversion while a genuine
    # cross-dialect inversion was not (audit 2026-08-19).
    if method in ("assertIs", "assertIsNot") and len(node.args) > 1:
        for arg in node.args[:2]:
            if isinstance(arg, ast.Constant) and arg.value is None:
                method = "assertIsNone" if method == "assertIs" else "assertIsNotNone"
                form, level = _UNITTEST_MAP[method]
                break
    positive = method not in _NEGATED_UNITTEST
    left_text = None
    right_lit = None
    right_val = None
    epsilon = None
    epsilon_kind = None
    subject_node: ast.AST | None = None
    expect_node: ast.AST | None = None
    if node.args:
        subject_node = node.args[0]
        if len(node.args) > 1:
            expect_node = node.args[1]
            # Same literal-side flip as bare assert: `assertEqual(3, calc())`.
            if _is_literal(node.args[0]) and not _is_literal(node.args[1]):
                expect_node, subject_node = node.args[0], node.args[1]
        left_text = text.seg(subject_node) if subject_node is not None else None
        if expect_node is not None:
            right_lit = _literal_repr(expect_node, text)
            right_val = _literal_value(expect_node)
        if form == "compare_eq" and level == S.EXACT_VALUE and len(node.args) > 1:
            if _is_container_literal(node.args[0]) or _is_container_literal(node.args[1]):
                level = S.EXACT_STRUCT
        # The len() shape rule, on the post-flip subject, same as the bare
        # lattice: `assertEqual(len(x), 3)` and `assert len(x) == 3` are both
        # TYPE_SHAPE. Without it the unittest dialect rated the shape
        # EXACT_VALUE and a routine modernisation blocked at high
        # (audit 2026-08-19).
        if (
            form == "compare_eq"
            and level == S.EXACT_VALUE
            and isinstance(subject_node, ast.Call)
            and _dotted(subject_node.func) == "len"
        ):
            form, level = "type_shape", S.TYPE_SHAPE
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
        if epsilon is None:
            # assertAlmostEqual's implicit default is places=7. Recording it
            # makes `places=0` appearing a loosening of that default instead
            # of silence — same one-sided-event defect as pytest.approx
            # (audit 2026-08-19).
            epsilon, epsilon_kind = "7", "places"
    if form == "truthy" and node.args and _is_literal(node.args[0]):
        form, level = "tautology", S.TAUTOLOGY
    if form == "compare_eq" and subject_node is not None and expect_node is not None:
        # Self-comparison with identity ops stripped, on the two actual
        # operands — the post-flip subject against the post-flip expectation.
        # The old check read `seg(args[1])` against `seg(args[1])`, so every
        # literal-first `assertEqual(expected, actual)` — the canonical
        # unittest order — was a textual self-comparison and classified
        # TAUTOLOGY(10). With strength 10 recorded, any weakening read as a
        # strength rise and the whole lattice was inert on the dialect's most
        # common spelling (audit 2026-08-19).
        if _norm(_strip_identity(subject_node, text)) == _norm(
            _strip_identity(expect_node, text)
        ):
            form, level = "tautology", S.TAUTOLOGY
    return _Classified(
        form,
        level,
        left_text,
        right_lit,
        right_val,
        epsilon,
        epsilon_kind,
        positive,
        _referenced_names(subject_node),
        _referenced_names(expect_node),
        # Same vacuousness test the bare path applies (`assert str(1) == "1"`
        # cannot fail): without it, `self.assertEqual(str(1), "1")` counted as
        # oracle mass for D4/D5 and reopened the padding family in the
        # unittest dialect (THREATMODEL 20/25/46, audit 2026-08-19).
        _is_trivial_subject(subject_node)
        and (expect_node is None or _is_trivial_subject(expect_node)),
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


def _canonical_import_path(
    node: ast.AST, import_bindings: dict[str, str] | None = None
) -> str | None:
    """Resolve one dotted expression through a statically imported root."""
    dotted = _dotted(node)
    if dotted is None:
        return None
    root, dot, suffix = dotted.partition(".")
    source = (import_bindings or {}).get(root)
    return source + (dot + suffix if dot else "") if source is not None else dotted


def _usefixtures_names(
    node: ast.AST, import_bindings: dict[str, str] | None = None
) -> tuple[str, ...]:
    """Literal fixtures requested by a pytest usefixtures decorator/call."""
    if not isinstance(node, ast.Call):
        return ()
    target = _canonical_import_path(node.func, import_bindings)
    if target not in ("pytest.mark.usefixtures", "mark.usefixtures"):
        return ()
    return tuple(
        arg.value
        for arg in node.args
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
    )


def _decorator_usefixtures(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
    import_bindings: dict[str, str] | None = None,
) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                name
                for decorator in node.decorator_list
                for name in _usefixtures_names(decorator, import_bindings)
            }
        )
    )


def _module_usefixtures(
    tree: ast.Module, import_bindings: dict[str, str] | None = None
) -> tuple[str, ...]:
    names: set[str] = set()
    for stmt in tree.body:
        if not isinstance(stmt, ast.Assign) or not any(
            isinstance(target, ast.Name) and target.id == "pytestmark"
            for target in stmt.targets
        ):
            continue
        values = (
            stmt.value.elts
            if isinstance(stmt.value, (ast.List, ast.Tuple))
            else (stmt.value,)
        )
        for value in values:
            names.update(_usefixtures_names(value, import_bindings))
    return tuple(sorted(names))


def _module_pytestmark_values(tree: ast.Module) -> tuple[ast.AST, ...]:
    """Individual marks installed through a module-level ``pytestmark``."""
    values: list[ast.AST] = []
    for stmt in tree.body:
        if not isinstance(stmt, ast.Assign) or not any(
            isinstance(target, ast.Name) and target.id == "pytestmark"
            for target in stmt.targets
        ):
            continue
        if isinstance(stmt.value, (ast.List, ast.Tuple)):
            values.extend(stmt.value.elts)
        else:
            values.append(stmt.value)
    return tuple(values)


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


def _caught_types(type_expr: ast.AST | None) -> tuple[str, ...]:
    """Dotted names of the exception types one catcher expression spells.

    `None` (a bare `except`) is (); tuples expand to their elements; an
    expression that is not a name chain — `E` resolved from an assignment
    would need binding analysis, a call, a subscript — records as "?", which
    no membership test matches: the aliased/dynamic spellings stay a named
    residual on every path (issue #57 §3), priced in the matrix rather than
    guessed at here.
    """
    if type_expr is None:
        return ()
    if isinstance(type_expr, ast.Tuple):
        return tuple(_dotted(e) or "?" for e in type_expr.elts)
    return (_dotted(type_expr) or "?",)


def _catches_assertionerror(caught: tuple[str, ...]) -> bool:
    """The one type-set truth: can this catcher swallow a failed assert?

    A bare catcher, or any type whose leaf is in `_BROAD_EXCEPTIONS`
    (Exception and BaseException are AssertionError's ancestors), catches it.
    Both the `except` path and the `with` path decide through this predicate —
    issue #57's whole point: the 2026-09-01 history was per-spelling patches
    (except covered, then `pytest.raises` bypassed, then `suppress`, then the
    tuple spelling) because the two paths kept separate type logic.
    """
    return not caught or any(c.rsplit(".", 1)[-1] in _BROAD_EXCEPTIONS for c in caught)


def _handler_info(node: ast.ExceptHandler) -> tuple[tuple[str, ...], bool]:
    caught = _caught_types(node.type)
    return caught, _catches_assertionerror(caught)


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


def _wraps_bare_assert(body: list[ast.stmt]) -> bool:
    """A bare `assert` statement runs directly in these statements.

    Narrower than `_contains_oracle` on purpose: `_is_oracle_call` treats any
    `assert*`-named call as an oracle, so a legitimate contract test —
    `with pytest.raises(AssertionError): my_validator(bad)` — would look like
    it wraps one. The neutralization signal keys only on a real `assert`
    statement, which is what both reported bypasses wrap and what a contract
    test of a helper never does. Nested scopes skipped, as everywhere else.
    """
    stack: list[ast.AST] = list(body)
    while stack:
        node = stack.pop()
        if isinstance(node, ast.Assert):
            return True
        for child in ast.iter_child_nodes(node):
            if isinstance(
                child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
            ):
                continue
            stack.append(child)
    return False


_NEUTRALIZING_CONTEXTS = ("suppress", "raises", "assertRaises", "assertRaisesRegex")


def _neutralizes_assertionerror(call: ast.AST) -> str | None:
    """A `with`-context that catches a failed assertion.

    `suppress(...)` swallows it, `pytest.raises(...)` expects it, and the
    unittest dialect — `self.assertRaises(...)` / `assertRaisesRegex(...)` as
    a context manager — is `raises` with a different surface (issue #57 §1;
    the regex variant still requires the assert to fail, the pattern only
    constrains the message). Whether the named type set can catch an
    AssertionError is decided by `_catches_assertionerror`, the same
    predicate the `except` path uses, so `pytest.raises(Exception)` and
    `raises(BaseException)` count exactly as `except Exception` always has
    (issue #57 §2 — the asymmetry that produced the tuple hole). Matched on
    the trailing callee name so an alias can't dodge it — `from contextlib
    import suppress as s` still resolves to `suppress`. For `suppress` every
    positional argument counts (it can suppress several); for the raises
    family only the first argument is the expected type. A callee bound to a
    bare name (`r = pytest.raises`) and an aliased type value
    (`E = AssertionError`) stay named residuals, asserted silent in
    tests/test_neutralization_matrix.py.
    """
    if not isinstance(call, ast.Call):
        return None
    leaf = (_dotted(call.func) or "").rsplit(".", 1)[-1]
    if leaf not in _NEUTRALIZING_CONTEXTS:
        return None
    candidates = call.args if leaf == "suppress" else call.args[:1]
    caught = tuple(t for arg in candidates for t in _caught_types(arg))
    if caught and _catches_assertionerror(caught):
        return leaf
    return None


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


def _unreachable_ids(func: ast.AST) -> set[int]:
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
    an assertion where checkwash still believed it ran — reopening bypass #29
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


_PARAMETRIZE = ("pytest.mark.parametrize", "mark.parametrize", "parametrize")


def _call_argument(call: ast.Call, position: int, keyword: str) -> ast.AST | None:
    if len(call.args) > position:
        return call.args[position]
    return next((item.value for item in call.keywords if item.arg == keyword), None)


def _is_parametrize(
    dec: ast.AST, import_bindings: dict[str, str] | None = None
) -> bool:
    return isinstance(dec, ast.Call) and (
        _canonical_import_path(dec.func, import_bindings) in _PARAMETRIZE
    )


def _parametrize_names(dec: ast.Call) -> list[str]:
    names_node = _call_argument(dec, 0, "argnames")
    if names_node is None:
        return []
    if isinstance(names_node, ast.Constant) and isinstance(names_node.value, str):
        return [name.strip() for name in names_node.value.split(",") if name.strip()]
    if isinstance(names_node, (ast.List, ast.Tuple)):
        return [
            elt.value
            for elt in names_node.elts
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
        ]
    return []


def _parametrize_provider_modes(
    marks, import_bindings: dict[str, str] | None = None
) -> dict[str, bool]:
    """Literal parametrize arguments mapped to direct-provider status.

    Pytest's ``indirect`` flag changes provider identity without changing the
    function signature. Unknown/dynamic values are conservatively retained as
    fixture requests: treating one as direct could hide an operative fixture.
    The same representation is used for module, class, and function marks so
    inherited provider metadata cannot diverge from function-local handling.
    """
    providers: dict[str, bool] = {}
    for dec in marks:
        if not _is_parametrize(dec, import_bindings):
            continue
        assert isinstance(dec, ast.Call)
        names = _parametrize_names(dec)
        if not names:
            continue
        indirect_node = _call_argument(dec, 2, "indirect")
        if indirect_node is None or (
            isinstance(indirect_node, ast.Constant) and indirect_node.value is False
        ):
            modes = {name: True for name in names}
        elif isinstance(indirect_node, ast.Constant) and indirect_node.value is True:
            modes = {name: False for name in names}
        elif isinstance(indirect_node, (ast.List, ast.Tuple)) and all(
            isinstance(elt, ast.Constant) and isinstance(elt.value, str)
            for elt in indirect_node.elts
        ):
            indirect = {elt.value for elt in indirect_node.elts}
            modes = {name: name not in indirect for name in names}
        else:
            modes = {name: False for name in names}

        for name, direct in modes.items():
            # Duplicate parametrization of one argument is rejected by pytest.
            # If malformed source nevertheless contains it, retaining any
            # indirect interpretation is the fail-closed provider choice.
            providers[name] = providers.get(name, True) and direct
    return providers


def _merge_parametrize_provider_modes(
    inherited: dict[str, bool], local: dict[str, bool]
) -> dict[str, bool]:
    """Merge nested mark scopes without letting an indirect mode disappear."""
    merged = dict(inherited)
    for name, direct in local.items():
        merged[name] = merged.get(name, True) and direct
    return merged


def _direct_parametrize_names(
    func,
    import_bindings: dict[str, str] | None = None,
    inherited: dict[str, bool] | None = None,
) -> set[str]:
    providers = _merge_parametrize_provider_modes(
        inherited or {},
        _parametrize_provider_modes(func.decorator_list, import_bindings),
    )
    return {name for name, direct in providers.items() if direct}


def _parameter_default_providers(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    imports: dict[str, str],
) -> dict[str, tuple[str, str]]:
    """Statically evaluated Python defaults keyed by parameter name.

    Defaults execute in the enclosing module scope, so an imported object can
    be canonicalized before the parameter shadows its spelling.  An
    unresolved local expression retains canonical source as positive provider
    identity; malformed/unparseable expressions fail silent.
    """
    positional = func.args.posonlyargs + func.args.args
    pairs = list(zip(positional[-len(func.args.defaults) :], func.args.defaults))
    pairs.extend(
        (argument, value)
        for argument, value in zip(func.args.kwonlyargs, func.args.kw_defaults)
        if value is not None
    )
    out: dict[str, tuple[str, str]] = {}
    for argument, value in pairs:
        provider = _resolved_value_identity(value, imports)
        if provider is None:
            try:
                provider = ast.unparse(value)
            except (AttributeError, ValueError):  # pragma: no cover - defensive
                continue
        if provider:
            out[argument.arg] = ("default", provider)
    return out


def _param_cell_value(cell):
    """The value inside a parametrize cell, seen through `pytest.param`.

    `[1, 2, 3]` becoming `[pytest.param(1, marks=pytest.mark.skip), ...]` keeps
    every value and every row, and disables the lot. That is `TEST_DISABLED`'s
    event and it is already reported at high; reading the wrapper as part of
    the value made this rule fire on it as well, which is two findings for one
    edit.
    """
    if isinstance(cell, ast.Call) and _dotted(cell.func) in ("pytest.param", "param") and cell.args:
        return cell.args[0]
    return cell


def _param_columns(
    func, import_bindings: dict[str, str] | None = None
) -> dict[str, str]:
    """parametrize argname -> canonical text of that column, row by row.

    The expectation of a parametrized test does not live in the test at all; it
    lives in a column of the decorator's table. Editing that column moves the
    oracle while the assertion stays byte-identical, which is the same shape as
    editing a local binding (THREATMODEL 86a) one level out.

    Only argnames are recorded here. Which of them is the *expectation* is not
    decided by position or by being called `expected` — it is whichever column
    the assertion's expectation side actually consumes, which the detector
    reads off `right_depends_on`. Changing the input column is not changing the
    oracle, and a heuristic on the name would get that wrong.
    """
    out: dict[str, list[str]] = {}
    for dec in func.decorator_list:
        if not _is_parametrize(dec, import_bindings):
            continue
        assert isinstance(dec, ast.Call)
        values = _call_argument(dec, 1, "argvalues")
        if not isinstance(values, (ast.List, ast.Tuple)):
            continue
        names = _parametrize_names(dec)
        if not names:
            continue
        for row in values.elts:
            cells = row.elts if isinstance(row, (ast.List, ast.Tuple)) else [row]
            if len(names) == 1 and not isinstance(row, (ast.List, ast.Tuple)):
                cells = [row]
            for name, cell in zip(names, cells):
                try:
                    out.setdefault(name, []).append(ast.unparse(_param_cell_value(cell)))
                except (AttributeError, ValueError):  # pragma: no cover - defensive
                    out.setdefault(name, []).append("")
    return {name: "".join(vals) for name, vals in sorted(out.items())}


def _fixture_definitions(
    tree: ast.Module,
    definition_imports: dict[int, dict[str, str]] | None = None,
) -> dict[str, str]:
    """Same-file `@pytest.fixture` name -> canonical text of what it produces.

    A fixture is not a collected unit, so nothing in the IR saw its body. An
    expectation supplied by one could be edited with the assertion untouched
    and every rule silent. Conftest fixtures are deliberately out of scope and
    recorded as a residual rather than half-implemented.
    """
    out: dict[str, str] = {}
    live = _module_callable_scopes(tree)
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if live.get(node.name) is not node:
            continue
        exact = (definition_imports or {}).get(id(node))
        if not _is_fixture_def(node, exact):
            continue
        fixture_name = _fixture_public_name(node, exact)
        if fixture_name is None:
            continue
        produced = []
        for sub in ast.walk(node):
            if isinstance(sub, (ast.Return, ast.Yield)) and sub.value is not None:
                try:
                    produced.append(ast.unparse(sub.value))
                except (AttributeError, ValueError):  # pragma: no cover - defensive
                    produced.append("")
        if produced:
            out[fixture_name] = "|".join(produced)
    return dict(sorted(out.items()))


def _param_case_count(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    import_bindings: dict[str, str] | None = None,
) -> int | None:
    """pytest test-item count contributed by @pytest.mark.parametrize rows.

    Deleting rows deletes test items; in pytest's model each row IS a test
    unit, so the count belongs in the IR (confirmed red-team finding).
    """
    total: int | None = None
    for dec in func.decorator_list:
        if not _is_parametrize(dec, import_bindings):
            continue
        assert isinstance(dec, ast.Call)
        values = _call_argument(dec, 1, "argvalues")
        if not isinstance(values, (ast.List, ast.Tuple)):
            continue
        # A row is a test item only if it still runs. Counting `len(elts)`
        # meant wrapping every row in `pytest.param(..., marks=pytest.mark.skip)`
        # left the count unchanged while the whole parametrized test stopped
        # executing — deleting the same rows blocked, skipping them did not
        # (reader audit 2026-08-02).
        rows = sum(0 if _param_row_disabled(e) else 1 for e in values.elts)
        total = rows if total is None else total * rows
    return total


_STMT_BODY_FIELDS = ("body", "orelse", "finalbody")


def _skip_call_guards(func: ast.FunctionDef | ast.AsyncFunctionDef, text) -> dict[int, str]:
    """id(call node) -> conjunction of enclosing `if` condition sources.

    `if PY_3_14_PLUS and not slots: pytest.xfail(...)` is the imperative
    spelling of `skipif(PY_3_14_PLUS and not slots)`; without the guard, D6
    cannot tell it from an unconditional kill (attrs 7373d88, FP sweep).
    Orelse branches contribute the negated test. Loop/try/with/match bodies
    pass conditions through without adding their own: an unrecorded conjunct
    only makes the real skip *more* conditional, so a recorded guard that is
    false somewhere means the real condition is false there too, and one that
    is not earns nothing — both err toward flagging.
    """
    out: dict[int, str] = {}

    def record(stmts: list[ast.stmt], conds: tuple[str, ...]) -> None:
        for stmt in stmts:
            if isinstance(stmt, ast.If):
                t = text.seg(stmt.test) or ""
                record(stmt.body, conds + ((t,) if t else ()))
                record(stmt.orelse, conds + ((f"not ({t})",) if t else ()))
                continue
            compound = False
            for fname in _STMT_BODY_FIELDS:
                sub = getattr(stmt, fname, None)
                if isinstance(sub, list) and any(isinstance(s, ast.stmt) for s in sub):
                    compound = True
                    record([s for s in sub if isinstance(s, ast.stmt)], conds)
            for handler in getattr(stmt, "handlers", None) or []:
                compound = True
                record(handler.body, conds)
            for case in getattr(stmt, "cases", None) or []:
                compound = True
                record(case.body, conds)
            if not compound and conds:
                for node in ast.walk(stmt):
                    if isinstance(node, ast.Call):
                        out[id(node)] = " and ".join(conds)

    record(func.body, ())
    return out


_SCOPE_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
# Callees that invoke a function argument immediately. `partial` is deliberately
# absent: it *constructs*, and the call happens when the partial itself is
# called — which is exactly the edit that turns `job()` into
# `assert callable(job)` (benchmarks/tamper 036).
_INVOKES_ARGUMENT = frozenset({"map", "filter", "apply", "run", "testmod", "exec"})
_DEFERS_ARGUMENT = frozenset({"partial"})


def _scope_nodes(scope):
    """Nodes this scope executes, without descending into nested scopes.

    Nested scopes come back separately, and only when something invokes them.
    """
    stack = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        if isinstance(node, _SCOPE_NODES):
            continue
        yield node
        stack.extend(ast.iter_child_nodes(node))


def _scope_nodes_cached(scope, cache: dict[int, tuple] | None):
    """`_scope_nodes`, memoised per scope for one file's parse.

    A module helper invoked by many units used to be re-walked once per unit
    per consumer — the single largest share of the perf gate's budget after
    the reaching round pushed the slowest CI leg over it.
    """
    if cache is None:
        return _scope_nodes(scope)
    key = id(scope)
    got = cache.get(key)
    if got is None:
        got = tuple(_scope_nodes(scope))
        cache[key] = got
    return got


def _invocations(scope, caches: tuple[dict, dict] | None = None) -> set[str]:
    """Names this scope actually *invokes*.

    Mention is not invocation, and the distinction is the whole design:
    `callable(assert_sum)`, `hasattr`, `inspect.getsource(f)` and `f.__name__`
    all name the oracle without running it, which is precisely the edit these
    attacks make. Counting a bare `Name` argument as a call hides
    benchmarks/tamper 001.

    `caches` is one file's `(scope-nodes, invocations)` memo pair: shared
    module scopes are asked the same question by every unit that reaches
    them, and the answer never changes within a parse.
    """
    nodes_cache = inv_cache = None
    if caches is not None:
        nodes_cache, inv_cache = caches
        hit = inv_cache.get(id(scope))
        if hit is not None:
            return set(hit)
    out: set[str] = set()
    for node in _scope_nodes_cached(scope, nodes_cache):
        if isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                name = _callee_root(item.context_expr)
                if name:
                    out.add(name)
        elif isinstance(node, ast.For):
            name = _callee_root(node.iter)
            if name:
                out.add(name)
        elif isinstance(node, ast.Call):
            name = _callee_root(node)
            if not name:
                continue
            out.add(name)
            if name.split(".")[-1] in _INVOKES_ARGUMENT:
                out.update(a.id for a in node.args if isinstance(a, ast.Name))
    if inv_cache is not None:
        inv_cache[id(scope)] = frozenset(out)
    return out


def _callee_root(node) -> str | None:
    if not isinstance(node, ast.Call):
        return None
    f = node.func
    while isinstance(f, ast.Attribute):
        f = f.value
    return f.id if isinstance(f, ast.Name) else None


def _is_contextmanager(node) -> bool:
    return isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
        (isinstance(d, ast.Name) and d.id == "contextmanager")
        or (isinstance(d, ast.Attribute) and d.attr == "contextmanager")
        for d in node.decorator_list
    )


def _local_scopes(
    func,
    module_scopes: dict[str, ast.AST],
    lexical_facts: tuple[set[str], set[str], set[str]] | None = None,
) -> dict[str, ast.AST]:
    """Callable names visible to this unit: the module's, plus its own nested
    defs and lambdas, plus names bound to a deferred call (`partial`)."""
    lexical, _globals, _nonlocals = (
        lexical_facts
        if lexical_facts is not None
        else _lexical_scope_names(func)
    )
    # Any lexical binding shadows a module helper for the entire function,
    # including parameters supplied by fixtures or parametrize.  Supported
    # local callables are added back below with their own positional proof.
    out = {
        name: target
        for name, target in module_scopes.items()
        if name not in lexical
    }
    for node in ast.walk(func):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node is not func
            and node.name in lexical
        ):
            out[node.name] = node
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if not isinstance(target, ast.Name) or target.id not in lexical:
                    continue
                if isinstance(node.value, ast.Lambda):
                    out[target.id] = node.value
                elif isinstance(node.value, ast.Call):
                    callee = _callee_root(node.value)
                    if callee and callee.split(".")[-1] in _DEFERS_ARGUMENT:
                        for arg in node.value.args:
                            if isinstance(arg, ast.Name) and arg.id in out:
                                out[target.id] = out[arg.id]
                                break
    return out


def _module_callable_scopes(tree: ast.Module) -> dict[str, ast.AST]:
    """Definitely live same-file callables after module execution.

    Tests run only after the module body has completed.  A raw census of all
    top-level definitions therefore keeps stale helpers after a later import,
    assignment, or delete of the same name.  This small final-binding walk
    follows straight-line statements and statically selected ``if`` arms;
    any path-dependent compound binding removes the candidate so uncertainty
    cannot project an obsolete helper into a test call site.
    """
    live: dict[str, ast.AST] = {}

    def remove(names: set[str]) -> None:
        for name in names:
            live.pop(name, None)

    def walk(statements: list[ast.stmt]) -> None:
        for stmt in statements:
            if isinstance(
                stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            ):
                live[stmt.name] = stmt
                continue
            if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                remove(set(_import_bindings((stmt,))))
                continue
            if isinstance(stmt, ast.Assign):
                names = {
                    name
                    for target in stmt.targets
                    for name in _bound_target_names(target)
                }
                remove(names)
                if isinstance(stmt.value, ast.Lambda):
                    for target in stmt.targets:
                        if isinstance(target, ast.Name):
                            live[target.id] = stmt.value
                continue
            if isinstance(stmt, ast.AnnAssign):
                if stmt.value is not None:
                    names = _bound_target_names(stmt.target)
                    remove(names)
                    if isinstance(stmt.target, ast.Name) and isinstance(
                        stmt.value, ast.Lambda
                    ):
                        live[stmt.target.id] = stmt.value
                continue
            if isinstance(stmt, (ast.AugAssign, ast.Delete)):
                targets = (
                    (stmt.target,)
                    if isinstance(stmt, ast.AugAssign)
                    else tuple(stmt.targets)
                )
                remove(
                    {
                        name
                        for target in targets
                        for name in _bound_target_names(target)
                    }
                )
                continue
            if isinstance(stmt, ast.If):
                truth = _static_truth(stmt.test)
                if truth is True:
                    walk(stmt.body)
                elif truth is False:
                    walk(stmt.orelse)
                else:
                    remove(_lexical_scope_names(stmt)[0])
                continue
            # Loops, try/match arms, context-manager targets, and walruses can
            # all leave different final objects on different paths.  Dropping
            # their bound names is the safe final-binding join.
            remove(_lexical_scope_names(stmt)[0])

    walk(tree.body)
    return live


def _local_callable_at_binding(
    scope: ast.AST,
    name: str,
    position: tuple[int, int],
    key: str,
) -> ast.AST | None:
    """The callable node established by one positional local binding.

    ``_local_scopes`` is only a name index.  Two sequential definitions can
    legally reuse one name, so its final AST node cannot identify what an
    earlier call executed.  Match the reaching entry's position as well as
    its stable key, without descending into a nested lexical scope.
    """

    def canonical(node: ast.AST) -> str | None:
        try:
            return ast.unparse(node)
        except (AttributeError, ValueError):  # pragma: no cover - defensive
            return None

    def walk(statements: list[ast.stmt]) -> ast.AST | None:
        for stmt in statements:
            stmt_position = (
                getattr(stmt, "lineno", 0) or 0,
                getattr(stmt, "col_offset", 0) or 0,
            )
            if isinstance(
                stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            ):
                if (
                    stmt_position == position
                    and stmt.name == name
                    and key == _named_scope_binding_key(stmt)
                ):
                    return stmt
                continue
            value = None
            targets: tuple[ast.AST, ...] = ()
            if isinstance(stmt, ast.Assign):
                value, targets = stmt.value, tuple(stmt.targets)
            elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
                value, targets = stmt.value, (stmt.target,)
            if (
                stmt_position == position
                and isinstance(value, ast.Lambda)
                and any(name in _bound_target_names(target) for target in targets)
                and canonical(value) == key
            ):
                return value
            for field in ("body", "orelse", "finalbody"):
                nested = getattr(stmt, field, None)
                if isinstance(nested, list):
                    found = walk(
                        [child for child in nested if isinstance(child, ast.stmt)]
                    )
                    if found is not None:
                        return found
            for handler in getattr(stmt, "handlers", ()):
                found = walk(handler.body)
                if found is not None:
                    return found
            for case in getattr(stmt, "cases", ()):
                found = walk(case.body)
                if found is not None:
                    return found
        return None

    body = getattr(scope, "body", None)
    return walk(body) if isinstance(body, list) else None


def _live_scope_target(
    scope: ast.AST,
    site: ast.AST,
    name: str,
    scopes: dict[str, ast.AST],
    ordered_cache: dict[int, dict] | None = None,
    ordered_bindings: dict | None = None,
    lexical_cache: dict[int, tuple[set[str], set[str], set[str]]] | None = None,
) -> ast.AST | None:
    """Resolve a same-file callable at one invocation position.

    Module names are live unless the caller lexically shadows them (already
    reflected by ``_local_scopes``) or explicitly rebinds a ``global``/
    ``nonlocal`` name.  A supported local callable additionally needs one
    definite reaching binding at this call site; a later definition,
    conditional definition, or intervening rebind fails toward silence.
    """
    target = scopes.get(name)
    if target is None:
        return None
    if not isinstance(
        scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    ):
        return target
    lexical_facts = (
        lexical_cache.get(id(scope)) if lexical_cache is not None else None
    )
    if lexical_facts is None:
        lexical_facts = _lexical_scope_names(scope)
        if lexical_cache is not None:
            lexical_cache[id(scope)] = lexical_facts
    lexical, globals_, nonlocals = lexical_facts
    if name not in lexical | globals_ | nonlocals:
        return target
    ordered = ordered_bindings
    if ordered is None:
        if ordered_cache is not None:
            ordered = ordered_cache.get(id(scope))
        if ordered is None:
            ordered = _ordered_bindings(scope)
            if ordered_cache is not None:
                ordered_cache[id(scope)] = ordered
    entries = _reaching_entries(
        (
            getattr(site, "lineno", 0) or 0,
            getattr(site, "col_offset", 0) or 0,
        ),
        name,
        ordered,
    )
    if not entries:
        # A global declaration does not itself replace the module helper; a
        # later global assignment must not leak backward to an earlier call.
        return target if name not in lexical else None
    if len(entries) != 1 or entries[0][1]:
        return None
    key = entries[0][2]
    live_local = _local_callable_at_binding(
        scope, name, entries[0][0], key
    )
    if live_local is not None:
        return live_local
    # ``_local_scopes`` maps a recognized ``partial(name, ...)`` binding to
    # its deferred target.  Retain that existing spelling only while the
    # reaching definition is still itself a definite partial call.
    try:
        value = ast.parse(key, mode="eval").body
    except (SyntaxError, ValueError, MemoryError):
        return None
    callee = _callee_root(value) if isinstance(value, ast.Call) else None
    if callee and callee.split(".")[-1] in _DEFERS_ARGUMENT:
        partial_bindings = 0
        for _position, conditional, candidate_key, _refs in ordered.get(
            name, ()
        ):
            try:
                candidate = ast.parse(candidate_key, mode="eval").body
            except (SyntaxError, ValueError, MemoryError):
                continue
            candidate_callee = (
                _callee_root(candidate)
                if isinstance(candidate, ast.Call)
                else None
            )
            if (
                not conditional
                and candidate_callee
                and candidate_callee.split(".")[-1] in _DEFERS_ARGUMENT
            ):
                partial_bindings += 1
        if partial_bindings != 1:
            return None
        return target
    return None


def _executed_scopes(
    func,
    module_scopes: dict[str, ast.AST],
    caches: tuple[dict, dict] | None = None,
    roots: tuple[str, ...] | None = None,
    root_sites: tuple[tuple[ast.AST, str], ...] | None = None,
    local_scopes: dict[str, ast.AST] | None = None,
    edge_entries: dict[int, list[tuple[ast.AST, ast.AST]]] | None = None,
) -> list:
    """The unit, plus every same-file scope it actually reaches.

    This is what makes `UnitSide.assertions` mean *the assertions this test
    runs* rather than *the assert statements written inside it*. Both halves
    matter: an assertion in an uninvoked nested `def` stops counting, and an
    assertion in a helper the unit calls starts.

    With `roots`, the walk starts from those invocation names instead of
    everything the unit invokes: the closure reachable through one entry
    site. The union over a unit's entry roots equals the default walk. The
    finite same-file callable graph is bounded by ``seen`` rather than an
    arbitrary depth cutoff, which also terminates recursive helper cycles.
    """
    scopes = (
        local_scopes
        if local_scopes is not None
        else _local_scopes(func, module_scopes)
    )
    nodes_cache = caches[0] if caches is not None else None
    module_scope_ids = {id(target) for target in module_scopes.values()}
    ordered_cache: dict[int, dict] = {}
    lexical_cache: dict[int, tuple[set[str], set[str], set[str]]] = {}

    def entered_names(scope: ast.AST) -> set[str | None]:
        return {
            _callee_root(item.context_expr)
            for node in _scope_nodes_cached(scope, nodes_cache)
            if isinstance(node, (ast.With, ast.AsyncWith))
            for item in node.items
        }

    out = [func]
    seen: set[int] = {id(func)}
    wanted = set(roots) if roots is not None else None
    entry_sites = (
        root_sites
        if root_sites is not None
        else tuple(_helper_entry_sites(func, nodes_cache))
    )
    frontier = [
        (func, site, name, scopes)
        for site, name in entry_sites
        if wanted is None or name in wanted
    ]
    while frontier:
        parent, site, name, visible = frontier.pop()
        target = _live_scope_target(
            parent,
            site,
            name,
            visible,
            ordered_cache,
            lexical_cache=lexical_cache,
        )
        if target is None:
            continue
        # A @contextmanager runs its body only when entered: building the
        # generator and never using `with` runs nothing (tamper 004).
        if _is_contextmanager(target) and name not in entered_names(parent):
            continue
        if edge_entries is not None:
            edge_entries.setdefault(id(target), []).append((parent, site))
        if id(target) in seen:
            continue
        seen.add(id(target))
        out.append(target)
        target_entry_sites = tuple(
            _helper_entry_sites(target, nodes_cache)
        )
        if not target_entry_sites and not isinstance(target, ast.ClassDef):
            continue
        inherited = (
            module_scopes if id(target) in module_scope_ids else visible
        )
        target_scopes = _local_scopes(target, inherited)
        if isinstance(target, ast.ClassDef):
            for child in target.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    seen.add(id(child))
                    if edge_entries is not None:
                        edge_entries.setdefault(id(child), []).append(
                            (parent, site)
                        )
                    out.append(child)
                    child_scopes = _local_scopes(child, module_scopes)
                    frontier.extend(
                        (child, child_site, child_name, child_scopes)
                        for child_site, child_name in _helper_entry_sites(
                            child, nodes_cache
                        )
                    )
        frontier.extend(
            (target, child_site, child_name, target_scopes)
            for child_site, child_name in target_entry_sites
        )
    return out


def _helper_entry_sites(func, nodes_cache) -> list[tuple[ast.AST, str]]:
    """(position node, invocation name) for every unit-level entry into a
    same-file helper, in source order.

    Mirrors `_invocations` node for node — a plain call, a `with` item's
    context expression, a `for` iterator, and a bare-`Name` argument to an
    `_INVOKES_ARGUMENT` call — but keeps *where* each entry happens instead
    of collapsing to a name set. The position node is what the inherited
    assertions' reaching keys are computed at: that is when the helper's
    oracle executes relative to the unit's own bindings (issue #55).
    """
    sites: list[tuple[ast.AST, str]] = []
    for node in _scope_nodes_cached(func, nodes_cache):
        if isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                name = _callee_root(item.context_expr)
                if name:
                    sites.append((item.context_expr, name))
        elif isinstance(node, ast.For):
            name = _callee_root(node.iter)
            if name:
                sites.append((node.iter, name))
        elif isinstance(node, ast.Call):
            name = _callee_root(node)
            if not name:
                continue
            sites.append((node, name))
            if name.split(".")[-1] in _INVOKES_ARGUMENT:
                sites.extend((node, a.id) for a in node.args if isinstance(a, ast.Name))
    sites.sort(key=lambda s: (s[0].lineno, s[0].col_offset))
    return sites


def _vacuous_bound_asserts(func: ast.AST) -> set[int]:
    """Ids of `assert data == <literal>` where `data` was bound to the same
    literal earlier in the same statement list and nothing between touches it.

    The subject is a bare Name, so `_is_trivial_subject` calls it state — yet
    straight-line locally the assertion cannot fail. That spelling counted as
    full oracle mass for D4/D5 and excused a deleted failing test through
    RESTRUCTURED: the bare-dialect member of the padding family (rows
    20/25/46), reproduced as a silent pass in the 2026-08-19 audit.

    Deliberately narrow: same statement list only (an outer binding is
    invisible to an inner block, failing toward real, not vacuous), both
    operand orders accepted, and ANY mention of the name between binding and
    assert disqualifies — `data = [1, 2, 3]; process(data);
    assert data == [1, 2, 3]` is a genuine oracle over `process`, not
    padding.
    """
    out: set[int] = set()

    def _nameless(node: ast.AST) -> bool:
        return not any(isinstance(n, ast.Name) for n in ast.walk(node))

    for holder in ast.walk(func):
        body = getattr(holder, "body", None)
        if not isinstance(body, list):
            continue
        bound: dict[str, ast.expr] = {}
        for stmt in body:
            if (
                isinstance(stmt, ast.Assign)
                and len(stmt.targets) == 1
                and isinstance(stmt.targets[0], ast.Name)
                and _nameless(stmt.value)
            ):
                bound[stmt.targets[0].id] = stmt.value
                continue
            if isinstance(stmt, ast.Assert) and id(stmt) not in out:
                t = stmt.test
                if (
                    isinstance(t, ast.Compare)
                    and len(t.ops) == 1
                    and isinstance(t.ops[0], ast.Eq)
                    and t.comparators
                ):
                    pair = None
                    if isinstance(t.left, ast.Name) and _nameless(t.comparators[0]):
                        pair = (t.left, t.comparators[0])
                    elif isinstance(t.comparators[0], ast.Name) and _nameless(t.left):
                        pair = (t.comparators[0], t.left)
                    if pair is not None:
                        subject, expect = pair
                        hit = bound.get(subject.id)
                        if hit is not None and ast.dump(hit) == ast.dump(expect):
                            out.add(id(stmt))
            mentions = {n.id for n in ast.walk(stmt) if isinstance(n, ast.Name)}
            for name in list(bound):
                if name in mentions:
                    del bound[name]
    return out


def _collect_unit(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    qualname: str,
    text: str,
    off: _Offsets,
    inherited_markers: list[Marker] | None = None,
    module_scopes: dict[str, ast.AST] | None = None,
    caches: tuple[dict, dict] | None = None,
    import_bindings: dict[str, str] | None = None,
    module_import_origins: tuple[
        tuple[str, str, str, int, int], ...
    ] = (),
    fixture_uses: tuple[str, ...] = (),
    parametrize_providers: dict[str, bool] | None = None,
    collect_standins: bool = True,
    module_standin_bindings: dict[str, str] | None = None,
    definition_imports: dict[str, str] | None = None,
    definition_import_maps: dict[int, dict[str, str]] | None = None,
    module_monkeypatch_receivers: frozenset[str] = frozenset(),
    module_api_values: Mapping[str, str] | None = None,
    module_api_definition_values: Mapping[int, Mapping[str, str]] | None = None,
    transparent_fixture_receivers: frozenset[str] = frozenset(),
    fixture_layers: tuple[
        tuple[str, dict[str, tuple[str, ...]], tuple[str, ...]], ...
    ] = (),
) -> ParsedUnit:
    assertions: list[Assertion] = []
    calls: set[str] = set()
    patches: set[tuple[str, str]] = set()
    body = text.seg(func) or ""
    markers = _decorator_markers(func, text, off) + list(inherited_markers or [])
    handlers: list[Handler] = []
    counter = 0
    dead = _unreachable_ids(func)
    guards = _skip_call_guards(func, text)
    _unparse_memo: dict[int, str] = {}
    _refs_memo: dict[int, tuple[str, ...]] = {}
    _flags: dict[str, bool] = {}
    definition_bindings, bindings = _binding_maps(
        func, unparse_memo=_unparse_memo, refs_memo=_refs_memo, flags=_flags
    )
    ordered_bindings = (
        _ordered_bindings(
            func,
            unparse_memo=_unparse_memo,
            refs_memo=_refs_memo,
            has_walrus=_flags.get("walrus", False),
        )
        if definition_bindings or _flags.get("named_scope", False)
        else {}
    )
    vacuous = _vacuous_bound_asserts(func)

    # Markers, handlers, calls and patches stay keyed to the unit's own body: a
    # helper's assertions are this unit's oracle, a helper's `except` is not
    # this unit's handler. Only the assertion set follows reachability.
    nodes_cache = caches[0] if caches is not None else None
    lexical_facts = _lexical_scope_names(func)
    invoked_names = _invocations(func, caches)
    # Most tests call production imports and no same-file helper.  Building
    # the callable index and walking the helper closure in that case only
    # re-traverses the unit AST: a local helper can be reachable only through
    # a name that is either module-visible or lexically bound in this scope.
    may_reach_local_scope = bool(invoked_names) and (
        not invoked_names.isdisjoint(module_scopes or {})
        or not invoked_names.isdisjoint(lexical_facts[0])
    )
    if may_reach_local_scope:
        local_scopes = _local_scopes(
            func,
            module_scopes or {},
            lexical_facts,
        )
        executed = _executed_scopes(
            func,
            module_scopes or {},
            caches=caches,
            local_scopes=local_scopes,
        )
    else:
        local_scopes = {}
        executed = [func]
    direct_scope_ids = {
        id(node) for node in _scope_nodes_cached(func, nodes_cache)
    }
    reached_asserts = {
        id(n)
        for scope in executed
        for n in _scope_nodes_cached(scope, nodes_cache)
        if isinstance(n, ast.Assert)
    }
    # Asserts collected by this walk, so the executed-scopes pass below does
    # not add them a second time: an invoked *nested* def is both lexically
    # inside `func` (this walk sees it) and an executed scope (that loop sees
    # it), and double-counting an oracle invents an assertion to "remove".
    own_assert_ids: set[int] = set()
    # A consumer can be reached by a stand-in installed in conftest even when
    # this file installs nothing itself. Preserve function-local import aliases
    # for that reachability check. The lexical guard avoids an extra scope walk
    # for the overwhelmingly common no-local-import unit without making the
    # stand-in-install prefilter a reachability boundary.
    if (
        collect_standins
        or not lexical_facts[0].isdisjoint(import_bindings or {})
        or _scope_needs_import_environments(
            func, body, import_bindings or {}
        )
    ):
        import_environments, imported = _scope_import_environments(
            func,
            import_bindings or {},
            definition_base=definition_imports,
        )
    else:
        # A raw-source proof says this scope neither imports nor shadows a
        # module binding. Reuse the module environment directly and avoid a
        # per-test control-flow walk. Empty remains a known-empty map; it is
        # not permission to borrow bindings back from the file later.
        import_environments = {}
        imported = {
            name: target
            for name, target in sorted((import_bindings or {}).items())
        }
    runtime_import_environments = (
        _scope_runtime_import_environments(
            func, imported, import_environments
        )
        if re.search(
            r"\b(?:from|import)\b|\bimport_module\b|\bsys\s*\.\s*modules\b",
            body,
        )
        else {}
    )

    def oracle_import_metadata(node: ast.AST):
        exact = _imports_at(node, imported, import_environments)
        runtime = runtime_import_environments.get(id(node), ())
        module = _visible_module_import_origins(
            module_import_origins,
            exact,
            runtime,
        )
        return exact, runtime, module

    params = tuple(
        argument.arg
        for argument in (
            func.args.posonlyargs + func.args.args + func.args.kwonlyargs
        )
        if argument.arg not in ("self", "cls")
    )
    decorator_imports = definition_imports or import_bindings or {}
    default_providers = _parameter_default_providers(
        func, definition_imports or {}
    )
    direct_parametrize = _direct_parametrize_names(
        func, decorator_imports, parametrize_providers
    )
    requested_fixtures = (
        (set(params) - direct_parametrize - set(default_providers))
        | set(fixture_uses)
    )
    if collect_standins:
        receiver_bindings = {
            name: value
            for name, value in (module_standin_bindings or {}).items()
            if name not in transparent_fixture_receivers
        }
        immediate_patch_receivers = _mocker_fixture_receivers(
            func, requested_fixtures, receiver_bindings
        )
        lexical_scope_names = lexical_facts[0]
        monkeypatch_receivers = _pytest_fixture_receivers(
            func,
            requested_fixtures,
            "monkeypatch",
            receiver_bindings,
        ) | frozenset(
            name
            for name in module_monkeypatch_receivers
            if name not in lexical_scope_names
        )
        api_facts = _standin_api_facts(
            func,
            imported,
            import_environments,
            monkeypatch_receivers=monkeypatch_receivers,
            mocker_receivers=immediate_patch_receivers,
            inherited_values=module_api_values,
            definition_time_values=(
                (module_api_definition_values or {}).get(
                    id(func), module_api_values or {}
                )
            ),
        )
    else:
        immediate_patch_receivers = frozenset()
        api_facts = _StandinApiFacts()
    standin_nodes: list[ast.AST] = []

    for node in ast.walk(func):
        if id(node) in dead:
            continue
        if (
            collect_standins
            and id(node) in direct_scope_ids
            and isinstance(
                node, (ast.Assign, ast.AnnAssign, ast.NamedExpr, ast.Call)
            )
        ):
            standin_nodes.append(node)
        # An assert written inside a nested `def` that nothing calls is present
        # in the source and absent from the run. Counting it as live is what
        # let `verify()` be defined and never invoked (tamper 020) — and it is
        # older than that attack.
        if isinstance(node, ast.Assert) and id(node) not in reached_asserts:
            continue
        if isinstance(node, ast.Assert):
            own_assert_ids.add(id(node))
            c = _classify_assert(node, text)
            seg = text.seg(node) or ""
            depends = _resolve_through(c.right_names, bindings)
            direct = set(c.left_names) | set(c.right_names)
            reach = _reaching_keys(
                node,
                _positional_closure(node, c.left_names + c.right_names, ordered_bindings),
                ordered_bindings,
            )
            oracle_imports, oracle_runtime_imports, oracle_module_imports = (
                oracle_import_metadata(node)
            )
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
                    trivial=_is_trivial_subject(node.test) or id(node) in vacuous,
                    positive=c.positive,
                    left_names=c.left_names,
                    right_depends_on=depends,
                    reaching=reach,
                    reaching_sig=_reaching_sig(reach, direct),
                    standin_imports=oracle_imports,
                    standin_runtime_imports=oracle_runtime_imports,
                    standin_module_imports=oracle_module_imports,
                    standin_position=(
                        (
                            getattr(node, "lineno", 0) or 0,
                            getattr(node, "col_offset", 0) or 0,
                        )
                        if id(node) in direct_scope_ids
                        else None
                    ),
                    standin_oracle_key=_standin_oracle_key(
                        node,
                        c,
                        oracle_imports,
                    ),
                )
            )
            counter += 1
        elif isinstance(node, ast.Call):
            name = _dotted(node.func)
            if name:
                calls.add(name)
                calls.add(name.rsplit(".", 1)[-1])
                # Preserve the exact IR-v1/local-spelling patch census.  The
                # richer stand-in lifetime pass below is intentionally a
                # separate internal channel.
                pair = _patch_call_target(node, name)
                if pair is not None:
                    patches.add(pair)
                if name in _SKIP_CALLS:
                    seg = text.seg(node) or name
                    markers.append(
                        Marker(name=name, text=seg, span=off.span(node), guard=guards.get(id(node)))
                    )
                if name in ("pytest.raises", "pytest.warns", "raises"):
                    # `pytest.raises(E, match=...)` IS an oracle: triage found
                    # human commits folding an excinfo substring assert into
                    # match= and getting blocked for "removing" it.
                    match_kw = next((kw for kw in node.keywords if kw.arg == "match"), None)
                    seg = text.seg(node) or name
                    (
                        oracle_imports,
                        oracle_runtime_imports,
                        oracle_module_imports,
                    ) = oracle_import_metadata(node)
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
                            standin_imports=oracle_imports,
                            standin_runtime_imports=oracle_runtime_imports,
                            standin_module_imports=oracle_module_imports,
                            standin_position=(
                                (
                                    getattr(node, "lineno", 0) or 0,
                                    getattr(node, "col_offset", 0) or 0,
                                )
                                if id(node) in direct_scope_ids
                                else None
                            ),
                        )
                    )
                    counter += 1
            c = _classify_unittest_call(node, text)
            if c is not None:
                seg = text.seg(node) or ""
                depends = _resolve_through(c.right_names, bindings)
                direct = set(c.left_names) | set(c.right_names)
                reach = _reaching_keys(
                    node,
                    _positional_closure(
                        node, c.left_names + c.right_names, ordered_bindings
                    ),
                    ordered_bindings,
                )
                (
                    oracle_imports,
                    oracle_runtime_imports,
                    oracle_module_imports,
                ) = oracle_import_metadata(node)
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
                        left_names=c.left_names,
                        right_depends_on=depends,
                        trivial=c.trivial,
                        reaching=reach,
                        reaching_sig=_reaching_sig(reach, direct),
                        standin_imports=oracle_imports,
                        standin_runtime_imports=oracle_runtime_imports,
                        standin_module_imports=oracle_module_imports,
                        standin_position=(
                            (
                                getattr(node, "lineno", 0) or 0,
                                getattr(node, "col_offset", 0) or 0,
                            )
                            if id(node) in direct_scope_ids
                            else None
                        ),
                        standin_oracle_key=_standin_oracle_key(
                            node,
                            c,
                            oracle_imports,
                        ),
                    )
                )
                counter += 1
        elif isinstance(node, ast.ExceptHandler):
            caught, is_broad = _handler_info(node)
            seg = text.seg(node) or ""
            handlers.append(
                Handler(caught=caught, is_broad=is_broad, text=seg.split("\n")[0], span=off.span(node))
            )

    raw_installs = [
        (node, install)
        for node in standin_nodes
        for install in _standin_install_targets(
            node,
            _imports_at(node, imported, import_environments),
            api_facts,
        )
    ]
    effective_installs: list[StandinInstall] = []
    if raw_installs:
        patch_contexts = {
            **_standin_patch_contexts(func),
            **api_facts.call_contexts,
        }
        patch_activations = _standin_patch_activations(
            func,
            patch_contexts,
            imported,
            import_environments,
            immediate_receivers=immediate_patch_receivers,
            api_facts=api_facts,
        )
        direct_restore_boundaries = _straight_line_restores(
            func,
            imported,
            scope="test",
            dead=dead,
            environments=import_environments,
            api_facts=api_facts,
        )
        for node, (target, attr, kind) in raw_installs:
            if (
                _patch_call_is_operative(
                    node,
                    patch_activations,
                    imported,
                    import_environments,
                    immediate_patch_receivers,
                    api_facts,
                )
                and _context_install_is_live(
                    node,
                    (target, attr, kind),
                    patch_contexts,
                    patch_activations,
                    imported,
                    scope="test",
                    text=text,
                    bindings=definition_bindings,
                    dead=dead,
                    environments=import_environments,
                )
                # A test-body sys.modules swap is operative only when a
                # literal runtime import happens after it. A top-level import
                # already captured the old module object.
                and (
                    kind != "module"
                    or _module_reimported_after(
                        func,
                        node,
                        target,
                        imported,
                        import_environments,
                    )
                )
            ):
                effective_installs.append(
                    _standin_record(
                        node,
                        (target, attr, kind),
                        text,
                        scope="test",
                        active_until=(
                            direct_restore_boundaries.get(id(node))
                            or (
                                (
                                    getattr(
                                        patch_contexts[id(node)],
                                        "end_lineno",
                                        0,
                                    )
                                    or 0,
                                    getattr(
                                        patch_contexts[id(node)],
                                        "end_col_offset",
                                        0,
                                    )
                                    or 0,
                                )
                                if id(node) in patch_contexts
                                else None
                            )
                        ),
                        api_fixture_receiver=(
                            api_facts.call_fixture_receivers.get(id(node))
                        ),
                    )
                )

    # The other half: assertions the unit runs that are not written inside it.
    # `assert_sum(add(2, 3), 5)` is a *call*, so without this the unit records
    # zero assertions, nothing can be removed or weakened, and a replacement
    # `assert callable(assert_sum)` reads as an assertion *added* — by the
    # strength lattice the test got stronger (THREATMODEL 91).
    #
    # Inherited once per unit-level entry site, not once per helper: each
    # copy carries the reaching keys of its own call's position, so a pure
    # insertion of one more case leaves every other site's copy identical
    # (issue #55, sympy aa1b43c3 — the R1 residual), while rebinding a
    # forwarded name between its honest definition and the call still
    # changes what that site's copy reads. The span stays the helper-side
    # assert — one edited helper line keeps collapsing to one finding
    # downstream — so a site's copies differ by `reaching_sig` alone, and
    # deleting one of N calls surfaces as a removed assertion instead of
    # vanishing into a same-size set.
    lexical_parents: dict[int, ast.FunctionDef | ast.AsyncFunctionDef] = {}

    def map_nested_scopes(
        node: ast.AST,
        parent: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                lexical_parents.setdefault(id(child), parent)
                map_nested_scopes(child, child)
            elif not isinstance(child, (ast.ClassDef, ast.Lambda)):
                map_nested_scopes(child, parent)

    if collect_standins and len(executed) > 1:
        for root_scope in {
            id(scope): scope
            for scope in executed
            if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef))
        }.values():
            map_nested_scopes(root_scope, root_scope)

    def helper_base_imports(
        scope: ast.FunctionDef | ast.AsyncFunctionDef,
        unit_site: ast.AST,
    ) -> dict[str, str]:
        """Live closure imports where a nested helper is invoked."""
        parent = lexical_parents.get(id(scope))
        if parent is None:
            return dict(import_bindings or {})
        if parent is func:
            parent_environments, parent_imports = (
                import_environments,
                imported,
            )
        else:
            parent_environments, parent_imports = _scope_import_environments(
                parent,
                helper_base_imports(parent, unit_site),
            )
        parent_dead = _unreachable_ids(parent)
        sites = [
            node
            for node, root in _helper_entry_sites(parent, nodes_cache)
            if root == scope.name and id(node) not in parent_dead
        ]
        if not sites:
            # A scope-name collision or an unresolved dynamic invocation is
            # not positive import provenance.
            return {}
        environments = [
            _imports_at(node, parent_imports, parent_environments)
            for node in sites
        ]
        return {
            name: target
            for name, target in environments[0].items()
            if all(other.get(name) == target for other in environments[1:])
        }

    root_closures: dict[
        tuple[int, int],
        tuple[list, dict[int, list[tuple[ast.AST, ast.AST]]]],
    ] = {}
    live_scope_lexical_cache: dict[
        int, tuple[set[str], set[str], set[str]]
    ] = {}
    inherited_rows: dict[int, list] = {}
    helper_oracle_import_cache: dict[
        tuple[int, tuple[tuple[str, str], ...]],
        tuple[
            dict[int, dict[str, str]],
            dict[str, str],
            dict[int, tuple[tuple[str, str, str, int, int], ...]],
        ],
    ] = {}
    helper_install_rows: dict[
        tuple,
        tuple[
            tuple[
                ast.AST,
                tuple[str, str, str],
                bool,
                bool,
                tuple[tuple[int, int], ...],
                str | None,
            ],
            ...,
        ],
    ] = {}
    helper_install_facts: dict[tuple, _StandinApiFacts] = {}

    def helper_oracle_import_metadata(
        scope: ast.FunctionDef | ast.AsyncFunctionDef,
        oracle: ast.AST,
        unit_site: ast.AST,
    ):
        """Definition provenance for an oracle projected to a call site."""
        base_imports = helper_base_imports(scope, unit_site)
        cache_key = (id(scope), tuple(sorted(base_imports.items())))
        cached = helper_oracle_import_cache.get(cache_key)
        if cached is None:
            helper_environments, helper_imports = (
                _scope_import_environments(
                    scope,
                    base_imports,
                    definition_base=(definition_import_maps or {}).get(
                        id(scope), base_imports
                    ),
                )
            )
            helper_runtime_imports = _scope_runtime_import_environments(
                scope,
                helper_imports,
                helper_environments,
            )
            cached = (
                helper_environments,
                helper_imports,
                helper_runtime_imports,
            )
            helper_oracle_import_cache[cache_key] = cached
        helper_environments, helper_imports, helper_runtime_imports = cached
        exact_imports = _imports_at(
            oracle,
            helper_imports,
            helper_environments,
        )
        runtime_imports = helper_runtime_imports.get(id(oracle), ())
        module_imports = _visible_module_import_origins(
            module_import_origins,
            exact_imports,
            runtime_imports,
        )
        return exact_imports, runtime_imports, module_imports

    def helper_call_parameter_values(
        scope: ast.FunctionDef | ast.AsyncFunctionDef,
        site_node: ast.AST,
        caller_facts: _StandinApiFacts,
    ) -> dict[str, str | None]:
        """Exact API/fixture values explicitly forwarded to one helper call.

        Unknown explicit values are retained as ``None`` so they suppress a
        default API origin. Starred arguments cannot be paired soundly; they
        conservatively invalidate every parameter they may fill.
        """
        if (
            not isinstance(site_node, ast.Call)
            or _callee_root(site_node) != scope.name
        ):
            return {}
        origins = caller_facts.call_argument_origins.get(id(site_node))
        if origins is None:
            return {}
        positional_origins, keyword_origins = origins
        positional_parameters = scope.args.posonlyargs + scope.args.args
        keyword_parameters = {
            argument.arg
            for argument in (*scope.args.args, *scope.args.kwonlyargs)
        }
        values: dict[str, str | None] = {}
        position = 0
        for argument, origin in zip(site_node.args, positional_origins):
            if isinstance(argument, ast.Starred):
                for parameter in positional_parameters[position:]:
                    values[parameter.arg] = None
                position = len(positional_parameters)
                continue
            if position < len(positional_parameters):
                values[positional_parameters[position].arg] = origin
                position += 1
        for (name, origin), keyword in zip(
            keyword_origins, site_node.keywords
        ):
            if name is None or keyword.arg is None:
                for parameter in keyword_parameters:
                    values.setdefault(parameter, None)
            elif name in keyword_parameters:
                values[name] = origin
        return values

    def helper_runtime_overrides(
        scope: ast.FunctionDef | ast.AsyncFunctionDef,
        site_node: ast.AST,
        caller_scope: ast.AST,
        caller_facts: _StandinApiFacts,
    ) -> dict[str, str | None]:
        """Exact explicit arguments plus live lexical closure values."""
        values = helper_call_parameter_values(
            scope, site_node, caller_facts
        )
        if lexical_parents.get(id(scope)) is not caller_scope:
            return values
        live = caller_facts.call_value_environments.get(id(site_node))
        caller_locals = _lexical_scope_names(caller_scope)[0]
        scope_locals, scope_globals, _scope_nonlocals = (
            _lexical_scope_names(scope)
        )
        referenced = {
            node.id
            for node in _scope_nodes_cached(scope, nodes_cache)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
        }
        closed_names = (
            caller_locals & referenced
        ) - scope_locals - scope_globals
        for name in closed_names:
            # Absence is meaningful: an unknown outer-local value must shadow
            # a same-named real module API rather than borrowing it back.
            values.setdefault(name, (live or {}).get(name))
        return values

    def invoked_helper_installs(
        scope: ast.FunctionDef | ast.AsyncFunctionDef,
        site_node: ast.AST,
        caller_scope: ast.AST,
        caller_facts: _StandinApiFacts,
    ) -> tuple[tuple, _StandinApiFacts, tuple]:
        """Operative installs in one helper, projected later to its call site.

        A helper has its own lexical imports, patch lifetimes and restoration
        boundary.  Reusing the test root's environment/context would accept a
        shadowed alias and miss ``patch(...).start()`` inside the helper.  The
        result is cached by scope plus enclosing live import environment; only
        the cheap call-site projection varies between invocations.
        """
        base_imports = helper_base_imports(scope, site_node)
        runtime_overrides = helper_runtime_overrides(
            scope, site_node, caller_scope, caller_facts
        )
        lexical_child = lexical_parents.get(id(scope)) is caller_scope
        definition_values = (
            caller_facts.definition_values.get(id(scope), {})
            if lexical_child
            else None
        )
        if not lexical_child:
            definition_values = (
                (module_api_definition_values or {}).get(
                    id(scope), module_api_values or {}
                )
            )
        cache_key = (
            id(scope),
            tuple(sorted(base_imports.items())),
            tuple(
                sorted(
                    (name, origin or "<unknown>")
                    for name, origin in runtime_overrides.items()
                )
            ),
            tuple(sorted(definition_values.items())),
        )
        cached = helper_install_rows.get(cache_key)
        if cached is not None:
            return cached, helper_install_facts[cache_key], cache_key

        helper_environments, helper_imports = _scope_import_environments(
            scope,
            base_imports,
            definition_base=(definition_import_maps or {}).get(
                id(scope), base_imports
            ),
        )
        helper_dead = _unreachable_ids(scope)
        helper_nodes = tuple(_scope_nodes_cached(scope, nodes_cache))
        helper_api_facts = _standin_api_facts(
            scope,
            helper_imports,
            helper_environments,
            monkeypatch_receivers=frozenset(
                name
                for name in module_monkeypatch_receivers
                if name not in _lexical_scope_names(scope)[0]
            ),
            inherited_values=module_api_values,
            definition_time_values=definition_values,
            parameter_values=runtime_overrides,
        )
        helper_install_facts[cache_key] = helper_api_facts
        candidates = [
            (node, install)
            for node in helper_nodes
            if isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr, ast.Call))
            and id(node) not in helper_dead
            for install in _standin_install_targets(
                node,
                _imports_at(node, helper_imports, helper_environments),
                helper_api_facts,
            )
        ]
        if not candidates:
            helper_install_rows[cache_key] = ()
            return (), helper_api_facts, cache_key

        contexts = {
            **_standin_patch_contexts(scope),
            **helper_api_facts.call_contexts,
        }
        activations = _standin_patch_activations(
            scope,
            contexts,
            helper_imports,
            helper_environments,
            api_facts=helper_api_facts,
        )
        restored = _straight_line_restores(
            scope,
            helper_imports,
            scope="test",
            dead=helper_dead,
            environments=helper_environments,
            api_facts=helper_api_facts,
        )
        helper_bindings = _binding_definitions(scope)
        global_names = {
            name
            for node in helper_nodes
            if isinstance(node, ast.Global)
            for name in node.names
        }

        oracle_nodes = [
            node
            for node in helper_nodes
            if isinstance(node, ast.Assert)
            or (
                isinstance(node, ast.Call)
                and _classify_unittest_call(node, text) is not None
            )
        ]

        def invoked_oracle_nodes(
            entry_sites: tuple[tuple[ast.AST, str], ...] | None,
        ) -> tuple[ast.AST, ...]:
            """Oracles in helpers entered while this lifecycle is active."""
            closure = _executed_scopes(
                scope,
                module_scopes or {},
                caches=caches,
                root_sites=entry_sites,
            )
            return tuple(
                node
                for reached_scope in closure[1:]
                for node in _scope_nodes_cached(reached_scope, nodes_cache)
                if isinstance(node, ast.Assert)
                or (
                    isinstance(node, ast.Call)
                    and _classify_unittest_call(node, text) is not None
                )
            )

        def oracle_spans_for(
            install_node: ast.AST,
        ) -> tuple[bool, tuple[tuple[int, int], ...]]:
            lifecycle = activations.get(id(install_node))
            if lifecycle == "decorator":
                eligible = [
                    *oracle_nodes,
                    *invoked_oracle_nodes(None),
                ]
                persists = False
            elif lifecycle == "context":
                context = contexts.get(id(install_node))
                inside = (
                    {
                        id(candidate)
                        for candidate in _standin_scope_nodes(
                            _scope_body_nodes(context.body)
                        )
                    }
                    if context is not None
                    else set()
                )
                direct_eligible = [
                    oracle for oracle in oracle_nodes if id(oracle) in inside
                ]
                entry_sites = tuple(
                    (node, root)
                    for node, root in _helper_entry_sites(scope, nodes_cache)
                    if id(node) in inside
                )
                eligible = [
                    *direct_eligible,
                    *invoked_oracle_nodes(entry_sites),
                ]
                persists = False
            else:
                end = (
                    getattr(install_node, "end_lineno", 0) or 0,
                    getattr(install_node, "end_col_offset", 0) or 0,
                )
                restore_boundary = restored.get(id(install_node))
                eligible = [
                    oracle
                    for oracle in oracle_nodes
                    if (
                        getattr(oracle, "lineno", 0) or 0,
                        getattr(oracle, "col_offset", 0) or 0,
                    )
                    > end
                    and (
                        id(install_node) not in restored
                        or (
                            getattr(oracle, "lineno", 0) or 0,
                            getattr(oracle, "col_offset", 0) or 0,
                        )
                        < restored[id(install_node)]
                    )
                ]
                entry_sites = tuple(
                    (node, root)
                    for node, root in _helper_entry_sites(scope, nodes_cache)
                    if (
                        getattr(node, "lineno", 0) or 0,
                        getattr(node, "col_offset", 0) or 0,
                    )
                    > end
                    and (
                        restore_boundary is None
                        or (
                            getattr(node, "lineno", 0) or 0,
                            getattr(node, "col_offset", 0) or 0,
                        )
                        < restore_boundary
                    )
                )
                if entry_sites:
                    eligible.extend(invoked_oracle_nodes(entry_sites))
                persists = id(install_node) not in restored
            return persists, tuple(
                sorted({off.span(oracle) for oracle in eligible})
            )

        oracle_lifetimes = {
            id(node): oracle_spans_for(node) for node, _install in candidates
        }
        kept = tuple(
            (
                node,
                install,
                install[2] == "module"
                and _module_reimported_after(
                    scope,
                    node,
                    install[0],
                    helper_imports,
                    helper_environments,
                ),
                *oracle_lifetimes[id(node)],
                helper_api_facts.call_fixture_receivers.get(id(node)),
            )
            for node, install in candidates
            if (install[2] != "binding" or install[1] in global_names)
            and _patch_call_is_operative(
                node,
                activations,
                helper_imports,
                helper_environments,
                api_facts=helper_api_facts,
            )
            and (
                _context_install_is_live(
                    node,
                    install,
                    contexts,
                    activations,
                    helper_imports,
                    scope="test",
                    text=text,
                    bindings=helper_bindings,
                    dead=helper_dead,
                    environments=helper_environments,
                )
                or (
                    activations.get(id(node)) == "context"
                    and bool(oracle_lifetimes[id(node)][1])
                )
            )
        )
        helper_install_rows[cache_key] = kept
        return kept, helper_api_facts, cache_key

    helper_entry_sites = (
        _helper_entry_sites(func, nodes_cache) if local_scopes else ()
    )
    for site_node, root in helper_entry_sites:
        if id(site_node) in dead:
            continue
        if root not in local_scopes:
            continue
        live_target = _live_scope_target(
            func,
            site_node,
            root,
            local_scopes,
            ordered_bindings=ordered_bindings,
            lexical_cache=live_scope_lexical_cache,
        )
        if live_target is None:
            continue
        closure_key = (id(site_node), id(live_target))
        cached_closure = root_closures.get(closure_key)
        if cached_closure is None:
            edge_entries: dict[
                int, list[tuple[ast.AST, ast.AST]]
            ] = {}
            child_sites = tuple(
                _helper_entry_sites(live_target, nodes_cache)
            )
            if (
                not child_sites
                and not isinstance(live_target, ast.ClassDef)
                and not _is_contextmanager(live_target)
            ):
                # The target has no transitive fanout, so the expensive
                # per-root scope reconstruction cannot add anything.  This
                # keeps a unit calling many flat helpers linear. Classes
                # still need the general walk to expand their method scopes.
                closure = [func, live_target]
                edge_entries[id(live_target)] = [(func, site_node)]
            else:
                closure = _executed_scopes(
                    func,
                    module_scopes or {},
                    caches=caches,
                    roots=(root,),
                    root_sites=((site_node, root),),
                    edge_entries=edge_entries,
                )
            cached_closure = (closure, edge_entries)
            root_closures[closure_key] = cached_closure
        closure, edge_entries = cached_closure
        scope_by_id = {id(scope): scope for scope in closure}
        outgoing_edges: dict[
            int, list[tuple[ast.AST, ast.AST]]
        ] = {}
        for target_id, incoming_edges in edge_entries.items():
            target_scope = scope_by_id.get(target_id)
            if target_scope is None or target_scope is func:
                continue
            for caller_scope, invocation_site in incoming_edges:
                if id(caller_scope) not in scope_by_id:
                    continue
                outgoing_edges.setdefault(id(caller_scope), []).append(
                    (target_scope, invocation_site)
                )
        for edges in outgoing_edges.values():
            edges.sort(
                key=lambda edge: (
                    getattr(edge[1], "lineno", 0) or 0,
                    getattr(edge[1], "col_offset", 0) or 0,
                    getattr(edge[0], "name", ""),
                )
            )

        # Expand each lexical AST only once above, but evaluate it once per
        # distinct incoming provenance state.  This preserves both real/fake
        # calls to the same helper while identical calls and recursive cycles
        # terminate on the helper analysis cache key.
        if collect_standins:
            analysis_queue: list[tuple[ast.AST, _StandinApiFacts]] = [
                (func, api_facts)
            ]
            seen_helper_states: set[tuple] = set()
            queue_index = 0
            while queue_index < len(analysis_queue):
                caller_scope, caller_facts = analysis_queue[queue_index]
                queue_index += 1
                for scope, invocation_site in outgoing_edges.get(
                    id(caller_scope), ()
                ):
                    if not isinstance(
                        scope, (ast.FunctionDef, ast.AsyncFunctionDef)
                    ):
                        continue
                    (
                        helper_rows,
                        helper_api_facts,
                        analysis_key,
                    ) = invoked_helper_installs(
                        scope,
                        invocation_site,
                        caller_scope,
                        caller_facts,
                    )
                    if analysis_key in seen_helper_states:
                        continue
                    seen_helper_states.add(analysis_key)
                    analysis_queue.append((scope, helper_api_facts))
                    for (
                        install_node,
                        install,
                        internally_reimported,
                        persists_after_owner,
                        owner_oracle_spans,
                        api_fixture_receiver,
                    ) in helper_rows:
                        if (
                            install[2] == "module"
                            and not internally_reimported
                            and not _module_reimported_after(
                                func,
                                site_node,
                                install[0],
                                imported,
                                import_environments,
                            )
                        ):
                            continue
                        effective_installs.append(
                            _standin_record(
                                install_node,
                                install,
                                text,
                                scope="test",
                                owner=getattr(scope, "name", None),
                                position_node=site_node,
                                persists_after_owner=persists_after_owner,
                                owner_oracle_spans=owner_oracle_spans,
                                api_fixture_receiver=api_fixture_receiver,
                            )
                        )
        for scope in closure:
            if scope is func:
                continue
            rows = inherited_rows.get(id(scope))
            if rows is None:
                rows = []
                for node in _scope_nodes_cached(scope, nodes_cache):
                    if isinstance(node, ast.Assert):
                        if id(node) in own_assert_ids:
                            continue
                        c = _classify_assert(node, text)
                        trivial = _is_trivial_subject(node.test) or id(node) in vacuous
                    elif isinstance(node, ast.Call):
                        c = _classify_unittest_call(node, text)
                        if c is None:
                            continue
                        trivial = c.trivial
                    else:
                        continue
                    rows.append((node, c, trivial))
                inherited_rows[id(scope)] = rows
            for node, c, trivial in rows:
                seg = text.seg(node) or ""
                direct = set(c.left_names) | set(c.right_names)
                reach = _reaching_keys(
                    site_node,
                    _positional_closure(
                        site_node, c.left_names + c.right_names, ordered_bindings
                    ),
                    ordered_bindings,
                )
                (
                    oracle_imports,
                    oracle_runtime_imports,
                    oracle_module_imports,
                ) = helper_oracle_import_metadata(
                    scope,
                    node,
                    site_node,
                )
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
                        trivial=trivial,
                        positive=c.positive,
                        left_names=c.left_names,
                        right_depends_on=c.right_names,
                        inherited=True,
                        reaching=reach,
                        reaching_sig=_reaching_sig(reach, direct),
                        standin_imports=oracle_imports,
                        standin_runtime_imports=oracle_runtime_imports,
                        standin_module_imports=oracle_module_imports,
                        standin_runtime_imports_projected=True,
                        standin_position=(
                            getattr(site_node, "lineno", 0) or 0,
                            getattr(site_node, "col_offset", 0) or 0,
                        ),
                        standin_oracle_key=_standin_oracle_key(
                            node,
                            c,
                            oracle_imports,
                        ),
                    )
                )
                counter += 1

    body_hash = hashlib.sha256(normalize_text(body).encode("utf-8")).hexdigest() if body else ""

    assertions.sort(key=lambda a: a.span)
    for i, a in enumerate(assertions):
        a.id = f"a{i}"

    param_columns = _param_columns(func, decorator_imports)
    parameter_providers = dict(default_providers)
    lexical_names = tuple(sorted(lexical_facts[0]))
    ambiguous_providers = set(default_providers) & direct_parametrize
    for name in ambiguous_providers:
        parameter_providers[name] = ("ambiguous", "")
    for name in direct_parametrize - ambiguous_providers:
        parameter_providers[name] = (
            "parametrize",
            param_columns.get(name, "<parametrize>"),
        )
    side = UnitSide(
        span=off.span(func),
        assertions=assertions,
        calls=tuple(sorted(calls)),
        markers=sorted(markers, key=lambda m: m.span),
        handlers=sorted(handlers, key=lambda h: h.span),
        param_cases=_param_case_count(func, decorator_imports),
        body_hash=body_hash,
        bindings=definition_bindings,
        # Exclusivity can only matter for a multiply-bound name. Most test
        # units bind each local once, so avoid another full statement walk
        # when the definition map already proves the result must be empty.
        exclusive_bindings=(
            _exclusive_bindings(func)
            if any("" in key for key in definition_bindings.values())
            else ()
        ),
        param_columns=param_columns,
        patches=tuple(sorted(patches)),
        standin_installs=tuple(
            sorted(
                effective_installs,
                key=lambda install: (
                    install.effect_identity,
                    install.finding_target,
                    install.text,
                ),
            )
        ),
        invoked=tuple(sorted(invoked_names)),
        params=params,
        fixtures=tuple(
            sorted(requested_fixtures)
        ),
        standin_imports=imported,
        standin_module_bindings=dict(module_standin_bindings or {}),
        standin_parameter_providers=parameter_providers,
        standin_lexical_names=lexical_names,
        standin_fixture_layers=fixture_layers,
    )
    return ParsedUnit(qualname=qualname, span=side.span, side=side, shingles=_shingles(func))


def _collection_controls(tree: ast.Module, text) -> list[tuple[ast.AST, str | None]]:
    """(statement, enclosing-`if` conjunction) for everything that puts a path
    into `collect_ignore`.

    Only the assignment form used to count, so the idiomatic spelling — set an
    empty list, then `extend` it, which is how attrs writes it — dropped whole
    test files silently (bypass 70). An *empty* assignment is an initialiser
    and not a control: recording it would make attrs' honest version gate look
    like an unconditional kill.
    """
    found: list[tuple[ast.AST, str | None]] = []

    def control(stmt: ast.stmt) -> ast.AST | None:
        def _targets_control(target) -> bool:
            # `collect_ignore[:] = [...]` and `collect_ignore[0] = ...` are
            # Subscript, not Name, so the whole slice form was invisible
            # (THREATMODEL 83).
            if isinstance(target, ast.Subscript):
                target = target.value
            return isinstance(target, ast.Name) and target.id in _CONFTEST_NAMES

        if isinstance(stmt, ast.Assign) and any(_targets_control(t) for t in stmt.targets):
            value = stmt.value
            if isinstance(value, (ast.List, ast.Tuple, ast.Set)) and not value.elts:
                return None
            return stmt
        if isinstance(stmt, ast.AugAssign) and _targets_control(stmt.target):
            return stmt
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            head, _, attr = (_dotted(stmt.value.func) or "").rpartition(".")
            if head in _CONFTEST_NAMES and attr in ("extend", "append", "insert"):
                return stmt
        return None

    def record(stmts: list[ast.stmt], conds: tuple[str, ...]) -> None:
        for stmt in stmts:
            if isinstance(stmt, ast.If):
                t = text.seg(stmt.test) or ""
                record(stmt.body, conds + ((t,) if t else ()))
                record(stmt.orelse, conds + ((f"not ({t})",) if t else ()))
                continue
            node = control(stmt)
            if node is not None:
                found.append((node, " and ".join(conds) if conds else None))
            for fname in _STMT_BODY_FIELDS:
                sub = getattr(stmt, fname, None)
                if isinstance(sub, list) and any(isinstance(s, ast.stmt) for s in sub):
                    record([s for s in sub if isinstance(s, ast.stmt)], conds)
            # `except ImportError: collect_ignore.append(...)` is what every
            # project with an optional dependency writes, and handlers were not
            # walked at all: an `ExceptHandler` is not an `ast.stmt`, so the
            # loop above skipped the whole list (THREATMODEL 83).
            #
            # Walking them without reading the exception as a guard would have
            # turned that idiom into a false positive. The exception type *is*
            # the condition, so it is recorded as one and the compat-gate logic
            # treats it as the gate it is.
            for handler in getattr(stmt, "handlers", []) or []:
                if not isinstance(handler, ast.ExceptHandler):
                    continue
                record(
                    [s for s in handler.body if isinstance(s, ast.stmt)],
                    conds + (_handler_guard(stmt, handler),),
                )

    record(tree.body, ())
    return found


_IMPORT_ERRORS = frozenset({"ImportError", "ModuleNotFoundError"})


def _handler_guard(try_stmt, handler: ast.ExceptHandler) -> str:
    """The condition an `except` block actually expresses.

    `try: import redis / except ImportError: collect_ignore.append(...)` is the
    optional-dependency gate every such project writes, and its condition is
    exactly "redis is not installed". Recorded as `find_spec("redis") is None`,
    which is the spelling the compat-gate logic already recognises and the one
    an adversarial audit cited when this build blocked a PR that *added* the
    tests it was guarding.

    Anything else — a bare `except`, a different exception, a try body that is
    not a plain import — records the exception text, which does not parse as a
    condition and therefore earns no credit. That is deliberate: an
    unconditional control hidden inside a `try` should still fire.
    """
    caught = _dotted(handler.type) if handler.type is not None else None
    body = [s for s in getattr(try_stmt, "body", []) if isinstance(s, ast.stmt)]
    if caught in _IMPORT_ERRORS and body and all(
        isinstance(s, (ast.Import, ast.ImportFrom)) for s in body
    ):
        first = body[0]
        module = (
            first.names[0].name
            if isinstance(first, ast.Import) and first.names
            else (first.module or "")
        )
        if module:
            return f'find_spec("{module}") is None'
    return f"except {caught}" if caught else "except"


def _ignored_paths(controls) -> tuple[str, ...]:
    """Every literal path these controls put into `collect_ignore`, sorted.

    Markers deduplicate by name, so a conftest that *already had* a control
    produced no event at all when a second one was appended — an entire test
    file left collection in silence (THREATMODEL 81). Comparing the resolved
    set of paths rather than the marker's name is what makes the second control
    an event.

    Non-literal entries are simply absent: a path this cannot resolve is not
    evidence in either direction.
    """
    out: set[str] = set()
    for node, _guard in controls:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                out.add(sub.value)
    return tuple(sorted(out))


def _conftest_unit(tree: ast.Module, text: str, off: _Offsets) -> ParsedUnit:
    """Suite-level collection controls in a conftest, as one synthetic unit."""
    markers: list[Marker] = _pytestmark_markers(tree, text, off)

    controls = _collection_controls(tree, text)
    ignored: tuple[str, ...] = _ignored_paths(controls)
    if controls:
        node, _ = controls[0]
        guards = [g for _, g in controls]
        # The weakest guard wins. Markers are deduplicated by name, so without
        # this one honest version gate would have covered any number of
        # unconditional drops sharing the name (bypass 71). A disjunction is
        # the true reading anyway: the files are ignored if *any* branch fires.
        combined = (
            None
            if any(g is None for g in guards)
            else " or ".join(f"({g})" for g in guards)
        )
        seg = (text.seg(node) or "conftest.collect_ignore").split("\n")[0]
        markers.append(
            Marker(name="conftest.collect_ignore", text=seg, span=off.span(node), guard=combined)
        )

    for node in ast.walk(tree):
        name = None
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in _CONFTEST_HOOKS:
            name = f"conftest.{node.name}"
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
    side = UnitSide(span=(0, len(text.text)), markers=unique, collect_ignored=ignored)
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


def _normalize_for_fingerprint(tree: ast.AST) -> ast.AST:
    """Strip what cannot change behaviour, so a cosmetic edit does not flip a
    symbol's fingerprint and buy repair evidence (audit 2026-08-19).

    `def f(x) -> float:` with an added return annotation, a non-leading string
    statement after the docstring, `x: int` with no value, and
    `_checked = None` inside the function body all change `ast.dump` while
    changing nothing the code does — and an attacker controls both sides of
    the diff, so each was a one-line purchase of REPAIR_EVIDENCE for any
    oracle cheat (THREATMODEL row 4 reopened).

    Removed here: parameter/return annotations (function and lambda), string
    constants in non-leading statement position, value-less annotated
    assignments, the annotation of a value-carrying annotated assignment,
    and — **inside function bodies only** — an assignment of a literal to a
    name the function never reads. Module- and class-level constants are
    untouched: a constant the production file never reads may still be read
    by the tests (`TAX = 0.05` in billing.py), and dropping it would deny
    honest repair evidence. Functions containing `global`/`nonlocal` keep
    their assignments: a store can escape the scope without a load.

    Deliberately NOT normalised: alpha-renames. Deciding which names escape
    needs scope analysis checkwash does not have, and a wrong normalisation
    silently disables evidence for genuine rename-driven API changes — a
    documented residual, priced as such.
    """
    for node in ast.walk(tree):
        args: ast.arguments | None = None
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            node.returns = None
            args = node.args
        elif isinstance(node, ast.Lambda):
            args = node.args
        if args is not None:
            for arg in (
                *args.posonlyargs, *args.args, args.vararg,
                *args.kwonlyargs, args.kwarg,
            ):
                if arg is not None:
                    arg.annotation = None
        if isinstance(node, ast.AnnAssign) and node.annotation is not None:
            node.annotation = None
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            kept: list[ast.stmt] = []
            for stmt in node.body:
                # Any string statement still standing is noise: leading
                # docstrings were stripped by the earlier pass, so a survivor
                # here was never a docstring (audit 2026-08-19).
                if (
                    isinstance(stmt, ast.Expr)
                    and isinstance(stmt.value, ast.Constant)
                    and isinstance(stmt.value.value, str)
                ):
                    continue
                if isinstance(stmt, ast.AnnAssign) and stmt.value is None:
                    continue  # `x: int` binds nothing
                kept.append(stmt)
            node.body = kept or [ast.Pass()]
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        # The expensive checks (nested walks) run only when a drop candidate
        # exists, so files without dead literal bindings pay one cheap pass.
        if not any(
            isinstance(stmt, ast.Assign)
            and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], ast.Name)
            and isinstance(stmt.value, ast.Constant)
            for stmt in node.body
        ):
            continue
        if any(
            isinstance(stmt, (ast.Global, ast.Nonlocal))
            for stmt in ast.walk(node)
        ):
            continue
        loads = {
            n.id
            for n in ast.walk(node)
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
        }
        kept = []
        for stmt in node.body:
            if (
                isinstance(stmt, ast.Assign)
                and len(stmt.targets) == 1
                and isinstance(stmt.targets[0], ast.Name)
                and stmt.targets[0].id not in loads
                and isinstance(stmt.value, ast.Constant)
            ):
                continue  # a literal bound to a name this scope never reads
            kept.append(stmt)
        node.body = kept or [ast.Pass()]
    return tree


def _fingerprint(node: ast.AST) -> str:
    dump = ast.dump(node, include_attributes=False)
    return hashlib.sha256(dump.encode("utf-8")).hexdigest()[:16]


def _is_test_name(name: str) -> bool:
    return name.startswith("test")


def _is_test_class(node: ast.ClassDef) -> bool:
    """pytest's default `python_classes = Test*`, **plus unittest subclasses**.

    Renaming `TestBilling` to `BillingTests` silently deletes every test in a
    plain class, so the `Test*` half stays (confirmed red-team finding).

    But `python_classes` does not gate unittest collection: pytest collects any
    `unittest.TestCase` subclass whatever it is called. This function used to
    take only the name and return `name.startswith("Test")`, so
    `class BillingTests(unittest.TestCase)` produced **zero units** and all
    nineteen detectors were inert on the file — `assertEqual(total, 105.0)`
    becoming `assertTrue(total > 0)` passed clean while pytest ran the test and
    the suite went from `1 failed` to `1 passed`. SPEC §2 asserted the opposite
    of pytest's real behaviour and the implementation was built on it
    (THREATMODEL 86, adversarial verification 2026-08-09).

    Base detection is syntactic and deliberately generous: anything whose base
    is spelled `TestCase`, or is an attribute access ending in `TestCase`
    (`unittest.TestCase`, `unittest.IsolatedAsyncioTestCase`, `django.test.TestCase`),
    counts. A project-local subclass used as a base (`class Foo(BaseTest)`) is
    not resolved — that is a residual, not a claim.
    """
    if node.name.startswith("Test"):
        return True
    for base in node.bases:
        dotted = _dotted(base)
        if dotted and dotted.split(".")[-1].endswith("TestCase"):
            return True
    return False


def _transitive_test_classes(tree: ast.Module) -> frozenset[str]:
    """Module-level class names that are test containers once same-file base
    chains are followed to a fixpoint.

    SPEC §2: every `unittest.TestCase` subclass is collected, whatever it is
    named. `_is_test_class` reads one hop of spelled bases, so routing
    TestCase through a same-file class — tornado's `abstract_base_test`
    refactor turned `class OverrideResolverTest(AsyncTestCase, _Mixin)` into
    `class OverrideResolverTest(_Mixin)` with `_Mixin(AsyncTestCase)` — made
    the subclass stop being a test container, and every lexical unit in it
    "disappeared" while its def was byte-identical on both sides (R1 phantom,
    tornado e6d3f49). Same-file bare-name bases only; a base imported from
    another module is still the documented residual.
    """
    classes = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}
    test = {name for name, node in classes.items() if _is_test_class(node)}
    changed = True
    while changed:
        changed = False
        for name, node in classes.items():
            if name in test:
                continue
            for base in node.bases:
                if isinstance(base, ast.Name) and base.id in test:
                    test.add(name)
                    changed = True
                    break
    return frozenset(test)


def _callees(node: ast.AST) -> tuple[str, ...]:
    names: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            dotted = _dotted(sub.func)
            if dotted:
                names.add(dotted.rsplit(".", 1)[-1])
    return tuple(sorted(names))


def _definition_import_maps(tree: ast.Module) -> dict[int, dict[str, str]]:
    """Live imports when module/class definitions and decorators execute."""
    out: dict[int, dict[str, str]] = {}

    def walk_container(root: ast.AST, base: dict[str, str]) -> None:
        environments, final = _scope_import_environments(
            root, base, definition_base=base
        )
        body = getattr(root, "body", ())
        if not isinstance(body, list):
            return

        def walk_statements(statements: list[ast.stmt]) -> None:
            for stmt in statements:
                exact = _imports_at(stmt, final, environments)
                if isinstance(
                    stmt,
                    (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
                ):
                    out[id(stmt)] = dict(exact)
                    walk_container(stmt, exact)
                    continue
                for field in ("body", "orelse", "finalbody"):
                    nested = getattr(stmt, field, None)
                    if isinstance(nested, list):
                        walk_statements(
                            [node for node in nested if isinstance(node, ast.stmt)]
                        )
                for handler in getattr(stmt, "handlers", ()):
                    walk_statements(handler.body)
                for case in getattr(stmt, "cases", ()):
                    walk_statements(case.body)

        walk_statements(body)

    walk_container(tree, {})
    return out


def parse_python(data: bytes, collect_tests: bool, conftest: bool = False) -> ParsedFile:
    raw = normalize_source(data)
    # This gate is intentionally before ast.parse and every per-test walk.
    # Files with no installation-shaped source pay none of the stand-in
    # lifetime machinery; the structured predicate remains authoritative for
    # candidates that pass this conservative source-only screen.
    standin_source_hint = collect_tests and _raw_may_contain_standin(raw)
    try:
        tree = ast.parse(raw)
    except SyntaxError:
        return ParsedFile(parse_ok=False)
    except (RecursionError, ValueError, MemoryError):
        # Deeply nested expressions raise RecursionError, not SyntaxError.
        # Head-side content is attacker-controlled: degrade visibly instead
        # of crashing the process (confirmed red-team finding).
        return ParsedFile(parse_ok=False)

    # One parse, one in-place normalisation: symbol fingerprints are dumped
    # straight from subtrees instead of re-running unparse+parse per symbol,
    # and the fingerprint ignores what cannot change behaviour (annotations,
    # noise statements, dead literal bindings) so a cosmetic prod edit buys
    # no repair evidence. Test files never fingerprint symbols, so they skip
    # the pass entirely — collection semantics never see a mutated tree.
    _strip_docstrings(tree)
    if not collect_tests:
        _normalize_for_fingerprint(tree)
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
    # Callables a unit can reach without leaving the file. Computed once per
    # module, not per unit: a suite with 200 tests and 5 helpers would otherwise
    # rebuild the same map 200 times.
    module_scopes: dict[str, ast.AST] = {}
    test_class_names: frozenset[str] = frozenset()
    if collect_tests:
        module_scopes = _module_callable_scopes(tree)
        test_class_names = _transitive_test_classes(tree)
    import_bindings = _standin_import_bindings(tree) if collect_tests else {}
    module_import_origins = (
        _module_native_import_origins(tree, import_bindings)
        if collect_tests
        else ()
    )
    definition_import_maps = (
        _definition_import_maps(tree)
        if collect_tests
        and any(
            isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            )
            and (
                node.decorator_list
                or (
                    isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and (node.args.defaults or any(node.args.kw_defaults))
                )
            )
            for node in ast.walk(tree)
        )
        else {}
    )
    module_binding_statements = (
        tuple(_definite_module_statements(tree.body)) if collect_tests else ()
    )
    module_import_locals = {
        name
        for stmt in module_binding_statements
        if isinstance(stmt, (ast.Import, ast.ImportFrom))
        for name in _import_bindings((stmt,))
    }
    module_standin_bindings = (
        _module_local_bindings(tree, definition_import_maps)
        if any(
            isinstance(
                stmt,
                (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.ClassDef),
            )
            or (
                isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef))
                and (
                    not _is_test_name(stmt.name)
                    or _is_fixture_def(
                        stmt,
                        definition_import_maps.get(id(stmt), import_bindings),
                    )
                    or stmt.name in module_import_locals
                )
            )
            for stmt in module_binding_statements
        )
        else {}
    )
    fixture_dependencies = (
        _module_fixture_dependencies(tree, definition_import_maps)
        if collect_tests
        else {}
    )
    transparent_fixture_receivers = (
        _transparent_fixture_receivers(tree, definition_import_maps)
        if collect_tests
        else frozenset()
    )
    module_autouse_fixtures = (
        _module_autouse_fixtures(tree, definition_import_maps)
        if collect_tests
        else ()
    )
    module_fixture_uses = (
        _module_usefixtures(tree, import_bindings) if collect_tests else ()
    )
    module_parametrize_providers = (
        _parametrize_provider_modes(
            _module_pytestmark_values(tree), import_bindings
        )
        if collect_tests
        else {}
    )
    assigned_standin_call_aliases: set[str] = set()
    collect_standins = (
        _has_standin_install(
            tree, import_bindings, assigned_standin_call_aliases
        )
        if collect_tests and standin_source_hint
        else False
    )
    module_monkeypatch_receivers: frozenset[str] = frozenset()
    module_api_values: dict[str, str] = {}
    module_api_definition_values: dict[int, dict[str, str]] = {}
    if collect_standins:
        module_api_environments, module_api_imports = (
            _scope_import_environments(tree, {})
        )
        module_api_facts = _standin_api_facts(
            tree, module_api_imports, module_api_environments
        )
        module_api_values = dict(module_api_facts.final_values)
        module_api_definition_values = {
            node_id: dict(values)
            for node_id, values in module_api_facts.definition_values.items()
        }
        module_monkeypatch_receivers = frozenset(
            name
            for name, origin in module_api_facts.final_values.items()
            if origin == "monkeypatch"
            or origin.startswith("monkeypatch_instance:")
        )
    # One file's worth of scope-walk memoisation: (scope-nodes, invocations),
    # shared by every unit so a helper reached by many tests is walked once.
    file_caches: tuple[dict, dict] = ({}, {})

    def visit(
        node: ast.AST,
        prefix: str,
        inherited: list[Marker],
        inherited_fixtures: tuple[str, ...],
        inherited_parametrize: dict[str, bool],
        inherited_fixture_layers: tuple[
            tuple[str, dict[str, tuple[str, ...]], tuple[str, ...]], ...
        ],
        collectible: bool,
    ) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qual = f"{prefix}{child.name}"
                child_definition_imports = definition_import_maps.get(
                    id(child), import_bindings
                )
                if want_symbols:
                    symbols[qual] = _fingerprint(child)
                    symbol_calls[qual] = _callees(child)
                if collect_tests and collectible and _is_test_name(child.name):
                    unit_raw = "\n".join(
                        (
                            *(text.seg(decorator) or "" for decorator in child.decorator_list),
                            text.seg(child) or "",
                        )
                    )
                    units.append(
                        _collect_unit(
                            child,
                            qual,
                            text,
                            off,
                            inherited,
                            module_scopes,
                            file_caches,
                            import_bindings,
                            module_import_origins,
                            tuple(
                                sorted(
                                    set(inherited_fixtures)
                                    | set(
                                        _decorator_usefixtures(
                                            child, child_definition_imports
                                        )
                                    )
                                )
                            ),
                            inherited_parametrize,
                            collect_standins=(
                                collect_standins
                                and (
                                    _raw_unit_may_contain_standin(
                                        unit_raw,
                                        import_bindings,
                                        assigned_standin_call_aliases,
                                    )
                                    or any(
                                        name in module_scopes
                                        for name in _invocations(
                                            child, file_caches
                                        )
                                    )
                                )
                            ),
                            module_standin_bindings=module_standin_bindings,
                            definition_imports=child_definition_imports,
                            definition_import_maps=definition_import_maps,
                            module_monkeypatch_receivers=(
                                module_monkeypatch_receivers
                            ),
                            module_api_values=module_api_values,
                            module_api_definition_values=(
                                module_api_definition_values
                            ),
                            transparent_fixture_receivers=(
                                transparent_fixture_receivers
                            ),
                            fixture_layers=inherited_fixture_layers,
                        )
                    )
                # Nested defs are never collected as pytest items.
                visit(
                    child,
                    qual + ".",
                    inherited,
                    inherited_fixtures,
                    inherited_parametrize,
                    inherited_fixture_layers,
                    False,
                )
            elif isinstance(child, ast.ClassDef):
                qual = f"{prefix}{child.name}"
                child_definition_imports = definition_import_maps.get(
                    id(child), import_bindings
                )
                if want_symbols:
                    symbols[qual] = _fingerprint(child)
                # Class-level skip decorators disable every test inside the
                # class — they must reach each unit (confirmed red-team FN).
                class_markers = _decorator_markers(child, text, off) if collect_tests else []
                class_fixtures = (
                    tuple(
                        sorted(
                            set(inherited_fixtures)
                            | set(
                                _decorator_usefixtures(
                                    child, child_definition_imports
                                )
                            )
                        )
                    )
                    if collect_tests
                    else inherited_fixtures
                )
                class_parametrize = (
                    _merge_parametrize_provider_modes(
                        inherited_parametrize,
                        _parametrize_provider_modes(
                            child.decorator_list, child_definition_imports
                        ),
                    )
                    if collect_tests
                    else inherited_parametrize
                )
                class_fixture_dependencies = (
                    _module_fixture_dependencies(
                        child,
                        definition_import_maps,
                        class_scope=True,
                    )
                    if collect_tests
                    else {}
                )
                class_fixture_layers = inherited_fixture_layers
                if class_fixture_dependencies:
                    class_fixture_layers = (
                        *class_fixture_layers,
                        (
                            qual,
                            class_fixture_dependencies,
                            _module_autouse_fixtures(
                                child, definition_import_maps
                            ),
                        ),
                    )
                visit(
                    child,
                    qual + ".",
                    inherited + class_markers,
                    class_fixtures,
                    class_parametrize,
                    class_fixture_layers,
                    collectible
                    and (_is_test_class(child) or child.name in test_class_names)
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
                visit(
                    child,
                    prefix,
                    inherited,
                    inherited_fixtures,
                    inherited_parametrize,
                    inherited_fixture_layers,
                    collectible,
                )

    visit(
        tree,
        "",
        module_markers,
        module_fixture_uses,
        module_parametrize_providers,
        (),
        True,
    )
    standin_installs = (
        _module_standin_installs(
            tree,
            text,
            import_bindings,
            definition_imports=definition_import_maps,
            include_hooks=conftest,
        )
        if collect_tests and collect_standins
        else ()
    )
    if conftest:
        units = [_conftest_unit(tree, text, off)]
    elif collect_tests and standin_installs:
        for unit in units:
            def class_install_applies(install: StandinInstall) -> bool:
                if install.scope == "class":
                    owner = install.owner or ""
                    return bool(owner) and unit.qualname.startswith(owner + ".")
                if install.scope == "class_fixture":
                    owner = install.owner or ""
                    class_name = owner.rpartition(".")[0]
                    return (
                        bool(class_name)
                        and unit.qualname.startswith(class_name + ".")
                        and install_applies(
                            install,
                            unit.side,
                            fixture_dependencies,
                            module_autouse_fixtures,
                        )
                    )
                return install_applies(
                    install,
                    unit.side,
                    fixture_dependencies,
                    module_autouse_fixtures,
                )

            applicable = [
                install
                for install in standin_installs
                if (
                    install.kind != "module"
                    or install.scope in ("fixture", "class", "class_fixture")
                    or (
                        install.scope == "module"
                        and _module_imported_after_install(tree, install)
                    )
                )
                and class_install_applies(install)
            ]
            if applicable:
                inherited = {
                    install.effect_identity: install
                    for install in (
                        *(unit.side.standin_installs or ()),
                        *applicable,
                    )
                }
                unit.side.standin_installs = tuple(
                    inherited[key] for key in sorted(inherited)
                )

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
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            # The with-context twins of `except AssertionError`:
            # `suppress(...)` swallows a failed assert, the raises family
            # (`pytest.raises`, `self.assertRaises`, `assertRaisesRegex`)
            # expects one — for any type set that can catch an
            # AssertionError, same predicate as the except path (issue #57;
            # the original two spellings were red-team bypasses,
            # 2026-09-01). Keyed on wrapping a bare `assert` so a contract
            # test of a helper (a call, not an assert) is untouched. Emitted
            # to both lists: for a test file the engine reads swallowing, and
            # neutralising an assertion is the swallow.
            #
            # The cheap check first: `with` statements are everywhere in test
            # files (`open`, `raises`, `patch`), and running the bare-assert
            # walk on every one of them cost the macOS perf leg its budget
            # (v0.2.4). `_neutralizes_assertionerror` is a name+args lookup;
            # the walk runs only when a neutraliser is actually present.
            neutralisers = [
                item.context_expr
                for item in node.items
                if _neutralizes_assertionerror(item.context_expr)
            ]
            if neutralisers and _wraps_bare_assert(node.body):
                for ctx in neutralisers:
                    seg = _norm((text.seg(ctx) or "").split("\n")[0])
                    broad.append(seg)
                    swallowing.append(seg)
    broad.sort()
    swallowing.sort()

    suppressions = [
        f"{i + 1}:{line.strip()}"
        for i, line in enumerate(raw.split("\n"))
        if _SUPPRESSION_RE.search(line)
    ]

    units.sort(key=lambda u: u.span)
    if collect_tests:
        helper_asserts, fixture_asserts, autouse = _module_oracle_scopes(
            tree,
            text,
            off,
            definition_import_maps,
            import_bindings,
            module_import_origins,
        )
        helper_calls = _module_helper_calls(tree, definition_import_maps)
    else:
        helper_asserts, fixture_asserts, autouse = {}, {}, ()
        helper_calls = {}
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
        constants=_top_level_constants(tree, text),
        from_imports=_top_level_from_imports(tree),
        import_bindings=import_bindings,
        standin_installs=standin_installs,
        fixture_defs=(
            _fixture_definitions(tree, definition_import_maps)
            if collect_tests
            else {}
        ),
        helper_asserts=helper_asserts,
        helper_calls=helper_calls,
        fixture_asserts=fixture_asserts,
        autouse_fixtures=autouse,
        fixture_dependencies=fixture_dependencies,
    )


def _module_helper_calls(
    tree: ast.Module,
    definition_imports: dict[int, dict[str, str]] | None = None,
) -> dict[str, tuple[str, ...]]:
    """Callee leaves of same-file helpers. One hop, no fixtures, no tests."""
    out: dict[str, tuple[str, ...]] = {}
    for name, node in _module_callable_scopes(tree).items():
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        exact = (definition_imports or {}).get(id(node))
        if _is_test_name(name) or _is_fixture_def(node, exact):
            continue
        out[name] = _callees(node)
    return out


def _pytest_definition_decorator(
    node: ast.AST,
    member: str,
    imports: dict[str, str] | None = None,
) -> ast.AST | None:
    """One decorator positively resolved to ``pytest.<member>``."""
    if not isinstance(
        node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    ):
        return None
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if imports is None:
            canonical = _dotted(target)
            accepted = canonical in (f"pytest.{member}", member)
        else:
            accepted = _live_import_path(target, imports) == f"pytest.{member}"
        if accepted:
            return decorator
    return None


def _is_fixture_def(
    node: ast.AST, imports: dict[str, str] | None = None
) -> bool:
    return (
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and _pytest_definition_decorator(node, "fixture", imports) is not None
    )


def _fixture_public_name(
    node: ast.AST, imports: dict[str, str] | None = None
) -> str | None:
    """Literal pytest fixture name, including ``@fixture(name=...)``."""
    decorator = _pytest_definition_decorator(node, "fixture", imports)
    if decorator is None:
        return None
    assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    if isinstance(decorator, ast.Call):
        names = [kw.value for kw in decorator.keywords if kw.arg == "name"]
        if not names:
            return node.name
        if len(names) != 1:
            return None
        if isinstance(names[0], ast.Constant) and names[0].value is None:
            return node.name
        value = _string_literal(names[0])
        if value and value.isidentifier() and not keyword.iskeyword(value):
            return value
        # A dynamic/empty/invalid exported name is not evidence for either
        # spelling.  Falling back to the Python carrier would silently invent
        # a fixture registration pytest may not expose under that name.
        return None
    return node.name


def _fixture_is_autouse(
    node: ast.AST, imports: dict[str, str] | None = None
) -> bool:
    decorator = _pytest_definition_decorator(node, "fixture", imports)
    if not isinstance(decorator, ast.Call):
        return False
    return any(
        kw.arg == "autouse"
        and isinstance(kw.value, ast.Constant)
        and kw.value.value is True
        for kw in decorator.keywords
    )


def _hook_registration(
    node: ast.AST, imports: dict[str, str] | None = None
) -> tuple[str, bool] | None:
    """Effective pytest hook name and whether it is a wrapper."""
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return None
    decorator = _pytest_definition_decorator(node, "hookimpl", imports)
    if decorator is None:
        return (node.name, False) if node.name.startswith("pytest_") else None
    effective = node.name
    wrapper = False
    if isinstance(decorator, ast.Call):
        specnames = [
            keyword.value
            for keyword in decorator.keywords
            if keyword.arg == "specname"
        ]
        if specnames:
            if len(specnames) != 1:
                return None
            literal = _string_literal(specnames[0])
            if literal is None or not literal.startswith("pytest_"):
                return None
            effective = literal
        wrapper = any(
            keyword.arg in ("hookwrapper", "wrapper")
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value is True
            for keyword in decorator.keywords
        )
    return (effective, wrapper)


def _is_runtest_call_wrapper(
    node: ast.AST, imports: dict[str, str] | None = None
) -> bool:
    return _hook_registration(node, imports) == ("pytest_runtest_call", True)


def _module_autouse_fixtures(
    tree: ast.Module,
    definition_imports: dict[int, dict[str, str]] | None = None,
) -> tuple[str, ...]:
    return tuple(
        sorted(
            fixture_name
            for node in _module_callable_scopes(tree).values()
            if _fixture_is_autouse(
                node, (definition_imports or {}).get(id(node))
            )
            if (
                fixture_name := _fixture_public_name(
                    node, (definition_imports or {}).get(id(node))
                )
            )
            is not None
        )
    )


def _module_fixture_dependencies(
    tree: ast.Module | ast.ClassDef,
    definition_imports: dict[int, dict[str, str]] | None = None,
    *,
    class_scope: bool = False,
) -> dict[str, tuple[str, ...]]:
    out: dict[str, tuple[str, ...]] = {}
    for node in _module_callable_scopes(tree).values():
        exact = (definition_imports or {}).get(id(node))
        if not _is_fixture_def(node, exact):
            continue
        fixture_name = _fixture_public_name(node, exact)
        if fixture_name is None:
            continue
        out[fixture_name] = tuple(
            sorted(
                _required_injected_parameters(
                    node,
                    class_member=class_scope,
                    definition_imports=exact,
                )
            )
        )
    return {name: out[name] for name in sorted(out)}


def _transparent_fixture_receivers(
    tree: ast.Module,
    definition_imports: dict[int, dict[str, str]] | None = None,
) -> frozenset[str]:
    """Conventional fixture overrides that return the injected receiver.

    A same-name fixture normally shadows pytest's built-in provider.  The
    exact one-statement forwarding wrappers below are different: pytest
    injects the previous provider and the wrapper exports that identical
    object.  No other return/yield shape is promoted to receiver provenance.
    """
    transparent: set[str] = set()
    for node in _module_callable_scopes(tree).values():
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        exact = (definition_imports or {}).get(id(node))
        if not _is_fixture_def(node, exact):
            continue
        fixture_name = _fixture_public_name(node, exact)
        if fixture_name not in ("monkeypatch", "mocker"):
            continue
        if fixture_name not in _required_injected_parameters(
            node, definition_imports=exact
        ):
            continue
        body = [
            stmt
            for stmt in node.body
            if not (
                isinstance(stmt, ast.Expr)
                and isinstance(stmt.value, ast.Constant)
                and isinstance(stmt.value.value, str)
            )
        ]
        forwarded: ast.AST | None = None
        if len(body) == 1 and isinstance(body[0], ast.Return):
            forwarded = body[0].value
        elif (
            len(body) == 1
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Yield)
        ):
            forwarded = body[0].value.value
        if isinstance(forwarded, ast.Name) and forwarded.id == fixture_name:
            transparent.add(fixture_name)
    return frozenset(transparent)


def _classified_asserts(
    nodes,
    text,
    off,
    *,
    imports: Mapping[str, str],
    import_environments: dict[int, dict[str, str]],
    runtime_import_environments: dict[
        int, tuple[tuple[str, str, str, int, int], ...]
    ],
    module_import_origins: tuple[
        tuple[str, str, str, int, int], ...
    ],
) -> tuple:
    """Classified carrier asserts with their definition-time provenance."""
    out = []
    for node in nodes:
        if not isinstance(node, ast.Assert):
            continue
        c = _classify_assert(node, text)
        seg = text.seg(node) or ""
        exact_imports = _imports_at(node, dict(imports), import_environments)
        runtime_imports = runtime_import_environments.get(id(node), ())
        module_imports = _visible_module_import_origins(
            module_import_origins,
            exact_imports,
            runtime_imports,
        )
        bare = (
            isinstance(node.test, ast.Compare)
            and len(node.test.comparators) == 1
            and isinstance(node.test.comparators[0], ast.Name)
        )
        out.append(
            Assertion(
                id="a?",  # assigned when merged into a unit
                bare_expectation=bare,
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
                left_names=c.left_names,
                right_depends_on=c.right_names,
                inherited=True,
                standin_imports=exact_imports,
                standin_runtime_imports=runtime_imports,
                standin_module_imports=module_imports,
                standin_position=(
                    getattr(node, "lineno", 0) or 0,
                    getattr(node, "col_offset", 0) or 0,
                ),
                standin_oracle_key=_standin_oracle_key(
                    node,
                    c,
                    exact_imports,
                ),
            )
        )
    return tuple(out)


def _module_oracle_scopes(
    tree: ast.Module,
    text,
    off,
    definition_imports: dict[int, dict[str, str]] | None = None,
    import_bindings: dict[str, str] | None = None,
    module_import_origins: tuple[
        tuple[str, str, str, int, int], ...
    ] = (),
):
    """(helper_asserts, fixture_asserts, autouse_fixtures) for a test module.

    Helpers contribute their **own** direct asserts — one hop across the file
    boundary, matching the same-file depth line. Fixtures contribute everything
    lexically inside: the closure they return is what the unit invokes, and the
    post-`yield` teardown runs whether or not anything calls it.
    """
    helpers: dict[str, tuple] = {}
    fixtures: dict[str, tuple] = {}
    autouse: list[str] = []

    def carrier_environments(
        root: ast.FunctionDef | ast.AsyncFunctionDef,
        definition_base: dict[str, str] | None,
    ):
        """Import provenance for a carrier and its lexical closures."""
        all_import_environments: dict[int, dict[str, str]] = {}
        all_runtime_imports: dict[
            int, tuple[tuple[str, str, str, int, int], ...]
        ] = {}

        def direct_nested_functions(scope: ast.AST):
            stack = list(ast.iter_child_nodes(scope))
            while stack:
                child = stack.pop()
                if isinstance(
                    child, (ast.FunctionDef, ast.AsyncFunctionDef)
                ):
                    yield child
                    continue
                if isinstance(child, (ast.ClassDef, ast.Lambda)):
                    continue
                stack.extend(ast.iter_child_nodes(child))

        def visit_scope(
            scope: ast.FunctionDef | ast.AsyncFunctionDef,
            base: dict[str, str],
            scope_definition_base: dict[str, str] | None,
            initial_runtime: tuple[
                tuple[str, str, str, int, int], ...
            ] = (),
        ) -> dict[str, str]:
            environments, imported = _scope_import_environments(
                scope,
                base,
                definition_base=scope_definition_base,
            )
            runtime = _scope_runtime_import_environments(
                scope,
                imported,
                environments,
                initial_rows=initial_runtime,
            )
            all_import_environments.update(environments)
            all_runtime_imports.update(runtime)
            for child in direct_nested_functions(scope):
                child_base = _imports_at(child, imported, environments)
                visit_scope(
                    child,
                    child_base,
                    (definition_imports or {}).get(
                        id(child), child_base
                    ),
                    runtime.get(id(child), ()),
                )
            return imported

        imported = visit_scope(
            root,
            dict(import_bindings or {}),
            definition_base,
        )
        return all_import_environments, imported, all_runtime_imports

    for carrier, node in _module_callable_scopes(tree).items():
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        exact = (definition_imports or {}).get(id(node))
        fixture = _is_fixture_def(node, exact)
        if fixture:
            fixture_name = _fixture_public_name(node, exact)
            if fixture_name is None:
                continue
            if _fixture_is_autouse(node, exact):
                autouse.append(fixture_name)
            assert_nodes = tuple(
                candidate
                for candidate in ast.walk(node)
                if isinstance(candidate, ast.Assert)
            )
        else:
            if _is_test_name(carrier):
                continue
            assert_nodes = tuple(
                candidate
                for candidate in _scope_nodes(node)
                if isinstance(candidate, ast.Assert)
            )
        if not assert_nodes:
            continue

        (
            import_environments,
            carrier_imports,
            runtime_import_environments,
        ) = carrier_environments(node, exact)
        found = _classified_asserts(
            assert_nodes,
            text,
            off,
            imports=carrier_imports,
            import_environments=import_environments,
            runtime_import_environments=runtime_import_environments,
            module_import_origins=module_import_origins,
        )
        if fixture:
            fixtures[fixture_name] = found
        else:
            helpers[carrier] = found
    return helpers, fixtures, tuple(sorted(autouse))


def _top_level_constants(tree: ast.Module, text) -> dict[str, str]:
    """Top-level `NAME = <expr>` bindings, name -> expression source."""
    out: dict[str, str] = {}
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign):
            value, names = stmt.value, [t.id for t in stmt.targets if isinstance(t, ast.Name)]
        elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None and isinstance(stmt.target, ast.Name):
            value, names = stmt.value, [stmt.target.id]
        else:
            continue
        seg = text.seg(value)
        if seg:
            for name in names:
                out[name] = seg
    return out


_SETATTR_CALLS = frozenset({"setattr", "set_attribute"})
_PATCH_CALLS = ("setattr", "setitem", "set_attribute")
_STANDIN_COMPOUND_STATEMENTS = (
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.Try,
    ast.TryStar,
    ast.With,
    ast.AsyncWith,
    ast.Match,
)


@dataclass
class _StandinApiFacts:
    """Internal, position-aware proof for stand-in API spellings."""

    call_kinds: dict[int, str] = field(default_factory=dict)
    call_contexts: dict[int, ast.With | ast.AsyncWith] = field(
        default_factory=dict
    )
    call_fixture_receivers: dict[int, str] = field(default_factory=dict)
    # Exact proven receiver origin for method calls. Constructed
    # MonkeyPatch objects carry an instance-specific origin so ``undo()``
    # closes only installations made through that same object.
    call_receiver_origins: dict[int, str] = field(default_factory=dict)
    # Runtime API origins of each call's explicit arguments. ``None`` keeps an
    # explicit but unproven value distinct from an omitted argument so helper
    # defaults cannot leak through a call-site override.
    call_argument_origins: dict[
        int,
        tuple[
            tuple[str | None, ...],
            tuple[tuple[str | None, str | None], ...],
        ],
    ] = field(default_factory=dict)
    # Runtime API environment at each exact call site.  This is separate from
    # argument origins because a nested helper closes over its lexical
    # parent's live locals even when none of them are explicit arguments.
    call_value_environments: dict[int, dict[str, str]] = field(
        default_factory=dict
    )
    final_values: dict[str, str] = field(default_factory=dict)
    # API values live immediately before a named scope is defined. Decorators
    # and defaults execute in this environment, before the new scope's local
    # bindings exist; its body instead starts from the separately shadowed
    # runtime environment below.
    definition_values: dict[int, dict[str, str]] = field(default_factory=dict)


_CALLABLE_API_PATHS = {
    "builtins.setattr": "builtin_setattr",
    "builtins.getattr": "builtin_getattr",
    "builtins.vars": "builtin_vars",
    "operator.setitem": "operator_setitem",
    "unittest.mock.patch": "mock_patch",
    "unittest.mock.patch.object": "mock_patch_object",
    "unittest.mock.patch.dict": "mock_patch_dict",
    "pytest.MonkeyPatch": "monkeypatch_constructor",
}


def _standin_api_facts(
    root: ast.AST,
    imports: dict[str, str],
    environments: dict[int, dict[str, str]] | None = None,
    *,
    monkeypatch_receivers: frozenset[str] = frozenset(),
    mocker_receivers: frozenset[str] = frozenset(),
    inherited_values: Mapping[str, str] | None = None,
    definition_time_values: Mapping[str, str] | None = None,
    parameter_values: Mapping[str, str | None] | None = None,
) -> _StandinApiFacts:
    """Resolve supported APIs without trusting a coincidental method name.

    The value environment is deliberately tiny: builtin callables plus the
    two patching receiver families.  Unknown branches retain an origin only
    when every path agrees, so ambiguity cannot become ownership evidence.
    """
    facts = _StandinApiFacts()
    builtin_values: dict[str, str] = {
        name: kind
        for name, kind in {
            "setattr": "builtin_setattr",
            "getattr": "builtin_getattr",
            "vars": "builtin_vars",
        }.items()
    }
    values = dict(builtin_values)
    values.update(inherited_values or {})
    definition_environment = dict(builtin_values)
    definition_environment.update(
        inherited_values or {}
        if definition_time_values is None
        else definition_time_values
    )
    if isinstance(root, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        lexical = _lexical_scope_names(root)[0]
        for name in lexical:
            values.pop(name, None)
    values.update(
        {name: "fixture:monkeypatch" for name in monkeypatch_receivers}
    )
    values.update({name: "fixture:mocker" for name in mocker_receivers})

    def monkeypatch_origin(origin: str | None) -> bool:
        return bool(
            origin == "monkeypatch"
            or origin == "fixture:monkeypatch"
            or (origin or "").startswith("monkeypatch_instance:")
            or (origin or "").startswith("monkeypatch_context:")
            or (origin or "").startswith("fixture:monkeypatch_context:")
        )

    def mocker_origin(origin: str | None) -> bool:
        return origin in ("mocker", "fixture:mocker")

    def fixture_receiver_for_call(
        node: ast.Call, state: dict[str, str]
    ) -> str | None:
        callable_origin = expression_origin(node.func, state)
        if (callable_origin or "").startswith("fixture:mocker"):
            return "mocker"
        if (callable_origin or "").startswith("fixture:monkeypatch"):
            return "monkeypatch"
        if isinstance(node.func, ast.Attribute):
            receiver = expression_origin(node.func.value, state)
            if (receiver or "").startswith("fixture:mocker"):
                return "mocker"
            if (receiver or "").startswith("fixture:monkeypatch"):
                return "monkeypatch"
        return None

    def exact_imports(node: ast.AST) -> dict[str, str]:
        return _imports_at(node, imports, environments)

    def expression_origin(node: ast.AST, state: dict[str, str]) -> str | None:
        if isinstance(node, ast.NamedExpr):
            return expression_origin(node.value, state)
        if isinstance(node, ast.Name):
            origin = state.get(node.id)
            if origin is not None:
                return origin
            imported = _live_import_path(node, exact_imports(node))
            return _CALLABLE_API_PATHS.get(imported or "")
        imported = _live_import_path(node, exact_imports(node))
        if imported in _CALLABLE_API_PATHS:
            return _CALLABLE_API_PATHS[imported]
        if isinstance(node, ast.Attribute):
            base = expression_origin(node.value, state)
            if mocker_origin(base) and node.attr == "patch":
                return (
                    "fixture:mocker_patch_namespace"
                    if base == "fixture:mocker"
                    else "mocker_patch_namespace"
                )
            if base == "mock_patch" and node.attr == "object":
                return "mock_patch_object"
            if base == "mock_patch" and node.attr == "dict":
                return "mock_patch_dict"
            if base in (
                "mocker_patch_namespace",
                "fixture:mocker_patch_namespace",
            ) and node.attr == "object":
                return (
                    "fixture:mocker_patch_object"
                    if base.startswith("fixture:")
                    else "mocker_patch_object"
                )
        if isinstance(node, ast.Call):
            kind = classify_call(node, state)
            if kind == "monkeypatch_constructor":
                return f"monkeypatch_instance:{id(node)}"
            if kind == "monkeypatch_context":
                dependency = fixture_receiver_for_call(node, state)
                prefix = (
                    "fixture:monkeypatch_context:"
                    if dependency == "monkeypatch"
                    else "monkeypatch_context:"
                )
                return f"{prefix}{id(node)}"
        return None

    def classify_call(node: ast.Call, state: dict[str, str]) -> str | None:
        imported = _live_import_path(node.func, exact_imports(node))
        if imported in _CALLABLE_API_PATHS:
            return _CALLABLE_API_PATHS[imported]
        callable_origin = expression_origin(node.func, state)
        if callable_origin in {
            "builtin_setattr",
            "builtin_getattr",
            "builtin_vars",
            "operator_setitem",
            "mock_patch",
            "mock_patch_object",
            "mock_patch_dict",
            "monkeypatch_constructor",
            "mocker_patch_namespace",
            "mocker_patch_object",
            "fixture:mocker_patch_namespace",
            "fixture:mocker_patch_object",
        }:
            if callable_origin in (
                "mocker_patch_namespace",
                "fixture:mocker_patch_namespace",
            ):
                return "mocker_patch"
            if callable_origin in (
                "mocker_patch_object",
                "fixture:mocker_patch_object",
            ):
                return "mocker_patch_object"
            return callable_origin
        if not isinstance(node.func, ast.Attribute):
            return None
        receiver = expression_origin(node.func.value, state)
        if monkeypatch_origin(receiver):
            if node.func.attr in ("setattr", "set_attribute"):
                return "monkeypatch_setattr"
            if node.func.attr == "setitem":
                return "monkeypatch_setitem"
            if node.func.attr == "context":
                return "monkeypatch_context"
            if node.func.attr == "undo":
                return "monkeypatch_undo"
        if mocker_origin(receiver) and node.func.attr == "patch":
            return "mocker_patch"
        if (
            receiver
            in ("mocker_patch_namespace", "fixture:mocker_patch_namespace")
            and node.func.attr == "object"
        ):
            return "mocker_patch_object"
        return None

    def scan_expression(
        node: ast.AST,
        state: dict[str, str],
        active_contexts: dict[str, ast.With | ast.AsyncWith] | None = None,
    ) -> None:
        for candidate in ast.walk(node):
            if not isinstance(candidate, ast.Call):
                continue
            prior_values = facts.call_value_environments.get(id(candidate))
            facts.call_value_environments[id(candidate)] = (
                dict(state)
                if prior_values is None
                else merge([prior_values, state])
            )
            facts.call_argument_origins[id(candidate)] = (
                tuple(
                    expression_origin(
                        argument.value if isinstance(argument, ast.Starred) else argument,
                        state,
                    )
                    for argument in candidate.args
                ),
                tuple(
                    (keyword.arg, expression_origin(keyword.value, state))
                    for keyword in candidate.keywords
                ),
            )
            kind = classify_call(candidate, state)
            if kind is None:
                continue
            facts.call_kinds[id(candidate)] = kind
            if isinstance(candidate.func, ast.Attribute):
                receiver_origin = expression_origin(
                    candidate.func.value, state
                )
                if receiver_origin is not None:
                    facts.call_receiver_origins[id(candidate)] = (
                        receiver_origin
                    )
            dependency = fixture_receiver_for_call(candidate, state)
            if dependency is not None:
                facts.call_fixture_receivers[id(candidate)] = dependency
            if kind in ("monkeypatch_setattr", "monkeypatch_setitem"):
                receiver = (
                    expression_origin(candidate.func.value, state)
                    if isinstance(candidate.func, ast.Attribute)
                    else None
                )
                context = (active_contexts or {}).get(receiver or "")
                if context is not None:
                    facts.call_contexts[id(candidate)] = context

    def bind_target(
        target: ast.AST, origin: str | None, state: dict[str, str]
    ) -> None:
        if isinstance(target, (ast.Name, ast.arg)):
            name = target.id if isinstance(target, ast.Name) else target.arg
            if origin is None:
                state.pop(name, None)
            else:
                state[name] = origin
            return
        if isinstance(target, (ast.Tuple, ast.List)):
            for element in target.elts:
                bind_target(element, None, state)

    def bind_assignment(
        target: ast.AST, value: ast.AST, state: dict[str, str]
    ) -> None:
        """Propagate API origins through statically paired unpacking."""
        if (
            isinstance(target, (ast.Tuple, ast.List))
            and isinstance(value, (ast.Tuple, ast.List))
            and len(target.elts) == len(value.elts)
        ):
            for target_element, value_element in zip(
                target.elts, value.elts
            ):
                bind_assignment(target_element, value_element, state)
            return
        bind_target(target, expression_origin(value, state), state)

    def merge(states: list[dict[str, str]]) -> dict[str, str]:
        if not states:
            return {}
        return {
            name: origin
            for name, origin in states[0].items()
            if all(other.get(name) == origin for other in states[1:])
        }

    def process(
        statements: list[ast.stmt],
        incoming: dict[str, str],
        active_contexts: dict[str, ast.With | ast.AsyncWith] | None = None,
    ) -> dict[str, str]:
        current = dict(incoming)
        for stmt in statements:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                prior_definition = facts.definition_values.get(id(stmt))
                facts.definition_values[id(stmt)] = (
                    dict(current)
                    if prior_definition is None
                    else merge([prior_definition, current])
                )
                for decorator in stmt.decorator_list:
                    scan_expression(decorator, current, active_contexts)
                if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for default in (*stmt.args.defaults, *stmt.args.kw_defaults):
                        if default is not None:
                            scan_expression(default, current, active_contexts)
                current.pop(stmt.name, None)
                continue
            if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                for name, path in _import_bindings((stmt,), {}).items():
                    origin = _CALLABLE_API_PATHS.get(path)
                    if origin is None:
                        current.pop(name, None)
                    else:
                        current[name] = origin
                continue
            if isinstance(stmt, ast.Assign):
                scan_expression(stmt.value, current, active_contexts)
                for target in stmt.targets:
                    scan_expression(target, current, active_contexts)
                if isinstance(stmt.value, ast.NamedExpr):
                    bind_target(
                        stmt.value.target,
                        expression_origin(stmt.value.value, current),
                        current,
                    )
                for target in stmt.targets:
                    bind_assignment(target, stmt.value, current)
                continue
            if isinstance(stmt, ast.AnnAssign):
                scan_expression(stmt.target, current, active_contexts)
                if stmt.value is not None:
                    scan_expression(stmt.value, current, active_contexts)
                    origin = expression_origin(stmt.value, current)
                else:
                    origin = None
                bind_target(stmt.target, origin, current)
                continue
            if isinstance(stmt, ast.AugAssign):
                scan_expression(stmt.target, current, active_contexts)
                scan_expression(stmt.value, current, active_contexts)
                bind_target(stmt.target, None, current)
                continue
            if isinstance(stmt, ast.Delete):
                for target in stmt.targets:
                    scan_expression(target, current, active_contexts)
                    bind_target(target, None, current)
                continue
            if isinstance(stmt, ast.If):
                scan_expression(stmt.test, current, active_contexts)
                if isinstance(stmt.test, ast.NamedExpr):
                    bind_target(
                        stmt.test.target,
                        expression_origin(stmt.test.value, current),
                        current,
                    )
                truth = _static_truth(stmt.test)
                if truth is True:
                    current = process(stmt.body, current, active_contexts)
                elif truth is False:
                    current = process(stmt.orelse, current, active_contexts)
                else:
                    current = merge(
                        [
                            process(stmt.body, current, active_contexts),
                            process(stmt.orelse, current, active_contexts)
                            if stmt.orelse
                            else dict(current),
                        ]
                    )
                continue
            if isinstance(stmt, (ast.With, ast.AsyncWith)):
                entered = dict(current)
                entered_contexts = dict(active_contexts or {})
                for item in stmt.items:
                    scan_expression(item.context_expr, entered, active_contexts)
                    origin = expression_origin(item.context_expr, entered)
                    bind_target(item.optional_vars, origin, entered)
                    if (
                        origin is not None
                        and (
                            origin.startswith("monkeypatch_context:")
                            or origin.startswith("fixture:monkeypatch_context:")
                        )
                    ):
                        entered_contexts[origin] = stmt
                current = process(
                    stmt.body,
                    entered,
                    entered_contexts,
                )
                continue
            if isinstance(stmt, (ast.For, ast.AsyncFor, ast.While)):
                if isinstance(stmt, (ast.For, ast.AsyncFor)):
                    scan_expression(stmt.iter, current, active_contexts)
                    entered = dict(current)
                    bind_target(stmt.target, None, entered)
                else:
                    scan_expression(stmt.test, current, active_contexts)
                    if isinstance(stmt.test, ast.NamedExpr):
                        bind_target(
                            stmt.test.target,
                            expression_origin(stmt.test.value, current),
                            current,
                        )
                    entered = dict(current)
                body_end = process(stmt.body, entered, active_contexts)
                current = merge([current, body_end])
                current = process(stmt.orelse, current, active_contexts)
                continue
            if isinstance(stmt, (ast.Try, ast.TryStar)):
                normal = process(stmt.body, current, active_contexts)
                normal = process(stmt.orelse, normal, active_contexts)
                paths = [normal]
                for handler in stmt.handlers:
                    handler_state = dict(current)
                    if handler.name:
                        handler_state.pop(handler.name, None)
                    paths.append(
                        process(handler.body, handler_state, active_contexts)
                    )
                current = process(
                    stmt.finalbody, merge(paths), active_contexts
                )
                continue
            if isinstance(stmt, ast.Match):
                scan_expression(stmt.subject, current, active_contexts)
                paths = [dict(current)]
                for case in stmt.cases:
                    paths.append(
                        process(case.body, current, active_contexts)
                    )
                current = merge(paths)
                continue
            scan_expression(stmt, current, active_contexts)
            if (
                isinstance(stmt, ast.Expr)
                and isinstance(stmt.value, ast.NamedExpr)
            ):
                bind_target(
                    stmt.value.target,
                    expression_origin(stmt.value.value, current),
                    current,
                )
        return current

    if isinstance(root, (ast.FunctionDef, ast.AsyncFunctionDef)):
        for decorator in root.decorator_list:
            scan_expression(decorator, definition_environment)
        for default in (*root.args.defaults, *root.args.kw_defaults):
            if default is not None:
                scan_expression(default, definition_environment)
        # Defaults execute in the enclosing definition-time environment, but
        # their resulting objects are the parameter values seen by the body.
        # Carry only exact supported API origins; ordinary/defaulted fixture
        # lookalikes remain unknown.
        runtime_values = dict(values)
        positional = root.args.posonlyargs + root.args.args
        for argument, default in zip(
            positional[-len(root.args.defaults) :], root.args.defaults
        ):
            bind_target(
                argument,
                expression_origin(default, definition_environment),
                runtime_values,
            )
        for argument, default in zip(
            root.args.kwonlyargs, root.args.kw_defaults
        ):
            if default is not None:
                bind_target(
                    argument,
                    expression_origin(default, definition_environment),
                    runtime_values,
                )
        for parameter, origin in (parameter_values or {}).items():
            if origin is None:
                runtime_values.pop(parameter, None)
            else:
                runtime_values[parameter] = origin
        values = runtime_values
    if isinstance(root, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        facts.final_values = process(root.body, values)
    elif isinstance(root, ast.stmt):
        facts.final_values = process([root], values)
    else:
        scan_expression(root, values)
        facts.final_values = dict(values)
    return facts


def _patch_call_target(
    node: ast.Call, dotted: str | None
) -> tuple[str, str] | None:
    """The frozen IR-v1 patch spelling, retained byte-for-byte in spirit.

    Rich stand-in analysis lives beside this helper.  `UnitSide.patches` and
    TEST_PATCHES_SUBJECT allowlist fingerprints historically used this local
    spelling, so canonicalising it would be an unannounced schema/identity
    migration.
    """
    if not dotted or not node.args:
        return None
    parts = dotted.split(".")
    tail = parts[-1]
    if tail in _PATCH_CALLS:
        if len(parts) < 2:
            return None
    elif tail == "object":
        if len(parts) < 2 or parts[-2] != "patch":
            return None
    elif tail != "patch":
        return None

    first = node.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        target = first.value
        if "." not in target:
            return None
        return (target, target.rsplit(".", 1)[1])
    if len(node.args) < 2:
        return None
    attr = node.args[1]
    if not (isinstance(attr, ast.Constant) and isinstance(attr.value, str)):
        return None
    base = _dotted(first)
    if base is None:
        return None
    return (f"{base}.{attr.value}", attr.value)


_STANDIN_RAW_CALL_RE = re.compile(
    # Bare tokens intentionally include import declarations: once
    # ``patch``/``setitem`` is imported as an arbitrary alias, source text at
    # the call site no longer contains the original verb. False positives
    # only enable the structured pass; omitting the import token would turn
    # the raw performance gate into a detection boundary.
    r"(?:\b(?:setattr|setitem|set_attribute|vars|patch)\b|"
    r"\bsys\s*\.\s*modules\b|__dict__)"
)
# Broad on purpose: this is only an enable gate. Matching every genuine
# assignment, including a parenthesised target split across lines, is more
# important than avoiding harmless structured passes for defaults/keywords.
_STANDIN_RAW_ASSIGN_RE = re.compile(r"(?::=|(?<![=!<>:])=(?!=))")
_SCOPE_IMPORT_FLOW_RE = re.compile(
    r"\b(?:del|for|with|except|match|case|global|nonlocal)\b|"
    r"(?::=|(?:\*\*|//|<<|>>|[+\-*/%@&|^])=)"
)


def _raw_may_contain_standin(raw: str) -> bool:
    """Source-only conservative gate for the expensive lifetime passes.

    It runs before AST parsing.  Calls/mappings have distinctive tokens;
    direct attribute, unpacking, and imported-name assignments take the
    assignment arm.  A false positive only enables the structured pass, while
    the intentionally broad assignment pattern keeps false negatives out of
    the security boundary.
    """
    return bool(
        _STANDIN_RAW_CALL_RE.search(raw)
        or ("=" in raw and _STANDIN_RAW_ASSIGN_RE.search(raw))
    )


def _raw_unit_may_contain_standin(
    raw: str,
    imports: dict[str, str],
    assigned_call_aliases: Collection[str] = (),
) -> bool:
    """Raw unit gate, including verbs imported under arbitrary aliases."""
    if _raw_may_contain_standin(raw):
        return True
    aliases = set(assigned_call_aliases) | {
        local
        for local, target in imports.items()
        if target.rsplit(".", 1)[-1]
        in {*_SETATTR_CALLS, "setitem", "patch"}
    }
    # Do not reproduce Python's callable grammar in this performance gate.
    # Parenthesisation and explicit continuation admit indefinitely many
    # equivalent spellings; seeing a known imported verb anywhere in the
    # unit is the conservative proof that the structured AST pass is needed.
    # A false positive only costs that pass, while a false negative suppresses
    # the finding altogether.
    return any(
        re.search(rf"\b{re.escape(alias)}\b", raw)
        for alias in aliases
    )


def _scope_needs_import_environments(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    raw: str,
    base: dict[str, str],
) -> bool:
    """Conservative raw gate for the assertion-position import walk."""
    if re.search(r"\b(?:from|import)\b", raw):
        return True
    if not base:
        return False
    args = func.args
    parameters = {
        arg.arg
        for arg in (
            args.posonlyargs
            + args.args
            + args.kwonlyargs
            + ([args.vararg] if args.vararg is not None else [])
            + ([args.kwarg] if args.kwarg is not None else [])
        )
    }
    if parameters.intersection(base):
        return True
    if _SCOPE_IMPORT_FLOW_RE.search(raw):
        return True
    # A nested definition binds its name in this lexical scope. Match only
    # imported names, so the root test definition itself stays on the fast
    # path and ordinary helpers do not defeat the gate.
    return any(
        re.search(
            rf"\b(?:async\s+def|def|class)\s+{re.escape(name)}\b",
            raw,
        )
        for name in base
    )


def _standin_import_bindings(tree: ast.Module) -> dict[str, str]:
    """Definitely live module import locals -> canonical targets."""
    _environments, final = _scope_import_environments(tree, {})
    return final


def _import_bindings(
    nodes, base: dict[str, str] | None = None
) -> dict[str, str]:
    out: dict[str, str] = dict(base or {})
    for stmt in nodes:
        if isinstance(stmt, ast.Import):
            for alias in stmt.names:
                local = alias.asname or alias.name.split(".", 1)[0]
                out[local] = alias.name if alias.asname else local
        elif isinstance(stmt, ast.ImportFrom):
            module = "." * stmt.level + (stmt.module or "")
            for alias in stmt.names:
                if alias.name == "*":
                    continue
                local = alias.asname or alias.name
                if stmt.module:
                    out[local] = f"{module}.{alias.name}"
                else:
                    out[local] = f"{module}{alias.name}"
    return {name: out[name] for name in sorted(out)}


def _scope_import_bindings(
    root: ast.AST, base: dict[str, str]
) -> dict[str, str]:
    _environments, final = _scope_import_environments(root, base)
    return final


def _bound_target_names(target: ast.AST | None) -> set[str]:
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, ast.Starred):
        return _bound_target_names(target.value)
    if isinstance(target, (ast.Tuple, ast.List)):
        return {
            name
            for element in target.elts
            for name in _bound_target_names(element)
        }
    return set()


def _pattern_bound_names(pattern: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(pattern):
        if isinstance(node, ast.MatchAs) and node.name:
            names.add(node.name)
        elif isinstance(node, ast.MatchStar) and node.name:
            names.add(node.name)
        elif isinstance(node, ast.MatchMapping) and node.rest:
            names.add(node.rest)
    return names


def _lexical_scope_names(root: ast.AST) -> tuple[set[str], set[str], set[str]]:
    """(locals, globals, nonlocals) for one Python lexical scope."""
    local: set[str] = set()
    global_names: set[str] = set()
    nonlocal_names: set[str] = set()
    if isinstance(root, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        args = root.args
        local.update(
            arg.arg
            for arg in (
                args.posonlyargs
                + args.args
                + args.kwonlyargs
                + ([args.vararg] if args.vararg is not None else [])
                + ([args.kwarg] if args.kwarg is not None else [])
            )
        )

    def visit(node: ast.AST, *, is_root: bool = False) -> None:
        if not is_root and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            local.add(node.name)
            return
        if not is_root and isinstance(node, ast.Lambda):
            return
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            # Comprehension targets live in their implicit scope.  NamedExpr
            # leakage is a deliberately conservative residual.
            return
        if isinstance(node, ast.Global):
            global_names.update(node.names)
            return
        if isinstance(node, ast.Nonlocal):
            nonlocal_names.update(node.names)
            return
        if isinstance(node, ast.Import):
            local.update(alias.asname or alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            local.update(
                alias.asname or alias.name
                for alias in node.names
                if alias.name != "*"
            )
        elif isinstance(node, ast.ExceptHandler) and node.name:
            local.add(node.name)
        elif isinstance(node, ast.Match):
            for case in node.cases:
                local.update(_pattern_bound_names(case.pattern))
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            local.add(node.id)
        for child in ast.iter_child_nodes(node):
            visit(child)

    visit(root, is_root=True)
    local.difference_update(global_names | nonlocal_names)
    return local, global_names, nonlocal_names


def _scope_import_environments(
    root: ast.AST,
    base: dict[str, str],
    *,
    definition_base: dict[str, str] | None = None,
) -> tuple[dict[int, dict[str, str]], dict[str, str]]:
    """Import bindings at each executable node and after the scope.

    Python makes every assigned/imported function name lexical from entry, but
    the value bound to it still changes in statement order.  The per-node map
    is therefore required: a parameter/local assignment must not borrow a
    module import, while an import followed by a live oracle must remain
    visible even if an unrelated rebind occurs later.  Unknown branches merge
    only bindings identical on every path, failing toward silence.
    """
    environments: dict[int, dict[str, str]] = {}
    outer = dict(base if definition_base is None else definition_base)
    initial = dict(base)
    local, _globals, nonlocals = _lexical_scope_names(root)
    if isinstance(root, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        for name in local | nonlocals:
            initial.pop(name, None)

    def stamp(node: ast.AST, env: dict[str, str]) -> None:
        environments[id(node)] = dict(env)
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                continue
            stamp(child, env)

    def merge(paths: list[dict[str, str]]) -> dict[str, str]:
        if not paths:
            return {}
        return {
            name: value
            for name, value in paths[0].items()
            if all(path.get(name) == value for path in paths[1:])
        }

    def drop(env: dict[str, str], names: set[str]) -> dict[str, str]:
        out = dict(env)
        for name in names:
            out.pop(name, None)
        return out

    if isinstance(root, (ast.FunctionDef, ast.AsyncFunctionDef)):
        # Decorators and defaults execute in the enclosing scope before the
        # function's lexical locals exist. A later local named ``mock`` must
        # not make an already-evaluated ``@mock.patch`` disappear.
        for decorator in root.decorator_list:
            stamp(decorator, outer)
        for value in (*root.args.defaults, *root.args.kw_defaults):
            if value is not None:
                stamp(value, outer)

    def process(statements, incoming: dict[str, str]) -> dict[str, str]:
        current = dict(incoming)
        for stmt in statements:
            environments[id(stmt)] = dict(current)
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                for decorator in stmt.decorator_list:
                    stamp(decorator, current)
                if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for value in (*stmt.args.defaults, *stmt.args.kw_defaults):
                        if value is not None:
                            stamp(value, current)
                current.pop(stmt.name, None)
                continue

            stamp(stmt, current)
            if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                current = _import_bindings((stmt,), current)
            elif isinstance(stmt, ast.Assign):
                current = drop(
                    current,
                    {
                        name
                        for target in stmt.targets
                        for name in _bound_target_names(target)
                    },
                )
            elif isinstance(stmt, (ast.AnnAssign, ast.AugAssign)):
                current = drop(current, _bound_target_names(stmt.target))
            elif isinstance(stmt, ast.Delete):
                current = drop(
                    current,
                    {name for target in stmt.targets for name in _bound_target_names(target)},
                )
            elif isinstance(stmt, ast.If):
                truth = _static_truth(stmt.test)
                if truth is True:
                    current = process(stmt.body, current)
                elif truth is False:
                    current = process(stmt.orelse, current)
                else:
                    current = merge(
                        [
                            process(stmt.body, dict(current)),
                            process(stmt.orelse, dict(current)) if stmt.orelse else dict(current),
                        ]
                    )
            elif isinstance(stmt, (ast.For, ast.AsyncFor)):
                entered = drop(current, _bound_target_names(stmt.target))
                body_end = process(stmt.body, entered)
                current = merge([current, body_end])
                current = process(stmt.orelse, current)
            elif isinstance(stmt, ast.While):
                body_end = process(stmt.body, dict(current))
                current = merge([current, body_end])
                current = process(stmt.orelse, current)
            elif isinstance(stmt, (ast.With, ast.AsyncWith)):
                entered = dict(current)
                for item in stmt.items:
                    entered = drop(entered, _bound_target_names(item.optional_vars))
                current = process(stmt.body, entered)
            elif isinstance(stmt, (ast.Try, ast.TryStar)):
                normal = process(stmt.body, dict(current))
                normal = process(stmt.orelse, normal)
                paths = [normal]
                for handler in stmt.handlers:
                    handler_env = dict(current)
                    if handler.name:
                        handler_env.pop(handler.name, None)
                    handler_end = process(handler.body, handler_env)
                    if handler.name:
                        handler_end.pop(handler.name, None)
                    paths.append(handler_end)
                current = process(stmt.finalbody, merge(paths))
            elif isinstance(stmt, ast.Match):
                paths = [dict(current)]
                for case in stmt.cases:
                    case_env = drop(current, _pattern_bound_names(case.pattern))
                    paths.append(process(case.body, case_env))
                current = merge(paths)

            # Assignment expressions bind for following statements.  Their
            # within-expression evaluation order is left as a conservative
            # residual; removing the import avoids a false ownership claim.
            named = {
                child.target.id
                for child in ast.walk(stmt)
                if isinstance(child, ast.NamedExpr)
                and isinstance(child.target, ast.Name)
            }
            if named:
                current = drop(current, named)
        return {name: current[name] for name in sorted(current)}

    if isinstance(
        root,
        (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
    ):
        body = root.body
    elif isinstance(root, ast.stmt):
        # Class-body collection passes an individual compound member here.
        # Treating ``If.body`` as a whole scope silently discarded its live
        # ``else`` (and likewise Try handlers / Match cases).  Process the
        # compound statement itself so its ordinary branch semantics apply.
        body = [root]
    else:
        stamp(root, initial)
        body = []
    final = process(body, initial)
    environments[id(root)] = dict(initial)
    return environments, final


def _native_import_rows(
    stmt: ast.Import | ast.ImportFrom,
    *,
    include_dotted: bool = False,
) -> dict[str, tuple[str, str, str, int, int]]:
    """Bindings established by one runtime native import statement.

    ``binding`` mirrors the canonical import map while ``loaded`` records the
    module Python must freshly resolve. Dotted ``import app.billing`` is not
    positive evidence here: a stale ``app.billing`` attribute on the already
    imported parent package can win even after ``sys.modules['app.billing']``
    changes. ``from app.billing import name`` is narrow enough because its
    source module itself is the replaced entry; ``from app import billing``
    intentionally records only ``app`` and therefore does not claim the child
    replacement reached the binding.
    """
    position = (
        getattr(stmt, "lineno", 0) or 0,
        getattr(stmt, "col_offset", 0) or 0,
    )
    canonical = _import_bindings((stmt,), {})
    rows: dict[str, tuple[str, str, str, int, int]] = {}
    if isinstance(stmt, ast.Import):
        for alias in stmt.names:
            if "." in alias.name and not include_dotted:
                continue
            local = alias.asname or alias.name.split(".", 1)[0]
            binding = canonical.get(local)
            if binding is not None:
                rows[local] = (
                    local,
                    binding,
                    alias.name,
                    *position,
                )
    else:
        for alias in stmt.names:
            if alias.name == "*":
                continue
            local = alias.asname or alias.name
            binding = canonical.get(local)
            if binding is not None:
                source_module = ("." * stmt.level) + (stmt.module or "")
                if not source_module:
                    continue
                rows[local] = (
                    local,
                    binding,
                    source_module,
                    *position,
                )
    return rows


def _scope_runtime_import_environments(
    root: ast.Module | ast.FunctionDef | ast.AsyncFunctionDef,
    imports: dict[str, str] | None = None,
    import_environments: dict[int, dict[str, str]] | None = None,
    *,
    include_dotted: bool = False,
    initial_rows: tuple[
        tuple[str, str, str, int, int], ...
    ] = (),
) -> dict[int, tuple[tuple[str, str, str, int, int], ...]]:
    """Definitely fresh function-local imports at each AST position.

    Module imports deliberately do not seed this map: they ran during
    collection and therefore cannot prove that a later fixture/test-body
    ``sys.modules`` swap affects the oracle. Unknown control-flow joins retain
    a row only when every path has the same fresh origin.  A literal
    ``importlib.import_module``/``sys.modules[...]`` assignment is also a
    fresh capture; its empty ``binding`` field means liveness is carried by
    this flow map rather than by the ordinary import environment. The module
    origin pass reuses this walker with ``include_dotted=True`` and reads only
    its final, non-empty native binding rows.
    """
    environments: dict[
        int, tuple[tuple[str, str, str, int, int], ...]
    ] = {}

    def freeze(rows: dict[str, tuple[str, str, str, int, int]]):
        return tuple(rows[name] for name in sorted(rows))

    def stamp(
        node: ast.AST,
        rows: dict[str, tuple[str, str, str, int, int]],
    ) -> None:
        environments[id(node)] = freeze(rows)
        for child in ast.iter_child_nodes(node):
            if isinstance(
                child,
                (
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                    ast.ClassDef,
                    ast.Lambda,
                ),
            ):
                continue
            stamp(child, rows)

    def merge(
        paths: list[dict[str, tuple[str, str, str, int, int]]],
    ) -> dict[str, tuple[str, str, str, int, int]]:
        if not paths:
            return {}
        return {
            name: row
            for name, row in paths[0].items()
            if all(path.get(name) == row for path in paths[1:])
        }

    def drop(
        rows: dict[str, tuple[str, str, str, int, int]],
        names: set[str],
    ) -> dict[str, tuple[str, str, str, int, int]]:
        kept = dict(rows)
        for name in names:
            kept.pop(name, None)
        return kept

    def process(
        statements: list[ast.stmt],
        incoming: dict[str, tuple[str, str, str, int, int]],
        conditional: bool = False,
    ) -> dict[str, tuple[str, str, str, int, int]]:
        current = dict(incoming)
        for stmt in statements:
            environments[id(stmt)] = freeze(current)
            if isinstance(
                stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            ):
                current.pop(stmt.name, None)
                continue
            stamp(stmt, current)
            if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                # A conditional re-import invalidates an earlier definite
                # origin even when it cannot contribute a new definite row.
                # Dropping every Python binding also covers dotted imports,
                # which runtime sys.modules evidence intentionally omits.
                current = drop(
                    current,
                    set(_import_bindings((stmt,), {})),
                )
                if not conditional:
                    current.update(
                        _native_import_rows(
                            stmt,
                            include_dotted=include_dotted,
                        )
                    )
            elif isinstance(stmt, ast.Assign):
                assigned = {
                    name
                    for target in stmt.targets
                    for name in _bound_target_names(target)
                }
                propagated = (
                    current.get(stmt.value.id)
                    if isinstance(stmt.value, ast.Name)
                    else None
                )
                loaded = None
                if isinstance(stmt.value, (ast.Call, ast.Subscript)):
                    loaded = _resolved_module_expr(
                        stmt.value,
                        _imports_at(
                            stmt,
                            imports or {},
                            import_environments,
                        ),
                    )
                current = drop(current, assigned)
                if not conditional and (propagated is not None or loaded):
                    position = (
                        getattr(stmt.value, "lineno", 0) or 0,
                        getattr(stmt.value, "col_offset", 0) or 0,
                    )
                    for name in assigned:
                        current[name] = (
                            (name, "", loaded, *position)
                            if loaded is not None
                            else (name, *propagated[1:])
                        )
            elif isinstance(stmt, (ast.AnnAssign, ast.AugAssign)):
                assigned = _bound_target_names(stmt.target)
                propagated = (
                    current.get(stmt.value.id)
                    if isinstance(stmt, ast.AnnAssign)
                    and isinstance(stmt.value, ast.Name)
                    else None
                )
                loaded = None
                if (
                    isinstance(stmt, ast.AnnAssign)
                    and isinstance(stmt.value, (ast.Call, ast.Subscript))
                ):
                    loaded = _resolved_module_expr(
                        stmt.value,
                        _imports_at(
                            stmt,
                            imports or {},
                            import_environments,
                        ),
                    )
                current = drop(current, assigned)
                if not conditional and (propagated is not None or loaded):
                    position_node = stmt.value
                    position = (
                        getattr(position_node, "lineno", 0) or 0,
                        getattr(position_node, "col_offset", 0) or 0,
                    )
                    for name in assigned:
                        current[name] = (
                            (name, "", loaded, *position)
                            if loaded is not None
                            else (name, *propagated[1:])
                        )
            elif isinstance(stmt, ast.Delete):
                current = drop(
                    current,
                    {
                        name
                        for target in stmt.targets
                        for name in _bound_target_names(target)
                    },
                )
            elif isinstance(stmt, ast.If):
                truth = _static_truth(stmt.test)
                if truth is True:
                    current = process(stmt.body, current, conditional)
                elif truth is False:
                    current = process(stmt.orelse, current, conditional)
                else:
                    current = merge(
                        [
                            process(stmt.body, dict(current), True),
                            (
                                process(stmt.orelse, dict(current), True)
                                if stmt.orelse
                                else dict(current)
                            ),
                        ]
                    )
            elif isinstance(stmt, (ast.For, ast.AsyncFor)):
                entered = drop(current, _bound_target_names(stmt.target))
                body_end = process(stmt.body, entered, True)
                current = merge([current, body_end])
                current = process(stmt.orelse, current, True)
            elif isinstance(stmt, ast.While):
                body_end = process(stmt.body, dict(current), True)
                current = merge([current, body_end])
                current = process(stmt.orelse, current, True)
            elif isinstance(stmt, (ast.With, ast.AsyncWith)):
                entered = dict(current)
                for item in stmt.items:
                    entered = drop(
                        entered, _bound_target_names(item.optional_vars)
                    )
                current = process(stmt.body, entered, conditional)
            elif isinstance(stmt, (ast.Try, ast.TryStar)):
                normal = process(stmt.body, dict(current), True)
                normal = process(stmt.orelse, normal, True)
                paths = [normal]
                for handler in stmt.handlers:
                    handler_env = dict(current)
                    if handler.name:
                        handler_env.pop(handler.name, None)
                    handler_end = process(handler.body, handler_env, True)
                    if handler.name:
                        handler_end.pop(handler.name, None)
                    paths.append(handler_end)
                current = process(
                    stmt.finalbody, merge(paths), conditional
                )
            elif isinstance(stmt, ast.Match):
                paths = [dict(current)]
                for case in stmt.cases:
                    case_env = drop(
                        current, _pattern_bound_names(case.pattern)
                    )
                    paths.append(process(case.body, case_env, True))
                current = merge(paths)

            named = {
                child.target.id
                for child in ast.walk(stmt)
                if isinstance(child, ast.NamedExpr)
                and isinstance(child.target, ast.Name)
            }
            if named:
                current = drop(current, named)
        return current

    initial = {row[0]: row for row in initial_rows}
    if isinstance(root, (ast.FunctionDef, ast.AsyncFunctionDef)) and initial:
        local, globals_, _nonlocals = _lexical_scope_names(root)
        initial = drop(initial, local | globals_)
    final = process(root.body, initial)
    # Function callers need the entry state at the root; module-origin
    # collection uses the same flow walker and reads its final state here.
    environments[id(root)] = (
        freeze(final) if isinstance(root, ast.Module) else freeze(initial)
    )
    return environments


def _module_native_import_origins(
    tree: ast.Module,
    live_imports: Mapping[str, str],
) -> tuple[tuple[str, str, str, int, int], ...]:
    """Final definite collection-time native import origins.

    Canonical import liveness and origin provenance intentionally remain two
    checks.  The shared control-flow walker supplies the exact statement that
    established a binding; the ordinary module import map rejects propagated
    aliases and any later assignment/delete that stopped being an import.
    """
    if not live_imports:
        return ()
    environments = _scope_runtime_import_environments(
        tree,
        dict(live_imports),
        include_dotted=True,
    )
    return tuple(
        row
        for row in environments.get(id(tree), ())
        if row[1] and live_imports.get(row[0]) == row[1]
    )


def _visible_module_import_origins(
    origins: tuple[tuple[str, str, str, int, int], ...],
    live_imports: Mapping[str, str],
    runtime_imports: tuple[tuple[str, str, str, int, int], ...],
) -> tuple[tuple[str, str, str, int, int], ...]:
    """Collection-time origins still visible at one function oracle.

    The canonical per-node environment removes lexical shadows and ordinary
    rebindings.  A same-spelled function-local import can leave that canonical
    target unchanged, so its separate runtime provenance must explicitly
    displace the collection-time row.
    """
    runtime_locals = {row[0] for row in runtime_imports}
    return tuple(
        row
        for row in origins
        if row[0] not in runtime_locals
        and live_imports.get(row[0]) == row[1]
    )


def _module_local_bindings(
    tree: ast.Module,
    definition_imports: dict[int, dict[str, str]] | None = None,
) -> dict[str, str]:
    """Final straight-line module bindings that are not imports.

    The value is a canonical provider when the assignment is tied to an
    imported object, ``"<fixture>"`` for a same-file fixture definition, and
    otherwise ``""``.  This small internal channel lets the
    aligned sides distinguish ``from app import f`` from a later ``f = fake``
    even when the import line itself was removed. Statically chosen branches
    participate; path-dependent writes stay out so uncertainty cannot become
    positive ownership proof.
    """
    environments, imports = _scope_import_environments(tree, {})
    local: dict[str, str] = {}

    def bind(target: ast.AST, value: ast.AST | None, env: dict[str, str]) -> None:
        if (
            isinstance(target, (ast.Tuple, ast.List))
            and isinstance(value, (ast.Tuple, ast.List))
            and len(target.elts) == len(value.elts)
        ):
            for target_element, value_element in zip(target.elts, value.elts):
                bind(target_element, value_element, env)
            return
        provider = _resolved_value_identity(value, env) if value is not None else None
        for name in _bound_target_names(target):
            local[name] = provider or ""

    for stmt in _definite_module_statements(tree.body):
        env = _imports_at(stmt, imports, environments)
        if isinstance(stmt, (ast.Import, ast.ImportFrom)):
            for name in _import_bindings((stmt,)):
                local.pop(name, None)
        elif isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                bind(target, stmt.value, env)
        elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
            bind(stmt.target, stmt.value, env)
        elif isinstance(stmt, ast.AugAssign):
            bind(stmt.target, None, env)
        elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            local[stmt.name] = ""
        elif isinstance(stmt, ast.Delete):
            for target in stmt.targets:
                for name in _bound_target_names(target):
                    local.pop(name, None)
    # Pytest discovers fixture metadata on the final module attribute, not at
    # the textual decorator alone.  Reuse the callable final-binding join so a
    # later carrier rebind/import/delete revokes the proof, while a literal
    # exported ``name=`` remains available even though it is not a Python
    # module variable.
    for carrier, node in _module_callable_scopes(tree).items():
        exact = (definition_imports or {}).get(id(node))
        fixture_name = _fixture_public_name(node, exact)
        if fixture_name is None:
            continue
        local[fixture_name] = "<fixture>"
        if fixture_name == carrier:
            local[carrier] = "<fixture>"
    return {name: local[name] for name in sorted(local)}


def _definite_module_statements(statements):
    """Module statements reached through only statically chosen branches."""
    for stmt in statements:
        yield stmt
        if not isinstance(stmt, ast.If):
            continue
        truth = _static_truth(stmt.test)
        if truth is True:
            yield from _definite_module_statements(stmt.body)
        elif truth is False:
            yield from _definite_module_statements(stmt.orelse)


def _module_imported_after_install(
    tree: ast.Module, install: StandinInstall
) -> bool:
    """A definite module import follows a sys.modules replacement."""
    for stmt in _definite_module_statements(tree.body):
        position = (
            getattr(stmt, "lineno", 0) or 0,
            getattr(stmt, "col_offset", 0) or 0,
        )
        if position <= install.position:
            continue
        if isinstance(stmt, ast.Import) and any(
            "." not in alias.name and alias.name == install.target
            for alias in stmt.names
        ):
            return True
        if isinstance(stmt, ast.ImportFrom):
            source_module = ("." * stmt.level) + (stmt.module or "")
            if source_module == install.target:
                return True
    return False


def _string_literal(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _valid_module_target(value: str, *, allow_relative: bool = True) -> bool:
    """Whether a canonical import/module target is structurally safe.

    Python syntax already validates ordinary Import nodes; string-based patch
    and importlib/sys.modules forms are attacker-controlled.  Reject slashes,
    drives, traversal, empty components, and non-identifiers before a target
    can be turned into a repository ownership path.
    """
    if not value or "\x00" in value or "/" in value or "\\" in value or ":" in value:
        return False
    stripped = value.lstrip(".")
    if not stripped or (stripped != value and not allow_relative):
        return False
    return all(
        part.isidentifier() and not keyword.iskeyword(part)
        for part in stripped.split(".")
    )


def _live_import_path(node: ast.AST, imports: dict[str, str]) -> str | None:
    """Resolve a dotted expression only through its live imported root.

    ``_canonical_import_path`` deliberately preserves an unresolved spelling
    for syntax families where a bare conventional name is useful.  Stand-in
    ownership cannot use that fallback: a parameter or local named ``sys`` or
    ``importlib`` is not the corresponding standard-library module.  The
    position-keyed import environment is therefore positive evidence here.
    """
    dotted = _dotted(node)
    if dotted is None:
        return None
    root, dot, suffix = dotted.partition(".")
    source = imports.get(root)
    if source is None:
        return None
    return source + (dot + suffix if dot else "")


def _resolved_module_expr(node: ast.AST, imports: dict[str, str]) -> str | None:
    """Resolve only expressions structurally tied to an imported module."""
    dotted = _dotted(node)
    if dotted:
        if dotted == "request.module" or dotted.startswith("request.module."):
            return dotted
        root, dot, suffix = dotted.partition(".")
        source = imports.get(root)
        if source is not None:
            resolved = source + (dot + suffix if dot else "")
            return resolved if _valid_module_target(resolved) else None
    if isinstance(node, ast.Call):
        call = _live_import_path(node.func, imports)
        if call == "importlib.import_module" and node.args:
            literal = _string_literal(node.args[0])
            return (
                literal
                if literal is not None and _valid_module_target(literal)
                else None
            )
    if (
        isinstance(node, ast.Subscript)
        and _live_import_path(node.value, imports) == "sys.modules"
    ):
        literal = _string_literal(node.slice)
        return (
            literal
            if literal is not None
            and _valid_module_target(literal, allow_relative=False)
            else None
        )
    return None


def _mapping_module(
    node: ast.AST,
    imports: dict[str, str],
    api_facts: _StandinApiFacts | None = None,
) -> tuple[str, str] | None:
    """Return (kind, module) for a supported module mapping expression."""
    if _live_import_path(node, imports) == "sys.modules":
        return ("module", "sys.modules")
    if (
        isinstance(node, ast.Call)
        and _standin_call_kind(node, imports, api_facts) == "builtin_vars"
        and node.args
    ):
        module = _resolved_module_expr(node.args[0], imports)
        if module is not None:
            return ("attribute", module)
    if isinstance(node, ast.Attribute) and node.attr == "__dict__":
        module = _resolved_module_expr(node.value, imports)
        if module is not None:
            return ("attribute", module)
    return None


def _direct_install(path: str) -> tuple[str, str, str] | None:
    path = path.strip()
    if "." not in path or not _valid_module_target(path, allow_relative=False):
        return None
    return (path, path.rsplit(".", 1)[1], "attribute")


def _lvalue_install(
    node: ast.AST,
    imports: dict[str, str],
    api_facts: _StandinApiFacts | None = None,
) -> tuple[str, str, str] | None:
    """A structured assignment target -> canonical install identity."""
    if isinstance(node, ast.Name):
        # Only a binding live immediately before the write is replaced.  An
        # outer import hidden by a parameter/function-local name is not an
        # origin: borrowing it here turns ordinary local setup into a patch.
        # Removed-import replacements are compared across aligned sides in
        # ``new_unit_standin_installs`` instead.
        target = imports.get(node.id)
        if (
            target is None
            or "." not in target.lstrip(".")
            or not _valid_module_target(target)
        ):
            return None
        return (target, node.id, "binding")
    if isinstance(node, ast.Attribute):
        module = _resolved_module_expr(node.value, imports)
        if module is None:
            return None
        target = f"{module}.{node.attr}"
        return (
            (target, node.attr, "attribute")
            if _valid_module_target(target)
            else None
        )
    if isinstance(node, ast.Subscript):
        mapped = _mapping_module(node.value, imports, api_facts)
        key = _string_literal(node.slice)
        if mapped is None or key is None:
            return None
        kind, module = mapped
        if kind == "module":
            return (
                (key, "*", "module")
                if _valid_module_target(key, allow_relative=False)
                else None
            )
        if not key.isidentifier():
            return None
        return (f"{module}.{key}", key, "attribute")
    return None


def _lvalue_installs(
    node: ast.AST,
    imports: dict[str, str],
    api_facts: _StandinApiFacts | None = None,
) -> tuple[tuple[str, str, str], ...]:
    if isinstance(node, (ast.Tuple, ast.List)):
        return tuple(
            install
            for element in node.elts
            for install in _lvalue_installs(element, imports, api_facts)
        )
    install = _lvalue_install(node, imports, api_facts)
    return (install,) if install is not None else ()


def _assignment_installs(
    target: ast.AST,
    value: ast.AST | None,
    imports: dict[str, str],
    api_facts: _StandinApiFacts | None = None,
) -> tuple[tuple[str, str, str], ...]:
    """Assignment targets paired to values where unpacking makes that legal."""
    if (
        isinstance(target, (ast.Tuple, ast.List))
        and isinstance(value, (ast.Tuple, ast.List))
        and len(target.elts) == len(value.elts)
    ):
        return tuple(
            install
            for target_element, value_element in zip(target.elts, value.elts)
            for install in _assignment_installs(
                target_element,
                value_element,
                imports,
                api_facts,
            )
        )
    return tuple(
        kept
        for install in _lvalue_installs(target, imports, api_facts)
        if (
            kept := _not_self_install(
                install, value, imports, api_facts
            )
        )
        is not None
    )


def _standin_call_argument(
    node: ast.Call, position: int, *keyword_names: str
) -> ast.AST | None:
    if position < len(node.args):
        # Supplying the same argument positionally and by keyword is not a
        # legal invocation; do not manufacture a semantic call from it.
        if any(keyword.arg in keyword_names for keyword in node.keywords):
            return None
        return node.args[position]
    matches = [
        keyword.value
        for keyword in node.keywords
        if keyword.arg in keyword_names
    ]
    return matches[0] if len(matches) == 1 else None


def _standin_call_kind(
    node: ast.AST,
    imports: dict[str, str],
    api_facts: _StandinApiFacts | None,
) -> str | None:
    if not isinstance(node, ast.Call):
        return None
    if api_facts is not None:
        return api_facts.call_kinds.get(id(node))
    imported = _live_import_path(node.func, imports)
    if imported in _CALLABLE_API_PATHS:
        return _CALLABLE_API_PATHS[imported]
    if isinstance(node.func, ast.Name) and node.func.id in (
        "setattr",
        "getattr",
        "vars",
    ):
        return f"builtin_{node.func.id}"
    return None


def _resolved_value_identity(
    node: ast.AST,
    imports: dict[str, str],
    api_facts: _StandinApiFacts | None = None,
) -> str | None:
    """Canonical identity used only to reject semantic self-assignment."""
    resolved = _resolved_module_expr(node, imports)
    if resolved is not None:
        return resolved
    if (
        isinstance(node, ast.Call)
        and _standin_call_kind(node, imports, api_facts)
        == "builtin_getattr"
        and len(node.args) >= 2
    ):
        module = _resolved_module_expr(node.args[0], imports)
        attr = _string_literal(node.args[1])
        if module is not None and attr is not None:
            return f"{module}.{attr}"
    if isinstance(node, ast.Subscript):
        install = _lvalue_install(node, imports, api_facts)
        if install is not None:
            return install[0]
    return None


def _not_self_install(
    install: tuple[str, str, str] | None,
    value: ast.AST | None,
    imports: dict[str, str],
    api_facts: _StandinApiFacts | None = None,
) -> tuple[str, str, str] | None:
    if install is None:
        return None
    if (
        value is not None
        and _resolved_value_identity(value, imports, api_facts) == install[0]
    ):
        return None
    return install


def _standin_install_targets(
    node: ast.AST,
    imports: dict[str, str],
    api_facts: _StandinApiFacts | None = None,
) -> tuple[tuple[str, str, str], ...]:
    """Flatten supported stand-in spellings to ``(target, attr, kind)``.

    The predicate intentionally starts from the target, not from the verb.
    Builtin ``setattr`` is supported when its object is an imported module,
    while the same call on a locally-created object remains ordinary test
    setup.  This is the narrow distinction issue #85 could not express when
    the old frontend simply denied builtin ``setattr`` wholesale.
    """
    found: list[tuple[str, str, str]] = []
    if isinstance(node, ast.Assign):
        for target in node.targets:
            found.extend(
                _assignment_installs(
                    target, node.value, imports, api_facts
                )
            )
    elif isinstance(node, ast.AnnAssign) and node.value is not None:
        found.extend(
            _assignment_installs(
                node.target, node.value, imports, api_facts
            )
        )
    elif isinstance(node, ast.NamedExpr):
        found.extend(
            _assignment_installs(
                node.target, node.value, imports, api_facts
            )
        )
    elif isinstance(node, ast.Call):
        api_kind = _standin_call_kind(node, imports, api_facts)

        if api_kind in ("builtin_setattr", "monkeypatch_setattr"):
            allow_keywords = api_kind != "builtin_setattr"
            first = _standin_call_argument(
                node, 0, *(('target', 'obj', 'object') if allow_keywords else ())
            )
            if first is None:
                return ()
            literal = _string_literal(first)
            if literal is not None:
                install = _direct_install(literal)
                value = _standin_call_argument(
                    node, 1, *(('value',) if allow_keywords else ())
                )
            else:
                name = _standin_call_argument(
                    node, 1, *(('name', 'attribute') if allow_keywords else ())
                )
                attr = _string_literal(name)
                module = _resolved_module_expr(first, imports)
                install = (
                    (f"{module}.{attr}", attr, "attribute")
                    if module is not None
                    and attr is not None
                    and attr.isidentifier()
                    else None
                )
                value = _standin_call_argument(
                    node, 2, *(('value',) if allow_keywords else ())
                )
            install = _not_self_install(
                install, value, imports, api_facts
            )
            if install is not None:
                found.append(install)

        elif api_kind in ("operator_setitem", "monkeypatch_setitem"):
            mapping = _standin_call_argument(node, 0, "dic", "mapping")
            name = _standin_call_argument(node, 1, "name", "key")
            mapped = (
                _mapping_module(mapping, imports, api_facts)
                if mapping is not None
                else None
            )
            key = _string_literal(name)
            install = None
            if mapped is not None and key is not None:
                kind, module = mapped
                if kind == "module":
                    install = (
                        (key, "*", "module")
                        if _valid_module_target(key, allow_relative=False)
                        else None
                    )
                elif key.isidentifier():
                    install = (f"{module}.{key}", key, "attribute")
            value = _standin_call_argument(node, 2, "value")
            install = _not_self_install(
                install, value, imports, api_facts
            )
            if install is not None:
                found.append(install)

        elif api_kind in ("mock_patch_object", "mocker_patch_object"):
            object_arg = _standin_call_argument(node, 0, "target")
            attribute_arg = _standin_call_argument(node, 1, "attribute")
            module = (
                _resolved_module_expr(object_arg, imports)
                if object_arg is not None
                else None
            )
            attr = _string_literal(attribute_arg)
            install = (
                (f"{module}.{attr}", attr, "attribute")
                if module is not None and attr is not None and attr.isidentifier()
                else None
            )
            value = _standin_call_argument(node, 2, "new")
            install = _not_self_install(
                install, value, imports, api_facts
            )
            if install is not None:
                found.append(install)

        elif api_kind in ("mock_patch", "mocker_patch"):
            target_arg = _standin_call_argument(node, 0, "target")
            literal = _string_literal(target_arg)
            install = _direct_install(literal) if literal is not None else None
            value = _standin_call_argument(node, 1, "new")
            install = _not_self_install(
                install, value, imports, api_facts
            )
            if install is not None:
                found.append(install)

        elif api_kind == "mock_patch_dict":
            mapping = _standin_call_argument(node, 0, "in_dict")
            values = _standin_call_argument(node, 1, "values")
            mapped = (
                _mapping_module(mapping, imports, api_facts)
                if mapping is not None
                else None
            )
            if mapped == ("module", "sys.modules") and isinstance(values, ast.Dict):
                for key, value in zip(values.keys, values.values):
                    module = _string_literal(key)
                    install = (
                        (module, "*", "module")
                        if module is not None
                        and _valid_module_target(module, allow_relative=False)
                        else None
                    )
                    install = _not_self_install(
                        install, value, imports, api_facts
                    )
                    if install is not None:
                        found.append(install)

    return tuple(sorted(set(found)))


def _standin_record(
    node: ast.AST,
    install: tuple[str, str, str],
    text: _Offsets,
    *,
    scope: str,
    owner: str | None = None,
    autouse: bool = False,
    position_node: ast.AST | None = None,
    active_until: tuple[int, int] | None = None,
    persists_after_owner: bool = True,
    owner_oracle_spans: tuple[tuple[int, int], ...] = (),
    api_fixture_receiver: str | None = None,
) -> StandinInstall:
    target, attr, kind = install
    legacy = (
        _patch_call_target(node, _dotted(node.func))
        if isinstance(node, ast.Call)
        else None
    )
    display_target = (
        legacy[0]
        if legacy is not None and legacy[1] == attr
        else attr if kind == "binding" else None
    )
    seg = _norm((text.seg(node) or target).split("\n", 1)[0])
    effective_position = position_node if position_node is not None else node
    return StandinInstall(
        target=target,
        attr=attr,
        text=seg,
        scope=scope,
        owner=owner,
        autouse=autouse,
        kind=kind,
        position=(
            getattr(effective_position, "lineno", 0) or 0,
            getattr(effective_position, "col_offset", 0) or 0,
        ),
        display_target=display_target,
        active_until=active_until,
        persists_after_owner=persists_after_owner,
        owner_oracle_spans=owner_oracle_spans,
        api_fixture_receiver=api_fixture_receiver,
    )


def _has_standin_install(
    tree: ast.Module,
    imports: dict[str, str],
    assigned_call_aliases: set[str] | None = None,
) -> bool:
    """Cheap once-per-file guard for the heavier stand-in lifetime passes.

    Most test diffs contain no installation at all. Previously every test
    function still paid for four additional scope walks (local imports,
    patch contexts, activations, and restores). One conservative whole-file
    inventory is enough to skip that machinery. This predicate is deliberately
    broader than the structured detector: false positives only pay for the
    full analysis, while a false negative would suppress a finding.

    Keep import aliases as sets, not one cross-scope binding map. Two nested
    scopes may reuse an alias for different modules; merging them with normal
    dict overwrite semantics would make an early-exit decision depend on AST
    traversal order and could hide the binding from the scope that owns it.
    """
    imported_names = set(imports)
    standin_call_aliases = {
        local
        for local, target in imports.items()
        if target.rsplit(".", 1)[-1] in {*_SETATTR_CALLS, "setitem", "patch"}
    }
    standin_call_aliases.update({"setattr"})
    assigned_names: set[str] = set()
    called_names: set[str] = set()
    alias_edges: dict[str, set[str]] = {}
    obvious = False

    def register_alias(name: str, value: ast.AST) -> None:
        value_name = value.id if isinstance(value, ast.Name) else None
        value_dotted = _dotted(value)
        if value_dotted and (
            value_dotted.rsplit(".", 1)[-1]
            in (*_SETATTR_CALLS, "setitem", "patch")
            or value_dotted.endswith(".patch.object")
            or value_dotted.endswith(".patch.dict")
        ):
            standin_call_aliases.add(name)
        elif value_name is not None:
            alias_edges.setdefault(name, set()).add(value_name)

    def register_paired_aliases(target: ast.AST, value: ast.AST) -> None:
        if (
            isinstance(target, (ast.Tuple, ast.List))
            and isinstance(value, (ast.Tuple, ast.List))
            and len(target.elts) == len(value.elts)
        ):
            for target_element, value_element in zip(
                target.elts, value.elts
            ):
                register_paired_aliases(target_element, value_element)
        elif isinstance(target, ast.Name):
            register_alias(target.id, value)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.update(
                alias.asname or alias.name.split(".", 1)[0]
                for alias in node.names
            )
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*":
                    continue
                local = alias.asname or alias.name
                imported_names.add(local)
                if alias.name in (*_SETATTR_CALLS, "setitem", "patch"):
                    standin_call_aliases.add(local)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            positional = node.args.posonlyargs + node.args.args
            for argument, default in zip(
                positional[-len(node.args.defaults) :], node.args.defaults
            ):
                register_alias(argument.arg, default)
            for argument, default in zip(
                node.args.kwonlyargs, node.args.kw_defaults
            ):
                if default is not None:
                    register_alias(argument.arg, default)
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
            if isinstance(node, ast.Assign):
                targets = node.targets
                value = node.value
            else:
                targets = (node.target,)
                value = node.value
            value_name = value.id if isinstance(value, ast.Name) else None
            value_dotted = _dotted(value)
            direct_callable = bool(
                value_dotted
                and (
                    value_dotted.rsplit(".", 1)[-1]
                    in (*_SETATTR_CALLS, "setitem", "patch")
                    or value_dotted.endswith(".patch.object")
                    or value_dotted.endswith(".patch.dict")
                )
            )
            for target in targets:
                register_paired_aliases(target, value)
                if any(
                    isinstance(part, (ast.Attribute, ast.Subscript))
                    for part in ast.walk(target)
                ):
                    obvious = True
                assigned_names.update(
                    part.id
                    for part in ast.walk(target)
                    if isinstance(part, ast.Name)
                )
                for name in _assignment_name_targets(target):
                    if direct_callable:
                        standin_call_aliases.add(name)
                    elif value_name is not None:
                        alias_edges.setdefault(name, set()).add(value_name)
        elif isinstance(node, ast.Call):
            dotted = _dotted(node.func) or ""
            tail = dotted.rsplit(".", 1)[-1]
            if tail in (*_SETATTR_CALLS, "setitem", "patch", "object", "dict"):
                obvious = True
            if any(
                ((_dotted(argument) or "").endswith(".patch"))
                for argument in (
                    *node.args,
                    *(keyword.value for keyword in node.keywords),
                )
            ):
                # Exact provenance is checked by the structured pass. This is
                # only the conservative file gate for an API callable passed
                # into a helper, e.g. ``verify(mock.patch)``.
                obvious = True
            if isinstance(node.func, ast.Name):
                called_names.add(node.func.id)

    changed = True
    while changed:
        changed = False
        for alias, sources in alias_edges.items():
            if alias in standin_call_aliases:
                continue
            if sources.intersection(standin_call_aliases):
                standin_call_aliases.add(alias)
                changed = True

    if assigned_call_aliases is not None:
        assigned_call_aliases.update(standin_call_aliases)

    return obvious or bool(
        assigned_names.intersection(imported_names)
        or called_names.intersection(standin_call_aliases)
    )


def _scope_body_nodes(statements) -> tuple[ast.AST, ...]:
    return tuple(statements)


def _standin_scope_nodes(roots: tuple[ast.AST, ...]):
    for root in roots:
        yield root
        yield from _scope_nodes(root)


def _standin_patch_contexts(root: ast.AST) -> dict[int, ast.With | ast.AsyncWith]:
    """Patch-call id -> lexical context manager that owns its lifetime."""
    out: dict[int, ast.With | ast.AsyncWith] = {}
    for node in (root, *_scope_nodes(root)):
        if not isinstance(node, (ast.With, ast.AsyncWith)):
            continue
        for item in node.items:
            # Entering ``factory(patch(...))`` enters the factory's context,
            # not the nested patcher object merely passed as an argument.
            # Only the context expression itself can be the patch lifecycle.
            if isinstance(item.context_expr, ast.Call):
                out[id(item.context_expr)] = node
    return out


def _pytest_mocker_patch_call(
    node: ast.AST, immediate_receivers: frozenset[str]
) -> bool:
    """Whether pytest-mock proves this patch call is immediate.

    ``mocker.patch`` deliberately mirrors ``unittest.mock.patch`` spelling,
    but returns the installed mock rather than a dormant patcher.  The caller
    supplies only receiver names proven to be live pytest fixture requests;
    a coincidental local named ``mocker`` earns no lifecycle shortcut.
    """
    if not isinstance(node, ast.Call):
        return False
    dotted = _dotted(node.func) or ""
    parts = dotted.split(".") if dotted else []
    return bool(
        parts
        and parts[0] in immediate_receivers
        and (
            parts[1:] == ["patch"]
            or parts[1:] == ["patch", "object"]
        )
    )


def _required_injected_parameters(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    class_member: bool = False,
    definition_imports: Mapping[str, str] | None = None,
) -> frozenset[str]:
    """Signature names pytest must provide rather than Python defaults.

    This mirrors pytest's ``getfuncargnames`` contract: only required
    positional-or-keyword and keyword-only parameters are fixture requests.
    Positional-only parameters cannot be supplied by pytest's keyword-based
    fixture injection, even when they have no default. Module fixtures may
    legitimately request fixtures named ``self``, ``cls``, or ``request``;
    those spellings have no special meaning outside a class. For a class
    member pytest binds the first mandatory argument regardless of its name,
    except for an actual ``staticmethod`` (and, matching pytest, when any
    positional-only parameter makes the normal binding shortcut inapplicable).
    """
    all_positional = func.args.posonlyargs + func.args.args
    defaulted = {
        argument.arg
        for argument in all_positional[-len(func.args.defaults) :]
    } if func.args.defaults else set()
    defaulted.update(
        argument.arg
        for argument, value in zip(
            func.args.kwonlyargs, func.args.kw_defaults
        )
        if value is not None
    )
    required = [
        argument.arg
        for argument in (*func.args.args, *func.args.kwonlyargs)
        if argument.arg not in defaulted
    ]
    static_method = any(
        (
            _live_import_path(decorator, definition_imports or {})
            or _dotted(decorator)
            or ""
        )
        in ("staticmethod", "builtins.staticmethod")
        for decorator in func.decorator_list
        if not isinstance(decorator, ast.Call)
    )
    if (
        class_member
        and not static_method
        and not func.args.posonlyargs
        and required
    ):
        required = required[1:]
    return frozenset(required)


def _pytest_fixture_receivers(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    requested: Collection[str],
    receiver: str,
    module_bindings: Mapping[str, str] | None = None,
) -> frozenset[str]:
    """One conventional pytest fixture receiver proven at scope entry.

    The position-aware API flow drops this origin at an actual local write.
    Rejecting the receiver merely because a write exists *later* in the scope
    lets a tail assignment erase an earlier live installation.
    """
    if (
        receiver not in requested
        or (module_bindings or {}).get(receiver) == "<fixture>"
    ):
        return frozenset()
    return frozenset({receiver})


def _mocker_fixture_receivers(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    requested: Collection[str],
    module_bindings: Mapping[str, str] | None = None,
) -> frozenset[str]:
    """Proven pytest-mock receiver names for one collected/fixture scope."""
    return _pytest_fixture_receivers(
        func, requested, "mocker", module_bindings
    )


def _is_patch_constructor(
    node: ast.AST,
    imports: dict[str, str],
    immediate_receivers: frozenset[str] = frozenset(),
    api_facts: _StandinApiFacts | None = None,
) -> bool:
    if not isinstance(node, ast.Call):
        return False
    if _pytest_mocker_patch_call(node, immediate_receivers):
        return False
    return _standin_call_kind(node, imports, api_facts) in {
        "mock_patch",
        "mock_patch_object",
        "mock_patch_dict",
    }


def _imports_at(
    node: ast.AST,
    fallback: dict[str, str],
    environments: dict[int, dict[str, str]] | None,
) -> dict[str, str]:
    return (
        environments.get(id(node), fallback)
        if environments is not None
        else fallback
    )


def _standin_patch_activations(
    root: ast.AST,
    contexts: dict[int, ast.With | ast.AsyncWith],
    imports: dict[str, str],
    environments: dict[int, dict[str, str]] | None = None,
    *,
    decorator_root: bool = False,
    immediate_receivers: frozenset[str] = frozenset(),
    api_facts: _StandinApiFacts | None = None,
) -> dict[int, str]:
    """Patch constructors proven entered as decorator/context/or `.start()`."""
    active = {node_id: "context" for node_id in contexts}
    if decorator_root and _is_patch_constructor(
        root,
        _imports_at(root, imports, environments),
        immediate_receivers,
        api_facts,
    ):
        active[id(root)] = "decorator"
    for node in (root, *_scope_nodes(root)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for decorator in node.decorator_list:
                # A patcher nested inside another decorator call is just an
                # argument unless that wrapper explicitly enters it, which
                # static syntax cannot prove.
                if _is_patch_constructor(
                    decorator,
                    _imports_at(decorator, imports, environments),
                    immediate_receivers,
                    api_facts,
                ):
                    active.setdefault(id(decorator), "decorator")
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "start"
        ):
            constructor = node.func.value
            if _is_patch_constructor(
                constructor,
                _imports_at(constructor, imports, environments),
                immediate_receivers,
                api_facts,
            ):
                active[id(constructor)] = "start"
    return active


def _patch_call_is_operative(
    node: ast.AST,
    activations: dict[int, str],
    imports: dict[str, str],
    environments: dict[int, dict[str, str]] | None = None,
    immediate_receivers: frozenset[str] = frozenset(),
    api_facts: _StandinApiFacts | None = None,
) -> bool:
    return not _is_patch_constructor(
        node,
        _imports_at(node, imports, environments),
        immediate_receivers,
        api_facts,
    ) or id(node) in activations


def _target_loaded(
    nodes: tuple[ast.AST, ...],
    install: tuple[str, str, str],
    imports: dict[str, str],
    environments: dict[int, dict[str, str]] | None = None,
) -> bool:
    target, attr, _kind = install
    for node in _standin_scope_nodes(nodes):
        node_imports = _imports_at(node, imports, environments)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            if target.startswith("request.module.") and node.id == attr:
                return True
            if node_imports.get(node.id) == target:
                return True
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
            if _resolved_module_expr(node, node_imports) == target:
                return True
        elif isinstance(node, ast.Call):
            if _resolved_module_expr(node, node_imports) == target:
                return True
    return False


def _module_reimported_after(
    root: ast.AST,
    install_node: ast.AST,
    target: str,
    imports: dict[str, str],
    environments: dict[int, dict[str, str]] | None = None,
) -> bool:
    """A later literal runtime import of ``target`` feeds a later oracle."""

    def start(node: ast.AST) -> tuple[int, int]:
        return (
            getattr(node, "lineno", 0) or 0,
            getattr(node, "col_offset", 0) or 0,
        )

    install_end = (
        getattr(install_node, "end_lineno", 0) or 0,
        getattr(install_node, "end_col_offset", 0) or 0,
    )
    nodes = tuple(_scope_nodes(root))
    assertions = tuple(node for node in nodes if isinstance(node, ast.Assert))
    oracles = tuple(
        node
        for node in nodes
        if isinstance(node, ast.Assert) or _is_oracle_call(node)
    )
    if isinstance(root, (ast.FunctionDef, ast.AsyncFunctionDef)):
        native_environments = _scope_runtime_import_environments(
            root, imports, environments
        )
        for assertion in oracles:
            assertion_imports = _imports_at(
                assertion, imports, environments
            )
            for local, binding, loaded, line, column in (
                native_environments.get(id(assertion), ())
            ):
                position = (line, column)
                if (
                    position > install_end
                    and start(assertion) > position
                    and assertion_imports.get(local) == binding
                    and loaded == target
                ):
                    # Subject consumption is checked against the expanded
                    # assertion in ``install_reaches_expressions``.  This
                    # predicate is only the temporal admission gate.
                    return True
    for call in nodes:
        if (
            not isinstance(call, ast.Call)
            or start(call) <= install_end
            or _resolved_module_expr(
                call, _imports_at(call, imports, environments)
            )
            != target
        ):
            continue
        for assertion in assertions:
            if any(child is call for child in ast.walk(assertion.test)):
                return True
        bound: set[str] = set()
        for assignment in nodes:
            if isinstance(assignment, ast.Assign):
                targets, value = assignment.targets, assignment.value
            elif isinstance(assignment, ast.AnnAssign) and assignment.value is not None:
                targets, value = (assignment.target,), assignment.value
            elif isinstance(assignment, ast.NamedExpr):
                targets, value = (assignment.target,), assignment.value
            else:
                continue
            if not any(child is call for child in ast.walk(value)):
                continue
            for assignment_target in targets:
                bound.update(_assignment_name_targets(assignment_target))
        if bound and any(
            start(assertion) > start(call)
            and any(
                isinstance(child, ast.Name)
                and isinstance(child.ctx, ast.Load)
                and child.id in bound
                for child in ast.walk(assertion.test)
            )
            for assertion in assertions
        ):
            return True
    return False


def _contains_scope_yield(
    nodes: tuple[ast.AST, ...], dead: set[int] | None = None
) -> bool:
    return any(
        isinstance(node, (ast.Yield, ast.YieldFrom))
        and (dead is None or id(node) not in dead)
        for node in _standin_scope_nodes(nodes)
    )


def _context_install_is_live(
    node: ast.AST,
    install: tuple[str, str, str],
    contexts: dict[int, ast.With | ast.AsyncWith],
    activations: dict[int, str],
    imports: dict[str, str],
    *,
    scope: str,
    text=None,
    bindings: dict[str, str] | None = None,
    dead: set[int] | None = None,
    environments: dict[int, dict[str, str]] | None = None,
) -> bool:
    lifecycle = activations.get(id(node))
    if lifecycle == "decorator":
        return scope in ("test", "class")
    if lifecycle == "start":
        return True
    context = contexts.get(id(node))
    if context is None:
        return True
    body = _scope_body_nodes(context.body)
    if scope in ("fixture", "class_fixture", "hookwrapper"):
        # A patch context containing the fixture's yield remains entered while
        # the test runs. If it exits before yield, it restored the target.
        return _contains_scope_yield(body, dead)
    if scope == "test":
        # Retain the install and let its exclusive ``active_until`` window
        # meet the complete executed-oracle inventory.  A lexical-only scan
        # here misses an assertion in a helper invoked inside the context;
        # an outside assertion is still rejected by the shared window check.
        return True
    # Module and hook scopes finish before a consumer test oracle executes.
    return False


def _straight_line_restores(
    root: ast.AST,
    imports: dict[str, str],
    *,
    scope: str,
    dead: set[int] | None = None,
    environments: dict[int, dict[str, str]] | None = None,
    api_facts: _StandinApiFacts | None = None,
) -> dict[int, tuple[int, int]]:
    """Install-node ids mapped to their definite restoration boundary.

    This deliberately models only straight-line statements. Conditional and
    dynamically-computed restores remain named residuals rather than being
    guessed. In a fixture, the first yield is the oracle boundary: teardown
    restores after it do not cancel the stand-in while the test was running.
    Fresh imports are tracked per live local binding by
    ``_scope_runtime_import_environments``.  The ``sys.modules`` effect itself
    always ends at deletion; a later unrelated import must not borrow an
    earlier unused capture to keep that effect globally alive.
    """
    body = getattr(root, "body", ())
    if not isinstance(body, list):
        return {}

    originals: dict[str, str] = {}
    # Every still-reachable stand-in instance for a target. MonkeyPatch keeps
    # a private undo stack, so a later receiver may temporarily cover an
    # earlier installation and then reveal it again. A single latest row loses
    # that state in both directions.
    active: dict[
        tuple[str, str], dict[int, tuple[str, str | None]]
    ] = {}
    current: dict[tuple[str, str], int | None] = {}
    receiver_stacks: dict[
        str,
        list[tuple[tuple[str, str], int, int | None]],
    ] = {}
    boundaries: dict[int, tuple[int, int]] = {}

    def close_pair(
        pair: tuple[str, str],
        boundary: tuple[int, int],
        *,
        keep: int | None = None,
    ) -> None:
        rows = active.get(pair)
        if not rows:
            return
        for node_id in tuple(rows):
            if node_id == keep:
                continue
            boundaries.setdefault(node_id, boundary)
            rows.pop(node_id, None)
        if not rows:
            active.pop(pair, None)

    def saved_original_replacement(call: ast.Call) -> ast.AST | None:
        """Replacement operand of a positively proven MonkeyPatch setattr."""
        if (
            api_facts is None
            or api_facts.call_kinds.get(id(call)) != "monkeypatch_setattr"
        ):
            return None
        target = _standin_call_argument(
            call, 0, "target", "obj", "object"
        )
        if target is None:
            return None
        if _string_literal(target) is not None:
            return _standin_call_argument(call, 1, "value")
        return _standin_call_argument(call, 2, "value")

    for stmt in body:
        if dead is not None and id(stmt) in dead:
            continue
        stmt_nodes = (stmt,)
        if scope == "module" and isinstance(stmt, _SCOPE_NODES):
            continue
        if scope in ("fixture", "class_fixture", "hookwrapper") and _contains_scope_yield(
            stmt_nodes, dead
        ):
            break

        if isinstance(stmt, _STANDIN_COMPOUND_STATEMENTS):
            # Conditional writes/imports are not straight-line proof of either
            # restoration or capture.
            continue

        boundary = (
            getattr(stmt, "lineno", 0) or 0,
            getattr(stmt, "col_offset", 0) or 0,
        )

        writes = {
            (target, attr): (node, (target, attr, kind))
            for node in _standin_scope_nodes(stmt_nodes)
            for target, attr, kind in _standin_install_targets(
                node,
                _imports_at(node, imports, environments),
                api_facts,
            )
        }
        restore_pairs: set[tuple[str, str]] = set()
        undo_receiver: str | None = None
        if (
            isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Call)
            and api_facts is not None
            and api_facts.call_kinds.get(id(stmt.value))
            == "monkeypatch_undo"
        ):
            undo_receiver = api_facts.call_receiver_origins.get(id(stmt.value))
        if isinstance(stmt, (ast.Import, ast.ImportFrom)):
            rebound = _import_bindings((stmt,), {})
            for pair, rows in active.items():
                if rebound.get(pair[1]) == pair[0] and any(
                    kind == "binding" for kind, _receiver in rows.values()
                ):
                    restore_pairs.add(pair)
        elif isinstance(stmt, ast.Delete):
            for target_node in stmt.targets:
                if not isinstance(target_node, ast.Subscript):
                    continue
                mapped = _mapping_module(
                    target_node.value,
                    _imports_at(target_node, imports, environments),
                    api_facts,
                )
                module = _string_literal(target_node.slice)
                pair = (module or "", "*")
                if (
                    mapped == ("module", "sys.modules")
                    and module is not None
                    and pair in active
                    and any(
                        kind == "module"
                        for kind, _receiver in active[pair].values()
                    )
                ):
                    restore_pairs.add(pair)

        assignment: tuple[list[ast.AST], ast.AST] | None = None
        if isinstance(stmt, ast.Assign):
            assignment = (list(stmt.targets), stmt.value)
        elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
            assignment = ([stmt.target], stmt.value)

        if assignment is not None:
            targets, value = assignment
            original = originals.get(value.id) if isinstance(value, ast.Name) else None
            if original is not None:
                for target_node in targets:
                    install = _lvalue_install(
                        target_node,
                        _imports_at(target_node, imports, environments),
                        api_facts,
                    )
                    if install is not None and install[0] == original:
                        restore_pairs.add((install[0], install[1]))

            # Save an original imported object before any later mutation. A
            # reassignment to an unknown value invalidates the alias.
            value_identity = _resolved_value_identity(
                value,
                _imports_at(value, imports, environments),
                api_facts,
            )
            # Reading the target after its replacement captures the stand-in,
            # not the original.  Treating that value as a restore token lets
            # ``saved = target; target = saved`` erase the live installation.
            if value_identity is not None and any(
                pair[0] == value_identity for pair in active
            ):
                value_identity = None
            for target_node in targets:
                if not isinstance(target_node, ast.Name) or target_node.id in imports:
                    continue
                if value_identity is not None:
                    originals[target_node.id] = value_identity
                elif isinstance(value, ast.Name) and value.id in originals:
                    originals[target_node.id] = originals[value.id]
                else:
                    originals.pop(target_node.id, None)

        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            replacement = saved_original_replacement(stmt.value)
            original = (
                originals.get(replacement.id)
                if isinstance(replacement, ast.Name)
                else None
            )
            if original is not None:
                restore_pairs.update(
                    pair for pair in writes if pair[0] == original
                )

        if undo_receiver is not None:
            for pair, node_id, previous in reversed(
                receiver_stacks.pop(undo_receiver, [])
            ):
                boundaries.setdefault(node_id, boundary)
                if previous is None:
                    close_pair(pair, boundary)
                    current[pair] = None
                else:
                    close_pair(pair, boundary, keep=previous)
                    current[pair] = (
                        previous
                        if previous in active.get(pair, {})
                        else None
                    )
        for pair in restore_pairs:
            if pair in writes:
                # The restoration assignment is syntactically a write but
                # semantically reinstalls the saved original. Give that node
                # an empty active window so it cannot become a second stand-in.
                boundaries[id(writes[pair][0])] = boundary
            close_pair(pair, boundary)
            current[pair] = None
        for pair in set(writes) - restore_pairs:
            node, install = writes[pair]
            node_id = id(node)
            receiver = (
                api_facts.call_receiver_origins.get(node_id)
                if api_facts is not None
                else None
            )
            previous = current.get(pair)
            active.setdefault(pair, {})[node_id] = (install[2], receiver)
            current[pair] = node_id
            if receiver is not None:
                receiver_stacks.setdefault(receiver, []).append(
                    (pair, node_id, previous)
                )

    return boundaries


def _module_standin_installs(
    tree: ast.Module,
    text: _Offsets,
    imports: dict[str, str],
    *,
    definition_imports: dict[int, dict[str, str]] | None = None,
    include_hooks: bool,
) -> tuple[StandinInstall, ...]:
    """Structured installations that execute outside an individual test.

    Module/class bodies, fixtures, and pytest hooks have different execution
    conditions.  Keeping the scope on the record lets the engine map a
    conftest install only to tests it can actually affect. Ordinary helper and
    test function bodies are not scanned here; `_collect_unit` owns the latter.
    """
    out: list[StandinInstall] = []
    module_environments, module_imports = _scope_import_environments(tree, {})

    def record(
        root: ast.AST,
        scope: str,
        owner: str | None = None,
        autouse: bool = False,
        *,
        allow_binding: bool = True,
        dead: set[int] | None = None,
        decorator_root: bool = False,
        base_imports: dict[str, str] | None = None,
        definition_base: dict[str, str] | None = None,
        immediate_receivers: frozenset[str] = frozenset(),
        monkeypatch_receivers: frozenset[str] = frozenset(),
    ) -> None:
        environments, scope_imports = _scope_import_environments(
            root,
            imports if base_imports is None else base_imports,
            definition_base=definition_base,
        )
        nodes = (root, *_scope_nodes(root))
        api_facts = _standin_api_facts(
            root,
            scope_imports,
            environments,
            monkeypatch_receivers=monkeypatch_receivers,
            mocker_receivers=immediate_receivers,
        )
        yield_boundary = min(
            (
                (getattr(node, "lineno", 0), getattr(node, "col_offset", 0))
                for node in nodes
                if isinstance(node, (ast.Yield, ast.YieldFrom))
                and (dead is None or id(node) not in dead)
            ),
            default=None,
        )
        raw_installs = [
            (node, install)
            for node in nodes
            if isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr, ast.Call))
            and (dead is None or id(node) not in dead)
            and not (
                scope in ("fixture", "class_fixture", "hookwrapper")
                and yield_boundary is not None
                and (
                    getattr(node, "lineno", 0),
                    getattr(node, "col_offset", 0),
                )
                > yield_boundary
            )
            for install in _standin_install_targets(
                node,
                _imports_at(node, scope_imports, environments),
                api_facts,
            )
            if allow_binding or install[2] != "binding"
        ]
        if not raw_installs:
            return

        contexts = {
            **_standin_patch_contexts(root),
            **api_facts.call_contexts,
        }
        activations = _standin_patch_activations(
            root,
            contexts,
            scope_imports,
            environments,
            decorator_root=decorator_root,
            immediate_receivers=immediate_receivers,
            api_facts=api_facts,
        )
        restored = _straight_line_restores(
            root,
            scope_imports,
            scope=scope,
            dead=dead,
            environments=environments,
            api_facts=api_facts,
        )
        global_names = {
            name
            for node in nodes
            if isinstance(node, ast.Global)
            for name in node.names
        }
        for node, (target, attr, kind) in raw_installs:
            if (
                id(node) in restored
                or not _patch_call_is_operative(
                    node,
                    activations,
                    scope_imports,
                    environments,
                    immediate_receivers,
                    api_facts,
                )
                or not _context_install_is_live(
                    node,
                    (target, attr, kind),
                    contexts,
                    activations,
                    scope_imports,
                    scope=scope,
                    dead=dead,
                    environments=environments,
                )
            ):
                continue
            if kind == "binding" and scope in (
                "fixture",
                "class_fixture",
                "hook",
                "hookwrapper",
            ):
                # A name assigned inside a fixture/hook is local unless
                # explicitly global, so it cannot replace the binding a
                # separate test function reaches.
                if attr not in global_names:
                    continue
            out.append(
                _standin_record(
                    node,
                    (target, attr, kind),
                    text,
                    scope=scope,
                    owner=owner,
                    autouse=autouse,
                    api_fixture_receiver=(
                        api_facts.call_fixture_receivers.get(id(node))
                    ),
                )
            )

    module_dead = _unreachable_ids(tree)
    live_callables = _module_callable_scopes(tree)
    local_fixture_names = {
        fixture_name
        for node in live_callables.values()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        if (
            fixture_name := _fixture_public_name(
                node, (definition_imports or {}).get(id(node))
            )
        )
        is not None
    }
    local_fixture_bindings = {
        name: "<fixture>" for name in local_fixture_names
    }
    module_api_facts = _standin_api_facts(
        tree, module_imports, module_environments
    )
    module_monkeypatch_receivers = frozenset(
        name
        for name, origin in module_api_facts.final_values.items()
        if origin == "monkeypatch"
        or origin.startswith("monkeypatch_instance:")
    )
    for stmt in _definite_module_statements(tree.body):
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if live_callables.get(stmt.name) is not stmt:
                continue
            exact = (definition_imports or {}).get(
                id(stmt),
                _imports_at(stmt, module_imports, module_environments),
            )
            if _is_fixture_def(stmt, exact):
                autouse = _fixture_is_autouse(stmt, exact)
                fixture_name = _fixture_public_name(stmt, exact)
                if fixture_name is None and not autouse:
                    continue
                # A fixture may deliberately extend the provider it
                # overrides: ``def monkeypatch(monkeypatch): ...`` resolves
                # the parameter through the next outer/plugin provider, not
                # recursively to itself.  Other same-file fixture names still
                # shadow the conventional pytest API receiver.
                receiver_shadow_bindings = {
                    name: value
                    for name, value in local_fixture_bindings.items()
                    if name != fixture_name
                }
                record(
                    stmt,
                    "fixture",
                    fixture_name or stmt.name,
                    autouse,
                    dead=_unreachable_ids(stmt),
                    definition_base=exact,
                    immediate_receivers=_mocker_fixture_receivers(
                        stmt,
                        _required_injected_parameters(stmt),
                        receiver_shadow_bindings,
                    ),
                    monkeypatch_receivers=(
                        _pytest_fixture_receivers(
                            stmt,
                            _required_injected_parameters(stmt),
                            "monkeypatch",
                            receiver_shadow_bindings,
                        )
                        | frozenset(
                            name
                            for name in module_monkeypatch_receivers
                            if name not in _lexical_scope_names(stmt)[0]
                        )
                    ),
                )
            elif include_hooks:
                registration = _hook_registration(stmt, exact)
                if registration is not None:
                    hook_name, wrapper = registration
                    record(
                        stmt,
                        "hookwrapper" if wrapper else "hook",
                        hook_name,
                        dead=_unreachable_ids(stmt),
                        definition_base=exact,
                        monkeypatch_receivers=frozenset(
                            name
                            for name in module_monkeypatch_receivers
                            if name not in _lexical_scope_names(stmt)[0]
                        ),
                    )
            continue
        if isinstance(stmt, ast.ClassDef):
            class_base_imports = _imports_at(
                stmt,
                module_imports,
                module_environments,
            )
            class_environments, class_imports = _scope_import_environments(
                stmt,
                class_base_imports,
            )
            if not include_hooks:
                for decorator in stmt.decorator_list:
                    record(
                        decorator,
                        "class",
                        stmt.name,
                        allow_binding=False,
                        decorator_root=True,
                        base_imports=class_base_imports,
                        definition_base=class_base_imports,
                        monkeypatch_receivers=(
                            module_monkeypatch_receivers
                        ),
                    )
                for member in stmt.body:
                    member_exact = (definition_imports or {}).get(
                        id(member),
                        _imports_at(member, class_imports, class_environments),
                    )
                    if _is_fixture_def(member, member_exact):
                        fixture_name = _fixture_public_name(
                            member, member_exact
                        )
                        autouse = _fixture_is_autouse(member, member_exact)
                        if fixture_name is None and not autouse:
                            continue
                        record(
                            member,
                            "class_fixture",
                            f"{stmt.name}.{fixture_name or member.name}",
                            autouse,
                            dead=_unreachable_ids(member),
                            definition_base=member_exact,
                            immediate_receivers=_mocker_fixture_receivers(
                                member,
                                _required_injected_parameters(
                                    member,
                                    class_member=True,
                                    definition_imports=member_exact,
                                ),
                                local_fixture_bindings,
                            ),
                            monkeypatch_receivers=(
                                _pytest_fixture_receivers(
                                    member,
                                    _required_injected_parameters(
                                        member,
                                        class_member=True,
                                        definition_imports=member_exact,
                                    ),
                                    "monkeypatch",
                                    local_fixture_bindings,
                                )
                                | frozenset(
                                    name
                                    for name in module_monkeypatch_receivers
                                    if name
                                    not in _lexical_scope_names(member)[0]
                                )
                            ),
                        )
            # Class-body statements execute at import, but bare-name writes
            # land in the class namespace and decorators/method bodies have
            # their own lifetimes. Imported-module attribute writes remain
            # supportable without treating the whole class as module scope.
            class_dead = _unreachable_ids(stmt)
            for member in stmt.body:
                if not isinstance(
                    member, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                ):
                    record(
                        member,
                        "module",
                        allow_binding=False,
                        dead=class_dead,
                        base_imports=_imports_at(
                            member,
                            class_imports,
                            class_environments,
                        ),
                        monkeypatch_receivers=(
                            module_monkeypatch_receivers
                        ),
                    )
            continue
    # Module statements need their actual statement-order environment.  A
    # final import map would let an import/rebind later in the file leak back
    # into an earlier write (and lose an earlier class decorator after a later
    # rebind).
    record(tree, "module", dead=module_dead, base_imports={})

    return tuple(sorted(set(out), key=lambda install: install.effect_identity + (install.text,)))


def conftest_patch_targets(data: bytes, first_party: frozenset[str]) -> list[str]:
    """Frozen IR-v1 census of first-party conftest patch calls.

    This intentionally retains the original raw-call semantics and spelling.
    The new lifetime/reachability discriminator is carried separately by
    ParsedFile.standin_installs and DiffGlobals.conftest_standin_patches.
    """
    raw = normalize_source(data)
    try:
        tree = ast.parse(raw)
    except (SyntaxError, RecursionError, ValueError, MemoryError):
        return []
    text = _Offsets(raw)
    local = {
        (alias.asname or alias.name.split(".")[0])
        for stmt in tree.body
        if isinstance(stmt, ast.Import)
        for alias in stmt.names
        if alias.name.split(".")[0] in first_party
    }
    local |= {
        (alias.asname or alias.name)
        for stmt in tree.body
        if isinstance(stmt, ast.ImportFrom)
        and (stmt.level or (stmt.module or "").split(".")[0] in first_party)
        for alias in stmt.names
    }
    out: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in _PATCH_CALLS or not node.args:
            continue
        base = node.func.value
        if not (isinstance(base, ast.Name) and base.id == "monkeypatch"):
            continue
        target = node.args[0]
        dotted = _dotted(target) or ""
        root = dotted.split(".")[0]
        is_first_party = (
            root in first_party
            or dotted.startswith("request.module")
            or root in local
        )
        if isinstance(target, ast.Constant) and isinstance(target.value, str):
            is_first_party = target.value.split(".")[0] in first_party
        if is_first_party:
            seg = (text.seg(node) or dotted).split("\n")[0]
            out.append(_norm(seg))
    return sorted(set(out))


def _top_level_from_imports(tree: ast.Module) -> dict[str, tuple[str, str]]:
    """Top-level `from M import a as b`, local name -> (module, original).

    Absolute imports (level 0), and same-directory package-relative imports
    (`from .assertions import x`, level 1 with a single-component module).
    The engine resolves a dotless module as a sibling `{tdir}/{module}.py`,
    which is exactly where `.assertions` lives, so the relative spelling of a
    verbatim assertion-helper extraction now resolves the same as the
    absolute one — the two disagreed, and the relative form read as
    ASSERT_REMOVED (red-team false positive, 2026-09-01). Deeper relative
    imports (`from ..pkg import x`, or `from .sub.helpers import x`) resolve
    against a parent the engine's sibling rule does not model, and stay a
    documented residual.
    """
    out: dict[str, tuple[str, str]] = {}
    for stmt in tree.body:
        if not isinstance(stmt, ast.ImportFrom) or not stmt.module:
            continue
        same_dir_relative = stmt.level == 1 and "." not in stmt.module
        if stmt.level == 0 or same_dir_relative:
            for alias in stmt.names:
                if alias.name != "*":
                    out[alias.asname or alias.name] = (stmt.module, alias.name)
    return out


def module_constants(data: bytes) -> dict[str, str]:
    """Top-level constant bindings of a module checkwash was not diffing.

    The engine uses this to resolve skip-condition names imported from files
    outside the diff (click's `from click._compat import WIN`). An unreadable
    or unparseable module yields nothing: the name stays unevaluable and the
    compat-gate credit is simply not earned.
    """
    raw = normalize_source(data)
    try:
        tree = ast.parse(raw)
    except (SyntaxError, RecursionError, ValueError, MemoryError):
        return {}
    return _top_level_constants(tree, _Offsets(raw))

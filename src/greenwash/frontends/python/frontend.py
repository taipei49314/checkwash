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
from greenwash.ir.astutil import dotted_name as _dotted
from greenwash.ir.model import Assertion, Handler, Marker, UnitSide, normalize_text

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
    # (inside if/try) are deliberately absent: a name greenwash cannot pin
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
    # Same-file `@pytest.fixture` name -> canonical text of what it produces.
    fixture_defs: dict[str, str] = field(default_factory=dict)
    # Top-level absolute `from M import a as b` bindings, local -> (module,
    # original). Relative and star imports are not recorded.
    from_imports: dict[str, tuple[str, str]] = field(default_factory=dict)
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
        return _Classified(
            "approx",
            S.APPROX,
            right_literal=_literal_repr(expected, text) if expected is not None else None,
            right_value=_literal_value(expected) if expected is not None else None,
            epsilon=eps,
            epsilon_kind=kind,
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
        left_text = text.seg(subject_node)
        right_lit = _literal_repr(expect_node, text) if expect_node is not None else None
        right_val = _literal_value(expect_node) if expect_node is not None else None
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


def _binding_definitions(func) -> dict[str, str]:
    """Locally bound name -> structural key of its defining expression.

    Canonical source (`ast.unparse`) rather than raw text, so reformatting the
    expression is not a change — the first false positive this would otherwise
    invent. A name bound more than once takes the joined keys of every
    right-hand side, in source order, because greenwash cannot tell which one
    reaches the assertion without evaluating.

    **Not `ast.dump`.** The first version used it and broke the byte-identical
    guarantee: `ast.dump` renders the AST's internal field set, which changes
    between Python releases, so 3.13 produced different IR from 3.11 and 3.12
    for identical input. The nine-way byte-compare job caught it on the release
    commit — the split was by interpreter version, not by OS, which is the
    signature. `ast.unparse` emits code, not node internals.

    This cannot be verified on a single interpreter: only the matrix can see a
    cross-version divergence, which is precisely why that job exists.
    """
    out: dict[str, list[str]] = {}
    for node in ast.walk(func):
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            targets, value = [node.target], node.value
        else:
            continue
        if value is None:
            continue
        try:
            key = ast.unparse(value)
        except (AttributeError, ValueError):  # pragma: no cover - defensive
            key = ""
        for target in targets:
            for name in _assignment_name_targets(target):
                out.setdefault(name, []).append(key)
    for node in ast.walk(func):
        if isinstance(node, ast.NamedExpr) and isinstance(node.target, ast.Name):
            try:
                key = ast.unparse(node.value)
            except (AttributeError, ValueError):  # pragma: no cover - defensive
                key = ""
            out.setdefault(node.target.id, []).append(key)
    # Unit separator, not "|": a Python expression can contain a bitwise or,
    # and `resolve_through` has to be able to tell "one binding" from "several".
    return {name: "".join(keys) for name, keys in sorted(out.items())}


def _local_bindings(func) -> dict[str, tuple[str, ...]]:
    """In-body `name = <expr>` bindings, name -> names referenced by the RHS.

    Only assignments written inside the unit count. Function parameters are
    deliberately excluded, which is what keeps a parametrized test off
    EXPECTED_VALUE_DERIVED: `@parametrize("items,expected", ...)` binds
    `expected` as an argument, so it resolves to itself and shares no name
    with the subject. A name rebound more than once maps to the union of its
    right-hand sides, because greenwash cannot order them without evaluating.
    """
    out: dict[str, set[str]] = {}
    for node in ast.walk(func):
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            targets = [node.target]
        else:
            continue
        if node.value is None:
            continue
        refs = set(_referenced_names(node.value))
        for target in targets:
            for name in _assignment_name_targets(target):
                out.setdefault(name, set()).update(refs)
    for node in ast.walk(func):
        if isinstance(node, ast.NamedExpr) and isinstance(node.target, ast.Name):
            out.setdefault(node.target.id, set()).update(_referenced_names(node.value))
    return {k: tuple(sorted(v)) for k, v in out.items()}


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


_PARAMETRIZE = ("pytest.mark.parametrize", "mark.parametrize", "parametrize")


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


def _param_columns(func) -> dict[str, str]:
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
        if not isinstance(dec, ast.Call) or _dotted(dec.func) not in _PARAMETRIZE:
            continue
        if len(dec.args) < 2 or not isinstance(dec.args[1], (ast.List, ast.Tuple)):
            continue
        names_node = dec.args[0]
        if isinstance(names_node, ast.Constant) and isinstance(names_node.value, str):
            names = [n.strip() for n in names_node.value.split(",") if n.strip()]
        elif isinstance(names_node, (ast.List, ast.Tuple)):
            names = [
                e.value for e in names_node.elts
                if isinstance(e, ast.Constant) and isinstance(e.value, str)
            ]
        else:
            continue
        for row in dec.args[1].elts:
            cells = row.elts if isinstance(row, (ast.List, ast.Tuple)) else [row]
            if len(names) == 1 and not isinstance(row, (ast.List, ast.Tuple)):
                cells = [row]
            for name, cell in zip(names, cells):
                try:
                    out.setdefault(name, []).append(ast.unparse(_param_cell_value(cell)))
                except (AttributeError, ValueError):  # pragma: no cover - defensive
                    out.setdefault(name, []).append("")
    return {name: "".join(vals) for name, vals in sorted(out.items())}


def _fixture_definitions(tree: ast.Module) -> dict[str, str]:
    """Same-file `@pytest.fixture` name -> canonical text of what it produces.

    A fixture is not a collected unit, so nothing in the IR saw its body. An
    expectation supplied by one could be edited with the assertion untouched
    and every rule silent. Conftest fixtures are deliberately out of scope and
    recorded as a residual rather than half-implemented.
    """
    out: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not any(
            _dotted(d.func if isinstance(d, ast.Call) else d) in ("pytest.fixture", "fixture")
            for d in node.decorator_list
        ):
            continue
        produced = []
        for sub in ast.walk(node):
            if isinstance(sub, (ast.Return, ast.Yield)) and sub.value is not None:
                try:
                    produced.append(ast.unparse(sub.value))
                except (AttributeError, ValueError):  # pragma: no cover - defensive
                    produced.append("")
        if produced:
            out[node.name] = "|".join(produced)
    return dict(sorted(out.items()))


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


def _invocations(scope) -> set[str]:
    """Names this scope actually *invokes*.

    Mention is not invocation, and the distinction is the whole design:
    `callable(assert_sum)`, `hasattr`, `inspect.getsource(f)` and `f.__name__`
    all name the oracle without running it, which is precisely the edit these
    attacks make. Counting a bare `Name` argument as a call hides
    benchmarks/tamper 001.
    """
    out: set[str] = set()
    for node in _scope_nodes(scope):
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


def _local_scopes(func, module_scopes: dict[str, ast.AST]) -> dict[str, ast.AST]:
    """Callable names visible to this unit: the module's, plus its own nested
    defs and lambdas, plus names bound to a deferred call (`partial`)."""
    out = dict(module_scopes)
    for node in ast.walk(func):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node is not func:
            out[node.name] = node
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if not isinstance(target, ast.Name):
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


def _executed_scopes(func, module_scopes: dict[str, ast.AST], max_depth: int = 4) -> list:
    """The unit, plus every same-file scope it actually reaches.

    This is what makes `UnitSide.assertions` mean *the assertions this test
    runs* rather than *the assert statements written inside it*. Both halves
    matter: an assertion in an uninvoked nested `def` stops counting, and an
    assertion in a helper the unit calls starts.
    """
    scopes = _local_scopes(func, module_scopes)
    with_entered = {
        _callee_root(item.context_expr)
        for node in _scope_nodes(func)
        if isinstance(node, (ast.With, ast.AsyncWith))
        for item in node.items
    }
    out = [func]
    seen: set[int] = {id(func)}
    frontier = [(name, 0) for name in _invocations(func)]
    while frontier:
        name, depth = frontier.pop()
        target = scopes.get(name)
        if target is None or depth >= max_depth or id(target) in seen:
            continue
        # A @contextmanager runs its body only when entered: building the
        # generator and never using `with` runs nothing (tamper 004).
        if _is_contextmanager(target) and name not in with_entered:
            continue
        seen.add(id(target))
        out.append(target)
        if isinstance(target, ast.ClassDef):
            for child in target.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    seen.add(id(child))
                    out.append(child)
                    frontier.extend((c, depth + 1) for c in _invocations(child))
        frontier.extend((c, depth + 1) for c in _invocations(target))
    return out


def _collect_unit(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    qualname: str,
    text: str,
    off: _Offsets,
    inherited_markers: list[Marker] | None = None,
    module_scopes: dict[str, ast.AST] | None = None,
) -> ParsedUnit:
    assertions: list[Assertion] = []
    calls: set[str] = set()
    patches: set[tuple[str, str]] = set()
    markers = _decorator_markers(func, text, off) + list(inherited_markers or [])
    handlers: list[Handler] = []
    counter = 0
    dead = _unreachable_ids(func)
    guards = _skip_call_guards(func, text)
    bindings = _local_bindings(func)

    # Markers, handlers, calls and patches stay keyed to the unit's own body: a
    # helper's assertions are this unit's oracle, a helper's `except` is not
    # this unit's handler. Only the assertion set follows reachability.
    executed = _executed_scopes(func, module_scopes or {})
    reached_asserts = {
        id(n) for scope in executed for n in _scope_nodes(scope) if isinstance(n, ast.Assert)
    }
    # Asserts collected by this walk, so the executed-scopes pass below does
    # not add them a second time: an invoked *nested* def is both lexically
    # inside `func` (this walk sees it) and an executed scope (that loop sees
    # it), and double-counting an oracle invents an assertion to "remove".
    own_assert_ids: set[int] = set()

    for node in ast.walk(func):
        if id(node) in dead:
            continue
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
                    left_names=c.left_names,
                    right_depends_on=_resolve_through(c.right_names, bindings),
                )
            )
            counter += 1
        elif isinstance(node, ast.Call):
            name = _dotted(node.func)
            if name:
                calls.add(name)
                calls.add(name.rsplit(".", 1)[-1])
                # Folded into this walk rather than given its own: a second
                # full `ast.walk` per unit put the 500-file budget over by
                # 0.18 s, and the dotted name is already computed here.
                # Unreachable code is skipped above, which is right — a patch
                # that never executes installs nothing.
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
                        left_names=c.left_names,
                        right_depends_on=_resolve_through(c.right_names, bindings),
                        trivial=c.trivial,
                    )
                )
                counter += 1
        elif isinstance(node, ast.ExceptHandler):
            caught, is_broad = _handler_info(node)
            seg = text.seg(node) or ""
            handlers.append(
                Handler(caught=caught, is_broad=is_broad, text=seg.split("\n")[0], span=off.span(node))
            )

    # The other half: assertions the unit runs that are not written inside it.
    # `assert_sum(add(2, 3), 5)` is a *call*, so without this the unit records
    # zero assertions, nothing can be removed or weakened, and a replacement
    # `assert callable(assert_sum)` reads as an assertion *added* — by the
    # strength lattice the test got stronger (THREATMODEL 91).
    for scope in executed:
        if scope is func:
            continue
        for node in _scope_nodes(scope):
            if isinstance(node, ast.Assert) and id(node) in own_assert_ids:
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
                        left_names=c.left_names,
                        right_depends_on=c.right_names,
                        inherited=True,
                    )
                )
                counter += 1
                continue
            c = _classify_unittest_call(node, text) if isinstance(node, ast.Call) else None
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
                        left_names=c.left_names,
                        right_depends_on=c.right_names,
                        inherited=True,
                        trivial=c.trivial,
                    )
                )
                counter += 1

    body = text.seg(func) or ""
    body_hash = hashlib.sha256(normalize_text(body).encode("utf-8")).hexdigest() if body else ""

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
        body_hash=body_hash,
        bindings=_binding_definitions(func),
        param_columns=_param_columns(func),
        patches=tuple(sorted(patches)),
        invoked=tuple(sorted(_invocations(func))),
        params=tuple(
            a.arg
            for a in (func.args.posonlyargs + func.args.args + func.args.kwonlyargs)
            if a.arg not in ("self", "cls")
        ),
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
    # Callables a unit can reach without leaving the file. Computed once per
    # module, not per unit: a suite with 200 tests and 5 helpers would otherwise
    # rebuild the same map 200 times.
    module_scopes: dict[str, ast.AST] = {}
    if collect_tests:
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                module_scopes[node.name] = node
            elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Lambda):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        module_scopes[target.id] = node.value

    def visit(node: ast.AST, prefix: str, inherited: list[Marker], collectible: bool) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qual = f"{prefix}{child.name}"
                if want_symbols:
                    symbols[qual] = _fingerprint(child)
                    symbol_calls[qual] = _callees(child)
                if collect_tests and collectible and _is_test_name(child.name):
                    units.append(
                        _collect_unit(child, qual, text, off, inherited, module_scopes)
                    )
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
                    and _is_test_class(child)
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
    if collect_tests:
        helper_asserts, fixture_asserts, autouse = _module_oracle_scopes(tree, text, off)
        helper_calls = _module_helper_calls(tree)
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
        fixture_defs=_fixture_definitions(tree) if collect_tests else {},
        helper_asserts=helper_asserts,
        helper_calls=helper_calls,
        fixture_asserts=fixture_asserts,
        autouse_fixtures=autouse,
    )


def _module_helper_calls(tree: ast.Module) -> dict[str, tuple[str, ...]]:
    """Callee leaves of same-file helpers. One hop, no fixtures, no tests."""
    out: dict[str, tuple[str, ...]] = {}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if _is_test_name(node.name) or _is_fixture_def(node):
            continue
        out[node.name] = _callees(node)
    return out


def _is_fixture_def(node) -> bool:
    return isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
        _dotted(d.func if isinstance(d, ast.Call) else d) in ("pytest.fixture", "fixture")
        for d in node.decorator_list
    )


def _classified_asserts(nodes, text, off) -> tuple:
    out = []
    for node in nodes:
        if not isinstance(node, ast.Assert):
            continue
        c = _classify_assert(node, text)
        seg = text.seg(node) or ""
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
            )
        )
    return tuple(out)


def _module_oracle_scopes(tree: ast.Module, text, off):
    """(helper_asserts, fixture_asserts, autouse_fixtures) for a test module.

    Helpers contribute their **own** direct asserts — one hop across the file
    boundary, matching the same-file depth line. Fixtures contribute everything
    lexically inside: the closure they return is what the unit invokes, and the
    post-`yield` teardown runs whether or not anything calls it.
    """
    helpers: dict[str, tuple] = {}
    fixtures: dict[str, tuple] = {}
    autouse: list[str] = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if _is_fixture_def(node):
            found = _classified_asserts(ast.walk(node), text, off)
            if found:
                fixtures[node.name] = found
            for d in node.decorator_list:
                if isinstance(d, ast.Call) and any(
                    kw.arg == "autouse" and isinstance(kw.value, ast.Constant) and kw.value.value
                    for kw in d.keywords
                ):
                    autouse.append(node.name)
        elif not _is_test_name(node.name):
            found = _classified_asserts(_scope_nodes(node), text, off)
            if found:
                helpers[node.name] = found
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


_PATCH_CALLS = ("setattr", "setitem", "set_attribute")


def _patch_call_target(node: ast.Call, dotted: str | None) -> tuple[str, str] | None:
    """One patch dialect -> (target, attribute), or None if this is not one.

    Called from `_collect_unit`'s single walk, which covers the decorator list
    too — that is where half of these live: `@mock.patch("pkg.mod.attr")` is
    the same installation as the `monkeypatch.setattr` two lines into the body.

    Accepted: `monkeypatch.setattr`/`setitem` (including through
    `monkeypatch.context()`, whose receiver is named by the `with` clause and
    so cannot be pinned to the fixture name), `patch(...)`, `mock.patch(...)`,
    `mocker.patch(...)`, and `patch.object(...)` in any of those spellings.

    The builtin `setattr(obj, "name", v)` is deliberately NOT one: it has no
    receiver, and mutating an object the test owns is configuration, not the
    installation of a stand-in. Reading it as one would fire on every fixture
    that sets up its subject.
    """
    if not dotted or not node.args:
        return None
    parts = dotted.split(".")
    tail = parts[-1]
    if tail in _PATCH_CALLS:
        if len(parts) < 2:  # the builtin, not a patcher
            return None
    elif tail == "object":
        if len(parts) < 2 or parts[-2] != "patch":
            return None
    elif tail != "patch":
        return None

    # Which form this is depends on the first argument, not on the arity:
    # `monkeypatch.setattr("pkg.mod.attr", v)` and
    # `monkeypatch.setattr(mod, "attr", v)` are both three-argument calls.
    first = node.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        target = first.value
        if "." not in target:
            return None  # unqualified: neither a module nor an attribute
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


def conftest_patch_targets(data: bytes, first_party: frozenset[str]) -> list[str]:
    """`monkeypatch.setattr(...)` calls in a conftest aimed at first-party code.

    A fixture that swaps the module under test for an adapter makes every
    assertion in the suite check the stand-in, with production and test files
    both byte-identical — a real agent escaped exactly this way (decoy probe
    arm 2026-08-04). Third-party and stdlib targets (faking time, network,
    env) are normal hygiene and are not reported.
    """
    raw = normalize_source(data)
    try:
        tree = ast.parse(raw)
    except (SyntaxError, RecursionError, ValueError, MemoryError):
        return []
    text = _Offsets(raw)
    # Names bound by an import *of first-party code*: `import app.pathnorm`,
    # `from app.pathnorm import normalize`, `from .helpers import x`. A
    # stdlib or third-party import (`import time`) binds a name too, and
    # patching that is hygiene, not tampering.
    local = {
        (a.asname or a.name.split(".")[0])
        for s in tree.body
        if isinstance(s, ast.Import)
        for a in s.names
        if a.name.split(".")[0] in first_party
    }
    local |= {
        (a.asname or a.name)
        for s in tree.body
        if isinstance(s, ast.ImportFrom)
        and (s.level or (s.module or "").split(".")[0] in first_party)
        for a in s.names
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
        # `monkeypatch.setattr(request.module, "name", ...)` reaches into the
        # test module itself, which is always first-party.
        dotted = _dotted(target) or ""
        root = dotted.split(".")[0]
        is_first_party = root in first_party or dotted.startswith("request.module") or root in local
        if isinstance(target, ast.Constant) and isinstance(target.value, str):
            is_first_party = target.value.split(".")[0] in first_party
        if is_first_party:
            seg = (text.seg(node) or dotted).split("\n")[0]
            out.append(_norm(seg))
    return sorted(set(out))


def _top_level_from_imports(tree: ast.Module) -> dict[str, tuple[str, str]]:
    """Top-level absolute `from M import a as b`, local name -> (module, original)."""
    out: dict[str, tuple[str, str]] = {}
    for stmt in tree.body:
        if isinstance(stmt, ast.ImportFrom) and stmt.module and not stmt.level:
            for alias in stmt.names:
                if alias.name != "*":
                    out[alias.asname or alias.name] = (stmt.module, alias.name)
    return out


def module_constants(data: bytes) -> dict[str, str]:
    """Top-level constant bindings of a module greenwash was not diffing.

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

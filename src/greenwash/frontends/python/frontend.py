"""Python frontend: stdlib-ast parsing of one file side into semantic units.

See DECISIONS.md D-001 for why this is `ast` and not tree-sitter in v0.1.
A file that fails to parse is reported with parse_ok=False and surfaces in
`skipped_files` — visible degradation, never silent (SPEC §8).
"""

from __future__ import annotations

import ast
import hashlib
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

_BROAD_EXCEPTIONS = {"Exception", "BaseException"}

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

    def span(self, node: ast.AST) -> tuple[int, int]:
        lineno = getattr(node, "lineno", 1)
        col = getattr(node, "col_offset", 0)
        end_lineno = getattr(node, "end_lineno", lineno)
        end_col = getattr(node, "end_col_offset", col)
        try:
            start = self._starts[lineno - 1] + col
            end = self._starts[end_lineno - 1] + end_col
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
    for kw in call.keywords:
        if kw.arg in ("rel", "abs"):
            seg = text.seg(kw.value)
            if seg is not None:
                return seg, kw.arg
    return None, None


def _literal_value(node: ast.AST) -> str | None:
    """repr() of a literal's VALUE (quote-style independent), else None."""
    try:
        return repr(ast.literal_eval(node))
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


def _classify_assert(node: ast.Assert, text: str) -> _Classified:
    test = node.test
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
        left_text = text.seg(left)
        right_lit = _literal_repr(comparators[0], text) if comparators else None
        right_val = _literal_value(comparators[0]) if comparators else None
        if isinstance(op, (ast.Eq, ast.NotEq)):
            # Self-comparison (`assert f(x) == f(x)`) can never fail: the
            # oracle is gone even though the form still looks exact
            # (confirmed red-team finding).
            right_text = text.seg(comparators[0]) if comparators else None
            if left_text and right_text and _norm(left_text) == _norm(right_text):
                return _Classified("tautology", S.TAUTOLOGY, left_text, right_lit, right_val)
            if isinstance(left, ast.Call) and _dotted(left.func) == "len":
                return _Classified("type_shape", S.TYPE_SHAPE, left_text, right_lit, right_val)
            if _is_container_literal(left) or any(_is_container_literal(c) for c in comparators):
                return _Classified("compare_eq", S.EXACT_STRUCT, left_text, right_lit, right_val)
            return _Classified("compare_eq", S.EXACT_VALUE, left_text, right_lit, right_val)
        if isinstance(op, (ast.Gt, ast.GtE, ast.Lt, ast.LtE)):
            return _Classified("compare_ord", S.BOUND, left_text, right_lit, right_val)
        if isinstance(op, (ast.In, ast.NotIn)):
            return _Classified("membership", S.PATTERN, left_text, right_lit, right_val)
        if isinstance(op, (ast.Is, ast.IsNot)):
            comp = comparators[0]
            if isinstance(comp, ast.Constant) and comp.value is None:
                return _Classified("non_null", S.NON_NULL, left_text)
            return _Classified("compare_eq", S.EXACT_VALUE, left_text, right_lit, right_val)
        return _Classified("unknown", None, left_text)
    if isinstance(test, ast.Call):
        name = _dotted(test.func)
        if name == "isinstance":
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
    if form == "truthy" and node.args and _is_literal(node.args[0]):
        form, level = "tautology", S.TAUTOLOGY
    if form == "compare_eq" and len(node.args) > 1:
        right_text = text.seg(node.args[1])
        if left_text and right_text and _norm(left_text) == _norm(right_text):
            form, level = "tautology", S.TAUTOLOGY
    return _Classified(form, level, left_text, right_lit, right_val, epsilon, epsilon_kind)


def _decorator_markers(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef, text: str, off: _Offsets
) -> list[Marker]:
    markers: list[Marker] = []
    for dec in node.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        name = _dotted(target)
        if name in _SKIP_DECORATORS:
            seg = text.seg(dec) or name
            markers.append(Marker(name=name, text=seg, span=off.span(dec)))
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
            name = _dotted(target)
            if name in _SKIP_DECORATORS:
                seg = text.seg(stmt) or name
                markers.append(Marker(name=name, text=seg, span=off.span(stmt)))
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


def _unreachable_ids(func: ast.FunctionDef | ast.AsyncFunctionDef) -> set[int]:
    """Node ids under statements that can never execute.

    `return` (or `raise`) parked at the top of a test body leaves every
    assertion in the AST while killing the test — a one-token cheat that was
    completely silent before (confirmed red-team finding).
    """
    dead: set[int] = set()

    def scan(body: list[ast.stmt]) -> None:
        stop = None
        for i, stmt in enumerate(body):
            if stop is not None:
                for node in ast.walk(stmt):
                    dead.add(id(node))
                continue
            if isinstance(stmt, (ast.Return, ast.Raise)):
                stop = i
                continue
            for name in ("body", "orelse", "finalbody"):
                inner = getattr(stmt, name, None)
                if isinstance(inner, list) and inner and isinstance(inner[0], ast.stmt):
                    scan(inner)
            for handler in getattr(stmt, "handlers", []) or []:
                scan(handler.body)

    scan(func.body)
    return dead


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
        rows = len(dec.args[1].elts)
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
    module_markers = _pytestmark_markers(tree, text, off) if collect_tests else []

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
                    collectible and _is_test_class(child.name),
                )
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
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
        elif isinstance(node, ast.Constant) and not isinstance(node.value, (bool, type(None))):
            rep = repr(node.value)
            if len(rep) <= 64:
                literals.add(rep)
        elif isinstance(node, ast.ExceptHandler):
            _caught, is_broad = _handler_info(node)
            if is_broad:
                broad.append(_norm((text.seg(node) or "except:").split("\n")[0]))
    broad.sort()

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
    )

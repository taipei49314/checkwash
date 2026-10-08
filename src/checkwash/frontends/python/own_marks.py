"""A setup guard that reads the test's own marks is read per unit (#358).

A marker-gated autouse fixture is how a suite turns `@pytest.mark.<name>`
into a skip:

    @pytest.fixture(autouse=True)
    def only_slow(request):
        if request.node.get_closest_marker("slow") and not os.environ.get("SLOW"):
            pytest.skip("slow tests are off")

The guard's first conjunct is false for a test that carries no `slow` mark,
so the skip never fires for it. The D6 evaluator cannot read the test's
marks, so the outcome was recorded on every unit the fixture reaches, as an
unknown guard (D-087, and #351 for a conftest's).

Each path condition of the outcome is read here against the marks the unit
carries statically, before the paths are joined:

- `request.node.get_closest_marker("m")`, `request.node.get_marker("m")`,
  either `is None` / `is not None`, and `bool(...)` of one, read the marks:
  true when the unit carries `m`, false when it does not and every mark it
  carries is known;
- `"m" in request.keywords`, `request.keywords.get("m")` (or through
  `request.node.keywords`) read pytest's keywords, which also hold the
  names of the test, its classes, its module and its directories: true
  when the unit carries `m` or is named `m`, unknown otherwise.

A path with a false condition never fires for the unit and is dropped; a
condition that is true is dropped from its path. No path left: no marker. A
path with no condition left: the outcome is unconditional for the unit.

Only a fixture of the default function scope that takes `request` is read
so (`setup_skip_controls._test_request`): a wider scope's `request.node` is
a class, module or session, not the test.

The unit's marks are those its decorators, its classes' decorators and
`pytestmark` (with their same-file bases) and its module's `pytestmark`
apply. They are unknown, and the guard is read as before, wherever a mark may
be added that this reading cannot see:
- a hook or call that adds marks, or a `pytest_plugins` load, in the test
  module or its conftest chain (`adds_marks`), or a chain cut short by a
  conftest that cannot be read;
- a coroutine test, which an async plugin in auto mode marks;
- a decorator imported from anywhere but the standard library's or
  Twisted's test tools (`_PLAIN_MODULES`), or defined in the file;
- a `pytestmark` that is not a literal, or is bound under a condition;
- a `parametrize` that may hold a `pytest.param` with marks (`_hides_params`);
- a name bound more than once or by a statement this reading does not
  follow, or in a class body;
- a base class outside the file other than `object` and unittest's or
  trial's `TestCase`, or one whose marks pytest before 7.2 read differently.
"""
from __future__ import annotations

import ast

from checkwash.ir.astutil import dotted_name

from .setup_skip_controls import _conjunction, _names, module_bindings

_MARK_READS = frozenset({"get_closest_marker", "get_marker"})
# What may add a mark the static reading cannot see: a call that adds one, a
# hook that may, a plugin a conftest loads, and a test module's own
# `pytest_generate_tests`, which may parametrize with `marks=`.
_MARK_ADDERS = frozenset({"add_marker", "applymarker"})
_MARK_HOOKS = frozenset({
    "pytest_collection_modifyitems", "pytest_itemcollected", "pytest_pycollect_makeitem",
    "pytest_generate_tests", "pytest_collection_finish",
})
_PLAIN_BASES = frozenset({
    "object", "unittest.TestCase", "unittest.case.TestCase",
    "twisted.trial.unittest.TestCase", "twisted.trial.unittest.SynchronousTestCase",
})
# Modules whose decorators apply no mark and draw none from a plugin: the
# standard library's test tools, and Twisted's, which ships no pytest plugin.
# Any other imported decorator may be a mark under another name, or its
# plugin may mark what it decorates (hypothesis marks each `@given` test).
_PLAIN_MODULES = frozenset({"unittest", "mock", "functools", "contextlib", "typing", "abc", "twisted"})
# Module path parts read as the test suite's own, and pytest's own roots: a
# value imported from one of them may be a param with marks.
_TEST_ROOTS = frozenset({"tests", "test", "testing", "conftest"})
_PLUGIN_ROOTS = frozenset({"pytest", "_pytest"})
_UNKNOWN = object()


def adds_marks(tree: ast.Module) -> bool:
    """Can this module add a mark a static reading of a test does not see?"""
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in _MARK_ADDERS:
            return True
        if isinstance(node, ast.Name) and node.id in _MARK_ADDERS:
            return True
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in _MARK_HOOKS:
            return True
        if isinstance(node, ast.Name) and node.id == "pytest_plugins" and isinstance(node.ctx, ast.Store):
            return True
    return False


def reads_marks(text: str | None) -> bool:
    """Might this guard text read the test's own marks? A cheap screen before parsing."""
    return bool(text) and "request" in text and ("marker" in text or "keywords" in text)


def _is_request_node(node: ast.AST) -> bool:
    return isinstance(node, ast.Attribute) and node.attr == "node" and isinstance(node.value, ast.Name) \
        and node.value.id == "request"


def _is_keywords(node: ast.AST) -> bool:
    if not (isinstance(node, ast.Attribute) and node.attr == "keywords"):
        return False
    owner = node.value
    return (isinstance(owner, ast.Name) and owner.id == "request") or _is_request_node(owner)


def _string_arg(call: ast.Call) -> str | None:
    args = [*call.args, *(keyword.value for keyword in call.keywords if keyword.arg == "name")]
    if len(args) == 1 and len(call.args) + len(call.keywords) == 1 and isinstance(args[0], ast.Constant) \
            and type(args[0].value) is str:
        return args[0].value
    return None


def _read(node: ast.AST, marks, names) -> bool | None:
    """The truth of a read of the unit's own marks or keywords, None when unknown or no such read."""
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name) and func.id == "bool" and len(node.args) == 1 and not node.keywords:
            return _read(node.args[0], marks, names)
        if not isinstance(func, ast.Attribute):
            return None
        name = _string_arg(node)
        if name is None:
            return None
        if func.attr in _MARK_READS and _is_request_node(func.value):
            if marks is _UNKNOWN:
                return None
            return name in marks
        if func.attr == "get" and _is_keywords(func.value):
            return _keyword(name, marks, names)
        return None
    if isinstance(node, ast.Compare) and len(node.ops) == 1:
        op, right = node.ops[0], node.comparators[0]
        if isinstance(op, (ast.In, ast.NotIn)) and _is_keywords(right) and isinstance(node.left, ast.Constant) \
                and type(node.left.value) is str:
            value = _keyword(node.left.value, marks, names)
            return None if value is None else value == isinstance(op, ast.In)
        if isinstance(op, (ast.Is, ast.IsNot)) and isinstance(right, ast.Constant) and right.value is None:
            value = _read(node.left, marks, names)
            return None if value is None else value == isinstance(op, ast.IsNot)
    return None


def _keyword(name: str, marks, names) -> bool | None:
    if name in names or (marks is not _UNKNOWN and name in marks):
        return True
    return None


def _simplify(node: ast.AST, source: str, marks, names):
    """(truth, text) of a condition under the unit's marks.

    truth is True / False when the condition is settled, else None with the
    condition's text, where each settled conjunct of an `and` and disjunct of
    an `or` is dropped. Unsettled parts keep their source text.
    """
    value = _read(node, marks, names)
    if value is not None:
        return value, None
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        inner, text = _simplify(node.operand, source, marks, names)
        if inner is not None:
            return not inner, None
        if text == ast.get_source_segment(source, node.operand):
            return None, ast.get_source_segment(source, node)
        return None, f"not ({text})"
    if isinstance(node, ast.BoolOp):
        absorbing = isinstance(node.op, ast.Or)
        parts, changed = [], False
        for operand in node.values:
            value, text = _simplify(operand, source, marks, names)
            if value is absorbing:
                return absorbing, None
            if value is not None:
                changed = True
                continue
            changed |= text != ast.get_source_segment(source, operand)
            parts.append((operand, text))
        if not parts:
            return not absorbing, None
        if not changed:
            return None, ast.get_source_segment(source, node)
        if len(parts) == 1:
            return None, parts[0][1]
        joiner = " or " if absorbing else " and "
        loose = (ast.BoolOp, ast.IfExp, ast.Lambda, ast.NamedExpr)
        return None, joiner.join(f"({text})" if isinstance(operand, loose) else text for operand, text in parts)
    return None, ast.get_source_segment(source, node)


def resolve(paths, marks, names):
    """(effect, evidence, guard) for one unit from a guarded outcome's paths, or None when none fires.

    `paths` holds (effect, evidence, conds) for each outcome the setup
    reaches, with the conditions it is reached under (`setup_outcome`).
    `marks` is the set of marks the unit carries, or `UNKNOWN`; `names` the
    unit's own name and its classes'. A condition this reading cannot settle
    is kept as written.
    """
    kept = []
    for effect, evidence, conds in paths:
        left, dead = [], False
        for cond in conds:
            try:
                node = ast.parse(cond, mode="eval").body
            except (SyntaxError, ValueError, RecursionError, MemoryError):
                node = None
            value, text = (None, cond) if node is None else _simplify(node, cond, marks, names)
            if value is False:
                dead = True
                break
            if value is None:
                left.append(text or cond)
        if dead:
            continue
        if not left:
            return effect, evidence, None
        kept.append((effect, evidence, tuple(left)))
    if not kept:
        return None
    clauses = [_conjunction(conds) for _effect, _evidence, conds in kept]
    guard = clauses[0] if len(clauses) == 1 else " or ".join(f"({c})" for c in clauses)
    return kept[0][0], kept[0][1], guard


UNKNOWN = _UNKNOWN


def _testish(module: str) -> bool:
    """Is this module the test suite's own, or a pytest plugin's, so that it may build marked params?"""
    parts = module.split(".")
    return parts[0] in _PLUGIN_ROOTS or parts[0].startswith("pytest_") or any(
        part in _TEST_ROOTS or part.startswith("test") or part.endswith("testing") for part in parts)


def _mark_name(full: str) -> str | None:
    """The mark a dotted target names (`pytest.mark.<name>`, legacy `py.test.mark.<name>`), else None."""
    parts = full.split(".")
    for prefix in (["pytest", "mark"], ["py", "test", "mark"]):
        if len(parts) > len(prefix) and parts[:len(prefix)] == prefix:
            return parts[len(prefix)]
    return None


class OwnMarks:
    """The marks each unit of one test module carries statically, or UNKNOWN.

    A name is followed only through its single top-level binding: a native
    import (`pytest`, `unittest`), an import, a plain assignment or a def.
    A name bound more than once, under a compound statement, or by any other
    statement is opaque, as is one a class body binds, which a decorator in
    that body sees first.
    """

    def __init__(self, tree: ast.Module, chain=()):
        self._unknown = adds_marks(tree) or any(getattr(level, "adds_marks", False) for level in chain)
        self._bindings = module_bindings(tree, mutated=False)
        self._imports: dict[str, tuple[str, int]] = {}
        self._values: dict[str, ast.expr] = {}
        self._defs: dict[str, ast.AST] = {}
        self._star = False
        counts: dict[str, int] = {}
        opaque: set[str] = set()
        for statement in tree.body:
            names = _names([statement])
            for name in names:
                counts[name] = counts.get(name, 0) + 1
            if isinstance(statement, (ast.Import, ast.ImportFrom)):
                for alias in statement.names:
                    if alias.name == "*":
                        module = statement.module or ""
                        self._star |= bool(statement.level) or module.split(".")[0] not in _PLAIN_MODULES
                    elif isinstance(statement, ast.ImportFrom):
                        self._imports[alias.asname or alias.name] = (statement.module or "", statement.level)
                    else:
                        self._imports[alias.asname or alias.name.split(".")[0]] = (alias.name, 0)
            elif isinstance(statement, ast.Assign) and all(isinstance(target, ast.Name) for target in statement.targets):
                for target in statement.targets:
                    self._values[target.id] = statement.value
            elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name) and statement.value:
                self._values[statement.target.id] = statement.value
            elif isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self._defs[statement.name] = statement
            else:
                opaque |= names
        # A name a function binds with `global` is the module's too.
        for node in ast.walk(tree):
            if isinstance(node, ast.Global):
                opaque.update(node.names)
        self._opaque = frozenset(opaque | {name for name, count in counts.items() if count > 1})
        self._class_names: set[str] = set()
        self._rebound = set(self._opaque)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                seen: set[str] = set()
                for statement in node.body:
                    for name in _names([statement]):
                        if name in seen:
                            self._rebound.add(name)
                        seen.add(name)
                self._class_names |= seen
        # A param's marks are passed by the `marks` keyword, or a mapping
        # with that key, or a `ParameterSet` built directly.
        self._marks_spelled = any(
            isinstance(node, ast.keyword) and node.arg == "marks"
            or isinstance(node, ast.Constant) and node.value == "marks"
            or isinstance(node, ast.Name) and node.id == "ParameterSet"
            or isinstance(node, ast.Attribute) and node.attr == "ParameterSet"
            for node in ast.walk(tree))
        self._module = self._scope(tree.body)
        self._class_memo: dict[int, object] = {}

    def of(self, func, classes=()):
        """The marks `func`, defined in `classes` (outermost first), carries; UNKNOWN when unknowable.

        A coroutine test's marks are unknown: an async plugin in auto mode
        (pytest-asyncio, pytest-trio) marks each one. So are those of a test
        whose name is bound again, as `test_x = pytest.mark.slow(test_x)` does.
        """
        if self._unknown or self._module is _UNKNOWN or isinstance(func, ast.AsyncFunctionDef) \
                or func.name in self._rebound:
            return _UNKNOWN
        marks = set(self._module)
        own = self._decorators(func.decorator_list)
        if own is _UNKNOWN:
            return _UNKNOWN
        marks |= own
        for cls in classes:
            found = self._class(cls, frozenset())
            if found is _UNKNOWN:
                return _UNKNOWN
            marks |= found
        return frozenset(marks)

    def _class(self, cls: ast.ClassDef, seen: frozenset):
        """A class's marks: its decorators, its `pytestmark` and its same-file bases'.

        Since pytest 7.2 a class's marks are those of its whole MRO; before,
        a class that binds `pytestmark` read only its own, and one with
        several marked bases only its first's. Where the two readings differ
        the marks are unknown.
        """
        if id(cls) in self._class_memo:
            return self._class_memo[id(cls)]
        parts = [self._decorators(cls.decorator_list), self._scope(cls.body)]
        inherited = []
        for base in cls.bases:
            name = dotted_name(base)
            if name is None:
                parts.append(_UNKNOWN)
                continue
            first, dot, rest = name.partition(".")
            target = self._bindings.get(first)
            full = target + dot + rest if target else name
            if full in _PLAIN_BASES and first not in self._opaque and first not in self._defs \
                    and first not in self._values:
                continue
            if isinstance(self._defs.get(name), ast.ClassDef) and name not in seen and name not in self._opaque:
                inherited.append(self._class(self._defs[name], seen | {name}))
                continue
            parts.append(_UNKNOWN)
        marked = [found for found in inherited if found]
        if len(marked) > 1 or marked and any(isinstance(target, ast.Name) and target.id == "pytestmark"
                                             for statement in cls.body for target in _targets(statement)):
            parts.append(_UNKNOWN)
        parts.extend(inherited)
        result = _UNKNOWN if any(part is _UNKNOWN for part in parts) else frozenset().union(*parts)
        self._class_memo[id(cls)] = result
        return result

    def _decorators(self, decorators):
        marks = set()
        for decorator in decorators:
            found = self._mark(decorator, frozenset())
            if found is _UNKNOWN:
                return _UNKNOWN
            marks |= found
        return frozenset(marks)

    def _scope(self, body):
        """The marks `pytestmark` holds at the end of one module or class body.

        Only a plain binding at the scope's top level is read: `=` and an
        annotated `=` replace the marks, `+=` extends them. Any other
        statement that binds, extends or deletes it (a tuple target,
        `.append(...)`, one inside a compound statement, so under a
        condition) leaves the scope's marks unknown.
        """
        marks = frozenset()
        for statement in body:
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            replace = True
            if isinstance(statement, ast.Assign) and len(statement.targets) == 1 \
                    and isinstance(statement.targets[0], ast.Name) and statement.targets[0].id == "pytestmark":
                value = statement.value
            elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name) \
                    and statement.target.id == "pytestmark":
                if statement.value is None:
                    continue
                value = statement.value
            elif isinstance(statement, ast.AugAssign) and isinstance(statement.target, ast.Name) \
                    and statement.target.id == "pytestmark" and isinstance(statement.op, ast.Add):
                value, replace = statement.value, False
            elif _touches_pytestmark(statement):
                return _UNKNOWN
            else:
                continue
            found = self._value(value, frozenset())
            if found is _UNKNOWN:
                return _UNKNOWN
            marks = found if replace else marks | found
        return marks

    def _value(self, value, resolving):
        if isinstance(value, ast.Starred):
            value = value.value
        if isinstance(value, (ast.List, ast.Tuple)):
            marks = set()
            for element in value.elts:
                found = self._value(element, resolving)
                if found is _UNKNOWN:
                    return _UNKNOWN
                marks |= found
            return frozenset(marks)
        if isinstance(value, ast.BinOp) and isinstance(value.op, ast.Add):
            left, right = self._value(value.left, resolving), self._value(value.right, resolving)
            return _UNKNOWN if _UNKNOWN in (left, right) else left | right
        found = self._mark(value, resolving)
        if found == frozenset():
            # `pytestmark` holds what this reading cannot read: a call's
            # result, a name bound elsewhere.
            return _UNKNOWN
        return found

    def _spelled(self, name: str, resolving: frozenset):
        """The dotted target `name` spells through the module's bindings, or UNKNOWN.

        A same-file value is followed only when it is itself a dotted name
        (`mark = pytest.mark`). A def, an import from anywhere but a plain
        module, an opaque name, or a name a star import may bring is unknown.
        """
        first, dot, rest = name.partition(".")
        if first in self._opaque or first in self._class_names or first in self._defs:
            return _UNKNOWN
        bound = self._bindings.get(first)
        if bound:
            return bound + dot + rest
        if first in self._imports:
            module, level = self._imports[first]
            return name if not level and module.split(".")[0] in _PLAIN_MODULES else _UNKNOWN
        if first in self._values:
            base = dotted_name(self._values[first])
            if base is None or first in resolving or len(resolving) >= 8:
                return _UNKNOWN
            return self._spelled(base + dot + rest, resolving | {first})
        return _UNKNOWN if self._star else name

    def _mark(self, node, resolving):
        """The marks one decorator or `pytestmark` element applies: a set, empty for none, or UNKNOWN."""
        call = node if isinstance(node, ast.Call) else None
        target = call.func if call is not None else node
        name = dotted_name(target)
        if name is None:
            return _UNKNOWN
        value = self._values.get(name)
        if value is not None and dotted_name(value) is None and name not in self._opaque \
                and name not in self._class_names:
            # `skip_win = pytest.mark.skipif(...)`: the marks a same-file value holds.
            if call is not None or name in resolving or len(resolving) >= 8:
                return _UNKNOWN
            return self._value(value, resolving | {name})
        full = self._spelled(name, resolving)
        if full is _UNKNOWN:
            return _UNKNOWN
        mark = _mark_name(full)
        if mark is None:
            return frozenset()
        if mark == "parametrize" and call is not None and self._hides_params(call, frozenset()):
            return _UNKNOWN
        return frozenset({mark})

    def _hides_params(self, node, resolving) -> bool:
        """Could this `parametrize` call hold a `pytest.param` whose marks this reading does not see?

        A param takes marks only by the `marks` keyword, which the module
        must then spell (`_marks_spelled`), or through a `**` mapping. What
        the call reads is followed through the module's own values and defs;
        a name imported from a test-side or plugin module, opaque, or bound
        in a class body may hold one.
        """
        if self._marks_spelled:
            return True
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call) and any(keyword.arg is None for keyword in sub.keywords):
                return True
            if not (isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load)):
                continue
            name = sub.id
            if name in self._opaque or name in self._class_names:
                return True
            if self._bindings.get(name):
                continue
            if name in self._imports:
                module, level = self._imports[name]
                if level or _testish(module):
                    return True
                continue
            target = self._values.get(name) or self._defs.get(name)
            if target is not None:
                if name in resolving or len(resolving) >= 8 or self._hides_params(target, resolving | {name}):
                    return True
            elif self._star:
                return True
        return False


def _targets(statement):
    if isinstance(statement, ast.Assign):
        return statement.targets
    if isinstance(statement, (ast.AnnAssign, ast.AugAssign)):
        return [statement.target]
    return []


def _touches_pytestmark(statement) -> bool:
    """Does this statement bind, extend or delete `pytestmark` in a way `_scope` does not read?"""
    for node in ast.walk(statement):
        if isinstance(node, ast.Name) and node.id == "pytestmark" and isinstance(node.ctx, (ast.Store, ast.Del)):
            return True
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "pytestmark":
            return True
    return False

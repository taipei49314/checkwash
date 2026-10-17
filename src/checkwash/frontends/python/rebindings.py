"""Which binding of a test's name pytest collects (#424).

pytest collects a module's or a class's tests from its `__dict__` once that
scope has run, so a name's last binding is the only one collected. A
`def test_x` that a later statement rebinds or deletes never runs: a second
def, `del test_x`, `test_x = None`, an import, `Cls.test_x = ...` after the
class, a literal-name `setattr`/`delattr`/`globals()[...]`. Every syntactic
binding of each name in a module and in each class body is read here, with
the path it runs on (ruling 424, 2026-10-14):

- a later binding that certainly replaces a def or class, on a straight-line
  path or under branches that always hold, means pytest never collects it:
  it is no unit (Q1 (b)). A rebound class takes all its units with it;
- one that replaces it only under a condition leaves the unit, with a
  `collection.rebound` marker whose guard is that condition, judged as a
  guarded body skip (Q2 (a), Q6 (a));
- one in a loop body, a conditional binder (`except ... as`, a for target, a
  walrus a short circuit can skip), a `match` case, or mid-way through a `try`
  body leaves the unit with a marker whose guard D6 never holds (None);
- bindings on exclusive paths do not rebind each other: if/elif/else arms,
  `match` cases, separate except handlers, a handler and the try `else`, and
  a handler and the try body when nothing after the try-body binding can
  raise;
- `X = f(X)`, and nested one-argument chains, are read as `@f` would be (Q5
  (a)): a skip or xfail applied this way is that mark, and an unknown wrapper
  keeps the test live;
- a def or class that a collected name captured before the rebinding
  (`test_y = test_x`, `TestAlias = TestX`) stays as it was, and so does a
  rebound class's method that an earlier same-file subclass still runs.
  Only when same-file C3 resolution proves that no collected class runs the
  method does it go as above (Q9 (a)).

Not read, and named as residuals by THREATMODEL row 135: computed names,
`exec`, star imports, `sys.modules` replacement, `global` in a function that
runs at import, metaclasses, `__init_subclass__`, class decorators, wrappers
that drop the test, and a raise earlier in the module that keeps a later def
from running.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field, replace

from checkwash.frontends.python.setup_skip_controls import _conjunction
from checkwash.ir.astutil import dotted_name
from checkwash.ir.markers import REBOUND
from checkwash.ir.model import Marker

# Event kinds. A DEF binds a def or class statement; a BIND is any other
# binding, deletion included; a DECORATE is `X = f(X)`; a CAPTURE is the
# load of `X` in `Y = X`, recorded under `X`.
DEF, BIND, DECORATE, CAPTURE = "def", "bind", "decorate", "capture"

# What a binding needs, once an earlier def has bound, to run: these
# sentinels, None for nothing (it always runs), or a guard's source text.
_EXCLUSIVE = object()  # it never runs on a path where the def bound
_DEAD = object()  # it never runs at all
_UNKNOWN = object()  # it may not run, under no condition D6 can read

# The namespace a literal key names: `globals()["test_x"] = ...`.
_NAMESPACES = {"globals", "vars", "locals"}
_TRY = (ast.Try, ast.TryStar)
_LOOPS = (ast.For, ast.AsyncFor, ast.While)
_TYPE_ALIAS = getattr(ast, "TypeAlias", ())


@dataclass
class Status:
    """What the bindings after a def or class do to it.

    `dropped`: pytest never collects it. `markers`: the rebinding and
    decoration markers its units carry. For a class, `gone` and `rebound` are
    what its own rebinding does to a unit collected through it that its body
    does not define (`inherited_test_methods`); its body's units carry that
    already.
    """

    dropped: bool = False
    markers: list[Marker] = field(default_factory=list)
    gone: bool = False
    rebound: list[Marker] = field(default_factory=list)


@dataclass
class _Event:
    pos: tuple[int, int]
    # (container, arm, index) from the module down to the binding statement:
    # arm is "body", "orelse", "finalbody", ("handler", i) or ("case", i), and
    # index -1 is a binder at the head of an arm (`except E as name`).
    path: tuple
    cite: ast.AST
    kind: str
    node: ast.AST | None = None
    decorators: tuple = ()
    binder: bool = False
    # The statement may fail before it binds: in a `try` body it may then not bind.
    fails: bool = True
    # CAPTURE: the capturing name and its own binding.
    target: str | None = None
    other: _Event | None = None


class _Scope:
    def __init__(self, owner: ast.AST) -> None:
        self.owner = owner
        self.events: dict[str, list[_Event]] = {}
        # A binding from outside the body (`Cls.test_x = ...`) makes its
        # namespace something its body does not say.
        self.external = False

    def add(self, name: str, event: _Event) -> None:
        self.events.setdefault(name, []).append(event)


def _same(a, b) -> bool:
    return a[0] is b[0] and a[1] == b[1] and a[2] == b[2]


def _arm(frame) -> list[ast.stmt]:
    container, arm, _index = frame
    if isinstance(arm, tuple):
        kind, i = arm
        return container.handlers[i].body if kind == "handler" else container.cases[i].body
    return getattr(container, arm)


def _is_try_body(frame) -> bool:
    return isinstance(frame[0], _TRY) and frame[1] == "body"


def _is_handler(arm) -> bool:
    return isinstance(arm, tuple) and arm[0] == "handler"


def _chain(value: ast.AST) -> tuple[tuple[ast.AST, ...], ast.AST]:
    """`f(g(x))` as its wrappers, outermost first, and the innermost value.

    Only a call with exactly one positional argument and no keywords wraps:
    that is the call a decorator makes.
    """
    wrappers = []
    while (
        isinstance(value, ast.Call) and len(value.args) == 1 and not value.keywords
        and not isinstance(value.args[0], ast.Starred)
    ):
        wrappers.append(value.func)
        value = value.args[0]
    return tuple(wrappers), value


def _targets(target: ast.AST) -> list[ast.AST]:
    """The Name, Attribute and Subscript targets one assignment target holds."""
    if isinstance(target, ast.Starred):
        return _targets(target.value)
    if isinstance(target, (ast.Tuple, ast.List)):
        return [inner for element in target.elts for inner in _targets(element)]
    return [target]


def _receiver(node: ast.AST) -> list[str] | None:
    """`Outer.Inner` as ["Outer", "Inner"], or None for anything but a name chain."""
    names = []
    while isinstance(node, ast.Attribute):
        names.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    names.append(node.id)
    names.reverse()
    return names


def _literal(node: ast.AST | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _namespace_call(node: ast.AST) -> str | None:
    """`globals()`, `vars()` or `locals()` called bare: which one."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.args and not node.keywords:
        return node.func.id if node.func.id in _NAMESPACES else None
    return None


def _unittest_classes(tree: ast.Module) -> frozenset[str]:
    """Module-level classes that subclass a `*TestCase`, through same-file bases."""
    classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
    found = {
        name for name, node in classes.items()
        if any((dotted_name(base) or "").split(".")[-1].endswith("TestCase") for base in node.bases)
    }
    changed = True
    while changed:
        changed = False
        for name, node in classes.items():
            if name not in found and any(isinstance(b, ast.Name) and b.id in found for b in node.bases):
                found.add(name)
                changed = True
    return frozenset(found)


class Reader:
    """What the frontend lends this reading.

    `condition(node)`: a test's source text. `truth(node)`: its constant
    folding. `handler_guard(try, handler)`: an `except` block's condition.
    `match_dead(match)`, `never_iterates(for)`: dead compound statements.
    `marks(decorators, cls)`: the skip and xfail marks these decorators apply
    in a class body (None: the module). `cite(node)`: a marker's text and
    span. `collectible_class(cls)`: does the frontend collect this class's
    tests.
    """

    def __init__(self, *, condition, truth, handler_guard, match_dead, never_iterates, marks, cite,
                 collectible_class):
        self.condition = condition
        self.truth = truth
        self.handler_guard = handler_guard
        self.match_dead = match_dead
        self.never_iterates = never_iterates
        self.marks = marks
        self.cite = cite
        self.collectible_class = collectible_class


def _rebound_marker(reader: Reader, node: ast.AST, guard: str | None) -> Marker:
    text, span = reader.cite(node)
    return Marker(name=REBOUND, text=text, span=span, guard=guard)


class _Walk:
    """Every binding in a module and its class bodies, with its path."""

    def __init__(self, tree: ast.Module, reader: Reader, expressions: bool) -> None:
        self.reader = reader
        self.expressions = expressions
        self.module = _Scope(tree)
        self.classes: dict[int, _Scope] = {}
        self.attributes: list[tuple[list[str], str, _Event]] = []
        self.lazy = any(
            isinstance(node, ast.ImportFrom) and node.module == "__future__"
            and any(alias.name == "annotations" for alias in node.names)
            for node in tree.body
        )
        self.body(tree.body, tree, "body", (), self.module)

    # -- what may raise -----------------------------------------------------

    def quiet(self, stmt: ast.stmt) -> bool:
        """Can this statement never raise? Strict: a handler's def is exclusive with a
        try-body def only when nothing after the latter can raise (Q6)."""
        if isinstance(stmt, ast.Pass):
            return True
        if isinstance(stmt, ast.Expr):
            return isinstance(stmt.value, ast.Constant)
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if stmt.decorator_list or getattr(stmt, "type_params", None):
                return False
            args = stmt.args
            defaults = [*args.defaults, *(d for d in args.kw_defaults if d is not None)]
            if not all(isinstance(d, ast.Constant) for d in defaults):
                return False
            if self.lazy:
                return True
            every = [*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg]
            notes = [stmt.returns, *(arg.annotation for arg in every if arg is not None)]
            return all(note is None or isinstance(note, ast.Constant) for note in notes)
        if isinstance(stmt, ast.ClassDef):
            return (
                not (stmt.decorator_list or stmt.bases or stmt.keywords or getattr(stmt, "type_params", None))
                and all(self.quiet(inner) for inner in stmt.body)
            )
        if isinstance(stmt, ast.Assign):
            return isinstance(stmt.value, ast.Constant) and all(isinstance(t, ast.Name) for t in stmt.targets)
        if isinstance(stmt, ast.AnnAssign):
            return (
                isinstance(stmt.target, ast.Name)
                and (stmt.value is None or isinstance(stmt.value, ast.Constant))
                and (self.lazy or isinstance(stmt.annotation, ast.Constant))
            )
        return False

    def binds(self, stmt: ast.stmt | None) -> bool:
        """Does this statement surely bind once it runs?"""
        if stmt is None:
            return False
        if self.quiet(stmt):
            return True
        if isinstance(stmt, ast.Delete):
            return all(isinstance(t, ast.Name) for t in stmt.targets)
        if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
            return (
                all(isinstance(t, ast.Name) for t in targets)
                and isinstance(stmt.value, (ast.Constant, ast.Name, ast.Lambda))
            )
        return False

    # -- the walk -----------------------------------------------------------

    def body(self, stmts, container, arm, path, scope: _Scope) -> None:
        for index, stmt in enumerate(stmts):
            self.statement(stmt, path + ((container, arm, index),), scope)

    def new(self, here, cite, kind, stmt=None, **extra) -> _Event:
        return _Event(pos=(cite.lineno, cite.col_offset), path=here, cite=cite, kind=kind,
                      fails=not self.binds(stmt), **extra)

    def event(self, scope, name, here, cite, kind, stmt=None, **extra) -> _Event:
        event = self.new(here, cite, kind, stmt, **extra)
        scope.add(name, event)
        return event

    def statement(self, stmt: ast.stmt, here: tuple, scope: _Scope) -> None:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            self.headers(stmt, here, scope)
            self.event(scope, stmt.name, here, stmt, DEF, stmt, node=stmt)
            if isinstance(stmt, ast.ClassDef):
                inner = _Scope(stmt)
                self.classes[id(stmt)] = inner
                self.body(stmt.body, stmt, "body", here, inner)
            return
        if isinstance(stmt, ast.If):
            self.expr(stmt.test, here, stmt, scope)
            self.body(stmt.body, stmt, "body", here, scope)
            self.body(stmt.orelse, stmt, "orelse", here, scope)
            return
        if isinstance(stmt, (ast.For, ast.AsyncFor)):
            self.expr(stmt.iter, here, stmt, scope)
            # A for over a constant-empty iterable binds nothing (Q4).
            if not self.reader.never_iterates(stmt):
                for target in _targets(stmt.target):
                    self.target(target, None, here, stmt, scope, binder=True)
            self.body(stmt.body, stmt, "body", here, scope)
            self.body(stmt.orelse, stmt, "orelse", here, scope)
            return
        if isinstance(stmt, ast.While):
            self.expr(stmt.test, here, stmt, scope)
            self.body(stmt.body, stmt, "body", here, scope)
            self.body(stmt.orelse, stmt, "orelse", here, scope)
            return
        if isinstance(stmt, (ast.With, ast.AsyncWith)):
            for item in stmt.items:
                self.expr(item.context_expr, here, stmt, scope)
                if item.optional_vars is not None:
                    for target in _targets(item.optional_vars):
                        self.target(target, None, here, stmt, scope)
            self.body(stmt.body, stmt, "body", here, scope)
            return
        if isinstance(stmt, _TRY):
            self.body(stmt.body, stmt, "body", here, scope)
            for i, handler in enumerate(stmt.handlers):
                arm = ("handler", i)
                if handler.type is not None:
                    self.expr(handler.type, here, stmt, scope)
                if handler.name:
                    # Bound when the handler runs, and deleted when it ends.
                    self.event(scope, handler.name, here + ((stmt, arm, -1),), handler, BIND, binder=True)
                self.body(handler.body, stmt, arm, here, scope)
            self.body(stmt.orelse, stmt, "orelse", here, scope)
            self.body(stmt.finalbody, stmt, "finalbody", here, scope)
            return
        if isinstance(stmt, ast.Match):
            self.expr(stmt.subject, here, stmt, scope)
            for i, case in enumerate(stmt.cases):
                arm = ("case", i)
                head = here + ((stmt, arm, -1),)
                for node in ast.walk(case.pattern):
                    name = node.name if isinstance(node, (ast.MatchAs, ast.MatchStar)) else None
                    if isinstance(node, ast.MatchMapping):
                        name = node.rest
                    if name:
                        self.event(scope, name, head, node, BIND, binder=True)
                if case.guard is not None:
                    self.expr(case.guard, head, stmt, scope)
                self.body(case.body, stmt, arm, here, scope)
            return
        if isinstance(stmt, ast.Assign):
            self.expr(stmt.value, here, stmt, scope)
            for target in stmt.targets:
                for node in _targets(target):
                    self.target(node, stmt.value if node is target else None, here, stmt, scope)
            return
        if isinstance(stmt, ast.AnnAssign):
            # An annotation without a value binds nothing (Q4).
            if stmt.value is not None:
                self.expr(stmt.value, here, stmt, scope)
                self.target(stmt.target, stmt.value, here, stmt, scope)
            return
        if isinstance(stmt, ast.AugAssign):
            self.expr(stmt.value, here, stmt, scope)
            self.target(stmt.target, None, here, stmt, scope)
            return
        if isinstance(stmt, ast.Delete):
            for target in stmt.targets:
                for node in _targets(target):
                    self.target(node, None, here, stmt, scope)
            return
        if isinstance(stmt, (ast.Import, ast.ImportFrom)):
            # A star import binds names it does not say: a residual.
            for alias in stmt.names:
                if alias.name != "*":
                    self.event(scope, alias.asname or alias.name.split(".")[0], here, stmt, BIND, stmt)
            return
        if _TYPE_ALIAS and isinstance(stmt, _TYPE_ALIAS) and isinstance(stmt.name, ast.Name):
            self.event(scope, stmt.name.id, here, stmt, BIND, stmt)
            return
        for child in ast.iter_child_nodes(stmt):
            if isinstance(child, ast.expr):
                self.expr(child, here, stmt, scope)

    def headers(self, stmt, here, scope) -> None:
        """A def's or class's decorators, defaults and bases run in the enclosing scope."""
        if not self.expressions:
            return
        nodes = list(stmt.decorator_list)
        if isinstance(stmt, ast.ClassDef):
            nodes += [*stmt.bases, *(kw.value for kw in stmt.keywords)]
        else:
            nodes += [*stmt.args.defaults, *(d for d in stmt.args.kw_defaults if d is not None)]
        for node in nodes:
            self.expr(node, here, stmt, scope)

    def target(self, node, value, here, stmt, scope, binder=False) -> None:
        """One assignment, deletion or loop target. `value`: what a lone target receives."""
        if isinstance(node, ast.Name):
            name = node.id
            if value is None:
                self.event(scope, name, here, stmt, BIND, stmt, binder=binder)
                return
            wrappers, inner = _chain(value)
            if isinstance(inner, ast.Name) and inner.id == name:
                # `X = f(X)` is `@f` (Q5); `X = X` rebinds nothing.
                if wrappers:
                    self.event(scope, name, here, stmt, DECORATE, stmt, decorators=wrappers, binder=binder)
                return
            bound = self.event(scope, name, here, stmt, BIND, stmt, binder=binder)
            if isinstance(inner, ast.Name):
                self.event(scope, inner.id, here, stmt, CAPTURE, stmt, target=name, other=bound)
            return
        if isinstance(node, ast.Attribute):
            receiver = _receiver(node.value)
            if receiver is None or scope is not self.module:
                return
            kind, wrappers = BIND, ()
            if value is not None:
                wrappers, inner = _chain(value)
                same = (
                    isinstance(inner, ast.Attribute) and inner.attr == node.attr
                    and _receiver(inner.value) == receiver
                )
                if same and not wrappers:
                    return
                if same:
                    kind = DECORATE
            event = self.new(here, stmt, kind, stmt, decorators=wrappers, binder=binder)
            self.attributes.append((receiver, node.attr, event))
            return
        if isinstance(node, ast.Subscript):
            space = self.namespace(_namespace_call(node.value), scope)
            key = _literal(node.slice)
            if key is not None and space is not None:
                self.event(space, key, here, stmt, BIND, stmt, binder=binder)

    def namespace(self, space: str | None, scope: _Scope) -> _Scope | None:
        """The scope `globals()`, `vars()` or `locals()` names from this one."""
        if space is None:
            return None
        if scope is self.module:
            return scope
        # In a class body `locals()` and `vars()` are the class namespace;
        # `globals()` there is the module's, which this walk does not follow
        # out of a class body.
        return scope if space != "globals" else None

    def expr(self, node: ast.AST, here, stmt, scope, conditional: bool = False) -> None:
        """Walrus targets and literal-name `setattr`/`delattr`/namespace calls in one expression."""
        if not self.expressions:
            return
        stack = [(node, conditional)]
        while stack:
            current, cond = stack.pop()
            if isinstance(current, ast.Lambda):
                continue
            if isinstance(current, ast.NamedExpr) and isinstance(current.target, ast.Name):
                self.event(scope, current.target.id, here, current, BIND, binder=cond)
            elif isinstance(current, ast.Call):
                self.call(current, here, stmt, scope, cond)
            if isinstance(current, ast.BoolOp):
                first, *rest = current.values
                stack.append((first, cond))
                stack.extend((value, True) for value in rest)
            elif isinstance(current, ast.IfExp):
                stack += [(current.test, cond), (current.body, True), (current.orelse, True)]
            elif isinstance(current, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
                # The first iterable runs in this scope; the rest runs per item.
                first = current.generators[0].iter
                stack.append((first, cond))
                for child in ast.iter_child_nodes(current):
                    if isinstance(child, ast.comprehension):
                        stack.extend((part, True) for part in ast.iter_child_nodes(child) if part is not first)
                    else:
                        stack.append((child, True))
            else:
                stack.extend((child, cond) for child in ast.iter_child_nodes(current))

    def call(self, node: ast.Call, here, stmt, scope, cond) -> None:
        func = node.func
        if isinstance(func, ast.Name) and func.id in ("setattr", "delattr") and len(node.args) >= 2:
            key = _literal(node.args[1])
            receiver = _receiver(node.args[0])
            if key is None or receiver is None or scope is not self.module:
                return
            self.attributes.append((receiver, key, self.new(here, stmt, BIND, binder=cond)))
            return
        if isinstance(func, ast.Attribute):
            space = self.namespace(_namespace_call(func.value), scope)
            if space is None:
                return
            keys: list[str] = []
            if func.attr in ("pop", "__delitem__", "__setitem__") and node.args:
                keys = [key for key in [_literal(node.args[0])] if key is not None]
            elif func.attr == "update":
                keys = [kw.arg for kw in node.keywords if kw.arg]
                for arg in node.args:
                    if isinstance(arg, ast.Dict):
                        keys += [key for key in (_literal(k) for k in arg.keys) if key is not None]
            for key in keys:
                self.event(space, key, here, stmt, BIND, binder=cond)

    def resolve(self, names: list[str], pos: tuple[int, int]) -> _Scope | None:
        """The class scope `Outer.Inner` names at module position `pos`."""
        scope = self.module
        for depth, name in enumerate(names):
            defs = [
                e for e in scope.events.get(name, ())
                if e.kind == DEF and isinstance(e.node, ast.ClassDef) and (depth or e.pos < pos)
            ]
            if not defs:
                return None
            scope = self.classes[id(defs[-1].node)]
        return scope


class _Judge:
    def __init__(self, walk: _Walk, reader: Reader, tree: ast.Module) -> None:
        self.walk = walk
        self.reader = reader
        self.unittest = _unittest_classes(tree)
        self.status: dict[int, Status] = {}
        # Classes their own later binding replaces, certainly or under a condition.
        self.rebound_classes: list[tuple[_Scope, _Event, bool, list[Marker]]] = []
        self.gone: set[int] = set()

    # -- paths ----------------------------------------------------------------

    def entry(self, frame, last: bool, event: _Event):
        """What entering this arm needs: None, a guard, _DEAD or _UNKNOWN."""
        container, arm, index = frame
        reader = self.reader
        if isinstance(container, ast.If):
            truth = reader.truth(container.test)
            if arm == "body":
                return None if truth is True else _DEAD if truth is False else reader.condition(container.test)
            return _DEAD if truth is True else None if truth is False else f"not ({reader.condition(container.test)})"
        if isinstance(container, (ast.For, ast.AsyncFor)):
            empty = reader.never_iterates(container)
            if arm == "body":
                return _DEAD if empty else _UNKNOWN
            return None if empty else _UNKNOWN
        if isinstance(container, ast.While):
            truth = reader.truth(container.test)
            if arm == "body":
                return _DEAD if truth is False else _UNKNOWN
            return None if truth is False else _UNKNOWN
        if isinstance(container, (ast.With, ast.AsyncWith)):
            return None
        if isinstance(container, _TRY):
            quiet = all(self.walk.quiet(stmt) for stmt in container.body)
            if arm == "body":
                # A binding mid-way through a try body runs only if nothing
                # before it raised (Q6).
                before = container.body[:index]
                return None if last and not event.fails and all(self.walk.quiet(s) for s in before) else _UNKNOWN
            if _is_handler(arm):
                return _DEAD if quiet else reader.handler_guard(container, container.handlers[arm[1]])
            if arm == "orelse":
                return None if quiet else _UNKNOWN
            return None
        if isinstance(container, ast.Match):
            return _DEAD if reader.match_dead(container) else _UNKNOWN
        return _UNKNOWN

    def arms(self, d: _Event, k: int, fe):
        """Two arms of one compound statement: `d` in one, the later binding in the other."""
        container, a, index = d.path[k]
        b = fe[1]
        if isinstance(container, (ast.If, ast.Match)):
            return _EXCLUSIVE
        if isinstance(container, _TRY):
            if _is_handler(a) and (_is_handler(b) or b == "orelse"):
                return _EXCLUSIVE
            if a == "orelse" and _is_handler(b):
                return _EXCLUSIVE
            if b == "finalbody":
                return None
            if a == "body" and (_is_handler(b) or b == "orelse"):
                # Nothing after the try-body binding can raise: the handler
                # runs only if it did not bind, and the `else` whenever it did.
                tail = len(d.path) == k + 1 and all(self.walk.quiet(stmt) for stmt in container.body[index + 1:])
                if _is_handler(b):
                    return _EXCLUSIVE if tail else self.reader.handler_guard(container, container.handlers[b[1]])
                return None if tail else _UNKNOWN
        return _UNKNOWN

    def relation(self, d: _Event, e: _Event):
        """What `e`, a binding after `d`, needs to run once `d` has bound."""
        dp, ep = d.path, e.path
        k, n = 0, min(len(dp), len(ep))
        while k < n and _same(dp[k], ep[k]):
            k += 1
        if k == n:
            return _UNKNOWN
        fd, fe = dp[k], ep[k]
        siblings = fd[1] == fe[1]
        conds = []
        if not siblings:
            entry = self.arms(d, k, fe)
            if entry is _EXCLUSIVE:
                return _EXCLUSIVE
            conds.append(entry)
        rest = ep[k + 1:]
        conds += [self.entry(frame, i == len(rest) - 1, e) for i, frame in enumerate(rest)]
        shared = ep[:k + 1] if siblings else ep[:k]
        # A loop body both run in may stop between them (Q6).
        if any(isinstance(frame[0], _LOOPS) and frame[1] == "body" for frame in shared):
            conds.append(_UNKNOWN)
        # A raise between them in a try body both run in skips the later one.
        if any(_is_try_body(frame) for frame in shared):
            if not (
                siblings and len(dp) == len(ep) == k + 1 and not e.fails
                and all(self.walk.quiet(stmt) for stmt in _arm(fd)[fd[2] + 1:fe[2]])
            ):
                conds.append(_UNKNOWN)
        if e.binder:
            conds.append(_UNKNOWN)
        if any(c is _DEAD for c in conds):
            return _DEAD
        if any(c is _UNKNOWN for c in conds):
            return _UNKNOWN
        texts = [c for c in conds if isinstance(c, str)]
        return _conjunction(texts) if texts else None

    # -- one def or class -----------------------------------------------------

    def survives(self, scope: _Scope, name: str, bound: _Event) -> bool:
        """Does no later binding certainly replace this binding of `name`?"""
        return not any(
            e.pos > bound.pos and e.kind in (DEF, BIND) and self.relation(bound, e) is None
            for e in scope.events.get(name, ())
        )

    def collects(self, node: ast.AST, name: str) -> bool:
        """Does pytest collect this def or class under `name`?"""
        if isinstance(node, ast.ClassDef):
            return name.startswith("Test") or node.name in self.unittest
        return name.startswith("test")

    def judge(self, scope: _Scope, name: str, d: _Event):
        """(certainly replaced, rebound markers, decoration markers, captured)."""
        rebound: list[Marker] = []
        marks: list[Marker] = []
        captured = False
        owner = scope.owner if isinstance(scope.owner, ast.ClassDef) else None
        for e in sorted((e for e in scope.events[name] if e.pos > d.pos), key=lambda e: e.pos):
            rel = self.relation(d, e)
            if rel is _EXCLUSIVE or rel is _DEAD:
                continue
            if e.kind == DECORATE:
                guard = rel if isinstance(rel, str) else None
                marks += [replace(m, guard=guard) for m in self.reader.marks(e.decorators, owner)]
                continue
            if e.kind == CAPTURE:
                if self.collects(d.node, e.target) and self.survives(scope, e.target, e.other):
                    captured = True
                continue
            if rel is None:
                return True, rebound, marks, captured
            rebound.append(_rebound_marker(self.reader, e.cite, rel if isinstance(rel, str) else None))
        return False, rebound, marks, captured

    def run(self) -> dict[int, Status]:
        for scope in (self.walk.module, *self.walk.classes.values()):
            for name, events in scope.events.items():
                if len(events) < 2:
                    continue
                for d in events:
                    if d.kind != DEF:
                        continue
                    gone, rebound, marks, captured = self.judge(scope, name, d)
                    status = self.status.setdefault(id(d.node), Status())
                    status.markers += marks
                    if captured or not (gone or rebound):
                        continue
                    if isinstance(d.node, ast.ClassDef):
                        self.rebound_classes.append((scope, d, gone, rebound))
                        status.gone = gone
                        status.rebound = rebound
                        if gone:
                            self.gone.add(id(d.node))
                    else:
                        status.dropped = status.dropped or gone
                        status.markers += rebound
        # A rebound class takes its units with it, except those a collected
        # subclass still runs (Q9).
        for scope, d, gone, rebound in self.rebound_classes:
            kept = self.still_run(scope, d)
            for attribute, events in self.walk.classes[id(d.node)].events.items():
                if attribute in kept:
                    continue
                for event in events:
                    if event.kind != DEF or not any(frame[0] is d.node for frame in event.path):
                        continue
                    status = self.status.setdefault(id(event.node), Status())
                    status.dropped = status.dropped or gone
                    status.markers += [replace(m) for m in rebound]
        return {
            key: status for key, status in self.status.items()
            if status.dropped or status.markers or status.gone or status.rebound
        }

    # -- Q9: a rebound class an earlier subclass still runs --------------------

    def current(self, scope: _Scope, name: str, pos) -> _Event | None:
        """The class statement `name` holds at `pos`, when nothing else bound it since."""
        latest = None
        for e in scope.events.get(name, ()):
            if e.pos < pos and e.kind in (DEF, BIND) and (latest is None or e.pos > latest.pos):
                latest = e
        if latest is None or latest.kind != DEF or not isinstance(latest.node, ast.ClassDef):
            return None
        return latest

    def subclasses(self, scope: _Scope, d: _Event) -> list[_Event]:
        """Classes of this scope whose bases reach `d`'s class, through same-scope classes."""
        found: list[_Event] = []
        frontier = [d]
        seen = {id(d.node)}
        classes = [
            e for events in scope.events.values() for e in events
            if e.kind == DEF and isinstance(e.node, ast.ClassDef)
        ]
        while frontier:
            parent = frontier.pop()
            for e in classes:
                if id(e.node) in seen:
                    continue
                for base in e.node.bases:
                    if not (isinstance(base, ast.Name) and base.id == parent.node.name):
                        continue
                    hit = self.current(scope, base.id, e.pos)
                    if hit is not None and hit.node is parent.node:
                        seen.add(id(e.node))
                        found.append(e)
                        frontier.append(e)
                        break
        return found

    def plain(self, cls: ast.ClassDef) -> bool:
        """A class whose namespace its body says, as `inherited_tests` reads one."""
        inner = self.walk.classes.get(id(cls))
        if inner is None or inner.external or cls.decorator_list or cls.keywords:
            return False
        for stmt in cls.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Pass)):
                continue
            if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
                continue
            if isinstance(stmt, ast.Assign) and all(isinstance(t, ast.Name) for t in stmt.targets):
                continue
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) and stmt.value is not None:
                continue
            return False
        return True

    def mro(self, scope: _Scope, s: _Event, d: _Event):
        """`s`'s method resolution order, with same-scope classes as nodes and other
        bases as opaque tokens; None when it cannot be read."""
        resolved: dict[int, tuple] = {}

        def linear(event: _Event, active: frozenset):
            node = event.node
            if id(node) in resolved:
                return resolved[id(node)]
            if id(node) in active or node.decorator_list or node.keywords:
                return None
            if node is not d.node and not self.plain(node):
                return None
            bases: list = []
            for base in node.bases:
                hit = self.current(scope, base.id, event.pos) if isinstance(base, ast.Name) else None
                bases.append(hit if hit is not None else ("opaque", ast.dump(base)))
            orders = []
            for base in bases:
                if isinstance(base, tuple):
                    orders.append([base])
                    continue
                order = linear(base, active | {id(node)})
                if order is None:
                    return None
                orders.append(list(order))
            heads = [base.node if isinstance(base, _Event) else base for base in bases]
            if len({id(h) if not isinstance(h, tuple) else h for h in heads}) != len(heads):
                return None
            sequences = [order for order in orders if order] + [heads]
            result = [node]
            while any(sequences):
                sequences = [seq for seq in sequences if seq]
                candidate = next(
                    (seq[0] for seq in sequences if not any(seq[0] in other[1:] for other in sequences)), None
                )
                if candidate is None:
                    return None
                result.append(candidate)
                for seq in sequences:
                    if seq and seq[0] == candidate:
                        seq.pop(0)
            resolved[id(node)] = tuple(result)
            return resolved[id(node)]

        return linear(s, frozenset())

    def still_run(self, scope: _Scope, d: _Event) -> set[str]:
        """The attributes of `d`'s class that a collected subclass may still run (Q9)."""
        subclasses = self.subclasses(scope, d)
        if not subclasses:
            return set()
        attributes = set(self.walk.classes[id(d.node)].events)
        kept: set[str] = set()
        for s in subclasses:
            if id(s.node) in self.gone or not self.reader.collectible_class(s.node):
                continue
            order = self.mro(scope, s, d)
            for attribute in attributes - kept:
                if order is None or self.runs(order, d.node, attribute):
                    kept.add(attribute)
        return kept

    def runs(self, order, base: ast.ClassDef, attribute: str) -> bool:
        """Does this order reach `base` for `attribute`, or may it?"""
        for cls in order:
            if cls is base:
                return True
            if isinstance(cls, tuple):
                # An opaque base before it may define the attribute or not.
                return True
            if attribute in self.walk.classes[id(cls)].events:
                return False
        return True


def final_bindings(tree: ast.Module, reader: Reader, *, expressions: bool) -> dict[int, Status]:
    """id(def or class node) -> what its later bindings do to it, for those they change.

    `expressions` reads walrus targets and literal-name `setattr`, `delattr`
    and namespace calls inside expressions; a module that spells none of
    them skips that walk.
    """
    walk = _Walk(tree, reader, expressions)
    for names, attribute, event in walk.attributes:
        scope = walk.resolve(names, event.pos)
        if scope is not None:
            scope.add(attribute, event)
            scope.external = True
    if not any(len(events) > 1 for scope in (walk.module, *walk.classes.values()) for events in scope.events.values()):
        return {}
    return _Judge(walk, reader, tree).run()

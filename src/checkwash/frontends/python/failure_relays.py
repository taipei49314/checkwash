"""Python failure relays: a broad handler that hands the failure to a future the test awaits (D-190).

In a test file a broad `except` is BROAD_EXCEPT_ADDED's swallow when the
block it guards holds an oracle and the handler neither re-raises nor
asserts (SPEC §4). uvloop's regression tests catch a callback's or a
thread's assertion failure that way and pass it, unchanged, to an asyncio
future that the test then awaits, so the failure still fails the test:
D-187 accepted three such false blocks for 0.10 only. This module proves a
bounded spelling of that shape. SPEC §4 "Python failure relays" states the
rules, R1 to R7 with R2b, and the names below follow it.

The frontend keeps its swallow list exactly as before and records which of
its handlers this module proves to be relays; the engine credits the after
side's relays only, and only within what 0.10 counts as added (D-190).

R2 and R2b keep a credited relay off what checkwash protects: it sits in a
function nested in another, in a collected test module and outside any
fixture, and its `try` body neither holds an assertion a parse-time unit
executes nor reads the name of a same-file function such an assertion runs
in. Whatever else a relay that a stand-in defeats could lose, 0.10 already
lets a cheaper edit lose: an oracle no unit executes can be deleted silently
(THREATMODEL row 91), and an assertion reached through a call, such as an
alias, a fixture's closure or a helper from another file, can be swallowed
by a broad handler around a call not named `assert...`, which 0.10 does not
count as a swallow (row 176). R3 to R7 are precision on top
of that: they refuse the spellings they name, and they trust what the file
cannot show (a loop its base class builds, asyncio itself; row 171).

The proof is pure syntax and never imports or runs the test. A `Reader`
is built once per parsed side, the first time a relay-shaped handler needs
it. One walk numbers the nodes in pre-order, so "inside B" is an interval
test, and the per-scope, per-future, per-statement and per-body questions
are memoised; what remains are walks up the scope chain from each relay and
loop read, so the cost is at worst the file's size times the nesting depth
of those scopes. Reachability is read from the statements before the
consumer rather than from `_unreachable_ids`, whose cost on every function
grew with the nesting depth: a review timed a 350 KB chain of 90 nested
coroutines at 11.9 seconds against 0.72 on 0.10. A first prototype took
25.5 seconds for 400 handlers sharing one future, against the PreToolUse
ask's 30-second deadline (2026-10-29 status review).
"""

from __future__ import annotations

import ast
import bisect

from checkwash.frontends.python.literal_conversions import module_bindings
from checkwash.ir.astutil import dotted_name

_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
_FUNCTION_LIKE = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
_SCOPES = (
    ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef,
    ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp,
)
_LOOPS = (ast.For, ast.AsyncFor, ast.While)
_SCHEDULERS = frozenset({"call_soon", "call_soon_threadsafe"})
# R2b (b): the last name of a decorator that makes a def a pytest fixture.
_FIXTURES = frozenset({"fixture", "yield_fixture"})
# R6: what a same-file stand-in for a loop or a future would bind, store,
# name in a string or pass as a keyword.
_PROTOCOL = frozenset({
    "create_future", "call_soon", "call_soon_threadsafe", "run_until_complete",
    "set_exception", "set_result", "__await__", "__getattr__", "__getattribute__",
})
# R6: stored or deleted on any receiver, these could also replace what a
# consumer calls, `fut.result()` among them.
_PROTOCOL_STORES = _PROTOCOL | {"result"}
# R7: the attributes of asyncio the rules read, only ever as a call's function.
_ASYNCIO_READ = frozenset({"Future", "wait_for", "gather"})
# R3: reading or writing a scope, a frame, a closure, an object's attribute
# table or a module by another route, anywhere in the file: these builtins,
# read by name in any way (called, aliased or passed on), `getattr` other
# than called with a string constant for its name, these attributes (a
# call's `monkeypatch.setattr` or `object.__setattr__` included), these
# names, and an import of `importlib` or `builtins`.
_DYNAMIC_BUILTINS = frozenset({
    "locals", "vars", "globals", "eval", "exec", "compile", "__import__", "setattr", "delattr",
})
_DYNAMIC_ATTRIBUTES = frozenset({
    "setattr", "delattr", "__setattr__", "__delattr__", "__dict__", "__closure__", "cell_contents",
    "__code__", "__globals__", "__builtins__", "f_locals", "f_globals", "f_back", "_getframe",
    "currentframe", "getclosurevars", "get_referrers", "get_referents", "get_objects", "modules", "patch",
    "__subclasses__",
})
_DYNAMIC_NAMES = frozenset({"importlib", "patch", "builtins", "__builtins__"})
_DYNAMIC_MODULES = frozenset({"importlib", "builtins"})
_TYPE_PARAMETERS = ("TypeVar", "ParamSpec", "TypeVarTuple")


def _relay(handler: ast.ExceptHandler) -> tuple[ast.Name, ast.AST | None] | None:
    """R1's statement: (F's name in it, the scheduler or None), or None.

    The handler binds the exception as E, and its first statement is
    `F.set_exception(E)` or `L.call_soon(F.set_exception, E)` /
    `L.call_soon_threadsafe(F.set_exception, E)`, with no other argument
    or keyword, where F is a plain name other than E.
    """
    name = handler.name
    if not name or not handler.body:
        return None
    first = handler.body[0]
    if not (isinstance(first, ast.Expr) and isinstance(first.value, ast.Call)):
        return None
    call = first.value
    func = call.func
    if call.keywords or not isinstance(func, ast.Attribute):
        return None
    if func.attr == "set_exception" and len(call.args) == 1:
        target, exception, scheduler = func.value, call.args[0], None
    elif func.attr in _SCHEDULERS and len(call.args) == 2:
        method = call.args[0]
        if not (isinstance(method, ast.Attribute) and method.attr == "set_exception"):
            return None
        target, exception, scheduler = method.value, call.args[1], func.value
    else:
        return None
    if not (isinstance(target, ast.Name) and isinstance(exception, ast.Name)
            and exception.id == name and target.id != name):
        return None
    return target, scheduler


def candidate(handler: ast.ExceptHandler) -> bool:
    """The cheap part of R1: is this handler shaped like a relay at all?"""
    return _relay(handler) is not None


def _root_name(node: ast.AST) -> str | None:
    """The name an attribute or subscript chain starts from: `asyncio` for `asyncio.Future.result`."""
    while isinstance(node, (ast.Attribute, ast.Subscript)):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _children(node: ast.AST):
    """(field, index in a list field or -1, child) for each child node, in `ast.iter_child_nodes` order."""
    for field, value in ast.iter_fields(node):
        if isinstance(value, ast.AST):
            yield field, -1, value
        elif isinstance(value, list):
            for index, item in enumerate(value):
                if isinstance(item, ast.AST):
                    yield field, index, item


def _parameters(scope: ast.AST) -> frozenset[str]:
    arguments = getattr(scope, "args", None)
    if not isinstance(arguments, ast.arguments):
        return frozenset()
    every = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]
    every += [a for a in (arguments.vararg, arguments.kwarg) if a is not None]
    return frozenset(a.arg for a in every)


def _first_positional(function: ast.AST) -> str | None:
    positional = [*function.args.posonlyargs, *function.args.args]
    return positional[0].arg if positional else None


def _own_binders(scope: ast.AST) -> dict[str, list[ast.AST]]:
    """Every name `scope`'s own body binds, read as `fixture_producers._binders` reads one.

    A store or delete, an import alias, an `except ... as` or match
    capture, a `global` or `nonlocal` declaration, and a nested def or class
    of that name. Nested bodies and lambdas are not entered; a
    comprehension's target counts, which only errs toward no credit. A
    lambda's own body is its one expression.
    """
    found: dict[str, list[ast.AST]] = {}
    body = scope.body if isinstance(scope.body, list) else [scope.body]
    stack: list[ast.AST] = list(body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            found.setdefault(node.name, []).append(node)
            continue
        if isinstance(node, ast.Lambda):
            continue
        if isinstance(node, ast.Name):
            if isinstance(node.ctx, (ast.Store, ast.Del)):
                found.setdefault(node.id, []).append(node)
        elif isinstance(node, ast.alias):
            found.setdefault(node.asname or node.name.split(".")[0], []).append(node)
        elif isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)):
            if node.name:
                found.setdefault(node.name, []).append(node)
        elif isinstance(node, ast.MatchMapping):
            if node.rest:
                found.setdefault(node.rest, []).append(node)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            for name in node.names:
                found.setdefault(name, []).append(node)
        stack.extend(ast.iter_child_nodes(node))
    return found


class _Index:
    """Pre-order positions of one kind of node, by name: "inside B" is a bisect."""

    def __init__(self) -> None:
        self.positions: dict[str, list[int]] = {}
        self.nodes: dict[str, list[ast.AST]] = {}

    def add(self, key: str, position: int, node: ast.AST) -> None:
        self.positions.setdefault(key, []).append(position)
        self.nodes.setdefault(key, []).append(node)

    def within(self, key: str, start: int, stop: int) -> list[ast.AST]:
        """The nodes under `key` whose position lies in [start, stop)."""
        positions = self.positions.get(key)
        if not positions:
            return []
        low = bisect.bisect_left(positions, start)
        high = bisect.bisect_left(positions, stop, low)
        return self.nodes[key][low:high]

    def any_within(self, key: str, start: int, stop: int) -> bool:
        positions = self.positions.get(key)
        if not positions:
            return False
        low = bisect.bisect_left(positions, start)
        return low < len(positions) and positions[low] < stop


def _any_between(positions: list[int] | None, start: int, stop: int) -> bool:
    if not positions:
        return False
    low = bisect.bisect_left(positions, start)
    return low < len(positions) and positions[low] < stop


class _Future:
    """What R3 to R5 found for one future F bound in one function B."""

    __slots__ = ("set_exception", "set_result", "proven")

    def __init__(self, set_exception: list[ast.AST], set_result: list[ast.AST], proven: bool) -> None:
        self.set_exception = set_exception
        self.set_result = set_result
        self.proven = proven


class Reader:
    """Proves failure relays in one parsed side (R1 to R7, SPEC §4, D-190).

    `off` is the parse's `_Offsets` (its text and tree); `unit_spans` are
    the character spans of every assertion a parse-time unit executes
    (`UnitSide.assertions`), the coordinates `Assertion.span` uses.
    """

    def __init__(self, tree: ast.Module, off, unit_spans) -> None:
        # The frontend imports this module, so its helpers are read once it
        # has loaded, as gating.py reads it.
        from checkwash.frontends.python import frontend

        self._fe = frontend
        self._tree = tree
        self._off = off
        spans = sorted(unit_spans)
        self._unit_spans = spans
        self._unit_starts = [start for start, _end in spans]
        self._parent: dict[int, ast.AST] = {}
        self._field: dict[int, str] = {}
        self._index: dict[int, int] = {}
        self._pre: dict[int, int] = {}
        self._end: dict[int, int] = {}
        self._scope: dict[int, ast.AST | None] = {}  # the nearest scope, the module included
        self._def: dict[int, ast.AST | None] = {}    # the nearest def; lambdas, comprehensions, classes transparent
        self._fn: dict[int, ast.AST | None] = {}     # the nearest def or lambda
        self._names = _Index()          # Name nodes by identifier, any context
        self._attribute_nodes: dict[str, list[ast.AST]] = {}  # Attribute nodes by name, any context
        self._loads: dict[str, list[ast.AST]] = {}  # name and attribute loads, by spelling (R2)
        self._bindings = _Index()       # every binding of a name, in any scope
        self._nonlocals = _Index()      # `nonlocal` declarations by name
        self._stores = _Index()         # attribute stores and deletes by attribute name
        self._returns: dict[int, list[int]] = {}   # per nearest def or lambda: its returns
        self._generators: set[int] = set()          # functions holding a yield
        self._functions: list[ast.AST] = []         # defs and lambdas, for R2
        self._classes: list[ast.ClassDef] = []
        self._strings: set[str] = set()
        self._dynamic = False           # R3, anywhere in the file
        self._asyncio_loose = False     # R7: asyncio read other than as `asyncio.<attr>`, or imported otherwise
        self._protocol_keyword = False  # R6: a keyword argument named like the protocol
        self._owns: dict[int, dict[str, list[ast.AST]]] = {}
        self._number(tree)
        self._module_classes = frozenset(
            node.name for node in tree.body if isinstance(node, ast.ClassDef))
        self._class_bound = frozenset(
            name for cls in self._classes for name in self._own(cls))
        self._stand_ins: bool | None = None
        self._asyncio: bool | None = None
        self._asserting: dict[int, list[int]] | None = None
        self._futures: dict[tuple[int, str], _Future | None] = {}
        self._loops: dict[int, bool] = {}
        self._attributes: dict[tuple[str, int], bool] = {}
        self._redirects: dict[str, bool] = {}
        self._completions: dict[int, bool] = {}
        self._fixtures: dict[int, bool] = {}
        self._lives: dict[int, bool] = {}
        self._runs: dict[int, bool] = {}
        self._first_stops: dict[tuple[int, str], int] = {}
        self._jumps: dict[int, bool] = {}

    # --- one walk ----------------------------------------------------------

    def _number(self, tree: ast.Module) -> None:
        """Number every node in pre-order and index what the rules look up."""
        parent, field, index, pre, end = self._parent, self._field, self._index, self._pre, self._end
        scope, nearest_def, nearest_fn = self._scope, self._def, self._fn
        count = 0
        pre[id(tree)] = count
        scope[id(tree)] = None
        count += 1
        stack = [(tree, _children(tree))]
        while stack:
            node, children = stack[-1]
            following = next(children, None)
            if following is None:
                end[id(node)] = count
                stack.pop()
                continue
            name, position, child = following
            key = id(child)
            parent[key] = node
            field[key] = name
            index[key] = position
            pre[key] = count
            scope[key] = node if isinstance(node, (*_SCOPES, ast.Module)) else scope[id(node)]
            nearest_def[key] = node if isinstance(node, _FUNCTIONS) else nearest_def.get(id(node))
            nearest_fn[key] = node if isinstance(node, _FUNCTION_LIKE) else nearest_fn.get(id(node))
            self._note(child, count, node)
            count += 1
            stack.append((child, _children(child)))

    def _note(self, node: ast.AST, position: int, parent: ast.AST) -> None:
        if isinstance(node, ast.Name):
            self._names.add(node.id, position, node)
            if isinstance(node.ctx, (ast.Store, ast.Del)):
                self._bindings.add(node.id, position, node)
            else:
                self._loads.setdefault(node.id, []).append(node)
                if node.id == "asyncio" and not (isinstance(parent, ast.Attribute) and parent.value is node):
                    self._asyncio_loose = True
                if node.id in _DYNAMIC_NAMES or node.id in _DYNAMIC_BUILTINS:
                    self._dynamic = True
                elif node.id == "getattr" and not (
                        isinstance(parent, ast.Call) and parent.func is node and len(parent.args) >= 2
                        and isinstance(parent.args[1], ast.Constant) and isinstance(parent.args[1].value, str)):
                    self._dynamic = True
        elif isinstance(node, ast.Attribute):
            self._attribute_nodes.setdefault(node.attr, []).append(node)
            if isinstance(node.ctx, (ast.Store, ast.Del)):
                self._stores.add(node.attr, position, node)
                if _root_name(node) == "asyncio":
                    self._asyncio_loose = True
            else:
                self._loads.setdefault(node.attr, []).append(node)
                if (node.attr in _ASYNCIO_READ and isinstance(node.value, ast.Name) and node.value.id == "asyncio"
                        and not (isinstance(parent, ast.Call) and parent.func is node)):
                    self._asyncio_loose = True
            if node.attr in _DYNAMIC_ATTRIBUTES:
                self._dynamic = True
        elif isinstance(node, ast.Constant):
            if isinstance(node.value, str):
                self._strings.add(node.value)
        elif isinstance(node, ast.keyword):
            if node.arg in _PROTOCOL:
                self._protocol_keyword = True
        elif isinstance(node, ast.Return):
            self._returns.setdefault(id(self._fn.get(id(node))), []).append(position)
        elif isinstance(node, (ast.Yield, ast.YieldFrom)):
            self._generators.add(id(self._fn.get(id(node))))
        elif isinstance(node, ast.arg):
            self._bindings.add(node.arg, position, node)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            self._bindings.add(node.name, position, node)
            if isinstance(node, ast.ClassDef):
                self._classes.append(node)
            else:
                self._functions.append(node)
        elif isinstance(node, ast.Lambda):
            self._functions.append(node)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root == "asyncio" and alias.asname:
                    self._asyncio_loose = True
                elif root in _DYNAMIC_MODULES:
                    self._dynamic = True
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root == "asyncio":
                self._asyncio_loose = True
            elif root in _DYNAMIC_MODULES:
                self._dynamic = True
        elif isinstance(node, ast.alias):
            if node.name != "*":
                self._bindings.add(node.asname or node.name.split(".")[0], position, node)
        elif isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)):
            if node.name:
                self._bindings.add(node.name, position, node)
        elif isinstance(node, ast.MatchMapping):
            if node.rest:
                self._bindings.add(node.rest, position, node)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            for name in node.names:
                self._bindings.add(name, position, node)
                if isinstance(node, ast.Nonlocal):
                    self._nonlocals.add(name, position, node)
        elif type(node).__name__ in _TYPE_PARAMETERS:
            self._bindings.add(node.name, position, node)

    # --- structure ---------------------------------------------------------

    def _up(self, node: ast.AST) -> ast.AST | None:
        return self._parent.get(id(node))

    def _span(self, node: ast.AST) -> tuple[int, int]:
        """The positions strictly inside `node`: its descendants."""
        return self._pre[id(node)] + 1, self._end[id(node)]

    def _scope_of(self, node: ast.AST) -> ast.AST | None:
        """The nearest scope (or the module) holding `node`."""
        return self._scope.get(id(node))

    def _own(self, scope: ast.AST) -> dict[str, list[ast.AST]]:
        found = self._owns.get(id(scope))
        if found is None:
            found = self._owns[id(scope)] = _own_binders(scope)
        return found

    def _binds(self, scope: ast.AST, name: str) -> bool:
        return name in self._own(scope) or name in _parameters(scope)

    # --- the proof ---------------------------------------------------------

    def proven(self, handler: ast.ExceptHandler, try_node: ast.AST) -> bool:
        """Is `handler`, of `try_node`, a proven failure relay (R1 to R7)?"""
        # try/except* is not read: an except* handler sees an exception group.
        if not isinstance(try_node, ast.Try):
            return False
        shape = _relay(handler)
        if shape is None:
            return False
        # R3: nothing in the file reaches a scope, a frame, a closure, an
        # attribute table or a module by another route.
        if self._dynamic:
            return False
        target, scheduler = shape
        # R1: the try lies in a function S, with no loop between them.
        holder = self._up(try_node)
        while holder is not None and not isinstance(holder, (*_SCOPES, ast.Module)):
            if isinstance(holder, _LOOPS):
                return False
            holder = self._up(holder)
        if not isinstance(holder, _FUNCTIONS):
            return False
        # R2b (c): S is nested in another function, not a module-level def
        # or a method. How S is called is not read: a unit that calls S
        # itself folds S's assertions, which R2 refuses.
        if not isinstance(self._scope_of(holder), _FUNCTIONS):
            return False
        # R2b (b): no function enclosing the try is a pytest fixture.
        if not self._fixture_free(holder):
            return False
        # R2: the try body neither holds an assertion a unit executes nor
        # reads the name of a function such an assertion runs in.
        if self._guards_unit_assertion(try_node) or self._reaches_unit_assertion(try_node, holder):
            return False
        future = self._future_of(holder, target.id)
        if future is None:
            return False
        if scheduler is not None and not self._trusted_loop(scheduler):
            return False
        # R4: this relay is the only set_exception site, and every
        # set_result is a direct statement of this try's else clause.
        if len(future.set_exception) != 1 or future.set_exception[0] is not target:
            return False
        if any(self._up(stmt) is not try_node or self._field.get(id(stmt)) != "orelse"
               for stmt in future.set_result):
            return False
        # R5: a proven consumer.
        return future.proven

    def _fixture_free(self, function: ast.AST) -> bool:
        """R2b (b): neither `function` nor a def enclosing it is a pytest fixture, memoised per def.

        Any decorator whose last name is `fixture` or `yield_fixture` counts,
        `pytest_asyncio.fixture` among them, which the frontend's own
        fixture reading does not know.
        """
        chain: list[ast.AST] = []
        node: ast.AST | None = function
        known: bool | None = None
        while node is not None:
            known = self._fixtures.get(id(node))
            if known is not None:
                break
            chain.append(node)
            node = self._def.get(id(node))
        result = True if known is None else known
        for enclosing in reversed(chain):
            result = result and not self._fe._is_fixture_def(enclosing) and not any(
                (dotted_name(d.func if isinstance(d, ast.Call) else d) or "").rsplit(".", 1)[-1] in _FIXTURES
                for d in enclosing.decorator_list)
            self._fixtures[id(enclosing)] = result
        return result

    def _guards_unit_assertion(self, try_node: ast.Try) -> bool:
        """R2, in character offsets, as `Assertion.span` records them."""
        if not self._unit_spans or not try_node.body:
            return False
        start = self._off.span(try_node.body[0])[0]
        stop = self._off.span(try_node.body[-1])[1]
        spans = self._unit_spans
        index = bisect.bisect_left(self._unit_starts, start)
        while index < len(spans) and spans[index][0] < stop:
            if spans[index][1] <= stop:
                return True
            index += 1
        return False

    def _reaches_unit_assertion(self, try_node: ast.Try, holder: ast.AST) -> bool:
        """R2 through a call: the try body, outside nested defs, reads an asserting name."""
        if not self._unit_spans or not try_node.body:
            return False
        positions = self._asserting_loads().get(id(holder))
        return _any_between(positions, self._pre[id(try_node.body[0])], self._end[id(try_node.body[-1])])

    def _asserting_loads(self) -> dict[int, list[int]]:
        """Per def, the positions of its reads of an asserting name (R2).

        A def or lambda is asserting when an assertion a parse-time unit
        executes lies in its own body, or when it reads an asserting name; a
        def's name, its class's when it is a method, and the names a lambda
        is assigned to are asserting names. Names match by spelling, as a
        name or an attribute, anywhere in the file, and a def's reads
        include those in its lambdas, comprehensions and class bodies, so
        a same-name function elsewhere only errs toward no credit.
        """
        if self._asserting is None:
            found: dict[int, list[int]] = {}
            for name in self._asserting_names():
                for use in self._loads.get(name, ()):
                    found.setdefault(id(self._def.get(id(use))), []).append(self._pre[id(use)])
            for positions in found.values():
                positions.sort()
            self._asserting = found
        return self._asserting

    def _asserting_names(self) -> set[str]:
        marked: set[int] = set()
        names: set[str] = set()
        queue: list[str] = []

        def mark(function: ast.AST | None) -> None:
            if function is None or id(function) in marked:
                return
            marked.add(id(function))
            for name in self._names_of(function):
                if name not in names:
                    names.add(name)
                    queue.append(name)

        # The innermost def or lambda around each unit assertion: one sweep
        # over the functions' character spans, which nest as the tree does.
        intervals = []
        for function in self._functions:
            start, end = self._off.span(function)
            intervals.append((start, -end, self._pre[id(function)], function))
        intervals.sort(key=lambda interval: interval[:3])
        open_functions: list[tuple[int, ast.AST]] = []
        following = 0
        for start, end in self._unit_spans:
            while following < len(intervals) and intervals[following][0] <= start:
                begin, negative_end, _position, function = intervals[following]
                following += 1
                while open_functions and open_functions[-1][0] <= begin:
                    open_functions.pop()
                open_functions.append((-negative_end, function))
            while open_functions and open_functions[-1][0] < end:
                open_functions.pop()
            if open_functions:
                function = open_functions[-1][1]
                mark(function)
                if isinstance(function, ast.Lambda):
                    mark(self._def.get(id(function)))
        while queue:
            for use in self._loads.get(queue.pop(), ()):
                mark(self._fn.get(id(use)))
                mark(self._def.get(id(use)))
        return names

    def _names_of(self, function: ast.AST) -> list[str]:
        up = self._up(function)
        if isinstance(function, _FUNCTIONS):
            return [function.name, up.name] if isinstance(up, ast.ClassDef) else [function.name]
        targets: list[ast.AST] = []
        if isinstance(up, ast.Assign) and up.value is function:
            targets = up.targets
        elif isinstance(up, (ast.AnnAssign, ast.NamedExpr)) and up.value is function:
            targets = [up.target]
        return [t.id if isinstance(t, ast.Name) else t.attr
                for t in targets if isinstance(t, (ast.Name, ast.Attribute))]

    # --- R3 to R5: the future ------------------------------------------------

    def _future_of(self, holder: ast.AST, name: str) -> _Future | None:
        """R3: resolve F outward from S through function scopes only."""
        scope: ast.AST | None = holder
        while scope is not None and not isinstance(scope, ast.Module):
            if isinstance(scope, ast.ClassDef):
                return None
            if isinstance(scope, _FUNCTIONS) and self._binds(scope, name):
                break
            scope = self._scope_of(scope)
        if not isinstance(scope, _FUNCTIONS):
            return None
        key = (id(scope), name)
        if key not in self._futures:
            self._futures[key] = self._read_future(scope, name)
        return self._futures[key]

    def _read_future(self, b: ast.AST, name: str) -> _Future | None:
        # R5: B's own failure reaches its caller.
        if not self._completes(b):
            return None
        start, stop = self._span(b)
        # Exactly one binding of F in B's whole subtree, nested scopes,
        # parameters and `global`/`nonlocal` included: the single Name
        # target of an Assign that is a direct statement of B's body.
        binders = self._bindings.within(name, start, stop)
        if len(binders) != 1:
            return None
        target = binders[0]
        statement = self._up(target)
        if not (isinstance(target, ast.Name) and isinstance(statement, ast.Assign)
                and len(statement.targets) == 1 and statement.targets[0] is target
                and self._up(statement) is b and self._field.get(id(statement)) == "body"):
            return None
        if not self._creates_future(statement.value):
            return None
        set_exception: list[ast.AST] = []
        set_result: list[ast.AST] = []
        proven = False
        for use in self._names.within(name, start, stop):
            if use is target:
                continue
            up = self._up(use)
            if isinstance(up, ast.Attribute) and up.attr == "set_exception":
                set_exception.append(use)
                continue
            if isinstance(up, ast.Attribute) and up.attr == "set_result":
                site = self._set_result_statement(up)
                if site is None:
                    return None
                set_result.append(site)
                continue
            found = self._consumer(use)
            if found is None:
                return None  # R4: any other use of F
            if not proven and self._proves(found, b):
                proven = True
        return _Future(set_exception, set_result, proven)

    def _completes(self, b: ast.AST) -> bool:
        """R5: B is no generator and every read of its name is a proven call; a nested B is called and undecorated.

        The name is read as a name or an attribute anywhere in the file, and
        each read must be the function of a call outside any lambda, in a
        statement that nothing in its function can swallow
        (`_unswallowed`). So B is not handed to a thread, the loop or another
        callable, and a failure of its call reaches that function; a loop or
        an `if` around the call can only keep B from running. An async B's
        coroutine is not followed further: one that is scheduled and never
        awaited is open (row 171), and so is a failure lost above the
        calling function. A B defined at module level or as a method of a
        module-level class may go uncalled and keeps its decorators, which
        mark tests.
        """
        known = self._completions.get(id(b))
        if known is None:
            scope = self._scope_of(b)
            nested = not (isinstance(scope, ast.Module) or (
                isinstance(scope, ast.ClassDef) and isinstance(self._scope_of(scope), ast.Module)))
            known = (id(b) not in self._generators and not (nested and b.decorator_list)
                     and self._called_as_proven(b, nested))
            self._completions[id(b)] = known
        return known

    def _called_as_proven(self, b: ast.AST, nested: bool) -> bool:
        reads = [*self._names.nodes.get(b.name, ()), *self._attribute_nodes.get(b.name, ())]
        if nested and not reads:
            return False
        for node in reads:
            call = self._up(node)
            if not (isinstance(node.ctx, ast.Load) and isinstance(call, ast.Call) and call.func is node
                    and not isinstance(self._fn.get(id(node)), ast.Lambda)):
                return False
            statement = call
            while statement is not None and not isinstance(statement, ast.stmt):
                statement = self._up(statement)
            g = self._fn.get(id(statement)) if statement is not None else None
            if not isinstance(g, _FUNCTIONS) or not self._unswallowed(statement, g):
                return False
        return True

    def _unswallowed(self, statement: ast.AST, g: ast.AST) -> bool:
        """Nothing between the statement and G can swallow its failure.

        The walk up to G passes no `try` body with a handler, no part of a
        `try` whose finally clause returns, breaks or continues, and no
        `with` body unless every item is `s.attr(...)` R6 trusts.
        """
        node = statement
        while True:
            up, field = self._up(node), self._field.get(id(node))
            if up is None:
                return False
            if up is g:
                return True
            if isinstance(up, (ast.Try, ast.TryStar)):
                if (up.handlers and field == "body") or (field != "finalbody" and self._finally_jumps(up)):
                    return False
            elif isinstance(up, (ast.With, ast.AsyncWith)):
                if field == "body" and not self._trusted_items(up):
                    return False
            node = up

    def _trusted_items(self, with_node: ast.AST) -> bool:
        """Every item is `s.attr(...)` with `s.attr` trusted as R6 trusts a loop."""
        return all(isinstance(item.context_expr, ast.Call) and self._trusted_loop(item.context_expr.func)
                   for item in with_node.items)

    def _creates_future(self, value: ast.AST) -> bool:
        """R3: `asyncio.Future()`, `asyncio.Future(loop=<trusted L>)` or `<trusted L>.create_future()`."""
        if not isinstance(value, ast.Call):
            return False
        func = value.func
        if self._is_asyncio(func, "Future"):
            if value.args or any(keyword.arg != "loop" for keyword in value.keywords):
                return False
            return self._stand_in_free() and all(self._trusted_loop(k.value) for k in value.keywords)
        return (isinstance(func, ast.Attribute) and func.attr == "create_future"
                and not value.args and not value.keywords and self._trusted_loop(func.value))

    def _set_result_statement(self, method: ast.Attribute) -> ast.AST | None:
        """R4: the Expr statement of `F.set_result(x)` or `<trusted L>.call_soon[_threadsafe](F.set_result, x)`."""
        call = self._up(method)
        if not isinstance(call, ast.Call) or call.keywords:
            return None
        if call.func is method:
            if len(call.args) != 1 or isinstance(call.args[0], ast.Starred):
                return None
        elif not (isinstance(call.func, ast.Attribute) and call.func.attr in _SCHEDULERS
                  and len(call.args) == 2 and call.args[0] is method
                  and not isinstance(call.args[1], ast.Starred)
                  and self._trusted_loop(call.func.value)):
            return None
        statement = self._up(call)
        return statement if isinstance(statement, ast.Expr) and statement.value is call else None

    def _consumer(self, use: ast.Name) -> tuple[ast.AST, str] | None:
        """R5's consuming statement holding this load of F, with its kind, or None.

        An Expr, or an Assign whose value is `await A` (inside an async def),
        `<trusted L>.run_until_complete(A)` or `F.result()`, where A is F,
        `asyncio.wait_for(A', ...)` with A' first, or `asyncio.gather(..., A',
        ...)` with A' a direct positional argument, no `**` and
        `return_exceptions` absent or literal False.
        """
        node, up = use, self._up(use)
        if isinstance(up, ast.Attribute) and up.attr == "result":
            root = self._up(up)
            if not (isinstance(root, ast.Call) and root.func is up and not root.args and not root.keywords):
                return None
            kind = "result"
        else:
            while isinstance(up, ast.Call) and self._passes_on(up, node):
                node, up = up, self._up(up)
            if isinstance(up, ast.Await) and up.value is node:
                root, kind = up, "await"
            elif (isinstance(up, ast.Call) and isinstance(up.func, ast.Attribute)
                  and up.func.attr == "run_until_complete" and len(up.args) == 1
                  and up.args[0] is node and not up.keywords and self._trusted_loop(up.func.value)):
                root, kind = up, "run"
            else:
                return None
        statement = self._up(root)
        if isinstance(statement, (ast.Expr, ast.Assign)) and statement.value is root:
            return statement, kind
        return None

    def _passes_on(self, call: ast.Call, argument: ast.AST) -> bool:
        """`asyncio.wait_for(argument, ...)`, or `asyncio.gather(...)` with it among its arguments (R5, R7)."""
        if self._is_asyncio(call.func, "wait_for"):
            return bool(call.args) and call.args[0] is argument
        if self._is_asyncio(call.func, "gather"):
            if not any(a is argument for a in call.args):
                return False
            for keyword in call.keywords:
                if keyword.arg is None:
                    return False
                if keyword.arg == "return_exceptions" and not (
                        isinstance(keyword.value, ast.Constant) and keyword.value.value is False):
                    return False
            return True
        return False

    def _proves(self, found: tuple[ast.AST, str], b: ast.AST) -> bool:
        """R5: the consuming statement is proven in B, or in a coroutine B runs."""
        statement, kind = found
        c = self._scope_of(statement)
        if not isinstance(c, _FUNCTIONS):
            return False
        if kind == "await" and not isinstance(c, ast.AsyncFunctionDef):
            return False
        if not self._live(statement, c):
            return False
        if c is b:
            return True
        return (self._up(c) is b and self._field.get(id(c)) == "body" and not c.decorator_list
                and id(c) not in self._generators and self._run_from(c, b))

    def _run_from(self, c: ast.AST, b: ast.AST) -> bool:
        """R5: B binds C's name only by that def and runs `C(...)` from a proven statement."""
        known = self._runs.get(id(c))
        if known is not None:
            return known
        result = False
        binders = self._own(b).get(c.name, [])
        if len(binders) == 1 and binders[0] is c and c.name not in _parameters(b):
            start, stop = self._span(b)
            for use in self._names.within(c.name, start, stop):
                call = self._up(use)
                if not (isinstance(call, ast.Call) and call.func is use):
                    continue
                up = self._up(call)
                if isinstance(up, ast.Await) and up.value is call:
                    root = up
                    if not isinstance(b, ast.AsyncFunctionDef):
                        continue
                elif (isinstance(up, ast.Call) and isinstance(up.func, ast.Attribute)
                      and up.func.attr == "run_until_complete" and len(up.args) == 1
                      and up.args[0] is call and not up.keywords and self._trusted_loop(up.func.value)):
                    root = up
                else:
                    continue
                statement = self._up(root)
                if not (isinstance(statement, (ast.Expr, ast.Assign)) and statement.value is root):
                    continue
                if self._scope_of(statement) is b and self._live(statement, b):
                    result = True
                    break
        self._runs[id(c)] = result
        return result

    def _live(self, statement: ast.AST, g: ast.AST) -> bool:
        """R5's "proven in G": nothing between the statement and G can skip it or swallow its failure.

        Up to G the walk passes only the body or finally clause of a `try`
        that has no handler and whose finally clause neither returns, breaks
        nor continues, and the body of a `with` whose every item is
        `s.attr(...)` with `s.attr` trusted as R6 trusts a loop: a context
        manager the test's base class provides, such as uvloop's
        `self.tcp_client(...)`, never one the file names or builds, whose
        `__exit__` may suppress whatever it is called; and no statement
        before it, at any level of the walk, is a `return` or a `raise` or
        holds a `return` outside nested functions. With no handler on the
        walk, a `raise` nested in an earlier statement leaves G uncaught, so
        it fails or skips the test and never lets it pass: uvloop opens
        tests with `if self.implementation == 'asyncio': raise
        unittest.SkipTest()`. A guarded `return` refuses whatever its guard,
        which is stricter than `_unreachable_ids`; the reading is linear,
        where `_unreachable_ids` on each function would grow with the
        nesting depth.
        """
        known = self._lives.get(id(statement))
        if known is not None:
            return known
        result = True
        node = statement
        while True:
            up = self._up(node)
            field = self._field.get(id(node))
            if up is None or self._stops_before(up, field, node):
                result = False
                break
            if up is g:
                break
            if isinstance(up, ast.Try):
                if up.handlers or field not in ("body", "finalbody") or self._finally_jumps(up):
                    result = False
                    break
            elif isinstance(up, (ast.With, ast.AsyncWith)):
                if field != "body" or not self._trusted_items(up):
                    result = False
                    break
            else:
                result = False
                break
            node = up
        self._lives[id(statement)] = result
        return result

    def _stops_before(self, parent: ast.AST, field: str | None, node: ast.AST) -> bool:
        """A statement before `node` in its body is a `return` or `raise`, or holds a `return`."""
        body = getattr(parent, field, None) if field else None
        if not isinstance(body, list):
            return True
        key = (id(parent), field)
        first = self._first_stops.get(key)
        if first is None:
            first = len(body)
            for index, stmt in enumerate(body):
                if self._stops(stmt):
                    first = index
                    break
            self._first_stops[key] = first
        return first < self._index[id(node)]

    def _stops(self, stmt: ast.AST) -> bool:
        """`stmt` is a `raise`, or is or holds a `return` outside nested defs and lambdas."""
        return isinstance(stmt, ast.Raise) or _any_between(
            self._returns.get(id(self._fn.get(id(stmt)))), self._pre[id(stmt)], self._end[id(stmt)])

    def _finally_jumps(self, try_node: ast.AST) -> bool:
        """Its finally clause returns, breaks or continues, outside nested scopes."""
        key = id(try_node)
        if key not in self._jumps:
            stack: list[ast.AST] = list(try_node.finalbody)
            jumps = False
            while stack and not jumps:
                node = stack.pop()
                if isinstance(node, (ast.Return, ast.Break, ast.Continue)):
                    jumps = True
                elif not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                    stack.extend(ast.iter_child_nodes(node))
            self._jumps[key] = jumps
        return self._jumps[key]

    # --- R6: the trusted loop ----------------------------------------------

    def _trusted_loop(self, expr: ast.AST) -> bool:
        known = self._loops.get(id(expr))
        if known is None:
            known = self._loops[id(expr)] = self._read_loop(expr)
        return known

    def _read_loop(self, expr: ast.AST) -> bool:
        """R6: `s.attr`, or a name bound once to it, in a method of a module-level class.

        M, the outermost function holding the use, is defined directly in a
        module-level class body, with only function or lambda scopes between
        it and the use, and is neither a staticmethod nor a classmethod; s
        is its first positional parameter, bound neither in M nor in any
        scope between. Nothing in the file may redirect `attr`
        (`_attribute_trusted`), and the file is stand-in free.
        """
        if not self._stand_in_free():
            return False
        found = self._method(expr)
        if found is None:
            return False
        m, inner = found
        receiver = _first_positional(m)
        if receiver is None or receiver in self._own(m) or any(self._binds(s, receiver) for s in inner):
            return False
        if isinstance(expr, ast.Attribute):
            if not (isinstance(expr.value, ast.Name) and expr.value.id == receiver):
                return False
            attr = expr.attr
        elif isinstance(expr, ast.Name):
            attr = self._loop_alias(expr.id, inner, m, receiver)
            if attr is None:
                return False
        else:
            return False
        return self._attribute_trusted(attr, m)

    def _method(self, use: ast.AST) -> tuple[ast.AST, list[ast.AST]] | None:
        """(M, the scopes between the use and M), or None."""
        scopes: list[ast.AST] = []
        node = self._up(use)
        while node is not None and not isinstance(node, ast.Module):
            if isinstance(node, ast.ClassDef):
                if not scopes or not isinstance(scopes[-1], _FUNCTIONS):
                    return None
                m = scopes[-1]
                if self._up(m) is not node or not isinstance(self._up(node), ast.Module):
                    return None
                if any((dotted_name(d) or "").rsplit(".", 1)[-1] in ("staticmethod", "classmethod")
                       for d in m.decorator_list):
                    return None
                return m, scopes[:-1]
            if isinstance(node, _SCOPES):
                if not isinstance(node, (*_FUNCTIONS, ast.Lambda)):
                    return None
                scopes.append(node)
            node = self._up(node)
        return None

    def _loop_alias(self, name: str, inner: list[ast.AST], m: ast.AST, receiver: str) -> str | None:
        """The attr of `name = receiver.attr`, the one binding of `name` in the first function binding it."""
        for scope in (*inner, m):
            if not self._binds(scope, name):
                continue
            if not isinstance(scope, _FUNCTIONS) or name in _parameters(scope):
                return None
            binders = self._own(scope).get(name, [])
            if len(binders) != 1:
                return None
            target = binders[0]
            statement = self._up(target)
            if not (isinstance(target, ast.Name) and isinstance(statement, ast.Assign)
                    and len(statement.targets) == 1 and statement.targets[0] is target
                    and self._up(statement) is scope and self._field.get(id(statement)) == "body"):
                return None
            value = statement.value
            if not (isinstance(value, ast.Attribute) and isinstance(value.value, ast.Name)
                    and value.value.id == receiver):
                return None
            if self._nonlocals.any_within(name, *self._span(scope)):
                return None
            return value.attr
        return None

    def _attribute_trusted(self, attr: str, m: ast.AST) -> bool:
        """R6: nothing in the file can redirect `attr` for M's receiver.

        No class body binds it, no string constant equals it, nothing inside
        M stores or deletes it on any receiver, and every store or delete of
        it elsewhere is on a fresh local (`_fresh_receiver`).
        """
        key = (attr, id(m))
        known = self._attributes.get(key)
        if known is None:
            known = (attr not in self._class_bound and attr not in self._strings
                     and not self._redirected(attr)
                     and not self._stores.any_within(attr, *self._span(m)))
            self._attributes[key] = known
        return known

    def _redirected(self, attr: str) -> bool:
        known = self._redirects.get(attr)
        if known is None:
            known = not all(self._fresh_receiver(store) for store in self._stores.nodes.get(attr, ()))
            self._redirects[attr] = known
        return known

    def _fresh_receiver(self, store: ast.Attribute) -> bool:
        """R6: the store's receiver is a local bound only to the result of a call that reads no parameter.

        A plain name, inside a function, that is a parameter neither of
        that function nor of one enclosing it, and that the function binds
        only by direct assignments of a call's result, as uvloop's
        `proto = MyProto(loop=loop)` then `proto.loop = loop`, where no
        call reads a parameter of those functions. So an alias of the
        receiver (`me = self`, `me = (lambda x: x)(self)`), a helper's
        parameter (`case.loop = ...`), a module-level class and anything
        that is not a plain name all count as redirecting.
        """
        receiver = store.value
        owner = self._def.get(id(store))
        if not isinstance(receiver, ast.Name) or owner is None:
            return False
        name = receiver.id
        parameters: set[str] = set()
        scope: ast.AST | None = owner
        while scope is not None:
            if isinstance(scope, _FUNCTION_LIKE):
                parameters |= _parameters(scope)
            scope = self._scope_of(scope)
        if name in parameters:
            return False
        binders = self._own(owner).get(name)
        if not binders:
            return False
        for target in binders:
            statement = self._up(target)
            if not (isinstance(target, ast.Name) and isinstance(statement, ast.Assign)
                    and isinstance(statement.value, ast.Call)):
                return False
            if any(isinstance(node, ast.Name) and node.id in parameters for node in ast.walk(statement.value)):
                return False
        return True

    def _stand_in_free(self) -> bool:
        """R6: no class body binds, nothing stores, no string names and no keyword argument is a protocol name.

        A store or delete of `result` on any receiver counts as well.
        """
        if self._stand_ins is None:
            self._stand_ins = (
                not (self._class_bound & _PROTOCOL)
                and not any(attr in self._stores.nodes for attr in _PROTOCOL_STORES)
                and not (self._strings & _PROTOCOL)
                and not self._protocol_keyword
            )
        return self._stand_ins

    # --- R7: asyncio --------------------------------------------------------

    def _is_asyncio(self, expr: ast.AST, attr: str) -> bool:
        return (isinstance(expr, ast.Attribute) and expr.attr == attr and isinstance(expr.value, ast.Name)
                and expr.value.id == "asyncio" and self._asyncio_trusted())

    def _asyncio_trusted(self) -> bool:
        """R7: the name asyncio is the real module wherever this file reads it.

        Every binding of the name, counted in all scopes, is a module-level
        `import asyncio` or `import asyncio.<sub>` without `as`; asyncio is
        imported no other way (no `as`, no `from asyncio... import`) and
        there is no star import; the name is read only as `asyncio.<attr>`,
        and `asyncio.Future`, `asyncio.wait_for` and `asyncio.gather` only as
        a call's function, so never aliased, subclassed or patched; nothing
        stores or deletes anything reached from it (`asyncio.Future.result`
        included), or an attribute named `Future`, `wait_for` or `gather` on
        any receiver; and no string constant starts with "asyncio." or
        equals one of those three names.
        """
        if self._asyncio is None:
            counts, star = self._fe._bindings(self._off) or module_bindings(self._tree)
            top = sum(
                1 for statement in self._tree.body if isinstance(statement, ast.Import)
                for alias in statement.names
                if alias.asname is None and (alias.name == "asyncio" or alias.name.startswith("asyncio."))
            )
            self._asyncio = (
                not star and top > 0 and counts["asyncio"] == top
                and not self._asyncio_loose
                and not any(attr in self._stores.nodes for attr in _ASYNCIO_READ)
                and not (self._strings & _ASYNCIO_READ)
                and not any(string.startswith("asyncio.") for string in self._strings)
            )
        return self._asyncio

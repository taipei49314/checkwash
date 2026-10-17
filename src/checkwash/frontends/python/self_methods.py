"""Helper methods a test reaches through its instance (#306).

In a method unit, `self._check(value)` runs the method `_check` that the
class running the test resolves: its own body, then its same-file bases in
method resolution order (ruling 306, Q1 (a), Q2 (a)). The method is
followed as a module helper is: its assertions are the unit's, and a skip it
ends in is the unit's skip. The receiver is the method's first positional
parameter, as `self.skipTest` reads it, and only while the method never
rebinds it.

A call resolves only when nothing in the file can make another function
answer it (ruling 306, 2026-10-14):

- Sub-Q2: the order is a local C3 over the module's top-level classes, with
  each base the file does not define kept as an opaque entry. The name
  resolves only in a same-file class reached before the first opaque entry.
  It stays unresolved on a C3 failure, a class name the module binds more
  than once, a decorator on the running class or on any class up to the one
  that binds the name, or a metaclass (or any class keyword),
  `__init_subclass__` or `__getattribute__` on any same-file class in the
  order.
- Sub-Q3: in the first class of the order that binds the name, its one
  binding is a plain def in the class body, not under `if` or `try`. Nowhere
  in the module does code store or delete `.<name>`, store into a
  `.__dict__`, call `setattr`, `delattr` or `object.__setattr__` with that
  literal name (or with a computed name on a receiver or on a class of the
  order), or name it in `patch.object` or `monkeypatch.setattr`; and no
  class of the order defines `__setattr__`.
- Sub-Q4: only an undecorated `def` or `async def` resolves, so a
  `staticmethod` or `classmethod` called through the instance does not.
- Sub-Q6: a name `unittest.TestCase` defines is never followed, in any
  class: the call keeps the reading it has always had.
"""

from __future__ import annotations

import ast

from checkwash.frontends.python.class_attributes import receivers
from checkwash.ir.astutil import dotted_name

# The names unittest.TestCase defines, as a fixed literal list: their union
# over Python 3.11 to 3.14, never read from the running interpreter (Sub-Q6).
TESTCASE_NAMES = frozenset({
    "__call__", "__eq__", "__hash__", "__init__", "__init_subclass__", "__repr__", "__str__",
    "_addDuration", "_addExpectedFailure", "_addSkip", "_addUnexpectedSuccess", "_baseAssertEqual",
    "_callCleanup", "_callSetUp", "_callTearDown", "_callTestMethod", "_classSetupFailed",
    "_class_cleanups", "_cleanups", "_deprecate", "_diffThreshold", "_formatMessage",
    "_getAssertEqualityFunc", "_outcome", "_subtest", "_testMethodDoc", "_testMethodName",
    "_truncateMessage", "_type_equality_funcs",
    "addClassCleanup", "addCleanup", "addTypeEqualityFunc",
    "assertAlmostEqual", "assertAlmostEquals", "assertCountEqual", "assertDictContainsSubset",
    "assertDictEqual", "assertEndsWith", "assertEqual", "assertEquals", "assertFalse", "assertGreater",
    "assertGreaterEqual", "assertHasAttr", "assertIn", "assertIs", "assertIsInstance", "assertIsNone",
    "assertIsNot", "assertIsNotNone", "assertIsSubclass", "assertLess", "assertLessEqual",
    "assertListEqual", "assertLogs", "assertMultiLineEqual", "assertNoLogs", "assertNotAlmostEqual",
    "assertNotAlmostEquals", "assertNotEndsWith", "assertNotEqual", "assertNotEquals",
    "assertNotHasAttr", "assertNotIn", "assertNotIsInstance", "assertNotIsSubclass", "assertNotRegex",
    "assertNotRegexpMatches", "assertNotStartsWith", "assertRaises", "assertRaisesRegex",
    "assertRaisesRegexp", "assertRegex", "assertRegexpMatches", "assertSequenceEqual", "assertSetEqual",
    "assertStartsWith", "assertTrue", "assertTupleEqual", "assertWarns", "assertWarnsRegex", "assert_",
    "countTestCases", "debug", "defaultTestResult", "doClassCleanups", "doCleanups",
    "enterClassContext", "enterContext", "fail", "failIf", "failIfAlmostEqual", "failIfEqual",
    "failUnless", "failUnlessAlmostEqual", "failUnlessEqual", "failUnlessRaises", "failureException",
    "id", "longMessage", "maxDiff", "run", "setUp", "setUpClass", "shortDescription", "skipTest",
    "subTest", "tearDown", "tearDownClass",
})

_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef)
# Names a same-file class in the order must not define: each lets the class
# answer an attribute lookup with something its body does not say.
_LOOKUP = ("__init_subclass__", "__getattribute__")
_SETATTR = {"setattr", "delattr", "object.__setattr__", "object.__delattr__"}


def _literal(node) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _root(node) -> str | None:
    while isinstance(node, (ast.Attribute, ast.Subscript, ast.Call)):
        node = node.func if isinstance(node, ast.Call) else node.value
    return node.id if isinstance(node, ast.Name) else None


def _class_binds(cls: ast.ClassDef) -> dict[str, list[ast.stmt]]:
    """name -> each top-level statement of the class body that binds it, at any depth.

    A def under an `if` or a `try` is bound by that compound statement, so it
    is no plain def of the class body (Sub-Q3).
    """
    from checkwash.frontends.python.setup_skip_controls import _names

    out: dict[str, list[ast.stmt]] = {}
    for statement in cls.body:
        for name in _names([statement]):
            out.setdefault(name, []).append(statement)
    return out


class Methods:
    """One module's same-file method resolution for calls through an instance."""

    def __init__(self, tree: ast.Module) -> None:
        self.classes: dict[str, ast.ClassDef] = {}
        counts: dict[str, int] = {}
        for statement in tree.body:
            if isinstance(statement, ast.ClassDef):
                self.classes.setdefault(statement.name, statement)
        # A class name bound by anything but its one class statement.
        self.rebound: set[str] = set()
        for statement in tree.body:
            if isinstance(statement, (*_DEFS, ast.ClassDef)) and statement.name in self.classes:
                counts[statement.name] = counts.get(statement.name, 0) + 1
        self.rebound.update(name for name, count in counts.items() if count > 1)
        # Attribute names something stores or deletes, and literal names
        # reflective calls or patches name, anywhere in the module.
        self.stored: set[str] = set()
        self.dict_store = False
        self.computed: set[str] = set()  # receiver roots of a computed-name setattr/delattr
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)) and node.id in self.classes:
                self.rebound.add(node.id)
            elif isinstance(node, ast.alias) and (node.asname or node.name.split(".")[0]) in self.classes:
                self.rebound.add(node.asname or node.name.split(".")[0])
            elif isinstance(node, ast.Attribute) and isinstance(node.ctx, (ast.Store, ast.Del)):
                self.stored.add(node.attr)
            elif isinstance(node, ast.Subscript) and isinstance(node.ctx, (ast.Store, ast.Del)):
                if isinstance(node.value, ast.Attribute) and node.value.attr == "__dict__":
                    self.dict_store = True
            elif isinstance(node, ast.Call):
                self._call(node)
        self._orders: dict[int, tuple | None] = {}
        self._binds: dict[int, dict[str, list[ast.stmt]]] = {}
        self._resolved: dict[tuple[int, str], tuple | None] = {}

    def _call(self, node: ast.Call) -> None:
        name = dotted_name(node.func) or ""
        if name in _SETATTR and len(node.args) >= 2:
            key = _literal(node.args[1])
            if key is not None:
                self.stored.add(key)
            else:
                self.computed.add(_root(node.args[0]) or "")
        elif (name.endswith("patch.object") or name.endswith("monkeypatch.setattr")) and node.args:
            key = _literal(node.args[1]) if len(node.args) >= 2 else None
            if key is not None:
                self.stored.add(key)
            target = _literal(node.args[0])
            if target is not None:
                self.stored.add(target.rsplit(".", 1)[-1])

    def binds(self, cls: ast.ClassDef) -> dict[str, list[ast.stmt]]:
        if id(cls) not in self._binds:
            self._binds[id(cls)] = _class_binds(cls)
        return self._binds[id(cls)]

    def order(self, cls: ast.ClassDef) -> tuple | None:
        """`cls`'s local C3 order: same-file classes as nodes, other bases as opaque
        tokens, or None when it cannot be read (Sub-Q2)."""
        if id(cls) in self._orders:
            return self._orders[id(cls)]
        self._orders[id(cls)] = None  # a cycle reads as unresolvable

        def linear(node: ast.ClassDef, active: frozenset):
            if node.name in active or node.name in self.rebound or self.classes.get(node.name) is not node:
                return None
            if node.keywords:
                return None
            bases: list = []
            for base in node.bases:
                local = self.classes.get(base.id) if isinstance(base, ast.Name) else None
                bases.append(local if local is not None else ("opaque", ast.dump(base)))
            orders = []
            for base in bases:
                if isinstance(base, tuple):
                    orders.append([base])
                    continue
                order = linear(base, active | {node.name})
                if order is None:
                    return None
                orders.append(list(order))
            heads = list(bases)
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
            return tuple(result)

        found = linear(cls, frozenset())
        self._orders[id(cls)] = found
        return found

    def resolve(self, cls: ast.ClassDef | None, name: str, receiver: str | None = None):
        """(method def, the class that defines it) a call `<receiver>.<name>()` runs
        in an instance of `cls`, or None when the file does not settle it."""
        if cls is None or name in TESTCASE_NAMES or name in self.stored or self.dict_store:
            return None
        if receiver is not None and receiver in self.computed:
            return None
        key = (id(cls), name)
        if key not in self._resolved:
            self._resolved[key] = self._resolve(cls, name)
        return self._resolved[key]

    def _resolve(self, cls: ast.ClassDef, name: str):
        order = self.order(cls)
        if order is None:
            return None
        local = [entry for entry in order if not isinstance(entry, tuple)]
        if any(lookup in self.binds(entry) for entry in local for lookup in (*_LOOKUP, "__setattr__")):
            return None
        if any(entry.name in self.computed for entry in local):
            return None
        for entry in order:
            if isinstance(entry, tuple):
                # An opaque base may define it or not.
                return None
            if entry.decorator_list:
                return None
            bindings = self.binds(entry).get(name)
            if not bindings:
                continue
            if len(bindings) != 1 or not isinstance(bindings[0], _DEFS) or bindings[0] not in entry.body:
                return None
            method = bindings[0]
            if method.decorator_list:
                return None
            return method, entry
        return None


def receiver(function) -> str | None:
    """The name a method reads its instance through, when it never rebinds it."""
    names = receivers(function)
    return next(iter(names)) if names else None


def instance_calls(nodes, name: str | None):
    """Each call `<name>.<attr>(...)` among `nodes`, with the attribute it names."""
    if name is None:
        return []
    return [
        (node, node.func.attr)
        for node in nodes
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name) and node.func.value.id == name
    ]

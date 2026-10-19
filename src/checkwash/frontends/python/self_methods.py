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
  that binds the name, unless it returns the class it decorates, or a
  metaclass (or any class keyword), `__init_subclass__` or
  `__getattribute__` on any same-file class in the order. Only the module's
  own name counts as bound again (#487): a statement at module scope, under
  a compound statement too, the header of a def, class or lambda there, or
  an assignment expression in a comprehension there binds it; a function,
  lambda or class body is read as binding a local name, unless a body
  declares it `global` (a metaclass whose `__prepare__` returns the module's
  namespace is not read). The decorators that return the class are a fixed
  list (#487), read through the module's import bindings with no `*` or
  `**` argument: `pytest.mark.<name>`, bare or called, but not with one
  positional argument that is not a constant, which pytest returns to
  decorate the class itself; and unittest's `skip(<str>)`,
  `skipIf(<condition>, <str>)` and `skipUnless(<condition>, <str>)`, with
  the reason a string literal, and bare `expectedFailure`. A form that can
  disable a test (unittest's, `parametrize`, or a mark that is not only a
  label) is transparent only on the running class and only where its units
  carry it: a skip in a spelling the frontend reads as one, or a
  `usefixtures` of literal names. A root the module binds more than once,
  declares `global` or stores or deletes an attribute or item under, or
  that a star import may bind, is opaque, and so is every form of a package
  that a store, setter or patch reaches through its target, by any name an
  import binds into the package or by a dotted string.
- Sub-Q3: in the first class of the order that binds the name, its one
  binding is a plain def in the class body, not under `if` or `try`. Nowhere
  in the module does code store or delete `.<name>`, call `setattr`,
  `delattr` or `object.__setattr__` with that literal name (or with a
  computed name on a receiver or on a class of the order), or name it in
  `patch.object` or `monkeypatch.setattr`; and no class of the order defines
  `__setattr__`. Since #502 these also name it: a call whose last name is
  `__setattr__` or `__delattr__`, by the first str literal of its first two
  positional arguments (`self.__setattr__("_check", f)`,
  `type.__setattr__(C, "_check", f)`); a keyword or a literal dict key of
  `update()`, or the literal key of `setdefault()`, on `x.__dict__` or
  `vars(x)`; and in a class body a literal key of `vars()` or `locals()`
  stored, deleted, or written by those calls, `__setitem__` or `__delitem__`.
  No name resolves anywhere in the module after a store into or del from
  `x.__dict__[...]` or `vars(x)[...]` with any key (`vars(C)[...]` raises at
  run time, as `C.__dict__[...]` does, and is read the same way), a
  `__setitem__` or `__delitem__` on either, a store or del of `x.__dict__`
  itself (`=`, `|=`, a literal-name setattr), or any of these writes whose
  name is not a literal: a `**` argument or another mapping in `update()`, a
  computed key, a `__setattr__` or `__delattr__` with no literal name, a
  `setattr` or `delattr` whose target or name is a starred argument
  (`setattr(*(C, "_check", f))`). A computed-name `setattr`
  on a plain alias of the receiver or of a class of the order counts as one
  on it, one hop (`x = C`, `x = type(self)`, `x = self.__class__`, bound in
  the call's own scope, a def or lambda around it, or the module), and one
  whose target is reached through a subscript or another call
  (`globals()["C"]`) counts as one on every class.
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
_SETATTR = {"setattr", "delattr", "object.__setattr__", "object.__delattr__",
            "builtins.setattr", "builtins.delattr"}
# The last names of calls that write into their first argument (#487).
_SETTERS = frozenset({"setattr", "delattr", "setitem", "delitem",
                      "__setattr__", "__delattr__", "__setitem__", "__delitem__"})
_DICT_SETTERS = frozenset({"update", "setdefault", "pop", "popitem", "clear", "__setitem__", "__delitem__"})
# The namespace methods that rebind a helper's name (#502): `update` and
# `setdefault` by the names they write, `__setitem__` and `__delitem__` as
# the item store and del they spell. A deletion from an instance's namespace
# shows the class's def again, so `pop`, `popitem` and `clear` are not read.
_NAMESPACE_WRITES = frozenset({"update", "setdefault", "__setitem__", "__delitem__"})
# Matched by a call's last name, bound or unbound (#502).
_DUNDER_SETTERS = frozenset({"__setattr__", "__delattr__"})
# unittest's class decorators that return the class they decorate, as a
# fixed literal list read through the bindings to `unittest` or
# `unittest.case` (#487; `Lib/unittest/case.py` of CPython 3.11 to 3.14):
# each skip by the position of its reason, which `reason=` may pass instead.
# Bare, a skip returns its inner function; and a function passed as the
# reason comes back wrapped, so only a string literal is read.
_SKIPS = {
    "unittest.skip": 0, "unittest.case.skip": 0,
    "unittest.skipIf": 1, "unittest.case.skipIf": 1,
    "unittest.skipUnless": 1, "unittest.case.skipUnless": 1,
}
_EXPECTED = frozenset({"unittest.expectedFailure", "unittest.case.expectedFailure"})
# The marks that skip or xfail a test, as `frontend._SKIP_DECORATORS` reads them.
_SKIP_MARKS = frozenset({"skip", "skipif", "xfail"})
_COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)


def _is_mark(full: str) -> bool:
    """Is this dotted target `pytest.mark.<name>`? `MarkGenerator.__getattr__`
    rejects a name that starts with `_`."""
    parts = full.split(".")
    return len(parts) == 3 and parts[:2] == ["pytest", "mark"] and not parts[2].startswith("_")


def _skips(full: str) -> bool:
    """Is this transparent form one the frontend reads as a skip of the class it decorates?"""
    return full in _SKIPS or full in _EXPECTED or (_is_mark(full) and full.rsplit(".", 1)[-1] in _SKIP_MARKS)


def _disables(full: str) -> bool:
    """Can this transparent form disable the tests of the class it decorates?

    unittest's forms skip or xfail; a mark can unless it only labels an
    item (#209 Q2): `usefixtures`, `dependency` and any mark named for a
    skip or an xfail; and `parametrize`, whose class-level rows the frontend
    does not read (an empty list skips every test).
    """
    from checkwash.frontends.python.hook_guards import _labelling

    mark = full.rsplit(".", 1)[-1]
    return _skips(full) or (_is_mark(full) and (mark == "parametrize" or not _labelling(mark)))


def _carried(full: str, name: str, call: ast.Call | None) -> bool:
    """Do the units of the class this disabling form decorates carry it?

    The frontend reads a skip by its trailing name (`frontend._canonical_marker`),
    so not under another one (`from unittest import skipIf as when`), and a
    `usefixtures` of literal names (`setup_skip_controls._usefixtures`).
    Nothing reads `dependency`, a mark only named for a skip, or a class's
    `parametrize` rows.
    """
    if _skips(full):
        from checkwash.frontends.python.frontend import _canonical_marker

        return _canonical_marker(name) is not None
    if full == "pytest.mark.usefixtures":
        return call is None or (not call.keywords and all(_literal(arg) is not None for arg in call.args))
    return False


def _through_dict(node) -> bool:
    """Is this `x.__dict__` or `vars(x)`?"""
    return getattr(node, "attr", None) == "__dict__" or (
        isinstance(node, ast.Call) and dotted_name(node.func) == "vars")


def _object_namespace(node) -> bool:
    """Is this an object's namespace, `x.__dict__` or `vars(x)` with an argument (#502)?"""
    if isinstance(node, ast.Attribute):
        return node.attr == "__dict__"
    return (isinstance(node, ast.Call) and dotted_name(node.func) in ("vars", "builtins.vars")
            and bool(node.args or node.keywords))


def _class_namespace(node) -> bool:
    """Is this `vars()` or `locals()` with no argument, a class's namespace in its body (#502)?

    At module scope it is the module's namespace and in a function its
    locals, where a write rebinds no method.
    """
    return (isinstance(node, ast.Call) and not node.args and not node.keywords
            and dotted_name(node.func) in ("vars", "locals", "builtins.vars", "builtins.locals"))


def _scoped(tree: ast.Module):
    """(node, scopes) for each node of the module (#502).

    `scopes` runs from the module to the def, lambda or class whose body
    holds the node. A def's, lambda's or class's header (`_header`) runs in
    the scope that holds it. A comprehension is read as part of its scope.
    """
    stack = [(statement, (tree,)) for statement in tree.body]
    while stack:
        node, scopes = stack.pop()
        yield node, scopes
        if isinstance(node, (*_DEFS, ast.ClassDef, ast.Lambda)):
            stack.extend((child, scopes) for child in _header(node))
            inner = (*scopes, node)
            stack.extend((child, inner) for child in ([node.body] if isinstance(node, ast.Lambda) else node.body))
        else:
            stack.extend((child, scopes) for child in ast.iter_child_nodes(node))


def _target(node) -> str | None:
    """The name a computed-name `setattr` writes under (#502).

    `x` for `x`, `x.attr`, `x.__class__` or `type(x)`, as `_root` reads them;
    None when the target is reached through a subscript or another call
    (`globals()["C"]`, `make()`), or is no name at all.
    """
    while True:
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "type"
                and len(node.args) == 1 and not node.keywords):
            node = node.args[0]
        elif isinstance(node, ast.Attribute):
            node = node.value
        else:
            return node.id if isinstance(node, ast.Name) else None


def _module(target: str) -> str:
    """The package of a native dotted target; `_pytest` and `py.test` are pytest's."""
    top = target.split(".")[0]
    return "pytest" if top in ("_pytest", "py") else top


def _header(node) -> list:
    """The parts of a def, class or lambda that run in the scope holding it."""
    if isinstance(node, ast.ClassDef):
        return [*node.decorator_list, *node.bases, *node.keywords]
    if isinstance(node, ast.Lambda):
        return [node.args]
    return [*node.decorator_list, node.args, *([node.returns] if node.returns is not None else [])]


def _module_binds(tree: ast.Module):
    """(name, node) for each binding of a name in module scope (ruling 487 (c)).

    That is each statement at module scope, under a compound statement too,
    with an `except ... as` or a match capture there, and the header of each
    def, class and lambda in it: decorators, bases, class keywords, defaults
    and annotations. A comprehension's own targets bind its scope, but an
    assignment expression in it binds this one (PEP 572). No function,
    lambda or class body is read: what it binds is local, unless it declares
    the name `global`, which the caller reads.
    """
    stack = [(statement, False) for statement in tree.body]
    while stack:
        node, comprehension = stack.pop()
        if isinstance(node, (*_DEFS, ast.ClassDef, ast.Lambda)):
            if not isinstance(node, ast.Lambda):
                yield node.name, node
            children = _header(node)
        elif isinstance(node, ast.NamedExpr):
            yield node.target.id, node.target
            children = [node.value]
        else:
            if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)) and not comprehension:
                yield node.id, node
            elif isinstance(node, ast.alias):
                yield node.asname or node.name.split(".")[0], node
            elif isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)) and node.name:
                yield node.name, node
            elif isinstance(node, ast.MatchMapping) and node.rest:
                yield node.rest, node
            children = list(ast.iter_child_nodes(node))
            comprehension = comprehension or isinstance(node, _COMPREHENSIONS)
        stack.extend((child, comprehension) for child in children)


def _literal(node) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _root(node) -> str | None:
    while isinstance(node, (ast.Attribute, ast.Subscript, ast.Call)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "type"
                and len(node.args) == 1 and not node.keywords):
            # `type(self)` is the receiver's class, as `self.__class__` is.
            node = node.args[0]
            continue
        node = node.func if isinstance(node, ast.Call) else node.value
    return node.id if isinstance(node, ast.Name) else None


def _argument(node: ast.Call, position: int, keyword: str):
    """The call's argument at `position`, or passed as `keyword`, or None."""
    if len(node.args) > position:
        return node.args[position]
    return next((k.value for k in node.keywords if k.arg == keyword), None)


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
        from checkwash.frontends.python.setup_skip_controls import _names, module_bindings

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
        # Only a binding of the module's own name rebinds it (ruling 487 (c)).
        # Another class or def of that name under a module-level `if` or `try`
        # may be the one that runs (Sub-Q2); one in a body is local.
        scoped: dict[str, int] = {}
        for name, node in _module_binds(tree):
            scoped[name] = scoped.get(name, 0) + 1
            if name in self.classes and node is not self.classes[name]:
                self.rebound.add(name)
        # A class decorator is read through the module's import bindings
        # (#487). A decorator runs when its class statement does, so a root
        # bound more than once is opaque in any order: counted per top-level
        # statement, as `OwnMarks` counts (#358), and per binding in module
        # scope, which also reads the headers `_names` stops at. A star
        # import may bind any root.
        self._bindings = module_bindings(tree)
        per_statement: dict[str, int] = {}
        for statement in tree.body:
            for name in _names([statement]):
                per_statement[name] = per_statement.get(name, 0) + 1
        self._opaque = {name for name, count in (*per_statement.items(), *scoped.items()) if count > 1}
        self._star = "*" in scoped
        # A store, `setattr` or patch under any name an import anywhere binds
        # into a package changes that package for every spelling of it
        # (#487): `pytest.mark.slow = wrap` reaches `@mark.slow` too, and
        # `from _pytest.mark.structures import MarkDecorator` is pytest's.
        self._imported: dict[str, set[str]] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    local = alias.asname or alias.name.split(".")[0]
                    self._imported.setdefault(local, set()).add(_module(alias.name))
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                for alias in node.names:
                    if alias.name != "*":
                        self._imported.setdefault(alias.asname or alias.name, set()).add(_module(node.module))
        self._mutated: set[str] = set()
        # Attribute names something stores or deletes, and literal names
        # reflective calls, patches or namespace writes name, anywhere in the
        # module.
        self.stored: set[str] = set()
        # A write that may bind any name: into `x.__dict__[...]` or
        # `vars(x)[...]`, or one whose name is not a literal (#502).
        self.dict_store = False
        # Receiver roots of a computed-name setattr/delattr, and of the plain
        # aliases they are written through (#502).
        self.computed: set[str] = set()
        # A computed-name setattr whose target is no name: any class (#502).
        self.any_class = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Global):
                # A body that declares the name `global` binds the module's
                # (ruling 487 (c)).
                self.rebound.update(name for name in node.names if name in self.classes)
                self._opaque.update(node.names)
            elif isinstance(node, ast.Attribute) and isinstance(node.ctx, (ast.Store, ast.Del)):
                self.stored.add(node.attr)
                # A stored `pytest.mark.slow` wins over the mark
                # `MarkGenerator.__getattr__` would make (#487).
                self._opaque.add(_root(node) or "")
                self._mutate(node)
            elif isinstance(node, ast.Subscript) and isinstance(node.ctx, (ast.Store, ast.Del)):
                if _object_namespace(node.value):
                    # `x.__dict__[...]` or `vars(x)[...]`, for any key (#502).
                    self.dict_store = True
                self._opaque.add(_root(node) or "")
                self._mutate(node)
            elif isinstance(node, ast.Call):
                self._call(node)
        self._namespaces(tree)
        if "__dict__" in self.stored:
            # `x.__dict__ = ...`, `|=`, `del` or a literal-name setattr of it
            # replaces a whole namespace (#502).
            self.dict_store = True
        self._orders: dict[int, tuple | None] = {}
        self._binds: dict[int, dict[str, list[ast.stmt]]] = {}
        self._resolved: dict[tuple[int, str], tuple | None] = {}

    def _call(self, node: ast.Call) -> None:
        name = dotted_name(node.func) or ""
        self._writes(node, name)
        if name in _SETATTR and len(node.args) >= 2:
            key = _literal(node.args[1])
            if key is not None:
                self.stored.add(key)
            else:
                self.computed.add(_root(node.args[0]) or "")
        elif name.endswith("patch.object") or name.endswith("monkeypatch.setattr"):
            # By position or by keyword: `patch.object(target, attribute)`,
            # `monkeypatch.setattr(target, name)`.
            key = _literal(_argument(node, 1, "attribute" if name.endswith("patch.object") else "name"))
            if key is not None:
                self.stored.add(key)
            target = _literal(_argument(node, 0, "target"))
            if target is not None:
                self.stored.add(target.rsplit(".", 1)[-1])

    def _namespaces(self, tree: ast.Module) -> None:
        """The rebinding spellings #502 adds to Sub-Q3's (ruling 502, items 1 to 4).

        A class body's `vars()` or `locals()` is its namespace, so a literal
        key written there rebinds that name. A computed-name `setattr` or
        `delattr` is followed one hop through a plain assignment of its
        target's name, `x = <value>` (or an annotated or walrus one), as
        Python looks the name up: in the call's own scope, the defs and
        lambdas around it, and the module. A value that is no name, as
        `_target` reads it (`x = make()`), is not followed.
        """
        aliases: dict[tuple[int, str], list] = {}
        targets: list[tuple[ast.expr, tuple]] = []
        for node, scopes in _scoped(tree):
            in_class = isinstance(scopes[-1], ast.ClassDef)
            if isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)) and node.value is not None:
                for target in node.targets if isinstance(node, ast.Assign) else [node.target]:
                    if isinstance(target, ast.Name):
                        aliases.setdefault((id(scopes[-1]), target.id), []).append(node.value)
            elif isinstance(node, ast.Subscript) and isinstance(node.ctx, (ast.Store, ast.Del)):
                if in_class and _class_namespace(node.value):
                    self._key(node.slice)
            elif isinstance(node, ast.Call):
                self._namespace_call(node, in_class)
                if (dotted_name(node.func) or "") in _SETATTR:
                    if any(isinstance(arg, ast.Starred) for arg in node.args[:2]):
                        # `setattr(*(C, "_check", f))`: any target, any name.
                        self.dict_store = True
                    elif len(node.args) >= 2 and _literal(node.args[1]) is None:
                        targets.append((node.args[0], scopes))
        for target, scopes in targets:
            root = _target(target)
            if root is None:
                # `setattr(globals()["C"], NAME, f)`: every class (item 4).
                self.any_class = True
                continue
            self.computed.add(root)
            around = [scope for scope in reversed(scopes[:-1]) if not isinstance(scope, ast.ClassDef)]
            for scope in (scopes[-1], *around):
                for value in aliases.get((id(scope), root), ()):
                    alias = _target(value)
                    if alias is not None:
                        self.computed.add(alias)

    def _namespace_call(self, node: ast.Call, in_class: bool) -> None:
        """A call that rebinds a name through a namespace or a dunder setter (#502)."""
        func = node.func
        last = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if last in _DUNDER_SETTERS:
            # A bound call carries the name first (`self.__setattr__("_check", f)`),
            # an unbound one second (`type.__setattr__(C, "_check", f)`).
            first = node.args[:2]
            if any(isinstance(arg, ast.Starred) for arg in first):
                self.dict_store = True
            else:
                self._key(next((arg for arg in first if _literal(arg) is not None), None))
            return
        if not isinstance(func, ast.Attribute) or last not in _NAMESPACE_WRITES:
            return
        by_key = in_class and _class_namespace(func.value)
        if not (by_key or _object_namespace(func.value)):
            return
        if last == "update":
            if (any(keyword.arg is None for keyword in node.keywords) or len(node.args) > 1
                    or (node.args and not isinstance(node.args[0], ast.Dict))):
                # `update(**attrs)`, `update(attrs)`: any name.
                self.dict_store = True
                return
            self.stored.update(keyword.arg for keyword in node.keywords)
            for key in node.args[0].keys if node.args else ():
                self._key(key)  # a `**` entry's key is None: any name
        elif last == "setdefault" or by_key:
            self._key(node.args[0] if node.args else None)
        else:
            # `x.__dict__.__setitem__(...)` is the item store it spells: any name.
            self.dict_store = True

    def _key(self, node) -> None:
        """A name a namespace write gives: a str literal rebinds it, anything else every name (#502)."""
        key = _literal(node)
        if key is None:
            self.dict_store = True
        else:
            self.stored.add(key)

    def _writes(self, node: ast.Call, name: str) -> None:
        """Record the packages a call that may write into its target reaches (#487).

        A setter or deleter by its last name (`setattr`, `b.setattr`,
        `type.__setattr__`, `monkeypatch.setitem`), any `patch` (`patch.object`,
        `patch.multiple`, `patch.dict`, a dotted-string target), and a dict
        method on `x.__dict__` or `vars(x)` write into their first argument,
        a bound `x.__setattr__(...)` into `x`. Only the target is read, never
        the value: `patch.object(Total, "rate", mock.Mock())` reaches no
        package through `mock`.
        """
        func = node.func
        last = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        owner = func.value if isinstance(func, ast.Attribute) else None
        dict_owner = owner is not None and _through_dict(owner)
        if not (last in _SETTERS or "patch" in name.split(".")
                or last in _DICT_SETTERS and (dict_owner or node.args and _through_dict(node.args[0]))):
            return
        if any(isinstance(arg, ast.Starred) for arg in node.args):
            # `setattr(*(target, name, value))`: any argument may be the target.
            targets = list(node.args)
        else:
            first = node.args[0] if node.args else _argument(node, 0, "target") or _argument(node, 0, "in_dict")
            targets = [first] if first is not None else []
        if owner is not None and (last.startswith("__") or dict_owner):
            targets.append(owner)
        for target in targets:
            self._mutate(target)
            text = _literal(target)
            if text is not None:
                # `mock.patch("pytest.mark.slow", wrap)`
                self._mutated.add(_module(text))

    def _mutate(self, target) -> None:
        """Record the packages a store's, `setattr`'s or patch's target names (#487)."""
        for node in ast.walk(target):
            if isinstance(node, ast.Name):
                self._mutated.update(self._imported.get(node.id, ()))

    def _transparent(self, decorator, running: bool) -> bool:
        """Does this class decorator return the class it decorates (#487)?

        `running` says whether it decorates the class running the test.
        """
        call = decorator if isinstance(decorator, ast.Call) else None
        name = dotted_name(call.func if call is not None else decorator)
        if name is None:
            return False
        first, dot, rest = name.partition(".")
        target = self._bindings.get(first)
        if not target or first in self._opaque or self._star or _module(target) in self._mutated:
            return False
        full = target + dot + rest
        if _disables(full) and not (running and _carried(full, name, call)):
            # A form that can disable a test is admitted only where the units
            # carry it: a base's decorators reach only its own units
            # (THREATMODEL row 117), and the running class's units carry only
            # what the frontend reads (#487).
            return False
        if call is None:
            return _is_mark(full) or full in _EXPECTED
        if any(isinstance(arg, ast.Starred) for arg in call.args) or any(k.arg is None for k in call.keywords):
            # `*` and `**` pass what the call does not spell.
            return False
        if _is_mark(full):
            # `MarkDecorator` returns a lone class or function argument, and
            # that then decorates the class.
            return not (len(call.args) == 1 and not call.keywords and not isinstance(call.args[0], ast.Constant))
        position = _SKIPS.get(full)
        if position is None:
            return False
        if len(call.args) == position + 1 and not call.keywords:
            reason = call.args[position]
        elif len(call.args) == position and [k.arg for k in call.keywords] == ["reason"]:
            reason = call.keywords[0].value
        else:
            return False
        return _literal(reason) is not None

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
        if self.any_class or any(entry.name in self.computed for entry in local):
            return None
        for entry in order:
            if isinstance(entry, tuple):
                # An opaque base may define it or not.
                return None
            if not all(self._transparent(decorator, entry is cls) for decorator in entry.decorator_list):
                # Any other decorator may replace the class (#487).
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

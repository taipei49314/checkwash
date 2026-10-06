"""Class attributes a skip guard reads, resolved from class bodies (#254).

`if self.item_class is None: raise unittest.SkipTest(...)` reads an attribute
the test's class sets in its body. When the unit's class, or a base class of
it in the same file, assigns the attribute exactly once, unconditionally, in
its class body, the guard is read with that value, as a guard's module
constants are (ruling 254.Q1). Three kinds of value are used:

- a literal (`None`, `True`, `0`, `"x"`, a tuple of literals);
- a class or a function the file defines, a builtin class or function, a
  lambda, or `staticmethod`/`classmethod` of one of those: not `None`, true,
  and equal to nothing but itself;
- a name the file imports: not `None`, as the ruling has it for the class or
  the function it names. Only `is None` and `is not None` are read: what else
  holds depends on the object, which this file does not show.

Anything else stays unknown, and so does an attribute the file assigns any
other way: through an attribute target anywhere in the module (an instance's
`self.item_class = ...`, or `TotalTest.item_class = ...`), more than once or
under a statement in the class body, by `setattr`, or reflectively. Code a
string literal hands to `eval` or `exec` is read with the module. So is a
private name (`_x`) unknown: the framework sets some on the instance.

The lookup reads the unit's class and its same-file bases, each with a single
base. None of them may carry a decorator or a class keyword: the decorator or
the metaclass receives a class of the chain and may rebind any attribute of
it or of a class derived from it. None may define `__getattribute__`. The
chain must end in a class that derives from nothing, from `object` or from
unittest's `TestCase`. Any other base, or a second one, may set the attribute
on the instance from code this file does not show: Django's `TestCase` sets
`self.client`.

What runs outside the file is not read, as for module constants: a conftest
or a plugin that sets the attribute, the module an imported name comes from
binding it to `None`, or code a computed string hands to `eval` or `exec`.

`crediting_subclasses` serves ruling 254.Q2: a same-file subclass that runs a
base's test unchanged, adding nothing but attribute values and tests of its
own.
"""
from __future__ import annotations

import ast
import builtins
import copy
import types

NONE = "none"
OBJECT = "object"
NOT_NONE = "not-none"

# Calls through which code can bind or read attributes this reading does not see.
_REFLECTIVE = frozenset({"setattr", "delattr", "globals", "locals", "vars", "__import__"})
# Calls that run code from a string, and the mode to parse a literal one in.
_RUNS_CODE = {"eval": "eval", "exec": "exec"}
# Attributes that reach a class body's namespace or an object's attributes by the back door.
_REFLECTIVE_ATTRIBUTES = frozenset({"__dict__", "__setattr__", "_getframe", "currentframe", "f_locals",
                                    "f_globals"})
# Rebinding one of these replaces where an attribute lookup looks.
_LOOKUP_ATTRIBUTES = frozenset({"__dict__", "__class__", "__bases__"})
# unittest's test case classes set only private names on an instance.
_UNITTEST_CASES = frozenset({"TestCase", "IsolatedAsyncioTestCase"})
PLAIN = "plain"
UNITTEST = "unittest"


class ClassValue(ast.expr):
    """A class attribute's value inside a guard: `None`, an `OBJECT` or a `NOT_NONE` name.

    `_static_truth` reads `None` and an `OBJECT` as truth values and in
    `is`/`==` comparisons with `None`, a `NOT_NONE` name in `is` comparisons
    with `None` only, and each as unknown anywhere else.
    """

    _fields = ()

    def __init__(self, kind: str) -> None:
        super().__init__()
        self.kind = kind

    def __deepcopy__(self, memo):  # pragma: no cover - trivial
        return ClassValue(self.kind)


def _store_names(node: ast.AST) -> set[str]:
    """Names `node` binds in the scope it runs in: a nested def or class binds only its own name."""
    names = set()
    stack = [node]
    while stack:
        sub = stack.pop()
        if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(sub.name)
            # Decorators, defaults and bases run in this scope; the body does not.
            stack.extend(sub.decorator_list)
            if isinstance(sub, ast.ClassDef):
                stack.extend([*sub.bases, *sub.keywords])
            else:
                stack.extend([*sub.args.defaults, *(d for d in sub.args.kw_defaults if d is not None)])
            continue
        if isinstance(sub, ast.Lambda):
            stack.extend([*sub.args.defaults, *(d for d in sub.args.kw_defaults if d is not None)])
            continue
        if isinstance(sub, ast.Name) and isinstance(sub.ctx, (ast.Store, ast.Del)):
            names.add(sub.id)
        elif isinstance(sub, ast.alias):
            names.add(sub.asname or sub.name.split(".")[0])
        elif isinstance(sub, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)) and sub.name:
            names.add(sub.name)
        elif isinstance(sub, (ast.Global, ast.Nonlocal)):
            names.update(sub.names)
        stack.extend(ast.iter_child_nodes(sub))
    return names


def _literal(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        return _literal(node.operand)
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return all(_literal(element) for element in node.elts)
    return False


class ClassAttributes:
    """The class-body attribute values of one module's top-level classes."""

    def __init__(self, tree: ast.Module) -> None:
        self.tree = tree
        self.classes: dict[str, ast.ClassDef] = {}
        ambiguous: set[str] = set()
        # name -> (kind, value) for each module-level binding; kind is "def",
        # "import" (value: the (module, name) it binds), "assign" or "other".
        bindings: dict[str, list[tuple[str, ast.AST | None]]] = {}
        self.star = False
        for statement in tree.body:
            if isinstance(statement, ast.ClassDef):
                self.classes[statement.name] = statement
                bindings.setdefault(statement.name, []).append(("def", statement))
            elif isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                bindings.setdefault(statement.name, []).append(("def", statement))
            elif isinstance(statement, (ast.Import, ast.ImportFrom)):
                for alias in statement.names:
                    if alias.name == "*":
                        self.star = True
                        continue
                    name = alias.asname or alias.name.split(".")[0]
                    if isinstance(statement, ast.Import):
                        source = (alias.name if alias.asname else name, None)
                    else:
                        source = (statement.module if not statement.level else None, alias.name)
                    bindings.setdefault(name, []).append(("import", source))
            elif isinstance(statement, ast.Assign) and all(isinstance(t, ast.Name) for t in statement.targets):
                for target in statement.targets:
                    bindings.setdefault(target.id, []).append(("assign", statement.value))
            elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
                if statement.value is not None:
                    bindings.setdefault(statement.target.id, []).append(("assign", statement.value))
            else:
                for name in _store_names(statement):
                    bindings.setdefault(name, []).append(("other", None))
        self.module_bindings = bindings
        for name, entries in bindings.items():
            if name in self.classes and len(entries) > 1:
                ambiguous.add(name)
        self.ambiguous = ambiguous
        self._own: dict[str, dict[str, ast.AST | None]] = {}
        self._scanned = False

    def _scan(self) -> None:
        """Read the whole module once, the first time a guard asks: most never do."""
        if self._scanned:
            return
        self._scanned = True
        ambiguous = self.ambiguous
        # Attribute names some code assigns or deletes through an attribute
        # target anywhere in the module: an instance attribute, or the class
        # attribute rebound through its class. Either makes the class body's
        # value not the one a guard reads.
        self.poisoned: set[str] = set()
        self.reflective = False
        pending: list[ast.AST] = [self.tree]
        while pending:
            for node in ast.walk(pending.pop()):
                if isinstance(node, ast.Attribute):
                    stored = isinstance(node.ctx, (ast.Store, ast.Del))
                    if node.attr in _REFLECTIVE_ATTRIBUTES or (stored and node.attr in _LOOKUP_ATTRIBUTES):
                        self.reflective = True
                    if stored:
                        self.poisoned.add(node.attr)
                        root = node.value
                        while isinstance(root, (ast.Attribute, ast.Subscript)):
                            root = root.value
                        if isinstance(root, ast.Name) and root.id in self.classes:
                            ambiguous.add(root.id)
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    if node.func.id in _REFLECTIVE:
                        self.reflective = True
                    elif node.func.id in _RUNS_CODE and node.args and isinstance(node.args[0], ast.Constant):
                        # A literal's code is read with the module; a
                        # computed string's is not, as a helper's in
                        # another file is not.
                        try:
                            pending.append(ast.parse(node.args[0].value, mode=_RUNS_CODE[node.func.id]))
                        except (SyntaxError, TypeError, ValueError, RecursionError, MemoryError):
                            self.reflective = True

    # -- values ------------------------------------------------------------

    def _module_value(self, name: str) -> ast.AST | None:
        """What a bare name in a class body's value holds, or None for unknown."""
        entries = self.module_bindings.get(name)
        if entries is None:
            # A module's own dunders (`__doc__`, `__spec__`) shadow the
            # builtins module's, and may be None.
            builtin = getattr(builtins, name, None)
            if self.star or name.startswith("__") or not isinstance(
                    builtin, (type, types.BuiltinFunctionType)):
                return None
            return ClassValue(OBJECT)
        if len(entries) != 1:
            return None
        kind, value = entries[0]
        if kind == "def":
            return ClassValue(OBJECT)
        if kind == "import":
            return ClassValue(NOT_NONE)
        if kind == "assign" and value is not None and _literal(value):
            return self._from_literal(value)
        return None

    @staticmethod
    def _from_literal(value: ast.AST) -> ast.AST:
        if isinstance(value, ast.Constant) and value.value is None:
            return ClassValue(NONE)
        return value

    def _value(self, value: ast.AST, class_names: set[str]) -> ast.AST | None:
        if _literal(value):
            return self._from_literal(value)
        if isinstance(value, ast.Lambda):
            return ClassValue(OBJECT)
        if isinstance(value, ast.Name):
            if value.id in class_names:
                # A name the class body binds itself shadows the module's.
                return None
            return self._module_value(value.id)
        if (isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
                and value.func.id in {"staticmethod", "classmethod"}
                and value.func.id not in self.module_bindings and not self.star
                and len(value.args) == 1 and not value.keywords):
            # Read through an instance, a staticmethod gives back what it
            # wraps, and a classmethod a method bound to it: neither is None
            # when the wrapped object is not.
            inner = self._value(value.args[0], class_names)
            return inner if isinstance(inner, ClassValue) and inner.kind in (OBJECT, NOT_NONE) else None
        return None

    def _own_values(self, cls: ast.ClassDef) -> dict[str, ast.AST | None]:
        """attr -> value (None: unknown) for each name `cls`'s body binds."""
        cached = self._own.get(cls.name)
        if cached is not None:
            return cached
        simple: dict[str, list[ast.AST]] = {}
        other: set[str] = set()
        for statement in cls.body:
            if isinstance(statement, ast.Assign) and all(isinstance(t, ast.Name) for t in statement.targets):
                for target in statement.targets:
                    simple.setdefault(target.id, []).append(statement.value)
            elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
                if statement.value is not None:
                    simple.setdefault(statement.target.id, []).append(statement.value)
            elif isinstance(statement, ast.Pass) or (
                    isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant)):
                continue
            else:
                other |= _store_names(statement)
        names = set(simple) | other
        values: dict[str, ast.AST | None] = {}
        for name in names:
            if name in other or len(simple.get(name, ())) != 1:
                values[name] = None
            else:
                values[name] = self._value(simple[name][0], names - {name})
        self._own[cls.name] = values
        return values

    def value(self, cls: ast.ClassDef, attr: str) -> ast.AST | None:
        """The value `self.<attr>` reads for an instance of `cls`, or None for unknown."""
        if attr.startswith("_"):
            return None
        self._scan()
        if self.reflective or attr in self.poisoned:
            return None
        chain = self._chain(cls)
        if chain is None or self._root(chain[-1]) is None or any(
                link.decorator_list or link.keywords or "__getattribute__" in self._own_values(link)
                for link in chain):
            return None
        for link in chain:
            own = self._own_values(link)
            if attr in own:
                return own[attr]
        return None

    def env(self, cls: ast.ClassDef | None):
        """A lookup `attr -> value or None` for instances of `cls`, or None when `cls` is not resolvable."""
        if cls is None or self.classes.get(cls.name) is not cls:
            return None
        return lambda attr: self.value(cls, attr)

    # -- 254.Q2 --------------------------------------------------------------

    def _chain(self, cls: ast.ClassDef) -> list[ast.ClassDef] | None:
        """`cls` and its same-file single-base ancestors, or None when not resolvable.

        The chain ends at the first class with no base, more than one, or one
        outside the file.
        """
        chain, seen = [], set()
        current = cls
        while True:
            if current.name in seen or current.name in self.ambiguous or self.classes.get(current.name) is not current:
                return None
            seen.add(current.name)
            chain.append(current)
            if len(current.bases) != 1:
                return chain
            base = current.bases[0]
            if not (isinstance(base, ast.Name) and base.id in self.classes):
                return chain
            current = self.classes[base.id]

    def _root(self, cls: ast.ClassDef) -> str | None:
        """`PLAIN` when the chain's last class `cls` derives from nothing or `object`,
        `UNITTEST` from unittest's `TestCase`, None from anything else."""
        if not cls.bases:
            return PLAIN
        if len(cls.bases) != 1:
            return None
        base = cls.bases[0]
        if isinstance(base, ast.Name):
            if base.id == "object" and base.id not in self.module_bindings and not self.star:
                return PLAIN
            entries = self.module_bindings.get(base.id, [])
            if entries and all(kind == "import" and value in {("unittest", case) for case in _UNITTEST_CASES}
                               for kind, value in entries):
                return UNITTEST
            return None
        if (isinstance(base, ast.Attribute) and isinstance(base.value, ast.Name)
                and base.value.id == "unittest" and base.attr in _UNITTEST_CASES):
            entries = self.module_bindings.get("unittest", [])
            if entries and all(entry == ("import", ("unittest", None)) for entry in entries):
                return UNITTEST
        return None

    def crediting_subclasses(self, cls: ast.ClassDef, method: str) -> list[ast.ClassDef]:
        """Same-file subclasses of `cls` that run its test `method` unchanged (254.Q2).

        Each one reaches `cls` through same-file single bases. It, and each
        class between it and `cls`, adds nothing but values for attributes
        the base declares and tests of its own (`_adds_only_values_and_tests`).
        No class of its chain binds `__test__`. It is collected: a subclass of
        unittest's `TestCase`, or a class pytest's default `Test*` collects,
        whose whole hierarchy is in the file and defines no `__init__` or
        `__new__`. Its own guards are not read here: the caller judges the
        test under its values.
        """
        self._scan()
        if self.reflective or self.classes.get(cls.name) is not cls or cls.name in self.ambiguous:
            return []
        own_chain = self._chain(cls) or [cls]
        # Every attribute name `cls` and its bases read or call, on any object.
        reached = {node.attr for link in own_chain for node in ast.walk(link) if isinstance(node, ast.Attribute)}
        # The attributes they declare with a plain value in a class body.
        declared = {
            target.id
            for link in own_chain for statement in link.body
            if isinstance(statement, (ast.Assign, ast.AnnAssign))
            for target in (statement.targets if isinstance(statement, ast.Assign) else [statement.target])
            if isinstance(target, ast.Name)
        }
        out = []
        for candidate in self.classes.values():
            if candidate is cls:
                continue
            chain = self._chain(candidate)
            if chain is None or cls not in chain:
                continue
            between = chain[:chain.index(cls)]
            if not all(self._adds_only_values_and_tests(link, method, reached, declared) for link in between):
                continue
            if any("__test__" in self._own_values(link) for link in chain):
                continue
            if not (self._root(chain[-1]) == UNITTEST or self._pytest_class(candidate, chain)):
                continue
            out.append(candidate)
        return sorted(out, key=lambda node: node.lineno)

    def _pytest_class(self, candidate: ast.ClassDef, chain: list[ast.ClassDef]) -> bool:
        """pytest's default `Test*` collects `candidate`: no class it derives from can stop it."""
        return candidate.name.startswith("Test") and not any(
            {"__init__", "__new__"} & set(self._own_values(link)) for link in chain)

    @staticmethod
    def _adds_only_values_and_tests(cls: ast.ClassDef, method: str, reached: set[str], declared: set[str]) -> bool:
        """`cls` cannot change how a test it inherits runs.

        Its body holds new values for public attributes the base declares in
        its class body, which the caller's guards are judged under, and
        undecorated tests of its own that the base never reaches through an
        attribute. Anything else may: a setup or teardown callback, a
        framework entry point (`run`, `debug`, a dunder) whether defined or
        assigned, a helper the inherited test calls, or a `pytestmark` or
        `__test__` binding. (A decorator or a class keyword leaves its values
        unknown, so the caller finds no guard they settle.)
        """
        for statement in cls.body:
            if isinstance(statement, ast.Pass) or (
                    isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant)):
                continue
            if isinstance(statement, (ast.Assign, ast.AnnAssign)):
                targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
                if all(isinstance(t, ast.Name) and t.id in declared and not t.id.startswith("_")
                       and t.id not in {method, "pytestmark"} for t in targets):
                    continue
                return False
            if (isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and statement.name.startswith("test") and statement.name != method
                    and not statement.decorator_list and statement.name not in reached):
                continue
            return False
        return True


def receivers(function: ast.FunctionDef | ast.AsyncFunctionDef) -> frozenset[str]:
    """The name a method reads its instance or class through, when it never rebinds it."""
    if any(isinstance(d, ast.Name) and d.id == "staticmethod" for d in function.decorator_list):
        return frozenset()
    positional = [*function.args.posonlyargs, *function.args.args]
    if not positional:
        return frozenset()
    name = positional[0].arg
    if any(name in _store_names(statement) for statement in function.body):
        return frozenset()
    return frozenset({name})


def substitute(expr: ast.AST, env, names: frozenset[str]) -> ast.AST:
    """`expr` with each `<receiver>.<attr>` the class bodies resolve replaced by its value."""
    if env is None or not names or not any(
            isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in names
            for node in ast.walk(expr)):
        return expr

    class _Substitute(ast.NodeTransformer):
        def visit_Lambda(self, node: ast.Lambda) -> ast.AST:
            arguments = node.args
            params = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs,
                      *(a for a in (arguments.vararg, arguments.kwarg) if a is not None)]
            if any(param.arg in names for param in params):
                # The receiver's name means the lambda's own parameter here;
                # only the defaults are read in the enclosing scope.
                arguments.defaults = [self.visit(d) for d in arguments.defaults]
                arguments.kw_defaults = [d if d is None else self.visit(d) for d in arguments.kw_defaults]
                return node
            return self.generic_visit(node)

        def visit_Attribute(self, node: ast.Attribute) -> ast.AST:
            if (isinstance(node.value, ast.Name) and node.value.id in names
                    and isinstance(node.ctx, ast.Load)):
                value = env(node.attr)
                if value is not None:
                    return ast.copy_location(copy.deepcopy(value), node)
                return node
            return self.generic_visit(node)

    return _Substitute().visit(copy.deepcopy(expr))

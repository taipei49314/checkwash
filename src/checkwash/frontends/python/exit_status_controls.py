"""Conftest code that forces pytest's exit status (#422).

pytest exits with `session.exitstatus` as `wrap_session` returns it, unless
the process ends first. So a conftest can turn a failing run green without
touching a test: write 0 to `session.exitstatus`, reset `session.testsfailed`
(the other input to it), raise `pytest.exit(returncode=0)`, call `os._exit(0)`,
or raise a `SystemExit` that escapes pytest. Each is a runtime control in
#84's family (ruling 422.Q1). It mints
`conftest.runtime.exit.<place>.<effect>.<path-hash>` on the `<suite>` unit,
where `<place>` is the function the effect sits in (`module` at module scope)
and the hash is taken over the path condition, as `runtime_controls` takes
it. The marker carries no guard, so neither COMPAT_GATE nor repair evidence
can hold it.

What is read (ruling 422.Q2, Q4):
- a write named `exitstatus` or `testsfailed`, on any receiver, in any code
  of the conftest: an assignment (augmented ones included), a `del`,
  `setattr`/`__setattr__`/`delattr` with a literal name, a literal key of
  `x.__dict__` or `vars(x)`, or a keyword or literal dict key of their
  `update()`. A `testsfailed` write is an effect when it is zero, a decrement
  or unreadable; `+=` a positive literal and a non-zero literal are not;
- `pytest.exit(..., returncode=v)` and a call of `pytest.exit.Exception`,
  `Exit` or a same-file subclass, anywhere. With no returncode, or None, the
  run is interrupted or keeps its status, so it is no effect;
- `os._exit(v)` under any alias, called in a place or passed there as a
  callable (`atexit.register(os._exit, 0)`, `functools.partial(...)`);
- `sys.exit(v)`, `exit()`, `quit()`, a `SystemExit` or same-file subclass
  called or raised, in a place, except under `pytest_cmdline_main`, which the
  row-7 follow-up covers. SystemExit escapes pytest from all the others. The
  three functions also count when passed there as a positional argument
  (`atexit.register(sys.exit, 0)`). A bare `exit` or `quit` is not the
  builtin where a binding hides it: a parameter or assignment in its scope,
  an enclosing one or module scope (for a passed name), or, for any use, only
  unconditional module-level imports that precede it (`from pytest import
  exit`).

Places are module scope; every `pytest_*` function or method (its effective
hook is a `hookimpl(specname=...)`); every fixture; every callable passed to,
or decorated by, `atexit.register` or an `addfinalizer`; the lambdas inside a
place; and every same-file function a place calls by name, transitively (row
125), including a same-file class's `__new__` and `__init__` when the class is
called and its methods when called through the class name.

A value is read as a POSIX exit status, modulo 256. 0 (False, 0.0,
`ExitCode.OK`) and 5 (`ExitCode.NO_TESTS_COLLECTED`, the recipe's input below)
are effects, and so is anything this reading cannot show to be neither, a
named constant included (ruling 209.Q2). None or an absent value is 0 for a
write and for SystemExit. For SystemExit a string or float prints and exits 1.

The status the run already had is no effect: inside a `pytest_sessionfinish`
or `pytest_terminal_summary`, its own unrebound `exitstatus` parameter,
`session.exitstatus` on its own unrebound `session` parameter, `int()` or
`ExitCode()` of either, and a zero under a positive conjunct `exitstatus == 0`
(`== ExitCode.OK`, `not exitstatus`) over either. None of this holds when
the conftest calls or names that hook anywhere else, since it could pass a
forged argument. Any other `<x>.exitstatus` is unreadable.

The recipe that turns "no tests collected" into success is no control
(ruling 422.Q3): a zero written to `session.exitstatus` in such a
`pytest_sessionfinish`, under a positive conjunct, not negated and not in an
`or`, that compares its status with 5 by `==` or `is`, by `in` a literal
tuple or set of 5 alone, as a `match` case, or in `0 if exitstatus == 5 else
exitstatus`. pytest returns 5 only when nothing failed (`_pytest/main.py`).

Code that never runs is not read: an `if __name__ == "__main__":` block when
the module never binds `__name__` (by name, import, string constant, keyword
or attribute write), a branch whose test is a literal constant, and an
undecorated nested function never named in the function that defines it (a
decorator receives the function, so a decorated one is live). Neither is a
fork child: `os._exit` under a positive `pid == 0` or `not pid` over a name
bound once, in the same function, to `os.fork()` or `os.forkpty()[0]`.

Not read here (the 422.Q4 and Q5 residuals): `pytest_cmdline_main`,
`pytest_runtestloop` or `pytest_collection` short-circuits; callbacks
registered in other ways (`config.add_cleanup`, `signal.signal`,
`threading.Timer`, `weakref.finalize`); other plugin modules; exits in test
modules or production code; `os.exec*` into a no-op; computed names
(`getattr`, `__import__`, a computed `update(**...)`); rebinding pytest's own
functions; `ctypes`; interpreter start-up files; and a recipe combined with a
run that collects nothing.
"""
from __future__ import annotations

import ast
import hashlib

from checkwash.ir.astutil import dotted_name, stable_dump

from .hook_guards import _rebinds
from .setup_skip_controls import _pytest_name

_STATUS = "exitstatus"
_FAILED = "testsfailed"
_WRITTEN = frozenset({_STATUS, _FAILED})
# The reader runs only on a conftest that names one of these (422.Q2).
_TOKENS = ("exit", "quit", "testsfailed")
_OS_EXIT = frozenset({"os._exit", "posix._exit", "nt._exit"})
_SYS_EXIT = frozenset({"sys.exit", "exit", "quit", "builtins.exit", "builtins.quit"})
_PYTEST_EXIT = frozenset({"pytest.exit", "_pytest.outcomes.exit"})
_EXIT_CLASSES = frozenset({"pytest.exit.Exception", "_pytest.outcomes.exit.Exception", "_pytest.outcomes.Exit"})
_SYSTEM_EXIT = frozenset({"SystemExit", "builtins.SystemExit"})
# Builtin names that stay builtins wherever an import binds them in another scope.
_BUILTIN_EXITS = frozenset({"exit", "quit", "SystemExit"})
_EXIT_CODE = frozenset({"pytest.ExitCode", "_pytest.main.ExitCode", "_pytest.config.ExitCode"})
_EXIT_CODES = {"OK": 0, "TESTS_FAILED": 1, "INTERRUPTED": 2, "INTERNAL_ERROR": 3, "USAGE_ERROR": 4,
               "NO_TESTS_COLLECTED": 5}
_FIXTURES = frozenset({"pytest.fixture", "pytest.yield_fixture", "_pytest.fixtures.fixture",
                       "_pytest.fixtures.yield_fixture"})
_FORK = frozenset({"os.fork", "posix.fork"})
_FORKPTY = frozenset({"os.forkpty", "posix.forkpty"})
_STATUS_HOOKS = frozenset({"pytest_sessionfinish", "pytest_terminal_summary"})
_RECIPE_HOOK = "pytest_sessionfinish"
_COMMAND_HOOK = "pytest_cmdline_main"
# Nodes that are only part of an operator's spelling, shared between expressions.
_SPELLING = (ast.expr_context, ast.boolop, ast.operator, ast.unaryop, ast.cmpop)

# How a value reads as the status a run ends with.
_ZERO, _FIVE, _OTHER, _UNREADABLE = "zero", "five", "other", "unreadable"
_UNKNOWN = object()


def _mentions_exit(tree: ast.Module) -> bool:
    """Does any name, attribute, keyword or string in the module contain an exit token?"""
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            text = node.id
        elif isinstance(node, ast.Attribute):
            text = node.attr
        elif isinstance(node, ast.alias):
            text = f"{node.name} {node.asname or ''}"
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            text = node.name
        elif isinstance(node, ast.ImportFrom):
            text = node.module or ""
        elif isinstance(node, ast.keyword):
            text = node.arg or ""
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            text = node.value
        else:
            continue
        lowered = text.lower()
        if any(token in lowered for token in _TOKENS):
            return True
    return False


def _rebinds_dunder_name(tree: ast.Module) -> bool:
    """Can the module rebind `__name__` other than as a plain name: a string key, a keyword, an attribute?"""
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value == "__name__":
            return True  # `globals()["__name__"] = ...`, `setattr(module, "__name__", ...)`
        if isinstance(node, ast.keyword) and node.arg == "__name__":
            return True  # `globals().update(__name__=...)`
        if isinstance(node, ast.Attribute) and node.attr == "__name__" and not isinstance(node.ctx, ast.Load):
            return True  # `sys.modules[__name__].__name__ = ...`
    return False


def _exit_truth(node) -> bool | None:
    """The truth of a literal test (`False`, `0`, `not True`), or None."""
    flipped = False
    while isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        node, flipped = node.operand, not flipped
    if isinstance(node, ast.Constant):
        return bool(node.value) != flipped
    return None


def _exit_conjuncts(conds):
    """The positive conjuncts of a path condition: no `else` branch, no `or`."""
    for cond in conds:
        if cond[0] == "case":
            yield cond
        elif cond[0] == "test":
            pending = [cond[1]]
            while pending:
                test = pending.pop()
                if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.And):
                    pending.extend(test.values)
                else:
                    yield ("test", test)


def _exit_reading(value, callee: str) -> str:
    """How a literal reads as the status `callee` ends the run with.

    `callee` is "write" (`session.exitstatus`), "pytest" (a returncode), "os"
    (`os._exit`) or "sys" (SystemExit).
    """
    if value is _UNKNOWN:
        return _UNREADABLE
    if value is None:
        # pytest.exit without a returncode interrupts; os._exit() raises TypeError.
        return _OTHER if callee in ("pytest", "os") else _ZERO
    if isinstance(value, int):
        rest = value % 256
        return _ZERO if rest == 0 else _FIVE if rest == 5 else _OTHER
    if isinstance(value, (float, complex)) and callee in ("write", "pytest"):
        # `ExitCode(0.0)` is `ExitCode.OK`.
        return _ZERO if value == 0 else _FIVE if value == 5 else _OTHER
    return _OTHER


def _failed_reading(value) -> str:
    """How a literal written to `testsfailed` reads: a falsy count hides every failure."""
    if value is _UNKNOWN:
        return _UNREADABLE
    return _OTHER if bool(value) else _ZERO


def _positive_increment(node) -> bool:
    return isinstance(node, ast.Constant) and type(node.value) in (int, bool) and node.value > 0


def _exit_render(cond) -> str:
    return ":".join([cond[0], *("None" if part is None else stable_dump(part) for part in cond[1:])])


class _ExitNames:
    """What each name in the conftest can stand for, read over the whole file."""

    def __init__(self, tree: ast.Module):
        self.imports: dict[str, set[str]] = {}
        self.bound: set[str] = set()
        self.used: set[str] = set()
        self.star = False
        # How many import bindings each name has, and the end lines of those that
        # are unconditional statements at module scope.
        self.import_count: dict[str, int] = {}
        self.top_imports: dict[str, list[int]] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.asname or alias.name.split(".")[0]
                    self.imports.setdefault(name, set()).add(alias.name if alias.asname else name)
                    self.import_count[name] = self.import_count.get(name, 0) + 1
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name == "*":
                        self.star = True
                        continue
                    origin = f"{node.module}.{alias.name}" if node.module and not node.level else ""
                    name = alias.asname or alias.name
                    self.imports.setdefault(name, set()).add(origin)
                    self.import_count[name] = self.import_count.get(name, 0) + 1
            elif isinstance(node, ast.Name):
                self.used.add(node.id)
                if not isinstance(node.ctx, ast.Load):
                    self.bound.add(node.id)
            elif isinstance(node, ast.Attribute):
                self.used.add(node.attr)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self.bound.add(node.name)
            elif isinstance(node, ast.arg):
                self.bound.add(node.arg)
            elif isinstance(node, ast.ExceptHandler) and node.name:
                self.bound.add(node.name)
            elif isinstance(node, (ast.Global, ast.Nonlocal)):
                self.bound.update(node.names)
            elif isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name:
                self.bound.add(node.name)
            elif isinstance(node, ast.MatchMapping) and node.rest:
                self.bound.add(node.rest)
        for statement in tree.body:
            if isinstance(statement, (ast.Import, ast.ImportFrom)):
                for alias in statement.names:
                    if alias.name == "*":
                        continue
                    name = alias.asname or (alias.name.split(".")[0] if isinstance(statement, ast.Import) else alias.name)
                    self.top_imports.setdefault(name, []).append(statement.end_lineno or statement.lineno)

    def shadows_builtin(self, node) -> bool:
        """Is this `exit` or `quit` certainly not the builtin?

        It is not when every binding of the name is an unconditional import at
        module scope, and one of them ends before this use starts: a function
        defined after that import can only run after it, and a use above it
        still reads as the builtin.
        """
        if not isinstance(node, ast.Name) or node.id not in ("exit", "quit"):
            return False
        lines = self.top_imports.get(node.id, [])
        return (bool(lines) and len(lines) == self.import_count.get(node.id, 0) and node.id not in self.bound
                and not self.star and min(lines) < node.lineno)

    def origins(self, node) -> set[str]:
        """Every dotted name this expression can stand for: through its imports, and as written."""
        name = dotted_name(node)
        if not name:
            return set()
        root, dot, rest = name.partition(".")
        found = {_pytest_name(origin + dot + rest) for origin in self.imports.get(root, ()) if origin}
        if not found or root in self.bound or self.star or root in _BUILTIN_EXITS:
            found.add(_pytest_name(name))
        return found

    def trusted(self, node, allowed: frozenset[str]) -> bool:
        """Is this certainly one of `allowed`: a name bound only by imports of it?"""
        name = dotted_name(node)
        if not name:
            return False
        root, dot, rest = name.partition(".")
        origins = self.imports.get(root)
        if not origins or "" in origins or root in self.bound or self.star:
            return False
        return all(_pytest_name(origin + dot + rest) in allowed for origin in origins)

    def builtin(self, name: str) -> bool:
        """Is this name certainly the builtin?"""
        return name not in self.imports and name not in self.bound and not self.star

    def _literal_status(self, node):
        if isinstance(node, ast.Constant):
            return node.value
        if (isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd))
                and isinstance(node.operand, ast.Constant)
                and isinstance(node.operand.value, (int, float, complex))):
            value = node.operand.value
            return -value if isinstance(node.op, ast.USub) else +value
        if isinstance(node, ast.Attribute) and node.attr in _EXIT_CODES and self.trusted(node.value, _EXIT_CODE):
            return _EXIT_CODES[node.attr]
        return _UNKNOWN

    def constant(self, node):
        """The literal value of an exit status, or `_UNKNOWN`."""
        value = self._literal_status(node)
        if value is not _UNKNOWN or not isinstance(node, ast.Call):
            return value
        if len(node.args) != 1 or node.keywords or isinstance(node.args[0], ast.Starred):
            return _UNKNOWN
        inner = self._literal_status(node.args[0])
        if type(inner) not in (bool, int, float):
            return _UNKNOWN
        if isinstance(node.func, ast.Name) and node.func.id == "int" and self.builtin("int"):
            try:
                return int(inner)
            except (OverflowError, ValueError):
                return _UNKNOWN
        if self.trusted(node.func, _EXIT_CODE) and inner in _EXIT_CODES.values():
            return int(inner)
        return _UNKNOWN


class _ExitHook:
    """A `pytest_sessionfinish` or `pytest_terminal_summary` whose own arguments are the status."""

    def __init__(self, function, names: _ExitNames, effective: str):
        arguments = function.args
        params = {a.arg for a in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs)}
        self.effective = effective
        self.names = names
        self.status = _STATUS if _STATUS in params and not _rebinds(function, _STATUS) else None
        self.session = "session" if "session" in params and not _rebinds(function, "session") else None

    def argument(self, node) -> bool:
        """Is this the hook's `exitstatus`, or `session.exitstatus` on its `session`?"""
        if isinstance(node, ast.Name):
            return self.status is not None and node.id == self.status
        return (isinstance(node, ast.Attribute) and node.attr == _STATUS and self.session is not None
                and isinstance(node.value, ast.Name) and node.value.id == self.session)

    def passes(self, node) -> bool:
        """Is this value the status the run already had?"""
        if self.argument(node):
            return True
        if not (isinstance(node, ast.Call) and len(node.args) == 1 and not node.keywords):
            return False
        func = node.func
        converts = (isinstance(func, ast.Name) and func.id == "int" and self.names.builtin("int")) or (
            self.names.trusted(func, _EXIT_CODE))
        return converts and self.argument(node.args[0])

    def _code(self, node, code: int) -> bool:
        if isinstance(node, ast.Constant):
            return type(node.value) is int and node.value == code
        member = next(name for name, value in _EXIT_CODES.items() if value == code)
        return isinstance(node, ast.Attribute) and node.attr == member and self.names.trusted(node.value, _EXIT_CODE)

    def compares(self, conjunct, code: int, membership: bool) -> bool:
        """Does this positive conjunct prove that the status equals `code`?"""
        if conjunct[0] == "case":
            _kind, subject, pattern = conjunct
            return self.argument(subject) and isinstance(pattern, ast.MatchValue) and self._code(pattern.value, code)
        test = conjunct[1]
        if code == 0 and isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
            return self.argument(test.operand)
        if not isinstance(test, ast.Compare) or len(test.ops) != 1:
            return False
        operator, left, right = test.ops[0], test.left, test.comparators[0]
        if isinstance(operator, ast.Eq) or (membership and isinstance(operator, ast.Is)):
            return (self.argument(left) and self._code(right, code)) or (
                self._code(left, code) and self.argument(right))
        if membership and isinstance(operator, ast.In):
            return (self.argument(left) and isinstance(right, (ast.Tuple, ast.Set)) and bool(right.elts)
                    and all(self._code(element, code) for element in right.elts))
        return False


class _ExitReading:
    """One conftest's live code, its places, and the effects in them."""

    def __init__(self, tree: ast.Module):
        self.tree = tree
        self.names = _ExitNames(tree)
        self.binds_main = ("__name__" in self.names.bound or "__name__" in self.names.imports
                           or _rebinds_dunder_name(tree))
        # id(node) -> (node, innermost scope, path condition), for code that can run.
        self.info: dict[int, tuple[ast.AST, ast.AST, tuple]] = {}
        self.parents: dict[int, ast.AST] = {}
        self.labels: dict[int, str] = {id(tree): "module"}
        self.members: dict[int, list[ast.AST]] = {}
        self.lambdas: dict[int, list[ast.AST]] = {}
        self.defs: dict[str, list[ast.AST]] = {}
        self.classes: dict[str, list[ast.ClassDef]] = {}
        self.hooks: dict[int, _ExitHook | None] = {}
        self._visit()
        # Names module scope binds other than by an import, `global` statements included.
        module = self.members.get(id(tree), ())
        self.module_bound = {n.id for n in module if isinstance(n, ast.Name) and not isinstance(n.ctx, ast.Load)}
        self.module_bound.update(n.name for n in module
                                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))
        self.module_bound.update(name for n in ast.walk(tree) if isinstance(n, ast.Global) for name in n.names)
        self.exit_classes = self._subclasses(_EXIT_CLASSES)
        self.system_classes = self._subclasses(_SYSTEM_EXIT)
        self.registered = self._registered()

    # -- the walk -------------------------------------------------------

    def _visit(self) -> None:
        stack = [(self.tree, self.tree, ())]
        while stack:
            node, scope, conds = stack.pop()
            self.info[id(node)] = (node, scope, conds)
            if node is not scope:
                self.members.setdefault(id(scope), []).append(node)
            children = list(self._children(node, scope, conds))
            for child, child_scope, child_conds in reversed(children):
                self.parents[id(child)] = node
                stack.append((child, child_scope, child_conds))

    def _children(self, node, scope, conds):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            arguments = node.args
            for child in (*node.decorator_list, *arguments.defaults,
                          *(d for d in arguments.kw_defaults if d is not None)):
                yield child, scope, conds
            if self._dead(node, scope):
                return
            self._enter(node, scope, node.name)
            self.defs.setdefault(node.name, []).append(node)
            for child in node.body:
                yield child, node, ()
            return
        if isinstance(node, ast.Lambda):
            arguments = node.args
            for child in (*arguments.defaults, *(d for d in arguments.kw_defaults if d is not None)):
                yield child, scope, conds
            self._enter(node, scope, "lambda")
            self.lambdas.setdefault(id(scope), []).append(node)
            yield node.body, node, ()
            return
        if isinstance(node, ast.ClassDef):
            self.classes.setdefault(node.name, []).append(node)
            # A class body runs where the class statement stands.
            for child in (*node.decorator_list, *node.bases, *(k.value for k in node.keywords), *node.body):
                yield child, scope, conds
            return
        if isinstance(node, (ast.If, ast.IfExp)):
            yield node.test, scope, conds
            truth = False if self._main_block(node.test) else _exit_truth(node.test)
            body = node.body if isinstance(node, ast.If) else [node.body]
            orelse = node.orelse if isinstance(node, ast.If) else [node.orelse]
            if truth is not False:
                inner = conds if truth else conds + (("test", node.test),)
                for child in body:
                    yield child, scope, inner
            if truth is not True:
                inner = conds if truth is False else conds + (("not", node.test),)
                for child in orelse:
                    yield child, scope, inner
            return
        if isinstance(node, ast.While):
            yield node.test, scope, conds
            truth = _exit_truth(node.test)
            if truth is not False:
                inner = conds if truth else conds + (("test", node.test),)
                for child in node.body:
                    yield child, scope, inner
            for child in node.orelse:
                yield child, scope, conds
            return
        if isinstance(node, ast.Match):
            yield node.subject, scope, conds
            for case in node.cases:
                inner = conds + (("case", node.subject, case.pattern),)
                if case.guard is not None:
                    yield case.guard, scope, inner
                    inner = inner + (("test", case.guard),)
                for child in case.body:
                    yield child, scope, inner
            return
        if isinstance(node, ast.Try) or type(node).__name__ == "TryStar":
            for child in (*node.body, *node.orelse, *node.finalbody):
                yield child, scope, conds
            for handler in node.handlers:
                if handler.type is not None:
                    yield handler.type, scope, conds
                inner = conds + (("except", handler.type),)
                for child in handler.body:
                    yield child, scope, inner
            return
        for child in ast.iter_child_nodes(node):
            if not isinstance(child, _SPELLING):
                yield child, scope, conds

    def _dead(self, function, scope) -> bool:
        """Is this an undecorated function nested in another that never names it?"""
        if not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            return False
        if isinstance(self.parents.get(id(function)), ast.ClassDef):
            return False
        if function.decorator_list:
            return False  # a decorator receives it: `@atexit.register`, `@request.addfinalizer`
        return not any(isinstance(n, ast.Name) and n.id == function.name for n in ast.walk(scope))

    def _enter(self, function, scope, name: str) -> None:
        prefix = "" if scope is self.tree else self.labels[id(scope)] + "."
        parent = self.parents.get(id(function))
        if isinstance(parent, ast.ClassDef):
            prefix += parent.name + "."
        self.labels[id(function)] = prefix + name

    def _main_block(self, test) -> bool:
        """Is this `__name__ == "__main__"` in a module that never binds `__name__`?"""
        if self.binds_main or not isinstance(test, ast.Compare) or len(test.ops) != 1:
            return False
        if not isinstance(test.ops[0], ast.Eq):
            return False
        left, right = test.left, test.comparators[0]
        name, text = (left, right) if isinstance(left, ast.Name) else (right, left)
        return (isinstance(name, ast.Name) and name.id == "__name__"
                and isinstance(text, ast.Constant) and text.value == "__main__")

    def _subclasses(self, known: frozenset[str]) -> set[str]:
        """These classes, and the names of the same-file classes that derive from them."""
        found = set(known)
        classes = [n for n in ast.walk(self.tree) if isinstance(n, ast.ClassDef)]
        changed = True
        while changed:
            changed = False
            for cls in classes:
                if cls.name not in found and any(self.names.origins(base) & found for base in cls.bases):
                    found.add(cls.name)
                    changed = True
        return found

    # -- places -----------------------------------------------------------

    def _effective(self, function) -> str:
        """The hook a `pytest_*` function implements: its `hookimpl(specname=...)`, else its name."""
        for decorator in function.decorator_list:
            if isinstance(decorator, ast.Call):
                for keyword in decorator.keywords:
                    if (keyword.arg == "specname" and isinstance(keyword.value, ast.Constant)
                            and isinstance(keyword.value.value, str)):
                        return keyword.value.value
        return function.name

    def _is_fixture(self, function) -> bool:
        for decorator in function.decorator_list:
            target = decorator.func if isinstance(decorator, ast.Call) else decorator
            name = dotted_name(target)
            if name and (name.rsplit(".", 1)[-1] in ("fixture", "yield_fixture")
                         or self.names.origins(target) & _FIXTURES):
                return True
        return False

    def _methods(self, class_name: str, names) -> list[ast.AST]:
        """The live methods with these names of the same-file classes called `class_name`."""
        return [member for cls in self.classes.get(class_name, ()) for member in cls.body
                if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)) and member.name in names
                and id(member) in self.labels]

    def _same_file_callees(self, node) -> list[ast.AST]:
        """The same-file functions a call by this name can run.

        A same-file class called by name runs its `__new__` and `__init__`;
        `Helper.bye()` runs `Helper`'s method `bye`.
        """
        if isinstance(node, ast.Name):
            return [*self.defs.get(node.id, []), *self._methods(node.id, ("__new__", "__init__"))]
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id in ("self", "cls"):
                return self.defs.get(node.attr, [])
            return self._methods(node.value.id, (node.attr,))
        return []

    def _callables(self, node) -> list[ast.AST]:
        """The same-file code a callable argument runs: a lambda, a function, a `partial` of one."""
        while isinstance(node, ast.Call) and node.args and "functools.partial" in self.names.origins(node.func):
            node = node.args[0]
        if isinstance(node, ast.Lambda):
            return [node] if id(node) in self.labels else []
        return self._same_file_callees(node)

    def _registers(self, func) -> bool:
        """Is this `atexit.register` or an `addfinalizer`?"""
        return "atexit.register" in self.names.origins(func) or (
            isinstance(func, ast.Attribute) and func.attr == "addfinalizer")

    def _registered(self) -> list[ast.AST]:
        """Callables passed to, or decorated by, `atexit.register` or an `addfinalizer`."""
        found: list[ast.AST] = []
        for node, _scope, _conds in self.info.values():
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and id(node) in self.labels:
                if any(self._registers(d) for d in node.decorator_list):
                    found.append(node)
            elif isinstance(node, ast.Call) and node.args and self._registers(node.func):
                found.extend(self._callables(node.args[0]))
        return found

    def _roots(self, without_command: bool) -> list[ast.AST]:
        roots: list[ast.AST] = [self.tree, *self.registered]
        for functions in self.defs.values():
            for function in functions:
                if function.name.startswith("pytest_"):
                    if not (without_command and self._effective(function) == _COMMAND_HOOK):
                        roots.append(function)
                elif self._is_fixture(function):
                    roots.append(function)
        return roots

    def _reach(self, roots) -> set[int]:
        """The scopes these run: the lambdas in them and the functions they call, transitively."""
        reached: set[int] = set()
        pending = list(roots)
        while pending:
            scope = pending.pop()
            if id(scope) in reached:
                continue
            reached.add(id(scope))
            pending.extend(self.lambdas.get(id(scope), ()))
            for node in self.members.get(id(scope), ()):
                if isinstance(node, ast.Call):
                    pending.extend(self._same_file_callees(node.func))
        return reached

    # -- values -----------------------------------------------------------

    def _hook(self, scope) -> _ExitHook | None:
        if id(scope) not in self.hooks:
            hook = None
            if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)) and scope.name.startswith("pytest_"):
                effective = self._effective(scope)
                # A hook the conftest calls or names elsewhere can be handed a forged status.
                if effective in _STATUS_HOOKS and scope.name not in self.names.used:
                    hook = _ExitHook(scope, self.names, effective)
            self.hooks[id(scope)] = hook
        return self.hooks[id(scope)]

    def _leaves(self, value, conds):
        """The values a conditional expression can take, each with the condition it takes it under."""
        found, pending = [], [(value, conds)]
        while pending:
            node, path = pending.pop()
            if isinstance(node, ast.IfExp):
                truth = _exit_truth(node.test)
                if truth is not False:
                    pending.append((node.body, path if truth else path + (("test", node.test),)))
                if truth is not True:
                    pending.append((node.orelse, path if truth is False else path + (("not", node.test),)))
            else:
                found.append((node, path))
        return found

    def _counts(self, value, callee: str, scope, conds, receiver=None) -> bool:
        """Can this value end the run with a status that hides a failure?

        `value` is an expression, None for an absent one, or `_UNKNOWN`.
        `receiver` is what a plain `<receiver>.exitstatus = value` writes to.
        """
        if value is _UNKNOWN:
            return True
        hook = self._hook(scope)
        recipe = (hook is not None and hook.effective == _RECIPE_HOOK and hook.session is not None
                  and isinstance(receiver, ast.Name) and receiver.id == hook.session)
        leaves = [(None, conds)] if value is None else self._leaves(value, conds)
        for leaf, path in leaves:
            if leaf is not None and hook is not None and hook.passes(leaf):
                continue
            reading = _exit_reading(None if leaf is None else self.names.constant(leaf), callee)
            if reading == _OTHER:
                continue
            if reading == _ZERO and hook is not None:
                conjuncts = list(_exit_conjuncts(path))
                if any(hook.compares(c, 0, membership=False) for c in conjuncts):
                    continue
                if recipe and any(hook.compares(c, 5, membership=True) for c in conjuncts):
                    continue
            return True
        return False

    def _forked(self, name: str, scope) -> bool:
        """Is `name` bound once in this scope, to `os.fork()` or `os.forkpty()[0]`, and nowhere else?"""
        stores = []
        for node in ast.walk(scope):
            if node is scope:
                continue
            if isinstance(node, ast.Name) and node.id == name and not isinstance(node.ctx, ast.Load):
                stores.append(node)
            elif isinstance(node, ast.arg) and node.arg == name:
                return False
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == name:
                return False
            elif isinstance(node, ast.alias) and (node.asname or node.name.split(".")[0]) == name:
                return False
            elif isinstance(node, (ast.Global, ast.Nonlocal)) and name in node.names:
                return False
            elif isinstance(node, ast.ExceptHandler) and node.name == name:
                return False
            elif isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name == name:
                return False
            elif isinstance(node, ast.MatchMapping) and node.rest == name:
                return False
        if len(stores) != 1:
            return False
        statement = self.parents.get(id(stores[0]))
        if not (isinstance(statement, ast.Assign) and len(statement.targets) == 1
                and statement.targets[0] is stores[0]):
            return False
        value = statement.value
        if isinstance(value, ast.Call):
            return not value.args and not value.keywords and self.names.trusted(value.func, _FORK)
        return (isinstance(value, ast.Subscript) and isinstance(value.value, ast.Call)
                and not value.value.args and not value.value.keywords
                and isinstance(value.slice, ast.Constant) and type(value.slice.value) is int
                and value.slice.value == 0 and self.names.trusted(value.value.func, _FORKPTY))

    def _fork_child(self, conds, scope) -> bool:
        """Does the path hold a positive `pid == 0` or `not pid` over a forked pid?"""
        for conjunct in _exit_conjuncts(conds):
            if conjunct[0] != "test":
                continue
            test, name = conjunct[1], None
            if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not) and isinstance(test.operand, ast.Name):
                name = test.operand.id
            elif isinstance(test, ast.Compare) and len(test.ops) == 1 and isinstance(test.ops[0], ast.Eq):
                for one, other in ((test.left, test.comparators[0]), (test.comparators[0], test.left)):
                    if (isinstance(one, ast.Name) and isinstance(other, ast.Constant)
                            and type(other.value) is int and other.value == 0):
                        name = one.id
            if name is not None and self._forked(name, scope):
                return True
        return False

    # -- effects ----------------------------------------------------------

    def _statement(self, node):
        while node is not None and not isinstance(node, ast.stmt):
            node = self.parents.get(id(node))
        return node

    def _assigned(self, node):
        """The value an assignment target receives: an expression, `_UNKNOWN`, or None for no write."""
        parent = self.parents.get(id(node))
        if isinstance(parent, ast.Assign) and any(target is node for target in parent.targets):
            return parent.value
        if isinstance(parent, ast.AnnAssign) and parent.target is node:
            return parent.value
        if isinstance(parent, (ast.Tuple, ast.List)):
            outer = self.parents.get(id(parent))
            if (isinstance(outer, ast.Assign) and any(target is parent for target in outer.targets)
                    and isinstance(outer.value, (ast.Tuple, ast.List))
                    and len(outer.value.elts) == len(parent.elts)
                    and not any(isinstance(e, ast.Starred) for e in (*outer.value.elts, *parent.elts))):
                index = next(i for i, element in enumerate(parent.elts) if element is node)
                return outer.value.elts[index]
        return _UNKNOWN

    def _write(self, node, attribute: str, scope, conds, receiver):
        """The effect of writing `attribute` through this target, or None."""
        effect = "exitstatus" if attribute == _STATUS else "testsfailed"
        statement = self._statement(node)
        parent = self.parents.get(id(node))
        if isinstance(node.ctx, ast.Del):
            return effect, statement
        if isinstance(parent, ast.AugAssign) and parent.target is node:
            if attribute == _FAILED and isinstance(parent.op, ast.Add) and _positive_increment(parent.value):
                return None
            return effect, statement
        value = self._assigned(node)
        if value is None:
            return None  # an annotation alone writes nothing
        direct = isinstance(parent, ast.Assign)
        return self._written(attribute, value, scope, conds, receiver if direct else None, effect, statement)

    def _written(self, attribute, value, scope, conds, receiver, effect, evidence):
        if attribute == _FAILED:
            if value is _UNKNOWN:
                return effect, evidence
            for leaf, _path in self._leaves(value, conds):
                if _failed_reading(self.names.constant(leaf)) != _OTHER:
                    return effect, evidence
            return None
        if self._counts(value, "write", scope, conds, receiver):
            return effect, evidence
        return None

    @staticmethod
    def _namespace(holder) -> bool:
        """Is this `x.__dict__` or `vars(x)`?"""
        if isinstance(holder, ast.Attribute) and holder.attr == "__dict__":
            return True
        return isinstance(holder, ast.Call) and isinstance(holder.func, ast.Name) and holder.func.id == "vars"

    def _dict_key(self, node) -> str | None:
        """The status attribute a `x.__dict__[...]` or `vars(x)[...]` target names, or None."""
        key = node.slice
        if not (isinstance(key, ast.Constant) and isinstance(key.value, str) and key.value in _WRITTEN):
            return None
        return key.value if self._namespace(node.value) else None

    def _updates(self, node) -> list[tuple[str, ast.AST]]:
        """(attribute, value) for each status attribute a `x.__dict__.update(...)` or `vars(x).update(...)` writes.

        Keywords and the literal keys of a dict literal are read; a computed
        mapping or `**` is a computed name, a 422.Q4 residual.
        """
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "update" and self._namespace(func.value)):
            return []
        found = [(keyword.arg, keyword.value) for keyword in node.keywords if keyword.arg in _WRITTEN]
        if node.args and isinstance(node.args[0], ast.Dict):
            mapping = node.args[0]
            found.extend((key.value, value) for key, value in zip(mapping.keys, mapping.values)
                         if isinstance(key, ast.Constant) and isinstance(key.value, str) and key.value in _WRITTEN)
        return found

    def _setter(self, node):
        """(attribute, value) for a `setattr`, `__setattr__` or `delattr` of a status attribute."""
        func = node.func
        name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
        if name not in ("setattr", "__setattr__", "delattr", "__delattr__"):
            return None
        for index, argument in enumerate(node.args[:2]):
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str) and argument.value in _WRITTEN:
                following = node.args[index + 1] if index + 1 < len(node.args) else None
                if "del" in name or following is None or isinstance(following, ast.Starred):
                    return argument.value, _UNKNOWN
                return argument.value, following
        return None

    def _first(self, node, keywords):
        """The status argument of an exit call: its first positional, or a named keyword."""
        if node.args:
            return _UNKNOWN if isinstance(node.args[0], ast.Starred) else node.args[0]
        for keyword in node.keywords:
            if keyword.arg is None:
                return _UNKNOWN
            if keyword.arg in keywords:
                return keyword.value
        return None

    def _returncode(self, node):
        """The `returncode` of a `pytest.exit` or `Exit` call: keyword or second positional."""
        for keyword in node.keywords:
            if keyword.arg == "returncode":
                return keyword.value
        if any(k.arg is None for k in node.keywords) or any(isinstance(a, ast.Starred) for a in node.args[:2]):
            return _UNKNOWN
        return node.args[1] if len(node.args) >= 2 else None

    def _call_effect(self, node, scope, conds, places, system):
        origins = self.names.origins(node.func)
        setter = self._setter(node)
        if setter is not None:
            attribute, value = setter
            effect = "exitstatus" if attribute == _STATUS else "testsfailed"
            found = self._written(attribute, value, scope, conds, None, effect, node)
            if found is not None:
                return found
        for attribute, value in self._updates(node):
            effect = "exitstatus" if attribute == _STATUS else "testsfailed"
            found = self._written(attribute, value, scope, conds, None, effect, node)
            if found is not None:
                return found
        system_names = origins & _SYS_EXIT
        if self.names.shadows_builtin(node.func):
            system_names.discard(node.func.id)  # `from pytest import exit`: not the builtin
        if origins & _PYTEST_EXIT or origins & self.exit_classes:
            if self._counts(self._returncode(node), "pytest", scope, conds):
                return "pytest-exit", node
        if origins & _OS_EXIT and id(scope) in places and not self._fork_child(conds, scope):
            if self._counts(self._first(node, ("status", "n")), "os", scope, conds):
                return "os-exit", node
        if id(scope) in system and system_names:
            if self._counts(self._first(node, ("status", "code")), "sys", scope, conds):
                return "system-exit", node
        if id(scope) in system and origins & self.system_classes:
            if node.keywords or any(isinstance(a, ast.Starred) for a in node.args):
                value = _UNKNOWN
            elif len(node.args) > 1:
                value = ast.Constant("")  # several arguments are printed as a tuple, and the run exits 1
            else:
                value = node.args[0] if node.args else None
            if self._counts(value, "sys", scope, conds):
                return "system-exit", node
        return None

    def _hidden(self, name: str, scope) -> bool:
        """Does this scope, an enclosing one or module scope bind `name` other than by an import?"""
        while scope is not self.tree:
            if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                arguments = scope.args
                params = (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs,
                          arguments.vararg, arguments.kwarg)
                if any(p is not None and p.arg == name for p in params) or _rebinds(scope, name):
                    return True
            scope = self.info[id(scope)][1]
        return name in self.module_bound

    def _passed_system_exit(self, node, parent, scope, origins) -> bool:
        """Is this `sys.exit`, `exit` or `quit` passed as a positional argument?

        A bare `exit` or `quit` is a variable, not the builtin, where a
        parameter or binding hides it (`exit = config.getoption(...)`).
        """
        if not (isinstance(parent, ast.Call) and any(argument is node for argument in parent.args)):
            return False
        found = origins & _SYS_EXIT
        if isinstance(node, ast.Name) and node.id in ("exit", "quit") and (
                self.names.shadows_builtin(node) or self._hidden(node.id, scope)):
            found.discard(node.id)
        return bool(found)

    def _reference(self, node, scope, conds, places, system):
        """`os._exit` passed as a callable, or `sys.exit` passed as an argument: its next argument is the status."""
        parent = self.parents.get(id(node))
        if isinstance(parent, ast.Attribute) and parent.value is node:
            return None
        if isinstance(parent, ast.Call) and parent.func is node:
            return None
        origins = self.names.origins(node)
        if origins & _OS_EXIT and id(scope) in places:
            callee, effect = "os", "os-exit"
        elif id(scope) in system and self._passed_system_exit(node, parent, scope, origins):
            callee, effect = "sys", "system-exit"
        else:
            return None
        value = _UNKNOWN
        if isinstance(parent, ast.Call):
            index = next((i for i, a in enumerate(parent.args) if a is node), None)
            if index is not None:
                rest = parent.args[index + 1:]
                if rest:
                    value = _UNKNOWN if isinstance(rest[0], ast.Starred) else rest[0]
                elif not parent.keywords:
                    value = None
        if callee == "os" and self._fork_child(conds, scope):
            return None
        return (effect, node) if self._counts(value, callee, scope, conds) else None

    def _effect(self, node, scope, conds, places, system):
        if isinstance(node, ast.Attribute) and node.attr in _WRITTEN and not isinstance(node.ctx, ast.Load):
            return self._write(node, node.attr, scope, conds, node.value)
        if isinstance(node, ast.Subscript) and not isinstance(node.ctx, ast.Load):
            attribute = self._dict_key(node)
            return None if attribute is None else self._write(node, attribute, scope, conds, None)
        if isinstance(node, ast.Call):
            return self._call_effect(node, scope, conds, places, system)
        if isinstance(node, ast.Raise):
            # `raise SystemExit` with no call: its code is None, and the run exits 0.
            exc = node.exc
            if (exc is not None and not isinstance(exc, ast.Call) and id(scope) in system
                    and self.names.origins(exc) & self.system_classes):
                return "system-exit", node
            return None
        if isinstance(node, (ast.Name, ast.Attribute)) and isinstance(node.ctx, ast.Load):
            return self._reference(node, scope, conds, places, system)
        return None

    def effects(self):
        """(place, effect, path condition, evidence) for each effect, in source walk order."""
        places = self._reach(self._roots(without_command=False))
        system = self._reach(self._roots(without_command=True))
        for node, scope, conds in list(self.info.values()):
            found = self._effect(node, scope, conds, places, system)
            if found is not None:
                effect, evidence = found
                yield self.labels[id(scope)], effect, conds, evidence


def exit_status_controls(tree: ast.Module):
    """Yield (marker name, evidence node) for each effect that can force pytest's exit status."""
    if not _mentions_exit(tree):
        return
    for place, effect, conds, node in _ExitReading(tree).effects():
        digest = hashlib.sha256("|".join(_exit_render(cond) for cond in conds).encode()).hexdigest()[:16]
        yield f"conftest.runtime.exit.{place}.{effect}.{digest}", node

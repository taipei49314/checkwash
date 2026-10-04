"""The condition a conftest collection hook acts under (#208, #209 Q1).

A `pytest_collection_modifyitems` or `pytest_ignore_collect` hook, and an
`add_marker(<skip>)` call, was a suite-level control whatever its body did,
and carried no guard. So pytest's own `--runslow` recipe blocked at high,
while the same condition on `collect_ignore` held at warn. Such a control now
carries the condition its effects fire under. That condition is read with the
path condition #196 183.2 reads in a setup: each enclosing `if` test,
`not (...)` for an `else` branch and for the code after a branch that always
ends, and an `except` block's condition (`_handler_guard`). The weakest guard
across a control's effects is its guard, as row 71's is for `collect_ignore`,
so one effect with none leaves the control unguarded.

An effect is anything this reading cannot show to be inert, so an effect it
cannot read still counts (ruling 209.Q2). Inert is:
- binding or deleting a plain local name, `pass`, `break`, `continue`, an
  import, and a `return`, `raise` or `assert` of inert expressions;
- an expression whose every call only reads: a builtin that reads what it is
  given, an environment or mark call named by its import (`os.environ.get`,
  `importlib.util.find_spec`, `pytest.mark.skip`, ...), or a method that reads
  (`getoption`, `get_closest_marker`, `startswith`, `get`, ...).
Everything else is an effect: `add_marker`, `items[:] = ...`, `items.remove`,
an augmented assignment, a call to a function the conftest defines, a call
through `session.items` or through a name bound to the list. The test of an
`if` or `while`, a loop's iterable and a `match` subject are read the same
way, where they are evaluated. A `with` statement is always an effect,
because its context manager runs code, and its body never ends the path,
because that code can swallow an exception. In `pytest_ignore_collect`, a
`return` of anything but `None` or `False` is an effect whose value is part
of its condition.

Two readings are particular to hooks:
- A loop body is read. A hook's effects sit in `for item in items:`, and they
  fire whenever the loop runs.
- A condition is part of the guard only when it names nothing but
  module-level names, reading builtins, the hook's `config` or `session`
  (unless the hook rebinds it), and locals bound exactly once, by one plain
  assignment from those. Such a local is replaced by its value, so
  `GATE = True` / `if GATE:` reads as the `True` it is. A condition that names
  an item, the items list or any other local selects items; it does not say
  when the hook acts. So the hook that drops `test_total` by name has no guard
  at all.
"""
from __future__ import annotations

import ast
import builtins
import copy

from checkwash.ir.astutil import dotted_name

from .setup_skip_controls import _conjunction

COLLECTION_HOOKS = ("pytest_collection_modifyitems", "pytest_ignore_collect")
# The markers whose guard this reading gives them.
HOOK_MARKERS = frozenset({*(f"conftest.{hook}" for hook in COLLECTION_HOOKS), "conftest.add_marker_skip"})
_ENVIRONMENT_PARAMS = frozenset({"config", "session"})
_EXCEPTIONS = frozenset(
    name for name in dir(builtins)
    if isinstance(getattr(builtins, name), type) and issubclass(getattr(builtins, name), BaseException)
)
# Builtins that only read what they are given, and the exception classes.
_READING_BUILTINS = frozenset({
    "abs", "all", "any", "ascii", "bin", "bool", "bytes", "callable", "chr", "complex", "dict",
    "divmod", "enumerate", "filter", "float", "format", "frozenset", "getattr", "hasattr", "hash",
    "hex", "id", "int", "isinstance", "issubclass", "iter", "len", "list", "map", "max", "min",
    "next", "oct", "ord", "pow", "print", "range", "repr", "reversed", "round", "set", "slice",
    "sorted", "str", "sum", "tuple", "zip",
}) | _EXCEPTIONS
# Of those, the ones that call a function they are given. They read only when
# that function is a lambda, whose body is read with the call, or another
# reading builtin: `map(items.remove, ...)` is not a read.
_CALLING_BUILTINS = frozenset({"filter", "map", "max", "min", "sorted"})
# Calls that read the environment, the file system or a name, or that build a
# mark, by the dotted name their import gives them.
_READER_CALLS = frozenset({
    "fnmatch.fnmatch", "fnmatch.fnmatchcase",
    "importlib.metadata.version", "importlib.util.find_spec",
    "logging.getLogger",
    "os.environ.get", "os.getenv",
    "os.path.abspath", "os.path.basename", "os.path.dirname", "os.path.exists", "os.path.isdir",
    "os.path.isfile", "os.path.join", "os.path.normpath", "os.path.relpath", "os.path.splitext",
    "pathlib.Path", "pathlib.PurePath",
    "platform.machine", "platform.python_implementation", "platform.python_version",
    "platform.release", "platform.system",
    "re.compile", "re.fullmatch", "re.match", "re.search",
    "shutil.which",
    "warnings.warn",
})
_READER_PREFIXES = ("pytest.mark.",)
# Methods that read, whatever they are called on.
_READER_METHODS = frozenset({
    # pytest: options, ini values, plugins, and a node's markers and names
    "get_closest_marker", "getini", "getoption", "getvalue", "has_plugin", "hasplugin",
    "iter_markers", "iter_markers_with_node", "listchain", "listextrakeywords", "listnames",
    # str and bytes
    "casefold", "count", "decode", "encode", "endswith", "find", "format", "index", "isalnum",
    "isalpha", "isdigit", "isidentifier", "islower", "isupper", "join", "lower", "lstrip",
    "partition", "removeprefix", "removesuffix", "replace", "rfind", "rpartition", "rsplit",
    "rstrip", "split", "splitlines", "startswith", "strip", "upper",
    # paths, regular expressions and mappings
    "absolute", "as_posix", "copy", "exists", "fullmatch", "get", "group", "groups",
    "is_absolute", "is_dir", "is_file", "is_relative_to", "items", "joinpath", "keys", "match",
    "relative_to", "resolve", "search", "values", "with_name", "with_suffix",
    # logging
    "critical", "debug", "error", "exception", "info", "log", "warning",
})
# A binding that is not one plain `name = value`.
_OTHER = object()


def _stored(target) -> set[str]:
    return {n.id for n in ast.walk(target) if isinstance(n, ast.Name)}


def _plain(target) -> bool:
    """Does assigning to this target only bind local names?"""
    if isinstance(target, ast.Name):
        return True
    if isinstance(target, ast.Starred):
        return _plain(target.value)
    return isinstance(target, (ast.Tuple, ast.List)) and all(_plain(t) for t in target.elts)


def _scope_statements(statements):
    """The statements of one scope, not those of the functions and classes it defines."""
    for statement in statements:
        yield statement
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for field in ("body", "orelse", "finalbody"):
            yield from _scope_statements(getattr(statement, field, None) or [])
        for handler in getattr(statement, "handlers", None) or []:
            yield from _scope_statements(handler.body)
        for case in getattr(statement, "cases", None) or []:
            yield from _scope_statements(case.body)


def _bindings(statements) -> tuple[dict[str, list], dict[str, set[str]]]:
    """Every binding of every name in one scope, and the modules its imports name.

    A plain `name = value` records its value; an import records None; any
    other binding (a loop target, `with ... as`, `+=`, a walrus, `global`,
    `except ... as`, a `match` capture, a definition) records `_OTHER`.
    """
    found: dict[str, list] = {}
    imports: dict[str, set[str]] = {}

    def add(name, value):
        found.setdefault(name, []).append(value)

    for statement in _scope_statements(statements):
        if isinstance(statement, (ast.Import, ast.ImportFrom)):
            for alias in statement.names:
                if alias.name == "*":
                    continue
                if isinstance(statement, ast.Import):
                    name = alias.asname or alias.name.split(".")[0]
                    origin = alias.name if alias.asname else name
                else:
                    name = alias.asname or alias.name
                    origin = f"{statement.module}.{alias.name}" if statement.module and not statement.level else ""
                add(name, None)
                imports.setdefault(name, set()).add(origin)
        elif isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            add(statement.name, _OTHER)
        elif isinstance(statement, ast.Assign):
            for target in statement.targets:
                if isinstance(target, ast.Name):
                    add(target.id, statement.value)
                else:
                    for name in _stored(target):
                        add(name, _OTHER)
        elif isinstance(statement, ast.AnnAssign):
            if isinstance(statement.target, ast.Name) and statement.value is not None:
                add(statement.target.id, statement.value)
            else:
                for name in _stored(statement.target):
                    add(name, _OTHER)
        elif isinstance(statement, (ast.AugAssign, ast.For, ast.AsyncFor)):
            for name in _stored(statement.target):
                add(name, _OTHER)
        elif isinstance(statement, (ast.With, ast.AsyncWith)):
            for item in statement.items:
                if item.optional_vars is not None:
                    for name in _stored(item.optional_vars):
                        add(name, _OTHER)
        elif isinstance(statement, ast.Delete):
            for target in statement.targets:
                if isinstance(target, ast.Name):
                    add(target.id, _OTHER)
        elif isinstance(statement, (ast.Global, ast.Nonlocal)):
            for name in statement.names:
                add(name, _OTHER)
        for handler in getattr(statement, "handlers", None) or []:
            if handler.name:
                add(handler.name, _OTHER)
        for case in getattr(statement, "cases", None) or []:
            for node in ast.walk(case.pattern):
                for name in (getattr(node, "name", None), getattr(node, "rest", None)):
                    if isinstance(name, str):
                        add(name, _OTHER)
        for node in ast.walk(statement):
            if isinstance(node, ast.NamedExpr):
                for name in _stored(node.target):
                    add(name, _OTHER)
    return found, imports


def _trusted_imports(found: dict[str, list], imports: dict[str, set[str]]) -> dict[str, str]:
    """The names bound only by imports of one absolute module, and that module."""
    return {
        name: next(iter(origins))
        for name, origins in imports.items()
        if len(origins) == 1 and "" not in origins and all(v is None for v in found.get(name, []))
    }


def _headers(statement) -> list[ast.AST]:
    """The expressions a compound statement evaluates where it stands, not in its body."""
    if isinstance(statement, (ast.If, ast.While)):
        return [statement.test]
    if isinstance(statement, (ast.For, ast.AsyncFor)):
        return [statement.iter]
    if isinstance(statement, ast.Match):
        return [statement.subject, *(case.guard for case in statement.cases if case.guard is not None)]
    if isinstance(statement, ast.Try) or type(statement).__name__ == "TryStar":
        return [h.type for h in statement.handlers if h.type is not None]
    if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
        arguments = statement.args
        every = (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs, arguments.vararg, arguments.kwarg)
        annotations = [a.annotation for a in every if a is not None and a.annotation is not None]
        returns = [statement.returns] if statement.returns is not None else []
        return [*arguments.defaults, *(d for d in arguments.kw_defaults if d is not None), *annotations, *returns]
    return []


class _Hook:
    """What one hook's reading needs to know about its names."""

    def __init__(self, function, module: tuple[dict[str, list], dict[str, str], bool]):
        module_found, module_imports, star = module
        module_names = set(module_found)
        self.name = function.name
        arguments = function.args
        params = [a.arg for a in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs)]
        found, imports = _bindings(function.body)
        local = set(found) | set(params)
        # A name the hook binds shadows the module's. One it binds only by an
        # import is trusted, as the module's imports are.
        self.imports = {n: o for n, o in module_imports.items() if n not in local}
        self.imports.update(_trusted_imports(found, imports))
        # After `from x import *` at module level, any builtin may be rebound.
        self.shadowed = module_names | local | (set(_READING_BUILTINS) if star else set())
        self.allowed = (module_names | _READING_BUILTINS) - local
        # `config` and `session` are pytest's, unless the hook rebinds them.
        self.allowed |= (_ENVIRONMENT_PARAMS & set(params)) - set(found)
        self.values: dict[str, ast.AST] = {}
        self._settle(found, module_names, module_imports)

    def _settle(self, found: dict[str, list], module_names: set[str], module_imports: dict[str, str]) -> None:
        """Add the environmental locals.

        A local is environmental when it is bound only by imports, or by
        exactly one plain assignment from the environment and nothing else.
        The assigned value replaces the name in a guard (`render`), so the
        guard says what the hook tests. A local that shadows a module-level
        name never is, since the guard would be evaluated against the
        module's binding, unless both import the same module.
        """
        changed = True
        while changed:
            changed = False
            for name, bound in found.items():
                if name in self.allowed:
                    continue
                if name in module_names and not (
                    name in module_imports and self.imports.get(name) == module_imports[name]
                ):
                    continue
                imports = all(v is None for v in bound)
                single = len(bound) == 1 and isinstance(bound[0], ast.AST)
                if imports or (single and self.environmental(bound[0])):
                    self.allowed.add(name)
                    if not imports:
                        self.values[name] = bound[0]
                    changed = True

    def render(self, node: ast.AST, condition) -> str:
        """The condition's source, with each environmental local replaced by its value."""
        if not any(isinstance(n, ast.Name) and n.id in self.values for n in ast.walk(node)):
            return condition(node)
        values = self.values

        class _Inline(ast.NodeTransformer):
            def __init__(self):
                self.depth = 0

            def visit_Name(self, name):
                if name.id in values and self.depth < 8:
                    self.depth += 1
                    return self.visit(copy.deepcopy(values[name.id]))
                return name

        return ast.unparse(_Inline().visit(copy.deepcopy(node)))

    def environmental(self, node: ast.AST) -> bool:
        return all(n.id in self.allowed for n in ast.walk(node) if isinstance(n, ast.Name)) and not any(
            isinstance(n, (ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp))
            for n in ast.walk(node)
        )

    def inert(self, node: ast.AST) -> bool:
        """Can evaluating this expression change nothing but the hook's own locals?"""
        return not any(
            isinstance(n, (ast.Await, ast.YieldFrom)) or (isinstance(n, ast.Call) and not self._reads(n))
            for n in ast.walk(node)
        )

    def _reads(self, call: ast.Call) -> bool:
        """Does this call only read? Its arguments' own calls are judged on their own."""
        func = call.func
        if isinstance(func, ast.Name):
            origin = self.imports.get(func.id)
            if origin is not None:
                return origin in _READER_CALLS or origin.startswith(_READER_PREFIXES)
            if func.id not in _READING_BUILTINS or func.id in self.shadowed:
                return False
            if func.id == "iter":
                return len(call.args) == 1 and not call.keywords
            if func.id in ("map", "filter"):
                return bool(call.args) and self._reading_function(call.args[0])
            if func.id in _CALLING_BUILTINS:
                return all(self._reading_function(k.value) for k in call.keywords if k.arg == "key")
            return True
        if isinstance(func, ast.Attribute):
            name = dotted_name(func)
            if name:
                root, _, rest = name.partition(".")
                origin = self.imports.get(root)
                if origin is not None:
                    resolved = f"{origin}.{rest}"
                    if resolved in _READER_CALLS or resolved.startswith(_READER_PREFIXES):
                        return True
            return func.attr in _READER_METHODS
        return False

    def _reading_function(self, node: ast.AST) -> bool:
        if isinstance(node, ast.Lambda) or (isinstance(node, ast.Constant) and node.value is None):
            return True
        return (
            isinstance(node, ast.Name)
            and node.id in _READING_BUILTINS
            and node.id not in _CALLING_BUILTINS
            and node.id not in self.shadowed
        )

    def effect(self, statement) -> ast.AST | None:
        """The condition this simple statement adds when it is an effect: `True` for none, else None."""
        if isinstance(statement, ast.Return):
            value = statement.value
            if value is not None and not self.inert(value):
                return ast.Constant(True)
            if self.name != "pytest_ignore_collect" or value is None:
                return None
            if isinstance(value, ast.Constant) and value.value in (None, False):
                return None
            return value
        return None if self._inert_statement(statement) else ast.Constant(True)

    def _inert_statement(self, statement) -> bool:
        if isinstance(statement, (ast.Pass, ast.Break, ast.Continue, ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal)):
            return True
        if isinstance(statement, ast.Expr):
            return self.inert(statement.value)
        if isinstance(statement, ast.Assign):
            return all(_plain(t) for t in statement.targets) and self.inert(statement.value)
        if isinstance(statement, ast.AnnAssign):
            return _plain(statement.target) and (statement.value is None or self.inert(statement.value))
        if isinstance(statement, ast.Delete):
            return all(isinstance(t, ast.Name) for t in statement.targets)
        if isinstance(statement, ast.Assert):
            return self.inert(statement.test) and (statement.msg is None or self.inert(statement.msg))
        if isinstance(statement, ast.Raise):
            return all(x is None or self.inert(x) for x in (statement.exc, statement.cause))
        return False


def _ends(statement, in_loop: bool) -> bool:
    return isinstance(statement, (ast.Return, ast.Raise)) or (
        in_loop and isinstance(statement, (ast.Continue, ast.Break))
    )


def _walk(statements, conds, hook: _Hook, sites, in_loop=False) -> bool:
    """Record (node, conds) for each effect; True when the list always ends."""
    for statement in statements:
        for node in _headers(statement):
            if not hook.inert(node):
                sites.append((node, conds))
        if isinstance(statement, ast.If):
            body = _walk(statement.body, conds + (("test", statement.test),), hook, sites, in_loop)
            orelse = _walk(statement.orelse, conds + (("not", statement.test),), hook, sites, in_loop)
            if body and orelse:
                return True
            if body:
                conds = conds + (("not", statement.test),)
            elif orelse:
                conds = conds + (("test", statement.test),)
            continue
        if isinstance(statement, (ast.For, ast.AsyncFor)):
            if not _plain(statement.target):
                sites.append((statement.target, conds))
            _walk(statement.body, conds, hook, sites, in_loop=True)
            _walk(statement.orelse, conds, hook, sites, in_loop)
            continue
        if isinstance(statement, ast.While):
            _walk(statement.body, conds + (("test", statement.test),), hook, sites, in_loop=True)
            _walk(statement.orelse, conds, hook, sites, in_loop)
            continue
        if isinstance(statement, (ast.With, ast.AsyncWith)):
            # The context manager runs code here, and can swallow what ends the body.
            sites.extend((item.context_expr, conds) for item in statement.items)
            _walk(statement.body, conds, hook, sites, in_loop)
            continue
        if isinstance(statement, ast.Try) or type(statement).__name__ == "TryStar":
            from .frontend import _handler_guard  # the frontend imports this module

            _walk(statement.body + statement.orelse, conds, hook, sites, in_loop)
            for handler in statement.handlers:
                raw = ("raw", _handler_guard(statement, handler))
                _walk(handler.body, conds + (raw,), hook, sites, in_loop)
            if _walk(statement.finalbody, conds, hook, sites, in_loop):
                return True
            continue
        if isinstance(statement, ast.Match):
            # A case pattern selects; it does not say when the hook acts.
            for case in statement.cases:
                _walk(case.body, conds, hook, sites, in_loop)
            continue
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Its body runs where it is called, and that call is an effect.
            # Its decorators are called here.
            sites.extend((d, conds) for d in statement.decorator_list)
            continue
        if isinstance(statement, ast.ClassDef):
            # A class body runs here.
            sites.append((statement, conds))
            continue
        extra = hook.effect(statement)
        if extra is not None:
            sites.append((statement, conds + (("test", extra),)))
        if _ends(statement, in_loop):
            return True
    return False


def _guard(conds, hook: _Hook, condition) -> str | None:
    """The environmental conjuncts of a path condition, or None for none."""
    parts: list[str] = []
    for kind, node in conds:
        if kind == "raw":
            parts.append(node)
        elif kind == "test":
            values = node.values if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.And) else [node]
            parts.extend(
                hook.render(v, condition) for v in values
                if not (isinstance(v, ast.Constant) and v.value is True) and hook.environmental(v)
            )
        elif hook.environmental(node):
            parts.append(f"not ({hook.render(node, condition)})")
    return _conjunction(tuple(parts))


def weakest(guards: list[str | None]) -> str | None:
    """One guard for several controls: None if any has none, else their disjunction."""
    if not guards or any(g is None for g in guards):
        return None
    unique = list(dict.fromkeys(guards))
    return unique[0] if len(unique) == 1 else " or ".join(f"({g})" for g in unique)


def collection_hook_guards(tree: ast.Module, condition) -> tuple[dict[int, str | None], dict[int, str | None]]:
    """The guard of each collection hook definition, and of each `add_marker` call in one.

    Both map `id(node)` to a guard, None when unguarded. A hook with no effect
    is unguarded, as every hook was before (#209 Q2 decides which hooks are
    controls at all). An `add_marker` call outside a collection hook is not in
    the second map. `condition` gives an expression's source text.
    """
    found, imports = _bindings(tree.body)
    star = any(
        isinstance(s, ast.ImportFrom) and any(a.name == "*" for a in s.names) for s in _scope_statements(tree.body)
    )
    module = (found, _trusted_imports(found, imports), star)
    hooks: dict[int, str | None] = {}
    calls: dict[int, str | None] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name not in COLLECTION_HOOKS:
            continue
        hook = _Hook(node, module)
        sites: list[tuple[ast.AST, tuple]] = []
        _walk(node.body, (), hook, sites)
        guards = []
        for site, conds in sites:
            guard = _guard(conds, hook, condition)
            guards.append(guard)
            for call in ast.walk(site):
                if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == "add_marker":
                    calls[id(call)] = guard
        hooks[id(node)] = weakest(guards)
    return hooks, calls

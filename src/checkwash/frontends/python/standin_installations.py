"""Source-only installation effects that reach an existing Python oracle.

Assignments, native setattr and literal module/dictionary replacements share
one effect predicate. A spelling alone is insufficient: a statically bound
repository target must be replaced before a live assertion consumes it. The
ordinary frontend retains its patch API/IR contracts; this pass contributes
only installation events, never alignment or repair/equivalence credit.

Only literal, statically selected execution is followed. Dynamic targets,
unknown branch selection, external fixtures/plugins and recursion provide no
positive installation proof. Repository code is never executed.
"""

from __future__ import annotations

import ast
from collections.abc import Sequence
from dataclasses import dataclass, field, replace

from checkwash.change import EngineError
from checkwash.conftest_context import ConftestContext
from checkwash.frontends.python.frontend import _static_truth, parse_python
from checkwash.gating import unit_is_live
from checkwash.ir.astutil import stable_dump
from checkwash.pyenv import known_baseline
from checkwash.roles import collectable

_MAX_SOURCE_BYTES = 1_000_000
_MAX_SOURCE_NODES = 30_000
_MAX_CONTEXT_READS = 4096
_MAX_CONTEXT_BYTES = 64_000_000
_MAX_ANALYSIS_STEPS = 1_000_000


def _syntax(source):
    if source is not None and not isinstance(source, bytes):
        raise EngineError("stand-in source is not bytes")
    if source is None:
        return None
    if len(source) > _MAX_SOURCE_BYTES:
        raise EngineError("stand-in source exceeds the byte limit")
    try:
        tree = ast.parse(source.decode("utf-8-sig"))
    except (SyntaxError, UnicodeError, ValueError, RecursionError):
        return None
    if sum(1 for _node in ast.walk(tree)) > _MAX_SOURCE_NODES:
        raise EngineError("stand-in source exceeds the syntax node limit")
    return tree


@dataclass(frozen=True)
class _Effect:
    path: str
    target: str
    kind: str
    replacement: str
    text: str
    span: tuple[int, int]

    @property
    def key(self):
        return self.target, self.kind, self.replacement


@dataclass(frozen=True)
class _Value:
    alias: str | None = None
    effects: frozenset[_Effect] = frozenset()


@dataclass
class _Function:
    module: "_Module"
    node: ast.FunctionDef | ast.AsyncFunctionDef
    qualname: str
    fixture_name: str | None = None
    autouse: bool = False


@dataclass
class _Module:
    path: str
    source: str
    tree: ast.Module
    package: str
    functions: dict[str, _Function] = field(default_factory=dict)
    env: dict[str, _Value] = field(default_factory=dict)
    baseline_imports: dict[tuple[str, str], str] = field(default_factory=dict)


def _value(*values, alias=None):
    return _Value(alias, frozenset(effect for value in values for effect in value.effects))


def _literal(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _import_module(node, package):
    module = node.module or ""
    if node.level:
        parts = package.split(".") if package else []
        if node.level > len(parts):
            return None
        parent = parts[:len(parts) - node.level + 1]
        module = ".".join([*parent, module] if module else parent)
    return module or None


def _package(path, exists):
    directory = path.rpartition("/")[0]
    parts = []
    while directory and exists(f"{directory}/__init__.py"):
        parent, _, leaf = directory.rpartition("/")
        if not leaf.isidentifier():
            return ""
        parts.insert(0, leaf)
        directory = parent
    return ".".join(parts)


def _candidate(source, imported_names=()):
    tree = _syntax(source)
    if tree is None:
        return False
    imports = set(imported_names)
    imports.update(a.asname or a.name.split(".")[0] for node in ast.walk(tree)
                   if isinstance(node, (ast.Import, ast.ImportFrom)) for a in node.names)
    setters = {"setattr"} | {a.asname or a.name for node in ast.walk(tree)
                             if isinstance(node, ast.ImportFrom) and node.module == "builtins" and not node.level
                             for a in node.names if a.name == "setattr"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in setters:
                return True
            if isinstance(node.func, ast.Attribute) and node.func.attr in {"setattr", "setitem"}:
                # The binding check below separates builtins.setattr from
                # arbitrary methods and existing monkeypatch API coverage.
                return True
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, (ast.Attribute, ast.Subscript)) or
                   isinstance(t, ast.Name) and t.id in imports for t in targets):
                return True
    return False


def _imports(source):
    tree = _syntax(source)
    if tree is None:
        return set()
    return {a.asname or a.name.split(".")[0] for n in ast.walk(tree)
            if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}


class _Trace:
    def __init__(self, modules, context, side, deny, budget=None):
        self.modules = modules
        self.context = context
        self.side = side
        self.deny = deny
        self.active: dict[tuple[str, str], _Effect] = {}
        self.observed: set[_Effect] = set()
        self.stack = []
        self.steps = 0
        self.test_module = None
        self.budget = budget if budget is not None else [0]

    def owned(self, target):
        if target.startswith("@") or target.split(".", 1)[0] in self.deny:
            return False
        return self.context.contains(target, self.side)

    def _step(self):
        self.steps += 1
        self.budget[0] += 1
        if self.steps > 20_000 or self.budget[0] > _MAX_ANALYSIS_STEPS:
            raise EngineError("stand-in execution proof exceeds the source step limit")

    def effect(self, target, kind="attribute"):
        return frozenset(e for (name, k), e in self.active.items()
                         if k == kind and (name == target or kind == "module" and target.startswith(name + ".")))

    def expression(self, node, module, env, qualname, *, native_setattr=True):
        self._step()
        if node is None:
            return _Value()
        if isinstance(node, ast.Name):
            return env.get(node.id, _Value())
        if isinstance(node, ast.Attribute):
            base = self.expression(node.value, module, env, qualname, native_setattr=native_setattr)
            if base.alias == "@request" and node.attr == "module":
                return _Value("@test_module")
            if base.alias == "@test_module" and self.test_module is not None:
                return self.test_module.env.get(node.attr, _Value())
            alias = f"{base.alias}.{node.attr}" if base.alias else None
            return _Value(alias, base.effects | (self.effect(alias) if alias else frozenset()))
        if isinstance(node, ast.Lambda):
            return _Value()  # constructing a callable does not execute its body
        if isinstance(node, ast.Call):
            fn = self.expression(node.func, module, env, qualname, native_setattr=native_setattr)
            args = [self.expression(n, module, env, qualname, native_setattr=native_setattr) for n in node.args]
            kwargs = {k.arg: self.expression(k.value, module, env, qualname, native_setattr=native_setattr)
                      for k in node.keywords if k.arg is not None}
            builtin = (isinstance(node.func, ast.Name) and node.func.id == "setattr" and native_setattr
                       and "setattr" not in env) or fn.alias == "builtins.setattr"
            if builtin and len(node.args) == 3 and not node.keywords:
                attr = _literal(node.args[1])
                if args[0].alias and attr:
                    self.install(f"{args[0].alias}.{attr}", "attribute", args[2], node.args[2], node, module)
                return _Value()
            native_name = node.func.id if isinstance(node.func, ast.Name) and node.func.id not in env else None
            if (native_name == "vars" or fn.alias == "builtins.vars") and len(args) == 1 and not kwargs:
                return _value(args[0], alias=f"{args[0].alias}.__dict__" if args[0].alias else None)
            if (native_name == "getattr" or fn.alias == "builtins.getattr") and len(args) in (2, 3):
                attr = _literal(node.args[1])
                if attr and args[0].alias == "@test_module" and self.test_module is not None:
                    return self.test_module.env.get(attr, args[2] if len(args) == 3 else _Value())
                if attr and args[0].alias:
                    target = f"{args[0].alias}.{attr}"
                    return _Value(target, args[0].effects | self.effect(target))
            if fn.alias == "importlib.import_module" and node.args:
                imported = _literal(node.args[0])
                if imported and all(part.isidentifier() for part in imported.split(".")):
                    return _Value(imported, self.effect(imported, "module"))
            if fn.alias == "pytest.MonkeyPatch" and not args and not kwargs:
                return _Value("@monkeypatch")
            if fn.alias == "@monkeypatch.setitem" and len(args) == 3 and not kwargs:
                name = _literal(node.args[1])
                if name and args[0].alias and args[0].alias.endswith(".__dict__"):
                    self.install(f"{args[0].alias[:-9]}.{name}", "attribute", args[2], node.args[2], node, module)
                return _Value()
            helper = module.functions.get(fn.alias.removeprefix("@function:") if fn.alias else "")
            if helper is not None:
                return _value(fn, *args, *kwargs.values(), self.function(helper, args, kwargs))
            result = _value(fn, *args, *kwargs.values())
            if isinstance(node.func, ast.Attribute) and node.func.attr.startswith("assert"):
                self.observe(result)
            return result
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            return _Value()  # separate dynamic execution scope
        return _value(*(self.expression(child, module, env, qualname, native_setattr=native_setattr)
                        for child in ast.iter_child_nodes(node) if isinstance(child, ast.expr)))

    def observe(self, value):
        self.observed.update(e for e in value.effects if self.owned(e.target))

    def install(self, target, kind, value, replacement, node, module):
        test_binding = None
        if target.startswith("@test_module.") and self.test_module is not None:
            name = target.removeprefix("@test_module.")
            old = self.test_module.env.get(name, _Value())
            original = self.test_module.baseline_imports.get(("", name)) or old.alias
            if not original or original.startswith("@"):
                return None
            target, kind, test_binding = original, "binding", name
        if value.alias == target and not value.effects:
            self.active.pop((target, kind), None)  # restoring the captured original
            if test_binding:
                self.test_module.env[test_binding] = value
            return None
        effect = _Effect(module.path, target, kind,
                         value.alias or stable_dump(replacement),
                         ast.get_source_segment(module.source, node) or ast.unparse(node),
                         (node.lineno, getattr(node, "end_lineno", node.lineno)))
        self.active[target, kind] = effect
        if test_binding:
            self.test_module.env[test_binding] = replace(value, effects=value.effects | {effect})
        return effect

    def assign(self, target, value, replacement, node, module, env, qualname):
        if isinstance(target, ast.Name):
            old = (env.get(target.id, _Value()).alias or module.baseline_imports.get((qualname, target.id))
                   or module.baseline_imports.get(("", target.id)))
            if old and not old.startswith("@") and value.alias != old:
                effect = self.install(old, "binding", value, replacement, node, module)
                if effect is not None:
                    value = replace(value, effects=value.effects | {effect})
            env[target.id] = value
        elif isinstance(target, ast.Attribute):
            base = self.expression(target.value, module, env, qualname)
            if base.alias:
                self.install(f"{base.alias}.{target.attr}", "attribute", value, replacement, node, module)
        elif isinstance(target, ast.Subscript):
            base = self.expression(target.value, module, env, qualname)
            name = _literal(target.slice)
            if name and base.alias == "sys.modules":
                self.install(name, "module", value, replacement, node, module)
            elif name and base.alias and base.alias.endswith(".__dict__"):
                self.install(f"{base.alias[:-9]}.{name}", "attribute", value, replacement, node, module)
        elif isinstance(target, (ast.Tuple, ast.List)) and isinstance(replacement, (ast.Tuple, ast.List)):
            if len(target.elts) == len(replacement.elts):
                for dest, source in zip(target.elts, replacement.elts):
                    self.assign(dest, self.expression(source, module, env, qualname), source, node, module, env, qualname)

    def block(self, statements, module, env, qualname, *, native_setattr=True):
        result = _Value()
        for node in statements:
            self._step()
            if isinstance(node, ast.Import):
                for alias in node.names:
                    local = alias.asname or alias.name.split(".")[0]
                    target = alias.name if alias.asname else alias.name.split(".")[0]
                    env[local] = _Value(target, self.effect(alias.name, "module"))
                    module.baseline_imports.setdefault((qualname, local), target)
            elif isinstance(node, ast.ImportFrom):
                imported = _import_module(node, module.package)
                if imported:
                    for alias in node.names:
                        if alias.name == "*":
                            continue
                        target = f"{imported}.{alias.name}"
                        local = alias.asname or alias.name
                        env[local] = _Value(target, self.effect(imported, "module") | self.effect(target))
                        module.baseline_imports.setdefault((qualname, local), target)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qual = f"{qualname}.{node.name}" if qualname else node.name
                function = _Function(module, node, qual)
                for decorator in node.decorator_list:
                    call = decorator if isinstance(decorator, ast.Call) else None
                    value = self.expression(call.func if call else decorator, module, env, qualname)
                    if value.alias == "pytest.fixture":
                        function.fixture_name = node.name
                        if call:
                            for keyword in call.keywords:
                                if keyword.arg == "name" and _literal(keyword.value):
                                    function.fixture_name = _literal(keyword.value)
                                if keyword.arg == "autouse" and isinstance(keyword.value, ast.Constant):
                                    function.autouse = keyword.value.value is True
                module.functions[qual] = function
                env[node.name] = _Value(f"@function:{qual}")
            elif isinstance(node, ast.ClassDef):
                # Keep class fixtures separate; a test outside this class must
                # never inherit its providers or autouse markers.
                qual = f"{qualname}.{node.name}" if qualname else node.name
                class_env = dict(env)
                self.block(node.body, module, class_env, qual)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                if node.value is None:
                    continue
                if isinstance(node.value, (ast.Yield, ast.YieldFrom)):
                    return self.expression(node.value.value, module, env, qualname, native_setattr=native_setattr)
                value = self.expression(node.value, module, env, qualname, native_setattr=native_setattr)
                for target in node.targets if isinstance(node, ast.Assign) else [node.target]:
                    self.assign(target, value, node.value, node, module, env, qualname)
            elif isinstance(node, ast.Assert):
                self.observe(self.expression(node.test, module, env, qualname, native_setattr=native_setattr))
            elif isinstance(node, ast.Return):
                return self.expression(node.value, module, env, qualname, native_setattr=native_setattr)
            elif isinstance(node, ast.Expr) and isinstance(node.value, (ast.Yield, ast.YieldFrom)):
                # Fixtures hand control to the test here; teardown cannot
                # retroactively install a stand-in under the earlier oracle.
                return self.expression(node.value.value, module, env, qualname, native_setattr=native_setattr)
            elif isinstance(node, ast.Expr):
                result = self.expression(node.value, module, env, qualname, native_setattr=native_setattr)
            elif isinstance(node, ast.If):
                truth = _static_truth(node.test)
                if truth is not None:
                    result = self.block(node.body if truth else node.orelse, module, env, qualname, native_setattr=native_setattr)
                else:
                    for child in ast.walk(node):
                        if isinstance(child, ast.Name) and isinstance(child.ctx, (ast.Store, ast.Del)):
                            env.pop(child.id, None)
            elif isinstance(node, (ast.With, ast.AsyncWith)):
                # Ordinary context managers do not make an explicit setattr
                # or assignment inert. Patch API lifetimes remain the existing
                # frontend's responsibility, so no API effect is invented.
                for item in node.items:
                    self.expression(item.context_expr, module, env, qualname, native_setattr=native_setattr)
                result = self.block(node.body, module, env, qualname, native_setattr=native_setattr)
        return result

    def function(self, function, args=(), kwargs=None):
        identity = (function.module.path, function.qualname)
        if identity in self.stack or len(self.stack) >= 8:
            return _Value()
        kwargs = kwargs or {}
        self.stack.append(identity)
        try:
            node = function.node
            parameters = [a.arg for a in node.args.posonlyargs + node.args.args]
            env = dict(function.module.env)
            # Python makes every assignment in a function lexical, including
            # a later/conditional one. Do not borrow that name from the module.
            lexical = set(parameters) | {a.arg for a in node.args.kwonlyargs}

            class Bindings(ast.NodeVisitor):
                def visit_Name(self, item):
                    if isinstance(item.ctx, (ast.Store, ast.Del)):
                        lexical.add(item.id)

                def visit_FunctionDef(self, item):
                    lexical.add(item.name)

                visit_AsyncFunctionDef = visit_FunctionDef

                def visit_ClassDef(self, item):
                    lexical.add(item.name)

                def visit_Import(self, item):
                    lexical.update(a.asname or a.name.split(".")[0] for a in item.names)

                def visit_ImportFrom(self, item):
                    lexical.update(a.asname or a.name for a in item.names)

            visitor = Bindings()
            for statement in node.body:
                visitor.visit(statement)
            for name in lexical:
                env[name] = _Value()
            for index, name in enumerate(parameters):
                env[name] = args[index] if index < len(args) else kwargs.get(name, _Value())
            for arg in node.args.kwonlyargs:
                env[arg.arg] = kwargs.get(arg.arg, _Value())
            return self.block(node.body, function.module, env, function.qualname, native_setattr="setattr" not in lexical)
        finally:
            self.stack.pop()


def _module(path, source, package, baseline=None):
    tree = _syntax(source)
    if tree is None:
        return None
    text = source.decode("utf-8-sig")
    module = _Module(path, text, tree, package, baseline_imports=dict(baseline or {}))

    def imports(statements, qualname=""):
        for node in statements:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module.baseline_imports.setdefault((qualname, alias.asname or alias.name.split(".")[0]),
                                                       alias.name if alias.asname else alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                name = _import_module(node, package)
                if name:
                    for alias in node.names:
                        if alias.name != "*":
                            module.baseline_imports.setdefault((qualname, alias.asname or alias.name), f"{name}.{alias.name}")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                imports(node.body, f"{qualname}.{node.name}" if qualname else node.name)

    imports(tree.body)
    return module


def _fixture_requests(function):
    node = function.node
    names = [a.arg for a in node.args.posonlyargs + node.args.args + node.args.kwonlyargs
             if a.arg not in {"self", "cls"}]
    direct = set()
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
            continue
        if decorator.func.attr == "usefixtures":
            names.extend(name for arg in decorator.args if (name := _literal(arg)))
        elif decorator.func.attr == "parametrize" and decorator.args:
            argnames = _literal(decorator.args[0])
            if argnames is not None:
                columns = {name.strip() for name in argnames.split(",")}
            elif isinstance(decorator.args[0], (ast.Tuple, ast.List)):
                columns = {_literal(arg) for arg in decorator.args[0].elts} - {None}
            else:
                continue
            indirect = next((k.value for k in decorator.keywords if k.arg == "indirect"), None)
            if isinstance(indirect, ast.Constant) and indirect.value is True:
                continue
            selected = {_literal(arg) for arg in indirect.elts} if isinstance(indirect, (ast.Tuple, ast.List)) else set()
            direct.update(columns - selected)
    return [name for name in names if name not in direct]


def _observed_for_test(modules, test_path, qualname, context, side, deny, budget):
    trace = _Trace(modules, context, side, deny, budget)
    active_modules = []
    for module in modules:
        if module.path == test_path:
            continue
        module = replace(module, functions={}, env={})
        trace.block(module.tree.body, module, module.env, "")
        active_modules.append(module)
    for module in active_modules:
        for name in ("pytest_configure", "pytest_sessionstart"):
            hook = module.functions.get(name)
            if hook is not None:
                trace.function(hook)
    test_module = replace(next(m for m in modules if m.path == test_path), functions={}, env={})
    trace.block(test_module.tree.body, test_module, test_module.env, "")
    trace.test_module = test_module
    active_modules.append(test_module)
    function = test_module.functions.get(qualname)
    if function is None:
        return set()
    # Setup hooks precede fixture evaluation; module-level imports have already
    # captured their providers, so a later sys.modules write cannot alter them.
    for module in active_modules:
        for name in ("pytest_collection_modifyitems", "pytest_collection_finish", "pytest_generate_tests", "pytest_runtest_setup"):
            hook = module.functions.get(name)
            if hook is not None:
                trace.function(hook)
    fixtures = {}
    autouse = set()
    class_prefix = qualname.rpartition(".")[0]
    for module in active_modules:
        for candidate in module.functions.values():
            if candidate.fixture_name is None:
                continue
            owner = candidate.qualname.rpartition(".")[0]
            if owner and not (class_prefix == owner or class_prefix.startswith(owner + ".")):
                continue
            fixtures[candidate.fixture_name] = candidate
            if candidate.autouse:
                autouse.add(candidate.fixture_name)
    values = {}
    pending = set()

    def activate(name):
        if name in values:
            return values[name]
        function = fixtures.get(name)
        if function is None:
            if name == "request":
                return _Value("@request")
            if name == "monkeypatch":
                return _Value("@monkeypatch")
            return _Value()
        if name in pending:
            return _Value()
        pending.add(name)
        kwargs = {dependency: activate(dependency) for dependency in _fixture_requests(function)}
        values[name] = trace.function(function, kwargs=kwargs)
        pending.remove(name)
        return values[name]

    for name in sorted(autouse):
        activate(name)
    kwargs = {name: activate(name) for name in _fixture_requests(function)}
    trace.function(function, kwargs=kwargs)
    return trace.observed


def installation_events(ir, changes, config, *, root_reader=None, root_searcher=None, root_path_lister=None):
    """(path, unit, target, text, span) for new effects on existing oracles."""
    # Legacy direct callers (including frozen corpus emitters) do not provide
    # a complete repository view. Preserve that API's established coverage;
    # absence of callbacks is not evidence that a provider is repository-owned.
    if root_reader is None:
        return []
    changed = {}
    for change in changes:
        path = change.path.replace("\\", "/")
        old = (change.old_path or path).replace("\\", "/")
        changed[path] = (change.before if old == path else None, change.after)
        if old != path:
            changed[old] = (change.before, None)
    deny = known_baseline() | set(ir.globals.third_party_roots)
    candidates = set()
    candidate_bytes = 0
    for path, sides in changed.items():
        role = config.role_of(path)
        if role not in {"test", "conftest"}:
            continue
        candidate_bytes += sum(len(source) for source in sides if source is not None)
        if candidate_bytes > _MAX_CONTEXT_BYTES:
            raise EngineError("stand-in changed context exceeds the source byte limit")
        imported = _imports(sides[0])
        if any(_candidate(source, imported) for source in sides) and (
            role == "test" or _new_assignment_candidate(sides, deny)
        ):
            candidates.add(path)
    if not candidates:
        return []
    conftest_changed = {path for path in candidates if config.role_of(path) == "conftest"}
    raw_inventory = ()
    if conftest_changed:
        if root_path_lister is not None:
            raw_inventory = root_path_lister()
        elif root_searcher is not None:
            # Legacy STRICT search's empty needle inventories every nonempty
            # Python file. That is complete for oracle consumers (an empty
            # module has none), but is NOT a shadow/package inventory.
            raw_inventory = root_searcher([""])
    if (not isinstance(raw_inventory, Sequence) or isinstance(raw_inventory, (str, bytes))
            or len(raw_inventory) > 200_000):
        raise EngineError("stand-in strict inventory is invalid or exceeds the path limit")
    inventory = set()
    for path in raw_inventory:
        if not isinstance(path, str):
            raise EngineError("stand-in strict inventory contains an invalid path")
        path = path.replace("\\", "/")
        if not path or path.startswith("/") or ":" in path or any(p in {"", ".", ".."} for p in path.split("/")):
            raise EngineError("stand-in strict inventory contains an unsafe path")
        inventory.add(path)
    test_paths = {path for path in candidates if config.role_of(path) == "test"}
    test_paths.update(path for path in inventory if config.role_of(path) == "test" and collectable(path)
                      and any(not c.rpartition("/")[0] or path.startswith(c.rpartition("/")[0] + "/")
                              for c in conftest_changed))
    memo = {}
    read_bytes = [0]
    budget = [0]

    def read(path, side):
        if path in changed:
            return changed[path][side]
        if path not in memo:
            if len(memo) >= _MAX_CONTEXT_READS:
                raise EngineError("stand-in context exceeds the source read limit")
            if root_reader is None:
                memo[path] = None
            else:
                memo[path] = root_reader(path)
            if memo[path] is not None and not isinstance(memo[path], bytes):
                raise EngineError("stand-in strict snapshot returned invalid source bytes")
            if memo[path] is not None:
                read_bytes[0] += len(memo[path])
                if len(memo[path]) > _MAX_SOURCE_BYTES or read_bytes[0] > _MAX_CONTEXT_BYTES:
                    raise EngineError("stand-in context exceeds the source byte limit")
            if path in inventory and memo[path] is None:
                raise EngineError("stand-in inventoried source disappeared")
        return memo[path]

    # Ownership probes share the same bounded reader as consumer discovery.
    context = ConftestContext(changes, lambda path: read(path, 1))
    events = []
    for path in sorted(test_paths):
        if not collectable(path):
            continue
        sides = [read(path, side) for side in (0, 1)]
        if any(source is None for source in sides):
            continue  # a new test has no existing oracle to replace
        if any(_syntax(source) is None for source in sides):
            continue
        parsed = [parse_python(source, collect_tests=True) for source in sides]
        if not all(p.parse_ok for p in parsed):
            continue
        live = [{u.qualname for u in p.units if unit_is_live(u.side, p.constants)} for p in parsed]
        ancestors = []
        directory = path.rpartition("/")[0]
        while True:
            ancestors.append(f"{directory}/conftest.py" if directory else "conftest.py")
            if not directory:
                break
            directory = directory.rpartition("/")[0]
        modules = [[], []]
        for source_path in [*reversed(ancestors), path]:
            baseline = None
            for side in (0, 1):
                source = read(source_path, side)
                if source is None:
                    continue
                package = _package(source_path, lambda candidate: read(candidate, side) is not None)
                module = _module(source_path, source, package, baseline)
                if module is None:
                    raise EngineError("stand-in provider context could not be parsed")
                # Baseline imports identify the removal-and-assignment form;
                # they do not execute or activate a provider on the head side.
                seed = _Trace([], context, side, deny, budget)
                seed.block(module.tree.body, module, module.env, "")
                if side == 0:
                    baseline = dict(module.baseline_imports)
                modules[side].append(module)
        for qualname in sorted(live[0] & live[1]):
            before = _observed_for_test(modules[0], path, qualname, context, 0, deny, budget)
            after = _observed_for_test(modules[1], path, qualname, context, 1, deny, budget)
            previous = {effect.key for effect in before}
            for effect in sorted(after, key=lambda e: (e.path, e.target, e.text, e.span)):
                if effect.key not in previous:
                    events.append((effect.path, qualname if effect.path == path else None,
                                   effect.target, effect.text, effect.span))
    return sorted(set(events), key=lambda row: (row[0], row[1] or "", row[2], row[3], row[4]))


def _new_assignment_candidate(sides, deny=()):
    """Only changed, potentially first-party effects need reverse discovery.

    This is a scheduling filter, not the finding predicate: positional
    bindings, ownership and actual oracle reach are checked by the trace.
    It keeps ordinary sys.path setup and unchanged legacy installations from
    acquiring a new whole-repository inventory requirement.
    """
    def keys(source, inherited=()):
        tree = _syntax(source)
        if tree is None:
            return set(), (), dict(inherited)
        aliases = {"request": "@request", **dict(inherited)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for item in node.names:
                    aliases[item.asname or item.name.split(".")[0]] = item.name if item.asname else item.name.split(".")[0]
            elif isinstance(node, ast.ImportFrom):
                for item in node.names:
                    # This broad filter must retain relative bindings. The
                    # execution trace later requires a real package anchor.
                    module = f"@relative.{node.module or ''}" if node.level else node.module
                    if module:
                        aliases[item.asname or item.name] = f"{module}.{item.name}"

        def path(node):
            if isinstance(node, ast.Name):
                return aliases.get(node.id)
            if isinstance(node, ast.Attribute):
                base = path(node.value)
                return f"{base}.{node.attr}" if base else None
            if isinstance(node, ast.Call):
                fn = path(node.func)
                if fn == "importlib.import_module" and node.args:
                    return _literal(node.args[0])
                if ((isinstance(node.func, ast.Name) and node.func.id == "vars" and "vars" not in aliases)
                        or fn == "builtins.vars") and len(node.args) == 1:
                    return path(node.args[0])
            return None

        found = set()
        for node in ast.walk(tree):
            target = None
            if isinstance(node, ast.Call) and node.args:
                fn = path(node.func)
                if (isinstance(node.func, ast.Name) and node.func.id == "setattr") or fn == "builtins.setattr":
                    target = path(node.args[0])
                elif isinstance(node.func, ast.Attribute) and node.func.attr == "setitem":
                    target = path(node.args[0])
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for item in targets:
                    selected = path(item.value) if isinstance(item, (ast.Attribute, ast.Subscript)) else path(item)
                    if selected == "sys.modules" and isinstance(item, ast.Subscript):
                        selected = _literal(item.slice)
                    if selected and selected.split(".", 1)[0] not in deny:
                        target = selected
                        break
            if target and target.split(".", 1)[0] not in deny:
                found.add(stable_dump(node))
        registrations = tuple(stable_dump(ast.FunctionDef(name=n.name, args=n.args, body=[],
                              decorator_list=n.decorator_list, returns=None, type_comment=None))
                              for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
        return found, registrations, aliases

    before, b_registration, aliases = keys(sides[0])
    after, a_registration, _ = keys(sides[1], aliases)
    return bool(after - before or after and a_registration != b_registration)

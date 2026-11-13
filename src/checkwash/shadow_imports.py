"""Live test and fixture import extraction and revision-local memoisation."""

from __future__ import annotations

import ast
from types import MappingProxyType
from typing import Callable, Iterable, Mapping, Sequence

from checkwash.change import FileChange
from checkwash.frontends.python.frontend import _static_truth, parse_python
from checkwash.shadow_controls import _source_package
from checkwash.shadow_runners import _scope_applies
from checkwash.shadow_models import (
    _FixtureBinding,
    _decode,
    _dotted,
    _live_shadow_attr,
)
from checkwash.shadow_providers import (
    _provider_execution_key,
    _provider_package_chain,
    _side_source,
    _source_key,
)


def _import_targets(
    node: ast.AST, extra_used: Iterable[str] = (), *, package: str = ""
) -> set[str]:
    Position = tuple[int, int]
    bindings: list[tuple[str, tuple[str, ...], Position]] = []
    external_used = set(extra_used)
    loads: dict[str, list[Position]] = {}
    writes: dict[str, list[Position]] = {}

    def position(current: ast.AST) -> Position:
        return getattr(current, "lineno", -1), getattr(current, "col_offset", -1)

    def write(name: str, current: ast.AST) -> None:
        writes.setdefault(name, []).append(position(current))

    def bind(target: ast.AST | None, current: ast.AST) -> None:
        if isinstance(target, ast.Name):
            write(target.id, current)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for element in target.elts:
                bind(element, current)
        elif isinstance(target, ast.Starred):
            bind(target.value, current)

    class Visitor(ast.NodeVisitor):
        def __init__(self, root: ast.AST):
            self.root = root

        def visit_FunctionDef(self, current):  # noqa: N802 - ast visitor API
            if current is self.root:
                self.generic_visit(current)
            else:
                write(current.name, current)

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_ClassDef(self, current):  # noqa: N802 - ast visitor API
            if current is self.root:
                self.generic_visit(current)
            else:
                write(current.name, current)

        def visit_Lambda(self, current):  # noqa: N802 - ast visitor API
            return

        def visit_If(self, current):  # noqa: N802 - ast visitor API
            # Imports used only for typing never become runtime providers.
            guard = _dotted(current.test)
            if guard in ("TYPE_CHECKING", "typing.TYPE_CHECKING"):
                for stmt in current.orelse:
                    self.visit(stmt)
                return
            truth = _static_truth(current.test)
            if truth is not None:
                branch = current.body if truth else current.orelse
                for stmt in branch:
                    self.visit(stmt)
                return
            self.generic_visit(current)

        def visit_Import(self, current):  # noqa: N802 - ast visitor API
            for alias in current.names:
                local = alias.asname or alias.name.split(".", 1)[0]
                write(local, current)
                bindings.append((local, (alias.name,), position(current)))

        def visit_ImportFrom(self, current):  # noqa: N802 - ast visitor API
            module = current.module or ""
            if current.level:
                parts = package.split(".") if package else []
                if current.level > len(parts):
                    return  # no established package, or beyond its root
                parent = parts[: len(parts) - current.level + 1]
                module = ".".join([*parent, module] if module else parent)
            if not module:
                return
            for alias in current.names:
                if alias.name != "*":
                    local = alias.asname or alias.name
                    write(local, current)
                    bindings.append(
                        (
                            local,
                            (module, f"{module}.{alias.name}"),
                            position(current),
                        )
                    )

        def visit_Assign(self, current):  # noqa: N802 - ast visitor API
            for target in current.targets:
                bind(target, current)
            self.visit(current.value)

        def visit_AnnAssign(self, current):  # noqa: N802 - ast visitor API
            bind(current.target, current)
            if current.value is not None:
                self.visit(current.value)

        def visit_AugAssign(self, current):  # noqa: N802 - ast visitor API
            bind(current.target, current)
            self.visit(current.value)

        def visit_NamedExpr(self, current):  # noqa: N802 - ast visitor API
            bind(current.target, current)
            self.visit(current.value)

        def visit_For(self, current):  # noqa: N802 - ast visitor API
            bind(current.target, current)
            self.generic_visit(current)

        visit_AsyncFor = visit_For

        def visit_With(self, current):  # noqa: N802 - ast visitor API
            for item in current.items:
                bind(item.optional_vars, current)
            self.generic_visit(current)

        visit_AsyncWith = visit_With

        def visit_ExceptHandler(self, current):  # noqa: N802 - ast visitor API
            if current.name:
                write(current.name, current)
            self.generic_visit(current)

        def visit_Delete(self, current):  # noqa: N802 - ast visitor API
            for target in current.targets:
                bind(target, current)

        def visit_Name(self, current):  # noqa: N802 - ast visitor API
            if isinstance(current.ctx, ast.Load):
                loads.setdefault(current.id, []).append(position(current))

    Visitor(node).visit(node)

    def reaches_use(local: str, imported_at: Position) -> bool:
        later_writes = [
            written_at
            for written_at in writes.get(local, ())
            if written_at > imported_at
        ]
        if local in external_used and not later_writes:
            return True
        return any(
            loaded_at > imported_at
            and not any(imported_at < written_at < loaded_at for written_at in later_writes)
            for loaded_at in loads.get(local, ())
        )

    return {
        target
        for local, targets, imported_at in bindings
        if reaches_use(local, imported_at)
        for target in targets
    }


def _scope_global_loads(scope: ast.AST) -> set[str]:
    """Names a function reads from module scope, excluding local bindings."""

    class Names(ast.NodeVisitor):
        def __init__(self):
            self.loads: set[str] = set()
            self.locals: set[str] = set()
            self.globals: set[str] = set()

        def visit_FunctionDef(self, current):  # noqa: N802
            if current is scope:
                self.generic_visit(current)
            else:
                self.locals.add(current.name)

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_ClassDef(self, current):  # noqa: N802
            if current is scope:
                self.generic_visit(current)
            else:
                self.locals.add(current.name)

        def visit_Global(self, current):  # noqa: N802
            self.globals.update(current.names)

        def visit_Nonlocal(self, current):  # noqa: N802
            self.locals.update(current.names)

        def visit_arg(self, current):  # noqa: N802
            self.locals.add(current.arg)

        def visit_Import(self, current):  # noqa: N802
            self.locals.update(
                alias.asname or alias.name.split(".", 1)[0]
                for alias in current.names
            )

        def visit_ImportFrom(self, current):  # noqa: N802
            self.locals.update(
                alias.asname or alias.name
                for alias in current.names
                if alias.name != "*"
            )

        def visit_Name(self, current):  # noqa: N802
            if isinstance(current.ctx, ast.Load):
                self.loads.add(current.id)
            else:
                self.locals.add(current.id)

    names = Names()
    names.visit(scope)
    return names.loads - (names.locals - names.globals)


def _fixture_decorator(node: ast.AST) -> ast.AST | None:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return None
    return next(
        (
            decorator
            for decorator in node.decorator_list
            if _dotted(decorator.func if isinstance(decorator, ast.Call) else decorator)
            in ("pytest.fixture", "fixture")
        ),
        None,
    )


def _fixture_bindings(data: bytes | None, *, package: str = "") -> dict[str, _FixtureBinding]:
    """Top-level fixtures and only the imports their bodies actually use."""

    if not data:
        return {}
    try:
        tree = ast.parse(_decode(data))
    except (SyntaxError, ValueError):
        return {}
    module = ast.Module(body=list(tree.body), type_ignores=[])
    out: dict[str, _FixtureBinding] = {}
    for node in tree.body:
        decorator = _fixture_decorator(node)
        if decorator is None:
            continue
        assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        name = node.name
        autouse = False
        if isinstance(decorator, ast.Call):
            for keyword in decorator.keywords:
                if (
                    keyword.arg == "name"
                    and isinstance(keyword.value, ast.Constant)
                    and isinstance(keyword.value.value, str)
                ):
                    name = keyword.value.value
                elif (
                    keyword.arg == "autouse"
                    and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value is True
                ):
                    autouse = True
        imports = _import_targets(node, package=package) | _import_targets(
            module, _scope_global_loads(node), package=package
        )
        dependencies = {
            argument.arg
            for argument in (
                node.args.posonlyargs + node.args.args + node.args.kwonlyargs
            )
            if argument.arg not in ("self", "cls")
        }
        out[name] = _FixtureBinding(
            imports=frozenset(imports),
            dependencies=frozenset(dependencies),
            autouse=autouse,
        )
    return out


def _pytest_mark_aliases(tree: ast.Module) -> tuple[set[str], set[str]]:
    """Local names that provably denote ``pytest`` or ``pytest.mark``."""

    pytest_names: set[str] = set()
    mark_names: set[str] = set()
    for stmt in tree.body:
        if isinstance(stmt, ast.Import):
            for alias in stmt.names:
                if alias.name == "pytest":
                    pytest_names.add(alias.asname or "pytest")
        elif isinstance(stmt, ast.ImportFrom) and stmt.level == 0 and stmt.module == "pytest":
            for alias in stmt.names:
                if alias.name == "mark":
                    mark_names.add(alias.asname or "mark")
    return pytest_names, mark_names


def _pytest_mark_kind(
    decorator: ast.AST,
    aliases: tuple[set[str], set[str]],
) -> str | None:
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    dotted = _dotted(target)
    pytest_names, mark_names = aliases
    for name in pytest_names:
        prefix = f"{name}.mark."
        if dotted.startswith(prefix):
            return dotted[len(prefix) :]
    for name in mark_names:
        prefix = f"{name}."
        if dotted.startswith(prefix):
            return dotted[len(prefix) :]
    return None


def _parametrized_values(
    node: ast.AST,
    aliases: tuple[set[str], set[str]] | None = None,
) -> set[str]:
    """Arguments supplied directly by parametrize rather than by fixtures."""

    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return set()
    direct: set[str] = set()
    aliases = aliases or ({"pytest"}, {"mark"})
    for decorator in node.decorator_list:
        if not (
            isinstance(decorator, ast.Call)
            and _pytest_mark_kind(decorator, aliases) == "parametrize"
            and decorator.args
        ):
            continue
        names_node = decorator.args[0]
        if isinstance(names_node, ast.Constant) and isinstance(names_node.value, str):
            names = {name.strip() for name in names_node.value.split(",") if name.strip()}
        elif isinstance(names_node, (ast.List, ast.Tuple)):
            names = {
                item.value
                for item in names_node.elts
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            }
        else:
            continue
        all_indirect = False
        indirect: set[str] = set()
        for keyword in decorator.keywords:
            if keyword.arg != "indirect":
                continue
            if isinstance(keyword.value, ast.Constant) and keyword.value.value is True:
                all_indirect = True
            elif isinstance(keyword.value, (ast.List, ast.Tuple, ast.Set)):
                indirect = {
                    item.value
                    for item in keyword.value.elts
                    if isinstance(item, ast.Constant) and isinstance(item.value, str)
                }
            else:
                # Dynamic indirectness cannot prove a fixture request.
                indirect = set()
        if all_indirect:
            continue
        direct.update(names - indirect)
    return direct


def _usefixtures_values(
    node: ast.AST,
    aliases: tuple[set[str], set[str]],
) -> set[str]:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return set()
    requested: set[str] = set()
    for decorator in node.decorator_list:
        if not (
            isinstance(decorator, ast.Call)
            and _pytest_mark_kind(decorator, aliases) == "usefixtures"
        ):
            continue
        requested.update(
            argument.value
            for argument in decorator.args
            if isinstance(argument, ast.Constant)
            and isinstance(argument.value, str)
        )
    return requested


def _test_fixture_requests(data: bytes | None) -> set[str]:
    if not data:
        return set()
    try:
        tree = ast.parse(_decode(data))
    except (SyntaxError, ValueError):
        return set()
    parser = _live_shadow_attr("parse_python", parse_python)
    parsed = parser(data, collect_tests=True)
    if not parsed.parse_ok:
        return set()
    aliases = _pytest_mark_aliases(tree)
    functions: dict[str, tuple[ast.AST, tuple[ast.ClassDef, ...]]] = {}

    def index(
        node: ast.AST,
        prefix: str = "",
        classes: tuple[ast.ClassDef, ...] = (),
    ) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions[f"{prefix}{child.name}"] = (child, classes)
                index(child, f"{prefix}{child.name}.", classes)
            elif isinstance(child, ast.ClassDef):
                index(child, f"{prefix}{child.name}.", (*classes, child))

    index(tree)
    requested: set[str] = set()
    for unit in parsed.units:
        indexed = functions.get(unit.qualname.split("#", 1)[0])
        if indexed is not None:
            node, classes = indexed
            decorated = (*classes, node)
            direct = set().union(
                *(_parametrized_values(item, aliases) for item in decorated)
            )
            requested.update(set(unit.side.params) - direct)
            requested.update(
                set().union(*(_usefixtures_values(item, aliases) for item in decorated))
            )
    return requested


def _active_fixture_imports(
    test_path: str,
    test_data: bytes | None,
    conftest_sources: Mapping[str, bytes | None],
    *,
    fixture_binding_reader: Callable[..., Mapping[str, _FixtureBinding]]
    | None = None,
    test_fixture_requests: Iterable[str] | None = None,
    paths: Iterable[str] = (),
) -> set[str]:
    """Imports reached through requested/autouse fixtures visible to one test."""

    binding_reader = fixture_binding_reader or _live_shadow_attr(
        "_fixture_bindings", _fixture_bindings
    )
    paths = frozenset(paths)
    definitions: dict[str, _FixtureBinding] = {}
    autouse: set[str] = set()
    for path in sorted(conftest_sources, key=lambda item: (item.count("/"), item)):
        if not _scope_applies(path.rpartition("/")[0], test_path):
            continue
        bindings = binding_reader(
            conftest_sources[path], package=_source_package(path, paths)
        )
        autouse.update(name for name, binding in bindings.items() if binding.autouse)
        definitions.update(bindings)
    # A test-module fixture is the closest definition and therefore overrides
    # a same-named fixture from any ancestor conftest.
    local = binding_reader(test_data, package=_source_package(test_path, paths))
    autouse.update(name for name, binding in local.items() if binding.autouse)
    definitions.update(local)

    if test_fixture_requests is None:
        request_reader = _live_shadow_attr("_test_fixture_requests", _test_fixture_requests)
        requested = request_reader(test_data)
    else:
        requested = set(test_fixture_requests)
    pending = list(requested | autouse)
    active: set[str] = set()
    imports: set[str] = set()
    while pending:
        name = pending.pop()
        if name in active:
            continue
        active.add(name)
        binding = definitions.get(name)
        if binding is None:
            continue
        imports.update(binding.imports)
        pending.extend(binding.dependencies - active)
    return imports


def _active_test_imports(
    data: bytes | None,
    *,
    test_fixture_requests: Iterable[str] | None = None,
    package: str = "",
) -> set[str]:
    """Imports executed by a collected test, fixture or called helper."""

    if not data:
        return set()
    try:
        tree = ast.parse(_decode(data))
    except (SyntaxError, ValueError):
        return set()
    parser = _live_shadow_attr("parse_python", parse_python)
    parsed = parser(data, collect_tests=True)
    if not parsed.parse_ok:
        return set()

    functions: dict[str, ast.AST] = {}

    def index(node: ast.AST, prefix: str = "") -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions[f"{prefix}{child.name}"] = child
                index(child, f"{prefix}{child.name}.")
            elif isinstance(child, ast.ClassDef):
                index(child, f"{prefix}{child.name}.")

    index(tree)
    top_level = {
        stmt.name: stmt
        for stmt in tree.body
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    active_scopes: list[ast.AST] = []
    for unit in parsed.units:
        qual = unit.qualname.split("#", 1)[0]
        node = functions.get(qual)
        if node is not None:
            active_scopes.append(node)
        for name in unit.side.invoked:
            # A parameter-local call is either a requested fixture (handled
            # below) or a direct parametrized value; it cannot resolve to a
            # same-named top-level helper/fixture by lexical name.
            if name in unit.side.params:
                continue
            helper = top_level.get(name)
            if helper is not None:
                active_scopes.append(helper)
    if test_fixture_requests is None:
        request_reader = _live_shadow_attr("_test_fixture_requests", _test_fixture_requests)
        requested = request_reader(data)
    else:
        requested = set(test_fixture_requests)
    for name in requested | set(parsed.autouse_fixtures):
        fixture = top_level.get(name)
        if fixture is not None:
            active_scopes.append(fixture)

    # Module imports execute before collection, but an unused import is not
    # enough to call the imported module the assertion's subject.  Its local
    # binding must be consumed by one of the live scopes above.  Scope-local
    # imports apply the same rule within that scope.
    synthetic_module = ast.Module(body=list(tree.body), type_ignores=[])
    used_by_live_scope: set[str] = set()
    for scope in active_scopes:
        used_by_live_scope.update(_scope_global_loads(scope))

    active = _import_targets(synthetic_module, used_by_live_scope, package=package)
    for scope in active_scopes:
        active |= _import_targets(scope, package=package)
    return active


class _ShadowAnalysisCache:
    """Revision-local memoisation keyed by immutable source content.

    A detector call describes exactly one before/head pair.  Keeping this
    cache local to that call avoids stale path-only answers across commits,
    while sharing unchanged bytes between sides and between tests that use
    the same conftest or provider chain.
    """

    def __init__(self) -> None:
        self._source_keys: dict[bytes | None, tuple[str, str] | None] = {}
        self._fixture_bindings: dict[
            tuple[bytes | None, str], Mapping[str, _FixtureBinding]
        ] = {}
        self._fixture_requests: dict[bytes | None, frozenset[str]] = {}
        self._test_imports: dict[tuple[bytes | None, str], frozenset[str]] = {}
        self._fixture_imports: dict[tuple, frozenset[str]] = {}
        self._provider_keys: dict[
            tuple[
                str,
                tuple[str, str],
                frozenset[str],
                tuple[tuple[str, bytes | None], ...],
            ],
            tuple[tuple[str, str], ...] | None,
        ] = {}

    def source_key(self, data: bytes | None) -> tuple[str, str] | None:
        if data not in self._source_keys:
            keyer = _live_shadow_attr("_source_key", _source_key)
            self._source_keys[data] = keyer(data)
        return self._source_keys[data]

    def fixture_bindings(
        self, data: bytes | None, *, package: str = ""
    ) -> Mapping[str, _FixtureBinding]:
        key = (data, package)
        if key not in self._fixture_bindings:
            reader = _live_shadow_attr("_fixture_bindings", _fixture_bindings)
            self._fixture_bindings[key] = MappingProxyType(
                reader(data, package=package)
            )
        return self._fixture_bindings[key]

    def fixture_requests(self, data: bytes | None) -> frozenset[str]:
        if data not in self._fixture_requests:
            reader = _live_shadow_attr("_test_fixture_requests", _test_fixture_requests)
            self._fixture_requests[data] = frozenset(reader(data))
        return self._fixture_requests[data]

    def active_test_imports(self, data: bytes | None, *, package: str = "") -> frozenset[str]:
        key = (data, package)
        if key not in self._test_imports:
            reader = _live_shadow_attr("_active_test_imports", _active_test_imports)
            self._test_imports[key] = frozenset(
                reader(
                    data,
                    test_fixture_requests=self.fixture_requests(data),
                    package=package,
                )
            )
        return self._test_imports[key]

    def active_fixture_imports(
        self,
        test_path: str,
        test_data: bytes | None,
        conftest_sources: Mapping[str, bytes | None],
        paths: Iterable[str] = (),
    ) -> frozenset[str]:
        conftest_key = tuple(sorted(conftest_sources.items()))
        packages = tuple(
            (path, _source_package(path, paths))
            for path in (test_path, *sorted(conftest_sources))
        )
        key = (test_path, test_data, conftest_key, packages)
        if key not in self._fixture_imports:
            reader = _live_shadow_attr("_active_fixture_imports", _active_fixture_imports)
            self._fixture_imports[key] = frozenset(
                reader(
                    test_path,
                    test_data,
                    conftest_sources,
                    fixture_binding_reader=self.fixture_bindings,
                    test_fixture_requests=self.fixture_requests(test_data),
                    paths=paths,
                )
            )
        return self._fixture_imports[key]

    def provider_execution_key(
        self,
        module: str,
        selected: tuple[str, str],
        paths: Iterable[str],
        contents: Mapping[str, bytes | None],
    ) -> tuple[tuple[str, str], ...] | None:
        path_set = frozenset(paths)
        root, provider = selected
        executed = (*_provider_package_chain(module, root, path_set), provider)
        content_key = tuple((path, contents.get(path)) for path in executed)
        key = (module, selected, path_set, content_key)
        if key not in self._provider_keys:
            keyer = _live_shadow_attr("_provider_execution_key", _provider_execution_key)
            self._provider_keys[key] = keyer(
                module,
                selected,
                path_set,
                contents,
                source_keyer=self.source_key,
            )
        return self._provider_keys[key]


def _match_active_test_imports(
    test_paths: Sequence[str],
    conftest_paths: Sequence[str],
    before_paths: set[str],
    after_paths: set[str],
    change_by_path: Mapping[str, FileChange],
    side_change_by_path: Mapping[str, FileChange],
    snapshot: Mapping[str, bytes | None],
    modules: set[str],
    analysis: _ShadowAnalysisCache,
) -> tuple[dict[str, set[str]], set[str]]:
    """Return per-test surviving module imports and their union across both sides."""

    before_conftests = {
        path: _side_source(path, "before", side_change_by_path, snapshot)
        for path in conftest_paths
        if path in before_paths
    }
    after_conftests = {
        path: _side_source(path, "after", side_change_by_path, snapshot)
        for path in conftest_paths
        if path in after_paths
    }
    imported_by_test: dict[str, set[str]] = {}
    active_modules: set[str] = set()
    for test_path in test_paths:
        after_source = _side_source(test_path, "after", change_by_path, snapshot)
        before_source = _side_source(test_path, "before", side_change_by_path, snapshot)
        imported = (
            (
                analysis.active_test_imports(
                    before_source, package=_source_package(test_path, before_paths)
                )
                | analysis.active_fixture_imports(
                    test_path, before_source, before_conftests, before_paths
                )
            )
            & (
                analysis.active_test_imports(
                    after_source, package=_source_package(test_path, after_paths)
                )
                | analysis.active_fixture_imports(
                    test_path, after_source, after_conftests, after_paths
                )
            )
            & modules
        )
        if imported:
            imported_by_test[test_path] = imported
            active_modules.update(imported)
    return imported_by_test, active_modules

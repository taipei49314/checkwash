"""Stage helpers for parsing one Python file (`_parse_python`)."""

from __future__ import annotations

import ast
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field, replace
from types import ModuleType, SimpleNamespace
from typing import Any

from checkwash.ir.model import Assertion, Marker


@dataclass(slots=True)
class ModuleScanResult:
    """Module-wide imports, literals, suppressions, and broad/swallowing/relay handlers."""

    imports: list[str]
    suppressions: list[str]
    literals: frozenset[str]
    broad_handlers: tuple[str, ...]
    swallowing_handlers: tuple[str, ...]
    relay_handlers: tuple[str, ...]


@dataclass(slots=True)
class ModuleParseState:
    """Per-file collection state and lazy class/setup/fixture resolvers."""

    fe: ModuleType
    raw: str
    tree: ast.Module
    off: Any
    doctests: list[Assertion]
    collect_tests: bool
    conftest: bool
    chain: tuple[Any, ...]
    want_symbols: bool
    module_aliases: dict[str, list[ast.expr]]
    module_markers: list[Marker]
    module_scopes: dict[str, ast.AST]
    test_class_names: frozenset[str]
    file_caches: tuple[dict, dict]
    branch_fixtures: dict[str, ast.Constant]
    setup_scopes: tuple[Any, ...]
    marker_origins: dict[tuple[str, tuple[int, int], str], str]
    body_names: dict[str, str | None]
    body_roots: frozenset[str]
    condition: Callable[[ast.AST], str]
    helper_outcomes: Any
    class_attrs: Any
    units: list[Any] = field(default_factory=list)
    symbols: dict[str, str] = field(default_factory=dict)
    symbol_calls: dict[str, tuple[str, ...]] = field(default_factory=dict)
    class_setup: dict[tuple[int, int], Any] = field(default_factory=dict)
    methods_built: list[Any] = field(default_factory=list)
    instances: dict[int, Any] = field(default_factory=dict)
    resolved_methods: dict[str, ast.AST] = field(default_factory=dict)
    producer_scopes: dict[int, Any] = field(default_factory=dict)
    own_marks: list[Any] = field(default_factory=list)
    class_aliases: dict[int, dict[str, list[ast.expr]]] = field(default_factory=dict)
    rebound: dict[int, Any] = field(default_factory=dict)

    def attrs_of(self, cls: ast.ClassDef | None) -> Any:
        return self.class_attrs.env(cls) if self.class_attrs is not None and cls is not None else None

    def methods_of(self) -> Any:
        if not self.methods_built:
            self.methods_built.append(self.fe.Methods(self.tree))
        return self.methods_built[0]

    def instance_of(self, cls: ast.ClassDef | None) -> Any:
        if cls is None or not self.collect_tests or self.conftest:
            return None
        if id(cls) not in self.instances:
            self.instances[id(cls)] = self.fe._Instance(self.methods_of, cls)
        return self.instances[id(cls)]

    def aliases_of(self, cls: ast.ClassDef) -> dict[str, list[ast.expr]]:
        if id(cls) not in self.class_aliases:
            self.class_aliases[id(cls)] = self.fe._mark_aliases(cls.body, self.module_aliases)
        return self.class_aliases[id(cls)]

    def class_marks(self, cls: ast.ClassDef) -> list[Marker]:
        """A class's decorators and its body's `pytestmark` (#260 Q1)."""
        return self.fe._decorator_markers(cls, self.off, self.off, self.module_aliases) + self.fe._pytestmark_markers(
            cls.body, self.off, self.off, self.aliases_of(cls)
        )


def extend_nested_setup(
    state: ModuleParseState,
    scopes: tuple[Any, ...],
    *classes: ast.ClassDef,
    instance: ast.ClassDef | None = None,
) -> tuple[Any, ...]:
    """`scopes` extended by these class bodies, innermost last.

    `instance` is the class whose instance runs the setup, when it is not
    the class that defines it: its class attributes are the ones a guard
    reads (#254), and its methods are the ones a setup callback's calls
    through `self` run (#306).
    """
    if not scopes:
        return scopes
    for cls in classes:
        owner = instance if instance is not None else cls
        key = (id(cls), id(owner))
        if key not in state.class_setup:
            running = state.instance_of(owner)
            state.class_setup[key] = state.fe.SetupScope(
                cls.body,
                scopes[0].bindings,
                in_class=True,
                marks=cls.decorator_list,
                bases=cls.bases,
                condition=state.condition,
                attrs=state.attrs_of(owner),
                helpers=state.helper_outcomes,
                methods=(id(owner), running.follow) if running is not None else None,
            )
        scopes = scopes + (state.class_setup[key],)
    return scopes


def unit_fixture_producers(
    state: ModuleParseState,
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    classes: tuple[ast.ClassDef, ...],
) -> tuple:
    """Resolve parameter fixture producers visible to `func` across module and class scopes."""
    if not state.collect_tests or state.conftest:
        return ()
    args = func.args
    if not (args.posonlyargs or args.args or args.kwonlyargs):
        return ()
    fe = state.fe
    module_scope = state.producer_scopes.get(id(state.tree))
    if module_scope is None:
        module_scope = state.producer_scopes[id(state.tree)] = fe.ProducerScope(
            state.tree.body, fe.module_bindings(state.tree), fe.import_modules(state.tree)
        )
    scopes = [module_scope]
    for cls in classes:
        scope = state.producer_scopes.get(id(cls))
        if scope is None:
            scope = state.producer_scopes[id(cls)] = fe.ProducerScope(
                cls.body,
                module_scope.bindings,
                module_scope.modules,
                in_class=True,
                marks=cls.decorator_list,
                bases=cls.bases,
                keywords=cls.keywords,
            )
        scopes.append(scope)
    return fe.unit_producers(scopes, func, method=bool(classes), chain=state.chain)


def parse_and_normalize_module(
    fe: ModuleType, data: bytes, collect_tests: bool
) -> tuple[str, ast.Module, Any, list[Assertion]] | None:
    """Decode, parse, extract doctest examples, and normalize `tree` in place."""
    raw = fe.normalize_source(data)
    try:
        tree = fe.parse_module(raw)
        if collect_tests and "if" in raw and ("assert" in raw or "raise" in raw and "AssertionError" in raw):
            tree = fe.conditional_oracle_carriers(tree)
    except SyntaxError:
        return None
    except (RecursionError, ValueError, MemoryError):
        # Deeply nested expressions raise RecursionError, not SyntaxError.
        # Head-side content is attacker-controlled: degrade visibly instead
        # of crashing the process (confirmed red-team finding).
        return None

    # One parse, one in-place normalisation: symbol fingerprints are dumped
    # straight from subtrees instead of re-running unparse+parse per symbol,
    # and the fingerprint ignores what cannot change behaviour (annotations,
    # noise statements, dead literal bindings) so a cosmetic prod edit buys
    # no repair evidence. Test files never fingerprint symbols, so they skip
    # the pass entirely — collection semantics never see a mutated tree.
    off = fe._Offsets(raw)
    off.tree = tree
    doctests = fe.module_examples(tree, off) if collect_tests and ">>>" in raw and "doctest" in raw else []
    fe._strip_docstrings(tree)
    if not collect_tests:
        fe._normalize_for_fingerprint(tree)
    return raw, tree, off, doctests


def build_module_parse_state(
    fe: ModuleType,
    raw: str,
    tree: ast.Module,
    off: Any,
    doctests: list[Assertion],
    *,
    collect_tests: bool,
    conftest: bool,
    chain: tuple[Any, ...],
    imported: Any,
) -> ModuleParseState:
    """Prepare module-level scopes, marks, setup scopes and class attribute caches."""
    # Symbol fingerprints exist to answer "did prod behaviour change?"; test
    # files never need them, and computing them dominated parse time.
    want_symbols = not collect_tests
    module_aliases = fe._mark_aliases(tree.body) if collect_tests else {}
    module_markers = (
        fe._pytestmark_markers(tree.body, off, off, module_aliases) + fe._module_skip_markers(tree, off, off)
        if collect_tests
        else []
    )
    # Callables a unit can reach without leaving the file. Computed once per
    # module, not per unit: a suite with 200 tests and 5 helpers would otherwise
    # rebuild the same map 200 times.
    module_scopes: dict[str, ast.AST] = {}
    test_class_names: frozenset[str] = frozenset()
    if collect_tests:
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                module_scopes[node.name] = node
            elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Lambda):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        module_scopes[target.id] = node.value
        test_class_names = fe._transitive_test_classes(tree)
    # One file's worth of scope-walk memoisation: (scope-nodes, invocations),
    # shared by every unit so a helper reached by many tests is walked once.
    file_caches: tuple[dict, dict] = ({}, {})
    branch_fixtures = fe.literal_fixtures(tree) if collect_tests else {}

    setup_scopes: tuple[Any, ...] = ()
    marker_origins: dict[tuple[str, tuple[int, int], str], str] = {}
    # What a test body's names resolve to at module level, for its skips (#220).
    body_names = fe.module_bindings(tree, mutated=False) if collect_tests and not conftest else {}
    # Names a test can import inside itself, read when an import is indented.
    body_roots = (
        frozenset(
            name
            for node in fe._walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for name, _target in (fe._import_pairs(node) or ())
        )
        if body_names and fe._NESTED_IMPORT.search(raw)
        else frozenset()
    )

    def condition(node: ast.AST) -> str:
        return off.seg(node) or ast.unparse(node)

    imported_helpers = (
        fe.ImportedHelpers(fe.imported_helper_names(tree), imported)
        if imported is not None and collect_tests and not conftest
        else None
    )
    if imported_helpers is not None and not imported_helpers.names:
        imported_helpers = None
    spells_outcome = any(token in raw for token in fe._SETUP_OUTCOME_TOKENS)
    helper_outcomes = (
        fe.HelperOutcomes(module_scopes, condition, branch_fixtures, imported_helpers)
        if collect_tests and not conftest and (spells_outcome or imported_helpers is not None)
        else None
    )
    if collect_tests and not conftest and (
        spells_outcome
        or imported_helpers is not None
        or any(fixture[2] is not None for level in chain for fixture in level.fixtures.values())
    ):
        setup_scopes = (
            fe.SetupScope(tree.body, fe.module_bindings(tree), condition=condition, helpers=helper_outcomes),
        )
    class_attrs = (
        fe.ClassAttributes(tree)
        if collect_tests and not conftest and any(isinstance(node, ast.ClassDef) for node in tree.body)
        else None
    )

    return ModuleParseState(
        fe=fe,
        raw=raw,
        tree=tree,
        off=off,
        doctests=doctests,
        collect_tests=collect_tests,
        conftest=conftest,
        chain=chain,
        want_symbols=want_symbols,
        module_aliases=module_aliases,
        module_markers=module_markers,
        module_scopes=module_scopes,
        test_class_names=test_class_names,
        file_caches=file_caches,
        branch_fixtures=branch_fixtures,
        setup_scopes=setup_scopes,
        marker_origins=marker_origins,
        body_names=body_names,
        body_roots=body_roots,
        condition=condition,
        helper_outcomes=helper_outcomes,
        class_attrs=class_attrs,
    )


def compute_rebound_statuses(state: ModuleParseState) -> None:
    """Compute final name rebinding and dead-definition statuses (#424, #499)."""
    if not state.collect_tests or state.conftest:
        return
    fe = state.fe
    off = state.off
    state.rebound = fe.final_bindings(
        state.tree,
        fe._BindingReader(
            condition=state.condition,
            truth=fe._static_truth,
            handler_guard=fe._handler_guard,
            match_dead=fe._match_is_dead,
            never_iterates=lambda stmt: fe._is_literal(stmt.iter) and not fe._truthy_literal(stmt.iter),
            marks=lambda decorators, cls: fe._decorator_markers(
                SimpleNamespace(decorator_list=list(decorators)),
                off,
                off,
                state.aliases_of(cls) if cls is not None else state.module_aliases,
            ),
            cite=lambda node: ((off.seg(node) or "").split("\n")[0], off.span(node)),
            collectible_class=lambda cls: (
                (fe._is_test_class(cls) or cls.name in state.test_class_names)
                and not fe._test_attr_disabled(cls.body)
            ),
        ),
        expressions=any(token in state.raw for token in fe._EXPRESSION_BINDING_TOKENS),
    )


def credit_abstract_base_unit(
    state: ModuleParseState,
    unit: Any,
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    cls: ast.ClassDef,
) -> Any:
    """Ruling 254.Q2: credit an abstract base's test when a same-file subclass runs it."""
    fe = state.fe
    markers = unit.side.markers
    if state.class_attrs is None or not markers or any(
        not (m.name in fe.BODY_MARKERS or m.name.startswith(("setup.", "helper."))) or m.guard is not None
        for m in markers
    ):
        return unit
    helper_marked = any(m.name.startswith("helper.") for m in markers)
    local = fe.body_bindings(func, state.body_names, method=True)
    skips = {
        id(node)
        for node in fe._walk(func)
        if isinstance(node, (ast.Call, ast.Raise)) and fe.body_outcome(node, local) is not None
    }
    for subclass in state.class_attrs.crediting_subclasses(cls, func.name):
        dead = fe._unreachable_ids(
            func, state.branch_fixtures, lambda stmt: id(stmt) in skips, state.attrs_of(subclass)
        )
        if any(node not in dead for node in skips):
            continue
        if fe.setup_markers(state, func, extend_nested_setup(state, state.setup_scopes, cls, instance=subclass), (subclass,)):
            continue
        if helper_marked and state.helper_outcomes is not None:
            calls = [node for node in fe._walk(func) if isinstance(node, ast.Call) and id(node) not in dead]
            scopes_seen = fe._local_scopes(func, state.module_scopes)
            plain = [
                node
                for node in calls
                if isinstance(node.func, ast.Name)
                and (
                    node.func.id in scopes_seen
                    or state.helper_outcomes.imported is not None
                    and node.func.id in state.helper_outcomes.imported
                )
            ]
            if plain and state.helper_outcomes.reached(
                func, state.body_names, plain, method=True, local_scopes=scopes_seen
            ):
                continue
            running = state.instance_of(subclass)
            if running is not None and state.helper_outcomes.method_calls(
                func,
                state.body_names,
                id(subclass),
                attrs=state.attrs_of(subclass),
                follow=running.follow,
                calls=[node for node in calls if isinstance(node.func, ast.Attribute)],
            ):
                continue
        return fe.ParsedUnit(
            qualname=unit.qualname,
            span=unit.span,
            side=replace(unit.side, markers=[]),
            shingles=unit.shingles,
        )
    return unit


def visit_module_scopes(state: ModuleParseState) -> None:
    """Iterative preorder visitation collecting symbol fingerprints and lexical test units."""
    fe = state.fe
    off = state.off
    frames: list[tuple[
        Iterator[ast.AST], str, list[Marker], bool,
        tuple[Any, ...], dict[str, list[ast.expr]] | None,
        ast.ClassDef | None, tuple[ast.ClassDef, ...],
    ]] = [(
        ast.iter_child_nodes(state.tree),
        "",
        state.module_markers,
        True,
        state.setup_scopes,
        state.module_aliases,
        None,
        (),
    )]
    while frames:
        children, prefix, inherited, collectible, scopes, aliases, owner, classes = frames[-1]
        child = next(children, None)
        if child is None:
            frames.pop()
            continue
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            qual = f"{prefix}{child.name}"
            if state.want_symbols:
                state.symbols[qual] = fe._fingerprint(child)
                state.symbol_calls[qual] = fe._callees(child)
            bound = state.rebound.get(id(child))
            if state.collect_tests and collectible and fe._is_test_name(child.name) and not (bound and bound.dropped):
                unit = fe._collect_unit(
                    child,
                    qual,
                    off,
                    off,
                    inherited + (bound.markers if bound else []) + fe.setup_markers(state, child, scopes, classes),
                    state.module_scopes,
                    state.file_caches,
                    state.branch_fixtures,
                    state.doctests,
                    aliases,
                    outcome_bindings=state.body_names,
                    method="." in qual,
                    outcome_roots=state.body_roots,
                    attrs=state.attrs_of(owner),
                    helpers=state.helper_outcomes,
                    origins=state.marker_origins,
                    instance=state.instance_of(owner if owner is not None else classes[-1]) if classes else None,
                    resolved=state.resolved_methods,
                    producers=unit_fixture_producers(state, child, classes),
                )
                state.units.append(credit_abstract_base_unit(state, unit, child, owner) if owner is not None else unit)
            # Nested defs are never collected as pytest items.
            frames.append((ast.iter_child_nodes(child), qual + ".", inherited, False, (), None, None, ()))
        elif isinstance(child, ast.ClassDef):
            qual = f"{prefix}{child.name}"
            if state.want_symbols:
                state.symbols[qual] = fe._fingerprint(child)
            class_markers = state.class_marks(child) if state.collect_tests else []
            bound = state.rebound.get(id(child))
            if bound is not None:
                class_markers = class_markers + bound.markers
            class_collectible = (
                collectible
                and (fe._is_test_class(child) or child.name in state.test_class_names)
                and not fe._test_attr_disabled(child.body)
                and not (bound and bound.dropped)
            )
            frames.append((
                ast.iter_child_nodes(child),
                qual + ".",
                inherited + class_markers,
                class_collectible,
                extend_nested_setup(state, scopes, child) if class_collectible else (),
                state.aliases_of(child) if state.collect_tests else None,
                child,
                classes + (child,),
            ))
        elif state.want_symbols and isinstance(child, (ast.Assign, ast.AnnAssign)):
            targets = child.targets if isinstance(child, ast.Assign) else [child.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    state.symbols[f"{prefix}{target.id}"] = fe._fingerprint(child)
        else:
            frames.append((ast.iter_child_nodes(child), prefix, inherited, collectible, scopes, aliases, None, classes))


def collect_inherited_and_suite_units(state: ModuleParseState) -> None:
    """Collect inherited test methods, apply conftest suite unit override, and disambiguate names."""
    fe = state.fe
    off = state.off
    if state.collect_tests:
        for cls, owner, method in fe.inherited_test_methods(state.tree):
            through = state.rebound.get(id(cls))
            if through is not None and through.gone:
                continue
            state.units.append(fe._collect_unit(
                method,
                f"{cls.name}.{method.name}",
                off,
                off,
                state.module_markers
                + state.class_marks(owner)
                + state.class_marks(cls)
                + (through.markers + through.rebound if through is not None else [])
                + fe.setup_markers(state, method, extend_nested_setup(state, state.setup_scopes, owner, cls, instance=cls), (cls,)),
                state.module_scopes,
                state.file_caches,
                state.branch_fixtures,
                state.doctests,
                state.aliases_of(owner),
                outcome_bindings=state.body_names,
                method=True,
                outcome_roots=state.body_roots,
                attrs=state.attrs_of(cls),
                helpers=state.helper_outcomes,
                origins=state.marker_origins,
                instance=state.instance_of(cls),
                resolved=state.resolved_methods,
                producers=unit_fixture_producers(state, method, (owner, cls)),
            ))
    if state.conftest:
        state.units = [fe._conftest_unit(state.tree, off, off)]

    seen_names: dict[str, int] = {}
    for unit in state.units:
        n = seen_names.get(unit.qualname, 0)
        seen_names[unit.qualname] = n + 1
        if n:
            unit.qualname = f"{unit.qualname}#{n + 1}"


def _collect_try_handlers(
    state: ModuleParseState,
    node: ast.Try | ast.TryStar,
    *,
    reads_relays: bool,
    testcase_of: Callable[[ast.ExceptHandler], Callable[[ast.Call], bool]],
    proven_relay: Callable[[ast.ExceptHandler, ast.AST], bool],
    broad: list[str],
    swallowing: list[str],
    relays: list[str],
) -> None:
    fe = state.fe
    guards_oracle = fe._contains_oracle(node.body)
    for handler in node.handlers:
        _caught, is_broad = fe._handler_info(handler)
        if not is_broad:
            continue
        seg = fe._norm((state.off.seg(handler) or "except:").split("\n")[0])
        broad.append(seg)
        if not guards_oracle:
            continue
        if fe._swallows(handler):
            swallowing.append(seg)
            if reads_relays and fe._relay_candidate(handler) and proven_relay(handler, node):
                relays.append(seg)
        elif not fe._raises_in(handler) and fe._proved_to_pass(handler, testcase_of(handler)):
            swallowing.append(seg + fe._ALWAYS_PASSING)


def scan_module_handlers_and_metadata(state: ModuleParseState) -> ModuleScanResult:
    """Scan module AST and lines for imports, literals, handlers, with-neutralisers, and suppressions."""
    fe = state.fe
    handler_scopes: list[dict[int, tuple[ast.ClassDef, ast.AST]]] = []

    def testcase_of(handler: ast.ExceptHandler) -> Callable[[ast.Call], bool]:
        def testcase(call: ast.Call) -> bool:
            if not handler_scopes:
                handler_scopes.append(fe._handler_methods(state.tree))
            scope = handler_scopes[0].get(id(handler))
            return scope is not None and fe._testcase_method(call, *scope, state.methods_of(), state.raw)

        return testcase

    relays: list[str] = []
    relay_readers: list[Any] = []
    reads_relays = state.collect_tests and not state.conftest

    def proven_relay(handler: ast.ExceptHandler, node: ast.AST) -> bool:
        try:
            if not relay_readers:
                relay_readers.append(None)
                relay_readers[0] = fe._RelayReader(
                    state.tree, state.off, [a.span for u in state.units for a in u.side.assertions]
                )
            reader = relay_readers[0]
            return reader is not None and reader.proven(handler, node)
        except RecursionError:
            return False

    imports: list[str] = []
    literals: set[str] = set()
    broad: list[str] = []
    swallowing: list[str] = []
    for node in fe._walk(state.tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            if not node.level:
                imports.append(node.module)
        elif isinstance(node, ast.Constant) and not isinstance(node.value, (bool, type(None))):
            rep = repr(node.value)
            if len(rep) <= 64:
                literals.add(rep)
        elif isinstance(node, (ast.Try, ast.TryStar)):
            _collect_try_handlers(
                state,
                node,
                reads_relays=reads_relays,
                testcase_of=testcase_of,
                proven_relay=proven_relay,
                broad=broad,
                swallowing=swallowing,
                relays=relays,
            )
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            neutralisers = [
                item.context_expr
                for item in node.items
                if fe._neutralizes_assertionerror(item.context_expr)
            ]
            if neutralisers and fe._wraps_bare_assert(node.body):
                for ctx in neutralisers:
                    seg = fe._norm((state.off.seg(ctx) or "").split("\n")[0])
                    broad.append(seg)
                    swallowing.append(seg)
    broad.sort()
    swallowing.sort()
    relays.sort()

    suppressions = [
        f"{i + 1}:{line.strip()}"
        for i, line in enumerate(state.raw.split("\n"))
        if fe._SUPPRESSION_RE.search(line)
    ]
    return ModuleScanResult(
        imports=imports,
        suppressions=suppressions,
        literals=frozenset(literals),
        broad_handlers=tuple(broad),
        swallowing_handlers=tuple(swallowing),
        relay_handlers=tuple(relays),
    )


def assemble_parsed_file(state: ModuleParseState, scan: ModuleScanResult) -> Any:
    """Sort units, extract module helper/fixture oracle scopes, and build `ParsedFile`."""
    fe = state.fe
    state.units.sort(key=lambda u: u.span)
    if state.collect_tests:
        helper_asserts, fixture_asserts, autouse = fe._module_oracle_scopes(state.tree, state.off, state.off)
        helper_calls = fe._module_helper_calls(state.tree)
        for via, method_node in sorted(state.resolved_methods.items()):
            helper_calls[via] = fe._callees(method_node)
    else:
        helper_asserts, fixture_asserts, autouse = {}, {}, ()
        helper_calls = {}
    return fe.ParsedFile(
        parse_ok=True,
        units=state.units,
        symbols=state.symbols,
        symbol_calls=state.symbol_calls,
        imports=sorted(set(scan.imports)),
        suppressions=scan.suppressions,
        literals=scan.literals,
        broad_handlers=scan.broad_handlers,
        swallowing_handlers=scan.swallowing_handlers,
        relay_handlers=scan.relay_handlers,
        constants=fe._top_level_constants(state.tree, state.off),
        from_imports=fe._top_level_from_imports(state.tree),
        fixture_defs=fe._fixture_definitions(state.tree) if state.collect_tests else {},
        helper_asserts=helper_asserts,
        helper_calls=helper_calls,
        fixture_asserts=fixture_asserts,
        autouse_fixtures=autouse,
        marker_origins=state.marker_origins,
    )

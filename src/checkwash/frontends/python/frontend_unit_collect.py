"""Stage helpers for collecting one Python test unit (`_collect_unit`)."""

from __future__ import annotations

import ast
import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any

from checkwash.ir import strength as S
from checkwash.ir.model import Assertion, Handler, Marker, UnitSide


@dataclass(slots=True)
class UnitCollectContext:
    """Per-unit collection state shared across `_collect_unit` pipeline stages."""

    fe: ModuleType
    func: ast.FunctionDef | ast.AsyncFunctionDef
    qualname: str
    text: Any
    off: Any
    module_scopes: dict[str, ast.AST]
    caches: tuple[dict, dict] | None
    nodes_cache: dict | None
    doctests: list[Assertion]
    module_names: dict[str, str | None]
    method: bool
    attrs: Any
    helpers: Any
    origins: dict | None
    instance: Any
    resolved: dict | None
    producers: tuple[tuple[str, str, tuple[str, ...]], ...]
    fixture_params: frozenset[str]
    markers: list[Marker]
    outcome_of: Callable[[ast.Call | ast.Raise], str | None]
    dead: set[int]
    guards: dict[int, str]
    definition_bindings: dict[str, str]
    bindings: dict[str, tuple[str, ...]]
    ordered_bindings: dict[str, list[tuple[int, str, tuple[str, ...]]]]
    vacuous: set[int]
    local_scopes: dict[str, ast.AST]
    reached_asserts: set[int]
    fixture_reads: Callable[[ast.AST, ast.AST], tuple[str, ...]]
    resolved_subject: Callable[[ast.AST, str | None], tuple[str, str] | None]
    assertions: list[Assertion] = field(default_factory=list)
    calls: set[str] = field(default_factory=set)
    patches: set[tuple[str, str]] = field(default_factory=set)
    handlers: list[Handler] = field(default_factory=list)
    own_assert_ids: set[int] = field(default_factory=set)
    outcome_nodes: list[ast.Call | ast.Raise] = field(default_factory=list)
    helper_calls: list[ast.Call] = field(default_factory=list)
    method_calls: list[ast.Call] = field(default_factory=list)
    receiver_names: frozenset[str] | None = None
    counter: int = 0


def _make_outcome_resolver(
    fe: ModuleType,
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    module_names: dict[str, str | None],
    outcome_roots: frozenset[str],
    *,
    method: bool,
) -> Callable[[ast.Call | ast.Raise], str | None]:
    # A body skip is read through the module's import bindings, shadowed by
    # the function's own, which are worked out only for a call or raise whose
    # root can spell one (#220).
    roots = fe._OUTCOME_ROOTS | outcome_roots | {name for name, target in module_names.items() if target}
    positional = [*func.args.posonlyargs, *func.args.args]
    if method and positional:
        # The instance, whatever it is called, spells `self.skipTest`.
        roots = roots | {positional[0].arg}
    local_names: dict[str, str | None] | None = None

    def outcome_of(node: ast.Call | ast.Raise) -> str | None:
        nonlocal local_names
        target = node.func if isinstance(node, ast.Call) else node.exc
        if isinstance(target, ast.Call):
            target = target.func
        name = fe._dotted(target) if target is not None else None
        if not name or name.partition(".")[0] not in roots:
            return None
        if local_names is None:
            local_names = fe.body_bindings(func, module_names, method=method)
        return fe.body_outcome(node, local_names)

    return outcome_of


def _make_fixture_reader(
    fe: ModuleType,
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    fixture_params: frozenset[str],
    bindings: dict[str, tuple[str, ...]],
    refs_memo: dict[int, tuple[str, ...]],
) -> Callable[[ast.AST, ast.AST], tuple[str, ...]]:
    """Build the lazy fixture-parameter reader for assertions in `func` (#471)."""
    nested_nodes: set[int] | None = None
    rebound: frozenset[str] = frozenset()
    followed: dict[str, tuple[str, ...]] = {}

    def fixture_reads(node: ast.AST, expression: ast.AST) -> tuple[str, ...]:
        """The fixture parameters assertion `node` of the unit's own body reads in `expression` (471 Q3).

        Directly, or through the unit's own assignments (`_resolve_through`):
        not one made inside a nested def, class or lambda, and less the names
        an assigned value binds in a lambda or comprehension of its own
        (`_fixture_read_bindings`, D-155 reading 3). A parameter the body binds
        again holds another value there, and is not counted: one the binding
        map records (`=`, augmented, annotated or walrus), and one bound any
        other way in the unit's own scope (`_fixture_binders`: a `for` or
        comprehension target, `with ... as`, `except ... as`, `del`, an
        import, `global` or `nonlocal`, a match capture, a nested def or class
        of that name). A name inside a lambda or a comprehension of the
        assertion that binds it is not read, nor followed (`assertion_names`);
        a parameter all of whose occurrences there are such names is not
        counted, even when a name the assertion reads leads to it, which errs
        toward no evidence.
        """
        nonlocal nested_nodes, rebound, followed
        if not fixture_params:
            return ()
        if nested_nodes is None:
            nested_nodes = {
                id(inner)
                for scope in fe._walk(func)
                if scope is not func
                and isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda))
                for inner in ast.walk(scope)
            }
            rebound = frozenset(param for param in fixture_params if fe._fixture_binders(func, param))
            followed = fe._fixture_read_bindings(func, nested_nodes, refs_memo)
        if id(node) in nested_nodes:
            return ()
        read, shadowed = fe.assertion_names(expression)
        return tuple(sorted(
            name for name in fe._resolve_through(tuple(sorted(read)), followed)
            if name in fixture_params and name not in bindings and name not in rebound and name not in shadowed
        ))

    return fixture_reads


def _make_subject_resolver(
    fe: ModuleType,
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    ordered_bindings: dict[str, list[tuple[int, str, tuple[str, ...]]]],
    nodes_cache: dict | None,
) -> Callable[[ast.AST, str | None], tuple[str, str] | None]:
    # The subject a bare local name stands for (#434), worked out per unit
    # only once an assertion checks a name the unit binds.
    plain_names: frozenset[str] | None = None
    own_scope: frozenset[int] | None = None

    def resolved_subject(node: ast.AST, left: str | None) -> tuple[str, str] | None:
        nonlocal plain_names, own_scope
        if not left or not left.isidentifier() or left not in ordered_bindings:
            return None
        if plain_names is None:
            plain_names = fe._plain_names(func, ordered_bindings)
            own_scope = frozenset(map(id, fe._scope_nodes_cached(func, nodes_cache)))
        if left not in plain_names or id(node) not in own_scope:
            return None
        return fe._resolved_subject(node, left, ordered_bindings)

    return resolved_subject


def prepare_unit_context(
    fe: ModuleType,
    *,
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    qualname: str,
    text: Any,
    off: Any,
    inherited_markers: list[Marker] | None,
    module_scopes: dict[str, ast.AST] | None,
    caches: tuple[dict, dict] | None,
    fixtures: dict[str, ast.Constant] | None,
    doctests: list[Assertion] | None,
    aliases: dict[str, list[ast.expr]] | None,
    outcome_bindings: dict[str, str | None] | None,
    method: bool,
    outcome_roots: frozenset[str],
    attrs: Any,
    helpers: Any,
    origins: dict | None,
    instance: Any,
    resolved: dict | None,
    producers: tuple[tuple[str, str, tuple[str, ...]], ...],
) -> UnitCollectContext:
    """Initialize bindings, reachability, outcome resolvers and caches for `func`."""
    markers = fe._decorator_markers(func, text, off, aliases) + list(inherited_markers or [])
    module_names = outcome_bindings or {}
    outcome_of = _make_outcome_resolver(fe, func, module_names, outcome_roots, method=method)
    dead = fe._unreachable_ids(func, fixtures, lambda stmt: outcome_of(stmt) is not None, attrs)
    guards = fe._skip_call_guards(func, text)

    unparse_memo: dict[int, str] = {}
    refs_memo: dict[int, tuple[str, ...]] = {}
    flags: dict[str, bool] = {}
    definition_bindings, bindings = fe._binding_maps(
        func, unparse_memo=unparse_memo, refs_memo=refs_memo, flags=flags
    )
    ordered_bindings = (
        fe._ordered_bindings(
            func,
            unparse_memo=unparse_memo,
            refs_memo=refs_memo,
            has_walrus=flags.get("walrus", False),
        )
        if definition_bindings
        else {}
    )
    vacuous = fe._vacuous_bound_asserts(func)
    fixture_params = frozenset(param for param, _callee, _modules in producers)
    fixture_reads = _make_fixture_reader(fe, func, fixture_params, bindings, refs_memo)

    # Markers, handlers, calls and patches stay keyed to the unit's own body: a
    # helper's assertions are this unit's oracle, a helper's `except` is not
    # this unit's handler. Only the assertion set follows reachability.
    nodes_cache = caches[0] if caches is not None else None
    scopes_map = module_scopes or {}
    # The callable map is stable for this unit; reuse it for the initial walk
    # and each helper entry instead of rediscovering the same nested scopes.
    local_scopes = fe._local_scopes(func, scopes_map)
    executed = fe._executed_scopes(func, scopes_map, caches=caches, local_scopes=local_scopes)
    reached_asserts = {
        id(n)
        for scope in executed
        for n in fe._scope_nodes_cached(scope, nodes_cache)
        if isinstance(n, ast.Assert)
    }
    resolved_subject = _make_subject_resolver(fe, func, ordered_bindings, nodes_cache)

    return UnitCollectContext(
        fe=fe,
        func=func,
        qualname=qualname,
        text=text,
        off=off,
        module_scopes=scopes_map,
        caches=caches,
        nodes_cache=nodes_cache,
        doctests=doctests or [],
        module_names=module_names,
        method=method,
        attrs=attrs,
        helpers=helpers,
        origins=origins,
        instance=instance,
        resolved=resolved,
        producers=producers,
        fixture_params=fixture_params,
        markers=markers,
        outcome_of=outcome_of,
        dead=dead,
        guards=guards,
        definition_bindings=definition_bindings,
        bindings=bindings,
        ordered_bindings=ordered_bindings,
        vacuous=vacuous,
        local_scopes=local_scopes,
        reached_asserts=reached_asserts,
        fixture_reads=fixture_reads,
        resolved_subject=resolved_subject,
    )


def _append_own_assertion(
    ctx: UnitCollectContext,
    node: ast.AST,
    c: Any,
    expression: ast.AST,
    *,
    trivial: bool,
) -> None:
    fe = ctx.fe
    seg = ctx.text.seg(node) or ""
    depends = fe._resolve_through(c.right_names, ctx.bindings)
    direct = set(c.left_names) | set(c.right_names)
    reach = fe._reaching_keys(
        node,
        fe._positional_closure(node, c.left_names + c.right_names, ctx.ordered_bindings),
        ctx.ordered_bindings,
    )
    ctx.assertions.append(
        Assertion(
            id=f"a{ctx.counter}",
            form=c.form,
            strength=c.strength,
            text=seg,
            span=ctx.off.span(node),
            left=c.left,
            right_literal=c.right_literal,
            right_value=c.right_value,
            epsilon=c.epsilon,
            epsilon_kind=c.epsilon_kind,
            predicate=c.predicate,
            operand_source=c.operand_source,
            unevaluated_expected=c.unevaluated_expected,
            unbound_operands=c.unbound_operands,
            trivial=trivial,
            positive=c.positive,
            left_names=c.left_names,
            right_depends_on=depends,
            reaching=reach,
            reaching_sig=fe._reaching_sig(reach, direct),
            resolved_subject=ctx.resolved_subject(node, c.left),
            fixture_reads=ctx.fixture_reads(node, expression) if ctx.fixture_params else (),
        )
    )
    ctx.counter += 1


def _collect_body_call(ctx: UnitCollectContext, node: ast.Call) -> None:
    fe = ctx.fe
    name = fe._dotted(node.func)
    if name:
        ctx.calls.add(name)
        ctx.calls.add(name.rsplit(".", 1)[-1])
        # Folded into this walk rather than given its own: a second full
        # `ast.walk` per unit put the 500-file budget over by 0.18 s, and the
        # dotted name is already computed here. Unreachable code is skipped
        # in `collect_body_statements`, which is right — a patch that never
        # executes installs nothing.
        pair = fe._patch_call_target(node, name, ctx.func, ctx.text)
        if pair is not None:
            ctx.patches.add(pair)
        if name in ("pytest.raises", "pytest.warns", "raises"):
            # `pytest.raises(E, match=...)` IS an oracle: triage found human
            # commits folding an excinfo substring assert into match= and
            # getting blocked for "removing" it.
            match_kw = next((kw for kw in node.keywords if kw.arg == "match"), None)
            seg = ctx.text.seg(node) or name
            ctx.assertions.append(
                Assertion(
                    id=f"a{ctx.counter}",
                    form="pattern" if match_kw is not None else "raises",
                    strength=S.PATTERN if match_kw is not None else None,
                    text=seg,
                    span=ctx.off.span(node),
                    right_literal=(
                        fe._literal_repr(match_kw.value, ctx.text) if match_kw is not None else None
                    ),
                )
            )
            ctx.counter += 1
    c = fe._classify_unittest_call(node, ctx.text) or fe._tolerance_statement_classified(node, ctx.text)
    if c is not None:
        _append_own_assertion(ctx, node, c, node, trivial=c.trivial)


def resolve_body_outcome_guard(ctx: UnitCollectContext, node: ast.AST) -> str | None:
    """Resolve the enclosing condition of a body skip/xfail under class attributes (#254)."""
    guard = ctx.guards.get(id(node))
    if guard is not None and ctx.attrs is not None:
        # A guard that holds under the class's attributes is no condition: the
        # skip reads as unconditional, as a setup callback's does (#254).
        fe = ctx.fe
        if ctx.receiver_names is None:
            ctx.receiver_names = fe.receivers(ctx.func)
        parsed = fe.parse_expr(guard)
        if parsed is not None and fe._static_truth(fe.substitute(parsed, ctx.attrs, ctx.receiver_names)) is True:
            return None
    return guard


def collect_body_statements(ctx: UnitCollectContext) -> None:
    """Single-pass AST walk collecting own assertions, outcome candidates, calls, patches and handlers."""
    fe = ctx.fe
    func = ctx.func
    helpers = ctx.helpers
    for node in fe._walk(func):
        if id(node) in ctx.dead:
            continue
        if (
            helpers is not None
            and isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and (node.func.id in ctx.local_scopes
                 or helpers.imported is not None and node.func.id in helpers.imported)
        ):
            ctx.helper_calls.append(node)
        if ctx.instance is not None and isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            ctx.method_calls.append(node)
        # Candidate native skip or xfail (`raise unittest.SkipTest` or `pytest.skip()`),
        # minted as `Marker(name=skip, ...)` in `_collect_unit` (#199 Q4, #220).
        if isinstance(node, (ast.Call, ast.Raise)):
            ctx.outcome_nodes.append(node)
        # An assert written inside a nested `def` that nothing calls is present
        # in the source and absent from the run. Counting it as live is what
        # let `verify()` be defined and never invoked (tamper 020) — and it is
        # older than that attack.
        if isinstance(node, ast.Assert) and id(node) not in ctx.reached_asserts:
            continue
        if isinstance(node, ast.Assert):
            ctx.own_assert_ids.add(id(node))
            c = fe._classify_assert(node, ctx.text)
            # A tolerance call (#222) judges its two values, as
            # `assertTrue(<call>)` and `assertAlmostEqual` do.
            trivial = fe._is_trivial_subject(node.test) or c.trivial or id(node) in ctx.vacuous
            _append_own_assertion(ctx, node, c, node.test, trivial=trivial)
        elif isinstance(node, ast.Call):
            _collect_body_call(ctx, node)
        elif isinstance(node, ast.ExceptHandler):
            caught, is_broad = fe._handler_info(node)
            seg = ctx.text.seg(node) or ""
            ctx.handlers.append(
                Handler(caught=caught, is_broad=is_broad, text=seg.split("\n")[0], span=ctx.off.span(node))
            )


def collect_helper_skip_markers(ctx: UnitCollectContext) -> None:
    """Append markers for skip/xfail outcomes reached via helper functions or instance methods."""
    fe = ctx.fe
    if ctx.helpers is not None and ctx.helper_calls:
        for helper, effect, evidence, guard in ctx.helpers.reached(
            ctx.func, ctx.module_names, ctx.helper_calls, method=ctx.method, local_scopes=ctx.local_scopes
        ):
            ctx.markers.append(fe._helper_marker(helper, effect, evidence, guard, ctx.text, ctx.off, ctx.origins))
    # A skip a helper method the unit calls through its instance ends in, read
    # under the running class's attributes (#306 Q1, Sub-Q5).
    if ctx.helpers is not None and ctx.instance is not None and ctx.method_calls:
        for helper, effect, evidence, guard in ctx.helpers.method_calls(
            ctx.func,
            ctx.module_names,
            id(ctx.instance.running),
            attrs=ctx.attrs,
            follow=ctx.instance.follow,
            calls=ctx.method_calls,
        ):
            ctx.markers.append(fe._helper_marker(helper, effect, evidence, guard, ctx.text, ctx.off, ctx.origins))


def _scope_inherited_rows(
    ctx: UnitCollectContext,
    scope: ast.AST,
    inherited_rows: dict[int, list[tuple[ast.AST, Any, bool]]],
) -> list[tuple[ast.AST, Any, bool]]:
    fe = ctx.fe
    rows = inherited_rows.get(id(scope))
    if rows is None:
        rows = []
        for node in fe._scope_nodes_cached(scope, ctx.nodes_cache):
            if isinstance(node, ast.Assert):
                if id(node) in ctx.own_assert_ids:
                    continue
                c = fe._classify_assert(node, ctx.text)
                trivial = fe._is_trivial_subject(node.test) or c.trivial or id(node) in ctx.vacuous
            elif isinstance(node, ast.Call):
                c = fe._classify_unittest_call(node, ctx.text) or fe._tolerance_statement_classified(node, ctx.text)
                if c is None:
                    continue
                trivial = c.trivial
            else:
                continue
            rows.append((node, c, trivial))
        inherited_rows[id(scope)] = rows
    return rows


def _append_inherited_assertions(
    ctx: UnitCollectContext,
    site_node: ast.AST,
    scope: ast.AST,
    inherited_rows: dict[int, list[tuple[ast.AST, Any, bool]]],
    via: str | None = None,
) -> None:
    fe = ctx.fe
    for node, c, trivial in _scope_inherited_rows(ctx, scope, inherited_rows):
        seg = ctx.text.seg(node) or ""
        direct = set(c.left_names) | set(c.right_names)
        reach = fe._reaching_keys(
            site_node,
            fe._positional_closure(site_node, c.left_names + c.right_names, ctx.ordered_bindings),
            ctx.ordered_bindings,
        )
        ctx.assertions.append(
            Assertion(
                id=f"a{ctx.counter}",
                form=c.form,
                strength=c.strength,
                text=seg,
                span=ctx.off.span(node),
                left=c.left,
                right_literal=c.right_literal,
                right_value=c.right_value,
                epsilon=c.epsilon,
                epsilon_kind=c.epsilon_kind,
                predicate=c.predicate,
                operand_source=c.operand_source,
                unevaluated_expected=c.unevaluated_expected,
                unbound_operands=c.unbound_operands,
                trivial=trivial,
                positive=c.positive,
                left_names=c.left_names,
                right_depends_on=c.right_names,
                inherited=True,
                reaching=reach,
                reaching_sig=fe._reaching_sig(reach, direct),
                via=via,
            )
        )
        ctx.counter += 1


def collect_inherited_assertions(ctx: UnitCollectContext) -> None:
    """Expand assertions inherited from local/module helpers and `self` helper methods (#55, #306).

    Inherited once per unit-level entry site, not once per helper: each copy
    carries the reaching keys of its own call's position, so a pure insertion
    of one more case leaves every other site's copy identical (issue #55,
    sympy aa1b43c3 — the R1 residual), while rebinding a forwarded name
    between its honest definition and the call still changes what that site's
    copy reads. The span stays the helper-side assert — one edited helper line
    keeps collapsing to one finding downstream — so a site's copies differ by
    `reaching_sig` alone, and deleting one of N calls surfaces as a removed
    assertion instead of vanishing into a same-size set (THREATMODEL 91).
    """
    fe = ctx.fe
    func = ctx.func
    root_closures: dict[str, list] = {}
    inherited_rows: dict[int, list[tuple[ast.AST, Any, bool]]] = {}

    for site_node, root in fe._helper_entry_sites(func, ctx.nodes_cache):
        if id(site_node) in ctx.dead or root not in ctx.local_scopes:
            continue
        closure = root_closures.get(root)
        if closure is None:
            closure = fe._executed_scopes(
                func, ctx.module_scopes, caches=ctx.caches, roots=(root,), local_scopes=ctx.local_scopes
            )
            root_closures[root] = closure
        for scope in closure:
            if scope is func:
                continue
            _append_inherited_assertions(ctx, site_node, scope, inherited_rows)

    # A helper method reached through the instance (#306): followed as a
    # module helper is, once per entry site, and its assertions carry the
    # method's class-qualified name as `via` (306 Sub-Q11).
    if ctx.instance is not None:
        method_closures: dict[int, list] = {}
        for site_node in sorted(ctx.method_calls, key=lambda node: (node.lineno, node.col_offset)):
            found = ctx.instance.resolve(func, site_node)
            if found is None:
                continue
            target, owner = found
            via = f"{owner.name}.{target.name}"
            if ctx.resolved is not None:
                ctx.resolved[via] = target
            closure = method_closures.get(id(target))
            if closure is None:
                closure = ctx.instance.closure(target, ctx.module_scopes, ctx.caches)
                method_closures[id(target)] = closure
            for scope in closure:
                if scope is not func:
                    _append_inherited_assertions(ctx, site_node, scope, inherited_rows, via)


def finalize_collected_unit(ctx: UnitCollectContext) -> Any:
    """Attach doctest examples, sort/renumber assertions, and assemble `ParsedUnit`."""
    fe = ctx.fe
    func = ctx.func
    ctx.assertions.extend(fe.checked_examples(func, ctx.doctests, ctx.dead))
    body = ctx.text.seg(func) or ""
    body_hash = hashlib.sha256(fe.normalize_text(body).encode("utf-8")).hexdigest() if body else ""

    ctx.assertions.sort(key=lambda a: a.span)
    for i, a in enumerate(ctx.assertions):
        a.id = f"a{i}"

    side = UnitSide(
        span=ctx.off.span(func),
        assertions=ctx.assertions,
        calls=tuple(sorted(ctx.calls)),
        markers=sorted(ctx.markers, key=lambda m: m.span),
        handlers=sorted(ctx.handlers, key=lambda h: h.span),
        param_cases=fe._param_case_count(func),
        body_hash=body_hash,
        bindings=ctx.definition_bindings,
        # Exclusivity can only matter for a multiply-bound name. Most test
        # units bind each local once, so avoid another full statement walk
        # when the definition map already proves the result must be empty.
        exclusive_bindings=(
            fe._exclusive_bindings(func)
            if any("\x1f" in key for key in ctx.definition_bindings.values())
            else ()
        ),
        param_columns=fe._param_columns(func),
        param_rows=fe._param_tables(func),
        patches=tuple(sorted(ctx.patches)),
        invoked=tuple(sorted(fe._invocations(func, ctx.caches))),
        params=tuple(
            a.arg
            for a in (func.args.posonlyargs + func.args.args + func.args.kwonlyargs)
            if a.arg not in ("self", "cls")
        ),
        fixture_producers=ctx.producers,
    )
    return fe.ParsedUnit(qualname=ctx.qualname, span=side.span, side=side, shingles=fe._shingles(func))

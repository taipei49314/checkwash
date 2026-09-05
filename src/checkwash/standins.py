"""Shared semantics for stand-ins installed under an existing test oracle.

The frontend flattens assignment and patching dialects to ``StandinInstall``.
Both conftest-wide and per-test detectors then make the same two judgements:
is the target positively tied to the repository, and does a live oracle reach
that exact target?
"""

from __future__ import annotations

import ast
from collections import Counter
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field

from checkwash.ir.markers import parse_expr


@dataclass(frozen=True, order=True)
class StandinInstall:
    target: str
    attr: str
    text: str
    scope: str  # module | fixture | class | class_fixture | hook | hookwrapper | test
    owner: str | None = None
    autouse: bool = False
    kind: str = "attribute"  # attribute | binding | module
    position: tuple[int, int] = (0, 0)
    # Human/fingerprint spelling for a unit-local target.  Canonical `target`
    # drives ownership/reach; this retains the pre-existing local spelling
    # (`billing.invoice_total`) where UnitSide.patches historically exposed it.
    display_target: str | None = None
    # Import-alias replacement keeps the old (owned) target in `target` and
    # records the new provider here.  The oracle reaches the local `attr` name;
    # ownership must still be proved for the thing that was replaced.
    replacement_target: str | None = None
    # End of the lexical/runtime interval in which this installation is
    # active.  ``None`` means that it remains active for the rest of the
    # unit.  The endpoint is exclusive: an oracle at this position observes
    # the restored target.  This is analysis metadata, not part of the
    # spelling/effect identity exposed to detectors.
    active_until: tuple[int, int] | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    # Helper-scoped decorators/contexts undo the effect when the helper
    # returns.  These fields let projected call-site installs distinguish
    # inherited oracles that executed inside the owner from caller oracles
    # observed afterwards. They are internal and never enter effect identity.
    persists_after_owner: bool = field(
        default=True,
        repr=False,
        compare=False,
    )
    owner_oracle_spans: tuple[tuple[int, int], ...] = field(
        default=(),
        repr=False,
        compare=False,
    )
    # Conventional pytest fixture whose injected receiver is the positive
    # API-provenance evidence for this call.  The engine uses this to reject
    # a ``mocker``/``monkeypatch`` spelling when a nearer repository fixture
    # shadows the plugin/builtin fixture.  Explicit constructors/imported
    # callables leave the field unset.
    api_fixture_receiver: str | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    @property
    def identity(self) -> tuple[str, str, str]:
        """Spelling-independent identity used for base/head newness."""
        return (self.kind, self.target, self.attr)

    @property
    def effect_identity(self) -> tuple[str, str, str]:
        """Semantic identity of the installed runtime effect.

        Scope, owner, and autouse are applicability evidence, not part of the
        mutation itself.  Callers resolve those conditions independently for
        each side before comparing the oracle multiset.  Including them here
        would turn a fixture rename, an autouse toggle, or a direct-to-fixture
        refactor into a new effect even when the same target already reached
        the same oracle.
        """
        # A binding write's effect is replacing this lexical slot.  Its
        # provider target is ownership evidence, not newness: if an unchanged
        # local assignment sits under a separately edited import, changing
        # that import must not manufacture a newly added assignment.
        return (
            (self.kind, "", self.attr)
            if self.kind == "binding"
            else self.identity
        )

    @property
    def finding_target(self) -> str:
        return self.display_target or self.target


# Only hooks whose ordinary completion precedes test-call execution can
# install a persistent stand-in under a later oracle. A sys.modules swap has
# the tighter boundary for bindings captured at collection; later literal
# runtime imports are modelled separately.
_HOOKS_BEFORE_ORACLE = frozenset(
    {
        "pytest_configure",
        "pytest_sessionstart",
        "pytest_collection_modifyitems",
        "pytest_collection_finish",
        "pytest_generate_tests",
        "pytest_runtest_setup",
    }
)
_HOOKS_BEFORE_IMPORT = frozenset({"pytest_configure", "pytest_sessionstart"})


def target_is_repo_owned(target: str, owned_roots: Collection[str]) -> bool:
    """Whether positive evidence ties this target to the repository.

    ``request.module`` explicitly names the importing test module and a
    relative import is package-local even when its leaf collides with a
    stdlib name. Absolute roots require evidence collected by the engine from
    the base manifest, a repository production path, or a readable module in
    the head snapshot; a declared dependency prevents the readable-path probe
    from deciding ownership unless the manifest also names that root as the
    project itself. An undeclared external import is unknown and stays a named
    residual; absence from a deny list is never ownership proof.
    """
    if target == "request.module" or target.startswith("request.module."):
        return True
    if target.startswith("."):
        return True
    root = target.split(".", 1)[0]
    return bool(root) and root in owned_roots


def _local_names_in(expr: str | None) -> set[str]:
    node = parse_expr(expr) if expr else None
    if node is None:
        return set()
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _binding_name_reached(expr: str | None, name: str) -> bool:
    """Whether an oracle lexically consumes this imported/local binding."""
    return name in _local_names_in(expr)


def _expanded_subject_expressions(
    direct: Collection[str], bindings: Mapping[str, str] | None = None
) -> tuple[str, ...]:
    """Oracle subjects plus one unambiguous local-binding hop."""
    direct = tuple(expression for expression in direct if expression)
    bound = bindings or {}
    names = {
        name
        for expression in direct
        for name in _local_names_in(expression)
    }
    definitions = tuple(
        definition
        for name in sorted(names)
        if (definition := bound.get(name)) is not None
        and "\x1f" not in definition
    )
    return direct + definitions


def _dotted(node: ast.AST) -> str | None:
    parts: list[str] = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if not isinstance(cur, ast.Name):
        return None
    parts.append(cur.id)
    return ".".join(reversed(parts))


def _canonical_subject_refs(
    expr: str | None, import_bindings: Mapping[str, str]
) -> set[str]:
    """Canonical import chains occurring in one oracle-subject expression."""
    node = parse_expr(expr) if expr else None
    if node is None:
        return set()
    refs: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            source = import_bindings.get(child.id)
            if source is not None:
                refs.add(source)
        elif isinstance(child, ast.Attribute):
            dotted = _dotted(child)
            if dotted is None:
                continue
            if dotted == "request.module" or dotted.startswith("request.module."):
                refs.add(dotted)
                continue
            root, dot, suffix = dotted.partition(".")
            source = import_bindings.get(root)
            if source is not None:
                refs.add(source + (dot + suffix if dot else ""))
    return refs


def _canonical_live_attribute_refs(
    expr: str | None, import_bindings: Mapping[str, str]
) -> set[str]:
    """Canonical chains whose final value is looked up at oracle runtime.

    A bare imported name is a captured object: patching the source module's
    attribute later does not update that local binding.  In contrast,
    ``billing.invoice_total`` still performs an attribute lookup on the live
    imported module object.  Keep that distinction instead of collapsing
    both spellings to the same canonical string.
    """
    node = parse_expr(expr) if expr else None
    if node is None:
        return set()
    refs: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Attribute):
            continue
        dotted = _dotted(child)
        if dotted is None:
            continue
        if dotted == "request.module" or dotted.startswith(
            "request.module."
        ):
            refs.add(dotted)
            continue
        root, dot, suffix = dotted.partition(".")
        source = import_bindings.get(root)
        if source is not None:
            refs.add(source + (dot + suffix if dot else ""))
    return refs


def _runtime_leaf_binding_reaches(
    install: StandinInstall,
    expressions: Collection[str],
    import_bindings: Mapping[str, str],
    runtime_imports: Collection[
        tuple[str, str, str, int, int]
    ] | None,
    oracle_position: tuple[int, int],
    *,
    projected: bool = False,
) -> bool:
    """Whether a fresh post-install ``from M import leaf`` is consumed."""
    parent, dot, _leaf = install.target.rpartition(".")
    if not dot:
        return False
    for local, binding, loaded, line, column in runtime_imports or ():
        if binding != install.target or loaded != parent:
            continue
        if import_bindings.get(local) != binding:
            continue
        if not any(
            _binding_name_reached(expression, local)
            for expression in expressions
        ):
            continue
        position = (line, column)
        if projected and install.scope == "test" and install.owner is None:
            # The row is inside a helper definition executed at the oracle's
            # projected call site.  The enclosing test install has already
            # passed the call-site window check in `_install_reaches_assertion`.
            return True
        if position >= oracle_position:
            continue
        if (
            install.scope == "test"
            and (
                position <= install.position
                or (
                    install.active_until is not None
                    and position >= install.active_until
                )
            )
        ):
            continue
        return True
    return False


def _attribute_leaf_capture_needs_runtime_import(
    install: StandinInstall,
) -> bool:
    """Whether collection-time leaf bindings predate this install.

    Test bodies, fixture setup, and later pytest hooks run after test-module
    collection.  Their module-attribute writes therefore cannot update a
    top-level ``from`` binding.  Module/class-body writes are intentionally
    absent: they can occur on either side of a same-file import, whose source
    position is not part of the current per-assertion IR.
    """
    return install.scope in (
        "fixture",
        "class",
        "class_fixture",
        "hookwrapper",
        "test",
    ) or (
        install.scope == "hook"
        and install.owner not in _HOOKS_BEFORE_IMPORT
    )


def _same_file_module_leaf_reach(
    install: StandinInstall,
    expressions: Collection[str],
    import_bindings: Mapping[str, str],
    module_imports: Collection[
        tuple[str, str, str, int, int]
    ] | None,
) -> bool | None:
    """Reach state for a same-file module install and captured leaf.

    ``None`` means that the origin is not definite enough to narrow the
    conservative canonical-reference fallback.  A definite import after the
    install captured the replacement; when every consumed exact leaf came
    from an earlier import, each local still holds the original object.
    """
    parent, dot, _leaf = install.target.rpartition(".")
    if not dot:
        return None
    captured = {
        local
        for expression in expressions
        for local in _local_names_in(expression)
        if import_bindings.get(local) == install.target
    }
    if not captured:
        return None

    origins: dict[str, tuple[int, int]] = {}
    for local, binding, loaded, line, column in module_imports or ():
        if (
            local in captured
            and binding == install.target
            and loaded == parent
            and import_bindings.get(local) == binding
        ):
            origins[local] = (line, column)
    if any(position > install.position for position in origins.values()):
        return True
    if captured.issubset(origins):
        return False
    return None


def _runtime_imports_in(
    expr: str | None, import_bindings: Mapping[str, str]
) -> set[str]:
    """Literal targets reached through a live ``importlib`` binding."""
    node = parse_expr(expr) if expr else None
    if node is None:
        return set()
    modules: set[str] = set()
    for call in ast.walk(node):
        if not isinstance(call, ast.Call) or not call.args:
            continue
        dotted = _dotted(call.func)
        if dotted is None:
            continue
        root, dot, suffix = dotted.partition(".")
        source = import_bindings.get(root)
        if source is None:
            # Conventional spelling is not ownership evidence: a parameter
            # or local named `importlib` can expose any `import_module` method.
            continue
        canonical = source + (dot + suffix if dot else "")
        if canonical != "importlib.import_module":
            continue
        first = call.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            modules.add(first.value)
    return modules


def _module_runtime_row_reaches(
    install: StandinInstall,
    expressions: Collection[str],
    import_bindings: Mapping[str, str],
    bindings: Mapping[str, str] | None,
    runtime_imports: Collection[
        tuple[str, str, str, int, int]
    ] | None,
) -> bool:
    """Whether a still-live fresh import captured this module install."""
    expanded = _expanded_subject_expressions(expressions, bindings)
    for local, binding, loaded, line, column in runtime_imports or ():
        # Native imports retain their canonical binding; dynamic literal
        # imports use an empty binding and carry liveness in the positional
        # flow row itself.
        if binding and import_bindings.get(local) != binding:
            continue
        if not any(
            _binding_name_reached(expression, local)
            for expression in expanded
        ):
            continue
        if loaded != install.target:
            continue
        position = (line, column)
        if install.scope == "test" and position <= install.position:
            continue
        if (
            install.scope == "test"
            and install.active_until is not None
            and position >= install.active_until
        ):
            continue
        return True
    return False


def install_reaches_expressions(
    install: StandinInstall,
    expressions: Collection[str],
    import_bindings: Mapping[str, str],
    bindings: Mapping[str, str] | None = None,
    lexical_names: Collection[str] = (),
    runtime_imports: Collection[
        tuple[str, str, str, int, int]
    ] | None = None,
    oracle_position: tuple[int, int] | None = None,
    module_imports: Collection[
        tuple[str, str, str, int, int]
    ] | None = None,
    same_unit_install: bool = False,
    runtime_imports_projected: bool = False,
) -> bool:
    """Whether canonical oracle-subject expressions reach an installation.

    Attribute labels alone are insufficient: two unrelated modules can both
    expose ``normalize``.  Imported local names anchor the reached label to
    the same canonical module path as the installation.
    """
    expressions = _expanded_subject_expressions(expressions, bindings)
    if not expressions:
        return False

    if install.target.startswith("request.module."):
        return any(
            install.attr in _local_names_in(expression)
            and install.attr not in lexical_names
            for expression in expressions
        )

    # Replacing a `from M import name` binding (by assignment or by changing
    # the import source while keeping its alias) leaves the oracle spelling as
    # that local name.  Once rebound it no longer resolves through the import
    # map, so reach is necessarily lexical for this one installation kind.
    if install.kind == "binding":
        if (
            install.replacement_target is not None
            and import_bindings.get(install.attr) != install.replacement_target
        ):
            return False
        return any(
            _binding_name_reached(expression, install.attr)
            for expression in expressions
        )

    refs = {
        ref
        for expression in expressions
        for ref in _canonical_subject_refs(expression, import_bindings)
    }

    if install.kind == "module":
        dynamic_imports = {
            module
            for expression in expressions
            for module in _runtime_imports_in(expression, import_bindings)
        }
        if install.target in dynamic_imports:
            return True
        if _module_runtime_row_reaches(
            install,
            expressions,
            import_bindings,
            bindings,
            runtime_imports,
        ):
            return True
        # A fixture, test body, or later hook runs after collection imported
        # the test module. Its sys.modules replacement affects only a fresh
        # runtime import, handled above; a top-level binding is already live.
        if install.scope in (
            "fixture",
            "class",
            "class_fixture",
            "hookwrapper",
            "test",
        ) or (
            install.scope == "hook" and install.owner not in _HOOKS_BEFORE_IMPORT
        ):
            return False
        return any(
            ref == install.target or ref.startswith(install.target + ".")
            for ref in refs
        )

    # An attribute replacement installed after module collection cannot
    # retroactively update a leaf captured by an earlier ``from`` import.
    # Rich Python IR supplies the exact oracle position and definite runtime-
    # import rows: a bare leaf reaches only when a matching fresh ``from``
    # import executed after the install. Attribute access through a module or
    # object import remains a live lookup. External IR-v1 has no positional
    # evidence and retains the conservative historical fallback below.
    if (
        install.kind == "attribute"
        and _attribute_leaf_capture_needs_runtime_import(install)
        and oracle_position is not None
    ):
        live_refs = {
            ref
            for expression in expressions
            for ref in _canonical_live_attribute_refs(
                expression, import_bindings
            )
        }
        if install.target in live_refs:
            return True
        return _runtime_leaf_binding_reaches(
            install,
            expressions,
            import_bindings,
            runtime_imports,
            oracle_position,
            projected=runtime_imports_projected,
        )

    # Module/class-body writes execute during this file's import.  Only a
    # same-UnitSide install has comparable source coordinates: conftest module
    # installs execute before a downstream test file is imported and must not
    # compare unrelated line numbers.  A module object still performs a live
    # attribute lookup, and a function-local import necessarily runs after
    # module import completes.
    if (
        install.kind == "attribute"
        and install.scope == "module"
        and same_unit_install
        and oracle_position is not None
    ):
        live_refs = {
            ref
            for expression in expressions
            for ref in _canonical_live_attribute_refs(
                expression, import_bindings
            )
        }
        if install.target in live_refs:
            return True
        if _runtime_leaf_binding_reaches(
            install,
            expressions,
            import_bindings,
            runtime_imports,
            oracle_position,
            projected=runtime_imports_projected,
        ):
            return True
        module_reach = _same_file_module_leaf_reach(
            install,
            expressions,
            import_bindings,
            module_imports,
        )
        if module_reach is not None:
            return module_reach

    # Module and attribute must be one canonical subject chain. Seeing the
    # module on the subject side and the attribute on the expectation side is
    # not reachability.
    return install.target in refs


def _install_reaches_assertion(
    install: StandinInstall,
    assertion,
    side,
    import_bindings: Mapping[str, str],
) -> bool:
    """Whether one oracle executes inside and consumes one install."""
    if assertion.left is None:
        return False

    oracle_position = getattr(assertion, "standin_position", None)
    exact_imports = getattr(assertion, "standin_imports", None)
    live_imports = (
        exact_imports if exact_imports is not None else import_bindings
    )
    if install.scope == "test" and oracle_position is not None:
        inside_owner = bool(
            assertion.inherited
            and oracle_position == install.position
            and assertion.span in install.owner_oracle_spans
        )
        if not inside_owner and not install.persists_after_owner:
            return False
        # A local install begins after its installing expression completes.
        # Its optional endpoint is exclusive: an assertion at the restoration
        # boundary no longer observes the stand-in.
        if not inside_owner and install.position >= oracle_position:
            return False
        if (
            install.active_until is not None
            and oracle_position >= install.active_until
        ):
            if install.kind != "module" or not _module_runtime_row_reaches(
                install,
                (assertion.left,),
                live_imports,
                getattr(side, "bindings", None),
                getattr(assertion, "standin_runtime_imports", None),
            ):
                return False

    return install_reaches_expressions(
        install,
        (assertion.left,),
        live_imports,
        getattr(side, "bindings", None),
        getattr(side, "standin_lexical_names", ()),
        getattr(assertion, "standin_runtime_imports", None),
        oracle_position,
        getattr(assertion, "standin_module_imports", None),
        any(
            candidate is install
            for candidate in (
                getattr(side, "standin_installs", None) or ()
            )
        ),
        bool(
            getattr(
                assertion,
                "standin_runtime_imports_projected",
                False,
            )
        ),
    )


def install_reaches(
    install: StandinInstall,
    side,
    import_bindings: Mapping[str, str],
) -> bool:
    """Whether this unit's canonical oracle subjects reach an install."""
    # An assertion can sit before or after a local import/rebind.  Prefer the
    # binding environment captured at that exact position; inherited/external
    # assertions have no positional map and use the unit/file fallback.
    return any(
        _install_reaches_assertion(
            install,
            assertion,
            side,
            import_bindings,
        )
        for assertion in side.assertions
    )


def _canonical_expression(expression: str | None) -> str:
    """Formatting-independent syntax for one expression, when parseable."""
    node = parse_expr(expression) if expression else None
    if node is None:
        return " ".join((expression or "").split())
    return ast.dump(node, annotate_fields=True, include_attributes=False)


def _oracle_semantic_key(assertion) -> str:
    """Stable identity of the complete oracle, excluding its message.

    Current Python IR carries a canonical full-expression key.  The fallback
    is intentionally richer than dependency-name summaries so independently
    constructed IR-v1 assertions still distinguish ``expected`` from
    ``expected + 1`` while ignoring source whitespace.
    """
    internal = getattr(assertion, "standin_oracle_key", None)
    if internal is not None:
        return internal

    syntax = ""
    text = getattr(assertion, "text", "")
    try:
        module = ast.parse(text)
    except (SyntaxError, ValueError, TypeError):
        module = None
    if module is not None and len(module.body) == 1:
        statement = module.body[0]
        if isinstance(statement, ast.Assert):
            # The optional assertion message is not part of the oracle.
            syntax = ast.dump(
                statement.test,
                annotate_fields=True,
                include_attributes=False,
            )
        elif isinstance(statement, ast.Expr):
            syntax = ast.dump(
                statement.value,
                annotate_fields=True,
                include_attributes=False,
            )

    if not syntax:
        expected = (
            getattr(assertion, "right_value", None)
            or _canonical_expression(
                getattr(assertion, "right_literal", None)
            )
            or "\x1f".join(
                getattr(assertion, "right_depends_on", ()) or ()
            )
        )
        syntax = "\x1f".join(
            (
                _canonical_expression(getattr(assertion, "left", None)),
                expected,
                getattr(assertion, "epsilon_kind", None) or "",
                _canonical_expression(
                    getattr(assertion, "epsilon", None)
                ),
            )
        )

    return "\x1d".join(
        (
            getattr(assertion, "form", "unknown"),
            "1" if getattr(assertion, "positive", True) else "0",
            syntax,
        )
    )


class _ProviderSlotNames(ast.NodeTransformer):
    """Replace local provider aliases with structural oracle slots."""

    def __init__(self, slots: Mapping[str, str]):
        self.slots = slots

    def visit_Name(self, node: ast.Name) -> ast.AST:
        replacement = self.slots.get(node.id)
        if replacement is None:
            return node
        return ast.copy_location(
            ast.Name(id=replacement, ctx=node.ctx), node
        )


def _ordered_subject_names(expression: str) -> tuple[str, ...]:
    """Names in stable syntactic-use order, without duplicate occurrences."""
    node = parse_expr(expression)
    if node is None:
        return ()
    seen: set[str] = set()
    ordered: list[str] = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Name) or child.id in seen:
            continue
        seen.add(child.id)
        ordered.append(child.id)
    return tuple(ordered)


def _provider_slot_oracle_key(
    assertion,
    slots: Mapping[str, str],
) -> str:
    """Oracle identity invariant to a provider local's alias spelling.

    Python's internal key already canonicalizes module-attribute aliases, but
    a bare imported callable remains a ``Name``.  Replace only locals with a
    positively classified provider, and do so by syntactic slot, so ordinary
    local shadows and string literals cannot borrow import provenance.
    """
    internal = getattr(assertion, "standin_oracle_key", None)
    if internal is None or not slots:
        return _oracle_semantic_key(assertion)
    prefix = internal.split("\x1d", 2)
    if len(prefix) != 3:
        return internal

    def normalize(component: str) -> str:
        keyword = ""
        expression = component
        name, equals, value = component.partition("=")
        if (
            equals
            and name.isidentifier()
            and not value.startswith("=")
        ):
            keyword = name + "="
            expression = value
        node = parse_expr(expression)
        if node is None:
            return component
        normalized = _ProviderSlotNames(slots).visit(node)
        ast.fix_missing_locations(normalized)
        return keyword + ast.dump(
            normalized,
            annotate_fields=True,
            include_attributes=False,
        )

    semantic = "\x1e".join(
        normalize(component) for component in prefix[2].split("\x1e")
    )
    return "\x1d".join((prefix[0], prefix[1], semantic))


def _install_sort_key(install: StandinInstall) -> tuple:
    return (
        install.effect_identity,
        install.finding_target,
        install.text,
        install.position,
        install.active_until or (10**12, 10**12),
        install.replacement_target or "",
    )


def effect_oracle_multisets(
    side,
    import_bindings: Mapping[str, str],
    installs: Collection[StandinInstall] | None = None,
) -> tuple[
    Counter[str],
    dict[tuple[str, str, str], Counter[str]],
    dict[tuple[str, str, str], StandinInstall],
]:
    """Return all oracles and the oracle multiset reached by each effect.

    Installations with the same ``effect_identity`` are alternative instances
    of one runtime effect.  A particular oracle occurrence is therefore
    counted once when *any* instance reaches it, rather than once per spelling
    or installation site.  Representatives retain deterministic finding text
    and target data for callers that select a newly reaching effect.
    """
    selected = (
        tuple(installs)
        if installs is not None
        else tuple(getattr(side, "standin_installs", None) or ())
    )
    grouped: dict[
        tuple[str, str, str], list[StandinInstall]
    ] = {}
    for install in sorted(selected, key=_install_sort_key):
        grouped.setdefault(install.effect_identity, []).append(install)

    representatives = {
        effect: instances[0]
        for effect, instances in sorted(grouped.items())
    }
    oracles: Counter[str] = Counter()
    reached: dict[
        tuple[str, str, str], Counter[str]
    ] = {effect: Counter() for effect in representatives}
    representative_reaches: set[
        tuple[str, str, str]
    ] = set()
    for assertion in side.assertions:
        if assertion.left is None:
            continue
        key = _oracle_semantic_key(assertion)
        oracles[key] += 1
        for effect, instances in grouped.items():
            for install in instances:
                if not _install_reaches_assertion(
                    install,
                    assertion,
                    side,
                    import_bindings,
                ):
                    continue
                reached[effect][key] += 1
                # Prefer a representative that really reaches an oracle.
                # Otherwise a same-effect spelling after every assertion
                # could be selected ahead of the instance that caused the
                # event, then be rejected by a detector's defensive reach
                # check.
                if effect not in representative_reaches:
                    representatives[effect] = install
                    representative_reaches.add(effect)
                break
    return oracles, reached, representatives


def new_reaching_effects(
    before,
    after,
    before_import_bindings: Mapping[str, str] | None = None,
    after_import_bindings: Mapping[str, str] | None = None,
    *,
    before_installs: Collection[StandinInstall] | None = None,
    after_installs: Collection[StandinInstall] | None = None,
) -> tuple[StandinInstall, ...]:
    """Select effects newly known to reach a pre-existing oracle.

    For every effect/oracle shape, the sound lower bound is::

        max(0, R_head - R_base - max(0, O_head - O_base))

    The final term spends newly added identical oracles first.  Only a reach
    increase that cannot be explained by such additions is a new stand-in
    event.
    """
    before_imports = (
        before_import_bindings
        if before_import_bindings is not None
        else getattr(before, "standin_imports", None) or {}
    )
    after_imports = (
        after_import_bindings
        if after_import_bindings is not None
        else getattr(after, "standin_imports", None) or {}
    )
    before_oracles, before_reached, _before_representatives = (
        effect_oracle_multisets(before, before_imports, before_installs)
    )
    after_oracles, after_reached, after_representatives = (
        effect_oracle_multisets(after, after_imports, after_installs)
    )

    selected: list[StandinInstall] = []
    for effect, head_counts in sorted(after_reached.items()):
        base_counts = before_reached.get(effect, Counter())
        if any(
            max(
                0,
                head_count
                - base_counts[key]
                - max(0, after_oracles[key] - before_oracles[key]),
            )
            for key, head_count in head_counts.items()
        ):
            selected.append(after_representatives[effect])
    return tuple(selected)


def _provider_context(side) -> tuple:
    """Cheap exact context gate for semantic provider transitions.

    The engine uses this same tuple before invoking the more expensive
    per-oracle comparison, so the optimization cannot drift from the shared
    stand-in semantics.
    """
    return (
        getattr(side, "standin_imports", None),
        getattr(side, "standin_module_bindings", None),
        getattr(side, "standin_parameter_providers", None),
        getattr(side, "standin_lexical_names", ()),
        getattr(side, "params", ()),
        getattr(side, "fixtures", ()),
        getattr(side, "param_columns", {}),
        getattr(side, "bindings", {}),
        tuple(
            (
                getattr(assertion, "standin_imports", None),
                getattr(assertion, "reaching", None),
            )
            for assertion in side.assertions
        ),
    )


def new_unit_standin_installs(before, after) -> tuple[StandinInstall, ...]:
    """New semantic stand-in effects for one aligned unit.

    Rich internal metadata is preferred.  The fallback preserves compatibility
    with an externally constructed IR-v1 UnitSide, whose only channel is the
    historical local-spelling `patches` tuple.
    """
    before_internal = getattr(before, "standin_installs", None)
    after_internal = getattr(after, "standin_installs", None)
    if before_internal is None or after_internal is None:
        was = set(before.patches)
        return tuple(
            StandinInstall(
                target=target,
                attr=attr,
                text=target,
                scope="test",
                display_target=target,
            )
            for target, attr in after.patches
            if (target, attr) not in was
        )

    if not before_internal and not after_internal:
        # Almost every unit in an ordinary diff has no stand-in syntax.  The
        # one remaining event this function can synthesize is an existing
        # oracle binding changing provider (#88).  Prove that its entire raw
        # provider environment is unchanged before doing any expression AST
        # work.  Oracle text/shape is intentionally absent: changing only an
        # expectation cannot manufacture a provider transition.
        if _provider_context(before) == _provider_context(after):
            return ()

    before_imports = getattr(before, "standin_imports", None) or {}
    after_imports = getattr(after, "standin_imports", None) or {}
    found = list(
        new_reaching_effects(
            before,
            after,
            before_imports,
            after_imports,
            before_installs=before_internal,
            after_installs=after_internal,
        )
    )

    # Issue #88: the installation can be the import statement itself.  The
    # local alias is stable while its provider changes from first-party code
    # to a reference/stand-in.  New imports are ordinary setup; only replacing
    # an existing binding is an event.
    def definition_provider(
        definition: str, imports: Mapping[str, str]
    ) -> str | None:
        """Canonical provider for one unambiguous local definition."""
        if not definition or "\x1f" in definition:
            return None
        node = parse_expr(definition)
        if node is None:
            return None
        dotted = _dotted(node)
        if dotted is None:
            return None
        root, dot, suffix = dotted.partition(".")
        provider = imports.get(root)
        if provider is None:
            return None
        return provider + (dot + suffix if dot else "")

    def oracle_shape(assertion, expression: str) -> str:
        """Stable assertion identity without source-formatting trivia."""
        internal = getattr(assertion, "standin_oracle_key", None)
        if internal is not None:
            return internal
        # External IR-v1 assertions have no private full-oracle key.  Include
        # the canonical subject in addition to the richer fallback so two
        # provider slots within an otherwise identical unittest call remain
        # distinct.
        return "\x1d".join(
            (_oracle_semantic_key(assertion), _canonical_expression(expression))
        )

    def binding_oracles(
        side,
    ) -> tuple[
        dict[tuple[str, str], Counter[tuple[str, str]]],
        dict[
            tuple[str, str],
            dict[tuple[str, str], list[str]],
        ],
    ]:
        fallback = getattr(side, "standin_imports", None) or {}
        module_bindings = getattr(side, "standin_module_bindings", None) or {}
        parameter_providers = (
            getattr(side, "standin_parameter_providers", None) or {}
        )
        lexical_names = set(
            getattr(side, "standin_lexical_names", ()) or ()
        )
        reached: dict[tuple[str, str], Counter[tuple[str, str]]] = {}
        locals_by_provider: dict[
            tuple[str, str],
            dict[tuple[str, str], list[str]],
        ] = {}
        for assertion in side.assertions:
            expression = assertion.left
            if expression is None:
                continue
            exact_imports = getattr(assertion, "standin_imports", None)
            if exact_imports is None and getattr(
                side, "standin_installs", None
            ) is not None:
                # Cross-file/fixture-carried assertions do not have a source
                # position in this unit. They remain eligible for ordinary
                # stand-in reach via the legacy fallback, but cannot prove an
                # import-provider replacement happened before their oracle.
                continue
            imports = exact_imports if exact_imports is not None else fallback
            expressions = _expanded_subject_expressions(
                (expression,), side.bindings
            )
            names = {
                name
                for expanded in expressions
                for name in _local_names_in(expanded)
            }
            reaching = getattr(assertion, "reaching", None) or {}
            providers: dict[str, tuple[str, str]] = {}
            for local in sorted(names):
                target = imports.get(local)
                provider: tuple[str, str] | None = (
                    ("import", target) if target is not None else None
                )
                if provider is None and reaching.get(local):
                    provider = (
                        "local",
                        definition_provider(reaching[local], imports) or "",
                    )
                is_parameter = local in getattr(side, "params", ())
                if provider is None and is_parameter:
                    parameter_provider = parameter_providers.get(local)
                    if (
                        parameter_provider is not None
                        and parameter_provider[0] == "ambiguous"
                    ):
                        continue
                    provider = parameter_provider
                if (
                    provider is None
                    and local in side.param_columns
                    and local not in getattr(side, "fixtures", ())
                ):
                    # A literal direct-parametrize column is a positively
                    # identified provider.  A bare or indirect parameter is
                    # only lexical shadow evidence and must not borrow a
                    # same-named module definition below.
                    provider = ("parametrize", side.param_columns[local])
                if (
                    provider is None
                    and is_parameter
                    and module_bindings.get(local) == "<fixture>"
                ):
                    # A same-file fixture definition is a positive provider
                    # for its requested parameter.  Plugin/conftest fixtures
                    # have no side-local definition proof and stay silent.
                    provider = ("fixture", "<fixture>")
                if (
                    provider is None
                    and not is_parameter
                    and local not in lexical_names
                    and local in module_bindings
                ):
                    provider = ("module", module_bindings[local])
                if provider is not None:
                    providers[local] = provider

            # Bare imported callables are semantically provider slots, not
            # durable local spellings.  Number only positively classified
            # direct subject names in syntactic order.  Expanded helper names
            # keep their old name-keyed fallback because they have no slot in
            # the assertion syntax itself.
            direct_slots = tuple(
                local
                for local in _ordered_subject_names(expression)
                if local in providers
            )
            slot_names = {
                local: f"__checkwash_standin_provider_{index}"
                for index, local in enumerate(direct_slots)
            }
            slot_ids = {
                local: f"slot:{index}"
                for index, local in enumerate(direct_slots)
            }
            normalized_shape = _provider_slot_oracle_key(
                assertion, slot_names
            )
            for local, provider in sorted(providers.items()):
                key = (
                    (slot_ids[local], normalized_shape)
                    if local in slot_ids
                    else (
                        "name:" + local,
                        oracle_shape(assertion, expression),
                    )
                )
                reached.setdefault(key, Counter())[provider] += 1
                locals_by_provider.setdefault(key, {}).setdefault(
                    provider, []
                ).append(local)
        return reached, locals_by_provider

    before_oracles, _before_locals = binding_oracles(before)
    after_oracles, after_locals = binding_oracles(after)
    for key in sorted(set(before_oracles) & set(after_oracles)):
        # Compare multisets within one oracle shape.  Cartesian-producting
        # provider sets invents A→B and B→A changes when an unchanged test
        # repeats the same assertion on either side of a local re-import.
        removed = sorted(
            (before_oracles[key] - after_oracles[key]).elements()
        )
        added = sorted(
            (after_oracles[key] - before_oracles[key]).elements()
        )
        local_offsets: Counter[tuple[str, str]] = Counter()
        for old, new in zip(removed, added):
            old_mode, old_target = old
            new_mode, new_target = new
            if old_mode != "import" or (
                new_target and new_target == old_target
            ):
                continue
            choices = after_locals.get(key, {}).get(new, ())
            offset = local_offsets[new]
            if offset >= len(choices):
                continue
            local = choices[offset]
            local_offsets[new] += 1
            found.append(
                StandinInstall(
                    target=old_target,
                    attr=local,
                    text=local,
                    scope=(
                        "test"
                        if new_mode
                        in ("local", "default", "parametrize", "fixture")
                        else "module"
                    ),
                    kind="binding",
                    display_target=local,
                    replacement_target=(
                        new_target if new_mode == "import" else None
                    ),
                )
            )

    by_effect: dict[tuple, StandinInstall] = {}
    for install in sorted(
        found,
        key=_install_sort_key,
    ):
        # Binding effect identity intentionally omits its replaced provider,
        # but ownership is proved *after* this function returns. Preserve one
        # representative per candidate target until that filter runs; an
        # external provider must not crowd out a repo-owned provider merely
        # because both replace the same lexical slot.
        key = (
            (*install.effect_identity, install.target)
            if install.kind == "binding"
            else install.effect_identity
        )
        by_effect.setdefault(key, install)
    return tuple(by_effect.values())


def fixture_closure(
    requested: Collection[str],
    dependencies: Mapping[str, Collection[str]] | None = None,
) -> frozenset[str]:
    """Requested fixtures plus their finite, name-keyed dependency closure."""
    seen = set(requested)
    pending = list(seen)
    graph = dependencies or {}
    while pending:
        fixture = pending.pop()
        for dependency in graph.get(fixture, ()):
            if dependency not in seen:
                seen.add(dependency)
                pending.append(dependency)
    return frozenset(seen)


def install_applies(
    install: StandinInstall,
    side,
    fixture_dependencies: Mapping[str, Collection[str]] | None = None,
    active_fixtures: Collection[str] = (),
    fixture_providers: Mapping[str, str] | None = None,
    install_provider: str | None = None,
) -> bool:
    """Whether a module/fixture/hook installation executes for this unit."""
    if install.scope == "module":
        return True
    if install.scope == "hook":
        hook = install.owner or ""
        return hook in _HOOKS_BEFORE_ORACLE
    if install.scope == "hookwrapper":
        return install.owner == "pytest_runtest_call"
    if install.scope in ("fixture", "class_fixture"):
        owner = (install.owner or "").rsplit(".", 1)[-1]
        if (
            fixture_providers is not None
            and install_provider is not None
            and fixture_providers.get(owner) != install_provider
        ):
            return False
        directly_requested = getattr(side, "fixtures", side.params)
        requested = fixture_closure(
            (*directly_requested, *active_fixtures), fixture_dependencies
        )
        return install.autouse or owner in requested
    return False

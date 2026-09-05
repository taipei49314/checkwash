"""IR data model (SPEC: checkwash_ir_version 1).

Detectors consume this and nothing else. All ordering inside the IR is
explicit and deterministic; no dict/set iteration order leaks into output.
Spans are character offsets into CRLF→LF-normalized source (SPEC §8).
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any

from checkwash import IR_VERSION


@dataclass
class Assertion:
    id: str
    form: str  # compare_eq | compare_ord | membership | non_null | approx | type_shape | pattern | truthy | tautology | raises | unknown
    strength: int | None
    text: str
    span: tuple[int, int]
    left: str | None = None
    right_literal: str | None = None
    right_value: str | None = None  # repr() of the evaluated literal, for hardcode matching
    epsilon: str | None = None  # literal source text of the tolerance, never a float
    epsilon_kind: str | None = None  # rel | abs | delta (bigger=looser) | places (bigger=stricter)
    # The asserted subject depends only on literals and builtins, so the
    # assertion cannot fail. Such assertions never count as compensation.
    trivial: bool = False
    # False for negated forms (!=, is not, not in, assertFalse, ...).
    # Flipping polarity inverts what the test proves while leaving form and
    # strength identical, so it needs to be part of the assertion's identity.
    positive: bool = True
    # Names appearing in the asserted subject's own expression, and the names
    # the expectation transitively depends on after in-body assignments are
    # followed (`expected = sum(items)` -> ("items", "sum")). Both sorted.
    #
    # These exist for EXPECTED_VALUE_DERIVED, which needs to tell a rewritten
    # expectation apart from a *recomputed* one. A literal replaced by a named
    # constant shares nothing with the subject; a literal replaced by an
    # expression over the subject's own arguments is the test re-implementing
    # the code it is supposed to be checking (THREATMODEL 84a).
    left_names: tuple[str, ...] = ()
    right_depends_on: tuple[str, ...] = ()
    # True when the expectation side is a single bare name — `== expected`,
    # nothing wrapped around it. Set for inherited helper asserts, where it is
    # the discriminator between "the literal-ness moved to the call site" and
    # "the helper transforms the expectation before comparing" (`sorted(...)`,
    # `set(...)`) — the latter is how three disguised-arm attacks hide, and
    # both spellings depend on the same names, so `right_depends_on` cannot
    # tell them apart.
    bare_expectation: bool = False
    # True when this assertion is not written in the unit but in a same-file
    # scope the unit invokes. It is part of the unit's oracle either way — that
    # is the whole point of reachability — but it is not part of the unit's
    # *body*, and rules that reason about an assertion holding a slot need to
    # know the difference. Extracting a concrete assert into a shared,
    # parametrised helper otherwise reads as substitution.
    inherited: bool = False
    # Reaching definition keys for the names this assertion consumes: name ->
    # the last unconditional
    # binding at or before this assertion joined with every conditional binding
    # after that one, in source order. SPEC §5's stated semantics — "the last
    # unconditional binding is the one the assertion reads" — held
    # per-assertion: `UnitSide.bindings` joins every definition of a name, so
    # inserting one self-contained case into a long function changed "the"
    # definition for every untouched assertion (sympy ed75b73d fired 13 times
    # on a 23-line pure insertion; R1). A name bound in the unit only *after*
    # the assertion maps to "", which is equal on both sides of a tail-append
    # and different when a definition moves across the assertion. A name bound
    # only inside a nested def is absent, and consumers fall back to the
    # unit-level map. Same-file inherited assertions carry the keys of their
    # unit-level call site — computed where the helper's oracle executes
    # relative to the unit's own bindings (issue #55); cross-file and
    # fixture-channel inherited assertions still carry None.
    reaching: dict[str, str] | None = None
    # The pairing signature: the reaching entries of the names this assertion
    # *directly* spells (left and right), serialized stably. Pairing needs a
    # context key so a repeated oracle matches the twin that reads the same
    # definitions — but the transitive closure must stay out of it: `F`
    # resolved through the unit-level map drags in names other definitions of
    # `F` reference, whose reaching keys legitimately differ across an
    # insertion, and a polluted signature would push untouched twins back to
    # the FIFO fallback this exists to avoid. Same-file inherited copies get
    # their call site's signature, which is what tells N copies of one helper
    # assert apart; "" for cross-file and fixture-channel inherited ones.
    reaching_sig: str = ""
    # Import bindings visible at this exact oracle position. A unit-wide map
    # cannot distinguish a live import from a later local rebind, nor can it
    # respect a parameter that lexically shadows a module import. Internal
    # only; emitted IR v1 is unchanged.
    standin_imports: dict[str, str] | None = field(
        default=None,
        repr=False,
        compare=False,
        kw_only=True,
        metadata={"internal": True},
    )
    # Function-local native imports definitely executed before this oracle.
    # Each row is ``(local, canonical binding, loaded module, line, column)``.
    # This is deliberately distinct from ``standin_module_imports``: a
    # fixture-time ``sys.modules`` swap can affect an import in the test body,
    # but cannot affect a module import captured during collection.
    # Internal only; emitted IR v1 is unchanged.
    standin_runtime_imports: tuple[
        tuple[str, str, str, int, int], ...
    ] | None = field(
        default=None,
        repr=False,
        compare=False,
        kw_only=True,
        metadata={"internal": True},
    )
    # Module-level native imports whose exact binding origin is still visible
    # at this oracle.  The row shape matches ``standin_runtime_imports``, but
    # collection-time captures must stay separate from imports executed in a
    # test body: an attribute replacement installed later cannot retroactively
    # change a leaf object captured by ``from module import leaf``. Internal
    # only; emitted IR v1 is unchanged.
    standin_module_imports: tuple[
        tuple[str, str, str, int, int], ...
    ] | None = field(
        default=None,
        repr=False,
        compare=False,
        kw_only=True,
        metadata={"internal": True},
    )
    # True when an inherited helper oracle executes at ``standin_position``
    # but its runtime-import row coordinates remain in the helper definition.
    # A caller-side install is ordered against the projected call site, while
    # the rows retain their exact source origins for helper-local reasoning.
    # Internal only; emitted IR v1 is unchanged.
    standin_runtime_imports_projected: bool = field(
        default=False,
        repr=False,
        compare=False,
        kw_only=True,
        metadata={"internal": True},
    )
    # Runtime position of this oracle within its owning test.  For an
    # inherited same-file oracle this is the helper call site, not the
    # helper's definition span.  It is internal ordering evidence only.
    standin_position: tuple[int, int] | None = field(
        default=None,
        repr=False,
        compare=False,
        kw_only=True,
        metadata={"internal": True},
    )
    # Canonical syntax of the complete oracle expression, excluding an
    # assertion message. Stand-in newness compares the semantic oracle an
    # effect reaches; raw source spacing and dependency-name-only summaries
    # are not stable enough for that security decision. Internal only.
    standin_oracle_key: str | None = field(
        default=None,
        repr=False,
        compare=False,
        kw_only=True,
        metadata={"internal": True},
    )


@dataclass
class Marker:
    name: str  # e.g. "pytest.mark.skip"
    text: str
    span: tuple[int, int]
    # For imperative skip calls (`pytest.skip()` et al.): the conjunction of
    # enclosing `if` conditions, source text, `not (...)`-wrapped for else
    # branches. `if PY_3_14_PLUS: pytest.xfail(...)` is the imperative spelling
    # of `skipif(PY_3_14_PLUS)`, and without the guard D6 cannot tell it from
    # an unconditional kill. Deliberately NOT part of the marker's identity:
    # fingerprints (and therefore recorded allowlist entries) must not change.
    guard: str | None = None


@dataclass
class Handler:
    caught: tuple[str, ...]  # empty = bare except
    is_broad: bool
    text: str
    span: tuple[int, int]


@dataclass
class UnitSide:
    span: tuple[int, int]
    assertions: list[Assertion] = field(default_factory=list)
    calls: tuple[str, ...] = ()  # sorted, unique
    markers: list[Marker] = field(default_factory=list)
    handlers: list[Handler] = field(default_factory=list)
    param_cases: int | None = None  # parametrized case count, None = not parametrized
    # sha256 of the unit's normalized body (decorators excluded), for the
    # whole-unit relocation credit: an assertion-less smoke test that moves
    # files verbatim has nothing in the D2 multiset to prove it moved.
    body_hash: str = ""
    # Locally bound name -> a structural key for its defining expression.
    #
    # `right_depends_on` records which names an expectation reaches; this
    # records what those names are *defined as*. Without it, editing
    # `expected = round(sum(items) * (1 + TAX), 2)` into
    # `round(sum(items), 2)` leaves the assertion line byte-identical and every
    # rule silent — THREATMODEL 86a, the shape an expectation that was already
    # a name has always been able to hide in. The key is `ast.dump` of the
    # parsed expression, so reformatting is not a change and a rename inside it
    # is. Keys inserted in sorted order (SPEC §8).
    bindings: dict[str, str] = field(default_factory=dict)
    # parametrize argname -> canonical text of that column across all rows.
    # A parametrized test's expectation lives in the decorator, not the body,
    # so editing it moves the oracle with the assertion untouched.
    param_columns: dict[str, str] = field(default_factory=dict)
    # Literal paths a conftest removes from collection, sorted. Markers
    # deduplicate by name, so appending a second control to a conftest that
    # already had one produced no event at all (THREATMODEL 81). The path set
    # is what makes it one.
    collect_ignored: tuple[str, ...] = ()
    # Names this unit's own body invokes (invocation, not mention) and the
    # unit's parameter names. The cross-file oracle merge is an engine step —
    # it needs to know what the unit calls (import channel) and what it
    # requests (fixture channel) without re-walking the AST there.
    invoked: tuple[str, ...] = ()
    params: tuple[str, ...] = ()
    # Fixtures explicitly requested by function parameters or usefixtures
    # markers. Kept separate so `params` retains its frozen IR meaning.
    fixtures: tuple[str, ...] = field(
        default=(),
        repr=False,
        compare=False,
        kw_only=True,
        metadata={"internal": True},
    )
    # Internal analysis context for the stand-in family.  These fields are
    # deliberately omitted from the serialized IR-v1 contract: `patches`
    # below predates the richer lifetime/alias model and its local spellings
    # and fingerprints are frozen.  New syntax is carried alongside it rather
    # than silently changing that public field's meaning.
    standin_imports: dict[str, str] | None = field(
        default=None,
        repr=False,
        compare=False,
        kw_only=True,
        metadata={"internal": True},
    )
    standin_installs: tuple[Any, ...] | None = field(
        default=None,
        repr=False,
        compare=False,
        kw_only=True,
        metadata={"internal": True},
    )
    # Top-level bare bindings that replace an import provider before tests
    # execute.  Kept per side so an aligned unit can prove the removed-import
    # spelling without changing the frozen `patches` census.
    standin_module_bindings: dict[str, str] | None = field(
        default=None,
        repr=False,
        compare=False,
        kw_only=True,
        metadata={"internal": True},
    )
    # Positively identified providers for test parameters: direct
    # parametrize values and evaluated Python defaults.  Fixture parameters
    # remain name-resolved through ``standin_module_bindings``.  Internal
    # only so the IR-v1 parameter/column contracts stay frozen.
    standin_parameter_providers: dict[str, tuple[str, str]] | None = field(
        default=None,
        repr=False,
        compare=False,
        kw_only=True,
        metadata={"internal": True},
    )
    # Names made lexical by the function body, including bindings whose
    # control-flow provenance is too uncertain to promote.  This prevents a
    # conditional/later local definition from borrowing a same-named module
    # provider. Internal only; positive local providers still come from each
    # assertion's positional ``reaching`` map.
    standin_lexical_names: tuple[str, ...] = field(
        default=(),
        repr=False,
        compare=False,
        kw_only=True,
        metadata={"internal": True},
    )
    # Fixture definitions contributed by lexical test classes, outermost to
    # innermost.  Each row is ``(class qualname, dependencies, autouse names)``.
    # The engine combines these with conftest/module providers per unit; a
    # file-wide flattened map cannot express a class-local override or the
    # parent-fixture chain behind ``def fixture_name(fixture_name)``.
    standin_fixture_layers: tuple[
        tuple[str, dict[str, tuple[str, ...]], tuple[str, ...]], ...
    ] = field(
        default=(),
        repr=False,
        compare=False,
        kw_only=True,
        metadata={"internal": True},
    )
    # Stand-ins this unit installs: (dotted target, patched attribute), sorted.
    # `monkeypatch.setattr`, `mock.patch`, `patch.object`, `mocker.patch` —
    # every dialect flattened to the same pair, because a rule that knows one
    # spelling is a rule the next agent spells around.
    #
    # Collected unfiltered. Whether a target is the repo's own code is a
    # question about the *diff*, not about this file, so the judgement lives in
    # the detector where `DiffGlobals` is in reach.
    patches: tuple[tuple[str, str], ...] = ()
    # Names bound more than once whose bindings are pairwise branch-exclusive —
    # every one in a different arm of the same `if`/`elif`/`else` (or `match`)
    # chain, so at most one of them executes on any path. `bindings` joins the
    # definitions but flattens the control flow, and the difference is load-
    # bearing: a version-gated alternative golden (`if sys.version_info >=
    # (3, 13): expected = new` / `else: expected = old`) keeps the old oracle
    # alive on the path that had it, while the same two definitions on a
    # straight line are a rebind where the last one wins at the assertion.
    # rich c8abbb3bd2 (adjudicated false positive, 2026-08-25) is the first
    # shape; the guard that spares it must not spare the second.
    exclusive_bindings: tuple[str, ...] = ()

    @property
    def disabled(self) -> bool:
        return bool(self.markers)


@dataclass
class AssertionPair:
    before_id: str
    after_id: str
    strength_change: int | None  # None when either side is unclassifiable
    # True when the pair came from the order fallback rather than from
    # matching text or matching (form, subject). A fallback pair is a guess:
    # two leftover assertions of compatible strength, paired by position and
    # nothing else. ASSERT_SUBSTITUTED exists because that guess reported
    # `strength_change: 0` for a deleted assertion whose slot a different one
    # had taken (THREATMODEL 84b).
    fallback: bool = False


@dataclass
class UnitDelta:
    assertion_pairs: list[AssertionPair] = field(default_factory=list)
    assertions_removed: list[str] = field(default_factory=list)  # before-side assertion ids
    assertions_added: list[str] = field(default_factory=list)  # after-side assertion ids
    markers_added: list[str] = field(default_factory=list)
    handlers_widened: list[str] = field(default_factory=list)
    tolerance_changes: list[tuple[str, str, str]] = field(default_factory=list)  # (kind, before, after)
    param_cases_removed: int = 0  # parametrized cases deleted (pytest test items)
    # Skips whose condition text never changed but whose *meaning* did,
    # because a constant it names was edited: `STRICT = True` -> `False`
    # under `if not STRICT: pytest.skip(...)` silences the test with no
    # marker event at all (decoy probe arm 2026-08-04). Entries are marker
    # names, matched to the after side.
    guards_weakened: list[str] = field(default_factory=list)


@dataclass
class Unit:
    kind: str  # "test_function"
    qualname: str
    match: str | None  # by_name | by_fingerprint | None (one-sided)
    before: UnitSide | None
    after: UnitSide | None
    delta: UnitDelta | None


@dataclass
class FileIR:
    path: str
    language: str  # "python" | "unknown"
    role: str
    status: str  # added | modified | deleted
    units: list[Unit] = field(default_factory=list)
    alignment: str = "full"  # "full" | "degraded"
    parse_ok: bool = True
    # Canonical local import binding -> target path on the selected file side.
    # Internal only: adding this analysis cache must not mutate emitted IR v1.
    standin_imports: dict[str, str] | None = field(
        default=None,
        repr=False,
        compare=False,
        kw_only=True,
        metadata={"internal": True},
    )
    # Constant environment for D6 on this file's skip conditions: name ->
    # defining expression source. Merged by the engine from the file's own
    # module-level constants plus names imported from files it can read
    # (in-diff first, then the head snapshot), so gating stays a pure
    # function of the IR. Keys are inserted in sorted order.
    constants: dict[str, str] = field(default_factory=dict)
    # The same environment resolved against this file's BASE side, so a
    # constant edit under an unchanged guard can be compared (GUARD_WEAKENED).
    constants_before: dict[str, str] = field(default_factory=dict)
    # Same-file top-level constant name -> canonical (ast.unparse) defining
    # expression, on each side. NOT the merged D6 environment above: that one
    # resolves cross-file with a head reader on the after side only, and an
    # asymmetric environment must never feed a two-sided comparison. These two
    # are the file's own module scope, both sides, canonicalized the same way
    # — the fourth expectation source for EXPECTATION_DEFINITION_CHANGED
    # (THREATMODEL 86a's largest blind bucket, 29.2% of the census; D-051).
    # Top-level rebinds are last-wins on both sides, which is module
    # execution order.
    module_constants: dict[str, str] = field(default_factory=dict)
    module_constants_before: dict[str, str] = field(default_factory=dict)
    # Same-file `@pytest.fixture` name -> canonical text of what it returns or
    # yields. A fixture is not a collected unit, so without this an expectation
    # supplied by one is invisible. Conftest fixtures are out of scope.
    fixture_defs: dict[str, str] = field(default_factory=dict)
    fixture_defs_before: dict[str, str] = field(default_factory=dict)
    # Same-file helper name -> callee leaves. Repair evidence follows one
    # hop through a helper the unit actually invokes (T1.9).
    helper_calls: dict[str, tuple[str, ...]] = field(default_factory=dict)


@dataclass
class DiffGlobals:
    prod_files_changed: list[str] = field(default_factory=list)
    prod_symbols_changed: list[str] = field(default_factory=list)  # non-trivial only
    # Symbols that existed at base and are gone at head, in modified prod
    # files. Feature removal explains a deleted test the way a modified
    # symbol explains an edited expectation (PROD_SYMBOL_REMOVED).
    prod_symbols_deleted: list[str] = field(default_factory=list)
    # Callers of changed prod symbols, for one-hop repair evidence:
    # {caller leaf name: [changed symbol leaf names it calls]}.
    prod_symbol_callers: dict[str, list[str]] = field(default_factory=dict)
    # A changed prod file checkwash cannot reason about (non-Python, deleted,
    # or unparseable). Conservatively suppresses E1 — see THREATMODEL #4.
    prod_opaque_change: bool = False
    # Top-level packages/modules of changed prod files, and what each test
    # file imports. Symbol-level evidence is confined to files the diff
    # touched, so any indirection through an unchanged module breaks it —
    # which is why httpx's URL-parser commits blocked (SPEC §5).
    prod_packages: list[str] = field(default_factory=list)
    test_file_imports: dict[str, list[str]] = field(default_factory=dict)
    new_literals_in_prod: list[str] = field(default_factory=list)  # repr() of constants
    # Literals already present on the base side of any changed file. A value
    # that already existed in the codebase is not a hardcode fingerprint,
    # however new its latest occurrence looks (dogfood-found false positive).
    base_literals: list[str] = field(default_factory=list)
    guardrail_files_changed: list[str] = field(default_factory=list)
    # Guardrail files this diff *created*. A constraint that did not
    # exist has not been relaxed, and treating creation as relaxation
    # made checkwash's own installer produce a critical block (field
    # integration 2026-08-07).
    guardrail_files_created: list[str] = field(default_factory=list)
    ci_files_changed: list[str] = field(default_factory=list)
    ci_weakening_lines: list[tuple[str, str]] = field(default_factory=list)  # (path, line)
    snapshot_files_changed: list[str] = field(default_factory=list)
    test_logic_changed: bool = False  # any test-role unit delta or one-sided unit
    imports_added: list[str] = field(default_factory=list)  # "path:module"
    unresolved_imports: list[tuple[str, str]] = field(default_factory=list)  # (path, module)
    suppressions_added: list[str] = field(default_factory=list)  # "path:text"
    broad_excepts_added: list[tuple[str, str]] = field(default_factory=list)  # (path, text)
    # Test/conftest files checkwash could not parse: (path, parsed_before?).
    unparseable_tests: list[tuple[str, bool]] = field(default_factory=list)
    hidden_unicode: list[tuple[str, str, str]] = field(default_factory=list)  # (path, codepoint, escaped line)
    exemptions_added: list[str] = field(default_factory=list)  # fingerprints appended in head allow.toml
    exemption_ledger_path: str = ".greenwash/allow.toml"  # the ledger those fingerprints were appended to
    guardrail_configs_created_loosening: list[str] = field(default_factory=list)  # created own config that disables a detector or raises fail_on (issue #79)
    scope_allow: list[str] = field(default_factory=list)  # contract globs ([] = SCOPE_DRIFT off)
    scope_drift: list[tuple[str, str]] = field(default_factory=list)  # (path, role)
    moved_assertion_texts: list[str] = field(default_factory=list)  # normalized, sorted
    # Body hashes of disappeared units that reappear verbatim as live added
    # units — the whole-unit form of the D2 move credit, and the only form an
    # assertion-less unit can earn. Multiset, spent like the texts above.
    moved_unit_hashes: list[str] = field(default_factory=list)
    # Body hashes of disappeared units whose identical, live copy exists at
    # head in a file the diff never touched (click 1103c5cac2: the deleted
    # test was a duplicate; the survivor still runs). A set, not a multiset:
    # one live survivor covers any number of identical deletions.
    duplicate_unit_hashes: list[str] = field(default_factory=list)
    # A dependency manifest (pyproject, requirements, lockfiles) changed in
    # this diff — the honest cause of expectation drift like httpx 0.28's
    # compact JSON separators (DEPENDENCY_DRIFT, EXPECTED_VALUE_CHANGED only).
    dependency_manifest_changed: bool = False
    # New conftest module/fixture/hook stand-ins that a live test oracle
    # actually reaches: (path, text). Replacing the code under test makes the
    # oracle assert against a stand-in while prod and tests stay byte-identical
    # (decoy probe arm 2026-08-04).
    conftest_prod_patches: list[tuple[str, str]] = field(default_factory=list)
    # Reachability/lifetime-refined conftest events for the current engine.
    # `None` means an older/external IR that has only the v1 field above;
    # `[]` means the richer pass ran and found no effective event.  Keeping
    # this private preserves `conftest_prod_patches`'s original raw-call
    # meaning and serialized shape.
    conftest_standin_patches: list[tuple[str, str]] | None = field(
        default=None,
        repr=False,
        compare=False,
        kw_only=True,
        metadata={"internal": True},
    )
    # Import roots that the manifests declare as *someone else's* code, sorted.
    #
    # Declared dependencies minus the project's own name, and the second half
    # of that sentence is the whole point: `parse_manifest` folds `project.name`
    # in with the dependencies on purpose, so "declared" alone would have
    # classified `flask` as third-party inside flask — a first-party check that
    # denies the first party, dead in exactly the six repos it is measured on.
    # Empty when no manifest was read, which leaves the stdlib list as the only
    # deny and is deliberately the quieter half of the error.
    third_party_roots: tuple[str, ...] = ()
    # Import roots positively tied to this repository: base-manifest project
    # names, production paths in the diff, or readable modules in the head
    # snapshot. A manifest-declared dependency cannot become local from the
    # readable-path probe alone. Unknown absolute roots are not first-party by
    # subtraction.
    first_party_roots: tuple[str, ...] = field(
        default=(),
        repr=False,
        compare=False,
        kw_only=True,
        metadata={"internal": True},
    )


@dataclass
class IR:
    base: str
    head: str
    files: list[FileIR] = field(default_factory=list)
    globals: DiffGlobals = field(default_factory=DiffGlobals)
    skipped_files: list[str] = field(default_factory=list)
    version: int = IR_VERSION


def to_jsonable(obj: Any) -> Any:
    """Dataclass tree → plain JSON-serializable structure (tuples become lists)."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {
            f.name: to_jsonable(getattr(obj, f.name))
            for f in dataclasses.fields(obj)
            if not f.metadata.get("internal")
        }
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(x) for x in obj]
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    return obj


def normalize_text(text: str) -> str:
    """Normal form for pairing, moves and fingerprints.

    Strips whitespace *outside* string literals only: whitespace inside a
    quoted string is semantics, and erasing it would let a relocated
    assertion with a silently edited expected value count as "moved
    verbatim" (SPEC §5 D2 — confirmed red-team finding).
    """
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch in "\"'":
            quote = ch * 3 if text[i : i + 3] == ch * 3 else ch
            out.append(quote)
            i += len(quote)
            while i < n:
                if text[i] == "\\" and len(quote) == 1 and i + 1 < n:
                    out.append(text[i : i + 2])
                    i += 2
                    continue
                if text.startswith(quote, i):
                    out.append(quote)
                    i += len(quote)
                    break
                out.append(text[i])
                i += 1
        elif ch.isspace():
            i += 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)

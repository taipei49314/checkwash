"""IR data model (SPEC: greenwash_ir_version 1).

Detectors consume this and nothing else. All ordering inside the IR is
explicit and deterministic; no dict/set iteration order leaks into output.
Spans are character offsets into CRLF→LF-normalized source (SPEC §8).
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any

from greenwash import IR_VERSION


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
    # Stand-ins this unit installs: (dotted target, patched attribute), sorted.
    # `monkeypatch.setattr`, `mock.patch`, `patch.object`, `mocker.patch` —
    # every dialect flattened to the same pair, because a rule that knows one
    # spelling is a rule the next agent spells around.
    #
    # Collected unfiltered. Whether a target is the repo's own code is a
    # question about the *diff*, not about this file, so the judgement lives in
    # the detector where `DiffGlobals` is in reach.
    patches: tuple[tuple[str, str], ...] = ()

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
    # Constant environment for D6 on this file's skip conditions: name ->
    # defining expression source. Merged by the engine from the file's own
    # module-level constants plus names imported from files it can read
    # (in-diff first, then the head snapshot), so gating stays a pure
    # function of the IR. Keys are inserted in sorted order.
    constants: dict[str, str] = field(default_factory=dict)
    # The same environment resolved against this file's BASE side, so a
    # constant edit under an unchanged guard can be compared (GUARD_WEAKENED).
    constants_before: dict[str, str] = field(default_factory=dict)
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
    # A changed prod file greenwash cannot reason about (non-Python, deleted,
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
    # made greenwash's own installer produce a critical block (field
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
    # Test/conftest files greenwash could not parse: (path, parsed_before?).
    unparseable_tests: list[tuple[str, bool]] = field(default_factory=list)
    hidden_unicode: list[tuple[str, str, str]] = field(default_factory=list)  # (path, codepoint, escaped line)
    exemptions_added: list[str] = field(default_factory=list)  # fingerprints appended in head allow.toml
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
    # Conftest fixtures that monkeypatch a first-party target: (path, text).
    # Replacing the code under test from a fixture makes the oracle assert
    # against a stand-in while prod and tests both stay byte-identical
    # (decoy probe arm 2026-08-04).
    conftest_prod_patches: list[tuple[str, str]] = field(default_factory=list)
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
        return {f.name: to_jsonable(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
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

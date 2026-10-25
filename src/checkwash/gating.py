"""Severity gating: the escalator/de-escalator table from SPEC §5.

This file IS the auditable policy. Applied in order: D2, E1, E2, D1, D3.
(D2 first because a moved assertion is conclusively benign and skips
escalation entirely; the SPEC table remains the authority on semantics.)
"""

from __future__ import annotations

import ast
import collections
import datetime
import operator

from checkwash.allowlist import AllowEntry, active_fingerprints
from checkwash.ci_control_flow import became_unanalysable
from checkwash.config import SEVERITY_ORDER, Config
from checkwash.contract import Contract
from checkwash.findings import SHAPE_GUARD_WEAKENED, SHAPE_INERT_MARK, SHAPE_MARKER_ADDED, Finding
from checkwash.compat import compat_gate_for, guard_always_skips, guard_can_be_false, unit_is_live
from checkwash.ir.astutil import dotted_name as _dotted_name
from checkwash.ir.markers import bare_names, marker_call, parse_expr
from checkwash.ir.model import IR, Assertion, Unit, UnitSide, judged_as_test, normalize_text
from checkwash.roles import _is_inert
ORACLE_RULES = {
    "ASSERT_REMOVED",
    # A different assertion in a deleted one's slot. The lattice reports it
    # as unchanged because the order fallback paired them (THREATMODEL 84b).
    "ASSERT_SUBSTITUTED",
    "ASSERT_WEAKENED",
    "TEST_DISABLED",
    "TOLERANCE_LOOSENED",
    "EXPECTED_VALUE_CHANGED",
    # The expectation replaced by a recomputation of the subject's own inputs.
    # Same family as EXPECTED_VALUE_CHANGED and legitimate for the same reason
    # — production may genuinely have changed under it — so it takes the same
    # repair-evidence path rather than escalating on its own (THREATMODEL 84a).
    "EXPECTED_VALUE_DERIVED",
    # The same edit seen from the other side of the `==`: the expected value
    # and the strength are untouched and the subject is wrapped until the
    # buggy output passes. Routine when production changed under it, which
    # is exactly what repair evidence measures.
    "SUBJECT_NORMALIZED",
    # The expectation and the operator are untouched and the subject's
    # *input data* changed, so the bug is no longer exercised (issue #93).
    # Routine when production changed under it — same repair-evidence path.
    "SUBJECT_INPUT_CHANGED",
    # E3 used to escalate this unconditionally, which blocked the single most
    # common honest repair there is: change a constant, update its test.
    # It goes through repair evidence like every other oracle rule.
    "EXPECTED_VALUE_HARDCODED",
    # Patching the code under test from a conftest fixture is an oracle
    # event: the assertions still run, against a stand-in.
    "CONFTEST_PATCHES_PROD",
    # The same swap one scope lower, inserted under an assertion that already
    # existed. Legitimate when production moved under the test, which is what
    # repair evidence measures — so it takes the same path, not its own.
    "TEST_PATCHES_SUBJECT",
    # The expectation's *definition* moved while the assertion line stayed
    # byte-identical (THREATMODEL 86a). Shipped at info in v0.1.19 because the
    # promotion sweep cost twelve blocks; the credit rounds (T1.9 helper hop
    # and D9, T1.10 producer filters, T1.11 literal needles, PACKAGE_REPAIR
    # under D-037) closed those one evidence class at a time, and the
    # 2026-08-25 re-sweep on this tree costs five — each adjudicated and named
    # in benchmarks/adjudication-2026-08-25.json, none judged a defensible
    # block, inside the written line of five (D-048).
    "EXPECTATION_DEFINITION_CHANGED",
}

# The rules whose finding in a Python test or conftest refuses the
# opaque-change credit (see apply_gates). This broad set remains empty.
# A separate condition below refuses this credit for Python findings with
# BROAD_EXCEPT_ADDED and no unit, in files judged as tests or conftest.
# Other findings retain D-171, including the D-028 suite-control exception.
# The original broad refusal (ruling Q1 (b), 2026-10-14:
# ASSERT_REMOVED, ASSERT_WEAKENED, TEST_DISABLED, TOLERANCE_LOOSENED and
# BROAD_EXCEPT_ADDED) fired its pre-registered stop in the v0.9.0 combined
# sweep and is turned off (D-171). #419 stays open for a redesign.
OPAQUE_REFUSED_RULES: frozenset[str] = frozenset()

# Report order: most severe rule classes first within a path.
RULE_ORDER = [
    "EXEMPTION_ADDED",
    "GUARDRAIL_TOUCHED",
    "HIDDEN_UNICODE",
    "TEST_FILE_UNPARSEABLE",
    "ASSERT_REMOVED",
    "ASSERT_SUBSTITUTED",
    "ASSERT_WEAKENED",
    "TEST_DISABLED",
    "CONFTEST_PATCHES_PROD",
    "TEST_PATCHES_SUBJECT",
    "TOLERANCE_LOOSENED",
    "EXPECTED_VALUE_HARDCODED",
    "EXPECTED_VALUE_CHANGED",
    "EXPECTED_VALUE_DERIVED",
    "EXPECTATION_DEFINITION_CHANGED",
    "SUBJECT_NORMALIZED",
    "SUBJECT_INPUT_CHANGED",
    "SNAPSHOT_CODE_COCHANGE",
    "CI_WORKFLOW_TOUCHED",
    "BROAD_EXCEPT_ADDED",
    "SUPPRESSION_ADDED",
    "IMPORT_UNRESOLVED",
    "SCOPE_DRIFT",
]


def _unit_index(ir: IR) -> dict[tuple[str, str], Unit]:
    index: dict[tuple[str, str], Unit] = {}
    for file in ir.files:
        for unit in file.units:
            index[(file.path, unit.qualname)] = unit
    return index


def _module_alignment(module: str, imports: list[str]) -> int:
    """The longest aligned component prefix between `module` and any import.

    `_module_reachable` answers the same question at depth >= 1; the symbol
    matcher additionally needs to know HOW aligned the reach was, because a
    root-level import (`from app import billing`) reaches every module in
    the package at depth 1 — and depth 1 is also exactly how much two
    unrelated sibling modules share.
    """
    if not module:
        return 99  # a top-level module file: any import reaches it, as ever
    mod = [c for c in module.split(".") if c]
    best = 0
    for imp in imports:
        want = [c for c in imp.split(".") if c]
        if not want:
            continue
        for start in range(len(mod)):
            tail = mod[start:]
            overlap = min(len(tail), len(want))
            if tail[:overlap] == want[:overlap] and overlap > best:
                best = overlap
    return best


def _module_reachable(module: str, imports: list[str]) -> bool:
    """Could a test importing `imports` be reaching into `module`?

    Compared on dotted *components*, and against every suffix of the changed
    module, not on the raw string. checkwash derives a module name from a file
    path, so a source root that is not itself importable — `src/`, `lib/`,
    `python/` — is part of the derived name and nothing a test imports can
    ever match it. Literal comparison therefore denied repair evidence to
    every src-layout project in the corpus; the identical diff passed without
    a `src/` directory and blocked with one (reader audit 2026-08-02).

    Still strict where it has to be: `pkg.module_a` and `pkg.module_b` share a
    package, but no suffix of one aligns with the other, so the same-package
    collision (bypass #35) is refused exactly as before.
    """
    return _module_alignment(module, imports) >= 1


def _symbol_match(
    calls: tuple[str, ...], changed_symbols: list[str], imports: list[str] | None = None
) -> bool:
    """Does the test call a symbol the diff actually changed?

    Entries are `module::qualname`. Matching on the leaf name alone let
    `module_a.calculate` supply repair evidence for a test that calls
    `module_b.calculate` — a same-name collision in an unrelated module
    (confirmed bypass). The changed symbol's module must also be reachable
    from what this test file imports.

    Reachable at depth 1 is not enough for a leaf-name hit (D-046, audit
    2026-08-19): a root-level import (`from app import billing`) reaches
    every module in the package, so `app.util::calculate` paid for a test of
    `app.billing.calculate` with one dead edit in a sibling — bypass #35's
    shape, reopened through the reachability fix that closed it. A leaf hit
    now additionally needs either a two-component alignment, or a dotted
    call whose first component IS the changed module's leaf — the honest
    root-import shape (`from app import billing; billing.calculate()` and
    the diff changes `app.billing::calculate`) keeps its credit through the
    second clause. Full-qual matches are unchanged. Stated residual: an
    aliased root import (`from app import billing as b; b.calculate()`)
    loses the second clause and reads as no evidence — visible at warn,
    allowlistable, and priced below reopening the sibling hole.
    """
    call_set = set(calls)
    for entry in changed_symbols:
        module, _, qual = entry.rpartition("::")
        leaf = qual.rsplit(".", 1)[-1]
        qual_hit = qual in call_set
        leaf_hit = leaf in call_set
        if not qual_hit and not leaf_hit:
            continue
        # No import information (unparsed test file): fall back to the old,
        # more permissive behaviour rather than inventing evidence either way.
        if imports is None:
            return True
        if qual_hit and _module_reachable(module, imports):
            return True
        if leaf_hit and (
            _module_alignment(module, imports) >= 2
            or any(
                "." in c and c.split(".")[0] == module.rsplit(".", 1)[-1]
                for c in call_set
            )
        ):
            return True
    return False


def _package_evidence(path: str, ir: IR) -> bool:
    """Did the diff change production code in a package this test imports?

    Weaker than symbol-level evidence on purpose, and used for exactly one
    rule (see apply_gates). Symbol evidence cannot see through an unchanged
    intermediate module — a test calling `httpx.URL(...)` gets no credit when
    the diff fixes `httpx/_urlparse.py` — and that single blind spot produced
    13 of httpx's 20 blocked commits in the 1800-commit sweep.

    A test-only diff has no changed prod package at all, so this cannot
    excuse the cheat the rule exists to catch.
    """
    changed = ir.globals.prod_packages
    if not changed:
        return False
    imports = list(ir.globals.test_file_imports.get(path, ()))
    if not imports:
        return False
    # Module reachability, not top-level-package equality: a test importing
    # `pkg.module_b` earned evidence from a change to `pkg.module_a` merely
    # because they share `pkg` (confirmed bypass). A test importing `httpx`
    # still reaches `httpx._urlparse`, which is what this rule is for.
    return any(_module_reachable(module, imports) for module in changed)


def _prod_removal_shape(f: Finding, unit: Unit | None) -> bool:
    """Only the removal shapes of TEST_DISABLED are eligible for the
    PROD_SYMBOL_REMOVED compensation: a unit that disappeared outright, or
    parametrize rows that left. A disabling marker added to a *live* test is
    the cheat this rule exists to catch, and stays out. One unit can carry
    both events at once, so this reads Finding.shape, never the English
    message (E2 / review 2026-08-11 Issue 3).
    """
    if unit is None:
        return False
    if unit.after is None and unit.before is not None:
        return True
    return (
        unit.delta is not None
        and unit.delta.param_cases_removed > 0
        and f.shape != SHAPE_MARKER_ADDED
    )


def _prod_symbol_removed(path: str | None, ir: IR) -> bool:
    """Did this diff delete an existing prod symbol the test file can reach?

    Feature removal is the honest twin of test deletion: the deprecation shim
    goes and its test goes with it (starlette 856c904a6d, b133ab45ad; httpx
    59914c7690; attrs 74007f67d2). Symbol-level evidence cannot connect them —
    the deleted test touched the symbol through an attribute access or not at
    all — so the credit is import-reachability against symbols that existed
    at base and are gone at head. Additions prove nothing (new code explains
    no deletion), and the compensation holds at warn, visible. The residual —
    deleting a dead prod symbol to escort a test deletion — is documented in
    THREATMODEL rather than papered over.
    """
    deleted = ir.globals.prod_symbols_deleted
    if not deleted or not path:
        return False
    imports = list(ir.globals.test_file_imports.get(path, ()))
    # `tests/test_status.py` testing `starlette/status.py` through
    # `importlib.import_module("starlette.status")` has no static import to
    # connect the two (starlette b133ab45ad). The naming convention is the
    # remaining honest signal, accepted only for this rule and only for the
    # two standard spellings.
    stem = path.rsplit("/", 1)[-1].removesuffix(".py")
    if stem.startswith("test_"):
        stem = stem[len("test_"):]
    elif stem.endswith("_test"):
        stem = stem[: -len("_test")]
    else:
        stem = ""
    for entry in deleted:
        module = entry.rpartition("::")[0]
        if imports and _module_reachable(module, imports):
            return True
        if stem and module.rsplit(".", 1)[-1] == stem:
            return True
    return False


def _file_repair_evidence(path: str, ir: IR, *, opaque: bool = True) -> bool:
    """Repair evidence for a finding with no unit of its own.

    Deliberately narrow: ONLY the opaque-change fallback applies. Asking
    whether *any* unit in the file had evidence let an unrelated
    `except AssertionError: pass` ride on a sibling test's legitimate repair
    (confirmed bypass). A file-scoped finding earns nothing from a unit it is
    not in.

    `opaque=False` refuses that one credit, so such a finding has no evidence
    at all: a broad except added in a Python test or conftest (#419). The
    opaque-change fallback was the only route it ever had.
    """
    return opaque and ir.globals.prod_opaque_change


def _finding_via(f: Finding, unit: Unit | None) -> str | None:
    """The helper method a finding's assertion was reached through (#306), or None.

    An assertion finding cites its assertion's span on one side; one reached
    through `self.<method>()` carries the method's class-qualified name.
    """
    if unit is None:
        return None
    for evidence, side in ((f.before, unit.before), (f.after, unit.after)):
        if evidence is None or side is None:
            continue
        for a in side.assertions:
            if a.via is not None and a.span == evidence.span:
                return a.via
    return None


def _finding_assertion(f: Finding, unit: Unit | None) -> Assertion | None:
    """The before half of the assertion a finding is about (#471), or None.

    An assertion finding cites its assertion's text and span. One that cites
    its before side names that assertion (for ASSERT_REMOVED, the removed
    one). One that cites only its after side (EXPECTED_VALUE_HARDCODED) is
    about a paired, edited assertion, whose before half is its pair's. A
    finding whose cited evidence is no assertion of the unit (a unit gone,
    TEST_PATCHES_SUBJECT, a tolerance change cited by its unit's span) has
    none, and neither has a unit with no before side.
    """
    if unit is None or unit.before is None:
        return None
    if f.before is not None:
        return next(
            (a for a in unit.before.assertions if a.span == f.before.span and a.text == f.before.text), None
        )
    if f.after is None or unit.after is None or unit.delta is None:
        return None
    after = next(
        (a for a in unit.after.assertions if a.span == f.after.span and a.text == f.after.text), None
    )
    if after is None:
        return None
    pair = next((p for p in unit.delta.assertion_pairs if p.after_id == after.id), None)
    if pair is None:
        return None
    return next((a for a in unit.before.assertions if a.id == pair.before_id), None)


def _fixture_producer_evidence(assertion: Assertion | None, side: UnitSide | None, ir: IR) -> bool:
    """Ruling 471: the producer of a fixture this assertion reads counts as a call of the test.

    `assertion` is the before half of the finding's assertion and `side` the
    unit's before side, whose fixtures were resolved one level deep, as
    pytest resolves them, from the module and the conftest chain as they
    were before the diff (`UnitSide.fixture_producers`). Only a fixture the
    assertion reads (`Assertion.fixture_reads`) counts (471 Q3 (b)). Its
    producer, the call it returns or yields, is matched as a call of the
    test is (`_symbol_match`, D-046), against the modules that the import
    binding the callee's root names in the fixture's own file, not the test
    file's imports: a test that gets its subject from a fixture may import
    nothing from the package. Neither the one-hop callers route nor the
    T1.9 helper hop is followed from a producer.
    """
    if assertion is None or side is None or not assertion.fixture_reads:
        return False
    reads = set(assertion.fixture_reads)
    for param, callee, modules in side.fixture_producers:
        if param in reads and _symbol_match(
            (callee, callee.rsplit(".", 1)[-1]), ir.globals.prod_symbols_changed, list(modules)
        ):
            return True
    return False


def _repair_evidence(
    unit: Unit | None,
    ir: IR,
    path: str | None = None,
    *,
    via_helper: bool = True,
    opaque: bool = True,
    via: str | None = None,
    assertion: Assertion | None = None,
) -> bool:
    """Did production change in a way that plausibly explains editing THIS test?

    Diff-global "some prod file changed" was the old test, and one dead line
    in any prod file disarmed the whole run (confirmed red-team finding).
    Evidence is now symbol-relevant: the test calls a changed symbol, or
    calls something that calls a changed symbol.

    `opaque=False` refuses the opaque-change fallback and leaves every
    symbol-level route below exactly as it is (#419: a weakening-class
    finding in a Python test or conftest; the caller decides).

    `assertion` is the before half of the finding's assertion
    (`_finding_assertion`), for the producer of a fixture it reads (#471);
    the caller passes none for TEST_DISABLED.
    """
    if opaque and ir.globals.prod_opaque_change:
        return True  # cannot reason about it — stay conservative, THREATMODEL #4
    if unit is None:
        return False
    side = unit.before or unit.after
    if side is None:
        return False
    imports = ir.globals.test_file_imports.get(path) if path else None
    if _symbol_match(side.calls, ir.globals.prod_symbols_changed, imports):
        return True
    if any(name in ir.globals.prod_symbol_callers for name in side.calls):
        return True
    # T1.9: one hop through a same-file helper the unit actually invokes.
    # Not for TEST_DISABLED — a deleted test plus a rewritten prod body is
    # the local-rewrite escort, not repair (prod_symbol_removed_local_rewrite).
    if via_helper and path:
        file = next((f for f in ir.files if f.path == path), None)
        if file is not None:
            invoked = set(side.invoked)
            for name in invoked:
                callees = file.helper_calls.get(name)
                if callees and _symbol_match(callees, ir.globals.prod_symbols_changed, imports):
                    return True
            # A helper method's callees, under its class-qualified name, are
            # evidence for the findings about assertions reached through it,
            # and for no other (306 Sub-Q8).
            if via is not None:
                callees = file.helper_calls.get(via)
                if callees and _symbol_match(callees, ir.globals.prod_symbols_changed, imports):
                    return True
    # The producer of a fixture the finding's before-side assertion reads, one
    # level deep (#471, ruling Q1 (c) to Q4 (a)).
    if _fixture_producer_evidence(assertion, unit.before, ir):
        return True
    return False


def _same_unit_rewrite(unit: Unit | None) -> bool:
    """The unit gained a NEWLY WRITTEN strong assertion alongside the removal.

    Triage cluster: private-API asserts rewritten against the public API,
    excinfo asserts folded into raises(match=...). "Newly written" is the
    load-bearing word: a unit that merely KEEPS an old assertion while the
    inconvenient one disappears is the sacrificial-cheat signature and must
    keep blocking. Compensated findings stay visible at warn.
    """
    if unit is None or unit.delta is None or unit.before is None or unit.after is None:
        return False
    if not unit.delta.assertions_removed:
        return False
    before_texts = {normalize_text(a.text) for a in unit.before.assertions}
    return any(_is_real_assertion(a) and a.via is None and normalize_text(a.text) not in before_texts
               for a in unit.after.assertions)


def _is_real_assertion(a) -> bool:
    """Strong enough to be an oracle, and capable of failing at all."""
    return a.strength is not None and a.strength >= 60 and not a.trivial


def _oracle_mass(side) -> int:
    # An assertion reached through a helper method neither earns a credit nor
    # adds a requirement (306 Sub-Q11).
    strong = sum(1 for a in side.assertions if _is_real_assertion(a) and a.via is None)
    return strong * max(1, side.param_cases or 1)


def _file_restructured(ir: IR, file_constants: dict[str, dict[str, str]]) -> dict[str, bool]:
    """path -> did the file's added live units replace its disappeared mass?

    Triage cluster: N tests merged into one parametrize, splits, in-file
    renames with rewrites. Oracle mass = strong assertions x parametrize rows;
    if what appeared covers what disappeared, disappearances hold at warn.
    """
    result: dict[str, bool] = {}
    for file in ir.files:
        if not judged_as_test(file):
            continue
        gone = added = 0
        for unit in file.units:
            if unit.before is not None and unit.after is None:
                gone += _oracle_mass(unit.before)
            elif (
                unit.after is not None
                and unit.before is None
                and unit_is_live(unit.after, file_constants.get(file.path))
            ):
                added += _oracle_mass(unit.after)
        if gone:
            result[file.path] = added >= gone
    return result


def _split_or_renamed(
    ir: IR, file_constants: dict[str, dict[str, str]]
) -> dict[tuple[str, str], bool]:
    """(path, qualname) -> was this disappeared unit split or renamed in place?

    Triage named the mechanism precisely: the vanished unit's name is a strict
    prefix of names added in the same file (a split), or vice versa (a merge),
    or the added name shares the vanished one's leading tokens (a rename with
    rewrite). The replacement must be LIVE and carry a real assertion, so
    renaming a test into a skipped stub does not qualify.

    A name relation alone is not enough, and neither is a file-wide mass
    check — that is exactly what D5 RESTRUCTURED already does, so requiring it
    here would make this rule redundant and would reject genuine one-into-two
    splits in files that also lost coverage elsewhere.

    The credit is therefore *per unit and spent*: each arriving unit's oracle
    mass can excuse related disappearances until it runs out. One weak
    survivor could previously excuse five deleted tests holding seven exact
    assertions, because every disappearance consulted the same single credit
    (reader audit 2026-08-02).
    """
    result: dict[tuple[str, str], bool] = {}
    for file in ir.files:
        if not judged_as_test(file):
            continue
        # leaf name -> remaining oracle mass this arrival can still vouch for
        budget: dict[str, int] = {}
        gone: list[tuple[str, str, int]] = []  # (qualname, leaf, mass)
        for unit in file.units:
            leaf = unit.qualname.rsplit(".", 1)[-1].split("#", 1)[0]
            if unit.before is not None and unit.after is None:
                gone.append((unit.qualname, leaf, _oracle_mass(unit.before)))
            elif unit.after is not None and unit.before is None:
                if not unit_is_live(unit.after, file_constants.get(file.path)):
                    continue
                if any(_is_real_assertion(a) and a.via is None for a in unit.after.assertions):
                    budget[leaf] = budget.get(leaf, 0) + _oracle_mass(unit.after)
        if not gone or not budget:
            continue
        # Deterministic order: smallest loss first, then by name, so the
        # outcome does not depend on file layout.
        for qualname, leaf, mass in sorted(gone, key=lambda g: (g[2], g[1])):
            related = sorted(
                new
                for new in budget
                if new.startswith(leaf + "_")
                or leaf.startswith(new + "_")
                or _shares_prefix(leaf, new)
            )
            available = sum(budget[new] for new in related)
            excused = bool(related) and available >= mass
            if excused:
                owed = mass
                for new in related:
                    spend = min(budget[new], owed)
                    budget[new] -= spend
                    owed -= spend
                    if not owed:
                        break
            result[(file.path, qualname)] = excused
    return result


def _shares_prefix(a: str, b: str, min_tokens: int = 3) -> bool:
    """Both names begin with the same >=3 underscore-separated tokens."""
    at, bt = a.split("_"), b.split("_")
    if len(at) < min_tokens or len(bt) < min_tokens:
        return False
    return at[:min_tokens] == bt[:min_tokens]


def apply_gates(
    ir: IR,
    findings: list[Finding],
    contract: Contract,
    config: Config,
    allow_entries: list[AllowEntry],
    today: datetime.date,
) -> str:
    """Mutates findings' severity/escalators in place; returns the verdict."""
    # The TEST_DISABLED detector keys a finding by its marker. Imported here:
    # the detectors import the frontends, which import this module.
    from checkwash.detectors.test_disabled import finding_marker

    # A multiset of credits: each ASSERTION_MOVED de-escalation spends one, so
    # two deletions cannot both be excused by a single re-appearance. Whole
    # units get the same treatment via their body hashes.
    moved = collections.Counter(ir.globals.moved_assertion_texts)
    moved_units = collections.Counter(ir.globals.moved_unit_hashes)
    duplicates = set(ir.globals.duplicate_unit_hashes)
    units = _unit_index(ir)
    active_allows = active_fingerprints(allow_entries, today)
    roles = {f.path: f.role for f in ir.files}
    judged_tests = {f.path for f in ir.files if judged_as_test(f)}
    # The frontend's own language call (`.py`, diffalign.align_file), read
    # from the IR so gating stays a pure function of it. A JS/TS test is
    # judged as a test too, and must not be mistaken for a Python one (#419).
    python_files = {f.path for f in ir.files if f.language == "python"}
    file_constants = {f.path: f.constants for f in ir.files}
    restructured = _file_restructured(ir, file_constants)
    split_renamed = _split_or_renamed(ir, file_constants)
    # Did the diff change a production-role file that can change runtime
    # behaviour? Only E1's label reads it (#473). The engine records each
    # production-role path of the diff (relocated test bytes aside) before
    # it decides whether to read symbols from the file, so a file that stops
    # parsing, a non-Python file added, deleted or renamed, and one whose
    # content runs the test suite are all in `prod_files_changed`. The inert
    # files (`roles._is_inert`: type stubs, docs-site and docs-build config,
    # repository metadata) change no runtime behaviour by the engine's own
    # list, so they do not count here. Generated artifacts and changes set
    # aside unread never reach `prod_files_changed` (#415).
    prod_changed = any(not _is_inert(path) for path in ir.globals.prod_files_changed)

    for f in findings:
        if f.fingerprint in active_allows:
            f.allowlisted = True
            f.deescalators.append("ALLOWLISTED")
            continue
        # A test file or a conftest: the one predicate behind both the broad
        # except below and the opaque refusal further down, so the two cannot
        # drift apart. #419 Q1 (b) refuses the credit in "Python test and
        # conftest files", which is this set (narrowed to Python below): the
        # set that makes BROAD_EXCEPT_ADDED an oracle rule.
        test_or_conftest = f.path in judged_tests or roles.get(f.path) == "conftest"
        # A broad except swallowing an assertion inside a test file IS oracle
        # tampering, whatever it would mean in production code (decoy run,
        # cache_invalidate).
        is_oracle = f.rule in ORACLE_RULES or (
            f.rule == "BROAD_EXCEPT_ADDED" and test_or_conftest
        )
        if not is_oracle:
            # Non-oracle escalations from the SPEC §5 table.
            if f.rule == "GUARDRAIL_TOUCHED":
                # E4, but only for a constraint that existed. Creating one has
                # relaxed nothing, and rating creation critical meant that
                # running `checkwash hook install --agent claude-code` and
                # committing the result — the two steps the README gives, in
                # the order it gives them — produced a blocking verdict on the
                # tool's own artefact (field integration 2026-08-07). Still
                # reported, at warn: a new `.cursorrules` is worth seeing.
                #
                # The exception is checkwash's own config (issue #79): with no
                # file the defaults were in force, so a created config.toml
                # that disables a detector or raises fail_on has relaxed a
                # constraint that existed. Read from the base side, that file
                # governs the *next* diff, and its creation was the only place
                # to catch the two-commit plant — at warn it never blocked.
                created = f.path in ir.globals.guardrail_files_created
                loosening = f.path in ir.globals.guardrail_configs_created_loosening
                if created and not loosening:
                    f.escalators.append("GUARDRAIL_CREATED")
                else:
                    f.severity = "critical"
                    f.escalators.append("META")
            elif f.rule == "HIDDEN_UNICODE":
                f.severity = "high"
                f.escalators.append("HIDDEN_CONTROL_CHARS")
            elif f.rule == "CI_WORKFLOW_TOUCHED" and any(
                path == f.path for path, _ in ir.globals.ci_weakening_lines
            ):
                # A file the reader took at base and declines at head has no
                # weakened command to name: its runners are out of reach, which
                # is its own escalator (#196 191.3).
                reasons = [line for path, line in ir.globals.ci_weakening_lines if path == f.path]
                f.severity = "high"
                if not all(became_unanalysable(line) for line in reasons):
                    f.escalators.append("CI_TEST_COMMAND_WEAKENED")
                if any(became_unanalysable(line) for line in reasons):
                    f.escalators.append("CI_BECAME_UNANALYSABLE")
            # A test file that parsed before this diff and does not parse now
            # has been taken out of checkwash's reach. A file that never
            # parsed (new, or newer syntax than the analyser) stays at warn:
            # loud, but not a block for choosing an older interpreter.
            elif f.rule == "TEST_FILE_UNPARSEABLE" and any(
                path == f.path and was_parseable
                for path, was_parseable in ir.globals.unparseable_tests
            ):
                f.severity = "high"
                f.escalators.append("TEST_BECAME_UNANALYSABLE")
            elif f.rule == "SCOPE_DRIFT" and any(
                path == f.path and role in ("prod", "ci", "guardrail")
                for path, role in ir.globals.scope_drift
            ):
                f.severity = "high"
                f.escalators.append("OUT_OF_SCOPE_PROD_TOUCH")
            continue

        unit = units.get((f.path, f.unit or ""))

        # A `pytestmark` in conftest.py disables nothing: pytest does not
        # collect conftest.py as a test module, so it never reads the mark.
        # The finding tells the reader so, at info, and nothing escalates it
        # (#209 Q3).
        if f.rule == "TEST_DISABLED" and f.shape == SHAPE_INERT_MARK:
            f.severity = "info"
            continue

        # D2 ASSERTION_MOVED: conclusively benign, skips escalation. Each
        # de-escalation *spends* a credit from the multiset.
        if f.rule == "ASSERT_REMOVED" and f.before is not None:
            key = normalize_text(f.before.text)
            if moved[key] > 0:
                moved[key] -= 1
                f.severity = "info"
                f.deescalators.append("ASSERTION_MOVED")
                continue
        if f.rule == "TEST_DISABLED" and unit is not None and unit.after is None and unit.before is not None:
            # The whole unit's normalized body reappearing as a live added
            # unit is the strongest form of "moved" — and the only one an
            # assertion-less smoke test can produce (click a391797d00,
            # test_echo_no_streams: nothing in the multiset to match).
            h = unit.before.body_hash
            if h and moved_units[h] > 0:
                moved_units[h] -= 1
                f.severity = "info"
                f.deescalators.append("ASSERTION_MOVED")
                continue
            # An identical live copy survives at head, outside the diff:
            # dedup, not a kill. Not spent — one survivor covers any number
            # of identical deletions, because it keeps running either way.
            if h and h in duplicates:
                f.severity = "info"
                f.deescalators.append("DUPLICATE_REMAINS")
                continue
            # What a disappeared unit needs moved is its own assertions: those
            # it reached through a helper method add no requirement (306 Sub-Q11).
            texts = [normalize_text(a.text) for a in unit.before.assertions if a.via is None]
            needed = collections.Counter(texts)
            if texts and all(moved[t] >= n for t, n in needed.items()):
                moved.subtract(needed)
                f.severity = "info"
                f.deescalators.append("ASSERTION_MOVED")
                continue

        # Materiality (ASSERT_WEAKENED only): a 10-point slide inside the
        # exact family (e.g. assertListEqual -> assertEqual on a variable) is
        # style drift, not oracle removal — the FP sweep blocked several such
        # human commits. Material = fell by >= 30, or left the exact family
        # (below EXACT_VALUE: landing on APPROX means a tolerance now exists
        # where an exact comparison used to be — the decoy run's most popular
        # cheat, never mild per THREATMODEL 13). Mild means "still exact":
        # 100 -> 90 within the exact family (D-047 aligned the SPEC text).
        # ...and the compared SUBJECT must be untouched. Wrapping both sides
        # in sorted() to make an ordered comparison order-insensitive is a
        # 100->90 slide too, but it is a rewrite of what is compared, not a
        # matcher style change (decoy run, sort_stability).
        mild_weakening = (
            f.rule == "ASSERT_WEAKENED"
            and (f.strength_drop or 0) < 30
            and f.strength_after is not None
            and f.strength_after >= 90
            and not f.subject_changed
        )

        # The disabling marker a TEST_DISABLED finding reports, or None (#208).
        marker = finding_marker(f, unit)

        # Compensation evidence from the triage clusters: all of these hold
        # the finding at warn (visible, allowlistable) instead of blocking.
        compensation = None
        # ASSERT_SUBSTITUTED joins ASSERT_REMOVED here on the same argument: a
        # unit that *deleted* an assertion and *wrote a new strong one* is
        # being rewritten wholesale, which is the documented triage cluster
        # (private-API asserts rewritten against the public API). Crediting the
        # removal at warn and blocking the substitution at high described one
        # edit two ways — httpx c7cd6aa5bdcf, "test obfuscate_sensitive_headers
        # via public api", was the measured case.
        #
        # It does not weaken what this rule was built for: `_same_unit_rewrite`
        # requires `assertions_removed` to be non-empty, and a pure substitution
        # removes nothing — the 2026-08-08 incident diff has
        # `assertions_removed: []` and stays high. Residual, stated: deleting an
        # assertion *and* substituting another *and* adding a plausible strong
        # one buys warn for all of it, which is the trade ASSERT_REMOVED has
        # carried since this compensation existed.
        if f.rule in ("ASSERT_REMOVED", "ASSERT_SUBSTITUTED") and _same_unit_rewrite(unit):
            compensation = "SAME_UNIT_REWRITE"
        elif (
            f.rule == "TEST_DISABLED"
            and unit is not None
            and unit.after is None
            and restructured.get(f.path)
        ):
            compensation = "RESTRUCTURED"
        elif (
            f.rule == "TEST_DISABLED"
            and unit is not None
            and unit.after is None
            and split_renamed.get((f.path, f.unit or ""))
        ):
            compensation = "SPLIT_OR_RENAMED"
        elif f.rule == "TEST_DISABLED" and compat_gate_for(unit, file_constants.get(f.path), marker):
            # D6 judges the marker the finding reports, not the unit it sits
            # on: an honest gate beside a new disable lent it its credit, on a
            # conftest's `<suite>` and on a test alike (#208).
            compensation = "COMPAT_GATE"
        elif (
            f.rule == "TEST_DISABLED"
            and _prod_removal_shape(f, unit)
            and _prod_symbol_removed(f.path, ir)
        ):
            compensation = "PROD_SYMBOL_REMOVED"

        # D-171 keeps the broad OPAQUE_REFUSED_RULES set empty. Only the
        # narrow file-scoped BROAD_EXCEPT_ADDED condition below is enabled.
        # The following historical broad design remains disabled for all
        # other rules; it is retained to explain the earlier experiment.
        #
        # A weakening-class finding in a Python test or conftest does not
        # take the opaque-change credit (#419, ruling Q1 (b), 2026-10-14).
        # Python test code reaches its subject through Python, and a Python
        # production change that explains the edit is read as symbol
        # evidence, which still applies to every finding that has a unit: a
        # direct call of a changed symbol and the one-hop callers route, and
        # the T1.9 same-file helper hop except for TEST_DISABLED, as does the
        # producer of a fixture the finding's assertion reads (#471).
        # BROAD_EXCEPT_ADDED is file-scoped and never had a unit. What this refuses
        # is the opaque-change route: one byte in a template, a C or Rust
        # file, a data file, a shell script that runs no tests, or a JS
        # module was the whole price of holding a weakened, removed or skipped
        # Python oracle at warn, and a broad except added around an assertion
        # had no other route.
        #
        # Kept, deliberately: a JS/TS test keeps the credit until the #212
        # corpus prices the change, because its production code is never
        # parsed and the credit is the only evidence it can earn. The rules
        # outside OPAQUE_REFUSED_RULES keep it in every language, and
        # PACKAGE_REPAIR and DEPENDENCY_DRIFT, the two credits that ask
        # `has_evidence`, never apply to these five rules. Every compensation
        # and MILD_WEAKENING is computed as before; a refused finding now
        # reaches them instead of stopping at REPAIR_EVIDENCE.
        #
        # For a conftest's `<suite>` control that means: an unguarded one
        # refused every repair evidence already (below). A guarded one (its
        # guard can be false) with only an opaque edit beside it is now held,
        # if at all, by its own D6 COMPAT_GATE: a `<suite>` unit calls
        # nothing, so it never had symbol evidence (D-066). A guarded
        # COLLECTION control (`collect_ignore`, the two collection hooks or an
        # `add_marker` skip: compat._SUITE_GATES) earns it on its guard alone,
        # so it is held by an `if` guard that can be false, and by the import
        # gate: a `try` body of plain imports (`import X` or
        # `from X import ...`) under `except ImportError` or
        # `except ModuleNotFoundError`, which the frontend records as
        # `find_spec("X") is None` (frontend `_handler_guard`,
        # `_IMPORT_ERRORS`). Any other `except` guard is recorded as the
        # exception text, which is no condition D6 can read: a bare `except`,
        # another exception class, a tuple of classes (even
        # `(ImportError, ModuleNotFoundError)`), a relative `from . import`,
        # or a `try` body that is not plain imports. A control under such a
        # guard still is not a suite control (its guard can be false), earns
        # no COMPAT_GATE, and now blocks beside an opaque edit.
        # That is the literal effect of Q1 (b), recorded by the 2026-10-16
        # ruling, and it amends the "only an unguarded control refuses repair
        # evidence" reading of D-088 / 209.Q4 for opaque evidence.
        #
        # A `conftest.runtime.*` control (an execution or report hook, an
        # exit-status control, a swapped `item.runtest`, a skipping fixture)
        # does not move. The frontend records no guard on it
        # (`_conftest_unit`; #84 and 432.Q5 hash a guard into the name
        # instead), so it is always read as unguarded: a suite control, which
        # refused every repair evidence before #419 and still does.
        #
        # Stated plainly, as the ruling asks: this catches an agent that
        # weakens a Python test beside an edit it was making anyway. One that
        # has read this rule moves to a rule that keeps the credit, or to a
        # kept no-op edit in a called function (Route A, THREATMODEL 93 as
        # widened by #419 Q3).
        refuses_opaque = (
            (
                f.rule in OPAQUE_REFUSED_RULES
                or (
                    f.rule == "BROAD_EXCEPT_ADDED"
                    and f.unit is None
                    and unit is None
                )
            )
            and f.path in python_files
            and test_or_conftest
        )
        # D1 REPAIR_EVIDENCE / E1 NO_PROD_CHANGE_IN_DIFF are two sides of one
        # question: is there a production change that explains this edit?
        has_evidence = (
            _file_repair_evidence(f.path, ir, opaque=not refuses_opaque)
            if unit is None
            else _repair_evidence(
                unit, ir, f.path,
                via_helper=f.rule != "TEST_DISABLED",
                opaque=not refuses_opaque,
                via=_finding_via(f, unit),
                # Every oracle rule that takes symbol evidence reads a
                # fixture's producer except TEST_DISABLED, as for the T1.9
                # hop (#471, ruling Q4 (a)).
                assertion=_finding_assertion(f, unit) if f.rule != "TEST_DISABLED" else None,
            )
        )
        package_only = (
            not has_evidence
            and f.rule in ("EXPECTED_VALUE_CHANGED", "EXPECTATION_DEFINITION_CHANGED")
            and _package_evidence(f.path, ir)
        )
        # An expectation literal tracking a dependency change: httpx 0.28
        # switched to compact JSON separators and every exact literal in the
        # corpus followed it (starlette 5ccbc62175, 100f05a66b).
        #
        # ASSERT_SUBSTITUTED joins it on corpus evidence: flask's two "bump
        # werkzeug 2.3.7" commits (5bb30270d2, 9f9550247a) rewrote
        # `assert rv.data == b"127.0.0.1"` into
        # `assert flask.g.remote_addr == "127.0.0.1"` because the dependency's
        # API moved under them. A version bump that changes behaviour changes
        # *how you reach* the value as often as it changes the value, so
        # crediting only the literal left the shape dependency bumps actually
        # produce blocking at high. The oracle is intact in both.
        #
        # Still scoped, exactly like PACKAGE_REPAIR: a manifest bump buys
        # nothing for a weakened or a deleted oracle, and both rules here
        # require unweakened strength. Residual: a substitution smuggled into
        # a genuine dependency bump gets the same credit — THREATMODEL 84c.
        dep_drift = (
            not has_evidence
            and not package_only
            and f.rule in (
                "EXPECTED_VALUE_CHANGED",
                "ASSERT_SUBSTITUTED",
                "EXPECTATION_DEFINITION_CHANGED",
            )
            and ir.globals.dependency_manifest_changed
        )
        # A production change never makes it correct to stop *collecting*
        # tests. Repair evidence answers "did production change, so this
        # expectation legitimately changed?" — a question a suite-level
        # collection control does not raise. On the 2026-08-07 probe arm an
        # agent dropped the failing tests out of collection and the honest
        # `scripts/lint.sh` edit its own task demanded paid for it, because
        # an unreadable prod file grants this credit diff-globally
        # (THREATMODEL row 68). A compatibility gate does explain it, and
        # still does: that branch is untouched below.
        #
        # Only when the control is **unguarded**. The first cut of this rule
        # asked nothing about the guard and blocked a PR that added a backend,
        # added its own tests, and gated them on `find_spec("redis")` — net
        # tests disabled: zero, production changed in three files, verdict
        # high (adversarial audit 2026-08-07, same day it shipped). A guard is
        # the difference between "these tests cannot run here" and "these
        # tests do not run any more".
        #
        # "Unguarded" is the finding's own control with no guard that can be
        # false: a guard that always holds is no guard (#209 Q4), and a gate
        # elsewhere in the conftest guards nothing here (#208). A finding
        # with no marker of its own reports a guard that now always fires,
        # or a path added to an unguarded control (row 81): either way its
        # control acts everywhere.
        after_markers = unit.after.markers if unit is not None and unit.after is not None else []
        own = [m for m in after_markers if marker is not None and m.name == marker]
        unguarded_control = (
            any(not guard_can_be_false(m.guard, file_constants.get(f.path)) for m in own)
            if own
            else f.shape == SHAPE_GUARD_WEAKENED
        )
        suite_control = (
            f.rule == "TEST_DISABLED"
            and roles.get(f.path) == "conftest"
            and (f.unit or "") == "<suite>"
            and unguarded_control
        )
        if has_evidence and not suite_control:
            f.deescalators.append("REPAIR_EVIDENCE")
        elif package_only:
            f.deescalators.append("PACKAGE_REPAIR")
        elif dep_drift:
            f.deescalators.append("DEPENDENCY_DRIFT")
        elif compensation is not None:
            f.deescalators.append(compensation)
        elif mild_weakening:
            f.deescalators.append("MILD_WEAKENING")
        else:
            f.severity = "high"
            # Say the true reason. Refusing repair evidence and then printing
            # "no production change in this diff" over a diff full of them is
            # a false statement in a blocking message, which is the class of
            # defect this project exists to catch (audit 2026-08-07).
            #
            # For a suite control the reason is a fact about the diff, not
            # about this finding's evidence. A `<suite>` unit calls nothing,
            # so a readable production edit elsewhere in the diff gives it no
            # symbol-matched evidence, and asking `has_evidence` printed the
            # false sentence over exactly that diff (#205). Any production
            # file changed: the control is unexplained. None: the old wording
            # is true.
            #
            # A refused opaque change is the same class of claim (#419 Q5 (b)):
            # the diff did change production, in a file checkwash reads but
            # cannot reason about, and that change is not accepted as this
            # finding's evidence. Still E1, so severity, verdict and
            # fingerprint are what they would be under the old wording; only
            # the sentence changes, as D-066's did. Not "unread": #448 uses
            # that word for a side that is never read at all, and such a side
            # never sets `prod_opaque_change`. A suite control keeps its own
            # label, which it always reaches first here: an opaque change is
            # a production file in `prod_files_changed`. D-171's broad set
            # remains empty. This label is reachable only for the separately
            # admitted Python unit-less BROAD_EXCEPT_ADDED condition, when
            # an opaque production change exists and the finding reaches E1.
            #
            # Every other finding here is the same class of claim (#473,
            # ruling Q2 and Q3, 2026-10-18). If the diff changed a
            # production-role file that is not inert (`prod_changed`, above),
            # production did change, and no evidence this finding may take
            # reached that change: no symbol it calls, no caller of one, no
            # helper hop, and no package or opaque credit where the rule
            # takes one. Nor did the producer of a fixture the finding's
            # assertion reads, the route #522 added for #471
            # (`_fixture_producer_evidence`). The usual cause is a reach
            # checkwash does not follow, such as an unchanged module between
            # the test and the change. `NO_PROD_CHANGE_IN_DIFF` is kept for a
            # diff that changes no production-role file, or only inert ones.
            # Still E1: severity is set above and the label is outside the
            # fingerprint, so only the sentence changes. Both labels before
            # this one keep their conditions and come first: a suite control
            # keeps D-066's test, inert files included, and a refused opaque
            # change keeps its own label.
            if suite_control and (has_evidence or ir.globals.prod_files_changed):
                reason = "COLLECTION_CONTROL_UNEXPLAINED"
            elif refuses_opaque and ir.globals.prod_opaque_change:
                reason = "OPAQUE_PROD_CHANGE_NOT_EVIDENCE"
            elif prod_changed:
                reason = "PROD_CHANGE_NOT_EVIDENCE"
            else:
                reason = "NO_PROD_CHANGE_IN_DIFF"
            f.escalators.append(reason)

        # E2 ORACLE_FREEZE
        if contract.oracle_freeze:
            f.severity = "high"
            f.escalators.append("ORACLE_FREEZE")

    threshold = SEVERITY_ORDER[config.fail_on]
    blocking = [
        f for f in findings if not f.allowlisted and SEVERITY_ORDER[f.severity] >= threshold
    ]
    return "block" if blocking else "pass"

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

from greenwash.allowlist import AllowEntry, active_fingerprints
from greenwash.config import SEVERITY_ORDER, Config
from greenwash.contract import Contract
from greenwash.findings import Finding
from greenwash.ir.markers import bare_names, marker_call, parse_expr
from greenwash.ir.model import IR, Unit, normalize_text

ORACLE_RULES = {
    "ASSERT_REMOVED",
    "ASSERT_WEAKENED",
    "TEST_DISABLED",
    "TOLERANCE_LOOSENED",
    "EXPECTED_VALUE_CHANGED",
    # E3 used to escalate this unconditionally, which blocked the single most
    # common honest repair there is: change a constant, update its test.
    # It goes through repair evidence like every other oracle rule.
    "EXPECTED_VALUE_HARDCODED",
}

# Report order: most severe rule classes first within a path.
RULE_ORDER = [
    "EXEMPTION_ADDED",
    "GUARDRAIL_TOUCHED",
    "HIDDEN_UNICODE",
    "ASSERT_REMOVED",
    "ASSERT_WEAKENED",
    "TEST_DISABLED",
    "TOLERANCE_LOOSENED",
    "EXPECTED_VALUE_HARDCODED",
    "EXPECTED_VALUE_CHANGED",
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


def _module_reachable(module: str, imports: list[str]) -> bool:
    """Could a test importing `imports` be reaching into `module`?

    Compared on dotted *components*, and against every suffix of the changed
    module, not on the raw string. greenwash derives a module name from a file
    path, so a source root that is not itself importable — `src/`, `lib/`,
    `python/` — is part of the derived name and nothing a test imports can
    ever match it. Literal comparison therefore denied repair evidence to
    every src-layout project in the corpus; the identical diff passed without
    a `src/` directory and blocked with one (reader audit 2026-08-02).

    Still strict where it has to be: `pkg.module_a` and `pkg.module_b` share a
    package, but no suffix of one aligns with the other, so the same-package
    collision (bypass #35) is refused exactly as before.
    """
    if not module:
        return True
    mod = [c for c in module.split(".") if c]
    for imp in imports:
        want = [c for c in imp.split(".") if c]
        if not want:
            continue
        for start in range(len(mod)):
            tail = mod[start:]
            overlap = min(len(tail), len(want))
            if tail[:overlap] == want[:overlap]:
                return True
    return False


def _symbol_match(
    calls: tuple[str, ...], changed_symbols: list[str], imports: list[str] | None = None
) -> bool:
    """Does the test call a symbol the diff actually changed?

    Entries are `module::qualname`. Matching on the leaf name alone let
    `module_a.calculate` supply repair evidence for a test that calls
    `module_b.calculate` — a same-name collision in an unrelated module
    (confirmed bypass). The changed symbol's module must also be reachable
    from what this test file imports.
    """
    call_set = set(calls)
    for entry in changed_symbols:
        module, _, qual = entry.rpartition("::")
        leaf = qual.rsplit(".", 1)[-1]
        if qual not in call_set and leaf not in call_set:
            continue
        # No import information (unparsed test file): fall back to the old,
        # more permissive behaviour rather than inventing evidence either way.
        if imports is None or _module_reachable(module, imports):
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
    the cheat this rule exists to catch, and stays out — discriminated on the
    finding message because one unit can carry both events at once.
    """
    if unit is None:
        return False
    if unit.after is None and unit.before is not None:
        return True
    return (
        unit.delta is not None
        and unit.delta.param_cases_removed > 0
        and "disabling marker added" not in f.message
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


def _file_repair_evidence(path: str, ir: IR) -> bool:
    """Repair evidence for a finding with no unit of its own.

    Deliberately narrow: ONLY the opaque-change fallback applies. Asking
    whether *any* unit in the file had evidence let an unrelated
    `except AssertionError: pass` ride on a sibling test's legitimate repair
    (confirmed bypass). A file-scoped finding earns nothing from a unit it is
    not in.
    """
    return ir.globals.prod_opaque_change


def _repair_evidence(unit: Unit | None, ir: IR, path: str | None = None) -> bool:
    """Did production change in a way that plausibly explains editing THIS test?

    Diff-global "some prod file changed" was the old test, and one dead line
    in any prod file disarmed the whole run (confirmed red-team finding).
    Evidence is now symbol-relevant: the test calls a changed symbol, or
    calls something that calls a changed symbol.
    """
    if ir.globals.prod_opaque_change:
        return True  # cannot reason about it — stay conservative, THREATMODEL #4
    if unit is None:
        return False
    side = unit.before or unit.after
    if side is None:
        return False
    imports = ir.globals.test_file_imports.get(path) if path else None
    if _symbol_match(side.calls, ir.globals.prod_symbols_changed, imports):
        return True
    return any(name in ir.globals.prod_symbol_callers for name in side.calls)


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
    return any(_is_real_assertion(a) and normalize_text(a.text) not in before_texts
               for a in unit.after.assertions)


def _is_real_assertion(a) -> bool:
    """Strong enough to be an oracle, and capable of failing at all."""
    return a.strength is not None and a.strength >= 60 and not a.trivial


def _oracle_mass(side) -> int:
    strong = sum(1 for a in side.assertions if _is_real_assertion(a))
    return strong * max(1, side.param_cases or 1)


def _file_restructured(ir: IR, file_constants: dict[str, dict[str, str]]) -> dict[str, bool]:
    """path -> did the file's added live units replace its disappeared mass?

    Triage cluster: N tests merged into one parametrize, splits, in-file
    renames with rewrites. Oracle mass = strong assertions x parametrize rows;
    if what appeared covers what disappeared, disappearances hold at warn.
    """
    result: dict[str, bool] = {}
    for file in ir.files:
        if file.role != "test":
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
        if file.role != "test":
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
                if any(_is_real_assertion(a) for a in unit.after.assertions):
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


_COMPAT_TOKENS = ("sys.version_info", "sys.platform", "platform.", "os.name")

# Environments the condition is evaluated against. A real compatibility gate
# skips somewhere and runs somewhere; one that is true everywhere is an
# unconditional kill wearing a compat costume.
_ENV_MATRIX = tuple(
    {"version_info": version, "platform": plat, "os_name": osname, "system": system}
    for version in ((3, 11, 0), (3, 12, 0), (3, 13, 0), (3, 14, 0))
    for plat, osname, system in (
        ("win32", "nt", "Windows"),
        ("linux", "posix", "Linux"),
        ("darwin", "posix", "Darwin"),
    )
)

_EVAL_CMP_OPS: dict[type, object] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}


class _Maybe:
    """A sub-expression greenwash cannot evaluate, kept as a free variable.

    Refusing credit outright whenever anything was unevaluable blocked real
    compatibility gates: `skipif(MAC and sys.version_info >= (3, 13) and not
    sys._is_gil_enabled())` mentions a module constant and a helper call, and
    is exactly the honest pattern D6 exists for. Three-valued logic keeps the
    property that matters — a condition is only called an unconditional kill
    when it is true *whatever* the unknown parts turn out to be.
    """

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "MAYBE"


MAYBE = _Maybe()


def _eval_condition(
    node: ast.AST, env: dict, consts: dict[str, ast.AST] | None = None
) -> object:
    """Evaluate a skipif condition in one hypothetical environment.

    Deliberately tiny: only the constructs a compatibility gate actually uses.
    Anything else evaluates to `MAYBE` and propagates through three-valued
    logic, so the answer is `True` only when the condition holds no matter what
    the unknown parts are.

    `consts` maps bare names to their defining expressions, resolved by the
    engine into the IR (same file, imported from the diff, or read at head):
    `skipif(WIN)` evaluates whatever `WIN` was bound to. Resolution is
    cycle-guarded and depth-capped; a name that cannot be chased stays MAYBE.
    """

    def ev(node: ast.AST, resolving: frozenset[str] = frozenset()) -> object:
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Tuple):
            return tuple(ev(e, resolving) for e in node.elts)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            inner = ev(node.operand, resolving)
            return MAYBE if inner is MAYBE else not inner
        if isinstance(node, ast.BoolOp):
            values = [ev(v, resolving) for v in node.values]
            if isinstance(node.op, ast.And):
                if any(v is not MAYBE and not v for v in values):
                    return False
                return True if all(v is not MAYBE and v for v in values) else MAYBE
            if any(v is not MAYBE and v for v in values):
                return True
            return False if all(v is not MAYBE and not v for v in values) else MAYBE
        if isinstance(node, ast.Compare):
            left = ev(node.left, resolving)
            for op, comparator in zip(node.ops, node.comparators):
                fn = _EVAL_CMP_OPS.get(type(op))
                if fn is None:
                    return MAYBE
                right = ev(comparator, resolving)
                if left is MAYBE or right is MAYBE:
                    return MAYBE
                try:
                    if not fn(left, right):  # type: ignore[operator]
                        return False
                except TypeError:
                    return MAYBE
                left = right
            return True
        if isinstance(node, ast.Subscript):
            value = ev(node.value, resolving)
            # `sys.version_info[:2] < (3, 12)` is one of the two commonest
            # ways to spell a real version gate; refusing to evaluate it would
            # deny the de-escalation to honest code.
            if isinstance(node.slice, ast.Slice):
                lower = ev(node.slice.lower, resolving) if node.slice.lower else None
                upper = ev(node.slice.upper, resolving) if node.slice.upper else None
                step = ev(node.slice.step, resolving) if node.slice.step else None
                try:
                    return value[slice(lower, upper, step)]  # type: ignore[index]
                except TypeError:
                    return MAYBE
            index = ev(node.slice, resolving)
            try:
                return value[index]  # type: ignore[index]
            except (TypeError, IndexError, KeyError):
                return MAYBE
        if isinstance(node, ast.Call):
            name = _dotted_name(node.func)
            if name in ("platform.system", "system"):
                return env["system"]
            # `sys.platform.startswith("win")` — the other commonest spelling.
            # Keyed on the attribute itself, not the dotted name: a chained
            # call like `platform.system().lower()` has no dotted name at all.
            if isinstance(node.func, ast.Attribute) and node.func.attr in (
                "startswith",
                "endswith",
                "lower",
                "upper",
            ):
                target = ev(node.func.value, resolving)
                if isinstance(target, str):
                    args = [ev(a, resolving) for a in node.args]
                    method = getattr(target, node.func.attr)
                    try:
                        return method(*args)
                    except TypeError:
                        return MAYBE
            return MAYBE
        name = _dotted_name(node)
        if name in ("sys.version_info", "version_info"):
            return env["version_info"]
        if name in ("sys.version_info.major", "version_info.major"):
            return env["version_info"][0]
        if name in ("sys.version_info.minor", "version_info.minor"):
            return env["version_info"][1]
        if name in ("sys.platform", "platform"):
            return env["platform"]
        if name in ("os.name", "name"):
            return env["os_name"]
        if consts and name and "." not in name and name not in resolving and len(resolving) < 16:
            expr = consts.get(name)
            if expr is not None:
                return ev(expr, resolving | {name})
        return MAYBE

    return ev(node)


def _dotted_name(node: ast.AST) -> str | None:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _discriminates(condition: ast.AST, consts: dict[str, ast.AST] | None) -> bool:
    """Does this condition actually depend on the environment?

    The old test was a substring match against seven hardcoded spellings of an
    always-true version comparison. Every other spelling earned the credit —
    `skipif(True or sys.platform == "win32")`, `skipif(sys.version_info >=
    (3, 8))`, `skipif(os.name != "java")` — which turned D6 into a general
    "disable this test" switch (reader audit 2026-08-02). The condition is now
    evaluated over a matrix of environments.

    Unknown sub-expressions stay unknown rather than voiding the whole
    condition: real gates reference module constants and helper calls
    (`MAC and sys.version_info >= (3, 13) and not sys._is_gil_enabled()`), and
    refusing those blocked three honest click commits. The credit is denied
    only when the condition is provably true in every environment *and* under
    every assignment to the parts greenwash cannot see.

    "Provably true" means truthy, not `is True`: a condition that resolves to
    a non-empty string or tuple skips everywhere just as `True` does, and the
    `is True` test used to hand exactly that spelling the credit (a truthy
    constant plus a compat token smuggled into `reason=`).
    """

    def definitely(value: object) -> bool:
        return value is not MAYBE and bool(value)

    return not all(definitely(_eval_condition(condition, env, consts)) for env in _ENV_MATRIX)


# Condition-bearing decorator markers, exactly as _canonical_marker emits
# them. unittest.skipIf is deliberately absent for now: unmeasured, and the
# credit should not outrun the corpus.
_GATE_DECORATORS = ("pytest.mark.skipif", "pytest.mark.xfail")
# Imperative skips whose recorded guard plays the role of the condition.
_GATE_CALLS = ("pytest.skip", "pytest.xfail", "self.skipTest")


def _parse_constants(raw: dict[str, str]) -> dict[str, ast.AST]:
    return {name: expr for name, expr in ((n, parse_expr(t)) for n, t in raw.items()) if expr is not None}


def _marker_is_compat_gate(m, raw: dict[str, str], consts: dict[str, ast.AST]) -> bool:
    """Is this single marker a qualified interpreter/OS gate?

    Marker names carry their condition (`skipif(cond)`), so the canonical
    part before the parenthesis is matched. Names in the condition resolve
    through the engine-built constant environment, so `skipif(WIN)` is judged
    by what `WIN` is bound to — not by whether the marker text happens to
    contain the string `sys.platform` (FP sweep: click b761eda, attrs
    7373d88). The compat-token filter runs over the condition text *plus*
    those resolved expressions, keeping the credit scoped to interpreter/OS
    gates rather than becoming general skip amnesty.
    """
    canonical = m.name.split("(", 1)[0]
    condition: ast.AST | None = None
    if canonical in _GATE_DECORATORS:
        call = marker_call(m.text)
        if call is None or not call.args:
            return False
        if canonical == "pytest.mark.xfail" and _xfail_strict(call):
            return False
        condition = call.args[0]
    elif canonical in _GATE_CALLS and m.guard:
        condition = parse_expr(m.guard)
    if condition is None:
        return False
    searched = " ".join([m.text, m.guard or "", *_expansion_texts(condition, raw)])
    if not any(tok in searched for tok in _COMPAT_TOKENS):
        return False
    # always true, or unverifiable: not a gate, a disable
    return _discriminates(condition, consts)


def _compat_gate(unit: Unit | None, constants: dict[str, str] | None = None) -> bool:
    """A skip keyed on interpreter/OS version is a compat gate, not a kill.

    Three spellings earn the credit, all evaluated the same way: `skipif(cond)`,
    non-strict `xfail(cond)` (strict inverts the oracle instead of skipping
    it, which is not a gate), and an imperative `pytest.skip()`/`pytest.xfail()`
    /`self.skipTest()` under recorded `if` guards.
    """
    if unit is None or unit.after is None:
        return False
    raw = constants or {}
    consts = _parse_constants(raw)
    return any(_marker_is_compat_gate(m, raw, consts) for m in unit.after.markers)


def unit_is_live(side, constants: dict[str, str] | None) -> bool:
    """Does this unit still run somewhere?

    `disabled = bool(markers)` was the load-bearing definition for every
    relocation credit (D2 moved assertions, D5 restructure mass, the
    split/rename budget) — and it called a test carried across files together
    with its own `skipif(WIN)` marker dead on arrival, which blocked three
    pure test-file splits in the FP corpus (click a391797d00, 700798252a).
    A unit is live when every marker on it is a D6-qualified compat gate:
    the same evaluator, the same constants, the same refusal for `skip`,
    always-true conditions, and anything unverifiable. Bypass #9 (the
    sacrificial `@pytest.mark.skip` absorber) stays closed because an
    unconditional skip qualifies for nothing.
    """
    if not side.markers:
        return True
    raw = constants or {}
    consts = _parse_constants(raw)
    return all(_marker_is_compat_gate(m, raw, consts) for m in side.markers)


def _xfail_strict(call: ast.Call) -> bool:
    for kw in call.keywords:
        if kw.arg == "strict":
            return bool(isinstance(kw.value, ast.Constant) and kw.value.value)
    return False


def _expansion_texts(condition: ast.AST, raw: dict[str, str]) -> list[str]:
    """Defining expressions of every constant the condition (transitively)
    names, in resolution order — the text the compat-token filter must also
    see, or `skipif(WIN)` never looks like a platform gate."""
    out: list[str] = []
    seen: set[str] = set()
    queue = sorted(n for n in bare_names(condition) if n in raw)
    while queue:
        name = queue.pop(0)
        if name in seen:
            continue
        seen.add(name)
        out.append(raw[name])
        expr = parse_expr(raw[name])
        if expr is not None:
            queue.extend(sorted(n for n in bare_names(expr) if n in raw and n not in seen))
    return out


def apply_gates(
    ir: IR,
    findings: list[Finding],
    contract: Contract,
    config: Config,
    allow_entries: list[AllowEntry],
    today: datetime.date,
) -> str:
    """Mutates findings' severity/escalators in place; returns the verdict."""
    # A multiset of credits: each ASSERTION_MOVED de-escalation spends one, so
    # two deletions cannot both be excused by a single re-appearance. Whole
    # units get the same treatment via their body hashes.
    moved = collections.Counter(ir.globals.moved_assertion_texts)
    moved_units = collections.Counter(ir.globals.moved_unit_hashes)
    duplicates = set(ir.globals.duplicate_unit_hashes)
    units = _unit_index(ir)
    active_allows = active_fingerprints(allow_entries, today)
    roles = {f.path: f.role for f in ir.files}
    file_constants = {f.path: f.constants for f in ir.files}
    restructured = _file_restructured(ir, file_constants)
    split_renamed = _split_or_renamed(ir, file_constants)

    for f in findings:
        if f.fingerprint in active_allows:
            f.allowlisted = True
            f.deescalators.append("ALLOWLISTED")
            continue
        # A broad except swallowing an assertion inside a test file IS oracle
        # tampering, whatever it would mean in production code (decoy run,
        # cache_invalidate).
        is_oracle = f.rule in ORACLE_RULES or (
            f.rule == "BROAD_EXCEPT_ADDED" and roles.get(f.path) in ("test", "conftest")
        )
        if not is_oracle:
            # Non-oracle escalations from the SPEC §5 table.
            if f.rule == "GUARDRAIL_TOUCHED":
                f.severity = "critical"
                f.escalators.append("META")  # E4
            elif f.rule == "HIDDEN_UNICODE":
                f.severity = "high"
                f.escalators.append("HIDDEN_CONTROL_CHARS")
            elif f.rule == "CI_WORKFLOW_TOUCHED" and any(
                path == f.path for path, _ in ir.globals.ci_weakening_lines
            ):
                f.severity = "high"
                f.escalators.append("CI_TEST_COMMAND_WEAKENED")
            # A test file that parsed before this diff and does not parse now
            # has been taken out of greenwash's reach. A file that never
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
            texts = [normalize_text(a.text) for a in unit.before.assertions]
            needed = collections.Counter(texts)
            if texts and all(moved[t] >= n for t, n in needed.items()):
                moved.subtract(needed)
                f.severity = "info"
                f.deescalators.append("ASSERTION_MOVED")
                continue

        # Materiality (ASSERT_WEAKENED only): a 10-point slide inside the
        # exact family (e.g. assertListEqual -> assertEqual on a variable) is
        # style drift, not oracle removal — the FP sweep blocked several such
        # human commits. Material = fell by >= 30, or landed below PATTERN.
        # Landing on APPROX means a tolerance now exists where an exact
        # comparison used to be — the decoy run's most popular cheat. Mild
        # means "still exact": 100 -> 90 within the exact family.
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

        # Compensation evidence from the triage clusters: all of these hold
        # the finding at warn (visible, allowlistable) instead of blocking.
        compensation = None
        if f.rule == "ASSERT_REMOVED" and _same_unit_rewrite(unit):
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
        elif f.rule == "TEST_DISABLED" and _compat_gate(unit, file_constants.get(f.path)):
            compensation = "COMPAT_GATE"
        elif (
            f.rule == "TEST_DISABLED"
            and _prod_removal_shape(f, unit)
            and _prod_symbol_removed(f.path, ir)
        ):
            compensation = "PROD_SYMBOL_REMOVED"

        # D1 REPAIR_EVIDENCE / E1 NO_PROD_CHANGE_IN_DIFF are two sides of one
        # question: is there a production change that explains this edit?
        has_evidence = (
            _file_repair_evidence(f.path, ir) if unit is None else _repair_evidence(unit, ir, f.path)
        )
        package_only = (
            not has_evidence
            and f.rule == "EXPECTED_VALUE_CHANGED"
            and _package_evidence(f.path, ir)
        )
        # An expectation literal tracking a dependency change: httpx 0.28
        # switched to compact JSON separators and every exact literal in the
        # corpus followed it (starlette 5ccbc62175, 100f05a66b). Scoped to
        # EXPECTED_VALUE_CHANGED exactly like PACKAGE_REPAIR: a manifest bump
        # buys nothing for a weakened or deleted oracle.
        dep_drift = (
            not has_evidence
            and not package_only
            and f.rule == "EXPECTED_VALUE_CHANGED"
            and ir.globals.dependency_manifest_changed
        )
        if has_evidence:
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
            f.escalators.append("NO_PROD_CHANGE_IN_DIFF")

        # E2 ORACLE_FREEZE
        if contract.oracle_freeze:
            f.severity = "high"
            f.escalators.append("ORACLE_FREEZE")

    threshold = SEVERITY_ORDER[config.fail_on]
    blocking = [
        f for f in findings if not f.allowlisted and SEVERITY_ORDER[f.severity] >= threshold
    ]
    return "block" if blocking else "pass"

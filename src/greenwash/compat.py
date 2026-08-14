"""D6 skip-condition evaluation. Extracted from gating (E5)."""
from __future__ import annotations

import ast
import operator

from greenwash.ir.astutil import dotted_name as _dotted_name
from greenwash.ir.markers import bare_names, marker_call, parse_expr
from greenwash.ir.model import Unit

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
_GATE_CALLS = (
    "pytest.skip",
    "pytest.xfail",
    "self.skipTest",
    # Same shape one level up: `if not PY_3_14_PLUS: collect_ignore.extend(...)`
    # is a compatibility gate over a whole file, and its recorded guard is the
    # condition (attrs 61e8179545). Unguarded, it earns nothing.
    "conftest.collect_ignore",
)


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
    # The compat-token filter keeps the credit from becoming general skip
    # amnesty for individual tests. A *suite-level collection control* is a
    # different object: its guard is the whole justification, and the
    # alternative to trusting a discriminating one is blocking every
    # optional-dependency gate a project writes — `if find_spec("redis") is
    # None: collect_ignore.append(...)` names no interpreter and no OS, and an
    # adversarial audit caught this build blocking exactly that, on a PR that
    # *added* the tests it was guarding. Still has to discriminate: an
    # always-true guard is a disable wearing a condition.
    if canonical != "conftest.collect_ignore" and not any(
        tok in searched for tok in _COMPAT_TOKENS
    ):
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


def guard_always_skips(guard: str, constants: dict[str, str] | None) -> bool:
    """Is this if-guard true in every environment greenwash considers?

    Used to compare a skip guard across the diff: a guard that used to be
    false somewhere and is now true everywhere silences the test without
    touching a single character of the guard itself (GUARD_WEAKENED).
    Unevaluable guards answer False, so the finding is never invented from
    ignorance.
    """
    condition = parse_expr(guard)
    if condition is None:
        return False
    consts = _parse_constants(constants or {})
    return all(
        (v := _eval_condition(condition, env, consts)) is not MAYBE and bool(v)
        for env in _ENV_MATRIX
    )


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



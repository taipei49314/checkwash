"""D6 skip-condition evaluation. Extracted from gating (E5)."""
from __future__ import annotations

import ast
import operator
from collections import Counter

from checkwash.frontends.python.conftest_controls import is_collection_control
from checkwash.ir.astutil import dotted_name as _dotted_name
from checkwash.ir.markers import (
    GUARDED_SKIP_CALLS,
    bare_names,
    is_guarded_mark,
    is_guarded_skip,
    is_helper_skip,
    is_rebound,
    is_setup_skip,
    is_string_condition,
    mark_condition,
    marker_call,
    parse_expr,
    skip_condition,
)
from checkwash.ir.model import Unit

_COMPAT_TOKENS = ("sys.version_info", "sys.platform", "platform.", "os.name")

# Environments the condition is evaluated against. A real compatibility gate
# skips somewhere and runs somewhere; one that is true everywhere is an
# unconditional kill wearing a compat costume.
#
# D-201 asks a single test's gate to provably run somewhere, so the matrix
# reads what honest gates name and it once left unknown: the interpreter
# (CPython, and PyPy at 3.11, the version it ships) and the machine each
# platform reports (`platform.machine()`). The micro release is not one of
# its facts: `sys.version_info` is the five-tuple it is with that element
# unknown (`_Release`), so `sys.version_info > (3, 11, 0)` is true on every
# 3.11 release while `>= (3, 11, 1)`, which skips everywhere but on 3.11.0,
# is unknown there.
_PLATFORMS = (
    ("win32", "nt", "Windows", ("AMD64", "ARM64")),
    ("linux", "posix", "Linux", ("x86_64", "aarch64")),
    ("darwin", "posix", "Darwin", ("x86_64", "arm64")),
)


class _Release:
    """A release number whose micro element is unknown (D-201).

    `sys.version_info` is `(3, minor, micro, "final", 0)`, and
    `platform.python_version_tuple()` is `("3", minor, micro)` as text. A
    comparison is answered when every micro release gives the same answer:
    `> (3, 11, 0)` is true on 3.11 whatever the micro release is, and
    `>= (3, 12)` never reaches it. One that depends on it (`>= (3, 11, 1)`,
    `[2] == 0`) raises the TypeError the evaluator reads as unknown. As a
    tuple does, it equals nothing but a tuple, so `!= None` is true, and a
    release compared with itself (or a slice of itself) shares its micro
    release.
    """

    __slots__ = ("head", "tail", "numeric")

    def __init__(self, head: tuple, tail: tuple = (), numeric: bool = True) -> None:
        self.head = head
        self.tail = tail
        self.numeric = numeric

    def _samples(self, other: object) -> list[tuple]:
        if not isinstance(other, tuple):
            raise TypeError("a release compares with a tuple")
        at = len(self.head)
        if self.numeric:
            # The answer can only change where the micro release crosses the
            # other tuple's own element, so these samples cover every case.
            micros = {0, 1}
            if len(other) > at and type(other[at]) is int:
                micros |= {m for m in (other[at] - 1, other[at], other[at] + 1) if m >= 0}
        else:
            # As text, a micro release orders by its digits: unknown once
            # the leading elements are equal and the other tuple goes on.
            if len(other) > at and other[:at] == self.head:
                raise TypeError("depends on the micro release")
            micros = {"0"}
        return [(*self.head, micro, *self.tail) for micro in micros]

    def _at(self, micro: int) -> tuple:
        return (*self.head, micro if self.numeric else str(micro), *self.tail)

    def _decide(self, op, other: object) -> bool:
        if isinstance(other, _Release):
            # Both are the one interpreter's: the same micro release.
            answers = {bool(op(self._at(micro), other._at(micro))) for micro in (0, 1)}
        else:
            answers = {bool(op(sample, other)) for sample in self._samples(other)}
        if len(answers) != 1:
            raise TypeError("depends on the micro release")
        return answers.pop()

    def __eq__(self, other: object) -> bool:
        # `!=` is its negation, and defining it leaves the class unhashable.
        if not isinstance(other, (tuple, _Release)):
            return False
        return self._decide(operator.eq, other)

    def __lt__(self, other: object) -> bool:
        return self._decide(operator.lt, other)

    def __le__(self, other: object) -> bool:
        return self._decide(operator.le, other)

    def __gt__(self, other: object) -> bool:
        return self._decide(operator.gt, other)

    def __ge__(self, other: object) -> bool:
        return self._decide(operator.ge, other)

    def __len__(self) -> int:
        return len(self.head) + 1 + len(self.tail)

    def __getitem__(self, index: object) -> object:
        at = len(self.head)
        if isinstance(index, slice):
            stop = len(self) if index.stop is None else index.stop
            if index.start not in (None, 0) or index.step is not None or type(stop) is not int or stop < 0:
                raise TypeError("a slice checkwash does not read")
            if stop <= at:
                return self.head[:stop]
            return _Release(self.head, self.tail[:stop - at - 1], self.numeric)
        if type(index) is not int:
            raise TypeError("an index checkwash does not read")
        position = index + len(self) if index < 0 else index
        if 0 <= position < at:
            return self.head[position]
        if at < position < len(self):
            return self.tail[position - at - 1]
        raise TypeError("the micro release, or no element at all")


class _VersionString:
    """`platform.python_version()`, `"3.<minor>.<micro>"` with the micro release unknown (D-201).

    A comparison, a prefix test, a slice or a substring test is answered
    when the known part decides it: `< "3.12"` on 3.11,
    `.startswith("3.11")`, `[:4] == "3.11"`, `"3.11" in`. One that reaches
    the micro digits (`== "3.11.0"`) is unknown. As a string does, it
    equals nothing but a string.
    """

    __slots__ = ("prefix",)

    def __init__(self, major: int, minor: int) -> None:
        self.prefix = f"{major}.{minor}."

    def _decide(self, op, other: object) -> bool:
        if not isinstance(other, str):
            raise TypeError("a version string compares with a string")
        for mine, theirs in zip(self.prefix, other):
            if mine != theirs:
                return bool(op(mine, theirs))
        if len(other) <= len(self.prefix):
            # The other string is a prefix of this one, which goes on.
            return bool(op(self.prefix + "0", other))
        raise TypeError("depends on the micro release")

    def __eq__(self, other: object) -> bool:
        # `!=` is its negation, and defining it leaves the class unhashable.
        if other is self:
            return True
        if not isinstance(other, str):
            return False
        return self._decide(operator.eq, other)

    def __lt__(self, other: object) -> bool:
        return self._decide(operator.lt, other)

    def __le__(self, other: object) -> bool:
        return self._decide(operator.le, other)

    def __gt__(self, other: object) -> bool:
        return self._decide(operator.gt, other)

    def __ge__(self, other: object) -> bool:
        return self._decide(operator.ge, other)

    def __getitem__(self, index: object) -> str:
        if isinstance(index, slice):
            if (index.start in (None, 0) and index.step is None and type(index.stop) is int
                    and 0 <= index.stop <= len(self.prefix)):
                return self.prefix[:index.stop]
        elif type(index) is int and 0 <= index < len(self.prefix):
            return self.prefix[index]
        raise TypeError("reaches the micro release")

    def __contains__(self, item: object) -> bool:
        if not isinstance(item, str):
            raise TypeError("a substring is text")
        if item in self.prefix:
            return True
        # It could only run into the micro release's digits from the end of
        # the known part: "11.2" might, "3.13" cannot.
        for cut in range(len(item)):
            if self.prefix.endswith(item[:cut]) and item[cut:].isdigit():
                raise TypeError("depends on the micro release")
        return False

    def startswith(self, affixes: object) -> bool:
        answers = set()
        for affix in affixes if isinstance(affixes, tuple) else (affixes,):
            if not isinstance(affix, str):
                raise TypeError("an affix is text")
            if self.prefix.startswith(affix):
                return True
            answers.add(None if affix.startswith(self.prefix) else False)
        if None in answers:
            raise TypeError("depends on the micro release")
        return False


_ENV_MATRIX = tuple(
    {"version_info": _Release((3, minor), ("final", 0)), "platform": plat, "os_name": osname, "system": system,
     "implementation": impl, "machine": machine}
    for impl, minors in (("CPython", (11, 12, 13, 14)), ("PyPy", (11,)))
    for minor in minors
    for plat, osname, system, machines in _PLATFORMS
    for machine in machines
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
    """A sub-expression checkwash cannot evaluate, kept as a free variable.

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

    def __eq__(self, other: object) -> bool:
        # Inside a tuple, `==` and `in` reach the element itself: an unknown
        # entry must leave the answer unknown, not unequal (D-201).
        raise TypeError("an unknown value")

    __hash__ = object.__hash__


MAYBE = _Maybe()


class _Module:
    """A module pytest binds in a string condition's namespace (#263).

    pytest evaluates `skipif("...")` with `os`, `sys` and `platform` bound to
    those modules beside the test module's globals. As a value, a module is
    truthy and equals nothing but itself, so `"platform != 'linux'"` is true
    everywhere, as it is under pytest.
    """

    __slots__ = ("name",)

    def __init__(self, name: str) -> None:
        self.name = name

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<module {self.name}>"


_PYTEST_MODULES = {name: _Module(name) for name in ("os", "sys", "platform")}


class _KnownString:
    """An environment fact read only for the values the matrix holds (D-201).

    The matrix holds CPython and PyPy, so `platform.python_implementation()
    == "PyPy"` is known in every environment. In the old reading, which asks
    whether a condition is true everywhere, a comparison with any other name
    (`!= "IronPython"`) stays unknown, as it was before the interpreter
    joined the matrix: naming an interpreter the matrix does not hold must
    not make a condition true everywhere. The question whether a condition
    is provably false somewhere reads the plain value instead (the
    evaluator's `exact`): on CPython, `== "GraalVM"` is false. The TypeError
    is the evaluator's MAYBE, and `!=` and `in` reach `__eq__` too.
    """

    __slots__ = ("value", "known")

    def __init__(self, value: str, known: frozenset[str]) -> None:
        self.value = value
        self.known = known

    def __eq__(self, other: object) -> bool:
        if isinstance(other, str) and other in self.known:
            return other == self.value
        raise TypeError("a value the environment matrix does not hold")


_INTERPRETERS = frozenset({"CPython", "PyPy"})
_INTERPRETER_NAMES = frozenset({"cpython", "pypy"})
_MACHINES = frozenset(machine for *_, machines in _PLATFORMS for machine in machines)
# Every environment is 64-bit, so "32bit" is a value the matrix does not hold.
_ARCHITECTURES = frozenset({"64bit"})


def _known_method(target: _KnownString, method: str, args: list) -> object:
    """A string method on a fact the matrix knows, as `platform.machine().lower()`.

    `lower` and `upper` keep the value known. `startswith` and `endswith`
    answer only for an affix some value the matrix holds has: asking about
    one it holds none of (`.startswith("riscv")`) stays unknown, as a
    comparison with a name it does not hold does.
    """
    if method in ("lower", "upper") and not args:
        return _KnownString(getattr(target.value, method)(), frozenset(getattr(k, method)() for k in target.known))
    if method in ("startswith", "endswith") and len(args) == 1:
        affixes = args[0] if isinstance(args[0], tuple) else (args[0],)
        if all(isinstance(affix, str) for affix in affixes) and any(
                getattr(k, method)(affixes) for k in target.known):
            return getattr(target.value, method)(affixes)
    raise TypeError("a value the environment matrix does not hold")


class _BuiltinModuleNames:
    """`sys.builtin_module_names`, read for the one question a gate asks of it (D-201).

    `'__pypy__' in sys.builtin_module_names` is the oldest spelling of "on
    PyPy" (pytest 4445685285 adds it to a version gate). Membership of any
    other name is unknown, so it raises the TypeError the evaluator turns
    into MAYBE.
    """

    __slots__ = ("implementation",)

    def __init__(self, implementation: str) -> None:
        self.implementation = implementation

    def __contains__(self, name: object) -> bool:
        if name == "__pypy__":
            return self.implementation == "PyPy"
        raise TypeError("unknown builtin module")

    def __eq__(self, other: object) -> bool:
        # `!=` reaches this too, and defining it leaves the class unhashable.
        raise TypeError("unknown builtin module names")


def _member(item: object, container: object) -> object:
    """`item in container`, three-valued (D-201).

    Python's `in` stops at the first entry its `==` cannot answer, so the
    answer depended on the order of the entries: `not in ("PyPy",
    "IronPython")` was read on PyPy and `not in ("IronPython", "PyPy")` was
    not. Each entry is asked here, and one that equals the item answers
    whatever the others are.
    """
    if item is MAYBE or container is MAYBE:
        return MAYBE
    if isinstance(container, (tuple, list, frozenset)):
        unknown = False
        for entry in container:
            if entry is MAYBE:
                unknown = True
                continue
            try:
                if item == entry:
                    return True
            except TypeError:
                unknown = True
        return MAYBE if unknown else False
    if isinstance(container, _KnownString):
        # A substring of a fact the old reading keeps to the values it holds.
        return MAYBE
    try:
        return bool(item in container)  # a str, or `sys.builtin_module_names`
    except TypeError:
        return MAYBE


def _compare(op: ast.cmpop, left: object, right: object) -> object:
    """One link of a comparison chain: True, False or MAYBE."""
    if left is MAYBE or right is MAYBE:
        return MAYBE
    if isinstance(op, (ast.In, ast.NotIn)):
        found = _member(left, right)
        if found is MAYBE:
            return MAYBE
        return found if isinstance(op, ast.In) else not found
    fn = _EVAL_CMP_OPS.get(type(op))
    if fn is None:
        return MAYBE
    try:
        return bool(fn(left, right))
    except TypeError:
        return MAYBE


def _eval_condition(
    node: ast.AST, env: dict, consts: dict[str, ast.AST] | None = None, pytest_names: bool = False,
    exact: bool = False,
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

    `pytest_names` evaluates a string condition as pytest does (#263): a bare
    `os`, `sys` or `platform` is that module unless the test module binds the
    name to a constant, which wins as the module's globals do. A constant's
    own expression is module code, read as any other condition is.

    `exact` (D-201) reads the interpreter, the machine and the architecture
    as the plain values each environment has, for the question whether a
    condition is provably false somewhere. Without it, a comparison with a
    value the matrix does not hold stays unknown (`_KnownString`).
    """

    def fact(value: str, known: frozenset[str]) -> object:
        return value if exact else _KnownString(value, known)

    def ev(node: ast.AST, resolving: frozenset[str] = frozenset(), pytest: bool = pytest_names) -> object:
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Tuple):
            return tuple(ev(e, resolving, pytest) for e in node.elts)
        if isinstance(node, ast.List):
            # `sys.platform not in ["linux", "darwin"]` is the list spelling
            # of the tuple one (D-201). It stays a list: `sys.version_info[:2]
            # != [3, 11]` is true everywhere, as it is under Python.
            return [ev(e, resolving, pytest) for e in node.elts]
        if isinstance(node, ast.Set):
            try:
                return frozenset(ev(e, resolving, pytest) for e in node.elts)
            except TypeError:
                return MAYBE
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            inner = ev(node.operand, resolving, pytest)
            return MAYBE if inner is MAYBE else not inner
        if isinstance(node, ast.BoolOp):
            values = [ev(v, resolving, pytest) for v in node.values]
            if isinstance(node.op, ast.And):
                if any(v is not MAYBE and not v for v in values):
                    return False
                return True if all(v is not MAYBE and v for v in values) else MAYBE
            if any(v is not MAYBE and v for v in values):
                return True
            return False if all(v is not MAYBE and not v for v in values) else MAYBE
        if isinstance(node, ast.Compare):
            # A chain is the conjunction of its links: one provably false
            # link makes it false, whatever the others are.
            operands = [ev(node.left, resolving, pytest), *(ev(c, resolving, pytest) for c in node.comparators)]
            links = [_compare(op, a, b) for op, a, b in zip(node.ops, operands, operands[1:])]
            if any(link is False for link in links):
                return False
            return MAYBE if any(link is MAYBE for link in links) else True
        if isinstance(node, ast.Subscript):
            if (isinstance(node.value, ast.Call) and not node.value.args
                    and _dotted_name(node.value.func) in ("platform.architecture", "architecture")
                    and isinstance(node.slice, ast.Constant) and node.slice.value == 0):
                # `platform.architecture()[0]`: every environment is 64-bit.
                return fact("64bit", _ARCHITECTURES)
            value = ev(node.value, resolving, pytest)
            # `sys.version_info[:2] < (3, 12)` is one of the two commonest
            # ways to spell a real version gate; refusing to evaluate it would
            # deny the de-escalation to honest code.
            if isinstance(node.slice, ast.Slice):
                lower = ev(node.slice.lower, resolving, pytest) if node.slice.lower else None
                upper = ev(node.slice.upper, resolving, pytest) if node.slice.upper else None
                step = ev(node.slice.step, resolving, pytest) if node.slice.step else None
                try:
                    return value[slice(lower, upper, step)]  # type: ignore[index]
                except TypeError:
                    return MAYBE
            index = ev(node.slice, resolving, pytest)
            try:
                return value[index]  # type: ignore[index]
            except (TypeError, IndexError, KeyError):
                return MAYBE
        if isinstance(node, ast.Call):
            name = _dotted_name(node.func)
            if name in ("platform.system", "system"):
                return env["system"]
            if name in ("platform.python_implementation", "python_implementation"):
                return fact(env["implementation"], _INTERPRETERS)
            if name in ("platform.machine", "machine") and not node.args:
                return fact(env["machine"], _MACHINES)
            if name in ("platform.python_version", "python_version") and not node.args:
                return _VersionString(*env["version_info"].head)
            if name in ("platform.python_version_tuple", "python_version_tuple") and not node.args:
                return _Release(tuple(str(part) for part in env["version_info"].head), numeric=False)
            # `int(platform.python_version_tuple()[1])`: a version part as a number.
            if name == "int" and len(node.args) == 1 and not node.keywords:
                value = ev(node.args[0], resolving, pytest)
                if isinstance(value, str):
                    try:
                        return int(value)
                    except ValueError:
                        return MAYBE
                return value if type(value) is int else MAYBE
            # `hasattr(sys, "pypy_version_info")`, pytest's own PYPY constant.
            if (name == "hasattr" and len(node.args) == 2 and not node.keywords
                    and _dotted_name(node.args[0]) == "sys"
                    and isinstance(node.args[1], ast.Constant) and node.args[1].value == "pypy_version_info"):
                return env["implementation"] == "PyPy"
            # `sys.platform.startswith("win")` — the other commonest spelling.
            # Keyed on the attribute itself, not the dotted name: a chained
            # call like `platform.system().lower()` has no dotted name at all.
            if isinstance(node.func, ast.Attribute) and node.func.attr in (
                "startswith",
                "endswith",
                "lower",
                "upper",
            ):
                target = ev(node.func.value, resolving, pytest)
                if isinstance(target, _VersionString) and node.func.attr == "startswith" and len(node.args) == 1:
                    try:
                        return target.startswith(ev(node.args[0], resolving, pytest))
                    except TypeError:
                        return MAYBE
                if isinstance(target, _KnownString):
                    try:
                        return _known_method(target, node.func.attr, [ev(a, resolving, pytest) for a in node.args])
                    except TypeError:
                        return MAYBE
                if isinstance(target, str):
                    args = [ev(a, resolving, pytest) for a in node.args]
                    method = getattr(target, node.func.attr)
                    try:
                        return method(*args)
                    except TypeError:
                        return MAYBE
            return MAYBE
        if pytest and isinstance(node, ast.Name) and node.id in _PYTEST_MODULES:
            # Resolving a constant leaves pytest's namespace, so nothing is
            # being resolved yet here and no cycle can pass through.
            expr = consts.get(node.id) if consts else None
            if expr is None:
                return _PYTEST_MODULES[node.id]
            return ev(expr, resolving | {node.id}, False)
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
        if name == "sys.implementation.name":
            return fact(env["implementation"].lower(), _INTERPRETER_NAMES)
        if name == "sys.builtin_module_names":
            return _BuiltinModuleNames(env["implementation"])
        if consts and name and "." not in name and name not in resolving and len(resolving) < 16:
            expr = consts.get(name)
            if expr is not None:
                return ev(expr, resolving | {name}, False)
        return MAYBE

    return ev(node)


def _discriminates(
    parts: list[tuple[ast.AST, bool]], consts: dict[str, ast.AST] | None, runs_somewhere: bool = False
) -> bool:
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
    every assignment to the parts checkwash cannot see.

    "Provably true" means truthy, not `is True`: a condition that resolves to
    a non-empty string or tuple skips everywhere just as `True` does, and the
    `is True` test used to hand exactly that spelling the credit (a truthy
    constant plus a compat token smuggled into `reason=`).

    The condition is the conjunction of its parts, each evaluated in its own
    namespace: a `pytestmark` binding's guard is module code, while the mark's
    string condition is evaluated as pytest does (#263).

    `runs_somewhere` (D-201) asks the other half for a single test's gate: is
    there an environment where the condition is provably false, so the test
    provably runs there? It reads each environment's interpreter, machine and
    architecture exactly: on CPython, `== "GraalVM"` is false. An unknown part no longer earns the credit by
    standing in for the false case: `skipif(sys.version_info >= (3, 0) and
    bool(sys.modules))` names the interpreter only to pass the token filter
    and skips everywhere, and so does `skipif(sys.platform == "win32" or
    bool(sys.modules))`. `MAC and sys.version_info >= (3, 13) and not
    sys._is_gil_enabled()` keeps it: off macOS, `MAC` is false whatever the
    call returns. A suite-level collection control keeps the old reading,
    because its guard is the whole justification and an optional-dependency
    guard (`find_spec("redis") is None`) is unknown everywhere.
    """

    if runs_somewhere:
        return any(_fires(parts, env, consts) is False for env in _ENV_MATRIX)
    return not all(_fires(parts, env, consts, exact=False) is True for env in _ENV_MATRIX)


def _fires(parts: list[tuple[ast.AST, bool]], env: dict, consts: dict[str, ast.AST] | None,
           exact: bool = True) -> object:
    """Does a gate's condition hold here: True, False or MAYBE.

    The conjunction of its parts, each truthy or not, so a condition that
    resolves to a non-empty string or tuple holds as `True` does. Read
    exactly unless `exact` is False, the old reading's question.
    """
    values = [_eval_condition(node, env, consts, pytest_names, exact) for node, pytest_names in parts]
    if any(value is not MAYBE and not value for value in values):
        return False
    return True if all(value is not MAYBE for value in values) else MAYBE


# Condition-bearing decorator markers, exactly as _canonical_marker emits
# them. unittest.skipIf is deliberately absent for now: unmeasured, and the
# credit should not outrun the corpus.
_GATE_DECORATORS = ("pytest.mark.skipif", "pytest.mark.xfail")
# unittest's conditional skips, each with whether it skips when its
# condition is false. They earn nothing, but where the test runs is judged
# with them (D-201).
_UNITTEST_CONDITIONAL = {"unittest.skipIf": False, "skipIf": False, "unittest.skipUnless": True, "skipUnless": True}
# The suite-level collection controls of a conftest: `collect_ignore`, the
# collection hooks, and an `add_marker` skip in one. Same shape one level up:
# `if not PY_3_14_PLUS: collect_ignore.extend(...)` is a compatibility gate
# over a whole file, and its recorded guard is the condition (attrs
# 61e8179545). A hook's guard is the condition its effects fire under (#209
# Q1). Unguarded, each earns nothing.
_SUITE_GATES = (
    "conftest.collect_ignore",
    "conftest.pytest_collection_modifyitems",
    "conftest.pytest_ignore_collect",
    "conftest.add_marker_skip",
)
# Imperative skips whose recorded guard plays the role of the condition: every
# native body skip or xfail, called or raised (#220), and the suite gates.
_GATE_CALLS = (*sorted(GUARDED_SKIP_CALLS), *_SUITE_GATES)


def _parse_constants(raw: dict[str, str]) -> dict[str, ast.AST]:
    return {name: expr for name, expr in ((n, parse_expr(t)) for n, t in raw.items()) if expr is not None}


def _gate_parts(m, raw: dict[str, str], strict: bool = False) -> tuple[str, list[tuple[ast.AST, bool]]] | None:
    """The canonical name and the condition parts of a marker that can be a gate, or None.

    Marker names carry their condition (`skipif(cond)`), so the canonical
    part before the parenthesis is matched. The condition is the conjunction
    of its parts, each with whether pytest compiles it from a string (#263).
    None for a strict xfail (it inverts the oracle instead of skipping it),
    unless `strict` asks where the test runs, for a condition or guard that
    does not parse, and for a marker with no condition to judge.
    """
    canonical = m.name.split("(", 1)[0]
    parts: list[tuple[ast.AST, bool]] = []
    if canonical in _GATE_DECORATORS or (m.guard and is_guarded_mark(canonical)):
        # A mark's condition, and the guard of the `pytestmark` binding that
        # carries it: both must hold for the mark to apply, so the condition
        # is their conjunction (#260 Q2).
        call = marker_call(m.text)
        if canonical == "pytest.mark.xfail" and call is not None and _xfail_strict(call) and not strict:
            return None
        if m.guard:
            guard = parse_expr(m.guard)
            if guard is None:
                return None
            parts.append((guard, False))
        if canonical in _GATE_DECORATORS and call is not None and call.args:
            # A string condition is the expression pytest compiles from it;
            # one that does not compile earns nothing (#263).
            condition = mark_condition(call)
            if condition is None:
                return None
            parts.append((condition, is_string_condition(call)))
    elif (
        canonical in _GATE_CALLS or is_setup_skip(canonical) or is_helper_skip(canonical) or is_rebound(canonical)
    ) and m.guard:
        # A skip in the setup the unit runs is judged as one in its body is
        # (#196 183.2): its guard is the condition its setup reaches it under.
        # So is one a helper ends in, under the condition its call reaches it
        # (#272), and a later binding of the test's name, under the condition
        # that binding runs under (#424 Q6).
        guard = parse_expr(m.guard)
        if guard is not None:
            parts.append((guard, False))
    if not parts:
        return None
    return canonical, parts


def _names_the_environment(m, raw: dict[str, str], parts: list[tuple[ast.AST, bool]]) -> bool:
    """Does the condition, with its constants resolved, name the interpreter or OS?"""
    searched = " ".join([m.text, m.guard or "", *(text for node, _ in parts for text in _expansion_texts(node, raw))])
    return any(tok in searched for tok in _COMPAT_TOKENS)


def _marker_is_compat_gate(m, raw: dict[str, str], consts: dict[str, ast.AST], credit: bool = False) -> bool:
    """Is this single marker a qualified interpreter/OS gate?

    Names in the condition resolve through the engine-built constant
    environment, so `skipif(WIN)` is judged by what `WIN` is bound to — not
    by whether the marker text happens to contain the string `sys.platform`
    (FP sweep: click b761eda, attrs 7373d88). The compat-token filter runs
    over the condition text *plus* those resolved expressions, keeping the
    credit scoped to interpreter/OS gates rather than becoming general skip
    amnesty.

    `credit` asks D-201's question for D6's hold on an added skip: a single
    test's gate must provably run somewhere. Liveness (`unit_is_live`) keeps
    the old reading: it decides whether a moved test still runs, which a
    gate carried along with it does not change, and whether a stand-in
    installation is looked for at all, where reading an unknown gate as
    dead would hide the installation.
    """
    gate = _gate_parts(m, raw)
    if gate is None:
        return False
    canonical, parts = gate
    # The compat-token filter keeps the credit from becoming general skip
    # amnesty for individual tests. A *suite-level collection control* is a
    # different object: its guard is the whole justification, and the
    # alternative to trusting a discriminating one is blocking every
    # optional-dependency gate a project writes — `if find_spec("redis") is
    # None: collect_ignore.append(...)` names no interpreter and no OS, and an
    # adversarial audit caught this build blocking exactly that, on a PR that
    # *added* the tests it was guarding. Still has to discriminate: an
    # always-true guard is a disable wearing a condition. A collection hook
    # is judged the same way, so pytest's `--runslow` recipe holds as its
    # `collect_ignore` spelling does (D-028, #209 Q1).
    if canonical not in _SUITE_GATES and not _names_the_environment(m, raw, parts):
        return False
    # always true, or unverifiable: not a gate, a disable. For the credit, a
    # single test's gate must also provably run somewhere (D-201).
    return _discriminates(parts, consts, runs_somewhere=credit and canonical not in _SUITE_GATES)


def _joint_parts(m, raw: dict[str, str]) -> list[tuple[ast.AST, bool]] | None:
    """A gate's condition parts when where the test runs is asked (D-201).

    Every gate D6 reads, and two that earn nothing but still keep the test
    from running normally: unittest's conditional skips (`skipUnless` skips
    when its condition is false) and a strict xfail, which inverts the
    oracle wherever its condition holds.
    """
    canonical = m.name.split("(", 1)[0]
    if canonical in _UNITTEST_CONDITIONAL:
        call = marker_call(m.text)
        if call is None:
            return None
        if call.args and not isinstance(call.args[0], ast.Starred):
            condition = call.args[0]
        else:
            condition = next((k.value for k in call.keywords if k.arg == "condition"), None)
            if condition is None:
                return None
        if _UNITTEST_CONDITIONAL[canonical]:
            condition = ast.UnaryOp(op=ast.Not(), operand=condition)
        parts = [(condition, False)]
        if m.guard:
            guard = parse_expr(m.guard)
            if guard is None:
                return None
            parts.insert(0, (guard, False))
        return parts
    gate = _gate_parts(m, raw, strict=True)
    return None if gate is None else gate[1]


def _environment_gates(side, raw: dict[str, str], consts: dict[str, ast.AST]) -> list[tuple]:
    """The gates on a unit's side the matrix can read: (key, canonical name, parts).

    A gate takes part when its condition is known, true or false, in some
    environment: a skip on an optional dependency (`skipif(not HAS_NUMPY)`)
    is unknown everywhere and says nothing about where the test runs,
    whatever its message says ("not available on this platform."), while one
    on PyPy spelled without a compat token (`sys.implementation.name ==
    "pypy"`) does. A suite-level collection control is not the unit's own.
    The key is the gate's name and its parsed parts, so respelling a quote
    is not a new gate.
    """
    gates = []
    for m in side.markers:
        canonical = m.name.split("(", 1)[0]
        if canonical in _SUITE_GATES:
            continue
        parts = _joint_parts(m, raw)
        if parts is None or all(_fires(parts, env, consts) is MAYBE for env in _ENV_MATRIX):
            continue
        gates.append(((canonical, tuple(ast.dump(node) for node, _ in parts)), canonical, parts))
    return gates


def _runs_somewhere_jointly(unit: Unit, raw: dict[str, str], consts: dict[str, ast.AST]) -> bool:
    """Do the gates this change added leave an environment where the test may run? (D-201)

    Two gates that each run somewhere can still cover every environment
    between them: `skipif(sys.platform == "win32")` beside an added
    `skipif(sys.platform != "win32")`, or a mark beside the opposite body
    skip. So there must be an environment where every gate the change added
    is provably false and no gate the test already had is provably true.

    A gate the test already had is one with the same marker and condition
    on the base side, or, for a skip in the setup the test runs, in a helper
    or under a later binding, the same marker whose guard the change
    rewrote: a fixture's skips are one marker under their merged
    conditions, so a branch added to it rewrites that guard, and the rewrite
    is the guard rules' to judge. Body skips share one name, so only their
    conditions pair them. Each is read with the constants the change leaves, as every D6
    reading is, and one the matrix cannot read leaves the environment open:
    the change did not add it. A test the gates it had already kept from
    every environment the matrix holds (a Python 2 only test,
    `skipif(sys.version_info[0] >= 3)`) gains no environment and loses
    none, so nothing is asked of it here; each added gate still has to run
    somewhere on its own.
    """
    after = _environment_gates(unit.after, raw, consts)
    if len(after) < 2:
        return True
    before = _environment_gates(unit.before, raw, consts) if unit.before is not None else []
    if before and not any(
            all(_fires(parts, env, consts) is not True for _, _, parts in before) for env in _ENV_MATRIX):
        return True
    same = Counter(key for key, _, _ in before)
    named = Counter(name for _, name, _ in before)
    kept, pending = [], []
    for key, name, parts in after:
        if same[key]:
            same[key] -= 1
            named[name] -= 1
            kept.append(parts)
        else:
            pending.append((name, parts))
    added = []
    for name, parts in pending:
        if named[name] and (is_setup_skip(name) or is_helper_skip(name) or is_rebound(name)):
            named[name] -= 1
            kept.append(parts)
        else:
            added.append(parts)
    return any(
        all(_fires(parts, env, consts) is False for parts in added)
        and all(_fires(parts, env, consts) is not True for parts in kept)
        for env in _ENV_MATRIX
    )


def compat_gate_for(unit: Unit | None, constants: dict[str, str] | None, name: str | None) -> bool:
    """Is the disabling marker this finding reports a qualified gate? (#208)

    A skip keyed on interpreter/OS version is a compat gate, not a kill.
    Three spellings earn the credit, all evaluated the same way: `skipif(cond)`,
    non-strict `xfail(cond)` (strict inverts the oracle instead of skipping
    it, which is not a gate), and an imperative `pytest.skip()`/`pytest.xfail()`
    /`self.skipTest()` under recorded `if` guards, in the test's body or in the
    setup it runs (#196 183.2). A mark a `pytestmark` binding carries is judged
    on its own condition and the binding's guard together (#260 Q2). A
    conftest's suite-level collection control earns it on its own guard
    (D-028, #209 Q1).

    D6 judges the added skip, so the hold is a fact about the finding's own
    marker, not about the unit. Every after-side marker with that name must
    qualify on its own guard, as row 71's weakest guard does for
    `collect_ignore`: an unguarded `pytest.skip` beside a guarded one is not
    held. A gate elsewhere on the unit lends nothing, and a finding with no
    marker of its own (`name` None: a unit gone, rows removed, a guard
    weakened or removed) gets no hold.
    """
    if name is None or unit is None or unit.after is None:
        return False
    markers = [m for m in unit.after.markers if m.name == name]
    if not markers:
        return False
    raw = constants or {}
    consts = _parse_constants(raw)
    if not all(_marker_is_compat_gate(m, raw, consts, credit=True) for m in markers):
        return False
    # Each gate runs somewhere; what the change added must leave somewhere
    # together with what was there (D-201).
    return _runs_somewhere_jointly(unit, raw, consts)


def guard_always_skips(guard: str, constants: dict[str, str] | None) -> bool:
    """Is this if-guard true in every environment checkwash considers?

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


def guard_can_be_false(guard: str | None, constants: dict[str, str] | None) -> bool:
    """Is this a guard at all: a condition that does not hold everywhere? (#209 Q4)

    A suite-level control with no guard that can be false is unguarded:
    `if True:` or `if sys.version_info >= (3, 0):` wrapped around a drop
    guards nothing. Judged by the evaluator D6 uses, so the parts checkwash
    cannot see stay unknown and only a guard true under every assignment of
    them guards nothing. An `except` block's condition that is not an
    expression still counts, as it always has.
    """
    if not guard:
        return False
    return not guard_always_skips(guard, constants)


def removed_skip_guard(name: str, unit, constants_before: dict[str, str] | None) -> str | None:
    """The condition a body skip ran under at base, when the diff removed it.

    THREATMODEL 54's other half (#196 183.2): `if sys.version_info < (3, 9):
    pytest.skip()` becoming a bare `pytest.skip()` keeps the call's name, so
    no marker is added, and the guard is gone rather than always true, so
    `guard_always_skips` has nothing to read. Every base instance of the call
    must have run under a condition that does not always fire, and some head
    instance must run under none (`skip_condition`). The first base condition
    comes back for the message; None otherwise, and for any marker whose
    guard does not say when it fires. A skip in the setup the unit runs is
    read the same way, by its own guard (183.2's second stage), and so is a
    mark a `pytestmark` binding carries, by the binding's guard (#260 Q2). A
    decorator's mark has no guard, so it never answers.

    A suite-level collection control is read by its guard too: removing the
    `if` around a `collect_ignore.append(...)` keeps the ignored paths, and a
    hook keeps its marker, so nothing else reports that the control now acts
    everywhere (#261 Q1). An unguarded effect added beside guarded ones
    leaves the hook no guard, and so does a constant `True` its reading
    drops: the same event (#261 Q2, Q3).
    """
    if (
        not (is_guarded_skip(name) or is_guarded_mark(name) or is_collection_control(name))
        or unit.before is None
        or unit.after is None
    ):
        return None
    conditions = []
    for m in unit.before.markers:
        if m.name != name:
            continue
        condition = skip_condition(m, unit.before)
        if condition is None or (m.guard and guard_always_skips(m.guard, constants_before)):
            return None
        conditions.append(condition)
    if conditions and any(
        m.name == name and skip_condition(m, unit.after) is None for m in unit.after.markers
    ):
        return conditions[0]
    return None


def unit_is_live(side, constants: dict[str, str] | None) -> bool:
    """Does this unit still run somewhere?

    `disabled = bool(markers)` was the load-bearing definition for every
    relocation credit (D2 moved assertions, D5 restructure mass, the
    split/rename budget) — and it called a test carried across files together
    with its own `skipif(WIN)` marker dead on arrival, which blocked three
    pure test-file splits in the FP corpus (click a391797d00, 700798252a).
    A unit is live when every marker on it is a D6-qualified compat gate:
    the same evaluator, the same constants, the same refusal for `skip` and
    always-true conditions. Bypass #9 (the sacrificial `@pytest.mark.skip`
    absorber) stays closed because an unconditional skip qualifies for
    nothing. Liveness keeps the reading from before D-201: a condition with
    a part checkwash cannot read is live unless it is true whatever that part
    is (`_marker_is_compat_gate`'s `credit`; THREATMODEL row 55).
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



"""Literal pytest hook effects that suppress execution or replace an outcome.

Hook names alone are not evidence: reporting/async plugins legitimately use
the same hooks. Follow the yielded Result/TestReport and the item callback,
without importing pytest or executing repository source. Unknown predicates
retain both paths; dead literal branches and nested uncalled functions do not.

A conftest can also swap what pytest runs for a no-op (#432). Three direct
spellings are read, each as its own effect key so a later write to one never
clears another (ruling 432.Q2):

- `item.runtest`, `item.obj` or `item._obj` written (assignment, `setattr`
  with a literal name, through simple aliases) on the `item`, `pyfuncitem` or
  `nextitem` parameter of a top-level, non-async hook in `_ITEM_HOOKS`:
  `item-runtest-replaced`, `nextitem-obj-replaced`, ...;
- `runtest` written on pytest's item classes (`pytest.Function`,
  `pytest.Item`, `_pytest.python.Function`,
  `_pytest.unittest.TestCaseFunction`): `Function-runtest-replaced`, ...;
- a native `unittest.TestCase` method in `TESTCASE_METHODS` written:
  `testcase-assertEqual-replaced`, ...

The class and TestCase writes are read at module scope (the `module`
pseudo-hook) and in the body of any top-level, non-async `pytest_*` function.

Only a lambda or an undecorated same-file function is read as the
replacement; one built by a call or bound from another object's attribute is
not (ruling 432.Q4). A callback or class-level `runtest` replacement is a
no-op when it does not delegate: no call anywhere in it (nested scopes and
defaults included) mentions a carrier of the original. Carriers are traced
(taint), not matched by spelling: the item and its aliases, pytest's item
classes, a class-level replacement's first parameter, every name bound or
written from an expression that mentions a carrier (a runner built from the
original, an original stored on the item or in a container, a default
parameter, a local function whose body mentions one), and every name bound in
a statement this reader does not enter. A TestCase replacement is a no-op
only with no call, raise or assert anywhere in it. A later write to the same
attribute that is not a no-op clears that attribute's effect only, as
`_outcome` does for `report.outcome`.

A write under a condition is reported as #84's controls are: the guard is
hashed into the marker name, and the marker carries none (ruling 432.Q5).
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field, replace
import hashlib

from checkwash.ir.astutil import stable_dump
from .exit_status_controls import exit_status_controls
from .setup_skip_controls import fixture_setup_controls, setup_skip_controls

_HOOKS = {"pytest_pyfunc_call", "pytest_runtest_call", "pytest_runtest_protocol",
          "pytest_runtest_makereport", "pytest_runtest_logreport"}

# Hooks whose `item`, `pyfuncitem` or `nextitem` parameter is read for a
# replaced callback (ruling 432.Q2). A closed list.
_ITEM_HOOKS = frozenset({"pytest_runtest_protocol", "pytest_runtest_setup", "pytest_runtest_call",
                         "pytest_runtest_makereport", "pytest_runtest_teardown", "pytest_pyfunc_call",
                         "pytest_itemcollected"})
_ITEM_PARAMS = {"item": "item", "pyfuncitem": "item", "nextitem": "nextitem"}
_ITEM_ATTRS = frozenset({"runtest", "obj", "_obj"})

# Native `unittest.TestCase` methods a replacement is read for: the public
# assertion methods of Python 3.11-3.13 with their deprecated aliases (removed
# in 3.12), `fail`, and the methods that run a test. `_getAssertEqualityFunc`
# and `failureException` are not methods a no-op replaces: the first returns a
# checker, the second is a class attribute (ruling 432.Q2, Q4).
TESTCASE_METHODS = frozenset({
    "assertAlmostEqual", "assertCountEqual", "assertDictContainsSubset", "assertDictEqual", "assertEqual",
    "assertFalse", "assertGreater", "assertGreaterEqual", "assertIn", "assertIs", "assertIsInstance",
    "assertIsNone", "assertIsNot", "assertIsNotNone", "assertLess", "assertLessEqual", "assertListEqual",
    "assertLogs", "assertMultiLineEqual", "assertNoLogs", "assertNotAlmostEqual", "assertNotEqual",
    "assertNotIn", "assertNotIsInstance", "assertNotRegex", "assertRaises", "assertRaisesRegex", "assertRegex",
    "assertSequenceEqual", "assertSetEqual", "assertTrue", "assertTupleEqual", "assertWarns", "assertWarnsRegex",
    # Deprecated aliases (Python 3.11).
    "assertAlmostEquals", "assertEquals", "assertNotAlmostEquals", "assertNotEquals", "assertNotRegexpMatches",
    "assertRaisesRegexp", "assertRegexpMatches", "assert_", "failIf", "failIfAlmostEqual", "failIfEqual",
    "failUnless", "failUnlessAlmostEqual", "failUnlessEqual", "failUnlessRaises",
    # Failing and running a test.
    "fail", "_baseAssertEqual", "_callTestMethod", "run", "__call__", "debug",
})

# What an import or an attribute of a known module binds.
_MODULES = {"unittest": "mod:unittest", "unittest.case": "mod:unittest.case", "pytest": "mod:pytest",
            "_pytest": "mod:_pytest", "_pytest.python": "mod:_pytest.python",
            "_pytest.unittest": "mod:_pytest.unittest"}
_CLASSES = {"unittest.TestCase": "cls:TestCase", "unittest.case.TestCase": "cls:TestCase",
            "pytest.Function": "cls:Function", "pytest.Item": "cls:Item",
            "_pytest.python.Function": "cls:Function", "_pytest.unittest.TestCaseFunction": "cls:TestCaseFunction"}
_ITEM_CLASSES = {"cls:Function": "Function", "cls:Item": "Item", "cls:TestCaseFunction": "TestCaseFunction"}


@dataclass
class _State:
    bindings: dict[str, str] = field(default_factory=dict)
    effects: dict[str, ast.AST] = field(default_factory=dict)
    called: bool = False
    stopped: bool = False
    guards: tuple[str, ...] = ()
    # Names bound to a replacement this reader reads: a lambda or an
    # undecorated same-file function.
    values: dict[str, ast.AST] = field(default_factory=dict)

    def copy(self):
        return replace(self, bindings=dict(self.bindings), effects=dict(self.effects), values=dict(self.values))


class _Lazy:
    """A value computed on first use: most conftests replace nothing, and
    tracing carriers is only needed for a replacement that is read."""

    def __init__(self, compute):
        self._compute, self._value = compute, None

    def get(self) -> frozenset[str]:
        if self._value is None:
            self._value = frozenset(self._compute())
        return self._value


_NO_TAINT = _Lazy(frozenset)


@dataclass(frozen=True)
class _Scope:
    hook: str
    wrapper: str | None = None
    # Read item callback writes (a hook in `_ITEM_HOOKS`)?
    item_writes: bool = False
    # Read item-class `runtest` and TestCase method writes?
    class_writes: bool = False
    # Carriers of the original bound in this scope.
    taint: _Lazy = _NO_TAINT


def _truth(node):
    if isinstance(node, ast.Constant):
        return bool(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        value = _truth(node.operand)
        return not value if value is not None else None
    return None


def _kind(node, state, hook, wrapper):
    if isinstance(node, ast.Name):
        return state.bindings.get(node.id)
    if isinstance(node, ast.Attribute):
        base = _kind(node.value, state, hook, wrapper)
        if base is not None and base.startswith("mod:"):
            dotted = base[4:] + "." + node.attr
            return _MODULES.get(dotted) or _CLASSES.get(dotted)
        return None
    if isinstance(node, ast.Yield):
        return "report" if hook == "pytest_runtest_makereport" and wrapper == "wrapper" else "result"
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        if node.func.attr == "get_result" and _kind(node.func.value, state, hook, wrapper) == "result":
            return "report" if hook == "pytest_runtest_makereport" else None
    return None


def _calls(node):
    """Expression calls only; constructing a callable does not run its body."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
        return
    if isinstance(node, ast.Call):
        yield node
    for child in ast.iter_child_nodes(node):
        yield from _calls(child)


def _expression(node, state, scope):
    hook, wrapper = scope.hook, scope.wrapper
    for call in _calls(node):
        fn = call.func
        if isinstance(fn, ast.Attribute):
            receiver = _kind(fn.value, state, hook, wrapper)
            if receiver == "item" and fn.attr in {"obj", "runtest"}:
                state.called = True
            if (receiver == "result" and fn.attr == "force_result" and call.args
                    and isinstance(call.args[0], ast.Constant) and call.args[0].value is None
                    and hook in {"pytest_runtest_call", "pytest_runtest_protocol"}):
                state.effects["exception-suppressed"] = call
        if (isinstance(fn, ast.Name) and fn.id == "setattr" and "setattr" not in state.bindings
                and len(call.args) >= 3 and isinstance(call.args[1], ast.Constant)
                and call.args[1].value == "outcome" and _kind(call.args[0], state, hook, wrapper) == "report"):
            _outcome(call.args[2], call, state)
        elif (isinstance(fn, ast.Name) and fn.id == "setattr" and "setattr" not in state.bindings
                and len(call.args) == 3 and not call.keywords and isinstance(call.args[1], ast.Constant)
                and isinstance(call.args[1].value, str)):
            _write(call.args[0], call.args[1].value, call.args[2], call, state, scope)


def _outcome(value, node, state):
    if isinstance(value, ast.Constant) and value.value == "passed":
        state.effects["report-passed"] = node
    else:
        state.effects.pop("report-passed", None)


def _bind(name, kind, value, state):
    """Bind a name: its kind for `_kind`, and the replacement it holds, if read."""
    state.bindings[name] = kind or "local"
    if value is None:
        state.values.pop(name, None)
    else:
        state.values[name] = value


def _readable(value, state):
    """The lambda or undecorated same-file function an expression is, or None."""
    if isinstance(value, ast.Lambda):
        return value
    if isinstance(value, ast.Name):
        return state.values.get(value.id)
    return None


def _import(stmt, state):
    for alias in stmt.names:
        if isinstance(stmt, ast.Import):
            if alias.asname:
                _bind(alias.asname, _MODULES.get(alias.name), None, state)
            else:
                top = alias.name.split(".", 1)[0]
                _bind(top, _MODULES.get(top), None, state)
        elif alias.name != "*":
            if stmt.module == "builtins" and stmt.level == 0 and (alias.asname or alias.name) == alias.name:
                # `from builtins import setattr` leaves the name the builtin
                # it was. Inside a hook `_hook_import` already leaves it; at
                # module scope binding it would hide `setattr(pytest.Function,
                # "runtest", ...)`.
                state.bindings.pop(alias.name, None)
                state.values.pop(alias.name, None)
                continue
            dotted = f"{stmt.module}.{alias.name}" if stmt.level == 0 and stmt.module else None
            kind = (_MODULES.get(dotted) or _CLASSES.get(dotted)) if dotted else None
            _bind(alias.asname or alias.name, kind, None, state)


def _hook_import(stmt, state):
    """An import inside a hook binds only the names it resolves to a known
    module or class. It may fail inside a `try`, so every other name keeps
    the binding it had, as #84's reader, which ignored hook imports, left it:
    rebinding `setattr`, `report`, `outcome` or `item` would hide a rewrite
    that really runs."""
    imported = _State()
    _import(stmt, imported)
    for name, kind in imported.bindings.items():
        if kind.startswith(("mod:", "cls:")):
            _bind(name, kind, None, state)


def _bind_statement(stmt, state, scope):
    """Apply what a definition, import or simple assignment binds. True when it was one."""
    if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
        _bind(stmt.name, "local", None if stmt.decorator_list else stmt, state)
    elif isinstance(stmt, ast.ClassDef):
        _bind(stmt.name, "local", None, state)
    elif isinstance(stmt, (ast.Import, ast.ImportFrom)):
        _import(stmt, state)
    elif isinstance(stmt, (ast.Assign, ast.AnnAssign)):
        value = stmt.value
        for target in stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]:
            if isinstance(target, ast.Name):
                _bind(target.id, _kind(value, state, scope.hook, scope.wrapper), _readable(value, state), state)
    else:
        return False
    return True


def _mentions(node, taint, resolve):
    """Does this expression mention a carrier of the original?"""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and sub.id in taint:
            return True
        if isinstance(sub, (ast.Name, ast.Attribute)) and resolve(sub) in _ITEM_CLASSES:
            return True
    return False


def _names(node):
    return {sub.id for sub in ast.walk(node) if isinstance(sub, ast.Name)}


def _taint(roots, seeds, resolve):
    """Every name bound or written, anywhere under `roots`, from an expression that mentions a carrier."""
    taint = set(seeds)
    nodes = [sub for root in roots for sub in ast.walk(root)]
    changed = True
    while changed:
        changed = False
        for node in nodes:
            new = set()
            if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                if node.value is not None and _mentions(node.value, taint, resolve):
                    for target in node.targets if isinstance(node, ast.Assign) else [node.target]:
                        new |= _names(target)
            elif isinstance(node, ast.NamedExpr):
                if _mentions(node.value, taint, resolve):
                    new.add(node.target.id)
            elif isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
                if _mentions(node.iter, taint, resolve):
                    new |= _names(node.target)
            elif isinstance(node, ast.withitem):
                if node.optional_vars is not None and _mentions(node.context_expr, taint, resolve):
                    new |= _names(node.optional_vars)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if _mentions(node, taint, resolve):
                    new.add(node.name)
            elif isinstance(node, ast.arguments):
                positional = node.posonlyargs + node.args
                pairs = list(zip(positional[len(positional) - len(node.defaults):], node.defaults))
                pairs += [(arg, default) for arg, default in zip(node.kwonlyargs, node.kw_defaults) if default]
                new |= {arg.arg for arg, default in pairs if _mentions(default, taint, resolve)}
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                # `saved.append(item.runtest)` stores the original in `saved`;
                # `pytest.skip(item.nodeid)` stores nothing in `pytest`.
                if (not (resolve(node.func.value) or "").startswith("mod:")
                        and any(_mentions(arg, taint, resolve) for arg in node.args + [kw.value for kw in node.keywords])):
                    new |= _names(node.func.value)
            if new - taint:
                taint |= new
                changed = True
    return taint


def _all_bound(node):
    """Every name a statement binds anywhere inside it."""
    names = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and isinstance(sub.ctx, (ast.Store, ast.Del)):
            names.add(sub.id)
        elif isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(sub.name)
        elif isinstance(sub, ast.alias):
            names.add(sub.asname or sub.name.split(".", 1)[0])
        elif isinstance(sub, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)) and sub.name:
            names.add(sub.name)
        elif isinstance(sub, ast.MatchMapping) and sub.rest:
            names.add(sub.rest)
    return names


def _unentered(statements):
    """Names bound in a statement `_walk` does not enter: a loop, `with`, `match` or `except` body."""
    names = set()
    for stmt in statements:
        if isinstance(stmt, ast.If):
            names |= _unentered(stmt.body + stmt.orelse)
        elif isinstance(stmt, ast.Try):
            names |= _unentered(stmt.body + stmt.orelse + stmt.finalbody)
            for handler in stmt.handlers:
                names |= _all_bound(handler)
        elif not isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Expr, ast.Assign,
                                   ast.AnnAssign, ast.AugAssign, ast.Return, ast.Raise, ast.Import,
                                   ast.ImportFrom, ast.Delete, ast.Pass)):
            names |= _all_bound(stmt)
    return names


def _resolver(state, scope):
    return lambda node: _kind(node, state, scope.hook, scope.wrapper)


def _delegates(replacement, seeds, resolve):
    """Does any call in the replacement mention a carrier of the original?"""
    taint = _taint([replacement], seeds, resolve)
    return any(isinstance(node, ast.Call) and _mentions(node, taint, resolve) for node in ast.walk(replacement))


def _callback_noop(value, state, scope, class_level):
    replacement = _readable(value, state)
    if replacement is None:
        return False
    seeds = set(scope.taint.get())
    if class_level:
        args = replacement.args
        positional = args.posonlyargs + args.args
        first = positional[0] if positional else args.vararg
        if first is not None:
            seeds.add(first.arg)
    return not _delegates(replacement, seeds, _resolver(state, scope))


def _testcase_noop(value, state):
    replacement = _readable(value, state)
    return replacement is not None and not any(
        isinstance(node, (ast.Call, ast.Raise, ast.Assert)) for node in ast.walk(replacement))


def _write(receiver, attr, value, node, state, scope):
    """A write (or, with no value, a delete) of `receiver.attr`."""
    kind = _kind(receiver, state, scope.hook, scope.wrapper)
    if scope.item_writes and kind in ("item", "nextitem") and attr in _ITEM_ATTRS:
        key = f"{kind}-{attr}-replaced"
        noop = value is not None and _callback_noop(value, state, scope, class_level=False)
    elif scope.class_writes and kind in _ITEM_CLASSES and attr == "runtest":
        key = f"{_ITEM_CLASSES[kind]}-runtest-replaced"
        noop = value is not None and _callback_noop(value, state, scope, class_level=True)
    elif scope.class_writes and kind == "cls:TestCase" and attr in TESTCASE_METHODS:
        key = f"testcase-{attr}-replaced"
        noop = value is not None and _testcase_noop(value, state)
    else:
        return
    if noop:
        state.effects[key] = node
    else:
        state.effects.pop(key, None)


def _walk(statements, states, scope):
    hook, wrapper = scope.hook, scope.wrapper
    for stmt in statements:
        next_states = []
        for state in states:
            if state.stopped:
                next_states.append(state)
                continue
            if isinstance(stmt, ast.If):
                truth = _truth(stmt.test)
                for chosen, body in ((True, stmt.body), (False, stmt.orelse)):
                    if truth is not None and truth != chosen:
                        continue
                    branch = state.copy()
                    if truth is None:
                        branch.guards += (("" if chosen else "not:") + stable_dump(stmt.test),)
                    next_states.extend(_walk(body, [branch], scope))
                continue
            if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                value = stmt.value
                if value is not None:
                    _expression(value, state, scope)
                for target in stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]:
                    if (isinstance(target, ast.Attribute) and target.attr == "outcome"
                            and _kind(target.value, state, hook, wrapper) == "report"):
                        _outcome(value, stmt, state)
                    elif isinstance(target, ast.Attribute) and value is not None:
                        _write(target.value, target.attr, value, stmt, state, scope)
                _bind_statement(stmt, state, scope)
            elif isinstance(stmt, (ast.Import, ast.ImportFrom)) and scope.hook != "module":
                _hook_import(stmt, state)
            elif _bind_statement(stmt, state, scope):
                pass
            elif isinstance(stmt, ast.Delete):
                for target in stmt.targets:
                    if isinstance(target, ast.Attribute):
                        _write(target.value, target.attr, None, stmt, state, scope)
            elif isinstance(stmt, ast.Return):
                if stmt.value is not None:
                    _expression(stmt.value, state, scope)
                if (hook in {"pytest_pyfunc_call", "pytest_runtest_protocol"} and not wrapper
                        and not state.called and isinstance(stmt.value, ast.Constant) and stmt.value.value is True):
                    state.effects["call-skipped"] = stmt
                state.stopped = True
            elif isinstance(stmt, ast.Raise):
                state.effects.clear()
                state.stopped = True
            elif isinstance(stmt, ast.Expr):
                _expression(stmt.value, state, scope)
            elif isinstance(stmt, ast.Try):
                # New-style wrappers may consume an AssertionError thrown back
                # through yield. Plain reporting/re-raising wrappers stay quiet.
                yield_in_body = any(isinstance(n, ast.Yield) for s in stmt.body for n in ast.walk(s))
                if wrapper == "wrapper" and hook == "pytest_runtest_call" and yield_in_body:
                    for handler in stmt.handlers:
                        caught = handler.type
                        names = {n.id for n in ast.walk(caught) if isinstance(n, ast.Name)} if caught else {"BaseException"}
                        if (names & {"AssertionError", "Exception", "BaseException"}
                                and all(isinstance(s, (ast.Pass, ast.Return)) for s in handler.body)):
                            state.effects["exception-suppressed"] = handler
                state_list = _walk(stmt.body + stmt.orelse + stmt.finalbody, [state], scope)
                next_states.extend(state_list)
                continue
            # Unsupported control flow has no positive execution proof. Do
            # not scan its descendants as though they all execute.
            next_states.append(state)
        states = next_states
        if len(states) > 64:
            return []
    return states


def _module_seeds(tree):
    """What module scope binds for every function to see: known modules and
    classes, and the replacements this reader reads. A name bound more than
    once to different things, or bound where `_walk` does not enter, is left
    out."""
    state, scope = _State(), _Scope("module")
    conflicts = _unentered(tree.body)

    def visit(statements):
        for stmt in statements:
            if isinstance(stmt, ast.If):
                visit(stmt.body)
                visit(stmt.orelse)
            elif isinstance(stmt, ast.Try):
                visit(stmt.body)
                visit(stmt.orelse)
                visit(stmt.finalbody)
            else:
                before = (dict(state.bindings), dict(state.values))
                if _bind_statement(stmt, state, scope):
                    for name in set(state.bindings) | set(before[0]):
                        if name in before[0] and (before[0][name], before[1].get(name)) != (
                                state.bindings.get(name), state.values.get(name)):
                            conflicts.add(name)

    visit(tree.body)
    kinds = {name: kind for name, kind in state.bindings.items()
             if name not in conflicts and kind.startswith(("mod:", "cls:"))}
    values = {name: value for name, value in state.values.items() if name not in conflicts}
    return kinds, values


def _hook_seeds(func, scope, state, module_taint):
    """A hook's carriers before tracing: module ones, names bound where `_walk`
    does not enter, and, where callbacks are read, the item parameters."""
    seeds = set(module_taint.get()) | _unentered(func.body)
    if scope.item_writes:
        seeds |= {name for name, kind in state.bindings.items() if kind in ("item", "nextitem")}
    return seeds


def runtime_controls(tree: ast.Module):
    """Return stable effect names and concrete source evidence for live hooks."""
    yield from setup_skip_controls(tree)
    yield from fixture_setup_controls(tree)
    # Session-level: code that forces pytest's exit status (#422).
    yield from exit_status_controls(tree)
    kinds, values = _module_seeds(tree)
    seeded = _State(bindings=dict(kinds), values=dict(values))
    module = _Scope("module", class_writes=True)
    module_taint = _Lazy(lambda: _taint(tree.body, _unentered(tree.body), _resolver(seeded, module)))
    # Module scope is the `module` pseudo-hook: it reads only the item-class
    # and TestCase writes (#432), and never mints a `fixture` name.
    walks = [(module.hook, tree.body, _State(), replace(module, taint=module_taint))]
    bindings = {}
    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            bindings[stmt.name] = stmt
        elif isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            for target in stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]:
                if isinstance(target, ast.Name):
                    bindings.pop(target.id, None)
    for name, func in bindings.items():
        plain = isinstance(func, ast.FunctionDef)
        if name not in _HOOKS and not (plain and name.startswith("pytest_")):
            continue
        wrapper = None
        for dec in func.decorator_list:
            if isinstance(dec, ast.Call):
                for kw in dec.keywords:
                    if kw.arg in {"wrapper", "hookwrapper"} and _truth(kw.value) is True:
                        wrapper = kw.arg
        state = seeded.copy()
        for arg in func.args.posonlyargs + func.args.args + func.args.kwonlyargs:
            state.bindings[arg.arg] = (_ITEM_PARAMS.get(arg.arg)
                                       or ("report" if arg.arg == "report" and name == "pytest_runtest_logreport"
                                           else "local"))
            state.values.pop(arg.arg, None)
        scope = _Scope(name, wrapper, item_writes=plain and name in _ITEM_HOOKS, class_writes=plain)
        taint = _Lazy(lambda func=func, scope=scope, initial=state.copy(): _taint(
            func.body, _hook_seeds(func, scope, initial, module_taint), _resolver(initial, scope)))
        walks.append((name, func.body, state, replace(scope, taint=taint)))
    for name, statements, state, scope in walks:
        for branch in _walk(statements, [state], scope):
            for effect, node in branch.effects.items():
                guard = hashlib.sha256("|".join(branch.guards).encode()).hexdigest()[:16]
                yield f"conftest.runtime.{name}.{effect}.{guard}", node

"""Skips a test reaches through a same-file helper (#272).

A test that calls `_later()` is skipped as surely as one that calls
`pytest.skip()` itself when `_later` always skips, and so is a test whose
fixture or xunit setup calls it. The helper is read as a setup callback is
read (`setup_outcome`): an outcome every call reaches is unconditional, and
one reached under a path condition keeps that condition (#196 183.2). The
call site's own conditions, and those of every helper call on the way, are
conjoined with it.

Only the same-file scopes `_executed_scopes` resolves for assertions are
followed (ruling 272.Q1): a function the module defines, or one nested in
the calling scope, or a lambda bound to a name, called by that plain name,
at most four calls deep. A method reached through `self`, a class, a
generator and a helper passed as an argument are not. The marker is
`helper.<function>.<effect>`, named for the helper that holds the outcome
(272.Q3).
"""
from __future__ import annotations

import ast

from checkwash.frontends.python.setup_skip_controls import (
    _conjunction,
    _generator,
    _names,
    body_bindings,
    body_outcome,
    outcome_call,
    setup_outcome,
)

# As deep as `_executed_scopes` follows a unit's helpers for assertions.
MAX_DEPTH = 4
_BODY_FIELDS = ("body", "orelse", "finalbody")
_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef)


def call_conditions(scope, condition) -> dict[int, tuple[str, ...]]:
    """id(call) -> the path conditions a call in `scope`'s own body runs under.

    Each enclosing `if` test, `not (...)` for an `else` branch, and an
    `except` block's own condition (`_handler_guard`): what a body skip's
    guard and `skip_condition` read. A loop, `with`, `match` or `try` body
    adds none, as a body skip's guard has none from them. Nested function
    and class bodies are left out: they run only when called, and a lambda's
    body is dead code to `_unreachable_ids`, whose live calls are the only
    ones asked about.
    """
    from checkwash.frontends.python.frontend import _handler_guard

    out: dict[int, tuple[str, ...]] = {}

    def expressions(stmt, conds):
        stack = [child for child in ast.iter_child_nodes(stmt) if not isinstance(child, ast.stmt)]
        while stack:
            node = stack.pop()
            if isinstance(node, (ast.ExceptHandler, ast.match_case)):
                continue
            if isinstance(node, ast.Call):
                out[id(node)] = conds
            stack.extend(child for child in ast.iter_child_nodes(node) if not isinstance(child, ast.stmt))

    def record(stmts, conds):
        for stmt in stmts:
            if isinstance(stmt, (*_DEFS, ast.ClassDef)):
                continue
            if isinstance(stmt, ast.If):
                test = condition(stmt.test)
                expressions(stmt, conds)
                record(stmt.body, (*conds, test))
                record(stmt.orelse, (*conds, f"not ({test})"))
                continue
            expressions(stmt, conds)
            for field in _BODY_FIELDS:
                body = getattr(stmt, field, None)
                if isinstance(body, list):
                    record([s for s in body if isinstance(s, ast.stmt)], conds)
            for handler in getattr(stmt, "handlers", None) or []:
                record(handler.body, (*conds, _handler_guard(stmt, handler)))
            for case in getattr(stmt, "cases", None) or []:
                record(case.body, conds)

    record(scope.body, ())
    return out


def _parameters(function) -> set[str]:
    args = function.args
    return {arg.arg for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg)
            if arg is not None}


def _shadowed(function) -> frozenset[str]:
    """The names a function binds itself: its parameters and its body's bindings."""
    return frozenset(_parameters(function) | _names(function.body))


def _lambda_outcome(target: ast.Lambda, bindings):
    """'skip' or 'xfail' when calling this lambda always ends in that outcome."""
    return outcome_call(target.body, {**bindings, **dict.fromkeys(_parameters(target))})


class HelperOutcomes:
    """One test module's helpers, each read once, for every scope that calls them.

    `module_scopes` maps the module's top-level names to their definitions,
    as `_executed_scopes` sees them. `condition` gives an expression's source
    text, and `fixtures` the module's literal fixtures, which settle branches
    in a helper as they do in a test (`_unreachable_ids`).
    """

    def __init__(self, module_scopes: dict, condition, fixtures=None):
        self.module_scopes = module_scopes
        self.condition = condition
        self.fixtures = fixtures
        self._of: dict[tuple[int, int], tuple] = {}
        self._scope: dict[tuple[int, int], tuple] = {}

    def candidate(self, node, local_scopes, shadowed=frozenset()):
        """The helper a call runs when it calls one by its plain name, or None.

        `shadowed` holds the names the calling scope binds itself, its
        parameters included: a module function of that name is not what the
        call runs there (`def test(offline): offline()` calls a fixture's
        value).
        """
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            return None
        name = node.func.id
        target = local_scopes.get(name)
        if target is None or (name in shadowed and self.module_scopes.get(name) is target):
            return None
        if isinstance(target, ast.Lambda) or (isinstance(target, _DEFS) and not _generator(target)):
            return target
        return None

    def reached(self, scope, bindings, calls, *, method=False, local_scopes):
        """(helper, effect, evidence, guard) for each outcome these calls in `scope` reach.

        `calls` are the calls in `scope` that run (not dead), by a plain name
        `local_scopes` holds; `bindings` resolves `scope`'s module names, and
        `method` reads its first parameter as the instance. Most calls reach
        a helper that ends in nothing, so the scope's own names and path
        conditions are worked out only for one that does.
        """
        found = []
        conditions = own = shadowed = None
        for node in calls:
            target = self.candidate(node, local_scopes)
            if target is None or target is scope:
                continue
            name = node.func.id
            nested = self.module_scopes.get(name) is not target
            if nested and own is None:
                # A nested function sees the names its enclosing scope binds.
                own = body_bindings(scope, bindings, method=method)
            inner = self.of(name, target, own if nested else bindings, frozenset({id(scope)}))
            if not inner:
                continue
            if shadowed is None:
                shadowed = _shadowed(scope)
            if not nested and name in shadowed:
                continue
            if conditions is None:
                conditions = call_conditions(scope, self.condition)
            path = conditions[id(node)]
            for helper, effect, evidence, conds in inner:
                found.append((helper, effect, evidence, _conjunction((*path, *conds))))
        return found

    def of_scope(self, scope, bindings, *, method=False):
        """`reached` for every call in `scope` that runs: what a setup provider's helpers end in."""
        _own, calls, local_scopes = self._calls(scope, bindings, method)
        return self.reached(scope, bindings, calls, method=method, local_scopes=local_scopes)

    def of(self, name, target, bindings, chain=frozenset()):
        """(helper, effect, evidence, conditions) for what calling `target` ends in.

        Its own outcome, and those of the helpers it calls on the way, each
        under the path conditions it is reached by inside `target`, its own
        guard last.
        """
        key = (id(target), id(bindings))
        if key not in self._of:
            self._of[key] = tuple(self._read(name, target, bindings, MAX_DEPTH - 1, chain | {id(target)}))
        return self._of[key]

    def _read(self, name, target, bindings, depth, chain):
        if isinstance(target, ast.Lambda):
            effect = _lambda_outcome(target, bindings)
            return [(name, effect, target.body, ())] if effect else []
        found = []
        outcome = setup_outcome(target, bindings, condition=self.condition)
        if outcome is not None:
            effect, evidence, guard = outcome
            found.append((target.name, effect, evidence, (guard,) if guard else ()))
            if guard is None:
                # Every call ends there: nothing it would call after runs.
                return found
        if depth <= 0:
            return found
        own, calls, local_scopes = self._calls(target, bindings)
        conditions = None
        shadowed = _shadowed(target)
        for node in calls:
            sub = self.candidate(node, local_scopes, shadowed)
            if sub is None or id(sub) in chain:
                continue
            nested = self.module_scopes.get(node.func.id) is not sub
            inner = self._read(node.func.id, sub, own if nested else bindings, depth - 1, chain | {id(sub)})
            if not inner:
                continue
            if conditions is None:
                conditions = call_conditions(target, self.condition)
            path = conditions[id(node)]
            for helper, effect, evidence, conds in inner:
                found.append((helper, effect, evidence, (*path, *conds)))
        return found

    def _calls(self, scope, bindings, method=False):
        """(scope's own bindings, the calls in it that run, the callables it sees), once per scope."""
        from checkwash.frontends.python.frontend import _local_scopes, _unreachable_ids

        key = (id(scope), id(bindings), method)
        if key not in self._scope:
            own = body_bindings(scope, bindings, method=method)
            dead = _unreachable_ids(scope, self.fixtures, lambda stmt: body_outcome(stmt, own) is not None)
            calls = [node for node in ast.walk(scope) if isinstance(node, ast.Call) and id(node) not in dead]
            self._scope[key] = (own, calls, _local_scopes(scope, self.module_scopes))
        return self._scope[key]

"""Skips a test reaches through a same-file or imported helper (#272).

A test that calls `_later()` is skipped as surely as one that calls
`pytest.skip()` itself when `_later` always skips, and so is a test whose
fixture or xunit setup calls it. The helper is read as a setup callback is
read (`setup_outcome`): an outcome every call reaches is unconditional, and
one reached under a path condition keeps that condition (#196 183.2). The
call site's own conditions, and those of every helper call on the way, are
conjoined with it.

In the test's own file, the scopes `_executed_scopes` resolves for
assertions are followed (ruling 272.Q1): a function the module defines, or
one nested in the calling scope, or a lambda bound to a name, called by
that plain name, at most four calls deep. A method reached through `self`,
a class, a generator and a helper passed as an argument are not. The
marker is `helper.<function>.<effect>`, named for the helper that holds the
outcome (272.Q3).

A function a test or conftest module defines, bound by a top-level
`from M import f` and called by that plain name, is followed into the
module the engine resolves for it (272.Q2, the second stage). A guarded
outcome keeps its condition closed over that module's names (#357): its
constants are inlined and other value reads use the fixed `helper.` prefix.
The marker keeps that module's evidence text and span (`Foreign`).
"""
from __future__ import annotations

import ast
from collections import Counter
from typing import NamedTuple

from checkwash.frontends.python.setup_skip_controls import (
    ConftestGuard,
    _conjunction,
    _generator,
    _names,
    body_bindings,
    body_outcome,
    module_bindings,
    outcome_call,
    setup_outcome,
)

# As deep as `_executed_scopes` follows a unit's helpers for assertions.
MAX_DEPTH = 4
_BODY_FIELDS = ("body", "orelse", "finalbody")
_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef)
# A module that spells none of these ends no call in a native outcome.
_OUTCOME_TOKENS = ("skip", "Skip", "xfail", "XFail")


class Foreign(NamedTuple):
    """An outcome's evidence in another file: its text and span there, and that file's path."""

    text: str
    span: tuple[int, int]
    path: str


class Imported(NamedTuple):
    """A call's target that a top-level `from M import f` binds, by its local name."""

    name: str


class ImportedHelpers:
    """The functions a test module imports by name with a reachable native outcome.

    `names` maps a local name to (module, original name); `resolve` reads
    that module and gives its outcomes with their conditions, or nothing.
    Each name is resolved once, here, and one that
    ends in nothing is dropped: a module that imports no such function
    reads as it did before.
    """

    def __init__(self, names: dict[str, tuple[str, str]], resolve):
        self._outcomes: dict[str, tuple] = {}
        for name, (module, original) in names.items():
            found = tuple(resolve(module, original) or ())
            if found:
                self._outcomes[name] = found
        self.names = {name: names[name] for name in self._outcomes}

    def __contains__(self, name) -> bool:
        return name in self._outcomes

    def outcomes(self, name: str) -> tuple:
        return self._outcomes[name]


def imported_helper_names(tree: ast.Module) -> dict[str, tuple[str, str]]:
    """Local name -> (module, original) for each name a top-level `from M import f` binds alone.

    The imports `_top_level_from_imports` reads, which the engine resolves
    for an imported assertion helper too. A name any other top-level
    statement binds as well is not followed: which binding a call sees
    depends on order. Nor is any name, once a star import may bind it.
    """
    from checkwash.frontends.python.frontend import _top_level_from_imports

    names = _top_level_from_imports(tree)
    if not names:
        return {}
    counts: Counter = Counter()
    for statement in tree.body:
        if isinstance(statement, ast.ImportFrom) and any(alias.name == "*" for alias in statement.names):
            return {}
        counts.update(_names([statement]))
    return {name: target for name, target in names.items() if counts[name] == 1}


class HelperGuard(ConftestGuard):
    """Close imported-helper guards with a fixed prefix and lexical local bindings.

    Nested helpers may bind their own parameters, or close over an enclosing
    helper's locals. Neither is the module constant of the same name. This
    does not resolve arguments or imports and does not change conftest scope
    handling. Attribute roots and call targets retain #351's stated limits.
    """

    _prefix = 'helper'

    def __init__(self, tree, text_of, span_of):
        super().__init__(tree, text_of, span_of)
        # A conditional assignment, augmented update, deletion, unpacking or
        # definition can overwrite a plain module constant. Keep such names
        # unknown rather than reusing the earlier defining expression. Plain
        # assignments retain the existing last-assignment closure behavior.
        uncertain = set()
        for statement in tree.body:
            plain = (
                isinstance(statement, ast.Assign)
                and all(isinstance(target, ast.Name) for target in statement.targets)
            ) or (
                isinstance(statement, ast.AnnAssign)
                and isinstance(statement.target, ast.Name)
                and statement.value is not None
            )
            if not plain:
                uncertain.update(_names([statement], mutated=True))
        self._constants = {
            name: value for name, value in self._constants.items() if name not in uncertain
        }
        stack = [(tree, frozenset())]
        while stack:
            node, bound = stack.pop()
            if isinstance(node, _DEFS):
                bound = bound | _shadowed(node)
            elif isinstance(node, ast.Lambda):
                bound = bound | frozenset(_parameters(node))
            if isinstance(node, ast.Name):
                self._locals[id(node)] = bound
            stack.extend((child, bound) for child in ast.iter_child_nodes(node))


class HelperModule:
    """A module a test imports a helper from, read for what calling each of its functions ends in.

    Its own functions are followed as a test module's are, with its own
    names, branch constants and same-file helpers. What they import is not
    followed: one hop into the tree. A conditional outcome is closed over
    this module before it is combined with the importing call site's guard.
    """

    def __init__(self, data: bytes, path: str):
        from checkwash.frontends.python.branch_constants import literal_fixtures
        from checkwash.frontends.python.frontend import _Offsets, normalize_source

        self.path = path
        self._memo: dict[str, tuple] = {}
        self._scopes: dict[str, ast.AST] = {}
        raw = normalize_source(data)
        if not any(token in raw for token in _OUTCOME_TOKENS):
            return
        try:
            tree = ast.parse(raw)
        except (SyntaxError, RecursionError, ValueError, MemoryError):
            return
        for node in tree.body:
            if isinstance(node, (*_DEFS, ast.ClassDef)):
                self._scopes[node.name] = node
            elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Lambda):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        self._scopes[target.id] = node.value
        self._text = _Offsets(raw)
        self._bindings = module_bindings(tree, mutated=False)
        self._helpers = HelperOutcomes(
            self._scopes, HelperGuard(tree, self._text.seg, self._text.span), literal_fixtures(tree)
        )

    def outcomes(self, name: str) -> tuple:
        """(helper, effect, Foreign, conditions) for each outcome `name` reaches."""
        if name not in self._memo:
            target = self._scopes.get(name)
            found = ()
            if isinstance(target, ast.Lambda) or (isinstance(target, _DEFS) and not _generator(target)):
                found = tuple(
                    (helper, effect, self._foreign(evidence, helper), conds)
                    for helper, effect, evidence, conds in self._helpers.of(name, target, self._bindings)
                )
            self._memo[name] = found
        return self._memo[name]

    def _foreign(self, evidence, helper: str) -> Foreign:
        return Foreign(self._text.seg(evidence) or helper, self._text.span(evidence), self.path)


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
    in a helper as they do in a test (`_unreachable_ids`). `imported` holds
    the functions other modules define that the module imports by name
    (`ImportedHelpers`), or None.
    """

    def __init__(self, module_scopes: dict, condition, fixtures=None, imported: ImportedHelpers | None = None):
        self.module_scopes = module_scopes
        self.condition = condition
        self.fixtures = fixtures
        self.imported = imported
        self._of: dict[tuple[int, int], tuple] = {}
        self._scope: dict[tuple[int, int], tuple] = {}

    def candidate(self, node, local_scopes, shadowed=frozenset()):
        """The helper a call runs when it calls one by its plain name, or None.

        `shadowed` holds the names the calling scope binds itself, its
        parameters included: a module function of that name is not what the
        call runs there (`def test(offline): offline()` calls a fixture's
        value). A name only an import binds gives `Imported`.
        """
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            return None
        name = node.func.id
        target = local_scopes.get(name)
        if target is None:
            if self.imported is not None and name in self.imported and name not in shadowed:
                return Imported(name)
            return None
        if name in shadowed and self.module_scopes.get(name) is target:
            return None
        if isinstance(target, ast.Lambda) or (isinstance(target, _DEFS) and not _generator(target)):
            return target
        return None

    def reached(self, scope, bindings, calls, *, method=False, local_scopes):
        """(helper, effect, evidence, guard) for each outcome these calls in `scope` reach.

        `calls` are the calls in `scope` that run (not dead), by a plain name
        `local_scopes` holds or an imported helper's; `bindings` resolves
        `scope`'s module names, and `method` reads its first parameter as the
        instance. Most calls reach a helper that ends in nothing, so the
        scope's own names and path conditions are worked out only for one
        that does.
        """
        found = []
        conditions = own = shadowed = None
        for node in calls:
            target = self.candidate(node, local_scopes)
            if target is None or target is scope:
                continue
            name = node.func.id
            if isinstance(target, Imported):
                # Another module's function: what every call of it reaches,
                # unless the calling scope binds the name itself.
                inner = self.imported.outcomes(name)
                nested = False
            else:
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
            if sub is None:
                continue
            if isinstance(sub, Imported):
                inner = self.imported.outcomes(sub.name)
            elif id(sub) in chain:
                continue
            else:
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

"""The producer of a fixture a test requests by parameter (#471).

SPEC §5 clause 1 grants repair evidence for a symbol the test calls, and a
call is one written in the unit's own body. A test that gets its subject
from a pytest fixture calls nothing that builds it: the fixture does. Ruling
471 (owner, 2026-10-16) counts one call of such a fixture as the test's, for
the findings whose before-side assertion reads the fixture's value:

- Q1 (c), what a fixture contributes: only its producer, the call whose
  value it returns or yields, directly (`return C(...)`, `yield C(...)`) or
  through one plain local binding (`p = C(...)`, then `yield p`), from a
  site under no branch, loop, `match`, or `try` handler, `else` or `finally`.
  The other calls in its body do not count, the producer's own arguments included.
- The producer is resolved through the fixture file's own imports. Its root
  is a name whose final top-level binding in that file is an `import` or an
  absolute `from ... import` (`import_modules`), and the modules that
  statement names are the only ones a changed symbol may come from
  (`gating._symbol_match`, D-046). A root the fixture binds itself (a
  parameter, as in `return app.test_client()`, or a local) resolves to
  nothing, and so does a name a top-level `if` or `try` binds.
- Q2 (a), how far: one level, for a fixture the unit requests by parameter,
  resolved as pytest resolves it for that test (`unit_producers`): the
  innermost class first, then the enclosing classes and the module, then
  the conftest chain, nearest first (`ConftestLevel.producers`). A name a
  `parametrize` on the unit, its classes or its module supplies directly
  runs no fixture. A level that binds the name in a way this reading does
  not follow (`SetupScope.opaque`), a star import, an unreadable conftest,
  or a class with a base or keyword this reading does not follow, stops the
  lookup, with no producer. Fixtures of fixtures do not count, nor do an
  `autouse` fixture and a `usefixtures` mark the test does not also request
  by parameter.

Which findings take the producer (Q3 (b)) and which rules (Q4 (a)) is
gating's call; this module only reads it.
"""
from __future__ import annotations

import ast

from checkwash.ir.astutil import dotted_name

from .setup_skip_controls import (
    _direct_arguments,
    _executed,
    _fixture,
    _names,
    _plain_binding,
    _pytestmark,
    _requests,
)


def import_modules(tree: ast.Module) -> dict[str, tuple[str, ...]]:
    """Each name whose final top-level binding is an import -> the modules that import names.

    `import a.b` binds `a` to the module it names (`a.b`), `import a.b as c`
    binds `c` to it, and `from m import x` binds `x` to `m`. A relative
    import names no module this reading can place, and a star import after
    a name's binding may rebind it, so neither resolves. A name whose final
    binding is anything else (an assignment, a def, or an import under a
    top-level `if` or `try`) does not resolve either.
    """
    last: dict[str, tuple[int, ast.stmt]] = {}
    star = -1
    for index, statement in enumerate(tree.body):
        if isinstance(statement, ast.ImportFrom) and any(alias.name == "*" for alias in statement.names):
            star = index
        for name in _names([statement]):
            last[name] = (index, statement)
    found: dict[str, tuple[str, ...]] = {}
    for name in sorted(last):
        index, statement = last[name]
        if index < star:
            continue
        modules: list[str] = []
        if isinstance(statement, ast.Import):
            modules = sorted({
                alias.name for alias in statement.names
                if (alias.asname or alias.name.split(".")[0]) == name
            })
        elif (isinstance(statement, ast.ImportFrom) and statement.module and not statement.level
              and any(alias.name != "*" and (alias.asname or alias.name) == name for alias in statement.names)):
            modules = [statement.module]
        if modules:
            found[name] = tuple(modules)
    return found


def _binders(function, name: str) -> list[ast.AST]:
    """Every node in `function`'s own scope that binds `name`.

    A store or delete, an import alias, an `except ... as` or match capture,
    a `global` or `nonlocal` declaration, and a nested def or class of that
    name. Nested bodies and lambdas are not entered; a comprehension's
    target counts, which only errs toward no evidence. The frontend also
    reads it for a fixture parameter the unit binds again (#471 Q3).
    """
    found: list[ast.AST] = []
    stack: list[ast.AST] = list(function.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name == name:
                found.append(node)
            continue
        if isinstance(node, ast.Lambda):
            continue
        if isinstance(node, ast.Name):
            if node.id == name and isinstance(node.ctx, (ast.Store, ast.Del)):
                found.append(node)
        elif isinstance(node, ast.alias):
            if (node.asname or node.name.split(".")[0]) == name:
                found.append(node)
        elif isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)):
            if node.name == name:
                found.append(node)
        elif isinstance(node, ast.MatchMapping):
            if node.rest == name:
                found.append(node)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            if name in node.names:
                found.append(node)
        stack.extend(ast.iter_child_nodes(node))
    return found


_COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)


def assertion_names(node: ast.AST) -> tuple[frozenset[str], frozenset[str]]:
    """(read, shadowed): the `Name` ids in `node`, an assertion's expression, by what binds them (#471 Q3).

    An occurrence inside a lambda whose parameters bind its name, or inside a
    comprehension one of whose targets names it, is that lambda's or that
    comprehension's own variable, not the name the test binds. `read` holds each
    name with an occurrence of neither kind, `shadowed` each name all of whose
    occurrences are of one. A comprehension is taken whole, its first iterable
    (which Python evaluates outside it) and a name a target only reads (`ledger`
    in `for ledger.x in rows`) included, erring toward no evidence; a lambda's
    defaults are read outside it, as Python reads them. The frontend reads it for `fixture_reads`.
    """
    read: set[str] = set()
    seen: set[str] = set()
    stack: list[tuple[ast.AST, frozenset[str]]] = [(node, frozenset())]
    while stack:
        current, bound = stack.pop()
        if isinstance(current, ast.Name):
            seen.add(current.id)
            if current.id not in bound:
                read.add(current.id)
            continue
        if isinstance(current, ast.Lambda):
            args = current.args
            stack.extend((default, bound) for default in (*args.defaults, *args.kw_defaults) if default is not None)
            stack.append((current.body, bound | {
                arg.arg for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg)
                if arg is not None
            }))
            continue
        if isinstance(current, _COMPREHENSIONS):
            bound = bound | {
                target.id for generator in current.generators for target in ast.walk(generator.target)
                if isinstance(target, ast.Name)
            }
        stack.extend((child, bound) for child in ast.iter_child_nodes(current))
    return frozenset(read), frozenset(seen - read)


def nested_bound_names(node: ast.AST) -> frozenset[str]:
    """The names a lambda's parameters or a comprehension's targets bind anywhere in `node` (#471, D-155 reading 3).

    `node` is a value the unit assigns. When the frontend's `fixture_reads`
    follows the unit's own assignments, these names are dropped from what
    the assignment leads to: in `result = (lambda ledger: ledger.fee)(make())`,
    `ledger` is the lambda's own variable, not the fixture, so `result` leads
    to `make` only. A name that also occurs outside the lambda or
    comprehension that binds it is dropped too, as is a name a target only
    reads, erring toward no evidence.
    """
    found: set[str] = set()
    for inner in ast.walk(node):
        if isinstance(inner, ast.Lambda):
            args = inner.args
            found.update(
                arg.arg for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg)
                if arg is not None
            )
        elif isinstance(inner, _COMPREHENSIONS):
            found.update(
                target.id for generator in inner.generators for target in ast.walk(generator.target)
                if isinstance(target, ast.Name)
            )
    return frozenset(found)


def _unconditional(body: list[ast.stmt]) -> list[ast.stmt]:
    """The statements of `body`, and of each `with` or `try` body reached from it through such bodies only.

    A branch, a loop and a `match` are not entered, since a statement there may
    not run; nor, erring toward no evidence, a `try`'s handlers, `else` and `finally`.
    """
    found: list[ast.stmt] = []
    stack = list(body)
    while stack:
        statement = stack.pop()
        found.append(statement)
        if isinstance(statement, (ast.With, ast.AsyncWith, ast.Try, ast.TryStar)):
            stack.extend(statement.body)
    return found


def _assigned_value(nodes: list[ast.AST], target: ast.AST) -> ast.expr | None:
    """The value a plain assignment with `target` as its only target assigns, or None."""
    for node in nodes:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and node.targets[0] is target:
            return node.value
        if isinstance(node, ast.AnnAssign) and node.target is target and node.value is not None:
            return node.value
    return None


def producer(function, modules: dict[str, tuple[str, ...]]) -> tuple[str, tuple[str, ...]] | None:
    """(dotted callee, modules) of the call fixture `function` returns or yields, or None.

    The value comes from one site in the function's own body, outside any
    nested def, class or lambda: its only `yield <value>` when it yields
    (a generator fixture's value is what it yields first), else its only
    `return <value>`. A `yield from`, a bare `yield`, a second site of
    either kind, or no site at all gives no producer. The site must be a
    `return` or `yield` statement of the body itself, or of a `with` or
    `try` body reached from it (`_unconditional`). One under an `if`, a
    loop or a `match` may not run, and one in a `try`'s handler, `else` or
    `finally` is left out too, erring toward no evidence: each gives no
    producer. The value is a call with a dotted callee, or a name, not a
    parameter, that the body binds exactly once, by a plain assignment of
    such a call. The callee's root must be a name `modules` resolves
    (`import_modules` of the fixture's file) that the function does not
    bind itself.
    """
    args = function.args
    params = {
        arg.arg for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg)
        if arg is not None
    }
    nodes = list(_executed(function.body))
    if any(isinstance(node, ast.YieldFrom) for node in nodes):
        return None
    yields = [node for node in nodes if isinstance(node, ast.Yield)]
    sites = yields or [node for node in nodes if isinstance(node, ast.Return)]
    if len(sites) != 1 or sites[0].value is None:
        return None
    site = sites[0]
    if not any(
        statement is site or (isinstance(statement, ast.Expr) and statement.value is site)
        for statement in _unconditional(function.body)
    ):
        return None
    value = site.value
    if isinstance(value, ast.Name):
        if value.id in params:
            return None
        binders = _binders(function, value.id)
        if len(binders) != 1:
            return None
        value = _assigned_value(nodes, binders[0])
    if not isinstance(value, ast.Call):
        return None
    name = dotted_name(value.func)
    if not name:
        return None
    root = name.split(".", 1)[0]
    if root in params or _binders(function, root):
        return None
    found = modules.get(root)
    return (name, found) if found else None


class ProducerScope:
    """The fixtures one module or class body defines, each with its producer or None (#471).

    `producers`, `opaque`, `star` and `direct` are read as `SetupScope`
    reads its fixtures: only a name's final binding provides one, a name
    bound some other way is opaque, and `direct` holds the argnames a class
    or module `parametrize` supplies. `based`: a class with a base other
    than a plain `object`, or with a keyword, which may inherit or receive
    any fixture this reading does not see. `bindings` are the module's
    (`setup_skip_controls.module_bindings`); `modules` is the module's
    `import_modules`, through which a producer's root resolves, in a class
    body too.
    """

    def __init__(self, body, bindings, modules, *, in_class=False, marks=(), bases=(), keywords=()):
        self.bindings = bindings
        self.modules = modules
        self.direct = frozenset(_direct_arguments([*marks, *_pytestmark(body)], bindings))
        last: dict[str, ast.stmt] = {}
        for statement in body:
            for name in _names([statement]):
                last[name] = statement
        self.opaque = frozenset(name for name, statement in last.items() if not _plain_binding(statement, bindings))
        self.star = any(
            isinstance(statement, ast.ImportFrom) and any(alias.name == "*" for alias in statement.names)
            for statement in body
        )
        self.based = in_class and (bool(keywords) or not (
            "object" not in bindings
            and all(isinstance(base, ast.Name) and base.id == "object" for base in bases)
        ))
        self.producers: dict[str, tuple[str, tuple[str, ...]] | None] = {}
        for statement in body:
            if (not isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
                    or last.get(statement.name) is not statement):
                continue
            fixture = _fixture(statement, bindings)
            if fixture is not None:
                self.producers[fixture[0]] = producer(statement, modules)
        self.fixtures = self.producers


def unit_producers(scopes, function, *, method, chain=()) -> tuple[tuple[str, str, tuple[str, ...]], ...]:
    """(parameter, producer, modules) for each fixture `function` requests by parameter that has one.

    `scopes` runs from the module to the innermost enclosing class
    (`ProducerScope`), and `chain` holds the conftest levels above the
    module, nearest first (`ConftestLevel`). A requested name is an argument
    without a default, the instance and `request` excepted
    (`setup_skip_controls._requests`). It resolves at the first level that
    defines it, and stops at the first own level that binds it some other
    way, holds a star import or is `based`, and at the first conftest that
    binds it some other way or cannot be read. Sorted by parameter.
    """
    static = any(isinstance(mark, ast.Name) and mark.id == "staticmethod" for mark in function.decorator_list)
    requested = _requests(function, receiver=method and not static)
    if not requested:
        return ()
    direct = set(_direct_arguments(function.decorator_list, scopes[0].bindings))
    for scope in scopes:
        direct |= scope.direct
    levels = [*reversed(scopes), *chain]
    own = len(scopes)
    found = []
    for name in sorted(requested - direct):
        for index, level in enumerate(levels):
            if name in level.fixtures:
                made = level.producers.get(name)
                if made is not None:
                    found.append((name, made[0], made[1]))
                break
            if name in level.opaque or level.star or (index < own and level.based):
                break
    return tuple(found)

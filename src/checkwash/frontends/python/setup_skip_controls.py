"""Native pytest setup callbacks that skip a collected test.

Only an unconditional native skip/xfail supplies this evidence: a call to
`pytest.skip`/`pytest.xfail` (or `self.skipTest`), or a raise of the exception
they raise or of unittest's `SkipTest`, with plain arguments, as a statement
every run of the callback executes before it can return, raise or hand control
to the test. Unknown module execution, decorators, bindings, control flow and
hook signatures do not establish that the setup callback suppresses a test.

That one reading (`callback_outcome`) is shared by every path a unit's setup
runs through (issue #172): the closed `pytest_runtest_setup` hook proof below,
conftest fixtures as suite-level runtime controls (`fixture_setup_controls`),
and a test module's own fixtures and xunit setup callbacks as markers on the
units that reach them (`SetupScope`, `setup_outcomes`).

A guarded skip is not this evidence: its guard is its justification, and an
environment condition is not something a source reading can settle. A unit's
own setup still records it, with that guard (`setup_outcome`, #196 183.2), so
it is judged as a guarded skip in a test body is. The conftest paths read only
the unconditional outcome until their requests are resolved
(196.followup.conftest-request-side).
"""
from __future__ import annotations

import ast

from checkwash.ir.astutil import dotted_name


def _body(statements):
    return [statement for statement in statements if not (
        isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant)
        and type(statement.value.value) is str)]


def _resolve(node, bindings):
    name = dotted_name(node)
    if not name:
        return None
    first, dot, rest = name.partition('.')
    target = bindings.get(first)
    return target + dot + rest if target else None


def _decorator(node, bindings, target, keywords):
    if not isinstance(node, ast.Call):
        return _resolve(node, bindings) == target and target == 'pytest.fixture'
    return (_resolve(node.func, bindings) == target and not node.args
            and len({kw.arg for kw in node.keywords}) == len(node.keywords)
            and all(kw.arg in keywords and isinstance(kw.value, ast.Constant)
                    and type(kw.value.value) is bool for kw in node.keywords))


# Native calls that end setup in a skip or xfail outcome, and the exceptions
# those calls raise. pytest's unittest plugin reports unittest's SkipTest as a
# skip wherever it is raised, so raising it is the same act spelled through
# the standard library. `importorskip` is deliberately absent: whether it
# skips depends on what is installed, which no reading of the source decides.
_OUTCOME_CALLS = {
    'pytest.skip': 'skip', 'pytest.xfail': 'xfail', 'self.skipTest': 'skip',
    '_pytest.outcomes.skip': 'skip', '_pytest.outcomes.xfail': 'xfail',
}
_OUTCOME_RAISES = {
    'pytest.skip.Exception': 'skip', 'pytest.xfail.Exception': 'xfail',
    '_pytest.outcomes.Skipped': 'skip', '_pytest.outcomes.XFailed': 'xfail',
    'unittest.SkipTest': 'skip', 'unittest.case.SkipTest': 'skip',
}
_OUTCOME_KEYWORDS = frozenset({'reason', 'msg', 'allow_module_level'})
_NATIVE_MODULES = frozenset({'pytest', '_pytest', '_pytest.outcomes', 'unittest', 'unittest.case'})
# An argument that calls, awaits, yields, binds or unpacks runs code before
# the outcome, and that code could leave first.
_IMPURE = (ast.Call, ast.Await, ast.Yield, ast.YieldFrom, ast.NamedExpr, ast.Lambda, ast.Starred)
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
_LEAVES = (ast.Return, ast.Raise, ast.Yield, ast.YieldFrom)


def _plain(call):
    """At most a reason and the known flags, computed without running code."""
    values = [*call.args, *(keyword.value for keyword in call.keywords)]
    return (len(call.args) <= 1
            and all(keyword.arg in _OUTCOME_KEYWORDS for keyword in call.keywords)
            and len({keyword.arg for keyword in call.keywords}) == len(call.keywords)
            and not any(isinstance(node, _IMPURE) for value in values for node in ast.walk(value)))


def outcome_call(node, bindings):
    """'skip' or 'xfail' when `node` is a native outcome call with plain arguments."""
    if not isinstance(node, ast.Call) or not _plain(node):
        return None
    return _OUTCOME_CALLS.get(_resolve(node.func, bindings))


def _outcome(statement, bindings):
    """(effect, evidence) when this statement itself ends setup in an outcome."""
    if isinstance(statement, ast.Raise):
        raised = statement.exc
        if isinstance(raised, ast.Call) and _plain(raised):
            raised = raised.func
        # `from None` only hides the context: nothing runs and the outcome
        # propagates unchanged. Any other cause is an expression evaluated
        # first, which could raise instead, so it stays unproved.
        if raised is None or statement.cause is not None and not (
                isinstance(statement.cause, ast.Constant) and statement.cause.value is None):
            return None
        effect = _OUTCOME_RAISES.get(_resolve(raised, bindings))
        return (effect, statement) if effect else None
    if isinstance(statement, (ast.Expr, ast.Return, ast.Assign, ast.AnnAssign)):
        effect = outcome_call(statement.value, bindings)
        return (effect, statement.value) if effect else None
    return None


def _executed(nodes):
    """Every node these run, without entering nested function or class bodies."""
    stack = [node for node in nodes if not isinstance(node, _SCOPES)]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(child for child in ast.iter_child_nodes(node) if not isinstance(child, _SCOPES))


def _may_leave(statements):
    """Can control return, raise or hand over to the test inside these?"""
    return any(isinstance(node, _LEAVES) for node in _executed(statements))


def _generator(function):
    return any(isinstance(node, (ast.Yield, ast.YieldFrom)) for node in _executed(function.body))


def _fold(test):
    # Imported late: the frontend imports this module.
    from .frontend import _static_truth

    return _static_truth(test)


def _reached(statements, bindings):
    """(the first outcome every run reaches or None, whether later code may not run)."""
    for statement in statements:
        found = _outcome(statement, bindings)
        if found is not None:
            return found, True
        branch = None
        if isinstance(statement, ast.If):
            truth = _fold(statement.test)
            if truth is not None:
                branch = statement.body if truth else statement.orelse
        elif isinstance(statement, ast.Try) and not statement.handlers and not _may_leave(statement.finalbody):
            # No handler can catch the outcome and no `finally` can return
            # over it, so the body runs as straight-line code.
            branch = statement.body + statement.finalbody
        if branch is not None:
            found, stopped = _reached(branch, bindings)
            if found is not None or stopped:
                return found, True
        elif _may_leave([statement]):
            return None, True
    return None, False


def _names(nodes, *, mutated=False):
    """Names these statements bind; with `mutated`, also roots of assigned attributes."""
    names = set()
    stack = list(nodes)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
            continue
        if isinstance(node, ast.Lambda):
            continue
        if isinstance(node, (ast.Name, ast.Attribute, ast.Subscript)) and isinstance(node.ctx, (ast.Store, ast.Del)):
            root = node
            while isinstance(root, (ast.Attribute, ast.Subscript)):
                root = root.value
            if isinstance(root, ast.Name) and (root is node or mutated):
                names.add(root.id)
        elif isinstance(node, ast.alias):
            names.add(node.asname or node.name.split('.')[0])
        elif isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)) and node.name:
            names.add(node.name)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            names.update(node.names)
        stack.extend(ast.iter_child_nodes(node))
    return names


def _local(function, bindings, receiver):
    args = function.args
    positional = [*args.posonlyargs, *args.args]
    params = [arg.arg for arg in (*positional, *args.kwonlyargs, args.vararg, args.kwarg) if arg is not None]
    stored = _names(function.body)
    local = {**bindings, **dict.fromkeys([*params, *sorted(stored)])}
    if receiver and positional and positional[0].arg not in stored:
        local[positional[0].arg] = 'self'
    return local


def callback_outcome(function, bindings, *, receiver=False):
    """(effect, evidence) for the first native outcome every call of `function` reaches.

    `bindings` maps module names to native dotted targets (None for anything
    else). A name the callback binds anywhere is local to its whole body, so
    it shadows the module binding. `receiver` reads the first positional
    parameter as the instance, which is how `self.skipTest` resolves.
    """
    return _reached(_body(function.body), _local(function, bindings, receiver))[0]


# How a walk over statements ends: every path ends there (in an outcome, or by
# leaving), control falls through to what follows, or some path may leave
# under a condition the walk does not follow.
_ENDS, _FALLS, _STOPS = 'ends', 'falls', 'stops'


def _handler_condition(try_statement, handler):
    # Imported late: the frontend imports this module.
    from .frontend import _handler_guard

    return _handler_guard(try_statement, handler)


def _guarded(statements, bindings, conds, sites, condition):
    """Walk `statements` under the path condition `conds`, a tuple of source texts.

    Appends (effect, evidence, conds) for each native outcome a run reaches
    whenever its path condition holds, and returns how the walk ends and
    whether some path left without an outcome. The path condition is the one
    guard definition of #196 183.2: each enclosing `if` test, `not (...)` for
    an `else` branch and for the code after a branch that always ends, and an
    `except` block's own condition (`_handler_guard`, as a conftest's
    `collect_ignore` records it). A path this reading cannot follow ends the
    walk rather than widening a guard: code after a branch that may leave
    without always leaving, and any other compound statement that may leave.
    Loop, `with` and `match` bodies and a `try` body are not read for
    outcomes, as `callback_outcome` does not read them.
    """
    left = False
    for statement in statements:
        found = _outcome(statement, bindings)
        if found is not None:
            sites.append((*found, conds))
            return _ENDS, left
        if isinstance(statement, ast.If):
            truth = _fold(statement.test)
            if truth is not None:
                state, leaves = _guarded(statement.body if truth else statement.orelse,
                                         bindings, conds, sites, condition)
                left |= leaves
                if state != _FALLS or leaves:
                    return state if state != _FALLS else _STOPS, left
                continue
            test = condition(statement.test)
            body, body_left = _guarded(statement.body, bindings, (*conds, test), sites, condition)
            orelse, orelse_left = _guarded(statement.orelse, bindings, (*conds, f'not ({test})'), sites, condition)
            left |= body_left or orelse_left
            if _STOPS in (body, orelse):
                return _STOPS, left
            if body == orelse == _ENDS:
                return _ENDS, left
            if body == _ENDS and not orelse_left:
                conds = (*conds, f'not ({test})')
            elif orelse == _ENDS and not body_left:
                conds = (*conds, test)
            elif body_left or orelse_left:
                return _STOPS, left
            continue
        if isinstance(statement, ast.Try) and not statement.handlers and not _may_leave(statement.finalbody):
            state, leaves = _guarded(statement.body + statement.finalbody, bindings, conds, sites, condition)
            left |= leaves
            if state != _FALLS or leaves:
                return state if state != _FALLS else _STOPS, left
            continue
        if isinstance(statement, ast.Try):
            if _may_leave([*statement.body, *statement.orelse, *statement.finalbody]):
                return _STOPS, left
            for handler in statement.handlers:
                state, leaves = _guarded(handler.body, bindings, (*conds, _handler_condition(statement, handler)),
                                         sites, condition)
                if state == _STOPS or leaves:
                    return _STOPS, left or leaves
            continue
        if isinstance(statement, (ast.Return, ast.Raise)) or (
                isinstance(statement, ast.Expr) and isinstance(statement.value, (ast.Yield, ast.YieldFrom))):
            return _ENDS, True
        if _may_leave([statement]):
            return _STOPS, left
    return _FALLS, left


def _expression(text):
    try:
        return ast.parse(text, mode='eval').body
    except SyntaxError:
        return None


def _conjunction(conds):
    """`conds` joined with `and`, or None for none.

    A test written across lines inside parentheses keeps them, and a conjunct
    that would bind more loosely than `and` is wrapped. An `except` block's
    condition that is not an expression stays as written: the guard then
    earns nothing that needs it parsed, and still counts as a condition.
    """
    parts = []
    for cond in conds:
        node = _expression(cond)
        if node is None and _expression(f'({cond})') is not None:
            cond, node = f'({cond})', _expression(f'({cond})')
        loose = isinstance(node, (ast.BoolOp, ast.IfExp, ast.Lambda, ast.NamedExpr))
        parts.append(f'({cond})' if len(conds) > 1 and loose else cond)
    return ' and '.join(parts) or None


def setup_outcome(function, bindings, *, receiver=False, condition=ast.unparse):
    """(effect, evidence, guard) for the outcome a unit's setup callback ends in, or None.

    guard None: every call reaches it, read exactly as `callback_outcome`
    reads it. Otherwise each outcome a call reaches whenever its path
    condition holds counts (`_guarded`), and the guard is the disjunction of
    those conditions (#196 183.2), so two branches that between them cover
    every run read as the unconditional skip they are wherever the guard can
    be evaluated. The first such outcome names the effect and is the evidence.
    `condition` gives an expression's source text.
    """
    local = _local(function, bindings, receiver)
    body = _body(function.body)
    found = _reached(body, local)[0]
    if found is not None:
        return (*found, None)
    sites = []
    _guarded(body, local, (), sites, condition)
    if not sites:
        return None
    effect, evidence, _conds = sites[0]
    clauses = [_conjunction(conds) for _effect, _evidence, conds in sites]
    if None in clauses:
        return effect, evidence, None
    return effect, evidence, clauses[0] if len(clauses) == 1 else ' or '.join(f'({c})' for c in clauses)


def module_bindings(tree):
    """Each module name's final top-level binding: a native dotted target, or None.

    Setup callbacks run after the module has executed, so the last binding is
    the one they see. A name any other statement binds, or whose attributes
    it assigns, resolves to nothing.
    """
    bindings = {}
    for statement in tree.body:
        if isinstance(statement, ast.Import):
            for alias in statement.names:
                local = alias.asname or alias.name.split('.')[0]
                target = alias.name if alias.asname else local
                bindings[local] = target if target in _NATIVE_MODULES else None
        elif isinstance(statement, ast.ImportFrom) and statement.module and not statement.level:
            native = statement.module in _NATIVE_MODULES
            for alias in statement.names:
                if alias.name != '*':
                    bindings[alias.asname or alias.name] = f'{statement.module}.{alias.name}' if native else None
        else:
            bindings.update(dict.fromkeys(sorted(_names([statement], mutated=True))))
    return bindings


def setup_skip_controls(tree):
    from .callable_fixture_expectations import _parameters

    bindings, functions = {}, []
    for node in _body(tree.body):
        if isinstance(node, ast.Import) and len(node.names) == 1 and node.names[0].name == 'pytest':
            pairs = [(node.names[0].asname or 'pytest', 'pytest')]
        elif (isinstance(node, ast.ImportFrom) and node.module == 'pytest' and not node.level
              and node.names and all(alias.name in {'skip', 'xfail', 'fixture', 'hookimpl'} for alias in node.names)):
            pairs = [(alias.asname or alias.name, 'pytest.' + alias.name) for alias in node.names]
        elif isinstance(node, ast.FunctionDef) and _parameters(node) is not None:
            if node.name in bindings or node.name.startswith('__'):
                return
            bindings[node.name] = None
            functions.append((node, dict(bindings)))
            continue
        else:
            return
        for name, target in pairs:
            if name.startswith('__') or name in bindings and bindings[name] != target:
                return
            bindings[name] = target
    result = None
    for function, declared in functions:
        # Later rebinding of the provider would change a global lookup.
        if any(bindings.get(name) != target for name, target in declared.items() if target):
            return
        body = _body(function.body)
        if function.name != 'pytest_runtest_setup':
            if (function.name.startswith('pytest_') or _parameters(function) != []
                    or len(function.decorator_list) != 1
                    or not _decorator(function.decorator_list[0], declared, 'pytest.fixture', {'autouse'})
                    or len(body) != 1 or not isinstance(body[0], ast.Expr)
                    or not isinstance(body[0].value, ast.Yield) or body[0].value.value is not None):
                return
            continue
        if (_parameters(function) not in ([], ['item']) or len(function.decorator_list) > 1
                or any(not _decorator(dec, declared, 'pytest.hookimpl', {'tryfirst', 'trylast'})
                       for dec in function.decorator_list)
                or _generator(function)):
            return
        # The one shared reading of "this callback always ends in an outcome".
        outcome = callback_outcome(function, declared)
        if outcome is None:
            return
        result = ('conftest.runtime.pytest_runtest_setup.' + outcome[0], outcome[1])
    if result is not None:
        yield result


# xunit setup that pytest calls itself, and the units each one runs for.
_MODULE_SETUP = {'setup_module': 'all', 'setUpModule': 'all', 'setup_function': 'functions'}
_CLASS_SETUP = {'setup_class': 'methods', 'setUpClass': 'methods', 'setup_method': 'methods', 'setUp': 'methods'}
# unittest's own callbacks: only a unittest.TestCase runs them. On a plain
# class pytest calls setup_class and setup_method alone.
_UNITTEST_SETUP = frozenset({'setUpClass', 'setUp'})


def _fixture(function, bindings):
    """(registered name, autouse) for a plain native fixture definition, else None."""
    if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)) or len(function.decorator_list) != 1:
        return None
    decorator = function.decorator_list[0]
    call = decorator if isinstance(decorator, ast.Call) else None
    target = _resolve(call.func if call is not None else decorator, bindings)
    if target != 'pytest.fixture' or call is not None and call.args:
        return None
    name, autouse = function.name, False
    for keyword in call.keywords if call is not None else ():
        value = keyword.value.value if isinstance(keyword.value, ast.Constant) else None
        if (keyword.arg is None or keyword.arg == 'autouse' and type(value) is not bool
                or keyword.arg == 'name' and type(value) is not str):
            return None
        if keyword.arg == 'autouse':
            autouse = value
        elif keyword.arg == 'name':
            name = value
    return name, autouse


def _requests(function, *, receiver):
    """Fixture names a callback or a test asks pytest for: arguments without defaults."""
    args = function.args
    positional = [*args.posonlyargs, *args.args]
    names = [arg.arg for arg in positional[:len(positional) - len(args.defaults)]]
    if receiver:
        names = names[1:]
    names += [arg.arg for arg, default in zip(args.kwonlyargs, args.kw_defaults) if default is None]
    return frozenset(names) - {'request'}


def _usefixtures(marks, bindings):
    """Names that literal `pytest.mark.usefixtures(...)` marks among these request."""
    return {argument.value for mark in marks
            if isinstance(mark, ast.Call) and _resolve(mark.func, bindings) == 'pytest.mark.usefixtures'
            for argument in mark.args
            if isinstance(argument, ast.Constant) and type(argument.value) is str}


def _pytestmark(body):
    marks = []
    for statement in body:
        if isinstance(statement, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == 'pytestmark' for target in statement.targets):
            value = statement.value
            marks.extend(value.elts if isinstance(value, (ast.List, ast.Tuple)) else [value])
    return marks


def _strings(node):
    if isinstance(node, ast.Constant) and type(node.value) is str:
        return [item.strip() for item in node.value.split(',') if item.strip()]
    if isinstance(node, (ast.List, ast.Tuple)) and all(
            isinstance(item, ast.Constant) and type(item.value) is str for item in node.elts):
        return [item.value for item in node.elts]
    return None


def _direct_arguments(marks, bindings):
    """Argnames these `parametrize` marks supply directly: no fixture runs for them."""
    names = set()
    for mark in marks:
        if not (isinstance(mark, ast.Call) and mark.args
                and _resolve(mark.func, bindings) == 'pytest.mark.parametrize'):
            continue
        argnames = _strings(mark.args[0]) or []
        indirect = next((keyword.value for keyword in mark.keywords if keyword.arg == 'indirect'), None)
        if indirect is None or isinstance(indirect, ast.Constant) and indirect.value is False:
            names.update(argnames)
        elif isinstance(indirect, (ast.List, ast.Tuple)) and _strings(indirect) is not None:
            names.update(set(argnames) - set(_strings(indirect)))
    return names


class SetupScope:
    """The setup providers one module or class body defines (issue #172).

    `fixtures`: registered name -> (requested names, autouse, outcome or None).
    `implicit`: xunit callback name -> (units it runs for, outcome or None).
    An outcome is `setup_outcome`'s (effect, evidence, guard).
    `usefixtures`: names marks request for every unit in scope. `direct`:
    argnames a class or module `parametrize` supplies to every unit in scope.
    Only a name's final binding provides anything: pytest reads the finished
    namespace. `bases` is the class's base list, None when unknown.
    `condition` gives a guard's source text.
    """

    def __init__(self, body, bindings, *, in_class=False, marks=(), bases=None, condition=ast.unparse):
        self.bindings = bindings
        self.fixtures = {}
        self.implicit = {}
        scope_marks = [*marks, *_pytestmark(body)]
        self.usefixtures = frozenset(_usefixtures(scope_marks, bindings))
        self.direct = frozenset(_direct_arguments(scope_marks, bindings))
        last = {}
        for statement in body:
            for name in _names([statement]):
                last[name] = statement
        callbacks = _CLASS_SETUP if in_class else _MODULE_SETUP
        if (in_class and bases is not None and 'object' not in bindings
                and all(isinstance(base, ast.Name) and base.id == 'object' for base in bases)):
            # Only unittest runs setUp/setUpClass, and a class with no base but
            # `object` is no TestCase. The classes scoped here are the
            # collecting class, the classes enclosing it and a wholly same-file
            # hierarchy (`inherited_tests`): none makes a TestCase inherit this body.
            callbacks = {name: applies for name, applies in callbacks.items() if name not in _UNITTEST_SETUP}
        for statement in body:
            if (not isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
                    or last.get(statement.name) is not statement):
                continue
            fixture = _fixture(statement, bindings)
            if fixture is not None:
                name, autouse = fixture
                self.fixtures[name] = (_requests(statement, receiver=in_class), autouse,
                                       setup_outcome(statement, bindings, receiver=in_class, condition=condition))
            elif statement.name in callbacks:
                decorators = statement.decorator_list
                plain = (isinstance(statement, ast.FunctionDef) and not _generator(statement)
                         and (not decorators or len(decorators) == 1 and isinstance(decorators[0], ast.Name)
                              and decorators[0].id in {'classmethod', 'staticmethod'}
                              and decorators[0].id not in bindings))
                outcome = (setup_outcome(statement, bindings, receiver=in_class and not decorators,
                                         condition=condition)
                           if plain else None)
                self.implicit[statement.name] = (callbacks[statement.name], outcome)
        module_setup = last.get('setUpModule')
        if (not in_class and isinstance(module_setup, (ast.FunctionDef, ast.AsyncFunctionDef))
                and not module_setup.decorator_list):
            # pytest calls only the first of setUpModule and setup_module it
            # finds, so a plain setUpModule leaves setup_module unused.
            self.implicit.pop('setup_module', None)


def setup_outcomes(scopes, function, *, method):
    """(provider, effect, evidence, guard) for every outcome this unit's setup reaches.

    `scopes` runs from the module to the innermost enclosing class. The unit
    reaches what its arguments name, what `usefixtures` names, the autouse
    fixtures in scope, what those request in turn, and the xunit setup pytest
    runs for it; a name that `parametrize` on the unit, its class or its
    module supplies directly runs no fixture anywhere in that closure.
    Conftest fixtures are not resolved here: they are judged once,
    suite-wide, as runtime controls (`fixture_setup_controls`).
    """
    bindings = scopes[0].bindings
    static = any(isinstance(mark, ast.Name) and mark.id == 'staticmethod' for mark in function.decorator_list)
    wanted = set(_requests(function, receiver=method and not static))
    wanted |= _usefixtures(function.decorator_list, bindings)
    direct = _direct_arguments(function.decorator_list, bindings)
    fixtures, implicit = {}, {}
    for scope in scopes:
        fixtures.update(scope.fixtures)
        implicit.update(scope.implicit)
        wanted |= scope.usefixtures
        wanted |= {name for name, fixture in scope.fixtures.items() if fixture[1]}
        direct |= scope.direct
    wanted -= direct
    found = {}
    for name in sorted(implicit):
        applies, outcome = implicit[name]
        if outcome is not None and (applies == 'all' or (applies == 'methods') == method):
            found[name] = outcome
    queue = sorted(wanted)
    # A directly parametrized name replaces its fixture for every request in
    # the closure, not only the unit's own.
    seen = set(queue) | direct
    while queue:
        name = queue.pop(0)
        if name not in fixtures:
            continue
        requested, _autouse, outcome = fixtures[name]
        if outcome is not None:
            found.setdefault(name, outcome)
        for request in sorted(requested - seen):
            seen.add(request)
            queue.append(request)
    return [(name, *found[name]) for name in sorted(found)]


def fixture_setup_controls(tree):
    """Conftest fixtures whose setup always ends in a skip or xfail outcome.

    Any test under the conftest's directory can request them, so each one is
    a suite-level runtime control, named per fixture: another such fixture in
    a conftest that already had one is still an event (THREATMODEL 81's
    lesson). Which tests request it is not resolved: they may live anywhere
    under the directory, outside the diff. A guarded one is not read until
    they are (196.followup.conftest-request-side).
    """
    fixtures = SetupScope(tree.body, module_bindings(tree)).fixtures
    for name in sorted(fixtures):
        outcome = fixtures[name][2]
        if outcome is not None and outcome[2] is None:
            yield f'conftest.runtime.fixture.{name}.{outcome[0]}', outcome[1]

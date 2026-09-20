"""Prove direct asserted production-call replacements without broad call scans.

Only the root subject call in an existing paired literal equality is eligible.
The arguments and expectation must stay identical, the old callable must have
a repository import, and the new callable must be a builtin, bounded pure
same-file stand-in, or literal-return unittest.mock object. Ordinary helper
extraction forwarding production, import renames and expected-side edits do
not satisfy this predicate.
"""
from __future__ import annotations

import ast

from checkwash.change import EngineError
from checkwash.conftest_context import ConftestContext
from checkwash.frontends.python.literal_string_standins import literal_string_standin
from checkwash.frontends.python.literal_stdlib_standins import literal_math_gcd_standin, math_is_unshadowed
from checkwash.frontends.python.parameterized_subject_replacements import parameterized_abs_event
from checkwash.ir.astutil import stable_dump
from checkwash.ir.markers import parse_expr
from checkwash.pyenv import known_baseline

_BUILTINS = frozenset({"abs", "all", "any", "bool", "dict", "enumerate", "float", "int",
                      "len", "list", "max", "min", "range", "reversed", "round", "set",
                      "sorted", "str", "sum", "tuple", "zip"})
_MOCKS = {"unittest.mock.Mock", "unittest.mock.MagicMock", "mock.Mock", "mock.MagicMock"}


def _parse(data):
    if not isinstance(data, bytes):
        return None
    if len(data) > 1_000_000:
        raise EngineError("subject replacement source exceeds the byte limit")
    try:
        tree = ast.parse(data.decode("utf-8-sig"))
    except (SyntaxError, UnicodeError, ValueError, RecursionError):
        return None
    if sum(1 for _ in ast.walk(tree)) > 30_000:
        raise EngineError("subject replacement source exceeds the syntax node limit")
    return tree


def _bindings(statements):
    values = {}
    for stmt in statements:
        if isinstance(stmt, ast.Import):
            for alias in stmt.names:
                values[alias.asname or alias.name.split(".")[0]] = alias.name if alias.asname else alias.name.split(".")[0]
        elif isinstance(stmt, ast.ImportFrom) and not stmt.level:
            for alias in stmt.names:
                values[alias.asname or alias.name] = f"{stmt.module}.{alias.name}"
        elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            values[stmt.name] = stmt
        elif isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            for target in stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]:
                if isinstance(target, ast.Name):
                    values[target.id] = stmt.value
        elif isinstance(stmt, (ast.If, ast.For, ast.While, ast.Try, ast.With)):
            # Unknown control flow cannot prove that a name still has its
            # unconditional import, builtin, or local helper binding.
            for node in ast.walk(stmt):
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                    values[node.id] = None
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    values[node.name] = None
                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    for alias in node.names:
                        values[alias.asname or alias.name.split(".")[0]] = None
    return values


def _resolve(expr, bindings, pending=frozenset()):
    if isinstance(expr, ast.Name):
        if expr.id in pending:
            return None
        if expr.id not in bindings:
            return "builtins." + expr.id if expr.id in _BUILTINS else None
        value = bindings[expr.id]
        return _resolve(value, bindings, pending | {expr.id}) if isinstance(value, (ast.Name, ast.Attribute)) else value
    if isinstance(expr, ast.Attribute):
        parent = _resolve(expr.value, bindings, pending)
        return parent + "." + expr.attr if isinstance(parent, str) else None
    return expr


def _pure(node, parameters, bindings, pending=frozenset()):
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.Name):
        if node.id in parameters:
            return True
        if node.id in pending:
            return False
        value = bindings.get(node.id)
        return isinstance(value, ast.AST) and _pure(value, parameters, bindings, pending | {node.id})
    if isinstance(node, ast.Call):
        fn = _resolve(node.func, bindings)
        return (isinstance(fn, str) and fn in {"builtins." + name for name in _BUILTINS}
                and all(_pure(arg, parameters, bindings, pending) for arg in node.args)
                and all(kw.arg is not None and _pure(kw.value, parameters, bindings, pending) for kw in node.keywords))
    if isinstance(node, (ast.List, ast.Tuple, ast.Set, ast.Dict, ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.IfExp, ast.Subscript, ast.Slice)):
        return all(_pure(child, parameters, bindings, pending) for child in ast.iter_child_nodes(node)
                   if isinstance(child, ast.expr))
    return False


def _standin(value, bindings):
    if isinstance(value, str):
        return value in {"builtins." + name for name in _BUILTINS}
    if isinstance(value, ast.Call):
        fn = _resolve(value.func, bindings)
        return (isinstance(fn, str) and fn in _MOCKS and not value.args
                and len(value.keywords) == 1 and value.keywords[0].arg == "return_value"
                and _pure(value.keywords[0].value, set(), bindings))
    if isinstance(value, (ast.FunctionDef, ast.AsyncFunctionDef)):
        body = value.body
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
            body = body[1:]
        if value.decorator_list or len(body) != 1 or not isinstance(body[0], ast.Return):
            return False
        expression = body[0].value
    elif isinstance(value, ast.Lambda):
        expression = value.body
    else:
        return False
    parameters = {a.arg for a in value.args.posonlyargs + value.args.args + value.args.kwonlyargs}
    if value.args.vararg:
        parameters.add(value.args.vararg.arg)
    if value.args.kwarg:
        parameters.add(value.args.kwarg.arg)
    # A parameter named like a builtin may itself be a production callable;
    # its invocation cannot prove that this helper is a production-free stub.
    scoped = {**bindings, **{name: None for name in parameters}}
    return expression is not None and _pure(expression, parameters, scoped)


def _scope(tree, qualname):
    scope = tree
    for part in qualname.split("."):
        scope = next((node for node in scope.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == part), None)
        if scope is None:
            return None
    return scope if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)) else None


def _binding_sites(statements):
    """Inventory writes in one namespace, without entering nested scopes."""
    sites = {}

    class Writes(ast.NodeVisitor):
        def add(self, name, node):
            sites.setdefault(name, []).append(node)

        def visit_Name(self, node):
            if isinstance(node.ctx, (ast.Store, ast.Del)):
                self.add(node.id, node)

        def visit_Import(self, node):
            for alias in node.names:
                self.add(alias.asname or alias.name.split(".")[0], node)

        def visit_ImportFrom(self, node):
            for alias in node.names:
                self.add(alias.asname or alias.name, node)

        def visit_FunctionDef(self, node):
            self.add(node.name, node)

        visit_AsyncFunctionDef = visit_FunctionDef
        visit_ClassDef = visit_FunctionDef

    visitor = Writes()
    for statement in statements:
        visitor.visit(statement)
    return sites


def _subject_call(assertion, tree, qualname):
    """Project only stable, straight-line captures of the asserted value.

    Assertion.reaching describes bindings at the assertion, not at an earlier
    assignment. Require a concrete assignment chain and stable dependencies
    before using that environment to resolve the captured call.
    """
    node = parse_expr(assertion.left or "")
    if isinstance(node, ast.Call):
        return node
    if not isinstance(node, ast.Name):
        return None
    scope = _scope(tree, qualname)
    if scope is None:
        return None
    if any(isinstance(statement, ast.ImportFrom) and any(alias.name == "*" for alias in statement.names)
           for statement in tree.body):
        return None
    try:
        statements = ast.parse(assertion.text).body
    except (SyntaxError, ValueError):
        return None
    if len(statements) != 1 or not isinstance(statements[0], ast.Assert):
        return None
    matches = [i for i, statement in enumerate(scope.body)
               if isinstance(statement, ast.Assert) and stable_dump(statement) == stable_dump(statements[0])]
    if len(matches) != 1:
        return None
    prefix = scope.body[:matches[0]]
    assignments = {}
    for statement in prefix:
        if any(isinstance(part, (ast.NamedExpr, ast.Delete, ast.Global, ast.Nonlocal)) for part in ast.walk(statement)):
            return None
        if isinstance(statement, (ast.Assign, ast.AnnAssign)):
            targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
            if len(targets) != 1 or not isinstance(targets[0], ast.Name) or statement.value is None:
                return None
            assignments[targets[0].id] = (statement, statement.value)
        elif isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if statement.decorator_list or statement.args.defaults or any(statement.args.kw_defaults):
                return None
        elif not (isinstance(statement, (ast.Import, ast.ImportFrom, ast.Pass))
                  or isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant)):
            return None
    local_sites = _binding_sites(scope.body)
    module_sites = _binding_sites(tree.body)
    local_values = _bindings(prefix)
    module_values = _bindings(tree.body)
    boundary = (scope.body[matches[0]].lineno, scope.body[matches[0]].col_offset)
    seen = set()
    for _ in range(8):
        if isinstance(node, ast.Call):
            break
        if not isinstance(node, ast.Name) or node.id in seen:
            return None
        seen.add(node.id)
        if len(local_sites.get(node.id, [])) != 1 or node.id not in assignments:
            return None
        capture, node = assignments[node.id]
        position = (capture.lineno, capture.col_offset)
        if position >= boundary:
            return None
        boundary = position
    else:
        return None
    # Other calls can change the names or objects whose earlier values were
    # captured. This bounded proof accepts only the one subject invocation.
    for statement in prefix:
        if isinstance(statement, (ast.Assign, ast.AnnAssign)) and any(
                isinstance(part, ast.Call) and part is not node for part in ast.walk(statement)):
            return None
    pending = [part.id for part in ast.walk(node) if isinstance(part, ast.Name) and isinstance(part.ctx, ast.Load)]
    checked = set()
    while pending:
        name = pending.pop()
        if name in checked:
            continue
        checked.add(name)
        if name in local_sites:
            sites = local_sites[name]
            if len(sites) != 1 or (sites[0].lineno, sites[0].col_offset) >= boundary:
                return None
            # The assertion environment does not carry local import bindings.
            # Never fall back to a same-named module import for this capture.
            if isinstance(sites[0], (ast.Import, ast.ImportFrom)):
                return None
            value = local_values.get(name)
        else:
            if len(module_sites.get(name, [])) > 1:
                return None
            value = module_values.get(name)
            if name in module_sites and value is None:
                return None
            if isinstance(value, (ast.Name, ast.Attribute, ast.Call)):
                # A module alias or constructed object captured its inputs at
                # its assignment, before any subsequent module rebinding.
                for dependency in ast.walk(value):
                    if isinstance(dependency, ast.Name) and isinstance(dependency.ctx, ast.Load):
                        if any((site.lineno, site.col_offset) > (value.lineno, value.col_offset)
                               for site in module_sites.get(dependency.id, [])):
                            return None
        if isinstance(value, ast.AST):
            pending.extend(part.id for part in ast.walk(value) if isinstance(part, ast.Name) and isinstance(part.ctx, ast.Load))
    return node


def _scoped_bindings(tree, qualname, assertion):
    bindings = _bindings(tree.body)
    scope = _scope(tree, qualname)
    if scope is None:
        return None
    for arg in scope.args.posonlyargs + scope.args.args + scope.args.kwonlyargs:
        bindings[arg.arg] = None
    # Reaching definitions belong to this assertion, avoiding a later local
    # assignment being attributed to an earlier invocation.
    for name, expression in (assertion.reaching or {}).items():
        if expression:
            parsed = parse_expr(expression)
            bindings[name] = parsed
    bindings.update({name: value for name, value in _bindings(scope.body).items()
                     if isinstance(value, (ast.FunctionDef, ast.AsyncFunctionDef))})
    return bindings


def _helper_module_inert(tree):
    """Bound module execution before lending its namespace to a helper."""
    bindings, definitions_started = {}, False

    def literal(value):
        if value is None or any(isinstance(node, (ast.Call, ast.Name)) for node in ast.walk(value)):
            return False
        try:
            ast.literal_eval(value)
            return True
        except (ValueError, TypeError, RecursionError, MemoryError):
            return False

    for statement in tree.body:
        if isinstance(statement, ast.Pass) or (isinstance(statement, ast.Expr)
                and isinstance(statement.value, ast.Constant) and type(statement.value.value) is str):
            continue
        if isinstance(statement, (ast.Import, ast.ImportFrom)):
            if definitions_started or (isinstance(statement, ast.ImportFrom)
                                       and (statement.level or any(alias.name == "*" for alias in statement.names))):
                return False
        elif isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            definitions_started = True
            args = statement.args
            if (statement.decorator_list or statement.returns or getattr(statement, "type_params", ())
                    or any(arg.annotation for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs,
                                                       *([args.vararg] if args.vararg else []), *([args.kwarg] if args.kwarg else [])])
                    or any(not literal(value) for value in args.defaults)
                    or any(value is not None and not literal(value) for value in args.kw_defaults)
                    or statement.name.startswith(("pytest_", "__"))
                    or statement.name in {"setup_module", "teardown_module", "setup_function", "teardown_function",
                                          "setup", "teardown", "setUpModule", "tearDownModule"}):
                return False
        elif isinstance(statement, ast.Assign) and len(statement.targets) == 1 and isinstance(statement.targets[0], ast.Name):
            value = statement.value
            mock = (isinstance(value, ast.Call) and _resolve(value.func, bindings) in _MOCKS
                    and not value.args and len(value.keywords) == 1
                    and value.keywords[0].arg == "return_value" and literal(value.keywords[0].value))
            if not (literal(value) or isinstance(value, ast.Name) and value.id in bindings or mock):
                return False
        else:
            return False
        local = _bindings([statement])
        if any(name in bindings or name.startswith(("pytest_", "__")) for name in local):
            return False
        bindings.update(local)
    return True


def _assertion_scope(tree, qualname, assertion):
    """Locate one directly called, zero-argument assertion helper.

    Inherited assertions normally carry the caller's environment. That is
    insufficient to resolve helper parameters or nested closures, so admit
    only an unshadowed module helper with one literal assertion and a caller
    that begins with that call. Later assertions cannot change that dispatch,
    but every lexical local binding and reflective mutation remains unknown.
    """
    if not assertion.inherited:
        return qualname
    if not _helper_module_inert(tree):
        return None
    caller = _scope(tree, qualname)
    if (caller is None or caller.decorator_list or caller.returns or caller.args.args or caller.args.posonlyargs
            or caller.args.kwonlyargs or caller.args.vararg or caller.args.kwarg
            or not caller.body or not isinstance(caller.body[0], ast.Expr)
            or any(not isinstance(statement, ast.Assert) for statement in caller.body[1:])
            or _binding_sites(caller.body)
            or any(isinstance(node, (ast.NamedExpr, ast.Global, ast.Nonlocal)) for node in ast.walk(caller))):
        return None
    call = caller.body[0].value
    if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name) or call.args or call.keywords:
        return None
    if any(isinstance(node, ast.ImportFrom) and any(alias.name == '*' for alias in node.names)
           for node in tree.body):
        return None
    if any((isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id in {"globals", "locals", "vars", "exec", "eval", "setattr", "delattr"})
           or (isinstance(node, (ast.Attribute, ast.Subscript)) and isinstance(node.ctx, (ast.Store, ast.Del)))
           for node in ast.walk(tree)):
        return None
    sites = _binding_sites(tree.body).get(call.func.id, [])
    if len(sites) != 1 or not isinstance(sites[0], ast.FunctionDef):
        return None
    helper = sites[0]
    if (helper.decorator_list or helper.returns or helper.args.args or helper.args.posonlyargs or helper.args.kwonlyargs
            or helper.args.vararg or helper.args.kwarg or len(helper.body) != 1
            or not isinstance(helper.body[0], ast.Assert)):
        return None
    try:
        expected = ast.parse(assertion.text).body
    except (SyntaxError, ValueError):
        return None
    if len(expected) != 1 or stable_dump(helper.body[0]) != stable_dump(expected[0]):
        return None
    return helper.name


def _literal_helper_replacement(tree, qualname, call, replacement, prove):
    if (not isinstance(replacement, ast.FunctionDef) or replacement not in tree.body
            or not isinstance(call.func, ast.Name) or call.func.id != replacement.name
            or not _helper_module_inert(tree)):
        return False
    scope = _scope(tree, qualname)
    if (scope is None or scope.decorator_list or scope.args.args or scope.args.posonlyargs
            or scope.args.kwonlyargs or scope.args.vararg or scope.args.kwarg
            or len(scope.body) != 1 or not isinstance(scope.body[0], ast.Assert)):
        return False
    # Another test in this module may run first. Only literal calls through
    # this same closed helper can establish that its binding stays intact.
    for function in tree.body:
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)) or function is replacement:
            continue
        args = function.args
        if (not isinstance(function, ast.FunctionDef) or not function.name.startswith("test")
                or args.posonlyargs or args.args or args.kwonlyargs or args.vararg or args.kwarg
                or len(function.body) != 1 or not isinstance(function.body[0], ast.Assert)):
            return False
        assertion = function.body[0]
        comparison = assertion.test
        if (not isinstance(comparison, ast.Compare) or len(comparison.ops) != 1
                or not isinstance(comparison.ops[0], ast.Eq) or not isinstance(comparison.left, ast.Call)
                or not isinstance(comparison.left.func, ast.Name) or comparison.left.func.id != replacement.name
                or not prove(replacement, comparison.left)):
            return False
        try:
            ast.literal_eval(comparison.comparators[0])
            if assertion.msg is not None:
                ast.literal_eval(assertion.msg)
        except (ValueError, TypeError, RecursionError, MemoryError):
            return False
    # Rebinding or reflective writes cannot establish the invoked function.
    for node in ast.walk(tree):
        if (isinstance(node, (ast.Global, ast.Nonlocal, ast.NamedExpr))
                or isinstance(node, ast.Name) and node.id == replacement.name and isinstance(node.ctx, (ast.Store, ast.Del))
                or isinstance(node, (ast.Attribute, ast.Subscript)) and isinstance(node.ctx, (ast.Store, ast.Del))
                or isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in {"globals", "locals", "vars", "exec", "eval", "setattr", "delattr"}):
            return False
    return prove(replacement, call)


def _literal_string_replacement(tree, qualname, call, replacement):
    return _literal_helper_replacement(tree, qualname, call, replacement, literal_string_standin)


def subject_replacement_events(ir, changes, *, root_reader=None):
    if root_reader is None:
        return []
    context = ConftestContext(changes, root_reader)
    deny = known_baseline() | set(ir.globals.third_party_roots)
    by_path = {c.path: c for c in changes}
    events = []
    for file in ir.files:
        change = by_path.get(file.path)
        if file.role != "test" or change is None or not change.before or not change.after:
            continue
        trees = None
        for unit in file.units:
            if unit.before is None or unit.after is None or unit.delta is None:
                continue
            before = {a.id: a for a in unit.before.assertions}
            after = {a.id: a for a in unit.after.assertions}
            if any(assertion.inherited and assertion.right_literal is None for assertion in after.values()):
                if trees is None:
                    trees = (_parse(change.before), _parse(change.after))
                event = parameterized_abs_event(unit, trees, file.path, change.after, context, deny)
                if event is not None:
                    events.append(event)
            for pair in unit.delta.assertion_pairs:
                b, a = before[pair.before_id], after[pair.after_id]
                if (b.form != "compare_eq" or a.form != b.form
                        or not b.positive or not a.positive or b.right_literal is None
                        or a.right_literal != b.right_literal):
                    continue
                if trees is None:
                    trees = (_parse(change.before), _parse(change.after))
                if any(tree is None for tree in trees):
                    continue
                old_scope = _assertion_scope(trees[0], unit.qualname, b)
                new_scope = _assertion_scope(trees[1], unit.qualname, a)
                if old_scope is None or new_scope is None:
                    continue
                old_call, new_call = _subject_call(b, trees[0], old_scope), _subject_call(a, trees[1], new_scope)
                if not isinstance(old_call, ast.Call) or not isinstance(new_call, ast.Call):
                    continue
                if (stable_dump(old_call.func) == stable_dump(new_call.func)
                        or stable_dump(ast.Tuple(elts=old_call.args, ctx=ast.Load())) != stable_dump(ast.Tuple(elts=new_call.args, ctx=ast.Load()))
                        or [stable_dump(k) for k in old_call.keywords] != [stable_dump(k) for k in new_call.keywords]):
                    continue
                old_bindings = _scoped_bindings(trees[0], old_scope, b)
                new_bindings = _scoped_bindings(trees[1], new_scope, a)
                if old_bindings is None or new_bindings is None:
                    continue
                target = _resolve(old_call.func, old_bindings)
                replacement = _resolve(new_call.func, new_bindings)
                if (not isinstance(target, str) or target.split(".", 1)[0] in deny
                        or not context.contains(target, 0)):
                    continue
                if not (_standin(replacement, new_bindings)
                        or _literal_string_replacement(trees[1], new_scope, new_call, replacement)
                        or literal_math_gcd_standin(replacement, new_call, new_bindings)
                        and math_is_unshadowed(context, file.path)
                        and _literal_helper_replacement(trees[1], new_scope, new_call, replacement,
                            lambda function, call: literal_math_gcd_standin(function, call, new_bindings))):
                    continue
                events.append((file.path, unit.qualname, target, a.text, a.span))
    return sorted(set(events))

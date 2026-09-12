"""Bounded, two-sided projection of an exact concrete test consolidation.

N native tests and one literal table can describe the same ordered N oracles.
Recognize an entire module of imports, inert literal definitions and transparent tests:
one native comparison per case, one imported call with literal arguments, and
a literal expectation. No repository expression is executed. Subject/input
coverage must match before either side is projected. Expected values remain
on both sides for the ordinary detectors to compare; changing one cannot
acquire equivalence credit. Unsupported syntax keeps the ordinary frontend
output and detector findings.

The projected units represent concrete cases, not newly discovered functions.
Their stable identities and semantic assertions come from the concrete AST;
their spans still point into the actual source. This changes no alignment
threshold, assertion strength, detector severity, or exemption policy.
"""

from __future__ import annotations

import ast
import copy
import hashlib
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import PurePosixPath

from checkwash.frontends.python.frontend import ParsedFile, _Offsets, normalize_source, parse_python
from checkwash.frontends.python.oracle_blocks import expand_string_blocks, string_block
from checkwash.frontends.python.oracle_purity import pure_imported_calls
from checkwash.frontends.python.oracle_unittest import expand_unittest_classes
from checkwash.frontends.python.oracle_wrappers import expand_operator_asserts, expand_wrappers, trusted_wrapper_import
from checkwash.frontends.python.snapshot_context import inert_test_execution_context
from checkwash.ir.astutil import dotted_name, stable_dump

MAX_SOURCE_BYTES = 65_536
MAX_AST_NODES = 4_096
MAX_CASES = 64
_CONTROL_NAMES = {"pytest", "pytestmark", "pytest_plugins"}
_IMPLICIT_HOOKS = {"setup_module", "teardown_module", "setup_function", "teardown_function",
                   "setup_class", "teardown_class", "setup_method", "teardown_method", "setup", "teardown"}


@dataclass
class _Case:
    assertion: ast.Assert
    source_assertion: ast.Assert
    source_function: ast.FunctionDef
    body: list[ast.stmt] | None = None


def _literal(node):
    if isinstance(node, ast.Constant):
        return type(node.value) in (type(None), bool, int, float, str, bytes)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        return isinstance(node.operand, ast.Constant) and type(node.operand.value) in (int, float)
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return all(_literal(item) for item in node.elts)
    if isinstance(node, ast.Dict):
        return all(key is not None and _literal(key) and _literal(value)
                   for key, value in zip(node.keys, node.values))
    return False


def _docstring(node):
    return (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str))


def _constant(node, bound=()):
    """One inert, non-control module binding, with no executable annotation."""
    if isinstance(node, ast.Assign) and len(node.targets) == 1:
        target, value = node.targets[0], node.value
    elif isinstance(node, ast.AnnAssign) and node.value is not None:
        annotation = node.annotation
        if not ((isinstance(annotation, ast.Constant) and isinstance(annotation.value, str))
                or (isinstance(annotation, ast.Name) and annotation.id not in bound
                    and annotation.id in {"bool", "int", "float", "str", "bytes", "tuple", "list", "dict", "set"})):
            return None
        target, value = node.target, node.value
    else:
        return None
    if (not isinstance(target, ast.Name) or target.id in bound or target.id in _CONTROL_NAMES
            or target.id.startswith("__") or not _literal(value)):
        return None
    return target.id, value


def _table_source(node, constants, used):
    if isinstance(node, ast.Name) and node.id in constants:
        used[node.id] += 1
        return constants[node.id]
    return node


def _immutable_rows(table):
    return (isinstance(table, (ast.List, ast.Tuple))
            and all(_immutable_param(row) for row in table.elts))


def _args(node):
    args = node.args
    if (not isinstance(node, ast.FunctionDef) or node.returns or getattr(node, "type_params", ())
            or args.posonlyargs or args.kwonlyargs or args.defaults or args.vararg or args.kwarg
            or any(arg.annotation for arg in args.args)):
        return None
    return [arg.arg for arg in args.args]


def _names(node):
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, (ast.Tuple, ast.List)) and all(isinstance(item, ast.Name) for item in node.elts):
        names = [item.id for item in node.elts]
        return names if len(names) == len(set(names)) else None
    return None


def _rows(table, names, *, unpack=True):
    if not isinstance(table, (ast.List, ast.Tuple)) or not 1 <= len(table.elts) <= MAX_CASES:
        return None
    result = []
    for row in table.elts:
        values = row.elts if unpack and isinstance(row, (ast.List, ast.Tuple)) else [row]
        if len(values) != len(names) or not all(_literal(value) for value in values):
            return None
        result.append(dict(zip(names, values)))
    return result


class _Substitute(ast.NodeTransformer):
    def __init__(self, bindings):
        self.bindings = bindings

    def visit_Name(self, node):
        return copy.deepcopy(self.bindings.get(node.id, node))


def _concrete(node, bindings, imports):
    if not isinstance(node, ast.Assert) or node.msg is not None:
        return None
    # A literal one-argument predicate adds no closure or dynamic dispatch.
    # Substitute its sole input once, before substituting helper bindings;
    # otherwise an identically named lambda parameter could be captured.
    if (isinstance(node.test, ast.Call) and isinstance(node.test.func, ast.Name)
            and node.test.func.id in bindings):
        predicate = bindings[node.test.func.id]
        if _literal_predicate(predicate) and len(node.test.args) == 1 and not node.test.keywords:
            node = copy.deepcopy(node)
            compare = copy.deepcopy(predicate.body)
            compare.left = node.test.args[0]
            node.test = compare
    original = node.test
    if isinstance(original, ast.Compare):
        # Substitution copies a row's AST into each use. Reusing the same
        # object in two subject arguments, or as input and expectation, is
        # not equivalent to constructing two independent literal objects.
        # Decline every repeated row binding rather than guess mutability.
        uses = Counter(n.id for n in ast.walk(original) if isinstance(n, ast.Name) and n.id in bindings)
        if any(count > 1 for count in uses.values()):
            return None
    concrete = _Substitute(bindings).visit(copy.deepcopy(node))
    compare = concrete.test
    if not isinstance(compare, ast.Compare) or len(compare.ops) != 1:
        return None
    actual, expected = compare.left, compare.comparators[0]
    if not isinstance(compare.ops[0], (ast.Eq, ast.Is)) or not _literal(expected):
        return None
    if isinstance(compare.ops[0], ast.Is) and not (
        isinstance(expected, ast.Constant) and expected.value in (None, True, False)
        and type(expected.value) in (type(None), bool)
    ):
        return None
    if not isinstance(actual, ast.Call):
        return None
    name = dotted_name(actual.func)
    if (not name or name.split(".")[0] not in imports or name.split(".")[0] == "pytest"
            or not all(_literal(arg) for arg in actual.args)
            or not all(keyword.arg is not None and _literal(keyword.value) for keyword in actual.keywords)):
        return None
    return concrete


def _literal_predicate(node):
    if not isinstance(node, ast.Lambda):
        return False
    args, body = node.args, node.body
    return (not args.posonlyargs and len(args.args) == 1 and not args.kwonlyargs
            and not args.defaults and not args.vararg and not args.kwarg
            and isinstance(body, ast.Compare) and len(body.ops) == 1
            and isinstance(body.ops[0], (ast.Eq, ast.Is))
            and isinstance(body.left, ast.Name) and body.left.id == args.args[0].arg
            and _literal(body.comparators[0]))


def _fixture(node):
    if (_args(node) != ["request"] or len(node.decorator_list) != 1 or len(node.body) != 1
            or not isinstance(node.body[0], ast.Return)
            or dotted_name(node.body[0].value) != "request.param"):
        return None
    decorator = node.decorator_list[0]
    if (not isinstance(decorator, ast.Call) or dotted_name(decorator.func) != "pytest.fixture"
            or decorator.args or len(decorator.keywords) != 1 or decorator.keywords[0].arg != "params"):
        return None
    return decorator.keywords[0].value


def _immutable_param(node):
    """A shared params object must contain no mutable object at any depth.

    Pytest reuses the parameter objects across consumers, even at function
    scope. Copying a list/dict/set into projected calls would lose that alias.
    Tuple rows of literal scalars keep the existing concrete-prefix proof.
    """
    if isinstance(node, ast.Tuple):
        return all(_immutable_param(item) for item in node.elts)
    return isinstance(node, (ast.Constant, ast.UnaryOp)) and _literal(node)


def _helper(node):
    """A same-file `def check(a, b): assert <...>` a table row can call.

    Inlining is the only way to prove the loop body actually checks the row:
    crediting the call itself would credit any call, which is exactly the
    unproved step a reviewer rejected in the first attempt at this
    (E-04, 2026-09-06). Bounded to one statement, one message-free assertion,
    plain named parameters, no decorator, and a name pytest does not collect
    under default `python_functions` (already required by the caller's inert
    startup proof, which rejects any non-default collection option).
    """
    parameters = _args(node)
    if (parameters is None or node.name.startswith(("test", "pytest_")) or node.name in _IMPLICIT_HOOKS
            or node.decorator_list or len(node.body) != 1
            or len(set(parameters)) != len(parameters)):
        return None
    assertion = node.body[0]
    if not isinstance(assertion, ast.Assert) or assertion.msg is not None:
        return None
    return parameters, assertion


def _plain_classes(tree):
    """Flatten stateless default-collected classes and local helper mixins.

    No constructor, descriptor, decorator, class data, external inheritance,
    method override or instance use survives this grammar. Consequently a
    direct method call binds only its explicit literal arguments. Local base
    classes contain helpers only; test method order remains source order.
    """
    classes, methods, flattened, class_tests = {}, {}, [], set()
    occupied = {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        if (node.name in classes or node.decorator_list or node.keywords
                or getattr(node, "type_params", ()) or len(node.bases) > 1):
            return None
        inherited = {}
        if node.bases:
            base = node.bases[0]
            if not isinstance(base, ast.Name) or base.id not in methods:
                return None
            if any(name.startswith("test") for name in methods[base.id]):
                return None
            inherited = dict(methods[base.id])
        own = {}
        for member in node.body:
            if _docstring(member) or isinstance(member, ast.Pass):
                continue
            parameters = _args(member) if isinstance(member, ast.FunctionDef) else None
            if (parameters is None or not parameters or parameters[0] != "self"
                    or len(set(parameters)) != len(parameters) or member.decorator_list
                    or member.name.startswith(("__", "pytest_")) or member.name in _IMPLICIT_HOOKS
                    or member.name in inherited or member.name in own):
                return None
            alias = ("test_" if member.name.startswith("test") else "_case_") + node.name + "__" + member.name
            if alias in occupied:
                return None
            occupied.add(alias)
            own[member.name] = alias
        if not own or (not node.name.startswith("Test") and any(name.startswith("test") for name in own)):
            return None
        classes[node.name] = node
        methods[node.name] = {**inherited, **own}

    for name in classes:
        bindings = sum(isinstance(item, (ast.FunctionDef, ast.ClassDef)) and item.name == name
                       or isinstance(item, ast.Name) and isinstance(item.ctx, ast.Store) and item.id == name
                       or isinstance(item, ast.arg) and item.arg == name
                       or isinstance(item, ast.alias) and (item.asname or item.name.split('.')[0]) == name
                       for item in ast.walk(tree))
        if bindings != 1:
            return None

    class Calls(ast.NodeTransformer):
        def __init__(self, local=None):
            self.local = local

        def visit_Call(self, call):
            call = self.generic_visit(call)
            if not isinstance(call.func, ast.Attribute):
                return call
            receiver, method = call.func.value, call.func.attr
            target = None
            if isinstance(receiver, ast.Name) and receiver.id == "self" and self.local is not None:
                target = self.local.get(method)
            elif (isinstance(receiver, ast.Call) and isinstance(receiver.func, ast.Name)
                  and receiver.func.id in classes and not receiver.args and not receiver.keywords
                  and not receiver.func.id.startswith("Test")):
                target = methods[receiver.func.id].get(method)
            if target is not None and not method.startswith("test"):
                call.func = ast.copy_location(ast.Name(id=target, ctx=ast.Load()), call.func)
            return call

    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            rewritten = Calls().visit(node)
            if any(isinstance(item, ast.Name) and item.id in classes for item in ast.walk(rewritten)):
                return None
            flattened.append(rewritten)
            continue
        for original in node.body:
            if not isinstance(original, ast.FunctionDef):
                continue
            member = copy.deepcopy(original)
            member.name = methods[node.name][original.name]
            member.args.args = member.args.args[1:]
            member = Calls(methods[node.name]).visit(member)
            if any(isinstance(item, ast.Name) and (item.id == "self" or item.id in classes)
                   for item in ast.walk(member)):
                return None
            flattened.append(member)
            if original.name.startswith("test"):
                class_tests.add(member.name)
    tree.body = flattened
    return class_tests


def _table_helper(node):
    """A non-collected, one-parameter helper whose whole body checks a table."""
    parameters = _args(node)
    if (parameters is None or len(parameters) != 1 or node.name.startswith("test")
            or node.decorator_list or len(node.body) != 1 or not isinstance(node.body[0], ast.For)):
        return None
    loop = node.body[0]
    columns = _names(loop.target)
    if (not columns or parameters[0] in columns or loop.orelse or len(loop.body) != 1
            or not isinstance(loop.iter, ast.Name) or loop.iter.id != parameters[0]
            or not isinstance(loop.body[0], ast.Assert) or loop.body[0].msg is not None):
        return None
    assertion = loop.body[0]
    if any(isinstance(item, ast.Name) and item.id == parameters[0] for item in ast.walk(assertion)):
        return None  # the table object itself must not be treated as a row literal
    return parameters[0], columns, assertion, not isinstance(loop.target, ast.Name)


def _inlined(statement, bindings, helpers, scope):
    """`check(row, names)` as a unit's only statement -> the helper's own
    assertion, with the helper's parameters bound to this row's literals.

    The callee has to *be* the module-level helper at run time, so it must
    be a bare name that nothing in the test's own scope rebinds: a test
    parameter, a parametrize argname, a loop target or the local a table is
    assigned to. `for check, n, expected in rows: check(check, n, expected)`
    calls the row's first cell, not the helper; substituting the helper
    there would credit a check that never runs. (Module-level rebinding is
    already impossible: `_module` admits no statement but imports and
    uniquely named defs.)

    Every argument must be a row name or a literal; anything else is an
    unproved value. A row name reaching two parameters is declined for the
    same reason `_concrete` declines a repeated binding: at run time both
    parameters see one object, while substitution would copy two independent
    literals.
    """
    if not (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call)):
        return None
    call = statement.value
    if not isinstance(call.func, ast.Name) or call.func.id in scope:
        return None
    helper = helpers.get(call.func.id)
    if helper is None or call.keywords or len(call.args) != len(helper[0]):
        return None
    parameters, assertion = helper
    inner, consumed = {}, Counter()
    for parameter, argument in zip(parameters, call.args):
        if isinstance(argument, ast.Name) and argument.id in bindings:
            consumed[argument.id] += 1
            inner[parameter] = bindings[argument.id]
        elif _literal(argument):
            inner[parameter] = argument
        elif isinstance(argument, ast.Call) or _literal_predicate(argument):
            # A call is effectful. It must reach the single concrete subject
            # exactly once; unused or duplicated evaluated arguments cannot
            # disappear through helper expansion. _concrete validates the
            # imported callee and all literal call arguments afterwards.
            if sum(isinstance(item, ast.Name) and item.id == parameter for item in ast.walk(assertion)) != 1:
                return None
            inner[parameter] = argument
        else:
            return None
    if any(count > 1 for count in consumed.values()):
        return None
    return assertion, inner


def _checked(statement, bindings, imports, helpers, scope, constants):
    """The row's concrete assertion, whether written inline or via a helper.

    `scope` is every name the test binds itself (parameters, row names, the
    local a table is assigned to); a helper call through one of those names
    is not a call of the helper.
    """
    if isinstance(statement, ast.Assert):
        return _concrete(statement, bindings, imports)
    inlined = _inlined(statement, bindings, helpers, scope | set(bindings))
    if inlined is None:
        return None
    assertion, inner = inlined
    return _concrete(assertion, {**constants, **inner}, imports)


def _table_fixture(node):
    """A zero-argument `@pytest.fixture` whose whole body returns a literal
    table, for a test that walks it with a `for` loop.

    Unlike `params=`, this multiplies no collection: it is a shared literal
    constant, so several tests may read it. Nothing in it is executed here — the rows are substituted
    into each concrete assertion exactly as an inline table's are.
    """
    if _args(node) != [] or len(node.decorator_list) != 1 or len(node.body) != 1:
        return None
    decorator = node.decorator_list[0]
    if isinstance(decorator, ast.Call):
        if decorator.args or decorator.keywords:
            return None
        decorator = decorator.func
    if dotted_name(decorator) != "pytest.fixture":
        return None
    returned = node.body[0]
    if not isinstance(returned, ast.Return) or not isinstance(returned.value, (ast.List, ast.Tuple, ast.Name)):
        return None
    return returned.value


def _test(node, fixtures, tables, imports, helpers, table_helpers, constants, used_constants, *, baseline,
          multiple=False):
    names = _args(node)
    if names is None or not node.name.startswith("test"):
        return None
    if multiple and not names and not node.decorator_list and 1 <= len(node.body) <= MAX_CASES:
        assertions = [_checked(statement, {}, imports, helpers, set(), {}) for statement in node.body]
        if any(assertion is None for assertion in assertions):
            return None
        return [_Case(assertion, statement, node) for assertion, statement in zip(assertions, node.body)], True, "unittest"
    block = string_block(node) if not names and not node.decorator_list else None
    if block is not None:
        assertion, body = block
        concrete = _concrete(assertion, {}, imports)
        if concrete is None:
            return None
        return [_Case(concrete, node.body[-1], node, body)], True, "string-block"
    body, bindings, table, form = node.body, [{}], False, "native"
    # Names the test itself binds, for `_inlined`'s shadowing check: its
    # parameters now, the row names and any table local below.
    scope = set(names)
    if baseline:
        if names or node.decorator_list:
            return None
    elif node.decorator_list:
        if len(node.decorator_list) != 1:
            return None
        decorator = node.decorator_list[0]
        if (not isinstance(decorator, ast.Call) or dotted_name(decorator.func) != "pytest.mark.parametrize"
                or len(decorator.args) != 2 or decorator.keywords):
            return None
        columns = decorator.args[0]
        if isinstance(columns, ast.Constant) and isinstance(columns.value, str):
            columns = [name.strip() for name in columns.value.split(",")]
        elif isinstance(columns, (ast.List, ast.Tuple)) and all(
                isinstance(item, ast.Constant) and isinstance(item.value, str) for item in columns.elts):
            columns = [item.value for item in columns.elts]
        else:
            return None
        if not names or len(columns) != len(set(columns)) or set(columns) != set(names):
            return None
        values = _table_source(decorator.args[1], constants, used_constants)
        bindings = _rows(values, columns, unpack=len(columns) != 1)
        table, form = True, "parametrize"
    elif (len(names) == 1 and names[0] in tables and len(body) == 1 and isinstance(body[0], ast.For)
          and isinstance(body[0].iter, ast.Name) and body[0].iter.id == names[0]):
        loop = body[0]
        columns = _names(loop.target)
        if loop.orelse or not columns or names[0] in columns:
            return None
        bindings = _rows(tables[names[0]], columns, unpack=not isinstance(loop.target, ast.Name))
        scope.update(columns)
        body, table, form = loop.body, True, "table-fixture-loop"
    elif names:
        if (len(names) != 1 or names[0] not in fixtures or len(body) != 2
                or not isinstance(body[0], ast.Assign) or len(body[0].targets) != 1
                or not isinstance(body[0].value, ast.Name) or body[0].value.id != names[0]):
            return None
        columns = _names(body[0].targets[0])
        if not columns or names[0] in columns:
            return None
        bindings = _rows(fixtures[names[0]], columns, unpack=not isinstance(body[0].targets[0], ast.Name))
        scope.update(columns)
        body, table, form = body[1:], True, "params-fixture"
    elif ((len(body) == 1 and isinstance(body[0], ast.For))
          or (len(body) == 2 and isinstance(body[0], ast.Assign) and isinstance(body[1], ast.For))):
        loop = body[-1]
        rows = loop.iter
        if len(body) == 2:
            assignment = body[0]
            if (len(assignment.targets) != 1 or not isinstance(assignment.targets[0], ast.Name)
                    or not isinstance(rows, ast.Name) or rows.id != assignment.targets[0].id
                    or rows.id in imports):
                return None
            rows = assignment.value
            scope.add(assignment.targets[0].id)
        columns = _names(loop.target)
        if loop.orelse or not columns:
            return None
        rows = _table_source(rows, constants, used_constants)
        bindings = _rows(rows, columns, unpack=not isinstance(loop.target, ast.Name))
        scope.update(columns)
        body, table, form = loop.body, True, "literal-loop"
    elif (len(body) == 1 and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Call)
          and isinstance(body[0].value.func, ast.Name) and body[0].value.func.id in table_helpers
          and body[0].value.func.id not in scope):
        call = body[0].value
        if len(call.args) != 1 or call.keywords:
            return None
        parameter, columns, assertion, unpack = table_helpers[call.func.id]
        values = _table_source(call.args[0], constants, used_constants)
        bindings = _rows(values, columns, unpack=unpack)
        scope.update([parameter, *columns])
        body, table, form = [assertion], True, "table-helper-loop"
    if bindings is None or len(body) != 1:
        return None
    if (form == "native" and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Call)
            and isinstance(body[0].value.func, ast.Name) and body[0].value.func.id in helpers):
        table, form = True, "assert-helper"
    # Mutable module objects may be table containers, but must not be copied
    # into subject/expected expressions as though each reference allocated a
    # fresh object. Immutable constants still obey the repeated-binding guard.
    immutable = {name: value for name, value in constants.items() if _immutable_param(value)}
    free = {name: value for name, value in immutable.items() if name not in scope}
    assertions = [_checked(body[0], {**free, **row}, imports, helpers, scope, immutable)
                  for row in bindings]
    if any(assertion is None for assertion in assertions):
        return None
    return [_Case(assertion, body[0], node) for assertion in assertions], table, form


def _module(source, *, baseline):
    if len(source) > MAX_SOURCE_BYTES:
        return None
    text = normalize_source(source)
    tree = ast.parse(text)
    if sum(1 for _ in ast.walk(tree)) > MAX_AST_NODES:
        return None
    wrapper_tests = expand_wrappers(tree)
    if wrapper_tests is None:
        return None
    expand_operator_asserts(tree)
    block_tests = expand_string_blocks(tree)
    if block_tests is None:
        return None
    unittest_tests = expand_unittest_classes(tree)
    if unittest_tests is None:
        return None
    class_tests = _plain_classes(tree)
    if class_tests is None:
        return None
    imports, import_nodes, functions, names = set(), [], [], set()
    constants, used_constants, modules, wrapper_authorities = {}, Counter(), set(), set()
    pytest_imported = False
    for node in tree.body:
        if _docstring(node) or isinstance(node, ast.Pass):
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)) and not functions:
            if isinstance(node, ast.ImportFrom) and (node.level or any(alias.name == "*" for alias in node.names)):
                return None
            bound = [alias.asname or (alias.name.split(".")[0] if isinstance(node, ast.Import) else alias.name)
                     for alias in node.names]
            if names.intersection(bound) or len(set(bound)) != len(bound):
                return None
            names.update(bound)
            imports.update(bound)
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif node.module:
                modules.add(node.module)
                modules.update(node.module + "." + alias.name for alias in node.names)
            if (isinstance(node, ast.Import) and len(node.names) == 1
                    and node.names[0].name == "pytest" and node.names[0].asname is None):
                pytest_imported = True
            else:
                # Aliased pytest could be a shadowing decorator authority.
                if "pytest" in bound:
                    return None
                wrapper_authority = trusted_wrapper_import(node)
                if wrapper_authority:
                    wrapper_authorities.add(wrapper_authority)
                else:
                    import_nodes.append(ast.dump(node, include_attributes=False))
        elif not functions and (constant := _constant(node, names)) is not None:
            name, value = constant
            names.add(name)
            constants[name] = value
        elif isinstance(node, ast.FunctionDef) and node.name not in names:
            names.add(node.name)
            if node.body and _docstring(node.body[0]):
                node.body = node.body[1:]
            functions.append(node)
        else:
            return None
    fixtures, tables, shared_tables = {}, {}, set()
    if not baseline:
        for function in functions:
            fixture = _fixture(function)
            if fixture is not None:
                if not pytest_imported:
                    return None
                fixtures[function.name] = _table_source(fixture, constants, used_constants)
                continue
            table_fixture = _table_fixture(function)
            if table_fixture is not None:
                if not pytest_imported:
                    return None
                if isinstance(table_fixture, ast.Name) and table_fixture.id in constants:
                    shared_tables.add(function.name)
                tables[function.name] = _table_source(table_fixture, constants, used_constants)
    helpers, table_helpers = {}, {}
    for function in functions:
        if function.name in fixtures or function.name in tables:
            continue
        candidate = _helper(function)
        if candidate is not None:
            helpers[function.name] = candidate
            continue
        table_candidate = _table_helper(function)
        if table_candidate is not None:
            table_helpers[function.name] = table_candidate
    result, table, forms = [], False, []
    used_fixtures, used_helpers, used_tables = Counter(), Counter(), Counter()
    for function in functions:
        if function.name in fixtures or function.name in tables or function.name in helpers or function.name in table_helpers:
            continue
        expanded = _test(function, fixtures, tables, imports, helpers, table_helpers, constants, used_constants,
                         baseline=baseline, multiple=function.name in unittest_tests)
        if expanded is None:
            return None
        cases, is_table, form = expanded
        if function.name in class_tests:
            is_table, form = True, "plain-class"
        if function.name in wrapper_tests:
            is_table, form = True, "oracle-wrapper"
        forms.append((function.name, form))
        if function.decorator_list and not pytest_imported:
            return None
        used_fixtures.update(set(_args(function)) & fixtures.keys())
        used_tables.update(set(_args(function)) & tables.keys())
        used_helpers.update(name for name in (dotted_name(call.func) for call in ast.walk(function)
                                              if isinstance(call, ast.Call)) if name in helpers or name in table_helpers)
        result.extend(cases)
        table |= is_table
        if len(result) > MAX_CASES:
            return None
    if fixtures.keys() != used_fixtures.keys():
        return None
    for name, count in used_fixtures.items():
        if count > 1:
            params = fixtures[name]
            if not _immutable_rows(params):
                return None
    if any(count > 1 and not _immutable_rows(constants[name]) for name, count in used_constants.items()):
        return None
    if any(used_tables[name] > 1 and not _immutable_rows(tables[name]) for name in shared_tables):
        return None
    # A helper nobody calls never runs, but leaving one uninspected in an
    # otherwise transparent module weakens the "entire module" claim the
    # projection rests on. Same discipline as the fixtures above.
    if helpers.keys() | table_helpers.keys() != used_helpers.keys() or tables.keys() != used_tables.keys():
        return None
    return (text, import_nodes, result, table, pytest_imported, modules, forms, wrapper_authorities,
            bool(block_tests or unittest_tests), bool(unittest_tests))


def _module_unshadowed(path, read, module):
    """Reject repository-local substitutes for a standard wrapper authority."""
    parts = PurePosixPath(path.replace("\\", "/")).parts
    directories = {"", "src"}
    directories.update("/".join(parts[:depth]) for depth in range(1, len(parts)))
    for directory in sorted(directories):
        prefix = directory + "/" if directory else ""
        if any(read(prefix + candidate) is not None for candidate in (module + ".py", module + "/__init__.py")):
            return False
    return True


def _pytest_unshadowed(path, read):
    return _module_unshadowed(path, read, "pytest")


def _project(parsed, text, cases):
    keys = Counter()
    definitions = []
    for case in cases:
        digest = hashlib.sha256(_subject_key(case).encode()).hexdigest()[:24]
        keys[digest] += 1
        name = f"test_concrete_{digest}_{keys[digest]}"
        body = case.body if case.body is not None else [case.assertion]
        rendered = "\n".join(ast.unparse(statement) for statement in body)
        definitions.append(f"def {name}():\n" + "\n".join("    " + line for line in rendered.splitlines()) + "\n")
    concrete = parse_python("\n".join(definitions).encode(), collect_tests=True)
    offsets = _Offsets(text)
    units = []
    for unit, case in zip(concrete.units, cases):
        span = offsets.span(case.source_function)
        sources = ([item for item in case.body if isinstance(item, ast.Assert)]
                   if case.body is not None else [case.source_assertion])
        assertions = [replace(assertion, span=offsets.span(source))
                      for assertion, source in zip(unit.side.assertions, sources)]
        units.append(replace(unit, span=span, side=replace(unit.side, span=span, assertions=assertions)))
    return replace(parsed, units=units)


def _subject_key(case):
    compare = case.assertion.test
    key = stable_dump(compare.left) + ":" + type(compare.ops[0]).__name__
    if case.body is not None:
        key += ":aux:" + stable_dump(ast.Module(body=case.body[:-1], type_ignores=[]))
    return key


def _bounded_tree(source):
    if source is None:
        return ast.Module(body=[], type_ignores=[])
    if not isinstance(source, bytes) or len(source) > MAX_SOURCE_BYTES:
        return None
    try:
        tree = ast.parse(normalize_source(source))
    except (SyntaxError, ValueError, TypeError, MemoryError, RecursionError):
        return None
    return tree if sum(1 for _ in ast.walk(tree)) <= MAX_AST_NODES else None


def _inert_module(tree):
    names = set()
    for node in tree.body:
        if _docstring(node) or isinstance(node, ast.Pass):
            continue
        constant = _constant(node, names)
        if constant is None:
            return False
        names.add(constant[0])
    return True


def _related_source_paths(path, modules):
    parts = PurePosixPath(path.replace("\\", "/")).parts
    roots = {"", "src", *("/".join(parts[:depth]) for depth in range(1, len(parts)))}
    candidates = set()
    for module in modules:
        pieces = module.split(".")
        for depth in range(1, len(pieces) + 1):
            relative = "/".join(pieces[:depth])
            for root in roots:
                prefix = root + "/" if root else ""
                candidates.add(prefix + relative + ".py")
                candidates.add(prefix + relative + "/__init__.py")
    return candidates


def _compatible_cochanges(path, modules, changes):
    """Permit unrelated inert sidecars, not unproved changes to execution.

    A second file is no longer an automatic veto. Documentation, literal-only
    modules and source edits preserving the complete AST cannot alter the
    table's concrete oracle sequence. Imported modules/package initializers,
    renames, executable source edits and arbitrary config/data changes still
    withhold this proof. Both startup snapshots are checked separately below.
    """
    if len(changes) > MAX_CASES:
        return False
    related = _related_source_paths(path, modules)
    for change in changes:
        candidate = change.path.replace("\\", "/")
        if candidate == path.replace("\\", "/"):
            continue
        if (change.old_path is not None or change.synthetic is not None
                or change.status not in {"added", "modified", "deleted"}):
            return False
        if candidate in related:
            return False
        if candidate.endswith((".md", ".rst")):
            continue
        if not candidate.endswith(".py"):
            return False
        old, new = _bounded_tree(change.before), _bounded_tree(change.after)
        if old is None or new is None:
            return False
        if stable_dump(old) != stable_dump(new) and not (_inert_module(old) and _inert_module(new)):
            return False
    return True


def _context_snapshots(path, before, after, changes, read, search):
    """Overlay both changed sides onto the strict head snapshot and inventory."""
    overlays = [{path: before}, {path: after}]
    for change in changes:
        overlays[0][change.path] = change.before
        overlays[1][change.path] = change.after
    result = []
    for overlay in overlays:
        def side_read(candidate, overlay=overlay):
            return overlay[candidate] if candidate in overlay else read(candidate)

        def side_search(needles, overlay=overlay):
            paths = search(needles)
            if not isinstance(paths, (list, tuple)) or any(not isinstance(item, str) for item in paths):
                return paths
            found = set(paths)
            for candidate, source in overlay.items():
                found.discard(candidate)
                if (candidate.endswith(".py") and source
                        and any(needle.encode() in source for needle in needles)):
                    found.add(candidate)
            return sorted(found)

        result.append((side_read, side_search))
    return result


def _ordinary_rows_cover(module, parsed):
    units = {unit.qualname: unit.side for unit in parsed.units}
    return all(form == "native" or (form == "parametrize" and name in units and units[name].param_rows)
               for name, form in module[6])


def project_table_consolidation(before: bytes, after: bytes, before_parsed: ParsedFile, after_parsed: ParsedFile,
                                *, path: str, root_reader=None, root_searcher=None, changes=()):
    """Project exact ordered subject coverage; leave expected edits detectable.

    The caller selects a modified collected test file. Unrelated inert
    cochanges are allowed only with closed startup context on both sides. Baseline
    tests are plain, zero-argument native single-assert functions; the head
    can consolidate them into literal parametrize, fixture(params=), or loops.
    A row's single check may be written inline or delegated to a same-file
    message-free single-assert helper, which is inlined per row before any
    strictness below applies. Deleting/reordering rows, dynamic tables,
    indirect/marked params, setup/teardown, multiple assertions, and any
    executable module statement remain outside this bounded implementation;
    docstrings and unique literal constants are inert preamble, not execution.
    """
    if (root_reader is None or root_searcher is None or not before_parsed.parse_ok or not after_parsed.parse_ok
            or not before_parsed.units):
        return before_parsed, after_parsed
    try:
        old, new = _module(before, baseline=True), _module(after, baseline=False)
        if old is None:
            old = _module(before, baseline=False)
        if old is None or new is None or old[1] != new[1] or not (old[3] or new[3]):
            return before_parsed, after_parsed
        if (old[3] and new[3] and old[6] == new[6]
                and _ordinary_rows_cover(old, before_parsed) and _ordinary_rows_cover(new, after_parsed)):
            # An edit within the same row carrier/unit retains #135 and the
            # row-identity channel. Projection proves a carrier transition;
            # it must not relabel ordinary parametrize expectation findings.
            return before_parsed, after_parsed
        old_keys = [_subject_key(case) for case in old[2]]
        new_keys = [_subject_key(case) for case in new[2]]
        # Extra literal cases can follow the complete old sequence. They
        # cannot run before an old oracle and change what it subsequently
        # sees; insertion/reordering stays outside the proof.
        if not old_keys:
            return before_parsed, after_parsed
        if old_keys != new_keys[:len(old_keys)]:
            if not (old[9] or new[9]) or Counter(old_keys) - Counter(new_keys):
                return before_parsed, after_parsed
            # Default TestCase sorts test methods and repeats setup per test.
            # Reordering earns credit only after both imported-source purity
            # proofs below; every original concrete oracle remains present.
            old[2].sort(key=_subject_key)
            new[2].sort(key=_subject_key)
    except (SyntaxError, ValueError, TypeError, MemoryError, RecursionError):
        return before_parsed, after_parsed
    # A loop runs function-scope autouse fixtures once, while separate
    # functions run them once per case. An unchanged reset/mutator can
    # therefore invalidate the apparent same-oracle proof. Absence or
    # inertness of every test ancestor needs a strict snapshot reader.
    # Snapshot errors must escape the parser's unsupported-syntax fallback.
    changes = tuple(changes)
    if not _compatible_cochanges(path, old[5] | new[5], changes):
        return before_parsed, after_parsed
    for module, (read, search) in zip((old, new), _context_snapshots(
            path, before, after, changes, root_reader, root_searcher)):
        if not inert_test_execution_context(path, read, search):
            return before_parsed, after_parsed
        if module[4] and not _pytest_unshadowed(path, read):
            return before_parsed, after_parsed
        if any(not _module_unshadowed(path, read, authority) for authority in module[7]):
            return before_parsed, after_parsed
        if (old[8] or new[8]) and not pure_imported_calls(module[0].encode(),
                                                [case.assertion.test.left for case in module[2]], path=path, read=read):
            return before_parsed, after_parsed
    return _project(before_parsed, old[0], old[2]), _project(after_parsed, new[0], new[2])

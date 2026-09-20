"""Bounded, two-sided projection of concrete oracle carriers.

Native tests, literal tables and closed helper/class/wrapper bodies can
describe the same concrete checks. Each primary oracle compares an imported
call with literal arguments against a literal expectation. Ordinary carrier
changes preserve the ordered subject/input prefix. A string block retains
its one assignment and all length, prefix and exact-value assertions; its
auxiliary checks must match. No repository expression is executed.

The TestCase extension models sorted test methods and repeats straight-line
setUp assertions for each method. It requires exactly the original oracle
identities and multiplicities, plus closed pure imported source on both
sides. Default subTest-only after-suites may add rows while retaining every
original identity and count, since a failed row does not stop later checks.
The general exact-multiplicity proof establishes the same pass/fail conditions when expected
values are preserved, not the original call order or execution of assertions
after a failure. Expected values remain on both sides for the ordinary
detectors to compare; changed values do not acquire equivalence credit.
Unsupported syntax keeps the ordinary frontend output and findings.

The projected units represent concrete cases, not newly discovered functions.
Their stable identities and semantic assertions come from the concrete AST;
their spans still point into the actual source. This changes no alignment
threshold, assertion strength, detector severity, or exemption policy.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import math
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import PurePosixPath

from checkwash.frontends.python.frontend import ParsedFile, _Offsets, normalize_source, parse_python
from checkwash.frontends.python.expected_constants import folded_expected
from checkwash.frontends.python.oracle_blocks import IMPLICIT_ENTRY_NAMES, expand_string_blocks, string_block
from checkwash.frontends.python.oracle_purity import primitive_literal_result, pure_imported_calls, shared_literal_collection_inputs
from checkwash.frontends.python.primitive_strings import primitive_string_result
from checkwash.frontends.python.derived_literals import derived_shape, fold_derived, primitive_derived_result
from checkwash.frontends.python.indexed_fixture_tables import expand_indexed_fixture_tables
from checkwash.frontends.python.oracle_unittest import expand_unittest_classes
from checkwash.frontends.python.oracle_wrappers import expand_operator_asserts, expand_wrappers, trusted_wrapper_import
from checkwash.frontends.python.snapshot_context import inert_test_execution_context
from checkwash.frontends.python.table_factories import expand_literal_table_factories
from checkwash.frontends.python.inert_helpers import prune_inert_helpers
from checkwash.frontends.python.literal_fixtures import expand_literal_fixtures
from checkwash.frontends.python.raises_oracles import extract_raises_oracles, retain_raises_units
from checkwash.frontends.python.tuple_oracles import expand_tuple_oracles, primitive_tuple_result
from checkwash.frontends.python.helper_predicates import expand_predicate_helpers
from checkwash.frontends.python.prefix_predicates import expand_prefix_predicates
from checkwash.ir.astutil import dotted_name, stable_dump

MAX_SOURCE_BYTES = 65_536
MAX_AST_NODES = 4_096
MAX_CASES = 64
_CONTROL_NAMES = {"pytest", "pytestmark", "pytest_plugins"}
_IMPLICIT_HOOKS = IMPLICIT_ENTRY_NAMES


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


def _approx_expected(node):
    """A standard approx object over finite numeric literals, never inputs."""
    if (not isinstance(node, ast.Call) or dotted_name(node.func) != "pytest.approx"
            or len(node.args) != 1 or not _literal(node.args[0])):
        return False

    def numeric(value):
        if type(value) in (int, float):
            return type(value) is int or math.isfinite(value)
        if isinstance(value, (list, tuple)):
            return bool(value) and all(type(item) in (int, float) and numeric(item) for item in value)
        return False

    try:
        if not numeric(ast.literal_eval(node.args[0])):
            return False
        keys = set()
        for keyword in node.keywords:
            if keyword.arg in keys or keyword.arg not in {"rel", "abs", "nan_ok"} or not _literal(keyword.value):
                return False
            keys.add(keyword.arg)
            value = ast.literal_eval(keyword.value)
            if keyword.arg == "nan_ok":
                if type(value) is not bool:
                    return False
            elif type(value) not in (int, float) or not numeric(value) or value < 0:
                return False
    except (ValueError, TypeError, OverflowError, RecursionError, MemoryError):
        return False
    return True


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
        if len(values) != len(names) or not all(_literal(value) or _approx_expected(value) for value in values):
            return None
        result.append(dict(zip(names, values)))
    return result


class _Substitute(ast.NodeTransformer):
    def __init__(self, bindings):
        self.bindings = bindings

    def visit_Name(self, node):
        return copy.deepcopy(self.bindings.get(node.id, node))


def _concrete(node, bindings, imports):
    if not isinstance(node, ast.Assert):
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
    else:
        uses = {}
    concrete = _Substitute(bindings).visit(copy.deepcopy(node))
    compare = concrete.test
    if not isinstance(compare, ast.Compare) or len(compare.ops) != 1:
        return None
    actual, expected = compare.left, compare.comparators[0]
    if _literal(actual) and isinstance(expected, ast.Call):
        # Reorientation is a value proof only for primitive results. A custom
        # equality implementation can dispatch differently by operand order;
        # the existing primitive-result/import closure check below owns that
        # obligation on both snapshots before projection is credited.
        actual, expected = expected, actual
        compare.left, compare.comparators[0] = actual, expected
        concrete._requires_primitive_string = True
    derived = fold_derived(expected)
    if derived is not None:
        expected, authority = derived
        compare.comparators[0] = expected
        concrete._requires_derived_authority = authority
    if any(count > 1 for count in uses.values()):
        actual_uses = Counter(n.id for n in ast.walk(original.left) if isinstance(n, ast.Name))
        if not (derived is not None and all(count <= 1 or (
                isinstance(bindings[name], (ast.Constant, ast.UnaryOp)) and _literal(bindings[name])
                and actual_uses[name] <= 1) for name, count in uses.items())):
            return None
    approximate = _approx_expected(expected)
    if not isinstance(compare.ops[0], (ast.Eq, ast.Is)) or not (_literal(expected) or approximate):
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
    if approximate:
        concrete._requires_approx_authority = True
    if concrete.msg is not None:
        concrete._requires_primitive_string = True
        message = concrete.msg
        if isinstance(message, ast.Constant) and type(message.value) is str:
            pass
        elif isinstance(message, ast.JoinedStr):
            for part in message.values:
                if isinstance(part, ast.Constant) and type(part.value) is str:
                    continue
                if not isinstance(part, ast.FormattedValue) or part.format_spec is not None or part.conversion not in (-1, 97, 114, 115):
                    return None
                if _literal(part.value):
                    continue
                if stable_dump(part.value) != stable_dump(actual):
                    return None
                concrete._requires_primitive_string = True
        else:
            return None
        concrete.msg = None
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
    (E-04, 2026-09-06). Bounded to one assertion, plain named parameters,
    no decorator, and a name pytest does not collect
    under default `python_functions` (already required by the caller's inert
    startup proof, which rejects any non-default collection option).
    A single local result or diagnostic message additionally requires a
    closed primitive-string result proof before projection earns credit.
    """
    parameters = _args(node)
    if (parameters is None or node.name.startswith(("test", "pytest_")) or node.name in _IMPLICIT_HOOKS
            or node.decorator_list or len(node.body) not in (1, 2)
            or len(set(parameters)) != len(parameters)):
        return None
    assertion = node.body[-1]
    if not isinstance(assertion, ast.Assert):
        return None
    if len(node.body) == 2:
        assignment = node.body[0]
        if (not isinstance(assignment, ast.Assign) or len(assignment.targets) != 1
                or not isinstance(assignment.targets[0], ast.Name) or not isinstance(assignment.value, ast.Call)):
            return None
        name = assignment.targets[0].id
        if name in parameters or sum(isinstance(n, ast.Name) and n.id == name for n in ast.walk(assertion.test)) != 1:
            return None
        assertion = _Substitute({name: assignment.value}).visit(copy.deepcopy(assertion))
        assertion._requires_primitive_string = True
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


def _forwarded_functions(functions, imports):
    """Inline only exact positional forwarding to an imported production call.

    Every formal is forwarded once in the same order, and every use must be
    a direct call. The final concrete-oracle checks still prove the actual
    literal inputs, retained call order and complete original coverage.
    """
    forwarders = {}
    for function in functions:
        parameters = _args(function)
        if (parameters is None or function.name.startswith(("test", "pytest_")) or function.decorator_list
                or len(function.body) != 1 or not isinstance(function.body[0], ast.Return)):
            continue
        value = function.body[0].value
        if (not isinstance(value, ast.Call) or value.keywords or not all(isinstance(arg, ast.Name) for arg in value.args)
                or [arg.id for arg in value.args] != parameters or len(set(parameters)) != len(parameters)):
            continue
        callee = dotted_name(value.func)
        if not callee or callee.split(".")[0] not in imports - {"pytest"}:
            continue
        forwarders[function.name] = parameters, value
    if not forwarders:
        return functions
    for function in functions:
        if any((isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store) and node.id in forwarders)
               or (isinstance(node, ast.arg) and node.arg in forwarders)
               for node in ast.walk(function)):
            return None
    used = set()

    class Calls(ast.NodeTransformer):
        def visit_Call(self, node):
            node = self.generic_visit(node)
            if not isinstance(node.func, ast.Name) or node.func.id not in forwarders:
                return node
            parameters, value = forwarders[node.func.id]
            if node.keywords or len(node.args) != len(parameters) or any(isinstance(arg, ast.Starred) for arg in node.args):
                return node
            used.add(node.func.id)
            return ast.copy_location(_Substitute(dict(zip(parameters, node.args))).visit(copy.deepcopy(value)), node)

    result = []
    for function in functions:
        if function.name in forwarders:
            continue
        function = Calls().visit(function)
        if any(isinstance(node, ast.Name) and node.id in forwarders for node in ast.walk(function)):
            return None
        result.append(function)
    return result if used == forwarders.keys() else None


def _captured_result(body, unavailable):
    """A fresh local holds one primitive subject result used once by its check."""
    if len(body) != 2:
        return None
    assignment, check = body
    if (not isinstance(assignment, ast.Assign) or len(assignment.targets) != 1
            or not isinstance(assignment.targets[0], ast.Name) or not isinstance(assignment.value, ast.Call)
            or not isinstance(check, ast.Assert) or check.msg is not None):
        return None
    name = assignment.targets[0].id
    if (name in unavailable or name.startswith(('__', 'pytest_'))
            or any(isinstance(node, ast.Name) and node.id == name for node in ast.walk(assignment.value))
            or sum(isinstance(node, ast.Name) and node.id == name for node in ast.walk(check)) != 1):
        return None
    assertion = _Substitute({name: assignment.value}).visit(copy.deepcopy(check))
    assertion._requires_primitive_string = True
    return assertion


def _callable_fixtures(functions, imports):
    """Preserve a scalar-string fixture's assertions before its callable.

    Default function scope, no fixture inputs, no cleanup and only direct
    collected consumers are admitted. Each consumer receives the complete
    ordered assertion prefix, including an empty prefix. A two-statement
    result capture becomes one check only under the primitive-result proof.
    """
    fixtures = {}
    for function in functions:
        plain = copy.copy(function)
        plain.decorator_list = []
        if (_args(plain) != [] or len(function.decorator_list) != 1
                or not 1 <= len(function.body) <= MAX_CASES or not isinstance(function.body[-1], ast.Return)):
            continue
        decorator = function.decorator_list[0]
        if isinstance(decorator, ast.Call):
            if decorator.args or decorator.keywords:
                continue
            decorator = decorator.func
        returned = function.body[-1].value
        assertions = [_concrete(statement, {}, imports) for statement in function.body[:-1]]
        if (dotted_name(decorator) != "pytest.fixture" or not isinstance(returned, ast.Name)
                or returned.id not in imports - {"pytest"}
                or any(assertion is None for assertion in assertions)):
            continue
        if any(not all(isinstance(value, ast.Constant) and type(value.value) is str
                       for value in [*assertion.test.left.args, *assertion.test.comparators])
               or assertion.test.left.keywords for assertion in assertions):
            continue
        fixtures[function.name] = function.body[:-1], returned
    if not fixtures:
        return functions, set()
    result, used, expanded = [], set(), set()
    for function in functions:
        if function.name in fixtures:
            continue
        parameters = _args(function)
        if parameters and any(name in fixtures for name in parameters):
            if len(parameters) != 1 or not function.name.startswith("test") or function.decorator_list:
                return None, set()
            name = parameters[0]
            prefix, returned = fixtures[name]
            body = function.body
            if not all(isinstance(statement, ast.Assert) for statement in body):
                captured = _captured_result(body, imports | fixtures.keys())
                if captured is None:
                    return None, set()
                body = [captured]
            function = copy.deepcopy(function)
            function.args.args = []
            function.body = [*copy.deepcopy(prefix), *[_Substitute({name: returned}).visit(statement)
                                                      for statement in copy.deepcopy(body)]]
            used.add(name)
            expanded.add(function.name)
        if any(isinstance(node, ast.Name) and node.id in fixtures for node in ast.walk(function)):
            return None, set()
        result.append(function)
    return (result, expanded) if used == fixtures.keys() else (None, set())


def _test(node, fixtures, tables, imports, helpers, table_helpers, constants, used_constants, *, baseline,
          multiple=False):
    names = _args(node)
    if names is None or not node.name.startswith("test"):
        return None
    if not names and not node.decorator_list:
        captured = _captured_result(node.body, imports | helpers.keys() | table_helpers.keys() | constants.keys())
        if captured is not None:
            concrete = _concrete(captured, {}, imports)
            if concrete is not None:
                return [_Case(concrete, node.body[-1], node)], True, 'captured-result'
    if not names and not node.decorator_list and node.body and isinstance(node.body[0], ast.FunctionDef):
        local_helpers = dict(helpers)
        local_names, remaining = set(), list(node.body)
        while remaining and isinstance(remaining[0], ast.FunctionDef):
            helper = remaining.pop(0)
            candidate = _helper(helper)
            if (candidate is None or helper.name in local_helpers or helper.name in imports
                    or helper.name in constants or helper.name in table_helpers):
                return None
            local_helpers[helper.name] = candidate
            local_names.add(helper.name)
        if not 1 <= len(remaining) <= MAX_CASES:
            return None
        used = {call.func.id for statement in remaining for call in ast.walk(statement)
                if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)}
        if not local_names <= used:
            return None
        assertions = [_checked(statement, {}, imports, local_helpers, set(), {}) for statement in remaining]
        if any(assertion is None for assertion in assertions):
            return None
        return ([_Case(assertion, statement, node) for assertion, statement in zip(assertions, remaining)],
                True, "local-assert-helper")
    if not names and not node.decorator_list and 1 <= len(node.body) <= MAX_CASES and (multiple or len(node.body) > 1):
        assertions = [_checked(statement, {}, imports, helpers, set(), {}) for statement in node.body]
        if all(assertion is not None for assertion in assertions):
            return ([_Case(assertion, statement, node) for assertion, statement in zip(assertions, node.body)],
                    multiple, "unittest" if multiple else "native")
        if multiple and not (len(node.body) == 1 and isinstance(node.body[0], ast.For)):
            return None
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
    elif (len(names) == 1 and names[0] in tables and len(body) == 2
          and isinstance(body[0], ast.Assign) and len(body[0].targets) == 1
          and isinstance(body[0].targets[0], ast.Name) and isinstance(body[1], ast.For)):
        assignment, loop = body
        local_name = assignment.targets[0].id
        columns = _names(loop.target)
        iterator = loop.iter
        values = tables[names[0]]
        expected = assignment.value
        if (local_name in imports | scope | {"zip"} or not columns or len(columns) != 2 or loop.orelse
                or set(columns) & (imports | scope | {local_name, "zip"})
                or not isinstance(iterator, ast.Call) or dotted_name(iterator.func) != "zip"
                or iterator.keywords or [dotted_name(arg) for arg in iterator.args] != [names[0], local_name]
                or not isinstance(values, (ast.List, ast.Tuple)) or not isinstance(expected, (ast.List, ast.Tuple))
                or not 0 < len(values.elts) == len(expected.elts) <= MAX_CASES
                or not all(isinstance(value, ast.Constant) and type(value.value) is str
                           for value in [*values.elts, *expected.elts])):
            return None
        bindings = [dict(zip(columns, pair)) for pair in zip(values.elts, expected.elts)]
        scope.update([local_name, *columns])
        body, table, form = loop.body, True, "zip-fixture"
    elif (len(names) == 1 and names[0] in tables and len(body) == 1 and isinstance(body[0], ast.For)
          and isinstance(body[0].iter, ast.Name) and body[0].iter.id == names[0]):
        loop = body[0]
        columns = _names(loop.target)
        if loop.orelse or not columns or names[0] in columns:
            return None
        bindings = _rows(tables[names[0]], columns, unpack=not isinstance(loop.target, ast.Name))
        scope.update(columns)
        body, table, form = loop.body, True, "table-fixture-loop"
    elif (len(names) == 1 and names[0] in tables and len(body) == 1 and isinstance(body[0], ast.Expr)
          and isinstance(body[0].value, ast.Call) and isinstance(body[0].value.func, ast.Name)
          and body[0].value.func.id in table_helpers and body[0].value.func.id not in scope):
        call = body[0].value
        if (len(call.args) != 1 or call.keywords or not isinstance(call.args[0], ast.Name)
                or call.args[0].id != names[0]):
            return None
        parameter, columns, assertion, unpack = table_helpers[call.func.id]
        bindings = _rows(tables[names[0]], columns, unpack=unpack)
        scope.update([parameter, *columns])
        body, table, form = [assertion], True, "table-fixture-helper"
    elif (len(names) == 1 and names[0] in fixtures
          and isinstance(fixtures[names[0]], (ast.List, ast.Tuple))
          and all(isinstance(value, (ast.Constant, ast.UnaryOp)) and _literal(value)
                  for value in fixtures[names[0]].elts)
          and body and not (isinstance(body[0], ast.Assign) and isinstance(body[0].value, ast.Name)
                           and body[0].value.id == names[0])):
        bindings = _rows(fixtures[names[0]], names, unpack=False)
        table, form = True, "params-fixture"
    elif names:
        if (len(names) != 1 or names[0] not in fixtures or not 2 <= len(body) <= MAX_CASES
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
    source_statement = body[-1] if body else None
    if table and 1 < len(body) <= MAX_CASES:
        # A fresh name for a row cell does not change its value or identity.
        # Substitute aliases back to the original row names before _concrete
        # counts uses, so two names for one mutable cell cannot evade its
        # repeated-object guard. Calls, rebinding and unpacking stay outside
        # this narrow carrier transformation.
        aliases = {}
        for statement in body[:-1]:
            if (not isinstance(statement, ast.Assign) or len(statement.targets) != 1
                    or not isinstance(statement.targets[0], ast.Name)):
                return None
            name = statement.targets[0].id
            if name in scope or name in imports or name in constants:
                return None
            if isinstance(statement.value, ast.Name):
                if statement.value.id not in scope | aliases.keys():
                    return None
            elif isinstance(statement.value, ast.Call):
                callee = dotted_name(statement.value.func)
                checked_expression = body[-1].test if isinstance(body[-1], ast.Assert) else body[-1]
                if ((not callee or callee.split(".")[0] not in imports - {"pytest"}) and not derived_shape(statement.value)
                        or sum(isinstance(node, ast.Name) and node.id == name for node in ast.walk(checked_expression)) != 1
                        or any(isinstance(node, ast.Name) and node.id == name
                               for later in body[:-1] if later is not statement for node in ast.walk(later))):
                    return None
            else:
                return None
            aliases[name] = _Substitute(aliases).visit(copy.deepcopy(statement.value))
            scope.add(name)
        body = [_Substitute(aliases).visit(copy.deepcopy(body[-1]))]
    if bindings is None or len(body) != 1:
        return None
    if table and isinstance(body[0], ast.If):
        condition = body[0]
        if condition.orelse or len(condition.body) != 1:
            return None
        filtered = []
        for row in bindings:
            predicate = _Substitute(row).visit(copy.deepcopy(condition.test))
            value = folded_expected(predicate, lambda _name: False)
            if not isinstance(value, ast.Constant) or type(value.value) is not bool:
                return None
            if value.value:
                filtered.append(row)
        if not filtered:
            # A collected consumer whose whole oracle is disabled cannot be
            # erased from the proof and replaced by another consumer's rows.
            # Preserve the ordinary frontend's per-test execution evidence.
            return None
        bindings, body, form = filtered, [condition.body[0]], "filtered-" + form
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
    return [_Case(assertion, source_statement, node) for assertion in assertions], table, form


def _module(source, *, baseline):
    if len(source) > MAX_SOURCE_BYTES:
        return None
    text = normalize_source(source)
    tree = ast.parse(text)
    if sum(1 for _ in ast.walk(tree)) > MAX_AST_NODES:
        return None
    if any(isinstance(node, (ast.FunctionDef, ast.ClassDef))
           and (node.name in _IMPLICIT_HOOKS or node.name.startswith(("pytest_", "__")))
           for node in tree.body):
        return None  # validate implicit entry points before any helper can be removed
    raises_oracles = extract_raises_oracles(tree)
    tuple_tests = expand_tuple_oracles(tree)
    predicate_tests = expand_predicate_helpers(tree)
    if predicate_tests is None:
        return None
    prefix_tests = expand_prefix_predicates(tree)
    if prefix_tests is None:
        return None
    inert_helpers = prune_inert_helpers(tree)
    literal_fixture_tests = expand_literal_fixtures(tree)
    factory_tests = expand_literal_table_factories(tree)
    indexed_fixture_tests = expand_indexed_fixture_tables(tree)
    # A default-scope literal fixture that no source requests contributes no
    # oracle or setup effects. Keep every reference, shadowed definition,
    # marker string and non-default decorator visible to the ordinary parser.
    references = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    references.update(node.arg for node in ast.walk(tree) if isinstance(node, ast.arg))
    references.update(node.value for node in ast.walk(tree)
                      if isinstance(node, ast.Constant) and type(node.value) is str)
    definitions = Counter(node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.ClassDef)))
    plain_pytest = any(isinstance(node, ast.Import) and len(node.names) == 1
                       and node.names[0].name == "pytest" and node.names[0].asname is None for node in tree.body)
    retained = []
    for node in tree.body:
        unused_fixture = (plain_pytest and isinstance(node, ast.FunctionDef) and _args(node) == []
                          and node.name not in references and definitions[node.name] == 1
                          and not node.name.startswith("test") and len(node.decorator_list) == 1
                          and dotted_name(node.decorator_list[0]) == "pytest.fixture"
                          and len(node.body) == 1 and isinstance(node.body[0], ast.Return)
                          and _literal(node.body[0].value))
        if not unused_fixture:
            retained.append(node)
    pruned_fixtures = len(retained) != len(tree.body)
    tree.body = retained
    wrapper_tests = expand_wrappers(tree)
    if wrapper_tests is None:
        return None
    expand_operator_asserts(tree)
    block_tests = expand_string_blocks(tree)
    if block_tests is None:
        return None
    unittest_expansion = expand_unittest_classes(tree)
    if unittest_expansion is None:
        return None
    unittest_tests, subtest_only = unittest_expansion
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
            if names.intersection(bound) or len(set(bound)) != len(bound) or any(name.startswith("__") for name in bound):
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
    count_before_forwarding = len(functions)
    functions = _forwarded_functions(functions, imports)
    if functions is None:
        return None
    expanded_forwarders = len(functions) != count_before_forwarding
    functions, callable_fixture_tests = _callable_fixtures(functions, imports)
    if functions is None:
        return None
    if callable_fixture_tests and not pytest_imported:
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
    result, table, forms, auxiliary = [], False, [], []
    used_fixtures, used_helpers, used_tables = Counter(), Counter(), Counter()
    for function in functions:
        if function.name in fixtures or function.name in tables or function.name in helpers or function.name in table_helpers:
            continue
        expanded = _test(function, fixtures, tables, imports, helpers, table_helpers, constants, used_constants,
                         baseline=baseline, multiple=function.name in unittest_tests | callable_fixture_tests)
        if expanded is None:
            # A discarded comparison is never an oracle. It can be omitted
            # only when another real assertion checks that same call/input,
            # and the caller closes production purity on both snapshots.
            # This admits redundant calls added beside a full subTest table,
            # while retaining assertion removal and new input boundaries.
            if (_args(function) != [] or function.decorator_list or not function.name.startswith('test')
                    or not 1 <= len(function.body) <= MAX_CASES
                    or not all(isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Compare)
                               for statement in function.body)):
                return None
            comparisons = [_concrete(ast.copy_location(ast.Assert(test=statement.value, msg=None), statement), {}, imports)
                           for statement in function.body]
            if any(assertion is None for assertion in comparisons):
                return None
            auxiliary.extend(_Case(assertion, statement, function)
                             for assertion, statement in zip(comparisons, function.body))
            continue
        cases, is_table, form = expanded
        if function.name in class_tests:
            is_table, form = True, "plain-class"
        if function.name in wrapper_tests:
            is_table, form = True, "oracle-wrapper"
        if function.name in callable_fixture_tests:
            is_table, form = True, "callable-fixture"
        if function.name in factory_tests:
            is_table, form = True, "literal-table-factory"
        if function.name in indexed_fixture_tests:
            is_table, form = True, "indexed-fixture-parametrize"
        if function.name in literal_fixture_tests:
            is_table, form = True, "literal-fixtures"
        if function.name in prefix_tests:
            is_table, form = True, "literal-prefix-predicate"
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
    # pytest reuses each literal params object across its consumers. Concrete
    # copies are equivalent only when every imported call is proved pure on
    # both snapshots, so no earlier consumer can mutate a later row's input.
    shared_fixture_params = any(count > 1 and not _immutable_rows(fixtures[name])
                                for name, count in used_fixtures.items())
    if shared_fixture_params:
        for case in result:
            case.assertion._requires_shared_collection_inputs = True
    if any(count > 1 and not _immutable_rows(constants[name]) for name, count in used_constants.items()):
        return None
    if any(used_tables[name] > 1 and not _immutable_rows(tables[name]) for name in shared_tables):
        return None
    # A helper nobody calls never runs, but leaving one uninspected in an
    # otherwise transparent module weakens the "entire module" claim the
    # projection rests on. Same discipline as the fixtures above.
    if helpers.keys() | table_helpers.keys() != used_helpers.keys() or tables.keys() != used_tables.keys():
        return None
    if any(form == "zip-fixture" for _, form in forms) and "zip" in names:
        return None
    if any(getattr(case.assertion, "_requires_approx_authority", False) for case in result) and not pytest_imported:
        return None
    derived_authorities = set().union(*(getattr(case.assertion, "_requires_derived_authority", set()) for case in result))
    if derived_authorities & names or any(isinstance(node, ast.arg) and node.arg in derived_authorities
                                         for node in ast.walk(tree)):
        return None
    checked_subjects = {_subject_key(case) for case in result}
    if any(_subject_key(case) not in checked_subjects for case in auxiliary):
        return None
    return (text, import_nodes, result, table, pytest_imported, modules, forms, wrapper_authorities,
            bool(block_tests or unittest_tests or pruned_fixtures or inert_helpers
                 or expanded_forwarders or factory_tests or indexed_fixture_tests or literal_fixture_tests
                 or auxiliary or raises_oracles or tuple_tests or shared_fixture_params
                 or predicate_tests or prefix_tests or any(form == 'string-block' for _, form in forms)),
            bool(unittest_tests),
            subtest_only and all(name in unittest_tests for name, _ in forms), raises_oracles)


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
        comparison = case.assertion.test
        if (getattr(case.assertion, "_requires_operator_authority", False)
                and isinstance(comparison.ops[0], ast.Is)
                and isinstance(comparison.comparators[0], ast.Constant)
                and comparison.comparators[0].value is None):
            # The ordinary null-check form retains strength30. The proved
            # concrete oracle also states the literal answer None; retain
            # that fact so replacing it by numeric approximation cannot hide
            # behind an apparent strength increase.
            assertions = [replace(assertion, right_literal="None", right_value="None") for assertion in assertions]
        units.append(replace(unit, span=span, side=replace(unit.side, span=span, assertions=assertions)))
    return replace(parsed, units=units)


def _subject_key(case):
    compare = case.assertion.test
    key = stable_dump(compare.left) + ":" + getattr(case.assertion, "_paired_operator", type(compare.ops[0]).__name__)
    if case.body is not None:
        key += ":aux:" + stable_dump(ast.Module(body=case.body[:-1], type_ignores=[]))
    return key


def _pair_approximate_identity(old, new):
    """Keep the actual operators when an identity oracle becomes approximate.

    This only establishes which concrete call the two assertions check; their
    distinct operators and expectations remain in the projected source for
    ordinary weakening detection. It grants no identity/equality equivalence.
    """
    if len(new) < len(old):
        return False
    pairs = []
    for before, after in zip(old, new):
        if _subject_key(before) == _subject_key(after):
            continue
        previous, current = before.assertion.test, after.assertion.test
        expected = previous.comparators[0]
        if (before.body is not None or after.body is not None
                or stable_dump(previous.left) != stable_dump(current.left)
                or not isinstance(previous.ops[0], ast.Is) or not isinstance(current.ops[0], ast.Eq)
                or not isinstance(expected, ast.Constant) or type(expected.value) not in (bool, type(None))
                or not _approx_expected(current.comparators[0])):
            return False
        pairs.append((before, after))
    if not pairs:
        return False
    for before, after in pairs:
        after.assertion._paired_operator = type(before.assertion.test.ops[0]).__name__
        before.assertion._requires_operator_authority = True
        after.assertion._requires_operator_authority = True
    return True


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


def _closed_proof_imports(module, calls):
    """Every import must be an inspected subject or a proved standard wrapper."""
    called = {call.func.id for call in calls if isinstance(call.func, ast.Name)}
    for node in ast.parse(module[0]).body:
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        authority = trusted_wrapper_import(node)
        if authority is not None and authority in module[7]:
            continue  # the caller checked this wrapper's unshadowed source
        if isinstance(node, ast.Import):
            if any(alias.name != "pytest" or alias.asname for alias in node.names):
                return False
        elif node.level or any((alias.asname or alias.name) not in called for alias in node.names):
            return False
    return True


def _native_renames(old, new):
    """Renamed/reordered one-assert tests retain every concrete call input.

    This optional proof additionally requires pure production on both sides;
    source-order-sensitive subjects cannot acquire renamed-unit identities.
    """
    if old[3] or new[3] or not old[2] or len(old[2]) != len(new[2]):
        return False
    for module in (old, new):
        if any(form != 'native' for _, form in module[6]):
            return False
        if any(len(case.source_function.body) != 1 or not isinstance(case.source_function.body[0], ast.Assert)
               for case in module[2]):
            return False
    return ([case.source_function.name for case in old[2]] != [case.source_function.name for case in new[2]]
            and Counter(_subject_key(case) for case in old[2]) == Counter(_subject_key(case) for case in new[2]))


def project_table_consolidation(before: bytes, after: bytes, before_parsed: ParsedFile, after_parsed: ParsedFile,
                                *, path: str, root_reader=None, root_searcher=None, changes=()):
    """Project proved concrete coverage while retaining expected-value edits.

    Both snapshots require closed repository startup context; unrelated
    inert cochanges do not veto a proof. Supported carriers include native
    comparisons, literal parametrize/fixture/loop tables, complete local
    assertion helpers, stateless plain classes and exact wrapper grammars.
    Their ordinary subject/input sequence must preserve the complete old
    prefix. Marked/indirect/dynamic rows and unknown dispatch retain the
    ordinary frontend. Module docstrings and unique literal data are inert.

    Two extensions require closed pure imported source: a complete string
    assignment plus length/prefix/exact assertions, and bounded TestCase
    collection/setup. The former retains every auxiliary assertion; the
    latter preserves exact oracle multiplicity and suite pass/fail semantics
    despite changed grouping/order. It does not claim execution-trace
    equivalence. Arbitrary multi-assert helpers, lifecycle code, side effects,
    explicit setup calls and new setup failure barriers receive no credit.
    """
    if (root_reader is None or root_searcher is None or not before_parsed.parse_ok or not after_parsed.parse_ok
            or not before_parsed.units):
        return before_parsed, after_parsed
    try:
        old, new = _module(before, baseline=True), _module(after, baseline=False)
        if old is None:
            old = _module(before, baseline=False)
        if old is None or new is None or old[1] != new[1]:
            return before_parsed, after_parsed
        if Counter(oracle.key for oracle in old[11]) - Counter(oracle.key for oracle in new[11]):
            return before_parsed, after_parsed  # never discard a removed/changed exception or its exact message
        native_renames = _native_renames(old, new)
        if (any(form == 'literal-fixtures' for _, form in old[6])
                and any(form == 'literal-fixtures' for _, form in new[6])):
            return before_parsed, after_parsed  # retain existing same-carrier fixture provenance ownership
        if not (old[3] or new[3] or native_renames):
            return before_parsed, after_parsed
        if (old[3] and new[3] and old[6] == new[6]
                and _ordinary_rows_cover(old, before_parsed) and _ordinary_rows_cover(new, after_parsed)):
            # An edit within the same row carrier/unit retains #135 and the
            # row-identity channel. Projection proves a carrier transition;
            # it must not relabel ordinary parametrize expectation findings.
            return before_parsed, after_parsed
        old_keys = [_subject_key(case) for case in old[2]]
        new_keys = [_subject_key(case) for case in new[2]]
        # Field checks do not reject additional keys. A complete dictionary
        # equality may replace them, but the reverse loses an oracle even
        # when the field values match. Keep every original complete check
        # and its multiplicity before granting carrier equivalence.
        old_complete = Counter(_subject_key(case) for case in old[2]
                               if not getattr(case.assertion, '_partial_dictionary_fields', False))
        new_complete = Counter(_subject_key(case) for case in new[2]
                               if not getattr(case.assertion, '_partial_dictionary_fields', False))
        if (any(getattr(case.assertion, '_partial_dictionary_fields', False) for case in new[2])
                and old_complete - new_complete):
            return before_parsed, after_parsed
        if old_keys != new_keys[:len(old_keys)] and _pair_approximate_identity(old[2], new[2]):
            old_keys = [_subject_key(case) for case in old[2]]
            new_keys = [_subject_key(case) for case in new[2]]
        indexed_extension = (len(old[6]) == len(new[6]) == 1 and old[6][0][0] == new[6][0][0]
                             and old[6][0][1] == "parametrize" and new[6][0][1] == "indexed-fixture-parametrize"
                             and len(set(old_keys)) == len(old_keys) and len(set(new_keys)) == len(new_keys)
                             and not (Counter(old_keys) - Counter(new_keys)))
        # Extra literal cases can follow the complete old sequence. They
        # cannot run before an old oracle and change what it subsequently
        # sees; insertion/reordering stays outside the proof.
        if not old_keys:
            return before_parsed, after_parsed
        if ((old[9] or new[9]) and Counter(old_keys) != Counter(new_keys)
                and not (new[10] and not Counter(old_keys) - Counter(new_keys))):
            # TestCase setup precedes each test body. Do not admit additional
            # setup/oracles as an unordered superset: their failure barriers
            # were absent from the original suite. Only the exact existing
            # pure oracle multiplicity may change grouping or collection order.
            # An after-suite of only default subTest loops is different: a
            # failing added row still runs later rows, so a pure superset
            # preserves every original check without a new failure barrier.
            return before_parsed, after_parsed
        if old_keys != new_keys[:len(old_keys)]:
            if not (old[9] or new[9] or indexed_extension or native_renames) or Counter(old_keys) - Counter(new_keys):
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
        message_calls = [case.assertion.test.left for case in module[2]
                         if getattr(case.assertion, "_requires_primitive_string", False)]
        approximate = any(getattr(case.assertion, "_requires_approx_authority", False)
                          or getattr(case.assertion, "_requires_operator_authority", False) for case in module[2])
        derived = any(hasattr(case.assertion, "_requires_derived_authority") for case in module[2])
        if derived:
            calls = [case.assertion.test.left for case in module[2]]
            called = {call.func.id for call in calls if isinstance(call.func, ast.Name)}
            for node in ast.parse(module[0]).body:
                if isinstance(node, ast.Import):
                    if any(alias.name != "pytest" or alias.asname for alias in node.names):
                        return before_parsed, after_parsed
                elif isinstance(node, ast.ImportFrom):
                    if node.level or any((alias.asname or alias.name) not in called for alias in node.names):
                        return before_parsed, after_parsed
            if not pure_imported_calls(module[0].encode(), calls, path=path, read=read,
                                       result_proof=primitive_derived_result):
                return before_parsed, after_parsed
        if approximate:
            calls = [case.assertion.test.left for case in module[2]]
            called = {call.func.id for call in calls if isinstance(call.func, ast.Name)}
            # Approx objects in a parameter decorator are constructed before
            # test execution. Production or another import must not replace
            # pytest.approx between collection and an inline assertion.
            for node in ast.parse(module[0]).body:
                if isinstance(node, ast.Import):
                    if any(alias.name != "pytest" or alias.asname for alias in node.names):
                        return before_parsed, after_parsed
                elif isinstance(node, ast.ImportFrom):
                    if node.level or any((alias.asname or alias.name) not in called for alias in node.names):
                        return before_parsed, after_parsed
            if not pure_imported_calls(module[0].encode(), calls, path=path, read=read):
                return before_parsed, after_parsed
        if message_calls or any(form in {"zip-fixture", "callable-fixture"} for _, form in module[6]):
            calls = [case.assertion.test.left for case in module[2]]
            called = {call.func.id for call in calls if isinstance(call.func, ast.Name)}
            # Another module import or oracle could replace a function or a
            # formatting authority before this helper runs. Every imported
            # source and every preceding subject call must earn the same
            # primitive-string proof, even when its own assert has no message.
            for node in ast.parse(module[0]).body:
                if isinstance(node, ast.Import):
                    if any(alias.name != "pytest" or alias.asname for alias in node.names):
                        return before_parsed, after_parsed
                elif isinstance(node, ast.ImportFrom):
                    if node.level or any((alias.asname or alias.name) not in called for alias in node.names):
                        return before_parsed, after_parsed
            strings_only = any(form in {"zip-fixture", "callable-fixture"} for _, form in module[6])
            def primitive_result(source, target, call):
                return (primitive_string_result(source, target, call)
                        or not strings_only and primitive_literal_result(source, target, call))
            if not pure_imported_calls(module[0].encode(), calls, path=path, read=read,
                                       result_proof=primitive_result):
                return before_parsed, after_parsed
            if not _module_unshadowed(path, read, "re"):
                return before_parsed, after_parsed
        if old[8] or new[8] or native_renames:
            calls = [case.assertion.test.left for case in module[2]] + [oracle.call for oracle in module[11]]
            if not _closed_proof_imports(module, calls) or not pure_imported_calls(
                    module[0].encode(), calls, path=path, read=read):
                return before_parsed, after_parsed
        for case in module[2]:
            if getattr(case.assertion, '_requires_shared_collection_inputs', False) and not pure_imported_calls(
                    module[0].encode(), [case.assertion.test.left], path=path, read=read,
                    result_proof=shared_literal_collection_inputs):
                return before_parsed, after_parsed
            arity = getattr(case.assertion, '_requires_tuple_arity', None)
            if arity is not None and not pure_imported_calls(
                    module[0].encode(), [case.assertion.test.left], path=path, read=read,
                    result_proof=lambda source, target, call: primitive_tuple_result(source, target, call, arity)):
                return before_parsed, after_parsed
    return (retain_raises_units(_project(before_parsed, old[0], old[2]), old[0], old[11]),
            retain_raises_units(_project(after_parsed, new[0], new[2]), new[0], new[11]))

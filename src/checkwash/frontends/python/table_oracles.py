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
from checkwash.frontends.python.boolean_comparison_pairs import pair_boolean_comparisons, primitive_boolean_result
import copy
import hashlib
import math
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import PurePosixPath

from checkwash.frontends.python.frontend import ParsedFile, _Offsets, normalize_source, parse_python
from checkwash.frontends.python.conditional_oracles import conditional_oracle_carriers
from checkwash.frontends.python.expected_constants import folded_expected
from checkwash.frontends.python.oracle_blocks import IMPLICIT_ENTRY_NAMES, expand_string_blocks, string_block
from checkwash.frontends.python.oracle_purity import primitive_literal_result, pure_imported_calls, shared_literal_collection_inputs
from checkwash.frontends.python.primitive_strings import primitive_string_result
from checkwash.frontends.python.derived_literals import derived_shape, fold_derived, primitive_derived_result
from checkwash.frontends.python.indexed_fixture_tables import expand_indexed_fixture_tables
from checkwash.frontends.python.oracle_unittest import expand_unittest_classes
from checkwash.frontends.python.oracle_wrappers import expand_operator_asserts, expand_wrappers, trusted_wrapper_import
from checkwash.frontends.python.snapshot_context import inert_test_execution_context
from checkwash.frontends.python.literal_expected_bindings import expand_literal_expected_bindings
from checkwash.frontends.python.literal_subject_bindings import expand_literal_subject_bindings
from checkwash.frontends.python.captured_assert_helpers import expand_captured_assert_helpers
from checkwash.frontends.python.regrouped_captures import capture_obligations, regroup_complete_captures
from checkwash.frontends.python.inert_signatures import strip_none_test_returns
from checkwash.frontends.python.table_factories import expand_literal_table_factories
from checkwash.frontends.python.inert_helpers import prune_inert_helpers
from checkwash.frontends.python.literal_fixtures import expand_literal_fixtures
from checkwash.frontends.python.parametrized_membership_oracles import expand_parametrized_membership
from checkwash.frontends.python.parameter_helper_answers import expand_parameter_helper_answers
from checkwash.frontends.python.failing_exception_wrappers import expand_failing_exception_wrappers
from checkwash.frontends.python.fixture_conditional_answers import expand_fixture_conditional_answers
from checkwash.frontends.python.hex_tuple_answers import expand_hex_tuple_answers
from checkwash.frontends.python.literal_iteration_oracles import expand_literal_iteration_oracles
from checkwash.frontends.python.fixture_row_helpers import expand_fixture_row_helpers
from checkwash.frontends.python.raises_oracles import extract_raises_oracles, retain_raises_units
from checkwash.frontends.python.tuple_oracles import expand_tuple_oracles, primitive_tuple_result
from checkwash.frontends.python.local_auxiliary_oracles import (extract_local_auxiliary_oracles,
                                                              retain_local_auxiliary_units)
from checkwash.frontends.python.helper_predicates import expand_predicate_helpers
from checkwash.frontends.python.prefix_predicates import expand_prefix_predicates
from checkwash.frontends.python.callable_fixture_rows import consumer_rows, fixture_prefix_rows
from checkwash.frontends.python.normalized_result_tables import project_normalized_result_table
from checkwash.frontends.python.unique_predicates import (complete_unique_helper, expand_unique_predicates,
                                                       _unique_literal, input_unique_count, unshadowed_unique_builtins)
from checkwash.frontends.python.table_oracles_module import (
    collect_module_cases, collect_top_level_declarations, finalize_module_projection,
    lower_module_carriers, parse_and_validate_module_ast, resolve_module_definitions,
)
from checkwash.frontends.python.table_oracles_projection import (
    align_concrete_case_sequences, parse_compatible_carrier_pair,
    render_projected_pair, verify_module_snapshot_purity,
)
from checkwash.frontends.python.table_oracles_test import (
    _UNMATCHED, expand_direct_test_carrier, finalize_test_cases,
    inline_row_aliases, resolve_test_carrier,
)
from checkwash.ir.astutil import dotted_name, stable_dump
import sys

_SELF = sys.modules[__name__]

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
    if getattr(concrete, '_requires_unique_expected', False) and not _unique_literal(expected):
        return None
    if getattr(concrete, '_requires_input_unique_count', False) and not input_unique_count(actual, expected):
        return None
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
            or len({keyword.arg for keyword in actual.keywords}) != len(actual.keywords)
            or not all(keyword.arg is not None and _literal(keyword.value) for keyword in actual.keywords)):
        return None
    if approximate:
        concrete._requires_approx_authority = True
    if concrete.msg is not None:
        concrete._requires_primitive_string = True
        message = concrete.msg
        if isinstance(message, ast.Constant) and type(message.value) is str:
            pass
        elif (isinstance(message, ast.BinOp) and isinstance(message.op, ast.Add)
              and isinstance(message.left, ast.Constant) and type(message.left.value) is str
              and isinstance(message.right, ast.Call) and isinstance(message.right.func, ast.Name)
              and message.right.func.id == 'repr' and len(message.right.args) == 1 and not message.right.keywords
              and _literal(message.right.args[0])
              and not any(isinstance(item, ast.Call) for item in ast.walk(message.right.args[0]))):
            # Only builtin representation of literal data is inert. Verify
            # repr's whole-module binding authority after collecting names;
            # the existing diagnostic proof closes all production imports.
            concrete._requires_repr_authority = True
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
    if (not isinstance(decorator, ast.Call) or dotted_name(decorator.func) != "pytest.fixture" or decorator.args):
        return None
    keywords = {keyword.arg: keyword.value for keyword in decorator.keywords}
    if len(keywords) != len(decorator.keywords) or set(keywords) not in ({'params'}, {'params', 'ids'}):
        return None
    if 'ids' in keywords:
        values, ids = keywords['params'], keywords['ids']
        if (not isinstance(values, (ast.List, ast.Tuple)) or not isinstance(ids, (ast.List, ast.Tuple))
                or len(ids.elts) != len(values.elts)
                or not all(isinstance(item, ast.Constant) and type(item.value) is str for item in ids.elts)
                or len({item.value for item in ids.elts}) != len(ids.elts)):
            return None
    return keywords['params']


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
            or node.decorator_list or len(node.body) not in (1, 2, 3)
            or len(set(parameters)) != len(parameters)):
        return None
    if len(node.body) == 3:
        assertion = complete_unique_helper(node)
        return (parameters, assertion) if assertion is not None else None
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
            member._source_qualname = f"{node.name}.{original.name}"
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
    if helper is None:
        return None
    parameters, assertion = helper
    if len(call.args) > len(parameters):
        return None
    arguments = dict(zip(parameters, call.args))
    for keyword in call.keywords:
        if keyword.arg not in parameters or keyword.arg in arguments:
            return None  # unknown, repeated, positional collision or **kwargs
        arguments[keyword.arg] = keyword.value
    if len(arguments) != len(parameters):
        return None
    inner, consumed = {}, Counter()
    for parameter, argument in arguments.items():
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
    if call.keywords:
        # Keyword order cannot change subject/helper bindings through a
        # callback or repository back-reference. Both snapshots must earn
        # the closed imported-source proof before this new carrier is used.
        assertion = copy.deepcopy(assertion)
        assertion._requires_closed_helper = True
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

    Default function scope, no fixture dependencies, no cleanup and only direct
    collected consumers are admitted. Each consumer receives the complete
    ordered assertion prefix, including an empty prefix. A two-statement
    result capture becomes one check only under the primitive-result proof.
    """
    fixtures = {}
    for function in functions:
        plain = copy.copy(function)
        plain.decorator_list = []
        parameters = _args(plain)
        if (parameters is None or len(function.decorator_list) != 1
                or not 1 <= len(function.body) <= MAX_CASES or not isinstance(function.body[-1], ast.Return)):
            continue
        prefixes = fixture_prefix_rows(function, parameters)
        if prefixes is None:
            continue
        returned = function.body[-1].value
        # Fixture injection masks a same-named module import. In particular,
        # `return request` returns pytest's FixtureRequest, never an imported
        # function named request, even when the fixture prefix is empty.
        available_imports = imports - set(parameters)
        assertions = [_concrete(statement, {}, available_imports) for prefix in prefixes for statement in prefix]
        if (not isinstance(returned, ast.Name)
                or returned.id not in available_imports - {"pytest"}
                or any(assertion is None for assertion in assertions)):
            continue
        if any(not all(isinstance(value, ast.Constant) and type(value.value) is str
                       for value in [*assertion.test.left.args, *assertion.test.comparators])
               or assertion.test.left.keywords for assertion in assertions):
            continue
        fixtures[function.name] = prefixes, returned
    if not fixtures:
        return functions, set()
    result, used, expanded = [], set(), set()
    for function in functions:
        if function.name in fixtures:
            continue
        parameters = _args(function)
        if parameters and any(name in fixtures for name in parameters):
            requested = [name for name in parameters if name in fixtures]
            if len(requested) != 1 or not function.name.startswith("test"):
                return None, set()
            name = requested[0]
            prefixes, returned = fixtures[name]
            rows = consumer_rows(function, parameters, name)
            if rows is None or function.decorator_list and len(prefixes) != 1:
                return None, set()  # no unproved product of fixture and decorator parameter axes
            body = function.body
            if not all(isinstance(statement, ast.Assert) for statement in body):
                captured = _captured_result(body, imports | fixtures.keys() | set(parameters))
                if captured is None:
                    return None, set()
                body = [captured]
            function = copy.deepcopy(function)
            function.args.args = []
            function.decorator_list = []
            function.body = []
            for prefix in prefixes:
                for row in rows:
                    checks = [_Substitute({name: returned}).visit(statement) for statement in copy.deepcopy(body)]
                    if row:
                        # Keep row-use accounting inside _concrete; eager
                        # substitution must not bypass its alias guard.
                        checks = [_concrete(statement, row, imports) for statement in checks]
                        if any(statement is None for statement in checks):
                            return None, set()
                    function.body.extend([*copy.deepcopy(prefix), *checks])
            if len(function.body) > MAX_CASES:
                return None, set()
            used.add(name)
            expanded.add(function.name)
        if any(isinstance(node, ast.Name) and node.id in fixtures for node in ast.walk(function)):
            return None, set()
        result.append(function)
    return (result, expanded) if used == fixtures.keys() else (None, set())


def _captured_blocks(node, imports, forbidden):
    """Partition complete capture/check blocks without carrying local aliases.

    Every block must independently satisfy the existing string/dictionary
    grammar and literal imported-call proof. Reassigning the result name is
    harmless only under the two-sided production purity check required by
    the string-block carrier; no value can flow across block boundaries.
    """
    if forbidden & {'len', 'max'}:
        return None
    groups = []
    for statement in node.body:
        if isinstance(statement, ast.Assign) and isinstance(statement.value, ast.Call):
            if (len(statement.targets) != 1 or not isinstance(statement.targets[0], ast.Name)
                    or statement.targets[0].id in forbidden | {'len', 'max'}):
                return None
            groups.append([statement])
        elif isinstance(statement, ast.Assert) and groups:
            groups[-1].append(statement)
        else:
            return None
    if not 2 <= len(groups) <= MAX_CASES:
        return None
    result = []
    for group in groups:
        function = copy.copy(node)
        function.body = group
        block = string_block(function)
        if block is None:
            return None
        assertion, body = block
        concrete = _concrete(assertion, {}, imports)
        if concrete is None:
            return None
        result.append(_Case(concrete, group[-1], node, body))
    return result


def _test(node, fixtures, tables, imports, helpers, table_helpers, constants, used_constants, *, baseline,
          multiple=False):
    names = _args(node)
    if names is None or not node.name.startswith("test"):
        return None
    if not names and not node.decorator_list:
        direct = expand_direct_test_carrier(
            node, imports, helpers, table_helpers, constants, multiple=multiple, rt=_SELF
        )
        if direct is not _UNMATCHED:
            return direct
    scope = set(names)
    carrier = resolve_test_carrier(
        node, names, fixtures, tables, imports, table_helpers, constants, used_constants, scope,
        baseline=baseline, rt=_SELF,
    )
    if carrier is None:
        return None
    body, bindings, table, form = carrier
    source_statement = body[-1] if body else None
    if table and 1 < len(body) <= MAX_CASES:
        body = inline_row_aliases(body, scope, imports, constants, _SELF)
        if body is None:
            return None
    return finalize_test_cases(
        node, body, bindings, table, form, scope, source_statement, imports, helpers, constants, _SELF
    )


def _module(source, *, baseline):
    parsed = parse_and_validate_module_ast(source, _SELF)
    if parsed is None:
        return None
    lowered = lower_module_carriers(parsed[0], parsed[1], source, _SELF)
    if lowered is None:
        return None
    declarations = collect_top_level_declarations(lowered.tree, _SELF)
    if declarations is None:
        return None
    definitions = resolve_module_definitions(declarations, baseline=baseline, rt=_SELF)
    if definitions is None:
        return None
    collected = collect_module_cases(lowered, declarations, definitions, baseline=baseline, rt=_SELF)
    if collected is None:
        return None
    return finalize_module_projection(lowered, declarations, definitions, collected, _SELF)


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


def source_unit_map(parsed):
    """Map original `ParsedUnit` spans (and unique start offsets) to source Python test qualnames."""
    by_span, by_start, start_counts = {}, {}, Counter()
    for unit in getattr(parsed, "units", ()):
        name = getattr(unit, "source_unit", "") or unit.qualname
        by_span[unit.span] = name
        start_counts[unit.span[0]] += 1
        by_start[unit.span[0]] = name
    unique_starts = {start: name for start, name in by_start.items() if start_counts[start] == 1}
    return by_span, unique_starts


def resolve_source_unit(source_units, span, function) -> str:
    """Resolve the enclosing Python test's qualified name for a projected AST function."""
    if source_units is not None:
        by_span, unique_starts = source_units
        if span in by_span:
            return by_span[span]
        if span[0] in unique_starts:
            return unique_starts[span[0]]
    return getattr(function, "_source_qualname", function.name)


def _project(parsed, text, cases, source_units=None):
    if source_units is None:
        source_units = source_unit_map(parsed)
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
        source_unit = resolve_source_unit(source_units, span, case.source_function)
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
        units.append(replace(
            unit,
            span=span,
            side=replace(unit.side, span=span, assertions=assertions),
            source_unit=source_unit,
        ))
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


_CAPTURED_SPECIAL_AUTHORITIES = (
    "_requires_boolean_result",
    "_requires_approx_authority",
    "_requires_operator_authority",
    "_requires_derived_authority",
    "_requires_repr_authority",
    "_requires_tuple_arity",
    "_requires_unique_expected",
    "_requires_input_unique_count",
    "_requires_closed_helper",
    "_requires_shared_collection_inputs",
    "_partial_dictionary_fields",
)


def _same_captured_results(old, new) -> bool:
    """True when every same-named `captured-result` test keeps its local binding, call/operator, and plain RHS."""
    captured_names = {name for name, form in old[6] if form == "captured-result"}
    if not captured_names:
        return True
    old_cases = [case for case in old[2] if case.source_function.name in captured_names]
    new_cases = [case for case in new[2] if case.source_function.name in captured_names]
    if len(old_cases) != len(captured_names) or len(new_cases) != len(captured_names):
        return False
    old_by_name = {case.source_function.name: case for case in old_cases}
    new_by_name = {case.source_function.name: case for case in new_cases}
    for name in captured_names:
        before_case, after_case = old_by_name.get(name), new_by_name.get(name)
        if before_case is None or after_case is None:
            return False
        if _subject_key(before_case) != _subject_key(after_case):
            return False
        if any(getattr(item.assertion, attr, None) not in (None, False)
               for item in (before_case, after_case) for attr in _CAPTURED_SPECIAL_AUTHORITIES):
            return False
        before_body, after_body = before_case.source_function.body, after_case.source_function.body
        if (len(before_body) != 2 or len(after_body) != 2
                or not isinstance(before_body[0], ast.Assign) or not isinstance(after_body[0], ast.Assign)
                or len(before_body[0].targets) != 1 or len(after_body[0].targets) != 1
                or not isinstance(before_body[0].targets[0], ast.Name)
                or not isinstance(after_body[0].targets[0], ast.Name)
                or before_body[0].targets[0].id != after_body[0].targets[0].id
                or not isinstance(before_body[1], ast.Assert)
                or not isinstance(after_body[1], ast.Assert)
                or not isinstance(before_body[1].test, ast.Compare)
                or not isinstance(after_body[1].test, ast.Compare)
                or not isinstance(before_body[1].test.left, ast.Name)
                or not isinstance(after_body[1].test.left, ast.Name)):
            return False
    return True


def _ordinary_rows_cover(module, parsed, *, allow_captured: bool = False):
    units = {unit.qualname: unit.side for unit in parsed.units}
    return all(
        form == "native"
        or (form == "parametrize" and name in units and units[name].param_rows)
        or (allow_captured and form == "captured-result" and name in units)
        for name, form in module[6]
    )


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
    """Renamed or regrouped native tests retain every concrete call input.

    This optional proof additionally requires pure production on both sides;
    source-order-sensitive subjects cannot acquire renamed-unit identities.
    Each complete body contains only already-proved native assertions or
    direct calls whose helper assertions `_checked` has fully expanded,
    and exact call multiplicity survives a merge or split. Grouping may change
    which assertion executes after a failure, but not pure suite pass/fail.
    """
    if old[3] or new[3] or not old[2] or len(old[2]) != len(new[2]):
        return False
    for module in (old, new):
        if any(form != 'native' for _, form in module[6]):
            return False
        if any(not case.source_function.body or not all(isinstance(statement, (ast.Assert, ast.Expr))
               for statement in case.source_function.body)
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
    normalized = project_normalized_result_table(
        before, after, before_parsed, after_parsed, path=path,
        root_reader=root_reader, root_searcher=root_searcher, changes=changes)
    if normalized is not None:
        return normalized
    try:
        pair = parse_compatible_carrier_pair(before, after, before_parsed, after_parsed, _SELF)
        if pair is None:
            return before_parsed, after_parsed
        old, new, native_renames = pair
        if not align_concrete_case_sequences(old, new, native_renames=native_renames, rt=_SELF):
            return before_parsed, after_parsed
    except (SyntaxError, ValueError, TypeError, MemoryError, RecursionError):
        return before_parsed, after_parsed
    # Snapshot errors must escape the parser's unsupported-syntax fallback.
    changes = tuple(changes)
    if not _compatible_cochanges(path, old[5] | new[5], changes):
        return before_parsed, after_parsed
    closed_purity_required = bool(old[8] or new[8] or native_renames)
    for module, (read, search) in zip((old, new), _context_snapshots(
            path, before, after, changes, root_reader, root_searcher)):
        if not verify_module_snapshot_purity(
            module, path=path, read=read, search=search,
            closed_purity_required=closed_purity_required, rt=_SELF,
        ):
            return before_parsed, after_parsed
    return render_projected_pair(before_parsed, after_parsed, old, new, _SELF)

"""Test-level carrier decomposition stages for concrete table oracles."""

from __future__ import annotations

import ast
import copy

from checkwash.ir.astutil import dotted_name

_UNMATCHED = object()


def expand_local_assert_helpers(node, imports, helpers, table_helpers, constants, rt):
    """Expand leading local single-assertion helpers inside a parameterless test."""
    local_helpers = dict(helpers)
    local_names, remaining = set(), list(node.body)
    while remaining and isinstance(remaining[0], ast.FunctionDef):
        helper = remaining.pop(0)
        candidate = rt._helper(helper)
        if (candidate is None or helper.name in local_helpers or helper.name in imports
                or helper.name in constants or helper.name in table_helpers):
            return None
        local_helpers[helper.name] = candidate
        local_names.add(helper.name)
    if not 1 <= len(remaining) <= rt.MAX_CASES:
        return None
    used = {call.func.id for statement in remaining for call in ast.walk(statement)
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)}
    if not local_names <= used:
        return None
    assertions = [rt._checked(statement, {}, imports, local_helpers, set(), {}) for statement in remaining]
    if any(assertion is None for assertion in assertions):
        return None
    return ([rt._Case(assertion, statement, node) for assertion, statement in zip(assertions, remaining)],
            True, "local-assert-helper")


def expand_direct_test_carrier(node, imports, helpers, table_helpers, constants, *, multiple, rt):
    """Expand parameterless, undecorated direct carriers or return _UNMATCHED."""
    forbidden = imports | helpers.keys() | table_helpers.keys() | constants.keys()
    captured = rt._captured_result(node.body, forbidden)
    if captured is not None:
        concrete = rt._concrete(captured, {}, imports)
        if concrete is not None:
            return [rt._Case(concrete, node.body[-1], node)], True, "captured-result"
    if node.body and isinstance(node.body[0], ast.FunctionDef):
        return expand_local_assert_helpers(node, imports, helpers, table_helpers, constants, rt)
    if 1 <= len(node.body) <= rt.MAX_CASES and (multiple or len(node.body) > 1):
        assertions = [rt._checked(statement, {}, imports, helpers, set(), {}) for statement in node.body]
        if all(assertion is not None for assertion in assertions):
            grouped_helpers = any(getattr(assertion, "_requires_closed_helper", False) for assertion in assertions)
            return ([rt._Case(assertion, statement, node) for assertion, statement in zip(assertions, node.body)],
                    multiple or grouped_helpers,
                    "unittest" if multiple else "grouped-assert-helper" if grouped_helpers else "native")
        if multiple and not (len(node.body) == 1 and isinstance(node.body[0], ast.For)):
            return None
    blocks = rt._captured_blocks(node, imports, forbidden)
    if blocks is not None:
        return blocks, True, "string-block"
    block = rt.string_block(node)
    if block is not None:
        assertion, body = block
        concrete = rt._concrete(assertion, {}, imports)
        if concrete is None:
            return None
        return [rt._Case(concrete, node.body[-1], node, body)], True, "string-block"
    return _UNMATCHED


def resolve_parametrize_carrier(node, names, constants, used_constants, rt):
    """Resolve a single @pytest.mark.parametrize decorator carrier."""
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
    values = rt._table_source(decorator.args[1], constants, used_constants)
    bindings = rt._rows(values, columns, unpack=len(columns) != 1)
    return node.body, bindings, True, "parametrize"


def resolve_fixture_carrier(body, names, fixtures, tables, imports, table_helpers, scope, rt):
    """Resolve a single-parameter table-fixture or params-fixture test carrier."""
    if (len(names) == 1 and names[0] in tables and len(body) == 2
            and isinstance(body[0], ast.Assign) and len(body[0].targets) == 1
            and isinstance(body[0].targets[0], ast.Name) and isinstance(body[1], ast.For)):
        assignment, loop = body
        local_name = assignment.targets[0].id
        columns = rt._names(loop.target)
        iterator = loop.iter
        values = tables[names[0]]
        expected = assignment.value
        if (local_name in imports | scope | {"zip"} or not columns or len(columns) != 2 or loop.orelse
                or set(columns) & (imports | scope | {local_name, "zip"})
                or not isinstance(iterator, ast.Call) or dotted_name(iterator.func) != "zip"
                or iterator.keywords or [dotted_name(arg) for arg in iterator.args] != [names[0], local_name]
                or not isinstance(values, (ast.List, ast.Tuple)) or not isinstance(expected, (ast.List, ast.Tuple))
                or not 0 < len(values.elts) == len(expected.elts) <= rt.MAX_CASES
                or not all(isinstance(value, ast.Constant) and type(value.value) is str
                           for value in [*values.elts, *expected.elts])):
            return None
        bindings = [dict(zip(columns, pair)) for pair in zip(values.elts, expected.elts)]
        scope.update([local_name, *columns])
        return loop.body, bindings, True, "zip-fixture"
    if (len(names) == 1 and names[0] in tables and len(body) == 1 and isinstance(body[0], ast.For)
            and isinstance(body[0].iter, ast.Name) and body[0].iter.id == names[0]):
        loop = body[0]
        columns = rt._names(loop.target)
        if loop.orelse or not columns or names[0] in columns:
            return None
        bindings = rt._rows(tables[names[0]], columns, unpack=not isinstance(loop.target, ast.Name))
        scope.update(columns)
        return loop.body, bindings, True, "table-fixture-loop"
    if (len(names) == 1 and names[0] in tables and len(body) == 1 and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Call) and isinstance(body[0].value.func, ast.Name)
            and body[0].value.func.id in table_helpers and body[0].value.func.id not in scope):
        call = body[0].value
        if (len(call.args) != 1 or call.keywords or not isinstance(call.args[0], ast.Name)
                or call.args[0].id != names[0]):
            return None
        parameter, columns, assertion, unpack = table_helpers[call.func.id]
        bindings = rt._rows(tables[names[0]], columns, unpack=unpack)
        scope.update([parameter, *columns])
        return [assertion], bindings, True, "table-fixture-helper"
    if (len(names) == 1 and names[0] in fixtures
            and isinstance(fixtures[names[0]], (ast.List, ast.Tuple))
            and all(isinstance(value, (ast.Constant, ast.UnaryOp)) and rt._literal(value)
                    for value in fixtures[names[0]].elts)
            and body and not (isinstance(body[0], ast.Assign) and isinstance(body[0].value, ast.Name)
                              and body[0].value.id == names[0])):
        bindings = rt._rows(fixtures[names[0]], names, unpack=False)
        return body, bindings, True, "params-fixture"
    if (len(names) != 1 or names[0] not in fixtures or not 2 <= len(body) <= rt.MAX_CASES
            or not isinstance(body[0], ast.Assign) or len(body[0].targets) != 1
            or not isinstance(body[0].value, ast.Name) or body[0].value.id != names[0]):
        return None
    columns = rt._names(body[0].targets[0])
    if not columns or names[0] in columns:
        return None
    bindings = rt._rows(fixtures[names[0]], columns, unpack=not isinstance(body[0].targets[0], ast.Name))
    scope.update(columns)
    return body[1:], bindings, True, "params-fixture"


def resolve_loop_carrier(body, imports, table_helpers, constants, used_constants, scope, rt):
    """Resolve an inline literal-loop, table-helper-loop, or native test body."""
    if ((len(body) == 1 and isinstance(body[0], ast.For))
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
        columns = rt._names(loop.target)
        if loop.orelse or not columns:
            return None
        rows = rt._table_source(rows, constants, used_constants)
        bindings = rt._rows(rows, columns, unpack=not isinstance(loop.target, ast.Name))
        scope.update(columns)
        return loop.body, bindings, True, "literal-loop"
    if (len(body) == 1 and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Call)
            and isinstance(body[0].value.func, ast.Name) and body[0].value.func.id in table_helpers
            and body[0].value.func.id not in scope):
        call = body[0].value
        if len(call.args) != 1 or call.keywords:
            return None
        parameter, columns, assertion, unpack = table_helpers[call.func.id]
        values = rt._table_source(call.args[0], constants, used_constants)
        bindings = rt._rows(values, columns, unpack=unpack)
        scope.update([parameter, *columns])
        return [assertion], bindings, True, "table-helper-loop"
    return body, [{}], False, "native"


def resolve_test_carrier(node, names, fixtures, tables, imports, table_helpers, constants, used_constants, scope, *,
                         baseline, rt):
    """Dispatch decorator, fixture, loop, or baseline native test carriers."""
    if baseline:
        return None if (names or node.decorator_list) else (node.body, [{}], False, "native")
    if node.decorator_list:
        return resolve_parametrize_carrier(node, names, constants, used_constants, rt)
    if names:
        return resolve_fixture_carrier(node.body, names, fixtures, tables, imports, table_helpers, scope, rt)
    return resolve_loop_carrier(node.body, imports, table_helpers, constants, used_constants, scope, rt)


def inline_row_aliases(body, scope, imports, constants, rt):
    """Substitute fresh local row/call aliases into the final body statement.

    A fresh name for a row cell does not change its value or identity.
    Substitute aliases back to the original row names before _concrete counts
    uses, so two names for one mutable cell cannot evade its repeated-object
    guard. Calls, rebinding and unpacking stay outside this narrow carrier.
    """
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
            if ((not callee or callee.split(".")[0] not in imports - {"pytest"}) and not rt.derived_shape(statement.value)
                    or sum(isinstance(node, ast.Name) and node.id == name for node in ast.walk(checked_expression)) != 1
                    or any(isinstance(node, ast.Name) and node.id == name
                           for later in body[:-1] if later is not statement for node in ast.walk(later))):
                return None
        else:
            return None
        aliases[name] = rt._Substitute(aliases).visit(copy.deepcopy(statement.value))
        scope.add(name)
    return [rt._Substitute(aliases).visit(copy.deepcopy(body[-1]))]


def finalize_test_cases(node, body, bindings, table, form, scope, source_statement, imports, helpers, constants, rt):
    """Filter constant row guards and instantiate concrete _Case entries."""
    if bindings is None or len(body) != 1:
        return None
    if table and isinstance(body[0], ast.If):
        condition = body[0]
        if condition.orelse or len(condition.body) != 1:
            return None
        filtered = []
        for row in bindings:
            predicate = rt._Substitute(row).visit(copy.deepcopy(condition.test))
            value = rt.folded_expected(predicate, lambda _name: False)
            if not isinstance(value, ast.Constant) or type(value.value) is not bool:
                return None
            if value.value:
                filtered.append(row)
        if not filtered:
            # A collected consumer whose whole oracle is disabled cannot be
            # erased from the proof and replaced by another consumer's rows.
            return None
        bindings, body, form = filtered, [condition.body[0]], "filtered-" + form
    if (form == "native" and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Call)
            and isinstance(body[0].value.func, ast.Name) and body[0].value.func.id in helpers):
        table, form = True, "assert-helper"
    # Mutable module objects may be table containers, but must not be copied
    # into subject/expected expressions as though each reference allocated a
    # fresh object. Immutable constants still obey the repeated-binding guard.
    immutable = {name: value for name, value in constants.items() if rt._immutable_param(value)}
    free = {name: value for name, value in immutable.items() if name not in scope}
    assertions = [rt._checked(body[0], {**free, **row}, imports, helpers, scope, immutable)
                  for row in bindings]
    if any(assertion is None for assertion in assertions):
        return None
    return [rt._Case(assertion, source_statement, node) for assertion in assertions], table, form

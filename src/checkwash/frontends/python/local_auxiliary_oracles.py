"""Retain added local checks without crediting them as production coverage.

Only plain closed helpers called on immutable literal strings are supported.
Each complete local equality survives as an auxiliary unit, identified by its
full helper definition, literal call and expected value. Imported production
oracles must independently preserve all original coverage.
"""
import ast
import copy
import hashlib
from collections import Counter
from dataclasses import dataclass, replace

from checkwash.frontends.python.frontend import _Offsets, parse_python
from checkwash.frontends.python.oracle_blocks import IMPLICIT_ENTRY_NAMES, _args
from checkwash.frontends.python.oracle_purity import _BUILTINS, _pure_module
from checkwash.frontends.python.primitive_strings import primitive_string_result
from checkwash.ir.astutil import dotted_name, stable_dump


@dataclass
class LocalAuxiliaryOracle:
    owner: ast.FunctionDef
    source: ast.Assert
    helper: ast.FunctionDef
    assertion: ast.Assert

    @property
    def key(self):
        return stable_dump(ast.Module(body=[self.helper, self.assertion], type_ignores=[]))


def _binding_counts(tree):
    nodes = list(ast.walk(tree))
    counts = Counter(node.id for node in nodes if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load))
    counts.update(node.arg for node in nodes if isinstance(node, ast.arg))
    counts.update(node.name for node in nodes if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))
    counts.update(node.asname or node.name.split('.')[0] for node in nodes if isinstance(node, ast.alias))
    return counts


def _table_fixture(function):
    plain = copy.copy(function)
    plain.decorator_list = []
    if (_args(plain) != [] or len(function.decorator_list) != 1 or len(function.body) != 1
            or not isinstance(function.body[0], ast.Return)):
        return None
    decorator = function.decorator_list[0]
    if isinstance(decorator, ast.Call):
        if decorator.args or decorator.keywords:
            return None
        decorator = decorator.func
    rows = function.body[0].value
    if (dotted_name(decorator) != 'pytest.fixture' or not isinstance(rows, (ast.List, ast.Tuple))
            or not 1 <= len(rows.elts) <= 64
            or not all(isinstance(row, ast.Tuple) and row.elts and all(
                isinstance(cell, ast.Constant) and type(cell.value) is str for cell in row.elts) for row in rows.elts)):
        return None
    return rows


def _caller(function, fixtures, unavailable):
    names = _args(function)
    if names is None or not function.name.startswith('test') or len(function.body) != 1:
        return None
    statement = function.body[0]
    if not names:
        return (statement, [{}]) if isinstance(statement, ast.Assert) else None
    if (len(names) != 1 or names[0] not in fixtures or not isinstance(statement, ast.For)
            or statement.orelse or not isinstance(statement.iter, ast.Name) or statement.iter.id != names[0]
            or len(statement.body) != 1 or not isinstance(statement.body[0], ast.Assert)
            or not isinstance(statement.target, (ast.List, ast.Tuple))
            or not all(isinstance(item, ast.Name) for item in statement.target.elts)):
        return None
    columns = [item.id for item in statement.target.elts]
    if not columns or len(columns) != len(set(columns)) or set(columns) & (unavailable | set(names)):
        return None
    rows = fixtures[names[0]].elts
    if any(len(row.elts) != len(columns) for row in rows):
        return None
    return statement.body[0], [dict(zip(columns, row.elts)) for row in rows]


def _concrete_local(assertion, row, helpers, bindings):
    if not isinstance(assertion, ast.Assert) or assertion.msg is not None:
        return None
    compare = assertion.test
    if (not isinstance(compare, ast.Compare) or len(compare.ops) != 1 or not isinstance(compare.ops[0], ast.Eq)
            or not isinstance(compare.left, ast.Call) or not isinstance(compare.left.func, ast.Name)
            or compare.left.func.id not in helpers or compare.left.keywords):
        return None
    helper = helpers[compare.left.func.id]
    uses = Counter(node.id for node in ast.walk(assertion) if isinstance(node, ast.Name) and node.id in row)
    if any(count > 1 for count in uses.values()):
        return None

    class Cells(ast.NodeTransformer):
        def visit_Name(self, node):
            return copy.deepcopy(row.get(node.id, node))

    concrete = Cells().visit(copy.deepcopy(assertion))
    call = concrete.test.left
    if (not call.args or not all(isinstance(value, ast.Constant) and type(value.value) is str
                                for value in [*call.args, concrete.test.comparators[0]])):
        return None
    source = ast.unparse(helper).encode()
    if not _pure_module(source, helper.name) or not primitive_string_result(source, helper.name, call):
        return None
    authorities = {node.id for node in ast.walk(helper) if isinstance(node, ast.Name)
                   and isinstance(node.ctx, ast.Load) and node.id in _BUILTINS | {'ValueError'}}
    if any(bindings[name] for name in authorities):
        return None
    return helper, concrete


def extract_local_auxiliary_oracles(tree):
    helpers = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)
               and not node.name.startswith(('test', 'pytest_', '__')) and node.name not in IMPLICIT_ENTRY_NAMES
               and _args(node) is not None and any(isinstance(part, ast.Return) for part in ast.walk(node))}
    if not helpers:
        return []
    bindings = _binding_counts(tree)
    fixtures = {node.name: rows for node in tree.body if isinstance(node, ast.FunctionDef)
                and (rows := _table_fixture(node)) is not None}
    if fixtures and (bindings['pytest'] != 1 or not any(isinstance(node, ast.Import) and len(node.names) == 1
            and node.names[0].name == 'pytest' and node.names[0].asname is None for node in tree.body)):
        return []
    unavailable = set(helpers) | {node.asname or node.name.split('.')[0]
                                  for node in ast.walk(tree) if isinstance(node, ast.alias)}
    oracles, removed, used = [], set(), set()
    for function in tree.body:
        if not isinstance(function, ast.FunctionDef):
            continue
        caller = _caller(function, fixtures, unavailable)
        if caller is None:
            continue
        assertion, rows = caller
        concrete = [_concrete_local(assertion, row, helpers, bindings) for row in rows]
        if not concrete or any(item is None for item in concrete):
            continue
        if bindings[function.name] != 1:
            return []  # extracting an override must not revive an earlier dead test
        for helper, check in concrete:
            if bindings[helper.name] != 1:
                return []
            oracles.append(LocalAuxiliaryOracle(copy.deepcopy(function), copy.deepcopy(assertion),
                                               copy.deepcopy(helper), check))
            used.add(helper.name)
        removed.add(function)
        if len(oracles) > 64:
            return []
    if not oracles:
        return []
    retained = [node for node in tree.body if node not in removed
                and not (isinstance(node, ast.FunctionDef) and node.name in used)]
    if any(isinstance(node, ast.Name) and node.id in used for statement in retained for node in ast.walk(statement)):
        return []  # every use must be one of the preserved concrete local checks
    tree.body = retained
    return oracles


def retain_local_auxiliary_units(parsed, text, oracles):
    if not oracles:
        return parsed
    counts, definitions = Counter(), []
    for oracle in oracles:
        digest = hashlib.sha256(oracle.key.encode()).hexdigest()[:24]
        counts[digest] += 1
        name = f'test_local_auxiliary_{digest}_{counts[digest]}'
        rendered = ast.unparse(oracle.helper) + '\n' + ast.unparse(oracle.assertion)
        definitions.append(f'def {name}():\n' + '\n'.join('    ' + line for line in rendered.splitlines()))
    projected = parse_python('\n'.join(definitions).encode(), collect_tests=True)
    offsets, units = _Offsets(text), list(parsed.units)
    for unit, oracle in zip(projected.units, oracles):
        span = offsets.span(oracle.owner)
        assertions = [replace(assertion, span=offsets.span(oracle.source)) for assertion in unit.side.assertions]
        units.append(replace(unit, span=span, side=replace(unit.side, span=span, assertions=assertions)))
    return replace(parsed, units=units)

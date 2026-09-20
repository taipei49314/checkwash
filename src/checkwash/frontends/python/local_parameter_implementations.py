"""Complete literal parameter rows redirected into a closed numeric helper.

This adds existing subject-installation evidence only. It grants no oracle
alignment or equivalence to the local implementation and executes no
repository function. Forwarders and opaque helper calls remain unknown.
"""
from __future__ import annotations

import ast
import copy

from .callable_fixture_expectations import _number, _parameters, _tree
from .expected_constants import folded_expected
from .frontend import _Offsets, normalize_source
from .oracle_blocks import IMPLICIT_ENTRY_NAMES
from .oracle_purity import primitive_literal_result, pure_imported_calls
from .snapshot_context import inert_test_execution_context
from checkwash.ir.astutil import dotted_name, stable_dump
from checkwash.pyenv import known_baseline

_RESERVED = IMPLICIT_ENTRY_NAMES | {'pytest', 'pytestmark', 'pytest_plugins', 'request', 'round'}


def _module(source, after):
    tree = _tree(source)
    if tree is None:
        return None
    imported, functions, occupied, pytest = None, [], set(), False
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and type(node.value.value) is str:
            continue
        if (after and isinstance(node, ast.Import) and not functions and not pytest and len(node.names) == 1
                and node.names[0].name == 'pytest' and node.names[0].asname is None):
            name, pytest = 'pytest', True
        elif (isinstance(node, ast.ImportFrom) and not functions and imported is None and not node.level
                and node.module and len(node.names) == 1 and node.names[0].name != '*'):
            imported = node
            name = node.names[0].asname or node.names[0].name
        elif isinstance(node, ast.FunctionDef) and _parameters(node) is not None:
            name = node.name
            functions.append(node)
        else:
            return None
        if (name in occupied or name.startswith(('__', 'pytest_'))
                or name in _RESERVED and not (name == 'pytest' and isinstance(node, ast.Import))):
            return None
        occupied.add(name)
    if imported is None or not functions or (after and (not pytest or len(functions) != 2)):
        return None
    provider = imported.names[0].asname or imported.names[0].name
    if provider.startswith('test'):
        return None
    return imported, provider, functions, occupied


def _expression(node, names):
    if _number(node) or isinstance(node, ast.Name) and node.id in names:
        return True
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        return _expression(node.operand, names)
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod)):
        return _expression(node.left, names) and _expression(node.right, names)
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'round'
            and not node.keywords and len(node.args) == 1 and _expression(node.args[0], names))


def _helper(helper, occupied):
    names = _parameters(helper)
    if (helper.name.startswith('test') or helper.decorator_list or len(names) != 2
            or set(names) & (occupied | _RESERVED) or not 1 <= len(helper.body) <= 2
            or not isinstance(helper.body[-1], ast.Return) or not _expression(helper.body[-1].value, set(names))):
        return None
    if len(helper.body) == 2:
        guard = helper.body[0]
        if (not isinstance(guard, ast.If) or guard.orelse or len(guard.body) != 1
                or not isinstance(guard.body[0], ast.Return) or not _expression(guard.body[0].value, set(names))
                or not isinstance(guard.test, ast.Compare) or len(guard.test.ops) != 1
                or not isinstance(guard.test.ops[0], (ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE))
                or not _expression(guard.test.left, set(names))
                or not _expression(guard.test.comparators[0], set(names))):
            return None
    return names


def _value(node, bindings):
    class Resolve(ast.NodeTransformer):
        def visit_Name(self, item):
            return copy.deepcopy(bindings.get(item.id, item))

        def visit_Call(self, item):
            argument = folded_expected(self.visit(copy.deepcopy(item.args[0])), lambda _: False)
            if argument is None or not _number(argument):
                raise ValueError('unproved numeric round operand')
            return ast.Constant(value=round(ast.literal_eval(argument)))

    return folded_expected(Resolve().visit(copy.deepcopy(node)), lambda _: False)


def _returns(helper, names, values):
    bindings = dict(zip(names, values))
    expression = helper.body[-1].value
    if len(helper.body) == 2:
        guard = helper.body[0]
        condition = _value(guard.test, bindings)
        if not isinstance(condition, ast.Constant) or type(condition.value) is not bool:
            return False
        if condition.value:
            expression = guard.body[0].value
    answer = _value(expression, bindings)
    return answer is not None and _number(answer)


def _rows(old, new):
    if stable_dump(old[0]) != stable_dump(new[0]) or not 1 <= len(old[2]) <= 64:
        return None
    previous = []
    for function in old[2]:
        if (not function.name.startswith('test') or function.decorator_list or _parameters(function) != []
                or len(function.body) != 1 or not isinstance(function.body[0], ast.Assert)
                or function.body[0].msg is not None):
            return None
        comparison = function.body[0].test
        if (not isinstance(comparison, ast.Compare) or len(comparison.ops) != 1 or not isinstance(comparison.ops[0], ast.Eq)
                or not _number(comparison.comparators[0])):
            return None
        call = comparison.left
        if (not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name) or call.func.id != old[1]
                or call.keywords or len(call.args) != 2 or not all(_number(arg) for arg in call.args)):
            return None
        previous.append((call, comparison.comparators[0]))
    helper, test = new[2]
    names = _helper(helper, new[3])
    arguments = _parameters(test)
    if (names is None or not test.name.startswith('test') or len(arguments) != 3
            or set(arguments) & (new[3] | _RESERVED) or len(test.decorator_list) != 1
            or len(test.body) != 1 or not isinstance(test.body[0], ast.Assert) or test.body[0].msg is not None):
        return None
    decorator = test.decorator_list[0]
    if (not isinstance(decorator, ast.Call) or dotted_name(decorator.func) != 'pytest.mark.parametrize'
            or decorator.keywords or len(decorator.args) != 2
            or not isinstance(decorator.args[0], ast.Constant) or type(decorator.args[0].value) is not str
            or [name.strip() for name in decorator.args[0].value.split(',')] != arguments
            or not isinstance(decorator.args[1], (ast.List, ast.Tuple)) or len(decorator.args[1].elts) != len(previous)):
        return None
    comparison = test.body[0].test
    if (not isinstance(comparison, ast.Compare) or len(comparison.ops) != 1 or not isinstance(comparison.ops[0], ast.Eq)
            or not isinstance(comparison.comparators[0], ast.Name) or comparison.comparators[0].id != arguments[2]):
        return None
    called = comparison.left
    if (not isinstance(called, ast.Call) or not isinstance(called.func, ast.Name) or called.func.id != helper.name
            or called.keywords or len(called.args) != 2
            or any(not isinstance(arg, ast.Name) or arg.id != name for arg, name in zip(called.args, arguments[:2]))):
        return None
    for (original, expected), row in zip(previous, decorator.args[1].elts):
        if (not isinstance(row, (ast.List, ast.Tuple)) or len(row.elts) != 3 or not all(_number(value) for value in row.elts)
                or [stable_dump(value) for value in row.elts] != [stable_dump(value) for value in [*original.args, expected]]
                or not _returns(helper, names, row.elts[:2])):
            return None
    return test, [row[0] for row in previous]


def local_parameter_implementation_events(ir, changes, *, root_reader=None, root_searcher=None):
    from .table_oracles import _context_snapshots, _pytest_unshadowed
    if root_reader is None or root_searcher is None:
        return []
    changes = tuple(changes)
    changed = [change for change in changes if change.before != change.after]
    if len(changed) != 1:
        return []
    change = changed[0]
    if (not change.before or not change.after or change.status != 'modified' or change.old_path is not None
            or b'parametrize' not in change.after):
        return []
    file = next((file for file in ir.files if file.path == change.path and file.role == 'test' and file.parse_ok), None)
    if file is None:
        return []
    try:
        old, new = _module(change.before, False), _module(change.after, True)
        if old is None or new is None:
            return []
        matched = _rows(old, new)
        if matched is None:
            return []
        test, calls = matched
        target = old[0].module + '.' + old[0].names[0].name
        if target.split('.')[0] in known_baseline() | set(ir.globals.third_party_roots):
            return []
        if not any(unit.qualname == test.name and unit.after is not None for unit in file.units):
            return []
        for source, (read, search) in zip((change.before, change.after), _context_snapshots(
                change.path, change.before, change.after, changes, root_reader, root_searcher)):
            if (not inert_test_execution_context(change.path, read, search) or not _pytest_unshadowed(change.path, read)
                    or not pure_imported_calls(source, calls, path=change.path, read=read, result_proof=primitive_literal_result)):
                return []
        offsets = _Offsets(normalize_source(change.after))
        statement = test.body[0]
        return [(change.path, test.name, target, offsets.seg(statement), offsets.span(statement))]
    except (SyntaxError, ValueError, TypeError, AttributeError, RecursionError, MemoryError, ArithmeticError):
        return []

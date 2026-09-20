"""Closed numeric fixture callbacks used as higher-order call expectations.

This adds provenance only: a concrete production factory invocation keeps all
of its arguments while an independent literal answer becomes a different
closed fixture result. Neither repository functions nor callbacks are run.
"""
from __future__ import annotations

import ast
import copy
import math

from checkwash.frontends.python.expected_constants import folded_expected
from checkwash.frontends.python.frontend import _Offsets, normalize_source
from checkwash.frontends.python.oracle_purity import pure_imported_calls
from checkwash.frontends.python.snapshot_context import inert_test_execution_context
from checkwash.ir.astutil import dotted_name, stable_dump


def _parameters(node):
    args = node.args
    if (args.posonlyargs or args.kwonlyargs or args.vararg or args.kwarg or args.defaults
            or any(arg.annotation for arg in args.args)
            or isinstance(node, ast.FunctionDef) and (node.returns or getattr(node, 'type_params', ()))):
        return None
    names = [arg.arg for arg in args.args]
    return names if len(names) == len(set(names)) and len(names) <= 4 else None


def _number(node):
    if any(isinstance(item, (ast.Name, ast.Call)) for item in ast.walk(node)):
        return False
    try:
        value = ast.literal_eval(node)
        return (type(value) is int and value.bit_length() <= 256
                or type(value) is float and math.isfinite(value))
    except (ValueError, TypeError, SyntaxError, RecursionError, MemoryError):
        return False


def _numeric(node, names):
    if _number(node):
        return True
    if isinstance(node, ast.Name):
        return node.id in names
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        return _numeric(node.operand, names)
    return (isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod))
            and _numeric(node.left, names) and _numeric(node.right, names))


def _tree(source):
    if not isinstance(source, bytes) or len(source) > 65_536:
        return None
    tree = ast.parse(normalize_source(source))
    return tree if sum(1 for _ in ast.walk(tree)) <= 4096 else None


def _module(source, after, *, fixture_factory=False):
    tree = _tree(source)
    if tree is None:
        return None
    occupied, imports, functions, pytest = set(), {}, {}, False
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and type(node.value.value) is str:
            continue
        if isinstance(node, ast.ImportFrom) and not functions and node.module and not node.level:
            for alias in node.names:
                name = alias.asname or alias.name
                if name in occupied or alias.name == '*' or name == 'pytest' or name.startswith('__'):
                    return None
                imports[name] = (node.module, alias.name)
                occupied.add(name)
        elif (isinstance(node, ast.Import) and not functions and len(node.names) == 1
              and node.names[0].name == 'pytest' and node.names[0].asname is None and 'pytest' not in occupied):
            pytest = True
            occupied.add('pytest')
        elif isinstance(node, ast.FunctionDef) and node.name not in occupied:
            occupied.add(node.name)
            functions[node.name] = node
        else:
            return None
    tests = [node for node in functions.values() if node.name.startswith('test')]
    if len(imports) != 1 or len(tests) != 1 or len(functions) != (2 if after else 1):
        return None
    test = tests[0]
    parameters = _parameters(test)
    if test.decorator_list or parameters is None or not after and parameters:
        return None
    fixture = None
    if after:
        if not pytest or len(parameters) != 1 or parameters[0] in imports:
            return None
        fixture = functions.get(parameters[0])
        if (fixture is None or fixture.name.startswith(('test', 'pytest_', '__')) or _parameters(fixture) != []
                or len(fixture.decorator_list) != 1):
            return None
        decorator = fixture.decorator_list[0]
        if isinstance(decorator, ast.Call) and not decorator.args and not decorator.keywords:
            decorator = decorator.func
        if dotted_name(decorator) != 'pytest.fixture':
            return None
        if fixture_factory:
            if (len(fixture.body) != 2 or not isinstance(fixture.body[0], ast.FunctionDef)
                    or not isinstance(fixture.body[1], ast.Return) or not isinstance(fixture.body[1].value, ast.Name)
                    or fixture.body[1].value.id != fixture.body[0].name):
                return None
            factory = fixture.body[0]
            captured = _parameters(factory)
            if (factory.decorator_list or captured is None or not captured or len(factory.body) != 1
                    or not isinstance(factory.body[0], ast.Return) or not isinstance(factory.body[0].value, ast.Lambda)):
                return None
            callback = factory.body[0].value
        else:
            if (len(fixture.body) != 1 or not isinstance(fixture.body[0], ast.Return)
                    or not isinstance(fixture.body[0].value, ast.Lambda)):
                return None
            callback, captured = fixture.body[0].value, []
        callback_parameters = _parameters(callback)
        if (callback_parameters is None or not callback_parameters
                or not _numeric(callback.body, set(captured) | set(callback_parameters))):
            return None
    return imports, test, fixture


def _factory_result(source, target, call, inner_arity):
    """A plain production factory returns its one closed numeric function."""
    tree = _tree(source)
    if tree is None:
        return False
    body = [node for node in tree.body if not (isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant) and type(node.value.value) is str)]
    if len(body) != 1 or not isinstance(body[0], ast.FunctionDef) or body[0].name != target:
        return False
    factory = body[0]
    parameters = _parameters(factory)
    if (parameters is None or factory.decorator_list or call.keywords or len(call.args) != len(parameters)
            or not all(_number(arg) for arg in call.args) or len(factory.body) != 2):
        return False
    nested, returned = factory.body
    if (not isinstance(nested, ast.FunctionDef) or nested.decorator_list
            or not isinstance(returned, ast.Return) or not isinstance(returned.value, ast.Name)
            or returned.value.id != nested.name or nested.name in parameters or len(nested.body) != 1
            or not isinstance(nested.body[0], ast.Return)):
        return False
    inner = _parameters(nested)
    return (inner is not None and len(inner) == inner_arity
            and _numeric(nested.body[0].value, set(parameters) | set(inner)))


def callable_fixture_events(path, before, after, reader):
    """Return additive ordinary expectation-provenance records, if closed."""
    from .table_oracles import _Substitute, _pytest_unshadowed
    if (not before or not after or b'lambda' not in after or b'fixture' not in after
            or any(p != path and old != new for p, (old, new) in reader.raw.items())):
        return []
    try:
        old, new = _module(before, False), _module(after, True)
        if old is None or new is None or old[0] != new[0] or old[1].name != new[1].name:
            return []
        if len(old[1].body) != 1 or len(new[1].body) not in (1, 2):
            return []
        previous, current = old[1].body[0], new[1].body[-1]
        if any(not isinstance(node, ast.Assert) or node.msg is not None
               or not isinstance(node.test, ast.Compare) or len(node.test.ops) != 1
               or not isinstance(node.test.ops[0], ast.Eq) for node in (previous, current)):
            return []
        original = previous.test.left
        if (not isinstance(original, ast.Call) or original.keywords or not all(_number(arg) for arg in original.args)
                or not isinstance(original.func, ast.Call) or original.func.keywords
                or not isinstance(original.func.func, ast.Name) or original.func.func.id not in old[0]
                or not all(_number(arg) for arg in original.func.args) or not _number(previous.test.comparators[0])):
            return []
        local = {}
        if len(new[1].body) == 2:
            assignment = new[1].body[0]
            if (not isinstance(assignment, ast.Assign) or len(assignment.targets) != 1
                    or not isinstance(assignment.targets[0], ast.Name)
                    or assignment.targets[0].id in set(new[0]) | {new[1].name, new[2].name, 'pytest'}
                    or stable_dump(assignment.value) != stable_dump(original.func)):
                return []
            local[assignment.targets[0].id] = assignment.value
        comparison = _Substitute(local).visit(copy.deepcopy(current.test))
        left, right = comparison.left, comparison.comparators[0]
        def fixture_call(node):
            return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == new[2].name
        if fixture_call(left):
            left, right = right, left
        if stable_dump(left) != stable_dump(original) or not fixture_call(right) or right.keywords:
            return []
        callback = new[2].body[0].value
        parameters = _parameters(callback)
        if len(right.args) != len(parameters) or not all(_number(arg) for arg in right.args):
            return []
        expression = _Substitute(dict(zip(parameters, right.args))).visit(copy.deepcopy(callback.body))
        expected = folded_expected(expression, lambda _: False)
        if expected is None or not _number(expected) or stable_dump(expected) == stable_dump(previous.test.comparators[0]):
            return []
        for side, source in enumerate((before, after)):
            read = lambda candidate, side=side: reader.source(candidate, side, authority=True)
            search = lambda needles, side=side: reader.search(needles, side)
            if (not inert_test_execution_context(path, read, search) or not _pytest_unshadowed(path, read)
                    or not pure_imported_calls(source, [original.func], path=path, read=read,
                        result_proof=lambda data, target, call: _factory_result(data, target, call, len(original.args)))):
                return []
        offsets = [_Offsets(normalize_source(source)) for source in (before, after)]
        return [(old[1].name, offsets[0].seg(previous), offsets[0].span(previous),
                 offsets[1].seg(current), offsets[1].span(current), ast.unparse(original), 'Eq',
                 ast.unparse(previous.test.comparators[0]), ast.unparse(expected))]
    except (SyntaxError, ValueError, TypeError, AttributeError, RecursionError, MemoryError):
        return []

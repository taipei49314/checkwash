"""Resolve one finite index parameter against a literal expected-value fixture."""

import ast
import copy
import math


def _plain_args(function):
    args = function.args
    if (function.returns or getattr(function, "type_params", ()) or args.posonlyargs or args.kwonlyargs
            or args.defaults or args.vararg or args.kwarg or any(arg.annotation for arg in args.args)):
        return None
    return [arg.arg for arg in args.args]


def _scalar(node):
    try:
        value = ast.literal_eval(node)
        return (type(value) in (str, bytes, int, bool, type(None))
                or type(value) is float and math.isfinite(value))
    except (ValueError, TypeError, RecursionError, MemoryError):
        return False


def expand_indexed_fixture_tables(tree):
    """Return expanded test names; callers must prove source purity and pytest."""
    if not any(isinstance(node, ast.Import) and len(node.names) == 1
               and node.names[0].name == "pytest" and node.names[0].asname is None for node in tree.body):
        return set()
    for node in ast.walk(tree):
        if ((isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)) and node.id == "range")
                or (isinstance(node, ast.arg) and node.arg == "range")
                or (isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name == "range")
                or (isinstance(node, ast.alias) and (node.asname or node.name.split('.')[0]) == "range")):
            return set()
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    if len({function.name for function in functions}) != len(functions):
        return set()
    fixtures = {}
    for function in functions:
        if (_plain_args(function) == [] and not function.name.startswith("test")
                and len(function.decorator_list) == 1 and ast.unparse(function.decorator_list[0]) == "pytest.fixture"
                and len(function.body) == 1 and isinstance(function.body[0], ast.Return)
                and isinstance(function.body[0].value, (ast.List, ast.Tuple))
                and 0 < len(function.body[0].value.elts) <= 64
                and all(_scalar(value) for value in function.body[0].value.elts)):
            fixtures[function.name] = function
    expanded, consumed = set(), set()
    for function in functions:
        names = _plain_args(function)
        if (not function.name.startswith("test") or names is None or len(names) != 2
                or len(function.decorator_list) != 1 or len(function.body) != 1
                or not isinstance(function.body[0], ast.Assert)):
            continue
        decorator = function.decorator_list[0]
        if (not isinstance(decorator, ast.Call) or ast.unparse(decorator.func) != "pytest.mark.parametrize"
                or len(decorator.args) != 2 or decorator.keywords
                or not isinstance(decorator.args[0], ast.Constant) or type(decorator.args[0].value) is not str):
            continue
        index_name = decorator.args[0].value.strip()
        if index_name not in names:
            continue
        fixture_name = next(name for name in names if name != index_name)
        fixture = fixtures.get(fixture_name)
        iterator = decorator.args[1]
        if (fixture is None or fixture_name in consumed or not isinstance(iterator, ast.Call)
                or not isinstance(iterator.func, ast.Name) or iterator.func.id != "range"
                or iterator.keywords or not 1 <= len(iterator.args) <= 3
                or any(not isinstance(arg, ast.Constant) or type(arg.value) is not int for arg in iterator.args)):
            continue
        try:
            indices = range(*(arg.value for arg in iterator.args))
            if not 0 < len(indices) <= 64 or any(index < 0 or index >= len(fixture.body[0].value.elts) for index in indices):
                continue
        except (ValueError, OverflowError):
            continue
        assertion = function.body[0]
        comparison = assertion.test
        if (assertion.msg is not None or not isinstance(comparison, ast.Compare) or len(comparison.ops) != 1
                or not isinstance(comparison.ops[0], (ast.Eq, ast.Is))):
            continue
        expected = comparison.comparators[0]
        if (not isinstance(expected, ast.Subscript) or not isinstance(expected.value, ast.Name)
                or expected.value.id != fixture_name or not isinstance(expected.slice, ast.Name)
                or expected.slice.id != index_name):
            continue
        fixture_references = [node for node in ast.walk(tree) if isinstance(node, ast.Name) and node.id == fixture_name]
        fixture_parameters = [node for node in ast.walk(tree) if isinstance(node, ast.arg) and node.arg == fixture_name]
        if fixture_references != [expected.value] or len(fixture_parameters) != 1:
            continue
        if any(isinstance(node, ast.alias) and (node.asname or node.name.split('.')[0]) == fixture_name for node in ast.walk(tree)):
            continue
        expected_name = "_checkwash_indexed_expected"
        if any((isinstance(node, ast.Name) and node.id == expected_name)
               or (isinstance(node, ast.arg) and node.arg == expected_name) for node in ast.walk(tree)):
            continue
        values = fixture.body[0].value.elts
        rows = [ast.Tuple(elts=[ast.Constant(value=index), copy.deepcopy(values[index])], ctx=ast.Load()) for index in indices]
        decorator.args = [ast.Constant(value=index_name + "," + expected_name), ast.List(elts=rows, ctx=ast.Load())]
        function.args.args = [arg for arg in function.args.args if arg.arg != fixture_name]
        function.args.args.append(ast.arg(arg=expected_name))
        comparison.comparators[0] = ast.Name(id=expected_name, ctx=ast.Load())
        expanded.add(function.name)
        consumed.add(fixture_name)
    tree.body = [node for node in tree.body if not isinstance(node, ast.FunctionDef) or node.name not in consumed]
    return expanded

"""Closed scalar all-comparisons and literal dictionary fixture loops.

Every row becomes a real comparison; no repository expression is evaluated.
The caller retains the original ordered inputs and proves pure production
and closed startup context before crediting this carrier transformation.
"""
import ast
import copy
from collections import Counter

from checkwash.frontends.python.expected_constants import folded_expected


def _plain(function, parameters):
    args = function.args
    return (not function.decorator_list and not function.returns and not getattr(function, 'type_params', ())
            and not args.posonlyargs and not args.kwonlyargs and not args.defaults and not args.vararg
            and not args.kwarg and not any(arg.annotation for arg in args.args)
            and [arg.arg for arg in args.args] == parameters)


def _scalar(node):
    return isinstance(node, ast.Constant) and type(node.value) in (type(None), bool, int, float, str, bytes)


class _Bind(ast.NodeTransformer):
    def __init__(self, values):
        self.values = values

    def visit_Name(self, node):
        return copy.deepcopy(self.values.get(node.id, node))


def _all_rows(function):
    if not _plain(function, []):
        return None
    body, rows_name, rows = function.body, None, None
    if len(body) == 2 and isinstance(body[0], ast.Assign) and len(body[0].targets) == 1:
        assignment = body[0]
        if not isinstance(assignment.targets[0], ast.Name):
            return None
        rows_name, rows = assignment.targets[0].id, assignment.value
        body = body[1:]
    if len(body) != 1 or not isinstance(body[0], ast.Assert) or body[0].msg is not None:
        return None
    statement, call = body[0], body[0].test
    if (not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name) or call.func.id != 'all'
            or call.keywords or len(call.args) != 1 or not isinstance(call.args[0], ast.GeneratorExp)):
        return None
    generator = call.args[0]
    if len(generator.generators) != 1:
        return None
    loop, comparison = generator.generators[0], generator.elt
    if (loop.is_async or loop.ifs or not isinstance(loop.target, ast.Name)
            or loop.target.id in {'all', rows_name} or not isinstance(comparison, ast.Compare)
            or len(comparison.ops) != 1 or not isinstance(comparison.ops[0], ast.Eq)
            or not isinstance(comparison.left, ast.Call)):
        return None
    if rows_name is not None:
        if (not isinstance(loop.iter, ast.Name) or loop.iter.id != rows_name
                or sum(isinstance(node, ast.Name) and node.id == rows_name for node in ast.walk(function)) != 2):
            return None
    else:
        rows = loop.iter
    if not isinstance(rows, (ast.List, ast.Tuple)) or not 1 <= len(rows.elts) <= 64 or not all(map(_scalar, rows.elts)):
        return None
    result = []
    for value in rows.elts:
        concrete = _Bind({loop.target.id: value}).visit(copy.deepcopy(comparison))
        expected = folded_expected(concrete.comparators[0], lambda _: False)
        if expected is None or not _scalar(expected):
            return None
        concrete.comparators[0] = expected
        result.append(ast.copy_location(ast.Assert(test=concrete, msg=None), statement))
    return result


def expand_literal_iteration_oracles(tree):
    nodes = list(ast.walk(tree))
    bound = Counter(node.id for node in nodes if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load))
    bound.update(node.name for node in nodes if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)))
    bound.update(node.asname or node.name.split('.')[0] for node in nodes if isinstance(node, ast.alias))
    definitions = bound.copy()
    bound.update(node.arg for node in nodes if isinstance(node, ast.arg))
    imported = {alias.asname or alias.name for node in tree.body if isinstance(node, ast.ImportFrom) for alias in node.names}
    expanded = set()
    if not bound['all']:
        for function in tree.body:
            if isinstance(function, ast.FunctionDef) and function.name.startswith('test'):
                rows = _all_rows(function)
                if rows is not None:
                    # Comprehension targets cannot replace the called import.
                    if any(not isinstance(row.test.left.func, ast.Name) or row.test.left.func.id not in imported for row in rows):
                        continue
                    function.body = rows
                    expanded.add(function.name)
    # Dict fixtures use Python insertion order. Duplicate/equal keys would
    # silently overwrite a row; decline them rather than invent coverage.
    if (bound['pytest'] != 1 or not any(isinstance(node, ast.Import) and len(node.names) == 1
            and node.names[0].name == 'pytest' and node.names[0].asname is None for node in tree.body)):
        return expanded
    fixtures = {}
    for function in tree.body:
        if not isinstance(function, ast.FunctionDef) or definitions[function.name] != 1:
            continue
        plain = copy.copy(function)
        plain.decorator_list = []
        if (not _plain(plain, []) or len(function.decorator_list) != 1
                or ast.unparse(function.decorator_list[0]) not in {'pytest.fixture', 'pytest.fixture()'}
                or len(function.body) != 1 or not isinstance(function.body[0], ast.Return)):
            continue
        value = function.body[0].value
        if (not isinstance(value, ast.Dict) or not 1 <= len(value.keys) <= 64
                or not all(_scalar(item) for item in [*value.keys, *value.values])):
            continue
        keys = [key.value for key in value.keys]
        if len(set(keys)) != len(keys):
            continue
        fixtures[function.name] = value
    replacements, used = {}, set()
    for function in tree.body:
        if not isinstance(function, ast.FunctionDef) or function.name in fixtures:
            continue
        names = [arg.arg for arg in function.args.args]
        selected = set(names) & fixtures.keys()
        if not selected:
            continue
        if len(selected) != 1 or len(names) != 1 or not function.name.startswith('test') or not _plain(function, names):
            return None
        fixture = names[0]
        body = function.body
        if len(body) == 2 and isinstance(body[0], ast.Assign) and len(body[0].targets) == 1:
            assignment = body[0]
            if (not isinstance(assignment.targets[0], ast.Name)
                    or assignment.targets[0].id in imported | {fixture, 'pytest'}
                    or folded_expected(assignment.value, lambda _: False) is None
                    or sum(isinstance(node, ast.Name) and node.id == assignment.targets[0].id
                           for node in ast.walk(function)) != 1):
                return None
            body = body[1:]
        if len(body) != 1 or not isinstance(body[0], ast.For):
            return None
        loop = body[0]
        if (loop.orelse or len(loop.body) != 1 or not isinstance(loop.body[0], ast.Assert)
                or not isinstance(loop.target, (ast.Tuple, ast.List)) or len(loop.target.elts) != 2
                or not all(isinstance(item, ast.Name) for item in loop.target.elts)
                or len({item.id for item in loop.target.elts}) != 2
                or {item.id for item in loop.target.elts} & (imported | {fixture, 'pytest'})
                or not isinstance(loop.iter, ast.Call) or loop.iter.args or loop.iter.keywords
                or ast.unparse(loop.iter.func) != fixture + '.items'):
            return None
        value = fixtures[fixture]
        copied = copy.deepcopy(function)
        copied.args.args = []
        copied.body = [copy.deepcopy(loop)]
        copied.body[0].iter = ast.copy_location(ast.List(elts=[ast.Tuple(elts=[copy.deepcopy(key), copy.deepcopy(val)], ctx=ast.Load())
            for key, val in zip(value.keys, value.values)], ctx=ast.Load()), loop.iter)
        if any(isinstance(node, ast.Name) and node.id in fixtures for node in ast.walk(copied)):
            return None
        replacements[function] = copied
        used.add(fixture)
    if not fixtures:
        return expanded
    remaining = [replacements.get(node, node) for node in tree.body if not isinstance(node, ast.FunctionDef) or node.name not in fixtures]
    if used != fixtures.keys() or any(isinstance(node, ast.Name) and node.id in fixtures for parent in remaining for node in ast.walk(parent)):
        return None
    tree.body = remaining
    expanded.update(function.name for function in replacements)
    return expanded

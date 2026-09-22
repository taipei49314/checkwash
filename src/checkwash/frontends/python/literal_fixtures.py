"""Fully accounted default-scope literal fixture consumers."""
import ast
import copy
from collections import Counter

from checkwash.frontends.python.expected_constants import folded_expected
from checkwash.frontends.python.table_factories import _immutable


def _arguments(node):
    args = node.args
    if (node.returns or getattr(node, 'type_params', ()) or args.posonlyargs or args.kwonlyargs
            or args.defaults or args.vararg or args.kwarg or any(arg.annotation for arg in args.args)):
        return None
    return [arg.arg for arg in args.args]


def _literal(node):
    if any(not isinstance(item, (ast.Constant, ast.List, ast.Tuple, ast.UnaryOp, ast.UAdd, ast.USub, ast.Load))
           for item in ast.walk(node)):
        return None
    return folded_expected(node, lambda _: False)


class _Values(ast.NodeTransformer):
    def __init__(self, values):
        self.values = values

    def visit_Name(self, node):
        return copy.deepcopy(self.values.get(node.id, node))

    def visit_Call(self, node):
        node = self.generic_visit(node)
        if (isinstance(node.func, ast.Attribute) and node.func.attr == 'replace'
                and isinstance(node.func.value, ast.Constant) and type(node.func.value.value) is str
                and len(node.func.value.value) <= 4096
                and len(node.args) == 2 and not node.keywords
                and all(isinstance(arg, ast.Constant) and type(arg.value) is str and len(arg.value) <= 4096 for arg in node.args)):
            original, old, new = node.func.value.value, node.args[0].value, node.args[1].value
            if len(original) + original.count(old) * (len(new) - len(old)) > 4096:
                return node
            value = node.func.value.value.replace(node.args[0].value, node.args[1].value)
            if len(value) <= 4096:
                return ast.copy_location(ast.Constant(value=value), node)
        return node


def expand_literal_fixtures(tree):
    nodes = list(ast.walk(tree))
    bindings = Counter(node.name for node in nodes if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))
    bindings.update(node.id for node in nodes if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load))
    bindings.update(node.asname or node.name.split('.')[0] for node in nodes if isinstance(node, ast.alias))
    if (bindings['pytest'] != 1 or not any(isinstance(node, ast.Import) and len(node.names) == 1
            and node.names[0].name == 'pytest' and node.names[0].asname is None for node in tree.body)
            or any(isinstance(node, ast.arg) and node.arg == 'pytest' for node in nodes)
            or any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                   and node.func.id in {'eval', 'exec', 'globals', 'locals', 'vars', 'getattr', 'setattr', 'delattr'}
                   for node in nodes)):
        return set()
    fixtures = {}
    for function in tree.body:
        if (not isinstance(function, ast.FunctionDef) or bindings[function.name] != 1
                or len(function.decorator_list) != 1 or len(function.body) != 1
                or not isinstance(function.body[0], ast.Return)):
            continue
        decorator, args = function.decorator_list[0], _arguments(function)
        params = None
        if isinstance(decorator, ast.Call):
            if decorator.args:
                continue
            if decorator.keywords:
                if len(decorator.keywords) != 1 or decorator.keywords[0].arg != 'params':
                    continue
                params = _literal(decorator.keywords[0].value)
                if (not isinstance(params, (ast.List, ast.Tuple)) or not 1 <= len(params.elts) <= 64
                        or not all(isinstance(row, (ast.Constant, ast.UnaryOp)) and _immutable(row) for row in params.elts)):
                    continue
            decorator = decorator.func
        if ast.unparse(decorator) != 'pytest.fixture':
            continue
        if params is None and args == []:
            value = _literal(function.body[0].value)
            if value is not None:
                fixtures[function.name] = (function, False, [value])
        elif params is not None and args == ['request'] and ast.unparse(function.body[0].value) == 'request.param':
            fixtures[function.name] = (function, True, params.elts)
    if not fixtures or all(param for _, param, _ in fixtures.values()):
        return set()
    replacements, allowed_loads, allowed_args, used = {}, set(), set(), set()
    existing_names = {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
    expanded = set()
    for function in tree.body:
        if not isinstance(function, ast.FunctionDef) or function.name in fixtures:
            continue
        args = _arguments(function)
        if args is None or not set(args) & fixtures.keys():
            continue
        if (not function.name.startswith('test') or function.decorator_list or set(args) - fixtures.keys()
                or len(args) != len(set(args))
                or len(function.body) != 1 or not isinstance(function.body[0], ast.Assert) or function.body[0].msg is not None
                or any(isinstance(node, (ast.Lambda, ast.GeneratorExp, ast.ListComp, ast.SetComp, ast.DictComp, ast.NamedExpr))
                       for node in ast.walk(function.body[0]))):
            return set()
        loads = [node for node in ast.walk(function.body[0]) if isinstance(node, ast.Name) and node.id in fixtures]
        if Counter(node.id for node in loads) != Counter(args):
            return set()  # preserve object identity: each fresh fixture value reaches one use
        parametrized = [name for name in args if fixtures[name][1]]
        if len(parametrized) > 1:
            return set()
        count = len(fixtures[parametrized[0]][2]) if parametrized else 1
        copies = []
        for index in range(count):
            values = {name: fixtures[name][2][index if fixtures[name][1] else 0] for name in args}
            clone = copy.deepcopy(function)
            clone.args.args = []
            clone.body = [_Values(values).visit(clone.body[0])]
            if parametrized:
                clone.name += f'__literal_fixture_{index}'
                if clone.name in existing_names:
                    return set()
            expanded.add(clone.name)
            if len(expanded) > 64:
                return set()
            copies.append(clone)
        replacements[function] = copies
        used.update(args)
        allowed_loads.update(id(node) for node in loads)
        allowed_args.update(id(node) for node in function.args.args)
    if used != fixtures.keys():
        return set()
    for node in nodes:
        if (isinstance(node, ast.Name) and node.id in fixtures and id(node) not in allowed_loads
                or isinstance(node, ast.arg) and node.arg in fixtures and id(node) not in allowed_args
                or isinstance(node, ast.Attribute) and node.attr in fixtures
                or isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in fixtures):
            return set()
    tree.body = [item for node in tree.body if not isinstance(node, ast.FunctionDef) or node.name not in fixtures
                 for item in replacements.get(node, [node])]
    return expanded

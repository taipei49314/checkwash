"""Keep a complete string-oracle block through literal helper extraction."""

import ast
import copy


IMPLICIT_ENTRY_NAMES = {"setup_module", "teardown_module", "setup_function", "teardown_function",
                        "setup_class", "teardown_class", "setup_method", "teardown_method", "setup", "teardown"}


def _args(node):
    if not isinstance(node, ast.FunctionDef):
        return None
    args = node.args
    if (node.decorator_list or node.returns or getattr(node, 'type_params', ()) or args.posonlyargs
            or args.kwonlyargs or args.defaults or args.vararg or args.kwarg
            or any(arg.annotation for arg in args.args)):
        return None
    return [arg.arg for arg in args.args]


def _scalar(node):
    try:
        return type(ast.literal_eval(node)) in (type(None), bool, int, float, str, bytes)
    except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
        return False


class _Bindings(ast.NodeTransformer):
    def __init__(self, values):
        self.values = values

    def visit_Name(self, node):
        return copy.deepcopy(self.values.get(node.id, node))


class _LiteralBuiltins(ast.NodeTransformer):
    def visit_Call(self, node):
        node = self.generic_visit(node)
        if not isinstance(node.func, ast.Name) or node.keywords:
            return node
        if (node.func.id == 'len' and len(node.args) == 1 and isinstance(node.args[0], ast.Constant)
                and type(node.args[0].value) in (str, bytes)):
            return ast.copy_location(ast.Constant(value=len(node.args[0].value)), node)
        if (node.func.id == 'max' and 1 < len(node.args) <= 64
                and all(isinstance(arg, ast.Constant) and type(arg.value) is int for arg in node.args)):
            return ast.copy_location(ast.Constant(value=max(arg.value for arg in node.args)), node)
        return node


def string_block(function):
    """One subject call, length/prefix checks, then the exact string oracle."""
    if len(function.body) != 4:
        return None
    assignment, length, prefix, exact = function.body
    if (not isinstance(assignment, ast.Assign) or len(assignment.targets) != 1
            or not isinstance(assignment.targets[0], ast.Name) or not isinstance(assignment.value, ast.Call)
            or not all(isinstance(node, ast.Assert) and node.msg is None for node in (length, prefix, exact))):
        return None
    local = assignment.targets[0].id
    a, b, c = length.test, prefix.test, exact.test
    if not (isinstance(a, ast.Compare) and len(a.ops) == 1 and isinstance(a.ops[0], ast.Eq)
            and isinstance(a.left, ast.Call) and isinstance(a.left.func, ast.Name) and a.left.func.id == 'len'
            and len(a.left.args) == 1 and not a.left.keywords and isinstance(a.left.args[0], ast.Name)
            and a.left.args[0].id == local and isinstance(a.comparators[0], ast.Constant)
            and type(a.comparators[0].value) is int):
        return None
    if not (isinstance(b, ast.Call) and isinstance(b.func, ast.Attribute) and b.func.attr == 'startswith'
            and isinstance(b.func.value, ast.Name) and b.func.value.id == local
            and len(b.args) == 1 and not b.keywords and isinstance(b.args[0], ast.Constant)
            and type(b.args[0].value) is str):
        return None
    if not (isinstance(c, ast.Compare) and len(c.ops) == 1 and isinstance(c.ops[0], ast.Eq)
            and isinstance(c.left, ast.Name) and c.left.id == local
            and isinstance(c.comparators[0], ast.Constant) and type(c.comparators[0].value) is str):
        return None
    if any(isinstance(node, ast.Name) and node.id == local for node in ast.walk(assignment.value)):
        return None
    primary = copy.deepcopy(exact)
    primary.test.left = copy.deepcopy(assignment.value)
    canonical = _Bindings({local: ast.Name(id='_oracle_result', ctx=ast.Load())}).visit(copy.deepcopy(function))
    canonical.body[0].targets[0].ctx = ast.Store()
    return primary, canonical.body


def expand_string_blocks(tree):
    candidates = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)
                  and not node.name.startswith(('test', 'pytest_')) and node.name not in IMPLICIT_ENTRY_NAMES
                  and _args(node) is not None and len(node.body) == 4}
    if not candidates and not any(isinstance(node, ast.FunctionDef) and len(node.body) == 4 for node in tree.body):
        return set()
    for name in candidates:
        count = sum(isinstance(item, (ast.FunctionDef, ast.ClassDef)) and item.name == name
                    or isinstance(item, ast.Name) and isinstance(item.ctx, ast.Store) and item.id == name
                    or isinstance(item, ast.arg) and item.arg == name
                    or isinstance(item, ast.alias) and (item.asname or item.name.split('.')[0]) == name
                    for item in ast.walk(tree))
        if count != 1:
            return None
    if any((isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store) and node.id in {'len', 'max'})
           or (isinstance(node, ast.arg) and node.arg in {'len', 'max'})
           or (isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in {'len', 'max'})
           or (isinstance(node, ast.alias) and (node.asname or node.name.split('.')[0]) in {'len', 'max'})
           for node in ast.walk(tree)):
        return None
    result, expanded, used = [], set(), set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in candidates:
            continue
        if isinstance(node, ast.FunctionDef) and node.name.startswith('test') and _args(node) == []:
            if len(node.body) == 1 and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Call):
                call = node.body[0].value
                if isinstance(call.func, ast.Name) and call.func.id in candidates:
                    helper = candidates[call.func.id]
                    parameters = _args(helper)
                    if (call.keywords or len(call.args) != len(parameters) or len(set(parameters)) != len(parameters)
                            or not all(_scalar(arg) for arg in call.args)
                            or any(isinstance(item, ast.Name) and isinstance(item.ctx, ast.Store) and item.id in parameters
                                   for item in ast.walk(helper))):
                        return None
                    body = _Bindings(dict(zip(parameters, call.args))).visit(copy.deepcopy(helper)).body
                    node.body = body
                    used.add(call.func.id)
            node = _LiteralBuiltins().visit(node)
            if string_block(node) is not None:
                expanded.add(node.name)
        if any(isinstance(item, ast.Name) and item.id in candidates for item in ast.walk(node)):
            return None
        result.append(node)
    if used != candidates.keys():
        return None
    tree.body = result
    return expanded

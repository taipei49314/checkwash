"""Complete primitive tuple component checks retain a single concrete oracle."""
import ast
import copy

from checkwash.frontends.python.oracle_purity import _pure_module


def _block(body, forbidden):
    if not 2 <= len(body) <= 65:
        return None
    assignment = body[0]
    if (not isinstance(assignment, ast.Assign) or len(assignment.targets) != 1
            or not isinstance(assignment.targets[0], (ast.Tuple, ast.List))
            or not isinstance(assignment.value, ast.Call) or not isinstance(assignment.value.func, ast.Name)):
        return None
    targets = assignment.targets[0].elts
    if not targets or not all(isinstance(target, ast.Name) for target in targets):
        return None
    names = [target.id for target in targets]
    if len(names) != len(set(names)) or set(names) & forbidden:
        return None
    assertions = body[1:]
    if any(not isinstance(node, ast.Assert) or node.msg is not None or not isinstance(node.test, ast.Compare)
           or len(node.test.ops) != 1 or not isinstance(node.test.ops[0], ast.Eq) for node in assertions):
        return None
    if len(assertions) == 1:
        left = assertions[0].test.left
        if (not isinstance(left, ast.Tuple) or len(left.elts) != len(names)
                or any(not isinstance(value, ast.Name) or value.id != name for value, name in zip(left.elts, names))):
            return None
        expected = assertions[0].test.comparators[0]
    elif len(assertions) == len(names):
        if any(not isinstance(node.test.left, ast.Name) or node.test.left.id != name
               for node, name in zip(assertions, names)):
            return None
        expected = ast.Tuple(elts=[node.test.comparators[0] for node in assertions], ctx=ast.Load())
    else:
        return None
    if any(isinstance(node, ast.Name) and node.id in names for node in ast.walk(expected)):
        return None
    assertion = copy.deepcopy(assertions[0])
    assertion.test = ast.Compare(left=copy.deepcopy(assignment.value), ops=[ast.Eq()], comparators=[copy.deepcopy(expected)])
    assertion._requires_tuple_arity = len(names)
    return [ast.copy_location(assertion, assertions[0])]


def expand_tuple_oracles(tree):
    """Only complete straight-line blocks; surrounding carriers stay validated."""
    forbidden = {node.asname or node.name.split('.')[0] for node in ast.walk(tree) if isinstance(node, ast.alias)}
    forbidden.update(node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef)))
    forbidden.update(target.id for node in tree.body if isinstance(node, ast.Assign)
                     for target in node.targets if isinstance(target, ast.Name))
    result = set()
    for function in tree.body:
        if not isinstance(function, ast.FunctionDef) or not function.name.startswith('test'):
            continue
        scope = forbidden | {arg.arg for arg in function.args.args + function.args.posonlyargs + function.args.kwonlyargs}
        replacement = _block(function.body, scope)
        if replacement is not None:
            function.body = replacement
            result.add(function.name)
        elif len(function.body) == 1 and isinstance(function.body[0], ast.For):
            loop = function.body[0]
            names = {node.id for node in ast.walk(loop.target) if isinstance(node, ast.Name)}
            replacement = _block(loop.body, scope | names)
            if replacement is not None:
                loop.body = replacement
                result.add(function.name)
    return result


def primitive_tuple_result(source, target, call, arity):
    """Every explicit return is a built-in tuple with the unpacked arity."""
    if not _pure_module(source, target):
        return False
    function = next((node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name == target), None)
    returns = [node.value for node in ast.walk(function) if isinstance(node, ast.Return)] if function else []
    return bool(returns) and all(isinstance(value, ast.Tuple) and len(value.elts) == arity for value in returns)

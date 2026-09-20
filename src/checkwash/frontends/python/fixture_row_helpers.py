"""Move a helper's exact row unpack into fully accounted fixture consumers."""
import ast
import copy


def expand_fixture_row_helpers(functions, fixtures, arguments, helper):
    candidates = {}
    for function in functions:
        parameters = arguments(function)
        if (parameters is None or len(parameters) != 1 or function.decorator_list
                or not 2 <= len(function.body) <= 3):
            continue
        unpack = function.body[0]
        if (not isinstance(unpack, ast.Assign) or len(unpack.targets) != 1
                or not isinstance(unpack.targets[0], (ast.List, ast.Tuple))
                or not isinstance(unpack.value, ast.Name) or unpack.value.id != parameters[0]
                or not all(isinstance(target, ast.Name) for target in unpack.targets[0].elts)):
            continue
        names = [target.id for target in unpack.targets[0].elts]
        if not names or len(set(names)) != len(names) or parameters[0] in names:
            continue
        clone = copy.deepcopy(function)
        clone.args.args = [ast.arg(arg=name) for name in names]
        clone.body = clone.body[1:]
        if (not any(isinstance(node, ast.Name) and node.id == parameters[0]
                    for statement in clone.body for node in ast.walk(statement)) and helper(clone) is not None):
            candidates[function.name] = (clone, unpack, names)
    if not candidates:
        return functions, set()
    replacements, uses, allowed = {}, set(), set()
    for function in functions:
        if function.name in candidates:
            continue
        parameters = arguments(function)
        if (parameters is None or len(parameters) != 1 or parameters[0] not in fixtures
                or function.decorator_list or not function.name.startswith('test') or len(function.body) != 1
                or not isinstance(function.body[0], ast.Expr) or not isinstance(function.body[0].value, ast.Call)):
            continue
        call = function.body[0].value
        if (not isinstance(call.func, ast.Name) or call.func.id not in candidates or call.keywords
                or len(call.args) != 1 or not isinstance(call.args[0], ast.Name) or call.args[0].id != parameters[0]):
            continue
        _, unpack, names = candidates[call.func.id]
        if parameters[0] in names or call.func.id in names:
            return None, set()
        clone = copy.deepcopy(function)
        assignment = copy.deepcopy(unpack)
        assignment.value = copy.deepcopy(call.args[0])
        # The body still calls the same validated helper. The normal table
        # parser retains the argument-use and concrete-oracle checks.
        invocation = copy.deepcopy(function.body[0])
        invocation.value.args = [ast.Name(id=name, ctx=ast.Load()) for name in names]
        clone.body = [assignment, invocation]
        replacements[function.name] = clone
        uses.add(call.func.id)
        allowed.add(id(call.func))
    if uses != candidates.keys():
        return functions, set()  # leave unrelated/unused helper bodies visible
    for function in functions:
        for node in ast.walk(function):
            if ((isinstance(node, ast.Name) and node.id in candidates and id(node) not in allowed)
                    or isinstance(node, ast.arg) and node.arg in candidates):
                return None, set()
    return [candidates[function.name][0] if function.name in candidates else replacements.get(function.name, function)
            for function in functions], set(replacements)

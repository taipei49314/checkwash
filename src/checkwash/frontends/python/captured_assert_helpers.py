"""Expose the exact assertion of a helper checking a captured primitive value."""
import ast
import copy

from .oracle_blocks import IMPLICIT_ENTRY_NAMES, _args


def _capture_expression(node):
    if isinstance(node, ast.Name):
        return True
    if isinstance(node, ast.Subscript):
        return (isinstance(node.value, ast.Name) and isinstance(node.slice, ast.Constant)
                and type(node.slice.value) in (int, str))
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'len'
            and len(node.args) == 1 and isinstance(node.args[0], ast.Name) and not node.keywords)


def expand_captured_assert_helpers(tree, literal):
    """Only a complete two-name equality body; no call itself is an oracle.

    The later whole-body grammar must prove the capture and all checks, and
    the caller must close every production import on both snapshots. Unknown
    helper references remain visible; only fully consumed definitions vanish.
    """
    candidates = {}
    for function in tree.body:
        parameters = _args(function)
        if (parameters is None or len(parameters) != 2 or len(set(parameters)) != 2
                or function.name.startswith(('test', 'pytest_', '__')) or function.name in IMPLICIT_ENTRY_NAMES
                or len(function.body) != 1 or not isinstance(function.body[0], ast.Assert)):
            continue
        assertion = function.body[0]
        compare = assertion.test
        if (assertion.msg is not None or not isinstance(compare, ast.Compare) or len(compare.ops) != 1
                or not isinstance(compare.ops[0], ast.Eq) or not isinstance(compare.left, ast.Name)
                or compare.left.id != parameters[0] or not isinstance(compare.comparators[0], ast.Name)
                or compare.comparators[0].id != parameters[1]):
            continue
        bindings = sum(isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name == function.name
                       or isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store) and node.id == function.name
                       or isinstance(node, ast.arg) and node.arg == function.name
                       or isinstance(node, ast.alias) and (node.asname or node.name.split('.')[0]) == function.name
                       for node in ast.walk(tree))
        if bindings == 1:
            candidates[function.name] = parameters
    changed, used = set(), set()
    for function in tree.body:
        if not isinstance(function, ast.FunctionDef) or not function.name.startswith('test') or _args(function) != []:
            continue
        for index, statement in enumerate(function.body):
            if not isinstance(statement, ast.Expr) or not isinstance(statement.value, ast.Call):
                continue
            call = statement.value
            if not isinstance(call.func, ast.Name) or call.func.id not in candidates:
                continue
            parameters = candidates[call.func.id]
            if len(call.args) > 2:
                continue
            arguments = dict(zip(parameters, call.args))
            for keyword in call.keywords:
                if keyword.arg not in parameters or keyword.arg in arguments:
                    break
                arguments[keyword.arg] = keyword.value
            else:
                if (len(arguments) == 2 and _capture_expression(arguments[parameters[0]])
                        and literal(arguments[parameters[1]])):
                    comparison = ast.Compare(left=copy.deepcopy(arguments[parameters[0]]), ops=[ast.Eq()],
                                             comparators=[copy.deepcopy(arguments[parameters[1]])])
                    function.body[index] = ast.copy_location(ast.Assert(test=comparison, msg=None), statement)
                    used.add(call.func.id)
                    changed.add(function.name)
    references = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    tree.body = [node for node in tree.body if not (
        isinstance(node, ast.FunctionDef) and node.name in used and node.name not in references)]
    return changed

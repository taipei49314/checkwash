"""Closed added parametrized tests beside an existing exception carrier."""
import ast
import copy

from .oracle_purity import _literal
from .table_oracles import _args, _bounded_tree, _Substitute
from checkwash.ir.astutil import dotted_name


def added_literal_tests(source, target, controls, inert_message):
    """Return the original target and calls from fully inspected extra tests.

    Added tests retain their native IR. This grammar only proves that their
    decorators and bodies cannot install a replacement for the old subject.
    The caller must prove every concrete imported call pure on both sides.
    """
    tree = _bounded_tree(source)
    if tree is None:
        return None
    imported, functions, occupied, pytest = None, [], set(), False
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and type(node.value.value) is str:
            continue
        if (isinstance(node, ast.Import) and not functions and not pytest and len(node.names) == 1
                and node.names[0].name == 'pytest' and node.names[0].asname is None):
            name, pytest = 'pytest', True
        elif (isinstance(node, ast.ImportFrom) and not functions and imported is None and not node.level
              and node.module and len(node.names) == 1 and node.names[0].name != '*'):
            imported = node
            name = node.names[0].asname or node.names[0].name
        elif isinstance(node, ast.FunctionDef) and _args(node) is not None:
            name = node.name
            functions.append(node)
        else:
            return None
        if (name in occupied or name.startswith(('__', 'pytest_'))
                or name in controls and not (name == 'pytest' and isinstance(node, ast.Import))):
            return None
        occupied.add(name)
    if (not pytest or imported is None or not 2 <= len(functions) <= 16
            or functions[0].name != target or _args(functions[0]) != [] or functions[0].decorator_list):
        return None
    provider = imported.names[0].asname or imported.names[0].name
    calls = []
    for function in functions[1:]:
        args = _args(function)
        if (not function.name.startswith('test') or not args or len(set(args)) != len(args)
                or set(args) & (occupied | {'request'}) or len(function.decorator_list) != 1):
            return None
        decorator = function.decorator_list[0]
        if (not isinstance(decorator, ast.Call) or dotted_name(decorator.func) != 'pytest.mark.parametrize'
                or decorator.keywords or len(decorator.args) != 2
                or not isinstance(decorator.args[0], ast.Constant) or type(decorator.args[0].value) is not str
                or [name.strip() for name in decorator.args[0].value.split(',')] != args
                or not isinstance(decorator.args[1], (ast.List, ast.Tuple))
                or not 0 < len(decorator.args[1].elts) <= 64):
            return None
        for row in decorator.args[1].elts:
            values = [row] if len(args) == 1 else row.elts if isinstance(row, (ast.List, ast.Tuple)) else []
            if len(values) != len(args) or not all(_literal(value) for value in values):
                return None
            values = [ast.Constant(value=literal) if type(literal := ast.literal_eval(value))
                      in (type(None), bool, int, float, str, bytes) else value for value in values]
            body = _Substitute(dict(zip(args, values))).visit(
                ast.Module(body=copy.deepcopy(function.body), type_ignores=[])).body
            capture = None
            if len(body) == 2 and isinstance(body[0], ast.Assign) and len(body[0].targets) == 1:
                assignment, check = body
                if (not isinstance(assignment.targets[0], ast.Name)
                        or assignment.targets[0].id in occupied | set(args)):
                    return None
                capture, call = assignment.targets[0].id, assignment.value
                subject = check.test.left if isinstance(check, ast.Assert) and isinstance(check.test, ast.Compare) else None
                if not isinstance(subject, ast.Name) or subject.id != capture:
                    return None
            elif len(body) == 1 and isinstance(body[0], ast.Assert) and isinstance(body[0].test, ast.Compare):
                check, call = body[0], body[0].test.left
            else:
                return None
            if (not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name) or call.func.id != provider
                    or call.keywords or not all(_literal(arg) for arg in call.args)
                    or not isinstance(check, ast.Assert) or not isinstance(check.test, ast.Compare)
                    or len(check.test.ops) != 1 or not isinstance(check.test.ops[0], (ast.Eq, ast.Is))
                    or not _literal(check.test.comparators[0]) or not inert_message(check.msg, capture)):
                return None
            calls.append(call)
            if len(calls) > 64:
                return None
    return (imported, functions[0], provider), calls

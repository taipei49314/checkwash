"""Expose a single fresh literal input without changing input identity."""
import ast
import copy

from .oracle_blocks import _args


def expand_literal_subject_bindings(tree, literal):
    """The caller retains exact row keys and requires both source purity proofs."""
    forbidden = {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
    imports = {alias.asname or alias.name.split('.')[0] for node in tree.body
               if isinstance(node, (ast.Import, ast.ImportFrom)) for alias in node.names}
    forbidden.update(imports)
    forbidden.update(target.id for node in tree.body if isinstance(node, ast.Assign)
                     for target in node.targets if isinstance(target, ast.Name))
    changed = set()
    for function in tree.body:
        if (not isinstance(function, ast.FunctionDef) or not function.name.startswith('test')
                or _args(function) != []):
            continue
        body = function.body
        if (body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
                and type(body[0].value.value) is str):
            body = body[1:]
        if len(body) != 2:
            continue
        assignment, check = body
        if (not isinstance(assignment, ast.Assign) or len(assignment.targets) != 1
                or not isinstance(assignment.targets[0], ast.Name) or not literal(assignment.value)
                or not isinstance(check, ast.Assert) or not isinstance(check.test, ast.Compare)
                or len(check.test.ops) != 1 or not isinstance(check.test.ops[0], (ast.Eq, ast.Is))):
            continue
        name, call = assignment.targets[0].id, check.test.left
        if (name in forbidden or name.startswith('__')
                or not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name) or call.func.id not in imports
                or len({keyword.arg for keyword in call.keywords}) != len(call.keywords)
                or any(keyword.arg is None for keyword in call.keywords)
                or sum(isinstance(node, ast.Name) and node.id == name for node in ast.walk(call)) != 1
                or any(isinstance(node, ast.Name) and node.id == name for node in ast.walk(check.test.comparators[0]))):
            continue

        class Substitute(ast.NodeTransformer):
            def visit_Name(self, node):
                return copy.deepcopy(assignment.value) if node.id == name else node

        normalized = Substitute().visit(copy.deepcopy(check))
        resolved = normalized.test.left
        if (not all(literal(arg) for arg in resolved.args)
                or not all(literal(keyword.value) for keyword in resolved.keywords)):
            continue
        function.body = [normalized]
        changed.add(function.name)
    return changed

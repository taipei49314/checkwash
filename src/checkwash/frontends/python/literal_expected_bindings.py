"""One fresh literal local immediately consumed as an assertion's answer."""
import ast
import copy

from .oracle_blocks import _args


def expand_literal_expected_bindings(tree, literal):
    """Keep substitution single-use; the caller must close production purity.

    Allocation moves across the subject call, so even a literal answer needs
    the two-sided source proof. Other statements, uses or bindings remain
    untouched for the complete module/body validation to reject if unknown.
    """
    forbidden = {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
    forbidden.update(node.asname or node.name.split('.')[0] for node in ast.walk(tree) if isinstance(node, ast.alias))
    forbidden.update(target.id for node in tree.body if isinstance(node, ast.Assign)
                     for target in node.targets if isinstance(target, ast.Name))
    changed = set()
    for function in tree.body:
        if (not isinstance(function, ast.FunctionDef) or not function.name.startswith('test')
                or _args(function) != []):
            continue
        body, index = [], 0
        while index < len(function.body):
            assignment = function.body[index]
            check = function.body[index + 1] if index + 1 < len(function.body) else None
            if (not isinstance(assignment, ast.Assign) or len(assignment.targets) != 1
                    or not isinstance(assignment.targets[0], ast.Name) or not literal(assignment.value)
                    or not isinstance(check, ast.Assert) or not isinstance(check.test, ast.Compare)
                    or len(check.test.ops) != 1 or not isinstance(check.test.ops[0], (ast.Eq, ast.Is))):
                body.append(assignment)
                index += 1
                continue
            name = assignment.targets[0].id
            answer = check.test.comparators[0]
            occurrences = [node for node in ast.walk(function) if isinstance(node, ast.Name) and node.id == name]
            if (name in forbidden or not isinstance(answer, ast.Name) or answer.id != name
                    or len(occurrences) != 2 or sum(isinstance(node.ctx, ast.Store) for node in occurrences) != 1):
                body.append(assignment)
                index += 1
                continue
            check = copy.deepcopy(check)
            check.test.comparators[0] = copy.deepcopy(assignment.value)
            body.append(check)
            changed.add(function.name)
            index += 2
        function.body = body
    return changed

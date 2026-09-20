"""Reassemble split fragments only when they retain a complete captured oracle.

This supplies no credit to a partial check. The complete tuple/string/field
validators must accept every concatenated group, with all original assertion
occurrences retained. The caller closes imported production and startup on
both snapshots before allowing repeated calls to be regrouped.
"""
import ast
import copy
from collections import Counter

from .oracle_blocks import _args, string_block
from .tuple_oracles import _block as tuple_block


class _LocalNames(ast.NodeTransformer):
    def __init__(self, names):
        self.names = names

    def visit_Name(self, node):
        return ast.copy_location(ast.Name(id=self.names.get(node.id, node.id), ctx=node.ctx), node)


def _message(node, literal, repr_unbound):
    if node is None or isinstance(node, ast.Constant) and type(node.value) is str:
        return True
    return (repr_unbound and isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add)
            and isinstance(node.left, ast.Constant) and type(node.left.value) is str
            and isinstance(node.right, ast.Call) and isinstance(node.right.func, ast.Name)
            and node.right.func.id == 'repr' and len(node.right.args) == 1 and not node.right.keywords
            and literal(node.right.args[0]))


def _complete(body, function, forbidden):
    candidate = copy.copy(function)
    candidate.body = body
    return tuple_block(body, forbidden) is not None or string_block(candidate) is not None


def capture_obligations(source, literal):
    """Re-read original clauses only for an attempted regrouping transition."""
    from .captured_assert_helpers import expand_captured_assert_helpers
    from .inert_signatures import strip_none_test_returns
    from .literal_expected_bindings import expand_literal_expected_bindings
    tree = ast.parse(source)
    strip_none_test_returns(tree)
    expand_literal_expected_bindings(tree, literal)
    expand_captured_assert_helpers(tree, literal)
    regroup_complete_captures(tree, literal)
    return getattr(tree, '_capture_obligations', None)


def regroup_complete_captures(tree, literal):
    if not any(isinstance(function, ast.FunctionDef) and any(
            isinstance(statement, ast.Assign) and isinstance(statement.value, ast.Call)
            for statement in function.body) for function in tree.body):
        return set()
    imports = {alias.asname or alias.name for node in tree.body
               if isinstance(node, ast.ImportFrom) and node.module and not node.level for alias in node.names}
    bound = Counter()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound[node.name] += 1
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            bound[node.id] += 1
        elif isinstance(node, ast.arg):
            bound[node.arg] += 1
        elif isinstance(node, ast.alias):
            bound[node.asname or node.name.split('.')[0]] += 1
    if {'len', 'max'} & bound.keys():
        return set()
    forbidden = imports | {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
    forbidden.update(target.id for node in tree.body if isinstance(node, ast.Assign)
                     for target in node.targets if isinstance(target, ast.Name))
    groups, selected, incomplete, obligations = {}, [], False, Counter()
    for function in tree.body:
        if (not isinstance(function, ast.FunctionDef) or not function.name.startswith('test')
                or _args(function) != [] or bound[function.name] != 1):
            continue
        fragments = []
        for statement in function.body:
            if isinstance(statement, ast.Assign) and isinstance(statement.value, ast.Call):
                fragments.append([statement])
            elif isinstance(statement, ast.Assert) and fragments:
                fragments[-1].append(statement)
            else:
                fragments = []
                break
        if not fragments:
            continue
        selected.append(function)
        for fragment in fragments:
            assignment, *checks = fragment
            call = assignment.value
            if (len(assignment.targets) != 1 or not checks or not isinstance(call.func, ast.Name)
                    or call.func.id not in imports or not all(literal(arg) for arg in call.args)
                    or not all(keyword.arg is not None and literal(keyword.value) for keyword in call.keywords)):
                return set()
            target = assignment.targets[0]
            targets = [target] if isinstance(target, ast.Name) else target.elts if isinstance(target, (ast.Tuple, ast.List)) else []
            if not targets or not all(isinstance(item, ast.Name) for item in targets):
                return set()
            names = [item.id for item in targets]
            if len(names) != len(set(names)) or set(names) & (forbidden | {'len', 'max', 'repr'}):
                return set()
            canonical = [f'_checkwash_capture_{index}' for index in range(len(names))]
            if set(canonical) & forbidden:
                return set()
            body = _LocalNames(dict(zip(names, canonical))).visit(ast.Module(body=copy.deepcopy(fragment), type_ignores=[])).body
            for check in body[1:]:
                if not _message(check.msg, literal, 'repr' not in bound):
                    return set()
                check.msg = None
            key = (ast.dump(call), type(target).__name__, len(names))
            for check in body[1:]:
                obligation = copy.deepcopy(check.test)
                if (isinstance(obligation, ast.Compare) and len(obligation.ops) == 1
                        and isinstance(obligation.ops[0], (ast.Eq, ast.Is))
                        and literal(obligation.comparators[0])):
                    # Keep expected-value edits available to their ordinary
                    # detector; only the answer value is omitted from identity.
                    obligation.comparators[0] = ast.Name(id='_checked_answer', ctx=ast.Load())
                obligations[key + (ast.dump(obligation),)] += 1
            groups.setdefault(key, []).append((body, function))
            incomplete |= not _complete(body, function, forbidden)
    tree._capture_obligations = obligations
    if not incomplete or not 1 <= len(groups) <= 64:
        return set()
    selected_names = {function.name for function in selected}
    if any(isinstance(node, ast.Name) and node.id in selected_names for node in ast.walk(tree)):
        return set()  # collected functions must have no explicit callers or aliases
    replacements = []
    for index, fragments in enumerate(groups.values()):
        first, owner = fragments[0]
        body = [first[0], *(check for fragment, _ in fragments for check in fragment[1:])]
        if not _complete(body, owner, forbidden):
            return set()  # duplicate, missing or conflicting clauses never disappear
        function = copy.copy(owner)
        function.name = f'{owner.name}__complete_capture_{index}'
        if function.name in bound:
            return set()
        function.body = body
        function.end_lineno = max(original.end_lineno for _, original in fragments)
        function.end_col_offset = max(original.end_col_offset for _, original in fragments
                                      if original.end_lineno == function.end_lineno)
        replacements.append(function)
    selected_ids = {id(function) for function in selected}
    tree.body = [node for node in tree.body if id(node) not in selected_ids] + replacements
    return {function.name for function in replacements}

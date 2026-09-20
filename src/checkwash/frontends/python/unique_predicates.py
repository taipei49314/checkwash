"""Keep an exact primitive sequence oracle beside an entailed uniqueness check.

Supported clauses count unique output or unique input elements. The complete
predicate must follow from the exact flat literal answer and, for input counts,
the concrete input row. Neither a predicate alone nor partial element checks
become an exact oracle.
"""
import ast
import copy
from collections import Counter

from checkwash.frontends.python.oracle_blocks import IMPLICIT_ENTRY_NAMES, _args
from checkwash.ir.astutil import stable_dump


def _unique_helper(node):
    names = _args(node)
    if names is None or len(names) != 1 or len(node.body) != 1 or not isinstance(node.body[0], ast.Return):
        return False
    expected = ast.parse(f'len({names[0]}) == len(set({names[0]}))', mode='eval').body
    return stable_dump(node.body[0].value) == stable_dump(expected)


def _unique_literal(node):
    if not isinstance(node, (ast.List, ast.Tuple)):
        return False
    try:
        values = ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return False
    return (all(type(value) in (type(None), bool, int, float, str, bytes) for value in values)
            and len(values) == len(set(values)))


def input_unique_count(actual, expected):
    """The exact answer entails the helper's input-cardinality clause.

    These are concrete flat primitive row values. The caller separately
    proves that production cannot mutate the input before the second check.
    """
    if (not isinstance(actual, ast.Call) or actual.keywords or len(actual.args) != 1
            or not isinstance(actual.args[0], (ast.List, ast.Tuple)) or not _unique_literal(expected)):
        return False
    try:
        values, answer = ast.literal_eval(actual.args[0]), ast.literal_eval(expected)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return False
    return (len(values) <= 64 and all(type(value) in (type(None), bool, int, float, str, bytes) for value in values)
            and len(answer) == len(set(values)))


def complete_unique_helper(node):
    """Capture, exact expected argument, then the complete uniqueness clause.

    Later concrete-row checks prove a unique expected sequence and any input
    cardinality obligation. This syntax alone grants no equivalence credit.
    """
    names = _args(node)
    if (names is None or len(names) != 2 or len(set(names)) != 2
            or any(name.startswith('__') for name in names) or len(node.body) != 3):
        return None
    assignment, exact, predicate = node.body
    if (not isinstance(assignment, ast.Assign) or len(assignment.targets) != 1
            or not isinstance(assignment.targets[0], ast.Name) or not isinstance(assignment.value, ast.Call)
            or not isinstance(assignment.value.func, ast.Name) or assignment.value.keywords
            or len(assignment.value.args) != 1 or not isinstance(assignment.value.args[0], ast.Name)
            or assignment.value.args[0].id != names[0]
            or not isinstance(exact, ast.Assert) or not isinstance(predicate, ast.Assert)):
        return None
    local = assignment.targets[0].id
    if local.startswith('__') or local in names or local == assignment.value.func.id:
        return None
    expected = ast.parse(f'{local} == {names[1]}', mode='eval').body
    unique = ast.parse(f'len({local}) == len(set({local}))', mode='eval').body
    input_count = ast.parse(f'len({local}) == len(set({names[0]}))', mode='eval').body
    counted_input = stable_dump(predicate.test) == stable_dump(input_count)
    if (stable_dump(exact.test) != stable_dump(expected)
            or not (stable_dump(predicate.test) == stable_dump(unique) and exact.msg is None and predicate.msg is None
                    or counted_input and (predicate.msg is None or isinstance(predicate.msg, ast.Constant)
                                           and type(predicate.msg.value) is str))):
        return None
    assertion = copy.deepcopy(exact)
    class Captured(ast.NodeTransformer):
        def visit_Name(self, item):
            return copy.deepcopy(assignment.value) if item.id == local else item
    assertion = Captured().visit(assertion)
    assertion._requires_unique_expected = True
    assertion._requires_primitive_string = True
    if counted_input:
        assertion._requires_input_unique_count = True
    return assertion


def unshadowed_unique_builtins(tree):
    for node in ast.walk(tree):
        name = None
        if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load):
            name = node.id
        elif isinstance(node, ast.arg):
            name = node.arg
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = node.name
        elif isinstance(node, ast.alias):
            name = node.asname or node.name.split('.')[0]
        if name in {'len', 'set'}:
            return False
    return True


def _checked_block(body, helpers):
    if len(body) != 3:
        return None
    assignment, predicate, exact = body
    if (not isinstance(assignment, ast.Assign) or len(assignment.targets) != 1
            or not isinstance(assignment.targets[0], ast.Name) or not isinstance(assignment.value, ast.Call)
            or not isinstance(predicate, ast.Assert) or predicate.msg is not None
            or not isinstance(exact, ast.Assert) or exact.msg is not None):
        return None
    local, call, compare = assignment.targets[0].id, predicate.test, exact.test
    if (not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name) or call.func.id not in helpers
            or call.keywords or len(call.args) != 1 or not isinstance(call.args[0], ast.Name) or call.args[0].id != local
            or not isinstance(compare, ast.Compare) or len(compare.ops) != 1 or not isinstance(compare.ops[0], ast.Eq)
            or not isinstance(compare.left, ast.Name) or compare.left.id != local
            or not _unique_literal(compare.comparators[0])
            or any(isinstance(node, ast.Name) and node.id == local for node in ast.walk(assignment.value))):
        return None
    assertion = copy.deepcopy(exact)
    assertion.test.left = copy.deepcopy(assignment.value)
    assertion._requires_primitive_string = True
    return assertion, call.func.id


def expand_unique_predicates(tree):
    helpers = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)
               and not node.name.startswith(('test', 'pytest_', '__')) and node.name not in IMPLICIT_ENTRY_NAMES
               and _unique_helper(node)}
    if not helpers:
        return set()
    nodes = list(ast.walk(tree))
    bindings = Counter(node.id for node in nodes if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load))
    bindings.update(node.arg for node in nodes if isinstance(node, ast.arg))
    bindings.update(node.name for node in nodes if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))
    bindings.update(node.asname or node.name.split('.')[0] for node in nodes if isinstance(node, ast.alias))
    if any(bindings[name] != 1 for name in helpers) or bindings['len'] or bindings['set']:
        return None
    result, expanded, used = [], set(), set()
    for function in tree.body:
        if isinstance(function, ast.FunctionDef) and function.name in helpers:
            continue
        if isinstance(function, ast.FunctionDef) and function.name.startswith('test') and _args(function) == []:
            checked = _checked_block(function.body, helpers)
            if checked is not None:
                assertion, helper = checked
                function.body = [assertion]
                used.add(helper)
                expanded.add(function.name)
        if any(isinstance(node, ast.Name) and node.id in helpers for node in ast.walk(function)):
            return None
        result.append(function)
    if used != helpers:
        return None
    tree.body = result
    return expanded

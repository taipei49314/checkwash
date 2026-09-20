"""Literal expectations consumed by a closed local mismatch-list oracle.

An empty list, one production result, one conditional append and the final
emptiness assertion establish the comparison that the test actually checks.
This only adds expectation provenance; the source assertions remain intact.
"""
from __future__ import annotations

import ast
import copy

from .callable_fixture_expectations import _parameters, _tree
from .expected_constants import folded_expected
from .frontend import _Offsets, normalize_source
from .oracle_purity import pure_imported_calls
from .primitive_strings import primitive_string_result
from .snapshot_context import inert_test_execution_context
from checkwash.ir.astutil import stable_dump


def _string(node):
    return (isinstance(node, ast.Constant) and type(node.value) is str
            and len(node.value) <= 1024 and node.value.isascii())


def _name(node, name):
    return isinstance(node, ast.Name) and node.id == name


def _assignment(statement):
    if (isinstance(statement, ast.Assign) and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)):
        return statement.targets[0].id
    return None


def _condition(condition, result, helper):
    """Return the independent answer and its literal diagnostic payload."""
    if isinstance(condition, ast.Compare) and len(condition.ops) == 1 and isinstance(condition.ops[0], ast.NotEq):
        if _name(condition.left, result) and _string(condition.comparators[0]) and helper is None:
            return condition.comparators[0], condition.comparators[0]
        return None
    if not isinstance(condition, ast.UnaryOp) or not isinstance(condition.op, ast.Not):
        return None
    condition = condition.operand
    if helper is None:
        if (isinstance(condition, ast.Compare) and len(condition.ops) == 1 and isinstance(condition.ops[0], ast.Eq)
                and _name(condition.left, result) and _string(condition.comparators[0])):
            return condition.comparators[0], condition.comparators[0]
        return None
    if (not isinstance(condition, ast.Call) or not _name(condition.func, helper.name)
            or condition.keywords or len(condition.args) != 2 or not _name(condition.args[0], result)
            or not _string(condition.args[1])):
        return None
    parameters = _parameters(helper)
    if (parameters is None or len(parameters) != 2 or helper.decorator_list or len(helper.body) != 1
            or not isinstance(helper.body[0], ast.Return)):
        return None
    comparison = helper.body[0].value
    if (not isinstance(comparison, ast.Compare) or len(comparison.ops) != 1
            or not isinstance(comparison.ops[0], ast.Eq) or not _name(comparison.left, parameters[0])):
        return None
    right = comparison.comparators[0]
    if any(isinstance(node, ast.Name) and node.id != parameters[1] for node in ast.walk(right)):
        return None

    class Substitute(ast.NodeTransformer):
        def visit_Name(self, node):
            return copy.deepcopy(condition.args[1])

    expected = folded_expected(Substitute().visit(copy.deepcopy(right)), lambda _: False)
    return (expected, condition.args[1]) if _string(expected) else None


def _trace(source):
    tree = _tree(source)
    if tree is None:
        return None
    body = [node for node in tree.body if not (isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant) and type(node.value.value) is str)]
    if len(body) != 2:
        return None
    imported, test = body
    if (not isinstance(imported, ast.ImportFrom) or imported.level or not imported.module or len(imported.names) != 1
            or imported.names[0].name == '*' or not isinstance(test, ast.FunctionDef)
            or not test.name.startswith('test') or test.decorator_list or _parameters(test) != []):
        return None
    alias = imported.names[0]
    provider = alias.asname or alias.name
    if provider == test.name or provider.startswith('__') or alias.name.startswith('__'):
        return None
    statements, helper = test.body, None
    if statements and isinstance(statements[0], ast.FunctionDef):
        helper, statements = statements[0], statements[1:]
    if len(statements) != 4:
        return None
    initialized, captured, branch, final = statements
    errors, result = _assignment(initialized), _assignment(captured)
    names = [provider, test.name, errors, result, *([helper.name] if helper else [])]
    if (None in names or len(set(names)) != len(names) or any(name.startswith('__') for name in names)
            or not isinstance(initialized.value, ast.List) or initialized.value.elts):
        return None
    call = captured.value
    if (not isinstance(call, ast.Call) or not _name(call.func, provider) or call.keywords
            or not 1 <= len(call.args) <= 4 or not all(_string(arg) for arg in call.args)
            or not isinstance(branch, ast.If) or branch.orelse or len(branch.body) != 1
            or not isinstance(final, ast.Assert) or final.msg is not None
            or not isinstance(final.test, ast.UnaryOp) or not isinstance(final.test.op, ast.Not)
            or not _name(final.test.operand, errors)):
        return None
    expected = _condition(branch.test, result, helper)
    appended = branch.body[0]
    if expected is None or not isinstance(appended, ast.Expr) or not isinstance(appended.value, ast.Call):
        return None
    append = appended.value
    if (not isinstance(append.func, ast.Attribute) or append.func.attr != 'append'
            or not _name(append.func.value, errors) or append.keywords or len(append.args) != 1
            or not isinstance(append.args[0], ast.Tuple) or len(append.args[0].elts) != 2
            or not _name(append.args[0].elts[0], result)
            or stable_dump(append.args[0].elts[1]) != stable_dump(expected[1])):
        return None
    return tree, test, imported, call, expected[0], branch, final


def trace_expectation_events(path, before, after, reader):
    """Keep the same concrete production call's changed trace answer visible."""
    from .table_oracles import _pytest_unshadowed
    if (not before or not after or b'.append' not in before or b'.append' not in after
            or any(p != path and old != new for p, (old, new) in reader.raw.items())):
        return []
    try:
        old, new = _trace(before), _trace(after)
        if (old is None or new is None or old[1].name != new[1].name
                or stable_dump(old[2]) != stable_dump(new[2]) or stable_dump(old[3]) != stable_dump(new[3])
                or stable_dump(old[4]) == stable_dump(new[4])):
            return []
        for side, (source, trace) in enumerate(zip((before, after), (old, new))):
            read = lambda candidate, side=side: reader.source(candidate, side, authority=True)
            search = lambda needles, side=side: reader.search(needles, side)
            if (not inert_test_execution_context(path, read, search) or not _pytest_unshadowed(path, read)
                    or not pure_imported_calls(source, [trace[3]], path=path, read=read,
                                               result_proof=primitive_string_result)):
                return []
        evidence = []
        for source, trace in ((before, old), (after, new)):
            offsets = _Offsets(normalize_source(source))
            span = offsets.span(trace[5])[0], offsets.span(trace[6])[1]
            evidence.extend((offsets.text[slice(*span)], span))
        return [(old[1].name, *evidence, ast.unparse(old[3]), 'Eq', ast.unparse(old[4]), ast.unparse(new[4]))]
    except (SyntaxError, ValueError, TypeError, AttributeError, RecursionError, MemoryError):
        return []

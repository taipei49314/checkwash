"""Retain field answers when a closed string helper supplies a whole mapping.

Only a literal string split and closed primitive expressions form the helper
answer. Both snapshots must return ordinary dictionaries with exactly those
keys. This contributes provenance, never field/full-dictionary equivalence.
"""
from __future__ import annotations

import ast
import copy

from .callable_fixture_expectations import _parameters, _tree
from .expected_constants import folded_expected
from .frontend import _Offsets, normalize_source
from .oracle_blocks import IMPLICIT_ENTRY_NAMES
from .oracle_purity import primitive_literal_result, pure_imported_calls
from .snapshot_context import inert_test_execution_context
from checkwash.ir.astutil import stable_dump

_RESERVED = IMPLICIT_ENTRY_NAMES | {'setUpModule', 'tearDownModule', 'setUpClass', 'tearDownClass',
                                  'setUp', 'tearDown', 'len', 'pytest', 'pytestmark', 'pytest_plugins'}


def _string(node):
    return isinstance(node, ast.Constant) and type(node.value) is str and len(node.value) <= 4096


def _assignment(node):
    return (node.targets[0].id if isinstance(node, ast.Assign) and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name) else None)


def _keys(node):
    if (not isinstance(node, ast.Dict) or not 0 < len(node.keys) <= 16
            or not all(_string(key) for key in node.keys)):
        return None
    keys = [key.value for key in node.keys]
    return set(keys) if len(keys) == len(set(keys)) else None


def _module(source, after):
    tree = _tree(source)
    if tree is None:
        return None
    body = [node for node in tree.body if not (isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant) and type(node.value.value) is str)]
    if not body or not isinstance(body[0], ast.ImportFrom):
        return None
    imported, functions = body[0], body[1:]
    if (imported.level or not imported.module or len(imported.names) != 1 or imported.names[0].name == '*'
            or not 1 <= len(functions) <= 17 or any(not isinstance(node, ast.FunctionDef)
                or node.decorator_list or _parameters(node) is None for node in functions)):
        return None
    provider = imported.names[0].asname or imported.names[0].name
    names = [provider, *(function.name for function in functions)]
    if (len(names) != len(set(names)) or any(name in _RESERVED or name.startswith(('__', 'pytest_')) for name in names)):
        return None
    helper = functions[0] if after else None
    tests = functions[1:] if after else functions
    if (not tests or any(not node.name.startswith('test') or _parameters(node) != [] for node in tests)
            or after and (helper.name.startswith('test') or len(_parameters(helper)) != 1)):
        return None
    return imported, provider, {node.name: node for node in tests}, helper, set(names)


def _capture(statement, provider, occupied):
    name = _assignment(statement)
    call = statement.value if name is not None else None
    if (name is None or name in occupied or name in _RESERVED or name.startswith('__')
            or not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name) or call.func.id != provider
            or call.keywords or len(call.args) != 1 or not _string(call.args[0])):
        return None
    return name, call


def _helper_answer(helper, argument, occupied):
    parameter = _parameters(helper)[0]
    if (parameter in occupied | _RESERVED or len(helper.body) != 2
            or not isinstance(helper.body[1], ast.Return)):
        return None
    assignment, returned = helper.body
    parts = _assignment(assignment)
    call = assignment.value if parts is not None else None
    if (parts is None or parts in occupied | _RESERVED | {parameter} or parts.startswith('__')
            or not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute) or call.func.attr != 'split'
            or not isinstance(call.func.value, ast.Name) or call.func.value.id != parameter or call.args or call.keywords
            or _keys(returned.value) is None):
        return None
    words = argument.value.split()
    if len(words) > 64:
        return None
    binding = ast.Tuple(elts=[ast.Constant(value=word) for word in words], ctx=ast.Load())

    class Substitute(ast.NodeTransformer):
        def visit_Name(self, node):
            return copy.deepcopy(binding) if node.id == parts else node

    values = {}
    for key, value in zip(returned.value.keys, returned.value.values):
        if any(isinstance(node, ast.Name) and node.id not in {parts, 'len'} for node in ast.walk(value)):
            return None
        folded = folded_expected(Substitute().visit(copy.deepcopy(value)), lambda name: name == 'len')
        if not _string(folded):
            return None
        values[key.value] = folded
    return values


def _dictionary_result(source, target, call, keys):
    if not primitive_literal_result(source, target, call):
        return False
    tree = _tree(source)
    function = next((node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == target), None)
    return (function is not None and isinstance(function.body[-1], ast.Return)
            and all(_keys(node.value) == keys for node in ast.walk(function) if isinstance(node, ast.Return)))


def dictionary_helper_events(path, before, after, reader):
    from .table_oracles import _pytest_unshadowed
    if (not before or not after or b'.split(' not in after
            or any(p != path and old != new for p, (old, new) in reader.raw.items())):
        return []
    try:
        old, new = _module(before, False), _module(after, True)
        if old is None or new is None or stable_dump(old[0]) != stable_dump(new[0]) or old[2].keys() != new[2].keys():
            return []
        rows, changes = [], []
        for name, original in old[2].items():
            edited = new[2][name]
            if not 2 <= len(original.body) <= 17 or len(edited.body) != 3:
                return []
            previous = _capture(original.body[0], old[1], old[4])
            current = _capture(edited.body[0], new[1], new[4])
            if previous is None or current is None or stable_dump(previous[1]) != stable_dump(current[1]):
                return []
            fields = {}
            for statement in original.body[1:]:
                if (not isinstance(statement, ast.Assert) or statement.msg is not None
                        or not isinstance(statement.test, ast.Compare) or len(statement.test.ops) != 1
                        or not isinstance(statement.test.ops[0], ast.Eq) or not _string(statement.test.comparators[0])):
                    return []
                field = statement.test.left
                if (not isinstance(field, ast.Subscript) or not isinstance(field.value, ast.Name)
                        or field.value.id != previous[0] or not _string(field.slice) or field.slice.value in fields):
                    return []
                fields[field.slice.value] = statement
            expectation, check = edited.body[1:]
            expected_name = _assignment(expectation)
            expected_call = expectation.value if expected_name is not None else None
            if (expected_name is None or expected_name in new[4] | _RESERVED | {current[0]}
                    or expected_name.startswith('__') or not isinstance(expected_call, ast.Call)
                    or not isinstance(expected_call.func, ast.Name) or expected_call.func.id != new[3].name
                    or expected_call.keywords or len(expected_call.args) != 1
                    or stable_dump(expected_call.args[0]) != stable_dump(current[1].args[0])
                    or not isinstance(check, ast.Assert) or check.msg is not None
                    or not isinstance(check.test, ast.Compare) or len(check.test.ops) != 1
                    or not isinstance(check.test.ops[0], ast.Eq) or not isinstance(check.test.left, ast.Name)
                    or check.test.left.id != current[0] or not isinstance(check.test.comparators[0], ast.Name)
                    or check.test.comparators[0].id != expected_name):
                return []
            answers = _helper_answer(new[3], expected_call.args[0], new[4])
            if answers is None or answers.keys() != fields.keys():
                return []
            rows.append((previous[1], set(fields)))
            for key, statement in fields.items():
                if statement.test.comparators[0].value != answers[key].value:
                    subject = ast.Subscript(value=copy.deepcopy(previous[1]), slice=ast.Constant(value=key), ctx=ast.Load())
                    changes.append((name, statement, check, subject, statement.test.comparators[0], answers[key]))
                    if len(changes) > 128:
                        return []
        if not changes:
            return []
        for side, source in enumerate((before, after)):
            read = lambda candidate, side=side: reader.source(candidate, side, authority=True)
            search = lambda needles, side=side: reader.search(needles, side)
            if not inert_test_execution_context(path, read, search) or not _pytest_unshadowed(path, read):
                return []
            for call, keys in rows:
                if not pure_imported_calls(source, [call], path=path, read=read,
                        result_proof=lambda data, target, call: _dictionary_result(data, target, call, keys)):
                    return []
        offsets = [_Offsets(normalize_source(source)) for source in (before, after)]
        return [(name, offsets[0].seg(previous), offsets[0].span(previous), offsets[1].seg(current), offsets[1].span(current),
                 ast.unparse(subject), 'Eq', ast.unparse(wanted), ast.unparse(got))
                for name, previous, current, subject, wanted, got in changes]
    except (SyntaxError, ValueError, TypeError, AttributeError, RecursionError, MemoryError):
        return []

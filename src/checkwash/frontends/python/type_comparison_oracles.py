"""Classify closed builtin type comparisons without changing their predicate.

An exact comparison of two runtime types constrains shape, not the values.
Only primitive imported calls and completely accounted local test/helper
bodies establish that ``type`` is the builtin and cannot invoke custom type
equality. Unknown bindings or executable startup content retain ordinary IR.
"""
from __future__ import annotations

import ast
from dataclasses import replace

from .frontend import _Offsets, normalize_source
from .oracle_blocks import IMPLICIT_ENTRY_NAMES
from .oracle_purity import primitive_literal_result, pure_imported_calls
from .snapshot_context import inert_test_execution_context
from .table_oracles import _args, _bounded_tree, _context_snapshots, _literal, _pytest_unshadowed
from checkwash.ir import strength as S

_RESERVED = IMPLICIT_ENTRY_NAMES | {'type', 'self', 'pytestmark', 'pytest_plugins'}


def _safe(name):
    return name not in _RESERVED and not name.startswith(('__', 'pytest_'))


def _body(node):
    return [item for item in node.body if not (
        isinstance(item, ast.Expr) and isinstance(item.value, ast.Constant)
        and type(item.value.value) is str)]


def _comparison(node):
    return (isinstance(node, ast.Assert) and node.msg is None
            and isinstance(node.test, ast.Compare) and len(node.test.ops) == 1
            and isinstance(node.test.ops[0], (ast.Eq, ast.NotEq, ast.Is, ast.IsNot)))


def _typed(node):
    if not _comparison(node):
        return None
    operands = [node.test.left, node.test.comparators[0]]
    if not all(isinstance(item, ast.Call) and isinstance(item.func, ast.Name)
               and item.func.id == 'type' and len(item.args) == 1 and not item.keywords
               for item in operands):
        return None
    return [item.args[0] for item in operands]


def _module(source):
    tree = _bounded_tree(source)
    if tree is None:
        return None
    imports, helpers, functions, classes, occupied = {}, {}, [], set(), set()
    for node in _body(tree):
        if isinstance(node, ast.ImportFrom) and not node.level and node.module:
            if node.module == 'pytest' or any(alias.name == '*' for alias in node.names):
                return None
            names = [alias.asname or alias.name for alias in node.names]
            imports.update((name, node) for name in names)
        elif isinstance(node, ast.FunctionDef) and not node.decorator_list:
            names = [node.name]
            arguments = _args(node)
            if node.name.startswith('test'):
                if arguments != []:
                    return None
                functions.append(node)
            else:
                body = _body(node)
                if (arguments is None or len(arguments) != 2 or len(set(arguments)) != 2
                        or not all(_safe(name) for name in arguments)
                        or len(body) != 1 or not _comparison(body[0])):
                    return None
                operands = _typed(body[0])
                shaped = operands is not None
                if not shaped:
                    operands = [body[0].test.left, body[0].test.comparators[0]]
                if [item.id if isinstance(item, ast.Name) else None for item in operands] != arguments:
                    return None
                helpers[node.name] = (body[0], shaped)
        elif isinstance(node, ast.ClassDef):
            names = [node.name]
            if (node.decorator_list or node.keywords or getattr(node, 'type_params', ())
                    or len(node.bases) > 1 or any(not isinstance(base, ast.Name)
                                                or base.id not in classes for base in node.bases)):
                return None
            methods = set()
            for method in _body(node):
                if isinstance(method, ast.Pass):
                    continue
                if (not isinstance(method, ast.FunctionDef) or method.decorator_list
                        or not method.name.startswith('test') or not _safe(method.name)
                        or _args(method) != ['self'] or method.name in methods):
                    return None
                methods.add(method.name)
                functions.append(method)
            classes.add(node.name)
        else:
            return None
        if len(names) != len(set(names)) or occupied.intersection(names) or not all(_safe(name) for name in names):
            return None
        occupied.update(names)
    calls, shapes, used = [], [], set()

    def arguments(actual, expected):
        if (not isinstance(actual, ast.Call) or not isinstance(actual.func, ast.Name)
                or actual.func.id not in imports or not all(_literal(arg) for arg in actual.args)
                or len({kw.arg for kw in actual.keywords}) != len(actual.keywords)
                or not all(kw.arg is not None and _literal(kw.value) for kw in actual.keywords)
                or not _literal(expected)):
            return False
        try:
            ast.literal_eval(expected)
        except (ValueError, TypeError):
            return False
        calls.append(actual)
        used.add(actual.func.id)
        return True

    for function in functions:
        if not _body(function):
            return None
        for statement in _body(function):
            if isinstance(statement, ast.Assert):
                if isinstance(statement.test, ast.Constant) and statement.test.value is True and statement.msg is None:
                    continue
                if not _comparison(statement):
                    return None
                operands = _typed(statement)
                if operands is not None:
                    shapes.append(statement)
                else:
                    operands = [statement.test.left, statement.test.comparators[0]]
                if not arguments(*operands):
                    return None
            elif (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call)
                  and isinstance(statement.value.func, ast.Name) and statement.value.func.id in helpers):
                call = statement.value
                if call.keywords or len(call.args) != 2 or not arguments(*call.args):
                    return None
                assertion, shaped = helpers[call.func.id]
                if shaped:
                    shapes.append(assertion)
            else:
                return None
    if not calls or used != set(imports):
        return None
    return calls, shapes


def mark_type_comparisons(before, after, before_parsed, after_parsed, *, path,
                          root_reader=None, root_searcher=None, changes=()):
    if (root_reader is None or root_searcher is None or b'type' not in before + after
            or not before_parsed.parse_ok or not after_parsed.parse_ok):
        return before_parsed, after_parsed
    try:
        modules = [_module(source) for source in (before, after)]
        if any(module is None for module in modules) or not any(module[1] for module in modules):
            return before_parsed, after_parsed
        for source, module, (read, search) in zip((before, after), modules, _context_snapshots(
                path, before, after, tuple(changes), root_reader, root_searcher)):
            if (not inert_test_execution_context(path, read, search) or not _pytest_unshadowed(path, read)
                    or not pure_imported_calls(source, module[0], path=path, read=read,
                                               result_proof=primitive_literal_result)):
                return before_parsed, after_parsed
        result = []
        for source, module, parsed in zip((before, after), modules, (before_parsed, after_parsed)):
            offsets = _Offsets(normalize_source(source))
            spans = {offsets.span(node) for node in module[1]}
            units = [replace(unit, side=replace(unit.side, assertions=[
                replace(assertion, form='type_shape', strength=S.TYPE_SHAPE)
                if assertion.span in spans else assertion for assertion in unit.side.assertions
            ])) for unit in parsed.units]
            result.append(replace(parsed, units=units))
        return tuple(result)
    except (SyntaxError, ValueError, TypeError, AttributeError, RecursionError, MemoryError):
        return before_parsed, after_parsed

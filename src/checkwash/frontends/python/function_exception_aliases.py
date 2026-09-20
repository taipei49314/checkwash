"""Retain builtin exception alias catchers in a complete plain test inventory.

Every test keeps its sole original concrete assertion. Afterward it may remain
direct, be wrapped by the known catcher, or sit under an inert empty-length
guard. Only catcher evidence is added; this does not remove guarded assertions.
"""
from __future__ import annotations

import ast
from dataclasses import replace

from .class_exception_aliases import _EXCEPTIONS, _name
from .empty_length_guards import _empty_length
from .frontend import _Offsets, _norm, normalize_source
from .neutralizing_aliases import _assertion
from .oracle_purity import primitive_literal_result, pure_imported_calls
from .snapshot_context import inert_test_execution_context
from .table_oracles import _args, _bounded_tree, _context_snapshots, _pytest_unshadowed
from checkwash.ir.astutil import stable_dump


def _module(source, *, after):
    tree = _bounded_tree(source)
    if tree is None:
        return None
    body = [node for node in tree.body if not (
        isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
        and type(node.value.value) is str)]
    if len(body) < (4 if after else 2):
        return None
    imported = body[0]
    if (not isinstance(imported, ast.ImportFrom) or imported.level or not imported.module
            or imported.module == 'pytest' or len(imported.names) != 1
            or imported.names[0].name == '*'):
        return None
    provider = imported.names[0].asname or imported.names[0].name
    if provider.startswith('test'):
        return None
    names = [provider]
    functions = body[1:]
    framework = exception = None
    if after:
        module, alias = body[1:3]
        if (not isinstance(module, ast.Import) or len(module.names) != 1 or module.names[0].name != 'pytest'
                or not isinstance(alias, ast.Assign) or len(alias.targets) != 1
                or not isinstance(alias.targets[0], ast.Name) or not isinstance(alias.value, ast.Name)
                or alias.value.id not in _EXCEPTIONS):
            return None
        framework = module.names[0].asname or module.names[0].name
        exception = alias.targets[0].id
        names += [framework, exception]
        functions = body[3:]
    if not 1 <= len(functions) <= 64:
        return None
    identities, calls, contexts = [], [], []
    for function in functions:
        if (not isinstance(function, ast.FunctionDef) or not function.name.startswith('test')
                or function.decorator_list or _args(function) != [] or len(function.body) != 1):
            return None
        names.append(function.name)
        statement = function.body[0]
        if after and isinstance(statement, ast.With):
            if (len(statement.items) != 1 or statement.items[0].optional_vars is not None
                    or len(statement.body) != 1):
                return None
            context = statement.items[0].context_expr
            if (not isinstance(context, ast.Call) or context.keywords or len(context.args) != 1
                    or not isinstance(context.args[0], ast.Name) or context.args[0].id != exception
                    or not isinstance(context.func, ast.Attribute) or context.func.attr != 'raises'
                    or not isinstance(context.func.value, ast.Name) or context.func.value.id != framework):
                return None
            contexts.append(context)
            statement = statement.body[0]
        elif after and isinstance(statement, ast.If):
            if statement.orelse or len(statement.body) != 1 or not _empty_length(statement.test):
                return None
            statement = statement.body[0]
        call = _assertion(statement, provider)
        if call is None:
            return None
        try:
            ast.literal_eval(statement.test.comparators[0])
        except (ValueError, TypeError):
            return None
        identities.append((function.name, stable_dump(statement)))
        calls.append(call)
    if len(set(names)) != len(names) or any(name == 'len' or not _name(name) for name in names):
        return None
    return (stable_dump(imported), identities), calls, contexts


def mark_function_exception_aliases(before, after, before_parsed, after_parsed, *, path,
                                    root_reader=None, root_searcher=None, changes=()):
    if (root_reader is None or root_searcher is None or b'raises' not in after
            or not before_parsed.parse_ok or not after_parsed.parse_ok):
        return before_parsed, after_parsed
    try:
        old, new = _module(before, after=False), _module(after, after=True)
        if old is None or new is None or not new[2] or old[0] != new[0]:
            return before_parsed, after_parsed
        for source, module, (read, search) in zip((before, after), (old, new), _context_snapshots(
                path, before, after, tuple(changes), root_reader, root_searcher)):
            if (not inert_test_execution_context(path, read, search) or not _pytest_unshadowed(path, read)
                    or not pure_imported_calls(source, module[1], path=path, read=read,
                                               result_proof=primitive_literal_result)):
                return before_parsed, after_parsed
        offsets = _Offsets(normalize_source(after))
        added = [_norm(offsets.seg(context).split('\n')[0]) for context in new[2]]
        return before_parsed, replace(after_parsed,
            broad_handlers=tuple(sorted([*after_parsed.broad_handlers, *added])),
            swallowing_handlers=tuple(sorted([*after_parsed.swallowing_handlers, *added])))
    except (SyntaxError, ValueError, TypeError, AttributeError, RecursionError, MemoryError):
        return before_parsed, after_parsed

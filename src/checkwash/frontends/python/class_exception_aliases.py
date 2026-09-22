"""Assertion catchers behind a builtin exception alias in a closed test class.

Only the default class, a literal true flag and its sole ordinary test method
are admitted. This adds existing handler evidence without rewriting assertions
or treating arbitrary class attributes as execution facts.
"""
from __future__ import annotations

import ast
from dataclasses import replace

from .empty_parameter_sets import _standard_unshadowed
from .frontend import _Offsets, _norm, normalize_source
from .neutralizing_aliases import _assertion
from .oracle_blocks import IMPLICIT_ENTRY_NAMES
from .oracle_purity import primitive_literal_result, pure_imported_calls
from .snapshot_context import inert_test_execution_context
from .table_oracles import _args, _bounded_tree, _context_snapshots
from checkwash.ir.astutil import stable_dump

_EXCEPTIONS = {'AssertionError', 'Exception', 'BaseException'}
_RESERVED = IMPLICIT_ENTRY_NAMES | _EXCEPTIONS | {'type', 'self', 'pytestmark', 'pytest_plugins'}


def _name(name):
    return name not in _RESERVED and not name.startswith(('__', 'pytest_'))


def _module(source, *, after):
    tree = _bounded_tree(source)
    if tree is None:
        return None
    body = [node for node in tree.body if not (
        isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
        and type(node.value.value) is str)]
    if len(body) != (4 if after else 2):
        return None
    imported, cls = body[0], body[-1]
    if (not isinstance(imported, ast.ImportFrom) or imported.level or not imported.module
            or imported.module == 'pytest' or len(imported.names) != 1
            or imported.names[0].name == '*'):
        return None
    provider = imported.names[0].asname or imported.names[0].name
    if (not isinstance(cls, ast.ClassDef) or not cls.name.startswith('Test')
            or cls.bases or cls.keywords or cls.decorator_list or getattr(cls, 'type_params', ())
            or len(cls.body) != 2):
        return None
    flag, method = cls.body
    if (not isinstance(flag, ast.Assign) or len(flag.targets) != 1
            or not isinstance(flag.targets[0], ast.Name)
            or not isinstance(flag.value, ast.Constant) or flag.value.value is not True
            or not isinstance(method, ast.FunctionDef) or not method.name.startswith('test')
            or method.decorator_list or getattr(method, 'type_params', ())
            or _args(method) != ['self'] or len(method.body) != 1):
        return None
    names = [provider, cls.name, flag.targets[0].id, method.name]
    guard = method.body[0]
    if (not isinstance(guard, ast.If) or guard.orelse or len(guard.body) != 1
            or not isinstance(guard.test, ast.Attribute) or guard.test.attr != flag.targets[0].id):
        return None
    dispatch = guard.test.value
    if (not isinstance(dispatch, ast.Call) or not isinstance(dispatch.func, ast.Name)
            or dispatch.func.id != 'type' or dispatch.keywords or len(dispatch.args) != 1
            or not isinstance(dispatch.args[0], ast.Name) or dispatch.args[0].id != 'self'):
        return None
    context = None
    statement = guard.body[0]
    if after:
        module, alias = body[1:3]
        if (not isinstance(module, ast.Import) or len(module.names) != 1
                or module.names[0].name != 'pytest'
                or not isinstance(alias, ast.Assign) or len(alias.targets) != 1
                or not isinstance(alias.targets[0], ast.Name) or not isinstance(alias.value, ast.Name)
                or alias.value.id not in _EXCEPTIONS):
            return None
        framework = module.names[0].asname or module.names[0].name
        exception = alias.targets[0].id
        names += [framework, exception]
        if (not isinstance(statement, ast.With) or len(statement.items) != 1
                or statement.items[0].optional_vars is not None or len(statement.body) != 1):
            return None
        context = statement.items[0].context_expr
        if (not isinstance(context, ast.Call) or context.keywords or len(context.args) != 1
                or not isinstance(context.args[0], ast.Name) or context.args[0].id != exception
                or not isinstance(context.func, ast.Attribute) or context.func.attr != 'raises'
                or not isinstance(context.func.value, ast.Name) or context.func.value.id != framework):
            return None
        statement = statement.body[0]
    if len(set(names)) != len(names) or any(not _name(name) for name in names):
        return None
    call = _assertion(statement, provider)
    if call is None:
        return None
    # A literal expected container must itself be constructible before it can
    # support the claimed assertion; AST literal syntax alone permits bad keys.
    try:
        ast.literal_eval(statement.test.comparators[0])
    except (ValueError, TypeError):
        return None
    identity = (stable_dump(imported), cls.name, stable_dump(flag), method.name,
                stable_dump(method.args), stable_dump(guard.test), stable_dump(statement))
    return identity, call, context


def mark_class_exception_aliases(before, after, before_parsed, after_parsed, *, path,
                                 root_reader=None, root_searcher=None, changes=()):
    if (root_reader is None or root_searcher is None or b'raises' not in after
            or b'class ' not in before or not before_parsed.parse_ok or not after_parsed.parse_ok):
        return before_parsed, after_parsed
    try:
        old, new = _module(before, after=False), _module(after, after=True)
        if old is None or new is None or old[0] != new[0]:
            return before_parsed, after_parsed
        for source, module, (read, search) in zip((before, after), (old, new), _context_snapshots(
                path, before, after, tuple(changes), root_reader, root_searcher)):
            if (not inert_test_execution_context(path, read, search)
                    or not _standard_unshadowed({'pytest'}, path, read)
                    or not pure_imported_calls(source, [module[1]], path=path, read=read,
                                               result_proof=primitive_literal_result)):
                return before_parsed, after_parsed
        context = _norm(_Offsets(normalize_source(after)).seg(new[2]).split('\n')[0])
        return before_parsed, replace(after_parsed,
            broad_handlers=tuple(sorted([*after_parsed.broad_handlers, context])),
            swallowing_handlers=tuple(sorted([*after_parsed.swallowing_handlers, context])))
    except (SyntaxError, ValueError, TypeError, AttributeError, RecursionError, MemoryError):
        return before_parsed, after_parsed

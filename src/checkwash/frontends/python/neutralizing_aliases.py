"""Retain newly introduced assertion catchers behind closed module aliases.

This supplies ordinary swallowing-handler evidence only. The old assertions
must remain byte-independent AST equivalents, and every import and executed
call must have closed source authority before an alias is treated as a catcher.
"""
from __future__ import annotations

import ast
from dataclasses import replace

from .empty_parameter_sets import _standard_unshadowed
from .frontend import _Offsets, _norm, normalize_source
from .oracle_blocks import IMPLICIT_ENTRY_NAMES
from .oracle_purity import primitive_literal_result, pure_imported_calls
from .snapshot_context import inert_test_execution_context
from .table_oracles import _args, _bounded_tree, _context_snapshots
from checkwash.ir.astutil import stable_dump

_MODULES = {'pytest': 'raises', 'contextlib': 'suppress'}
_EXCEPTIONS = {'AssertionError', 'Exception', 'BaseException', 'ValueError', 'TypeError', 'RuntimeError'}
_BROAD = {'AssertionError', 'Exception', 'BaseException'}
_RESERVED = IMPLICIT_ENTRY_NAMES | _EXCEPTIONS | {'pytestmark', 'pytest_plugins'}


def _literal(node):
    if isinstance(node, ast.Constant):
        return type(node.value) in (type(None), bool, int, float, str, bytes)
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return all(_literal(item) for item in node.elts)
    if isinstance(node, ast.Dict):
        return all(key is not None and _literal(key) and _literal(value)
                   for key, value in zip(node.keys, node.values))
    return (isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub))
            and isinstance(node.operand, ast.Constant) and type(node.operand.value) in (int, float))


def _assertion(node, provider):
    if (not isinstance(node, ast.Assert) or node.msg is not None
            or not isinstance(node.test, ast.Compare) or len(node.test.ops) != 1
            or not isinstance(node.test.ops[0], (ast.Eq, ast.Is))
            or not _literal(node.test.comparators[0])):
        return None
    call = node.test.left
    if (not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name) or call.func.id != provider
            or not all(_literal(arg) for arg in call.args)
            or len({keyword.arg for keyword in call.keywords}) != len(call.keywords)
            or not all(keyword.arg is not None and _literal(keyword.value) for keyword in call.keywords)):
        return None
    return call


def _catcher(call, aliases):
    if (not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name)
            or call.func.id not in aliases or call.keywords or not call.args):
        return False
    kind = aliases[call.func.id]
    if kind == 'raises' and len(call.args) != 1:
        return False
    types = []
    for arg in call.args:
        items = arg.elts if isinstance(arg, ast.Tuple) else [arg]
        if not items or any(not isinstance(item, ast.Name) or item.id not in _EXCEPTIONS for item in items):
            return False
        types.extend(item.id for item in items)
    return bool(_BROAD.intersection(types))


def _module(source, *, after):
    tree = _bounded_tree(source)
    if tree is None:
        return None
    occupied, modules, direct, aliases, standard = set(), {}, {}, {}, set()
    imported, test = None, None
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and type(node.value.value) is str:
            continue
        if test is not None:
            return None
        if (isinstance(node, ast.Import) and len(node.names) == 1
                and node.names[0].name in _MODULES):
            alias = node.names[0]
            name = alias.asname or alias.name
            modules[name] = alias.name
            standard.add(alias.name)
        elif (isinstance(node, ast.ImportFrom) and not node.level and node.module
              and len(node.names) == 1 and node.names[0].name != '*'):
            alias = node.names[0]
            name = alias.asname or alias.name
            if node.module in _MODULES and alias.name == _MODULES[node.module]:
                direct[name] = alias.name
                standard.add(node.module)
            elif imported is None and node.module not in _MODULES:
                imported = node
            else:
                return None
        elif (after and isinstance(node, ast.Assign) and len(node.targets) == 1
              and isinstance(node.targets[0], ast.Name)):
            name, value = node.targets[0].id, node.value
            if isinstance(value, ast.Name) and value.id in direct | aliases:
                aliases[name] = (direct | aliases)[value.id]
            elif (isinstance(value, ast.Attribute) and isinstance(value.value, ast.Name)
                  and value.value.id in modules and value.attr == _MODULES[modules[value.value.id]]):
                aliases[name] = value.attr
            else:
                return None
        elif (isinstance(node, ast.FunctionDef) and node.name.startswith('test')
              and not node.decorator_list and _args(node) == []):
            test, name = node, node.name
        else:
            return None
        if name in occupied or name in _RESERVED or name.startswith(('__', 'pytest_')):
            return None
        occupied.add(name)
    if imported is None or test is None or len(test.body) > 64:
        return None
    provider = imported.names[0].asname or imported.names[0].name
    assertions, calls, contexts = [], [], []
    for statement in test.body:
        if after and isinstance(statement, ast.With):
            if (len(statement.items) != 1 or statement.items[0].optional_vars is not None
                    or not _catcher(statement.items[0].context_expr, aliases)):
                return None
            contexts.append(statement.items[0].context_expr)
            body = statement.body
        else:
            body = [statement]
        for item in body:
            call = _assertion(item, provider)
            if call is None:
                return None
            assertions.append(item)
            calls.append(call)
    return imported, test, assertions, calls, contexts, standard


def mark_neutralizing_aliases(before, after, before_parsed, after_parsed, *, path,
                             root_reader=None, root_searcher=None, changes=()):
    if (root_reader is None or root_searcher is None or b'with ' not in after
            or not before_parsed.parse_ok or not after_parsed.parse_ok):
        return before_parsed, after_parsed
    try:
        old, new = _module(before, after=False), _module(after, after=True)
        if (old is None or new is None or not new[4] or old[1].name != new[1].name
                or stable_dump(old[0]) != stable_dump(new[0])
                or [stable_dump(node) for node in old[2]] != [stable_dump(node) for node in new[2]]):
            return before_parsed, after_parsed
        for source, module, (read, search) in zip((before, after), (old, new), _context_snapshots(
                path, before, after, tuple(changes), root_reader, root_searcher)):
            if (not inert_test_execution_context(path, read, search)
                    or not _standard_unshadowed(module[5], path, read)
                    or not pure_imported_calls(source, module[3], path=path, read=read,
                                               result_proof=primitive_literal_result)):
                return before_parsed, after_parsed
        text = _Offsets(normalize_source(after))
        added = [_norm(text.seg(context).split('\n')[0]) for context in new[4]]
        return before_parsed, replace(after_parsed,
            broad_handlers=tuple(sorted([*after_parsed.broad_handlers, *added])),
            swallowing_handlers=tuple(sorted([*after_parsed.swallowing_handlers, *added])))
    except (SyntaxError, ValueError, TypeError, AttributeError, RecursionError, MemoryError):
        return before_parsed, after_parsed

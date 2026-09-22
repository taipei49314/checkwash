"""Known-false builtin lengths cannot keep a wrapped assertion executable.

Only an introduction around the exact prior direct assertions is considered.
The complete source and startup inventory establish builtin authority; no
environment or interpreter-version predicate is assigned a truth value here.
"""
from __future__ import annotations

import ast
from dataclasses import replace

from .frontend import _Offsets, normalize_source
from .neutralizing_aliases import _assertion
from .oracle_blocks import IMPLICIT_ENTRY_NAMES
from .oracle_purity import primitive_literal_result, pure_imported_calls
from .snapshot_context import inert_test_execution_context
from .table_oracles import _args, _bounded_tree, _context_snapshots, _pytest_unshadowed
from checkwash.ir.astutil import stable_dump


def _empty_length(node):
    if (not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != 'len'
            or len(node.args) != 1 or node.keywords):
        return False
    value = node.args[0]
    if isinstance(value, (ast.List, ast.Tuple)):
        return not value.elts
    if isinstance(value, ast.Dict):
        return not value.keys
    return isinstance(value, ast.Constant) and type(value.value) in (str, bytes) and not value.value


def _module(source, *, after):
    tree = _bounded_tree(source)
    if tree is None:
        return None
    body = [node for node in tree.body if not (isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant) and type(node.value.value) is str)]
    if (len(body) != 2 or not isinstance(body[0], ast.ImportFrom) or body[0].level
            or not body[0].module or len(body[0].names) != 1 or body[0].names[0].name == '*'):
        return None
    imported, test = body
    provider = imported.names[0].asname or imported.names[0].name
    if (provider in IMPLICIT_ENTRY_NAMES | {'len', 'pytestmark', 'pytest_plugins'}
            or provider.startswith(('test', '__', 'pytest_'))
            or not isinstance(test, ast.FunctionDef) or not test.name.startswith('test')
            or test.name == provider or test.decorator_list or _args(test) != []
            or not 0 < len(test.body) <= 64):
        return None
    assertions, calls, dead = [], [], []
    for statement in test.body:
        guarded = after and isinstance(statement, ast.If)
        if guarded:
            if statement.orelse or not _empty_length(statement.test):
                return None
            statements = statement.body
        else:
            statements = [statement]
        for assertion in statements:
            call = _assertion(assertion, provider)
            if call is None:
                return None
            assertions.append(assertion)
            calls.append(call)
            if guarded:
                dead.append(assertion)
    return imported, test, assertions, calls, dead


def mark_empty_length_guards(before, after, before_parsed, after_parsed, *, path,
                             root_reader=None, root_searcher=None, changes=()):
    if (root_reader is None or root_searcher is None or b'len' not in after
            or not before_parsed.parse_ok or not after_parsed.parse_ok):
        return before_parsed, after_parsed
    try:
        old, new = _module(before, after=False), _module(after, after=True)
        if (old is None or new is None or not new[4] or old[1].name != new[1].name
                or stable_dump(old[0]) != stable_dump(new[0])
                or [stable_dump(node) for node in old[2]] != [stable_dump(node) for node in new[2]]):
            return before_parsed, after_parsed
        text = _Offsets(normalize_source(after))
        expected_spans = [text.span(node) for node in new[2]]
        if (len(after_parsed.units) != 1 or after_parsed.units[0].qualname != new[1].name
                or [node.span for node in after_parsed.units[0].side.assertions] != expected_spans):
            return before_parsed, after_parsed
        for source, module, (read, search) in zip((before, after), (old, new), _context_snapshots(
                path, before, after, tuple(changes), root_reader, root_searcher)):
            if (not inert_test_execution_context(path, read, search)
                    or not _pytest_unshadowed(path, read)
                    or not pure_imported_calls(source, module[3], path=path, read=read,
                                               result_proof=primitive_literal_result)):
                return before_parsed, after_parsed
        dead_spans = {text.span(node) for node in new[4]}
        unit = after_parsed.units[0]
        assertions = [node for node in unit.side.assertions if node.span not in dead_spans]
        assertions = [replace(node, id=f'a{index}') for index, node in enumerate(assertions)]
        return before_parsed, replace(after_parsed, units=[replace(unit, side=replace(unit.side, assertions=assertions))])
    except (SyntaxError, ValueError, TypeError, AttributeError, RecursionError, MemoryError):
        return before_parsed, after_parsed

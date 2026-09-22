"""Closed primitive normalizations that erase an exact value comparison.

An empty prefix of a builtin string and the positivity of a builtin repr's
length are constant on primitive values. Validate their unwrapped calls with
the complete type-comparison inventory, then classify the original assertions.
The inventory is private proof data; actual predicates, spans and calls stay.
"""
from __future__ import annotations

import ast
from dataclasses import replace

from .closed_class_flag_oracles import unwrap_closed_class_flag
from .frontend import _Offsets, normalize_source
from .oracle_purity import primitive_literal_result, pure_imported_calls
from .snapshot_context import inert_test_execution_context
from .table_oracles import _bounded_tree, _context_snapshots, _module_unshadowed, _pytest_unshadowed
from .type_comparison_oracles import _module_tree
from checkwash.ir import strength as S

_BUILTINS = {'str', 'repr', 'len'}


def _argument(node, name):
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == name
            and len(node.args) == 1 and not node.keywords):
        return node.args[0]
    return None


def _zero(node):
    return isinstance(node, ast.Constant) and type(node.value) is int and node.value == 0


def _normalized(node):
    if (isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Slice)
            and node.slice.lower is None and _zero(node.slice.upper) and node.slice.step is None):
        value = _argument(node.value, 'str')
        if value is not None:
            return 'empty-string-prefix', value
    if (isinstance(node, ast.Compare) and len(node.ops) == 1 and isinstance(node.ops[0], ast.Gt)
            and _zero(node.comparators[0])):
        represented = _argument(node.left, 'len')
        value = _argument(represented, 'repr')
        if value is not None:
            return 'nonempty-repr', value
    return None


def _bindings(tree):
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            names.add(node.id)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update(alias.asname or alias.name.split('.')[0] for alias in node.names)
    return names


def _module(source):
    tree = _bounded_tree(source)
    if tree is None or _bindings(tree) & _BUILTINS or not unwrap_closed_class_flag(tree):
        return None
    normalized = []
    for node in ast.walk(tree):
        if (not isinstance(node, ast.Assert) or node.msg is not None
                or not isinstance(node.test, ast.Compare) or len(node.test.ops) != 1
                or not isinstance(node.test.ops[0], ast.Eq)):
            continue
        left, right = _normalized(node.test.left), _normalized(node.test.comparators[0])
        if left is not None and right is not None and left[0] == right[0]:
            normalized.append(node)
            node.test.left, node.test.comparators = left[1], [right[1]]
    inventory = _module_tree(tree)
    return (*inventory, normalized) if inventory is not None else None


def mark_builtin_normalizations(before, after, before_parsed, after_parsed, *, path,
                                root_reader=None, root_searcher=None, changes=()):
    if (root_reader is None or root_searcher is None or not before_parsed.parse_ok or not after_parsed.parse_ok
            or not (b'str' in before + after or b'repr' in before + after)):
        return before_parsed, after_parsed
    try:
        modules = [_module(source) for source in (before, after)]
        if any(module is None for module in modules) or not any(module[2] for module in modules):
            return before_parsed, after_parsed
        for source, module, (read, search) in zip((before, after), modules, _context_snapshots(
                path, before, after, tuple(changes), root_reader, root_searcher)):
            if (not inert_test_execution_context(path, read, search) or not _pytest_unshadowed(path, read)
                    or not _module_unshadowed(path, read, 'builtins')
                    or not pure_imported_calls(source, module[0], path=path, read=read,
                                               result_proof=primitive_literal_result)):
                return before_parsed, after_parsed
        result = []
        for source, module, parsed in zip((before, after), modules, (before_parsed, after_parsed)):
            offsets = _Offsets(normalize_source(source))
            shapes = {offsets.span(node) for node in module[1]}
            constants = {offsets.span(node) for node in module[2]}
            units = [replace(unit, side=replace(unit.side, assertions=[
                replace(assertion, form='tautology', strength=S.TAUTOLOGY, trivial=True)
                if assertion.span in constants else
                replace(assertion, form='type_shape', strength=S.TYPE_SHAPE)
                if assertion.span in shapes else assertion for assertion in unit.side.assertions
            ])) for unit in parsed.units]
            result.append(replace(parsed, units=units))
        return tuple(result)
    except (SyntaxError, ValueError, TypeError, AttributeError, RecursionError, MemoryError, ArithmeticError):
        return before_parsed, after_parsed

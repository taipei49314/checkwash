"""A literal string passed to builtin all cannot consume a stored oracle.

Every character is truthy and the empty string is vacuously true. Retain the
actual assertion and classify only this tautology, under complete builtin,
literal-range, production and startup authority. No generator is evaluated.
"""
from __future__ import annotations

import ast
import copy
from dataclasses import replace

from .expected_constants import folded_expected
from .frontend import _Offsets, normalize_source
from .oracle_blocks import IMPLICIT_ENTRY_NAMES
from .oracle_purity import primitive_literal_result, pure_imported_calls
from .snapshot_context import inert_test_execution_context
from .table_oracles import _args, _bounded_tree, _context_snapshots, _pytest_unshadowed
from checkwash.ir import strength as S
from checkwash.ir.astutil import stable_dump

_RESERVED = IMPLICIT_ENTRY_NAMES | {'all', 'range', 'pytestmark', 'pytest_plugins'}


def _body(node):
    return [item for item in node.body if not (isinstance(item, ast.Expr)
            and isinstance(item.value, ast.Constant) and type(item.value.value) is str)]


def _expected_expression(node, variable):
    """Validate every branch before folding; dead syntax still binds/compiles."""
    if isinstance(node, ast.Constant):
        return type(node.value) in (int, float, bool)
    if isinstance(node, ast.Name):
        return isinstance(node.ctx, ast.Load) and node.id == variable
    if isinstance(node, ast.UnaryOp):
        return isinstance(node.op, (ast.UAdd, ast.USub, ast.Not)) and _expected_expression(node.operand, variable)
    if isinstance(node, ast.BinOp):
        return (isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod))
                and _expected_expression(node.left, variable) and _expected_expression(node.right, variable))
    if isinstance(node, ast.Compare):
        return (all(isinstance(op, (ast.Eq, ast.NotEq, ast.Is, ast.IsNot, ast.Lt, ast.LtE, ast.Gt, ast.GtE))
                    for op in node.ops)
                and all(_expected_expression(item, variable) for item in [node.left, *node.comparators]))
    if isinstance(node, ast.BoolOp):
        return all(_expected_expression(item, variable) for item in node.values)
    if isinstance(node, ast.IfExp):
        return all(_expected_expression(item, variable) for item in (node.test, node.body, node.orelse))
    return False


def _module(source):
    tree = _bounded_tree(source)
    if tree is None or len(_body(tree)) != 2:
        return None
    imported, test = _body(tree)
    if (not isinstance(imported, ast.ImportFrom) or imported.level or not imported.module
            or len(imported.names) != 1 or imported.names[0].name == '*'
            or not isinstance(test, ast.FunctionDef) or not test.name.startswith('test')
            or test.decorator_list or _args(test) != [] or len(_body(test)) != 2):
        return None
    provider = imported.names[0].asname or imported.names[0].name
    assignment, assertion = _body(test)
    if (not isinstance(assignment, ast.Assign) or len(assignment.targets) != 1
            or not isinstance(assignment.targets[0], ast.Name)
            or not isinstance(assignment.value, ast.GeneratorExp)
            or not isinstance(assertion, ast.Assert) or assertion.msg is not None):
        return None
    generator, stored = assignment.value, assignment.targets[0].id
    if len(generator.generators) != 1:
        return None
    loop, comparison = generator.generators[0], generator.elt
    if (loop.is_async or loop.ifs or not isinstance(loop.target, ast.Name)
            or not isinstance(comparison, ast.Compare) or len(comparison.ops) != 1
            or not isinstance(comparison.ops[0], ast.Eq)):
        return None
    # A dead expression can still bind an enclosing local (PEP 572), change
    # generator kind or be compile-invalid. Constant folding must not erase
    # those lexical facts before builtin all/range authority is established.
    if not _expected_expression(comparison.comparators[0], loop.target.id):
        return None
    names = [provider, test.name, stored, loop.target.id]
    if (len(set(names)) != 4 or any(name in _RESERVED or name.startswith(('__', 'pytest_')) for name in names)):
        return None
    call = comparison.left
    if (not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name) or call.func.id != provider
            or call.keywords or len(call.args) != 1 or not isinstance(call.args[0], ast.Name)
            or call.args[0].id != loop.target.id):
        return None
    iterator = loop.iter
    if (not isinstance(iterator, ast.Call) or not isinstance(iterator.func, ast.Name)
            or iterator.func.id != 'range' or iterator.keywords or not 1 <= len(iterator.args) <= 3):
        return None
    values = []
    for argument in iterator.args:
        try:
            value = ast.literal_eval(argument)
        except (ValueError, TypeError):
            return None
        if type(value) not in (int, bool) or abs(value) > 1024:
            return None
        values.append(value)
    rows = range(*values)
    if not 1 <= len(rows) <= 64:
        return None
    calls = []
    for value in rows:
        class Bind(ast.NodeTransformer):
            def visit_Name(self, node):
                return ast.Constant(value=value) if node.id == loop.target.id else node
        expected = folded_expected(Bind().visit(copy.deepcopy(comparison.comparators[0])), lambda _: False)
        if not isinstance(expected, ast.Constant) or type(expected.value) not in (int, float, bool):
            return None
        calls.append(ast.Call(func=copy.deepcopy(call.func), args=[ast.Constant(value=value)], keywords=[]))
    consumed = assertion.test
    if (not isinstance(consumed, ast.Call) or not isinstance(consumed.func, ast.Name)
            or consumed.func.id != 'all' or consumed.keywords or len(consumed.args) != 1):
        return None
    argument = consumed.args[0]
    literal = isinstance(argument, ast.Constant) and type(argument.value) is str
    if not literal and not (isinstance(argument, ast.Name) and argument.id == stored):
        return None
    return imported, test, assertion, calls, literal


def mark_literal_all(before, after, before_parsed, after_parsed, *, path,
                     root_reader=None, root_searcher=None, changes=()):
    if (root_reader is None or root_searcher is None or b'all' not in before + after
            or not before_parsed.parse_ok or not after_parsed.parse_ok):
        return before_parsed, after_parsed
    try:
        modules = [_module(source) for source in (before, after)]
        if (any(module is None for module in modules) or not any(module[4] for module in modules)
                or stable_dump(modules[0][0]) != stable_dump(modules[1][0])
                or modules[0][1].name != modules[1][1].name):
            return before_parsed, after_parsed
        for source, module, (read, search) in zip((before, after), modules, _context_snapshots(
                path, before, after, tuple(changes), root_reader, root_searcher)):
            if (not inert_test_execution_context(path, read, search) or not _pytest_unshadowed(path, read)
                    or not pure_imported_calls(source, module[3], path=path, read=read,
                                               result_proof=primitive_literal_result)):
                return before_parsed, after_parsed
        result = []
        for source, module, parsed in zip((before, after), modules, (before_parsed, after_parsed)):
            span = _Offsets(normalize_source(source)).span(module[2])
            units = [replace(unit, side=replace(unit.side, assertions=[
                replace(assertion, form='tautology', strength=S.TAUTOLOGY, trivial=True)
                if module[4] and assertion.span == span else assertion for assertion in unit.side.assertions
            ])) for unit in parsed.units]
            result.append(replace(parsed, units=units))
        return tuple(result)
    except (SyntaxError, ValueError, TypeError, AttributeError, RecursionError, MemoryError, ArithmeticError):
        return before_parsed, after_parsed

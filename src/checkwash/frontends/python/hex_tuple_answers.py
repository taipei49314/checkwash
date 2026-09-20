"""Resolve a closed hexadecimal tuple helper on literal string inputs.

Only builtin int over slices of a fresh literal string's lstrip result is
admitted. Every returned component is resolved before an indexed answer is
used, retaining errors from any tuple element. The table caller keeps complete
tuple/exception obligations and proves production and startup on both sides.
"""
from __future__ import annotations

import ast
import copy

from .callable_fixture_expectations import _parameters
from .oracle_blocks import IMPLICIT_ENTRY_NAMES
from checkwash.ir.astutil import dotted_name, stable_dump

_RESERVED = IMPLICIT_ENTRY_NAMES | {'int', 'str', 'len', 'pytest', 'ValueError', 'pytestmark', 'pytest_plugins', 'request'}


def _string(node):
    return isinstance(node, ast.Constant) and type(node.value) is str and len(node.value) <= 4096


def _integer(node):
    try:
        value = ast.literal_eval(node)
        return value if type(value) is int and abs(value) <= 4096 else None
    except (ValueError, TypeError):
        return None


def _answer(helper, argument, occupied):
    parameters = _parameters(helper)
    if (parameters is None or len(parameters) != 1 or helper.decorator_list or helper.name.startswith('test')
            or parameters[0] in occupied | _RESERVED or parameters[0].startswith('__') or len(helper.body) != 2):
        return None
    assignment, returned = helper.body
    if (not isinstance(assignment, ast.Assign) or len(assignment.targets) != 1
            or not isinstance(assignment.targets[0], ast.Name) or not isinstance(returned, ast.Return)
            or not isinstance(returned.value, ast.Tuple) or not 1 <= len(returned.value.elts) <= 16):
        return None
    name, strip = assignment.targets[0].id, assignment.value
    if (name in occupied | _RESERVED | set(parameters) or name.startswith('__')
            or not isinstance(strip, ast.Call) or not isinstance(strip.func, ast.Attribute) or strip.func.attr != 'lstrip'
            or not isinstance(strip.func.value, ast.Name) or strip.func.value.id != parameters[0]
            or strip.keywords or len(strip.args) != 1 or not _string(strip.args[0])):
        return None
    text = argument.value.lstrip(strip.args[0].value)
    result = []
    for conversion in returned.value.elts:
        if (not isinstance(conversion, ast.Call) or not isinstance(conversion.func, ast.Name) or conversion.func.id != 'int'
                or conversion.keywords or len(conversion.args) != 2 or not isinstance(conversion.args[1], ast.Constant)
                or type(conversion.args[1].value) is not int or conversion.args[1].value != 16):
            return None
        selected = conversion.args[0]
        if not isinstance(selected, ast.Subscript) or not isinstance(selected.value, ast.Name) or selected.value.id != name:
            return None
        if isinstance(selected.slice, ast.Slice):
            bounds = [_integer(part) if part is not None else None
                      for part in (selected.slice.lower, selected.slice.upper, selected.slice.step)]
            if any(part is not None and value is None for part, value in zip(
                    (selected.slice.lower, selected.slice.upper, selected.slice.step), bounds)):
                return None
            index = slice(*bounds)
        else:
            index = _integer(selected.slice)
            if index is None:
                return None
        try:
            value = text[index]
            if not 0 < len(value) <= 64:
                return None
            result.append(ast.Constant(value=int(value, 16)))
        except (ValueError, IndexError):
            return None
    return result


def _raises(test, provider):
    if len(test.body) != 1 or not isinstance(test.body[0], ast.With):
        return False
    block = test.body[0]
    if len(block.items) != 1 or block.items[0].optional_vars is not None or len(block.body) != 1:
        return False
    context = block.items[0].context_expr
    statement = block.body[0]
    call = statement.value if isinstance(statement, ast.Expr) else None
    return (isinstance(context, ast.Call) and dotted_name(context.func) == 'pytest.raises'
            and not context.keywords and len(context.args) == 1 and dotted_name(context.args[0]) == 'ValueError'
            and isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == provider
            and not call.keywords and len(call.args) == 1 and _string(call.args[0]))


def expand_hex_tuple_answers(tree):
    imported, functions, occupied, pytest = None, [], set(), False
    for node in tree.body:
        if isinstance(node, ast.Expr) and _string(node.value):
            continue
        if (isinstance(node, ast.Import) and not functions and not pytest and len(node.names) == 1
                and node.names[0].name == 'pytest' and node.names[0].asname is None):
            name, pytest = 'pytest', True
        elif (isinstance(node, ast.ImportFrom) and not functions and imported is None and not node.level
                and node.module and len(node.names) == 1 and node.names[0].name != '*'):
            imported, name = node, node.names[0].asname or node.names[0].name
        elif isinstance(node, ast.FunctionDef) and _parameters(node) is not None:
            name = node.name
            functions.append(node)
        else:
            return set()
        if (name in occupied or name.startswith(('__', 'pytest_'))
                or name in _RESERVED and not (name == 'pytest' and isinstance(node, ast.Import))):
            return set()
        occupied.add(name)
    if imported is None or not 2 <= len(functions) <= 18:
        return set()
    provider = imported.names[0].asname or imported.names[0].name
    if provider.startswith('test'):
        return set()
    helper, tests = functions[0], functions[1:]
    replacements, changed = {}, set()
    for test in tests:
        if not test.name.startswith('test') or _parameters(test) != [] or test.decorator_list:
            return set()
        if pytest and _raises(test, provider):
            continue
        if not 2 <= len(test.body) <= 17:
            return set()
        capture = test.body[0]
        if (not isinstance(capture, ast.Assign) or len(capture.targets) != 1
                or not isinstance(capture.targets[0], (ast.Tuple, ast.List))):
            return set()
        targets = capture.targets[0].elts
        if not all(isinstance(value, ast.Name) for value in targets):
            return set()
        names = [value.id for value in targets]
        if (len(names) != len(set(names)) or set(names) & (occupied | _RESERVED)
                or any(name.startswith('__') for name in names) or len(test.body) != len(names)+1):
            return set()
        subject = capture.value
        if (not isinstance(subject, ast.Call) or not isinstance(subject.func, ast.Name) or subject.func.id != provider
                or subject.keywords or len(subject.args) != 1 or not _string(subject.args[0])):
            return set()
        answers = _answer(helper, subject.args[0], occupied)
        if answers is None:
            return set()
        for name, assertion in zip(names, test.body[1:]):
            if (not isinstance(assertion, ast.Assert) or assertion.msg is not None
                    or not isinstance(assertion.test, ast.Compare) or len(assertion.test.ops) != 1
                    or not isinstance(assertion.test.ops[0], ast.Eq) or not isinstance(assertion.test.left, ast.Name)
                    or assertion.test.left.id != name):
                return set()
            expected = assertion.test.comparators[0]
            if not isinstance(expected, ast.Subscript):
                return set()
            call, index = expected.value, _integer(expected.slice)
            if (not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name) or call.func.id != helper.name
                    or call.keywords or len(call.args) != 1 or stable_dump(call.args[0]) != stable_dump(subject.args[0])
                    or index is None or not -len(answers) <= index < len(answers)):
                return set()
            replacements[assertion] = copy.deepcopy(answers[index])
        changed.add(test.name)
    if not changed:
        return set()
    for assertion, value in replacements.items():
        assertion.test.comparators[0] = ast.copy_location(value, assertion.test.comparators[0])
    tree.body.remove(helper)
    return changed

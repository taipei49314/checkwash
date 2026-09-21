"""A single collected class's literal True guard has no dynamic dispatch.

This only changes a private proof tree. The caller must still validate every
remaining module statement, imported call and complete execution context.
"""
from __future__ import annotations

import ast

from .oracle_blocks import IMPLICIT_ENTRY_NAMES


def _body(node):
    return [item for item in node.body if not (
        isinstance(item, ast.Expr) and isinstance(item.value, ast.Constant)
        and type(item.value.value) is str)]


def unwrap_closed_class_flag(tree):
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    if not any(any(isinstance(item, (ast.Assign, ast.AnnAssign)) for item in _body(node)) for node in classes):
        return True
    if len(classes) != 1:
        return False
    node = classes[0]
    body = _body(node)
    if (not node.name.startswith('Test') or node.bases or node.decorator_list or node.keywords
            or getattr(node, 'type_params', ()) or len(body) != 2):
        return False
    binding, method = body
    if (not isinstance(binding, ast.Assign) or len(binding.targets) != 1
            or not isinstance(binding.targets[0], ast.Name)
            or not isinstance(binding.value, ast.Constant) or binding.value.value is not True
            or not isinstance(method, ast.FunctionDef)):
        return False
    name = binding.targets[0].id
    if name in IMPLICIT_ENTRY_NAMES | {'pytestmark', 'pytest_plugins'} or name.startswith(('__', 'pytest_', 'test')):
        return False
    statements = _body(method)
    if len(statements) != 1 or not isinstance(statements[0], ast.If) or statements[0].orelse:
        return False
    guard = statements[0]
    value = guard.test
    if (not isinstance(value, ast.Attribute) or value.attr != name
            or not isinstance(value.value, ast.Call) or value.value.keywords or len(value.value.args) != 1
            or not isinstance(value.value.func, ast.Name) or value.value.func.id != 'type'
            or not isinstance(value.value.args[0], ast.Name) or value.value.args[0].id != 'self'):
        return False
    # Removing the literal field and guard is proof-only. Remaining class and
    # method bindings, signatures and complete oracle bodies are still checked.
    node.body = [method]
    method.body = guard.body
    return True

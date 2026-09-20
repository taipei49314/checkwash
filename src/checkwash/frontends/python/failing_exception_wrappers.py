"""Expose an oracle inside an exception handler that always fails the test.

Only a sole ``except Exception`` handler calling standard pytest.fail is
transparent. No except body may recover, skip, return, or call repository
code. The table caller proves imported production and startup on both sides.
"""
import ast

from .callable_fixture_expectations import _parameters
from checkwash.ir.astutil import dotted_name


def _message(node, name):
    if isinstance(node, ast.Constant):
        return type(node.value) is str and len(node.value) <= 4096
    return (isinstance(node, ast.JoinedStr) and len(node.values) <= 16
            and all(isinstance(value, ast.Constant) and type(value.value) is str and len(value.value) <= 4096
                    or isinstance(value, ast.FormattedValue) and value.conversion == -1 and value.format_spec is None
                    and isinstance(value.value, ast.Name) and value.value.id == name for value in node.values))


def expand_failing_exception_wrappers(tree):
    pytest_imports = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.alias) and (node.asname or node.name.split('.')[0]) in {'pytest', 'Exception'}:
            if node.name != 'pytest' or node.asname is not None:
                return set()
            pytest_imports += 1
        elif (isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)) and node.id in {'pytest', 'Exception'}
                or isinstance(node, ast.arg) and node.arg in {'pytest', 'Exception'}
                or isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in {'pytest', 'Exception'}
                or isinstance(node, ast.ExceptHandler) and node.name in {'pytest', 'Exception'}):
            return set()
    if pytest_imports != 1 or not any(isinstance(node, ast.Import) and len(node.names) == 1
            and node.names[0].name == 'pytest' and node.names[0].asname is None for node in tree.body):
        return set()
    changed = set()
    for function in tree.body:
        if (not isinstance(function, ast.FunctionDef) or not function.name.startswith('test')
                or _parameters(function) is None or len(function.body) != 1 or not isinstance(function.body[0], ast.Try)):
            continue
        wrapper = function.body[0]
        if wrapper.orelse or wrapper.finalbody or len(wrapper.handlers) != 1 or not 1 <= len(wrapper.body) <= 2:
            continue
        handler = wrapper.handlers[0]
        if (not isinstance(handler.type, ast.Name) or handler.type.id != 'Exception' or not handler.name
                or handler.name.startswith('__') or len(handler.body) != 1 or not isinstance(handler.body[0], ast.Expr)):
            continue
        # An except target is a local for the entire function, including the
        # try body before the handler ever runs. Removing it must not turn an
        # UnboundLocalError into a valid global subject/parameter reference.
        if (handler.name in _parameters(function) or any(isinstance(node, ast.Name) and node.id == handler.name
                for statement in wrapper.body for node in ast.walk(statement))):
            continue
        call = handler.body[0].value
        if (not isinstance(call, ast.Call) or dotted_name(call.func) != 'pytest.fail'
                or len(call.args) != 1 or call.keywords or not _message(call.args[0], handler.name)):
            continue
        if (not isinstance(wrapper.body[-1], ast.Assert)
                or len(wrapper.body) == 2 and not isinstance(wrapper.body[0], ast.Assign)):
            continue
        function.body = wrapper.body
        changed.add(function.name)
    return changed

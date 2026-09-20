"""Closed native pytest setup hooks that skip a collected test.

Only an unconditional native skip/xfail call supplies this evidence. Unknown
module execution, decorators, bindings, control flow and hook signatures do
not establish that the setup callback suppresses a test.
"""
from __future__ import annotations

import ast

from checkwash.ir.astutil import dotted_name


def _body(statements):
    return [statement for statement in statements if not (
        isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant)
        and type(statement.value.value) is str)]


def _resolve(node, bindings):
    name = dotted_name(node)
    if not name:
        return None
    first, dot, rest = name.partition('.')
    target = bindings.get(first)
    return target + dot + rest if target else None


def _decorator(node, bindings, target, keywords):
    if not isinstance(node, ast.Call):
        return _resolve(node, bindings) == target and target == 'pytest.fixture'
    return (_resolve(node.func, bindings) == target and not node.args
            and len({kw.arg for kw in node.keywords}) == len(node.keywords)
            and all(kw.arg in keywords and isinstance(kw.value, ast.Constant)
                    and type(kw.value.value) is bool for kw in node.keywords))


def setup_skip_controls(tree):
    from .callable_fixture_expectations import _parameters

    bindings, functions = {}, []
    for node in _body(tree.body):
        if isinstance(node, ast.Import) and len(node.names) == 1 and node.names[0].name == 'pytest':
            pairs = [(node.names[0].asname or 'pytest', 'pytest')]
        elif (isinstance(node, ast.ImportFrom) and node.module == 'pytest' and not node.level
              and node.names and all(alias.name in {'skip', 'xfail', 'fixture', 'hookimpl'} for alias in node.names)):
            pairs = [(alias.asname or alias.name, 'pytest.' + alias.name) for alias in node.names]
        elif isinstance(node, ast.FunctionDef) and _parameters(node) is not None:
            if node.name in bindings or node.name.startswith('__'):
                return
            bindings[node.name] = None
            functions.append((node, dict(bindings)))
            continue
        else:
            return
        for name, target in pairs:
            if name.startswith('__') or name in bindings and bindings[name] != target:
                return
            bindings[name] = target
    result = None
    for function, declared in functions:
        # Later rebinding of the provider would change a global lookup.
        if any(bindings.get(name) != target for name, target in declared.items() if target):
            return
        body = _body(function.body)
        if function.name != 'pytest_runtest_setup':
            if (function.name.startswith('pytest_') or _parameters(function) != []
                    or len(function.decorator_list) != 1
                    or not _decorator(function.decorator_list[0], declared, 'pytest.fixture', {'autouse'})
                    or len(body) != 1 or not isinstance(body[0], ast.Expr)
                    or not isinstance(body[0].value, ast.Yield) or body[0].value.value is not None):
                return
            continue
        if (_parameters(function) not in ([], ['item']) or len(function.decorator_list) > 1
                or any(not _decorator(dec, declared, 'pytest.hookimpl', {'tryfirst', 'trylast'})
                       for dec in function.decorator_list)
                or len(body) != 1 or not isinstance(body[0], ast.Expr)
                or not isinstance(body[0].value, ast.Call)):
            return
        call = body[0].value
        local = {**declared, **{name: None for name in _parameters(function)}}
        target = _resolve(call.func, local)
        if (target not in {'pytest.skip', 'pytest.xfail'} or len(call.args) > 1 or call.keywords
                or any(not isinstance(arg, ast.Constant) or type(arg.value) is not str for arg in call.args)):
            return
        result = ('conftest.runtime.pytest_runtest_setup.' + target.rsplit('.', 1)[1], call)
    if result is not None:
        yield result

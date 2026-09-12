"""Syntax-only expansion of two complete, transparent oracle wrappers.

This does not execute decorators or generators. An entire known body must
match, and every use must be a collected, argument-free test. The caller
still proves literal inputs, comparison strength, coverage and repository
startup context, including the standard-library wrapper authorities.
"""

from __future__ import annotations

import ast
import copy


def _args(node):
    if not isinstance(node, ast.FunctionDef):
        return None
    args = node.args
    if (node.returns or node.decorator_list or getattr(node, 'type_params', ())
            or args.posonlyargs or args.kwonlyargs or args.defaults or args.vararg or args.kwarg
            or any(arg.annotation for arg in args.args)):
        return None
    return [arg.arg for arg in args.args]


def _same(node, text):
    return ast.dump(node, include_attributes=False) == ast.dump(ast.parse(text).body[0], include_attributes=False)


def _decorator(node):
    parameters = _args(node)
    if parameters is None or len(parameters) != 1 or len(node.body) != 2:
        return None
    deco = node.body[0]
    arguments = _args(deco)
    if arguments is None or len(arguments) != 1 or len(deco.body) != 2:
        return None
    wrapper = deco.body[0]
    if not isinstance(wrapper, ast.FunctionDef):
        return None
    expected, fn = parameters[0], arguments[0]
    names = [node.name, expected, deco.name, fn, wrapper.name]
    if len(set(names)) != len(names) or 'functools' in names:
        return None
    template = (f'def {node.name}({expected}):\n'
                f'    def {deco.name}({fn}):\n'
                f'        @functools.wraps({fn})\n'
                f'        def {wrapper.name}():\n'
                f'            assert {fn}() == {expected}\n'
                f'        return {wrapper.name}\n'
                f'    return {deco.name}\n')
    return 'decorator' if _same(node, template) else None


def _contextmanager(node):
    if not isinstance(node, ast.FunctionDef) or len(node.body) != 3:
        return None
    plain = copy.copy(node)
    plain.decorator_list = []
    parameters = _args(plain)
    assignment = node.body[0]
    if (parameters is None or len(parameters) != 1 or not isinstance(assignment, ast.Assign)
            or len(assignment.targets) != 1 or not isinstance(assignment.targets[0], ast.Name)):
        return None
    expected, box = parameters[0], assignment.targets[0].id
    if len({node.name, expected, box, 'contextmanager'}) != 4:
        return None
    template = (f'@contextmanager\ndef {node.name}({expected}):\n'
                f'    {box} = {{}}\n    yield {box}\n    assert {box}["got"] == {expected}\n')
    return 'contextmanager' if _same(node, template) else None


def trusted_wrapper_import(node):
    if isinstance(node, ast.Import) and len(node.names) == 1:
        alias = node.names[0]
        if alias.name in {'functools', 'operator'} and alias.asname is None:
            return alias.name
    if (isinstance(node, ast.ImportFrom) and node.module == 'contextlib' and not node.level
            and len(node.names) == 1 and node.names[0].name == 'contextmanager'
            and node.names[0].asname is None):
        return 'contextlib'
    return None


def expand_operator_asserts(tree):
    """Canonicalize only direct standard-library equality/identity asserts."""
    if not any(trusted_wrapper_import(node) == 'operator' for node in tree.body):
        return
    if any((isinstance(node, ast.arg) and node.arg == 'operator')
           or (isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store) and node.id == 'operator')
           for node in ast.walk(tree)):
        return
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assert) or node.msg is not None:
            continue
        call = node.test
        if (not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute)
                or not isinstance(call.func.value, ast.Name) or call.func.value.id != 'operator'
                or call.func.attr not in {'eq', 'is_'} or len(call.args) != 2 or call.keywords):
            continue
        node.test = ast.copy_location(ast.Compare(left=call.args[0],
                                                  ops=[ast.Eq() if call.func.attr == 'eq' else ast.Is()],
                                                  comparators=[call.args[1]]), call)


def expand_wrappers(tree):
    authorities = {trusted_wrapper_import(node) for node in tree.body}
    wrappers = {}
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        kind = _decorator(node) if 'functools' in authorities else None
        if kind is None and 'contextlib' in authorities:
            kind = _contextmanager(node)
        if kind:
            if node.name.startswith('test') or node.name in wrappers:
                return None
            wrappers[node.name] = kind
    if not wrappers:
        return set()
    # Removing a helper must not erase duplicate definitions or rebinding.
    for name in wrappers:
        bindings = sum(isinstance(item, (ast.FunctionDef, ast.ClassDef)) and item.name == name
                       or isinstance(item, ast.Name) and isinstance(item.ctx, ast.Store) and item.id == name
                       or isinstance(item, ast.alias) and (item.asname or item.name.split('.')[0]) == name
                       for item in ast.walk(tree))
        if bindings != 1:
            return None
    result, expanded, used = [], set(), set()
    for original in tree.body:
        if isinstance(original, ast.FunctionDef) and original.name in wrappers:
            continue
        node = copy.deepcopy(original)
        if isinstance(node, ast.FunctionDef) and node.name.startswith('test'):
            plain = copy.copy(node)
            plain.decorator_list = []
            if _args(plain) == [] and len(node.body) == 1:
                call, actual, expected = None, None, None
                if len(node.decorator_list) == 1:
                    candidate = node.decorator_list[0]
                    if (isinstance(candidate, ast.Call) and isinstance(candidate.func, ast.Name)
                            and wrappers.get(candidate.func.id) == 'decorator'
                            and isinstance(node.body[0], ast.Return)):
                        call, actual = candidate, node.body[0].value
                elif not node.decorator_list and isinstance(node.body[0], ast.With):
                    context = node.body[0]
                    if len(context.items) == 1 and len(context.body) == 1:
                        item, assignment = context.items[0], context.body[0]
                        candidate = item.context_expr
                        if (isinstance(candidate, ast.Call) and isinstance(candidate.func, ast.Name)
                                and wrappers.get(candidate.func.id) == 'contextmanager'
                                and isinstance(item.optional_vars, ast.Name) and isinstance(assignment, ast.Assign)
                                and len(assignment.targets) == 1):
                            target = assignment.targets[0]
                            if (isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name)
                                    and target.value.id == item.optional_vars.id and isinstance(target.slice, ast.Constant)
                                    and target.slice.value == 'got'
                                    and not any(isinstance(n, ast.Name) and n.id == item.optional_vars.id
                                                for n in ast.walk(assignment.value))):
                                call, actual = candidate, assignment.value
                if call is not None and len(call.args) == 1 and not call.keywords and actual is not None:
                    expected = call.args[0]
                    check = ast.Assert(test=ast.Compare(left=actual, ops=[ast.Eq()], comparators=[expected]), msg=None)
                    node.body = [ast.copy_location(check, node.body[0])]
                    node.decorator_list = []
                    expanded.add(node.name)
                    used.add(call.func.id)
        if any(isinstance(item, ast.Name) and item.id in wrappers for item in ast.walk(node)):
            return None
        result.append(node)
    if used != wrappers.keys():
        return None
    tree.body = result
    return expanded

"""Complete literal oracle rows moved into a patched stdlib TestCase method.

This is installation evidence for an existing oracle inventory, not alignment
or equivalence credit. Partial row matches cannot establish this mapping.
"""
from __future__ import annotations

import ast

from checkwash.ir.astutil import stable_dump


def _plain(function, count):
    if not isinstance(function, ast.FunctionDef):
        return False
    args = function.args
    parameters = args.posonlyargs + args.args
    return (len(parameters) == count and len({arg.arg for arg in parameters}) == count
            and not args.defaults and not args.kwonlyargs and not args.vararg and not args.kwarg
            and not any(arg.annotation for arg in parameters) and not function.returns
            and not getattr(function, "type_params", ()))


def _row(statement):
    if not isinstance(statement, ast.Assert) or statement.msg is not None:
        return None
    test = statement.test
    if (not isinstance(test, ast.Compare) or len(test.ops) != 1 or not isinstance(test.ops[0], ast.Eq)
            or not isinstance(test.left, ast.Call) or len(test.left.args) != 1 or test.left.keywords
            or not isinstance(test.left.args[0], ast.Constant) or type(test.left.args[0].value) is not str
            or not isinstance(test.comparators[0], ast.Constant) or type(test.comparators[0].value) is not str):
        return None
    return test.left, test.comparators[0]


def _inert(statement):
    return isinstance(statement, ast.Pass) or (isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant) and type(statement.value.value) is str)


def restructured_patch_event(path, modules, live, context, deny, budget, search=None):
    from .replacement_authority import closed_replacement_authority
    from .standin_installations import _Trace, _Value
    from .subject_replacements import _bindings, _helper_module_inert, _resolve

    if not live[0] or not live[1] or live[0] & live[1]:
        return None
    selected = [next(module for module in side if module.path == path) for side in modules]
    before, after = [module.tree for module in selected]
    if not _helper_module_inert(before):
        return None
    if any(any(not _inert(statement) for statement in module.tree.body)
           for side in modules for module in side if module.path != path):
        return None
    old_functions = [node for node in before.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    if ({node.name for node in old_functions} != live[0] or not 1 <= len(old_functions) <= 64
            or any(not _plain(node, 0) or node.decorator_list or len(node.body) != 1 for node in old_functions)):
        return None
    rows = [_row(node.body[0]) for node in old_functions]
    if any(row is None for row in rows):
        return None
    old_bindings, new_bindings = _bindings(before.body), _bindings(after.body)
    targets = {_resolve(row[0].func, old_bindings) for row in rows}
    if len(targets) != 1:
        return None
    target = next(iter(targets))
    if not isinstance(target, str) or target.split('.')[0] in deny or not context.contains(target, 0):
        return None
    classes = [node for node in after.body if isinstance(node, ast.ClassDef)]
    if len(classes) != 1:
        return None
    cls = classes[0]
    if (cls.decorator_list or cls.keywords or getattr(cls, 'type_params', ()) or len(cls.bases) != 1
            or _resolve(cls.bases[0], new_bindings) != 'unittest.TestCase'):
        return None
    members = [node for node in cls.body if not _inert(node)]
    if len(members) != 1 or not _plain(members[0], 2):
        return None
    method = members[0]
    qualname = cls.name + '.' + method.name
    if live[1] != {qualname} or len(method.decorator_list) != 1 or len(method.body) != len(rows):
        return None
    parameters = method.args.posonlyargs + method.args.args
    if parameters[0].arg != 'self':
        return None
    mock_name = parameters[1].arg
    decorator = method.decorator_list[0]
    if (not isinstance(decorator, ast.Call) or _resolve(decorator.func, new_bindings) != 'unittest.mock.patch'
            or len(decorator.args) != 1 or not isinstance(decorator.args[0], ast.Constant)
            or decorator.args[0].value != target or len(decorator.keywords) != 1
            or decorator.keywords[0].arg != 'side_effect'):
        return None
    sequence = decorator.keywords[0].value
    if not isinstance(sequence, (ast.List, ast.Tuple)) or len(sequence.elts) != len(rows):
        return None
    for (old_call, old_answer), statement, returned in zip(rows, method.body, sequence.elts):
        new = _row(statement)
        if (new is None or not isinstance(new[0].func, ast.Name) or new[0].func.id != mock_name
                or stable_dump(old_call.args[0]) != stable_dump(new[0].args[0])
                or stable_dump(old_answer) != stable_dump(new[1]) or stable_dump(old_answer) != stable_dump(returned)):
            return None
    # Only the original production module and the two exact unittest imports
    # may execute before constructing the known base class and patch wrapper.
    allowed_imports = {'unittest', 'unittest.mock', target.rsplit('.', 1)[0]}
    defined = False
    for statement in after.body:
        if statement is cls:
            defined = True
        elif isinstance(statement, (ast.Import, ast.ImportFrom)) and not defined:
            if isinstance(statement, ast.Import):
                if any(alias.name not in allowed_imports or (alias.asname or alias.name).startswith('__') for alias in statement.names):
                    return None
            elif (statement.level or statement.module not in allowed_imports
                  or any(alias.name == '*' or (alias.asname or alias.name).startswith('__') for alias in statement.names)):
                return None
        elif isinstance(statement, ast.If):
            test = statement.test
            call = statement.body[0].value if len(statement.body) == 1 and isinstance(statement.body[0], ast.Expr) else None
            if (not isinstance(test, ast.Compare) or len(test.ops) != 1 or not isinstance(test.ops[0], ast.Eq)
                    or not isinstance(test.left, ast.Name) or test.left.id != '__name__'
                    or not isinstance(test.comparators[0], ast.Constant) or test.comparators[0].value != '__main__'
                    or statement.orelse or not isinstance(call, ast.Call) or call.args or call.keywords
                    or _resolve(call.func, new_bindings) != 'unittest.main'):
                return None
        elif not _inert(statement):
            return None
    function = selected[1].functions.get(qualname)
    if function is None or function.patch_env is None:
        return None
    for side, tree in enumerate((before, after)):
        def read(candidate):
            return context.changed[candidate][side] if candidate in context.changed else context.reader(candidate)
        def inventory(needles):
            paths = search(needles) if search is not None else None
            if not isinstance(paths, (list, tuple)) or any(not isinstance(item, str) for item in paths):
                return paths
            # The reader overlays both snapshots; their inventory must also
            # retain removed old startup/sibling files and exclude additions.
            return sorted(({item.replace('\\', '/') for item in paths} - set(context.changed))
                          | {name for name, versions in context.changed.items() if versions[side] is not None})
        if not closed_replacement_authority(
                tree, target, path=path, read=read, search=inventory,
                modules={'unittest', 'unittest.mock'},
                symbols={'unittest': {'TestCase', 'main', 'mock'}, 'unittest.mock': {'patch'}}):
            return None
    trace = _Trace(modules[1], context, 1, deny, budget, search)
    item = ast.withitem(context_expr=decorator, optional_vars=ast.Name(id=mock_name, ctx=ast.Store()))
    # The first row alone proves consumption. The complete literal sequence
    # above additionally prevents an unrelated or weakened inventory match.
    value = trace.patch_result(item, None, method.body[:1], selected[1], function.patch_env, qualname)
    if value is None:
        return None
    trace.function(function, [_Value(), value])
    if len(trace.observed) != 1:
        return None
    effect = next(iter(trace.observed))
    return (path, qualname, effect.target, effect.text, effect.span)

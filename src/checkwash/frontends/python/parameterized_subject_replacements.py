"""Literal assertion-helper calls that substitute a numeric builtin subject.

This contributes an installation event only. It does not normalize assertions,
change alignment, or give a helper production-oracle credit.
"""
from __future__ import annotations

import ast

from checkwash.ir.astutil import stable_dump


def _numeric(node):
    try:
        return type(ast.literal_eval(node)) in {int, float}
    except (ValueError, TypeError, RecursionError, MemoryError):
        return False


def _plain(function, arguments):
    if not isinstance(function, ast.FunctionDef):
        return False
    args = function.args
    return (not function.decorator_list and function.returns is None
            and not getattr(function, "type_params", ())
            and len(args.posonlyargs + args.args) == arguments
            and not any(arg.annotation for arg in args.posonlyargs + args.args)
            and not args.defaults and not args.kwonlyargs and not args.vararg and not args.kwarg)


def _comparison(statement):
    if not isinstance(statement, ast.Assert) or statement.msg is not None:
        return None
    test = statement.test
    return (test if isinstance(test, ast.Compare) and len(test.ops) == 1
            and isinstance(test.ops[0], ast.Eq) and isinstance(test.left, ast.Call) else None)


def parameterized_abs_event(unit, trees, path, source, context, deny, search=None):
    """Compare complete literal rows, then prove the first replacement runs.

    Later helper calls may be behind a failing assertion, so only the first
    invocation contributes evidence. All rows must retain their exact old
    input and answer, and every test in the module must have this closed form.
    """
    from .frontend import _Offsets
    from .literal_stdlib_standins import _read
    from .replacement_authority import closed_replacement_authority
    from .subject_replacements import _bindings, _helper_module_inert, _resolve

    if any(tree is None or not _helper_module_inert(tree) for tree in trees):
        return None
    old_functions = {node.name: node for node in trees[0].body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    new_functions = {node.name: node for node in trees[1].body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    if not old_functions or any(not name.startswith("test") or not _plain(node, 0)
                                for name, node in old_functions.items()):
        return None
    helpers = set(new_functions) - set(old_functions)
    if len(helpers) != 1 or not set(old_functions) <= set(new_functions):
        return None
    helper_name = next(iter(helpers))
    helper = new_functions[helper_name]
    if helper_name.startswith("test") or not _plain(helper, 2) or len(helper.body) != 1:
        return None
    comparison = _comparison(helper.body[0])
    if comparison is None or len(comparison.left.args) != 1 or comparison.left.keywords:
        return None
    parameters = [arg.arg for arg in helper.args.posonlyargs + helper.args.args]
    argument, answer = comparison.left.args[0], comparison.comparators[0]
    if (not isinstance(argument, ast.Name) or not isinstance(answer, ast.Name)
            or set(parameters) != {argument.id, answer.id}):
        return None
    bindings = [_bindings(tree.body) for tree in trees]
    if _resolve(comparison.left.func, {**bindings[1], **{name: None for name in parameters}}) != "builtins.abs":
        return None
    argument_index, answer_index = parameters.index(argument.id), parameters.index(answer.id)
    first = None
    rows = 0
    targets = set()
    for name, before in old_functions.items():
        after = new_functions[name]
        if not _plain(after, 0) or not before.body or len(before.body) != len(after.body):
            return None
        for index, (old_statement, new_statement) in enumerate(zip(before.body, after.body)):
            rows += 1
            if rows > 128:
                return None
            old = _comparison(old_statement)
            call = new_statement.value if isinstance(new_statement, ast.Expr) else None
            if (old is None or len(old.left.args) != 1 or old.left.keywords
                    or not _numeric(old.left.args[0]) or not _numeric(old.comparators[0])
                    or not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name)
                    or call.func.id != helper_name or call.keywords or len(call.args) != 2
                    or not all(_numeric(value) for value in call.args)
                    or stable_dump(old.left.args[0]) != stable_dump(call.args[argument_index])
                    or stable_dump(old.comparators[0]) != stable_dump(call.args[answer_index])):
                return None
            target = _resolve(old.left.func, bindings[0])
            if (not isinstance(target, str) or target.split(".", 1)[0] in deny
                    or not context.contains(target, 0)):
                return None
            targets.add(target)
            if name == unit.qualname and index == 0:
                offsets = _Offsets(source.decode("utf-8-sig"))
                first = (path, unit.qualname, target, offsets.seg(call), offsets.span(call))
    if len(targets) != 1 or not closed_replacement_authority(
            trees[1], next(iter(targets)), path=path, read=lambda candidate: _read(context, candidate),
            search=search, modules={'builtins', 'pytest'}, symbols={'builtins': {'abs'}}):
        return None
    return first

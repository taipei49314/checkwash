"""Closed integer calls to an unshadowed stdlib replacement helper."""
from __future__ import annotations

import ast

from checkwash.change import EngineError


def literal_math_gcd_standin(function, call, bindings):
    from .subject_replacements import _resolve

    if not isinstance(function, ast.FunctionDef) or not isinstance(call, ast.Call):
        return False
    args = function.args
    parameters = [*args.posonlyargs, *args.args]
    if (function.decorator_list or function.returns or getattr(function, "type_params", ())
            or args.defaults or args.kw_defaults or args.kwonlyargs or args.vararg or args.kwarg
            or any(arg.annotation for arg in parameters) or call.keywords
            or len(call.args) != len(parameters) or len(parameters) != 2
            or len(function.body) != 1 or not isinstance(function.body[0], ast.Return)):
        return False
    try:
        # Custom __index__ methods can call production. Only exact integers
        # prove that stdlib gcd's argument conversion has no such callback.
        if any(type(ast.literal_eval(value)) is not int for value in call.args):
            return False
    except (ValueError, TypeError, RecursionError, MemoryError):
        return False
    expression = function.body[0].value
    names = {arg.arg for arg in parameters}
    return (isinstance(expression, ast.Call) and len(expression.args) == 2 and not expression.keywords
            and all(isinstance(value, ast.Name) and value.id in names for value in expression.args)
            and _resolve(expression.func, {**bindings, **{name: None for name in names}}) == "math.gcd")


def math_is_unshadowed(context, path):
    """Check conventional repository and test-directory Python import paths."""
    prefixes = {"", "src/"}
    directory = path.replace("\\", "/").rpartition("/")[0]
    for _ in range(16):
        if not directory:
            break
        prefixes.add(directory + "/")
        directory = directory.rpartition("/")[0]
    else:
        return False
    for prefix in sorted(prefixes):
        for suffix in ("math.py", "math/__init__.py"):
            candidate = prefix + suffix
            if candidate in context.changed:
                value = context.changed[candidate][1]
            else:
                if candidate not in context.cache:
                    if len(context.cache) >= 128:
                        raise EngineError("stdlib replacement authority exceeds the snapshot read budget")
                    value = context.reader(candidate)
                    if value is not None and not isinstance(value, bytes):
                        raise EngineError("stdlib replacement reader returned invalid source bytes")
                    context.cache[candidate] = value
                value = context.cache[candidate]
            if value is not None:
                return False
    return True

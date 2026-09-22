"""Production-free string helpers for a concrete literal-string invocation."""
from __future__ import annotations

import ast


def literal_string_standin(function, call):
    """Prove primitive receivers through a small, total string-method chain.

    An arbitrary parameter's method can dispatch back into production. Only
    an actual string literal establishes the receiver type here; no source
    expression is executed and no global or mutable value is borrowed.
    """
    if not isinstance(function, ast.FunctionDef) or not isinstance(call, ast.Call):
        return False
    args = function.args
    parameters = [*args.posonlyargs, *args.args]
    if (function.decorator_list or function.returns or getattr(function, "type_params", ())
            or args.defaults or args.kw_defaults or args.kwonlyargs or args.vararg or args.kwarg
            or any(arg.annotation for arg in parameters) or call.keywords
            or len(call.args) != len(parameters) or not parameters
            or any(not isinstance(value, ast.Constant) or type(value.value) is not str for value in call.args)
            or len(function.body) != 1 or not isinstance(function.body[0], ast.Return)):
        return False
    names = {arg.arg for arg in parameters}

    def primitive(node):
        if isinstance(node, ast.Name) and node.id in names:
            return "str"
        if isinstance(node, ast.Constant) and type(node.value) is str:
            return "str"
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and not node.keywords and primitive(node.func.value) == "str"):
            return None
        if not node.args:
            if node.func.attr in {"lower", "upper", "casefold", "strip", "lstrip", "rstrip"}:
                return "str"
            if node.func.attr == "split":
                return "str-list"
        if node.func.attr == "join" and len(node.args) == 1 and primitive(node.args[0]) == "str-list":
            return "str"
        return None

    return primitive(function.body[0].value) == "str"

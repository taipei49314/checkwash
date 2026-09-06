"""One closed conditional-failure spelling becomes a native oracle carrier.

``if value != expected: raise AssertionError("literal")`` has the same
failure predicate as ``assert not (value != expected)``. Transform only the
analysis AST, preserving original source positions, so reachability, inherited
oracles and exception neutralization all consume the same carrier. No source
is rewritten or executed.
"""

from __future__ import annotations

import ast

from checkwash.ir.astutil import dotted_name


def _constructor_uncertain(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)) and node.id == "AssertionError":
            return True
        if isinstance(node, ast.arg) and node.arg == "AssertionError":
            return True
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == "AssertionError":
            return True
        if isinstance(node, ast.ExceptHandler) and node.name == "AssertionError":
            return True
        if isinstance(node, (ast.Import, ast.ImportFrom)) and any(
            a.name == "*" or (a.asname or a.name.split(".")[0]) == "AssertionError" for a in node.names
        ):
            return True
        if isinstance(node, ast.Attribute) and node.attr == "AssertionError" and isinstance(node.ctx, (ast.Store, ast.Del)):
            return True
        if isinstance(node, ast.Call) and (dotted_name(node.func) or "").rsplit(".", 1)[-1] in (
            "exec", "eval", "globals", "locals", "vars", "setattr", "delattr",
        ):
            # Dynamic namespace writes cannot establish the built-in binding.
            return True
    return False


def _failure(node):
    if (not isinstance(node.test, ast.Compare) or len(node.test.ops) != 1
            or not isinstance(node.test.ops[0], (ast.Eq, ast.NotEq, ast.Is, ast.IsNot, ast.In, ast.NotIn))
            or len(node.body) != 1 or node.orelse or not isinstance(node.body[0], ast.Raise)):
        return None
    failure = node.body[0]
    if failure.cause is not None:
        return None
    exception = failure.exc
    if isinstance(exception, ast.Name) and exception.id == "AssertionError":
        return ast.Constant(value=None)
    if (isinstance(exception, ast.Call) and isinstance(exception.func, ast.Name)
            and exception.func.id == "AssertionError" and not exception.keywords
            and len(exception.args) <= 1 and all(isinstance(a, ast.Constant) for a in exception.args)):
        return exception.args[0] if exception.args else ast.Constant(value=None)
    return None


class _OracleCarriers(ast.NodeTransformer):
    def visit_If(self, node):
        message = _failure(node)
        if message is None:
            return self.generic_visit(node)
        condition = ast.copy_location(ast.UnaryOp(op=ast.Not(), operand=node.test), node.test)
        return ast.copy_location(ast.Assert(test=condition, msg=message), node)


def conditional_oracle_carriers(tree):
    """Return the same tree with recognized failure predicates represented.

    A shadowed/dynamic exception constructor declines the whole module rather
    than guessing which binding reaches the raise. Unsupported conditional
    failures retain their original AST and existing behavior.
    """
    if _constructor_uncertain(tree):
        return tree
    return _OracleCarriers().visit(tree)

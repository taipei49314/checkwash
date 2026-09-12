"""Evaluate a small closed language over bounded primitive literal values.

No eval, import of repository modules, attribute lookup or repository call is
performed. The caller separately proves authority for len/math.prod syntax.
Unsupported or oversized expressions return no proof, never equivalence.
"""

import ast
import math
import operator


class _Unknown(Exception):
    pass


def folded_expected(node, allow_call):
    steps = 0

    def bounded(value):
        if type(value) is int and value.bit_length() <= 256:
            return value
        if type(value) is float and math.isfinite(value):
            return value
        if type(value) in (bool, type(None)):
            return value
        if type(value) in (str, bytes) and len(value) <= 4096:
            return value
        if type(value) in (tuple, list) and len(value) <= 64:
            for item in value:
                bounded(item)
            return value
        raise _Unknown

    def visit(expr, depth=0):
        nonlocal steps
        steps += 1
        if steps > 128 or depth > 16:
            raise _Unknown
        sub = lambda item: visit(item, depth + 1)
        if isinstance(expr, ast.Constant):
            return bounded(expr.value)
        if isinstance(expr, (ast.Tuple, ast.List)):
            if len(expr.elts) > 64:
                raise _Unknown
            values = [sub(item) for item in expr.elts]
            return bounded(tuple(values) if isinstance(expr, ast.Tuple) else values)
        if isinstance(expr, ast.UnaryOp) and isinstance(expr.op, (ast.UAdd, ast.USub)):
            value = sub(expr.operand)
            if type(value) not in (int, float):
                raise _Unknown
            return bounded(+value if isinstance(expr.op, ast.UAdd) else -value)
        if isinstance(expr, ast.BinOp):
            left, right = sub(expr.left), sub(expr.right)
            operations = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
                          ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod}
            operation = operations.get(type(expr.op))
            numeric = type(left) in (int, float) and type(right) in (int, float)
            concatenation = isinstance(expr.op, ast.Add) and type(left) is type(right) and type(left) in (str, bytes)
            if operation is None or not (numeric or concatenation):
                raise _Unknown
            return bounded(operation(left, right))
        if isinstance(expr, ast.Compare) and len(expr.ops) == 1:
            left, right = sub(expr.left), sub(expr.comparators[0])
            comparisons = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt,
                           ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge}
            compare = comparisons.get(type(expr.ops[0]))
            if compare is None or type(left) not in (int, float, str, bytes) or type(right) not in (int, float, str, bytes):
                raise _Unknown
            return compare(left, right)
        if isinstance(expr, ast.IfExp):
            condition = sub(expr.test)
            if type(condition) is not bool:
                raise _Unknown
            return sub(expr.body if condition else expr.orelse)
        if isinstance(expr, ast.Subscript):
            value = sub(expr.value)
            if type(value) not in (str, bytes, list, tuple):
                raise _Unknown
            if isinstance(expr.slice, ast.Slice):
                bounds = [sub(part) if part is not None else None
                          for part in (expr.slice.lower, expr.slice.upper, expr.slice.step)]
                if any(part is not None and type(part) is not int for part in bounds):
                    raise _Unknown
                index = slice(*bounds)
            else:
                index = sub(expr.slice)
                if type(index) is not int:
                    raise _Unknown
            return bounded(value[index])
        if isinstance(expr, ast.Call) and len(expr.args) == 1 and not expr.keywords:
            name = ast.unparse(expr.func)
            if name not in ("len", "math.prod") or not allow_call(name):
                raise _Unknown
            value = sub(expr.args[0])
            if name == "len" and type(value) in (str, bytes, list, tuple):
                return len(value)
            if name == "math.prod" and type(value) in (list, tuple):
                result = 1
                for item in value:
                    steps += 1
                    if steps > 128 or type(item) not in (int, float):
                        raise _Unknown
                    result = bounded(result * item)
                return result
        raise _Unknown

    try:
        value = visit(node)
        return ast.parse(repr(value), mode="eval").body
    except (_Unknown, ArithmeticError, ValueError, TypeError, IndexError, RecursionError, MemoryError):
        return None

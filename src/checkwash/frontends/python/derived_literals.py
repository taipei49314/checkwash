"""Three bounded primitive expectation spellings, without repository execution."""

import ast
import copy

from checkwash.frontends.python.expected_constants import folded_expected


AUTHORITIES = frozenset({"bin", "list", "range"})


def derived_shape(node):
    if not isinstance(node, ast.Call) or node.keywords:
        return False
    if isinstance(node.func, ast.Name) and node.func.id == "list" and len(node.args) == 1:
        inner = node.args[0]
        return (isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name)
                and inner.func.id == "range" and not inner.keywords and 1 <= len(inner.args) <= 3)
    if isinstance(node.func, ast.Attribute):
        if node.func.attr == "count" and len(node.args) == 1:
            inner = node.func.value
            return (isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name)
                    and inner.func.id == "bin" and len(inner.args) == 1 and not inner.keywords)
        if node.func.attr == "join" and len(node.args) == 1:
            return isinstance(node.args[0], ast.GeneratorExp)
    return False


def fold_derived(node):
    """Return a literal AST plus required builtin names, or no proof."""
    if not derived_shape(node):
        return None

    def literal(expression):
        folded = folded_expected(expression, lambda name: False)
        if folded is None:
            raise ValueError
        return ast.literal_eval(folded)

    try:
        if isinstance(node.func, ast.Name):
            args = [literal(value) for value in node.args[0].args]
            if any(type(value) is not int or value.bit_length() > 256 for value in args):
                return None
            sequence = range(*args)
            if len(sequence) > 64:
                return None
            value, names = list(sequence), frozenset({"list", "range"})
        elif node.func.attr == "count":
            number, needle = literal(node.func.value.args[0]), literal(node.args[0])
            if type(number) is not int or number.bit_length() > 256 or type(needle) is not str or len(needle) > 4096:
                return None
            value, names = bin(number).count(needle), frozenset({"bin"})
        else:
            separator = literal(node.func.value)
            expression = node.args[0]
            if type(separator) is not str or len(expression.generators) != 1:
                return None
            generator = expression.generators[0]
            if (generator.is_async or not isinstance(generator.target, ast.Name)
                    or not isinstance(expression.elt, ast.Name) or expression.elt.id != generator.target.id
                    or len(generator.ifs) != 1):
                return None
            check = generator.ifs[0]
            if (not isinstance(check, ast.Call) or check.args or check.keywords
                    or not isinstance(check.func, ast.Attribute) or check.func.attr != "isdigit"
                    or not isinstance(check.func.value, ast.Name) or check.func.value.id != generator.target.id):
                return None
            source = literal(generator.iter)
            if type(source) is not str or len(source) > 4096:
                return None
            selected = [character for character in source if character.isdigit()]
            if sum(map(len, selected)) + max(0, len(selected) - 1) * len(separator) > 4096:
                return None
            value, names = separator.join(selected), frozenset()
        return ast.parse(repr(value), mode="eval").body, names
    except (ValueError, TypeError, ArithmeticError, RecursionError, MemoryError):
        return None


def primitive_derived_result(source, target, call):
    """A sole plain function returning the same closed primitive grammar."""
    try:
        if len(source) > 65_536:
            return False
        tree = ast.parse(source)
        if sum(1 for _ in ast.walk(tree)) > 4096:
            return False
        body = [node for node in tree.body if not isinstance(node, ast.Pass)
                and not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
                         and type(node.value.value) is str)]
        if len(body) != 1 or not isinstance(body[0], ast.FunctionDef):
            return False
        function = body[0]
        args = function.args
        if (function.name != target or target in AUTHORITIES or function.decorator_list or function.returns
                or getattr(function, "type_params", ()) or args.posonlyargs or args.kwonlyargs or args.defaults
                or args.vararg or args.kwarg or any(arg.annotation for arg in args.args)
                or call.keywords or len(call.args) != len(args.args)
                or len(function.body) != 1 or not isinstance(function.body[0], ast.Return)):
            return False
        bindings = {arg.arg: value for arg, value in zip(args.args, call.args)}
        if bindings.keys() & AUTHORITIES:
            return False

        class Substitute(ast.NodeTransformer):
            def visit_Name(self, node):
                return copy.deepcopy(bindings.get(node.id, node))

        return fold_derived(Substitute().visit(copy.deepcopy(function.body[0].value))) is not None
    except (ValueError, TypeError, SyntaxError, RecursionError, MemoryError):
        return False

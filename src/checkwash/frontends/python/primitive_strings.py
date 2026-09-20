"""A closed type proof for formatting a production result in an assert message.

Only one plain function over literal strings is admitted. No repository code
is executed: string operations, slices and branch returns prove that an
untrusted formatting hook cannot run on the returned value. A sole standard
``re`` import permits string ``re.sub``; the caller must prove its authority.
"""

import ast

_STRING_SEQUENCE = object()


def primitive_string_result(source, target, call):
    if call.keywords or not all(isinstance(value, ast.Constant) and type(value.value) is str for value in call.args):
        return False
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, TypeError, RecursionError, MemoryError):
        return False
    if len(source) > 65_536 or sum(1 for _ in ast.walk(tree)) > 4096:
        return False
    body = [node for node in tree.body if not isinstance(node, ast.Pass)
            and not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and type(node.value.value) is str)]
    regex = False
    if (body and isinstance(body[0], ast.Import) and len(body[0].names) == 1
            and body[0].names[0].name == "re" and body[0].names[0].asname is None):
        regex = True
        body = body[1:]
    if len(body) != 1 or not isinstance(body[0], ast.FunctionDef) or body[0].name != target or target == "len":
        return False
    function = body[0]
    args = function.args
    if (function.decorator_list or function.returns or getattr(function, "type_params", ())
            or args.posonlyargs or args.kwonlyargs or args.vararg or args.kwarg or args.defaults
            or any(arg.annotation for arg in args.args) or len(args.args) != len(call.args)):
        return False
    names = {arg.arg for arg in args.args}
    if names & {"len", "re"} or len(names) != len(args.args):
        return False
    steps = 0

    def kind(node):
        nonlocal steps
        steps += 1
        if steps > 2048:
            return None
        if isinstance(node, ast.Name):
            return str if node.id in names else None
        if isinstance(node, ast.Constant):
            return type(node.value) if type(node.value) in (str, int, bool) else None
        if isinstance(node, ast.Subscript) and kind(node.value) is str:
            index = node.slice
            if isinstance(index, ast.Slice):
                if all(value is None or kind(value) is int for value in (index.lower, index.upper, index.step)):
                    return str
            elif kind(index) is int:
                return str
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add) and kind(node.left) is kind(node.right) is str:
            return str
        if isinstance(node, ast.Call) and not node.keywords:
            if isinstance(node.func, ast.Name) and node.func.id == "len" and len(node.args) == 1 and kind(node.args[0]) is str:
                return int
            if (regex and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "re" and node.func.attr == "sub" and len(node.args) == 3
                    and all(kind(arg) is str for arg in node.args)):
                return str
            if isinstance(node.func, ast.Attribute) and kind(node.func.value) is str:
                if node.func.attr == "split" and not node.args:
                    return _STRING_SEQUENCE
                if node.func.attr == "join" and len(node.args) == 1 and kind(node.args[0]) is _STRING_SEQUENCE:
                    return str
                if node.func.attr in {"startswith", "endswith"} and len(node.args) == 1 and kind(node.args[0]) is str:
                    return bool
                if node.func.attr in {"lower", "upper", "strip", "lstrip", "rstrip", "casefold"} and not node.args:
                    return str
                if node.func.attr in {"strip", "lstrip", "rstrip"} and len(node.args) == 1 and kind(node.args[0]) is str:
                    return str
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not) and kind(node.operand) is bool:
            return bool
        if isinstance(node, ast.Compare) and len(node.ops) == 1 and isinstance(node.ops[0], (ast.Eq, ast.NotEq)):
            if kind(node.left) is kind(node.comparators[0]) is str:
                return bool
        return None

    def statements(nodes, depth=0):
        nonlocal steps
        steps += 1
        if steps > 2048 or depth > 16:
            return False
        for index, node in enumerate(nodes):
            if isinstance(node, ast.Return):
                return kind(node.value) is str
            if isinstance(node, ast.If) and kind(node.test) is bool:
                if not statements([*node.body, *nodes[index + 1:]], depth + 1) or not statements([*node.orelse, *nodes[index + 1:]], depth + 1):
                    return False
                return True
            return False
        return False

    statements_left = list(function.body)
    while statements_left and isinstance(statements_left[0], ast.Assign):
        assignment = statements_left.pop(0)
        if (len(assignment.targets) != 1 or not isinstance(assignment.targets[0], ast.Name)
                or assignment.targets[0].id in {"len", "re"} or kind(assignment.value) is not str):
            return False
        names.add(assignment.targets[0].id)
    # Each branch independently reaches a primitive-string return. There are
    # no object mutation, decorators, calls to user code or hooks.
    return statements(statements_left)

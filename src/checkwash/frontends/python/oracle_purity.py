"""A source proof for order-independent calls on concrete built-in values.

Only import-free modules of plain pure functions are accepted. Functions may
return/branch/raise a literal ValueError using their arguments and a short
list of builtins. No repository function is evaluated by this proof.
"""

import ast
from pathlib import PurePosixPath


_BUILTINS = {'len', 'range', 'all', 'any', 'max', 'min', 'abs'}


def _literal(node):
    if any(isinstance(item, ast.Call) for item in ast.walk(node)):
        return False  # literal_eval accepts set(), whose name may be rebound at definition time
    try:
        ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return False
    return True


def _expression(node, names):
    if isinstance(node, ast.Constant):
        return type(node.value) in (type(None), bool, int, float, str, bytes)
    if isinstance(node, ast.Name):
        return node.id in names
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return all(_expression(item, names) for item in node.elts)
    if isinstance(node, ast.UnaryOp):
        return isinstance(node.op, (ast.UAdd, ast.USub, ast.Not, ast.Invert)) and _expression(node.operand, names)
    if isinstance(node, ast.BinOp):
        return (isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod))
                and _expression(node.left, names) and _expression(node.right, names))
    if isinstance(node, ast.Compare):
        return (_expression(node.left, names) and all(_expression(item, names) for item in node.comparators)
                and all(isinstance(op, (ast.Eq, ast.NotEq, ast.Is, ast.IsNot, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
                                        ast.In, ast.NotIn)) for op in node.ops))
    if isinstance(node, ast.BoolOp):
        return all(_expression(item, names) for item in node.values)
    if isinstance(node, ast.IfExp):
        return all(_expression(item, names) for item in (node.test, node.body, node.orelse))
    if isinstance(node, ast.Subscript):
        return _expression(node.value, names) and _expression(node.slice, names)
    if isinstance(node, ast.Slice):
        return all(item is None or _expression(item, names) for item in (node.lower, node.upper, node.step))
    if isinstance(node, ast.Call):
        return (isinstance(node.func, ast.Name) and node.func.id in _BUILTINS and node.func.id not in names
                and not node.keywords and all(_expression(arg, names) for arg in node.args))
    if isinstance(node, ast.GeneratorExp) and len(node.generators) == 1:
        generator = node.generators[0]
        if (generator.is_async or not isinstance(generator.target, ast.Name) or generator.target.id in names
                or not _expression(generator.iter, names)):
            return False
        inner = names | {generator.target.id}
        return _expression(node.elt, inner) and all(_expression(item, inner) for item in generator.ifs)
    return False


def _body(statements, names):
    for node in statements:
        if isinstance(node, ast.Return) and node.value is not None and _expression(node.value, names):
            continue
        if (isinstance(node, ast.If) and _expression(node.test, names)
                and _body(node.body, names) and _body(node.orelse, names)):
            continue
        if (isinstance(node, ast.Raise) and node.cause is None and isinstance(node.exc, ast.Call)
                and isinstance(node.exc.func, ast.Name) and node.exc.func.id == 'ValueError'
                and 'ValueError' not in names and not node.exc.keywords
                and all(_literal(arg) for arg in node.exc.args)):
            continue
        return False
    return True


def _inert(node):
    return (isinstance(node, ast.Pass) or isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str))


def _tree(source):
    if not isinstance(source, bytes) or len(source) > 65_536:
        return None
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, TypeError, MemoryError, RecursionError):
        return None
    return tree if sum(1 for _ in ast.walk(tree)) <= 4096 else None


def _pure_module(source, target):
    tree = _tree(source)
    if tree is None:
        return False
    found, bound = False, set()
    for node in tree.body:
        if _inert(node):
            continue
        if (not isinstance(node, ast.FunctionDef) or node.name in bound or node.name.startswith('__')
                or node.name in _BUILTINS | {'ValueError'}):
            return False
        bound.add(node.name)
        args = node.args
        if (node.decorator_list or node.returns or getattr(node, 'type_params', ())
                or args.posonlyargs or args.kwonlyargs or args.vararg or args.kwarg
                or any(arg.annotation for arg in args.args) or not all(_literal(item) for item in args.defaults)):
            return False
        names = {arg.arg for arg in args.args}
        if len(names) != len(args.args) or names & (_BUILTINS | {'ValueError'}):
            return False
        body = node.body[1:] if node.body and _inert(node.body[0]) else node.body
        if not body or not _body(body, names):
            return False
        found |= node.name == target
    return found


def pure_imported_calls(source, calls, *, path, read):
    """Require a unique local `from package.module import function` source."""
    tree = _tree(source)
    if tree is None:
        return False
    imports = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for alias in node.names:
                imports[alias.asname or alias.name] = (node.module, alias.name)
    parts = PurePosixPath(path.replace('\\', '/')).parts
    roots = {'', 'src', *('/'.join(parts[:depth]) for depth in range(1, len(parts)))}
    for call in calls:
        if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name) or call.func.id not in imports:
            return False
        module, name = imports[call.func.id]
        relative = module.replace('.', '/')
        candidates = []
        for root in sorted(roots):
            prefix = root + '/' if root else ''
            for suffix in ('.py', '/__init__.py'):
                candidate = prefix + relative + suffix
                data = read(candidate)
                if data is not None:
                    candidates.append((candidate, data))
        if len(candidates) != 1 or not _pure_module(candidates[0][1], name):
            return False
        selected = PurePosixPath(candidates[0][0]).parts
        for depth in range(1, len(selected)):
            initializer = '/'.join(selected[:depth]) + '/__init__.py'
            if initializer == candidates[0][0]:
                continue
            data = read(initializer)
            if data is not None:
                parsed = _tree(data)
                if parsed is None or not all(_inert(node) for node in parsed.body):
                    return False
    return True

"""A source proof for order-independent calls on concrete built-in values.

Plain pure functions use closed builtins or narrowly recognized fresh-local
collection/regex idioms. A sole re import needs separate repository-shadow
checks. No repository function is evaluated by this proof.
"""

import ast
from pathlib import PurePosixPath

from checkwash.frontends.python.oracle_collections import fresh_fill_none, fresh_interleave, fresh_unique_merge, fresh_unique_sequence
from checkwash.frontends.python.oracle_regex import closed_regex_body
from checkwash.frontends.python.oracle_scalar_algorithms import closed_euclidean, closed_ordinal


_BUILTINS = {'len', 'range', 'all', 'any', 'max', 'min', 'abs', 'sum', 'zip', 'int', 'str', 'list', 'set', 'sorted', 'round'}


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
    if isinstance(node, ast.Dict):
        return all(key is not None and _expression(key, names) and _expression(value, names)
                   for key, value in zip(node.keys, node.values))
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
        if (isinstance(node.func, ast.Attribute)
                and node.func.attr in {'replace', 'strip', 'lstrip', 'rstrip', 'split', 'rsplit', 'join', 'lower', 'upper', 'casefold', 'startswith', 'isdigit'}):
            # Parameters and every admitted intermediate value are concrete
            # builtins. These string/bytes methods cannot mutate a receiver
            # or invoke an external callback; other receivers raise normally.
            return (not node.keywords and _expression(node.func.value, names)
                    and all(_expression(arg, names) for arg in node.args))
        return (isinstance(node.func, ast.Name) and node.func.id in _BUILTINS and node.func.id not in names
                and not node.keywords and all(_expression(arg, names) for arg in node.args))
    if isinstance(node, (ast.GeneratorExp, ast.ListComp)) and len(node.generators) == 1:
        generator = node.generators[0]
        target = generator.target
        if isinstance(target, ast.Name):
            bound = [target.id]
        elif isinstance(target, (ast.Tuple, ast.List)) and all(isinstance(item, ast.Name) for item in target.elts):
            bound = [item.id for item in target.elts]
        else:
            return False
        if (generator.is_async or not bound or len(bound) != len(set(bound))
                or set(bound) & (names | _BUILTINS | {'ValueError'})
                or not _expression(generator.iter, names)):
            return False
        inner = names | set(bound)
        return _expression(node.elt, inner) and all(_expression(item, inner) for item in generator.ifs)
    return False


def _numeric(node, names):
    if isinstance(node, ast.Constant):
        return type(node.value) in (int, float)
    if isinstance(node, ast.Name):
        return node.id in names
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        return _numeric(node.operand, names)
    return (isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod))
            and _numeric(node.left, names) and _numeric(node.right, names))


def _body(statements, names, numbers=frozenset()):
    names, numbers = set(names), set(numbers)
    for node in statements:
        if isinstance(node, ast.Return) and node.value is not None and _expression(node.value, names):
            continue
        if (isinstance(node, ast.If) and _expression(node.test, names)
                and _body(node.body, names, numbers) and _body(node.orelse, names, numbers)):
            continue
        if (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id not in _BUILTINS | {'ValueError'}
                and not node.targets[0].id.startswith('__') and _expression(node.value, names)):
            target = node.targets[0].id
            numeric = _numeric(node.value, numbers)
            if target in numbers and not numeric:
                return False  # never turn a proven scalar accumulator into a mutable alias
            names.add(target)
            if numeric:
                numbers.add(target)
            continue
        if (isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name) and node.target.id in numbers
                and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult)) and _numeric(node.value, numbers)):
            continue
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], (ast.Tuple, ast.List))
                and isinstance(node.value, (ast.Tuple, ast.List))
                and len(node.targets[0].elts) == len(node.value.elts)
                and all(isinstance(target, ast.Name) and target.id not in _BUILTINS | {'ValueError'}
                        and not target.id.startswith('__') for target in node.targets[0].elts)
                and all(_numeric(value, numbers) for value in node.value.elts)):
            targets = [target.id for target in node.targets[0].elts]
            if not targets or len(targets) != len(set(targets)):
                return False
            names.update(targets)
            numbers.update(targets)
            continue
        if (isinstance(node, ast.For) and isinstance(node.target, ast.Name)
                and node.target.id not in _BUILTINS | {'ValueError'} and not node.target.id.startswith('__')
                and not node.orelse and isinstance(node.iter, ast.Call) and isinstance(node.iter.func, ast.Name)
                and node.iter.func.id == 'range' and _expression(node.iter, names)
                and _body(node.body, names | {node.target.id}, numbers | {node.target.id})):
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
    found, bound, regex = False, set(), False
    for node in tree.body:
        if _inert(node):
            continue
        if (not bound and isinstance(node, ast.Import) and len(node.names) == 1
                and node.names[0].name == 're' and node.names[0].asname is None):
            bound.add('re')
            regex = True
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
        if not body or not (_body(body, names) or fresh_unique_merge(body, [arg.arg for arg in args.args])
                            or fresh_interleave(body, [arg.arg for arg in args.args])
                            or fresh_unique_sequence(body, [arg.arg for arg in args.args])
                            or closed_euclidean(body, [arg.arg for arg in args.args])
                            or closed_ordinal(body, [arg.arg for arg in args.args])
                            or regex and closed_regex_body(body, [arg.arg for arg in args.args])):
            return False
        found |= node.name == target
    return found


def primitive_literal_result(source, target, call):
    """Import-free primitive operations on literal inputs have no user format hooks.

    The function grammar cannot construct custom objects, import callbacks or
    mutate an input. Literal defaults and built-in containers keep all reachable
    values primitive; failures raise before the assertion rather than passing it.
    """
    return (all(_literal(arg) for arg in call.args)
            and all(keyword.arg is not None and _literal(keyword.value) for keyword in call.keywords)
            and _pure_module(source, target))


def shared_literal_collection_inputs(source, target, call):
    """Closed fresh collection results cannot mutate shared flat fixture rows.

    This requires the complete fresh-local collection grammar, not just the
    presence of list/set constructors or an apparent return type. Arbitrary
    mutable parameters retain their original execution and alias semantics.
    """
    if call.keywords or len(call.args) != 2 or not _pure_module(source, target):
        return False
    tree = _tree(source)
    function = next((node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == target), None)
    if function is None:
        return False
    def scalar(node):
        return isinstance(node, ast.Constant) and type(node.value) in (type(None), bool, int, float, str, bytes)
    def sequence(node):
        return isinstance(node, (ast.List, ast.Tuple)) and all(scalar(item) for item in node.elts)
    parameters = [arg.arg for arg in function.args.args]
    if fresh_fill_none(function.body, parameters):
        return sequence(call.args[0]) and scalar(call.args[1])
    return all(sequence(arg) for arg in call.args) and fresh_unique_merge(function.body, parameters)


def _unambiguous_import_parents(module, roots, selected_root, read):
    """A unique leaf must belong to the package Python can actually import.

    Namespace portions remain eligible until a regular package selects one
    root. Competing regular packages have unknown search-path order, and a
    module at a parent name cannot supply submodules. Never borrow a leaf
    from an excluded namespace portion or guess which regular package wins.
    """
    parts = module.split('.')
    if len(parts) > 16:
        return False
    active = set(roots)
    for depth in range(1, len(parts)):
        relative = '/'.join(parts[:depth])
        packages = set()
        for root in sorted(active):
            prefix = root + '/' if root else ''
            if read(prefix + relative + '.py') is not None:
                return False
            if read(prefix + relative + '/__init__.py') is not None:
                packages.add(root)
        if len(packages) > 1:
            return False
        if packages:
            active = packages
        if selected_root not in active:
            return False
    return True


def pure_imported_calls(source, calls, *, path, read, result_proof=None):
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
                    candidates.append((candidate, data, root))
        if len(candidates) != 1 or not (result_proof(candidates[0][1], name, call) if result_proof is not None
                                       else _pure_module(candidates[0][1], name)):
            return False
        if not _unambiguous_import_parents(module, roots, candidates[0][2], read):
            return False
        selected = PurePosixPath(candidates[0][0]).parts
        target_tree = _tree(candidates[0][1])
        if target_tree is None:
            return False
        if any(isinstance(node, ast.Import) and any(alias.name == 're' for alias in node.names) for node in target_tree.body):
            authority_roots = roots | {'/'.join(selected[:depth]) for depth in range(1, len(selected))}
            if any(read((root + '/' if root else '') + suffix) is not None
                   for root in authority_roots for suffix in ('re.py', 're/__init__.py')):
                return False
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

"""Closed visible-source authority for optional len/math.prod folding.

This is an effect check, not evaluation of repository functions. Every source
import and every function body in the graph must fit the small grammar. The
caller separately proves concrete primitive subject inputs and inert pytest
startup. Missing or ambiguous imports withhold this optional proof.
"""

from __future__ import annotations

import ast
from pathlib import PurePosixPath


class _Unsafe(Exception):
    pass


_EXCEPTIONS = {"ValueError", "TypeError", "ZeroDivisionError"}
_PROTECTED = {"len", *_EXCEPTIONS}
_HOOKS = {"setup_module", "teardown_module", "setup_function", "teardown_function",
          "setup", "teardown", "setUpModule", "tearDownModule"}


def _inert(node):
    return isinstance(node, ast.Pass) or (
        isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def _literal(node):
    # literal_eval alone is insufficient: it accepts set(), which could be a
    # repository function when evaluated as a default or module expression.
    if any(isinstance(item, (ast.Call, ast.Name)) for item in ast.walk(node)):
        return False
    try:
        ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return False
    return True


def _target_names(node):
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, (ast.Tuple, ast.List)):
        result = set()
        for item in node.elts:
            names = _target_names(item)
            if result & names:
                raise _Unsafe
            result.update(names)
        return result
    raise _Unsafe  # attribute/subscript writes can mutate shared authorities


def safe_call_graph(paths: tuple[str, ...], read) -> bool:
    """Check entry/helper sources and their complete bounded import closure.

    The supplied strict reader owns I/O failures and its overall read budget.
    No missing source, unproved external import, or unrecognized statement is
    treated as inert. Cyclic import graphs are conservatively unsupported.
    """
    cache, modules, active = {}, {}, set()

    def source(path):
        if path not in cache:
            cache[path] = read(path)
        value = cache[path]
        if value is not None and (not isinstance(value, bytes) or len(value) > 65_536):
            raise _Unsafe
        return value

    def roots(path):
        parts = PurePosixPath(path).parts
        return {"", "src", *("/".join(parts[:n]) for n in range(1, len(parts)))}

    def valid_path(path):
        return (isinstance(path, str) and bool(path) and "\\" not in path and ":" not in path
                and not path.startswith("/") and all(p not in {"", ".", ".."} for p in path.split("/")))

    def math_authority(owner):
        for root in sorted(roots(owner)):
            prefix = root + "/" if root else ""
            for suffix in ("math.py", "math/__init__.py"):
                if source(prefix + suffix) is not None:
                    raise _Unsafe

    def resolve(owner, dotted, level=0):
        if not dotted or not all(part.isidentifier() for part in dotted.split(".")):
            raise _Unsafe
        relative = dotted.replace(".", "/")
        if level:
            directory = list(PurePosixPath(owner).parent.parts)
            if level > len(directory):
                raise _Unsafe
            selected_roots = {"/".join(directory[:len(directory) - level + 1])}
        else:
            selected_roots = roots(owner)
        candidates = []
        for root in sorted(selected_roots):
            prefix = root + "/" if root else ""
            for suffix in (".py", "/__init__.py"):
                candidate = prefix + relative + suffix
                if source(candidate) is not None:
                    candidates.append((candidate, root))
        if len(candidates) != 1:
            raise _Unsafe
        selected, root = candidates[0]
        # A module file at a package prefix prevents that package import.
        pieces = relative.split("/")
        prefix = root + "/" if root else ""
        for depth in range(1, len(pieces)):
            package = prefix + "/".join(pieces[:depth])
            if source(package + ".py") is not None:
                raise _Unsafe
            # A different search root can win at a package prefix before the
            # otherwise unique leaf is considered. Its initializer can also
            # mutate math and extend __path__, so leaf uniqueness is not
            # sufficient authority for src/app/calc.py versus root/app/.
            for alternate in sorted(selected_roots - {root}):
                alternate_prefix = alternate + "/" if alternate else ""
                other = alternate_prefix + "/".join(pieces[:depth])
                if source(other + ".py") is not None or source(other + "/__init__.py") is not None:
                    raise _Unsafe
        return selected

    def load(path):
        if path in active or len(modules) + len(active) >= 32:
            raise _Unsafe
        if path in modules:
            return modules[path]
        if not valid_path(path) or source(path) is None:
            raise _Unsafe
        active.add(path)
        tree = ast.parse(source(path))
        if sum(1 for _ in ast.walk(tree)) > 4096:
            raise _Unsafe
        functions, imports, constants, bindings = {}, {}, set(), set()

        def bind(name):
            if name in bindings or name in _PROTECTED or name.startswith("__"):
                raise _Unsafe
            bindings.add(name)

        for node in tree.body:
            if _inert(node):
                continue
            if isinstance(node, ast.FunctionDef):
                bind(node.name)
                if node.name in _HOOKS or node.name.startswith("pytest_"):
                    raise _Unsafe
                functions[node.name] = node
            elif isinstance(node, ast.Assign) and _literal(node.value):
                for target in node.targets:
                    for name in _target_names(target):
                        bind(name)
                        constants.add(name)
            elif isinstance(node, ast.Import):
                for item in node.names:
                    name = item.asname or item.name.split(".")[0]
                    bind(name)
                    if item.name == "math":
                        math_authority(path)
                        imports[name] = ("math",)
                    else:
                        imported = resolve(path, item.name)
                        tail = "" if item.asname else item.name.partition(".")[2]
                        imports[name] = ("module", imported, tail)
            elif isinstance(node, ast.ImportFrom) and node.module:
                for item in node.names:
                    if item.name == "*":
                        raise _Unsafe
                    name = item.asname or item.name
                    bind(name)
                    if node.module == "math" and not node.level and item.name == "prod":
                        math_authority(path)
                        imports[name] = ("prod",)
                    else:
                        imports[name] = ("member", resolve(path, node.module, node.level), item.name)
            else:
                raise _Unsafe

        protected = _PROTECTED | {name for name, value in imports.items() if value[0] in {"math", "prod"}}
        imported_modules = {value[1] for value in imports.values() if value[0] in {"module", "member"}}
        for imported in sorted(imported_modules):
            load(imported)

        # Parent initializers also execute during import. Literal assignments
        # and definitions are allowed only after the same full graph check.
        parts = PurePosixPath(path).parts
        for depth in range(1, len(parts)):
            initializer = "/".join(parts[:depth]) + "/__init__.py"
            if initializer != path and source(initializer) is not None:
                load(initializer)

        def exported(module_path, member, seen=()):
            if (module_path, member) in seen:
                raise _Unsafe
            other = load(module_path)
            if member in other[0]:
                return True
            value = other[1].get(member)
            if value and value[0] == "member":
                return exported(value[1], value[2], (*seen, (module_path, member)))
            return False

        for value in imports.values():
            if value[0] == "member" and not exported(value[1], value[2]):
                raise _Unsafe

        def callee(node, local):
            if isinstance(node, ast.Name):
                if node.id in local or node.id in constants:
                    return False
                if node.id == "len" or node.id in functions:
                    return True
                value = imports.get(node.id)
                return bool(value and (value[0] == "prod" or value[0] == "member" and exported(value[1], value[2])))
            parts = []
            while isinstance(node, ast.Attribute):
                parts.insert(0, node.attr)
                node = node.value
            if not isinstance(node, ast.Name) or node.id in local:
                return False
            value = imports.get(node.id)
            if value is None:
                return False
            if value[0] == "math":
                return parts == ["prod"]
            if value[0] == "module":
                prefix = value[2].split(".") if value[2] else []
                return (parts[:len(prefix)] == prefix and len(parts) == len(prefix) + 1
                        and exported(value[1], parts[-1]))
            return False

        def expression(node, local):
            if isinstance(node, ast.Constant):
                return type(node.value) in (type(None), bool, int, float, str, bytes)
            if isinstance(node, ast.Name):
                return node.id in local or node.id in constants
            if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
                return all(expression(item, local) for item in node.elts)
            if isinstance(node, ast.Dict):
                return all(k is not None and expression(k, local) and expression(v, local)
                           for k, v in zip(node.keys, node.values))
            if isinstance(node, (ast.UnaryOp, ast.BinOp, ast.BoolOp, ast.Compare, ast.IfExp)):
                return all(expression(item, local) for item in ast.iter_child_nodes(node) if isinstance(item, ast.expr))
            if isinstance(node, ast.Subscript):
                return expression(node.value, local) and expression(node.slice, local)
            if isinstance(node, ast.Slice):
                return all(item is None or expression(item, local) for item in (node.lower, node.upper, node.step))
            if isinstance(node, ast.Call):
                return (callee(node.func, local) and not any(k.arg is None for k in node.keywords)
                        and all(expression(a, local) for a in node.args)
                        and all(expression(k.value, local) for k in node.keywords))
            return False

        def body(statements, local):
            for node in statements:
                if _inert(node):
                    continue
                if isinstance(node, ast.Assign):
                    if not expression(node.value, local):
                        raise _Unsafe
                    for target in node.targets:
                        if _target_names(target) & protected:
                            raise _Unsafe
                elif isinstance(node, ast.AugAssign):
                    if not isinstance(node.target, ast.Name) or node.target.id in protected or not expression(node.value, local):
                        raise _Unsafe
                    # A local alias can still refer to a parameter/global
                    # container. Only independently numeric-seeded locals
                    # may use in-place arithmetic (the product accumulator).
                    if node.target.id not in numeric_accumulators:
                        raise _Unsafe
                elif isinstance(node, ast.For):
                    if _target_names(node.target) & protected or not expression(node.iter, local):
                        raise _Unsafe
                    body(node.body, local)
                    body(node.orelse, local)
                elif isinstance(node, ast.If):
                    if not expression(node.test, local):
                        raise _Unsafe
                    body(node.body, local)
                    body(node.orelse, local)
                elif isinstance(node, ast.Return):
                    if node.value is not None and not expression(node.value, local):
                        raise _Unsafe
                elif isinstance(node, ast.Assert):
                    if not expression(node.test, local) or (node.msg is not None and not expression(node.msg, local)):
                        raise _Unsafe
                elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                    if not expression(node.value, local):
                        raise _Unsafe
                elif (isinstance(node, ast.Raise) and node.cause is None and isinstance(node.exc, ast.Call)
                      and isinstance(node.exc.func, ast.Name) and node.exc.func.id in _EXCEPTIONS
                      and not node.exc.keywords and all(_literal(a) for a in node.exc.args)):
                    continue
                else:
                    raise _Unsafe

        for function in functions.values():
            args = function.args
            if (function.decorator_list or function.returns or getattr(function, "type_params", ())
                    or args.posonlyargs or args.kwonlyargs or args.vararg or args.kwarg
                    or any(a.annotation for a in args.args) or not all(_literal(d) for d in args.defaults)):
                raise _Unsafe
            arguments = {arg.arg for arg in args.args}
            if arguments & protected or len(arguments) != len(args.args):
                raise _Unsafe
            if function.name.startswith("test") and arguments:
                raise _Unsafe
            local = arguments | {item.id for item in ast.walk(function)
                                 if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Store)}
            if local & protected:
                raise _Unsafe
            numeric_accumulators, other_bindings = set(), set(arguments)
            for item in ast.walk(function):
                if isinstance(item, ast.Assign):
                    numeric = (isinstance(item.value, ast.Constant) and type(item.value.value) in (int, float))
                    for target in item.targets:
                        target_names = _target_names(target)
                        if numeric and isinstance(target, ast.Name):
                            numeric_accumulators.update(target_names)
                        else:
                            other_bindings.update(target_names)
                elif isinstance(item, ast.For):
                    other_bindings.update(_target_names(item.target))
            numeric_accumulators.difference_update(other_bindings)
            body(function.body, local)
        active.remove(path)
        modules[path] = (functions, imports)
        return modules[path]

    try:
        if not paths or len(paths) > 2:
            return False
        for path in dict.fromkeys(paths):
            load(path)
        return True
    except (_Unsafe, SyntaxError, ValueError, TypeError, MemoryError, RecursionError):
        return False

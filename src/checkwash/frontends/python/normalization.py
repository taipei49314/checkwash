"""Closed-expression proof for redundant string normalization in a test.

This is not Python execution or name-based repair credit. A literal ASCII string
passes through a transparent same-file helper or inline string methods, then
through a one-parameter production function containing only a return. Both
production expressions must become structurally identical after projecting
known string methods. Unsupported syntax or uncertain bindings earns nothing.
"""

from __future__ import annotations

import ast
import copy
from pathlib import PurePosixPath

from checkwash.ir.astutil import argument_wraps

_METHODS = frozenset({"strip", "lstrip", "rstrip", "lower", "upper", "casefold"})
_MAX_READS = 64
_MAX_SOURCE = 100_000


class _Unproved(Exception):
    pass


def _tree(source):
    if source is None or len(source) > _MAX_SOURCE:
        raise _Unproved
    try:
        tree = ast.parse(source.decode("utf-8-sig"))
    except (UnicodeError, SyntaxError, ValueError, RecursionError, MemoryError):
        raise _Unproved from None
    if sum(1 for _ in ast.walk(tree)) > 4096:
        raise _Unproved
    return tree


def _docstring(node):
    return isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)


def _plain_function(node, arity):
    if not isinstance(node, ast.FunctionDef):
        raise _Unproved
    args = node.args
    params = [*args.posonlyargs, *args.args]
    if (len(params) != arity or node.decorator_list or node.returns
            or getattr(node, "type_params", ()) or args.defaults or args.kwonlyargs
            or args.vararg or args.kwarg or any(p.annotation for p in params)):
        raise _Unproved
    return params


def _return_function(node):
    params = _plain_function(node, 1)
    if len(node.body) != 1 or not isinstance(node.body[0], ast.Return) or node.body[0].value is None:
        raise _Unproved
    return params[0].arg, node.body[0].value


def _string_chain(node, parameter):
    if isinstance(node, ast.Name) and node.id == parameter:
        return True
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr in _METHODS and not node.args and not node.keywords
            and _string_chain(node.func.value, parameter))


def _project(node, bindings, helpers, depth=0):
    """Project a small closed grammar; never eval or invoke repository code."""
    if depth > 16:
        raise _Unproved
    descend = lambda n: _project(n, bindings, helpers, depth + 1)
    if isinstance(node, ast.Constant):
        if type(node.value) not in (str, bool, int, type(None)):
            raise _Unproved
        # Python minor versions carry different Unicode tables. Keeping this
        # proof to ASCII prevents host Unicode versions changing its verdict.
        if isinstance(node.value, str) and (len(node.value) > 4096 or not node.value.isascii()):
            raise _Unproved
        return copy.deepcopy(node)
    if isinstance(node, ast.Name) and node.id in bindings:
        return copy.deepcopy(bindings[node.id])
    if isinstance(node, (ast.Set, ast.List, ast.Tuple)) and len(node.elts) <= 32:
        result = copy.copy(node)
        result.elts = [descend(n) for n in node.elts]
        return result
    if isinstance(node, ast.Compare) and len(node.ops) == 1 and isinstance(
        node.ops[0], (ast.Eq, ast.NotEq, ast.In, ast.NotIn)
    ):
        return ast.Compare(left=descend(node.left), ops=node.ops,
                           comparators=[descend(node.comparators[0])])
    if isinstance(node, ast.Call) and not node.keywords:
        if (isinstance(node.func, ast.Attribute) and node.func.attr in _METHODS
                and not node.args):
            value = descend(node.func.value)
            if not isinstance(value, ast.Constant) or type(value.value) is not str:
                raise _Unproved
            # These are fixed stdlib str methods on an exact built-in str.
            return ast.Constant(value=getattr(str, node.func.attr)(value.value))
        if isinstance(node.func, ast.Name) and node.func.id in helpers and len(node.args) == 1:
            parameter, expression = helpers[node.func.id]
            value = descend(node.args[0])
            return _project(expression, {parameter: value}, {}, depth + 1)
    raise _Unproved


def _caller(source, qualname):
    tree = _tree(source)
    imports, helpers, target = {}, {}, None
    assertions = []
    occupied = set()
    for node in tree.body:
        if _docstring(node):
            continue
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            for alias in node.names:
                name = alias.asname or alias.name
                if alias.name == "*" or name in occupied:
                    raise _Unproved
                occupied.add(name)
                imports[name] = (node.module, alias.name)
        elif isinstance(node, ast.FunctionDef) and node.name.startswith("test"):
            _plain_function(node, 0)
            if node.name in occupied or len(node.body) != 1 or not isinstance(node.body[0], ast.Assert):
                raise _Unproved
            assertion = node.body[0]
            if (assertion.msg is not None or not isinstance(assertion.test, ast.Compare)
                    or len(assertion.test.ops) != 1):
                raise _Unproved
            occupied.add(node.name)
            assertions.append(assertion)
            if node.name == qualname:
                target = assertion
        elif isinstance(node, ast.FunctionDef) and not node.name.startswith("test"):
            parameter, expression = _return_function(node)
            if node.name in occupied or not _string_chain(expression, parameter):
                raise _Unproved
            occupied.add(node.name)
            helpers[node.name] = (parameter, expression)
        else:
            # Executable module statements, conditional bindings,
            # assignments and decorators are outside this closed caller proof.
            raise _Unproved
    if target is None:
        raise _Unproved
    # Companion tests can execute too. Admit only the same closed literal
    # calls, never a harmless-looking assert that mutates the imported callee.
    for assertion in assertions:
        call = assertion.test.left
        if (not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name)
                or call.func.id not in imports or len(call.args) != 1 or call.keywords
                or not isinstance(assertion.test.comparators[0], ast.Constant)):
            raise _Unproved
        argument = _project(call.args[0], {}, helpers)
        if not isinstance(argument, ast.Constant) or type(argument.value) is not str:
            raise _Unproved
    return imports, helpers, target


def _production(module, original, path, read):
    parts = module.split(".")
    if len(parts) > 4 or not all(p.isidentifier() for p in parts):
        raise _Unproved
    prefixes = sorted({"", "src/", str(PurePosixPath(path).parent) + "/"})
    candidates = []
    for prefix in prefixes:
        stem = prefix + "/".join(parts)
        for candidate in (stem + ".py", stem + "/__init__.py"):
            source = read(candidate)
            if source is not None:
                candidates.append((candidate, source))
        # Package initialization must be inert, and a module with the same
        # package name must not shadow the candidate under another path root.
        for depth in range(1, len(parts)):
            parent = prefix + "/".join(parts[:depth])
            if read(parent + ".py") is not None:
                raise _Unproved
            init = read(parent + "/__init__.py")
            if init is not None and any(not _docstring(n) for n in _tree(init).body):
                raise _Unproved
    if len(candidates) != 1:
        raise _Unproved
    tree = _tree(candidates[0][1])
    body = [n for n in tree.body if not _docstring(n)]
    if len(body) != 1 or not isinstance(body[0], ast.FunctionDef) or body[0].name != original:
        raise _Unproved
    return _return_function(body[0])


def _equivalent(before, after, qualname, path, read):
    b_imports, _b_helpers, b_assert = _caller(before, qualname)
    a_imports, a_helpers, a_assert = _caller(after, qualname)
    b, a = b_assert.test.left, a_assert.test.left
    if (len(b_imports) != 1 or b_imports != a_imports or not isinstance(b, ast.Call) or not isinstance(a, ast.Call)
            or not isinstance(b.func, ast.Name) or ast.dump(b.func) != ast.dump(a.func)
            or b.func.id not in b_imports or len(b.args) != 1 or len(a.args) != 1
            or b.keywords or a.keywords or not isinstance(b.args[0], ast.Constant)
            or type(b.args[0].value) is not str):
        raise _Unproved
    # The oracle and polarity must be exactly the same, independently of the
    # detector's literal metadata. Only its subject is replaced for comparison.
    old_compare, new_compare = copy.deepcopy(b_assert.test), copy.deepcopy(a_assert.test)
    expected = old_compare.comparators[0]
    operator = old_compare.ops[0]
    if isinstance(operator, (ast.Is, ast.IsNot)):
        if not isinstance(expected, ast.Constant) or type(expected.value) not in (bool, type(None)):
            raise _Unproved
    elif not isinstance(operator, (ast.Eq, ast.NotEq)) or not isinstance(expected, ast.Constant):
        raise _Unproved
    old_compare.left = new_compare.left = ast.Constant(value=None)
    if ast.dump(old_compare) != ast.dump(new_compare):
        raise _Unproved
    module, original = b_imports[b.func.id]
    parameter, expression = _production(module, original, path, read)
    old_value = _project(b.args[0], {}, {})
    new_value = _project(a.args[0], {}, a_helpers)
    if not isinstance(new_value, ast.Constant) or type(new_value.value) is not str:
        raise _Unproved
    old_result = _project(expression, {parameter: old_value}, {})
    new_result = _project(expression, {parameter: new_value}, {})
    return ast.dump(old_result) == ast.dump(new_result)


def mark_normalization_equivalence(ir, raw_by_path, root_reader):
    """Attach proof only for unchanged production read from a strict snapshot.

    The historical head_reader treats read failures as absence, so it cannot
    participate. Missing strict callbacks or exhausted proof budgets keep the
    finding. A real strict-reader error propagates as an engine error.
    """
    cache = {}

    def read(path):
        if path not in cache:
            if path in raw_by_path:
                before, after = raw_by_path[path]
                if before != after:
                    raise _Unproved
                cache[path] = after
            else:
                if root_reader is None or len(cache) >= _MAX_READS:
                    raise _Unproved
                cache[path] = root_reader(path)
        return cache[path]

    for file in ir.files:
        if file.language != "python" or file.role != "test" or file.path not in raw_by_path:
            continue
        if any(path != file.path and before != after
               for path, (before, after) in raw_by_path.items()):
            continue
        before, after = raw_by_path[file.path]
        proven = []
        for unit in file.units:
            if unit.before is None or unit.after is None or unit.delta is None:
                continue
            b_by_id = {a.id: a for a in unit.before.assertions}
            a_by_id = {a.id: a for a in unit.after.assertions}
            for pair in unit.delta.assertion_pairs:
                b, a = b_by_id[pair.before_id], a_by_id[pair.after_id]
                if b.inherited or a.inherited or not argument_wraps(b.left, a.left):
                    continue
                try:
                    if _equivalent(before, after, unit.qualname, file.path, read):
                        proven.append((unit.qualname, b.id, a.id))
                except (_Unproved, RecursionError, MemoryError):
                    pass
        file.normalization_equivalent_pairs = tuple(sorted(proven))

"""One bounded pytest item callback replacement, without executing source.

Only a directly imported hookimpl(tryfirst=True), normal synchronous
pytest_runtest_call(item), and literal zero-argument lambda: None are read.
Unknown execution invalidates this new proof, never other runtime channels.
Native import spelling follows the existing frontend convention; repository
import shadowing and other plugins' later effects are not resolved here.
"""
from __future__ import annotations

import ast


_HOOK = "pytest_runtest_call"
_ITEM, _ORIGINAL, _NOOP = "item", "original", "noop"


def _literal_branch(node):
    negate = False
    while isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        negate, node = not negate, node.operand
    if isinstance(node, ast.Constant) and type(node.value) is bool:
        return not node.value if negate else node.value
    return None


def _statements(body):
    """Walk selected literal branches once; unknown compounds remain opaque."""
    pending = list(reversed(body))
    while pending:
        statement = pending.pop()
        if isinstance(statement, ast.If):
            branch = _literal_branch(statement.test)
            if branch is not None:
                pending.extend(reversed(statement.body if branch else statement.orelse))
                continue
        yield statement


def _plain_function(node):
    args = node.args
    return (isinstance(node, ast.FunctionDef) and not node.returns
            and not getattr(node, "type_params", ()) and not args.defaults
            and not any(value is not None for value in args.kw_defaults)
            and not any(arg.annotation for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs,
                *([args.vararg] if args.vararg else []), *([args.kwarg] if args.kwarg else [])]))


def _hook_decorator(node, imports):
    if not isinstance(node, ast.Call) or node.args or len(node.keywords) != 1:
        return False
    keyword = node.keywords[0]
    if not (keyword.arg == "tryfirst" and isinstance(keyword.value, ast.Constant)
            and keyword.value.value is True):
        return False
    function = node.func
    if isinstance(function, ast.Name):
        return imports.get(function.id) == "pytest.hookimpl"
    return (isinstance(function, ast.Attribute) and function.attr == "hookimpl"
            and isinstance(function.value, ast.Name) and imports.get(function.value.id) == "pytest")


def _ordinary_body(function):
    # A yield in a literal dead branch still makes the entire function a
    # generator. Nested callable bodies do not change the hook's function kind.
    pending = list(function.body)
    while pending:
        node = pending.pop()
        if isinstance(node, (ast.Yield, ast.YieldFrom, ast.Await, ast.Global, ast.Nonlocal)):
            return False
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            pending.extend(ast.iter_child_nodes(node))
    return True


def _live_hook(tree):
    """Decorator authority is read at definition time, hook identity at exit."""
    imports, selected = {}, None
    for node in _statements(tree.body):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.asname or alias.name.split(".")[0]
                imports[name] = "pytest" if alias.name == "pytest" else None
                if name == _HOOK:
                    selected = None
        elif isinstance(node, ast.ImportFrom):
            if any(alias.name == "*" for alias in node.names):
                return None
            for alias in node.names:
                name = alias.asname or alias.name
                imports[name] = ("pytest.hookimpl" if not node.level and node.module == "pytest"
                                 and alias.name == "hookimpl" else None)
                if name == _HOOK:
                    selected = None
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not _plain_function(node):
                return None
            if node.name == _HOOK:
                args = node.args
                admitted = (not args.posonlyargs and [arg.arg for arg in args.args] == ["item"]
                            and not args.kwonlyargs and not args.vararg and not args.kwarg
                            and len(node.decorator_list) == 1
                            and _hook_decorator(node.decorator_list[0], imports) and _ordinary_body(node))
                if node.decorator_list and not admitted:
                    return None  # Arbitrary decorator execution is unknown.
                selected = node if admitted else None
            elif node.decorator_list:
                return None
            imports[node.name] = None
        elif (isinstance(node, ast.Assign) and len(node.targets) == 1
              and isinstance(node.targets[0], ast.Name)
              and isinstance(node.value, (ast.Constant, ast.Name))):
            if isinstance(node.value, ast.Name) and node.value.id not in imports:
                return None  # An unresolved read may fail before registration.
            name = node.targets[0].id
            imports[name] = None
            if name == _HOOK:
                selected = None
        elif isinstance(node, ast.Pass) or (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)):
            continue
        else:
            return None
    return selected


def _empty_lambda(node):
    if not isinstance(node, ast.Lambda):
        return False
    args = node.args
    return (not args.posonlyargs and not args.args and not args.kwonlyargs
            and not args.vararg and not args.kwarg and not args.defaults and not args.kw_defaults
            and isinstance(node.body, ast.Constant) and node.body.value is None)


def _replacement(function):
    # Alias names refer to one hook item and captures of its current method.
    # Rebinding a local name does not restore a method already set on the item.
    bindings, current, evidence = {"item": _ITEM}, _ORIGINAL, None
    for node in _statements(function.body):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            value, target = node.value, node.targets[0]
            if isinstance(value, ast.Name):
                if value.id not in bindings:
                    return None  # Unknown global/undefined reads are not normal-exit proof.
                kind = bindings.get(value.id)
            elif isinstance(value, ast.Attribute) and value.attr == "runtest" and isinstance(value.value, ast.Name):
                if bindings.get(value.value.id) != _ITEM:
                    return None
                kind = current
            elif _empty_lambda(value):
                kind = _NOOP
            elif isinstance(value, ast.Constant):
                kind = None
            elif (isinstance(value, ast.Lambda) and not value.args.defaults
                  and not any(default is not None for default in value.args.kw_defaults)):
                kind = None  # Construction is inert; its body is not a no-op proof.
            else:
                return None
            if isinstance(target, ast.Name):
                bindings[target.id] = kind
            elif (isinstance(target, ast.Attribute) and target.attr == "runtest"
                  and isinstance(target.value, ast.Name) and bindings.get(target.value.id) == _ITEM):
                current = kind
                evidence = node if kind == _NOOP else None
            else:
                return None
        elif isinstance(node, ast.FunctionDef) and _plain_function(node) and not node.decorator_list:
            bindings[node.name] = None  # An uncalled body has no runtime effect.
        elif isinstance(node, ast.Return):
            return evidence if node.value is None or isinstance(node.value, ast.Constant) else None
        elif isinstance(node, ast.Raise):
            return None
        elif isinstance(node, ast.Pass) or (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)):
            continue
        else:
            # Calls/escapes, yield, try/finally, loops and unknown predicates
            # can execute or restore the original. Never retain a stale label.
            return None
    return evidence


def item_callback_controls(tree: ast.Module):
    function = _live_hook(tree)
    if function is not None:
        evidence = _replacement(function)
        if evidence is not None:
            yield "conftest.runtime.pytest_runtest_call.item-runtest-noop", evidence

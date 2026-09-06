"""Bounded import/binding evidence for conftest patch targets.

This recognizes imported APIs and pytest's standard fixture parameters. It
does not infer the behaviour of arbitrary functions merely named ``patch``
or arbitrary objects merely named ``monkeypatch``.
"""

from __future__ import annotations

import ast


def _resolve(node, bindings):
    if isinstance(node, ast.Name):
        return bindings.get(node.id)
    if isinstance(node, ast.Attribute):
        base = _resolve(node.value, bindings)
        return f"{base}.{node.attr}" if base else None
    return None


def _names(node):
    """Names assigned in this scope; nested scope bodies do not bind here."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {node.name}
    if isinstance(node, ast.Import):
        return {a.asname or a.name.split(".")[0] for a in node.names}
    if isinstance(node, ast.ImportFrom):
        return {a.asname or a.name for a in node.names}
    if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
        return {node.id}
    if isinstance(node, ast.ExceptHandler) and node.name:
        return {node.name} | set().union(*(_names(n) for n in node.body))
    return set().union(*(_names(n) for n in ast.iter_child_nodes(node)))


def patch_calls(tree, source, module_exists, *, module_name=""):
    """Return proven patch calls aimed at repository code, with source text."""
    found = []
    functions = []

    def import_bindings(node, bindings):
        if isinstance(node, ast.Import):
            for alias in node.names:
                bindings[alias.asname or alias.name.split(".")[0]] = alias.name if alias.asname else alias.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                parent = module_name.split(".")[:-node.level]
                if not parent:
                    return
                module = ".".join([*parent, module] if module else parent)
            for alias in node.names:
                if alias.name != "*":
                    bindings[alias.asname or alias.name] = f"{module}.{alias.name}"

    def target(call, bindings):
        api = _resolve(call.func, bindings)
        if api not in {"@pytest.monkeypatch.setattr", "@pytest.monkeypatch.setitem", "@pytest.monkeypatch.set_attribute"}:
            return False
        arg = call.args[0] if call.args else next((k.value for k in call.keywords if k.arg == "target"), None)
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            # String forms name the attribute too. A bare module is not a
            # valid setattr string target and is not evidence of a patch.
            dotted = arg.value.rsplit(".", 1)[0] if "." in arg.value else ""
        else:
            dotted = _resolve(arg, bindings) or ""
        if dotted == "@pytest.request.module" or dotted.startswith("@pytest.request.module."):
            return True
        return bool(dotted) and module_exists(dotted)

    def expression(node, bindings):
        if isinstance(node, (ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            return  # these introduce another lexical scope
        if isinstance(node, ast.Call) and target(node, bindings):
            found.append(ast.get_source_segment(source, node) or ast.unparse(node))
        for child in ast.iter_child_nodes(node):
            expression(child, bindings)

    def block(statements, bindings, *, inspect=True, defer=False):
        for statement in statements:
            if isinstance(statement, (ast.Import, ast.ImportFrom)):
                import_bindings(statement, bindings)
                continue
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if inspect:
                    for decorator in statement.decorator_list:
                        expression(decorator, bindings)
                    if defer:
                        fixture = any(_resolve(d.func if isinstance(d, ast.Call) else d, bindings) == "pytest.fixture" for d in statement.decorator_list)
                        functions.append((statement, fixture))
                bindings.pop(statement.name, None)
                continue
            if isinstance(statement, ast.ClassDef):
                bindings.pop(statement.name, None)
                continue
            if isinstance(statement, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith, ast.Try, ast.TryStar, ast.Match)):
                # Conditional writes cannot establish a single reaching
                # binding. Remove them before inspecting nested operations.
                nested = dict(bindings)
                for name in _names(statement):
                    nested.pop(name, None)
                for _field, value in ast.iter_fields(statement):
                    if isinstance(value, list) and value and all(isinstance(n, ast.stmt) for n in value):
                        block(value, nested, inspect=inspect)
                    elif isinstance(value, ast.expr) and inspect:
                        expression(value, nested)
                    elif isinstance(value, list):
                        for item in value:
                            if isinstance(item, ast.withitem) and inspect:
                                expression(item.context_expr, nested)
                            elif isinstance(item, ast.ExceptHandler):
                                block(item.body, nested, inspect=inspect)
                            elif isinstance(item, ast.match_case):
                                block(item.body, nested, inspect=inspect)
                for name in _names(statement):
                    bindings.pop(name, None)
                continue
            if inspect:
                expression(statement, bindings)
            assigned = _names(statement)
            for name in assigned:
                bindings.pop(name, None)
            # A locally constructed pytest MonkeyPatch has the same API as
            # the builtin fixture. Arbitrary constructor results do not.
            if isinstance(statement, (ast.Assign, ast.AnnAssign)) and isinstance(statement.value, ast.Call):
                if _resolve(statement.value.func, bindings) == "pytest.MonkeyPatch":
                    for name in assigned:
                        bindings[name] = "@pytest.monkeypatch"
        return bindings

    final_globals = block(tree.body, {}, inspect=False)
    block(tree.body, {}, defer=True)
    defined_names = set().union(*(_names(n) for n in tree.body))
    for function, fixture in functions:
        bindings = dict(final_globals)
        params = [*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs]
        params += [p for p in (function.args.vararg, function.args.kwarg) if p is not None]
        locals_ = set().union(*(_names(n) for n in function.body))
        for name in locals_ | {p.arg for p in params}:
            bindings.pop(name, None)
        if fixture:
            for parameter in params:
                if parameter.arg in {"monkeypatch", "request"} and parameter.arg not in defined_names:
                    bindings[parameter.arg] = f"@pytest.{parameter.arg}"
        block(function.body, bindings)
    return found

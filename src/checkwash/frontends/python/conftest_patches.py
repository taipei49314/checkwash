"""Bounded import/binding evidence for conftest patch targets.

This recognizes imported APIs and pytest's standard fixture parameters. It
does not infer the behaviour of arbitrary functions merely named ``patch``
or arbitrary objects merely named ``monkeypatch``.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass


@dataclass
class _Patcher:
    call: ast.Call
    bindings: dict


# Bindings key for getattr-captured originals (never a valid Python name).
_CAPTURES = "@captures"


def _resolve(node, bindings):
    if isinstance(node, ast.Name):
        value = bindings.get(node.id)
        return value if isinstance(value, str) else None
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


def patch_calls(tree, source, module_exists, *, module_name="", source_segment=None):
    """Return proven patch calls aimed at repository code, with source text."""
    found = []
    functions = []
    segment = source_segment or (lambda node: ast.get_source_segment(source, node))
    # Builtins the module never rebinds. A module-level `setattr = …` (or an
    # import of the name) makes every bare call ambiguous, including for the
    # late-binding functions defined here, so the native reading turns off.
    defined_names = set().union(*(_names(n) for n in tree.body))
    natives = {"setattr", "vars"} - defined_names

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

    def api_of(call, bindings):
        api = _resolve(call.func, bindings)
        if api is None and isinstance(call.func, ast.Name) and call.func.id in natives and call.func.id not in bindings:
            return f"builtins.{call.func.id}"
        return api

    def target(call, bindings):
        api = api_of(call, bindings)
        if api not in {
            "@pytest.monkeypatch.setattr", "@pytest.monkeypatch.setitem", "@pytest.monkeypatch.set_attribute",
            "unittest.mock.patch", "unittest.mock.patch.object",
            "builtins.setattr",
        }:
            return False
        if api == "builtins.setattr":
            # The builtin spells the same installation without a patcher
            # receiver (#85): setattr(request.module, "name", stand_in). It
            # only takes positional arguments, and an unreadable attribute
            # name is not evidence.
            if len(call.args) != 3 or call.keywords:
                return False
            if not (isinstance(call.args[1], ast.Constant) and isinstance(call.args[1].value, str)):
                return False
        arg = call.args[0] if call.args else next((k.value for k in call.keywords if k.arg == "target"), None)
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            if api in ("unittest.mock.patch.object", "builtins.setattr"):
                return False  # these require an object, not a string
            # String forms name the attribute too. A bare module is not a
            # valid setattr string target and is not evidence of a patch.
            dotted = arg.value.rsplit(".", 1)[0] if "." in arg.value else ""
        else:
            if api == "unittest.mock.patch":
                return False  # patch requires a qualified string target
            dotted = _resolve(arg, bindings) or ""
            if (not dotted and api == "@pytest.monkeypatch.setitem"
                    and isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name)
                    and arg.func.id == "vars" and "vars" in natives and "vars" not in bindings
                    and len(arg.args) == 1 and not arg.keywords):
                # setitem(vars(mod), "name", v) patches the module dictionary
                # directly — the request.module sibling from issue #85.
                dotted = _resolve(arg.args[0], bindings) or ""
        if dotted == "@pytest.request.module" or dotted.startswith("@pytest.request.module."):
            return True
        if api == "builtins.setattr":
            # Writing the test module's own namespace rewrites what live
            # assertions read at call time; writing a first-party module
            # object does not reach consumers that captured a from-import
            # first. Only the execution-proof trace may report those.
            return False
        return bool(dotted) and module_exists(dotted)

    def store_target(node, bindings):
        """`request.module.name = v` / `vars(request.module)["name"] = v` — the
        statement spellings of the #85 stand-in, which no patch call matches.
        Only request.module is proven here; first-party module stores stay
        with the execution-proof installation trace."""
        if isinstance(node, ast.Attribute):
            base = _resolve(node.value, bindings)
            return f"{base}.{node.attr}" if base else None
        if (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name) and node.value.func.id == "vars"
                and "vars" in natives and "vars" not in bindings
                and len(node.value.args) == 1 and not node.value.keywords
                and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str)):
            base = _resolve(node.value.args[0], bindings)
            return f"{base}.{node.slice.value}" if base else None
        return None

    def patcher(node, bindings):
        if isinstance(node, ast.Name):
            value = bindings.get(node.id)
            return value if isinstance(value, _Patcher) else None
        if isinstance(node, ast.Call) and _resolve(node.func, bindings) in {
            "unittest.mock.patch", "unittest.mock.patch.object",
        }:
            return _Patcher(node, dict(bindings))
        return None

    def activate(node, bindings):
        value = patcher(node, bindings)
        if value is not None and target(value.call, value.bindings):
            found.append(segment(value.call) or ast.unparse(value.call))

    def expression(node, bindings, *, activated=False):
        if isinstance(node, (ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            return  # these introduce another lexical scope
        if activated:
            activate(node, bindings)
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for item in targets:
                dotted = store_target(item, bindings)
                if dotted and (dotted == "@pytest.request.module" or dotted.startswith("@pytest.request.module.")):
                    found.append(segment(node) or ast.unparse(node))
        if isinstance(node, ast.Call):
            api = api_of(node, bindings)
            if api and (api.startswith("@pytest.monkeypatch.") or api == "builtins.setattr") and target(node, bindings):
                if api != "builtins.setattr" or not _restores_original(node, bindings):
                    found.append(segment(node) or ast.unparse(node))
            if (isinstance(node.func, ast.Attribute) and node.func.attr == "start"
                    and not node.args and not node.keywords):
                activate(node.func.value, bindings)
        for child in ast.iter_child_nodes(node):
            expression(child, bindings)

    def _restores_original(node, bindings):
        """setattr(X, "name", saved) where `saved` was captured by an earlier
        getattr(X, "name", …) is the teardown half of the installation — the
        install call already carries the evidence (issue #85's save/restore
        idiom must not double-report)."""
        if not isinstance(node.args[2], ast.Name):
            return False
        captured = (bindings.get(_CAPTURES) or {}).get(node.args[2].id)
        if not captured:
            return False
        obj = _resolve(node.args[0], bindings) or ""
        return bool(obj) and captured == f"{obj}.{node.args[1].value}"

    def _getattr_capture(node, bindings):
        """`name = getattr(obj, "attr", …)` as ("name", "obj.attr"), or None."""
        if not (isinstance(node, ast.Call) and 2 <= len(node.args) <= 3 and not node.keywords):
            return None
        api = _resolve(node.func, bindings)
        if api != "builtins.getattr" and not (
                api is None and isinstance(node.func, ast.Name) and node.func.id == "getattr"
                and "getattr" not in defined_names and "getattr" not in bindings):
            return None
        if not (isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str)):
            return None
        obj = _resolve(node.args[0], bindings)
        return f"{obj}.{node.args[1].value}" if obj else None

    def block(statements, bindings, *, inspect=True, defer=False):
        # Copy-on-write: captures recorded in a nested branch stay local to it.
        bindings[_CAPTURES] = dict(bindings.get(_CAPTURES) or {})
        for statement in statements:
            if isinstance(statement, (ast.Import, ast.ImportFrom)):
                import_bindings(statement, bindings)
                continue
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if inspect:
                    for decorator in statement.decorator_list:
                        expression(decorator, bindings, activated=True)
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
                entering = dict(bindings)
                for _field, value in ast.iter_fields(statement):
                    if isinstance(value, list) and value and all(isinstance(n, ast.stmt) for n in value):
                        block(value, dict(nested), inspect=inspect)
                    elif isinstance(value, ast.expr) and inspect:
                        expression(value, nested)
                    elif isinstance(value, list):
                        for item in value:
                            if isinstance(item, ast.withitem) and inspect:
                                # Enter before binding ``as`` targets or
                                # executing writes in the managed body.
                                expression(item.context_expr, entering, activated=True)
                                if item.optional_vars is not None:
                                    for name in _names(item.optional_vars):
                                        entering.pop(name, None)
                            elif isinstance(item, ast.ExceptHandler):
                                block(item.body, dict(nested), inspect=inspect)
                            elif isinstance(item, ast.match_case):
                                block(item.body, dict(nested), inspect=inspect)
                for name in _names(statement):
                    bindings.pop(name, None)
                continue
            if inspect:
                expression(statement, bindings)
            assigned = _names(statement)
            constructed = patcher(statement.value, bindings) if isinstance(statement, (ast.Assign, ast.AnnAssign)) else None
            for name in assigned:
                bindings.pop(name, None)
                bindings[_CAPTURES].pop(name, None)
            if isinstance(statement, (ast.Assign, ast.AnnAssign)):
                capture = _getattr_capture(statement.value, bindings)
                if capture:
                    targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
                    if len(targets) == 1 and isinstance(targets[0], ast.Name):
                        bindings[_CAPTURES][targets[0].id] = capture
            if constructed is not None:
                # Constructors are inert until a with/decorator/start use.
                # Record only direct name bindings; destructuring does not
                # establish which runtime object a later name denotes.
                targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
                for item in targets:
                    if isinstance(item, ast.Name):
                        bindings[item.id] = constructed
            # A locally constructed pytest MonkeyPatch has the same API as
            # the builtin fixture. Arbitrary constructor results do not.
            if isinstance(statement, (ast.Assign, ast.AnnAssign)) and isinstance(statement.value, ast.Call):
                if _resolve(statement.value.func, bindings) == "pytest.MonkeyPatch":
                    for name in assigned:
                        bindings[name] = "@pytest.monkeypatch"
        return bindings

    final_globals = block(tree.body, {}, inspect=False)
    block(tree.body, {}, defer=True)
    for function, fixture in functions:
        bindings = dict(final_globals)
        bindings[_CAPTURES] = dict(bindings.get(_CAPTURES) or {})
        params = [*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs]
        params += [p for p in (function.args.vararg, function.args.kwarg) if p is not None]
        locals_ = set().union(*(_names(n) for n in function.body))
        for name in locals_ | {p.arg for p in params}:
            bindings.pop(name, None)
            bindings[_CAPTURES].pop(name, None)
        for name in natives & (locals_ | {p.arg for p in params}):
            # A locally bound `setattr`/`vars` is not the builtin, even though
            # popping the local above would otherwise read as "unshadowed".
            bindings[name] = None
        if fixture:
            for parameter in params:
                if parameter.arg in {"monkeypatch", "request"} and parameter.arg not in defined_names:
                    bindings[parameter.arg] = f"@pytest.{parameter.arg}"
        block(function.body, bindings)
    return found

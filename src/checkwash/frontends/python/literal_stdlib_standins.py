"""Closed integer calls to an unshadowed stdlib replacement helper."""
from __future__ import annotations

import ast
from collections import ChainMap

from checkwash.change import EngineError
from checkwash.frontends.python.oracle_purity import imported_from, pure_imported_calls
from checkwash.frontends.python.snapshot_context import inert_test_execution_context


def _read(context, path):
    if path in context.changed:
        return context.changed[path][1]
    if path not in context.cache:
        if len(context.cache) >= 128:
            raise EngineError("stdlib replacement authority exceeds the snapshot read budget")
        value = context.reader(path)
        if value is not None and not isinstance(value, bytes):
            raise EngineError("stdlib replacement reader returned invalid source bytes")
        context.cache[path] = value
    return context.cache[path]


def literal_math_gcd_standin(function, call, bindings):
    from .subject_replacements import _resolve

    if not isinstance(function, ast.FunctionDef) or not isinstance(call, ast.Call):
        return False
    args = function.args
    parameters = [*args.posonlyargs, *args.args]
    if (function.decorator_list or function.returns or getattr(function, "type_params", ())
            or args.defaults or args.kw_defaults or args.kwonlyargs or args.vararg or args.kwarg
            or any(arg.annotation for arg in parameters) or call.keywords
            or len(call.args) != len(parameters) or len(parameters) != 2
            or len(function.body) != 1 or not isinstance(function.body[0], ast.Return)):
        return False
    try:
        # Custom __index__ methods can call production. Only exact integers
        # prove that stdlib gcd's argument conversion has no such callback.
        if any(type(ast.literal_eval(value)) is not int for value in call.args):
            return False
    except (ValueError, TypeError, RecursionError, MemoryError):
        return False
    expression = function.body[0].value
    names = {arg.arg for arg in parameters}
    # The parameters lie over the bindings, which are not copied (#469).
    return (isinstance(expression, ast.Call) and len(expression.args) == 2 and not expression.keywords
            and all(isinstance(value, ast.Name) and value.id in names for value in expression.args)
            and _resolve(expression.func, ChainMap({name: None for name in names}, bindings)) == "math.gcd")


def math_is_unshadowed(context, path):
    """Check conventional repository and test-directory Python import paths."""
    prefixes = {"", "src/"}
    directory = path.replace("\\", "/").rpartition("/")[0]
    for _ in range(16):
        if not directory:
            break
        prefixes.add(directory + "/")
        directory = directory.rpartition("/")[0]
    else:
        return False
    for prefix in sorted(prefixes):
        for suffix in ("math.py", "math/__init__.py"):
            candidate = prefix + suffix
            if _read(context, candidate) is not None:
                return False
    return True


def _top_level_imports(tree):
    """What the authority's statement check reads of `tree`: None when one
    of its top-level imports refuses every target, else the (module, name)
    pairs its other `from module import name` statements bind, each of
    which must be the target."""
    imported = set()
    for statement in tree.body:
        if isinstance(statement, ast.Import):
            if any(alias.name != 'math' for alias in statement.names):
                return None
        elif isinstance(statement, ast.ImportFrom):
            if statement.level:
                return None
            if statement.module == 'math':
                if any(alias.name != 'gcd' for alias in statement.names):
                    return None
            else:
                imported.update((statement.module, alias.name) for alias in statement.names)
    return imported


def math_import_authority(source, tree, old_call, target, path, context, search, kept=None):
    """No imported source or repository startup can replace stdlib gcd.

    A file-shadow check alone is insufficient: the production module itself
    could assign math.gcd = production. Require the complete imported module
    and package initializers to satisfy the existing closed source grammar,
    and inspect the complete conventional test startup inventory as well.

    `kept` is a dict the subject-replacement pass keeps for one file (#469),
    in which each part of the check is made once, when first asked, so that
    no part is made again for each test. The statement check reads only
    `tree` and the target, so the file's imports are read once and each
    target is compared with them. `pure_imported_calls` reads the old call
    only for what its callee's name imports in `source`, so its answer is
    kept per imported function; the startup check reads neither, so it is
    made once. Besides `source` and `tree` the check reads the repository,
    through `search` and through `context`, whose cache keeps every source
    it reads, so for a snapshot that does not change during the run a kept
    answer is the one a fresh check gives. Without `kept`, the check is made
    afresh.
    """
    module_name, _, function_name = target.rpartition('.')
    read = lambda candidate: _read(context, candidate)
    if kept is not None:
        if "statements" not in kept:
            kept["statements"] = _top_level_imports(tree)
        imported = kept["statements"]
        if imported is None or not imported <= {(module_name, function_name)}:
            return False
        if "table" not in kept:
            kept["table"] = imported_from(source)
        table = kept["table"]
        callee = old_call.func if isinstance(old_call, ast.Call) else None
        # `pure_imported_calls` refuses a callee that is not a name the source imports.
        key = table.get(callee.id) if table is not None and isinstance(callee, ast.Name) else None
        if key is None:
            return False
        sources = kept.setdefault("sources", {})
        if key not in sources:
            sources[key] = pure_imported_calls(source, [old_call], path=path, read=read)
        if not sources[key]:
            return False
        if "startup" not in kept:
            kept["startup"] = inert_test_execution_context(path, read, search)
        return kept["startup"]
    for statement in tree.body:
        if isinstance(statement, ast.Import):
            if any(alias.name != 'math' for alias in statement.names):
                return False
        elif isinstance(statement, ast.ImportFrom):
            if statement.level:
                return False
            if statement.module == 'math':
                if any(alias.name != 'gcd' for alias in statement.names):
                    return False
            elif statement.module != module_name or any(alias.name != function_name for alias in statement.names):
                return False
    return (pure_imported_calls(source, [old_call], path=path, read=read)
            and inert_test_execution_context(path, read, search))

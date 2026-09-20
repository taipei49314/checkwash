"""Complete import/startup authority for closed replacement evidence."""
from __future__ import annotations

import ast

from .oracle_purity import pure_imported_calls
from .snapshot_context import inert_test_execution_context


def closed_replacement_authority(tree, target, *, path, read, search, modules, symbols):
    """Imported production cannot rewrite the builtin/stdlib replacement API.

    The caller proves the test's closed executable grammar. This guard checks
    every import against its small API vocabulary, the complete production
    source and its package initializers, and repository startup/sibling tests.
    A synthetic import selects that exact resolved production function; it
    does not infer identity from a nearby call or give any oracle credit.
    """
    module_name, _, function_name = target.rpartition('.')
    if not module_name or not all(part.isidentifier() for part in target.split('.')):
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name not in modules | {module_name} for alias in node.names):
                return False
        elif isinstance(node, ast.ImportFrom):
            allowed = symbols.get(node.module, set())
            if node.module == module_name:
                allowed = allowed | {function_name}
            if node.level or any(alias.name not in allowed for alias in node.names):
                return False
    roots = {'', 'src/'}
    directory = path.replace('\\', '/').rpartition('/')[0]
    for _ in range(16):
        if not directory:
            break
        roots.add(directory + '/')
        directory = directory.rpartition('/')[0]
    else:
        return False
    # Builtins is interpreter-owned; imported external modules need the same
    # conventional path-shadow exclusion as the production resolver.
    for name in (modules | set(symbols)) - {'builtins'}:
        relative = name.replace('.', '/')
        if any(read(prefix + relative + suffix) is not None
               for prefix in sorted(roots) for suffix in ('.py', '/__init__.py')):
            return False
    source = f'from {module_name} import {function_name} as _subject\n'.encode()
    call = ast.Call(func=ast.Name(id='_subject', ctx=ast.Load()), args=[], keywords=[])
    return (pure_imported_calls(source, [call], path=path, read=read)
            and inert_test_execution_context(path, read, search))

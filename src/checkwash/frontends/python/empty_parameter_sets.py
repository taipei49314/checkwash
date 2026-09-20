"""Expose a known single test replaced by a closed empty parameter set.

The ordinary count delta distinguishes unknown counts from known numbers.
Only this two-sided source proof supplies the missing 1 -> 0 observation;
an unknown previous parameter provider is never assumed to contain a case.
"""
import ast
from dataclasses import replace

from .oracle_purity import pure_imported_calls
from .snapshot_context import inert_test_execution_context
from .table_oracles import _args, _bounded_tree, _context_snapshots, _pytest_unshadowed, _IMPLICIT_HOOKS


def _empty(node, bound, depth=0):
    if depth > 16:
        return False
    if isinstance(node, (ast.List, ast.Tuple)):
        return not node.elts
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id not in bound and not node.keywords):
        if node.func.id in {'list', 'tuple'}:
            return not node.args or len(node.args) == 1 and _empty(node.args[0], bound, depth + 1)
        if node.func.id == 'range':
            return (len(node.args) == 1 and isinstance(node.args[0], ast.Constant)
                    and type(node.args[0].value) is int and node.args[0].value == 0)
    if isinstance(node, (ast.ListComp, ast.GeneratorExp)) and node.generators:
        first = node.generators[0]
        # No target, predicate, element or later iterator executes when the
        # first concrete builtin iterator is empty.
        return not any(generator.is_async for generator in node.generators) and _empty(first.iter, bound, depth + 1)
    return False


def _module(source, *, after):
    tree = _bounded_tree(source)
    if tree is None:
        return None
    functions, imported, bound, pytest = {}, [], set(), False
    for node in tree.body:
        if (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
                and type(node.value.value) is str):
            continue
        if (isinstance(node, ast.Import) and len(node.names) == 1
                and node.names[0].name == 'pytest' and node.names[0].asname is None):
            if functions:
                return None
            names = ['pytest']
            pytest = True
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            if functions:
                return None
            names = [alias.asname or alias.name for alias in node.names]
            if any(alias.name == '*' for alias in node.names) or 'pytest' in names:
                return None
            imported.extend(ast.Call(func=ast.Name(id=name, ctx=ast.Load()), args=[], keywords=[])
                            for name in names)
        elif isinstance(node, ast.FunctionDef) and _args(node) is not None:
            if node.name in _IMPLICIT_HOOKS or node.name.startswith(('pytest_', '__')):
                return None
            names = [node.name]
            functions[node.name] = node
        else:
            return None
        if len(set(names)) != len(names) or set(names) & bound:
            return None
        bound.update(names)
    empty = set()
    for name, function in functions.items():
        if not function.decorator_list:
            continue
        if not after or not pytest or len(function.decorator_list) != 1:
            return None
        decorator = function.decorator_list[0]
        if (not isinstance(decorator, ast.Call) or ast.unparse(decorator.func) != 'pytest.mark.parametrize'
                or len(decorator.args) != 2 or decorator.keywords
                or not isinstance(decorator.args[0], ast.Constant) or type(decorator.args[0].value) is not str
                or _args(function) != [decorator.args[0].value] or not _empty(decorator.args[1], bound)):
            return None
        empty.add(name)
    return (functions, imported, empty) if len(functions) <= 64 and len(imported) <= 32 else None


def _inert_import(source, target, _call):
    """Definitions do not execute their bodies during test collection.

    This proves import-time inertness only, never pure calls or oracle credit.
    Decorators, evaluated signatures, imports and other statements decline.
    """
    tree = _bounded_tree(source)
    if tree is None:
        return False
    names = set()
    for node in tree.body:
        if (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
                and type(node.value.value) is str):
            continue
        if (not isinstance(node, ast.FunctionDef) or _args(node) is None or node.decorator_list
                or node.name in names or node.name.startswith('__')):
            return False
        names.add(node.name)
    return target in names


def _unique_package_roots(source, path, read):
    from pathlib import PurePosixPath
    parts = PurePosixPath(path).parts
    roots = {'', 'src', *('/'.join(parts[:depth]) for depth in range(1, len(parts)))}
    for node in ast.parse(source).body:
        if not isinstance(node, ast.ImportFrom):
            continue
        module = node.module.split('.')
        for depth in range(1, len(module)):
            relative = '/'.join(module[:depth])
            hits = []
            for root in sorted(roots):
                prefix = root + '/' if root else ''
                if read(prefix + relative + '.py') is not None:
                    return False
                if read(prefix + relative + '/__init__.py') is not None:
                    hits.append(root)
            if len(hits) > 1:
                return False
            if hits:
                prefix = hits[0] + '/' if hits[0] else ''
                leaf = prefix + '/'.join(module)
                if read(leaf + '.py') is None and read(leaf + '/__init__.py') is None:
                    return False  # another root wins the package before the leaf
    return True


def mark_empty_parameter_introduction(before, after, before_parsed, after_parsed, *, path,
                                     root_reader=None, root_searcher=None, changes=()):
    if (root_reader is None or root_searcher is None or b'parametrize' not in after
            or not before_parsed.parse_ok or not after_parsed.parse_ok):
        return before_parsed, after_parsed
    old, new = _module(before, after=False), _module(after, after=True)
    if old is None or new is None:
        return before_parsed, after_parsed
    eligible = {name for name in new[2] if name in old[0] and name.startswith('test')
                and not old[0][name].decorator_list and _args(old[0][name]) == []}
    if not eligible:
        return before_parsed, after_parsed
    for source, module, (read, search) in zip((before, after), (old, new), _context_snapshots(
            path, before, after, tuple(changes), root_reader, root_searcher)):
        if (not inert_test_execution_context(path, read, search) or not _pytest_unshadowed(path, read)
                or not _unique_package_roots(source, path, read)
                or not pure_imported_calls(source, module[1], path=path, read=read, result_proof=_inert_import)):
            return before_parsed, after_parsed
    def counted(parsed, count):
        return replace(parsed, units=[replace(unit, side=replace(unit.side, param_cases=count))
            if unit.qualname in eligible else unit for unit in parsed.units])
    return counted(before_parsed, 1), counted(after_parsed, 0)

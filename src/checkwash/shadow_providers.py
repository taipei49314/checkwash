"""Provider indexing, namespace/extended-package selection, and execution keys."""

from __future__ import annotations

import ast
import hashlib
from typing import Callable, Iterable, Mapping, Sequence

from checkwash.change import FileChange
from checkwash.ir.astutil import stable_dump
from checkwash.opaque import opaque_error
from checkwash.shadow_models import (
    SearchPlan,
    _decode,
    _dedupe_roots,
    _dotted,
    _join,
    _live_shadow_attr,
)


def _module_relpaths(module: str) -> tuple[str, str]:
    rel = module.replace(".", "/")
    return f"{rel}.py", f"{rel}/__init__.py"


def _provider_entries(module: str, paths: Iterable[str]) -> list[tuple[str, str]]:
    file_rel, package_rel = _module_relpaths(module)
    entries: list[tuple[str, str]] = []
    for path in sorted(set(paths)):
        for rel in (file_rel, package_rel):
            if path == rel:
                entries.append(("", path))
            elif path.endswith("/" + rel):
                entries.append((path[: -(len(rel) + 1)], path))
    return entries


def _plan_provider_entries(
    module: str, roots: Sequence[str], paths: Iterable[str]
) -> list[tuple[str, str]]:
    """Exact module providers rooted in one concrete search plan.

    ``_provider_entries`` intentionally discovers every suffix interpretation
    while building the repository index.  That broad inventory is not valid
    evidence that a same-path provider had an executable alternate: a path
    such as ``vendor/app/value.py`` is irrelevant unless ``vendor`` is an
    actual root in this plan.
    """

    allowed = set(_dedupe_roots(roots))
    return [
        (root, path)
        for root, path in _provider_entries(module, paths)
        if root in allowed
    ]


def _package_init_paths(module: str, paths: Iterable[str]) -> set[str]:
    parts = module.split(".")
    rels = [f"{'/'.join(parts[:i])}/__init__.py" for i in range(1, len(parts))]
    return {
        path
        for path in paths
        if any(path == rel or path.endswith("/" + rel) for rel in rels)
    }


def _provider_package_chain(module: str, root: str, paths: Iterable[str]) -> tuple[str, ...]:
    """Regular-package initializers executed before the selected leaf."""

    path_set = set(paths)
    parts = module.split(".")
    return tuple(
        init
        for i in range(1, len(parts))
        if (init := _join(root, f"{'/'.join(parts[:i])}/__init__.py")) in path_set
    )


def _directory_exists(directory: str, paths: set[str], opaque: Sequence[str] = ()) -> bool:
    prefix = directory.rstrip("/") + "/"
    return any(path.startswith(prefix) for path in paths) or any(
        item.startswith(prefix) for item in opaque
    )


def _opaque_location(path: str, opaque: Sequence[str]) -> str | None:
    """The submodule a search location is, or lies inside, or None (#335)."""

    for directory in opaque:
        if path == directory or path.startswith(directory + "/"):
            return directory
    return None


def _extends_package_path(data: bytes | None) -> bool:
    if not data:
        return False
    try:
        tree = ast.parse(_decode(data))
    except (SyntaxError, ValueError):
        return False
    bindings: dict[str, str] = {}

    def is_extend_call(node: ast.AST | None) -> bool:
        if not isinstance(node, ast.Call) or len(node.args) < 2:
            return False
        name = _dotted(node.func)
        direct = bindings.get(name) == "extend_path"
        dotted = name.endswith(".extend_path") and bindings.get(
            name.rpartition(".")[0]
        ) == "pkgutil"
        if not direct and not dotted:
            return False
        return (
            isinstance(node.args[0], ast.Name)
            and node.args[0].id == "__path__"
            and isinstance(node.args[1], ast.Name)
            and node.args[1].id == "__name__"
        )

    def assigned_names(target: ast.AST | None) -> set[str]:
        if isinstance(target, ast.Name):
            return {target.id}
        if isinstance(target, (ast.Tuple, ast.List)):
            return {
                name
                for element in target.elts
                for name in assigned_names(element)
            }
        if isinstance(target, ast.Starred):
            return assigned_names(target.value)
        return set()

    for stmt in tree.body:
        if isinstance(stmt, ast.Import):
            for alias in stmt.names:
                local = alias.asname or alias.name.split(".", 1)[0]
                if alias.name == "pkgutil":
                    bindings[local] = "pkgutil"
                else:
                    bindings.pop(local, None)
            continue
        if isinstance(stmt, ast.ImportFrom):
            for alias in stmt.names:
                if alias.name == "*":
                    continue
                local = alias.asname or alias.name
                if stmt.module == "pkgutil" and alias.name == "extend_path":
                    bindings[local] = "extend_path"
                else:
                    bindings.pop(local, None)
            continue
        if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
            if any(
                isinstance(target, ast.Name) and target.id == "__path__"
                for target in targets
            ) and is_extend_call(stmt.value):
                return True
            for target in targets:
                for name in assigned_names(target):
                    bindings.pop(name, None)
            continue
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bindings.pop(stmt.name, None)
        elif isinstance(stmt, ast.Delete):
            for target in stmt.targets:
                for name in assigned_names(target):
                    bindings.pop(name, None)
    return False


def _selected_provider(
    module: str,
    roots: Sequence[str],
    paths: Iterable[str],
    contents: Mapping[str, bytes | None] | None = None,
    opaque: Sequence[str] = (),
) -> tuple[str, str] | None:
    path_set = set(paths)
    ordered = list(_dedupe_roots(roots))
    # Walk package prefixes using Python's regular-vs-namespace rule.  A
    # regular package found later on sys.path beats namespace portions found
    # earlier; a pkgutil.extend_path package deliberately keeps those later
    # locations.  Looking only at the final path suffix gets this wrong and
    # reports shadows Python would never import.
    locations: list[tuple[str, str]] = [(root, root) for root in ordered]
    parts = module.split(".")
    for part in parts[:-1]:
        candidates: list[tuple[str, str, str]] = []
        for origin, directory in locations:
            child = _join(directory, part)
            # A location inside a submodule may hold the package; it decides
            # the import unless a regular package earlier on the path does
            # (#335).
            owner = _opaque_location(child, opaque)
            if owner is not None:
                if not candidates:
                    raise opaque_error(owner, f"the import of {module} can resolve inside it")
                continue
            init = f"{child}/__init__.py"
            if init in path_set:
                candidates.append((origin, child, init))
        if candidates:
            origin, child, init = candidates[0]
            next_locations = [(origin, child)]
            if _extends_package_path((contents or {}).get(init)):
                for other_origin, directory in locations:
                    other = _join(directory, part)
                    # A location inside a submodule joins the package's path;
                    # the walk fails there only if it gets that far (#335).
                    if other != child and (
                        _directory_exists(other, path_set, opaque)
                        or _opaque_location(other, opaque) is not None
                    ):
                        next_locations.append((other_origin, other))
            locations = next_locations
        else:
            locations = [
                (origin, child)
                for origin, directory in locations
                if _directory_exists((child := _join(directory, part)), path_set, opaque)
            ]
        if not locations:
            return None

    leaf = parts[-1]
    for origin, directory in locations:
        file_path = _join(directory, f"{leaf}.py")
        package_path = _join(directory, f"{leaf}/__init__.py")
        owner = _opaque_location(file_path, opaque) or _opaque_location(
            _join(directory, leaf), opaque
        )
        if owner is not None:
            raise opaque_error(owner, f"the import of {module} can resolve inside it")
        if package_path in path_set:
            return origin, package_path
        if file_path in path_set:
            return origin, file_path
    return None


_MAX_SOURCE_KEY_PARSE_BYTES = 128_000


def _bytes_source_key(data: bytes) -> tuple[str, str]:
    """Bounded, fail-closed identity when AST equivalence is unavailable."""

    return "sha256", hashlib.sha256(data).hexdigest()


def _source_key(data: bytes | None) -> tuple[str, str] | None:
    if data is None:
        return None
    limit = _live_shadow_attr("_MAX_SOURCE_KEY_PARSE_BYTES", _MAX_SOURCE_KEY_PARSE_BYTES)
    if len(data) > limit:
        return _bytes_source_key(data)
    try:
        # Python's bytes parser honors an encoding cookie. Lossy UTF-8
        # replacement could otherwise equate different executable literals
        # in two valid non-UTF-8 providers.
        tree = ast.parse(data)
        return "ast", stable_dump(tree)
    except (SyntaxError, ValueError, TypeError, MemoryError, RecursionError):
        # Attacker-controlled Python can exhaust the recursive AST builder or
        # dumper well below the engine's one-megabyte source ceiling.  Raw
        # content identity is conservative (a change stays changed), bounded,
        # and never turns an unreadable provider into equivalence credit.
        return _bytes_source_key(data)


def _provider_execution_key(
    module: str,
    selected: tuple[str, str],
    paths: Iterable[str],
    contents: Mapping[str, bytes | None],
    *,
    source_keyer: Callable[[bytes | None], tuple[str, str] | None] | None = None,
) -> tuple[tuple[str, str], ...] | None:
    """AST keys for every executed package initializer and the leaf."""

    root, provider = selected
    executed = (*_provider_package_chain(module, root, paths), provider)
    keyer = source_keyer or _live_shadow_attr("_source_key", _source_key)
    keys = tuple(keyer(contents.get(path)) for path in executed)
    if any(key is None for key in keys):
        return None
    return tuple(key for key in keys if key is not None)


def _changed_provider(
    module: str,
    plan: SearchPlan,
    before_paths: Iterable[str],
    after_paths: Iterable[str],
    contents: Mapping[str, bytes | None],
    *,
    added_paths: set[str],
    removed_paths: set[str] | None = None,
    structural_paths: set[str] | None = None,
    semantic_paths: set[str] | None = None,
    before_contents: Mapping[str, bytes | None] | None = None,
    allow_equivalent: bool = False,
    provider_keyer: Callable[
        [str, tuple[str, str], Iterable[str], Mapping[str, bytes | None]],
        tuple[tuple[str, str], ...] | None,
    ]
    | None = None,
    opaque: Sequence[str] = (),
) -> tuple[str, str] | None:
    """The one family predicate: did the imported module change provider?"""

    select = _live_shadow_attr("_selected_provider", _selected_provider)
    base_contents = contents if before_contents is None else before_contents
    before = select(module, plan.before_roots, before_paths, base_contents, opaque)
    after = select(module, plan.after_roots, after_paths, contents, opaque)
    if before is None or after is None:
        return None
    keyer = provider_keyer or _live_shadow_attr("_provider_execution_key", _provider_execution_key)
    before_key = keyer(module, before, before_paths, base_contents)
    after_key = keyer(module, after, after_paths, contents)
    if before_key is None or after_key is None:
        return None
    if before[1] == after[1]:
        # Two-commit plant: the already-winning provider was executable-
        # equivalent to an alternate provider at base, then changed in this
        # diff.  An ordinary edit to an intentionally divergent duplicate is
        # not this family and remains an honest negative.
        semantic = semantic_paths or set()
        executed = {
            *_provider_package_chain(module, before[0], before_paths),
            *_provider_package_chain(module, after[0], after_paths),
            before[1],
        }
        if not (executed & semantic) or before_key == after_key:
            return None
        alternate_after_keys = [
            keyer(module, (root, path), after_paths, contents)
            for root, path in _plan_provider_entries(
                module, plan.before_roots, before_paths
            )
            if path != before[1]
            and path in set(after_paths)
            and keyer(
                module, (root, path), before_paths, base_contents
            )
            == before_key
        ]
        if any(key is not None and key != after_key for key in alternate_after_keys):
            return before[1], after[1]
        if allow_equivalent and any(key == after_key for key in alternate_after_keys):
            return before[1], after[1]
        return None
    package_shape_changed = bool(
        _package_init_paths(module, added_paths | (structural_paths or set()))
    )
    if (
        after[1] not in added_paths
        and before[1] not in (removed_paths or set())
        and not package_shape_changed
        and plan.before_roots == plan.after_roots
    ):
        return None
    if before_key == after_key and not allow_equivalent:
        return None
    return before[1], after[1]


def _path_to_modules(path: str) -> set[str]:
    """All exact dotted-module interpretations under an ancestor search root."""

    if not path.endswith(".py"):
        return set()
    rel = path[:-3]
    if rel.endswith("/__init__"):
        rel = rel[: -len("/__init__")]
    parts = [part for part in rel.split("/") if part]
    out: set[str] = set()
    for i in range(len(parts)):
        tail = parts[i:]
        if all(part.isidentifier() for part in tail):
            out.add(".".join(tail))
    return out


def _module_from_root(path: str, root: str) -> str | None:
    prefix = root.rstrip("/") + "/" if root else ""
    if not path.startswith(prefix) or not path.endswith(".py"):
        return None
    rel = path[len(prefix) : -3]
    if rel.endswith("/__init__"):
        rel = rel[: -len("/__init__")]
    parts = [part for part in rel.split("/") if part]
    if not parts or not all(part.isidentifier() for part in parts):
        return None
    return ".".join(parts)


def _side_paths(
    after_paths: set[str], changes: Sequence[FileChange]
) -> tuple[set[str], set[str]]:
    before = set(after_paths)
    after = set(after_paths)
    for change in changes:
        path = change.path.replace("\\", "/")
        old = (change.old_path or "").replace("\\", "/")
        if change.status == "added":
            before.discard(path)
            after.add(path)
        elif change.status == "deleted":
            before.add(path)
            after.discard(path)
        elif old and old != path:
            before.add(old)
            before.discard(path)
            after.discard(old)
            after.add(path)
    return before, after


def _side_source(
    path: str,
    side: str,
    changes: Mapping[str, FileChange],
    snapshot: Mapping[str, bytes | None],
) -> bytes | None:
    change = changes.get(path)
    if change is not None:
        return change.before if side == "before" else change.after
    return snapshot.get(path)

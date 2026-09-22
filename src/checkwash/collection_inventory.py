"""Compare actual Python collection candidates under resolved root config.

This supplements the syntax-only CI scanner when a complete snapshot exists.
The finite comparison handles arbitrary literal glob changes and first-time
configuration without declaring ordinary configuration creation a weakening.
"""
from __future__ import annotations

import ast
import fnmatch
import posixpath

from checkwash.change import EngineError
from checkwash.pytest_collection import collection_options, resolved_collection_settings
from checkwash.roles import _runs_tests, is_artifact

_CONFIGS = ("pytest.ini", ".pytest.ini", "pyproject.toml", "tox.ini", "setup.cfg")
_DEFAULTS = {"python_files": ("test_*.py", "*_test.py"),
             "python_classes": ("Test",), "python_functions": ("test",),
             "norecursedirs": ("*.egg", ".*", "_darcs", "build", "CVS", "dist", "node_modules", "venv", "{arch}")}


def _matches(name, patterns, *, prefix=False):
    return any((prefix and name.startswith(pattern)) or fnmatch.fnmatchcase(name, pattern) for pattern in patterns)


def _settings(path, source):
    text = source.decode("utf-8-sig") if source else ""
    settings = resolved_collection_settings(text)
    if any(len(value) != 1 for key, value in settings.items() if key != "addopts"):
        return None
    return {key: next(iter(value)) for key, value in settings.items() if key != "addopts"}


def _disabled(body):
    return any(isinstance(node, (ast.Assign, ast.AnnAssign))
               and isinstance(node.value, ast.Constant) and node.value.value is False
               and any(isinstance(target, ast.Name) and target.id == "__test__"
                       for target in (node.targets if isinstance(node, ast.Assign) else [node.target]))
               for node in body)


def _candidates(sources, settings):
    paths = set(sources)
    roots = tuple(posixpath.normpath(root.replace("\\", "/")) for root in settings.get("testpaths", ()))
    selected = {path for path in paths if any(root == "." or path == root or path.startswith(root.rstrip("/") + "/")
                or fnmatch.fnmatchcase(path, root) for root in roots)}
    # pytest falls back to the invocation directory if no testpaths exists.
    paths = selected if selected else paths
    patterns = {**_DEFAULTS, **settings}
    result = set()
    for path in paths:
        if not path.endswith(".py") or is_artifact(path):
            continue
        parts = path.split("/")
        if not _matches(parts[-1], patterns["python_files"]):
            continue
        if any(_matches(part, patterns["norecursedirs"]) for part in parts[:-1]):
            continue
        try:
            tree = ast.parse(sources[path].decode("utf-8-sig"))
        except (SyntaxError, UnicodeError, RecursionError, ValueError):
            continue
        if _disabled(tree.body):
            continue
        disabled_functions = {target.value.id for stmt in tree.body if isinstance(stmt, (ast.Assign, ast.AnnAssign))
                              and isinstance(stmt.value, ast.Constant) and stmt.value.value is False
                              for target in (stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target])
                              if isinstance(target, ast.Attribute) and target.attr == "__test__" and isinstance(target.value, ast.Name)}
        for node in tree.body:
            if getattr(node, "name", None) in disabled_functions:
                continue
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if _matches(node.name, patterns["python_functions"], prefix=True):
                    result.add((path, node.name))
            elif (isinstance(node, ast.ClassDef) and not node.bases
                  and not _disabled(node.body)
                  and _matches(node.name, patterns["python_classes"], prefix=True)
                  and not any(isinstance(child, ast.FunctionDef) and child.name in {"__init__", "__new__"} for child in node.body)):
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and _matches(child.name, patterns["python_functions"], prefix=True):
                        result.add((path, node.name + "." + child.name))
    return result


def collection_inventory_changes(changes, config, *, path_lister=None, batch_reader=None):
    touched = {c.path: c for c in changes if c.path in _CONFIGS and config.role_of(c.path) == "ci"}
    if not touched or path_lister is None or batch_reader is None:
        return []
    if all(c.status == "modified" and resolved_collection_settings((c.before or b"").decode("utf-8-sig", errors="replace"))
           == resolved_collection_settings((c.after or b"").decode("utf-8-sig", errors="replace"))
           and collection_options((c.before or b"").decode("utf-8-sig", errors="replace"))
           == collection_options((c.after or b"").decode("utf-8-sig", errors="replace")) for c in touched.values()):
        return []
    paths = path_lister()
    if not isinstance(paths, (list, tuple)) or len(paths) > 200_000 or any(not isinstance(p, str) for p in paths):
        raise EngineError("pytest collection snapshot has an invalid path inventory")
    if any(not p or p.startswith("/") or ":" in p or "\\" in p
           or any(part in {"", ".", ".."} for part in p.split("/")) for p in paths):
        raise EngineError("pytest collection snapshot has an unsafe inventory path")
    path_set = set(paths)
    runners = {p for p in path_set if not is_artifact(p) and (
        p.startswith((".github/workflows/", "scripts/"))
        or p.endswith((".sh", ".bash", ".ps1", ".bat", ".cmd"))
        or p in {"Makefile", ".gitlab-ci.yml", "noxfile.py", "tox.ini"})}
    selected = runners | {p for p in path_set if p in _CONFIGS or (p.endswith(".py") and not is_artifact(p))}
    if len(selected) > 4096:
        raise EngineError("pytest collection snapshot exceeds the source read limit")
    snapshot = batch_reader(sorted(selected))
    if not isinstance(snapshot, dict) or set(snapshot) != selected or any(not isinstance(v, bytes) for v in snapshot.values()):
        raise EngineError("pytest collection snapshot source is incomplete")
    if any(len(v) > 1_000_000 for v in snapshot.values()) or sum(map(len, snapshot.values())) > 64_000_000:
        raise EngineError("pytest collection snapshot exceeds the source byte limit")
    from checkwash.shadow import _pytest_config_path, _runner_invocations
    from checkwash.frontends.python.frontend import parse_python

    # Existing plugin/collection controls mean the default collector's finite
    # candidates are not evidence of tests currently being run. Retain the
    # syntax detector, but withhold this inventory-based supplemental proof.
    for path, data in snapshot.items():
        if path.rsplit("/", 1)[-1] == "conftest.py" and data:
            parsed = parse_python(data, collect_tests=False, conftest=True)
            if not parsed.parse_ok or any(u.side.markers for u in parsed.units) or b"pytest_plugins" in data:
                return []

    # Explicit CLI targets override testpaths and may bypass filename
    # patterns. Such invocations need their own collection model; do not
    # attribute their collection to an implicit targetless root invocation.
    for path in runners - set(_CONFIGS):
        data = snapshot[path]
        if _runs_tests(data):
            invocations = _runner_invocations(path, data)
            if (not invocations or any(item.targets or item.config_path or item.cwd for item in invocations)
                    or collection_options(data.decode("utf-8-sig", errors="replace"))
                    or b"PYTEST_ADDOPTS" in data or b"--override-ini" in data or b" -o " in data):
                return []

    sides = []
    for side in ("before", "after"):
        contents = dict(snapshot)
        for change in changes:
            if change.path not in _CONFIGS and not change.path.endswith(".py"):
                continue
            data = change.before if side == "before" else change.after
            if data is None:
                contents.pop(change.path, None)
            else:
                contents[change.path] = data
            if side == "before" and change.old_path:
                contents[change.old_path] = change.before
                if change.old_path != change.path:
                    contents.pop(change.path, None)
        config_path = _pytest_config_path(contents, "", contents=contents, cwd="")
        try:
            settings = _settings(config_path, contents.get(config_path))
        except UnicodeError:
            return []
        if settings is None:
            return []
        sides.append((config_path, contents, settings))
    before_path, before, old = sides[0]
    after_path, after, new = sides[1]
    if before_path not in touched and after_path not in touched:
        return []
    # Compare the same surviving source bytes, so deleting/editing a test
    # cannot be mistaken for a configuration effect.
    common = {p: data for p, data in before.items() if p.endswith(".py") and after.get(p) == data}
    previous = _candidates(common, old)
    old_options = collection_options((before.get(before_path) or b"").decode("utf-8-sig", errors="replace"))
    new_options = collection_options((after.get(after_path) or b"").decode("utf-8-sig", errors="replace"))
    path = after_path if after_path in touched else before_path
    if previous and new_options.keys() - old_options.keys():
        option = sorted(new_options.keys() - old_options.keys())[0]
        return [(path, "resolved pytest collection option introduced: " + " ".join(option).rstrip())]
    lost = sorted(previous - _candidates(common, new))
    if not lost:
        return []
    example = "::".join(lost[0])
    return [(path, f"resolved pytest collection excludes {len(lost)} existing test(s), including {example}")]

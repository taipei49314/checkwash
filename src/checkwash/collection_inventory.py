"""Compare actual Python collection candidates under resolved root config.

This supplements the syntax-only CI scanner when a complete snapshot exists.
The finite comparison handles arbitrary literal glob changes and first-time
configuration without declaring ordinary configuration creation a weakening.

A new selector in the root config is judged against the base-suite tests
that a run it governs collects: every test for a run without targets, and
the tests beneath the targets for a run with explicit targets (#196 184.1).
A path option or a `-p no:` plugin counts only when it can leave one of those
tests out (#196 184.2). A run with explicit targets ignores testpaths, so the
settings proof does not reach it.
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
# Built-in plugins whose absence cannot leave a test out or turn a failure
# into a pass: the cache (`--lf`/`--ff` state), the faulthandler traceback
# dump, the pastebin upload and `--stepwise` bookkeeping (#196 184.2). Every
# other `-p no:` keeps blocking, `no:python` and `no:unittest` included.
_HARMLESS_PLUGINS = frozenset({"cacheprovider", "faulthandler", "pastebin", "stepwise"})
# Config files that discovery from a targeted run's targets can meet beneath
# the root: such a nested config governs that run instead of the root config
# (#196 184.1).
_NESTED_CONFIGS = ("pytest.toml", ".pytest.toml", "pytest.ini", ".pytest.ini", "pyproject.toml", "tox.ini", "setup.cfg")


def _nested_config(path):
    return "/" in path and path.rsplit("/", 1)[-1] in _NESTED_CONFIGS and not is_artifact(path)


def _matches(name, patterns, *, prefix=False):
    return any((prefix and name.startswith(pattern)) or fnmatch.fnmatchcase(name, pattern) for pattern in patterns)


def _settings(path, source):
    text = source.decode("utf-8-sig") if source else ""
    settings = resolved_collection_settings(text)
    if any(len(value) != 1 for key, value in settings.items() if key != "addopts"):
        return None
    return {key: next(iter(value)) for key, value in settings.items() if key != "addopts"}


def _under(path, targets):
    """Is this test file among what an invocation's explicit targets collect?"""
    return any(path == target or path.startswith(target + "/") or fnmatch.fnmatchcase(path, target)
               for target in targets)


def _drops(option, tests):
    """Can an option the diff introduces leave out one of these tests (#196 184.2)?

    A path option is evaluated against the tests' paths and node ids, and a
    `-p no:` against the plugins whose absence changes no outcome. Markers,
    keywords and `--co` are not evaluated: they count whenever a test is
    there to lose.
    """
    if not tests:
        return False
    name, value = option
    if name == "-p":
        return value.removeprefix("no:") not in _HARMLESS_PLUGINS
    if name == "--ignore":
        root = posixpath.normpath(value.replace("\\", "/"))
        return root == "." or any(path == root or path.startswith(root + "/") for path, _ in tests)
    if name == "--ignore-glob":
        pattern = posixpath.normpath(value.replace("\\", "/"))
        # pytest skips a directory that matches with everything beneath it.
        return any(fnmatch.fnmatchcase(prefix, pattern)
                   for path, _ in tests
                   for prefix in ["/".join(path.split("/")[:end]) for end in range(1, path.count("/") + 2)])
    if name == "--deselect":
        # A node id prefix deselects every test it starts; a parametrized
        # case (`::test_x[1]`) is a test the suite partly loses.
        return any(node.startswith(value) or value.startswith(node + "[")
                   for node in (path + "::" + test.replace(".", "::") for path, test in tests))
    return True


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
    selected = runners | {p for p in path_set if p in _CONFIGS or _nested_config(p)
                          or (p.endswith(".py") and not is_artifact(p))}
    if len(selected) > 4096:
        raise EngineError("pytest collection snapshot exceeds the source read limit")
    snapshot = batch_reader(sorted(selected))
    if not isinstance(snapshot, dict) or set(snapshot) != selected or any(not isinstance(v, bytes) for v in snapshot.values()):
        raise EngineError("pytest collection snapshot source is incomplete")
    if any(len(v) > 1_000_000 for v in snapshot.values()) or sum(map(len, snapshot.values())) > 64_000_000:
        raise EngineError("pytest collection snapshot exceeds the source byte limit")
    from checkwash.shadow import _pytest_config_path, _runner_invocations
    from checkwash.frontends.python.conftest_controls import is_collection_control
    from checkwash.frontends.python.frontend import parse_python

    # A conftest that changes what pytest collects means the default
    # collector's finite candidates are not evidence of the tests being run:
    # a collection control (SPEC §2b), `pytest_plugins`, or a conftest that
    # does not parse. Retain the syntax detector, but withhold this
    # inventory-based supplemental proof. A runtime control does not withhold
    # it: the test is still collected, and its skip is reported where it is
    # planted (#199 Q1, Q2).
    for path, data in snapshot.items():
        if path.rsplit("/", 1)[-1] == "conftest.py" and data:
            parsed = parse_python(data, collect_tests=False, conftest=True)
            if (not parsed.parse_ok or b"pytest_plugins" in data
                    or any(is_collection_control(m.name) for u in parsed.units for m in u.side.markers)):
                return []

    # Explicit CLI targets override testpaths and may bypass filename
    # patterns, so a targeted invocation does not inherit the root config's
    # collection settings. It still inherits its addopts: a new selector there
    # is judged against the base-suite tests beneath the targets (#196 184.1).
    invocations = []
    for path in sorted(runners - set(_CONFIGS)):
        data = snapshot[path]
        if _runs_tests(data):
            found = _runner_invocations(path, data)
            if (not found or any(item.config_path or item.cwd for item in found)
                    or collection_options(data.decode("utf-8-sig", errors="replace"))
                    or b"PYTEST_ADDOPTS" in data or b"--override-ini" in data or b" -o " in data):
                return []
            invocations.extend(found)
    targeted = [item.targets for item in invocations if item.targets]
    # With no runner in the tree, the suite is the implicit targetless run's.
    targetless = not invocations or any(not item.targets for item in invocations)

    sides = []
    for side in ("before", "after"):
        contents = dict(snapshot)
        for change in changes:
            if change.path not in _CONFIGS and not change.path.endswith(".py") and not _nested_config(change.path):
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
    # One definition of the existing suite serves both proofs below: what the
    # base settings collected from the whole base tree. Reading it from
    # byte-identical files only hid every test in a file the diff also edits,
    # and a marker selector cannot be applied without editing the marked file:
    # `@pytest.mark.slow` on the only test plus a first
    # `addopts = "-m 'not slow'"` fell back to warn, while the same diff beside
    # one untouched test blocked (issue #173).
    suite = _candidates({p: data for p, data in before.items() if p.endswith(".py")}, old)
    old_options = collection_options((before.get(before_path) or b"").decode("utf-8-sig", errors="replace"))
    new_options = collection_options((after.get(after_path) or b"").decode("utf-8-sig", errors="replace"))
    path = after_path if after_path in touched else before_path
    # The base-suite tests a run the root config governs collects: all of
    # them for a targetless run, and those beneath the targets for a targeted
    # one, when discovery from its targets finds this same config on both
    # sides rather than a nested one (#196 184.1).
    reached = set(suite) if targetless else set()
    for targets in targeted:
        if (_pytest_config_path(before, "", targets, contents=before) == before_path
                and _pytest_config_path(after, "", targets, contents=after) == after_path):
            reached |= {(test_path, name) for test_path, name in suite if _under(test_path, targets)}
    # Markers, keywords and `--co` are not evaluated, so such a selector is
    # judged against the existence of those tests; a path option and a
    # plugin are judged by what they can leave out (#196 184.2). A tree that
    # collected nothing at base has nothing for a selector to deselect.
    introduced = sorted(option for option in new_options.keys() - old_options.keys() if _drops(option, reached))
    if introduced:
        return [(path, "resolved pytest collection option introduced: " + " ".join(introduced[0]).rstrip())]
    # A targeted run ignores testpaths, so the settings proof stays withheld.
    if targeted or old == new:
        return []
    # Settings are judged test by test, and only for their own effect: the old
    # and the new settings are applied to the same head tree, so deleting,
    # emptying or moving a test cannot be mistaken for a configuration effect,
    # and a test this diff adds is not an existing one. A renamed file keeps
    # its base identity.
    moved = {c.path: c.old_path for c in changes if c.old_path}
    head = {p: data for p, data in after.items() if p.endswith(".py")}
    still = {(moved.get(p, p), name) for p, name in _candidates(head, old)}
    kept = {(moved.get(p, p), name) for p, name in _candidates(head, new)}
    lost = sorted((suite & still) - kept)
    if not lost:
        return []
    example = "::".join(lost[0])
    return [(path, f"resolved pytest collection excludes {len(lost)} existing test(s), including {example}")]

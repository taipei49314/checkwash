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

An option every base-side pytest command in the runner files carried, which
the head commands dropped and nothing else, moved into the config: each run
passes it before and after, so it is not new (#196 184.3). A command this
reader cannot parse leaves that proof open, and the option is judged.
"""
from __future__ import annotations

import ast
import fnmatch
import posixpath
import re
import shlex

from checkwash.change import EngineError
from checkwash.opaque import opaque_error, split_inventory
from checkwash.ci_control_flow import _read_yaml, _step_command, is_github_workflow
from checkwash.pytest_collection import (
    _commands,
    _pytest_arguments,
    _spelled_options,
    collection_options,
    collection_settings,
    resolved_collection_settings,
)
from checkwash.roles import _runs_tests, is_artifact
from checkwash.runner_command import invokes_named_runner

# The root configs pytest reads, in the order it looks for them (#221).
_CONFIGS = ("pytest.toml", ".pytest.toml", "pytest.ini", ".pytest.ini", "pyproject.toml", "tox.ini", "setup.cfg")
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


def _runner(path):
    """A file whose pytest commands are the runs a root config governs."""
    return not is_artifact(path) and (
        path.startswith((".github/workflows/", "scripts/"))
        or path.endswith((".sh", ".bash", ".ps1", ".bat", ".cmd"))
        or path in {"Makefile", ".gitlab-ci.yml", "noxfile.py", "tox.ini"})


def _calls(path, data):
    """Every pytest command a runner file runs, as its words, or None (#196 184.3).

    None means the file may run a test runner in a way this reader cannot
    parse, so what its runs pass is not known: a command that may run one
    (`invokes_named_runner`) and is not a pytest command the option reader
    parses (`coverage run -m pytest`, `tox`, `make test`, a nox session), a
    line that does not lex, a step that runs a runner action, a `tox.ini`
    environment's commands, pytest settings the file writes itself,
    `PYTEST_ADDOPTS`, `--override-ini` or ` -o `. A workflow is read step by
    step, so a step's name or a cache key is not a command.
    """
    if not _runs_tests(data):
        return []
    text = data.decode("utf-8-sig", errors="replace")
    if path == "tox.ini":
        # Its pytest sections configure; only an environment's commands run.
        return None if re.search(r"(?m)^\s*commands(?:_pre|_post)?\s*=", text) else []
    if any(marker in data for marker in (b"PYTEST_ADDOPTS", b"--override-ini", b" -o ")):
        return None
    texts = [text]
    if is_github_workflow(path):
        tree = _read_yaml(data)
        jobs = tree.get("jobs") if isinstance(tree, dict) else None
        if not isinstance(jobs, dict):
            return None
        texts = []
        for job in jobs.values():
            steps = job.get("steps") if isinstance(job, dict) else None
            for step in steps if isinstance(steps, list) else ():
                if isinstance(step, dict) and isinstance(step.get("run"), str):
                    texts.append(step["run"])
                elif isinstance(step, dict) and _step_command(step) is not None:
                    return None
    calls = []
    for text in texts:
        if collection_settings(text):
            return None
        for command, words in _commands(text):
            if words is None:
                if invokes_named_runner(command):
                    return None
            elif _pytest_arguments(words) is not None:
                calls.append(tuple(words))
            elif words and invokes_named_runner(shlex.join(words)):
                return None
    return calls


def _side_calls(files):
    calls = {}
    for path, data in files.items():
        found = _calls(path, data)
        if found is None:
            return None
        calls[path] = found
    return calls


def _without(call, options):
    """One pytest command's words without the words that spell these options."""
    arguments = _pytest_arguments(list(call))
    offset = len(call) - len(arguments)
    dropped = {offset + index for option, span in _spelled_options(arguments) if option in options for index in span}
    return tuple(word for index, word in enumerate(call) if index not in dropped)


def _migrated(new_options, before_calls, after_calls):
    """The new config options a provably identical migration moved (#196 184.3).

    Every pytest command the runner files ran at base carried each of them,
    and each file's head commands are its base commands with exactly those
    options removed, so every run passes them before and after. pytest keeps
    the last `-m` or `-k` only, so one moves only when the config holds no
    other value for it. Anything less proves nothing, and the options stay
    judged.
    """
    if before_calls is None or after_calls is None:
        return set()
    calls = [call for path in sorted(before_calls) for call in before_calls[path]]
    if not calls:
        return set()
    carried = [{option for option, _span in _spelled_options(_pytest_arguments(list(call)))} for call in calls]
    moved = {option for option in new_options
             if all(option in options for options in carried)
             and not (option[0] in ("-m", "-k") and sum(name == option[0] for name, _value in new_options) > 1)}
    if moved and all([_without(call, moved) for call in before_calls.get(path, [])] == after_calls.get(path, [])
                     for path in before_calls.keys() | after_calls.keys()):
        return moved
    return set()


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


def collection_sources(paths):
    """The files `opaque_reached` reads: the root configs and the runner files (#335)."""
    return sorted(p for p in paths if p in _CONFIGS or _runner(p))


def opaque_reached(opaque, head, changes):
    """The first submodule a pytest run could collect from, on either side (#335).

    `head` maps the root configs and runner files present at head to their
    bytes (`collection_sources`); the diff's changes to them are applied for
    each side. The runs are the runner files' pytest commands, or the bare
    `pytest` a tree without one implies. A run reaches a directory when one
    of its path arguments names the directory, a path inside it or one above
    it. A run without one collects from the root config's testpaths, else
    from the root, and recurses into every directory no norecursedirs
    pattern stops. A setting read two ways counts both ways. An undecodable
    config or a run's own config reaches every submodule, and a runner file
    whose pytest command does not parse is a run without path arguments. A
    path argument that expands a variable (`$1`, `{posargs}`) names no path.
    """
    if not opaque:
        return None
    from checkwash.shadow import _pytest_config_path, _runner_invocations

    for side in ("before", "after"):
        contents = dict(head)
        for change in changes:
            path = change.path.replace("\\", "/")
            if side == "before":
                # a renamed file held its bytes at its old path
                contents.pop(path, None)
                path = (change.old_path or path).replace("\\", "/")
            data = change.before if side == "before" else change.after
            if path not in _CONFIGS and not _runner(path):
                continue
            if data is None:
                contents.pop(path, None)
            else:
                contents[path] = data
        config_path = _pytest_config_path(contents, "", contents=contents, cwd="")
        source = contents.get(config_path)
        try:
            readings = resolved_collection_settings(source.decode("utf-8-sig") if source else "")
        except UnicodeError:
            return opaque[0]
        targets = []
        runs = targetless = False
        for path in sorted(contents):
            if not _runner(path) or not _runs_tests(contents[path]):
                continue
            runs = True
            found = _runner_invocations(path, contents[path])
            targetless = targetless or not found or any(not item.targets for item in found)
            if any(item.config_path for item in found):
                return opaque[0]
            targets.extend(target for item in found for target in item.targets)
        targetless = targetless or not runs
        # A setting the reader resolves two ways is read both ways; a config's
        # norecursedirs replaces pytest's default list.
        for testpaths in readings.get("testpaths", {()}):
            roots = tuple(posixpath.normpath(root.replace("\\", "/")) for root in testpaths) or (".",)
            for skipped in readings.get("norecursedirs", {_DEFAULTS["norecursedirs"]}):
                for directory in opaque:
                    if any(_reaches(target, directory, skipped) for target in targets):
                        return directory
                    if targetless and any(_reaches(root, directory, skipped) for root in roots):
                        return directory
    return None


# A wildcard pytest or the shell expands: `*`, `?` or a bracket set such as
# `[ab]`. tox's `[]` (its old spelling of `{posargs}`) is a literal name.
_WILDCARD = re.compile(r"[*?]|\[[^\]]+\]")


def _reaches(root, directory, skipped):
    """Does collection from this root, a path argument or a testpath, enter the directory?

    A root inside the directory, or the directory itself, enters it. A root
    above it recurses into it unless a norecursedirs pattern stops one of the
    directories between them. A root with a wildcard is read from its literal
    prefix, and reaches whatever lies on either side of that prefix.
    """
    root = "" if root in (".", "") else root.rstrip("/")
    parts = root.split("/") if root else []
    literal = []
    for part in parts:
        if _WILDCARD.search(part):
            prefix = "/".join(literal)
            return (not prefix or directory == prefix or directory.startswith(prefix + "/")
                    or prefix.startswith(directory + "/"))
        literal.append(part)
    if root == directory or root.startswith(directory + "/"):
        return True
    if root and not directory.startswith(root + "/"):
        return False
    below = directory[len(root) + 1:] if root else directory
    return not any(_matches(part, skipped) for part in below.split("/"))


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
    # A submodule is listed as a directory whose content is unknown (#335).
    paths, opaque = split_inventory(paths)
    if any(not p or p.startswith("/") or ":" in p or "\\" in p
           or any(part in {"", ".", ".."} for part in p.split("/")) for p in (*paths, *opaque)):
        raise EngineError("pytest collection snapshot has an unsafe inventory path")
    path_set = set(paths)
    runners = {p for p in path_set if _runner(p)}
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
    # The candidates below are the whole collection's; a submodule's tests
    # are unknown, so a run that can reach one leaves them unproved (#335).
    reached = opaque_reached(opaque, {p: snapshot[p] for p in collection_sources(path_set)}, changes)
    if reached is not None:
        raise opaque_error(reached, "pytest's collection can reach it")
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
        # An option every run's command carried moved into the config, if
        # the head commands dropped it and nothing else (#196 184.3).
        head_runners = {p: snapshot[p] for p in runners}
        base_runners = dict(head_runners)
        for change in changes:
            base_runners.pop(change.path, None)
            origin = change.old_path or change.path
            if change.before is not None and _runner(origin):
                base_runners[origin] = change.before
        moved = _migrated(new_options, _side_calls(base_runners), _side_calls(head_runners))
        introduced = [option for option in introduced if option not in moved]
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

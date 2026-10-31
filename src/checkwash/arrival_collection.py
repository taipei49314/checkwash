"""Does pytest collect a Python test that arrives in this change? (D-193)

A moved or folded test pays for the tests it replaces only where it runs,
and a renamed test file that pytest stops collecting has lost its tests.
Both read pytest's default patterns and the unit's own markers, and nothing
of the repository's configuration, so a test parked where that
configuration never runs it still paid, and a rename out of it was silent
(THREATMODEL row 179).

This reads the head's standing configuration for a targetless run from the
repository root, the run a check makes when it calls plain `pytest`, as
pytest 9 reads it: the root config `locate_config` finds there, loaded as
`load_config_dict_from_file` loads it (iniconfig's rules for `.ini` and
`.cfg` files, tomllib for `.toml` ones, native tables included), with the
`-o` overrides in its `addopts`. From it come `python_files`,
`python_classes`, `python_functions`, `testpaths` and `norecursedirs`, and
from `addopts` the
targets (normalized as pytest normalizes collection arguments, node ids
included), `--ignore`, `--ignore-glob` and `--deselect`; from the arrival's
conftest chain, the nearest `collect_ignore` and `collect_ignore_glob`; and
from the tree, the virtual environment directories pytest never enters.
pytest never asks whether to ignore a run's initial path or a directory
above one. Names match with POSIX case rules, as the rest of the collection
reading does; a pattern with a slash matches pytest's absolute path, so it
decides only where every checkout depth agrees. Reads are batched, and the
inventory is listed only for a decision that needs it, a target in
`addopts` or an arrival outside every testpath: a working tree's listing
walks it whole.

Each answer is collected, not collected, or unknown. A credit needs
"collected" and a finding needs "not collected", so an unknown answer pays
nothing and reports nothing. An ignore entry the module adds only under a
condition, and a word after a plugin option the reading cannot place, are
possible, not certain. Unknown: a `-k` expression (for a test; a file is
still decided), an `@` argument file, an option under which no test or only
a cached selection runs (`--collect-only`, `--setup-only`, `--lf`, `--sw`
and the like), `--pyargs`, another rootdir, `-c`, `--keep-duplicates`, a
`-p` plugin load or `-p no:python` or `-p no:unittest`, a combined short
option the reading does not know, an addopts target outside the
repository, a configuration pytest itself refuses, a conftest in the chain
that may define a hook or load a plugin (it can collect or leave out any
path), a list a conftest changes in a way the reading does not follow, a
file that cannot be read. `--noconftest`, `--confcutdir` and
`--collect-in-virtualenv` are read. `-m` needs no reading: a proof binds the
unit's decorators, which may only be `parametrize`, `skip`, `skipif` and
`xfail`, and a row's marks withhold it (D-192). `python_classes` is read
once configured, since a first configuration is only a warning; at its
default, a class's name, bases and body are in the proof key on both sides.
Runner commands with their own targets or options, `PYTEST_ADDOPTS`,
nested configs, conftests outside the chain and installed plugins are not
read.
"""
from __future__ import annotations

import ast
import fnmatch
import posixpath
import shlex
import tomllib

_IGNORES = ("collect_ignore", "collect_ignore_glob")
# Builtins through which a conftest can bind a module global unseen
# (`vars` only without an argument, where it is the module's namespace).
_DYNAMIC = frozenset({"globals", "exec", "eval"})
# The root config files pytest's `locate_config` tries, in its order.
_CONFIG_ORDER = ("pytest.toml", ".pytest.toml", "pytest.ini", ".pytest.ini", "pyproject.toml", "tox.ini", "setup.cfg")
# The `args` settings this reading uses, with pytest 9's defaults.
_DEFAULTS = {
    "addopts": (),
    "python_files": ("test_*.py", "*_test.py"),
    "python_classes": ("Test",),
    "python_functions": ("test",),
    "testpaths": (),
    "norecursedirs": ("*.egg", ".*", "_darcs", "build", "CVS", "dist", "node_modules", "venv", "{arch}"),
}
# Options under which no test runs, only a cached selection does, or the
# arguments mean something this reading does not take: another config, or
# module names for targets.
_UNREAD_OPTIONS = frozenset({
    "--co", "--collect-only", "--collectonly", "--setup-only", "--setuponly", "--setup-plan", "--setupplan",
    "--fixtures", "--funcargs", "--fixtures-per-test", "--markers", "--help", "-h", "--version", "-V", "--cache-show",
    "--lf", "--last-failed", "--sw", "--stepwise", "--sw-skip", "--stepwise-skip", "--sw-reset", "--stepwise-reset",
    "--pyargs", "-c", "--config-file", "--keep-duplicates", "--keepduplicates",
})
# The built-in plugins that collect test functions, classes and TestCases.
_COLLECTING_PLUGINS = frozenset({"python", "unittest"})
# Short options as argparse reads a combined word such as `-qk expr` or
# `-rA`: the flags pytest and its common plugins define, and the options
# that take the rest of the word, or the next word, as their value.
_SHORT_FLAGS = frozenset("vqxlshVfd")
_SHORT_VALUES = frozenset("kmpcorWn")
# pytest 9.1.1's own long options that take no value. A word after any other
# long option may be that option's value rather than a target.
_LONG_FLAGS = frozenset({
    "--cache-clear", "--co", "--collect-in-virtualenv", "--collect-only", "--collectonly",
    "--continue-on-collection-errors", "--disable-plugin-autoload", "--disable-pytest-warnings",
    "--disable-warnings", "--doctest-continue-on-failure", "--doctest-ignore-import-errors", "--doctest-modules",
    "--exitfirst", "--failed-first", "--ff", "--fixtures", "--fixtures-per-test", "--force-short-summary",
    "--full-trace", "--fulltrace", "--funcargs", "--help", "--keep-duplicates", "--keepduplicates", "--last-failed",
    "--lf", "--markers", "--new-first", "--nf", "--no-fold-skipped", "--no-header", "--no-showlocals", "--no-summary",
    "--noconftest", "--pdb", "--pyargs", "--quiet", "--runxfail", "--setup-only", "--setup-plan", "--setup-show",
    "--setuponly", "--setupplan", "--setupshow", "--showlocals", "--stepwise", "--stepwise-reset", "--stepwise-skip",
    "--strict", "--strict-config", "--strict-markers", "--sw", "--sw-reset", "--sw-skip", "--trace",
    "--trace-config", "--traceconfig", "--verbose", "--version", "--xfail-tb",
})
# A pattern with a slash matches pytest's absolute path. Matching at the
# shallowest checkout decides for every deeper one; matching only deeper is
# unknown.
_SHALLOW, _DEEP = 1, 32
_READ_ERRORS = (OSError, ValueError, TypeError, RuntimeError, RecursionError)


class _Unknown(Exception):
    """pytest refuses the configuration, or this reading cannot follow it."""


def _joined(node):
    """`os.path.join` of string constants, as the path it builds, or None."""
    if (isinstance(node, ast.Call) and node.args and not node.keywords
            and isinstance(node.func, ast.Attribute) and node.func.attr == "join"
            and isinstance(node.func.value, ast.Attribute) and node.func.value.attr == "path"
            and isinstance(node.func.value.value, ast.Name) and node.func.value.value.id == "os"
            and all(isinstance(argument, ast.Constant) and isinstance(argument.value, str) for argument in node.args)):
        return posixpath.join(*(argument.value.replace("\\", "/") for argument in node.args))
    return None


def _entries(node, certain=True):
    """The strings a literal ignore-list expression can hold, each with whether it holds it for certain, or None.

    A literal list or tuple of strings or `os.path.join` of strings, a
    concatenation of such lists, or a conditional between two of them, whose
    arms each hold their entries only maybe.
    """
    if isinstance(node, (ast.List, ast.Tuple)):
        values = []
        for element in node.elts:
            if isinstance(element, ast.Constant) and isinstance(element.value, str):
                values.append((element.value, certain))
            elif _joined(element) is not None:
                values.append((_joined(element), certain))
            else:
                return None
        return values
    if isinstance(node, ast.IfExp):
        body, orelse = _entries(node.body, False), _entries(node.orelse, False)
        return None if body is None or orelse is None else body + orelse
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _entries(node.left, certain), _entries(node.right, certain)
        return None if left is None or right is None else left + right
    return None


def _ignore_entries(node):
    """What a module-level statement or call does to an ignore list: (name, entries, binds, the name node), or None.

    The entries are None where they are not literal.
    """
    if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        named = [target for target in targets if isinstance(target, ast.Name) and target.id in _IGNORES]
        if not named:
            return None
        if node.value is None:
            return named[0].id, [], False, named[0]  # an annotation binds nothing
        values = _entries(node.value) if len(targets) == 1 else None
        return named[0].id, values, not isinstance(node, ast.AugAssign), named[0]
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
            and isinstance(node.func.value, ast.Name) and node.func.value.id in _IGNORES:
        values = None
        if not node.keywords and len(node.args) == 1 and node.func.attr == "append":
            values = _entries(ast.List(elts=node.args, ctx=ast.Load()))
        elif not node.keywords and len(node.args) == 1 and node.func.attr == "extend":
            values = _entries(node.args[0])
        elif not node.keywords and len(node.args) == 2 and node.func.attr == "insert":
            values = _entries(ast.List(elts=node.args[1:], ctx=ast.Load()))
        return node.func.value.id, values, False, node.func.value
    return None


# A list a conftest binds, or changes, in a way this reading does not follow.
_UNREAD_LIST = object()


def _conftest_ignores(source):
    """{"collect_ignore": ..., "collect_ignore_glob": ...} a conftest binds, or None when anything is possible.

    pytest reads the module's own lists once it has run. Each is a pair of
    literal entries, those the module certainly holds and those it may hold
    (added under a condition, an arm of a conditional expression, or kept
    only if a conditional rebinding does not run); None when the module
    never binds it, so that a nearer conftest's bound list hides the ones
    above; or `_UNREAD_LIST` when the module binds or changes it other than
    by a module-level literal assignment, `append`, `extend` or `insert`: in
    a function that does not bind the name itself, through `global`, an
    attribute, a keyword or the name as a string. A function's or a class's
    own name is its own: a local list or a class attribute is not the
    module's.

    None, anything possible, for a conftest pytest cannot import or whose
    code may define a hook or load a plugin, which can collect or leave out
    any path: a `pytest_` name, a star import, `exec`, `eval`, `globals()`,
    `vars()` and `__dict__`.
    """
    try:
        # Bytes, so that a coding declaration decides the text, as for Python.
        tree = ast.parse(source)
    except (SyntaxError, UnicodeError, ValueError, RecursionError, MemoryError):
        return None
    calls_with_arguments = {id(node.func) for node in ast.walk(tree)
                            if isinstance(node, ast.Call) and node.args and isinstance(node.func, ast.Name)}
    unread = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name.startswith("pytest_"):
            return None
        if isinstance(node, ast.alias) and (node.name == "*" or any(
                part.startswith("pytest_") for part in (node.asname or node.name).split("."))):
            return None
        if (isinstance(node, ast.Name) and (node.id.startswith("pytest_") or node.id in _DYNAMIC
                                            or (node.id == "vars" and id(node) not in calls_with_arguments))) \
                or (isinstance(node, ast.Attribute) and node.attr == "__dict__"):
            return None
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name in _IGNORES:
            unread.add(node.name)
        elif isinstance(node, ast.alias) and (node.asname or node.name.split(".")[0]) in _IGNORES:
            unread.add(node.asname or node.name.split(".")[0])
        elif isinstance(node, ast.Attribute) and node.attr in _IGNORES:
            unread.add(node.attr)
        elif isinstance(node, ast.keyword) and node.arg in _IGNORES:
            unread.add(node.arg)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in _IGNORES:
            unread.add(node.value)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            unread.update(name for name in node.names if name in _IGNORES)
    # Each list: None while unbound, else [certain entries, possible entries]
    # in module order. A binding that always runs replaces the list; one that
    # may not run, and an entry added under a condition, are only possible.
    lists = {name: None for name in _IGNORES}
    unbound_additions = set()
    taken = set()
    mentions = []  # (name node, its scope, whether a comprehension binds it)
    binds_parameter = set()

    def visit(node, scope, generator=False, conditional=False):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            arguments = node.args
            every = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs,
                     *(argument for argument in (arguments.vararg, arguments.kwarg) if argument is not None)]
            # Decorators, defaults and annotations run in the enclosing scope.
            for part in (*getattr(node, "decorator_list", ()), *arguments.defaults,
                         *(default for default in arguments.kw_defaults if default is not None),
                         *(argument.annotation for argument in every if argument.annotation is not None),
                         *((node.returns,) if getattr(node, "returns", None) is not None else ())):
                visit(part, scope)
            if any(argument.arg in _IGNORES for argument in every):
                binds_parameter.add(id(node))
            for part in (node.body if isinstance(node.body, list) else [node.body]):
                visit(part, node)
            return
        if isinstance(node, ast.ClassDef):
            for part in (*node.decorator_list, *node.bases, *(keyword.value for keyword in node.keywords)):
                visit(part, scope)
            for part in node.body:
                visit(part, node)
            return
        if scope is tree:
            found = _ignore_entries(node)
            if found is not None:
                name, values, binds, mention = found
                taken.add(id(mention))
                if values is None:
                    unread.add(name)
                else:
                    certain = [entry for entry, sure in values if sure and not conditional]
                    possible = [entry for entry, sure in values if not sure or conditional]
                    state = lists[name]
                    if binds and not conditional:
                        lists[name] = [certain, possible]
                    elif binds:
                        lists[name] = [[], [*(state[0] + state[1] if state else []), *certain, *possible]]
                    elif state is None:
                        unbound_additions.add(name)
                    else:
                        state[0].extend(certain)
                        state[1].extend(possible)
        if isinstance(node, ast.comprehension):
            visit(node.target, scope, generator=True, conditional=conditional)
            for part in (node.iter, *node.ifs):
                visit(part, scope, conditional=conditional)
            return
        if isinstance(node, ast.Name) and node.id in _IGNORES:
            mentions.append((node, scope, generator))
        # Whatever a compound statement holds may not run, or may run again.
        nested = conditional or isinstance(node, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.With,
                                                  ast.AsyncWith, ast.Match, getattr(ast, "TryStar", ast.Try)))
        for child in ast.iter_child_nodes(node):
            visit(child, scope, generator, nested)

    try:
        visit(tree, tree)
    except RecursionError:
        return None
    scopes = {}
    for node, scope, generator in mentions:
        if scope is tree:
            if id(node) not in taken:
                unread.add(node.id)  # a loop target, a subscript, a read, a `del`
        elif isinstance(scope, ast.ClassDef):
            if isinstance(node.ctx, ast.Load):
                unread.add(node.id)  # it may read the module's list
        else:
            own = scopes.setdefault((id(scope), node.id), [id(scope) in binds_parameter, False])
            if isinstance(node.ctx, ast.Load) or generator:
                own[1] = True
            else:
                own[0] = True
    # A function that never binds the name itself reads or changes the module's list.
    unread.update(name for (_scope, name), (bound_here, used) in scopes.items() if used and not bound_here)
    if unbound_additions - unread:
        return None  # an entry added to a list the module has not bound: its import fails
    return {name: _UNREAD_LIST if name in unread else None if lists[name] is None
            else (tuple(lists[name][0]), tuple(lists[name][1])) for name in _IGNORES}


def _ini_sections(text):
    """{section: {name: value}} as iniconfig reads an INI file for pytest, inline comments kept.

    Raises _Unknown where iniconfig refuses the file, which stops pytest.
    """
    sections = {}
    section = None
    value = None
    for line in text.removeprefix("\ufeff").splitlines():
        if line.lstrip()[:1] in ("#", ";") or not line.rstrip():
            continue
        line = line.rstrip()
        if line[0] == "[":
            header = line
            for char in "#;":
                header = header.split(char)[0].rstrip()
            if header.endswith("]"):
                name = header[1:-1]
                if not name or name in sections:
                    raise _Unknown
                section, value = name, None
                sections[section] = {}
                continue
            # iniconfig takes any other line that starts with "[" for a continuation.
            if value is None:
                raise _Unknown
            value.append(line.strip())
        elif not line[0].isspace():
            name, separator, rest = line.partition("=")
            if not separator or ":" in name:
                name, separator, rest = line.partition(":")
                if not separator:
                    raise _Unknown
            name, rest = name.strip(), rest.strip()
            if section is None or name in sections[section]:
                raise _Unknown
            value = [rest] if rest else []
            sections[section][name] = value
        else:
            if value is None:
                raise _Unknown
            value.append(line.strip())
    return {section: {name: "\n".join(lines) for name, lines in names.items()} for section, names in sections.items()}


def _load(name, data):
    """The pytest settings one root file holds, as `load_config_dict_from_file` loads them.

    {setting: (mode, value)}, or None when the file holds no pytest
    configuration. Raises _Unknown where pytest refuses the file.
    """
    if not isinstance(data, bytes):
        raise _Unknown
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise _Unknown from None
    if name.endswith(".ini"):
        sections = _ini_sections(text)
        if "pytest" in sections:
            return {key: ("ini", value) for key, value in sections["pytest"].items()}
        return {} if name in ("pytest.ini", ".pytest.ini") else None
    if name.endswith(".cfg"):
        sections = _ini_sections(text)
        if "tool:pytest" in sections:
            return {key: ("ini", value) for key, value in sections["tool:pytest"].items()}
        if "pytest" in sections:
            raise _Unknown  # pytest refuses a [pytest] section in setup.cfg
        return None
    try:
        document = tomllib.loads(text)  # a BOM is refused, as pytest refuses it
    except tomllib.TOMLDecodeError:
        raise _Unknown from None
    if name in ("pytest.toml", ".pytest.toml"):
        table = document.get("pytest", {})
        if not isinstance(table, dict):
            raise _Unknown
        return {key: ("toml", value) for key, value in table.items()}
    tool = document.get("tool", {})
    table = tool.get("pytest", {}) if isinstance(tool, dict) else None
    if not isinstance(table, dict):
        raise _Unknown
    native = {key: value for key, value in table.items() if key != "ini_options"}
    ini = table.get("ini_options")
    if native and ini:
        raise _Unknown  # pytest refuses both tables
    if native:
        return {key: ("toml", value) for key, value in native.items()}
    if ini is None:
        return None
    if not isinstance(ini, dict):
        raise _Unknown
    return {key: ("ini", value if isinstance(value, list) else str(value)) for key, value in ini.items()}


def _arguments(mode, value):
    """An `args` setting's words, as `Config._getini` gives them."""
    if mode == "ini" and isinstance(value, str):
        try:
            return tuple(shlex.split(value))
        except ValueError:
            raise _Unknown from None
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return tuple(value)
    raise _Unknown


def _addopts(words):
    """The options and positional words of addopts, as pytest's argument parser reads them.

    Returns ([(option, value)], [(positional word, uncertain)]): a word is
    uncertain after a long option this reading cannot place, whose value it
    may be. Raises _Unknown on a combined short option it does not know.
    """
    from checkwash.shadow import _PYTEST_OPTIONS_WITH_OPTIONAL_VALUE, _PYTEST_OPTIONS_WITH_VALUE

    options, positional = [], []
    unplaced = False
    index = 0
    while index < len(words):
        word = words[index]
        index += 1
        if word == "--":
            positional.extend((rest, False) for rest in words[index:])
            break
        if word.startswith("--"):
            name, equals, value = word.partition("=")
            if not equals and index < len(words) and (
                    name in _PYTEST_OPTIONS_WITH_VALUE
                    or (name in _PYTEST_OPTIONS_WITH_OPTIONAL_VALUE and not words[index].startswith("-"))):
                value = words[index]
                index += 1
            options.append((name, value))
            unplaced = not equals and name not in _LONG_FLAGS and name not in _PYTEST_OPTIONS_WITH_VALUE \
                and name not in _PYTEST_OPTIONS_WITH_OPTIONAL_VALUE
            continue
        if word.startswith("-") and len(word) > 1:
            for at, char in enumerate(word[1:], start=2):
                if char in _SHORT_VALUES:
                    value = word[at:]
                    if not value and index < len(words):
                        value = words[index]
                        index += 1
                    options.append(("-" + char, value))
                    break
                if char not in _SHORT_FLAGS:
                    raise _Unknown
                options.append(("-" + char, ""))
        else:
            positional.append((word, unplaced))
        unplaced = False
    return options, positional


def _root_settings(read_many):
    """The settings pytest 9 takes from the repository root for a plain run there, as word tuples.

    The config is found as `locate_config` finds it, from the root only,
    and loaded as `load_config_dict_from_file` loads it; pytest loads each
    later config file too, to report it ignored, so a refused one stops it.
    The `-o` overrides in addopts then apply, as `Config._preparse` applies
    them, the last one winning. Raises _Unknown where pytest would stop.
    """
    files = read_many(_CONFIG_ORDER)
    found = {}
    for index, name in enumerate(_CONFIG_ORDER):
        if files.get(name) is None:
            continue
        loaded = _load(name, files[name])
        if loaded is not None:
            for later in _CONFIG_ORDER[index + 1:]:
                if files.get(later) is not None:
                    _load(later, files[later])
            found = loaded
            break
    settings = {key: _arguments(*found[key]) if key in found else default for key, default in _DEFAULTS.items()}
    explicit = {key for key in _DEFAULTS if key in found}
    options, _positional = _addopts(settings["addopts"])
    for option, value in options:
        if option in ("-o", "--override-ini"):
            key, separator, content = value.partition("=")
            if not separator:
                raise _Unknown
            if key in settings and key != "addopts":
                settings[key] = _arguments("ini", content)
                explicit.add(key)
    settings["explicit"] = frozenset(explicit)
    return settings


def _prefixes(path):
    parts = path.split("/")
    return ["/".join(parts[:end]) for end in range(1, len(parts) + 1)]


def _magic(pattern):
    return any(char in pattern for char in "*?[")


def _path_glob(path, pattern, depth=_SHALLOW):
    """pytest's `fnmatch_ex`: a pattern without a slash matches the last name, one with a slash the absolute path.

    The absolute path is the repository's own below a checkout `depth`
    directories deep.
    """
    if "/" not in pattern:
        return fnmatch.fnmatchcase(path.rsplit("/", 1)[-1], pattern)
    return not pattern.startswith("/") and fnmatch.fnmatchcase("/\0" * depth + "/" + path, "*/" + pattern)


def _path_globs(path, patterns):
    """True when a pattern matches at every checkout depth, None when one may match only at some, else False.

    An absolute pattern names one checkout's own path, which may be this one.
    """
    if any(_path_glob(path, pattern) for pattern in patterns):
        return True
    return None if any(pattern.startswith("/") or _path_glob(path, pattern, _DEEP) for pattern in patterns) else False


def _prefix_or_glob(name, patterns):
    """pytest's reading of `python_functions`: a prefix, or a glob when the pattern holds one."""
    return any(name.startswith(pattern) or (_magic(pattern) and fnmatch.fnmatchcase(name, pattern))
               for pattern in patterns)


def _glob_close(states, parts):
    """`**` matches no name as well."""
    states, stack = set(states), list(states)
    while stack:
        at = stack.pop()
        if at < len(parts) and parts[at] == "**" and at + 1 not in states:
            states.add(at + 1)
            stack.append(at + 1)
    return states


def _glob_step(states, name, parts, strict):
    """The pattern positions after one more path name, as `glob.iglob(..., recursive=True)` matches.

    Strict reading keeps glob's rule that a wildcard skips a hidden name; the
    loose reading drops it, so it matches at least what glob matches.
    """
    hidden = strict and name.startswith(".")
    following = set()
    for at in states:
        if at >= len(parts):
            continue
        head = parts[at]
        if head == "**":
            if not hidden:
                following.add(at)
        elif not _magic(head):
            if name == head:
                following.add(at + 1)
        elif fnmatch.fnmatchcase(name, head) and not (hidden and not head.startswith(".")):
            following.add(at + 1)
    return _glob_close(following, parts)


def _glob_reaches(names, parts):
    """Could the glob yield the directory named by `names`, or a path below it?"""
    states = _glob_close({0}, parts)
    for name in names:
        states = _glob_step(states, name, parts, strict=False)
        if not states:
            return False
    return True


def _subsumed(argument, by):
    """pytest's `is_collection_argument_subsumed_by` for (path, parts, parametrization)."""
    path, parts, parametrization = argument
    by_path, by_parts, by_parametrization = by
    if by_path != path:
        return not by_parts and (by_path == "" or path.startswith(by_path + "/"))
    if len(by_parts) > len(parts) or parts[:len(by_parts)] != by_parts:
        return False
    return by_parametrization is None or by_parametrization == parametrization


class Collection:
    """What pytest collects at head, for a targetless run from the repository root.

    Calling it asks whether pytest certainly collects a test, which is what
    pays a credit; `excludes` asks whether it certainly does not collect a
    file, which is what makes a finding. Unknown answers no to both.
    """

    def __init__(self, decide):
        self._decide = decide

    def __call__(self, path, qualname, source=None):
        return self._decide(path, qualname, source) is True

    def excludes(self, path):
        return self._decide(path, None) is False


def arrival_collector(read, list_paths=None, read_many=None):
    """The head's `Collection`, read through `read`, `read_many` and `list_paths`.

    `read(path)` gives a repository path's head bytes, or None when it is
    absent, and raises when it cannot be read; `read_many(paths)` gives
    several as a mapping, and stands for repeated `read` calls when absent;
    `list_paths()` gives the head's inventory, a submodule or directory link
    as its path with a trailing slash, or is None.
    """
    from checkwash.change import EngineError
    from checkwash.opaque import split_inventory
    from checkwash.shadow import _normalise_root

    errors = (EngineError, _Unknown, *_READ_ERRORS)
    many = read_many if read_many is not None else (lambda paths: {path: read(path) for path in paths})
    unknown = Collection(lambda path, qualname, source=None: None)
    try:
        settings = _root_settings(many)
        options, positional = _addopts(settings["addopts"])
    except errors:
        return unknown
    if any(word.startswith("@") for word in settings["addopts"]):
        return unknown  # argparse reads the arguments from that file (`fromfile_prefix_chars`)
    for option, value in options:
        if option in _UNREAD_OPTIONS:
            return unknown
        if option == "--rootdir" and _normalise_root(value) != "":
            return unknown
        if option == "-p" and (not value.startswith("no:") or value[3:] in _COLLECTING_PLUGINS):
            return unknown  # a loaded plugin may leave tests out; these two collect them
    # A keyword expression selects tests, not files: it leaves every test
    # unknown and every file decided.
    keyword = any(option == "-k" for option, _value in options)
    ignored, globs = [], []
    for option, value in options:
        if option in ("--ignore", "--ignore-glob"):
            value = value.replace("\\", "/")
            if not value or value.startswith("/") or ":" in value:
                return unknown
            (ignored if option == "--ignore" else globs).append(posixpath.normpath(value))
    deselected = [value for option, value in options if option == "--deselect" and value]
    if any(pattern.startswith("/") for pattern in settings["norecursedirs"]):
        return unknown
    # Conftests are not loaded at all, or only those at or below a cut.
    noconftest = any(option == "--noconftest" for option, _value in options)
    cuts = [_normalise_root(value) for option, value in options if option == "--confcutdir"]
    if None in cuts:
        return unknown
    confcut = cuts[-1] if cuts else ""
    in_virtualenv = any(option == "--collect-in-virtualenv" for option, _value in options)
    targets, uncertain = [], set()
    for word, unplaced in positional:
        base, bracket, rest = word.partition("[")
        path, *parts = base.split("::")
        target = _normalise_root(path)
        if target is None or (bracket and not parts):
            return unknown  # outside the repository, not a path, or a path pytest refuses
        targets.append((target, tuple(parts), bracket + rest if bracket else None))
        if unplaced:
            uncertain.add(targets[-1])
    listing = []

    def inventory():
        """The head's files, opaque directories and the files' tree, listed once and only when needed."""
        if not listing:
            try:
                listed = list_paths() if list_paths is not None else None
            except errors:
                listed = None
            if listed is None:
                listing.append((None, (), None))
            else:
                files, opaque = split_inventory(listed)
                paths = frozenset(path for path in files if isinstance(path, str))
                tree = {}
                for path in paths:
                    node = tree
                    for name in path.split("/"):
                        node = node.setdefault(name, {})
                listing.append((paths, opaque, tree))
        return listing[0]

    if targets:
        paths, opaque, _tree = inventory()
        if paths is None:
            return unknown  # a target cannot be told from an unknown option's value

        def holds_tests(target, parts):
            """A target pytest takes for one: a word naming nothing is an unknown option's value, as in
            collection_inventory._addopts_targets, and so is a directory without a test module in it."""
            if target == "":
                return True
            if target in paths:
                return bool(parts) or target.endswith(".py")
            if parts:
                return False
            if any(target == directory or target.startswith(directory + "/") or directory.startswith(target + "/")
                   for directory in opaque):
                return True
            return any(path.startswith(target + "/") and path.endswith(".py")
                       and _path_globs(path, settings["python_files"]) is not False for path in paths)

        kept = sorted((argument for argument in targets if holds_tests(argument[0], argument[1])),
                      key=lambda argument: (tuple(argument[0].split("/")) if argument[0] else (), argument[1],
                                            argument[2] or ""))
        if uncertain.intersection(kept):
            return unknown  # a word that may be an unknown option's value decides the initial paths
        targets = []
        for argument in kept:
            if not targets or not _subsumed(argument, targets[-1]):
                targets.append(argument)
    # A run with targets ignores testpaths.
    roots = () if targets else tuple(posixpath.normpath(root.replace("\\", "/")) for root in settings["testpaths"])
    existing = {}

    def exists(root):
        """Does a testpath exist at head: True, False, or None when unknown?"""
        if root not in existing:
            parts = root.split("/")
            if root == ".":
                existing[root] = True
            elif root.startswith("/") or ".." in parts:
                existing[root] = None  # outside the repository
            else:
                paths, opaque, tree = inventory()
                if paths is None:
                    existing[root] = None
                elif not any(_magic(part) for part in parts):
                    if (root in paths or any(path.startswith(root + "/") for path in paths)
                            or any(directory == root or directory.startswith(root + "/") for directory in opaque)):
                        existing[root] = True
                    elif any(root.startswith(directory + "/") for directory in opaque):
                        existing[root] = None
                    else:
                        existing[root] = False
                else:
                    found = False
                    stack = [(tree, _glob_close({0}, parts))]
                    while stack and not found:
                        node, states = stack.pop()
                        for name, child in node.items():
                            following = _glob_step(states, name, parts, strict=False)
                            if len(parts) in following:
                                found = True
                                break
                            if following:
                                stack.append((child, following))
                    if found:
                        existing[root] = True
                    elif any(_glob_reaches(directory.split("/"), parts) for directory in opaque):
                        existing[root] = None
                    else:
                        existing[root] = False
        return existing[root]

    def anchor(path):
        """(the initial path a run reaches `path` through, '' for the root, and the node ids it selects there or None).

        False when no initial path reaches it, None when unknown. pytest keeps
        the outermost of overlapping initial paths (`normalize_collection_arguments`).
        """
        if targets:
            hits = [argument for argument in targets
                    if argument[0] == "" or path == argument[0] or path.startswith(argument[0] + "/")]
            if not hits:
                return False
            whole = [argument for argument in hits if not argument[1]]
            start = min((argument[0] for argument in hits), key=len)
            return start, None if whole else [(argument[1], argument[2]) for argument in hits]
        if roots:
            if "." in roots:
                return "", None
            names = path.split("/")
            shortest = None
            for root in roots:
                parts = root.split("/")
                states = _glob_close({0}, parts)
                for end, name in enumerate(names, start=1):
                    states = _glob_step(states, name, parts, strict=True)
                    if not states:
                        break
                    if len(parts) in states:
                        if shortest is None or end < shortest:
                            shortest = end
                        break
            if shortest is not None:
                return "/".join(names[:shortest]), None
            # pytest searches from the root only when no testpath exists.
            found = [exists(root) for root in roots]
            return False if True in found else (None if None in found else ("", None))
        return "", None

    probed: dict[str, object] = {}
    failed = object()

    def probe(paths):
        """Read the paths not read yet, together; a refusal leaves each of them unknown."""
        wanted = [path for path in dict.fromkeys(paths) if path not in probed]
        if wanted:
            try:
                found = many(wanted)
            except errors:
                found = {}
                for path in wanted:
                    try:
                        found[path] = read(path)
                    except errors:
                        found[path] = failed
            for path in wanted:
                probed[path] = found.get(path, failed)
        return {path: probed[path] for path in paths}

    def environment(directory):
        """Does pytest take this directory for a virtual environment (`_in_venv`): True, False or None?"""
        markers = probe([f"{directory}/pyvenv.cfg", f"{directory}/conda-meta/history"]).values()
        if any(marker is not None and marker is not failed for marker in markers):
            return True
        return None if failed in markers else False

    chain: dict[str, dict | None] = {}

    def conftest(directory):
        cpath = f"{directory}/conftest.py" if directory else "conftest.py"
        if cpath not in chain:
            source = probe([cpath])[cpath]
            if source is None:
                chain[cpath] = {name: None for name in _IGNORES}
            elif source is failed or not isinstance(source, bytes):
                chain[cpath] = None
            else:
                chain[cpath] = _conftest_ignores(source)
        return chain[cpath]

    trees = {}

    def classes(path, names, source):
        """Are the classes holding a test collected under a configured python_classes: True, False or None?

        A class with bases may be a TestCase, which pytest's unittest plugin
        collects whatever its name; one whose base is spelled `...TestCase`
        is taken for one, any other is unknown.
        """
        if path not in trees:
            try:
                trees[path] = ast.parse(source) if isinstance(source, bytes) else None
            except (SyntaxError, UnicodeError, ValueError, RecursionError, MemoryError):
                trees[path] = None
        scope = trees[path].body if trees[path] is not None else None
        if scope is None:
            return None
        for name in names:
            found = [node for node in scope if isinstance(node, ast.ClassDef) and node.name == name]
            if not found:
                return None
            cls = found[-1]
            if _prefix_or_glob(name, settings["python_classes"]):
                if not cls.bases and any(isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                                         and item.name in ("__init__", "__new__") for item in cls.body):
                    return False  # pytest warns and does not collect a class with a constructor
            elif any(ast.unparse(base).rsplit(".", 1)[-1].endswith("TestCase") for base in cls.bases):
                pass
            elif cls.bases:
                return None
            else:
                return False
            scope = cls.body
        return True

    def decide(path, qualname, source=None):
        """True when pytest collects `path` (and the test `qualname` in it), False when it does not, None when unknown.

        A certain exclusion decides even beside an unknown, so each check
        runs before an unknown answers.
        """
        if path.startswith("/") or ":" in path or any(part in ("", ".", "..") for part in path.split("/")):
            return None  # not a repository path
        if not path.endswith(".py"):
            return False
        found = anchor(path)
        if found is False:
            return False
        answers = []
        if found is None:
            answers.append(None)
            start, selections = "", None
        else:
            start, selections = found
        # pytest never asks whether to ignore an initial path or a directory
        # above one (`isinitpath`): norecursedirs, virtual environments,
        # --ignore, --ignore-glob and the conftest lists judge only the paths
        # below it.
        prefixes = [prefix for prefix in _prefixes(path) if not (start + "/").startswith(prefix + "/")]
        directories = [prefix for prefix in prefixes if prefix != path]
        # The conftests pytest loads above the path, the root first.
        chain_directories = [] if noconftest else [
            directory for directory in ["", *_prefixes(path)[:-1]]
            if confcut == "" or directory == confcut or directory.startswith(confcut + "/")]
        markers = [] if in_virtualenv else [f"{directory}/{marker}" for directory in directories
                                            for marker in ("pyvenv.cfg", "conda-meta/history")]
        probe([*(f"{directory}/conftest.py" if directory else "conftest.py" for directory in chain_directories),
               *markers])
        states = [conftest(directory) for directory in chain_directories]
        if any(state is None for state in states):
            return None  # a hook in the chain can collect, or leave out, any path
        # pytest collects a file named as an initial path whatever its name.
        if path != start:
            included = _path_globs(path, settings["python_files"])
            if included is False:
                return False
            if included is None:
                answers.append(None)
        for directory in directories:
            excluded = _path_globs(directory, settings["norecursedirs"])
            if excluded:
                return False
            if excluded is None:
                answers.append(None)
        if any(prefix == root for prefix in prefixes for root in ignored):
            return False
        if any(fnmatch.fnmatchcase(prefix, pattern) for prefix in prefixes for pattern in globs):
            return False
        for directory in [] if in_virtualenv else directories:
            venv = environment(directory)
            if venv:
                return False
            if venv is None:
                answers.append(None)
        # Each path is judged by the nearest conftest above it that binds each
        # list (`_getconftest_pathlist`), read relative to that conftest.
        governing = {directory: {name: None for name in _IGNORES} for directory in ["", *_prefixes(path)[:-1]]}
        nearest = {name: None for name in _IGNORES}
        for directory, state in zip(chain_directories, states):
            for name in _IGNORES:
                if state[name] is not None:
                    nearest[name] = (directory, state[name])
            governing[directory] = dict(nearest)
        for prefix in prefixes:
            for name, rule in governing[posixpath.dirname(prefix)].items():
                if rule is None:
                    continue
                directory, entries = rule
                if entries is _UNREAD_LIST:
                    answers.append(None)
                    continue
                base = directory + "/" if directory else ""
                certain, possible = entries
                for entry, sure in (*((entry, True) for entry in certain), *((entry, False) for entry in possible)):
                    entry = entry.replace("\\", "/")
                    if entry.startswith("/") or ":" in entry:
                        answers.append(None)
                        continue
                    entry = posixpath.normpath(base + entry)
                    if prefix == entry if name == "collect_ignore" else fnmatch.fnmatchcase(prefix, entry):
                        if sure:
                            return False
                        answers.append(None)  # an entry the module adds only under a condition
        if qualname is None:
            # A --deselect that every node id in the file starts with deselects the file.
            if any(path.startswith(value) for value in deselected):
                return False
        else:
            test = qualname.split("#", 1)[0]
            node = path + "::" + test.replace(".", "::")
            if any(node.startswith(value) for value in deselected):
                return False
            if any(value.startswith(node + "[") for value in deselected):
                answers.append(None)  # one of its rows, if it has rows
            if not _prefix_or_glob(test.rsplit(".", 1)[-1], settings["python_functions"]):
                return False
            if selections is not None:
                names = tuple(test.split("."))
                chosen = [parametrization for parts, parametrization in selections if names[:len(parts)] == parts]
                if not chosen:
                    return False
                if None not in chosen:
                    answers.append(None)  # only some of its rows run
            if "python_classes" in settings["explicit"] and "." in test:
                held = classes(path, test.split(".")[:-1], source)
                if held is False:
                    return False
                if held is None:
                    answers.append(None)
            if keyword:
                answers.append(None)
        return None if None in answers else True

    def guarded(path, qualname, source=None):
        try:
            return decide(path, qualname, source)
        except errors:
            return None

    return Collection(guarded)

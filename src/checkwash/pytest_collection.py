"""Compare bounded pytest collection settings, including option arguments.

The old CI token scan cannot see a narrower value of a token that already
exists. This parser recognizes literal settings and command-line selectors;
it neither imports pytest nor executes configuration or shell expressions.
"""
from __future__ import annotations

import ast
from collections import Counter
import fnmatch
import re
import shlex

_SETTING = re.compile(r"^\s*(testpaths|python_files|python_classes|python_functions|norecursedirs|addopts)\s*=\s*(.*)$")
_VALUE_OPTIONS = {"--ignore", "--ignore-glob", "--deselect", "-k", "-m"}
_COLLECT_ONLY = {"--co", "--collect-only"}
_INCLUDE = {"testpaths", "python_files", "python_classes", "python_functions"}
_PYTEST_SECTIONS = {"[pytest]", "[tool:pytest]", "[tool.pytest.ini_options]"}


def _words(value: str) -> tuple[str, ...] | None:
    try:
        literal = ast.literal_eval(value)
    except (ValueError, SyntaxError, TypeError, RecursionError, MemoryError):
        literal = None
    if isinstance(literal, (list, tuple)):
        return tuple(literal) if all(isinstance(v, str) for v in literal) else None
    if isinstance(literal, str):
        value = literal
    try:
        return tuple(shlex.split(value, comments=True, posix=True))
    except ValueError:
        return None


def _bracket_depth(line: str, depth: int) -> int:
    """A TOML array's bracket depth after one more of its lines, strings and comments aside."""
    quote = ""
    escaped = False
    for char in line:
        if quote:
            if escaped:
                escaped = False
            elif char == "\\" and quote == '"':
                escaped = True
            elif char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
        elif char == "#":
            break
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
    return depth


def _comment_or_blank(line: str) -> bool:
    return not line.strip() or line.strip().startswith(("#", ";"))


def collection_settings(text: str) -> dict[str, set[tuple[str, ...]]]:
    """Literal INI/TOML values; ambiguous duplicate values remain distinct.

    A TOML array runs to the line that closes it, whatever its elements hold
    (`"--import-mode=importlib"`). A value that opens with neither a bracket
    nor a quote is an INI value, continued over every indented line, as
    iniconfig reads it, with or without `=` (#324). A quoted value is read
    as a TOML string and never continued (#327). A line a value spans is
    not read again as a setting or a section, and no value is evaluated.
    """
    values: dict[str, set[tuple[str, ...]]] = {}
    lines = text.splitlines()
    active = False
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        if line.strip().startswith("[") and line.strip().endswith("]"):
            active = line.strip() in _PYTEST_SECTIONS
        if not active:
            continue
        match = _SETTING.match(line)
        if not match:
            continue
        name, value = match.groups()
        if value.lstrip().startswith("["):
            block = [value]
            depth = _bracket_depth(value, 0)
            while depth > 0 and index < len(lines):
                block.append(lines[index])
                depth = _bracket_depth(lines[index], depth)
                index += 1
            value = "\n".join(block)
        elif not value.lstrip().startswith(("'", '"')):
            continued = [value.strip()]
            while index < len(lines) and (_comment_or_blank(lines[index]) or lines[index][:1].isspace()):
                if not _comment_or_blank(lines[index]):
                    continued.append(lines[index].strip())
                index += 1
            value = " ".join(part for part in continued if part)
        words = _words(value)
        if words is not None:
            values.setdefault(name, set()).add(words)
    return values


def _pytest_arguments(words):
    while words and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]):
        words = words[1:]
    if words and words[0] in {"env", "exec", "command"}:
        return _pytest_arguments(words[1:])
    if not words:
        return None
    program = words[0].replace("\\", "/").rsplit("/", 1)[-1]
    if program in {"pytest", "pytest.exe", "py.test", "py.test.exe"}:
        return words[1:]
    if program in {"uv", "poetry", "pipenv", "pdm"} and words[1:2] == ["run"]:
        return _pytest_arguments(words[2:])
    if re.fullmatch(r"(?:python(?:\d+(?:\.\d+)?)?|py)(?:\.exe)?", program):
        # Only Python's module launcher establishes a pytest invocation.
        # The coverage launcher may put another '-m' before pytest.
        for index in range(1, len(words) - 1):
            if words[index:index + 2] == ["-m", "pytest"]:
                return words[index + 2:]
            if words[index] in {"-c", "-"}:
                break
    return None


def _commands(text):
    """Each simple command of a text, as (its line's command text, its words).

    A line that does not lex yields its command text with None for words.
    """
    # Literal shell continuations retain arguments on the invocation line.
    for line in text.replace("\\\n", " ").replace("`\n", " ").splitlines():
        if _SETTING.match(line):
            continue
        command = re.sub(r"^\s*(?:-\s*)?(?:run|command|script):\s*", "", line)
        # YAML's quoted scalar contains one command, not a quoted executable.
        if command.startswith(('"', "'")) and command[-1:] == command[:1]:
            try:
                unquoted = ast.literal_eval(command)
            except (SyntaxError, ValueError, TypeError, MemoryError, RecursionError):
                unquoted = None
            if isinstance(unquoted, str):
                command = unquoted
        try:
            lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|")
            lexer.whitespace_split = True
            tokens = list(lexer)
        except ValueError:
            yield command, None
            continue
        words = []
        for token in [*tokens, ";"]:
            if token and set(token) <= set(";&|"):
                yield command, words
                words = []
            else:
                words.append(token)


def _option_arguments(text):
    yield from collection_settings(text).get("addopts", ())
    for _command, words in _commands(text):
        arguments = None if words is None else _pytest_arguments(words)
        if arguments is not None:
            yield arguments


def _spelled_options(words):
    """Each collection option in one invocation's arguments, with the span of words that spells it."""
    index = 0
    while index < len(words):
        start, word = index, words[index]
        if word == "--":
            break
        name, equals, value = word.partition("=")
        if word.startswith(("-k", "-m")) and len(word) > 2 and not word.startswith("--"):
            name, equals, value = word[:2], True, word[2:]
        elif word.startswith("-p") and len(word) > 2 and not word.startswith("--"):
            name, equals, value = "-p", True, word[2:]
        option = None
        if word in _COLLECT_ONLY:
            option = ("collect-only", "")
        elif name in _VALUE_OPTIONS:
            if not equals and index + 1 < len(words):
                index += 1
                value = words[index]
            if value and not value.startswith("-"):
                option = (name, value)
        elif name == "-p":
            if not equals and index + 1 < len(words):
                index += 1
                value = words[index]
            if value.startswith("no:"):
                option = ("-p", value)
        if option is not None:
            yield option, range(start, index + 1)
        index += 1


def collection_options(text: str) -> Counter[tuple[str, str]]:
    return Counter(option for words in _option_arguments(text) for option, _span in _spelled_options(words))


def resolved_collection_settings(text: str) -> dict[str, set[tuple[str, ...]]]:
    """Apply literal pytest -o/--override-ini values after ordinary settings.

    Preserve ambiguity between separate invocations; within an invocation
    pytest uses the last override of each name.
    """
    settings = collection_settings(text)
    overrides: dict[str, set[tuple[str, ...]]] = {}
    for words in _option_arguments(text):
        current = {}
        index = 0
        while index < len(words):
            word = words[index]
            if word == "--":
                break
            value = None
            if word in {"-o", "--override-ini"} and index + 1 < len(words):
                index += 1
                value = words[index]
            elif word.startswith("--override-ini="):
                value = word.split("=", 1)[1]
            elif word.startswith("-o") and not word.startswith("--"):
                value = word[2:]
            if value is not None:
                name, separator, content = value.partition("=")
                if separator and name in _INCLUDE | {"norecursedirs"}:
                    parsed = _words(content)
                    if parsed is not None:
                        current[name] = parsed
            index += 1
        for name, value in current.items():
            overrides.setdefault(name, set()).add(value)
    return {**settings, **overrides}


def _covered(child: str, parent: str, *, paths: bool) -> bool:
    if child == parent:
        return True
    if paths:
        child, parent = child.rstrip("/\\"), parent.rstrip("/\\")
        if not any(c in parent for c in "*?["):
            return child.startswith(parent + "/") or child.startswith(parent + "\\")
    # A literal belongs to a glob; two arbitrary globs need a language
    # inclusion proof we do not have. The common terminal-star prefix form
    # can be compared without assuming the repository's test inventory.
    if not any(c in child for c in "*?["):
        return fnmatch.fnmatchcase(child, parent)
    if parent.count("*") == 1 and not any(c in parent for c in "?["):
        prefix, suffix = parent.split("*")
        return child.startswith(prefix) and child.endswith(suffix)
    return False


def pytest_collection_changes(before_surface: str, after: str) -> list[str]:
    """New selectors or a provably stricter literal collection setting.

    Comparing against the whole before CI surface preserves config moves.
    First-time ordinary testpaths configuration is deliberately not treated
    as a narrowing; a new collect-only command does stop test execution.
    """
    findings = []
    old_options = collection_options(before_surface)
    for option in sorted(collection_options(after) if before_surface.strip() else ()):
        if option not in old_options:
            name, value = option
            findings.append("pytest collection option introduced: " + name + (" " + value if value else ""))
    old, new = resolved_collection_settings(before_surface), resolved_collection_settings(after)
    for name in sorted(_INCLUDE & old.keys() & new.keys()):
        # A config migration can produce several old values. Do not claim a
        # narrowing from only one arbitrarily chosen source.
        if len(old[name]) != 1 or len(new[name]) != 1:
            continue
        b, a = next(iter(old[name])), next(iter(new[name]))
        if not b or not a or set(a) == set(b):
            continue
        if (all(any(_covered(x, y, paths=name == "testpaths") for y in b) for x in a)
                and not all(any(_covered(y, x, paths=name == "testpaths") for x in a) for y in b)):
            findings.append("pytest " + name + " narrowed: " + " ".join(b) + " -> " + " ".join(a))
    if len(old.get("norecursedirs", ())) == 1 and len(new.get("norecursedirs", ())) == 1:
        b, a = next(iter(old["norecursedirs"])), next(iter(new["norecursedirs"]))
        if set(a) > set(b):
            findings.append("pytest norecursedirs gained exclusions")
    return findings

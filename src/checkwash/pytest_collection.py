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


def collection_settings(text: str) -> dict[str, set[tuple[str, ...]]]:
    """Literal INI/TOML values; ambiguous duplicate values remain distinct."""
    values: dict[str, set[tuple[str, ...]]] = {}
    lines = text.splitlines()
    for index, line in enumerate(lines):
        match = _SETTING.match(line)
        if not match:
            continue
        name, value = match.groups()
        # INI continuation lists and multiline TOML arrays are both bounded
        # by the next non-indented setting/section, never evaluated.
        if not value.strip() or value.strip() == "[":
            continued = []
            for following in lines[index + 1:]:
                stripped = following.strip()
                if stripped == "]":
                    continued.append("]")
                    break
                if not stripped or stripped.startswith(("#", ";")):
                    continue
                if not following[:1].isspace() or "=" in stripped or stripped.startswith("["):
                    break
                continued.append(stripped)
            value = value + " " + " ".join(continued)
        words = _words(value)
        if words is not None:
            values.setdefault(name, set()).add(words)
    return values


def collection_options(text: str) -> Counter[tuple[str, str]]:
    options: Counter[tuple[str, str]] = Counter()
    for line in text.splitlines():
        setting = _SETTING.match(line)
        if setting:
            if setting.group(1) != "addopts":
                continue
            words = _words(setting.group(2))
        else:
            # YAML run fields are shell command carriers, not option values.
            command = re.sub(r"^\s*(?:-\s*)?(?:run|command|script):\s*", "", line)
            words = _words(command)
        if words is None:
            continue
        index = 0
        while index < len(words):
            word = words[index]
            name, equals, value = word.partition("=")
            if word in _COLLECT_ONLY:
                options[("collect-only", "")] += 1
            elif name in _VALUE_OPTIONS:
                if not equals and index + 1 < len(words):
                    index += 1
                    value = words[index]
                if value and not value.startswith("-"):
                    options[(name, value)] += 1
            index += 1
    return options


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
    if parent.endswith("*") and not any(c in parent[:-1] for c in "*?["):
        return child.startswith(parent[:-1])
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
    old, new = collection_settings(before_surface), collection_settings(after)
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

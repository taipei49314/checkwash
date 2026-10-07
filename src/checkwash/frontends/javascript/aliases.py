"""Alias specifiers a JS/TS test file can name a first-party module by (#196 188.6).

A module mock and an import name one module when they resolve to one key
(`module_mocks.module_key`). Relative specifiers resolve against the test
file. Two kinds of alias resolve as well:

- **`@/` and `~/`.** By convention they name the project's own source root,
  whatever runner configuration maps them: the same alias string in a mock
  and an import is one module (`@/billing`, `@/billing.ts` and
  `@/billing/index` alike).
- **The base side's root `tsconfig.json`.** Its `compilerOptions.paths`
  map a specifier to a repository path, relative to `baseUrl` or, without
  one, to the repository root. A mapped specifier is the module at that
  path, so `vi.mock("@/billing")` and `import ... from "../src/billing"`
  are one module under `"@/*": ["src/*"]`. A pattern takes TypeScript's
  precedence: an exact pattern first, then the longest prefix; its first
  target is the module.

Bounded: the root `tsconfig.json` only, as the base side holds it, so a
diff cannot remap its own mocks; no `extends`, no nested or `jsconfig.json`
file, and no bundler or runner alias configuration. A pattern with an empty
prefix (`"*"`) is not read: it maps package names too, and only the file
inventory could tell them apart. For the same reason a bare specifier that
`baseUrl` alone would resolve is not first-party.
"""

from __future__ import annotations

import json
import posixpath
from dataclasses import dataclass

ALIAS_PREFIXES = ("@/", "~/")
MAX_TSCONFIG_BYTES = 256 * 1024
MAX_PATTERNS = 256


def _without_comments(text: str) -> str:
    """tsconfig.json is JSON with comments and trailing commas; drop both."""
    out: list[str] = []
    i, length = 0, len(text)
    while i < length:
        char = text[i]
        if char == '"':
            end = i + 1
            while end < length and text[end] != '"':
                end += 2 if text[end] == "\\" else 1
            out.append(text[i:end + 1])
            i = end + 1
        elif text.startswith("//", i):
            end = text.find("\n", i)
            i = length if end < 0 else end
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = length if end < 0 else end + 2
        elif char == ",":
            following = i + 1
            while following < length:
                if text[following].isspace():
                    following += 1
                elif text.startswith("//", following):
                    end = text.find("\n", following)
                    following = length if end < 0 else end
                elif text.startswith("/*", following):
                    end = text.find("*/", following + 2)
                    following = length if end < 0 else end + 2
                else:
                    break
            if following >= length or text[following] not in "}]":
                out.append(char)
            i += 1
        else:
            out.append(char)
            i += 1
    return "".join(out)


@dataclass(frozen=True)
class TsconfigPaths:
    """The `paths` patterns of one tsconfig.json, targets joined to `baseUrl`."""

    exact: dict[str, str]
    # (prefix, suffix, target), the longest prefix first; equal prefixes keep
    # the order the file declares them in, as TypeScript picks the first.
    wildcards: tuple[tuple[str, str, str], ...]

    def target(self, specifier: str) -> str | None:
        """The repository path a specifier maps to, unnormalized; None if no pattern matches."""
        if specifier in self.exact:
            return self.exact[specifier]
        for prefix, suffix, target in self.wildcards:
            if (len(specifier) >= len(prefix) + len(suffix)
                    and specifier.startswith(prefix) and specifier.endswith(suffix)):
                return target.replace("*", specifier[len(prefix):len(specifier) - len(suffix)], 1)
        return None


def tsconfig_paths(data: bytes | None) -> TsconfigPaths | None:
    """The `compilerOptions.paths` a root tsconfig.json states; None when it states none or cannot be read."""
    if data is None or len(data) > MAX_TSCONFIG_BYTES:
        return None
    try:
        config = json.loads(_without_comments(data.decode("utf-8-sig")))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None
    options = config.get("compilerOptions") if isinstance(config, dict) else None
    paths = options.get("paths") if isinstance(options, dict) else None
    if not isinstance(paths, dict):
        return None
    base_url = options.get("baseUrl", "")
    if not isinstance(base_url, str):
        return None
    exact: dict[str, str] = {}
    wildcards: list[tuple[str, str, str]] = []
    for pattern, targets in list(paths.items())[:MAX_PATTERNS]:
        if not isinstance(targets, list) or not targets or not isinstance(targets[0], str):
            continue
        first = targets[0]
        if pattern.count("*") > 1 or first.count("*") > (1 if "*" in pattern else 0):
            continue
        target = posixpath.join(base_url, first) if base_url else first
        if "*" not in pattern:
            exact[pattern] = target
            continue
        prefix, _star, suffix = pattern.partition("*")
        if prefix:
            wildcards.append((prefix, suffix, target))
    wildcards.sort(key=lambda entry: -len(entry[0]))
    if not exact and not wildcards:
        return None
    return TsconfigPaths(exact, tuple(wildcards))


class Aliases:
    """The base side's root tsconfig.json, read once and only when a specifier asks."""

    def __init__(self, read_tsconfig=None):
        self._read = read_tsconfig
        self._paths: list[TsconfigPaths | None] = []

    def target(self, specifier: str) -> str | None:
        if self._read is None:
            return None
        if not self._paths:
            self._paths.append(tsconfig_paths(self._read()))
        paths = self._paths[0]
        return paths.target(specifier) if paths is not None else None

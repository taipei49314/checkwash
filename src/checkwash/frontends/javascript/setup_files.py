"""Stand-ins a JavaScript setup file installs before every test file (#218).

Row 109 (#177) reads a module mock or a replacing spy written in the test
file whose oracle consumes it. A runner also loads setup files before every
test file, so the same `jest.mock("./src/billing", () => ({ invoiceTotal:
() => 78.75 }))` written there replaces the code under test for the whole
suite, while every test file and every assertion stays byte-identical. It
passed with zero findings: setup files have the production role, and the
mock scan reads only the file that holds the assertion. That is row 60's JS
twin, which CONFTEST_PATCHES_PROD closes for a Python conftest.

Carriers, as ruled on #218 (2026-10-06):

- `setupTests.js` and `setupTests.ts` (Create React App's `src/setupTests`);
- `jest.setup.*` and `vitest.setup.*`, with any JS or TS extension;
- the files the base side's root `package.json` names in `jest.setupFiles`
  and `jest.setupFilesAfterEnv`, spelled `./x` or `<rootDir>/x`; any other
  entry names a package, not a repository file.

The events, judged like CONFTEST_PATCHES_PROD: a newly observed stand-in
aimed at first-party code, without resolving which test reads it, reported
under TEST_PATCHES_SUBJECT with no unit:

- a first-party module mock or replacing spy in a carrier, read by the scan
  a test file's goes through (`module_mocks._Side`), so first-party means
  what it means there and a third-party mock (`jest.mock("axios")`) is
  hygiene. It is new unless a base-side carrier in the diff already
  installed it, so a mock moved between carriers or reformatted stays
  silent;
- `jest.enableAutomock()` in a carrier, new unless a base-side carrier in
  the diff already called it;
- `"automock": true` under the root `package.json`'s `jest` key, new unless
  the base side set it.

Residual: a rewritten manual mock under `__mocks__/` (S4); runner config
files (`jest.config.*`, `vitest.config.*`) and what they set, their
`setupFiles` and `automock` among them; a setup file that only the head
side's `package.json` names, under another name; `globalSetup`; and a
nested `package.json`.
"""

from __future__ import annotations

import json
import posixpath
import re

from checkwash.frontends.javascript.aliases import Aliases
from checkwash.frontends.javascript.bindings import CALL
from checkwash.frontends.javascript.frontend import _call_argument_spans
from checkwash.frontends.javascript.module_mocks import (
    _EXTENSIONS,
    _TRIGGER,
    _Install,
    _module_path,
    _possibly_one,
    _Side,
)

_NAMED = re.compile(r"(?:^|/)(?:setupTests\.(?:js|ts)|(?:jest|vitest)\.setup\.(?:[mc]?[jt]s|[jt]sx))\Z")
_LISTS = ("setupFiles", "setupFilesAfterEnv")
_ROOT_DIR = "<rootDir>/"
MAX_MANIFEST_BYTES = 1_000_000


def jest_config(data: bytes | None) -> dict:
    """The root package.json's `jest` object; {} when absent or unreadable."""
    if not data or len(data) > MAX_MANIFEST_BYTES:
        return {}
    try:
        manifest = json.loads(data.decode("utf-8-sig", errors="replace"))
    except (ValueError, RecursionError):
        return {}
    config = manifest.get("jest") if isinstance(manifest, dict) else None
    return config if isinstance(config, dict) else {}


def listed_setup_files(manifest: bytes | None) -> frozenset[str]:
    """Module keys of the repository files `jest.setupFiles` and
    `jest.setupFilesAfterEnv` name, extension-insensitive as Jest resolves
    them: `./jest.setup`, `./jest.setup.js` and `<rootDir>/jest.setup.ts`
    are one key."""
    config = jest_config(manifest)
    found: set[str] = set()
    for key in _LISTS:
        entries = config.get(key)
        for entry in entries if isinstance(entries, list) else ():
            if not isinstance(entry, str):
                continue
            if entry.startswith(_ROOT_DIR):
                entry = entry[len(_ROOT_DIR):]
            elif not entry.startswith(("./", "../")):
                continue  # a package, resolved from node_modules
            path = posixpath.normpath(entry)
            if path in {".", ".."} or path.startswith(("../", "/")):
                continue
            found.add(_module_path(path))
    return frozenset(found)


def is_carrier(path: str, listed: frozenset[str]) -> bool:
    """Does the runner load this file before every test file?"""
    path = path.replace("\\", "/")
    return bool(_NAMED.search(path)) or _module_path(path) in listed


def _automock_calls(side: _Side) -> list[tuple[str, tuple[int, int]]]:
    """(text, span) of each `jest.enableAutomock()`, `jest` the runner object."""
    masked, found = side.bindings.masked, []
    for call in CALL.finditer(masked):
        start = call.start()
        previous = start - 1
        while previous >= 0 and masked[previous].isspace():
            previous -= 1
        if previous >= 0 and masked[previous] in ".#":
            continue  # a member of something else
        parts = re.sub(r"\s+", "", call.group("callee")).split(".")
        if len(parts) != 2 or parts[1] != "enableAutomock" or side._runner(parts[0], start) != "jest":
            continue
        arguments = _call_argument_spans(side.text, side.code, call.end() - 1, len(side.text))
        end = arguments[1] if arguments is not None else call.end()
        found.append((side.text[start:end], (start, end)))
    return found


def _target(install: _Install) -> str:
    """What an installation replaces: one member, a whole module, or part of
    one. A partial factory's names are every name it spells and every name
    it merges in one hop (`_Side._factory_names`), which reads right when an
    oracle consumes one of them and lists runner calls too when nothing is
    consumed, so here the module is named. An opaque factory replaces the
    whole module (#196 188.5)."""
    if install.member is not None:
        return f"{install.module}:{'.'.join(install.member)}"
    if install.names is not None:
        return f"part of {install.module}"
    return install.module


def _installed_before(install: _Install, base: list[_Side]) -> bool:
    """Did a base-side carrier already replace it? Then it moved or was respelled.

    A member is covered by a spy on it or a module mock that replaces it; a
    whole-module mock by a whole-module mock. A partial mock is covered by
    any mock of its module: which exports a partial factory replaces is read
    only as every name it spells or merges in, and that set moves with any
    edit to the factory's body (`super.getContent()` ->
    `super.getContent(new Set())`). An opaque factory is a whole-module mock."""
    for side in base:
        if install.member is not None:
            if side.replaces(install.module, install.member):
                return True
            continue
        mocks = [other for other in side.installs
                 if other.member is None and _possibly_one(other.module, install.module)]
        if any(other.names is None for other in mocks) or (install.names is not None and mocks):
            return True
    return False


def setup_file_events(changes, manifest=None, read_tsconfig=None) -> list[tuple[str, None, str, str, tuple[int, int]]]:
    """(path, None, target, text, span) for each new stand-in a setup file installs.

    `manifest` reads the base side's root package.json; `read_tsconfig` the
    base side's root tsconfig.json, as module_mock_events reads it. Each is
    called at most once, and only when a change could need it.
    """
    changed = [change for change in changes if change.path.replace("\\", "/") == "package.json"]
    if not changed and not any((change.old_path or change.path).endswith(_EXTENSIONS)
                               or change.path.endswith(_EXTENSIONS) for change in changes):
        return []
    base_manifest = manifest() if callable(manifest) else manifest
    listed = listed_setup_files(base_manifest)
    aliases = Aliases(read_tsconfig)
    events: set[tuple[str, None, str, str, tuple[int, int]]] = set()
    base: list[_Side] = []
    heads: list[tuple[str, _Side]] = []
    for change in changes:
        old = (change.old_path or change.path).replace("\\", "/")
        path = change.path.replace("\\", "/")
        if change.before is not None and is_carrier(old, listed) and _TRIGGER.search(change.before):
            base.append(_Side(old, change.before, aliases))
        if change.after is not None and is_carrier(path, listed) and _TRIGGER.search(change.after):
            heads.append((path, _Side(path, change.after, aliases)))
    base_automock = any(_automock_calls(side) for side in base)
    for path, head in heads:
        for install in head.installs:
            if not _installed_before(install, base):
                events.add((path, None, _target(install), install.text, install.span))
        if not base_automock:
            for text, span in _automock_calls(head):
                events.add((path, None, "automock", text, span))
    for change in changed:
        if jest_config(change.after).get("automock") is True and jest_config(base_manifest).get("automock") is not True:
            events.add(("package.json", None, "automock", '"automock": true', (0, 0)))
    return sorted(events)

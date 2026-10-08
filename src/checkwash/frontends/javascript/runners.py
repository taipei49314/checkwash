"""Runner evidence: which JS test runner collects a file, when that is known.

One definition for every consumer that needs the runner (#196 186.7, 186.4,
187.4; #198 Q5). Evidence is either a proven set of runners or unknown
(None):

- A file's own imports name its runner: ``vitest``, ``@jest/globals``
  (Jest), ``node:test``, ``bun:test``, ``ava`` and ``tap``; a ``Deno.test``
  call names Deno.
  ``chai`` is an assertion library that runs under any of them, so it names
  no runner and leaves the others standing. A file that names several
  runners is proven to run under one of them.
- Otherwise the base side's root ``package.json``, when its dependencies name
  exactly one of ``jest``, ``vitest``, ``mocha``, ``jasmine``, ``ava`` and
  ``tap``. A mix, or none, is unknown. The base side, because the diff under
  review must not choose the runner it is judged by.

Each runner's row is its documented zero-configuration discovery, matched
case-sensitively, as the runners match it:

- Jest 30 ``testMatch``: beneath ``__tests__``, or ``?(*.)+(spec|test)``
  names (https://jestjs.io/docs/configuration#testmatch-arraystring).
- Vitest ``include``: ``**/*.{test,spec}.?(c|m)[jt]s?(x)``
  (https://vitest.dev/config/include).
- Node's test runner: ``test``, ``test-*``, ``*-test``, ``*_test`` and
  ``*.test`` names, and everything beneath a ``test`` directory
  (https://nodejs.org/api/test.html#running-tests-from-the-command-line).
- Mocha: ``./test/*.{js,cjs,mjs}``, not recursive (``spec`` defaults to
  ``test``, ``recursive`` to false; https://mochajs.org/#the-test-directory).
- Jasmine: ``jasmine init``'s ``spec_dir: "spec"`` with
  ``spec_files: ["**/*[sS]pec.?(m)js"]``
  (https://jasmine.github.io/setup/nodejs.html).
- Bun: ``*.test``, ``*_test``, ``*.spec`` and ``*_spec`` names
  (https://bun.com/docs/test/discovery).
- Deno: ``{*_,*.,}test.{ts,tsx,mts,js,mjs,jsx}`` names, and every script
  beneath ``__tests__`` (https://docs.deno.com/runtime/test/).
- AVA 8 (``lib/globs.js``, ``lib/extensions.js``): ``js`` and ``mjs`` files
  named ``test`` at the root or in ``src``/``source``, ``*.spec``, ``*.test``
  or ``test-*`` anywhere, or beneath ``__tests__``, ``test`` or ``tests``;
  not beneath a ``__helper(s)__``/``__fixture(s)__`` directory under
  ``__tests__`` or a ``helper(s)``/``fixture(s)`` one under ``test(s)``, and
  never a "helper": a name, or a directory, that starts with one ``_``.
- tap 21 (``@tapjs/config``'s ``include`` and ``exclude``, with the default
  TypeScript plugin's extensions): beneath ``test``, ``tests``, ``__test__``
  or ``__tests__``, or named ``*.test``, ``*.tests``, ``*.spec``, ``test`` or
  ``tests``; not beneath ``fixture*``, ``dist``, ``tap-snapshots`` or a
  dot directory.

Configured globs (``testMatch``, ``include``, ``spec``, ``bunfig.toml``) are
still not read, so a project that configures its own still gets the default
answer. Each consumer states what unknown evidence means to it.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
import json
import re

from checkwash.roles import is_artifact


_JS = frozenset({"js", "cjs", "mjs"})
_TS = frozenset({"ts", "cts", "mts"})
_JSX = frozenset({"jsx", "tsx"})
_ANY = _JS | _TS | _JSX

# Import specifiers that name the runner a file runs under.
_RUNNER_MODULES = {"vitest": "vitest", "@jest/globals": "jest", "node:test": "node", "bun:test": "bun",
                   "ava": "ava", "tap": "tap"}
# Runners a root manifest can name, by dependency name.
_MANIFEST_RUNNERS = ("jest", "vitest", "mocha", "jasmine", "ava", "tap")
# Runners that scope `.only` to the file it is written in (#196 187.4). AVA
# runs each file in a worker with a runner of its own (`lib/worker/base.js`),
# so its `.only` reaches that file's tests alone (#233).
_FILE_SCOPED_FOCUS = frozenset({"jest", "vitest", "ava"})
# Runners that run only the innermost focus: a focused block with a focused
# declaration inside it runs only that one (#196 187.2). Mocha is stricter
# still, which this leaves lenient.
_INNERMOST_FOCUS = frozenset({"vitest", "mocha", "jasmine", "node"})
# Runners whose rows exist only on evidence, for test obligations as for
# continuity (#196 186.4). Never union rows: as one, AVA's and tap's
# `tests/**` would make every JS helper under a Python project's `tests/` a
# test (#233).
EVIDENCE_ONLY = frozenset({"bun", "deno", "ava", "tap"})
# AVA's "helper" directories: one leading underscore (`_util`, not `__x`).
_AVA_HELPER_DIRECTORY = re.compile(r"_(?:[^_].*)?", re.DOTALL)
_AVA_EXCLUDED_UNDER_TESTS = re.compile(r"__(?:helper|fixture)s?__")
_AVA_EXCLUDED_UNDER_TEST = re.compile(r"(?:helper|fixture)s?")
_TAP_EXCLUDED = re.compile(r"fixtures*|dist|tap-snapshots|node_modules")

_IMPORT = re.compile(
    r"(?<![\w$.])import\s+(?!type\s)[^;'\"`]{0,2000}?\bfrom\s*(?P<q1>['\"])(?P<m1>[^'\"\n]{1,256})(?P=q1)"
    r"|(?<![\w$.])import\s*(?P<q2>['\"])(?P<m2>[^'\"\n]{1,256})(?P=q2)"
    r"|(?<![\w$.])(?:require|import)\s*\(\s*(?P<q3>['\"])(?P<m3>[^'\"\n]{1,256})(?P=q3)\s*\)"
)
_DENO_TEST = re.compile(r"(?<![\w$.])Deno\s*\.\s*test\s*(?:\.\s*(?:only|ignore)\s*)?\(")
_JEST_STEM = re.compile(r"(?:.*[.])?(?:spec|test)+", re.DOTALL)


def _node_stem(stem: str) -> bool:
    return stem == "test" or stem.startswith("test-") or stem.endswith(("-test", "_test", ".test"))


def _vitest_stem(stem: str) -> bool:
    head, dot, word = stem.rpartition(".")
    return bool(dot) and word in ("test", "spec") and bool(head) and not head.startswith(".")


def _bun_stem(stem: str) -> bool:
    return any(stem.endswith(suffix) and len(stem) > len(suffix)
               for suffix in (".test", "_test", ".spec", "_spec"))


def _deno_stem(stem: str) -> bool:
    return stem == "test" or (stem.endswith(("_test", ".test")) and len(stem) > 5)


def _split(path: str) -> tuple[list[str], str, str] | None:
    *directories, name = path.replace("\\", "/").split("/")
    stem, separator, extension = name.rpartition(".")
    if not separator or not stem:
        return None
    return directories, stem, extension


def collects(runner: str, path: str, *, fold: bool = False) -> bool:
    """Does `runner`'s default discovery collect `path`?

    Case-sensitive, as the runners match. `fold` is for test obligations,
    which stay case-insensitive (#196 186.3).
    """
    normalized = path.replace("\\", "/")
    if fold:
        normalized = normalized.lower()
    if is_artifact(normalized.lower()):
        return False
    parts = _split(normalized)
    if parts is None:
        return False
    directories, stem, extension = parts
    if runner == "jest":
        return extension in _ANY and ("__tests__" in directories or bool(_JEST_STEM.fullmatch(stem)))
    if runner == "vitest":
        return extension in _ANY and _vitest_stem(stem)
    if runner == "node":
        return extension in _JS | _TS and ("test" in directories or _node_stem(stem))
    if runner == "mocha":
        return extension in _JS and bool(directories) and directories[-1] == "test"
    if runner == "jasmine":
        return extension in {"js", "mjs"} and "spec" in directories and stem.endswith(("spec", "Spec"))
    if runner == "bun":
        return extension in _ANY and not any(d.startswith(".") for d in directories) and _bun_stem(stem)
    if runner == "deno":
        return extension in _ANY - {"cjs", "cts"} and ("__tests__" in directories or _deno_stem(stem))
    if runner == "ava":
        return extension in {"js", "mjs"} and _ava_collects(directories, stem)
    if runner == "tap":
        return extension in _ANY and _tap_collects(directories, stem)
    raise ValueError(f"unknown runner {runner!r}")


def _ava_collects(directories: list[str], stem: str) -> bool:
    if stem.startswith(("_", ".")) or any(
            _AVA_HELPER_DIRECTORY.fullmatch(d) or d.startswith(".") for d in directories):
        return False
    for marker, excluded in (("__tests__", _AVA_EXCLUDED_UNDER_TESTS),
                             ("test", _AVA_EXCLUDED_UNDER_TEST), ("tests", _AVA_EXCLUDED_UNDER_TEST)):
        if marker in directories and any(
                excluded.fullmatch(d) for d in directories[directories.index(marker) + 1:]):
            return False
    if stem == "test" and directories in ([], ["src"], ["source"]):
        return True
    head, dot, word = stem.rpartition(".")
    return (bool(dot and head and word in ("spec", "test")) or stem.startswith("test-")
            or any(d in ("__tests__", "test", "tests") for d in directories))


def _tap_collects(directories: list[str], stem: str) -> bool:
    if stem.startswith(".") or any(d.startswith(".") or _TAP_EXCLUDED.fullmatch(d) for d in directories):
        return False
    if any(d in ("test", "tests", "__test__", "__tests__") for d in directories):
        return True
    head, dot, word = stem.rpartition(".")
    return bool(dot and head and word in ("test", "tests", "spec")) or stem in ("test", "tests")


def union_collects(path: str) -> bool:
    """The role-blind union of the rows the obligations predicate reads,
    matched case-sensitively: what continuity falls back to without
    evidence (#196 186.3, 186.7)."""
    return collects("node", path) or collects("jest", path)


def file_runners(data: bytes | None) -> frozenset[str]:
    """The runners a file's own source names; empty when it names none."""
    return _file_runners(data) if data else frozenset()


@lru_cache(maxsize=16)
def _file_runners(data: bytes) -> frozenset[str]:
    from checkwash.frontends.javascript.frontend import _code_positions

    text = data.decode("utf-8-sig", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    # The specifier is a string, so the scan keeps strings; the keyword
    # must still be code, or `"import { a } from 'vitest'"` would count.
    strings = _code_positions(text, keep_strings=True)
    code = _code_positions(text)
    masked = "".join(c if strings[i] else " " for i, c in enumerate(text))
    found: set[str] = set()
    for match in _IMPORT.finditer(masked):
        module = match.group("m1") or match.group("m2") or match.group("m3")
        if code[match.start()] and module in _RUNNER_MODULES:
            found.add(_RUNNER_MODULES[module])
    if any(code[match.start()] for match in _DENO_TEST.finditer(masked)):
        found.add("deno")
    return frozenset(found)


def manifest_runners(data: bytes | None) -> frozenset[str] | None:
    """The one runner a root package.json names, else None (unknown)."""
    if not data or len(data) > 1_000_000:
        return None
    try:
        manifest = json.loads(data.decode("utf-8-sig", errors="replace"))
    except (ValueError, RecursionError):
        return None
    if not isinstance(manifest, dict):
        return None
    named: set[str] = set()
    for table in ("dependencies", "devDependencies"):
        entries = manifest.get(table)
        if isinstance(entries, dict):
            named.update(name for name in _MANIFEST_RUNNERS if name in entries)
    return frozenset(named) if len(named) == 1 else None


def runner_evidence(data: bytes | None,
                    manifest: bytes | None | Callable[[], bytes | None]) -> frozenset[str] | None:
    """The runners proven to run this file, or None when unknown.

    `manifest` is the base root package.json, or a reader of it, called only
    when the file names no runner itself.
    """
    found = file_runners(data)
    if found:
        return found
    return manifest_runners(manifest() if callable(manifest) else manifest)


def collected(path: str, evidence: frozenset[str] | None) -> bool:
    """Is `path` collected by a runner the evidence names, or, without
    evidence, by the union?"""
    if evidence is None:
        return union_collects(path)
    return any(collects(runner, path) for runner in sorted(evidence))


def collection_continues(old: str, new: str, evidence: frozenset[str] | None) -> bool:
    """Does a runner that collected `old` still collect `new` (#196 186.7)?

    Evidence answers only for a path its runner collects by default: when it
    does not collect `old` either, the project configures its own globs, and
    the move is judged by the union instead, the lenient direction.
    """
    if evidence is not None and collected(old, evidence):
        return collected(new, evidence)
    return union_collects(new)


def evidenced_test_path(path: str, data: bytes | None) -> bool:
    """Does a runner row that exists only on evidence (Bun, Deno, AVA, tap)
    make this side of `path` a test? Case-insensitive, as test obligations
    are."""
    # Every such row collects JS/TS extensions only, so any other file, a
    # Python test among them, is answered without reading the rows.
    if path.rpartition(".")[2].lower() not in _ANY:
        return False
    rows = [runner for runner in sorted(EVIDENCE_ONLY) if collects(runner, path, fold=True)]
    return bool(rows) and bool(file_runners(data).intersection(rows))


def focus_is_file_scoped(evidence: frozenset[str] | None) -> bool:
    """Is the runner proven to keep `.only` inside its own file (#196 187.4)?"""
    return bool(evidence) and evidence <= _FILE_SCOPED_FOCUS


def focus_is_innermost(evidence: frozenset[str] | None) -> bool:
    """Is the runner proven to run only the innermost focus (#196 187.2)?

    Jest, and a runner that is not known, keep Jest's rule, the most
    permissive of the runners measured.
    """
    return bool(evidence) and evidence <= _INNERMOST_FOCUS

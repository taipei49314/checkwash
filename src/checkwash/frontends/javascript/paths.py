"""Bounded JS/TS test paths: the test runners' zero-configuration discovery.

A path is a test path when a mainstream runner collects it with no
configuration at all. Each row of ``_DEFAULT_DISCOVERY`` is one documented
default:

- Node's test runner collects ``test``, ``test-*``, ``*-test``, ``*_test`` and
  ``*.test`` names and every file beneath a directory named ``test``; Mocha's
  default ``./test/*.{js,cjs,mjs}`` is a subset:
  https://nodejs.org/api/test.html#running-tests-from-the-command-line
- Jest's default ``testMatch`` collects every file beneath a directory named
  ``__tests__`` and ``?(*.)+(spec|test)`` names, JSX/TSX included; Vitest's
  default ``*.{test,spec}.*`` include is a subset:
  https://jestjs.io/docs/configuration#testmatch-arraystring

The rows form a union because the classifier does not know which runner a
project uses, so a move between two rows reads as benign. That is why Bun's
``*_spec`` names, and ``*_test`` beyond Node's extensions, are not a row: none
of the runners above collects them, and as a row they would make
``x.test.js`` -> ``x_spec.js`` a benign move in every Jest, Vitest, Mocha or
node:test project, where it drops the test. ``__tests__`` is a runner default,
not a configured glob: this classifier still does not read configured globs
(``testMatch``, ``include``, ``spec``) or execute a runner. Generated/dependency
paths keep the engine's existing artifact exclusions. A path whose role SPEC
section 2 resolves before ``test`` (guardrail, ci, snapshot, lockfile,
conftest) keeps that published role. The engine still parses and judges such a
path as a test beside that role's rules, and a rename between two of these
paths keeps the test whatever roles they hold (#197).
"""

from __future__ import annotations

import re

from checkwash.roles import is_artifact


_NODE_EXTENSIONS = frozenset({"js", "cjs", "mjs", "ts", "cts", "mts"})
# Jest's `?([mc])[jt]s?(x)`, as far as its default moduleFileExtensions reach.
_JEST_EXTENSIONS = _NODE_EXTENSIONS | {"jsx", "tsx"}
# Jest's `?(*.)+(spec|test)`: an optional dotted prefix, then only those words.
_JEST_STEM = re.compile(r"(?:.*[.])?(?:spec|test)+", re.DOTALL)


def _node_stem(stem: str) -> bool:
    return stem == "test" or stem.startswith("test-") or stem.endswith(("-test", "_test", ".test"))


# (extensions, directory whose every descendant is collected, name rule).
# This table is the one definition: the engine's role assignment, its JS
# parse gate and its rename expansion all read it through is_js_test_path.
_DEFAULT_DISCOVERY = (
    (_NODE_EXTENSIONS, "test", _node_stem),
    (_JEST_EXTENSIONS, "__tests__", _JEST_STEM.fullmatch),
)


def is_js_test_path(path: str) -> bool:
    """Classify repository paths consistently across host operating systems.

As with the former suffix-only classifier, matching is case-insensitive.
Directory matching is segment-based: ``contest``, ``test-support`` and
``__tests__x`` do not make arbitrary source files into tests, and neither do
directories that sit beside tests without matching a default (Jest's
``__mocks__``, a codemod's ``__testfixtures__``). ``tests`` alone is not a
default of the runners modelled here. Each row keeps its runner's own
extensions: Node does not collect ``test/example.jsx``; Jest collects
``__tests__/example.jsx``.
"""
    normalized = path.replace("\\", "/").lower()
    if is_artifact(normalized):
        return False
    *directories, name = normalized.split("/")
    stem, separator, extension = name.rpartition(".")
    if not separator:
        return False
    return any(
        extension in extensions
        and (directory in directories or bool(matches(stem)))
        for extensions, directory, matches in _DEFAULT_DISCOVERY
    )

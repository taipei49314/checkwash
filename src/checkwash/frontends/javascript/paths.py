"""Bounded JS/TS test paths, including Node's default test discovery.

Node documents ``*.test.*``, ``*-test.*``, ``*_test.*``, ``test-*.*``,
``test.*`` and JavaScript/TypeScript files beneath a directory named ``test``:
https://nodejs.org/api/test.html#running-tests-from-the-command-line

Retain the existing Jest/Vitest ``.spec.*`` and JSX/TSX suffix convention.
This classifier does not infer arbitrary configured globs or execute a runner.
Generated/dependency paths keep the engine's existing artifact exclusions.
"""

from __future__ import annotations

from checkwash.roles import is_artifact


_NODE_EXTENSIONS = frozenset({"js", "cjs", "mjs", "ts", "cts", "mts"})
_EXPLICIT_SUFFIXES = tuple(
    f".{kind}.{extension}"
    for kind in ("test", "spec")
    for extension in (*sorted(_NODE_EXTENSIONS), "jsx", "tsx")
)


def is_js_test_path(path: str) -> bool:
    """Classify repository paths consistently across host operating systems.

As with the former suffix-only classifier, matching is case-insensitive.
Directory matching is segment-based: ``contest`` and ``test-support`` do not
make arbitrary source files into tests. ``tests`` alone is not a Node default.
"""
    normalized = path.replace("\\", "/").lower()
    if is_artifact(normalized):
        return False
    parts = normalized.split("/")
    name = parts[-1]
    if name.endswith(_EXPLICIT_SUFFIXES):
        return True
    stem, separator, extension = name.rpartition(".")
    if not separator or extension not in _NODE_EXTENSIONS:
        return False
    return (
        "test" in parts[:-1]
        or stem == "test"
        or stem.startswith("test-")
        or stem.endswith(("_test", "-test"))
    )

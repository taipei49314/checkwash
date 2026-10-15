"""Opaque directories: submodules (#335) and working-tree directory symlinks (#414).

A git submodule's tree belongs to another repository. The strict snapshot
lists it as a directory with a trailing slash and never reads inside it. A
pass that needs a fact from inside one, an import that could resolve there or
a collection that could reach it, fails closed with an engine error naming
the submodule's path; every other pass proceeds over the rest of the tree.

The working-tree snapshot lists a directory symlink the same way and never
follows it (#414): its target can lie outside the repository or repeat a
tree listed elsewhere. Its entry is a `SymlinkedDirectory`, so the error
names it as a directory symlink rather than as a submodule.
"""

from __future__ import annotations

from checkwash.change import EngineError


class SymlinkedDirectory(str):
    """The path of a working-tree directory symlink, an opaque directory (#414)."""

    __slots__ = ()


def same_kind(original, path):
    """`path`, a respelling of the opaque entry `original`, keeps its kind (#414)."""
    if isinstance(original, SymlinkedDirectory) and isinstance(path, str):
        return SymlinkedDirectory(path)
    return path


def split_inventory(paths):
    """A path inventory's files and its opaque directories (#335).

    `GitSnapshot.list_paths` lists a submodule as its path with a trailing
    slash: a directory whose content belongs to another repository and is
    unknown here. `WorkingTreeSnapshot.list_paths` lists a directory symlink
    the same way (#414). A consumer that does not split it out reads it as an
    unsafe path and fails, as every inventory read failed on a submodule
    before #335.
    """
    files, opaque = [], []
    for path in paths:
        if isinstance(path, str) and path.endswith("/") and path.strip("/"):
            opaque.append(same_kind(path, path[:-1]))
        else:
            files.append(path)
    return files, tuple(sorted(opaque))


def opaque_owner(path, opaque):
    """The opaque directory a path lies inside, or None (#335)."""
    for directory in opaque:
        if path.startswith(directory + "/"):
            return directory
    return None


def opaque_error(directory, reason):
    """The engine error for a fact a pass needs from inside an opaque directory (#335, #414)."""
    if isinstance(directory, SymlinkedDirectory):
        shown = directory if directory.isprintable() else repr(str(directory))
        return EngineError(f"strict snapshot inventory cannot follow directory symlink {shown}: {reason}")
    return EngineError(f"strict snapshot cannot inspect the submodule {directory}: {reason}")

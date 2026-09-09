"""Qualified finite path scope comparisons."""
from __future__ import annotations
import posixpath
import re
from .model import QualityError, inside
from .resolver import attach, boolean, check_dynamic, declarations, integer, resolved_sources, strings
from .snapshot import source

def scope(snapshot, target, patterns, profile, result, side, stage):
    patterns = strings(patterns)
    for pattern in patterns:
        literal = pattern[:-3] if pattern.endswith("/**") else pattern
        if ("/" not in literal or literal.startswith("/") or any(c in literal for c in "*?[]{}!\\\0:")
                or any(p in {"", ".", ".."} for p in literal.split("/"))):
            raise QualityError("UNSUPPORTED_PATTERN", "Only qualified literal paths and directory/** patterns are supported")
    if any(snapshot.modes[p] not in {"100644", "100755"} and any(inside(p, s.rstrip("/")) for s in target.paths) for p in snapshot.paths):
        raise QualityError("EXTERNAL_SOURCE", "Target scope contains a symlink or submodule")
    paths = [p for p in snapshot.paths if p in snapshot.tracked and p.endswith((".py", ".pyi"))
             and snapshot.modes[p] in {"100644", "100755"}
             and any(p == s or (s.endswith("/") and p.startswith(s)) for s in target.paths)]
    if len(paths) * max(1, len(patterns)) > 1_000_000:
        raise QualityError("RESOURCE_LIMIT", "Pattern comparison budget exceeded")
    kept = []
    for path in paths:
        relative = posixpath.relpath(path, "." if target.root == "." else target.root)
        if not any((relative.startswith(pattern[:-2]) if pattern.endswith("/**") else relative == pattern)
                   for pattern in patterns):
            kept.append(path)
    return sorted(kept)



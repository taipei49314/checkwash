"""Inventory adapter around the existing strict Git and worktree readers."""
from __future__ import annotations

import os
import stat
from pathlib import Path

from checkwash.change import EngineError
from checkwash.gitio.snapshot import GitSnapshot, WorkingTreeSnapshot, _run
from .model import MAX_BYTES, MAX_PATHS, MAX_TOTAL, QualityError, content_digest, safe_path


class Snapshot:
    def __init__(self, repo, revision=None):
        self.repo = str(Path(repo).resolve())
        self.reader = GitSnapshot(repo, revision) if revision else WorkingTreeSnapshot(repo)
        self.revision = self.reader._rev() if revision else None
        self.cache = {}
        self.bytes_read = 0
        self.paths, self.modes = self.inventory()
        raw = _run(self.repo, ["ls-files", "-z"])
        self.tracked = set(raw.decode("utf-8").rstrip("\0").split("\0")) - {""}
        if self.revision:
            self.tracked = set(self.paths)

    def inventory(self):
        modes = {}
        if self.revision:
            raw = _run(self.repo, ["ls-tree", "-r", "-z", self.revision])
            for record in raw.split(b"\0"):
                if not record:
                    continue
                meta, sep, path = record.partition(b"\t")
                fields = meta.split()
                if not sep or len(fields) != 3:
                    raise QualityError("SOURCE_INVALID", "Invalid Git inventory", kind="error")
                modes[path.decode("utf-8")] = fields[0].decode("ascii")
        else:
            def failed(exc):
                raise QualityError("SOURCE_READ_FAILED", "Worktree inventory failed", kind="error") from exc
            for directory, dirs, files in os.walk(self.repo, followlinks=False, onerror=failed):
                dirs[:] = sorted(d for d in dirs if d != ".git")
                for name in list(dirs):
                    path = Path(directory, name)
                    if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
                        modes[path.relative_to(self.repo).as_posix()] = "120000"
                        dirs.remove(name)
                for name in sorted(files):
                    if name == ".git":
                        continue
                    path = Path(directory, name)
                    mode = path.lstat().st_mode
                    modes[path.relative_to(self.repo).as_posix()] = "100644" if stat.S_ISREG(mode) else "120000"
                if len(modes) > MAX_PATHS:
                    raise QualityError("RESOURCE_LIMIT", "Worktree path inventory exceeds limit")
        if len(modes) > MAX_PATHS:
            raise QualityError("RESOURCE_LIMIT", "Git path inventory exceeds limit")
        return sorted(modes), modes

    def read(self, path):
        safe_path(path)
        if path in self.cache:
            return self.cache[path]
        parts = path.split("/")
        if any(self.modes.get("/".join(parts[:i])) in {"120000", "160000"} for i in range(1, len(parts) + 1)):
            raise QualityError("EXTERNAL_SOURCE", "Cannot analyze symlink or submodule source")
        try:
            data = self.reader.read(path)
        except EngineError as exc:
            if "byte limit" in str(exc):
                raise QualityError("RESOURCE_LIMIT", "Source exceeds strict-reader byte limit") from exc
            raise QualityError("SOURCE_READ_FAILED", "Strict snapshot read failed", kind="error") from exc
        except OSError as exc:
            raise QualityError("SOURCE_READ_FAILED", "Source read failed", kind="error") from exc
        if data is None and path in self.modes:
            raise QualityError("SOURCE_READ_FAILED", "Inventoried source could not be read", kind="error")
        if data is not None:
            if len(data) > MAX_BYTES:
                raise QualityError("RESOURCE_LIMIT", "Source byte limit exceeded")
            self.bytes_read += len(data)
            if self.bytes_read > MAX_TOTAL:
                raise QualityError("RESOURCE_LIMIT", "Total source byte limit exceeded")
        self.cache[path] = data
        return data

    def verify(self):
        if self.revision:
            return
        if self.inventory() != (self.paths, self.modes):
            raise QualityError("SNAPSHOT_CHANGED", "Worktree inventory changed during analysis", kind="error")
        for path, before in self.cache.items():
            try:
                after = self.reader.read(path)
            except (OSError, EngineError) as exc:
                raise QualityError("SNAPSHOT_CHANGED", "Worktree changed during analysis", kind="error") from exc
            if before != after:
                raise QualityError("SNAPSHOT_CHANGED", "Worktree source changed during analysis", kind="error")


class MappingSnapshot:
    """Complete caller-owned byte snapshots used by deterministic fixtures."""
    def __init__(self, files):
        self.files = dict(files)
        self.paths = sorted(files)
        self.tracked = set(files)
        self.modes = {p: "100644" for p in files}
        self.revision = "fixture"

    def read(self, path):
        safe_path(path)
        return self.files.get(path)

    def verify(self):
        pass


def source(snapshot, side, path, role="selected"):
    data = snapshot.read(path)
    record = {"side": side, "path": path, "state": "absent" if data is None else "present",
              "role": role, "selection_reason": role}
    if data is not None:
        record["digest"] = content_digest(data)
    return record, data

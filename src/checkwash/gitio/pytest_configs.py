"""Paired pytest config evidence: frozen Git or read-once regular worktree records."""

from __future__ import annotations

import hashlib

from checkwash.change import EngineError, FileChange
from checkwash.gitio.snapshot import (MAX_BATCH_BYTES, MAX_INVENTORY_PATHS, MAX_SOURCE_BYTES,
                                     ConfigSource, GitSnapshot, WorkingTreeSnapshot)

CONFIG_NAMES = frozenset({"pytest.toml", ".pytest.toml", "pytest.ini", ".pytest.ini",
                          "pyproject.toml", "tox.ini", "setup.cfg"})


class WorktreePytestConfigs:
    """One analysis's read-once regular config evidence, not a link-following reader.

    The ordinary working-tree reader keeps all admission checks. Config bytes
    and modes are retained once read, and changed sources must agree with the
    captured diff. OIDs describe raw content in this repository's object format;
    revision='worktree' does not claim that object was committed or stored.
    """

    def __init__(self, source: WorkingTreeSnapshot, before: GitSnapshot, changes):
        self.source = source
        revision = before._rev()
        if len(revision) not in (40, 64):
            raise EngineError("worktree pytest config needs a frozen base object identity")
        self._algorithm = hashlib.sha1 if len(revision) == 40 else hashlib.sha256
        self._paths = None
        self._modes = {}
        self._records = {}
        self._bytes = 0
        changes = tuple(changes)
        self._changes = {change.path.replace("\\", "/"): change.after for change in changes}
        for change in changes:
            old_path = (change.old_path or change.path).replace("\\", "/")
            if old_path != change.path.replace("\\", "/"):
                self._changes.setdefault(old_path, None)

    def list_paths(self):
        if self._paths is None:
            self._paths = tuple(self.source.list_paths())
        return list(self._paths)

    def config_modes(self, paths):
        missing = sorted(set(paths) - self._modes.keys())
        if missing:
            self._modes.update(self.source.config_modes(missing))
        return {path: self._modes[path] for path in sorted(set(paths))}

    def read_config_many(self, paths):
        selected = sorted(set(paths))
        if len(selected) > MAX_INVENTORY_PATHS or any(path.rsplit("/", 1)[-1] not in CONFIG_NAMES for path in selected):
            raise EngineError("worktree pytest config received an unregistered request")
        self.list_paths()
        modes = self.config_modes(selected)
        missing = [path for path in selected if path not in self._records]
        for path in missing:
            if modes[path] not in {None, b"100644", b"100755"}:
                raise EngineError(f"worktree pytest config is not a regular source: path={path!r}; use a repository-owned regular source or a committed range")
        if missing:
            values = self.source.read_many(missing)
            if self.source.config_modes(missing) != {path: modes[path] for path in missing}:
                raise EngineError("worktree pytest config modes changed during analysis")
            for path in missing:
                data = values[path]
                if (data is None) != (modes[path] is None):
                    raise EngineError(f"worktree pytest config presence changed during analysis: path={path!r}")
                if (data is not None) != (path in self._paths):
                    raise EngineError(f"worktree pytest config differs from captured inventory: path={path!r}")
                if path in self._changes and data != self._changes[path]:
                    raise EngineError(f"worktree pytest config differs from captured diff: path={path!r}")
                if data is None:
                    self._records[path] = None
                    continue
                if not isinstance(data, bytes) or len(data) > MAX_SOURCE_BYTES:
                    raise EngineError(f"worktree pytest config exceeds the source byte limit: path={path!r}")
                self._bytes += len(data)
                if self._bytes > MAX_BATCH_BYTES:
                    raise EngineError("worktree pytest config exceeds the batch byte limit")
                oid = self._algorithm(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest().encode("ascii")
                self._records[path] = ConfigSource(path, "worktree", modes[path], oid, data,
                                                   path, modes[path], oid)
        return {path: self._records[path] for path in selected}


class PairedPytestConfigs:
    """One analysis's base/head config records and effective config deltas.

    Call prepare once before either consumer's relevance gate. Internal
    FileChange-shaped deltas go only to config-control comparisons, never
    into the engine's diff or its Python/provider byte maps.
    This cache bounds its own paired config reads, not all analysis reads.
    Each consumer retains its separate selection and ordinary read limits.
    """

    def __init__(self, before: GitSnapshot, after: GitSnapshot | WorktreePytestConfigs):
        self.snapshots = {"before": before, "after": after}
        self.paths = {}
        self.requests = {"before": set(), "after": set()}
        self.records = {"before": {}, "after": {}}
        self.changes = {}
        self._charged = {}
        self.bytes_read = 0
        self._prepared = False

    def _charge(self, side, path, size):
        key = (side, path)
        previous = self._charged.get(key, 0)
        self._charged[key] = max(previous, size)
        self.bytes_read += max(0, size - previous)
        if len(self._charged) > MAX_INVENTORY_PATHS:
            raise EngineError("pytest config evidence exceeds the source read limit")
        if self.bytes_read > MAX_BATCH_BYTES:
            raise EngineError("pytest config evidence exceeds the source byte limit")

    def read(self, side, paths):
        snapshot = self.snapshots[side]
        selected = set(paths)
        # Only existing recognized config names grant this capability.
        # Runner parsing alone does not establish the command's cwd.
        if not selected <= self.requests[side]:
            raise EngineError("pytest config evidence received an unregistered request")
        missing = sorted(selected - self.records[side].keys())
        if missing:
            values = snapshot.read_config_many(missing)
            for path, value in values.items():
                self._charge(side, path, 0 if value is None else len(value.data) + value.link_bytes)
            self.records[side].update(values)
        return {path: self.records[side][path] for path in sorted(selected)}

    def prepare(self):
        if self._prepared:
            raise EngineError("pytest config context cannot be reused across analyses")
        for side, snapshot in self.snapshots.items():
            self.paths[side] = set(snapshot.list_paths())
            self.requests[side] = {path for path in self.paths[side]
                                   if path.rsplit("/", 1)[-1] in CONFIG_NAMES}
        candidates = self.requests["before"] | self.requests["after"]
        # Keep both sides of each recognized path, including old-only ones.
        for side in self.requests:
            self.requests[side].update(candidates)
        modes = [snapshot.config_modes(candidates) if hasattr(snapshot, "config_modes") else
                 {path: snapshot._tree_entries.get(path, (None,))[0] for path in candidates}
                 for snapshot in self.snapshots.values()]
        aliases = {path for path in candidates if any(values[path] == b"120000" for values in modes)}
        before = self.read("before", aliases)
        after = self.read("after", aliases)
        for path in sorted(aliases):
            old = before[path].data if before[path] is not None else None
            new = after[path].data if after[path] is not None else None
            if old != new:
                status = "added" if old is None else "deleted" if new is None else "modified"
                self.changes[path] = FileChange(path, status, old, new,
                                                synthetic="pytest_config_evidence")
        self._prepared = True
        return self

    def sources(self, side, paths):
        return {path: None if record is None else record.data
                for path, record in self.read(side, paths).items()}

    def reported_change(self, path, changes):
        """Bind a logical alias event to a real changed regular target.

        No link blob receives its target's text/digest. Commit labels stay
        in run metadata; putting them in the reason would destabilize the
        existing content-bound CI fingerprint.
        """
        old = self.records["before"].get(path)
        new = self.records["after"].get(path)
        if not any(record is not None and record.mode == b"120000" for record in (old, new)):
            return None
        if old is None or new is None:
            raise EngineError(f"pytest config event lacks paired target evidence: path={path!r}")
        matches = [change for change in changes
                   if change.path == new.target_path
                   and (change.old_path or change.path) == old.target_path
                   and change.before == old.data and change.after == new.data]
        if len(matches) != 1:
            raise EngineError(f"pytest config event has no unique physical changed source: path={path!r}, before={old.target_path!r}, head={new.target_path!r}")
        context = (f"logical pytest config {path!r}; "
                   f"before target={old.target_path!r} blob={old.target_oid.decode('ascii')}; "
                   f"head target={new.target_path!r} blob={new.target_oid.decode('ascii')}")
        return matches[0], context

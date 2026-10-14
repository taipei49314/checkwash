"""Paired frozen-tree pytest config evidence; never a generic source reader."""

from __future__ import annotations

from checkwash.change import EngineError, FileChange
from checkwash.gitio.snapshot import MAX_BATCH_BYTES, MAX_INVENTORY_PATHS, GitSnapshot

CONFIG_NAMES = frozenset({"pytest.toml", ".pytest.toml", "pytest.ini", ".pytest.ini",
                          "pyproject.toml", "tox.ini", "setup.cfg"})


class PairedPytestConfigs:
    """One analysis's base/head config records and effective config deltas.

    Call prepare once before either consumer's relevance gate. Internal
    FileChange-shaped deltas go only to config-control comparisons, never
    into the engine's diff or its Python/provider byte maps.
    This cache bounds its own paired config reads, not all analysis reads.
    Each consumer retains its separate selection and ordinary read limits.
    """

    def __init__(self, before: GitSnapshot, after: GitSnapshot):
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
        aliases = {path for path in candidates
                   if any(snapshot._tree_entries.get(path, (None,))[0] == b"120000"
                          for snapshot in self.snapshots.values())}
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

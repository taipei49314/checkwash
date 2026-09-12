"""Strict, bounded snapshots for reverse oracle discovery.

Legacy readers deliberately treat several failures as missing data. That is
safe when withholding refactor credit, but not when searching for assertions
that disappeared. These adapters distinguish absence from an incomplete read.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

from checkwash.change import EngineError

MAX_SOURCE_BYTES = 1_000_000
MAX_SEARCH_HITS = 64
MAX_INVENTORY_PATHS = 200_000
MAX_BATCH_BYTES = 64_000_000
_SKIP = {".git", "__pycache__", "node_modules", "dist", "build", ".venv", "venv", ".tox", ".nox", ".eggs", "htmlcov"}


def search_source_mapping(snapshot, needles):
    """Search a caller-owned complete byte snapshot.

    The empty needle has the same inventory meaning as the filesystem
    adapters: nonempty Python files only, with no silent hit truncation.
    Ordinary searches retain the historical in-memory matching behavior.
    """
    if "" in needles:
        paths = [path for path, data in sorted(snapshot.items()) if path.endswith(".py") and data]
        if len(paths) >= MAX_SEARCH_HITS:
            raise EngineError("strict snapshot importer search exceeds the hit limit")
        return paths
    return [path for path, data in sorted(snapshot.items())
            if any(needle.encode("utf-8") in data for needle in needles)]


def _run(repo, args, *, data=None, no_matches=False):
    result = subprocess.run(["git", "-C", str(repo), *args], input=data, capture_output=True)
    if no_matches and result.returncode == 1:
        return b""
    if result.returncode != 0:
        raise EngineError("strict snapshot git read failed: " + result.stderr.decode("utf-8", errors="replace").strip())
    return result.stdout


class GitSnapshot:
    def __init__(self, repo, revision):
        self.repo = repo
        self.revision = revision
        self._resolved = None
        self._tree_entries = None

    def list_paths(self):
        """Complete revision inventory, including empty modules and controls.

        Text-search results cannot stand in for this: empty __init__.py files
        change import resolution, and pytest/runner settings are not Python.
        Selected nonregular files are rejected by read_many, never read as
        the bytes of a symlink target or silently omitted from this inventory.
        """
        if self._tree_entries is None:
            raw = _run(self.repo, ["ls-tree", "-r", "-l", "-z", self._rev()])
            entries = {}
            for record in raw.split(b"\0"):
                if not record:
                    continue
                metadata, separator, raw_path = record.partition(b"\t")
                fields = metadata.split()
                if not separator or len(fields) != 4:
                    raise EngineError("strict snapshot inventory returned an invalid tree record")
                mode, kind, oid, size = fields
                if kind == b"commit":
                    raise EngineError("strict snapshot inventory cannot inspect a submodule")
                if kind != b"blob" or not size.isdigit():
                    raise EngineError("strict snapshot inventory returned an invalid blob")
                try:
                    path = raw_path.decode("utf-8")
                except UnicodeError as exc:
                    raise EngineError("strict snapshot inventory has an undecodable path") from exc
                entries[path] = (mode, oid, int(size))
                if len(entries) > MAX_INVENTORY_PATHS:
                    raise EngineError("strict snapshot inventory exceeds the path limit")
            self._tree_entries = entries
        return sorted(self._tree_entries)

    def read_many(self, paths):
        """Read selected regular blobs in bounded batches from one frozen tree."""
        self.list_paths()
        selected = sorted(set(paths))
        if len(selected) > MAX_INVENTORY_PATHS:
            raise EngineError("strict snapshot batch exceeds the path limit")
        result = {}
        present = []
        size_total = 0
        for path in selected:
            entry = self._tree_entries.get(path)
            if entry is None:
                result[path] = None
                continue
            mode, oid, size = entry
            if mode not in {b"100644", b"100755"}:
                raise EngineError("strict snapshot batch cannot inspect nonregular source")
            if size > MAX_SOURCE_BYTES:
                raise EngineError("strict snapshot source exceeds the byte limit")
            size_total += size
            if size_total > MAX_BATCH_BYTES:
                raise EngineError("strict snapshot batch exceeds the byte limit")
            present.append((path, oid, size))
        for start in range(0, len(present), 256):
            batch = present[start:start + 256]
            raw = _run(self.repo, ["cat-file", "--batch"], data=b"".join(oid + b"\n" for _p, oid, _s in batch))
            cursor = 0
            for path, oid, size in batch:
                end = raw.find(b"\n", cursor)
                expected = oid + b" blob " + str(size).encode("ascii")
                if end < 0 or raw[cursor:end] != expected:
                    raise EngineError("strict snapshot batch returned an invalid blob header")
                cursor = end + 1
                if len(raw) < cursor + size + 1 or raw[cursor + size:cursor + size + 1] != b"\n":
                    raise EngineError("strict snapshot batch returned incomplete source")
                result[path] = raw[cursor:cursor + size]
                cursor += size + 1
            if cursor != len(raw):
                raise EngineError("strict snapshot batch returned trailing bytes")
        return result

    def _rev(self):
        if self._resolved is None:
            self._resolved = _run(
                self.repo, ["rev-parse", "--verify", f"{self.revision}^{{commit}}"],
            ).decode("ascii").strip()
        return self._resolved

    def read(self, path):
        if any(c in path for c in "\r\n\0"):
            raise EngineError("strict snapshot path cannot be represented in the batch protocol")
        spec = f"{self._rev()}:{path}".encode("utf-8")
        checked = _run(self.repo, ["cat-file", "--batch-check"], data=spec + b"\n")
        if checked == spec + b" missing\n":
            return None
        header = checked.rstrip(b"\n")
        parts = header.split()
        if len(parts) != 3 or parts[1] != b"blob" or not parts[2].isdigit():
            raise EngineError("strict snapshot returned an invalid blob header")
        size = int(parts[2])
        if size > MAX_SOURCE_BYTES:
            raise EngineError("strict snapshot source exceeds the byte limit")
        raw = _run(self.repo, ["cat-file", "--batch"], data=spec + b"\n")
        actual_header, separator, body = raw.partition(b"\n")
        if not separator or actual_header != header or len(body) != size + 1 or not body.endswith(b"\n"):
            raise EngineError("strict snapshot blob is incomplete or exceeds the source limit")
        return body[:-1]

    def search(self, needles):
        if not needles:
            return []
        if "" in needles:
            # grep skips symlink blobs; a complete startup inventory must not
            # turn those omitted sources into known absence. Tree metadata
            # also identifies empty files without parsing their contents.
            raw = _run(self.repo, ["ls-tree", "-r", "-l", "-z", self._rev()])
            paths = []
            for record in raw.split(b"\0"):
                if not record:
                    continue
                metadata, separator, path = record.partition(b"\t")
                fields = metadata.split()
                if not separator or len(fields) != 4:
                    raise EngineError("strict snapshot inventory returned an invalid tree record")
                mode, kind, _oid, size = fields
                if kind == b"commit":
                    raise EngineError("strict snapshot inventory cannot inspect a submodule")
                if not path.endswith(b".py"):
                    continue
                if mode not in {b"100644", b"100755"} or kind != b"blob" or not size.isdigit():
                    raise EngineError("strict snapshot inventory cannot inspect a nonregular Python source")
                if int(size):
                    paths.append(path.decode("utf-8"))
                    if len(paths) >= MAX_SEARCH_HITS:
                        raise EngineError("strict snapshot importer search exceeds the hit limit")
            return paths
        args = ["grep", "-l", "-F", "-z"]
        for needle in needles:
            args.extend(["-e", needle])
        args.extend([self._rev(), "--", "*.py"])
        raw = _run(self.repo, args, no_matches=True)
        paths = []
        for record in raw.split(b"\0"):
            if record:
                if b":" not in record:
                    raise EngineError("strict snapshot search returned an invalid path record")
                paths.append(record.split(b":", 1)[1].decode("utf-8"))
        if len(paths) >= MAX_SEARCH_HITS:
            raise EngineError("strict snapshot importer search exceeds the hit limit")
        return paths


class WorkingTreeSnapshot:
    def __init__(self, repo):
        self.root = Path(repo).resolve()

    def list_paths(self):
        """Inventory all repository files except Git's own metadata."""
        paths = []

        def fail(error):
            raise EngineError("strict snapshot inventory failed") from error

        for directory, dirs, files in os.walk(self.root, onerror=fail):
            dirs[:] = sorted(d for d in dirs if d != ".git")
            if any(Path(directory, d).is_symlink() for d in dirs):
                raise EngineError("strict snapshot inventory cannot follow directory symlinks")
            for filename in sorted(files):
                if filename == ".git":
                    continue
                paths.append(Path(directory, filename).relative_to(self.root).as_posix())
                if len(paths) > MAX_INVENTORY_PATHS:
                    raise EngineError("strict snapshot inventory exceeds the path limit")
        return sorted(paths)

    def read_many(self, paths):
        selected = sorted(set(paths))
        if len(selected) > MAX_INVENTORY_PATHS:
            raise EngineError("strict snapshot batch exceeds the path limit")
        result = {}
        size_total = 0
        for path in selected:
            lexical = self.root / path
            if lexical.is_symlink():
                raise EngineError("strict snapshot batch cannot inspect nonregular source")
            data = self.read(path)
            if data is not None:
                size_total += len(data)
                if size_total > MAX_BATCH_BYTES:
                    raise EngineError("strict snapshot batch exceeds the byte limit")
            result[path] = data
        return result

    def read(self, path):
        target = (self.root / path).resolve()
        if not target.is_relative_to(self.root):
            raise EngineError("strict snapshot path leaves the repository")
        try:
            with target.open("rb") as source:
                data = source.read(MAX_SOURCE_BYTES + 1)
        except FileNotFoundError:
            return None
        if len(data) > MAX_SOURCE_BYTES:
            raise EngineError("strict snapshot source exceeds the byte limit")
        return data

    def search(self, needles):
        if not needles:
            return []
        wanted = [n.encode("utf-8") for n in needles]
        paths = []

        def fail(error):
            raise EngineError("strict snapshot importer search failed") from error

        for directory, dirs, files in os.walk(self.root, onerror=fail):
            # An empty needle requests the entire nonempty Python inventory.
            # Importer searches may skip generated/hidden trees, but an
            # optional startup-context proof cannot silently omit them.
            dirs[:] = sorted(d for d in dirs if d != ".git" and (
                "" in needles or (d not in _SKIP and not d.startswith("."))
            ))
            if any(Path(directory, d).is_symlink() for d in dirs):
                raise EngineError("strict snapshot importer search cannot follow directory symlinks")
            for filename in sorted(files):
                if not filename.endswith(".py"):
                    continue
                if "" in needles and Path(directory, filename).is_symlink():
                    raise EngineError("strict snapshot inventory cannot inspect a nonregular Python source")
                path = Path(directory, filename).relative_to(self.root).as_posix()
                data = self.read(path)
                if data is None:
                    raise EngineError("strict snapshot source disappeared during importer search")
                if data and any(n in data for n in wanted):
                    paths.append(path)
                    if len(paths) >= MAX_SEARCH_HITS:
                        raise EngineError("strict snapshot importer search exceeds the hit limit")
        return paths

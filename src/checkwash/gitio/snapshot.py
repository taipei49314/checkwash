"""Strict, bounded snapshots distinguish absence from incomplete source reads."""

from __future__ import annotations

import os
import hashlib
import re
import stat
from pathlib import Path
import subprocess

from checkwash.change import EngineError
from checkwash.opaque import opaque_error, opaque_owner

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
    try:
        result = subprocess.run(["git", "-C", str(repo), *args], input=data, capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise EngineError("strict snapshot git read could not complete") from exc
    if no_matches and result.returncode == 1 and not result.stdout and not result.stderr:
        return b""
    if result.returncode != 0:
        raise EngineError("strict snapshot git read failed: " + result.stderr.decode("utf-8", errors="replace").strip())
    if no_matches and (not result.stdout or result.stderr):
        raise EngineError("strict snapshot search returned an inconsistent success response")
    return result.stdout


def _verify_blob(oid, data):
    algorithm = "sha1" if len(oid) == 40 else "sha256" if len(oid) == 64 else None
    if algorithm is None or not re.fullmatch(b"[0-9a-f]+", oid):
        raise EngineError("strict snapshot returned an invalid object identity")
    actual = hashlib.new(algorithm, b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest().encode("ascii")
    if actual != oid:
        raise EngineError("strict snapshot blob content does not match its object identity")


class GitSnapshot:
    def __init__(self, repo, revision):
        self.repo = repo
        self.revision = revision
        self._resolved = None
        self._tree_entries = None
        self._opaque = None
        self._owners = {}

    def list_paths(self):
        """Complete revision inventory, including empty modules and controls.

        Text-search results cannot stand in for this: empty __init__.py files
        change import resolution, and pytest/runner settings are not Python.
        Selected nonregular files are rejected by read_many, never read as
        the bytes of a symlink target or silently omitted from this inventory.
        A submodule is listed as its path with a trailing slash, a directory
        whose content is unknown (`split_inventory`, #335).
        """
        if self._tree_entries is None:
            raw = _run(self.repo, ["ls-tree", "-r", "-l", "-z", self._rev()])
            if len(raw) > 64_000_000 or (raw and not raw.endswith(b"\0")):
                raise EngineError("strict snapshot inventory returned incomplete records")
            entries = {}
            opaque = set()
            for record in raw[:-1].split(b"\0") if raw else []:
                metadata, separator, raw_path = record.partition(b"\t")
                fields = metadata.split()
                if not separator or len(fields) != 4:
                    raise EngineError("strict snapshot inventory returned an invalid tree record")
                mode, kind, oid, size = fields
                if not re.fullmatch(b"(?:[0-9a-f]{40}|[0-9a-f]{64})", oid):
                    raise EngineError("strict snapshot inventory returned an invalid object identity")
                try:
                    path = raw_path.decode("utf-8")
                except UnicodeError as exc:
                    raise EngineError("strict snapshot inventory has an undecodable path") from exc
                if not path or any(c in path for c in "\r\n\0"):
                    raise EngineError("strict snapshot inventory returned an unsafe path")
                if path in entries or path in opaque:
                    raise EngineError("strict snapshot inventory returned a duplicate path")
                if len(entries) + len(opaque) >= MAX_INVENTORY_PATHS:
                    raise EngineError("strict snapshot inventory exceeds the path limit")
                if kind == b"commit":
                    if mode != b"160000" or size != b"-":
                        raise EngineError("strict snapshot inventory returned an invalid gitlink")
                    opaque.add(path)
                    continue
                if kind != b"blob" or mode not in {b"100644", b"100755", b"120000"} or not size.isdigit():
                    raise EngineError("strict snapshot inventory returned an invalid blob")
                entries[path] = (mode, oid, int(size))
                if len(entries) + len(opaque) > MAX_INVENTORY_PATHS:
                    raise EngineError("strict snapshot inventory exceeds the path limit")
            self._tree_entries = entries
            self._opaque = tuple(sorted(opaque))
        return sorted([*self._tree_entries, *(directory + "/" for directory in self._opaque)])

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
            if any(c in path for c in "\r\n\0"):
                raise EngineError("strict snapshot path cannot be represented in the batch protocol")
            owner = opaque_owner(path, self._opaque)
            if owner is not None:
                raise opaque_error(owner, f"{path} lies inside it")
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
                _verify_blob(oid, result[path])
                cursor += size + 1
            if cursor != len(raw):
                raise EngineError("strict snapshot batch returned trailing bytes")
        return result

    def _owner(self, path):
        """The submodule a path lies inside, or None (#335).

        A path inside a submodule reads as missing, as an absent one does. The
        inventory, once listed, knows every submodule; until then each parent
        directory is asked once, with one tree listing of its ancestors.
        """
        if self._opaque is not None:
            return opaque_owner(path, self._opaque)
        parent = path.rpartition("/")[0]
        if not parent:
            return None
        if parent not in self._owners:
            parts = parent.split("/")
            ancestors = ["/".join(parts[:end]) for end in range(1, len(parts) + 1)]
            raw = _run(self.repo, ["ls-tree", "-d", "-z", self._rev(), "--", *ancestors])
            owner = None
            for record in raw.split(b"\0"):
                metadata, separator, name = record.partition(b"\t")
                fields = metadata.split()
                named = name.decode("utf-8", errors="replace")
                if separator and len(fields) == 3 and fields[1] == b"commit" and named in ancestors:
                    owner = named
                    break
            self._owners[parent] = owner
        return self._owners[parent]

    def _names_submodule(self, path):
        """Whether the path is a submodule entry itself (#335).

        git 2.43 answers such a path `<spec> missing`, and git 2.55 `<oid>
        submodule`, so the tree entry decides, not the wording of the answer:
        the parent tree is listed by its object path, which no pathspec
        globbing or case folding widens.
        """
        if self._opaque is not None:
            return path in self._opaque
        parent, _slash, name = path.rpartition("/")
        raw = _run(self.repo, ["ls-tree", "-z", f"{self._rev()}:{parent}" if parent else self._rev()])
        for record in raw.split(b"\0"):
            metadata, separator, entry = record.partition(b"\t")
            fields = metadata.split()
            if separator and len(fields) == 3 and fields[1] == b"commit" and entry == name.encode("utf-8"):
                return True
        return False

    def _rev(self):
        if self._resolved is None:
            raw = _run(self.repo, ["rev-parse", "--verify", "--end-of-options", f"{self.revision}^{{commit}}"])
            if not re.fullmatch(b"(?:[0-9a-f]{40}|[0-9a-f]{64})\n", raw):
                raise EngineError("strict snapshot returned an invalid resolved commit")
            self._resolved = raw.decode("ascii").strip()
        return self._resolved

    def read(self, path):
        if any(c in path for c in "\r\n\0"):
            raise EngineError("strict snapshot path cannot be represented in the batch protocol")
        spec = f"{self._rev()}:{path}".encode("utf-8")
        checked = _run(self.repo, ["cat-file", "--batch-check"], data=spec + b"\n")
        if not checked.endswith(b"\n") or checked.count(b"\n") != 1:
            raise EngineError("strict snapshot returned an incomplete batch-check frame")
        missing = checked == spec + b" missing\n"
        header = checked[:-1]
        parts = header.split()
        if missing or len(parts) != 3 or parts[1] != b"blob" or not parts[2].isdigit():
            owner = self._owner(path)
            if owner is not None:
                raise opaque_error(owner, f"{path} lies inside it")
            if missing or self._names_submodule(path):
                # A successful `missing` batch response is not proof of path
                # absence: its tree can still name a lost loose object.
                self.list_paths()
                if path in self._tree_entries:
                    raise EngineError("strict snapshot inventoried source returned missing")
                return None
            raise EngineError("strict snapshot returned an invalid blob header")
        size = int(parts[2])
        if size > MAX_SOURCE_BYTES:
            raise EngineError("strict snapshot source exceeds the byte limit")
        self.list_paths()
        entry = self._tree_entries.get(path)
        if entry is None or entry[0] not in {b"100644", b"100755"} or entry[1:] != (parts[0], size):
            raise EngineError("strict snapshot blob header does not match its regular tree entry")
        raw = _run(self.repo, ["cat-file", "--batch"], data=spec + b"\n")
        actual_header, separator, body = raw.partition(b"\n")
        if not separator or actual_header != header or len(body) != size + 1 or not body.endswith(b"\n"):
            raise EngineError("strict snapshot blob is incomplete or exceeds the source limit")
        _verify_blob(parts[0], body[:-1])
        return body[:-1]

    def search(self, needles):
        if not needles:
            return []
        if "" in needles:
            # grep skips symlink blobs; a complete startup inventory must not
            # turn those omitted sources into known absence. Tree metadata
            # also identifies empty files without parsing their contents.
            self.list_paths()
            if self._opaque:
                raise opaque_error(self._opaque[0], "the Python inventory needs its sources")
            paths = []
            for path, (mode, _oid, size) in sorted(self._tree_entries.items()):
                if not path.endswith(".py"):
                    continue
                if mode not in {b"100644", b"100755"}:
                    raise EngineError("strict snapshot inventory cannot inspect a nonregular Python source")
                if size:
                    paths.append(path)
                    if len(paths) >= MAX_SEARCH_HITS:
                        raise EngineError("strict snapshot importer search exceeds the hit limit")
            return paths
        args = ["grep", "-l", "-F", "-z"]
        for needle in needles:
            args.extend(["-e", needle])
        args.extend([self._rev(), "--", "*.py"])
        raw = _run(self.repo, args, no_matches=True)
        if len(raw) > 32_000_000 or (raw and not raw.endswith(b"\0")):
            raise EngineError("strict snapshot search returned incomplete or over-budget records")
        paths = []
        prefix = self._rev().encode("ascii") + b":"
        for record in raw[:-1].split(b"\0") if raw else []:
            if not record.startswith(prefix) or record == prefix:
                raise EngineError("strict snapshot search returned an invalid path record")
            try:
                path = record[len(prefix):].decode("utf-8", errors="strict")
            except UnicodeError as exc:
                raise EngineError("strict snapshot search returned an undecodable path") from exc
            if any(c in path for c in "\r\n\0"):
                raise EngineError("strict snapshot search returned an unsafe path")
            paths.append(path)
        if len(paths) != len(set(paths)):
            raise EngineError("strict snapshot search returned duplicate paths")
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
        lexical = self.root / path
        target = lexical.resolve()
        if not target.is_relative_to(self.root):
            raise EngineError("strict snapshot path leaves the repository")
        try:
            mode = lexical.lstat().st_mode
        except FileNotFoundError:
            return None
        if not stat.S_ISREG(mode):
            raise EngineError("strict snapshot cannot inspect nonregular source")
        try:
            with target.open("rb") as source:
                data = source.read(MAX_SOURCE_BYTES + 1)
        except FileNotFoundError as exc:
            raise EngineError("strict snapshot source disappeared after inventory") from exc
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

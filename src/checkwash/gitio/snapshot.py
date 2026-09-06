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
_SKIP = {".git", "__pycache__", "node_modules", "dist", "build", ".venv", "venv", ".tox", ".nox", ".eggs", "htmlcov"}


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

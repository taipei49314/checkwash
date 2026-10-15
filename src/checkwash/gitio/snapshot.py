"""Strict, bounded snapshots distinguish absence from incomplete source reads."""

from __future__ import annotations

import os
import hashlib
import re
import stat
from dataclasses import dataclass
from bisect import bisect_left
from pathlib import Path
import subprocess

from checkwash.change import EngineError, UnreadSide
from checkwash.opaque import SymlinkedDirectory, opaque_error, opaque_owner

MAX_SOURCE_BYTES = 1_000_000
MAX_SEARCH_HITS = 64
MAX_INVENTORY_PATHS = 200_000
MAX_BATCH_BYTES = 64_000_000
_SKIP = {".git", "__pycache__", "node_modules", "dist", "build", ".venv", "venv", ".tox", ".nox", ".eggs", "htmlcov"}


@dataclass(frozen=True)
class ConfigSource:
    """Internal provenance for an explicitly requested pytest config."""

    path: str
    revision: str
    mode: bytes
    oid: bytes
    data: bytes
    target_path: str
    target_mode: bytes
    target_oid: bytes
    link_bytes: int = 0


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


def _nonregular(message, path, mode):
    """A refusal that names the path and what it is (#346).

    The path is shown as is, unless it would not print on one line.
    """
    kind = {b"120000": "a symlink", b"040000": "a directory"}.get(mode, "not a regular file")
    shown = path if path.isprintable() else repr(path)
    return EngineError(f"{message} {shown} ({kind})")


def _over_limit(path):
    """The working-tree path-limit refusal, naming where the walk stopped (#414)."""
    shown = path if path.isprintable() else repr(path)
    return EngineError(f"strict snapshot inventory exceeds the path limit of {MAX_INVENTORY_PATHS} at {shown}")


def _batch_over_limit(path, side, total):
    """The batch byte-limit refusal, naming the path that crossed it (#415)."""
    shown = path if path.isprintable() else repr(path)
    return EngineError(f"strict snapshot batch exceeds the byte limit at {shown} "
                       f"({side}, {total} > {MAX_BATCH_BYTES} bytes)")


def _verify_blob(oid, data):
    algorithm = "sha1" if len(oid) == 40 else "sha256" if len(oid) == 64 else None
    if algorithm is None or not re.fullmatch(b"[0-9a-f]+", oid):
        raise EngineError("strict snapshot returned an invalid object identity")
    actual = hashlib.new(algorithm, b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest().encode("ascii")
    if actual != oid:
        raise EngineError("strict snapshot blob content does not match its object identity")


class GitSnapshot:
    def __init__(self, repo, revision, side=None):
        self.repo = repo
        self.revision = revision
        # The diff side this tree is ("base" or "head"), named in a size
        # refusal; a snapshot no caller labelled names its revision (#415).
        self.side = side
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

    def _side(self):
        return self.side or str(self.revision)

    def read_many(self, paths, *, unread_oversized=False):
        """Read selected regular blobs in bounded batches from one frozen tree.

        A blob over MAX_SOURCE_BYTES refuses, naming path, side, size and
        limit; with `unread_oversized` it comes back as an `UnreadSide`
        instead, and costs the batch nothing (#415).
        """
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
                raise _nonregular("strict snapshot batch cannot inspect nonregular source", path, mode)
            if size > MAX_SOURCE_BYTES:
                unread = UnreadSide(path, self._side(), size, MAX_SOURCE_BYTES)
                if not unread_oversized:
                    raise unread.refusal()
                result[path] = unread
                continue
            size_total += size
            if size_total > MAX_BATCH_BYTES:
                raise _batch_over_limit(path, self._side(), size_total)
            present.append((path, oid, size))
        result.update(self._read_objects(present))
        return result

    def _read_objects(self, present):
        """Exact-OID transport; public readers validate modes and budgets first."""
        result = {}
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

    def read_config_many(self, paths):
        """One same-tree link hop, only for explicit config-evidence callers.

        Generic read/read_many and WorkingTreeSnapshot never call this API.
        Each logical alias pays for its link plus effective returned bytes.
        """
        inventory = self.list_paths()

        def directory(path):
            if not path:
                return True
            prefix = path + "/"
            index = bisect_left(inventory, prefix)
            return index < len(inventory) and inventory[index].startswith(prefix)

        selected = sorted(set(paths))
        if len(selected) > MAX_INVENTORY_PATHS:
            raise EngineError("strict snapshot config batch exceeds the path limit")
        entries = {}
        links = []
        result = {}
        total = 0
        for path in selected:
            if (not path or path.startswith("/") or ":" in path or "\\" in path
                    or any(c in path for c in "\r\n\0")
                    or any(part in {"", ".", ".."} for part in path.split("/"))):
                raise EngineError(f"strict snapshot config has an unsafe path: path={path!r}, ref={self._rev()!r}")
            owner = opaque_owner(path, self._opaque)
            if owner is not None or path in self._opaque:
                raise EngineError(f"strict snapshot config reaches a submodule: path={path!r}, ref={self._rev()!r}")
            parts = path.split("/")
            if any("/".join(parts[:end]) in self._tree_entries for end in range(1, len(parts))):
                raise EngineError(f"strict snapshot config traverses a non-directory: path={path!r}, ref={self._rev()!r}")
            entry = self._tree_entries.get(path)
            if entry is None:
                # A directory is not an absent optional config.
                if directory(path):
                    raise EngineError(f"strict snapshot config is a directory: path={path!r}, ref={self._rev()!r}")
                result[path] = None
                continue
            mode, oid, size = entry
            if size > MAX_SOURCE_BYTES:
                raise EngineError(f"strict snapshot config source exceeds the byte limit: path={path!r}, ref={self._rev()!r}, bytes={size}, limit={MAX_SOURCE_BYTES}")
            entries[path] = entry
            total += size
            if total > MAX_BATCH_BYTES:
                raise EngineError(f"strict snapshot config batch exceeds the byte limit: path={path!r}, ref={self._rev()!r}, bytes={total}, limit={MAX_BATCH_BYTES}")
            if mode == b"120000":
                links.append((path, oid, size))
        link_data = self._config_objects(links)
        targets = {}
        for path, (mode, oid, size) in entries.items():
            target = path
            if mode == b"120000":
                try:
                    text = link_data[path].decode("utf-8", errors="strict")
                except UnicodeError as exc:
                    raise EngineError(f"strict snapshot config link is undecodable: path={path!r}, ref={self._rev()!r}") from exc
                if not text or text.startswith("/") or ":" in text or any(c in text for c in "\\\r\n\0"):
                    raise EngineError(f"strict snapshot config link has an unsafe target: path={path!r}, ref={self._rev()!r}, target={text!r}")
                parts = path.split("/")[:-1]
                for part in text.split("/"):
                    traversed = "/".join(parts)
                    if (traversed in self._tree_entries or traversed in self._opaque
                            or not directory(traversed)):
                        raise EngineError(f"strict snapshot config link traverses a non-directory: path={path!r}, ref={self._rev()!r}, target={text!r}")
                    if part in {"", "."}:
                        continue
                    if part == "..":
                        if not parts:
                            raise EngineError(f"strict snapshot config link leaves its tree: path={path!r}, ref={self._rev()!r}, target={text!r}")
                        parts.pop()
                    else:
                        parts.append(part)
                target = "/".join(parts)
                prefixes = ["/".join(parts[:end]) for end in range(1, len(parts))]
                if any(prefix in self._tree_entries or prefix in self._opaque for prefix in prefixes):
                    raise EngineError(f"strict snapshot config link traverses a non-directory: path={path!r}, ref={self._rev()!r}, target={target!r}")
                target_entry = self._tree_entries.get(target)
                if target_entry is None or target_entry[0] not in {b"100644", b"100755"}:
                    raise EngineError(f"strict snapshot config target is not one regular blob: path={path!r}, ref={self._rev()!r}, target={target!r}")
                if target_entry[2] > MAX_SOURCE_BYTES:
                    raise EngineError(f"strict snapshot config target exceeds the byte limit: path={path!r}, ref={self._rev()!r}, target={target!r}, bytes={target_entry[2]}, limit={MAX_SOURCE_BYTES}")
                total += target_entry[2]
                if total > MAX_BATCH_BYTES:
                    raise EngineError(f"strict snapshot config batch exceeds the byte limit: path={path!r}, ref={self._rev()!r}, bytes={total}, limit={MAX_BATCH_BYTES}")
            else:
                target_entry = (mode, oid, size)
            targets[path] = (target, target_entry)
        requested = [(path, entry[1], entry[2]) for path, (_target, entry) in targets.items()]
        data = self._config_objects(requested)
        for path, (target, target_entry) in targets.items():
            mode, oid, size = entries[path]
            result[path] = ConfigSource(path, self._rev(), mode, oid, data[path],
                                        target, target_entry[0], target_entry[1],
                                        size if mode == b"120000" else 0)
        return result

    def _config_objects(self, present):
        # A failed transport may not identify one object. Record the exact
        # bounded request batch, without claiming which member caused it.
        result = {}
        for start in range(0, len(present), 256):
            batch = present[start:start + 256]
            try:
                result.update(self._read_objects(batch))
            except EngineError as exc:
                paths = tuple(path for path, _oid, _size in batch)
                raise EngineError(f"strict snapshot config object read failed: paths={paths!r}, ref={self._rev()!r}, detail={str(exc)!r}") from exc
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

    def read(self, path, *, unread_oversized=False):
        """One blob, None when absent; over the limit as `read_many` (#415)."""
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
        unread = None
        if size > MAX_SOURCE_BYTES:
            unread = UnreadSide(path, self._side(), size, MAX_SOURCE_BYTES)
            if not unread_oversized:
                raise unread.refusal()
        self.list_paths()
        entry = self._tree_entries.get(path)
        if entry is None or entry[0] not in {b"100644", b"100755"} or entry[1:] != (parts[0], size):
            raise EngineError("strict snapshot blob header does not match its regular tree entry")
        if unread is not None:
            return unread
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
                    raise _nonregular("strict snapshot inventory cannot inspect a nonregular Python source", path, mode)
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
    def __init__(self, repo, side="worktree"):
        self.root = Path(repo).resolve()
        self.side = side  # named in a size refusal (#415)

    def list_paths(self):
        """Inventory all repository files except Git's own metadata.

        Ignored and hidden trees are listed like any other: in hook mode the
        whole working tree is attacker-controlled. A directory symlink is
        listed as its path with a trailing slash, an opaque directory as a
        submodule is (`split_inventory`), and is never followed. A pass that
        needs a fact from inside it, an import that could resolve there or a
        collection that could reach it, fails closed naming it (#414).
        """
        paths = []

        def fail(error):
            raise EngineError("strict snapshot inventory failed") from error

        for directory, dirs, files in os.walk(self.root, onerror=fail):
            kept = []
            for name in sorted(d for d in dirs if d != ".git"):
                if not Path(directory, name).is_symlink():
                    kept.append(name)
                    continue
                link = Path(directory, name).relative_to(self.root).as_posix()
                paths.append(SymlinkedDirectory(link + "/"))
                if len(paths) > MAX_INVENTORY_PATHS:
                    raise _over_limit(link)
            dirs[:] = kept
            for filename in sorted(files):
                if filename == ".git":
                    continue
                paths.append(Path(directory, filename).relative_to(self.root).as_posix())
                if len(paths) > MAX_INVENTORY_PATHS:
                    raise _over_limit(paths[-1])
        return sorted(paths)

    def read_many(self, paths):
        selected = sorted(set(paths))
        if len(selected) > MAX_INVENTORY_PATHS:
            raise EngineError("strict snapshot batch exceeds the path limit")
        result = {}
        size_total = 0
        for path in selected:
            owner = self._symlinked_ancestor(path)
            if owner is not None:
                raise opaque_error(owner, f"{path} lies inside it")
            lexical = self.root / path
            if lexical.is_symlink():
                raise _nonregular("strict snapshot batch cannot inspect nonregular source", path, b"120000")
            data = self.read(path)
            if data is not None:
                size_total += len(data)
                if size_total > MAX_BATCH_BYTES:
                    raise _batch_over_limit(path, self.side, size_total)
            result[path] = data
        return result

    def _symlinked_ancestor(self, path):
        """The directory symlink a path lies inside, or None (#414).

        The inventory lists such a link as an opaque directory; a read must
        not follow it either, as a read inside a submodule fails closed.
        """
        parts = path.replace("\\", "/").split("/")[:-1]
        current = self.root
        for end, part in enumerate(parts, 1):
            if part in {"", ".", ".."}:
                return None
            current = current / part
            if current.is_symlink():
                return SymlinkedDirectory("/".join(parts[:end]))
        return None

    def read(self, path, *, unread_oversized=False):
        """One file, None when absent; over the limit as `GitSnapshot.read` (#415)."""
        owner = self._symlinked_ancestor(path)
        if owner is not None:
            raise opaque_error(owner, f"{path} lies inside it")
        lexical = self.root / path
        target = lexical.resolve()
        if not target.is_relative_to(self.root):
            raise EngineError("strict snapshot path leaves the repository")
        try:
            mode = lexical.lstat().st_mode
        except FileNotFoundError:
            return None
        if not stat.S_ISREG(mode):
            kind = b"120000" if stat.S_ISLNK(mode) else b"040000" if stat.S_ISDIR(mode) else None
            raise _nonregular("strict snapshot cannot inspect nonregular source", path, kind)
        try:
            with target.open("rb") as source:
                data = source.read(MAX_SOURCE_BYTES + 1)
                if len(data) > MAX_SOURCE_BYTES:
                    size = max(os.fstat(source.fileno()).st_size, len(data))
        except FileNotFoundError as exc:
            raise EngineError("strict snapshot source disappeared after inventory") from exc
        if len(data) > MAX_SOURCE_BYTES:
            unread = UnreadSide(path, self.side, size, MAX_SOURCE_BYTES)
            if not unread_oversized:
                raise unread.refusal()
            return unread
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
            for name in dirs:
                if Path(directory, name).is_symlink():
                    link = SymlinkedDirectory(Path(directory, name).relative_to(self.root).as_posix())
                    raise opaque_error(link, "the Python inventory needs its sources" if "" in needles
                                       else "the importer search needs its sources")
            for filename in sorted(files):
                if not filename.endswith(".py"):
                    continue
                path = Path(directory, filename).relative_to(self.root).as_posix()
                if "" in needles and Path(directory, filename).is_symlink():
                    raise _nonregular("strict snapshot inventory cannot inspect a nonregular Python source", path, b"120000")
                data = self.read(path)
                if data is None:
                    raise EngineError("strict snapshot source disappeared during importer search")
                if data and any(n in data for n in wanted):
                    paths.append(path)
                    if len(paths) >= MAX_SEARCH_HITS:
                        raise EngineError("strict snapshot importer search exceeds the hit limit")
        return paths

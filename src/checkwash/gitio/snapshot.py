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
import threading
import unicodedata

from checkwash.change import SHEBANG_PREFIX_BYTES, EngineError, SearchHitLimit, UnreadSide
from checkwash.opaque import SymlinkedDirectory, opaque_error, opaque_owner

MAX_SOURCE_BYTES = 1_000_000
MAX_SEARCH_HITS = 64
MAX_INVENTORY_PATHS = 200_000
MAX_BATCH_BYTES = 64_000_000
# The ceiling on one Git side streamed for its prefix (#455): a blob over
# MAX_SOURCE_BYTES and at most this size is streamed and verified; a larger
# one keeps no prefix, so it is answered as it was before the prefix existed.
MAX_PREFIX_STREAM_BYTES = MAX_BATCH_BYTES
# A link's text is a path. One longer than this is not read, and the link
# keeps its refusal (#551).
MAX_LINK_TEXT_BYTES = 4096
# A streamed blob passes through memory in pieces of at most this size.
_STREAM_CHUNK = 65_536
# Each streamed object gets the time `_run` gives one process.
_STREAM_TIMEOUT_S = 60
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


@dataclass(frozen=True)
class TreeAlias:
    """A tree entry that a path the tree lacks can stand for on disk (#500).

    `kind` is "a symlink", "a file" or "a submodule". `whole` is true when
    the entry is the path itself in another case, false when it lies at a
    proper prefix of the path.
    """

    entry: str
    kind: str
    whole: bool


def search_source_mapping(snapshot, needles):
    """Search a caller-owned complete byte snapshot.

    The empty needle has the same inventory meaning as the filesystem
    adapters: nonempty Python files only, with no silent hit truncation.
    Ordinary searches retain the historical in-memory matching behavior.
    """
    if "" in needles:
        paths = [path for path, data in sorted(snapshot.items()) if path.endswith(".py") and data]
        if len(paths) >= MAX_SEARCH_HITS:
            raise SearchHitLimit("strict snapshot importer search exceeds the hit limit")
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


def _nonregular(message, path, mode, *, side=None, entry=None):
    """A refusal that names the path and what it is (#346).

    Legacy callers keep their original text. Worktree read/batch callers
    opt into side, entrypoint and safe recovery context.
    """
    kind = {b"120000": "a symlink", b"040000": "a directory"}.get(mode, "not a regular file")
    if entry is not None:
        logical = "<non-repository-relative path>" if Path(path).anchor else path
        return EngineError(
            f"{message} {logical!r} ({kind}); side={side!r}, entry={entry!r}. "
            "Use a repository-owned regular source at this path; "
            "a committed range reads committed bytes only."
        )
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


def _blob_digest(oid, size):
    """The object hash for `oid`, fed the blob header for `size` bytes.

    Fed the blob's bytes, whole or in pieces, its hex digest is `oid` exactly
    when they are the blob's content (#455 streams them in pieces).
    """
    algorithm = "sha1" if len(oid) == 40 else "sha256" if len(oid) == 64 else None
    if algorithm is None or not re.fullmatch(b"[0-9a-f]+", oid):
        raise EngineError("strict snapshot returned an invalid object identity")
    return hashlib.new(algorithm, b"blob " + str(size).encode("ascii") + b"\0")


def _verify_blob(oid, data):
    digest = _blob_digest(oid, len(data))
    digest.update(data)
    if digest.hexdigest().encode("ascii") != oid:
        raise EngineError("strict snapshot blob content does not match its object identity")


def _stream_record(stdout, oid, size):
    """The first SHEBANG_PREFIX_BYTES bytes of one `cat-file --batch` record (#455).

    The record must be what `_read_objects` requires: the header `<oid> blob
    <size>`, exactly `size` bytes and a newline. Past the prefix, the bytes
    are read in pieces of at most _STREAM_CHUNK, hashed and dropped, so no
    oversized blob is held whole, and the whole is checked against `oid` as
    `_verify_blob` checks a full read: a blob whose bytes do not hash to its
    object identity refuses with the same message.
    """
    digest = _blob_digest(oid, size)
    expected = oid + b" blob " + str(size).encode("ascii") + b"\n"
    if stdout.readline(len(expected)) != expected:
        raise EngineError("strict snapshot batch returned an invalid blob header")
    prefix = b""
    remaining = size
    while remaining:
        chunk = stdout.read(min(remaining, _STREAM_CHUNK))
        if not chunk:
            raise EngineError("strict snapshot batch returned incomplete source")
        if len(prefix) < SHEBANG_PREFIX_BYTES:
            prefix += chunk[:SHEBANG_PREFIX_BYTES - len(prefix)]
        digest.update(chunk)
        remaining -= len(chunk)
    if stdout.read(1) != b"\n":
        raise EngineError("strict snapshot batch returned incomplete source")
    if digest.hexdigest().encode("ascii") != oid:
        raise EngineError("strict snapshot blob content does not match its object identity")
    return prefix


def _kill(process):
    if process.poll() is None:
        try:
            process.kill()
        except OSError:
            pass


def _stream_prefixes(repo, objects):
    """{oid: prefix} for (oid, size) pairs, through one `cat-file --batch` (#455).

    The objects are asked one at a time, each record read whole before the
    next is asked, so neither pipe can fill while the other waits. Each
    object adds the time `_run` gives one process to the deadline. A process
    that fails, times out or answers out of protocol refuses, as `_run` and
    `_read_objects` do.
    """
    if not objects:
        return {}
    try:
        process = subprocess.Popen(["git", "-C", str(repo), "cat-file", "--batch"],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as exc:
        raise EngineError("strict snapshot git read could not complete") from exc
    expired = threading.Event()

    def expire():
        expired.set()
        _kill(process)

    timer = threading.Timer(_STREAM_TIMEOUT_S * (len(objects) + 1), expire)
    timer.daemon = True
    timer.start()
    prefixes = {}
    try:
        for oid, size in objects:
            process.stdin.write(oid + b"\n")
            process.stdin.flush()
            prefixes[oid] = _stream_record(process.stdout, oid, size)
        process.stdin.close()
        if process.stdout.read(1):
            raise EngineError("strict snapshot batch returned trailing bytes")
        error = process.stderr.read()
        if process.wait() != 0:
            raise EngineError("strict snapshot git read failed: " + error.decode("utf-8", errors="replace").strip())
    except (OSError, EngineError) as exc:
        if expired.is_set() or not isinstance(exc, EngineError):
            raise EngineError("strict snapshot git read could not complete") from exc
        raise
    finally:
        timer.cancel()
        _kill(process)
        process.wait()
        for stream in (process.stdin, process.stdout, process.stderr):
            try:
                stream.close()
            except OSError:
                pass
    return prefixes


class GitSnapshot:
    def __init__(self, repo, revision, side=None, *, resolved=None):
        self.repo = repo
        self.revision = revision
        # The diff side this tree is ("base" or "head"), named in a size
        # refusal; a snapshot no caller labelled names its revision (#415).
        self.side = side
        if resolved is not None and (not isinstance(resolved, str) or not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", resolved)):
            raise EngineError("strict snapshot returned an invalid resolved commit")
        self._resolved = resolved
        self._tree_entries = None
        self._trees = None
        self._opaque = None
        self._listed_paths = None
        self._owners = {}
        # The committed links of this tree, once it is listed, and every path
        # it was asked for that is one of them or lies beneath one (#551).
        self._links = frozenset()
        self._link_asks = []

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
            raw = _run(self.repo, ["ls-tree", "-r", "-t", "-l", "-z", self._rev()])
            if len(raw) > 64_000_000 or (raw and not raw.endswith(b"\0")):
                raise EngineError("strict snapshot inventory returned incomplete records")
            entries = {}
            trees = set()
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
                if path in entries or path in opaque or path in trees:
                    raise EngineError("strict snapshot inventory returned a duplicate path")
                if kind == b"tree":
                    if mode != b"040000" or size != b"-":
                        raise EngineError("strict snapshot inventory returned an invalid tree")
                    if len(trees) >= MAX_INVENTORY_PATHS:
                        raise EngineError("strict snapshot inventory exceeds the path limit")
                    trees.add(path)
                    continue
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
            self._trees = frozenset(trees)
            self._opaque = tuple(sorted(opaque))
            self._links = frozenset(path for path, entry in entries.items() if entry[0] == b"120000")
            self._listed_paths = tuple(sorted([*self._tree_entries, *(directory + "/" for directory in self._opaque)]))
        if self._listed_paths is None:
            self._listed_paths = tuple(sorted([*self._tree_entries, *(directory + "/" for directory in self._opaque)]))
        return list(self._listed_paths)

    def _side(self):
        return self.side or str(self.revision)

    def _asked_through_a_link(self, path):
        """Note a path this tree was asked for that is a committed link or lies beneath one (#551).

        Such a path has no bytes here: a read of the link is refused, and a
        path beneath it comes back absent. A caller may take either for a
        file that is not there, and a few do. That is how a link the
        runtime-provider pass reads through its view could hide something
        from another pass, so the view counts these asks, and a run that
        read links keeps its verdict only when there are none
        (`LinkedTreeView.settle`). Nothing else reads the note. The tree is
        listed before this is called.
        """
        if not self._links:
            return
        parts = path.split("/")
        for end in range(1, len(parts) + 1):
            if "/".join(parts[:end]) in self._links:
                self._link_asks.append(path)
                return

    def has_python_module(self, name: str) -> bool:
        """Match a dotted import against the root and src layouts in this Git tree."""
        parts = name.split(".")
        if not all(part.isidentifier() for part in parts):
            return False
        if self._tree_entries is None:
            self.list_paths()
        locations = ["", "src/"]
        for index, part in enumerate(parts):
            namespaces = []
            for prefix in locations:
                path = prefix + part
                package = self._tree_entries.get(path + "/__init__.py")
                if package is not None:
                    if package[0] not in {b"100644", b"100755"}:
                        return False
                    # A regular package owns its children's search path.
                    locations = [path + "/"]
                    break
                module = self._tree_entries.get(path + ".py")
                if module is not None:
                    return index == len(parts) - 1 and module[0] in {b"100644", b"100755"}
                if path in self._trees:
                    namespaces.append(path + "/")
                elif path in self._opaque or self._tree_entries.get(path, (None,))[0] == b"120000":
                    # A symlink or submodule cannot prove a Python package.
                    return False
            else:
                locations = namespaces
            if not locations:
                return False
        return True

    def config_modes(self, paths):
        """Bounded metadata for explicitly requested pytest config evidence."""
        self.list_paths()
        selected = sorted(set(paths))
        if len(selected) > MAX_INVENTORY_PATHS:
            raise EngineError("strict snapshot config metadata exceeds the path limit")
        for path in selected:
            if path not in self._tree_entries:
                self._asked_through_a_link(path)
        return {path: self._tree_entries.get(path, (None,))[0] for path in selected}

    def read_many(self, paths, *, unread_oversized=False, stream_prefix=True):
        """Read selected regular blobs in bounded batches from one frozen tree.

        A blob over MAX_SOURCE_BYTES refuses, naming path, side, size and
        limit; with `unread_oversized` it comes back as an `UnreadSide`
        instead, and costs the batch nothing (#415). Unless `stream_prefix`
        is false, such a side up to MAX_PREFIX_STREAM_BYTES keeps its
        verified prefix, all of them streamed through one more `cat-file
        --batch` for this tree (#455).
        """
        self.list_paths()
        selected = sorted(set(paths))
        if len(selected) > MAX_INVENTORY_PATHS:
            raise EngineError("strict snapshot batch exceeds the path limit")
        result = {}
        present = []
        streamed = []
        size_total = 0
        for path in selected:
            if any(c in path for c in "\r\n\0"):
                raise EngineError("strict snapshot path cannot be represented in the batch protocol")
            owner = opaque_owner(path, self._opaque)
            if owner is not None:
                raise opaque_error(owner, f"{path} lies inside it")
            entry = self._tree_entries.get(path)
            if entry is None:
                self._asked_through_a_link(path)
                result[path] = None
                continue
            mode, oid, size = entry
            if mode not in {b"100644", b"100755"}:
                refusal = _nonregular("strict snapshot batch cannot inspect nonregular source", path, mode)
                if mode == b"120000":
                    # Named for the runtime-provider pass, which may read a
                    # committed range's unchanged links through a view (#551).
                    refusal.refused_link = path
                    self._link_asks.append(path)
                raise refusal
            if size > MAX_SOURCE_BYTES:
                unread = UnreadSide(path, self._side(), size, MAX_SOURCE_BYTES)
                if not unread_oversized:
                    raise unread.refusal()
                result[path] = unread
                if stream_prefix and size <= MAX_PREFIX_STREAM_BYTES:
                    streamed.append((path, oid, size))
                continue
            size_total += size
            if size_total > MAX_BATCH_BYTES:
                raise _batch_over_limit(path, self._side(), size_total)
            present.append((path, oid, size))
        result.update(self._read_objects(present))
        # Two paths that hold one blob stream it once.
        prefixes = _stream_prefixes(self.repo, sorted({(oid, size) for _path, oid, size in streamed}))
        for path, oid, size in streamed:
            result[path] = UnreadSide(path, self._side(), size, MAX_SOURCE_BYTES, prefix=prefixes[oid])
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
        inventory = self._listed_paths if self._listed_paths is not None else self.list_paths()

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
                self._asked_through_a_link(path)
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

    def read(self, path, *, unread_oversized=False, stream_prefix=True):
        """One blob, None when absent; over the limit as `read_many` (#415).

        The prefix of a side over the limit is streamed through one more
        `cat-file --batch`, the one a blob under the limit costs (#455).
        """
        if any(c in path for c in "\r\n\0"):
            raise EngineError("strict snapshot path cannot be represented in the batch protocol")
        if self._tree_entries is not None and self.definitely_lacks(path):
            return None
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
                self._asked_through_a_link(path)
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
            self._asked_through_a_link(path)
            raise EngineError("strict snapshot blob header does not match its regular tree entry")
        if unread is not None:
            if stream_prefix and size <= MAX_PREFIX_STREAM_BYTES:
                prefix = _stream_prefixes(self.repo, [(parts[0], size)])[parts[0]]
                return UnreadSide(path, self._side(), size, MAX_SOURCE_BYTES, prefix=prefix)
            return unread
        raw = _run(self.repo, ["cat-file", "--batch"], data=spec + b"\n")
        actual_header, separator, body = raw.partition(b"\n")
        if not separator or actual_header != header or len(body) != size + 1 or not body.endswith(b"\n"):
            raise EngineError("strict snapshot blob is incomplete or exceeds the source limit")
        _verify_blob(parts[0], body[:-1])
        return body[:-1]

    def definitely_lacks(self, path):
        """True when the cached tree inventory proves `read(path)` is None."""
        if not path or any(c in path for c in "\\\r\n\0"):
            return False
        if path.startswith("/") or path.endswith("/") or any(part in {"", ".", ".."} for part in path.split("/")):
            return False
        inventory = self._listed_paths if self._listed_paths is not None else self.list_paths()
        if path in self._tree_entries or path in self._opaque or (self._trees is not None and path in self._trees):
            return False
        if opaque_owner(path, self._opaque) is not None:
            return False
        prefix = path + "/"
        index = bisect_left(inventory, prefix)
        if index < len(inventory) and inventory[index].startswith(prefix):
            return False
        self._asked_through_a_link(path)
        return True

    def alias(self, path):
        """The entry a path this tree lacks can stand for on disk, or None (#500).

        Git looks `<rev>:<path>` up byte for byte and never through an entry
        that is not a directory. A working tree follows a symlink, opens a
        directory the head put where this tree holds a file, and on a
        case-insensitive checkout matches any case. So the answer is the
        first entry, by the shortest prefix, that equals a proper prefix of
        `path` when case is ignored and is a file, symlink or submodule; or
        else an entry that equals `path` itself only when case is ignored.
        An entry equal to `path` byte for byte is what `read` answers, so it
        is no alias. `read` answers a submodule named exactly as absent, so
        the caller's fallback then opens whatever the working tree holds
        there. Every comparison is on text, with `str.casefold`, so the
        answer is the same on every file system; casefold is no file
        system's own case table, so it can join names one keeps apart and
        miss names one joins (D-158 readings 2 and 3).
        """
        self.list_paths()
        folded = {}
        entries = [(name, "a symlink" if mode == b"120000" else "a file")
                   for name, (mode, _oid, _size) in self._tree_entries.items()]
        entries += [(name, "a submodule") for name in self._opaque]
        for name, kind in sorted(entries):
            folded.setdefault(name.casefold(), []).append((name, kind))
        parts = path.split("/")
        for end in range(1, len(parts) + 1):
            whole = end == len(parts)
            for name, kind in folded.get("/".join(parts[:end]).casefold(), ()):
                if not whole or name != path:
                    return TreeAlias(name, kind, whole)
        return None

    def search(self, needles, exclude=frozenset()):
        """Python paths holding a needle; the empty needle lists them all.

        `exclude` leaves its paths out of an ordinary search: they are neither
        returned nor counted toward the hit limit (D-206). The inventory, the
        empty needle, is never narrowed.
        """
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
                        raise SearchHitLimit("strict snapshot importer search exceeds the hit limit")
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
        paths = [path for path in paths if path not in exclude]
        if len(paths) >= MAX_SEARCH_HITS:
            raise SearchHitLimit("strict snapshot importer search exceeds the hit limit")
        return paths


def _folded(path):
    """A path as a file system that folds case and Unicode form compares it."""
    return unicodedata.normalize("NFC", path).casefold()


def _link_walk(path, data, entries, trees, submodules=(), folded=None):
    """Where a committed link's text leads in its own tree (#551): a kind and a target.

    `data` is the link's text and `path` its own path. The text is resolved
    against the link's directory, inside the tree, as D-133 resolves a
    symlinked pytest config.
    - `("file", target)`: a regular file of the tree.
    - `("directory", target)`: a directory of the tree, the root included.
    - `("unknown", None)`: the text is missing, undecodable, empty or holds a
      colon, a backslash, a carriage return, a line feed or a NUL; or it is
      absolute, or the walk leaves the tree, and may come back into a
      checkout of it by a path the tree does not show (`/proc/self/cwd/x`,
      `../<the checkout's own name>/x`); or the walk meets another link or a
      submodule; or it misses a name that the tree holds in another case or
      Unicode form (`folded`, the tree's paths as `_folded` gives them),
      where a checkout that folds them would follow the link.
    - `("nothing", None)`: any other text, which leads to nothing the tree
      holds: a name on the way or at its end is missing inside the tree, or
      the walk passes through a regular file. A build may create a missing
      name later, as it may a path a config names; neither is seen.
    """
    if data is None:
        return ("unknown", None)
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeError:
        return ("unknown", None)
    if not text or ":" in text or any(c in text for c in "\\\r\n\0") or text.startswith("/"):
        return ("unknown", None)

    def beyond(name):
        """What a name that is no directory of the tree is: a link or a submodule is not known."""
        entry = entries.get(name)
        if (entry is not None and entry[0] == b"120000") or name in submodules or opaque_owner(name, submodules):
            return ("unknown", None)
        if entry is None and folded is not None and _folded(name) in folded:
            return ("unknown", None)
        return ("nothing", None)

    parts = path.split("/")[:-1]
    for part in text.split("/"):
        if parts and "/".join(parts) not in trees:
            return beyond("/".join(parts))
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                return ("unknown", None)
            parts.pop()
        else:
            parts.append(part)
    target = "/".join(parts)
    if not target or target in trees:
        return ("directory", target)
    entry = entries.get(target)
    if entry is not None and entry[0] in (b"100644", b"100755"):
        return ("file", target)
    return beyond(target)


def _link_reading(path, data, entries, trees):
    """How a committed link reads (#551): `("file", target)`, `("directory", target)` or None.

    None is every link `_link_walk` finds to lead to nothing or cannot tell.
    """
    walk = _link_walk(path, data, entries, trees)
    return walk if walk[0] in ("file", "directory") else None


def refused_link(error):
    """The committed link whose refusal by `GitSnapshot.read_many` this error is, or None (#551)."""
    return getattr(error, "refused_link", None)


def link_view_of(snapshot, base=None):
    """The link view of a committed range (#551), or None for a source that has none.

    `snapshot` is the head and `base` the tree the range starts from. A view
    needs both as committed trees, because it reads a link only where the
    link reads the same on the two sides. The working tree, a proposed edit
    and a mapping have none, and the runtime-provider pass then has the root
    readers alone, as before.
    """
    if isinstance(snapshot, GitSnapshot) and isinstance(base, GitSnapshot):
        return LinkedTreeView(snapshot, base)
    return None


# Source the engine's passes read where it lies, or find by a search of the
# tree. A link with such a name is not what they see: a search does not look
# inside a link, pytest runs a linked conftest at the link's path, and a test
# that exists only as a link is no test to the detectors (#551).
_SOURCE_SUFFIXES = (".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts")
# What an import finds beside source: a compiled Python module, and an
# archive that can stand on the import path.
_COMPILED_SUFFIXES = (".pyc", ".pyo", ".pyd", ".so", ".zip", ".egg", ".whl")
# The names pytest takes for a config, in whatever directory a run starts from or names with `-c`.
_PYTEST_CONFIG_NAMES = frozenset({"pytest.toml", ".pytest.toml", "pytest.ini", ".pytest.ini", "pyproject.toml",
                                  "tox.ini", "setup.cfg"})
# Where a repository keeps checkwash's own policy. It is read from the base
# tree before any pass runs, and `sweep` reads it from git itself.
_POLICY_DIRECTORIES = (".checkwash", ".greenwash")


def _matters_under_a_second_name(path, mode):
    """Would this entry, beneath a directory link's target, mean something under the link's path too? (#551)

    A file beneath the target has a second name under the link, which no
    pass lists, searches or resolves. Source, a compiled module and an
    archive can be imported or collected under it, a text file that
    pytest's default doctest pattern takes (`test*.txt`) collected under
    it, a pytest config found under it, and a link beneath the target gives
    further names that are not looked at.
    """
    lowered = path.lower()
    name = path.rsplit("/", 1)[-1]
    return (mode == b"120000" or lowered.endswith(_SOURCE_SUFFIXES) or lowered.endswith(_COMPILED_SUFFIXES)
            or name in _PYTEST_CONFIG_NAMES or (name.startswith("test") and name.endswith(".txt")))


class LinkedTreeView:
    """A committed range's head as the runtime-provider pass reads its unchanged links (#551).

    Ruling 551, question 2 (owner, 2026-11-27). The pass asks for unchanged
    paths that could hold a test runner, a pytest control, a candidate test
    or a provider, and `GitSnapshot.read_many` refuses a link among them.
    Where that refusal would end the pass, the engine runs it again through
    this view (`_record_runtime_shadows`), and here:
    - a link to a regular file of the same commit reads as that file, as a
      symlinked pytest config does in a range check (D-133 item 2);
    - a link to a directory of the same commit is listed as an opaque
      directory, as the working tree lists one (D-134): it holds no bytes,
      the files it leads to are listed under their own paths, and an import
      that can resolve inside it or a collection that can reach it fails
      closed, naming it;
    - a link that leads to nothing the tree holds keeps the refusal, naming
      it, when the pass asks for it.

    Only this pass reads a link. Every other pass reads the snapshot, where a
    search does not look inside a link, a path beneath a link is absent, and
    some readers take a refused link for an absent file. So a run that reads
    links here ends with a verdict only under two conditions, and otherwise
    as it did before the ruling, with the same refusal.

    First, every link of the tree is one the view can answer for
    (`readable`), whether the pass asks for it or not:
    - a link must read the same on both sides of the range: the same entry
      at base and at head, text that leads to the same place in both trees.
      For a file that place holds the same entry, bytes and mode. For a
      directory no path beneath it differs, and no submodule lies in it. A
      link whose target the range adds, changes or removes stands for
      something else at head than at base, and no reader is told;
    - a link named as source (`_SOURCE_SUFFIXES`) is not read, whatever it
      leads to: a test, a conftest or a module that exists under the link's
      name is one only this pass would see, and pytest runs a linked
      conftest at the link's path, where `Path(__file__).resolve()` is the
      target's;
    - a directory link is not read when a file named as source lies beneath
      its target, or a compiled module, an archive, a `test*.txt` file, a
      pytest config or another link (`_matters_under_a_second_name`). Such
      a file has a second name under
      the link, and no pass knows it: an import through the link resolves to
      nothing, a helper a test calls through it is never read, and a search
      finds no importer there;
    - a link at `.checkwash` or `.greenwash`, or beneath one, is not read:
      checkwash's own policy is read through it as absent;
    - a link the walk cannot place (another link, a submodule, text it does
      not read, an absolute text or one that leaves the tree, a name the
      tree holds in another case) is not known to be harmless.

    The engine asks one thing more of a readable view (`aliases`): no file
    beneath a directory link's target has another role under the link's
    path than under its own (`_record_runtime_shadows`).

    Second, no other reader asked either tree for a link or for a path
    beneath one (`settle`). The trees note each such ask made through
    `read`, `read_many`, `definitely_lacks`, `config_modes` or
    `read_config_many` (`GitSnapshot._asked_through_a_link`), from the
    moment they are made. A test made on the path listing alone asks
    nothing and is not noted. The scan that follows a changed
    script's call to another script is one such reader: it takes a script it
    cannot read for one that runs no suite, so `|| true` after a call to a
    linked script, or to a script beneath a directory link, would pass.

    The working tree has no such view.
    """

    def __init__(self, snapshot, base):
        self._snapshot = snapshot
        self._base = base
        self._readings = None
        self._directories = None
        self._listed = None
        self._unreadable = None
        # The refusal that sent the pass here, once it reads through the view,
        # and what the view itself kept from it.
        self._refusal = None
        self._asked = []

    def _resolved(self):
        """Every link of the head tree with its reading, each link's text read once."""
        if self._readings is None:
            snapshot, base = self._snapshot, self._base
            snapshot.list_paths()
            base.list_paths()
            entries, trees, submodules = snapshot._tree_entries, snapshot._trees, snapshot._opaque
            base_entries, base_trees, base_submodules = base._tree_entries, base._trees, base._opaque
            links = sorted((path, oid, size) for path, (mode, oid, size) in entries.items() if mode == b"120000")
            folded = frozenset(_folded(name) for name in (*entries, *trees, *submodules)) if links else frozenset()
            base_folded = (frozenset(_folded(name) for name in (*base_entries, *base_trees, *base_submodules))
                           if links else frozenset())
            second_names = sorted(name for name, entry in entries.items()
                                  if _matters_under_a_second_name(name, entry[0]))
            policy = tuple(directory + "/" for directory in _POLICY_DIRECTORIES)
            changed = sorted(path for path in entries.keys() | base_entries.keys()
                             if entries.get(path) != base_entries.get(path))
            changed += [path for path in sorted(set(submodules) ^ set(base_submodules))]
            every_submodule = tuple(sorted(set(submodules) | set(base_submodules)))
            sized = [link for link in links if link[2] <= MAX_LINK_TEXT_BYTES]
            total = 0
            for path, _oid, size in sized:
                total += size
                if total > MAX_BATCH_BYTES:
                    raise _batch_over_limit(path, snapshot._side(), total)
            texts = snapshot._read_objects(sized)
            readings = {}
            unreadable = []
            for path, _oid, _size in links:
                kind, target = walk = _link_walk(path, texts.get(path), entries, trees, submodules, folded)
                safe = (base_entries.get(path) == entries[path] and kind != "unknown"
                        and not path.lower().endswith(_SOURCE_SUFFIXES)
                        and path not in _POLICY_DIRECTORIES and not path.startswith(policy)
                        and walk == _link_walk(path, texts.get(path), base_entries, base_trees, base_submodules,
                                               base_folded))
                if safe and kind == "file":
                    safe = base_entries.get(target) == entries.get(target)
                elif safe and kind == "directory":
                    inside = target + "/" if target else ""
                    first = bisect_left(second_names, inside)
                    safe = (not any(other == target or other.startswith(inside) for other in changed)
                            and not any(other == target or other.startswith(inside) for other in every_submodule)
                            and not (first < len(second_names) and second_names[first].startswith(inside)))
                if not safe:
                    unreadable.append(path)
                readings[path] = walk if safe and kind in ("file", "directory") else None
            self._unreadable = tuple(unreadable)
            self._readings = readings
            self._directories = tuple(sorted(
                SymlinkedDirectory(path) for path, reading in self._readings.items()
                if reading is not None and reading[0] == "directory"
            ))
        return self._readings

    def readable(self):
        """Is every link of the tree one the view can answer for, or one that leads to nothing?"""
        self._resolved()
        return not self._unreadable

    def aliases(self):
        """Each file beneath a directory link's target, as (its name under the link, its own path).

        The second name is one no reader lists. The view answers for the
        link only if that name means nothing more than the first: the
        engine compares the roles of the two (`_alias_changes_a_role`). No
        link lies beneath such a target (`_matters_under_a_second_name`),
        so there are no names through a second link.
        """
        readings = self._resolved()
        listed = self._snapshot.list_paths()
        for link, reading in sorted(readings.items()):
            if reading is None or reading[0] != "directory":
                continue
            inside = reading[1] + "/" if reading[1] else ""
            for index in range(bisect_left(listed, inside), len(listed)):
                real = listed[index]
                if not real.startswith(inside):
                    break
                yield link + "/" + real[len(inside):], real

    def mark(self):
        """Where the two trees' notes of link asks stand now, for `begin`."""
        return (len(self._snapshot._link_asks), len(self._base._link_asks))

    def begin(self, refusal, mark):
        """Start answering for the links, after `refusal` ended the pass's run over the snapshot.

        `mark` is where the notes stood before that run. Its asks for the
        links this view reads are dropped: the pass runs again from the
        start, and the view answers them. Every other ask it made stays
        noted, a path beneath a link among them: something the pass
        consulted may remember the answer and not ask again.
        """
        self._require_readable()
        readings = self._resolved()
        self._refusal = refusal
        for notes, start in ((self._snapshot._link_asks, mark[0]), (self._base._link_asks, mark[1])):
            notes[start:] = [path for path in notes[start:] if readings.get(path) is None]

    def asked(self):
        """Each path a link kept from a reader: the view's own refusals, then the head tree's notes and the base's.

        Everything the two trees were asked counts, from the moment they
        were made: the policy files are read from the base tree before any
        pass runs. One range check makes its trees and runs one analysis.
        """
        return (*self._asked, *self._snapshot._link_asks, *self._base._link_asks)

    def settle(self):
        """End a run: one that read links here keeps the refusal if any other reader asked for a link.

        The view answers the runtime-provider pass alone. Any other reader
        that asked either tree for a link, or for a path beneath one, was
        refused or told the path is absent, and may have gone on as if no
        such file existed. The run then ends as it did before the ruling,
        with the refusal that sent the pass here. A run that never read
        through the view is left as it is.
        """
        if self._refusal is not None and self.asked():
            raise self._refusal

    def unreadable(self):
        """The links that keep the view from being used, in path order."""
        self._resolved()
        return self._unreadable

    def list_paths(self):
        """`GitSnapshot.list_paths`, with each link the view reads as a directory as an opaque directory."""
        if self._listed is None:
            self._require_readable()
            directories = set(self._directories)
            listed = [path for path in self._snapshot.list_paths() if path not in directories]
            listed.extend(SymlinkedDirectory(directory + "/") for directory in self._directories)
            self._listed = tuple(sorted(listed))
        return list(self._listed)

    def _require_readable(self):
        if not self.readable():
            raise _nonregular("strict snapshot batch cannot inspect nonregular source", self._unreadable[0], b"120000")

    def read_many(self, paths):
        """`GitSnapshot.read_many`, with each link the view reads as a file answered as that file.

        The target is read as any selected source is, so one over the source
        limit refuses under its own path, and a read inside a link to a
        directory fails closed, as one inside a working-tree directory link
        does (#414). A link that leads to nothing falls through to the
        snapshot, which refuses it as before.
        """
        self._require_readable()
        readings = self._resolved()
        followed = {}
        plain = []
        for path in sorted(set(paths)):
            owner = opaque_owner(path, self._directories)
            if owner is not None:
                # Noted too: a caller that catches the refusal has not read the path.
                self._asked.append(path)
                raise opaque_error(owner, f"{path} lies inside it")
            reading = readings.get(path)
            if reading is not None and reading[0] == "file":
                followed[path] = reading[1]
            else:
                plain.append(path)
        data = self._snapshot.read_many([*plain, *followed.values()])
        result = {path: data[path] for path in plain}
        result.update({path: data[target] for path, target in followed.items()})
        return result


# Where a virtual environment keeps links of its own (D-208): its scripts
# directory, where `python -m venv` links the environment's interpreter on
# Linux and macOS (`bin`) and, given `--symlinks`, on Windows (`Scripts`),
# and the `lib64` link to `lib` that it makes on 64-bit Linux.
_ENVIRONMENT_SCRIPTS = frozenset({"bin", "Scripts"})


def _regular_file(path):
    try:
        return stat.S_ISREG(os.lstat(path).st_mode)
    except (OSError, ValueError):
        return False


def environment_of_link(root, path):
    """The virtual environment of which `path` is an own link, or None (D-208).

    `path`, relative to the repository root `root` and spelled with `/`, must
    be a symbolic link directly in `<D>/bin` or `<D>/Scripts` whose name does
    not end in `.py` in any case, or `<D>/lib64` linking to `lib` beside a
    directory `<D>/lib` (`environment_lib64`). `<D>` is a directory other than
    the repository root that holds `pyvenv.cfg` as a regular file: the file
    PEP 405 names, which `python -m venv`, virtualenv and uv write, and by
    which pytest skips the directory when recursing. Each test is an lstat, or
    a readlink on `lib64`, so no link is followed and a `pyvenv.cfg` that is a
    link does not count. The answer is `<D>`, spelled as `path` spells it.
    """
    parts = path.split("/")
    if any(part in ("", ".", "..") for part in parts) or parts[-1].lower().endswith(".py"):
        return None
    if len(parts) >= 3 and parts[-2] in _ENVIRONMENT_SCRIPTS:
        environment = parts[:-2]
        try:
            if not stat.S_ISLNK(os.lstat(os.path.join(root, *parts)).st_mode):
                return None
            if not stat.S_ISREG(os.lstat(os.path.join(root, *environment, "pyvenv.cfg")).st_mode):
                return None
        except (OSError, ValueError):
            return None
        return "/".join(environment)
    if len(parts) >= 2 and parts[-1] == "lib64":
        environment = parts[:-1]
        return "/".join(environment) if environment_lib64(os.path.join(root, *environment), "lib64") else None
    return None


def environment_lib64(directory, name):
    """Is `directory/name` a virtual environment's `lib64` link to its `lib` (D-208)?

    `python -m venv` links `lib64` to `lib` on 64-bit Linux. A link named
    `lib64` whose text is exactly `lib`, beside a directory `lib`, in a
    directory that holds `pyvenv.cfg` as a regular file, holds no file a
    walk does not list under `lib`. Each test is an lstat or a readlink, so
    nothing is followed. The caller rules out the repository root.
    """
    if name != "lib64":
        return False
    try:
        return (stat.S_ISLNK(os.lstat(os.path.join(directory, name)).st_mode)
                and os.readlink(os.path.join(directory, name)) == "lib"
                and stat.S_ISDIR(os.lstat(os.path.join(directory, "lib")).st_mode)
                and stat.S_ISREG(os.lstat(os.path.join(directory, "pyvenv.cfg")).st_mode))
    except (OSError, ValueError):
        return False


class WorkingTreeSnapshot:
    def __init__(self, repo, side="worktree"):
        self.root = Path(repo).resolve()
        self.side = side  # named in a size refusal (#415)

    def _passed_over(self, directory, name):
        """A directory link the walks pass over: a virtual environment's `lib64`
        link to its `lib`, below the repository root, whose files the walk
        lists under `lib` (D-208). Every other directory link stays opaque (#414)."""
        return Path(directory) != self.root and environment_lib64(directory, name)

    def list_paths(self):
        """Inventory all repository files except Git's own metadata.

        Ignored and hidden trees are listed like any other: in hook mode the
        whole working tree is attacker-controlled. A directory symlink is
        listed as its path with a trailing slash, an opaque directory as a
        submodule is (`split_inventory`), and is never followed. A pass that
        needs a fact from inside it, an import that could resolve there or a
        collection that could reach it, fails closed naming it (#414). A
        virtual environment's own non-directory links in `bin` or `Scripts`
        are not listed at all (D-208): no pass reads them, and a read of one
        refuses; its `lib64` link to its `lib` is passed over, as its files
        are listed under `lib`, while any other directory link stays opaque.
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
                if self._passed_over(directory, name):
                    continue
                link = Path(directory, name).relative_to(self.root).as_posix()
                paths.append(SymlinkedDirectory(link + "/"))
                if len(paths) > MAX_INVENTORY_PATHS:
                    raise _over_limit(link)
            dirs[:] = kept
            # Test pyvenv.cfg once per scripts directory so ordinary files pay no lstat.
            in_scripts = (
                Path(directory) != self.root
                and os.path.basename(directory) in _ENVIRONMENT_SCRIPTS
                and Path(directory).parent != self.root
                and _regular_file(os.path.join(os.path.dirname(directory), "pyvenv.cfg"))
            )
            for filename in sorted(files):
                if filename == ".git":
                    continue
                path = Path(directory, filename).relative_to(self.root).as_posix()
                if in_scripts and environment_of_link(self.root, path) is not None:
                    continue
                paths.append(path)
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
                raise _nonregular("strict snapshot batch cannot inspect nonregular source", path, b"120000",
                                  side=self.side, entry="worktree/read_many")
            data = self.read(path)
            if data is not None:
                size_total += len(data)
                if size_total > MAX_BATCH_BYTES:
                    raise _batch_over_limit(path, self.side, size_total)
            result[path] = data
        return result

    def config_modes(self, paths):
        """Config metadata only; preserve ordinary source admission and follow no link data."""
        selected = sorted(set(paths))
        if len(selected) > MAX_INVENTORY_PATHS:
            raise EngineError("worktree pytest config metadata exceeds the path limit")
        result = {}
        for path in selected:
            if (not path or path.startswith("/") or ":" in path or "\\" in path
                    or any(c in path for c in "\r\n\0")
                    or any(part in {"", ".", ".."} for part in path.split("/"))):
                raise EngineError(f"worktree pytest config has an unsafe path: path={path!r}")
            owner = self._symlinked_ancestor(path)
            if owner is not None:
                raise opaque_error(owner, f"{path} lies inside it")
            lexical = self.root / path
            try:
                parent = lexical.parent.resolve()
            except (OSError, RuntimeError) as exc:
                raise EngineError(f"worktree pytest config metadata unavailable: path={path!r}") from exc
            if not parent.is_relative_to(self.root):
                raise EngineError(f"worktree pytest config leaves the repository: path={path!r}; use a repository-owned regular source or a committed range")
            try:
                mode = lexical.lstat().st_mode
            except FileNotFoundError:
                result[path] = None
                continue
            except OSError as exc:
                raise EngineError(f"worktree pytest config metadata unavailable: path={path!r}") from exc
            result[path] = (b"120000" if stat.S_ISLNK(mode) else
                            b"100755" if stat.S_ISREG(mode) and mode & stat.S_IXUSR else
                            b"100644" if stat.S_ISREG(mode) else
                            b"040000" if stat.S_ISDIR(mode) else b"nonregular")
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
            logical = "<non-repository-relative path>" if Path(path).anchor else path
            raise EngineError(
                f"strict snapshot path leaves the repository: path={logical!r}, "
                f"side={self.side!r}, entry='worktree/read'. "
                "Restore a repository-owned regular source at this path; "
                "a committed range reads committed bytes only, not this working-tree source."
            )
        try:
            mode = lexical.lstat().st_mode
        except FileNotFoundError:
            return None
        if not stat.S_ISREG(mode):
            kind = b"120000" if stat.S_ISLNK(mode) else b"040000" if stat.S_ISDIR(mode) else None
            raise _nonregular("strict snapshot cannot inspect nonregular source", path, kind,
                              side=self.side, entry="worktree/read")
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
            # Its first bytes are in memory already: keep the prefix, with no
            # read added and the 1,000,001-byte bound unchanged (#455).
            return UnreadSide(path, self.side, size, MAX_SOURCE_BYTES, prefix=data[:SHEBANG_PREFIX_BYTES])
        return data

    def search(self, needles, exclude=frozenset()):
        """Python paths holding a needle; the empty needle lists them all.

        `exclude` leaves its paths out of an ordinary search: they are neither
        read, returned nor counted toward the hit limit (D-206). The
        inventory, the empty needle, is never narrowed.
        """
        if not needles:
            return []
        wanted = [n.encode("utf-8") for n in needles]
        paths = []

        def fail(error):
            raise EngineError("strict snapshot importer search failed") from error

        for directory, dirs, files in os.walk(self.root, onerror=fail):
            # An empty needle requests the entire nonempty Python inventory.
            # Importer searches may skip generated/hidden trees, but an
            # optional startup-context proof cannot silently omit them. Both
            # pass over a virtual environment's `lib64` link to its `lib`,
            # whose files they find under `lib` (D-208).
            dirs[:] = sorted(d for d in dirs if d != ".git" and (
                "" in needles or (d not in _SKIP and not d.startswith("."))
            ) and not (d == "lib64" and self._passed_over(directory, d)))
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
                if "" not in needles and path in exclude:
                    continue
                data = self.read(path)
                if data is None:
                    raise EngineError("strict snapshot source disappeared during importer search")
                if data and any(n in data for n in wanted):
                    paths.append(path)
                    if len(paths) >= MAX_SEARCH_HITS:
                        raise SearchHitLimit("strict snapshot importer search exceeds the hit limit")
        return paths

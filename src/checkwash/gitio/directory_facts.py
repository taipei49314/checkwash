"""Internal paired directory-link metadata; never permission to omit source.

The caller must separately prove runner/config/collection irrelevance. This
capability reads only tree objects and symlink payloads, never target files.
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from checkwash.change import EngineError
from checkwash.gitio.snapshot import (
    MAX_BATCH_BYTES,
    MAX_INVENTORY_PATHS,
    MAX_SOURCE_BYTES,
    GitSnapshot,
    _run,
)

NO_PROOF: Literal["NO_PROOF"] = "NO_PROOF"


@dataclass(frozen=True)
class TreeEdge:
    parent_oid: bytes
    name: str
    child_oid: bytes
    mode: bytes = b"040000"


@dataclass(frozen=True)
class DirectoryLinkFact:
    revision: str
    root_tree_oid: bytes
    path: str
    link_mode: bytes
    link_oid: bytes
    link_size: int
    target_path: str
    target_mode: bytes
    target_oid: bytes
    # Every edge was mode 040000 and its complete child tree was verified.
    # Edges include traversals subsequently reversed by a literal '..'.
    ancestors: tuple[TreeEdge, ...]
    # None means that no complete child inventory was supplied, never empty.
    children: tuple[tuple[str, bytes, bytes], ...] | None = None


@dataclass(frozen=True)
class PairedDirectoryLinkFact:
    before: DirectoryLinkFact
    after: DirectoryLinkFact


@dataclass(frozen=True)
class DirectoryFactsBatch:
    records: Mapping[str, PairedDirectoryLinkFact | Literal["NO_PROOF"]]
    before_tree_bytes: int
    after_tree_bytes: int
    before_link_bytes: int
    after_link_bytes: int
    before_tree_entries: int
    after_tree_entries: int

    @property
    def metadata_bytes(self) -> int:
        return (self.before_tree_bytes + self.after_tree_bytes
                + self.before_link_bytes + self.after_link_bytes)


@dataclass
class _Budget:
    bytes_read: int = 0
    reserve_bytes: Callable[[int], None] | None = None
    reserve_entries: Callable[[int], None] | None = None

    def charge(self, size: int) -> None:
        self.bytes_read += size
        if self.bytes_read > MAX_BATCH_BYTES:
            raise EngineError("directory-link metadata exceeds the paired byte limit")
        if self.reserve_bytes is not None:
            self.reserve_bytes(size)


def _paths(paths: Sequence[str]) -> list[str]:
    if not isinstance(paths, Sequence) or isinstance(paths, (str, bytes)):
        raise EngineError("directory-link metadata requires a path sequence")
    if len(paths) > MAX_INVENTORY_PATHS:
        raise EngineError("directory-link metadata request exceeds the inventory limit")
    selected: set[str] = set()
    path_bytes = 0
    for path in paths:
        if (not isinstance(path, str) or not path or path.startswith("/")
                or ":" in path or "\\" in path
                or any(char in path for char in "\r\n\0")
                or any(part in {"", ".", ".."} for part in path.split("/"))):
            raise EngineError("directory-link metadata received an unsafe path")
        if path in selected:
            continue
        try:
            path_bytes += len(path.encode("utf-8", errors="strict"))
        except UnicodeError as exc:
            raise EngineError("directory-link metadata path is undecodable") from exc
        selected.add(path)
        if len(selected) > MAX_INVENTORY_PATHS or path_bytes > MAX_BATCH_BYTES:
            raise EngineError("directory-link metadata request exceeds the inventory limit")
    return sorted(selected)


def _size(digits: bytes, limit: int, message: str) -> int:
    # Git emits canonical decimal sizes. Compare before int() so a corrupt
    # header cannot escape EngineError via Python's integer conversion limit.
    maximum = str(limit).encode("ascii")
    if (len(digits) > len(maximum)
            or len(digits) == len(maximum) and digits > maximum):
        raise EngineError(message)
    return int(digits)


class _Side:
    def __init__(self, snapshot: GitSnapshot, budget: _Budget) -> None:
        self.snapshot = snapshot
        self.revision = snapshot._rev()
        self.budget = budget
        self.trees: dict[bytes, dict[str, tuple[bytes, bytes]]] = {}
        self.tree_entries = 0
        self.tree_bytes = 0
        self.link_bytes = 0
        raw = _run(snapshot.repo, ["rev-parse", "--verify", "--end-of-options",
                                   f"{self.revision}^{{tree}}"])
        if not re.fullmatch(b"(?:[0-9a-f]{40}|[0-9a-f]{64})\n", raw):
            raise EngineError("directory-link metadata returned an invalid root tree")
        self.root = raw[:-1]
        self._tree(self.root)

    def _tree(self, oid: bytes) -> dict[str, tuple[bytes, bytes]]:
        if oid in self.trees:
            return self.trees[oid]
        checked = _run(self.snapshot.repo, ["cat-file", "--batch-check"], data=oid + b"\n")
        match = re.fullmatch(re.escape(oid) + rb" tree (0|[1-9][0-9]*)\n", checked)
        if match is None:
            raise EngineError("directory-link metadata returned an invalid tree header")
        size = _size(match.group(1), MAX_BATCH_BYTES,
                     "directory-link metadata exceeds the paired byte limit")
        self.budget.charge(size)
        self.tree_bytes += size
        raw = _run(self.snapshot.repo, ["cat-file", "--batch"], data=oid + b"\n")
        header, separator, body = raw.partition(b"\n")
        if (not separator or header != checked[:-1] or len(body) != size + 1
                or not body.endswith(b"\n")):
            raise EngineError("directory-link metadata returned an incomplete tree")
        payload = body[:-1]
        algorithm = "sha1" if len(oid) == 40 else "sha256"
        digest = hashlib.new(algorithm, b"tree " + str(size).encode("ascii")
                             + b"\0" + payload).hexdigest().encode("ascii")
        if digest != oid:
            raise EngineError("directory-link tree content does not match its identity")
        width = len(oid) // 2
        entries: dict[str, tuple[bytes, bytes]] = {}
        cursor = 0
        previous_key = None
        while cursor < len(payload):
            space = payload.find(b" ", cursor)
            nul = payload.find(b"\0", space + 1) if space >= 0 else -1
            if space < 0 or nul < 0 or nul + 1 + width > len(payload):
                raise EngineError("directory-link metadata has an incomplete tree entry")
            mode = payload[cursor:space]
            if mode not in {b"40000", b"100644", b"100755", b"120000", b"160000"}:
                raise EngineError("directory-link metadata has an invalid tree mode")
            try:
                name = payload[space + 1:nul].decode("utf-8", errors="strict")
            except UnicodeError as exc:
                raise EngineError("directory-link metadata has an undecodable tree name") from exc
            if (not name or name in {".", ".."} or any(c in name for c in "/\r\n\0")
                    or name in entries):
                raise EngineError("directory-link metadata has an invalid or duplicate tree name")
            # Git compares a tree name as if followed by '/', and any other
            # entry as if followed by NUL. Reject a hash-valid unsorted tree:
            # dictionary lookup must agree with Git's canonical tree lookup.
            key = payload[space + 1:nul] + (b"/" if mode == b"40000" else b"\0")
            if previous_key is not None and key <= previous_key:
                raise EngineError("directory-link metadata has an unsorted tree")
            previous_key = key
            child = payload[nul + 1:nul + 1 + width].hex().encode("ascii")
            entries[name] = (mode, child)
            self.tree_entries += 1
            if self.budget.reserve_entries is not None:
                self.budget.reserve_entries(1)
            if self.tree_entries > MAX_INVENTORY_PATHS:
                raise EngineError("directory-link metadata exceeds the tree entry limit")
            cursor = nul + 1 + width
        self.trees[oid] = entries
        return entries

    def _parent(self, path: str) -> tuple[
        list[tuple[str, bytes]], list[TreeEdge], tuple[bytes, bytes] | None,
    ] | None:
        stack = [("", self.root)]
        edges: list[TreeEdge] = []
        parts = path.split("/")
        for name in parts[:-1]:
            parent = stack[-1][1]
            entry = self._tree(parent).get(name)
            if entry is None or entry[0] != b"40000":
                return None
            self._tree(entry[1])
            edges.append(TreeEdge(parent, name, entry[1]))
            stack.append((name, entry[1]))
        return stack, edges, self._tree(stack[-1][1]).get(parts[-1])

    def collect(self, paths: list[str]) -> dict[str, DirectoryLinkFact]:
        links: dict[str, tuple[list[tuple[str, bytes]], list[TreeEdge], bytes]] = {}
        for path in paths:
            located = self._parent(path)
            if located is not None and located[2] is not None and located[2][0] == b"120000":
                links[path] = (located[0], located[1], located[2][1])
        if not links:
            return {}
        # The source transport already batches at its original 256-object
        # boundary. Preflight all declared sizes before any link payload read.
        checked = _run(self.snapshot.repo, ["cat-file", "--batch-check"],
                       data=b"".join(value[2] + b"\n" for value in links.values()))
        records = checked.splitlines(keepends=True)
        if len(records) != len(links):
            raise EngineError("directory-link metadata returned incomplete link headers")
        present: list[tuple[str, bytes, int]] = []
        for (path, link_record), record in zip(links.items(), records):
            oid = link_record[2]
            match = re.fullmatch(re.escape(oid) + rb" blob (0|[1-9][0-9]*)\n", record)
            if match is None:
                raise EngineError("directory-link metadata returned an invalid link header")
            size = _size(match.group(1), MAX_SOURCE_BYTES,
                         "directory-link payload exceeds the source byte limit")
            self.budget.charge(size)
            self.link_bytes += size
            present.append((path, oid, size))
        payloads = self.snapshot._read_objects(present)
        facts: dict[str, DirectoryLinkFact] = {}
        for path, oid, size in present:
            try:
                target = payloads[path].decode("utf-8", errors="strict")
            except UnicodeError:
                continue  # Verified bytes, but outside the admitted link syntax.
            if (not target or target.startswith("/") or ":" in target
                    or any(c in target for c in "\\\r\n\0")):
                continue
            original_stack, original_edges, _ = links[path]
            stack = list(original_stack)
            edges = list(original_edges)
            proved = True
            for name in target.split("/"):
                if name in {"", "."}:
                    continue
                if name == "..":
                    if len(stack) == 1:
                        proved = False
                        break
                    stack.pop()
                    continue
                parent = stack[-1][1]
                entry = self._tree(parent).get(name)
                if entry is None or entry[0] != b"40000":
                    proved = False
                    break
                self._tree(entry[1])
                edges.append(TreeEdge(parent, name, entry[1]))
                stack.append((name, entry[1]))
            if proved:
                facts[path] = DirectoryLinkFact(
                    self.revision, self.root, path, b"120000", oid, size,
                    "/".join(name for name, _ in stack[1:]), b"040000", stack[-1][1], tuple(edges),
                    tuple((name, mode, oid) for name, (mode, oid)
                          in self._tree(stack[-1][1]).items()))
        return facts


def paired_directory_link_facts(
    before: GitSnapshot, after: GitSnapshot, paths: Sequence[str],
    *, reserve_bytes: Callable[[int], None] | None = None,
    reserve_entries: Callable[[int], None] | None = None,
) -> DirectoryFactsBatch:
    """Return a verified paired fact or explicit NO_PROOF for every requested path.

    One invocation owns its same-side metadata cache. The optional callbacks
    reserve payload bytes before transport and count entries before publishing
    that side's complete verified tree cache, against a consumer's remaining
    allowance. The original standalone transport ceiling also remains active.
    The returned ledger includes unsuccessful proof attempts. Neither an
    omitted callback nor a successful fact establishes analysis-wide bounded
    work or relevance. Callback errors propagate without refund or caching.
    Generic/config source readers and existing inventory semantics are unchanged.
    """
    if not isinstance(before, GitSnapshot) or not isinstance(after, GitSnapshot):
        raise EngineError("directory-link metadata requires frozen Git snapshots")
    selected = _paths(paths)
    if not selected:
        return DirectoryFactsBatch(MappingProxyType({}), 0, 0, 0, 0, 0, 0)
    budget = _Budget(reserve_bytes=reserve_bytes, reserve_entries=reserve_entries)
    old_side, new_side = _Side(before, budget), _Side(after, budget)
    old, new = old_side.collect(selected), new_side.collect(selected)
    result: dict[str, PairedDirectoryLinkFact | Literal["NO_PROOF"]] = {}
    for path in selected:
        left, right = old.get(path), new.get(path)
        if (left is not None and right is not None
                and (left.link_oid, left.link_size, left.target_path, left.target_oid)
                == (right.link_oid, right.link_size, right.target_path, right.target_oid)):
            result[path] = PairedDirectoryLinkFact(left, right)
        else:
            result[path] = NO_PROOF
    return DirectoryFactsBatch(
        MappingProxyType(result), old_side.tree_bytes, new_side.tree_bytes,
        old_side.link_bytes, new_side.link_bytes,
        old_side.tree_entries, new_side.tree_entries)

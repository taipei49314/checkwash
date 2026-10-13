"""Internal optional shebang-probe deferral within shadow's original batch.

This is not a generic source reader. Inventory remains complete; a deferred
key is absent from the byte cache and every required access is still strict.
"""
from __future__ import annotations

import configparser
import posixpath
import re
from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Literal

from checkwash.change import EngineError
from checkwash.frontends.python.conftest_controls import is_collection_control
from checkwash.frontends.python.frontend import parse_python
from checkwash.gitio.directory_facts import (
    PairedDirectoryLinkFact,
    paired_directory_link_facts,
)
from checkwash.gitio.pytest_configs import PairedPytestConfigs
from checkwash.gitio.snapshot import (
    MAX_BATCH_BYTES,
    MAX_INVENTORY_PATHS,
    MAX_SOURCE_BYTES,
)
from checkwash.roles import _is_runner_script, _runner_shape, collectable
from checkwash.runner_references import ReferenceClosure, reference_closure


class _Ledger:
    def __init__(self, initial: set[str]):
        self.bytes = 0
        self.work = len(initial)  # Deferred members retain the original count.
        self.logical: set[tuple[str, str]] = set()
        self.reserve_work(0)

    def reserve_bytes(self, size: int) -> None:
        self.bytes += size
        if self.bytes > MAX_BATCH_BYTES:
            raise EngineError("runtime-shadow initial snapshot exceeds the source byte limit")

    def reserve_work(self, count: int) -> None:
        self.work += count
        if self.work > MAX_INVENTORY_PATHS:
            raise EngineError("runtime-shadow initial snapshot exceeds the source read limit")

    def source(self, side: str, path: str, size: int, link_bytes: int = 0) -> None:
        if size > MAX_SOURCE_BYTES:
            raise EngineError("runtime-shadow initial snapshot exceeds the source byte limit")
        key = side, path
        if key not in self.logical:
            self.reserve_bytes(size + link_bytes)
            self.logical.add(key)


class DeferredSources(dict):
    """Only successful bytes are iterable; get/item are required-read barriers."""

    def __init__(self, values: Mapping[str, bytes | None], deferred: set[str],
                 required: Callable[[str], bytes]):
        super().__init__(values)
        self.deferred = frozenset(deferred)
        self.required = required
        self.proofs: Mapping[str, PairedDirectoryLinkFact | Literal["NO_PROOF"]] = MappingProxyType({})
        self.contexts: Mapping[str, ReferenceClosure] = MappingProxyType({})

    def __getitem__(self, path):
        if path in self.deferred:
            return self.required(path)
        return super().__getitem__(path)

    def get(self, path, default=None):
        if path in self.deferred:
            return self.required(path)
        return super().get(path, default)


def optional_candidates(evidence, reader, initial: set[str], config,
                        config_paths, test_paths, conftest_paths) -> set[str]:
    if (not isinstance(evidence, PairedPytestConfigs) or not evidence._prepared
            or reader != evidence.snapshots["after"].read_many):
        return set()
    prohibited = set(config_paths) | set(test_paths) | set(conftest_paths)
    candidates = set()
    for path in initial - prohibited:
        name = path.rsplit("/", 1)[-1]
        if (not name or "." in name or collectable(path)
                or config.role_of(path) == "ci" or _runner_shape(path, None, None)):
            continue
        if all(evidence.snapshots[side]._tree_entries.get(path, (None,))[0] == b"120000"
               for side in ("before", "after")):
            candidates.add(path)
    return candidates


def _flat_data(fact: PairedDirectoryLinkFact) -> bool:
    # All children, not merely filenames returned by a recursive source list.
    # Any subdirectory/link/gitlink withholds this bounded proof. We do not
    # infer custom collection from filenames; unsupported settings decline.
    return all(side.children is not None and all(
        mode in {b"100644", b"100755"} and not name.casefold().endswith((".py", ".txt"))
        for name, mode, _oid in side.children)
        for side in (fact.before, fact.after))


def _touches(reference: str, alias: str) -> bool:
    # A proof is shared across platforms. A Git-distinct case variant cannot
    # establish runtime absence on a case-insensitive filesystem.
    reference, alias = reference.casefold(), alias.casefold()
    return reference == alias or reference.startswith(alias + "/")


def _conftest_opaque(data: bytes) -> bool:
    parsed = parse_python(data, collect_tests=False, conftest=True)
    # Use the existing collection/runtime classification, plus conservative
    # source-visible plugin/configuration and unmodeled collection hooks.
    # Runtime hooks and ordinary fixtures are not opaque merely by existing.
    return (not parsed.parse_ok or b"pytest_plugins" in data
            or re.search(rb"\bpytest_(?:collect[A-Za-z0-9_]*|pycollect_[A-Za-z0-9_]*|"
                         rb"generate_tests|ignore_collect|configure|addoption)\b", data) is not None
            or any(is_collection_control(marker.name)
                   for unit in parsed.units for marker in unit.side.markers))


def _conftest_index(paths, reserve_work: Callable[[int], None]) -> dict[str, set[str]]:
    index: dict[str, set[str]] = {}
    for path in paths:
        reserve_work(1)
        if path.rsplit("/", 1)[-1].casefold() == "conftest.py":
            index.setdefault(path.casefold(), set()).add(path)
    return index


def _ancestor_conftests(directory: str, index: Mapping[str, set[str]],
                       reserve_work: Callable[[int], None]) -> set[str]:
    selected: set[str] = set()
    while True:
        reserve_work(1)
        path = posixpath.join(directory, "conftest.py")
        selected.update(index.get(path.casefold(), ()))
        if not directory:
            return selected
        directory = posixpath.dirname(directory)


def _literal_aliases(sources: Mapping[str, bytes], aliases: set[str],
                     reserve_work: Callable[[int], None]) -> set[str]:
    """Conservative literal-reference veto, independent of pytest root choice.

    This does not execute/interpret non-test recipes. Even a comment mention
    can withhold proof; nothing here creates a positive relevance finding.
    Check both the declared repository cwd and a carrier-relative spelling.
    Unknown selected-command substitutions remain the closure's responsibility.
    """
    by_spelling: dict[str, set[str]] = {}
    for alias in aliases:
        by_spelling.setdefault(alias.casefold(), set()).add(alias)
    leaves = {path.rsplit("/", 1)[-1] for path in by_spelling}
    found = set()
    for source, data in sources.items():
        try:
            text = data.decode("utf-8-sig", errors="strict")
        except UnicodeError as exc:
            raise EngineError("runtime-shadow required carrier is not UTF-8") from exc
        for match in re.finditer(r"[^\s\"'`=,;()\[\]{}<>|:&]+", text):
            raw = match.group()
            reserve_work(len(raw) + 1)  # Before normalization/copies.
            raw = raw.replace("\\", "/").casefold()
            if not leaves.intersection(raw.split("/")):
                continue
            # Preserve an explicit alias suffix even with an unknown/absolute
            # prefix. This is a veto, not variable expansion or a positive
            # assertion that such an ambient prefix points into the checkout.
            delimited = "/" + raw.strip("/") + "/"
            for spelling, actual in by_spelling.items():
                reserve_work(len(delimited) + len(spelling) + 1)
                if "/" + spelling + "/" in delimited:
                    found.update(actual)
            for cwd in ("", posixpath.dirname(source)):
                path = posixpath.normpath(posixpath.join(cwd, raw)).casefold().lstrip("/")
                while path not in {"", ".", "..", "/"}:
                    reserve_work(len(path) + 1)
                    found.update(by_spelling.get(path, ()))
                    path = path.rpartition("/")[0]
    return found


def defer_optional_sources(*, evidence: PairedPytestConfigs, initial: set[str],
                           candidates: set[str], snapshot: dict,
                           config_paths, config_sources, runner_paths, conftest_paths,
                           changes, config) -> DeferredSources:
    ledger = _Ledger(initial)
    initial_configs = initial & set(config_paths)
    # Read the raw successful cache, never its future required-read interface.
    for path in initial - candidates:
        data = config_sources["after"].get(path) if path in initial_configs else snapshot.get(path)
        if not isinstance(data, bytes):
            raise EngineError("runtime-shadow snapshot read failed: " + path)
        link_bytes = evidence.records["after"][path].link_bytes if path in initial_configs else 0
        ledger.source("after", path, len(data), link_bytes)

    acquired: dict[tuple[str, str], bytes] = {}

    def required(side: str, path: str) -> bytes:
        key = side, path
        if key in acquired:
            return acquired[key]
        source = evidence.snapshots[side]
        # list_paths was prepared on this exact fixed side. These are verified
        # transport sizes, not a filename-to-mode assumption. The original
        # reader still validates mode, object identity, framing and absence.
        entry = source._tree_entries.get(path)
        if entry is not None and entry[0] in {b"100644", b"100755"}:
            ledger.source(side, path, entry[2])  # Reserve before transport.
        data = source.read_many([path]).get(path)
        if not isinstance(data, bytes):
            raise EngineError("runtime-shadow required source read failed: " + path)
        if entry is None or len(data) != entry[2]:
            raise EngineError("runtime-shadow required source changed after preflight")
        acquired[key] = data
        return data

    facts = paired_directory_link_facts(evidence.snapshots["before"], evidence.snapshots["after"],
                                       sorted(candidates), reserve_bytes=ledger.reserve_bytes,
                                       reserve_entries=ledger.reserve_work)
    proved = {path for path, fact in facts.records.items()
              if isinstance(fact, PairedDirectoryLinkFact) and _flat_data(fact)}
    # NO_PROOF is not absence. Preserve the original strict error immediately.
    for path in sorted(candidates - proved):
        snapshot[path] = required("after", path)

    contexts = {}
    for side in ("before", "after"):
        conftest_index = _conftest_index(evidence.paths[side], ledger.reserve_work)
        scoped_conftests = set(conftest_paths)
        for path in proved:
            fact = getattr(facts.records[path], side)
            for directory in (path, fact.target_path):
                scoped_conftests.update(_ancestor_conftests(
                    directory, conftest_index, ledger.reserve_work))
        sources = {}
        for path in sorted((set(runner_paths) | set(config_paths) | scoped_conftests) - proved):
            if path not in evidence.paths[side]:
                continue  # Proven absent in this fixed inventory, not a failed read.
            if path in config_sources[side]:
                data = config_sources[side][path]
                record = evidence.records[side][path]
                if not isinstance(data, bytes) or record is None:
                    raise EngineError("runtime-shadow config source lacks bytes: " + path)
                ledger.source(side, path, len(data), record.link_bytes)
            elif path in changes:
                data = changes[path].before if side == "before" else changes[path].after
                if not isinstance(data, bytes):
                    raise EngineError("runtime-shadow changed control lacks source: " + path)
                ledger.source(side, path, len(data))
            else:
                data = snapshot.get(path)
                if not isinstance(data, bytes):
                    data = required(side, path)
                # Unchanged regular controls share bytes under the existing
                # complete FileChange contract, but keep side/logical charges.
                ledger.source(side, path, len(data))
            sources[path] = data
            ledger.reserve_work(1)
        if any(_conftest_opaque(sources[path]) for path in scoped_conftests if path in sources):
            # Collection inventory's later return[] cannot justify this
            # consumer's omission. Restore its original required read now.
            for path in sorted(proved):
                snapshot[path] = required("after", path)
            proved.clear()
            break
        live = {path: data for path, data in sources.items()
                if path in config_paths or config.role_of(path) == "ci"
                or _is_runner_script(path, data, data)}
        for path in sorted(_literal_aliases(live, proved, ledger.reserve_work)):
            required(side, path)
        closure = reference_closure(sources, paths=frozenset(evidence.paths[side]),
                                    reserve_work=ledger.reserve_work,
                                    ci_paths=frozenset(path for path in sources
                                                       if config.role_of(path) == "ci"))
        contexts[side] = closure
        if not closure.complete:
            for path in sorted(proved):
                snapshot[path] = required("after", path)
            proved.clear()
            break
        for reference in closure.references:
            ledger.reserve_work(1)
            touched = {path for path in proved if _touches(reference.path, path)
                       or reference.kind not in {"collection", "config-testpaths"}
                       and (not reference.path or path.casefold().startswith(reference.path.casefold() + "/"))}
            for path in sorted(touched):
                # Even a collection target naming the alias is an explicit
                # request; flat metadata is not permission to replace it.
                required(side, path)
            if reference.kind in {"config", "coverage-config", "script", "local-action"}:
                data = sources.get(reference.path)
                if data is None:
                    data = required(side, reference.path)
                if reference.kind == "coverage-config":
                    parser = configparser.RawConfigParser(interpolation=None, strict=True)
                    try:
                        parser.read_string(data.decode("utf-8-sig", errors="strict"))
                    except (configparser.Error, UnicodeError) as exc:
                        raise EngineError("runtime-shadow coverage config could not be parsed") from exc
                    # The fixed source needs only coverage's exclusion filter.
                    # Plugins/source/dynamic settings are not proved harmless
                    # by a successful INI parse, nor interpreted as empty.
                    if (parser.defaults() or set(parser.sections()) != {"run"}
                            or set(parser.options("run")) - {"omit"}
                            or any(char in parser.get("run", "omit", fallback="")
                                   for char in "$%{}\0")):
                        for path in sorted(proved):
                            required("after", path)
                        proved.clear()
    result = DeferredSources(snapshot, proved, lambda path: required("after", path))
    result.proofs = MappingProxyType({path: facts.records[path] for path in proved})
    result.contexts = MappingProxyType(contexts)
    return result

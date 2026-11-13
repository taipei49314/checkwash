"""Repository path inventory, collision indexing, head search, and bounded snapshot reads."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Collection, Iterable, Mapping, Sequence

from checkwash.change import EngineError, FileChange
from checkwash.config import Config
from checkwash.gitio.snapshot import MAX_BATCH_BYTES, MAX_INVENTORY_PATHS, MAX_SOURCE_BYTES
from checkwash.opaque import opaque_error, same_kind, split_inventory
from checkwash.roles import _runner_shape, collectable
from checkwash.shadow_controls import (
    _DiffGateState,
    _config_search,
    _dormant_configs,
    _is_conftest_path,
    _is_package_init,
    _package_shape_change,
    _pytest_import_root,
    _sys_path_roots,
)
from checkwash.shadow_runners import (
    _could_be_extensionless_runner,
    _runner_control,
    _runner_invocation_sides,
    _scope_applies,
)
from checkwash.shadow_imports import _ShadowAnalysisCache, _match_active_test_imports
from checkwash.shadow_models import (
    HeadSearchResult,
    _PYTEST_CONFIGS,
    _join,
    _live_shadow_attr,
)
from checkwash.shadow_providers import (
    _module_from_root,
    _opaque_location,
    _path_to_modules,
    _side_paths,
    _side_source,
)

_HEAD_SEARCH_NEEDLE_BATCH = 128


def _normalized_head_search_path(path: object) -> str | None:
    """A safely normalized repository-relative path, or no attestation."""

    if not isinstance(path, str):
        return None
    normalized = path.replace("\\", "/")
    if (
        not normalized
        or normalized.startswith("/")
        or (
            len(normalized) >= 2
            and normalized[0].isalpha()
            and normalized[1] == ":"
        )
        or any(ord(char) < 32 or ord(char) == 127 for char in normalized)
    ):
        return None
    parts = normalized.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return None
    return normalized


def _complete_head_search(
    head_searcher: Callable[[list[str]], Sequence[str] | HeadSearchResult] | None,
    modules: Iterable[str],
) -> set[str] | None:
    """Return authoritative matches, or ``None`` for the fail-closed path."""

    if head_searcher is None:
        return None
    batch_size = _live_shadow_attr("_HEAD_SEARCH_NEEDLE_BATCH", _HEAD_SEARCH_NEEDLE_BATCH)
    roots = sorted({part for module in modules for part in module.split(".")})
    matches: set[str] = set()
    for start in range(0, len(roots), batch_size):
        needles = roots[start : start + batch_size]
        try:
            result = head_searcher(needles)
            if (
                not isinstance(result, HeadSearchResult)
                or result.complete is not True
            ):
                return None
            normalized = {
                _normalized_head_search_path(path)
                for path in result
            }
            if None in normalized:
                return None
            matches.update(path for path in normalized if path is not None)
        except Exception:
            # Search is only a narrowing optimisation.  An incomplete result,
            # callback error, or malformed path must retain the complete tree
            # walk below rather than becoming proof that no oracle imports it.
            return None
    return matches


@dataclass(frozen=True)
class _InventoryState:
    """Validated repository path inventory and classified control candidates."""

    inventory: list[str]
    opaque: tuple[str, ...]
    before_paths: set[str]
    after_paths: set[str]
    added_paths: set[str]
    removed_paths: set[str]
    config_paths: list[str]
    dormant_configs: frozenset[str]
    read_config_paths: list[str]
    all_conftest_paths: list[str]
    changed_runner_paths: list[str]
    runner_snapshot_paths: list[str]


def _collect_shadow_inventory(
    changes: Sequence[FileChange],
    config: Config,
    diff_state: _DiffGateState,
    *,
    head_path_lister: Callable[[], Sequence[str]] | None,
    config_evidence,
    shebang_free: Collection[str],
) -> _InventoryState:
    """List, validate, and partition repository paths and control candidates."""

    configs = _live_shadow_attr("_PYTEST_CONFIGS", _PYTEST_CONFIGS)
    raw_inventory = head_path_lister() if head_path_lister is not None else []
    if not isinstance(raw_inventory, Sequence) or isinstance(raw_inventory, (str, bytes)):
        raise EngineError("runtime-shadow inventory returned invalid paths")
    if len(raw_inventory) > 200_000:
        raise EngineError("runtime-shadow inventory exceeds the path limit")
    # A submodule is listed as a directory whose content is unknown (#335),
    # and so is a working-tree directory symlink, which keeps its kind (#414).
    raw_inventory, raw_opaque = split_inventory(raw_inventory)
    normalized_inventory = [_normalized_head_search_path(path) for path in raw_inventory]
    normalized_opaque = tuple(
        same_kind(path, _normalized_head_search_path(path)) for path in raw_opaque
    )
    if any(path is None for path in (*normalized_inventory, *normalized_opaque)):
        raise EngineError("runtime-shadow inventory returned an unsafe path")
    inventory = [path for path in normalized_inventory if path is not None]
    opaque = tuple(path for path in normalized_opaque if path is not None)

    listed = [
        path
        for path in inventory
        if path.endswith(".py")
        or path.rsplit("/", 1)[-1] in configs
        or config.role_of(path) == "ci"
        or _runner_shape(path, None, None)
        or _could_be_extensionless_runner(path)
    ]
    after_paths = set(listed)
    after_paths.update(
        path for path, c in diff_state.change_by_path.items() if c.after is not None
    )
    after_paths.difference_update(
        path for path, c in diff_state.change_by_path.items() if c.after is None
    )
    before_paths, after_paths = _side_paths(after_paths, changes)
    if config_evidence is not None:
        before_paths.update(
            config_evidence.requests["before"] & config_evidence.paths["before"]
        )
        after_paths.update(
            config_evidence.requests["after"] & config_evidence.paths["after"]
        )
    added_paths = after_paths - before_paths
    removed_paths = before_paths - after_paths

    config_paths = sorted(
        p for p in before_paths | after_paths if p.rsplit("/", 1)[-1] in configs
    )
    # A nested config under a directory that holds no collected test file on
    # either side governs nothing this pass analyses (#346). It is not read
    # up front; it is read only if a run's config discovery reaches it.
    dormant = _dormant_configs(config_paths, before_paths | after_paths)
    read_config_paths = [path for path in config_paths if path not in dormant]
    all_conftest_paths = sorted(
        p for p in before_paths | after_paths if _is_conftest_path(p)
    )
    changed_runner_paths = sorted(
        path
        for path, change in diff_state.change_by_path.items()
        if path.rsplit("/", 1)[-1] not in configs
        and (change.old_path or path).replace("\\", "/").rsplit("/", 1)[-1] not in configs
        and not _is_conftest_path(path)
        and not _is_conftest_path((change.old_path or path).replace("\\", "/"))
        and any(_runner_invocation_sides(path, change, config))
    )
    # A dot-less path is read for a shebang, its only runner shape. A path
    # set aside unread (#415) has no bytes here but the head's, which are not
    # its base side, so reading it refuses. One whose sides hold no shell
    # shebang (#455) is no runner on either side, which the read would only
    # confirm: it is skipped, so it adds no invocation, as a read would not.
    runner_snapshot_paths = sorted(
        path
        for path in before_paths | after_paths
        if path.rsplit("/", 1)[-1] not in configs
        and not _is_conftest_path(path)
        and (
            config.role_of(path) == "ci"
            or _runner_shape(path, None, None)
            or (_could_be_extensionless_runner(path) and path not in shebang_free)
        )
    )
    return _InventoryState(
        inventory=inventory,
        opaque=opaque,
        before_paths=before_paths,
        after_paths=after_paths,
        added_paths=added_paths,
        removed_paths=removed_paths,
        config_paths=config_paths,
        dormant_configs=dormant,
        read_config_paths=read_config_paths,
        all_conftest_paths=all_conftest_paths,
        changed_runner_paths=changed_runner_paths,
        runner_snapshot_paths=runner_snapshot_paths,
    )


def _collect_package_shape_modules(
    inventory_state: _InventoryState,
    diff_state: _DiffGateState,
) -> tuple[set[str], set[str]]:
    """Collect changed package-boundary ``__init__.py`` paths and affected submodules."""

    added_packages = {
        package
        for path in inventory_state.added_paths
        if _is_package_init(path)
        for package in _path_to_modules(path)
    }
    package_shape_paths: set[str] = set()
    for path, change in diff_state.change_by_path.items():
        if not _package_shape_change(path, change):
            continue
        old_path = (change.old_path or path).replace("\\", "/")
        if _is_package_init(old_path):
            package_shape_paths.add(old_path)
        if _is_package_init(path):
            package_shape_paths.add(path)
    semantic_packages = {
        package
        for path in diff_state.provisional_staged_paths
        if _is_package_init(path)
        for package in _path_to_modules(path)
    }
    shape_packages = added_packages | semantic_packages | {
        package
        for path in package_shape_paths
        for package in _path_to_modules(path)
    }
    affected_modules: set[str] = set()
    if shape_packages:
        for path in sorted(inventory_state.after_paths | inventory_state.before_paths):
            for module in _path_to_modules(path):
                parts = module.split(".")
                if any(
                    ".".join(parts[:i]) in shape_packages
                    for i in range(1, len(parts))
                ):
                    affected_modules.add(module)
    return package_shape_paths, affected_modules


def _collect_changed_search_roots(
    inventory_state: _InventoryState,
    diff_state: _DiffGateState,
    package_shape_paths: set[str],
    config: Config,
) -> set[str]:
    """Collect search roots introduced, removed, or reordered by changed controls."""

    configs = _live_shadow_attr("_PYTEST_CONFIGS", _PYTEST_CONFIGS)
    changed_roots: set[str] = {""} if diff_state.search_order_changed else set()
    import_mode_changed = False
    for path, change in sorted(diff_state.control_changes.items()):
        old_path = (change.old_path or path).replace("\\", "/")
        old_config = old_path.rsplit("/", 1)[-1] in configs
        new_config = path.rsplit("/", 1)[-1] in configs
        if old_config or new_config:
            before_search = (
                _config_search(old_path, change.before) if old_config else ((), "prepend")
            )
            after_search = (
                _config_search(path, change.after) if new_config else ((), "prepend")
            )
            changed_roots.update(before_search[0])
            changed_roots.update(after_search[0])
            import_mode_changed |= before_search[1] != after_search[1]
            continue
        old_conftest = _is_conftest_path(old_path)
        new_conftest = _is_conftest_path(path)
        if old_conftest or new_conftest:
            if old_conftest:
                changed_roots.update(_sys_path_roots(old_path, change.before))
            if new_conftest:
                changed_roots.update(_sys_path_roots(path, change.after))
            continue
        if path in inventory_state.changed_runner_paths and _runner_control(
            path, change, config
        ):
            before_invocations, after_invocations = _runner_invocation_sides(
                path, change, config
            )
            for invocation in (*before_invocations, *after_invocations):
                changed_roots.update(invocation.roots)
            import_mode_changed |= tuple(item.mode for item in before_invocations) != tuple(
                item.mode for item in after_invocations
            )
    if import_mode_changed or package_shape_paths:
        for path in sorted(inventory_state.before_paths | inventory_state.after_paths):
            if collectable(path):
                changed_roots.add(_pytest_import_root(path, inventory_state.before_paths))
                changed_roots.add(_pytest_import_root(path, inventory_state.after_paths))
    return changed_roots


@dataclass(frozen=True)
class _CandidateModulesState:
    """Candidate modules surviving collision and lazy AST-equivalence checks."""

    modules: set[str]
    provider_index: dict[str, set[str]]
    package_shape_paths: set[str]
    staged_candidate_paths: set[str]


def _discover_colliding_candidates(
    inventory_state: _InventoryState,
    diff_state: _DiffGateState,
    config: Config,
    third_party: set[str],
    analysis: _ShadowAnalysisCache,
) -> _CandidateModulesState | None:
    """Build the provider collision index and filter two-commit plant candidates lazily."""

    modules: set[str] = set()
    for path in sorted(
        inventory_state.added_paths
        | inventory_state.removed_paths
        | diff_state.provisional_staged_paths
    ):
        modules |= _path_to_modules(path)
    if diff_state.changed_config_paths or any(
        _is_conftest_path(path)
        or _is_conftest_path(diff_state.control_changes[path].old_path or path)
        for path in diff_state.changed_control_paths
    ):
        for path in sorted(inventory_state.after_paths | inventory_state.before_paths):
            modules.update(_path_to_modules(path))

    package_shape_paths, shape_modules = _collect_package_shape_modules(
        inventory_state, diff_state
    )
    modules.update(shape_modules)
    changed_roots = _collect_changed_search_roots(
        inventory_state, diff_state, package_shape_paths, config
    )

    by_module: dict[str, set[str]] = {}
    for root in sorted(changed_roots):
        for path in sorted(inventory_state.after_paths | inventory_state.before_paths):
            module = _module_from_root(path, root)
            if module is not None:
                by_module.setdefault(module, set()).add(path)
    modules.update(module for module, providers in by_module.items() if len(providers) > 1)
    modules = {m for m in modules if m and m.split(".", 1)[0] not in third_party}

    indexed_modules = set(modules)
    for module in modules:
        parts = module.split(".")
        indexed_modules.update(".".join(parts[:i]) for i in range(1, len(parts)))
    provider_index: dict[str, set[str]] = {}
    for path in sorted(inventory_state.before_paths | inventory_state.after_paths):
        for module in _path_to_modules(path) & indexed_modules:
            provider_index.setdefault(module, set()).add(path)

    # Discard ordinary new modules before reading any source, unless another
    # provider may lie inside an opaque submodule (#335).
    modules = {
        module
        for module in modules
        if len(provider_index.get(module, ())) > 1
        or any(
            _opaque_location(_join(root, module.replace(".", "/")), inventory_state.opaque)
            for root in changed_roots | {""}
        )
    }
    if not modules:
        return None

    indexed_survivors = set(modules)
    for module in modules:
        parts = module.split(".")
        indexed_survivors.update(
            ".".join(parts[:index]) for index in range(1, len(parts))
        )
    staged_candidate_paths = {
        path
        for path in diff_state.provisional_staged_paths
        if (
            _path_to_modules(path) & indexed_survivors
            and analysis.source_key(diff_state.change_by_path[path].before)
            != analysis.source_key(diff_state.change_by_path[path].after)
        )
    }
    if not diff_state.normally_relevant and not staged_candidate_paths:
        return None
    return _CandidateModulesState(
        modules=modules,
        provider_index=provider_index,
        package_shape_paths=package_shape_paths,
        staged_candidate_paths=staged_candidate_paths,
    )


def _verify_opaque_collection_unreached(
    inventory_state: _InventoryState,
    changes: Sequence[FileChange],
    head_batch_reader: Callable[[Sequence[str]], Mapping[str, bytes | None]] | None,
) -> None:
    """Refuse when pytest's collection can reach an opaque submodule or directory link (#335)."""

    if not inventory_state.opaque or head_batch_reader is None:
        return
    from checkwash.collection_inventory import collection_sources, opaque_reached

    sources = collection_sources(inventory_state.inventory)
    head = head_batch_reader(sources) if sources else {}
    if not isinstance(head, Mapping):
        raise EngineError("runtime-shadow snapshot returned invalid source bytes")
    reached = opaque_reached(
        inventory_state.opaque,
        {path: head[path] for path in sources if isinstance(head.get(path), bytes)},
        changes,
    )
    if reached is not None:
        raise opaque_error(reached, "pytest's collection can reach it")


@dataclass(frozen=True)
class _ShortlistState:
    """Shortlisted candidate test modules and ancestor conftests."""

    eligible_tests: set[str]
    test_paths: list[str]
    conftest_paths: list[str]


def _shortlist_candidate_tests(
    inventory_state: _InventoryState,
    modules: set[str],
    changes: Sequence[FileChange],
    *,
    head_searcher: Callable[[list[str]], Sequence[str] | HeadSearchResult] | None,
    head_batch_reader: Callable[[Sequence[str]], Mapping[str, bytes | None]] | None,
) -> _ShortlistState | None:
    """Narrow candidate test modules via complete head search and conftest scope closure."""

    search = _live_shadow_attr("_complete_head_search", _complete_head_search)
    presearched = search(head_searcher, modules)
    if presearched is not None and not presearched:
        return None

    _verify_opaque_collection_unreached(inventory_state, changes, head_batch_reader)

    eligible_tests = {path for path in inventory_state.after_paths if collectable(path)}
    if presearched is None:
        test_paths = sorted(eligible_tests)
    else:
        matched_conftests = {
            path
            for path in presearched
            if path in inventory_state.after_paths and _is_conftest_path(path)
        }
        test_paths = sorted(
            (eligible_tests & presearched)
            | {
                test_path
                for test_path in eligible_tests
                if any(
                    _scope_applies(conftest.rpartition("/")[0], test_path)
                    for conftest in matched_conftests
                )
            }
        )
    if not test_paths:
        return None
    conftest_paths = [
        path
        for path in inventory_state.all_conftest_paths
        if any(_scope_applies(path.rpartition("/")[0], test_path) for test_path in test_paths)
    ]
    return _ShortlistState(
        eligible_tests=eligible_tests,
        test_paths=test_paths,
        conftest_paths=conftest_paths,
    )


def _validate_split_config_budget(
    initial_requests: set[str],
    config_paths: Sequence[str],
    config_sources: Mapping[str, Mapping[str, bytes | None]],
    snapshot: Mapping[str, bytes | None],
    config_evidence,
) -> None:
    """Enforce path and byte caps across split config_evidence and initial snapshot reads."""

    max_paths = _live_shadow_attr("MAX_INVENTORY_PATHS", MAX_INVENTORY_PATHS)
    max_source = _live_shadow_attr("MAX_SOURCE_BYTES", MAX_SOURCE_BYTES)
    max_batch = _live_shadow_attr("MAX_BATCH_BYTES", MAX_BATCH_BYTES)

    initial_configs = initial_requests & set(config_paths)
    combined = {
        path: (
            config_sources["after"].get(path)
            if path in initial_configs
            else snapshot.get(path)
        )
        for path in initial_requests
    }
    missing = sorted(path for path, data in combined.items() if not isinstance(data, bytes))
    if missing:
        raise EngineError("runtime-shadow snapshot read failed: " + ", ".join(missing[:3]))
    link_bytes = sum(
        config_evidence.records["after"][path].link_bytes for path in initial_configs
    )
    if len(combined) > max_paths:
        raise EngineError("runtime-shadow initial snapshot exceeds the source read limit")
    if (
        any(len(data) > max_source for data in combined.values())
        or sum(map(len, combined.values())) + link_bytes > max_batch
    ):
        raise EngineError("runtime-shadow initial snapshot exceeds the source byte limit")


@dataclass
class _InitialSnapshotState:
    """Phase-1 snapshot contents and lazy dormant-config source reader."""

    snapshot: dict[str, bytes | None]
    config_sources: dict[str, dict[str, bytes | None]]
    dormant_configs: frozenset[str]
    side_change_by_path: Mapping[str, FileChange]
    config_evidence: object
    head_batch_reader: Callable[[Sequence[str]], Mapping[str, bytes | None]] | None

    def _read_dormant_config(self, path: str, side: str) -> None:
        if self.config_evidence is not None:
            if path not in self.config_sources[side]:
                self.config_sources[side].update(self.config_evidence.sources(side, [path]))
            return
        if (
            path in self.side_change_by_path
            or path in self.snapshot
            or self.head_batch_reader is None
        ):
            return
        read = self.head_batch_reader([path])
        if not isinstance(read, Mapping) or not isinstance(read.get(path), bytes):
            raise EngineError("runtime-shadow snapshot read failed: " + path)
        self.snapshot[path] = read[path]

    def config_source(self, path: str, side: str) -> bytes | None:
        if path in self.dormant_configs:
            self._read_dormant_config(path, side)
        if self.config_evidence is not None and path in self.config_sources[side]:
            return self.config_sources[side][path]
        return _side_source(path, side, self.side_change_by_path, self.snapshot)


def _read_initial_snapshot(
    inventory_state: _InventoryState,
    diff_state: _DiffGateState,
    shortlist: _ShortlistState,
    *,
    head_batch_reader: Callable[[Sequence[str]], Mapping[str, bytes | None]] | None,
    config_evidence,
) -> _InitialSnapshotState:
    """Execute bounded phase-1 batch read of candidate tests and controls."""

    initial_requests = (
        {
            *shortlist.test_paths,
            *shortlist.conftest_paths,
            *inventory_state.runner_snapshot_paths,
            *inventory_state.read_config_paths,
        }
        - set(diff_state.side_change_by_path)
    )
    initial_reads = sorted(
        initial_requests - set(inventory_state.config_paths)
        if config_evidence is not None
        else initial_requests
    )
    snapshot: dict[str, bytes | None] = {}
    if initial_reads and head_batch_reader is not None:
        read = head_batch_reader(initial_reads)
        if not isinstance(read, Mapping) or any(
            path in read and read[path] is not None and not isinstance(read[path], bytes)
            for path in initial_reads
        ):
            raise EngineError("runtime-shadow snapshot returned invalid source bytes")
        missing = [path for path in initial_reads if read.get(path) is None]
        if missing:
            raise EngineError(
                "runtime-shadow snapshot read failed: " + ", ".join(missing[:3])
            )
        snapshot.update(read)
    for path, change in diff_state.change_by_path.items():
        if change.after is not None:
            snapshot[path] = change.after

    config_sources: dict[str, dict[str, bytes | None]] = {}
    if config_evidence is not None:
        for side in ("before", "after"):
            config_sources[side] = dict(
                config_evidence.sources(side, inventory_state.read_config_paths)
            )
        _validate_split_config_budget(
            initial_requests,
            inventory_state.config_paths,
            config_sources,
            snapshot,
            config_evidence,
        )

    return _InitialSnapshotState(
        snapshot=snapshot,
        config_sources=config_sources,
        dormant_configs=inventory_state.dormant_configs,
        side_change_by_path=diff_state.side_change_by_path,
        config_evidence=config_evidence,
        head_batch_reader=head_batch_reader,
    )


def _read_provider_batch(
    provider_reads: Sequence[str],
    snapshot: dict[str, bytes | None],
    head_batch_reader: Callable[[Sequence[str]], Mapping[str, bytes | None]] | None,
) -> None:
    """Execute bounded phase-2 batch read for surviving provider sources."""

    if not provider_reads or head_batch_reader is None:
        return
    read = head_batch_reader(provider_reads)
    if not isinstance(read, Mapping) or any(
        path in read and read[path] is not None and not isinstance(read[path], bytes)
        for path in provider_reads
    ):
        raise EngineError("runtime-shadow provider returned invalid source bytes")
    missing = [path for path in provider_reads if read.get(path) is None]
    if missing:
        raise EngineError(
            "runtime-shadow provider read failed: " + ", ".join(missing[:3])
        )
    snapshot.update(read)


@dataclass(frozen=True)
class _ActiveProvidersState:
    """Surviving per-test imports and resolved provider source maps."""

    imported_by_test: dict[str, set[str]]
    module_paths: dict[str, tuple[set[str], set[str]]]
    contents: dict[str, bytes | None]
    before_contents: dict[str, bytes | None]


def _resolve_active_providers(
    inventory_state: _InventoryState,
    diff_state: _DiffGateState,
    candidate_state: _CandidateModulesState,
    shortlist: _ShortlistState,
    snapshot_state: _InitialSnapshotState,
    analysis: _ShadowAnalysisCache,
    *,
    head_batch_reader: Callable[[Sequence[str]], Mapping[str, bytes | None]] | None,
) -> _ActiveProvidersState | None:
    """Match active test imports on both sides and load exact provider sources."""

    imported_by_test, active_modules = _match_active_test_imports(
        shortlist.test_paths,
        shortlist.conftest_paths,
        inventory_state.before_paths,
        inventory_state.after_paths,
        diff_state.change_by_path,
        diff_state.side_change_by_path,
        snapshot_state.snapshot,
        candidate_state.modules,
        analysis,
    )
    if not active_modules:
        return None

    module_paths: dict[str, tuple[set[str], set[str]]] = {}
    provider_paths: set[str] = set()
    for module in active_modules:
        relevant = set(candidate_state.provider_index.get(module, ()))
        parts = module.split(".")
        for i in range(1, len(parts)):
            relevant.update(
                path
                for path in candidate_state.provider_index.get(".".join(parts[:i]), ())
                if path.endswith("/__init__.py")
            )
        provider_paths.update(relevant)
        module_paths[module] = (
            relevant & inventory_state.before_paths,
            relevant & inventory_state.after_paths,
        )

    provider_reads = sorted(
        provider_paths
        - set(diff_state.side_change_by_path)
        - set(snapshot_state.snapshot)
    )
    _read_provider_batch(provider_reads, snapshot_state.snapshot, head_batch_reader)

    contents = {path: snapshot_state.snapshot.get(path) for path in provider_paths}
    before_contents = {
        path: (
            diff_state.side_change_by_path[path].before
            if path in diff_state.side_change_by_path
            and diff_state.side_change_by_path[path].before is not None
            else snapshot_state.snapshot.get(path)
        )
        for path in provider_paths
    }
    return _ActiveProvidersState(
        imported_by_test=imported_by_test,
        module_paths=module_paths,
        contents=contents,
        before_contents=before_contents,
    )

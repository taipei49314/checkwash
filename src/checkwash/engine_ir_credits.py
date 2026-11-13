"""IR pipeline stage 4: relocation context proofs, D2 move credits, and D10 duplicate survivors."""

from __future__ import annotations

import hashlib
import sys
from collections import Counter
from typing import TYPE_CHECKING, Any

from checkwash.change import EngineError, FileChange
from checkwash.frontends.python.frontend import ParsedFile
from checkwash.ir.model import IR, judged_as_test, normalize_text
from checkwash.report.context import ReportContext

if TYPE_CHECKING:
    import types
    from checkwash.engine_ir_resolvers import ConftestChainResolver, HeadCollectionResolver

_CONTEXT_UNKNOWN = object()


def _eng() -> types.ModuleType:
    mod = sys.modules.get("checkwash.engine")
    if mod is None:
        import checkwash.engine as mod
    return mod


class RelocationContextResolver:
    """Bounded side-exact snapshot & startup context proof resolver for relocated oracles."""

    def __init__(
        self,
        changes: list[FileChange],
        expanded_changes: list[FileChange],
        *,
        chain_resolver: ConftestChainResolver,
        root_reader: Any,
        root_searcher: Any,
        root_path_lister: Any,
        report_context: ReportContext | None,
    ) -> None:
        self.chain_resolver = chain_resolver
        self.root_reader = root_reader
        self.root_searcher = root_searcher
        self.root_path_lister = root_path_lister
        self.report_context = report_context
        self.relocation_sources = {
            change.path.replace("\\", "/"): (change.before, change.after)
            for change in expanded_changes
        }
        self.relocation_initializers: dict[tuple[str, int], bytes | None] = {}
        self.relocation_context_sources: dict[tuple[str, int], Any] = {}
        self.relocation_context_bytes = 0
        self.relocation_context_inventory: dict[int, Any] = {}
        self.relocation_context_paths: dict[int, Any] = {}
        self.relocation_side_observations: dict[tuple[str, int], list[tuple[bytes | None, bool]]] = {}
        rename_sources = {
            (change.old_path or change.path).replace("\\", "/")
            for change in changes
            if change.old_path
            and change.old_path.replace("\\", "/") != change.path.replace("\\", "/")
        }
        for change in changes:
            path = change.path.replace("\\", "/")
            old = (change.old_path or path).replace("\\", "/")
            if old != path:
                observations = (
                    (old, 0, change.before, False),
                    (path, 1, change.after, False),
                    (path, 0, None, True),
                    (old, 1, None, True),
                )
            else:
                inferred = (
                    change.status == "added" and path in rename_sources and change.before is None
                )
                observations = ((path, 0, change.before, inferred), (path, 1, change.after, False))
            for candidate, side, data, inferred in observations:
                self.relocation_side_observations.setdefault((candidate, side), []).append(
                    (data, inferred)
                )

    def observed_source(self, candidate: str, side: int) -> bytes | None:
        observations = self.relocation_side_observations[(candidate, side)]
        actual = [data for data, inferred in observations if not inferred]
        if not actual:
            return None
        value = actual[0]
        if any(data != value for data in actual[1:]):
            raise ValueError("conflicting optional oracle-context source observations")
        return value

    def context_source(self, candidate: str, side: int) -> bytes | None:
        """Optional proof reads use their actual side; unchanged paths use HEAD."""
        if (
            not isinstance(candidate, str)
            or not candidate
            or "\\" in candidate
            or ":" in candidate
            or "\0" in candidate
            or any(part in {"", ".", ".."} for part in candidate.split("/"))
        ):
            raise ValueError("invalid optional oracle-context source path")
        if self.root_reader is None:
            raise ValueError("optional oracle context requires a strict snapshot")
        changed = (candidate, side) in self.relocation_side_observations
        key = (candidate, side if changed else -1)
        if key not in self.relocation_context_sources:
            if len(self.relocation_context_sources) >= 256:
                raise ValueError("optional oracle-context source read budget exhausted")
            self.relocation_context_sources[key] = _CONTEXT_UNKNOWN
            if self.relocation_context_bytes >= 2 * 1024 * 1024:
                raise ValueError("optional oracle-context source byte budget exhausted")
            data = (
                self.observed_source(candidate, side)
                if changed
                else self.root_reader(candidate)
            )
            if data is not None and not isinstance(data, bytes):
                raise ValueError("optional oracle-context source is unknown or too large")
            if data is not None:
                self.relocation_context_bytes += len(data)
                if len(data) > 65536:
                    raise ValueError("optional oracle-context source is unknown or too large")
                if self.relocation_context_bytes > 2 * 1024 * 1024:
                    raise ValueError("optional oracle-context source byte budget exhausted")
                if self.report_context is not None:
                    for recorded_side in (0, 1) if key[1] == -1 else (side,):
                        self.report_context.snapshot(candidate, recorded_side, data)
            self.relocation_context_sources[key] = data
        if self.relocation_context_sources[key] is _CONTEXT_UNKNOWN:
            raise ValueError("optional oracle-context source remains unknown")
        return self.relocation_context_sources[key]

    def context_search(self, needles: list[str], side: int) -> list[str]:
        """Reconstruct the complete nonempty Python inventory on the actual side."""
        if needles != [""] or self.root_searcher is None:
            raise ValueError("optional oracle context requires a strict source inventory")
        if side not in self.relocation_context_inventory:
            self.relocation_context_inventory[side] = _CONTEXT_UNKNOWN
            if -1 not in self.relocation_context_inventory:
                self.relocation_context_inventory[-1] = _CONTEXT_UNKNOWN
                paths = self.root_searcher([""])
                if not isinstance(paths, (list, tuple)) or len(paths) >= 64:
                    raise ValueError("optional oracle-context inventory is unknown or too large")
                normalized = set()
                for candidate in paths:
                    if not isinstance(candidate, str):
                        raise ValueError("invalid optional oracle-context inventory path")
                    candidate = candidate.replace("\\", "/")
                    if (
                        not candidate.endswith(".py")
                        or ":" in candidate
                        or "\0" in candidate
                        or any(
                            part in {"", ".", ".."} or any(ord(c) < 32 for c in part)
                            for part in candidate.split("/")
                        )
                        or candidate in normalized
                    ):
                        raise ValueError("invalid optional oracle-context inventory path")
                    normalized.add(candidate)
                self.relocation_context_inventory[-1] = frozenset(normalized)
            paths = self.relocation_context_inventory[-1]
            if paths is _CONTEXT_UNKNOWN:
                raise ValueError("optional oracle-context inventory remains unknown")
            selected = set(paths)
            changed_paths = {
                candidate
                for candidate, observed_side in self.relocation_side_observations
                if observed_side == side and candidate.endswith(".py")
            }
            for candidate in sorted(changed_paths):
                data = self.context_source(candidate, side)
                selected.discard(candidate)
                if data:
                    selected.add(candidate)
            if len(selected) >= 64:
                raise ValueError("optional oracle-context inventory is too large")
            self.relocation_context_inventory[side] = tuple(sorted(selected))
        if self.relocation_context_inventory[side] is _CONTEXT_UNKNOWN:
            raise ValueError("optional oracle-context inventory remains unknown")
        return list(self.relocation_context_inventory[side])

    def context_path_list(self, side: int) -> list[str]:
        """Complete side-correct entry names also cover non-Python aliases."""
        if self.root_path_lister is None:
            raise ValueError("optional oracle context requires complete path metadata")
        if side not in self.relocation_context_paths:
            self.relocation_context_paths[side] = _CONTEXT_UNKNOWN
            if -1 not in self.relocation_context_paths:
                self.relocation_context_paths[-1] = _CONTEXT_UNKNOWN
                paths = self.root_path_lister()
                if not isinstance(paths, (list, tuple)) or len(paths) > 512:
                    raise ValueError(
                        "optional oracle-context path metadata is unknown or too large"
                    )
                normalized = set()
                for candidate in paths:
                    if not isinstance(candidate, str):
                        raise ValueError("invalid optional oracle-context metadata path")
                    candidate = candidate.replace("\\", "/")
                    if (
                        ":" in candidate
                        or any(
                            part in {"", ".", ".."} or any(ord(c) < 32 for c in part)
                            for part in candidate.split("/")
                        )
                        or candidate in normalized
                    ):
                        raise ValueError("invalid optional oracle-context metadata path")
                    normalized.add(candidate)
                self.relocation_context_paths[-1] = frozenset(normalized)
            paths = self.relocation_context_paths[-1]
            if paths is _CONTEXT_UNKNOWN:
                raise ValueError("optional oracle-context path metadata remains unknown")
            selected = set(paths)
            for candidate, observed_side in sorted(self.relocation_side_observations):
                if observed_side != side:
                    continue
                data = self.observed_source(candidate, side)
                if data is not None and not isinstance(data, bytes):
                    raise ValueError("optional oracle-context entry presence is unknown")
                selected.discard(candidate)
                if data is not None:
                    selected.add(candidate)
            if len(selected) > 512:
                raise ValueError("optional oracle-context path metadata is too large")
            self.relocation_context_paths[side] = tuple(sorted(selected))
        if self.relocation_context_paths[side] is _CONTEXT_UNKNOWN:
            raise ValueError("optional oracle-context path metadata remains unknown")
        return list(self.relocation_context_paths[side])

    def startup(self, path: str, side: int, data: bytes | None) -> str | None:
        """Hash proof of equal ancestor conftests and package `__init__.py` initializers."""
        if data is None:
            return None
        proof = []
        for level in self.chain_resolver.conftest_chain(path, side, data):
            if level.star or level.adds_marks:
                return None
            source = self.chain_resolver.level_source(level.path, side)
            if source is None or b"request" in source:
                return None
            proof.append((level.path, hashlib.sha256(source.replace(b"\r\n", b"\n")).hexdigest()))
        parts = path.split("/")[:-1]
        if len(parts) > 16 or self.root_reader is None:
            return None
        for depth in range(len(parts), -1, -1):
            initializer = "/".join([*parts[:depth], "__init__.py"])
            key = (initializer, side if initializer in self.relocation_sources else -1)
            if key not in self.relocation_initializers:
                if len(self.relocation_initializers) >= 64:
                    return None
                if initializer in self.relocation_sources:
                    source = self.relocation_sources[initializer][side]
                else:
                    try:
                        source = self.root_reader(initializer)
                    except (EngineError, OSError, ValueError, TypeError):
                        return None
                if source is not None and (not isinstance(source, bytes) or len(source) > 65536):
                    return None
                self.relocation_initializers[key] = source
                if source is not None and self.report_context is not None:
                    for recorded_side in (0, 1) if key[1] == -1 else (side,):
                        self.report_context.snapshot(initializer, recorded_side, source)
            source = self.relocation_initializers[key]
            if source:
                proof.append(
                    (initializer, hashlib.sha256(source.replace(b"\r\n", b"\n")).hexdigest())
                )
        return repr(proof)

    def side_callbacks(self, side_index: int) -> tuple[Any, Any, Any]:
        """Bind `(source_reader, source_searcher, source_path_lister)` for `side_index`."""
        reader = (
            (lambda candidate: self.context_source(candidate, side_index))
            if self.root_reader is not None
            else None
        )
        searcher = (
            (lambda needles: self.context_search(needles, side_index))
            if self.root_searcher is not None
            else None
        )
        lister = (
            (lambda: self.context_path_list(side_index))
            if self.root_path_lister is not None
            else None
        )
        return reader, searcher, lister

    def mark_ir_file_contexts(self, ir: IR) -> None:
        """Populate `oracle_context` and `oracle_assertion_contexts` across changed files."""
        eng = _eng()
        for file in ir.files:
            needed = {
                unit.qualname
                for unit in file.units
                if unit.before is None
                or unit.after is None
                or (
                    unit.delta is not None
                    and (unit.delta.assertions_removed or unit.delta.assertions_added)
                )
            }
            if not needed:
                continue
            sources = self.relocation_sources.get(file.path, (None, None))
            for side_index, field in enumerate(("before", "after")):
                data = sources[side_index]
                sides = [
                    (unit.qualname, getattr(unit, field))
                    for unit in file.units
                    if getattr(unit, field) is not None
                ]
                startup = (
                    self.startup(file.path, side_index, data)
                    if file.language == "python"
                    else ""
                )
                source_reader, source_searcher, source_path_lister = self.side_callbacks(
                    side_index
                )
                eng.mark_contexts(
                    data,
                    sides,
                    file.path,
                    file.language,
                    startup_known=startup is not None,
                    startup=startup,
                    needed=needed,
                    source_reader=source_reader,
                    source_searcher=source_searcher,
                    source_path_lister=source_path_lister,
                )


def record_move_credits(
    ir: IR,
    js_head_runners: dict[str, frozenset[str] | None],
    head_collection: HeadCollectionResolver,
    relocation_sources: dict[str, tuple[bytes | None, bytes | None]],
) -> None:
    """Count multiset assertion/unit move credits (D2) across live collected destinations."""
    eng = _eng()
    g = ir.globals
    removed_texts: Counter[str] = Counter()
    added_texts: Counter[str] = Counter()
    removed_units: Counter[str] = Counter()
    added_units: Counter[str] = Counter()
    payable = any(
        unit.before is not None
        and (
            unit.after is None
            or (unit.delta is not None and unit.delta.assertions_removed)
        )
        for file in ir.files
        for unit in file.units
    )
    for file in ir.files:
        constants = file.constants
        js_collected = file.path not in js_head_runners or eng.collected(
            file.path, js_head_runners[file.path],
        )
        python_test = payable and file.language == "python" and judged_as_test(file)
        for unit in file.units:
            live_after = (
                unit.after is not None
                and js_collected
                and eng.unit_is_live(unit.after, constants)
            )
            if (
                live_after
                and python_test
                and (
                    unit.before is None
                    or (unit.delta is not None and unit.delta.assertions_added)
                )
            ):
                live_after = head_collection.collected(
                    file.path,
                    unit.qualname,
                    relocation_sources.get(file.path, (None, None))[1],
                )
            if unit.after is not None and not live_after:
                unit.after.oracle_context = ""
                unit.after.oracle_assertion_contexts = {}
            if unit.delta is not None and unit.before is not None and unit.after is not None:
                b_by_id = {a.id: a for a in unit.before.assertions}
                a_by_id = {a.id: a for a in unit.after.assertions}
                for aid in unit.delta.assertions_removed:
                    if aid in b_by_id:
                        removed_texts[normalize_text(b_by_id[aid].text)] += 1
                if live_after:
                    for aid in unit.delta.assertions_added:
                        if aid in a_by_id and a_by_id[aid].via is None:
                            added_texts[normalize_text(a_by_id[aid].text)] += 1
            elif unit.before is not None and unit.after is None:
                for a in unit.before.assertions:
                    if a.via is None:
                        removed_texts[normalize_text(a.text)] += 1
                if unit.before.body_hash:
                    removed_units[unit.before.body_hash] += 1
            elif unit.after is not None and unit.before is None:
                if live_after:
                    for a in unit.after.assertions:
                        if a.via is None:
                            added_texts[normalize_text(a.text)] += 1
                    if unit.after.body_hash:
                        added_units[unit.after.body_hash] += 1

    moved = removed_texts & added_texts
    g.moved_assertion_texts = sorted(moved.elements())
    g.moved_unit_hashes = sorted((removed_units & added_units).elements())


def record_duplicate_survivors(
    ir: IR,
    *,
    head_searcher: Any,
    head_reader: Any,
    chain_resolver: ConftestChainResolver,
    after_by_path: dict[str, ParsedFile],
    relocation_resolver: RelocationContextResolver,
    head_collection: HeadCollectionResolver,
) -> None:
    """Find disappeared units whose identical live collected body survives untouched at head (D10)."""
    if head_searcher is None or head_reader is None:
        return
    eng = _eng()
    wanted: set[str] = set()
    needles: set[str] = set()
    for file in ir.files:
        if not judged_as_test(file) and file.role != "conftest":
            continue
        for unit in file.units:
            if unit.before is not None and unit.after is None and unit.before.body_hash:
                h = unit.before.oracle_context
                if not h:
                    continue
                if any(
                    u.before is None and u.after is not None and u.after.oracle_context == h
                    for candidate in ir.files
                    for u in candidate.units
                ):
                    continue
                wanted.add(h)
                leaf = unit.qualname.rsplit(".", 1)[-1].split("#", 1)[0]
                needles.add(f"def {leaf}(")
    if not wanted:
        return
    diff_paths = {f.path for f in ir.files}
    candidates = sorted(
        p.replace("\\", "/")
        for p in head_searcher(sorted(needles))
        if p.replace("\\", "/") not in diff_paths
        and p.endswith(".py")
        and eng.collectable(p.replace("\\", "/"))
    )
    found: set[str] = set()
    source_reader, source_searcher, source_path_lister = relocation_resolver.side_callbacks(1)
    for path in candidates[: eng._MAX_DUP_READS]:
        data = head_reader(path)
        if data is None:
            continue
        parsed = eng.parse_python(
            data,
            collect_tests=True,
            chain=chain_resolver.conftest_chain(path, 1, data),
            imported=chain_resolver.imported_helpers(path, 1),
        )
        if not parsed.parse_ok:
            continue
        consts = eng._gate_constants(parsed, after_by_path, head_reader)
        startup = relocation_resolver.startup(path, 1, data)
        eng.mark_contexts(
            data,
            [(pu.qualname, pu.side) for pu in parsed.units],
            path,
            "python",
            startup_known=startup is not None,
            startup=startup,
            source_reader=source_reader,
            source_searcher=source_searcher,
            source_path_lister=source_path_lister,
        )
        for pu in parsed.units:
            if (
                pu.side.oracle_context in wanted
                and eng.unit_is_live(pu.side, consts)
                and head_collection.collected(path, pu.qualname, data)
            ):
                found.add(pu.side.oracle_context)
    ir.globals.duplicate_unit_hashes = sorted(found)

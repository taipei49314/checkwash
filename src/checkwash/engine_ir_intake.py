"""IR pipeline stage 1: diff intake guards, helper importer expansion, and global surface setup."""

from __future__ import annotations

import sys
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.conftest_context import ConftestContext
from checkwash.ir.model import IR, DiffGlobals
from checkwash.pyenv import known_baseline
from checkwash.report.context import ReportContext

if TYPE_CHECKING:
    import types


def _eng() -> types.ModuleType:
    mod = sys.modules.get("checkwash.engine")
    if mod is None:
        import checkwash.engine as mod
    return mod


@dataclass
class DiffIntake:
    """Prepared diff change list and guarded snapshot readers."""

    changes: list[FileChange]
    unread_changes: list[FileChange]
    root_reader: Any
    head_reader: Any
    root_batch_reader: Any
    importer_reads: int
    reviewed_root_modules: set[str]


@dataclass
class GlobalSurface:
    """Initial IR, DiffGlobals, runtime shadow state, and CI/collection surfaces."""

    ir: IR
    config_evidence: Any
    shadow_evidence_paths: set[str]
    resolvable: set[str] | None
    one_hop: Any
    ci_base: Any
    config_report_changes: dict[str, FileChange]
    raw_by_path: dict[str, tuple[bytes | None, bytes | None]]
    conftest_context: ConftestContext
    rename_destinations: dict[str, str]


def prepare_diff_intake(
    changes: list[FileChange],
    config: Config,
    scope_allow: list[str] | None,
    *,
    head_reader=None,
    report_context: ReportContext | None = None,
    root_reader=None,
    root_searcher=None,
    root_path_lister=None,
    root_batch_reader=None,
) -> DiffIntake:
    """Filter oversized/link changes, guard snapshot readers, and expand helper importers."""
    eng = _eng()
    allowed = scope_allow or []
    changes, unread_changes = eng._set_aside_unread(changes, config, allowed, root_reader)
    # Absent from `changes`, a set-aside path would read as unchanged (#415).
    root_reader = eng._guard_unread_reads(root_reader, unread_changes)
    head_reader = eng._guard_unread_reads(head_reader, unread_changes)
    root_batch_reader = eng._guard_unread_reads(root_batch_reader, unread_changes, batch=True)
    # After unread sides so #456's Stop-hook size block still wins over a refused link (D-208).
    changes, _linked = eng._set_aside_links(
        changes, config, allowed, root_reader, root_path_lister, root_batch_reader,
    )
    importer_changes, importer_reads, reviewed_root_modules = eng._root_importer_changes(
        changes, config, root_reader, root_searcher, root_path_lister,
    )
    changes = [*changes, *importer_changes]
    # The expected-value pass is additive and bounded: past its bounds it
    # reads none of a helper's importers and says so (D-206), but only in a
    # run that reports what it says. A run without a report context (sweep,
    # bench, demo) keeps the engine error. The root-helper channel above,
    # which reviews removed assertions, keeps its engine errors too.
    set_aside: list[str] | None = [] if report_context is not None else None
    changes = [
        *changes,
        *eng.expected_importer_changes(
            changes, config, root_reader, root_searcher, reviewed_root_modules, skipped=set_aside,
        ),
    ]
    if report_context is not None:
        report_context.importer_gaps.extend(set_aside)
    return DiffIntake(
        changes=changes,
        unread_changes=unread_changes,
        root_reader=root_reader,
        head_reader=head_reader,
        root_batch_reader=root_batch_reader,
        importer_reads=importer_reads,
        reviewed_root_modules=reviewed_root_modules,
    )


def _third_party_roots(
    changes: list[FileChange],
    unread_changes: list[FileChange],
    known_modules: set[str] | None,
    self_modules: set[str] | None,
) -> tuple[str, ...]:
    """Someone else's code = declared, minus the project's own name and repo top-level dirs."""
    if known_modules is None:
        return ()
    repo_roots = {
        part[:-3] if part.endswith(".py") else part
        for change in (*changes, *unread_changes)
        for part in change.path.replace("\\", "/").split("/")
    }
    return tuple(
        sorted(set(known_modules) - set(self_modules or ()) - repo_roots - known_baseline())
    )


def _resolvable_modules(
    changes: list[FileChange],
    known_modules: set[str] | None,
) -> set[str] | None:
    """Imports already present on the base side or diff paths; only new imports can be hallucinated."""
    if known_modules is None:
        return None
    resolvable = set(known_modules)
    for change in changes:
        for part in change.path.replace("\\", "/").split("/"):
            resolvable.add(part[:-3] if part.endswith(".py") else part)
    return resolvable


def _record_runtime_shadows(
    g: DiffGlobals,
    changes: list[FileChange],
    unread_changes: list[FileChange],
    config: Config,
    root_path_lister,
    root_batch_reader,
    config_evidence,
) -> set[str]:
    """Evaluate runtime subject shadows, map logical-to-physical config controls, and collect evidence paths."""
    eng = _eng()
    shadow_hits = eng.find_runtime_subject_shadows(
        changes,
        config,
        g.third_party_roots,
        head_path_lister=root_path_lister,
        head_batch_reader=root_batch_reader,
        include_equivalent=True,
        config_evidence=config_evidence,
        shebang_free=eng._shebang_free(unread_changes),
    )
    if config_evidence is not None:
        reported_hits = []
        for hit in shadow_hits:
            controls = set(hit.control_paths)
            finding_path = hit.finding_path
            contexts = []
            for logical in sorted(controls & config_evidence.changes.keys()):
                reported = config_evidence.reported_change(logical, changes)
                if reported is not None:
                    physical, context = reported
                    controls.add(physical.path)
                    contexts.append(context)
                    if finding_path == logical:
                        finding_path = physical.path
            reported_hits.append(
                replace(
                    hit,
                    finding_path=finding_path,
                    trigger="; ".join([hit.trigger, *contexts]),
                    control_paths=tuple(sorted(controls)),
                )
            )
        shadow_hits = reported_hits
    g.runtime_subject_shadows = [
        (
            hit.finding_path,
            hit.module,
            hit.before_provider,
            hit.after_provider,
            hit.test_path,
            hit.trigger,
        )
        for hit in shadow_hits
        if hit.reportable
    ]
    return {
        path
        for hit in shadow_hits
        for path in (
            hit.after_provider,
            *hit.after_chain,
            *hit.related_evidence_paths,
            *hit.control_paths,
            hit.trigger,
        )
    }


def _record_collection_and_ci_surface(
    g: DiffGlobals,
    changes: list[FileChange],
    config: Config,
    head_reader,
    root_path_lister,
    root_batch_reader,
    config_evidence,
    shadow_evidence_paths: set[str],
) -> tuple[Any, Any, dict[str, FileChange]]:
    """Compute CI base surface and record collection-inventory narrowing events."""
    eng = _eng()
    # Computed once, before anything is judged: E6 needs to know what the
    # ci surface already said, not just what this diff added to it.
    one_hop = eng._one_hop_runners(changes, config, head_reader)
    ci_base = eng._ci_base_surface(changes, config, one_hop)
    collection_events = eng.collection_inventory_changes(
        changes,
        config,
        path_lister=root_path_lister,
        batch_reader=root_batch_reader,
        config_evidence=config_evidence,
    )
    config_report_changes: dict[str, FileChange] = {}
    for path, reason in collection_events:
        reported = (
            config_evidence.reported_change(path, changes)
            if config_evidence is not None
            else None
        )
        if reported is not None:
            physical, context = reported
            path = physical.path
            reason = reason + "; " + context
            config_report_changes[path] = physical
            shadow_evidence_paths.add(path)
            if physical.old_path:
                shadow_evidence_paths.add(physical.old_path)
        g.ci_weakening_lines.append((path, reason))
    return one_hop, ci_base, config_report_changes


def initialize_global_surface(
    intake: DiffIntake,
    config: Config,
    *,
    base_label: str,
    head_label: str,
    scope_allow: list[str] | None,
    known_modules: set[str] | None,
    self_modules: set[str] | None,
    pytest_configs=None,
    root_path_lister=None,
) -> GlobalSurface:
    """Create IR + DiffGlobals and run global shadow, CI-base, and collection passes."""
    eng = _eng()
    g = DiffGlobals()
    g.scope_allow = sorted(scope_allow or [])
    if known_modules is not None:
        g.third_party_roots = _third_party_roots(
            intake.changes, intake.unread_changes, known_modules, self_modules,
        )
    ir = IR(base=base_label, head=head_label, globals=g)
    config_evidence = pytest_configs.prepare() if pytest_configs is not None else None
    shadow_evidence_paths = _record_runtime_shadows(
        g,
        intake.changes,
        intake.unread_changes,
        config,
        root_path_lister,
        intake.root_batch_reader,
        config_evidence,
    )
    resolvable = _resolvable_modules(intake.changes, known_modules)
    one_hop, ci_base, config_report_changes = _record_collection_and_ci_surface(
        g,
        intake.changes,
        config,
        intake.head_reader,
        root_path_lister,
        intake.root_batch_reader,
        config_evidence,
        shadow_evidence_paths,
    )
    # Cross-file oracle resolution (A5-x) parses helper files straight from
    # the change bytes, memoised — never from the loop's parse cache, so it
    # cannot depend on the order sorted() happens to visit paths in.
    raw_by_path: dict[str, tuple[bytes | None, bytes | None]] = {
        c.path.replace("\\", "/"): (c.before, c.after) for c in intake.changes
    }
    conftest_context = eng.ConftestContext(intake.changes, intake.root_reader)
    rename_destinations = {
        c.old_path.replace("\\", "/"): c.path.replace("\\", "/")
        for c in intake.changes
        if c.old_path
    }
    return GlobalSurface(
        ir=ir,
        config_evidence=config_evidence,
        shadow_evidence_paths=shadow_evidence_paths,
        resolvable=resolvable,
        one_hop=one_hop,
        ci_base=ci_base,
        config_report_changes=config_report_changes,
        raw_by_path=raw_by_path,
        conftest_context=conftest_context,
        rename_destinations=rename_destinations,
    )

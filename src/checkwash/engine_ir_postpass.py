"""IR pipeline stage 5: stand-in installations, equivalence/provenance passes, and config evidence."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

from checkwash.change import EngineError, FileChange
from checkwash.config import Config
from checkwash.ir.model import IR
from checkwash.report.context import ReportContext

if TYPE_CHECKING:
    import types


def _eng() -> types.ModuleType:
    mod = sys.modules.get("checkwash.engine")
    if mod is None:
        import checkwash.engine as mod
    return mod


def record_standin_installations(
    ir: IR,
    changes: list[FileChange],
    unread_changes: list[FileChange],
    config: Config,
    *,
    root_reader: Any = None,
    root_searcher: Any = None,
    root_path_lister: Any = None,
) -> None:
    """Collect Python and JS stand-in/subject replacement events onto `ir.globals`."""
    eng = _eng()
    g = ir.globals
    for path, unit, target, text, span in eng.installation_events(
        ir,
        changes,
        config,
        root_reader=root_reader,
        root_searcher=root_searcher,
        root_path_lister=root_path_lister,
    ):
        if unit is None:
            if (path, text) not in g.conftest_prod_patches:
                g.conftest_prod_patches.append((path, text))
        else:
            g.subject_installations.append((path, unit, target, text, span))
    python_standin_passes = (
        lambda: eng.subject_replacement_events(
            ir,
            changes,
            root_reader=root_reader,
            root_searcher=root_searcher,
            root_path_lister=root_path_lister,
        ),
        lambda: eng.callable_fixture_subject_events(
            ir, changes, root_reader=root_reader, root_searcher=root_searcher,
        ),
        lambda: eng.local_parameter_implementation_events(
            ir, changes, root_reader=root_reader, root_searcher=root_searcher,
        ),
        lambda: eng.fixture_local_implementation_events(
            ir, changes, root_reader=root_reader, root_searcher=root_searcher,
        ),
        lambda: eng.parametrized_string_standin_events(
            ir, changes, root_reader=root_reader, root_searcher=root_searcher,
        ),
    )
    for event_source in python_standin_passes:
        for event in event_source():
            if event not in g.subject_installations:
                g.subject_installations.append(event)
    read_tsconfig = eng._base_root_file(changes, root_reader, "tsconfig.json", unread_changes)
    for event in eng.module_mock_events(ir, changes, read_tsconfig):
        if event not in g.subject_installations:
            g.subject_installations.append(event)
    for event in eng.setup_file_events(
        changes, eng._base_manifest(changes, root_reader, unread_changes), read_tsconfig,
    ):
        if event not in g.subject_installations:
            g.subject_installations.append(event)


def mark_equivalence_and_provenance(
    ir: IR,
    raw_by_path: dict[str, tuple[bytes | None, bytes | None]],
    root_reader: Any,
    root_searcher: Any,
    config: Config,
    report_context: ReportContext | None,
    strict_head_oracle_sources: dict[str, bytes | None],
) -> None:
    """Run post-alignment table/parameter/normalization equivalence and expected-value provenance."""
    eng = _eng()
    eng.mark_table_normalization(ir, raw_by_path, root_reader, root_searcher)
    eng.mark_param_input_identity(ir, raw_by_path, root_reader)
    eng.mark_normalization_equivalence(ir, raw_by_path, root_reader, root_searcher)
    eng.mark_expected_provenance(
        ir,
        raw_by_path,
        root_reader,
        config.role_of,
        report_context,
        strict_head_oracle_sources,
        root_searcher,
    )
    eng.mark_js_expected_provenance(ir, raw_by_path)


def attach_config_report_evidence(
    ir: IR,
    config_report_changes: dict[str, FileChange],
    rename_destinations: dict[str, str],
) -> None:
    """Attach physical target file evidence for logical pytest config narrowing findings."""
    eng = _eng()
    g = ir.globals
    files_by_path = {file.path: file for file in ir.files}
    for path, change in sorted(config_report_changes.items()):
        if path not in files_by_path:
            raise EngineError(f"pytest config physical change has no file evidence: path={path!r}")
        if files_by_path[path].status != change.status:
            raise EngineError(
                f"pytest config physical change has incompatible file evidence: path={path!r}"
            )
        files_by_path[path].change_evidence = eng._change_evidence(change, rename_destinations)
        if path not in g.ci_files_changed:
            g.ci_files_changed.append(path)

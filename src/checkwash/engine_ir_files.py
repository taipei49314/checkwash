"""IR pipeline stage 3: per-file classification, parsing, alignment, and DiffGlobals recording."""

from __future__ import annotations

import sys
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.frontends.python.frontend import ParsedFile
from checkwash.ir.model import DiffGlobals, FileIR, IR, Marker, judged_as_test, normalize_text
from checkwash.report.context import ReportContext

if TYPE_CHECKING:
    import types
    from checkwash.engine_ir_intake import DiffIntake, GlobalSurface
    from checkwash.engine_ir_resolvers import (
        ConftestChainResolver,
        CrossfileOracleResolver,
        HeadCollectionResolver,
    )


def _eng() -> types.ModuleType:
    mod = sys.modules.get("checkwash.engine")
    if mod is None:
        import checkwash.engine as mod
    return mod


@dataclass
class FilePassResult:
    """Outputs of the per-file parsing, alignment, and DiffGlobals pass."""

    expanded_changes: list[FileChange]
    after_by_path: dict[str, ParsedFile]
    before_by_path: dict[str, ParsedFile]
    js_head_runners: dict[str, frozenset[str] | None]


def _classify_file_change(
    path: str,
    change: FileChange,
    config: Config,
    one_hop: Any,
) -> tuple[str, str, bool, bool, bool, bool]:
    """Resolve `(role, table_role, is_python, is_js_test, test_obligations, judged_test)`."""
    eng = _eng()
    role = config.role_of(path)
    if role == "prod" and (
        eng._is_runner_script(path, change.before, change.after, change.old_path)
        or path in one_hop
        or eng._test_commands_changed(path, change.before, change.after)
    ):
        role = "ci"
    is_python = path.endswith(".py")
    table_role = role
    is_js_test = eng.is_js_test_file(path, change.before, change.after)
    if eng._js_test(path, role, change.before, change.after):
        role = "test"
    elif role == "prod" and eng.is_test_support_path(path):
        role = "test"
    test_obligations = (is_js_test or (is_python and eng.collectable(path))) and role != "test"
    judged_test = role == "test" or test_obligations
    return role, table_role, is_python, is_js_test, test_obligations, judged_test


def _project_modified_python_test_pair(
    path: str,
    change: FileChange,
    before_parsed: ParsedFile,
    after_parsed: ParsedFile,
    root_reader: Any,
    root_searcher: Any,
    changes: list[FileChange],
) -> tuple[ParsedFile, ParsedFile]:
    """Run the 11 in-place Python modified-test pair projections in pipeline order."""
    eng = _eng()
    passes = (
        eng.mark_classic_exception_removal,
        eng.mark_empty_parameter_introduction,
        eng.mark_neutralizing_aliases,
        eng.mark_empty_length_guards,
        eng.mark_class_exception_aliases,
        eng.mark_function_exception_aliases,
        eng.mark_type_comparisons,
        eng.mark_builtin_normalizations,
        eng.mark_literal_all,
        eng.project_manual_unittest_suites,
        eng.project_table_consolidation,
    )
    for projector in passes:
        before_parsed, after_parsed = projector(
            change.before,
            change.after,
            before_parsed,
            after_parsed,
            path=path,
            root_reader=root_reader,
            root_searcher=root_searcher,
            changes=changes,
        )
    return before_parsed, after_parsed


def _parse_and_record_sides(
    path: str,
    change: FileChange,
    role: str,
    is_python: bool,
    is_js_test: bool,
    judged_test: bool,
    manifest: Any,
    chain_resolver: ConftestChainResolver,
    intake: DiffIntake,
    root_searcher: Any,
    report_context: ReportContext | None,
    before_by_path: dict[str, ParsedFile],
    after_by_path: dict[str, ParsedFile],
) -> tuple[ParsedFile | None, ParsedFile | None, bool]:
    """Parse before/after sides, run Python pair projections, and record report snapshots."""
    eng = _eng()
    before_parsed: ParsedFile | None = None
    after_parsed: ParsedFile | None = None
    collect = False
    if is_python:
        is_conftest = role == "conftest"
        collect = is_conftest or (judged_test and eng.collectable(path))
        reaches_chain = (
            collect
            and not is_conftest
            and change.synthetic not in ("root_helper_importer", "expected_provenance_importer")
        )
        if change.before is not None:
            before_path = (change.old_path or path).replace("\\", "/")
            before_parsed = eng.parse_python(
                change.before,
                collect_tests=collect,
                conftest=is_conftest,
                chain=chain_resolver.conftest_chain(before_path, 0, change.before)
                if reaches_chain
                else (),
                imported=chain_resolver.imported_helpers(before_path, 0)
                if reaches_chain
                else None,
            )
        if change.after is not None:
            after_parsed = eng.parse_python(
                change.after,
                collect_tests=collect,
                conftest=is_conftest,
                chain=chain_resolver.conftest_chain(path, 1, change.after)
                if reaches_chain
                else (),
                imported=chain_resolver.imported_helpers(path, 1)
                if reaches_chain
                else None,
            )
    elif is_js_test:
        if change.before is not None:
            before_parsed = eng.parse_javascript(
                change.before, eng._innermost_focus(change.before, manifest),
            )
        if change.after is not None:
            after_parsed = eng.parse_javascript(
                change.after, eng._innermost_focus(change.after, manifest),
            )

    if (
        is_python
        and judged_test
        and collect
        and change.status == "modified"
        and change.old_path is None
        and before_parsed is not None
        and after_parsed is not None
    ):
        before_parsed, after_parsed = _project_modified_python_test_pair(
            path,
            change,
            before_parsed,
            after_parsed,
            intake.root_reader,
            root_searcher,
            intake.changes,
        )

    if report_context is not None:
        if is_js_test:
            report_context.javascript_coverage(path, 0, change.before, before_parsed)
            report_context.javascript_coverage(path, 1, change.after, after_parsed)
        if is_python or is_js_test:
            report_context.snapshot(path, 0, change.before)
            report_context.snapshot(path, 1, change.after)
        report_context.parsed(path, 0, before_parsed)
        report_context.parsed(path, 1, after_parsed)

    if after_parsed is not None and after_parsed.parse_ok:
        after_by_path[path] = after_parsed
    if before_parsed is not None and before_parsed.parse_ok:
        before_by_path[path] = before_parsed
    return before_parsed, after_parsed, collect


def _align_and_attach_file_ir(
    path: str,
    change: FileChange,
    role: str,
    is_python: bool,
    is_js_test: bool,
    test_obligations: bool,
    judged_test: bool,
    collect: bool,
    single_context_change: bool,
    before_parsed: ParsedFile | None,
    after_parsed: ParsedFile | None,
    manifest: Any,
    surface: GlobalSurface,
    intake: DiffIntake,
    root_searcher: Any,
    oracle_resolver: CrossfileOracleResolver,
    before_by_path: dict[str, ParsedFile],
    js_head_runners: dict[str, frozenset[str] | None],
) -> FileIR:
    """Merge cross-file oracles, align file sides into `FileIR`, and attach file-level metadata."""
    eng = _eng()
    g = surface.ir.globals
    native_context_unchanged = False
    if (
        single_context_change
        and change.old_path is None
        and is_python
        and (judged_test or role == "conftest")
    ):
        before_context = eng._native_assertion_context(change.before, before_parsed)
        after_context = eng._native_assertion_context(change.after, after_parsed)
        native_context_unchanged = (
            before_context is not None
            and after_context is not None
            and before_context[0] == after_context[0]
            and sum(b != a for b, a in zip(before_context[1], after_context[1])) <= 1
        )

    if is_python and judged_test and collect:
        eng.project_truthiness_oracles(
            path,
            before_parsed,
            after_parsed,
            surface.raw_by_path,
            intake.root_reader,
            root_searcher,
        )
        if before_parsed is not None:
            oracle_resolver.merge_crossfile_oracles(path, before_parsed, 0, before_by_path)
        if after_parsed is not None:
            oracle_resolver.merge_crossfile_oracles(path, after_parsed, 1, before_by_path)

    file_ir = eng.align_file(path, role, change.status, before_parsed, after_parsed)
    file_ir.test_obligations = test_obligations
    file_ir.native_assertion_context_unchanged = native_context_unchanged
    if is_js_test and change.after is not None:
        head_runners = eng.runner_evidence(change.after, manifest)
        js_head_runners[path] = head_runners
        focus = after_parsed.focus if after_parsed is not None and after_parsed.parse_ok else None
        had_focus = before_parsed is not None and before_parsed.focus is not None
        if (
            focus is not None
            and not had_focus
            and change.synthetic != "renamed_from_test"
            and not eng.focus_is_file_scoped(head_runners)
        ):
            file_ir.suite_focus_added = Marker(
                name="test.focused", text=focus.text, span=focus.span,
            )
    if (judged_test or role == "conftest") and path.endswith(".py"):
        from checkwash.frontends.python.constant_renames import literal_constant_renames

        file_ir.module_constant_renames = literal_constant_renames(change.before, change.after)
    if role in ("ci", "guardrail"):
        file_ir.change_evidence = eng._change_evidence(change, surface.rename_destinations)
    parsed_for_helpers = (
        after_parsed if after_parsed and after_parsed.parse_ok else before_parsed
    )
    if parsed_for_helpers is not None and parsed_for_helpers.parse_ok:
        file_ir.helper_calls = dict(parsed_for_helpers.helper_calls)
    surface.ir.files.append(file_ir)
    if is_python and not file_ir.parse_ok:
        surface.ir.skipped_files.append(path)
        if (judged_test or role == "conftest") and change.status != "deleted":
            was_parseable = before_parsed is not None and before_parsed.parse_ok
            g.unparseable_tests.append((path, was_parseable))
            file_ir.change_evidence = eng._change_evidence(change, surface.rename_destinations)
    return file_ir


def _record_test_and_cross_cutting_globals(
    g: DiffGlobals,
    path: str,
    change: FileChange,
    role: str,
    table_role: str,
    judged_test: bool,
    file_ir: FileIR,
    before_parsed: ParsedFile | None,
    after_parsed: ParsedFile | None,
    surface: GlobalSurface,
) -> None:
    """Record test imports, test logic changes, scope drift, hidden unicode, deps, and conftest patches."""
    eng = _eng()
    if (judged_test or role == "conftest") and after_parsed and after_parsed.parse_ok:
        g.test_file_imports[path] = list(after_parsed.imports)
    elif (
        (judged_test or role == "conftest")
        and after_parsed is None
        and before_parsed
        and before_parsed.parse_ok
    ):
        g.test_file_imports[path] = list(before_parsed.imports)
    if judged_test or role == "conftest":
        for unit in file_ir.units:
            if unit.before is None or unit.after is None:
                g.test_logic_changed = True
            elif unit.delta is not None:
                b_by_id = {a.id: a for a in unit.before.assertions}
                a_by_id = {a.id: a for a in unit.after.assertions}
                edited = any(
                    (b := b_by_id.get(p.before_id)) is not None
                    and (a := a_by_id.get(p.after_id)) is not None
                    and normalize_text(b.text) != normalize_text(a.text)
                    for p in unit.delta.assertion_pairs
                )
                if edited or (
                    unit.delta.assertions_removed
                    or unit.delta.assertions_added
                    or unit.delta.markers_added
                    or unit.delta.param_cases_removed
                ):
                    g.test_logic_changed = True

    if (
        change.synthetic not in ("root_helper_importer", "expected_provenance_importer")
        and g.scope_allow
        and not any(eng._scope_match(path, glob) for glob in g.scope_allow)
    ):
        g.scope_drift.append((path, eng._scope_role(role, table_role, before_parsed, after_parsed)))
        if file_ir.change_evidence is None:
            file_ir.change_evidence = eng._change_evidence(change, surface.rename_destinations)

    if judged_test or role in ("conftest", "prod", "ci", "guardrail"):
        eng._scan_hidden_unicode(g, path, change.before, change.after)

    if path in eng.MANIFESTS and eng._deps_differ(change.before, change.after, path):
        g.dependency_manifest_changed = True

    if role == "conftest" and change.after is not None:
        mod_name = eng._module_of(path)
        before_patches = (
            set(
                eng.conftest_patch_targets(
                    change.before,
                    module_exists=lambda module: surface.conftest_context.contains(module, 0),
                    module_name=mod_name,
                )
            )
            if change.before is not None
            else set()
        )
        for text in eng.conftest_patch_targets(
            change.after,
            module_exists=lambda module: surface.conftest_context.contains(module, 1),
            module_name=mod_name,
        ):
            if text not in before_patches:
                g.conftest_prod_patches.append((path, text))


def _record_prod_change(
    g: DiffGlobals,
    path: str,
    change: FileChange,
    config: Config,
    is_python: bool,
    before_parsed: ParsedFile | None,
    after_parsed: ParsedFile | None,
    shadow_evidence_paths: set[str],
) -> None:
    """Record production file symbol, caller, literal, deletion, and opacity evidence."""
    eng = _eng()
    g.prod_files_changed.append(path)
    package = eng._module_of(path)
    if path in shadow_evidence_paths:
        return
    if is_python and before_parsed and after_parsed and before_parsed.parse_ok and after_parsed.parse_ok:
        for q in sorted(set(before_parsed.symbols) | set(after_parsed.symbols)):
            if before_parsed.symbols.get(q) != after_parsed.symbols.get(q):
                g.prod_symbols_changed.append(f"{package}::{q}")
                if q in before_parsed.symbols and q not in after_parsed.symbols:
                    parts = q.split(".")
                    prefixes = (".".join(parts[:i]) for i in range(1, len(parts)))
                    if not any(p in after_parsed.symbols for p in prefixes):
                        g.prod_symbols_deleted.append(f"{package}::{q}")
                if q in before_parsed.symbols and q in after_parsed.symbols:
                    g.prod_packages.append(package)
        eng._record_callers(g, after_parsed, g.prod_symbols_changed)
        g.new_literals_in_prod.extend(sorted(after_parsed.literals - before_parsed.literals))
    elif is_python and change.status == "added" and after_parsed and after_parsed.parse_ok:
        new_symbols = [f"{package}::{q}" for q in sorted(after_parsed.symbols)]
        g.prod_symbols_changed.extend(new_symbols)
        g.prod_symbols_in_added_files.extend(new_symbols)
        eng._record_callers(g, after_parsed, g.prod_symbols_changed)
        g.new_literals_in_prod.extend(sorted(after_parsed.literals))
    elif (
        is_python
        and change.status == "deleted"
        and before_parsed is not None
        and before_parsed.parse_ok
    ):
        for q in sorted(before_parsed.symbols):
            g.prod_symbols_changed.append(f"{package}::{q}")
            g.prod_symbols_deleted.append(f"{package}::{q}")
    elif eng.is_artifact(path) or eng._is_inert(path):
        pass
    else:
        old_path = (change.old_path or path).replace("\\", "/")
        self_inflicted = (
            is_python
            and before_parsed is not None
            and before_parsed.parse_ok
            and (after_parsed is None or not after_parsed.parse_ok)
        )
        if (
            change.before
            and change.after
            and change.before != change.after
            and config.role_of(old_path) == "prod"
            and not eng.is_test_support_path(old_path)
            and not self_inflicted
            and not eng._mentions_test_runner(change)
        ):
            g.prod_opaque_change = True


def _record_non_prod_role_change(
    g: DiffGlobals,
    path: str,
    change: FileChange,
    role: str,
    test_obligations: bool,
    file_ir: FileIR,
    surface: GlobalSurface,
    policy_base: Any,
) -> None:
    """Record guardrail, CI, and snapshot role evidence on `DiffGlobals`."""
    eng = _eng()
    if role == "guardrail":
        shadow = eng.shadow_baseline(change, policy_base)
        if path in (".checkwash/allow.toml", ".greenwash/allow.toml"):
            before_policy = shadow[0] if shadow is not None else change.before
            appended = eng._classify_allowlist_change(before_policy, change.after)
            if shadow is not None:
                g.policy_shadows[path] = {
                    **shadow[1],
                    "kind": "allow_append" if appended is not None else "allow_rewrite",
                }
            if appended is not None:
                g.exemptions_added.extend(appended)
                g.exemption_ledger_path = path
            else:
                g.guardrail_files_changed.append(path)
        else:
            g.guardrail_files_changed.append(path)
            if shadow is not None:
                g.policy_shadows[path] = {
                    **shadow[1],
                    "kind": eng.config_transition(shadow[0], change.after),
                }
        if not change.before:
            g.guardrail_files_created.append(path)
            if (
                shadow is None
                and path in eng._OWN_CONFIG_PATHS
                and eng._created_config_loosens(change.after)
            ):
                g.guardrail_configs_created_loosening.append(path)
    elif role == "ci" and test_obligations:
        g.ci_files_changed.append(path)
    elif role == "ci":
        g.ci_files_changed.append(path)
        if (
            change.status == "deleted"
            and eng._is_ci_workflow(path)
            and (
                eng._runs_tests(change.before, path)
                or eng.holds_runner_site(path, change.before)
            )
        ):
            g.ci_weakening_lines.append((path, "workflow file removed"))
        eng._scan_ci_weakening(
            g, path, change.before, change.after, surface.ci_base, change.old_path,
        )
    elif role == "snapshot":
        g.snapshot_files_changed.append(path)
        if change.status == "modified":
            file_ir.change_evidence = eng._change_evidence(change, surface.rename_destinations)


def _record_syntax_hygiene_globals(
    g: DiffGlobals,
    path: str,
    change: FileChange,
    role: str,
    is_python: bool,
    is_js_test: bool,
    judged_test: bool,
    before_parsed: ParsedFile | None,
    after_parsed: ParsedFile | None,
    resolvable: set[str] | None,
    base_literals: set[str],
) -> None:
    """Record base literals, added suppressions, added/unresolved imports, and broad handlers."""
    eng = _eng()
    if is_python and before_parsed is not None and before_parsed.parse_ok:
        base_literals.update(before_parsed.literals)

    if is_python:
        before_sup = eng._suppression_texts(before_parsed)
        after_sup = eng._suppression_texts(after_parsed)
        for text, count in (after_sup - before_sup).items():
            g.suppressions_added.extend([f"{path}:{text}"] * count)
        if (
            before_parsed is not None
            and after_parsed is not None
            and before_parsed.parse_ok
            and after_parsed.parse_ok
        ):
            added_imports = sorted(set(after_parsed.imports) - set(before_parsed.imports))
        elif change.status == "added" and after_parsed is not None and after_parsed.parse_ok:
            added_imports = sorted(set(after_parsed.imports))
        else:
            added_imports = []
        for module in added_imports:
            g.imports_added.append(f"{path}:{module}")
            if resolvable is not None and module.split(".", 1)[0] not in resolvable:
                g.unresolved_imports.append((path, module))

    if is_python or is_js_test:
        def _handlers(parsed: ParsedFile | None) -> tuple[str, ...]:
            if parsed is None or not parsed.parse_ok:
                return ()
            if judged_test or role == "conftest":
                return parsed.swallowing_handlers
            return parsed.broad_handlers

        before_broad = Counter(_handlers(before_parsed))
        after_broad = Counter(_handlers(after_parsed))
        added = after_broad - before_broad
        after_relays = Counter(
            after_parsed.relay_handlers
            if after_parsed is not None
            and after_parsed.parse_ok
            and (judged_test or role == "conftest")
            else ()
        )
        if added and after_relays:
            added &= after_broad - after_relays
        for text, count in sorted(added.items()):
            g.broad_excepts_added.extend([(path, text)] * count)


def _finalize_file_globals_and_constants(
    ir: IR,
    expanded_changes: list[FileChange],
    rename_destinations: dict[str, str],
    base_literals: set[str],
    before_by_path: dict[str, ParsedFile],
    after_by_path: dict[str, ParsedFile],
    head_reader: Any,
) -> None:
    """Sort DiffGlobals collections, hash snapshot companions, and resolve D6 constant environments."""
    eng = _eng()
    g = ir.globals
    g.base_literals = sorted(base_literals)
    g.prod_packages = sorted(set(g.prod_packages))
    g.suppressions_added.sort()
    g.imports_added.sort()
    g.unresolved_imports.sort()
    g.broad_excepts_added.sort()
    g.ci_weakening_lines.sort()
    g.hidden_unicode.sort()
    g.scope_drift.sort()
    g.exemptions_added.sort()

    if g.snapshot_files_changed and g.prod_files_changed and not g.test_logic_changed:
        paths = set(g.snapshot_files_changed) | set(g.prod_files_changed)
        selected_changes = {
            c.path.replace("\\", "/"): c
            for c in expanded_changes
            if c.path.replace("\\", "/") in paths
        }
        for file in ir.files:
            if file.path in paths and file.change_evidence is None:
                file.change_evidence = eng._change_evidence(
                    selected_changes[file.path], rename_destinations,
                )

    for file in ir.files:
        parsed = after_by_path.get(file.path)
        if (judged_as_test(file) or file.role == "conftest") and parsed is not None:
            file.constants = eng._gate_constants(parsed, after_by_path, head_reader)
            file.fixture_defs = dict(parsed.fixture_defs)
            file.module_constants = eng._canonical_constants(parsed.constants)
            before = before_by_path.get(file.path)
            if before is not None:
                file.constants_before = eng._gate_constants(before, before_by_path, None)
                file.fixture_defs_before = dict(before.fixture_defs)
                file.module_constants_before = eng._canonical_constants(before.constants)
                eng._mark_weakened_guards(file)


def populate_files_and_globals(
    surface: GlobalSurface,
    intake: DiffIntake,
    config: Config,
    *,
    chain_resolver: ConftestChainResolver,
    oracle_resolver: CrossfileOracleResolver,
    head_collection: HeadCollectionResolver,
    root_searcher: Any = None,
    report_context: ReportContext | None = None,
    policy_base: Any = None,
) -> FilePassResult:
    """Expand renames, classify and parse every changed file, align FileIRs, and record DiffGlobals."""
    eng = _eng()
    g = surface.ir.globals
    manifest = eng._base_manifest(intake.changes, intake.root_reader, intake.unread_changes)
    expanded_changes = sorted(
        eng._expand_renames(intake.changes, config, manifest, head_collection.excludes),
        key=lambda c: c.path,
    )
    js_head_runners: dict[str, frozenset[str] | None] = {}
    after_by_path: dict[str, ParsedFile] = {}
    before_by_path: dict[str, ParsedFile] = {}
    base_literals: set[str] = set()
    single_context_change = (
        sum(not eng.is_artifact(c.path) for c in (*intake.changes, *intake.unread_changes)) == 1
    )

    for change in expanded_changes:
        path = change.path.replace("\\", "/")
        if eng.is_artifact(path):
            continue
        role, table_role, is_python, is_js_test, test_obligations, judged_test = (
            _classify_file_change(path, change, config, surface.one_hop)
        )
        before_parsed, after_parsed, collect = _parse_and_record_sides(
            path, change, role, is_python, is_js_test, judged_test,
            manifest, chain_resolver, intake, root_searcher, report_context,
            before_by_path, after_by_path,
        )
        file_ir = _align_and_attach_file_ir(
            path, change, role, is_python, is_js_test, test_obligations, judged_test, collect,
            single_context_change, before_parsed, after_parsed, manifest, surface, intake,
            root_searcher, oracle_resolver, before_by_path, js_head_runners,
        )
        _record_test_and_cross_cutting_globals(
            g, path, change, role, table_role, judged_test,
            file_ir, before_parsed, after_parsed, surface,
        )
        if change.synthetic == "renamed_from_test":
            pass
        elif role == "prod":
            _record_prod_change(
                g, path, change, config, is_python,
                before_parsed, after_parsed, surface.shadow_evidence_paths,
            )
        else:
            _record_non_prod_role_change(
                g, path, change, role, test_obligations, file_ir, surface, policy_base,
            )
        _record_syntax_hygiene_globals(
            g, path, change, role, is_python, is_js_test, judged_test,
            before_parsed, after_parsed, surface.resolvable, base_literals,
        )

    _finalize_file_globals_and_constants(
        surface.ir, expanded_changes, surface.rename_destinations,
        base_literals, before_by_path, after_by_path, intake.head_reader,
    )
    return FilePassResult(
        expanded_changes=expanded_changes,
        after_by_path=after_by_path,
        before_by_path=before_by_path,
        js_head_runners=js_head_runners,
    )

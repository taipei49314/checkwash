"""First-party provenance verification, deduplication, and SubjectShadow emission."""

from __future__ import annotations

from dataclasses import replace

from checkwash.config import Config
from checkwash.shadow_controls import (
    _ControlInvocations,
    _DiffGateState,
    _build_test_search_plans,
    _is_conftest_path,
    _plan_roots,
)
from checkwash.shadow_imports import _ShadowAnalysisCache
from checkwash.shadow_inventory import (
    _ActiveProvidersState,
    _CandidateModulesState,
    _InitialSnapshotState,
    _InventoryState,
    _ShortlistState,
)
from checkwash.shadow_models import SearchPlan, SubjectShadow, _live_shadow_attr
from checkwash.shadow_providers import (
    _changed_provider,
    _package_init_paths,
    _plan_provider_entries,
    _provider_package_chain,
    _selected_provider,
)
from checkwash.shadow_runners import _scope_applies


def _is_reportable_first_party_shadow(
    module: str,
    scoped: SearchPlan,
    before_provider: str,
    after_provider: str,
    before_key: tuple[tuple[str, str], ...],
    after_key: tuple[tuple[str, str], ...],
    before_module_paths: set[str],
    after_module_paths: set[str],
    before_contents: dict[str, bytes | None],
    contents: dict[str, bytes | None],
    config: Config,
    analysis: _ShadowAnalysisCache,
) -> bool | None:
    """Verify first-party ``prod`` provenance and return reportability (or ``None`` to skip)."""

    if before_provider == after_provider:
        # The selected path was already first in search order. It belongs to
        # this family only when a first-party alternate had the same execution
        # key immediately before this edit.
        canonical_after_keys = [
            analysis.provider_execution_key(
                module,
                (root, path),
                after_module_paths,
                contents,
            )
            for root, path in _plan_provider_entries(
                module,
                scoped.before_roots,
                before_module_paths,
            )
            if path != before_provider
            and path in after_module_paths
            and config.role_of(path) == "prod"
            and analysis.provider_execution_key(
                module,
                (root, path),
                before_module_paths,
                before_contents,
            )
            == before_key
        ]
        if not canonical_after_keys:
            return None
        return any(
            key is not None and key != after_key for key in canonical_after_keys
        )

    if config.role_of(before_provider) != "prod":
        return None
    # An executable-equivalent location/search-order switch is retained only
    # for evidence exclusion, not reported.
    return before_key != after_key


def _attribute_shadow_hit(
    *,
    test_path: str,
    module: str,
    plan: SearchPlan,
    before_provider: str,
    after_provider: str,
    after_root: str,
    reportable: bool,
    inventory_state: _InventoryState,
    diff_state: _DiffGateState,
    candidate_state: _CandidateModulesState,
) -> tuple[tuple[str, str], SubjectShadow]:
    """Attribute trigger, finding_path, package chain, and control_paths for a hit."""

    package_chain = _provider_package_chain(
        module, after_root, inventory_state.after_paths
    )
    shape_trigger = next(
        (path for path in package_chain if path in candidate_state.package_shape_paths),
        None,
    )
    if shape_trigger is None:
        shape_trigger = next(
            iter(
                sorted(
                    _package_init_paths(module, candidate_state.package_shape_paths)
                )
            ),
            None,
        )
    provider_departed = before_provider in inventory_state.removed_paths
    effective_trigger = (
        before_provider
        if provider_departed
        else after_provider
        if before_provider == after_provider
        else shape_trigger or plan.trigger
    )
    finding_path = (
        before_provider
        if provider_departed
        else after_provider
        if after_provider in inventory_state.added_paths or before_provider == after_provider
        else effective_trigger
    )
    control_paths = tuple(
        sorted(
            set(plan.control_paths)
            | {
                path
                for path in diff_state.changed_control_paths
                if _is_conftest_path(path)
                and _scope_applies(path.rpartition("/")[0], test_path)
            }
            | (
                {plan.trigger}
                if plan.trigger in diff_state.changed_control_paths
                else set()
            )
            | _package_init_paths(module, candidate_state.package_shape_paths)
        )
    )
    dedupe = (module.split(".", 1)[0], after_root)
    return dedupe, SubjectShadow(
        finding_path=finding_path,
        module=module,
        before_provider=before_provider,
        after_provider=after_provider,
        test_path=test_path,
        trigger=effective_trigger,
        after_chain=package_chain,
        control_paths=control_paths,
        reportable=reportable,
    )


def _evaluate_module_shadow(
    test_path: str,
    module: str,
    plan: SearchPlan,
    *,
    inventory_state: _InventoryState,
    diff_state: _DiffGateState,
    candidate_state: _CandidateModulesState,
    active_state: _ActiveProvidersState,
    config: Config,
    analysis: _ShadowAnalysisCache,
    include_equivalent: bool,
) -> tuple[tuple[str, str], SubjectShadow] | None:
    """Evaluate one ``(test_path, module, plan)`` triple and build a SubjectShadow hit."""

    changed_fn = _live_shadow_attr("_changed_provider", _changed_provider)
    select_fn = _live_shadow_attr("_selected_provider", _selected_provider)

    scoped = SearchPlan(
        plan.trigger,
        _plan_roots(plan, test_path, inventory_state.before_paths, "before"),
        _plan_roots(plan, test_path, inventory_state.after_paths, "after"),
        plan.before_mode,
        plan.after_mode,
        plan.scope_dir,
        plan.control_paths,
    )
    before_mod_paths, after_mod_paths = active_state.module_paths[module]
    changed = changed_fn(
        module,
        scoped,
        before_mod_paths,
        after_mod_paths,
        active_state.contents,
        added_paths=inventory_state.added_paths,
        removed_paths=inventory_state.removed_paths,
        structural_paths=candidate_state.package_shape_paths,
        before_contents=active_state.before_contents,
        semantic_paths=candidate_state.staged_candidate_paths,
        allow_equivalent=include_equivalent,
        provider_keyer=analysis.provider_execution_key,
        opaque=inventory_state.opaque,
    )
    if changed is None:
        return None
    before_provider, after_provider = changed

    before_selected = select_fn(
        module,
        scoped.before_roots,
        before_mod_paths,
        active_state.before_contents,
        inventory_state.opaque,
    )
    after_selected = select_fn(
        module,
        scoped.after_roots,
        after_mod_paths,
        active_state.contents,
        inventory_state.opaque,
    )
    if before_selected is None or after_selected is None:
        return None
    before_key = analysis.provider_execution_key(
        module, before_selected, before_mod_paths, active_state.before_contents
    )
    after_key = analysis.provider_execution_key(
        module, after_selected, after_mod_paths, active_state.contents
    )
    if before_key is None or after_key is None:
        return None

    reportable = _is_reportable_first_party_shadow(
        module,
        scoped,
        before_provider,
        after_provider,
        before_key,
        after_key,
        before_mod_paths,
        after_mod_paths,
        active_state.before_contents,
        active_state.contents,
        config,
        analysis,
    )
    if reportable is None:
        return None

    return _attribute_shadow_hit(
        test_path=test_path,
        module=module,
        plan=plan,
        before_provider=before_provider,
        after_provider=after_provider,
        after_root=after_selected[0],
        reportable=reportable,
        inventory_state=inventory_state,
        diff_state=diff_state,
        candidate_state=candidate_state,
    )


def _merge_or_append_shadow(
    hits: list[SubjectShadow],
    seen: dict[tuple[str, str], int],
    dedupe: tuple[str, str],
    candidate: SubjectShadow,
) -> None:
    """Deduplicate package fanout while preserving suppressed stand-in evidence paths."""

    if dedupe in seen:
        index = seen[dedupe]
        existing = hits[index]
        related = tuple(
            sorted(
                {
                    *existing.related_evidence_paths,
                    existing.after_provider,
                    *existing.after_chain,
                    candidate.after_provider,
                    *candidate.after_chain,
                }
            )
        )
        controls = tuple(sorted({*existing.control_paths, *candidate.control_paths}))
        if candidate.reportable and not existing.reportable:
            hits[index] = replace(
                candidate,
                related_evidence_paths=related,
                control_paths=controls,
                reportable=True,
            )
        else:
            hits[index] = replace(
                existing,
                related_evidence_paths=related,
                control_paths=controls,
            )
        return

    seen[dedupe] = len(hits)
    hits.append(candidate)


def _emit_subject_shadows(
    *,
    inventory_state: _InventoryState,
    diff_state: _DiffGateState,
    candidate_state: _CandidateModulesState,
    shortlist: _ShortlistState,
    snapshot_state: _InitialSnapshotState,
    active_state: _ActiveProvidersState,
    controls_state: _ControlInvocations,
    config: Config,
    analysis: _ShadowAnalysisCache,
    include_equivalent: bool,
) -> list[SubjectShadow]:
    """Evaluate per-test search plans and emit deterministically ordered SubjectShadow hits."""

    hits: list[SubjectShadow] = []
    seen: dict[tuple[str, str], int] = {}
    for test_path, imported in active_state.imported_by_test.items():
        plans = _build_test_search_plans(
            test_path,
            before_paths=inventory_state.before_paths,
            after_paths=inventory_state.after_paths,
            eligible_tests=shortlist.eligible_tests,
            controls_state=controls_state,
            control_changes=diff_state.control_changes,
            config_source=snapshot_state.config_source,
        )
        for plan in plans:
            for module in sorted(imported, key=lambda m: (-m.count("."), m)):
                evaluated = _evaluate_module_shadow(
                    test_path,
                    module,
                    plan,
                    inventory_state=inventory_state,
                    diff_state=diff_state,
                    candidate_state=candidate_state,
                    active_state=active_state,
                    config=config,
                    analysis=analysis,
                    include_equivalent=include_equivalent,
                )
                if evaluated is not None:
                    dedupe, candidate = evaluated
                    _merge_or_append_shadow(hits, seen, dedupe, candidate)

    return sorted(hits, key=lambda hit: (hit.finding_path, hit.module, hit.test_path))

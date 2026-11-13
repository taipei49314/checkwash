"""Runtime import-provider shadow detection (#86 / #95).

This is deliberately an import-resolution check, not a filename rule.  A
candidate exists only when an existing test imported the same dotted module
on both sides, that module resolved to first-party production at base, and a
different, non-equivalent repository provider wins at head.  Package,
namespace-package and search-path spellings all feed the same predicate.

The repository snapshot is requested lazily.  A new provider, a search-path
edit, or a semantic edit to a provider that an existing test imports can open
the inventory path; ordinary edits with no usable inventory callbacks remain
on the fast path.  Names are listed once, candidate sources are fetched in two
bounded batches (tests/controls, then exact providers), and only collectable
test files are parsed.
"""

from __future__ import annotations

import ast
import configparser
import hashlib
import posixpath
import re
import shlex
import tomllib
from collections.abc import Mapping as _MappingABC
from dataclasses import dataclass, replace
from fnmatch import fnmatchcase
from types import MappingProxyType
from typing import Callable, Collection, Iterable, Mapping, Sequence

from checkwash.change import EngineError, FileChange
from checkwash.config import Config
from checkwash.frontends.python.frontend import _static_truth, parse_python
from checkwash.gitio.snapshot import MAX_BATCH_BYTES, MAX_INVENTORY_PATHS, MAX_SOURCE_BYTES
from checkwash.ir.astutil import stable_dump
from checkwash.opaque import opaque_error, same_kind, split_inventory
from checkwash.roles import _is_runner_script, _runner_shape, _runs_tests, collectable
from checkwash.shadow_controls import (
    _LazyConfigSources,
    _collect_control_invocations,
    _config_change,
    _config_search,
    _dormant_configs,
    _gate_shadow_diff,
    _import_mode,
    _is_conftest_path,
    _is_package_init,
    _is_sys_path,
    _package_shape_change,
    _path_expr,
    _plan_roots,
    _pytest_config_matches,
    _pytest_config_path,
    _pytest_import_root,
    _relevant,
    _search_order_change,
    _source_package,
    _sys_path_roots,
)
from checkwash.shadow_emission import _emit_subject_shadows
from checkwash.shadow_imports import (
    _ShadowAnalysisCache,
    _active_fixture_imports,
    _active_test_imports,
    _fixture_bindings,
    _fixture_decorator,
    _import_targets,
    _parametrized_values,
    _pytest_mark_aliases,
    _pytest_mark_kind,
    _scope_global_loads,
    _test_fixture_requests,
    _usefixtures_values,
)
from checkwash.shadow_inventory import (
    _HEAD_SEARCH_NEEDLE_BATCH,
    _collect_shadow_inventory,
    _complete_head_search,
    _discover_colliding_candidates,
    _normalized_head_search_path,
    _read_initial_snapshot,
    _resolve_active_providers,
    _shortlist_candidate_tests,
)
from checkwash.shadow_models import (
    HeadSearchResult,
    SearchPlan,
    SubjectShadow,
    _FixtureBinding,
    _PYTEST_CONFIGS,
    _PYTHONPATH_REFS,
    _RunnerInvocation,
    _decode,
    _dedupe_roots,
    _dotted,
    _join,
    _normalise_root,
    _split_path_value,
)
from checkwash.shadow_providers import (
    _MAX_SOURCE_KEY_PARSE_BYTES,
    _bytes_source_key,
    _changed_provider,
    _directory_exists,
    _extends_package_path,
    _module_from_root,
    _module_relpaths,
    _opaque_location,
    _package_init_paths,
    _path_to_modules,
    _plan_provider_entries,
    _provider_entries,
    _provider_execution_key,
    _provider_package_chain,
    _selected_provider,
    _side_paths,
    _side_source,
    _source_key,
)
from checkwash.shadow_runners import (
    _BATCH_PYTHONPATH,
    _POWERSHELL_PYTHONPATH,
    _PYTEST_OPTIONS_WITH_OPTIONAL_VALUE,
    _PYTEST_OPTIONS_WITH_VALUE,
    _SHELL_GLOB_MAGIC,
    _YAML_PYTHONPATH,
    _align_runner_invocations,
    _could_be_extensionless_runner,
    _expand_invocation_targets,
    _invocation_applies,
    _invocation_scope_score,
    _line_words,
    _pytest_args,
    _pytest_cli,
    _runner_control,
    _runner_invocation_sides,
    _runner_invocations,
    _runner_invocations_live,
    _runner_pythonpath,
    _runner_roots,
    _runner_search_sides,
    _scope_applies,
    _shell_glob_match,
    _shell_pythonpath,
)


def find_runtime_subject_shadows(
    changes: Sequence[FileChange],
    config: Config,
    third_party_roots: Iterable[str] = (),
    *,
    head_path_lister: Callable[[], Sequence[str]] | None = None,
    head_batch_reader: Callable[[Sequence[str]], Mapping[str, bytes | None]] | None = None,
    head_searcher: Callable[[list[str]], Sequence[str] | HeadSearchResult] | None = None,
    include_equivalent: bool = False,
    config_evidence=None,
    shebang_free: Collection[str] = frozenset(),
) -> list[SubjectShadow]:
    """Return provider changes for existing first-party test imports.

    `shebang_free` names changed paths the engine set aside unread whose
    sides it found to hold no shell shebang (#455). Phase one does not read
    such a path for a shebang.
    """

    if (head_path_lister is None) != (head_batch_reader is None):
        raise EngineError("runtime-shadow inventory requires both path and byte readers")
    analysis = _ShadowAnalysisCache()
    third_party = set(third_party_roots)

    diff_state = _gate_shadow_diff(
        changes, config,
        head_path_lister=head_path_lister, head_batch_reader=head_batch_reader,
        head_searcher=head_searcher, config_evidence=config_evidence,
    )
    if diff_state is None:
        return []

    inventory_state = _collect_shadow_inventory(
        changes, config, diff_state,
        head_path_lister=head_path_lister,
        config_evidence=config_evidence, shebang_free=shebang_free,
    )
    candidate_state = _discover_colliding_candidates(
        inventory_state, diff_state, config, third_party, analysis
    )
    if candidate_state is None:
        return []

    shortlist = _shortlist_candidate_tests(
        inventory_state, candidate_state.modules, changes,
        head_searcher=head_searcher, head_batch_reader=head_batch_reader,
    )
    if shortlist is None:
        return []

    snapshot_state = _read_initial_snapshot(
        inventory_state, diff_state, shortlist,
        head_batch_reader=head_batch_reader, config_evidence=config_evidence,
    )
    active_state = _resolve_active_providers(
        inventory_state, diff_state, candidate_state, shortlist,
        snapshot_state, analysis, head_batch_reader=head_batch_reader,
    )
    if active_state is None:
        return []

    controls_state = _collect_control_invocations(
        conftest_paths=shortlist.conftest_paths,
        before_paths=inventory_state.before_paths,
        after_paths=inventory_state.after_paths,
        changed_runner_paths=inventory_state.changed_runner_paths,
        runner_snapshot_paths=inventory_state.runner_snapshot_paths,
        change_by_path=diff_state.change_by_path,
        side_change_by_path=diff_state.side_change_by_path,
        snapshot=snapshot_state.snapshot,
        side_source=_side_source,
        config=config,
    )
    return _emit_subject_shadows(
        inventory_state=inventory_state, diff_state=diff_state,
        candidate_state=candidate_state, shortlist=shortlist,
        snapshot_state=snapshot_state, active_state=active_state,
        controls_state=controls_state, config=config,
        analysis=analysis, include_equivalent=include_equivalent,
    )

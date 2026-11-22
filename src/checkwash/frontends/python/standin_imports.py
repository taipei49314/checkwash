"""Resolve a test's bare import beside it under the repository's pytest invocations."""

from functools import cache

from checkwash.roles import _runner_shape, collectable
from checkwash.shadow_controls import (
    _LazyConfigSources, _build_test_search_plans, _collect_control_invocations,
    _is_conftest_path, _plan_roots,
)
from checkwash.shadow_providers import _module_relpaths, _selected_provider, _side_paths
from checkwash.shadow_runners import _could_be_extensionless_runner


def sibling_rebindings(inventory, opaque, changes, config, read):
    before, after = _side_paths(inventory, changes)
    all_paths = before | after
    changed = {change.path.replace("\\", "/"): change for change in changes}
    by_side = dict(changed)
    for change in changes:
        if change.old_path:
            by_side[change.old_path.replace("\\", "/")] = change
    tests = {path for path in all_paths if collectable(path) and config.role_of(path) == "test"}

    def source(path, side):
        return read(path, int(side == "after"))

    @cache
    def controls(conftests):
        runners = [path for path in all_paths if config.role_of(path) == "ci"
                   or _runner_shape(path, None, None) or _could_be_extensionless_runner(path)]
        snapshot = _LazyConfigSources(runners, lambda path: read(path, 1))
        return _collect_control_invocations(
            conftest_paths=conftests,
            before_paths=before, after_paths=after, changed_runner_paths=sorted(changed),
            runner_snapshot_paths=sorted(runners), change_by_path=changed,
            side_change_by_path=by_side, snapshot=snapshot,
            side_source=lambda path, side, _changes, _snapshot: source(path, side), config=config,
        )

    @cache
    def roots(test):
        conftests = tuple(sorted(path for path in all_paths if _is_conftest_path(path)
                                 and (path == "conftest.py" or test.startswith(path.rpartition("/")[0] + "/"))))
        plans = _build_test_search_plans(
            test, before_paths=before, after_paths=after, eligible_tests=tests,
            controls_state=controls(conftests), control_changes=changed, config_source=source,
        )
        return [(_plan_roots(plan, test, before, "before"), _plan_roots(plan, test, after, "after"))
                for plan in plans]

    init_sources = [_LazyConfigSources((p for p in paths if p.endswith("/__init__.py")),
                                       lambda path, side=side: read(path, side))
                    for side, paths in enumerate((before, after))]

    def original_binding(old, search):
        parts = old.split(".")
        for end in range(len(parts), 0, -1):
            provider = _selected_provider(".".join(parts[:end]), search, before, init_sources[0], opaque)
            if provider:
                return provider[1], ".".join(parts[end:])
        return None

    @cache
    def resolves(test, old, imported, target, side):
        # Only expand the old root/src ownership proof for an actual test-side
        # provider. A regular package inserts its outer parent, not tests/.
        directory = test.rpartition("/")[0]
        paths = (before, after)[side]
        if not directory or not any(f"{directory}/{rel}" in paths for rel in _module_relpaths(imported)):
            return False
        for plan in roots(test):
            provider = _selected_provider(imported, plan[side], paths, init_sources[side], opaque)
            if provider is None or provider[0] != directory:
                continue
            original = original_binding(old, (*plan[0], "src"))
            if original and original[0] in paths and original != (provider[1], target[len(imported):].lstrip(".")):
                return True
        return False

    return resolves

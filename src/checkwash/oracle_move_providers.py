"""Bind cross-directory Python test moves to their revision's pytest import origins."""
from __future__ import annotations

import ast
from collections import defaultdict
from functools import cache

from checkwash.change import EngineError
from checkwash.opaque import split_inventory
from checkwash.oracle_credit import _key, _source_lines, _span
from checkwash.roles import _runner_shape, collectable
from checkwash.shadow_controls import (
    _build_test_search_plans, _collect_control_invocations, _is_conftest_path,
    _plan_roots, _source_package,
)
from checkwash.shadow_imports import _import_targets, _scope_global_loads
from checkwash.shadow_providers import _selected_provider
from checkwash.shadow_runners import _could_be_extensionless_runner, _scope_applies


def bind_moved_providers(ir, resolver, config):
    by_proof = defaultdict(list)
    for file in ir.files:
        if file.language != "python":
            continue
        for unit in file.units:
            if unit.kind == "helper_function":
                continue
            if (unit.before is None) == (unit.after is None):
                continue
            side = unit.before or unit.after
            if side.oracle_context:
                by_proof[side.oracle_context].append((int(unit.before is None), file.path, side))
    groups = [group for group in by_proof.values()
              if {revision for revision, _, _ in group} == {0, 1}
              and len({path.rpartition("/")[0] for _, path, _ in group}) > 1]
    if not groups or resolver.root_path_lister is None:
        return

    listed, opaque = split_inventory(resolver.root_path_lister())

    @cache
    def paths(revision):
        # The repository inventory is metadata. Source reads remain bounded and
        # side-correct through the relocation resolver, including renames.
        result = set(listed)
        for path, side in resolver.relocation_side_observations:
            if side == revision:
                result.discard(path)
                if resolver.observed_source(path, side) is not None:
                    result.add(path)
        return result

    @cache
    def source_units(path, revision):
        data = resolver.relocation_sources[path][revision]
        text = data.decode("utf-8-sig").replace("\r\n", "\n")
        tree = ast.parse(text)
        lines = _source_lines(text)
        offsets, total = [], 0
        for line in lines:
            offsets.append(total)
            total += len(line)
        functions = {_span(node, lines, offsets): node for node in ast.walk(tree)
                     if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        helpers = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        return tree, functions, helpers

    def imports(path, revision, side):
        tree, functions, helpers = source_units(path, revision)
        fn = functions[side.span]
        package = _source_package(path, paths(revision))
        loads = _scope_global_loads(fn)
        active = _import_targets(fn, package=package)
        for name in side.invoked:
            if name in helpers and name not in side.params:
                helper = helpers[name]
                loads.update(_scope_global_loads(helper))
                active.update(_import_targets(helper, package=package))
        return active | _import_targets(tree, loads, package=package)

    @cache
    def plans(path, revision):
        inventory = paths(revision)
        def read(name):
            return resolver.context_source(name, revision)
        conftests = sorted(p for p in inventory if _is_conftest_path(p)
                           and _scope_applies(p.rpartition("/")[0], path))
        runners = sorted(p for p in inventory if
                         config.role_of(p) == "ci" or _runner_shape(p, None, None)
                         or _could_be_extensionless_runner(p))
        snapshot = {p: read(p) for p in [*conftests, *runners]}
        controls = _collect_control_invocations(
            conftest_paths=conftests, before_paths=inventory, after_paths=inventory,
            changed_runner_paths=[], runner_snapshot_paths=runners,
            change_by_path={}, side_change_by_path={}, snapshot=snapshot,
            side_source=lambda p, *args: snapshot.get(p), config=config)
        candidates = _build_test_search_plans(
            path, before_paths=inventory, after_paths=inventory,
            eligible_tests={p for p in inventory if collectable(p)}, controls_state=controls,
            control_changes={}, config_source=lambda p, _: read(p))
        if not candidates:
            raise ValueError("no pytest invocation covers the relocated test")
        return [(plan.trigger, _plan_roots(plan, path, inventory, "after")) for plan in candidates]

    @cache
    def origin(module, path, revision):
        inventory = paths(revision)
        # Package initializers determine regular versus extended namespace lookup.
        parents = module.split(".")[:-1]
        contents = {p: resolver.context_source(p, revision) for p in inventory
                    if p.endswith("/__init__.py") and p.split("/")[-2] in parents}
        origins = []
        for trigger, roots in plans(path, revision):
            selected = _selected_provider(module, roots, inventory, contents, opaque)
            origins.append((trigger, selected[1] if selected is not None else ""))
        return tuple(sorted(origins))

    # Index only modules actually used by a matched relocation. A provider
    # which already exists beside the destination is just as significant as
    # one this diff added, even when the move itself is the only source edit.
    @cache
    def candidates(module):
        suffix = module.replace(".", "/")
        endings = (suffix + ".py", suffix + "/__init__.py")
        nested = tuple("/" + name for name in endings)
        return {p for p in (paths(0) | paths(1)) if p in endings or p.endswith(nested)}

    for group in groups:
        try:
            bindings = [imports(path, revision, side) for revision, path, side in group]
            relevant = {module for names in bindings for module in names if len(candidates(module)) > 1}
            if not relevant:
                continue
            identities = [tuple((module, origin(module, path, revision)) for module in sorted(names & relevant))
                          for (revision, path, _), names in zip(group, bindings)]
        except (EngineError, ValueError, TypeError, UnicodeError, SyntaxError, KeyError, RecursionError):
            # An incomplete collision proof cannot award whole-unit or fallback assertion credit.
            for _, _, side in group:
                side.oracle_context = ""
                side.oracle_assertion_contexts = {}
            continue
        if len(set(identities)) > 1:
            for (_, _, side), identity in zip(group, identities):
                side.oracle_context = _key("moved-provider", side.oracle_context, identity)
                side.oracle_assertion_contexts = {k: _key("moved-provider", v, identity)
                                                  for k, v in side.oracle_assertion_contexts.items()}

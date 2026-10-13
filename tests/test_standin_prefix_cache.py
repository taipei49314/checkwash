"""Owned cache equivalence/isolation controls; input modules are never run."""

import pytest
from test_standin_installations_main import hits, judge

from checkwash.change import EngineError
from checkwash.conftest_context import ConftestContext
from checkwash.frontends.python import standin_installations as subject

PATH = "tests/test_owned.py"
PROVIDERS = {
    "app/__init__.py": b"",
    "app/billing.py": b"def total():\n    return 1\n",
    "app/alternate.py": b"def total():\n    return 2\n",
}


def prepared(source, conftests=(), *, side=1):
    modules = [subject._module(path, text.encode(), "", side=("before", "after")[side])
               for path, text in (*conftests, (PATH, source))]
    context = ConftestContext([], PROVIDERS.get)
    budget = [0]
    return modules, context, budget


def cached(modules, context, budget, *, side=1):
    return subject._TestPrefix(modules, PATH, context, side, frozenset(), budget)


def uncached(modules, context, budget, name, *, side=1):
    return subject._observed_for_test(modules, PATH, name, context, side, frozenset(), budget)


def watch_prefixes(monkeypatch):
    native = subject._test_prefix
    costs = []

    def watch(*args, **kwargs):
        result = native(*args, **kwargs)
        costs.append(result[0].steps)
        return result

    monkeypatch.setattr(subject, "_test_prefix", watch)
    return costs


@pytest.mark.parametrize("side", [0, 1])
def test_common_prefix_cost_is_removed_only_from_actual_global_work(monkeypatch, side):
    source = ("import app.billing as billing\nbilling.total = lambda: 3\n"
              "def test_a():\n    assert billing.total() == 3\n"
              "def test_b():\n    assert billing.total() == 3\n")
    costs = watch_prefixes(monkeypatch)
    modules, context, budget = prepared(source, side=side)
    cache = cached(modules, context, budget, side=side)
    actual = [cache.observed(name) for name in ("test_a", "test_b")]
    assert len(costs) == 1 and all(len(effects) == 1 for effects in actual)
    prefix_cost = costs[0]
    copied_steps = []
    native_suffix = subject._observed_test_suffix

    def suffix(trace, *args):
        copied_steps.append(trace.steps)
        return native_suffix(trace, *args)

    monkeypatch.setattr(subject, "_observed_test_suffix", suffix)
    assert cache.observed("test_b") == actual[1]
    assert copied_steps == [prefix_cost]
    reference, reference_context, reference_budget = prepared(source, side=side)
    expected = [uncached(reference, reference_context, reference_budget, name, side=side)
                for name in ("test_a", "test_b", "test_b")]
    assert actual + [actual[1]] == expected
    assert costs == [prefix_cost] * 4  # One real cached prefix, three uncached.
    assert reference_budget[0] - budget[0] == 2 * prefix_cost


def test_all_mutable_prefix_state_and_function_owners_are_isolated():
    source = ("import app.billing as billing\nfrom unittest.mock import patch\n"
              "billing.total = lambda: 3\nassert billing.total() == 3\n"
              "@patch('app.billing.total', return_value=3)\n"
              "def test_a(mock):\n    assert mock() == 3\n")
    modules, context, budget = prepared(source)
    # The seed graph is not the executable module prefix.
    modules[0].env["seed_only"] = subject._Value("poison")
    trace, active = subject._test_prefix(modules, PATH, context, 1, frozenset(), budget)
    assert "seed_only" not in active[0].env
    effect = next(iter(trace.active.values()))
    trace.patch_results["owned"] = effect
    trace.called_patch_results.add("owned")
    left, left_modules = subject._copy_test_prefix(trace, active)
    right, right_modules = subject._copy_test_prefix(trace, active)
    assert set(vars(left)) == set(vars(trace))
    assert left.budget is right.budget is budget
    assert left.context is right.context is context
    assert left.test_module is left_modules[0]
    assert right.test_module is right_modules[0]
    for fork in (left, right):
        assert fork.modules[0] is not modules[0]
        assert fork.test_module.tree is active[0].tree
        assert fork.steps == trace.steps and not fork.failed_assertion
        assert fork.active == trace.active and fork.observed == trace.observed
        assert fork.patch_results == trace.patch_results
        assert fork.called_patch_results == trace.called_patch_results
        function = fork.test_module.functions["test_a"]
        assert function.module is fork.test_module
        assert function.node is active[0].functions["test_a"].node
        assert function.patch_env == active[0].functions["test_a"].patch_env
    left.active.clear()
    left.observed.clear()
    left.patch_results.clear()
    left.called_patch_results.clear()
    left.stack.append((PATH, "test_a"))
    left.steps += 1
    left.failed_assertion = True
    left.test_module.env["billing"] = subject._Value("other")
    left.test_module.baseline_imports[("", "billing")] = "other"
    left.test_module.functions["test_a"].patch_env.clear()
    left.test_module.functions.clear()
    assert right.active and right.observed and right.patch_results and right.called_patch_results
    assert right.stack == trace.stack == []
    assert not right.failed_assertion and right.steps == trace.steps
    assert right.test_module.env["billing"].alias == "app.billing"
    assert right.test_module.baseline_imports[("", "billing")] == "app.billing"
    assert right.test_module.functions["test_a"].patch_env
    assert active[0].functions["test_a"].patch_env


def test_setup_hook_fixture_and_test_order_remains_per_test(monkeypatch):
    early = ("pytest_configure", "pytest_sessionstart")
    late = ("pytest_collection_modifyitems", "pytest_collection_finish", "pytest_generate_tests", "pytest_runtest_setup")
    hooks = "".join(f"def {name}():\n    pass\n" for name in (*early, *late))
    root = "import pytest\n" + hooks + "@pytest.fixture(autouse=True)\ndef fixture_each():\n    pass\n"
    source = "def test_a():\n    assert True\ndef test_b():\n    assert True\n"
    conftests = (("conftest.py", root), ("tests/conftest.py", hooks))
    events = []
    native_block, native_function = subject._Trace.block, subject._Trace.function

    def block(self, statements, module, env, qualname, **kwargs):
        if qualname == "":
            events.append((module.path, "module"))
        return native_block(self, statements, module, env, qualname, **kwargs)

    def function(self, value, *args, **kwargs):
        events.append((value.module.path, value.qualname))
        return native_function(self, value, *args, **kwargs)

    monkeypatch.setattr(subject._Trace, "block", block)
    monkeypatch.setattr(subject._Trace, "function", function)
    modules, context, budget = prepared(source, conftests)
    cache = cached(modules, context, budget)
    cache.observed("test_a")
    cache.observed("test_b")
    prefix = [(path, "module") for path, _ in conftests]
    prefix += [(path, name) for path, _ in conftests for name in early]
    prefix += [(PATH, "module")]
    suffix = [(path, name) for path, _ in conftests for name in late]
    suffix += [("conftest.py", "fixture_each")]
    assert events == prefix + suffix + [(PATH, "test_a")] + suffix + [(PATH, "test_b")]


@pytest.mark.parametrize("source", [
    ("import app.billing as billing\n"
    "def test_a():\n    billing.total = lambda: 3\n    assert billing.total() == 3\n    assert False\n"
    "def test_b():\n    assert billing.total() == 1\n"),
    ("import pytest\nfrom app.billing import total\n"
    "@pytest.fixture\ndef replace_total(request):\n    request.module.total = lambda: 3\n"
    "def test_a(replace_total):\n    assert total() == 3\n"
    "def test_b():\n    assert total() == 1\n"),
])
def test_suffix_installations_observations_failure_and_module_env_do_not_leak(source):
    modules, context, budget = prepared(source)
    cache = cached(modules, context, budget)
    first = cache.observed("test_a")
    second = cache.observed("test_b")
    reference, reference_context, reference_budget = prepared(source)
    assert first == uncached(reference, reference_context, reference_budget, "test_a")
    assert second == uncached(reference, reference_context, reference_budget, "test_b")
    assert len(first) == 1 and second == set()


def test_suffix_import_discovery_invalidates_and_preserves_original_metadata(monkeypatch):
    source = ("def test_a():\n    if True:\n        import app.alternate as alias\n    assert True\n"
              "def test_b():\n    assert True\n")
    costs = watch_prefixes(monkeypatch)
    modules, context, budget = prepared(source)
    assert ("test_a", "alias") not in modules[0].baseline_imports
    cache = cached(modules, context, budget)
    assert cache.observed("test_a") == set()
    assert modules[0].baseline_imports[("test_a", "alias")] == "app.alternate"
    assert cache.snapshot is None
    assert cache.observed("test_b") == cache.observed("test_b") == set()
    assert len(costs) == 2


def test_changed_import_baseline_is_replayed_instead_of_reusing_old_aliases(monkeypatch):
    source = "from app.billing import total\ndef test_a():\n    assert total() == 1\n"
    costs = watch_prefixes(monkeypatch)
    modules, context, budget = prepared(source)
    cache = cached(modules, context, budget)
    assert cache.observed("test_a") == set()
    modules[0].baseline_imports[("", "total")] = "app.alternate.total"
    observed = cache.observed("test_a")
    assert len(costs) == 2
    assert {effect.target for effect in observed} == {"app.alternate.total"}


def test_failed_assertion_in_prefix_is_not_cached(monkeypatch):
    costs = watch_prefixes(monkeypatch)
    modules, context, budget = prepared("assert False\ndef test_a():\n    assert True\n")
    cache = cached(modules, context, budget)
    assert cache.observed("test_a") == cache.observed("test_a") == set()
    assert len(costs) == 2 and cache.snapshot is None


@pytest.mark.parametrize("stage", ["prefix", "suffix"])
def test_exceptions_are_not_cached(monkeypatch, stage):
    modules, context, budget = prepared("def test_a():\n    assert True\n")
    costs = watch_prefixes(monkeypatch)
    calls = []

    def fail(*_args, **_kwargs):
        calls.append(stage)
        raise EngineError("owned capture failure")

    monkeypatch.setattr(subject, "_test_prefix" if stage == "prefix" else "_observed_test_suffix", fail)
    cache = cached(modules, context, budget)
    for _ in range(2):
        with pytest.raises(EngineError, match="owned capture failure"):
            cache.observed("test_a")
        assert cache.snapshot is None
    assert calls == [stage, stage]
    assert len(costs) == (0 if stage == "prefix" else 2)


def test_cached_local_step_cost_still_enforces_the_original_guard():
    modules, context, budget = prepared("def test_a():\n    pass\n    pass\n")
    cache = cached(modules, context, budget)
    cache.observed("missing")  # Populate a successful prefix without a suffix.
    cache.snapshot[1].steps = 19_999  # Synthetic boundary; production cap is unchanged.
    previous = budget[0]
    with pytest.raises(EngineError, match="source step limit"):
        cache.observed("test_a")
    assert budget[0] == previous + 2
    assert cache.snapshot is None


def test_cached_suffix_still_enforces_the_shared_global_guard():
    modules, context, budget = prepared("def test_a():\n    pass\n")
    cache = cached(modules, context, budget)
    cache.observed("test_a")
    budget[0] = subject._MAX_ANALYSIS_STEPS
    with pytest.raises(EngineError, match="source step limit"):
        cache.observed("test_a")
    assert budget[0] == subject._MAX_ANALYSIS_STEPS + 1
    assert cache.snapshot is None


def test_first_prefix_still_rejects_work_above_the_existing_local_guard():
    source = "pass\n" * 20_000 + "def test_a():\n    pass\n"
    modules, context, budget = prepared(source)
    cache = cached(modules, context, budget)
    for attempt in (1, 2):
        with pytest.raises(EngineError, match="source step limit"):
            cache.observed("test_a")
        assert cache.snapshot is None
        assert budget[0] == attempt * 20_001


def test_missing_function_keeps_prefix_observations_private():
    source = ("import app.billing as billing\nbilling.total = lambda: 3\n"
              "assert billing.total() == 3\ndef test_a():\n    pass\n")
    modules, context, budget = prepared(source)
    cache = cached(modules, context, budget)
    assert cache.observed("missing") == set()
    assert len(cache.observed("test_a")) == 1


def test_patch_result_and_decorator_environment_remain_per_invocation(monkeypatch):
    source = ("from unittest.mock import patch\n"
              "@patch('app.billing.total', return_value=3)\n"
              "def test_a(replacement):\n    assert replacement() == 3\n")
    monkeypatch.setattr(subject._Trace, "patch_authority", lambda self, module, target: True)
    modules, context, budget = prepared(source)
    cache = cached(modules, context, budget)
    actual = [cache.observed("test_a"), cache.observed("test_a")]
    reference, reference_context, reference_budget = prepared(source)
    expected = [uncached(reference, reference_context, reference_budget, "test_a") for _ in range(2)]
    assert actual == expected and all(len(effects) == 1 for effects in actual)
    saved = cache.snapshot[1]
    assert saved.patch_results == {} and saved.called_patch_results == set()
    assert saved.test_module.functions["test_a"].patch_env


def test_installation_events_separates_paths_sides_and_invocations(monkeypatch):
    before_source = ("import app.billing as billing\n"
                     "def test_a():\n    assert billing.total() == 3\n"
                     "def test_b():\n    assert billing.total() == 3\n")
    after_source = before_source.replace("def test_a", "billing.total = lambda: 3\ndef test_a")
    paths = (PATH, "tests/test_other.py")
    before = {path: before_source.encode() for path in paths}
    after = {path: after_source.encode() for path in paths}
    result = judge(before, after)
    second_invocation = judge(before, after)
    assert result == second_invocation
    assert len(hits(result)) == 4
    assert {finding.path for finding in hits(result)} == set(paths)

    def original(self, qualname):
        modules, path, context, side, deny, budget, search = self.arguments
        return subject._observed_for_test(modules, path, qualname, context, side, deny, budget, search)

    monkeypatch.setattr(subject._TestPrefix, "observed", original)
    assert judge(before, after) == result


def test_cache_hit_import_discovery_writes_back_and_rebuilds_before_reuse(monkeypatch):
    source = ("def test_a():\n    assert True\n"
              "def test_b():\n    if True:\n        import app.alternate as alias\n"
              "    alias.total = lambda: 3\n    assert alias.total() == 3\n"
              "def test_c():\n    assert True\n")
    key = ("test_b", "alias")
    costs = watch_prefixes(monkeypatch)
    modules, context, budget = prepared(source)
    cache = cached(modules, context, budget)
    assert key not in modules[0].baseline_imports
    actual = [cache.observed("test_a")]
    actual_metadata = [dict(modules[0].baseline_imports)]
    assert len(costs) == 1 and cache.snapshot is not None
    assert key not in cache.snapshot[1].test_module.baseline_imports

    actual.append(cache.observed("test_b"))
    actual_metadata.append(dict(modules[0].baseline_imports))
    assert len(costs) == 1  # Discovery was in a cloned hit, not a new prefix.
    assert {effect.target for effect in actual[-1]} == {"app.alternate.total"}
    assert modules[0].baseline_imports[key] == "app.alternate"
    assert cache.snapshot is None

    for _ in range(2):
        actual.append(cache.observed("test_c"))
        actual_metadata.append(dict(modules[0].baseline_imports))
        assert len(costs) == 2  # One real rebuild, then reuse of that new prefix.
    assert cache.snapshot[1].test_module.baseline_imports[key] == "app.alternate"

    reference, reference_context, reference_budget = prepared(source)
    expected, expected_metadata = [], []
    for name in ("test_a", "test_b", "test_c", "test_c"):
        expected.append(uncached(reference, reference_context, reference_budget, name))
        expected_metadata.append(dict(reference[0].baseline_imports))
    assert actual == expected
    assert actual_metadata == expected_metadata


def test_cache_hit_import_then_exception_writes_back_and_rebuilds(monkeypatch):
    source = ("def test_a():\n    assert True\n"
              "def test_b():\n    if True:\n        import app.alternate as alias\n"
              "    assert True\n"
              "def test_c():\n    assert True\n")
    key = ("test_b", "alias")
    failure = EngineError("owned failure after actual import discovery")
    native_block = subject._Trace.block
    discovered_maps = []

    def fail_after_import(self, statements, module, env, qualname, **kwargs):
        result = native_block(self, statements, module, env, qualname, **kwargs)
        if qualname == "test_b" and key in module.baseline_imports:
            assert env["alias"].alias == "app.alternate"
            discovered_maps.append(module.baseline_imports)
            raise failure
        return result

    monkeypatch.setattr(subject._Trace, "block", fail_after_import)
    costs = watch_prefixes(monkeypatch)
    modules, context, budget = prepared(source)
    cache = cached(modules, context, budget)
    assert key not in modules[0].baseline_imports
    first = cache.observed("test_a")
    assert len(costs) == 1 and cache.snapshot is not None
    with pytest.raises(EngineError) as raised:
        cache.observed("test_b")
    assert raised.value is failure
    assert len(costs) == 1 and len(discovered_maps) == 1
    assert discovered_maps[0] is not modules[0].baseline_imports
    assert modules[0].baseline_imports[key] == "app.alternate"
    exceptional_metadata = dict(modules[0].baseline_imports)
    assert cache.snapshot is None
    tail = []
    for _ in range(2):
        tail.append(cache.observed("test_c"))
        assert len(costs) == 2  # The invalidated hit cannot suppress replay.
    assert cache.snapshot[1].test_module.baseline_imports[key] == "app.alternate"

    reference, reference_context, reference_budget = prepared(source)
    assert first == uncached(reference, reference_context, reference_budget, "test_a")
    with pytest.raises(EngineError) as reference_raised:
        uncached(reference, reference_context, reference_budget, "test_b")
    assert reference_raised.value is failure
    assert len(discovered_maps) == 2
    assert discovered_maps[1] is reference[0].baseline_imports
    assert exceptional_metadata == reference[0].baseline_imports
    expected_tail = [uncached(reference, reference_context, reference_budget, "test_c")
                     for _ in range(2)]
    assert tail == expected_tail
    assert modules[0].baseline_imports == reference[0].baseline_imports

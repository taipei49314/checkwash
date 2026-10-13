"""Source-only proposals: input modules are parsed/analyzed, never executed."""

import pytest
from test_standin_installations_main import hits, judge

from checkwash.change import EngineError
from checkwash.frontends.python import standin_installations as subject

PATH = "tests/test_owned.py"


def prepared(source):
    module = subject._module(PATH, source.encode(), "", side="before")
    assert module is not None
    trace = subject._Trace([module], None, 0, set(), [0])
    return trace, module


@pytest.mark.parametrize("literal", ["1", "'text'", "b'bytes'", "None", "True", "1j"])
def test_direct_literal_values_keep_every_empty_binding(literal):
    trace, module = prepared(f"a = {literal}\nb = {literal}\n")
    trace.block(module.tree.body, module, module.env, "")
    assert module.env == {"a": subject._Value(), "b": subject._Value()}
    assert (trace.steps, trace.budget[0]) == (1, 1)
    assert not trace.active and not trace.observed


@pytest.mark.parametrize("count,steps", [(2, 1), (64, 1), (65, 3)])
def test_batch_has_fixed_sixty_four_store_bound(count, steps):
    trace, module = prepared("".join(f"padding_{n} = 1\n" for n in range(count)))
    trace.block(module.tree.body, module, module.env, "")
    assert len(module.env) == count
    assert all(value == subject._Value() for value in module.env.values())
    assert (trace.steps, trace.budget[0]) == (steps, steps)


@pytest.mark.parametrize("kind", ["provider_alias", "function_alias", "captured_import"])
def test_existing_alias_or_captured_import_stops_bulk_path(kind):
    trace, module = prepared("a = 1\nb = 2\nc = 3\n")
    if kind == "captured_import":
        module.baseline_imports["", "b"] = "app.billing.total"
    else:
        module.env["b"] = subject._Value(
            "app.billing.total" if kind == "provider_alias" else "@function:helper"
        )
    names, end = trace._literal_binding_run(module.tree.body, 0, module, module.env)
    assert (names, end) == (["a"], 1)
    names, end = trace._literal_binding_run(module.tree.body, 1, module, module.env)
    assert (names, end) == ([], 1)


@pytest.mark.parametrize("statement", [
    "a: int = 1", "obj.a = 1", "a = b = 1", "a = other",
    "a = helper()", "a = [1]", "a = -1",
])
def test_other_assignment_shapes_keep_interpreter_dispatch(statement):
    trace, module = prepared(statement + "\nb = 2\n")
    names, end = trace._literal_binding_run(module.tree.body, 0, module, module.env)
    assert (names, end) == ([], 0)


def test_duplicate_names_keep_last_empty_value_without_new_effects():
    trace, module = prepared("a = 1\na = 2\n")
    module.env["a"] = subject._Value(effects=frozenset())
    trace.block(module.tree.body, module, module.env, "")
    assert module.env == {"a": subject._Value()}
    assert trace.steps == trace.budget[0] == 1


def test_builtin_shadow_bindings_remain_present():
    trace, module = prepared("setattr = 1\ngetattr = 2\nvars = 3\n")
    trace.block(module.tree.body, module, module.env, "")
    assert set(module.env) == {"setattr", "getattr", "vars"}
    assert all(value.alias is None for value in module.env.values())


@pytest.mark.parametrize("local,shared", [(20_000, 0), (0, 1_000_000)])
def test_bulk_operation_still_fails_closed_before_mutation(local, shared):
    trace, module = prepared("a = 1\nb = 2\n")
    trace.steps = local
    trace.budget[0] = shared
    with pytest.raises(EngineError, match="source step limit") as raised:
        trace.block(module.tree.body, module, module.env, "")
    assert module.env == {}
    assert (trace.steps, trace.budget[0]) == (local + 1, shared + 1)
    assert "phase='literal_binding_batch'" in raised.value.standin_step_diagnostic
    assert "requested_side='before'" in raised.value.standin_step_diagnostic


@pytest.mark.parametrize("qualname", ["test_a", "OwnedClass"])
def test_function_and_class_scopes_keep_original_two_steps_per_store(qualname):
    trace, module = prepared("a = 1\nb = 2\n")
    trace.block(module.tree.body, module, module.env, qualname)
    assert (trace.steps, trace.budget[0]) == (4, 4)
    assert len(module.env) == 2


def literal_prefix():
    # Representative original shape, not a regenerated/replaced original case.
    return "import app.billing as billing\n" + "".join(
        f"padding_{n:06d} = 12345678901234567890\n" for n in range(26_000)
    )


def test_many_literal_stores_reach_real_tail_installation_and_existing_oracle():
    prefix = literal_prefix()
    before = (prefix + "def test_total():\n    observed = billing.total\n"
              "    assert billing.total() == 3\n").encode()
    after = (prefix + "def test_total():\n    billing.total = lambda: 3\n"
             "    assert billing.total() == 3\n").encode()
    found = hits(judge({PATH: before}, {PATH: after}))
    assert len(found) == 1 and found[0].severity == "high"
    assert "app.billing.total" in found[0].message


def test_many_literal_stores_do_not_invent_installation_for_normal_test_change():
    prefix = literal_prefix()
    before = (prefix + "def test_total():\n    assert billing.total() == 3\n").encode()
    after = (prefix + "def test_total():\n    observed = billing.total()\n"
             "    assert billing.total() == 3\n").encode()
    assert hits(judge({PATH: before}, {PATH: after})) == []


def test_captured_import_literal_rebinding_keeps_installation_evidence():
    prefix = "from app.billing import total\na = 1\nb = 2\n"
    before = (prefix + "def test_total():\n    assert total() == 3\n").encode()
    after = (prefix + "total = 3\ndef test_total():\n    assert total == 3\n").encode()
    assert len(hits(judge({PATH: before}, {PATH: after}))) == 1


def test_literal_attribute_store_after_batch_is_not_swallowed():
    prefix = "import app.billing as billing\na = 1\nb = 2\n"
    before = (prefix + "def test_total():\n    assert billing.total == 3\n").encode()
    after = (prefix + "billing.total = 3\ndef test_total():\n"
             "    assert billing.total == 3\n").encode()
    assert len(hits(judge({PATH: before}, {PATH: after}))) == 1


def test_failed_assertion_after_batch_still_prevents_tail_observation():
    prefix = "import app.billing as billing\na = 1\nb = 2\nassert False\n"
    before = (prefix + "def test_total():\n    assert billing.total() == 3\n").encode()
    after = (prefix + "billing.total = lambda: 3\ndef test_total():\n"
             "    assert billing.total() == 3\n").encode()
    assert hits(judge({PATH: before}, {PATH: after})) == []


def test_effectful_helper_between_runs_is_interpreted_in_source_order():
    prefix = ("import app.billing as billing\na = 1\nb = 2\n"
              "def install():\n    billing.total = lambda: 3\n")
    before = (prefix + "c = 3\nd = 4\ndef test_total():\n"
              "    assert billing.total() == 3\n").encode()
    after = (prefix + "install()\nc = 3\nd = 4\ndef test_total():\n"
             "    assert billing.total() == 3\n").encode()
    assert len(hits(judge({PATH: before}, {PATH: after}))) == 1

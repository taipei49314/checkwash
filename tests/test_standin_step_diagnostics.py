"""Finite diagnostic source controls, proposed for hosted qualification only."""
import ast

import pytest

from checkwash import cli
from checkwash.change import EngineError
from checkwash.frontends.python import standin_installations as subject

GENERIC = "stand-in execution proof exceeds the source step limit"
PATH = "tests/test_budget.py"


def prepared(side=1, local=0, shared=0):
    module = subject._Module(PATH, "", ast.Module(body=[], type_ignores=[]), "")
    trace = subject._Trace([module], None, side, set(), [shared])
    trace.steps = local
    trace.test_module = module
    return trace, module


def test_below_and_at_both_original_bounds_keep_exact_accounting():
    trace, module = prepared(local=19_998, shared=999_998)
    assert trace._step(module, "test_budget", "block") is None
    assert (trace.steps, trace.budget[0]) == (19_999, 999_999)
    assert trace._step(module, "test_budget", "block") is None
    assert (trace.steps, trace.budget[0]) == (20_000, 1_000_000)


@pytest.mark.parametrize("side", [0, 1])
@pytest.mark.parametrize("local,shared,which", [
    (20_000, 7, "trace"), (0, 1_000_000, "shared"),
    (20_000, 1_000_000, "trace+shared"),
])
def test_actual_failure_counters_and_both_guards_are_disclosed(side, local, shared, which):
    trace, module = prepared(side, local, shared)
    with pytest.raises(EngineError, match="^" + GENERIC + "$") as raised:
        trace._step(module, "test_budget", "block")
    assert type(raised.value) is EngineError
    assert str(raised.value) == GENERIC
    assert (trace.steps, trace.budget[0]) == (local + 1, shared + 1)
    detail = raised.value.standin_step_diagnostic
    assert detail is not None
    assert f"exceeded={which}," in detail
    assert f"trace_steps={local + 1}, trace_limit=20000" in detail
    assert f"shared_steps={shared + 1}, shared_limit=1000000" in detail
    assert "phase='block'" in detail and "unit='test_budget'" in detail
    assert f"path={PATH!r}" in detail
    assert "requested_side=" + repr(("before", "after")[side]) in detail


def test_legacy_no_argument_step_keeps_exact_error_without_invented_path():
    trace, _module = prepared(local=20_000)
    with pytest.raises(EngineError, match="^" + GENERIC + "$") as raised:
        trace._step()
    detail = raised.value.standin_step_diagnostic
    assert "path='<unknown>'" in detail and "phase='legacy'" in detail
    assert "unit=''" in detail
    assert (trace.steps, trace.budget[0]) == (20_001, 1)


@pytest.mark.parametrize("phase", ["expression", "binary_expression", "block"])
def test_all_three_actual_step_callers_supply_source_provenance(phase):
    trace, module = prepared(local=19_999 if phase == "binary_expression" else 20_000)
    with pytest.raises(EngineError) as raised:
        if phase == "block":
            trace.block([ast.Pass()], module, {}, "test_budget")
        elif phase == "binary_expression":
            trace.expression(ast.parse("a + b + c", mode="eval").body, module, {}, "test_budget")
        else:
            trace.expression(ast.Constant(value=1), module, {}, "test_budget")
    detail = raised.value.standin_step_diagnostic
    assert f"phase={phase!r}" in detail
    assert f"path={PATH!r}" in detail and "unit='test_budget'" in detail
    assert trace.steps == 20_001
    assert trace.budget[0] == (2 if phase == "binary_expression" else 1)


def test_cached_prefix_copy_keeps_local_charge_and_shared_counter_identity():
    trace, module = prepared(local=20_000, shared=10)
    copied, modules = subject._copy_test_prefix(trace, [module])
    assert copied.budget is trace.budget
    with pytest.raises(EngineError) as raised:
        copied._step(modules[0], "test_budget", "block")
    assert trace.steps == 20_000 and copied.steps == 20_001
    assert trace.budget == copied.budget == [11]
    assert "trace_steps=20001" in raised.value.standin_step_diagnostic
    assert "shared_steps=11" in raised.value.standin_step_diagnostic


@pytest.mark.parametrize("format_name", ["term", "json", "sarif"])
def test_cli_renders_diagnostic_as_same_exit_two_error_without_verdict(monkeypatch, capsys, format_name):
    trace, module = prepared(local=20_000)

    def fail(_args):
        trace._step(module, "test_budget", "block")

    monkeypatch.setattr(cli, "_cmd_check", fail)
    assert cli.main(["check", "--format", format_name]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err.startswith("checkwash engine error: EngineError: " + GENERIC)
    assert "exceeded=trace" in output.err and "trace_steps=20001" in output.err
    assert f"path={PATH!r}" in output.err and "requested_side='after'" in output.err


def test_unrelated_engine_error_keeps_original_cli_text(monkeypatch, capsys):
    def fail(_args):
        error = EngineError("owned unrelated failure")
        assert error.standin_step_diagnostic is None
        raise error

    monkeypatch.setattr(cli, "_cmd_check", fail)
    assert cli.main(["check", "--format", "json"]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "checkwash engine error: EngineError: owned unrelated failure\n"

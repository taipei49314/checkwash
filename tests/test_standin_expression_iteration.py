"""Owned source data only; execution of these tests belongs to hosted CI.

The shallow reference preserves the previous BinOp generic branch. Deep
cases exercise the real parser and trace, without changing recursion limits.
"""

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from checkwash.change import EngineError
from checkwash.conftest_context import ConftestContext
from checkwash.frontends.python import standin_installations as subject

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
import standin_cost_cases as cases


class _ObservedTrace(subject._Trace):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.function_order = []
        self.install_order = []

    def function(self, function, args=(), kwargs=None):
        self.function_order.append(function.qualname)
        return super().function(function, args, kwargs)

    def install(self, target, kind, value, replacement, node, module):
        self.install_order.append((target, value.alias, node.col_offset))
        return super().install(target, kind, value, replacement, node, module)


class _PreviousBinOpTrace(_ObservedTrace):
    def expression(self, node, module, env, qualname, *, native_setattr=True):
        if isinstance(node, ast.BinOp):
            self._step()
            if self.failed_assertion:
                return subject._Value()
            # Literal previous generic expression branch, used only shallowly.
            return subject._value(*(
                self.expression(child, module, env, qualname, native_setattr=native_setattr)
                for child in ast.iter_child_nodes(node) if isinstance(child, ast.expr)
            ))
        return super().expression(node, module, env, qualname, native_setattr=native_setattr)


def _trace(source="pass\n", trace_type=_ObservedTrace, budget=None):
    module = subject._module(cases.PATH, source.encode(), "", side="after")
    assert module is not None
    context = ConftestContext([], cases.COMMON.get)
    trace = trace_type([module], context, 1, set(), budget)
    return trace, module


def _effect(name):
    return subject._Effect(cases.PATH, "app." + name, "attribute", name, name, (1, 1))


def _state(trace):
    return (trace.steps, trace.budget[0], trace.failed_assertion, trace.active,
            trace.observed, trace.called_patch_results, trace.function_order,
            trace.install_order)


@pytest.mark.parametrize("source,names", [
    ("a + b", "ab"),
    ("(a + b) * (b + c)", "abc"),
    ("a + (b + c)", "abc"),
    ("(a - b) / c ** a", "abc"),
    ("-(a + b) + c", "abc"),
    ("(a, b)[0] + c", "abc"),
    ("external(a + b, named=c) + a", "abc"),
    ("(lambda: a + b) + (x for x in c)", ""),
])
def test_shallow_success_matches_previous_branch_without_borrowing_an_alias(source, names):
    node = ast.parse(source, mode="eval").body
    env = {name: subject._Value("app." + name, frozenset({_effect(name)}))
           for name in "abc"}
    trace, module = _trace(budget=[41])
    previous, old_module = _trace(trace_type=_PreviousBinOpTrace, budget=[41])
    actual = trace.expression(node, module, env, "test_owned")
    expected = previous.expression(node, old_module, env, "test_owned")
    assert actual == expected == subject._Value(effects=frozenset(_effect(name) for name in names))
    assert _state(trace) == _state(previous)


@pytest.mark.parametrize("callee,native,shadowed,installed", [
    ("setattr", True, False, True),
    ("setattr", False, False, False),
    ("setattr", True, True, False),
    ("native_setattr", False, False, True),
])
def test_left_to_right_install_consume_restore_retains_original_authority(
    callee, native, shadowed, installed,
):
    source = (f"{callee}(billing, 'total', lambda: 3) + billing.total() + "
              f"{callee}(billing, 'total', original) + billing.total()\n")
    results = []
    for trace_type in (_ObservedTrace, _PreviousBinOpTrace):
        trace, module = _trace(source, trace_type, [29])
        env = {"billing": subject._Value("app.billing"),
               "original": subject._Value("app.billing.total"),
               "native_setattr": subject._Value("builtins.setattr")}
        if shadowed:
            env["setattr"] = subject._Value("untrusted.setattr")
        value = trace.expression(module.tree.body[0].value, module, env, "", native_setattr=native)
        assert value.alias is None
        assert len(value.effects) == int(installed)
        assert trace.active == {}, "restoration must occur after the first consumption"
        if installed:
            assert [item[:2] for item in trace.install_order] == [
                ("app.billing.total", None), ("app.billing.total", "app.billing.total"),
            ]
            assert {effect.target for effect in value.effects} == {"app.billing.total"}
        else:
            assert trace.install_order == []
        results.append((value, _state(trace)))
    assert results[0] == results[1]


def test_successful_helpers_keep_call_order_and_effects_across_restoration():
    source = ("def install():\n    setattr(billing, 'total', lambda: 3)\n    return billing.total()\n"
              "def restore():\n    setattr(billing, 'total', original)\n    return billing.total()\n"
              "install() + restore() + install()\n")
    results = []
    for trace_type in (_ObservedTrace, _PreviousBinOpTrace):
        trace, module = _trace(source, trace_type, [67])
        trace.block(module.tree.body[:-1], module, module.env, "")
        module.env.update(billing=subject._Value("app.billing"),
                          original=subject._Value("app.billing.total"))
        value = trace.expression(module.tree.body[-1].value, module, module.env, "")
        assert trace.function_order == ["install", "restore", "install"]
        assert len(trace.install_order) == 3
        assert len(value.effects) == 1 and value.alias is None
        assert set(trace.active) == {("app.billing.total", "attribute")}
        assert frozenset(trace.active.values()) == value.effects
        results.append((value, _state(trace)))
    assert results[0] == results[1]


@pytest.mark.parametrize("expression,retained", [
    ("(a + stop()) + (later() + last())", True),
    ("(stop() + later()) + (last() + later())", False),
    ("a + (stop() + later())", True),
])
def test_failed_helper_skips_subtrees_but_charges_their_entered_roots(expression, retained):
    source = ("def stop():\n    assert False\n"
              "def later():\n    return 7\n"
              "def last():\n    return 9\n" + expression + "\n")
    results = []
    for trace_type in (_ObservedTrace, _PreviousBinOpTrace):
        trace, module = _trace(source, trace_type, [53])
        trace.block(module.tree.body[:-1], module, module.env, "")
        module.env["a"] = subject._Value("app.a", frozenset({_effect("a")}))
        local, shared = trace.steps, trace.budget[0]
        value = trace.expression(module.tree.body[-1].value, module, module.env, "")
        assert trace.failed_assertion and trace.function_order == ["stop"]
        assert trace.steps - local == trace.budget[0] - shared == 7
        assert value == subject._Value(effects=frozenset({_effect("a")}) if retained else frozenset())
        results.append((value, _state(trace)))
    assert results[0] == results[1]


@pytest.mark.parametrize("node", [None, ast.BinOp(left=ast.Constant(1), op=ast.Add(), right=ast.Constant(2))])
def test_already_failed_entry_still_charges_one_step_without_descending(node):
    trace, module = _trace(budget=[17])
    trace.failed_assertion = True
    assert trace.expression(node, module, {}, "") == subject._Value()
    assert trace.steps == 1 and trace.budget == [18]


@pytest.mark.parametrize("local,shared,end_local,end_shared,refused", [
    (19_997, 50, 20_000, 53, False),
    (19_999, 50, 20_001, 52, True),
    (0, 999_997, 3, 1_000_000, False),
    (0, 999_999, 2, 1_000_001, True),
])
def test_original_local_and_shared_limits_keep_exact_charge_and_failure(
    local, shared, end_local, end_shared, refused,
):
    node = ast.parse("a + b", mode="eval").body
    results = []
    for trace_type in (_ObservedTrace, _PreviousBinOpTrace):
        trace, module = _trace(trace_type=trace_type, budget=[shared])
        trace.steps = local
        if refused:
            with pytest.raises(EngineError, match="^stand-in execution proof exceeds the source step limit$"):
                trace.expression(node, module, {}, "")
        else:
            assert trace.expression(node, module, {}, "") == subject._Value()
        assert trace.steps == end_local and trace.budget == [end_shared]
        results.append(_state(trace))
    assert results[0] == results[1]


@pytest.mark.parametrize("side", [0, 1])
def test_original_deep_owned_ast_uses_19797_expression_steps(side):
    raw = cases.pair(cases.DEEP)[side]
    limit = sys.getrecursionlimit()
    trace, module = _trace(raw.decode(), budget=[73])
    assert len(raw) == cases.SIZE == 1_000_000
    node = module.tree.body[1].value
    assert isinstance(node, ast.BinOp)
    assert sum(isinstance(item, ast.BinOp) for item in ast.walk(node)) == 9898
    assert sum(isinstance(item, ast.Constant) for item in ast.walk(node)) == 9899
    assert trace.expression(node, module, {}, "") == subject._Value()
    assert trace.steps == 19_797 and trace.budget == [19_870]
    seed = _ObservedTrace([module], trace.context, 1, set(), [73])
    seed.block(module.tree.body, module, module.env, "")
    assert seed.steps == 19_800 and seed.budget == [19_873]
    seed.function(module.functions["test_total"])
    assert seed.steps == 19_809 and seed.budget == [19_882]
    assert len(seed.observed) == side
    assert sys.getrecursionlimit() == limit


def _git(repo, *args):
    run = subprocess.run(["git", "-C", str(repo), *args], check=False, capture_output=True,
                         text=True, encoding="utf-8", timeout=30)
    assert run.returncode == 0, run.stdout + run.stderr
    return run.stdout.strip()


@pytest.mark.parametrize("shape", [cases.DEEP, cases.SIBLING])
@pytest.mark.parametrize("weakening", [True, False])
def test_owned_deep_and_sibling_reach_a_real_cli_verdict(tmp_path, shape, weakening):
    before, after = cases.pair(shape)
    if not weakening:
        # A new owned normal control: only whitespace in the existing tail.
        after = before.replace(b"observed = billing.total", b"observed=  billing.total")
        assert after != before and len(after) == len(before)
        assert after.count(b" + ") == before.count(b" + ")
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.name", "owned stand-in expression")
    _git(tmp_path, "config", "user.email", "standin-expression@example.invalid")
    _git(tmp_path, "config", "commit.gpgsign", "false")
    for path, raw in {**cases.COMMON, cases.PATH: before}.items():
        destination = tmp_path / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "owned fixed base")
    base = _git(tmp_path, "rev-parse", "HEAD")
    (tmp_path / cases.PATH).write_bytes(after)
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "owned head")
    head = _git(tmp_path, "rev-parse", "HEAD")
    run = subprocess.run(
        [sys.executable, "-B", "-m", "checkwash", "check", f"{base}..{head}",
         "--repo", str(tmp_path), "--format", "json"],
        check=False, capture_output=True, text=True, encoding="utf-8", timeout=240,
        env={**os.environ, "PYTHONUTF8": "1", "NO_COLOR": "1"},
    )
    assert run.returncode == int(weakening), run.stdout + run.stderr
    assert run.stderr == ""
    report = json.loads(run.stdout)
    assert report["config_errors"] == report["skipped_files"] == []
    assert report["verdict"] == ("block" if weakening else "pass")
    found = [finding for finding in report["findings"] if finding["rule"] == "TEST_PATCHES_SUBJECT"]
    if weakening:
        assert len(found) == 1
        assert found[0]["severity"] == "high" and found[0]["path"] == cases.PATH
        assert "app.billing.total" in found[0]["message"]
    else:
        assert report["findings"] == []

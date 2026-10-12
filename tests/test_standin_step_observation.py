"""Owned fake traceback controls; no Checkwash or corpus import/execution."""
import ast
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


PATH = Path(__file__).resolve().parents[1] / "tools" / "standin_step_observation.py"
SPEC = importlib.util.spec_from_file_location("standin_step_observation_owned", PATH)
observer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(observer)


class OriginalFailure(Exception):
    pass


class FakeTrace:
    def __init__(self, steps, shared, side=0):
        self.steps, self.budget, self.side = steps, [shared], side
        self.stack = []
        self.secret = b"DO_NOT_SERIALIZE_TRACE_CONTENT"
        self.failure = OriginalFailure("DO_NOT_SERIALIZE_ERROR_ARGUMENT")

    def _step(self):
        self.steps += 1
        self.budget[0] += 1
        if self.steps > 20_000 or self.budget[0] > 1_000_000:
            raise self.failure

    def expression(self, node, module, env, qualname):
        self._step()

    def block(self, node, module, env, qualname):
        self.expression(node, module, env, qualname)


def observed_for_test(trace, test_path="tests/test_fake.py", qualname="test_target", side=0):
    module = SimpleNamespace(path=test_path, source=b"DO_NOT_SERIALIZE_MODULE_SOURCE")
    node = ast.Constant(value="DO_NOT_SERIALIZE_NODE_VALUE", lineno=9, end_lineno=9)
    trace.block(node, module, {"token": "DO_NOT_SERIALIZE_ENV"}, qualname)


def read(error):
    return observer.snapshot(error, step=FakeTrace._step, block=FakeTrace.block,
                             expression=FakeTrace.expression, observed_for_test=observed_for_test,
                             local_limit=20_000, shared_limit=1_000_000)


@pytest.mark.parametrize("steps,shared,flags", [
    (20_000, 20_000, {"per_trace": True, "shared": False}),
    (10, 1_000_000, {"per_trace": False, "shared": True}),
    (20_000, 1_000_000, {"per_trace": True, "shared": True}),
])
@pytest.mark.parametrize("side", [0, 1])
def test_exact_counter_flags_nearest_frame_side_and_original_identity(steps, shared, flags, side):
    trace = FakeTrace(steps, shared, side)
    try:
        observed_for_test(trace, side=side)
    except OriginalFailure as error:
        original_tb = error.__traceback__
        result = read(error)
        assert error is trace.failure and error.__traceback__ is original_tb
    else:
        pytest.fail("fake step must raise")
    assert trace.steps == steps + 1 and trace.budget == [shared + 1]
    assert result["counters"] == {"per_trace": steps + 1, "shared": shared + 1}
    assert result["exceeded"] == flags
    assert result["limits"] == {"per_trace": 20_000, "shared": 1_000_000}
    assert result["side"] == result["test_context"]["side"] == side
    assert result["nearest_operation"]["function"] == "expression"
    assert result["nearest_operation"]["module_path"] == "tests/test_fake.py"
    assert result["nearest_operation"]["qualname"] == "test_target"
    assert result["nearest_operation"]["node_type"] == "Constant"
    assert result["nearest_operation"]["node_line"] == 9
    assert "DO_NOT_SERIALIZE" not in json.dumps(result)


def test_equal_limits_do_not_raise_or_call_an_observer():
    trace = FakeTrace(19_999, 999_999)
    assert observed_for_test(trace) is None
    assert trace.steps == 20_000 and trace.budget == [1_000_000]


def test_seed_has_no_fabricated_per_test_context():
    trace = FakeTrace(20_000, 21_000)
    module = SimpleNamespace(path="tests/test_fake.py")
    try:
        trace.block(ast.Constant(value=0, lineno=3), module, {}, "")
    except OriginalFailure as error:
        result = read(error)
    assert result["test_context"] is None
    assert result["nearest_operation"]["qualname"] == ""


def test_expression_none_is_original_absence_not_an_observer_failure():
    trace = FakeTrace(20_000, 21_000)
    try:
        trace.expression(None, SimpleNamespace(path="tests/test_fake.py"), {}, "test_none")
    except OriginalFailure as error:
        result = read(error)
    assert result["nearest_operation"]["node_type"] is None
    assert result["nearest_operation"]["node_line"] is None
    assert result["nearest_operation"]["qualname"] == "test_none"


def test_unrelated_exception_keeps_no_step_frame_unknown_counters():
    try:
        raise OriginalFailure()
    except OriginalFailure as error:
        result = read(error)
    assert result["state"] == "NO_STEP_FRAME"
    assert result["counters"] is result["exceeded"] is result["side"] is None
    assert result["nearest_operation"] is result["test_context"] is None


def test_same_name_function_is_not_the_original_step_code():
    def _step():
        raise OriginalFailure()
    try:
        _step()
    except OriginalFailure as error:
        assert read(error)["state"] == "NO_STEP_FRAME"


@pytest.mark.parametrize("field,value", [("steps", True), ("budget", [False]), ("budget", []),
                                        ("budget", (1,)), ("side", True), ("side", 2)])
def test_malformed_counter_metadata_fails_without_changing_exception(field, value):
    trace = FakeTrace(20_000, 21_000)
    try:
        observed_for_test(trace)
    except OriginalFailure as error:
        setattr(trace, field, value)
        original_tb = error.__traceback__
        with pytest.raises(ValueError):
            read(error)
        assert error is trace.failure and error.__traceback__ is original_tb


def test_traceback_observer_bound_does_not_consume_or_replace_original_error(monkeypatch):
    trace = FakeTrace(20_000, 21_000)
    try:
        observed_for_test(trace)
    except OriginalFailure as error:
        original_tb = error.__traceback__
        monkeypatch.setattr(observer, "MAX_FRAMES", 1)
        with pytest.raises(ValueError, match="observer traceback bound"):
            read(error)
        assert error is trace.failure and error.__traceback__ is original_tb


def test_unreviewed_source_declines_before_any_original_call():
    def original():
        pytest.fail("observer must not execute an original function")
    with pytest.raises(ValueError, match="unreviewed stand-in source"):
        observer.observe(OriginalFailure(), original, b"not a reviewed engine")

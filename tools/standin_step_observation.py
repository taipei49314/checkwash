"""Exception-only, allowlisted metadata; never an engine step wrapper."""
from __future__ import annotations

import ast
import hashlib
import types


SOURCE_HASHES = frozenset({
    "d97c66607d4abe5add638e552d71ad153b879ba9a894d3422848aaa1a119c89e",  # 30cf
    "51c71734b717f28d107a19401483e80cd9cbecd68ff3687b9de220398979f591",  # 6bfa
})
LOCAL_LIMIT = 20_000  # Literal in _Trace._step in both exact source hashes.
SHARED_LIMIT = 1_000_000  # _MAX_ANALYSIS_STEPS in both exact source hashes.
MAX_FRAMES = 128  # Observer bound, not an engine recursion/resource limit.


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def location(trace):
    code = trace.tb_frame.f_code
    return {"file": code.co_filename, "function": code.co_name, "line": trace.tb_lineno}


def snapshot(error, *, step, block, expression, observed_for_test,
             local_limit, shared_limit):
    """Pure read of the existing traceback. Tests supply fake code identities.

    The caller protects recording errors and re-raises the original exception.
    Values are observed after the original increments; nothing is re-evaluated.
    """
    require(type(local_limit) is int and local_limit > 0
            and type(shared_limit) is int and shared_limit > 0, "invalid bound metadata")
    functions = (step, block, expression, observed_for_test)
    require(all(type(function) is types.FunctionType for function in functions), "unexpected original function type")
    frames = []
    trace = error.__traceback__
    while trace is not None:
        require(len(frames) < MAX_FRAMES, "observer traceback bound")
        frames.append(trace)
        trace = trace.tb_next
    matches = [trace for trace in frames if trace.tb_frame.f_code is step.__code__]
    limits = {"per_trace": local_limit, "shared": shared_limit}
    if not matches:
        return {"state": "NO_STEP_FRAME", "limits": limits, "counters": None,
                "exceeded": None, "step_frame": None, "nearest_operation": None,
                "test_context": None, "side": None, "function_stack": None}
    require(len(matches) == 1, "ambiguous original step frame")
    step_frame = matches[0]
    subject = step_frame.tb_frame.f_locals.get("self")
    state = vars(subject)
    steps, budget, side = state.get("steps"), state.get("budget"), state.get("side")
    require(type(steps) is int and steps >= 0 and type(budget) is list and len(budget) == 1
            and type(budget[0]) is int and budget[0] >= 0, "invalid original counter metadata")
    require(type(side) is int and side in (0, 1), "invalid original side metadata")
    stack = state.get("stack")
    require(type(stack) is list and len(stack) <= 8, "invalid original function-stack metadata")
    stack_rows = []
    for item in stack:
        require(type(item) is tuple and len(item) == 2 and all(type(part) is str for part in item),
                "invalid original function-stack entry")
        stack_rows.append({"path": item[0], "qualname": item[1]})
    nearest = None
    test_context = None
    for frame in reversed(frames):
        code, local = frame.tb_frame.f_code, frame.tb_frame.f_locals
        if nearest is None and (code is expression.__code__ or code is block.__code__) and local.get("self") is subject:
            module, qualname, node = local.get("module"), local.get("qualname"), local.get("node")
            path = vars(module).get("path")
            require(type(path) is str and type(qualname) is str, "invalid original module/qualname metadata")
            # expression(None) is a real original path: _step precedes its
            # early return. Absence is metadata, not an invented AST node.
            require(node is None or isinstance(node, ast.AST) and type(node).__module__ == "ast", "invalid original AST metadata")
            node_values = vars(node) if node is not None else {}
            line, end = node_values.get("lineno"), node_values.get("end_lineno")
            require((line is None or type(line) is int) and (end is None or type(end) is int), "invalid original AST span")
            nearest = {**location(frame), "module_path": path, "qualname": qualname,
                       "node_type": type(node).__name__ if node is not None else None,
                       "node_line": line, "node_end_line": end}
        if test_context is None and code is observed_for_test.__code__:
            path, qualname, test_side = local.get("test_path"), local.get("qualname"), local.get("side")
            require(type(path) is str and type(qualname) is str and type(test_side) is int
                    and test_side == side, "invalid original per-test context")
            test_context = {**location(frame), "test_path": path, "qualname": qualname, "side": test_side}
    return {"state": "STEP_FRAME_OBSERVED", "limits": limits,
            "counters": {"per_trace": steps, "shared": budget[0]},
            "exceeded": {"per_trace": steps > local_limit, "shared": budget[0] > shared_limit},
            "step_frame": location(step_frame), "nearest_operation": nearest,
            "test_context": test_context, "side": side,
            "side_name": "before" if side == 0 else "after", "function_stack": stack_rows}


def observe(error, original_installation_events, source_bytes):
    """Bind the real-code lookup and both limits to the selected qualified pyz."""
    require(type(source_bytes) is bytes, "source identity requires bytes")
    digest = hashlib.sha256(source_bytes).hexdigest()
    require(digest in SOURCE_HASHES, "unreviewed stand-in source")
    original = original_installation_events
    require(type(original) is types.FunctionType
            and original.__module__ == "checkwash.frontends.python.standin_installations"
            and original.__name__ == "installation_events", "unexpected original installation function")
    namespace = original.__globals__
    trace = namespace["_Trace"]
    require(type(namespace["_MAX_ANALYSIS_STEPS"]) is int
            and namespace["_MAX_ANALYSIS_STEPS"] == SHARED_LIMIT, "live shared limit differs from pinned source")
    functions = {"step": trace._step, "block": trace.block, "expression": trace.expression,
                 "observed_for_test": namespace["_observed_for_test"]}
    require(all(type(function) is types.FunctionType and function.__globals__ is namespace
                for function in functions.values()), "original code identities do not share the pinned module")
    result = snapshot(error, **functions, local_limit=LOCAL_LIMIT, shared_limit=SHARED_LIMIT)
    return {**result, "source_sha256": digest,
            "limits_provenance": {"per_trace": "literal in exact pinned _Trace._step source",
                                  "shared": "exact pinned source plus live _MAX_ANALYSIS_STEPS"}}

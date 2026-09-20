"""Literal pytest hook effects that suppress execution or replace an outcome.

Hook names alone are not evidence: reporting/async plugins legitimately use
the same hooks. Follow the yielded Result/TestReport and the item callback,
without importing pytest or executing repository source. Unknown predicates
retain both paths; dead literal branches and nested uncalled functions do not.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field, replace
import hashlib

from checkwash.ir.astutil import stable_dump

_HOOKS = {"pytest_pyfunc_call", "pytest_runtest_call", "pytest_runtest_protocol",
          "pytest_runtest_makereport", "pytest_runtest_logreport"}


@dataclass
class _State:
    bindings: dict[str, str] = field(default_factory=dict)
    effects: dict[str, ast.AST] = field(default_factory=dict)
    called: bool = False
    stopped: bool = False
    guards: tuple[str, ...] = ()

    def copy(self):
        return replace(self, bindings=dict(self.bindings), effects=dict(self.effects))


def _truth(node):
    if isinstance(node, ast.Constant):
        return bool(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        value = _truth(node.operand)
        return not value if value is not None else None
    return None


def _kind(node, state, hook, wrapper):
    if isinstance(node, ast.Name):
        return state.bindings.get(node.id)
    if isinstance(node, ast.Yield):
        return "report" if hook == "pytest_runtest_makereport" and wrapper == "wrapper" else "result"
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        if node.func.attr == "get_result" and _kind(node.func.value, state, hook, wrapper) == "result":
            return "report" if hook == "pytest_runtest_makereport" else None
    return None


def _calls(node):
    """Expression calls only; constructing a callable does not run its body."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
        return
    if isinstance(node, ast.Call):
        yield node
    for child in ast.iter_child_nodes(node):
        yield from _calls(child)


def _expression(node, state, hook, wrapper):
    for call in _calls(node):
        fn = call.func
        if isinstance(fn, ast.Attribute):
            receiver = _kind(fn.value, state, hook, wrapper)
            if receiver == "item" and fn.attr in {"obj", "runtest"}:
                state.called = True
            if (receiver == "result" and fn.attr == "force_result" and call.args
                    and isinstance(call.args[0], ast.Constant) and call.args[0].value is None
                    and hook in {"pytest_runtest_call", "pytest_runtest_protocol"}):
                state.effects["exception-suppressed"] = call
        if (isinstance(fn, ast.Name) and fn.id == "setattr" and "setattr" not in state.bindings
                and len(call.args) >= 3 and isinstance(call.args[1], ast.Constant)
                and call.args[1].value == "outcome" and _kind(call.args[0], state, hook, wrapper) == "report"):
            _outcome(call.args[2], call, state)


def _outcome(value, node, state):
    if isinstance(value, ast.Constant) and value.value == "passed":
        state.effects["report-passed"] = node
    else:
        state.effects.pop("report-passed", None)


def _walk(statements, states, hook, wrapper):
    for stmt in statements:
        next_states = []
        for state in states:
            if state.stopped:
                next_states.append(state)
                continue
            if isinstance(stmt, ast.If):
                truth = _truth(stmt.test)
                for chosen, body in ((True, stmt.body), (False, stmt.orelse)):
                    if truth is not None and truth != chosen:
                        continue
                    branch = state.copy()
                    if truth is None:
                        branch.guards += (("" if chosen else "not:") + stable_dump(stmt.test),)
                    next_states.extend(_walk(body, [branch], hook, wrapper))
                continue
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                state.bindings[stmt.name] = "local"
            elif isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                value = stmt.value
                if value is not None:
                    _expression(value, state, hook, wrapper)
                targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        state.bindings[target.id] = _kind(value, state, hook, wrapper) or "local"
                    elif (isinstance(target, ast.Attribute) and target.attr == "outcome"
                          and _kind(target.value, state, hook, wrapper) == "report"):
                        _outcome(value, stmt, state)
            elif isinstance(stmt, ast.Return):
                if stmt.value is not None:
                    _expression(stmt.value, state, hook, wrapper)
                if (hook in {"pytest_pyfunc_call", "pytest_runtest_protocol"} and not wrapper
                        and not state.called and isinstance(stmt.value, ast.Constant) and stmt.value.value is True):
                    state.effects["call-skipped"] = stmt
                state.stopped = True
            elif isinstance(stmt, ast.Raise):
                state.effects.clear()
                state.stopped = True
            elif isinstance(stmt, ast.Expr):
                _expression(stmt.value, state, hook, wrapper)
            elif isinstance(stmt, ast.Try):
                # New-style wrappers may consume an AssertionError thrown back
                # through yield. Plain reporting/re-raising wrappers stay quiet.
                yield_in_body = any(isinstance(n, ast.Yield) for s in stmt.body for n in ast.walk(s))
                if wrapper == "wrapper" and hook == "pytest_runtest_call" and yield_in_body:
                    for handler in stmt.handlers:
                        caught = handler.type
                        names = {n.id for n in ast.walk(caught) if isinstance(n, ast.Name)} if caught else {"BaseException"}
                        if (names & {"AssertionError", "Exception", "BaseException"}
                                and all(isinstance(s, (ast.Pass, ast.Return)) for s in handler.body)):
                            state.effects["exception-suppressed"] = handler
                state_list = _walk(stmt.body + stmt.orelse + stmt.finalbody, [state], hook, wrapper)
                next_states.extend(state_list)
                continue
            # Unsupported control flow has no positive execution proof. Do
            # not scan its descendants as though they all execute.
            next_states.append(state)
        states = next_states
        if len(states) > 64:
            return []
    return states


def runtime_controls(tree: ast.Module):
    """Return stable effect names and concrete source evidence for live hooks."""
    bindings = {}
    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            bindings[stmt.name] = stmt
        elif isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            for target in stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]:
                if isinstance(target, ast.Name):
                    bindings.pop(target.id, None)
    for name, func in bindings.items():
        if name not in _HOOKS:
            continue
        wrapper = None
        for dec in func.decorator_list:
            if isinstance(dec, ast.Call):
                for kw in dec.keywords:
                    if kw.arg in {"wrapper", "hookwrapper"} and _truth(kw.value) is True:
                        wrapper = kw.arg
        state = _State()
        for arg in func.args.posonlyargs + func.args.args + func.args.kwonlyargs:
            state.bindings[arg.arg] = ("item" if arg.arg in {"item", "pyfuncitem"}
                                       else "report" if arg.arg == "report" and name == "pytest_runtest_logreport" else "local")
        for branch in _walk(func.body, [state], name, wrapper):
            for effect, node in branch.effects.items():
                guard = hashlib.sha256("|".join(branch.guards).encode()).hexdigest()[:16]
                yield f"conftest.runtime.{name}.{effect}.{guard}", node

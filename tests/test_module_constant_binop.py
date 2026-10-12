"""Canonical module constants retain native text and bounded root fallback."""

import ast
import sys
from pathlib import Path

import pytest

from checkwash import engine
from checkwash.frontends.python.syntax import parse_module

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
import standin_cost_cases as cases


@pytest.mark.parametrize("source", [
    "a + b * c",
    "(a ** b) ** c",
    "('中文' + value) - (lambda: 1)",
])
def test_shallow_binary_constant_keeps_native_expression_text(source):
    expected = ast.unparse(ast.parse(source, mode="eval"))
    assert engine._canonical_constants({"answer": source}) == {"answer": expected}


@pytest.mark.parametrize("source", ["callee(1)", "-name", "(x, y)"])
def test_nonbinary_constant_keeps_original_expression_wrapper(monkeypatch, source):
    tree = ast.parse(source, mode="eval")
    native = ast.unparse
    expected = native(tree)
    received = []

    def unparse(node):
        received.append(node)
        return native(node)

    def no_binary_route(_node):
        raise AssertionError("nonbinary input reached binary fallback")

    monkeypatch.setattr(engine, "parse_text", lambda text, mode: tree)
    monkeypatch.setattr(engine.ast, "unparse", unparse)
    monkeypatch.setattr(engine, "_binding_key", no_binary_route)
    assert engine._canonical_constants({"answer": source}) == {"answer": expected}
    assert received == [tree]


@pytest.mark.parametrize("exception", [RecursionError, RuntimeError])
def test_nonbinary_unparse_exception_still_escapes(monkeypatch, exception):
    failure = exception("owned nonbinary failure")

    def fail(_node):
        raise failure

    monkeypatch.setattr(engine.ast, "unparse", fail)
    with pytest.raises(exception) as caught:
        engine._canonical_constants({"answer": "callee(1)"})
    assert caught.value is failure


def test_existing_value_error_skip_keeps_later_constants(monkeypatch):
    native = ast.unparse

    def unparse(node):
        if isinstance(node, ast.Expression) and isinstance(node.body, ast.Name):
            raise ValueError("owned native representation failure")
        return native(node)

    monkeypatch.setattr(engine.ast, "unparse", unparse)
    assert engine._canonical_constants({"bad": "missing", "good": "7"}) == {"good": "7"}


def test_unparsed_constant_is_still_absent_and_later_constants_survive():
    assert engine._canonical_constants({"bad": "(", "good": "7"}) == {"good": "7"}


def test_binary_native_recursion_uses_existing_emitter_without_changing_text(monkeypatch):
    tree = ast.parse("(left + right) * (other - last)", mode="eval")
    native = ast.unparse
    expected = native(tree)
    attempts = []

    def unparse(node):
        if node is tree.body:
            attempts.append(node)
            raise RecursionError("owned root binary native failure")
        return native(node)

    monkeypatch.setattr(engine, "parse_text", lambda text, mode: tree)
    monkeypatch.setattr(engine.ast, "unparse", unparse)
    assert engine._canonical_constants({"answer": "owned"}) == {"answer": expected}
    assert attempts == [tree.body]


def test_original_9899_leaf_constant_retains_complete_canonical_text(monkeypatch):
    # Isolate the already-successful parse path on every interpreter. This
    # source-backed AST is not evidence that each native eval parser accepts it.
    before, _after = cases.pair(cases.DEEP)
    module = parse_module(before.decode())
    root = module.body[1].value
    assert len(before) == 1_000_000 and isinstance(root, ast.BinOp)
    assert sum(isinstance(node, ast.BinOp) for node in ast.walk(root)) == 9898
    leaves = [node.value for node in ast.walk(root) if isinstance(node, ast.Constant)]
    atom = "0123456789abcdef" * 6
    assert leaves == [atom] * 9899
    segment = ast.get_source_segment(before.decode(), root)
    assert segment is not None
    tree = ast.Expression(body=root)
    received = []

    def parsed(text, mode):
        assert text == segment and mode == "eval"
        received.append(tree)
        return tree

    monkeypatch.setattr(engine, "parse_text", parsed)
    limit = sys.getrecursionlimit()
    expected = " + ".join([repr(atom)] * 9899)
    assert engine._canonical_constants({"padding": segment}) == {"padding": expected}
    assert received == [tree]
    assert sys.getrecursionlimit() == limit


def test_unsupported_deep_nonbinary_leaf_is_not_silently_dropped(monkeypatch):
    nested = ast.Constant(value="x")
    for _ in range(2000):
        nested = ast.BinOp(left=nested, op=ast.Add(), right=ast.Constant(value="x"))
    root = ast.BinOp(
        left=ast.Call(func=ast.Name(id="consume", ctx=ast.Load()), args=[nested], keywords=[]),
        op=ast.Add(), right=ast.Constant(value="x"),
    )
    tree = ast.Expression(body=root)
    monkeypatch.setattr(engine, "parse_text", lambda text, mode: tree)
    limit = sys.getrecursionlimit()
    with pytest.raises(RecursionError):
        engine._canonical_constants({"answer": "owned unsupported leaf"})
    assert sys.getrecursionlimit() == limit

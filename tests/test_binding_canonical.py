"""Exact stdlib spelling controls for the narrow R1 binding fallback.

These sources are parsed, never executed. The original R1 frontend/CLI,
fingerprint, corpus and hostile-input tests remain unchanged and required.
"""

import ast
import sys

import pytest

from checkwash.frontends.python import binding_canonical as canonical
from checkwash.frontends.python import frontend


OPERATORS = (
    ast.Add, ast.Sub, ast.Mult, ast.MatMult, ast.Div, ast.FloorDiv, ast.Mod,
    ast.Pow, ast.LShift, ast.RShift, ast.BitOr, ast.BitXor, ast.BitAnd,
)
SYMBOLS = ("+", "-", "*", "@", "/", "//", "%", "**", "<<", ">>", "|", "^", "&")
LEAVES = (
    "value", "42", "1.5", "2j", "-2", "+value", "~value", "not value",
    "-(left ** right)", "left < right", "left and right", "left or right",
    "yes if condition else no", "lambda x: x + 1", "(name := value)",
    "(yield value)", "(yield from values)", "await value()",
    "()", "(value,)", "(left, right)", "[left, right]", "{left: right}",
    "{left, right}", "[x for x in values]", "(x for x in values)",
    "call(left + right, named=value)", "value[left + right]", "3 .real",
    "f'{value!r:>10}'", "b'byte text'", "'a\\nb'",
    "_checkwash_binding_context", "'_checkwash_binding_context + '",
    "' + _checkwash_binding_context'", "f'{_checkwash_binding_context}'",
)


def _name(text):
    return ast.Name(id=text, ctx=ast.Load())


def _assert_matches_stdlib(tree, context):
    before = ast.dump(tree, include_attributes=True)
    expected = ast.unparse(tree)
    actual = canonical._iterative_binop(tree)
    assert actual == expected, (context, expected, actual)
    assert ast.dump(tree, include_attributes=True) == before, context
    # Equality of spelling is the primary contract; this separately rejects
    # any accidental semantic/grouping drift in the emitted expression.
    assert ast.dump(ast.parse(actual, mode="eval").body) == ast.dump(tree), context


@pytest.mark.parametrize("outer", OPERATORS, ids=lambda op: op.__name__)
def test_every_binary_operator_pair_preserves_each_association(outer):
    for inner in OPERATORS:
        for right in (False, True):
            child = ast.BinOp(left=_name("middle"), op=inner(), right=_name("last"))
            tree = ast.BinOp(
                left=_name("first") if right else child,
                op=outer(), right=child if right else _name("first"),
            )
            _assert_matches_stdlib(tree, (outer.__name__, inner.__name__, right))


@pytest.mark.parametrize("operator", OPERATORS, ids=lambda op: op.__name__)
def test_leaf_parentheses_and_sentinel_text_keep_stdlib_bytes(operator):
    for source in LEAVES:
        for right in (False, True):
            leaf = ast.parse(source, mode="eval").body
            tree = ast.BinOp(
                left=_name("outside") if right else leaf,
                op=operator(), right=leaf if right else _name("outside"),
            )
            _assert_matches_stdlib(tree, (operator.__name__, source, right))


def test_fallback_preserves_complete_350_term_key_without_changing_limit(monkeypatch):
    expected = " + ".join(["value(1)", *(["1"] * 349)])
    tree = ast.parse(expected, mode="eval").body
    original = ast.unparse
    seen = []
    limit = sys.getrecursionlimit()

    def exhausted_root_only(node):
        seen.append(node)
        if node is tree:
            raise RecursionError("owned root traversal failure")
        return original(node)

    monkeypatch.setattr(canonical.ast, "unparse", exhausted_root_only)
    assert canonical.binding_key(tree) == expected
    assert sys.getrecursionlimit() == limit
    assert seen[0] is tree
    assert len(seen) == 351  # One failed root plus one shallow context per leaf.


def test_successful_stdlib_result_is_returned_without_emitter(monkeypatch):
    tree = ast.parse("left + right * last", mode="eval").body
    expected = ast.unparse(tree)

    def unexpected_retry(node):
        raise AssertionError("successful stdlib key must not use fallback")

    monkeypatch.setattr(canonical, "_iterative_binop", unexpected_retry)
    assert canonical.binding_key(tree) == expected


@pytest.mark.parametrize("source", ["value", "left + call(value)"])
def test_remaining_recursion_errors_propagate_instead_of_empty_keys(monkeypatch, source):
    tree = ast.parse(source, mode="eval").body

    def exhausted(node):
        raise RecursionError("owned unsupported recursive leaf")

    monkeypatch.setattr(canonical.ast, "unparse", exhausted)
    with pytest.raises(RecursionError, match="owned unsupported recursive leaf"):
        canonical.binding_key(tree)


@pytest.mark.parametrize("right", [False, True])
def test_changed_stdlib_context_framing_is_visible(monkeypatch, right):
    monkeypatch.setattr(canonical.ast, "unparse", lambda node: "missing endpoint")
    with pytest.raises(RuntimeError, match="stdlib changed binding operand"):
        canonical._operand_text(_name("value"), ast.Add(), right)


@pytest.mark.parametrize("symbol", SYMBOLS)
def test_both_binding_consumers_keep_existing_formatting_identity(symbol):
    expression = f"left {symbol} (middle {symbol} right)"
    canonical_key = ast.unparse(ast.parse(expression, mode="eval").body)
    keys = []
    for rhs in (expression, f"( left  {symbol}  ( middle  {symbol}  right ) )"):
        function = ast.parse(f"def test_value():\n    got = {rhs}\n").body[0]
        definitions, references = frontend._binding_maps(function)
        ordered = frontend._ordered_bindings(function)
        assert definitions["got"] == canonical_key
        assert ordered["got"][0][2] == canonical_key
        assert references["got"] == ordered["got"][0][3] == ("left", "middle", "right")
        keys.append((definitions, ordered))
    assert keys[0] == keys[1]


@pytest.mark.parametrize("source", [
    "call(left + right)", "[left + right]", "{'key': left + right}",
    "(left + right,)", "-(left + right)", "lambda: left + right",
    "f'{left + right}'", "(got := left + right)",
])
def test_nonbinary_root_keeps_original_binding_consumer_path(monkeypatch, source):
    tree = ast.parse(source, mode="eval").body
    assert not isinstance(tree, ast.BinOp)
    expected = ast.unparse(tree)
    original = frontend._binding_key

    def only_binary_roots(node):
        assert isinstance(node, ast.BinOp), "nonbinary RHS must keep its original call site"
        return original(node)

    monkeypatch.setattr(frontend, "_binding_key", only_binary_roots)
    function = ast.parse(f"def test_value():\n    result = {source}\n").body[0]
    assert frontend._binding_maps(function)[0]["result"] == expected
    assert frontend._ordered_bindings(function)["result"][0][2] == expected

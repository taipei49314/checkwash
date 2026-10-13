"""Owned dump parity and production caller controls; fixture labels are unchanged."""

import ast
import hashlib
import importlib.util
import sys
from pathlib import Path

import pytest

from checkwash.frontends.python import frontend, syntax
from checkwash.ir import astutil


def native_dump(node):
    options = {"show_empty": True} if sys.version_info >= (3, 13) else {}
    return ast.dump(node, include_attributes=False, **options)


@pytest.mark.parametrize("source", [
    "x = 'a' + 'b' + 'c'\n",
    "变量 = u'雪' + r'\\u1234' + '🙂'\n",
    "x = b'a' + b'b'\n",
    "x = None\ny = ...\nz = True\n",
    "x = 1 + 2j\ny = -0.0\n",
    "x = [1, 2]\ny = {}\nz = ()\n",
    "def f(x, /, y=1, *, z=None):\n    return x + y * z\n",
    "async def f(x):\n    return await x()\n",
    "class C(Base):\n    value: int = 1\n",
    "def f():\n    pass\n",
    "x = {a: None for a in items if a}\n",
    "try:\n    f()\nexcept ValueError:\n    raise\n",
    "match value:\n    case {'a': item}:\n        result = item\n",
    "x = f'{name!r:>10}'\n",
])
def test_forced_dump_fallback_matches_native_bytes_and_digest(monkeypatch, source):
    tree = ast.parse(source)
    expected = native_dump(tree)
    old_limit = sys.getrecursionlimit()
    calls = []

    def failing(node, **options):
        calls.append((node, options))
        raise RecursionError("owned native dump failure")

    monkeypatch.setattr(astutil.ast, "dump", failing)
    actual = astutil.stable_dump(tree)
    assert actual == expected
    assert len(calls) == 1 and calls[0][0] is tree
    assert sys.getrecursionlimit() == old_limit
    assert frontend._fingerprint(tree) == hashlib.sha256(expected.encode("utf-8")).hexdigest()[:16]


def test_successful_native_dump_is_returned_without_fallback(monkeypatch):
    tree = ast.parse("x = 1\n")
    expected = native_dump(tree)
    native = ast.dump
    calls = []

    def recording(node, **options):
        calls.append((node, options))
        return native(node, **options)

    def forbidden(_node, _failure):
        pytest.fail("successful native dump entered fallback")

    monkeypatch.setattr(astutil.ast, "dump", recording)
    monkeypatch.setattr(astutil, "_iterative_dump", forbidden)
    assert astutil.stable_dump(tree) == expected
    options = {"include_attributes": False}
    if sys.version_info >= (3, 13):
        options["show_empty"] = True
    assert calls == [(tree, options)]


@pytest.mark.parametrize("failure", [TypeError("owned"), ValueError("owned"), MemoryError("owned")])
def test_non_recursion_dump_failures_are_not_reinterpreted(monkeypatch, failure):
    def failing(_node, **_options):
        raise failure

    def forbidden(_node, _failure):
        pytest.fail("non-recursion failure entered fallback")

    monkeypatch.setattr(astutil.ast, "dump", failing)
    monkeypatch.setattr(astutil, "_iterative_dump", forbidden)
    with pytest.raises(type(failure)) as raised:
        astutil.stable_dump(ast.Name(id="x", ctx=ast.Load()))
    assert raised.value is failure


def test_missing_optional_none_required_none_and_empty_lists_match_native():
    class Owned(ast.AST):
        _fields = ("missing", "optional", "required", "empty", "child")
        optional = None

    node = Owned()
    node.optional = node.required = None
    node.empty = []
    node.child = ast.Constant(value="雪", kind=None)
    node.lineno = 999
    node.extra_non_field = "ignored"
    expected = native_dump(node)
    assert astutil._iterative_dump(node, RecursionError("owned")) == expected
    assert "required=None" in expected and "empty=[]" in expected
    assert "optional=" not in expected and "missing=" not in expected
    assert "lineno=" not in expected and "extra_non_field=" not in expected


def test_shared_subtree_is_emitted_for_each_edge_without_mutation():
    leaf = ast.Constant(value="shared")
    node = ast.BinOp(left=leaf, op=ast.Add(), right=leaf)
    expected = native_dump(node)
    assert astutil._iterative_dump(node, RecursionError("owned")) == expected
    assert node.left is node.right is leaf
    assert expected.count("Constant(value='shared')") == 2


@pytest.mark.parametrize("kind", ["ast", "list"])
def test_active_cycle_retains_original_recursion_failure(kind):
    class Cycle(ast.AST):
        _fields = ("child",)
        child: object

    node = Cycle()
    if kind == "ast":
        node.child = node
    else:
        cycle: list[object] = []
        cycle.append(cycle)
        node.child = cycle
    failure = RecursionError("owned original cycle")
    with pytest.raises(RecursionError) as raised:
        astutil._iterative_dump(node, failure)
    assert raised.value is failure


@pytest.mark.parametrize("side", [0, 1])
def test_original_deep_pair_dump_keeps_every_operator_and_literal(side):
    spec = importlib.util.spec_from_file_location(
        "deep_production_owned_cases",
        Path(__file__).resolve().parents[1] / "tools" / "standin_cost_cases.py",
    )
    assert spec is not None and spec.loader is not None
    cases = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cases)
    raw = cases.pair(cases.DEEP)[side]
    tree = syntax.parse_module(raw.decode("utf-8-sig"))
    assignment = tree.body[1]
    leaves = 9899
    atom = "0123456789abcdef" * 6
    constant = "Constant(value=" + repr(atom) + ")"
    expected = (
        "Assign(targets=[Name(id='padding', ctx=Store())], value="
        + "BinOp(left=" * (leaves - 1)
        + constant
        + (", op=Add(), right=" + constant + ")") * (leaves - 1)
        + ")"
    )
    assert len(raw) == 1_000_000 and raw.count(b" + ") == leaves - 1
    before = [(id(n), getattr(n, "lineno", None), getattr(n, "col_offset", None))
              for n in ast.walk(assignment)]
    old_limit = sys.getrecursionlimit()
    actual = astutil.stable_dump(assignment)
    assert actual == expected
    assert actual.count("BinOp(") == leaves - 1
    assert actual.count("Constant(") == leaves
    assert frontend._fingerprint(assignment) == hashlib.sha256(expected.encode("utf-8")).hexdigest()[:16]
    assert sys.getrecursionlimit() == old_limit
    assert before == [(id(n), getattr(n, "lineno", None), getattr(n, "col_offset", None))
                      for n in ast.walk(assignment)]
    production = frontend.parse_python(raw, collect_tests=False)
    assert production.parse_ok
    assert production.symbols["padding"] == hashlib.sha256(expected.encode("utf-8")).hexdigest()[:16]
    assert production.constants["padding"] == raw.decode("utf-8-sig").split("\n")[1].split("=", 1)[1].strip()


@pytest.mark.parametrize("suffix", ["def broken(:\n    pass\n", "rest = (\n", "return = 1\n"])
def test_production_fallback_preserves_surrounding_invalid_source(monkeypatch, suffix):
    source = "padding = 'a' + 'b'\n" + suffix
    native = ast.parse
    calls = []

    def first_failure(text, *args, **kwargs):
        calls.append(text)
        if len(calls) == 1:
            raise RecursionError("owned initial parse failure")
        return native(text, *args, **kwargs)

    monkeypatch.setattr(syntax.ast, "parse", first_failure)
    assert not frontend.parse_python(source.encode(), collect_tests=False).parse_ok
    assert calls[0] == source


def test_production_chain_format_is_stable_but_a_changed_leaf_changes_the_digest():
    original = frontend.parse_python(b"padding = 'a' + 'b'\n", collect_tests=False)
    spaced = frontend.parse_python(b'padding  =  "a"  +  "b"\n', collect_tests=False)
    changed = frontend.parse_python(b"padding = 'a' + 'c'\n", collect_tests=False)
    assert original.parse_ok and spaced.parse_ok and changed.parse_ok
    assert original.symbols["padding"] == spaced.symbols["padding"]
    assert original.symbols["padding"] != changed.symbols["padding"]

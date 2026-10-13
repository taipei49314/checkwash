"""Source-only inputs: stdlib AST parity and the unchanged owned deep pair."""

import ast
import io
import json
import sys
import tokenize
from pathlib import Path

import pytest

from checkwash.change import EngineError
from checkwash.frontends.python import frontend, syntax
from checkwash.frontends.python import standin_installations as subject

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
import standin_cost_cases as cases


def force_first_recursion(monkeypatch):
    native = ast.parse
    failure = RecursionError("owned first parse only")
    calls = []

    def parse(source, *args, **kwargs):
        calls.append(source)
        if len(calls) == 1:
            raise failure
        return native(source, *args, **kwargs)

    monkeypatch.setattr(syntax.ast, "parse", parse)
    return failure, calls


@pytest.mark.parametrize("source", [
    "arbitrary = 'a' + 'b'\n",
    "name = 'a' + 'b' + 'c'",
    "name\t=\t'a'\t+\t'b'\r\n",
    "from mod import item\nx = 'a' + 'b'\ndef tail():\n    return item\n",
    "a = '0' + '0'\nother = 0\nb = '0' + '0' + '0'\n",
    "变量 = '雪' + 'é' + '🙂'\n尾 = 1\n",
    "K = u'雪' + r'\\u1234' + '\\n'\n",
    "x = '\\'' + '\"' + 'a\\tb'\n",
    "x = '''one line''' + \"\"\"still one line\"\"\"\n",
    "x = '\u2028' + '\u2029'\n",
    "# lead\nx = 'a' + 'b'\n# tail\n",
    "blob = b'a' + b'b'\nx = 'a' + 'b'\n",
    "x = 'a' + 'b'\nblob = b'a' + b'b'\n",
    "text = f'{name}' + 'b'\nx = 'a' + 'b'\n",
    "x = 'a' + 'b'\ntext = f'{name}' + 'b'\n",
])
def test_forced_fallback_matches_every_shallow_stdlib_ast_field(monkeypatch, source):
    expected = ast.parse(source)
    before = sys.getrecursionlimit()
    _failure, calls = force_first_recursion(monkeypatch)
    actual = syntax.parse_module(source)
    assert calls[0] == source
    assert sys.getrecursionlimit() == before
    assert ast.dump(actual, include_attributes=True) == ast.dump(expected, include_attributes=True)


@pytest.mark.parametrize("source", [
    "x = 'a' + 'b' * 'c'\n",
    "x = 'a' - 'b'\n",
    "x = 'a' 'b' + 'c'\n",
    "x = ('a' + 'b')\n",
    "x = 'a' + 'b'; y = 1\n",
    "x = 'a' + \\\n'b'\n",
    "x = ('a' +\n'b')\n",
    "x = '''a\nb''' + 'c'\n",
    "def f():\n    x = 'a' + 'b'\n",
    "if True: x = 'a' + 'b'\n",
    "x = b'a' + b'b'\n",
    "x = f'a' + 'b'\n",
    "x += 'a' + 'b'\n",
    "x = y = 'a' + 'b'\n",
    "x: str = 'a' + 'b'\n",
    "x = 'a' + 'b' # trailing comment\n",
    "x = 'a'\n",
])
def test_unsupported_shape_retains_the_original_recursion_failure(monkeypatch, source):
    failure, _calls = force_first_recursion(monkeypatch)
    with pytest.raises(RecursionError) as raised:
        syntax.parse_module(source)
    assert raised.value is failure


@pytest.mark.parametrize("suffix", [
    "def broken(:\n    pass\n",
    "y = (\n",
    "return = 1\n",
])
def test_surrounding_invalid_syntax_is_not_hidden_by_the_placeholder(monkeypatch, suffix):
    source = "x = 'a' + 'b'\n" + suffix
    force_first_recursion(monkeypatch)
    with pytest.raises(SyntaxError):
        syntax.parse_module(source)


@pytest.mark.parametrize("failure", [SyntaxError("invalid"), ValueError("invalid"), MemoryError("owned")])
def test_only_recursion_error_enters_fallback(monkeypatch, failure):
    def parse(_source):
        raise failure

    def forbidden(_readline):
        pytest.fail("fallback tokenizer was called for a non-recursion failure")

    monkeypatch.setattr(syntax.ast, "parse", parse)
    monkeypatch.setattr(syntax.tokenize, "generate_tokens", forbidden)
    with pytest.raises(type(failure)) as raised:
        syntax.parse_module("x = 'a' + 'b'\n")
    assert raised.value is failure


def test_successful_native_parse_does_not_tokenize(monkeypatch):
    source = "x = 'a' + 'b'\n"
    expected = ast.parse(source)
    calls = []

    def parse(raw):
        calls.append(raw)
        return expected

    def forbidden(_readline):
        pytest.fail("successful native parsing must not enter fallback")

    monkeypatch.setattr(syntax.ast, "parse", parse)
    monkeypatch.setattr(syntax.tokenize, "generate_tokens", forbidden)
    assert syntax.parse_module(source) is expected
    assert calls == [source]


def test_subject_counts_the_complete_reconstructed_tree(monkeypatch):
    source = b"x = 'a' + 'b' + 'c'\n"
    full_count = sum(1 for _node in ast.walk(ast.parse(source)))
    force_first_recursion(monkeypatch)
    monkeypatch.setattr(subject, "_MAX_SOURCE_NODES", full_count - 1)
    with pytest.raises(EngineError, match=f"nodes={full_count}, limit={full_count - 1}"):
        subject._syntax(source, path="owned.py", side="before")


def test_production_caller_recovers_with_its_complete_native_fingerprint(monkeypatch):
    source = "x = 'a' + 'b'\n"
    expected = frontend.parse_python(source.encode(), collect_tests=False)
    assert expected.parse_ok and "x" in expected.symbols
    _failure, calls = force_first_recursion(monkeypatch)
    result = frontend.parse_python(source.encode(), collect_tests=False)
    assert result.parse_ok
    assert result == expected
    assert calls[0] == source and len(calls) > 1


def test_test_caller_recovers_without_changing_the_shallow_unit(monkeypatch):
    source = b"x = 'a' + 'b'\ndef test_ok():\n    assert target() == 1\n"
    expected = frontend.parse_python(source, collect_tests=True)
    force_first_recursion(monkeypatch)
    actual = frontend.parse_python(source, collect_tests=True)
    assert expected.parse_ok and actual.parse_ok
    assert actual == expected


@pytest.mark.parametrize("side", [0, 1])
def test_original_deep_pair_has_every_literal_operator_and_source_position(
    monkeypatch, record_property, capsys, side,
):
    raw = cases.pair(cases.DEEP)[side]
    source = raw.decode("utf-8-sig")
    native = ast.parse
    first = {"state": "NOT_CALLED", "exception_class": None, "exception_message": None}

    def observe(text, *args, **kwargs):
        if first["state"] == "NOT_CALLED" and text == source and not args and not kwargs:
            first["state"] = "STARTED"
            try:
                result = native(text)
            except BaseException as error:
                first.update(state="RAISED", exception_class=type(error).__name__, exception_message=str(error))
                raise
            first["state"] = "RETURNED"
            return result
        return native(text, *args, **kwargs)

    monkeypatch.setattr(syntax.ast, "parse", observe)
    limit = sys.getrecursionlimit()
    try:
        tree = syntax.parse_module(source)
    finally:
        for key, value in first.items():
            record_property("initial_ast_parse_" + key, str(value))
        metadata = {
            "side": side, "state": first["state"],
            "exception_class": first["exception_class"],
            "exception_message": (
                first["exception_message"][:240]
                if first["exception_message"] is not None else None
            ),
        }
        with capsys.disabled():
            print("CHECKWASH_OWNED_PARSER_METADATA " + json.dumps(metadata, sort_keys=True))
    assert sys.getrecursionlimit() == limit, first
    assert len(raw) == 1_000_000 and raw.count(b" + ") == 9898, first
    assert first["state"] in ("RETURNED", "RAISED"), first
    if first["state"] == "RAISED":
        assert first["exception_class"] == "RecursionError", first

    tokens = [token for token in tokenize.generate_tokens(io.StringIO(source).readline)
              if token.type == tokenize.STRING and token.start[0] == 2]
    assert len(tokens) == 9899, first
    assignment = tree.body[1]
    assert isinstance(assignment, ast.Assign), first
    chain = assignment.value
    line = source.split("\n")[1]
    assert line.isascii(), first
    start = tokens[0].start[1]
    expected_value = "0123456789abcdef" * 6
    for token in reversed(tokens[1:]):
        assert isinstance(chain, ast.BinOp) and isinstance(chain.op, ast.Add), first
        assert (chain.lineno, chain.col_offset, chain.end_lineno, chain.end_col_offset) == (
            2, start, 2, token.end[1],
        ), first
        leaf = chain.right
        assert isinstance(leaf, ast.Constant) and leaf.value == expected_value and leaf.kind is None, first
        assert (leaf.lineno, leaf.col_offset, leaf.end_lineno, leaf.end_col_offset) == (
            2, token.start[1], 2, token.end[1],
        ), first
        chain = chain.left
    assert isinstance(chain, ast.Constant) and chain.value == expected_value and chain.kind is None, first
    assert (chain.lineno, chain.col_offset, chain.end_lineno, chain.end_col_offset) == (
        2, start, 2, tokens[0].end[1],
    ), first
    assert (assignment.lineno, assignment.col_offset, assignment.end_lineno, assignment.end_col_offset) == (
        2, 0, 2, tokens[-1].end[1],
    ), first
    assert isinstance(assignment.targets[0], ast.Name), first
    assert isinstance(assignment.targets[0].ctx, ast.Store), first
    assert assignment.targets[0].id == "padding", first
    target = assignment.targets[0]
    assert (target.lineno, target.col_offset, target.end_lineno, target.end_col_offset) == (2, 0, 2, 7), first
    assert assignment.type_comment is None and tree.type_ignores == [], first
    # The same unchanged prefix/tail gives an independent shallow node count.
    tail = (cases.BEFORE, cases.AFTER)[side]
    shallow = cases.padded(b"padding = 0\n", tail, cases.SIZE).decode("utf-8-sig")
    shallow_tree = native(shallow)
    expected_nodes = sum(1 for _node in ast.walk(shallow_tree)) + 3 * (len(tokens) - 1)
    assert sum(1 for _node in ast.walk(tree)) == expected_nodes, first
    assert ast.dump(tree.body[0], include_attributes=True) == ast.dump(shallow_tree.body[0], include_attributes=True)
    assert ast.dump(tree.body[2], include_attributes=True) == ast.dump(shallow_tree.body[2], include_attributes=True)

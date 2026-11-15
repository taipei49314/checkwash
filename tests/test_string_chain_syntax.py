"""Source-only inputs: stdlib AST parity and the owned deep string-chain pair.

The deep pair below is static detector data and is never executed. Sibling
test modules import it from here (`import test_string_chain_syntax as cases`).
"""

import ast
import io
import sys
import tokenize

import pytest

from checkwash.change import EngineError
from checkwash.frontends.python import frontend
from checkwash.frontends.python import standin_installations as subject
from checkwash.frontends.python import syntax

SIZE = 1_000_000
PATH = "tests/test_owned_cost.py"
DEEP = "deep_expression_1mb"
SIBLING = "deep_expression_sibling_128"
PREFIX = b"import app.billing as billing\n"
BEFORE = b"def test_total():\n    observed = billing.total\n    assert billing.total() == 3\n"
AFTER = b"def test_total():\n    billing.total = lambda: 3\n    assert billing.total() == 3\n"
COMMON = {"app/__init__.py": b"", "app/billing.py": b"def total():\n    return 1\n"}


def padded(body, tail, size):
    remaining = size - len(PREFIX) - len(body) - len(tail)
    if remaining < 2:
        raise ValueError("generator has no final line padding space")
    return PREFIX + body + b"#" + b" " * (remaining - 2) + b"\n" + tail


def pair(name):
    """Return the (before, after) bytes of one owned deep string-chain input.

    Both shapes are one left-associated `+` chain of real string literals at
    module scope. DEEP fills one megabyte (9,899 literals); SIBLING has 128.
    The recursion limit is never changed.
    """
    if name not in (DEEP, SIBLING):
        raise ValueError("unknown owned case")
    atom = b"'" + b"0123456789abcdef" * 6 + b"'"
    if name == DEEP:
        available = SIZE - len(PREFIX) - max(len(BEFORE), len(AFTER)) - len(b"padding = \n") - 2
        terms = (available + 3) // (len(atom) + 3)
    else:
        terms = 128
    body = b"padding = " + b" + ".join([atom] * terms) + b"\n"
    if name == DEEP:
        return padded(body, BEFORE, SIZE), padded(body, AFTER, SIZE)
    return PREFIX + body + BEFORE, PREFIX + body + AFTER


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
    # At exactly the limit, the forced fallback's complete tree is read.
    _failure, calls = force_first_recursion(monkeypatch)
    monkeypatch.setattr(subject, "_MAX_SOURCE_NODES", full_count)
    tree = subject._syntax(source, path="owned.py", side="before")
    assert calls[0] == source.decode() and len(calls) > 1
    assert tree is not None
    assert sum(1 for _node in ast.walk(tree)) == full_count


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
    monkeypatch, side,
):
    raw = pair(DEEP)[side]
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
    tree = syntax.parse_module(source)
    assert sys.getrecursionlimit() == limit, first
    assert len(raw) == 1_000_000 and raw.count(b" + ") == 9898, first
    assert first["state"] in ("RETURNED", "RAISED"), first
    if first["state"] == "RAISED":
        assert first["exception_class"] == "RecursionError", first

    tokens = [token._replace(line="") for token in tokenize.generate_tokens(io.StringIO(source).readline)
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
    tail = (BEFORE, AFTER)[side]
    shallow = padded(b"padding = 0\n", tail, SIZE).decode("utf-8-sig")
    shallow_tree = native(shallow)
    expected_nodes = sum(1 for _node in ast.walk(shallow_tree)) + 3 * (len(tokens) - 1)
    assert sum(1 for _node in ast.walk(tree)) == expected_nodes, first
    assert ast.dump(tree.body[0], include_attributes=True) == ast.dump(shallow_tree.body[0], include_attributes=True)
    assert ast.dump(tree.body[2], include_attributes=True) == ast.dump(shallow_tree.body[2], include_attributes=True)


def test_forced_fallback_on_deep_pair_recovers_in_bounded_memory(monkeypatch):
    import time
    import tracemalloc

    source = pair(DEEP)[0].decode("utf-8-sig")
    _failure, calls = force_first_recursion(monkeypatch)
    tracemalloc.start()
    try:
        started = time.perf_counter()
        tree = syntax.parse_module(source)
        elapsed = time.perf_counter() - started
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert calls[0] == source and len(calls) > 1
    assert elapsed < 5.0, f"deep fallback took {elapsed:.2f}s"
    assert peak < 32 * 1024 * 1024, f"deep fallback peak allocation {peak} bytes"
    assignment = tree.body[1]
    assert isinstance(assignment, ast.Assign)
    leaves = [node for node in ast.walk(assignment.value) if isinstance(node, ast.Constant)]
    assert len(leaves) == 9899


@pytest.mark.parametrize("builder", [
    lambda: "x = " + "+".join(["1"] * 100_000) + "\n",
    lambda: "x = " + "+".join(["1"] * 500_000) + "\n",
    lambda: "x = (" + " + ".join(["'ab'"] * 5_000) + ")\n",
    lambda: "y = (\n" + "+".join(["1"] * 100_000) + "\n)\n",
])
def test_long_nonchain_lines_reject_in_bounded_time_and_memory(monkeypatch, builder):
    import time
    import tracemalloc

    source = builder()
    failure, _calls = force_first_recursion(monkeypatch)
    tracemalloc.start()
    try:
        started = time.perf_counter()
        with pytest.raises(RecursionError) as raised:
            syntax.parse_module(source)
        elapsed = time.perf_counter() - started
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert raised.value is failure
    assert elapsed < 2.0, f"long non-chain rejection took {elapsed:.2f}s"
    assert peak < 16 * 1024 * 1024, f"long non-chain peak allocation {peak} bytes"


@pytest.mark.parametrize("template,recovers", [
    ("s = '''\n{chain}\n'''\n", False),
    ("y = (\n{chain}\n)\n", False),
    ("y = 'lead' + \\\n{chain}\n", False),
    ("def f():\n    {chain}\n", False),
    ("{chain} # trailing comment\n", False),
    ("if True:\n    pass\n{chain}\n", True),
    ("K = u'雪' + " + " + ".join(["'ab'"] * 600) + "\r\n", True),
])
def test_long_chain_context_boundaries(monkeypatch, template, recovers):
    long_chain = "x = " + " + ".join(["'abcd'"] * 600)
    source = template.format(chain=long_chain)
    assert max(len(line) for line in source.splitlines(keepends=True)) > 2048
    failure, _calls = force_first_recursion(monkeypatch)
    if not recovers:
        with pytest.raises(RecursionError) as raised:
            syntax.parse_module(source)
        assert raised.value is failure
    else:
        tree = syntax.parse_module(source)
        assigns = [node for node in tree.body if isinstance(node, ast.Assign)]
        assert len(assigns) == 1
        leaves = [node for node in ast.walk(assigns[0].value) if isinstance(node, ast.Constant)]
        assert len(leaves) >= 600


@pytest.mark.parametrize("prefix,field_head,field_tail", [
    ('fr"', "{'''}\"", "'''}\""),
    ("fr'", '{"""}\'', '"""}\''),
    ('FR"', "{'''}\"", "'''}\""),
    ('rf"', "{'''}\"", "'''}\""),
    ('fr"', "{x # \"", "}\""),
], ids=[
    "fr_triple_single",
    "fr_triple_double",
    "FR_triple",
    "rf_triple_single",
    "fr_comment",
])
def test_pep701_prefixed_multiline_fstrings_refuse_condensation_and_preserve_later_chain(
    monkeypatch, prefix, field_head, field_tail,
):
    pad = " + ".join(["a"] * 700)
    deep = "deep = " + " + ".join(["'a'"] * 600)
    first_line = f"y = {prefix}{field_head} + {pad}\n"
    assert len(first_line) > 2048
    assert syntax._condense_complete_nonchain_line(first_line) is None
    assert syntax._condense_quote_free_line(first_line) is None

    source = f"{first_line}{field_tail}\n{deep}\n"
    if sys.version_info < (3, 12):
        with pytest.raises(SyntaxError):
            syntax.parse_module(source)
    else:
        force_first_recursion(monkeypatch)
        tree = syntax.parse_module(source)
        assert [type(node) for node in tree.body] == [ast.Assign, ast.Assign]


def test_invalid_escape_python_source_parses_and_checks_without_warnings(monkeypatch, tmp_path):
    import subprocess
    import warnings

    chain_source = "pattern = '\\d+' + '\\s+'\n"
    with warnings.catch_warnings(record=True) as native_caught:
        warnings.simplefilter("always")
        native_tree = syntax.parse_module(chain_source)
    assert [str(item.message) for item in native_caught] == []

    force_first_recursion(monkeypatch)
    with warnings.catch_warnings(record=True) as fallback_caught:
        warnings.simplefilter("always")
        fallback_tree = syntax.parse_module(chain_source)
    assert [str(item.message) for item in fallback_caught] == []
    assert ast.dump(fallback_tree, include_attributes=True) == ast.dump(
        native_tree, include_attributes=True
    )

    def git(*args):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-b", "main")
    git("config", "user.name", "checkwash")
    git("config", "user.email", "checkwash@example.invalid")
    git("config", "commit.gpgsign", "false")
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_bytes(b"")
    (tmp_path / "app" / "code.py").write_text("def token():\n    return '42'\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    test_file = tmp_path / "tests" / "test_code.py"
    test_file.write_text(
        'import re\nfrom app.code import token\n\ndef test_token():\n    assert re.match("\\d+", token()).group(0) == "42"\n',
        encoding="utf-8",
    )
    git("add", "-A")
    git("commit", "-m", "base")
    test_file.write_text(
        'import re\nfrom app.code import token\n\ndef test_token():\n    assert re.match("\\d+", token()).group(0) != ""\n',
        encoding="utf-8",
    )
    git("commit", "-am", "head")
    run = subprocess.run(
        [sys.executable, "-W", "always", "-m", "checkwash", "check", "HEAD~1..HEAD", "--repo", str(tmp_path), "--format", "json"],
        capture_output=True,
        text=True,
    )
    assert run.returncode == 1, run.stderr
    assert run.stderr == ""
    assert '"ASSERT_WEAKENED"' in run.stdout



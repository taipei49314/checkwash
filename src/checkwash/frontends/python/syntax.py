"""Ordinary stdlib parsing with one lossless, token-proven recursion fallback.

Only a complete physical line at module scope of the form
NAME = STRING (+ STRING)+ is eligible. Other source stays with the stdlib.
Caller byte/node budgets still apply to the original input and rebuilt tree.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
import io
import re
import tokenize
import warnings

_LONG_LINE = 2048
_WS = " \t\f"
_MATCHING_OPEN = {")": "(", "]": "[", "}": "{"}
_STRING_RE = re.compile(
    r"(?:[rRuU])?(?:"
    r"'''(?:\\.|'(?!'')|[^'\\\r\n])*'''|"
    r'"""(?:\\.|"(?!"")|[^"\\\r\n])*"""|'
    r"'(?:\\.|[^'\\\r\n])*'|"
    r'"(?:\\.|[^"\\\r\n])*"'
    r")"
)
_NONCHAIN_ATOM_RE = re.compile(
    r"#[^\r\n]*|"
    r"(?:[rRuUbB]|[rR][bB]|[bB][rR])?(?:"
    r"'''(?:\\.|'(?!'')|[^'\\\r\n])*'''|"
    r'"""(?:\\.|"(?!"")|[^"\\\r\n])*"""|'
    r"'(?:\\.|[^'\\\r\n])*'|"
    r'"(?:\\.|[^"\\\r\n])*"'
    r")|"
    r"[()\[\]{}]|"
    r"[A-Za-z_][A-Za-z0-9_]*+(?![\'\"])|"
    r"[0-9+\-*/%&|^~<>=,.;:@ \t\f]+"
)
_QUOTE_FREE_RUN_RE = re.compile(r"[0-9A-Za-z_+\-*/%&|^~<>=,.;:@ ]+")


@dataclass(frozen=True, slots=True)
class _Literal:
    string: str
    start_col: int
    end_col: int


@dataclass(frozen=True, slots=True)
class _Tok:
    type: int
    string: str
    start_line: int
    start_col: int
    end_line: int
    end_col: int


@dataclass(frozen=True, slots=True)
class _Chain:
    line: int
    literals: tuple[_Literal, ...]


def _split_eol(raw_line: str) -> tuple[str, str]:
    if raw_line.endswith("\r\n"):
        return raw_line[:-2], "\r\n"
    if raw_line.endswith("\n"):
        return raw_line[:-1], "\n"
    return raw_line, ""


def _scan_chain_line(raw_line: str, lineno: int) -> _Chain | None:
    body, _eol = _split_eol(raw_line)
    if "\r" in body or not body or body[0] in _WS:
        return None
    n = len(body)
    pos = 0
    while pos < n and body[pos] not in " \t\f=":
        pos += 1
    name = body[:pos]
    if not name or not name.isidentifier():
        return None
    while pos < n and body[pos] in _WS:
        pos += 1
    if pos >= n or body[pos] != "=":
        return None
    pos += 1
    if pos < n and body[pos] == "=":
        return None
    literals: list[_Literal] = []
    while True:
        while pos < n and body[pos] in _WS:
            pos += 1
        match = _STRING_RE.match(body, pos)
        if match is None:
            return None
        start, end = match.span()
        literals.append(_Literal(body[start:end], start, end))
        pos = end
        while pos < n and body[pos] in _WS:
            pos += 1
        if pos == n:
            break
        if body[pos] != "+":
            return None
        pos += 1
    if len(literals) < 2:
        return None
    return _Chain(lineno, tuple(literals))


def _condense_complete_nonchain_line(raw_line: str) -> str | None:
    body, eol = _split_eol(raw_line)
    if "\r" in body or "\v" in body or "\x00" in body:
        return None
    n = len(body)
    ws_end = 0
    while ws_end < n and body[ws_end] in _WS:
        ws_end += 1
    ws = body[:ws_end]
    pos = ws_end
    stack: list[str] = []
    saw_code = False
    saw_comment = False
    while pos < n:
        match = _NONCHAIN_ATOM_RE.match(body, pos)
        if match is None:
            return None
        tok = match.group(0)
        pos = match.end()
        first = tok[0]
        if (first.isalpha() or first == "_") and pos < n and (
            body[pos] in "'\"" or body[pos].isalnum() or body[pos] == "_"
        ):
            return None
        if first == "#":
            saw_comment = True
            break
        if first in "([{":
            if len(stack) >= 199:
                return None
            stack.append(first)
            saw_code = True
        elif first in ")]}":
            if not stack or stack.pop() != _MATCHING_OPEN[first]:
                return None
            saw_code = True
        elif tok.strip(_WS):
            saw_code = True
    if stack:
        return None
    if not saw_code:
        return ws + ("#" if saw_comment else "") + eol
    return ws + "0" + eol


def _condense_quote_free_line(raw_line: str) -> str | None:
    body, eol = _split_eol(raw_line)
    if "'" in body or '"' in body or "\\" in body or "#" in body or "\r" in body or "\v" in body or "\x00" in body:
        return None
    n = len(body)
    ws_end = 0
    while ws_end < n and body[ws_end] in _WS:
        ws_end += 1
    return body[:ws_end] + _QUOTE_FREE_RUN_RE.sub("0", body[ws_end:]) + eol


def _chain(tokens: list[_Tok]) -> _Chain | None:
    # At least NAME, '=', STRING, '+', STRING. No ignored tokens inside it:
    # comments, adjacent strings, parentheses and continuations cannot qualify.
    if len(tokens) < 5 or len(tokens) % 2 == 0:
        return None
    first = tokens[0]
    if first.type != tokenize.NAME or first.start_col != 0:
        return None
    if tokens[1].type != tokenize.OP or tokens[1].string != "=":
        return None
    if any(token.start_line != first.start_line or token.end_line != first.start_line
           for token in tokens):
        return None
    for index, token in enumerate(tokens[2:], 2):
        if index % 2 == 0:
            if token.type != tokenize.STRING:
                return None
        elif token.type != tokenize.OP or token.string != "+":
            return None
    return _Chain(
        first.start_line,
        tuple(_Literal(tok.string, tok.start_col, tok.end_col) for tok in tokens[2::2]),
    )


def _chains(source: str) -> list[_Chain]:
    # Retaining every token on a long line keeps O(K) _Tok records per statement
    # on all Python versions, and older CPython 3.12 patch releases (such as
    # Ubuntu 24.04's 3.12.3, fixed by 3.12.14) also allocate a fresh full-line
    # str copy on every yielded TokenInfo (`token.line`), turning a physical
    # line of length L with K tokens into O(K * L) time and memory. Short lines
    # go straight through generate_tokens; long lines (> _LONG_LINE) pre-scan or
    # condense to a lexically equivalent stub so generate_tokens governs indent
    # and multiline state in bounded memory.
    result: list[_Chain] = []
    statement: list[_Tok] = []
    precomputed: dict[int, _Chain] = {}
    reader = io.StringIO(source)
    lineno = 0
    last_boundary_line = 0
    last_nl_line = 0
    bare_cr_seen = False
    indent = 0
    top = False

    def readline() -> str:
        nonlocal lineno, bare_cr_seen
        raw_line = reader.readline()
        if not raw_line:
            return ""
        lineno += 1
        body, eol = _split_eol(raw_line)
        if "\r" in body:
            bare_cr_seen = True
        if bare_cr_seen or len(raw_line) <= _LONG_LINE:
            return raw_line
        at_boundary = last_boundary_line == lineno - 1
        if at_boundary:
            scanned = _scan_chain_line(raw_line, lineno)
            if scanned is not None:
                precomputed[lineno] = scanned
                return "x = '0' + '0'" + eol
            stub = _condense_complete_nonchain_line(raw_line)
            if stub is not None:
                return stub
        elif last_nl_line == lineno - 1:
            stub = _condense_complete_nonchain_line(raw_line)
            if stub is not None:
                return stub
        stub = _condense_quote_free_line(raw_line)
        return stub if stub is not None else raw_line

    try:
        for token in tokenize.generate_tokens(readline):
            tok_type = token.type
            if tok_type == tokenize.INDENT:
                indent += 1
            elif tok_type == tokenize.DEDENT:
                indent -= 1
            elif tok_type == tokenize.NEWLINE:
                last_boundary_line = token.end[0]
                if top and statement:
                    line_no = statement[0].start_line
                    candidate = precomputed.get(line_no) if line_no in precomputed else _chain(statement)
                    if candidate is not None:
                        result.append(candidate)
                statement = []
                top = False
            elif tok_type == tokenize.ENDMARKER:
                break
            elif not statement and tok_type in (tokenize.NL, tokenize.COMMENT):
                if tok_type == tokenize.NL:
                    last_boundary_line = token.end[0]
                continue
            else:
                if tok_type == tokenize.NL:
                    last_nl_line = token.end[0]
                if not statement:
                    top = indent == 0
                statement.append(
                    _Tok(
                        tok_type,
                        token.string,
                        token.start[0],
                        token.start[1],
                        token.end[0],
                        token.end[1],
                    )
                )
    except tokenize.TokenError:
        # Keep any already completed chains. The entire remaining text is
        # retained, so parsing the shallow module still diagnoses its syntax.
        pass
    return result


def _parse_exec(source: str) -> ast.Module:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        warnings.simplefilter("ignore", DeprecationWarning)
        return ast.parse(source)


def _parse_eval(source: str) -> ast.Expression:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        warnings.simplefilter("ignore", DeprecationWarning)
        return ast.parse(source, mode="eval")


def _literal_tree(chain: _Chain, line: str, failure: RecursionError) -> ast.expr | None:
    root: ast.expr | None = None
    char_cursor = byte_cursor = 0
    for token in chain.literals:
        start, end = token.start_col, token.end_col
        byte_cursor += len(line[char_cursor:start].encode("utf-8"))
        column = byte_cursor
        byte_cursor += len(line[start:end].encode("utf-8"))
        char_cursor = end
        leaf = _parse_eval(token.string).body
        # Keep an unsupported statement untouched for the surrounding stdlib
        # parse; it must not prevent recovery of a different supported chain.
        if not isinstance(leaf, ast.Constant) or type(leaf.value) is not str:
            return None
        leaf.lineno = leaf.end_lineno = chain.line
        leaf.col_offset, leaf.end_col_offset = column, byte_cursor
        if root is None:
            root = leaf
        else:
            root = ast.BinOp(
                left=root, op=ast.Add(), right=leaf,
                lineno=chain.line, col_offset=root.col_offset,
                end_lineno=chain.line, end_col_offset=byte_cursor,
            )
    if root is None:
        raise failure
    return root


def _recover(source: str, failure: RecursionError) -> ast.Module:
    candidates = _chains(source)
    if not candidates:
        raise failure
    # Split only at Python physical newlines, not Unicode line separators in
    # string literals. Each eligible line is changed once; no subtree copies.
    lines = source.split("\n")
    replacements: dict[int, ast.expr] = {}
    for chain in candidates:
        line = lines[chain.line - 1]
        root = _literal_tree(chain, line, failure)
        if root is None:
            continue
        start, end = chain.literals[0].start_col, chain.literals[-1].end_col
        width = len(line[start:end].encode("utf-8"))
        lines[chain.line - 1] = line[:start] + "0" + " " * (width - 1) + line[end:]
        replacements[chain.line] = root
    if not replacements:
        raise failure
    tree = _parse_exec("\n".join(lines))
    for node in tree.body:
        root = replacements.get(node.lineno)
        if root is None:
            continue
        # The surrounding assignment and its native Name/Store context must
        # come from the shallow module, not from a hand-built substitute.
        if not (
            isinstance(node, ast.Assign) and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.col_offset == 0
            and isinstance(node.value, ast.Constant) and node.value.value == 0
            and node.value.col_offset == root.col_offset
            and node.value.end_col_offset == root.col_offset + 1
        ):
            raise failure
        node.value = root
        node.end_lineno, node.end_col_offset = root.end_lineno, root.end_col_offset
        del replacements[node.lineno]
    if replacements:
        raise failure
    return tree


def parse_module(source: str) -> ast.Module:
    """Return the full module AST; never fold or omit a string-chain node."""
    try:
        return _parse_exec(source)
    except RecursionError as failure:
        return _recover(source, failure)

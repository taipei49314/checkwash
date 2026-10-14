"""Ordinary stdlib parsing with one lossless, token-proven recursion fallback.

Only a complete physical line at module scope of the form
NAME = STRING (+ STRING)+ is eligible. Other source stays with the stdlib.
Caller byte/node budgets still apply to the original input and rebuilt tree.
"""

from __future__ import annotations

import ast
import io
import tokenize
from dataclasses import dataclass


@dataclass(frozen=True)
class _Chain:
    line: int
    literals: tuple[tokenize.TokenInfo, ...]


def _chain(tokens: list[tokenize.TokenInfo]) -> _Chain | None:
    # At least NAME, '=', STRING, '+', STRING. No ignored tokens inside it:
    # comments, adjacent strings, parentheses and continuations cannot qualify.
    if len(tokens) < 5 or len(tokens) % 2 == 0:
        return None
    first = tokens[0]
    if first.type != tokenize.NAME or first.start[1] != 0:
        return None
    if tokens[1].type != tokenize.OP or tokens[1].string != "=":
        return None
    if any(token.start[0] != first.start[0] or token.end[0] != first.start[0]
           for token in tokens):
        return None
    for index, token in enumerate(tokens[2:], 2):
        if index % 2 == 0:
            if token.type != tokenize.STRING:
                return None
        elif token.type != tokenize.OP or token.string != "+":
            return None
    return _Chain(first.start[0], tuple(tokens[2::2]))


def _chains(source: str) -> list[_Chain]:
    result: list[_Chain] = []
    statement: list[tokenize.TokenInfo] = []
    indent = 0
    top = False
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type == tokenize.INDENT:
                indent += 1
            elif token.type == tokenize.DEDENT:
                indent -= 1
            elif token.type == tokenize.NEWLINE:
                candidate = _chain(statement) if top else None
                if candidate is not None:
                    result.append(candidate)
                statement = []
                top = False
            elif token.type == tokenize.ENDMARKER:
                break
            elif not statement and token.type in (tokenize.NL, tokenize.COMMENT):
                continue
            else:
                if not statement:
                    top = indent == 0
                statement.append(token)
    except tokenize.TokenError:
        # Keep any already completed chains. The entire remaining text is
        # retained, so parsing the shallow module still diagnoses its syntax.
        pass
    return result


def _literal_tree(chain: _Chain, line: str, failure: RecursionError) -> ast.expr | None:
    root: ast.expr | None = None
    char_cursor = byte_cursor = 0
    for token in chain.literals:
        start, end = token.start[1], token.end[1]
        byte_cursor += len(line[char_cursor:start].encode("utf-8"))
        column = byte_cursor
        byte_cursor += len(line[start:end].encode("utf-8"))
        char_cursor = end
        leaf = ast.parse(token.string, mode="eval").body
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
        start, end = chain.literals[0].start[1], chain.literals[-1].end[1]
        width = len(line[start:end].encode("utf-8"))
        lines[chain.line - 1] = line[:start] + "0" + " " * (width - 1) + line[end:]
        replacements[chain.line] = root
    if not replacements:
        raise failure
    tree = ast.parse("\n".join(lines))
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
        return ast.parse(source)
    except RecursionError as failure:
        return _recover(source, failure)

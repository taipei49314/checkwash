"""Keep binding-key spelling while iterating an over-deep root BinOp chain.

This is intentionally not a general Python unparser. Ordinary inputs retain
the stdlib result; only a root BinOp that exhausted its recursive traversal
uses the bounded-scope emitter below. Leaves still use public ast.unparse.
"""

from __future__ import annotations

import ast


# Relative precedence between binary operators only. Non-binary operand
# precedence stays with the stdlib through a shallow, public AST context.
_OPERATORS = {
    ast.BitOr: ("|", 1),
    ast.BitXor: ("^", 2),
    ast.BitAnd: ("&", 3),
    ast.LShift: ("<<", 4),
    ast.RShift: (">>", 4),
    ast.Add: ("+", 5),
    ast.Sub: ("-", 5),
    ast.Mult: ("*", 6),
    ast.MatMult: ("@", 6),
    ast.Div: ("/", 6),
    ast.FloorDiv: ("//", 6),
    ast.Mod: ("%", 6),
    ast.Pow: ("**", 7),
}
_CONTEXT_NAME = "_checkwash_binding_context"


def _operand_text(node: ast.AST, operator: ast.operator, right: bool) -> str:
    """Let public ast.unparse retain the exact leaf's operand parentheses.

    Strip one checked endpoint only. The same sentinel text inside a Name,
    string, f-string, attribute or other operand is never searched/replaced.
    No locations are changed and the operand AST is not copied or mutated.
    """
    sentinel = ast.Name(id=_CONTEXT_NAME, ctx=ast.Load())
    symbol = _OPERATORS[type(operator)][0]
    if right:
        context = ast.BinOp(left=sentinel, op=operator, right=node)
        prefix = f"{_CONTEXT_NAME} {symbol} "
        text = ast.unparse(context)
        if not text.startswith(prefix) or len(text) <= len(prefix):
            raise RuntimeError("stdlib changed binding operand prefix")
        return text[len(prefix):]
    context = ast.BinOp(left=node, op=operator, right=sentinel)
    suffix = f" {symbol} {_CONTEXT_NAME}"
    text = ast.unparse(context)
    if not text.endswith(suffix) or len(text) <= len(suffix):
        raise RuntimeError("stdlib changed binding operand suffix")
    return text[:-len(suffix)]


def _iterative_binop(root: ast.BinOp) -> str:
    """Emit a connected BinOp tree once, preserving stdlib grouping.

    Each pending tuple is (operand, parent operator, is right operand).
    Lower-precedence children need parentheses; equal precedence follows
    the stdlib's left association except for right-associated power.
    The worklist emits tokens and joins once, without subtree strings/walks.
    """
    pending: list[str | tuple[ast.AST, ast.operator | None, bool]] = [(root, None, False)]
    tokens: list[str] = []
    while pending:
        item = pending.pop()
        if isinstance(item, str):
            tokens.append(item)
            continue
        node, parent, right = item
        if not isinstance(node, ast.BinOp):
            if parent is None:
                raise TypeError("iterative binding emitter requires a BinOp root")
            tokens.append(_operand_text(node, parent, right))
            continue
        symbol, precedence = _OPERATORS[type(node.op)]
        parentheses = False
        if parent is not None:
            parent_precedence = _OPERATORS[type(parent)][1]
            # All binary operations associate left except power. Keep the
            # other direction's parentheses even for associative arithmetic.
            stricter = not right if isinstance(parent, ast.Pow) else right
            parentheses = precedence < parent_precedence + int(stricter)
        if parentheses:
            tokens.append("(")
            pending.append(")")
        pending.append((node.right, node.op, True))
        pending.append(f" {symbol} ")
        pending.append((node.left, node.op, False))
    return "".join(tokens)


def binding_key(node: ast.AST) -> str:
    """Preserve every successful old key, retry only the measured shape.

    An unsupported recursive leaf still raises. Never turn an exception into
    an empty key, raw-source signature, altered node budget or semantic credit.
    """
    try:
        return ast.unparse(node)
    except RecursionError:
        if not isinstance(node, ast.BinOp):
            raise
        return _iterative_binop(node)

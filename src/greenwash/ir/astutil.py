"""Expression comparisons shared by the detectors that need them.

`_wraps` lived twice, byte-identical apart from a docstring, in
`assert_substituted.py` and `subject_normalized.py`. Two copies of a
containment rule means the next person to widen the boundary widens it in one
of them, and the two rules disagree about what "the same subject" means without
anything failing (static review 2026-08-11, Issue 7).

Everything here is structural. Source text is the wrong unit for this: it makes
reformatting a change and it makes `f( x )` a different subject from `f(x)`.
"""

from __future__ import annotations

import ast

from greenwash.ir.markers import parse_expr
from greenwash.ir.model import normalize_text


def same_expr(before: str | None, after: str | None) -> bool:
    """Are these the same expression, ignoring spelling and spacing?"""
    if before is None or after is None:
        return before == after
    if normalize_text(before) == normalize_text(after):
        return True
    b, a = parse_expr(before), parse_expr(after)
    if b is None or a is None:
        return False
    return ast.dump(b) == ast.dump(a)


def expr_wraps(before: str | None, after: str | None) -> bool:
    """Does the after-expression contain the before-expression inside it?

    `f(x)` inside `f(x).replace(...)` or `sorted(f(x))` is the same node
    however either side is spelled. A subject replaced outright is a different
    test, not a laundered one, and earns nothing here.
    """
    if not before or not after or before == after:
        return False
    b, a = parse_expr(before), parse_expr(after)
    if b is None or a is None:
        return False
    target = ast.dump(b)
    return any(ast.dump(node) == target for node in ast.walk(a) if node is not a)


def argument_wraps(before: str | None, after: str | None) -> bool:
    """Same call, same arity, and at least one argument wrapped in place.

    `encode_path(s)` becoming `encode_path(normalise(s))` laundered the subject
    without touching it: whole-expression containment sees no overlap, because
    the old call is not a sub-expression of the new one — the *arguments* are
    (redteam-weaknesses.md §4B).

    Every argument must either be unchanged or contain its counterpart, and at
    least one must actually be wrapped. A call whose argument was simply
    replaced by a different one is a different test and is refused here, the
    same line `expr_wraps` draws for the subject.
    """
    if not before or not after or before == after:
        return False
    b, a = parse_expr(before), parse_expr(after)
    if not isinstance(b, ast.Call) or not isinstance(a, ast.Call):
        return False
    if ast.dump(b.func) != ast.dump(a.func):
        return False
    if len(b.args) != len(a.args) or len(b.keywords) != len(a.keywords):
        return False

    wrapped = False
    for old, new in zip(b.args, a.args):
        old_d, new_d = ast.dump(old), ast.dump(new)
        if old_d == new_d:
            continue
        if any(ast.dump(n) == old_d for n in ast.walk(new) if n is not new):
            wrapped = True
            continue
        return False

    for old_kw, new_kw in zip(b.keywords, a.keywords):
        if old_kw.arg != new_kw.arg:
            return False
        old_d, new_d = ast.dump(old_kw.value), ast.dump(new_kw.value)
        if old_d == new_d:
            continue
        if any(ast.dump(n) == old_d for n in ast.walk(new_kw.value) if n is not new_kw.value):
            wrapped = True
            continue
        return False

    return wrapped


def resolve_through(expr: str | None, bindings: dict[str, str]) -> str | None:
    """A bare local name replaced by what it was assigned, once.

    `got = encode_path(s).replace(...)` then `assert got == "..."` moves the
    wrapper one statement up, and the subject the assertion carries is just
    `got` — so containment had nothing to compare (redteam-weaknesses.md §4A).

    Exactly one substitution, and only for a subject that is a bare name. Two
    hops are a residual and are recorded as one rather than chased: the k+1
    hop always exists, and the honest answer is a stated bound.
    """
    if not expr:
        return expr
    node = parse_expr(expr)
    if not isinstance(node, ast.Name):
        return expr
    definition = bindings.get(node.id)
    # A name assigned more than once carries every right-hand side, joined.
    # Substituting that is substituting something that is not an expression at
    # all — and it invented a false positive on flask `daf1510a4b`, where a
    # test appends new assertions and rebinds `rv` a second time: the joined
    # value happened to contain the old one, containment matched, and the
    # finding read "the asserted subject was wrapped (rv -> rv)".
    #
    # If greenwash cannot say which binding reaches the assertion, it does not
    # get to guess.
    if definition is None or "" in definition:
        return expr
    return definition

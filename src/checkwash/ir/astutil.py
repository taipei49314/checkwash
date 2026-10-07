"""Expression comparisons shared by the detectors that need them.

`_wraps` lived twice, byte-identical apart from a docstring, in
`assert_substituted.py` and `subject_normalized.py`. Two copies of a
containment rule means the next person to widen the boundary widens it in one
of them, and the two rules disagree about what "the same subject" means without
anything failing (static review 2026-08-11, Issue 7).

`dotted_name` lived twice more, also byte-identical: `frontend._dotted` and
`gating._dotted_name` (E1 / the same review's DRY table).

Everything here is structural. Source text is the wrong unit for this: it makes
reformatting a change and it makes `f( x )` a different subject from `f(x)`.
"""

from __future__ import annotations

import ast
import sys
import warnings

from checkwash.ir.markers import parse_expr
from checkwash.ir.model import normalize_text


def stable_dump(node: ast.AST) -> str:
    """`ast.dump` text that is byte-identical on every supported Python.

    Python 3.13 changed `ast.dump` to omit empty lists and None fields by
    default (`show_empty=False`). Anything that *digests* the dump text —
    the synthesized `test_concrete_<digest>` names of projected table rows,
    symbol fingerprints — then differs between interpreters, and the
    cross-OS/Python byte-compare gate (SPEC §8) fails: v0.3.0 candidate
    run 34109601179 emitted one corpus digest on 3.11/3.12 and another on
    3.13. `show_empty=True` reproduces the pre-3.13 text exactly, so keys
    computed on 3.11/3.12 do not change. Comparisons of two dumps made by
    the same interpreter are unaffected either way and keep calling
    `ast.dump` directly.
    """
    if sys.version_info >= (3, 13):
        return ast.dump(node, include_attributes=False, show_empty=True)
    return ast.dump(node, include_attributes=False)


def dotted_name(node: ast.AST) -> str | None:
    """`a.b.c` for Name/Attribute chains, else None."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


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


def asserted_subject(statement: str) -> str | None:
    """What a Python `assert` statement checks, its `not`s peeled (#331).

    The tested expression itself, or, for a comparison with an `approx(...)`
    call (`total() == pytest.approx(78.75)`), its other side. The Python
    frontend records no subject for a bare truthy or `isinstance` assert, nor
    for an approx comparison, so this is the subject such a pair can be
    compared by. None when the text is not one `assert` statement.
    """
    # The file warned once when it was read (an invalid escape, `'\d'`, is a
    # SyntaxWarning, or a DeprecationWarning before Python 3.12); reading one
    # of its statements again adds nothing to say (#319).
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            body = ast.parse(statement.strip()).body
        except (SyntaxError, RecursionError, ValueError, MemoryError):
            return None
    if len(body) != 1 or not isinstance(body[0], ast.Assert):
        return None
    test = body[0].test
    while isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        test = test.operand
    if isinstance(test, ast.Compare) and len(test.ops) == 1:
        sides = [test.left, test.comparators[0]]
        approx = [side for side in sides if isinstance(side, ast.Call)
                  and (dotted_name(side.func) or "").rpartition(".")[2] == "approx"]
        if len(approx) == 1:
            test = sides[1] if approx[0] is sides[0] else sides[0]
    try:
        return ast.unparse(test)
    except (RecursionError, ValueError):
        return None


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
    # If checkwash cannot say which binding reaches the assertion, it does not
    # get to guess.
    if definition is None or "" in definition:
        return expr
    return definition

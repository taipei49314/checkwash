"""What an assertion checks, for pairing assertions by subject (#434).

The order fallback used to give an old assertion the first leftover of known
strength in span order. A precondition written above a rewritten oracle then
took the oracle's place: `assert area(4, 5) == 20.0` rewritten as
`result = area(4, 5)`, `assert isinstance(result, float)`, `assert result ==
20.0` paired the old `==` with the `isinstance` and blocked as a weakening,
while the same two lines in the other order passed (#434 A1, #457). The
ruling (2026-10-16, A.4) has an old assertion first take a leftover that
checks the same subject.

The same subject means the same expression read in the same context:

- the subject written out (`left`), with the reaching keys of the names it
  reads at the assertion (`Assertion.reaching`); or
- for a bare local name, the expression the one plain `name = <expr>`
  assignment that reaches the assertion bound it to, with the reaching keys
  of the names that expression reads where it runs. The Python frontend
  records this as `Assertion.resolved_subject`, and only where that binding
  is the name's value whenever the assertion runs.

One helper, so #460 (a chained range split into its links) can ask the same
question without a second definition of "the same subject".
"""

from __future__ import annotations

import ast
from collections.abc import Iterable, Mapping

from checkwash.ir.markers import parse_expr
from checkwash.ir.model import Assertion, normalize_text


def reaching_signature(reaching: Mapping[str, str], names: Iterable[str]) -> str:
    """The reaching keys of `names`, serialized stably.

    Only names the unit binds have a key (`_reaching_keys` in the Python
    frontend); a module name, a builtin or a parameter the unit never
    rebinds has none, on either side.
    """
    return "\x1e".join(f"{name}\x1d{reaching[name]}" for name in sorted(set(names)) if name in reaching)


def subject_of(assertion: Assertion) -> tuple[str, str] | None:
    """(expression, reading context) of what an own assertion checks, or None.

    None for an assertion with no subject (a bare truthy, `isinstance` or
    approx assert, `pytest.raises`), and for one the unit does not hold in
    its own body: a copy inherited from a helper or reached through a
    helper method (`via`).
    """
    if assertion.left is None or assertion.inherited or assertion.via is not None:
        return None
    resolved = assertion.resolved_subject
    if resolved is not None:
        # A JSON round trip turns the tuple into a list.
        expression, context = resolved
        return str(expression), str(context)
    return assertion.left, reaching_signature(assertion.reaching or {}, assertion.left_names)


def subject_key(assertion: Assertion) -> tuple[str, str] | None:
    """A key for `same_subject`: equal keys are the same subject, read in the same context.

    (reading context, the expression as parsed), so spelling and spacing do
    not matter, as for `astutil.same_expr`. An expression that does not
    parse is kept as its normalized text, which equals no parsed one. None
    for an assertion with no subject (`subject_of`), and for a subject too
    deep to compare, which is not known to be the same as any other. The
    order fallback computes each leftover's key once.
    """
    subject = subject_of(assertion)
    if subject is None:
        return None
    expression, context = subject
    node = parse_expr(expression)
    if node is None:
        return context, "\x00" + normalize_text(expression)
    try:
        return context, ast.dump(node)
    except (RecursionError, ValueError):
        return None


def same_subject(before: Assertion, after: Assertion) -> bool:
    """Do these two assertions check the same subject, read in the same context?"""
    old = subject_key(before)
    return old is not None and old == subject_key(after)

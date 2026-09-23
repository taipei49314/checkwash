"""Bounded expectation equivalence for consumers of JS scalar evidence."""

from __future__ import annotations

from checkwash.ir.model import Assertion


_JS_SUFFIXES = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts")


def same_known_js_scalar(path: str, before: Assertion, after: Assertion) -> bool:
    """Compare frontend-proved JS scalar values without their source spelling.

    The JS frontend supplies canonical Number/string/Boolean/null evidence.
    Equivalent quotes, escapes, radix or exponent spellings do not rewrite
    that expectation. Missing values or changed dependencies prove nothing;
    callers retain their existing Python and unknown-operand behavior.
    The string ``"None"`` represents a known JS null; actual None is unknown.
    """
    return (
        path.lower().endswith(_JS_SUFFIXES)
        and before.right_literal is not None and after.right_literal is not None
        and before.right_value is not None
        and before.right_value == after.right_value
        and before.right_depends_on == after.right_depends_on
    )

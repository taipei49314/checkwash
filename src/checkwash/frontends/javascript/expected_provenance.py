"""Expected-value provenance for JS/TS tests: what an expected name or call reads (#226).

The JavaScript port of Python's provenance channel (docs/expected-provenance.md),
for an equality's expected value. A name the expected value reads is
substituted, never executed: an import becomes its module and export
(`./total.OTHER`), a `const`/`let`/`var` it reads becomes its initializer,
itself resolved the same way, and a function or class the file declares
stays as written. When a pair on one subject resolves to different values
and either side read such a name, the pair is recorded as Python records
its own, and EXPECTATION_DEFINITION_CHANGED reports it (226.Q1, Q3).

Bounded like the rest of the JS frontend: no scope analysis beyond
`Bindings`, eight levels of initializers, operands of at most 4096
characters. A template literal holding a substitution, or anything the
operand reader cannot read, resolves to nothing, and the pair keeps the
native rules' reading.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from checkwash.frontends.javascript.bindings import Bindings
from checkwash.frontends.javascript.frontend import file_bindings
from checkwash.frontends.javascript.literals import operand_text, populate_expectation
from checkwash.ir.model import IR, Assertion, judged_as_test

_JS_SUFFIXES = (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts")
MAX_DEPTH = 8
MAX_EVENTS = 128
_NAME = re.compile(r"[A-Za-z_$][\w$]*")
_QUOTES = "\"'`"
# Words an operand spells that are not names it reads.
_WORDS = frozenset({
    "true", "false", "null", "undefined", "NaN", "Infinity", "this", "super", "new",
    "typeof", "void", "delete", "in", "instanceof", "of", "await", "yield", "async",
    "function", "class", "return", "as", "satisfies", "keyof", "readonly", "unique",
})
# A character outside brackets and strings that makes an expression more
# than one operand: it is parenthesized where it replaces a name.
_OPERATORS = set(" +-*/%<>=!&|^?:,~")


@dataclass(frozen=True)
class _Resolved:
    text: str
    # The same operand with each import a plain name: a specifier's `./` and
    # `@scope/` are no operators when the shape of the operand is asked.
    shape: str
    indirect: bool


def _code(source: str):
    """(index, depth) for each character outside strings; None when a template interpolates."""
    positions = []
    depth = 0
    i = 0
    while i < len(source):
        char = source[i]
        if char in _QUOTES:
            close = i + 1
            while close < len(source) and source[close] != char:
                if char == "`" and source.startswith("${", close):
                    return None
                close += 2 if source[close] == "\\" else 1
            i = close + 1
            continue
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        positions.append((i, depth))
        i += 1
    return positions


def _reads(source: str, positions) -> list[tuple[int, int, str]]:
    """The names an operand reads: not a property, an object key or a keyword."""
    code = {index for index, _ in positions}
    reads = []
    for match in _NAME.finditer(source):
        start, end = match.span()
        if start not in code or (start > 0 and (source[start - 1].isalnum() or source[start - 1] in "_$")):
            continue
        before = source[:start].rstrip()
        after = source[end:].lstrip()
        if before.endswith(".") and not before.endswith(".."):
            continue
        if after.startswith(":") and not after.startswith("::") and before.endswith(("{", ",")):
            continue
        if match.group() not in _WORDS:
            reads.append((start, end, match.group()))
    return reads


def _atomic(source: str) -> bool:
    positions = _code(source)
    return positions is not None and not any(
        depth == 0 and source[index] in _OPERATORS for index, depth in positions)


def _canonical(source: str, bindings: Bindings, position: int) -> str:
    """A literal's canonical value, as `right_value` records one; any other operand as written."""
    probe = Assertion(id="", form="compare_eq", strength=None, text="", span=(0, 0))
    populate_expectation(probe, source, lambda: bindings.is_global(("Number",), position))
    return probe.right_value if probe.right_value is not None else source


def resolve(source: str | None, bindings: Bindings, position: int, depth: int = 0) -> _Resolved | None:
    """What an operand reads, substituted; None when it cannot be read."""
    operand = operand_text(source) if source is not None else None
    if operand is None or depth > MAX_DEPTH:
        return None
    positions = _code(operand)
    if positions is None:
        return None
    parts: list[str] = []
    shapes: list[str] = []
    last = 0
    indirect = False
    for start, end, name in _reads(operand, positions):
        replacement = shape = None
        imported = bindings.imported(name, position)
        if imported is not None:
            specifier, export = imported
            replacement = specifier if export == "*" else f"{specifier}.{export}"
            shape = name
        else:
            initializer = bindings.initializer(name, position)
            if initializer is not None:
                inner = resolve(initializer, bindings, position, depth + 1)
                if inner is None:
                    return None
                wrap = not _atomic(inner.shape)
                replacement = f"({inner.text})" if wrap else inner.text
                shape = f"({inner.shape})" if wrap else inner.shape
            elif bindings.declared_function(name, position):
                indirect = True
        if replacement is not None:
            indirect = True
            parts += [operand[last:start], replacement]
            shapes += [operand[last:start], shape]
            last = end
    parts.append(operand[last:])
    shapes.append(operand[last:])
    text, shape = operand_text("".join(parts)), operand_text("".join(shapes))
    if text is None or shape is None:
        return None
    return _Resolved(_canonical(text, bindings, position), shape, indirect)


def _is_call(source: str) -> bool:
    """Is the subject one call, `callee(...)` with nothing around it, as Python's channel requires?"""
    positions = _code(source)
    if positions is None or not source.endswith(")") or not _atomic(source):
        return False
    openings = [index for index, depth in positions if depth == 1 and source[index] == "("]
    closings = [index for index, depth in positions if depth == 0 and source[index] == ")"]
    if not openings or not closings or closings[-1] != len(source) - 1:
        return False
    opening = max(index for index in openings if index < closings[-1])
    return opening > 0 and (source[opening - 1].isalnum() or source[opening - 1] in "_$)]")


def mark_js_expected_provenance(ir: IR, raw: dict[str, tuple[bytes | None, bytes | None]]) -> None:
    """Record JS/TS expected-value provenance events beside Python's (#226)."""
    for file in ir.files:
        sides = raw.get(file.path)
        if (not file.path.lower().endswith(_JS_SUFFIXES) or not judged_as_test(file) or not file.parse_ok
                or sides is None or sides[0] is None or sides[1] is None):
            continue
        pairs = []
        for unit in file.units:
            if unit.delta is None or unit.before is None or unit.after is None:
                continue
            before = {a.id: a for a in unit.before.assertions}
            after = {a.id: a for a in unit.after.assertions}
            for pair in unit.delta.assertion_pairs:
                b, a = before.get(pair.before_id), after.get(pair.after_id)
                if (b is None or a is None or pair.strength_change is None or pair.strength_change < 0
                        or b.form != "compare_eq" or a.form != "compare_eq" or not (b.positive and a.positive)
                        or b.operand_source is None or a.operand_source is None
                        or b.operand_source == a.operand_source or b.inherited or a.inherited):
                    continue
                pairs.append((unit.qualname, b, a))
        if not pairs:
            continue
        old_bindings, new_bindings = file_bindings(sides[0]), file_bindings(sides[1])
        records = list(file.expected_provenance_events)
        for name, b, a in pairs:
            old = resolve(b.operand_source, old_bindings, b.span[0])
            new = resolve(a.operand_source, new_bindings, a.span[0])
            old_subject = resolve(b.left, old_bindings, b.span[0])
            new_subject = resolve(a.left, new_bindings, a.span[0])
            if (old is None or new is None or old_subject is None or new_subject is None
                    or old_subject.text != new_subject.text or not _is_call(new_subject.shape)
                    or not (old.indirect or new.indirect) or old.text == new.text):
                continue
            records.append((name, b.text, tuple(b.span), a.text, tuple(a.span),
                            new_subject.text, "Eq", old.text, new.text))
            if len(records) >= MAX_EVENTS:
                break
        file.expected_provenance_events = tuple(records)

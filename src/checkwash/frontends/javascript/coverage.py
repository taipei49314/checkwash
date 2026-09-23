"""Bounded assertion candidates that the JS frontend did not represent.

This is reporting evidence, not a tampering detector or proof of complete
JavaScript coverage. Candidate names are deliberately independent of the
frontend's supported-method tables, so an omitted API can remain visible.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from checkwash.frontends.javascript.frontend import (
    _call_arguments,
    _code_positions,
    _conditional_arm,
)
from checkwash.frontends.python.frontend import ParsedFile, normalize_source

_NAME = r"[A-Za-z_$][\w$]*"
_MODULE = r"(?P<quote>['\"])(?:node:)?assert(?:/strict)?(?P=quote)"
_IMPORT = re.compile(r"\bimport\s+(?P<bindings>[^;]{1,500}?)\s+from\s*" + _MODULE)
_REQUIRE = re.compile(
    r"\b(?:const|let|var)\s+(?P<bindings>" + _NAME + r"|\{[^}]{1,500}\})"
    r"\s*=\s*require\s*\(\s*" + _MODULE + r"\s*\)"
)


@dataclass(frozen=True)
class CoverageGap:
    path: str
    side: str
    line: int
    column: int
    callee: str
    reason: str

    def message(self) -> str:
        return (
            f"analysis incomplete: {self.side} {self.path}:{self.line}:{self.column}: "
            f"{self.callee}: {self.reason}"
        )


def _roots(text: str, code: bytearray) -> set[str]:
    roots = {"assert", "t.assert"}
    import_code = _code_positions(text, keep_strings=True)
    imports = "".join(char if import_code[i] else " " for i, char in enumerate(text))
    for pattern, separator in ((_IMPORT, "as"), (_REQUIRE, ":")):
        for match in pattern.finditer(imports):
            if not code[match.start()]:
                continue
            bindings = match.group("bindings").strip()
            default = re.match(_NAME, bindings)
            if default:
                roots.add(default.group())
            namespace = re.search(r"\*\s+as\s+(" + _NAME + r")", bindings)
            if namespace:
                roots.add(namespace.group(1))
            named = re.search(r"\{([^}]+)\}", bindings)
            if named:
                for binding in named.group(1).split(","):
                    name = re.fullmatch(
                        r"\s*(" + _NAME + r")(?:\s*" + separator
                        + r"\s*(" + _NAME + r"))?\s*", binding,
                    )
                    if name:
                        roots.add(name.group(2) or name.group(1))
    return roots


def _previous(masked: str, start: int) -> int:
    position = start - 1
    while position >= 0 and masked[position].isspace():
        position -= 1
    return position


def _declaration(text: str, masked: str, code: bytearray, start: int, opening: int) -> bool:
    previous = _previous(masked, start)
    if previous >= 0 and masked[previous] == "*":
        previous = _previous(masked, previous)
    if re.search(r"\bfunction$", masked[:previous + 1]):
        return True
    call = _call_arguments(text, code, opening, len(text))
    if call is None:
        return False
    following = call[1]
    while following < len(text) and masked[following].isspace():
        following += 1
    if following >= len(text):
        return False
    if masked[following] == ":" and not _conditional_arm(text, code, start):
        return True
    return masked[following] == "{" and "\n" not in text[call[1]:following]


def javascript_coverage_gaps(
    data: bytes, parsed: ParsedFile, path: str, side: str,
) -> list[CoverageGap]:
    text = normalize_source(data)
    code = _code_positions(text)
    masked = "".join(char if code[i] else " " for i, char in enumerate(text))
    represented = {a.span[0] for unit in parsed.units for a in unit.side.assertions}
    candidates: dict[int, tuple[str, str]] = {}

    roots = "|".join(
        r"\s*\.\s*".join(re.escape(part) for part in root.split("."))
        for root in sorted(_roots(text, code), key=lambda item: (-len(item), item))
    )
    calls = re.compile(
        r"(?<![\w$.#])(?:" + roots + r")"
        r"(?:\s*(?:\?\.|\.)\s*" + _NAME + r"|\s*\[[^]\n]*\])*"
        r"\s*(?:\?\.)?\s*\("
    )
    for match in calls.finditer(masked):
        start = match.start()
        previous = _previous(masked, start)
        if previous >= 0 and masked[previous] in ".#":
            continue
        if re.search(r"\bnew$", masked[:previous + 1]):
            continue
        callee = text[start:match.end() - 1].strip()
        if "." not in callee and "[" not in callee:
            if _declaration(text, masked, code, start, match.end() - 1):
                continue
        candidates[start] = (callee, "Node assertion candidate is not represented in the assertion scan")

    # Every expect(...) candidate is checked, including unknown matchers and
    # chains such as resolves/rejects that the supported matcher regex omits.
    for match in re.finditer(r"(?<![\w$.#])expect\s*\(", masked):
        start = match.start()
        previous = _previous(masked, start)
        if previous >= 0 and masked[previous] in ".#":
            continue
        if _declaration(text, masked, code, start, match.end() - 1):
            continue
        callee = "expect(...)"
        call = _call_arguments(text, code, match.end() - 1, len(text))
        if call is not None:
            chain = re.match(r"(?:\s*\.\s*" + _NAME + r")+", masked[call[1]:])
            if chain:
                callee += re.sub(r"\s+", "", chain.group())
        candidates[start] = (callee, "expect candidate is not represented in the assertion scan")

    return [
        CoverageGap(
            path=path,
            side=side,
            line=text.count("\n", 0, start) + 1,
            column=start - text.rfind("\n", 0, start),
            callee=re.sub(r"\s+", " ", callee)[:160],
            reason=reason,
        )
        for start, (callee, reason) in sorted(candidates.items())
        if start not in represented
    ]

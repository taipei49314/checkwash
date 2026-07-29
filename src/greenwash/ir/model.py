"""IR data model (SPEC: greenwash_ir_version 1).

Detectors consume this and nothing else. All ordering inside the IR is
explicit and deterministic; no dict/set iteration order leaks into output.
Spans are character offsets into CRLF→LF-normalized source (SPEC §8).
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any

from greenwash import IR_VERSION


@dataclass
class Assertion:
    id: str
    form: str  # compare_eq | compare_ord | membership | non_null | approx | type_shape | pattern | truthy | tautology | raises | unknown
    strength: int | None
    text: str
    span: tuple[int, int]
    left: str | None = None
    right_literal: str | None = None
    epsilon: str | None = None  # literal source text of the tolerance, never a float


@dataclass
class Marker:
    name: str  # e.g. "pytest.mark.skip"
    text: str
    span: tuple[int, int]


@dataclass
class Handler:
    caught: tuple[str, ...]  # empty = bare except
    is_broad: bool
    text: str
    span: tuple[int, int]


@dataclass
class UnitSide:
    span: tuple[int, int]
    assertions: list[Assertion] = field(default_factory=list)
    calls: tuple[str, ...] = ()  # sorted, unique
    markers: list[Marker] = field(default_factory=list)
    handlers: list[Handler] = field(default_factory=list)


@dataclass
class AssertionPair:
    before_id: str
    after_id: str
    strength_change: int | None  # None when either side is unclassifiable


@dataclass
class UnitDelta:
    assertion_pairs: list[AssertionPair] = field(default_factory=list)
    assertions_removed: list[str] = field(default_factory=list)  # before-side assertion ids
    assertions_added: list[str] = field(default_factory=list)  # after-side assertion ids
    markers_added: list[str] = field(default_factory=list)
    handlers_widened: list[str] = field(default_factory=list)
    tolerance_changes: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class Unit:
    kind: str  # "test_function"
    qualname: str
    match: str | None  # by_name | by_fingerprint | None (one-sided)
    before: UnitSide | None
    after: UnitSide | None
    delta: UnitDelta | None


@dataclass
class FileIR:
    path: str
    language: str  # "python" | "unknown"
    role: str
    status: str  # added | modified | deleted
    units: list[Unit] = field(default_factory=list)
    alignment: str = "full"  # "full" | "degraded"
    parse_ok: bool = True


@dataclass
class DiffGlobals:
    prod_files_changed: list[str] = field(default_factory=list)
    prod_symbols_changed: list[str] = field(default_factory=list)  # non-trivial only
    prod_nontrivial_change: bool = False
    new_literals_in_prod: list[str] = field(default_factory=list)
    guardrail_files_changed: list[str] = field(default_factory=list)
    ci_files_changed: list[str] = field(default_factory=list)
    snapshot_files_changed: list[str] = field(default_factory=list)
    imports_added: list[str] = field(default_factory=list)
    suppressions_added: list[str] = field(default_factory=list)
    moved_assertion_texts: list[str] = field(default_factory=list)  # normalized, sorted


@dataclass
class IR:
    base: str
    head: str
    files: list[FileIR] = field(default_factory=list)
    globals: DiffGlobals = field(default_factory=DiffGlobals)
    skipped_files: list[str] = field(default_factory=list)
    version: int = IR_VERSION


def to_jsonable(obj: Any) -> Any:
    """Dataclass tree → plain JSON-serializable structure (tuples become lists)."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_jsonable(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(x) for x in obj]
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    return obj


def normalize_text(text: str) -> str:
    """Normal form for pairing, moves and fingerprints.

    Strips whitespace *outside* string literals only: whitespace inside a
    quoted string is semantics, and erasing it would let a relocated
    assertion with a silently edited expected value count as "moved
    verbatim" (SPEC §5 D2 — confirmed red-team finding).
    """
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch in "\"'":
            quote = ch * 3 if text[i : i + 3] == ch * 3 else ch
            out.append(quote)
            i += len(quote)
            while i < n:
                if text[i] == "\\" and len(quote) == 1 and i + 1 < n:
                    out.append(text[i : i + 2])
                    i += 2
                    continue
                if text.startswith(quote, i):
                    out.append(quote)
                    i += len(quote)
                    break
                out.append(text[i])
                i += 1
        elif ch.isspace():
            i += 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)

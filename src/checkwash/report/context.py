"""Optional source provenance for reports; never part of serialized IR.

Only the bytes actually parsed by the engine may supply a line number.
Inherited assertions retain their source file, including when their text was
specialized at a call site. Ambiguous origins deliberately stay file-level.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from checkwash.findings import Evidence
from checkwash.frontends.python.frontend import normalize_source


@dataclass
class ReportContext:
    _sources: dict[tuple[str, int], str] = field(default_factory=dict)
    _origins: dict[tuple[str, int, tuple[int, int], str], set[str]] = field(
        default_factory=dict
    )

    def snapshot(self, path: str, side: int, data: bytes | None) -> None:
        if data is not None:
            self._sources[(path, side)] = normalize_source(data)

    def bind(self, path: str, side: int, item, source_path: str) -> None:
        key = (path, side, item.span, item.text)
        self._origins.setdefault(key, set()).add(source_path)

    def parsed(self, path: str, side: int, parsed) -> None:
        if parsed is None:
            return
        for unit in parsed.units:
            for item in (*unit.side.assertions, *unit.side.markers, *unit.side.handlers):
                self.bind(path, side, item, path)

    def location(self, path: str, evidence: Evidence) -> tuple[str, int] | None:
        # Primary locations point to head. Base-only evidence is not a span
        # in that file and must not be projected onto the new contents.
        origins = self._origins.get((path, 1, evidence.span, evidence.text), set())
        if len(origins) != 1:
            return None
        origin = next(iter(origins))
        source = self._sources.get((origin, 1))
        start, end = evidence.span
        if source is None or not 0 <= start < end <= len(source):
            return None
        return origin, source.count("\n", 0, start) + 1

"""Finding model and fingerprints (SPEC: greenwash_findings_version 1)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from greenwash.ir.model import normalize_text


@dataclass
class Evidence:
    text: str
    span: tuple[int, int]


@dataclass
class Finding:
    rule: str
    severity: str  # info | warn | high | critical
    message: str
    path: str
    unit: str | None
    before: Evidence | None = None
    after: Evidence | None = None
    escalators: list[str] = field(default_factory=list)
    deescalators: list[str] = field(default_factory=list)
    fingerprint: str = ""
    allowlisted: bool = False
    # ASSERT_WEAKENED only: how far the strength fell and where it landed,
    # so gating can distinguish material weakening from style drift.
    strength_drop: int | None = None
    strength_after: int | None = None

    def sort_key(self) -> tuple:
        from greenwash.gating import RULE_ORDER

        try:
            rank = RULE_ORDER.index(self.rule)
        except ValueError:
            rank = len(RULE_ORDER)
        return (rank, self.path, self.unit or "", self.rule, self.fingerprint)


def make_fingerprint(rule: str, path: str, qualname: str | None, before_text: str) -> str:
    digest = hashlib.sha256(
        "/".join([rule, path, qualname or "", normalize_text(before_text)]).encode("utf-8")
    ).hexdigest()[:12]
    return f"{rule}/{path}/{qualname or '-'}/{digest}"

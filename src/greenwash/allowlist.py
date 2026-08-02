"""Exemption records (.greenwash/allow.toml, read from the BASE side — SPEC §6)."""

from __future__ import annotations

import datetime
import tomllib
from dataclasses import dataclass

MAX_EXPIRY_DAYS = 180


@dataclass
class AllowEntry:
    fingerprint: str
    rule: str
    reason: str
    author: str
    created: str
    expires: str


def load_allowlist(data: bytes | None) -> tuple[list[AllowEntry], str | None]:
    """-> (entries, error). A corrupt ledger voids every exemption in the
    repo, so it must be reported rather than swallowed (SPEC §6)."""
    if not data:
        return [], None
    try:
        raw = tomllib.loads(data.decode("utf-8", errors="replace"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        return [], f".greenwash/allow.toml could not be parsed ({exc}); no exemptions are active"
    entries: list[AllowEntry] = []
    for item in raw.get("allow", []):
        if not isinstance(item, dict):
            continue
        fingerprint = item.get("fingerprint")
        reason = item.get("reason")
        expires = item.get("expires")
        if isinstance(expires, datetime.date):
            expires = expires.isoformat()
        if not (isinstance(fingerprint, str) and isinstance(reason, str) and reason.strip()):
            continue  # invalid entries are ignored, never honoured
        if not isinstance(expires, str):
            continue
        created = item.get("created", "")
        if isinstance(created, datetime.date):
            created = created.isoformat()
        entries.append(
            AllowEntry(
                fingerprint=fingerprint,
                rule=str(item.get("rule", "")),
                reason=reason,
                author=str(item.get("author", "")),
                created=str(created),
                expires=expires,
            )
        )
    return entries, None


def active_fingerprints(entries: list[AllowEntry], today: datetime.date) -> set[str]:
    """Exemptions still in force today.

    The MAX_EXPIRY_DAYS cap was only checked when `greenwash allow` wrote an
    entry, so a hand-edited ledger could grant a ten-year exemption and be
    honoured (reader audit 2026-08-02). The cap is enforced here too, against
    `created` where it is present and against today otherwise, so the reading
    side never trusts a window the writing side would have refused.
    """
    active: set[str] = set()
    for e in entries:
        try:
            expiry = datetime.date.fromisoformat(e.expires)
        except ValueError:
            continue
        if expiry < today:
            continue
        try:
            start = datetime.date.fromisoformat(e.created)
        except ValueError:
            start = today
        if (expiry - start).days > MAX_EXPIRY_DAYS:
            continue  # over the cap: treat as not exempted
        active.add(e.fingerprint)
    return active

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


def load_allowlist(data: bytes | None) -> list[AllowEntry]:
    if not data:
        return []
    try:
        raw = tomllib.loads(data.decode("utf-8", errors="replace"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError):
        return []
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
    return entries


def active_fingerprints(entries: list[AllowEntry], today: datetime.date) -> set[str]:
    active: set[str] = set()
    for e in entries:
        try:
            expiry = datetime.date.fromisoformat(e.expires)
        except ValueError:
            continue
        if expiry >= today:
            active.add(e.fingerprint)
    return active

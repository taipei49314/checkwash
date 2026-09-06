"""Exemption records (.checkwash/allow.toml, or the legacy .greenwash/allow.toml; read from the BASE side — SPEC §6)."""

from __future__ import annotations

import datetime
import tomllib
from dataclasses import dataclass

from checkwash.findings import fingerprint_issue, fingerprint_state

MAX_EXPIRY_DAYS = 180


@dataclass
class AllowEntry:
    fingerprint: str
    rule: str
    reason: str
    author: str
    created: str
    expires: str


def load_allowlist(data: bytes | None, path: str = ".greenwash/allow.toml") -> tuple[list[AllowEntry], str | None]:
    """-> (entries, error). A corrupt ledger voids every exemption in the
    repo, so it must be reported rather than swallowed (SPEC §6)."""
    if not data:
        return [], None
    # utf-8-sig, not utf-8: PowerShell 5.1 Set-Content -Encoding utf8 writes a BOM,
    # which tomllib rejects at line 1 column 1 and which then discarded the whole
    # file in favour of defaults. Every other reader already strips it (issue #71).
    try:
        raw = tomllib.loads(data.decode("utf-8-sig", errors="replace"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        return [], f"{path} could not be parsed ({exc}); no exemptions are active"
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


@dataclass
class AllowSummary:
    present: bool
    parse_error: str | None
    entries: int
    active: int
    expired: int
    over_cap: int
    retired: int = 0
    invalid: int = 0


def _entry_state(e: AllowEntry, today: datetime.date) -> str:
    """`active`, `expired`, `over_cap`, `retired`, or `invalid` — one implementation
    both consumers share, so the doctor's summary and the gate can never
    disagree (their docstrings promise "same rules").

    The cap is anchored at `min(created, today)`: anchoring at `created`
    alone let a hand-edited ledger set `created = "2030-01-01"` /
    `expires = "2030-06-01"` — a 151-day window that does not even start for
    years — and be honoured today, which defeats the read-side enforcement
    exactly the way bypass #39 closed (audit 2026-08-19). A missing or
    unparseable `created` still anchors at today.
    """
    key_state = fingerprint_state(e.fingerprint, e.rule)
    if key_state != "supported":
        return key_state
    try:
        expiry = datetime.date.fromisoformat(e.expires)
    except ValueError:
        return "invalid"
    try:
        start = datetime.date.fromisoformat(e.created)
    except ValueError:
        start = today
    anchor = min(start, today)
    if (expiry - anchor).days > MAX_EXPIRY_DAYS:
        return "over_cap"
    if expiry < today:
        return "expired"
    return "active"


def summarize_allowlist(data: bytes | None, today: datetime.date) -> AllowSummary:
    """How the ledger will be honoured today. Same rules as `active_fingerprints`."""
    if not data:
        return AllowSummary(False, None, 0, 0, 0, 0)
    entries, err = load_allowlist(data)
    if err:
        return AllowSummary(True, err, 0, 0, 0, 0)
    active = expired = over_cap = retired = invalid = 0
    for e in entries:
        state = _entry_state(e, today)
        if state == "over_cap":
            over_cap += 1
        elif state == "expired":
            expired += 1
        elif state == "active":
            active += 1
        elif state == "retired":
            retired += 1
        elif state == "invalid":
            invalid += 1
    return AllowSummary(True, None, len(entries), active, expired, over_cap, retired, invalid)


def fingerprint_diagnostics(entries: list[AllowEntry]) -> list[str]:
    """Unsupported keys remain parsed for ledger-change detection, but visible.

    Parsing must not filter these out: the engine compares parsed before/after
    entries to distinguish append-only additions from revocation or rewriting.
    """
    return [
        f"{entry.fingerprint}: {issue}"
        for entry in entries
        if (issue := fingerprint_issue(entry.fingerprint, entry.rule)) is not None
    ]


def active_fingerprints(entries: list[AllowEntry], today: datetime.date) -> set[str]:
    """Exemptions still in force today.

    The MAX_EXPIRY_DAYS cap was only checked when `checkwash allow` wrote an
    entry, so a hand-edited ledger could grant a ten-year exemption and be
    honoured (reader audit 2026-08-02). The cap is enforced here too,
    anchored at `min(created, today)` — see `_entry_state` for why the
    anchor is not `created` alone — so the reading side never trusts a
    window the writing side would have refused.
    """
    return {
        e.fingerprint for e in entries if _entry_state(e, today) == "active"
    }

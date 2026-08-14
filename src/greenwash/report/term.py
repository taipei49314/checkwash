"""Terminal report rendering. Colors honour NO_COLOR and non-tty output."""

from __future__ import annotations

import os
import sys

from greenwash.allowlist import MAX_EXPIRY_DAYS
from greenwash.findings import Finding
from greenwash.ir.model import IR

_SEV_COLOR = {"critical": "35", "high": "31", "warn": "33", "info": "36"}


def _use_color(stream) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    return hasattr(stream, "isatty") and stream.isatty()


def _symbols(stream) -> dict[str, str]:
    """Unicode glyphs only when the stream encoding can carry them.

    Piped output on legacy-locale Windows is cp1252; writing '✓' there raised
    UnicodeEncodeError and turned a clean diff into exit 1 (confirmed
    red-team crash). ASCII fallback keeps the exit-code contract intact.
    """
    enc = getattr(stream, "encoding", None) or "ascii"
    try:
        "✓✗⚠—".encode(enc)
    except (UnicodeEncodeError, LookupError):
        return {"pass": "OK", "block": "X", "warn": "!", "dash": "-"}
    return {"pass": "✓", "block": "✗", "warn": "⚠", "dash": "—"}


# One line of evidence, bounded. SUPPRESSION_ADDED on a generated module
# printed a ~1400-character unicode regex twice — once in the message and
# once as evidence — and buried every other finding on the screen.
_EVIDENCE_WIDTH = 160


def _evidence(text: str | None) -> str:
    if not text:
        return ""
    first = text.splitlines()[0]
    return first if len(first) <= _EVIDENCE_WIDTH else first[: _EVIDENCE_WIDTH - 1] + "…"


def _c(code: str, text: str, color: bool) -> str:
    return f"\x1b[{code}m{text}\x1b[0m" if color else text


def render(
    ir: IR,
    findings: list[Finding],
    verdict: str,
    fail_on: str,
    stream=None,
    errors: list[str] | None = None,
) -> str:
    stream = stream or sys.stdout
    color = _use_color(stream)
    sym = _symbols(stream)
    lines: list[str] = []

    visible = [f for f in findings if not f.allowlisted]
    suppressed = [f for f in findings if f.allowlisted]
    blocking = verdict == "block"

    if not visible and not suppressed:
        head = "greenwash: no known tampering pattern detected"
        lines.append(_c("32", sym["pass"] + " " + head, color))
    else:
        n_high = sum(1 for f in visible if f.severity in ("high", "critical"))
        if blocking:
            head = f"greenwash: {n_high} finding(s) at or above {fail_on} {sym['dash']} blocking"
            lines.append(_c("31", sym["block"] + " " + head, color))
        else:
            head = f"greenwash: {len(visible)} finding(s), none at or above {fail_on}"
            lines.append(_c("33", sym["warn"] + " " + head, color))
    lines.append("")

    for f in visible:
        sev = _c(_SEV_COLOR.get(f.severity, "0"), f.severity.upper(), color)
        where = f"{f.path} :: {f.unit}" if f.unit else f.path
        lines.append(f"{f.rule}   {sev}   {where}")
        lines.append(f"  {f.message}")
        if f.escalators:
            lines.append(f"  why high: {', '.join(f.escalators)}" if f.severity in ("high", "critical") else f"  escalators: {', '.join(f.escalators)}")
        if f.deescalators:
            lines.append(f"  held at {f.severity} by: {', '.join(f.deescalators)}")
        elif f.severity in ("high", "critical"):
            # Say only what did not happen. Listing credits that did not
            # fire as if they should have is the COLLECTION_CONTROL_UNEXPLAINED
            # class of lie.
            lines.append("  no de-escalator applied")
        if f.before is not None:
            lines.append(f"  before  {_evidence(f.before.text)}")
        if f.after is not None:
            lines.append(f"  after   {_evidence(f.after.text)}")
        if f.severity in ("high", "critical"):
            lines.append("  next: fix the code, or record a reviewed exemption:")
            lines.append(f'    greenwash allow "{f.fingerprint}" --reason "..."')
            # The allowlist is read from the *base* side, so an agent cannot
            # exempt itself inside the diff under review. Correct, and it made
            # the printed instruction look broken: run it, re-run check, get
            # the identical block, with nothing saying why (field integration
            # 2026-08-07). The reader of a blocking report is exactly the
            # person who needs the second half of the sentence.
            lines.append("    then commit .greenwash/allow.toml — it is read from the base side")
        lines.append("")

    for message in errors or []:
        lines.append(_c("33", "! " + message, color))
    if ir.skipped_files:
        lines.append(f"skipped (unparseable): {', '.join(ir.skipped_files)}")
    if suppressed:
        lines.append(
            f"allowlisted findings: {len(suppressed)} "
            f"(see .greenwash/allow.toml; expiry cap {MAX_EXPIRY_DAYS} days; "
            "takes effect after commit)"
        )
    counts = {"critical": 0, "high": 0, "warn": 0, "info": 0}
    for f in visible:
        counts[f.severity] += 1
    lines.append(
        "summary: "
        + " ".join(f"{k}={v}" for k, v in counts.items())
        + f" verdict={verdict} allow_cap={MAX_EXPIRY_DAYS}d"
    )
    return "\n".join(lines) + "\n"

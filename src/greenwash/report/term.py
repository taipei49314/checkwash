"""Terminal report rendering. Colors honour NO_COLOR and non-tty output."""

from __future__ import annotations

import os
import sys

from greenwash.findings import Finding
from greenwash.ir.model import IR

_SEV_COLOR = {"critical": "35", "high": "31", "warn": "33", "info": "36"}


def _use_color(stream) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    return hasattr(stream, "isatty") and stream.isatty()


def _c(code: str, text: str, color: bool) -> str:
    return f"\x1b[{code}m{text}\x1b[0m" if color else text


def render(ir: IR, findings: list[Finding], verdict: str, fail_on: str, stream=None) -> str:
    stream = stream or sys.stdout
    color = _use_color(stream)
    lines: list[str] = []

    visible = [f for f in findings if not f.allowlisted]
    suppressed = [f for f in findings if f.allowlisted]
    blocking = verdict == "block"

    if not visible and not suppressed:
        head = "greenwash: no known tampering pattern detected"
        lines.append(_c("32", "✓ " + head, color))
    else:
        n_high = sum(1 for f in visible if f.severity in ("high", "critical"))
        if blocking:
            head = f"greenwash: {n_high} finding(s) at or above {fail_on} — blocking"
            lines.append(_c("31", "✗ " + head, color))
        else:
            head = f"greenwash: {len(visible)} finding(s), none at or above {fail_on}"
            lines.append(_c("33", "⚠ " + head, color))
    lines.append("")

    for f in visible:
        sev = _c(_SEV_COLOR.get(f.severity, "0"), f.severity.upper(), color)
        where = f"{f.path} :: {f.unit}" if f.unit else f.path
        lines.append(f"{f.rule}   {sev}   {where}")
        lines.append(f"  {f.message}")
        if f.escalators:
            lines.append(f"  escalators: {', '.join(f.escalators)}")
        if f.deescalators:
            lines.append(f"  context: {', '.join(f.deescalators)}")
        if f.before is not None:
            lines.append(f"  before  {f.before.text.splitlines()[0] if f.before.text else ''}")
        if f.after is not None:
            lines.append(f"  after   {f.after.text.splitlines()[0] if f.after.text else ''}")
        if f.severity in ("high", "critical"):
            lines.append("  fix the code, or record a reviewed exemption:")
            lines.append(f'    greenwash allow "{f.fingerprint}" --reason "..."')
        lines.append("")

    if ir.skipped_files:
        lines.append(f"skipped (unparseable): {', '.join(ir.skipped_files)}")
    if suppressed:
        lines.append(f"allowlisted findings: {len(suppressed)} (see .greenwash/allow.toml)")
    counts = {"critical": 0, "high": 0, "warn": 0, "info": 0}
    for f in visible:
        counts[f.severity] += 1
    lines.append(
        "summary: "
        + " ".join(f"{k}={v}" for k, v in counts.items())
        + f" verdict={verdict}"
    )
    return "\n".join(lines) + "\n"

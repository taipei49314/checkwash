"""Canonical findings JSON (SPEC §8: sorted keys, no timestamps, LF only)."""

from __future__ import annotations

from collections.abc import Iterable
import json

from checkwash import FINDINGS_VERSION, __version__
from checkwash.change import UnreadSide
from checkwash.findings import Finding
from checkwash.ir.model import IR, to_jsonable
from checkwash.report.unread import unread_entries


def findings_to_json(
    ir: IR, findings: list[Finding], verdict: str, errors: list[str] | None = None,
    unread: Iterable[UnreadSide] = (),
) -> str:
    counts = {"critical": 0, "high": 0, "warn": 0, "info": 0}
    for f in findings:
        counts[f.severity] += 1
    payload = {
        "checkwash_findings_version": FINDINGS_VERSION,
        "run": {
            "base": ir.base,
            "head": ir.head,
            "checkwash_version": __version__,
        },
        "findings": [to_jsonable(f) for f in findings],
        "summary": counts,
        "skipped_files": list(ir.skipped_files),
        "config_errors": list(errors or []),
        "verdict": verdict,
    }
    entries = unread_entries(unread)
    if entries:
        # Optional, so omitted when empty: a run with no unread side keeps
        # the envelope it had before #454, byte for byte.
        payload["unread"] = entries
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2) + "\n"


def ir_to_json(ir: IR) -> str:
    return json.dumps(to_jsonable(ir), sort_keys=True, ensure_ascii=False, indent=2) + "\n"

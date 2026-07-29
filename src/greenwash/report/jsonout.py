"""Canonical findings JSON (SPEC §8: sorted keys, no timestamps, LF only)."""

from __future__ import annotations

import json

from greenwash import FINDINGS_VERSION, __version__
from greenwash.findings import Finding
from greenwash.ir.model import IR, to_jsonable


def findings_to_json(
    ir: IR, findings: list[Finding], verdict: str, errors: list[str] | None = None
) -> str:
    counts = {"critical": 0, "high": 0, "warn": 0, "info": 0}
    for f in findings:
        counts[f.severity] += 1
    payload = {
        "greenwash_findings_version": FINDINGS_VERSION,
        "run": {
            "base": ir.base,
            "head": ir.head,
            "greenwash_version": __version__,
        },
        "findings": [to_jsonable(f) for f in findings],
        "summary": counts,
        "skipped_files": list(ir.skipped_files),
        "config_errors": list(errors or []),
        "verdict": verdict,
    }
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2) + "\n"


def ir_to_json(ir: IR) -> str:
    return json.dumps(to_jsonable(ir), sort_keys=True, ensure_ascii=False, indent=2) + "\n"

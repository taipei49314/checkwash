"""Separate deterministic syntax-coverage report; never a tampering verdict."""

from __future__ import annotations

from dataclasses import asdict
import json

from checkwash import __version__
from checkwash.ir.model import IR
from checkwash.report.context import ReportContext


def coverage_to_json(ir: IR, context: ReportContext) -> str:
    payload = {
        "checkwash_coverage_version": 1,
        "run": {"base": ir.base, "head": ir.head, "checkwash_version": __version__},
        "scope": "javascript_assertion_candidates",
        "status": "incomplete" if context.coverage_gaps else "no_known_gaps",
        "files": [{"path": path, "side": side} for path, side in context.coverage_files],
        "gaps": [asdict(gap) for gap in context.coverage_gaps],
    }
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2) + "\n"

"""SARIF 2.1.0 subset for GitHub code scanning (T2.1).

Deterministic: sorted keys, no timestamps, LF, UTF-8. This is a projection
of findings, not a second verdict. Exit codes stay SPEC §9.
"""

from __future__ import annotations

import json
from urllib.parse import quote

from checkwash import __version__
from checkwash.findings import CHANGE_FINGERPRINT_RULES, Finding, fingerprint_state
from checkwash.ir.model import IR
from checkwash.report.context import ReportContext

_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
_INFORMATION_URI = "https://github.com/taipei49314/checkwash"

_LEVEL = {
    "info": "note",
    "warn": "warning",
    "high": "error",
    "critical": "error",
}


def findings_to_sarif(
    ir: IR, findings: list[Finding], context: ReportContext | None = None
) -> str:
    visible = [f for f in findings if not f.allowlisted]
    rule_ids = sorted({f.rule for f in visible})
    rules = [
        {
            "id": rule_id,
            "name": rule_id,
            "shortDescription": {"text": rule_id},
        }
        for rule_id in rule_ids
    ]
    results = [_result(f, context) for f in sorted(visible, key=lambda item: item.sort_key())]
    payload = {
        "$schema": _SCHEMA,
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "informationUri": _INFORMATION_URI,
                        "name": "checkwash",
                        "rules": rules,
                        "semanticVersion": __version__,
                    }
                },
                "properties": {
                    "checkwash.base": ir.base,
                    "checkwash.head": ir.head,
                },
                "results": results,
            }
        ],
    }
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2) + "\n"


def _result(finding: Finding, context: ReportContext | None) -> dict:
    path = finding.path.replace("\\", "/")
    location = None
    if context is not None and finding.after is not None:
        location = context.location(path, finding.after)
    if location is not None:
        path, line = location
    physical = {"artifactLocation": {"uri": quote(path, safe="/")}}
    if location is not None:
        # Line-only regions avoid confusing Python character offsets in
        # normalized text with SARIF offsets in the original artifact.
        physical["region"] = {"startLine": line}
    result = {
        "level": _LEVEL[finding.severity],
        "locations": [
            {
                "physicalLocation": physical
            }
        ],
        "message": {"text": finding.message},
        "partialFingerprints": {
            (
                "checkwash/v2"
                if finding.rule in CHANGE_FINGERPRINT_RULES
                and fingerprint_state(finding.fingerprint, finding.rule) == "supported"
                else "checkwash/v1"
            ): finding.fingerprint
        },
        "ruleId": finding.rule,
    }
    if location is None:
        evidence = finding.after or finding.before
        if evidence is not None:
            result["properties"] = {
                "checkwash.evidenceSide": "head" if finding.after is not None else "base",
                "checkwash.evidenceText": evidence.text,
            }
    return result

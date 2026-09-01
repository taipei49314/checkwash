"""SARIF 2.1.0 subset for GitHub code scanning (T2.1).

Deterministic: sorted keys, no timestamps, LF, UTF-8. This is a projection
of findings, not a second verdict. Exit codes stay SPEC §9.
"""

from __future__ import annotations

import json

from checkwash import __version__
from checkwash.findings import Finding
from checkwash.ir.model import IR

_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
_INFORMATION_URI = "https://github.com/taipei49314/greenwash"

_LEVEL = {
    "info": "note",
    "warn": "warning",
    "high": "error",
    "critical": "error",
}


def findings_to_sarif(ir: IR, findings: list[Finding]) -> str:
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
    results = [_result(f) for f in sorted(visible, key=lambda item: item.sort_key())]
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


def _result(finding: Finding) -> dict:
    evidence = finding.after or finding.before
    region = {"startLine": 1}
    if evidence is not None:
        # Spans are character offsets, not lines. GitHub requires startLine.
        # Until the IR carries a line, pin the file and keep the span in
        # properties rather than invent a line number from missing source.
        region = {"startLine": 1, "charOffset": evidence.span[0]}
    return {
        "level": _LEVEL[finding.severity],
        "locations": [
            {
                "physicalLocation": {
                    "artifactLocation": {"uri": finding.path.replace("\\", "/")},
                    "region": region,
                }
            }
        ],
        "message": {"text": finding.message},
        "partialFingerprints": {"checkwash/v1": finding.fingerprint},
        "ruleId": finding.rule,
    }

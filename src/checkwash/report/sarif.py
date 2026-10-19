"""SARIF 2.1.0 subset for GitHub code scanning (T2.1).

Deterministic: sorted keys, no timestamps, LF, UTF-8. This is a projection
of findings, not a second verdict. Exit codes stay SPEC §9.
"""

from __future__ import annotations

from collections.abc import Iterable
import json
from urllib.parse import quote

from checkwash import __version__
from checkwash.change import UnreadSide
from checkwash.findings import Finding, is_content_bound_fingerprint
from checkwash.ir.model import IR
from checkwash.report.context import ReportContext
from checkwash.report.unread import sorted_unread

_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
_INFORMATION_URI = "https://github.com/taipei49314/checkwash"

_LEVEL = {
    "info": "note",
    "warn": "warning",
    "high": "error",
    "critical": "error",
}


def findings_to_sarif(
    ir: IR, findings: list[Finding], context: ReportContext | None = None,
    unread: Iterable[UnreadSide] = (),
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
    notifications = []
    if context is not None:
        for gap in context.coverage_gaps:
            notification = {
                "level": "warning",
                "message": {"text": gap.message()},
                "properties": {
                    "checkwash.path": gap.path,
                    "checkwash.side": gap.side,
                    "checkwash.line": gap.line,
                    "checkwash.column": gap.column,
                },
            }
            # A base-side coordinate is not a location in the checked-out
            # head. Keep its side/path/line in the diagnostic instead.
            if gap.side == "after":
                notification["locations"] = [{"physicalLocation": {
                    "artifactLocation": {"uri": quote(gap.path.replace("\\", "/"), safe="/")},
                    "region": {"startLine": gap.line},
                }}]
            notifications.append(notification)
    # Unread sides follow the coverage gaps in the same invocation (#454).
    notifications.extend(_unread_notification(side) for side in sorted_unread(unread))
    if notifications:
        # The run gave a verdict, so the execution succeeded; what it did
        # not read is a notification, never a result.
        payload["runs"][0]["invocations"] = [{
            "executionSuccessful": True,
            "toolExecutionNotifications": notifications,
        }]
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2) + "\n"


def _unread_notification(side: UnreadSide) -> dict:
    """A side carried unread (#454): the stderr note and its four facts.

    The properties are the findings JSON entry's keys, prefixed as the
    coverage gaps' are, and nothing else the side may carry (#455).
    """
    notification = {
        "level": "warning",
        "message": {"text": side.note()},
        "properties": {
            "checkwash.path": side.path,
            "checkwash.side": side.side,
            "checkwash.size": side.size,
            "checkwash.limit": side.limit,
        },
    }
    # A base side is not a file in the checked-out head or working tree, as
    # a base-side coverage gap is not; its path stays in the properties. No
    # side was read, so no line is named.
    if side.side != "base":
        notification["locations"] = [{"physicalLocation": {
            "artifactLocation": {"uri": quote(side.path.replace("\\", "/"), safe="/")},
        }}]
    return notification


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
                if is_content_bound_fingerprint(finding.fingerprint, finding.rule)
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

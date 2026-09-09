"""Versioned quality formats, separate from legacy findings schema 2."""
import json
import unicodedata


def json_report(payload):
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2) + "\n"


def terminal(payload):
    run = payload["run"]
    lines = [f"Checkwash quality | {run['mode'].upper()} | {payload['verdict'].upper()} | analysis {payload['analysis_status'].upper()}"]
    if run["discovery"]:
        lines.append("DISCOVERY: no base targets. No completeness or enforcement claim.")
    for finding in payload["findings"]:
        suffix = " [base exemption]" if finding["allowlisted"] else ""
        lines.append(f"{finding['severity'].upper()} {finding['rule']} [{finding['target_id'] or 'policy'}]{suffix}")
        lines.append("  " + finding["message"])
        if finding["before"]["state"] == finding["after"]["state"] == "known":
            lines.append(f"  {finding['before']['data']} -> {finding['after']['data']}")
        for place in finding["locations"]:
            lines.append(f"  {place['side']} {place['path']}:{place['start_line']}")
        if "fingerprint" in finding:
            lines.append("  " + finding["fingerprint"])
    for diagnostic in payload["diagnostics"]:
        lines.append(f"{diagnostic['kind'].upper()} {diagnostic['code']}: {diagnostic['message']}")
    lines.append("Evidence concerns declared configuration only. CI execution was not verified.")
    # Paths and diagnostic keys are repository input. Preserve visible text
    # while preventing control/bidi characters from impersonating new output.
    def visible(line):
        return "".join(("\\u%04x" % ord(c)) if unicodedata.category(c) in {"Cc", "Cf"} else c for c in line)
    return "\n".join(visible(line) for line in lines) + "\n"


def sarif(payload):
    from .model import RULES
    levels = {"critical": "error", "high": "error", "warn": "warning", "info": "note"}
    results = []
    for finding in payload["findings"]:
        entry = {"ruleId": finding["rule"], "level": levels[finding["severity"]],
                 "message": {"text": finding["message"]},
                 "properties": {"evidenceLevel": finding["evidence_level"], "targetId": finding["target_id"], "mode": payload["run"]["mode"]}}
        locations = []
        for place in finding["locations"]:
            from urllib.parse import quote
            locations.append({"physicalLocation": {"artifactLocation": {"uri": quote(place["path"], safe="/")},
                                                     "region": {"startLine": place["start_line"], "startColumn": place["start_column"], "endLine": place["end_line"], "endColumn": place["end_column"]}},
                              "properties": {"snapshotSide": place["side"]}})
        if locations:
            entry["locations"] = locations[-1:]
            entry["relatedLocations"] = [dict(loc, id=i + 1) for i, loc in enumerate(locations[:-1])]
        if "fingerprint" in finding:
            entry["partialFingerprints"] = {"checkwash/quality/q1": finding["fingerprint"]}
        if finding["allowlisted"]:
            entry["suppressions"] = [{"kind": "external", "status": "accepted"}]
        results.append(entry)
    notifications = [{"descriptor": {"id": d["code"]}, "level": "error" if d["kind"] == "error" else "warning", "message": {"text": d["message"]}} for d in payload["diagnostics"]]
    return json_report({"version": "2.1.0", "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
                        "runs": [{"tool": {"driver": {"name": "checkwash-quality", "rules": [{"id": r, "shortDescription": {"text": r}} for r in RULES]}},
                                  "results": results, "invocations": [{"executionSuccessful": payload["analysis_status"] == "complete", "toolExecutionNotifications": notifications}]}]})

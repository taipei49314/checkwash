"""Versioned quality formats, separate from legacy findings schema 2."""
import json
import unicodedata


def json_report(payload):
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2) + "\n"


def explanation(rule, description, format):
    """Rule metadata only: describing a rule does not analyze a change."""
    help_text = "See docs/quality.md for the support matrix and base-only exemptions."
    if format == "term":
        return f"{rule}: {description}\n{help_text}\n"
    if format == "json":
        return json_report({"operation": "explain", "authority": "advisory_only",
                            "rule": rule, "description": description, "documentation": "docs/quality.md"})
    return json_report({"version": "2.1.0", "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
                        "runs": [{"tool": {"driver": {"name": "checkwash-quality",
                                                       "rules": [{"id": rule, "shortDescription": {"text": rule},
                                                                  "fullDescription": {"text": description},
                                                                  "help": {"text": help_text}}],
                                                       "properties": {"operation": "explain", "authority": "advisory_only"}}},
                                  "results": []}]})


def profile_inventory(rows, format, *, details=False):
    if format == "json":
        return json_report({"profiles": rows})
    lines = ["Checkwash quality profiles | limited preview"]
    brief = {"id", "tool", "tool_version", "digest", "scope"}
    for row in rows:
        lines.append(f"{row['id']}: {row['tool']} {row['tool_version']} | {row['scope']}")
        lines.append("  digest: " + row["digest"])
        if details:
            for key in sorted(set(row) - brief):
                lines.append("  " + key + ":")
                lines.extend("    " + line for line in json_report(row[key]).rstrip().splitlines())
    lines.append("Models describe declared configuration; tool execution and CI protection were not verified.")
    return "\n".join(visible(line) for line in lines) + "\n"


def visible(line):
    # Repository input must not impersonate new terminal output.
    return "".join(("\\u%04x" % ord(c)) if unicodedata.category(c) in {"Cc", "Cf"} else c for c in line)


def terminal(payload):
    run = payload["run"]
    lines = [f"Checkwash quality | {run['mode'].upper()} | {payload['verdict'].upper()} | analysis {payload['analysis_status'].upper()}"]
    if run["discovery"]:
        lines.append("DISCOVERY: no base targets. No completeness or enforcement claim.")
    for finding, paths, count, files in grouped(payload["findings"]):
        suffix = " [base exemption]" if finding["allowlisted"] else ""
        counted = f"  {count} files" if count > 1 else ""
        lines.append(f"{finding['severity'].upper()} {finding['rule']} [{finding['target_id'] or 'policy'}]{suffix}{counted}")
        # One line for several files names the setting, not the first file it was found in.
        message = finding["message"].replace(finding["dimension"], finding["dimension"].split("@", 1)[0], 1) if count > 1 else finding["message"]
        lines.append("  " + message)
        if count > 1:
            lines.append("  files: " + ", ".join(files))
        if finding["rule"] == "QW_RULE_DISABLED" and finding["dimension"].split("@", 1)[0] == "ruff.lint.rules":
            removed = finding["lost"]
            lines.append(f"  removed {len(removed)}: {compress(removed)}")
            if added := finding["gained"]:
                lines.append(f"  added {len(added)}: {compress(added)}")
        elif finding["before"]["state"] == finding["after"]["state"] == "known":
            lines.append(f"  {finding['before']['data']} -> {finding['after']['data']}")
        for place in paths:
            # location() returns an empty span at 1:1 when a key cannot be located.
            where = place["path"]
            if place["start_line"] == place["end_line"] == place["end_column"] == 1:
                where += " (file only)"
            else:
                where += f":{place['start_line']}"
            lines.append(f"  {place['side']} {where}")
        if "fingerprint" in finding:
            lines.append("  " + finding["fingerprint"])
    for diagnostic in payload["diagnostics"]:
        lines.append(f"{diagnostic['kind'].upper()} {diagnostic['code']}: {diagnostic['message']}")
    lines.append("Evidence concerns declared configuration only. CI execution was not verified.")
    return "\n".join(visible(line) for line in lines) + "\n"


def compress(codes):
    """`B002-B035, B039, F401`: runs of three or more consecutive codes fold into a range."""
    out, run = [], []
    for code in codes:
        head = code.rstrip("0123456789")
        number = int(code[len(head):]) if len(head) < len(code) else None
        if run and run[-1][0] == head and number is not None and run[-1][1] is not None and number == run[-1][1] + 1:
            run.append((head, number, code))
            continue
        out.extend(_fold(run))
        run = [(head, number, code)]
    out.extend(_fold(run))
    return ", ".join(out)


def _fold(run):
    if len(run) >= 3:
        return [f"{run[0][2]}-{run[-1][2]}"]
    return [entry[2] for entry in run]


def grouped(findings):
    """Findings that differ only in which file they name, merged under the count the terminal shows.

    A project-wide weakened setting produces one finding per analysed file; a terminal reader
    wants the change once, with the files that carry it. Json keeps every entry.
    """
    merged, order = {}, []
    for finding in findings:
        dimension = finding["dimension"]
        base = dimension.split("@", 1)[0]
        key = (finding["rule"], finding.get("target_id"), finding["severity"], finding["allowlisted"],
               base, tuple(finding.get("lost") or ()), tuple(finding.get("gained") or ()))
        if key not in merged:
            merged[key] = (finding, [], 0, [])
            order.append(key)
        entry, paths, count, files = merged[key]
        for place in finding["locations"]:
            if not any(_same_place(place, seen) for seen in paths):
                paths.append(place)
        if "@" in dimension:
            files.append(dimension.split("@", 1)[1])
        merged[key] = (entry, paths, count + 1, files)
    return [merged[key] for key in order]


def _same_place(a, b):
    return (a["side"], a["path"], a["start_line"], a["start_column"]) == (b["side"], b["path"], b["start_line"], b["start_column"])


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

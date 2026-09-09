"""Independent quality verdicts; existing test-oracle gating is untouched."""
from __future__ import annotations

import datetime

from checkwash import __version__
from .adapters import ADAPTERS
from .model import ALLOW_PATH, POLICY_PATH, MAX_SOURCES, RULES, QualityError, canonical, digest, known
from .policy import load_exemptions, load_policy
from .profiles import load as load_profile
from .resolver import NAMES, read_config, declarations
from .snapshot import source


def event(rule, target_id, dimension, before, after, sources, locations, *, severity="warn", message="", kind="changed"):
    return {"rule": rule, "severity": severity, "target_id": target_id,
            "evidence_level": "declaration", "dimension": dimension, "event_kind": kind,
            "message": message, "before": before, "after": after, "allowlisted": False,
            "locations": locations, "sources": sources, "lost": [], "gained": [],
            "remediation": "Review this change and the reported analysis boundary."}


def diagnostic(payload, code, message, target_id=None, dimensions=(), *, kind="incomplete"):
    payload["diagnostics"].append({"code": code, "kind": kind, "target_id": target_id,
                                   "dimensions": sorted(set(dimensions)), "message": message, "locations": []})
    if kind == "incomplete":
        payload["findings"].append(event("QW_ANALYSIS_INCOMPLETE", target_id,
                                         ",".join(sorted(dimensions)) or "analysis",
                                         {"state": "unknown"}, {"state": "unknown"}, [], [],
                                         message=message, kind=code))


def new_payload(base_label, head_label):
    return {"checkwash_quality_version": 1,
            "run": {"base": base_label, "head": head_label, "checkwash_version": __version__,
                    "mode": "report", "discovery": False},
            "analysis_status": "complete", "verdict": "no_blocking_finding",
            "targets": [], "findings": [], "diagnostics": [], "summary": {}}


def finish(payload):
    status = [t["status"] for t in payload["targets"]]
    hard_error = any(d["kind"] == "error" for d in payload["diagnostics"])
    incomplete = any(d["kind"] == "incomplete" for d in payload["diagnostics"])
    payload["analysis_status"] = ("error" if hard_error else "unsupported" if status and all(s == "unsupported" for s in status)
                                  else "partial" if incomplete or any(s != "complete" for s in status) else "complete")
    count = {s: sum(f["severity"] == s for f in payload["findings"]) for s in ("critical", "high", "warn", "info")}
    blocking = sum(f["severity"] in {"critical", "high"} and not f["allowlisted"] for f in payload["findings"])
    payload["summary"] = {**count, "blocking_findings": blocking,
                           "incomplete_targets": sum(s != "complete" for s in status),
                           "allowlisted_findings": sum(f["allowlisted"] for f in payload["findings"])}
    enforce = payload["run"]["mode"] == "enforce"
    if hard_error:
        verdict, code = "error", 2
    elif incomplete and enforce:
        verdict, code = "incomplete", 2
    elif blocking and enforce:
        verdict, code = "block", 1
    elif incomplete:
        verdict, code = "incomplete", 0
    elif payload["findings"]:
        verdict, code = "reported", 0
    else:
        verdict, code = "no_blocking_finding", 0
    payload["verdict"] = verdict
    payload["targets"].sort(key=lambda t: t["id"])
    payload["findings"].sort(key=lambda f: (RULES.index(f["rule"]), f["target_id"] or "", f["dimension"], f.get("fingerprint", ""), f["message"]))
    payload["diagnostics"].sort(key=lambda d: (d["target_id"] or "", d["code"], d["dimensions"], d["message"]))
    return payload, code


def analyze(base, head, *, base_label="base", head_label="head", today=None, profiles=None):
    payload = new_payload(base_label, head_label)
    try:
        _analyze(payload, base, head, today or datetime.date.today(), profiles)
        base.verify()
        head.verify()
    except QualityError as exc:
        diagnostic(payload, exc.code, str(exc), kind=exc.kind)
    except Exception as exc:
        # User data must not turn a crash into the exit-1 "block" verdict.
        diagnostic(payload, "INTERNAL_ERROR", "Quality analysis failed: " + type(exc).__name__, kind="error")
    return finish(payload)


def _analyze(payload, base, head, today, profiles):
    base_policy = base.read(POLICY_PATH)
    mode, targets = load_policy(base_policy)
    payload["run"]["mode"] = mode
    payload["run"]["discovery"] = base_policy is None
    eligible, before_allow = load_exemptions(base.read(ALLOW_PATH), today)
    for path in (POLICY_PATH, ALLOW_PATH):
        records = [source(snap, side, path, "policy")[0] for snap, side in ((base, "base"), (head, "head"))]
        before, after = base.read(path), head.read(path)
        if before == after:
            continue
        severity = "critical"
        if path == ALLOW_PATH:
            _, after_allow = load_exemptions(after, today)
            if after_allow[:len(before_allow)] == before_allow and len(after_allow) > len(before_allow):
                severity = "warn"
        payload["findings"].append(event("QW_POLICY_CHANGED", None, "quality.policy", {"state": "unknown"}, {"state": "unknown"}, records, [],
                                         severity=severity, kind="base_policy_changed",
                                         message="Quality policy changed; this run still uses base policy and exemptions."))
    if not targets:
        discover(payload, base, head)
        diagnostic(payload, "NO_BASE_TARGETS", "Discovery only: no base targets or qualified execution context.")
        return
    for target in targets:
        row = {"id": target.id, "tool": target.tool, "profile": target.profile,
               "activation_evidence": "declared_only", "status": "unsupported",
               "checked_dimensions": [], "unsupported_dimensions": [], "sources": []}
        payload["targets"].append(row)
        try:
            profile = load_profile(target.profile, target.tool) if profiles is None else profiles[target.profile]
            if profile["tool"] != target.tool:
                raise QualityError("UNKNOWN_PROFILE", "Profile tool mismatch")
            row["profile_digest"] = profile["digest"]
            for path in target.version_files:
                for snap, side in ((base, "base"), (head, "head")):
                    row["sources"].append(source(snap, side, path, "version")[0])
                if base.read(path) != head.read(path):
                    raise QualityError("TOOL_VERSION_UNRESOLVED", "Tracked version source changed; target version is unresolved")
            left = ADAPTERS[target.tool](base, target, "base", profile)
            right = ADAPTERS[target.tool](head, target, "head", profile)
            row["sources"].extend(left.sources + right.sources)
            if len(row["sources"]) > 2 * MAX_SOURCES:
                raise QualityError("RESOURCE_LIMIT", "Target source closure exceeds limit")
            # Discovery binds absent higher-priority candidates too. Source
            # digest includes both snapshots; unrelated repo paths are excluded.
            row["discovery_digest"] = digest(row["sources"])
            common = set(base.tracked) & set(head.tracked) & set(base.paths) & set(head.paths)
            if target.tool == "coverage" and left.values.get("coverage.context") != right.values.get("coverage.context"):
                for resolved in (left, right):
                    resolved.problem("CONTEXT_UNRESOLVED", "Coverage precision/measurement context changed", ["coverage.report.fail_under"])
            for resolved in (left, right):
                for code, message, dims in resolved.problems:
                    diagnostic(payload, code, message, target.id, dims)
                    row["unsupported_dimensions"].extend(dims)
            dimensions = sorted((set(left.values) & set(right.values)) - set(row["unsupported_dimensions"]))
            for dimension in dimensions:
                before, after = left.values[dimension], right.values[dimension]
                if dimension.endswith(".scope"):
                    before = sorted(set(before) & common)
                    after = sorted(set(after) & common)
                row["checked_dimensions"].append(dimension)
                compare(payload, target, row, dimension, before, after, left, right, eligible)
            if left.declarations != right.declarations and row["unsupported_dimensions"]:
                payload["findings"].append(event("QW_POLICY_CHANGED", target.id, "configuration", known(canonical(left.declarations)), known(canonical(right.declarations)), row["sources"], [],
                                                 message="Configuration changed; some effects could not be resolved."))
            row["unsupported_dimensions"] = sorted(set(row["unsupported_dimensions"]))
            row["status"] = "partial" if dimensions and row["unsupported_dimensions"] else "unsupported" if not dimensions else "complete"
        except QualityError as exc:
            row["status"] = "error" if exc.kind == "error" else "unsupported"
            row["unsupported_dimensions"] = ["target"]
            diagnostic(payload, exc.code, str(exc), target.id, ["target"], kind=exc.kind)
        except KeyError:
            row["unsupported_dimensions"] = ["target"]
            diagnostic(payload, "UNKNOWN_PROFILE", "Incomplete or unknown profile", target.id, ["target"])


def compare(payload, target, row, dimension, before, after, left, right, eligible):
    rule, lost, gained = None, [], []
    if dimension == "coverage.report.fail_under":
        if int(after) < int(before):
            rule = "QW_THRESHOLD_LOWERED"
    elif dimension.endswith(".scope") or dimension.endswith(".rules") or dimension == "mypy.error_codes":
        lost, gained = sorted(set(before) - set(after)), sorted(set(after) - set(before))
        if lost:
            rule = "QW_SCOPE_NARROWED" if dimension.endswith(".scope") else "QW_RULE_DISABLED"
    elif dimension.startswith("mypy."):
        reverse = dimension in {"mypy.ignore_errors", "mypy.ignore_missing_imports"}
        if (before is False and after is True) if reverse else (before is True and after is False):
            rule = "QW_RULE_DISABLED"
    if rule is None:
        return
    locations = [r.locations[dimension] for r in (left, right) if dimension in r.locations]
    finding = event(rule, target.id, dimension, known(before), known(after), row["sources"], locations,
                    severity="high", message=f"{dimension}: requirements weakened under the declared target.", kind="weakened")
    finding.update(evidence_level="resolved_config", lost=lost, gained=gained,
                   profile_digest=row["profile_digest"], discovery_digest=row["discovery_digest"])
    witness_digest = None
    if rule == "QW_SCOPE_NARROWED":
        witness_digest = digest(lost)
        finding["witnesses"] = {"total": len(lost), "paths": lost[:20], "set_digest": witness_digest}
        finding["lost"] = lost[:20]
    identity = {"rule": rule, "target": target.__dict__, "event_kind": "weakened", "dimension": dimension,
                "before": before, "after": after, "sources": row["sources"], "profile_digest": row["profile_digest"],
                "discovery_digest": row["discovery_digest"], "witness_digest": witness_digest}
    finding["fingerprint"] = f"{rule}/{target.id}/q1:{digest(identity)}"
    finding["allowlisted"] = finding["fingerprint"] in eligible
    finding["remediation"] = "Review the concrete loss; restore the requirement or record this exact change in a prior base-side exemption."
    payload["findings"].append(finding)


def discover(payload, base, head):
    import posixpath
    for tool, names in sorted(NAMES.items()):
        for path in sorted(set(base.paths) | set(head.paths)):
            if posixpath.basename(path) not in names:
                continue
            if base.read(path) == head.read(path):
                continue
            records, values = [], []
            for snap, side in ((base, "base"), (head, "head")):
                record, data = source(snap, side, path, "candidate")
                records.append(record)
                raw = read_config(data, path, tool)[0] if data is not None else None
                values.append(declarations(raw))
            if values[0] != values[1]:
                payload["findings"].append(event("QW_POLICY_CHANGED", None, tool + ".declaration",
                                                 known(canonical(values[0])), known(canonical(values[1])), records, [],
                                                 message="Candidate configuration changed; no base target establishes its effective context."))

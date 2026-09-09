"""Quality command integration; no changes to check's default policy."""
from checkwash.gitio import merge_base
from .engine import analyze, diagnostic, finish, new_payload
from .model import QualityError, RULES
from .profiles import available
from .report import json_report, terminal, sarif
from .snapshot import Snapshot


def run(args, today):
    if args.range == "profiles":
        if args.rule is not None or args.format == "sarif":
            return "error: quality profiles accepts no rule or SARIF format\n", 2
        rows = [{key: row[key] for key in ("id", "tool", "tool_version", "digest", "scope")} for row in available().values()]
        return json_report({"profiles": rows}), 0
    if args.range == "explain":
        if args.rule not in RULES:
            return "error: expected a quality rule ID\n", 2
        explanations = {
            "QW_THRESHOLD_LOWERED": "A resolved integral coverage minimum decreased, for example 85 to 50. Changed precision, measurement context or dynamic values withhold this proof.",
            "QW_RULE_DISABLED": "A previously enabled requirement was removed, for example selecting F401 and then ignoring F401. Gained rules do not cancel losses. Overrides must be resolved.",
            "QW_SCOPE_NARROWED": "A supported exclusion removes an existing surviving source path. The report lists witnesses. It does not estimate coverage percentages or future-file effects.",
            "QW_POLICY_CHANGED": "A declaration changed, or base-owned Checkwash policy was edited. Head policy never governs its own review. This event does not prove tool execution.",
            "QW_ANALYSIS_INCOMPLETE": "An unsupported construct or bounded resource limit prevented analysis. This cannot be exempted; enforce returns 2 and report remains explicitly incomplete.",
        }
        return f"{args.rule}: {explanations[args.rule]}\nSee docs/quality.md for the support matrix and base-only exemptions.\n", 0
    base_label, head_label = "HEAD", "worktree"
    try:
        if args.rule is not None:
            raise QualityError("POLICY_INVALID", "Unexpected extra quality argument", kind="error")
        if args.range:
            sep = "..." if "..." in args.range else ".."
            if sep not in args.range:
                raise QualityError("POLICY_INVALID", "Expected BASE..HEAD or BASE...HEAD", kind="error")
            left, right = args.range.split(sep, 1)
            if not left or not right or left.startswith("-") or right.startswith("-") or ".." in right:
                raise QualityError("POLICY_INVALID", "Invalid revision range", kind="error")
            if sep == "...":
                left = merge_base(args.repo, left, right)
            base, head = Snapshot(args.repo, left), Snapshot(args.repo, right)
        else:
            base, head = Snapshot(args.repo, "HEAD"), Snapshot(args.repo)
        base_label, head_label = base.revision, head.revision or "worktree"
        payload, code = analyze(base, head, base_label=base_label, head_label=head_label, today=today)
    except QualityError as exc:
        payload = new_payload(base_label, head_label)
        # Snapshot construction failed before trusted mode could be read.
        # Never downgrade an unknown base enforce policy to report/pass.
        diagnostic(payload, exc.code, str(exc), kind="error")
        payload, code = finish(payload)
    except Exception as exc:
        payload = new_payload(base_label, head_label)
        diagnostic(payload, "SOURCE_READ_FAILED", "Cannot establish quality snapshots: " + type(exc).__name__, kind="error")
        payload, code = finish(payload)
    return {"term": terminal, "json": json_report, "sarif": sarif}[args.format](payload), code

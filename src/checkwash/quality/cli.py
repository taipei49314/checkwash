"""Quality command integration; no changes to check's default policy."""
from checkwash.gitio import merge_base
from .engine import analyze, diagnostic, finish, new_payload
from .model import POLICY_PATH, QualityError, RULES
from .profiles import available
from .report import json_report, terminal, sarif
from .snapshot import Snapshot


def run_setup(args, today):
    from .setup import add_issue, base_result, doctor, draft, render
    try:
        snapshot = Snapshot(args.repo)
        if args.range == "init":
            result, code = draft(snapshot, root=getattr(args, "root", None) or ".",
                                 tools=getattr(args, "tool", None), paths=getattr(args, "paths", None))
        else:
            head_policy, head_revision = None, None
            try:
                head = Snapshot(args.repo, "HEAD")
                head_policy, head_revision = head.read(POLICY_PATH), head.revision
            except Exception:
                # An unborn/unreadable HEAD is advice to fix setup, never a pass.
                pass
            result, code = doctor(snapshot, head_policy=head_policy, head_revision=head_revision, today=today)
    except Exception as exc:
        result, code = base_result(args.range), 2
        result["state"] = "error"
        add_issue(result, exc.code if isinstance(exc, QualityError) else "SOURCE_READ_FAILED",
                  str(exc) if isinstance(exc, QualityError) else "Cannot inspect setup: " + type(exc).__name__)
    return render(result, args.format), code


def run(args, today):
    init_flags = any(getattr(args, key, None) is not None for key in ("root", "paths", "tool"))
    details = getattr(args, "details", False)
    if (init_flags and args.range != "init") or (details and args.range != "profiles"):
        return "error: --root, --paths and --tool are init-only; --details is profiles-only\n", 2
    if args.range in {"init", "doctor"}:
        if args.rule is not None or args.format == "sarif":
            return "error: quality init/doctor accepts no extra argument or SARIF format\n", 2
        return run_setup(args, today)
    if args.range == "profiles":
        if args.rule is not None or args.format == "sarif":
            return "error: quality profiles accepts no rule or SARIF format\n", 2
        try:
            rows = list(available().values())
        except QualityError as exc:
            return json_report({"error": exc.code, "message": str(exc)}), 2
        if not details:
            rows = [{key: row[key] for key in ("id", "tool", "tool_version", "digest", "scope")} for row in rows]
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

"""Quality command integration; no changes to check's default policy."""
from checkwash.gitio import merge_base
from .engine import analyze, diagnostic, finish, new_payload
from .model import QualityError, RULES
from .profiles import available
from .report import json_report, terminal, sarif
from .snapshot import Snapshot


def run(args, today):
    if args.range == "profiles":
        return json_report({"profiles": list(available().values())}), 0
    if args.range == "explain":
        if args.rule not in RULES:
            return "error: expected a quality rule ID\n", 2
        return f"{args.rule}: bounded configuration analysis. See docs/quality.md for evidence, exemptions and limitations.\n", 0
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

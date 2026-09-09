"""Read-only onboarding. Setup advice never supplies authority to a review."""
from __future__ import annotations

from dataclasses import asdict
import json
import posixpath

from .engine import analyze
from .model import POLICY_PATH, QualityError, Resolved, Target, inside, safe_path
from .policy import load_policy
from .profiles import available
from .resolver import choose

TOOLS = ("coverage", "ruff", "mypy")
TRANSIENT = {".git", ".venv", "venv", ".tox", ".nox", "node_modules", "build", "dist", "__pycache__"}


def advice(code):
    return {
        "NO_BASE_TARGETS": "Generate a draft with checkwash quality init, review its models/paths, then commit the policy before expecting PR enforcement.",
        "UNKNOWN_PROFILE": "Use checkwash quality profiles --details to inspect supported models; select the model matching the tool version you actually run.",
        "TOOL_VERSION_UNRESOLVED": "Review the changed version source and choose a qualified matching model; do not assume the previous model still applies.",
        "UNSUPPORTED_KEY": "Inspect the named settings against quality profiles --details. Keep the incomplete result visible until that context is supported.",
        "UNSUPPORTED_PATTERN": "The current scope model accepts only its documented literal paths and directory/** subset. Preserve existing checks when reviewing alternatives.",
        "CONTEXT_UNRESOLVED": "Inspect the selected/inherited sources and the named context. Report mode supports observation while the unresolved behavior is investigated.",
        "POLICY_INVALID": "Correct the policy syntax or target declarations; quality init prints a new draft only when no policy exists.",
        "SOURCE_INVALID": "Correct the malformed configuration source; parser errors cannot be exempted.",
        "RESOURCE_LIMIT": "Inspect the documented source/path limits and reduce the input or split declared targets without silently dropping checks.",
        "EXTERNAL_SOURCE": "Select repository-owned regular files; symlink, submodule and external configuration sources are not followed.",
        "SNAPSHOT_CHANGED": "Retry from stable committed revisions after concurrent edits finish.",
        "NO_TRACKED_SOURCES": "Review target.paths and commit the intended Python sources; an empty tracked universe cannot establish useful scope coverage.",
        "POLICY_NOT_IN_HEAD": "Review and commit this policy. A PR uses its base revision's policy, so installing it in the PR does not enable protection for that same PR.",
        "HEAD_UNAVAILABLE": "Create the initial reviewed commit, then rerun doctor. No committed policy could be checked.",
    }.get(code, "Review the diagnostic and configuration sources; do not interpret an incomplete analysis as passing enforcement.")


def base_result(operation):
    return {"checkwash_quality_setup_version": 1, "operation": operation, "authority": "advisory_only",
            "state": "needs_attention", "ci_execution_verified": False, "branch_protection_verified": False,
            "tool_versions_verified": False, "targets": [], "diagnostics": [], "next_steps": []}


def add_issue(result, code, message, target_id=None):
    result["diagnostics"].append({"code": code, "message": message, "target_id": target_id, "remediation": advice(code)})


def matching_sources(snapshot, paths, *, tracked=False):
    return sorted(p for p in snapshot.paths if (not tracked or p in snapshot.tracked)
                  and snapshot.modes[p] in {"100644", "100755"} and p.endswith((".py", ".pyi"))
                  and any(p == s or (s.endswith("/") and p.startswith(s)) for s in paths))


def inferred_paths(snapshot, root):
    result = set()
    for path in snapshot.paths:
        if not inside(path, root) or not path.endswith((".py", ".pyi")) or snapshot.modes[path] not in {"100644", "100755"}:
            continue
        relative = posixpath.relpath(path, root)
        if set(relative.split("/")) & TRANSIENT:
            continue
        first, sep, _ = relative.partition("/")
        prefix = "" if root == "." else root + "/"
        result.add(prefix + first + ("/" if sep else ""))
    return sorted(result)


def toml_value(value):
    # JSON escapes are TOML-compatible except UTF-16 surrogate pairs.
    # Emit TOML code-point escapes so Unicode paths also remain terminal-safe.
    text = json.dumps(value, ensure_ascii=False)
    return "".join(("\\u%04x" % ord(c) if ord(c) <= 0xFFFF else "\\U%08x" % ord(c))
                   if ord(c) >= 127 else c for c in text)


def draft(snapshot, *, root=".", tools=None, paths=None, profiles=None):
    result = base_result("init")
    if snapshot.read(POLICY_PATH) is not None:
        raise QualityError("POLICY_INVALID", "A quality policy already exists; use quality doctor or edit it deliberately", kind="error")
    safe_path(root, root=True)
    profiles = available() if profiles is None else profiles
    chosen_tools = sorted(set(TOOLS if tools is None else tools))
    if not chosen_tools or set(chosen_tools) - set(TOOLS):
        raise QualityError("POLICY_INVALID", "Choose coverage, ruff or mypy", kind="error")
    scope = sorted(set(inferred_paths(snapshot, root) if paths is None else paths))
    if not scope:
        raise QualityError("POLICY_INVALID", "No Python source paths found; provide explicit repository-relative --paths", kind="error")
    for path in scope:
        safe_path(path)
        if not inside(path.rstrip("/"), root):
            raise QualityError("POLICY_INVALID", "Draft paths must remain inside the requested root", kind="error")
    targets = []
    for tool in chosen_tools:
        models = sorted((p for p in profiles.values() if p["tool"] == tool), key=lambda p: p["id"])
        if len(models) != 1:
            raise QualityError("UNKNOWN_PROFILE", "Draft generation requires exactly one supported model for " + tool)
        target = Target(tool + "-main", tool, root, "auto", models[0]["id"], scope)
        resolved = Resolved()
        selected = choose(snapshot, target, "worktree", resolved)
        if selected is None:
            if tools is not None:
                add_issue(result, "CONTEXT_UNRESOLVED", "No " + tool + " configuration found at " + root, target.id)
            continue
        targets.append(target)
        result["targets"].append({**asdict(target), "selected_config": selected[0],
                                  "model_version": models[0]["tool_version"], "version_selection": "requires_review",
                                  "source_file_count": len(matching_sources(snapshot, scope)), "sources": resolved.sources})
    if not targets or result["diagnostics"]:
        if not targets:
            add_issue(result, "NO_BASE_TARGETS", "No configured supported tools found at the requested root")
        result["next_steps"] = ["Review the repository root and requested tools; no partial policy draft was produced."]
        return result, 2
    lines = ["# Draft only: review tool versions, target paths and configuration selection.",
             "# Model IDs declare assumptions; tool execution and CI protection were not verified.",
             "# Commit the reviewed policy before expecting it to govern a later PR.",
             'schema_version = 1', 'mode = "report"']
    for target in targets:
        lines.extend(["", "[[targets]]"])
        for key in ("id", "tool", "root", "config", "profile", "paths"):
            lines.append(key + " = " + toml_value(getattr(target, key)))
    text = "\n".join(lines) + "\n"
    load_policy(text.encode())  # The printed draft must satisfy the actual policy parser.
    snapshot.verify()
    result.update(state="draft", policy_toml=text)
    result["next_steps"] = ["Save this output as quality-draft.toml and review it before installing .checkwash/quality.toml.",
                            "Confirm the exact tool versions and intended source paths; then run checkwash quality doctor.",
                            "Keep report mode for initial observation. Enforce requires a separate reviewed base policy and a required CI status."]
    return result, 0


def doctor(snapshot, *, head_policy=None, head_revision=None, today=None):
    result = base_result("doctor")
    policy = snapshot.read(POLICY_PATH)
    mode, targets = load_policy(policy)
    result["mode"] = mode
    result["policy"] = {"path": POLICY_PATH, "present": policy is not None, "head_revision": head_revision,
                        "matches_head": policy is not None and head_revision is not None and policy == head_policy}
    if not targets:
        add_issue(result, "NO_BASE_TARGETS", "No worktree quality policy exists")
        snapshot.verify()
        return result, 2
    # This equal-snapshot probe is only inspected as setup data. It is never
    # emitted as a review verdict or allowed to govern another invocation.
    payload, _ = analyze(snapshot, snapshot, base_label="setup-worktree", head_label="setup-worktree", today=today)
    result["analysis_status"] = payload["analysis_status"]
    by_id = {target.id: target for target in targets}
    for row in payload["targets"]:
        target = by_id[row["id"]]
        count = len(matching_sources(snapshot, target.paths, tracked=True))
        result["targets"].append({**row, "tracked_source_files": count})
        if not count:
            add_issue(result, "NO_TRACKED_SOURCES", "No tracked Python sources match this target", target.id)
    for diagnostic in payload["diagnostics"]:
        add_issue(result, diagnostic["code"], diagnostic["message"], diagnostic["target_id"])
    if head_revision is None:
        add_issue(result, "HEAD_UNAVAILABLE", "No committed HEAD policy could be established")
    elif policy != head_policy:
        add_issue(result, "POLICY_NOT_IN_HEAD", "The working policy is new or differs from HEAD")
    result["state"] = "error" if payload["analysis_status"] == "error" else "needs_attention" if result["diagnostics"] else "configured"
    result["next_steps"] = ["Review any unsupported dimensions without weakening existing checks to silence diagnostics.",
                            "Run checkwash quality BASE...HEAD to review a real change under its base policy.",
                            "Verify CI execution and required branch status separately; doctor does not verify either."]
    snapshot.verify()
    return result, 0 if result["state"] == "configured" else 2


def render(result, format):
    if format == "json":
        return json.dumps(result, sort_keys=True, ensure_ascii=False, indent=2) + "\n"
    if result["operation"] == "init" and result.get("policy_toml"):
        return result["policy_toml"]
    from .report import visible
    lines = [f"Checkwash quality setup | {result['state'].upper()} | advisory only"]
    for target in result["targets"]:
        lines.append(f"{target['id']}: {target.get('status', 'draft')} | {target.get('profile', '')}")
        if "tracked_source_files" in target:
            lines.append(f"  Tracked Python sources: {target['tracked_source_files']}")
    for issue in result["diagnostics"]:
        lines += [issue["code"] + ": " + issue["message"], "  " + issue["remediation"]]
    lines.extend(result["next_steps"])
    lines.append("Tool versions, CI execution and branch protection were not verified.")
    return "\n".join(visible(line) for line in lines) + "\n"

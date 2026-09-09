"""Prepare source evidence, never predictions, for the frozen natural study.

Only the standard library and read-only Git object commands are used. No import
of Checkwash, subject checkout, dependency install or subject execution occurs.
Run corpus collection on hosted CI; unit tests use small synthetic packets.
"""
from __future__ import annotations

import argparse
import base64
from collections import Counter
import csv
import difflib
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import time
import tomllib
import urllib.parse
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ("coverage", "ruff", "mypy")
QUALIFIED_VERSIONS = {"coverage": "7.16.0", "ruff": "0.16.6", "mypy": "2.3.1"}
SHA = re.compile(r"[0-9a-f]{40}\Z")
CONFIG_NAMES = {"pyproject.toml", "ruff.toml", ".ruff.toml", "mypy.ini",
                ".mypy.ini", ".coveragerc", "setup.cfg", "tox.ini",
                "pytest.ini", ".pre-commit-config.yaml", ".pre-commit-config.yml"}
ROOT_CONTEXT = {"uv.lock", "poetry.lock", "pdm.lock", "Pipfile", "Pipfile.lock"}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def dump(path, value):
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    path.write_bytes(raw)
    path.with_suffix(path.suffix + ".sha256").write_text(digest(raw) + "\n", encoding="utf-8")
    return digest(raw)


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def validate_initial(raw, protocol_bytes, prereg):
    require(digest(raw) == prereg["original_manifest_sha256"], "original manifest digest mismatch")
    manifest = json.loads(raw)
    protocol = json.loads(protocol_bytes)
    require(manifest["protocol_sha256"] == digest(protocol_bytes), "original protocol digest mismatch")
    require(manifest["reviewed_count"] == 0 and manifest["evaluation"] == "NOT_RUN", "original state changed")
    groups = {}
    for entry in protocol["repository_candidates"]:
        rows = [r for r in manifest["candidates"] if r["repo"] == entry["repo"]]
        require(len(rows) == protocol["initial_candidates_per_repository"], "original group size mismatch")
        require([r["source_order"] for r in rows] == list(range(len(rows))), "original order mismatch")
        for row in rows:
            require(SHA.fullmatch(row["base"]) and SHA.fullmatch(row["head"]), "invalid commit ID")
            require(row["path"] == entry["path"] and row["label"] == "UNREVIEWED", "original candidate changed")
            for source in row["sources"].values():
                require(source["state"] == "present", "original source missing")
                data = base64.b64decode(source["content_base64"], validate=True)
                require(digest(data) == source["sha256"], "original source digest mismatch")
                blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
                require(blob == source["git_blob"], "original Git blob mismatch")
        groups[entry["repo"]] = rows
    require(sum(map(len, groups.values())) == len(manifest["candidates"]), "unexpected original repository")
    return protocol, groups


def api(endpoint, **params):
    url = "https://api.github.com/" + endpoint + "?" + urllib.parse.urlencode(params)
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "checkwash-natural-review"}
    if os.environ.get("GH_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["GH_TOKEN"]
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as response:
        return json.load(response)


def select_history(pages, initial, desired):
    """Verify the frozen prefix, keeping API order without any content test."""
    selected, omitted, seen = [], [], set()
    for rows in pages:
        for row in rows:
            commit = row["sha"]
            require(SHA.fullmatch(commit) and commit not in seen, "invalid or repeated API commit")
            seen.add(commit)
            parents = row["parents"]
            if len(parents) != 1:
                omitted.append({"sha": commit, "parent_count": len(parents)})
                continue
            require(SHA.fullmatch(parents[0]["sha"]), "invalid parent ID")
            if len(selected) < desired:
                selected.append({"head": commit, "base": parents[0]["sha"]})
    prefix = [{"head": r["head"], "base": r["base"]} for r in initial]
    require(selected[:len(prefix)] == prefix, "history no longer matches frozen original prefix")
    return selected, omitted


def collect_history(repo, path, cutoff, initial, prereg, output):
    pages, exhausted = [], False
    desired = len(initial) + prereg["additional_candidates_per_repository"]
    for page in range(1, prereg["maximum_history_pages_per_repository"] + 1):
        rows = api("repos/" + repo + "/commits", path=path, until=cutoff, per_page=100, page=page)
        require(isinstance(rows, list), "unexpected history response")
        # Store only provenance metadata; commit messages are not instructions or labels.
        pages.append([{"sha": r["sha"], "parents": [{"sha": p["sha"]} for p in r["parents"]]} for r in rows])
        exhausted = len(rows) < 100
        if exhausted or sum(len(r["parents"]) == 1 for p in pages for r in p) >= desired:
            break
    selected, omitted = select_history(pages, initial, desired)
    receipt = {"repo": repo, "path": path, "cutoff": cutoff, "pages": pages,
               "selected_count": len(selected), "desired_count": desired,
               "history_exhausted": exhausted, "page_limit_reached": not exhausted and len(selected) < desired,
               "omitted": omitted}
    dump(output / (repo.replace("/", "--") + ".json"), receipt)
    return selected, receipt


def git(repo_path, *args, timeout=120):
    proc = subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "--no-replace-objects",
                           "-C", str(repo_path), *args], stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, timeout=timeout, check=False)
    if proc.returncode:
        raise RuntimeError("Git object read failed: " + args[0])
    return proc.stdout


def wanted_context(path):
    p = PurePosixPath(path)
    if p.name in CONFIG_NAMES:
        return True
    if len(p.parts) == 1 and p.name in ROOT_CONTEXT:
        return True
    if path.startswith(".github/workflows/") and p.suffix in {".yml", ".yaml"}:
        return True
    return ("requirements" in p.parts or p.name.startswith("requirements")) and p.suffix in {".txt", ".in"}


def object_bytes(repo_path, blob, limit):
    size = int(git(repo_path, "cat-file", "-s", blob))
    if size > limit:
        return None, size
    data = git(repo_path, "cat-file", "blob", blob)
    require(len(data) == size, "Git blob size mismatch")
    return data, size


def read_snapshot(repo_path, sha, limits, blob_cache, object_dir):
    require(SHA.fullmatch(sha), "invalid snapshot ID")
    inventory = git(repo_path, "ls-tree", "-r", "-z", sha)
    rows = []
    for row in inventory.split(b"\0"):
        if row:
            metadata, path_bytes = row.split(b"\t", 1)
            mode, kind, blob = metadata.decode("ascii").split()
            path = path_bytes.decode("utf-8", errors="strict")
            if wanted_context(path):
                rows.append((path, mode, kind, blob))
    # Priority is fixed, never based on tool changes or model output.
    rows.sort(key=lambda r: (r[0] != "pyproject.toml", len(PurePosixPath(r[0]).parts), r[0]))
    sources, total, accepted = {}, 0, 0
    for path, mode, kind, blob in rows:
        record = {"git_blob": blob, "git_mode": mode}
        if kind != "blob" or mode not in {"100644", "100755"}:
            record.update(state="unknown", reason="non-regular-file")
        elif accepted >= limits["files_per_snapshot"]:
            record.update(state="unknown", reason="snapshot-file-limit")
        else:
            if blob not in blob_cache:
                blob_cache[blob] = object_bytes(repo_path, blob, limits["bytes_per_file"])
            data, size = blob_cache[blob]
            record["size"] = size
            if data is None:
                record.update(state="unknown", reason="source-byte-limit")
            elif total + size > limits["total_bytes_per_snapshot"]:
                record.update(state="unknown", reason="snapshot-byte-limit")
            else:
                key = digest(data)
                destination = object_dir / key
                if not destination.exists():
                    destination.write_bytes(data)
                record.update(state="present", sha256=key, object="objects/" + key)
                total += size
                accepted += 1
        sources[path] = record
    return {"commit": sha, "tracked_entries": inventory.count(b"\0"),
            "inventory_sha256": digest(inventory), "sources": sources,
            "closure_status": "UNESTABLISHED", "activation_status": "UNESTABLISHED"}


def flatten(value, prefix=()):
    if isinstance(value, dict):
        result = {}
        for key, child in value.items():
            result.update(flatten(child, (*prefix, key)))
        if not value:
            result[prefix] = value
        return result
    return {prefix: value}


def table_differences(before, after):
    try:
        documents = [tomllib.loads(data.decode("utf-8")) for data in (before, after)]
        require(all(isinstance(d.get("tool", {}), dict) for d in documents), "non-table tool value")
    except (ValueError, UnicodeError):
        return {"state": "unknown", "reason": "unparseable-pyproject", "tools": {}}
    result = {}
    for tool in TOOLS:
        values = [flatten(d.get("tool", {}).get(tool, {})) for d in documents]
        changes = []
        for path in sorted(set(values[0]) | set(values[1])):
            bp, hp = path in values[0], path in values[1]
            b, h = values[0].get(path), values[1].get(path)
            if bp != hp or repr(b) != repr(h):
                changes.append({"key_path": list(path), "base_present": bp, "head_present": hp,
                                "base": b, "head": h})
        result[tool] = changes
    return {"state": "parsed", "tools": result,
            "review_aid": "changed tool tables" if any(result.values()) else "no changed tool tables",
            "human_relevance": "UNREVIEWED", "human_label": "UNREVIEWED"}


def version_evidence(sources, output):
    result = {tool: {"mentions": [], "exact_version_candidates": [],
                     "effective_version": None, "status": "UNESTABLISHED"} for tool in TOOLS}
    for path, source in sources.items():
        if source["state"] != "present":
            continue
        data = (output / source["object"]).read_bytes()
        try:
            content = data.decode("utf-8")
        except UnicodeError:
            continue
        lines = content.splitlines()
        for number, line in enumerate(lines, 1):
            for tool in TOOLS:
                if not re.search(r"(?<![A-Za-z0-9_-])" + tool + r"(?![A-Za-z0-9_-])", line, re.I):
                    continue
                if len(result[tool]["mentions"]) < 80:
                    result[tool]["mentions"].append({"path": path, "line": number, "text": line[:400]})
                match = re.search(r"\b" + tool + r"(?:\[[^\]]+\])?\s*==\s*([0-9]+(?:\.[0-9]+){1,3})(?![0-9A-Za-z.*+_-])", line)
                if match:
                    result[tool]["exact_version_candidates"].append({"version": match[1], "path": path,
                                                                    "line": number, "kind": "requirement-mention"})
        if path.endswith((".toml", ".lock")):
            try:
                doc = tomllib.loads(content)
            except ValueError:
                continue
            for package in doc.get("package", []) if isinstance(doc.get("package"), list) else []:
                if isinstance(package, dict) and package.get("name") in TOOLS and isinstance(package.get("version"), str):
                    result[package["name"]]["exact_version_candidates"].append(
                        {"version": package["version"], "path": path, "kind": "lock-entry"})
        if PurePosixPath(path).name in {".pre-commit-config.yaml", ".pre-commit-config.yml"}:
            current_tool = None
            for number, line in enumerate(lines, 1):
                if re.search(r"\brepo\s*:", line):
                    current_tool = "ruff" if "/ruff-pre-commit" in line else "mypy" if "/mirrors-mypy" in line else None
                match = re.search(r"\brev:\s*['\"]?v?([0-9]+(?:\.[0-9]+){1,3})(?=['\"\s#]|$)", line)
                if current_tool and match:
                    result[current_tool]["exact_version_candidates"].append(
                        {"version": match[1], "path": path, "line": number, "kind": "pre-commit-rev-mention"})
    return result


def source_bytes(snapshot, path, output):
    source = snapshot["sources"].get(path)
    if source and source["state"] == "present":
        return (output / source["object"]).read_bytes()
    return None


def summarize(candidates, histories, errors):
    counts = Counter()
    repos = {}
    for row in candidates:
        group = repos.setdefault(row["repo"], {"candidates": 0, "table_changed_candidates": 0,
                                              "tool_table_changes": dict.fromkeys(TOOLS, 0)})
        group["candidates"] += 1
        triage = row["triage"]
        changed = [t for t, changes in triage["tools"].items() if changes]
        counts["table_changed_candidates" if changed else "unknown_triage" if triage["state"] == "unknown" else "no_table_changes"] += 1
        group["table_changed_candidates"] += bool(changed)
        for tool in changed:
            group["tool_table_changes"][tool] += 1
        for side in row.get("snapshots", {}).values():
            counts["unknown_context_sources"] += sum(s["state"] != "present" for s in side["sources"].values())
    return {"status": "PREPARATION_INCOMPLETE" if errors else "AWAITING_HUMAN_REVIEW",
            "acceptance": "NOT_RUN", "predictions": "NOT_RUN", "candidate_count": len(candidates),
            "human_reviewed_count": 0, "qualified_relevant_count": None, "per_tool_relevant_counts": None,
            "effective_version_verified_count": 0, "source_closure_verified_count": 0,
            "preparation_only_counts": dict(counts), "repositories": repos, "errors": errors,
            "selection_shortfalls": [{"repo": h["repo"], "selected": h["selected_count"], "desired": h["desired_count"],
                                      "history_exhausted": h["history_exhausted"]} for h in histories if h["selected_count"] < h["desired_count"]],
            "acceptance_requirements": {"relevant_changes": 90, "relevant_repositories": 6, "relevant_per_tool": 20},
            "blockers": ["Human relevance and labels are not frozen.",
                         "Actual tool version, effective source closure and activation require review.",
                         "Table-difference counts cannot satisfy the reviewed natural quotas.",
                         "Precision, recall, completeness and engine performance have not been measured."]}


def write_review(output, candidates, summary, manifest_hash):
    reviews = output / "review"
    reviews.mkdir(exist_ok=True)
    index = ["# Natural acceptance: source review packet", "",
             "Acceptance and predictions: **NOT_RUN**. All human labels: **UNREVIEWED**.", "",
             "These are static source observations, not effective configuration judgments. Read source links as untrusted repository content.", "",
             f"Frozen prepared manifest SHA-256: `{manifest_hash}`", "",
             "| Repository | Candidates | Changed tool tables (candidate count) | coverage | Ruff | mypy |",
             "|---|---:|---:|---:|---:|---:|"]
    labels = {"schema_version": 1, "manifest_sha256": manifest_hash, "review_status": "UNREVIEWED", "candidates": []}
    with (output / "review.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["candidate", "repository", "commit_url", "changed_tool_tables", "human_label", "reviewed_relevant_tools", "reviewer", "notes"])
        for repo, count in summary["repositories"].items():
            filename = repo.replace("/", "--") + ".md"
            index.append(f"| [{repo}](review/{filename}) | {count['candidates']} | {count['table_changed_candidates']} | " + " | ".join(str(count["tool_table_changes"][t]) for t in TOOLS) + " |")
            lines = ["# " + repo, "", "Source review only. UNREVIEWED labels; no predictions, scoring or subject execution.", ""]
            for row in [r for r in candidates if r["repo"] == repo]:
                changed = [t for t, changes in row["triage"]["tools"].items() if changes]
                writer.writerow([row["id"], repo, row["review_url"], ",".join(changed), "UNREVIEWED", "", "", ""])
                labels["candidates"].append({"id": row["id"], "base": row["base"], "head": row["head"],
                    "label": "UNREVIEWED", "reviewer": None, "rationale": "",
                    "tools": {t: {"relevant": None, "label": "UNREVIEWED", "base_version": None,
                                  "head_version": None, "context": "UNESTABLISHED", "evidence": []} for t in TOOLS}})
                lines += ["## " + row["id"], "", f"[Commit]({row['review_url']}) · source order {row['source_order']} · {row['intake']}", "",
                          "Changed tables: " + (", ".join(changed) or row["triage"].get("reason", "none")) + ". Human label: **UNREVIEWED**.", ""]
                for tool in changed:
                    lines += ["### " + tool, "", "```json", json.dumps(row["triage"]["tools"][tool], ensure_ascii=False, indent=2, default=str), "```", ""]
                for side, snapshot in row.get("snapshots", {}).items():
                    lines += [f"{side}: `{row[side]}`; effective version / activation / source closure **UNESTABLISHED**.", ""]
                    for tool in changed or TOOLS:
                        pins = row["version_evidence"][side][tool]["exact_version_candidates"]
                        lines.append(f"- {tool} exact version mentions: " + (", ".join(sorted({p["version"] for p in pins})) or "none") + f"; qualified model: {QUALIFIED_VERSIONS[tool]}.")
                        for pin in pins:
                            url = f"https://github.com/{repo}/blob/{row[side]}/{urllib.parse.quote(pin['path'])}"
                            if pin.get("line"):
                                url += "#L" + str(pin["line"])
                            lines.append(f"  - [{pin['path']}]({url}): {pin['version']} ({pin['kind']}; activation unverified)")
                    unavailable = [p + ": " + s["reason"] for p, s in snapshot["sources"].items() if s["state"] != "present"]
                    if unavailable:
                        lines += ["", "Unavailable context: " + "; ".join(unavailable)]
                    lines += [""]
                if changed:
                    before = source_bytes(row["snapshots"]["base"], row["path"], output)
                    after = source_bytes(row["snapshots"]["head"], row["path"], output)
                    if before is not None and after is not None:
                        diff = "\n".join(difflib.unified_diff(before.decode("utf-8", "replace").splitlines(), after.decode("utf-8", "replace").splitlines(), fromfile="base/" + row["path"], tofile="head/" + row["path"], lineterm=""))
                        fence = "`" * max(3, max((len(m[0]) + 1 for m in re.finditer(r"`+", diff)), default=3))
                        lines += ["<details><summary>Raw pyproject diff</summary>", "", fence + "diff", diff, fence, "", "</details>", ""]
            (reviews / filename).write_text("\n".join(lines) + "\n", encoding="utf-8")
    index += ["", "Table changes are screening aids; the six repositories and 90/20 quotas still need human relevance review.", "",
              "Review the per-repository before/after keys and version evidence, then fill review-labels.json. Record an identified reviewer, per-tool relevance/labels, actual version and source/activation evidence. Legitimate weakening is a subtype of weakening, not a second observation.", "",
              "No scores are available until the labels and source hashes are frozen. Missing context remains unknown; version mentions never establish the version that ran upstream."]
    (output / "review.md").write_text("\n".join(index) + "\n", encoding="utf-8")
    dump(output / "review-labels.json", labels)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--initial", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    args = parser.parse_args()
    require(os.environ.get("GITHUB_ACTIONS") == "true", "Corpus preparation runs on hosted CI; use synthetic unit tests locally")
    require(not args.output.exists(), "output must be new; frozen artifacts cannot be overwritten")
    start = time.monotonic()
    prereg_bytes = (ROOT / "docs/quality-evaluation/natural-preparation-v1.json").read_bytes().replace(b"\r\n", b"\n")
    prereg = json.loads(prereg_bytes)
    initial_raw = (args.initial / "candidate-manifest.json").read_bytes()
    protocol_bytes = (args.initial / "protocol.json").read_bytes()
    protocol, groups = validate_initial(initial_raw, protocol_bytes, prereg)
    args.output.mkdir(parents=True)
    for name in ("history", "objects"):
        (args.output / name).mkdir()
    args.cache.mkdir(parents=True, exist_ok=True)
    (args.output / "original-manifest.json").write_bytes(initial_raw)
    (args.output / "protocol.json").write_bytes(protocol_bytes)
    (args.output / "preregistration.json").write_bytes(prereg_bytes)
    candidates, histories, errors = [], [], []
    for entry in protocol["repository_candidates"]:
        repo, path = entry["repo"], entry["path"]
        try:
            rows, receipt = collect_history(repo, path, protocol["cutoff_utc"], groups[repo], prereg, args.output / "history")
            histories.append(receipt)
            repo_path = args.cache / (repo.replace("/", "--") + ".git")
            require(not repo_path.exists(), "bare cache must be new")
            subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "clone", "--bare", "--single-branch",
                            "https://github.com/" + repo + ".git", str(repo_path)], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=900)
            blob_cache, snapshots = {}, {}
            for order, row in enumerate(rows):
                for sha in (row["base"], row["head"]):
                    if sha not in snapshots:
                        snapshots[sha] = read_snapshot(repo_path, sha, prereg["context_limits"], blob_cache, args.output / "objects")
                pair = {side: snapshots[row[side]] for side in ("base", "head")}
                if order < len(groups[repo]):
                    original = groups[repo][order]
                    for side in pair:
                        source = pair[side]["sources"].get(path, {})
                        require(source.get("sha256") == original["sources"][side]["sha256"] and source.get("git_blob") == original["sources"][side]["git_blob"], "frozen source mismatch")
                before, after = (source_bytes(pair[s], path, args.output) for s in ("base", "head"))
                triage = table_differences(before, after) if before is not None and after is not None else {"state": "unknown", "reason": "source-absent-or-unavailable", "tools": {}}
                candidates.append({"id": repo.replace("/", "--") + "-" + row["head"][:12], "repo": repo,
                    "path": path, "source_order": order, **row, "intake": "original" if order < len(groups[repo]) else "replenishment-1",
                    "review_url": "https://github.com/" + repo + "/commit/" + row["head"],
                    "label": "UNREVIEWED", "snapshots": pair, "triage": triage,
                    "version_evidence": {side: version_evidence(snapshot["sources"], args.output) for side, snapshot in pair.items()}})
                if (order + 1) % 25 == 0:
                    print(repo + ": " + str(order + 1) + " source packets prepared; no predictions", flush=True)
            print(repo + ": complete, " + str(len(rows)) + " candidates", flush=True)
        except Exception as error:
            errors.append({"repo": repo, "error_type": type(error).__name__, "message": str(error)[:300]})
            print(repo + ": INCOMPLETE " + type(error).__name__, flush=True)
    summary = summarize(candidates, histories, errors)
    manifest_hash = dump(args.output / "prepared-manifest.json", {"schema_version": 1,
        "original_manifest_sha256": digest(initial_raw), "preregistration_sha256": digest(prereg_bytes),
        "engine_commit": prereg["engine_commit"], "engine_tree": prereg["engine_tree"],
        "collector_commit": os.environ.get("GITHUB_SHA"), "run_id": os.environ.get("GITHUB_RUN_ID"),
        "candidates": candidates, "summary": summary})
    dump(args.output / "summary.json", summary)
    write_review(args.output, candidates, summary, manifest_hash)
    dump(args.output / "preparation-receipt.json", {"collector_commit": os.environ.get("GITHUB_SHA"),
        "run_id": os.environ.get("GITHUB_RUN_ID"), "python": sys.version, "platform": sys.platform,
        "elapsed_seconds": round(time.monotonic() - start, 3), "measurement": "source preparation only; not engine performance",
        "manifest_sha256": manifest_hash, "predictions": "NOT_RUN", "acceptance": "NOT_RUN"})
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    if errors:
        raise SystemExit("Preparation incomplete; errors and partial evidence preserved")


if __name__ == "__main__":
    main()

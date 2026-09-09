"""Public, read-only intake. No Checkwash analysis or external project execution."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import urllib.parse
import urllib.request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    protocol_path = Path(__file__).resolve().parents[1] / "docs/quality-evaluation/protocol.json"
    protocol_bytes = protocol_path.read_bytes().replace(b"\r\n", b"\n")
    protocol = json.loads(protocol_bytes)
    args.output.mkdir(parents=True, exist_ok=True)
    def get(endpoint, **params):
        url = "https://api.github.com/" + endpoint + ("?" + urllib.parse.urlencode(params) if params else "")
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "checkwash-quality-candidate-intake"}
        if os.environ.get("GH_TOKEN"):
            headers["Authorization"] = "Bearer " + os.environ["GH_TOKEN"]
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as response:
            return json.load(response)
    candidates, errors, omitted_merges = [], [], []
    for entry in protocol["repository_candidates"]:
        repo, path = entry["repo"], entry["path"]
        try:
            rows = get("repos/" + repo + "/commits", path=path, until=protocol["cutoff_utc"], per_page=100)
            omitted_merges.extend({"repo": repo, "sha": r["sha"]} for r in rows if len(r["parents"]) > 1)
            selected = [r for r in rows if len(r["parents"]) == 1][:protocol["initial_candidates_per_repository"]]
            assert len(selected) == protocol["initial_candidates_per_repository"], "candidate history shortfall"
            for position, row in enumerate(selected):
                before, after = row["parents"][0]["sha"], row["sha"]
                result = {"id": repo.replace("/", "--") + "-" + after[:12], "repo": repo, "path": path,
                          "source_order": position, "base": before, "head": after,
                          "review_url": "https://github.com/" + repo + "/commit/" + after,
                          "label": "UNREVIEWED", "relevant_tools": None, "tool_versions": None,
                          "context_status": "configuration-only; full closure and activation not established", "sources": {}}
                for side, sha in [("base", before), ("head", after)]:
                    try:
                        content = get("repos/" + repo + "/contents/" + urllib.parse.quote(path, safe="/"), ref=sha)
                        assert content["type"] == "file" and content.get("encoding") == "base64", "unsupported content response"
                        data = base64.b64decode(content["content"])
                        assert len(data) <= 1_000_000, "configuration byte limit"
                        result["sources"][side] = {"state": "present", "git_blob": content["sha"], "sha256": hashlib.sha256(data).hexdigest(), "content_base64": base64.b64encode(data).decode("ascii")}
                    except Exception as error:
                        result["sources"][side] = {"state": "unknown", "error_type": type(error).__name__}
                candidates.append(result)
            print(repo + ": " + str(len(selected)) + " candidate IDs captured; labels unreviewed", flush=True)
        except Exception as error:
            errors.append({"repo": repo, "error_type": type(error).__name__})
    manifest = {"schema_version": 1, "protocol_sha256": hashlib.sha256(protocol_bytes).hexdigest(),
                "source_commit": os.environ.get("GITHUB_SHA"), "candidates": candidates, "errors": errors, "omitted_merges": omitted_merges,
                "candidate_count": len(candidates), "reviewed_count": 0, "qualified_natural_count": None,
                "per_tool_relevant_counts": None, "evaluation": "NOT_RUN"}
    raw = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
    (args.output / "candidate-manifest.json").write_bytes(raw)
    (args.output / "candidate-manifest.sha256").write_text(hashlib.sha256(raw).hexdigest() + "\n", encoding="utf-8")
    (args.output / "protocol.json").write_bytes(protocol_bytes)
    review = ["# Quality natural-change candidate review", "", "Intake only: no predictions or acceptance scores. Review relevance and source context first.", "", "| Candidate | Review | Label | Relevant tools |", "|---|---|---|---|"]
    review += [f"| {r['id']} | [commit]({r['review_url']}) | UNREVIEWED | unknown |" for r in candidates]
    (args.output / "review.md").write_text("\n".join(review) + "\n", encoding="utf-8")
    if errors or any(s["state"] == "unknown" for r in candidates for s in r["sources"].values()):
        raise SystemExit("Intake incomplete; preserved errors and unknown sources in manifest")


if __name__ == "__main__":
    main()

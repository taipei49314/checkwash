"""Post high findings as a GitHub PR review. Action-side only; no engine network."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


def _line(finding: dict) -> int:
    after = finding.get("after") or {}
    before = finding.get("before") or {}
    span = after.get("span") or before.get("span")
    if isinstance(span, list) and span:
        # Character offset is not a line. GitHub requires a line >= 1.
        return 1
    return 1


def comments_from_findings(findings: list[dict]) -> list[dict]:
    comments = []
    for finding in findings:
        if finding.get("allowlisted"):
            continue
        if finding.get("severity") not in ("high", "critical"):
            continue
        body = (
            f"**{finding.get('rule')}** ({finding.get('severity')})\n\n"
            f"{finding.get('message')}\n"
        )
        unit = finding.get("unit")
        if unit:
            body += f"\nunit: `{unit}`"
        comments.append(
            {
                "path": finding.get("path") or "",
                "line": _line(finding),
                "body": body,
            }
        )
    return comments[:32]


def main(path: str) -> int:
    repo = os.environ.get("GH_REPO") or ""
    number = os.environ.get("PR_NUMBER") or ""
    token = os.environ.get("GH_TOKEN") or ""
    if not repo or not number or not token:
        print("comment-pr skipped: GH_REPO / PR_NUMBER / GH_TOKEN missing", file=sys.stderr)
        return 0
    payload = json.loads(open(path, encoding="utf-8").read())
    comments = comments_from_findings(payload.get("findings") or [])
    if not comments:
        print("comment-pr: no high findings to post")
        return 0
    body = {
        "commit_id": "",
        "event": "COMMENT",
        "body": f"checkwash: {len(comments)} high finding(s)",
        "comments": comments[:32],
    }
    # commit_id empty is rejected; omit it so GitHub uses the latest HEAD.
    del body["commit_id"]
    data = json.dumps(body).encode("utf-8")
    url = f"https://api.github.com/repos/{repo}/pulls/{number}/reviews"
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            print(f"comment-pr: posted review ({resp.status})")
            return 0
    except urllib.error.HTTPError as exc:
        print(f"comment-pr soft-fail: HTTP {exc.code} {exc.reason}", file=sys.stderr)
        return 0
    except urllib.error.URLError as exc:
        print(f"comment-pr soft-fail: {exc.reason}", file=sys.stderr)
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))

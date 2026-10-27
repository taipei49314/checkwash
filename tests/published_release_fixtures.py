"""Owned GitHub metadata fixtures backed by temporary Git repositories."""
import base64
from datetime import datetime, timezone
import hashlib
import json
import re


API = "https://api.github.com/repos/taipei49314/checkwash"


def response_row(url, value, *, status=200, headers=(), raw=None):
    raw = json.dumps(value, separators=(",", ":")).encode() if raw is None else raw
    now = datetime.now(timezone.utc).isoformat()
    return dict(url=url, final_url=url, status=status, headers=list(headers), started_at=now, finished_at=now,
                raw_base64=base64.b64encode(raw).decode(), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                truncated=False, error=None)


def release(tag, pin, number=1):
    return dict(id=number, tag_name=tag, url=API + "/releases/" + str(number),
                html_url="https://github.com/taipei49314/checkwash/releases/tag/" + tag,
                draft=False, prerelease=False, published_at="2026-10-01T00:00:00Z",
                assets=[dict(id=number + 1000, name="checkwash.pyz", state="uploaded", size=pin["size"],
                             digest="sha256:" + pin["sha256"], download_count=0,
                             browser_download_url="https://github.com/taipei49314/checkwash/releases/download/"
                             + tag + "/checkwash.pyz")])


def native_fetch(vg, repo, pin, *, releases=None):
    if releases is None:
        tags = vg._git_text(repo, "tag", "--list", "v*").split()
        releases = [release(tag, pin, index) for index, tag in enumerate(tags, 1)]
    def fetch(url):
        if url == API + "/releases?per_page=100&page=1":
            return response_row(url, releases)
        if url.startswith(API + "/git/ref/tags/"):
            tag = url.rsplit("/", 1)[1]
            oid = vg._git_text(repo, "rev-parse", "refs/tags/" + tag)
            kind = vg._git_text(repo, "cat-file", "-t", oid)
            return response_row(url, dict(ref="refs/tags/" + tag, object=dict(type=kind, sha=oid)))
        if url.startswith(API + "/git/tags/"):
            oid = url.rsplit("/", 1)[1]
            lines = vg._git_text(repo, "cat-file", "-p", oid).splitlines()
            obj = dict(line.split(" ", 1) for line in lines[:2])
            return response_row(url, dict(sha=oid, object=dict(type=obj["type"], sha=obj["object"])))
        match = re.fullmatch(re.escape(API) + r"/compare/([0-9a-f]{40})\.\.\.([0-9a-f]{40})\?per_page=1&page=1", url)
        if match:
            base, head = match.groups()
            merge = vg._git_text(repo, "merge-base", base, head)
            status = "identical" if base == head else "ahead" if merge == base else "behind" if merge == head else "diverged"
            return response_row(url, dict(base_commit={"sha": base}, merge_base_commit={"sha": merge}, status=status))
        raise AssertionError("unexpected owned native endpoint: " + url)
    return fetch

"""Bound public release metadata for the previous-release tag gate.

This is metadata acquisition and validation, never product execution. A bare
tag or the absence of a public Release does not prove publication history, nor
does an anonymous response establish whether a private draft exists. The native
publisher refreshes this evidence independently before relying on it.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import http.client
import json
import re
import urllib.error
import urllib.parse
import urllib.request


REPOSITORY = "taipei49314/checkwash"
REPOSITORY_ID = 1320152564
API = "https://api.github.com/repos/" + REPOSITORY
PAGE_SIZE = 100
MAX_PAGES = 10
MAX_RESPONSE = 8 * 1024 * 1024
MAX_TOTAL = 16 * 1024 * 1024
MAX_TAGS = 50
MAX_PEELS = 5
SEMVER = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")
SHA = re.compile(r"[0-9a-f]{40}\Z")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


class EvidenceError(ValueError):
    def __init__(self, message, evidence=None):
        super().__init__(message)
        self.evidence = evidence


def require(condition, message):
    if not condition:
        raise EvidenceError(message)


def utc(value):
    require(type(value) is str, "metadata timestamp absent")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise EvidenceError("invalid metadata timestamp") from None
    require(result.tzinfo is not None and result.utcoffset().total_seconds() == 0,
            "metadata timestamp must be UTC")
    return result


def strict_json(raw):
    def pairs(rows):
        result = {}
        for key, value in rows:
            require(key not in result, "duplicate release JSON key")
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=lambda value: (_ for _ in ()).throw(EvidenceError("nonfinite release JSON")))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise EvidenceError("invalid release JSON: " + str(error)) from None


def page_url(page):
    return API + "/releases?per_page=100&page=" + str(page)


def allowed_url(url):
    require(type(url) is str, "native API URL absent")
    parsed = urllib.parse.urlsplit(url)
    require(parsed.scheme == "https" and parsed.netloc == "api.github.com"
            and parsed.username is None and parsed.password is None and not parsed.fragment,
            "unexpected native API origin")
    require(re.fullmatch(re.escape(API) + r"/releases\?per_page=100&page=[1-9][0-9]*", url)
            or re.fullmatch(re.escape(API) + r"/git/ref/tags/v[0-9]+\.[0-9]+\.[0-9]+", url)
            or re.fullmatch(re.escape(API) + r"/git/tags/[0-9a-f]{40}", url)
            or re.fullmatch(re.escape(API) + r"/compare/[0-9a-f]{40}\.\.\.[0-9a-f]{40}\?per_page=1&page=1", url),
            "unexpected publication metadata endpoint")


def request(url, *, token=None):
    """Retain original bounded bytes and HTTP failures; never follow redirects."""
    allowed_url(url)
    row = dict(url=url, final_url=None, status=None, headers=[],
               started_at=datetime.now(timezone.utc).isoformat(), finished_at=None,
               raw_base64="", bytes=0, sha256=hashlib.sha256(b"").hexdigest(),
               truncated=False, error=None)
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
               "User-Agent": "checkwash-published-release-identity"}
    if token is not None:
        require(type(token) is str and bool(token), "native metadata token absent")
        headers["Authorization"] = "Bearer " + token
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    raw = b""
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect)
        try:
            response = opener.open(urllib.request.Request(url, headers=headers), timeout=30)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            row.update(status=response.status, final_url=response.geturl(), headers=list(response.headers.items()))
            raw = response.read(MAX_RESPONSE + 1)
            row["truncated"] = len(raw) > MAX_RESPONSE
    except (OSError, urllib.error.URLError, http.client.HTTPException) as error:
        if isinstance(error, http.client.IncompleteRead):
            raw = error.partial[:MAX_RESPONSE + 1]
            row["truncated"] = True
        row["error"] = type(error).__name__ + ": " + str(error)
    finally:
        row.update(finished_at=datetime.now(timezone.utc).isoformat(), bytes=len(raw),
                   sha256=hashlib.sha256(raw).hexdigest(), raw_base64=base64.b64encode(raw).decode("ascii"))
    return row


def response(row, expected):
    require(type(row) is dict and set(row) == set("url final_url status headers started_at finished_at raw_base64 bytes sha256 truncated error".split()),
            "publication response fields differ")
    allowed_url(expected)
    require(row["url"] == row["final_url"] == expected and type(row["status"]) is int
            and row["status"] == 200 and row["error"] is None and row["truncated"] is False,
            "native publication response failed/redirected/partial")
    require(utc(row["finished_at"]) >= utc(row["started_at"]), "metadata response timing differs")
    require(type(row["raw_base64"]) is str, "raw native bytes absent")
    try:
        raw = base64.b64decode(row["raw_base64"], validate=True)
    except (ValueError, TypeError):
        raise EvidenceError("invalid raw native encoding") from None
    require(type(row["bytes"]) is int and row["bytes"] == len(raw) <= MAX_RESPONSE
            and row["sha256"] == hashlib.sha256(raw).hexdigest(), "native response byte binding differs")
    require(type(row["headers"]) is list and all(type(item) in (list, tuple) and len(item) == 2
            and all(type(part) is str for part in item) for item in row["headers"]), "native headers absent")
    lengths = [value for name, value in row["headers"] if name.lower() == "content-length"]
    require(len(lengths) <= 1 and (not lengths or re.fullmatch(r"0|[1-9][0-9]*", lengths[0])
            and int(lengths[0]) == len(raw)), "native HTTP body is incomplete/length differs")
    return strict_json(raw)


def next_page(row, page):
    values = [value for name, value in row["headers"] if name.lower() == "link"]
    require(len(values) <= 1, "duplicate pagination Link")
    if not values:
        return None
    links = {}
    for part in values[0].split(","):
        match = re.fullmatch(r'\s*<([^<>]+)>;\s*rel="(next|prev|first|last)"\s*', part)
        require(match is not None and match[2] not in links, "unknown/malformed pagination Link")
        url, relation = match.groups()
        # GitHub emits its immutable repository-ID alias in real Link headers.
        # Bind only this audited ID/name pair; requests still use page_url().
        aliases = (API, "https://api.github.com/repositories/" + str(REPOSITORY_ID))
        require(any(re.fullmatch(re.escape(alias) + r"/releases\?per_page=100&page=[1-9][0-9]*", url)
                    for alias in aliases),
                "noncanonical pagination URL")
        number = int(url.rsplit("=", 1)[1])
        require((relation != "next" or number == page + 1)
                and (relation != "prev" or number == page - 1)
                and (relation != "first" or number == 1)
                and (relation != "last" or number >= page), "pagination order differs")
        links[relation] = number
    if "last" in links and links["last"] > page:
        require("next" in links, "pagination ends before its last page")
    return links.get("next")


def release_projection(value):
    require(type(value) is dict and type(value.get("id")) is int and value["id"] > 0
            and type(value.get("tag_name")) is str and type(value.get("draft")) is bool
            and type(value.get("prerelease")) is bool and type(value.get("assets")) is list,
            "release identity fields differ")
    require(value.get("url") == API + "/releases/" + str(value["id"])
            and (value["draft"] or value.get("html_url") == "https://github.com/" + REPOSITORY + "/releases/tag/" + value["tag_name"]),
            "release repository/native URL differs")
    fields = "id name state size digest browser_download_url".split()
    require(all(type(asset) is dict for asset in value["assets"]), "release asset object absent")
    return {**{key: value.get(key) for key in ("id", "tag_name", "draft", "prerelease", "published_at")},
            "assets": [{key: asset.get(key) for key in fields} for asset in value["assets"]]}


def catalog(pages):
    require(type(pages) is list and 0 < len(pages) <= MAX_PAGES, "catalog page coverage absent/capped")
    releases, ids, tags = [], set(), set()
    for page, row in enumerate(pages, 1):
        values = response(row, page_url(page))
        require(type(values) is list and len(values) <= PAGE_SIZE, "release catalog page shape differs")
        following = next_page(row, page)
        require((following == page + 1) == (page < len(pages)), "incomplete/extra catalog pages")
        require(following is None or len(values) == PAGE_SIZE, "partial intermediate catalog page")
        for value in values:
            projection = release_projection(value)
            require(projection["id"] not in ids and projection["tag_name"] not in tags,
                    "duplicate/drifting release catalog")
            ids.add(projection["id"])
            tags.add(projection["tag_name"])
            releases.append(projection)
    return releases


def semver(tag):
    match = SEMVER.fullmatch(tag) if type(tag) is str else None
    return tuple(int(part) for part in match.groups()) if match else None


def relevant_releases(releases, pin, pushed):
    found = {}
    for value in releases:
        tag = value["tag_name"]
        version = semver(tag)
        if version is None or tag == pushed or version < semver(pin["tag"]) or value["draft"]:
            continue
        require(value["prerelease"] is False, "stable-name release carries prerelease flag")
        utc(value["published_at"])
        found[tag] = value
    require(pin["tag"] in found, "pinned baseline has no public published stable Release")
    return dict(sorted(found.items()))


def tag_identity(tag, rows):
    require(type(rows) is list and 0 < len(rows) <= MAX_PEELS + 1, "native tag coverage absent/capped")
    url = API + "/git/ref/tags/" + tag
    value = response(rows[0], url)
    require(type(value) is dict and value.get("ref") == "refs/tags/" + tag,
            "native tag ref differs")
    obj = value.get("object")
    initial = None
    visited = set()
    index = 1
    while True:
        require(type(obj) is dict and obj.get("type") in ("tag", "commit")
                and type(obj.get("sha")) is str and SHA.fullmatch(obj["sha"]), "native tag object differs")
        oid = obj["sha"]
        require(oid not in visited, "native tag peel cycle")
        visited.add(oid)
        if initial is None:
            initial = oid
        if obj["type"] == "commit":
            require(index == len(rows), "extra native tag peel evidence")
            return dict(tag_object=initial, commit=oid)
        require(index < len(rows), "native tag peel is incomplete")
        value = response(rows[index], API + "/git/tags/" + oid)
        require(type(value) is dict and value.get("sha") == oid, "native annotated tag differs")
        obj = value.get("object")
        index += 1


def relevant_tags(releases, pin, pushed, merged_tags):
    return set(releases) | {pushed} | {tag for tag in merged_tags if semver(tag) is not None
        and semver(tag) >= semver(pin["tag"])}


def ancestry_url(base, head):
    return API + "/compare/" + base + "..." + head + "?per_page=1&page=1"


def ancestry(row, base, head):
    value = response(row, ancestry_url(base, head))
    require(type(value) is dict and type(value.get("base_commit")) is dict
            and value["base_commit"].get("sha") == base
            and type(value.get("merge_base_commit")) is dict
            and type(value["merge_base_commit"].get("sha")) is str
            and SHA.fullmatch(value["merge_base_commit"]["sha"])
            and value.get("status") in ("ahead", "behind", "diverged", "identical"),
            "native comparison identity/status differs")
    merged = value["merge_base_commit"]["sha"] == base
    require(merged == (value["status"] in ("ahead", "identical"))
            and ((base == head) == (value["status"] == "identical")), "native ancestry/status contradict")
    return dict(commit=base, head=head, merge_base=value["merge_base_commit"]["sha"],
                status=value["status"], merged=merged)


def validate(evidence, pin, pushed, *, merged_tags=()):
    require(type(evidence) is dict and set(evidence) == set("schema_version kind repository started_at finished_at catalog_passes tags ancestry".split())
            and type(evidence["schema_version"]) is int and evidence["schema_version"] == 1
            and evidence["kind"] == "checkwash.published-release-identity.v1" and evidence["repository"] == REPOSITORY,
            "publication evidence schema differs")
    require(utc(evidence["finished_at"]) >= utc(evidence["started_at"]), "publication evidence timing differs")
    require(type(evidence["catalog_passes"]) is list and len(evidence["catalog_passes"]) == 2,
            "publication catalog closure pass absent")
    first, closed = (catalog(pages) for pages in evidence["catalog_passes"])
    require(first == closed, "publication catalog changed during closure")
    releases = relevant_releases(closed, pin, pushed)
    require(all(utc(value["published_at"]) <= utc(evidence["finished_at"]) for value in releases.values()),
            "Release publication timestamp is after its captured evidence")
    tags = evidence["tags"]
    require(type(tags) is dict and set(tags) == relevant_tags(releases, pin, pushed, merged_tags)
            and len(tags) <= MAX_TAGS, "native relevant tag coverage differs")
    identities = {tag: tag_identity(tag, rows) for tag, rows in sorted(tags.items())}
    comparisons = evidence["ancestry"]
    require(type(comparisons) is dict and set(comparisons) == set(tags) - {pushed}, "native ancestry coverage differs")
    head = identities[pushed]["commit"]
    ancestors = {tag: ancestry(row, identities[tag]["commit"], head) for tag, row in sorted(comparisons.items())}
    rows = [row for pages in evidence["catalog_passes"] for row in pages]
    rows += [row for tag in sorted(tags) for row in tags[tag]]
    rows += [comparisons[tag] for tag in sorted(comparisons)]
    require(sum(row["bytes"] for row in rows) <= MAX_TOTAL, "publication evidence exceeds total bound")
    previous = utc(evidence["started_at"])
    for row in rows:
        require(utc(row["started_at"]) >= previous and utc(row["finished_at"]) <= utc(evidence["finished_at"]),
                "publication read chronology differs")
        previous = utc(row["finished_at"])
    return dict(releases=releases, identities=identities, ancestry=ancestors)


def pyz_asset(release, pin=None):
    rows = [row for row in release["assets"] if row["name"] == "checkwash.pyz"]
    require(len(rows) == 1, "published Release pyz is absent/duplicated")
    asset = rows[0]
    require(type(asset["id"]) is int and asset["id"] > 0 and asset["state"] == "uploaded"
            and type(asset["size"]) is int and 0 < asset["size"] <= 256 * 1024 * 1024
            and type(asset["digest"]) is str and DIGEST.fullmatch(asset["digest"])
            and asset["browser_download_url"] == "https://github.com/" + REPOSITORY + "/releases/download/"
            + release["tag_name"] + "/checkwash.pyz", "published pyz identity is invalid/incomplete")
    if pin is not None:
        require(asset["size"] == pin["size"] and asset["digest"] == "sha256:" + pin["sha256"],
                "published baseline pyz differs from pin")
    return asset


def capture(pin, pushed, *, merged_tags=(), fetch=None):
    fetch = request if fetch is None else fetch
    evidence = dict(schema_version=1, kind="checkwash.published-release-identity.v1", repository=REPOSITORY,
                    started_at=datetime.now(timezone.utc).isoformat(), finished_at=None, catalog_passes=[], tags={}, ancestry={})
    total = 0
    def read(url, target):
        nonlocal total
        row = fetch(url)
        target.append(row)
        value = response(row, url)
        total += row["bytes"]
        require(total <= MAX_TOTAL, "publication evidence exceeds total bound")
        return value
    try:
        for _ in range(2):
            pages = []
            evidence["catalog_passes"].append(pages)
            for page in range(1, MAX_PAGES + 1):
                read(page_url(page), pages)
                if next_page(pages[-1], page) is None:
                    break
            else:
                raise EvidenceError("catalog pagination reached its cap without closure")
            catalog(pages)
        first, closed = (catalog(pages) for pages in evidence["catalog_passes"])
        require(first == closed, "publication catalog changed during closure")
        releases = relevant_releases(closed, pin, pushed)
        wanted = sorted(relevant_tags(releases, pin, pushed, merged_tags))
        require(len(wanted) <= MAX_TAGS, "too many relevant publication tags")
        for tag in wanted:
            rows = []
            evidence["tags"][tag] = rows
            value = read(API + "/git/ref/tags/" + tag, rows)
            for depth in range(MAX_PEELS + 1):
                obj = value.get("object") if type(value) is dict else None
                require(type(obj) is dict and obj.get("type") in ("tag", "commit")
                        and type(obj.get("sha")) is str and SHA.fullmatch(obj["sha"]), "native tag object differs")
                if obj["type"] == "commit":
                    break
                require(depth < MAX_PEELS, "native tag peel reached its cap")
                value = read(API + "/git/tags/" + obj["sha"], rows)
            else:
                raise EvidenceError("native tag peel reached its cap")
            tag_identity(tag, rows)
        identities = {tag: tag_identity(tag, rows) for tag, rows in evidence["tags"].items()}
        for tag in sorted(set(wanted) - {pushed}):
            rows = []
            try:
                read(ancestry_url(identities[tag]["commit"], identities[pushed]["commit"]), rows)
            finally:
                if rows:
                    evidence["ancestry"][tag] = rows[0]
        evidence["finished_at"] = datetime.now(timezone.utc).isoformat()
        validate(evidence, pin, pushed, merged_tags=merged_tags)
        return evidence
    except (EvidenceError, OSError, ValueError, urllib.error.URLError) as error:
        evidence["finished_at"] = datetime.now(timezone.utc).isoformat()
        raise EvidenceError(str(error), evidence) from None

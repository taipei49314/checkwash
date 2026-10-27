"""Published baseline identity on owned Git/native-metadata fixtures only."""
import copy
import base64
from datetime import timedelta
import importlib.util
from pathlib import Path
import urllib.error

import pytest

from published_release_fixtures import API, native_fetch, release, response_row


ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location("published_baseline_owned_" + name, ROOT / "tools" / (name + ".py"))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


VG = load("verdict_gate")
P = VG._PUBLICATION
R = load("pju_release_bridge")


@pytest.fixture
def owned(tmp_path):
    repo = tmp_path / "owned repo"
    repo.mkdir()
    VG._git(repo, "init", "-q", "-b", "main")
    commits = {}
    for tag in ("v0.9.0", "v0.9.1", "v0.10.0"):
        (repo / "VERSION").write_text(tag + "\n", encoding="utf-8")
        VG._git(repo, "add", "--all")
        VG._git(repo, "commit", "-q", "-m", tag)
        VG._git(repo, "tag", "-a", tag, "-m", "owned " + tag)
        commits[tag] = VG._git_text(repo, "rev-parse", "HEAD")
    pin = dict(tag="v0.9.0", version="0.9.0", commit=commits["v0.9.0"], size=914407, sha256="a" * 64)
    return repo, pin, commits


def snapshot(owned, *, releases=None, fetch=None):
    repo, pin, _ = owned
    releases = [release(pin["tag"], pin)] if releases is None else releases
    fetch = native_fetch(VG, repo, pin, releases=releases) if fetch is None else fetch
    merged = VG._git_text(repo, "tag", "--merged", "HEAD", "--list", "v*").split()
    return P.capture(pin, "v0.10.0", merged_tags=merged, fetch=fetch)


def check(owned, evidence):
    return VG.check_tag_rule(owned[0], "v0.10.0", owned[1], publication=evidence)


def execution(evidence):
    return dict(started_at=(P.utc(evidence["started_at"]) - timedelta(seconds=1)).isoformat(),
                finished_at=(P.utc(evidence["finished_at"]) + timedelta(seconds=1)).isoformat())


class Native:
    def __init__(self, fetch):
        self.fetch, self.reads = fetch, []

    def publication_response(self, url):
        self.reads.append(url)
        return self.fetch(url)


def test_real_published_baseline_plus_retained_orphan_tag_passes(owned):
    before = VG._git_text(owned[0], "show-ref", "--tags")
    evidence = snapshot(owned)
    errors, info = check(owned, evidence)
    assert errors == []
    assert info["highest_other"] == "v0.9.0"
    assert info["unpublished_merged_tags"] == ["v0.9.1"]
    assert len(evidence["catalog_passes"]) == 2
    assert set(evidence["tags"]) == {"v0.9.0", "v0.9.1", "v0.10.0"}
    assert set(evidence["ancestry"]) == {"v0.9.0", "v0.9.1"}
    assert VG._git_text(owned[0], "show-ref", "--tags") == before


@pytest.mark.parametrize("asset_problem", [None, "missing", "duplicate", "bad-digest", "wrong-origin", "not-uploaded"])
def test_v091_if_truly_published_can_never_be_excluded_to_pass_v090(owned, asset_problem):
    pin = owned[1]
    higher = release("v0.9.1", pin, 2)
    if asset_problem == "missing":
        higher["assets"] = []
    elif asset_problem == "duplicate":
        higher["assets"] *= 2
    elif asset_problem == "bad-digest":
        higher["assets"][0]["digest"] = None
    elif asset_problem == "wrong-origin":
        higher["assets"][0]["browser_download_url"] = "https://example.invalid/checkwash.pyz"
    elif asset_problem == "not-uploaded":
        higher["assets"][0]["state"] = "new"
    errors, info = check(owned, snapshot(owned, releases=[release(pin["tag"], pin), higher]))
    assert info["highest_other"] == "v0.9.1"
    assert any("not the highest other published" in error for error in errors)
    assert "v0.9.1" not in info["unpublished_merged_tags"]
    if asset_problem:
        assert any("published Release v0.9.1:" in error for error in errors)


@pytest.mark.parametrize("mutation", ["missing", "digest", "size", "url", "draft", "prerelease", "date", "future-date", "repository"])
def test_baseline_publication_must_be_real_and_match_unchanged_pin(owned, mutation):
    baseline = release("v0.9.0", owned[1])
    releases = [baseline]
    if mutation == "missing":
        releases = []
    elif mutation in ("digest", "size", "url"):
        field, value = {"digest": ("digest", "sha256:" + "b" * 64), "size": ("size", 1),
                        "url": ("browser_download_url", "https://example.invalid/pyz")}[mutation]
        baseline["assets"][0][field] = value
    elif mutation in ("draft", "prerelease"):
        baseline[mutation] = True
    elif mutation == "date":
        baseline["published_at"] = None
    elif mutation == "future-date":
        baseline["published_at"] = "2999-01-01T00:00:00Z"
    else:
        baseline["url"] = "https://api.github.com/repos/attacker/other/releases/1"
    try:
        evidence = snapshot(owned, releases=releases)
    except P.EvidenceError as error:
        assert error.evidence["catalog_passes"]
    else:
        assert check(owned, evidence)[0]


def test_current_release_is_excluded_without_requiring_its_future_assets(owned):
    pin = owned[1]
    current = release("v0.10.0", pin, 3)
    current["assets"] = []
    errors, info = check(owned, snapshot(owned, releases=[release(pin["tag"], pin), current]))
    assert errors == [] and info["highest_other"] == pin["tag"]


def test_private_draft_is_not_claimed_published_but_stable_prerelease_is_an_explicit_refusal(owned):
    pin = owned[1]
    draft = release("v0.9.1", pin, 2)
    draft["draft"] = True
    draft["published_at"] = None
    assert check(owned, snapshot(owned, releases=[release(pin["tag"], pin), draft]))[0] == []
    draft.update(draft=False, prerelease=True, published_at="2026-10-02T00:00:00Z")
    with pytest.raises(P.EvidenceError, match="prerelease flag"):
        snapshot(owned, releases=[release(pin["tag"], pin), draft])


@pytest.mark.parametrize("status", [302, 403, 404, 429, 500, 503])
def test_http_failure_is_retained_and_never_means_no_release(owned, status):
    def fetch(url):
        return response_row(url, {"message": "owned failure"}, status=status)
    with pytest.raises(P.EvidenceError) as caught:
        snapshot(owned, fetch=fetch)
    row = caught.value.evidence["catalog_passes"][0][0]
    assert row["status"] == status and row["bytes"] > 0
    assert caught.value.evidence["finished_at"] is not None


@pytest.mark.parametrize("change", ["timeout", "truncated", "redirect", "hash", "content-length", "duplicate-link", "foreign-link", "foreign-repository-id", "unknown-link", "skipped-page"])
def test_partial_or_unbound_metadata_never_becomes_catalog_absence(owned, change):
    def fetch(url):
        row = response_row(url, [])
        if change == "timeout":
            row.update(status=None, error="TimeoutError: owned timeout")
        elif change == "truncated":
            row["truncated"] = True
        elif change == "redirect":
            row["final_url"] = "https://attacker.invalid/releases"
        elif change == "hash":
            row["sha256"] = "f" * 64
        elif change == "content-length":
            row["headers"] = [("Content-Length", str(row["bytes"] + 1))]
        else:
            links = {"duplicate-link": [("Link", ""), ("link", "")],
                     "foreign-link": [("Link", '<https://attacker.invalid/releases?page=2>; rel="next"')],
                     "foreign-repository-id": [("Link", '<https://api.github.com/repositories/1/releases?per_page=100&page=2>; rel="next"')],
                     "unknown-link": [("Link", '<' + P.page_url(2) + '>; rel="mystery"')],
                     "skipped-page": [("Link", '<' + P.page_url(3) + '>; rel="next"')]}
            row["headers"] = links[change]
        return row
    with pytest.raises(P.EvidenceError) as caught:
        snapshot(owned, fetch=fetch)
    assert caught.value.evidence["catalog_passes"][0]


def paginated(owned, *, duplicate=False, drift=False):
    pin = owned[1]
    low = [release("v0.1." + str(index), pin, index + 10) for index in range(100)]
    baseline = release("v0.9.0", pin, 110 if not duplicate else 10)
    native = native_fetch(VG, owned[0], pin)
    calls = []
    def fetch(url):
        calls.append(url)
        if url == P.page_url(1):
            values = copy.deepcopy(low)
            if drift and calls.count(url) > 1:
                values[0]["tag_name"] = "v0.1.1000"
                values[0]["html_url"] = "https://github.com/taipei49314/checkwash/releases/tag/v0.1.1000"
            return response_row(url, values, headers=[("Link", '<' + P.page_url(2) + '>; rel="next", <' + P.page_url(2) + '>; rel="last"')])
        if url == P.page_url(2):
            return response_row(url, [baseline], headers=[("Link", '<' + P.page_url(1) + '>; rel="prev", <' + P.page_url(1) + '>; rel="first"')])
        return native(url)
    return fetch, calls


def test_pagination_retains_both_complete_original_passes(owned):
    fetch, calls = paginated(owned)
    evidence = snapshot(owned, fetch=fetch)
    assert [len(pages) for pages in evidence["catalog_passes"]] == [2, 2]
    assert calls[:4] == [P.page_url(1), P.page_url(2)] * 2
    assert check(owned, evidence)[0] == []


def test_actual_github_numeric_repository_link_alias_is_bound_but_not_followed(owned):
    fetch, calls = paginated(owned)
    def alias(url):
        row = fetch(url)
        row["headers"] = [(name, value.replace(API, "https://api.github.com/repositories/" + str(P.REPOSITORY_ID)))
                          for name, value in row["headers"]]
        return row
    evidence = snapshot(owned, fetch=alias)
    assert check(owned, evidence)[0] == []
    assert all(url.startswith(API) for url in calls)


@pytest.mark.parametrize("problem", ["duplicate", "drift", "cap"])
def test_pagination_cannot_claim_completion_after_a_partial_or_drifting_snapshot(owned, monkeypatch, problem):
    fetch, _ = paginated(owned, duplicate=problem == "duplicate", drift=problem == "drift")
    if problem == "cap":
        monkeypatch.setattr(P, "MAX_PAGES", 1)
    with pytest.raises(P.EvidenceError) as caught:
        snapshot(owned, fetch=fetch)
    assert caught.value.evidence["catalog_passes"]


@pytest.mark.parametrize("bound", ["MAX_RESPONSE", "MAX_TOTAL", "MAX_TAGS"])
def test_each_metadata_resource_bound_fails_without_discarding_original_reads(owned, monkeypatch, bound):
    monkeypatch.setattr(P, bound, 1)
    with pytest.raises(P.EvidenceError) as caught:
        snapshot(owned)
    assert caught.value.evidence["catalog_passes"][0]


def test_duplicate_json_keys_and_missing_closure_are_rejected(owned):
    def fetch(url):
        return response_row(url, None, raw=b'[{"id":1,"id":2}]')
    with pytest.raises(P.EvidenceError, match="duplicate release JSON key"):
        snapshot(owned, fetch=fetch)
    proof = snapshot(owned)
    proof["catalog_passes"].pop()
    assert check(owned, proof)[0]


def test_malformed_native_ancestry_is_retained_as_failed_metadata(owned):
    original = native_fetch(VG, owned[0], owned[1], releases=[release("v0.9.0", owned[1])])
    def fetch(url):
        return response_row(url, {"base_commit": None}) if "/compare/" in url else original(url)
    with pytest.raises(P.EvidenceError, match="native comparison") as caught:
        snapshot(owned, fetch=fetch)
    assert caught.value.evidence["ancestry"]


@pytest.mark.parametrize("problem", ["ref", "peel", "ancestry"])
def test_native_ref_peel_and_ancestry_are_bound_to_local_git(owned, problem):
    fetch = native_fetch(VG, owned[0], owned[1], releases=[release("v0.9.0", owned[1])])
    def altered(url):
        row = fetch(url)
        if (problem == "ref" and url.endswith("/git/ref/tags/v0.9.0")):
            return response_row(url, dict(ref="refs/tags/v0.9.0", object=dict(type="commit", sha=owned[2]["v0.9.1"])))
        baseline_object = VG._git_text(owned[0], "rev-parse", "refs/tags/v0.9.0")
        if problem == "peel" and url == API + "/git/tags/" + baseline_object:
            value = P.strict_json(base64.b64decode(row["raw_base64"]))
            value["object"]["sha"] = owned[2]["v0.9.1"]
            return response_row(url, value)
        if problem == "ancestry" and "/compare/" in url:
            value = P.strict_json(base64.b64decode(row["raw_base64"]))
            value.update(status="diverged", merge_base_commit={"sha": "c" * 40})
            return response_row(url, value)
        return row
    evidence = snapshot(owned, fetch=altered)
    assert check(owned, evidence)[0]


def test_higher_unmerged_release_requires_native_ancestry_and_cannot_hide_a_missing_ref(owned):
    repo, pin, commits = owned
    VG._git(repo, "checkout", "-q", "-b", "side", commits[pin["tag"]])
    (repo / "SIDE").write_text("owned side\n", encoding="utf-8")
    VG._git(repo, "add", "--all")
    VG._git(repo, "commit", "-q", "-m", "side")
    VG._git(repo, "tag", "-a", "v0.11.0", "-m", "owned unrelated branch")
    VG._git(repo, "checkout", "-q", "main")
    evidence = snapshot(owned, releases=[release(pin["tag"], pin), release("v0.11.0", pin, 2)])
    errors, info = check(owned, evidence)
    assert errors == [] and info["published_unmerged_tags"] == ["v0.11.0"]
    VG._git(repo, "tag", "-d", "v0.11.0")
    assert any("published baseline identity:" in message for message in check(owned, evidence)[0])


def test_native_publisher_rejects_a_forged_or_stale_higher_release_omission(owned):
    evidence = snapshot(owned)
    value = check(owned, evidence)[1]
    api = Native(native_fetch(VG, owned[0], owned[1], releases=[release("v0.9.0", owned[1]), release("v0.9.1", owned[1], 2)]))
    with pytest.raises(P.EvidenceError, match="current native published baseline identity failed") as caught:
        R.validate_published_baseline(VG, owned[0], "v0.10.0", owned[1], value, api, execution(evidence))
    assert api.reads and caught.value.evidence["catalog_passes"]


def test_forged_raw_catalog_cannot_replace_the_native_publishers_own_read(owned):
    pin = owned[1]
    releases = [release("v0.9.0", pin), release("v0.9.1", pin, 2)]
    forged = snapshot(owned, releases=releases)
    for pages in forged["catalog_passes"]:
        old = pages[0]
        replacement = response_row(old["url"], [releases[0]], headers=old["headers"])
        replacement.update(started_at=old["started_at"], finished_at=old["finished_at"])
        pages[0] = replacement
    # The in-process pure evaluator cannot authenticate caller bytes; no CLI
    # override exposes this injection, and actual publication refreshes natively.
    errors, value = check(owned, forged)
    assert errors == []
    api = Native(native_fetch(VG, owned[0], pin, releases=releases))
    with pytest.raises(P.EvidenceError, match="current native published baseline identity failed"):
        R.validate_published_baseline(VG, owned[0], "v0.10.0", pin, value, api, execution(forged))


def test_native_publisher_refresh_preserves_raw_but_ignores_download_count_mutability(owned):
    evidence = snapshot(owned)
    value = check(owned, evidence)[1]
    current = release("v0.9.0", owned[1])
    current["assets"][0]["download_count"] = 9999
    api = Native(native_fetch(VG, owned[0], owned[1], releases=[current]))
    result = R.validate_published_baseline(VG, owned[0], "v0.10.0", owned[1], value, api, execution(evidence))
    assert result["highest_other"] == "v0.9.0" and api.reads
    assert result["publication_evidence"]["catalog_passes"] != evidence["catalog_passes"]


def test_authenticated_refresh_does_not_infer_publication_from_a_private_draft(owned):
    evidence = snapshot(owned)
    value = check(owned, evidence)[1]
    draft = release("v0.9.1", owned[1], 2)
    draft.update(draft=True, published_at=None,
                 html_url="https://github.com/taipei49314/checkwash/releases/tag/untagged-owned-draft")
    api = Native(native_fetch(VG, owned[0], owned[1], releases=[release("v0.9.0", owned[1]), draft]))
    result = R.validate_published_baseline(VG, owned[0], "v0.10.0", owned[1], value, api, execution(evidence))
    assert result["highest_other"] == "v0.9.0"


def test_reuploaded_baseline_asset_identity_cannot_hide_behind_equal_byte_digest(owned):
    evidence = snapshot(owned)
    value = check(owned, evidence)[1]
    changed = release("v0.9.0", owned[1])
    changed["assets"][0]["id"] += 1
    api = Native(native_fetch(VG, owned[0], owned[1], releases=[changed]))
    with pytest.raises(P.EvidenceError, match="changed or was omitted") as caught:
        R.validate_published_baseline(VG, owned[0], "v0.10.0", owned[1], value, api, execution(evidence))
    assert caught.value.evidence["catalog_passes"]


def test_retained_metadata_cannot_precede_its_original_gate_execution(owned):
    evidence = snapshot(owned)
    value = check(owned, evidence)[1]
    api = Native(lambda url: pytest.fail("invalid custody must fail before native read"))
    bad = dict(started_at=evidence["finished_at"], finished_at=evidence["finished_at"])
    with pytest.raises(ValueError, match="outside its original gate execution"):
        R.validate_published_baseline(VG, owned[0], "v0.10.0", owned[1], value, api, bad)


def test_non_tag_gate_keeps_its_existing_zero_network_engine_contract(tmp_path, monkeypatch):
    from test_verdict_gate import e2e_inputs
    inputs = e2e_inputs(tmp_path)
    monkeypatch.setattr(P, "request", lambda url: pytest.fail("a non-tag verdict run made a metadata read"))
    engines = {"baseline": (inputs.baseline.pyz, inputs.baseline.source),
               "candidate": (inputs.candidate.pyz, inputs.candidate.source),
               "canary-old": (inputs.baseline.pyz, inputs.baseline.source),
               "canary-new": (inputs.candidate.pyz, inputs.candidate.source)}
    result = VG.run_gate(mode="gate", pins_path=inputs.pins, cases_dir=inputs.cases, engines=engines,
                         labels_path=inputs.labels, accepted_path=inputs.accepted, work_dir=tmp_path / "work")
    assert result["status"] == "passed" and result["tag_rule"] is None


def test_request_retains_http_redirect_without_forwarding_its_token(monkeypatch):
    import io
    seen = []
    class Opener:
        def open(self, req, timeout):
            seen.append(req)
            raise urllib.error.HTTPError(req.full_url, 302, "owned redirect", {"Location": "https://attacker.invalid/"}, io.BytesIO(b"owned redirect"))
    def opener(*handlers):
        redirects = [handler for handler in handlers if isinstance(handler, type) and issubclass(handler, P.urllib.request.HTTPRedirectHandler)]
        assert len(redirects) == 1
        assert redirects[0]().redirect_request(None, None, 302, None, {}, "https://attacker.invalid/") is None
        return Opener()
    monkeypatch.setattr(P.urllib.request, "build_opener", opener)
    row = P.request(P.page_url(1), token="owned-fake-token")
    assert len(seen) == 1 and seen[0].full_url == P.page_url(1)
    assert row["status"] == 302 and row["bytes"] > 0
    assert "owned-fake-token" not in str(row)
    with pytest.raises(P.EvidenceError):
        P.response(row, P.page_url(1))


def test_request_retains_an_incomplete_http_body_as_failure(monkeypatch):
    class Response:
        status = 200
        headers = {"Content-Length": "999"}
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def geturl(self):
            return P.page_url(1)
        def read(self, count):
            raise P.http.client.IncompleteRead(b"[]", 997)
    class Opener:
        def open(self, req, timeout):
            return Response()
    monkeypatch.setattr(P.urllib.request, "build_opener", lambda *handlers: Opener())
    row = P.request(P.page_url(1))
    assert row["status"] == 200 and row["bytes"] == 2 and row["truncated"] is True
    assert "IncompleteRead" in row["error"] and base64.b64decode(row["raw_base64"]) == b"[]"
    with pytest.raises(P.EvidenceError):
        P.response(row, P.page_url(1))

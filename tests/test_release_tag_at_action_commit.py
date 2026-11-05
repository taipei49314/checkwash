"""From v0.12.0 a release tag points at its Action commit A (D-200).

Every new check runs both ways on owned Git chains and owned native metadata:
a v0.12.0 or later tag follows the new rule, and a v0.11.x or earlier tag the
old one. B is the base, A the release PR's content commit, R its last commit
(doctor's own Action pin set to A), M the release merge of B and R, and S a
squash. No product code, network or candidate execution.
"""
import ast
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from types import SimpleNamespace
import zipapp
import zipfile

import pytest

from own_action_pin_fixtures import DOCTOR, PREVIOUS, chain, commit, content, doctor, git, project, repository, set_own, write
from published_release_fixtures import native_fetch

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location("tag_at_action_" + name, ROOT / "tools" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R = load("pju_release_bridge")
P = R.P
VG = load("verdict_gate")
COLLECT = load("collect_pju_release")
T = load("own_action_pin")

# What GitHub's /git/tags read of the real v0.11.0 tag object returned on
# 2026-11-06 Asia/Taipei (a read-only `gh api` call): the object's bytes after
# its headers, with LF line breaks.
V0110_MESSAGE = (
    "CheckWash v0.11.0\n\n"
    "Source: 34555301de3d5ea4b2c8e4470b797a06d0a1e395\n"
    "Tree: 49f366fd321bf9db2785cb0fd5172d040fc2c375\n"
    "Main report SHA256: 9baffee7d4acdc1bfdddf67fb774869edf6b52e5f416f478cb12506ebdc0a17d\n"
    "Main check: 126096866675\n"
    "Main receipt: b7ce77f85a0646c8861270f947e475d1a6257f5b\n"
    "Fixed-corpus comparison: 3,600 in-sample commits, empty list, reviewed by the maintainer before tagging.\n"
    "Tagged by Claude (Claude Code, LAPTOP-01AGNPJU) under the maintainer's pre-1.0 delegation.\n"
)
# The message the `tag` command writes; `{tag}` and the commits are filled in per chain.
RELEASE_MESSAGE = ("CheckWash {tag}", "Release-Merge: {M}")


def tag(root, name, target, *lines):
    git(root, "tag", "-a", name, target, *(part for line in lines for part in ("-m", line)))
    return git(root, "rev-parse", "refs/tags/" + name)


def filled(lines, c, name):
    return [line.format(tag=name, A=c["A"], M=c["M"], R=c["R"], S=c["S"]) for line in lines]


# ---------------------------------------------------------------- the shared rule

def test_one_version_boundary_serves_every_release_tool():
    assert P.ACTION_COMMIT_TAG == (0, 12, 0)
    tags = ("v0.9.1", "v0.10.0", "v0.11.0", "v0.11.12", "v0.12.0", "v0.12.1", "v1.0.0")
    assert [P.tag_at_action_commit(name) for name in tags] == [False, False, False, False, True, True, True]
    for bad in ("0.12.0", "v0.12", "v00.12.0", "v0.12.0-rc1", None):
        with pytest.raises(ValueError, match="release tag is not vX.Y.Z"):
            P.tag_at_action_commit(bad)
    # Each tool decides through the shared function, and no tool holds a boundary of its own.
    for name in ("pju_release_bridge", "verdict_gate", "collect_pju_release", "own_action_pin"):
        tree = ast.parse((ROOT / "tools" / (name + ".py")).read_text(encoding="utf-8"))
        assert any(isinstance(node, ast.Attribute) and node.attr == "tag_at_action_commit" for node in ast.walk(tree)), name
    for path in sorted((ROOT / "tools").glob("*.py")):
        if path.name == "published_release_identity.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        versions = [tuple(item.value for item in node.elts) for node in ast.walk(tree) if isinstance(node, ast.Tuple)
                    and node.elts and all(isinstance(item, ast.Constant) and type(item.value) is int for item in node.elts)]
        assert not [value for value in versions if value[:2] == (0, 12)], path.name


def test_the_message_parse_is_calibrated_on_the_real_v0_11_0_tag():
    raw = subprocess.check_output(["git", "-C", str(ROOT), "cat-file", "tag", "refs/tags/v0.11.0"])
    assert raw.startswith(b"object 34555301de3d5ea4b2c8e4470b797a06d0a1e395\ntype commit\ntag v0.11.0\n")
    assert P.tag_message(raw) == V0110_MESSAGE
    # v0.11.0 points at M and names it on a `Source:` line, which the new rule never reads.
    with pytest.raises(ValueError, match="exactly one Release-Merge line"):
        P.release_merge(V0110_MESSAGE)


MERGE = "d" * 40


@pytest.mark.parametrize("message", [
    f"CheckWash v0.12.0\n\nRelease-Merge: {MERGE}\n",
    f"Release-Merge: {MERGE}",
    f"CheckWash v0.12.0\n\nRelease-Merge: {MERGE}\nAction-Commit: {'a' * 40}\nMain check: 1\n",
])
def test_release_merge_reads_its_one_line(message):
    assert P.release_merge(message) == MERGE


@pytest.mark.parametrize("message, needle", [
    ("CheckWash v0.12.0\n", "exactly one Release-Merge line"),
    (f"Release-Merge: {MERGE}\nRelease-Merge: {MERGE}\n", "exactly one Release-Merge line"),
    (f"Release-Merge: {MERGE}\nrelease-merge: {'e' * 40}\n", "exactly one Release-Merge line"),
    (f"Release-Merge: {MERGE}\n  Release-Merge: {'e' * 40}\n", "exactly one Release-Merge line"),
    (f"Release-Merge: {MERGE.upper()}\n", "is not 'Release-Merge: <40 lowercase hex>'"),
    (f"Release-Merge:  {MERGE}\n", "is not 'Release-Merge: <40 lowercase hex>'"),
    (f"Release-Merge: {MERGE} \n", "is not 'Release-Merge: <40 lowercase hex>'"),
    (f"Release-Merge: {MERGE[:39]}\n", "is not 'Release-Merge: <40 lowercase hex>'"),
    (f" Release-Merge: {MERGE}\n", "is not 'Release-Merge: <40 lowercase hex>'"),
    (f"Release-Merge: {MERGE}\r\n", "other than printable ASCII"),
    (f"note\rRelease-Merge: {MERGE}\n", "other than printable ASCII"),
    # A reader may break a line where the tools do not, or miss a hidden prefix.
    (f"Release-Merge: {MERGE}\nnote Release-Merge: {'e' * 40}\n", "other than printable ASCII"),
    (f"Release-Merge: {MERGE}\nnote\x85Release-Merge: {'e' * 40}\n", "other than printable ASCII"),
    (f"Release-Merge: {MERGE}\nnote\x0bRelease-Merge: {'e' * 40}\n", "other than printable ASCII"),
    (f"Release-Merge: {MERGE}\n﻿Release-Merge: {'e' * 40}\n", "other than printable ASCII"),
    (f"Release-Merge: {MERGE}\n\tRelease-Merge: {'e' * 40}\n", "other than printable ASCII"),
    (f"CheckWash v0.12.0 — notes\nRelease-Merge: {MERGE}\n", "other than printable ASCII"),
    (None, "absent"),
])
def test_release_merge_refuses_anything_but_one_exact_line(message, needle):
    with pytest.raises(ValueError, match=needle):
        P.release_merge(message)


def test_tag_message_reads_an_annotated_tag_object_only(tmp_path):
    c = chain(tmp_path / "repo", version="0.12.0")
    tag(c["root"], "v0.12.0", c["A"], *filled(RELEASE_MESSAGE, c, "v0.12.0"))
    raw = subprocess.check_output(["git", "-C", str(c["root"]), "cat-file", "tag", "refs/tags/v0.12.0"])
    assert P.tag_message(raw) == f"CheckWash v0.12.0\n\nRelease-Merge: {c['M']}\n"
    for bad, needle in ((b"tree " + b"1" * 40 + b"\n\nmessage\n", "not an annotated tag object"),
                        (b"object " + b"1" * 40 + b"\ntype commit\n", "has no message"),
                        (b"object " + b"1" * 40 + b"\n\n\xff\n", "not UTF-8")):
        with pytest.raises(ValueError, match=needle):
            P.tag_message(bad)


def test_released_doctor_sets_only_the_own_line_and_only_when_the_pins_are_equal():
    action = "c" * 40
    assert P.released_doctor(doctor().encode(), action) == doctor(own=action).encode()
    refused = {
        "pins differ": doctor(own="e" * 40).encode(),
        "exactly one previous and one own": (doctor() + f'_OWN_ACTION_PIN = "{PREVIOUS}"\n').encode(),
        "exact shape": doctor().replace(f'_OWN_ACTION_PIN = "{PREVIOUS}"', f'_OWN_ACTION_PIN = "{PREVIOUS}"  # x').encode(),
        "carriage return or form feed": doctor().replace("\n", "\r\n").encode(),
    }
    for needle, raw in refused.items():
        with pytest.raises(ValueError, match=needle):
            P.released_doctor(raw, action)
    with pytest.raises(ValueError, match="carriage return or form feed"):
        P.released_doctor((doctor() + "\x0c\n").encode(), action)
    with pytest.raises(ValueError, match="full commit"):
        P.released_doctor(doctor().encode(), "c" * 39)


# ---------------------------------------------------------------- the release bridge, native

PREFIX = "/repos/" + R.REPOSITORY
B_, A_, R_, M_, TAG_OBJECT, TREE = "b" * 40, "a" * 40, "c" * 40, "d" * 40, "f" * 40, "9" * 40


class Native:
    """Owned GitHub reads; any other endpoint fails."""

    def __init__(self):
        self.data, self.reads = {}, []

    def request(self, method, path, body=None):
        assert method == "GET"
        if path not in self.data:
            raise ValueError("unexpected owned endpoint: " + path)
        self.reads.append(path)
        return copy.deepcopy(self.data[path])


def release_subject(stage, name="v0.12.0", *, head=M_, workflow=None):
    """A tag or later subject. The release-event capture runs at the tag's commit unless `workflow` says otherwise."""
    if workflow is None:
        at_action = P.tag_at_action_commit(name)
        workflow = (A_ if at_action else head) if stage == "release-event" else "e" * 40
    return dict(schema_version=1, kind="checkwash.pju-release-subject.v1", stage=stage, repository=R.REPOSITORY,
                head_sha=head, base_sha=B_, source_tree=TREE, tag=name, tag_object=TAG_OBJECT,
                release_id=None if stage == "tag" else 50,
                event=dict(name="release" if stage == "release-event" else "workflow_dispatch", run_id=60, run_attempt=1,
                           workflow_sha=workflow, created_at="2026-11-06T00:00:00Z", payload_sha256="8" * 64))


def native_chain(value, *, tagged=None, message=RELEASE_MESSAGE, merge_parents=(B_, R_), last_parents=(A_,)):
    """GitHub's objects for M, R, the tag and the release; the tag points at `tagged`.

    `message` is a sequence of lines to fill in, or None for a tag object without one.
    """
    name = value["tag"]
    if tagged is None:
        tagged = A_ if P.tag_at_action_commit(name) else value["head_sha"]
    api = Native()
    api.data[PREFIX + "/git/commits/" + M_] = dict(sha=M_, tree={"sha": TREE}, parents=[{"sha": item} for item in merge_parents])
    api.data[PREFIX + "/git/commits/" + R_] = dict(sha=R_, tree={"sha": TREE}, parents=[{"sha": item} for item in last_parents])
    api.data[PREFIX + "/git/ref/tags/" + name] = dict(ref="refs/tags/" + name, object={"type": "tag", "sha": TAG_OBJECT})
    obj = dict(sha=TAG_OBJECT, tag=name, object={"type": "commit", "sha": tagged})
    if message is not None:
        obj["message"] = "\n\n".join(line.format(tag=name, M=M_) for line in message) + "\n"
    api.data[PREFIX + "/git/tags/" + TAG_OBJECT] = obj
    if value["release_id"] is not None:
        release = dict(id=50, tag_name=name, draft=False, prerelease=False, published_at="2026-11-06T00:00:00Z", assets=[])
        api.data[PREFIX + "/releases/50"] = release
        api.data[PREFIX + "/releases/tags/" + name] = release
    event = value["event"]
    api.data[PREFIX + "/actions/runs/60/attempts/1"] = dict(
        id=60, run_attempt=1, event=event["name"], head_sha=event["workflow_sha"], path=R.WORKFLOW,
        repository={"full_name": R.REPOSITORY}, actor={"login": "taipei49314"}, triggering_actor={"login": "taipei49314"},
        created_at=event["created_at"], status="completed", conclusion="success")
    return api


@pytest.mark.parametrize("stage", ["tag", "release-event", "public-visitor"])
def test_a_v0_12_0_tag_points_at_the_action_commit_and_names_the_merge(stage):
    value = release_subject(stage)
    api = native_chain(value)
    assert R.live_subject(api, value) == stage
    assert PREFIX + "/git/commits/" + R_ in api.reads


@pytest.mark.parametrize("stage", ["tag", "release-event", "public-visitor"])
def test_a_v0_11_tag_still_points_at_the_release_merge(stage):
    value = release_subject(stage, "v0.11.9")
    assert R.live_subject(native_chain(value, message=("CheckWash {tag}",)), value) == stage
    # The old rule is unchanged: a v0.11.x tag at A is refused, and R is never read.
    api = native_chain(value, tagged=A_)
    with pytest.raises(ValueError, match="tag peeled source mismatch"):
        R.live_subject(api, value)
    assert PREFIX + "/git/commits/" + R_ not in api.reads


LIVE_REFUSALS = {
    "tag at M": (dict(tagged=M_), "tag peeled source mismatch"),
    "tag at R": (dict(tagged=R_), "tag peeled source mismatch"),
    "no Release-Merge line": (dict(message=("CheckWash {tag}",)), "exactly one Release-Merge line"),
    "two Release-Merge lines": (dict(message=("Release-Merge: {M}", "Release-Merge: {M}")), "exactly one Release-Merge line"),
    "message names another merge": (dict(message=("Release-Merge: " + "7" * 40,)), "Release-Merge is not the release merge"),
    "no message": (dict(message=None), "release tag message absent"),
    "M has one parent": (dict(merge_parents=(B_,)), "native release merge is not a two-parent merge commit"),
    "M has three parents": (dict(merge_parents=(B_, R_, A_)), "native release merge is not a two-parent merge commit"),
    "R has two parents": (dict(last_parents=(A_, B_)), "does not have one native parent"),
    "R has no parent": (dict(last_parents=()), "does not have one native parent"),
}


@pytest.mark.parametrize("case", list(LIVE_REFUSALS), ids=list(LIVE_REFUSALS))
def test_a_v0_12_0_tag_that_breaks_the_rule_is_refused(case):
    kwargs, needle = LIVE_REFUSALS[case]
    value = release_subject("tag")
    with pytest.raises(ValueError, match=needle):
        R.live_subject(native_chain(value, **kwargs), value)


def test_a_v0_12_0_tag_needs_the_native_last_commit_it_asked_for():
    value = release_subject("tag")
    api = native_chain(value)
    api.data[PREFIX + "/git/commits/" + R_]["sha"] = "6" * 40
    with pytest.raises(ValueError, match="does not have one native parent"):
        R.live_subject(api, value)


def test_the_release_event_capture_must_have_run_at_the_tag_commit():
    for workflow in (M_, "e" * 40):
        value = release_subject("release-event", workflow=workflow)
        with pytest.raises(ValueError, match="the release-event capture did not run at the tag's commit"):
            R.live_subject(native_chain(value), value)
    # v0.11.x keeps its old rule, which did not read the capture's workflow commit here.
    value = release_subject("release-event", "v0.11.9", workflow="e" * 40)
    assert R.live_subject(native_chain(value, message=("CheckWash {tag}",)), value) == "release-event"


def capture_env(tmp_path, name, event_sha):
    payload = dict(action="published", release={"id": 50, "tag_name": name, "draft": False},
                   repository={"full_name": R.REPOSITORY}, sender={"login": "taipei49314"})
    path = tmp_path / "event.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return dict(GITHUB_EVENT_NAME="release", GITHUB_REPOSITORY=R.REPOSITORY, GITHUB_REPOSITORY_OWNER="taipei49314",
                GITHUB_ACTOR="taipei49314", GITHUB_TRIGGERING_ACTOR="taipei49314", GITHUB_SHA=event_sha,
                GITHUB_WORKFLOW_SHA=event_sha, GITHUB_WORKFLOW_REF=R.REPOSITORY + "/" + R.WORKFLOW + "@refs/tags/" + name,
                GITHUB_EVENT_PATH=str(path), GITHUB_RUN_ID="60", GITHUB_RUN_ATTEMPT="1")


def endpoints(reads):
    """The endpoint kinds read, without the commit, tag and run identities."""
    return {re.sub(r"/(?:[0-9a-f]{40}|v\d+\.\d+\.\d+|\d+)(?=/|$)", "/*", path) for path in reads}


def test_the_release_event_capture_reads_the_merge_from_the_tag(tmp_path):
    # Up to v0.11.x the event runs at the tag's commit, M, which is the head.
    old = release_subject("release-event", "v0.11.9")
    api = native_chain(old, message=("CheckWash {tag}",))
    captured, raw = R.capture(api, capture_env(tmp_path, "v0.11.9", M_))
    assert (captured["head_sha"], captured["base_sha"], captured["source_tree"]) == (M_, B_, TREE)
    assert captured["tag_object"] == TAG_OBJECT and captured["event"]["workflow_sha"] == M_
    assert captured["event"]["payload_sha256"] == R.digest(raw)
    old_endpoints = endpoints(api.reads)
    # From v0.12.0 the event runs at A, and the head is the M the tag's message names.
    api = native_chain(release_subject("release-event"))
    captured, raw = R.capture(api, capture_env(tmp_path, "v0.12.0", A_))
    assert (captured["head_sha"], captured["base_sha"], captured["source_tree"]) == (M_, B_, TREE)
    assert (captured["tag"], captured["tag_object"], captured["release_id"]) == ("v0.12.0", TAG_OBJECT, 50)
    assert captured["event"]["workflow_sha"] == A_ and captured["event"]["name"] == "release"
    assert captured["event"]["payload_sha256"] == R.digest(raw)
    # No endpoint beyond those the capture and its native subject check already read.
    assert endpoints(api.reads) == old_endpoints == {
        PREFIX + "/git/commits/*", PREFIX + "/git/ref/tags/*", PREFIX + "/git/tags/*", PREFIX + "/releases/*",
        PREFIX + "/releases/tags/*", PREFIX + "/actions/runs/*/attempts/*"}


CAPTURE_REFUSALS = {
    "the event runs at M": (M_, dict(tagged=M_), "does not have the release event's commit as its Action commit"),
    "the tag points elsewhere": (A_, dict(tagged=B_), "does not point at the release event's commit"),
    "no Release-Merge line": (A_, dict(message=("CheckWash {tag}",)), "exactly one Release-Merge line"),
    "M's Action commit is another": (A_, dict(last_parents=(B_,)), "does not have the release event's commit as its Action commit"),
    "M is not a merge": (A_, dict(merge_parents=(B_,)), "not a two-parent merge commit"),
}


@pytest.mark.parametrize("case", list(CAPTURE_REFUSALS), ids=list(CAPTURE_REFUSALS))
def test_the_release_event_capture_refuses_a_broken_chain(tmp_path, case):
    event_sha, kwargs, needle = CAPTURE_REFUSALS[case]
    api = native_chain(release_subject("release-event", workflow=event_sha), **kwargs)
    with pytest.raises(ValueError, match=needle):
        R.capture(api, capture_env(tmp_path, "v0.12.0", event_sha))


def test_the_release_event_capture_needs_an_annotated_tag(tmp_path):
    api = native_chain(release_subject("release-event"))
    api.data[PREFIX + "/git/ref/tags/v0.12.0"]["object"] = {"type": "commit", "sha": A_}
    with pytest.raises(ValueError, match="annotated public tag required"):
        R.capture(api, capture_env(tmp_path, "v0.12.0", A_))
    # The ref and the tag object must both be the event's tag.
    for path, field, value, needle in (
            (PREFIX + "/git/ref/tags/v0.12.0", "ref", "refs/tags/v0.12.1", "annotated public tag required"),
            (PREFIX + "/git/tags/" + TAG_OBJECT, "tag", "v0.12.1", "does not point at the release event's commit")):
        api = native_chain(release_subject("release-event"))
        api.data[path][field] = value
        with pytest.raises(ValueError, match=needle):
            R.capture(api, capture_env(tmp_path, "v0.12.0", A_))


# ---------------------------------------------------------------- the release bridge, local

def function(path, name):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    return next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)


def calls(node):
    return [ast.unparse(item.func) for item in ast.walk(node) if isinstance(item, ast.Call)]


def test_the_tag_source_and_visitor_bind_the_commit_the_tag_points_at(tmp_path):
    c = chain(tmp_path / "repo", version="0.12.0")
    root = c["root"]
    tree = git(root, "rev-parse", c["M"] + "^{tree}")
    current = dict(tag="v0.12.0", head_sha=c["M"], base_sha=c["B"], source_tree=tree)
    assert R.tag_commit(root, current) == (c["A"], git(root, "rev-parse", c["A"] + "^{tree}"))
    assert R.tag_commit(root, dict(current, tag="v0.11.9")) == (c["M"], tree)
    for changed in (dict(head_sha=c["S"]), dict(base_sha=c["A"])):
        with pytest.raises(ValueError, match="not a two-parent merge commit of its base"):
            R.tag_commit(root, dict(current, **changed))
    nested = git(root, "commit-tree", c["R"] + "^{tree}", "-p", c["B"], "-p", c["M"], "-m", "merge of a merge")
    with pytest.raises(ValueError, match="does not have one parent"):
        R.tag_commit(root, dict(current, head_sha=nested))
    assert calls(function("tools/pju_release_bridge.py", "validate_tag_records")).count("tag_commit") == 1
    assert calls(function("tools/pju_release_bridge.py", "validate_visitors")).count("validate_tag_records") == 1


@pytest.mark.parametrize("name", ["v0.12.0", "v0.11.9"])
def test_the_tag_records_are_held_to_the_commit_the_tag_points_at(tmp_path, monkeypatch, name):
    c = chain(tmp_path / "repo", version=name[1:])
    root = c["root"]
    tagged = c["A"] if name == "v0.12.0" else c["M"]
    current = dict(stage="tag", tag=name, tag_object=TAG_OBJECT, head_sha=c["M"], base_sha=c["B"],
                   source_tree=git(root, "rev-parse", c["M"] + "^{tree}"))
    seen = []
    monkeypatch.setattr(R, "validate_source_receipt", lambda receipt, **kwargs: seen.append(("source", receipt, kwargs)))
    monkeypatch.setattr(R, "validate_visitor", lambda packet, visitor, exits, source_root, commit, version, *, source_identity:
                        seen.append(("visitor", visitor, commit, version, source_identity)))
    visitor = dict(schema_version=1, status="completed", subject=current,
                   visitor=dict(target="git+https://github.com/" + R.REPOSITORY + ".git@" + name))
    packet = SimpleNamespace(json={"tag-source.json": {"receipt": "owned"}, "tag-visitor.json": visitor}.__getitem__)
    records = dict(tag_source="tag-source.json", tag_visitor="tag-visitor.json")
    assert R.validate_tag_records(packet, records, root, "trusted", "collector", current, name[1:], "exits") == tagged
    tree = git(root, "rev-parse", tagged + "^{tree}")
    assert seen == [("source", {"receipt": "owned"}, dict(tag=name, commit=tagged, tag_object=TAG_OBJECT, tree=tree,
                                                         trusted_root="trusted", collector="collector")),
                    ("visitor", visitor["visitor"], tagged, name[1:], tagged)]


def test_a_v0_12_0_baseline_binds_the_merge_built_pyz_to_its_action_commit(tmp_path):
    c = chain(tmp_path / "repo", version="0.12.0")
    root = c["root"]
    merge_members = R.engine_source_members(root, c["M"], None)
    pin = dict(tag="v0.12.0", version="0.12.0", commit=c["A"], sha256="0" * 64, size=1)
    assert R.engine_source_members(root, c["A"], pin) == merge_members
    # Before v0.12.0 the pinned commit's own tree is the pyz's, as before.
    old = dict(pin, tag="v0.11.9", version="0.11.9")
    assert R.engine_source_members(root, c["A"], old) == R.engine_source_members(root, c["A"], None) != merge_members
    unclean = chain(tmp_path / "unclean", version="0.12.0", doctor_text=doctor(own="e" * 40))
    with pytest.raises(ValueError, match="pins differ"):
        R.engine_source_members(unclean["root"], unclean["A"], pin)
    verdict = function("tools/pju_release_bridge.py", "validate_verdict")
    assert "verdict_engine_source" in calls(verdict)
    assert not [node for node in ast.walk(verdict) if isinstance(node, ast.Constant) and node.value == "src/checkwash"]


def engine_pyz(root, commit):
    """A pyz whose package is the commit's `src/checkwash`."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("__main__.py", "owned\n")
        for name, raw in sorted(R.B.tree_files(root, commit, "src/checkwash").items()):
            archive.writestr("checkwash/" + name, raw)
    return buffer.getvalue()


def test_a_verdict_engine_is_held_to_its_pin_and_its_source(tmp_path):
    c = chain(tmp_path / "repo", version="0.12.0")
    root = c["root"]
    built, own = engine_pyz(root, c["M"]), engine_pyz(root, c["A"])

    def run(role, raw, commit, pins):
        packet = SimpleNamespace(raw={"engine.pyz": raw}.__getitem__,
                                 json={"q.json": {"artifact_sha256": R.digest(raw)}}.__getitem__,
                                 manifest={"records": {"qualifications": {"pyz": "q.json"}}})
        item = dict(source_sha=commit, pyz="engine.pyz", sha256=R.digest(raw), bytes=len(raw), runtime_path="owned")
        return R.verdict_engine_source(packet, root, role, item, pins, c["M"])

    def pins(raw, name):
        pin = dict(tag=name, version=name[1:], commit=c["A"], sha256=R.digest(raw), size=len(raw))
        return {"baseline": pin, "canary": {"old": pin, "new": pin}}

    # A v0.12.0 pin's commit is A, and its pyz is built from M, A's tree with doctor's own line set to A.
    commit, raw, members = run("baseline", built, c["A"], pins(built, "v0.12.0"))
    assert (commit, raw) == (c["A"], built) and "checkwash/doctor.py" in members
    with pytest.raises(ValueError, match="verdict engine archive/source members differ"):
        run("baseline", own, c["A"], pins(own, "v0.12.0"))
    # Before v0.12.0 the pinned commit's own tree is the pyz's, for the baseline and the canaries.
    for role in ("baseline", "canary-old", "canary-new"):
        assert run(role, own, c["A"], pins(own, "v0.11.9"))[0] == c["A"]
        with pytest.raises(ValueError, match="verdict engine archive/source members differ"):
            run(role, built, c["A"], pins(built, "v0.11.9"))
    # The candidate is the head's tree and its qualified pyz.
    assert run("candidate", built, c["M"], pins(own, "v0.12.0"))[0] == c["M"]
    with pytest.raises(ValueError, match="verdict engine source mismatch"):
        run("candidate", built, c["A"], pins(own, "v0.12.0"))


# ---------------------------------------------------------------- the verdict gate

FAKE_CLI = '''import json
import sys

VERSION = "{version}"


def main():
    args = sys.argv[1:]
    if args == ["--version"]:
        print("checkwash " + VERSION)
        return 0
    if args == ["check", "HEAD..HEAD", "--format", "json"]:
        print(json.dumps({{"checkwash_findings_version": 2, "findings": [], "summary": {{}}, "config_errors": [],
                          "skipped_files": [], "verdict": "pass",
                          "run": {{"base": "HEAD", "head": "HEAD", "checkwash_version": VERSION}}}}))
        return 0
    print("checkwash engine error: owned fake", file=sys.stderr)
    return 2
'''


def fake_release(tmp_path, version, *, released=True, doctor_text=None):
    """A committed fake source at the pinned commit, and a pyz built as the release builds it.

    With `released`, the pyz is built from the release merge's tree, whose doctor
    sets the own Action pin to the pinned commit; else from the commit's own tree.
    """
    source = tmp_path / "source"
    write(source, {"src/checkwash/__init__.py": f"__version__ = {version!r}\n",
                   "src/checkwash/cli.py": FAKE_CLI.format(version=version),
                   "src/checkwash/zipapp_entry.py": "def run():\n    from checkwash.cli import main\n    raise SystemExit(main())\n",
                   DOCTOR: doctor() if doctor_text is None else doctor_text,
                   "pyproject.toml": project(version)})
    VG._git(source, "init", "-q", "-b", "main")
    VG._git(source, "add", "--all")
    VG._git(source, "commit", "-q", "-m", "fake release " + version)
    action = VG._git_text(source, "rev-parse", "HEAD")
    build = tmp_path / "build"
    shutil.copytree(source / "src", build)
    if released:
        path = build / "checkwash" / "doctor.py"
        path.write_bytes(path.read_bytes().replace(f'_OWN_ACTION_PIN = "{PREVIOUS}"'.encode(),
                                                   f'_OWN_ACTION_PIN = "{action}"'.encode()))
    pyz = tmp_path / "engine.pyz"
    zipapp.create_archive(build, pyz, main="checkwash.zipapp_entry:run")
    data = pyz.read_bytes()
    pin = dict(tag="v" + version, version=version, commit=action, sha256=hashlib.sha256(data).hexdigest(), size=len(data))
    return VG.Engine(role="baseline", python=sys.executable, pyz=pyz, source=source, pin=pin)


def test_a_v0_12_0_baseline_pyz_is_bound_to_its_action_commit(tmp_path):
    record = VG.verify_identity(fake_release(tmp_path / "released", "0.12.0"), tmp_path / "work")
    assert record["errors"] == []
    assert record["controls"] == {"clean_range": "ok", "invalid_ref": "ok"}
    assert record["cli_version"] == "checkwash 0.12.0"


def test_a_v0_12_0_baseline_refuses_its_unreleased_tree_and_an_unclean_action_commit(tmp_path):
    record = VG.verify_identity(fake_release(tmp_path / "as-is", "0.12.0", released=False), tmp_path / "work")
    assert any("members does not match source package: checkwash/doctor.py" in error for error in record["errors"])
    assert record["cli_version"] is None and record["proposed_pin"] is None
    record = VG.verify_identity(fake_release(tmp_path / "unclean", "0.12.0", doctor_text=doctor(own="e" * 40)),
                                tmp_path / "work2")
    assert any("pins differ" in error for error in record["errors"]), record["errors"]
    assert record["cli_version"] is None and record["proposed_pin"] is None


def test_a_v0_11_baseline_keeps_its_commits_own_tree(tmp_path):
    assert VG.verify_identity(fake_release(tmp_path / "as-is", "0.11.9", released=False), tmp_path / "work")["errors"] == []
    record = VG.verify_identity(fake_release(tmp_path / "released", "0.11.9"), tmp_path / "work2")
    assert any("members does not match source package: checkwash/doctor.py" in error for error in record["errors"])


def tag_rule_repo(tmp_path, monkeypatch, pushed, target, lines=RELEASE_MESSAGE, *, head="M", lightweight=False):
    """A chain whose base B is the published baseline v0.11.0, with the pushed tag on `target` and HEAD at `head`."""
    c = chain(tmp_path / "repo", version=pushed[1:])
    root = c["root"]
    git(root, "tag", "-a", "v0.11.0", c["B"], "-m", "baseline")
    if lightweight:
        git(root, "tag", pushed, c[target])
    else:
        tag(root, pushed, c[target], *filled(lines, c, pushed))
    git(root, "checkout", "-q", "--detach", c[head])
    pin = dict(tag="v0.11.0", version="0.11.0", commit=c["B"], sha256="b" * 64, size=100)
    monkeypatch.setattr(VG._PUBLICATION, "request", native_fetch(VG, root, pin))
    return c, pin


def test_the_tag_rule_from_v0_12_0_runs_on_the_merge_its_tag_names(tmp_path, monkeypatch):
    c, pin = tag_rule_repo(tmp_path, monkeypatch, "v0.12.0", "A")
    errors, info = VG.check_tag_rule(c["root"], "v0.12.0", pin)
    assert errors == [] and info["highest_other"] == "v0.11.0"


TAG_RULE_REFUSALS = {
    "tag at M": (dict(target="M"), "the pushed tag v0.12.0 points at {M}, not at HEAD's Action commit HEAD^2^1 ({A})"),
    "message names the squash": (dict(lines=("Release-Merge: {S}",)), "names the release merge {S}, not HEAD {M}"),
    "no Release-Merge line": (dict(lines=("CheckWash {tag}",)), "exactly one Release-Merge line"),
    "lightweight tag": (dict(lightweight=True), "pushed tag v0.12.0: git cat-file failed"),
    "run on the tag's commit": (dict(head="A"), "HEAD {A} has no Action commit HEAD^2^1 for the pushed tag v0.12.0"),
}


@pytest.mark.parametrize("case", list(TAG_RULE_REFUSALS), ids=list(TAG_RULE_REFUSALS))
def test_the_tag_rule_from_v0_12_0_refuses_a_tag_off_the_rule(tmp_path, monkeypatch, case):
    kwargs, expected = TAG_RULE_REFUSALS[case]
    kwargs = dict(kwargs)
    c, pin = tag_rule_repo(tmp_path, monkeypatch, "v0.12.0", kwargs.pop("target", "A"), **kwargs)
    errors = VG.check_tag_rule(c["root"], "v0.12.0", pin)[0]
    assert any(expected.format(A=c["A"], M=c["M"], S=c["S"]) in error for error in errors), errors


def test_the_tag_rule_before_v0_12_0_still_runs_on_the_tags_commit(tmp_path, monkeypatch):
    c, pin = tag_rule_repo(tmp_path / "old", monkeypatch, "v0.11.9", "M", ("CheckWash {tag}",))
    assert VG.check_tag_rule(c["root"], "v0.11.9", pin)[0] == []
    c, pin = tag_rule_repo(tmp_path / "at-a", monkeypatch, "v0.11.9", "A")
    assert VG.check_tag_rule(c["root"], "v0.11.9", pin)[0] == [
        f"HEAD {c['M']} is not the commit of the pushed tag v0.11.9 ({c['A']})"]


# ---------------------------------------------------------------- the collector

class Reader:
    """The collector's Git reader, on an owned repository."""

    def read(self, root, *args):
        return subprocess.check_output(["git", "-C", str(root), *args])

    def text(self, root, *args):
        return self.read(root, *args).decode("utf-8").strip()


def collection(tmp_path, value, **args):
    tmp_path.mkdir(parents=True, exist_ok=True)
    payload = b'{"action":"published"}'
    value["event"]["payload_sha256"] = COLLECT.digest(payload)
    parents = {name: dict(report="parents/" + name + ".json", sha256=COLLECT.digest(b"{}"), check_run_id=3)
               for name in COLLECT.STAGES[value["stage"]]}
    (tmp_path / "parents").mkdir(exist_ok=True)
    for row in parents.values():
        (tmp_path / row["report"]).write_bytes(b"{}")
    files = {"subject.json": json.dumps(value, sort_keys=True).encode(), "event.json": payload,
             "parents.json": json.dumps(parents, sort_keys=True).encode()}
    for name, raw in files.items():
        (tmp_path / name).write_bytes(raw)
    namespace = SimpleNamespace(subject=tmp_path / "subject.json", subject_sha256=COLLECT.digest(files["subject.json"]),
                                event_payload=tmp_path / "event.json", parents=tmp_path / "parents.json",
                                parents_sha256=COLLECT.digest(files["parents.json"]), parent_report_root=tmp_path,
                                release_artifacts=None, release_artifacts_sha256=None, advertised_source=None,
                                verdict_baseline_source=None, action_root=tmp_path / "action",
                                verdict_canary_old_source=tmp_path / "old", verdict_canary_new_source=tmp_path / "new",
                                tag_source=None)
    for key, item in args.items():
        setattr(namespace, key, item)
    return COLLECT.ReleaseCollection(namespace, COLLECT.load_backend())


def collector_case(tmp_path, name, target, lines=RELEASE_MESSAGE, stage="tag"):
    c = chain(tmp_path / "repo", version=name[1:])
    tag_object = tag(c["root"], name, c[target], *filled(lines, c, name))
    value = dict(release_subject(stage, name, head=c["M"]), base_sha=c["B"], tag_object=tag_object,
                 source_tree=git(c["root"], "rev-parse", c["M"] + "^{tree}"))
    value["event"]["created_at"] = "2020-01-01T00:00:00Z"
    helpers = {path: {"sha256": "owned"} for path in ("tools/verdict_gate.py", "tools/published_release_identity.py",
                                                       "tools/verify_published_source.py", "tools/qualify_zipapp.py")}
    ctx = dict(source_before=helpers, trusted_before=helpers, source=c["root"], reader=Reader(),
               project={"version": name[1:]}, output=tmp_path / "out", scratch=tmp_path / "scratch",
               manifest={"runtime": {"os": "Windows", "python_version": "3.11.9", "dependencies": {"twine": "owned"}}})
    return c, value, ctx


def tag_source_checkout(tmp_path, c):
    """A clean clone of the chain at A, with its tags."""
    path = tmp_path / "tag-source"
    git(tmp_path, "clone", "-q", str(c["root"]), str(path))
    git(path, "checkout", "-q", "--detach", c["A"])
    for key, value in {"user.name": "Owned tag source", "user.email": "fixture@example.invalid"}.items():
        git(path, "config", key, value)
    return path


@pytest.mark.parametrize("stage", ["tag", "release-event"])
def test_the_collector_checks_a_v0_12_0_tag_on_the_action_commit(tmp_path, stage):
    c, value, ctx = collector_case(tmp_path, "v0.12.0", "A", stage=stage)
    with_source = collection(tmp_path / "a", value, tag_source=tag_source_checkout(tmp_path, c))
    with_source.preflight(ctx)
    assert with_source.tag_commit(ctx) == c["A"]
    with pytest.raises(ValueError, match="needs --tag-source"):
        collection(tmp_path / "b", value).preflight(ctx)


def test_the_collector_checks_the_tag_source_before_the_long_steps(tmp_path):
    c, value, ctx = collector_case(tmp_path, "v0.12.0", "A")
    path = tag_source_checkout(tmp_path, c)
    coll = collection(tmp_path / "a", value, tag_source=path)
    coll.preflight(ctx)
    assert ctx["tag_source"] == (path, coll.action.snapshot(ctx["reader"], path, c["A"]))
    # A checkout at M, a dirty one and one whose tag is another object are refused at once.
    git(path, "checkout", "-q", "--detach", c["M"])
    with pytest.raises(ValueError, match="checkout HEAD mismatch"):
        collection(tmp_path / "b", value, tag_source=path).preflight(ctx)
    git(path, "checkout", "-q", "--detach", c["A"])
    (path / "stray.txt").write_text("stray\n", encoding="utf-8")
    with pytest.raises(ValueError, match="dirty source checkout"):
        collection(tmp_path / "c", value, tag_source=path).preflight(ctx)
    (path / "stray.txt").unlink()
    git(path, "tag", "-d", "v0.12.0")
    tag(path, "v0.12.0", c["A"], *filled(RELEASE_MESSAGE, c, "v0.12.0"), "again")
    with pytest.raises(ValueError, match="does not hold the release tag"):
        collection(tmp_path / "d", value, tag_source=path).preflight(ctx)


COLLECTOR_REFUSALS = {
    "tag at M": ("M", RELEASE_MESSAGE, "local annotated tag identity differs"),
    "message names the squash": ("A", ("Release-Merge: {S}",), "local tag message names another release merge"),
    "no Release-Merge line": ("A", ("CheckWash {tag}",), "exactly one Release-Merge line"),
}


@pytest.mark.parametrize("case", list(COLLECTOR_REFUSALS), ids=list(COLLECTOR_REFUSALS))
def test_the_collector_refuses_a_v0_12_0_tag_off_the_rule(tmp_path, case):
    target, lines, needle = COLLECTOR_REFUSALS[case]
    c, value, ctx = collector_case(tmp_path, "v0.12.0", target, lines)
    with pytest.raises(ValueError, match=needle):
        collection(tmp_path / "collection", value, tag_source=tmp_path / "tag-source").preflight(ctx)


def test_the_collector_keeps_a_v0_11_tag_on_the_merge_without_a_tag_source(tmp_path):
    c, value, ctx = collector_case(tmp_path, "v0.11.9", "M", ("CheckWash {tag}",))
    collection(tmp_path / "a", value).preflight(ctx)
    with pytest.raises(ValueError, match="--tag-source is only for v0.12.0 and later tags"):
        collection(tmp_path / "b", value, tag_source=tmp_path / "tag-source").preflight(ctx)
    pr = dict(release_subject("tag"), stage="pr", tag=None, tag_object=None, release_id=None, pr_number=1)
    pr["event"]["created_at"] = "2020-01-01T00:00:00Z"
    with pytest.raises(ValueError, match="--tag-source is only for tag and later stages"):
        collection(tmp_path / "pr", pr, tag_source=tmp_path / "tag-source").preflight(dict(ctx, reader=None))


@pytest.mark.parametrize("name", ["v0.12.0", "v0.11.9"])
def test_the_tag_source_receipt_and_visitor_bind_the_tag_commit(tmp_path, name):
    at_action = name == "v0.12.0"
    c, value, ctx = collector_case(tmp_path, name, "A" if at_action else "M",
                                   RELEASE_MESSAGE if at_action else ("CheckWash {tag}",))
    tag_source = tmp_path / "tag-source"
    coll = collection(tmp_path / "collection", value, tag_source=tag_source if at_action else None)
    seen = []
    snapshot = {"src/checkwash/doctor.py": {"sha256": "A's doctor"}}
    later = [snapshot]

    def tag_source_receipt(ctx, label, source, tag_name, commit, tag_object):
        seen.append(("tag-source", source, commit, tag_object))

    def visitor(ctx, label, target, version, members, *, source_identity=None):
        seen.append(("visitor", target, members, source_identity))
        return {"name": label}

    def after(reader, path, commit):
        seen.append(("after", path, commit))
        return later[0]

    coll.preflight = lambda ctx: None
    coll.qualify_zipapp = coll.verdict = coll.advertised = lambda ctx, *args: None
    coll.tag_source, coll.visitor = tag_source_receipt, visitor
    coll.action = SimpleNamespace(snapshot=after)
    ctx.update(run=lambda *args, **kwargs: b"", output=tmp_path / "out", py=["python"], wheel="w", sdist="s",
               source_before={"src/checkwash/doctor.py": {"sha256": "M's doctor"}})
    if at_action:
        # Preflight took the checkout's snapshot.
        ctx["tag_source"] = (tag_source, snapshot)
    coll.stage_steps(ctx)
    target = "git+" + COLLECT.PUBLIC_GIT + "@" + name
    if at_action:
        assert seen == [("tag-source", tag_source, c["A"], value["tag_object"]),
                        ("visitor", target, snapshot, c["A"]), ("after", tag_source, c["A"])]
        # The checkout must not change while the collection runs.
        later[0] = {"src/checkwash/doctor.py": {"sha256": "changed"}}
        with pytest.raises(ValueError, match="tag source changed"):
            coll.stage_steps(ctx)
    else:
        assert seen == [("tag-source", c["root"], c["M"], value["tag_object"]),
                        ("visitor", target, ctx["source_before"], c["M"])]


# ---------------------------------------------------------------- tools/own_action_pin.py

def release_repository(root):
    """B with the files the release-event capture runs, then A at 0.12.0, R and M."""
    repository(root)
    write(root, {path: f"owned {path}\n" for path in T.CAPTURE_FILES})
    b = commit(root, "B with the capture files")
    a = content(root, "0.12.0")
    set_own(root, a)
    r = commit(root, "R")
    m = git(root, "commit-tree", r + "^{tree}", "-p", b, "-p", r, "-m", "merge")
    return dict(root=root, B=b, A=a, R=r, M=m)


def test_the_capture_files_are_the_helpers_the_release_tools_load_or_audit():
    def names(node):
        return {"tools/" + item.value.removeprefix("tools/") for item in ast.walk(node)
                if isinstance(item, ast.Constant) and type(item.value) is str and item.value.endswith(".py")}

    trusted = names(function("tools/pju_release_bridge.py", "verify_admitted"))
    assert "tools/published_release_identity.py" in trusted
    tree = ast.parse((ROOT / "tools/collect_pju_release.py").read_text(encoding="utf-8"))
    preflight = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "preflight")
    audited = names(preflight) | set(R.B.UTILITIES) | {"tools/receipt_execution_route.py"}
    assert set(T.CAPTURE_FILES) == trusted | audited | {".github/workflows/release.yml"}


def main_report(path, c, **changes):
    value = dict(kind="checkwash.pju-release-verification.v1", status="verified", repository=R.REPOSITORY,
                 subject=dict(stage="main", head_sha=c["M"], base_sha=c["B"]), check_run_id=1)
    value.update(changes)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def remote_main(tmp_path, root, sha):
    remote = tmp_path / "remote.git"
    if not remote.exists():
        git(tmp_path, "init", "-q", "--bare", str(remote))
    git(root, "push", "-q", "--force", str(remote), sha + ":refs/heads/main")
    return remote


def pre_push(c, report, remote, trusted):
    return ["check", "--repo", str(c["root"]), "--stage", "tag", "--head", c["M"], "--base", c["B"],
            "--announced", PREVIOUS, "--main-report", str(report), "--trusted", trusted, "--remote", str(remote)]


def refused(capsys, args, needle):
    assert T.main(args) == 2
    assert needle in capsys.readouterr().err


def test_the_tag_command_puts_the_tag_on_the_action_commit_and_names_the_merge(tmp_path, capsys):
    c = release_repository(tmp_path / "repo")
    assert T.main(["tag", "--repo", str(c["root"]), "--head", c["M"], "--base", c["B"], "--announced", PREVIOUS]) == 0
    printed = capsys.readouterr().out
    assert printed == f'git tag -a v0.12.0 {c["A"]} -m "CheckWash v0.12.0" -m "Release-Merge: {c["M"]}"\n'
    # The printed command makes the tag every tool reads.
    tag(c["root"], "v0.12.0", c["A"], "CheckWash v0.12.0", f"Release-Merge: {c['M']}")
    raw = subprocess.check_output(["git", "-C", str(c["root"]), "cat-file", "tag", "refs/tags/v0.12.0"])
    assert P.release_merge(P.tag_message(raw)) == c["M"]
    # Before v0.12.0 the tag is made on M, so there is no such command.
    old = chain(tmp_path / "old")
    refused(capsys, ["tag", "--repo", str(old["root"]), "--head", old["M"], "--base", old["B"], "--announced", PREVIOUS],
            "only from v0.12.0 does a tag point at the Action commit")
    # The head must be a release merge that scheme S verifies.
    refused(capsys, ["tag", "--repo", str(c["root"]), "--head", c["R"], "--base", c["B"], "--announced", PREVIOUS],
            "not a two-parent merge commit")


def test_the_pre_push_tag_check_runs_the_three_local_checks(tmp_path, capsys):
    c = release_repository(tmp_path / "repo")
    tag(c["root"], "v0.12.0", c["A"], "CheckWash v0.12.0", f"Release-Merge: {c['M']}")
    report = main_report(tmp_path / "main.json", c)
    remote = remote_main(tmp_path, c["root"], c["M"])
    assert T.main(pre_push(c, report, remote, c["B"])) == 0
    result = json.loads(capsys.readouterr().out)
    assert (result["action_commit"], result["release_pr_head"]) == (c["A"], c["R"])
    assert result["tag"] == {"name": "v0.12.0", "tag_object": git(c["root"], "rev-parse", "refs/tags/v0.12.0"),
                             "action_commit": c["A"], "release_merge": c["M"], "trusted": c["B"]}
    # From v0.12.0 the tag check needs both inputs.
    refused(capsys, pre_push(c, report, remote, c["B"])[:-6] + ["--remote", str(remote)],
            "needs --main-report and --trusted")


def test_the_pre_push_tag_check_refuses_each_broken_link(tmp_path, capsys):
    c = release_repository(tmp_path / "repo")
    root = c["root"]
    report = main_report(tmp_path / "main.json", c)
    remote = remote_main(tmp_path, root, c["M"])
    args = pre_push(c, report, remote, c["B"])
    # 1. The local tag: missing, lightweight, on M, or naming another merge.
    refused(capsys, args, "git cat-file -t refs/tags/v0.12.0 failed")
    git(root, "tag", "v0.12.0", c["A"])
    refused(capsys, args, "is not an annotated tag")
    for target, lines, needle in ((c["M"], (f"Release-Merge: {c['M']}",), f"points at {c['M']}, not at the Action commit"),
                                  (c["A"], (f"Release-Merge: {c['R']}",), "does not name the release merge"),
                                  (c["A"], ("CheckWash v0.12.0",), "exactly one Release-Merge line")):
        git(root, "tag", "-d", "v0.12.0")
        tag(root, "v0.12.0", target, *lines)
        refused(capsys, args, needle)
    # A tag of a tag peels to A, but the bridge reads the tag object's own target.
    git(root, "tag", "-d", "v0.12.0")
    tag(root, "inner", c["A"], "inner")
    tag(root, "v0.12.0", "inner", "CheckWash v0.12.0", f"Release-Merge: {c['M']}")
    git(root, "tag", "-d", "inner")
    refused(capsys, args, "does not point at the Action commit")
    # A tag object named for another release.
    git(root, "tag", "-d", "v0.12.0")
    body = (f"object {c['A']}\ntype commit\ntag v0.12.1\ntagger Owned <owned@example.invalid> 0 +0000\n\n"
            f"CheckWash v0.12.0\n\nRelease-Merge: {c['M']}\n")
    misnamed = subprocess.run(["git", "-C", str(root), "mktag"], input=body.encode(), capture_output=True, check=True)
    git(root, "update-ref", "refs/tags/v0.12.0", misnamed.stdout.decode().strip())
    refused(capsys, args, "is not named v0.12.0")
    git(root, "tag", "-d", "v0.12.0")
    tag(root, "v0.12.0", c["A"], "CheckWash v0.12.0", f"Release-Merge: {c['M']}")
    # 2. M is the main stage report's verified head and the remote's main; a
    #    test-merge commit of an open pull request also has A as its ^2^1.
    for changes in (dict(kind="checkwash.pju-release-verification.v2"), dict(status="failed"), dict(repository="other/repo"),
                    dict(subject=dict(stage="tag", head_sha=c["M"], base_sha=c["B"])),
                    dict(subject=dict(stage="main", head_sha=c["R"], base_sha=c["B"])),
                    dict(subject=dict(stage="main", head_sha=c["M"], base_sha=c["A"]))):
        main_report(report, c, **changes)
        refused(capsys, args, "is not a verified main report of this release merge")
    main_report(report, c)
    remote_main(tmp_path, root, c["B"])
    refused(capsys, args, f"is not the release merge {c['M']}")
    remote_main(tmp_path, root, c["M"])
    # 3. A holds the trusted ref's bytes of every file the release-event capture runs.
    write(root, {"tools/pju_release_bridge.py": "owned tools/pju_release_bridge.py, changed\n"})
    trusted = commit(root, "a trusted ref with another bridge")
    refused(capsys, pre_push(c, report, remote, trusted),
            "the Action commit differs from the trusted ref in tools/pju_release_bridge.py")
    assert T.main(pre_push(c, report, remote, c["B"])) == 0


def test_the_tag_check_before_v0_12_0_keeps_its_rule_and_takes_no_pre_push_inputs(tmp_path, capsys):
    old = chain(tmp_path / "old")
    base = ["check", "--repo", str(old["root"]), "--stage", "tag", "--head", old["M"], "--base", old["B"],
            "--announced", PREVIOUS]
    assert T.main(base) == 0
    assert json.loads(capsys.readouterr().out) == {"applies": True, "action_commit": old["A"],
                                                   "release_pr_head": old["R"], "previous_action_pin": PREVIOUS}
    refused(capsys, base + ["--trusted", old["B"]], "are for the tag stage of a v0.12.0 or later release")
    pr = ["check", "--repo", str(old["root"]), "--stage", "pr", "--head", old["R"], "--base", old["B"],
          "--announced", PREVIOUS]
    refused(capsys, pr + ["--main-report", str(tmp_path / "unused.json")],
            "are for the tag stage of a v0.12.0 or later release")

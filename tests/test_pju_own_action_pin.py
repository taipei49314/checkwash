"""Scheme S (D-194) in the release bridge and the ordinary receipt bridge.

Owned Git chains and owned native metadata only; no product code, network or
candidate execution.
"""
import ast
import importlib.util
import json
from pathlib import Path

import pytest

from own_action_pin_fixtures import (ACTION, ADVERTISED, DOCTOR, PREVIOUS, chain, commit, doctor, git, project,
                                     repository, write)

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("pju_release_bridge_own_pin", ROOT / "tools/pju_release_bridge.py")
R = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(R)
B = R.B


def current(stage, head, base):
    return {"stage": stage, "head_sha": head, "base_sha": base}


def verify(c, stage, head, *, base=None, announced=PREVIOUS, pr_head=None):
    return R.validate_own_action_pin(c["root"], current(stage, head, c["B"] if base is None else base),
                                     announced=announced, pr_head=pr_head)


@pytest.fixture
def good(tmp_path):
    return chain(tmp_path / "good")


def test_the_release_chain_verifies_at_every_stage(good):
    expected = {"applies": True, "action_commit": good["A"], "release_pr_head": good["R"], "previous_action_pin": PREVIOUS}
    assert verify(good, "pr", good["R"]) == expected
    assert verify(good, "main", good["M"], pr_head=good["R"]) == expected
    for stage in ("main", "tag", "release-event", "public-visitor"):
        assert verify(good, stage, good["M"]) == expected


def test_a_subject_at_the_advertised_version_is_not_a_release(tmp_path):
    root = tmp_path / "plain"
    c = dict(root=root, B=repository(root))
    write(root, {"NEWS": "no version change\n"})
    head = commit(root, "H")
    for stage in ("pr", "main"):
        assert verify(c, stage, head) == {"applies": False}
    with pytest.raises(ValueError, match="not a two-parent merge commit"):
        verify(c, "tag", head)


def test_a_version_bumped_in_an_earlier_pr_still_needs_r(tmp_path):
    # Head and base both say 0.11.0; the advertised release is still 0.10.0.
    c = chain(tmp_path / "bumped", base_version="0.11.0", version="0.11.0")
    with pytest.raises(ValueError, match="own Action pin is not the one parent"):
        verify(c, "pr", c["A"])
    assert verify(c, "pr", c["R"])["action_commit"] == c["A"]


def test_merge_shape_and_pr_head_are_bound(good):
    cases = {
        "pr head without R": (dict(stage="pr", head=good["A"]), "own Action pin is not the one parent"),
        "squash": (dict(stage="main", head=good["S"], pr_head=good["R"]), "not a two-parent merge commit"),
        "squash at the tag": (dict(stage="tag", head=good["S"]), "not a two-parent merge commit"),
        "other PR head": (dict(stage="main", head=good["M"], pr_head=good["A"]), "not the verified release PR head"),
        "other base": (dict(stage="tag", head=good["M"], base=good["A"]), "not a two-parent merge commit"),
        "reversed parents": (dict(stage="tag", head=git(good["root"], "commit-tree", good["R"] + "^{tree}", "-p", good["R"],
                                                        "-p", good["B"], "-m", "reversed")), "not a two-parent merge commit"),
        "A's tree": (dict(stage="tag", head=git(good["root"], "commit-tree", good["A"] + "^{tree}", "-p", good["B"],
                                                "-p", good["R"], "-m", "content tree")), "merge tree differs"),
        "merge of A": (dict(stage="tag", head=git(good["root"], "commit-tree", good["A"] + "^{tree}", "-p", good["B"],
                                                  "-p", good["A"], "-m", "no R")), "own Action pin is not the one parent"),
        "other announced pin": (dict(stage="pr", head=good["R"], announced="2" * 40), "not the announced pin"),
    }
    for label, (case, message) in cases.items():
        stage, head = case.pop("stage"), case.pop("head")
        with pytest.raises(ValueError, match=message):
            verify(good, stage, head, **case)
            pytest.fail(label)


def readme(text):
    def edit(root, action):
        (root / "README.md").write_bytes(text.encode())
    return edit


def doctor_bytes(old, new):
    def edit(root, action):
        path = root / DOCTOR
        path.write_bytes(path.read_bytes().replace(old.replace("{A}", action).encode(), new.replace("{A}", action).encode()))
    return edit


def appended(root, action):
    path = root / DOCTOR
    path.write_bytes(path.read_bytes() + b"# extra\n")


def executable(root):
    git(root, "update-index", "--chmod=+x", DOCTOR)


def crlf_blob(root):
    # *.py eol=lf would normalize a CRLF worktree file, so stage the CRLF blob directly.
    path = root.parent / "crlf-doctor.py"
    path.write_bytes((root / DOCTOR).read_bytes().replace(b"\n", b"\r\n"))
    git(root, "update-index", "--cacheinfo", "100644," + git(root, "hash-object", "-w", "--no-filters", str(path)) + "," + DOCTOR)


REFUSED = [
    ("R also edits README", dict(edit=readme(f"      - uses: {ACTION}@{PREVIOUS} # v0.10.0\nmore\n")), "outside doctor.py"),
    ("R also adds a file listed after doctor.py", dict(edit=lambda root, action: write(root, {"tools/late.py": "LATE = 1\n"})),
     "outside doctor.py"),
    ("R appends a doctor line", dict(edit=appended), "more than doctor's own Action pin line"),
    ("R sets another SHA", dict(edit=doctor_bytes('_OWN_ACTION_PIN = "{A}"', '_OWN_ACTION_PIN = "' + "3" * 40 + '"')),
     "own Action pin is not the one parent"),
    ("R changes another doctor line", dict(edit=doctor_bytes("_X = 1", "_X = 2")), "more than doctor's own Action pin line"),
    ("R writes the own line over another line", dict(doctor_text=doctor().replace(f'_OWN_ACTION_PIN = "{PREVIOUS}"', "_OWN = 0"),
                                                     edit=doctor_bytes("_OWN = 0", '_OWN_ACTION_PIN = "{A}"')),
     "more than doctor's own Action pin line"),
    ("R changes the previous pin too", dict(edit=doctor_bytes('_PREVIOUS_ACTION_PIN = "' + PREVIOUS + '"',
                                                              '_PREVIOUS_ACTION_PIN = "{A}"')), "not the announced pin"),
    ("R commits a CRLF doctor.py", dict(staged=crlf_blob), "differ from the exact shape"),
    ("R makes doctor.py executable", dict(staged=executable), "mode or change kind"),
    ("README recommends another pin", dict(readme=f"      - uses: {ACTION}@{'2' * 40} # v0.10.0\n"),
     "README does not recommend exactly the announced Action pin"),
    ("README keeps an older pin too", dict(readme=f"      - uses: {ACTION}@{PREVIOUS} # v0.10.0\n{ACTION}@{'d' * 40}\n"),
     "README does not recommend exactly the announced Action pin"),
    ("README names a tag ref too", dict(readme=f"      - uses: {ACTION}@{PREVIOUS} # v0.10.0\nTaipei49314/Checkwash/action@v0.11.0\n"),
     "README does not recommend exactly the announced Action pin"),
    ("README has no pin", dict(readme="no workflow\n"), "README does not recommend exactly the announced Action pin"),
    ("two own lines", dict(doctor_text=doctor() + f'_OWN_ACTION_PIN = "{PREVIOUS}"\n'), "exactly one previous and one own"),
    ("no previous line", dict(doctor_text=doctor().replace("_PREVIOUS_ACTION_PIN = ", "_PREVIOUS = ")),
     "exactly one previous and one own"),
]


@pytest.mark.parametrize("kwargs, message", [case[1:] for case in REFUSED], ids=[case[0] for case in REFUSED])
def test_r_changes_exactly_the_own_pin_line(tmp_path, kwargs, message):
    c = chain(tmp_path / "chain", **kwargs)
    for stage, head, pr_head in (("pr", c["R"], None), ("main", c["M"], c["R"]), ("tag", c["M"], None)):
        with pytest.raises(ValueError, match=message):
            verify(c, stage, head, pr_head=pr_head)


def test_r_with_two_parents_is_refused(good):
    tree = git(good["root"], "rev-parse", good["R"] + "^{tree}")
    merged = git(good["root"], "commit-tree", tree, "-p", good["A"], "-p", good["B"], "-m", "R as a merge")
    for stage, head in (("pr", merged), ("tag", git(good["root"], "commit-tree", tree, "-p", good["B"], "-p", merged, "-m", "M"))):
        with pytest.raises(ValueError, match="own Action pin is not the one parent"):
            verify(good, stage, head)


def test_a_shallow_or_missing_parent_fails_closed(good, tmp_path):
    shallow = tmp_path / "shallow"
    git(tmp_path, "clone", "-q", "--depth", "1", good["root"].as_uri(), str(shallow))
    assert git(shallow, "rev-parse", "HEAD") == good["R"]
    with pytest.raises(ValueError, match="own Action pin is not the one parent"):
        verify(dict(good, root=shallow), "pr", good["R"])
    with pytest.raises(ValueError):
        verify(good, "pr", "9" * 40)


class Native:
    def __init__(self, head, parents, sha=None):
        self.path = f"/repos/{R.REPOSITORY}/git/commits/{head}"
        self.value = {"sha": sha or head, "parents": parents}
        self.reads = 0

    def request(self, method, path, body=None):
        assert method == "GET" and path == self.path
        self.reads += 1
        return json.loads(json.dumps(self.value))


def test_native_merge_parents_are_github_order(good):
    own_pin = verify(good, "main", good["M"], pr_head=good["R"])
    value = current("main", good["M"], good["B"])
    api = Native(good["M"], [{"sha": good["B"]}, {"sha": good["R"]}])
    R.validate_native_merge(api, value, own_pin)
    assert api.reads == 1
    for label, api in {
        "reversed": Native(good["M"], [{"sha": good["R"]}, {"sha": good["B"]}]),
        "one parent": Native(good["M"], [{"sha": good["B"]}]),
        "three parents": Native(good["M"], [{"sha": good["B"]}, {"sha": good["R"]}, {"sha": good["A"]}]),
        "other PR head": Native(good["M"], [{"sha": good["B"]}, {"sha": good["A"]}]),
        "malformed": Native(good["M"], [good["B"], good["R"]]),
        "other commit": Native(good["M"], [{"sha": good["B"]}, {"sha": good["R"]}], sha=good["S"]),
    }.items():
        with pytest.raises(ValueError, match="native merge parents differ"):
            R.validate_native_merge(api, value, own_pin)
            pytest.fail(label)


def test_native_merge_is_not_read_for_pr_or_non_release_subjects(good):
    api = Native("0" * 40, [])
    R.validate_native_merge(api, current("pr", good["R"], good["B"]), verify(good, "pr", good["R"]))
    R.validate_native_merge(api, current("main", good["M"], good["B"]), {"applies": False})
    assert api.reads == 0


def function(tree, name):
    return next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)


def calls(node, name):
    return [item for item in ast.walk(node) if isinstance(item, ast.Call) and ast.unparse(item.func) == name]


def test_release_verification_runs_the_rule_before_product_evidence_and_reports_it():
    packet = function(ast.parse((ROOT / "tools/pju_release_bridge.py").read_text(encoding="utf-8")), "validate_packet")
    order = [calls(packet, name)[0].lineno for name in
             ("validate_parents", "validate_own_action_pin", "validate_native_merge", "validate_product")]
    assert order == sorted(order) and len(set(order)) == 4
    rule = calls(packet, "validate_own_action_pin")[0]
    assert {keyword.arg: ast.unparse(keyword.value) for keyword in rule.keywords} == {
        "announced": "B.ACTION_SHA", "pr_head": "pr_head"}
    report = [call for call in calls(packet, "dict") if any(keyword.arg == "kind" for keyword in call.keywords)]
    assert [ast.unparse(keyword.value) for call in report for keyword in call.keywords
            if keyword.arg == "own_action_pin"] == ["own_pin"]


def test_ordinary_receipts_refuse_a_head_that_changes_the_version(good, tmp_path):
    with pytest.raises(ValueError, match="only through the release bridge's pr stage"):
        B.validate_ordinary_head(good["root"], good["R"])
    with pytest.raises(ValueError, match="only through the release bridge's pr stage"):
        B.validate_ordinary_head(good["root"], good["A"])
    B.validate_ordinary_head(good["root"], good["B"])
    root = tmp_path / "broken"
    repository(root)
    for files, message in (
        ({"release/advertised.toml": None}, "release/advertised.toml at the head could not be read"),
        ({"release/advertised.toml": "[release\n"}, "release/advertised.toml at the head could not be read"),
        ({"release/advertised.toml": "[release]\ntag = 'v0.10.0'\n"}, "has no release version"),
        ({"pyproject.toml": "[project]\nversion = 1\n"}, "pyproject.toml at the head has no project version"),
    ):
        for name, text in files.items():
            if text is None:
                (root / name).unlink()
            else:
                write(root, {name: text})
        head = commit(root, "broken")
        with pytest.raises(ValueError, match=message):
            B.validate_ordinary_head(root, head)
        write(root, {"pyproject.toml": project("0.10.0"), "release/advertised.toml": ADVERTISED})
        B.validate_ordinary_head(root, commit(root, "restored"))


@pytest.mark.parametrize("head, error", [("R", "only through the release bridge's pr stage"), ("B", "GitHub token missing")])
def test_ordinary_bridge_refuses_a_release_head_before_any_github_read(good, tmp_path, monkeypatch, head, error):
    trusted = git(good["root"], "rev-parse", "HEAD")
    for key, value in dict(GITHUB_EVENT_NAME="workflow_dispatch", GITHUB_REPOSITORY=B.REPOSITORY,
                           GITHUB_REPOSITORY_OWNER="taipei49314", GITHUB_ACTOR="taipei49314",
                           GITHUB_TRIGGERING_ACTOR="taipei49314", GITHUB_SHA=trusted, GITHUB_WORKFLOW_SHA=trusted,
                           GITHUB_WORKFLOW_REF=B.REPOSITORY + "/.github/workflows/quality-candidate-intake.yml@refs/heads/main").items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    output = tmp_path / "report.json"
    assert B.main(["verify", "--receipt-root", str(good["root"] / "receipt"), "--source-root", str(good["root"]),
                   "--trusted-root", str(good["root"]), "--manifest-sha256", "0" * 64, "--collector-source-sha", trusted,
                   "--receipt-commit", trusted, "--trusted-workflow-sha", trusted, "--head", good[head],
                   "--base", good["B"], "--pr", "1", "--output", str(output)]) == 1
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "failed" and error in report["error"]
    entry = function(ast.parse((ROOT / "tools/pju_receipt_bridge.py").read_text(encoding="utf-8")), "main")
    assert calls(entry, "validate_ordinary_head")[0].lineno < calls(entry, "GitHub")[0].lineno

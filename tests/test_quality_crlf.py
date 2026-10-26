"""Quality policy comparison uses the same CRLF boundary as source digests."""
import datetime
import json
import subprocess
from types import SimpleNamespace

import pytest

from checkwash.quality.cli import run
from checkwash.quality.engine import analyze
from checkwash.quality.model import ALLOW_PATH, POLICY_PATH
from checkwash.quality.profiles import available
from checkwash.quality.snapshot import MappingSnapshot

TODAY = datetime.date(2026, 10, 26)
VERSION_PATH = "tool-version.txt"


def files():
    profile = next(p for p in available().values() if p["tool"] == "coverage")
    policy = f'''schema_version=1
mode="enforce"
[[targets]]
id="main"
tool="coverage"
root="."
config="pyproject.toml"
profile="{profile['id']}"
paths=["src/"]
version_files=["{VERSION_PATH}"]
'''.encode()
    return {POLICY_PATH: policy, ALLOW_PATH: b"allow=[]\n",
            VERSION_PATH: b"coverage==7.6.1\n",
            "pyproject.toml": b"[tool.coverage.report]\nfail_under=85\n",
            "src/code.py": b"value = 1\n"}


def scan(left, right):
    return analyze(MappingSnapshot(left), MappingSnapshot(right), today=TODAY)


@pytest.mark.parametrize("path", [POLICY_PATH, ALLOW_PATH, VERSION_PATH])
@pytest.mark.parametrize("reverse", [False, True])
def test_crlf_only_policy_allow_and_version_sources_are_unchanged(path, reverse):
    left = files()
    right = {**left, path: left[path].replace(b"\n", b"\r\n")}
    expected = scan(left, left)
    actual = scan(right, left) if reverse else scan(left, right)
    assert actual == expected
    assert actual[1] == 0 and actual[0]["findings"] == []


@pytest.mark.parametrize("path", [POLICY_PATH, ALLOW_PATH])
@pytest.mark.parametrize("edit", ["comment", "order"])
def test_real_policy_byte_edits_are_still_critical(path, edit):
    left = files()
    original = left[path]
    if edit == "comment":
        changed = original + b"# reviewed text changed\n"
    elif edit == "order":
        # The policy can retain its parsed meaning without retaining its bytes.
        changed = (original.replace(b'schema_version=1\nmode="enforce"',
                                    b'mode="enforce"\nschema_version=1')
                   if path == POLICY_PATH else b"\n" + original)
    payload, code = scan(left, {**left, path: changed})
    assert code == 1
    findings = [f for f in payload["findings"] if f["rule"] == "QW_POLICY_CHANGED"]
    assert len(findings) == 1 and findings[0]["severity"] == "critical"


@pytest.mark.parametrize("path", [POLICY_PATH, ALLOW_PATH, VERSION_PATH])
@pytest.mark.parametrize("addition", [False, True])
def test_absent_and_present_sources_remain_distinct(path, addition):
    present = files()
    absent = {p: data for p, data in present.items() if p != path}
    left, right = (absent, present) if addition else (present, absent)
    payload, code = scan(left, right)
    assert not any(d["code"] == "INTERNAL_ERROR" for d in payload["diagnostics"])
    if path == VERSION_PATH:
        assert code == 2
        assert any(d["code"] == "TOOL_VERSION_UNRESOLVED" for d in payload["diagnostics"])
    else:
        findings = [f for f in payload["findings"] if f["rule"] == "QW_POLICY_CHANGED"]
        assert len(findings) == 1 and findings[0]["severity"] == "critical"


def test_real_version_change_is_still_unresolved():
    left = files()
    payload, code = scan(left, {**left, VERSION_PATH: b"coverage==7.6.2\r\n"})
    assert code == 2 and payload["verdict"] == "incomplete"
    assert any(d["code"] == "TOOL_VERSION_UNRESOLVED" for d in payload["diagnostics"])


def test_lone_carriage_return_in_version_source_is_not_normalized():
    left = files()
    payload, code = scan(left, {**left, VERSION_PATH: left[VERSION_PATH] + b"\r"})
    assert code == 2
    assert any(d["code"] == "TOOL_VERSION_UNRESOLVED" for d in payload["diagnostics"])


def test_crlf_keeps_real_weakening_fingerprint_and_payload():
    left = files()
    right = {**left, "pyproject.toml": b"[tool.coverage.report]\nfail_under=50\n"}
    expected, code = scan(left, right)
    crlf_right = {p: data.replace(b"\n", b"\r\n") for p, data in right.items()}
    actual, actual_code = scan(left, crlf_right)
    assert code == actual_code == 1
    assert actual == expected
    assert [f["rule"] for f in actual["findings"]] == ["QW_THRESHOLD_LOWERED"]
    assert actual["findings"][0]["fingerprint"] == expected["findings"][0]["fingerprint"]


def test_existing_base_side_exemption_keeps_matching_with_crlf_sources():
    left = files()
    right = {**left, "pyproject.toml": b"[tool.coverage.report]\nfail_under=50\n"}
    finding = scan(left, right)[0]["findings"][0]
    exemption = f'''[[allow]]
fingerprint="{finding['fingerprint']}"
rule="QW_THRESHOLD_LOWERED"
target_id="main"
reason="Reviewed exact threshold change"
author="regression-fixture"
created="2026-10-25"
expires="2026-11-25"
'''.encode()
    left[ALLOW_PATH] = right[ALLOW_PATH] = exemption
    expected, code = scan(left, right)
    crlf_left = {p: data.replace(b"\n", b"\r\n") for p, data in left.items()}
    actual, actual_code = scan(crlf_left, right)
    assert code == actual_code == 0
    assert actual == expected
    assert len(actual["findings"]) == 1 and actual["findings"][0]["allowlisted"]
    assert actual["findings"][0]["fingerprint"] == finding["fingerprint"]


def test_git_worktree_crlf_matches_range_and_detects_real_policy_edit(tmp_path):
    def git(*args):
        return subprocess.run(["git", "-c", "core.hooksPath=", *args], cwd=tmp_path,
                              check=True, capture_output=True).stdout

    git("init", "-q")
    git("config", "user.name", "Quality CRLF regression")
    git("config", "user.email", "quality-crlf@example.invalid")
    git("config", "core.autocrlf", "true")
    for path, data in files().items():
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    git("add", ".")
    git("commit", "-qm", "base")
    for path, data in files().items():
        (tmp_path / path).write_bytes(data.replace(b"\n", b"\r\n"))
    git("add", ".")
    assert git("status", "--porcelain") == b""
    assert b"\r\n" in (tmp_path / POLICY_PATH).read_bytes()
    assert b"\r\n" not in git("show", f"HEAD:{POLICY_PATH}")
    args = SimpleNamespace(range="HEAD..HEAD", rule=None, repo=str(tmp_path), format="json")
    range_text, range_code = run(args, TODAY)
    args.range = None
    worktree_text, worktree_code = run(args, TODAY)
    range_payload, worktree_payload = json.loads(range_text), json.loads(worktree_text)
    assert range_code == worktree_code == 0
    assert range_payload["findings"] == worktree_payload["findings"] == []
    assert range_payload["analysis_status"] == worktree_payload["analysis_status"] == "complete"
    policy = tmp_path / POLICY_PATH
    policy.write_bytes(policy.read_bytes() + b"# real policy edit\r\n")
    changed_text, changed_code = run(args, TODAY)
    changed = json.loads(changed_text)
    assert changed_code == 1
    assert [(f["rule"], f["severity"]) for f in changed["findings"]] == [("QW_POLICY_CHANGED", "critical")]

"""Issue #454: unread (oversized) sides named in json, sarif and term output.

Since #448, `check` carries a changed side over the 1,000,000-byte source
limit unread when no detector must read it, sets its whole change aside and
still gives a verdict. Only a stderr note named the side, so a consumer of the
machine output could not tell a pass that never read a file from one that
read every file.

Ruling B (2026-10-18): `--format json` gains an optional `unread` key, one
entry per side with exactly `path`, `side`, `size` and `limit`, sorted by
path, then side, and omitted when empty. `--format sarif` names each side as
a `warning` tool execution notification, never a result. The term report
adds a `! ` line per side and, when there is no finding, the "analysis
incomplete" head. hook-json and `--emit-ir` keep their bytes, and the skipped
root lockfile stays a stderr note. Exit codes, severities, rule ids and
fingerprints are unchanged.

Large files are generated here, never committed.
"""
from dataclasses import dataclass
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import quote

import pytest

from checkwash.change import UnreadSide
from checkwash.findings import Finding
from checkwash.frontends.javascript.coverage import CoverageGap
from checkwash.ir.model import IR
from checkwash.report.context import ReportContext
from checkwash.report.jsonout import findings_to_json
from checkwash.report.sarif import findings_to_sarif
from checkwash.report.term import render
from checkwash.report.unread import unread_entries, unread_entry

LIMIT = 1_000_000
INCOMPLETE = "checkwash: analysis incomplete; no known tampering pattern detected"
NOTE = "not read, over the source byte limit"
ENVELOPE = {"checkwash_findings_version", "run", "findings", "summary", "skipped_files", "config_errors", "verdict"}
BILLING = b"def compute_invoice_total(items):\n    return sum(items)\n"
TEST = (b"from billing import compute_invoice_total\n\n\n"
        b"def test_invoice_total():\n"
        b"    total = compute_invoice_total([10.5, 94.8])\n"
        b"    assert total == 105.3\n")
WEAKENED = TEST.replace(b"assert total == 105.3", b"assert total > 0")
ENV = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
       "PYTHONUTF8": "1", "GREENWASH_TODAY": "2026-10-19", "NO_COLOR": "1"}


def blob(size, seed):
    """`size` bytes of hex text, distinct per seed (as in test_issue415)."""
    body = hashlib.shake_256(seed.encode()).hexdigest((size + 1) // 2).encode()
    return body[:size - 1] + b"\n"


def side(path, name, size=LIMIT + 1):
    return UnreadSide(path, name, size, LIMIT)


def entry(path, name, size=LIMIT + 1):
    return {"path": path, "side": name, "size": size, "limit": LIMIT}


def described(path, name, size=LIMIT + 1):
    return f"{path} ({name}, {size} > {LIMIT} bytes)"


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True).stdout


def _write(repo, files):
    for path, data in files.items():
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_bytes(data)


def _commit(repo, message="head"):
    git(repo, "add", "-A")
    git(repo, "commit", "-m", message)


def _repo(tmp_path, extra=None):
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "config", "user.name", "checkwash-test")
    git(tmp_path, "config", "user.email", "test@example.invalid")
    git(tmp_path, "config", "commit.gpgsign", "false")
    git(tmp_path, "config", "core.autocrlf", "false")
    _write(tmp_path, {"billing.py": BILLING, "tests/test_billing.py": TEST, **(extra or {})})
    _commit(tmp_path, "base")
    return tmp_path


def _check(repo, *args):
    result = subprocess.run([sys.executable, "-m", "checkwash", "check", *args, "--repo", str(repo)],
                            env=ENV, capture_output=True, timeout=120)
    return result.returncode, result.stdout.decode("utf-8"), result.stderr.decode("utf-8")


def _notes(stderr):
    return [line for line in stderr.splitlines() if NOTE in line]


def _matched(payload):
    """The stderr notes the payload's entries stand for, one to one."""
    return [f"checkwash: {UnreadSide(**item).note()}" for item in payload["unread"]]


def _render(findings=(), verdict="pass", **kwargs):
    # A StringIO has no encoding, so the report uses its ASCII symbols.
    return render(IR(base="BASE", head="HEAD"), list(findings), verdict, "high", stream=io.StringIO(),
                  **kwargs).splitlines()


# --- the writers -----------------------------------------------------------------------------------

@dataclass(frozen=True)
class _Prefixed(UnreadSide):
    """A side with a field beyond the note's four, as #455 stores a bounded prefix."""

    prefix: bytes = b"#!/bin/sh\n"


@pytest.mark.parametrize("kind", [UnreadSide, _Prefixed], ids=["plain", "with_prefix"])
def test_an_entry_has_exactly_the_four_keys_of_the_note(kind):
    # An explicit projection: `to_jsonable` would write the prefix, and its
    # bytes would not even serialize.
    unread = kind("bin/tool.dat", "head", LIMIT + 1, LIMIT)
    expected = entry("bin/tool.dat", "head")
    assert unread_entry(unread) == expected
    ir = IR(base="BASE", head="HEAD")
    assert json.loads(findings_to_json(ir, [], "pass", unread=[unread]))["unread"] == [expected]
    run, = json.loads(findings_to_sarif(ir, [], unread=[unread]))["runs"]
    notification, = run["invocations"][0]["toolExecutionNotifications"]
    assert notification["properties"] == {f"checkwash.{key}": value for key, value in expected.items()}


def test_every_writer_sorts_by_path_then_side_whatever_the_diff_order():
    # Range mode lists changes in Git's order, worktree mode in status order
    # plus rename pairing: neither decides the order of the output.
    sides = [side("data/b.csv", "head"), side("assets/z.png", "worktree"),
             side("data/b.csv", "base"), side("assets/a.png", "head")]
    order = [("assets/a.png", "head"), ("assets/z.png", "worktree"), ("data/b.csv", "base"), ("data/b.csv", "head")]
    ir = IR(base="BASE", head="HEAD")
    payload = json.loads(findings_to_json(ir, [], "pass", unread=sides))
    assert [(item["path"], item["side"]) for item in payload["unread"]] == order
    assert unread_entries(reversed(sides)) == payload["unread"]
    run, = json.loads(findings_to_sarif(ir, [], unread=sides))["runs"]
    assert [(n["properties"]["checkwash.path"], n["properties"]["checkwash.side"])
            for n in run["invocations"][0]["toolExecutionNotifications"]] == order
    lines = _render(unread=sides)
    assert [line for line in lines[1:] if line.startswith("! ")] == ["! " + side(*pair).note() for pair in order]


def test_no_unread_side_leaves_the_envelope_and_the_invocation_as_they_were():
    # The key is omitted, not empty, and no invocation is built for nothing.
    ir = IR(base="BASE", head="HEAD")
    assert set(json.loads(findings_to_json(ir, [], "pass", unread=[]))) == ENVELOPE
    run, = json.loads(findings_to_sarif(ir, [], ReportContext(), unread=[]))["runs"]
    assert "invocations" not in run
    gap = CoverageGap("tests/a.test.mjs", "after", 2, 3, "assert.match", "not represented")
    run, = json.loads(findings_to_sarif(ir, [], ReportContext(coverage_gaps=[gap]), unread=[]))["runs"]
    assert run["invocations"] == [{"executionSuccessful": True, "toolExecutionNotifications": [{
        "level": "warning",
        "message": {"text": gap.message()},
        "properties": {"checkwash.path": "tests/a.test.mjs", "checkwash.side": "after",
                       "checkwash.line": 2, "checkwash.column": 3},
        "locations": [{"physicalLocation": {"artifactLocation": {"uri": "tests/a.test.mjs"},
                                            "region": {"startLine": 2}}}],
    }]}]
    lines = _render(unread=[])
    assert lines[0].endswith("checkwash: no known tampering pattern detected")
    assert "analysis incomplete" not in lines[0]
    assert not [line for line in lines[1:] if line.startswith("! ")]


def test_sarif_keeps_coverage_gaps_and_unread_sides_in_one_invocation():
    ir = IR(base="BASE", head="HEAD")
    gap = CoverageGap("web/total.test.mjs", "before", 4, 1, "assert.match", "not represented")
    sides = [side("報表/總額.csv", "worktree"), side("data/old.csv", "base"), side("data/moved.csv", "head")]
    run, = json.loads(findings_to_sarif(ir, [], ReportContext(coverage_gaps=[gap]), unread=sides))["runs"]
    assert run["results"] == []
    invocation, = run["invocations"]
    assert invocation["executionSuccessful"] is True
    # The coverage gaps first, then the unread sides by path, then side.
    gap_note, moved, old, report = invocation["toolExecutionNotifications"]
    assert gap_note["message"]["text"] == gap.message()
    assert moved == {
        "level": "warning",
        "message": {"text": side("data/moved.csv", "head").note()},
        "properties": {"checkwash.path": "data/moved.csv", "checkwash.side": "head",
                       "checkwash.size": LIMIT + 1, "checkwash.limit": LIMIT},
        "locations": [{"physicalLocation": {"artifactLocation": {"uri": "data/moved.csv"}}}],
    }
    # A base side is no file in the checked-out tree: no location.
    assert old == {
        "level": "warning",
        "message": {"text": side("data/old.csv", "base").note()},
        "properties": {"checkwash.path": "data/old.csv", "checkwash.side": "base",
                       "checkwash.size": LIMIT + 1, "checkwash.limit": LIMIT},
    }
    assert report["properties"]["checkwash.path"] == "報表/總額.csv"
    assert report["locations"] == [{"physicalLocation": {"artifactLocation": {"uri": quote("報表/總額.csv", safe="/")}}}]
    assert report["message"]["text"] == f"{NOTE}: {described('報表/總額.csv', 'worktree')}; it earns no repair evidence"


TERM_FINDINGS = {
    # name: (findings, verdict); "no finding" means none visible and none allowlisted.
    "none": ([], "pass"),
    "visible": ([Finding("ASSERT_WEAKENED", "high", "weakened", "tests/test_x.py", "test_x")], "block"),
    "allowlisted": ([Finding("ASSERT_WEAKENED", "high", "weakened", "tests/test_x.py", "test_x",
                             allowlisted=True)], "pass"),
    "below_fail_on": ([Finding("ASSERT_WEAKENED", "warn", "weakened", "tests/test_x.py", "test_x")], "pass"),
}


@pytest.mark.parametrize("case", sorted(TERM_FINDINGS))
def test_the_term_head_says_incomplete_only_when_there_is_no_finding(case):
    findings, verdict = TERM_FINDINGS[case]
    unread = side("assets/logo.png", "head", 1_500_000)
    lines = _render(findings, verdict, unread=[unread])
    if case == "none":
        assert lines[0].endswith(INCOMPLETE)
    else:
        assert lines[0] == _render(findings, verdict)[0]
        assert "analysis incomplete" not in lines[0]
    # Every run shows the side.
    assert "! " + unread.note() in lines[1:]


def test_the_term_lines_follow_config_errors_and_coverage_gaps():
    gap = CoverageGap("web/total.test.mjs", "after", 4, 1, "assert.match", "not represented")
    unread = side("assets/logo.png", "head", 1_500_000)
    lines = _render(errors=["a config warning"], context=ReportContext(coverage_gaps=[gap]), unread=[unread])
    assert lines[0].endswith(INCOMPLETE)
    assert [line for line in lines[1:] if line.startswith("! ")] == [
        "! a config warning", "! " + gap.message(), "! " + unread.note()]


# --- the CLI ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("size", [LIMIT, LIMIT + 1, 1_500_000], ids=["at_the_limit", "one_byte_over", "issue_example"])
def test_a_range_names_an_oversized_image_beside_a_weakened_test(tmp_path, size):
    repo = _repo(tmp_path)
    _write(repo, {"assets/logo.png": blob(size, "logo"), "tests/test_billing.py": WEAKENED})
    _commit(repo)
    code, stdout, stderr = _check(repo, "HEAD~1..HEAD", "--format", "json")
    assert "engine error" not in stderr, stderr
    payload = json.loads(stdout)
    if size == LIMIT:
        # Read, so not listed: the key is omitted, not empty.
        assert "unread" not in payload
        assert _notes(stderr) == []
        return
    assert payload["unread"] == [entry("assets/logo.png", "head", size)]
    # The verdict and finding are #415's: the side earns no evidence (#419).
    assert (code, payload["verdict"]) == (1, "block")
    weakened = [f for f in payload["findings"] if f["rule"] == "ASSERT_WEAKENED"]
    assert [(f["severity"], "NO_PROD_CHANGE_IN_DIFF" in f["escalators"]) for f in weakened] == [("high", True)]
    assert _notes(stderr) == _matched(payload)


def test_sarif_names_the_image_as_a_notification_not_a_result(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, {"assets/logo.png": blob(1_500_000, "logo"), "tests/test_billing.py": WEAKENED})
    _commit(repo)
    code, stdout, stderr = _check(repo, "HEAD~1..HEAD", "--format", "sarif")
    assert code == 1, stderr
    run, = json.loads(stdout)["runs"]
    assert "ASSERT_WEAKENED" in [result["ruleId"] for result in run["results"]]
    assert "assets/logo.png" not in [result["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
                                     for result in run["results"]]
    assert run["invocations"] == [{"executionSuccessful": True, "toolExecutionNotifications": [{
        "level": "warning",
        "message": {"text": side("assets/logo.png", "head", 1_500_000).note()},
        "properties": {"checkwash.path": "assets/logo.png", "checkwash.side": "head",
                       "checkwash.size": 1_500_000, "checkwash.limit": LIMIT},
        "locations": [{"physicalLocation": {"artifactLocation": {"uri": "assets/logo.png"}}}],
    }]}]


@pytest.mark.parametrize("findings", [False, True], ids=["no_findings", "findings"])
def test_the_term_report_names_the_unread_side(tmp_path, findings):
    repo = _repo(tmp_path)
    _write(repo, {"assets/logo.png": blob(1_500_000, "logo")})
    if findings:
        _write(repo, {"tests/test_billing.py": WEAKENED})
    _commit(repo)
    code, stdout, stderr = _check(repo, "HEAD~1..HEAD")
    assert "engine error" not in stderr, stderr
    lines = stdout.splitlines()
    unread = side("assets/logo.png", "head", 1_500_000)
    if findings:
        assert code == 1
        assert "finding(s) at or above high" in lines[0] and "blocking" in lines[0]
        assert "analysis incomplete" not in lines[0]
    else:
        assert code == 0
        assert lines[0].endswith(INCOMPLETE)
    assert "! " + unread.note() in lines
    assert _notes(stderr) == [f"checkwash: {unread.note()}"]


@pytest.mark.parametrize("mode", ["range", "worktree"])
def test_each_kind_of_unread_side_gives_its_entries(tmp_path, mode):
    repo = _repo(tmp_path, {"data/old.csv": blob(LIMIT + 1, "old"), "data/gone.csv": blob(LIMIT + 1, "gone"),
                            "data/big.csv": blob(LIMIT + 1, "big")})
    git(repo, "mv", "data/old.csv", "data/moved.csv")
    (repo / "data" / "gone.csv").unlink()
    _write(repo, {"data/big.csv": blob(LIMIT + 2, "bigger"), "assets/new.csv": blob(LIMIT + 1, "new")})
    if mode == "range":
        _commit(repo)
        code, stdout, stderr = _check(repo, "HEAD~1..HEAD", "--format", "json")
        new = "head"
    else:
        # Untracked, unstaged and staged at once.
        code, stdout, stderr = _check(repo, "--format", "json")
        new = "worktree"
    assert code in (0, 1) and "engine error" not in stderr, stderr
    payload = json.loads(stdout)
    # An addition, both sides over the limit, a deletion and a rename. Range
    # mode holds the rename as one change, worktree mode as an unpaired
    # deletion and addition; either way its sides are these two.
    assert payload["unread"] == [
        entry("assets/new.csv", new),
        entry("data/big.csv", "base"),
        entry("data/big.csv", new, LIMIT + 2),
        entry("data/gone.csv", "base"),
        entry("data/moved.csv", new),
        entry("data/old.csv", "base"),
    ]
    # The notes keep the diff's order; as a set they are the entries.
    assert sorted(_notes(stderr)) == sorted(_matched(payload))


@pytest.mark.parametrize("name", ["poetry.lock", "uv.lock"])
def test_a_skipped_root_lockfile_is_not_listed(tmp_path, name):
    # Read from the base on every run, changed or not: not a changed side set
    # aside with its change, so it stays a stderr note (ruling Q4).
    repo = _repo(tmp_path, {name: blob(1_200_000, name)})
    _write(repo, {"tests/test_billing.py": TEST + b"# reviewed\n"})
    _commit(repo)
    code, stdout, stderr = _check(repo, "HEAD~1..HEAD", "--format", "json")
    assert code == 0, stderr
    assert "unread" not in json.loads(stdout)
    assert (f"checkwash: skipped {described(name, 'base', 1_200_000)}: over the source byte limit; "
            "the run continues without its declared modules") in stderr.splitlines()
    assert _notes(stderr) == []


@pytest.mark.parametrize("name", ["poetry.lock", "uv.lock"])
def test_a_changed_root_lockfile_lists_its_unread_side_beside_the_skip(tmp_path, name):
    # The skip is not listed, but a change the diff makes to that lockfile is
    # set aside like any other (no detector must read a lockfile), so its
    # side over the limit is an entry; listing the skip too would name it
    # twice (ruling Q4).
    repo = _repo(tmp_path, {name: blob(1_200_000, name)})
    _write(repo, {name: b"version = 1\n", "tests/test_billing.py": TEST + b"# reviewed\n"})
    _commit(repo)
    code, stdout, stderr = _check(repo, "HEAD~1..HEAD", "--format", "json")
    assert code == 0, stderr
    payload = json.loads(stdout)
    assert payload["unread"] == [entry(name, "base", 1_200_000)]
    assert (f"checkwash: skipped {described(name, 'base', 1_200_000)}: over the source byte limit; "
            "the run continues without its declared modules") in stderr.splitlines()
    assert _notes(stderr) == _matched(payload)


@pytest.mark.parametrize("case", ["hook_json_pass", "hook_json_block", "emit_ir"])
def test_hook_json_and_emit_ir_name_no_unread_side(tmp_path, case):
    # Neither output changes for an unread side (ruling Q6); only stderr
    # carries the note. (A run without the file is no byte-for-byte control:
    # an unread co-change can still change what the engine proves, #415.)
    repo = _repo(tmp_path)
    _write(repo, {"data/dump.csv": blob(1_500_000, "dump")})
    if case == "hook_json_block":
        _write(repo, {"tests/test_billing.py": WEAKENED})
    code, stdout, stderr = _check(repo, *(["--emit-ir"] if case == "emit_ir" else ["--format", "hook-json"]))
    assert code == 0, stderr
    assert _notes(stderr) == [f"checkwash: {side('data/dump.csv', 'worktree', 1_500_000).note()}"]
    assert "dump.csv" not in stdout
    payload = json.loads(stdout)
    if case == "hook_json_pass":
        # `{}` on a pass, as before #454; no systemMessage is added.
        assert stdout == "{}\n"
    elif case == "hook_json_block":
        assert set(payload) == {"decision", "reason"}
        assert payload["decision"] == "block" and "ASSERT_WEAKENED" in payload["reason"]
    else:
        # The IR dataclass's fields, and no IR entry for the set-aside change.
        assert set(payload) == {"base", "head", "files", "globals", "skipped_files", "version"}

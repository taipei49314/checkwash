"""All closed snapshot adapters use the same nonempty Python inventory."""

import datetime
import io
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from checkwash import demo
from checkwash.cases import Case, case_snapshot, case_to_changes
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.gitio.snapshot import GitSnapshot, WorkingTreeSnapshot, search_source_mapping
from test_benchmark_snapshot_adapters import WRAPPERS, _load, _write_tree
from test_cases_runner import test_case as _run_fixture
from test_conftest_targets import git
from test_subject_normalization import BEFORE, AFTER, PRODUCTION


EMITTER = _load("tools/emit_corpus.py")


def _case(padding=0):
    head = {"src/app/parse_bool.py": PRODUCTION.decode()}
    head.update({f"empty_{i}.py": "" for i in range(64)})
    head.update({f"docs/note_{i}.txt": "Documentation." for i in range(64)})
    head.update({f"module_{i}.py": "pass\n" for i in range(padding)})
    return Case(before={"tests/test_bool.py": BEFORE.decode()},
                after={"tests/test_bool.py": AFTER.decode()}, head=head)


def _source(case):
    sections = []
    for label, tree in [("before", case.before), ("after", case.after), ("head", case.head)]:
        sections.extend(f"=== {label}: {path} ===\n{data}" for path, data in tree.items())
    return "\n".join([*sections, "=== expect ===\n[]"])


def test_case_snapshot_contains_changed_added_and_removes_deleted_paths():
    case = Case(before={"old.py": "pass", "changed.py": "before"},
                after={"changed.py": "after", "new.py": "new"},
                head={"old.py": "stale", "changed.py": "stale", "unchanged.py": "same"})
    assert case_snapshot(case) == {"changed.py": b"after", "new.py": b"new", "unchanged.py": b"same"}


def test_ordinary_mapping_search_keeps_its_existing_content_behavior():
    mapping = {"empty.py": b"", "a.py": b"marker", "notes.txt": b"marker"}
    assert search_source_mapping(mapping, ["marker"]) == ["a.py", "notes.txt"]
    assert search_source_mapping(mapping, [""]) == ["a.py"]
    assert search_source_mapping(mapping, []) == []


def test_fixture_demo_and_emitter_ignore_empty_and_nonpython_inventory_padding(tmp_path, monkeypatch):
    case = _case()
    text = _source(case)
    fixture = tmp_path / "closed-normalization.gwcase"
    fixture.write_text(text, encoding="utf-8")
    _run_fixture(fixture)
    stream = io.StringIO()
    monkeypatch.setattr(demo, "_load_cases", lambda: [(fixture.name, text)])
    assert demo.run(stream) == 0
    assert "SUBJECT_NORMALIZED" not in stream.getvalue()
    output = []
    monkeypatch.setattr(EMITTER, "CASES", [fixture])
    monkeypatch.setattr(EMITTER, "_write", output.append)
    EMITTER.main()
    findings = json.loads(output[1])
    assert findings["verdict"] == "pass" and findings["findings"] == []


@pytest.mark.parametrize("wrapper", WRAPPERS)
def test_benchmark_inventory_ignores_empty_and_nonpython_padding(wrapper, tmp_path):
    case = _case()
    padding = {path: data.encode() for path, data in case.head.items() if not path.startswith("src/")}
    _write_tree(tmp_path / "before", {**padding, "tests/test_bool.py": BEFORE})
    _write_tree(tmp_path / "after", {**padding, "tests/test_bool.py": AFTER})
    _write_tree(tmp_path / "src", {"app/parse_bool.py": PRODUCTION})
    result = WRAPPERS[wrapper](tmp_path) if wrapper == "tamper" else WRAPPERS[wrapper](tmp_path / "before", tmp_path / "after", tmp_path / "src")
    assert result == ("pass", [])


@pytest.mark.parametrize("padding, expected", [(0, "pass"), (61, "pass"), (62, "block")])
def test_memory_git_and_worktree_inventory_have_identical_precision(tmp_path, padding, expected):
    case = _case(padding)
    snapshot = case_snapshot(case)
    memory = analyze(case_to_changes(case), Config(), Contract(), [], datetime.date(2026, 9, 6),
                     root_reader=snapshot.get, root_searcher=lambda needles: search_source_mapping(snapshot, needles))
    assert memory[2] == expected
    before = {**snapshot, "tests/test_bool.py": BEFORE}
    _write_tree(tmp_path, before)
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "config", "user.name", "test")
    git(tmp_path, "config", "user.email", "test@example.invalid")
    git(tmp_path, "config", "commit.gpgsign", "false")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-m", "before")
    (tmp_path / "tests/test_bool.py").write_bytes(AFTER)
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"), "PYTHONUTF8": "1"}
    for mode in ("worktree", "range"):
        args = []
        if mode == "range":
            git(tmp_path, "add", "tests/test_bool.py")
            git(tmp_path, "commit", "-m", "after")
            args = ["HEAD~1..HEAD"]
        result = subprocess.run([sys.executable, "-m", "checkwash", "check", *args, "--repo", str(tmp_path), "--format", "json"], env=env, capture_output=True, timeout=30)
        assert result.returncode == (0 if expected == "pass" else 1), result.stderr
        assert json.loads(result.stdout)["verdict"] == expected
    if padding < 62:
        want = search_source_mapping(snapshot, [""])
        assert sorted(GitSnapshot(tmp_path, "HEAD").search([""])) == want
        assert sorted(WorkingTreeSnapshot(tmp_path).search([""])) == want

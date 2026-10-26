"""D-178: task lookup uses the directory originally named by --repo.

Fixture source is only statically reviewed. No fixture test/Python is executed.
"""
import json
import os
import subprocess

import pytest

from checkwash.cli import main


FREEZE = b"---\ncheckwash:\n  oracle_freeze: true\n---\n"
LOOSE = b"---\ncheckwash:\n  oracle_freeze: false\n---\n"
TEST = b"from calc import calc\n\ndef test_calc():\n    assert calc(2) == 4\n"
FINGERPRINT = "ASSERT_WEAKENED/tests/test_calc.py/test_calc/v2:04f0f96c59052f24ac2eede4e0054b388b9433d93a8d6f3ca6d9b5a25d2fefde"


def _git(repo, *args):
    result = subprocess.run(["git", "-c", "core.fsmonitor=false", "-C", str(repo), *args],
                            check=True, capture_output=True, timeout=60)
    return result.stdout.decode("utf-8").strip()


def _write(repo, path, data):
    destination = repo / path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)


def _repository(tmp_path, root_task=FREEZE):
    repo, caller = tmp_path / "repository", tmp_path / "caller"
    repo.mkdir()
    caller.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    for key, value in (("user.name", "task authority control"),
                       ("user.email", "task@example.invalid"),
                       ("commit.gpgsign", "false"), ("core.autocrlf", "false")):
        _git(repo, "config", key, value)
    _write(repo, "calc.py", b"def calc(x):\n    return x * 2\n")
    _write(repo, "tests/test_calc.py", TEST)
    _write(repo, "TASK.md", root_task)
    _write(repo, "pkg/TASK.md", LOOSE)
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "BASE owns two distinct contracts")
    base = _git(repo, "rev-parse", "HEAD")
    _write(repo, "calc.py", b"def calc(x):\n    return x * 2 + 0\n")
    _write(repo, "tests/test_calc.py", TEST.replace(b"== 4", b"> 0"))
    # The HEAD contracts contradict BASE deliberately: neither governs itself.
    _write(repo, "TASK.md", LOOSE)
    _write(repo, "pkg/TASK.md", FREEZE)
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "static weakening with opposite HEAD contracts")
    head = _git(repo, "rev-parse", "HEAD")
    # The range keeps its after commit; the worktree compares BASE with the
    # same after bytes instead of accidentally reviewing a clean HEAD.
    _git(repo, "update-ref", "refs/heads/candidate", head)
    _git(repo, "update-ref", "refs/heads/main", base)
    _git(repo, "read-tree", base)
    _write(caller, "TASK.md", LOOSE)
    _write(caller, "LOCAL.md", LOOSE)
    _write(repo, "LOCAL.md", FREEZE)
    _write(repo, "pkg/LOCAL.md", FREEZE)
    return repo, caller, base, head


@pytest.fixture
def authority_repo(tmp_path):
    return _repository(tmp_path)


def _review(fixture, monkeypatch, capsys, cwd, given, task, mode="range", fmt="json"):
    repo, caller, base, head = fixture
    monkeypatch.chdir(cwd)
    args = ["check", *([base + ".." + head] if mode == "range" else []),
            "--task", task, "--format", fmt]
    if given is not None:
        args += ["--repo", str(given)]
    code = main(args)
    output = capsys.readouterr()
    payload = json.loads(output.out) if output.out else None
    return code, payload, output.err


def _assert_freeze(code, payload, frozen):
    assert code == (1 if frozen else 0)
    assert payload["verdict"] == ("block" if frozen else "pass")
    findings = [finding for finding in payload["findings"] if finding["rule"] == "ASSERT_WEAKENED"]
    assert len(findings) == 1
    assert findings[0]["fingerprint"] == FINGERPRINT
    assert ("ORACLE_FREEZE" in findings[0]["escalators"]) is frozen


@pytest.mark.parametrize("mode", ["range", "worktree"])
@pytest.mark.parametrize("shape,frozen", [
    ("external-root-relative", True),
    ("pkg-root-relative", True),
    ("root-pkg-relative", False),
    ("external-pkg-relative", False),
    ("external-root-absolute", True),
    ("external-pkg-absolute", False),
    ("pkg-relative-repo-parent", True),
    ("root-relative-repo-pkg", False),
    ("pkg-default-repo", False),
    ("pkg-parent-task", True),
])
def test_task_contract_binds_original_repo_not_cwd_or_reroot(authority_repo, monkeypatch, capsys, shape, frozen, mode):
    repo, caller, *_ = authority_repo
    mappings = {
        "external-root-relative": (caller, repo, "TASK.md"),
        "pkg-root-relative": (repo / "pkg", repo, "TASK.md"),
        "root-pkg-relative": (repo, repo / "pkg", "TASK.md"),
        "external-pkg-relative": (caller, repo / "pkg", "TASK.md"),
        "external-root-absolute": (caller, repo, str(repo / "TASK.md")),
        "external-pkg-absolute": (caller, repo / "pkg", str(repo / "pkg/TASK.md")),
        "pkg-relative-repo-parent": (repo / "pkg", "..", "TASK.md"),
        "root-relative-repo-pkg": (repo, "pkg", "TASK.md"),
        "pkg-default-repo": (repo / "pkg", None, "TASK.md"),
        "pkg-parent-task": (repo / "pkg", repo / "pkg", "../TASK.md"),
    }
    code, payload, stderr = _review(authority_repo, monkeypatch, capsys, *mappings[shape], mode=mode)
    _assert_freeze(code, payload, frozen)
    assert "working-tree copy" not in stderr
    assert "TASK path context" not in stderr


@pytest.mark.skipif(os.name != "nt", reason="native Windows address syntax")
@pytest.mark.parametrize("shape,frozen", [
    ("drive-relative-task", True), ("drive-relative-repo", False), ("root-relative-task", True),
])
def test_windows_addresses_use_native_join_against_original_repo(authority_repo, monkeypatch, capsys, shape, frozen):
    repo, caller, *_ = authority_repo
    assert repo.drive == caller.drive
    cases = {
        "drive-relative-task": (repo / "pkg", repo, repo.drive + "TASK.md"),
        "drive-relative-repo": (repo, repo.drive + "pkg", "TASK.md"),
        "root-relative-task": (caller, repo, str(repo / "TASK.md")[len(repo.drive):]),
    }
    code, payload, stderr = _review(authority_repo, monkeypatch, capsys, *cases[shape])
    _assert_freeze(code, payload, frozen)
    assert "working-tree copy" not in stderr


@pytest.mark.parametrize("fmt", ["json", "hook-json"])
@pytest.mark.parametrize("subdirectory", [False, True])
def test_genuine_absence_fallback_is_repo_bound_and_root_only(authority_repo, monkeypatch, capsys, fmt, subdirectory):
    repo, caller, *_ = authority_repo
    given = repo / "pkg" if subdirectory else repo
    code, payload, stderr = _review(authority_repo, monkeypatch, capsys, caller, given, "LOCAL.md", fmt=fmt)
    if subdirectory:
        assert code == (0 if fmt == "hook-json" else 2)
        assert "from a subdirectory only the base copy is read" in stderr
        assert "working-tree copy" not in stderr
        assert payload is None if fmt == "json" else "decision" not in payload
    else:
        assert code == (0 if fmt == "hook-json" else 1)
        assert stderr.count("working-tree copy") == 1
        if fmt == "hook-json":
            assert payload["decision"] == "block"
        else:
            _assert_freeze(code, payload, True)


@pytest.mark.parametrize("fmt", ["json", "hook-json"])
def test_root_case_alias_is_still_refused_from_external_cwd(authority_repo, monkeypatch, capsys, fmt):
    repo, caller, *_ = authority_repo
    code, payload, stderr = _review(authority_repo, monkeypatch, capsys, caller, repo, "task.md", fmt=fmt)
    assert code == (0 if fmt == "hook-json" else 2)
    assert "which the base tree holds only in another case, as TASK.md" in stderr
    assert "working-tree copy" not in stderr
    assert payload is None if fmt == "json" else "decision" not in payload


def test_repo_relative_scope_matches_same_explicit_absolute_base_contract(tmp_path, monkeypatch, capsys):
    scoped = b"---\ncheckwash:\n  oracle_freeze: true\n  scope:\n    allow:\n      - tests/**\n---\n"
    fixture = _repository(tmp_path, root_task=scoped)
    repo, caller, *_ = fixture
    relative = _review(fixture, monkeypatch, capsys, caller, repo, "TASK.md")
    absolute = _review(fixture, monkeypatch, capsys, caller, repo, str(repo / "TASK.md"))
    assert relative == absolute
    _assert_freeze(relative[0], relative[1], True)
    assert any(finding["rule"] == "SCOPE_DRIFT" for finding in relative[1]["findings"])

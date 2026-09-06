"""An inert source function does not prove the binding a test executes."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from checkwash.change import EngineError
from checkwash.frontends.python.snapshot_context import inert_test_execution_context
from checkwash.gitio.snapshot import GitSnapshot, WorkingTreeSnapshot
from test_subject_normalization import BEFORE, AFTER, SNAPSHOT, PRODUCTION, run
from test_conftest_targets import git


MUTATE = b'''import importlib
subject = importlib.import_module("app.parse_bool")
subject.parse_bool = lambda s: s in {"1", "true", "yes"}
'''


@pytest.mark.parametrize("path", ["__init__.py", "conftest.py", "tests/__init__.py", "tests/conftest.py", "tests/other/conftest.py", "tests/test_aaa.py"])
def test_startup_rebinding_cannot_borrow_production_source_proof(path):
    ir, findings, verdict = run(snapshot={**SNAPSHOT, path: MUTATE})
    assert verdict == "block"
    assert any(f.rule == "SUBJECT_NORMALIZED" for f in findings)
    assert ir.files[0].normalization_equivalent_pairs == ()


@pytest.mark.parametrize("source", [b"", b"# comment\n", b'"""Package docs."""\n', b"pass\n"])
def test_inert_startup_context_preserves_the_honest_proof(source):
    _, findings, verdict = run(snapshot={**SNAPSHOT, "tests/__init__.py": source, "conftest.py": source})
    assert verdict == "pass"
    assert findings == []


@pytest.mark.parametrize("source", [b"import custom_plugin\n", b'pytest_plugins = ["plugin"]\n', b"def pytest_configure():\n    mutate()\n", b"invalid ! syntax\n"])
def test_uncertain_conftest_execution_withholds_credit(source):
    assert run(snapshot={**SNAPSHOT, "tests/conftest.py": source})[2] == "block"


def test_all_ancestor_startup_paths_are_requested_from_strict_reader():
    requested = []

    def read(path):
        requested.append(path)
        return None

    assert inert_test_execution_context("tests/unit/test_bool.py", read, lambda needles: [])
    assert requested == [
        ".pytest.ini", ".pytest.toml", "__init__.py", "conftest.py", "pyproject.toml",
        "pytest.ini", "pytest.toml", "setup.cfg",
        "tests/.pytest.ini", "tests/.pytest.toml", "tests/__init__.py", "tests/conftest.py",
        "tests/pyproject.toml", "tests/pytest.ini", "tests/pytest.toml", "tests/setup.cfg", "tests/tox.ini",
        "tests/unit/.pytest.ini", "tests/unit/.pytest.toml", "tests/unit/__init__.py", "tests/unit/conftest.py",
        "tests/unit/pyproject.toml", "tests/unit/pytest.ini", "tests/unit/pytest.toml", "tests/unit/setup.cfg",
        "tests/unit/tox.ini", "tox.ini",
    ]


def test_failed_or_invalid_startup_reader_does_not_become_absence():
    def failed(path):
        raise EngineError("context unavailable")

    with pytest.raises(EngineError, match="context unavailable"):
        inert_test_execution_context("tests/test_bool.py", failed, lambda needles: [])
    with pytest.raises(EngineError, match="invalid source bytes"):
        inert_test_execution_context("tests/test_bool.py", lambda path: False, lambda needles: [])


def test_incomplete_inventory_withholds_optional_proof():
    assert not inert_test_execution_context("tests/test_bool.py", {}.get)
    assert not inert_test_execution_context("tests/test_bool.py", {}.get, lambda needles: [f"module_{i}.py" for i in range(64)])

    def failed(needles):
        raise EngineError("inventory unavailable")

    assert not inert_test_execution_context("tests/test_bool.py", {}.get, failed)


def test_sibling_test_package_initializer_is_part_of_execution_context():
    snapshot = {**SNAPSHOT, "tests/other/test_smoke.py": b"def test_smoke():\n    pass\n", "tests/other/__init__.py": MUTATE}
    assert run(snapshot=snapshot)[2] == "block"


@pytest.mark.parametrize("source", [
    b'def test_smoke():\n    assert "x".upper() == "X"\n',
    b'"""Padding tests."""\ndef test_smoke():\n    assert 1 + 1 == 2\n',
])
def test_closed_literal_sibling_tests_preserve_precision(source):
    assert run(snapshot={**SNAPSHOT, "tests/test_smoke.py": source})[2] == "pass"


@pytest.mark.parametrize("source", [
    b'import other\n',
    b'def test_mutate():\n    mutate()\n',
    b'def test_mutate(x=mutate()):\n    pass\n',
    b'@mutate\ndef test_smoke():\n    pass\n',
    b'def test_smoke():\n    assert (obj := custom()).ready\n',
])
def test_unproved_sibling_tests_withhold_precision(source):
    assert run(snapshot={**SNAPSHOT, "tests/test_smoke.py": source})[2] == "block"


def test_inventoried_source_disappearance_is_an_error():
    with pytest.raises(EngineError, match="inventoried source disappeared"):
        inert_test_execution_context("tests/test_bool.py", {}.get, lambda needles: ["tests/conftest.py"])


@pytest.mark.parametrize("path, source", [
    ("pytest.ini", b"[pytest]\npython_files = *.py\n"),
    (".pytest.ini", b"[pytest]\npython_functions = *\n"),
    ("tests/pytest.ini", b"[pytest]\npython_classes = *\n"),
    ("tox.ini", b"[pytest]\naddopts = -p custom_plugin\n"),
    ("setup.cfg", b"[tool:pytest]\npython_files = *.py\n"),
    ("pyproject.toml", b'[tool.pytest.ini_options]\npython_files = ["*.py"]\n'),
    ("pytest.toml", b'[pytest]\npython_files = ["*.py"]\n'),
    (".pytest.toml", b'[pytest]\npython_files = ["*.py"]\n'),
    ("pytest.ini", b"invalid config without a section\n"),
    ("pyproject.toml", b"invalid ! toml\n"),
])
def test_unproved_pytest_configuration_withholds_default_collection_proof(path, source):
    assert run(snapshot={**SNAPSHOT, path: source})[2] == "block"


@pytest.mark.parametrize("path, source", [
    ("pytest.ini", b"# no custom options\n[pytest]\n"),
    ("setup.cfg", b"[metadata]\nname = sample\n"),
    ("pyproject.toml", b'[project]\nname = "sample"\nversion = "0.1.0"\n'),
    ("pytest.toml", b"# empty config\n"),
])
def test_empty_pytest_options_and_nonpytest_metadata_preserve_the_proof(path, source):
    assert run(snapshot={**SNAPSHOT, path: source})[2] == "pass"


def test_git_and_worktree_empty_needle_inventory_agree_on_empty_sources(tmp_path):
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "config", "user.name", "test")
    git(tmp_path, "config", "user.email", "test@example.invalid")
    git(tmp_path, "config", "commit.gpgsign", "false")
    (tmp_path / "conftest.py").write_bytes(b"# no hooks\n")
    (tmp_path / "empty.py").write_bytes(b"")
    (tmp_path / "notes.txt").write_bytes(b"not a Python source\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-m", "snapshot")
    assert GitSnapshot(tmp_path, "HEAD").search([""]) == ["conftest.py"]
    assert WorkingTreeSnapshot(tmp_path).search([""]) == ["conftest.py"]


def test_inventory_includes_hidden_python_source_and_rejects_git_symlinks(tmp_path):
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "config", "user.name", "test")
    git(tmp_path, "config", "user.email", "test@example.invalid")
    git(tmp_path, "config", "commit.gpgsign", "false")
    (tmp_path / ".hidden").mkdir()
    (tmp_path / ".hidden/conftest.py").write_bytes(MUTATE)
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-m", "snapshot")
    assert GitSnapshot(tmp_path, "HEAD").search([""]) == [".hidden/conftest.py"]
    assert WorkingTreeSnapshot(tmp_path).search([""]) == [".hidden/conftest.py"]
    blob = subprocess.run(["git", "hash-object", "-w", "--stdin"], cwd=tmp_path,
                          input=b".hidden/conftest.py", capture_output=True, check=True).stdout.decode().strip()
    git(tmp_path, "update-index", "--add", "--cacheinfo", f"120000,{blob},tests/conftest.py")
    git(tmp_path, "commit", "-m", "symlink")
    with pytest.raises(EngineError, match="nonregular Python source"):
        GitSnapshot(tmp_path, "HEAD").search([""])


def test_exhausted_read_budget_keeps_the_original_finding(monkeypatch):
    monkeypatch.setattr("checkwash.frontends.python.normalization._MAX_READS", 0)
    ir, findings, verdict = run()
    assert verdict == "block"
    assert any(f.rule == "SUBJECT_NORMALIZED" for f in findings)
    assert ir.files[0].normalization_equivalent_pairs == ()


@pytest.mark.parametrize("startup", ["tests/__init__.py", "conftest.py", "tests/conftest.py", "tests/aaa/conftest.py", "tests/test_aaa.py"])
@pytest.mark.parametrize("mode", ["range", "worktree"])
def test_runtime_rebinding_red_to_green_does_not_earn_equivalence(tmp_path, startup, mode):
    (tmp_path / "src/app").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "src/app/parse_bool.py").write_bytes(PRODUCTION)
    startup_file = tmp_path / startup
    startup_file.parent.mkdir(parents=True, exist_ok=True)
    startup_file.write_bytes(MUTATE)
    if startup.startswith("tests/aaa/"):
        (tmp_path / "tests/aaa/test_smoke.py").write_text("def test_smoke():\n    pass\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n", encoding="utf-8")
    test = tmp_path / "tests/test_bool.py"
    test.write_bytes(BEFORE)
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "config", "user.name", "test")
    git(tmp_path, "config", "user.email", "test@example.invalid")
    git(tmp_path, "config", "commit.gpgsign", "false")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-m", "before")
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(tmp_path / "src"), str(Path(__file__).resolve().parents[1] / "src")]), "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    before = subprocess.run([sys.executable, "-m", "pytest", "-q", "tests"], cwd=tmp_path, env=env, capture_output=True, timeout=30)
    assert before.returncode == 1 and b"AssertionError: assert False is True" in before.stdout
    test.write_bytes(AFTER)
    after = subprocess.run([sys.executable, "-m", "pytest", "-q", "tests"], cwd=tmp_path, env=env, capture_output=True, timeout=30)
    assert after.returncode == 0 and b"passed" in after.stdout
    args = []
    if mode == "range":
        git(tmp_path, "add", "tests/test_bool.py")
        git(tmp_path, "commit", "-m", "normalized")
        args = ["HEAD~1..HEAD"]
    result = subprocess.run([sys.executable, "-m", "checkwash", "check", *args, "--repo", str(tmp_path), "--format", "json"], env=env, capture_output=True, timeout=30)
    assert result.returncode == 1, result.stderr
    report = json.loads(result.stdout)
    assert report["verdict"] == "block"
    assert any(f["rule"] == "SUBJECT_NORMALIZED" for f in report["findings"])


@pytest.mark.parametrize("mode", ["range", "worktree"])
def test_custom_collection_red_to_green_does_not_earn_equivalence(tmp_path, mode):
    # The custom filename is intentionally outside default collectable().
    # pytest imports it during collection before running test_bool.py.
    (tmp_path / "pytest.ini").write_text("[pytest]\npython_files = *.py\n", encoding="utf-8")
    test_runtime_rebinding_red_to_green_does_not_earn_equivalence(tmp_path, "tests/boot.py", mode)

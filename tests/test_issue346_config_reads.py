"""#346: which nested pytest configs the runtime-provider pass reads, and
refusals of a nonregular source that name the path."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from checkwash.change import EngineError, FileChange
from checkwash.config import Config
from checkwash.gitio import snapshot as snapshots
from checkwash.shadow import find_runtime_subject_shadows


NESTED = "requirements/pyproject.toml"


def git(repo, *args, data=None):
    result = subprocess.run(["git", "-C", str(repo), *args], input=data,
                            capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    return result.stdout


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "config", "user.name", "owned config reads")
    git(tmp_path, "config", "user.email", "config@example.invalid")
    git(tmp_path, "config", "commit.gpgsign", "false")
    git(tmp_path, "config", "core.autocrlf", "false")
    return tmp_path


def commit(repo, files, parent=None):
    """Write a tree from (mode, bytes) entries; no host symlinks are needed."""
    git(repo, "read-tree", "--empty")
    for path, (mode, data) in sorted(files.items()):
        oid = git(repo, "hash-object", "-w", "--stdin", data=data).decode("ascii").strip()
        git(repo, "update-index", "--add", "--cacheinfo", f"{mode},{oid},{path}")
    tree = git(repo, "write-tree").decode("ascii").strip()
    args = ["commit-tree", tree, *(["-p", parent] if parent else [])]
    revision = git(repo, *args, data=b"owned config tree\n").decode("ascii").strip()
    git(repo, "update-ref", "refs/heads/main", revision)
    return revision


def provider_tree(extra=None):
    sources = {
        "app/__init__.py": b"",
        "app/normalize.py": b"def normalize(value):\n    return value.lower()\n",
        "src/app/__init__.py": b"",
        "src/app/normalize.py": b"def normalize(value):\n    return value.strip()\n",
        "tests/test_normalize.py": (
            b"from app.normalize import normalize\n\n"
            b"def test_normalize():\n    assert normalize(' X ') == 'x'\n"
        ),
        "pytest.ini": b"[pytest]\npythonpath = . src\n",
        # A nested config under a directory with no test file.
        NESTED: b'[tool.pytest.ini_options]\npythonpath = ["elsewhere"]\n',
        "requirements/sync.py": b"VALUE = 1\n",
    }
    sources.update(extra or {})
    changes = [
        FileChange("app/__init__.py", "added", None, sources["app/__init__.py"]),
        FileChange("app/normalize.py", "added", None, sources["app/normalize.py"]),
        FileChange("pytest.ini", "modified", b"[pytest]\npythonpath = src\n", sources["pytest.ini"]),
    ]
    return sources, changes


def refusing_reader(sources, batches):
    """A head batch reader that records each batch it is asked for."""
    def read(paths):
        paths = list(paths)
        batches.append(paths)
        if NESTED in paths:
            # What GitSnapshot.read_many says for a symlink at that path.
            raise EngineError(f"strict snapshot batch cannot inspect nonregular source {NESTED} (a symlink)")
        return {path: sources.get(path) for path in paths}
    return read


def test_nested_config_under_a_directory_without_tests_is_not_read():
    sources, changes = provider_tree()
    batches = []
    hits = find_runtime_subject_shadows(
        changes,
        Config(),
        head_path_lister=lambda: sorted(sources),
        head_batch_reader=refusing_reader(sources, batches),
        head_searcher=lambda _needles: ["tests/test_normalize.py"],
    )
    assert [(hit.before_provider, hit.after_provider) for hit in hits] == [
        ("src/app/normalize.py", "app/normalize.py")
    ]
    requested = [path for batch in batches for path in batch]
    assert "tests/test_normalize.py" in requested
    assert NESTED not in requested


def test_nested_config_without_tests_is_still_read_when_a_run_names_it():
    runner = f"#!/bin/sh\npytest -c {NESTED} tests\n".encode()
    sources, changes = provider_tree({"scripts/test.sh": runner})
    batches = []
    with pytest.raises(EngineError, match=f"nonregular source {NESTED} \\(a symlink\\)"):
        find_runtime_subject_shadows(
            changes,
            Config(),
            head_path_lister=lambda: sorted(sources),
            head_batch_reader=refusing_reader(sources, batches),
            head_searcher=lambda _needles: ["tests/test_normalize.py"],
        )
    # The dormant config is not in the initial batch, which does hold the
    # runner that names it; it is read later, on its own, once the runner's
    # `-c` reaches it. Reading every config up front would refuse in the
    # first batch instead.
    assert len(batches) >= 2, batches
    assert "scripts/test.sh" in batches[0]
    assert NESTED not in batches[0]
    assert batches[-1] == [NESTED]


def test_git_batch_refusal_names_the_symlinked_path(repo):
    revision = commit(repo, {NESTED: ("120000", b"../pyproject.toml"),
                             "pyproject.toml": ("100644", b"[project]\nname='owned'\n")})
    with pytest.raises(EngineError) as caught:
        snapshots.GitSnapshot(repo, revision).read_many([NESTED, "pyproject.toml"])
    assert str(caught.value) == (
        "strict snapshot batch cannot inspect nonregular source requirements/pyproject.toml (a symlink)")


def test_git_python_inventory_refusal_names_the_symlinked_path(repo):
    revision = commit(repo, {"pkg/alias.py": ("120000", b"real.py"),
                             "pkg/real.py": ("100644", b"VALUE = 1\n")})
    with pytest.raises(EngineError) as caught:
        snapshots.GitSnapshot(repo, revision).search([""])
    assert str(caught.value) == (
        "strict snapshot inventory cannot inspect a nonregular Python source pkg/alias.py (a symlink)")


def test_working_tree_refusal_names_a_directory(tmp_path):
    (tmp_path / "configs" / "pytest.ini").mkdir(parents=True)
    with pytest.raises(EngineError) as caught:
        snapshots.WorkingTreeSnapshot(tmp_path).read("configs/pytest.ini")
    assert str(caught.value) == (
        "strict snapshot cannot inspect nonregular source configs/pytest.ini (a directory)")


def test_working_tree_batch_refusal_names_the_symlinked_path(tmp_path):
    (tmp_path / "pyproject.toml").write_bytes(b"[project]\nname='owned'\n")
    (tmp_path / "requirements").mkdir()
    try:
        (tmp_path / NESTED).symlink_to("../pyproject.toml")
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks unavailable: {exc}")
    with pytest.raises(EngineError) as caught:
        snapshots.WorkingTreeSnapshot(tmp_path).read_many([NESTED])
    assert str(caught.value) == (
        "strict snapshot batch cannot inspect nonregular source requirements/pyproject.toml (a symlink)")


def test_a_path_that_would_break_the_line_is_quoted():
    error = snapshots._nonregular("strict snapshot batch cannot inspect nonregular source",
                                  "a\nb.ini", b"120000")
    assert str(error) == "strict snapshot batch cannot inspect nonregular source 'a\\nb.ini' (a symlink)"
    assert "\n" not in str(error)


def test_cli_range_with_an_unchanged_nested_config_link_gives_a_verdict(repo):
    # Owned minimal analogue of the reported shape: an unchanged
    # requirements/pyproject.toml -> ../pyproject.toml link, and pytest's
    # settings moving from setup.cfg into a new pytest.ini. Before #346 the
    # strict batch refused the link and the check exited 2 with no verdict.
    before = {
        NESTED: ("120000", b"../pyproject.toml"),
        "pyproject.toml": ("100644", b"[project]\nname='owned'\nversion='0.0.0'\n"),
        "requirements/sync.py": ("100644", b"VALUE = 1\n"),
        "setup.cfg": ("100644", b"[metadata]\nname=owned\n\n[tool:pytest]\ntestpaths = tests\n"),
        "src/billing.py": ("100644", b"def total():\n    return 1\n"),
        "tests/test_total.py": ("100644", b"from billing import total\n\n"
                                          b"def test_total():\n    assert total() == 1\n"),
    }
    after = {**before,
             "setup.cfg": ("100644", b"[metadata]\nname=owned\n"),
             "pytest.ini": ("100644", b"[pytest]\ntestpaths = tests\n")}
    base = commit(repo, before)
    head = commit(repo, after, base)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    result = subprocess.run([sys.executable, "-m", "checkwash", "check", "--repo", str(repo),
                             f"{base}..{head}", "--format", "json"],
                            env=env, capture_output=True, timeout=60)
    assert result.returncode in (0, 1), (result.stdout, result.stderr)
    assert b"engine error" not in result.stderr.lower()
    assert json.loads(result.stdout)["verdict"] in {"pass", "warn", "block"}

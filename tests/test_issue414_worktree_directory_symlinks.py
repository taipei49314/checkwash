"""Issue #414: a directory symlink in the working tree is an opaque directory.

Without a range, `check` (the pre-commit and Claude Code Stop hooks) walks the
whole working tree. Any directory symlink in it, even one in a gitignored
`.venv` (`lib64 -> lib`) or pnpm's `node_modules`, used to stop the walk with
"strict snapshot inventory cannot follow directory symlinks", naming no path,
so every `.py` edit exited 2 with no verdict; hook-json printed nothing.

The inventory now lists such a link as its path with a trailing slash, as a
submodule is listed (#335), and never follows it. A run fails, naming the
path, only when a pass needs a fact from inside it: a read, an import that
resolves there, or a pytest collection that can reach it. pytest's default
norecursedirs keeps `.venv` and `node_modules` out of reach. In hook-json
mode an engine error exits 0 with a JSON warning that does not block the stop.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from checkwash.change import EngineError
from checkwash.gitio.snapshot import WorkingTreeSnapshot
from checkwash.opaque import SymlinkedDirectory, opaque_error, split_inventory

TOTAL = b"def total():\n    return 78.75\n"
TEST = b"from pkg import total\n\n\ndef test_total():\n    assert total() == 78.75\n"
REFUSAL = "strict snapshot inventory cannot follow directory symlink"


def _link(link, target):
    """A directory symlink, or a skip where the host cannot make one."""
    try:
        link.symlink_to(target, target_is_directory=True)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlinks unavailable: {exc}")


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True).stdout.decode().strip()


def _repo(tmp_path, files):
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "config", "user.name", "checkwash-test")
    git(tmp_path, "config", "user.email", "test@example.invalid")
    git(tmp_path, "config", "commit.gpgsign", "false")
    git(tmp_path, "config", "core.autocrlf", "false")
    for path, data in files.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_bytes(data)
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-m", "base")
    return tmp_path


def _check(repo, fmt):
    """`check` with no range: the working tree against HEAD, as the hooks run it."""
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
           "PYTHONUTF8": "1", "GREENWASH_TODAY": "2026-10-14", "NO_COLOR": "1"}
    result = subprocess.run([sys.executable, "-m", "checkwash", "check", "--repo", str(repo), "--format", fmt],
                            env=env, capture_output=True, timeout=60)
    return result.returncode, result.stdout.decode("utf-8"), result.stderr.decode("utf-8")


def _tree(root):
    (root / "real").mkdir()
    (root / "real" / "a.py").write_bytes(b"A = 1\n")
    (root / "top.py").write_bytes(b"")
    _link(root / "link", Path("real"))
    return WorkingTreeSnapshot(root)


# --- the snapshot ---------------------------------------------------------------------------------

def test_the_inventory_lists_a_directory_symlink_as_an_opaque_directory(tmp_path):
    paths = _tree(tmp_path).list_paths()
    assert paths == ["link/", "real/a.py", "top.py"]
    files, opaque = split_inventory(paths)
    assert files == ["real/a.py", "top.py"]
    assert opaque == ("link",)
    assert isinstance(opaque[0], SymlinkedDirectory)
    assert str(opaque_error(opaque[0], "pytest's collection can reach it")) == (
        f"{REFUSAL} link: pytest's collection can reach it")


def test_a_read_inside_a_directory_symlink_names_it(tmp_path):
    snapshot = _tree(tmp_path)
    assert snapshot.read("real/a.py") == b"A = 1\n"
    for read in (snapshot.read, lambda path: snapshot.read_many([path])):
        with pytest.raises(EngineError) as caught:
            read("link/a.py")
        assert str(caught.value) == f"{REFUSAL} link: link/a.py lies inside it"


def test_the_path_limit_refusal_names_where_the_walk_stopped(tmp_path, monkeypatch):
    # Ignored trees still count toward the limit; the refusal says where.
    monkeypatch.setattr("checkwash.gitio.snapshot.MAX_INVENTORY_PATHS", 2)
    for name in ("a.py", "b.py", "c.py"):
        (tmp_path / name).write_bytes(b"")
    with pytest.raises(EngineError) as caught:
        WorkingTreeSnapshot(tmp_path).list_paths()
    assert str(caught.value) == "strict snapshot inventory exceeds the path limit of 2 at c.py"


def test_searches_name_the_directory_symlink(tmp_path):
    snapshot = _tree(tmp_path)
    with pytest.raises(EngineError) as caught:
        snapshot.search([""])
    assert str(caught.value) == f"{REFUSAL} link: the Python inventory needs its sources"
    with pytest.raises(EngineError) as caught:
        snapshot.search(["A"])
    assert str(caught.value) == f"{REFUSAL} link: the importer search needs its sources"


# --- the issue's rows -----------------------------------------------------------------------------

def _venv(repo):
    packages = repo / ".venv" / "lib" / "python3.12" / "site-packages"
    packages.mkdir(parents=True)
    (packages / "six.py").write_bytes(b"VALUE = 1\n")
    _link(repo / ".venv" / "lib64", Path("lib"))


def _pnpm(repo):
    store = Path(".pnpm") / "left-pad@1.3.0" / "node_modules" / "left-pad"
    (repo / "node_modules" / store).mkdir(parents=True)
    (repo / "node_modules" / store / "index.js").write_bytes(b"module.exports = 1;\n")
    _link(repo / "node_modules" / "left-pad", store)


@pytest.mark.parametrize("fmt", ["term", "hook-json"])
@pytest.mark.parametrize("layout", [_venv, _pnpm], ids=["venv_lib64", "pnpm_node_modules"])
def test_an_unreachable_directory_symlink_gives_a_verdict(tmp_path, layout, fmt):
    repo = _repo(tmp_path, {".gitignore": b".venv/\nnode_modules/\n", "src/pkg/__init__.py": TOTAL,
                            "tests/test_total.py": TEST})
    layout(repo)
    (repo / "src" / "pkg" / "__init__.py").write_bytes(TOTAL.replace(b"78.75", b"round(78.75, 2)"))
    code, stdout, stderr = _check(repo, fmt)
    assert "engine error" not in stderr, stderr
    if fmt == "term":
        assert code in (0, 1), stderr
        assert "verdict=" in stdout
    else:
        assert code == 0, stderr
        assert "systemMessage" not in json.loads(stdout)


@pytest.mark.parametrize("fmt", ["term", "hook-json"])
def test_a_collection_that_reaches_a_directory_symlink_fails_closed_naming_it(tmp_path, fmt):
    # No testpaths: a bare pytest collects from the root, and no
    # norecursedirs pattern stops `linked`.
    repo = _repo(tmp_path, {".gitignore": b"linked\n", "setup.cfg": b"[tool:pytest]\naddopts = -ra\n",
                            "src/pkg/__init__.py": TOTAL, "tests/test_total.py": TEST})
    _link(repo / "linked", Path("src"))
    (repo / "setup.cfg").write_bytes(b"[tool:pytest]\naddopts = -ra --showlocals\n")
    code, stdout, stderr = _check(repo, fmt)
    refusal = f"{REFUSAL} linked: pytest's collection can reach it"
    assert refusal in stderr
    if fmt == "term":
        assert code == 2
    else:
        # The stop is not blocked: no decision, and the user sees why.
        assert code == 0, stderr
        payload = json.loads(stdout)
        assert set(payload) == {"systemMessage"}
        assert "not analysed" in payload["systemMessage"]
        assert refusal in payload["systemMessage"]


def test_a_blocking_config_error_does_not_block_the_stop(tmp_path):
    repo = _repo(tmp_path, {".checkwash/config.toml": b'[gate]\non_engine_error = "block"\n',
                            ".checkwash/allow.toml": b"[[allow]\n",
                            "src/pkg/__init__.py": TOTAL, "tests/test_total.py": TEST})
    (repo / "src" / "pkg" / "__init__.py").write_bytes(TOTAL.replace(b"78.75", b"round(78.75, 2)"))
    code, _stdout, stderr = _check(repo, "term")
    assert code == 2
    assert "allow.toml could not be parsed" in stderr
    code, stdout, stderr = _check(repo, "hook-json")
    assert code == 0, stderr
    payload = json.loads(stdout)
    assert set(payload) == {"systemMessage"}
    assert "not analysed" in payload["systemMessage"]
    assert "allow.toml could not be parsed" in payload["systemMessage"]

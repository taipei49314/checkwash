"""Explain outside worktree refusals without changing source admission."""
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

import pytest

from checkwash.change import EngineError
from checkwash.gitio.snapshot import WorkingTreeSnapshot


LOGICAL = "tests/alias/test_api.py"
BEFORE = b"from pkg import api\n\ndef test_api():\n    assert api() == 1\n"
AFTER = b"from pkg import api\n\ndef test_api():\n    assert api() > 0\n"
PROD = b"def api():\n    return 1\n"


def check_details(message, logical=LOGICAL, side="worktree"):
    assert "strict snapshot path leaves the repository" in message
    assert f"path={logical!r}" in message
    assert f"side={side!r}" in message
    assert "entry='worktree/read'" in message
    assert "repository-owned regular source" in message
    assert "committed bytes only" in message


def test_outside_read_names_the_logical_path_and_does_not_open_target(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_bytes(b"DO_NOT_DISCLOSE_OR_READ\n")
    snapshot = WorkingTreeSnapshot(repo)

    def forbidden_open(*args, **kwargs):
        pytest.fail("the refused external source was opened")

    monkeypatch.setattr(Path, "open", forbidden_open)
    with pytest.raises(EngineError) as caught:
        snapshot.read("../outside.py")
    check_details(str(caught.value), "../outside.py")
    assert str(outside) not in str(caught.value)
    assert "DO_NOT_DISCLOSE_OR_READ" not in str(caught.value)


def test_outside_absolute_input_does_not_disclose_the_external_path(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "private-target.py"
    outside.write_bytes(b"private bytes\n")
    with pytest.raises(EngineError) as caught:
        WorkingTreeSnapshot(repo).read(str(outside))
    check_details(str(caught.value), "<non-repository-relative path>")
    assert str(outside) not in str(caught.value)


def test_outside_diagnostic_escapes_logical_path_and_side(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    snapshot = WorkingTreeSnapshot(repo, side="worktree\n\x1b[31m")
    logical = "tests/line\nbreak\x1b[31m.py"
    lexical = snapshot.root / logical
    original = Path.resolve

    def resolve(path, *args, **kwargs):
        return tmp_path / "external-owned.py" if path == lexical else original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)
    monkeypatch.setattr(snapshot, "_symlinked_ancestor", lambda _path: None)
    with pytest.raises(EngineError) as caught:
        snapshot.read(logical)
    message = str(caught.value)
    check_details(message, logical, snapshot.side)
    assert "\n" not in message and "\x1b" not in message
    assert "\\n" in message and "\\x1b" in message


def test_repository_owned_regular_file_still_reads(tmp_path):
    (tmp_path / "source.py").write_bytes(PROD)
    assert WorkingTreeSnapshot(tmp_path).read("source.py") == PROD


def test_nonregular_admission_and_existing_reason_are_unchanged(tmp_path):
    (tmp_path / "source.py").mkdir()
    with pytest.raises(EngineError) as caught:
        WorkingTreeSnapshot(tmp_path).read("source.py")
    assert str(caught.value) == "strict snapshot cannot inspect nonregular source source.py (a directory)"


@pytest.fixture(scope="module")
def native_cases(tmp_path_factory):
    if os.name != "nt":
        pytest.skip("Windows native junction cases")
    owner = tmp_path_factory.mktemp("native-reader")
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0",
                "GIT_AUTHOR_NAME": "owned reader fixture", "GIT_AUTHOR_EMAIL": "reader@example.invalid",
                "GIT_COMMITTER_NAME": "owned reader fixture", "GIT_COMMITTER_EMAIL": "reader@example.invalid",
                "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z"})
    cases, junctions = {}, []
    try:
        for kind in ("inside", "outside", "regular"):
            repo = owner / kind
            repo.mkdir()

            def git(*args, data=None):
                return subprocess.run(["git", "-c", "core.hooksPath=nul", "-c", "core.autocrlf=false",
                                       "-c", "commit.gpgsign=false", *args], cwd=repo, env=env,
                                      input=data, capture_output=True, check=True, timeout=30).stdout

            git("init", "-q", "-b", "main")
            for path, data in (("pkg.py", PROD), (LOGICAL, BEFORE)):
                oid = git("hash-object", "-w", "--stdin", data=data).decode().strip()
                git("update-index", "--add", "--cacheinfo", f"100644,{oid},{path}")
            tree = git("write-tree").decode().strip()
            commit = git("commit-tree", tree, "-m", "owned static reader case").decode().strip()
            git("update-ref", "refs/heads/main", commit)
            (repo / "pkg.py").write_bytes(PROD)
            (repo / "tests").mkdir()
            alias = repo / "tests/alias"
            if kind == "regular":
                alias.mkdir()
                target = alias
            else:
                target = repo / "owned-target" if kind == "inside" else owner / "external-owned-target"
                target.mkdir()
                (target / "test_api.py").write_bytes(AFTER)
                if kind == "inside":
                    (repo / ".git/info/exclude").write_text("/owned-target/\n", encoding="utf-8")
                made = subprocess.run(["cmd", "/c", "mklink", "/J", str(alias), str(target)],
                                      env=env, capture_output=True, timeout=30)
                assert made.returncode == 0, repr(made.stderr)
                assert not alias.is_symlink()
                assert alias.lstat().st_reparse_tag == stat.IO_REPARSE_TAG_MOUNT_POINT
                junctions.append((alias, target))
            (target / "test_api.py").write_bytes(AFTER)
            index = git("ls-files", "--stage", "-z")
            status = git("status", "--porcelain", "-z", "--untracked-files=all", "--no-renames")
            assert status == b" M " + LOGICAL.encode() + b"\0"
            assert b"100644 " in index and LOGICAL.encode() in index
            (repo / ".git/reader-index.raw").write_bytes(index)
            (repo / ".git/reader-status.raw").write_bytes(status)
            cases[kind] = repo
        yield cases
    finally:
        for alias, target in junctions:
            # Verify both owned paths, then remove only the junction entry.
            absolute = Path(os.path.abspath(alias))
            assert absolute.is_relative_to(owner.resolve())
            assert alias.resolve(strict=True).is_relative_to(owner.resolve())
            assert target.resolve(strict=True).is_relative_to(owner.resolve())
            assert alias.lstat().st_reparse_tag == stat.IO_REPARSE_TAG_MOUNT_POINT
            before = (target / "test_api.py").read_bytes()
            alias.rmdir()
            assert (target / "test_api.py").read_bytes() == before


@pytest.mark.parametrize("kind", ("inside", "outside", "regular"))
@pytest.mark.parametrize("format", ("json", "hook-json"))
def test_native_junction_refusal_and_weakening_controls(native_cases, kind, format):
    repo = native_cases[kind]
    source = Path(__file__).resolve().parents[1] / "src"
    bootstrap = f"import sys;sys.path.insert(0,{str(source)!r});from checkwash.cli import main;raise SystemExit(main())"
    command = [sys.executable, "-I", "-B", "-X", "utf8", "-c", bootstrap,
               "check", "--repo", str(repo), "--format", format]
    result = subprocess.run(command, capture_output=True, timeout=60)
    raw = repo / ".git" / ("reader-" + format)
    raw.with_suffix(".stdout").write_bytes(result.stdout)
    raw.with_suffix(".stderr").write_bytes(result.stderr)
    raw.with_suffix(".meta.json").write_text(json.dumps({"command": command, "exit": result.returncode,
        "stdout_sha256": hashlib.sha256(result.stdout).hexdigest(),
        "stderr_sha256": hashlib.sha256(result.stderr).hexdigest()}, indent=2), encoding="utf-8")
    if kind == "outside":
        assert result.returncode == (2 if format == "json" else 0)
        check_details(result.stderr.decode("utf-8"))
        assert str(repo.parent / "external-owned-target") not in result.stderr.decode("utf-8")
        if format == "json":
            assert result.stdout == b""
        else:
            payload = json.loads(result.stdout)
            assert set(payload) == {"systemMessage"}
            assert "not analysed" in payload["systemMessage"]
            assert "decision" not in payload
    else:
        assert result.returncode == (1 if format == "json" else 0)
        assert result.stderr == b""
        payload = json.loads(result.stdout)
        if format == "json":
            assert payload["verdict"] == "block"
            assert [(f["rule"], f["severity"], f["path"], f["unit"]) for f in payload["findings"]] == [
                ("ASSERT_WEAKENED", "high", LOGICAL, "test_api")]
            assert payload["findings"][0]["fingerprint"] == (
                "ASSERT_WEAKENED/tests/alias/test_api.py/test_api/v2:"
                "9a27f17761c9a9d310ac9a4f194d6d80a67c640be4be5e1d17d97bef3619f399")
        else:
            assert payload["decision"] == "block"
            assert "ASSERT_WEAKENED" in payload["reason"]

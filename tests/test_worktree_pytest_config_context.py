"""Worktree pytest evidence uses strict regular reads and fresh analysis contexts."""
import hashlib
import json
from pathlib import Path
import stat
import subprocess
from types import SimpleNamespace

import pytest

from checkwash.change import EngineError, FileChange
from checkwash.cli import main
from checkwash.gitio import snapshot as snapshots


class BaseIdentity:
    def __init__(self, width=40):
        self.width = width

    def _rev(self):
        return "0" * self.width


class RegularSource:
    def __init__(self, files):
        self.files = dict(files)
        self.modes = {path: b"100644" for path in files}
        self.reads = []

    def list_paths(self):
        return sorted(self.files)

    def config_modes(self, paths):
        return {path: self.modes.get(path) for path in paths}

    def read_many(self, paths):
        self.reads.append(tuple(paths))
        return {path: self.files.get(path) for path in paths}


def view(source, changes=(), width=40):
    from checkwash.gitio.pytest_configs import WorktreePytestConfigs

    return WorktreePytestConfigs(source, BaseIdentity(width), changes)


def test_regular_config_context_retains_one_read_and_truthful_content_identity():
    data = b"[pytest]\naddopts=-k keep\n"
    source = RegularSource({"pytest.ini": data})
    context = view(source)
    first = context.read_config_many(["pytest.ini"])["pytest.ini"]
    source.files["pytest.ini"] = b"changed after captured read"
    assert context.read_config_many(["pytest.ini"])["pytest.ini"] is first
    assert source.reads == [("pytest.ini",)]
    assert first.data == data and first.revision == "worktree"
    assert first.path == first.target_path == "pytest.ini"
    assert first.mode == first.target_mode == b"100644" and first.link_bytes == 0
    assert first.oid == first.target_oid == hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest().encode()


def test_sha256_repository_identity_is_not_falsely_reported_as_sha1():
    data = b"[pytest]\n"
    record = view(RegularSource({"pytest.ini": data}), width=64).read_config_many(["pytest.ini"])["pytest.ini"]
    assert record.target_oid == hashlib.sha256(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest().encode()


@pytest.mark.parametrize("mode", [b"120000", b"040000", b"nonregular"])
def test_worktree_context_never_opens_nonregular_or_link_target(mode):
    source = RegularSource({"pytest.ini": b"an untrusted link would point elsewhere"})
    source.modes["pytest.ini"] = mode
    with pytest.raises(EngineError, match="not a regular source"):
        view(source).read_config_many(["pytest.ini"])
    assert source.reads == []


def test_worktree_context_refuses_data_different_from_captured_diff():
    source = RegularSource({"pytest.ini": b"new bytes during analysis"})
    changes = [FileChange(path="pytest.ini", status="modified", before=b"old", after=b"captured head")]
    with pytest.raises(EngineError, match="differs from captured diff"):
        view(source, changes).read_config_many(["pytest.ini"])


def test_backslash_diff_path_cannot_bypass_captured_bytes_consistency():
    source = RegularSource({"config/pytest.ini": b"late bytes"})
    changes = [FileChange(path=r"config\pytest.ini", status="modified", before=b"old", after=b"captured")]
    with pytest.raises(EngineError, match="differs from captured diff"):
        view(source, changes).read_config_many(["config/pytest.ini"])


@pytest.mark.parametrize("old_path", ["old/pytest.ini", r"old\pytest.ini"])
def test_renamed_config_old_path_cannot_reappear_outside_captured_diff(old_path):
    source = RegularSource({"new/pytest.ini": b"old", "old/pytest.ini": b"[pytest]\naddopts=-k narrow\n"})
    changes = (change for change in [
        FileChange(path="new/pytest.ini", status="modified", before=b"old", after=b"old", old_path=old_path)
    ])
    with pytest.raises(EngineError, match="differs from captured diff"):
        view(source, changes).read_config_many(["old/pytest.ini"])


def test_renamed_config_keeps_captured_old_path_absence():
    source = RegularSource({"new/pytest.ini": b"old"})
    changes = (change for change in [
        FileChange(path="new/pytest.ini", status="modified", before=b"old", after=b"old", old_path="old/pytest.ini")
    ])
    result = view(source, changes).read_config_many(["new/pytest.ini", "old/pytest.ini"])
    assert result["new/pytest.ini"].data == b"old" and result["old/pytest.ini"] is None


@pytest.mark.parametrize("rename_first", [True, False])
def test_explicit_old_path_change_keeps_its_captured_after_bytes(rename_first):
    restored = b"[pytest]\naddopts=-k reviewed\n"
    source = RegularSource({"new/pytest.ini": b"old", "old/pytest.ini": restored})
    rename = FileChange(path="new/pytest.ini", status="modified", before=b"old", after=b"old", old_path=r"old\pytest.ini")
    explicit = FileChange(path=r"old\pytest.ini", status="modified", before=b"old", after=restored)
    changes = (change for change in ([rename, explicit] if rename_first else [explicit, rename]))
    result = view(source, changes).read_config_many(["new/pytest.ini", "old/pytest.ini"])
    assert result["new/pytest.ini"].data == b"old"
    assert result["old/pytest.ini"].data == restored


def test_worktree_context_keeps_absence_distinct_from_empty_regular_source():
    source = RegularSource({"pytest.ini": b""})
    result = view(source).read_config_many(["pytest.ini", "pyproject.toml"])
    assert result["pytest.ini"].data == b"" and result["pyproject.toml"] is None


def test_case_alias_or_late_file_cannot_supply_an_inventory_absence():
    class CaseAlias(RegularSource):
        def list_paths(self):
            return ["PyTest.ini"]

    with pytest.raises(EngineError, match="captured inventory"):
        view(CaseAlias({"pytest.ini": b"[pytest]\n"})).read_config_many(["pytest.ini"])


def test_worktree_context_keeps_the_existing_per_source_byte_limit():
    with pytest.raises(EngineError, match="source byte limit"):
        view(RegularSource({"pytest.ini": b"x" * (snapshots.MAX_SOURCE_BYTES + 1)})).read_config_many(["pytest.ini"])


def test_mode_change_during_a_read_is_not_frozen_as_regular_evidence():
    class ModeChanges(RegularSource):
        calls = 0

        def config_modes(self, paths):
            self.calls += 1
            if self.calls > 1:
                return {path: b"120000" for path in paths}
            return super().config_modes(paths)

    with pytest.raises(EngineError, match="modes changed during analysis"):
        view(ModeChanges({"pytest.ini": b"[pytest]\n"})).read_config_many(["pytest.ini"])


@pytest.mark.parametrize("path", ["../pytest.ini", "/pytest.ini", "C:/pytest.ini", "dir/../pytest.ini", "dir\n/pytest.ini"])
def test_native_metadata_api_rejects_unsafe_names_before_file_reads(tmp_path, path):
    source = snapshots.WorkingTreeSnapshot(tmp_path)
    with pytest.raises(EngineError, match="unsafe path"):
        source.config_modes([path])


def test_final_file_link_metadata_never_resolves_or_reads_its_target(tmp_path, monkeypatch):
    source = snapshots.WorkingTreeSnapshot(tmp_path)
    link = tmp_path / "pytest.ini"
    link.write_bytes(b"owned stand-in; native file symlink privilege is unavailable")
    original_resolve = Path.resolve
    original_lstat = Path.lstat

    def resolve(path, *args, **kwargs):
        assert path != link, "final link target must not be resolved"
        return original_resolve(path, *args, **kwargs)

    def lstat(path, *args, **kwargs):
        if path == link:
            return SimpleNamespace(st_mode=stat.S_IFLNK | 0o777)
        return original_lstat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)
    monkeypatch.setattr(Path, "lstat", lstat)
    monkeypatch.setattr(source, "read_many", lambda _paths: pytest.fail("link data read is forbidden"))
    assert source.config_modes(["pytest.ini"]) == {"pytest.ini": b"120000"}
    with pytest.raises(EngineError, match="not a regular source"):
        view(source).read_config_many(["pytest.ini"])


def test_metadata_rejects_an_outside_parent_without_resolving_final_file(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    source = snapshots.WorkingTreeSnapshot(root)
    parent = root / "junction"
    outside = tmp_path / "outside-owned"
    outside.mkdir()
    original = Path.resolve

    def resolve(path, *args, **kwargs):
        assert path != parent / "pytest.ini"
        return outside if path == parent else original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)
    with pytest.raises(EngineError, match="leaves the repository") as caught:
        source.config_modes(["junction/pytest.ini"])
    assert str(outside) not in str(caught.value)


def git(repo, *args, data=None):
    result = subprocess.run(["git", "-C", str(repo), *args], input=data, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    return result.stdout


def initialize(repo):
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "pytest config context")
    git(repo, "config", "user.email", "context@example.invalid")
    git(repo, "config", "commit.gpgsign", "false")
    git(repo, "config", "core.autocrlf", "false")


@pytest.mark.parametrize("format", ["json", "hook-json"])
def test_git_base_link_with_fake_worktree_link_cannot_silently_pass(tmp_path, monkeypatch, capsys, format):
    # PJU cannot create native file links (WinError1314). Git stores the real
    # BASE120000 blob; the trusted fake supplies only after-side link metadata.
    # Neither the fake nor the reader follows a target through a worktree link.
    from checkwash import cli

    initialize(tmp_path)
    git(tmp_path, "config", "core.symlinks", "false")
    target = tmp_path / "settings" / "current.txt"
    target.parent.mkdir()
    target.write_bytes(b"[pytest]\naddopts=\n")
    link = b"settings/current.txt"
    (tmp_path / "pytest.ini").write_bytes(link)
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_keep.py").write_bytes(b"def test_keep():\n    assert api() == 1\n")
    git(tmp_path, "add", "-A")
    oid = git(tmp_path, "hash-object", "-w", "--stdin", data=link).decode().strip()
    git(tmp_path, "update-index", "--cacheinfo", f"120000,{oid},pytest.ini")
    git(tmp_path, "commit", "-m", "base with frozen config link")
    base = git(tmp_path, "rev-parse", "HEAD").decode().strip()
    old = snapshots.GitSnapshot(tmp_path, base).read_config_many(["pytest.ini"])["pytest.ini"]
    assert old.mode == b"120000" and old.data == b"[pytest]\naddopts=\n"
    target.write_bytes(b"[pytest]\naddopts=-k keep\n")
    original = snapshots.WorkingTreeSnapshot

    class FakeLinkSnapshot(original):
        def config_modes(self, paths):
            modes = super().config_modes(paths)
            if "pytest.ini" in modes:
                modes["pytest.ini"] = b"120000"
            return modes

        def read_many(self, paths):
            assert "pytest.ini" not in paths, "worktree link must be refused before data reads"
            return super().read_many(paths)

    monkeypatch.setattr(cli, "WorkingTreeSnapshot", FakeLinkSnapshot)
    code = main(["check", "--repo", str(tmp_path), "--format", format])
    output = capsys.readouterr()
    if format == "json":
        assert code == 2 and output.out == ""
        assert "worktree pytest config is not a regular source" in output.err
    else:
        payload = json.loads(output.out)
        assert code == 0 and "decision" not in payload
        assert "not analysed" in payload["systemMessage"]


def test_native_regular_pyproject_context_matches_committed_range(tmp_path, capsys):
    initialize(tmp_path)
    (tmp_path / "pyproject.toml").write_bytes(b'[tool.pytest.ini_options]\naddopts=""\n')
    (tmp_path / "test_keep.py").write_bytes(b"def test_keep():\n    assert api() == 1\n")
    (tmp_path / "test_drop.py").write_bytes(b"def test_drop():\n    assert api() == 2\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-m", "base")
    base = git(tmp_path, "rev-parse", "HEAD").decode().strip()
    (tmp_path / "pyproject.toml").write_bytes(b'[tool.pytest.ini_options]\naddopts="-k keep"\n')
    code = main(["check", "--repo", str(tmp_path), "--format", "json"])
    worktree = json.loads(capsys.readouterr().out)
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-m", "narrow collection")
    other = main(["check", f"{base}..HEAD", "--repo", str(tmp_path), "--format", "json"])
    committed = json.loads(capsys.readouterr().out)
    assert code == other == 1
    assert worktree["findings"] == committed["findings"]
    assert worktree["config_errors"] == committed["config_errors"] == []
    assert any(f["rule"] == "CI_WORKFLOW_TOUCHED" and f["severity"] == "high" for f in worktree["findings"])


def test_session_note_builds_a_fresh_pair_from_session_base_not_primary_head(tmp_path, monkeypatch):
    from checkwash import cli
    from checkwash.config import Config
    from checkwash.gitio.pytest_configs import PairedPytestConfigs, WorktreePytestConfigs

    initialize(tmp_path)
    config = tmp_path / "pytest.ini"
    original = b"[pytest]\naddopts=\n"
    config.write_bytes(original)
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-m", "session base")
    base = git(tmp_path, "rev-parse", "HEAD").decode().strip()
    head_bytes = b"[pytest]\naddopts=-x\n"
    config.write_bytes(head_bytes)
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-m", "session head")
    head = git(tmp_path, "rev-parse", "HEAD").decode().strip()
    source = snapshots.WorkingTreeSnapshot(tmp_path)
    prior = snapshots.GitSnapshot(tmp_path, head)
    first = b"[pytest]\naddopts=-q\n"
    config.write_bytes(first)
    primary = PairedPytestConfigs(prior, WorktreePytestConfigs(source, prior, [])).prepare()
    assert primary.sources("after", ["pytest.ini"])["pytest.ini"] == first
    second = b"[pytest]\naddopts=-k keep\n"
    config.write_bytes(second)
    seen = []

    def capture(args, changes, config_side, **readers):
        paired = readers["pytest_configs"]
        assert paired is not primary and config_side == base
        assert paired.snapshots["before"].revision == base
        paired.prepare()
        assert paired.sources("before", ["pytest.ini"])["pytest.ini"] == original
        assert paired.sources("after", ["pytest.ini"])["pytest.ini"] == second
        seen.append(paired)
        return SimpleNamespace(config=Config(), findings=[])

    monkeypatch.setattr(cli, "_analyse", capture)
    note = cli._session_note(SimpleNamespace(repo=str(tmp_path)),
        SimpleNamespace(base=base, head=head, missing=None),
        {"root_snapshot": source, "pytest_configs": primary})
    assert note is None and len(seen) == 1

"""Quality inventories refuse junction sources on every supported Python."""
import os
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from checkwash.quality.model import QualityError
from checkwash.quality.snapshot import Snapshot


@pytest.mark.skipif(os.name != "nt", reason="Windows native junction")
@pytest.mark.parametrize("external", [False, True])
def test_native_junction_is_not_walked_or_read(tmp_path, external):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
    target = (tmp_path if external else repo) / "target"
    target.mkdir()
    source = target / "config.toml"
    source.write_bytes(b"sensitive = true\n")
    link = repo / "linked"
    created = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
    if created.returncode:
        pytest.fail("Native junction creation failed: " + repr(created.stderr))
    try:
        assert not link.is_symlink()
        assert link.lstat().st_reparse_tag == stat.IO_REPARSE_TAG_MOUNT_POINT
        snapshot = Snapshot(repo)
        assert snapshot.modes["linked"] == "120000"
        assert not any(p.startswith("linked/") for p in snapshot.paths)
        if not external:
            assert snapshot.read("target/config.toml") == b"sensitive = true\n"
        with pytest.raises(QualityError) as caught:
            snapshot.read("linked/config.toml")
        assert caught.value.code == "EXTERNAL_SOURCE"
        assert caught.value.kind == "incomplete"
        assert "linked/config.toml" not in snapshot.cache
    finally:
        # Remove only this directory entry; never recurse into the target.
        link.rmdir()
        assert source.read_bytes() == b"sensitive = true\n"


@pytest.mark.parametrize("tag", [0, 0x9000001A, 0x8000001B])
def test_other_directory_reparse_tags_are_not_junctions(tmp_path, monkeypatch, tag):
    root = tmp_path / "repo"
    root.mkdir()
    directory = root / "ordinary"
    directory.mkdir()
    file = directory / "config.toml"
    file.write_bytes(b"ordinary = true\n")
    native_lstat = Path.lstat

    def lstat(path, *args, **kwargs):
        if path == directory:
            return SimpleNamespace(st_mode=stat.S_IFDIR, st_reparse_tag=tag,
                                   st_file_attributes=getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
        return native_lstat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", lstat)
    snapshot = Snapshot.__new__(Snapshot)
    snapshot.repo = str(root)
    snapshot.revision = None
    paths, modes = snapshot.inventory()
    assert paths == ["ordinary/config.toml"]
    assert modes == {"ordinary/config.toml": "100644"}


def test_plain_directory_without_windows_metadata_stays_regular(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    directory = root / "ordinary"
    directory.mkdir()
    (directory / "config.toml").write_bytes(b"ordinary = true\n")
    native_lstat = Path.lstat

    def lstat(path, *args, **kwargs):
        if path == directory:
            return SimpleNamespace(st_mode=stat.S_IFDIR)
        return native_lstat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", lstat)
    snapshot = Snapshot.__new__(Snapshot)
    snapshot.repo = str(root)
    snapshot.revision = None
    assert snapshot.inventory() == (["ordinary/config.toml"], {"ordinary/config.toml": "100644"})

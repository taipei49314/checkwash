"""CRLF checkout relocation keeps identity and adjacent weakening evidence."""
import json
import subprocess

import pytest

from checkwash.change import FileChange
from checkwash.cli import main
from checkwash.gitio.git import _detect_worktree_renames, list_worktree_changes


@pytest.mark.parametrize("before,after,paired", [
    (b"assert api() == 1\n", b"assert api() == 1\r\n", True),
    (b"assert api() == 1\r\n", b"assert api() == 1\n", True),
    (b"assert api() == 1\n", b"assert api() > 0\r\n", False),
    (b"assert api() == 1\n", b" assert api() == 1\r\n", False),
    (b"a\nb\n", b"a\rb\r", False),
    (b"\0a\nb\n", b"\0a\r\nb\r\n", False),
    (b"\xffa\nb\n", b"\xffa\r\nb\r\n", False),
    (b"\0same\r\n", b"\0same\r\n", True),
    (b"", b"", True),
])
def test_bounded_textual_pairing_retains_exact_source_bytes(before, after, paired):
    changes = [FileChange("test_old.py", "deleted", before, None),
               FileChange("test_new.py", "added", None, after)]
    result = _detect_worktree_renames(changes)
    assert len(result) == (1 if paired else 2)
    if paired:
        assert result[0].old_path == "test_old.py"
        assert result[0].before == before and result[0].after == after
    else:
        assert result == changes


def test_duplicate_content_pairing_is_deterministic_and_spent_once():
    changes = [FileChange("test_b.py", "deleted", b"assert x\n", None),
               FileChange("test_a.py", "deleted", b"assert x\n", None),
               FileChange("test_new.py", "added", None, b"assert x\r\n")]
    result = _detect_worktree_renames(changes)
    renamed = [c for c in result if c.old_path]
    assert len(renamed) == 1 and renamed[0].old_path == "test_a.py"
    assert any(c.path == "test_b.py" and c.status == "deleted" for c in result)


@pytest.mark.parametrize("staged", [False, True])
def test_native_range_and_crlf_worktree_keep_same_findings(tmp_path, capsys, staged):
    def git(*args):
        return subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True).stdout
    git("init")
    git("config", "user.name", "synthetic")
    git("config", "user.email", "synthetic@example.invalid")
    git("config", "commit.gpgsign", "false")
    git("config", "core.autocrlf", "false")
    (tmp_path / ".gitattributes").write_bytes(b"*.py text\n")
    moved = b"def test_keep():\n    assert api(1) == 1\n"
    (tmp_path / "test_old.py").write_bytes(moved)
    (tmp_path / "test_other.py").write_bytes(b"def test_other():\n    assert api(7) == 7\n")
    git("add", "-A")
    git("commit", "-m", "base")
    base = git("rev-parse", "HEAD").decode().strip()
    (tmp_path / "test_old.py").unlink()
    (tmp_path / "test_new.py").write_bytes(moved.replace(b"\n", b"\r\n"))
    (tmp_path / "test_other.py").write_bytes(b"def test_other():\r\n    assert api(7) > 0\r\n")
    if staged:
        git("add", "-A")
    changes = list_worktree_changes(str(tmp_path))
    rename = [c for c in changes if c.old_path == "test_old.py"]
    assert len(rename) == 1 and rename[0].path == "test_new.py"
    assert rename[0].before == moved and rename[0].after == moved.replace(b"\n", b"\r\n")
    worktree_exit = main(["check", "--repo", str(tmp_path), "--format", "json"])
    worktree = json.loads(capsys.readouterr().out)
    git("add", "-A")
    git("commit", "-m", "relocation and adjacent weakening")
    range_exit = main(["check", f"{base}..HEAD", "--repo", str(tmp_path), "--format", "json"])
    ranged = json.loads(capsys.readouterr().out)
    assert range_exit == worktree_exit == 1
    assert ranged["findings"] == worktree["findings"]
    assert ranged["config_errors"] == worktree["config_errors"] == []
    assert any(f["rule"] == "ASSERT_WEAKENED" and f["path"] == "test_other.py" for f in ranged["findings"])

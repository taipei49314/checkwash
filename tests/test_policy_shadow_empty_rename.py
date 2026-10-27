"""An empty file renamed into a priority policy path is still a new winning policy (D-177)."""
import json
import subprocess

import pytest

from checkwash.cli import main


def git(repo, *args):
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    return result.stdout.decode("utf-8").strip()


LEGACY = {
    "config.toml": b'[gate]\non_engine_error = "block"\n',
    "allow.toml": (b'[[allow]]\nfingerprint = "ASSERT_REMOVED/tests/test_x.py/test_x/v2:0"\n'
                   b'rule = "ASSERT_REMOVED"\nreason = "reviewed"\nauthor = "maintainer"\n'
                   b'created = "2026-10-01"\nexpires = "2099-01-01"\n'),
}


def plant(repo, name, *, rename):
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "policy shadow rename")
    git(repo, "config", "user.email", "shadow@example.invalid")
    git(repo, "config", "commit.gpgsign", "false")
    git(repo, "config", "core.autocrlf", "false")
    (repo / ".greenwash").mkdir()
    (repo / ".greenwash" / name).write_bytes(LEGACY[name])
    (repo / "pkg").mkdir()
    (repo / "pkg" / ".gitkeep").write_bytes(b"")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "base")
    base = git(repo, "rev-parse", "HEAD")
    if rename:
        git(repo, "rm", "-q", "pkg/.gitkeep")
    (repo / ".checkwash").mkdir()
    (repo / ".checkwash" / name).write_bytes(b"")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "empty priority policy")
    return base


@pytest.mark.parametrize("name", ["config.toml", "allow.toml"])
def test_empty_rename_into_priority_policy_matches_a_plain_creation(tmp_path, capsys, name):
    results = {}
    for rename in (False, True):
        repo = tmp_path / ("renamed" if rename else "added")
        repo.mkdir()
        base = plant(repo, name, rename=rename)
        if rename:
            status = git(repo, "diff", "--name-status", "--find-renames", base, "HEAD")
            assert status.startswith("R100"), status
        code = main(["check", f"{base}..HEAD", "--repo", str(repo), "--format", "json"])
        report = json.loads(capsys.readouterr().out)
        policy = [(f["rule"], f["severity"]) for f in report["findings"]
                  if f["path"] == f".checkwash/{name}"]
        results[rename] = (code, report["verdict"], policy)
    assert results[True] == results[False]
    code, verdict, policy = results[True]
    assert code == 1 and verdict == "block"
    assert policy and all(severity == "critical" for _rule, severity in policy)

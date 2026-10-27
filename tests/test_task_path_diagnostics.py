"""Expose repo-relative task mapping on a genuine lookup failure."""
import json
import subprocess

import pytest

from checkwash.cli import main


@pytest.fixture
def task_repo(tmp_path, monkeypatch):
    repo = tmp_path / "repository"
    caller = tmp_path / "caller"
    repo.mkdir()
    caller.mkdir()
    for args in (("init",), ("config", "user.name", "TASK path fixture"),
                 ("config", "user.email", "fixture@example.invalid")):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    (repo / "TASK.md").write_text("---\ncheckwash:\n  oracle_freeze: true\n---\n", encoding="utf-8")
    (repo / "test_api.py").write_text("def test_api():\n    assert api() == 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "-c", "commit.gpgsign=false", "commit", "-m", "trusted baseline"], check=True, capture_output=True)
    monkeypatch.chdir(caller)
    return repo, caller


@pytest.mark.parametrize("format", ("json", "hook-json"))
def test_outside_task_names_repo_relative_mapping(task_repo, capsys, format):
    repo, caller = task_repo
    code = main(["check", "--repo", str(repo), "--task", "../caller/TASK.md", "--format", format])
    output = capsys.readouterr()
    assert code == (0 if format == "hook-json" else 2)
    assert "TASK path context" in output.err
    assert repr(str(caller)) in output.err and repr(str(repo)) in output.err
    assert repr(str(caller / "TASK.md")) in output.err
    assert "absolute repository-owned" in output.err
    if format == "json":
        assert output.out == ""
    else:
        payload = json.loads(output.out)
        assert "decision" not in payload and "systemMessage" in payload


def test_absolute_task_control_stays_clean_without_path_warning(task_repo, capsys):
    repo, caller = task_repo
    assert main(["check", "--repo", str(repo), "--task", str(repo / "TASK.md"), "--format", "json"]) == 0
    output = capsys.readouterr()
    assert "TASK path context" not in output.err
    assert json.loads(output.out)["verdict"] == "pass"

"""Execute the installed handler, including cwd/PYTHONPATH shadow attempts."""

import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

from checkwash.hooks import HookInstallError, build_handler, install_claude, is_managed_handler


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True)


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "project with spaces 發票"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.name", "hook-test")
    _git(root, "config", "user.email", "hook@example.invalid")
    (root / "test_total.py").write_text("def test_total():\n    assert total() == 5\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "-c", "commit.gpgsign=false", "commit", "-m", "baseline")
    return root


def _handler(repo):
    settings = json.loads((repo / ".claude/settings.local.json").read_text(encoding="utf-8"))
    return settings["hooks"]["Stop"][0]["hooks"][0]


def _run(handler, repo, extra=None):
    return subprocess.run(
        [handler["command"], *handler["args"]], cwd=repo, capture_output=True,
        env={**os.environ, "PYTHONPATH": str(repo), **(extra or {})},
    )


@pytest.mark.parametrize("shadow", ["checkwash.py", "checkwash/__init__.py"])
def test_local_handler_executes_bound_package_despite_shadowing(repo, shadow):
    install_claude(str(repo), True)
    handler = _handler(repo)
    path = repo / shadow
    path.parent.mkdir(exist_ok=True)
    path.write_text("raise RuntimeError('repository module must never execute')\n", encoding="utf-8")
    clean = _run(handler, repo)
    assert clean.returncode == 0, clean.stderr
    assert json.loads(clean.stdout) == {}
    (repo / "test_total.py").write_text("def test_total():\n    assert total() > 0\n", encoding="utf-8")
    blocked = _run(handler, repo)
    assert blocked.returncode == 0, blocked.stderr
    assert json.loads(blocked.stdout)["decision"] == "block"
    assert b"ASSERT_WEAKENED" in blocked.stdout
    # An input/engine error remains a hook failure, not a verdict JSON.
    broken = json.loads(json.dumps(handler))
    broken["args"] += ["--repo", str(repo / "absent")]
    error = _run(broken, repo)
    assert error.returncode == 2
    assert b"engine error" in error.stderr


def test_zipapp_only_installs_and_executes_with_no_cli_on_path(repo, tmp_path):
    root = Path(__file__).resolve().parents[1]
    archive = tmp_path / "tool with spaces 發票.pyz"
    with zipfile.ZipFile(archive, "w") as bundle:
        for path in (root / "src/checkwash").rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                bundle.write(path, path.relative_to(root / "src").as_posix())
        bundle.writestr("__main__.py", "from checkwash.cli import main\nraise SystemExit(main())\n")
    environment = {**os.environ, "PATH": str(Path(sys.executable).parent), "PYTHONPATH": str(repo)}
    install = subprocess.run(
        [sys.executable, "-I", str(archive), "hook", "install", "--agent", "claude-code", "--local", "--repo", str(repo)],
        env=environment, capture_output=True,
    )
    assert install.returncode == 0, install.stderr
    handler = _handler(repo)
    assert json.loads(handler["args"][3]) == {"kind": "zipapp", "path": str(archive.resolve())}
    (repo / "test_total.py").write_text("def test_total():\n    assert total() > 0\n", encoding="utf-8")
    blocked = _run(handler, repo)
    assert blocked.returncode == 0, blocked.stderr
    assert json.loads(blocked.stdout)["decision"] == "block"


def test_local_upgrade_is_idempotent_and_preserves_custom_hooks(repo):
    path = repo / ".claude/settings.local.json"
    path.parent.mkdir()
    legacy = {"type": "command", "command": "checkwash check --format hook-json"}
    custom = {"type": "command", "command": "checkwash check --format hook-json --fail-on warn"}
    settings = {"permissions": {"allow": ["Bash(pytest:*)"]}, "hooks": {"Stop": [{"hooks": [legacy, custom]}]}}
    path.write_bytes(json.dumps(settings).encode("utf-8-sig"))
    assert "updated:" in install_claude(str(repo), True)
    first = path.read_bytes()
    decoded = json.loads(first)
    handlers = decoded["hooks"]["Stop"][0]["hooks"]
    assert custom in handlers
    assert sum(is_managed_handler(h) for h in handlers) == 1
    assert decoded["permissions"] == settings["permissions"]
    assert "already installed:" in install_claude(str(repo), True)
    assert path.read_bytes() == first


def test_python_executable_with_spaces_is_one_argument(repo, tmp_path, monkeypatch):
    environment = tmp_path / "Python runtime with spaces 發票"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(environment)], check=True, capture_output=True)
    executable = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    monkeypatch.setattr("checkwash.hooks.sys.executable", str(executable))
    install_claude(str(repo), True)
    handler = _handler(repo)
    assert handler["command"] == str(executable)
    result = _run(handler, repo)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {}


@pytest.mark.parametrize("settings", [[], {"hooks": []}, {"hooks": {"Stop": {}}}, {"hooks": {"Stop": [{"hooks": [1]}]}}])
def test_invalid_settings_are_not_modified(repo, settings):
    path = repo / ".claude/settings.local.json"
    path.parent.mkdir()
    original = json.dumps(settings).encode("utf-8")
    path.write_bytes(original)
    with pytest.raises(HookInstallError):
        install_claude(str(repo), True)
    assert path.read_bytes() == original


def test_shared_missing_cli_does_not_create_settings(repo, monkeypatch):
    monkeypatch.setattr("checkwash.hooks.shutil.which", lambda _: None)
    with pytest.raises(HookInstallError, match="install the CLI or use --local"):
        install_claude(str(repo), False)
    assert not (repo / ".claude").exists()


def test_shared_handler_is_portable_and_probed(monkeypatch):
    calls = []
    monkeypatch.setattr("checkwash.hooks.shutil.which", lambda _: "C:/tool/checkwash.exe")
    monkeypatch.setattr("checkwash.hooks._probe", lambda command, args: calls.append((command, args)))
    assert build_handler(False) == {"type": "command", "command": "checkwash", "args": ["check", "--format", "hook-json"]}
    assert calls == [("C:/tool/checkwash.exe", ["--version"])]


def test_shared_merge_keeps_portable_binding_and_other_settings(repo, monkeypatch):
    monkeypatch.setattr("checkwash.hooks.shutil.which", lambda _: "C:/tool/checkwash.exe")
    monkeypatch.setattr("checkwash.hooks._probe", lambda *args: None)
    path = repo / ".claude/settings.json"
    path.parent.mkdir()
    path.write_text('{"permissions": {"allow": ["Bash(pytest:*)"]}}', encoding="utf-8")
    install_claude(str(repo), False)
    settings = json.loads(path.read_text(encoding="utf-8"))
    assert settings["permissions"] == {"allow": ["Bash(pytest:*)"]}
    assert settings["hooks"]["Stop"][0]["hooks"][0]["command"] == "checkwash"
    before = path.read_bytes()
    assert "already installed" in install_claude(str(repo), False)
    assert path.read_bytes() == before


def test_probe_and_atomic_replace_failures_leave_original(repo, monkeypatch):
    path = repo / ".claude/settings.local.json"
    path.parent.mkdir()
    original = b'{"permissions": {"allow": []}}\n'
    path.write_bytes(original)
    def fail(*args):
        raise OSError("simulated write failure")
    monkeypatch.setattr("checkwash.hooks.os.replace", fail)
    with pytest.raises(OSError):
        install_claude(str(repo), True)
    assert path.read_bytes() == original
    assert sorted(p.name for p in path.parent.iterdir()) == ["settings.local.json"]

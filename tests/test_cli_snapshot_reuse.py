"""CLI reuse of `GitSnapshot` across base policy, task, manifest, and range reads."""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from checkwash import cli
from checkwash.change import EngineError
import checkwash.config as config_mod
import checkwash.gitio as gitio_pkg
from checkwash.gitio import git as gitio_git
from checkwash.gitio.snapshot import MAX_SOURCE_BYTES, GitSnapshot

GITLINK = "1111111111111111111111111111111111111111"


def _git(repo: Path, *args: str, data: bytes | None = None) -> bytes:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        input=data,
        capture_output=True,
        check=False,
        timeout=60,
    )
    assert proc.returncode == 0, (
        f"git {' '.join(args)} failed ({proc.returncode}): "
        f"{proc.stderr.decode('utf-8', 'replace')}"
    )
    return proc.stdout


def _init_repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.name", "snapshot-reuse-test")
    _git(root, "config", "user.email", "snapshot-reuse@example.invalid")
    _git(root, "config", "commit.gpgsign", "false")
    _git(root, "config", "core.autocrlf", "false")
    return root


def _write_files(root: Path, files: dict[str, bytes]) -> None:
    for rel, content in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


def _commit_all(root: Path, message: str) -> str:
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", message)
    return _git(root, "rev-parse", "HEAD").decode("ascii").strip()


def _spy_git_calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, ...]]:
    calls: list[tuple[str, ...]] = []
    original = subprocess.run

    def counting(argv, *args, **kwargs):
        if isinstance(argv, (list, tuple)) and argv and argv[0] == "git":
            # Strip `git -C <repo>` prefix to inspect the git subcommand cleanly.
            cmd = tuple(argv[3:]) if len(argv) >= 3 and argv[1] == "-C" else tuple(argv[1:])
            calls.append(cmd)
        return original(argv, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", counting)
    return calls


def _stdin_json(payload: dict) -> io.TextIOWrapper:
    return io.TextIOWrapper(io.BytesIO(json.dumps(payload).encode("utf-8")), encoding="utf-8")


def test_range_cli_check_reuses_base_and_head_snapshots_within_subprocess_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _init_repo(tmp_path / "big")
    base_files: dict[str, bytes] = {"src/app/__init__.py": b""}
    head_files: dict[str, bytes] = {}
    count = 60
    for i in range(count):
        base_files[f"src/app/mod_{i}.py"] = f"def compute_{i}(x):\n    return x * {i + 1}\n".encode()
        base_files[f"tests/test_mod_{i}.py"] = (
            f"from app.mod_{i} import compute_{i}\n\n\n"
            f"def test_compute_{i}():\n    assert compute_{i}(2) == {2 * (i + 1)}\n"
        ).encode()
        head_files[f"src/app/mod_{i}.py"] = (
            f"def compute_{i}(x):\n    # tuned\n    return x * {i + 1}\n"
        ).encode()
        head_files[f"tests/test_mod_{i}.py"] = (
            f"from app.mod_{i} import compute_{i}\n\n\n"
            f"def test_compute_{i}():\n    result = compute_{i}(2)\n"
            f"    assert result == {2 * (i + 1)}\n"
        ).encode()
    _write_files(repo, base_files)
    _commit_all(repo, "base")
    _write_files(repo, head_files)
    _commit_all(repo, "head")

    calls = _spy_git_calls(monkeypatch)
    rc = cli.main(["check", "HEAD~1..HEAD", "--repo", str(repo), "--format", "json"])
    out = capsys.readouterr()
    assert rc == 0, out.err
    payload = json.loads(out.out)
    assert payload["verdict"] == "pass"

    ls_trees = [c for c in calls if c and c[0] == "ls-tree"]
    batch_checks = [c for c in calls if c[:2] == ("cat-file", "--batch-check")]
    batches = [c for c in calls if c[:2] == ("cat-file", "--batch")]
    assert len(ls_trees) == 2, ls_trees
    assert len(batch_checks) == 0, batch_checks
    assert len(batches) == 2, batches
    assert len(calls) <= 18, f"expected <= 18 git subprocesses, got {len(calls)}: {calls}"


def test_empty_range_base_equals_head_reuses_side_snapshots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _init_repo(tmp_path / "same")
    _write_files(
        repo,
        {
            "src/pkg.py": b"def val():\n    return 1\n",
            "tests/test_pkg.py": b"from pkg import val\n\ndef test_val():\n    assert val() == 1\n",
        },
    )
    _commit_all(repo, "base")

    calls = _spy_git_calls(monkeypatch)
    rc = cli.main(["check", "HEAD..HEAD", "--repo", str(repo), "--format", "json"])
    out = capsys.readouterr()
    assert rc == 0, out.err
    assert json.loads(out.out)["verdict"] == "pass"
    ls_trees = [c for c in calls if c and c[0] == "ls-tree"]
    # Separate base and head snapshots keep side="base" vs side="head" labels (#415): 2 ls-trees total.
    assert len(ls_trees) == 2, ls_trees


def test_five_manifests_batch_in_one_cat_file_batch_and_resolve_imports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _init_repo(tmp_path / "manifests")
    _write_files(
        repo,
        {
            "pyproject.toml": (
                b'[project]\nname = "my-service"\nversion = "0.1.0"\n'
                b'dependencies = ["alpha-lib>=1.0"]\n'
            ),
            "requirements.txt": b"beta-lib==2.0.0\n",
            "requirements-dev.txt": b"gamma-lib>=0.5\n",
            "poetry.lock": b'[[package]]\nname = "delta-lib"\nversion = "1.2.3"\n',
            "uv.lock": b'version = 1\n\n[[package]]\nname = "epsilon-lib"\nversion = "4.5.6"\n',
            "my_service/__init__.py": b"def calc():\n    return 42\n",
            "tests/test_calc.py": (
                b"from my_service import calc\n\n"
                b"def test_calc():\n    assert calc() == 42\n"
            ),
        },
    )
    base_sha = _commit_all(repo, "base")
    _write_files(
        repo,
        {
            "tests/test_imports.py": (
                b"import alpha_lib\n"
                b"import beta_lib\n"
                b"import gamma_lib\n"
                b"import delta_lib\n"
                b"import epsilon_lib\n"
                b"import my_service\n"
                b"import undeclared_phantom_pkg\n\n"
                b"def test_imports():\n"
                b"    assert my_service.calc() == 42\n"
            ),
        },
    )
    _commit_all(repo, "add imports")

    # Verify direct helper batches all 5 in one cat-file --batch call.
    snap = GitSnapshot(str(repo), base_sha, side="base", resolved=base_sha)
    snap.list_paths()
    helper_calls = _spy_git_calls(monkeypatch)
    items, err = gitio_git.read_base_manifests_from_snapshot(
        snap, cli.MANIFESTS, cli.SKIPPABLE_OVERSIZED
    )
    assert err is None
    assert [name for name, _ in items] == list(cli.MANIFESTS)
    assert helper_calls == [("cat-file", "--batch")], helper_calls

    # Verify end-to-end CLI resolves all 5 declared packages + self_modules and flags only the phantom import.
    batch_check_inputs: list[bytes] = []
    cli_calls = _spy_git_calls(monkeypatch)
    spied_run = subprocess.run
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda argv, *a, **kw: (
            batch_check_inputs.append(kw.get("input", b""))
            if isinstance(argv, (list, tuple)) and len(argv) >= 5 and argv[0] == "git" and argv[3:5] == ["cat-file", "--batch-check"]
            else None,
            spied_run(argv, *a, **kw),
        )[1],
    )
    rc = cli.main(["check", "HEAD~1..HEAD", "--repo", str(repo), "--format", "json"])
    out = capsys.readouterr()
    assert rc in (0, 1), out.err
    findings = json.loads(out.out)["findings"]
    unresolved = [f for f in findings if f["rule"] == "IMPORT_UNRESOLVED"]
    assert len(unresolved) == 1, unresolved
    assert "undeclared_phantom_pkg" in unresolved[0]["message"]
    checked_text = b"".join(batch_check_inputs).decode("utf-8")
    for manifest in cli.MANIFESTS:
        assert f"{base_sha}:{manifest}\n" not in checked_text
    assert "undeclared_phantom_pkg" not in checked_text
    assert len([c for c in cli_calls if c and c[0] == "ls-tree"]) == 2, cli_calls


def test_checkwash_config_shadows_oversized_and_corrupt_greenwash_and_uses_batch_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _init_repo(tmp_path / "shadow-cfg")
    oversized_toml = b"# " + (b"x" * (MAX_SOURCE_BYTES + 64)) + b"\n"
    _write_files(
        repo,
        {
            ".checkwash/config.toml": b'[gate]\nfail_on = "warn"\n',
            ".checkwash/allow.toml": b"exemptions = []\n",
            ".greenwash/config.toml": oversized_toml,
            ".greenwash/allow.toml": b"not = [valid toml\n",
            "pkg.py": b"def f():\n    return 1\n",
            "tests/test_pkg.py": b"from pkg import f\n\ndef test_f():\n    assert f() == 1\n",
        },
    )
    _commit_all(repo, "base")
    _write_files(repo, {"README.md": b"# docs\n"})
    _commit_all(repo, "head")

    batch_checked: list[bytes] = []
    original = subprocess.run

    def spy(argv, *args, **kwargs):
        if (
            isinstance(argv, (list, tuple))
            and len(argv) >= 5
            and argv[0] == "git"
            and argv[3:5] == ["cat-file", "--batch-check"]
        ):
            batch_checked.append(kwargs.get("input", b""))
        return original(argv, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", spy)
    rc = cli.main(["check", "HEAD~1..HEAD", "--repo", str(repo), "--format", "json"])
    out = capsys.readouterr()
    assert rc == 0, out.err
    assert out.err == ""
    checked_specs = b"".join(batch_checked).decode("utf-8")
    assert ":.checkwash/config.toml\n" in checked_specs
    assert ":.checkwash/allow.toml\n" in checked_specs
    assert ".greenwash/config.toml" not in checked_specs
    assert ".greenwash/allow.toml" not in checked_specs

    # Converse: when .checkwash/config.toml is absent, oversized .greenwash/config.toml still refuses.
    repo2 = _init_repo(tmp_path / "unshadowed-cfg")
    _write_files(
        repo2,
        {
            ".greenwash/config.toml": oversized_toml,
            "tests/test_pkg.py": b"def test_ok():\n    assert 1 == 1\n",
        },
    )
    _commit_all(repo2, "base")
    _write_files(repo2, {"README.md": b"# docs\n"})
    _commit_all(repo2, "head")
    rc2 = cli.main(["check", "HEAD~1..HEAD", "--repo", str(repo2), "--format", "term"])
    out2 = capsys.readouterr()
    assert rc2 == 2
    assert ".greenwash/config.toml" in out2.err


def test_skippable_oversized_lockfiles_continue_while_non_lockfile_or_symlink_refuses(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    oversized_lock = b"# lock\n" + (b"a" * (MAX_SOURCE_BYTES + 100)) + b"\n"

    # 1. Oversized poetry.lock and uv.lock are skipped in MANIFESTS order; pyproject.toml still resolves.
    repo_ok = _init_repo(tmp_path / "skip-locks")
    _write_files(
        repo_ok,
        {
            "pyproject.toml": b'[project]\nname = "demo"\nversion = "0.1.0"\ndependencies = ["httpx>=0.27"]\n',
            "poetry.lock": oversized_lock,
            "uv.lock": oversized_lock + b"# uv\n",
            "tests/test_demo.py": b"def test_one():\n    assert 1 == 1\n",
        },
    )
    _commit_all(repo_ok, "base")
    _write_files(
        repo_ok,
        {
            "tests/test_demo.py": b"import httpx\n\ndef test_one():\n    assert 1 == 1\n",
        },
    )
    _commit_all(repo_ok, "use httpx")

    rc = cli.main(["check", "HEAD~1..HEAD", "--repo", str(repo_ok), "--format", "json"])
    out = capsys.readouterr()
    assert rc == 0, out.err
    assert json.loads(out.out)["findings"] == []
    poetry_idx = out.err.find("skipped poetry.lock (base,")
    uv_idx = out.err.find("skipped uv.lock (base,")
    assert 0 <= poetry_idx < uv_idx, out.err

    # 2. Oversized non-lockfile manifest (requirements-dev.txt) refuses with exit 2.
    repo_bad = _init_repo(tmp_path / "oversized-req")
    _write_files(
        repo_bad,
        {
            "requirements-dev.txt": oversized_lock,
            "tests/test_demo.py": b"def test_one():\n    assert 1 == 1\n",
        },
    )
    _commit_all(repo_bad, "base")
    _write_files(repo_bad, {"README.md": b"hi\n"})
    _commit_all(repo_bad, "head")
    rc_bad = cli.main(["check", "HEAD~1..HEAD", "--repo", str(repo_bad), "--format", "term"])
    out_bad = capsys.readouterr()
    assert rc_bad == 2
    assert "requirements-dev.txt" in out_bad.err

    # 3. Oversized poetry.lock before symlinked uv.lock emits poetry.lock note first, then refuses uv.lock.
    repo_link = _init_repo(tmp_path / "link-lock")
    _write_files(
        repo_link,
        {
            "poetry.lock": oversized_lock,
            "real-uv.lock": b"version = 1\n",
            "tests/test_demo.py": b"def test_one():\n    assert 1 == 1\n",
        },
    )
    _git(repo_link, "add", "-A")
    link_oid = _git(repo_link, "hash-object", "-w", "--stdin", data=b"real-uv.lock").decode("ascii").strip()
    _git(repo_link, "update-index", "--add", "--cacheinfo", f"120000,{link_oid},uv.lock")
    _git(repo_link, "commit", "-q", "-m", "base")
    _write_files(repo_link, {"README.md": b"hi\n"})
    _git(repo_link, "add", "README.md")
    _git(repo_link, "commit", "-q", "-m", "head")

    rc_link = cli.main(["check", "HEAD~1..HEAD", "--repo", str(repo_link), "--format", "term"])
    out_link = capsys.readouterr()
    assert rc_link == 2
    assert "skipped poetry.lock (base," in out_link.err
    assert "strict snapshot blob header does not match its regular tree entry" in out_link.err


def test_submodule_named_like_manifest_is_skipped_without_extra_git_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _init_repo(tmp_path / "sub-manifest")
    _write_files(
        repo,
        {
            ".gitmodules": (
                b'[submodule "pyproject.toml"]\n'
                b"\tpath = pyproject.toml\n"
                b"\turl = https://example.invalid/sub.git\n"
            ),
            "requirements.txt": b"declared-sub-pkg==1.0\n",
            "tests/test_sub.py": b"def test_ok():\n    assert 2 == 2\n",
        },
    )
    _git(repo, "add", "-A")
    _git(repo, "update-index", "--add", "--cacheinfo", f"160000,{GITLINK},pyproject.toml")
    _git(repo, "commit", "-q", "-m", "base")
    base_sha = _git(repo, "rev-parse", "HEAD").decode("ascii").strip()

    _write_files(
        repo,
        {
            "tests/test_sub.py": b"import declared_sub_pkg\n\ndef test_ok():\n    assert 2 == 2\n",
        },
    )
    _git(repo, "add", "tests/test_sub.py")
    _git(repo, "commit", "-q", "-m", "head")

    snap = GitSnapshot(str(repo), base_sha, side="base", resolved=base_sha)
    assert snap.definitely_lacks("pyproject.toml") is False
    assert gitio_git.read_base_file_from_snapshot(snap, "pyproject.toml") is None

    calls = _spy_git_calls(monkeypatch)
    rc = cli.main(["check", "HEAD~1..HEAD", "--repo", str(repo), "--format", "json"])
    out = capsys.readouterr()
    assert rc == 0, out.err
    assert json.loads(out.out)["findings"] == []
    assert len([c for c in calls if c and c[0] == "ls-tree"]) == 2


def test_task_base_read_and_issue500_alias_share_base_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _init_repo(tmp_path / "task-share")
    _write_files(
        repo,
        {
            "TASK.md": b"---\ncheckwash:\n  oracle_freeze: true\n---\n# Task\n",
            "calc.py": b"def add(a, b):\n    return a + b\n",
            "tests/test_calc.py": b"from calc import add\n\ndef test_add():\n    assert add(1, 2) == 3\n",
        },
    )
    _commit_all(repo, "base")
    _write_files(
        repo,
        {
            "TASK.md": b"---\ncheckwash:\n  oracle_freeze: false\n---\n# Disarmed\n",
            "calc.py": b"def add(a, b):\n    return a + b + 0\n",
            "tests/test_calc.py": b"from calc import add\n\ndef test_add():\n    assert add(1, 2) > 0\n",
        },
    )
    _commit_all(repo, "weaken")

    # 1. Base TASK.md wins in range mode and shares base_snapshot (only 1 base ls-tree).
    calls = _spy_git_calls(monkeypatch)
    rc = cli.main(["check", "HEAD~1..HEAD", "--repo", str(repo), "--task", "TASK.md", "--format", "json"])
    out = capsys.readouterr()
    assert rc == 1, out.err
    findings = json.loads(out.out)["findings"]
    weakened = [f for f in findings if f["rule"] == "ASSERT_WEAKENED"]
    assert weakened and "ORACLE_FREEZE" in weakened[0]["escalators"]
    assert len([c for c in calls if c and c[0] == "ls-tree"]) == 2

    # 2. Issue #500 case-alias refusal (`--task task.md` against base `TASK.md`) reuses base_snapshot.
    calls_alias = _spy_git_calls(monkeypatch)
    rc_alias = cli.main(["check", "--repo", str(repo), "--task", "task.md", "--format", "term"])
    out_alias = capsys.readouterr()
    assert rc_alias == 2
    assert "holds only in another case, as TASK.md" in out_alias.err
    assert len([c for c in calls_alias if c and c[0] == "ls-tree"]) == 1

    # 3. Truly absent task file falls back to working tree; range mode shares its 2 snapshots (base + head).
    _write_files(repo, {"NEW_TASK.md": b"---\ncheckwash:\n  oracle_freeze: false\n---\n"})
    calls_fb = _spy_git_calls(monkeypatch)
    rc_fb = cli.main(["check", "HEAD~1..HEAD", "--repo", str(repo), "--task", "NEW_TASK.md", "--format", "json"])
    out_fb = capsys.readouterr()
    assert rc_fb in (0, 1), out_fb.err
    assert "the base tree has no file at NEW_TASK.md" in out_fb.err
    assert len([c for c in calls_fb if c and c[0] == "ls-tree"]) == 2


def test_pre_tool_use_and_stop_session_reuse_snapshots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _init_repo(tmp_path / "hooks")
    _write_files(
        repo,
        {
            "pyproject.toml": b'[project]\nname = "app"\nversion = "0.1.0"\n',
            "src/app.py": b"def total():\n    return 10\n",
            "tests/test_app.py": b"from app import total\n\ndef test_total():\n    assert total() == 10\n",
        },
    )
    _commit_all(repo, "base")

    # Record session start.
    monkeypatch.setattr(
        sys, "stdin", _stdin_json({"session_id": "s-1", "hook_event_name": "SessionStart"})
    )
    assert cli.main(["hook", "session-start", "--repo", str(repo)]) == 0
    capsys.readouterr()

    # PreToolUse on a non-test Python file uses 1 ls-tree and 0 cat-file calls.
    calls_non_test = _spy_git_calls(monkeypatch)
    monkeypatch.setattr(
        sys,
        "stdin",
        _stdin_json(
            {
                "session_id": "s-1",
                "hook_event_name": "PreToolUse",
                "tool_name": "Write",
                "tool_input": {
                    "file_path": str(repo / "src" / "app.py"),
                    "content": "def total():\n    return 11\n",
                },
            }
        ),
    )
    assert cli.main(["hook", "pre-tool-use", "--repo", str(repo)]) == 0
    assert json.loads(capsys.readouterr().out) == {}
    assert len([c for c in calls_non_test if c and c[0] == "ls-tree"]) == 1
    assert [c for c in calls_non_test if c and c[0] == "cat-file"] == []

    # PreToolUse on a weakened test reuses config_snapshot as head when session base == HEAD.
    calls_test = _spy_git_calls(monkeypatch)
    monkeypatch.setattr(
        sys,
        "stdin",
        _stdin_json(
            {
                "session_id": "s-1",
                "hook_event_name": "PreToolUse",
                "tool_name": "Write",
                "tool_input": {
                    "file_path": str(repo / "tests" / "test_app.py"),
                    "content": "from app import total\n\ndef test_total():\n    assert total() > 0\n",
                },
            }
        ),
    )
    assert cli.main(["hook", "pre-tool-use", "--repo", str(repo)]) == 0
    pre_out = json.loads(capsys.readouterr().out)
    assert pre_out["hookSpecificOutput"]["permissionDecision"] == "ask"
    assert len([c for c in calls_test if c and c[0] == "ls-tree"]) == 1

    # Commit an edit in the session so Stop hook runs both leg 1 and _session_note leg 2.
    _write_files(
        repo,
        {"tests/test_app.py": b"from app import total\n\ndef test_total():\n    assert total() > 0\n"},
    )
    _commit_all(repo, "weaken in session")
    calls_stop = _spy_git_calls(monkeypatch)
    monkeypatch.setattr(
        sys, "stdin", _stdin_json({"session_id": "s-1", "hook_event_name": "Stop"})
    )
    assert cli.main(["check", "--repo", str(repo), "--format", "hook-json", "--hook-input", "stdin"]) == 0
    stop_out = json.loads(capsys.readouterr().out)
    assert "commits made during this session hold 1 finding(s)" in stop_out.get("systemMessage", "")
    # Leg 1 + _session_note share config_snapshot across policy/manifests/pytest_configs (<= 4 ls-trees total).
    assert len([c for c in calls_stop if c and c[0] == "ls-tree"]) <= 4, calls_stop


def test_monkeypatch_fallbacks_preserve_cli_config_and_gitio_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _init_repo(tmp_path / "mp")
    _write_files(
        repo,
        {
            "TASK.md": b"# base task\n",
            "pkg.py": b"def v():\n    return 1\n",
            "tests/test_pkg.py": b"from pkg import v\n\ndef test_v():\n    assert v() == 1\n",
        },
    )
    _commit_all(repo, "base")
    _write_files(repo, {"README.md": b"change\n"})
    _commit_all(repo, "head")

    # 1. Monkeypatching config.read_base_config_file or cli.read_base_config_file is honoured.
    seen_policy: list[str] = []
    orig_cfg = config_mod.read_base_config_file
    monkeypatch.setattr(
        config_mod,
        "read_base_config_file",
        lambda r, s, n: (seen_policy.append(n) or orig_cfg(r, s, n)),
    )
    assert cli.main(["check", "HEAD~1..HEAD", "--repo", str(repo), "--format", "json"]) == 0
    capsys.readouterr()
    assert seen_policy == ["config.toml", "allow.toml"]
    monkeypatch.undo()

    # 2. Monkeypatching gitio.git.read_base_file falls back for policy, --task, and MANIFESTS.
    seen_files: list[str] = []
    orig_rbf = gitio_git.read_base_file

    def fake_rbf(r: str, b: str, p: str, *, side: str = "base") -> bytes | None:
        seen_files.append(p)
        return orig_rbf(r, b, p, side=side)

    monkeypatch.setattr(gitio_git, "read_base_file", fake_rbf)
    assert cli.main(["check", "HEAD~1..HEAD", "--repo", str(repo), "--task", "TASK.md", "--format", "json"]) == 0
    capsys.readouterr()
    assert "TASK.md" in seen_files
    assert all(m in seen_files for m in cli.MANIFESTS)
    assert ".checkwash/config.toml" in seen_files
    monkeypatch.undo()

    # 3. Monkeypatching gitio_pkg.base_alias is honoured while base_snapshot is active.
    alias_calls: list[str] = []
    orig_alias = gitio_pkg.base_alias
    monkeypatch.setattr(
        gitio_pkg,
        "base_alias",
        lambda r, b, p: (alias_calls.append(p) or orig_alias(r, b, p)),
    )
    _write_files(repo, {"OTHER_TASK.md": b"# wt\n"})
    assert cli.main(["check", "--repo", str(repo), "--task", "OTHER_TASK.md", "--format", "json"]) == 0
    capsys.readouterr()
    assert alias_calls == ["OTHER_TASK.md"]


def test_definitely_lacks_and_resolved_oid_validation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _init_repo(tmp_path / "unit")
    _write_files(
        repo,
        {
            ".gitmodules": b'[submodule "vendor/sub"]\n\tpath = vendor/sub\n\turl = https://example.invalid/s.git\n',
            "dir/nested/file.py": b"x = 1\n",
        },
    )
    _git(repo, "add", "-A")
    _git(repo, "update-index", "--add", "--cacheinfo", f"160000,{GITLINK},vendor/sub")
    _git(repo, "commit", "-q", "-m", "base")
    sha = _git(repo, "rev-parse", "HEAD").decode("ascii").strip()

    with pytest.raises(EngineError, match="invalid resolved commit"):
        GitSnapshot(str(repo), "HEAD", resolved="not-a-hex-oid")
    with pytest.raises(EngineError, match="invalid resolved commit"):
        GitSnapshot(str(repo), "HEAD", resolved="A" * 40)

    snap = GitSnapshot(str(repo), sha, side="base", resolved=sha)
    assert snap.definitely_lacks("") is False
    assert snap.definitely_lacks(".") is False
    assert snap.definitely_lacks("../outside") is False
    assert snap.definitely_lacks("/abs") is False
    assert snap.definitely_lacks("dir/") is False
    assert snap.definitely_lacks("bad\npath") is False
    assert snap.definitely_lacks("dir\\nested\\file.py") is False
    assert snap.definitely_lacks("dir") is False
    assert snap.definitely_lacks("dir/nested") is False
    assert snap.definitely_lacks("dir/nested/file.py") is False
    assert snap.definitely_lacks("vendor/sub") is False
    assert snap.definitely_lacks("vendor/sub/inside.py") is False
    assert snap.definitely_lacks("absent.toml") is True
    assert snap.definitely_lacks("dir/absent.toml") is True

    # Mutating the returned list_paths() list does not corrupt cached _listed_paths.
    listed = snap.list_paths()
    listed.clear()
    assert "dir/nested/file.py" in snap.list_paths()
    assert snap.definitely_lacks("dir/nested/file.py") is False

    # Empty 040000 Git subtrees (via mktree + commit-tree) are never treated as absent,
    # and never fail open to an untrusted working-tree --task or policy file.
    empty_tree_oid = _git(repo, "mktree", data=b"").decode("ascii").strip()
    root_tree_raw = _git(repo, "ls-tree", "-z", sha)
    augmented = (
        root_tree_raw
        + f"040000 tree {empty_tree_oid}\temptydir\0".encode("ascii")
        + f"040000 tree {empty_tree_oid}\tTASK.md\0".encode("ascii")
    )
    custom_tree = _git(repo, "mktree", "-z", data=augmented).decode("ascii").strip()
    custom_commit = _git(repo, "commit-tree", custom_tree, "-p", sha, "-m", "empty-trees").decode("ascii").strip()
    _git(repo, "update-ref", "refs/heads/main", custom_commit)

    snap_unlisted = GitSnapshot(str(repo), custom_commit, side="base", resolved=custom_commit)
    with pytest.raises(EngineError, match="invalid blob header"):
        snap_unlisted.read("emptydir")

    snap_listed = GitSnapshot(str(repo), custom_commit, side="base", resolved=custom_commit)
    snap_listed.list_paths()
    assert snap_listed.definitely_lacks("emptydir") is False
    assert snap_listed.definitely_lacks("TASK.md") is False
    with pytest.raises(EngineError, match="invalid blob header"):
        snap_listed.read("emptydir")

    # Even if the working tree places a regular file at TASK.md, base's empty 040000 tree fails closed (exit 2).
    _write_files(repo, {"TASK.md": b"---\ncheckwash:\n  oracle_freeze: false\n---\n"})
    rc_task = cli.main(["check", "--repo", str(repo), "--task", "TASK.md", "--format", "term"])
    out_task = capsys.readouterr()
    assert rc_task == 2
    assert "invalid blob header" in out_task.err

"""Git failures retain an error, including faults in real generated objects.

These fixtures are synthetic; no historical or held-out repository is read.
Existing expected findings and gate fixtures remain unchanged.
"""
import os
import datetime
from pathlib import Path
import subprocess
import sys

import pytest

from checkwash.change import EngineError
from checkwash.gitio import git as gitio
from checkwash.gitio import snapshot as snapshots


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True).stdout


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "config", "user.name", "synthetic")
    git(tmp_path, "config", "user.email", "synthetic@example.invalid")
    git(tmp_path, "config", "commit.gpgsign", "false")
    git(tmp_path, "config", "core.autocrlf", "false")
    (tmp_path / "test_example.py").write_bytes(b"def test_example():\n    assert 1 == 1\n")
    (tmp_path / "empty.py").write_bytes(b"")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-m", "base")
    return tmp_path


def object_path(repo, revision="HEAD", path="test_example.py"):
    oid = git(repo, "rev-parse", f"{revision}:{path}").decode("ascii").strip()
    return repo / ".git" / "objects" / oid[:2] / oid[2:]


def reader(repo, operation):
    snapshot = snapshots.GitSnapshot(repo, "HEAD")
    snapshot.list_paths()  # Inventory first; faults happen after this boundary.
    return {
        "legacy_one": lambda: gitio.read_base_file(str(repo), "HEAD", "test_example.py"),
        "legacy_batch": lambda: gitio.read_blobs(str(repo), [("HEAD", "test_example.py")]),
        "snapshot_one": lambda: snapshot.read("test_example.py"),
        "snapshot_batch": lambda: snapshot.read_many(["test_example.py"]),
    }[operation]


@pytest.mark.parametrize("operation", ["legacy_one", "legacy_batch", "snapshot_one", "snapshot_batch"])
@pytest.mark.parametrize("fault", ["removed", "corrupt"])
def test_real_object_loss_never_becomes_absence(repo, operation, fault):
    read = reader(repo, operation)
    target = object_path(repo)
    assert target.is_file() and target.resolve().is_relative_to((repo / ".git" / "objects").resolve())
    target.chmod(0o600)
    if fault == "removed":
        target.unlink()
    else:
        target.write_bytes(b"not a zlib git object")
    with pytest.raises((GitError, EngineError)):
        read()


GitError = gitio.GitError


@pytest.mark.parametrize("operation", ["inventory", "legacy_batch"])
def test_reference_keeps_original_submodule_inventory_refusal(repo, operation):
    # Do not backport the newer opaque-submodule detector policy into v0.6.0.
    commit = git(repo, "rev-parse", "HEAD").decode().strip()
    git(repo, "update-index", "--add", "--cacheinfo", "160000," + commit + ",vendor")
    git(repo, "commit", "-m", "generated gitlink")
    with pytest.raises((GitError, EngineError), match="cannot inspect a submodule"):
        if operation == "inventory":
            snapshots.GitSnapshot(repo, "HEAD").list_paths()
        else:
            gitio.read_blobs(str(repo), [("HEAD", "test_example.py")])


@pytest.mark.parametrize("operation", ["legacy_one", "legacy_batch"])
@pytest.mark.parametrize("fault", ["nonzero", "missing", "wrong_type", "wrong_oid", "truncated", "corrupt_bytes", "trailing"])
def test_batch_protocol_faults_are_errors(repo, monkeypatch, operation, fault):
    read = reader(repo, operation)
    original = subprocess.run

    def inject(argv, **kwargs):
        proc = original(argv, **kwargs)
        if argv[-2:] != ["cat-file", "--batch"]:
            return proc
        raw = proc.stdout
        header, sep, body = raw.partition(b"\n")
        assert sep and b" blob " in header
        changes = {
            "missing": header.split()[0] + b" missing\n",
            "wrong_type": raw.replace(b" blob ", b" tree ", 1),
            "wrong_oid": b"0" * len(header.split()[0]) + raw[len(header.split()[0]):],
            "truncated": raw[:-1],
            "corrupt_bytes": header + b"\n" + b"X" + body[1:],
            "trailing": raw + b"junk",
        }
        return subprocess.CompletedProcess(argv, 128 if fault == "nonzero" else 0,
                                           changes.get(fault, raw), b"injected failure" if fault == "nonzero" else b"")

    monkeypatch.setattr(subprocess, "run", inject)
    with pytest.raises((GitError, EngineError)):
        read()


@pytest.mark.parametrize("module", [gitio, snapshots])
@pytest.mark.parametrize("fault", ["startup", "timeout"])
def test_process_failure_is_not_missing(monkeypatch, module, fault):
    def fail(*args, **kwargs):
        if fault == "startup":
            raise OSError("synthetic startup failure")
        raise subprocess.TimeoutExpired("git", 60)

    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises((GitError, EngineError)):
        module._run("unused", ["status"])


@pytest.mark.parametrize("case", ["no_match", "one_stdout", "one_stderr", "error_valid_stdout", "unterminated", "wrong_prefix", "duplicate", "undecodable"])
def test_head_search_status_and_protocol(monkeypatch, case):
    oid = "a" * 40
    path = oid.encode() + b":tests/test_example.py\0"
    responses = {
        "no_match": (1, b"", b""),
        "one_stdout": (1, path, b""),
        "one_stderr": (1, b"", b"read failed"),
        "error_valid_stdout": (128, path, b"read failed"),
        "unterminated": (0, path[:-1], b""),
        "wrong_prefix": (0, b"other:test.py\0", b""),
        "duplicate": (0, path + path, b""),
        "undecodable": (0, oid.encode() + b":test_\xff.py\0", b""),
    }
    monkeypatch.setattr(gitio, "resolve_commit", lambda *args: oid)
    monkeypatch.setattr(subprocess, "run", lambda argv, **kwargs: subprocess.CompletedProcess(argv, *responses[case]))
    if case == "no_match":
        assert gitio.grep_head_paths("unused", "HEAD", ["needle"]) == []
    else:
        with pytest.raises(GitError):
            gitio.grep_head_paths("unused", "HEAD", ["needle"])


def test_readable_empty_missing_and_rename_keep_their_meaning(repo):
    assert gitio.read_base_file(str(repo), "HEAD", "absent.py") is None
    assert gitio.read_base_file(str(repo), "HEAD", "empty.py") == b""
    git(repo, "mv", "test_example.py", "test_renamed.py")
    git(repo, "commit", "-m", "rename")
    changes = gitio.list_range_changes(str(repo), "HEAD~1", "HEAD")
    assert len(changes) == 1
    change = changes[0]
    assert change.old_path == "test_example.py" and change.path == "test_renamed.py"
    assert change.before == change.after == b"def test_example():\n    assert 1 == 1\n"


@pytest.mark.parametrize("path", ["test_example.py", ".checkwash/config.toml", "pyproject.toml", "conftest.py"])
def test_cli_object_loss_has_no_verdict(repo, path):
    data = {
        "test_example.py": b"def test_example():\n    assert 1 == 1\n",
        ".checkwash/config.toml": b"# synthetic config\n",
        "pyproject.toml": b"# synthetic manifest\n",
        "conftest.py": b"# synthetic context\n",
    }[path]
    (repo / path).parent.mkdir(parents=True, exist_ok=True)
    (repo / path).write_bytes(data)
    git(repo, "add", "-A")
    git(repo, "commit", "--allow-empty", "-m", "controls")
    (repo / "test_example.py").write_bytes(b"def test_example():\n    assert True\n")
    git(repo, "commit", "-am", "weaken")
    # Build the relevant exact inventory before removing a real generated blob.
    assert path in snapshots.GitSnapshot(repo, "HEAD~1").list_paths()
    target = object_path(repo, "HEAD~1", path)
    assert target.resolve().is_relative_to((repo / ".git" / "objects").resolve())
    target.chmod(0o600)
    target.unlink()
    proc = subprocess.run([sys.executable, "-m", "checkwash", "check", "HEAD~1..HEAD", "--repo", str(repo), "--format", "json"],
                          capture_output=True, env={**os.environ, "PYTHONUTF8": "1"}, timeout=60)
    assert proc.returncode == 2, proc.stdout
    assert not proc.stdout.strip(), "an input failure must not publish an ordinary verdict"


@pytest.mark.parametrize("operation", ["changes", "snapshot"])
def test_worktree_permission_failure_is_not_deletion(repo, monkeypatch, operation):
    (repo / "test_example.py").write_bytes(b"def test_example():\n    assert True\n")
    original = Path.open

    def deny(path, *args, **kwargs):
        if path.name == "test_example.py":
            raise PermissionError("synthetic denied source")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", deny)
    with pytest.raises(PermissionError):
        if operation == "changes":
            gitio.list_worktree_changes(str(repo))
        else:
            snapshots.WorkingTreeSnapshot(repo).read("test_example.py")


def test_required_diff_side_cannot_use_tree_absence(repo):
    with pytest.raises(GitError, match="required diff side"):
        gitio.read_blobs(str(repo), [("HEAD", "absent.py")], required=True)


def test_real_head_search_object_loss_is_not_no_matches(repo):
    target = object_path(repo)
    assert target.resolve().is_relative_to((repo / ".git" / "objects").resolve())
    target.chmod(0o600)
    target.unlink()
    with pytest.raises(GitError):
        gitio.grep_head_paths(str(repo), "HEAD", ["test_example"])


def test_sweep_counts_read_failure_separately_from_proven_root(repo):
    from checkwash.sweep import sweep

    (repo / "test_example.py").write_bytes(b"def test_example():\n    assert True\n")
    git(repo, "commit", "-am", "weaken")
    target = object_path(repo)
    assert target.resolve().is_relative_to((repo / ".git" / "objects").resolve())
    target.chmod(0o600)
    target.unlink()
    result = sweep(str(repo), "HEAD", 2, datetime.date(2026, 1, 1))
    assert (result.commits, result.errors, result.skipped) == (0, 1, 1)


@pytest.mark.parametrize("case", ["no_match", "match", "empty_success", "null_record", "extra_null", "one_stdout", "one_stderr", "success_stderr", "error_valid_stdout", "unterminated", "wrong_prefix", "duplicate", "undecodable"])
def test_root_context_search_preserves_status_and_record_failure(monkeypatch, case):
    oid = "a" * 40
    path = oid.encode() + b":tests/test_example.py\0"
    responses = {
        "no_match": (1, b"", b""), "match": (0, path, b""),
        "empty_success": (0, b"", b""), "null_record": (0, b"\0", b""),
        "extra_null": (0, path + b"\0", b""), "one_stdout": (1, path, b""),
        "one_stderr": (1, b"", b"read failed"), "success_stderr": (0, path, b"read failed"),
        "error_valid_stdout": (128, path, b"read failed"), "unterminated": (0, path[:-1], b""),
        "wrong_prefix": (0, b"other:test.py\0", b""), "duplicate": (0, path + path, b""),
        "undecodable": (0, oid.encode() + b":test_\xff.py\0", b""),
    }
    snapshot = snapshots.GitSnapshot("unused", oid)
    snapshot._resolved = oid
    monkeypatch.setattr(subprocess, "run", lambda argv, **kwargs: subprocess.CompletedProcess(argv, *responses[case]))
    if case in {"no_match", "match"}:
        assert snapshot.search(["needle"]) == ([] if case == "no_match" else ["tests/test_example.py"])
    else:
        with pytest.raises(EngineError):
            snapshot.search(["needle"])


@pytest.mark.parametrize("case", ["empty_success", "success_stderr"])
def test_head_search_rejects_inconsistent_success(monkeypatch, case):
    oid = "a" * 40
    path = oid.encode() + b":tests/test_example.py\0"
    monkeypatch.setattr(gitio, "resolve_commit", lambda *args: oid)
    monkeypatch.setattr(subprocess, "run", lambda argv, **kwargs: subprocess.CompletedProcess(
        argv, 0, b"" if case == "empty_success" else path, b"read failed" if case == "success_stderr" else b""))
    with pytest.raises(GitError):
        gitio.grep_head_paths("unused", oid, ["needle"])


def test_real_root_search_object_loss_is_not_no_matches(repo):
    snapshot = snapshots.GitSnapshot(repo, "HEAD")
    assert "test_example.py" in snapshot.list_paths()
    target = object_path(repo)
    assert target.resolve().is_relative_to((repo / ".git" / "objects").resolve())
    target.chmod(0o600)
    target.unlink()
    with pytest.raises(EngineError):
        snapshot.search(["test_example"])


@pytest.mark.parametrize("raw", [
    b" M\0", b" M test_example.py", b" M test_example.py\0\0", b" M:test_example.py\0",
    b"ZZ test_example.py\0", b"   test_example.py\0", b" M test_example.py\0 M test_example.py\0",
    b" M test_\xff.py\0", b" M test_\n.py\0",
])
def test_worktree_status_rejects_malformed_input_before_reading(monkeypatch, raw):
    monkeypatch.setattr(gitio, "_run", lambda *args: raw)

    def unexpected_read(*args):
        pytest.fail("malformed status must be rejected before any source read")

    monkeypatch.setattr(gitio, "resolve_commit", lambda *args: "a" * 40)
    monkeypatch.setattr(gitio, "_read_blob", unexpected_read)
    with pytest.raises(GitError):
        gitio.list_worktree_changes("unused")


@pytest.mark.parametrize("operation", ["clean", "modified", "deleted"])
def test_complete_worktree_status_keeps_normal_changes(repo, operation):
    path = repo / "test_example.py"
    if operation == "modified":
        path.write_bytes(b"def test_example():\n    assert True\n")
    elif operation == "deleted":
        path.unlink()
    changes = gitio.list_worktree_changes(str(repo))
    if operation == "clean":
        assert changes == []
    else:
        assert len(changes) == 1 and changes[0].path == "test_example.py"
        assert changes[0].status == operation


@pytest.mark.parametrize("operation", ["list", "startup_search"])
@pytest.mark.parametrize("case", ["empty_tree", "null_record", "double_null", "leading_null", "extra_null", "unterminated", "malformed", "empty_name", "wrong_oid", "duplicate"])
def test_inventory_failure_cannot_erase_sources(monkeypatch, operation, case):
    oid = "a" * 40
    record = b"100644 blob " + oid.encode() + b" 1\ttest_example.py\0"
    responses = {
        "empty_tree": b"", "null_record": b"\0", "double_null": b"\0\0",
        "leading_null": b"\0" + record, "extra_null": record + b"\0",
        "unterminated": record[:-1], "malformed": b"100644 blob\0",
        "empty_name": b"100644 blob " + oid.encode() + b" 1\t\0",
        "wrong_oid": b"100644 blob nope 1\ttest_example.py\0",
        "duplicate": record + record,
    }
    snapshot = snapshots.GitSnapshot("unused", oid)
    snapshot._resolved = oid
    monkeypatch.setattr(subprocess, "run", lambda argv, **kwargs: subprocess.CompletedProcess(argv, 0, responses[case], b""))
    read = snapshot.list_paths if operation == "list" else lambda: snapshot.search([""])
    if case == "empty_tree":
        assert read() == []
    else:
        with pytest.raises(EngineError):
            read()


@pytest.mark.parametrize("fault", ["empty", "truncated", "parent_removed", "nonzero_valid"])
def test_sweep_commit_object_fault_is_error_not_root(repo, monkeypatch, fault):
    from checkwash.sweep import sweep

    (repo / "test_example.py").write_bytes(b"def test_example():\n    assert True\n")
    git(repo, "commit", "-am", "weaken")
    child = git(repo, "rev-parse", "HEAD").decode().strip()
    original = subprocess.run

    def inject(argv, **kwargs):
        proc = original(argv, **kwargs)
        if argv[-3:] != ["cat-file", "commit", child]:
            return proc
        raw = proc.stdout
        assert b"\nparent " in raw
        changed = {"empty": b"", "truncated": raw[:-1],
                   "parent_removed": b"\n".join(line for line in raw.split(b"\n") if not line.startswith(b"parent "))}
        return subprocess.CompletedProcess(argv, 128 if fault == "nonzero_valid" else 0,
                                           changed.get(fault, raw), b"fault" if fault == "nonzero_valid" else b"")

    monkeypatch.setattr(subprocess, "run", inject)
    result = sweep(str(repo), "HEAD", 2, datetime.date(2026, 1, 1))
    assert (result.commits, result.errors, result.skipped) == (0, 1, 1)


def test_shallow_boundary_is_not_a_root(repo, tmp_path):
    from checkwash.sweep import sweep

    (repo / "test_example.py").write_bytes(b"def test_example():\n    assert True\n")
    git(repo, "commit", "-am", "weaken")
    clone = tmp_path / "shallow-clone"
    subprocess.run(["git", "clone", "--depth", "1", "--no-local", repo.as_uri(), str(clone)],
                   check=True, capture_output=True, timeout=60)
    assert git(clone, "rev-parse", "--is-shallow-repository").strip() == b"true"
    assert len(git(clone, "rev-list", "--parents", "-n", "1", "HEAD").split()) == 1
    result = sweep(str(clone), "HEAD", 2, datetime.date(2026, 1, 1))
    assert (result.commits, result.errors, result.skipped) == (0, 1, 0)


@pytest.mark.parametrize("raw", [b"abc\n", b"a" * 40, b"g" * 40 + b"\n", b"a" * 40 + b"\n" + b"b" * 40 + b"\n"])
def test_snapshot_rejects_unbound_revision_output(monkeypatch, raw):
    def response(argv, **kwargs):
        assert "rev-parse" in argv, "no source command may use the invalid identity"
        return subprocess.CompletedProcess(argv, 0, raw, b"")

    monkeypatch.setattr(subprocess, "run", response)
    with pytest.raises(EngineError, match="resolved commit"):
        snapshots.GitSnapshot("unused", "HEAD").list_paths()


def test_three_dot_cli_freezes_endpoints_before_merge_base(repo, monkeypatch, capsys):
    from checkwash import cli

    first = git(repo, "rev-parse", "HEAD").decode().strip()
    (repo / "test_example.py").write_bytes(b"def test_example():\n    assert True\n")
    git(repo, "commit", "-am", "weaken")
    second = git(repo, "rev-parse", "HEAD").decode().strip()
    git(repo, "branch", "left", second)
    git(repo, "branch", "right", first)
    original_merge, original_changes = cli.merge_base, cli.list_range_changes
    seen = []

    def move_after_merge(repo_arg, left, right):
        base = original_merge(repo_arg, left, right)
        seen.append((left, right))
        git(repo, "update-ref", "refs/heads/right", second)
        return base

    def capture_changes(repo_arg, base, head):
        seen.append((base, head))
        return original_changes(repo_arg, base, head)

    monkeypatch.setattr(cli, "merge_base", move_after_merge)
    monkeypatch.setattr(cli, "list_range_changes", capture_changes)
    assert cli.main(["check", "left...right", "--repo", str(repo), "--format", "json"]) == 0
    assert seen == [(second, first), (first, first)]
    assert git(repo, "rev-parse", "right").decode().strip() == second
    capsys.readouterr()


def test_worktree_cli_uses_one_committed_baseline_after_head_moves(repo, monkeypatch, capsys):
    from checkwash import cli

    control = repo / ".checkwash" / "config.toml"
    control.parent.mkdir()
    control.write_bytes(b"# baseline A\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "baseline A")
    first = git(repo, "rev-parse", "HEAD").decode().strip()
    control.write_bytes(b"# baseline B\n")
    git(repo, "commit", "-am", "baseline B")
    second = git(repo, "rev-parse", "HEAD").decode().strip()
    git(repo, "reset", "--hard", first)
    (repo / "test_example.py").write_bytes(b"def test_example():\n    assert True\n")
    original_changes, original_config, original_file = cli.list_worktree_changes, cli.read_base_config_file, cli.read_base_file
    versions, config_bytes = [], []

    def move_after_changes(repo_arg, *, base=None):
        assert base == first
        changes = original_changes(repo_arg, base=base)
        git(repo, "update-ref", "HEAD", second)
        return changes

    def config(repo_arg, revision, name):
        versions.append(revision)
        value = original_config(repo_arg, revision, name)
        if name == "config.toml":
            config_bytes.append(value[1])
        return value

    def manifest(repo_arg, revision, path):
        versions.append(revision)
        return original_file(repo_arg, revision, path)

    monkeypatch.setattr(cli, "list_worktree_changes", move_after_changes)
    monkeypatch.setattr(cli, "read_base_config_file", config)
    monkeypatch.setattr(cli, "read_base_file", manifest)
    assert cli.main(["check", "--repo", str(repo), "--format", "json"]) in {0, 1}
    assert versions and set(versions) == {first}
    assert config_bytes == [b"# baseline A\n"]
    assert git(repo, "rev-parse", "HEAD").decode().strip() == second
    capsys.readouterr()


def test_worktree_head_movement_during_status_has_no_verdict(repo, monkeypatch, capsys):
    from checkwash import cli

    first = git(repo, "rev-parse", "HEAD").decode().strip()
    (repo / "test_example.py").write_bytes(b"def test_example():\n    assert True\n")
    git(repo, "commit", "-am", "weaken")
    second = git(repo, "rev-parse", "HEAD").decode().strip()
    git(repo, "reset", "--hard", first)
    original = subprocess.run
    injections = []

    def inject(argv, **kwargs):
        result = original(argv, **kwargs)
        if "status" in argv and "--porcelain" in argv:
            git(repo, "update-ref", "HEAD", second)
            injections.append(True)
        return result

    monkeypatch.setattr(subprocess, "run", inject)
    assert cli.main(["check", "--repo", str(repo), "--format", "json"]) == 2
    assert injections == [True] and not capsys.readouterr().out.strip()


@pytest.mark.parametrize("raw", [b"", b"\0"])
def test_root_importer_discovery_fault_has_no_cli_verdict(repo, monkeypatch, capsys, raw):
    from checkwash import cli

    helper = repo / "test_helpers.py"
    helper.write_bytes(b"def check(value):\n    assert value == 1\n")
    (repo / "test_example.py").write_bytes(b"from test_helpers import check\n\ndef test_example():\n    check(1)\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "helper caller")
    helper.write_bytes(b"def check(value):\n    assert True\n")
    git(repo, "commit", "-am", "weaken helper")
    original = subprocess.run
    injections = []

    def inject(argv, **kwargs):
        if "grep" in argv and argv[-1] == "*.py":
            injections.append(True)
            return subprocess.CompletedProcess(argv, 0, raw, b"")
        return original(argv, **kwargs)

    monkeypatch.setattr(subprocess, "run", inject)
    assert cli.main(["check", "HEAD~1..HEAD", "--repo", str(repo), "--format", "json"]) == 2
    assert injections and not capsys.readouterr().out.strip()


@pytest.mark.parametrize("raw", [b"\0", b"100644 blob invalid 1\ttest_example.py\0", b"100644 blob " + b"a" * 40 + b" 1\ttest_example.py"])
def test_malformed_inventory_cannot_return_none_for_present_source(repo, monkeypatch, raw):
    original = subprocess.run

    def inject(argv, **kwargs):
        if "ls-tree" in argv:
            return subprocess.CompletedProcess(argv, 0, raw, b"")
        return original(argv, **kwargs)

    monkeypatch.setattr(subprocess, "run", inject)
    with pytest.raises(GitError):
        gitio.read_blobs(str(repo), [("HEAD", "test_example.py")])


@pytest.mark.parametrize("operation", ["untracked", "staged"])
def test_worktree_status_keeps_untracked_and_staged(repo, operation):
    (repo / "new_test.py").write_bytes(b"def test_new():\n    assert True\n")
    if operation == "staged":
        git(repo, "add", "new_test.py")
    changes = gitio.list_worktree_changes(str(repo))
    assert len(changes) == 1 and changes[0].path == "new_test.py" and changes[0].status == "added"

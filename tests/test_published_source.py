"""Owned identities exercise the same validator used by publication jobs.

These repositories and remotes belong to this test; no real tag is fabricated,
no existing fixture label changes, and no Checkwash runtime is imported here.
"""
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("published_source", ROOT / "tools/verify_published_source.py")
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


def git(repo, *args):
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True)
    return result.stdout.decode("ascii").strip()


@pytest.fixture
def release(tmp_path):
    repo, remote = tmp_path / "source", tmp_path / "remote.git"
    repo.mkdir()
    remote.mkdir()
    git(repo, "init")
    git(repo, "config", "user.name", "Owned identity fixture")
    git(repo, "config", "user.email", "fixture@example.invalid")
    git(repo, "config", "core.autocrlf", "false")
    git(repo, "config", "commit.gpgsign", "false")
    git(repo, "config", "tag.gpgsign", "false")
    files = {
        "src/checkwash/__init__.py": '__version__ = "1.2.3"\n',
        "src/checkwash/cli.py": "# synthetic runtime\n",
        "pyproject.toml": '[project]\nname="checkwash"\nversion="1.2.3"\n',
        "action/action.yml": "name: synthetic\n",
        "action/post_review.py": "# synthetic existing action driver\n",
        ".pre-commit-hooks.yaml": "[]\n",
        "README.md": "Synthetic fixture; no product runtime.\n",
    }
    for name, text in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "owned release")
    commit = git(repo, "rev-parse", "HEAD")
    git(repo, "tag", "-a", "v1.2.3", "-m", "owned release")
    git(remote, "init", "--bare")
    git(repo, "push", str(remote), "refs/tags/v1.2.3")
    return repo, dict(tag="v1.2.3", expected_commit=commit, source_sha=commit,
                      remote=str(remote), expected_tag_object=git(repo, "rev-parse", "refs/tags/v1.2.3"))


def failed(result, fragment):
    assert result["status"] == "failed", result
    assert any(fragment in error for error in result["errors"]), result


def test_exact_native_tag_and_all_public_surfaces_pass(release):
    repo, identity = release
    result = validator.verify(repo, **identity)
    assert result["status"] == "passed", result
    assert result["source_commit"] == identity["expected_commit"] == result["remote_tag_commit"]
    assert result["tag_object"] == identity["expected_tag_object"] == result["remote_tag_object"]
    assert result["source_tree"] == git(repo, "rev-parse", "HEAD^{tree}")
    assert result["public_surfaces"] == ["src/", "pyproject.toml", "action/", ".pre-commit-hooks.yaml"]
    assert result["errors"] == []


def test_missing_local_tag_is_failure(release):
    repo, identity = release
    git(repo, "tag", "-d", identity["tag"])
    failed(validator.verify(repo, **identity), "git rev-parse failed")


def test_missing_public_tag_is_failure_even_when_local_tag_exists(release):
    repo, identity = release
    git(Path(identity["remote"]), "update-ref", "-d", "refs/tags/" + identity["tag"])
    failed(validator.verify(repo, **identity), "git ls-remote failed")


def test_public_tag_object_cannot_be_replaced(release):
    repo, identity = release
    git(Path(identity["remote"]), "update-ref", "refs/tags/" + identity["tag"], identity["expected_commit"])
    failed(validator.verify(repo, **identity), "remote tag object differs")


def test_wrong_expected_commit_is_failure(release):
    repo, identity = release
    failed(validator.verify(repo, **{**identity, "expected_commit": "f" * 40}), "local tag points to wrong commit")


def test_wrong_checkout_is_failure(release):
    repo, identity = release
    failed(validator.verify(repo, **{**identity, "source_sha": "f" * 40}), "checkout does not match expected source")


@pytest.mark.parametrize("path", ["pyproject.toml", "src/checkwash/__init__.py"])
def test_equal_source_and_tag_with_wrong_version_still_fail(release, path):
    repo, identity = release
    target = repo / path
    target.write_text(target.read_text(encoding="utf-8").replace("1.2.3", "1.2.4"), encoding="utf-8")
    git(repo, "add", path)
    git(repo, "commit", "-m", "wrong release version")
    commit = git(repo, "rev-parse", "HEAD")
    git(repo, "tag", "-f", "-a", identity["tag"], "-m", "wrong version")
    git(repo, "push", "--force", identity["remote"], "refs/tags/" + identity["tag"])
    values = {**identity, "source_sha": commit, "expected_commit": commit,
              "expected_tag_object": git(repo, "rev-parse", "refs/tags/" + identity["tag"])}
    failed(validator.verify(repo, **values), "version differs from tag")


@pytest.mark.parametrize("path", ["src/checkwash/cli.py", "pyproject.toml", "action/action.yml",
                                  "action/post_review.py", "action/secure.py", ".pre-commit-hooks.yaml"])
@pytest.mark.parametrize("committed", [False, True])
def test_each_public_surface_and_new_action_driver_are_checked(release, path, committed):
    repo, identity = release
    with (repo / path).open("a", encoding="utf-8") as stream:
        stream.write("\n# changed public surface\n")
    if committed:
        git(repo, "add", path)
        git(repo, "commit", "-m", "candidate public change")
        identity = {**identity, "source_sha": git(repo, "rev-parse", "HEAD")}
    failed(validator.verify(repo, **identity), "git diff failed" if committed else "dirty or untracked public surface")


def test_documentation_only_commit_is_not_misrepresented_as_public_change(release):
    repo, identity = release
    (repo / "README.md").write_text("Documentation only.\n", encoding="utf-8")
    git(repo, "add", "README.md")
    git(repo, "commit", "-m", "documentation only")
    result = validator.verify(repo, **{**identity, "source_sha": git(repo, "rev-parse", "HEAD")})
    assert result["status"] == "passed", result
    assert result["source_commit"] != result["tag_commit"]  # receipts retain both subjects


@pytest.mark.parametrize("command", ["rev-parse", "show", "ls-tree", "diff", "status", "ls-remote"])
def test_every_git_failure_is_error_even_with_empty_stdout(release, monkeypatch, command):
    repo, identity = release
    run = validator.subprocess.run

    def fault(args, **kwargs):
        if command in args:
            return subprocess.CompletedProcess(args, 128, b"", b"owned git failure")
        return run(args, **kwargs)

    monkeypatch.setattr(validator.subprocess, "run", fault)
    failed(validator.verify(repo, **identity), f"git {command} failed (128)")


@pytest.mark.parametrize("raw", [b"", b"not-an-oid\trefs/tags/v1.2.3\n",
                               (b"a" * 40 + b"\trefs/tags/v1.2.3\n") * 2])
def test_empty_malformed_or_duplicate_remote_response_cannot_pass(release, monkeypatch, raw):
    repo, identity = release
    original = validator.git

    def fault(root, *args):
        return raw if args[0] == "ls-remote" else original(root, *args)

    monkeypatch.setattr(validator, "git", fault)
    result = validator.verify(repo, **identity)
    assert result["status"] == "failed" and result["errors"], result


def test_cli_failure_writes_receipt_and_returns_nonzero(release, tmp_path):
    repo, identity = release
    output = tmp_path / "receipt.json"
    git(repo, "tag", "-d", identity["tag"])
    code = validator.main(["--repo", str(repo), "--tag", identity["tag"],
                           "--expected-commit", identity["expected_commit"],
                           "--source-sha", identity["source_sha"], "--remote", identity["remote"],
                           "--output", str(output)])
    assert code == 1
    failed(json.loads(output.read_text(encoding="utf-8")), "git rev-parse failed")


def test_advertised_manifest_records_publication_receipt_identity():
    manifest = validator.advertised(ROOT / "release/advertised.toml")
    release = manifest["release"]
    record = (ROOT / "docs/releases" / (release["tag"] + "-publication-verification.md")).read_text(encoding="utf-8")
    for value in (release["commit"], release["tag_object"], manifest["pyz"]["sha256"]):
        assert value in record
    assert str(manifest["pyz"]["bytes"]) in record.replace(",", "")


def test_state_separately_labels_published_release_identity():
    release = validator.advertised(ROOT / "release/advertised.toml")["release"]
    state = (ROOT / "STATE.md").read_text(encoding="utf-8")
    assert f"| last published CLI | {release['tag']} |" in state
    assert f"| last published CLI commit | {release['commit']} |" in state

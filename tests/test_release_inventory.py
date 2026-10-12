"""Owned synthetic archives test the actual release inventory fail-closed path.

No product build or assertion engine is needed for these identity-unit tests.
The real qualification workflow separately executes the real product contract.
"""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("release_inventory_under_test", ROOT / "tools/release_inventory.py")
inventory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inventory)


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                          check=True).stdout.decode("ascii").strip()


@pytest.fixture
def subject(tmp_path, monkeypatch):
    repo = tmp_path / "source"
    repo.mkdir()
    git(repo, "init")
    for key, value in {"user.name": "Owned archive fixture", "user.email": "fixture@example.invalid",
                       "core.autocrlf": "false", "commit.gpgsign": "false"}.items():
        git(repo, "config", key, value)
    files = {
        "src/checkwash/__init__.py": b'__version__ = "1.2.3"\n',
        "src/checkwash/cli.py": b"# synthetic package bytes, not product code\n",
        "pyproject.toml": (b'[project]\nname="checkwash"\nversion="1.2.3"\n'
                           b'requires-python=">=3.11"\ndependencies=[]\n'
                           b'[project.scripts]\ncheckwash="checkwash.cli:main"\n'),
    }
    for name, raw in files.items():
        target = repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    git(repo, "add", ".")
    git(repo, "commit", "-m", "owned archive source")
    source = git(repo, "rev-parse", "HEAD")
    monkeypatch.setattr(inventory, "ROOT", repo)
    monkeypatch.setattr(inventory, "BUILDER_ROOT", repo)
    monkeypatch.setenv("ENGINE_SOURCE", source)
    return repo, source, files


def archives(tmp_path, files):
    package = {name.removeprefix("src/"): raw for name, raw in files.items() if name.startswith("src/")}
    pyz, wheel, sdist = (tmp_path / "checkwash.pyz", tmp_path / "checkwash-1.2.3-py3-none-any.whl",
                         tmp_path / "checkwash-1.2.3.tar.gz")
    for target, members in [
        (pyz, {**package, "__main__.py": inventory.ENTRY}),
        (wheel, {**package,
                 "checkwash-1.2.3.dist-info/entry_points.txt": b"[console_scripts]\ncheckwash=checkwash.cli:main\n",
                 "checkwash-1.2.3.dist-info/METADATA": b"Name: checkwash\nVersion: 1.2.3\nRequires-Python: >=3.11\n\n"}),
    ]:
        with zipfile.ZipFile(target, "w") as archive:
            for name, raw in members.items():
                archive.writestr(name, raw)
    with tarfile.open(sdist, "w:gz") as archive:
        for name, raw in {**files, "PKG-INFO": b"Name: checkwash\nVersion: 1.2.3\nRequires-Python: >=3.11\n\n"}.items():
            info = tarfile.TarInfo("checkwash-1.2.3/" + name)
            info.size = len(raw)
            archive.addfile(info, io.BytesIO(raw))
    return pyz, wheel, sdist


def execute(tmp_path, subject, monkeypatch, distribution, artifacts, *, qualified_digest=None, qualification_source=None):
    repo, source, _ = subject
    qualification = tmp_path / "qualification.json"
    data = dict(status="passed", source_commit=qualification_source or source, distribution=distribution)
    if distribution != "source":
        data["artifact_sha256"] = qualified_digest or hashlib.sha256(artifacts[0].read_bytes()).hexdigest()
    qualification.write_text(json.dumps(data), encoding="utf-8")
    output = tmp_path / "inventory.json"
    argv = ["release_inventory.py", "--source-root", str(repo), "--distribution", distribution,
            "--qualification", str(qualification), "--output", str(output)]
    for path in artifacts:
        argv.extend(["--artifact", str(path)])
    monkeypatch.setattr(sys, "argv", argv)
    code = inventory.main()
    return code, json.loads(output.read_text(encoding="utf-8"))


@pytest.mark.parametrize("distribution", ["source", "wheel", "pyz"])
def test_exact_owned_source_and_archives_pass(subject, tmp_path, monkeypatch, distribution):
    pyz, wheel, sdist = archives(tmp_path, subject[2])
    artifacts = {"source": [], "wheel": [wheel, sdist], "pyz": [pyz]}[distribution]
    code, receipt = execute(tmp_path, subject, monkeypatch, distribution, artifacts)
    assert code == 0 and receipt["status"] == "passed", receipt
    assert receipt["source_commit"] == subject[1]
    assert len(receipt["artifacts"]) == len(artifacts)


@pytest.mark.parametrize("distribution", ["wheel", "pyz"])
def test_same_version_stale_archive_fails_identity(subject, tmp_path, monkeypatch, distribution):
    stale = {**subject[2], "src/checkwash/cli.py": b"# same version, different runtime bytes\n"}
    pyz, wheel, sdist = archives(tmp_path, stale)
    code, receipt = execute(tmp_path, subject, monkeypatch, distribution,
                            [pyz] if distribution == "pyz" else [wheel, sdist])
    assert code == 1 and receipt["status"] == "failed"
    assert "artifact package bytes differ" in " ".join(receipt["errors"])


def test_post_qualification_artifact_substitution_fails(subject, tmp_path, monkeypatch):
    pyz, _, _ = archives(tmp_path, subject[2])
    original_digest = hashlib.sha256(pyz.read_bytes()).hexdigest()
    # Same member bytes remain valid, but delivered archive bytes are different.
    with zipfile.ZipFile(pyz, "a") as archive:
        archive.comment = b"owned post-qualification substitution"
    code, receipt = execute(tmp_path, subject, monkeypatch, "pyz", [pyz], qualified_digest=original_digest)
    assert code == 1 and "differs from qualification" in " ".join(receipt["errors"])


@pytest.mark.parametrize("fault", ["missing", "malformed", "extra_member", "missing_sdist", "wrong_qualification_source"])
def test_missing_or_bad_delivery_cannot_pass(subject, tmp_path, monkeypatch, fault):
    pyz, wheel, _ = archives(tmp_path, subject[2])
    digest = hashlib.sha256(pyz.read_bytes()).hexdigest()
    kwargs = {}
    distribution, selected = "pyz", [pyz]
    if fault == "missing":
        pyz.unlink()
    elif fault == "malformed":
        pyz.write_bytes(b"not a ZIP")
    elif fault == "extra_member":
        with zipfile.ZipFile(pyz, "a") as archive:
            archive.writestr("unreviewed.py", b"# extra runtime\n")
    elif fault == "missing_sdist":
        distribution, selected = "wheel", [wheel]
        digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    else:
        kwargs["qualification_source"] = "f" * 40
    code, receipt = execute(tmp_path, subject, monkeypatch, distribution, selected,
                            qualified_digest=digest, **kwargs)
    assert code == 1 and receipt["status"] == "failed" and receipt["errors"], receipt


def test_git_error_with_empty_output_fails_inventory(subject, tmp_path, monkeypatch):
    original = inventory.subprocess.run

    def fail_diff(args, **kwargs):
        if "diff" in args:
            return subprocess.CompletedProcess(args, 128, b"", b"owned Git failure")
        return original(args, **kwargs)

    monkeypatch.setattr(inventory.subprocess, "run", fail_diff)
    code, receipt = execute(tmp_path, subject, monkeypatch, "source", [])
    assert code == 1 and "Git inventory command failed" in " ".join(receipt["errors"])

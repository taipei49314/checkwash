"""Conftest stand-ins resolve against unchanged repository modules."""

import datetime
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import EngineError, FileChange, analyze


PRODUCTION = b"def total():\n    return 0\n"
PATCH = b'''import pytest
import pricing

@pytest.fixture(autouse=True)
def fix(monkeypatch):
    monkeypatch.setattr(pricing, "total", lambda: 5)
'''


def run(source=PATCH, *, before=None, head=None, extra=(), reader=None):
    changes = [FileChange("tests/conftest.py", "added" if before is None else "modified", before, source), *extra]
    return analyze(changes, Config(), Contract(), [], datetime.date(2026, 9, 6),
                   root_reader=reader if reader is not None else (head or {"pricing.py": PRODUCTION}).get)


@pytest.mark.parametrize("path", ["pricing.py", "src/pricing.py", "pricing/__init__.py", "src/pricing/__init__.py"])
def test_conftest_only_patch_of_unchanged_module_blocks(path):
    _ir, findings, verdict = run(head={path: PRODUCTION})
    assert verdict == "block"
    assert [f.rule for f in findings] == ["CONFTEST_PATCHES_PROD"]


@pytest.mark.parametrize("source", [
    PATCH.replace(b'monkeypatch.setattr(pricing, "total",', b'monkeypatch.setattr("pricing.total",'),
    PATCH.replace(b"import pricing", b"import pricing as subject").replace(b"setattr(pricing,", b"setattr(subject,"),
    PATCH.replace(b"import pricing", b"from pricing import Total as subject").replace(b"setattr(pricing,", b"setattr(subject,"),
    PATCH.replace(b"import pricing\n", b"").replace(b"    monkeypatch.setattr", b"    import pricing\n    monkeypatch.setattr"),
    PATCH.replace(b"import pytest", b"import pytest as pt").replace(b"@pytest.fixture", b"@pt.fixture"),
    PATCH.replace(b"import pytest", b"from pytest import fixture as fixture_alias").replace(b"@pytest.fixture", b"@fixture_alias"),
    PATCH.replace(b"def fix(monkeypatch):", b"def fix():\n    monkeypatch = pytest.MonkeyPatch()"),
])
def test_first_party_target_spellings(source):
    assert run(source)[2] == "block"


@pytest.mark.parametrize("source", [
    PATCH.replace(b"pricing", b"requests"),
    PATCH.replace(b"pricing", b"time"),
    PATCH.replace(b'import pricing', b'import requests as pricing'),
    PATCH.replace(b'import pricing', b'pricing = object()'),
    PATCH.replace(b'    monkeypatch.setattr', b'    pricing = object()\n    monkeypatch.setattr'),
    PATCH + b"\npricing = object()\n",
    PATCH.replace(b'fix(monkeypatch)', b'fix(monkeypatch, pricing)'),
    PATCH.replace(b'    monkeypatch.setattr', b'    monkeypatch = object()\n    monkeypatch.setattr'),
    PATCH.replace(b'@pytest.fixture(autouse=True)\n', b''),
    PATCH.replace(b'@pytest.fixture(autouse=True)', b'@someone.fixture(autouse=True)'),
    PATCH + b'\n@pytest.fixture\ndef monkeypatch():\n    return object()\n',
    PATCH.replace(b'    monkeypatch.setattr(pricing, "total", lambda: 5)', b'    callback = lambda monkeypatch: monkeypatch.setattr(pricing, "total", 5)'),
    PATCH.replace(b'    monkeypatch.setattr(pricing, "total", lambda: 5)', b'    values = [monkeypatch.setattr(pricing, "total", 5) for monkeypatch in custom_objects]'),
])
def test_unproven_or_external_objects_are_not_first_party_patchers(source):
    _ir, findings, _verdict = run(source)
    assert not any(f.rule == "CONFTEST_PATCHES_PROD" for f in findings)


def test_unchanged_patch_does_not_create_a_new_finding():
    assert run(PATCH + b"\n# harmless comment\n", before=PATCH)[1] == []


def test_import_rebinding_to_local_target_is_a_new_patch():
    before = PATCH.replace(b"import pricing", b"import requests as pricing")
    assert run(before=before)[2] == "block"


def test_request_module_requires_real_request_fixture_parameter():
    real = PATCH.replace(b"import pricing\n", b"").replace(b"fix(monkeypatch)", b"fix(monkeypatch, request)").replace(b"setattr(pricing,", b"setattr(request.module,")
    assert run(real)[2] == "block"
    fake = real.replace(b"    monkeypatch.setattr", b"    request = object()\n    monkeypatch.setattr")
    assert not any(f.rule == "CONFTEST_PATCHES_PROD" for f in run(fake)[1])


def test_production_comment_and_path_order_do_not_determine_target_identity():
    for filename in ("pricing.py", "zzz/pricing.py"):
        changes = [FileChange(filename, "modified", PRODUCTION, PRODUCTION + b"# comment\n")]
        assert run(extra=changes)[2] == "block"


def test_missing_snapshot_and_failed_snapshot_are_engine_errors():
    with pytest.raises(EngineError, match="strict snapshot reader"):
        analyze([FileChange("conftest.py", "added", None, PATCH)], Config(), Contract(), [], datetime.date(2026, 9, 6))

    def failed(path):
        raise EngineError("unreadable source")

    with pytest.raises(EngineError, match="unreadable source"):
        run(reader=failed)


def test_snapshot_read_budget_cannot_silently_drop_target():
    source = b"import pytest\n@pytest.fixture\ndef f(monkeypatch):\n" + b"".join(
        f'    monkeypatch.setattr("external_{i}.fn", lambda: 0)\n'.encode() for i in range(33)
    )
    with pytest.raises(EngineError, match="snapshot read budget"):
        run(source, reader={}.get)


def test_changed_target_uses_its_own_snapshot_side():
    before = PATCH.replace(b"pricing", b"new_product")
    added = FileChange("new_product.py", "added", None, PRODUCTION)
    assert run(before, before=before, extra=[added], reader={}.get)[2] == "block"


def test_module_rename_preserves_preexisting_patch_identity():
    renamed = FileChange("billing.py", "modified", PRODUCTION, PRODUCTION, old_path="pricing.py")
    after = PATCH.replace(b"import pricing", b"import billing as pricing")
    assert run(after, before=PATCH, extra=[renamed], reader={"billing.py": PRODUCTION}.get)[1] == []


def test_relative_import_target_is_resolved_in_its_conftest_package():
    assert run(PATCH.replace(b"import pricing", b"from . import pricing"), head={"tests/pricing.py": PRODUCTION})[2] == "block"


def test_invalid_snapshot_value_cannot_prove_module_identity():
    with pytest.raises(EngineError, match="invalid source bytes"):
        run(reader=lambda path: False)


def git(repo, *args):
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True)
    return result.stdout.decode().strip()


@pytest.mark.parametrize("mode", ["worktree", "range"])
def test_real_pytest_standin_is_blocked_without_production_diff(tmp_path, mode, patch_source=PATCH):
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "config", "user.name", "checkwash-test")
    git(tmp_path, "config", "user.email", "test@example.invalid")
    git(tmp_path, "config", "commit.gpgsign", "false")
    (tmp_path / "pricing.py").write_bytes(PRODUCTION)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_pricing.py").write_text("import pricing\n\ndef test_total():\n    assert pricing.total() == 5\n", encoding="utf-8")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-m", "base")
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
    baseline = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=tmp_path, env=env, capture_output=True)
    assert baseline.returncode == 1
    assert b"assert 0 == 5" in baseline.stdout
    (tmp_path / "tests/conftest.py").write_bytes(patch_source)
    repaired = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=tmp_path, env=env, capture_output=True)
    assert repaired.returncode == 0, repaired.stdout
    assert b"1 passed" in repaired.stdout
    args = []
    if mode == "range":
        git(tmp_path, "add", "tests/conftest.py")
        git(tmp_path, "commit", "-m", "stand-in")
        args = ["HEAD~1..HEAD"]
    checked = subprocess.run([sys.executable, "-m", "checkwash", "check", *args, "--repo", str(tmp_path), "--format", "json"], env=env, capture_output=True)
    assert checked.returncode == 1, checked.stderr
    report = json.loads(checked.stdout)
    assert report["verdict"] == "block"
    assert any(f["rule"] == "CONFTEST_PATCHES_PROD" for f in report["findings"])

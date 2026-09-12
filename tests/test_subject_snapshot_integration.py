"""T-326: strict adapter and relative-import boundaries (pool execution only)."""

import datetime
import subprocess

import pytest

from checkwash.change import EngineError, FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.gitio.snapshot import GitSnapshot, WorkingTreeSnapshot
from checkwash.shadow import (
    HeadSearchResult, _ShadowAnalysisCache, _active_test_imports,
    _complete_head_search, _source_package,
    _source_key,
)


@pytest.mark.parametrize("statement,package,wanted", [
    ("from .billing import total", "app", "app.billing"),
    ("from ..billing import total", "app.tests", "app.billing"),
    ("from . import billing as total", "app", "app.billing"),
])
def test_relative_subject_imports_have_a_proven_package(statement, package, wanted):
    data = f"{statement}\ndef test_total():\n    assert total() == 3\n".encode()
    assert wanted in _active_test_imports(data, package=package)
    assert not _active_test_imports(data)


def test_import_cache_separates_identical_bytes_in_different_packages():
    data = b"from .billing import total\ndef test_total():\n    assert total() == 3\n"
    cache = _ShadowAnalysisCache()
    assert "alpha.billing" in cache.active_test_imports(data, package="alpha")
    assert "beta.billing" in cache.active_test_imports(data, package="beta")
    assert "alpha.billing" not in cache.active_test_imports(data, package="beta")


def test_provider_identity_honors_python_encoding_cookies():
    before = b"# coding: latin1\nVALUE = '\xe9'\n"
    after = b"# coding: latin1\nVALUE = '\xea'\n"
    assert _source_key(before) != _source_key(after)


def test_relative_import_cannot_climb_above_its_known_package():
    source = b"from ..billing import total\ndef test_total():\n    assert total() == 3\n"
    assert not _active_test_imports(source, package="app")


def test_unused_relative_import_is_not_a_live_subject():
    source = b"from .billing import total\ndef test_other():\n    assert 3 == 3\n"
    assert not _active_test_imports(source, package="app")


@pytest.mark.parametrize("bad", ["../tests/test_total.py", "/tests/test_total.py", "C:/tests/test_total.py", None])
def test_shadow_rejects_unrepresentable_inventory_paths(bad):
    from checkwash.shadow import find_runtime_subject_shadows
    with pytest.raises(EngineError, match="inventory returned an unsafe path"):
        find_runtime_subject_shadows(
            [FileChange("tests/src/billing.py", "added", None, b"def total(): return 3\n")], Config(),
            head_path_lister=lambda: [bad], head_batch_reader=lambda paths: {},
        )


def test_empty_initializers_establish_relative_package_context():
    assert _source_package("tests/app/test_x.py", ["tests/app/__init__.py"]) == "app"
    assert _source_package("tests/app/test_x.py", []) == ""


def test_complete_import_search_includes_relative_name_components():
    needles_seen = []

    def search(needles):
        needles_seen.extend(needles)
        return HeadSearchResult(("app/test_total.py",), complete=True)

    assert _complete_head_search(search, ["app.billing"]) == {"app/test_total.py"}
    assert "billing" in needles_seen


def test_snapshots_inventory_empty_sources_controls_and_exact_bytes(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    files = {"app/__init__.py": b"", "pytest.ini": b"[pytest]\r\npythonpath=src\r\n",
             "app/billing.py": b"def total():\n    return 3\n"}
    for name, data in files.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    # This temporary repository records exact fixture bytes, independent of
    # the runner's global newline-conversion setting.
    subprocess.run(["git", "-C", str(tmp_path), "-c", "core.autocrlf=false", "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                    "commit", "-qm", "snapshot"], check=True)
    for snapshot in (WorkingTreeSnapshot(tmp_path), GitSnapshot(tmp_path, "HEAD")):
        assert snapshot.list_paths() == sorted(files)
        assert snapshot.read_many(sorted(files)) == files
        assert snapshot.read_many(["absent.py"]) == {"absent.py": None}


def test_equivalent_provider_does_not_excuse_an_assertion_weakening():
    source = b"def total():\n    return 3\n"
    before_test = b"from app.billing import total\ndef test_total():\n    assert total() == 3\n"
    after_test = b"from app.billing import total\ndef test_total():\n    assert total()\n"
    snapshot = {"src/app/__init__.py": b"", "src/app/billing.py": source,
                "app/__init__.py": b"", "app/billing.py": source,
                "tests/test_total.py": after_test,
                "pytest.ini": b"[pytest]\npythonpath = . src\n"}
    changes = [FileChange("app/__init__.py", "added", None, b""),
               FileChange("app/billing.py", "added", None, source),
               FileChange("tests/test_total.py", "modified", before_test, after_test),
               FileChange("pytest.ini", "modified", b"[pytest]\npythonpath = src\n", snapshot["pytest.ini"])]
    _ir, findings, _verdict = analyze(
        changes, Config(), Contract(), [], datetime.date(2026, 9, 12),
        root_reader=snapshot.get, root_path_lister=lambda: sorted(snapshot),
        root_batch_reader=lambda paths: {path: snapshot.get(path) for path in paths},
    )
    assert not [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    weakened = [f for f in findings if f.rule == "ASSERT_WEAKENED"]
    assert len(weakened) == 1 and weakened[0].severity == "high"
    assert not set(weakened[0].deescalators) & {"REPAIR_EVIDENCE", "PACKAGE_REPAIR"}


def test_shadow_inventory_missing_a_selected_source_fails_closed():
    from checkwash.shadow import find_runtime_subject_shadows
    changes = [FileChange("tests/src/billing.py", "added", None, b"def total(): return 3\n")]
    with pytest.raises(EngineError, match="snapshot read failed"):
        find_runtime_subject_shadows(
            changes, Config(),
            head_path_lister=lambda: ["src/billing.py", "tests/src/billing.py", "tests/test_total.py"],
            head_batch_reader=lambda paths: {path: None for path in paths},
        )


def test_shadow_inventory_requires_its_matching_byte_reader():
    from checkwash.shadow import find_runtime_subject_shadows
    with pytest.raises(EngineError, match="requires both path and byte readers"):
        find_runtime_subject_shadows(
            [FileChange("tests/src/billing.py", "added", None, b"def total(): return 3\n")], Config(),
            head_path_lister=lambda: ["tests/src/billing.py"],
        )

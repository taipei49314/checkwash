"""Collection changes must preserve migration and broadening controls."""
import datetime
import pytest

from checkwash.change import FileChange
from checkwash.engine import analyze
from checkwash.config import Config
from checkwash.contract import Contract


def run(changes):
    return analyze(changes, Config(), Contract(), [], datetime.date(2026, 9, 12))[1]


def findings(before, after, path="pytest.ini"):
    return [f for f in run([FileChange(path, "modified", before.encode(), after.encode())]) if f.rule == "CI_WORKFLOW_TOUCHED"]


@pytest.mark.parametrize("option", ["--co", "--collect-only", "--ignore-glob=test_*.py", "--ignore-glob test_*.py", "-k public"])
def test_added_collection_option_blocks(option):
    hits = findings("[pytest]\naddopts = -q\n", "[pytest]\naddopts = -q " + option + "\n")
    assert len(hits) == 1 and hits[0].severity == "high"


@pytest.mark.parametrize("before,after", [
    ("testpaths = tests", "testpaths = tests/unit"),
    ("testpaths = tests/unit tests/integration", "testpaths = tests/unit"),
    ("python_files = test_*.py", "python_files = test_public_*.py"),
    ('testpaths = ["tests", "checks"]', 'testpaths = ["tests"]'),
    ("testpaths =\n    tests/unit\n    tests/integration", "testpaths =\n    tests/unit"),
])
def test_existing_collection_value_can_narrow(before, after):
    hits = findings("[pytest]\n" + before, "[pytest]\n" + after)
    assert hits and hits[0].severity == "high"


@pytest.mark.parametrize("before,after", [
    ("testpaths = tests/unit", "testpaths = tests"),
    ("testpaths = tests", "testpaths = tests checks"),
    ("python_files = test_public_*.py", "python_files = test_*.py"),
    ('addopts = -q -k "not slow"', 'addopts = -q -k "not slow"\n# comment'),
    ("testpaths = tests checks", "testpaths = checks tests"),
])
def test_broadened_or_repeated_collection_stays_warn(before, after):
    hits = findings("[pytest]\n" + before, "[pytest]\n" + after)
    assert all(f.severity == "warn" for f in hits)


def test_migrated_equal_configuration_stays_warn():
    result = run([
        FileChange("setup.cfg", "deleted", b"[tool:pytest]\ntestpaths = tests\naddopts = -k public\n", None),
        FileChange("pyproject.toml", "added", None, b'[tool.pytest.ini_options]\ntestpaths = ["tests"]\naddopts = "-k public"\n'),
    ])
    assert all(f.severity == "warn" for f in result if f.rule == "CI_WORKFLOW_TOUCHED")


def test_migration_does_not_hide_narrowing():
    result = run([
        FileChange("setup.cfg", "deleted", b"[tool:pytest]\ntestpaths = tests\n", None),
        FileChange("pyproject.toml", "added", None, b'[tool.pytest.ini_options]\ntestpaths = ["tests/unit"]\n'),
    ])
    assert any(f.rule == "CI_WORKFLOW_TOUCHED" and f.severity == "high" for f in result)


def test_python_module_launcher_is_not_a_marker_selector():
    hits = findings("run: pytest\n", "run: python -m pytest\n", ".github/workflows/test.yml")
    assert all(f.severity == "warn" for f in hits)


def test_marker_selector_after_python_launcher_still_blocks():
    hits = findings("run: python -m pytest\n", "run: python -m pytest -m public\n", ".github/workflows/test.yml")
    assert hits and hits[0].severity == "high"


def test_case_sensitive_existing_selector_is_not_new():
    hits = findings("[pytest]\naddopts = -k TestHTTP\n", "[pytest]\naddopts = -k TestHTTP\n# retained\n")
    assert all(f.severity == "warn" for f in hits)

"""A mock.patch constructor alone does not replace production behavior."""

import ast
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from checkwash.frontends.python.conftest_patches import patch_calls
from test_conftest_mock_patch import MOCK_PATCH
from test_conftest_targets import PRODUCTION, git, run, test_real_pytest_standin_is_blocked_without_production_diff as _standin_e2e


@pytest.mark.parametrize("source", [
    b'from unittest.mock import patch\npatch("pricing.total", return_value=5)\n',
    b'from unittest.mock import patch\np = patch("pricing.total", return_value=5)\n',
    b'from unittest.mock import patch\np = patch("pricing.total", return_value=5)\np.stop()\n',
    b'import pricing\nfrom unittest.mock import patch\npatch.object(pricing, "total", return_value=5)\n',
    MOCK_PATCH.replace(b'    with patch("pricing.total", return_value=5):\n        yield',
                       b'    patch("pricing.total", return_value=5)\n    yield'),
])
def test_unused_mock_constructor_is_not_an_active_patch(source):
    assert not any(f.rule == "CONFTEST_PATCHES_PROD" for f in run(source)[1])


@pytest.mark.parametrize("activation", [
    "p.start()",
    "with p:\n    pass",
    "with p as p:\n    pass",
    "with p:\n    p = custom",
    "@p\ndef helper(mock):\n    return mock",
    "alias = p\nalias.start()",
])
@pytest.mark.parametrize("constructor", [
    'patch("pricing.total", return_value=5)',
    'patch.object(pricing, "total", return_value=5)',
])
def test_direct_name_patcher_requires_a_proven_activation(activation, constructor):
    source = f"import pricing\nfrom unittest.mock import patch\np = {constructor}\n{activation}\n".encode()
    assert any(f.rule == "CONFTEST_PATCHES_PROD" for f in run(source)[1])


@pytest.mark.parametrize("rebind", ["p = custom", "del p", "if condition:\n    p = custom"])
def test_rebound_patcher_does_not_borrow_old_constructor(rebind):
    source = f'from unittest.mock import patch\np = patch("pricing.total", return_value=5)\n{rebind}\np.start()\n'.encode()
    assert not any(f.rule == "CONFTEST_PATCHES_PROD" for f in run(source)[1])


def test_unused_constructor_needs_no_target_snapshot_probe():
    def unknown(module):
        raise AssertionError("unused constructor must not request target identity")

    source = 'from unittest.mock import patch\np = patch("pricing.total", return_value=5)\n'
    assert patch_calls(ast.parse(source), source, unknown) == []


@pytest.mark.parametrize("mode", ["range", "worktree"])
def test_real_pytest_named_start_is_still_blocked(tmp_path, mode):
    source = MOCK_PATCH.replace(
        b'    with patch("pricing.total", return_value=5):\n        yield',
        b'    p = patch("pricing.total", return_value=5)\n    p.start()\n    yield\n    p.stop()')
    _standin_e2e(tmp_path, mode, source)


@pytest.mark.parametrize("mode", ["range", "worktree"])
def test_real_pytest_unused_constructor_preserves_the_failure(tmp_path, mode):
    (tmp_path / "tests").mkdir()
    (tmp_path / "pricing.py").write_bytes(PRODUCTION)
    (tmp_path / "tests/test_total.py").write_text(
        "from pricing import total\ndef test_total():\n    assert total() == 5\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n", encoding="utf-8")
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "config", "user.name", "test")
    git(tmp_path, "config", "user.email", "test@example.invalid")
    git(tmp_path, "config", "commit.gpgsign", "false")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-m", "before")
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(tmp_path), str(Path(__file__).resolve().parents[1] / "src")]), "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    before = subprocess.run([sys.executable, "-m", "pytest", "-q", "tests"], cwd=tmp_path, env=env, capture_output=True, timeout=30)
    assert before.returncode == 1 and b"AssertionError" in before.stdout
    (tmp_path / "conftest.py").write_bytes(MOCK_PATCH.replace(
        b'    with patch("pricing.total", return_value=5):\n        yield',
        b'    unused = patch("pricing.total", return_value=5)\n    yield'))
    after = subprocess.run([sys.executable, "-m", "pytest", "-q", "tests"], cwd=tmp_path, env=env, capture_output=True, timeout=30)
    assert after.returncode == 1 and b"AssertionError" in after.stdout
    args = []
    if mode == "range":
        git(tmp_path, "add", "conftest.py")
        git(tmp_path, "commit", "-m", "unused patcher")
        args = ["HEAD~1..HEAD"]
    result = subprocess.run([sys.executable, "-m", "checkwash", "check", *args, "--repo", str(tmp_path), "--format", "json"], env=env, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert not any(f["rule"] == "CONFTEST_PATCHES_PROD" for f in json.loads(result.stdout)["findings"])

"""unittest.mock's import aliases and string/object targets in conftest."""

import pytest

from checkwash.engine import FileChange
from test_conftest_targets import PRODUCTION, run, test_real_pytest_standin_is_blocked_without_production_diff as _standin_e2e


MOCK_PATCH = b'''import pytest
from unittest.mock import patch

@pytest.fixture(autouse=True)
def fix():
    with patch("pricing.total", return_value=5):
        yield
'''


@pytest.mark.parametrize("with_production", [False, True])
def test_conftest_mock_patch_blocks_with_and_without_production_diff(with_production):
    extra = [FileChange("pricing.py", "modified", PRODUCTION, PRODUCTION + b"# docstring control\n")] if with_production else []
    _ir, findings, verdict = run(MOCK_PATCH, extra=extra)
    assert verdict == "block"
    assert [f.rule for f in findings] == ["CONFTEST_PATCHES_PROD"]


@pytest.mark.parametrize("source", [
    MOCK_PATCH,
    MOCK_PATCH.replace(b"from unittest.mock import patch", b"from unittest.mock import patch as replace").replace(b"with patch(", b"with replace("),
    MOCK_PATCH.replace(b"from unittest.mock import patch", b"import unittest.mock as mock").replace(b"with patch(", b"with mock.patch("),
    MOCK_PATCH.replace(b"from unittest.mock import patch", b"from unittest import mock as substitute").replace(b"with patch(", b"with substitute.patch("),
    MOCK_PATCH.replace(b"from unittest.mock import patch", b"import unittest.mock").replace(b"with patch(", b"with unittest.mock.patch("),
    MOCK_PATCH.replace(b"from unittest.mock import patch", b"import pricing\nfrom unittest.mock import patch").replace(b'patch("pricing.total",', b'patch.object(pricing, "total",'),
    MOCK_PATCH.replace(b"from unittest.mock import patch", b"import pricing as p\nfrom unittest.mock import patch as substitute").replace(b'patch("pricing.total",', b'substitute.object(p, "total",'),
    MOCK_PATCH.replace(b"from unittest.mock import patch", b"from pricing import Total as subject\nfrom unittest import mock").replace(b'patch("pricing.total",', b'mock.patch.object(subject, "total",'),
    MOCK_PATCH.replace(b'patch("pricing.total",', b'patch(target="pricing.total",'),
    MOCK_PATCH.replace(b"from unittest.mock import patch", b"import pricing\nfrom unittest.mock import patch").replace(b'patch("pricing.total",', b'patch.object(target=pricing, attribute="total",'),
    MOCK_PATCH.replace(b"from unittest.mock import patch\n", b"").replace(b"    with patch", b"    from unittest.mock import patch\n    with patch"),
    b'from unittest.mock import patch\npatch("pricing.total", return_value=5).start()\n',
    b'import pricing\nfrom unittest.mock import patch\npatch.object(pricing, "total", return_value=5).start()\n',
    b'from unittest.mock import patch\n@patch("pricing.total", return_value=5)\ndef helper(mock):\n    return mock\n',
])
def test_unittest_mock_import_aliases_and_target_spellings(source):
    assert run(source)[2] == "block"


@pytest.mark.parametrize("source", [
    MOCK_PATCH.replace(b"pricing.total", b"requests.get"),
    MOCK_PATCH.replace(b"pricing.total", b"time.time"),
    MOCK_PATCH.replace(b"from unittest.mock import patch", b"from some_library import patch"),
    MOCK_PATCH.replace(b"from unittest.mock import patch", b"def patch(*args, **kwargs):\n    return object()"),
    MOCK_PATCH.replace(b"def fix():", b"def fix(patch):"),
    MOCK_PATCH.replace(b"    with patch", b"    patch = custom_patch\n    with patch"),
    MOCK_PATCH + b"\npatch = custom_patch\n",
    MOCK_PATCH.replace(b"from unittest.mock import patch", b"import requests as pricing\nfrom unittest.mock import patch").replace(b'patch("pricing.total",', b'patch.object(pricing, "get",'),
    MOCK_PATCH.replace(b"from unittest.mock import patch", b"import pricing\nfrom unittest.mock import patch").replace(b'patch("pricing.total",', b'patch.object(pricing, "total",').replace(b"    with patch", b"    pricing = custom_object\n    with patch"),
    MOCK_PATCH.replace(b"from unittest.mock import patch", b"import pricing\nfrom unittest.mock import patch").replace(b'patch("pricing.total",', b'patch.object(pricing, "total",') + b"\npricing = custom_object\n",
    MOCK_PATCH.replace(b'patch("pricing.total",', b'patch.object("pricing.total",'),
    MOCK_PATCH.replace(b'patch("pricing.total",', b'patch(pricing,'),
])
def test_external_targets_and_fake_or_rebound_patchers_stay_silent(source):
    assert not any(f.rule == "CONFTEST_PATCHES_PROD" for f in run(source)[1])


def test_unchanged_mock_patch_remains_silent():
    assert run(MOCK_PATCH + b"\n# comment\n", before=MOCK_PATCH)[1] == []


@pytest.mark.parametrize("mode", ["worktree", "range"])
@pytest.mark.parametrize("patch_source", [
    MOCK_PATCH,
    MOCK_PATCH.replace(b"from unittest.mock import patch", b"import pricing\nfrom unittest.mock import patch").replace(b'patch("pricing.total",', b'patch.object(pricing, "total",'),
])
def test_actual_pytest_mock_standin_is_blocked(tmp_path, mode, patch_source):
    # The same red-to-green repository probe exercises each installation
    # dialect through real pytest, then checks the actual CLI exit code.
    _standin_e2e(tmp_path, mode, patch_source)

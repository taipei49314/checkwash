"""Test-wide guards.

The no-network fixture makes "zero network" a tested claim, not a README
adjective (SPEC §8): any in-process socket creation fails the test.

The local Claude Code hook runs `python -I -c <bootstrap>` bound to the package
under test, and `-I` ignores PYTHONDONTWRITEBYTECODE. The install probe and
every executed local handler therefore compile src/checkwash into __pycache__
beside the source. The session removes the caches it created, so a test run
leaves the published source surface as it found it: the tag-stage source check
refused the v0.9.1 tag on exactly these ignored caches.
"""

from pathlib import Path
import shutil
import socket

import pytest


_SRC = Path(__file__).resolve().parents[1] / "src"
_source_caches_before = None


class _NetworkBlocked(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def _blocked(*args, **kwargs):
        raise _NetworkBlocked("network access is forbidden in checkwash core paths")

    monkeypatch.setattr(socket, "socket", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    yield


def _source_caches():
    return {path for path in _SRC.rglob("__pycache__") if path.is_dir()}


def pytest_sessionstart(session):
    # xdist workers share this checkout. Only the controller, which finishes
    # after every worker, takes the snapshot and cleans up; a nested
    # collect-only run (the documented-count test) leaves it alone.
    global _source_caches_before
    if not hasattr(session.config, "workerinput") and not session.config.option.collectonly:
        _source_caches_before = _source_caches()


def pytest_sessionfinish(session):
    if _source_caches_before is None:
        return
    for path in sorted(_source_caches() - _source_caches_before, reverse=True):
        shutil.rmtree(path, ignore_errors=True)
